"""Check that every surface in the access pack answers the way an agent would use it.

  source setup/access-pack/env.sh      # optional; the script reads values.env itself
  python setup/verify_access.py

Works for both modes (local emulator and your own BigQuery project). Exit code 1 if
anything fails.
"""
import json, os, socket, subprocess, sys, urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PIN = "5ae1182"
DATASETS = {"novamart", "novamart_analytics", "novamart_logs"}

def load_values():
    path = os.path.join(HERE, "access-pack", "values.env")
    if not os.path.exists(path):
        sys.exit(f"no access pack at {path}; run setup/setup_local.py first")
    v = {}
    for line in open(path):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, val = line.split("=", 1); v[k] = val
    return v

def check_bigquery(v):
    from google.cloud import bigquery
    project = v["WAREHOUSE_PROJECT"]
    if v.get("BIGQUERY_API_ENDPOINT"):
        from google.api_core.client_options import ClientOptions
        from google.auth.credentials import AnonymousCredentials
        where = v["BIGQUERY_API_ENDPOINT"]
        try:   # fail fast: the client would otherwise retry a refused connection for ten minutes
            urllib.request.urlopen(where + "/", timeout=3)
        except urllib.error.HTTPError:
            pass
        except Exception as e:
            return False, f"{where}: not answering ({e.__class__.__name__}); start it with: docker compose -f setup/docker-compose.yml up -d bq-emulator"
        client = bigquery.Client(project=project, credentials=AnonymousCredentials(),
                                 client_options=ClientOptions(api_endpoint=where))
    else:
        client = bigquery.Client(project=project)
        where = "bigquery.googleapis.com"
    found = {d.dataset_id for d in client.list_datasets(timeout=60)}
    missing = DATASETS - found
    if missing:
        return False, f"{where}: datasets missing {sorted(missing)} (found {sorted(found)})"
    n = list(client.query(f"SELECT COUNT(*) AS n FROM `{project}.novamart.orders`").result(timeout=120))[0].n
    counts = os.path.join(HERE, "data", "counts.json")
    if os.path.exists(counts):
        want = json.load(open(counts)).get("novamart.orders")
        if want is not None and n != want:
            return False, f"{where}: novamart.orders has {n} rows, expected {want}"
    return True, f"{where}: 3 datasets, novamart.orders has {n} rows"

def check_redash(v):
    req = urllib.request.Request(v["REDASH_URL"].rstrip("/") + "/api/dashboards",
                                 headers={"Authorization": f"Key {v['REDASH_API_KEY']}"})
    with urllib.request.urlopen(req, timeout=10) as r:
        d = json.load(r)
    n = d.get("count", len(d.get("results", [])))
    return n == 9, f"{v['REDASH_URL']}: {n} dashboards" + ("" if n == 9 else " (expected 9)")

def check_workspace(v):
    repo = os.path.join(v["WORKSPACE"], "novamart")
    r = subprocess.run(["git", "-C", repo, "rev-parse", "--short", "HEAD"], capture_output=True, text=True)
    if r.returncode != 0:
        return False, f"{repo}: not a git checkout ({r.stderr.strip()})"
    head = r.stdout.strip()
    return head.startswith(PIN), f"{repo}: HEAD {head}" + ("" if head.startswith(PIN) else f" (expected {PIN})")

def check_postgres(v):
    port = int(v.get("ESTATE_PG_PORT", "15433"))
    with socket.socket() as s:
        s.settimeout(3)
        try:
            s.connect(("127.0.0.1", port))
        except OSError as e:
            return False, f"127.0.0.1:{port}: {e}"
    return True, f"127.0.0.1:{port}: accepting connections"

def main():
    v = load_values()
    print(f"access pack mode: {v.get('MODE', 'local')}")
    ok_all = True
    for name, fn in [("BigQuery", check_bigquery), ("Redash", check_redash),
                     ("Codebase", check_workspace), ("Estate Postgres", check_postgres)]:
        try:
            ok, msg = fn(v)
        except Exception as e:
            ok, msg = False, f"{type(e).__name__}: {str(e).splitlines()[0][:160]}"
        ok_all &= ok
        print(f"  [{'PASS' if ok else 'FAIL'}] {name:16} {msg}")
    print("all surfaces answer" if ok_all else "something is not answering; see above")
    return 0 if ok_all else 1

if __name__ == "__main__":
    sys.exit(main())
