# Novamart tribal knowledge handbook

Started: `2026-08-27 17:08:27 IST`  
Run UUID: `f4855933-f305-474c-b0da-25004211f68a`  
Repository: `novamart` pinned at `2ae79e23690f7ef09a2e9231fdfa3a2cdb84be00`  
Scope: only the pinned repository and its Git history, read-only BigQuery project `<warehouse-project>`, and read-only Redash at `<redash-url>` were used. [Evidence: E0]

## 1. Summary

Novamart has several valid but non-interchangeable meanings of “revenue.” For current approved finance reporting, use `novamart_analytics.statements_final`; for the number originally published, use `novamart.statements`; for product-merchandising dashboards, reproduce each dashboard’s item-line, date-window, exclusion, and status rules exactly. [Evidence: E1, E2, R2-R9]

For October 2019, the published net was `1,194,652.79`, the fee-corrected net was `1,194,652.93`, and the final restated net was `1,191,085.36`. The final value is `1,230,332.43` published gross, less the corrected `35,679.50` fee, less `3,567.57` of chargebacks booked back to the original order month. [Evidence: Q1, Q5; `novamart_analytics.statements_final` DDL]

The finance statement is an append-only publication snapshot. It is not a live recomputation from current order statuses: October now has 3,695 paid headers worth `1,206,337.32`, plus 43 cancelled and 27 refunded headers worth `23,995.11`; the original statement captured all 3,765 orders before those later state changes. [Evidence: Q2; `novamart.statements`; commit `a92c96d`]

The executive best-seller, brand, and category dashboards count item rows using `order_lines` with a legacy header fallback, but do not filter order status. That can materially overstate paid performance: in the data-anchored last-seven-day reproduction, product `1005284` ranked third with `5,096.14` revenue and zero paid units, and excluded SKU `1002544` still appeared because the Redash query excludes brands but not `EXCLUDED_SKUS`. [Evidence: Q6; Redash queries 2-4; commits `92596dc`, `1169e40`]

Customer counts are different metrics, not variants of one metric. The last stored nightly KPI is 1,152 trailing-30-day paid buyers; the board query returns zero in this snapshot because all 1,155 candidates match its test/example-email rules; the latest local-day executive definition counts 54 ordering users without a status filter. [Evidence: Q10, Q22, Q23; Redash queries 1 and 5; commit `dd0c8fc`]

The active recommendation path is version `2.0.0`, backed by `product_affinity_v2` rows stamped `2.0.1`; version 4 trains nightly but has never been enabled in `deploy/flags.env`, and no v4 serving exposure appears in `rec_decision_log`. [Evidence: `deploy/flags.env` at `2ae79e2`; Q12-Q13; L1; commits `df4ed85`, `a1946ff`]

The v4 model does not change candidate order: it multiplies every v2 affinity score by one learned global scalar. Warehouse verification found zero rank mismatches across 948 joined candidate pairs and a nearly constant model/v2 ratio of `0.97545–0.97556`. It therefore cannot provide learned per-user or per-pair ranking improvements in its current form. [Evidence: Q14; `model_train.py` lines 64-72 at `2ae79e2`]

The operational migration needs care. Redash reads the serving Cloud SQL database, not BigQuery; BigQuery is a backfill snapshot. The warehouse DAG is manual, supplies none of the CLI’s required arguments, and the code targets dataset `analytics` while this environment’s physical dataset is `novamart_analytics`. The Airflow migration also retained only the 12:00 intraday run and dropped the retired cron’s 17:00 run. [Evidence: R0; commits `2ae79e2`, `43e54a1`; `warehouse_backfill.py` lines 46-75; `warehouse_backfill_dag.py` lines 11-19; `intraday_report_dag.py` lines 7-14; retired `crontab.txt` lines 28-29]

## 2. Why this project

Business questions currently cross four semantic layers: mutable serving rows, append-only report snapshots, restatement views, and dashboard-specific cleanup SQL. A number can be internally consistent in one layer and still be wrong for another consumer. [Evidence: `orders`, `payments`, `report_rows`, `statements`, `statements_corrected`, `statements_final`; Redash queries 2-9]

The project exists to make those boundaries explicit so that finance can reproduce a board number, analysts can explain dashboard deltas, and engineers can change batch or recommendation pipelines without silently changing business definitions. [Evidence: commits `a576d0d`, `dd0c8fc`, `2885137`, `442b135`; repository goal context]

The highest-risk misunderstandings are: treating gross merchandise sales as net finance revenue; counting order headers after multi-item checkout; assuming “active customer” is globally defined; assuming a table is consumed because it is refreshed; and trusting README descriptions over executable code and logs. [Evidence: commits `92596dc`, `d2481be`, `dd0c8fc`, `8584613`; Q17]

## 3. Business understanding

### Order-to-money lifecycle

1. Product views, cart actions, or order creation synthesize missing `users` and `products`. Most user names, regions, channels, devices, age bands, opt-ins, product titles, costs, vendors, and stock values are deterministic functions of numeric IDs rather than independently captured business facts. [Evidence: `onboarding.py` lines 21-47, `catalog.py` lines 58-65 at `2ae79e2`]
2. `/orders` takes the item price from the request, computes a processor fee of `2.9% + 0.30`, locks both session and payment reference, and deduplicates callback replays by payment reference. [Evidence: `orders.py` lines 14-64; constants `FEE_RATE`, `FEE_FLAT`; commits `b676969`, `12e1c68`]
3. A new payment callback creates an order header, one line, and one payment, then changes status from 0 to 1. A different callback in the same user/session within 15 minutes appends a line and payment to the recent order and increases the header’s `price`; therefore header price is order total while line/payment rows retain transaction items. [Evidence: `orders.py` lines 65-105; commit `5d1300d`]
4. Status meanings evidenced by code are 0 pending, 1 paid, 2 cancelled, 3 refunded, and 6 fraud-held. Reconcile ignores status 5, but no definition or writer for status 5 exists in the pinned repository. [Evidence: `constants.py` lines 12-19, 37-38; `fraud_score.py` lines 44-47; `reconcile.py` line 16]
5. The cancel/refund endpoints only mutate order status. The gateway-refund endpoint instead appends a negative `payments` row and does not change order status; it has no idempotency key, so webhook replay can duplicate a monetary reversal. [Evidence: `orders.py` lines 114-155; `payments_webhook.py` lines 11-20; commit `c49a7bb`]

### Finance publication and restatement

The monthly job runs for the previous Eastern business month. It sums paid order-header prices for gross and count, sums collected payment fees joined to those paid orders, computes `net = gross - fee`, and appends a statement row. It does not sum payment net and therefore a negative gateway-refund row with fee zero does not reduce statement net. [Evidence: `monthly_statement.py` lines 16-53; `payments_webhook.py` lines 17-19]

Before commit `a92c96d`, statement fees were calculated once as `gross * 2.9%`; the fix changed the source to collected per-payment fees. Commit `12e1c68` added the flat 0.30 fee on 2019-11-20, and commit `4a58d17` updated only the expected-fee audit calculation. [Evidence: commits `a92c96d`, `12e1c68`, `4a58d17`]

`novamart.statements` answers “what did we publish then?”; `novamart_analytics.statements_corrected` overlays `statement_overrides`; `novamart_analytics.statements_final` additionally subtracts chargebacks from gross and net by the original order’s Eastern month while leaving fees and order count unchanged. [Evidence: Q1, Q5; BigQuery DDL for both views; commit `cd559d3`]

The unified refunds view is a monitoring surface, not an input to `statements_final`. It unions cancelled orders, refunded orders, and negative payment rows and groups them by refund/update event time in the Redash query; cancellations are therefore labeled as refunds, and gateway refunds are reported in the event month rather than the original sale month. [Evidence: `novamart_analytics.refunds_unified` DDL; Redash query 6; Q4]

### Product reporting

After multi-item checkout launched, the authoritative item stream became `order_lines` plus orders with no lines as the legacy fallback. November has 3,582 order headers but 3,614 item rows; December has 1,768 headers but 1,961 item rows. Revenue agrees because header prices aggregate line prices, but units and product attribution do not. [Evidence: Q9; commit `92596dc`]

The nightly daily report uses item rows, Eastern calendar-day bounds, removes statuses 0/2/3, `analytics.test_users`, SKUs `1004856`/`1002544`, and brands `lucente`/`jetem`. It does not exclude status 6, so fraud-held orders enter daily report revenue even though monthly finance excludes them by requiring status 1. [Evidence: `daily_report.py` lines 17-65; `constants.py` lines 6-19; `monthly_statement.py` line 28]

The nightly `top_sellers` table is not the executive best-seller dashboard: the job counts paid order headers for yesterday and ranks by units, while Redash counts all-status item rows over a rolling seven days and ranks by revenue. [Evidence: `top_sellers.py` lines 15-39; Redash query 2]

Brand and category dashboards use rolling 30-day item revenue, no status filter, QA/brand exclusions, and revenue ordering. Category reporting chooses the latest mapping effective on the item date from current plus history tables, with history winning equal-date ties. [Evidence: Redash queries 3-4; commit `33054cd`; Q7-Q8]

### Customer lifecycle

`users.created_at` is not a pure registration timestamp because catalog, cart, and order traffic creates user rows on first sight. Explicit registered-account beta identities live in `accounts` as UUIDs and map back to legacy numeric users through email/account mapping. [Evidence: `catalog.py` lines 58-65; `accounts.py` lines 23-48; Redash query 7]

The current app no longer registers the `users`, `reports`, or `accounts` routers. The similar-widget commit dropped users/reports, and the gateway-refund commit later dropped accounts; CI exercises only catalog/cart/order flows, so these regressions were not caught. [Evidence: `app.py` lines 6-23 at `2ae79e2`; commits `f1217a8`, `c49a7bb`; `ci/run_ci.py` at `2ae79e2`]

## 4. Metrics

### Revenue source-of-truth policy

| Question | Use | Definition and caveat |
|---|---|---|
| What is current approved monthly net revenue? | `novamart_analytics.statements_final` | Corrected statement net minus booked chargebacks; it does not consume `refunds_unified`. [Evidence: view DDL; Q1] |
| What number was published in the old deck? | `novamart.statements` | Append-only run snapshot; later statuses and restatements do not rewrite it. [Evidence: Q1-Q2; commit `a576d0d`] |
| What did the statement-generation bug change? | `statements_corrected` plus `statement_overrides`/`statement_corrections` | Separates approved statement corrections from chargebacks. [Evidence: Q5; corrected-view DDL] |
| What is product sales revenue? | Dashboard SQL or item-line reconstruction | Gross item price, not finance net; filters differ by consumer and exec dashboards omit status filtering. [Evidence: Redash queries 2-5] |
| What cash movement did the gateway record? | `payments` | Payment rows include per-callback fees and negative refunds; do not join naively to headers and sum header gross once per payment. [Evidence: `orders.py`; `payments_webhook.py`; Q3] |
| What refunds were surfaced operationally? | `refunds_unified` / Redash query 6 | Includes cancellations and groups by event month; not a finance-statement adjustment input. [Evidence: view DDL; Q4] |

### Published monthly finance numbers

| Month | Published gross | Published fee | Published net | Corrected net | Final net | Explanation |
|---|---:|---:|---:|---:|---:|---|
| 2019-09 | 2,702.00 | 78.36 | 2,623.64 | 2,623.64 | 2,623.64 | All 12 headers later became cancelled/refunded, demonstrating snapshot semantics. [Evidence: Q1-Q2] |
| 2019-10 | 1,230,332.43 | 35,679.64 | 1,194,652.79 | 1,194,652.93 | 1,191,085.36 | 0.14 fee correction, then 3,567.57 chargebacks. [Evidence: Q1, Q5] |
| 2019-11 | 1,101,397.01 | 32,110.92 | 1,069,286.09 | 1,069,286.09 | 1,069,286.09 | No effective correction or chargeback in the snapshot. [Evidence: Q1, Q5] |
| 2019-12 | — | — | — | — | — | No December statement row exists because the snapshot ends before the January 1 monthly run. [Evidence: `novamart.statements`; Q18] |

When answering “what was October revenue?”, first ask whether the requester means gross sales, originally published net, corrected net, or current restated net. Unless they explicitly want the old deck, answer `1,191,085.36` current restated net and explain the `0.14` fee correction plus `3,567.57` chargeback adjustment. [Evidence: Q1, Q5; Redash query 9]

### Other metric contracts

| Metric | Actual contract | Source of truth / consumer |
|---|---|---|
| Best sellers | Rolling 7×24h item rows, QA `424242` and two brands removed, all statuses, sort by revenue, top 20. | Redash query 2. [Evidence: R2] |
| Nightly top products | Previous Eastern day, paid order headers, sort by units, top 50. | `novamart.top_products`. [Evidence: `top_sellers.py`] |
| Brand revenue API | Eastern calendar month, paid order headers, excluded SKUs and brands. The router is currently unmounted. | `reports.py`; current `app.py`. [Evidence: `reports.py` lines 13-42; `app.py`] |
| Brand revenue dashboard | Rolling 30-day item rows, no status filter, QA numeric/string exclusions, brand denylist. | Redash query 3. [Evidence: R3] |
| Category revenue | Same item/status/window rules as exec brand revenue, with effective-dated taxonomy mapping. | Redash query 4. [Evidence: R4] |
| Daily KPI revenue/orders | Latest closed-day `report_rows` snapshots plus latest intraday snapshot for today; brands denied twice. | Redash query 5. [Evidence: R5] |
| Revenue widget | Seven Eastern calendar days, latest closed snapshots plus latest today snapshot; prior versions must not be summed. | Redash query 8; commit `3eced24`. [Evidence: R8, Q11] |
| Nightly active customers | Distinct paid order-header users in trailing 30×24h; no QA/brand/email exclusions. | `kpi_daily.active_customers`. [Evidence: `kpi_daily.py`; Q23] |
| Exec daily active customers | Distinct ordering users per Eastern day; no status filter; removes QA `424242` and two brands. | Redash query 5. [Evidence: R5] |
| Board active customers | Distinct users with status not in 0/2/3 over trailing 30×24h, excluding known and heuristic test emails. | Redash query 1. [Evidence: R1, Q22] |
| Contactable customers | Marketing opt-in plus valid non-example email. The snapshot view contains zero rows. | `contactable_users`; Redash query 5. [Evidence: view DDL; Q22] |
| Funnel active users | Distinct cart/order users in trailing 24h; sessions split at inactivity greater than 120 minutes. | `daily_funnel`. [Evidence: `funnel.py`; commit `f915c1b`] |
| Registered conversion | Paid legacy users mapped from UUID accounts by email; 30 accounts/buyers and `18,155.71` revenue in the snapshot. | Redash query 7; Q24. [Evidence: R7, Q24] |

The dataset has 38,950 user rows, of which 38,910 use generated `@example.com` addresses; this makes raw “signup” counts closer to first-seen identities than verified registrations. [Evidence: Q21; `catalog.py`]

The email digest does not use `contactable_users` or `marketing_opt_in`; it counts any email not ending in `@example.com`. Logs show 40 recipients while the trusted contactable view has zero, so “digest recipients” must not be interpreted as consented/eligible customers. [Evidence: `email_digest.py` lines 44-56; Q17, Q22]

## 5. System

### Runtime topology

The FastAPI service writes serving Postgres and logs every SQL statement plus JSON app/job events. Redash data source 1 is the read-only PostgreSQL source named `novamart serving (Cloud SQL)`. BigQuery contains a later snapshot of 12 app tables, 20 analytics base tables, four analytics views, and three raw log tables plus one normalized log view. [Evidence: `db.py`, `logutil.py`; R0; BigQuery dataset inventory]

The logical Postgres schema `analytics.*` maps to physical BigQuery dataset `novamart_analytics.*`; public Postgres tables map to BigQuery dataset `novamart.*`. Query history is in `novamart_logs.db_queries`, app events in `app_events`, and job history in `job_runs`. [Evidence: `data-access.md`; BigQuery schemas; `db_queries_normalized` DDL]

All nine Redash queries are unscheduled and expose no cached result ID/retrieval timestamp in the inspected read-only instance. Their rolling windows use database `now()`, so the appendix’s product/customer reproductions deliberately anchor to the warehouse’s maximum event time and are diagnostic historical reproductions, not claims about a present Redash tile value. [Evidence: R1-R9; Q6-Q10]

### Scheduled jobs and blast radius

| Airflow time | Job | Produces | If it fails |
|---|---|---|---|
| 03:00 daily | reconcile | warning logs only | Duplicate refs remain untriaged; current snapshot has 130 duplicate refs affecting 285 rows. [Evidence: DAG; Q20] |
| 03:30 daily | affinity | overwritten `product_affinity` | Legacy score table becomes empty/partial after delete-first failure, though current serving does not use it. [Evidence: `affinity.py`; L1] |
| 03:45 daily | affinity_v2 | overwritten `product_affinity_v2` | Active recommender falls back or serves cache/stale partial data. It crashed Dec 3-5 on missing December seasonal factor. [Evidence: `affinity_v2.py`; Q19; commit `3dbe4d7`] |
| 04:15 daily | model_train | `model_registry`, overwritten `model_scores` | v4 scores stale/partial; no current customer impact because v4 flag is off. [Evidence: `model_train.py`; `deploy/flags.env`] |
| 04:45 daily | price_suggest | overwritten `price_suggestions` | Shadow experiment becomes stale; storefront unaffected. [Evidence: `price_suggest.py`; Q17] |
| 05:15 daily | trending | daily `trending_daily` top 50 | Homepage trending and recommendation fallback stale/missing for the day. [Evidence: `trending.py`; `similar.py`] |
| 05:45 daily | fraud_score | append `order_risk`, mutate orders to status 6 | Risky orders remain paid; downstream finance includes them until a later run, while daily reports include status 6 even after holding. [Evidence: `fraud_score.py`; `constants.py`] |
| 06:00 daily | daily_report | append `report_rows` snapshot | Closed-day KPI/revenue dashboards stale; partial autocommit versions can remain. [Evidence: `daily_report.py`; R5] |
| 06:15 daily | kpi_daily | append trailing-30-day KPI | Stored active-customer headline stale. [Evidence: `kpi_daily.py`] |
| 06:20 daily | funnel | append daily funnel | Funnel users/sessions stale. [Evidence: `funnel.py`] |
| 06:45 daily | top_sellers | append `top_products` | Nightly product list stale; unrelated Redash best-seller query still runs live. [Evidence: `top_sellers.py`; R2] |
| 06:50 daily | reorder_forecast | overwritten `reorder_hints` | Advisory hints stale; no finance-grade commitment should depend on them. [Evidence: `reorder_forecast.py`; commit `442b135`] |
| 07:15 daily | email_digest | append `digest_log` | Digest not recorded/sent; flag is read from `deploy/cron.env`. [Evidence: `email_digest.py`; commit `0bd4eac`] |
| 12:00 daily | intraday_report | append intraday snapshots | Today’s dashboard becomes stale; migrated DAG omitted the old 17:00 second refresh. [Evidence: DAG; retired cron; Q11] |
| 06:30 on day 1 | monthly_statement | append `statements` | Finance month not published; rerun can create duplicate month rows because there is no key/upsert. [Evidence: `monthly_statement.py`; `schema.sql`] |
| manual only | warehouse_backfill | replaces BigQuery tables | As committed, DAG invocation fails missing required CLI args; a successful rerun is destructive replacement, not incremental sync. [Evidence: `warehouse_backfill.py`; DAG]

All job connections use autocommit. Delete-then-insert jobs can expose empty or partially rebuilt tables, while append-only jobs can leave partial versions or duplicates; there are no inter-DAG dependencies, retries, freshness checks, or transactions encoded in this repository. [Evidence: `db.py` lines 20-26; all job files; all DAG files]

The Airflow DAGs use naive datetimes and do not specify `America/New_York`. The retired cron explicitly ran in local time and logs show its Eastern-to-UTC offsets; safe migration requires verifying the Airflow deployment’s default timezone before assuming the numeric cron hours preserved business time. [Evidence: `crontab.txt`; DAG files; Q17]

Two runbook traps are outside Airflow. The README still says trending uses 60 days although executable code uses 30 after commit `f563dea`; and `scripts/rerun_kpis.py` calls the discount helper without the finance-approved 0.25 cap, so it receives the helper’s legacy 0.40 default and has no implemented data extraction. [Evidence: README lines 33-35; `trending.py` lines 9-40; commit `f563dea`; `discounts.py`; `scripts/rerun_kpis.py`]

## 6. Data

### Warehouse map and freshness

Core app facts are `users`, `products`, `cart_items`, `orders`, `order_lines`, `payments`, `report_rows`, `report_rows_intraday`, `statements`, `top_products`, `accounts`, and `account_map`. Analytical outputs include affinity/model tables, KPI/funnel/trending/risk/pricing/reorder tables, test/category/restatement tables, and the four views `contactable_users`, `refunds_unified`, `statements_corrected`, and `statements_final`. [Evidence: BigQuery dataset inventory; warehouse manifest at `2ae79e2`]

Business event coverage ends on 2019-12-31 for orders, payments, products, users, and batch outputs. Five older orders have `updated_at = 2026-08-13 21:12:33`, all status 1 and priced below 2,600, so `MAX(updated_at)` is not a safe business-freshness watermark; use event time plus load metadata. [Evidence: Q18, Q22]

The backfill performs `bq load --replace` for every table, serializing Cloud SQL exports through GCS. It has no incremental cursor, reconciliation checksum, atomic all-table cutover, or preserved prior snapshot. [Evidence: `warehouse_backfill.py` lines 55-76]

The warehouse manifest says analytics tables load to dataset `analytics`, but the accessible dataset is `novamart_analytics`; this naming mismatch must be resolved before rerunning. The committed Airflow command also omits required `--project`, `--instance`, and `--staging` arguments. [Evidence: `warehouse_backfill.py` lines 47-75; BigQuery dataset inventory; DAG]

### Data-quality caveats

- `orders` is a mutable lifecycle/header table; `order_lines` is the item fact only from 2019-11-22 onward, so all item metrics require the legacy fallback. [Evidence: Q9, Q18; commit `92596dc`]
- `payments` can have several positive rows per merged order plus negative refund rows; joining and summing `orders.price` per payment duplicates header gross. [Evidence: Q3; `orders.py`]
- `statements` is append-only and has no uniqueness constraint on month; views can duplicate a month after a rerun. [Evidence: `schema.sql` lines 69-76; corrected-view DDL]
- Intraday rows are append-only snapshots. Every 2019-12-09 through 2019-12-31 day has two versions; raw sums are nearly double the latest snapshot on many days. [Evidence: Q11; commit `3eced24`]
- The blank-brand audit table captures 5,972 products and `38,499.83` historical revenue through 2019-10-21, so blank brand is known lineage debt rather than a legitimate segment. [Evidence: Q20; commit `ea0e97b`]
- The test-user table contains one user, while dashboard SQL also hard-codes numeric and UUID QA identities; test exclusion is not centralized. [Evidence: Q20; Redash queries 1-5; commit `adbcb7e`]
- Reconcile currently finds 130 duplicate payment references and only logs them; it does not repair or quarantine transactions. [Evidence: Q20; `reconcile.py`]
- The `refunds_unified` snapshot has no order appearing in multiple refund kinds, but its `UNION ALL` design permits future double counting if status and gateway pathways both record the same refund. [Evidence: Q22; view DDL]

### Safe query rules

Use half-open Eastern business windows converted to UTC for calendar reporting; do not use UTC date truncation for finance. [Evidence: `timeutil.py` lines 20-40; commit `102c9b4`]

Use `order_lines` plus the no-lines header fallback for item units/revenue, but use one order header for finance order count/gross. Never count headers after joining payments without re-aggregating payments per order. [Evidence: `orders.py`; commit `92596dc`; Q3, Q9]

For snapshot tables, select the maximum `created_at` per report date before summing. For overwritten score tables, select the maximum `updated_at` batch consistently; do not mix partial timestamps. [Evidence: Redash queries 5 and 8; `similar.py` lines 92-106]

## 7. Experimentation

### Recommendation experiment

The only explicit online allocation is a deterministic 1-in-20 hash bucket. Its random arm shuffles only the first 500 catalog IDs ordered by ID, not the full eligible catalog, and records decisions in `rec_decision_log`. [Evidence: `similar.py` lines 48-50, 73-87]

During the v2 period, the log contains 14,566 random-arm decisions, 52,695 v2-score decisions, and 207,959 fallbacks; roughly four-fifths of non-random v2 traffic fell back because scores were absent or filtered. [Evidence: Q12]

An item-line-aware descriptive check found a seven-day recommended-item purchase rate of `1.43%` for v2-scored exposures, `0.35%` for fallback, and `0.00%` for the random arm; 24-hour any-order rates were `7.90%`, `5.87%`, and `5.51%`. These are exposure-level descriptive rates, not a causal model win, because eligibility, candidate pools, repeated impressions, sparse coverage, and deterministic user assignment differ. [Evidence: Q15]

Affinity v2 itself is not a learned model: it weights co-cart pairs and an `EXISTS` purchase indicator, adds category/price heuristics and seasonality, and marks pairs with fewer than three observations as `-1`. Its conversion query has no time ordering relative to the cart, so prior or later purchases can label a pair as converted. [Evidence: `affinity_v2.py` lines 13-60]

Version 4 trains logistic regression on random-arm exposures, but its target is “any later paid order by the user,” with no horizon and no requirement that the purchased item was recommended. It fetches stock and opt-in but omits them from the vector, and it never fetches the README-claimed region affinity or device mix. [Evidence: `model_train.py` lines 30-57; README lines 41-43]

Version 4 then uses only coefficient zero to multiply every affinity-v2 pair score by the same factor. The result has zero observed ranking changes and has never been served under the current flag. There is no holdout evaluation, calibration report, or causal experiment analysis in the repository. [Evidence: `model_train.py` lines 60-75; Q13-Q15; `deploy/flags.env`]

Conclusion: affinity v2 shows better descriptive item-purchase rates where it has coverage, but the company has not demonstrated that v4 works as a learned recommender. A safe next experiment would freeze labels to a declared horizon, score candidate/user features per impression, randomize comparable candidate sets, log item-level outcomes, and predeclare coverage and lift metrics. [Evidence for current-state conclusion: Q12-Q15; `model_train.py`; `similar.py`]

### Other experiments

Dynamic pricing is shadow-only: nightly `price_suggestions` rewrites up to 500 products with a ±5% nudge based on whether demand is above the batch median. Historical query logs show 18,537 writes and zero reads, and the storefront continues to use vendor-feed/request prices. [Evidence: `price_suggest.py`; Q17; `catalog.py`, `orders.py`; commits `894c535`, `cca9b0d`]

Reorder hints are a hand-fit inverse-velocity heuristic, not ML. Lower velocity mechanically yields a larger hint; the table covers only the top 200 paid-order products over 14 days and is overwritten nightly. It is advisory and unsuitable for finance commitments. [Evidence: `reorder_forecast.py`; commit `f85cdd2`; `docs/forecast_caveats.md` at `2ae79e2`]

Fraud scoring is a deterministic heuristic that changed threshold from 0.90 to 0.70 and then 0.85. Logs show the threshold transitions and held counts; because status 6 is absent from daily-report exclusions, threshold experiments also alter the gap between dashboard and finance revenue. [Evidence: Q19; commits `53f6f6c`, `1cb8721`; `constants.py`]

## 8. Glossary

- **As-published statement** — immutable row emitted by the monthly job in `novamart.statements`. [Evidence: `monthly_statement.py`; Q1]
- **Corrected statement** — as-published row with a finance override applied by `statements_corrected`. [Evidence: view DDL]
- **Final statement** — corrected row after chargebacks are assigned to original order month. [Evidence: `statements_final` DDL]
- **Gross** — paid order-header price sum in the monthly statement; product dashboards use item-price gross under different filters. [Evidence: `monthly_statement.py`; R2-R5]
- **Net** — statement gross less collected processing fees and, in the final view, chargebacks; it is not synonymous with summed `payments.net`. [Evidence: `monthly_statement.py`; final-view DDL]
- **Order header** — one `orders` row, possibly representing several same-session callbacks/items after 2019-11-22. [Evidence: `orders.py`; commit `5d1300d`]
- **Item order** — one `order_lines` row, with a legacy `orders` fallback when no lines exist. [Evidence: commit `92596dc`]
- **Paid** — status 1. [Evidence: `orders.py`, `monthly_statement.py`]
- **Held** — status 6, assigned by fraud scoring; excluded from monthly finance but not daily reports. [Evidence: `fraud_score.py`; `constants.py`]
- **Refund** — ambiguous: order status 3, negative gateway payment, and the dashboard’s inclusion of status-2 cancellations. [Evidence: `refunds_unified` DDL]
- **Active customer** — consumer-specific; nightly trailing paid buyer, executive daily ordering user, or board-cleaned trailing buyer. [Evidence: `kpi_daily.py`; R1, R5]
- **Contactable user** — opted-in, valid, non-example email according to the analytics view; not the population used by `email_digest`. [Evidence: view DDL; `email_digest.py`]
- **Registered account** — UUID beta identity in `accounts`, mapped to legacy numeric user identity. [Evidence: `accounts.py`; R7]
- **Affinity v1** — legacy 30-day recency-weighted co-cart score in `product_affinity`. [Evidence: `affinity.py`]
- **Affinity v2 / serving 2.0.0** — conversion/category/price/season-adjusted co-cart score stored with row version 2.0.1 and actively served. [Evidence: `affinity_v2.py`; `similar.py`; flag]
- **v4** — nightly logistic fit whose output is a global rescaling of v2 scores; trained but not enabled. [Evidence: `model_train.py`; Q14]
- **Fallback** — latest trending top five used when the selected score table yields no usable rows. [Evidence: `similar.py` lines 115-128]
- **Random arm** — deterministic 5% user bucket receiving a shuffle of the first 500 eligible product IDs. [Evidence: `similar.py`]
- **Snapshot table** — append-only report output where consumers must select the latest batch timestamp. [Evidence: R5, R8; Q11]
- **Shadow table** — generated but not served output, notably `price_suggestions`. [Evidence: `price_suggest.py`; Q17]

# Appendix

## A. Evidence catalog

- **E0** — local wall-clock command; `git rev-parse HEAD`; clean `git status`; goal and extra-context files supplied for task `novamart`.
- **E1** — repository files at commit `2ae79e23690f7ef09a2e9231fdfa3a2cdb84be00`, especially `schema.sql`, `novamart/routers/*`, `novamart/jobs/*`, `airflow/dags/*`, and `deploy/*.env`.
- **E2** — historical dashboard SQL at commit `1179287`, immediately before commit `57ea43a` removed `dashboards/` during the Redash migration.
- **R0** — Redash data source 1 metadata: name `novamart serving (Cloud SQL)`, type `pg`, `view_only=true`; dashboard inventory contains nine dashboards.
- **R1-R9** — Redash query IDs: 1 `actives_board`, 2 `best_sellers`, 3 `brand_revenue`, 4 `category_revenue`, 5 `daily_kpis`, 6 `refunds`, 7 `registered_conversion`, 8 `revenue_widget`, 9 `statements_final`. Each is described as migrated from its former repository SQL file and has no schedule.
- **Q1** — `finance_1.sql`: union of `novamart.statements`, `novamart_analytics.statements_corrected`, and `novamart_analytics.statements_final`, ordered by month/source.
- **Q2** — `finance_2.sql`: orders grouped by Eastern month and status with row count, value, and buyers.
- **Q3** — `finance_3.sql`: paid orders joined to payments by original order month, exposing payment-row multiplicity, fees, net, and gateway refunds.
- **Q4** — `finance_4.sql`: `refunds_unified` grouped by Eastern event month and kind.
- **Q5** — `finance_5.sql`: overrides, corrections, and chargebacks grouped by original order month.
- **Q6** — `product.sql`: exact Redash best-seller semantics translated to BigQuery and anchored to `MAX(orders.created_at)`, with paid comparisons added.
- **Q7** — `product_brand.sql`: exact Redash brand semantics translated and data-anchored, with paid comparisons.
- **Q8** — `product_category.sql`: item-line and effective-dated taxonomy reconstruction, data-anchored, with paid comparisons.
- **Q9** — `product_integrity.sql`: header/item counts and revenue by Eastern month.
- **Q10** — `customer.sql`: three active-customer definitions reproduced at the warehouse’s event-time anchor.
- **Q11** — `report_snapshots.sql`: intraday version count, raw sum, and latest-version sum by report date.
- **Q12** — `ml_summary.sql`: recommendation decisions by intended/effective version, source, arm, and reason.
- **Q13** — `ml_registry.sql`: all 17 v4 training registry rows, 2019-12-15 through 2019-12-31.
- **Q14** — `ml_scores.sql`: latest v2/model pair join, score ratio, and per-base rank mismatch check.
- **Q15** — `ml_outcomes.sql`: descriptive exposure outcomes with item-line-aware recommended-item attribution.
- **Q16** — `batch_tables.sql`: row counts and batch timestamps for report and analytical outputs.
- **Q17** — `query_lineage.sql`, `job_log_sample.sql`, and `job_runs.sql`: production SQL-read/write lineage and job history.
- **Q18** — `warehouse_freshness.sql`: core table row counts and event/update timestamps.
- **Q19** — `job_crashes.sql` and `fraud_runs.sql`: three affinity-v2 December crashes and fraud threshold history.
- **Q20** — `operational_checks.sql`: 130 duplicate refs/285 rows, 5,972 blank-brand audit rows, and one test user.
- **Q21** — `customer_segments.sql`: monthly first-seen users, placeholder emails, opt-ins, and account counts.
- **Q22** — `focused_checks.sql`: board exclusions, contactable view count, five 2026-dated order updates, refund overlap, and selected query lineage.
- **Q23** — `customer_registered.sql`: latest stored KPI rows; 1,152 at 2019-12-31 11:15 UTC.
- **Q24** — registered conversion reconstruction from accounts → user email → paid orders: 30 registered buyers and `18,155.71` revenue.
- **L1** — `novamart_logs.db_queries` examples: v1 reads through 2019-12-06, v2 reads from 2019-12-06 through 2019-12-31, zero price-suggestion reads, and repeated active v2 serving lines at 2019-12-31 23:57:06.
- **L2** — `novamart_logs.job_runs` latest-day examples: affinity 08:30, affinity-v2 08:45, model train 09:15, price suggestions 09:45, trending 10:15, fraud 10:45, daily report 11:00, KPI 11:15, funnel 11:20, top sellers 11:45, reorder 11:50, digest 12:15, intraday 17:00 and 22:00 UTC.

## B. Definition-change timeline

- 2019-10-08 `83fb3ed`: daily report begins excluding test SKUs. [Evidence: commit]
- 2019-10-25 `ba1fbfa`: Lucente hidden from reports. [Evidence: commit]
- 2019-11-02 `a92c96d`: statement fee changes from aggregate percentage to collected per-payment fee. [Evidence: commit]
- 2019-11-05 `102c9b4`: business-day UTC bounds fixed for DST fallback. [Evidence: commit]
- 2019-11-18 `11c0a42`: cancelled/refunded statuses removed from daily report. [Evidence: commit]
- 2019-11-19 `1233af8`: 500-row report scan cap removed from execution, though the stale constant remains. [Evidence: commit; current `daily_report.py`]
- 2019-11-20 `12e1c68`: fee becomes 2.9% plus 0.30 per payment callback. [Evidence: commit]
- 2019-11-22 `5d1300d`: same-session callbacks merge; header versus item semantics diverge. [Evidence: commit]
- 2019-11-27 `b59f077`: QA smoke user excluded from report/dashboard logic. [Evidence: commit]
- 2019-12-05 `92596dc`: daily/product dashboards move to item lines plus legacy fallback. [Evidence: commit]
- 2019-12-09 `cd559d3`: chargeback-aware final statements introduced. [Evidence: commit; view DDL]
- 2019-12-06 `f563dea`: trending lookback shortens from 60 to 30 days; the README remains stale. [Evidence: commit; `trending.py`; README]
- 2019-12-15 `1169e40`: Jetem joins Lucente on the report/dashboard denylist. [Evidence: commit]
- 2019-12-23 `a3bffec`: unified refunds/dashboard introduced. [Evidence: commit; view DDL]
- 2019-12-24 `3eced24`: revenue widget fixed to select latest snapshots and avoid overlap. [Evidence: commit]
- 2020-01-03 `57ea43a`: dashboards move from Git SQL files to Redash. [Evidence: commit; R1-R9]
- 2020-01-04 `43e54a1`: schedules move from cron to Airflow. [Evidence: commit; DAGs]
- 2020-01-05 `2ae79e2`: one-shot Postgres-to-BigQuery replacement backfill added. [Evidence: commit]

## C. Operational runbook

For a disputed monthly finance number: identify the requested semantic layer; read all three statement surfaces; inspect overrides/corrections and chargebacks; compare later status changes separately; report both the as-published and current-restated answers if the request is ambiguous. [Evidence: Q1-Q5]

For a disputed product number: copy the exact Redash query; pin an as-of timestamp; use item-line fallback; preserve its status, QA, SKU, brand, timezone, and mapping rules; then show a paid-only comparison rather than silently “fixing” the dashboard definition. [Evidence: R2-R5; Q6-Q9]

For a failed append-only report job: rerun with a new batch timestamp and verify consumers select the latest complete version. For a delete-first score/hint job: do not rerun until the serving fallback and table-rebuild atomicity are understood; stage and swap is safer than delete then row-by-row insert. [Evidence: job code; R5/R8; Q11]

Before enabling v4: fix labels and candidate scoring, add offline/online evaluation, verify full-catalog randomization, stage model scores atomically, then change `REC_MODEL_VERSION` and redeploy while monitoring effective version, fallback rate, and item-level outcomes in `rec_decision_log`. [Evidence: `similar.py`; `model_train.py`; Q12-Q15]

Before rerunning warehouse backfill: supply and validate required CLI arguments, resolve `analytics` versus `novamart_analytics`, export to a new staging prefix, load to staging tables, compare counts/checksums and view dependencies, and only then cut over. The committed DAG must not be treated as a safe ready-to-run rebuild. [Evidence: `warehouse_backfill.py`; DAG; BigQuery inventory]
