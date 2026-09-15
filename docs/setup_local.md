# Local setup

One command stands up the full estate on your machine, serving the same APIs the original evaluation used: the BigQuery API (project `novamart-warehouse`, three datasets), Redash, and a git checkout of the application repo at the pinned commit.

## Requirements

Docker (with compose), Python 3.10+, `pip install -r setup/requirements.txt`, about 3 GB free disk. No cloud account and no credentials are needed once the dataset is public; during the private phase set `HF_TOKEN`.

## Run

```bash
python setup/setup_local.py
```

This downloads the estate from Hugging Face into `setup/data/`, starts the containers (BigQuery emulator on :9050, Redash on :5050, estate Postgres on :5433), loads all 36 tables into the emulator (the 3.6M row query log takes the longest), restores the Postgres dump that Redash queries, seeds the 9 dashboards and their queries, clones `novamart-sim/novamart` into `setup/workspace/novamart` at the pinned commit, and writes `setup/access-pack/` with the values the brief's placeholders refer to (warehouse project, Redash URL and API key, workspace path) plus rendered convenience copies of the brief.

Re-run with `--no-download` to reuse `setup/data/`. `docker compose -f setup/docker-compose.yml down -v` resets everything.

## Notes

- Redash is served on host port 5050 because macOS AirPlay occupies 5000.
- The emulator serves project id `novamart-warehouse`, so the in-world `docs/data-access.md`, the brief, and the loaded warehouse all agree.
- Emulator parity: `python setup/parity/run_parity.py --target emulator` re-runs every claim's evidence SQL against the emulator and compares to `setup/parity/goldens.json`, the normalized results from the original warehouse.
