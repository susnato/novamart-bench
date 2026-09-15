# Changelog

## 2026-09-16

- Canonical submissions: `results/verdicts.json` split into per-entry `submissions/*/judge_record.json` (values byte-identical, verified by reassembly; original released book names kept in each record's `released_book_names`); `results/claim_matrix.md` moved to `docs/`; `results/` removed. Verification now writes the full five-pass judge record into each entry alongside the derived majorities and stats. Notebook and all scripts read the per-entry records; self-tests reproduce the published entries exactly.

## 2026-09-15

- World repo release preparation: an internal infrastructure identifier in the world repo's `docs/data-access.md` was replaced with the fictional `novamart-warehouse` (only a single word change in the string), which re-hashed the six final commits. See the Verification section of the README for the hash map.
- claims: 23 hash references across 8 claim files updated to the current world history (7 in `07_recsys.yaml`, 5 in `02_orders_payments.yaml`, 4 in `09_dashboards.yaml`, 2 each in `05_products_catalog.yaml` and `08_jobs_scheduling.yaml`, 1 each in `03_finance_reporting.yaml`, `06_customers.yaml`, `10_fraud_pricing.yaml`); this covers `commit_hash` fields, one `git show` URI, and two prose excerpts. Claim text semantics, rubrics, and evidence chains unchanged.
- estate samples: the two history patch files renamed to their current hashes (`4bfcbe6-migrate-crontab-to-airflow.patch`, `41e3537-move-dashboards-to-redash.patch`) with their From headers updated to the current full shas.
- prompts: the commit pin in the brief updated from `2ae79e2` to `5ae1182` (one token). The August baseline runs used the pre-rewrite pin; the pinned trees are identical except the single identifier above.
- The nine released books are byte-unchanged and cite the original hashes.
- claims evidence SQL fix: three evidence queries (claims NB-02, NB-03, NB-05) selected `ts` from the log export tables, but the released log schema's column is `timestamp` (Cloud Logging sink envelope shape). The queries never executed as released; fixed to `timestamp`. Found while computing the parity goldens; all 36 evidence queries now execute against the warehouse.
- estate data scrub (applies to the distributed fixtures, not to payload content): the log export envelope fields (`logName`, `resource.labels.project_id`) on all 5,168,645 log rows carried the same internal infrastructure identifier as the world doc; replaced with `novamart-warehouse`, matching the world repo. Three `job_runs` rows from the `affinity_v2` crash incident captured a generation-machine filesystem path inside the traceback; replaced with the in-world path `/srv/novamart/repo/...`. `textPayload` and all application payload content are byte-unchanged; a full-corpus sweep (identifier, usernames, machine paths, secret patterns) is clean.
- setup/parity/goldens.json added: normalized results of all 36 evidence queries computed against the original warehouse, used by CI to verify the local emulator returns identical results.
