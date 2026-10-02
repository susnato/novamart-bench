# Local setup

One command brings up the whole estate on your machine: the BigQuery API (project `novamart-warehouse`, three datasets), Redash, and a checkout of the application repo at the pinned commit. These are the same interfaces the baselines were evaluated against.

## Requirements

Docker with compose, Python 3.10 or newer, `pip install -r setup/requirements.txt`, and about 15 GB of free disk (the emulator's database volume grows to roughly 10 GB once the estate is loaded). No cloud account and no credentials.

## Run

```bash
python setup/setup_local.py
```

The script downloads the estate from Hugging Face into `setup/data/`, starts the containers ([bqemulator](https://github.com/jjviscomi/bqemulator) serving the BigQuery API on :9050, Redash on :5050, the estate Postgres on :5433), loads the 35 tables into the emulator, creates the 5 estate views (4 in `novamart_analytics`, 1 in `novamart_logs`), restores the Postgres dump that Redash queries, seeds the 9 dashboards, clones `novamart-sim/novamart` into `setup/workspace/novamart` at the pinned commit, and writes `setup/access-pack/` with the values the brief's placeholders refer to (warehouse project, Redash URL and API key, workspace path) and rendered copies of the brief.

To run it again without downloading, add `--no-download`. To wipe everything, including the emulator's data volume: `docker compose -f setup/docker-compose.yml down -v`.

## Notes

- Redash is on port 5050 rather than 5000 because macOS AirPlay sits on 5000.
- The emulator serves project id `novamart-warehouse`, which is what the in-world `docs/data-access.md`, the brief and the loaded warehouse all say.
- To check that the emulator answers like the real warehouse, run `python setup/parity/run_parity.py --target emulator`. It re-runs every claim's evidence SQL and compares the results to `setup/parity/goldens.json`, which holds the results from the original warehouse. You should see 36 of 36 matched, 0 skipped. CI runs the same check weekly.
- The emulator version is pinned with `BQ_EMULATOR_TAG` (default `1.4.0`). The previous emulator, goccy/bigquery-emulator, is still in the compose file behind a profile for one more release: stop `bq-emulator`, then `docker compose -f setup/docker-compose.yml --profile goccy up -d bq-emulator-goccy` (same port). Parity against it needs `--engine goccy`, which skips the one query it cannot finish.
- The emulator may hang on a query (it runs queries on a single connection, so one stuck query blocks the rest). If it does, restart it: `docker compose -f setup/docker-compose.yml restart bq-emulator`.
