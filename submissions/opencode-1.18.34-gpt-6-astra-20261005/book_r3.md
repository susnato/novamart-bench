# Novamart tribal knowledge

## 1. Summary

- **For current approved finance reporting, use `novamart_analytics.statements_final`. For an old published deck, use `novamart.statements`.** October 2019 net is **1,194,652.79 originally published**, **1,194,652.93 after the fee correction**, and **1,191,085.36 after 3,567.57 of booked chargebacks**. Those are three deliberately different reporting layers, not interchangeable calculations. [Q-finance] [C-restatement]
- **A dashboard’s “revenue,” “orders,” and “customers” need its exact definition.** Item-level merchandising sales, parent-order finance totals, payment movements, daily report snapshots, trailing-30-day buyers, and daily distinct ordering users have different grains, clocks, filters, and refresh paths. The current nine Redash queries make these differences explicit. [R] [C-statement] [C-report] [C-kpi]
- **Historical corrections do not automatically repair stored reports.** A 500-row scan cap left November 17’s report at 487 included units and 148,857.07, versus 704 units and 223,853.03 under the contemporary filters applied to the supplied order snapshot. The December revenue-widget fix also prevents repeated intraday snapshots from being added to closed-day totals. [Q-cap] [H-orders] [R] [H-metrics]
- **The recommendation system serves v2, with substantial fallback traffic.** The flag is `2.0.0`; batch rows say `2.0.1`; v4 trains but has no observed serving traffic. In the latest v4 snapshot, all 948 candidate-pair ranks match v2. Training completion is therefore not evidence of a better recommender. [C-flags] [C-similar] [Q-rec-mix] [Q-v4-ranks]
- **Logs reveal failures and definition changes that the README does not.** Affinity v2 crashed on December 3–5; a refactor left 1,372 random-serving app rows without a matching decision-log row on December 17–19; trending changed from 60 to 30 days; and the email digest did not start producing records until December 17 despite an earlier enable flag. [Q-failures] [Q-rec-gap] [Q-job-config] [Q-digest]
- **Scope matters:** the checked-out code is `5ae1182`, operational records end in December 2019, and some backfill-generated values carry 2026 dates. Examples below freeze an analysis time and distinguish stored historical outputs from calculations against mutable snapshot data. [H-log] [Q-coverage] [Q-taxonomy] [Q-future]

## 2. Why this project

Novamart’s metric definitions live across application code, batch jobs, manually created warehouse objects, historical database statements, and Redash SQL. For example, the finance views were created in engineer backfills recorded in `novamart_logs.db_queries`; they are absent from the initial `schema.sql`, while Redash reads them as reporting authorities. Understanding only the repository schema would miss the finance reporting contract. [Q-view-log] [C-schema] [R]

The practical purpose of this document is to make three decisions reproducible: **which financial number to quote and how to reconcile it; what a dashboard number actually counts; and which pipeline changes affect reporting or serving**. The source hierarchy, historical bridges, explicit definitions, and read-only recipes below address the observed disagreements rather than assuming one universal “revenue” or “active customer.” [C-restatement] [C-metric-definitions] [R] [C-similar]

## 3. Business understanding

Novamart is implemented as a marketplace backend with product views, cart events, payment-callback order creation, catalog price feeds, cancellations, refunds, and a similar-products widget. Product and user records are bootstrapped on first sight. A user row is consequently evidence of an observed shopper ID, not necessarily a completed registration. User profile attributes and product cost/stock attributes are deterministically synthesized from IDs in this implementation. [C-app] [C-catalog] [C-onboarding] [C-orders]

Money has three separate operational representations:

1. **Orders:** the parent commercial record and current lifecycle status; newer parents can contain multiple separately priced lines.
2. **Payments:** collected amounts, processor fees, and negative gateway movements, potentially several rows per parent.
3. **Statements:** published monthly snapshots plus approved overrides and booked chargebacks. The statement job’s net is order gross less collected processor fees; it is not a cost-of-goods or profit calculation. [C-orders] [C-webhook] [C-statement] [Q-view-log]

Merchandising reporting intentionally hides some products and brands, while finance does not apply those same exclusions. Lucente and Jetem exclusions are reporting policy, not evidence that the underlying orders or payments vanished. QA cleanup is also consumer-specific. [C-constants] [C-report] [C-statement] [R]

## 4. Metrics

| Question | Authoritative surface for that question | Essential qualification |
|---|---|---|
| What did we publish for a month? | `novamart.statements` | Append-only run snapshot; select the publication you intend to reproduce. [C-statement] [C-restatement] |
| What is the current approved monthly finance figure? | `novamart_analytics.statements_final`; Redash query 5 | Overrides first, chargebacks attributed to original order month second. [Q-view-log] [R] |
| What moved through the payment ledger? | `novamart.payments` | Group by payment time for movement-period reporting; include negative rows deliberately. [C-webhook] [Q-payments] |
| What does the refunds dashboard count? | `novamart_analytics.refunds_unified`; query 1 | Cancellation/refund status rows **plus** negative payment rows; event/update month, not original sale month. [Q-view-log] [R] |
| What are executive daily sales? | Latest completed `report_rows` per prior day; latest `report_rows_intraday` for today; query 7 | “Orders” is summed report **units**; status, QA, SKU, and brand rules come partly from the writer. [C-report] [C-intraday] [R] |
| What are the best sellers? | Redash query 9 | Rolling seven days, item rows plus legacy fallback, no status filter, revenue-ranked top 20. [R] |
| What are brand/category sales? | Queries 8 and 6 | Rolling 30 days, item grain, no status filter; category labels are effective-dated. [R] |
| How many customers are active? | Name the consumer first: `kpi_daily`, query 7, or query 3 | Respectively trailing paid buyers, daily ordering users, and trailing buyers after board cleanup; held orders differ across definitions. [C-kpi] [R] |
| How many registered customers converted? | Query 4 | Actually lifetime paid buyer count and gross revenue for email-mapped accounts; no conversion-rate denominator. [R] |
| How many customers are contactable? | `novamart_analytics.contactable_users` | Opt-in + email syntax + domain exclusions; the digest uses a different predicate. [Q-view-log] [C-digest] |
| What is funnel activity? | `novamart_analytics.daily_funnel` | Trailing-day cart/order activity split into inactivity sessions, not page-view sessions or a complete conversion funnel. [C-funnel] |

**Concrete cross-checks:** the final October statement net is 1,191,085.36; registered reporting returns 30 buyers and 18,155.71; the supplied contactable view returns zero; the December 31 daily KPI example has 60 report units, 18,202.09 revenue, and 54 ordering users. These figures answer different questions and should not be combined into a common “customer conversion” calculation. [Q-finance] [Q-registered] [Q-customers] [Q-daily-example]

## 5. System

The core lineage is:

```text
catalog/view/cart/payment callbacks
    -> serving Postgres users/products/cart_items/orders/order_lines/payments
    -> scheduled reports, finance snapshots, risk scoring, recommendation tables
    -> Redash queries and similar-products serving

serving tables -> manifest-driven warehouse backfill -> BigQuery tables
app/SQL/job logs -> novamart_logs -> historical diagnosis
```

The application uses FastAPI and psycopg; jobs connect synchronously with autocommit. January’s checked-in schedule authority is `airflow/dags/`, not the retired crontab. The warehouse loader is a one-shot export/load mechanism, not evidence of continuously synchronized warehouse data. [C-app] [C-db] [C-cron] [C-dag] [C-backfill] [C-access]

**Wiring caveat:** the pinned `app.py` mounts catalog, carts, orders, similar, and payment-webhook routers. The repository also defines account, user-email, and brand-report routers, but does not mount them there. Historical account/email operations are present in the logs and data; endpoint definitions alone do not establish reachability through this pinned app entrypoint. [C-app] [C-accounts] [C-users] [C-brand-api] [Q-qa] [Q-app-types]

## 6. Data

Postgres `public.*` corresponds to BigQuery `novamart.*`; Postgres `analytics.*` corresponds to the **observed** BigQuery dataset `novamart_analytics.*`. The inventory contains 12 app tables, 20 analytics tables, four analytics views, three exported log tables, and a normalized query-log view. The pinned data-access document and loader still say/use `analytics` as the warehouse dataset, contradicting the observed dataset name. [Q-inventory] [C-access] [C-backfill]

The main join contracts are numeric `users.id = orders.user_id`, `orders.id = payments.order_id = order_lines.order_id`, and `products.id = product_id`. UUID `accounts.account_id` is a separate namespace, bridged by `account_map` or by the email mapping the registered dashboard actually uses. A direct UUID-to-numeric-ID comparison is not an identity join. [Q-inventory] [C-accounts] [R]

The snapshot has **9,127 parent orders, 9,361 payment rows, 2,284 order lines, 38,950 user rows, and 30 accounts**. These totals are intentionally unequal: 2,059 orders have lines, and negative payment movements add rows without creating new orders. The detailed catalog and temporal limitations are in Appendices A and F. [Q-inventory] [Q-grains] [Q-customers] [Q-refund-overlap]

## 7. Experimentation

**What is established:** a deterministic approximately 5%-of-users random recommendation arm exists; nightly logistic fits and model score outputs exist; serving defaults to v2; dynamic pricing is shadow-only; fraud and reorder outputs are hand-coded heuristics. **What is not established by these sources:** causal recommendation lift, fraud-detection accuracy, purchasing-forecast accuracy, or revenue gains from suggested prices. Those outcomes are not measured by successful refresh logs. [C-similar] [C-train] [C-pricing] [C-fraud] [C-reorder] [Q-rec-mix] [Q-pricing-reads]

For a defensible recommendation experiment, first repair exposure completeness and identity, define a fixed item-level outcome window, use point-in-time features, and evaluate user-level randomized assignment with uncertainty. Compare the assigned serving policy—including its fallback behavior—not only the subset where model scores happened to exist. These are proposed evaluation requirements, motivated by the observed logging gap, limited random candidate pool, current label construction, and high fallback share. [Q-rec-gap] [C-similar] [C-train] [Q-rec-mix]

## 8. Glossary

| Term | Meaning in this system |
|---|---|
| Parent order | One `orders` row; after the session-merge change it can represent multiple lines/payments. [C-orders] |
| Item sale / unit | One `order_lines` row, or a legacy `orders` row only when the parent has no lines; there is no quantity column in the line schema. [Q-inventory] [R] |
| Paid/completed | `status = 1` in finance, nightly buyer metrics, and several ranking jobs. [C-statement] [C-kpi] [C-top] |
| Cancelled / refunded | Current status 2 / 3; these endpoints change status rather than inserting a negative payment. [C-orders] |
| Held | Status 6 written by fraud scoring; excluded by `status = 1`, included by `NOT IN (0,2,3)`. [C-fraud] [C-report] |
| Payment reference | Callback idempotency key; historical duplicates remain, and newer lines/payments have their own references. [C-orders] [Q-duplicates] |
| Gross / fee / net | Depends on surface; monthly job uses paid parent-order gross, collected payment fees, and gross minus fees. [C-statement] |
| Published / corrected / final | Original statement; original with overrides; corrected with original-order-month chargebacks deducted. [Q-view-log] |
| Refund | In query 1, a unified status/movement record, not necessarily a unique cash refund. [R] [Q-view-log] |
| Active customer | Consumer-specific distinct shopper count; never assume one common definition. [C-metric-definitions] [R] |
| Contactable | Membership in the opt-in/email-filtered view, not merely a non-placeholder email. [Q-view-log] |
| Account | UUID beta registration; not the numeric shopper identifier. [C-accounts] |
| Report version | Rows for one report date sharing a run’s `created_at`; choose one complete version. [C-report] [R] |
| Affinity | Directional co-cart pair score, with v2 adding order/category/price weighting. [C-affinity] [C-affinity2] |
| Sentinel `-1` | Too few observed pairs to qualify; not a negative preference. [C-affinity] |
| Intended / effective version | Configured model versus recorded selected path; legacy v1 logs do not reliably distinguish fallback using version alone. [C-similar] [Q-rec-mix] |
| Random arm | User-hash assignment with deterministic per-user/session/base shuffle of a restricted candidate pool. [C-similar] |
| Trending | Paid parent-order count with recency decay, min five, top 50; 30-day current window. [C-trending] |
| Reorder hint | `int(15.6 + 162.4 / (velocity + 1.8))`; advisory inverse-velocity heuristic. [C-reorder] |
| Shadow pricing | Generated price suggestions with no observed serving reads. [C-pricing] [Q-pricing-reads] |

---

## Appendix A. Investigation scope, evidence, and clocks

### A.1 Scope and reproducibility

- Investigation started **2026-10-05T15:10:57+00:00**; run UUID **`49acc1fa-9761-4f36-869d-cde4a9b9d620`**. The checked-out repository resolved to **`5ae11821806a396aac10115e03863b8c68c1bfcc`**. Code citations below refer to this checkout unless a historical commit is named. [Run] [H-log]
- Warehouse evidence was collected through BigQuery metadata reads and saved `SELECT` queries against `novamart-warehouse`; each linked query-result JSON includes the exact SQL and returned rows. Redash evidence came from GET requests for queries, dashboards, and data sources. The source data and repository were not changed. [Q-inventory] [R-inventory] [C-collector] [C-investigation]
- The Redash inventory exposes nine dashboards and nine queries on data source 1, type `pg`. Every query had `latest_query_data_id = null`; therefore the numerical examples here are independent warehouse reproductions, not claims about cached numbers visibly displayed by Redash. The full SQL is retained in `redash_sql.json`. [R-inventory] [R]
- Operational app data begins September 25, 2019; app and SQL logs end December 31 at 23:57:06 UTC; order creation ends December 31 at 16:51:39 UTC. Job/SQL history starts September 16. There is no January job-run evidence in these exports. [Q-coverage]

### A.2 Which clock is being used?

| Clock | Rule and consequence |
|---|---|
| Business calendar | Daily sales and statements use `America/New_York`; calculate both local boundaries, then convert to UTC. A local day need not be 24 hours. [C-time] |
| Rolling operational windows | Jobs commonly use `run_timestamp - interval`; best sellers and brand/category dashboards use query-time rolling windows. They are not calendar weeks/months. [C-kpi] [C-trending] [R] |
| Publication time | `statements.created_at` identifies the published snapshot, not when every later correction was booked. The October override deliberately preserves the original publication timestamp. [Q-overrides] [Q-view-log] |
| Refund/event time | Status-based refund rows use current `orders.updated_at`; gateway refunds use payment `created_at`. [Q-view-log] |
| Query-log time | A log records a statement and parameters before execution; an attempted statement is not proof it succeeded. Several engineer queries refer to nonexistent columns such as `external_ref`, `total_amount`, or `source`. [C-db] [Q-manual] [Q-inventory] |
| Analysis cutoff | Product/customer rolling examples use **2020-01-01T00:00:00Z**, which is still December 31 in New York. Calendar-widget examples use business date **2019-12-31**. The saved queries expose the exact boundary. [Q-best-example] [Q-brand-example] [Q-category-example] [Q-widget] |

**Historical reconstruction limitation:** a time predicate against the supplied warehouse does not restore the old database state. Order statuses, user emails, product metadata, and current score tables can have changed since the event. The published October gross is 1,230,332.43, but a current `status = 1` order recomputation gives 1,206,337.32. Preserve published outputs for historical questions rather than assuming current rows reconstruct publication-time facts. [Q-finance] [Q-recompute] [C-restatement]

### A.3 Observed temporal inconsistencies

The six taxonomy-history rows for lighting/entertainment have `valid_from = 2026-08-13`, although their backfill statement is logged on December 12, 2019 and uses `CURRENT_DATE`. The five released paid orders have `updated_at = 2026-08-13T21:12:33.493918Z`, while the December 29 historical release statement uses `NOW()`. The blank-brand diagnostic snapshot similarly has a 2026 capture timestamp. These observations are consistent with execution-time defaults during backfill, but the exact external replay process is not established by the allowed sources. Treat the stored dates as observed data, and do not silently reinterpret them as 2019 dates. [Q-taxonomy] [Q-future] [Q-risk-release] [Q-blank] [Q-manual]

Consequences: effective-dated 2019 category queries retain the old groups; an `updated_at <= historical_cutoff` predicate would exclude the five released orders even though their creation dates are in the operational period; and a diagnostic snapshot’s capture time cannot establish its purported 2019 production timing. [Q-taxonomy] [Q-future] [Q-blank] [R]

## Appendix B. Financial numbers end to end

### B.1 Order lifecycle and counting grain

The current payment callback calculates `fee = round(request_price * 0.029 + 0.30, 2)`, takes transaction advisory locks for session and payment reference, and checks both parent and line references. A replay inserts a missing payment if necessary and promotes only status 0 to 1. A new reference can append to the same user/session’s recent order if a line occurred within 15 minutes and the order is neither cancelled nor refunded. Appending increases parent `price`, sets status 1, and inserts one line and one payment; the parent’s original `product_id` and creation time remain. [C-orders]

This has four reporting implications:

1. Parent `price` is an order total, not necessarily the price of the parent `product_id`. Summing it by that product/brand misattributes later items. Order 7626, for example, has six distinct products and a 2,415.00 parent/line total. [Q-multiitem]
2. Parent-order counts, item counts, and payment counts diverge. There are 2,284 lines across 2,059 parents, so adding all parents to all lines double-counts the line-bearing parents. Use lines **or** a no-lines parent fallback. [Q-grains] [R]
3. Item reports use line timestamps for newer items; statements use parent order timestamps. A session merge across a day/month boundary can therefore allocate item sales differently from the parent statement. This is a code-derived consequence, not a measured boundary incident. [C-orders] [C-report] [C-statement]
4. Appending excludes statuses 2 and 3 but not 6, and explicitly writes status 1. Thus a new same-session callback can, by code, clear a held status. Replay logic and append logic should be tested separately when modifying lifecycle behavior. [C-orders]

Historical callback idempotency arrived in commit `b676969` on October 15. Earlier duplicates remain: **130 repeated references, 285 associated order rows, 155 extra rows beyond one per reference**, with duplicate creation timestamps ending October 15. `reconcile` flags them but does not repair or delete anything. It checks `status <> 5`, groups references, sorts them, and takes a fixed batch; repeated warnings are not newly created duplicate sales. [H-orders] [Q-duplicates] [C-reconcile]

The cancellation constant was 4 before commit `8f19718` changed it to 2 and added cancellation handling on October 28. Refund status 3 arrived in `d87cb3d` on November 15. Current snapshot statuses are 1, 2, 3, and 6; neither “any nonzero status is paid” nor “not cancelled means status 1” is a valid universal rule. Status 5 is excluded by reconcile, but its business meaning is not established by the current constants or observed status inventory. [H-orders] [H-log] [C-constants] [Q-status]

### B.2 Payment fees: stored collection wins over recalculation

Before the November 20 fee change, callback fees were 2.9%; commit `12e1c68` added 0.30 per transaction. The first observed payment matching the added-flat-fee pattern is **2019-11-20T14:27:41Z**. The later statement diagnostic assumes the change at **2019-11-20T05:00:00Z**, New York midnight. Code-commit dates, policy boundaries, and observed callbacks are distinct pieces of evidence. [H-log] [C-constants] [C-statement] [Q-fee-boundary]

Monthly fee logic changed in `a92c96d` on November 2 from `round(monthly_gross * 0.029, 2)` to the sum of stored payment fees joined to qualifying orders. Per-transaction rounding explains why multiplying a monthly total is not equivalent. After session merging, a flat fee is also charged for each callback/payment rather than once per parent order. [H-finance] [C-orders]

| Month | Evidence and interpretation |
|---|---|
| September | Statement fee 78.36; collected fee 78.37; warning delta −0.01. No September override is present, so final reporting retains net 2,623.64 rather than silently changing it to payment net 2,623.63. [Q-finance] [Q-payments] [Q-overrides] [Q-fee-warnings] |
| October | Aggregate-formula fee 35,679.64 versus collected 35,679.50; approved override increases net by 0.14. [Q-overrides] [Q-fee-warnings] |
| November | Warning expected 31,940.51 versus collected 32,110.92, delta −170.41. The published statement already uses the collected amount; the audit correction row has delta **0.00**. A warning about expectations is not proof the published fee was wrong. [Q-fee-warnings] [Q-finance] [Q-corrections] |

The December 2 diagnostic fix (`4a58d17`) makes expected fees effective-date-aware, but still computes them per **parent order**. On the supplied November data this diagnostic yields 32,120.54, versus actual collection 32,110.92. A payment-grain midnight-cutover diagnostic yields 32,130.14; 64 post-midnight transactions still lack the flat fee. Thus even the newer expectation is not a substitute for recorded collection: it differs in transaction grain and actual activation timing, with rounding also involved. [H-finance] [Q-fee-order] [Q-fee-payment]

### B.3 Published, corrected, and final statements

The monthly job selects the previous **New York calendar month**, sums parent `orders.price` and counts parents with current `status = 1`, separately sums all payment fees joined to those qualifying parents, and inserts one snapshot. It does not apply QA/SKU/brand exclusions. It does not subtract negative payment gross/net from order gross. Re-running it now can produce a different answer because the parent statuses have changed. [C-statement] [Q-recompute]

| Month | Published gross | Published fee | Published net | Corrected net | Final gross | Final net | Published order count |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2019-09 | 2,702.00 | 78.36 | 2,623.64 | 2,623.64 | 2,702.00 | 2,623.64 | 12 |
| 2019-10 | 1,230,332.43 | 35,679.64 | 1,194,652.79 | 1,194,652.93 | 1,226,764.86 | 1,191,085.36 | 3,765 |
| 2019-11 | 1,101,397.01 | 32,110.92 | 1,069,286.09 | 1,069,286.09 | 1,101,397.01 | 1,069,286.09 | 3,582 |

All entries are read from the three statement layers. No December statement exists in the supplied snapshot; the job history contains only three publications, the latest on December 1. [Q-finance] [Q-jobs]

The transformation is:

```text
published statements
  LEFT JOIN statement_overrides by month; COALESCE override values
    -> statements_corrected
  subtract SUM(chargeback.amount) grouped by original order's New York month
    -> statements_final
```

Chargebacks change gross and net, leaving the fee and published order count unchanged. `statement_corrections` is an explanatory audit table, not an extra amount automatically subtracted by either view. Multiple base publications would survive these joins, so choose a publication deliberately rather than summing statement rows. [Q-view-log] [C-restatement]

**October reconciliation:**

```text
Published net                           1,194,652.79
Fee correction                                +0.14
Corrected net                           1,194,652.93
Booked chargebacks: 734.81 + 940.82
                 + 1,891.94                 -3,567.57
Final restated net                      1,191,085.36
```

The chargebacks are for order IDs 55, 46, and 49. Their `reported_at` is December 1; the historical insertion/view creation is logged December 9; their original order month is October. “Reported,” “booked by a backfill,” and “attributed revenue month” are therefore different dates. [Q-chargebacks] [Q-manual] [Q-finance]

### B.4 Refunds are not one homogeneous ledger

| Mechanism | Storage effect | Reporting consequence |
|---|---|---|
| `/orders/{id}/cancel` | Sets status 2 and update time; no negative payment insertion | Later `status = 1` queries exclude it, but old statements/report snapshots remain. [C-orders] |
| `/orders/{id}/refund` | Sets status 3; allowed from paid or already-refunded status; no negative payment insertion | Operational refund indication, not a recorded gateway movement. [C-orders] |
| `/payments/gateway_refund` | Inserts negative gross and net, fee zero, without changing order status | Can affect the payment ledger while status-based revenue remains unchanged. No refund ID or replay deduplication is implemented in this endpoint. [C-webhook] |
| `analytics.chargebacks` | Separate booked amounts linked to original orders | Consumed only by the final-statement adjustment described above. [Q-view-log] |

`refunds_unified` is a `UNION ALL`: current orders with status 2/3 at their update time, plus payments whose gross or net is negative at payment time. The payment amount is `ABS(gross)` if gross is negative, otherwise `ABS(net)`. It neither deduplicates across mechanisms nor includes the chargeback table. [Q-view-log]

| Refund-event month | Cancelled status | Refunded status | Gateway movements | Dashboard total |
|---|---:|---:|---:|---:|
| November 2019 | 24 / 6,511.32 | 8 / 3,180.45 | 0 | **32 / 9,691.77** |
| December 2019 | 30 / 6,738.32 | 20 / 10,267.02 | 9 / 1,843.59 | **59 / 18,848.93** |

Cells are record count / amount, not unique refunded buyers or necessarily unique refunded orders. This reproduces query 1’s grouping by New York event month. [Q-refunds] [R]

The nine negative payments belong to just **three October orders**, IDs 3762, 3763, and 3776, with three negative rows each; all three parents still have status 1. Their amounts total 1,843.59. The supplied unified view therefore has no current overlap between its status and gateway components, but its definition would permit overlap if the same parents later changed to status 2/3. Repeated rows are observed; the data do not by themselves establish whether they were intended partial refunds or webhook replays. [Q-gateway] [Q-refund-overlap] [C-webhook]

**Do not subtract the refunds dashboard total from final statement net as a shortcut.** It mixes cancellation indications and gateway movements, uses event months, and is not the adjustment source used by `statements_final`. In particular, the final view does not automatically apply the 1,843.59 of gateway refunds, even though the payment ledger records them. Quote the approved view as the current finance policy and explain this limitation separately. [Q-view-log] [Q-gateway] [C-restatement]

### B.5 December has several valid-looking but different provisional totals

| December calculation against available snapshot data | Result | Why it differs |
|---|---:|---|
| Positive payment gross | 592,542.22 | Includes 1,961 positive payment rows across 1,768 parents, including subsequently held orders. [Q-payments] [Q-status] |
| Payment movement net, including negative rows | 572,926.48 | 574,770.07 positive net less 1,843.59 December gateway movements for October parents. [Q-payments] [Q-gateway] |
| Current paid-parent order gross | 552,328.93 | `status = 1` excludes 12 held parents totaling 40,213.29. [Q-status] |
| Monthly-job-style provisional net | 535,728.67 | Current paid-parent gross minus 16,600.26 of joined fees; this is not a published December statement. [Q-recompute] [Q-finance] |
| Full available December item sales under current daily-report filters | 553,913.00 | Includes held statuses but removes test users, excluded SKUs, and denied brands. [Q-current-report] |
| Stored completed daily reports | 535,561.72 | Covers report dates December 1–30; December 31 is still intraday in the export. [Q-report-months] [Q-report-versions] |

These comparisons use the supplied current statuses and available event history; they are not a reconstruction of the database at every historical cutoff. The end of the export also precedes the final five UTC hours of the December 31 New York business day. [Q-coverage] [Q-future] [C-time]

### B.6 Daily reporting defects and snapshot rules

The current daily report scans yesterday’s New York interval, expands lines with a no-lines parent fallback, excludes statuses **0, 2, 3**, removes `analytics.test_users`, and then excludes product IDs **1004856, 1002544** and brands **lucente, jetem**. It counts each included item row once and appends product aggregates under one run timestamp. Status 6 is included. The intraday job uses the same rules from local midnight to its run timestamp. [C-report] [C-intraday] [C-constants]

| Change | What it explains |
|---|---|
| `83fb3ed`, October 8 | Excluded test SKUs introduced into daily reporting. Earlier snapshots can include them. [H-metrics] |
| `ba1fbfa`, October 25 | Lucente added to the report denylist for partnerships. [H-metrics] |
| `102c9b4`, November 5 | Old day end was UTC start + 24 hours. November 3 needed `[2019-11-03T04:00Z, 2019-11-04T05:00Z)`. The omitted final hour contains eight orders totaling 2,985.99 before merchandising exclusions. [H-orders] [Q-dst] |
| `11c0a42`, November 18 | Report exclusions expanded from only status 0 to 0/2/3; cancellation/refund statuses had previously leaked into reports. [H-metrics] |
| `1233af8`, November 19 | `fetchmany(500)` became `fetchall()`. The constant `REPORT_SCAN_CAP = 500` remains in constants but is no longer read by the report. [H-orders] [C-constants] [C-report] |
| `b59f077`, November 27 | QA cleanup added to the report and dashboard definitions. [H-metrics] |
| `92596dc`, December 5 | Reports and item dashboards adopted order lines plus legacy fallback, after lines had begun appearing November 22. [H-metrics] [Q-grains] |
| `a2e0013`, December 8 | Intraday snapshots introduced. [H-log] [C-intraday] |
| `1169e40`, December 15 | Jetem added to the hidden-brand rules. [H-metrics] |
| `3eced24`, December 24 | Revenue widget fixed to select latest closed-day snapshots plus only today’s latest intraday snapshot. [H-metrics] [R] |

**Measured scan-cap case:** November 17 has 735 eligible-status orders. After the contemporary SKU/Lucente filters, the current snapshot yields 704 units and 223,853.03. The November 18 run logged exactly 500 scanned rows and stored only 487 units / 148,857.07: a 217-unit and 74,995.96 gap. No corrected version of that report date is present in the report-version query. This separates an observed row-cap defect from normal exclusion effects. [Q-cap] [Q-cap-log] [Q-report-versions]

**Measured snapshot-double-count case:** for business date December 31, the corrected seven-calendar-day widget is **139,598.13**. Adding every daily and intraday row for the same period produces **371,872.10**, an excess of **232,273.97**. Intraday values are cumulative snapshots, not incremental revenue. [Q-widget] [R]

**Missing date is not automatically a failed job.** November 15 has no orders and no report rows, but its November 16 run logged successful generation with zero products and zero scanned orders. The writer does not materialize zero-revenue days, and query 7 is driven from report days, so an absent chart date can be a true zero as well as a pipeline problem. Check run logs before diagnosing. [Q-empty-day] [Q-empty-job] [C-report] [R]

### B.7 How to answer “what was revenue in month M, and why?”

1. **Name the meaning:** historical publication, current approved restatement, payment movement, or filtered merchandising sales. Use the corresponding source rather than translating between them by title alone. [C-restatement] [R] [C-statement]
2. **Name the calendar and observation time:** New York month boundaries; publication/run version; warehouse cutoff; current versus historical lifecycle state. [C-time] [Q-coverage] [Q-future]
3. **For an old deck**, retrieve its `statements` row and publication time. **For current finance**, retrieve `statements_final` and bridge it through `statement_overrides` and `chargebacks`. [Q-view-log] [C-restatement]
4. **Check payments at the right grain:** pre-aggregate fees by order before joining to parent gross; retain transaction-level fee facts and negative movements separately. [C-statement] [C-orders] [Q-fee-payment]
5. **Explain operating-report differences** through status, item versus parent grain, hidden products/brands, QA, calendar boundaries, report code version, and snapshot selection. Do not assume report totals equal statements. [C-report] [R] [H-metrics]
6. **If no statement exists**, report that explicitly and label any recomputation provisional. For December, the export has no January publication. [Q-finance] [Q-jobs]

## Appendix C. Product and customer analytics

### C.1 Complete Redash query map

The query IDs and dashboard names below come from the current read-only Redash API. Dashboard IDs differ from query IDs for the product/KPI dashboards; the query ID is the useful SQL citation. [R-inventory]

| Query / dashboard | Exact current meaning | Traps |
|---|---|---|
| [1: refunds](http://localhost:5050/queries/1) / `refunds` | Monthly count and sum from `analytics.refunds_unified`, grouped in New York | Count is unified records, not unique refund transactions; no chargeback component. [R] [Q-view-log] |
| [2: revenue_widget](http://localhost:5050/queries/2) / `revenue_widget` | Seven **calendar** dates including today: latest daily version for prior six dates, latest intraday version for today | No additional product-brand join here; relies on historical writer filters. No fallback to a closed-day report for today. [R] |
| [3: actives_board](http://localhost:5050/queries/3) / `actives_board` | Distinct ordering users in trailing 30 days, excluding statuses 0/2/3, test-user table members, and email heuristics | Includes held status 6; no brand filter; not the nightly paid-only metric. [R] |
| [4: registered_conversion](http://localhost:5050/queries/4) / `registered_conversion` | Distinct numeric users whose current email matches an account; all-time status-1 buyer count and parent-order gross | No time bound, no post-enrollment restriction, no denominator, no QA/brand filter. [R] |
| [5: statements_final](http://localhost:5050/queries/5) / `statements_final` | `SELECT * FROM analytics.statements_final ORDER BY month` | Current restatement layer; not historical deck values or a payment cash ledger. [R] |
| [6: category_revenue](http://localhost:5050/queries/6) / `category_revenue` | Trailing 30-day item count and item price; QA 424242 and Lucente/Jetem removed; effective-dated display group; revenue descending | No status or excluded-SKU filter; category date cast relies on source SQL’s session date semantics. [R] |
| [7: daily_kpis](http://localhost:5050/queries/7) / `daily_kpis` | Today + prior 13 local dates; latest reports; summed units/revenue; daily distinct ordering/contactable users | Customer branch has no status filter and uses parent product; sales branch uses item reports. Missing report days do not get a generated zero row. [R] |
| [8: brand_revenue](http://localhost:5050/queries/8) / `brand_revenue` | Trailing 30-day item counts/prices, hidden brands removed, numeric QA ID and its UUID string excluded; revenue descending | No status or excluded-SKU filter. Numeric `user_id::text` cannot become the QA UUID; the numeric exclusion does the work for current orders. [R] [Q-inventory] |
| [9: best_sellers](http://localhost:5050/queries/9) / `best_sellers` | Trailing 7×24 hours; item counts/prices; QA 424242 and Lucente/Jetem removed; top 20 by revenue | “Best” means revenue, not units; no status or excluded-SKU filter. [R] |

The rolling product queries contain lower time bounds but no explicit upper bound. On this finite export there are no events beyond the chosen example cutoff; for a later warehouse containing additional events, a faithful historical reproduction needs an explicit upper bound and historical dimension/status handling. [R] [Q-coverage]

### C.2 Product grain and competing “best seller” lists

All three item dashboards use:

```text
orders JOIN order_lines
UNION ALL
orders WHERE no order_lines exist for that parent
```

This counts newer items once and retains old single-item orders. The Dec 5 change did not convert every other consumer: nightly `top_sellers`, trending, pricing, reorder hints, the digest’s top product, and the brand-report router still use the parent `orders.product_id`. [R] [C-top] [C-trending] [C-pricing] [C-reorder] [C-digest] [C-brand-api]

| Consumer | Window | Ranking/count | Cleanup |
|---|---|---|---|
| Best-sellers dashboard | Rolling seven days at query time | Item revenue descending, top 20; also displays item count | QA and hidden brands; no status/SKU exclusion. [R] |
| `top_products` nightly output | Previous New York calendar day | Paid parent-order units descending, product ID tie-break, top 50 | Status 1 only; no QA, SKU, or brand cleanup. [C-top] |
| `trending_daily` | Rolling 30 days at job time | Paid parent-order count × recency decay; min five, top 50 | Status 1 only; no QA, SKU, or brand cleanup. [C-trending] |
| Brand-report router definition | Requested New York calendar month | Paid parent-order gross grouped by current parent product brand; blank becomes `unbranded` | Excluded SKUs and hidden brands, but no QA-table filter; also unmounted in pinned app. [C-brand-api] [C-app] |

A concrete discrepancy: at the example cutoff, best sellers ranks product **1005284 third**, with **two units / 5,096.14**, even though its paid-unit count is **zero**. Its inclusion follows the dashboard’s absent status filter. First and second are 1005116 (5,889.81) and 1005115 (5,325.55). This is an expected definition mismatch with paid-only lists, not proof of a broken aggregation. [Q-best-example]

At the same cutoff, the brand query’s leading groups are Apple **236,606.73**, Samsung **128,113.51**, and Xiaomi **20,818.56**. Category leaders are electronics **437,887.95**, other **93,558.92**, and appliances **30,208.94**. These are merchandising gross figures under query-specific filters, not monthly finance net. [Q-brand-example] [Q-category-example] [R]

### C.3 Hidden brands, QA, and metadata repair

- **Lucente:** hidden from daily reports by `ba1fbfa`, described as a partnerships decision. **Jetem:** added by `1169e40`. The current dashboards independently filter both brands; current products can therefore relabel or exclude an old stored report row at read time. [H-metrics] [C-constants] [R]
- **QA:** `analytics.test_users` contains the numeric smoke-test user 424242; the historical backfill insertion is logged November 27. Its account UUID `cc27b436-d6f9-4e84-adaf-e716025dd369` was created December 1 at 16:30 UTC. Query 8’s extra UUID string exclusion records that lineage but does not map namespaces. [Q-manual] [Q-qa] [R]
- **Blank brands:** first-sight inserts may have blank category/brand; `ON CONFLICT DO NOTHING` and process-local known-ID caches prevented later enrichment in the original path. The October 21 repair updates blank brand/title when a later event has a nonblank brand; current vendor upserts also preserve existing nonblank metadata when incoming metadata is blank. [C-catalog] [H-log]
- **Diagnostic versus current population:** `blank_brand_products` captures 5,972 product rows with 204 associated order units / 38,499.83 across its two suspected-cause groups; current `products` has 17,442 blank-brand rows. The diagnostic table is not a continuously refreshed inventory, and its capture timestamp is a separate temporal caveat. [Q-blank] [Q-current-blank]

Blank brand is not the same as a hidden brand. SQL `brand NOT IN ('lucente','jetem')` allows the empty string, while the brand-report router renders it as `unbranded`. Product and customer attributes used by downstream models should also be interpreted in light of `onboarding.py`’s deterministic synthesis, rather than presumed real submitted demographics. [R] [C-brand-api] [C-onboarding]

### C.4 Catalog prices and taxonomy are versioned differently

The original catalog feed inserted products without updating existing prices. Commit `d213f6e` on November 9 added upserts; `795d273` on November 15 added append-only vendor price history. Current feed handling writes `analytics.price_history` and updates `products.list_price`; orders still store the callback’s own supplied price rather than looking up the current catalog or shadow suggestion. The available price-history records begin November 18 and contain 1,400 rows for 241 products, so they are not a complete catalog-wide historical price archive. [H-log] [C-catalog] [C-orders] [Q-price-history]

Category reporting combines `category_names` (priority 0) and `category_name_history` (priority 1). For each item, it chooses a matching product category code whose `valid_from` is no later than the item’s date; latest date wins, with history winning a same-date tie. No mapping becomes `other`. This prevents joining multiple versions and multiplying revenue. [R]

The intended taxonomy changes move `construction.tools.light*` to lighting and `electronics.audio*` to entertainment. The actual supplied history dates are August 13, 2026, so **2019 examples must still use construction/electronics**. Replacing the effective-date join with “latest mapping” would rewrite old reporting. Moreover, the product’s category code itself is current metadata, not an effective-dated product-category assignment history. [Q-taxonomy] [Q-manual] [C-catalog] [R]

### C.5 Customers, accounts, contactability, and active definitions

**Shopper population versus signups.** `users.created_at` is usually first observation through a view/cart/order bootstrap. The account endpoint can also create a missing numeric user. The snapshot has 38,950 users but only 30 UUID accounts, all account creations in December. Counting user inserts as completed signups would materially misstate what the code records. There is no dedicated explicit-signup event among the observed app event types. [C-catalog] [C-accounts] [Q-customers] [Q-account-history] [Q-app-types]

**Registered reporting.** The pre-fix dashboard compared account UUID text to numeric order-user text; `b975479` replaced this on December 21 with distinct numeric users obtained through shared email. The current result is **30 buyers, 74 paid parent orders, 18,155.71 gross**. Of those orders, **63 / 14,911.96 occurred before account enrollment**. It therefore answers lifetime buyer history for currently mapped accounts, not post-registration conversion. [H-metrics] [R] [Q-registered] [Q-pre-enrollment]

`account_map` is an explicit alternative identity bridge present in the app data, but the official dashboard uses email. All 30 current mappings agree with email in this snapshot. Email is mutable, and `users.email` and `accounts.email` are not synchronized by the email-update router; future or historical mismatches require an explicit identity policy rather than an unannounced switch in dashboard semantics. [C-accounts] [C-users] [Q-map-consistency] [R]

| Customer consumer | Grain/window/status | Cleanup and measured interpretation |
|---|---|---|
| `kpi_daily.active_customers` | Distinct numeric buyers over trailing 30 days anchored at job run; status 1 | No QA, email, or brand filter. Latest stored value: **1,152** at Dec 31 11:15Z. Recomputing at Jan 1 00:00Z changes the window and yields **1,146**, so do not expect equality across cutoffs. [C-kpi] [Q-kpi-latest] [Q-actives] |
| Exec daily `active_customers` | Distinct parent-order users per New York date; dashboard’s 14-date display range; no status filter | Excludes numeric QA 424242 and parent-product Lucente/Jetem. Dec 31 example: **54**. Summing daily distinct counts does not produce a 14-day distinct population. [R] [Q-daily-example] |
| Board `active_customers` | Distinct ordering users over trailing 30 days; excludes statuses 0/2/3 | Removes `test_users` and email-domain/localpart heuristics, but no brand filter; includes held orders. Example result: **0**, after 1,151 status-eligible distinct users before email cleanup. [R] [Q-board] [Q-actives] |
| Exec `contactable_customers` | Daily ordering users who also appear in `contactable_users` | Same exec customer filters; separate from total contactable population. Current contactable population is **0**. [R] [Q-customers] |
| Funnel `users_active` | Unique users with cart or order rows in trailing day | No status, email, QA, or brand cleanup; Dec 31 output **308**, accompanied by **345 sessions**. [C-funnel] [Q-funnel-latest] |
| Digest recipients | All users whose email is not case-sensitively `LIKE '%@example.com'` | No opt-in, syntax, or board-test cleanup; outputs **40** recipients. [C-digest] [Q-digest] |

The board predicate excludes exact domains `novamart.com`, `example.com`, `example.net`, `example.org`; suffixes `.example` and `.test`; prefixes `internal.` and `test.`; and regex-delimited qa/test/demo/internal/seed/sandbox/smoke localparts or corresponding test-like domain tokens. It does not use `contactable_users` or require opt-in. A missing user/email can pass its `COALESCE`-to-empty-string checks. [R]

The trusted contactable view instead requires marketing opt-in, a case-insensitive email syntax regex, excludes exact example.com/net/org, and excludes `.example`. It does **not** contain the board’s full test-domain/localpart rule set. Current emails are **38,910 `example.com` and 40 `gmail.example`**, so every user is excluded from this view; **23** of the latter 40 are opted in, but that does not make `.example` addresses contactable. This also explains why digest “recipients = 40” and trusted “contactable = 0” can coexist. [Q-view-log] [Q-email-domains] [C-digest]

### C.6 Funnel and digest interpretation

The funnel job reads cart and order rows from its trailing 24-hour window, sorts by user/time, and splits a session when the gap is **strictly greater than** `GAP_MIN`. It does not consume `product_viewed` logs or use the supplied session IDs as its session definition. The table contains sessions and active users, not separate view/cart/purchase funnel stages. Cart removal deletes rows from `cart_items`, so recomputing old activity from current cart state is also not a durable event-log reconstruction. [C-funnel] [C-carts]

`f915c1b` increased the inactivity gap from 30 to 120 minutes on December 14; run logs show 120 beginning December 15. This mechanically merges more activity into fewer sessions and can alter any derived orders-per-session figure without changing shopper behavior. Such a derived ratio is not stored by this job. [H-log] [Q-job-config] [C-funnel]

The digest’s flag evolution is a useful operational lesson: November 28 configured `ENABLE_DIGEST=1` but checked `DIGEST_ON`; December 9 fixed the variable name; December 16 added direct reading of `deploy/cron.env`. Only December 17–31 have the 15 observed `digest_sent`/`digest_log` records. The current precedence is environment `ENABLE_DIGEST`, then environment `DIGEST_ON`, then file `ENABLE_DIGEST`, else disabled. Disabled execution returns silently. The implementation writes a log/count and contains no mail-transport call, so `digest_sent` alone is not evidence of email delivery or campaign engagement. [H-jobs] [C-digest] [C-cron-env] [Q-digest] [Q-jobs]

## Appendix D. Recommendations and other ML-like systems

### D.1 Version and serving lineage

| Version/path | Production evidence | Interpretation |
|---|---|---|
| Initial affinity writer | `776d674`, Oct 12; writes `product_affinity` | Directional same-session co-cart counts with decay. [H-log] [C-affinity] |
| Serving `1.0.0` | `f1217a8`, Oct 26; 392,630 observed v1 decision rows | Reads legacy affinity; missing scores fall back to a live seven-day paid-order bestseller query. Both model and fallback were stamped effective `1.0.0`, so use `rec_source`. [H-log] [H-rec] [Q-rec-mix] |
| Serving `2.0.0` | `df4ed85`, Dec 6; first observed v2 app read 16:40:11Z | Reads `product_affinity_v2`; adds random arm; fallback now reads latest `trending_daily`. [H-rec] [Q-score-reads] [C-similar] |
| Batch `2.0.1` | December seasonal guard fix `3dbe4d7` | Row-version stamp for repaired v2 writer, not a separate serving flag. [H-jobs] [C-affinity2] |
| Trained `4.0.0` | `a1946ff`, Dec 14; 17 model-registry rows Dec 15–31 | Artifacts exist, but flag remains v2 and decision logs show no intended/effective v4. [H-rec] [Q-models] [Q-rec-mix] [C-flags] |

The current selector uses the v2 table only for effective version `2.0.0`; other non-random version strings take the model-score branch. `1.0.0` remains in a descriptive enum, not a working rollback dispatch to the legacy table. Aliases include `2`/`v2` and `4`/`v4`/`model4`; missing flag file defaults to v2. The code reads the relative flag file on each request, despite the file comment describing deploy-time use. [C-similar] [C-flags]

### D.2 Affinity formulas and their limitations

**V1:** join cart rows on equal session and unequal product; group directional `(base_pid, rec_pid)` pairs; restrict the base-side cart timestamp to the prior 30 days; count joined row pairs and take the latest base-side timestamp. If `pairs_seen < 3`, score is −1; otherwise:

```text
score = round(pairs_seen × exp(-0.05 × age_days_since_latest_base_cart), 4)
```

The threshold was added in `fef5c96` on November 12; logs show the new min-pairs field from November 13. Repeated cart rows can multiply pair counts, the second side is not independently time-bounded, and the join does not additionally require equal user IDs. Those are the actual SQL semantics, not distinct-session support counts. [C-affinity] [H-log] [Q-job-config]

**V2** keeps the same pair construction and qualification gate, then uses:

```text
raw = (pairs_seen + 3 × converted_pair_rows) × exp(-0.05 × age_days)
if same nonblank category: raw *= 1.15
if recommendation/base current-price ratio > 4 or < 0.25: raw *= 0.7
score = round(raw × monthly_seasonal_factor, 4)
```

A “converted” pair row means the second-side user has **any status-1 parent order for the second-side product**, with no requirement that the order followed this cart session or occurred within the window. Multi-item parent-product attribution can miss conversions of non-parent items. Category and price features use current product metadata. This is a weighted heuristic association, not an experimentally estimated recommendation effect. [C-affinity2] [C-orders]

The monthly factor array has January–November entries only. Original December indexing crashed before the writer connected or created/refreshed the table. Three logged failures occurred December 3, 4, and 5 at 08:45Z. The guard in `3dbe4d7` uses 1.0 for December, and the first successful v2 refresh is December 6 at 08:45Z—before the observed serving switch later that day. These failures do not establish that the then-v1 widget was broken. [H-jobs] [Q-failures] [Q-jobs] [Q-score-reads]

The latest v1/v2 tables each contain **3,912 directional pairs, 2,964 negative sentinels**, and 1,476 base IDs. Only 948 pairs qualify; the model-score table contains those 948 pairs across 449 bases. Coverage must be evaluated against the viewed-product distribution, not merely the number of generated pairs. [Q-scores]

### D.3 What is actually served and logged

For non-random users the current handler reads only nonnegative scores from the table’s maximum `updated_at`, orders by score, takes five, and then removes excluded SKUs. Filtering **after** the limit can return fewer than five items; it does not refill the list. If no items remain or a score read fails, it reads the five highest-ranked products from the latest trending day. There is no maximum staleness age or fallback SKU filter in that branch. [C-similar]

The code labels any caught score-query exception `table_missing`, so that reason would not uniquely identify a missing table. Cache-epoch errors are swallowed, and an empty table supplies no new non-null epoch; either case can leave an old cache entry until its TTL expires. These are code-level failure possibilities, not observed `table_missing` incidents in the supplied decision-log grouping. [C-similar] [Q-rec-mix]

The latest trending top five are **1004767, 1004856, 1002544, 1005115, 1005100**. The middle two are the globally excluded test SKUs. A December 31 SQL decision-log insertion records that exact fallback list. Thus excluded-SKU protection is real in score/random paths but incomplete in fallback. [Q-trending] [Q-db-samples] [C-constants] [C-similar]

| Decision-log population | Counts / interpretation |
|---|---|
| v1 | 66,444 affinity + 326,186 fallback = 392,630; fallback **83.08%**. Both carry effective version 1.0.0. [Q-rec-mix] |
| v2 non-random | 52,695 model + 207,959 fallback = 260,654; fallback **79.78%**. [Q-rec-mix] |
| v2 random logged | 14,566 decisions, 942 distinct users; every stored random list contains five items. [Q-rec-mix] [Q-random-population] [Q-random-length] |
| Dec 27–31 non-random | 11,874 model + 38,237 fallback; fallback **76.30%** after the cache fix. This is serving coverage, not measured conversion lift. [Q-rec-latest] |

The decision log stores time, numeric user, base product, comma-separated items, intended/effective version, source, reason, and arm. It lacks a dedicated request/exposure ID and session field; app `rec_served` logs include session and item count but not item IDs or both versions. Several timestamp/user/base/arm keys occur more than once, so that tuple is not a proven unique exposure key. Do not blindly deduplicate it or many-to-many join it to outcomes. [Q-inventory] [C-similar] [Q-rec-duplicates]

### D.4 Random-arm logging regression and cache history

Users enter the random arm when the first eight hex digits of SHA-256 of their numeric ID, interpreted as an integer, are divisible by 20. The candidate pool is the **first 500 product IDs ordered by ID after excluded-SKU removal**, not the whole catalog. A `Random(f"{uid}:{session}:{pid}")` shuffle makes a given user/session/base list deterministic. Five percent is an assignment rule for users, not a promise of exactly 5% of requests, and randomness is only over this restricted pool. [C-similar]

Commit `30e8907` on December 17 added an early random-arm return before the decision-log insertion, while keeping app `rec_served` logging. `a00f24c` restored insertion on December 19. Read-only reconciliation finds **1,372 unmatched random-serving app rows**, from **2019-12-17T16:50:10Z through 2019-12-19T14:54:44Z**, using `(timestamp, user_id, base_pid, arm)` matching. [H-rec] [Q-rec-gap]

| UTC date | App random servings | Stored random decisions | Difference |
|---|---:|---:|---:|
| Dec 17 | 658 | 549 | 109 missing |
| Dec 18 | 848 | 0 | 848 missing |
| Dec 19 | 822 | 407 | 415 missing |

Separately, Dec 11 has 638 app rows versus 639 decisions; aggregate differences are not a clean one-to-one identity audit. Across all versions there are 669,190 app `rec_served` rows versus 667,850 decision rows. The missing random window is directly explained by code, but not every global count difference should be assigned to that regression. [Q-rec-gap-daily] [Q-rec-app-count] [Q-inventory] [Q-rec-duplicates]

The December 19 fix also introduced a six-hour process-local score cache keyed only by base product, including empty results. It could continue serving old or empty results after a nightly refresh, and version changes could reuse the same cache key. `8ed2971` on December 26 changed the key to `(table, base_pid)`, checks maximum score-table update time to invalidate that table’s cache, selects the latest update batch, and caches only nonempty lists. [H-rec] [C-similar]

`fallback_reason = 'cache'` is not itself proof of fallback: current successful cached model decisions also use that field. In the older cache interval, 25,091 decisions have both source fallback and reason cache; 21,427 overall v2 model decisions have reason cache. Interpret source, effective version, and reason together. Process-local caches are per worker, and autocommit table refreshes can expose incomplete new batches during refresh. [Q-rec-mix] [C-similar] [C-db] [C-affinity2]

### D.5 V4 training: implemented features versus README

The trainer fetches all logged random-arm exposures and labels an exposure positive if the same numeric user has any later current-status-1 parent order. It does not require the ordered item to be recommended, does not limit time-to-order, and does not implement a holdout split. Older exposures have more opportunity to acquire a positive label; recent exposures are right-censored. Current order status and current product/popularity features also change old training examples over time. [C-train]

| Feature mentioned or fetched | Actual training vector? |
|---|---|
| Served-list size | Yes: comma-separated item count; all 14,566 stored random lists currently have size five. [C-train] [Q-random-length] |
| Base price | Yes: current `list_price / 1000`. [C-train] |
| Base popularity | Yes: all current status-1 parent orders for base product, divided by 100; not bounded at exposure time. [C-train] |
| Account age | Yes: days from numeric user’s first-seen timestamp to exposure, divided by 60 and capped above at 1. [C-train] [C-catalog] |
| Signup channel | Yes, but only `signup_channel == 'organic'`, not all channel categories. [C-train] |
| Marketing opt-in | Fetched, explicitly omitted from the vector. [C-train] |
| Stock | Fetched, unused in the vector. [C-train] |
| Region affinity / device mix | Listed by README, absent from the training SELECT/vector. [C-readme] [C-train] |

With at least 20 rows and both labels, it fits deterministic `LogisticRegression(random_state=0, solver='lbfgs')`. It records coefficients/intercept and row count. On insufficient/single-class data it still writes a registry row with a note and leaves existing scores intact; a registry entry or `model_trained` event therefore does not alone establish fresh scores. [C-train]

Most importantly, inference does **not** use the fitted logistic prediction. It takes only the first coefficient `w` and writes:

```text
model_score(base, rec) = round(affinity_v2_score(base, rec) × (1 + 0.1 × w), 4)
```

The other coefficients and intercept do not affect stored recommendation scores. The latest training run has 14,411 rows and `w = -0.24483754375789174`, making the multiplier approximately 0.975516. The observed score ratios match this, and a deterministic score/ID rank comparison finds **zero rank changes across all 948 pairs**. This implementation is not personalized ranking and supplies no demonstrated rank-quality gain over v2; it is also not the configured serving path. [C-train] [Q-latest-model] [Q-v4-scale] [Q-v4-ranks] [C-flags]

### D.6 Other “ML” outputs

**Trending:** 30-day status-1 parent counts; minimum five; score `units * exp(-0.05 * days_since_latest_order)`; reverse tuple sort of score/units/product ID; top 50. It deletes and rewrites only the current output day. The README still says 60 days, but `f563dea` and logs show 30 from December 7. This changes list churn and recommendation fallback even without changing the affinity model. [C-trending] [C-readme] [Q-job-config] [H-log]

**Fraud:** `core = min(parent_price / 3000, 1)`; multiply by `1 + 0.15*new_account + 0.15*high_velocity`, cap at 1, round four decimals. New-account means order less than seven days after user creation; velocity means at least three orders in the inclusive prior 24 hours, including the current order. Score only status-1 orders in the trailing day, append risk rows, and set status 6 when score is strictly above threshold. This is a price/user heuristic without observed labeled-fraud evaluation. [C-fraud]

Threshold logs show **0.90 on Dec 4–5, 0.70 on Dec 6–29, and 0.85 on Dec 30–31**. `1cb8721` raised the threshold; a separate December 29 backfill released held orders priced below 2,600. Five risk-scored orders above 0.70 are currently paid with the later update timestamp discussed in Appendix A; 12 current held orders total 40,213.29. A KPI jump after this release is not necessarily new customer demand. [Q-job-config] [H-orders] [Q-manual] [Q-risk-release] [Q-status]

**Pricing:** `price_suggest` selects the top 500 current products by trailing-14-day paid parent-order count, compares demand with the middle selected row’s count, and nudges current list price by +5% above that count, otherwise −5%. The table is deleted/repopulated nightly. `cca9b0d` put serving rollout on hold; the flag file has no pricing activation flag, and the historical SQL search found **zero SELECT/WITH reads from the suggestion table**. Order prices remain request-supplied, catalog prices vendor-supplied. Fresh suggestions do not establish a live pricing experiment. [C-pricing] [C-flags] [Q-pricing-reads] [C-orders] [C-catalog] [H-log]

**Reorder hints:** for the top 200 products by trailing-14-day paid parent-order velocity, `velocity = count / 14`, then `int(15.6 + K / (velocity + 1.8))`. `f85cdd2` changed only K from **141.12 to 162.4**. Latest output: 200 rows, velocities 0.0714–2.7143, hints 51–102. The inverse formula gives **larger hints to lower velocity**, and uses no lead time, open purchase orders, inventory target, or forecast uncertainty. Treat it as the explicitly advisory merchandising heuristic, not a validated procurement quantity. [C-reorder] [H-jobs] [Q-forecast] [C-forecast-doc]

### D.7 Evaluation plan supported by the observed defects

The following are proposed changes to evaluation practice, not claims that these tests already exist:

1. Add stable exposure/request identity and preserve session, served items, rank, arm, intended/effective version, score-batch timestamp, and reason; reconcile app servings to decision writes. The current schema and regression show why these fields matter. [Q-inventory] [C-similar] [Q-rec-gap]
2. Evaluate post-exposure outcomes within a fixed, fully observed window and at line/product grain; freeze features at exposure time. Current any-future-order labels and current-feature joins are insufficient for attributable recommendation quality. [C-train] [C-orders]
3. Hold out users/time, report uncertainty at the randomized user unit, check assignment balance, and analyze the assigned policy with fallback included. Randomized users are not interchangeable independent impressions, and the catalog candidate pool is restricted. [C-similar] [Q-rec-mix]
4. Before calling v4 an improvement, require a scoring function that can actually change candidate ranking and then measure ranking/online outcomes. The current stored ranks do not change. [Q-v4-ranks] [C-train]
5. Evaluate fraud against adjudicated outcomes and business cost; evaluate reorder hints against inventory-aware forecast/purchasing outcomes. Neither writer contains that validation, and pricing has no observed served treatment. [C-fraud] [C-reorder] [C-pricing] [Q-pricing-reads]

## Appendix E. Scheduled jobs, dependencies, and safe modification

### E.1 Scheduling authority and migration gaps

Commit `4bfcbe6` retired the crontab and added one-task Airflow DAGs. The wrappers use naive `datetime` start dates, `catchup=False`, and simple `python -m ...` commands. They specify no timezone, working directory, cross-DAG dependency, retry policy, or historical execution timestamp. Consequently the old crontab’s “times are local” comment does not prove the deployed Airflow timezone; the scheduler configuration is outside the observed sources. [H-log] [C-cron] [C-dags]

There is a concrete migration mismatch: the retired schedule lists intraday runs at **12:00 and 17:00**, and historical logs show both, but the checked-in Airflow DAG schedules **only `0 12 * * *`**. The warehouse DAG is manual and invokes the module without its required `--project`, `--instance`, and `--staging` arguments. These are code-level migration defects/requirements; there are no January execution logs here proving their runtime resolution. [C-cron] [C-intraday-dag] [Q-report-versions] [C-warehouse-dag] [C-backfill] [Q-coverage]

### E.2 Complete job inventory

Schedules below are the literal Airflow cron expressions; timezone requires deployed configuration confirmation. Every ordinary wrapper runs `python -m novamart.jobs.<job>`; source paths and historical output counts are in the cited evidence. [C-dags] [Q-jobs]

| Job / schedule | Inputs → output and write mode | Consumer / failure consequence |
|---|---|---|
| `reconcile` / `0 3 * * *` | Repeated order references except status 5 → warning logs; sorted `LIMIT 200`; no correction | Finance/ops lose anomaly visibility if it fails; it does not repair revenue. 107 completed runs observed. [C-reconcile] [Q-jobs] |
| `affinity` / `30 3 * * *` | Cart pairs → full delete/repopulate `product_affinity`; also bootstraps decision-log table | Legacy widget input; no current widget consumer under v2, but retains bootstrap side effect. 80 refreshes. [C-affinity] [C-similar] [Q-jobs] |
| `affinity_v2` / `45 3 * * *` | Cart pairs + parent orders + products → full delete/repopulate `product_affinity_v2` | Current v2 serving and v4 candidate input; failure can leave stale/missing/partial scores and trigger fallback. 26 successes, three crashes. [C-affinity2] [Q-jobs] [Q-failures] |
| `model_train` / `15 4 * * *` | Random decision rows + users/products/orders + v2 candidates → registry append, score full replacement only on successful fit | Potential v4 input, not active v2 serving; a registry row may accompany unchanged scores. 17 runs. [C-train] [C-flags] [Q-jobs] |
| `price_suggest` / `45 4 * * *` | Paid-parent 14-day demand + catalog prices → full replacement of suggestions | Shadow analytics; no observed current serving reads. 37 refreshes. [C-pricing] [Q-pricing-reads] [Q-jobs] |
| `trending` / `15 5 * * *` | Paid-parent rolling counts → replace current day’s top 50 | Similar-product fallback; old latest day remains usable without freshness enforcement. 59 refreshes. [C-trending] [C-similar] [Q-jobs] |
| `fraud_score` / `45 5 * * *` | Recent paid orders + users/order velocity → append risk rows, mutate order status to 6 | Changes status-1 finance/KPI/ranking populations; report/board status predicates still include held orders. 28 runs. [C-fraud] [C-statement] [C-report] [R] [Q-jobs] |
| `daily_report` / `0 6 * * *` | Yesterday’s filtered items → append `report_rows` | Closed-day executive sales/widget input; absent or partial output affects chart and totals. 107 start/success pairs. [C-report] [R] [Q-jobs] |
| `kpi_daily` / `15 6 * * *` | Trailing-30-day paid parent buyers → append one KPI row | Nightly active-buyer history; not the source of the exec customer CTE. 45 rows/runs. [C-kpi] [R] [Q-jobs] |
| `funnel` / `20 6 * * *` | Trailing-day cart/order rows → append session/user counts | Session denominator history; gap changes create a metric break. 53 runs. [C-funnel] [Q-jobs] |
| `monthly_statement` / `30 6 1 * *` | Previous local month’s paid parents + payment fees → append snapshot | Base for all statement layers; reruns create extra publications. Three observed runs. [C-statement] [Q-view-log] [Q-jobs] |
| `top_sellers` / `45 6 * * *` | Yesterday’s paid parent products → append ranked `top_products` | Nightly units list; not the Redash best-sellers query. 55 runs. [C-top] [R] [Q-jobs] |
| `reorder_forecast` / `50 6 * * *` | Paid-parent 14-day velocity → full replacement of 200 hints | Advisory merchandising output; no observed finance/report dependency in current code. 35 runs. [C-reorder] [C-forecast-doc] [Q-jobs] |
| `email_digest` / `15 7 * * *` | Flag + seven-day paid parent top product + loose email count → append digest log | Flag-disabled return is silent; logged send is not transport confirmation. 15 logged outputs. [C-digest] [Q-jobs] |
| `intraday_report` / `0 12 * * *` | Today-to-run-time filtered items → append cumulative snapshots | Today’s sales/KPI/widget input; legacy 17:00 run missing from wrapper. 47 historical start/success pairs. [C-intraday] [C-intraday-dag] [Q-jobs] |
| `warehouse_backfill` / manual | Manifest serving tables → serialized CSV exports and `bq load --replace` | Warehouse rebuild, not an incremental feed; wrong analytics dataset mapping and missing wrapper arguments need resolution before use. [C-backfill] [C-warehouse-dag] [Q-inventory] |

### E.3 Actual dependency graph versus coincident schedules

- **Recommendation dependency:** cart/order/product data → v2 affinity → optional model training; serving reads v2/model scores and trending fallback. Chronological schedules place training after affinity, but no DAG dependency enforces completion or consistent input batches. [C-affinity2] [C-train] [C-similar] [C-dags]
- **Financial/reporting dependency:** order/payment/status mutations → report and statement jobs; approved manual overrides and chargebacks → finance views → query 5. Status changes and snapshots run on different clocks, so a later raw query can disagree with a successful older publication. [C-fraud] [C-report] [C-statement] [Q-view-log]
- **Customer dependency:** auto-created users and mutable emails → account/email matching and contactable view; orders → distinct buyers; cart/order state → funnel. These are not interchangeable registration/activity feeds. [C-catalog] [C-users] [C-accounts] [C-funnel] [R]
- **Bootstrap dependency:** `schema.sql` has only the initial app tables. Runtime DDL and manual historical backfills provision additional tables/views; notably the old affinity job creates `rec_decision_log`. Retiring that writer without a replacement schema migration could break a clean bootstrap even if its scores are no longer read. [C-schema] [C-affinity] [Q-view-log] [Q-manual]

### E.4 Failure modes that matter before a rerun or extension

**Autocommit refreshes are not atomic.** `db.job_connect()` uses `autocommit=True`; affinity, pricing, forecast, and model-score refreshes delete then insert rows individually. A failure after deletion can expose empty or partial outputs. A maximum timestamp is not a completion marker. The new serving cache epoch can notice the first inserted row of an incomplete batch, and the report dashboards’ `MAX(created_at)` can select a partially written report. [C-db] [C-affinity2] [C-train] [C-pricing] [C-reorder] [C-report] [C-similar] [R]

**Append-only jobs are not idempotent reruns.** Daily/intraday reports, KPI/funnel rows, top-product ranks, statements, digest logs, and risk history append without a run-uniqueness constraint in their writer definitions. Latest-version selection helps the specific dashboards, but raw sums can double-count; identical timestamps would not distinguish separate attempts. Fraud reruns also operate on already-mutated status populations. [C-report] [C-intraday] [C-kpi] [C-funnel] [C-top] [C-statement] [C-digest] [C-fraud]

**Historical execution is not parameterized consistently.** `timeutil.now()` accepts `FAKE_NOW`, but several rolling queries have only a lower bound, and model labels/popularity have no exposure/run upper bound. Applying an old clock to a database containing later records can still leak future data. Airflow wrappers do not pass the logical execution date. A correct backfill needs bounded source data and historical-state semantics, not only a fake clock. [C-time] [C-kpi] [C-affinity2] [C-train] [C-dags]

**Reconcile scheduling:** `388370b` moved it from 02:00 to 03:00 with a commit message noting backup overlap. The observed completed-run mean rises from 4.17 ms before the new schedule to 5.74 ms after, maximum 9.8 ms; no reconcile crashes are logged. The sources support a schedule-overlap concern, not a proven timeout incident. Batch size rose 100→200 in `030d841`; latest runs repeatedly flag the same 130 references. [H-jobs] [Q-reconcile-runtime] [Q-failures]

**Discount rerun trap:** `DISCOUNT_CAP` is 0.25, but `apply_discounts(rows, cap=0.40)` retains the legacy default, and `scripts/rerun_kpis.py` omits the argument. A 100-unit amount becomes 60 rather than 75. The helper currently has an empty manually populated input and only prints; the reviewed report/statement writers do not invoke it. Treat it as a hazardous one-off recipe, not evidence that production statement revenue was discounted by 40%. [C-discounts] [C-rerun] [C-constants] [C-report] [C-statement] [H-jobs]

### E.5 Proposed safe change procedure

1. **Read-only preflight:** record source cutoff, relevant schemas, output batch timestamps/row counts, current flags, and matching job success/failure logs. Check consumers using code, Redash, and historical SELECT lineage rather than job/table names. [Q-inventory] [Q-jobs] [Q-score-reads] [R]
2. **Specify the metric contract:** entity grain, status policy, QA/SKU/brand filters, calendar/window, historical-state handling, and as-published versus restated output. Explicitly decide whether a change intentionally breaks comparison with old outputs. [C-report] [C-statement] [C-metric-definitions]
3. **Design an atomic publication boundary and rerun identity:** compute a complete version, validate it, then publish it; make retries select/replace a known version instead of blindly appending. This is a recommendation addressing the observed autocommit and snapshot risks, not the current implementation. [C-db] [C-report] [C-affinity2] [R]
4. **Enforce real dependencies and freshness checks:** training requires a completed candidate batch; serving requires a completed/fresh score or fallback batch; finance requires explicit publication and adjustment inputs. Fix scheduling timezone, working directory, arguments, and missing intraday run as part of the contract. [C-dags] [C-warehouse-dag] [C-backfill] [C-similar]
5. **Verify meaningful cases before deployment:** replayed callback; multi-item parent; cancellation/refund/hold; November DST boundary; >500-row day; zero-output day; two intraday versions; incomplete refresh; all 12 seasonal months; disabled flag; random-arm logging; old/new identity namespaces. These cases derive from concrete defects and current code paths above. The existing CI smoke test exercises only basic app/order flow and three jobs, and is not sufficient evidence for these contracts. [C-ci] [H-orders] [H-rec] [Q-failures] [Q-cap] [Q-empty-job]

The provided CI script truncates scratch tables and invokes writing jobs, so it was inspected rather than executed for this read-only investigation. Validation here consists of metadata reads, independent SELECT reconciliations, and checks of the produced document/artifacts. [C-ci] [C-investigation]

## Appendix F. Data catalog and ownership

All warehouse table names below are in project `novamart-warehouse`. Counts are observed metadata counts for tables; view results must be queried rather than interpreting their metadata `numRows = 0` as empty contents. Writer ownership is derived from current code and historical SQL, not inferred from table naming. [Q-inventory] [Q-view-log] [Q-manual]

### F.1 App dataset: `novamart`

| Table / rows | Grain and important keys | Writer / principal consumers |
|---|---|---|
| `users` / 38,950 | Numeric shopper ID; mutable email and synthesized attributes; first-seen creation | Catalog/entity bootstrap, account definition, email-update definition; buyers, identity mapping, ML features. [C-catalog] [C-accounts] [C-users] [C-onboarding] |
| `accounts` / 30 | UUID account enrollment and copied email | Account-router definition; registered dashboard. [C-accounts] [R] |
| `account_map` / 30 | Numeric uid ↔ UUID plus link time | Account-router definition; explicit identity bridge, not used by query 4. [C-accounts] [R] |
| `products` / 81,018 | Product ID, current brand/category/list price/cost/stock | First-sight bootstrap and vendor feed; item grouping and ML heuristics. [C-catalog] [C-onboarding] |
| `cart_items` / 36,938 | Cart rows with user/product/session/time; repeated adds possible, remove deletes matches | Cart API; affinity and funnel. [C-carts] [C-affinity] [C-funnel] |
| `orders` / 9,127 | Parent order; current status, summed price after append, original product/ref/time | Payment callbacks and lifecycle/risk changes; statements, buyer metrics, parent-grain jobs. [C-orders] [C-fraud] [C-statement] |
| `order_lines` / 2,284 | One item callback per reference; parent ID, product, price, session, time | Current callback path; daily reports and item dashboards. [C-orders] [C-report] [R] |
| `payments` / 9,361 | Money movement; parent ID, gross/fee/net, nullable reference | Callback and gateway-refund paths; fee source and payment-ledger reporting. [C-orders] [C-webhook] [C-statement] |
| `report_rows` / 6,923 | Product × report date × run timestamp | Daily writer; latest closed-day dashboard snapshots. [C-report] [R] |
| `report_rows_intraday` / 2,358 | Product × report date × cumulative snapshot timestamp | Intraday writer; today’s partial sales. [C-intraday] [R] |
| `statements` / 3 | Month × publication run | Monthly writer; overrides/final views and historical deck reproduction. [C-statement] [Q-view-log] |
| `top_products` / 2,396 | Report date × rank × run | Top-sellers writer; separate from query 9. [C-top] [R] |

The initial schema is not a complete migration specification: it lacks lines, account tables, intraday/top-product tables, newer payment reference column, and analytics objects. The callback creates partial unique indexes on newer references, but old parent references are not globally unique and old payment references may be null. Warehouse metadata does not enforce the serving database’s intended relational contracts. [C-schema] [C-orders] [Q-inventory] [Q-duplicates]

### F.2 Analytics dataset: `novamart_analytics`

| Table / rows | Grain / provenance | Main use |
|---|---|---|
| `blank_brand_products` / 5,972 | One-time engineer diagnostic product snapshot | Explains missing metadata; not a current brand dimension. [Q-manual] [Q-blank] |
| `category_names` / 135 | Category-code mapping with effective date | Baseline taxonomy; query 6. [Q-manual] [R] |
| `category_name_history` / 6 | Additional category-code versions | Effective-date remaps; actual history dates require care. [Q-taxonomy] [R] |
| `chargebacks` / 3 | Booked order-linked amount and reported time | Final statement adjustment. [Q-chargebacks] [Q-view-log] |
| `daily_funnel` / 53 | Run-date/session/user-count snapshot | Activity denominators. [C-funnel] |
| `digest_log` / 15 | Timestamp, recipient count, top product | Digest job output audit, not delivery confirmations. [C-digest] |
| `kpi_daily` / 45 | Run-date trailing-buyer snapshot | Nightly active customers. [C-kpi] |
| `model_registry` / 17 | Model version × train run with coefficient JSON and row count | Training audit; does not prove deployment. [C-train] [C-flags] |
| `model_scores` / 948 | Latest base/recommendation pair score | Flag-gated v4 candidate ranking. [C-train] [C-similar] |
| `order_risk` / 1,631 | Order score per scoring run; core and boolean features | Fraud heuristic audit and hold generation. [C-fraud] |
| `price_history` / 1,400 | Vendor product price event | Partial historical catalog prices, not charged order prices. [C-catalog] [Q-price-history] |
| `price_suggestions` / 500 | Latest product recommendation | Shadow pricing output. [C-pricing] |
| `product_affinity` / 3,912 | Latest directional co-cart pair | Legacy model output; still refreshed. [C-affinity] [Q-score-reads] |
| `product_affinity_v2` / 3,912 | Latest weighted pair, batch version `2.0.1` | Live v2 serving and v4 candidates. [C-affinity2] [C-similar] [C-train] |
| `rec_decision_log` / 667,850 | Serving-decision rows without unique exposure key | Training and serving audit; known completeness regression. [C-similar] [Q-rec-gap] |
| `reorder_hints` / 200 | Latest product velocity/hint | Advisory merchandising. [C-reorder] |
| `statement_corrections` / 1 | Month, delta, reason | Audit note; November delta zero. [Q-corrections] |
| `statement_overrides` / 1 | Month replacement values | Approved October fee correction. [Q-overrides] |
| `test_users` / 1 | Known test shopper ID | Daily-report and board cleanup; current member 424242. [Q-manual] [C-report] [R] |
| `trending_daily` / 2,898 | Day × rank | Recommendation fallback and ranking history. [C-trending] [C-similar] |

| View | Definition/source contract |
|---|---|
| `contactable_users` | Numeric users passing opt-in, syntax, and example-domain rules. [Q-view-log] |
| `refunds_unified` | Status-2/3 order indications plus negative payment movements, `UNION ALL`. [Q-view-log] |
| `statements_corrected` | Published statements with month overrides; no correction-delta subtraction. [Q-view-log] |
| `statements_final` | Corrected statements less booked chargebacks by original local order month. [Q-view-log] |

### F.3 Logs and warehouse rebuild

| Log surface | Observed size / use |
|---|---|
| `novamart_logs.app_events` | 1,570,017 rows; JSON event payloads, including views, carts, orders, accounts, refunds, rec servings, and finance warnings. [Q-inventory] [Q-app-types] |
| `novamart_logs.db_queries` | 3,597,650 rows; raw `textPayload` with timestamp, actor, statement, parameters. Includes app, job, engineer, and engineer-backfill actors. [Q-inventory] [Q-actors] [Q-manual] |
| `novamart_logs.job_runs` | 978 rows; start/completion/statistics/error events, not 978 distinct scheduled runs. Some jobs log both start and completion; others log only completion. [Q-inventory] [Q-jobs] |
| `novamart_logs.db_queries_normalized` | Convenience view with query/job-shaped columns; this investigation relied on raw source statements for historical operations. [Q-inventory] [Q-manual] |

The backfill manifest covers the 32 serving tables, with explicit column/type lists, timestamp-to-UTC rendering, numeric/date/UUID-to-text casts, and `__PGNULL__` sentinel handling to distinguish null from blank text. It serializes Cloud SQL CSV exports and replaces each destination table on load. It does not recreate the four analytics view definitions, transport log exports, or establish one cross-table transactionally consistent snapshot. Those objects and freshness guarantees need their own provisioning/reconciliation. [C-backfill] [C-manifest] [Q-inventory]

At the pinned revision, `dataset = "novamart" if schema == "public" else schema` targets `analytics.*`, while the inspected destination is `novamart_analytics.*`. The manual DAG also supplies none of the loader’s required arguments. Do not treat this checked-in wrapper as a verified complete warehouse rebuild procedure. [C-backfill] [C-warehouse-dag] [Q-inventory]

## Appendix G. Historical change index

Dates below are commit dates unless an observed run is explicitly stated. A commit title alone does not prove a backfill executed or that historical snapshots were rewritten; the linked logs/results supply those distinctions. [H-log] [Q-manual] [Q-jobs]

| Date | Commit(s) | Durable interpretation |
|---|---|---|
| Sep 15 | `2da4141` | Initial service/schema/dashboard import. [H-log] |
| Oct 8 | `83fb3ed` | Test-SKU daily-report exclusion. [H-metrics] |
| Oct 12 | `776d674` | Legacy affinity writer. [H-log] [C-affinity] |
| Oct 15 | `b676969`, `7f24380` | Callback idempotency and order-duration logging. [H-orders] [H-log] |
| Oct 16 | `088a372` | Email-update router definition; email becomes an explicitly mutable identity attribute. [H-log] [C-users] |
| Oct 18 | `030d841` | Reconcile limit 100→200. [H-jobs] |
| Oct 21 | `ea0e97b`, `193f22d` | Blank-brand repair and monthly brand-report definition. [H-log] [C-catalog] [C-brand-api] |
| Oct 25–28 | `ba1fbfa`, `f1217a8`, `8f19718` | Hide Lucente in reports; similar widget v1; cancellation status 4→2 and replay lifecycle fix. [H-metrics] [H-log] [H-orders] |
| Nov 2 | `a92c96d`, `152a760` | Statement fee collection fix/October override lineage; trending introduced with 60-day window. [H-finance] [Q-overrides] [H-log] |
| Nov 5–10 | `102c9b4`, `9a51155`, `4dbcf7f`, `d213f6e`, `388370b` | DST window fix; top sellers; funnel; catalog price upserts; reconcile moved to 03:00. [H-orders] [H-log] [H-jobs] |
| Nov 12 | `fef5c96` | Rare affinity pairs receive −1 sentinel; first corresponding log field Nov 13. [H-log] [Q-job-config] |
| Nov 15–19 | `d87cb3d`, `795d273`, `14726e7`, `11c0a42`, `1233af8` | Refund status, price history, trailing buyer KPI, report status cleanup, scan-cap removal. [H-log] [H-metrics] [H-orders] |
| Nov 20–22 | `12e1c68`, `35c581e`, `5d1300d` | Flat processor fee; discount-cap/helper mismatch; session-merged orders and item/payment reference grain. [H-log] [H-jobs] [H-orders] |
| Nov 24–30 | `894c535`, `f5e3032`, `b59f077`, `b567d9d`, `c19a307`, `2814b3d` | Shadow pricing, reorder hints, QA cleanup, accounts, digest, category reporting. [H-log] [H-metrics] [H-jobs] |
| Dec 2–5 | `4a58d17`, `89666bf`, `cca9b0d`, `e4656fb`, `e10cb0c`, `c49a7bb`, `92596dc`, `53f6f6c`, `3dbe4d7` | Fee diagnostic/audit, affinity v2 and pricing hold, fraud, contactable view, gateway refunds, item reporting, tighter fraud threshold, seasonal crash fix. [H-log] [H-finance] [H-jobs] [Q-view-log] |
| Dec 6–9 | `f563dea`, `df4ed85`, `a2e0013`, `cd559d3`, `8dc520b` | Shorter trending window, v2/random serving, intraday snapshots, final statements, first digest flag fix. [H-log] [H-rec] [H-finance] [H-jobs] |
| Dec 10–14 | `d6e34c6`, `2dde4f0`, `33054cd`, `a1946ff`, `f915c1b` | Registered/board dashboards, taxonomy history, v4 trainer, 120-minute sessions. [H-log] [H-rec] [Q-taxonomy] |
| Dec 15–19 | `1169e40`, `0bd4eac`, `30e8907`, `adbcb7e`, `a00f24c`, `686a5d6` | Jetem exclusion, file-based digest flag, lost/restored random logging, QA UUID exclusion, cache, initial revenue widget. [H-log] [H-metrics] [H-jobs] [H-rec] |
| Dec 21–26 | `f85cdd2`, `b975479`, `a3bffec`, `3eced24`, `8ed2971` | Reorder constant retune, identity join fix, unified refunds, snapshot-safe widget, cache invalidation. [H-jobs] [H-metrics] [H-finance] [H-rec] |
| Dec 29–30 | `1cb8721`, `dd0c8fc`, `a576d0d` | Fraud threshold 0.85/release lineage; explicit active-definition and restatement policy docs. [H-orders] [Q-manual] [C-metric-definitions] [C-restatement] |
| Jan 2–5 | `d398b0d`, `41e3537`, `4bfcbe6`, `5ae1182` | Data-access documentation, dashboards moved to Redash, crontab retired for Airflow, warehouse backfill added. [H-log] [C-access] [C-cron] [C-backfill] |

## Appendix H. Read-only SQL recipes

These are BigQuery-style `SELECT` recipes. Unqualified dataset names refer to project `novamart-warehouse`; Postgres/Redash SQL uses `public`/`analytics` and different date syntax. The exact executed investigation SQL and results are retained in the query artifacts. Use explicit historical cutoffs when adapting rolling dashboard queries. [Q-inventory] [R] [C-investigation]

### H.1 Retrieve all finance layers before arguing about a month

```sql
SELECT 'published' AS layer, * FROM novamart.statements
UNION ALL
SELECT 'corrected' AS layer, * FROM novamart_analytics.statements_corrected
UNION ALL
SELECT 'final' AS layer, * FROM novamart_analytics.statements_final
ORDER BY month, layer;
```

This is the executed query behind the statement table and October bridge. Filter to the requested month after choosing the publication/restatement meaning; do not aggregate the three layers together. [Q-finance] [C-restatement]

### H.2 Recompute the monthly job’s current-state gross/fee/net without join inflation

```sql
WITH fees AS (
  SELECT order_id, SUM(fee) AS fee
  FROM novamart.payments
  GROUP BY order_id
)
SELECT FORMAT_TIMESTAMP('%Y-%m', o.created_at, 'America/New_York') AS month,
       COUNT(*) AS orders,
       SUM(o.price) AS gross,
       SUM(f.fee) AS fee,
       SUM(o.price) - SUM(f.fee) AS net
FROM novamart.orders o
LEFT JOIN fees f ON f.order_id = o.id
WHERE o.status = 1
GROUP BY month
ORDER BY month;
```

Pre-aggregation prevents several payments per parent from multiplying parent gross. This reproduces current-state monthly-job semantics, not an old publication or a gateway-refund-adjusted revenue policy. Validate missing payments separately if extending it to new data. [Q-recompute] [C-statement] [C-orders]

### H.3 Reproduce refund-dashboard components

```sql
SELECT FORMAT_TIMESTAMP('%Y-%m', at, 'America/New_York') AS month,
       kind, COUNT(*) AS n, SUM(amount) AS amount
FROM novamart_analytics.refunds_unified
GROUP BY month, kind
ORDER BY month, kind;
```

Summing kinds within month reproduces query 1. Preserve the breakdown to distinguish operational cancellations from negative money movements. [Q-refunds] [R]

### H.4 Construct the common item grain

```sql
WITH item_orders AS (
  SELECT o.id AS order_id, o.user_id, o.status,
         ol.product_id, ol.price, ol.created_at
  FROM novamart.orders o
  JOIN novamart.order_lines ol ON ol.order_id = o.id
  UNION ALL
  SELECT o.id, o.user_id, o.status,
         o.product_id, o.price, o.created_at
  FROM novamart.orders o
  WHERE NOT EXISTS (
    SELECT 1 FROM novamart.order_lines ol WHERE ol.order_id = o.id
  )
)
SELECT io.product_id, COUNT(*) AS units, SUM(io.price) AS revenue
FROM item_orders io
JOIN novamart.products p ON p.id = io.product_id
WHERE io.created_at >= TIMESTAMP('2019-12-25 00:00:00+00')
  AND io.user_id <> 424242
  AND p.brand NOT IN ('lucente', 'jetem')
GROUP BY io.product_id
ORDER BY revenue DESC
LIMIT 20;
```

This matches the example best-sellers semantics on the bounded supplied export. A historical rerun against later data must add the chosen upper time bound. Adding `status = 1` or the report SKU exclusions would intentionally change the official dashboard definition. [Q-best-example] [R]

### H.5 Select one completed report version and only today’s intraday version

```sql
WITH daily AS (
  SELECT r.*
  FROM novamart.report_rows r
  JOIN (
    SELECT report_date, MAX(created_at) AS created_at
    FROM novamart.report_rows
    WHERE report_date >= DATE('2019-12-25')
      AND report_date < DATE('2019-12-31')
    GROUP BY report_date
  ) v USING (report_date, created_at)
), intraday AS (
  SELECT r.*
  FROM novamart.report_rows_intraday r
  WHERE report_date = DATE('2019-12-31')
    AND created_at = (
      SELECT MAX(created_at)
      FROM novamart.report_rows_intraday
      WHERE report_date = DATE('2019-12-31')
    )
)
SELECT SUM(revenue) AS revenue_7d
FROM (
  SELECT revenue FROM daily
  UNION ALL
  SELECT revenue FROM intraday
);
```

This returns the corrected 139,598.13 example. The read pattern matches the dashboard but cannot independently prove a latest batch is complete; check job completion/output counts as well. [Q-widget] [R] [C-db] [C-report]

### H.6 Audit actual recommendation paths

```sql
SELECT intended_version, effective_version, rec_source,
       fallback_reason, arm, COUNT(*) AS n,
       MIN(ts) AS first_at, MAX(ts) AS last_at
FROM novamart_analytics.rec_decision_log
GROUP BY intended_version, effective_version, rec_source,
         fallback_reason, arm
ORDER BY n DESC;
```

Use this instead of counting intended model versions as successful model service. It distinguishes v1’s misleading fallback version stamp, v2 fallback/cache paths, random-arm traffic, and the absence of v4 serving in the supplied log. [Q-rec-mix]

### H.7 Find recorded batch failures and historical view creation

```sql
SELECT timestamp, severity, TO_JSON_STRING(jsonPayload) AS payload
FROM novamart_logs.job_runs
WHERE severity <> 'INFO'
ORDER BY timestamp;
```

```sql
SELECT timestamp, textPayload
FROM novamart_logs.db_queries
WHERE REGEXP_CONTAINS(LOWER(textPayload), r'create (or replace )?view')
ORDER BY timestamp;
```

These are read-only queries **about** historical writes, not instructions to execute the logged DDL. The first exposes the affinity seasonal crashes; the second recovers view contracts omitted from the base schema. [Q-failures] [Q-view-log]

## Appendix I. Evidence index and remaining boundaries

### I.1 How to follow citations

`C-*` links point to the pinned repository files, except the two explicitly identified investigation scripts stored beside this document. `H-*` links are saved read-only git history/diffs. `Q-*` links contain exact SELECT SQL plus results; timestamp numbers in their REST output are microseconds since Unix epoch. `R` links contain the retrieved Redash SQL/metadata, including query IDs. The document is the single Markdown deliverable; the neighboring JSON, Python, text, and patch files are its intermediate evidence artifacts. [C-collector] [C-investigation] [R-inventory]

### I.2 Unresolved or bounded conclusions

- **Approved finance versus complete money adjustments:** final statements have a clear documented authority, but their view does not automatically consume gateway refunds. This investigation establishes the implemented policy and the recorded movements, not a new approved accounting treatment. [C-restatement] [Q-view-log] [Q-gateway]
- **Historical states:** snapshot values with later mutations and execution-time backfill dates prevent universal reconstruction of the old database from event timestamps alone. Original publications and logs are necessary, but raw SQL logs record attempts rather than returned results. [Q-future] [Q-taxonomy] [C-db]
- **Live infrastructure after migration:** deployed Airflow timezone/arguments/working directory, additional router wiring, and continuing warehouse synchronization are not established by the checked-in wrappers or the through-December logs. [C-dags] [C-app] [C-backfill] [Q-coverage]
- **Retiring legacy affinity:** no current widget read and no later app read is observed, but the writer still bootstraps decision-log schema. The allowed repository/log/dashboard scope cannot prove the absence of every unobserved external consumer. [C-affinity] [C-similar] [Q-score-reads] [R]
- **Model business value:** the sources establish execution, logging gaps, coverage, heuristic mechanics, and v4’s unchanged ranks. They do not establish causal uplift or calibrated fraud/forecast performance. Treat the proposed evaluations as work still required. [C-train] [Q-rec-gap] [Q-v4-ranks] [C-fraud] [C-reorder]

### I.3 Citation targets

[Run]: run_metadata.json
[C-access]: ../novamart/docs/data-access.md
[C-restatement]: ../novamart/docs/restatement_policy.md
[C-metric-definitions]: ../novamart/docs/metrics_definitions.md
[C-readme]: ../novamart/README.md
[C-forecast-doc]: ../novamart/docs/forecast_caveats.md
[C-schema]: ../novamart/schema.sql
[C-app]: ../novamart/novamart/app.py
[C-db]: ../novamart/novamart/db.py
[C-onboarding]: ../novamart/novamart/onboarding.py
[C-catalog]: ../novamart/novamart/routers/catalog.py
[C-carts]: ../novamart/novamart/routers/carts.py
[C-orders]: ../novamart/novamart/routers/orders.py
[C-webhook]: ../novamart/novamart/routers/payments_webhook.py
[C-accounts]: ../novamart/novamart/routers/accounts.py
[C-users]: ../novamart/novamart/routers/users.py
[C-brand-api]: ../novamart/novamart/routers/reports.py
[C-similar]: ../novamart/novamart/routers/similar.py
[C-constants]: ../novamart/novamart/constants.py
[C-time]: ../novamart/novamart/jobs/timeutil.py
[C-statement]: ../novamart/novamart/jobs/monthly_statement.py
[C-report]: ../novamart/novamart/jobs/daily_report.py
[C-intraday]: ../novamart/novamart/jobs/intraday_report.py
[C-kpi]: ../novamart/novamart/jobs/kpi_daily.py
[C-top]: ../novamart/novamart/jobs/top_sellers.py
[C-funnel]: ../novamart/novamart/jobs/funnel.py
[C-reconcile]: ../novamart/novamart/jobs/reconcile.py
[C-affinity]: ../novamart/novamart/jobs/affinity.py
[C-affinity2]: ../novamart/novamart/jobs/affinity_v2.py
[C-train]: ../novamart/novamart/jobs/model_train.py
[C-trending]: ../novamart/novamart/jobs/trending.py
[C-fraud]: ../novamart/novamart/jobs/fraud_score.py
[C-pricing]: ../novamart/novamart/jobs/price_suggest.py
[C-reorder]: ../novamart/novamart/jobs/reorder_forecast.py
[C-digest]: ../novamart/novamart/jobs/email_digest.py
[C-discounts]: ../novamart/novamart/jobs/discounts.py
[C-rerun]: ../novamart/scripts/rerun_kpis.py
[C-flags]: ../novamart/deploy/flags.env
[C-cron-env]: ../novamart/deploy/cron.env
[C-cron]: ../novamart/crontab.txt
[C-dags]: ../novamart/airflow/dags/
[C-dag]: ../novamart/airflow/dags/daily_report_dag.py
[C-intraday-dag]: ../novamart/airflow/dags/intraday_report_dag.py
[C-warehouse-dag]: ../novamart/airflow/dags/warehouse_backfill_dag.py
[C-backfill]: ../novamart/novamart/jobs/warehouse_backfill.py
[C-manifest]: ../novamart/novamart/jobs/warehouse_manifest.json
[C-ci]: ../novamart/ci/run_ci.py
[C-collector]: evidence.py
[C-investigation]: investigate.py
[H-log]: git_history.txt
[H-orders]: history_orders.patch
[H-finance]: history_finance.patch
[H-metrics]: history_metrics.patch
[H-rec]: history_rec.patch
[H-jobs]: history_jobs.patch
[R]: redash_sql.json
[R-inventory]: redash_inventory.json
[Q-inventory]: warehouse_inventory.json
[Q-coverage]: time_coverage.json
[Q-finance]: initial_finance.json
[Q-view-log]: view_creation_logs.json
[Q-manual]: manual_log.json
[Q-status]: order_status_month.json
[Q-payments]: payments_month.json
[Q-overrides]: overrides.json
[Q-corrections]: corrections.json
[Q-chargebacks]: chargebacks.json
[Q-grains]: order_grains.json
[Q-duplicates]: duplicate_ref_summary.json
[Q-recompute]: monthly_statement_recompute.json
[Q-fee-warnings]: statement_warnings.json
[Q-fee-boundary]: fee_boundary.json
[Q-fee-order]: november_fee_diagnostic.json
[Q-fee-payment]: nov_fee_payment_level.json
[Q-refunds]: refunds_month.json
[Q-gateway]: gateway_refund_details.json
[Q-refund-overlap]: refund_overlap.json
[Q-cap]: busy_day_cap_loss.json
[Q-cap-log]: report_scan_caps.json
[Q-dst]: dst_missing_hour.json
[Q-report-versions]: report_versions.json
[Q-report-months]: report_monthly_snapshots.json
[Q-current-report]: current_filter_monthly.json
[Q-widget]: revenue_widget_20191231.json
[Q-empty-day]: nov_empty_day.json
[Q-empty-job]: nov_empty_job.json
[Q-multiitem]: line_multiitem_examples.json
[Q-best-example]: best_sellers_20191231.json
[Q-brand-example]: brand_revenue_20191231.json
[Q-category-example]: category_revenue_20191231.json
[Q-daily-example]: daily_kpis_20191231.json
[Q-customers]: customer_counts.json
[Q-registered]: registered_conversion.json
[Q-pre-enrollment]: registered_pre_enrollment.json
[Q-account-history]: account_history.json
[Q-map-consistency]: account_map_consistency.json
[Q-email-domains]: email_domains.json
[Q-actives]: actives_compare.json
[Q-board]: board_actives_20191231.json
[Q-kpi-latest]: kpi_latest.json
[Q-funnel-latest]: funnel_latest.json
[Q-qa]: qa_account_evidence.json
[Q-taxonomy]: actual_taxonomy_changes.json
[Q-future]: mutable_future_times.json
[Q-blank]: blank_brand_summary.json
[Q-current-blank]: current_bad_brand.json
[Q-price-history]: price_feed_history.json
[Q-jobs]: job_summary.json
[Q-failures]: job_failures.json
[Q-job-config]: job_config_history.json
[Q-digest]: digest_history.json
[Q-reconcile-runtime]: reconcile_performance.json
[Q-risk-release]: risk_released.json
[Q-rec-mix]: rec_mix.json
[Q-rec-latest]: rec_latest_mix.json
[Q-rec-gap]: rec_logging_gap_exact.json
[Q-rec-gap-daily]: random_log_gap.json
[Q-rec-duplicates]: rec_log_duplicates.json
[Q-rec-app-count]: legacy_decision_counts.json
[Q-random-population]: random_distinct_counts.json
[Q-random-length]: random_list_lengths.json
[Q-models]: models.json
[Q-latest-model]: trained_data_recent.json
[Q-scores]: score_coverage.json
[Q-score-reads]: score_read_lineage.json
[Q-v4-scale]: v4_scaling.json
[Q-v4-ranks]: v4_ranking_changes.json
[Q-trending]: trending_latest.json
[Q-forecast]: forecast_snapshot.json
[Q-pricing-reads]: pricing_reads.json
[Q-db-samples]: db_samples.json
[Q-app-types]: app_event_types.json
[Q-actors]: db_actor_types.json
