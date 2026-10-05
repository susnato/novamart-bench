# Novamart Tribal Knowledge Document

*Run `7e2e46b6-6d34-46d8-90a8-36724dbf7843`, started 2026-10-05 16:42:34 UTC. Pillars 1-8 below; supporting detail, evidence key and run notes are in Appendices A-G. Citation tags: `[c:hash]` commit, `[f:path:line]` file at `5ae1182`, `[bq:dataset.table]` warehouse object, `[Qnn]` numbered query in `intermediate/evidence_outputs.txt`, `[rd:...]` Redash, `[doc:file]` repo doc, `[git:old-sql]` dashboard SQL from `41e3537^` (full key: Appendix G).*

---

# 1. Summary

**What novamart is.** A marketplace backend (FastAPI + Postgres) whose numbers are produced by ~16 nightly/monthly batch jobs and a set of hand-written dashboard SQL files that were moved to Redash on 2020-01-03 [f:README.md][c:41e3537][c:4bfcbe6]. Two engineers (Maya Iyer, Dev Kapoor; 54 commits each) plus a "Novamart Platform" identity (4 migration commits) built it in ~15 weeks [git log].

**The single most important thing to know: there is no single "revenue" number.** At least seven different revenue-like numbers exist (plus dashboard variants) and they disagree by up to ~7% for the same month. For October 2019 [Q02, Q03a, Q03c, Q07, Q08, Q10]:

| Definition | Oct-2019 gross | Source of truth for |
|---|---|---|
| Statement as published 2019-11-01 | **1,230,332.43** (net 1,194,652.79) | "what the November board deck said" `[bq:novamart.statements]` |
| Statement + fee override | gross 1,230,332.43, net 1,194,652.93 | fee-bug fix only `[bq:analytics.statements_corrected]` |
| `statements_final` (+ chargebacks) | **1,226,764.86** (net **1,191,085.36**) | "current restated finance number" per `[doc:docs/restatement_policy.md]` |
| Paid orders today (`orders.status=1`) | **1,206,337.32** (3,695 orders) | operational truth about payment state |
| ... minus replayed-callback duplicates | **1,147,509.08** | closest to "real" cash-backed revenue |
| `report_rows` (daily_report, latest versions) | 1,201,082.08 | exec KPI dashboard feed |
| `payments` positive gross | 1,230,332.43 | money-in ledger (never reduced by order refunds) |

*Why they differ (October):* (1) the statement was frozen on 2019-11-01 and **never re-cut for 43 cancellations ($10,748.42) and 27 refunds ($13,246.69)** processed later; (2) **151 duplicate orders worth $58,828.24** came from payment-gateway callback replays before the idempotency fix [c:b676969] and are still counted as paid; (3) the "restated" `statements_final` only subtracts 3 booked chargebacks ($3,567.57) - and those 3 orders are *also* already cancelled/refunded, so combining "status=1" with chargebacks double-counts [Q04]; (4) daily-report snapshots were never back-filled when filters (lucente, test SKUs, jetem, QA user) were added later [Q09].

**Other headline findings (each verified in data):**

1. **Dashboards run on the Postgres serving replica (`estate-pg`), not BigQuery**, use `now()`-relative windows, and are single-table widgets with no schedule or cache [rd:data_sources/1][rd:queries 1-9]. Against frozen 2019 data, "last 7/30 days" widgets evaluated in 2026 would be empty; replayed as-of 2019-12-31 they work (Q26).
2. **"Active customers" has 3 incompatible definitions** and the "most cleaned-up" one (board deck) returns **0** on this data because every user email is `@example.com` or `@gmail.example` and the filter excludes both [Q18, Q21, doc:docs/metrics_definitions.md]. Nightly rollup said 1,152 on 2019-12-31; the dashboard counts 47-75 *per day* [Q22, Q63].
3. **Customer attributes are synthetic.** `users` rows are created on first sight from any product view; region/channel/device/age/opt-in/vendor/cost/stock are hashes of the id [f:novamart/onboarding.py][f:novamart/routers/catalog.py:58-66]. Channel buy-rates are flat (~10%) [Q25]. `contactable_users` has **0 rows** [Q19].
4. **The similar-products widget mostly serves a trending fallback (80% of all logged responses), and 99% of those responses contain the internal QA test SKU 1004856** because the fallback path skips the `EXCLUDED_SKUS` filter [Q33, Q42, f:novamart/routers/similar.py:115-123 (fallback, unfiltered) vs :98 and :109 (filtered paths)].
5. **The "learned" rec model v4 is cosmetic and was never served**: `model_scores` is a constant 0.9755 multiple of `product_affinity_v2` (identical ranking), the first feature is constant (always 5 items), and `REC_MODEL_VERSION=2.0.0` so nothing reads `model_scores` [Q35, Q37, Q39, f:deploy/flags.env:4, Q55].
6. **The "unbiased" random arm draws only from the 500 lowest product IDs** (0.6% of the 81,018-product catalog) [Q38, f:novamart/routers/similar.py:77].
7. **Affinity v2 coverage is thin**: only 449 base products have any servable score (948 of 3,912 rows; the rest are the -1 sentinel) while 13,315 distinct base products were requested 2019-12-27..31; 76% of non-random requests fall back (80% across the v2 era) [Q36a, Q73, Q67, Q72].
8. **Fraud holds**: 12 orders / $40,213.29 are stuck in status 6: excluded from statements, `kpi_daily`, top_sellers and trending (all `status=1`) but *included* by the daily report, the status-agnostic dashboards and the board-actives query; 5 more were released by a hand-run `UPDATE ... price < 2600` that is not in the repo [Q57, Q60, Q14].
9. **Refunds**: the refunds dashboard counts cancellations as refunds, buckets by status-change month, and **triple-counts** 3 gateway refunds re-delivered weekly (9 rows, $1,843.59 vs $614.53 real); those orders stay `status=1` and still count as revenue [Q11, Q12].
10. **Operational outage signal**: 2019-11-15 has 2,136 cart adds / 1,175 sessions but **0 orders**; Nov 16-17 show 401 and 735 orders [Q17].
11. **Airflow migration dropped the 17:00 intraday run** (crontab had 12:00 and 17:00; the DAG only has `0 12 * * *`) [c:4bfcbe6][f:airflow/dags/intraday_report_dag.py].
12. **Docs are partly stale or wrong** (README rec-v4 feature list, trending 60-day, dataset names in `data-access.md`, `rec_versions.md` = "TBD") - audit in Appendix D.

**How a tenured person answers "what was revenue in month M, and why"** - see 4.1 (decision tree + worked Oct/Nov/Dec numbers).

---

# 2. Why this project

- **Purpose of the codebase.** Serve the storefront (catalog price feed, carts, order callbacks from the payment gateway, refunds/cancels, similar-products widget) and feed finance/ops with nightly reports [f:README.md][f:novamart/app.py].
- **Why the numbers matter.** `constants.py` carries the header *"Change with care - finance reads the numbers these produce"* [f:novamart/constants.py:1]. Monthly statements feed the board deck [doc:docs/restatement_policy.md]; exec dashboards feed leadership screens [rd:dash 1-9]; the rec widget and shadow pricing are the company's only ML/decisioning bets [f:novamart/routers/similar.py][f:novamart/jobs/price_suggest.py].
- **Why tribal knowledge is needed.** Definitions drifted through 100+ commits, filters were added without back-fills, SQL lives in three places (Python jobs, git-history dashboard files, Redash), warehouse views were created by hand-run sessions that appear only in the DB statement log [Q56, Q54], and several docs contradict the code (Appendix D). The only way to answer a number question correctly is to know *which definition, which date, which filters*.
- **Platform history (Jan 2020).** Single prod box -> Cloud SQL replica + BigQuery + Airflow + Redash; dashboards deleted from the repo [c:41e3537], crontab retired [c:4bfcbe6], warehouse loaded by a one-shot backfill [c:5ae1182][doc:docs/data-access.md].

---

# 3. Business understanding

## 3.1 Business model and entities
- Marketplace of ~81k products (brands such as samsung/apple/bosch; categories like `electronics.smartphone`) fed by a vendor price feed `POST /catalog/prices` [Q29, f:novamart/routers/catalog.py:85-100]. Product rows are created on first sight (viewed/carted/ordered) with synthetic title/vendor/cost/stock [f:novamart/onboarding.py:38-48].
- Customers are numeric ids relayed by the storefront (e.g. 512397607). A `users` row is created the first time an id is seen on any event - it is *not* a signup record [f:novamart/routers/catalog.py:58-66][Q23]. A 30-user "registered accounts beta" (UUID `accounts` + `account_map`) was created in one batch on 2019-12-01 16:30Z [bq:novamart.accounts][Q51: `account_created` 30 rows on 2019-12-01].
- Prices: `orders.price` is whatever the checkout callback posted; it equals `products.list_price` for only 2,080 of 7,068 legacy single-line orders (above 1,687, below 3,301) - use `orders.price` for revenue, never `list_price` [Q32].

## 3.2 Order lifecycle and status codes (all verified in code or data)
| status | meaning | evidence |
|---|---|---|
| 0 | created, awaiting payment (transient inside `/orders`; flipped to 1 in same call) | [f:novamart/routers/orders.py:92,104] |
| 1 | paid / "completed" | [f:novamart/routers/orders.py] |
| 2 | cancelled (was **4** until [c:8f19718] 2019-10-28) | [f:novamart/constants.py:13][c:8f19718] |
| 3 | refunded via `/orders/{id}/refund` (only from 1) | [f:novamart/routers/orders.py:137-157][c:d87cb3d] |
| 6 | fraud-held by nightly `fraud_score` | [f:novamart/jobs/fraud_score.py][c:e4656fb] |
| 4/5 | legacy / undefined: no rows today; `reconcile` still excludes `status<>5` | [Q01][f:novamart/jobs/reconcile.py:16] |

Current distribution: status 1 = 9,033 orders / $2,860,063.26; 2 = 54; 3 = 28; 6 = 12 / $40,213.29 [Q01, Q60].

**Order creation quirks that shape every count**
- Idempotent by `payment_ref` since [c:b676969] (2019-10-15 14:00Z). Before it, replayed callbacks created extra orders: **130 refs / 285 orders share a ref (155 extras; 151 of them status 1, $58,828.24, all order ids <= 1862, i.e. created before 2019-10-15 13:36:25Z)**; same user+product+price, minutes apart [Q05, Q06, Q68]. Since then, 522 replays are absorbed and logged `order_callback_replayed` [Q51].
- Since [c:5d1300d] (first `order_lines` row 2019-11-22 15:18Z [Q16]), a callback in the *same session within 15 min for the same user* is **merged into the existing order**: `orders.price` becomes the sum, a line is appended to `order_lines`, and one `payments` row per line is written (each line pays its own $0.30 flat fee) [f:novamart/routers/orders.py:66-89]. 2,059 orders have lines; 173 orders have >1 payment rows; 225 `order_appended` events [Q15, Q69, Q51].
  Consequence: `orders.product_id` is only the **first** item; jobs reading `orders` (top_sellers, trending, reorder, price_suggest, digest, model_train, affinity conversion) ignore later lines, while `daily_report`/dashboards read `order_lines`, and statements/kpi read order-level `price`.
- Cancel/refund endpoints only change `orders.status`; they **do not touch `payments`** [f:novamart/routers/orders.py:113-157]. The separate gateway webhook writes **negative** `payments` rows but leaves `orders.status=1` [f:novamart/routers/payments_webhook.py:11-21][c:c49a7bb] and is **not idempotent**: orders 3762/3763/3776 were refunded on 12-13, 12-20 and 12-27 (9 rows, -$1,843.59; real value $614.53) [Q11].

## 3.3 Money flow and fees
- Fee per payment row = `round(price*2.9% [+ $0.30 flat], 2)` [f:novamart/routers/orders.py:19][f:novamart/constants.py:4,32]. The flat fee entered code in [c:12e1c68] (2019-11-20 14:25Z) and the **first flat-fee payment is 2019-11-20 14:27:41Z** (last percent-only one 14:17:41Z) [Q62, Q13]. `monthly_statement` assumes the change at local midnight (05:00Z) [f:novamart/jobs/monthly_statement.py:13], so 64 payments / $19.20 between 05:00Z and 14:25Z are "expected" to carry the flat fee but did not [Q13].
- October fee story: the job first computed `gross*2.9%` = 35,679.64; it was changed on 2019-11-02 to sum collected per-order fees [c:a92c96d]; the published row was left alone and corrected through `statement_overrides` (35,679.50 / net 1,194,652.93) [Q03a][log:db_queries 2019-11-02 14:00 `[engineer-backfill:dev]`].
- November "audit correction": `statement_corrections` holds delta **0.00** (statement fee already equals collected fee) [Q03b]. The logged `statement_fee_mismatch` (-170.41) was a false alarm: the 2019-12-01 run still used the pre-flat-fee expectation (31,940.51); the formula was fixed the next day [Q53][c:4a58d17].

## 3.4 Finance statements: three layers (the "restatement stack")
1. `public.statements` / `[bq:novamart.statements]` - append-only snapshot written by `monthly_statement` on day 1 at 06:30 local for the prior local month; status=1 orders at run time [f:novamart/jobs/monthly_statement.py:16-45]. Three rows exist: 2019-09 (12 orders, 2,702.00), 2019-10, 2019-11 [Q02].
2. `analytics.statements_corrected` view = statements LEFT JOIN `statement_overrides` (one Oct row) [bq:novamart_analytics.statements_corrected][Q54][c:a92c96d].
3. `analytics.statements_final` view = corrected minus `chargebacks` grouped to the *order's* NY-month; fee unchanged [Q54][Q03c].
Policy text: use `public.statements` for "as published", `statements_final` for "current restated" [doc:docs/restatement_policy.md]. **Gaps the policy doesn't state** (all verified): status changes after publication are never reflected; chargebacks were back-dated (`reported_at` 2019-12-01 12:00Z, inserted 2019-12-09) for 3 October orders that were then cancelled/refunded on 12-10 and 12-17 [Q04][log:db_queries 2019-12-09 15:00 `INSERT INTO analytics.chargebacks`]; those 3 are literally "the first 3 October orders over $700" (selection by `ORDER BY created_at LIMIT 3`) - the table is seed-like, not a real chargeback feed; duplicates are untouched; the Sep statement (2,702.00) is entirely orders that were later cancelled/refunded (current status=1 revenue for Sep = 0) [Q01].

## 3.5 Timeline of definition changes (what a tenured person remembers)
| Date | Change | Evidence |
|---|---|---|
| 2019-09-15 | Initial import: cron-run `daily_report` (cap 500 rows, status!=0, no filters), `monthly_statement` (fee=gross*2.9%), dashboards best_sellers/brand/daily_kpis | [c:2da4141] |
| 10-08 | Test SKUs 1004856, 1002544 hidden **in the daily report only** | [c:83fb3ed] |
| 10-15 | Idempotent order callbacks | [c:b676969] |
| 10-25 | `lucente` denylisted from report (not back-filled) | [c:ba1fbfa][Q09] |
| 10-26 | similar widget v1 (co-cart); `reports` & `users` routers silently unmounted from `app.py` in same commit | [c:f1217a8][f:novamart/app.py:19-23] |
| 10-28 | cancelled status 4 -> 2 | [c:8f19718] |
| 11-02 | statement fee uses collected fees; trending (60d) added | [c:a92c96d][c:152a760] |
| 11-05 | DST fix for local-day windows (report for 2019-11-03 lost its last hour: -$2,985.99, never re-run) | [c:102c9b4][Q09][log:db_queries 2019-11-05] |
| 11-15 | refund status 3 | [c:d87cb3d] |
| 11-16 | nightly `kpi_daily` (30d actives, status=1) | [c:14726e7] |
| 11-18/19 | report excludes statuses 0,2,3; **scan cap of 500 removed** (2019-11-17 report said 148,857 vs 223,853 actual) | [c:11c0a42][c:1233af8][Q09] |
| 11-20 | Fee = 2.9% + $0.30 | [c:12e1c68][Q13] |
| 11-22 | `order_lines` + same-session merge | [c:5d1300d][Q16] |
| 11-27 | QA user 424242 excluded (report job + dashboards); `analytics.test_users` seeded | [c:b59f077][log:db_queries 2019-11-27] |
| 12-02..05 | affinity v2; shadow pricing put on hold; fraud scoring (threshold 0.90 -> 0.70) | [c:89666bf][c:cca9b0d][c:e4656fb][c:53f6f6c] |
| 12-04 | `contactable_users` view | [c:e10cb0c] |
| 12-05 | order_lines-based counting in report/dashboards; gateway refund webhook | [c:92596dc][c:c49a7bb] |
| 12-06 | trending window 60 -> 30d (effective 12-07); widget v2 dispatch + random arm | [c:f563dea][c:df4ed85][Q43] |
| 12-08 | intraday report + dashboard merge of intraday snapshots | [c:a2e0013] |
| 12-09 | chargebacks + `statements_final` | [c:cd559d3] |
| 12-10..11 | registered-conversion dashboard; board actives query | [c:d6e34c6][c:2dde4f0] |
| 12-12 | versioned taxonomy mapping | [c:33054cd] |
| 12-14 | rec model v4 trained nightly; funnel gap 30 -> 120 min | [c:a1946ff][c:f915c1b] |
| 12-15 | `jetem` denylisted (report + dashboards) | [c:1169e40] |
| 12-16 | digest reads `deploy/cron.env` directly (digest effectively on from 12-17) | [c:0bd4eac][Q48] |
| 12-19 | widget cache added; random-arm logging restored (missed 12-17..18) | [c:a00f24c][Q34] |
| 12-21 | reorder constant K 141.12 -> 162.4 | [c:f85cdd2] |
| 12-23/24 | refunds dashboard; revenue widget de-dup fix | [c:a3bffec][c:3eced24] |
| 12-26 | cache invalidated on table refresh; empty results no longer cached | [c:8ed2971][Q33] |
| 12-29 | threshold 0.70 -> 0.85 + manual release of held orders < $2600 (UPDATE not in repo) | [c:1cb8721][Q57] |
| 2020-01-02..05 | data-access doc, dashboards -> Redash, crontab -> Airflow, warehouse backfill job | [c:d398b0d][c:41e3537][c:4bfcbe6][c:5ae1182] |

---

# 4. Metrics

## 4.1 Revenue: which number, when, and why

### Decision tree (the tenured-person answer)
1. **"What did we tell the board for month M?"** -> `[bq:novamart.statements]` row for M (as published). Oct: 1,230,332.43 gross / 1,194,652.79 net; Nov: 1,101,397.01 / 1,069,286.09; Sep: 2,702.00 / 2,623.64 [Q02].
2. **"What is the current finance number?"** -> `[bq:novamart_analytics.statements_final]` (Oct gross 1,226,764.86 / net 1,191,085.36; Nov unchanged) [Q03c] - **but state the caveats**: later cancels/refunds ($23,995.11 for Oct), duplicate callbacks ($58,828.24 for Oct) and gateway refunds (-$614.53 actual) are not reflected.
3. **"How much cash-backed paid revenue was there?"** -> `orders` with `status=1`, minus duplicate `payment_ref` orders, then subtract gateway-refunded orders (3 orders, $614.53). Oct: 1,206,337.32 -> **1,147,509.08** after dedupe [Q07].
4. **"What do the exec dashboards show?"** -> `report_rows` (daily_report output) via `daily_kpis`/`revenue_widget` [rd:query 7][rd:query 2]; Oct 1,201,082.08, Nov 966,974.33, Dec(1-30) 535,561.72 [Q08]. Never reconcile these to statements.

### Worked table (NY local months)
| Month | Published gross | Final gross | status=1 now | status=1 less dup. | report_rows | payments pos. gross | cancelled/refunded since | held (6) |
|---|---|---|---|---|---|---|---|---|
| 2019-09 | 2,702.00 | 2,702.00 | 0.00 | 0.00 | 2,702.00 | 2,702.00 | 2,702.00 (11 canc./1 ref.) | - |
| 2019-10 | 1,230,332.43 | 1,226,764.86 | 1,206,337.32 | 1,147,509.08 | 1,201,082.08 | 1,230,332.43 | 23,995.11 (43/27) | - |
| 2019-11 | 1,101,397.01 | 1,101,397.01 | 1,101,397.01 | 1,101,397.01 | 966,974.33 | 1,101,397.01 | 0 | - |
| 2019-12 | (not run) | - | 552,328.93 | 552,328.93 | 535,561.72 (to 12-30) | 592,542.22 (-1,843.59 gateway) | 0 | 40,213.29 (12) |
Sources: Q01, Q02, Q03c, Q07, Q08, Q10.

### Why `report_rows` is so low in November (-134k vs paid orders)
Approximate decomposition for Nov (Q07, Q09): excluded SKUs ~40.6k; lucente/jetem ~15.9k; the 500-row scan cap on 2019-11-17 (-74,995.96 on that day, fixed 11-19 but not re-run); the DST truncation of 2019-11-03 (-2,985.99). 2019-11-15 has no report row because there were zero orders [Q09, Q17]. In October, rows before 10-08/10-25 still contain test SKUs/lucente because filters were never back-filled (daily diffs equal denied-brand revenue exactly on 10-09..10-24) [Q09].

### Other revenue-like measures and their traps
| Metric | Definition & source | Trap |
|---|---|---|
| `top_products` / top_sellers | yesterday units, status=1, **no brand/SKU/QA filter**, orders only [f:novamart/jobs/top_sellers.py] | test SKUs rank #1 on 18 of 54 days [Q28] |
| best_sellers dashboard | rolling 7d, order_lines+legacy fallback, ranks by **revenue**, **no status filter**, no SKU filter [git:old-sql best_sellers][rd:query 9] | includes cancelled/refunded rows (e.g. #3 product shows 2 non-paid rows) [Q26] |
| brand_revenue / category_revenue dashboards | rolling 30d, same fallback, no status filter | blank brand = 17,442 products (34.8k s1 revenue in Oct); `'cc27b436-...'` string exclusion never matches (`user_id` is BIGINT) [Q07, Q29][git:old-sql brand_revenue] |
| `GET /reports/brands` | status=1, excludes EXCLUDED_SKUS + denylist [f:novamart/routers/reports.py:30-36] | **router not mounted** since 10-26 [f:novamart/app.py:19-23][c:f1217a8] |
| `analytics.refunds_unified` / refunds dashboard | cancels + refunds (by `updated_at` month) + negative payments | counts cancellations as refunds; gateway refunds triple-counted [Q12][bq:novamart_analytics.refunds_unified] |
| discounts helper | `apply_discounts(rows, cap=0.40)`; config says `DISCOUNT_CAP=0.25` [f:novamart/jobs/discounts.py:4][f:novamart/constants.py:35] | ops script `scripts/rerun_kpis.py` calls it with the **legacy 0.40 default** -> revenue x0.60 instead of x0.75 [f:scripts/rerun_kpis.py] |

## 4.2 Product analytics
- **Best sellers (jobs vs dashboard)**: job = units, status=1, orders.product_id; dashboard = revenue ranking, lines, no status filter. As-of 2019-12-31 the dashboard top 3 by revenue: #5115 (6,245.62), #5116 (5,889.81), #5284 (5,096.14, 2 non-paid rows) [Q26].
- **Excluded/hidden things (and where each is applied)**:

| Rule | report job | dashboards | statements | rec fallback | top_sellers/trending |
|---|---|---|---|---|---|
| EXCLUDED_SKUS (1004856 "Internal Test", 1002544 "Unbranded Item #2544") | yes (from 10-08) | **no** | **no** | **no** (only affinity/model path) | **no** |
| brand lucente / jetem | yes (10-25 / 12-15, not back-filled) | yes (jetem from 12-15) | no | no | no |
| QA user 424242 | via `analytics.test_users` (from 11-27) | yes (id literal) | no | n/a | no |
| status | not in (0,2,3) -> includes 6 | none | =1 | n/a | =1 |
Sources: [f:novamart/constants.py:7-19][f:novamart/jobs/daily_report.py][Q27, Q28, Q42][git:old-sql].
  *SKU 1002544 is brand `apple`, `electronics.smartphone`, title "Unbranded Item #2544" and carries $66,226.12 of paid revenue (138 orders) - it looks like a mislabeled real product rather than a test SKU; hiding it in the report understates revenue.* [Q27]
- **Brand/category taxonomy**: `category_names` (135 codes -> display_group, first-seen date) plus `category_name_history` (6 rows regrouping `electronics.audio.*` -> entertainment, `construction.tools.light` -> lighting) [bq:novamart_analytics.category_names][bq:novamart_analytics.category_name_history]. History rows have `valid_from = 2026-08-13` (the load date, because the insert used `CURRENT_DATE`) -> **the regroup never applies to any 2019 order** [Q30, Q58][log:db_queries 2019-12-12]. Dec-2019 category mix: electronics 426,872 / other 87,259 (of which 46,698 has blank category) [Q31].
- **Brand cleanliness**: 17,442 products have blank brand (8,016 of them have a category) due to ON CONFLICT DO NOTHING + known-id cache on first insert; repair path added 2019-10-21 [Q29][c:ea0e97b][bq:novamart_analytics.blank_brand_products].
- **Trending**: 30-day (README still says 60) window, min 5 units, decay 0.05/day, top 50; **includes the internal test SKU at rank #2 and 1002544 at #3 on 2019-12-31** [Q44][doc:docs/trending_notes.md].
- **Reorder hints**: advisory only; `hint = int(15.6 + K/(velocity+1.8))`, so hints *fall* as velocity rises (corr -0.96) [Q45][doc:docs/forecast_caveats.md].
- **Price suggestions**: shadow-only (+/-5% around list price vs median demand); 386 down / 109 up because ties at the median default to -5% [Q46][f:novamart/jobs/price_suggest.py]. Nothing reads the table [Q55].

## 4.3 Customer metrics
| Metric | Definition | Value (2019-12-31) | Used by |
|---|---|---|---|
| `users` rows ("signups") | id seen on any event; created_at = first sight | 38,950 (29,917 never carted/ordered; Oct's 15,045 "new users" is most likely a stream-start artifact: data begins 09-25) | nobody official [Q23, Q66] |
| Buyers ever | distinct `orders.user_id` | 4,112 (4,089 with status 1) | - [Q66] |
| **Nightly active customers** | distinct users, trailing 30x24h, `status=1`, no test filter | **1,152** | `analytics.kpi_daily` [f:novamart/jobs/kpi_daily.py] |
| **Dashboard actives** | per **NY day** distinct users, **no status filter**, excludes 424242 + denied brands | 47-75 per day (12-25..12-31) [Q63] | `daily_kpis` [rd:query 7] |
| **Board actives** | trailing 30d, status not in (0,2,3), excludes `test_users` and email patterns | **0** | `actives_board` [rd:query 3] |
| contactable | `contactable_users` view (opt-in, valid email, not example.*) | 0 rows | `daily_kpis.contactable_customers` always 0 |
| digest recipients | `email NOT LIKE '%@example.com'` | 40 every day, ignores opt-in | `email_digest` |
| registered buyers | accounts joined to users by **email** | see 4.5 | `registered_conversion` |
| funnel `users_active` | users with cart/order in last 24h (not views) | ~200-367/day | `analytics.daily_funnel` |
Sources: Q18-Q23, Q47, Q51; verification that nightly vs any-status vs board differ: Q21 (1,150 / 1,155 / 0).
- **Why nightly actives "fell" 1,560 -> 1,031 between 2019-12-16 and 12-18**: the 2019-11-16/17 promo cohort (401 + 735 orders) aged out of the 30-day window; not churn [Q22, Q17].
- Segments that exist only in code: `new_account` (<7 days since `users.created_at`) and `high_velocity` (3+ orders/24h) in fraud; `organic_user` in the model; `marketing_opt_in` for contactability [f:novamart/jobs/fraud_score.py][f:novamart/jobs/model_train.py:44-56]. All sourced from the synthetic profile; **do not draw channel/region/age conclusions** [Q25].

## 4.4 Operational / ML metrics
| Metric | Definition | Notes |
|---|---|---|
| Rec hit rate (derived in this study) | same user buys a recommended item within 24h of exposure | v2 "model" source 0.772%, trending fallback 0.149%, random 0.000% [Q41] |
| Fallback share | `rec_source='fallback'` / all | 80% overall; v1 era 326,186 of 392,630 (83%); v2 era 207,796 of 260,467 non-random (79.8%); 76.3% for 12-27..12-31 [Q33, Q72, Q67] |
| Funnel sessions | 120-min gap sessionizer on cart+order events | gap raised 30 -> 120 min [c:f915c1b]; ratio ~1.1 sessions/user, traffic step on 12-16 (230 -> 416) [Q47] |
| Job success | `job_runs` events | every job ran on every day of its span (run_days = span_days); only crash = affinity_v2 on 12-03..05 [Q71, Q48, Q49] |

## 4.5 Registered-customer conversion (id-namespace trap)
Orders use legacy numeric `user_id`; accounts use UUIDs; the first version of the dashboard joined `account_id::text = user_id::text` (always 0) [c:d6e34c6], fixed on 12-21 to join through email [c:b975479]. Mapping through `account_map.uid` is exact (30/30 match by uid and by email) [Q61]; the email join works only because placeholder emails are unique (38,950 distinct for 38,950 users) [Q18, Q61].

---

# 5. System

## 5.1 Architecture (data flow)
```
storefront ids -> FastAPI app (novamart/app.py) -> Postgres (serving, "novamart-prod-replica")
   routers mounted: catalog, carts, orders, similar, payments_webhook   (accounts/users/reports are NOT mounted)
   logs: app.jsonl, db_queries.log (every statement), jobs.jsonl  -> BigQuery novamart_logs.{app_events,db_queries,job_runs}
nightly jobs (crontab -> Airflow DAGs) read orders/cart_items/users/products, write analytics.* and public.report_rows/statements/top_products
warehouse_backfill (one-shot): gcloud sql export csv -> bq load --replace  => BigQuery novamart + novamart_analytics
Redash (novamart-ops) -> data source "novamart" type pg host estate-pg  (serving DB, not BigQuery)
```
Evidence: [f:novamart/app.py][f:novamart/db.py][f:novamart/logutil.py][f:novamart/jobs/warehouse_backfill.py][doc:docs/data-access.md][rd:data_sources/1].
- **Unmounted routers**: `/reports/brands` and `/users/{id}/email` dropped in [c:f1217a8]; `/accounts` dropped in [c:c49a7bb] (accounts exist only from 2019-12-01) [f:novamart/app.py:19-23][Q51].
- **Deploy markers**: 35 empty commits "trigger deploy #d2p-novamart" (usually 19:37-20:37Z). Code can take effect *before* the marker (flat fee appears in data 2 minutes after its commit, 6h before the marker) - do not infer activation time from deploy markers [c:12e1c68][c:9b5b0da][Q13].
- **Runtime flags**: `deploy/flags.env` `REC_MODEL_VERSION=2.0.0` read from a **relative path** per request; `deploy/cron.env` `ENABLE_DIGEST=1` read from a relative path by the digest job [f:novamart/routers/similar.py:37-45][f:novamart/jobs/email_digest.py:13-31]. Under any scheduler whose cwd is not the repo root both silently fall back (digest -> disabled; widget -> 2.0.0).

## 5.2 Scheduled jobs (what each produces, consumers, what breaks)
Schedules are NY-local (crontab header) and run at 10:00Z/11:00Z etc. around DST [Q50]. Airflow DAGs reuse the same clock strings with no timezone [f:airflow/dags/*.py].

| Job (local time) | Reads | Writes | Consumers | If it fails / dependencies |
|---|---|---|---|---|
| reconcile 03:00 | orders | `app_events duplicate_payment_ref` (cap 200) | humans only | flags the same set of up to 130 refs every night for 92 days (10,766 warnings; 130 distinct refs) - pure alert fatigue; nothing acts [Q52][f:novamart/jobs/reconcile.py] |
| affinity 03:30 (v1) | cart_items | `analytics.product_affinity` | widget until 12-06 only | now unused by anything yet still runs; safe to retire after confirming no external reader [Q55][doc:docs/affinity_lineage.md] |
| affinity_v2 03:45 | cart_items, orders, products | `analytics.product_affinity_v2` (stamped `2.0.1`) | widget (primary), model_train | crashed 12-03..05 (11-element seasonal list, December) -> fixed [c:3dbe4d7]; if it fails the table keeps yesterday's rows [Q49] |
| model_train 04:15 | rec_decision_log, v2 table | `model_registry`, `model_scores` | **no reader** | see 5.4; depends on v2 refresh by clock order only |
| price_suggest 04:45 | products, orders | `price_suggestions` (shadow) | none | on hold [c:cca9b0d] |
| trending 05:15 | orders | `trending_daily` (day-partitioned) | widget **fallback** (80% of traffic) | widget uses `MAX(day)`, so a failure silently serves a stale list |
| fraud_score 05:45 | orders, users | `order_risk`; **mutates `orders.status` 1->6** | all status=1 measures | only scores the last 24h of orders; held orders never re-scored [f:novamart/jobs/fraud_score.py] |
| daily_report 06:00 | orders/order_lines/products/test_users | `report_rows` (append-only, one version per date today [Q74]) | `daily_kpis`, `revenue_widget` | a missed day = missing KPI row; never self-heals (no back-fill logic) |
| kpi_daily 06:15 | orders | `kpi_daily` | exec "actives" | trailing-30d, status=1 |
| funnel 06:20 | cart_items, orders | `daily_funnel` | analytics | 24h lookback from run time |
| monthly_statement 06:30 on 1st | orders, payments | `statements` | finance | append-only; re-running **inserts a second row for the month** (no upsert); views then join the duplicates [f:novamart/jobs/monthly_statement.py:44-46] |
| top_sellers 06:45 | orders | `top_products` | merchandising | no filters |
| reorder_forecast 06:50 | orders | `reorder_hints` (advisory) | none | DELETE+row-insert, not atomic |
| email_digest 07:15 | orders, users | `digest_log` | marketing | silent no-op unless flag found |
| intraday_report 12:00 (+17:00 in cron) | orders | `report_rows_intraday` (append-only; 2 versions/day [Q74]) | dashboard "today" | **Airflow has only the 12:00 entry** [c:4bfcbe6] |
Row counts / first-last runs: [Q48]; clock times [Q50].

**Atomicity hazard shared by 6 jobs**: connection is `autocommit=True`; refresh = `DELETE` then thousands of single-row `INSERT`s [f:novamart/db.py:21][f:novamart/jobs/affinity_v2.py:46-61]. A crash mid-run leaves a partial table; the widget's later `updated_at = MAX(updated_at)` guard only mitigates reads of mixed generations [c:8ed2971].

## 5.3 Warehouse (BigQuery) and Redash
- **Datasets (real names)**: `novamart` (12 tables), `novamart_analytics` (20 tables + 4 views), `novamart_logs` (3 tables + 1 view). `docs/data-access.md` calls the analytics dataset `analytics`; the backfill code maps `analytics.*` -> dataset `analytics`, which does not exist here [doc:docs/data-access.md][f:novamart/jobs/warehouse_backfill.py:59-60][bq ls -> intermediate/bq_ls.txt].
- **Backfill** replaces each table (`bq load --replace`) from a CSV export; views are **not** in the manifest, so a rebuild would lose `contactable_users`, `refunds_unified`, `statements_corrected`, `statements_final` (their DDL exists only in the DB statement log as `[engineer-backfill:*]` sessions) [f:novamart/jobs/warehouse_manifest.json][Q56, Q54]. The Airflow wrapper calls it with **no required args** (`--project/--instance/--staging`), so it fails as written [f:airflow/dags/warehouse_backfill_dag.py].
- **Views** (BigQuery SQL via INFORMATION_SCHEMA): contactable_users = opt-in + regex + not example.com/net/org + not `%.example`; refunds_unified = status 2/3 orders UNION negative payments; statements_corrected/final as above [Q54].
- **Redash**: 9 dashboards, 9 queries, one Table widget each, no tags, no schedules, no alerts, no cached results; query text is identical (ignoring trailing whitespace) to the SQL files deleted in [c:41e3537] [intermediate/redash_sql_vs_git.txt]; owner Admin; data source type `pg` (host `estate-pg`) [rd:dash 1-9][rd:queries 1-9]. Dashboard 7 ("best_sellers") uses query 9 and dashboard 9 ("daily_kpis") uses query 7 (ids crossed, names consistent).
- **How to read a dashboard honestly**: Postgres SQL with `now()`; `analytics.*` here is a Postgres schema; results depend on run time (not reproducible after the fact); the board query's email filter currently zeroes the metric; rolling-window widgets in the sim's present (2026) would find no 2019 orders [Q21][rd:query 3] (inference, Appendix E).

## 5.4 ML / recommendation systems (Phase 3)
**Versions** (the docs say "TBD" [doc:docs/rec_versions.md]):
| Label | Where | What | Status |
|---|---|---|---|
| 1.0.0 | `similar.py` (c:f1217a8) | `product_affinity` (co-cart counts, decay 0.05/day, 30d, sentinel -1 for pairs <3 since c:fef5c96); fallback = 7-day bestsellers | live 10-26..12-06; 83% fallback [Q33] |
| 2.0.0 | `similar.py` (c:df4ed85) | `product_affinity_v2`: `(1*pairs + 3*converted) * exp(-0.05*age) * 1.15 same-category * 0.7 wild price ratio * seasonal(month)`; fallback = `trending_daily` latest day | **live since 12-06 (flag)** |
| 2.0.1 | `affinity_v2.py` MODEL_VERSION | row stamp in `product_affinity_v2` (from c:3dbe4d7) | label drift vs serving label 2.0.0 [doc:docs/affinity_lineage.md] |
| 4.0.0 | `model_train.py` (c:a1946ff) + serving branch in `similar.py` | logistic regression on random-arm exposures; writes `model_scores` | **never served** (flag stays 2.0.0) [Q33, Q55] |
| random arm | `in_random_arm`: sha256(uid) % 20 == 0 (5% of users) | uniform draw of 5 from `products` | logged since 12-06 |
Evidence: [f:novamart/routers/similar.py][f:novamart/jobs/affinity.py][f:novamart/jobs/affinity_v2.py][f:novamart/jobs/model_train.py].

**Serving path** `GET /products/{pid}/similar`: random arm -> else (cache 6h keyed by table+pid; invalidated when `MAX(updated_at)` of the backing table changes) -> `SELECT ... WHERE score>=0 AND updated_at=MAX(updated_at)` -> if empty: `trending_daily` latest day -> log row in `analytics.rec_decision_log` (+ JSONL `rec_served`) [f:novamart/routers/similar.py:68-123][c:8ed2971].
**Logging semantics**: `intended_version` = flag; `effective_version` = actual (`fallback` when degraded); `fallback_reason` in {no_scores, table_missing, cache}; `arm` in {none, random}. The `reason=cache` + `effective=fallback` rows (25,091, 12-19..12-26) are cached *empty* lists: before [c:8ed2971] empty results were cached for 6h [Q33].
**Known failure/regression log**: after the refactor [c:30e8907] (code 12-17 16:50Z, deploy marker 20:37Z) random-arm decisions were not logged: 549 rows on 12-17 (pre-deploy), **0 rows on 12-18**, restored by [c:a00f24c] on 12-19 14:55Z [Q34]; empty-list caching window 12-19..12-26 [c:a00f24c][c:8ed2971][Q33].

**Does it work? (evidence)**
- Coverage: only 449 base products have any positive score (948 rows) while 13,315 distinct base products were requested 2019-12-27..31; 2,964 of 3,912 v2 rows are sentinel -1 [Q73, Q67, Q36a].
- Lift: items from the v2 path are bought within 24h by the same user 0.772% of the time vs 0.149% for the trending fallback and 0.000% for random [Q41]. Directionally the affinity path works where it applies; users in the random arm buy at 5.5% vs 5.0% for the rest (52/942 vs 996/20,016; not significant) [Q40].
- Fallback quality: 530,000 of 534,145 fallback responses include `Internal Test #4856`; 235,068 include 1002544 [Q42].
- v4 model: `model_scores/v2` ratio is 0.9755-0.9756 for all 948 pairs -> same order as v2; n_items has min=max=5; training label = "user ever orders anything later" (13.3% positives; 14,566 rows from only 942 users); coefficient on the constant feature swings -0.81 -> -0.24 across nightly fits and the last fit flips the sign of the other four coefficients (e.g. feature 2: +0.25 -> -0.53) [Q35, Q37, Q39][f:novamart/jobs/model_train.py:44-72]. README claims 9 features (region, device, opt-in, stock...) but the code uses 5 [doc:README.md][f:novamart/jobs/model_train.py:52-56].
- Random arm validity: items come from `ORDER BY id LIMIT 500` -> ids 1,000,894-1,004,393 only [Q38][f:novamart/routers/similar.py:73-80].

## 5.5 Safe-change checklist for batch pipelines
1. Run order matters by wall clock only (no DAG dependencies): affinity_v2 (03:45) -> model_train (04:15); fraud_score (05:45) -> daily_report (06:00) -> kpi_daily (06:15). Add explicit dependencies before shifting times [f:airflow/dags/*.py].
2. Any filter change (brands, SKUs, statuses, QA users) must be applied to **all** of: `constants.py`, `daily_report`/`intraday_report`, `top_sellers`, `trending`, the similar fallback, `kpi_daily`, dashboards, and **historical `report_rows`** (back-fill) - history shows every filter change missed a surface [Q09, Q42, Q27].
3. Refresh jobs are not transactional; wrap DELETE+INSERT in one transaction (or write to a staging table and swap) before adding consumers.
4. `monthly_statement` and `report_rows` are append-only snapshots; re-runs create duplicate versions (readers must take latest `created_at`, which the dashboards do; the statements views do not) [f:novamart/jobs/monthly_statement.py:44-46][bq:novamart_analytics.statements_corrected].
5. Anything reading a flag/env file by relative path needs an absolute path or injected env.
6. Keep views in version control; they currently exist only as hand-run DDL in logs [Q56].
7. Timezones: business day = America/New_York; windows must be built from local midnights (see `timeutil.local_day_window_utc`), never `start + 24h` [c:102c9b4].
8. Verify any new "unique key" assumption: `orders.payment_ref` is not unique in history (130 repeated refs).

---

# 6. Data

## 6.1 Tables (warehouse row counts at inspection; Q59a, schema from `bq show`)
| Dataset.table | Rows | Grain / notes |
|---|---|---|
| novamart.orders | 9,127 | one per paid-ish order (merged lines roll up here); status per 3.2 |
| novamart.order_lines | 2,284 | only since 2019-11-22; 2,059 orders |
| novamart.payments | 9,361 | one per line; negative rows = gateway refunds; `payment_ref` NULL for 7,077 pre-11-22 rows + 9 refunds |
| novamart.products / users | 81,018 / 38,950 | created on first sight; synthetic attributes |
| novamart.cart_items | 36,938 | log shows 36,925 `cart_item_added` events (13 more rows than events; 14 are `qa-smoke`) [Q51, Q65] |
| novamart.report_rows / report_rows_intraday | 6,923 / 2,358 | per-day per-product snapshots; one version per day (intraday: 2 per day) [Q74] |
| novamart.statements | 3 | Sep/Oct/Nov, append-only |
| novamart.top_products | 2,396 | top 50/day |
| novamart.accounts / account_map | 30 / 30 | registered beta, all on 2019-12-01 |
| novamart_analytics.* (20) | see 5.2 | `rec_decision_log` 667,850; `product_affinity(_v2)` 3,912 each; `model_scores` 948; `trending_daily` 2,898; `order_risk` 1,631; `kpi_daily` 45; `daily_funnel` 53; `digest_log` 15; `reorder_hints` 200; `price_suggestions` 500; `price_history` 1,400; `category_names` 135; `chargebacks` 3; `test_users` 1 (424242) |
| novamart_logs.app_events / db_queries / job_runs | 1,570,017 / 3,597,650 / 978 | JSON payloads / raw statement lines / job events |

## 6.2 Lineage of the main numbers
`/orders` callback -> `orders` (+`order_lines`,`payments`) -> {`monthly_statement` -> `statements` -> views `statements_corrected` -> `statements_final`; `daily_report`/`intraday_report` -> `report_rows(_intraday)` -> Redash `daily_kpis`/`revenue_widget`; `kpi_daily`; `top_sellers`; `trending` -> widget fallback}. Cancel/refund endpoints mutate `orders.status` in place (no event table); gateway webhook inserts negative `payments`; chargebacks are a hand-loaded table [f:novamart/routers/*.py][Q04][Q56].

## 6.3 Data-quality register (all verified)
1. **Replay duplicates** (Oct): 151 paid orders / $58,828.24 [Q05].
2. **Statements frozen** against later status changes [Q01, Q02].
3. **Gateway refunds** leave `status=1`; re-delivered weekly (3 orders x 3) [Q11].
4. **Status 6 limbo**: 12 held orders / $40,213.29 (min price $2,655.33) excluded from every `status=1` measure (statements, kpi_daily, top_sellers, trending) yet included by the daily report, the status-agnostic dashboards and board actives; the released 5 (`updated_at = 2026-08-13`, load-time) have scores 0.72-0.86 and one (8329, score 0.857) would still exceed the new 0.85 threshold [Q14, Q57, Q58].
5. **Load-time timestamps**: `now()`/`CURRENT_DATE` defaults wrote 2026-08-13 into `orders.updated_at` (5 rows), `blank_brand_products.captured_at`, `category_name_history.valid_from` [Q58]. Treat 2026-08-13 as "backfill date", not business date.
6. **Zero-order day** 2019-11-15 despite 2,136 carts [Q17]; 51 orders on 11-16 and 89 on 11-17 have no matching cart session (payment_ref prefix) [Q64] - callbacks without a cart event.
7. **Report rows not back-filled**: lucente on 10-09..10-24; DST day 11-03 (-$2,985.99); scan cap day 11-17 (-$74,995.96) [Q09].
8. **Placeholder PII**: every email is `user<id>@example.com` or (40 users) `cust<id>@gmail.example`; email-based logic (board actives, contactable, digest, registered join) is therefore degenerate [Q18, Q19, Q21].
9. **QA noise is small**: user 424242 = 14 orders / $139.86 (session `qa-smoke`, UUID `cc27b436-...`) [Q24]. The *internal test SKU* is much bigger: 322 paid orders / $40,304.68 at an average price of ~$124.90 (max $266.13) against a $9.99 list price [Q27, Q70].
10. **Blank brand/category** (17,442 / 33,514 products) distorts brand and category dashboards [Q29].
11. **Multi-line orders**: `orders.product_id` is first line only [3.2]; units differ between jobs.
12. **Log gap**: `cart_items` has 13 more rows than `cart_item_added` events [Q65, Q51]; the `account_created` JSON event carries `user_id` as a string while other events use integers [log:app_events].
13. **Chargeback month attribution**: `statements_final` assigns a chargeback to the month of the *original order*, not the month it was reported; chargebacks reported 2019-12-01 therefore restate October [Q54, Q04].

## 6.4 The DB statement log as a time machine
`novamart_logs.db_queries` holds every app/job statement and the **human sessions** tagged `[engineer:maya]`, `[engineer:dev]`, `[engineer-backfill:*]` (191 lines, 2019-10-15 -> 2019-12-30) [Q56]. It is the only place the DDL for views, chargebacks, overrides, category mappings and the held-order release exist [Q54][Q57]. Useful facts: v1 widget table reads ended 2019-12-06 (392,630 reads) and v2 reads started the same day; nothing ever reads `model_scores`, `price_suggestions`, `reorder_hints`, `model_registry` [Q55].

---

# 7. Experimentation

## 7.1 What experiments exist
| Experiment | Design | Status | Verdict |
|---|---|---|---|
| Random data-collection arm | 5% of users by hash; 5 random products | live since 2019-12-06 (14,566 exposures, 942 users) | **Biased pool** (500 lowest ids) and heavy repeat exposure per user; unlogged 12-17..18 [Q34, Q38] |
| Learned rec model v4 | nightly logistic fit; scores = v2 x (1+0.1*w) | trained 17x, never served | **No signal** (constant multiple; constant feature; weak label) [Q35, Q37, Q39] |
| Affinity v2 vs v1 | version flag; no holdout | replaced v1 on 12-06 | v2 hit-rate 0.77%; no clean A/B (v1 era 83% fallback) [Q33, Q41] |
| Dynamic pricing phase 1 (shadow) | nightly +/-5% suggestions, top 500 | phase 2 on hold (exec/legal) [c:cca9b0d] | Never read; ties bias toward -5% [Q46] |
| Reorder hints | `15.6 + K/(v+1.8)`; K refit 141.12 -> 162.4 | advisory | Inverse in velocity (corr -0.96) [Q45][c:f85cdd2] |
| Fraud hold threshold | 0.90 -> 0.70 -> 0.85 within 26 days | live | Manual release outside repo; see 6.3(4) [c:e4656fb][c:53f6f6c][c:1cb8721] |
| Trending window | 60 -> 30 days | live | max units 251 -> 115 overnight [Q43] |
| Funnel sessionization | 30 -> 120 min | live | no visible effect (sparse events) [Q47] |

## 7.2 How to judge whether the ML "works"
1. Pull `rec_decision_log` by `rec_source` (not `effective_version`): only `model` rows are personalized.
2. Compute coverage first (share of requests with a servable score) - currently ~24% of non-random requests [Q33].
3. Compare a **hit rate on the exposed list** (not "user ever buys later") across sources: 0.772 / 0.149 / 0.000 % [Q41]. Remember trending and affinity lists differ in popularity, so lift is partly popularity.
4. Never compare to the random arm until the pool is the full catalog; today it measures "recommend obscure low-id products".
5. To evaluate v4: shadow-serve `model_scores` (it will rank identically to v2 today - verify before spending effort) [Q35].
6. Exclude test SKUs from the evaluated lists first (fallback lists are contaminated) [Q42].

## 7.3 Recommended fixes (ordered by value)
1. Apply `EXCLUDED_SKUS` (and the brand denylist) in the trending fallback and in `trending.py`, `top_sellers.py`, `email_digest.py`.
2. Sample the random arm from all products (or from the currently-servable catalog) and de-duplicate exposures per user/session.
3. Fix v4: remove the constant feature, define the label as purchase of a displayed item within a window, ship real per-pair features.
4. Raise v2 coverage (lower `MIN_PAIRS=3`, longer window) - 76% of pairs are sentinel.
5. Re-cut statements after status changes; dedupe replay orders; make the gateway webhook idempotent.

---

# 8. Glossary

| Term | Meaning (with evidence) |
|---|---|
| **active customer** | one of three definitions: nightly (30d, status=1), dashboard (per NY day, no status filter), board (30d, non-cancelled, email-filtered; returns 0) [4.3] |
| **affinity / affinity_v2** | co-cart pair scores; v2 adds conversion weight and boosts; v1 retired from serving 12-06 [5.4] |
| **arm** (`none`/`random`) | rec_decision_log field for the 5% random exposure group [f:novamart/routers/similar.py:48-50] |
| **blank brand** | product with empty `brand` because first insert lacked metadata [Q29] |
| **board deck number** | `public.statements` as published (e.g. Oct net 1,194,652.79) [doc:docs/restatement_policy.md] |
| **callback replay** | payment gateway re-sending an order callback; pre-10-15 created duplicates, now `order_callback_replayed` [c:b676969] |
| **chargeback table** | hand-loaded `analytics.chargebacks` (3 rows, 3,567.57) [Q04] |
| **contactable** | opt-in + valid, non-example email (0 users) [Q19] |
| **EXCLUDED_SKUS** | `[1004856, 1002544]` hidden from the daily report and the model path only [f:novamart/constants.py:7] |
| **fallback** | trending list served when no affinity scores exist (80% of requests) [Q33] |
| **FEE_RATE / FEE_FLAT** | 2.9% and $0.30 per payment line [f:novamart/constants.py:4,32] |
| **held order** | status 6, set by fraud_score when risk > threshold [f:novamart/jobs/fraud_score.py] |
| **intended vs effective version** | flag value vs what actually served (`fallback`) [5.4] |
| **intraday report** | partial-day snapshot into `report_rows_intraday`, 12:00 and 17:00 local (Airflow: 12:00 only) [c:a2e0013][c:4bfcbe6] |
| **item_orders** | dashboard CTE = order_lines UNION legacy single-item orders without lines [c:92596dc] |
| **kpi_daily** | nightly 30-day actives table [Q22] |
| **LOCAL_TZ** | America/New_York; business day/month boundary [f:novamart/constants.py:23] |
| **merge window** | 15-minute same-user same-session window folding callbacks into one order [c:5d1300d] |
| **model_scores** | v4 output, = 0.9755 x v2 score [Q35] |
| **order_lines** | per-item rows from 2019-11-22 [Q16] |
| **payment_ref** | gateway ref `PR-<session8>-<pid>`; not unique historically [Q06] |
| **random arm** | 5% of uids by sha256 hash; pool = 500 lowest product ids [Q38] |
| **report_rows** | daily_report output (per-day per-product units/revenue) [Q08] |
| **restatement** | corrected statements via overrides + chargebacks [Q03a-c] |
| **sentinel -1** | affinity score meaning "fewer than 3 pairs"; serving must filter `score>=0` [f:novamart/jobs/affinity.py:1-8] |
| **shadow** | computed but unused output (price_suggestions) [f:novamart/jobs/price_suggest.py] |
| **statements / _corrected / _final** | published / + fee override / + chargebacks [3.4] |
| **test_users** | `analytics.test_users` = {424242} [Q24] |
| **trending** | 30d, min 5 units, decayed, top 50 [Q43] |
| **2026-08-13** | warehouse load date baked into `now()` defaults [Q58] |

---

# Appendix A - Commit-by-commit map (non-deploy commits, 77 of 112)
Dates are authoring dates (UTC). Full diffs: `intermediate/git_log_full.txt`. Key: DK = Dev Kapoor, MI = Maya Iyer, NP = Novamart Platform.

| Commit | Date | Who | Effect |
|---|---|---|---|
| 2da4141 | 09-15 | MI | initial import (README, CI, crontab 3 jobs, 3 dashboards, orders/catalog/carts, schema) |
| 83fb3ed | 10-08 | DK | EXCLUDED_SKUS populated |
| 776d674 | 10-12 | DK | nightly `affinity` |
| b676969 / 7f24380 | 10-15 | MI | idempotent orders / duration_ms log |
| 088a372 | 10-16 | MI | email-update endpoint (later unmounted) |
| 030d841 | 10-18 | DK | RECONCILE_BATCH 100 -> 200 |
| ea0e97b | 10-21 | DK | repair blank brands |
| 193f22d | 10-21 | MI | `/reports/brands` (later unmounted) |
| ba1fbfa | 10-25 | DK | denylist lucente |
| f1217a8 | 10-26 | MI | similar widget; unmounts reports+users |
| 8f19718 | 10-28 | MI | cancel endpoint; STATUS_CANCELLED 4->2 |
| a92c96d | 11-02 | DK | statement fee = collected |
| 152a760 | 11-02 | DK | trending (60d) |
| 102c9b4 | 11-05 | DK | DST-safe day windows |
| 9a51155 | 11-06 | DK | top_sellers |
| 4dbcf7f | 11-08 | DK | funnel (30 min gap) |
| d213f6e | 11-09 | MI | price feed upsert |
| 388370b | 11-10 | DK | reconcile 02:00 -> 03:00 |
| fef5c96 | 11-12 | DK | affinity MIN_PAIRS gate (-1 sentinel) |
| 795d273 | 11-15 | DK | `analytics.price_history` |
| d87cb3d | 11-15 | MI | refund endpoint, status 3 |
| 14726e7 | 11-16 | DK | kpi_daily |
| 11c0a42 / 1233af8 | 11-18/19 | DK | report excludes 0,2,3 / remove scan cap |
| 12e1c68 | 11-20 | MI | fee +$0.30 |
| 35c581e | 11-21 | DK | DISCOUNT_CAP 0.25 + rerun helper (default 0.40) |
| 5d1300d | 11-22 | MI | order_lines + merge |
| 894c535 | 11-24 | DK | price_suggest (shadow) |
| f5e3032 | 11-26 | DK | reorder hints (K=141.12) |
| b59f077 | 11-27 | DK | QA user exclusion |
| b567d9d | 11-27 | MI | accounts endpoint |
| c19a307 | 11-28 | MI | email digest |
| 2814b3d | 11-30 | DK | category revenue + mapping |
| 4a58d17 | 12-02 | DK | flat fee in statement expectation; Nov correction row |
| 89666bf | 12-02 | DK | affinity v2 |
| cca9b0d | 12-02 | MI | pricing on hold |
| e4656fb | 12-03 | DK | fraud scoring (0.90) |
| e10cb0c | 12-04 | MI | contactable users |
| c49a7bb | 12-05 | MI | gateway refund webhook (unmounts accounts) |
| 92596dc | 12-05 | DK | order_lines counting |
| 53f6f6c | 12-05 | MI | threshold 0.70 |
| 3dbe4d7 | 12-05 | DK | v2 December crash fix (stamp 2.0.1) |
| f563dea | 12-06 | DK | trending 30d |
| df4ed85 | 12-06 | MI | widget dispatch + random arm |
| a2e0013 | 12-08 | DK | intraday report |
| cd559d3 | 12-09 | DK | chargebacks + statements_final |
| 8dc520b | 12-09 | MI | digest flag name fix |
| d6e34c6 / b975479 | 12-10 / 12-21 | MI | registered conversion + id-namespace fix |
| 2dde4f0 | 12-11 | MI | board actives |
| 33054cd | 12-12 | DK | versioned taxonomy |
| 8584613 | 12-13 | DK | trending notes |
| a1946ff | 12-14 | DK | model v4 |
| f915c1b | 12-14 | DK | funnel gap 120 |
| 1169e40 | 12-15 | MI | jetem denylist |
| 0bd4eac | 12-16 | MI | digest reads cron.env |
| 30e8907 | 12-17 | MI | similar refactor (drops random logging) |
| adbcb7e | 12-18 | DK | QA UUID in brand revenue |
| a00f24c | 12-19 | MI | restore logging; add cache |
| 686a5d6 / 3eced24 | 12-19 / 12-24 | MI / DK | revenue widget / de-dup |
| a9a4b0b | 12-20 | MI | dashboard notes |
| f85cdd2 | 12-21 | DK | reorder K 162.4 |
| 4396fbb | 12-22 | MI | rec_versions "TBD" |
| a3bffec | 12-23 | DK | refunds view/dashboard |
| 2885137 | 12-26 | DK | affinity lineage doc |
| 8ed2971 | 12-26 | MI | cache invalidation |
| d2481be / 442b135 | 12-27 / 12-28 | DK | pricing and forecast docs |
| 1cb8721 | 12-29 | MI | threshold 0.85 (+manual release) |
| dd0c8fc | 12-29 | MI | active-customer doc |
| a576d0d | 12-30 | DK | restatement policy |
| d398b0d, 41e3537, 4bfcbe6, 5ae1182 | 01-02..05 | NP | data-access doc, Redash move, Airflow, backfill |

# Appendix B - Redash catalog
| Dash id | Name | Query id | Source SQL (see [git:old-sql]) | Key caveat |
|---|---|---|---|---|
| 1 | refunds | 1 | `analytics.refunds_unified` by month | cancels counted as refunds; gateway triple count [Q12] |
| 2 | revenue_widget | 2 | latest `report_rows` per closed day + latest intraday for today (7 days) | depends on job snapshots, not orders [c:3eced24] |
| 3 | actives_board | 3 | 30d actives with email filter | returns 0 [Q21] |
| 4 | registered_conversion | 4 | accounts -> users by email -> orders status=1 | id namespaces [c:b975479] |
| 5 | statements_final | 5 | `SELECT * FROM analytics.statements_final` | [Q03c] |
| 6 | category_revenue | 6 | 30d, taxonomy lookup | history rows dated 2026-08-13 [Q30] |
| 7 | best_sellers | 9 | 7d by revenue | no status/SKU filter [Q26] |
| 8 | brand_revenue | 8 | 30d by brand | blank-brand bucket |
| 9 | daily_kpis | 7 | 14-day daily orders(units)/revenue/actives/contactable | "orders" = SUM(units) (items); contactable always 0 [Q19] |
All: data source `novamart` (pg, host `estate-pg`), no schedule, Admin-owned, no cached result [rd:data_sources/1].

# Appendix C - Replayed dashboard values (as-of 2019-12-31 17:00Z, BigQuery dialect)
- best_sellers top 10: Q26. daily actives (dashboard definition) 12-25..12-31: 56, 65, 63, 47, 75, 65, 54 (`intermediate/dash_daily_actives.txt`). 30d buyers (any status) 1,155 [Q21].
- These are *replays* of the SQL files, not Redash outputs (no query was executed in Redash).

# Appendix D - Documentation reliability audit
| Doc / claim | Verdict | Evidence |
|---|---|---|
| README: rec v4 features include region, device, opt-in, stock | **Wrong**: 5 features (n_items, price, popularity, account age, organic flag); opt-in/stock fetched, unused | [f:novamart/jobs/model_train.py:44-56] |
| README: trending uses 60-day window | **Stale** (30d since 12-07) | [Q43][doc:docs/trending_notes.md] |
| README: "Serving is version 4.0.0 behind REC_MODEL_VERSION" | **Misleading**: flag is 2.0.0 and no 4.0.0 row ever logged | [Q33][f:deploy/flags.env:4] |
| docs/restatement_policy.md numbers (1194652.79 / .93 / 1191085.36; chargebacks 3567.57) | **Correct** but incomplete (no mention of later cancels/refunds, duplicates, overlap of chargebacks with cancelled orders) | [Q02, Q03, Q04] |
| docs/metrics_definitions.md (3 actives definitions) | **Correct as code**; omits that the board definition returns 0 on real data | [Q21] |
| docs/dashboard_notes.md | Correct on filters; `'cc27b436-...'` exclusion is dead (BIGINT user_id); doesn't mention SKU/status gaps | [Q27][git:old-sql brand_revenue] |
| docs/affinity_lineage.md | Correct that widget moved to v2 on 12-06 (reads: v1 392,630 until 12-06) ; omits 76% fallback and `model_version` 2.0.1 vs 2.0.0 label risk it half-mentions | [Q55][Q33] |
| docs/pricing_status.md | **Correct** (write-only table) | [Q55] |
| docs/forecast_caveats.md | Correct; snapshot range slightly differs by day (now velocity 0.0714-2.7143, hints 51-102) | [Q45] |
| docs/trending_notes.md | **Correct** | [Q43] |
| docs/data-access.md: dataset `analytics` | **Wrong name** (`novamart_analytics`) | bq ls |
| docs/rec_versions.md | "TBD" (this document fills it) | [doc] |
| Commit 1cb8721 message "release held orders under $2600" | The release is **not in the commit**; it was a manual UPDATE | [Q57][c:1cb8721] |

# Appendix E - Open questions and unverified hypotheses
1. **Redash was not executed** (read-only rule), so actual Redash outputs/timings are unknown. Inference: queries run against Postgres `estate-pg` with `now()`; evaluated today they would return empty windows for 2019 data. Not verified.
2. **Airflow timezone**: DAG files carry no timezone; whether schedules fire in UTC or NY time is unknown here (flag only). If UTC, `intraday_report` (12:00) and `daily_report` (06:00) would shift 4-5 hours relative to crontab semantics.
3. **What happened on 2019-11-15** (no orders despite ~1,175 sessions with carts) - outage vs data loss is not determinable from logs (no ERROR-severity app events) [Q17, Q51].
4. **Were duplicate-ref orders real double charges?** They share one gateway ref and identical amounts minutes apart; payments rows also duplicated (fees collected twice) - cash impact needs gateway reconciliation [Q05].
5. **Whether SKU 1002544 is genuinely a test SKU** (looks like a mislabeled apple smartphone with $66k revenue) [Q27].
6. **Source of chargebacks**: table was seeded by selecting the first three Oct orders >$700; there is no ingestion job [Q04].
7. The warehouse copy of `report_rows` contains no duplicate versions, although engineers queried duplicates on 2019-11-19 [log:db_queries 2019-11-19]; either re-run versions were cleaned or the warehouse load kept the latest only.

# Appendix F - Reproduction & files
- `evidence_queries.py` -> `intermediate/evidence_outputs.txt` (78 numbered read-only queries with SQL and output).
- `intermediate/git_log_full.txt` (all diffs), `manual_stmts.txt` (human DB sessions), `analytics_stmts.json` (app/job statements touching analytics), `redash/` (dashboard & query JSON), `daily_recon.txt`, `dash_asof.sql`, `views.txt`.
- `q.sh` helper (BigQuery CLI wrapper). Run `source access-pack/env.sh` first.

# Appendix G - Run notes and full citation key
- **Run start (wall clock):** 2026-10-05 16:42:34 UTC; **UUID** `7e2e46b6-6d34-46d8-90a8-36724dbf7843` (all outputs live in this directory).
- **Sources used (only these):** repo `novamart` pinned at `5ae1182` (112 commits, 2019-09-15 -> 2020-01-05); BigQuery emulator project `novamart-warehouse` (datasets `novamart`, `novamart_analytics`, `novamart_logs`); Redash at `localhost:5055` (read-only GETs only). The task brief's own docs in `docs/` were treated as claims to verify, not as truth.
- **Data window:** orders 2019-09-25 12:30Z -> 2019-12-31 16:51Z [Q59a, Q01]; no January 2020 data, so no December statement exists [Q02].
- **Safety:** only SELECTs / read-only API GETs. Nothing in Redash was created, edited, archived or refreshed (so no dashboard was *executed*; see Appendix E). The repo and GitHub were not touched.
- **Emulator note:** the BigQuery emulator is DuckDB-backed; a few heavy window/join queries stalled it, so evidence queries were kept simple; `UNION ALL` of unlike selects crashes the `bq` CLI printer (split into separate queries).

| Tag | Meaning |
|---|---|
| `[c:abc1234]` | commit in the repo (`git show abc1234`) |
| `[f:path:line]` | file at pinned HEAD `5ae1182` |
| `[bq:dataset.table]` | warehouse table / view (`novamart`, `novamart_analytics`, `novamart_logs`) |
| `[Qnn]` | numbered query in `intermediate/evidence_outputs.txt` (SQL + output; re-run with `evidence_queries.py`) |
| `[log:job_runs]` `[log:app_events]` `[log:db_queries]` | BigQuery log exports (queries Q48-Q57, Q71) |
| `[rd:dash N / query N]` | Redash dashboard / query id (`intermediate/redash/`) |
| `[doc:file]` | `docs/*.md` or README in the repo |
| `[git:old-sql]` | dashboard SQL as of `41e3537^` (`git show 41e3537^:dashboards/<name>.sql`) |
