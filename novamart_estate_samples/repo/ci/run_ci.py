"""novamart CI: boot the app against a scratch database, exercise core flows.

Usage (run from repo root): python ci/run_ci.py
Env: CI_DSN (scratch postgres), CI_PORT (default 8199).
Exit 0 = green.
"""
import os
import subprocess
import sys
import time

import httpx
import psycopg

DSN = os.environ["CI_DSN"]
PORT = int(os.environ.get("CI_PORT", "8199"))
BASE = f"http://127.0.0.1:{PORT}"
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def fail(msg):
    print(f"CI FAIL: {msg}")
    sys.exit(1)


def main():
    with psycopg.connect(DSN, autocommit=True) as c:
        c.execute(open(os.path.join(REPO, "schema.sql")).read())
        for t in ("payments", "report_rows", "statements", "cart_items", "orders", "products", "users"):
            c.execute(f"TRUNCATE {t} CASCADE")

    env = dict(os.environ, NOVAMART_DSN=DSN, NOVAMART_LOG_DIR=os.path.join(REPO, "ci", "_logs"))
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "novamart.app:app", "--port", str(PORT), "--log-level", "critical"],
        cwd=REPO, env=env)
    try:
        for _ in range(100):
            try:
                httpx.get(f"{BASE}/health", timeout=1)
                break
            except Exception:
                time.sleep(0.2)
        else:
            fail("app never came up")

        ts = "2019-09-21T12:00:00+00:00"
        r = httpx.get(f"{BASE}/products/111", params={"uid": 1, "ts": ts, "session": "ci-s", "price": 10.0})
        if r.status_code != 200:
            fail(f"view: {r.status_code}")
        r = httpx.post(f"{BASE}/cart", json={"uid": 1, "pid": 111, "ts": ts, "session": "ci-s", "price": 10.0})
        if r.status_code != 200:
            fail(f"cart: {r.status_code}")
        r = httpx.post(f"{BASE}/orders", json={"uid": 1, "pid": 111, "ts": ts, "session": "ci-s",
                                               "price": 10.0, "ref": "PR-ci-111"})
        if r.status_code != 200:
            fail(f"order: {r.status_code}")

        with psycopg.connect(DSN) as c:
            orders = c.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
            pays = c.execute("SELECT COUNT(*), COALESCE(SUM(gross),0) FROM payments").fetchone()
            if orders < 1 or pays[0] != orders:
                fail(f"order/payment rows inconsistent: {orders} vs {pays[0]}")

        jobs_env = dict(env, FAKE_NOW="2019-09-22T07:00:00+00:00")
        for mod in ("novamart.jobs.reconcile", "novamart.jobs.daily_report", "novamart.jobs.monthly_statement"):
            rc = subprocess.run([sys.executable, "-m", mod], cwd=REPO, env=jobs_env).returncode
            if rc != 0:
                fail(f"job {mod} exited {rc}")
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
    print("CI OK")


if __name__ == "__main__":
    main()
