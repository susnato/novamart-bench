# NovaMart tribal knowledge

## 1. Summary

- **The finance answer depends on publication vintage.** For October 2019, originally published net revenue is **1,194,652.79**; the fee-corrected value is **1,194,652.93**; the approved final-view value is **1,191,085.36** after **3,567.57** of chargebacks. Use `novamart_analytics.statements_final` for current finance reporting and `novamart.statements` to reproduce the older deck. [Q01][Q02][Q03][Q04][Q06][^policy]
- **Cash, order sales, and dashboard revenue are separate measures.** Gateway refunds create negative payment rows without changing order status. Daily reports exclude selected products, brands, and users; product dashboards have different filters and generally no status filter. Summing a dashboard is not a finance reconciliation. [Q21][Q34][Q37][^orders][^reports][^dashboards]
- **Orders stopped being single-item records on November 22.** An order can contain several `order_lines` and payment transactions. Item attribution must use lines with a legacy-order fallback; parent counts, item counts, and payment counts are not interchangeable. [Q26][Q75]; commits `5d1300d`, `92596dc`, `33054cd`.
- **There is no universal active-customer definition.** The nightly rollup counts status-1 buyers over 30 days; the exec dashboard counts daily ordering users without a status filter; the board query additionally removes test/internal/example-like identities and accepts status 6. Registration UUIDs are a different namespace from numeric shopper IDs. [Q15][Q24][Q51][Q52][Q53][^customers][^accounts]
- **The live recommendation path in this checkout is v2, not v4.** The flag selects affinity-v2 scores, with trending fallback. Of **275,220 logged v2-period decisions**, **207,959 (75.56%)** were fallback, **52,695 (19.15%)** model-sourced, and **14,566 (5.29%)** random-arm. These are exposure shares, not conversion or lift. [Q29][Q64][^similar]
- **v4 trains, but does not implement the advertised learned ranking.** It fits five exposure/user features, then multiplies every eligible v2 pair score by the same scalar. All **948** candidate ranks matched v2 in the inspected snapshot. There is no demonstrated incremental recommendation benefit in this evidence. [Q14][Q44][Q63][Q77][^model]
- **Several operational labels overstate what runs.** Pricing suggestions remain shadow-only; reorder hints are an inverse-velocity heuristic; `digest_sent` records a recipient count but the job contains no email transport. A random-arm logging regression lost **1,372** matching exposure records, and affinity v2 crashed on December 3–5. [Q16][Q42][Q48][Q49][Q76][^pricing][^reorder][^digest]
- **Migration details matter.** Cron is retired, the actual warehouse analytics dataset is `novamart_analytics`, and the pinned backfill code still targets `analytics`. Airflow wrappers omit an explicit timezone, have no cross-DAG dependency checks, and preserve only the noon intraday run. Historical examples below use an explicit observation anchor because the query clock is in 2026 while business facts end in 2019. [Q32][Q67][E-schema][E-dags][^warehouse][^time]

**Evidence convention:** code footnotes identify files and line ranges at pinned commit `5ae11821806a396aac10115e03863b8c68c1bfcc`; other commit hashes identify inspected historical changes. `Q01`–`Q81` link to saved read-only SQL and returned rows, indexed in Appendix G. Dashboard citations identify actual Redash query IDs and widget mappings. Scope and start time are recorded in [run metadata](run_metadata.json). [E-git][E-redash]

## 2. Why this project

The business needs a repeatable answer to “what was revenue, and why?” because later fee corrections, chargebacks, status changes, cleanup filters, and snapshot selection can each produce a different defensible number. The repository’s restatement policy explicitly distinguishes the old deck from current finance reporting. [^policy][Q01][Q03][Q22][Q37]

This document provides three practical contracts: **finance lineage and publication history**, **the definition behind every migrated dashboard**, and **batch/ML dependencies sufficient to reason about a change or failure**. The inspected estate contains nine Redash dashboards and sixteen Airflow wrappers; the examples expose disagreements that these contracts must explain. [E-redash][E-dags][Q41][Q54][Q55]

## 3. Business understanding

- NovaMart is a marketplace backend with product browsing, carts, payment-gateway order callbacks, cancellation/refund operations, and a similar-products widget. Users and products are bootstrapped on first sight. `users.created_at` therefore means first persisted appearance, not necessarily a deliberate signup. [^app][^catalog][^orders][^accounts]
- The stored sales price comes from the order callback body. Catalog list prices come from vendor feeds, and historical feed prices are recorded separately. Product cost, stock, vendor, and user-profile attributes are deterministically synthesized by onboarding code; their presence alone does not establish measured inventory, demographic truth, or cost accounting. [^catalog][^orders][^onboarding][Q31][Q62]
- Finance’s `net` is the statement gross less collected processor fees, then less booked chargebacks in the final view. It does not deduct product costs, marketing spend, or unified-refund totals. The schema has no currency field or FX conversion pipeline in these finance tables, so preserve the stored monetary unit when quoting values. [^finance][Q19][E-schema]
- Commercial-report visibility is policy-driven: `lucente`, `jetem`, SKUs `1004856`/`1002544`, and QA shopper `424242` are excluded by selected consumers. These filters do not apply universally to money or customer counts. [^constants][^reports][^dashboards][Q39][Q49]

## 4. Metrics

| Question / metric | Authoritative surface for that purpose | Definition / principal qualification | Evidence |
|---|---|---|---|
| Current approved monthly finance gross/net | `novamart_analytics.statements_final`; Redash query 5 | Published snapshot → month overrides → chargebacks assigned to original order month | [Q03][Q19][^policy] |
| What the old deck published | `novamart.statements` | Append-only statement run, selected by month and publication timestamp | [Q01][^finance][^policy] |
| Collected money / fees | `novamart.payments` | Payment movements at transaction time; retain negative refund rows | [Q21][Q34][^orders] |
| Daily operational revenue / “orders” | Latest `report_rows` batch; today’s latest `report_rows_intraday` batch | Local-day item sales after report filters; “orders” is the sum of item units; completion is not encoded in the tables | [Q54][^reports][^dashboards] |
| Exec seven-day revenue widget | Redash query 2 | Six closed Eastern calendar days plus today’s latest partial snapshot | [Q55][^dashboards]; commit `3eced24` |
| Dashboard best sellers | Redash query 9 | Rolling 7×24 hours, item grain, QA/brand exclusions, no status filter, top 20 by revenue | [Q39][^dashboards] |
| Nightly top sellers | `novamart.top_products` | Yesterday’s status-1 parent orders; top 50 by units | [^top][Q16] |
| Brand/category revenue | Redash queries 8/6 | Rolling 30 days; line attribution; current product metadata; date-effective category display mapping | [Q40][Q58][^dashboards] |
| Nightly active customers | `novamart_analytics.kpi_daily` | Distinct status-1 shoppers in trailing 30 days, without QA/email/brand cleanup | [Q15][^customers] |
| Exec active/contactable customers | Redash query 7 | Distinct ordering shoppers per Eastern day; contactable subset joins trusted view | [Q53][^dashboards][Q19] |
| Board actives | Redash query 3 | Trailing 30 days, exclude statuses 0/2/3 and table/email tests, no brand filter | [Q51][^dashboards] |
| Registered buyers/revenue | Redash query 4 | Accounts → current shared email → numeric user → all-history status-1 orders; no rate denominator | [Q24][Q61][^dashboards] |
| “Refunds” dashboard | `novamart_analytics.refunds_unified`; query 1 | Status-based cancellations/refunds plus negative payment movements; event/update month | [Q08][Q19][Q33] |
| Funnel sessions/activity | `novamart_analytics.daily_funnel` | Cart/order activity in trailing 24 hours; split a user’s activity after >120 minutes | [^funnel][Q16]; commit `f915c1b` |

The metric name alone is insufficient: retain **grain, timestamp basis, status policy, exclusions, publication vintage, and snapshot/run version**. The documented differences above and the verified bridges in Appendices A/B supply those dimensions. [Q21][Q22][Q37][Q41][Q54][^policy]

## 5. System

```text
Vendor feed / product views / cart events
    ├─ users, products, cart_items
    └─ price_history
Gateway order callbacks
    ├─ orders (parent total + mutable status)
    ├─ order_lines (newer item/payment-ref grain)
    └─ payments (charge/refund movements and collected fees)

orders + lines + product/user filters → daily/intraday report snapshots → exec KPIs/widget
orders + payment fees → published statements → overrides → corrected → chargebacks → final
cart_items + orders + products → affinity v2 → similar widget → rec_decision_log
                                               └─ trending fallback
random-arm decisions + orders/users/products → v4 training → model_scores (flag-gated)

Serving Postgres tables → one-shot warehouse backfill → BigQuery copies
Postgres statement/app/job logs → novamart_logs
Redash (Postgres data source) → migrated SQL dashboards
```

The edges above come from the writers/readers, not merely table names. Monthly finance does **not** read daily-report rows; top sellers, trending, digest, risk, pricing, and reorder jobs still use parent-order data rather than the item CTE. [^catalog][^carts][^orders][^finance][^reports][^similar][^model][^top][^trending][^digest][^risk][^pricing][^reorder][^warehouse][E-redash-source]

The app is FastAPI with an async Postgres pool; jobs open synchronous **autocommit** connections. Application/DB/job log files are exported to warehouse log tables. Airflow schedules are wrappers around modules, not data-quality or publication gates. [^app][^db][^logging][E-schema][E-dags]

## 6. Data

- The inspected warehouse contains **12 app tables**, **20 analytics tables plus four views**, and **three log tables plus one normalized log view**. Map serving `public.*` to warehouse `novamart.*`, and serving `analytics.*` to actual warehouse `novamart_analytics.*`. The pinned data-access document and backfill mapper still call the latter `analytics`. [E-schema][^warehouse]
- Key grains are numeric shoppers, UUID accounts, parent orders, line payment references, payment movement IDs, snapshot product rows, directed affinity pairs, and recommendation exposures. A direct order↔payment join can multiply order totals; aggregate payment fees per order before comparing parent gross. [E-schema][Q25][Q26][Q36][Q75][^orders]
- Current status and product metadata are mutable; reports/statements/KPIs preserve computations made at earlier run times. Historical snapshots are not automatically regenerated after every status, taxonomy, brand, or fee change. [Q01][Q15][Q22][Q37][Q38][^finance][^reports][^catalog]
- In this snapshot, **38,910 users have `example.com` emails and 40 have `gmail.example` emails**; the trusted contactable view and cleaned board actives both return zero. A digest count of 40 is consequently not evidence of 40 trusted, contactable customers. [Q09][Q45][Q49][Q51][Q19]
- Business data/logs end on December 31, 2019; `CURRENT_TIMESTAMP()` returns an October 2026 clock. The comparisons below use **2020-01-01T00:00:00Z**, whose Eastern calendar day is December 31. They are warehouse reproductions of definitions, not refreshed or cached Redash results. [Q32][Q67][Q39][Q51][Q55][E-redash]

## 7. Experimentation

- User assignment is stable: SHA-256 of numeric UID, first eight hex characters modulo 20, with bucket zero assigned to random. The list is a deterministic shuffle seeded by `uid:session:base_pid`. “5%” describes assignment probability, not a promise that exactly 5% of requests appear in the arm. [^similar][Q64]
- Exploration is random **within the first 500 eligible product IDs**, not across the full 81,018-product catalog. No base-product, stock, category, brand, or prior-purchase exclusion is applied there beyond the two excluded SKUs. [^similar][Q72]
- Exposure logging lost random-arm records between the December 17 early-return refactor and December 19 repair. Compare app `rec_served` events with decision rows before training or assessing the arm; do not infer fewer random users from the missing decision rows. [Q41][Q76]; commits `30e8907`, `a00f24c`.
- v4’s outcome is **any later status-1 order by the exposed user**, without a product match or fixed attribution horizon. Its scores are rescaled v2 scores, not per-candidate predicted probabilities; no served v4 decisions or app reads of `model_scores` were found in the queried history. [Q29][Q42][Q77][^model]
- **Judgment:** recommendation serving exists, but most logged traffic is fallback, and the inspected evidence does not establish incremental conversion lift. Fraud, pricing, and reorder output similarly lack a validated effectiveness result here. Their implemented rules and operational outputs are documented in Appendix C. [Q64][Q77][Q47][Q48][Q42][^risk][^pricing][^reorder]
- **Proposed evaluation before extension:** use mature, bounded outcomes tied to served items; separate intended/effective version and fallback; account for the logging gap and user-level assignment; compare candidate/ranking changes and include a temporal holdout. These are recommendations motivated by the actual attribution, candidate-pool, and instrumentation defects—not claims that such an experiment has already run. [^similar][^model][Q41][Q63][Q77]

## 8. Glossary

| Term | Meaning in this estate | Evidence |
|---|---|---|
| Published statement | What the monthly job emitted at a particular publication time | [Q01][^finance] |
| Corrected statement | Published values with month-level replacement overrides applied | [Q02][Q04][Q19] |
| Final statement | Corrected gross/net minus booked chargebacks assigned to original order month | [Q03][Q06][Q19] |
| Gross / net | Statement order-price sum / that sum less collected processor fees, then final adjustments | [^finance][Q19] |
| Payment movement | A positive charge or negative gateway-refund row in `payments` | [Q21][Q34][^orders] |
| Parent order | Mutable total, first product, first creation time, status; may cover several lines | [^orders][Q75] |
| Item unit | One line, or one legacy order with no lines; not a quantity field | [^reports][Q26] |
| Status 0 / 1 / 2 / 3 / 6 | Pending / paid / cancelled / refunded / fraud-held | [^orders][^constants][^risk] |
| Historical status 4 | Old cancelled-status constant before alignment to 2 | commit `8f19718`; [^constants] |
| Status 5 | Value excluded by duplicate-ref reconciliation; no supported business meaning was established here | [^reconcile][Q07] |
| Active customer | Consumer-specific ordering/buyer count, not a universal definition | [^customers][^dashboards] |
| Contactable user | Opted-in user passing email syntax and example-domain exclusions | [Q19][Q09] |
| Registered account | UUID account linked to a legacy numeric UID, distinct from first-seen user | [^accounts][Q25] |
| Session | Raw storefront session string for affinity/order merging, or inferred inactivity session for funnel | [^orders][^affinity][^funnel] |
| Affinity sentinel −1 | Too few pair observations; not dislike or a negative preference | [^affinity][Q30] |
| Intended / effective version | Flag-selected path / actually logged serving outcome; old v1 fallback semantics differ | [^similar][Q29] |
| `rec_source` / `fallback_reason` | Model/affinity/fallback/random origin / explanation, sometimes `cache` rather than a failure | [Q29][^similar] |
| Shadow pricing | Suggested prices persisted but not read by serving | [^pricing][Q42] |
| Reorder hint | Advisory hand-fit inverse-velocity integer, not a learned purchasing forecast | [^reorder][Q48] |
| Warehouse backfill | Manual full table-copy mechanism, distinct from recurring batch production | [^warehouse][E-dags] |

---

## Appendix A. Finance, end to end

### A1. Order and payment lifecycle

1. `/orders` takes the callback’s `ts`, `uid`, `pid`, `price`, `ref`, and `session`. Current code locks the session and payment reference, looks for the reference across parent and line records, repairs a missing payment if necessary, and reactivates a replayed parent only when its status is 0. Replayed cancelled/refunded parents are not unconditionally restored by the current code. [^orders]
2. A new reference can append to the same user/session’s recent order when the most recent qualifying line is within 15 minutes and the parent is not cancelled/refunded. The parent price increases; a line and a separately fee-bearing payment are inserted. `orders.product_id` remains the first product and `orders.created_at` remains the original parent timestamp. Appending also sets status 1, so a new-reference append is a different status transition from a replay. [^orders]; commit `5d1300d`.
3. Every new transaction currently collects `round(price × 0.029 + 0.30, 2)`; payment net is `round(price − fee, 2)`. The flat fee entered callback code in commit `12e1c68`, November 20 at 14:25 UTC. [^orders][^constants]; commit `12e1c68`.
4. Cancellation changes the parent to 2 and rejects a previously refunded parent. The legacy refund endpoint changes a paid parent to 3; it does not insert a negative payment. The gateway-refund endpoint inserts `gross = net = −amount`, `fee = 0`, and does not change the parent status. [^orders]

**Identity and historical duplication:** commit `b676969` added reference-based idempotency on October 15. Current data retains **130 duplicated parent payment references covering 285 orders**; their latest order timestamp precedes that fix. Reconciliation warns about them rather than removing orders or reversing money. Historical finance snapshots therefore cannot be reproduced by applying a new deduplication rule without changing the metric. [Q50][Q78][^reconcile]; commit `b676969`.

**Grain check:** `order_lines` has **2,284 rows for 2,059 parents**, with **2,284 distinct references**. All 2,059 parent totals equal their summed line prices. The difference of 225 lines is also consistent with 225 `order_appended` app events. November has **3,582 paid parent orders but 3,614 payment transactions**; a raw join would repeat some parent totals. [Q26][Q75][Q17][Q36]

### A2. What the monthly job actually publishes

The job takes the **previous Eastern calendar month** using UTC-converted local midnights. It sums `orders.price` and counts **parent orders with status 1 at run time**. It independently sums `payments.fee` joined to those parents using the **order’s month**, not the payment’s month, then appends gross/fee/net/count to `statements`. It has no brand, SKU, QA, contactability, or currency filter. [^finance][^time]

This is not a general cash ledger: negative payment gross/net are not subtracted from the job’s order gross. A refund can occur in December against an October order and still leave that parent status 1. Fee expectations are diagnostic warnings; the current published fee is the collected fee sum. [Q34][Q36][^finance][^orders]

| Month | Published gross | Published fee | Published net | Final gross | Final fee | Final net | Published parents |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2019-09 | 2,702.00 | 78.36 | 2,623.64 | 2,702.00 | 78.36 | 2,623.64 | 12 |
| 2019-10 | 1,230,332.43 | 35,679.64 | 1,194,652.79 | 1,226,764.86 | 35,679.50 | 1,191,085.36 | 3,765 |
| 2019-11 | 1,101,397.01 | 32,110.92 | 1,069,286.09 | 1,101,397.01 | 32,110.92 | 1,069,286.09 | 3,582 |

All entries above are warehouse query results, not estimates. There is **no December statement row** in the inspected published/corrected/final surfaces. Missing finance publication must not be reported as zero revenue. [Q01][Q02][Q03]

### A3. October reconciliation: the answer a finance person would give

```text
Original published net                                      1,194,652.79
Replace aggregate-rate fee with collected per-order fees            +0.14
Corrected net                                              1,194,652.93
Booked chargebacks: order 55 (734.81), 46 (940.82), 49 (1,891.94)  −3,567.57
Final-view net                                             1,191,085.36
```

The original fee was computed from aggregate gross. Commit `a92c96d` switched the writer to collected fees on November 2; the October override replaces fee/net while preserving the snapshot’s publication timestamp and count. The final view added in commit `cd559d3` subtracts chargebacks from **original-order month**, retains fees/count, and does not use the chargeback’s report month as revenue month. [Q01][Q04][Q06][Q19]; commits `a92c96d`, `cd559d3`; [^policy]

There is a third, different October number: **recomputing currently status-1 orders** yields gross **1,206,337.32**, count **3,695**, collected fees **34,983.61**, and order-based net **1,171,353.71**. The **70** now-cancelled/refunded October parents total **23,995.11**, explaining the gross difference from the published snapshot. This recomputation is not the approved final-view number; do not silently replace that view with it or subtract the same refunds/chargebacks again. [Q22][Q36][Q03][^policy]

The October-cohort payment-net sum in that same status-1 recomputation is **1,169,510.12**, because its retained parents include **1,843.59** of December gateway-refund movements. Payment time and order-cohort time answer different questions. [Q34][Q36]

### A4. Fee changes, rounding, and November’s audit record

- Before the flat-fee deployment, callback fee was rounded per transaction at 2.9%. The original statement rounded 2.9% of aggregate gross. October differed by **0.14**; September still has a **0.01** published-versus-collected difference and no corresponding override in this snapshot. [Q01][Q04][Q21][Q35]; commits `a92c96d`, `12e1c68`.
- November’s statement already published **32,110.92** of collected fees. Its December 1 warning compared that with a percentage-only expectation **31,940.51**, delta **−170.41**. Commit `4a58d17` revised the expectation to include flat fees with a midnight-Eastern November 20 threshold; it did not replace the already-collected fee. [Q35][Q01][^finance]; commit `4a58d17`.
- The `statement_corrections` audit row has **delta 0.00** and reason “November 2019 processor fee change audit correction.” That table is explanatory: the corrected/final view lineage reads `statement_overrides`, not `statement_corrections`. Do not subtract a hypothetical November correction because the commit title says “correction.” [Q05][Q19]
- The expectation still has imperfect granularity/timing: current November parent-order expectation is about **32,120.54**, versus **32,130.14** at transaction grain under the same midnight threshold, while actual collected fees remain **32,110.92**. The first observed flat-fee transaction is November 20 **14:27:41 UTC**, after the source change’s 14:25 timestamp, not midnight. Diagnose with actual transaction timestamps and rounding; a parent formula is not the ledger. [Q69][Q70][Q71]; commit `12e1c68`.

### A5. Refunds and chargebacks are not interchangeable

`refunds_unified` is a **UNION ALL** of (a) current order status 2/3, amount `orders.price`, time `orders.updated_at`; and (b) each payment with negative gross or net, positive absolute amount, time `payments.created_at`. It neither deduplicates mechanisms nor includes chargebacks by definition. A later update can move a status-derived row’s reporting month, and a parent with both a status refund and a gateway movement can be counted through both branches. [Q19][Q08]

| Dashboard event month, Eastern | Status cancellations | Status refunds | Gateway refund movements | Total rows | Total amount |
|---|---:|---:|---:|---:|---:|
| 2019-11 | 24 / 6,511.32 | 8 / 3,180.45 | 0 / 0.00 | 32 | 9,691.77 |
| 2019-12 | 30 / 6,738.32 | 20 / 10,267.02 | 9 / 1,843.59 | 59 | 18,848.93 |

These totals reproduce Redash query 1’s event-month definition; they are not net-revenue adjustments to apply on top of `statements_final`. [Q33][^dashboards][Q19]

The nine gateway rows concern only three parents, all still status 1. Each has three full-price negative movements: order 3762 totals **76.44** against price **25.48**; 3763 totals **764.13** against **254.71**; 3776 totals **1,003.02** against **334.34**. The handler has no gateway-event ID or idempotency check. This establishes repeated stored movements, not whether they were genuine repeated refunds or replayed external webhooks; that distinction cannot be resolved from the available fields. [Q34][^orders][E-schema]

### A6. December: state exactly which provisional number you mean

At the inspected data cutoff, current December paid parents total **552,328.93**, with fees **16,600.26**, order-based net **535,728.67**, and **1,756** parents. There are also **12 held parents worth 40,213.29**. All-status December order/item gross is **592,542.22**; transaction-time payment gross is **590,698.63**, fee **17,772.15**, and net **572,926.48**, including the **1,843.59** of December gateway movements against older orders. None of these is a published December final statement. [Q22][Q36][Q21][Q80][Q03]

The stored closed-day December daily-report sum is **535,561.72** through December 30. It is filtered, computed at earlier run times, and lacks a December 31 closed-day run. It cannot replace the missing monthly statement. [Q38][Q16][^reports]

### A7. Read-only recipe for “what was revenue in month M?”

Start with the stored publication layers; the query below was executed read-only and returned the reconciled October values. Distinguish `published_net`, `corrected_net`, and `final_net` in the answer, rather than using one ambiguous `revenue` label. For multiple published runs, add the requested publication timestamp; the inspected views themselves do not select the latest run. [Q81][Q01][Q02][Q03][Q19][^finance]

```sql
SELECT s.month, s.created_at AS published_at,
       s.gross AS published_gross, s.fee AS published_fee,
       s.net AS published_net,
       c.gross AS corrected_gross, c.fee AS corrected_fee,
       c.net AS corrected_net,
       f.gross AS final_gross, f.fee AS final_fee, f.net AS final_net
FROM `novamart-warehouse.novamart.statements` s
LEFT JOIN `novamart-warehouse.novamart_analytics.statements_corrected` c
  ON c.month = s.month AND c.created_at = s.created_at
LEFT JOIN `novamart-warehouse.novamart_analytics.statements_final` f
  ON f.month = s.month AND f.created_at = s.created_at
WHERE s.month = '2019-10';
```

Then inspect that month’s override, its chargebacks joined to original orders, and historical `statement_generated`/`statement_fee_mismatch` logs. A raw current-order reconstruction is a diagnostic alongside the snapshot, with explicit status/time assumptions. [Q04][Q06][Q16][Q35][Q36]

### A8. Financial/report definition history

| Change | Consequence | Evidence |
|---|---|---|
| Initial import, September 15 | Parent-order reporting, rate-only fee, status exclusions only `[0]`, 500-row report fetch | commit `2da4141`; [Q12] |
| October 8: report SKU exclusions | Hide `1004856` and `1002544` from daily reports | commit `83fb3ed`; [^constants] |
| October 15: callback idempotency | New repeated refs reuse earlier orders; old duplicates remain | commit `b676969`; [Q50][Q78] |
| October 21: blank-brand repair | Future metadata can repair blank brand/title; audit snapshot remains separate | commit `ea0e97b`; [Q27][^catalog] |
| October 25: Lucente report suppression | Report constants exclude Lucente; this was not yet a universal dashboard filter | commit `ba1fbfa`; [^reports] |
| October 28: cancelled status alignment | Old constant 4 becomes 2; cancellation endpoint added | commit `8f19718`; [^constants][^orders] |
| November 2: collected-fee publication | October override; future statements use summed collected fees | commit `a92c96d`; [Q04][Q19] |
| November 5: DST boundary fix | End at next local midnight, not start+24 UTC hours | commit `102c9b4`; [Q59] |
| November 15/18: refunds/report statuses | Refund status 3 added; report exclusions become `[0,2,3]` | commits `d87cb3d`, `11c0a42` |
| November 19: full scan | Replace `fetchmany(500)` with `fetchall()`; stale constant remains unused | commit `1233af8`; [^reports][Q79] |
| November 20/22 | Add flat transaction fee; merge session callbacks into line-bearing parents | commits `12e1c68`, `5d1300d`; [Q26][Q36] |
| November 27 | Test-user table/report exclusion and dashboard QA exclusion | commit `b59f077`; [Q20][^reports] |
| December 2/5 | Flat-fee expectation fixed; best/brand/daily sales change to item grain | commits `4a58d17`, `92596dc` |
| December 8/9 | Intraday snapshots; final statement chargeback layer | commits `a2e0013`, `cd559d3`; [Q19] |
| December 15 | Add Jetem to report denylist; dashboards add both Lucente/Jetem filters | commit `1169e40` |
| December 23/24 | Unified refunds view; fix widget snapshot overlap and seven-day boundary | commits `a3bffec`, `3eced24`; [Q33][Q55][Q56] |
| December 29/30 | Fraud threshold raised and manual releases; documented restatement policy | commits `1cb8721`, `a576d0d`; [Q20][^policy] |

## Appendix B. Product and customer analytics

### B1. Every Redash dashboard, including what its labels hide

The widget-to-query mappings below were read from Redash dashboard detail responses. All nine query definitions use data source **1, `novamart`, type `pg`**; their schedules and `latest_query_data_id` were null at inspection. No cached dashboard result was available to certify a displayed value, so the historical examples were independently queried in BigQuery without refreshing Redash. [E-redash][E-redash-source]

| Dashboard ID / slug | Query ID | Returned number and exact principal semantics | When not to trust the label |
|---|---:|---|---|
| 1 `refunds` | 1 | Eastern month of unified `at`; row count and amount sum | Includes cancellations and repeated/mixed refund mechanisms; not unique refunded orders |
| 2 `revenue_widget` | 2 | Sum latest closed-day snapshots for today−6…yesterday, plus latest intraday today | Filtered gross sales, not finance net; current day partial; missing/partial batches |
| 3 `actives_board` | 3 | Distinct 30-day ordering users, statuses not 0/2/3, table/email cleanup | Includes held status 6; placeholder email cleanup can remove the entire observed population |
| 4 `registered_conversion` | 4 | All-history paid buyers and parent revenue after account/email/user mapping | No conversion rate or signup cohort; includes pre-enrollment orders; email mutable |
| 5 `statements_final` | 5 | All rows in final statements ordered by month | Approved restatement vintage, not old-deck or transaction-time cash |
| 6 `category_revenue` | 6 | Rolling 30-day item count/revenue by date-effective display group | Current product category; mapping-date issues; no status or explicit SKU filter |
| 7 `best_sellers` | 9 | Rolling seven-day item count/revenue, top 20 sorted by revenue | “Best” is revenue, not units; held/refunded/cancelled items can remain |
| 8 `brand_revenue` | 8 | Rolling 30-day item count/revenue by current brand | No status/SKU filter; blank brand not relabeled; UUID string exclusion cannot match numeric UID |
| 9 `daily_kpis` | 7 | Fourteen-day local series of report-unit “orders”, revenue, ordering users, contactable users | Revenue/item and customer/parent populations differ; day absent if report absent |

Evidence for every row: the nine live query definitions and corresponding dashboard detail JSON in [E-redash], saved SQL files in Appendix G, the trusted-view lineage [Q19], and the numeric reproductions [Q24][Q33][Q39][Q40][Q51][Q53][Q54][Q55][Q58].

### B2. Item attribution, best sellers, and brand reporting

The shared dashboard item rule is:

```sql
WITH item_orders AS (
  SELECT o.user_id, ol.product_id, ol.price, ol.created_at
  FROM novamart.orders o
  JOIN novamart.order_lines ol ON ol.order_id = o.id
  UNION ALL
  SELECT o.user_id, o.product_id, o.price, o.created_at
  FROM novamart.orders o
  WHERE NOT EXISTS (
    SELECT 1 FROM novamart.order_lines ol WHERE ol.order_id = o.id
  )
)
SELECT io.product_id, COUNT(*) AS units, SUM(io.price) AS revenue
FROM item_orders io
JOIN novamart.products p ON p.id = io.product_id
WHERE io.created_at >= TIMESTAMP_SUB(
  TIMESTAMP('2020-01-01T00:00:00Z'), INTERVAL 7 DAY)
  AND io.user_id <> 424242
  AND p.brand NOT IN ('lucente', 'jetem')
GROUP BY io.product_id
ORDER BY revenue DESC
LIMIT 20;
```

This preserves the actual best-sellers definition, including the missing status filter. The verified version adds a diagnostic count of non-status-1 items. At the historical anchor, product **1005116** leads with **6 units / 5,889.81**; product **1005284** ranks third with **2 units / 5,096.14**, both non-status-1. SKU **1002544**, excluded from daily reports, still appears with **10 units / 4,498.52**. [Q39][^dashboards][^constants]

The nightly `top_sellers` job is different: status-1 **parent** orders in yesterday’s Eastern day, top 50 by units with product-ID tie-break, no QA/brand/SKU cleanup, and append-only output. It can misattribute additional items to the first parent product and should not be used to reproduce query 9. [^top][^orders][^dashboards]

At the same anchor, rolling-30-day brand revenue begins with **Apple 236,606.73** and **Samsung 128,113.51**, including **11,655.30** and **8,090.51** of non-status-1 item revenue respectively. Blank brand is **17,585.39**; `internal` brand is **7,624.89**. The brand query excludes QA numeric ID and its UUID string, but does not exclude those brands or the two report SKUs. [Q40][^dashboards]

`/reports/brands` is yet another definition in source: selected calendar month, paid **parent** orders, SKU/brand exclusions, blank brands relabeled `unbranded`, no test-user-table filter. It was not changed by `92596dc`’s item-report fix, and **its router is not mounted in this pinned `app.py`**. Treat it as a defined code path, not verified live HTTP availability. [^brand-api][^app]; commit `92596dc`.

### B3. Category taxonomy is temporal, but product metadata is not

Query 6 unions `category_names` with `category_name_history`, selects the mapping with maximum `valid_from <= item_timestamp::date`, and prefers history on equal dates. Unmapped codes become `other`. It uses **current** `products.category`; there is no product-category history join. The original Postgres `::date` also depends on the session timezone rather than explicitly selecting Eastern time. [^dashboards][E-schema]; commit `33054cd`.

The category dashboard initially used parent orders in commit `2814b3d` (November 30). It adopted item attribution **on December 12 in `33054cd`**, not December 5: the latter changed best sellers, brand revenue, and daily reports only. The existing dashboard notes overgeneralize that date. [E-history]; commits `2814b3d`, `92596dc`, `33054cd`; [^dashboard-notes]

The six renamed history codes map `construction.tools.light` to `lighting` and five `electronics.audio.*` codes to `entertainment`, but their actual stored `valid_from` is **2026-08-13**, not December 2019. The historical SQL used `CURRENT_DATE`, even though the statement-log timestamp says December 12, 2019. Consequently the historical-anchor reproduction reports electronics **437,887.95**, other **93,558.92**, appliances **30,208.94**, construction **3,713.01**, apparel **3,663.34**, kids **617.89**, and no entertainment/lighting group. Preserve this observed inconsistency; do not silently rewrite effective dates to match the commit narrative. [Q13][Q20][Q46][Q58]

### B4. Blank brands and price history

Before October 21’s repair, bootstrap inserts used `ON CONFLICT DO NOTHING`; known-ID caches skipped reinsertion. A product first seen without brand metadata could remain blank despite later metadata-bearing events. The investigation captured **5,972 products**, **204 ordered units**, and **38,499.83** revenue in `blank_brand_products`; it is an audit-style snapshot, not the current blank-brand population. [Q20][Q27][^catalog]; commit `ea0e97b`.

Current products contain **17,442 blank brands** and **33,514 blank categories** out of **81,018** products. Brand repair updates blank brand/title, while vendor-feed upsert can update nonblank incoming category/brand/vendor and current prices. Historical report grouping therefore uses current metadata unless a snapshot already fixed it. [Q72][^catalog][^reports]

The price-feed bug fixed in commit `d213f6e` changed existing-product feed handling from insert-only to upsert. Commit `795d273` added price history; the first observed history row is November 18, not product creation or the commit date. There are **1,400 feed-history rows for 241 products**; **1,133** history rows differ from current catalog price. Order prices remain stored callback prices, so do not reconstruct historical revenue by multiplying units by current list price. [Q31][Q62][^catalog][^orders]; commits `d213f6e`, `795d273`.

### B5. Customer identity and signup populations

`ensure_entities` creates a numeric user during catalog/cart/order activity; it sets a placeholder email and deterministic profile. The accounts endpoint separately creates a UUID account and `account_map(uid, account_id, linked_at)` and bootstraps a missing numeric user. It reads the current user email into the new account; later user-email changes update only `users.email`. [^catalog][^accounts][^onboarding][^users]

| Local month | Newly first-seen user rows |
|---|---:|
| 2019-09 | 74 |
| 2019-10 | 15,045 |
| 2019-11 | 11,302 |
| 2019-12 | 12,529 |

These sum to **38,950 persisted users**, not verified human signups. The account beta has **30 accounts and 30 mapped numeric users**, with no email mismatch at inspection. QA UID **424242** maps to UUID **cc27b436-d6f9-4e84-adaf-e716025dd369**. [Q23][Q25][Q73][Q74]

The original registered-conversion query cast UUIDs and numeric IDs to text and compared them, producing an invalid identity join. Commit `b975479` replaced it with distinct numeric users found by exact shared email. The actual dashboard now returns **30 registered buyers**, **74 paid orders**, and **18,155.71 revenue** across all history; **63 orders / 14,911.96 revenue** precede account enrollment. It is neither post-signup conversion nor a conversion percentage. [Q24][Q61][^dashboards]; commits `d6e34c6`, `b975479`.

Use the current-email join to reproduce query 4 exactly; for a durable identity model, the explicit `account_map` is the better available relation to investigate because emails can change and are not declared unique. That is an implementation recommendation, not a change made to the dashboard. The accounts/users routers, like the reports router, are absent from this pinned app’s mount list even though historical creation/update logs exist. [^accounts][^users][^app][Q17][Q25][E-schema]

### B6. The three “active customers” and contactability

| Consumer | Grain / window | Status handling | Cleanup | Refresh |
|---|---|---|---|---|
| Nightly `kpi_daily` | One distinct-buyer number, run time−30 days onward | Exactly 1 | None for QA, email, brands, or SKUs | 06:15 wrapper; appended |
| Exec daily KPIs | Distinct ordering users per Eastern day, today plus 13 prior days | No filter | UID 424242; first parent product’s brand not Lucente/Jetem | Query-time customers joined to report snapshots |
| Board actives | Distinct ordering users, query time−30 days onward | Anything except 0/2/3, so 6 survives | Test-user table plus internal/test/example email domain/localpart patterns | Query-time |

Evidence for every definition: [^customers][^dashboards][^constants]. All three source queries use lower-bound-only windows; historical replays against a fuller database need an explicit upper bound and historical statuses to become point-in-time reconstructions. [^customers][^dashboards][^time]

Stored December 31 nightly actives are **1,152 at 11:15 UTC**. Applying the nightly rule to the current snapshot at the later historical anchor returns **1,146**; the board rule returns **0**, and December 31’s exec daily count is **54**. Those are distinct definitions/clocks, not failed reconciliation of a single metric. [Q15][Q51][Q52][Q53]

The trusted contactable view requires opt-in, a syntactically valid email, exclusion of `example.com/net/org`, and exclusion of `*.example`. All observed users’ domains fail those exclusions, yielding **zero contactable users**. The exec dashboard counts distinct contactable **ordering users that day**, not all contactable users or all opted-in users. There are **24,193 opted-in user rows**, which cannot substitute for contactability. [Q19][Q09][Q23][Q45][^dashboards]

The digest instead counts `users WHERE email NOT LIKE '%@example.com'`, without opt-in or the trusted view. It therefore records **40** recipients from `gmail.example`, although only **23** of them are opted in and none pass the trusted view. Some early digest top products are the report-excluded SKUs. [Q45][Q49][^digest][^constants]

### B7. Daily snapshots and the seven-day widget

Both report writers append product snapshots with one timestamp per invocation. Correct selection is **maximum batch timestamp per report date**, all product rows at that timestamp, final rows for closed days, and intraday rows only for today. Do not select the latest row independently per product, because disappeared products could then be retained from older batches. [^reports][^dashboards]

At the historical anchor, the corrected widget is **139,598.13**. Executing its old inclusive `CURRENT_DATE−7` union logic against the same data gives **410,387.39**: it includes eight calendar dates, accumulated intraday snapshots, and overlap with already-closed daily snapshots. Each of December 25–31 has two intraday versions; the final-report table has no multi-version day in this particular snapshot, though its writer permits reruns. [Q55][Q56][Q57][Q28]; commits `686a5d6`, `3eced24`.

December 31’s latest intraday batch is **22:00 UTC / 17:00 Eastern**, **60 item units**, **18,202.09 revenue**; its daily ordering-user count is **54** and contactable count **0**. December 30’s closed-day batch has **81 units / 24,767.62**. Customer counts are computed from current orders, while report totals were frozen earlier. The `daily_kpis` query starts from report days, so missing report days disappear rather than becoming explicit zeros. [Q53][Q54][^dashboards]

Two independently verified old undercount mechanisms: the DST fall-back report omitted **8 included orders / 2,985.99** from the last hour of November 3; and the November 17 cap omitted **217 otherwise-included orders / 74,995.96** after the first 500 scanned parents. Current code removes both mechanisms, but old snapshots retain their original production outputs. These diagnostics use the available current order state, not a reconstruction of every status at the original run. [Q59][Q60][Q79][Q16]; commits `102c9b4`, `1233af8`.

### B8. Sessionized funnel

`daily_funnel` unions cart and order timestamps from the last 24 hours, sorts per user, and starts a session when the inactivity gap is **strictly greater than** 120 minutes. It ignores storefront session strings, product views, payment/refund events, order status, QA filters, and conversion stages. Its `users_active` is activity-based, not the buyer metric. [^funnel]

Commit `f915c1b` changed the gap from 30 to 120 minutes on December 14 at 20:00 UTC. Job logs show 30 through that morning and 120 thereafter. December 31’s run reports **345 sessions / 308 active users** for a trailing 24-hour window, not a midnight-bounded previous calendar day. A time-series change across that release can be definitional. [Q16][^funnel]; commit `f915c1b`.

## Appendix C. ML, recommendations, and heuristic systems

### C1. Version/consumer history

| Version / change | Producer and serving behavior | Verified timing / evidence |
|---|---|---|
| Original affinity | Co-cart directed pair table; similar widget v1; fallback computed live from seven-day paid parent best sellers | commits `776d674`, `f1217a8`; [Q29][Q42] |
| Graduation gate | Pairs observed <3 get −1 sentinel; serving filters score ≥0 | commit `fef5c96`; [^affinity] |
| Affinity v2 introduced | Conversion-weighted pair scores, same-category/price boosts, monthly factor | commit `89666bf`; [^affinity] |
| December-factor fix, writer 2.0.1 | Eleven-entry Jan–Nov seasonal list caused December crash; guard returns factor 1.0 | commit `3dbe4d7`; [Q16][Q30] |
| Serving 2.0.0 rollout | Default flag dispatches v2 table; adds random arm; changes fallback to persisted trending | commit `df4ed85`; [Q29][Q42][^similar] |
| v4 training introduced | Random-arm logistic fit and score rescaling; flag remains v2 | commit `a1946ff`; [Q14][Q29][^model] |
| December 17 early return | Random recommendations still served/app-logged, decision insert bypassed | commit `30e8907`; [Q41][Q76] |
| December 19 fix + cache | Restore random decision insert; six-hour PID-only cache initially includes empty lists | commit `a00f24c`; [Q41][Q29] |
| December 26 cache repair | Cache key adds table; invalidate on MAX(updated_at); use latest score epoch; cache only nonempty lists | commit `8ed2971`; [^similar] |

The active flag is **serving version 2.0.0**; row writer version **2.0.1** is a separate concept. Do not call that mismatch a failed v4 deployment. There is no 3.x dispatch branch in the inspected serving code. A registry record for 4.0.0 does not mean 4.0.0 served traffic. [^similar][^affinity][Q14][Q29][Q30]

The v1 decision rows kept `effective_version = 1.0.0` even when `rec_source = fallback`; v2 uses effective `fallback`. Historical comparisons must use source/reason as well as version. [Q29]; commit `df4ed85`.

### C2. Affinity formulas and what they really observe

**v1:** self-join `cart_items` on equal raw session and different product IDs; filter only the base-side timestamp to run time−30 days; aggregate raw pair-row count and last base cart time. Eligible score is `pairs × exp(−0.05 × age_days_since_last_base_cart)`; pairs <3 receive −1. [^affinity]

The cart table is mutable: `/cart` appends a row, but `/cart/remove` deletes all rows matching user/product/session. Thus the surviving cart rows are not an immutable activity log; removal can change later affinity and funnel recomputations. App add/remove events are a separate logging surface. [^carts][^affinity][^funnel]

**v2:** same pair construction, plus `conv` counts pair rows whose recommendation-side user has **any** status-1 parent order for the recommended product. Score is:

```text
raw = (pairs + 3 × conv) × exp(−0.05 × age_days)
if same nonblank category: raw *= 1.15
if rec/base current-price ratio >4 or <0.25: raw *= 0.7
score = round(raw × monthly_factor, 4)
pairs <3 → score −1
```

`conv` is an extra 3× weight on top of the cart pair’s 1× contribution; it is not a clean “replace weight 1 with 3” event model. It does not require an order after the cart, within the same session, within 30 days, or for a subsequently appended line. The join lacks user equality and a recommendation-side time bound, so reused session strings and repeated cart rows can inflate pairs. These are limitations of the SQL, not validated conversion attribution. [^affinity][^orders]

Latest v2 has **3,912 pair rows**, **2,964 sentinels**, **948 eligible pairs**, **1,476 distinct bases overall**, all stamped 2.0.1 at December 31 **08:45 UTC**. This snapshot’s pair count is not an experiment sample size or serving coverage rate. [Q30]

Both affinity jobs full-delete and insert their table using autocommit. A crash during population can leave an empty/partial table visible to serving, despite the comment “full recompute.” The seasonal crash occurred before connection/table deletion, so the observed December 3–5 incident is different from that potential mid-publication failure. [^affinity][^db][Q16]

### C3. Serving, fallback, and cache

- `K = 5`. Exploit fetches the top nonnegative scores for the base at the **global latest table timestamp**, then removes the two excluded SKUs in Python. It does not refill a shortened nonempty list; zero items trigger fallback. The lookup is only base-product-specific, not user-personalized. [^similar]
- V2 reads `product_affinity_v2`; any other non-random selected version falls through to `model_scores`. The alias map accepts 2/v2 and 4/v4/model4; the version enum itself does not validate arbitrary flag values or restore the retired v1 table path. [^similar]
- Fallback returns top-ranked products from the maximum day in `trending_daily`, without an age limit, explicit excluded-SKU filter, base-product filter, stock filter, or tie/duplicate snapshot selection. A stale trending day can remain “available” indefinitely. [^similar][^trending]
- Cache TTL is six hours and cache is process-local. Current epoch refresh compares `MAX(updated_at)` and invalidates table-specific entries when it changes; exceptions are swallowed. Per-row autocommit publication means a new epoch may become visible before its full batch is ready. [^similar][^db][^affinity]
- A reason of `cache` is not itself a failure: logs contain **21,427 model decisions with reason cache**, plus **25,091 fallback decisions with reason cache** from the earlier cache behavior. Group by source/effective version before interpreting the reason. [Q29]; commits `a00f24c`, `8ed2971`.

`db_queries` shows **392,630 app reads of v1**, ending December 6 just before 15:00 UTC; v2 app reads begin immediately thereafter. V4 has **17 job reads of v2 candidates** and one ad hoc `model_scores` inspection, but no app reads of `model_scores` in the saved query. This supports keeping the legacy writer classified as **no observed current widget consumer**, rather than asserting every possible external consumer is absent. [Q42][^similar]

### C4. v4: advertised features versus actual implementation

Training consumes all logged random-arm exposure rows available at the run. The feature vector is exactly:

1. Served-list length.
2. Current base price /1,000.
3. Count of all status-1 **parent** orders for the base /100.
4. `min(account_age_days /60, 1)`; age comes from first-seen user timestamp.
5. Signup channel equals organic, encoded 0/1. [^model][^catalog]

Stock and marketing opt-in are fetched but not used. Region affinity and device mix are not queried into the vector. README’s richer feature list is therefore stale/aspirational. All **14,566 observed random lists have exactly five items**, so the first feature has no variation in the inspected exposure data. [^model][Q63][^readme]

The target is the existence of any later paid parent order by that user. Repeated exposures can share one eventual order; recent exposures have shorter outcome follow-up; order status and current product attributes can change after exposure. No fixed outcome horizon, item-match requirement, training cutoff window, holdout, calibration check, or evaluation metric is implemented. A retrospective rebuild from the warehouse would not be the same point-in-time training data. [^model][^orders][^catalog]

If training has ≥20 rows and both classes, it fits deterministic `LogisticRegression(random_state=0, solver='lbfgs')`. It then takes only the coefficient on list length, `w`, and writes **`v2_score × (1 + 0.1w)`** for every eligible pair. It does not evaluate the fitted model’s probability for a candidate or a user. Insufficient/single-class data writes a registry note but leaves old model scores in place. [^model]

The latest registry has **14,411 train rows**, with first coefficient about **−0.2448375**, implying multiplier about **0.97551625**. Observed score ratios are **0.975450970–0.975558015**, consistent with rounding, and **all 948 ranks are unchanged** when ties are broken by recommendation ID in the diagnostic. V4 is operational training output, not demonstrated new recommendation quality. [Q14][Q44][Q77]

### C5. The logging gap, precisely

| UTC day | App random-arm `rec_served` requests | Random decision rows |
|---|---:|---:|
| December 16 | 789 | 789 |
| December 17 | 658 | 549 |
| December 18 | 848 | 0 |
| December 19 | 822 | 407 |
| December 20 | 557 | 557 |

The comparison is at day/arm grain, with an additional timestamp/user/base anti-join confirming **1,372 missing random exposures**, from **December 17 16:50:10 UTC** through **December 19 14:54:44 UTC**. Serving continued and app events survived; the training decision table was incomplete. The unchanged training-row count **5,798** on December 18/19 is consistent with that outage, but is not by itself proof of equal traffic. [Q41][Q76][Q14]; commits `30e8907`, `a00f24c`.

The decision schema has no session/request ID; app events have session and list size but not the actual recommended IDs. The missing lists cannot be faithfully regenerated solely from those app fields. Existing tuple joins are useful diagnostics, not a guaranteed unique request identity. [E-schema][^similar]

### C6. Trending, risk, pricing, and reorder

**Trending:** current window is **30 days**, status-1 parent units, minimum 5, score `units × exp(−0.05 × age_since_last_order)`, top 50. It deletes/replaces only the current UTC-date-labeled day and keeps older days. `scored.sort(reverse=True)` resolves score ties by units and then higher product ID. README still says 60 days; commit `f563dea` changed the window on December 6, and logs first show 30 on December 7. It is a popularity heuristic used by fallback, not a learned recommendation model. [^trending][Q16][^readme]; commit `f563dea`.

**Fraud:** score is `min(min(price/3000,1) × (1 + 0.15new + 0.15velocity),1)`, rounded four decimals. New means first-seen user age <7 days at order time; velocity counts ≥3 parent orders in an inclusive prior-24-hour interval, including the current order and without a status filter. Only recent status-1 parents are scored; scores strictly above threshold become status 6. It is a hard-coded rule, not a fitted or outcome-validated fraud model. [^risk][^catalog]

Threshold history is **0.90** at introduction (`e4656fb`), **0.70** after December 5 (`53f6f6c`), **0.85** after December 29 (`1cb8721`). The latter commit changes only the constant; an independent historical SQL statement releases held parents priced <2,600. The warehouse has **1,631 scored parents** and **12 still held**, with remaining held prices **2,655.33–5,999.98**. Status-1 finance/trending/rollup jobs exclude them; daily-report and board exclusion lists do not. [Q16][Q20][Q47][Q80][^risk][^reports][^customers][^dashboards]

**Pricing:** top 500 products by 14-day paid parent-order count; determine median count in that selected list, nudge +5% above it and −5% otherwise; overwrite `price_suggestions`. Introduced `894c535`, serving rollout held `cca9b0d`. The queried logs show no SELECT reader of this table; app pricing reads neither suggestions nor a learned elasticity model. Actual prices still come from callback/vendor paths. [^pricing][Q42][^orders][^catalog]

**Reorder:** top 200 products by paid parent counts /14; `hint = int(15.6 + 162.4/(velocity+1.8))`. Commit `f85cdd2` changed only K from **141.12 to 162.4**. Lower velocity mechanically increases the hint. The latest table has **200 rows**, velocity **0.0714–2.7143**, hint **51–102**, with no input for inventory, lead time, open purchase orders, stockouts, holidays, margin, or cash constraints. Treat the README’s advisory restriction as substantive, not a trained-model disclaimer. [^reorder][Q48][^readme]; commit `f85cdd2`.

## Appendix D. Scheduled jobs and safe pipeline changes

### D1. Current wrapper inventory and downstream impact

Times below are the **cron-expression clock in source**, not a verified deployed timezone. Every wrapper has one BashOperator, `catchup=False`, and no dependency sensors or inter-DAG edges. Historical cron times were documented as local and observed job timestamps follow Eastern offsets; current DAGs have naive start dates and no explicit timezone. [E-dags][^time]; commit `4bfcbe6`.

| DAG / schedule | Reads → writes | When it fails or becomes stale | Write/retry semantics | Evidence |
|---|---|---|---|---|
| `reconcile` `0 3 * * *` | Parent duplicate refs → warning/job logs | Duplicate-payment-ref investigation loses its nightly signal; no repair is blocked because it never repairs | Repeats warnings, max 200 refs | [^reconcile][Q16] |
| `affinity` `30 3 * * *` | Raw co-carts → `product_affinity`; ensures decision-log table | No current widget reads observed after v2 switch; initialization/unknown external readers still require checking | Full delete/reinsert, autocommit | [^affinity][Q42] |
| `affinity_v2` `45 3 * * *` | Carts/orders/products → `product_affinity_v2` | Widget fallback/coverage/ranking and v4 candidate generation affected | Full delete/reinsert, autocommit | [^affinity][^similar][^model] |
| `model_train` `15 4 * * *` | Random decisions/orders/users/products/v2 → registry + `model_scores` | V4 score freshness affected if flag enabled; default v2 not directly switched | Registry append; scores replaced only after successful fit | [^model][^similar] |
| `price_suggest` `45 4 * * *` | Products + 14-day paid parent demand → suggestions | Shadow analytics stale; no observed serving reader | Full delete/reinsert | [^pricing][Q42] |
| `trending` `15 5 * * *` | 30-day paid parents → `trending_daily` | Recommendation fallback can use old/empty rankings | Delete/reinsert current day, old days retained | [^trending][^similar] |
| `fraud_score` `45 5 * * *` | Recent paid parents + users → risk rows + order status 6 | Risk rows/holds missing; status-1 downstream totals change | Append risk rows, mutate parents; repeat holds not symmetrical with original run | [^risk][Q47] |
| `daily_report` `0 6 * * *` | Yesterday’s local items/current filters → `report_rows` | Closed-day KPIs/widget day missing or partial | Append batch per run; no completeness flag | [^reports][^dashboards] |
| `kpi_daily` `15 6 * * *` | 30-day paid parents → `kpi_daily` | Stored buyer series stale; exec/board queries do not read this series | Append | [^customers][^dashboards] |
| `funnel` `20 6 * * *` | Last-day cart/order timestamps → `daily_funnel` | Session/activity series missing; no implemented conversion stage | Append | [^funnel] |
| `monthly_statement` `30 6 1 * *` | Prior-month paid parents + fees → statements | No new published month; final views cannot manufacture a base month | Append, no month uniqueness/latest selection | [^finance][Q19] |
| `top_sellers` `45 6 * * *` | Yesterday’s paid parent units → top products | Stored top-50 list stale; Redash best sellers is independently queried | Append | [^top][^dashboards] |
| `reorder_forecast` `50 6 * * *` | 14-day paid parent velocity → reorder hints | Advisory table stale/partial; not a finance publication dependency | Full delete/reinsert | [^reorder] |
| `email_digest` `15 7 * * *` | Flag + seven-day paid-parent leader + loose email count → digest log | No log when disabled; no implemented external mail send | Append if enabled | [^digest][Q49] |
| `intraday_report` `0 12 * * *` | Today’s local items to run time → intraday rows | Today’s KPI/widget frozen at prior snapshot | Append; migrated wrapper omits retired 17:00 run | [^reports][E-dags][Q16] |
| `warehouse_backfill` manual | Serving table manifest → CSV → BQ full replacements | Warehouse copies stale or inconsistently rebuilt; missing views not recreated | Serialized per-table exports; `bq load --replace` | [^warehouse][E-dags] |

Both affinity writers continue running, but model training reads **v2**, not v1. The meaningful dependency order is v2 publication → training, trending publication → fallback, fraud status mutations → status-filtered reporting, and statement/override/chargeback inputs → final view. The wrapper schedule spacing alone does not enforce these dependencies. [Q42][^model][^similar][^risk][^finance][E-dags]

### D2. Verified incidents and misleading health signals

- **Affinity v2 crash:** `novamart_logs.job_runs` contains `job_crashed`, `IndexError: list index out of range`, at **2019-12-03/04/05 08:45 UTC**, indexing `SEASONAL_FACTORS[t.month−1]`. First successful refresh is December 6 08:45, writer 2.0.1, season 1.0. The serving v2 switch happened later that day, so the three crashes should not be called three days of already-live v2 recommendation failures. [Q16][Q29][Q42]; commit `3dbe4d7`.
- **Digest flag failures:** original gating read the wrong environment path; `8dc520b` honors `ENABLE_DIGEST` but did not ensure the file was sourced. `0bd4eac` added direct `deploy/cron.env` reading. First `digest_sent` is December 17 12:15, with 40 recipients. Current precedence is `ENABLE_DIGEST` env, then `DIGEST_ON` env, then file value, else 0; env value 0 overrides file value 1. Disabled returns without a job log. [Q16][Q49][^digest]; commits `8dc520b`, `0bd4eac`.
- **Reconcile schedule:** changed from 02:00 local to 03:00 in `388370b`, whose commit describes backup-window overlap. SQL logs switch from 07:00 UTC on November 10 to 08:00 on November 11. The inspected job durations do not demonstrate a backup-induced performance incident: the largest captured reconcile duration is only 9.8 ms. Treat overlap as source-described context, not measured causal slowdown. [Q65][E-jobs]; commit `388370b`.
- **Success can publish a wrong number:** daily reports logged success while truncating at 500 or using the old 24-hour DST boundary. The logging regression also served recommendations successfully while omitting training exposures. Exit success and output validity are separate checks. [Q16][Q59][Q79][Q41]
- **Migration regression:** historical intraday logs include noon and 17:00 local snapshots; the sole Airflow intraday wrapper has `0 12 * * *`. Confirm this schedule loss when comparing refresh expectations across the migration. [E-dags][Q16][^reports]

### D3. Changes needed for safe reruns/extensions

These are **proposed engineering actions** derived from the inspected implementation, not mutations performed in this investigation. [^db][^reports][^finance][^model][^warehouse]

1. **Make publication atomic and identifiable.** Autocommit jobs can expose partial delete/reinsert tables or partially appended snapshots. A maximum timestamp is not a completion marker. Use transaction/staging publication and a completed run ID; select the latest completed run. Reusing an identical timestamp can duplicate rows even under MAX(timestamp) readers. [^db][^reports][^affinity][^trending][^dashboards]
2. **Pass a logical data interval.** Jobs use wall-clock `now()`/`FAKE_NOW`, not Airflow logical dates, and most rolling queries have only a lower bound. Retrospective reruns can consume future warehouse rows, current statuses, and changed dimensions; preserve the original output when reproducing an old deck. [^time][E-dags][^funnel][^customers][^model][^policy]
3. **Enforce dependency/freshness contracts.** Gate model training on a complete v2 epoch; distinguish a fresh trending fallback from an old maximum day; alert on missing report dates and random-arm logs separately from app availability. [^model][^similar][Q41][Q54][E-dags]
4. **Preserve metric definitions deliberately.** Changing parent jobs to item grain affects top sellers, trending, risk thresholds, price demand, reorder velocity, and flat-fee diagnostics. Revenue consumers also differ on held/test/brand/SKU treatment. Use the bridge queries before treating changes as business movement. [Q26][Q36][Q37][^top][^trending][^risk][^pricing][^reorder]
5. **Repair the ops discount helper before relying on it.** Finance-approved `DISCOUNT_CAP` is 0.25, but `apply_discounts` defaults to 0.40 and `rerun_kpis.py` omits the argument: it would return 60% rather than 75% of its manually supplied revenue rows. The script currently has empty rows and prints results; it does not persist a recomputation or call the daily/monthly jobs. No exact discount/promo SQL reference was found in the inspected log search, so this is a latent helper defect, not evidence that all reported revenue was discounted incorrectly. [^discounts][Q66]; commit `35c581e`.
6. **Fix the pinned warehouse wrapper/mapper contract before a rebuild.** `--project`, `--instance`, and `--staging` are required, while the DAG command supplies none. The pinned mapper targets `analytics`, unlike the actual `novamart_analytics` dataset. It loads tables only, not the four analytics views or log exports; views and log ingestion need separate lineage. [^warehouse][E-dags][E-schema]
7. **Verify route availability and test breadth.** Reports/accounts/users modules are not mounted in pinned `app.py`. CI exercises one view/cart/order and only reconcile/daily/monthly jobs; it does not cover multi-item attribution, refund idempotency, ML dispatch/cache, random logging, or schedule parity. A green smoke test would not establish these contracts. [^app][^ci][^orders][^similar]

## Appendix E. Warehouse data dictionary and provenance

### E1. Serving versus warehouse names

| Serving object family | Warehouse family | Meaning / provenance |
|---|---|---|
| `public.*` app/report tables | `novamart.*` | Manifest-driven table copies from serving Postgres |
| `analytics.*` tables/views | `novamart_analytics.*` | Actual analytics dataset; pinned docs/loader’s `analytics` name is stale for this endpoint |
| `db_queries.log` | `novamart_logs.db_queries` | Raw text SQL and Python params with actor/timestamp |
| `app.jsonl` | `novamart_logs.app_events` | JSON product/cart/order/refund/registration/recommendation events |
| `jobs.jsonl` / operations crash events | `novamart_logs.job_runs` | Batch statistics and captured crashes |
| Normalized SQL projection | `novamart_logs.db_queries_normalized` | Historical Postgres log projection with warehouse-job-shaped fields |

Evidence for every mapping: [E-schema][Q10][Q11][Q12][Q68][^logging][^warehouse]. `db_queries_normalized` is not evidence that historical Postgres statements were native BQ jobs with verified success. The logger writes **before execution**, and raw history includes attempts using nonexistent field names; normalized sample rows labeled DONE do not supply those statements’ returned results. [^db][Q20][Q68]

### E2. All application tables

| Warehouse table | Snapshot rows | Grain / joins / hazards |
|---|---:|---|
| `novamart.users` | 38,950 | Numeric `id`; mutable email; first-seen `created_at`; synthesized profile fields |
| `novamart.accounts` | 30 | UUID-string `account_id`; copied email; account creation timestamp |
| `novamart.account_map` | 30 | Numeric `uid`↔UUID account relation with link timestamp; no unique UID declared in writer |
| `novamart.products` | 81,018 | Numeric ID; current brand/category/vendor/price/cost/stock; not an SCD |
| `novamart.cart_items` | 36,938 | Cart row ID, numeric user/product, raw session, timestamp; repeated adds are rows |
| `novamart.orders` | 9,127 | Parent ID, numeric user, first product/ref, total price, current status, first/update time |
| `novamart.order_lines` | 2,284 | Parent/product/price/session/ref/time; new refs unique in serving index; no quantity |
| `novamart.payments` | 9,361 | Movement ID/order/gross/fee/net/time; legacy nullable payment ref; newer ref uniqueness |
| `novamart.report_rows` | 6,923 | Report date/product snapshot units/revenue/created time; append-only batches |
| `novamart.report_rows_intraday` | 2,358 | Same grain, partial-day snapshots; cumulative snapshots must not be summed together |
| `novamart.top_products` | 2,396 | Date/rank/product/units/run time; appended top-50 runs |
| `novamart.statements` | 3 | Month/gross/fee/net/parent count/publication time; no unique month key in base schema |

Counts and columns for every row are from [E-schema]; writer/semantics evidence is [^catalog][^accounts][^orders][^reports][^top][^finance]. Current order status counts are **9,033 paid**, **54 cancelled**, **28 refunded**, **12 held**; no 0/4/5 is present in this snapshot. Absence in data does not remove old or reserved code meanings. [Q07][^constants][^reconcile]

### E3. All analytics tables and views

| `novamart_analytics` object | Type / rows for tables | Grain / principal role |
|---|---|---|
| `blank_brand_products` | Table / 5,972 | Historical product investigation snapshot, suspected cause and captured time |
| `category_names` | Table / 135 | Category code/display group/effective date, original mappings |
| `category_name_history` | Table / 6 | Additional effective mappings, currently dated 2026-08-13 |
| `chargebacks` | Table / 3 | Original order ID/booked amount/report time |
| `statement_overrides` | Table / 1 | Month replacement values/publication time/note |
| `statement_corrections` | Table / 1 | Month audit delta/reason, not a final-view input |
| `test_users` | Table / 1 | Known QA numeric user IDs; currently 424242 |
| `daily_funnel` | Table / 53 | Run-date sessions/activity-user snapshot |
| `kpi_daily` | Table / 45 | Run-date trailing paid-buyer snapshot |
| `digest_log` | Table / 15 | Run time/recipient count/top product; no delivery proof |
| `price_history` | Table / 1,400 | Product/feed price/effective timestamp |
| `price_suggestions` | Table / 500 | Latest shadow product/old price/suggested price/demand batch |
| `reorder_hints` | Table / 200 | Latest product/velocity/hint batch |
| `order_risk` | Table / 1,631 | Parent risk/price core/new/velocity flags/score time |
| `product_affinity` | Table / 3,912 | Latest legacy directed pair/sentinel/count epoch |
| `product_affinity_v2` | Table / 3,912 | Latest directed pair/sentinel/count/writer version epoch |
| `model_registry` | Table / 17 | Training run version/time/coefficient JSON/row count |
| `model_scores` | Table / 948 | Latest eligible pair score/time; lacks explicit version column |
| `rec_decision_log` | Table / 667,850 | Exposure time/user/base/comma-list/intended/effective/source/reason/arm; no request/session ID |
| `trending_daily` | Table / 2,898 | Daily rank/product/score/parent units/run time |
| `contactable_users` | View | Numeric users surviving opt-in/email validation; zero result rows observed |
| `refunds_unified` | View | Mixed status/payment refund-like events; 91 result rows in queried snapshot |
| `statements_corrected` | View | Published snapshots with month overrides |
| `statements_final` | View | Corrected snapshots less original-month chargebacks |

Counts/columns/types are from [E-schema]; view-result counts and transformations from [Q08][Q09][Q19][Q33]; producers from [^affinity][^model][^trending][^funnel][^customers][^pricing][^reorder][^risk][^digest]. Metadata’s `numRows=0` for views is not a zero-valued metric; the statement views return three rows. The metadata endpoint did not expose view SQL, so this investigation combined successful view SELECTs with historical creation statements. [E-schema][Q02][Q03][Q19]

### E4. Logs, time, and warehouse refresh limits

`app_events` contains **1,570,017 rows**, `db_queries` **3,597,650**, `job_runs` **978**; each exported log table has timestamp/severity/text/JSON payload plus export metadata. Payload fields vary by event. Use `JSON_VALUE(jsonPayload,'$.event')`/`'$.job'` for discovery and raw `textPayload` for SQL/params. [E-schema][Q10][Q11][Q12][Q17]

Shared helpers use UTC storage and Eastern local day/month boundaries. Across November 3, the day window is **2019-11-03T04:00Z to 2019-11-04T05:00Z**, not a fixed 24 hours. Funnel/KPI/trending date labels use timestamp casts, while day-report labels use explicit Eastern conversion; preserve the distinction when joining daily outputs. [^time][^funnel][^customers][^trending][^reports][Q20][Q59]

The backfill manifest contains the **32 app/analytics tables**, not the analytics views or exported log tables. It serializes CSV exports, casts timestamps UTC, preserves NULL via `__PGNULL__` distinct from blank text, and loads with `--replace`. Exports are separate operations rather than one database-wide snapshot; no recurring warehouse synchronization is defined by the manual DAG. Data being present now does not establish the pinned wrapper is sufficient to reconstruct it. [^warehouse][E-dags][E-schema]

## Appendix F. Verification, boundaries, and unresolved facts

### F1. What was directly verified

- Pinned checkout identity, historical patches, current writers/readers, all sixteen DAG sources, warehouse object metadata, and all nine Redash dashboard/query definitions were inspected. Repository evidence and inventories are saved under the printed UUID directory. [E-git][E-history][E-schema][E-dags][E-redash]
- Read-only queries verified publication layers, fee warnings/audit rows, chargebacks/refunds, order/payment/line grain, customer identity/contactability, dashboard-definition reproductions, ML output/ranking/consumer lineage, raw query history, and actual job failures. Complete SQL/results are linked in Appendix G. [Q01][Q19][Q26][Q41][Q42][Q76][Q77]
- “Current” in this document means **current pinned code or inspected warehouse snapshot**, distinguished from observed historical execution. The warehouse clock/data cutoff and future taxonomy dates explicitly prevent assuming the imported estate is a live 2026 business series. [E-git][Q32][Q67][Q13]
- Document verification checked the eight required headings in order, exactly one Markdown deliverable, evidence-link/footnote targets, completed read-only query responses, cited commit ancestry, and an unchanged pinned repository. The executable finance recipe also returned the expected published/corrected/final values. [verification report](verification_report.json)[Q81]

### F2. What the evidence does not establish

| Open fact | Why it remains open / next source to inspect | Evidence boundary |
|---|---|---|
| Genuine versus replayed gateway refunds | No gateway event ID/receipt; repeated full amounts are visible, external event identity is not | [Q34][^orders][E-schema] |
| Recommendation causal lift | No observed v4 serving; target lacks product/horizon; random logging gap; no implemented evaluation result | [Q29][Q41][Q77][^model] |
| Deployed Airflow timezone/retry/config | Wrappers omit timezone/retry policy and deployment config was not available through the supplied sources | [E-dags] |
| All external consumers of legacy/shadow tables | Repository, Redash, and saved query history give bounded consumer evidence, not visibility into every outside notebook/service | [Q42][E-redash][^similar] |
| Exact old snapshot rerun from current app tables | Status/product/email are mutable, original run filters changed, and stored facts do not contain full temporal dimension/status history | [Q22][Q37][^catalog][^users][^orders] |
| Router availability beyond the pinned app | Historical account/email logs exist but pinned mount list excludes those routers | [Q17][^app] |
| Why taxonomy effective dates are in 2026 | Actual dates and historical `CURRENT_DATE` SQL are observable; the external execution context that selected that calendar date is not | [Q13][Q20] |
| December final finance publication | No base statement row or January monthly run in the provided snapshot | [Q01][Q03][Q16] |
| External email delivery | Job logs an outcome label but contains no mail transport/integration | [^digest][Q49] |

### F3. Practical answer format

For a disputed number, answer with **metric + amount + data interval + run/as-of time + publication vintage + grain + exclusions + evidence**. For example: “October 2019 final-view net is 1,191,085.36, based on the November 1 statement, a +0.14 fee correction, and −3,567.57 original-month chargebacks; the originally published deck value was 1,194,652.79.” This format follows the inspected restatement policy and verified numeric bridge. [^policy][Q01][Q04][Q06][Q03]

## Appendix G. Evidence index

### G1. Source and dashboard evidence

- **Pinned source:** full commit identity and local history in [git_history.json](git_history.json). Historical patches used in this document are `commit_<hash>.txt` in this directory; the task-relevant hashes are also explicitly cited in the text. [E-git][E-history]
- **Warehouse schemas:** [warehouse_schema_summary.json](warehouse_schema_summary.json) and complete metadata [warehouse_metadata.json](warehouse_metadata.json). These supply dataset/table/view names, all fields, and observed table row counts. [E-schema]
- **Schedulers/logs:** [dag_sources.json](dag_sources.json), [Q16_job_logs_all.json](Q16_job_logs_all.json), [job_log_summary.json](job_log_summary.json). The latter is a local summary of the full saved job query, not a new source. [E-dags][Q16][E-jobs]
- **Redash inventory:** [redash_inventory.json](redash_inventory.json); data source [redash_data_sources.json](redash_data_sources.json); per-dashboard `redash_dashboard_<slug>.json`; per-query `redash_query_<id>.json`. Saved SQL is listed below; dashboard IDs/query IDs are mapped in Appendix B1. [E-redash][E-redash-source]

| Redash query ID | Definition captured from GET response |
|---|---|
| 1 | [refunds SQL](redash_refunds.sql) |
| 2 | [revenue widget SQL](redash_revenue_widget.sql) |
| 3 | [board actives SQL](redash_actives_board.sql) |
| 4 | [registered conversion SQL](redash_registered_conversion.sql) |
| 5 | [final statements SQL](redash_statements_final.sql) |
| 6 | [category revenue SQL](redash_category_revenue.sql) |
| 7 | [daily KPIs SQL](redash_daily_kpis.sql) |
| 8 | [brand revenue SQL](redash_brand_revenue.sql) |
| 9 | [best sellers SQL](redash_best_sellers.sql) |

All definitions in this table are the captured live query definitions, rather than regenerated SQL from repository notes. [E-redash]

### G2. Executed read-only query ledger

Each linked artifact contains the **exact SELECT/CTE SQL**, normalized returned rows, and raw query response including completion status. No historical DDL shown in a log payload was executed by this investigation. Historical dashboard comparisons substitute the stated observation anchor for `now()` and translate Postgres syntax to BigQuery; query IDs identify these reproductions distinctly from Redash execution. [Q19][Q20][Q39][Q51][Q55][Q67]

| Evidence | Read / purpose | Key result or use |
|---|---|---|
| [Q01] | `novamart.statements` | Three as-published months |
| [Q02] | `statements_corrected` | Override-applied publication rows |
| [Q03] | `statements_final` | Current finance surface, October 1,191,085.36 net |
| [Q04] | `statement_overrides` | October fee/net replacement |
| [Q05] | `statement_corrections` | November audit delta zero |
| [Q06] | Chargebacks joined to original orders | Three October orders, 3,567.57 |
| [Q07] | Order status counts/dates/prices | Paid/cancelled/refunded/held snapshot |
| [Q08] | Unified refund event rows | Both status and gateway mechanisms |
| [Q09] | Contactable view count | Zero |
| [Q10] | Earliest job payloads | Log schema/event discovery |
| [Q11] | Earliest app payloads | QA smoke session discovery |
| [Q12] | Earliest SQL log payloads | Actors, params, original status/report rules |
| [Q13] | Category history mappings | Six rows effective 2026-08-13 |
| [Q14] | Model registry | Seventeen v4 training runs/coefficients |
| [Q15] | Latest stored KPI runs | December 31 active count 1,152 |
| [Q16] | All 978 job log records | Execution history, crashes, thresholds, windows, refreshes |
| [Q17] | App event counts and first/last times | Order/appends/replays/accounts/refunds/recs |
| [Q18] | First 300 app warnings | Bounded warning sample; not a complete warning history |
| [Q19] | Historical CREATE VIEW SQL payloads | Finance/contactable/refund lineage |
| [Q20] | All returned non-app/non-job SQL statements | 191 engineer/backfill investigation statements |
| [Q21] | Payment movements by Eastern month | Transaction-time money and fees |
| [Q22] | Parent orders by Eastern month/status | Current-status finance diagnostic |
| [Q23] | User/email/opt-in totals | 38,950 users; 24,193 opt-ins |
| [Q24] | Correct registered-user join | 30 buyers, 74 orders, 18,155.71 |
| [Q25] | Account-map/email join health | 30 mappings, no current email mismatch |
| [Q26] | Line/reference/parent grain | 2,284 lines / 2,059 parents |
| [Q27] | Blank-brand audit snapshot | 5,972 captured products / 38,499.83 revenue |
| [Q28] | Multi-version closed report dates | No such dates observed; writer can append reruns |
| [Q29] | Decision version/source/arm/reason rollout | Legacy/v2/fallback/cache semantics; no v4 traffic |
| [Q30] | V2 pair/sentinel/version epoch | 3,912 pairs, 2,964 sentinels, writer 2.0.1 |
| [Q31] | Price-history coverage/dates | 1,400 rows / 241 products |
| [Q32] | Table/log temporal bounds | Business cutoff and snapshot times |
| [Q33] | Refund month/kind aggregation | Dashboard event-month totals |
| [Q34] | Negative payments joined to parent status | Three retained paid orders with repeated refunds |
| [Q35] | All statement-fee warning payloads | September/October rounding, November old expectation |
| [Q36] | Payment-per-order aggregate then status-1 parent sum | Cohort gross/fee/order-net versus payment-net |
| [Q37] | Item-rule/status/filter monthly bridge | Definitions do not sum to one revenue series |
| [Q38] | Stored daily-report monthly totals | Published operational snapshots, not reconstructed finance |
| [Q39] | Best-sellers definition at historical anchor | Top-20 revenue order plus nonpaid diagnostic |
| [Q40] | Brand definition at anchor | Top-20 groups plus nonpaid diagnostic |
| [Q41] | App-versus-decision day/arm counts | Random logging regression |
| [Q42] | Historical SELECT readers by actor/table | Legacy/v2/model/shadow/reorder consumer lineage |
| [Q43] | Broad discount/promo text search | False-positive brand names; refined by Q66 |
| [Q44] | V4/v2 eligible pair score ratios | Global scalar with rounding |
| [Q45] | User domains and opt-in by domain | example.com/gmail.example only |
| [Q46] | Original category mapping dates/groups | Original six top-level display groups |
| [Q47] | Risk rows joined to parents | 1,631 scored; 12 currently held |
| [Q48] | Latest reorder-hint range | 200 rows; hints 51–102 |
| [Q49] | Digest history | Fifteen counts labeled sent, all 40 |
| [Q50] | Duplicate parent payment references | 130 refs / 285 orders |
| [Q51] | Board actives definition at anchor | Zero after email/table cleanup |
| [Q52] | Nightly active rule at anchor | 1,146 current-snapshot buyers |
| [Q53] | Exec daily customer definition at anchor | Fourteen daily counts; all contactable counts zero |
| [Q54] | Latest closed/today report batches at anchor | Fourteen report-day totals and timestamps |
| [Q55] | Correct seven-calendar-day widget | 139,598.13 |
| [Q56] | Old widget union/boundary logic | 410,387.39 |
| [Q57] | Recent intraday snapshot versions | Two batches per day |
| [Q58] | Date-effective category definition at anchor | Six category totals; future history not effective |
| [Q59] | DST omitted-hour diagnostic | Eight included orders / 2,985.99 |
| [Q60] | Selected busy-day order counts | November 17 has 735 current included-status parents |
| [Q61] | Registered paid orders before enrollment | 63 / 14,911.96 |
| [Q62] | Historical versus current list prices | 1,133 differing history rows |
| [Q63] | Random-list lengths | All five items |
| [Q64] | V2 exposure/source shares | 275,220 logged exposures, mostly fallback |
| [Q65] | Reconcile scheduled SQL timestamps | First later-clock run November 11 |
| [Q66] | Exact discount/promo-word SQL search | Zero rows; latent Python helper isolated |
| [Q67] | Warehouse query clock | October 2026, distinct from business data |
| [Q68] | Normalized historical-query sample | Job-shaped projection, not source execution proof |
| [Q69] | November parent fee expectation | About 32,120.54, 601 post-midnight parents |
| [Q70] | First observed flat-fee payment | November 20 14:27:41 UTC |
| [Q71] | November transaction fee expectation | 3,614 transactions; expectation differs from collected |
| [Q72] | Current catalog completeness | 17,442 blank brands; 33,514 blank categories |
| [Q73] | First-seen user counts by local month | First-seen series, not verified signups |
| [Q74] | QA UID-to-account mapping | Named UUID exclusion is the QA account |
| [Q75] | Parent total versus line sum | All 2,059 match |
| [Q76] | Random app events lacking matching decisions | 1,372; precise gap bounds |
| [Q77] | V2/v4 per-base candidate rank comparison | 948 candidates; zero changed ranks |
| [Q78] | Duplicate-ref parent time range | Duplicates predate idempotency fix |
| [Q79] | Busy-day included tail beyond 500 parents | 217 / 74,995.96 omitted under old cap |
| [Q80] | Current held parent price range/total | 12 / 40,213.29 |
| [Q81] | Execute Appendix A7's complete finance recipe | October publication/correction/final reconciliation in one SELECT |

### G3. Pinned code citations

[^policy]: Commit `5ae1182`, [`docs/restatement_policy.md`](../novamart/docs/restatement_policy.md), lines 5–34, 40–113: source-selection policy, October reconciliation, overrides and chargebacks.
[^orders]: Commit `5ae1182`, [`novamart/routers/orders.py`](../novamart/novamart/routers/orders.py), lines 14–111 and 114–155; [`novamart/routers/payments_webhook.py`](../novamart/novamart/routers/payments_webhook.py), lines 11–20: reference/session locks, merging, charges, cancellation/status refunds, negative gateway rows.
[^finance]: Commit `5ae1182`, [`novamart/jobs/monthly_statement.py`](../novamart/novamart/jobs/monthly_statement.py), lines 13–53: previous-month boundary, status-1 parent sums, collected fees, expectation, append-only publication.
[^reports]: Commit `5ae1182`, [`novamart/jobs/daily_report.py`](../novamart/novamart/jobs/daily_report.py), lines 13–68; [`novamart/jobs/intraday_report.py`](../novamart/novamart/jobs/intraday_report.py), lines 12–77: item fallback, filters, local windows, appended snapshots.
[^constants]: Commit `5ae1182`, [`novamart/constants.py`](../novamart/novamart/constants.py), lines 4–38: fees, excluded SKUs/brands/statuses, retired scan constant, local timezone, discount cap, fraud threshold.
[^dashboards]: Redash queries 1–9, observed in [`redash_inventory.json`](redash_inventory.json) and `redash_query_<id>.json`; exact SQL files linked in Appendix G1. Widget mapping from `redash_dashboard_<slug>.json`.
[^customers]: Commit `5ae1182`, [`novamart/jobs/kpi_daily.py`](../novamart/novamart/jobs/kpi_daily.py), lines 9–25; [`docs/metrics_definitions.md`](../novamart/docs/metrics_definitions.md), lines 6–67: stored trailing paid-buyer calculation and definition differences. Live Redash definitions independently checked.
[^accounts]: Commit `5ae1182`, [`novamart/routers/accounts.py`](../novamart/novamart/routers/accounts.py), lines 12–49: UUID creation, user bootstrap, email copying, explicit UID mapping.
[^users]: Commit `5ae1182`, [`novamart/routers/users.py`](../novamart/novamart/routers/users.py), lines 10–28: mutable email and old/new audit event.
[^catalog]: Commit `5ae1182`, [`novamart/routers/catalog.py`](../novamart/novamart/routers/catalog.py), lines 13–36, 39–65, 68–99: first-sight user/product bootstrap, caches, blank-brand repair, vendor upsert and price history.
[^carts]: Commit `5ae1182`, [`novamart/routers/carts.py`](../novamart/novamart/routers/carts.py), lines 11–30: entity bootstrap, cart-row append, matched-row deletion, separate app add/remove events.
[^onboarding]: Commit `5ae1182`, [`novamart/onboarding.py`](../novamart/novamart/onboarding.py), lines 1–5, 21–48: deterministic profile/vendor/cost/stock generation.
[^app]: Commit `5ae1182`, [`novamart/app.py`](../novamart/novamart/app.py), lines 7–23: pool lifecycle and only catalog/carts/orders/similar/payments-webhook router mounts.
[^similar]: Commit `5ae1182`, [`novamart/routers/similar.py`](../novamart/novamart/routers/similar.py), lines 24–131; [`deploy/flags.env`](../novamart/deploy/flags.env), line 4: active v2 dispatch, exploration pool/seeding, cache epochs/TTL, score/fallback filtering, decision fields.
[^affinity]: Commit `5ae1182`, [`novamart/jobs/affinity.py`](../novamart/novamart/jobs/affinity.py), lines 15–53; [`novamart/jobs/affinity_v2.py`](../novamart/novamart/jobs/affinity_v2.py), lines 13–63: windows, pair joins, sentinels, scoring, seasons, delete/reinsert epochs.
[^model]: Commit `5ae1182`, [`novamart/jobs/model_train.py`](../novamart/novamart/jobs/model_train.py), lines 16–77: random exposure target/vector, deterministic fitting conditions, global rescaling, registry append.
[^top]: Commit `5ae1182`, [`novamart/jobs/top_sellers.py`](../novamart/novamart/jobs/top_sellers.py), lines 12–39: previous-day status-1 parent units, tie-break and top 50, appended rows.
[^trending]: Commit `5ae1182`, [`novamart/jobs/trending.py`](../novamart/novamart/jobs/trending.py), lines 9–40: 30-day/min-5/decay/top-50 parent-order popularity and date-scoped replacement.
[^funnel]: Commit `5ae1182`, [`novamart/jobs/funnel.py`](../novamart/novamart/jobs/funnel.py), lines 9–43: trailing activity union, per-user gap segmentation, appended run-date output.
[^pricing]: Commit `5ae1182`, [`novamart/jobs/price_suggest.py`](../novamart/novamart/jobs/price_suggest.py), lines 1–4, 12–39, 47: shadow-only top-500/14-day/median/±5% computation and hold note.
[^reorder]: Commit `5ae1182`, [`novamart/jobs/reorder_forecast.py`](../novamart/novamart/jobs/reorder_forecast.py), lines 1–4, 12–37: advisory constants, top-200 velocity and inverse formula.
[^risk]: Commit `5ae1182`, [`novamart/jobs/fraud_score.py`](../novamart/novamart/jobs/fraud_score.py), lines 23–51: parent/user scoring, inclusive velocity count, rounded score and strict threshold hold.
[^digest]: Commit `5ae1182`, [`novamart/jobs/email_digest.py`](../novamart/novamart/jobs/email_digest.py), lines 13–56; [`deploy/cron.env`](../novamart/deploy/cron.env), line 3: flag precedence, loose recipient count, parent leader, append-only logging, no transport.
[^reconcile]: Commit `5ae1182`, [`novamart/jobs/reconcile.py`](../novamart/novamart/jobs/reconcile.py), lines 10–23: duplicate parent-ref warnings, status-5 omission, configured batch cap.
[^warehouse]: Commit `5ae1182`, [`novamart/jobs/warehouse_backfill.py`](../novamart/novamart/jobs/warehouse_backfill.py), lines 24–76; [`novamart/jobs/warehouse_manifest.json`](../novamart/novamart/jobs/warehouse_manifest.json); [`docs/data-access.md`](../novamart/docs/data-access.md), lines 6–22; [`airflow/dags/warehouse_backfill_dag.py`](../novamart/airflow/dags/warehouse_backfill_dag.py), lines 1–21: table manifest, schema casts/NULL handling, required args, dataset mapper, full replacement and manual wrapper.
[^time]: Commit `5ae1182`, [`novamart/jobs/timeutil.py`](../novamart/novamart/jobs/timeutil.py), lines 12–40: UTC now/FAKE_NOW, local-midnight day/month conversion; [`crontab.txt`](../novamart/crontab.txt), lines 1–31: retired local schedule reference.
[^db]: Commit `5ae1182`, [`novamart/db.py`](../novamart/novamart/db.py), lines 12–26; [`novamart/config.py`](../novamart/novamart/config.py), lines 4–6: async pool, synchronous autocommit jobs, log-before-execute semantics.
[^logging]: Commit `5ae1182`, [`novamart/logutil.py`](../novamart/novamart/logutil.py), lines 7–30: app/DB/job files and payload fields, explicit flushes.
[^brand-api]: Commit `5ae1182`, [`novamart/routers/reports.py`](../novamart/novamart/routers/reports.py), lines 13–43: calendar-month paid-parent brand endpoint, SKU/brand exclusions, `unbranded` display.
[^discounts]: Commit `5ae1182`, [`novamart/jobs/discounts.py`](../novamart/novamart/jobs/discounts.py), lines 4–10; [`scripts/rerun_kpis.py`](../novamart/scripts/rerun_kpis.py), lines 5–11; constants line 35: 40% default versus 25% constant, missing argument, empty/print-only helper.
[^ci]: Commit `5ae1182`, [`ci/run_ci.py`](../novamart/ci/run_ci.py), lines 26–30, 46–68: scratch schema/truncation, narrow one-order flow, only three job checks.
[^readme]: Commit `5ae1182`, [`README.md`](../novamart/README.md), lines 3–15, 29–45: backend layout, stale 60-day trending/richer-v4 feature claims, advisory reorder status.
[^dashboard-notes]: Commit `5ae1182`, [`docs/dashboard_notes.md`](../novamart/docs/dashboard_notes.md), lines 36–50: notes attribute category item-grain change to `92596dc`; actual category patch is `33054cd`.

[E-git]: git_history.json
[E-history]: trace_history.py
[E-schema]: warehouse_schema_summary.json
[E-dags]: dag_sources.json
[E-jobs]: job_log_summary.json
[E-redash]: redash_inventory.json
[E-redash-source]: redash_data_sources.json
[Q01]: Q01_statements.json
[Q02]: Q02_corrected.json
[Q03]: Q03_final.json
[Q04]: Q04_overrides.json
[Q05]: Q05_corrections.json
[Q06]: Q06_chargebacks.json
[Q07]: Q07_dates_status.json
[Q08]: Q08_refunds.json
[Q09]: Q09_contactable_count.json
[Q10]: Q10_job_sample.json
[Q11]: Q11_app_sample.json
[Q12]: Q12_db_sample.json
[Q13]: Q13_taxonomy_history.json
[Q14]: Q14_registry.json
[Q15]: Q15_recent_kpis.json
[Q16]: Q16_job_logs_all.json
[Q17]: Q17_app_event_counts.json
[Q18]: Q18_app_warnings.json
[Q19]: Q19_view_creation_history.json
[Q20]: Q20_manual_sql.json
[Q21]: Q21_money_by_month.json
[Q22]: Q22_orders_month_status.json
[Q23]: Q23_users_accounts.json
[Q24]: Q24_registered_totals.json
[Q25]: Q25_account_join_health.json
[Q26]: Q26_line_grain.json
[Q27]: Q27_blank_brands.json
[Q28]: Q28_snapshot_versions.json
[Q29]: Q29_decision_rollout.json
[Q30]: Q30_affinity_health.json
[Q31]: Q31_price_dates.json
[Q32]: Q32_table_dates.json
[Q33]: Q33_refunds_month_kind.json
[Q34]: Q34_gateway_status.json
[Q35]: Q35_statement_fee_warning.json
[Q36]: Q36_current_statement_calc.json
[Q37]: Q37_product_filter_bridge.json
[Q38]: Q38_report_months.json
[Q39]: Q39_best_sellers_asof.json
[Q40]: Q40_brand_asof.json
[Q41]: Q41_rec_logging_by_day.json
[Q42]: Q42_score_readers.json
[Q43]: Q43_discount_queries.json
[Q44]: Q44_model_score_ratio.json
[Q45]: Q45_bootstrap_domains.json
[Q46]: Q46_catalog_taxonomy_dates.json
[Q47]: Q47_risk_summary.json
[Q48]: Q48_hint_snapshot.json
[Q49]: Q49_digest_history.json
[Q50]: Q50_duplicate_refs.json
[Q51]: Q51_board_actives_asof.json
[Q52]: Q52_nightly_actives_asof.json
[Q53]: Q53_daily_customer_asof.json
[Q54]: Q54_latest_report_days.json
[Q55]: Q55_widget_asof.json
[Q56]: Q56_widget_old_asof.json
[Q57]: Q57_intraday_versions.json
[Q58]: Q58_category_asof.json
[Q59]: Q59_dst_omitted_hour.json
[Q60]: Q60_cap_days.json
[Q61]: Q61_identity_before_enrollment.json
[Q62]: Q62_price_validation.json
[Q63]: Q63_rec_random_list_lengths.json
[Q64]: Q64_rec_serving_rates.json
[Q65]: Q65_reconcile_schedule_history.json
[Q66]: Q66_discount_exact.json
[Q67]: Q67_emulator_now.json
[Q68]: Q68_normalized_sample.json
[Q69]: Q69_november_fee_bridge.json
[Q70]: Q70_flat_fee_first.json
[Q71]: Q71_november_payment_expected.json
[Q72]: Q72_product_quality.json
[Q73]: Q73_signups_by_month.json
[Q74]: Q74_qa_identity.json
[Q75]: Q75_order_lines_match.json
[Q76]: Q76_random_log_gap_exact.json
[Q77]: Q77_rec_rank_match.json
[Q78]: Q78_duplicate_ref_dates.json
[Q79]: Q79_report_cap_tail.json
[Q80]: Q80_current_month_status_held.json
[Q81]: Q81_finance_recipe.json
