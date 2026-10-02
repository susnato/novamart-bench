# GCP setup

This loads the estate into a BigQuery project of your own, so agents hit the real BigQuery API at whatever scale and cost you choose. Redash, the estate Postgres and the repo checkout still run locally through `setup/setup_local.py`; only the warehouse moves to the cloud.

## Requirements

`gcloud` logged in and `bq` installed, plus a project where you hold `roles/bigquery.user` (or anything that grants `bigquery.datasets.create` and `bigquery.jobs.create`). Cost: about 2 GB of BigQuery storage, and whatever queries you run, billed to your project.

## Run

```bash
python setup/setup_gcp.py --project your-project-id
```

The script first checks your permissions (`testIamPermissions`) and stops before creating anything if one is missing, printing the exact grant command to send to your admin. Then it creates the three datasets (`novamart`, `novamart_analytics`, `novamart_logs`; the names are fixed, only the project varies), loads every table from the downloaded data, and creates the 5 estate views from `setup/views/`. Your project id becomes the `<warehouse-project>` value in your access pack.

## If it gets interrupted

Run the same command again. It skips every table whose row count already matches `counts.json` and reloads only the tables that are missing or partial, so nothing finished is transferred twice.

If you cannot get the role, please use local mode: `python setup/setup_local.py`.
