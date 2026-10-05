# 1. Summary

**Novamart tribal knowledge: financial numbers, customer/product analytics, recommendation systems, and batch operations.** Investigation started **2026-10-05 15:10:56 UTC**; investigation ID **`bf0f9c05-58a3-421f-a87d-cd2e73789cb8`**. Repository baseline: **`5ae11821806a396aac10115e03863b8c68c1bfcc`**. The warehouse contains historical business activity through December 2019, not a continuously current 2026 business feed. Orders run from September 25 to December 31, 2019; application/query events end December 31 at 23:57:06 UTC. [Git evidence](git_evidence.json), [warehouse extent](data_extent.json).

The essential conclusions are:

1. **Ask which revenue before answering how much.** Original published finance numbers live in `novamart.statements`; approved current restatements live in `novamart_analytics.statements_final`. Payments, current paid-order totals, and executive sales dashboards answer different questions. October's originally published net is **1,194,652.79**; its final restated net is **1,191,085.36**. [C3], [published](finance_statements.json), [final](finance_final.json).
2. **Order headers, sold items, and payment transactions are different grains.** Since November 22, multiple same-session callbacks can accumulate into one order. Item reporting needs `order_lines` plus legacy orders with no lines. The snapshot contains **9,127 headers**, **2,284 lines on 2,059 headers**, and **173 multi-item orders**. [C1], `5d1300d`, [extent](data_extent.json), [line integrity](multi_item_integrity.json).
3. **Historical snapshots do not automatically change with current order status.** Recomputing October today from `status=1` produces net **1,171,353.71**, which is neither its original nor its approved final statement. Later cancellations/refunds and payment movements explain why re-running current SQL is not historical reproduction. [C3], [current recomputation](statement_recomputed_current.json), [status cohorts](orders_month_status.json).
4. **“Active customer” is three incompatible metrics.** Nightly KPI: trailing-30-day paid buyers; executive KPI: daily ordering users with brand/QA cleanup but no status filter; board query: trailing-30-day users excluding statuses `0,2,3` and test-like email identities. In this dataset the board/email cleanup removes everyone, while the paid-buyer definition counts **1,146** at a fixed January 1, 2020 UTC anchor. [C5], Redash queries **3/7**, [active comparison](active_counts.json).
5. **The digest does not use the trusted contactable-users view.** There are **38,950** numeric user rows, **30** UUID accounts, **40** digest-eligible addresses, and **zero** trusted contactable users. All emails are `example.com` or `gmail.example`. A “digest_sent” record is an aggregate job log, not proof of email delivery. [C4], [C8], [customer counts](customer_counts.json), [domains](email_domains.json).
6. **The recommendation system is mostly fallback, and v4 is not observed serving.** The active flag selects serving version `2.0.0`; the affinity-v2 writer stamps `2.0.1`. Of logged non-random v2 decisions, **79.78%** used fallback. Seventeen v4 training runs exist, but no v4 decisions or app reads of `model_scores` were observed. [C6], [C7], [versions](rec_versions.json), [registry](model_registry.json), [score readers](shadow_reads.json).
7. **Training success is not evidence of recommendation lift.** V4 fits five features, labels any later paid order as conversion, then scales every eligible affinity score by one global coefficient-derived factor. The latest multiplier is about **0.975516**; this preserves ranking apart from rounding/ties. Random-arm decision logging also has a verified December 17–19 hole. [C7], [score ratio](model_score_ratio.json), [logging gap](rec_logging_gap_bounds.json).
8. **Batch changes require attention to publication and scheduling, not just SQL.** Jobs use autocommit; several delete/repopulate tables non-atomically; append-only outputs can double count on rerun. Airflow wrappers have no dependency edges, explicit timezone, or logical-date injection. The intraday wrapper schedules only noon although retired cron ran noon and 17:00. [C10], [C11], [C13].
9. **The supplied data has material time/provenance inconsistencies.** A December 2019 taxonomy backfill using `CURRENT_DATE` produced rows effective **2026-08-13**. Five rows matching the logged December 29 fraud-release pattern carry **2026-08-13** update timestamps; that release SQL uses `NOW()`. Preserve both the logged action date and actual stored value; do not silently rewrite either in analysis. [taxonomy](taxonomy_changes.json), [released-order candidates](fraud_releases.json), SQL log IDs `nvm-dbq-0002395860`, `nvm-dbq-0003446400` in [manual SQL](manual_sql.txt).

**Reading guide:** the eight pillars provide the decision-oriented overview; appendices A–G contain detailed calculations, historical changes, table grains, job runbooks, reproduction queries, and the evidence register. All monetary figures below retain the repository's dollar-style units; no currency-conversion or accounting-standard interpretation is added. [C1], [C3], `12e1c68`.

# 2. Why this project

The practical need is to preserve **which definition, implementation version, data state, and reporting consumer produced a number**. The repository itself demonstrates why this is necessary: the trending README still says 60 days while code uses 30; the recommendation version document is `TBD`; finance explicitly distinguishes original statements from restatements; and dashboards were moved out of the repository into Redash. [C3], [C9], [C12], `41e3537`.

This document supports three concrete tasks:

| Task | What the reader should establish | Evidence base |
|---|---|---|
| Explain a month's revenue | Reporting purpose → statement layer → local month → fee correction → chargebacks → difference from order/payment/dashboard totals | [C1]–[C3], [finance evidence](finance_final.json), Appendix A |
| Explain a dashboard number | Exact query ID → grain → window → filters → identity mapping → snapshot version → current-versus-historical dimensions | [R], [V], Appendices B and F |
| Evaluate or extend batch/ML systems | Actual serving path → observed logs → upstream dependencies → publication semantics → model/measurement limitations | [C6]–[C11], [job inventory](job_event_inventory.json), Appendices C and D |

**Evidence precedence used here:** executable SQL/code and observed rows/logs establish behavior; documentation establishes intended policy; commit history establishes changes but not by itself the instant production adopted them. A logged SQL statement proves it was logged, not necessarily that it succeeded—`db.py` logs before executing, and historical analyst queries sometimes name nonexistent columns. Examples include `external_ref`, `total_amount`, and `charged_at`, whereas inspected schemas contain `payment_ref`, `price`, and `reported_at`. [C10], [W], [manual SQL](manual_sql.txt): `nvm-dbq-0001375316`, `nvm-dbq-0003446395`, `nvm-dbq-0003539855`.

**Scope of direct observation:** only the supplied repository, BigQuery datasets, and read-only Redash API were used. All nine Redash query definitions and the dashboard list were readable; dashboard-detail GETs returned HTTP 500 and every query had `latest_query_data_id=null`. Consequently, dashboard results in this document are explicitly labeled warehouse reproductions, not observed rendered/cached dashboard values. [R], [dashboard list](redash_dashboards_list.json), [detail GET results](redash_dashboards.json).

# 3. Business understanding

## The operational flow

1. **Catalog and shopper discovery:** product views and cart/order paths can bootstrap users/products on first sight. User emails initially use `user<uid>@example.com`; profile attributes, product cost, stock, and vendor are deterministically synthesized from IDs. These columns are inputs used by downstream jobs, not independently validated demographic, inventory, or cost facts. [C1], [C4].
2. **Catalog price changes:** the vendor feed updates current `products.list_price` and, after the history feature was added, appends `price_history`. A completed order uses the callback's supplied price, not a lookup of a price-suggestion table or historical list price. [C1], `d213f6e`, `795d273`.
3. **Purchasing:** a gateway callback creates or extends an order, writes one item line and one positive payment per new callback reference, calculates the processor fee, and marks the header paid. Replay handling and advisory locks are intended to prevent creating the same callback twice. [C1], `b676969`, `5d1300d`.
4. **Subsequent state/money changes:** cancellation and the original refund endpoint change header status; the gateway refund webhook adds negative payment money movements without changing status. Fraud scoring can hold an already-paid order. These paths therefore change different reporting surfaces. [C1], [C8].
5. **Reporting:** daily/intraday jobs publish filtered product sales snapshots; monthly statements publish an order-based financial snapshot; override and chargeback views layer approved finance restatements over the published snapshot. Redash adds its own consumer-specific definitions. [C2], [C3], [R], [V].

## What the financial language actually means

| Term in this estate | Operational meaning | Consequence |
|---|---|---|
| Order gross | `SUM(orders.price)` over the selected headers/status/window | For a multi-item order, header price is accumulated item value; do not repeat it across joined payment/line rows. [C1] |
| Payment gross/fee/net | Signed payment-row fields, with `net=gross-fee` | Refund webhook rows have negative gross/net and zero fee; payment time differs from original order month. [C1], [financial integrity](financial_integrity.json) |
| Statement net / “net revenue” | Published order gross minus collected fees, then explicit override/chargeback adjustments in the final view | It is not a general profit, margin, or complete refund-adjusted cash measure; the inspected job/view does not deduct product cost or all later gateway refunds. [C3], [V] |
| Dashboard revenue | Item sales or precomputed report revenue under each dashboard's filters | Often excludes brands/QA; often includes non-paid statuses; is not finance net. [R], [C2] |
| Refund amount | Unified union of cancellation/refund status amounts and negative payment amounts | It combines operational reversals with money movements; event count is not distinct refunded orders. [V], Redash query 1 |

## Status semantics

| Status | Meaning supported by evidence | Reporting effects |
|---|---|---|
| `0` | Initial/pending state before payment completion | Excluded by paid-only and report/board status filters. [C1], [C2] |
| `1` | Paid/completed state used by finance and many jobs | Required by monthly statements, top sellers, trending, KPI rollup, reorder, price suggestions and training outcomes. [C3], [C5], [C7]–[C9] |
| `2` | Cancelled, after `8f19718` | Excluded by current daily report and board query, but not direct item sales dashboards. [C1], [C2], [R] |
| `3` | Refunded via original status endpoint, after `d87cb3d` | Same filtering contrast as cancelled; gateway refunds need not use this status. [C1], [V] |
| `4` | Legacy cancellation constant in initial import | Renamed to `2` on October 28; no current status-4 rows were returned. Do not invent another business lifecycle meaning. `2da4141`, `8f19718`, [status counts](orders_month_status.json) |
| `5` | Excluded by duplicate-reference reconcile SQL | No fuller business meaning was found in the inspected implementation; report/board `NOT IN (0,2,3)` would admit it. [C10], [C2], [R] |
| `6` | Fraud hold | Excluded by `status=1`, admitted by `NOT IN (0,2,3)` and unfiltered dashboards. Twelve held December headers total **40,213.29** in the snapshot. [C8], [status counts](orders_month_status.json) |

# 4. Metrics

## Source-of-truth and consumer registry

**Warehouse names below use the actual datasets:** PostgreSQL `public.*` maps to `novamart.*`; PostgreSQL `analytics.*` maps to `novamart_analytics.*`. Redash stores PostgreSQL SQL, so its unqualified tables and `analytics.*` names should not be copied verbatim into BigQuery. [W], [R], [C12].

| Number / consumer | Authoritative surface for that question | Definition and principal trust boundary |
|---|---|---|
| Originally published monthly finance | `novamart.statements` | Append-only run snapshot; choose the publication needed, not a sum across repeated runs. [C3] |
| Corrected statement before chargebacks | `novamart_analytics.statements_corrected` | Per-field `COALESCE` from `statement_overrides`; `statement_corrections` is not in this view's lineage. [V] |
| Current restated finance | `novamart_analytics.statements_final`; Redash **query 5**, dashboard `statements_final` | Corrected gross/net minus booked chargebacks attributed to original Eastern order month; fee/count remain unchanged. [V], [R] |
| Collected payment money | `novamart.payments` | Signed movements at payment timestamp; preaggregate by `order_id` before joining headers. [C1], [current reconstruction](statement_recomputed_current.json) |
| Monthly refunds dashboard | Redash **query 1**, `novamart_analytics.refunds_unified` | Eastern month of refund/status-update timestamp; `COUNT(*)` union rows and sum positive refund amounts. Includes cancellations. [R], [V] |
| Daily executive revenue and “orders” | Redash **query 7**, dashboard `daily_kpis` | Last 14 Eastern calendar dates; latest complete-day report for prior dates, latest intraday batch for today; **“orders” means sum of item units**. Additional current-brand exclusion. [R], [C2] |
| Seven-day revenue widget | Redash **query 2**, dashboard `revenue_widget` | Last seven Eastern calendar dates including today; same closed-day/today split, latest timestamp per day; no product join or extra brand filter in widget SQL. [R] |
| Best sellers | Redash **query 9**, dashboard `best_sellers` | Rolling 7×24 hours; lines plus legacy fallback; exclude UID 424242 and brands Lucente/Jetem; **no status or excluded-SKU filter**; rank top 20 by revenue, not units. [R] |
| Brand revenue | Redash **query 8**, dashboard `brand_revenue` | Rolling 30 days, same item grain; exclude numeric QA ID plus a UUID string; exclude Lucente/Jetem; no status/SKU filter; empty brand remains empty. [R] |
| Category revenue | Redash **query 6**, dashboard `category_revenue` | Rolling 30 days; same item/QA/brand rules; latest effective category mapping at item date, history wins same-date ties, unmatched → `other`. Date cast is PostgreSQL session-date semantics, not an explicit Eastern conversion. [R] |
| Monthly brand-report function | `routers/reports.py:brand_report` | Eastern calendar month; **header** product and full header price; `status=1`; SKU and brand exclusions; no QA-user exclusion; blank brand → `unbranded`. The router exists but is not mounted by pinned `app.py`. [C1], [C14] |
| Nightly top sellers | `novamart.top_products` | Yesterday's Eastern day; `status=1`; header product counts; top 50 by units, product ID tie-break; no dashboard QA/brand/SKU exclusions. [C9] |
| Trending/homepage fallback | `novamart_analytics.trending_daily` | Rolling 30-day paid-header counts, minimum 5, recency-decayed score, top 50. Not the best-sellers dashboard. [C9] |
| Numeric “users” / first seen | `novamart.users` | First-observed bootstrap row; not proof of explicit signup. [C4] |
| Registered account signup | `novamart.accounts`, `account_map`; `account_created` app event | UUID registration/enrollment, linked to numeric shopper ID. Endpoint permits another UUID on another call; distinguish account rows from distinct people. [C4] |
| Registered conversion dashboard | Redash **query 4**, dashboard `registered_conversion` | Distinct email-matched numeric paid buyers and all-time header revenue, including pre-enrollment orders. **No conversion denominator or rate is computed.** [R] |
| Nightly active customers | `novamart_analytics.kpi_daily` | Distinct numeric buyers with `status=1`, trailing 30 days at run time; no QA/brand/email cleanup; append per run. [C5] |
| Executive active/contactable customers | Redash **query 7** | Distinct header-order users per Eastern day, no status filter; exclude QA 424242 and current header-product brands Lucente/Jetem; contactable subset joins trusted view. [R], [V] |
| Board actives | Redash **query 3**, dashboard `actives_board` | Trailing 30 days; statuses other than `0,2,3`; exclude `test_users` and extensive test/internal-email patterns; no brand filter. [R] |
| Funnel “users_active” / sessions | `novamart_analytics.daily_funnel` | Trailing-day cart+order events; all statuses/users; sessions split after **more than** 120 idle minutes per user; no product-view events. [C5] |
| Contactable users | `novamart_analytics.contactable_users` | Opt-in + syntactically valid email + exclude exact `example.com/.net/.org` and suffix `.example`. It does not itself implement all board test-domain rules or verify deliverability. [V] |
| Digest audience | `novamart_analytics.digest_log.recipients` | `COUNT(*) FROM users WHERE email NOT LIKE '%@example.com'`; no opt-in/validity/trusted-view join. [C8] |

## Verified numerical anchors

These anchors make definition differences concrete; they are **not all the same measurement period**. Rolling dashboard examples freeze the clock at **2020-01-01 00:00 UTC**, which is December 31, 2019 in New York. The daily/widget examples use that local date and the stored last intraday snapshot. Current-state recomputations still use the supplied final database state, not time travel. Exact SQL accompanies each linked result. [dashboard example SQL/results](daily_kpis_example.json), [active SQL/results](active_counts.json).

| Example | Verified value | Evidence |
|---|---:|---|
| October final finance net | 1,191,085.36 | [final](finance_final.json) |
| November final finance net | 1,069,286.09 | [final](finance_final.json) |
| September final finance net | 2,623.64 | [final](finance_final.json) |
| December current paid-header gross / fee / provisional net | 552,328.93 / 16,600.26 / 535,728.67 | [recomputation](statement_recomputed_current.json); no December published statement in [statements](finance_statements.json) |
| November / December unified refund totals | 9,691.77 / 18,848.93 | Sum of kinds in [refund breakdown](refunds_monthly.json) |
| Seven-calendar-day widget, December 25–31 | 139,598.13; naive union would yield 371,872.10 | [widget reproduction](revenue_widget_example.json) |
| December 31 daily KPI | 60 item units, 18,202.09 revenue, 54 daily active users, 0 contactable | [daily KPI reproduction](daily_kpis_example.json) |
| Last saved nightly active KPI, December 31 11:15 UTC | 1,152 | [saved KPI](kpi_latest.json) |
| Same definition recomputed at January 1 00:00 UTC | 1,146 | [fixed-anchor comparison](active_counts.json) |
| Board-active query at that anchor | 0, after email cleanup of 1,151 pre-cleanup candidate users | [fixed-anchor comparison](active_counts.json), [email domains](email_domains.json) |
| All-time registered paid buyers / revenue | 30 / 18,155.71; 63 of 74 paid headers predate enrollment | [registered reproduction](registered_counts.json), [enrollment time](account_map_consistency.json) |
| Best seller by revenue, fixed rolling-seven-day example | Product 1005116: 6 units, 5,889.81; product 1004767 sells 20 units but ranks lower at 4,788.30 | [best-seller reproduction](best_sellers_example.json) |
| Leading brand, fixed rolling-30-day example | Apple: 334 units, 236,606.73 | [brand reproduction](brand_revenue_example.json) |
| Category total, same rolling-30-day example | 1,880 items, 569,650.05; electronics 437,887.95 | [category reproduction](category_revenue_example.json) |

# 5. System

## Architecture and actual connectivity

The service is FastAPI with a psycopg async connection pool; jobs use synchronous PostgreSQL connections. The schema file is only a starting schema: later endpoints/jobs and manual backfills create additional tables, columns, indexes and views. The warehouse manifest lists 32 exported base tables; the warehouse adds views and exported logs. [C10], [C12], [C14], [W].

```text
catalog/views/carts/gateway callbacks
                │
                ▼
       serving PostgreSQL
 users/products/cart_items/orders/order_lines/payments
          │              │                 │
          │              ├─ daily/intraday reports ─ executive KPIs/widget
          │              ├─ monthly statement ─ overrides ─ chargebacks ─ final finance
          │              └─ top sellers/trending/KPI/funnel/fraud/pricing/reorder/digest
          └─ affinity v1/v2 ─ similar-products API ─ decision/app logs
                                   │
                           random-arm records
                                   ▼
                             model_train v4
                                   ▼
                          registry/model_scores
                          (flag-gated serving)

PostgreSQL tables ─ one-shot export/load ─ BigQuery datasets
statement/app/job logs ─ exports ─ novamart_logs
Redash query definitions retain PostgreSQL table names/SQL
```

This is a lineage map, not a claim that Airflow enforces these dependencies. The wrappers are independent single-task DAGs; model training is merely scheduled after affinity-v2. The current mounted routers are catalog, carts, orders, similar, and payment webhooks. **Accounts, email-update, and brand-report modules exist, and historical account/email events exist, but those three routers are not included in pinned `app.py`.** Endpoint availability therefore cannot be inferred from a module's existence. [C6]–[C14], [app events](app_event_inventory.json).

## Important serving boundaries

- **Recommendation flag:** `deploy/flags.env` currently says `REC_MODEL_VERSION=2.0.0`; code reads it on each request from a relative path. Missing file defaults to v2. Aliases normalize `2/v2` and `4/v4/model4`; arbitrary other strings also route to `model_scores` because dispatch is an `if v2 else model_scores`, not strict validation. A flag set to `1.0.0` does not restore the historical v1 path. [C6].
- **Score cache:** per-process six-hour cache keyed by `(table, base product)`; current code checks `MAX(updated_at)` and clears that table's cached entries when the timestamp changes. This fixes a documented stale-score window, but is not an atomic completed-batch protocol. [C6], [C10], `a00f24c`, `8ed2971`.
- **Fallback:** missing/empty eligible v2/model scores lead to the latest available trending day, without a maximum-age check. Exceptions in score lookup are labeled `table_missing` even though the exception handler is broad. Fallback errors themselves are not similarly caught. [C6].
- **Warehouse is not serving:** the app/jobs still query PostgreSQL; BigQuery is the analytical copy. The pinned exporter maps analytics tables to an `analytics` dataset, whereas the actual supplied warehouse uses `novamart_analytics`; local descendant commits `99003c3`/`20e066f` correct this. Those descendants are evidence of the fix, not changes applied to this pinned checkout. [C12], [W], [Git evidence](git_evidence.json).

# 6. Data

## Grain and time are part of every definition

| Data class | What is preserved | What is not automatically preserved |
|---|---|---|
| `orders` | Current header total/status, original creation time, latest update | Full status history or every item on its own row; later status changes alter a current-state historical query. [C1] |
| `order_lines` | Newer callback/item prices, product IDs, sessions, references and timestamps | Pre-November-22 history; older orders need fallback. [C1], [extent](data_extent.json) |
| `payments` | Individual signed movements and fees | Original status-based cancellations are not negative-payment entries. [C1], [V] |
| Daily/intraday report rows | Product aggregates at each run timestamp | They are snapshots, not incremental additions; all versions must not be summed together. [C2], [R] |
| Statements | Published monthly run outputs | Later approved changes live in separate override/chargeback layers; rerunning is not equivalent to reproducing the original. [C3], [V] |
| Current products/users | Latest attributes | General historical brand/category/email snapshots; joining them can reclassify old activity. Price history is only a partial vendor-feed history. [C1], [C4], [price history extent](price_history_extent.json) |
| Affinity/model/pricing/reorder tables | Latest delete/repopulate batch | Durable history of prior batch contents; logs/registry may preserve only summaries or coefficients. [C7]–[C10] |
| Decision/app/SQL logs | Served decision fields, application events, logged SQL text and parameters | A unique recommendation request ID, full response items in app events, successful execution for every SQL line, or genuine BigQuery bytes/slots for imported PostgreSQL statements. [C6], [C10], [normalized log sample](logs_normalized_sample.json) |

**Business calendar:** daily reports and statements use `America/New_York`; local-day windows convert both local midnights to UTC, allowing a 25-hour fall-back day. Several other jobs simply use `run_ts - interval` and store `ts::date`, which depends on database timestamp/date semantics. Redash best-seller/brand/category windows are rolling, while the widget/daily KPIs are local calendar windows. [C2], [C5], [C9], [R].

**Snapshot/time anomaly:** taxonomy history's six renamed-category rows are dated August 13, 2026, although their SQL action is logged December 12, 2019 and uses `CURRENT_DATE`. The as-of item-date join therefore correctly does **not** classify 2019 audio sales as `entertainment` or lighting-tool sales as `lighting` in this supplied snapshot. Likewise, five candidate fraud-release rows total **10,859.73** and carry a 2026 update timestamp matching the logged release predicate; their actual before-state is not stored in `orders`. These are observed inconsistencies; the evidence does not establish the precise environment mechanism that produced them. [taxonomy](taxonomy_changes.json), [category result](category_revenue_example.json), [release candidates](fraud_releases.json), [manual SQL](manual_sql.txt): `nvm-dbq-0002395860`, `nvm-dbq-0003446400`.

**Evidence freshness:** the latest log activity is 2019, while API resource creation times and some backfill-generated values are 2026. A present-day `now()` query against this historical copy can be empty; use a declared analytical anchor when reproducing historical rolling dashboards. A historical anchor alone does not reverse later status, price, email, or taxonomy changes. [data extent](data_extent.json), [W], [R], [current status cohorts](orders_month_status.json).

# 7. Experimentation

## What can be concluded about ML performance

| Question | Evidence-based answer |
|---|---|
| Does the v2 pipeline run and serve? | Yes: 26 successful refresh logs from December 6–31, serving reads of `product_affinity_v2`, and 52,695 logged `rec_source=model` decisions. This establishes operation, not incremental business lift. [job inventory](job_event_inventory.json), [readers](affinity_readers.json), [decisions](rec_versions.json) |
| Does the learned v4 model train? | Yes: 17 registry entries, December 15–31; latest entry has 14,411 training rows and five coefficients. [registry](model_registry.json) |
| Is v4 observed live? | No in the inspected historical evidence: no intended/effective v4 decisions, flag remains v2, and no app/job SELECT of `model_scores` was found. The one observed read is an engineer's count/freshness inspection. [C6], [decisions](rec_versions.json), [readers](shadow_reads.json) |
| Is v4 a personalized product-ranking model in serving? | No: the scoring writer multiplies every eligible v2 score by `1 + 0.1 * coefficient[0]`. It never runs `predict_proba` on a user-candidate feature vector. With the observed positive multiplier, rankings cannot improve except incidental rounding/tie effects. [C7], [score-ratio check](model_score_ratio.json) |
| Does “random arm” imply an unbiased full-catalog test? | No: user assignment is deterministic hash modulo 20, and the candidate pool is the first 500 product IDs excluding two SKUs; it is not the full catalog. Sampling is deterministic for `(uid,session,base_pid)`. [C6] |
| Is there enough evidence to claim a conversion lift? | No validated uplift estimator, bounded attribution, holdout result, or serving-v4 comparison is implemented in the inspected training/serving path. Training labels mean any subsequent paid header for the user, without matching purchased product to a shown item or imposing an attribution horizon. [C6], [C7] |

## Measurement traps that must be handled before an experiment

- **Historical version labels:** v1 fallback rows retain `effective_version=1.0.0`; v2 fallback uses `effective_version=fallback`. Group by source as well as version. Random-arm rows may retain effective version `2.0.0` even though they did not use model scores. [C6], `f1217a8`, `df4ed85`, [decision groups](rec_versions.json).
- **Logging outage, not zero treatment:** **1,372** app random-arm events have no matching decision key between **2019-12-17 16:50:10 UTC** and **2019-12-19 14:54:44 UTC**. On December 18 there are **848** random app events and **zero** random decision rows. The refactor's early return removed the insert; the fix restored it. [gap bounds](rec_logging_gap_bounds.json), [daily gap](rec_logging_gap.json), `30e8907`, `a00f24c`.
- **Exposure identity:** `(ts,user_id,base_pid)` is not unique: **2,838** repeated keys represent **2,846** extra rows. These are collisions/repeats of that candidate key, not proof that all such rows are erroneous duplicates. Decision records omit session, while app events contain session but not the item list. [duplicate-key check](rec_duplicate_keys.json), [C6], [sample app events](rec_gap_samples.json).
- **Candidate coverage and list size:** latest affinity-v2 contains 3,912 directed pairs, of which 2,964 are `-1` sentinels; 948 nonnegative candidate pairs feed model scores. About **72.65%** of v2 model-source decisions returned fewer than five items. Exposure quality and fallback mixture are therefore part of any treatment comparison. [score health](score_health.json), [list sizes](rec_incomplete_lists.json).
- **Training leakage/censoring:** current product price, current/all-history base popularity, and current order statuses are used to train labels for older exposures. Recent exposures have less future observation than older ones; the same user's later order can label many prior exposures positive. A time-split evaluation must reconstruct features and outcomes at explicit cutoffs. This is a methodological implication of the SQL, not a measured lift estimate. [C7].
- **Fraud confounding:** changes to status-6 thresholds and the one-off release alter paid-order outcomes without demonstrating a recommendation improvement. Session-gap changes and item/header changes also break naive before/after comparisons. [C5], [C8], `1cb8721`, [parameter history](job_parameter_history.json).

## Recommended evaluation contract

For a future implementation, define assignment at user level; log a unique exposure ID, actual item IDs/ranks, intended/effective version, score-batch ID and fallback cause; compare bounded item-attributed outcomes over equal observation windows; account for repeated users and fallback; and report confidence intervals plus guardrails for refund/hold rates and coverage. Exclude or explicitly reconstruct the December logging-hole interval before historical training/evaluation. These are recommendations responding to the observed schema, label and logging limitations, not claims that such an experiment already exists. [C6], [C7], [gap bounds](rec_logging_gap_bounds.json), [duplicate-key check](rec_duplicate_keys.json).

Other “intelligent” outputs require the same distinction: dynamic pricing is a **shadow heuristic**, reorder hints are a **hand-fit inverse-velocity formula**, and fraud scoring is a **price/user-signal rule**. Their successful job logs do not establish causal value, calibration, purchasing accuracy, or fraud precision/recall. [C8], [pricing readers](shadow_reads.json), Appendix C.

# 8. Glossary

| Term | Local meaning and evidence |
|---|---|
| As-published | The statement snapshot actually written at publication time. [C3] |
| Corrected | Original statement with monthly override values applied; pre-chargeback. [V] |
| Final / restated | Corrected statement with booked chargebacks subtracted from original-order-month gross/net. [V] |
| Header | One `orders` row, potentially carrying multiple item/payment callbacks. [C1] |
| Item / unit | One `order_lines` row, or one legacy header without lines, in item-aware reports; header count in older/non-migrated jobs. [C1], [C2], [C9] |
| Payment reference | Callback identity; older duplicate references survive the idempotency fix. [C1], [duplicate references](duplicate_refs.json) |
| Gateway refund | Negative payment row, zero fee, unchanged order status. [C1] |
| Chargeback | Separately booked amount by order, applied by final finance view; not a row in the unified refund view's definition. [V] |
| Active customer | Must be qualified as nightly paid buyer, executive daily orderer, or board-cleaned trailing buyer. [C5], [R] |
| Contactable | Trusted-view opt-in/email-pattern definition, distinct from digest recipient count. [V], [C8] |
| Registered | UUID account enrolled and related to numeric shopper identity; not every `users` row. [C4] |
| QA smoke account | Numeric UID `424242`, linked to UUID `cc27b436-d6f9-4e84-adaf-e716025dd369`. [QA event](qa_identity_log.json) |
| Effective category | Latest mapping valid at an item date; mapping history can differ from current product metadata. [R] |
| Snapshot version | Rows sharing output date and run `created_at`; select one whole batch, not an independent latest row for each product. [C2], [R] |
| Affinity | Directed co-cart pair statistic with recency decay; v2 additionally uses order-conversion and listing features. [C7] |
| Sentinel `-1` | Too few observed pairs, not negative preference. [C7] |
| Intended version | Normalized runtime version flag logged for a request. [C6] |
| Effective version / source | What serving reports it actually used; historical label semantics differ across v1/v2 and random/fallback. [C6], [decision groups](rec_versions.json) |
| Random arm | Approximately 5% of users by stable SHA-256 modulo assignment, shown samples from a restricted 500-product pool. [C6] |
| Trending | Recency-decayed paid-header units, currently 30-day lookback; fallback supply. [C9] |
| Shadow pricing | Suggestions written for analysis, with no observed serving consumer. [C8], [readers](shadow_reads.json) |
| Reorder hint | Advisory `int(15.6 + 162.4/(velocity+1.8))`, not a learned inventory forecast. [C8] |
| Business day/month | Eastern local calendar boundaries converted to UTC in reporting helpers. [C2] |
| `FAKE_NOW` | Job time override supported by `timeutil.now`; not automatically set to Airflow logical date. [C2], [C11] |

---

# Appendix A — Financial lineage, reconciliation, and history

## A1. Orders and payments: how records are actually made

The current order callback acquires advisory transaction locks on session and payment reference, searches both headers and lines for an existing reference, and reuses the earliest matching order. If a payment is missing it inserts one; a replay changes status only when the existing status is `0`. A new reference can append to an order belonging to the same user/session if a line lies in the preceding 15 minutes and the order is not cancelled/refunded. Appending increases header price, adds a line/payment, and sets status to `1`; that predicate does not exclude held status `6`. A new order is inserted at `0`, then paid at `1`. The first product/reference remain header attributes even when later products are appended. [C1]: `orders.py:19–105`.

**Consequences:**

- Payment transaction count can exceed header count; in November, **3,614 payment rows** coexist with **3,582 headers**. A header-payment join followed by `SUM(o.price)` duplicates header amounts on multi-payment orders. Use separate header aggregation and payment preaggregation. [payments](payments_monthly.json), [headers](orders_month_status.json), [C1].
- The October 15 idempotency change prevents future callback duplication; it does not delete historical duplicates. The current data contains **130 duplicated references**, **285 headers in those groups**, **155 excess headers**, and **106,943.01 gross across the groups**. That gross is not a proven overcharge amount; determining excess money requires gateway/reference-level reconciliation. [duplicate check](duplicate_refs.json), `b676969`, [C10].
- Reconcile only logs suspect references; it neither refunds nor repairs them. Its batch rose from 100 to 200 on October 18. The present count of 130 suspect references fits the new cap, so repeated warnings are not necessarily new duplicates. `030d841`, [C10], [duplicate check](duplicate_refs.json), [job performance](reconcile_performance.json).
- **Line reconciliation passed:** all 2,059 headers with lines equal their line-price sums; maximum six lines per header. Payments also have no orphan orders and no rows violating rounded `gross-fee=net`. These checks validate arithmetic and links, not gateway completeness or duplicate-business-event correctness. [line integrity](multi_item_integrity.json), [payment integrity](financial_integrity.json).

## A2. Fee calculation and why a small delta can be real

Originally each payment fee was `round(callback_price * 0.029, 2)`, while the monthly job rounded `SUM(gross)*0.029` only once. Rounding per payment versus once per month produces differences. Commit `a92c96d` changed actual statement fee to `SUM(payments.fee)` for the selected paid-order cohort; the job's expectation calculation remained only a diagnostic until amended again. [C3], `a92c96d`, [statement warnings](statement_warnings.json).

| Month / event | What actually happened | Evidence |
|---|---|---|
| September statement | Published fee 78.36, collected fee 78.37, warning delta −0.01; no September override is present, so final view still retains net 2,623.64 rather than collected-payment net 2,623.63 | [warnings](statement_warnings.json), [overrides](finance_overrides.json), [payments](payments_monthly.json), [final](finance_final.json) |
| October statement | Gross 1,230,332.43; aggregate-rounded fee 35,679.64 versus collected 35,679.50; override raises net by 0.14 | [published](finance_statements.json), [override](finance_overrides.json), SQL log `nvm-dbq-0000374529` |
| November 20 processor change | Payment callback adds 0.30 per transaction, not per accumulated header | `12e1c68`, [C1] |
| Actual same-day rollout evidence | Last observed percent-only payment November 20 **14:17:41 UTC**; first percent-plus-flat payment **14:27:41 UTC**. The monthly expectation instead uses November 20 **00:00 Eastern / 05:00 UTC** | [fee boundary](fee_boundary_summary.json), [C3]: `FEE_CHANGE_AT` |
| December 1 November statement | Already used collected fee 32,110.92; warning compares stale aggregate expectation 31,940.51 and reports −170.41. This is not proof that published November net was wrong by 170.41 | [warnings](statement_warnings.json), [published](finance_statements.json), `a92c96d` |
| December 2 audit | Expected-fee logic becomes date-sensitive and per-header rounded; `statement_corrections` records November delta **0.00**, not 170.41 | `4a58d17`, [audit correction](finance_corrections.json), SQL log `nvm-dbq-0001904091` |

Even the current **expected** fee is imperfect for replaying history: it calculates one flat fee per order header and chooses the rate by header creation time, whereas actual fees belong to callback/payment transactions and the observed deployment was intraday. The actual statement fee uses collected payment rows, so this diagnostic mismatch need not imply a wrong published fee. [C1], [C3], [fee boundary](fee_boundary_summary.json), [multi-item integrity](multi_item_integrity.json).

## A3. Published → corrected → final: authoritative bridge

| Month | Published gross | Published fee | Published net | Corrected net | Booked chargebacks | Final gross | Final net | Published count |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2019-09 | 2,702.00 | 78.36 | 2,623.64 | 2,623.64 | 0.00 | 2,702.00 | 2,623.64 | 12 |
| 2019-10 | 1,230,332.43 | 35,679.64 | 1,194,652.79 | 1,194,652.93 | 3,567.57 | 1,226,764.86 | 1,191,085.36 | 3,765 |
| 2019-11 | 1,101,397.01 | 32,110.92 | 1,069,286.09 | 1,069,286.09 | 0.00 | 1,101,397.01 | 1,069,286.09 | 3,582 |

**Evidence for every table value:** [published](finance_statements.json), [corrected](finance_corrected.json), [final](finance_final.json), [chargebacks](finance_chargebacks.json). October's final fee is 35,679.50; final view keeps corrected fee and count unchanged. [V].

The October explanation a finance veteran would give is:

> “The November deck used the originally published October net, 1,194,652.79. We corrected processor rounding by +0.14 to 1,194,652.93, then booked three chargebacks totaling 3,567.57 against October's original-order cohort. The approved restated net is 1,191,085.36. Use that for current finance reporting; retain the original for reproducing the old deck.” [C3], [override](finance_overrides.json), [chargebacks](finance_chargebacks.json), [final](finance_final.json).

The three chargebacks are order **46: 940.82**, **49: 1,891.94**, **55: 734.81**. Stored `reported_at` is December 1 at 12:00 UTC; the SQL that inserts them is logged December 9 at 15:00 UTC. The final view assigns them to the Eastern month of **order creation**, not reported/booking month. `created_at` in the final view remains the statement/override timestamp, not “time the final number last changed.” [chargebacks](finance_chargebacks.json), [V], SQL logs `nvm-dbq-0002221779`/`0002221780`.

**Final does not mean every possible current adjustment.** Its SQL only subtracts booked chargebacks from corrected snapshots. It does not re-evaluate all historical statuses or subtract every negative payment movement. For example, current October `status=1` gross is 1,206,337.32 and current header-fee net is 1,171,353.71; the 70 cancelled/refunded October headers total 23,995.11. These are a current-state cohort comparison, not another approved override. All 12 September headers now have status 2 or 3, but the original September statement still exists. [current reconstruction](statement_recomputed_current.json), [status cohorts](orders_month_status.json), [V].

**No December statement is present.** The available current-state December paid-order calculation is provisional: gross 552,328.93, fee 16,600.26, net 535,728.67. The log ends before the January monthly run. Do not substitute this provisional query into an official finance deck as if it were a published statement. [published statements](finance_statements.json), [recomputation](statement_recomputed_current.json), [job extent](data_extent.json), [C3].

## A4. Refunds have three distinct sources

| Mechanism | Data change | Time used by refunds dashboard | Known limitation |
|---|---|---|---|
| Cancel endpoint | Set status 2 and `updated_at`; no negative payment inserted | Header `updated_at` | Cancellation is counted as a refund-like amount even without evidence of cash returned. [C1], [V] |
| Original refund endpoint | Paid header → status 3; repeat call leaves status unchanged | Header `updated_at` | Full current header price is used; original endpoint does not record a refund amount/payment. [C1], [V] |
| Gateway webhook, introduced December 5 | Insert `gross=-amount, fee=0, net=-amount` | Payment `created_at` | Does not change header status or include a refund-id idempotency key; repeated webhook calls can add repeated movements. [C1], `c49a7bb` |

`refunds_unified`, introduced December 23, is a **`UNION ALL`**, not a deduplicated lifecycle ledger. It selects current statuses 2/3 plus payments where gross or net is negative; payment amount is `ABS(gross)` when gross is negative, otherwise `ABS(net)`. An order appearing in both branches could be counted twice; multiple payment refunds are multiple rows. In this snapshot the nine negative payments concern **three status-1 orders**, so no current status-branch overlap was found. [V], `a3bffec`, [overlap check](refund_status_overlap.json).

| Refund month | Kind | Rows | Amount |
|---|---|---:|---:|
| November | Cancelled status | 24 | 6,511.32 |
| November | Refunded status | 8 | 3,180.45 |
| December | Cancelled status | 30 | 6,738.32 |
| December | Refunded status | 20 | 10,267.02 |
| December | Gateway negative payments | 9 | 1,843.59 |

All values: [monthly refund query](refunds_monthly.json). Thus query 1 returns November **32 rows / 9,691.77** and December **59 rows / 18,848.93**, not 32 and 59 unique cash-refunded orders. Chargebacks are outside this view's definition. [R], [V].

## A5. Daily reporting history and reconciliation traps

The report scans yesterday's Eastern window, rejects statuses `0,2,3`, excludes IDs from `analytics.test_users`, then skips SKUs `1004856,1002544` and brands `lucente,jetem`. It counts lines when they exist, otherwise the legacy header; item timestamp controls the day. The intraday job uses the same logic from local midnight up to run time. Neither subtracts gateway-negative-payment rows. Status 6 is admitted. [C2].

| Change | Impact on interpreting historical reports | Evidence |
|---|---|---|
| Initial import, September 15 | Status exclusion only `[0]`; fetch first 500 matching rows; no SKU/brand exclusion | `2da4141` |
| October 8 | Test/internal SKUs 1004856 and 1002544 excluded going forward | `83fb3ed` |
| October 25 | Lucente hidden from reporting per partnership-related commit message; this is a reporting exclusion, not proof of no real sales | `ba1fbfa` |
| November 5 | Fix local-day end from start+24h UTC to next local midnight; prior November 3 output misses final local hour | `102c9b4`, [C2] |
| November 18 | Exclude cancelled/refunded statuses `2,3` in addition to `0` | `11c0a42` |
| November 19 | Replace `fetchmany(REPORT_SCAN_CAP)` with `fetchall`; constant 500 remains in constants but is unused by current report | `1233af8`, [C2] |
| November 22 → December 5 | Multi-item orders begin before reporting migrates to lines; temporary header-product allocation/item-count mismatch | `5d1300d`, `92596dc`, [line extent](data_extent.json) |
| November 27 | Exclude QA via `test_users` for report jobs; direct dashboards hardcode UID | `b59f077`, SQL log `nvm-dbq-0001684322`, [R] |
| December 8 | Intraday snapshot table/job introduced; snapshots overlap closed days after midnight | `a2e0013`, [C2] |
| December 15 | Jetem added to brand denylist and dashboard filters | `1169e40` |
| December 19 → 24 | Quick widget originally summed overlapping snapshots; fixed to latest closed days plus latest today | `686a5d6`, `3eced24`, Redash query 2 |

Observed checks distinguish a bug's existence from its proven magnitude:

- The November 3 report scanned **132** rows and published **123 units / 35,429.68** after filters. The omitted UTC hour `[2019-11-04 04:00,05:00)` contains **8 raw orders / 2,985.99**; this raw amount is not automatically the exact filtered reporting loss. [daily scan log](daily_scan_caps.json), [report snapshot](report_incident_days.json), [omitted hour](dst_missing_hour.json).
- November 17's run scanned exactly **500** rows and published **487 units / 148,857.07**. The cap is directly evidenced; the code fix does not establish that an old day's report was backfilled. October 5/6 snapshots have 128/121 units and should not be blamed on the cap without checking eligible source counts. [scan log](daily_scan_caps.json), [incident snapshots](report_incident_days.json), `1233af8`.
- Latest-per-day stored report revenue totals are September **2,702.00**, October **1,201,082.08**, November **966,974.33**, December **535,561.72**. December covers stored closed-day rows only through December 30. These totals mix historical report definitions and snapshots, so their difference from statements is not a single “missing revenue” adjustment. [monthly report aggregate](daily_reports_monthly.json), [C2], [job inventory](job_event_inventory.json).
- No repeated closed-day run timestamps were found by the version check; intraday usually has two timestamps per day, with only the initial December 8 evening batch on its first day. Rerun duplication remains a code-level risk even when this snapshot has no repeated closed-day batches. [version check](report_versions.json), [C2].

## A6. Answering “what was revenue in month M, and why?”

1. **Establish purpose:** original deck → `statements`; approved current finance → `statements_final`; movement/cash question → signed payments by movement date; filtered sales dashboard → its exact query. [C3], [R], [V].
2. **Select publication/as-of explicitly:** identify the statement run and override/chargeback rows known to the requested cutoff. Final-view `created_at` alone is not a restatement-as-of field. [V], [manual SQL](manual_sql.txt): `nvm-dbq-0000374529`, `nvm-dbq-0002221779`.
3. **Use Eastern month boundaries and correct grain:** aggregate headers independently; aggregate fees per order before joining; item category/brand allocations need line-first fallback. [C1]–[C3].
4. **Show the bridge:** published gross − published/overridden fees = corrected net; subtract booked chargebacks from the original order month. Treat the audit correction table as explanation, not an extra unconditional deduction. [V], [finance correction](finance_corrections.json).
5. **Explain residual differences:** current statuses, gateway refunds, QA/brand/SKU filters, historic bugs, item/header counts, catalog changes, and intraday snapshot duplication each produce different numbers. Do not force them into a universal revenue definition. [C1]–[C3], [R].

# Appendix B — Product and customer analytics in detail

## B1. Product identity, prices, and reporting dimensions

`products` is first-seen/current-state catalog data. Early inserts use `ON CONFLICT DO NOTHING`, and `_known_products` caches IDs per process. A product first observed without metadata can retain blank brand/category even when later activity contains better values. The October 21 brand-repair change updates blank brand/title on incoming catalog events; it does not constitute a comprehensive historical metadata backfill. [C1], `ea0e97b`.

The manually captured `blank_brand_products` table records both affected products and suspected causes; it is an investigative snapshot, not a live authoritative dimension. Product 1005174 was captured with blank brand and 1,929.69 revenue in that historical snapshot. Current direct brand reporting still has an empty-brand bucket: **124 items / 17,585.39** in the fixed 30-day example. The monthly brand-report function instead labels empty strings `unbranded`. [blank-brand evidence](blank_brands.json), [brand reproduction](brand_revenue_example.json), [C14], SQL log `nvm-dbq-0000110572`.

The vendor feed logged 200 accepted items on 13 weekly dates beginning October 7. Before the November 9 upsert fix, “accepted” did not imply existing prices were updated. Price history was introduced November 15; its first stored feed batch is November 18. The snapshot has **1,400 price-history rows for 241 products** through December 30. Historical sales value comes from line/header prices, not today's list price; an as-of list-price analysis must acknowledge missing pre-history and products outside the feed. [price-feed events](price_feed_history.json), [price-history extent](price_history_extent.json), `d213f6e`, `795d273`, [C1].

**Taxonomy evolution:** category mapping initially groups code prefixes into electronics, appliances, apparel, construction, kids, or other. December 12 adds history for lighting-tool and audio categories and changes dashboard selection to the latest valid mapping. It retains the old mapping rather than overwriting history, and the history source wins same-date ties. However, the actual six new mappings carry 2026 effective dates, so a query for 2019 must retain the old group until those stored dates. [R], `2814b3d`, `33054cd`, [mapping rows](category_mapping.json), [history rows](taxonomy_changes.json).

**Current product metadata is still joined to historical items.** Effective-dating the display-group map does not make `products.category` or `products.brand` historically versioned. A later product metadata repair can change historical reporting. Brand NULLs also differ from empty strings: `NOT IN` does not admit NULL in SQL, whereas an empty string can become a visible blank group. [R], [C1].

## B2. Why best-seller and brand/category numbers disagree with finance

- The direct dashboards intentionally include all statuses, including held/cancelled/refunded headers, and do not net negative payments. The nightly top-sellers job requires status 1 and counts headers. The report job has additional test-SKU exclusions. These are independent metric definitions. [R], [C2], [C9].
- The fixed best-sellers example includes **SKU 1002544**, even though it is excluded from daily reporting: **10 units / 4,498.52**. Brand revenue includes an `internal` brand bucket of **60 units / 7,624.89** because its denylist is specifically Lucente/Jetem. Do not silently add cleanup rules when asked to reproduce the official query. [best-seller result](best_sellers_example.json), [brand result](brand_revenue_example.json), [C2].
- The brand UUID exclusion is redundant for the inspected numeric `orders.user_id` namespace: the smoke account's UUID is an account identity, not a value stored in order-user ID. The numeric exclusion does the actual filtering in this schema. [W], Redash query 8, [QA identity event](qa_identity_log.json).
- Current monthly brand-report code allocates the entire header to `orders.product_id`, unlike line-aware dashboards. A merged order spanning brands can therefore produce different brand totals without a money-sum discrepancy. [C1], [C14], [R].
- KPI daily customer counts use the header's product brand and header creation day, while KPI revenue uses item products/timestamps inside snapshot generation. A multi-item order spanning brands or midnight can split these definitions further. [C1], [C2], Redash query 7.

## B3. Snapshot composition, the revenue widget, and incomplete days

For a closed date choose one batch timestamp across the entire date, then sum its product rows. For today choose only the latest intraday timestamp. **Do not choose the latest timestamp independently for each product**: products absent from a newer run would leak in from old runs. Do not include prior-day intraday totals alongside completed reports. The current Redash queries implement date-level maximum timestamp selection. [C2], Redash queries 2/7.

The widget's fixed December 25–31 result is **139,598.13**, while summing all matching daily and intraday snapshots would produce **371,872.10**. This reproduces the structural double-counting problem fixed December 24. Current query 7 additionally filters current product brands; query 2 relies on filters already applied when reports were written. Both can omit a date when no rows were published rather than emitting a literal zero, because neither builds a complete date spine. [widget comparison](revenue_widget_example.json), [R], `3eced24`.

The KPI row for “today” combines partial sales at the last intraday run with customer counts read live across that day's available orders. Those are not guaranteed to share an exact data cutoff. Verify run timestamp and completeness before explaining an apparent intraday conversion or revenue-per-customer change. [C2], Redash query 7.

## B4. Customers, signups, identity, and contactability

**Numeric users are first-seen shoppers.** `ensure_entities` and the product-view route create users without a signup action. Their `created_at` measures first ingestion on that path. Synthesized region/channel/device/age/opt-in values support code execution but cannot substantiate real-world marketing segmentation quality. [C1], [C4].

**Accounts are a separate UUID namespace.** `create_account` bootstraps a missing numeric user, reads that user's email, creates a UUID account, and writes `account_map(uid,account_id,linked_at)`. There is no per-UID uniqueness guard in the shown account creation logic. In the snapshot all **30 links are valid and emails agree**, with enrollment events at **2019-12-01 16:30 UTC**. [C4], [mapping check](account_map_consistency.json).

**Registered conversion history:** the December 10 query incorrectly compared UUID account strings to numeric order-user strings, returning no matches in this data. December 21 changes the dashboard to distinct numeric users matched via shared email, then joins paid orders. It intentionally includes pre-registration purchases and computes neither eligible registrations nor a denominator/rate. The correct current dashboard yields **30 buyers / 18,155.71**, including **63 pre-enrollment paid orders**. The explicit `account_map` is available for durable identity work, but changing query 4 to use it would be a definition change; first verify equivalence and handle repeated enrollments/email edits. `d6e34c6`, `b975479`, [bad join](registered_bad_join.json), [correct result](registered_counts.json), [mapping check](account_map_consistency.json), [R].

**Contactable is not merely “email changed.”** Forty email-update events occurred October 23; the snapshot has 38,910 `example.com` addresses and 40 `gmail.example` addresses, with 23 of the latter opted in. The trusted view excludes both domains, producing zero. The digest's simple `NOT LIKE '%@example.com'` count produces 40, despite the comment calling them contactable. The email-update endpoint stores supplied email without format validation and does not propagate changes to already-created account rows in the shown code. [C4], [C8], [email domains](email_domains.json), [event inventory](app_event_inventory.json), [V].

**Board zero is explainable, not proof of no shoppers.** At the fixed anchor, the paid-only rollup definition yields 1,146; allowing statuses other than 0/2/3 yields 1,151 candidates before board cleanup; all current emails then fail board example-domain rules. The board query also admits missing user-email records via `COALESCE('',...)` unless another filter removes them, so it is not a universal trusted-user definition. [active comparison](active_counts.json), Redash query 3.

**Funnel is activity sessionization, not a conversion funnel.** It merges only cart and order events by numeric user and timestamp over the preceding day, ignores the stored session string, counts a new session when inactivity exceeds the configured gap, and records sessions plus distinct users. The gap changes from 30 to 120 minutes on December 14; logs first show 120 on December 15. No view→cart→purchase conversion stages are computed. [C5], `f915c1b`, [parameter history](job_parameter_history.json).

# Appendix C — Recommendation and heuristic systems

## C1. Version history: code, production evidence, and naming

| Period / change | Producer / behavior | Serving and observed evidence |
|---|---|---|
| October 12 affinity added | Directed co-cart pairs over 30 days, exponential decay | First refresh log October 13; table `product_affinity`. `776d674`, [C7], [job inventory](job_event_inventory.json) |
| October 26 widget v1 | Read nonnegative affinity top 5; fallback to seven-day paid-header best sellers directly | Both intended/effective labels remain 1.0.0 even on fallback. `f1217a8`, [decision groups](rec_versions.json) |
| November 12 graduation gate | Pairs seen fewer than 3 get −1 | First `min_pairs=3` run November 13; higher fallback can follow a qualification change without a service outage. `fef5c96`, [parameter history](job_parameter_history.json) |
| December 2 affinity-v2 added | Conversion-weighted scores, category/price-ratio features and seasonal factor list | Job crashes December 3–5 before successful refresh because list has only January–November entries. `89666bf`, [crash logs](job_errors.json) |
| December 5 fix | Default missing seasonal month to 1.0; writer stamp becomes 2.0.1 | First successful v2 refresh December 6 08:45 UTC. `3dbe4d7`, [job inventory](job_event_inventory.json) |
| December 6 serving v2 + random arm | Intended serving version 2.0.0 selects affinity-v2 table; random arm and trending fallback introduced | Last old-table app read December 6 **16:39:58 UTC**; first v2 app read **16:40:11 UTC**, closely matching the 16:40 commit timestamp. `df4ed85`, [readers](affinity_readers.json) |
| December 14 v4 trainer added | Logistic training on random-arm decisions; writes registry/model scores | First training December 15; no observed v4 serving. `a1946ff`, [registry](model_registry.json), [decisions](rec_versions.json) |
| December 17 refactor | Random arm returns before decision-table insert | App serves continue, decision rows disappear for affected period. `30e8907`, [gap](rec_logging_gap.json) |
| December 19 fix + cache | Random insert restored; six-hour cache keyed only by base product, including empty lists | Empty cached results can keep causing fallback, and refresh does not invalidate yet. `a00f24c`, [decision groups](rec_versions.json) |
| December 26 cache repair | Key includes table; nonempty-only cache; invalidate on max score timestamp; read newest batch | New SQL reads and max-timestamp probes begin December 26 20:00 UTC. `8ed2971`, [readers](affinity_readers.json) |

No observed serving version 3 is present. The enum includes retired v1, active v2, and flag-gated v4; table writer patch version `2.0.1` is a different namespace from serving `2.0.0`. `docs/rec_versions.md` contains only `TBD`, so it cannot resolve these distinctions. [C6], [C7], [C12], [decision groups](rec_versions.json).

## C2. Affinity formulas and data assumptions

For each directed `(base_pid,rec_pid)` pair, v1 counts cart-row combinations sharing `session` with different products. Only the first alias's timestamp has the 30-day lower bound; the join does not additionally require equal user IDs or bound the second alias's time. Repeated cart events can therefore multiply pair counts; these are not necessarily distinct users/sessions. With at least three pairs:

```text
v1 score = pairs × exp(−0.05 × days_since_latest_base_cart)
otherwise score = −1
```

This follows the actual SQL/Python, not an assumption of a conventional collaborative-filtering implementation. Also, `cart_items` is not an immutable activity ledger: `/cart/remove` deletes matching user/product/session rows. Such removals can change subsequent affinity/funnel inputs, although no `cart_item_removed` event appears in the observed app-event inventory. [C7]: `affinity.py:34–50`; [C1]: `carts.py:23–30`; [event inventory](app_event_inventory.json).

V2 adds a conversion count for joined cart rows whose recommended-product user has **any paid header** with that product, without a post-cart condition or attribution window. It counts headers rather than `order_lines`, so non-header items of merged purchases may be missed. For qualifying pairs:

```text
raw = (pairs + 3 × converted_cart_rows) × exp(−0.05 × age_days)
if same nonempty category: raw *= 1.15
if recommended/base current list-price ratio > 4 or < 0.25: raw *= 0.7
score = round(raw × monthly_factor, 4)
```

Below three pairs the sentinel is still −1. The factor array covers January–November; current December fallback is 1.0. These are hand-set weights and eligibility rules, not learned v2 coefficients. [C7]: `affinity_v2.py:13–60`.

The latest v1 and v2 snapshots each contain **3,912 pairs / 1,476 base products**, with **2,964 sentinels**. V4 scores cover **948 pairs / 449 base products**. This supports a coverage explanation for high fallback, but does not prove each missing-serving result is solely caused by the sentinel gate. [score health](score_health.json), [C6].

## C3. Serving, fallback, cache, and logs

Current non-random serving selects up to five `score>=0` recommendations from the latest whole-table timestamp, ordered by score. It then filters excluded SKUs **after** SQL `LIMIT 5`; it does not refill a short nonempty list. It neither filters the brand denylist nor checks product stock in this path. When the resulting list is empty it uses five products from the latest trending day, without reapplying those excluded-SKU filters. The random pool excludes the two SKUs but does not explicitly exclude the base product. [C6].

Observed decision mix:

| Intended version | Source/effective path | Decisions | Interpretation |
|---|---|---:|---|
| 1.0.0 | Affinity | 66,444 | Legacy model served |
| 1.0.0 | Fallback, effective still 1.0.0 | 326,186 | 83.08% of all v1 decisions were fallback |
| 2.0.0 | Model, uncached | 31,268 | Affinity-v2, not learned-v4 |
| 2.0.0 | Model, reason `cache` | 21,427 | Cache is a retrieval path, not necessarily a fallback |
| 2.0.0 | Fallback, `no_scores` | 182,868 | No eligible scores on that path |
| 2.0.0 | Fallback, `cache` | 25,091 | Historical cached-empty-result fallback |
| 2.0.0 | Random arm | 14,566 | Logged random exposures; hole means not all served random exposures |

All counts and dates: [decision groups](rec_versions.json). V2 non-random fallback rate is `(182868+25091)/(182868+25091+31268+21427)=79.78%`. No empty lists were found in logged decisions, but short model lists were common. [list-size query](rec_incomplete_lists.json).

`rec_decision_log` stores timestamp, numeric user, base product, comma-separated item IDs, intended/effective version, source, reason, arm. The app's `rec_served` event stores session, item count, source and arm, but not item IDs or the model coefficient/batch version. Thus app logs establish that missing random exposures were served, but cannot alone supply the exact lost decision-table rows; reconstruction would also need the historical product pool and deterministic shuffle inputs. [C6], [gap samples](rec_gap_samples.json).

**Cache freshness boundary:** `MAX(updated_at)` changes as soon as the first new autocommitted row appears. A reader can observe a partial new score batch, cache an incomplete result, and retain it because later rows use the same timestamp. If the table is temporarily empty, the epoch check does not advance. Atomic publication or a completed-batch marker is therefore a justified future change; the current epoch fix does not prove all refresh races are eliminated. [C6], [C7], [C10].

## C4. What v4 actually learns and emits

The trainer reads all `arm='random'` decisions. Its actual feature vector is:

1. served item count;
2. current base list price / 1,000;
3. all-history paid header popularity of base product / 100;
4. `min(account_age_days/60,1)`;
5. indicator that signup channel is organic. [C7]: `model_train.py:30–57`.

Base stock and opt-in are fetched but unused. Region affinity, device mix, stock and marketing opt-in claimed by the README are not in the five-element vector. Account age uses the numeric user's creation timestamp, not UUID enrollment time. [C4], [C7], [C12].

At least 20 rows and both classes are required for `LogisticRegression(random_state=0,solver='lbfgs')`. If insufficient/single-class, the job still appends a registry row noting that condition and leaves existing model scores untouched. A `model_trained` event by itself therefore does not establish new scores or a fitted model. In the observed 17 entries, coefficients are present; December 18 and 19 both use 5,798 rows, consistent with the logging gap freezing new random decision input while labels/features can still change. [C7], [registry](model_registry.json), [gap](rec_logging_gap.json).

Scoring uses only coefficient zero:

```text
model_score(base,rec) = round(affinity_v2_score(base,rec) × (1 + 0.1 × w_item_count), 4)
```

The other coefficients and intercept do not affect output. On December 31, `w_item_count=-0.24483754375789174`, giving multiplier **0.9755162456**. The observed score ratios range **0.975450970–0.975558015**, consistent with four-decimal rounding. This is why “trained v4” should not be described as demonstrated better personalization or ranking. [C7], [registry](model_registry.json), [ratio check](model_score_ratio.json).

## C5. Other scheduled algorithms

| System | Actual algorithm / history | Trust boundary |
|---|---|---|
| Trending | Paid headers in rolling window; `units*exp(-0.05*age_since_last_order)`; minimum 5, top 50. Window changes 60→30 on December 6, observed runs December 7 onward | No item-line migration or QA/brand/SKU filter; fallback can be stale after failures. [C9], `f563dea`, [parameter history](job_parameter_history.json) |
| Fraud | `core=min(price/3000,1)`; multiply by `1+0.15*new_account+0.15*high_velocity`, cap at 1; new account <7 days; high velocity counts ≥3 headers in preceding 24h including current order | Rule score, no labeled-validation evidence. Scans paid headers from previous day; high-velocity subquery has no status filter. [C8] |
| Fraud threshold | Initial 0.90; 0.70 after December 5; 0.85 after December 29. Latest snapshot still has 12 held headers | December 29 manual `status=6 AND price<2600` release is separate from future scoring threshold; not a model retrain. `e4656fb`, `53f6f6c`, `1cb8721`, [parameter history](job_parameter_history.json), SQL log `nvm-dbq-0003446400` |
| Dynamic pricing | Top 500 current products by 14-day paid-header volume; median-position count threshold; +5% above it, −5% otherwise; replace suggestions nightly | Phase 2 held December 2. No app/job SELECT consumer observed; actual order price still callback-supplied. [C8], `894c535`, `cca9b0d`, [readers](shadow_reads.json) |
| Reorder hints | Top 200 paid-header products; velocity=`COUNT(*)/14`; `int(15.6+K/(velocity+1.8))`; K 141.12→162.4 on December 21 | Larger hint for slower velocity; ignores stock, lead time, POs, seasonality, price, budget. Explicitly advisory. Latest range 0.0714–2.7143 velocity and 51–102 hints, differing from the earlier prose snapshot. [C8], `f5e3032`, `f85cdd2`, [latest snapshot](reorder_snapshot.json) |
| Digest | Seven-day paid-header top product; count non-`@example.com` addresses; append aggregate log | Comment “contactable” is misleading; no email transport in job. Initial `DIGEST_ON`/`ENABLE_DIGEST` mismatch fixed December 9, direct env-file reading December 16; first observed sends December 17. [C8], `c19a307`, `8dc520b`, `0bd4eac`, [job inventory](job_event_inventory.json) |

**Can old affinity be retired?** For the pinned widget, yes as a candidate cleanup: current serving reads v2/model scores and the trainer reads v2. The query history shows old-table app reads only before the December 6 switch; both jobs remain scheduled. That establishes no current consumer **within the inspected repository/log period**, not a universal absence of external consumers. Preserve rollback expectations and validate consumers before a future removal. [C6], [C7], [C11], [readers](affinity_readers.json), [C12].

# Appendix D — Scheduled jobs and safe pipeline changes

## D1. Schedule, output, and failure matrix

Schedules below are the literal **pinned Airflow cron fields**. Retired cron says its times were local. Airflow wrappers use naive `start_date` and no explicit timezone, so actual runtime timezone depends on scheduler configuration that was not observed. Every wrapper has `catchup=False`; each has a single BashOperator calling its module. The observed 2019 runs belong to the prior scheduling era. [C11], [job inventory](job_event_inventory.json).

| Job / Airflow schedule | Inputs → output | Write/rerun semantics | What a failure or stale output affects |
|---|---|---|---|
| reconcile — `0 3 * * *` | Header payment-reference groups excluding status 5 → warning/job logs | Read/log only; repeat warnings for same unresolved references | Duplicate detection, not automatic finance repair. [C10] |
| affinity — `30 3 * * *` | 30-day co-cart rows → `product_affinity`; creates decision-log table if needed | Delete all then insert, autocommit | Legacy/rollback scores; no current widget consumer found. [C7], [C10] |
| affinity_v2 — `45 3 * * *` | Co-carts, paid headers, current catalog → `product_affinity_v2` | Delete all then insert | Current widget quality/coverage; model-train candidate input. [C6], [C7] |
| model_train — `15 4 * * *` | Random decisions, users/products/orders, v2 candidates → registry + model scores | Registry append; delete/replace scores only after successful qualifying fit | Future flag-gated v4; a successful run can still leave old scores when insufficient data. [C7] |
| price_suggest — `45 4 * * *` | 14-day paid headers/current prices → `price_suggestions` | Delete/replace | Shadow analytics only within observed consumers. [C8], [readers](shadow_reads.json) |
| trending — `15 5 * * *` | 30-day paid headers → `trending_daily` | Delete that day then insert; retains other days | Current fallback list; latest-day serving has no freshness threshold. [C6], [C9] |
| fraud_score — `45 5 * * *` | Paid headers in trailing day + user age/velocity → `order_risk`, header holds | Append scores, change statuses; rerun is state-dependent | Paid-only finance/KPIs/ranking versus reports that admit held orders. [C8] |
| daily_report — `0 6 * * *` | Yesterday's local item stream/current status/catalog/test users → `report_rows` | Append product batch; same timestamp rerun can duplicate rows | Closed-day dashboard sales; newer timestamps selected by latest-batch consumers. [C2], [R] |
| kpi_daily — `15 6 * * *` | Trailing-30-day paid headers → `kpi_daily` | Append | Saved nightly active metric; do not sum repeated run counts. [C5] |
| funnel — `20 6 * * *` | Trailing-day cart+header events → `daily_funnel` | Append | Session/activity history; gap-definition changes break comparisons. [C5] |
| monthly_statement — `30 6 1 * *` | Prior Eastern month's currently paid headers + linked fees → `statements` | Append | Published/corrected/final finance; views do not deduplicate repeated base snapshots. [C3], [V] |
| top_sellers — `45 6 * * *` | Yesterday paid header product counts → `top_products` | Append | Nightly units ranking; not direct Redash best sellers. [C9], [R] |
| reorder_forecast — `50 6 * * *` | 14-day paid-header velocity → `reorder_hints` | Delete/replace | Advisory merchandising hints; no durable output history. [C8] |
| email_digest — `15 7 * * *` | Flag, 7-day paid-header top product, loose email count → `digest_log` | Append when enabled; silent return when disabled | Aggregate digest record; absence can be flag suppression rather than failure. [C8] |
| intraday_report — `0 12 * * *` | Today midnight→run time, same filtering as report → `report_rows_intraday` | Append snapshot | Today's KPI/widget. **17:00 retired-cron run is absent from this DAG.** [C2], [C11] |
| warehouse_backfill — manual (`schedule=None`) | Manifest-listed PostgreSQL tables → CSV staging → BigQuery replace loads | Per-table export/load, destructive replace by job design | Warehouse freshness/schema; not a continuous sync or cross-table atomic snapshot. [C12] |

The discounts helper and `scripts/rerun_kpis.py` are not scheduled DAG jobs. The script's manually filled row list is currently empty; it only prints discounted rows and does not repair warehouse/report tables. [C13], [C11].

## D2. Incidents, silent failures, and misleading success indicators

- **Affinity-v2:** three crash logs explicitly show `IndexError` at the seasonal array lookup on December 3–5 (`nvm-job-0000000480`, `0000000492`, `0000000505`); successful refresh starts December 6. Because the failure happens before the write stage, it does not prove a partial table rewrite on those particular days. [job errors](job_errors.json), [C7], `3dbe4d7`.
- **Digest:** no observed digest runs until December 17, despite a November introduction and December 9 flag-name fix. The December 16 direct-read fix and first December 17 event establish that “scheduled” and “enabled successfully in runtime” were different. [job inventory](job_event_inventory.json), `8dc520b`, `0bd4eac`.
- **Reconcile backup overlap:** the November 10 commit moves 02:00→03:00 and mentions backup overlap. Observed mean duration rises from about **4.17 ms** before November 11 to **5.74 ms** after, maximum **9.8 ms**; there are no reconcile errors in the error query. The logs do not support describing this as a large observed outage or proving backup contention causally. `388370b`, [performance](reconcile_performance.json), [errors](job_errors.json).
- **Model training:** `model_trained` is emitted even for insufficient/single-class input; registry content and score freshness must accompany the event. [C7].
- **Report “success”:** November 17's capped 500-row report emitted normal `report_generated`; success did not establish completeness. A failed partial append under autocommit could similarly leave a max-timestamp batch that dashboards select. [scan log](daily_scan_caps.json), [C2], [C10], [R].
- **CI green:** the pinned CI exercises one simple view/cart/order and three jobs, assumes equal payment/order counts in that tiny fixture, and does not establish multi-item, refunds, ML serving, statement restatement, or dashboard correctness. CI also mutates scratch data, so it was inspected, not executed during this read-only investigation. [C14].

## D3. Operational pitfalls to resolve before a future change

1. **Make output publication atomic or versioned.** `job_connect()` uses `autocommit=True`; delete/reinsert jobs expose empty/partial tables, while partial newer append batches can eclipse complete older ones. A future design should publish a completed batch marker or atomically swap a prepared batch, and consumers should validate completion. [C10], [C2], [C6]–[C9].
2. **Define rerun keys and semantics.** Statements, daily/intraday reports, KPI, funnel, top products, risk, registry and digest outputs append. Replaying the same timestamp can create indistinguishable duplicates; a later timestamp changes latest-batch selection. Corrected/final views retain every base statement row. [C2], [C3], [C5], [C7]–[C9], [V].
3. **Pass a deliberate logical clock.** Airflow invokes modules without setting `FAKE_NOW`; jobs use wall clock. Several rolling SQL predicates have only a lower bound and no `<run_ts` upper bound, and catalog/status joins use current values. Setting `FAKE_NOW` on a present database is not a sufficient historical backfill strategy. [C2], [C5], [C7]–[C11].
4. **Enforce actual dependencies.** Training follows affinity-v2 by schedule only; trending supplies serving fallback; fraud runs before report/KPI but after trending/pricing/model training. Independent wrappers permit overlap/failure and different status cutoffs across consumers. Use freshness/completion prerequisites for a future pipeline extension. [C11], [C6]–[C9].
5. **Check relative working directory and environment.** Recommendation flags and digest env-file reads are relative to `deploy/`; wrappers do not set a working directory or load that file. Missing recommendation file defaults to v2; explicit `ENABLE_DIGEST` environment overrides `DIGEST_ON`, which overrides the file value. [C6], [C8], [C11].
6. **Do not treat the pinned backfill wrapper as runnable completeness.** The module requires `--project`, `--instance`, and `--staging`, but its DAG supplies none. It maps analytics to the wrong dataset for this estate, and the manifest covers base tables, not view/log construction. It uses `bq load --replace`, so rerun semantics are replacement, not incremental append. [C12], [W].
7. **Fix the discount-call contract before using the rerun helper.** `DISCOUNT_CAP=0.25`, but `apply_discounts(rows,cap=0.40)` defaults to 40% and the helper omits the argument. For 100 revenue, the helper retains 60 instead of 75. No evidence shows normal daily/monthly reports call this helper, so do not attribute their current totals to that discount bug. [C13], `35c581e`.
8. **Migrate the whole schema contract.** `schema.sql` omits later `order_lines`, payment reference additions, analytics tables/views and account identity structures. A new environment or pipeline relying only on that file can miss prerequisites; the affinity job currently creates `rec_decision_log`, for example. [C1], [C7], [C12], [W].

## D4. Read-only change-planning checklist

For a future authorized implementation, first capture the consumer query and data grain; compare fixed-anchor old/new SELECT results; quantify duplicate keys, missing links and timestamp bounds; identify all observed readers; decide whether history is restated or preserved; define atomic publication and rollback; and validate outputs rather than merely exit status. In particular, use a line-aware cohort for item changes, a statement bridge for finance changes, and exposure/source/batch tracking for recommendations. These steps follow directly from the observed mismatches above. [C1]–[C3], [C6], [C10], [R], [line check](multi_item_integrity.json), [reader inventory](affinity_readers.json).

Concrete acceptance comparisons should include: header totals versus line totals; signed payment balance; one intended report/statement batch per key; no accidental QA/brand/status/window changes; complete score batch plus coverage/fallback; and declared behavior for late refunds, post-publication status changes, missing catalog metadata and empty output dates. These are proposed checks, not tests already executed against a modified system. [payment check](financial_integrity.json), [line check](multi_item_integrity.json), [V], [R], [C6].

# Appendix E — Data dictionary and migration lineage

**All warehouse table/column names below were directly inventoried.** “Grain” describes the writer/observed shape, not an assertion that BigQuery enforces a primary key. PostgreSQL serving keys may differ from exported constraints. [W], [C1]–[C12].

| Dataset/table | Grain and important fields | Producer / consumer |
|---|---|---|
| `novamart.users` | Numeric ID; current email/profile; first-seen `created_at` | Bootstrap/account/email code; activity/contactable/training/fraud. [C1], [C4] |
| `novamart.accounts` | UUID account; enrollment email/time | Accounts module; registered dashboard. [C4], [R] |
| `novamart.account_map` | Numeric UID↔UUID link/time; do not assume unique UID | Accounts module; explicit identity bridge. [C4] |
| `novamart.products` | Product ID; current brand/category/vendor/list/cost/stock | Bootstrap/feed/brand repair; reporting/ML. [C1] |
| `novamart.cart_items` | Stored cart-add row; user/product/session/time; remove endpoint can delete it | Cart API; affinity/funnel. [C1], [C5], [C7] |
| `novamart.orders` | Header ID; first product/ref, accumulated price, current status, creation/update | Order/cancel/refund/fraud/manual release; most jobs. [C1], [C8] |
| `novamart.order_lines` | Callback/item line; order/product/price/session/ref/time | November 22 order path; item-aware reporting. [C1], [C2] |
| `novamart.payments` | Payment ID; order, signed gross/fee/net, optional ref, movement time | Order callback/gateway refund; finance/unified refunds. [C1], [C3], [V] |
| `novamart.report_rows` | Report date × product × run timestamp | Daily report → query 7/2. [C2], [R] |
| `novamart.report_rows_intraday` | Report date × product × partial-run timestamp | Intraday → query 7/2. [C2], [R] |
| `novamart.statements` | Month × publication run | Monthly job → corrected/final finance. [C3], [V] |
| `novamart.top_products` | Report date × rank × run | Top-sellers job; separate from Redash best sellers. [C9], [R] |
| `novamart_analytics.blank_brand_products` | Captured investigative product snapshot, units/revenue/cause | Manual backfill log `nvm-dbq-0000110572` |
| `novamart_analytics.category_names` | Baseline category-code mapping with `valid_from` | Manual prefix backfill → category dashboard. [R], SQL log `nvm-dbq-0001827865` |
| `novamart_analytics.category_name_history` | Category-code/display-group/effective-date row | Manual taxonomy additions → as-of category join. [R], SQL log `nvm-dbq-0002395860` |
| `novamart_analytics.chargebacks` | Booked order amount and reported time | Manual finance booking → final view. [V], SQL log `nvm-dbq-0002221779` |
| `novamart_analytics.daily_funnel` | Day/run sessions and distinct active users | Funnel job. [C5] |
| `novamart_analytics.digest_log` | Run time, recipient count, top product | Digest job; aggregate emission record. [C8] |
| `novamart_analytics.kpi_daily` | Day/run trailing active-customer count | KPI job. [C5] |
| `novamart_analytics.model_registry` | Version/run, serialized coefficients/note, train count | Trainer; audit of fits, not full model data snapshot. [C7] |
| `novamart_analytics.model_scores` | Latest base/recommended pair score/time | Trainer → flag-gated v4 serving. [C6], [C7] |
| `novamart_analytics.order_risk` | Order scoring event/core/flags/score/time | Fraud job; repeated scoring can append. [C8] |
| `novamart_analytics.price_history` | Product/vendor-feed list price/effective timestamp | Catalog feed after November feature. [C1] |
| `novamart_analytics.price_suggestions` | Latest product/current/suggested price/demand/time | Shadow job; no observed SELECT consumers. [C8], [readers](shadow_reads.json) |
| `novamart_analytics.product_affinity` | Latest directed pair/score/pair count/time | Legacy affinity; historical v1. [C7] |
| `novamart_analytics.product_affinity_v2` | Same plus writer model-version string | Current affinity producer → widget/trainer. [C6], [C7] |
| `novamart_analytics.rec_decision_log` | Served decision record; comma-separated items; source/version/arm | Similar API → random-arm training/analysis. [C6], [C7] |
| `novamart_analytics.reorder_hints` | Latest product/velocity/hint/time | Advisory reorder job. [C8] |
| `novamart_analytics.statement_corrections` | Audit month/delta/reason | Manual audit; not directly consumed by corrected/final view. [V], SQL log `nvm-dbq-0001904091` |
| `novamart_analytics.statement_overrides` | Replacement values by month, publication-style time/note | Manual finance correction → corrected view. [V] |
| `novamart_analytics.test_users` | Numeric excluded user IDs | Manual QA seed; report/board cleanup. [C2], [R], SQL log `nvm-dbq-0001684322` |
| `novamart_analytics.trending_daily` | Day/rank/product/score/units/run time | Trending → current fallback. [C6], [C9] |
| `novamart_analytics.contactable_users` **view** | Current users meeting opt-in/email predicate | Executive contactable counts. [V], [R] |
| `novamart_analytics.refunds_unified` **view** | Status reversal or negative-payment union row | Monthly refunds query. [V], [R] |
| `novamart_analytics.statements_corrected` **view** | Every base statement row with month override applied | Intermediate restatement layer. [V] |
| `novamart_analytics.statements_final` **view** | Corrected statement less original-order-month chargebacks | Current finance query 5. [V], [R] |
| `novamart_logs.db_queries` | Exported log row, `insertId`, timestamp, raw SQL `textPayload` | Historical app/job/manual SQL lineage. [C10], [log sample](logs_sample.json) |
| `novamart_logs.app_events` | JSON event payload plus export metadata | Order/refund/email/account/recommendation events. [C10], [event inventory](app_event_inventory.json) |
| `novamart_logs.job_runs` | JSON job events, summaries/errors, export metadata | Operational evidence; 978 log rows, not 978 distinct runs. [job inventory](job_event_inventory.json), [extent](data_extent.json) |
| `novamart_logs.db_queries_normalized` **view** | Imported SQL exposed as query-history-like columns | Convenience lineage; imported statement text remains PostgreSQL SQL. Sample bytes/slot counters are null and state is DONE even though raw logging itself is pre-execution. [normalized sample](logs_normalized_sample.json), [C10] |

Migration history matters operationally: `d398b0d` documents moved data access; `41e3537` removes dashboard SQL files into Redash; `4bfcbe6` retires cron and adds Airflow wrappers; pinned `5ae1182` adds the manifest-driven warehouse copy. Local subsequent commits `99003c3` and `20e066f` correct the analytics dataset name. Nothing in the inspected exporter creates the four analytics views or populates log exports, and the observed warehouse object inventory is broader than its manifest. [C11], [C12], [W], [Git evidence](git_evidence.json).

# Appendix F — Read-only reproduction cookbook

All examples are **SELECT-only**. Every saved query-result JSON includes its exact SQL, completion flag, total row count and returned rows. Reproductions freeze the clock where stated; no Redash refresh was used. The full fetched dashboard definitions are preserved in [redash_queries.sql](redash_queries.sql). [R], [query collection code](inspect_sources.py), [named investigation queries](query_suite.py).

## F1. Explain a statement without joining raw line/payment detail

This reproduces the published/corrected/final bridge while retaining every publication row. For an old-deck answer, select the requested original publication rather than assuming “latest” means “original.” [C3], [V], [published](finance_statements.json).

```sql
WITH cb AS (
  SELECT FORMAT_TIMESTAMP('%Y-%m', o.created_at, 'America/New_York') AS month,
         SUM(c.amount) AS chargebacks
  FROM `novamart-warehouse.novamart_analytics.chargebacks` c
  JOIN `novamart-warehouse.novamart.orders` o ON o.id = c.order_id
  GROUP BY 1
)
SELECT s.month, s.created_at AS published_at,
       s.gross AS published_gross, s.fee AS published_fee,
       s.net AS published_net,
       COALESCE(ov.fee, s.fee) AS corrected_fee,
       COALESCE(ov.net, s.net) AS corrected_net,
       COALESCE(cb.chargebacks, 0) AS chargebacks,
       ROUND(COALESCE(ov.net, s.net) - COALESCE(cb.chargebacks, 0), 2) AS final_net,
       ov.note
FROM `novamart-warehouse.novamart.statements` s
LEFT JOIN `novamart-warehouse.novamart_analytics.statement_overrides` ov
  ON ov.month = s.month
LEFT JOIN cb ON cb.month = s.month
WHERE s.month = '2019-10'
ORDER BY s.created_at;
```

For an official current monthly number, the shortest authoritative query is `SELECT * FROM novamart-warehouse.novamart_analytics.statements_final WHERE month='2019-10'` with the fully qualified table enclosed in backticks. Its executed all-month equivalent is [finance_final.json](finance_final.json). Do not subtract the unified-refunds dashboard total again without a separately defined reconciliation policy. [V], [C3].

## F2. Canonical item stream, with an explicit analysis clock

This is the lineage shared by the best-seller/brand/category reproductions. Carry order ID and reference when translating category lateral joins so each item can select one effective mapping; payment reference alone is not globally safe across historical duplicate headers. [C1], [R], [duplicates](duplicate_refs.json).

```sql
WITH item_orders AS (
  SELECT o.id AS order_id, o.user_id, o.status,
         ol.product_id, ol.price, ol.created_at, ol.payment_ref
  FROM `novamart-warehouse.novamart.orders` o
  JOIN `novamart-warehouse.novamart.order_lines` ol ON ol.order_id = o.id
  UNION ALL
  SELECT o.id, o.user_id, o.status,
         o.product_id, o.price, o.created_at, o.payment_ref
  FROM `novamart-warehouse.novamart.orders` o
  WHERE NOT EXISTS (
    SELECT 1 FROM `novamart-warehouse.novamart.order_lines` ol
    WHERE ol.order_id = o.id
  )
)
SELECT io.product_id, COUNT(*) AS units, SUM(io.price) AS revenue
FROM item_orders io
JOIN `novamart-warehouse.novamart.products` p ON p.id = io.product_id
WHERE io.created_at >= TIMESTAMP('2020-01-01 00:00:00+00') - INTERVAL 7 DAY
  AND io.user_id <> 424242
  AND p.brand NOT IN ('lucente', 'jetem')
GROUP BY 1
ORDER BY revenue DESC
LIMIT 20;
```

The missing upper bound, missing status condition, and absence of test-SKU exclusion deliberately match query 9. For a new as-of analysis add a clear upper bound as a documented definition change; do not add it silently when validating the original query. Executed result: [best_sellers_example.json](best_sellers_example.json). Related exact queries/results: [brand](brand_revenue_example.json), [category](category_revenue_example.json), [daily KPIs](daily_kpis_example.json), [widget](revenue_widget_example.json).

## F3. Explain money movements separately from paid-order statements

```sql
SELECT FORMAT_TIMESTAMP('%Y-%m', created_at, 'America/New_York') AS month,
       COUNT(*) AS payment_rows,
       SUM(gross) AS movement_gross,
       SUM(fee) AS collected_fees,
       SUM(net) AS movement_net,
       COUNTIF(gross < 0 OR net < 0) AS negative_rows
FROM `novamart-warehouse.novamart.payments`
GROUP BY 1
ORDER BY 1;
```

The executed movement-month query is [payments_monthly.json](payments_monthly.json). December signed movement net is **572,926.48**, which includes payments for held headers and December refunds against older orders; it differs from the December paid-header provisional statement net **535,728.67**. Query/endpoint lineage explains the distinction; no additional “adjustment” should be invented to force equality. [payments](payments_monthly.json), [current header reconstruction](statement_recomputed_current.json), [status counts](orders_month_status.json), [C1].

## F4. Retrieve the actual evidence for a historical manual action

```sql
SELECT insertId, timestamp, textPayload
FROM `novamart-warehouse.novamart_logs.db_queries`
WHERE insertId IN (
  'nvm-dbq-0000374529', -- October fee override
  'nvm-dbq-0001904091', -- November audit correction
  'nvm-dbq-0002221779', -- chargeback booking
  'nvm-dbq-0002395860', -- taxonomy history CURRENT_DATE
  'nvm-dbq-0003085802', -- refunds unified view
  'nvm-dbq-0003446400'  -- held-order release NOW()
)
ORDER BY timestamp, insertId;
```

The investigation's broader executed query captured all 191 non-app/non-job SQL log rows in [manual_sql.json](manual_sql.json), rendered in [manual_sql.txt](manual_sql.txt). Reading historical mutation statements here is evidence inspection; none of those statements was re-executed. The normalized query-history view is convenient for discovering readers, but retain the raw line/ID/parameters when tracing a specific incident. [C10], [normalized sample](logs_normalized_sample.json).

## F5. Check actual serving, training, and job failures

```sql
SELECT intended_version, effective_version, rec_source, fallback_reason, arm,
       COUNT(*) AS decisions, MIN(ts) AS first_at, MAX(ts) AS last_at
FROM `novamart-warehouse.novamart_analytics.rec_decision_log`
GROUP BY 1,2,3,4,5
ORDER BY decisions DESC;
```

Executed [decision groups](rec_versions.json) should be read alongside [app-versus-decision random counts](rec_logging_gap.json), [gap key anti-join](rec_logging_gap_bounds.json), [score freshness/coverage](score_health.json), [model registry](model_registry.json), and [job errors](job_errors.json). A score table's freshness, a trainer event, a configured flag and a served-decision record are separate evidence types. [C6], [C7], [C10].

# Appendix G — Evidence register and remaining boundaries

## G1. Citation convention

`[C#]` identifies the listed code/document evidence at **pinned commit `5ae1182`**, unless another commit is named inline. Commit hashes refer to the supplied repository's local history. `[R]` means fetched Redash query definitions; query IDs are distinct from dashboard IDs. `[W]` means observed warehouse metadata, and `[V]` means queried warehouse view definitions. Linked query-result JSON files contain the exact executed SELECT and its returned rows. Historical log IDs identify rows in `novamart_logs.db_queries`, `app_events`, or `job_runs`, as specified. [Git evidence](git_evidence.json), [R], [W], [V].

| Reference | Exact evidence inspected |
|---|---|
| **C1** | `5ae1182:novamart/routers/orders.py:14–155`, `payments_webhook.py:11–21`, `catalog.py:13–99`, `carts.py`; `schema.sql`; lineage commits `b676969`, `5d1300d`, `d87cb3d`, `c49a7bb`, `d213f6e`, `795d273` |
| **C2** | `5ae1182:novamart/jobs/daily_report.py:13–68`, `intraday_report.py:12–77`, `timeutil.py:12–40`, `novamart/constants.py`; commits `102c9b4`, `1233af8`, `92596dc`, `1169e40` |
| **C3** | `5ae1182:novamart/jobs/monthly_statement.py:13–53`, `docs/restatement_policy.md`; commits `a92c96d`, `4a58d17`, `cd559d3`, `a576d0d` |
| **C4** | `5ae1182:novamart/routers/accounts.py:12–49`, `users.py:10–28`, `catalog.py:39–79`, `onboarding.py:1–48`; commits `088a372`, `b567d9d`, `b975479` |
| **C5** | `5ae1182:novamart/jobs/kpi_daily.py:9–25`, `funnel.py:9–43`, `docs/metrics_definitions.md`; commits `14726e7`, `f915c1b`, `dd0c8fc` |
| **C6** | `5ae1182:novamart/routers/similar.py:24–131`, `deploy/flags.env`; commits `f1217a8`, `df4ed85`, `30e8907`, `a00f24c`, `8ed2971` |
| **C7** | `5ae1182:novamart/jobs/affinity.py:15–53`, `affinity_v2.py:13–63`, `model_train.py:16–77`; commits `776d674`, `fef5c96`, `89666bf`, `3dbe4d7`, `a1946ff` |
| **C8** | `5ae1182:novamart/jobs/fraud_score.py:17–51`, `price_suggest.py:12–47`, `reorder_forecast.py:12–37`, `email_digest.py:13–56`, `deploy/cron.env`; corresponding docs `pricing_status.md`, `forecast_caveats.md`; commits `e4656fb`, `53f6f6c`, `1cb8721`, `cca9b0d`, `f85cdd2`, `8dc520b`, `0bd4eac` |
| **C9** | `5ae1182:novamart/jobs/top_sellers.py:15–39`, `trending.py:9–40`, `docs/trending_notes.md`; commits `9a51155`, `152a760`, `f563dea` |
| **C10** | `5ae1182:novamart/db.py:12–26`, `logutil.py:7–30`, `config.py`, `jobs/reconcile.py:10–23`; commits `030d841`, `388370b` |
| **C11** | `5ae1182:airflow/dags/*_dag.py` (all 16 wrappers), `crontab.txt`; migration commit `4bfcbe6` |
| **C12** | `5ae1182:novamart/jobs/warehouse_backfill.py:24–76`, `warehouse_manifest.json`, `docs/data-access.md`, `README.md`, `docs/rec_versions.md`, `docs/affinity_lineage.md`; local descendant fixes `99003c3`, `20e066f` |
| **C13** | `5ae1182:novamart/jobs/discounts.py:4–10`, `scripts/rerun_kpis.py:5–11`, `novamart/constants.py:34–35`; commit `35c581e` |
| **C14** | `5ae1182:novamart/app.py:7–23`, `routers/reports.py:13–42`, `ci/run_ci.py:26–68`, `requirements.txt` |
| **R** | GET `/api/queries` and `/api/queries/{1..9}` at supplied Redash; saved [query metadata](redash_queries.json), [readable SQL](redash_queries.sql); GET dashboard list and failed detail calls saved separately |
| **W** | BigQuery table-list/table-detail GETs for `novamart`, `novamart_analytics`, `novamart_logs`; [catalog JSON](warehouse_catalog.json), [schema summary](warehouse_schema.txt) |
| **V** | `SELECT * FROM novamart-warehouse.novamart_analytics.INFORMATION_SCHEMA.VIEWS` (backtick-qualified); [view-definition result](view_definitions.json); exact historical PostgreSQL definitions also in manual SQL logs |

## G2. Query-result index

The following groups provide the evidence trail without requiring a reader to trust uncited prose. Each linked JSON is an intermediate evidence artifact kept in this document's directory. All business interpretations are in this one Markdown document. [query collector](inspect_sources.py), [query suite](query_suite.py).

| Topic | Executed evidence |
|---|---|
| Finance layers | [published](finance_statements.json), [corrected](finance_corrected.json), [final](finance_final.json), [overrides](finance_overrides.json), [audit corrections](finance_corrections.json), [chargebacks](finance_chargebacks.json), [view SQL](view_definitions.json) |
| Current-state versus movement finance | [header status/month](orders_month_status.json), [current paid reconstruction](statement_recomputed_current.json), [payment month](payments_monthly.json), [payment integrity](financial_integrity.json), [fee warnings](statement_warnings.json), [rollout boundary](fee_boundary_summary.json) |
| Refunds / callback grain | [refund month/kind](refunds_monthly.json), [status overlap](refund_status_overlap.json), [duplicate references](duplicate_refs.json), [line integrity](multi_item_integrity.json), [event inventory](app_event_inventory.json) |
| Daily reports | [month aggregate](daily_reports_monthly.json), [snapshot versions](report_versions.json), [incident dates](report_incident_days.json), [scan-cap log](daily_scan_caps.json), [DST raw hour](dst_missing_hour.json), [widget comparison](revenue_widget_example.json) |
| Dashboard reproductions | [best sellers](best_sellers_example.json), [brand revenue](brand_revenue_example.json), [category revenue](category_revenue_example.json), [daily KPIs](daily_kpis_example.json), [registered buyers](registered_counts.json), [board/nightly actives](active_counts.json) |
| Catalog lineage | [blank-brand capture](blank_brands.json), [category mappings](category_mapping.json), [taxonomy effective dates](taxonomy_changes.json), [feed events](price_feed_history.json), [price-history extent](price_history_extent.json) |
| Customers and identity | [counts](customer_counts.json), [domains](email_domains.json), [bad UUID join](registered_bad_join.json), [map integrity](account_map_consistency.json), [latest saved KPI](kpi_latest.json), [test users](test_accounts.json), [QA UUID event](qa_identity_log.json) |
| ML and serving | [version/source counts](rec_versions.json), [daily decisions](rec_daily.json), [registry](model_registry.json), [score health](score_health.json), [score ratio](model_score_ratio.json), [list size](rec_incomplete_lists.json), [repeated decision keys](rec_duplicate_keys.json) |
| Logging hole | [daily app/table comparison](rec_logging_gap.json), [missing-key bounds](rec_logging_gap_bounds.json), [actual app samples](rec_gap_samples.json) |
| Jobs and consumers | [job events](job_event_inventory.json), [parameter history](job_parameter_history.json), [errors](job_errors.json), [reconcile timing](reconcile_performance.json), [affinity readers](affinity_readers.json), [shadow/model/reorder readers](shadow_reads.json), [reorder snapshot](reorder_snapshot.json), [fraud release candidates](fraud_releases.json) |
| Provenance | [data extent](data_extent.json), [manual SQL with IDs](manual_sql.txt), [manual SQL query/result](manual_sql.json), [SQL actor inventory](log_user_inventory.json), [normalized query sample](logs_normalized_sample.json), [repository baseline/status/history](git_evidence.json) |

## G3. Remaining boundaries and priority follow-ups

1. **Rendered dashboards:** query definitions were verified, but detail GETs returned 500 and cached result IDs were null. Restore that read surface separately if pixel-level/dashboard-widget validation is required; the metric SQL evidence remains available. [R], [detail results](redash_dashboards.json).
2. **Airflow runtime:** only checked-in wrappers and historical job exports were available; actual scheduler timezone, deployed dependency configuration and January execution are not established. The noon-only intraday wrapper and missing warehouse arguments are definite checked-in findings. [C11], [C12], [job extent](data_extent.json).
3. **Historical as-of reconstruction:** mutable headers/dimensions and `NOW()/CURRENT_DATE` backfill anomalies prevent treating a current SELECT with an old date as a complete historical replay. Logs can establish selected changes, but a comprehensive temporal ledger was not found in the inspected schema. [W], [C1], [taxonomy](taxonomy_changes.json), [release candidates](fraud_releases.json).
4. **Finance completeness:** final statements implement the company's documented restatement policy; they are not proof of exhaustive refund/chargeback reconciliation, and the September one-cent discrepancy has no override. Further changes need a clearly defined finance policy rather than an unannounced new total. [C3], [V], [warnings](statement_warnings.json), [overrides](finance_overrides.json).
5. **ML value:** operation and coverage were established, but no defensible incremental-lift claim follows from the existing v4 scoring or labels. The immediate analytical prerequisites are complete exposure logging, bounded item-attributed outcomes, consistent cohorts and a meaningful candidate-level scoring/evaluation contract. [C6], [C7], [gap](rec_logging_gap_bounds.json), [ratio check](model_score_ratio.json).

[C1]: ../novamart/novamart/routers/orders.py
[C2]: ../novamart/novamart/jobs/daily_report.py
[C3]: ../novamart/docs/restatement_policy.md
[C4]: ../novamart/novamart/onboarding.py
[C5]: ../novamart/docs/metrics_definitions.md
[C6]: ../novamart/novamart/routers/similar.py
[C7]: ../novamart/novamart/jobs/model_train.py
[C8]: ../novamart/novamart/jobs/fraud_score.py
[C9]: ../novamart/novamart/jobs/trending.py
[C10]: ../novamart/novamart/db.py
[C11]: ../novamart/airflow/dags/
[C12]: ../novamart/novamart/jobs/warehouse_backfill.py
[C13]: ../novamart/scripts/rerun_kpis.py
[C14]: ../novamart/novamart/app.py
[R]: redash_queries.sql
[W]: warehouse_catalog.json
[V]: view_definitions.json
