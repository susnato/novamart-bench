# Real BigQuery setup (`cloud-bigquery` mode)

Two commands set up the estate with the warehouse in your own BigQuery project and the rest (Redash and the application repo checkout) on your machine. These are the same interfaces all the Agents should be evaluated against.

## Requirements

Before running the setup scripts make sure, tools as listed under [Before you start](../README.md#before-you-start) in the README are installed and install the python packages. Also make sure `gcloud` is logged in (`gcloud auth login`) and `bq` works from your terminal.

You need a GCP project where you have `roles/bigquery.user` (or any role which gives `bigquery.datasets.create` and `bigquery.jobs.create`). The datasets take about 2 GB of storage in BigQuery and every query your agent runs is billed to your project. Docker is still needed for Redash and the estate Postgres (no emulator in this mode, so around 1.5 GB of memory is enough).

## Run

```bash
python setup/setup_gcp.py --project your-project-id
python setup/setup_local.py --warehouse-project your-project-id --no-download
```

The first script downloads the estate from Hugging Face [dataset](https://huggingface.co/datasets/susnato/novamart-bench) into `setup/data/`, checks that you have the permissions (nothing is created if any permission is missing, it prints the exact command to ask your admin for) and then creates these datasets in your project and loads the data (takes approx 10 minutes, mostly uploading the two big log tables):

- `novamart` (app tables)
- `novamart_analytics` (analytics tables and views)
- `novamart_logs` (log exports, including the query log)

This loads all 35 tables, creates the 5 estate views (4 in `novamart_analytics`, 1 in `novamart_logs`) and at the end prints the second command. The dataset names are fixed, only the project changes, your project id becomes the `<warehouse-project>` in the brief.

The second script starts the containers (no emulator this time):

- Redash on :5050
- the estate Postgres on :15433
- Repo cloned at `~/novamart-estate/workspace/novamart` with pinned commit

This restores the Postgres dump that Redash queries, seeds the 9 dashboards, clones `novamart-sim/novamart` into `~/novamart-estate/workspace/novamart` at the pinned commit, and writes `~/novamart-estate/access-pack/` with the values the brief's placeholders refer to (your project as the warehouse, Redash URL and API key, workspace path) and rendered copies of the brief.

The estate lives outside this repo on purpose: run your agent from `~/novamart-estate/workspace/novamart` and never give it this repo, it has the gold claims and the released books. If you want the estate somewhere else, pass `--estate-dir /some/path` (the scripts remember it in `setup/.env`).

Setup never deletes anything in the estate it did not write itself: your run outputs, books and traces survive re-runs and a switch between local and cloud mode.

**To run the first script again**: just run the same command, it skips the tables which are already fully loaded (row count matches `counts.json`) and reloads only the missing or partial ones, so if the upload stops midway you don't lose anything.

**To wipe everything**: `docker compose -f setup/docker-compose.yml down -v` and `rm -rf ~/novamart-estate/workspace/novamart ~/novamart-estate/access-pack` (anything else you keep in the estate is left alone) for the local part, and delete the three datasets from your project to stop the storage cost: `bq rm -r -f -d your-project-id:novamart`, `bq rm -r -f -d your-project-id:novamart_analytics`, `bq rm -r -f -d your-project-id:novamart_logs`.

## Check it works

The second script runs `setup/verify_access.py` which calls your BigQuery project, redash and postgres instances to make sure they are healthy and prints the status, you should see something like this:

```bash
python ./setup/verify_access.py

# access pack mode: cloud-bigquery
#   [PASS] BigQuery         bigquery.googleapis.com: 3 datasets, novamart.orders has 9127 rows
#   [PASS] Redash           http://localhost:5050: 9 dashboards
#   [PASS] Codebase         ~/novamart-estate/workspace/novamart: HEAD 5ae1182
#   [PASS] Estate Postgres  127.0.0.1:15433: accepting connections
# all surfaces answer
```

Before running `bq` or your agent, source the access pack's env file; it sets your project for `bq` and the client libraries (and warns you if `gcloud` is not logged in)

```bash
source ~/novamart-estate/access-pack/env.sh
```

Then you can list the datasets to make sure it's working:

```bash
bq ls

#   datasetId
#  --------------------
#   novamart
#   novamart_analytics
#   novamart_logs
```

**About the service account key**: the brief says there is a key at `<access-pack>/sa-key.json`. In this mode that is your own credential, either you already did `gcloud auth application-default login` (then `bq` and all the client libraries just work), or you put your own key at `~/novamart-estate/access-pack/sa-key.json` and point `GOOGLE_APPLICATION_CREDENTIALS` at it. No anonymous credentials needed here.

Checkout the newly created `~/novamart-estate/access-pack/README.md` for more information.

## Notes

- Submissions mention which mode produced the runs (`environment_mode: cloud-bigquery` in `metadata.yaml`), the paper's baselines were run in this mode.
- Host ports: Redash 5050, estate Postgres 15433. Set `REDASH_PORT` or `ESTATE_PG_PORT` to choose others; if a default is busy, setup moves to the next free port and tells you. The chosen ports are recorded in `setup/.env` and in the access pack, so every later command agrees.
- `--no-download` in the second command reuses the data the first one downloaded, drop it if you are running the second command on a different machine.
- If you cannot get the role, please use local mode: `python setup/setup_local.py`.

