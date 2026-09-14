"""One-shot warehouse backfill: serving Postgres -> BigQuery.

Triggered manually (schedule=None) during the Jan 2020 platform migration;
kept for re-runs if the warehouse ever needs a rebuild from the serving DB.
"""
from datetime import datetime

from airflow import DAG
from airflow.operators.bash import BashOperator

with DAG(
    dag_id="warehouse_backfill",
    schedule=None,
    start_date=datetime(2020, 1, 1),
    catchup=False,
    tags=["novamart", "migration"],
) as dag:
    run = BashOperator(task_id="run",
                       bash_command="python -m novamart.jobs.warehouse_backfill")
