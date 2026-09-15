# Novamart tribal knowledge

Run UUID: `5891a8ad-1237-40d2-9d14-f4585fc1fd8f`. Investigation started at `2026-08-27 17:08:40 IST`. The repository was read at the required pinned revision `2ae79e23690f7ef09a2e9231fdfa3a2cdb84be00`; the serving database, warehouse, logs, and Redash were inspected read-only. [Evidence: repository HEAD `2ae79e23690f7ef09a2e9231fdfa3a2cdb84be00`; Redash data-source and query metadata; BigQuery `INFORMATION_SCHEMA` queries.]

## 1. Summary

Novamart has no single universal “revenue” number. The official current finance surface is `novamart_analytics.statements_final`, the historical as-published surface is `novamart.statements`, payment movement is in `novamart.payments`, and executive/product dashboards calculate separate operational revenue with different filters. [Evidence: Redash query 9 `statements_final`; views `novamart_analytics.statements_corrected` and `novamart_analytics.statements_final`; queries `statements_all`, `finance_reconciliation`, and `dashboard_cleanup_impact`; commit `a576d0d`.]

For a month that has closed and been published, answer in two numbers: “as published” from `novamart.statements`, and “currently restated” from `novamart_analytics.statements_final`. Then disclose that `statements_final` applies statement overrides and booked chargebacks but does **not** subtract status-based cancellations/refunds or negative gateway-refund payments. [Evidence: view DDLs for `statements_corrected`, `statements_final`, and `refunds_unified`; `novamart/jobs/monthly_statement.py` at `2ae79e2`; queries `statements_all`, `statement_adjustments`, and `finance_reconciliation`; commits `cd559d3` and `a3bffec`.]

The published/restated monthly figures in the snapshot are:

| Month | As-published gross / fee / net | Current final gross / fee / net | Interpretation | Evidence |
|---|---:|---:|---|---|
| 2019-09 | 2,702.00 / 78.36 / 2,623.64 | 2,702.00 / 78.36 / 2,623.64 | All 12 September orders are now status 2 or 3, but the append-only statement preserves their status at publication time. | `novamart.statements`; `novamart_analytics.statements_final`; queries `orders_month_status`, `statements_all`, `finance_reconciliation`; app-event first cancellation/refund dates. |
| 2019-10 | 1,230,332.43 / 35,679.64 / 1,194,652.79 | 1,226,764.86 / 35,679.50 / 1,191,085.36 | The fee override adds 0.14 to net, then 3,567.57 of chargebacks reduces gross and net. | Queries `statements_all`, `statement_adjustments`; views `statements_corrected`, `statements_final`; commits `a92c96d`, `cd559d3`. |
| 2019-11 | 1,101,397.01 / 32,110.92 / 1,069,286.09 | Same | The stored audit correction delta is zero; there are no booked chargebacks against November orders. | Queries `statements_all`, `statement_adjustments`; table `novamart_analytics.statement_corrections`. |
| 2019-12 | Not yet published in this snapshot | Not available | At the data cutoff, status-1 order gross/fee/net is 552,328.93 / 16,600.26 / 535,728.67; another 40,213.29 gross is status 6 and would be excluded by the statement job. | Queries `finance_reconciliation`, `orders_month_status`, `finance_status_payment_detail`; `monthly_statement.py`; data cutoff `2019-12-31 23:57:06 UTC` in logs. |

The most important trust warnings are:

1. `statements_final` is the company-approved current finance surface, but it is not a complete economic-net calculation because ordinary refunds are reported separately and gateway refunds do not reduce statement gross/net. [Evidence: Redash queries 6 and 9; view DDLs `refunds_unified` and `statements_final`; `monthly_statement.py`; query `finance_reconciliation`.]
2. The refunds dashboard triple-counts three gateway-refunded orders: nine negative payment rows represent three orders, each repeated three times; the displayed 1,843.59 gateway-refund total is 1,229.06 above one copy per order. [Evidence: Redash query 6; queries `refunds_month_kind` and `refund_double_count`; `payments_webhook.py`; nine `gateway_refund` app events.]
3. Best sellers, brand revenue, and category revenue do not filter order status. In the anchored last seven days, best-sellers product `1005284` ranks third with 5,096.14 revenue and zero paid units because its orders are held. [Evidence: Redash queries 2–4; query `dashboard_best_sellers`; status 6 definition in `fraud_score.py`.]
4. The same product dashboards omit the application’s excluded-SKU filter. SKU `1002544`, explicitly excluded from daily reports, ranks sixth in the anchored best-sellers result; the two excluded SKUs contribute 30,935.57 of status-1 revenue over the anchored last 30 days. [Evidence: `novamart/constants.py`; `daily_report.py`; Redash query 2; queries `dashboard_best_sellers` and `excluded_sku_impact`.]
5. The nightly active-customer KPI, daily exec active customers, and board actives are different metrics. At the snapshot endpoint they are 1,152 in the latest stored KPI, 54 on the latest dashboard day, and 0 under the board query’s email exclusions. [Evidence: Redash queries 1 and 5; `kpi_daily.py`; queries `active_customer_definitions`, `board_filter_diagnostics`.]
6. All 38,950 stored user emails use filtered example domains, so `contactable_users` returns zero despite 24,193 marketing opt-ins; the digest job uses a different rule and records 40 recipients. [Evidence: view `novamart_analytics.contactable_users`; queries `contactable_diagnostics`, `email_domain_summary`, `digest_history`; `email_digest.py`.]
7. Recommendation serving is version 2.0.0 backed by `product_affinity_v2`; v4 trains nightly but is flag-disabled. Its current scores preserve affinity-v2 rank order exactly, so even enabling it would not change candidate ranking. [Evidence: `deploy/flags.env`; `similar.py`; `model_train.py`; queries `model_rank_equivalence`, `model_registry`, `db_table_reads`; commit `a1946ff`.]
8. The January Airflow migration dropped the former 17:00 intraday run and does not declare an explicit DAG timezone. Verify scheduler timezone before changing schedules because the retired cron explicitly described its times as local. [Evidence: commit `43e54a1`; `crontab.txt`; `airflow/dags/intraday_report_dag.py`; all DAG definitions at `2ae79e2`.]

## 2. Why this project

The project is necessary because names that look equivalent are not equivalent in implementation. “Revenue” can mean statement gross, restated net, payment net, daily-report revenue, or raw dashboard order-line revenue; “active customer” has three competing definitions; “best seller” is revenue-ranked in Redash but unit-ranked in the batch table. [Evidence: Redash queries 1, 2, 5, 8, and 9; `monthly_statement.py`, `daily_report.py`, `top_sellers.py`, `kpi_daily.py`; queries `statements_all` and `active_customer_definitions`.]

The system also carries historical behavior forward. Statements are append-only snapshots, legacy single-item orders coexist with `order_lines`, category display names are effective-dated, and both old and new recommendation pipelines still run. [Evidence: tables `novamart.statements`, `novamart.orders`, `novamart.order_lines`, `novamart_analytics.category_names`, `category_name_history`, `product_affinity`, `product_affinity_v2`; commits `92596dc`, `33054cd`; Airflow DAGs `affinity` and `affinity_v2`.]

Finally, dashboard cleanup rules encode business decisions that are not obvious from schema names: Lucente and Jetem are hidden, one QA user is excluded, two internal SKUs are hidden only by some reports, and order status is intentionally or accidentally ignored by several executive queries. [Evidence: `constants.py`; Redash queries 2–5; commits `b59f077`, `1169e40`; queries `dashboard_cleanup_impact`, `excluded_sku_impact`.]

The practical goal is therefore not merely to reproduce a number, but to state its consumer, time grain, status policy, itemization policy, exclusions, timezone, restatement layer, and freshness in the same answer. [Evidence: divergences documented by Redash queries 1–9, `monthly_statement.py`, `daily_report.py`, and query `active_customer_definitions`.]

## 3. Business understanding

### Order-to-money lifecycle

1. A product view, cart add, or order callback lazily creates the numeric `users` and `products` records on first sight; `users.created_at` is therefore a first-seen timestamp, not necessarily an intentional registration. [Evidence: `catalog.py::_user_row`, `ensure_entities`, `view_product`; `carts.py`; `orders.py`; commit `2ae79e2`.]
2. `/orders` is a payment-gateway callback. It locks session and payment reference, creates a status-0 order, writes an order line and payment, then moves the order to status 1; a replayed reference is idempotent for the original payment path. [Evidence: `orders.py::create_order`; commit `b676969`; app events `order_created`, `order_callback_replayed`.]
3. Since `5d1300d`, callbacks for the same user/session within 15 minutes append lines and payments to one order and increase `orders.price`; 173 orders currently have multiple lines, and total line-or-legacy revenue exactly equals total `orders.price` at 2,926,973.66. [Evidence: `orders.py`; queries `itemization_summary`, `base_date_ranges`; commit `5d1300d`.]
4. Cancellation changes status to 2 without a negative payment; the original refund endpoint changes status to 3 without a negative payment; the later gateway-refund webhook writes a negative payment without changing order status. [Evidence: `orders.py::cancel_order`, `refund_order`; `payments_webhook.py`; commits `d87cb3d`, `c49a7bb`.]
5. Nightly fraud scoring can move a status-1 order to status 6 after payment. Twelve orders totaling 40,213.29 remain held at the snapshot endpoint. [Evidence: `fraud_score.py`; `constants.py`; queries `order_status_summary`, `orders_month_status`; commits `e4656fb`, `1cb8721`.]

The current order population is 9,127 orders: 9,033 paid/status 1, 54 cancelled/status 2, 28 refunded/status 3, and 12 held/status 6. There are 9,361 payment rows because multi-item order appends add 225 extra payments and gateway refunds add nine negative rows. [Evidence: queries `order_status_summary`, `payments_integrity`, `itemization_summary`; app-event counts `order_appended=225`, `gateway_refund=9`.]

### What “revenue” means

| Question | Use | Definition | Do not confuse with | Evidence |
|---|---|---|---|---|
| What did the monthly close originally publish? | `novamart.statements` | Append-only job snapshot: status-1 order price by Eastern month, collected payment fees, gross minus fee. | Current order statuses or refunds discovered later. | `monthly_statement.py`; table `novamart.statements`; query `statements_all`. |
| What is the approved current finance restatement? | `novamart_analytics.statements_final` | Published statement with overrides, then chargebacks assigned to original order month. | A complete refund-adjusted cash ledger. | View DDLs; Redash query 9; commits `cd559d3`, `a576d0d`. |
| What cash-like movements were mirrored? | `novamart.payments` | One positive row per transaction/line plus negative gateway-refund rows; net equals gross minus fee on every row. | A deduplicated gateway ledger. | Query `payments_integrity`; `orders.py`; `payments_webhook.py`. |
| What does the exec seven-day widget show? | Redash query 8 | Latest completed daily snapshots for the prior six Eastern calendar days plus latest intraday snapshot for today. | Rolling 7×24-hour raw orders. | Redash query 8; tables `report_rows`, `report_rows_intraday`; commit `3eced24`. |
| What do product dashboards call revenue? | Redash queries 2–4 | Raw item/legacy prices in rolling 7- or 30-day windows, with QA and brand exclusions but no status or SKU filter. | Paid revenue or the daily-report definition. | Redash queries 2–4; query `dashboard_cleanup_impact`. |

For a tenured answer, lead with the official finance surface and then reconcile. October illustrates the method: original gross 1,230,332.43 includes all 3,765 orders as they stood at close; today 70 of those orders are status 2/3, the fee was corrected by 0.14, and 3,567.57 of booked chargebacks produced final gross 1,226,764.86 and final net 1,191,085.36. [Evidence: queries `orders_month_status`, `statements_all`, `statement_adjustments`, `finance_reconciliation`; view `statements_final`.]

Do not silently subtract `refunds_unified` from `statements_final`: the view can contain repeated gateway callbacks, status-based cancellation amounts may represent reversals already handled elsewhere, and the approved restatement policy currently subtracts only chargebacks. Show the components and ask whether the consumer wants approved reporting net, processor movement, or an economic refund-adjusted analysis. [Evidence: view DDLs `refunds_unified` and `statements_final`; query `refund_double_count`; `payments_webhook.py`; commit `a576d0d`.]

### Product and merchandising behavior

The executive best-sellers query is a rolling seven-day product list ordered by revenue, despite exposing a `units` column. It uses `order_lines` for new orders and an `orders` fallback for legacy orders, excludes user `424242` and brands Lucente/Jetem, but applies no status or excluded-SKU filter. [Evidence: Redash query 2; commits `92596dc`, `b59f077`, `1169e40`.]

The nightly `top_products` job is a different metric: prior Eastern calendar day, status 1 only, top 50 ordered by units, and it counts `orders.product_id` rather than itemized `order_lines`. It can undercount or misattribute multi-item sales and is not the source for the Redash best-sellers dashboard. [Evidence: `top_sellers.py`; Redash query 2; table `novamart.top_products`; commit `9a51155`.]

Brand revenue is a rolling 30-day itemized query that excludes two QA identifiers and two hidden brands but includes blank brands, held orders, and internal SKUs. In the anchored snapshot, Apple leads with 236,606.73 displayed revenue versus 224,951.43 status-1 revenue; blank brand contributes 17,585.39 displayed revenue. [Evidence: Redash query 3; query `dashboard_brand_revenue`; commit `adbcb7e`.]

Category revenue uses effective-dated mappings from `category_names` plus `category_name_history`, choosing the mapping valid on the item date; unmapped data becomes `other`. The snapshot contains 33,514 products with blank category, and the anchored dashboard assigns 93,661.73 to `other`. [Evidence: Redash query 4; queries `dashboard_category_revenue`, `product_data_quality`; commit `33054cd`.]

Catalog quality is material: of 81,018 products, 17,442 have blank brand, 33,514 have blank category, and 907 have zero list price; the `blank_brand_products` audit table contains 5,972 captured rows rather than the full current blank-brand population. [Evidence: query `product_data_quality`; tables `novamart.products`, `novamart_analytics.blank_brand_products`.]

### Customer behavior

The `users` table has 38,950 numeric shopper identities created on first sight, while the registered-accounts beta has only 30 UUID accounts and 30 mappings. All 30 registered users are status-1 buyers with 18,155.71 recorded order revenue. [Evidence: `catalog.py`, `accounts.py`; queries `users_summary`, `registered_conversion`; tables `accounts`, `account_map`.]

The current FastAPI app does not mount `accounts`, `users`, or `reports` routers even though those modules exist, so those endpoints are not reachable from the pinned application entrypoint. [Evidence: `novamart/app.py` at commit `2ae79e2`; router files `accounts.py`, `users.py`, `reports.py`.]

The customer metrics intentionally disagree:

| Name/consumer | Exact meaning | Snapshot result | Evidence |
|---|---|---:|---|
| Nightly active customers | Distinct status-1 ordering users in trailing 30×24 hours; no QA, brand, or email cleanup. | 1,152 in latest stored run; 1,150 when re-anchored at last order timestamp. | `kpi_daily.py`; table `kpi_daily`; query `active_customer_definitions`; commit `14726e7`. |
| Exec daily active customers | Distinct ordering users per Eastern day over 14 days; no status filter; excludes user 424242 and Lucente/Jetem orders. | 54 on latest order day. | Redash query 5; query `active_customer_definitions`. |
| Board active customers | Distinct users with status not in 0/2/3 over trailing 30 days, excluding known test users and extensive email patterns. | 0 because all candidate emails match excluded example domains. | Redash query 1; queries `active_customer_definitions`, `board_filter_diagnostics`; commit `2dde4f0`. |
| Contactable customers | Marketing opt-in plus valid email, excluding example domains. | 0 despite 24,193 opt-ins. | View `contactable_users`; queries `users_summary`, `contactable_diagnostics`, `email_domain_summary`; commit `e10cb0c`. |
| Registered buyers | Status-1 buyers mapped from UUID accounts to numeric users through shared email. | 30 buyers, 18,155.71 revenue. | Redash query 7; query `registered_conversion`; commits `d6e34c6`, `b975479`. |

The “funnel” rollup is not a conventional multi-step funnel: it sessionizes only cart and order events from the last day, with a 120-minute inactivity gap, and stores sessions plus distinct active users. It does not measure product views, checkout starts, or stage conversion. [Evidence: `funnel.py`; table `daily_funnel`; commit `f915c1b`; query `funnel_summary`.]

## 4. Metrics

### Metric contract and trust matrix

| Metric | Grain/window | Inclusion/exclusion | Source of truth for its consumer | Trust guidance | Evidence |
|---|---|---|---|---|---|
| Published statement net | Eastern calendar month, snapshot at run | Status 1 at run; collected fee rows | `novamart.statements` | Trust to reproduce an old deck, including known old mistakes. | `monthly_statement.py`; `statements`; Redash/history commit `a576d0d`. |
| Final statement net | Month | Published/overridden statement less booked chargebacks | `statements_final` | Trust as approved current finance number; pair with refund disclosure. | View DDL; Redash query 9; `statement_adjustments`. |
| Refund total | Refund event month | Status 2/3 order amount plus every negative payment row | `refunds_unified`, Redash query 6 | Do not trust without deduplicating gateway events by order/refund identity. | View DDL; `refund_double_count`; `payments_webhook.py`. |
| Exec revenue widget | Seven Eastern calendar dates | Latest daily snapshots, current-day intraday; daily-report exclusions | `report_rows` + `report_rows_intraday`, Redash query 8 | Trust snapshot selection after `3eced24`; remember status 6 is included by producer. | Redash query 8; `daily_report.py`; `intraday_report.py`. |
| Best sellers | Rolling seven days | QA/brand cleanup; no status/SKU filter | Redash query 2 | Do not interpret as paid sales or clean merchandising demand. | Redash query 2; `dashboard_best_sellers`. |
| Brand/category revenue | Rolling 30 days | Itemized; QA/brand cleanup; no status/SKU filter | Redash queries 3/4 | Useful for the exec convention only; disclose held/test contribution. | Redash queries 3/4; `dashboard_cleanup_impact`, `excluded_sku_impact`. |
| Nightly top sellers | Prior Eastern day | Status 1; order rows, not item rows | `top_products` | Not equivalent to Redash; unsafe for multi-item accuracy. | `top_sellers.py`; `top_products`. |
| Trending | Rolling 30×24 hours | Status 1, at least five order rows, recency decay, top 50 | `trending_daily` | Trust as a heuristic fallback list, not a causal recommendation. | `trending.py`; query `operational_outputs`; commit `f563dea`. |
| Nightly active customers | Trailing 30×24 hours | Status 1 only | `kpi_daily` | Stable internal KPI, but includes test/internal users. | `kpi_daily.py`; `metrics_definitions.md`; `active_customer_definitions`. |
| Exec daily actives | Eastern day | Any status; QA/brand cleanup | Redash query 5 | Daily ordering users, not a 30-day active KPI. | Redash query 5. |
| Board actives | Trailing 30×24 hours | Non-0/2/3, test table and email cleanup | Redash query 1 | Returns zero on synthetic example-domain data; do not present without diagnosis. | Redash query 1; `board_filter_diagnostics`. |
| Contactable | Current users | Opt-in, valid address, non-example domain | `contactable_users` | Correct for its strict policy; zero in this simulation. | View DDL; `contactable_diagnostics`. |

### Dashboard-specific reconciliation

Over the anchored last 30 days, raw itemized revenue is 577,963.53; status-1 revenue is 537,750.24; the entire 40,213.29 gap is the held-order population. Hidden brands contribute 7,569.56 and QA contributes 39.96, leaving 570,354.01 under the product-dashboard cleanup convention before any SKU cleanup. [Evidence: queries `dashboard_cleanup_impact`, `dashboard_category_revenue`, `order_status_summary`.]

The daily report producer excludes statuses 0/2/3, but not status 6, and it excludes SKUs `1004856` and `1002544` plus brands Lucente/Jetem and `analytics.test_users`. Consequently, daily KPI revenue and raw product-dashboard revenue can disagree even for the same dates. [Evidence: `constants.py`; `daily_report.py`; Redash queries 2–5.]

Daily and intraday report tables are append-only. The snapshot has one daily version for each of 92 days and 47 intraday versions across 24 days; Redash correctly selects the latest `created_at` per date after the historical double-count fix. [Evidence: query `report_snapshot_health`; Redash queries 5 and 8; commit `3eced24`.]

### Metric change history

| Date/commit | Definition change | Consequence | Evidence |
|---|---|---|---|
| 2019-10-08 `83fb3ed` | Added internal SKU exclusions. | Daily reports omit SKUs that current product dashboards still include. | Commit `83fb3ed`; `constants.py`; Redash query 2. |
| 2019-10-25 `ba1fbfa` | Hid Lucente. | Executive/report revenue excludes partnership inventory. | Commit `ba1fbfa`; later `1169e40`. |
| 2019-11-02 `a92c96d` | Monthly fee uses collected payment fees. | October later needed a 0.14 override. | Commit `a92c96d`; `statement_overrides`. |
| 2019-11-05 `102c9b4` | Fixed Eastern local-day UTC window across DST. | Daily boundaries should use `timeutil.local_day_window_utc`. | Commit `102c9b4`; `timeutil.py`. |
| 2019-11-18 `11c0a42` | Excluded cancelled/refunded statuses from daily report. | Status 6, added later, remains included. | Commit `11c0a42`; `constants.py`; `fraud_score.py`. |
| 2019-11-19 `1233af8` | Removed 500-row scan cap from report query. | Busy-day undercount fixed; unused constant remains. | Commit `1233af8`; `daily_report.py`. |
| 2019-11-20 `12e1c68` | Fee became 2.9% + 0.30. | Statement expected-fee logic is time-dependent at Eastern 2019-11-20. | Commit `12e1c68`; `monthly_statement.py`. |
| 2019-11-22 `5d1300d` | Same-session callbacks merge into itemized orders. | Reports need `order_lines` plus legacy fallback. | Commit `5d1300d`; table date range; `itemization_summary`. |
| 2019-11-27 `b59f077` | Added QA cleanup. | Reports and dashboards omit known smoke traffic under different mechanisms. | Commit `b59f077`; Redash queries 2–5. |
| 2019-12-05 `92596dc` | Reports/dashboards became itemized. | Legacy fallback remains mandatory. | Commit `92596dc`; Redash queries 2–4. |
| 2019-12-08 `a2e0013` | Added intraday snapshots. | Today can be shown before daily close; multiple intraday versions accumulate. | Commit `a2e0013`; `report_rows_intraday`. |
| 2019-12-09 `cd559d3` | Added chargebacks/final statements. | Current finance number can differ from published snapshot. | Commit `cd559d3`; view `statements_final`. |
| 2019-12-15 `1169e40` | Added Jetem to denylist. | Product/report metrics hide both Lucente and Jetem. | Commit `1169e40`. |
| 2019-12-24 `3eced24` | Revenue widget selects latest closed/current snapshots. | Historical intraday snapshots no longer double-count final days. | Commit `3eced24`; Redash query 8. |

## 5. System

### Runtime architecture

The application is FastAPI over a Postgres/Cloud SQL serving database. Application and batch SQL are logged with actor tags, and scheduled jobs write their operational tables directly in Postgres using autocommit connections. [Evidence: `README.md`; `app.py`; `db.py`; `novamart_logs.db_queries_normalized`; query `db_actor_summary`.]

All nine inspected Redash queries use data source 1, `novamart serving (Cloud SQL)`, not BigQuery. The dashboards are therefore direct consumers of serving Postgres tables/views; BigQuery is an analytical copy used for this investigation. [Evidence: Redash `data_sources` metadata and queries 1–9, each `data_source_id=1`; commit `57ea43a`.]

BigQuery contains 12 app tables in `novamart`, analytics tables/views in `novamart_analytics`, and exported logs in `novamart_logs`. The pinned warehouse loader is a manual one-shot full export/load from Cloud SQL, and the provided data ends on 2019-12-31. [Evidence: `INFORMATION_SCHEMA.TABLES`; `warehouse_backfill.py`; `warehouse_backfill_dag.py schedule=None`; commit `2ae79e2`; query `base_date_ranges`.]

```text
vendor/product events + payment callbacks
                  |
                  v
FastAPI ----------> Cloud SQL/Postgres <---------- scheduled Python jobs
                         |   |                           |
                         |   +--> analytics/report tables
                         |                               |
                         +------> Redash (all 9 queries) |
                         |                               |
                         +------> SQL/app/job logs ------+
                         |
                         +-- manual full backfill --> BigQuery snapshot
```

[Evidence: `app.py`, `db.py`, `warehouse_backfill.py`, Airflow DAGs; Redash data-source metadata; BigQuery dataset inventory.]

### Serving safety and failure semantics

Batch connections use `autocommit=True`. Jobs that `DELETE` then insert row-by-row (`affinity`, `affinity_v2`, `model_train`, `price_suggest`, `reorder_forecast`) can expose an empty or partially rebuilt table if they fail after deletion; a safe extension should write a staging version and swap atomically or use one explicit transaction. [Evidence: `db.py::job_connect`; the five job files at commit `2ae79e2`.]

Daily report tables are append-only and dashboard queries choose the latest snapshot, making reruns recoverable if `created_at` is later. Monthly statements are also append-only, but `statements_corrected/final` do not select a latest row per month; a rerun can duplicate a month in the finance dashboard. [Evidence: `daily_report.py`, `intraday_report.py`, `monthly_statement.py`; view DDLs; Redash queries 8 and 9.]

The only in-repo KPI rerun helper is a skeleton that expects rows to be filled manually and invokes discount logic; it does not rebuild database KPI/report rows. Its discount helper defaults to the old 40% cap unless callers explicitly pass the current 25% constant. [Evidence: `scripts/rerun_kpis.py`; `discounts.py`; `constants.DISCOUNT_CAP`; commit `35c581e`.]

### Scheduled jobs

Cron expressions below are copied from the pinned Airflow DAGs; no DAG declares an explicit timezone. [Evidence: `airflow/dags/*.py`; commit `43e54a1`.]

| Airflow schedule | Job | Reads → writes/effect | What breaks on failure | Evidence |
|---|---|---|---|---|
| `0 3 * * *` | `reconcile` | `orders` → warning logs for duplicate `payment_ref` | Duplicate-ref alerting is stale; it does not repair rows. Current data has 130 duplicate refs across 285 order rows. | `reconcile.py`; query `duplicate_payment_refs_current`; job logs. |
| `30 3 * * *` | `affinity` | 30-day carts → `product_affinity` | Current widget is unaffected under flag 2.0.0; legacy artifact becomes stale. | `affinity.py`; `similar.py`; Redash/query logs. |
| `45 3 * * *` | `affinity_v2` | carts, products, order existence → `product_affinity_v2` | Score coverage becomes stale; unsupported base products already fall back to trending. | `affinity_v2.py`; `similar.py`; `rec_decisions`. |
| `15 4 * * *` | `model_train` | random-arm log, users/products/orders, affinity v2 → `model_registry`, `model_scores` | v4 artifact becomes stale, but live 2.0.0 serving is unaffected. | `model_train.py`; `flags.env`; `model_registry`. |
| `45 4 * * *` | `price_suggest` | products + 14-day paid orders → overwrite `price_suggestions` | Shadow recommendations stale; storefront prices unaffected. | `price_suggest.py`; query `operational_outputs`; commits `894c535`, `cca9b0d`. |
| `15 5 * * *` | `trending` | 30-day status-1 orders → day slice in `trending_daily` | Recommendation fallback and homepage trending use an older list. | `trending.py`; `similar.py`; commit `f563dea`. |
| `45 5 * * *` | `fraud_score` | last-day paid orders/users → append `order_risk`, mutate orders to status 6 | High-risk paid orders remain status 1 and enter finance/status-1 metrics. | `fraud_score.py`; `constants.py`; query `operational_outputs`. |
| `0 6 * * *` | `daily_report` | prior Eastern day itemized orders/products/test users → append `report_rows` | Closed-day revenue/KPI dashboards remain stale; rerun must create a later snapshot. | `daily_report.py`; Redash queries 5/8. |
| `15 6 * * *` | `kpi_daily` | trailing status-1 orders → append `kpi_daily` | Nightly 30-day active KPI stale; exec daily actives still query raw orders. | `kpi_daily.py`; Redash query 5. |
| `20 6 * * *` | `funnel` | last-day carts/orders → append `daily_funnel` | Session/user rollup stale; no serving impact found. | `funnel.py`; query `funnel_summary`. |
| `30 6 1 * *` | `monthly_statement` | prior Eastern month orders/payments → append `statements` | Month is unpublished; unsafe blind rerun can create duplicate statement rows. | `monthly_statement.py`; Redash query 9. |
| `45 6 * * *` | `top_sellers` | prior-day status-1 order rows → append `top_products` | Batch top list stale; Redash best sellers is independent. | `top_sellers.py`; Redash query 2. |
| `50 6 * * *` | `reorder_forecast` | 14-day paid order velocity → overwrite `reorder_hints` | Advisory hints stale; no finance/serving dependency found. | `reorder_forecast.py`; query `operational_outputs`. |
| `15 7 * * *` | `email_digest` | paid orders/users → append `digest_log` | Digest audit/send simulation missing; job uses 40 recipients, not `contactable_users`. | `email_digest.py`; `digest_history`; job logs. |
| `0 12 * * *` | `intraday_report` | today-to-now itemized orders → append `report_rows_intraday` | Today’s revenue dashboard stays at the prior snapshot. The retired 17:00 run was lost in migration. | `intraday_report_dag.py`; `crontab.txt`; Redash query 8; commit `43e54a1`. |
| manual | `warehouse_backfill` | every manifest table → full BigQuery loads | Warehouse snapshot cannot be rebuilt; serving and Redash remain online. | `warehouse_backfill.py`, manifest, DAG `schedule=None`; commit `2ae79e2`. |

Historical job logs show only three ERROR rows: affinity-v2 crashed on 2019-12-03, 04, and 05 with `IndexError` because the seasonal-factor list ended at November; commit `3dbe4d7` added a December-safe factor of 1.0 and successful refreshes begin 2019-12-06. [Evidence: `novamart_logs.job_runs` query `job_errors`; commit `3dbe4d7`; query `job_event_summary`.]

## 6. Data

### Source-of-truth map

| Domain | Serving source | Warehouse mirror | Primary consumers | Evidence |
|---|---|---|---|---|
| Shopper identity | `users`, `accounts`, `account_map` | `novamart.*` | App, board/registered dashboards, ML features | Schema; Redash queries 1/7; `model_train.py`. |
| Catalog | `products` | `novamart.products` plus `price_history` | App, reports, recommendation jobs | `catalog.py`; query `product_data_quality`. |
| Orders/items | `orders`, `order_lines` | `novamart.orders`, `novamart.order_lines` | Finance jobs, reports, dashboards, ML labels | `orders.py`; queries `itemization_summary`, `orders_month_status`. |
| Money movement | `payments` | `novamart.payments` | Monthly statement fees, refund view, audits | `orders.py`; `payments_webhook.py`; `payments_integrity`. |
| Finance publication | `statements` | `novamart.statements` | Corrected/final views, Redash query 9 | `monthly_statement.py`; view DDLs. |
| Restatements | `analytics.statement_*`, `chargebacks` | `novamart_analytics.*` | `statements_corrected/final` | View DDLs; `statement_adjustments`. |
| Operational reporting | `report_rows`, `report_rows_intraday`, `top_products` | `novamart.*` | Redash daily/revenue dashboards; legacy batch consumers | Redash queries 5/8; jobs. |
| Recommendation | `analytics.product_affinity*`, `model_*`, `rec_decision_log`, `trending_daily` | `novamart_analytics.*` | Similar-products API and training | `similar.py`; `model_train.py`; queries `ml_table_summary`, `rec_decisions`. |
| Observability | Postgres/app/job JSON logs | `novamart_logs.*` | Investigation and lineage | `db.py`, `logutil.py`; normalized log view DDL. |

### Data-quality and lineage caveats

`orders` changed from one row per sold item to one row per merged session-order. Any item or product analysis after 2019-11-22 must use `order_lines` with a `NOT EXISTS` legacy fallback; order-level finance may still use `orders.price`, which equals the summed lines in current data. [Evidence: commit `5d1300d`; query `itemization_summary`; Redash queries 2–4.]

The schema does not enforce most analytical uniqueness. `statements.month`, report `(date, product, created_at)`, recommendation pairs, and refund webhook events lack uniqueness constraints in their analytical use, so latest-version selection or deduplication is a consumer responsibility. [Evidence: `schema.sql`; job-created table DDL in source; view DDLs; query `refund_double_count`.]

Payment-reference idempotency is stronger on new order callbacks than on refunds. The order path has advisory locks and unique payment-reference indexes, but the refund webhook carries no idempotency key and simply inserts a new negative row. [Evidence: `orders.py`; `payments_webhook.py`; query `refund_double_count`.]

The warehouse is a full-copy snapshot rather than an incremental lineage layer. The loader exports each manifest table ordered by its first column and loads it into mapped datasets; it does not preserve an independent change history beyond history already present in source tables. [Evidence: `warehouse_backfill.py`; `warehouse_manifest.json`; DAG `schedule=None`; commit `2ae79e2`.]

### Status dictionary

| Status | Meaning in current code | Reporting behavior | Evidence |
|---:|---|---|---|
| 0 | transient order creation/unpaid | Excluded by daily reports and board actives; no current rows. | `orders.py`; `constants.EXCLUDED_STATUSES`; `order_status_summary`. |
| 1 | paid/active | Included by finance statement, KPI, trending, fraud input. | `monthly_statement.py`, `kpi_daily.py`, `trending.py`, `fraud_score.py`. |
| 2 | cancelled | Excluded by status-aware reports; surfaced as `order_cancelled` refund. | `constants.py`; `refunds_unified` DDL. |
| 3 | refunded through legacy order endpoint | Excluded by status-aware reports; surfaced as `order_refunded` refund. | `orders.py`; `refunds_unified` DDL. |
| 5 | unnamed historical/suspect exclusion in reconcile | Reconcile ignores it; no current rows and no named constant. | `reconcile.py`; `order_status_summary`. |
| 6 | fraud-held after payment | Excluded by status-1 finance/KPI jobs but **included** by daily reports and statusless product dashboards. | `fraud_score.py`; `constants.py`; Redash queries 2–5; `dashboard_cleanup_impact`. |

## 7. Experimentation

### Recommendations

The serving history is: v1 co-cart affinity from 2019-10-26; intended v2 from 2019-12-06; and nightly v4 training from 2019-12-15. The current flag remains `2.0.0`, while rows in the v2 table are stamped `2.0.1`, so serving version, table, and writer version use different labels. [Evidence: `similar.py`; `affinity_v2.py`; `flags.env`; queries `rec_decisions`, `model_registry`; commits `df4ed85`, `a1946ff`.]

For intended-v2 decision logs, 52,695 decisions received affinity-v2 model results, 207,959 fell back to trending/no-score or cache fallback, and 14,566 were in the stable 5% user-hash random arm. Thus only about 19.1% of all intended-v2 decisions were served scored v2 results. [Evidence: query `rec_decisions`; `similar.py::in_random_arm`.]

Affinity v2 is a heuristic, not a trained model: co-cart counts are weighted by whether the user ever bought the candidate product, with no requirement that purchase followed the cart exposure; it adds recency decay, same-category boost, extreme-price penalty, and seasonal scaling. [Evidence: `affinity_v2.py`; commit `89666bf`.]

The v4 trainer’s documentation overstates its implemented feature set. The actual vector has five features—served-list size, scaled base price, base popularity, capped account age, and organic-signup indicator—while stock and opt-in are fetched but unused, and region/device features are absent. [Evidence: `model_train.py`; contrast `README.md` at `2ae79e2`; commit `a1946ff`.]

Its label is any later status-1 order by the user, with no horizon and no requirement that the purchased product appeared in the recommendation list. Training therefore measures later purchasing propensity more than recommendation-item conversion. [Evidence: `model_train.py` label SQL; query `rec_experiment_user_level`.]

Most importantly, v4 applies only the first coefficient as one scalar multiplier to every nonnegative affinity-v2 pair. The current 948 model-score pairs have zero pair/rank mismatches versus affinity v2 and a nearly constant 0.9755 score ratio; v4 cannot reorder candidates. [Evidence: `model_train.py`; query `model_rank_equivalence`; tables `model_scores`, `product_affinity_v2`.]

The available experiment does not establish material lift. At first intended-v2 exposure per user, any-order conversion within seven days is 3.56% for 19,707 nonrandom users versus 3.40% for 942 random users; recommended-item purchase is 0.27% versus 0%. The small random sample and very low recommended-item event count make this inconclusive rather than proof that the system works. [Evidence: query `rec_experiment_user_level`; assignment rule in `similar.py`.]

Safe recommendation changes should first define an exposure-level outcome with a fixed horizon and recommended-item match, evaluate at user assignment level, remove post-exposure leakage, and make scoring capable of changing rank. Only after offline and random-arm checks should `REC_MODEL_VERSION` move from 2.0.0 to 4.0.0. [Evidence motivating each control: `model_train.py`; `similar.py`; queries `model_rank_equivalence`, `rec_experiment_user_level`; `flags.env`.]

### Other experiments and heuristics

Dynamic pricing is shadow-only. The nightly table holds 500 suggestions with ±5% nudges, but the catalog/vendor feed remains the live price path and no app read of `price_suggestions` exists. [Evidence: `price_suggest.py`; `catalog.py`; query `operational_outputs`; database table-read logs; commits `894c535`, `cca9b0d`.]

Reorder hints are advisory and mechanically inverse to recent velocity: `15.6 + 162.4/(velocity + 1.8)`, truncated to integer, for the top 200 products by 14-day paid order count. They omit inventory position, lead time, open purchase orders, seasonality, and cost constraints, so they are unsafe as purchase commitments. [Evidence: `reorder_forecast.py`; query `operational_outputs`; commits `f5e3032`, `f85cdd2`.]

Fraud scoring is also a hand-built heuristic: price/3,000 capped at 1, boosted 15% each for a new account and high velocity, with the current hold threshold 0.85. It has operational effect because it mutates order status, unlike shadow pricing. [Evidence: `fraud_score.py`; `constants.py`; commits `e4656fb`, `53f6f6c`, `1cb8721`.]

The email digest is gated on `ENABLE_DIGEST=1`, but the implemented job records a chosen top product and recipient count rather than an external delivery call. Its 40-recipient rule conflicts with the zero-row `contactable_users` policy. [Evidence: `email_digest.py`; `deploy/cron.env`; `digest_history`; `contactable_diagnostics`.]

## 8. Glossary

| Term | Novamart meaning | Evidence |
|---|---|---|
| Active customer | Ambiguous; qualify as nightly 30-day paid buyer, exec daily ordering user, or board-cleaned 30-day user. | Redash queries 1/5; `kpi_daily.py`. |
| Affinity v1 | 30-day co-cart pair score with recency decay and a `-1` insufficient-data sentinel. | `affinity.py`; table `product_affinity`. |
| Affinity v2 | Conversion-weighted co-cart heuristic served under version 2.0.0; table rows stamped 2.0.1. | `affinity_v2.py`; `similar.py`. |
| As-published statement | Immutable record of what monthly close emitted at that time. | `novamart.statements`; `monthly_statement.py`. |
| Chargeback | Separately booked amount assigned back to the original order month and subtracted by `statements_final`. | `chargebacks`; `statements_final` DDL. |
| Contactable customer | Opted-in user with syntactically valid, non-example email under `contactable_users`. | View DDL. |
| Daily report revenue | Itemized status-not-0/2/3 revenue after test-user, excluded-SKU, and brand filters; status 6 remains included. | `daily_report.py`; `constants.py`. |
| Final statement | Corrected statement less booked chargebacks; official current finance surface. | `statements_final`; Redash query 9. |
| Gateway refund | Negative payment row inserted by webhook; it does not change order status and currently lacks idempotency. | `payments_webhook.py`; `refunds_unified`. |
| Gross | Context-dependent: order-price sum in statements, payment `gross` in ledger analysis, or raw item price in dashboards. | `monthly_statement.py`; `payments`; Redash queries 2–4. |
| Held order | Status 6, assigned by fraud scoring after payment; excluded by status-1 jobs but not all dashboards/reports. | `fraud_score.py`; `dashboard_cleanup_impact`. |
| Legacy order | Order with no `order_lines`; product/price is read from `orders`. | Redash item-order CTEs; commit `92596dc`. |
| Net | In statements, gross minus collected fee, later reduced by chargebacks in final view; ordinary refunds are separate. | `monthly_statement.py`; `statements_final`; `refunds_unified`. |
| Order | Post-merge payment session container; may represent multiple item lines and payment transactions. | `orders.py`; `itemization_summary`. |
| Paid order | Status 1 under finance/KPI/trending code; not synonymous with “has a payment,” because held orders also have payments. | `orders.py`; `fraud_score.py`; `finance_status_payment_detail`. |
| Published correction | Override replacing statement gross/fee/net/order count for a month before chargebacks. | `statement_overrides`; `statements_corrected`. |
| Random arm | Stable user-hash 5% uniform product recommendation arm used for training data. | `similar.py`; `rec_decision_log`. |
| Restatement | Current transformation from published statement through overrides and chargebacks. | `statements_corrected`, `statements_final`. |
| Revenue widget | Latest prior-six-day daily snapshots plus latest current-day intraday snapshot. | Redash query 8. |
| Trending | Top 50 status-1 products from a rolling 30-day window, min five units, recency-decayed. | `trending.py`; commit `f563dea`. |

---

# Appendix A — Evidence index

All local evidence artifacts for this run are under `~/5891a8ad-1237-40d2-9d14-f4585fc1fd8f`. The exact warehouse SQL is recorded in `bq_query_manifest.json`; each named query has a same-named JSON result file. [Evidence: files generated during this read-only run.]

## A.1 Repository evidence

| Label | Evidence |
|---|---|
| Pinned code | Commit `2ae79e23690f7ef09a2e9231fdfa3a2cdb84be00`; clean `repo_status.txt`. |
| Full history | `git_history.tsv`, 111 commits from `2da4141` through `2ae79e2`. |
| Key diffs | `key_commit_diffs.txt`, covering finance, reports, customers, recommendations, fraud, Airflow, and warehouse migration. |
| Current source | `all_source.txt`, `key_source.txt`, `all_airflow_dags.txt`, `docs_and_schema.txt`. |
| Schedules | `airflow_schedule_inventory.txt`; migration diff `airflow_migration_diff.txt`. |

## A.2 Redash evidence

| Query ID | Name | Definition summary | Source |
|---:|---|---|---|
| 1 | `actives_board` | Cleaned trailing-30-day non-cancelled ordering users. | `redash_query_sql.txt`, data source 1. |
| 2 | `best_sellers` | Rolling seven-day itemized product revenue, top 20. | `redash_query_sql.txt`, data source 1. |
| 3 | `brand_revenue` | Rolling 30-day itemized revenue by current product brand. | `redash_query_sql.txt`, data source 1. |
| 4 | `category_revenue` | Rolling 30-day itemized revenue under effective-dated category mapping. | `redash_query_sql.txt`, data source 1. |
| 5 | `daily_kpis` | Latest report snapshots plus raw daily customer counts. | `redash_query_sql.txt`, data source 1. |
| 6 | `refunds` | Monthly count/sum of `refunds_unified`. | `redash_query_sql.txt`, data source 1. |
| 7 | `registered_conversion` | UUID accounts mapped by email to numeric ordering users. | `redash_query_sql.txt`, data source 1. |
| 8 | `revenue_widget` | Latest closed-day/current intraday snapshots across seven calendar dates. | `redash_query_sql.txt`, data source 1. |
| 9 | `statements_final` | All final statement rows ordered by month. | `redash_query_sql.txt`, data source 1. |

None of the nine query objects has a Redash schedule or cached `latest_query_data_id`; results are therefore not evidenced as pre-refreshed cached values in this snapshot. [Evidence: `redash_query_metadata.tsv`, `redash_queries.json`.]

## A.3 Warehouse queries used for quantified claims

| Query name | Primary tables/views | Purpose |
|---|---|---|
| `base_date_ranges` | app base tables | Row counts and data cutoff. |
| `orders_month_status`, `order_status_summary` | `orders` | Monthly/status population and value. |
| `itemization_summary`, `itemized_month_status` | `orders`, `order_lines` | Legacy/multi-line reconciliation. |
| `payments_integrity`, `payments_month`, `finance_status_payment_detail` | `payments`, `orders` | Payment arithmetic, negative rows, status linkage. |
| `refunds_month_kind`, `refund_double_count` | `refunds_unified` | Refund totals and duplicate gateway events. |
| `statements_all`, `statement_adjustments`, `finance_reconciliation` | statements, overrides, chargebacks, orders, payments | Publication/restatement lineage. |
| `dashboard_best_sellers`, `dashboard_brand_revenue`, `dashboard_category_revenue` | itemized orders, products, mappings | BigQuery translations of Redash logic anchored at last order time. |
| `dashboard_cleanup_impact`, `excluded_sku_impact` | orders, lines, products | Status, QA, brand, and SKU effects. |
| `report_snapshot_health` | report tables | Snapshot multiplicity and date coverage. |
| `product_data_quality` | products and mapping/audit tables | Blank/missing catalog attributes. |
| `users_summary`, `signups_month`, `contactable_diagnostics`, `email_domain_summary` | users/contactable/accounts/test users | Identity and contactability. |
| `active_customer_definitions`, `board_filter_diagnostics` | users/orders/products/test users/KPI | Reproduction of active-customer variants. |
| `registered_conversion`, `digest_history`, `funnel_summary` | account/digest/funnel tables | Secondary customer metrics. |
| `ml_table_summary`, `model_registry`, `rec_decisions` | recommendation artifacts | Version, coverage, and freshness. |
| `rec_outcomes`, `rec_experiment_user_level`, `model_rank_equivalence` | decision log, orders/lines, model/affinity scores | ML effectiveness and rank behavior. |
| `operational_outputs`, `latest_artifacts` | analytical job outputs | Job output size/freshness. |
| `job_event_summary`, `job_errors` | `novamart_logs.job_runs` | Success/error history. |
| `app_event_summary` | `novamart_logs.app_events` | Application-event counts and dates. |
| `db_actor_summary`, `db_table_reads`, `db_key_history` | normalized SQL logs | Actual readers/writers and historical adoption. |
| `duplicate_payment_refs_current` | `orders` | Current reconcile backlog. |

# Appendix B — “What was revenue, and why?” playbook

1. Ask whether the request is “match the old deck,” “current approved finance,” “processor/payment movement,” or “dashboard operational revenue.” These resolve respectively to `statements`, `statements_final`, `payments`, or the named Redash query. [Evidence: Redash queries 6/8/9; finance view DDLs; `monthly_statement.py`.]
2. Use Eastern calendar boundaries for statement/daily-report questions; rolling dashboard windows are query-time 7×24 or 30×24 hours except the calendar-date revenue widget. [Evidence: `timeutil.py`; `monthly_statement.py`; Redash queries 2–5/8.]
3. State the order-status policy. Status 6 is the common hidden discrepancy: finance/status-1 jobs exclude it, but daily reports and statusless product dashboards include it. [Evidence: `constants.py`; `fraud_score.py`; `dashboard_cleanup_impact`.]
4. State the itemization policy. Product analysis must use `order_lines` plus legacy fallback; order-level statements use total `orders.price`. [Evidence: `orders.py`; Redash queries 2–4; `itemization_summary`.]
5. State cleanup filters: QA/test users, Lucente/Jetem, and excluded SKUs are not applied consistently. [Evidence: `constants.py`; Redash queries 2–5; `excluded_sku_impact`.]
6. For closed months, show published, corrected, chargeback, and final values as a bridge. List ordinary/gateway refunds separately because they are not part of `statements_final`. [Evidence: view DDLs; `statements_all`, `statement_adjustments`, `refunds_month_kind`.]
7. Verify freshness and duplicate/version behavior before quoting a dashboard or rerun result. [Evidence: Redash query metadata; `report_snapshot_health`; autocommit in `db.py`; finance view DDLs.]

# Appendix C — Safe batch modification checklist

1. Preserve Eastern business-day/month boundaries with `timeutil`; add an explicit timezone to Airflow DAGs and verify the intended UTC/local schedule before deployment. [Evidence: `timeutil.py`; `crontab.txt`; Airflow DAGs; commit `43e54a1`.]
2. For overwrite jobs, build into a run-versioned staging table and publish atomically; do not retain autocommit `DELETE` plus row inserts for critical consumers. [Evidence: `db.py`; `affinity_v2.py`, `model_train.py`, `price_suggest.py`, `reorder_forecast.py`.]
3. Make reruns idempotent by a natural run key. For statements, enforce one approved row per month or make views select the approved/latest row. [Evidence: `monthly_statement.py`; view DDLs.]
4. Carry the full metric contract into new consumers: status, itemization, QA, SKU, brand, timezone, mapping validity, and snapshot version. [Evidence: documented divergences in Redash queries 1–9 and current jobs.]
5. Add refund idempotency at the gateway event level before using payment negatives as a ledger source. [Evidence: `payments_webhook.py`; `refund_double_count`.]
6. For recommendation changes, use user-level randomized evaluation, fixed outcome horizons, recommended-item outcomes, and a rank-changing score; log model version, candidate set, and fallback reason. [Evidence: `similar.py`; `model_train.py`; `rec_experiment_user_level`; `model_rank_equivalence`.]
7. Validate downstream tables and dashboards after a change using the source SQL logs, not repository search alone. [Evidence: `novamart_logs.db_queries_normalized`; query `db_table_reads`; Redash data-source metadata.]
