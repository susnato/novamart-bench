# Novamart — Tribal Knowledge Handbook

- Run id (uuid): `836e33ed-6ad0-4508-b7e2-40dabef4a8d9` · started `Mon Oct 5 18:18:53 UTC 2026`
- Sources used (only these): repo `novamart` pinned at `5ae1182` (plus its git history); BigQuery emulator project `novamart-warehouse` (datasets `novamart`, `novamart_analytics`, `novamart_logs`); Redash at `localhost:5054` (read only, nothing was executed or refreshed).
- How to read the citations:
  - `[c:<hash>]` is a git commit.
  - `[f:<path>]` is a file at the pinned commit.
  - `[t:<dataset.table>]` is a warehouse table or view.
  - `[Qn]` is a warehouse query. Its SQL and result are in Appendix B, and every query I ran, with its raw output, is in `queries_log.md` in this folder.
  - `[E:<timestamp actor>]` is a statement from the historical query log (`novamart_logs.db_queries`). The engineer statements are extracted to `eng_queries.tsv`.
  - `[R:<id>]` is a Redash query or dashboard. Snapshots are in `redash/`.
- Data time window: the operational data runs from 2019‑09‑25 12:30 UTC to 2019‑12‑31 23:57 UTC [Q1][Q16]. The code history runs from 2019‑09‑15 to 2020‑01‑05 [c:2da4141][c:5ae1182].

---

## 1. Summary

**What novamart is.** Novamart is a single‑service FastAPI + Postgres marketplace backend [f:README.md].
- Orders are created by payment‑gateway callbacks [f:novamart/routers/orders.py].
- About 15 nightly batch jobs build every reporting table [f:airflow/dags/*].
- Exec dashboards live in Redash and query the serving Postgres directly [R:data_source 1 → host `estate-pg`, type `pg`].
- BigQuery is a one‑shot backfilled copy of that Postgres [f:airflow/dags/warehouse_backfill_dag.py `schedule=None`].

**What a tenured person knows that the docs do not say:**

1. **"Revenue" has at least eight different numbers.** For October 2019:
   - The published statement says gross **$1,230,332.43** (net $1,194,652.79) [t:novamart.statements].
   - The "restated" view says gross **$1,226,764.86** (net $1,191,085.36) [t:novamart_analytics.statements_final].
   - Recomputing today with the statement's own logic gives **$1,206,337.32** [Q3].
   - Removing duplicate replayed orders and QA orders gives **≈$1,147,459** [Q36].
   - The daily report sums to **$1,201,082.08** [Q36].

   Every one of these is "right" for some consumer. Section 4.1 explains which one to use.
2. **The "chargebacks" behind the official restatement are not real.** On 2019‑12‑09, an engineer filled `analytics.chargebacks` with "the first 3 October orders over $700" and a hard‑coded `reported_at` [E:2019‑12‑09 15:00 engineer‑backfill:dev]. `statements_final`, which `docs/restatement_policy.md` calls the current finance number, subtracts those $3,567.57 [t:statements_final][f:docs/restatement_policy.md].
3. **Since 2019‑11‑22 most order callbacks fail before an order is written.** The merge‑orders change [c:5d1300d] runs DDL (`ALTER TABLE payments …`) inside every order request. From then until 2019‑12‑31:
   - 7,113 order requests reached the `ALTER`.
   - Only 2,981 got past it [Q18].
   - Daily orders fell from about 115 to about 35–70, while traffic and carts did not fall [Q4][Q17].

   This is the main reason December revenue (about $552K) is roughly half of November's [Q3]. Lock contention/deadlock from DDL in the request path is my **inference** from the statement log: the statements are logged right before they run [f:novamart/db.py], and the next statement never appears.
4. **The October statement double counts.** Before the idempotency fix [c:b676969, 2019‑10‑15], gateway callback replays created duplicate orders:
   - 130 payment refs have 285 orders in total [Q5].
   - 151 excess duplicates worth $58,828.24 are still `status=1` and inside October's gross.
   - The nightly `reconcile` job flags the same 130 refs every night and nothing ever fixes them [Q41].
5. **Refunds are invisible to revenue.**
   - Refunds and cancellations only flip `orders.status`. Payments are never reversed [f:orders.py].
   - Gateway refunds (refunds v2) insert negative `payments` rows without touching the order. The webhook is not idempotent: 3 real refunds were replayed weekly into 9 rows [Q7].
   - `analytics.refunds_unified` counts cancellations as refunds and triple counts the gateway refunds [Q9].
6. **Two of the "test SKUs" excluded from the daily report are real phones** [Q14]:
   - `1004856` is a Samsung phone whose product row was first created by the QA smoke test, so it is permanently titled "Internal Test" (about $40.8K of real sales).
   - `1002544` is an Apple smartphone with no QA orders ($66.7K).

   "Internal Test #4856" is the #2 trending product served to customers [Q35].
7. **Customer counts disagree by design, and two of them are broken** [Q20][Q31]:
   - The board‑deck "active customers" query returns **0**: its email heuristics exclude `example.com` (every auto‑created user) and `*.example`.
   - `contactable_customers` is always **0**.
   - The marketing digest emails 40 users and ignores opt‑in. 17 of them never opted in, and one is the QA account.
8. **The ML is weaker than it looks** [Q22][Q24][Q38]:
   - The similar‑products widget falls back to trending or bestsellers for most requests: 83% under v1 and about 76% under v2.
   - The "trained v4 model" has never served a request: the flag is `2.0.0`, although the README says 4.0.0.
   - Its scores are a constant multiple of the affinity‑v2 scores, so even if switched on it would rank identically.
   - Its training data had a 2‑day logging gap and only five features (one of them constant), versus the nine the README claims.
9. **Fraud scoring is a price threshold that mutates orders.**
   - It moves any order over about $2,550 to status 6 ("held"). No release workflow exists except a manual `UPDATE` [E:2019‑12‑29 engineer‑backfill:maya].
   - Held orders are excluded from statements but included in the daily report and dashboards [Q11][f:constants.py].
10. **Every rolling‑window dashboard (`now() - interval …`) returns empty on today's frozen data.** Its numbers can only be reproduced by re‑anchoring to 2019‑12‑31 [R:1‑9]. The Jan‑2020 Airflow migration also changed job timing: it dropped the 17:00 intraday run, and cron local times became, by default, UTC [f:crontab.txt][f:airflow/dags/intraday_report_dag.py].

---

## 2. Why this project

- **The code, docs and data disagree, and the docs are partly wrong.**
  - The README says trending uses a 60‑day window. The code has used 30 since [c:f563dea] [f:docs/trending_notes.md][Q41].
  - The README says rec v4 serves at 4.0.0, but `deploy/flags.env` is `REC_MODEL_VERSION=2.0.0` and every logged decision is intended 2.0.0 [f:README.md][f:deploy/flags.env][Q22].
  - `docs/rec_versions.md` just says "TBD".
  - `docs/restatement_policy.md` recommends a view built on fabricated chargebacks (§1 item 2).
- **Finance numbers have been patched by hand in production.** Overrides, a "correction" row with delta 0, synthetic chargebacks and released fraud holds were all ad‑hoc SQL by two engineers, Dev Kapoor and Maya Iyer [eng_queries.tsv]. None of it is in code review.
- **The platform just migrated** (Jan 2020): dashboards moved to Redash [c:41e3537], schedules to Airflow [c:4bfcbe6], and a warehouse backfill was added [c:5ae1182]. At the pinned commit the backfill writes analytics tables to a dataset named `analytics`, which does not exist in the warehouse; it was fixed only later on `origin/main` [c:20e066f][c:99003c3]. Whoever touches the pipelines next needs to know what silently changed.
- **Goal.** Answer "what was revenue in month X and why", explain every dashboard number including when not to trust it, judge whether the ML works, and safely change the batch pipelines.

---

## 3. Business understanding

**The business model.** A marketplace selling mostly consumer electronics (Apple and Samsung smartphones dominate) [Q33][Q35].
- Prices arrive from vendor feeds (`/catalog/prices`), but the charged price is whatever the gateway callback sends (`body["price"]`) [f:routers/catalog.py][f:routers/orders.py].
- Novamart pays a processor fee per transaction:
  - 2.9% until 2019‑11‑20 [f:constants.py FEE_RATE].
  - 2.9% + $0.30 from 2019‑11‑20 [c:12e1c68][f:jobs/monthly_statement.py FEE_CHANGE_AT].

**Company time zone.** Business days and months are `America/New_York`. Stored timestamps are UTC [f:constants.py LOCAL_TZ][f:jobs/timeutil.py].

**The order lifecycle** (status codes are integers on `orders.status`):

| code | meaning | set by | evidence |
|---|---|---|---|
| 0 | pending (inserted, then immediately set to 1 in the same request) | `create_order` | [f:orders.py] |
| 1 | paid / completed | `create_order`, merge, manual release of holds | [f:orders.py][E:2019‑12‑29 maya UPDATE] |
| 2 | cancelled. Can cancel a **paid** order, and no payment reversal is written. Was code 4 before [c:8f19718]; no status‑4 rows exist [Q3] | `/orders/{id}/cancel` | [f:orders.py][c:8f19718] |
| 3 | refunded. Status flip only, no money row | `/orders/{id}/refund` (since [c:d87cb3d] 2019‑11‑15) | [f:orders.py] |
| 5 | referenced only by `reconcile` (`status <> 5`). Never used anywhere | — | [f:jobs/reconcile.py] |
| 6 | fraud "held" | nightly `fraud_score` | [f:jobs/fraud_score.py][Q11] |

**Operating rhythm seen in the data:**
- Cancellations and refunds are applied in weekly batches on **Tuesdays at 16:00 UTC** (11/5 … 12/31), and they target the oldest orders (Sept 30 / Oct 1) [Q10].
- Gateway refund webhooks arrive on **Fridays at 15:30 UTC**. The same 3 refunds were replayed every week [Q7].

**Customers.** There is no signup flow in the data.
- A `users` row is auto‑created the first time any user id is seen: product view, cart or order. It gets the email `user<id>@example.com` and synthetic profile attributes hashed from the id [f:routers/catalog.py ensure_entities][f:onboarding.py].
- A "registered accounts beta" (`accounts`, `account_map`) has exactly 30 accounts, all created 2019‑12‑01 16:30 UTC [Q21]. The `/accounts` router was unmounted on 2019‑12‑05 when the gateway webhook was added [c:c49a7bb].
- 40 users changed their email to `cust<id>@gmail.example`, all on 2019‑10‑23 [Q16][Q20]. The `/users/{id}/email` router was mounted only between 2019‑10‑16 and 2019‑10‑26 [c:088a372][c:f1217a8].

**Business events in the data:**

| when (ET) | event | evidence |
|---|---|---|
| 2019‑09‑25 | first order: QA smoke user 424242 buys SKU 1004856 at $9.99 | [Q14][Q16] |
| 2019‑10‑01 | real traffic starts; large `lucente` catalog import | [Q4][Q15][f:docs/dashboard_notes.md] |
| 10‑01 → 10‑15 | duplicate orders from replayed callbacks | [Q5] |
| 2019‑11‑14 → 11‑17 | traffic surge (views 17–28K/day vs about 9K) | [Q17] |
| 2019‑11‑15 | **zero orders** despite 27.6K views and 2.1K carts. No `INSERT INTO orders` in the db log that day | [Q17] |
| 2019‑11‑16/17 | 401 / 735 orders. The Nov‑17 daily report was capped at 500 rows | [Q4][Q17] |
| 2019‑11‑22 21:59 UTC onward | merge deploy; about 58% of order requests fail before writing | [Q18] |
| 2019‑12‑03 | eight $2,999.99 orders, later held by fraud | [Q11] |

---

## 4. Metrics

### 4.1 Revenue: every definition in use

| # | Name / consumer | Definition | Includes / excludes | Evidence |
|---|---|---|---|---|
| R1 | **Published monthly statement**: board deck "as published" | `SUM(orders.price)` where `status=1` and `created_at` is in the ET month, **as of the run moment** (1st of the month, 06:30 local) | Includes duplicates, QA orders, test SKU 1004856, lucente, and orders later cancelled or refunded. Excludes held (6). **Fee** = SUM of collected `payments.fee` since [c:a92c96d]; before that, `gross*2.9%`. Net = gross − fee. Append‑only | [f:jobs/monthly_statement.py][t:novamart.statements] |
| R2 | `analytics.statements_corrected` | R1 with `statement_overrides` per month (COALESCE) | Only Oct‑2019 overridden: fee 35,679.64 → 35,679.50 | [t:statements_corrected][E:2019‑11‑02 dev INSERT overrides] |
| R3 | `analytics.statements_final`: "current finance number" per [f:docs/restatement_policy.md]; Redash dashboard `statements_final` | R2 minus `chargebacks` grouped by the **order's** ET month | Chargebacks are fabricated (3 orders, $3,567.57). Fee is not adjusted | [t:statements_final][E:2019‑12‑09 dev INSERT chargebacks][R:5] |
| R4 | **Live recompute** of R1 logic | same SQL run today | Drifts as statuses change: Sept went from $2,702 → $0 and Oct dropped $23,995.11 | [Q3] |
| R5 | **Daily report** (`report_rows`), which feeds the `daily_kpis` and `revenue_widget` dashboards | Per product per ET day: item lines (`order_lines`, falling back to `orders`) with `status NOT IN (0,2,3)`, minus `analytics.test_users`, minus `EXCLUDED_SKUS`, minus `BRAND_DENYLIST`, snapshotted at about 06:00 local the next day | **Includes held (6)**. Excludes two real SKUs. Never restated after later cancellations | [f:jobs/daily_report.py][f:constants.py] |
| R6 | Intraday (`report_rows_intraday`) | Same as R5 for "today so far", 2 snapshots/day (12:00 and 17:00 ET), append‑only | same | [f:jobs/intraday_report.py][Q37] |
| R7 | Dashboard item revenue (best sellers 7d, brand 30d, category 30d) | Item lines (`order_lines` + legacy fallback) over a rolling window from `now()` | **No status filter**, so cancelled, refunded and held count. Excludes user 424242 and lucente/jetem. Does **not** exclude SKU 1004856 | [R:9][R:8][R:6][f:docs/dashboard_notes.md] |
| R8 | Cash view (`payments`) | `SUM(gross)` by payment date | Duplicates have payments. Cancelled and refunded orders keep their positive payment. Gateway refunds are negative (×3 replays) | [Q6][Q36] |
| R9 | `/reports/brands` endpoint | `orders.price`, status=1, local month, minus SKUs and denylist, grouped by the first product's brand | Router unmounted since 2019‑10‑26, so dead code | [f:routers/reports.py][c:f1217a8] |

**Monthly revenue under the main definitions** (2019, ET months) [Q2][Q3][Q36]:

| Month | R1 published gross (net) | R3 statements_final gross (net) | R4 recompute today (status=1) | Held (6) not in R4 | R5 daily report sum | R8 payments gross | R4 minus duplicates and QA ("economic") |
|---|---|---|---|---|---|---|---|
| 2019‑09 | 2,702.00 (2,623.64), 12 orders | 2,702.00 (2,623.64) | 0.00 (all 12 later cancelled or refunded) | 0 | 2,702.00 | 2,702.00 | 0 |
| 2019‑10 | 1,230,332.43 (1,194,652.79), 3,765 | 1,226,764.86 (1,191,085.36) | 1,206,337.32 (3,695) | 0 | 1,201,082.08 | 1,230,332.43 | 1,147,459.13 (3,539) |
| 2019‑11 | 1,101,397.01 (1,069,286.09), 3,582 | 1,101,397.01 (1,069,286.09) | 1,101,397.01 (3,582) | 0 | 966,974.33 | 1,101,397.01 | 1,101,357.05 |
| 2019‑12 | **not published** (would run 2020‑01‑01) | — | 552,328.93 (1,756) | 40,213.29 (12) | 535,561.72 (Dec 1–30) | 590,698.63 (incl. −1,843.59 refunds) | 552,288.97 |

**How to answer "what was October revenue, and why"** (the tenured‑person answer):
1. The board saw **$1,230,332.43 gross / $1,194,652.79 net** [t:statements created 2019‑11‑01 10:30 UTC].
2. Two days later the fee was corrected by $0.14. It was a rounding issue: the sum of per‑order rounded fees vs the rounded sum [E:2019‑11‑02 dev queries][Q28 delta 0.14]. Net becomes $1,194,652.93 [t:statement_overrides].
3. `statements_final` subtracts $3,567.57 of "chargebacks" (orders 46, 49 and 55) [Q8]. Those rows were invented by query [E:2019‑12‑09]. Do **not** present 1,191,085.36 as a restated audited number.
4. Problems still inside the October gross:
   - $58,828.24 of duplicate replayed orders (151 orders) [Q5].
   - $23,995.11 of orders cancelled or refunded after publication (70 orders), none of which reversed a payment [Q3][Q10].
   - QA user orders ($49.95) [Q36].
   - Removing all of these gives an economic October of about **$1.147M**. Orders 46, 49 and 55 are both "chargebacks" and cancelled/refunded, so do not subtract them twice [Q8].

**November:** published $1,101,397.01 still equals the recompute, because no November order changed status [Q3]. The fee mismatch warning of −170.41 is the new $0.30 flat fee (about 568 orders after 11‑20), which the expectation code didn't handle until [c:4a58d17] [Q28]. Two caveats:
- November was depressed by the 11‑15 outage (0 orders) and by the post‑11‑22 order loss [Q17][Q18].
- The "November audit correction" row in `statement_corrections` has delta **0.00** and nothing reads that table [Q2][E:2019‑12‑02 dev INSERT corrections][t:statements_corrected definition].

**December:** about $552K paid, plus $40K held [Q3]. Lost order callbacks are the dominant reason it is about half of November [Q18].

### 4.2 Orders, units, payments, fees, refunds

- **What "orders" means.** One `orders` row can hold several items since [c:5d1300d]: callbacks from the same user and session within 15 minutes are appended. `orders.price` becomes the running total, but `orders.product_id` stays the **first** item [f:orders.py].
  - 173 orders have more than one line.
  - 225 appended lines worth $52,812.06 are attributed to the wrong product by every `orders.product_id`‑based job: top_sellers, trending, price_suggest, reorder_forecast, email_digest, affinity_v2 conversion, model_train popularity [Q19].
- **Units.** Dashboards and the daily report count item lines ([c:92596dc], 2019‑12‑05). `top_products.units` counts orders [f:jobs/top_sellers.py]. The `daily_kpis` column named "orders" is actually `SUM(units)` [R:7].
- **Payments.** There is one positive payment row per item callback. Of 9,361 rows, 7,077 have NULL `payment_ref` (rows written before the column existed, plus gateway refunds) [Q6]. `payments.payment_ref` was added at runtime by the order request [f:orders.py].
- **Fees.** The per‑row fee is `round(price*0.029 [+0.30],2)` [f:orders.py]. The statement fee is the sum of collected fees. The "expected fee" check only logs `statement_fee_mismatch`. Since [c:a92c96d] the log field `statement_fee` carries the *expected* (formula) fee and `collected_fee` carries the fee actually written to the statement, so the names are misleading [f:monthly_statement.py][Q28].
- **Refunds.** Four mechanisms, none reconciled:
  1. Status 3 via endpoint (28 orders).
  2. Cancel of a paid order, status 2 (54).
  3. Gateway webhook negative payments (9 rows = 3 refunds × 3 replays).
  4. "Chargebacks" table (synthetic).

  The `refunds` dashboard reads `analytics.refunds_unified`, which unions 1 + 2 + 3: Nov: 32 refunds / $9,691.77; Dec: 59 / $18,848.93. It dates each row by status‑change or payment time, not order month [Q9][R:1][t:refunds_unified].

### 4.3 Product metrics

| Metric | Source | Gotchas | Evidence |
|---|---|---|---|
| Best sellers (exec dashboard) | rolling 7×24h, item lines, **ranked by revenue** (not units), no status filter, minus 424242, minus lucente/jetem | Held orders appear. On 2019‑12‑31, #3 was Samsung 1005284: 2 units, both held. "Internal Test #4856" (a real Samsung phone) is *not* excluded | [R:9][Q33][f:docs/dashboard_notes.md] |
| Top sellers (nightly) | `top_products`: yesterday ET, `orders.product_id`, status=1, top 50 by order count | No SKU, brand or test‑user filter. Merged items invisible. Reruns append duplicates | [f:jobs/top_sellers.py][Q35] |
| Trending (homepage + widget fallback) | `analytics.trending_daily`: 30‑day window (60 until 2019‑12‑06), ≥5 units, recency decay, top 50, status=1, `orders.product_id` | No exclusions, so "Internal Test #4856" ranks #2 on 2019‑12‑31 | [f:jobs/trending.py][Q35][Q41] |
| Brand revenue (dashboard) | 30d item lines; excludes 424242 and its account UUID string | Blank brand shows as `''` ($17.4K in last 30d); brand `internal` is the Samsung phone mislabeled | [R:8][Q33][c:adbcb7e] |
| Category revenue (dashboard) | 30d; display group from `category_names` / `category_name_history` with `valid_from <= order date` | History rows (lighting / entertainment) carry `valid_from` = the load date. In the warehouse that is **2026‑08‑13**, so the remap never applies to 2019 orders. The original insert used `CURRENT_DATE` [E:2019‑12‑12 dev] | [R:6][Q34] |
| Brand repairs | Blank brands come from first‑sight inserts (`ON CONFLICT DO NOTHING`); repaired only when a later event carries a brand | 648 orders / $94.4K on blank‑brand products all‑time; `analytics.blank_brand_products` snapshot | [Q15][c:ea0e97b][E:2019‑10‑21 dev] |
| Exclusions | `EXCLUDED_SKUS=[1004856,1002544]` [c:83fb3ed]; `BRAND_DENYLIST` lucente [c:ba1fbfa] + jetem [c:1169e40] | jetem has 5 products and **0 orders**. lucente has 141 orders / $43.3K. Both "test SKUs" are real phones | [Q14][Q15] |

### 4.4 Customer metrics

| Metric | Consumer | Definition | Value (end of 2019) | Evidence |
|---|---|---|---|---|
| `kpi_daily.active_customers` | nightly KPI table | distinct `orders.user_id`, status=1, created ≥ run_ts − 30 days. No QA, SKU or brand filter. Appended per run | 1,152 (run 2019‑12‑31 11:15 UTC) | [f:jobs/kpi_daily.py][Q30] |
| `daily_kpis.active_customers` | exec KPI dashboard | distinct ordering users per ET day, **no status filter**, minus 424242, minus orders whose **first** product is lucente/jetem | e.g. 54 on 12‑31, 65 on 12‑30 | [R:7][Q32] |
| `actives_board` | board deck | 30d, status ∉ {0,2,3} (so **includes held**), minus `test_users`, minus email heuristics | **0**, because every user's email is `@example.com` or `@gmail.example` (1,149 candidates → 0) | [R:3][Q31][Q20] |
| `contactable_customers` | daily_kpis | users in `analytics.contactable_users` (opt‑in AND valid email AND domain not example.* / *.example) | **0 always** (view returns 0 rows) | [t:contactable_users][Q20] |
| digest "recipients" | marketing email job | users whose email `NOT LIKE '%@example.com'`. **Ignores marketing_opt_in** | 40/day (17 not opted in; includes QA 424242) | [f:jobs/email_digest.py][Q20] |
| funnel `users_active`, `sessions` | `analytics.daily_funnel` | users with cart or order events in the trailing 24h at run time. Sessions split by a gap of 30 min, then 120 min from 2019‑12‑15 [c:f915c1b] | 308 / 345 on 12‑31 | [f:jobs/funnel.py][Q30][Q41] |
| registered buyers | `registered_conversion` dashboard | accounts → users **via email** → orders status=1 (ignores `account_map`) | 30 buyers / $18,155.71. Includes QA; every one of the 30 accounts is a buyer | [R:4][Q21][c:b975479] |
| "users" / signups | — | `users` rows are first‑seen ids, not signups | 38,950 users; 4,112 ever ordered | [Q1][Q40] |

**Rule of thumb.** Quote `kpi_daily` for a trailing‑30d paid‑buyer KPI, and state that it includes the QA user. Never quote `actives_board` or `contactable_customers` without explaining that they are structurally 0.

### 4.5 ML / system health metrics
- **Similar‑widget serve mix** [Q22]:
  - v1 era (10‑26 → 12‑06): 83% fallback (326,186 of 392,630).
  - v2 era (12‑06 → 12‑31): about 76% fallback (207,959), 19% model (52,695), 5% random arm (14,566), out of 275,220.
- **Proxy outcome.** Share of decisions where the user bought one of the shown items within 7 days: model (affinity v2) **1.43%**, trending fallback 0.35%, random arm 0.00% [Q25]. This is correlational: there is no click logging and affinity pairs are co‑carted.
- **Callback success rate since 11‑22:** 2,981 / 7,113 ≈ 42% [Q18].

---

## 5. System

### 5.1 Components
- **API** (`novamart/app.py`). Routers currently mounted: catalog, carts, orders, similar, payments_webhook [f:novamart/app.py].
  - Not mounted, but files present: `accounts` (dropped [c:c49a7bb]), `users` and `reports` (dropped [c:f1217a8]).
- **Logging.** Every SQL statement is logged *before* execution to `db_queries.log` (now `novamart_logs.db_queries`). App events go to `app.jsonl` (now `app_events`) and job runs to `jobs.jsonl` (now `job_runs`) [f:novamart/db.py][f:novamart/logutil.py].
- **Order path** (`POST /orders`) [f:routers/orders.py]:
  1. Per request, it runs `CREATE TABLE IF NOT EXISTS order_lines`, two `CREATE INDEX`, `ALTER TABLE payments ADD COLUMN IF NOT EXISTS payment_ref` and a partial unique index.
  2. It takes advisory locks on session and ref.
  3. If the ref has been seen, it replays idempotently.
  4. Otherwise it appends to an order from the same user and session in the last 15 min whose status is not 2 or 3. **This includes held (6) orders and flips them to 1**, a code‑level risk.
  5. Otherwise it creates a new order.

  The DDL is the probable cause of about 58% of requests aborting since 2019‑11‑22 [Q18].
- **Catalog** [f:routers/catalog.py]:
  - The product row is created on first sight with `ON CONFLICT DO NOTHING`, so whoever creates it first owns its metadata. That is how QA froze SKU 1004856 as "Internal Test" [Q14].
  - The price feed upserts `list_price` [c:d213f6e] and appends to `analytics.price_history` [c:795d273]. `price_history` has 1,400 rows across 241 products [Q-misc in queries_log].
- **Similar products** (`GET /products/{pid}/similar`): see §5.3.
- **Gateway refund webhook:** inserts a negative payment with no idempotency key [f:routers/payments_webhook.py][Q7].

### 5.2 Batch jobs (schedule, outputs, what breaks)

Jobs run via `python -m novamart.jobs.<name>`. All of them use autocommit connections, so DELETE + INSERT refreshes are **not atomic** and readers can see empty or partial tables [f:novamart/db.py job_connect]. Times below are crontab local times (ET) before the migration; Airflow cron strings use the same clock digits [f:crontab.txt][f:airflow/dags/*]. Observed run times in UTC confirm the ET cron [Q26].

| Job (cron ET) | Writes | Logic highlights | Consumers | If it fails / is rerun | Evidence |
|---|---|---|---|---|---|
| reconcile 03:00 | logs only (`duplicate_payment_ref`) | refs with >1 order, LIMIT 200 | none | Nothing breaks. Flags the same 130 refs nightly since 10‑19 | [f:jobs/reconcile.py][Q41] |
| affinity 03:30 | `analytics.product_affinity` (v1) | co‑cart pairs 30d, decay 0.05, `<3` pairs → −1 sentinel | **nobody since 2019‑12‑06 16:39** | safe to retire | [Q38][f:docs/affinity_lineage.md] |
| affinity_v2 03:45 | `analytics.product_affinity_v2` (stamped 2.0.1) | v1 + 3× conversion + same‑category ×1.15 + price‑ratio ×0.7, × seasonal factor (Dec=1.0, so a no‑op for ranking) | widget (v2 path), model_train | Crashed 12‑03 to 12‑05 (December IndexError [c:3dbe4d7]). A mid‑run failure leaves a partial table | [Q27][f:jobs/affinity_v2.py] |
| model_train 04:15 | `analytics.model_registry`, `analytics.model_scores` | logistic regression on random‑arm logs (see §5.3) | nobody (flag = 2.0.0) | none today | [Q24][Q38] |
| price_suggest 04:45 | `analytics.price_suggestions` (shadow, ±5%) | top 500 by 14d paid orders | nobody (Phase 2 on hold [c:cca9b0d]) | none | [Q38][f:docs/pricing_status.md] |
| trending 05:15 | `analytics.trending_daily` (delete + insert same day, idempotent) | §4.3 | homepage, **widget fallback** | Widget uses `MAX(day)`, so it shows stale lists | [f:jobs/trending.py][f:routers/similar.py] |
| fraud_score 05:45 | `analytics.order_risk` + **UPDATE orders status 6** | `min(price/3000,1)×(1+0.15 new_acct+0.15 velocity)` > threshold (0.90 → 0.70 [c:53f6f6c] → 0.85 [c:1cb8721]) | statements (via status) | Reruns duplicate `order_risk` rows. The "release under $2600" was a manual UPDATE, not code | [Q11][E:2019‑12‑29] |
| daily_report 06:00 | `report_rows` (append) | §4.1 R5 | daily_kpis, revenue_widget | A missing day vanishes from daily_kpis. A rerun appends a version (dashboards take `MAX(created_at)`; a naive SUM doubles) | [f:jobs/daily_report.py][R:7][R:2] |
| kpi_daily 06:15 | `analytics.kpi_daily` (append) | §4.4 | KPI | duplicates on rerun | [f:jobs/kpi_daily.py] |
| funnel 06:20 | `analytics.daily_funnel` (append) | §4.4 | — | duplicates on rerun | [f:jobs/funnel.py] |
| monthly_statement 06:30 on the 1st | `statements` (append) | §4.1 R1 | statements_corrected/final, board | A rerun adds a 2nd row per month; the views don't dedup | [f:jobs/monthly_statement.py][t:statements_corrected] |
| top_sellers 06:45 | `top_products` (append) | §4.3 | — | duplicates on rerun | [f:jobs/top_sellers.py] |
| reorder_forecast 06:50 | `analytics.reorder_hints` (overwrite) | `int(15.6 + K/(v+1.8))`, K 141.12 → 162.4 [c:f85cdd2]. **Higher velocity gives a lower hint** | advisory only (read once by an engineer) | none | [f:docs/forecast_caveats.md][Q38] |
| email_digest 07:15 | `analytics.digest_log` + sends email | §4.4. Gated by `ENABLE_DIGEST`, read from the env or the **relative path** `deploy/cron.env` | marketing | Effectively off until 12‑17 because of the flag‑name bugs [c:8dc520b][c:0bd4eac]. Under Airflow's working dir the relative path may not resolve | [Q20][f:jobs/email_digest.py] |
| intraday_report 12:00 and 17:00 | `report_rows_intraday` (append) | §4.1 R6 | daily_kpis (today), revenue_widget | **The Airflow DAG has only 12:00**, so the 17:00 snapshot is lost after migration | [f:crontab.txt][f:airflow/dags/intraday_report_dag.py][Q37] |
| warehouse_backfill (manual) | BigQuery | gcloud export → bq load `--replace` per manifest | warehouse | At the pin, analytics goes to the `analytics` dataset (wrong); fixed on main [c:20e066f] | [f:jobs/warehouse_backfill.py] |

**Migration risks for whoever edits these pipelines:**
- **No dependencies are encoded.** Each DAG is a single BashOperator, and ordering relies only on clock times (affinity_v2 → model_train; daily_report → dashboards) [f:airflow/dags/*].
- **The time zone may have shifted.** Airflow cron strings default to UTC unless the deployment overrides it (nothing in the repo sets a timezone). If not overridden, every job now runs 4–5 hours earlier in ET terms, and the 12:00 intraday becomes a 07:00 ET snapshot [f:airflow/dags/*][f:crontab.txt "times are local"].
- **Relative‑path flags.** `deploy/flags.env` and `deploy/cron.env` are read via relative paths [f:routers/similar.py][f:jobs/email_digest.py].
- **CI is thin.** It only exercises view → cart → order plus reconcile, daily_report and monthly_statement, on a single order [f:ci/run_ci.py]. It would not catch concurrency failures in `/orders`.
- **Ops helper.** `scripts/rerun_kpis.py` calls `apply_discounts` with the legacy default cap 0.40, not `DISCOUNT_CAP=0.25` [f:scripts/rerun_kpis.py][f:jobs/discounts.py]. No production rollup applies discounts at all (grep).

### 5.3 Recommendation / ML systems

| Version | Period | Serving logic | Logged as | Evidence |
|---|---|---|---|---|
| 1.0.0 | 2019‑10‑26 → 2019‑12‑06 16:39 UTC | `product_affinity` top 5 (score ≥ 0); otherwise 7‑day bestsellers | intended = effective = 1.0.0, `rec_source` affinity / fallback | [c:f1217a8][Q22] |
| 2.0.0 | 2019‑12‑06 16:40 → now | `product_affinity_v2` top 5 at the latest `updated_at`; otherwise **trending_daily** top 5. 5% of users (sha256(uid) % 20 == 0) get the "random" arm | intended 2.0.0; effective 2.0.0 or "fallback"; arm none/random | [c:df4ed85][f:routers/similar.py] |
| 4.0.0 | trained nightly since 2019‑12‑15, **never served** | would read `analytics.model_scores` | — | [c:a1946ff][Q22][Q38] |

**Does it work? Judgment:**
1. **Coverage is low.**
   - Only 948 usable (score ≥ 0) pairs over 1,476 base products out of 81,018 products [Q24 tables].
   - About 76% of v2 requests fall back to trending, which itself contains the mislabeled "Internal Test" SKU [Q22][Q35].
2. **The random arm is not uniform.**
   - It samples from the 500 **lowest product ids** (`ORDER BY id LIMIT 500`), currently ids 1,000,894–1,004,386 out of 81K products [f:routers/similar.py][Q39].
   - Its logging was lost from 2019‑12‑17 16:50 to 2019‑12‑19 14:55: about 1,372 impressions [c:30e8907][c:a00f24c][Q23]. Training rows were identical on 12‑18 and 12‑19 (5,798) [Q24].
   - Random‑arm rows log `effective_version=2.0.0` even though the items are random, so filter by `arm`/`rec_source`, not by version [Q22].
3. **v4 is not a model of item relevance.**
   - Its label is "user placed any paid order after the impression", with no time bound and no link to the shown items [f:jobs/model_train.py].
   - It has five features, one of which (`n_items`) is constant at 5 [f:jobs/model_train.py][f:routers/similar.py K=5]. The README claims 9 features.
   - Scores are `v2_score × (1 + 0.1·coef[n_items])`: a positive constant per night, so the **ranking is identical to v2** [f:jobs/model_train.py].
   - Coefficients flip sign day to day, e.g. base_price from −1.36 to +0.39 [Q24].
4. **Cache bug window.**
   - 2019‑12‑19 → 12‑26: the in‑process cache stored empty lists, so 25,091 decisions were served fallback with `fallback_reason='cache'` [c:a00f24c][c:8ed2971][Q22].
   - 21,427 model decisions after 12‑19 came from the cache [Q22].
5. **Affinity v2 vs fallback.** Directionally, v2 beats random and trending on the purchase proxy (1.43% vs 0% / 0.35%) [Q25]. There is no click or exposure attribution, so this cannot be called a validated lift.
6. **Fraud "model".** It is a price threshold. At 0.85 every order over $2,550 is held; with both boosts the cut is about $1,962 [f:jobs/fraud_score.py]. 12 orders ($40,213.29) remain held indefinitely [Q11].
7. **Reorder hints and price suggestions** are advisory/shadow and unread [Q38][f:docs/forecast_caveats.md][f:docs/pricing_status.md].

### 5.4 Dashboards (Redash)

Nine dashboards, each with a single TABLE widget bound to one query (ids 1–9). Every query is a byte‑identical copy of the last `dashboards/*.sql` in git (commit `41e3537^`). The data source is Postgres `estate-pg/novamart`, not BigQuery. No cached results exist (`latest_query_data_id = null`) [R:queries_list.json][R:dash_id_*.json][R:data_sources/1]. A trust guide for each dashboard is in Appendix C.

---

## 6. Data

### 6.1 Warehouse inventory [Q1][f:jobs/warehouse_manifest.json][bq ls]
- **`novamart`** (12 app tables).

  | table | rows | span (UTC) |
  |---|---|---|
  | orders | 9,127 | 09‑25 → 12‑31 |
  | order_lines | 2,284 | from 2019‑11‑22 15:18 |
  | payments | 9,361 | |
  | users | 38,950 | |
  | products | 81,018 | |
  | cart_items | 36,938 | |
  | accounts | 30 | |
  | account_map | 30 | |
  | report_rows | 6,923 | |
  | report_rows_intraday | 2,358 | |
  | statements | 3 | |
  | top_products | 2,396 | |
- **`novamart_analytics`** (20 tables + 4 views).
  - Views: `contactable_users`, `refunds_unified`, `statements_corrected`, `statements_final`. The views are not in the backfill manifest; they were created by engineers' ad‑hoc SQL in Postgres [E:2019‑11‑02, 12‑04, 12‑09, 12‑23].
  - Engineer‑created tables (not produced by any job): `blank_brand_products`, `category_names`, `category_name_history`, `chargebacks`, `statement_overrides`, `statement_corrections`, `test_users` [eng_queries.tsv].
- **`novamart_logs`**: `app_events` (1,570,017), `db_queries` (3,597,650), `job_runs` (978), plus the view `db_queries_normalized`. The view maps `analytics.*` → `novamart_analytics.*` and the actor tag to `<actor>@novamart.sim`. It is slow; querying the raw `textPayload` was faster [Q12 note].
- **Actors in `db_queries`:** `app` 3,266,348; `job` 331,111; `engineer:dev` 107; `engineer:maya` 52; `engineer-backfill:dev` 29; `engineer-backfill:maya` 3 [Q12].
- **Warehouse artifacts.** Columns derived from `now()`/`CURRENT_DATE` show **2026‑08‑13**: `blank_brand_products.captured_at` and `category_name_history.valid_from` [Q34][Q-misc]. Timestamps come back from the emulator as epoch micros unless you CAST them.

### 6.2 Lineage (who writes what, who reads it)
```
gateway callback ─► orders / order_lines / payments ─┬─► daily_report ─► report_rows ─► [daily_kpis, revenue_widget]
                                                      ├─► intraday ─► report_rows_intraday ─► [daily_kpis, revenue_widget]
                                                      ├─► monthly_statement ─► statements ─► statements_corrected(+overrides) ─► statements_final(−chargebacks) ─► [statements_final dash]
                                                      ├─► top_sellers ─► top_products
                                                      ├─► trending ─► trending_daily ─► similar fallback
                                                      ├─► kpi_daily, funnel(+cart_items), fraud_score(→ orders.status=6, order_risk)
                                                      └─► dashboards (direct SQL: best_sellers, brand, category, actives_board, registered_conversion)
cart_items ─► affinity(v1, unused) / affinity_v2 ─► similar widget, model_train ─► model_scores (unused)
similar widget ─► rec_decision_log ─► model_train
users(email, opt_in) ─► contactable_users(view, 0 rows) ; email_digest(ignores view)
orders(status 2/3) + payments(<0) ─► refunds_unified ─► [refunds dash]
```
Evidence: [f:jobs/*][f:routers/similar.py][t:view definitions in bq_view_definitions.json][R:1‑9][Q38].

### 6.3 Known data defects (each with its fingerprint query)

| Defect | Size | Window | Fingerprint | Evidence |
|---|---|---|---|---|
| Duplicate orders from callback replays | 130 refs / 285 orders / $106,943; 151 excess still status=1 ($58,828.24) | 09‑30 → 10‑15 | `GROUP BY payment_ref HAVING COUNT(*)>1` | [Q5][c:b676969] |
| Order callbacks aborting at the DDL step | 4,132 of 7,113 requests | 11‑22 → 12‑31 | count `ALTER TABLE payments` vs `idx_payments_payment_ref` statements per day | [Q18][c:5d1300d] |
| Order outage | 0 orders | 2019‑11‑15 | orders per day | [Q4][Q17] |
| Daily‑report scan cap (500 rows) | Nov‑17 report used 500 of 735 orders | until [c:1233af8] 11‑19 | `job_runs orders_scanned=500` | [Q17] |
| DST 24h window bug | the last hour of 11‑03 missed | until [c:102c9b4] 11‑05 | [E:2019‑11‑05 dev] | [Q13] |
| Daily report included cancelled (status 2/3) until 11‑18 | — | until [c:11c0a42] | — | [c:11c0a42] |
| QA user 424242 / account cc27b436… | 14 orders / $139.86 | 09‑25 → 12‑25 | `test_users` | [Q14][Q21] |
| Real SKUs in `EXCLUDED_SKUS` | 1004856 ($40.8K real), 1002544 ($66.7K) | since 10‑08 | products insert history | [Q14] |
| Gateway refund replays | 3 refunds × 3 | 12‑13, 12‑20, 12‑27 | negative payments per order | [Q7] |
| Synthetic chargebacks | 3 orders / $3,567.57 | inserted 12‑09 | [E:2019‑12‑09] | [Q8] |
| Manual hold release | 5 orders back to status 1 | 12‑29 15:00 UTC | [E:2019‑12‑29 maya] | [Q11] |
| Random‑arm logging gap | about 1,372 impressions | 12‑17 → 12‑19 | app_events vs rec_decision_log | [Q23] |
| Empty‑list cache | 25,091 decisions | 12‑19 → 12‑26 | `fallback_reason='cache' AND rec_source='fallback'` | [Q22] |
| affinity_v2 crash | 3 nights | 12‑03 → 12‑05 | `job_runs event=job_crashed` | [Q27] |

---

## 7. Experimentation

**Infrastructure.** There is no experimentation platform. Assignment exists only for the rec random arm:
- It is deterministic, `sha256(uid)[:8] % 20 == 0`, i.e. 5% of users.
- It is logged in `analytics.rec_decision_log.arm` [f:routers/similar.py].
- There is no exposure, click or holdout logging for anything else [f:novamart/*][Q16 event list].

**Experiments and changes, and how to evaluate them:**

| Change | Type | Date / commit | Evaluable? | Evidence |
|---|---|---|---|---|
| Rec v1 → v2 | full switch (no concurrent control except the random arm) | 2019‑12‑06 [c:df4ed85] | Pre/post only. v2 fallback ~76% vs v1 83%. Purchase proxy 1.43% (model) vs 0.35% (fallback) vs 0% (random) | [Q22][Q25] |
| Random data‑collection arm (5%) | exploration | 2019‑12‑06 | Biased pool (lowest 500 ids) and a 2‑day logging gap. Use `arm='random'` and exclude 12‑17 16:50 → 12‑19 14:55 | [Q23][Q39] |
| Rec v4 learned model | offline only | 2019‑12‑14 [c:a1946ff] | Not served. Ranking identical to v2, so an A/B test of v4 vs v2 would be a null test | [f:jobs/model_train.py][Q24] |
| Dynamic pricing Phase 1 | shadow | 2019‑11‑24 [c:894c535]; Phase 2 held 12‑02 [c:cca9b0d] | No exposure. Shadow table only | [f:docs/pricing_status.md][Q38] |
| Fraud thresholds 0.90 → 0.70 → 0.85 | policy change | [c:e4656fb][c:53f6f6c][c:1cb8721] | holds per night in `job_runs` | [Q11] |
| Trending window 60 → 30 days | algorithm change | 2019‑12‑06 [c:f563dea] (logs switch 12‑07) | `job_runs window_days` | [Q41] |
| Funnel session gap 30 → 120 min | metric definition change | 2019‑12‑14 [c:f915c1b] (logs 12‑15) | sessions series breaks at 12‑15 | [Q41][Q30] |
| Reorder K 141.12 → 162.4 | hand refit | 2019‑12‑21 [c:f85cdd2] | no validation | [f:docs/forecast_caveats.md] |
| Processor fee 2.9% → 2.9% + $0.30 | external pricing | 2019‑11‑20 [c:12e1c68] | statement fee expectation [c:4a58d17] | [Q28] |

**Guidance.** Any before/after read across **2019‑11‑22** is confounded by the order‑callback failures [Q18], and so is any read across **2019‑11‑14 to 11‑17** (surge plus outage) [Q17]. To compare rec versions, condition on `rec_source`/`arm`, never on `effective_version` [Q22].

---

## 8. Glossary

| Term | Meaning at novamart | Evidence |
|---|---|---|
| ET / local day | America/New_York calendar day; all reports and statements use it | [f:constants.py] |
| status 0/1/2/3/6 | pending / paid / cancelled / refunded / fraud‑held (4 = old cancelled code, unused; 5 = phantom) | §3 |
| payment_ref | gateway reference; the idempotency key since [c:b676969] | [f:orders.py] |
| order line | one item callback inside a merged order (`order_lines`, from 2019‑11‑22) | [c:5d1300d] |
| legacy fallback | for orders with no `order_lines`, use the `orders` row itself as the item | [c:92596dc] |
| statement / published | append‑only row in `novamart.statements` written on the 1st | [f:monthly_statement.py] |
| override / corrected / final | `statement_overrides` → `statements_corrected` → `statements_final` (minus chargebacks) | [t:views] |
| chargeback | row in `analytics.chargebacks` (currently 3 synthetic rows) | [E:2019‑12‑09] |
| gateway refund | negative `payments` row from `/payments/gateway_refund` | [f:payments_webhook.py] |
| test user / QA smoke | `analytics.test_users` = {424242}; sessions `qa-smoke`; account UUID `cc27b436-d6f9-4e84-adaf-e716025dd369` | [Q14][Q21][f:docs/dashboard_notes.md] |
| EXCLUDED_SKUS / BRAND_DENYLIST | daily/intraday report and `/reports/brands` filters (code); dashboards hard‑code the brands only | [f:constants.py] |
| lucente / jetem | brands hidden from reports "per partnerships"; jetem has no orders | [c:ba1fbfa][c:1169e40][Q15] |
| active customer | ≥ 7 definitions; see §4.4 | §4.4 |
| contactable | opt‑in + valid non‑example email (view), currently 0 users | [t:contactable_users] |
| affinity sentinel −1 | pair seen < 3 times: "not enough data", not a negative signal; serving filters score ≥ 0 | [c:fef5c96] |
| intended vs effective version | flag value vs what was actually served ("fallback" if no scores) | [f:routers/similar.py] |
| random arm | the 5% of users who get random items for training data | [c:df4ed85] |
| held | status 6 set by fraud_score; released only manually | [Q11] |
| reconcile | nightly duplicate‑ref detector; logs only | [f:jobs/reconcile.py] |
| shadow | output computed but not served (price_suggestions) | [f:jobs/price_suggest.py] |
| advisory | not for finance commitments (reorder_hints) | [f:README.md] |

---

# Appendix

## A. Definition timeline (commit by commit, business‑relevant only)

The 50+ `trigger deploy #d2p-novamart` commits are empty [git_stat.txt].

| Date | Commit | Change | Impact |
|---|---|---|---|
| 09‑15 | 2da4141 | initial: orders insert per callback; statement fee = gross × 2.9%; daily report capped at 500 rows, excluded status only [0]; dashboards: best sellers (orders, 7d, no filters), brand, daily_kpis (UTC day) | baseline |
| 10‑08 | 83fb3ed | EXCLUDED_SKUS = [1004856, 1002544] | hides two real phones from report |
| 10‑12 | 776d674 | affinity v1 job | |
| 10‑15 | b676969 | idempotent callbacks by payment_ref | duplicates stop [Q5] |
| 10‑16 / 10‑21 | 088a372 / 193f22d | users email endpoint; /reports/brands | both unmounted 10‑26 by f1217a8 |
| 10‑18 | 030d841 | reconcile batch 100 → 200 | flagged 100 → 130 [Q41] |
| 10‑21 | ea0e97b | blank‑brand repair | |
| 10‑25 | ba1fbfa | hide lucente from reports | |
| 10‑26 | f1217a8 | similar widget v1 | |
| 10‑28 | 8f19718 | cancel endpoint; STATUS_CANCELLED 4 → 2; can cancel paid orders | |
| 11‑02 | a92c96d | statement fee = collected fees | Oct override 11‑02 [E] |
| 11‑02 | 152a760 | trending job (60d) | |
| 11‑05 | 102c9b4 | DST‑correct day windows | |
| 11‑06 | 9a51155 | top_sellers | |
| 11‑08 | 4dbcf7f | funnel (gap 30) | |
| 11‑09 | d213f6e | price feed upsert | |
| 11‑12 | fef5c96 | affinity −1 sentinel | |
| 11‑15 | 795d273 / d87cb3d | price_history; refund endpoint (status 3) | |
| 11‑16 | 14726e7 | kpi_daily | |
| 11‑18 | 11c0a42 | report excludes 2, 3 | |
| 11‑19 | 1233af8 | remove the 500‑row cap | |
| 11‑20 | 12e1c68 | fee 2.9% + $0.30 | |
| 11‑21 | 35c581e | DISCOUNT_CAP + rerun helper (legacy 0.40 default) | |
| 11‑22 | 5d1300d | **session merge + DDL in request** | ~58% callback loss [Q18] |
| 11‑24 / 12‑02 | 894c535 / cca9b0d | pricing shadow / hold | |
| 11‑26 | f5e3032 | reorder hints | |
| 11‑27 | b59f077 | exclude 424242 (dashboards); test_users (report) | |
| 11‑27 | b567d9d | accounts endpoint (unmounted 12‑05 by c49a7bb) | |
| 11‑28 | c19a307 | email digest (reads `DIGEST_ON`, not set) | |
| 11‑30 | 2814b3d | category revenue dashboard (+ category_names via ad‑hoc SQL) | |
| 12‑02 | 4a58d17 | statement expected fee handles the flat fee; "November correction" (delta 0, ad‑hoc) | |
| 12‑02 / 12‑05 | 89666bf / 3dbe4d7 | affinity v2; December crash fix (version 2.0.1) | |
| 12‑03 / 12‑05 / 12‑29 | e4656fb / 53f6f6c / 1cb8721 | fraud hold 0.90 / 0.70 / 0.85 | |
| 12‑04 | e10cb0c | contactable customers in daily_kpis (view created ad hoc) | always 0 |
| 12‑05 | c49a7bb | gateway refund webhook | non‑idempotent |
| 12‑05 | 92596dc | item‑level counting (order_lines + fallback) | |
| 12‑06 | f563dea / df4ed85 | trending 30d; rec v2 + random arm | |
| 12‑08 | a2e0013 | intraday snapshots; daily_kpis reads report tables + ET days | |
| 12‑09 | cd559d3 | statements_final dashboard (chargebacks ad hoc) | synthetic |
| 12‑09 / 12‑16 | 8dc520b / 0bd4eac | digest flag fixes | first digest 12‑17 [Q20] |
| 12‑10 / 12‑21 | d6e34c6 / b975479 | registered conversion (UUID cast bug → email join) | |
| 12‑11 | 2dde4f0 | actives_board | returns 0 [Q31] |
| 12‑12 | 33054cd | taxonomy history | future‑dated in the warehouse [Q34] |
| 12‑14 | a1946ff / f915c1b | rec v4 training; funnel gap 120 | |
| 12‑15 | 1169e40 | hide jetem everywhere | no effect (0 orders) |
| 12‑17 / 12‑19 / 12‑26 | 30e8907 / a00f24c / 8ed2971 | random‑arm logging dropped / restored + cache / cache invalidation | [Q22][Q23] |
| 12‑18 | adbcb7e | exclude the QA UUID string in brand dashboard | (string compare against bigint ids) |
| 12‑19 / 12‑24 | 686a5d6 / 3eced24 | revenue widget; fix double counting | old widget would show $410K vs $139.6K [Q37] |
| 12‑23 | a3bffec | refunds dashboard (view ad hoc) | |
| 01‑03 | 41e3537 | dashboards → Redash | |
| 01‑04 | 4bfcbe6 | crontab → Airflow (drops 17:00 intraday) | |
| 01‑05 | 5ae1182 | warehouse backfill (pinned) | analytics dataset name bug, fixed in 20e066f on origin/main |

## B. Evidence queries

All of these ran read‑only against the BigQuery emulator via `q.py` (REST `jobs.query`). The full SQL and raw output are in `queries_log.md`. Key queries:

- **Q1 inventory.** `SELECT 'orders', COUNT(*), MIN(created_at), MAX(created_at) FROM novamart.orders UNION ALL …` gave orders 9,127 / order_lines 2,284 / payments 9,361 / users 38,950 / products 81,018 / cart_items 36,938 / accounts 30 / report_rows 6,923 / intraday 2,358 / statements 3 / top_products 2,396. Log row counts come from `bq show` (app_events 1,570,017; db_queries 3,597,650; job_runs 978).
- **Q2 statements.**
  - `SELECT * FROM novamart.statements`: Sep 2,702.00 / 78.36 / 2,623.64 / 12 (2019‑10‑01 10:30); Oct 1,230,332.43 / 35,679.64 / 1,194,652.79 / 3,765 (2019‑11‑01 10:30); Nov 1,101,397.01 / 32,110.92 / 1,069,286.09 / 3,582 (2019‑12‑01 11:30).
  - `statement_overrides`: Oct fee 35,679.50, net 1,194,652.93.
  - `statement_corrections`: 2019‑11 delta 0.
  - `statements_final`: Oct 1,226,764.86 / 1,191,085.36.
- **Q3 status by month.** `SELECT FORMAT_DATETIME('%Y-%m', DATETIME(created_at,'America/New_York')) m, status, COUNT(*), SUM(price) FROM novamart.orders GROUP BY 1,2`:

  | month | 1 | 2 | 3 | 6 |
  |---|---|---|---|---|
  | Sep | — | 11 / 2,501.22 | 1 / 200.78 | — |
  | Oct | 3,695 / 1,206,337.32 | 43 / 10,748.42 | 27 / 13,246.69 | — |
  | Nov | 3,582 / 1,101,397.01 | — | — | — |
  | Dec | 1,756 / 552,328.93 | — | — | 12 / 40,213.29 |
- **Q4 orders per ET day.** E.g. 11‑14 78, 11‑15 *missing*, 11‑16 401, 11‑17 735, 11‑21 118, 11‑23 39, 12‑31 59.
- **Q5 duplicates.**
  - Refs by order count: 8,842 refs ×1, 113 ×2, 10 ×3, 6 ×4, 1 ×5.
  - The duplicated orders span 2019‑09‑30 → 10‑15: 285 orders, $106,943.01.
  - Excess (rn > 1) Oct status 1: 151 / $58,828.24.
- **Q6 payments.** 9,361 rows; 7,077 NULL ref; 9 negative; total gross 2,925,130.07; fee 85,640.94.
- **Q7 gateway refunds.** Orders 3762, 3763 and 3776 each have one positive and three negative rows dated 12‑13, 12‑20 and 12‑27 15:30, matching `app_events event=gateway_refund` (9 events).
- **Q8 chargebacks.** Orders 55 ($734.81, now status 2), 46 ($940.82, status 2) and 49 ($1,891.94, status 3); `reported_at` 2019‑12‑01 12:00. Source insert: [E:2019‑12‑09 15:00 engineer‑backfill:dev] `INSERT INTO analytics.chargebacks … SELECT o.id, o.price, '2019-12-01T12:00:00+00:00' … WHERE … status = 1 AND price > 700 … ORDER BY created_at, id LIMIT 3`.
- **Q9 refunds_unified by month.** Nov cancelled 24 / $6,511.32 and refunded 8 / $3,180.45. Dec cancelled 30 / $6,738.32, refunded 20 / $10,267.02, gateway 9 / $1,843.59.
- **Q10 status‑change timeline.** `updated_at` dates for status 2/3 are 11‑05, 11‑12, 11‑19, 11‑26, 12‑03, 12‑10, 12‑17, 12‑24, 12‑31 (all Tuesdays, 16:00 UTC). All target Sep/Oct orders.
- **Q11 held orders and fraud runs.** 12 orders in status 6, listed with their `order_risk`. `job_runs fraud_scored` held counts per night: 12‑04 8 (thr 0.9); then 1 each on 12‑06, 08, 17, 18, 19, 24, 28, 29 (thr 0.7) and 12‑31 (thr 0.85). The release statement: [E:2019‑12‑29 15:00 engineer‑backfill:maya] `UPDATE orders SET status = 1, updated_at = NOW() WHERE status = 6 AND price < 2600;`.
- **Q12 engineer statements.** `SELECT … FROM novamart_logs.db_queries WHERE REGEXP_CONTAINS(textPayload, r'^\S+ \[engineer')` returned 191 rows, saved to `eng_queries.tsv`. The actor breakdown is in §6.1.
- **Q13 report_rows per day.** One version per day. E.g. 11‑03 123 units vs 140 orders (DST); 11‑16 383 / $123,501.36; 11‑17 487 / $148,857.07 (capped).
- **Q14 excluded SKUs.**
  - 1004856: product row inserted 2019‑09‑25 12:30 as `('Internal Test #4856','qa.test','internal', 9.99)`. Later inserts attempted `'Samsung Smartphone #4856','electronics.smartphone','samsung',130.76` and were ignored by ON CONFLICT. It has 328 orders / $40,968.29, of which QA has 14.
  - 1002544: Apple smartphone, 139 orders / $66,690.18, 0 QA orders.
- **Q15 brands.** Blank brand 648 orders / $94,357.87. lucente 141 / $43,335.35 (676 products, first created 2019‑10‑01 03:10). jetem 5 products, 0 orders.
- **Q16 app event counts.** product_viewed 843,085; rec_served 669,190; cart_item_added 36,925; duplicate_payment_ref 10,766; order_created 9,127; order_callback_replayed 522; order_appended 225; order_cancelled 54; user_email_updated 40 (all 2019‑10‑23 13:00); account_created 30 (2019‑12‑01 16:30); order_refunded 28; price_feed_received 13; gateway_refund 9; statement_fee_mismatch 3.
- **Q17 surge and outage.**
  - Views/carts/orders per day, 11‑14 → 11‑17: 17,217/1,276/78; 27,661/2,136/0; 27,649/1,895/401; 25,390/1,642/735.
  - `INSERT INTO orders` statements on 11‑15: 0.
  - `job_runs` daily_report for 11‑15: 0 orders scanned; for 11‑17: `orders_scanned=500`.
- **Q18 callback abort funnel.** For each day, the count of `ALTER TABLE payments ADD COLUMN` vs `idx_payments_payment_ref` vs the lookup statement. Example 11‑23: s1–s4 = 107 each, s5 = 44, locks 88, lookups 44, inserts 39. Totals 11‑22 → 12‑31: reached 7,113, passed 2,981.
- **Q19 merged orders.** Line‑count distribution: 1 line 1,886, 2 lines 136, 3 lines 25, 4 lines 10, 5 and 6 lines 1 each. No total mismatches. Appended lines (rn > 1): 225 / $52,812.06, all with a product different from `orders.product_id`.
- **Q20 emails, contactability, digest.**
  - Domains: `example.com` 38,910 (24,170 opted in); `gmail.example` 40 (23 opted in).
  - `contactable_users` count: 0.
  - `digest_log`: 15 sends, 12‑17 → 12‑31, recipients 40. Top product 1002544 / 1004856 / 1004767.
- **Q21 accounts.** 30 accounts, all created 12‑01 16:30, including `cc27b436-…` → uid 424242. Registered conversion via email: 30 buyers / $18,155.71.
- **Q22 rec_decision_log.** Grouped by intended/effective/source/reason/arm:
  - 1.0.0 fallback/no_scores 326,186; 1.0.0 affinity 66,444.
  - 2.0.0 → fallback/no_scores 182,868; 2.0.0 model 31,268; random_arm 14,566; fallback/cache 25,091 (12‑19 → 12‑26); model/cache 21,427.
- **Q23 random‑arm gap.** Logged vs served random: 12‑17 549 vs 658; 12‑18 0 vs 848; 12‑19 407 vs 822.
- **Q24 model registry and tables.**
  - 17 trainings, 12‑15 → 12‑31; `train_rows` 4,197 → 14,411 (5,798 on both 12‑18 and 12‑19).
  - `coef[0]` (n_items) is between −0.24 and −0.81 every night. Other coefficients flip sign.
  - `model_scores` 948 rows (one version). `product_affinity_v2` 3,912 rows (2,964 sentinel, 948 usable, 1,476 base products, version 2.0.1). `product_affinity` has identical counts.
- **Q25 purchase proxy.** Decisions since 12‑06 16:40, unnested items joined to purchases (order_lines or orders) by the same user within 7 days: fallback 727 / 205,706 (0.353%); model 746 / 52,203 (1.429%); random 0 / 14,437.
- **Q26 job runs summary.**
  - Run counts and UTC times: affinity 80 (07:30/08:30); affinity_v2 26 (08:45) + 3 crashes; daily_report 107 (10:00/11:00); email_digest 15 (12:15); fraud 28 (10:45); funnel 53; intraday 47 (17:00/22:00); kpi 45; model_train 17; monthly 3; price_suggest 37; reconcile 107; reorder 35; top_sellers 55; trending 59.
  - Each run time is the local cron time in UTC under EDT/EST.
- **Q27 crash.** `job_runs event=job_crashed` 12‑03/04/05: `IndexError` at `SEASONAL_FACTORS[t.month - 1]`.
- **Q28 fee mismatches.** Sep −0.01; Oct `statement_fee` 35,679.64 vs collected 35,679.50 (delta 0.14); Nov 31,940.51 vs 32,110.92 (delta −170.41).
- **Q30 kpi_daily / daily_funnel series.** kpi 12‑31 = 1,152. Funnel 12‑31: sessions 345, users_active 308. Gap 30 → 120 from 12‑15.
- **Q31 board actives repro (now = 2020‑01‑01 05:00 UTC).** 1,149 candidates, 1,148 not test, **0** after email heuristics.
- **Q32 daily_kpis repro (today = 2019‑12‑31).**

  | day | orders (units) | revenue | active |
  |---|---|---|---|
  | 12‑31 | 60 | 18,202.09 | 54 |
  | 12‑30 | 81 | 24,767.62 | 65 |
  | 12‑29 | 89 | 24,379.38 | 75 |
  | 12‑18 | 67 | 19,566.50 | 55 |

  12‑31 comes from intraday; contactable is 0 on every day.
- **Q33 best sellers and brand repro.** Best sellers top 3 by revenue: 1005116 $5,889.81; 1005115 $5,325.55; 1005284 $5,096.14 (2 units, both non‑paid/held). Brand 30d: apple $236,606.73; samsung $127,496.25; …; '' $17,391.05; internal $7,624.89.
- **Q34 category mapping.**
  - History rows (lighting / entertainment) have `valid_from` 2026‑08‑13.
  - `category_names`: 135 codes, PK‑unique, groups other 52, appliances 30, apparel 24, electronics 13, construction 10, kids 6.
- **Q35 top_products and trending.** top_products 2019‑12‑30: #1 1004767 (3 orders). trending_daily 2019‑12‑31: #1 1004767 (66 units); **#2 1004856 "Internal Test #4856"**; #3 1002544.
- **Q36 monthly variants.** Report_rows by month: Oct 1,201,082.08; Nov 966,974.33; Dec 535,561.72.
  - Payments by month (gross / fee / negative):

    | month | gross | fee | negative |
    |---|---|---|---|
    | Oct | 1,230,332.43 | 35,679.50 | 0 |
    | Nov | 1,101,397.01 | 32,110.92 | 0 |
    | Dec | 590,698.63 | 17,772.15 | −1,843.59 |
  - Status 1 vs dedup vs dedup minus QA vs incl. held:

    | month | status 1 | dedup | dedup − QA | incl. held |
    |---|---|---|---|---|
    | Oct | 1,206,337.32 | 1,147,509.08 | 1,147,459.13 | 1,147,459.13 |
    | Nov | 1,101,397.01 | 1,101,397.01 | 1,101,357.05 | 1,101,357.05 |
    | Dec | 552,328.93 | 552,328.93 | 552,288.97 | 592,502.26 |
- **Q37 revenue widget.** Old logic (686a5d6) = $410,387.39 vs fixed logic (3eced24) = $139,598.13 for today = 2019‑12‑31. Intraday has 2 versions/day (17:00 and 22:00 UTC).
- **Q38 who reads analytics tables (db_queries).**
  - app → `product_affinity` (v1) 392,630 reads, last 2019‑12‑06 16:39:58.
  - app → v2 264,731; job → v2 17 (model_train).
  - model_scores: one engineer read only. reorder_hints: one engineer read. price_suggestions: none.
  - app → trending 207,950.
- **Q39 random pool.** The 500 lowest product ids are 1,000,894 … 1,004,386; catalog 81,018.
- **Q40 users by first‑seen month.**

  | month | first seen | ever ordered |
  |---|---|---|
  | Sep | 74 | 29 |
  | Oct | 15,045 | 2,685 |
  | Nov | 11,302 | 1,043 |
  | Dec | 12,529 | 355 |

  Distinct buyers 4,112; paid buyers 4,089.
- **Q41 job_runs parameters.**
  - trending `window_days`: 60 from 11‑03 to 12‑06, 30 from 12‑07 to 12‑31.
  - funnel `gap_min`: 30 to 12‑14, 120 from 12‑15.
  - reconcile flagged: 0 (9‑16 → 9‑30), rising daily to 100 (10‑14 → 10‑18), then **130 every night from 10‑19 to 12‑31**.

## C. Dashboard trust guide (Redash ids)

| Dashboard (query id) | What it really shows | Trust? / caveats |
|---|---|---|
| refunds (1) | `refunds_unified` per month of status change | **No**: it mixes cancellations, triple‑counted gateway refunds and status refunds, dated by event, not order month [Q9] |
| revenue_widget (2) | last 6 closed days of report_rows (latest version) + latest intraday for today | OK post‑[c:3eced24]. Inherits R5 caveats (held included, real SKUs excluded). After migration "today" freezes at the 12:00 snapshot [Q37] |
| actives_board (3) | 30d non‑cancelled buyers minus email heuristics | **Do not use**: structurally 0 [Q31] |
| registered_conversion (4) | buyers among the 30 beta accounts via email | small and selection‑biased; includes QA; ignores `account_map` [Q21] |
| statements_final (5) | statements + fee override − synthetic chargebacks | Use only with the caveat. Prefer published `statements` + an explicit adjustment list (§4.1) [Q8] |
| category_revenue (6) | 30d item revenue by display group | No status filter. Taxonomy history does not take effect (future `valid_from` in the warehouse) [Q34] |
| best_sellers (9) | 7d item revenue rank | No status filter (held/cancelled count). The mislabeled SKU 1004856 is included [Q33] |
| brand_revenue (8) | 30d item revenue by brand | Blank brand bucket; `internal` = the Samsung phone; QA UUID filter compares strings against numeric ids [Q33][c:adbcb7e] |
| daily_kpis (7) | report_rows/intraday revenue and units ("orders") + per‑day active users + contactable | "orders" = units; contactable always 0; active users unfiltered by status; brand filter applies to the first item only [Q32] |

All rolling windows use `now()`, so on today's static data the 7d/30d/14d dashboards return empty or zero. Reproduce them with an explicit anchor such as 2019‑12‑31 ET [R:1‑9].

## D. Safe‑change checklist for the batch pipelines
1. Remove the DDL from `POST /orders` and run it once at deploy time [Q18][f:orders.py]. This matters most.
2. Make refreshes atomic: wrap DELETE + INSERT in one transaction, or swap tables. Today jobs use autocommit [f:db.py].
3. Make append‑only outputs idempotent: report_rows, statements, kpi_daily, daily_funnel, top_products, order_risk. Dashboards guard only report_rows and intraday, via `MAX(created_at)` [R:2][R:7].
4. Add Airflow dependencies (affinity_v2 → model_train; daily_report → dashboards), set the timezone explicitly, and restore the 17:00 intraday run [f:airflow/dags/*][f:crontab.txt].
5. Fix `EXCLUDED_SKUS` (1004856 and 1002544 are real) and repair product 1004856's metadata [Q14].
6. Give the gateway refund webhook an idempotency key, and reconcile refunds against order status [Q7].
7. Delete or relabel the synthetic `analytics.chargebacks` rows, and annotate `docs/restatement_policy.md` [Q8].
8. Retire `affinity` v1 (no readers) [Q38]. Either fix v4 (item‑level labels, real features, a non‑constant transform) or drop it [Q24].
9. Make the email digest respect `marketing_opt_in` / `contactable_users` and exclude `test_users` [Q20].
10. If the warehouse is rebuilt, use the `origin/main` fix for the dataset name [c:20e066f].

## E. Repo docs: verified vs refuted

| Doc claim | Verdict | Evidence |
|---|---|---|
| trending_notes: window 60 → 30 on 12‑06/07 | ✔ | [Q41] |
| affinity_lineage: v1 unused by the widget | ✔ (and unused by every reader). Missed: model_train reads v2 | [Q38] |
| pricing_status: suggestions never read | ✔ | [Q38] |
| forecast_caveats: hint range 55–102 | Partly. Today's table is 51–102, velocity 0.0714–2.7143 | [Q-misc reorder_hints] |
| metrics_definitions: three active definitions | Incomplete. Misses funnel, contactable, digest, registered. The board definition yields 0 | §4.4 [Q31] |
| dashboard_notes: QA UUID created 12‑01; order_lines from 11‑22 | ✔ | [Q21][Q1] |
| restatement_policy: use statements_final for current finance | ✘. Its chargebacks are synthetic | [Q8] |
| README: rec v4 serving 4.0.0 with 9 features | ✘. Flag is 2.0.0; 5 features | [f:deploy/flags.env][f:jobs/model_train.py][Q22] |
| README: reconcile "flags anything odd in payments" | ✘. It only checks duplicate refs on orders | [f:jobs/reconcile.py] |
| data‑access: analytics dataset named `analytics` | ✘ at the pin; fixed to `novamart_analytics` on main | [c:99003c3] |

## F. Open questions (could not be determined from the sources)
- **The root cause of the 2019‑11‑15 zero‑order day.** No app error events exist, and no order statements were logged at all [Q17].
- **Whether failed callbacks were retried by the gateway.** The successful‑insert rate implies most were permanently lost, but the gateway's retry policy is not visible [Q18].
- **The Airflow `default_timezone` in production.** It is not in the repo.
- **Why 1002544 was put in `EXCLUDED_SKUS`.** The commit message says only "test skus" [c:83fb3ed].

## Files in this folder
- `novamart_tribal_knowledge.md`: this document.
- `queries_log.md`: every warehouse query with its raw result.
- `q.py`: the read‑only query helper.
- `eng_queries.tsv`: engineer statements from `db_queries`.
- `bq_view_definitions.json`.
- `git_log_full.txt`, `git_log_nomanifest.txt`, `git_stat.txt`: git history dumps.
- `dashboards_sql_git/`: the last git version of each dashboard SQL.
- `redash/`: API snapshots of dashboards, queries and the data source.
