"""Create the five estate views (four in novamart_analytics, one in novamart_logs).

The original warehouse serves these as views over the loaded tables; they ship
as SQL bodies in setup/views/ because views carry no rows. Order matters:
statements_final selects from statements_corrected.

  python setup/loaders/create_views.py --project your-project-id [--dataset-suffix _x] [--dry-run]

The emulator path is called from load_emulator.py with its client.
"""
import argparse, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
VIEWS_DIR = os.path.join(HERE, "..", "views")
DATASETS = ["novamart", "novamart_analytics", "novamart_logs"]
VIEWS = [  # (dataset, view) in dependency order
    ("novamart_analytics", "contactable_users"),
    ("novamart_analytics", "refunds_unified"),
    ("novamart_analytics", "statements_corrected"),
    ("novamart_analytics", "statements_final"),
    ("novamart_logs", "db_queries_normalized"),
]

def render(project, suffix=""):
    """Yield (qualified view name, CREATE OR REPLACE VIEW statement)."""
    for ds, name in VIEWS:
        body = open(os.path.join(VIEWS_DIR, f"{ds}.{name}.sql")).read().strip()
        for d in DATASETS:  # qualified table refs first, then the bare placeholder
            body = body.replace(f"`<warehouse-project>.{d}.", f"`{project}.{d}{suffix}.")
        body = body.replace("<warehouse-project>", project)
        target = f"{project}.{ds}{suffix}.{name}"
        yield target, f"CREATE OR REPLACE VIEW `{target}` AS\n{body}"

def create_on_emulator(client, project):
    for target, stmt in render(project):
        client.query(stmt).result(timeout=120)
        print(f"  view {target}")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--dataset-suffix", default="", help=argparse.SUPPRESS)
    ap.add_argument("--dry-run", action="store_true", help="validate only, create nothing")
    a = ap.parse_args()
    for target, stmt in render(a.project, a.dataset_suffix):
        cmd = ["bq", "--project_id", a.project, "query", "--nouse_legacy_sql"]
        if a.dry_run:
            cmd.append("--dry_run")
        r = subprocess.run(cmd + [stmt], capture_output=True, text=True)
        if r.returncode != 0:
            sys.exit(f"view failed for {target}: {r.stderr[-500:]}")
        print(f"  view {target}" + (" (dry run ok)" if a.dry_run else ""))
    return 0

if __name__ == "__main__":
    sys.exit(main())
