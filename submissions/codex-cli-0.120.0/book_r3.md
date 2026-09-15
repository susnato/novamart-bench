# 1. Summary

## Exercise record

- Started: **2026-08-27 17:08:43 IST**.
- Run UUID: **649d71f9-810f-47c3-bcb1-717154a2a0a4**.
- Code scope: only the pinned repository at commit `2ae79e23690f7ef09a2e9231fdfa3a2cdb84be00`; the worktree was clean when inspected.
- Data scope: read-only BigQuery project `<warehouse-project>`, datasets `novamart`, `novamart_analytics`, and `novamart_logs`; the business data spans 2019-09-25 through 2019-12-31, so it is a historical snapshot, not current production state. (Evidence: query **Q1**; commit `2ae79e2`, `novamart/jobs/warehouse_backfill.py`; Airflow DAG `warehouse_backfill`, `schedule=None`.)
- Dashboard scope: the nine read-only Redash dashboards at `<redash-url>`; no query was executed or refreshed because every saved query had `latest_query_data_id=null`. (Evidence: Redash dashboards **#1–#9**, queries **#1–#9**.)

## The tenured-operator answer

There is no single unqualified “revenue” number at Novamart. For a closed month and current finance reporting, use `<warehouse-project>.novamart_analytics.statements_final`; to reproduce what was published at the time, use `<warehouse-project>.novamart.statements`; for daily executive/product reporting, use the latest `report_rows`/`report_rows_intraday` snapshots or the exact saved dashboard SQL, because those numbers are item-level and intentionally exclude test users, statuses, SKUs, and brands. (Evidence: views `statements_final` and `statements_corrected`; Redash dashboard **#9/query #9**; Redash dashboard **#5/query #5**; commit `2ae79e2`, `novamart/jobs/daily_report.py`.)

The final-statement label must be read literally: `statements_final` starts with the append-only published statement, applies explicit overrides, then subtracts booked `chargebacks`. It does **not** consume `refunds_unified`, later cancellation/refund statuses, or negative gateway-refund payment rows. Consequently, it is the declared finance source of truth but not a complete economic-refund ledger. (Evidence: BigQuery view definitions `novamart_analytics.statements_corrected`, `novamart_analytics.statements_final`, and `novamart_analytics.refunds_unified`; query **Q4**; commit `a576d0d`.)

October 2019 is the canonical worked example: the original statement was gross **1,230,332.43**, fee **35,679.64**, net **1,194,652.79**, and 3,765 orders; a fee override reduced fee by **0.14**, raising corrected net to **1,194,652.93**; three booked chargebacks totaling **3,567.57** then reduced final gross and net to **1,226,764.86** and **1,191,085.36**. (Evidence: query **Q2** and query **Q3**; `novamart.statements`; `novamart_analytics.statement_overrides`; `novamart_analytics.chargebacks`; `novamart_analytics.statements_final`.)

The product dashboards are not finance statements. Best sellers is a rolling 7×24-hour, item-row query ranked by revenue with no status filter; brand and category revenue use 30×24-hour windows. All three use `order_lines` for post-2019-11-22 multi-item orders and a legacy `orders` fallback, exclude numeric QA user `424242`, and deny `lucente`/`jetem`; they do not exclude the configured test SKUs, so product `1002544` can appear in best sellers even though daily reports omit it. (Evidence: Redash dashboards **#2–#4**, queries **#2–#4**; query **Q12**; commit `92596dc`; commit `1169e40`; commit `2ae79e2`, `novamart/constants.py`.)

Customer counts are also definition-specific. The nightly KPI is trailing-30-day distinct `status=1` buyers; the executive daily KPI is distinct ordering users per Eastern calendar day with no status filter plus brand/QA cleanup; the board KPI is trailing-30-day buyers under different status rules and aggressive test-email cleanup. At the end-of-data anchor, comparable recomputations were 1,146 nightly-style, 1,151 pre-clean board candidates, **0** post-clean board actives, and 54 executive-daily actives for 2019-12-31. (Evidence: query **Q8**; `novamart_analytics.kpi_daily`; Redash dashboard **#1/query #1**; Redash dashboard **#5/query #5**; commit `14726e7`.)

The board count is zero because storefront-created shoppers use synthetic `@example.com` addresses and the board query excludes `example.com`; this is a structural incompatibility, not a small cleanup adjustment. The `contactable_users` view is also currently empty because it requires marketing opt-in and a valid non-example email, even though the email digest independently counted 40 non-`@example.com` recipients without using that view or checking opt-in. (Evidence: query **Q9**; view `novamart_analytics.contactable_users`; Redash dashboard **#1/query #1**; `novamart_logs.job_runs` log line at `2019-12-31T12:15:00Z`; commit `2ae79e2`, `novamart/jobs/email_digest.py`.)

The live recommendation flag is `2.0.0`, which serves `product_affinity_v2`, not the trained v4 scores. The v4 job is shadow output: on the last snapshot it multiplied every usable v2 candidate score by essentially the same factor and changed **zero of 948 pair ranks across 449 base products**. It therefore cannot improve ranking in its current form. (Evidence: commit `2ae79e2`, `deploy/flags.env`, `novamart/routers/similar.py`, and `novamart/jobs/model_train.py`; queries **Q14** and **Q15**.)

Recommendation coverage is poor: after the v2 rollout, 52,695 decisions used the v2 “model” source, 207,959 fell back to trending, and 14,566 used the random arm. The random arm is deterministic by user, but its candidate “uniform” pool is only the first 500 product IDs after exclusions, not the entire catalog. (Evidence: query **Q13** and query **Q16**; commit `2ae79e2`, `novamart/routers/similar.py`.)

The operational schedules moved from retired `crontab.txt` to Airflow at commit `43e54a1`; every scheduled DAG has `catchup=False`. A missed monthly statement therefore leaves the month absent from both corrected/final views, and a failed daily snapshot leaves a dashboard hole rather than being automatically backfilled. (Evidence: commit `43e54a1`; `airflow/dags/*.py`; Redash dashboard **#9/query #9**.)

## Confidence and principal caveats

This document has high confidence for code paths, stored data, saved dashboard definitions, and historical logs because each was independently cross-checked. It does not claim that BigQuery is continuously synchronized: the only warehouse loader in scope is a manual, table-by-table `--replace` backfill with no schedule. It also does not claim causal recommendation lift: the available comparison is observational, repeated-exposure data with time and eligibility confounding. (Evidence: commit `2ae79e2`, `novamart/jobs/warehouse_backfill.py`; Airflow DAG `warehouse_backfill`; query **Q17**.)

# 2. Why this project

Novamart’s numbers diverge for systematic reasons: one business concept is represented by multiple grains, time windows, status policies, cleanup filters, and publication states. Without this map, a correct query against the wrong surface will produce a confidently wrong answer. (Evidence: `novamart.orders`, `novamart.order_lines`, `novamart.payments`, `novamart.report_rows`, `novamart.statements`, and `novamart_analytics.statements_final`; Redash dashboards **#1–#9**.)

The project is necessary for five concrete reasons:

1. **Order grain changed.** Before 2019-11-22, one `orders` row represented one item. After same-session callback merging, one `orders` row can contain up to six item/payment rows; product reporting must use `order_lines` plus a legacy fallback, whereas monthly finance deliberately uses the order total. (Evidence: commit `5d1300d`; query **Q5**; `novamart_logs.db_queries` first `order_lines` creation at `2019-11-22T15:15:52Z`.)
2. **Published finance is immutable but restated finance is layered.** The monthly job appends a snapshot; overrides and chargebacks live separately. Re-running a raw order query today is not a reproduction of what the board saw then. (Evidence: commit `2ae79e2`, `novamart/jobs/monthly_statement.py`; views `statements_corrected` and `statements_final`; query **Q2**.)
3. **Dashboard cleanup is business logic.** `lucente`, `jetem`, QA user `424242`, two explicit SKUs, and `analytics.test_users` are omitted on some—but not all—surfaces. (Evidence: commit `1169e40`; commit `b59f077`; `novamart/constants.py`; Redash queries **#2–#5**.)
4. **Customer identity has two namespaces.** Historical commerce uses numeric `users.id`; the accounts beta uses UUID `accounts.account_id`. The registered-conversion dashboard maps by email, while the UUID exclusion in brand revenue is ineffective against numeric `orders.user_id`. (Evidence: Redash dashboard **#7/query #7** and dashboard **#3/query #3**; `novamart.orders` and `novamart.accounts` schemas; commit `b975479`.)
5. **“ML” covers production, shadow, and heuristic systems.** Affinity v2 is served, v4 scores are trained but flag-disabled and rank-equivalent to v2, dynamic pricing is shadow-only, and reorder hints are hand-fit advisory numbers. (Evidence: commit `2ae79e2`, `deploy/flags.env`, `novamart/jobs/model_train.py`, `novamart/jobs/price_suggest.py`, and `novamart/jobs/reorder_forecast.py`; query **Q15**.)

The practical outcome is a decision guide: identify the consumer and as-of state first, then select the metric definition and source. That is safer than trying to force every surface to reconcile to a single universal total. (Evidence: Redash queries **#1–#9**; query **Q2** and query **Q8**.)

# 3. Business understanding

## 3.1 Order-to-cash flow

1. A product view, cart action, or order can lazily create `users` and `products`; user attributes and placeholder emails are deterministic from numeric IDs, so `users.created_at` often means “first observed by the storefront,” not a deliberate signup. (Evidence: commit `2ae79e2`, `novamart/routers/catalog.py`, `novamart/routers/carts.py`, `novamart/onboarding.py`, and `novamart/routers/accounts.py`.)
2. `POST /orders` receives a gateway callback containing user, product, price, payment reference, session, and timestamp. The app takes advisory transaction locks on session and reference, checks both `orders.payment_ref` and `order_lines.payment_ref`, and ensures a payment exists, making callback replay idempotent by reference. (Evidence: commit `b676969`; commit `2ae79e2`, `novamart/routers/orders.py`.)
3. A new callback creates a pending order (`status=0`), an `order_lines` row, and a `payments` row, then marks the order paid (`status=1`). A callback in the same user/session within 15 minutes appends a line/payment and increments `orders.price`; this is why order totals and item rows now have different grains. (Evidence: commit `5d1300d`; commit `2ae79e2`, `novamart/routers/orders.py`; query **Q5**.)
4. Each positive payment stores gross, fee, and net. The current formula is `round(price*0.029 + 0.30, 2)`; the flat fee began on 2019-11-20, while earlier transactions used only 2.9%. (Evidence: commit `12e1c68`; `novamart/constants.py`; `novamart/jobs/monthly_statement.py`.)
5. Cancellation changes order status to `2`; an application refund changes status to `3`; the later gateway-refund webhook instead inserts a negative `payments` row and does not change order status. (Evidence: commits `8f19718`, `d87cb3d`, and `c49a7bb`; `novamart/routers/orders.py`; `novamart/routers/payments_webhook.py`.)
6. Fraud scoring can move recent paid orders to held status `6`; held orders are excluded by `status=1` finance/top-seller jobs but included by the board active-customer candidate rule because that rule excludes only `0,2,3`. (Evidence: commit `e4656fb`; commit `1cb8721`; `novamart/jobs/fraud_score.py`; Redash dashboard **#1/query #1**.)

## 3.2 Status semantics actually observed

| Status | Meaning in current code | Snapshot rows / gross | Consequence | Evidence |
|---:|---|---:|---|---|
| 0 | Pending during order creation | 0 / 0 | Most jobs exclude it; normal callback immediately promotes it to 1. | `novamart/routers/orders.py`; query **Q6** |
| 1 | Paid/completed | 9,033 / 2,860,063.26 | Finance and most jobs count this status. | `novamart.orders`; query **Q6** |
| 2 | Cancelled | 54 / 13,249.64 | Removed from daily reports; counted as `order_cancelled` by `refunds_unified`. | `novamart/constants.py`; view `refunds_unified`; query **Q7** |
| 3 | Refunded | 28 / 13,447.47 | Removed from daily reports; counted as `order_refunded` by `refunds_unified`. | `novamart/constants.py`; view `refunds_unified`; query **Q7** |
| 5 | Unknown reserved state, ignored by reconcile | 0 / 0 | The reconcile query excludes it, but no current writer or business definition in the scoped repo assigns it. | `novamart/jobs/reconcile.py`; query **Q6** |
| 6 | Fraud-held | 12 / 40,213.29 | Excluded by `status=1` jobs; not excluded by the board active rule. | `novamart/jobs/fraud_score.py`; query **Q6** |

## 3.3 The finance publication lifecycle

The monthly job runs at 06:30 on day 1, derives the previous Eastern calendar month, sums `orders.price` and order count where `status=1`, sums collected `payments.fee` joined to those orders, calculates `net=gross-fee`, and appends one row to `statements`. It warns if collected fees differ from the time-aware expected fee but stores the collected fee. (Evidence: commit `2ae79e2`, `novamart/jobs/monthly_statement.py`; Airflow DAG `monthly_statement`; `novamart_logs.db_queries` statement inserts at `2019-10-01T10:30:00Z`, `2019-11-01T10:30:00Z`, and `2019-12-01T11:30:00Z`.)

The fee algorithm changed twice historically. The initial job calculated fee as `round(monthly_gross*0.029,2)`, which differs from summing rounded per-transaction fees; commit `a92c96d` changed the stored fee to the collected payment sum. Commit `4a58d17` then made the warning’s expected-fee calculation aware of the 2019-11-20 flat-fee change. (Evidence: commits `a92c96d`, `12e1c68`, and `4a58d17`; historical `novamart/jobs/monthly_statement.py` at those commits.)

The publication layers are:

| Layer | Meaning | Use it for | Evidence |
|---|---|---|---|
| `novamart.statements` | Append-only result emitted by the monthly job at publication time. | Old board/deck reproduction and audit of “what did we say then?” | Table `novamart.statements`; Redash log insert lines; commit `a576d0d` |
| `novamart_analytics.statements_corrected` | Published row with any explicit `statement_overrides` replacement. | Explaining approved statement-generation corrections before chargebacks. | View definition `statements_corrected`; table `statement_overrides` |
| `novamart_analytics.statements_final` | Corrected row less chargebacks grouped to the original order’s Eastern month. | Declared current finance/external reporting source. | View definition `statements_final`; Redash dashboard **#9/query #9** |
| `novamart_analytics.refunds_unified` | Operational union of status-based cancellations/refunds and negative payment movements. | Refund operations/monitoring, with deduplication caveat. | View definition `refunds_unified`; Redash dashboard **#6/query #6** |

The refund dashboard counts union rows, not distinct orders. There are 91 rows across 85 orders, and three orders are represented by both a status event and gateway-refund row, contributing 1,843.59 twice to the undeduplicated total. (Evidence: query **Q7**.)

## 3.4 How to answer “what was revenue in month M, and why?”

1. Ask whether the caller means original publication, current restated finance, current mutable order state, or executive/product sales. Each is a different contract. (Evidence: query **Q2**; Redash dashboards **#2–#5** and **#9**.)
2. For an already published, current finance answer, select the month from `novamart_analytics.statements_final`. For historical-deck reproduction, select it from `novamart.statements` and show the delta through `statement_overrides` and `chargebacks`. (Evidence: views `statements_corrected` and `statements_final`; query **Q2** and **Q3**.)
3. If no statement exists, label the result provisional and sum `orders.price` over the Eastern month with `status=1`; separately reconcile payment gross/fee/net and refund movements. Do not silently call this a final statement. (Evidence: `novamart/jobs/monthly_statement.py`; query **Q4**.)
4. For an executive/product dashboard match, reproduce that dashboard’s item-line fallback, window, status behavior, and exclusions rather than using finance SQL. (Evidence: Redash queries **#2–#5**; `novamart/jobs/daily_report.py`.)

### Worked month: October 2019

| Stage | Gross | Fee | Net | Why | Evidence |
|---|---:|---:|---:|---|---|
| As published | 1,230,332.43 | 35,679.64 | 1,194,652.79 | Snapshot written 2019-11-01 before later status changes. | `novamart.statements`; query **Q2**; DB log `2019-11-01T10:30:00Z` |
| Corrected | 1,230,332.43 | 35,679.50 | 1,194,652.93 | Override sums per-order collected payment fees, a 0.14 correction. | `statement_overrides`; `statements_corrected`; query **Q3** |
| Final | 1,226,764.86 | 35,679.50 | 1,191,085.36 | Three chargebacks totaling 3,567.57 are attributed to October order dates. | `chargebacks`; `statements_final`; query **Q3** |
| Current mutable paid-order query | 1,206,337.32 | — | — | Later cancellations/refunds/holds changed statuses after publication. | `novamart.orders`; query **Q4** |

September is the sharpest warning: the stored final statement remains gross 2,702.00/net 2,623.64, while the current warehouse has zero status-1 September orders because all twelve were later cancelled/refunded. `statements_final` is therefore “final under the approved override-plus-chargeback policy,” not “net of every later refund/cancellation.” (Evidence: query **Q2** and query **Q4**; view definition `statements_final`.)

December has no row in `statements`, `statements_corrected`, or `statements_final` in this snapshot. The current mutable status-1 order gross is 552,328.93 and must be presented as provisional, not finance-approved. (Evidence: query **Q2** and query **Q4**.)

## 3.5 Product and merchandising reporting

The daily report works on the previous Eastern calendar day, excludes statuses `0,2,3`, joins `analytics.test_users`, uses item lines with legacy fallback, and then removes SKUs `1004856`/`1002544` and brands `lucente`/`jetem`. It appends snapshots to `report_rows`; intraday uses the same logic for today and appends to `report_rows_intraday`. (Evidence: commit `2ae79e2`, `novamart/jobs/daily_report.py`, `novamart/jobs/intraday_report.py`, and `novamart/constants.py`.)

The daily report once read only the first 500 matching rows; commit `1233af8` replaced `fetchmany(REPORT_SCAN_CAP)` with `fetchall`. `REPORT_SCAN_CAP=500` remains in `constants.py` with a stale comment, but it no longer limits the current job. (Evidence: commit `1233af8`; commit `2ae79e2`, `novamart/constants.py` and `novamart/jobs/daily_report.py`.)

The executive daily KPI and revenue widget correctly choose the latest snapshot per day to avoid append-only duplication. The warehouse has one daily snapshot per 92 report days but two intraday snapshots on 23 days; summing intraday without latest-version selection double-counts. (Evidence: query **Q11**; Redash dashboard **#5/query #5** and dashboard **#8/query #8**; commit `3eced24`.)

The daily KPI column named `orders` is actually `SUM(report_rows.units)`, so it is a cleaned item-unit count rather than an order-header count. Its active-customer CTE, however, joins the order header product and applies the brand denylist to that header, which can make a multi-item customer’s inclusion depend on the first/header product rather than every line. (Evidence: Redash dashboard **#5/query #5**; commit `5d1300d`; `novamart.order_lines`.)

The report endpoint `/reports/brands` is a separate definition: it uses one header `orders.product_id` per order, status `1`, Eastern month boundaries, and the same SKU/brand denylists. It does not expand multi-item `order_lines`, so it attributes an entire merged order total to the header product’s brand and should not be expected to match Redash brand revenue. (Evidence: commit `2ae79e2`, `novamart/routers/reports.py`; Redash dashboard **#3/query #3**.)

## 3.6 Customer and identity lifecycle

`users` is the legacy numeric identity and has 38,950 rows. Because views/carts/orders lazily create users with `user<ID>@example.com`, this table is an observed-shopper registry rather than a clean explicit-signup fact. (Evidence: query **Q9**; commit `2ae79e2`, `novamart/routers/catalog.py`, `novamart/routers/carts.py`, and `novamart/onboarding.py`.)

`accounts` is the explicit registered-account beta with UUID IDs; it has 30 accounts mapped to 30 legacy UIDs. The registered-conversion dashboard maps account email to user email, then counts all-time status-1 buyers/revenue; the snapshot result is 30 buyers and 18,155.71. (Evidence: query **Q9**; Redash dashboard **#7/query #7**; commit `b975479`.)

`contactable_users` requires marketing opt-in, a syntactically valid email, and a domain that is not `example.com/.net/.org`, `*.example`, or similar. The current view returns zero. The digest job does not use it: it merely counts `users.email NOT LIKE '%@example.com'`, which logged 40 recipients on 2019-12-31. (Evidence: view `contactable_users`; query **Q9**; commit `2ae79e2`, `novamart/jobs/email_digest.py`; job log `2019-12-31T12:15:00Z`.)

# 4. Metrics

## 4.1 Metric contracts and trust rules

| Metric | Exact contract | Official/actual consumer | Trust rule | Evidence |
|---|---|---|---|---|
| Monthly gross revenue | Published `SUM(orders.price)` for Eastern month where status was `1` at statement run. | Monthly statement and finance views. | Use `statements_final` for current approved reporting; it is not refund-complete. | `novamart/jobs/monthly_statement.py`; `statements_final`; query **Q2** |
| Monthly fee | Sum of collected `payments.fee` joined to qualifying orders. | Monthly statement. | Use stored statement/override, not `gross*rate`; per-transaction rounding and flat fees matter. | commit `a92c96d`; `novamart/jobs/monthly_statement.py` |
| Monthly net | `gross-fee`, then override, then chargebacks in final view. | Finance dashboard #9. | Does not subtract `refunds_unified`. | view `statements_final`; Redash **#9/query #9** |
| Refund count/total | Count and sum every row in `refunds_unified`, grouped by refund-event month. | Refund dashboard #6. | Deduplicate by `order_id` for unique refunded orders; cancellations are included as refunds. | view `refunds_unified`; Redash **#6/query #6**; query **Q7** |
| Daily report revenue | Sum item prices for Eastern day after status/test/SKU/brand cleanup. | `report_rows`, daily KPI, revenue widget. | Select latest snapshot per day; do not compare directly to finance. | `daily_report.py`; Redash **#5/#8**; query **Q11** |
| Best sellers | Rolling 7×24h item rows, all statuses, QA/brand cleanup, rank by revenue, top 20. | Redash #2. | It can include cancelled/refunded/held orders and configured excluded SKUs. | Redash **#2/query #2**; query **Q12** |
| Brand revenue | Rolling 30×24h item rows, all statuses, QA/brand cleanup. | Redash #3. | Blank and `internal` brands remain; UUID exclusion cannot match numeric user IDs. | Redash **#3/query #3**; query **Q12** |
| Category revenue | Rolling 30×24h item rows mapped using taxonomy valid at item date. | Redash #4. | Unknown categories become `other`; six codes have historical mappings. | Redash **#4/query #4**; query **Q10** |
| Nightly active customers | Distinct status-1 buyers in prior 30×24h at run time. | `kpi_daily`. | Includes synthetic/test users; append-only per run. | `kpi_daily.py`; table `kpi_daily`; query **Q8** |
| Executive daily active | Distinct ordering users per Eastern day, no status filter, user 424242 and brands denied. | Redash #5. | A per-day series, not trailing 30 days; does not use `kpi_daily`. | Redash **#5/query #5** |
| Board active | Distinct trailing-30d users with status not in 0/2/3, then test-table/email cleanup. | Redash #1. | Currently structurally zero because synthetic emails are excluded. | Redash **#1/query #1**; query **Q8** |
| Contactable customers | Ordering users that join to `contactable_users`. | Redash #5. | Current view is empty; do not infer digest recipients from it. | view `contactable_users`; Redash **#5**; query **Q9** |
| Funnel active users | Unique users with cart or order events in trailing 24h. | `daily_funnel`. | No product views and no order-status filter; not the same as buyers. | `funnel.py`; table `daily_funnel` |
| Registered conversion | All-time distinct paid legacy users whose email matches an account email; sum header order prices. | Redash #7. | Not a rate and has no time window; identity match is email-based. | Redash **#7/query #7** |
| Trending | Status-1 units over rolling 30 days, minimum 5, recency decay 0.05, top 50/day. | Homepage and rec fallback. | README’s 60-day statement is stale after `f563dea`. | `trending.py`; commit `f563dea`; table `trending_daily` |
| Reorder hint | `int(15.6 + 162.4/(velocity+1.8))`, velocity=status-1 orders/14 days, top 200. | Advisory table only. | Lower velocity mechanically produces a larger hint; never finance-grade. | `reorder_forecast.py`; table `reorder_hints`; commit `f85cdd2` |
| Price suggestion | ±5% around current list price based on above/below median demand among top 500. | Shadow table only. | No serving reader; phase 2 on hold. | `price_suggest.py`; commit `cca9b0d`; table `price_suggestions` |
| Fraud risk | `min(price/3000,1)*(1+0.15 new_account+0.15 high_velocity)`, capped at 1; hold if >0.85. | `order_risk` and status mutation. | Rule-based risk, not a trained model. | `fraud_score.py`; commit `1cb8721`; table `order_risk` |

## 4.2 Product-dashboard assumptions with measured impact

At the 2019-12-31 end-of-data anchor, the 30-day item-level population contained 1,917 rows and 577,259.57 revenue. Restricting to paid rows yielded 1,898 rows and 537,046.28, while the executive QA/brand filters—but still no status filter—yielded 1,880 rows and 569,650.05. The gap shows why adding a status filter to a dashboard reproduction does not “clean it up”; it changes the contract materially. (Evidence: query **Q12**.)

The same window contained 33 `lucente`/`jetem` rows worth 7,569.56 and four numeric-QA rows worth 39.96. Blank brand was still the fifth-largest brand group in the matched dashboard query, and `internal` brand was tenth, because only `lucente` and `jetem` are denied. (Evidence: query **Q12**; Redash dashboard **#3/query #3**.)

The matched best-seller query placed configured excluded SKU `1002544` sixth by revenue at the anchor. The daily report excludes that SKU, but Redash best sellers does not, so the two “top product” surfaces can disagree by design/omission. (Evidence: query **Q12**; `novamart/constants.py`; Redash dashboard **#2/query #2**.)

## 4.3 Active-customer reconciliation

| Definition at end-of-data anchor | Count | Main reason it differs | Evidence |
|---|---:|---|---|
| Nightly-style trailing 30d, status 1 | 1,146 | Paid-only, but no cleanup. | query **Q8** |
| Board candidate before cleanup | 1,151 | Includes held status 6. | query **Q8**; Redash **#1** |
| Board after cleanup | 0 | Excludes synthetic `example.com` shoppers. | query **Q8** |
| Executive daily on 2019-12-31 | 54 | One Eastern day, all statuses, brand/QA cleanup. | query **Q8**; Redash **#5** |
| Stored nightly KPI at 2019-12-31 11:15 UTC | 1,152 | Different exact 30×24h run anchor. | `kpi_daily`; job log `2019-12-31T11:15:00Z` |

## 4.4 Freshness metrics

The final warehouse snapshots were: affinity at 08:30 UTC, affinity v2 at 08:45, model scores at 09:15, price suggestions at 09:45, trending at 10:15, risk at 10:45, KPI at 11:15, funnel at 11:20, reorder hints at 11:50, digest at 12:15, and intraday reports at 17:00/22:00 on 2019-12-31. (Evidence: query **Q13**; `novamart_logs.job_runs` lines for 2019-12-31.)

# 5. System

## 5.1 Runtime architecture and lineage

The scoped system is a FastAPI service backed by Postgres/Cloud SQL. All application and job SQL passes through logging wrappers, producing the historical `db_queries` evidence. A January 2020 manual backfill exported each Postgres table to GCS and loaded it with BigQuery `--replace`, mapping `public.*` to dataset `novamart` and `analytics.*` to `novamart_analytics`. (Evidence: commit `2ae79e2`, `README.md`, `novamart/db.py`, `novamart/jobs/warehouse_backfill.py`, and `warehouse_manifest.json`.)

Redash saved queries target the Postgres names (`orders`, `analytics.*`), while BigQuery uses fully separate datasets (`novamart` and `novamart_analytics`). Analysts porting dashboard SQL to BigQuery must translate schema and SQL dialect, not paste it unchanged. (Evidence: Redash queries **#1–#9**; BigQuery table listings; view `db_queries_normalized`.)

The current scheduling source is Airflow, introduced at commit `43e54a1`; `crontab.txt` explicitly says retired. The DAGs are independent one-task wrappers with `catchup=False` and no declared inter-DAG dependencies, so ordering is conventional rather than enforced. (Evidence: commit `43e54a1`; `crontab.txt`; `airflow/dags/*.py`.)

## 5.2 Scheduled jobs and failure blast radius

Schedules below are the DAG cron expressions; historical logs line up with Eastern-local clock converted to UTC. (Evidence: `airflow/dags/*.py`; `novamart_logs.job_runs`.)

| Schedule | Job → output | If it fails | Evidence |
|---|---|---|---|
| `0 3 * * *` | `reconcile` → warning logs for duplicate `payment_ref`, max 200 | Duplicate references are not surfaced that night; the job never repairs them. | `reconcile_dag.py`; `reconcile.py`; log `2019-12-31T08:00:00Z`, flagged 130 |
| `30 3 * * *` | `affinity` → overwrite `product_affinity` | Legacy table becomes stale; current widget is unaffected under flag 2.0, though compute is still spent. | `affinity_dag.py`; `affinity.py`; query-log app reads end 2019-12-06 |
| `45 3 * * *` | `affinity_v2` → overwrite `product_affinity_v2` | Current exploit scores remain stale; serving does not enforce freshness and may keep using them. | `affinity_v2_dag.py`; `similar.py`; job crash logs 2019-12-03 through 2019-12-05 |
| `15 4 * * *` | `model_train` → append registry, overwrite `model_scores` when trainable | No effect under flag 2.0; under flag 4.0, trained scores become stale. | `model_train_dag.py`; `flags.env`; `model_train.py` |
| `45 4 * * *` | `price_suggest` → overwrite `price_suggestions` | Shadow analytics becomes stale; storefront prices are unaffected. | `price_suggest_dag.py`; `price_suggest.py`; commit `cca9b0d` |
| `15 5 * * *` | `trending` → replace one day in `trending_daily` | Homepage/fallback recommendations use the prior maximum day and silently become stale. | `trending_dag.py`; `trending.py`; `similar.py` |
| `45 5 * * *` | `fraud_score` → append `order_risk`, mutate high-risk orders to status 6 | Risky recent orders remain status 1 and can flow into finance/reporting. | `fraud_score_dag.py`; `fraud_score.py` |
| `0 6 * * *` | `daily_report` → append yesterday to `report_rows` | Executive daily KPI/revenue screens have a missing/stale closed day; no catchup is configured. | `daily_report_dag.py`; Redash **#5/#8** |
| `15 6 * * *` | `kpi_daily` → append trailing active count | `kpi_daily` consumers are stale; Redash daily KPI still computes its own actives directly. | `kpi_daily_dag.py`; `kpi_daily.py`; Redash **#5** |
| `20 6 * * *` | `funnel` → append `daily_funnel` | Session/user series misses a day. | `funnel_dag.py`; `funnel.py` |
| `45 6 * * *` | `top_sellers` → append `top_products` | The batch table misses a day; Redash best sellers is unaffected because it queries live order/item rows. | `top_sellers_dag.py`; `top_sellers.py`; Redash **#2** |
| `50 6 * * *` | `reorder_forecast` → overwrite `reorder_hints` | Advisory merchandising hints are stale; no finance/serving system should depend on them. | `reorder_forecast_dag.py`; `reorder_forecast.py` |
| `15 7 * * *` | `email_digest` → append `digest_log` | Digest is not sent/logged. | `email_digest_dag.py`; `email_digest.py` |
| `0 12 * * *` | `intraday_report` → append current-day snapshot | Today’s KPI/revenue screen stays on the last snapshot or has no today row. | `intraday_report_dag.py`; Redash **#5/#8** |
| `30 6 1 * *` | `monthly_statement` → append prior month to `statements` | Corrected/final finance views have no base row for the month; `catchup=False` means manual rerun is required. | `monthly_statement_dag.py`; views `statements_corrected/final` |
| none | `warehouse_backfill` → table-by-table BigQuery replacement | A partial rerun can leave datasets at mixed snapshot times; it is not a continuous replication path. | `warehouse_backfill_dag.py`; `warehouse_backfill.py` |

The retired cron ran intraday reporting at both 12:00 and 17:00, but the Airflow migration contains only `0 12 * * *`. Historical data has 47 snapshots over 24 days (two on 23 days); after migration, the second same-day refresh would disappear unless configured elsewhere outside the scoped repo. (Evidence: commit `43e54a1`; `crontab.txt`; `intraday_report_dag.py`; query **Q11**.)

## 5.3 Known production failures and silent degradation

Affinity v2 crashed on 2019-12-03, 12-04, and 12-05 with `IndexError` because the seasonal-factor list lacked December. Commit `3dbe4d7` added safe December handling; successful v2 writes began on 2019-12-06. During this class of failure, serving either uses any existing stale table or falls back when no usable scores exist; no explicit freshness alarm exists in the serving path. (Evidence: `novamart_logs.job_runs` ERROR lines at `2019-12-03T08:45:00Z` through `2019-12-05T08:45:00Z`; commit `3dbe4d7`; `novamart/routers/similar.py`.)

The serving cache invalidation checks `MAX(updated_at)` and silently catches every exception. This preserves availability but masks table/query failures and converts them to fallback behavior without an error signal in the response beyond `source=fallback` and logged `fallback_reason`. (Evidence: commit `2ae79e2`, `novamart/routers/similar.py`; `rec_decision_log`.)

## 5.4 Safe modification checklist

Before changing finance or reporting, preserve Eastern calendar boundaries, order-versus-item grain, historical fallback, status policy, and cleanup filters; run the October worked reconciliation and compare both published and final layers. (Evidence: `timeutil.py`; `monthly_statement.py`; Redash queries **#2–#5**; query **Q2**.)

Before changing recommendation pipelines, keep `score<0` as the “insufficient evidence” sentinel, preserve `updated_at` batch atomicity or replace delete/insert with an actually atomic publish, validate coverage/fallback rates, and test the exact feature flag. Both current affinity writers delete the table before row-by-row inserts, so a mid-run crash can expose an empty or partial table. (Evidence: `affinity.py`; `affinity_v2.py`; `similar.py`; `flags.env`.)

Before changing schedules, add explicit dependencies where outputs feed other jobs: affinity v2 should finish before model training; trending should finish before it is needed as fallback; daily report should finish before its dashboard SLA. The current DAGs do not encode these dependencies. (Evidence: `airflow/dags/affinity_v2_dag.py`, `model_train_dag.py`, `trending_dag.py`, and `daily_report_dag.py`.)

# 6. Data

## 6.1 App/serving snapshot (`novamart`)

| Table | Grain and role | Caveat | Evidence |
|---|---|---|---|
| `users` | One legacy numeric shopper row; profile and first-observed timestamp. | Often synthetic/lazy-created, not explicit signup. | schema; `catalog.py`; `onboarding.py` |
| `accounts` | One registered beta UUID account. | Separate namespace from `users.id`. | schema; `accounts.py` |
| `account_map` | Links legacy UID to account UUID. | Registered dashboard instead maps by email. | schema; Redash **#7** |
| `products` | Product catalog, current price/cost/stock/category/brand. | 17,442 rows have blank brand; historical prices live elsewhere. | query **Q10**; `catalog.py` |
| `cart_items` | Append/delete cart events by user/product/session/time. | Removal deletes events; affinity sees only retained rows. | `carts.py`; `affinity.py` |
| `orders` | Mutable order header and total. | Multi-item totals after 2019-11-22; status is mutable. | `orders.py`; query **Q5** |
| `order_lines` | Per-item/per-callback line for newer orders. | Absent on legacy orders; always use fallback for full history. | schema; log `2019-11-22T15:15:52Z` |
| `payments` | Per money callback/movement gross, fee, net. | Multiple per order; negative gateway refunds; payment_ref added later. | schema; `orders.py`; `payments_webhook.py` |
| `statements` | Append-only monthly publication snapshot. | Only Sep–Nov exist in this warehouse. | query **Q2** |
| `report_rows` | Per-day/product completed report snapshot. | Append-only; select latest `created_at` if reruns occur. | `daily_report.py`; Redash **#5/#8** |
| `report_rows_intraday` | Per-day/product partial snapshot. | Multiple versions per day; select latest for today only. | query **Q11**; Redash **#5/#8** |
| `top_products` | Per-day rank/product/units batch output. | Header-order grain and status 1; not the Redash best-seller source. | `top_sellers.py`; Redash **#2** |

## 6.2 Analytics snapshot (`novamart_analytics`)

| Table/view | Role | Mutation/history behavior | Evidence |
|---|---|---|---|
| `blank_brand_products` | Captured audit of products/orders with missing brand. | Snapshot/audit table; 5,972 rows versus 17,442 currently blank products. | query **Q10**; manifest |
| `category_names` | Current taxonomy code → display group with valid-from. | 135 rows. | query **Q10** |
| `category_name_history` | Prior taxonomy mappings. | Six rows/codes; category dashboard time-travels over both sources. | query **Q10**; Redash **#4** |
| `chargebacks` | Approved chargeback amount by order. | Consumed by `statements_final`. | view `statements_final`; query **Q3** |
| `contactable_users` | Valid opted-in, non-test-email users. | View over `users`; currently zero rows. | view definition; query **Q9** |
| `daily_funnel` | Daily trailing-24h sessions and active-event users. | Appended daily. | `funnel.py` |
| `digest_log` | Digest send time, recipient count, top product. | Appended on enabled runs. | `email_digest.py`; job logs |
| `kpi_daily` | Daily trailing-30d paid-buyer count. | Appended; 45 rows ending 2019-12-31. | query **Q13** |
| `model_registry` | v4 coefficients and training-row audit. | Appended every train; 17 observed versions/runs. | query **Q14** |
| `model_scores` | v4-rescaled v2 candidate scores. | Delete/repopulate when training succeeds. | `model_train.py`; query **Q15** |
| `order_risk` | Per-scoring-event rule features/score. | Appended; order status mutation is separate. | `fraud_score.py` |
| `price_history` | Vendor-fed list price over time. | Appended before product upsert. | `catalog.py` |
| `price_suggestions` | Shadow ±5% price recommendations. | Delete/repopulate nightly; no reader. | `price_suggest.py` |
| `product_affinity` | Legacy co-cart scores. | Delete/repopulate nightly; no current widget reads after rollout. | `affinity.py`; query-log access |
| `product_affinity_v2` | Conversion-weighted co-cart scores, stamped 2.0.1. | Delete/repopulate nightly; current widget source for flag 2.0. | `affinity_v2.py`; `similar.py` |
| `rec_decision_log` | Every served list’s user/base/items/version/source/reason/arm. | Append-only training/diagnostic fact. | `similar.py`; query **Q13** |
| `refunds_unified` | Status and gateway refund-event union. | View; can duplicate an order. | view definition; query **Q7** |
| `reorder_hints` | Advisory velocity/hint snapshot. | Delete/repopulate; no history in table. | `reorder_forecast.py` |
| `statement_corrections` | Audit reason/delta. | Explanatory, not read by final view. | query **Q3**; view definitions |
| `statement_overrides` | Replacement statement values by month. | Read by `statements_corrected`. | view definition; query **Q3** |
| `statements_corrected` | Published statement plus override. | View. | view definition |
| `statements_final` | Corrected statement less chargebacks. | View; declared finance dashboard source. | view definition; Redash **#9** |
| `test_users` | Known numeric QA IDs. | One row: 424242. | query **Q9** |
| `trending_daily` | Per-day top-50 recency-decayed paid products. | Replaces only current day; retains history. | `trending.py`; query **Q13** |

## 6.3 Logs (`novamart_logs`)

`db_queries` contains 3,597,650 raw Postgres-style statement lines; `db_queries_normalized` extracts actor, statement type, and referenced tables; `app_events` contains service JSON events; `job_runs` contains batch JSON events. (Evidence: BigQuery `bq show` metadata for the four objects; view definition `db_queries_normalized`.)

Historical usage confirms the lineage: app reads switched from `product_affinity` to `product_affinity_v2` at 2019-12-06 16:40 UTC; app reads/writes `order_lines` begin 2019-11-22; only the monthly job inserted three statement rows; `model_scores` had job writes and only one observed engineer read, no app reads. (Evidence: query **Q18**; raw DB log line `2019-12-06T16:40:11Z`; raw DB log line `2019-11-22T15:15:52Z`.)

## 6.4 Warehouse limitations

The backfill is ordered table-by-table, exporting Cloud SQL CSV then issuing BigQuery `load --replace`; it does not create a transactionally consistent cross-table snapshot. Views were added separately and reference the backfilled tables. Any future rerun must record a common extraction boundary or consumers can reconcile facts from different moments. (Evidence: commit `2ae79e2`, `novamart/jobs/warehouse_backfill.py`, `warehouse_manifest.json`; view definitions.)

# 7. Experimentation

## 7.1 Recommendation versions

| Version | Production meaning | Data/algorithm | Served? | Evidence |
|---|---|---|---|---|
| 1.0.0 | Legacy affinity | 30d same-session co-cart, recency decay, minimum three pair observations; `-1` means insufficient data. | Served 2019-10-26 to 2019-12-06, then retired. | `affinity.py`; `similar.py`; query **Q13** |
| 2.0.0 serving / 2.0.1 row stamp | Affinity v2 exploit | Co-cart plus any matching paid order conversion weight, same-category boost, extreme-price penalty, season factor. | **Yes**, active flag. | `flags.env`; `affinity_v2.py`; `similar.py` |
| 4.0.0 | Logistic fit on random-arm exposures; rescales v2 scores. | Five actual features: served-list size, base price, base popularity, account age, organic channel. | No, flag-disabled. | `model_train.py`; `flags.env` |

Affinity v2’s conversion feature is not a clean outcome: it checks whether the co-carted user has **any** paid order for the candidate product, with no condition that the order occurred after the cart event or within an attribution window. This can leak prior/future purchase history into the score. (Evidence: commit `2ae79e2`, `novamart/jobs/affinity_v2.py`.)

The README overstates v4’s feature set. The SQL fetches stock and marketing opt-in, but neither enters the feature vector; region affinity and device mix are not selected or computed. (Evidence: commit `2ae79e2`, `README.md` and `novamart/jobs/model_train.py`.)

The v4 label is also weak: an exposure is positive if the user places any later status-1 order, without an attribution window and without requiring purchase of a served item. Candidate scores are then `v2_score*(1+0.1*w)`, where `w` is the single list-size coefficient, so every pair gets the same batch-wide multiplier. (Evidence: commit `2ae79e2`, `novamart/jobs/model_train.py`.)

The warehouse verifies the consequence: the last v4 scores were approximately 0.9755× the v2 scores and changed zero ranks among 948 usable pairs for 449 base products. V4 is therefore a trained registry artifact, not a meaningfully different recommender. (Evidence: queries **Q14** and **Q15**.)

## 7.2 Random arm and logging

User assignment is deterministic: SHA-256 of numeric user ID modulo 20 equals zero, intended as 5%. Observed post-rollout assignment was 4.56% of users and 5.29% of decisions. (Evidence: `similar.py`; query **Q16**.)

The item pool is not uniform over the catalog. SQL orders eligible product IDs, limits to the first 500, then shuffles only those rows; the snapshot pool spans IDs 1000894–1004386 and only 107 of those 500 products had a paid order. It also ignores stock, brand denylists, and category relevance. (Evidence: commit `2ae79e2`, `novamart/routers/similar.py`; query **Q16**.)

Every decision logs intended/effective version, source, fallback reason, and arm in `rec_decision_log`; app logs separately record the served event. This is enough for exposure auditing but not impression/click/cart attribution, because items are stored as a comma-separated string and there is no explicit outcome table keyed to a decision. (Evidence: `similar.py`; schema `rec_decision_log`.)

## 7.3 Does the recommender work?

The defensible conclusion is **not proven**. In a diagnostic seven-day look-forward, served-item purchase was 1.48% for legacy affinity, 1.24% for v2-source decisions, 0.56% for fallback, and 0% for the random arm; any-order rates were 18.99%, 12.08%, 14.57%, and 11.01% respectively. These are not causal lifts because versions cover different dates, exposures repeat per user, eligibility differs by base product, and the random candidate pool is defective. (Evidence: query **Q17**.)

Operational coverage is also limited: after v2 rollout, 52,695 decisions used the v2 source, 207,959 used fallback, and 14,566 used random. Only about one-fifth of non-random decisions got v2 scores, so even a good affinity ranker would affect a minority of traffic. (Evidence: query **Q16**.)

A trustworthy evaluation should randomize among eligible in-stock candidates across the full catalog, log a decision ID plus item-level impressions/clicks/carts/orders, set an attribution window, freeze model/version definitions during analysis, and report user-level confidence intervals and guardrails. This recommendation follows directly from the missing fields and confounding in `rec_decision_log` and the current training label. (Evidence: schema `rec_decision_log`; `similar.py`; `model_train.py`.)

## 7.4 Other “experiments”

Dynamic pricing is explicitly phase-1 shadow output; the service has no read of `price_suggestions`, and catalog/vendor feed writes remain the live price path. (Evidence: commits `894c535` and `cca9b0d`; commit `2ae79e2`, repo-wide references in `novamart/jobs/price_suggest.py` and `novamart/routers/catalog.py`.)

Reorder forecasting and fraud scoring are deterministic heuristics, not learned experiments. Reorder hints invert velocity and omit inventory/lead-time economics; fraud uses price, account age, and recent order count with a hand-set threshold. Neither code path records holdout/control assignment or offline validation metrics. (Evidence: `reorder_forecast.py`; `fraud_score.py`; tables `reorder_hints` and `order_risk`.)

# 8. Glossary

| Term | Novamart-specific meaning | Evidence |
|---|---|---|
| Active customer | Ambiguous label covering nightly trailing buyers, executive daily ordering users, or board-cleaned trailing buyers. Always name the consumer. | `kpi_daily.py`; Redash **#1/#5** |
| Account | UUID identity from the registered-account beta, distinct from legacy numeric user ID. | `accounts`/`account_map`; Redash **#7** |
| As published | Exact append-only monthly row emitted at the original statement run. | `novamart.statements` |
| Board active | Trailing-30d distinct user with status not 0/2/3 after test/email cleanup. | Redash **#1/query #1** |
| Chargeback | Explicit approved amount in `chargebacks`, attributed to original order month by `statements_final`. | view `statements_final` |
| Contactable user | Marketing-opted-in user with syntactically valid non-example email. | view `contactable_users` |
| Daily revenue | Item-level cleaned report revenue, not monthly finance gross/net. | `daily_report.py`; Redash **#5/#8** |
| Effective version | Version actually used; can be `fallback` even when intended version is 2.0.0. | `rec_decision_log`; `similar.py` |
| Excluded SKU | Product `1004856` or `1002544`, omitted from daily/intraday reports and random rec pool but not all dashboards/jobs. | `constants.py`; Redash **#2** |
| Final statement | Corrected published statement less booked chargebacks; not unified-refund adjusted. | view `statements_final` |
| Held order | Fraud-scored order moved from status 1 to status 6. | `fraud_score.py` |
| Item order | `order_lines` item for newer orders, otherwise legacy header order row. | Redash **#2–#4**; commit `92596dc` |
| Legacy user | Numeric `users.id` used by orders and historical commerce. | schemas `users` and `orders` |
| Net revenue | In statements, gross minus processor fee, then optionally chargeback adjustment in final view. | `monthly_statement.py`; view `statements_final` |
| Order | Mutable header whose `price` is the total after same-session line merging. | `orders.py`; commit `5d1300d` |
| Order line | Per-product/per-callback row introduced 2019-11-22. | `order_lines`; DB log `2019-11-22T15:15:52Z` |
| Payment | Per-callback money row with gross/fee/net; can be positive purchase or negative gateway refund. | `payments`; `payments_webhook.py` |
| Provisional month | Month with no published statement; raw status-1 order aggregation only. | `statements`; query **Q4** |
| Random arm | Deterministic ~5% user cohort served shuffled products from the first 500 eligible IDs. | `similar.py`; query **Q16** |
| Refund | Either status-based cancellation/refund or negative payment movement in the unified view; may duplicate an order. | view `refunds_unified`; query **Q7** |
| Restatement | Approved override and/or chargeback adjustment layered over the original statement. | views `statements_corrected/final` |
| Signup | Not a clean fact in this system: `users.created_at` may be lazy first sight; `accounts.created_at` is explicit beta registration. | `catalog.py`; `accounts.py` |
| Snapshot | Append-only report/statement batch result at a `created_at`; consumers may need the latest version. | `report_rows`; `report_rows_intraday`; `statements` |
| Source of truth | Consumer-specific authoritative surface: final statements for current finance, published statements for old decks, exact Redash SQL/report snapshots for dashboards. | Redash **#5/#9**; views `statements_final`; table `statements` |
| Trending | Daily top 50 status-1 products from rolling 30d units with recency decay; recommendation fallback. | `trending.py`; `similar.py` |
| Usable affinity | Pair with score ≥0; score -1 means insufficient observations, not negative preference. | `affinity.py`; `affinity_v2.py` |

# Appendix A. Evidence and reproducibility queries

All queries below are read-only GoogleSQL executed in project `<warehouse-project>` on 2026-08-27. Redash evidence refers to the saved SQL returned by `GET /api/dashboards/<id>`; no dashboard query was run or refreshed.

## Q1 — Warehouse time range and volume

```sql
SELECT MIN(created_at) first_order, MAX(created_at) last_order,
       COUNT(*) orders, COUNT(DISTINCT user_id) buyers
FROM `<warehouse-project>.novamart.orders`;
```

Result: first `2019-09-25 12:30:00Z`, last `2019-12-31 16:51:39Z`, 9,127 rows, 4,112 distinct buyers.

## Q2 — Published, corrected, and final statements

```sql
SELECT 'published' layer, month,gross,fee,net,orders_count,created_at
FROM `<warehouse-project>.novamart.statements`
UNION ALL
SELECT 'corrected',month,gross,fee,net,orders_count,created_at
FROM `<warehouse-project>.novamart_analytics.statements_corrected`
UNION ALL
SELECT 'final',month,gross,fee,net,orders_count,created_at
FROM `<warehouse-project>.novamart_analytics.statements_final`
ORDER BY month,layer;
```

Key result: September unchanged at 2,702.00/78.36/2,623.64; October published 1,230,332.43/35,679.64/1,194,652.79, corrected net 1,194,652.93, final net 1,191,085.36; November unchanged at 1,101,397.01/32,110.92/1,069,286.09.

## Q3 — Restatement components

```sql
SELECT * FROM `<warehouse-project>.novamart_analytics.statement_overrides`;
SELECT * FROM `<warehouse-project>.novamart_analytics.statement_corrections`;
SELECT * FROM `<warehouse-project>.novamart_analytics.chargebacks` ORDER BY order_id;
```

Result: one October override; one zero-delta November audit correction; chargebacks 940.82, 1,891.94, and 734.81, totaling 3,567.57.

## Q4 — Mutable order/payment monthly reconciliation

```sql
WITH om AS (
  SELECT FORMAT_TIMESTAMP('%Y-%m',created_at,'America/New_York') month,
         COUNTIF(status=1) paid_order_rows,
         ROUND(SUM(IF(status=1,price,0)),2) paid_order_gross,
         ROUND(SUM(price),2) all_status_gross
  FROM `<warehouse-project>.novamart.orders` GROUP BY 1
), pm AS (
  SELECT FORMAT_TIMESTAMP('%Y-%m',o.created_at,'America/New_York') month,
         COUNT(*) payment_rows, ROUND(SUM(p.gross),2) payment_gross,
         ROUND(SUM(p.fee),2) payment_fee, ROUND(SUM(p.net),2) payment_net,
         ROUND(SUM(IF(o.status=1,p.gross,0)),2) current_paid_payment_gross
  FROM `<warehouse-project>.novamart.payments` p
  JOIN `<warehouse-project>.novamart.orders` o ON o.id=p.order_id GROUP BY 1
)
SELECT * FROM om FULL JOIN pm USING(month) ORDER BY month;
```

Key result: current paid order gross by month is 0.00 (Sep), 1,206,337.32 (Oct), 1,101,397.01 (Nov), and 552,328.93 (Dec).

## Q5 — Multi-item/payment grain

```sql
WITH lc AS (
  SELECT order_id,COUNT(*) lines,ROUND(SUM(price),2) line_sum
  FROM `<warehouse-project>.novamart.order_lines` GROUP BY order_id
), pc AS (
  SELECT order_id,COUNT(*) payments,ROUND(SUM(gross),2) payment_gross,
         COUNTIF(gross<0 OR net<0) negative_payments
  FROM `<warehouse-project>.novamart.payments` GROUP BY order_id
)
SELECT COUNTIF(lc.lines>1) multi_line_orders, MAX(lc.lines) max_lines,
       COUNTIF(o.price!=lc.line_sum) order_line_mismatches,
       COUNTIF(pc.payments>1) multi_payment_orders, MAX(pc.payments) max_payments
FROM `<warehouse-project>.novamart.orders` o
LEFT JOIN lc ON lc.order_id=o.id LEFT JOIN pc ON pc.order_id=o.id;
```

Result: 173 multi-line orders, maximum six lines, zero line-total mismatches; 176 multi-payment orders, maximum six payments.

## Q6 — Current status population

```sql
SELECT status,COUNT(*) orders,ROUND(SUM(price),2) gross,
       COUNT(DISTINCT user_id) buyers,MIN(created_at),MAX(created_at)
FROM `<warehouse-project>.novamart.orders`
GROUP BY status ORDER BY status;
```

Result: status 1 = 9,033/2,860,063.26; status 2 = 54/13,249.64; status 3 = 28/13,447.47; status 6 = 12/40,213.29.

## Q7 — Unified refund duplication

```sql
WITH r AS (
  SELECT order_id,COUNT(*) n,STRING_AGG(kind,',' ORDER BY kind) kinds,
         ROUND(SUM(amount),2) amount
  FROM `<warehouse-project>.novamart_analytics.refunds_unified`
  GROUP BY order_id
)
SELECT COUNT(*) refunded_orders,COUNTIF(n>1) double_recorded_orders,
       ROUND(SUM(amount),2) unified_sum,
       ROUND(SUM(IF(n>1,amount,0)),2) double_recorded_sum
FROM r;
```

Result: 85 orders, 3 duplicated orders, undeduplicated 28,540.70, duplicated-order contribution 1,843.59. Kind totals: 54 cancellations/13,249.64; 28 order refunds/13,447.47; 9 gateway refunds/1,843.59.

## Q8 — Active-customer definitions

The exact Redash board and executive filters were translated to BigQuery and anchored at `2019-12-31 23:59:59Z`; the nightly comparison used status 1 and a 30-day interval. Result: 1,146 nightly-style; 1,151 board candidates; 0 after board cleanup; 54 executive-daily for Eastern 2019-12-31. Evidence SQL is the saved Redash **#1/query #1** and **#5/query #5**, with table names mapped to BigQuery.

## Q9 — Identity/contactability

```sql
WITH registered_users AS (
  SELECT DISTINCT u.id user_id
  FROM `<warehouse-project>.novamart.accounts` a
  JOIN `<warehouse-project>.novamart.users` u ON u.email=a.email
)
SELECT (SELECT COUNT(*) FROM `<warehouse-project>.novamart.users`) users,
       (SELECT COUNT(*) FROM `<warehouse-project>.novamart.accounts`) accounts,
       (SELECT COUNT(*) FROM `<warehouse-project>.novamart_analytics.contactable_users`) contactable,
       (SELECT COUNT(*) FROM `<warehouse-project>.novamart_analytics.test_users`) test_users,
       (SELECT COUNT(DISTINCT o.user_id)
        FROM `<warehouse-project>.novamart.orders` o
        JOIN registered_users r ON r.user_id=o.user_id WHERE o.status=1) registered_buyers,
       (SELECT ROUND(SUM(o.price),2)
        FROM `<warehouse-project>.novamart.orders` o
        JOIN registered_users r ON r.user_id=o.user_id WHERE o.status=1) registered_revenue;
```

Result: 38,950 users, 30 accounts, zero contactable users, one test user (424242), and 30 registered buyers; registered paid revenue was 18,155.71.

## Q10 — Taxonomy and blank brands

```sql
SELECT
 (SELECT COUNT(*) FROM `<warehouse-project>.novamart_analytics.category_names`) current_rows,
 (SELECT COUNT(*) FROM `<warehouse-project>.novamart_analytics.category_name_history`) history_rows,
 (SELECT COUNT(*) FROM `<warehouse-project>.novamart.products` WHERE brand='') blank_products,
 (SELECT COUNT(*) FROM `<warehouse-project>.novamart_analytics.blank_brand_products`) audited_blank;
```

Result: 135 current mappings, six historical mappings, 17,442 currently blank-brand products, and 5,972 audit rows.

## Q11 — Report snapshot versions

```sql
WITH v AS (
 SELECT report_date,created_at FROM `<warehouse-project>.novamart.report_rows` GROUP BY 1,2
), d AS (SELECT report_date,COUNT(*) n FROM v GROUP BY 1),
iv AS (
 SELECT report_date,created_at FROM `<warehouse-project>.novamart.report_rows_intraday` GROUP BY 1,2
), id AS (SELECT report_date,COUNT(*) n FROM iv GROUP BY 1)
SELECT (SELECT COUNT(*) FROM v) daily_snapshots,
       (SELECT COUNTIF(n>1) FROM d) daily_rerun_days,
       (SELECT COUNT(*) FROM iv) intraday_snapshots,
       (SELECT COUNTIF(n>1) FROM id) intraday_multi_days,
       (SELECT MAX(n) FROM id) intraday_max_versions;
```

Result: 92 daily snapshots, no daily reruns, 47 intraday snapshots, 23 days with multiple intraday versions, maximum two.

## Q12 — Dashboard item population

The Redash item-order CTE was translated to BigQuery and anchored at `2019-12-31 23:59:59Z`. Result over 30 days: 1,917 item rows/577,259.57; status-1 subset 1,898/537,046.28; QA rows 4/39.96; denied brands 33/7,569.56; executive all-status filtered rows 1,880/569,650.05. The matched seven-day best-seller top ten included SKU 1002544 in sixth place at 4,498.52 revenue.

## Q13 — Recommendation decisions and output freshness

```sql
SELECT arm,intended_version,effective_version,rec_source,
       COALESCE(fallback_reason,'') fallback_reason,
       COUNT(*) decisions,COUNT(DISTINCT user_id) users,MIN(ts),MAX(ts)
FROM `<warehouse-project>.novamart_analytics.rec_decision_log`
GROUP BY 1,2,3,4,5 ORDER BY decisions DESC;
```

Key result: pre-v2 legacy affinity 66,444 and fallback 326,186; v2 direct/model 52,695 including cache, v2-era fallback 207,959, random 14,566. Latest output scalar checks found 3,912 affinity-v2 rows (948 usable), 948 model scores, 500 price suggestions, 200 reorder hints, and trending through 2019-12-31.

## Q14 — V4 registry

```sql
SELECT version,trained_at,train_rows,coef_json
FROM `<warehouse-project>.novamart_analytics.model_registry`
ORDER BY trained_at;
```

Result: 17 daily v4 rows from 2019-12-15 through 2019-12-31; training rows grew from 4,197 to 14,411.

## Q15 — V4 versus v2 ranking

```sql
WITH a AS (
 SELECT base_pid,rec_pid,ROW_NUMBER() OVER
   (PARTITION BY base_pid ORDER BY score DESC,rec_pid) r
 FROM `<warehouse-project>.novamart_analytics.product_affinity_v2` WHERE score>=0
), m AS (
 SELECT base_pid,rec_pid,ROW_NUMBER() OVER
   (PARTITION BY base_pid ORDER BY score DESC,rec_pid) r
 FROM `<warehouse-project>.novamart_analytics.model_scores`
)
SELECT COUNT(*) pairs,COUNTIF(a.r!=m.r) rank_mismatches,
       COUNT(DISTINCT a.base_pid) base_products
FROM a JOIN m USING(base_pid,rec_pid);
```

Result: 948 pairs, 449 base products, zero rank mismatches. Score ratios were approximately 0.97545–0.97556 because of numeric rounding.

## Q16 — Post-v2 coverage and random pool

```sql
WITH post AS (
 SELECT * FROM `<warehouse-project>.novamart_analytics.rec_decision_log`
 WHERE ts>='2019-12-06 16:40:00+00'
)
SELECT COUNT(*) decisions,COUNTIF(arm='random') random_decisions,
       COUNT(DISTINCT user_id) users,
       COUNT(DISTINCT IF(arm='random',user_id,NULL)) random_users,
       COUNTIF(rec_source='model') model_decisions,
       COUNTIF(rec_source='fallback') fallback_decisions
FROM post;
```

Result: 275,220 decisions; 14,566 random; 20,649 users/942 random users; 52,695 model-source and 207,959 fallback decisions. A separate exact serving-pool query returned 500 products spanning IDs 1000894–1004386; 107 had a paid order.

## Q17 — Non-causal recommendation diagnostic

For each decision, two `EXISTS` outcomes were calculated over the next seven days: any status-1 order and a status-1 order whose product ID appeared in the comma-separated served list. Aggregated results were fallback 14.57%/0.56%, legacy affinity 18.99%/1.48%, v2 model-source 12.08%/1.24%, and random 11.01%/0.00%. This is diagnostic only for the confounding reasons stated in §7.3.

## Q18 — Historical query consumers

```sql
SELECT rt.dataset_id,rt.table_id,n.user_email,n.statement_type,
       COUNT(*) uses,MIN(n.creation_time) first_at,MAX(n.creation_time) last_at
FROM `<warehouse-project>.novamart_logs.db_queries_normalized` n,
UNNEST(n.referenced_tables) rt
WHERE rt.table_id IN ('orders','order_lines','payments','statements',
 'statements_final','report_rows','report_rows_intraday','kpi_daily',
 'product_affinity','product_affinity_v2','model_scores','trending_daily',
 'rec_decision_log')
GROUP BY 1,2,3,4 ORDER BY rt.table_id,uses DESC;
```

Key result: app affinity reads moved from legacy (392,630 reads ending 2019-12-06) to v2 (264,731 beginning 2019-12-06); app never read `model_scores` in the logged period; three monthly job inserts created the three statement rows.

# Appendix B. Historical change timeline

| Date | Commit | Change and operational meaning |
|---|---|---|
| 2019-09-15 | `2da4141` | Initial service and dashboards. |
| 2019-10-15 | `b676969` | Payment-reference idempotency for callbacks. |
| 2019-10-28 | `8f19718` | Cancellation status endpoint. |
| 2019-11-02 | `a92c96d` | Statement fee changed from monthly-rate arithmetic to collected per-order fee sum. |
| 2019-11-05 | `102c9b4` | Eastern local-day windows fixed across DST fallback. |
| 2019-11-15 | `d87cb3d` | Refund status 3 added. |
| 2019-11-19 | `1233af8` | Daily report 500-row undercount removed. |
| 2019-11-20 | `12e1c68` | Processor fee changed to 2.9% + 0.30 per transaction. |
| 2019-11-22 | `5d1300d` | Same-session callback merging and `order_lines` introduced. |
| 2019-11-27 | `b59f077` | Numeric QA user cleanup added to reports/dashboards. |
| 2019-12-02 | `89666bf` | Conversion-weighted affinity v2 introduced. |
| 2019-12-02 | `cca9b0d` | Dynamic-pricing serving held; shadow job retained. |
| 2019-12-05 | `c49a7bb` | Negative-payment gateway refund path added. |
| 2019-12-05 | `92596dc` | Product reporting moved to item lines with legacy fallback. |
| 2019-12-06 | `f563dea` | Trending window shortened from 60 to 30 days. |
| 2019-12-06 | `df4ed85` | Recommendation version dispatch and random arm added. |
| 2019-12-09 | `cd559d3` | Chargebacks and final statements view added. |
| 2019-12-14 | `a1946ff` | V4 training/shadow scores added. |
| 2019-12-15 | `1169e40` | `jetem` joined `lucente` in report/dashboard denylist. |
| 2019-12-24 | `3eced24` | Revenue widget fixed to select latest intraday snapshot. |
| 2019-12-29 | `1cb8721` | Fraud threshold raised from 0.70 to 0.85; low held orders released. |
| 2020-01-03 | `57ea43a` | Dashboards moved to Redash. |
| 2020-01-04 | `43e54a1` | Scheduling moved from cron to Airflow. |
| 2020-01-05 | `2ae79e2` | Manual Cloud SQL-to-BigQuery backfill added; pinned state used here. |

# Appendix C. Dashboard catalog

| Dashboard / query | Saved definition summary | Primary warning |
|---|---|---|
| Redash **#1 / query #1**, `actives_board` | Board-cleaned trailing-30d users. | Zero under current synthetic-email population. |
| **#2 / #2**, `best_sellers` | Rolling 7d item revenue, top 20. | No status or excluded-SKU filter. |
| **#3 / #3**, `brand_revenue` | Rolling 30d item revenue by brand. | UUID exclusion is dead against numeric user ID; blank/internal brands remain. |
| **#4 / #4**, `category_revenue` | Rolling 30d item revenue with as-of taxonomy. | Unknowns map to `other`; taxonomy history matters. |
| **#5 / #5**, `daily_kpis` | Latest daily/intraday report revenue plus direct daily customer counts. | “Active” is daily/all-status and does not use `kpi_daily`; contactable is zero. |
| **#6 / #6**, `refunds` | Monthly count/sum of unified refund rows by event date. | Double-counts orders represented by both mechanisms; includes cancellations. |
| **#7 / #7**, `registered_conversion` | All-time paid registered buyers/revenue via email identity map. | Not a conversion rate and no time window. |
| **#8 / #8**, `revenue_widget` | Last seven Eastern calendar days from latest snapshots. | Cleaned item/report revenue, not finance statement revenue. |
| **#9 / #9**, `statements_final` | All final finance rows ordered by month. | Only override + chargebacks; no December row and no unified-refund adjustment. |
