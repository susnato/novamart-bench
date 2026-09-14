# NovaMart estate samples

Samples from each surface of the frozen estate. The complete estate is released at publication.

- `repo/`: the complete application working tree at the evaluation pin `2ae79e2`, exactly what the evaluated systems saw (code, jobs, Airflow DAGs, routers, all nine dashboard SQL definitions, deploy config, docs), with a single identifier placeholdered: the warehouse project id in `docs/data-access.md`.
- `repo.bundle`: the git history (108 commits) up to the December 31 freeze commit; restore with `git clone repo.bundle novamart`.
- `history_patches/`: the two post-freeze commits that claim evidence chains cite (`57ea43a` dashboards to Redash, `43e54a1` crontab to Airflow), shipped as leak-free patch files with original hashes. Withheld until publication: one docs commit and the warehouse-backfill commit, both naming the real warehouse project; their end state is present in `repo/`.
- `tables/`: the first 40 rows of every application table (`public.*`, 12 tables) and analytics table (`analytics.*`, 20 tables), one TSV per table, plus the complete schema in `db_schema.sql`.
- `query_log_head.log`: the first 100 statements of the historical query log (3,597,650 statements in full).
- `app_log_head.jsonl`, `jobs_log_sample.jsonl`: the first 100 lines of the application and job logs (1,570,017 entries in full); the job-log sample additionally includes the December job-crash window with traceback paths normalized to /srv/.
- `dashboard_daily_kpis.json`: one dashboard exported from the BI instance (widgets, visualization, query).

