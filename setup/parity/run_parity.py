"""Run every claim's evidence SQL against a warehouse and compare to goldens.

  python setup/parity/run_parity.py --target emulator          # vs goldens.json
  python setup/parity/run_parity.py --target real --project X --write-goldens

Goldens are computed once against the original warehouse; CI runs the emulator
leg and compares. Result normalization: rows as sorted tuples of stringified
values, floats rounded to 6 places.
"""
import argparse, glob, json, os, sys
import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..", "..")

def collect_sql():
    out = []
    for f in sorted(glob.glob(os.path.join(ROOT, "claims", "*.yaml"))):
        for claim in yaml.safe_load(open(f)) or []:
            for i, ev in enumerate(claim.get("evidence") or []):
                if ev.get("sql"):
                    out.append((claim["claim_id"], i, ev["sql"]))
    return out

def normalize(rows):
    def cell(v):
        if isinstance(v, float): return f"{v:.6f}"
        return str(v)
    return sorted([cell(v) for v in row] for row in rows)  # lists, not tuples: goldens round-trip through JSON

def run_real(sql, project):
    from google.cloud import bigquery
    client = bigquery.Client(project=project)
    return [list(r.values()) for r in client.query(sql).result()]

def run_emulator(sql):
    from google.api_core.client_options import ClientOptions
    from google.auth.credentials import AnonymousCredentials
    from google.cloud import bigquery
    client = bigquery.Client(project="novamart-warehouse", credentials=AnonymousCredentials(),
                             client_options=ClientOptions(api_endpoint=os.environ.get("BQ_EMULATOR_ENDPOINT", "http://localhost:9050")))
    return [list(r.values()) for r in client.query(sql).result()]

def check_quotes(data_dir):
    """Verify SQL quoted inside claim excerpts actually appears in the shipped estate."""
    import gzip, re
    quotes = []
    for f in sorted(glob.glob(os.path.join(ROOT, "claims", "*.yaml"))):
        for claim in yaml.safe_load(open(f)) or []:
            for ev in claim.get("evidence") or []:
                ex = ev.get("excerpt") or ""
                m = re.search(r'"(SELECT [^"]{20,200})', ex) or re.search(r'"(CREATE TABLE [^"]{20,200})', ex)
                if m and not ev.get("sql"):
                    quotes.append((claim["claim_id"], m.group(1)[:80]))
    hits = {}
    for cid, q in quotes:
        found = False
        for shard in glob.glob(os.path.join(data_dir, "tables", "novamart_logs", "*", "*.ndjson.gz")):
            with gzip.open(shard, "rt") as fh:
                if any(q in line for line in fh): found = True; break
        hits[cid] = found
        print(f"quote-check {cid}: {'FOUND in shipped logs' if found else 'NOT FOUND'} :: {q[:60]}...")
    return all(hits.values())

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", choices=["real", "emulator"], required=True)
    ap.add_argument("--warehouse-project", "--project", dest="project", default=None)
    ap.add_argument("--write-goldens", action="store_true")
    ap.add_argument("--check-quotes", action="store_true")
    a = ap.parse_args()
    if a.check_quotes:
        ok = check_quotes(os.path.join(ROOT, "setup", "data"))
        return 0 if ok else 1
    gpath = os.path.join(HERE, "goldens.json")
    goldens = json.load(open(gpath)) if os.path.exists(gpath) else {}
    results, failures, mismatches = {}, [], []
    for cid, i, sql in collect_sql():
        key = f"{cid}#{i}"
        q = sql.replace("<warehouse-project>", a.project or "novamart-warehouse")
        try:
            rows = run_real(q, a.project) if a.target == "real" else run_emulator(q)
            results[key] = normalize(rows)
        except Exception as e:
            failures.append((key, str(e).splitlines()[0][:160])); continue
        if not a.write_goldens and key in goldens and results[key] != goldens[key]:
            mismatches.append(key)
    print(f"queries: {len(results)+len(failures)} | ran: {len(results)} | errors: {len(failures)} | mismatches vs goldens: {len(mismatches)}")
    for k, e in failures: print(f"  ERROR {k}: {e}")
    for k in mismatches: print(f"  MISMATCH {k}")
    if a.write_goldens:
        json.dump(results, open(gpath, "w"), indent=0, sort_keys=True)
        print(f"goldens written: {len(results)} entries")
    return 1 if (failures or mismatches) and not a.write_goldens else 0

if __name__ == "__main__":
    sys.exit(main())
