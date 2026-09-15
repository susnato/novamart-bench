# GCP setup

Loads the estate into your own BigQuery project, so agents use the real BigQuery API at your own scale and cost. Redash, the estate Postgres, and the repo checkout still run locally via `setup/setup_local.py`; only the warehouse moves to your cloud.

## Requirements

`gcloud` authenticated and `bq` installed; a project where you hold `roles/bigquery.user` (or anything granting `bigquery.datasets.create` and `bigquery.jobs.create`). Costs: BigQuery storage for about 2 GB, queries billed to your project.

## Run

```bash
python setup/setup_gcp.py --project your-project-id
```

Phase 0 checks your permissions via `testIamPermissions` and creates nothing on failure; each missing permission is reported with the exact grant command to ask your admin for. On success it creates the three datasets (`novamart`, `novamart_analytics`, `novamart_logs`; the names are fixed by the benchmark, only the project varies) and loads every table from the downloaded fixtures. Your project id becomes the `<warehouse-project>` value in your access pack.

If you cannot get the role, local mode needs no cloud at all: `python setup/setup_local.py`.
