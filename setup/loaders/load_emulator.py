"""Load the NDJSON tables into the local BigQuery emulator.

The emulator serves project `novamart-warehouse` on localhost:9050, so the
in-world docs, the brief, and the loaded warehouse all agree.
"""
import glob, gzip, json, os, sys, time

from google.api_core.client_options import ClientOptions
from google.auth.credentials import AnonymousCredentials
from google.cloud import bigquery

PROJECT = "novamart-warehouse"
ENDPOINT = os.environ.get("BQ_EMULATOR_ENDPOINT", "http://localhost:9050")
BATCH = 2000

def schema_from_json(path):
    def field(f):
        return bigquery.SchemaField(
            f["name"], f["type"], mode=f.get("mode", "NULLABLE"),
            fields=[field(x) for x in f.get("fields", [])])
    return [field(f) for f in json.load(open(path))]

def main():
    base = os.path.join(os.path.dirname(__file__), "..", "data")
    client = bigquery.Client(project=PROJECT, credentials=AnonymousCredentials(),
                             client_options=ClientOptions(api_endpoint=ENDPOINT))
    total = 0
    for ds_dir in sorted(glob.glob(os.path.join(base, "tables", "*"))):
        ds = os.path.basename(ds_dir)
        client.create_dataset(bigquery.Dataset(f"{PROJECT}.{ds}"), exists_ok=True)
        for t_dir in sorted(glob.glob(os.path.join(ds_dir, "*"))):
            t = os.path.basename(t_dir)
            schema = schema_from_json(os.path.join(t_dir, "schema.json"))
            table = bigquery.Table(f"{PROJECT}.{ds}.{t}", schema=schema)
            client.create_table(table, exists_ok=True)
            rows, n, t0 = [], 0, time.time()
            for shard in sorted(glob.glob(os.path.join(t_dir, "*.ndjson.gz"))):
                with gzip.open(shard, "rt") as fh:
                    for line in fh:
                        rows.append(json.loads(line))
                        if len(rows) >= BATCH:
                            errs = client.insert_rows_json(table, rows)
                            if errs: print(f"  insert errors {ds}.{t}: {errs[:2]}"); return 1
                            n += len(rows); rows = []
            if rows:
                errs = client.insert_rows_json(table, rows)
                if errs: print(f"  insert errors {ds}.{t}: {errs[:2]}"); return 1
                n += len(rows)
            total += n
            print(f"  {ds}.{t}: {n} rows in {time.time()-t0:.1f}s")
    print(f"emulator loaded: {total} rows")
    return 0

if __name__ == "__main__":
    sys.exit(main())
