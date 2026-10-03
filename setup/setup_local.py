"""One-command local setup: download the estate, start the stack, load, seed, verify.

  python setup/setup_local.py                              # everything, warehouse in the local emulator
  python setup/setup_local.py --no-download                # reuse setup/data/
  python setup/setup_local.py --warehouse-project my-proj  # after setup_gcp.py: Redash and the repo only,
                                                           # access pack points at your BigQuery project

Endpoints when done: BigQuery emulator http://localhost:9050 (project
novamart-warehouse), Redash http://localhost:5050, estate Postgres :5433 (override
with ESTATE_PG_PORT), world repo cloned at setup/workspace/novamart (checked out
at the pin). The access pack in setup/access-pack/ carries all of it.
"""
import argparse, os, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
PIN = "5ae1182"
LOCAL_ONLY = ["estate-pg", "redash-redis", "redash-pg", "redash", "redash-scheduler", "redash-worker"]

def sh(cmd, **kw):
    print("+", " ".join(cmd)); r = subprocess.run(cmd, **kw)
    if r.returncode != 0: sys.exit(f"failed: {' '.join(cmd)}")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-download", action="store_true", help="reuse setup/data/")
    ap.add_argument("--warehouse-project", default=None,
                    help="your BigQuery project (after setup_gcp.py); skips the local emulator")
    ap.add_argument("--skip-verify", action="store_true")
    a = ap.parse_args()
    cloud = a.warehouse_project is not None
    pg_port = os.environ.get("ESTATE_PG_PORT", "5433")

    if not a.no_download:
        sh([sys.executable, os.path.join(HERE, "loaders", "download_data.py")])
    roles = os.path.join(HERE, "data", "roles.sql")
    if not os.path.exists(roles): open(roles, "w").write("-- placeholder for estate roles\n")
    with open(os.path.join(HERE, ".env"), "w") as f:   # read by every docker compose call for this file
        f.write(f"ESTATE_PG_PORT={pg_port}\n")
        if os.environ.get("BQ_EMULATOR_TAG"): f.write(f"BQ_EMULATOR_TAG={os.environ['BQ_EMULATOR_TAG']}\n")
    compose = ["docker", "compose", "-f", os.path.join(HERE, "docker-compose.yml"), "up", "-d"]
    sh(compose + (LOCAL_ONLY if cloud else []))
    ws = os.path.join(HERE, "workspace")
    os.makedirs(ws, exist_ok=True)
    repo = os.path.join(ws, "novamart")
    if not os.path.exists(repo):
        sh(["git", "clone", "https://github.com/novamart-sim/novamart", repo])
    sh(["git", "-C", repo, "checkout", PIN])
    print("waiting for services...")
    time.sleep(20)
    if not cloud:
        sh([sys.executable, os.path.join(HERE, "loaders", "load_emulator.py")])
    out = subprocess.run([sys.executable, os.path.join(HERE, "loaders", "seed_redash.py")],
                         capture_output=True, text=True)
    print(out.stdout[-2000:])
    if out.returncode != 0: print(out.stderr[-2000:]); sys.exit("redash seed failed")
    key = [l for l in out.stdout.splitlines() if l.startswith("REDASH_ADMIN_API_KEY=")][-1].split("=", 1)[1]
    sh([sys.executable, os.path.join(HERE, "loaders", "access_pack.py"),
        a.warehouse_project or "novamart-warehouse", "http://localhost:5050", key, ws,
        "--mode", "cloud-bigquery" if cloud else "local", "--estate-pg-port", pg_port])
    pack = os.path.join(HERE, "access-pack")
    print(f"\nestate is up. The access pack in {pack} has the values the brief's placeholders refer to.")
    if not a.skip_verify:
        print("checking every surface...")
        r = subprocess.run([sys.executable, os.path.join(HERE, "verify_access.py")])
        if r.returncode != 0: sys.exit(1)
    print(f"\ntry it now:\n  source {os.path.join(pack, 'env.sh')}\n"
          f"  bq query 'SELECT month, gross FROM `{a.warehouse_project or 'novamart-warehouse'}.novamart.statements` ORDER BY month LIMIT 10'")

if __name__ == "__main__":
    main()
