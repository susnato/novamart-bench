# Local setup

One command stands up the full estate on your machine, serving the same APIs the original evaluation used: the BigQuery API (project `novamart-warehouse`, three datasets), Redash, and a git checkout of the application repo at the pinned commit.

## Requirements

Docker (with compose), Python 3.10+, `pip install -r setup/requirements.txt`, about 15 GB free disk (the emulator's database volume reaches roughly 10 GB once the estate is loaded). No cloud account and no credentials are needed once the dataset is public; during the private phase set `HF_TOKEN`.

## Run

```bash
python setup/setup_local.py
```

This downloads the estate from Hugging Face into `setup/data/`, starts the containers ([bqemulator](https://github.com/jjviscomi/bqemulator) serving the BigQuery API on :9050, Redash on :5050, estate Postgres on :5433), loads all 35 tables into the emulator as NDJSON load jobs, creates the 5 estate views (4 in `novamart_analytics`, 1 in `novamart_logs`), restores the Postgres dump that Redash queries, seeds the 9 dashboards and their queries, clones `novamart-sim/novamart` into `setup/workspace/novamart` at the pinned commit, and writes `setup/access-pack/` with the values the brief's placeholders refer to (warehouse project, Redash URL and API key, workspace path) plus rendered convenience copies of the brief.

Re-run with `--no-download` to reuse `setup/data/`. `docker compose -f setup/docker-compose.yml down -v` resets everything, the emulator's data volume included.

## Notes

- Redash is served on host port 5050 because macOS AirPlay occupies 5000.
- The emulator serves project id `novamart-warehouse`, so the in-world `docs/data-access.md`, the brief, and the loaded warehouse all agree.
- Emulator parity: `python setup/parity/run_parity.py --target emulator` re-runs every claim's evidence SQL against the emulator and compares to `setup/parity/goldens.json`, the normalized results from the original warehouse. Expected: 35 of 35 matched, 0 skipped.
- Why bqemulator: on the shipped estate every evidence query answers in under a second (the previous emulator took tens of seconds or timed out on log-table scans), all 35 evidence statements match the real-BigQuery goldens with no skip list, and concurrent queries work. The full measurement table lives in the simulator repo's `RESULTS.md`.
- Pin the emulator with `BQ_EMULATOR_TAG` (default `1.4.0`). The previous emulator (goccy/bigquery-emulator) remains available for one release behind a compose profile: stop `bq-emulator`, then `docker compose -f setup/docker-compose.yml --profile goccy up -d bq-emulator-goccy` (same port; with it, parity needs `--engine goccy`, which skips the one query it cannot finish).
- If a query ever wedges the emulator (it executes queries on a single connection), restart the container: `docker compose -f setup/docker-compose.yml restart bq-emulator`.
