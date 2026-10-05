# 1. Summary

**Novamart tribal knowledge — finance, product/customer analytics, recommendations, and batch operations.** Investigation started **2026-10-05 15:10:56 UTC**, run UUID **`551f5d90-d0ce-4315-a2a2-bf226263be52`**. Code was inspected at **`5ae11821806a396aac10115e03863b8c68c1bfcc`**, together with its local history, the supplied BigQuery warehouse, and read-only Redash query definitions. Business-event evidence ends in December 2019; the January 2020 migration code is later than those events. [Run] [History] [Q42]

1. **There is no single interchangeable “revenue.”** Current approved finance reporting uses `novamart_analytics.statements_final`; historical publications use `novamart.statements`. Executive sales dashboards use filtered order/item prices or report snapshots, while payment movements live in `novamart.payments`. Those measures have different grains, filters, dates, and restatement behavior. [C-Statement] [C-Restatement] [Q04] [D2] [D5] [D7] [D9]
2. **October 2019 is the worked reconciliation:** published net **1,194,652.79**, corrected net **1,194,652.93**, final restated net **1,191,085.36**. The bridge is **+0.14** from collected-fee rounding, then **−3,567.57** in booked chargebacks assigned to the original order month. November final net is **1,069,286.09**. No December statement exists in the supplied statement tables. [Q01] [Q10] [Q11]
3. **Customer counts describe different populations.** The snapshot has **38,950 bootstrap user records**, **30 registered accounts**, **4,089 distinct currently paid buyers across all history**, **zero users passing the contactable view**, and **40 users passing the digest’s much weaker recipient rule**. Daily executive actives, nightly 30-day paid actives, and cleaned board actives are different metrics. [Q20] [Q34] [D3] [D7] [C-KPI] [C-Catalog] [C-Digest]
4. **Product reports are deliberately curated, and sometimes historically wrong.** Reporting excludes selected SKUs, brands, or QA users depending on the consumer. Multi-item order merging changed the grain in November; reporting adopted line-item logic later. The daily report historically truncated its input to 500 rows, and a revenue widget added overlapping intraday snapshots until its December 24 fix (`1233af8`, `92596dc`, `33054cd`, `3eced24`). [C-Orders] [C-Daily] [C-Constants] [Changes] [Q28] [Q38]
5. **The active recommendation policy is affinity v2, not the trained v4 model.** The flag is `2.0.0`; its batch rows say `2.0.1`. Available decisions contain no v4 serving. Across the v2-era non-random decisions, **79.78% used fallback**. The v4 job really fits a logistic model, but its published scores merely rescale affinity-v2 scores by one common coefficient-derived factor. This is not evidence of incremental recommendation lift. [C-Flags] [C-Similar] [C-Affinity2] [C-Train] [Q16] [Q33] [Arithmetic]
6. **Successful job execution is not enough to establish correct or live behavior.** Pricing is shadow-only; reorder quantities are hand-fit advisory outputs; the digest initially did nothing despite an enabled-looking flag; affinity v2 crashed on December 3–5; random-arm decision logging was lost on December 17–19. Current Airflow wrappers also differ from retired cron in a material way: only the noon intraday run is declared. [C-Price] [C-Reorder] [C-Digest] [Jobs] [Q31] [C-Cron] [C-IntradayDAG]

**Reading guide:** sections 2–8 give the operating model. Appendices provide the financial reconciliation, all nine dashboard definitions, customer identity rules, ML mechanics, every scheduled job, table inventory, historical changes, and executable read-only query patterns. Citations link to the inspected source or to saved evidence containing the actual SQL and results. [Evidence]

# 2. Why this project

The central engineering problem is **definition and execution drift across code, mutable tables, append-only snapshots, manual finance adjustments, and dashboard SQL**. For example, applying today’s `status = 1` filter to October orders produces net **1,171,353.71**, not either the published or approved restated October statement. Similarly, summing both report tables for the seven dates ending December 31 produces **371,872.10**, versus **139,598.13** under the corrected widget’s snapshot-selection rule. [Q26] [Q01] [Q38]

This document supports three concrete workflows:

- **Finance explanation:** identify publication versus restatement, reconstruct gross/fees/adjustments, and explain why operational sales or cash-movement totals differ. The statement layers, fee changes, refund mechanisms, and snapshot mutability are documented in Appendix A. [C-Restatement] [Q01] [Q04] [Q12] [Q26]
- **Dashboard explanation:** reproduce a consumer’s actual SQL, including its time window, identity namespace, exclusions, current dimension joins, and snapshot freshness. Appendix B covers every query returned by Redash. [Redash] [D1] [D2] [D3] [D4] [D5] [D6] [D7] [D8] [D9]
- **Pipeline and ML changes:** distinguish trained, served, logged, and consumed outputs; identify dependencies and non-idempotent writes; preserve historical definitions when extending jobs. Appendices C–D derive these requirements from the actual implementation and observed failures. [C-Train] [C-Similar] [C-DB] [Jobs] [C-DAGs]

# 3. Business understanding

## Commerce and money

Novamart is implemented as a marketplace backend using FastAPI and Postgres. Product views and carts bootstrap missing users/products; payment callbacks create orders and payment records. Catalog list price is a mutable feed attribute, whereas the callback’s supplied `price` is the amount written to the sale. No currency column appears in the supplied order/payment schema, so monetary amounts below are presented as stored rather than silently assigning a currency. [C-README] [C-Catalog] [C-Carts] [C-Orders] [C-Schema]

The business has four overlapping views of commerce:

| Question | Appropriate evidence | Essential qualification |
|---|---|---|
| What did the business publish for a month? | `novamart.statements` | Append-only job snapshots; preserve the relevant publication timestamp. [C-Statement] [C-Restatement] |
| What is the currently approved restated finance number? | `novamart_analytics.statements_final` / Redash `statements_final` | Applies statement overrides and booked chargebacks; it is not a complete live recomputation of every later refund. [Q04] [D5] |
| What monetary movements were recorded? | `novamart.payments`, by payment time | Includes negative gateway-refund rows; older cancel/refund endpoints only changed order status. [C-Webhook] [C-Orders] [Q14] |
| Which merchandise sold according to the executive report? | Item-order dashboard SQL or latest report snapshots | May hide brands/QA, include held orders, omit test SKUs only in some consumers, and ignore negative payment rows. [C-Daily] [D7] [D8] [D9] |

**“Net” in the statement means gross minus processor fees, then approved restatement adjustments.** The job does not subtract product cost, operating expenses, tax, or shipping. It therefore should not be relabeled profit or contribution margin. [C-Statement] [Q04] [C-Schema]

## Merchandise and customers

Lucente and Jetem suppression is a reporting policy, not deletion of those products or their payments. The two test/internal SKU exclusions are `1004856` and `1002544`; QA user `424242` is tracked separately. Finance’s monthly statement job has none of those product/QA filters. [C-Constants] [C-Daily] [C-Statement] [D8] [D9]

The `users` table largely represents **first-seen shoppers**, not explicit signups. `accounts` is a later UUID registration beta; orders retain numeric shopper IDs. Names, region, signup channel, device, age band, opt-in, product cost, and stock are deterministically synthesized from IDs in `onboarding.py`, rather than demonstrated observations from completed forms or inventory accounting. Analytical segmentation on those fields must retain that provenance. [C-Onboarding] [C-Catalog] [C-Accounts]

# 4. Metrics

## Metric selection card

| Metric / consumer | Actual definition | Do not confuse it with |
|---|---|---|
| Monthly statement gross | Sum of **order-header `price`**, order-created local month, `status = 1` at job execution. [C-Statement] | All payments, all line events in that month, or curated dashboard revenue. |
| Monthly statement fee / net | Sum of joined `payments.fee` for those orders; `net = gross − fee`. Final view then applies override/chargeback logic. [C-Statement] [Q04] | A flat percentage of monthly gross or profit. |
| Refunds dashboard | Count and sum `refunds_unified` events by Eastern **refund/status-update month**. [D1] [Q04] | Distinct refunded orders or automatically reconciled cash refunds. |
| Daily executive “orders” / revenue | Sum latest snapshot `units` / `revenue`; prior 13 closed local dates plus today’s latest intraday batch. [D7] | Header counts or the nightly active-customer table. |
| Revenue widget | Latest closed snapshots for prior six local dates, plus latest intraday snapshot for today. [D2] | A rolling 168-hour item query or the sum of all snapshot versions. |
| Best sellers | Item lines plus legacy-header fallback; last 7×24 hours; QA and brand filters; **no status filter**; top 20 by revenue. [D9] | Nightly `top_products`, which ranks yesterday’s paid headers by units. [C-Top] |
| Brand revenue | Same item grain, rolling 30 days, QA numeric/string exclusions, denied brands excluded, all statuses. [D8] | The monthly paid-header implementation in `routers/reports.py`. [C-Reports] |
| Category revenue | Same item grain and 30-day filters; one date-effective display-group mapping per item. [D6] | Splitting a category string or joining all mapping versions. |
| Nightly active customers | Distinct paid (`status = 1`) header buyers in trailing 30 days at job time; no QA/email/brand filtering. [C-KPI] | Daily actives or board actives. |
| Executive active customers | Distinct ordering users per Eastern date; no status restriction; excludes QA `424242` and header-product denied brands. [D7] | The sales snapshot’s eligible population or trailing-30-day unique buyers. |
| Board active customers | Trailing 30-day distinct users with status not in `[0,2,3]`; exclude `test_users` and email heuristics; no brand filter. [D3] | Strictly paid buyers: status 6 remains eligible before user filtering. |
| Registered conversion | Paid buyers and header revenue across **all history** for numeric users matched to account emails; no denominator. [D4] | A signup-to-purchase rate or post-registration-only revenue. |
| Contactable customers | Opted-in users with syntactically valid, non-placeholder-domain email; executive KPI counts the ordering subset. [Q04] [D7] | Digest recipients, who only need an email not ending in `@example.com`. [C-Digest] |
| Funnel sessions / users | Cart and order activity in trailing one day, sessionized by user with a strict inactivity gap over 120 minutes. [C-Funnel] | Product-view traffic, checkout conversion, or stored cart-session IDs. |

**Verified examples, not refreshed Redash results:** anchored to **2019-12-31 23:59:59 UTC**, the nightly active definition yields **1,146**, the board definition **0**, and the executive December 31 daily customer count **54**. The last stored nightly run, at **11:15 UTC**, contains **1,152**. These differ in clock, window, and filters; the data also contains later-mutated state. [Q37] [Q36] [Q40]

Under the latest December 31 report snapshots, the executive KPI is **60 units labeled “orders,” revenue 18,202.09, 54 active customers, and 0 contactable customers**. The corrected seven-calendar-date widget is **139,598.13**. These are useful reproduction fixtures for the exact definitions, not claims about a live 2026 storefront. [Q46] [Q38] [Q42]

# 5. System

## End-to-end flow

```text
Views / carts / catalog feed / payment callbacks
                    |
             FastAPI + Postgres
                    |
     users, products, carts, orders, order_lines, payments
          /                    |                      \
 sales/report jobs      recommendation jobs       fraud scoring
          |                    |                      |
 report snapshots       affinity / trending       order status 6
 statements             model_scores              + order_risk
          |                    |
 finance overlays       similar-products API
          |                    |
 Redash SQL              decision + app logs

One-shot warehouse export: serving tables -> BigQuery table copies
Historical log exports: db_queries / app_events / job_runs
```

The arrows above describe implemented reads/writes, not a declaration of Airflow dependency edges. Current DAG wrappers are independent single-task Bash jobs; the warehouse backfill is manual. [C-App] [C-Orders] [C-Daily] [C-Statement] [C-Affinity2] [C-Trending] [C-Train] [C-Fraud] [C-Similar] [C-DAGs] [C-Warehouse] [Inventory]

**Mounted routes matter.** At the pinned commit, `app.py` mounts catalog, carts, orders, similar, and gateway refunds. The `accounts`, `users`, and `reports` router files still exist but are not mounted. History shows users/reports were removed from app wiring by `f1217a8`, and accounts by `c49a7bb`. Treat their files as historical/dormant implementations, not proof those endpoints remain reachable. [C-App] [RouteHistory]

**Operational boundaries:** app SQL and job SQL are logged before execution; jobs use `autocommit=True`. A SQL log line proves an attempted statement, not successful commit. A job that deletes then inserts rows can expose an empty or partial result, and a retry of an append-only job can add a second version. [C-DB] [C-Log] [C-Daily] [C-Affinity2]

**Migration boundaries:** serving SQL uses Postgres `public`/`analytics`; the supplied warehouse uses datasets **`novamart` / `novamart_analytics`**. At `5ae1182`, both `docs/data-access.md` and the backfill dataset mapping still say/use `analytics`, which disagrees with the actual warehouse inventory. The backfill wrapper also omits CLI arguments that the underlying job requires. [C-Access] [C-Warehouse] [C-WarehouseDAG] [Inventory]

# 6. Data

## Evidence scope and source precedence

| Surface | Observed scope | What it establishes |
|---|---|---|
| Repository | Pinned `5ae1182`; local history from the September initial import through the January warehouse job. [Run] [History] | Implementation and definition changes, not automatic proof of deployment time. |
| App warehouse | 12 tables; 9,127 order headers, 2,284 line rows, 9,361 payment rows, 81,018 products, 38,950 users. [Inventory] | Current supplied state, including later mutations. |
| Analytics warehouse | 20 tables and 4 views. [Inventory] | Batch outputs, manual adjustments, and actual view behavior. |
| Logs | 3,597,650 DB-query rows, 1,570,017 app-event rows, 978 job-log rows; latest business log timestamp December 31, 2019. [Q42] | Observed attempted SQL, emitted app events, job outcomes, and historical parameter values. |
| Redash | Nine saved queries; every `latest_query_data_id` is null. Dashboard list succeeds, individual dashboard-detail GETs return HTTP 500. [Redash] [RedashDashboards] [DashboardError] | Authoritative saved query definitions, but no cached displayed-value evidence in this run. |

When sources disagree, use **the actual consumer query** to explain its metric, **the approved finance view** for restated statements, **job/app logs** to establish observed execution, and **the pinned implementation plus history** to explain mechanisms. Preserve contradictions explicitly rather than harmonizing them into a fictional common definition. The README’s trending window, advertised model features, and several documentation lineage claims demonstrate why this is necessary. [D5] [D6] [D7] [C-README] [C-Trending] [C-Train] [History]

## Important data-quality facts

- **Historical event time and physical mutation time are mixed.** Six category-history rows have `valid_from = 2026-08-13`, despite a December 12, 2019 logged backfill using `CURRENT_DATE`. Five released paid orders have `updated_at` in August 2026, despite a December 29, 2019 logged `NOW()` update. The blank-brand snapshot’s `captured_at` is also in August 2026. The documents and event logs do not justify silently rewriting these dates. [Q22] [Q23] [Q39] [Q40]
- **Product dimensions are mutable.** Revenue dashboards join current product brands/categories. Date-effective category-name mapping does not restore the product’s category as it was at purchase. Price history covers only recorded feed updates: **1,400 rows for 241 products**, starting November 18, rather than every historical catalog price. [C-Catalog] [D6] [D8] [Q41]
- **Current headers are not historical snapshots.** Status changes explain why September currently has no paid orders although a September statement exists, and why today’s October paid gross is lower than the October publication. [Q08] [Q01] [C-Orders]
- **The logged SQL history contains failed-looking exploratory queries too**, such as references to `orders.total_amount` and decision-log `source`/`reason`, which do not match the actual schemas. Do not infer columns from attempted SQL without checking metadata. [Q06] [Inventory] [C-DB]

# 7. Experimentation

## What can be concluded now

| System | Evidence-based conclusion |
|---|---|
| Affinity v1/v2 | Implemented heuristic ranking with a minimum-pair eligibility gate; v2 is actively used, but fallback dominates observed non-random traffic. This establishes operation and limited coverage, not causal lift. [C-Affinity] [C-Affinity2] [C-Similar] [Q16] |
| Trained recommendation v4 | Seventeen training records exist, but no observed v4 decisions. Latest scores match a uniform positive rescaling of v2 for all 948 eligible pairs; ranking is preserved apart from rounding/ties. [Q18] [Q16] [Q33] [C-Train] |
| Random arm | Stable user-hash assignment targets 5% of users, but recommendations are sampled only from the first 500 eligible product IDs. It is not uniform exploration of all 81,018 products. [C-Similar] [Inventory] |
| Dynamic pricing | Nightly output exists, but no serving read is present in code or captured SQL templates. Live order prices come from callbacks; catalog prices come from the feed. [C-Price] [C-Catalog] [C-Orders] [Q06] |
| Reorder forecasting | An inverse-velocity hand-fit heuristic, not a learned demand forecast; larger hints mechanically go to lower velocity. [C-Reorder] [Q25] |
| Fraud scoring | A deterministic price/rule score that really changes order status; no labeled fraud accuracy, precision/recall, or causal benefit is demonstrated by the job. [C-Fraud] [Jobs] |
| Digest | Observed `digest_sent` events and table inserts establish that the batch ran; the code contains no email transport call, so those events do not prove delivery. [C-Digest] [Jobs] |

## Recommended evaluation contract

For a future recommendation experiment, preserve **assignment, intended version, effective policy, source, fallback reason, candidate/served IDs, score-batch timestamp, and exposure/request identity** separately. Today’s random arm logs the intended model version as its effective version, v1 fallback also retains `1.0.0` (see `f1217a8`), and the decision table lacks session/request identity and batch version. Source-aware classification is therefore essential. [C-Similar] [Changes] [Inventory] [Q16]

Use a bounded, item-linked outcome window with mature observations; freeze features as of exposure; split evaluation in time and by user; distinguish policy-level intent-to-treat results from conditional model-served slices. These are recommendations prompted by current training’s **any-later-paid-order label**, repeated user exposures, present-day product features, unbounded popularity, missing random-arm decisions, and lack of validation metrics in the registry/job. No uplift estimate is claimed here. [C-Train] [Q18] [Q31] [Q32]

# 8. Glossary

| Term | Meaning in this estate |
|---|---|
| Order header | `orders` row; after session merging, its `price` can total multiple callback items while `product_id` remains the initial product. [C-Orders] |
| Item / unit | One `order_lines` row, or one legacy `orders` row only when that order has no lines; no separate quantity field is used by these dashboards. [D9] [Inventory] |
| Payment reference | Callback deduplication key; initially only on headers, later also uniquely indexed on lines and non-null payment references (`b676969`, `5d1300d`). [C-Orders] [Changes] |
| Paid / completed | Operational shorthand for `status = 1`; it does not guarantee there was no later gateway refund. [C-Orders] [C-Webhook] [Q13] |
| Cancelled / refunded / held | Current statuses 2 / 3 / 6; old code called cancellation 4 (`8f19718`). [C-Constants] [C-Fraud] [Changes] |
| Published statement | Historical snapshot in `novamart.statements`. [C-Restatement] |
| Corrected statement | Publication with month-level `statement_overrides` applied. [Q04] |
| Final statement | Corrected statement less booked chargebacks in the original order month. [Q04] |
| Contactable | Passes the opt-in, syntax, and placeholder-domain rules in `contactable_users`; not verified deliverability. [Q04] |
| Registered | UUID account associated with a numeric shopper; the dashboard currently resolves this through email. [C-Accounts] [D4] |
| Active | Consumer-specific: nightly paid 30-day buyers, daily ordering users, cleaned board buyers, or funnel activity users. [C-KPI] [D7] [D3] [C-Funnel] |
| Sentinel `−1` | Too few co-cart pairs to trust; not a negative preference. Serving must exclude negative scores. [C-Affinity] [C-Affinity2] |
| Intended / effective version | Configured model label versus recorded runtime label; interpret alongside `rec_source` and `arm`. [C-Similar] [Q16] |
| Fallback | v1: live seven-day paid-header best sellers; v2-era: latest available `trending_daily` ranks. [Changes] [C-Similar] |
| Snapshot version | A report batch identified by `created_at` within a business date; appending versions does not make them additive. [C-Daily] [C-Intraday] [D2] |
| Business day | America/New_York calendar date, whose UTC boundaries can span 23 or 25 hours. [C-Time] |
| Shadow output | A batch-produced suggestion table not connected to the inspected live serving path. [C-Price] [Q06] |

# Appendix A. Finance: answering “what was revenue, and why?”

## A1. Order and payment lifecycle

1. A view/cart/order can call the bootstrap path and create missing numeric user/product records. First-seen products can have blank metadata; first-seen users get `user<uid>@example.com`. Cart adds insert event-like rows; cart removal deletes matching rows, so `cart_items` is not guaranteed to be an immutable activity ledger. [C-Catalog] [C-Carts]
2. `/orders` receives `ts`, `uid`, `pid`, `price`, `ref`, and `session`; fee is `round(price × 0.029 + 0.30, 2)` in the pinned code. The supplied price, not the current catalog price or a suggestion, drives the order and payment. [C-Orders] [C-Constants]
3. Current callback handling takes transaction-level advisory locks on session and reference, finds the reference in both headers and lines, and inserts a missing payment if necessary. A replay of a status-0 header can restore it to status 1. The code does not have a universal “always create one order per callback” rule. [C-Orders]
4. A new reference can append to the same user/session’s recent order if a line is within 15 minutes and the order is not cancelled/refunded. It adds line price to header total, inserts a new line and payment, and leaves the header’s original product/time in place. A new header is inserted at status 0, then paid and set to 1. The append path can also move a held header back to 1 because its exclusion list is only statuses 2 and 3. [C-Orders]
5. Cancellation changes the header to 2, except a refunded order cannot be cancelled. Legacy refund changes a paid order to 3. Neither endpoint inserts a reversing payment. Gateway refund instead inserts `gross = net = −amount`, `fee = 0`, with no status change, reference-based deduplication, or amount/remaining-balance validation visible in that handler. [C-Orders] [C-Webhook]

**Observed grain:** 9,127 headers include 2,059 with lines and 173 with more than one line. Lines plus the legacy fallback yield **9,352 item rows**. All line-bearing order totals equal their line sums in this snapshot. Payments contain those positive item movements plus nine negative refund rows, giving 9,361 rows. Aggregate payments per order before joining to header revenue; otherwise multiple payments repeat header `price`. [Q15] [Inventory] [Q13] [Q26]

**Idempotency history:** before `b676969` on October 15, duplicate callbacks could create duplicate headers/payments. Reconcile still finds **130 duplicated references across 285 headers**, or **155 headers beyond one per reference**. Its job only warns; it does not repair or exclude them from statements. Their latest order timestamp precedes the idempotency fix. Do not silently deduplicate an approved statement to produce a new finance number. [Q27] [C-Reconcile] [History] [C-Statement]

## A2. Monthly statement calculation and authoritative layers

The monthly job selects the previous **Eastern calendar month**, using independently computed local-midnight boundaries converted to UTC. It sums paid header prices, counts headers, then separately sums all payment fees joined to those paid orders by **order-created month**. It appends `month, gross, fee, net, orders_count, created_at`. The fee query has no payment-created-date restriction. [C-Statement] [C-Time]

| Month | Published gross | Published fee | Published net | Corrected net | Final gross | Final net | Published header count |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2019-09 | 2,702.00 | 78.36 | 2,623.64 | 2,623.64 | 2,702.00 | 2,623.64 | 12 |
| 2019-10 | 1,230,332.43 | 35,679.64 | 1,194,652.79 | 1,194,652.93 | 1,226,764.86 | 1,191,085.36 | 3,765 |
| 2019-11 | 1,101,397.01 | 32,110.92 | 1,069,286.09 | 1,069,286.09 | 1,101,397.01 | 1,069,286.09 | 3,582 |

Every figure in this table is from the three statement surfaces; September–November are the only available months. Final October fee remains **35,679.50** and its count remains **3,765**: the final view subtracts chargebacks from gross/net, not fees/counts. [Q01] [Q04]

### October bridge

```text
Original order gross                           1,230,332.43
Original fee: rounded monthly gross × 2.9%         35,679.64
Original published net                         1,194,652.79

Replace fee with sum of collected fees: +0.14
Corrected fee                                     35,679.50
Corrected net                                  1,194,652.93

Subtract booked October-order chargebacks          3,567.57
Final restated gross                           1,226,764.86
Final restated net                             1,191,085.36
```

The November 2 override records the corrected October values while preserving the original publication timestamp. The December 9 SQL backfill inserted three chargebacks, with `reported_at` December 1, and the final view assigns them using the original orders’ Eastern month. Thus publication time, chargeback reporting time, booking-operation time, and revenue attribution month are distinct (`a92c96d`, `cd559d3`). [Q10] [Q11] [Q39] [Q04] [Changes]

**Policy:** reproduce an old deck from its original `statements` snapshot. Use `statements_final` for the current approved figure. `statements_corrected` is the intermediate fee/override layer. `statement_corrections` is an audit explanation table, not a second adjustment to add to the view. [C-Restatement] [Q04]

### Why recomputing old orders gives another answer

| Current-state paid-order recomputation | Headers | Gross | Collected fee | Gross minus fee |
|---|---:|---:|---:|---:|
| October | 3,695 | 1,206,337.32 | 34,983.61 | 1,171,353.71 |
| November | 3,582 | 1,101,397.01 | 32,110.92 | 1,069,286.09 |
| December | 1,756 | 552,328.93 | 16,600.26 | 535,728.67 |

These are **current supplied-state recomputations**, not replacement publications. October has 70 headers now cancelled/refunded, with prices totaling **23,995.11**, explaining the difference from published gross. All 12 September headers are now status 2 or 3. The December value is provisional under this formula because there is no December publication; 12 December held headers worth **40,213.29** are excluded by `status = 1`. [Q26] [Q08] [Q01]

The final statement view does **not** read negative payment gross/net or the unified refund view. October’s currently paid orders have an additional **1,843.59** in negative gateway payments, so their payment net is **1,169,510.12**, versus header-gross-minus-fees **1,171,353.71**. That is a third, explicitly different measure. A future reconciliation should expose this bridge rather than assuming the existing final view is a complete cash ledger. [Q26] [Q13] [Q04]

## A3. Processor fees: the rounding and deployment traps

- Before November 2, statement fee was `round(month_gross × 0.029, 2)`, while each payment fee was rounded individually. Commit `a92c96d` changed statement fee to the collected sum. October’s **0.14** discrepancy is real; September also logged collected fee **78.37** versus publication **78.36**, but no September override is present. [Changes] [Q30] [Q10]
- Commit `12e1c68`, November 20, added **0.30 per transaction**. Actual November 20 payments are mixed: **57 of 121** match percentage-plus-flat; all **118** November 21 payments match it. The later monthly expectation hard-codes the change to midnight Eastern, which does not exactly model the observed within-day rollout. [C-Statement] [Q47] [History]
- The December 1 warning for November compares the obsolete expectation **31,940.51** with collected **32,110.92**, delta **−170.41**. The published November statement already used collected fees. The December 2 audit correction row is **0.00**, not a further 170.41 adjustment (`4a58d17`). [Q30] [Q09] [Q01] [Changes]
- Current expected-fee logic still rounds once per **header**, whereas merged orders have multiple per-transaction flat fees and per-payment rounding. Replaying that expectation yields November **32,120.54** against actual **32,110.92**, and December **16,544.33** against actual **16,600.26**. Use stored collected fees to explain the published calculation; use transaction grain and actual fee-era timing for diagnostics. [Q49] [C-Orders] [C-Statement]

## A4. Refunds, cancellations, chargebacks

`refunds_unified` is a `UNION ALL` of: (a) current status-2/3 headers, amount `orders.price`, event time `orders.updated_at`; and (b) negative gross or net payments, amount `ABS(gross)` if gross is negative else `ABS(net)`, event time `payments.created_at`. Redash groups that event time into Eastern months. It does not deduplicate the two mechanisms or impose one refund per order. [Q04] [Q39] [D1]

| Event month | Kind | Rows counted | Amount |
|---|---|---:|---:|
| November | Order cancelled | 24 | 6,511.32 |
| November | Order refunded | 8 | 3,180.45 |
| **November total** | | **32** | **9,691.77** |
| December | Order cancelled | 30 | 6,738.32 |
| December | Order refunded | 20 | 10,267.02 |
| December | Gateway refund | 9 | 1,843.59 |
| **December total** | | **59** | **18,848.93** |

The nine gateway rows belong to **three still-paid orders**, so no cross-mechanism overlap is observed in this snapshot. Nevertheless, the view’s definition permits overlap and counts repeated/partial gateway events individually. Cancellations included by this dashboard are not proof of cash returned, and the handler’s lack of a refund event key means the nine rows alone cannot prove whether repeated equal refunds are legitimate or replays. [Q12] [Q13] [Arithmetic] [C-Webhook] [C-Orders]

Chargebacks are separate booked adjustments in `chargebacks`, not rows in `refunds_unified`; their statement attribution uses the original order month, unlike the refunds dashboard. Do not sum the refund dashboard and final statement deductions as though they shared a period and event definition. [Q04] [Q11] [D1]

## A5. Daily reporting history and known discontinuities

| Change | Before / after | Historical consequence and evidence |
|---|---|---|
| October 8, `83fb3ed` | Excluded SKUs changed from none to `1004856`, `1002544`. | Earlier snapshots still include them; constants are not a historical filter ledger. [History] [C-Constants] |
| October 25, `ba1fbfa` | Add Lucente to report denylist. | Partnerships suppression affects report revenue, not monthly statement revenue. [Changes] [C-Statement] |
| October 28, `8f19718`; November 15, `d87cb3d`; November 18, `11c0a42` | Cancellation constant 4→2; introduce refund status 3; report exclusions `[0]`→`[0,2,3]`. | Endpoint status changes and report eligibility changed on different dates. [Changes] [History] |
| November 5, `102c9b4` | Fixed 24-hour UTC day→two independently converted Eastern midnights. | November 3 was a 25-hour day. Eight orders worth **2,985.99** in `2019-11-04 04:00–05:00 UTC` were outside the old window. [Changes] [Q29] [Arithmetic] |
| November 19, `1233af8` | `fetchmany(500)`→`fetchall()`. | SQL had no `LIMIT`; the truncation was in Python. `REPORT_SCAN_CAP=500` remains as unused historical configuration. [Changes] [C-Daily] [C-Constants] |
| November 22, `5d1300d`; December 5, `92596dc` | Merge callbacks into multi-item orders; later change daily/best-seller/brand reporting to lines plus legacy fallback. | Between those dates header-product counts underdescribe item sales and misattribute appended-item revenue. [History] [C-Orders] [Changes] |
| November 27, `b59f077` | Daily report anti-joins `test_users`; dashboards hard-code QA 424242. | Table-based and hard-coded exclusions can diverge as the test-user table changes. [C-Daily] [D7] [D9] [Q06] |
| December 8, `a2e0013` | Add intraday snapshots; daily KPI switches from direct orders to snapshot sales plus direct-order customer counts. | Its “orders” measure becomes summed report units, and its revenue/customer populations can differ. [History] [D7] |
| December 15, `1169e40` | Add Jetem to report denylist; add both-brand joins/filters to executive queries. | Lucente dashboard suppression should not be backdated automatically to its earlier report-job suppression. [Changes] [D7] [D8] [D9] |
| December 19/24, `686a5d6` / `3eced24` | Introduce then fix seven-day revenue widget. | Prior closed days must use closed snapshots, today intraday, and only the newest version of each date. [History] [Changes] [D2] |

**Confirmed cap example:** November 17 has **735** order headers. Under the relevant SKU/Lucente/status exclusions, current data yields **704 units / 223,853.03**; the stored report contains **487 units / 148,857.07**, while its November 18 log says **500 scanned**. The difference is **217 units / 74,995.96**. November 16, with 401 scanned rows, matches **383 units / 123,501.36** after exclusions. No second repaired version of those dates appears in `report_rows`. [Q28] [Q24] [Q05] [RollupSamples] [Arithmetic]

**Confirmed DST example:** November 3’s stored report is **123 units / 35,429.68**. The current matching-filter full-day reconstruction is **131 / 38,415.67**; the eight last-hour rows account for the exact **2,985.99** difference. Do not attribute this particular dip to customer demand. [Q28] [Q29] [RollupSamples] [Arithmetic]

## A6. Finance answer procedure

1. State **month, business timezone, metric, and publication/restatement basis**. For an old deck select its `statements.created_at`; for current approved reporting select `statements_final`. [C-Time] [C-Restatement]
2. Show publication → override → chargeback bridge. Keep statement-correction audit deltas separate and verify whether they actually feed the view. [Q04] [Q09] [Q10] [Q11]
3. If reconciling operations, preaggregate payments to header grain; compare current header gross, recorded payment gross/net, status exclusions, and curated item/report totals separately. Preserve original-order versus payment/refund event month. [Q26] [Q14] [C-Statement] [D1]
4. For historical mismatches inspect code-era filters, snapshot timestamps, known cap/DST defects, line adoption, and subsequent state/dimension changes. The existing approved views do not automatically recompute all those effects. [Q04] [Q08] [Changes] [C-Daily]
5. For a month without a publication, label a query result **provisional current-state reconstruction**; do not fabricate an approved statement. December illustrates this distinction. [Q01] [Q26]

# Appendix B. Product, dashboard, and customer analytics

## B1. Complete Redash query dictionary

The IDs below are **query IDs**, not dashboard IDs. Redash’s list gives different dashboard IDs for some names, and no cached results were available. Saved SQL is preserved locally and the live query links are listed in the evidence index. All following descriptions are of the retrieved saved definitions. [Redash] [RedashDashboards]

### Query 9 — `best_sellers`

- Forms `item_orders` from every line joined to its parent user, plus headers having **no lines**. Uses the line timestamp for new items and header timestamp for legacy sales. [D9]
- Selects the rolling last seven days, excludes numeric user `424242`, and excludes current product brands `lucente`/`jetem`. It does **not** filter status, test SKU IDs, internal-brand products generally, payment refunds, or contactability. Blank brand strings survive the denylist. [D9]
- Returns product ID, `COUNT(*) AS units`, and `SUM(price) AS revenue`; orders by revenue descending, limit 20, with no explicit tie-breaker. Adding `status = 1` or sorting by units changes the metric. [D9]
- At the documented December 31 UTC anchor, product **1005116** leads with **6 units / 5,889.81**. Product **1004767** has more units (**20**) but less revenue (**4,788.30**). Test/internal SKU **1002544** is included with **10 / 4,498.52** because this query lacks the report-job SKU exclusions. [Q43] [C-Constants]

**Different product named “top sellers”:** `top_sellers.py` reads paid **headers** for the previous Eastern calendar date, ranks count descending/product ID ascending, and appends at most 50 rows to `top_products`. It does not use lines, denylisted brands, QA filters, or the rolling-seven-day revenue ranking. No retrieved Redash query reads `top_products`. [C-Top] [Redash]

### Query 8 — `brand_revenue`

The grain is the same line-plus-legacy union; the window is rolling 30 days. It excludes brands Lucente/Jetem and string forms of QA identities `424242` and `cc27b436-d6f9-4e84-adaf-e716025dd369`. However, `orders.user_id` is numeric: the UUID string exclusion is not an account-map join and cannot itself match numeric order IDs. The account-created log links that UUID to the QA identity; the numeric exclusion does the effective work for the supplied schema. [D8] [Inventory] [Q30]

At the December 31 UTC anchor, brand revenue totals **569,650.05 over 1,880 items**: Apple **236,606.73**, Samsung **128,113.51**, blank brand **17,585.39**, and `internal` **7,624.89**, among 263 returned brand groups. The presence of blank and internal groups is consistent with the actual filters. [Q44] [Arithmetic]

The dormant `/reports/brands?month=YYYY-MM` implementation is materially different: Eastern calendar month, paid **headers**, current header-product brand, SKU and brand denylist, no QA exclusion, and blank brand renamed `unbranded`. It remains header-grained at the pin and is not mounted in `app.py`. [C-Reports] [C-App]

### Query 6 — `category_revenue`

The current query uses item grain, a 30-day rolling window, QA exclusion, and both-brand denylist. It unions `category_names` with `category_name_history`, then chooses **one mapping** satisfying `code = current product.category` and `valid_from <= item.created_at::date`, ordered by latest `valid_from`, then history-source priority. Missing mappings become `other`. The unqualified Postgres `::date` conversion depends on the session’s date/time behavior; the query does not explicitly specify Eastern time for this mapping boundary. [D6]

The initial November 30 category query used order headers. **Line-grain adoption for category revenue occurred in `33054cd` on December 12**, not `92596dc` on December 5: that earlier commit changed only daily reporting, best sellers, and brand revenue. `docs/dashboard_notes.md` incorrectly attributes category’s line fallback to the earlier commit. [Changes] [History] [C-DashboardNotes]

The intended taxonomy revision maps `construction.tools.light%` to `lighting` and `electronics.audio%` to `entertainment`, while retaining old mappings. A simple prefix split cannot reproduce that contract; joining all mapping versions can multiply revenue. In the supplied data, all six history records instead have **2026-08-13** effective dates, so they do **not** apply to 2019 item dates. That discrepancy is observable and is consistent with the logged backfill’s use of `CURRENT_DATE`; it is not evidence that 2019 orders should be retroactively remapped in this investigation. [Q22] [Q39] [D6]

The read-only reproduction at the December 31 UTC anchor, using UTC dates for the unqualified mapping-date cast, returns:

| Display group | Units | Revenue |
|---|---:|---:|
| electronics | 1,098 | 437,887.95 |
| other | 525 | 93,558.92 |
| appliances | 165 | 30,208.94 |
| construction | 22 | 3,713.01 |
| apparel | 55 | 3,663.34 |
| kids | 15 | 617.89 |
| **Total** | **1,880** | **569,650.05** |

These figures come from the saved translated SELECT and reconcile to the brand total under the same item/filter window. A reproduction against Postgres should explicitly confirm its session timezone before claiming equivalence at mapping-date boundaries. [Q45] [Q44] [Arithmetic] [D6]

### Query 7 — `daily_kpis`

Sales come from latest `report_rows` versions for **today−13 through yesterday**, plus today’s latest `report_rows_intraday`. Each branch joins current products and applies the two-brand denylist again. Customer counts come independently from headers, grouped by Eastern date, with no status filter, QA 424242 excluded, and the **header product’s** brand filter. Contactables are counted by joining `contactable_users`. [D7]

Consequences: the “orders” column counts item units from report output; customers can include users whose cancelled orders do not contribute report revenue; multi-brand merged headers can have different customer inclusion from their item sales; current brand edits can alter a historical dashboard read. Dates without report rows do not appear as explicit zero days because the final result is driven by report days. [D7] [C-Daily] [C-Orders]

Before December 8 this query directly counted headers and summed prices, with `created_at::date` and a rolling 14-day lower bound. December 8 changed both the sales source and the explicit local-calendar presentation. December 4 had added contactables; December 15 added the brand-filter joins. These are definition discontinuities, not automatically changes in commercial performance (`e10cb0c`, `a2e0013`, `1169e40`). [Changes] [History]

### Query 2 — `revenue_widget`

This is **seven Eastern calendar dates including today**, not the best-seller query’s rolling 168 hours. It chooses one maximum `created_at` per prior closed date from `report_rows`, and only today’s maximum intraday version. It does not itself join products for a new denylist pass; it inherits the filters baked into each snapshot. A later change to historical product brands can therefore affect `daily_kpis` differently from the widget. [D2] [D7]

For December 25–31, the corrected selection gives **139,598.13 / 496 units**; naively summing both tables gives **371,872.10 / 1,340 units**. December 31 has two intraday versions whose sum is **36,404.18**, while its newest version alone is **18,202.09**. This is snapshot duplication, not two independent sets of sales. [Q38] [RollupSamples] [Q46]

### Query 5 — `statements_final`

It is simply `SELECT * FROM analytics.statements_final ORDER BY month`. There is no additional Redash accounting calculation. Explain it using Appendix A’s approved override/chargeback chain, and use the BQ dataset-qualified counterpart when querying the warehouse. The view itself does not choose a latest statement version per month if future reruns append duplicates. [D5] [Q04] [C-Statement]

### Query 1 — `refunds`

It groups `refunds_unified.at` into Eastern months, counts rows, and rounds summed amounts to two decimals. Its November/December totals are the **32 / 9,691.77** and **59 / 18,848.93** shown in Appendix A; it is an event-mix dashboard, not distinct refunded buyers/orders or settled cash reconciliation. [D1] [Q12] [Arithmetic]

### Query 3 — `actives_board`

It selects trailing-30-day distinct order users with status not in `[0,2,3]`, then excludes `test_users` and email heuristics. Those heuristics remove `novamart.com`, `example.com/.net/.org`, `.example`, `.test`, `internal.*`, `test.*`, and tokenized QA/test/demo/internal/seed/sandbox names, including smoke in the localpart pattern. It has no product-brand filter and no `marketing_opt_in` requirement. [D3]

Because it uses a left join and `COALESCE(...,'')`, a missing user/email is not explicitly rejected by the email tests. Status 6 is also not excluded. Therefore “cleaned 30-day ordering users” describes the SQL more accurately than “verified real paid customers.” In this snapshot every email domain is `example.com` or `gmail.example`, which makes the observed board count zero at the historical anchor. [D3] [Q34] [Q37]

### Query 4 — `registered_conversion`

It obtains **distinct numeric user IDs** by `accounts.email = users.email`, then joins paid headers and reports distinct buyers and summed header revenue for **all available history**. It has no conversion-rate denominator, cohort window, after-enrollment condition, or QA/brand exclusion. [D4]

The old UUID-text-to-numeric-ID join returns **0 buyers / 0 orders / NULL revenue**. The corrected query returns **30 / 74 / 18,155.71**; **63 orders / 14,911.96** occurred before enrollment. An explicit `account_map.uid` join currently gives the same 30/74/18,155.71 result, but it is not the current dashboard implementation. Email edits or non-unique emails can make those linkage strategies diverge later (`b975479`). [Q48] [C-Accounts] [C-Users] [Changes]

## B2. User lifecycle, signups, and segments

| Population | How it is created/counted | Observed count and qualification |
|---|---|---|
| First-seen users | View/cart/order/bootstrap inserts numeric `users.id`, default email and synthesized attributes. | **38,950**; counting `created_at` measures first sight in this system, not necessarily a completed registration. [C-Catalog] [C-Carts] [C-Onboarding] [Q20] |
| Registered beta accounts | `/accounts` historically created a UUID, copied user email, and added an `account_map` link. | **30 accounts / 30 distinct mapped UIDs**; route is unmounted at the pin. [C-Accounts] [C-App] [Q20] |
| Currently paid buyers, all history | Distinct order users where `status = 1`. | **4,089**, not all visitors and not a fixed historical publication. [Q20] |
| Marketing opt-in | Stored boolean synthesized by an ID hash. | **24,193**; provenance is synthetic rather than demonstrated consent capture from a form. [C-Onboarding] [Q20] |
| Contactable | Opt-in, case-insensitive email syntax regex, exclude `example.com/.net/.org` and any `.example` domain. | **0**. Syntax alone or opt-in alone is insufficient. [Q04] [Q20] |
| Digest recipient rule | `email NOT LIKE '%@example.com'`. | **40**, all `gmail.example`; does not check opt-in or the trusted view. [Q34] [C-Digest] |
| QA/test | `analytics.test_users` contains numeric 424242; dashboards often hard-code it. | Table inventory has one row; the UUID recorded for the QA account is an identity alias, not a new order-ID namespace. [Inventory] [Q06] [Q30] [D8] |
| Device/channel/region/age segments | Columns synthesized in `onboarding.py`; v4 uses only the organic-channel indicator among these segment flags. | No separate standard segment dashboard was returned by Redash; do not attribute measured demographic behavior to these generated labels. [C-Onboarding] [C-Train] [Redash] |

Forty email updates on October 23 changed placeholders to `cust<uid>@gmail.example`. Those users remain excluded by the trusted contactable view and board heuristics, but pass the digest’s suffix-only check. This explains the apparently inconsistent “40 reachable” versus “0 contactable” outputs without assuming an email pipeline failure. [Q30] [Q34] [Q04] [C-Digest] [D3]

## B3. Funnel semantics and the December “conversion” trap

`funnel.py` unions **cart_items and orders only**, selects a trailing one-day lower bound, sorts by numeric user and timestamp, and starts a new session when the gap exceeds `GAP_MIN`. It ignores product-view events and ignores original session strings; it does not require paid orders or remove QA/brands. It writes the run date, sessions, distinct active users, and run timestamp. It has no purchase numerator or conversion-rate field. [C-Funnel] [Inventory]

Commit `f915c1b` changed the gap from **30 to 120 minutes**. Logs show 30 through December 14 and 120 starting December 15. A longer inactivity threshold can merge sessions and mechanically raise a separately computed orders/sessions ratio without improving purchasing behavior. That is a mathematical consequence of the definition change, not an observed causal conversion improvement. The last stored run has **345 sessions / 308 active users**. [C-Funnel] [Jobs] [History]

## B4. Product metadata and pricing provenance

Blank brand is not automatically a legitimate “unbranded vendor” segment. Earlier insert-on-conflict-do-nothing behavior and the in-process known-ID cache could preserve first-seen blank metadata. Commit `ea0e97b` added a repair path on incoming nonblank brand events; the one-off `blank_brand_products` table captured **5,972 products**, not an ongoing repair or full current inventory. Its two recorded cause groups contain 3,907 blank-category and 2,065 other blank-brand products. [C-Catalog] [Q23] [Q39] [History]

The current products table still has **17,442 blank-brand rows**, **676 Lucente**, and **5 Jetem** products. The audit snapshot is therefore not a current count of missing brands. Joining mutable products to old sales can change brand attribution later even though sales prices are unchanged. [Q35] [D8] [C-Catalog]

Vendor feed behavior changed November 9 with `d213f6e`: existing product IDs now update price/cost/stock and nonblank metadata instead of ignoring the new row. November 15 added price-history recording; captured history begins with the November 18 feed. It is unsafe to use today’s `list_price` as historical selling price or to infer an old price before the first recorded feed row. Callback/line prices are the sale amounts; history is the observed list-price trail. [Changes] [History] [C-Catalog] [C-Orders] [Q41]

# Appendix C. Recommendations, ML, and advisory systems

## C1. Version and policy history

| Period / change | Producer and serving behavior | Observed evidence |
|---|---|---|
| October 12, `776d674` | Add nightly v1 co-cart affinity. | First refresh October 13, 07:30 UTC. [History] [Jobs] |
| October 26, `f1217a8` | Widget reads `product_affinity`; fallback queries seven-day paid-header popularity live. Both paths log effective version 1.0.0. | 392,630 v1 decisions, of which 326,186 source=fallback. [Changes] [Q16] |
| November 12, `fef5c96` | Rare pairs become score −1 at fewer than 3 pair observations. | First job log with `min_pairs=3` is November 13. [History] [Jobs] |
| December 2/5, `89666bf` / `3dbe4d7` | Add conversion-weighted v2; fix absent December seasonal factor, writer version 2.0.0→2.0.1. | Three December 3–5 crashes; first successful v2 refresh December 6 at 08:45 UTC. [Changes] [Jobs] |
| December 6, `df4ed85` | Serving flag 2.0.0, v2 table, stable random arm, trending-table fallback. | First v2 app score SELECT/decision on December 6; version/source totals in Q16. [Changes] [Q06] [Q16] |
| December 14, `a1946ff` | Add nightly v4 logistic fit and model-score table; serving remains flag-gated. | Seventeen registry rows, December 15–31; no v4 serving rows. [History] [Q18] [Q16] |
| December 17, `30e8907` | Random branch returns before writing the decision row. | App events continue; decision-log random rows disappear. [Changes] [Q31] |
| December 19, `a00f24c` | Restore random decision writes; add six-hour cache keyed only by base product, including empty results. | Cache-reason decisions appear; historical empty caches produce fallback with reason `cache`. [Changes] [Q16] |
| December 26, `8ed2971` | Cache key becomes `(table, base_pid)`; invalidate on new max `updated_at`; query only newest batch; cache only nonempty results. | First max-epoch/latest-batch score SELECTs December 26 at 20:00 UTC. [Changes] [Q06] |

There is no version-3 implementation in the pinned dispatch map. The map’s retained label `1.0.0` is historical metadata, not a functioning v1 rollback route: any non-2.0.0 non-random label selects `model_scores`. Likewise an unrecognized flag value is not rejected by dispatch. Validate flags against the actual branch, not just the presence of a version name in the enum. [C-Similar]

## C2. Affinity v1

The job self-joins cart rows on equal `session` and different product ID, with a **30-day lower bound on `c1.created_at` only**. It groups directed `(base_pid, rec_pid)` pairs, counts join rows, and uses the most recent `c1` timestamp. The score is:

```text
if pairs_seen < 3: score = -1
else: score = round(pairs_seen × exp(-0.05 × age_days), 4)
```

This counts row-pairs, not distinct customers or distinct sessions; repeated cart rows can multiply support. The join does not also require equal user ID, and its time filter does not constrain `c2` independently. These details matter when changing session ID generation, cart-removal behavior, or deduplication. [C-Affinity] [C-Carts]

The job deletes and rebuilds `product_affinity`. It also creates `rec_decision_log` if missing, a non-obvious bootstrap side effect. Current widget code no longer reads the old affinity table, and captured app SELECT templates stop using it on December 6. But removing the **job** requires moving that log-table bootstrap and checking consumers outside the captured evidence, rather than deleting it solely on the strength of the widget switch. [C-Affinity] [C-Similar] [Q06]

## C3. Affinity v2

V2 repeats the co-cart pair construction, then counts a conversion contribution whenever the `c2` shopper has **any currently paid header** for `c2.product_id`. There is no requirement that the order followed this cart or occurred in the same session/window, and appended-only item products may not match the order header product. It is a heuristic association feature, not an attributed purchase response. [C-Affinity2] [C-Orders]

For eligible pairs:

```text
raw = (1 × pairs_seen + 3 × conversion_contributions)
      × exp(-0.05 × age_days)
if same nonblank category: raw *= 1.15
if rec/base list-price ratio > 4 or < 0.25: raw *= 0.7
score = round(raw × monthly_seasonal_factor, 4)
```

The “cart=1, order=3” comment should not be read as replacing the cart weight: the implementation adds `3×conv` on top of all pair counts. Category and price features use current product rows. The seasonal list contains eleven factors; December now defaults to **1.0** after the crash fix. Output rows carry **`model_version='2.0.1'`**, although the serving flag and effective policy label are **`2.0.0`**. [C-Affinity2] [C-Similar] [Changes]

Both current affinity tables contain **3,912 pairs**, with **2,964 negative sentinels**, **948 eligible pairs**, and only **449 base products with eligible candidates**. That limited coverage is consistent with extensive fallback; it is not evidence of negative customer preferences toward 2,964 recommendations. [Q19]

## C4. Current serving and cache contract

- `intended_version()` reads the relative file `deploy/flags.env` on each request, resolves aliases (`2`, `v2`, `4`, `v4`, `model4`), and defaults to 2.0.0 if the file is unavailable or contains no matching assignment. It does not read a `REC_MODEL_VERSION` environment variable. Despite the file comment saying “read at deploy time,” the implementation reads at request time; working-directory and file-distribution behavior therefore matter. [C-Similar] [C-Flags]
- Hash the numeric UID using SHA-256, take the first eight hex digits modulo 20, and assign remainder zero to random. This is stable by user, not a fresh 5% coin flip per request. Request share need not equal user assignment share. [C-Similar]
- Random candidates are the first **500 product IDs** ordered ascending after the two SKU exclusions. Seed shuffling with `uid:session:pid`, return at most five. The base product, denied brands, and low/out-of-stock products are not explicitly filtered by this branch. [C-Similar]
- Non-random version 2.0.0 reads v2; other version labels read `model_scores`. Restrict to global max `updated_at`, score ≥0, top five by score, then remove excluded SKU IDs. Filtering after `LIMIT` can shorten the result, and there is no fill-to-five step for a short but nonempty model list. [C-Similar]
- Cache successful score lists for six hours per process and `(table, base_pid)`. Before lookup, compare the score table’s max timestamp and invalidate all cache entries for that table on a new non-null epoch. A failed/empty refresh need not invalidate old cached entries, and the epoch check swallows exceptions. [C-Similar]
- If there are no usable items, select up to five products from the newest **day** in `trending_daily`, ordered by rank. This is newest available, not an enforced fresh/current-day batch; fallback does not apply the model path’s SKU filter. [C-Similar]
- Persist decision time, UID, base PID, comma-separated served IDs, intended/effective version, source, fallback reason, and arm. The app event adds session and item count but omits the full served list. Neither record alone is a complete experiment-exposure schema. [C-Similar] [Inventory]

On December 31 specifically, **5,632** decisions used fallback, **1,950** used the v2 model path, and **422** used random. Model-path responses averaged **3.105 items**, while fallback and random averaged five, confirming that “top five widget” does not mean every model exposure received five candidates. User counts across these sources must not be added as disjoint segments: the same non-random user can receive model and fallback on different base products. [Q51] [C-Similar]

## C5. Logging integrity and interpretation

| UTC date | Random app events | Random decision rows | Missing decision rows |
|---|---:|---:|---:|
| December 17 | 658 | 549 | 109 |
| December 18 | 848 | 0 | 848 |
| December 19 | 822 | 407 | 415 |
| **Affected-date total** | **2,328** | **956** | **1,372** |

The last pre-gap random decision is **December 17 16:48:48 UTC**; the first restored one is **December 19 14:55:04 UTC**, consistent with the refactor and fix times. Training rows remain **5,798** on both December 18 and 19 despite continuing traffic. Treat this as selective missingness in the training/control population, not evidence that random traffic stopped. [Q31] [Q50] [Q18] [Arithmetic] [Changes]

There is also a separate discrepancy on December 11: the decision table has **32 more rows** than app `rec_served` events, including one extra random row. The available evidence establishes the mismatch but not its cause. It explains why subtracting whole-history totals does not recover the exact December 17–19 missing count. [LoggingGaps] [Q31]

For cohort analysis, distinguish:

| Intended label | Source / effective label | Interpretation |
|---|---|---|
| 1.0.0 | `affinity` / 1.0.0 | Old affinity ranking. [Q16] [Changes] |
| 1.0.0 | `fallback` / 1.0.0 | Old live popularity fallback, despite the same effective-version string. [Q16] [Changes] |
| 2.0.0 | `model` / 2.0.0 | Heuristic affinity-v2 scoring, not learned v4. [C-Similar] [Q16] |
| 2.0.0 | `random_arm` / 2.0.0 | Random data-collection policy, not v2 exploitation. [C-Similar] [Q16] |
| 2.0.0 | `fallback` / fallback | Trending fallback; reason can be `no_scores` or historical empty `cache`. [Q16] [Changes] |

The observed fallback shares are **83.08%** in v1 and **79.78%** in the v2-era non-random population. These are coverage/dispatch statistics across different time periods and data conditions, not an A/B lift comparison. [Q16] [Arithmetic]

## C6. Learned model v4: exact features and limitations

The training SELECT reads **all** decision rows with `arm='random'`, joins current users/products, and labels an exposure positive if that user has **any later currently paid order**. There is no outcome horizon, no link to an exposed item, no deduplication of repeated exposures, and no train/validation split. Base popularity counts all currently paid headers for that base product without an as-of restriction. Consequently, point-in-time features and outcome maturity are not enforced. [C-Train]

The fitted vector has exactly **five features**:

| Vector position | Implemented feature |
|---|---|
| 0 | Number of comma-separated served items. [C-Train] |
| 1 | Current base list price / 1,000. [C-Train] |
| 2 | Current all-history paid-header base popularity / 100. [C-Train] |
| 3 | Exposure-time user age / 60 days, capped above at 1.0. [C-Train] |
| 4 | Indicator that signup channel equals `organic`. [C-Train] |

Stock and opt-in are fetched but unused. Region affinity and device mix advertised by the README are absent from the vector. The generated onboarding attributes further limit claims that this fit captures measured demographic preferences. All **14,566** currently stored random exposures have exactly **five served items**, so feature 0 has no variation in this snapshot. [C-Train] [C-README] [C-Onboarding] [Q32]

With at least 20 rows and both classes, it fits `LogisticRegression(random_state=0, solver='lbfgs')`. It saves coefficients/intercept and training-row count to the registry. However, published candidate scores are **not predicted conversion probabilities**; they follow the formula below. [C-Train]

```text
w = coefficient of feature 0 (served-list size)
model_score(base, rec) = round(affinity_v2_score(base, rec) × (1 + 0.1 × w), 4)
```

The other coefficients and intercept are not used to score candidates, and no user-dependent scoring occurs. The latest `w` is **−0.24483754375789174**, giving multiplier **0.9755162456242108**; all **948** current model-score rows match this formula. A common positive multiplier preserves ordering except possible extra rounding ties, so this output does not implement the personalized learned ranking suggested by the README. [C-Train] [Q18] [Q33]

If data is insufficient or single-class, the job appends an “insufficient data or single class” registry note but leaves existing scores in place; `model_trained` is still emitted. Fresh registry/log activity alone therefore does not prove refreshed scores. At this snapshot, valid coefficient rows and matching score timestamps demonstrate successful scoring, but the active flag remains v2 and no observed decision uses v4. [C-Train] [Q18] [Q19] [C-Flags] [Q16]

## C7. Trending, pricing, reorder, and fraud

**Trending:** paid headers in a rolling 30-day window, minimum five units, score `units × exp(−0.05 × age_days_since_last_order)`, sort descending `(score, units, product_id)`, top 50. It replaces that run-date partition and supplies recommendation fallback. README says 60 days; `f563dea` changed the job to 30, first seen in logs December 7. It is still header-grained and has no report denylist or QA filtering. [C-Trending] [C-README] [Jobs] [History]

**Pricing:** a left join to recent 14-day paid headers ranks up to 500 products by demand count. Suggest +5% for counts strictly above the middle row’s count, otherwise −5%, around current list price; delete and rebuild `price_suggestions`. Products with no demand can enter if fewer than 500 have demand. The observed batch has 500 rows, demand range 1–40. The rollout was explicitly held by `cca9b0d`; no retrieved query template selects this table. [C-Price] [Q25] [Q06] [History]

**Reorder:** choose top 200 products by paid-header velocity `COUNT(*)/14`, then `hint_units = int(15.6 + 162.4/(velocity+1.8))`. Commit `f85cdd2` changed only K from **141.12 to 162.4**. The current batch spans **0.0714–2.7143 orders/day** and **51–102 hint units**. The older forecast note’s 55–102 range is not the current table’s range. This job does not incorporate stock, supplier lead times, open POs, uncertainty, or financial constraints; finance should treat it as the code’s explicitly advisory merchandising signal. [C-Reorder] [Changes] [Q25] [C-ForecastNotes]

**Fraud:** score recent paid headers with `core=min(price/3000,1)` and `score=round(min(core×(1+0.15×new_account+0.15×high_velocity),1),4)`. New means user age at order <7 days; high velocity means at least three headers in the inclusive prior-24-hour interval, including the current order. Score strictly above threshold moves a still-paid order to status 6; payments are left intact. Only the latest one-day lower-bound window is considered, and the score is appended to `order_risk`. [C-Fraud]

Threshold history is **0.90**, then **0.70** (`53f6f6c`), then **0.85** (`1cb8721`); logs first show the latter thresholds December 6 and December 30 respectively. The December 29 manual SQL releases held orders with **price <2,600**, not with recomputed score below 0.85. Five current paid orders have the later `NOW()` mutation timestamp and total **10,859.73**; 12 remain held at **40,213.29**. Raising a threshold alone does not reprocess old held orders. [Jobs] [Q39] [Q40] [Changes] [C-Fraud]

Status mutation propagates unevenly: monthly statements, nightly paid actives, trending, top sellers, pricing, and reorder use status 1; daily report and board candidates only exclude `[0,2,3]`, so they keep held orders; best-seller/brand/category dashboards do not filter status at all. A fraud-policy change can thus move some business metrics while leaving others unaffected. [C-Statement] [C-KPI] [C-Trending] [C-Top] [C-Price] [C-Reorder] [C-Daily] [D3] [D6] [D8] [D9]

# Appendix D. Scheduled jobs and safe pipeline changes

## D1. Schedule authority and clock semantics

Commit `4bfcbe6` retired `crontab.txt` and added Airflow wrappers. The former explicitly called its times local; the DAGs use naive `datetime` start dates and do not set a timezone. Thus the literal schedules below are verified, while their deployed timezone depends on Airflow configuration not present in the inspected files. The observed 2019 job timestamps match the historical local schedule, not proof that the January wrappers run with the same timezone. [C-Cron] [C-DAGs] [Jobs] [History]

Every supplied DAG has `catchup=False`, one BashOperator, and no declared inter-DAG readiness dependency or explicit retry settings. Jobs obtain wall-clock `now()` or environment `FAKE_NOW`, rather than receiving an Airflow logical interval. A delayed task or manual rerun can therefore process a different window from the intended historical interval. Most rolling SQL also supplies only a lower bound, so replaying it against a later full database can include future rows relative to a historical `FAKE_NOW`. [C-DAGs] [C-Time] [C-KPI] [C-Affinity2] [C-Train]

The wrappers do not explicitly establish a working directory or source `deploy/cron.env`. Digest enablement precedence is environment `ENABLE_DIGEST`, then environment `DIGEST_ON`, then the relative file’s `ENABLE_DIGEST`, then `0`; only the exact string `1` enables it. A missing file can therefore disable the job without an error or log when neither environment variable is supplied. Check the actual launch context when moving it to a scheduler. [C-DAGs] [C-Digest] [C-CronEnv]

## D2. Complete batch inventory

Short output names in this table refer to serving Postgres tables; `analytics.*` maps to warehouse `novamart_analytics.*`, and unqualified app tables map to `novamart.*`. Schedule strings come from the corresponding `airflow/dags/<job>_dag.py` at `5ae1182`. [Inventory] [C-DAGs]

| Job; literal Airflow schedule | Inputs and output/write mode | Consumer and failure consequence |
|---|---|---|
| `reconcile`; `0 3 * * *` | Scan headers with `status <> 5`, group duplicate payment refs, alphabetically first 200; write warning/job logs only. | Finance diagnostics lose detection if it fails; no data is repaired even on success. 130 references remain flagged. [C-Reconcile] [Q27] |
| `affinity`; `30 3 * * *` | 30-day co-cart pairs → delete/rebuild `analytics.product_affinity`; also bootstrap decision-log table. | Current widget no longer consumes v1 scores; old consumers/bootstrap still require deliberate retirement analysis. Failure during replacement can leave partial output. [C-Affinity] [Q06] |
| `affinity_v2`; `45 3 * * *` | Carts + current headers/products → delete/rebuild `analytics.product_affinity_v2`. | Active v2 widget and model training depend on it. Missing/empty scores increase fallback; stale scores can be served as latest available. [C-Affinity2] [C-Similar] [C-Train] |
| `model_train`; `15 4 * * *` | Random decisions + users/products/orders + v2 candidates → append registry; replace scores only for a valid fit. | Currently shadow/flag-gated for serving; a future v4 policy would inherit stale scores or fallback. Registry activity alone is insufficient. [C-Train] [C-Flags] |
| `price_suggest`; `45 4 * * *` | Current products + 14-day paid-header demand → replace `analytics.price_suggestions`. | Shadow analytics becomes stale; no inspected live pricing consumer breaks. [C-Price] [Q06] |
| `trending`; `15 5 * * *` | 30-day paid headers → replace run-date partition of `analytics.trending_daily`. | Similar-products fallback uses newest available day, so failure can silently retain old fallback lists. [C-Trending] [C-Similar] |
| `fraud_score`; `45 5 * * *` | Recent paid headers + user age/velocity → append `analytics.order_risk`; update qualifying headers to status 6. | Holds may not happen if it fails; current reporting populations differ according to status filters. Rolling one-day selection can miss old unscored orders after an outage. [C-Fraud] |
| `daily_report`; `0 6 * * *` | Previous Eastern date’s lines/legacy headers + products + test-users → append per-product `report_rows`. | Historical executive revenue disappears or stays stale; retries append versions, and partial batches can appear newest. [C-Daily] [D2] [D7] |
| `kpi_daily`; `15 6 * * *` | Trailing 30-day paid-header users → append `analytics.kpi_daily`. | Stored nightly active series misses a run; Redash’s independent customer query may still update. [C-KPI] [D7] |
| `funnel`; `20 6 * * *` | Trailing one-day cart/header activity → append `analytics.daily_funnel`. | Session/activity series has a gap; a late run shifts the window rather than inherently filling the missed one. [C-Funnel] [C-Time] |
| `monthly_statement`; `30 6 1 * *` | Previous local month’s paid headers + collected fees → append `statements`. | Publication is missing; reruns can create duplicate months propagated by finance views, and current-state recomputation may not match original publication. [C-Statement] [Q04] |
| `top_sellers`; `45 6 * * *` | Previous Eastern date’s paid headers → append up to 50 `top_products`. | This ranking table becomes stale; Redash best sellers and the widget do not read it in inspected definitions. [C-Top] [D9] [C-Similar] |
| `reorder_forecast`; `50 6 * * *` | 14-day paid-header counts → replace `analytics.reorder_hints`. | Advisory merchandising hints become stale/partial; no finance-grade forecast is produced. [C-Reorder] |
| `email_digest`; `15 7 * * *` | Seven-day paid-header top product + suffix-only email count; flag-gated append to `analytics.digest_log`. | When disabled it returns silently; when enabled it records a simulated send, not an implemented mail-delivery call. [C-Digest] |
| `intraday_report`; `0 12 * * *` | Current Eastern date through actual run time → append `report_rows_intraday`. | Today’s widget/KPI snapshot is absent/stale. Retired cron had **12:00 and 17:00**, but the wrapper declares only noon. [C-Intraday] [C-IntradayDAG] [C-Cron] |
| `warehouse_backfill`; `None` | Manifest tables → serial Cloud SQL CSV exports + per-table `bq load --replace`. | Warehouse copies can become incomplete/mixed-age; no continuously scheduled refresh is declared. Required CLI args are absent from the wrapper. [C-Warehouse] [C-WarehouseDAG] |

Clock order implies data dependencies but does not enforce them: model training is scheduled after v2; fraud scoring occurs after trending but before daily reporting and paid-customer KPIs. A fraud hold can therefore leave that morning’s trending list based on an earlier status snapshot while later paid-only metrics reflect the hold. This follows from the schedules and status-filtering queries, not from an observed Airflow dependency edge. [C-DAGs] [C-Trending] [C-Fraud] [C-KPI]

## D3. Observed runs, failures, and misleading success signals

- **Affinity-v2 December failure:** `novamart_logs.job_runs` IDs `nvm-job-0000000480`, `0000000492`, and `0000000505` record an `IndexError` at `SEASONAL_FACTORS[t.month - 1]` on December 3, 4, and 5. The list had eleven entries. First successful v2 refresh is `nvm-job-0000000518`, December 6 at 08:45 UTC. Since the current widget switched on December 6 after that refresh, those crashes alone do not prove a v2-serving outage beforehand. [Q05] [Jobs] [Q06] [Changes]
- **Digest two-stage flag failure:** the job originally read `DIGEST_ON`, while the file set `ENABLE_DIGEST=1`. December 9 fixed the variable name, but the job did not itself load `deploy/cron.env` until December 16. First observed `digest_sent` is December 17 at 12:15 UTC, then 15 daily events through December 31, each with 40 recipients. The first top product is excluded report SKU **1002544**, confirming a separate merchandising rule. [C-Digest] [C-CronEnv] [Changes] [Jobs] [C-Constants]
- **Reconcile schedule and cap:** October 18 increased limit 100→200; November 10 moved 02:00→03:00 with a commit message noting backup-window overlap. The supplied run logs do not show a corresponding reconcile crash or long-running outage; max recorded completion duration is 9.8 ms. Record the documented scheduling concern, not an invented incident. [Changes] [Jobs]
- **Latest batches:** December 31 has affinity at 08:30 UTC, v2 at 08:45, model at 09:15, pricing at 09:45, trending at 10:15, fraud at 10:45, daily report at 11:00, KPI at 11:15, funnel at 11:20, top sellers at 11:45, reorder at 11:50, digest at 12:15, and intraday at 17:00/22:00. Those timestamps establish the available data’s freshness, not a present-day operational SLA. [Q02] [Jobs]
- **Log coverage:** `job_runs` has 978 log records, not 978 unique executions; daily report/reconcile each emit start and finish records. Other jobs often emit only one completion record, and disabled digest emits none. Monitoring must use event semantics rather than raw row counts. [Q05] [C-Daily] [C-Reconcile] [C-Digest]

## D4. Warehouse/backfill implementation boundaries

`warehouse_manifest.json` enumerates **32 physical serving tables** and positional BQ types. The exporter renders timestamp-with-time-zone values explicitly in UTC, casts numeric/date/UUID/boolean values to text, uses `__PGNULL__` for nulls so blank strings remain distinct, orders by the first selected column, and serializes exports because the code expects one Cloud SQL export at a time. It then replaces each target table independently. [C-Manifest] [C-Warehouse]

At the pin, `public` maps to `novamart`, but the code maps any other schema to its original name, producing `analytics.<table>` instead of observed `novamart_analytics.<table>`. It does not create the four analytics views or export the log datasets. Those objects exist in the supplied warehouse, but their deployment cannot be attributed to this script alone. The schema file is also only the initial base schema; tables/views created by historical jobs/manual SQL are essential additional dependencies. [C-Warehouse] [C-Manifest] [C-Schema] [Inventory] [Q39]

The manual DAG invokes the module with no `--project`, `--instance`, or `--staging`, although argparse requires all three. Before relying on that wrapper for a future rebuild, explicitly supply the target mapping, arguments, view definitions, schema compatibility, and consistent snapshot strategy. This is a code-derived remediation recommendation; no warehouse rebuild was attempted. [C-WarehouseDAG] [C-Warehouse] [Run]

## D5. Modification/recovery runbook derived from the failure modes

1. **Make the contract explicit before changing a job:** output grain, eligible statuses, QA/brand/SKU policy, source timestamp, timezone, and snapshot/version selection. Changing paid-header logic to item logic is a metric migration, not merely a refactor. Use the dashboard matrix and November/December grain history as regression fixtures. [C-Orders] [C-Daily] [D6] [D7] [D9] [Changes]
2. **Parameterize the business interval separately from wall clock.** A future backfill should pass explicit start/end/as-of boundaries; a `FAKE_NOW` alone does not freeze mutable products, user emails, statuses, or unbounded SQL. Independently compute local midnights and test DST. [C-Time] [C-Funnel] [C-KPI] [C-Affinity2] [Q40] [Q29]
3. **Publish batches atomically with an explicit completed batch identifier.** Current autocommit delete/insert writers and append-only snapshots can expose incomplete newest timestamps. A staging-and-publish or transaction design should make all consumers read a completed version, including cache invalidation. [C-DB] [C-Affinity2] [C-Daily] [C-Similar] [D2]
4. **Define rerun semantics for each output.** Current report/statements/top-products/KPI/funnel/digest/risk writers append; affinity/model/price/reorder replace whole tables; trending replaces a day. A safe retry should not double-count snapshots or multiply statement months, and a historical repair should retain publication provenance. [C-Daily] [C-Statement] [C-Top] [C-KPI] [C-Funnel] [C-Digest] [C-Fraud] [C-Affinity2] [C-Train] [C-Price] [C-Reorder] [C-Trending] [Q04]
5. **Check readiness, not just earlier schedule time.** Require the intended score/data batch before training or serving publication; alert on stale fallback lists and score epochs. Independent Airflow wrappers do not implement those dependencies. [C-DAGs] [C-Train] [C-Similar]
6. **Preserve schema/bootstrap dependencies.** A fresh service needs objects absent from `schema.sql`, including price history, finance/contactable views, and the decision table. Retiring legacy affinity should relocate its decision-log DDL before removing that job. [C-Schema] [C-Catalog] [C-Affinity] [Q39]
7. **Audit actual consumers before removal.** The captured SQL and code show no live price-suggestion reader and no current widget v1 reader; those are bounded findings about inspected consumers. Search future dashboards/jobs and preserve required bootstrap side effects before retirement. [Q06] [Redash] [C-Price] [C-Affinity] [C-Similar]
8. **Fix the ops discount helper before using it as finance logic.** `DISCOUNT_CAP=0.25`, but `apply_discounts(rows, cap=0.40)` defaults to the legacy cap, and `scripts/rerun_kpis.py` calls it without a cap. It multiplies every row by 0.60 instead of 0.75. The helper currently prints a manually filled list and is not called by the scheduled sales jobs; there is no evidence it changed persisted revenue here. [C-Constants] [C-Discount] [C-Rerun] [C-Daily] [C-Intraday]
9. **Use meaningful regression fixtures:** October statement bridge, November 3 DST tail, November 17 >500 rows, a multi-line order, refund-still-paid behavior, three active definitions, random-arm log coverage, and score refresh/cache boundaries. The existing CI only exercises one view/cart/order flow and three job exits; its payment-count-equals-order-count check does not cover legitimate multi-payment headers. [C-CI] [Q01] [Q15] [Q29] [Q28] [Q13] [Q37] [Q31] [C-Similar]
10. **Validate changes in an isolated future development environment.** The supplied CI performs schema creation/truncation, starts a service, and runs mutating jobs. For this investigation it was read, not executed; warehouse evidence collection used SELECTs and metadata reads, and Redash used GET only. [C-CI] [Run] [Collector] [Queries]

# Appendix E. Warehouse/table field guide

## E1. App tables (`novamart`)

Counts below are the supplied inventory snapshot. Keys describe producer intent/serving structure, not a claim that BigQuery enforces Postgres constraints. [Inventory] [C-Schema] [C-Orders] [C-Accounts]

| Table | Rows | Grain / relationships / use |
|---|---:|---|
| `users` | 38,950 | Numeric shopper ID, current email and synthesized attributes, first-seen timestamp. Orders/carts/decision rows use this namespace. [Inventory] [C-Catalog] [C-Onboarding] |
| `accounts` | 30 | UUID registration record and email copied at enrollment. [Inventory] [C-Accounts] |
| `account_map` | 30 | UID↔account UUID link plus linked time; writer declares neither UID nor link-pair uniqueness. [Inventory] [C-Accounts] |
| `products` | 81,018 | Current product dimension, mutable list price/metadata/cost/stock. [Inventory] [C-Catalog] |
| `cart_items` | 36,938 | Add rows keyed by generated ID; user/product/session/time, removable by API. [Inventory] [C-Carts] |
| `orders` | 9,127 | Header ID, legacy user, original product/ref/time, accumulated price, mutable status/update time. [Inventory] [C-Orders] |
| `order_lines` | 2,284 | Callback item with order/product/price/session/payment-ref/time; unique payment-ref index in serving writer. [Inventory] [C-Orders] |
| `payments` | 9,361 | Monetary movement per payment row; multiple per header; nullable payment_ref including legacy/refund rows. [Inventory] [C-Orders] [C-Webhook] |
| `report_rows` | 6,923 | Product × report date × run timestamp, units/revenue; append-only snapshots. [Inventory] [C-Daily] |
| `report_rows_intraday` | 2,358 | Same product/date/version grain, cumulative partial-day snapshots. [Inventory] [C-Intraday] |
| `statements` | 3 | Month × publication run; gross/fee/net/header count. [Inventory] [C-Statement] |
| `top_products` | 2,396 | Product rank for previous local date and run; paid-header unit ranking. [Inventory] [C-Top] |

## E2. Analytics tables (`novamart_analytics`)

| Table | Rows | Producer / purpose / history behavior |
|---|---:|---|
| `blank_brand_products` | 5,972 | One-off analyst/engineer snapshot with cause labels, order aggregates, and captured time; not a live missing-brand view. [Inventory] [Q39] |
| `category_names` | 135 | Base code→display group mappings and validity dates. [Inventory] [Q22] |
| `category_name_history` | 6 | Higher-priority date-effective mapping revisions; actual effective dates are 2026. [Inventory] [Q22] |
| `chargebacks` | 3 | Booked amount by original order ID and reported time; restates original order month. [Inventory] [Q11] [Q04] |
| `statement_overrides` | 1 | Approved October replacement values, including publication timestamp and note. [Inventory] [Q10] |
| `statement_corrections` | 1 | November audit delta/reason; delta zero; not read by corrected/final views. [Inventory] [Q09] [Q04] |
| `test_users` | 1 | Numeric QA exclusion lookup, populated with 424242. [Inventory] [Q06] |
| `daily_funnel` | 53 | Appended run-date sessions/active users. [Inventory] [C-Funnel] |
| `kpi_daily` | 45 | Appended run-date trailing-30-day paid-buyer count. [Inventory] [C-KPI] |
| `digest_log` | 15 | Appended recipient-count/top-product run records. [Inventory] [C-Digest] |
| `order_risk` | 1,631 | Appended order score/core/user-signal flags/scored time; not one guaranteed unique row per order. [Inventory] [C-Fraud] |
| `price_history` | 1,400 | Product/list-price/feed-effective-time events, 241 products. [Inventory] [Q41] |
| `price_suggestions` | 500 | Latest whole-table shadow price recommendations. [Inventory] [C-Price] |
| `reorder_hints` | 200 | Latest whole-table velocity/hint output; no retained daily forecast history here. [Inventory] [C-Reorder] |
| `product_affinity` | 3,912 | Latest whole-table directed pair score/support/time, old model. [Inventory] [C-Affinity] |
| `product_affinity_v2` | 3,912 | Latest directed pair score/support/writer-version/time, active heuristic. [Inventory] [C-Affinity2] |
| `model_registry` | 17 | Appended training timestamp, version, coefficient JSON, train-row count. [Inventory] [C-Train] |
| `model_scores` | 948 | Latest successful fit’s scaled v2 candidate scores. [Inventory] [C-Train] [Q33] |
| `rec_decision_log` | 667,850 | Timestamp/user/base/items/version/source/reason/arm per logged exposure; CSV item IDs, no request/session key. [Inventory] [C-Similar] |
| `trending_daily` | 2,898 | Day/rank/product/score/units/run timestamp, current-day replacement with prior days retained. [Inventory] [C-Trending] |

## E3. Views and log tables

| Object | Contract |
|---|---|
| `novamart_analytics.contactable_users` | Current user/email/created-at projection after trusted contactability filters. [Q04] |
| `novamart_analytics.refunds_unified` | Union of current cancelled/refunded status rows and signed-payment refund events. [Q04] |
| `novamart_analytics.statements_corrected` | Statement rows left-joined to month overrides, each output field `COALESCE(override, published)`. [Q04] |
| `novamart_analytics.statements_final` | Corrected rows less summed order-month chargebacks in gross/net. [Q04] |
| `novamart_logs.db_queries` | Timestamp, insertId, raw Postgres-style statement line in `textPayload`, common log-export metadata. Full SQL parameters make this useful for old filters and manual DDL/backfills. [Inventory] [Q03] [Q39] |
| `novamart_logs.app_events` | JSON event records in `jsonPayload`: viewed/carted/ordered/replayed/refunded/registered/served and warnings. [Inventory] [Q07] [Q30] |
| `novamart_logs.job_runs` | JSON start/completion/crash records, job names, metrics, durations; not a universal one-row-per-run table. [Inventory] [Q05] |
| `novamart_logs.db_queries_normalized` | An available view with query/statement-type/user-email/timing and job-like metadata columns. Raw `db_queries` was used for the cited historical statements, avoiding assumptions that normalized fields prove successful execution. [Inventory] [Q06] [C-DB] |

The inventory API reports zero rows for views as metadata; that is not their SELECT result. For example, the statement views return three monthly rows each. Use view queries rather than metadata `numRows` to assess emptiness. [Inventory] [Q01]

# Appendix F. Reproducible read-only investigation queries

The saved `q*.json` artifacts contain the **exact SELECT, returned schema, full result rows, and pagination flag**. All 51 named evidence queries completed with no continuation page. `queries.py` contains Q05–Q51; Q01–Q04 were issued through `investigate.py query`. Redash SQL is saved separately as `redash_query_<id>.sql`; it was read, not executed or refreshed in Redash. [Collector] [Queries] [Q01] [Q02] [Q03] [Q04] [Redash]

## F1. Read the publication, correction, and final layers

This SELECT makes Q01’s column projection explicit for convenient inspection. Substitute a month filter in each branch when investigating one month; preserve `created_at` to distinguish publication versions. [Q01] [C-Statement]

```sql
SELECT 'published' AS layer, month, gross, fee, net, orders_count, created_at
FROM `novamart-warehouse.novamart.statements`
UNION ALL
SELECT 'corrected', month, gross, fee, net, orders_count, created_at
FROM `novamart-warehouse.novamart_analytics.statements_corrected`
UNION ALL
SELECT 'final', month, gross, fee, net, orders_count, created_at
FROM `novamart-warehouse.novamart_analytics.statements_final`
ORDER BY month, layer;
```

To explain adjustments, Q09–Q11 select the audit correction, override, and chargebacks joined to original order time. Q04 retrieves actual view definitions; Q39 preserves the historical backfill statements and their `insertId`s. In this emulator the information-schema rendering omits some string quoting, so the saved original Postgres DDL in Q39/Q06 is useful when reading the precise predicates. [Q09] [Q10] [Q11] [Q04] [Q39] [Q06]

## F2. Recompute current-state header revenue without payment fanout

This is Q26’s structure. Its result is diagnostic, not a replacement for published statements; grouping by header-created month deliberately differs from grouping money movements by payment time. [Q26] [Q14] [C-Restatement]

```sql
WITH payment_totals AS (
  SELECT order_id,
         SUM(fee) AS fee,
         SUM(gross) AS payment_gross,
         SUM(net) AS payment_net
  FROM `novamart-warehouse.novamart.payments`
  GROUP BY order_id
)
SELECT FORMAT_TIMESTAMP('%Y-%m', o.created_at, 'America/New_York') AS month,
       COUNT(*) AS orders,
       SUM(o.price) AS gross,
       SUM(p.fee) AS fee,
       SUM(o.price) - SUM(p.fee) AS header_net,
       SUM(p.payment_gross) AS payment_gross,
       SUM(p.payment_net) AS payment_net
FROM `novamart-warehouse.novamart.orders` o
LEFT JOIN payment_totals p ON p.order_id = o.id
WHERE o.status = 1
GROUP BY month
ORDER BY month;
```

## F3. Reproduce best sellers at an explicit historical anchor

The executed Q43 uses this line-plus-legacy grain and the same filters. The explicit anchor avoids treating the current wall clock as though it were inside the 2019 event history. The saved Q43 returns all 20 rows. [Q43] [D9] [Q42]

```sql
WITH item_orders AS (
  SELECT o.user_id, ol.product_id, ol.price, ol.created_at
  FROM `novamart-warehouse.novamart.orders` o
  JOIN `novamart-warehouse.novamart.order_lines` ol ON ol.order_id = o.id
  UNION ALL
  SELECT o.user_id, o.product_id, o.price, o.created_at
  FROM `novamart-warehouse.novamart.orders` o
  WHERE NOT EXISTS (
    SELECT 1 FROM `novamart-warehouse.novamart.order_lines` ol
    WHERE ol.order_id = o.id
  )
)
SELECT io.product_id, COUNT(*) AS units, SUM(io.price) AS revenue
FROM item_orders io
JOIN `novamart-warehouse.novamart.products` p ON p.id = io.product_id
WHERE io.created_at >= TIMESTAMP('2019-12-31 23:59:59+00') - INTERVAL 7 DAY
  AND io.user_id <> 424242
  AND p.brand NOT IN ('lucente', 'jetem')
GROUP BY io.product_id
ORDER BY revenue DESC
LIMIT 20;
```

For a historical as-of reconstruction on a database containing later events, add an explicit upper bound and select as-of dimension/status versions if available. The original dashboard only has a lower bound; Q43 faithfully retains that rule against this bounded snapshot. Current mutable dimensions mean a historical anchor alone is not full time travel. [D9] [Q42] [C-Catalog] [C-Orders]

## F4. Locate historical definitions in query logs

Q06 groups every raw SQL template by actor, count, first/last timestamp, and an example insertId. This finds one-off finance/taxonomy writes and runtime readers even when the operation was not committed as a migration file. To inspect a cited event directly, use the following read-only pattern, exercised by Q39. [Q06] [Q39]

```sql
SELECT timestamp, insertId, textPayload
FROM `novamart-warehouse.novamart_logs.db_queries`
WHERE insertId IN (
  'nvm-dbq-0000374529',  -- October override
  'nvm-dbq-0001904091',  -- November fee audit
  'nvm-dbq-0002395860',  -- taxonomy history using CURRENT_DATE
  'nvm-dbq-0003446400'   -- held-order release using NOW()
)
ORDER BY timestamp;
```

Interpret SQL log counts as attempts, because the logger writes before `conn.execute`. Corroborate actual results with tables and completion/app events. [C-DB] [Q10] [Q09] [Q22] [Q40]

## F5. Recommendation dispatch and logging coverage

Q16 is the source-aware dispatch audit below; Q31 joins daily app `rec_served` counts to decision rows to expose the missing random branch. Effective version alone would misclassify both v1 fallback and v2-era random traffic. [Q16] [Q31] [C-Similar] [Changes]

```sql
SELECT intended_version, effective_version, rec_source, fallback_reason, arm,
       COUNT(*) AS decisions, MIN(ts) AS first_at, MAX(ts) AS last_at
FROM `novamart-warehouse.novamart_analytics.rec_decision_log`
GROUP BY intended_version, effective_version, rec_source, fallback_reason, arm
ORDER BY decisions DESC;
```

## F6. Query index by operational question

| Question | Executed evidence queries |
|---|---|
| Which monthly numbers are approved, and why? | Q01, Q04, Q09–Q11, Q26, Q30, Q39, Q47, Q49. [Q01] [Q04] [Q26] [Q49] |
| How do money, refunds, statuses, and item/header counts differ? | Q08, Q12–Q15, Q27. [Q08] [Q12] [Q13] [Q14] [Q15] [Q27] |
| Were daily reports truncated or duplicated? | Q24, Q28–Q29, Q38, Q46; job history Q05. [Q24] [Q28] [Q29] [Q38] [Q46] [Q05] |
| What do product/brand/category queries produce? | Q22–Q23, Q35, Q41, Q43–Q45. [Q22] [Q23] [Q35] [Q41] [Q43] [Q44] [Q45] |
| Who counts as a customer, registered buyer, or contactable? | Q20–Q21, Q30, Q34, Q36–Q37, Q48. [Q20] [Q21] [Q30] [Q34] [Q36] [Q37] [Q48] |
| Which recommendation policy ran, and did training change ranking? | Q16–Q19, Q31–Q33, Q50–Q51. [Q16] [Q17] [Q18] [Q19] [Q31] [Q32] [Q33] [Q50] [Q51] |
| Are advisory outputs fresh, and which code read them? | Q06, Q19, Q25 and all job events Q05. [Q06] [Q19] [Q25] [Q05] |
| What is the temporal coverage, and where do physical timestamps disagree? | Q22–Q23, Q39–Q42. [Q22] [Q23] [Q39] [Q40] [Q41] [Q42] |

# Appendix G. Evidence index and remaining uncertainty

## G1. Citation conventions

**`C-*` references** are files/directories in the sole permitted repository at `5ae1182`; paths are relative to this document. **History/Changes** are read-only captures of local git history and selected patches. **`D1`–`D9`** are the exact retrieved Redash SQL, linked locally for reproducibility. **`Q01`–`Q51`** are executed BigQuery SELECT results with their SQL. **Jobs/Arithmetic/LoggingGaps** are deterministic summaries of those saved results, not additional external sources. [Run] [Collector] [Queries] [History] [Changes]

Live Redash query addresses, read-only during this investigation:

| ID | Name | Address |
|---|---|---|
| 1 | refunds | <http://localhost:5050/queries/1> [D1] |
| 2 | revenue_widget | <http://localhost:5050/queries/2> [D2] |
| 3 | actives_board | <http://localhost:5050/queries/3> [D3] |
| 4 | registered_conversion | <http://localhost:5050/queries/4> [D4] |
| 5 | statements_final | <http://localhost:5050/queries/5> [D5] |
| 6 | category_revenue | <http://localhost:5050/queries/6> [D6] |
| 7 | daily_kpis | <http://localhost:5050/queries/7> [D7] |
| 8 | brand_revenue | <http://localhost:5050/queries/8> [D8] |
| 9 | best_sellers | <http://localhost:5050/queries/9> [D9] |

## G2. Explicitly bounded conclusions

- **No current business activity beyond the supplied history is established.** Orders end December 31, logs end December 31, and no January monthly/job execution exists in the supplied logs. January DAGs and migration scripts are inspected code, not observed completed migrations. [Q42] [Q01] [Q05] [C-DAGs]
- **No rendered dashboard value or cache freshness was verified.** All query result pointers were null and dashboard details returned 500. The reported dashboard examples are clearly labeled warehouse reproductions with explicit anchors. [Redash] [DashboardError] [Q38] [Q43] [Q46]
- **No full gateway settlement or bank reconciliation is available.** The inspected tables store callback movements, status-only legacy refunds, and manual chargebacks; they do not establish every external settlement fact. The approved finance view should be described by its implemented scope. [C-Webhook] [C-Orders] [Q04] [Inventory]
- **No validated recommendation, pricing, forecast, or fraud uplift is demonstrated.** Training completion, scoring freshness, and serving counts establish system behavior; the code/registry lacks an evaluation contract sufficient to infer incremental commercial effect. [C-Train] [C-Price] [C-Reorder] [C-Fraud] [Q18] [Q16]
- **Timestamp discrepancies remain visible.** Current category effective dates and `NOW()`-derived mutation/capture times conflict with the historical log chronology. The observed values and likely mechanism are documented; the data was not rewritten or assumed to be historically corrected. [Q22] [Q23] [Q39] [Q40]
- **Some documentation is demonstrably stale or incomplete.** README’s 60-day trending and broad v4 feature list, category line-adoption attribution, the old reorder range, `analytics` warehouse naming, and `rec_versions.md` containing only “TBD” are not authoritative over the actual code/data. [C-README] [C-Trending] [C-Train] [C-DashboardNotes] [C-ForecastNotes] [C-Access] [C-RecNotes] [Q25] [Inventory] [Changes]

[Run]: run_metadata.json
[History]: git_history.txt
[Changes]: git_selected_changes.txt
[RouteHistory]: git_routes_history.txt
[Evidence]: #appendix-g-evidence-index-and-remaining-uncertainty
[Collector]: investigate.py
[Queries]: queries.py
[Inventory]: warehouse_inventory.json
[Redash]: redash_queries.json
[RedashDashboards]: redash_dashboards.json
[DashboardError]: redash_dashboard_9.json
[Jobs]: derived_job_summary.json
[LoggingGaps]: derived_logging_gaps.json
[RollupSamples]: derived_rollup_sample.json
[Arithmetic]: derived_arithmetic.json
[C-README]: ../novamart/README.md
[C-Schema]: ../novamart/schema.sql
[C-App]: ../novamart/novamart/app.py
[C-DB]: ../novamart/novamart/db.py
[C-Log]: ../novamart/novamart/logutil.py
[C-Catalog]: ../novamart/novamart/routers/catalog.py
[C-Carts]: ../novamart/novamart/routers/carts.py
[C-Orders]: ../novamart/novamart/routers/orders.py
[C-Webhook]: ../novamart/novamart/routers/payments_webhook.py
[C-Accounts]: ../novamart/novamart/routers/accounts.py
[C-Users]: ../novamart/novamart/routers/users.py
[C-Reports]: ../novamart/novamart/routers/reports.py
[C-Similar]: ../novamart/novamart/routers/similar.py
[C-Onboarding]: ../novamart/novamart/onboarding.py
[C-Constants]: ../novamart/novamart/constants.py
[C-Statement]: ../novamart/novamart/jobs/monthly_statement.py
[C-Daily]: ../novamart/novamart/jobs/daily_report.py
[C-Intraday]: ../novamart/novamart/jobs/intraday_report.py
[C-Time]: ../novamart/novamart/jobs/timeutil.py
[C-Reconcile]: ../novamart/novamart/jobs/reconcile.py
[C-Top]: ../novamart/novamart/jobs/top_sellers.py
[C-KPI]: ../novamart/novamart/jobs/kpi_daily.py
[C-Funnel]: ../novamart/novamart/jobs/funnel.py
[C-Digest]: ../novamart/novamart/jobs/email_digest.py
[C-Affinity]: ../novamart/novamart/jobs/affinity.py
[C-Affinity2]: ../novamart/novamart/jobs/affinity_v2.py
[C-Train]: ../novamart/novamart/jobs/model_train.py
[C-Trending]: ../novamart/novamart/jobs/trending.py
[C-Fraud]: ../novamart/novamart/jobs/fraud_score.py
[C-Price]: ../novamart/novamart/jobs/price_suggest.py
[C-Reorder]: ../novamart/novamart/jobs/reorder_forecast.py
[C-Discount]: ../novamart/novamart/jobs/discounts.py
[C-Rerun]: ../novamart/scripts/rerun_kpis.py
[C-Warehouse]: ../novamart/novamart/jobs/warehouse_backfill.py
[C-Manifest]: ../novamart/novamart/jobs/warehouse_manifest.json
[C-CI]: ../novamart/ci/run_ci.py
[C-DAGs]: ../novamart/airflow/dags/
[C-IntradayDAG]: ../novamart/airflow/dags/intraday_report_dag.py
[C-WarehouseDAG]: ../novamart/airflow/dags/warehouse_backfill_dag.py
[C-Cron]: ../novamart/crontab.txt
[C-CronEnv]: ../novamart/deploy/cron.env
[C-Flags]: ../novamart/deploy/flags.env
[C-Access]: ../novamart/docs/data-access.md
[C-Restatement]: ../novamart/docs/restatement_policy.md
[C-DashboardNotes]: ../novamart/docs/dashboard_notes.md
[C-ForecastNotes]: ../novamart/docs/forecast_caveats.md
[C-RecNotes]: ../novamart/docs/rec_versions.md
[D1]: redash_query_1.sql
[D2]: redash_query_2.sql
[D3]: redash_query_3.sql
[D4]: redash_query_4.sql
[D5]: redash_query_5.sql
[D6]: redash_query_6.sql
[D7]: redash_query_7.sql
[D8]: redash_query_8.sql
[D9]: redash_query_9.sql
[Q01]: q01_statements.json
[Q02]: q02_job_samples.json
[Q03]: q03_log_samples.json
[Q04]: q04_views.json
[Q05]: q05_job_history.json
[Q06]: q06_db_templates.json
[Q07]: q07_app_event_types.json
[Q08]: q08_order_month_status.json
[Q09]: q09_corrections.json
[Q10]: q10_overrides.json
[Q11]: q11_chargebacks.json
[Q12]: q12_refunds.json
[Q13]: q13_refund_overlap.json
[Q14]: q14_payments.json
[Q15]: q15_line_grain.json
[Q16]: q16_rec_versions.json
[Q17]: q17_rec_daily.json
[Q18]: q18_models.json
[Q19]: q19_affinity_health.json
[Q20]: q20_customer_populations.json
[Q21]: q21_registered.json
[Q22]: q22_taxonomy.json
[Q23]: q23_blank_brands.json
[Q24]: q24_rollup_versions.json
[Q25]: q25_reorder_prices.json
[Q26]: q26_finance_recomputed.json
[Q27]: q27_duplicate_refs.json
[Q28]: q28_busy_and_dst.json
[Q29]: q29_dst_last_hour.json
[Q30]: q30_app_special_events.json
[Q31]: q31_rec_logging_daily.json
[Q32]: q32_training_data_shape.json
[Q33]: q33_model_score_equivalence.json
[Q34]: q34_email_domains.json
[Q35]: q35_current_brand_state.json
[Q36]: q36_latest_kpis.json
[Q37]: q37_active_comparison.json
[Q38]: q38_widget_comparison.json
[Q39]: q39_db_key_lines.json
[Q40]: q40_status_release.json
[Q41]: q41_price_history.json
[Q42]: q42_dataset_coverage.json
[Q43]: q43_best_sellers.json
[Q44]: q44_brand_revenue.json
[Q45]: q45_category_revenue.json
[Q46]: q46_exec_daily_kpis.json
[Q47]: q47_fee_transition.json
[Q48]: q48_registered_lineage.json
[Q49]: q49_fee_mismatch_per_header.json
[Q50]: q50_random_gap_boundaries.json
[Q51]: q51_rec_current_day.json
