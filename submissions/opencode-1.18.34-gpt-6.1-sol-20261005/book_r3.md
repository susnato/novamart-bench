# 1. Summary

**Use the finance statement layers to answer monthly revenue questions; use each dashboard's own SQL to explain its numbers; distinguish recommendation training from actual serving and demonstrated impact.** Those are three different reporting contracts in this system. [^monthly] [^policy] [^R5] [^R7] [^similar] [^train]

| Decision | Answer supported by the inspected systems | Evidence |
|---|---|---|
| Current restated monthly finance revenue | `novamart_analytics.statements_final`; October 2019 net is **1,191,085.36**. | [Q004](q004_statement_layers.json), [^policy], [^R5] |
| Reproduce the old November board deck's October number | `novamart.statements`; October net was **1,194,652.79**. Do not replace an as-published answer with today's restatement. | [Q001](q001_statements.json), [^policy] |
| Explain the difference | A **0.14 fee correction** increases October net; **3,567.57 of chargebacks** then reduces gross and net, attributed to original order month. | [Q005](q005_overrides.json), [Q007](q007_chargebacks.json), [Q016](q016_statement_history_sql.json) |
| Explain executive revenue and “orders” | They are filtered report/item totals, with latest closed-day snapshots plus today's latest partial snapshot. “Orders” in daily KPIs means summed item units. | [^daily], [^intraday], [^R2], [^R7] |
| Explain active customers | Nightly 30-day paid buyers, daily executive ordering users, and cleaned 30-day board buyers are separate definitions. Held orders are included by some definitions and excluded by others. | [^kpi], [^R3], [^R7], [^fraud] |
| What recommendations are live? | Flag **2.0.0** reads affinity-v2 rows stamped **2.0.1**; v4 is trained but has no observed serving reads or intended-version traffic in the inspected logs. | [^flags], [^similar], [Q060](q060_app_score_reads.json), [Q080](q080_rec_rollout_times.json) |
| Does v4 improve ranking? | Its writer multiplies v2 scores by one global factor. The current **948** candidate pairs across **449** bases have **zero rank changes** against v2 under a common tie-breaker. Training success is not proof of better recommendations. | [^train], [Q036](q036_model_registry.json), [Q062](q062_score_ranks.json) |
| Are dynamic pricing and reorder quantities dependable live systems? | Pricing is write-only shadow output; reorder hints are a hand-fit inverse-velocity heuristic, explicitly advisory. | [^price], [^reorder], [Q055](q055_price_reader_counts.json), [Q041](q041_reorder_snapshot.json) |

**Scope:** repository `novamart` at `5ae1182`; the three supplied BigQuery datasets; and read-only Redash definitions. The available operational data is historical: orders end at **2019-12-31 16:51:39 UTC**, app logs at **23:57:06 UTC**, and job logs at **22:00:00 UTC** that day. Fixed-date reproductions below use this historical horizon rather than wall-clock `now()`. They are warehouse reproductions, not refreshed Redash results. [Repository commit](repository_commit.txt), [Q066](q066_runtime_boundaries.json), [Redash query metadata](redash_queries.json)

# 2. Why this project

The central business problem is **definition drift with preserved historical outputs**: order callbacks became idempotent and then multi-item; report filters and day windows changed; fees were corrected; later chargebacks created a restated finance layer; customer identity gained UUID accounts; recommendation logging and caches changed independently of model training. A number is interpretable only with its source, grain, time window, filters, publication/run time, and version. [History](git_definition_history.txt), [Batch history](git_batch_history.txt), [Q016](q016_statement_history_sql.json), [^accounts], [^similar]

This document supports three practical tasks: explaining a month's revenue with a reconciliation bridge; reproducing product/customer dashboard definitions; and understanding batch dependencies, failure modes, and ML effectiveness before extending pipelines. The need is visible in concrete discrepancies: October's three statement answers, the former revenue-widget overcount, and a random-arm logging gap while recommendations continued to be served. [Q001](q001_statements.json), [Q004](q004_statement_layers.json), [Q053](q053_revenue_widget_bug.json), [Q059](q059_rec_gap.json), commits `3eced24`, `30e8907`, `a00f24c` in [definition history](git_definition_history.txt)

# 3. Business understanding

- **Commerce flow:** product views and cart/order callbacks bootstrap catalog and shopper records; `/orders` accepts a gateway callback containing price, session, and payment reference. Payments record gross, processor fee, and net. New references in the same shopper/session within 15 minutes can add item lines and payments to an existing order. Thus a purchase callback, item, order header, and payment movement are different units. [^catalog] [^carts] [^orders]
- **Price authority:** storefront/catalog list prices come from vendor price-feed upserts, with `price_history` entries; the order writer uses the callback's price, not today's catalog price or `price_suggestions`. Repricing the catalog is not repricing historical orders. [^catalog] [^orders] [^price]
- **Finance contract:** monthly gross is eligible order-header price at statement generation; fee is collected payment fees attached to eligible orders; net is gross minus fees. Final statements apply overrides and booked chargebacks, not a recomputation of every subsequent refund or status change. Product cost is not subtracted, so this “net” is not profit or gross margin. [^monthly], [Q002](q002_views.json), [Q016](q016_statement_history_sql.json), [product schema](metadata_novamart_products.json)
- **Merchandising contract:** executive product reporting intentionally hides Lucente and Jetem, and often excludes QA user `424242`; daily report jobs additionally exclude two SKUs. Finance statements have none of these merchandise/QA exclusions. Do not reconcile these surfaces by expecting identical totals. [^daily] [^monthly] [^R8] [^R9]
- **Customer contract:** `users` is a first-seen shopper inventory, not an explicit registration log. `accounts` is a separate UUID registration beta; `account_map` bridges to legacy numeric IDs. Contactability, marketing opt-in, ordering activity, cart activity, and registration are distinct attributes. [^catalog] [^accounts] [^profile] [^funnel] [^R4], [Q016](q016_statement_history_sql.json)
- **ML/operations contract:** affinity and trending support similar-products serving; fraud scoring changes order eligibility for paid-only analytics; v4 trains into a separate score table; pricing and reorder outputs are shadow/advisory merchandising artifacts. [^similar] [^affinity2] [^trending] [^fraud] [^train] [^price] [^reorder]

# 4. Metrics

| Metric / consumer | Exact contract and authoritative surface | Important interpretation | Evidence |
|---|---|---|---|
| Published monthly finance gross / fee / net | `novamart.statements`, append per run; Eastern order-created month, `status=1` at run time | Historical publication, not today's order-state recomputation | [^monthly], [Q001](q001_statements.json) |
| Corrected monthly finance | `novamart_analytics.statements_corrected`: published rows with monthly overrides | Intermediate layer before chargebacks | [Q002](q002_views.json), [Q005](q005_overrides.json) |
| Final monthly finance / Redash `statements_final` | Corrected gross and net less chargebacks in original order's Eastern month; fee/count unchanged | Default current restated finance answer; no December row in available statements | [Q004](q004_statement_layers.json), [Q007](q007_chargebacks.json), [^R5] |
| Payment movement totals | `novamart.payments`, sum by payment `created_at`; negative rows represent gateway refunds | Money-movement ledger lens, different from statement order-month lens | [^gateway], [Q010](q010_payment_month.json), [Q011](q011_payment_order_month.json) |
| Refunds / Redash `refunds` | `refunds_unified`: cancellation/refund statuses plus negative payment events; Eastern event month | Counts mixed operational events, not just cash refunds or unique refunded orders | [Q008](q008_refunds.json), [Q016](q016_statement_history_sql.json), [^R1] |
| Daily executive revenue / “orders” | Latest `report_rows` batch for closed days, latest `report_rows_intraday` for today; 14 Eastern calendar dates | “Orders” is item units; today is partial; customer counts use a different eligibility path | [^R7] [^daily] [^intraday] |
| Seven-day revenue widget | Six closed Eastern calendar days + today's latest partial snapshot | Not rolling 168 hours; never union all historical intraday snapshots | [^R2], [Q075](q075_widget_total.json) |
| Executive best sellers | Item lines with legacy fallback; rolling 7×24h; QA and brand exclusions; revenue descending; top 20 | No status filter; not the nightly units-ranked top-products list; test SKUs are not excluded | [^R9] [^top] |
| Executive brand revenue | Item lines with fallback; rolling 30×24h; current brand; numeric QA plus string UUID exclusion | No status filter; blank brand remains blank; UUID exclusion is inert on the inspected numeric `user_id` schema | [^R8], [order schema](metadata_novamart_orders.json) |
| Executive category revenue | Same item grain; rolling 30×24h; latest eligible mapping by code/date, history wins date ties | Unmapped → `other`; uses current product category and session-date cast, not necessarily Eastern date | [^R6], [Q029](q029_taxonomy.json) |
| Nightly active customers | `kpi_daily`: distinct numeric buyers in trailing 30 days, `status=1`; appended per run | No QA, brand, or email cleaning | [^kpi], [Q021](q021_kpi_history.json) |
| Executive active customers | Per Eastern day, distinct ordering users; exclude QA and Lucente/Jetem, no status filter | Not a monthly unique total; adding daily distincts double-counts repeat buyers | [^R7] |
| Board active customers | Trailing 30 days; exclude statuses `0,2,3`; remove `test_users` and email heuristics | Includes status 6 holds; placeholder-email filtering eliminates every candidate in this snapshot | [^R3], [Q044](q044_board_snapshot.json) |
| Contactable customers | `contactable_users`: opt-in + valid-looking email + domain exclusions; daily KPI counts ordering members | Not identical to opt-in or digest recipient count | [Q016](q016_statement_history_sql.json), [Q017](q017_customers_snapshot.json), [^R7] |
| Registered buyers / revenue | Email-map accounts to numeric users; all historical `status=1` orders | Query named “conversion” has no denominator or enrollment-time restriction | [^R4], [Q019](q019_registered_conversion.json) |
| Funnel sessions / active users | Cart/order activity in trailing 24h, per-user inactivity splitting; `daily_funnel` | Excludes pure product views, ignores input session ID, includes all order statuses; gap changed 30→120 minutes | [^funnel], [Q042](q042_job_versions.json) |

# 5. System

The inspected architecture is **FastAPI → serving Postgres → batch output tables / Redash**, with a **manual Postgres-to-BigQuery backfill** and exported logs for investigation. Redash's data source is PostgreSQL (`type=pg`), so dashboard SQL's `analytics.*` names are Postgres schema names, not the warehouse dataset names. Current warehouse names are `novamart.*`, `novamart_analytics.*`, and `novamart_logs.*`. [^app] [^db] [^backfill], [Redash data source](redash_data_sources.json), [App catalog](tables_novamart.json), [Analytics catalog](tables_novamart_analytics.json), [Log catalog](tables_novamart_logs.json)

```text
Product / cart / payment callbacks
  -> users, products, cart_items, orders, order_lines, payments
       -> daily_report + intraday_report -> report snapshots -> executive revenue
       -> monthly_statement -> statements -> overrides -> corrected -> chargebacks -> final
       -> fraud_score -> status 6 -> changes paid-only metrics
       -> affinity_v2 -> scores -> similar widget -> decision log -> model_train -> model_scores
       -> trending -> latest ranked list -> similar fallback
       -> funnel / kpi / top_sellers / price_suggest / reorder_forecast / digest

Serving Postgres -- manual CSV export / replace load --> BigQuery tables
App/job/SQL logs ------------------------------------> BigQuery log datasets
Redash ---------------------------------------------> PostgreSQL queries
```

Each edge above is established by the named readers/writers, not by an orchestrated dependency graph: the Airflow files wrap individual jobs, and there are no declared upstream DAG dependencies. [^daily] [^intraday] [^monthly] [^fraud] [^affinity2] [^similar] [^train] [^trending] [^funnel] [^kpi] [^top] [^price] [^reorder] [^digest] [^backfill] [^schedules]

Operationally important findings: cron is retired; Airflow schedules lack an explicit timezone; the former 17:00 intraday run is absent from the pinned Airflow wrapper; the backfill wrapper omits mandatory CLI arguments; and the pinned exporter maps analytics tables to `analytics`, whereas the observed warehouse dataset is `novamart_analytics`. These are concrete extension/rebuild concerns detailed in Appendix E. [^schedules] [^backfill] [^manifest], [Analytics catalog](tables_novamart_analytics.json)

# 6. Data

The inspected warehouse contains **12 app tables**, **20 analytics tables plus 4 views**, and **3 log tables plus a normalized-query view**. Representative counts are **9,127 order headers**, **2,284 order lines**, **9,361 payments**, **38,950 users**, **81,018 products**, and **667,850 recommendation decisions**. This is the observed snapshot, not a claim of live production cardinality. [App catalog](tables_novamart.json), [Analytics catalog](tables_novamart_analytics.json), [Log catalog](tables_novamart_logs.json), [order metadata](metadata_novamart_orders.json), [line metadata](metadata_novamart_order_lines.json), [payment metadata](metadata_novamart_payments.json), [user metadata](metadata_novamart_users.json), [product metadata](metadata_novamart_products.json), [decision metadata](metadata_novamart_analytics_rec_decision_log.json)

The primary join keys are `orders.id → payments.order_id / order_lines.order_id`, numeric `users.id → orders.user_id / cart_items.user_id`, `products.id → product_id`, and `accounts.account_id → account_map.account_id → uid`. Multiple child rows make naive order/payment/item joins multiply money. Product reporting must use lines **or** the no-lines header fallback, not both. [^orders] [^accounts], [Q014](q014_item_grain.json), [^R9]

History and state must be kept separate: statements and reports preserve run snapshots; orders store only current status; payments record movements; product metadata is mutable; affinity/model/reorder/price tables are rebuilt; decision logs are append-only in the code. Current order state cannot by itself recreate a previously published month or prior model batch. [^monthly] [^daily] [^orders] [^gateway] [^catalog] [^affinity] [^affinity2] [^train] [^reorder] [^price] [^similar]

Two particularly consequential data-quality findings are **130 repeated legacy payment references** and **future-dated taxonomy history**: all six history mappings currently have `valid_from=2026-08-13`, despite a 2019 insertion log using `CURRENT_DATE`. Preserve these observations rather than silently changing the dates or deleting duplicate orders. [Q074](q074_payment_duplicate_details.json), [Q029](q029_taxonomy.json), [Q032](q032_db_historical_repairs.json)

# 7. Experimentation

**Observed ML operation is stronger evidence for “the jobs run” than for “the recommendations improve business outcomes.”** The active widget is v2; 17 v4 training records exist, but no observed v4 serving traffic exists, and its current rankings duplicate v2. The inspected training code has no holdout/evaluation path, candidate-conditioned predictor, or bounded recommendation-purchase label. [^flags] [^similar] [^train], [Q036](q036_model_registry.json), [Q060](q060_app_score_reads.json), [Q062](q062_score_ranks.json)

The deterministic 5% user random arm is useful infrastructure, but its catalog pool is the **first 500 eligible product IDs**, not the entire catalog; its decision log lost **1,372 random serves over December 17–19** while app serve events continued. Exclude or explicitly repair that period before training/evaluation claims. A further one-row app/decision discrepancy on December 11 is visible and remains unexplained. [^similar], [Q039](q039_random_pool.json), [Q059](q059_rec_gap.json), commits `30e8907`, `a00f24c` in [definition history](git_definition_history.txt)

A deliberately limited **descriptive proxy**, using first observed exposure during December 20–27 UTC and any paid order in the next 24h, yields **9/475 random users (1.89%)** versus **256/9,532 exploit users (2.69%)**. This is **not a recommendation-attributed lift estimate**: exploit combines model and fallback, outcomes need not involve served products, current paid status is used, and repeated impressions/eligibility are not experimentally normalized. It illustrates a reproducible diagnostic, not a rollout justification. [Q070](q070_experiment_proxy.json), [^similar] [^orders]

Suggested evaluation contract: user-level assignment, a recorded eligible candidate set and item propensity, request/session identifier, serving source/version/cache epoch, bounded item-specific purchase outcomes, mature outcome windows, and reporting of coverage/fallback/test-SKU leakage alongside conversion or net-value outcomes. Those suggestions address the observed logging, restricted-pool, unbounded-label, and fallback contamination mechanisms. [^similar] [^train] [^affinity2], [Q059](q059_rec_gap.json), [Q064](q064_rec_bad_items.json)

# 8. Glossary

| Term | Meaning in these systems | Evidence |
|---|---|---|
| Order | Header keyed by `orders.id`; may aggregate several callbacks/items | [^orders], [Q014](q014_item_grain.json) |
| Item / unit | One order-line row, or one legacy no-lines header; no quantity column | [line schema](metadata_novamart_order_lines.json), [^R9] |
| Payment | Gross/fee/net movement tied to an order; positive callback payment or negative gateway refund | [^orders] [^gateway] |
| Payment reference | Gateway callback identity; unique in newer non-null payment references and lines, but historical order-header duplicates remain | [^orders], [Q013](q013_integrity.json) |
| Gross / fee / net | Merchandise amount / collected processor fees / gross minus fees in monthly statements | [^monthly] |
| Published / corrected / final | Original snapshot / monthly override layer / override layer minus original-month chargebacks | [Q001](q001_statements.json), [Q002](q002_views.json), [Q004](q004_statement_layers.json) |
| Refund | Ambiguous: status cancellation/refund or actual negative gateway payment; `refunds_unified` includes all three kinds | [Q008](q008_refunds.json), [Q016](q016_statement_history_sql.json) |
| Held | Status `6`, assigned by the fraud heuristic; not necessarily an unpaid order | [^fraud], [Q011](q011_payment_order_month.json) |
| Active customer | Consumer-specific order/activity definition; always name its consumer and window | [^kpi] [^R3] [^R7] [^funnel] |
| Signup | `users.created_at` is first-seen bootstrap; `accounts.created_at` records registration beta creation | [^catalog] [^accounts] |
| Contactable | Opt-in and eligible email in `contactable_users`; stricter than the digest's email filter | [Q016](q016_statement_history_sql.json), [^digest] |
| Sentinel `-1` | Too little pair evidence, not dislike; serving filters negative scores | [^affinity] [^affinity2] [^similar] |
| Intended / effective version | Flag-selected target / actual path; legacy fallback rows still report effective `1.0.0` | [^similar], [Q034](q034_rec_summary.json), commit `f1217a8` in [definition history](git_definition_history.txt) |
| `rec_source` | Actual source (`affinity`, `model`, `fallback`, `random_arm`); `model` includes the heuristic v2 path | [Q034](q034_rec_summary.json), [^similar] |
| Random arm | Stable user-hash assignment with seeded shuffled lists from a restricted candidate pool | [^similar] |
| Trending | Paid order-header popularity, 30-day lookback, last-sale recency decay, min 5 units, top 50 | [^trending] |
| Reorder hint | `int(15.6 + 162.4 / (velocity + 1.8))`; advisory output, not learned forecast | [^reorder] |
| Shadow pricing | Nightly suggestions that are not read by the inspected app | [^price], [Q055](q055_price_reader_counts.json) |
| Snapshot batch | Rows sharing one run's `created_at`; dashboard readers select latest per report day | [^daily] [^intraday] [^R2] [^R7] |
| `analytics` | Postgres schema used by code/Redash; warehouse counterpart observed as `novamart_analytics` | [Redash source](redash_data_sources.json), [Analytics catalog](tables_novamart_analytics.json), [^backfill] |

# Appendix A. Finance: answering “what was revenue in this month, and why?”

## A1. Source-of-truth decision tree

1. **Historical publication requested:** use `novamart.statements`, retaining `created_at` to identify the publication/run. The job appends, and the schema has no month uniqueness constraint; do not sum repeated publications or assume a single row forever. [^monthly] [^schema], [Q001](q001_statements.json)
2. **Current finance answer requested:** use `novamart_analytics.statements_final`, as prescribed by the restatement policy and consumed by Redash query 5. Carry month, gross, fee, net, and order count. [^policy] [^R5], [Q004](q004_statement_layers.json)
3. **Explain a discrepancy:** show published → override/corrected → original-month chargebacks → final. `statement_corrections` is an audit reason/delta table, not a view automatically applied to the finance number. The observed November correction delta is **0.00**; October's replacement values are in `statement_overrides`. [Q005](q005_overrides.json), [Q006](q006_corrections.json), [Q002](q002_views.json)
4. **Cash movement requested:** separately aggregate `payments` by payment timestamp; do not label this the statement net. Status-only refunds leave historical payment rows intact, whereas gateway refunds add negative rows. [^orders] [^gateway], [Q010](q010_payment_month.json)
5. **A month has no statement:** distinguish unpublished from zero. Only September–November statement rows exist in this snapshot. December order/payment diagnostics are available, but an approved December statement is not. [Q001](q001_statements.json), [Q009](q009_orders_by_status.json), [Q010](q010_payment_month.json)

## A2. Verified statement values

| Eastern order month | Published gross | Published fee | Published net | Published orders | Current final gross | Current final fee | Current final net |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2019-09 | 2,702.00 | 78.36 | 2,623.64 | 12 | 2,702.00 | 78.36 | 2,623.64 |
| 2019-10 | 1,230,332.43 | 35,679.64 | 1,194,652.79 | 3,765 | 1,226,764.86 | 35,679.50 | 1,191,085.36 |
| 2019-11 | 1,101,397.01 | 32,110.92 | 1,069,286.09 | 3,582 | 1,101,397.01 | 32,110.92 | 1,069,286.09 |

Every value in this table comes from `statements` and `statements_final`; final order counts remain the published counts. [Q001](q001_statements.json), [Q004](q004_statement_layers.json)

**October reconciliation:** [Q001](q001_statements.json), [Q004](q004_statement_layers.json), [Q005](q005_overrides.json), [Q007](q007_chargebacks.json)

```text
Published net                         1,194,652.79
Fee correction (+0.14 to net)                  0.14
Corrected net                         1,194,652.93
Booked original-month chargebacks        -3,567.57
Final restated net                    1,191,085.36
```

The October override was logged on **2019-11-02 14:00 UTC** (`nvm-dbq-0000374529`), and the final view/chargeback backfill on **2019-12-09 15:00 UTC** (`nvm-dbq-0002221779`, `nvm-dbq-0002221780`). Chargebacks are **734.81**, **940.82**, and **1,891.94** on orders `55`, `46`, and `49`; their `reported_at` is December 1, but final reporting attributes them to October. [Q005](q005_overrides.json), [Q007](q007_chargebacks.json), [Q016](q016_statement_history_sql.json)

**Residual September issue:** collected payment fees total **78.37**, versus published/final **78.36**. The mismatch log reports `delta=-0.01`; no September override exists in the inspected override table. Do not invent a restatement just because recomputing collected fees gives a one-cent different answer. [Q010](q010_payment_month.json), [Q005](q005_overrides.json), [Q056](q056_fee_warnings.json)

## A3. Orders, payments, idempotency, and multi-item changes

Originally each callback inserted an order/payment pair. Commit **`b676969` (October 15)** added payment-reference locking and replay detection; **`8f19718` (October 28)** restricted replay reactivation to status `0` and established cancellation status `2`; **`5d1300d` (November 22)** introduced recent same-session grouping and per-reference line/payment uniqueness. These changes prevent new replay duplicates; they do not erase preexisting rows. [Definition history](git_definition_history.txt), [^orders]

At the pin, the callback locks both session and reference, searches header and line references, adds a missing payment if needed, and reuses the matching order. A new reference can append to the same user's session if a line is within the prior 15 minutes and the order is not cancelled/refunded. Appending increases header price, inserts one line and payment, and sets status back to `1`; the merge eligibility check does **not** exclude status `6`. This is a possible hold-reactivation mechanism, not evidence that every held order was reactivated. [^orders]

The snapshot has **2,059 headers with lines**, **2,284 lines**, and **173 multi-product headers**; all those headers match their summed line prices. **225** append events are logged. Headers keep their original product and creation time even when another product/time is appended, which affects product attribution and month/day boundaries if the header is used directly. [Q014](q014_item_grain.json), [Q057](q057_status_events.json), [^orders]

Legacy duplication remains: **130 repeated header payment references** cover **285 rows**, **106,943.01** summed header gross, and creation times before the October 15 fix. That is total gross on repeated-reference groups, **not** an automatically justified amount to subtract. Reconcile only warns on duplicate refs, excludes status `5`, and returns at most 200 sorted refs; it neither deduplicates orders nor reverses payments. The snapshot has no orphan payments, no duplicated non-null payment references, and no `gross-fee != net` payment rows. [Q074](q074_payment_duplicate_details.json), [Q013](q013_integrity.json), [^reconcile]

## A4. Fee history and warning interpretation

| Change | Actual behavior | Evidence |
|---|---|---|
| Initial fee | Each payment callback: `round(price * 0.029, 2)`; statement: round aggregate gross × rate | Commit `2da4141`, [definition history](git_definition_history.txt) |
| November 2 statement fix | Statement fee becomes `SUM(payments.fee)` for selected orders, avoiding sum-of-rounded versus rounded-sum mismatch | Commit `a92c96d`, [definition history](git_definition_history.txt), [Q005](q005_overrides.json) |
| November 20 processor change | Callback fee becomes `round(price * 0.029 + 0.30, 2)` per payment transaction | Commit `12e1c68`, [definition history](git_definition_history.txt), [^orders] |
| December 2 expected-fee fix | Statement warning expectation uses an Eastern November 20 cutoff, with flat fee on later headers | Commit `4a58d17`, [^monthly], [definition history](git_definition_history.txt) |

On December 1 the November warning showed expected **31,940.51**, collected **32,110.92**, delta **-170.41**. The published November fee was already the **collected** amount, and the later audit correction is **0.00**. A warning about the comparison formula did not mean the published fee was wrong. [Q001](q001_statements.json), [Q006](q006_corrections.json), [Q056](q056_fee_warnings.json)

The pinned expected-fee calculation still operates on **order headers**, whereas actual fees are charged per payment callback. On multi-item headers, an extra flat charge per transaction and separate rounding can differ from one charge on the summed header. Use collected fee rows as authority and the expectation as a diagnostic. [^monthly] [^orders], [Q014](q014_item_grain.json)

## A5. Status/refund history and what finance does not automatically restate

Status meanings established by code/history are `0` pending, `1` paid, `2` cancelled, `3` refunded, and `6` fraud-held. An initial unused cancellation constant was `4` before October 28; reconcile's `status<>5` references a special exclusion without a producer/meaning established by the inspected current code. Avoid assigning a business meaning to `5` without additional evidence. [^constants] [^orders] [^fraud] [^reconcile], commits `2da4141`, `8f19718`, `d87cb3d` in [definition history](git_definition_history.txt)

The cancellation and refund endpoints update order status/time; they do not insert negative payments. Gateway refund, introduced December 5 (`c49a7bb`), inserts `gross=-amount, fee=0, net=-amount` and does not change order status. It has no deduplication key or replay check in the inspected code. [^orders] [^gateway], [History](git_history.txt)

The unified refund view added December 23 (`a3bffec`) uses `UNION ALL` of current status `2/3` headers at `updated_at` and negative payments at payment `created_at`. It does not deduplicate the same economic event across mechanisms; status rows are full header prices, and a cancellation need not be a cash refund. No cross-mechanism overlap exists in the current data, but that is a snapshot observation rather than a guaranteed invariant. [Q016](q016_statement_history_sql.json), [Q015](q015_refund_overlap.json), [^R1]

| Refund event month | Status cancellation events / amount | Status refund events / amount | Gateway refund events / amount | Official mixed total |
|---|---:|---:|---:|---:|
| 2019-11 | 24 / 6,511.32 | 8 / 3,180.45 | 0 / 0.00 | 32 / 9,691.77 |
| 2019-12 | 30 / 6,738.32 | 20 / 10,267.02 | 9 / 1,843.59 | 59 / 18,848.93 |

The source for all event counts/amounts and the summed totals is [Q008](q008_refunds.json); its event-month grouping reproduces [Redash query 1](redash_query_1.json).

Today's October `status=1` headers total **1,206,337.32 across 3,695 orders**, not published gross **1,230,332.43 across 3,765**. The difference is **70 later cancelled/refunded orders** with **23,995.11** gross. Current October paid-order payment net is **1,169,510.12**, also reflecting **1,843.59** in later gateway refunds. The approved final statement is still **1,191,085.36**, because its definition starts with snapshots and applies explicit overrides/chargebacks, not current order-state/payment recomputation. [Q009](q009_orders_by_status.json), [Q011](q011_payment_order_month.json), [Q001](q001_statements.json), [Q004](q004_statement_layers.json)

For December, current paid-header gross is **552,328.93**, with **12 held headers / 40,213.29** excluded. Calendar payment movements instead total **590,698.63 gross**, **17,772.15 fee**, and **572,926.48 net**, including held-order payments and nine negative refund movements. Those are meaningful diagnostics, not an approved missing December statement. [Q009](q009_orders_by_status.json), [Q010](q010_payment_month.json), [Q011](q011_payment_order_month.json), [Q001](q001_statements.json)

## A6. Read-only monthly reconciliation recipe

For a published/current answer, run the source-layer query below, changing the month literal. A missing row means the month is not present in this source; no zero-filling is implied. This pattern is a parameterized form of the verified [Q001](q001_statements.json) and [Q004](q004_statement_layers.json); the exact recipe was also executed successfully as [Q084](q084_monthly_recipe.json).

```sql
SELECT 'published' AS source, month, gross, fee, net, orders_count, created_at
FROM `novamart-warehouse.novamart.statements`
WHERE month = '2019-10'
UNION ALL
SELECT 'corrected', month, gross, fee, net, orders_count, created_at
FROM `novamart-warehouse.novamart_analytics.statements_corrected`
WHERE month = '2019-10'
UNION ALL
SELECT 'final', month, gross, fee, net, orders_count, created_at
FROM `novamart-warehouse.novamart_analytics.statements_final`
WHERE month = '2019-10';
```

For an explanatory **current-state diagnostic**, aggregate payments by order before joining to avoid multiplication, and use two Eastern month boundaries converted to UTC. This follows the pinned statement selection/fee reader but adds payment gross/net to expose movements; it is not a historical reconstruction. The exact recipe was executed successfully as [Q085](q085_monthly_diagnostic_recipe.json). [^monthly] [^time], [Q011](q011_payment_order_month.json)

```sql
WITH bounds AS (
  SELECT
    TIMESTAMP(DATETIME '2019-10-01 00:00:00', 'America/New_York') AS start_at,
    TIMESTAMP(DATETIME '2019-11-01 00:00:00', 'America/New_York') AS end_at
), payment_by_order AS (
  SELECT order_id, COUNT(*) AS movements,
         SUM(gross) AS movement_gross, SUM(fee) AS fee, SUM(net) AS movement_net
  FROM `novamart-warehouse.novamart.payments`
  GROUP BY order_id
)
SELECT o.status, COUNT(*) AS order_headers, SUM(o.price) AS order_gross,
       SUM(p.movements) AS payment_movements,
       SUM(p.movement_gross) AS movement_gross,
       SUM(p.fee) AS collected_fee, SUM(p.movement_net) AS movement_net
FROM `novamart-warehouse.novamart.orders` o
CROSS JOIN bounds b
LEFT JOIN payment_by_order p ON p.order_id = o.id
WHERE o.created_at >= b.start_at AND o.created_at < b.end_at
GROUP BY o.status
ORDER BY o.status;
```

# Appendix B. Product reports, revenue dashboards, and definition history

## B1. The common item relation

The official item-based dashboard/report relation is: all lines joined to their header for user/status, **union all only headers with no lines**. Line price/time belongs to the item; header price/time belongs to the grouped order. This avoids dropping old orders and avoids double-counting both a header and its lines. There is no quantity column, so one row is one reported unit. [^daily] [^intraday] [^R6] [^R8] [^R9], [line schema](metadata_novamart_order_lines.json)

```sql
WITH item_orders AS (
  SELECT o.id AS order_id, o.user_id, o.status,
         ol.product_id, ol.price, ol.created_at
  FROM `novamart-warehouse.novamart.orders` o
  JOIN `novamart-warehouse.novamart.order_lines` ol ON ol.order_id = o.id
  UNION ALL
  SELECT o.id, o.user_id, o.status, o.product_id, o.price, o.created_at
  FROM `novamart-warehouse.novamart.orders` o
  WHERE NOT EXISTS (
    SELECT 1 FROM `novamart-warehouse.novamart.order_lines` ol
    WHERE ol.order_id = o.id
  )
)
SELECT product_id, COUNT(*) AS units, SUM(price) AS revenue
FROM item_orders
GROUP BY product_id;
```

The SQL above is the grain-only form of the relation verified by [Q048](q048_product_dashboard.json); add the intended consumer's window/status/QA/product rules, not a shared assumed “clean sales” filter.

## B2. Why similarly named product surfaces disagree

| Surface | Grain / window / ranking | Exclusions and caveats | Evidence |
|---|---|---|---|
| Executive best sellers, query 9 | Item relation; rolling 7 days; revenue desc; limit 20 | Exclude QA `424242` and brands Lucente/Jetem. No paid-status or two-SKU exclusion. | [^R9] |
| Nightly `top_sellers` → `top_products` | Header count; yesterday Eastern calendar day; units desc, product ID tie-break; top 50 | `status=1`; no QA/brand/SKU cleaning; appended rows | [^top] |
| Nightly trending → `trending_daily` | Header paid counts over 30 days; min 5; `units*exp(-0.05*age_since_last_sale)`; top 50 | No line expansion or cleanup; same-day output replaced; fallback reads latest available day | [^trending] [^similar] |
| Executive brand, query 8 | Item relation; rolling 30 days; revenue desc | No status or SKU exclusion; current product brand; QA ID strings | [^R8] |
| Executive category, query 6 | Item relation; rolling 30 days; revenue desc | No status or SKU exclusion; as-of name map but current product category | [^R6] |
| `/reports/brands` implementation | Headers; requested Eastern calendar month; `status=1`; revenue desc then brand | Excludes test SKUs and brands, **not QA user**; blank brand → `unbranded`; grouped headers misattribute appended-item revenue | [^reports] |

The reports router exists, but the pinned `app.py` does not include it. The same mounting discrepancy exists for the accounts and user-email routers, despite observed historical account/email-update events. Treat their code as implementation evidence and logs/tables as historical execution evidence, not proof those endpoints are exposed by this pinned app entrypoint. [^app] [^reports] [^accounts] [^users], [Q057](q057_status_events.json)

At an explicit **2020-01-01 00:00 UTC** rolling-window anchor, best sellers are headed by product `1005116` (**6 units / 5,889.81**) and `1005115` (**6 / 5,325.55**). Third-ranked `1005284` is **2 units / 5,096.14**, both non-paid under the current status. Excluded-by-report SKU `1002544` still appears in the dashboard with **10 / 4,498.52**, proving that report SKU exclusions are not dashboard SKU exclusions. [Q048](q048_product_dashboard.json), [^constants] [^R9]

At the same anchor, rolling brand revenue leads with Apple **236,606.73** and Samsung **128,113.51**; blank brand contributes **17,585.39**. Category totals are electronics **437,887.95**, other **93,558.92**, appliances **30,208.94**, construction **3,713.01**, apparel **3,663.34**, and kids **617.89**. These are reproduced merchandise sums under current dimensions, including held items, not fee-netted finance numbers. [Q049](q049_brand_dashboard.json), [Q067](q067_category_dashboard.json), [^R6] [^R8]

## B3. Catalog, brand, and category lineage

Product creation originally used `ON CONFLICT DO NOTHING` with known-ID caches; first-seen products could have blank metadata. Commit **`ea0e97b` (October 21)** added blank-brand repair, **`d213f6e` (November 9)** made the price feed upsert existing products, and **`795d273` (November 15)** added price history. The current product-view repair updates blank brand/title but not category; full feed upserts replace nonblank dimensions and price/cost/stock. [^catalog], [History](git_history.txt)

The forensic `blank_brand_products` snapshot contains **5,972 products**, with **204 counted header orders / 38,499.83 revenue**, split into missing-first-seen-metadata and insert/cache non-repair causes. Current catalog blank brands number **17,442**, so that diagnostic snapshot is not today's inventory and not an automatic reclassification table. Its `captured_at` is in 2026 even though the corresponding creation SQL is logged on October 21, 2019. [Q030](q030_blank_brand_snapshot.json), [Q031](q031_brand_counts.json), [Q032](q032_db_historical_repairs.json)

Category mapping was introduced in **`2814b3d` (November 30)**, then made versioned in **`33054cd` (December 12)**. Query 6 combines `category_names` with history, selects the latest `valid_from <= item.created_at::date`, and prioritizes history on same-date ties. This preserves mapping history but not historical product categories. The cast inherits the Postgres session timezone; the query does not explicitly make it Eastern. [^R6], [Taxonomy change](git_taxonomy_fix.txt), [History](git_history.txt)

The December 12 log (`nvm-dbq-0002395860`) records `CURRENT_DATE` for new `lighting` and `entertainment` labels. The inspected six history rows are actually dated **2026-08-13**, while base mapping dates range across 2019. Consequently those new labels are **not eligible for any 2019 item** in the current snapshot; the reproduced 2019 category totals contain no lighting/entertainment group. This is an observed historical reproducibility anomaly, not grounds to silently backdate the table. [Q029](q029_taxonomy.json), [Q050](q050_category_dates.json), [Q032](q032_db_historical_repairs.json), [Q067](q067_category_dashboard.json)

## B4. Daily report history: technical fixes versus business-policy changes

| Date / commit | Change and its reporting consequence | Evidence |
|---|---|---|
| Sep 15, `2da4141` | Exclude pending only; scan first 500 eligible rows; no SKU/brand cleanup | [Definition history](git_definition_history.txt) |
| Oct 8, `83fb3ed` | Hide products `1004856`, `1002544` in daily report | [Definition history](git_definition_history.txt) |
| Oct 25, `ba1fbfa` | Hide Lucente per partnerships in daily report / report API constant | [Definition history](git_definition_history.txt) |
| Nov 5, `102c9b4` | Correct DST window by converting both local midnights independently | [DST fix](git_dst_fix.txt), [Q072](q072_report_history_log.json) |
| Nov 18, `11c0a42` | Exclude cancelled/refunded statuses as well as pending | [Definition history](git_definition_history.txt) |
| Nov 19, `1233af8` | `fetchmany(500)` → `fetchall`; eliminate busy-day truncation | [Definition history](git_definition_history.txt), [Q077](q077_report_scan_cap.json) |
| Nov 27, `b59f077` | Report excludes `analytics.test_users`; executive order dashboards exclude numeric QA user | [Definition history](git_definition_history.txt), [Q032](q032_db_historical_repairs.json) |
| Dec 5, `92596dc` | Report/dashboard per-item expansion with no-lines fallback | [Definition history](git_definition_history.txt) |
| Dec 8, `a2e0013` | Intraday snapshots; KPI dashboard combines latest closed-day/today sources | [Definition history](git_definition_history.txt), [^R7] |
| Dec 15, `1169e40` | Add Jetem to report denylist and Lucente/Jetem product joins in executive dashboards | [Definition history](git_definition_history.txt) |
| Dec 24, `3eced24` | Revenue widget uses six closed days + today; latest batch only | [Definition history](git_definition_history.txt), [^R2] |

The pre-fix November 4 run covered November 3 **04:00 UTC to November 4 04:00 UTC**, rather than the correct **05:00 UTC** end for that 25-hour Eastern day. Current orders in the omitted hour are **8 headers / 2,985.99** gross, before the report's other filters; that is not necessarily the exact final report revenue shortfall. [Q072](q072_report_history_log.json), [Q078](q078_dst_missing_hour.json), [^time]

The November 18 run for November 17 logged exactly **500 scanned orders**. A current-state reconstruction of the corresponding old selection finds **735 headers**, showing why the cap could truncate a busy day. Snapshot status/dimension changes mean this reconstruction should not be mistaken for an exact historical eligible-row audit. `REPORT_SCAN_CAP=500` remains in constants but is unused by the current daily report. [Q077](q077_report_scan_cap.json), [Q082](q082_nov17_cap_population.json), [^daily] [^constants]

## B5. Snapshot blending and double counting

Report writers append every product row with a run-wide timestamp. The dashboard therefore selects **one latest batch per report date**, not one latest row per product. For prior dates it reads only completed report rows; for today it reads only the latest intraday rows. This is the intended contract even if the current full-day table happens to have no dates with multiple batches. [^daily] [^intraday] [^R2] [^R7], [Q051](q051_report_batches.json)

Using December 31 as “today,” the corrected seven-calendar-day widget is **139,598.13**. A naive union of both sources for the same seven dates returns **371,872.10**; the old `CURRENT_DATE-7` query additionally includes an eighth date and returns **410,387.39**. This combines overlapping historical intraday snapshots and full-day totals; it is not evidence of additional sales. [Q052](q052_revenue_widget_repro.json), [Q053](q053_revenue_widget_bug.json), [Q075](q075_widget_total.json), commit `3eced24` in [definition history](git_definition_history.txt)

December 31 daily KPIs reproduce **60 item units / 18,202.09 revenue**, alongside **54 distinct ordering users / 0 contactable ordering users**. The revenue comes from the latest partial snapshot, whereas customers come from orders under their own filter; the columns are not guaranteed to share the same as-of time or eligible order statuses. Missing report dates are not generated as zero rows because the final query starts from report days. [Q068](q068_daily_report_repro.json), [Q046](q046_customer_daily.json), [^R7]

Report/status filters are `NOT IN (0,2,3)`, not `status=1`: held orders remain eligible, while monthly statements and top/trending jobs drop them. The snapshot has **19 held item rows / 40,213.29**, across 12 headers. A fraud-threshold change can move paid-only metrics without equivalently moving executive report totals. [^daily] [^monthly] [^top] [^trending] [^fraud], [Q054](q054_held_exposure.json)

# Appendix C. Customer identities, segments, and consumers

## C1. First-seen users versus registered accounts

The user bootstrap assigns `user{uid}@example.com`, first-seen timestamp, and deterministic attributes synthesized from the ID. Product views, carts, and orders can all create users; therefore counts of `users.created_at` are first-seen visitors/shoppers, not proof of explicit account signups. Attributes such as region/channel/device/opt-in are synthesized here, so segment analyses must not portray them as independently observed customer declarations. [^catalog] [^carts] [^orders] [^profile]

Observed first-seen monthly user counts are **74** September, **15,045** October, **11,302** November, and **12,529** December; all sum to **38,950**. There are **24,193 opt-in users**, but **38,910** still have `@example.com` emails. [Q018](q018_signup_month.json), [Q017](q017_customers_snapshot.json)

Account creation added November 27 (`b567d9d`) generates a UUID, reads the numeric user's current email, and writes `account_map`. There is no email-unique constraint or idempotent account-creation check in the inspected implementation. The snapshot nevertheless has **30 accounts**, **30 distinct account emails**, **30 map rows**, and complete agreement between email/map matches. Historical account events were all logged on December 1. [^accounts], [Q020](q020_account_identity.json), [Q057](q057_status_events.json), [History](git_history.txt)

The December 10 registration dashboard originally tried to compare UUID and numeric namespaces; **`b975479` (December 21)** changed it to account-email → users → orders. Query 4 now returns **30 registered buyers**, **18,155.71 registered revenue**, and the warehouse reproduction finds **74 paid headers**. It includes pre-enrollment purchases, includes QA, and is not an actual conversion rate. `account_map` is an explicit bridge useful for diagnosing future email-change/duplicate-email issues, but the official query currently uses email. [^R4], [Q019](q019_registered_conversion.json), [Q020](q020_account_identity.json), [definition history](git_definition_history.txt), [^users] [^accounts]

The UUID `cc27b436-d6f9-4e84-adaf-e716025dd369` was created for numeric QA user `424242` (`nvm-app-0000914194`). Query 8 hard-excludes both strings, but warehouse order user IDs remain integers and there is no observed UUID order-ID namespace to exclude directly. Use the bridge for registered analyses rather than casting identifiers together. [Q073](q073_qa_and_hiding.json), [^R8], [order schema](metadata_novamart_orders.json), [^accounts]

## C2. Active customers and zeroes that are not business zeroes

| Consumer | Window | Eligibility | Snapshot / reproduction |
|---|---|---|---|
| Nightly `kpi_daily` | Run-time trailing 30 days | Paid status 1; no cleaning | Last stored Dec 31 rollup: **1,152** |
| Nightly definition at Jan 1 00:00 UTC on current snapshot | Trailing 30 days | Paid status 1; no cleaning | **1,146** |
| Broad board candidate definition, same anchor | Trailing 30 days | Not statuses 0/2/3 | **1,151**, before email/QA cleaning |
| Official board cleaning, same anchor | Trailing 30 days | Above + test-user/email exclusions | **0** |
| Daily executive ordering users | Eastern day, Dec 31 | No status filter; QA and Lucente/Jetem removed | **54** |

These figures are sourced from [Q021](q021_kpi_history.json), [Q045](q045_active_comparison.json), [Q044](q044_board_snapshot.json), and [Q046](q046_customer_daily.json), with the consumer contracts in [^kpi], [^R3], and [^R7]. Stored rollups and later current-state reconstructions have different anchors and potentially different order states; their difference is not itself a failed job.

All 40 non-placeholder emails use **`gmail.example`**; 23 of those users opt in, but the trusted view rejects `%.example`. Thus both the **contactable population** and the official cleaned **board active population** are zero in this dataset because of definitions, despite substantial order activity. Interpreting either as “the company has no customers” would be wrong. [Q047](q047_contactable_exclusions.json), [Q017](q017_customers_snapshot.json), [Q044](q044_board_snapshot.json), [Q009](q009_orders_by_status.json), [Q016](q016_statement_history_sql.json)

The board excludes exact domains `novamart.com`, `example.com/net/org`, suffixes `.example/.test`, prefixes `internal./test.`, and tokenized QA/test/demo/internal/seed/sandbox/smoke patterns in localparts/domains. It is a left join to users: a missing user's email becomes blank and can pass, so it is not intrinsically a “verified customer” count. The daily executive series instead uses the header product for brand filtering, even on multi-product headers. [^R3] [^R7] [^orders]

## C3. Funnel and digest discrepancies

`daily_funnel` reads surviving `cart_items` plus headers in the previous 24 hours, not product-view events or historical cart removals; cart removal deletes rows. It sessions by **user + inactivity gap**, ignoring the supplied session identifier. Pure browsers are absent, orders of every status count, and the run's date labels a rolling window rather than yesterday's Eastern calendar day. [^funnel] [^carts]

The gap changed **30→120 minutes** in `f915c1b` on December 14. Logs retain 30-minute behavior through December 14 and start 120-minute behavior December 15. This can reduce sessions per active user without reducing users; a larger active-user jump afterward cannot be attributed to the gap parameter alone. [Q042](q042_job_versions.json), [Q022](q022_funnel_history.json), [Batch history](git_batch_history.txt)

The digest's docstring says “contactable,” but its actual recipient selection is only `email NOT LIKE '%@example.com'`: no opt-in, validation, or trusted-view join. It selects one most frequent paid **header product** over seven days, without QA/brand/SKU exclusions. The code records `digest_sent`/`digest_log`; it contains no mail-delivery call, so that log does not prove real delivery or engagement. [^digest]

Flag handling evolved from the wrong `DIGEST_ON` setting (`c19a307`) to `ENABLE_DIGEST` precedence (`8dc520b`), then direct reading of `deploy/cron.env` (`0bd4eac`). Observed digest outputs start **December 17**, after the December 16 direct-file fix; there are **15 logged batches of 40 recipients**, even though the trusted contactable view is zero. Early top products include the excluded test SKUs. [^digest] [^cronenv], [Q023](q023_digest_history.json), [Batch history](git_batch_history.txt)

# Appendix D. Recommendations, learning, serving, and experimentation

## D1. Version timeline: writer, intended version, actual source

| Stage | Implementation / observed change | Evidence |
|---|---|---|
| Oct 12, `776d674` | Legacy co-cart affinity nightly writer begins; table `product_affinity` | [^affinity], [History](git_history.txt), [Q042](q042_job_versions.json) |
| Oct 26, `f1217a8` | Similar widget v1 reads legacy affinity; empty scores fall back to seven-day paid-header popularity directly | [Definition history](git_definition_history.txt), [Q080](q080_rec_rollout_times.json) |
| Nov 12, `fef5c96` | Require at least 3 pair observations; low-data score becomes `-1` | [^affinity], [History](git_history.txt) |
| Dec 2, `89666bf` | Conversion-weighted affinity v2 writer with seasonal factors | [^affinity2], [History](git_history.txt) |
| Dec 3–5 | V2 job crashes on missing December seasonal array element | [Q025](q025_job_errors.json) |
| Dec 5, `3dbe4d7`; observed Dec 6 | Safe season fallback to 1.0; first successful v2 refresh is Dec 6 | [^affinity2], [Q042](q042_job_versions.json), [History](git_history.txt) |
| Dec 6, `df4ed85` | Serving switches v1→v2 at **16:40 UTC**, adds hash-assigned random collection arm, uses trending fallback | [^similar], [Q080](q080_rec_rollout_times.json), [Q060](q060_app_score_reads.json) |
| Dec 14, `a1946ff`; observed Dec 15 | V4 training begins; registry/score outputs, behind flag | [^train], [Q036](q036_model_registry.json), [History](git_history.txt) |
| Dec 17, `30e8907` | Random-arm early return loses database decision logging | [Definition history](git_definition_history.txt), [Q059](q059_rec_gap.json) |
| Dec 19, `a00f24c` | Random decision logging restored; six-hour cache added | [Definition history](git_definition_history.txt), [Q059](q059_rec_gap.json) |
| Dec 26, `8ed2971` | Cache epoch invalidation, key includes table, latest-score-epoch reads, no empty-list caching | [^similar], [Definition history](git_definition_history.txt) |

Serving `2.0.0` selects v2 rows stamped `2.0.1`; those version strings have different roles. V1's log format kept effective `1.0.0` even on fallback, whereas later fallback uses effective `fallback`. Always combine `intended_version`, `effective_version`, `rec_source`, and `arm`; an effective-version-only query misclassifies older fallback as model service and random v2 traffic as v2-ranked service. [^similar] [^affinity2], [Q034](q034_rec_summary.json), commit `f1217a8` in [definition history](git_definition_history.txt)

The current enum retains `1.0.0`, but the dispatch is simply `2.0.0 → affinity_v2`, **everything else → model_scores**. It does not validate flags or restore the legacy v1 reader. Pointing the flag at `1.0.0` is therefore not a valid rollback to old affinity under this pin. Aliases for `2/v2` and `4/v4/model4` are normalized; a missing flag file defaults to `2.0.0`. [^similar]

## D2. Affinity mathematics and limitations

Legacy affinity self-joins surviving cart rows by session and unequal product ID, using a 30-day lower bound on **c1 only**, and counts directional row pairs. Below three pairs: `score=-1`; otherwise `pairs*exp(-0.05*days_since_latest_c1)`, rounded four decimals. This is not distinct-user/session counting, and multiple cart rows can multiply pair evidence. Both session reuse across users and unbounded c2 history can contaminate a join if input session identity is not globally reliable. [^affinity] [^carts]

V2 adds conversion evidence: for c2's user/product, it checks whether **any paid header order exists**, with no condition that the order follows that cart, occurs in the same session, or lies in the scoring window. Each joined row can therefore receive conversion credit from older/unrelated purchases; appended non-header product purchases are not recognized through `order_lines`. Raw score is `(pairs + 3*conversion_rows)*decay`, ×1.15 for equal nonblank current category, ×0.7 for current price ratios outside 0.25–4, ×season. The seasonal multiplier is global within a run and does not reorder pairs by itself. [^affinity2] [^orders]

Current legacy and v2 tables each contain **3,912 pairs**, **2,964 sentinel rows**, and **1,476 bases**; only **948 nonnegative pairs across 449 bases** feed v4. Sentinel rows mean insufficient evidence, not negative customer preference. Removing the graduation gate changes coverage and confidence rather than merely removing a sign convention. [Q037](q037_score_inventory.json), [Q062](q062_score_ranks.json), [^affinity] [^affinity2]

## D3. Serving and cache behavior

The endpoint returns up to five items. The deterministic user arm is `int(sha256(str(uid))[:8],16) % 20 == 0`; random lists shuffle the first 500 non-excluded products using seed `uid:session:pid`. They may recommend the base item, do not check stock, and are uniform only over this restricted pool. Across historical changing pools, random logs expose **552 distinct products / 72,830 item impressions**, not the full **81,018-product** snapshot. [^similar], [Q039](q039_random_pool.json), [product metadata](metadata_novamart_products.json)

For exploit, scores must be nonnegative and match the table's global `MAX(updated_at)`; excluded SKUs are filtered **after** SQL limit 5, without topping up. Cache is per process, six-hour TTL, keyed `(table,pid)`; each exploit request checks the table epoch and invalidates that table's cache on a changed maximum. Epoch-query exceptions are swallowed, so a stale cache can survive until TTL if refresh checking fails. Empty lists are no longer cached. [^similar]

If no eligible scores remain, fallback reads up to five products from latest available `trending_daily.day`, with no freshness maximum, stock check, base exclusion, or test-SKU filter. A failed/empty/missing trending pipeline can therefore yield stale lists, empty lists, or query failure; successful historical responses do not prove fallback quality. [^similar] [^trending]

Observed v1 traffic: **392,630 requests**, **326,186 fallback (83.08%)**. Observed intended-v2 traffic: **275,220 requests**, **52,695 model-source**, **14,566 random**, and **207,959 fallback (75.56% overall; 79.78% of non-random requests)**. No empty list is logged in either version cohort. These are historical aggregate shares with different traffic/time windows, not a controlled improvement estimate. [Q063](q063_serving_coverage.json)

Every one of the **534,145 fallback requests** in the inspected decision table contains at least one excluded SKU. There are **27 fallback self-recommendations** and **17 random-arm self-recommendations**. Model/affinity sources show zero excluded-SKU requests. The fallback path is thus technically returning lists while violating the main score path's exclusion behavior. [Q064](q064_rec_bad_items.json), [^similar]

The December 19 cache implementation stored empty results and keyed only by base product, creating both sticky no-score fallback and possible cross-version cache reuse. Historical `fallback_reason='cache'` appears on **25,091 fallback** and **21,427 model** requests; it is cache-path metadata, not necessarily an error. The December 26 patch fixes the stated key/epoch/empty-cache mechanisms; a current `cache` reason on a successful model request is expected. [Q034](q034_rec_summary.json), [^similar], commits `a00f24c`, `8ed2971` in [definition history](git_definition_history.txt)

## D4. V4: what training actually learns and what it serves

Training reads all `arm='random'` decisions. Label is whether the same user has **any later current-paid order**, without attribution to any recommended item or a finite horizon. Older exposures have more chance to acquire a positive label; recent examples are censored, and labels can change as later orders arrive or statuses change. Current catalog prices and all-time base-product popularity are joined to old exposures rather than point-in-time features. [^train] [^orders] [^catalog]

The actual vector has **five** components: served-list size; base list price / 1,000; all-time paid-header popularity / 100; account age / 60 capped above at 1; organic-channel indicator. Stock and opt-in are fetched but unused; region/device do not appear in the vector. README's larger feature list is inaccurate. The entire inspected random sample has `n_items=5`, so the first feature is constant rather than a learned list-size treatment variation. [^train] [^readme], [Q079](q079_model_items_constant.json)

A fixed-state `LogisticRegression(solver='lbfgs', random_state=0)` is fitted when at least 20 rows and both labels exist. The writer then ignores predicted probabilities, intercept, and all weights except the first: for every nonnegative v2 pair, `v4_score = round(v2_score * (1 + 0.1*w_first), 4)`. Neither candidate features nor user context affect this rank. If training is insufficient/single-class, a registry record is appended but score refresh is skipped, leaving old scores rather than proving a fresh usable model. [^train]

The latest registry row, December 31, has **14,411 train rows**, first coefficient **-0.2448375438**, and thus factor **0.9755162456**. Current scores have approximately that ratio to v2, with rounding variation; **948/948 ranks are unchanged** under `score DESC, rec_pid` in both tables. A negative factor in a different future run could even remove model eligibility by making scores negative; the code has no guard, so a change should explicitly preserve eligible-score semantics. [Q036](q036_model_registry.json), [Q038](q038_score_scale.json), [Q062](q062_score_ranks.json), [^train]

The current whole-history random-label reproduction has **14,566 rows**, **1,934 positive**, and **12,632 negative**. This uses the end-of-snapshot order state, not the latest training run's contemporaneous data, so it should not be asserted as that run's actual training label distribution. [Q040](q040_random_label.json), [Q036](q036_model_registry.json)

## D5. Logging, experiments, and assessing whether systems work

Decision rows hold timestamp, numeric user, base product, comma-separated items, intended/effective versions, source, fallback reason, and arm. App serve events hold session and count/source/arm but not item IDs or version; the decision table has no request/session key. A precise impression→session→order attribution join is therefore weaker than the names suggest. Repeated calls with the same random seed can produce repeated identical lists. [^similar], [decision schema](metadata_novamart_analytics_rec_decision_log.json)

The December 17 early return caused app-random versus decision-random gaps of **109**, **848**, and **415** on December 17, 18, and 19. App-random December 18 is **848**, database-random **0**; the training registry row count stays **5,798** on December 18 and 19 while other features/labels change. An additional December 11 decision surplus of one row remains a separate unexplained discrepancy. [Q059](q059_rec_gap.json), [Q036](q036_model_registry.json), commits `30e8907`, `a00f24c` in [definition history](git_definition_history.txt)

**Judgments supported by the evidence:** [^train] [^similar] [^fraud] [^price] [^reorder]

- Affinity/trending refreshes and recommendation serving occur, but low coverage, sentinel volume, fallback test-SKU leakage, and unbounded conversion credit weaken a “works well” claim. [Q037](q037_score_inventory.json), [Q063](q063_serving_coverage.json), [Q064](q064_rec_bad_items.json), [^affinity2]
- V4 training exists, but no observed live v4 reader and identical rankings mean the available evidence does not demonstrate incremental v4 value. [Q036](q036_model_registry.json), [Q060](q060_app_score_reads.json), [Q062](q062_score_ranks.json)
- Fraud is a hand-defined score, not a validated fraud model in this repository; threshold changes prove different holds, not precision/recall or avoided loss. [^fraud], [Q042](q042_job_versions.json)
- Pricing suggestions run, but are not consumed by storefront serving; there is no demonstrated price experiment outcome. [^price], [Q055](q055_price_reader_counts.json)
- Reorder hints are written, but the inverse formula and lack of inventory/lead-time/error evaluation do not support finance purchase commitments. [^reorder], [Q041](q041_reorder_snapshot.json)

Suggested experiment extension: repair item-specific, bounded, mature labels and request identifiers first; compare v2 and a genuinely candidate/user-dependent v4 under stable user assignment with a documented candidate universe; assess coverage and test-SKU leakage before attributing outcome shifts to the model. For causal claims, use the assigned arm rather than post-treatment fallback/source strata as the primary comparison; retain source strata for diagnostics. This design follows directly from the current assignment, logging, score, and label defects. [^similar] [^train] [^affinity2], [Q059](q059_rec_gap.json), [Q064](q064_rec_bad_items.json)

## D6. Shadow pricing and advisory replenishment

The pricing job selects the top **500 products** by paid header-order count over 14 days using a products-to-orders left join; zero-demand products can be included if needed to fill the list. It takes the middle row's count as the median threshold, suggests **+5%** of current list price for products strictly above that count and **−5%** otherwise, rounds to cents, and replaces the prior suggestion table. There is no elasticity model, margin constraint, uncertainty estimate, or serving lookup in this path. Shadow launch was `894c535` on November 24; `cca9b0d` on December 2 explicitly held phase-2 serving. The query logs contain 37 creates/deletes and 18,500 inserts, with no SELECT from the suggestion table among the matched statements. [^price] [^catalog] [^orders], [Q055](q055_price_reader_counts.json), [History](git_history.txt)

Reorder velocity is **paid header count / 14**, for the current top 200 products. Output is `int(15.6 + 162.4 / (velocity + 1.8))`: with positive constants, larger velocity mechanically yields a **smaller** hint. Its November 26 introduction (`f5e3032`) used `K=141.12`; December 21 (`f85cdd2`) changed only K to 162.4, not the inputs, window, cutoff, or formula shape. The current output has **200 rows**, velocities **0.0714–2.7143**, and hints **51–102**. It uses neither on-hand stock nor lead time, purchase orders, seasonality, margin, or stockout corrections, and overwrites history nightly. Those properties support the existing advisory labeling, not a validated purchasing quantity. [^reorder] [^forecastdoc], [Q041](q041_reorder_snapshot.json), [Batch history](git_batch_history.txt)

# Appendix E. Scheduled jobs: outputs, dependencies, failure impact, and safe extension

## E1. Scheduler inventory at the pin

All daily Airflow wrappers contain one BashOperator, `catchup=False`, and a naive September 15 start date; none specifies timezone, cross-job dependency, task retries, or data-interval parameters. The manual backfill has a January 1 start date and `schedule=None`. The following clock times are **cron expressions in repository wrappers**, not independently verified post-migration Eastern execution times. Historical cron explicitly called its times local. [^schedules]

| Job | Pinned schedule | Inputs → outputs / downstream impact | Failure or rerun behavior | Evidence |
|---|---|---|---|---|
| `reconcile` | `0 3 * * *` | Orders → duplicate-ref warnings; finance diagnostic | Lost warnings on failure; persistent duplicates repeatedly warned, not fixed | [^schedules] [^reconcile] |
| `affinity` | `30 3 * * *` | Carts → rebuilt legacy affinity; also provisions decision table | No current widget read after v2 switch; replacement writes can leave partial table | [^schedules] [^affinity], [Q071](q071_legacy_table_consumers.json) |
| `affinity_v2` | `45 3 * * *` | Carts/orders/products → rebuilt v2 affinity → live widget + v4 trainer | Stale/partial scores, more fallback, or stale training candidates; known seasonal crash | [^schedules] [^affinity2] [^similar] [^train], [Q025](q025_job_errors.json) |
| `model_train` | `15 4 * * *` | Random decisions/users/products/orders + v2 candidates → registry + rebuilt model scores | Stale/partial model output; default v2 serving unaffected unless flag is changed | [^schedules] [^train] [^flags] |
| `price_suggest` | `45 4 * * *` | Products + 14-day paid headers → replaced top-500 shadow suggestions | Stale/partial shadow table; no observed live pricing reader | [^schedules] [^price], [Q055](q055_price_reader_counts.json) |
| `trending` | `15 5 * * *` | 30-day paid headers → day's top-50 decayed popularity | Stale latest-day fallback if no new output; partial list during rebuild | [^schedules] [^trending] [^similar] |
| `fraud_score` | `45 5 * * *` | Last-day paid headers + user age/order velocity → risk rows + status 6 | Failure leaves unscored paid orders; success changes paid-only reports | [^schedules] [^fraud] [^monthly] [^kpi] |
| `daily_report` | `0 6 * * *` | Yesterday's items/status/products/test users → append report rows | Missing/partial closed-day dashboard data; reruns append another batch | [^schedules] [^daily] [^R7] |
| `kpi_daily` | `15 6 * * *` | Trailing-30-day paid headers → appended active rollup | Stale KPI; reruns append records for same day | [^schedules] [^kpi] |
| `funnel` | `20 6 * * *` | Trailing-24-hour carts + headers → appended session/user counts | Missing activity row; reruns append overlapping-window counts | [^schedules] [^funnel] |
| `monthly_statement` | `30 6 1 * *` | Last Eastern order month + payment fees → appended statement | Missing publication or repeated snapshots; warning does not prevent publication | [^schedules] [^monthly] |
| `top_sellers` | `45 6 * * *` | Yesterday's paid headers → appended top_products | Missing/stale list; reruns append duplicate ranks/batches | [^schedules] [^top] |
| `reorder_forecast` | `50 6 * * *` | 14-day paid headers → replaced top-200 hints | Stale/partial advisory hints; no durable history in table | [^schedules] [^reorder] |
| `email_digest` | `15 7 * * *` | Flag + seven-day paid header top product + coarse email count → digest log | Disabled path silently exits; no evidence of mail delivery; repeated logging on rerun | [^schedules] [^digest] |
| `intraday_report` | `0 12 * * *` | Today-start to run-time items → append partial report rows | Today is stale/missing/partial; pinned wrapper lacks legacy 17:00 run | [^schedules] [^intraday] [^R7] |
| `warehouse_backfill` | Manual, `None` | Manifest tables → serial Cloud SQL CSV export and BQ replace loads | Wrapper lacks required args; wrong analytics destination at pin; partial cross-table snapshot | [^schedules] [^backfill] [^manifest] |

There are **15 scheduled daily/monthly wrappers plus one manual migration wrapper**. Observed logs contain historical job executions through December, not post-migration Airflow task runs; the existence of a DAG file is not proof of successful January execution. [Repository file list](repository_files.txt), [Q042](q042_job_versions.json), [Q066](q066_runtime_boundaries.json)

## E2. Failures and semantic changes established by logs

- **Affinity December crash:** three job error rows on December 3–5 identify `IndexError` at `SEASONAL_FACTORS[t.month-1]`; first successful refresh is December 6. The current guard supplies season 1.0 beyond the 11-entry array. A scheduler process success should be checked against a new table epoch, not only the absence of an error. [Q025](q025_job_errors.json), [Q042](q042_job_versions.json), [^affinity2]
- **Trending window:** commit `f563dea` shortened 60→30 days on December 6; logs still show 60 through December 6 and 30 from December 7. README says 60; current code/log behavior is 30. Faster list churn is consistent with the shorter lookback, not proof of faster-growing demand. [^trending] [^readme], [Q042](q042_job_versions.json), [Batch history](git_batch_history.txt)
- **Fraud:** initial threshold 0.90 (`e4656fb`), tightened to 0.70 (`53f6f6c`), then raised to 0.85 (`1cb8721`). Observed runs use 0.90 December 4–5, 0.70 December 6–29, and 0.85 December 30–31. The December 29 commit only changes a constant; a separate engineer-backfill statement releases status-6 orders priced below 2,600 (`nvm-dbq-0003446400`). Threshold configuration does not release already held orders by itself. [^fraud] [^constants], [Q042](q042_job_versions.json), [Q076](q076_release_engineer.json), [definition history](git_definition_history.txt)
- **Fraud's formula:** `core=min(price/3000,1)`, ×`1+0.15*new_account+0.15*high_velocity`, capped at 1, held strictly above threshold. New account means order minus user-created less than seven days; velocity counts three or more headers in the prior 24h including the current one, without an order-status filter. It scores only paid orders created in the prior day; old held orders are not rescored/released. Current holds are 12 headers, **40,213.29**, prices **2,655.33–5,999.98**. [^fraud], [Q083](q083_fraud_threshold_population.json)
- **Reconcile schedule:** `388370b` moved 02:00→03:00 with a backup-window overlap noted in its commit. Sample November 6–15 logs show roughly **4.9–5.5 ms** durations and 130 flags; the provided evidence does not establish a reconcile outage or a measured backup-induced slowdown. [Batch history](git_batch_history.txt), [Q065](q065_reconcile_latency.json)
- **Digest inactivity:** flag direct-file reading was fixed December 16; outputs start December 17. Before calling its missing outputs a scheduler failure, inspect effective environment/file precedence and the job's silent disabled exit. [^digest] [^cronenv], [Q023](q023_digest_history.json), [Batch history](git_batch_history.txt)

## E3. Write semantics and dependency hazards

Batch connections use **autocommit**. A `DELETE` followed by per-row inserts is not an atomic table swap; concurrent readers can observe empty/partial outputs and a crashed writer can leave partial data. This applies to legacy/v2 affinity, model scores, price suggestions, and reorder hints; trending deletes the current day before inserting. Report snapshots likewise become visible one row at a time, and selecting their latest timestamp can pick an incomplete batch before completion. [^db] [^affinity] [^affinity2] [^train] [^price] [^reorder] [^trending] [^daily] [^intraday]

Nominal clock ordering is not dependency enforcement: affinity-v2 at 03:45 precedes model training at 04:15, but nothing blocks training if affinity fails or runs late. Fraud at 05:45 precedes daily report/KPI/statement but follows trending and model training; those jobs can read different status populations even on the same date. A held-order release or catalog refresh after a report run can alter live order/dashboard queries while stored snapshots remain fixed. [^schedules] [^fraud] [^trending] [^train] [^daily] [^kpi] [^monthly] [^catalog], [Q076](q076_release_engineer.json)

Jobs use `timeutil.now()`, with optional `FAKE_NOW`, instead of Airflow's logical date/data interval. A late run or ad-hoc rerun can target a different yesterday/month/window; `catchup=False` supplies no automatic historical recovery. Labeling a manual run as a past Airflow date does not make this code use that past date. [^time] [^schedules]

The old affinity job has no observed read consumer after December 6 and no current serving reference. However, it also creates `rec_decision_log`; removing it from a fresh setup without separately provisioning that table breaks widget logging/training. The evidence supports retiring its scoring output for the current widget, not blindly deleting every initialization responsibility or claiming unknown external consumers cannot exist. [Q071](q071_legacy_table_consumers.json), [Q060](q060_app_score_reads.json), [^affinity] [^similar] [^train]

## E4. Warehouse rebuild / migration details

The pinned backfill exports **32 tables** described in a manifest, ordered serially, with explicit casts and a `__PGNULL__` sentinel that preserves blank strings versus nulls. Timestamps are rendered UTC, UUIDs as strings, numeric fields as NUMERIC. Loads use `--replace`, not incremental append, and each table is exported/loaded independently. Views and log exports are not constructed by this table manifest. [^backfill] [^manifest], [Analytics catalog](tables_novamart_analytics.json), [Log catalog](tables_novamart_logs.json)

At `5ae1182`, `public` maps to dataset `novamart`, but other schemas retain their source name, so `analytics.*` targets **`analytics.*`**, inconsistent with observed **`novamart_analytics.*`**. The pinned `docs/data-access.md` repeats the stale dataset name. Establish the target mapping before any future rebuild; do not copy this command path verbatim and assume existing dashboard/warehouse consumers will be updated. [^backfill] [^accessdoc], [Analytics catalog](tables_novamart_analytics.json)

The one-shot Airflow wrapper invokes the backfill module without required `--project`, `--instance`, and `--staging`; as written, CLI parsing cannot run the advertised export. No invocation of this writer was performed in this investigation. Also, per-table exports do not establish a cross-table consistent snapshot, making order/payment/model/report joins vulnerable to temporal mismatch if the source is changing during a rebuild. [^schedules] [^backfill]

## E5. Safe modification checklist grounded in this code

1. **Specify the output contract first:** header/item/payment grain; source of truth; Eastern calendar versus rolling duration; eligibility and QA/brand/SKU rules; published versus restated. Keep finance snapshots and executive merchandising sums distinguishable. [^monthly] [^daily] [^R2] [^R3] [^R6] [^R7] [^R8] [^R9]
2. **Make run identity explicit:** use a requested window/logical date, unique run/batch identifier, completion marker, and output checks. Do not use `MAX(created_at)` alone as proof a batch finished. [^time] [^db] [^daily] [^intraday] [^R7]
3. **Use atomic publication for replacements:** construct a complete batch before switching consumers; preserve old published finance versions rather than rewriting them. Validate batch row count/epoch/sentinel/coverage invariants. [^db] [^affinity2] [^train] [^monthly], [Q037](q037_score_inventory.json)
4. **Declare dependency freshness:** train only on a complete suitable affinity/decision batch; serve a known-good score epoch; detect stale trending fallback. Keep provisioning dependencies when retiring legacy work. [^schedules] [^affinity] [^similar] [^train]
5. **Respect side effects:** fraud changes order statuses; digest recipient semantics differ from the trusted view; backfill replaces tables. Preserve a clear before/after metric bridge for threshold, identity, and taxonomy changes. [^fraud] [^digest] [^backfill], [Q076](q076_release_engineer.json), [Q029](q029_taxonomy.json)
6. **Avoid the discounted rerun trap:** `DISCOUNT_CAP=0.25`, but `apply_discounts` defaults to **0.40**, and `scripts/rerun_kpis.py` calls the default. For a 100-unit value it returns 60 instead of the intended 75 if callers wanted the configured cap. No pinned scheduled report calls this helper; do not apply either extra discount to official revenue without proving the intended contract. [^discount], commit `35c581e` in [definition history](git_definition_history.txt)
7. **Verify with appropriate isolated invariants:** items reconcile to header totals, replayed refs do not create new movements, fees are per transaction, timezone boundaries include DST, latest complete snapshot matches a read-only recomputation, source/version logging matches served items. Current CI only exercises a basic view/cart/order path and three jobs; it does not establish those extended invariants. [^orders] [^time] [^daily] [^monthly] [^similar] [^ci]

# Appendix F. Evidence, access limitations, and reproducibility

## F1. What was inspected and what each evidence type establishes

- **Pinned code:** [repository commit](repository_commit.txt), [full pinned archive](repository_5ae1182.tar), [file inventory](repository_files.txt), [ancestor history](git_history.txt), [definition diffs](git_definition_history.txt), and [batch/scheduler diffs](git_batch_history.txt). The report's code conclusions are anchored at `5ae1182`; commit dates describe code changes, while logs below establish observed behavior timing.
- **Warehouse:** table-list and `metadata_*` JSON files capture the inspected datasets/schemas. Every linked `qNNN_*.json` contains the exact read-only SQL, returned schema, row count, and result rows. `q003_jobs.json` preserves all **978** inspected job-log rows; aggregated investigations use explicit SQL rather than relying on undocumented file knowledge. [Log metadata](metadata_novamart_logs_job_runs.json), [Q003](q003_jobs.json)
- **Historical SQL:** `novamart_logs.db_queries.textPayload` is a Postgres-style statement plus source/parameters, not native BigQuery production job history. Statements are logged **before execution**, so a logged query alone proves an attempted statement, not that it succeeded. In particular, some historical engineer queries mention nonexistent extra statement columns or `chargebacks.charged_at`; current schema is `reported_at`. Pair logs with table/query results for successful data claims. [^db] [^logutil], [Q027](q027_log_sql_sample.json), [Q032](q032_db_historical_repairs.json), [chargeback schema](metadata_novamart_analytics_chargebacks.json)
- **Views:** [Q002](q002_views.json) captures warehouse view definitions, whose returned text omits some literal quote formatting. [Q016](q016_statement_history_sql.json) and [Q032](q032_db_historical_repairs.json) preserve the full original Postgres DDL. Use verified result queries or quoted original definitions, not a blind execution of the introspected text.
- **Redash:** all **9 dashboard/query definitions** and each dashboard's query association were retrieved by read-only GETs. All queries have `latest_query_data_id=null`, `schedule=null`, and no retrieved result time; there is no cached displayed numeric result to quote. Reproduced values are explicitly warehouse calculations using supplied historical anchors. [Dashboard inventory](redash_dashboards.json), [Query inventory](redash_queries.json), [daily KPI detail](redash_dashboard_daily_kpis.json)
- **Current-time caution:** operational logs end in 2019, while forensic capture/taxonomy date fields include 2026. Current wall-clock rolling queries over the historical order table would produce empty/zero activity even when historical reproductions show substantial commerce. No observed post-migration incremental warehouse-refresh job is present in the pinned DAGs; the backfill is explicitly manual. [Q066](q066_runtime_boundaries.json), [Q029](q029_taxonomy.json), [Q030](q030_blank_brand_snapshot.json), [^schedules] [^backfill]

### Redash dashboard → query inventory

| Dashboard ID / name | Query ID | Persisted source |
|---|---:|---|
| 1 / refunds | 1 | [dashboard](redash_dashboard_refunds.json), [SQL](redash_query_1.json) |
| 2 / revenue_widget | 2 | [dashboard](redash_dashboard_revenue_widget.json), [SQL](redash_query_2.json) |
| 3 / actives_board | 3 | [dashboard](redash_dashboard_actives_board.json), [SQL](redash_query_3.json) |
| 4 / registered_conversion | 4 | [dashboard](redash_dashboard_registered_conversion.json), [SQL](redash_query_4.json) |
| 5 / statements_final | 5 | [dashboard](redash_dashboard_statements_final.json), [SQL](redash_query_5.json) |
| 6 / category_revenue | 6 | [dashboard](redash_dashboard_category_revenue.json), [SQL](redash_query_6.json) |
| 7 / best_sellers | 9 | [dashboard](redash_dashboard_best_sellers.json), [SQL](redash_query_9.json) |
| 8 / brand_revenue | 8 | [dashboard](redash_dashboard_brand_revenue.json), [SQL](redash_query_8.json) |
| 9 / daily_kpis | 7 | [dashboard](redash_dashboard_daily_kpis.json), [SQL](redash_query_7.json) |

## F2. Data inventory and retention grain

| Warehouse objects | Role / retained grain | Evidence |
|---|---|---|
| `novamart.users`, `products`, `cart_items` | First-seen shopper/current catalog/current surviving cart entries | [^catalog] [^profile] [^carts], [App catalog](tables_novamart.json) |
| `orders`, `order_lines`, `payments` | Current header state, item callback facts, money movements | [^orders] [^gateway], [App catalog](tables_novamart.json) |
| `accounts`, `account_map` | UUID registrations and numeric-ID links | [^accounts], [Q020](q020_account_identity.json) |
| `report_rows`, `report_rows_intraday`, `top_products`, `statements` | Per-run published outputs; report/item snapshots, header rankings, monthly finance | [^daily] [^intraday] [^top] [^monthly] |
| `blank_brand_products` | Forensic captured diagnosis, not live backfill authority | [Q030](q030_blank_brand_snapshot.json), [Q032](q032_db_historical_repairs.json) |
| `category_names`, `category_name_history` | Base and additional effective-dated display mappings | [^R6], [Q029](q029_taxonomy.json), [Q050](q050_category_dates.json) |
| `test_users`, `contactable_users` | QA exclusion table and trusted contactability view | [Q032](q032_db_historical_repairs.json), [Q016](q016_statement_history_sql.json) |
| `statement_overrides`, `statement_corrections`, `chargebacks` | Approved replacement values, explanatory audit deltas, original-order chargeback facts | [Q005](q005_overrides.json), [Q006](q006_corrections.json), [Q007](q007_chargebacks.json) |
| `statements_corrected`, `statements_final`, `refunds_unified` | Recomputed views over base facts/snapshots; not independent finance writes | [Q002](q002_views.json), [Q016](q016_statement_history_sql.json) |
| `daily_funnel`, `kpi_daily`, `digest_log` | Appended activity/KPI/digest-log batches | [^funnel] [^kpi] [^digest] |
| `price_history`, `price_suggestions`, `reorder_hints` | Appended catalog-price changes; replaced shadow prices and advisory quantities | [^catalog] [^price] [^reorder] |
| `product_affinity`, `product_affinity_v2`, `model_scores` | Latest rebuilt candidate-pair score batches | [^affinity] [^affinity2] [^train] |
| `model_registry`, `rec_decision_log`, `order_risk`, `trending_daily` | Appended training/serving/risk records; trending day history with same-day replacement | [^train] [^similar] [^fraud] [^trending] |
| `novamart_logs.app_events`, `db_queries`, `job_runs`, `db_queries_normalized` | Log-export envelopes/raw payloads and a normalized query view | [Log catalog](tables_novamart_logs.json), [Log metadata](metadata_novamart_logs_db_queries_normalized.json), [^logutil] |

## F3. Remaining uncertainties and contradictory documentation

| Question / mismatch | What is established; what remains unverified | Evidence |
|---|---|---|
| Post-migration timezone / retries / operational health | Wrappers are naive and have no explicit dependencies/retries; scheduler instance defaults and real January runs were not supplied | [^schedules], [Q066](q066_runtime_boundaries.json) |
| Current warehouse freshness | Backfill is manual; operational dates end in 2019; no continuous replication contract is established by the pin | [^backfill] [^schedules], [Q066](q066_runtime_boundaries.json) |
| Registered/email/report endpoint mounting | Implementations and historical events exist; pinned app omits three routers | [^app] [^accounts] [^users] [^reports], [Q057](q057_status_events.json) |
| Model documentation | `rec_versions.md` is only `TBD`; README claims extra v4 features absent in vector | [^recdoc] [^readme] [^train] |
| Old affinity lineage note | Correct about current table dispatch/flag, but says both cron jobs run; cron is now retired and DAG wrappers are authoritative schedule declarations | [^lineagedoc] [^flags] [^similar] [^schedules] |
| Trending / reorder notes | README 60-day trending is stale; forecast note's old observed velocity/hint range differs from current max 2.7143 / min hint 51 | [^readme] [^trending] [^forecastdoc], [Q041](q041_reorder_snapshot.json) |
| Forensic timestamps | `CURRENT_DATE`/`now()` in logged backfills coexist with 2026 date/capture values; historical intent and current rows differ | [Q029](q029_taxonomy.json), [Q030](q030_blank_brand_snapshot.json), [Q032](q032_db_historical_repairs.json) |
| Random logging December 11 | One more decision row than app random serves; no demonstrated explanation | [Q059](q059_rec_gap.json) |
| Actual email delivery / model business lift | Digest only writes a log; recommendation training has no evaluated uplift artifact and v4 has no observed traffic | [^digest] [^train], [Q060](q060_app_score_reads.json) |

The exact read-only collection scripts are [collect_evidence.py](collect_evidence.py) and [investigate.py](investigate.py). Broader exploratory probes `Q043`, `Q058`, and `Q061` were superseded by the correctly targeted `Q060`, `Q076`, and `Q080` evidence for lineage/release timing; conclusions do not rely on truncated broad matches. [Q060](q060_app_score_reads.json), [Q076](q076_release_engineer.json), [Q080](q080_rec_rollout_times.json)

## F4. Citation definitions

All code citations below refer to repository commit **`5ae1182`**. History citations identify the change commit separately; saved query links include executable read-only SQL and observed results. [Repository commit](repository_commit.txt), [Pinned archive](repository_5ae1182.tar)

[^orders]: `5ae1182`, `novamart/routers/orders.py:14–155`: callback/idempotency/grouping/payment writes and status-only cancel/refund endpoints. [Source](../novamart/novamart/routers/orders.py).
[^gateway]: `5ae1182`, `novamart/routers/payments_webhook.py:1–21`: gateway source of truth, negative payment insertion, no status change/deduplication. [Source](../novamart/novamart/routers/payments_webhook.py).
[^monthly]: `5ae1182`, `novamart/jobs/monthly_statement.py:13–53`: Eastern previous month, paid-header gross/count, collected fees, expected-fee cutoff, append publication. [Source](../novamart/novamart/jobs/monthly_statement.py).
[^daily]: `5ae1182`, `novamart/jobs/daily_report.py:13–68`: local yesterday, line/fallback grain, exclusion rules, append snapshot. [Source](../novamart/novamart/jobs/daily_report.py).
[^intraday]: `5ae1182`, `novamart/jobs/intraday_report.py:12–77`: local today's partial window, line/fallback grain, append snapshot. [Source](../novamart/novamart/jobs/intraday_report.py).
[^constants]: `5ae1182`, `novamart/constants.py:3–38`: fees, report exclusions, statuses, timezone, legacy scan constant, discount/fraud thresholds. [Source](../novamart/novamart/constants.py).
[^reconcile]: `5ae1182`, `novamart/jobs/reconcile.py:10–23`: duplicate-ref warning scan and bounded batch. [Source](../novamart/novamart/jobs/reconcile.py).
[^policy]: `5ae1182`, `docs/restatement_policy.md:3–118`: published versus restated finance policy and October reconciliation. [Source](../novamart/docs/restatement_policy.md).
[^schema]: `5ae1182`, `schema.sql:6–76`: initial application schema and nonunique snapshot outputs. [Source](../novamart/schema.sql).
[^catalog]: `5ae1182`, `novamart/routers/catalog.py:10–98`: first-seen caches/bootstrap, brand repair, vendor-feed upsert and price history. [Source](../novamart/novamart/routers/catalog.py).
[^carts]: `5ae1182`, `novamart/routers/carts.py:11–30`: cart insert and destructive removal semantics. [Source](../novamart/novamart/routers/carts.py).
[^profile]: `5ae1182`, `novamart/onboarding.py:1–48`: ID-hash-generated customer/product attributes. [Source](../novamart/novamart/onboarding.py).
[^accounts]: `5ae1182`, `novamart/routers/accounts.py:23–49`: UUID registration, numeric bootstrap and account mapping. [Source](../novamart/novamart/routers/accounts.py).
[^users]: `5ae1182`, `novamart/routers/users.py:10–28`: current user-email update without account-email synchronization. [Source](../novamart/novamart/routers/users.py).
[^reports]: `5ae1182`, `novamart/routers/reports.py:13–42`: calendar-month header-based brand report implementation. [Source](../novamart/novamart/routers/reports.py).
[^app]: `5ae1182`, `novamart/app.py:7–28`: mounted router inventory, pool/log lifecycle. [Source](../novamart/novamart/app.py).
[^db]: `5ae1182`, `novamart/db.py:15–26`: SQL logging before execution; autocommit job connections. [Source](../novamart/novamart/db.py).
[^logutil]: `5ae1182`, `novamart/logutil.py:13–30`: app/job JSONL and parameterized raw statement format. [Source](../novamart/novamart/logutil.py).
[^time]: `5ae1182`, `novamart/jobs/timeutil.py:12–40`: wall-clock/FAKE_NOW and separately converted local day/month boundaries. [Source](../novamart/novamart/jobs/timeutil.py).
[^kpi]: `5ae1182`, `novamart/jobs/kpi_daily.py:9–25`: paid 30-day distinct-user rollup. [Source](../novamart/novamart/jobs/kpi_daily.py).
[^funnel]: `5ae1182`, `novamart/jobs/funnel.py:9–43`: cart/order rolling-24-hour inactivity sessions. [Source](../novamart/novamart/jobs/funnel.py).
[^top]: `5ae1182`, `novamart/jobs/top_sellers.py:15–39`: yesterday paid-header units ranking, append output. [Source](../novamart/novamart/jobs/top_sellers.py).
[^trending]: `5ae1182`, `novamart/jobs/trending.py:9–40`: 30-day min-5 popularity/decay and same-day replacement. [Source](../novamart/novamart/jobs/trending.py).
[^fraud]: `5ae1182`, `novamart/jobs/fraud_score.py:1–51`: heuristic formula, last-day paid selection, risk writes and holds. [Source](../novamart/novamart/jobs/fraud_score.py).
[^digest]: `5ae1182`, `novamart/jobs/email_digest.py:13–56`: environment/file flag precedence, top header product, coarse email recipients, log-only send path. [Source](../novamart/novamart/jobs/email_digest.py).
[^cronenv]: `5ae1182`, `deploy/cron.env:1–3`: `ENABLE_DIGEST=1`. [Source](../novamart/deploy/cron.env).
[^similar]: `5ae1182`, `novamart/routers/similar.py:24–131`: version aliases/dispatch, user random arm, table epoch/cache, fallback and decision logging. [Source](../novamart/novamart/routers/similar.py).
[^flags]: `5ae1182`, `deploy/flags.env:1–4`: intended recommendation version `2.0.0`. [Source](../novamart/deploy/flags.env).
[^affinity]: `5ae1182`, `novamart/jobs/affinity.py:15–53`: legacy co-cart scoring, sentinel and decision-table creation. [Source](../novamart/novamart/jobs/affinity.py).
[^affinity2]: `5ae1182`, `novamart/jobs/affinity_v2.py:13–63`: conversion credit, current listing multipliers, seasonal guard and v2 rebuild. [Source](../novamart/novamart/jobs/affinity_v2.py).
[^train]: `5ae1182`, `novamart/jobs/model_train.py:19–77`: unbounded labels, actual feature vector, logistic fit, global score rescaling and registry output. [Source](../novamart/novamart/jobs/model_train.py).
[^price]: `5ae1182`, `novamart/jobs/price_suggest.py:1–47`: shadow ±5% top-500 volume suggestions and rollout hold. [Source](../novamart/novamart/jobs/price_suggest.py).
[^reorder]: `5ae1182`, `novamart/jobs/reorder_forecast.py:1–37`: hand-fit inverse-velocity constants/top-200 overwrite. [Source](../novamart/novamart/jobs/reorder_forecast.py).
[^discount]: `5ae1182`, `novamart/jobs/discounts.py:4–10`, `scripts/rerun_kpis.py:5–11`, `novamart/constants.py:34–35`: legacy default 40% versus configured 25%, and default-using manual helper. [Helper](../novamart/novamart/jobs/discounts.py), [runbook](../novamart/scripts/rerun_kpis.py).
[^ci]: `5ae1182`, `ci/run_ci.py:26–68`: scratch DB mutations and basic flow/three-job smoke checks; inspected, not executed here. [Source](../novamart/ci/run_ci.py).
[^backfill]: `5ae1182`, `novamart/jobs/warehouse_backfill.py:24–76`: explicit casts, manifest selection, required args, schema mapping and replace loads. [Source](../novamart/novamart/jobs/warehouse_backfill.py).
[^manifest]: `5ae1182`, `novamart/jobs/warehouse_manifest.json:1–954`: 20 analytics + 12 public table columns/types; excludes views/log datasets. [Source](../novamart/novamart/jobs/warehouse_manifest.json).
[^schedules]: `5ae1182`, `crontab.txt:1–31` (retired); `airflow/dags/*_dag.py` (individual job schedules and BashOperators), especially `intraday_report_dag.py:7–14`, `warehouse_backfill_dag.py:11–19`, and `monthly_statement_dag.py:7–14`. Migration commit `4bfcbe6`; backfill commit `5ae1182`. [Retired cron](../novamart/crontab.txt), [DAGs](../novamart/airflow/dags/), [saved batch history](git_batch_history.txt).
[^readme]: `5ae1182`, `README.md:29–45`: pricing/reconcile context, stale 60-day trending, advisory reorder and overclaimed v4 features. [Source](../novamart/README.md).
[^accessdoc]: `5ae1182`, `docs/data-access.md:3–22`: migration surfaces and stale analytics dataset name. [Source](../novamart/docs/data-access.md).
[^recdoc]: `5ae1182`, `docs/rec_versions.md:1–3`: version notes only `TBD`. [Source](../novamart/docs/rec_versions.md).
[^lineagedoc]: `5ae1182`, `docs/affinity_lineage.md:3–104`: widget lineage and legacy cron-era claims. [Source](../novamart/docs/affinity_lineage.md).
[^forecastdoc]: `5ae1182`, `docs/forecast_caveats.md:5–123`: advisory rationale, omissions, prior observed range. [Source](../novamart/docs/forecast_caveats.md).
[^R1]: Redash dashboard **1 `refunds`**, query **1**, Eastern refund event-month grouping. [SQL](redash_query_1.json), [dashboard](redash_dashboard_refunds.json).
[^R2]: Redash dashboard **2 `revenue_widget`**, query **2**, latest closed-day/today snapshot blending and seven-calendar-day bounds. [SQL](redash_query_2.json), [dashboard](redash_dashboard_revenue_widget.json).
[^R3]: Redash dashboard **3 `actives_board`**, query **3**, trailing 30-day candidate statuses and email/test cleaning. [SQL](redash_query_3.json), [dashboard](redash_dashboard_actives_board.json).
[^R4]: Redash dashboard **4 `registered_conversion`**, query **4**, account-email mapping and all-history paid orders. [SQL](redash_query_4.json), [dashboard](redash_dashboard_registered_conversion.json).
[^R5]: Redash dashboard **5 `statements_final`**, query **5**, `SELECT * FROM analytics.statements_final ORDER BY month`. [SQL](redash_query_5.json), [dashboard](redash_dashboard_statements_final.json).
[^R6]: Redash dashboard **6 `category_revenue`**, query **6**, item fallback, as-of mapping, rolling 30 days, QA/brand exclusions. [SQL](redash_query_6.json), [dashboard](redash_dashboard_category_revenue.json).
[^R7]: Redash dashboard **9 `daily_kpis`**, query **7**, latest report snapshots plus daily order-based customer series. [SQL](redash_query_7.json), [dashboard](redash_dashboard_daily_kpis.json).
[^R8]: Redash dashboard **8 `brand_revenue`**, query **8**, item fallback, 30 days, string QA exclusions and current brands. [SQL](redash_query_8.json), [dashboard](redash_dashboard_brand_revenue.json).
[^R9]: Redash dashboard **7 `best_sellers`**, query **9**, item fallback, 7 days, revenue ordering, QA/brand exclusions, no status filter. [SQL](redash_query_9.json), [dashboard](redash_dashboard_best_sellers.json).
