"""Airflow wrapper for novamart.jobs.top_sellers (migrated from crontab.txt, Jan 2020)."""
from datetime import datetime

from airflow import DAG
from airflow.operators.bash import BashOperator

with DAG(
    dag_id="top_sellers",
    schedule="45 6 * * *",
    start_date=datetime(2019, 9, 15),
    catchup=False,
    tags=["novamart", "daily"],
) as dag:
    run = BashOperator(task_id="run", bash_command="python -m novamart.jobs.top_sellers")
