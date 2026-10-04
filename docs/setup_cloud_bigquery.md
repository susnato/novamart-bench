# Real BigQuery (`cloud-bigquery` mode)

Your warehouse in your own BigQuery project; Redash and the repo stay on your machine. Agents then hit the real BigQuery API, the same one the paper's baselines used, at whatever scale and cost you choose. Nothing else moves to the cloud: Redash and the estate Postgres run in docker on your machine, the repo is a local checkout, and to an agent those look exactly as they did in the original runs.

## Requirements

Tools as listed under [Before you start](../README.md#before-you-start) in the README, with `gcloud` logged in. Then a project where you hold `roles/bigquery.user` (or anything that grants `bigquery.datasets.create` and `bigquery.jobs.create`). Docker for the local half. Cost: about 2 GB of BigQuery storage, and whatever queries you run, billed to your project.

## Run

Two commands. The first loads the warehouse, the second brings up the local half and writes your access pack:

```bash
python setup/setup_gcp.py --project your-project-id
python setup/setup_local.py --warehouse-project your-project-id --no-download
```

`setup_gcp.py` first checks your permissions (`testIamPermissions`) and stops before creating anything if one is missing, printing the exact grant command to send to your admin. Then it creates the three datasets (`novamart`, `novamart_analytics`, `novamart_logs`; the names are fixed, only the project varies), loads every table from the downloaded data, and creates the 5 estate views from `setup/views/`.

`setup_local.py --warehouse-project` starts Redash and the estate Postgres (no emulator), checks out the repo at the pin, seeds the dashboards, writes `setup/access-pack/` with your project as `<warehouse-project>`, and runs `setup/verify_access.py` against everything.

## Credentials

The brief tells the agent to find a service-account key at `<access-pack>/sa-key.json`. In this mode that is your own credential: either `gcloud auth application-default login`, or a key of your own saved as `setup/access-pack/sa-key.json` with `GOOGLE_APPLICATION_CREDENTIALS` pointing at it. `source setup/access-pack/env.sh` sets the project for every client and warns if gcloud is not logged in.

## If it gets interrupted

Run the same `setup_gcp.py` command again. It skips every table whose row count already matches `counts.json` and reloads only the tables that are missing or partial, so nothing finished is transferred twice.

If you cannot get the role, please use local mode: `python setup/setup_local.py`.
