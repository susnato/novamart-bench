"""One-command local setup: download the estate, start the stack, load, seed.

  python setup/setup_local.py            # everything
  python setup/setup_local.py --no-download   # reuse setup/data/

Endpoints when done: BigQuery emulator http://localhost:9050 (project
novamart-warehouse), Redash http://localhost:5000, estate Postgres :5433,
world repo cloned at setup/workspace/novamart (checked out at the pin).
"""
import os, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
PIN = "5ae1182"

def sh(cmd, **kw):
    print("+", " ".join(cmd)); r = subprocess.run(cmd, **kw)
    if r.returncode != 0: sys.exit(f"failed: {' '.join(cmd)}")

def main():
    if "--no-download" not in sys.argv:
        sh([sys.executable, os.path.join(HERE, "loaders", "download_data.py")])
    roles = os.path.join(HERE, "data", "roles.sql")
    if not os.path.exists(roles): open(roles, "w").write("-- placeholder for estate roles\n")
    sh(["docker", "compose", "-f", os.path.join(HERE, "docker-compose.yml"), "up", "-d"])
    ws = os.path.join(HERE, "workspace")
    os.makedirs(ws, exist_ok=True)
    repo = os.path.join(ws, "novamart")
    if not os.path.exists(repo):
        sh(["git", "clone", "https://github.com/novamart-sim/novamart", repo])
    sh(["git", "-C", repo, "checkout", PIN])
    print("waiting for services...")
    time.sleep(20)
    sh([sys.executable, os.path.join(HERE, "loaders", "load_emulator.py")])
    out = subprocess.run([sys.executable, os.path.join(HERE, "loaders", "seed_redash.py")],
                         capture_output=True, text=True)
    print(out.stdout[-2000:]); 
    if out.returncode != 0: print(out.stderr[-2000:]); sys.exit("redash seed failed")
    key = [l for l in out.stdout.splitlines() if l.startswith("REDASH_ADMIN_API_KEY=")][-1].split("=",1)[1]
    sh([sys.executable, os.path.join(HERE, "loaders", "access_pack.py"),
        "novamart-warehouse", "http://localhost:5050", key, repo])
    print("\nlocal estate is up. See setup/access-pack/ for the values the brief's placeholders refer to.")

if __name__ == "__main__":
    main()
