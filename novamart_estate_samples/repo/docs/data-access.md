# Data access (post-migration)

As of Jan 2020 the data platform moved off the single prod box. Where things
live now:

| Surface | Where | Notes |
|---|---|---|
| Serving DB (Postgres) | Cloud SQL `novamart-prod-replica`, db `novamart` | the store this codebase reads/writes; read-only roles for analytics |
| Warehouse | BigQuery project `<warehouse-project>` | dataset `novamart` (12 app tables), `analytics` (20 tables + views) |
| Query history | BQ `novamart_logs.db_queries` | Postgres statement log export (textPayload = raw line) |
| App logs | BQ `novamart_logs.app_events` | jsonPayload = the app's JSONL records |
| Job runs | BQ `novamart_logs.job_runs` + Airflow on `novamart-ops` | Airflow UI has per-run task logs |
| Dashboards | Redash on `novamart-ops` | moved out of dashboards/ in this repo — see git history for the old SQL files |
| Schedules | Airflow on `novamart-ops` (`airflow/dags/` here) | crontab.txt is retired |

Access to `novamart-ops` (no public IP) is via IAP tunnel:

    gcloud compute start-iap-tunnel novamart-ops 8080 --local-host-port=localhost:8080  # Airflow
    gcloud compute start-iap-tunnel novamart-ops 5000 --local-host-port=localhost:5000  # Redash

The warehouse was loaded from the serving DB by `novamart.jobs.warehouse_backfill`
(see `airflow/dags/warehouse_backfill_dag.py` for the run wrapper).
