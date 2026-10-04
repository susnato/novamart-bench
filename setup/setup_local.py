"""One-command local setup: download the estate, start the stack, load, seed, verify.

  python setup/setup_local.py                              # everything, warehouse in the local emulator
  python setup/setup_local.py --no-download                # reuse setup/data/
  python setup/setup_local.py --warehouse-project my-proj  # after setup_gcp.py: Redash and the repo only,
                                                           # access pack points at your BigQuery project

Endpoints when done: BigQuery emulator http://localhost:9050 (project
novamart-warehouse), Redash http://localhost:5050, estate Postgres :15433. The
estate itself (the world repo at the pin and the access pack) lives OUTSIDE this
repo, under ~/novamart-estate by default (--estate-dir), so an agent running there
never sees the claims or the released books. Host ports can be set with
BQ_EMULATOR_PORT, REDASH_PORT and ESTATE_PG_PORT; a default that is busy moves to
the next free port. Ports and the estate location are recorded in setup/.env.
"""
import argparse, os, socket, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
PIN = "5ae1182"
LOCAL_ONLY = ["estate-pg", "redash-redis", "redash-pg", "redash", "redash-scheduler", "redash-worker"]
DEFAULT_PORTS = {"BQ_EMULATOR_PORT": 9050, "REDASH_PORT": 5050, "ESTATE_PG_PORT": 15433}
ENV_FILE = os.path.join(HERE, ".env")

def port_free(port):
    with socket.socket() as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("0.0.0.0", port)); return True
        except OSError:
            return False

def resolve_ports():
    """Explicit env var > the port recorded in setup/.env by an earlier run (our own
    containers hold it) > the default, moved to the next free port if it is busy."""
    recorded = {}
    if os.path.exists(ENV_FILE):
        for line in open(ENV_FILE):
            if "=" in line and not line.startswith("#"):
                k, v = line.strip().split("=", 1); recorded[k] = v
    chosen = {}
    for var, default in DEFAULT_PORTS.items():
        if os.environ.get(var):
            p = int(os.environ[var])
            if p != int(recorded.get(var, -1)) and not port_free(p):
                sys.exit(f"host port {p} ({var}) is already in use; pick another and re-run")
        elif var in recorded:
            p = int(recorded[var])
        else:
            p = default
            while not port_free(p): p += 1
            if p != default:
                print(f"host port {default} is in use, using {p} for {var} (recorded in setup/.env and the access pack)")
        chosen[var] = p
    return chosen

def sh(cmd, **kw):
    print("+", " ".join(cmd)); r = subprocess.run(cmd, **kw)
    if r.returncode != 0: sys.exit(f"failed: {' '.join(cmd)}")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-download", action="store_true", help="reuse setup/data/")
    ap.add_argument("--warehouse-project", default=None,
                    help="your BigQuery project (after setup_gcp.py); skips the local emulator")
    ap.add_argument("--skip-verify", action="store_true")
    ap.add_argument("--estate-dir", default="~/novamart-estate",
                    help="where the world repo checkout and the access pack live (outside this repo)")
    a = ap.parse_args()
    cloud = a.warehouse_project is not None
    estate = os.path.abspath(os.path.expanduser(a.estate_dir))
    ports = resolve_ports()
    pg_port = str(ports["ESTATE_PG_PORT"])
    bq_endpoint = f"http://localhost:{ports['BQ_EMULATOR_PORT']}"
    redash_url = f"http://localhost:{ports['REDASH_PORT']}"
    os.environ["BQ_EMULATOR_ENDPOINT"] = bq_endpoint   # read by the loader and the parity script
    os.environ["REDASH_URL"] = redash_url               # read by the Redash seeder

    if not a.no_download:
        sh([sys.executable, os.path.join(HERE, "loaders", "download_data.py")])
    roles = os.path.join(HERE, "data", "roles.sql")
    if not os.path.exists(roles): open(roles, "w").write("-- placeholder for estate roles\n")
    with open(ENV_FILE, "w") as f:   # read by every docker compose call for this file
        for var, p in ports.items(): f.write(f"{var}={p}\n")
        f.write(f"ESTATE_DIR={estate}\n")
        if os.environ.get("BQ_EMULATOR_TAG"): f.write(f"BQ_EMULATOR_TAG={os.environ['BQ_EMULATOR_TAG']}\n")
    compose = ["docker", "compose", "-f", os.path.join(HERE, "docker-compose.yml"), "up", "-d"]
    sh(compose + (LOCAL_ONLY if cloud else []))
    ws = os.path.join(estate, "workspace")
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
        a.warehouse_project or "novamart-warehouse", redash_url, key, ws,
        "--mode", "cloud-bigquery" if cloud else "local", "--estate-pg-port", pg_port,
        "--emulator-endpoint", bq_endpoint, "--out", os.path.join(estate, "access-pack")])
    pack = os.path.join(estate, "access-pack")
    print(f"\nestate is up at {estate}. The access pack in {pack} has the values the brief's placeholders refer to.")
    if not a.skip_verify:
        print("checking every surface...")
        r = subprocess.run([sys.executable, os.path.join(HERE, "verify_access.py")])
        if r.returncode != 0: sys.exit(1)
    print(f"\ntry it now:\n  source {os.path.join(pack, 'env.sh')}\n  bq ls\n"
          f"\nrun your agent from {os.path.join(ws, 'novamart')}; this repo (claims, released books) is not part of the estate.")

if __name__ == "__main__":
    main()
