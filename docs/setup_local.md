# Local setup

One command brings up the whole estate on your machine: the BigQuery API (project `novamart-warehouse`, three datasets), Redash, and a checkout of the application repo at the pinned commit. These are the same interfaces the baselines were evaluated against.

## Requirements

Tools as listed under [Before you start](../README.md#before-you-start) in the README. Then about 15 GB of free disk (the emulator's data volume is about 7 GB once the estate is loaded), and Docker allowed at least 4 CPUs and 8 GB of memory: the stack idles at about 3.5 GB (emulator 2 GB, Redash 1.4 GB), the load peaks at one core and 2.3 GB in the emulator for a few minutes, and heavy log-table queries can use several cores for a few seconds. Compose sets no per-container limits. No cloud account and no credentials.

## Run

```bash
python setup/setup_local.py
```

The script downloads the estate from Hugging Face into `setup/data/`, starts the containers ([bqemulator](https://github.com/jjviscomi/bqemulator) serving the BigQuery API on :9050, Redash on :5050, the estate Postgres on :5433), loads the 35 tables into the emulator, creates the 5 estate views (4 in `novamart_analytics`, 1 in `novamart_logs`), restores the Postgres dump that Redash queries, seeds the 9 dashboards, clones `novamart-sim/novamart` into `setup/workspace/novamart` at the pinned commit, and writes `setup/access-pack/` with the values the brief's placeholders refer to (warehouse project, Redash URL and API key, workspace path) and rendered copies of the brief.

To run it again without downloading, add `--no-download`. To wipe everything, including the emulator's data volume: `docker compose -f setup/docker-compose.yml down -v`.

It ends by running `setup/verify_access.py`, which checks each surface the way an agent would use it: a query through the BigQuery client, the Redash API with the key, the repo at the pin, and the estate Postgres. Run it again any time.

## Check it works

The brief tells the agent that the warehouse is "BigQuery, project `novamart-warehouse`". Locally that is an emulator on `http://localhost:9050`, which needs no key and accepts any token. `setup/access-pack/env.sh` makes the standard tools reach it: it points `bq` at the emulator (endpoint, project and a local copy of the API's discovery document via `BIGQUERYRC`, plus a one-line `bq` wrapper first on `PATH` that supplies a dummy token), so `bq` works with no Google login at all; and it sets `BIGQUERY_EMULATOR_HOST` for the Python, Go, Node and Java client libraries. Before running an agent:

```bash
source setup/access-pack/env.sh
python setup/verify_access.py
bq query 'SELECT month, gross FROM `novamart-warehouse.novamart.statements` ORDER BY month LIMIT 10'
```

The client libraries read the endpoint from the variable but still insist on a credential object before they send anything. On a machine with a valid `gcloud auth application-default login` they work unchanged; without one, pass anonymous credentials, for example in Python `bigquery.Client(project="novamart-warehouse", credentials=AnonymousCredentials())`. `setup/access-pack/README.md` spells all of this out per surface, and `env.sh` warns if the emulator is not running.

## Notes

- Redash is on port 5050 rather than 5000 because macOS AirPlay sits on 5000.
- The estate Postgres is on host port 5433. If something else holds it, set `ESTATE_PG_PORT` before running setup; Redash reaches Postgres inside docker either way.
- The emulator serves project id `novamart-warehouse`, which is what the in-world `docs/data-access.md`, the brief and the loaded warehouse all say.
- To check that the emulator answers like the real warehouse, run `python setup/parity/run_parity.py --target emulator`. It re-runs every claim's evidence SQL and compares the results to `setup/parity/goldens.json`, which holds the results from the original warehouse. You should see 36 of 36 matched, 0 skipped. CI runs the same check weekly.
- The emulator version is pinned with `BQ_EMULATOR_TAG` (default `1.4.0`). The previous emulator, goccy/bigquery-emulator, is still in the compose file behind a profile for one more release: stop `bq-emulator`, then `docker compose -f setup/docker-compose.yml --profile goccy up -d bq-emulator-goccy` (same port). Parity against it needs `--engine goccy`, which skips the one query it cannot finish.
- The emulator may hang on a query (it runs queries on a single connection, so one stuck query blocks the rest). If it does, restart it: `docker compose -f setup/docker-compose.yml restart bq-emulator`.
