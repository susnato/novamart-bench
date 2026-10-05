# Novamart tribal knowledge

## 1. Summary

**Use `novamart_analytics.statements_final` for the currently restated finance number; use `novamart.statements` to reproduce an originally published statement.** October 2019 net is **1,191,085.36 restated**, versus **1,194,652.79 originally published**. The bridge is a **+0.14 fee correction**, then **−3,567.57 booked chargebacks**. These are verified warehouse results, not just documentation examples. [Q01] [Q03] [Q04] [Q05] [Q07] [C-policy]

- **“Revenue” is several different contracts.** Statements use order-month, paid-status order-header totals and collected payment fees; product dashboards use item prices without a status filter; daily revenue uses filtered, versioned report snapshots. They are not interchangeable. [C-monthly] [C-report] [D09] [D07]
- **Order, item, payment, and callback counts diverge.** Since November 22, callbacks can append items/payments to a recent same-user/session order. The snapshot contains 9,127 orders, 9,361 payments, 2,284 explicit lines, and 173 multi-item orders; legacy orders require an item fallback. [C-order] [Q25] [Q45] [Q60] [W]
- **Customer definitions disagree by design, and some are misleading on these data.** A reproduced December 31 nightly KPI is 1,152 trailing paid buyers; the board query has 1,157 candidates before cleaning and zero after cleaning. All stored emails are `example.com` or `gmail.example`, so the contactable view also returns zero, although the digest reports 40 recipients. [Q35] [Q36] [Q17] [C-digest] [D03]
- **The default recommendation system is affinity v2, not learned v4.** The flag is `2.0.0`; v2 batch rows say `2.0.1`; v4 has 17 training records but no observed v4 decisions. About 75.56% of v2-intended decisions are fallback, and v4 currently rescales v2 scores rather than applying a learned candidate-specific prediction. [C-flags] [C-similar] [C-train] [Q15] [Q30] [Q63]
- **Batch outputs have material operational traps.** Jobs use autocommit; many append snapshots or delete-and-repopulate tables. Reruns can duplicate or expose partial outputs. The Airflow migration drops the old 17:00 intraday run, does not declare a scheduler timezone, and its warehouse wrapper omits required CLI arguments. [C-db] [C-cron] [C-dags] [C-backfill-dag] [C-backfill]
- **This is a historical estate snapshot, not evidence of business activity in 2026.** Core events end in December 2019, but some ad hoc backfill fields carry 2026 wall-clock dates. Rolling `now()` dashboard queries against the supplied snapshot can be empty, NULL, or zero. Historical reproductions below explicitly state their clock. [Q11] [Q34] [Q18] [Q67] [D02] [D03] [D09]

Investigation started at **2026-10-05T15:11:07+00:00**, UUID **`c48a4252-c091-4f94-8bbf-b60c9fe669f3`**, repository pinned at **`5ae11821806a396aac10115e03863b8c68c1bfcc`**. Evidence comes from this repository and its local ancestor history, warehouse SELECT results, and read-only Redash GETs. Saved evidence and the single Markdown deliverable are in this directory. Reference labels resolve to exact source paths, commits, queries, or dashboard definitions in Appendix G. [Session] [History]

## 2. Why this project

The practical problem is **definition drift plus incomplete lineage**: an older board deck can legitimately differ from a newer finance statement; “best seller” can mean revenue-ranked unfiltered items, yesterday's paid order-header units, or decayed trailing demand; and “active customer” can mean three different buyer populations. Reconstructing the intended consumer contract is therefore necessary before explaining a number. [C-policy] [C-metrics] [C-dashboard-notes] [C-top] [C-trending]

The engineering reason is equally concrete: dashboards moved out of the repository, cron was retired, analytics objects were created through historical ad hoc SQL, and the pinned warehouse loader disagrees with the observed analytics dataset. Reading only `schema.sql`, README, or a commit subject misses operational behavior. [C-schema] [C-access] [C-backfill] [W] [Q29] [History: commits `41e3537`, `4bfcbe6`, `5ae1182`]

**Decision policy:** name the consumer, time window, grain, status/filter policy, publication/restatement layer, and freshness before selecting a source. The appendices provide executable read-only reconciliation recipes and change guidance derived from the actual producers and consumers. [C-monthly] [C-report] [D01–D09] [C-db]

## 3. Business understanding

### Commerce lifecycle

1. **First sight is not necessarily signup.** Product views, cart additions, and order callbacks can create numeric `users` and `products` rows. Users receive placeholder email and deterministic profile attributes; product metadata can initially be blank. A count of `users.created_at` is consequently a first-seen identity count, not a validated registration funnel. [C-catalog:58–80] [C-cart:11–19] [C-onboarding]
2. **The catalog feed is the list-price producer.** It upserts catalog metadata/list prices and appends `analytics.price_history`; earlier `ON CONFLICT DO NOTHING` behavior left existing prices unchanged until commit `d213f6e`. Order callbacks nevertheless take `body["price"]` directly, without repricing from the catalog or shadow suggestion table. [C-catalog:84–98] [C-order:17–19] [History: `d213f6e`, `795d273`]
3. **A callback records a money transaction and may extend a basket.** It locks session/ref, finds an existing reference for replay, or appends a new line to an order with the same user/session and a line in the prior 15 minutes. An append increases header `price` and resets status to paid; the header's original product/time remain. A new reference gets its own payment row. [C-order:23–110]
4. **Cancellation, old refund, gateway refund, chargeback, and fraud hold are separate paths.** Cancellation and old refund change order state; gateway refund writes a negative payment without changing order state; booked chargebacks live in analytics; fraud scoring changes paid orders to held status 6. These differences explain why status-based sales, cash movement, refund activity, and finance statements can diverge. [C-order:114–155] [C-gateway] [C-fraud] [Q14] [Q29]

### Deliberate business exclusions

Daily reporting hides SKUs **1004856/1002544**, brands **`lucente`/`jetem`**, and users in `analytics.test_users` (currently numeric QA user **424242**). Product dashboards hardcode QA/brand exclusions but do **not** inherit the excluded-SKU list. Statements apply none of these merchandising/QA exclusions. Lucente's original reporting exclusion is attributed to partnerships in commit `ba1fbfa`; it is not evidence that its payments never occurred. [C-constants] [C-report] [D09] [D08] [C-monthly] [Q29:2019-11-27] [History: `ba1fbfa`, `1169e40`]

### Identity and segments

`orders.user_id`, `users.id`, `cart_items.user_id`, and recommendation `user_id` are numeric shopper IDs. `accounts.account_id` is a UUID in a registration beta, and `account_map.uid → account_id` records the link. The current registered-conversion dashboard instead links by shared email and includes pre-enrollment history. Casting a numeric ID and UUID to text does not establish identity. [C-schema] [C-account] [C-manifest] [D04] [History: `b975479`]

The supplied data have **38,950 users**, **30 accounts**, and **30 account-map rows**. Profile region/channel/device/age/opt-in and product vendor/cost/stock are synthesized from hashes of IDs by `onboarding.py`; downstream models treat these columns as ordinary features, but they are not independently observed customer preferences or inventory movements in this code. [Q24] [W] [C-onboarding]

## 4. Metrics

### Source-of-truth matrix

| Question / consumer | Authoritative contract in this estate | Key qualifications | Evidence |
|---|---|---|---|
| What was originally published for a month? | `novamart.statements` | Append-only publication snapshots; preserve the publication timestamp/version. | [Q01] [C-monthly] [C-policy] |
| What is the current restated finance number? | `novamart_analytics.statements_final`; Redash query 5 | Override layer, then chargebacks attributed to original Eastern order month; not a generic all-refunds cash ledger. | [Q03] [Q14] [D05] |
| Explain statement corrections before chargebacks | `novamart_analytics.statements_corrected` / `statement_overrides` | `statement_corrections` is explanatory, not added by this view; November's stored delta is zero. | [Q04] [Q05] [Q06] [Q14] |
| What money rows were recorded? | `novamart.payments` | Sum at payment grain; separate payment time from order time; negative gateway rows are distinct from order states. | [C-order] [C-gateway] [Q20] [Q26] |
| Daily exec revenue and “orders” | Latest `report_rows` batch per closed day; latest `report_rows_intraday` batch for today | Eastern day; filtered items; “orders” becomes units after the item-grain change; current status 6 is included. | [C-report] [C-intraday] [D07] |
| Exec revenue widget | Same versioned reports, seven Eastern calendar dates including today | Do not union all historical intraday versions into closed days. | [D02] [Q53] |
| Best sellers | Redash query 9 | Rolling 7×24h; item + legacy fallback; QA/brand filters; **no status/SKU filter**; top 20 by revenue. | [D09] |
| Brand / category revenue | Redash queries 8 / 6 | Rolling 30×24h; item prices; no status filter; current product metadata; category mapping effective on item date. | [D08] [D06] |
| Yesterday's top products | `novamart.top_products` | Paid order-header counts; yesterday's Eastern day; top 50 by units; no QA/SKU/brand cleanup. | [C-top] |
| Homepage/trending fallback demand | `novamart_analytics.trending_daily` | Paid header counts, rolling 30 days, minimum five, recency-decayed top 50. | [C-trending] |
| Nightly active customers | `novamart_analytics.kpi_daily` | Trailing paid buyers; 30 days from run time; no QA/email/brand cleanup. | [C-kpi] |
| Exec daily active/contactable customers | Redash query 7 | Per Eastern ordering day; no status filter; QA/brand cleanup; contactable is an intersected eligibility population. | [D07] [Q14] |
| Board active customers | Redash query 3 | Trailing statuses other than 0/2/3; test-user and email cleanup; held orders can qualify. | [D03] |
| Registered customers' conversion | Redash query 4 | All-history paid numeric shoppers linked by account email; returns buyers/revenue, **not a conversion rate**. | [D04] |
| Refunds dashboard | Redash query 1 / `refunds_unified` | Event-month state changes plus negative payment events; `UNION ALL`, not distinct refunds or deduplicated cash loss. | [D01] [Q14] |
| Sessions / funnel users | `novamart_analytics.daily_funnel` | Rolling preceding day of carts/orders, 120-minute inactivity split; omits product-only browsing. | [C-funnel] |

### Verified statement amounts

Amounts are presented as stored; the core monetary schema has no currency column. All three statement layers currently contain the following months, with **no December statement row**. [C-schema] [Q01] [Q03] [Q04]

| Month | Published gross | Published fee | Published net | Final gross | Final fee | Final net | Published order count |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2019-09 | 2,702.00 | 78.36 | 2,623.64 | 2,702.00 | 78.36 | 2,623.64 | 12 |
| 2019-10 | 1,230,332.43 | 35,679.64 | 1,194,652.79 | 1,226,764.86 | 35,679.50 | **1,191,085.36** | 3,765 |
| 2019-11 | 1,101,397.01 | 32,110.92 | 1,069,286.09 | 1,101,397.01 | 32,110.92 | **1,069,286.09** | 3,582 |

Every amount/count in this table comes from [Q01] and [Q03]; October's intermediate net is **1,194,652.93** in [Q04].

### Worked dashboard checks

These are warehouse reproductions of retrieved SQL contracts, **not cached/live Redash results**. Product queries are anchored to `2020-01-01 00:00:00 UTC`; daily/widget queries use Eastern date `2019-12-31`. The Redash query metadata has no cached result IDs. [Q50] [Q52] [Q53] [Redash-queries]

- Best seller **1005116** has 6 items / **5,889.81**; third-ranked **1005284** has **5,096.14** but zero paid-status units; excluded daily-report SKU **1002544** still appears with 10 items / **4,498.52**. This is the query's actual unfiltered-item/SKU policy. [Q50] [D09] [C-constants]
- December 31 daily KPI reproduction has **60 “orders” (units)**, **18,202.09 revenue**, **54 active customers**, and **0 contactable customers**. Revenue is the latest partial report; active customers are calculated separately from order headers. [Q52] [D07]
- The seven-date widget returns **139,598.13** under the fixed contract, versus **371,872.10** under naive summation of both snapshot tables: **232,273.97 excess** due to overlapping/repeated snapshots. [Q53] [D02]
- Registered conversion returns **30 buyers / 18,155.71**. Of 74 paid orders linked through the explicit account map, **63 / 14,911.96** predate account enrollment; the dashboard is not a post-signup conversion cohort. [Q19] [Q37] [D04]

Detailed financial reconciliation, every dashboard contract, and definition-change chronology are in Appendices A–C. [Q01–Q71] [D01–D09] [History]

## 5. System

The serving application is **FastAPI + Postgres**: pooled async connections for API traffic, sync autocommit connections for jobs. It exports JSONL app/job records and raw SQL-with-parameters lines, allowing historical reads/writes to be traced. Query logging occurs **before** SQL execution; a logged statement is an attempted operation, not proof of commit/success. [C-app] [C-db] [C-log]

```text
views / carts / callbacks / vendor feed
                 │
                 ▼
        serving Postgres app tables
          ├── finance statement job ──► statements ──► overrides ──► final + chargebacks
          ├── item sales rollups ──► daily / intraday snapshots ──► exec SQL
          ├── carts ──► affinity v2 ──► similar widget
          │                 └── random exposures + outcomes ──► v4 training / model_scores
          └── paid headers ──► trending ──► widget fallback

        explicit CSV export / replace-load ──► BigQuery snapshot
        app / SQL / job logs ──► novamart_logs
        saved Postgres SQL ──► Redash definitions
```

Edges are derived from the inspected producers/consumers, not an asserted cross-DAG orchestration graph. Redash datasource 1 is type `pg`; Airflow wrappers schedule each job independently, and the warehouse loader is a manual full-table copy. [C-order] [C-report] [C-monthly] [C-affinity2] [C-train] [C-similar] [C-backfill] [Redash-source] [C-dags] [C-access]

**Version reality:** v1 was co-cart affinity with paid-header bestseller fallback; v2 adds conversion-weighted affinity and trending fallback; v4 trains logistic regression but publishes a scalar-rescaled v2 candidate table. The active flag remains v2, and neither the observed decision history nor app score-read families show v4 serving. [History: `f1217a8`, `df4ed85`, `a1946ff`] [C-flags] [C-train] [Q21] [Q30]

**Operational dependencies:** v2 freshness affects direct recommendations and v4 training; trending freshness affects most fallback traffic; report freshness affects revenue/widgets, not the separate board query; fraud status changes alter paid-only finance/KPI/top-seller/model inputs while report and board predicates still include held orders. Appendix E specifies each job, current schedule, failure impact, and safe replay considerations. [C-affinity2] [C-train] [C-similar] [C-report] [D03] [C-monthly] [C-kpi] [C-fraud]

The pinned `app.py` registers catalog, carts, orders, similar, and gateway-refund routers. It **does not register** the account, user-email, or reports routers, despite their files and historical account/email records. Historical evidence establishes those operations occurred; it does not prove they are exposed by the pinned FastAPI entrypoint. [C-app:7–23] [C-account] [C-users] [C-brand-api] [Q22] [History: `f1217a8`]

## 6. Data

| Surface | Observed address | Meaning / limitation | Evidence |
|---|---|---|---|
| Serving names in code/Redash | `public.*` or unqualified app tables; `analytics.*` | Postgres names; do not paste them unmodified as BigQuery dataset names. | [C-manifest] [D01–D09] [Redash-source] |
| Warehouse app data | `novamart-warehouse.novamart` | 12 app tables including accounts, explicit lines, intraday reports. | [W] |
| Warehouse analytics | `novamart-warehouse.novamart_analytics` | 20 tables + 4 views; actual dataset differs from pinned docs/loader's `analytics`. | [W] [Q14] [C-access:9] [C-backfill:60] |
| Logs | `novamart-warehouse.novamart_logs` | Three exports plus normalized query view; raw SQL lives in `textPayload`, app/jobs in `jsonPayload`. | [W] [Q09] [Q10] [Q02] [Q61] |
| Dashboards | Read-only Redash at `http://localhost:5051` | Nine saved SQL queries and nine dashboard listings; query SQL was readable, dashboard detail GETs returned HTTP 500; widget binding/visual rendering was not verified. | [Redash-queries] [Redash-dashboards] [Redash-errors] |

**Time and grain are part of the data contract.** Statements and report days use America/New_York business boundaries; item timestamps can differ from their basket header timestamp; payment timestamps are another clock. Snapshot outputs append versions, whereas affinity/pricing/reorder/model-score tables are overwritten. No complete historical status dimension or general historical product-metadata dimension is present in the inspected schema/manifest. [C-time] [C-order] [C-monthly] [C-report] [C-manifest] [C-affinity2] [C-price] [C-reorder] [C-train]

**Observed freshness:** final daily sales stop at December 30; intraday/KPI/funnel/trending reach December 31. Core order/payment/recommendation history ends in December 2019. Separately, six category history rows use **2026-08-13**, five released holds have **2026 timestamps**, and the blank-brand diagnostic capture is also in 2026. Historical SQL uses `CURRENT_DATE`/`NOW()` for these backfills, so their stored wall-clock fields must not silently be interpreted as 2019 effective dates. [Q11] [Q34] [Q18] [Q44] [Q67] [Q29:2019-12-12, 2019-12-29]

**Source confidence:** executed warehouse SELECTs establish current values; code establishes pinned behavior; historical SQL/job logs establish attempted operations or observed completions; commit dates establish source changes. They are complementary, not substitutes. For example, the November 19 scan fix does not retroactively repair the still-capped November 17 report, and the December 12 taxonomy commit does not override the actual 2026 `valid_from` values. [C-db] [C-log] [Q33] [Q66] [Q70] [Q18] [History: `1233af8`, `33054cd`]

## 7. Experimentation

### What is actually established

| System / experiment | Supported conclusion | What the evidence does not establish | Evidence |
|---|---|---|---|
| Similar-products v2 | Runs and serves some qualifying pairs; observed v2-intended mix is 19.15% direct scores, 75.56% fallback, 5.29% logged random. | A causal increase in sales, or broad product coverage; only 621/42,264 observed base products received direct-score decisions across the v2 history. | [Q49] [Q63] |
| Learned v4 | Trains nightly and writes scores; all 948 matched latest pairs have the same deterministic rank as v2. | Deployed v4 lift or personalized ranking. No v4 decisions were observed. | [Q15] [Q41] [Q58] [Q30] [C-train] |
| Random data collection | User hash modulo 20 selects an arm; list is sampled from the first 500 eligible product IDs, with session/base deterministic shuffle. | Uniform catalog exploration or an unbiased full-catalog outcome benchmark; 1,372 random exposures are missing from decision logs over December 17–19. | [C-similar] [Q39] |
| Dynamic pricing | Shadow suggestions are written; serving rollout was held. | A live price effect: the app has no serving read of the suggestion table in the inspected path/log families. | [C-price] [C-catalog] [C-order] [Q21] [History: `cca9b0d`] |
| Reorder forecast | A hand-fit inverse-velocity advisory heuristic runs. | Purchasing-grade forecasting validation or inventory/lead-time optimization. | [C-reorder] [C-forecast] |
| Fraud | Fixed price/account/velocity score changes order states; 12 current holds, five observed releases. | Validated fraud discrimination or chargeback prevention; code contains no learned fraud fit, labeled evaluation, or holdout metric. | [C-fraud] [Q42] [Q67] |

### Descriptive outcome check, not lift

A read-only check links exposures in `[2019-12-06 17:00 UTC, 2019-12-30 00:00 UTC)` to **paid item events in the next 24h**. It uses explicit lines with legacy fallback, and the snapshot's current order states. Counts below are repeated-exposure counts, not independent users or attributed clicks. [Q57]

| Served source | Exposures | Distinct users | Exposure followed by any paid item | Exposure followed by a served item |
|---|---:|---:|---:|---:|
| v2 score (`model`) | 48,130 | 8,527 | 3,927 / ~8.16% | 420 / ~0.87% |
| fallback | 194,124 | 15,748 | 11,288 / ~5.81% | 299 / ~0.15% |
| random arm | 13,079 | 863 | 506 / ~3.87% | 0 / 0% |

All counts and derived percentages are from [Q57]. Direct-score and fallback traffic have different score availability/populations; random recommendations come from a restricted low-ID catalog pool; logging is incomplete in part of this window; no recommendation click event exists among the observed event types. Thus these numbers do **not** demonstrate v2/v4 incremental revenue. [C-similar] [Q39] [Q22] [Q57]

**Recommended evaluation before extension:** preserve user-level assignment and log completeness; specify a bounded item-level outcome and maturity window; use as-of features; publish candidate-specific predictions; evaluate coverage, fallback rate, ranking changes, and outcomes on a user/time-separated holdout before a logged v4-v2 serving comparison. These recommendations address the concrete label, feature, publication, and missing-log problems in Appendix D, rather than asserting an existing experiment framework. [C-train] [C-affinity2] [C-similar] [Q39] [Q54] [Q58]

## 8. Glossary

| Term | Meaning here | Evidence |
|---|---|---|
| Paid / completed | `orders.status = 1`; callback-set state, not fulfillment proof. | [C-order] [C-monthly] |
| Held | `status = 6`, set by nightly fraud scoring; still admitted by `NOT IN(0,2,3)` consumers. | [C-fraud] [C-report] [D03] |
| Order header | Basket/reference record with original product/time and accumulated price. | [C-order] |
| Item order | Explicit line if present, otherwise the one legacy header item; never both. | [C-report] [D09] |
| Payment | Money row per callback/ref or negative gateway refund; many can belong to one header. | [C-order] [C-gateway] |
| Published statement | Append-only monthly output at publication time. | [C-monthly] [Q01] |
| Corrected statement | Published row with month override values. | [Q14] [Q04] |
| Final statement | Corrected statement minus booked chargebacks in original order month. | [Q14] [Q03] |
| Refund activity | Cancellation/refunded state row plus negative gateway payment rows; not necessarily unique cash refunds. | [Q14] [D01] |
| Active customer | Consumer-specific daily/trailing buyer definition; identify the consumer. | [C-kpi] [D07] [D03] |
| Contactable | Opt-in, email-shape-valid, non-example-domain user in the analytics view. | [Q14] |
| Registered | UUID account linked to a numeric shopper; dashboard currently resolves by email. | [C-account] [D04] |
| Session | Raw cart/callback session string, or funnel's inactivity-derived session; distinct concepts. | [C-cart] [C-order] [C-funnel] |
| Affinity sentinel | Score `−1` means insufficient pair observations, not negative preference. | [C-affinity] [C-affinity2] |
| Intended / effective version | Configured version versus recorded execution path; v1 fallback logs retain effective `1.0.0`. | [C-similar] [Q30] [History: `f1217a8`] |
| `model` source | Serving score-table path, including affinity v2; not proof of learned v4 inference. | [C-similar] [C-flags] |
| Cache reason | Score cache hit, sometimes historically empty-cache fallback; not an experiment arm. | [C-similar] [Q30] [History: `a00f24c`] |
| Reorder hint | Advisory inverse-velocity heuristic output; not a validated purchase quantity. | [C-reorder] |
| Shadow pricing | Fresh price suggestions with no live serving consumer. | [C-price] |
| `analytics` | Postgres schema name; supplied warehouse equivalent is `novamart_analytics`. | [C-manifest] [W] |

# Appendix

## A. Answering “what was revenue in month M, and why?”

### A1. Choose the requested meaning first

1. To match an old deck, select the raw publication row/version from `novamart.statements`. To give the latest approved restatement under the documented policy, select `novamart_analytics.statements_final`. For an unpublished month, say the statement is absent, then label any computed figure as a provisional recomputation under a stated contract. [C-policy] [C-monthly] [Q01] [Q03]
2. Record the Eastern month window, publication time, and data freshness. October is `[2019-10-01 04:00 UTC, 2019-11-01 04:00 UTC)`; November is `[2019-11-01 04:00 UTC, 2019-12-01 05:00 UTC)` because the local boundary crosses the fall-back offset change. [C-time] [Q29:November fee audit]
3. Separate header gross/count from payment fee aggregation before joining. A direct join followed by `SUM(o.price)` repeats header revenue once per payment. Prefer payments aggregated by `order_id`, or the producer's two independent aggregates. [C-monthly:26–35] [C-order] [Q60]
4. Explain overrides and chargebacks separately. `statement_corrections.delta` is not consumed by `statements_corrected`; do not add it again. Gateway refunds are not automatically subtracted by `statements_final`. [Q14] [Q06] [C-gateway]
5. If reconciling back to orders, distinguish **state at publication** from **current state**. Current-state orders cannot automatically recreate the old deck, and product-report totals have additional exclusions and historical bugs. [Q12] [Q31] [Q01] [C-report] [Q70]

### A2. Read-only finance queries

**Published versus current restated number** (BigQuery; change the literal month). This is the source comparison executed in [Q01]/[Q03]/[Q04]; the join below is a convenient equivalent presentation for the currently one-row-per-month snapshot. If multiple publications exist, first select the explicitly requested publication version. [C-monthly] [Q01] [Q03] [Q04]

```sql
SELECT s.month,
       s.gross AS published_gross, s.fee AS published_fee, s.net AS published_net,
       c.net AS corrected_net,
       f.gross AS final_gross, f.fee AS final_fee, f.net AS final_net,
       s.orders_count, s.created_at AS published_at
FROM `novamart-warehouse.novamart.statements` s
LEFT JOIN `novamart-warehouse.novamart_analytics.statements_corrected` c
  ON c.month = s.month
LEFT JOIN `novamart-warehouse.novamart_analytics.statements_final` f
  ON f.month = s.month
WHERE s.month = '2019-10';
```

**Current-state provisional producer-equivalent calculation**, avoiding payment fanout. It reproduces the pinned statement producer's gross/fee logic, not an earlier publication and not complete net cash flow. The payment aggregation has no payment-date condition because the producer assigns fees by the order's month. [C-monthly:26–43] [Q31]

```sql
WITH p AS (
  SELECT order_id, SUM(fee) AS collected_fee
  FROM `novamart-warehouse.novamart.payments`
  GROUP BY order_id
)
SELECT COUNT(*) AS paid_headers,
       SUM(o.price) AS gross,
       SUM(COALESCE(p.collected_fee, 0)) AS fee,
       ROUND(SUM(o.price) - SUM(COALESCE(p.collected_fee, 0)), 2) AS net
FROM `novamart-warehouse.novamart.orders` o
LEFT JOIN p ON p.order_id = o.id
WHERE o.created_at >= TIMESTAMP(DATE '2019-10-01', 'America/New_York')
  AND o.created_at < TIMESTAMP(DATE '2019-11-01', 'America/New_York')
  AND o.status = 1;
```

**Chargeback bridge**: group by the original order month, not `reported_at`. This is the grouping encoded in the final view and inspected in [Q07]/[Q14]. [Q07] [Q14]

```sql
SELECT FORMAT_TIMESTAMP('%Y-%m', o.created_at, 'America/New_York') AS order_month,
       COUNT(*) AS booked_chargebacks, SUM(cb.amount) AS amount
FROM `novamart-warehouse.novamart_analytics.chargebacks` cb
JOIN `novamart-warehouse.novamart.orders` o ON o.id = cb.order_id
GROUP BY 1;
```

### A3. October: the complete numeric bridge

| Step | Gross | Fee | Net | Explanation / evidence |
|---|---:|---:|---:|---|
| As published November 1 | 1,230,332.43 | 35,679.64 | 1,194,652.79 | Old producer rounded `gross × .029`; [Q01] [History: `a92c96d^`, `a92c96d`] |
| Corrected | 1,230,332.43 | 35,679.50 | 1,194,652.93 | Actual summed payment fees; override inserted by logged November 2 SQL; [Q04] [Q05] [Q29:2019-11-02] |
| Final | 1,226,764.86 | 35,679.50 | 1,191,085.36 | Three booked chargebacks totaling 3,567.57 reduce gross and net, not fee/count; [Q03] [Q07] [Q14] |

The chargeback backfill was logged on December 9, but inserted `reported_at = 2019-12-01 12:00 UTC`. It selected the first three qualifying October paid orders over 700 with payments. This is evidence of the estate's booked records, not independent processor verification of why those disputes occurred. [Q29:2019-12-09] [Q07]

October's **current paid-header sum is only 1,206,337.32 / 3,695 orders**, whereas all October header prices still sum to the published 1,230,332.43 / 3,765 orders. The difference is **23,995.11** across 43 currently cancelled and 27 currently refunded orders. The original publication is not recomputed from these later states. [Q12] [Q31] [Q01]

### A4. Fee evolution and November's misleading warning

- Before the November 20 source change, callback fee was `round(price × .029, 2)`; afterward it is `round(price × .029 + .30, 2)` **per transaction**. `a92c96d` changed monthly fee from aggregate gross-percentage rounding to summed collected payments. [History: `12e1c68`, `a92c96d`] [C-order]
- The December 1 November statement already stored **32,110.92 collected fee** and **1,069,286.09 net**, but its warning compared against a percentage-only **31,940.51**, yielding **−170.41**. This warning did not mean the published fee was missing flat fees. `4a58d17` repaired the expected-fee diagnostic; the November audit row's delta is **zero**. [Q46] [Q01] [Q06] [History: `4a58d17`]
- The pinned diagnostic still works at **header grain**, applying one flat fee based on header date after Eastern midnight November 20. Actual payments have finer grain and the rollout transition occurred during that date. November has **601 headers versus 633 payments** after that boundary. Recomputed expected header fees are **32,120.54**, payment-grain midnight-policy fees **32,130.14**, and collected fees **32,110.92**. [C-monthly:13,36–42] [Q62]
- On November 20, **64 payment rows** contain only the percentage part and **57** contain the +0.30 part; those first 64 explain **19.20** of the midnight-policy gap. November 22 adds **0.02** rounding difference under the exact-NUMERIC comparison. Do not replace collected fees with the diagnostic formula or infer uncollected cash from it. [Q68] [Q69] [C-order:19] [C-monthly]
- September retains its original **78.36** statement fee even though payment fees sum to **78.37**; the available override only covers October. “Final” therefore means this view's approved layers, not that every historic rounding discrepancy has been repaired. [Q01] [Q05] [Q31] [Q46]

### A5. Refunds, repeated gateway records, and cash versus sales

| Mechanism | Data change | Monetary interpretation and reporting effect | Evidence |
|---|---|---|---|
| `/orders/{id}/cancel` | Status 2 + `updated_at`; no negative payment | Removes current paid eligibility; refund dashboard treats current cancelled state as activity. | [C-order:114–133] [Q14] |
| `/orders/{id}/refund` | Status 3 + `updated_at`; no negative payment | Historical refund-state path; paid-only recomputations exclude header; does not itself record a money debit. | [C-order:136–155] |
| `/payments/gateway_refund` | `payments.gross = net = −amount`, fee 0 | Gateway-movement mirror; leaves order status alone; producer's header gross does not automatically decline. | [C-gateway] [C-monthly] |
| Booked chargeback | `analytics.chargebacks` row | Final statement subtracts it from original order month, not reporting month. | [Q14] [Q07] |

`refunds_unified` does `UNION ALL` of current order statuses 2/3 and negative payment rows, taking state time from `orders.updated_at` and gateway time from payment creation. A state record and a money record for the same order can therefore both appear. It does not include the separate chargeback table. [Q14] [Q29:2019-12-23]

Verified refund activity: November has **24 cancellations / 6,511.32** and **8 old refunds / 3,180.45** (32 records / 9,691.77 total). December has **30 cancellations / 6,738.32**, **20 old refunds / 10,267.02**, and **9 gateway rows / 1,843.59** (59 records / 18,848.93 total). These are **event-month** aggregates; many underlying orders are from September/October. [Q13] [Q12] [D01]

All nine negative payment rows currently belong to **three status-1 orders**. The same order/amount pairs are recorded on December 13, 20, and 27: order 3776 / 334.34, 3762 / 25.48, 3763 / 254.71. The webhook has no processor event ID or replay deduplication. Investigate whether these are repeated notifications or genuine repeated movements before treating them as nine independent successful customer refunds; the stored records alone cannot decide that. [Q38] [Q64] [C-gateway]

October-assigned payment gross is **1,228,488.84** after those negative rows, distinct from statement gross and current paid-header gross. Payment net assigned to October is **1,192,809.34**; it is not the approved final statement net of **1,191,085.36**. The two use different layers and treatments, so blindly subtracting the refunds dashboard from statements produces another unsupported metric. [Q31] [Q03] [Q14]

### A6. Daily revenue history and replay pitfalls

- The old report used `fetchmany(500)`, then filtered products in Python. November 17's stored report is **487 units / 148,857.07**, while the current source under the then-applicable SKU/Lucente/status filters contains **704 / 223,853.03**. The run log explicitly says **500 orders scanned**. The November 19 `fetchall()` fix did not backfill that snapshot. [Q33] [Q66] [Q70] [History: `1233af8`]
- The pre-November 5 day helper normalized midnight then added 24 hours. The November 3 local day was 25 hours; its missing `[2019-11-04 04:00,05:00 UTC)` hour contains **8 header orders / 2,985.99** in the current snapshot. This quantifies the window gap, not necessarily the exact filtered report correction. [History: `102c9b4`] [Q56] [C-time]
- Before November 18, reports excluded only status 0, so cancellation/refund state changes could remain in report totals. Today the exclusion is 0/2/3, still admitting status 6 and any otherwise unexcluded state. [History: `11c0a42`] [C-constants] [C-report]
- Since December 5, reports use item timestamps/prices with legacy fallback. Before that, multi-item header revenue could be credited entirely to its first product and “units” meant headers. Different item/header times can move amounts between local days or months at boundaries. [History: `92596dc`, `5d1300d`] [C-order] [C-report]
- Reports are append-only and have no batch-complete marker. Current dashboards select the greatest `created_at` **for the day**, not the latest row independently per product. A failed partial newer append can hide a complete older batch; zero-sales days write no rows and can disappear rather than explicitly show zero. [C-report:62–68] [C-intraday:71–77] [C-db] [D07] [D02]

## B. Product/customer reporting and all nine Redash contracts

### B1. Dashboard/query inventory

Query IDs and dashboard IDs differ for three names; use this mapping when citing a screen. All saved queries use datasource 1 (`pg`), `schedule = null`, and `latest_query_data_id = null`. Dashboard listings exist, but detail requests returned 500, so the SQL contracts below are verified independently of widget attachment/rendering. [Redash-queries] [Redash-dashboards] [Redash-source] [Redash-errors]

| Name | Redash query ID | Dashboard listing ID / slug | Full contract |
|---|---:|---|---|
| refunds | 1 | 1 / `refunds` | Read `analytics.refunds_unified`; group Eastern event month; count rows and round summed positive activity amounts. [D01] |
| revenue_widget | 2 | 2 / `revenue_widget` | Seven Eastern calendar dates; latest closed-day final batches + today's latest intraday batch; no extra brand join. [D02] |
| actives_board | 3 | 3 / `actives_board` | 30-day numeric buyer candidates, statuses not 0/2/3; exclude `test_users` and explicit email-domain/localpart patterns. [D03] |
| registered_conversion | 4 | 4 / `registered_conversion` | DISTINCT numeric users matched to accounts by email; all-history paid header buyers/revenue; no denominator/window/QA/brand filtering. [D04] |
| statements_final | 5 | 5 / `statements_final` | Select final finance view ordered by month. [D05] |
| category_revenue | 6 | 6 / `category_revenue` | 30-day items; QA 424242/brand exclusions; effective category mapping; group display group; no status/SKU filter. [D06] |
| daily_kpis | 7 | 9 / `daily_kpis` | Fourteen Eastern dates; snapshot revenue/units + separate daily header buyer/contactable series. [D07] |
| brand_revenue | 8 | 8 / `brand_revenue` | 30-day items; two hardcoded text ID exclusions, two denied brands; group raw brand; no status/SKU filter. [D08] |
| best_sellers | 9 | 7 / `best_sellers` | 7-day items; QA numeric exclusion and denied brands; top 20 descending price-sum, not unit-count. [D09] |

### B2. Reproduce the item contract correctly

The following is the common read-only BigQuery equivalent of the item CTE in current sales dashboards. The anti-join is essential: do not count both a multi-item header total and its lines. Carry status along only if the intended consumer uses it; adding `status = 1` would change the best-sellers contract. [D09] [D08] [D06] [Q32]

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
SELECT io.product_id, COUNT(*) AS units, SUM(io.price) AS revenue
FROM item_orders io
JOIN `novamart-warehouse.novamart.products` p ON p.id = io.product_id
WHERE io.created_at >= TIMESTAMP '2020-01-01 00:00:00+00' - INTERVAL 7 DAY
  AND io.user_id <> 424242
  AND p.brand NOT IN ('lucente', 'jetem')
GROUP BY 1
ORDER BY revenue DESC
LIMIT 20;
```

At the snapshot's November grain, **3,582 paid headers become 3,614 item units**, preserving **1,101,397.01 total price**. December has **1,756 paid headers / 1,942 paid item units**, plus **12 held headers / 19 held item units**. All explicit line sums match their header totals in this snapshot. [Q12] [Q32] [Q45]

The extra UUID exclusion in brand SQL is `cc27b436-d6f9-4e84-adaf-e716025dd369`, described as QA's account UUID. But the input remains numeric `orders.user_id`; that UUID text cannot match it. The working numeric exclusion is 424242, whose snapshot has **14 orders / 139.86**. [D08] [C-schema] [C-dashboard-notes:46–51] [Q55]

### B3. Metadata, blank brands, and category mapping

Brand revenue groups raw `products.brand`, including the empty string; it does not rename blanks to `unbranded`. The old monthly brand API does use that label, but is a different header/status/calendar-month/SKU-filtered contract and is not registered in the pinned entrypoint. It has no test-user filter and would misattribute a multi-item header to its first product if mounted unchanged. [D08] [C-brand-api] [C-app] [C-order]

`analytics.blank_brand_products` is a **diagnostic capture**, not a live dimension. It has 5,972 rows: 3,907 missing-category first-seen/cache cases, 2,065 blank-brand insertion/conflict cases; captured header units/revenue total **204 / 38,499.83**. Its `suspected_cause` is the backfill's heuristic classification, not a proven cause for every row; its capture timestamp is 2026. The catalog later added blank-brand repair in `ea0e97b`, but that does not prove all historical metadata was repaired. [Q44] [Q29:2019-10-21] [C-catalog:35–36,51–55] [History: `ea0e97b`]

Category SQL unions `category_names` (priority 0) and `category_name_history` (priority 1), then picks the newest `valid_from ≤ item.created_at::date`; history wins a same-date tie. Unmatched/blank codes become `other`. This avoids multiplying item rows by all mapping versions. The date cast has no explicit business timezone in the Redash SQL, so verify the datasource session timezone when reproducing boundary items. [D06]

The base mapping has 135 rows covering dates 2019-09-25 through 2019-12-06. The six history rows reclassify `construction.tools.light` to lighting and five `electronics.audio.*` codes to entertainment, but **all six are effective 2026-08-13 in the supplied warehouse**. Therefore the retrieved effective-date logic does not apply those changes to 2019 items. Historical SQL used `CURRENT_DATE`; the commit dated December 12 alone is insufficient to assign a December 2019 effective date. [Q18] [Q47] [Q29:2019-12-12] [History: `33054cd`]

With the explicitly stated historical clock, [Q59] gives electronics **437,887.95**, other **93,558.92**, appliances **30,208.94**, construction **3,713.01**, apparel **3,663.34**, kids **617.89**. It does not produce lighting/entertainment groups for the 2019 items. Current product category/brand fields can still reclassify history; the effective mapping is not a full historical product dimension. [Q59] [D06] [C-catalog] [C-manifest]

### B4. Every customer definition, including signup and contactability

| Consumer | Population / window | Exclusions and trust issues | Evidence |
|---|---|---|---|
| `users` creation counts | Numeric identities at first view/cart/order/account insertion | Auto-bootstrap, placeholder email; profile channels are deterministic; not verified signups. | [C-catalog] [C-cart] [C-account] [C-onboarding] |
| UUID accounts | Account creation records / `account_created` | Creates a new UUID per call; no per-user uniqueness or request idempotency is declared in `account_map`; endpoint not mounted in pinned app. | [C-account] [C-app] |
| Nightly KPI | Distinct numeric paid buyers in trailing 30 days at 06:15-era run | No QA/email/brand filtering; appended once per run, not necessarily one unique row/day. | [C-kpi] |
| Exec daily active | Distinct header-ordering users per Eastern day over displayed 14 dates | No status filter; QA and header-product brand filters; counts are not additive across days. | [D07] |
| Exec contactable | Exec active population intersected with `contactable_users` | Contactability is view eligibility, not observed delivery success. | [D07] [Q14] |
| Board active | Trailing distinct users with status outside 0/2/3 | QA table + internal/test/email heuristics; permits status 6; missing emails coalesce empty and are not automatically rejected. | [D03] |
| Registered buyer | DISTINCT numeric users matched by `accounts.email = users.email`, with any status-1 order | No enrollment-date condition; mutable/nonunique email can break/fan out identity matching, though the CTE deduplicates numeric IDs. | [D04] [C-users] [C-schema] |
| Funnel active | Users with cart or header-order activity in preceding rolling day | No product views, no status/QA cleanup; mutable cart state removes historical events. | [C-funnel] [C-cart] |
| Digest recipients | All `users` whose email does not end in `@example.com` | No opt-in, regex or `.example` checks; not the contactable view. | [C-digest:50–55] |

The three active definitions' history is in `docs/metrics_definitions.md`, but that document's cron references are now historical; the Airflow wrappers are the pinned schedules. [C-metrics] [C-cron] [C-dags]

All **38,950** user emails match the email-shape regex; **24,193** users are opted in. That still yields **zero contactable** because 38,910 addresses are `example.com` and 40 are `gmail.example` (23 of those 40 opt in), and the view excludes both domain groups. The digest's weaker predicate admits all 40 `gmail.example` users. “Valid email syntax,” “opted in,” “contactable,” and “digest recipients” are materially different segments. [Q24] [Q36] [Q17] [Q14] [C-digest]

At `2019-12-31 11:15 UTC`, a bounded historical recomputation yields nightly/stored **1,152**, board candidates **1,157**, cleaned board **0**. The five extra candidate buyers arise under the broader status predicate; all candidates are then eliminated by this snapshot's email rules. The added upper bound in [Q35] prevents later rows in the available snapshot from contaminating the historical run clock; the producer's native query has only the lower bound. [Q35] [C-kpi] [D03]

### B5. Daily KPI / widget trust checklist grounded in their contracts

- Inspect `MAX(created_at)` and expected report day before trusting revenue; missing report batches are not explicit zero sales. Latest intraday is a partial day even when the dashboard says “today.” [Q34] [Q65] [C-report] [C-intraday] [D07]
- Select one complete batch per day. December 31 has two intraday versions, both **60 units / 18,202.09**; summing them yields twice the same cumulative total. [Q65] [D02]
- Daily KPI returns only dates present in `report_days`; customer-only dates can disappear. Revenue and customer counts are computed at different grains/windows, and the brand join for customer counts uses only the header's first product. [D07] [C-order]
- A report can include status 6, while nightly paid-active excludes it. Best-sellers revenue can include held/cancelled/refunded states. Do not explain such a difference as a numerical rounding error. [C-report] [C-constants] [C-kpi] [D09] [Q50]
- Current product metadata is joined again in daily KPI's revenue branches, while the revenue widget does not rejoin products. Later metadata changes can thus make them disagree even on the same source snapshot. [D07] [D02] [C-catalog]

## C. Historical changes that explain discontinuities

Dates below are **source-change dates** unless an observed runtime date is stated. Production/query evidence establishes runtime boundaries separately; deploy-trigger commit subjects alone are not deployment-success logs. [History] [C-db] [C-log]

| Source date / commit | Definition or behavior change | How to use the history |
|---|---|---|
| Sep 15 `2da4141` | Initial fee .029; cancellation constant 4; report excludes only 0; scan cap 500; reconcile limit 100. | Historical constants, not current status meanings. [History] [C-schema] |
| Oct 8 `83fb3ed` | Excluded report SKUs 1004856/1002544. | Later product dashboards do not inherit this filter. [History] [C-constants] [D09] |
| Oct 12 `776d674`; Nov 12 `fef5c96` | Co-cart affinity; minimum-three graduation sentinel added later. | Negative score means insufficient data. [History] [C-affinity] |
| Oct 15 `b676969` | Callback idempotency by ref; original replay could restore any nonpaid state. | Does not deduplicate older persisted order rows. [History] [Q45] |
| Oct 18 `030d841` | Reconcile batch 100→200. | More flags per run, no repair. [History] [C-reconcile] |
| Oct 21 `ea0e97b`, `193f22d` | Blank-brand repair and monthly header brand endpoint. | Distinguish metadata repair from item-grain attribution. [History] [C-catalog] [C-brand-api] |
| Oct 25 `ba1fbfa` | Lucente denied in reports per partnerships. | Report exclusion, not erased cash/finance. [History] [C-monthly] |
| Oct 26 `f1217a8` | v1 widget added; users/reports routers removed from app registration. | Historical records do not guarantee current endpoint exposure. [History] [C-app] |
| Oct 28 `8f19718` | Cancellation 4→2; endpoint added; replay only restores status 0. | Avoid treating historical state constants as a stable enum. [History] [C-order] |
| Nov 2 `a92c96d` | Statement fee now sums collected payments. | October publication remains raw, with a separate override. [Q01] [Q05] [History] |
| Nov 2 `152a760` | Trending introduced with 60-day window. | Current 30-day contract is later. [History] [C-trending] |
| Nov 5 `102c9b4` | Day windows use two local midnights across DST. | Older November 3 report has the short-window risk. [History] [Q56] |
| Nov 6 `9a51155`; Nov 8 `4dbcf7f`; Nov 16 `14726e7` | Top sellers; 30-minute funnel; trailing paid-active KPI. | These are separate metrics/refresh paths. [History] [C-top] [C-funnel] [C-kpi] |
| Nov 9 `d213f6e`; Nov 15 `795d273` | Vendor feed upsert; price history logging added. | Existing-price update and history coverage start are different. [History] [Q21] |
| Nov 10 `388370b` | Reconcile 02:00→03:00; subject says backup overlap. | Runs shift from 07:00→08:00 UTC after source change; sampled durations remain ~5 ms, so do not claim a measured slowdown from the subject. [Q43] [History] |
| Nov 15 `d87cb3d`; Nov 18 `11c0a42` | Status-3 refund endpoint; report excludes cancelled/refunded states. | State and reporting rollout dates differ. [History] [C-order] [C-report] |
| Nov 19 `1233af8` | Report `fetchmany(500)`→`fetchall()`. | November 17 capped output remains in stored data. [Q33] [Q70] [History] |
| Nov 20 `12e1c68` | .30 flat fee per transaction. | Actual transition is within the date, not the later diagnostic's midnight boundary. [Q69] [History] |
| Nov 21 `35c581e` | Config discount cap .25; helper default .40; ops rerun script calls default. | Manual helper can apply wrong cap; live inspected reports do not call it. [C-discount] [C-rerun] [C-report] [History] |
| Nov 22 `5d1300d` | Session-based multi-item orders and line/ref payment schema. | Orders, items and payment counts begin to diverge; line query attempts begin November 22. [Q21] [C-order] [History] |
| Nov 27 `b59f077`, `b567d9d` | QA exclusion; accounts and numeric-user bootstrap. | `test_users` seeded by logged SQL; account namespace is UUID. [Q29] [C-account] [History] |
| Nov 28 `c19a307`; Dec 9 `8dc520b`; Dec 16 `0bd4eac` | Digest introduced; flag name fixed; file read added. | First observed digest output December 17, not November introduction. [Q27] [C-digest] [History] |
| Nov 30 `2814b3d` | Category revenue/base mapping. | Mapping backfills live in SQL logs, not schema.sql. [Q29] [History] |
| Dec 2 `4a58d17` | Expected-fee diagnostic/audit record. | November published fee was already collected; audit delta is zero. [Q46] [Q06] [History] |
| Dec 2 `89666bf`; Dec 5 `3dbe4d7` | v2 seasonal affinity; December array-crash guard. | Three crashes Dec 3–5; first successful output Dec 6 at 08:45 UTC. [Q43] [Q27] [History] |
| Dec 2 `cca9b0d` | Dynamic pricing serving phase held. | Shadow job continues; does not set live prices. [C-price] [History] |
| Dec 3 `e4656fb`; Dec 5 `53f6f6c`; Dec 29 `1cb8721` | Fraud threshold .90→.70→.85; held-price<2600 release logged later. | Observed thresholds change Dec 6 and Dec 30; five releases carry wall-clock 2026 update times. [Q43] [Q67] [Q29] [History] |
| Dec 4 `e10cb0c` | Contactable view and daily contactable metric. | Digest never adopts the stronger view. [Q14] [C-digest] [D07] [History] |
| Dec 5 `92596dc` | Daily report + best/brand dashboards adopt items with legacy fallback. | After order merge rollout, reporting grain catches up later. [C-report] [D09] [D08] [History] |
| Dec 5 `c49a7bb` | Gateway refund negative-payment path. | Observed negative events start December 13. [Q64] [History] |
| Dec 6 `df4ed85`, `f563dea` | v2 dispatch/random arm; trending 60→30 days. | Dispatch reads switch Dec 6; trending run still says 60 Dec 6, then 30 Dec 7. [Q21] [Q43] [History] |
| Dec 8 `a2e0013` | Intraday report snapshots. | Old cron noon + 17:00; Airflow later retains only noon. [C-cron] [C-dags] [History] |
| Dec 9 `cd559d3` | Chargebacks and final statements surface. | Restates October original order month. [Q29] [Q03] [History] |
| Dec 10 `d6e34c6`; Dec 21 `b975479` | Wrong UUID-text join → email-linked numeric-user registered dashboard. | Recover all historical purchases, including pre-enrollment. [D04] [Q37] [History] |
| Dec 11 `2dde4f0` | Board active query introduced. | Cleaned trailing buyer population, not nightly KPI. [D03] [History] |
| Dec 12 `33054cd` | Effective taxonomy union/history fallback. | Actual history effective dates in this warehouse are 2026. [Q18] [D06] [History] |
| Dec 14 `a1946ff`, `f915c1b` | v4 training; session gap 30→120 minutes. | First training Dec 15; funnel logs first gap 120 Dec 15. [Q15] [Q43] [History] |
| Dec 15 `1169e40`; Dec 18 `adbcb7e` | Jetem/brand exclusions; extra QA UUID string filter. | Numeric input makes the UUID exclusion ineffective. [D08] [D09] [History] |
| Dec 17 `30e8907`; Dec 19 `a00f24c` | Random branch early-return drops decisions; restore log + six-hour cache. | Random logging hole Dec 17–19; cached empty lists can fall back with reason `cache`. [Q39] [Q30] [History] |
| Dec 19 `686a5d6`; Dec 24 `3eced24` | Revenue widget naive snapshots → latest closed-day/today selection. | Snapshot summation overstates the worked window by 232,273.97. [Q53] [D02] [History] |
| Dec 21 `f85cdd2` | Reorder K 141.12→162.4 only. | A manual constant retune, not a model redesign. [C-reorder] [History] |
| Dec 23 `a3bffec` | Unified refund activity and dashboard. | State + money `UNION ALL`, not deduplication. [Q14] [D01] [History] |
| Dec 26 `8ed2971` | Cache keys include table; invalidate on MAX(updated_at); serve latest timestamp. | First observed epoch queries Dec 26 20:00 UTC; partial refresh remains possible with autocommit. [Q21] [C-similar] [C-db] [History] |
| Dec 29 `dd0c8fc`; Dec 30 `a576d0d` | Active definitions / restatement policy documented. | Use definitions and policy, but verify current datasets and snapshot values. [C-metrics] [C-policy] [W] [History] |
| Jan 3 `41e3537`; Jan 4 `4bfcbe6`; Jan 5 `5ae1182` | Dashboard SQL removed/moved to Redash; cron retired/Airflow; warehouse loader. | Current access/schedules are migrated; loader dataset/argument defects are visible at the pinned commit. [C-access] [C-cron] [C-dags] [C-backfill] [History] |

## D. Recommendation/ML lineage and effectiveness

### D1. Affinity v1 and v2

V1 joins `cart_items c1,c2` on **session equality** and different product IDs, counts directed pair rows, and uses `pairs × exp(−.05 × age_days_since_last_c1)` over a c1 30-day lower bound. Pairs below three observations get −1. It deletes/repopulates the legacy affinity table. [C-affinity]

V2 adds `conv = count of pair rows whose c2 user has any status-1 header order for c2 product`, then scores `(pairs + 3×conv) × decay × season`, boosts matching nonempty categories by 1.15, and penalizes price ratios outside `[.25,4]` by .7. Its eleven seasonal factors cover Jan–Nov; December now defaults to 1.0. Stored rows use writer version **2.0.1**, while serving configuration **2.0.0** selects the table. [C-affinity2]

Important baked-in assumptions:

- The cart join has no user equality and constrains only c1 time; c2 can be older if a session ID is reused. Repeated cart rows multiply pair counts; removed carts disappear. Thus “pairs_seen” is not unique customers/co-purchase baskets. [C-affinity] [C-affinity2] [C-cart]
- The conversion `EXISTS` has no after-cart/session/horizon condition and reads only the header product. A preexisting purchase can count, while a secondary line purchase can be missed. It is not causal co-cart conversion attribution. [C-affinity2:33–44] [C-order]
- Current product category/list price affect historical affinity; the same-category and price-ratio boosts are heuristics, not learned weights. [C-affinity2:36–57] [C-catalog]
- Latest v2 data contain **3,912 pairs**, **2,964 sentinels**, and **948 qualifying pairs across 449 qualifying base products**. Qualification sparsity helps explain the observed fallback dominance. [Q71] [Q49]

The December 3–5 crashes occurred before a successful v2 refresh, because the old code indexed December into an eleven-element array. The guarded code first emits successful v2 output December 6. No evidence supports calling this a serving-v4 outage; v4 training had not yet begun. [Q43] [Q15] [History: `89666bf`, `3dbe4d7`, `a1946ff`]

### D2. Serving, logs, cache, and fallback

- `intended_version()` reads relative `deploy/flags.env` per request and canonicalizes v2/v4 aliases; missing file defaults v2. Code does not reject unknown versions: any non-2.0.0 nonrandom value takes `model_scores`, including the retired enum if manually configured. Run location/flag validation therefore matters. [C-similar:33–45,92–93]
- Random assignment is stable `sha256(str(uid))[:8] mod 20 == 0`; shuffle is `Random(f"{uid}:{session}:{pid}")`. It chooses five from the first 500 sorted eligible product IDs, rather than all 81,018 products, and does not remove the base product. Observed random item range is 1000894–1004505, with 17 self-recommendation exposures in the queried period. [C-similar:48–50,73–90] [W] [Q40]
- Nonrandom serving fetches up to five `score ≥ 0` recommendations from the latest global `updated_at`, then removes excluded SKUs without topping up. An empty list falls back to latest trending day's top five; missing-score/table-error and cache-hit reasons are logged separately. [C-similar:91–131]
- The fallback path does **not** apply the excluded-SKU filter, and trending has no such cleanup. In the queried December-period item exposures, fallback served excluded SKUs **396,569 times**; direct v2 `model` served denied-brand items **1,066 times**. Merchandising reporting exclusions are not a universal serving contract. [Q40] [C-similar] [C-trending] [C-constants]
- V1 logs keep effective version `1.0.0` even when `rec_source=fallback`; v2 logs can mark effective version `fallback`. Use `rec_source` for historical fallback rate rather than counting only `effective_version='fallback'`. [Q30] [History: `f1217a8`, `df4ed85`]
- `rec_decision_log.items` is comma-separated text. Decisions contain intended/effective/source/reason/arm but no session/request ID, candidate scores, or explicit click. `app_events.rec_served` retains session and list size, not the item list or intended/effective versions. Exact exposure/outcome attribution requires more than a naive timestamp join. [C-manifest] [C-similar] [Q22]

Six-hour in-process caching was introduced December 19, initially keyed only by product and caching empty score lists. December 26 keys it by `(table,pid)`, queries max refresh timestamp, invalidates when that timestamp changes, and caches only nonempty lists. These changes explain historical fallback rows with reason `cache`. [History: `a00f24c`, `8ed2971`] [Q30]

**Remaining inferred race:** producers delete/repopulate under autocommit. The first insert changes the max timestamp and can invalidate caches before the batch is complete; subsequent inserts keep that same timestamp. A partially filled nonempty list can then be cached for six hours without a second epoch change. Likewise, if an empty table has no new max, old caches need not invalidate immediately. Use atomic publication or a completion/epoch record when changing this pipeline; the current epoch mechanism alone is not a batch-completeness guarantee. [C-db:20–26] [C-affinity2:46–60] [C-similar:53–65,94–111]

### D3. Learned v4: actual inputs versus README claims

| Input/feature | Actual implementation | Evidence |
|---|---|---|
| Served-list size | Number of comma-separated items; feature 1 and sole coefficient used to publish candidate scores. All observed random lists have five items. | [C-train:49–56,68–72] [Q54] |
| Base price | Current list price /1000. | [C-train:34,53] |
| Base popularity | All current paid header purchases of base product /100, not as-of exposure. | [C-train:36–37,54] |
| Account age | Exposure time minus `users.created_at`, scaled /60 and capped above at 1; “user first seen,” not UUID enrollment. | [C-train:38,55] [C-catalog] |
| Signup channel | Only boolean `signup_channel == organic`. | [C-train:39,56] |
| Marketing opt-in | Fetched, explicitly omitted from vector pending calibration. | [C-train:40,50–51] |
| Stock | Fetched, not used in vector. | [C-train:35,47–56] |
| Region affinity / device mix | Claimed in README, absent from trainer SQL/vector. | [C-readme:41–43] [C-train] |
| Label | Any later status-1 **header** order for that user, with no upper time limit or purchased-item/session condition. | [C-train:31–44] |

The model fits logistic regression (`random_state=0`, `lbfgs`) when ≥20 rows and both label classes exist. It stores coefficients/intercept and training row count, then writes each qualifying v2 pair as `round(v2_score × (1 + .1 × coefficient_for_list_size), 4)`. It never calls candidate-level `predict_proba`, and does not use user attributes at serving time. If insufficient data/single class, it still logs/stores a registry record and leaves prior scores untouched. [C-train:58–77]

Latest v4 coefficient-for-list-size is **−0.2448375438**, giving multiplier **~0.9755162456**. The 948 latest matched score ratios cluster around that multiplier; across 449 bases, **zero** deterministic pair-rank differences are observed. A positive common scalar preserves score ordering apart from possible rounding ties; these stored outputs provide no demonstrated ranking improvement. [Q15] [Q41] [Q58] [C-train]

Label/feature caveats are direct consequences of the SQL: recent exposures have less follow-up; a user's eventual unrelated purchase can label multiple old exposures positive; mutable current popularity/price/status leak later information into a historical exposure; secondary-item orders are not considered by the header-only label. These are reasons to replace the training/evaluation contract before calling v4 an effective learned recommender. [C-train:31–44] [C-order]

### D4. Logging regression and interpretation of model versions

The December 17 refactor returns early from random serving before decision insertion; the December 19 fix restores insertion. Comparing app completions to decisions gives **109 missing random exposures December 17**, **848 December 18**, **415 December 19**. December 18 has 848 app random serves and zero decisions. The model registry's training count remains **5,798** for December 18/19 runs, consistent with the missing collection period. [History: `30e8907`, `a00f24c`] [Q39] [Q15]

Do not equate four different signals: registry version says a trainer ran; table writer version says who produced rows; intended serving version says the flag; effective/source says what the request actually used. Here v4 registry rows coexist with v2 writer `2.0.1`, intended `2.0.0`, and fallback-dominated serving. [Q15] [Q71] [Q30] [C-flags]

## E. Scheduled jobs and safe pipeline changes

### E1. Pinned schedules and production contracts

Schedule expressions below are literal Airflow DAG values at `5ae1182`; **their timezone is not declared in these wrappers**. Retired cron explicitly called its times local, and 2019 logs reflect Eastern offsets. Confirm deployed Airflow timezone/CWD/environment before assuming the same wall-clock schedule. Every wrapper is one BashOperator, `catchup=False`, with no cross-job dependency or explicit retry setting in the inspected files. [C-cron] [C-dags] [Q02] [Q43]

| Job / Airflow cron | Reads → produces; refresh mode | Failure / replay consequence | Evidence |
|---|---|---|---|
| reconcile / `0 3 * * *` | Header duplicate refs excluding status 5; lexically first 200 → warning logs only. | No automatic repair or advancing cursor; same refs can recur and larger backlogs can be truncated. Current 130 duplicate refs /155 excess headers persist. | [C-reconcile] [Q45] [C-dags] |
| affinity / `30 3 * * *` | 30-day co-cart directed pairs → legacy affinity, full replace; also initializes decision-log schema. | Legacy score refresh stops; current widget no longer reads this score table. Initialization side effect matters in fresh environments. | [C-affinity] [C-similar] [Q21] [C-dags] |
| affinity_v2 / `45 3 * * *` | Co-cart/outcome/current product features → v2 scores, full replace. | Direct v2 recommendations and v4 candidate quality become stale/partial; cache epoch is not batch completion. | [C-affinity2] [C-similar] [C-train] [C-dags] |
| model_train / `15 4 * * *` | Random decisions + current users/products/orders + qualifying v2 → append registry, replace model scores when fit possible. | Current default v2 serving continues; v4-ready scores stale; `model_trained` log alone does not mean scores refreshed. No waiting on v2 DAG completion. | [C-train] [C-flags] [C-dags] |
| price_suggest / `45 4 * * *` | Current catalog + 14-day paid header counts → top 500 +/-5% suggestions, full replace. | Shadow table becomes stale; no identified live price consumer. Median uses the middle row in descending unit order; products can have zero units via LEFT JOIN. | [C-price] [Q21] [C-dags] |
| trending / `15 5 * * *` | 30-day paid header demand, min 5, decay → top 50 for run-date; replace that date only. | Most widget fallback traffic gets old rankings or fails if no table; QA/SKUs/brands can propagate. Tie sort uses `(score,units,pid)` reverse order. | [C-trending] [C-similar] [Q63] [C-dags] |
| fraud_score / `45 5 * * *` | Prior-day status-1 headers + user creation/prior-order signals → append risk rows, update qualifying headers to 6. | Failure leaves new qualifying orders paid; a retry can append duplicate risk observations for unheld paid orders; already held rows are no longer selected. | [C-fraud] [C-dags] |
| daily_report / `0 6 * * *` | Yesterday's Eastern item sales + legacy fallback; exclude 0/2/3, QA, SKUs, brands → append product/day batch. | Historical exec revenue stale/missing; retry appends another version; partial latest version can hide older complete batch. | [C-report] [D07] [D02] [C-dags] |
| kpi_daily / `15 6 * * *` | Trailing 30-day status-1 distinct header buyers → append day/count. | Nightly active rollup stale; exec/board definitions do not consume it; retry adds another row/day. | [C-kpi] [D03] [D07] [C-dags] |
| funnel / `20 6 * * *` | Prior rolling day's carts+header orders → append run-date sessions/users_active. | Funnel stale; retry appends; result labels run day, not yesterday's Eastern calendar day; gaps >120 minutes split sessions, exactly 120 does not. | [C-funnel] [C-dags] |
| monthly_statement / `30 6 1 * *` | Previous Eastern month's status-1 header gross/count and associated payment fees → append statement. | No new publication; retries make more publication rows, and correction/final views do not choose one automatically. | [C-monthly] [Q14] [C-dags] |
| top_sellers / `45 6 * * *` | Yesterday's Eastern status-1 headers → append top 50 by units, ties product ID ascending. | Top-products table stale/missing; this is not the best-sellers dashboard producer; retries duplicate ranks/day. | [C-top] [D09] [C-dags] |
| reorder_forecast / `50 6 * * *` | Top 200 products by 14-day paid header velocity → full replace advisory hints. | Hints stale/partial; no durable forecast-history table; lower velocity mechanically gives larger quantity. | [C-reorder] [C-dags] |
| email_digest / `15 7 * * *` | Top paid-header product over 7 days + weak recipient count → append digest_log. | Can silently return when disabled; code writes/logs a digest but contains no mail-provider send call, so log is not delivery evidence. | [C-digest] [C-dags] |
| intraday_report / `0 12 * * *` | Today's Eastern items before run time → append cumulative product/day batch. | Today's KPI/widget partial data stale/missing; retry duplicates snapshots. Migration omits old cron's separate 17:00 entry. | [C-intraday] [C-cron:28–29] [C-dags] |
| warehouse_backfill / manual `schedule=None` | Manifest's 32 serving tables → sequential Cloud SQL CSV exports and `bq load --replace`. | Partial multi-table snapshots; pinned analytics destination is wrong for observed warehouse; wrapper command lacks required arguments. No view/log creation step in loader. | [C-backfill] [C-manifest] [C-backfill-dag] [W] |

Observed 2019 completions include 107 daily reports/reconciles, 80 legacy affinity refreshes, 26 v2 refreshes plus 3 v2 crashes, 59 trending runs, 55 top-seller runs, 53 funnel runs, 45 KPI runs, 47 intraday runs, 37 shadow-price runs, 35 reorder runs, 28 fraud runs, 17 v4 trainings, 15 digest logs, and 3 statements. These counts cover the supplied log history, not Jan 2020 Airflow run success. [Q27]

**Warehouse-copy details:** the manifest explicitly lists 12 public and 20 analytics tables and their column types. The loader casts timezone-aware timestamps to UTC text with microseconds, UUIDs/booleans/numbers/dates to text, and NULL to `__PGNULL__`, preserving empty strings separately. It sorts each export by its first selected column, exports tables sequentially, and loads each with `--replace` and the declared BigQuery types. The export/load loop has no shared multi-table transaction or snapshot watermark; a failure can leave earlier tables replaced and later tables old. The manifest covers neither the four finance/contactability/refund views nor the three log exports. [C-manifest] [C-backfill:24–75] [W]

### E2. Advisory systems, in detail

**Pricing:** median-ranked top-500 14-day paid header demand determines a +5% price nudge if `units > middle_row_units`, otherwise −5%. Suggestions are based on current catalog prices, written to analytics only, and remain shadow-only after the December 2 hold. A fresh table does not imply prices are being applied. [C-price] [C-catalog] [C-order] [Q21]

**Reorder:** `velocity = header_paid_count/14`; `hint = int(15.6 + 162.4/(velocity+1.8))`. December's refit changed only K from 141.12. Latest observed ranges are velocity **.0714–2.7143/day**, hint **51–102** across 200 products; this differs from the older example range in the caveats document. The formula is decreasing in velocity and omits inventory/lead time/PO context. [C-reorder] [History: `f85cdd2`] [Q48] [C-forecast]

**Fraud:** `core=min(price/3000,1)`; score is capped at 1 after +15% each for a user less than seven days old and ≥3 header orders in the inclusive prior 24h (including the current order). Only recent paid rows are scored; `score > threshold`, strictly, gets held. Current threshold .85; current holds total **40,213.29** across 12 headers. Five held orders below 2600 were released by ad hoc SQL; the batch itself does not reevaluate all old holds. [C-fraud] [C-constants] [Q12] [Q67] [Q29:2019-12-29]

**Digest:** flag priority is environment `ENABLE_DIGEST`, then environment `DIGEST_ON`, then relative `deploy/cron.env ENABLE_DIGEST`, then off. The file currently says 1. A conflicting environment variable can override the file; incorrect working directory can hide it. Recipient eligibility and top product bypass report cleanup. Logs show early digest top products include excluded SKU 1002544/1004856, consistent with that query. [C-digest] [C-cron-env] [Q08:2019-12-17–20] [C-constants]

### E3. Safely modify or extend these pipelines

The following are recommendations grounded in observed implementation behavior, not changes performed during this investigation. [Session] [C-db] [C-dags]

1. **Freeze the metric contract before a rewrite:** preserve Eastern business boundaries, explicit item fallback, the intended status/QA/SKU/brand rules, and finance publication-versus-restatement policy. Regression-check the October bridge and the worked item/snapshot/customer examples rather than expecting all dashboards to converge to one number. [C-time] [C-report] [C-policy] [Q03] [Q32] [Q35] [Q53]
2. **Make publication atomic and versioned:** build a complete replacement/batch before swapping the readable version; add completion metadata so max timestamp is not mistaken for completeness. This addresses autocommit delete/insert gaps, partial latest report batches, and premature cache invalidation. [C-db] [C-affinity2] [C-report] [C-similar]
3. **Define replay behavior per output:** daily/top/KPI/funnel/statement/digest/risk appends need explicit logical-run keys or publication version semantics; full-refresh scores/hints need atomic replacement; statement history should preserve the selected publication while corrections remain separate. The existing schema does not enforce general one-run/day uniqueness. [C-schema] [C-manifest] [C-report] [C-kpi] [C-monthly] [C-fraud] [C-digest]
4. **Make scheduler inputs explicit:** configure timezone, repository CWD, DSN, flags, and runtime business date; restore/decide the 17:00 intraday contract; wire actual dependencies/completion checks for affinity→training and producer→warehouse. Jobs use `now()`/`FAKE_NOW`, not Airflow logical date, and `catchup=False` does not repair missed historical outputs. [C-time] [C-dags] [C-cron] [C-similar] [C-digest]
5. **Repair loader contract before any future rebuild:** route Postgres analytics to actual `novamart_analytics`, pass `--project --instance --staging` (optional database/only), validate manifest coverage/schema and view provisioning separately, and publish one consistent snapshot epoch across tables. Current wrapper and script do not meet those requirements. [C-backfill:47–75] [C-backfill-dag] [C-manifest] [W]
6. **Retire legacy affinity only after consumer/initialization review:** current widget/read-family evidence supports no current legacy score reads after Dec 6, but the job also creates the decision-log table, both affinity DAGs remain scheduled, and absence of a read in the supplied finite logs is not proof about every external consumer. [Q21] [C-affinity] [C-similar] [C-dags] [C-lineage]
7. **Do not use the manual discount helper as a financial replay without correcting the cap:** `DISCOUNT_CAP=.25` but helper default `.40`, and `rerun_kpis.py` omits the argument. Its default retains 60% rather than the approved-cap 75%; it currently has an empty manually populated input and only prints. There is no evidence that live daily/statement jobs apply this helper. [C-constants] [C-discount] [C-rerun] [C-report] [C-monthly]
8. **Verify on read-only reconcilations before a future controlled deployment:** compare header/line/payment totals, report-batch completeness, source freshness, score coverage, actual source/version mix, and app-versus-decision log counts. The supplied CI smoke script truncates a scratch database and exercises only a basic view/cart/order plus three jobs; it is not comprehensive analytics/ML correctness evidence and was not executed here. [Q31] [Q45] [Q34] [Q71] [Q30] [Q39] [C-ci] [Session]

## F. Data catalog and evidence recipes

### F1. App tables (warehouse `novamart`)

| Table | Grain / joins / important semantics | Evidence |
|---|---|---|
| users | Numeric ID; mutable email; first-seen creation and deterministic profile columns. | [C-schema] [C-catalog] [C-users] [C-onboarding] |
| accounts | UUID registration record with copied email/creation time; not used as order ID. | [C-account] [W] |
| account_map | Numeric uid ↔ UUID account link with linked time; no declared unique uid constraint. | [C-account] [C-manifest] |
| products | Numeric ID; current metadata/list/cost/stock; feeds update existing rows. | [C-catalog] [C-manifest] |
| cart_items | Individual cart-add rows; user/product/session/time; current state can be deleted. | [C-cart] [C-schema] |
| orders | Header/basket ID; original numeric user/product/ref/time, accumulated price, current status/update time. | [C-order] [C-schema] |
| order_lines | Explicit per-item callbacks; order/product/price/session/ref/time; ref unique index is created at runtime. | [C-order] [C-manifest] |
| payments | Payment/ref transaction or negative refund; order FK; collected gross/fee/net/time; legacy refs nullable. | [C-schema] [C-order] [C-gateway] [Q60] |
| report_rows | Product/business-date/run-timestamp batch snapshot, append-only. | [C-report] |
| report_rows_intraday | Product/current-business-date/run timestamp, cumulative partial snapshot, append-only. | [C-intraday] |
| statements | Month/run timestamp publication; gross/fee/net/count, append-only without month uniqueness. | [C-schema] [C-monthly] |
| top_products | Rank/product/units/report_date/run timestamp; append-only paid-header ranking. | [C-top] |

`schema.sql` declares only the older seven app tables and analytics schema; runtime DDL, historical backfills, and the manifest contain the later tables/columns. Inspecting just the setup schema would miss lines, account links, payment refs, intraday data, score tables, and views. [C-schema] [C-manifest] [Q29] [W]

### F2. Analytics tables/views (warehouse `novamart_analytics`)

| Object | Purpose / producer / consumer | Evidence |
|---|---|---|
| test_users | QA numeric-ID exclusion; seeded 424242 by historical SQL; used in daily/board cleanup. | [Q29] [C-report] [D03] |
| blank_brand_products | Captured blank-brand diagnostics with heuristic cause, units/revenue/order timestamps; not continuously refreshed. | [Q29] [Q44] |
| category_names | Base code/display-group/effective-date mappings; historical prefix backfill. | [Q29] [D06] [Q47] |
| category_name_history | Effective reclassification rows, precedence over base on date ties. | [D06] [Q18] |
| price_history | Feed list price / product / valid_from append; not a customer charged-price ledger. | [C-catalog] [Q21] |
| statement_overrides | Month replacement gross/fee/net/count/publication time/note; October correction. | [Q05] [Q14] |
| statement_corrections | Month/delta/reason audit record; no direct final-view arithmetic. | [Q06] [Q14] |
| chargebacks | Booked order-ID amount/reported_at; final view joins original order month. | [Q07] [Q14] |
| statements_corrected (view) | Raw statements left-joined to month overrides; no latest-publication selection. | [Q14] [Q04] |
| statements_final (view) | Corrected gross/net minus month-grouped booked chargebacks; fee/count unchanged. | [Q14] [Q03] |
| refunds_unified (view) | Current cancelled/refunded headers + negative payment events, `UNION ALL`. | [Q14] [Q13] |
| contactable_users (view) | Opt-in + regex + domain eligibility; zero on observed snapshot. | [Q14] [Q17] |
| kpi_daily | Appended trailing paid-buyer rollup. | [C-kpi] [Q34] |
| daily_funnel | Appended run-date inactivity-session/cart-order active counts. | [C-funnel] [Q34] |
| product_affinity | Legacy directed co-cart scores, sentinel graduation, nightly replace. | [C-affinity] |
| product_affinity_v2 | Directed conversion-weighted scores with writer version, nightly replace. | [C-affinity2] [Q71] |
| rec_decision_log | Exposure timestamp/user/base/items/intended/effective/source/reason/arm; historical missing-random period. | [C-manifest] [Q39] [Q30] |
| model_registry | Appended version/trained_at/coefficient JSON/train_rows; does not establish deployed inference. | [C-train] [Q15] |
| model_scores | Nightly v2 candidate scores scaled by learned global coefficient; replace only on successful fit condition. | [C-train] [Q58] |
| trending_daily | Date/rank/product/score/units/run time; replace same run-date, retain other dates. | [C-trending] |
| order_risk | Appended order-level score/core/new-account/high-velocity/time; no fraud truth label. | [C-fraud] |
| price_suggestions | Full-replace shadow product/current/suggested price/demand/time output. | [C-price] |
| reorder_hints | Full-replace product/velocity/hint/time advisory output. | [C-reorder] |
| digest_log | Appended time/recipient-count/top-product; no provider delivery receipt. | [C-digest] |

### F3. Logs and historical query reconstruction

`db_queries.textPayload` carries raw lines such as `2019-... [job] statement: SELECT ... -- params: (...)`. Tags observed include app/job and engineer/backfill actors. `app_events.jsonPayload` has events such as order-created/appended/replayed, rec-served, email/account operations, refunds, and statement warnings. `job_runs.jsonPayload` has output counts/runtime/window/threshold fields plus v2 crash stack traces. [Q09] [Q10] [Q21] [Q22] [Q27] [Q43]

`novamart_logs.db_queries_normalized` is a **derived Postgres-log compatibility view**, not authentic BigQuery job-performance history. It synthesizes job IDs/user email/statement type/referenced-table guesses, sets timestamps all to raw log time, hardcodes state DONE/error NULL, and has NULL slot/byte metrics. Because `db.execute` logs before execution, even attempted queries with wrong columns can appear “DONE” through this view. Use raw logs + results/job-completion evidence to validate a claim. [Q61] [C-db] [Q29:queries referring to `total_amount`, `charged_at`, `source`/`reason`]

Read-only recipes used in this investigation:

```sql
-- Historical SQL family and first/last attempted use; see Q21.
SELECT REGEXP_EXTRACT(textPayload, r'\[(.*?)\]') AS actor,
       REGEXP_EXTRACT(textPayload, r'statement: (.*?)(?: -- params:|$)') AS sql,
       COUNT(*) AS n, MIN(timestamp) AS first_at, MAX(timestamp) AS last_at
FROM `novamart-warehouse.novamart_logs.db_queries`
GROUP BY 1, 2;

-- Detect run errors; full observed history is saved in Q08/Q43.
SELECT timestamp, jsonPayload
FROM `novamart-warehouse.novamart_logs.job_runs`
WHERE severity = 'ERROR'
ORDER BY timestamp;

-- Inspect actual view contracts; see Q14.
SELECT table_name, view_definition
FROM `novamart-warehouse.novamart_analytics.INFORMATION_SCHEMA.VIEWS`;
```

The emulator's INFORMATION_SCHEMA serialization strips some SQL literal quoting in returned view text. The executed views' results and the historical original `CREATE OR REPLACE VIEW` text in raw logs provide the usable semantic evidence; do not paste that serialized text verbatim as deployable DDL. [Q14] [Q61] [Q29] [Q03] [Q13] [Q17]

### F4. Remaining evidence limits

- No December/month-after-November published statement is present, so an approved December result cannot be supplied from a missing publication. Current December paid-header gross **552,328.93** is only a provisional status-based calculation; 12 held headers add **40,213.29** under broader status policies. [Q01] [Q12] [Q31]
- The warehouse loader copies table CSVs, not views/log exports, and its pinned destination for analytics is `analytics`, whereas the accessible dataset is `novamart_analytics`. The observable snapshot therefore cannot be attributed to a successful unmodified invocation of this pinned loader alone. No later branch code was used to resolve this inconsistency. [C-backfill] [C-manifest] [W] [Session]
- No deployed Airflow configuration/UI or successful Jan 2020 job log was available through the specified inspected surfaces; schedule timezone and runtime arguments/environment remain deployment questions, not established production facts. [C-dags] [C-backfill-dag] [Q27] [C-access]
- The old affinity table's last observed app reads precede v2 dispatch; later logs show v2 reads. This supports current widget lineage, but cannot rule out a consumer outside this finite repository/log/dashboard estate. [Q21] [C-similar] [C-lineage]
- Registry fit, `digest_sent`, shadow table refresh, and backup-overlap commit wording are not respectively evidence of deployed model lift, provider delivery, live dynamic prices, or measured reconcile slowdown. [C-train] [C-digest] [C-price] [Q43] [History: `388370b`]

## G. Evidence index and verification scope

### G1. Repository citations

All `C-*` links below refer to the pinned repository at **`5ae11821806a396aac10115e03863b8c68c1bfcc`**, with relevant line ranges in the citation text. Historical changes use their individual ancestor commit hashes, documented in `git_history.txt` and selected full diffs in `git_diffs.txt`. Validation confirmed the required eight headings, all local reference targets, the October/widget arithmetic, the random-log gap, exact agreement of all nine Redash SQL contracts with pre-migration ancestor SQL, one Markdown deliverable, and a clean repository at the pinned HEAD. [Session] [History] [Diffs] [Validation]

| Citation | File / relevant lines at pinned commit |
|---|---|
| [C-policy] | `docs/restatement_policy.md`, especially 7–16,20–34,76–113. |
| [C-metrics] | `docs/metrics_definitions.md`, three customer definitions. |
| [C-dashboard-notes] | `docs/dashboard_notes.md`, dashboard exclusions/grain/ranking. |
| [C-access] | `docs/data-access.md`, migration/data locations, including stale warehouse analytics name. |
| [C-lineage] | `docs/affinity_lineage.md`, legacy/v2 lineage; confirm against current flags/queries. |
| [C-forecast] | `docs/forecast_caveats.md`, advisory status and heuristic assumptions. |
| [C-readme] | `README.md`, especially stale trending window and overstated v4 feature list, 33–43. |
| [C-order] | `novamart/routers/orders.py`, 14–111 callbacks; 114–155 state endpoints. |
| [C-gateway] | `novamart/routers/payments_webhook.py`, 11–20 negative-money webhook. |
| [C-catalog] | `novamart/routers/catalog.py`, 13–36 inserts/upsert/history; 58–98 first-sight/feed. |
| [C-cart] | `novamart/routers/carts.py`, additions/removal. |
| [C-account] | `novamart/routers/accounts.py`, 23–49 account/link insertion. |
| [C-users] | `novamart/routers/users.py`, mutable email/audit. |
| [C-brand-api] | `novamart/routers/reports.py`, old monthly header brand contract. |
| [C-onboarding] | `novamart/onboarding.py`, deterministic synthesized attributes. |
| [C-similar] | `novamart/routers/similar.py`, complete serving/random/cache/logging path. |
| [C-constants] | `novamart/constants.py`, fees/exclusions/statuses/thresholds. |
| [C-flags] / [C-cron-env] | `deploy/flags.env:4` / `deploy/cron.env:3`. |
| [C-report] / [C-intraday] | `novamart/jobs/daily_report.py` / `intraday_report.py`, aggregation/batch writes. |
| [C-monthly] / [C-time] | `novamart/jobs/monthly_statement.py` / `timeutil.py`, month/day/fee semantics. |
| [C-reconcile] / [C-top] | `novamart/jobs/reconcile.py` / `top_sellers.py`. |
| [C-kpi] / [C-funnel] | `novamart/jobs/kpi_daily.py` / `funnel.py`. |
| [C-affinity] / [C-affinity2] | `novamart/jobs/affinity.py` / `affinity_v2.py`. |
| [C-train] / [C-fraud] | `novamart/jobs/model_train.py` / `fraud_score.py`. |
| [C-trending] / [C-price] / [C-reorder] | `novamart/jobs/trending.py` / `price_suggest.py` / `reorder_forecast.py`. |
| [C-digest] / [C-discount] / [C-rerun] | `novamart/jobs/email_digest.py` / `discounts.py` / `scripts/rerun_kpis.py`. |
| [C-backfill] / [C-manifest] | `novamart/jobs/warehouse_backfill.py` / `warehouse_manifest.json`. |
| [C-backfill-dag] / [C-dags] / [C-cron] | `airflow/dags/warehouse_backfill_dag.py` / all job wrappers / retired `crontab.txt`. |
| [C-app] / [C-db] / [C-log] / [C-ci] | `novamart/app.py` / `db.py` / `logutil.py` / `ci/run_ci.py`. |

### G2. Executed warehouse queries

Each `Qxx` reference links to a saved JSON containing **the exact SELECT SQL, returned schema, total rows, and returned values**. They were executed on `novamart-warehouse` through the provided credential-free emulator. Timestamp API values in raw results are microseconds since epoch; narrative dates are derived from those values or explicit JSON log timestamps. [Session] [Q02] [Q11]

| Query group | Evidence covered |
|---|---|
| [Q01], [Q03]–[Q07], [Q14] | Raw/corrected/final statements, overrides/audit rows/chargebacks, actual view contracts. |
| [Q02], [Q08]–[Q12], [Q21]–[Q23], [Q27]–[Q30], [Q43], [Q46], [Q61], [Q64], [Q70] | Log shapes, full job history, freshness/statuses, historical SQL families/actors/manual backfills, app event families, crashes/warnings/refund operations. |
| [Q13], [Q20], [Q26], [Q31], [Q38], [Q45], [Q60], [Q62], [Q68], [Q69] | Refund activity, negative money, safe header/payment bridges, line/ref integrity, fee-grain/rollout comparisons. |
| [Q17]–[Q19], [Q24], [Q25], [Q32], [Q35]–[Q37], [Q44], [Q47], [Q50]–[Q53], [Q55], [Q59] | Contactability/identity/product data, registered prehistory, customer definitions, blank brands/taxonomy, explicit-clock dashboard reproductions. |
| [Q33], [Q34], [Q56], [Q65], [Q66] | Report versions/freshness, DST gap, repeated intraday batches and legacy scan-cap comparison. |
| [Q15], [Q16], [Q30], [Q39]–[Q42], [Q48], [Q49], [Q54], [Q57], [Q58], [Q63], [Q67], [Q71] | Model registry/decision evolution, missing random logging, serving contamination, v4 scaling/ranks, risk/reorder outputs, descriptive outcomes/coverage. |

### G3. Redash and investigation evidence

- `redash_queries_list.json`, query-detail JSONs, and `redash_query_1.sql`…`redash_query_9.sql` preserve retrieved contracts; API-key fields in saved JSON were redacted. `redash_data_sources.json` establishes datasource type. [Redash-queries] [Redash-source] [D01–D09]
- `redash_dashboards_list.json` establishes names/IDs; `redash_dashboards_1.json`…`redash_dashboards_9.json` record the HTTP 500 detail-access limitation. There were no dashboard/query refreshes or mutations. [Redash-dashboards] [Redash-errors] [Session]
- `warehouse_inventory.json` preserves datasets' observed tables/views/schema/metadata; the collector scripts issue only GETs and guarded SELECT/WITH queries. No repository code, warehouse data, or dashboard content was modified; output creation was limited to this UUID directory. [W] [Collector] [Session]
- The delivered Markdown is the single narrative output; raw evidence/collection utilities are supporting files in the same directory. No external company knowledge, later branch fixes, destructive CI, serving jobs, or write queries were used. [Session] [Collector] [Investigation] [Deep-queries]

[Session]: session.json
[History]: git_history.txt
[Diffs]: git_diffs.txt
[W]: warehouse_inventory.json
[Collector]: collect_evidence.py
[Investigation]: investigate.py
[Deep-queries]: deep_queries.py
[Redash-queries]: redash_queries_list.json
[Redash-dashboards]: redash_dashboards_list.json
[Redash-source]: redash_data_sources.json
[Redash-errors]: redash_dashboards_9.json
[D01]: redash_query_1.sql
[D02]: redash_query_2.sql
[D03]: redash_query_3.sql
[D04]: redash_query_4.sql
[D05]: redash_query_5.sql
[D06]: redash_query_6.sql
[D07]: redash_query_7.sql
[D08]: redash_query_8.sql
[D09]: redash_query_9.sql
[C-policy]: ../novamart/docs/restatement_policy.md "5ae1182"
[C-metrics]: ../novamart/docs/metrics_definitions.md "5ae1182"
[C-dashboard-notes]: ../novamart/docs/dashboard_notes.md "5ae1182"
[C-access]: ../novamart/docs/data-access.md "5ae1182"
[C-lineage]: ../novamart/docs/affinity_lineage.md "5ae1182"
[C-forecast]: ../novamart/docs/forecast_caveats.md "5ae1182"
[C-readme]: ../novamart/README.md "5ae1182"
[C-schema]: ../novamart/schema.sql "5ae1182"
[C-order]: ../novamart/novamart/routers/orders.py "5ae1182"
[C-gateway]: ../novamart/novamart/routers/payments_webhook.py "5ae1182"
[C-catalog]: ../novamart/novamart/routers/catalog.py "5ae1182"
[C-cart]: ../novamart/novamart/routers/carts.py "5ae1182"
[C-account]: ../novamart/novamart/routers/accounts.py "5ae1182"
[C-users]: ../novamart/novamart/routers/users.py "5ae1182"
[C-brand-api]: ../novamart/novamart/routers/reports.py "5ae1182"
[C-onboarding]: ../novamart/novamart/onboarding.py "5ae1182"
[C-similar]: ../novamart/novamart/routers/similar.py "5ae1182"
[C-constants]: ../novamart/novamart/constants.py "5ae1182"
[C-flags]: ../novamart/deploy/flags.env "5ae1182"
[C-cron-env]: ../novamart/deploy/cron.env "5ae1182"
[C-report]: ../novamart/novamart/jobs/daily_report.py "5ae1182"
[C-intraday]: ../novamart/novamart/jobs/intraday_report.py "5ae1182"
[C-monthly]: ../novamart/novamart/jobs/monthly_statement.py "5ae1182"
[C-time]: ../novamart/novamart/jobs/timeutil.py "5ae1182"
[C-reconcile]: ../novamart/novamart/jobs/reconcile.py "5ae1182"
[C-top]: ../novamart/novamart/jobs/top_sellers.py "5ae1182"
[C-kpi]: ../novamart/novamart/jobs/kpi_daily.py "5ae1182"
[C-funnel]: ../novamart/novamart/jobs/funnel.py "5ae1182"
[C-affinity]: ../novamart/novamart/jobs/affinity.py "5ae1182"
[C-affinity2]: ../novamart/novamart/jobs/affinity_v2.py "5ae1182"
[C-train]: ../novamart/novamart/jobs/model_train.py "5ae1182"
[C-fraud]: ../novamart/novamart/jobs/fraud_score.py "5ae1182"
[C-trending]: ../novamart/novamart/jobs/trending.py "5ae1182"
[C-price]: ../novamart/novamart/jobs/price_suggest.py "5ae1182"
[C-reorder]: ../novamart/novamart/jobs/reorder_forecast.py "5ae1182"
[C-digest]: ../novamart/novamart/jobs/email_digest.py "5ae1182"
[C-discount]: ../novamart/novamart/jobs/discounts.py "5ae1182"
[C-rerun]: ../novamart/scripts/rerun_kpis.py "5ae1182"
[C-backfill]: ../novamart/novamart/jobs/warehouse_backfill.py "5ae1182"
[C-manifest]: ../novamart/novamart/jobs/warehouse_manifest.json "5ae1182"
[C-backfill-dag]: ../novamart/airflow/dags/warehouse_backfill_dag.py "5ae1182"
[C-dags]: ../novamart/airflow/dags/ "5ae1182"
[C-cron]: ../novamart/crontab.txt "5ae1182"
[C-app]: ../novamart/novamart/app.py "5ae1182"
[C-db]: ../novamart/novamart/db.py "5ae1182"
[C-log]: ../novamart/novamart/logutil.py "5ae1182"
[C-ci]: ../novamart/ci/run_ci.py "5ae1182"
[Q01]: Q01_statements.json
[Q02]: Q02_log_samples.json
[Q03]: Q03_final.json
[Q04]: Q04_corrected.json
[Q05]: Q05_overrides.json
[Q06]: Q06_corrections.json
[Q07]: Q07_chargebacks.json
[Q08]: Q08_jobs.json
[Q09]: Q09_log_shapes.json
[Q10]: Q10_app_shapes.json
[Q11]: Q11_data_clock.json
[Q12]: Q12_statuses.json
[Q13]: Q13_refunds.json
[Q14]: Q14_views.json
[Q15]: Q15_model_registry.json
[Q16]: Q16_rec_daily.json
[Q17]: Q17_contactable.json
[Q18]: Q18_mapping.json
[Q19]: Q19_registered.json
[Q20]: Q20_negative_payments.json
[Q21]: Q21_db_families.json
[Q22]: Q22_app_types.json
[Q23]: Q23_db_roles.json
[Q24]: Q24_user_segments.json
[Q25]: Q25_line_grain.json
[Q26]: Q26_payments_by_order_month.json
[Q27]: Q27_job_types.json
[Q28]: Q28_finance_events.json
[Q29]: Q29_manual_queries.json
[Q30]: Q30_rec_summary.json
[Q31]: Q31_month_bridge.json
[Q32]: Q32_items.json
[Q33]: Q33_report_versions.json
[Q34]: Q34_freshness.json
[Q35]: Q35_actives.json
[Q36]: Q36_email_domains.json
[Q37]: Q37_registered_history.json
[Q38]: Q38_refund_overlap.json
[Q39]: Q39_rec_logging.json
[Q40]: Q40_rec_item_leaks.json
[Q41]: Q41_score_scaling.json
[Q42]: Q42_risk.json
[Q43]: Q43_ops_events.json
[Q44]: Q44_blank_brand.json
[Q45]: Q45_order_anomalies.json
[Q46]: Q46_finance_warnings.json
[Q47]: Q47_category_dates.json
[Q48]: Q48_reorder_range.json
[Q49]: Q49_rec_coverage.json
[Q50]: Q50_best_sellers.json
[Q51]: Q51_brand_revenue.json
[Q52]: Q52_dashboard_days.json
[Q53]: Q53_widget_bridge.json
[Q54]: Q54_training_list_size.json
[Q55]: Q55_qa.json
[Q56]: Q56_dst_gap.json
[Q57]: Q57_rec_outcomes.json
[Q58]: Q58_score_rank_agreement.json
[Q59]: Q59_category_revenue.json
[Q60]: Q60_pay_ref_grain.json
[Q61]: Q61_log_view.json
[Q62]: Q62_fee_november.json
[Q63]: Q63_rec_rates.json
[Q64]: Q64_refund_events.json
[Q65]: Q65_intraday_versions.json
[Q66]: Q66_report_scan_source.json
[Q67]: Q67_released_holds.json
[Q68]: Q68_fee_deltas.json
[Q69]: Q69_fee_transition.json
[Q70]: Q70_job_scan_logs.json
[Q71]: Q71_affinity_quality.json
[Validation]: validation.json
[D01–D09]: redash_queries_list.json
[Q01–Q71]: .
[C-access:9]: ../novamart/docs/data-access.md "5ae1182 line 9"
[C-affinity2:33–44]: ../novamart/novamart/jobs/affinity_v2.py "5ae1182 lines 33–44"
[C-affinity2:36–57]: ../novamart/novamart/jobs/affinity_v2.py "5ae1182 lines 36–57"
[C-affinity2:46–60]: ../novamart/novamart/jobs/affinity_v2.py "5ae1182 lines 46–60"
[C-app:7–23]: ../novamart/novamart/app.py "5ae1182 lines 7–23"
[C-backfill:47–75]: ../novamart/novamart/jobs/warehouse_backfill.py "5ae1182 lines 47–75"
[C-backfill:60]: ../novamart/novamart/jobs/warehouse_backfill.py "5ae1182 line 60"
[C-backfill:24–75]: ../novamart/novamart/jobs/warehouse_backfill.py "5ae1182 lines 24–75"
[C-cart:11–19]: ../novamart/novamart/routers/carts.py "5ae1182 lines 11–19"
[C-catalog:35–36,51–55]: ../novamart/novamart/routers/catalog.py "5ae1182 lines 35–36,51–55"
[C-catalog:58–80]: ../novamart/novamart/routers/catalog.py "5ae1182 lines 58–80"
[C-catalog:84–98]: ../novamart/novamart/routers/catalog.py "5ae1182 lines 84–98"
[C-cron:28–29]: ../novamart/crontab.txt "5ae1182 lines 28–29"
[C-dashboard-notes:46–51]: ../novamart/docs/dashboard_notes.md "5ae1182 lines 46–51"
[C-db:20–26]: ../novamart/novamart/db.py "5ae1182 lines 20–26"
[C-digest:50–55]: ../novamart/novamart/jobs/email_digest.py "5ae1182 lines 50–55"
[C-intraday:71–77]: ../novamart/novamart/jobs/intraday_report.py "5ae1182 lines 71–77"
[C-monthly:13,36–42]: ../novamart/novamart/jobs/monthly_statement.py "5ae1182 lines 13,36–42"
[C-monthly:26–35]: ../novamart/novamart/jobs/monthly_statement.py "5ae1182 lines 26–35"
[C-monthly:26–43]: ../novamart/novamart/jobs/monthly_statement.py "5ae1182 lines 26–43"
[C-order:114–133]: ../novamart/novamart/routers/orders.py "5ae1182 lines 114–133"
[C-order:114–155]: ../novamart/novamart/routers/orders.py "5ae1182 lines 114–155"
[C-order:136–155]: ../novamart/novamart/routers/orders.py "5ae1182 lines 136–155"
[C-order:17–19]: ../novamart/novamart/routers/orders.py "5ae1182 lines 17–19"
[C-order:19]: ../novamart/novamart/routers/orders.py "5ae1182 line 19"
[C-order:23–110]: ../novamart/novamart/routers/orders.py "5ae1182 lines 23–110"
[C-readme:41–43]: ../novamart/README.md "5ae1182 lines 41–43"
[C-report:62–68]: ../novamart/novamart/jobs/daily_report.py "5ae1182 lines 62–68"
[C-similar:33–45,92–93]: ../novamart/novamart/routers/similar.py "5ae1182 lines 33–45,92–93"
[C-similar:48–50,73–90]: ../novamart/novamart/routers/similar.py "5ae1182 lines 48–50,73–90"
[C-similar:53–65,94–111]: ../novamart/novamart/routers/similar.py "5ae1182 lines 53–65,94–111"
[C-similar:91–131]: ../novamart/novamart/routers/similar.py "5ae1182 lines 91–131"
[C-train:31–44]: ../novamart/novamart/jobs/model_train.py "5ae1182 lines 31–44"
[C-train:34,53]: ../novamart/novamart/jobs/model_train.py "5ae1182 lines 34,53"
[C-train:35,47–56]: ../novamart/novamart/jobs/model_train.py "5ae1182 lines 35,47–56"
[C-train:36–37,54]: ../novamart/novamart/jobs/model_train.py "5ae1182 lines 36–37,54"
[C-train:38,55]: ../novamart/novamart/jobs/model_train.py "5ae1182 lines 38,55"
[C-train:39,56]: ../novamart/novamart/jobs/model_train.py "5ae1182 lines 39,56"
[C-train:40,50–51]: ../novamart/novamart/jobs/model_train.py "5ae1182 lines 40,50–51"
[C-train:49–56,68–72]: ../novamart/novamart/jobs/model_train.py "5ae1182 lines 49–56,68–72"
[C-train:58–77]: ../novamart/novamart/jobs/model_train.py "5ae1182 lines 58–77"
[History: `11c0a42`]: git_diffs.txt
[History: `1233af8`]: git_diffs.txt
[History: `1233af8`, `33054cd`]: git_diffs.txt
[History: `12e1c68`, `a92c96d`]: git_diffs.txt
[History: `30e8907`, `a00f24c`]: git_diffs.txt
[History: `33054cd`]: git_diffs.txt
[History: `388370b`]: git_history.txt
[History: `4a58d17`]: git_diffs.txt
[History: `89666bf`, `3dbe4d7`, `a1946ff`]: git_diffs.txt
[History: `92596dc`, `5d1300d`]: git_diffs.txt
[History: `a00f24c`]: git_diffs.txt
[History: `a00f24c`, `8ed2971`]: git_diffs.txt
[History: `a92c96d^`, `a92c96d`]: git_diffs.txt
[History: `b975479`]: git_diffs.txt
[History: `ba1fbfa`, `1169e40`]: git_diffs.txt
[History: `cca9b0d`]: git_history.txt
[History: `d213f6e`, `795d273`]: git_history.txt
[History: `ea0e97b`]: git_history.txt
[History: `f1217a8`]: git_diffs.txt
[History: `f1217a8`, `df4ed85`]: git_diffs.txt
[History: `f1217a8`, `df4ed85`, `a1946ff`]: git_diffs.txt
[History: `f85cdd2`]: git_diffs.txt
[History: commits `41e3537`, `4bfcbe6`, `5ae1182`]: git_diffs.txt
[Q08:2019-12-17–20]: Q08_jobs.json
[Q29:2019-10-21]: Q29_manual_queries.json
[Q29:2019-11-02]: Q29_manual_queries.json
[Q29:2019-11-27]: Q29_manual_queries.json
[Q29:2019-12-09]: Q29_manual_queries.json
[Q29:2019-12-12]: Q29_manual_queries.json
[Q29:2019-12-12, 2019-12-29]: Q29_manual_queries.json
[Q29:2019-12-23]: Q29_manual_queries.json
[Q29:2019-12-29]: Q29_manual_queries.json
[Q29:November fee audit]: Q29_manual_queries.json
[Q29:queries referring to `total_amount`, `charged_at`, `source`/`reason`]: Q29_manual_queries.json
