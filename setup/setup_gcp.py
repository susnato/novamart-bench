"""GCP setup: load the NovaMart estate into YOUR OWN BigQuery project.

  python setup/setup_gcp.py --project your-project-id [--no-download] [--dataset-suffix _test]

Phase 0 checks permissions and creates nothing on failure. The three dataset
names are fixed by the benchmark (novamart, novamart_analytics, novamart_logs);
only the project varies, and it becomes your <warehouse-project> value.
Requires: gcloud authenticated, bq CLI. Role needed: roles/bigquery.user (or
anything granting bigquery.datasets.create + bigquery.jobs.create).
"""
import argparse, glob, json, os, subprocess, sys, urllib.request

NEEDED = ["bigquery.datasets.create", "bigquery.jobs.create"]
DATASETS = ["novamart", "novamart_analytics", "novamart_logs"]
HERE = os.path.dirname(os.path.abspath(__file__))

def token():
    r = subprocess.run(["gcloud", "auth", "print-access-token"], capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("preflight: gcloud is not authenticated. Run `gcloud auth login` "
                 "(or use local mode: python setup/setup_local.py).")
    return r.stdout.strip()

def preflight(project):
    """Phase 0: hard checks, nothing created. Every failure collected."""
    problems = []
    req = urllib.request.Request(
        f"https://cloudresourcemanager.googleapis.com/v1/projects/{project}:testIamPermissions",
        method="POST", data=json.dumps({"permissions": NEEDED}).encode(),
        headers={"Authorization": f"Bearer {token()}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r: got = set(json.load(r).get("permissions", []))
    except urllib.error.HTTPError as e:
        sys.exit(f"preflight: cannot check project '{project}' ({e.code}). "
                 "Does the project exist and can you see it?")
    for p in set(NEEDED) - got:
        problems.append(f"missing permission {p}: ask a project admin for roles/bigquery.user\n"
                        f"    gcloud projects add-iam-policy-binding {project} "
                        f"--member=user:<you> --role=roles/bigquery.user")
    if problems:
        print("preflight FAILED, nothing created:\n- " + "\n- ".join(problems))
        print("\nNo admin nearby? Local mode needs no cloud at all: python setup/setup_local.py")
        sys.exit(1)
    print("preflight OK: permissions present, nothing created yet")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--no-download", action="store_true")
    ap.add_argument("--dataset-suffix", default="", help=argparse.SUPPRESS)
    a = ap.parse_args()
    preflight(a.project)
    if not a.no_download:
        subprocess.run([sys.executable, os.path.join(HERE, "loaders", "download_data.py")], check=True)
    base = os.path.join(HERE, "data")
    counts = json.load(open(os.path.join(base, "counts.json")))
    for ds in DATASETS:
        tgt = ds + a.dataset_suffix
        subprocess.run(["bq", "--project_id", a.project, "mk", "--force", "--dataset", tgt],
                       check=True, capture_output=True)
        for t_dir in sorted(glob.glob(os.path.join(base, "tables", ds, "*"))):
            t = os.path.basename(t_dir)
            expected = counts.get(f"{ds}.{t}")
            r = subprocess.run(["bq", "--project_id", a.project, "show", "--format=json", f"{tgt}.{t}"],
                               capture_output=True, text=True)
            if r.returncode == 0 and expected is not None:
                have = int(json.loads(r.stdout).get("numRows", -1))
                if have == expected:
                    print(f"[skip] {a.project}:{tgt}.{t} already complete ({have} rows)")
                    continue
                print(f"[redo] {a.project}:{tgt}.{t} has {have} rows, expected {expected}")
            schema = os.path.join(t_dir, "schema.json")
            shards = sorted(glob.glob(os.path.join(t_dir, "*.ndjson.gz")))
            print(f"[load] {a.project}:{tgt}.{t} ({len(shards)} shard(s))")
            for i, shard in enumerate(shards):
                cmd = ["bq", "--project_id", a.project, "load", "--source_format=NEWLINE_DELIMITED_JSON"]
                if i == 0: cmd.append("--replace")
                cmd += [f"{tgt}.{t}", shard, schema]
                r = subprocess.run(cmd, capture_output=True, text=True)
                if r.returncode != 0: sys.exit(f"load failed for {tgt}.{t}: {r.stderr[-500:]}")
    print(f"\ndone. Your <warehouse-project> is: {a.project}")
    print("Redash and the world repo run locally either way: python setup/setup_local.py "
          "(it skips nothing you did here; the warehouse in your access pack will be this project).")

if __name__ == "__main__":
    main()
