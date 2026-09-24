"""Load the NDJSON tables into the local BigQuery emulator (bqemulator).

The emulator serves project `novamart-warehouse` on localhost:9050, so the
in-world docs, the brief, and the loaded warehouse all agree. Tables load as
one NDJSON load job per shard, raw bytes passed through: the shipped shards
already carry JSON columns as objects, which is exactly what a load job
expects (pre-stringifying them would store JSON string scalars and break
JSON_VALUE paths).
"""
import glob, gzip, json, os, sys, time, urllib.request

from google.api_core.client_options import ClientOptions
from google.auth.credentials import AnonymousCredentials
from google.cloud import bigquery

PROJECT = "novamart-warehouse"
ENDPOINT = os.environ.get("BQ_EMULATOR_ENDPOINT", "http://localhost:9050")

def schema_from_json(path):
    def field(f):
        return bigquery.SchemaField(
            f["name"], f["type"], mode=f.get("mode", "NULLABLE"),
            fields=[field(x) for x in f.get("fields", [])])
    return [field(f) for f in json.load(open(path))]

def wait_ready(timeout=60):
    """Fail fast instead of letting the Google client retry a refused
    connection with backoff for ten minutes, which looks like a hang."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(ENDPOINT + "/", timeout=2)
            return
        except urllib.error.HTTPError:
            return  # any HTTP response means the server is up
        except Exception:
            time.sleep(1)
    sys.exit(f"emulator not reachable at {ENDPOINT} after {timeout}s; "
             "is the bq-emulator container up? (docker compose -f setup/docker-compose.yml up -d bq-emulator)")

def main():
    base = os.path.join(os.path.dirname(__file__), "..", "data")
    wait_ready()
    client = bigquery.Client(project=PROJECT, credentials=AnonymousCredentials(),
                             client_options=ClientOptions(api_endpoint=ENDPOINT))
    counts = json.load(open(os.path.join(base, "counts.json")))
    total = 0
    for ds_dir in sorted(glob.glob(os.path.join(base, "tables", "*"))):
        ds = os.path.basename(ds_dir)
        client.create_dataset(bigquery.Dataset(f"{PROJECT}.{ds}"), exists_ok=True)
        for t_dir in sorted(glob.glob(os.path.join(ds_dir, "*"))):
            t = os.path.basename(t_dir)
            schema = schema_from_json(os.path.join(t_dir, "schema.json"))
            table_id = f"{PROJECT}.{ds}.{t}"
            t0 = time.time()
            for i, shard in enumerate(sorted(glob.glob(os.path.join(t_dir, "*.ndjson.gz")))):
                with gzip.open(shard, "rb") as fh:
                    job = client.load_table_from_file(
                        fh, table_id,
                        job_config=bigquery.LoadJobConfig(
                            source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
                            schema=schema,
                            write_disposition="WRITE_TRUNCATE" if i == 0 else "WRITE_APPEND"))
                job.result()
            n = list(client.query(f"SELECT COUNT(*) FROM `{table_id}`").result())[0][0]
            expected = counts.get(f"{ds}.{t}")
            if expected is not None and n != expected:
                print(f"  ROW COUNT MISMATCH {ds}.{t}: loaded {n}, expected {expected}")
                return 1
            total += n
            print(f"  {ds}.{t}: {n} rows in {time.time()-t0:.1f}s")
    import create_views
    create_views.create_on_emulator(client, PROJECT)
    print(f"emulator loaded: {total} rows")
    return 0

if __name__ == "__main__":
    sys.exit(main())
