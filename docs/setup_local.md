# Local setup

One command brings up the whole estate on your machine: the BigQuery API (project `novamart-warehouse`, three datasets), Redash, and a checkout of the application repo at the pinned commit. These are the same interfaces all the Agents should be evaluated against.

## Requirements

Before running the setup script make sure, tools as listed under [Before you start](../README.md#before-you-start) in the README are installed and install the python packages.

The local setup needs about 15 GB of free disk (the emulator's data volume is about 7 GB once the estate is loaded), and Docker allowed at least 4 CPUs and 8 GB of memory: the stack idles at about 3.5 GB (emulator 2 GB, Redash 1.4 GB), the load peaks at one core and 2.3 GB in the emulator for a few minutes, and heavy log-table queries can use several cores for a few seconds. Compose sets no per-container limits.

## Run

```bash
python setup/setup_local.py
```

The script downloads the estate from Hugging Face [dataset](https://huggingface.co/datasets/susnato/novamart-bench) into `setup/data/`, starts the containers (takes approx 10 minutes from starting up the containers, transferring the data): 

- [bqemulator](https://github.com/jjviscomi/bqemulator) serving the BigQuery API on :9050
- Redash on :5050
- the estate Postgres on :15433
- Repo cloned at `./setup/workspace` with pinned commit

This loads the 35 tables into the emulator, creates the 5 estate views (4 in `novamart_analytics`, 1 in `novamart_logs`), restores the Postgres dump that Redash queries, seeds the 9 dashboards, clones `novamart-sim/novamart` into `setup/workspace/novamart` at the pinned commit, and writes `setup/access-pack/` with the values the brief's placeholders refer to (warehouse project, Redash URL and API key, workspace path) and rendered copies of the brief.

**To run it again without downloading the data**: add `--no-download`. 

**To wipe everything (including the emulator's data volume)**: `docker compose -f setup/docker-compose.yml down -v`.

## Check it works

The setup script runs `setup/verify_access.py` which calls BQ emulator, redash and postgres instances to make sure they are healthy and prints the status, you should see somethign like this:

```bash
python ./setup/verify_access.py

# access pack mode: local
#   [PASS] BigQuery         http://localhost:9050: 3 datasets, novamart.orders has 9127 rows
#   [PASS] Redash           http://localhost:5050: 9 dashboards
#   [PASS] Codebase         ./setup/workspace/novamart: HEAD 5ae1182
#   [PASS] Estate Postgres  127.0.0.1:15433: accepting connections
# all surfaces answer
```

Before running `bq` or your agent, source the access pack's env file; it points `bq` and the client libraries at the local emulator

```bash
source ./setup/access-pack/env.sh
```

Then u can query BQ emulator to make sure it's working:

```bash
bq query 'SELECT month, gross FROM `novamart-warehouse.novamart.statements` ORDER BY month LIMIT 10'

# +---------+-------------------+
# |  month  |       gross       |
# +---------+-------------------+
# | 2019-09 |    2702.000000000 |
# | 2019-10 | 1230332.430000000 |
# | 2019-11 | 1101397.010000000 |
# +---------+-------------------+
```

**If you are gonna call BQ from any client other than bq tool** pass anonymous credentials (with `env.sh` sourced, which is where the endpoint comes from), for example in python do:

```python
from google.cloud import bigquery
from google.auth.credentials import AnonymousCredentials
client = bigquery.Client(project="novamart-warehouse", credentials=AnonymousCredentials())
```

Checkout the newly created `setup/access-pack/README.md` for more information.

## Notes

- Redash is on port 5050 rather than 5000 because macOS AirPlay sits on 5000.
- Host ports: emulator 9050, Redash 5050, estate Postgres 15433. Set `BQ_EMULATOR_PORT`, `REDASH_PORT` or `ESTATE_PG_PORT` to choose others; if a default is busy, setup moves to the next free port and tells you. The chosen ports are recorded in `setup/.env` and in the access pack, so every later command agrees.
- The emulator serves project id `novamart-warehouse`, which is what the in-world `docs/data-access.md`, the brief and the loaded warehouse all say.
- To check that the emulator answers like the real warehouse, run `python setup/parity/run_parity.py --target emulator`. It re-runs every claim's evidence SQL and compares the results to `setup/parity/goldens.json`, which holds the results from the original warehouse. You should see 36 of 36 matched, 0 skipped. CI runs the same check weekly.
- The emulator version is pinned with `BQ_EMULATOR_TAG` (default `1.4.0`). The previous emulator, goccy/bigquery-emulator, is still in the compose file behind a profile for one more release: stop `bq-emulator`, then `docker compose -f setup/docker-compose.yml --profile goccy up -d bq-emulator-goccy` (same port). Parity against it needs `--engine goccy`, which skips the one query it cannot finish.
- If the emulator hangs on a query (it runs queries on a single connection, so one stuck query blocks the rest) restart it: `docker compose -f setup/docker-compose.yml restart bq-emulator`.

