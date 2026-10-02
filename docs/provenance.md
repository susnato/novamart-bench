# Provenance and release integrity

What changed between the internal runs behind the published numbers and what is released here, and why none of it touches the benchmark.

## The short version

Before release we renamed one internal infrastructure identifier to the fictional `novamart-warehouse`. The string appeared in one doc file inside the world repo and in the envelope metadata of the exported logs. Renaming it in the repo re-hashed the last six commits, so every place that cited those hashes had to be updated. We also fixed three evidence queries that had never been runnable. That is the whole list.

## The identifier rename

The world repo's `docs/data-access.md` carried the identifier. We replaced that one word with `novamart-warehouse`. Because git hashes depend on content, the six commits from the one that wrote that file onward got new hashes. The commits are otherwise identical: same trees, same messages, same authors, same dates.

The released books were produced in August against the old hashes and cite them; so does the brief printed in the paper. We left the books untouched (they are the verbatim run outputs) and updated the claims and the shipped brief to the new hashes instead. The map is below, so anyone reading a book can follow its citation to the current commit.

| Original hash (cited in released books and the paper) | Current hash | Commit |
|---|---|---|
| `1179287` | `d398b0d` | docs: data access after the platform migration |
| `57ea43a` | `41e3537` | chore: move dashboards to Redash |
| `43e54a1` | `4bfcbe6` | chore: migrate schedules from crontab to Airflow |
| `2ae79e2` (full: `2ae79e23690f7ef09a2e9231fdfa3a2cdb84be00`) | `5ae1182` (full: `5ae11821806a396aac10115e03863b8c68c1bfcc`) | feat: warehouse backfill job (serving Postgres -> BigQuery) |
| `2239d10` | `99003c3` | docs: warehouse analytics dataset is novamart_analytics |
| `2d57fa9` | `20e066f` | fix: backfill loads analytics tables into novamart_analytics |

The same identifier also sat in the exported log fixtures, in the Cloud Logging envelope fields (`logName` and resource labels). We replaced it there the same way. Three `job_runs` rows also carried a file path from the machine that generated the estate inside a traceback; those now show the in-world path `/srv/novamart/repo/...`. Nothing in `textPayload` or in any application payload changed. We then swept the whole corpus for the identifier, usernames, machine paths and secret patterns; it is clean.

## What we updated to match the new hashes

23 hash references across 8 claim files (`commit_hash` fields, one `git show` URI, two prose excerpts), the two history patch files in the estate samples (renamed to the new hashes, `From` headers updated), and the brief's commit pin (`2ae79e2` to `5ae1182`). Claim text, rubrics and evidence chains did not change. The August baseline runs used the old pin; the two pinned trees differ only in that one word.

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

## The evidence SQL fix

Three evidence queries (NB-02, NB-03, NB-05) selected a column called `ts` from the log export tables. The released log schema calls that column `timestamp` (it is the Cloud Logging sink envelope), so those three queries had never actually run. We fixed them during release preparation. All 36 evidence queries now execute against the warehouse, and their normalized results are pinned in `setup/parity/goldens.json`; CI checks every week that the local emulator returns the same results.

## What this means for the benchmark

Nothing about the benchmark changed. One identifier string was renamed and propagated consistently through the history and the fixtures, and three queries that had never run were made to run. It is a very small change. The claims, the books, the estate's payload data and every published number are exactly what the original runs produced, and all of it can be recomputed from this repo.
