# Provenance and release integrity

This document records exactly what changed between the internal runs that produced the published numbers and the artifacts released here, and why none of it affects the benchmark.

## The identifier replacement

During release preparation, an internal infrastructure identifier in the world repo's `docs/data-access.md` was replaced with the fictional `novamart-warehouse` (only a single word change in the string). This re-hashed the six final commits of the world repo. The claims' `commit_hash` fields and the brief's commit pin were updated to the current hashes; the nine released books are the verbatim outputs of the original runs and cite the original hashes, as does the paper's printed brief. The mapped commits are content-identical except for that one identifier.

The same identifier also appeared in the distributed log fixtures' envelope metadata (`logName` and resource labels) and was replaced there identically, and three `job_runs` rows carried a generation-machine file path inside a traceback, replaced with the in-world path `/srv/novamart/repo/...`. `textPayload` and all application payload content are byte-unchanged; a full-corpus sweep (identifier, usernames, machine paths, secret patterns) is clean.

## Commit hash map

| Original hash (cited in released books and the paper) | Current hash | Commit |
|---|---|---|
| `1179287` | `d398b0d` | docs: data access after the platform migration |
| `57ea43a` | `41e3537` | chore: move dashboards to Redash |
| `43e54a1` | `4bfcbe6` | chore: migrate schedules from crontab to Airflow |
| `2ae79e2` (full: `2ae79e23690f7ef09a2e9231fdfa3a2cdb84be00`) | `5ae1182` (full: `5ae11821806a396aac10115e03863b8c68c1bfcc`) | feat: warehouse backfill job (serving Postgres -> BigQuery) |
| `2239d10` | `99003c3` | docs: warehouse analytics dataset is novamart_analytics |
| `2d57fa9` | `20e066f` | fix: backfill loads analytics tables into novamart_analytics |

## What was updated to match

The update touched 23 hash references across 8 claim files (`commit_hash` fields, one `git show` URI, and two prose excerpts), the two history patch files in the estate samples (renamed to their current hashes, From headers updated), and the brief's commit pin (`2ae79e2` to `5ae1182`). Claim text semantics, rubrics, and evidence chains are unchanged. The August baseline runs used the pre-rewrite pin; the pinned trees are identical except for the single identifier above.

| Claim file | References updated |
|---|---|
| `07_recsys.yaml` | 7 |
| `02_orders_payments.yaml` | 5 |
| `09_dashboards.yaml` | 4 |
| `05_products_catalog.yaml` | 2 |
| `08_jobs_scheduling.yaml` | 2 |
| `03_finance_reporting.yaml` | 1 |
| `06_customers.yaml` | 1 |
| `10_fraud_pricing.yaml` | 1 |

## Evidence SQL fix

Three evidence queries (claims NB-02, NB-03, NB-05) selected `ts` from the log export tables, but the released log schema's column is `timestamp` (Cloud Logging sink envelope shape); the queries never executed as released and were fixed during release preparation. All 36 evidence queries now execute against the warehouse, and their normalized results are pinned in `setup/parity/goldens.json`, which CI uses to verify the local emulator returns identical results.

## What this means for the benchmark

None of the above changes the essence of the benchmark in any way. It is an artifact naming change: one identifier string, propagated consistently through the history and the fixtures, plus a fix to three queries that had never been runnable. It is a very small change. The claims' semantics, the books' content, the estate's payload data, and every published number are exactly what the original runs produced, and all of it is recomputable from this repo.
