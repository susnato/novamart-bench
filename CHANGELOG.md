# Changelog

## 2026-09-15

- World repo release preparation: an internal infrastructure identifier in the world repo's `docs/data-access.md` was replaced with the fictional `novamart-warehouse` (only a single word change in the string), which re-hashed the six final commits. See the Verification section of the README for the hash map.
- claims: 23 hash references across 8 claim files updated to the current world history (7 in `07_recsys.yaml`, 5 in `02_orders_payments.yaml`, 4 in `09_dashboards.yaml`, 2 each in `05_products_catalog.yaml` and `08_jobs_scheduling.yaml`, 1 each in `03_finance_reporting.yaml`, `06_customers.yaml`, `10_fraud_pricing.yaml`); this covers `commit_hash` fields, one `git show` URI, and two prose excerpts. Claim text semantics, rubrics, and evidence chains unchanged.
- estate samples: the two history patch files renamed to their current hashes (`4bfcbe6-migrate-crontab-to-airflow.patch`, `41e3537-move-dashboards-to-redash.patch`) with their From headers updated to the current full shas.
- prompts: the commit pin in the brief updated from `2ae79e2` to `5ae1182` (one token). The August baseline runs used the pre-rewrite pin; the pinned trees are identical except the single identifier above.
- The nine released books are byte-unchanged and cite the original hashes.
