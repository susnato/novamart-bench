# Novamart Tribal Knowledge

- Run id: `9426a337-a67b-4d6d-942d-589c70788540`  
- Started: 2026-10-05 17:39:27 UTC  
- Sources used (and only these): repo `novamart` pinned at `5ae1182` (112 commits, 2019-09-15 → 2020-01-05); BigQuery emulator project `novamart-warehouse` (datasets `novamart`, `novamart_analytics`, `novamart_logs`); Redash at `localhost:5056` (9 dashboards / 9 queries, read-only).  
- Nothing was mutated. All queries were `SELECT`/metadata reads; nothing in Redash was created, edited or refreshed. Intermediate outputs are in this directory (see Appendix F).

Citation conventions used below: `commit <hash>` = git commit in the repo; `file:line` = repo path; `table` = BigQuery `dataset.table`; `job_runs`/`app_events`/`db_queries` = rows in `novamart_logs.*`; `redash q<N>` / `redash dash<N>` = Redash query / dashboard ids; `[F<nn>]` = intermediate evidence file in this directory (Appendix F).

---

## 1. Summary

Novamart is a FastAPI + Postgres marketplace backend (`README.md:3`) whose entire reporting surface — finance statements, exec dashboards, KPI rollups, a "similar products" recommender, fraud holds, pricing/reorder heuristics — is produced by a set of nightly Python batch jobs writing to a Postgres `analytics` schema, then copied once into BigQuery by a backfill job (`commit 5ae1182`, `docs/data-access.md`). The data covers 2019-09-25 → 2019-12-31 (`novamart.orders` min/max `created_at`, [F13]). Dashboards moved to Redash and schedules to Airflow in Jan 2020 (`commit 41e3537`, `commit 4bfcbe6`).

The ten things a tenured person knows that the docs do not say plainly:

1. **"Revenue" has at least six different answers for the same month, and they are all "right" for a different question.** For October 2019: published statement net **$1,194,652.79** (`novamart.statements`), fee-corrected **$1,194,652.93** (`novamart_analytics.statements_corrected`), finance-final **$1,191,085.36** (`novamart_analytics.statements_final`), live re-computation on today's `status = 1` orders **$1,206,337.32**, sum of the daily report **$1,201,082.08** (`novamart.report_rows`), and dashboard-style item revenue **$1,210,334.97** [F27]. Section 4 and Appendix A explain every gap to the cent.
2. **Statements are append-only snapshots computed from `orders.status = 1` at run time** (`novamart/jobs/monthly_statement.py:26-46`). Cancellations and refunds that arrive later never flow back into them; only *chargebacks* are subtracted, via the `statements_final` view. $23,995.11 of October orders have since been cancelled/refunded but are still in finance's "final" number [F29].
3. **October gross contains ~$58.8K of double-booked orders.** Before `commit b676969` (2019-10-15) payment-gateway callbacks were not idempotent; 130 `payment_ref`s were booked 2–5 times (155 extra orders, $59,810.59, 151 still `status = 1`) [F13][F14]. Nightly `reconcile` flags exactly these 130 refs every night and has done nothing else since 2019-10-19 (`job_runs`, `flagged = 130` for 74 nights).
4. **The daily report (`report_rows`) is never regenerated and carries three permanent holes:** 2019-11-03 under-counted by $2,985.99 (DST bug fixed in `commit 102c9b4`), 2019-11-15 has no row at all (checkout outage: 28,666 product views, 0 orders [F12]), and 2019-11-17 was capped at 500 scanned rows and is short by **$74,995.96** (fixed in `commit 1233af8` two days later, never backfilled) [F10][F11].
5. **The "active customers" number depends entirely on who is asking.** The nightly rollup says 1,152 (2019-12-31, `novamart_analytics.kpi_daily`); the board-deck query (`redash q3`) returns **0** because its email heuristics exclude every one of the 38,950 users (all are `@example.com` or `@gmail.example`) [F18]; the exec KPI dashboard shows per-day distinct buyers (47–75/day in late Dec) and a `contactable_customers` column that is **always 0** because `analytics.contactable_users` is an empty view [F18][F28].
6. **A real Apple phone is classified as a "test SKU".** `EXCLUDED_SKUS = [1004856, 1002544]` (`novamart/constants.py:7`, `commit 83fb3ed`) hides product `1002544` — an `electronics.smartphone` by `apple`, 139 orders / $66,690.18 from ~90 distinct real users — from the daily report and `/reports/brands`, while the Redash dashboards (which do not apply `EXCLUDED_SKUS`) still show it in the best-sellers top 10 [F16][F28].
7. **The recommender mostly serves the trending list.** Of 667,850 logged decisions, 75–83% were `fallback` (top-5 of `analytics.trending_daily`), because affinity has scores for only 449 of ~43,000 requested base products [F21][F22]. The "trained model v4" (`novamart/jobs/model_train.py`) multiplies every affinity-v2 score by the same constant `(1 + 0.1·w)` — the ranking is identical to v2 (score ratio 0.9755 on every row), it has never been served (`deploy/flags.env` = `2.0.0`; zero `effective_version = '4.0.0'` rows), and its label is "user placed *any* paid order after exposure", not a click/purchase of a recommended item.
8. **Two config files disagree with the README.** README says rec serving is `4.0.0` and trending uses a 60-day window (`README.md:35,43`); live code/config say `REC_MODEL_VERSION=2.0.0` (`deploy/flags.env:4`) and `WINDOW_DAYS = 30` (`novamart/jobs/trending.py:9`, `commit f563dea`). `docs/trending_notes.md` already flags the first; nothing flags the second.
9. **Three HTTP routers were silently un-mounted.** `/users/{id}/email` and `/reports/brands` were dropped from `app.py` in `commit f1217a8` (2019-10-26) and `/accounts` in `commit c49a7bb` (2019-12-05). The registered-accounts beta therefore froze at 30 accounts, all created in one batch on 2019-12-01 16:30 UTC (`app_events` `account_created`, `novamart.accounts`).
10. **Fraud auto-hold has frozen $40,213.29 of December orders** in `status = 6` (12 orders, 8 of them $2,999.99 on 2019-12-03). They are excluded from every `status = 1` metric (statements, KPI rollup, trending) but *included* in the daily report and all Redash dashboards (status 6 is not in `EXCLUDED_STATUSES = [0, 2, 3]`). The 2019-12-29 "release held orders under $2600" (`commit 1cb8721`, `db_queries` `engineer-backfill:maya`) released nothing — the cheapest held order is $2,655.33 [F20].

---

## 2. Why this project

The goal (from the task brief) is to be able to (a) answer "what was revenue in a given month, and why" like a tenured finance/data person, (b) explain any dashboard number and know when not to trust it, and (c) judge whether the ML systems work and modify the batch pipelines safely.

Why that requires tribal knowledge rather than reading the code once:

- **Definitions changed ~weekly for four months.** 112 commits between 2019-09-15 and 2020-01-05 [F01]; of those, at least 25 change a metric definition, a filter list, a status code, a window, a threshold or a schedule (Appendix D). The same word ("active", "revenue", "units", "orders") means something different depending on which consumer and which date you look at.
- **Outputs are append-only snapshots, not recomputable views.** `report_rows`, `statements`, `kpi_daily`, `top_products`, `trending_daily`, `daily_funnel` are written once per run and never corrected (`novamart/jobs/*.py`; every one does `INSERT` without `DELETE` except the recommender tables). Bugs fixed in code remain in the historical rows. The git log tells you *when* a bug was fixed; only the data tells you *which rows* are wrong.
- **Corrections live outside the job pipeline.** Finance restatements are hand-inserted rows and views created from an engineer's laptop (`db_queries` actor `engineer-backfill:dev`, 2019-11-02, 2019-12-02, 2019-12-09) — see Appendix A.3. They are not in `schema.sql`, not in any job, and would not be recreated by a fresh deploy.
- **The company is tiny (two engineers: Dev Kapoor, Maya Iyer; `git log` authors) and the docs are partial.** `docs/rec_versions.md` is literally "TBD". `README.md` is stale in two places. `docs/dashboard_notes.md` and `docs/metrics_definitions.md` are accurate for their scope but silent on the empty-view and all-users-excluded problems.

---

## 3. Business understanding

### 3.1 What the business does

An online marketplace selling third-party catalog products (phones dominate: `electronics.smartphone` is $1.87M of $2.86M lifetime `status = 1` revenue; `apple` + `samsung` are $1.92M [F16][F19]). Customers browse products (`GET /products/{pid}`), add to cart (`POST /cart`), and pay through an external payment gateway that calls back `POST /orders` with a `payment_ref` (`novamart/routers/orders.py:14`). The platform takes a processor fee on each payment (2.9%, plus $0.30 flat from 2019-11-20; `novamart/constants.py:4,32`, `commit 12e1c68`).

### 3.2 How a sale becomes data (order lifecycle)

```
view ──> cart ──> gateway callback POST /orders (ts, uid, pid, price, ref, session)
                     │
                     ├─ ref already seen?  → replay: ensure a payments row, status 0→1   (commit b676969, 2019-10-15)
                     ├─ same uid+session within 15 min, order not cancelled/refunded?
                     │      → APPEND: orders.price += price, +order_lines row, +payments row   (commit 5d1300d, 2019-11-22)
                     └─ else → INSERT orders(status 0) + order_lines + payments, then status 1
```
(`novamart/routers/orders.py:43-105`.)

Consequences a tenured person knows:

- `orders` is **one row per checkout**, `order_lines` is **one row per item**, but `order_lines` only exists for orders since 2019-11-22 (`novamart.order_lines` min `created_at`; `docs/dashboard_notes.md`). Legacy orders have no lines, so every item-level query needs the `UNION ALL ... WHERE NOT EXISTS (order_lines)` fallback introduced in `commit 92596dc` (2019-12-05).
- For multi-item orders `orders.product_id` is the **first** item only and `orders.price` is the **sum** of items (`orders.py:79`). 173 orders are multi-line, carrying 398 payment rows [F14]. The flat $0.30 fee is charged **per line**, not per order (`orders.py:19,88`) — see Appendix A.2.
- `payments` is **one row per callback** (gross, fee, net), plus negative rows mirrored from gateway refunds (`novamart/routers/payments_webhook.py`). `payments.payment_ref` is NULL for rows before 2019-11-22 (7,068 of 9,352 positive rows [F06]).
- **Users and products are created on first sight** with placeholder email `user{uid}@example.com` and blank brand/category (`novamart/routers/catalog.py:58-65`, `novamart/onboarding.py`). "Signup" does not exist as an event; `users.created_at` is first-touch. Name/region/channel/device/age/opt-in are deterministic hashes of the id (`onboarding.py:25-35`).

### 3.3 Order statuses (and how they changed)

| status | meaning | since | evidence |
|---|---|---|---|
| 0 | pending (set on insert, flipped to 1 in same request) | initial | `orders.py:93,104` |
| 1 | paid | initial | |
| 2 | cancelled | 2019-10-28 (`STATUS_CANCELLED` was **4** before) | `commit 8f19718` |
| 3 | refunded | 2019-11-15 | `commit d87cb3d` |
| 5 | never defined; `reconcile` excludes it | initial | `novamart/jobs/reconcile.py:16` |
| 6 | fraud hold | 2019-12-03 | `commit e4656fb`, `novamart/jobs/fraud_score.py:46` |

Current distribution: 9,033 × status 1 ($2,860,063.26), 54 × 2 ($13,249.64), 28 × 3 ($13,447.47), 12 × 6 ($40,213.29) [F13]. The report job excluded only status 0 until `commit 11c0a42` (2019-11-18) added 2 and 3; it has never excluded 6.

### 3.4 Operational rhythms you have to know

- **Weekly Tuesday 16:00 UTC ops batch**: exactly 6 cancellations + 4 refunds, applied to the *oldest* order ids in sequence (ids 1→82), every Tuesday from 2019-11-05 to 2019-12-31 (`app_events` `order_cancelled`/`order_refunded`; [F29]). All of them are 30 Sept / 1 Oct orders. This is why the refunds dashboard shows refunds in Nov/Dec for October revenue.
- **Weekly Monday 11:00 UTC vendor price feed** (`acme_feed_v2`, 200 items; `app_events` `price_feed_received`, 13 events 2019-10-07 → 2019-12-30). Before `commit d213f6e` (2019-11-09) the feed used `ON CONFLICT DO NOTHING`, so prices were *not* updated; `analytics.price_history` starts 2019-11-18 (`commit 795d273`).
- **Weekly Friday 15:30 UTC gateway refund replay**: the same 3 refunds (orders 3762/3763/3776, $614.53 total) were posted on Dec 13, 20 and 27 and booked three times (`novamart.payments` ids 8049-8051, 8566-8568, 9035-9037) because the webhook has no idempotency key (`payments_webhook.py:17-19`) [F15][F29].
- **QA smoke tests** run as `user_id = 424242` (`cust424242@gmail.example`, created 2019-09-25; 14 orders, $139.86) and are the sole row of `analytics.test_users` (inserted by hand 2019-11-27, `db_queries` `engineer-backfill:dev`) [F17].
- **Checkout outage 2019-11-15**: zero orders all day with normal browsing; followed by 349 and 770 orders on Nov 16–17 (vs ~110/day normal) [F12]. Nov 17's daily report was then truncated by the 500-row cap (§1 item 4).

### 3.5 Brands/partners that are hidden on purpose

`BRAND_DENYLIST = ["lucente", "jetem"]` (`constants.py:10`). `lucente` hidden 2019-10-25 "per partnerships" (`commit ba1fbfa`): 676 products, $42,917.72 lifetime paid revenue, still selling (28 units in Dec) [F16]. `jetem` added 2019-12-15 (`commit 1169e40`): 5 products and **zero** orders ever [F17] — the filter is harmless today but it is in every dashboard. Hidden means hidden from the daily report, `/reports/brands`, and all Redash dashboards — **not** from statements, `kpi_daily`, trending, top_sellers, or any `status = 1` aggregate.

---

## 4. Metrics

Each metric below lists: canonical definition today, where it is produced, who consumes it, how it changed, and the traps.

### 4.1 Monthly revenue (finance)

**Canonical "finance number" = `novamart_analytics.statements_final.net`** (`docs/restatement_policy.md`; `redash q5`/`dash5 statements_final`). Lineage:

```
novamart.statements   (job snapshot; append-only; novamart/jobs/monthly_statement.py)
   └─ LEFT JOIN novamart_analytics.statement_overrides ON month  → statements_corrected (view)
         └─ minus SUM(chargebacks.amount) grouped by the ORDER's local month → statements_final (view)
```
View SQL: [F03]. Created by hand from `engineer-backfill:dev` on 2019-11-02 and 2019-12-09 (`db_queries`), referenced by `commit cd559d3`.

How the job computes a month (`monthly_statement.py:20-46`):
- month window = local (`America/New_York`) calendar month converted to UTC (`timeutil.local_month_window_utc`), run on the 1st at 06:30 local (`crontab.txt:8`) → Oct = `2019-10-01 04:00Z … 2019-11-01 04:00Z`, Nov = `… 2019-12-01 05:00Z`;
- `gross = SUM(orders.price) WHERE status = 1`, `orders_count = COUNT(*)`;
- `fee = SUM(payments.fee)` joined to those orders (since `commit a92c96d`, 2019-11-02; before that `fee = round(gross × 0.029, 2)`);
- `net = gross − fee`; one `INSERT` into `statements`; a WARNING `statement_fee_mismatch` if collected fee ≠ expected fee.

Published values (`novamart.statements`, [F04b]):

| month | gross | fee | net | orders | published (UTC) |
|---|---|---|---|---|---|
| 2019-09 | 2,702.00 | 78.36 | 2,623.64 | 12 | 2019-10-01 10:30 |
| 2019-10 | 1,230,332.43 | 35,679.64 | 1,194,652.79 | 3,765 | 2019-11-01 10:30 |
| 2019-11 | 1,101,397.01 | 32,110.92 | 1,069,286.09 | 3,582 | 2019-12-01 11:30 |

Restated values: Oct `statements_corrected` fee 35,679.50 / net 1,194,652.93 (override note: "Corrected to sum of per-order collected payment fees"); Oct `statements_final` gross 1,226,764.86 / net **1,191,085.36** (−3,567.57 chargebacks on orders 46, 49, 55) [F04][F04b]. Sep and Nov are unchanged through all three layers.

**Why the live number differs** (Appendix A.1 has the full bridge): re-running the same SQL today gives Oct gross 1,206,337.32 on 3,695 orders because 70 October orders ($23,995.11) were set to status 2/3 after publication; the `statements` row is reproducible exactly by adding back orders whose `updated_at > '2019-11-01 10:30'` [F05].

Traps:
- The December statement does not exist yet (job runs 2020-01-01). When it runs it will **exclude** the 12 held orders ($40,213.29, status 6) and **include** the 3 gateway-refunded orders (still status 1) — and it will include 9 negative refund rows' fees of 0 but not their gross (gross comes from `orders`, not `payments`).
- `statements_final` subtracts chargebacks for orders that were *also* cancelled/refunded (46 → status 2 on Dec 10; 49 → 3 on Dec 10; 55 → 2 on Dec 17) [F29]. Do not additionally net `refunds_unified` against `statements_final` for October or you double-subtract $3,567.57.
- `analytics.statement_corrections` (1 row: `2019-11`, delta `0.00`, "November 2019 processor fee change audit correction") is an audit note, not an input to any view. The Nov fee-change audit found nothing to correct because the statement already uses collected fees. Appendix A.2 explains the −$170.41 WARNING and the real ±$9.62 residual.

### 4.2 Daily revenue / orders (exec dashboard `daily_kpis`, `revenue_widget`)

Produced by `novamart/jobs/daily_report.py` (06:00 local, `report_date = yesterday`) into `novamart.report_rows(report_date, product_id, units, revenue, created_at)`; intraday by `novamart/jobs/intraday_report.py` (12:00 & 17:00 local since 2019-12-08, `commit a2e0013`) into `novamart.report_rows_intraday`.

Definition today: item-level rows (`order_lines`, legacy fallback) in the local day window, `status NOT IN (0,2,3)`, `user_id NOT IN analytics.test_users`, `product_id NOT IN EXCLUDED_SKUS`, `brand NOT IN BRAND_DENYLIST`; `units = COUNT(*)`, `revenue = SUM(price)`; one row per product; **append-only**.

Definition history (each change applies only to rows written after it):

| date | change | commit |
|---|---|---|
| 2019-10-08 | exclude SKUs 1004856, 1002544 | `83fb3ed` |
| 2019-10-25 | exclude brand `lucente` | `ba1fbfa` |
| 2019-11-05 | DST-safe local-day window (Nov 3 report already wrong) | `102c9b4` |
| 2019-11-18 | exclude status 2, 3 (was only 0) | `11c0a42` |
| 2019-11-19 | remove 500-row `fetchmany` cap (Nov 17 report already wrong) | `1233af8` |
| 2019-11-27 | exclude `analytics.test_users` | `b59f077` |
| 2019-12-05 | count per item via `order_lines` (was per order, first product) | `92596dc` |
| 2019-12-15 | exclude brand `jetem` | `1169e40` |

Consumers: `redash q7 daily_kpis` (`dash9`) — `orders` column is `SUM(units)`, i.e. **items, not orders** since 2019-12-05; `redash q2 revenue_widget` (`dash2`) — 7 calendar days incl. today. Both take only the latest `created_at` version per `report_date` (`commit 3eced24`, 2019-12-24, "Fix revenue widget double counting"): the first widget (`commit 686a5d6`, Dec 19) summed every intraday snapshot and every closed-day row for 7 days, double/triple counting. Both also re-apply `brand NOT IN ('lucente','jetem')` by joining `products` (redundant for rows after Dec 15, meaningful for older rows).

Traps: the three permanent holes (Nov 3, Nov 15, Nov 17) in §1; Oct 1–7 rows include `lucente`/test SKUs and orders later cancelled (the filters did not exist yet) — Oct 1 is $47,897.98 in `report_rows` vs $23,801.97 with today's rules [F10]; `report_rows` ends 2019-12-30 (Dec 31 is only in intraday). After the Airflow migration only the 12:00 intraday snapshot is scheduled (`airflow/dags/intraday_report_dag.py:9` vs `crontab.txt:28-29`).

### 4.3 Refunds

`novamart_analytics.refunds_unified` view (`commit a3bffec`, 2019-12-23; `redash q1 refunds`, `dash1`): status-2 orders as `order_cancelled`, status-3 as `order_refunded` (amount = `orders.price`, time = `orders.updated_at`), UNION negative `payments` rows as `gateway_refund` (time = payment `created_at`) [F03]. Output by month: Nov 32 / $9,691.77; Dec 59 / $18,848.93 [F15].

Traps: (1) refunds are attributed to the month the status changed, not the sales month — every one of them is a Sep/Oct order [F29]; (2) the 9 `gateway_refund` rows are 3 real refunds posted three times — $1,843.59 shown vs $614.53 real [F29]; (3) gateway-refunded orders stay `status = 1`, so they are simultaneously revenue and refunds; (4) a cancelled order's `price` for a multi-line order is the whole order; (5) chargebacks (`analytics.chargebacks`) are not in this view.

### 4.4 Active customers (three live definitions + one dead one)

| consumer | definition | value on 2019-12-31 | evidence |
|---|---|---|---|
| `novamart_analytics.kpi_daily.active_customers` (nightly 06:15) | `COUNT(DISTINCT user_id)` from `orders`, trailing 30×24h from run ts, `status = 1`, **no** exclusions | **1,152** (peak 2,256 on Nov 19; fell 1,560 → 1,031 on Dec 16-18 as the Nov 15-17 surge aged out) | `novamart/jobs/kpi_daily.py:17-19`, `commit 14726e7`, [F18] |
| `redash q7 daily_kpis.active_customers` (`dash9`) | distinct ordering users per **local calendar day**, any status, excl. `424242`, excl. lucente/jetem products | 65 (Dec 30), 75 (Dec 29) … | `git_dashboards/daily_kpis.sql`, [F28] |
| `redash q3 actives_board` (`dash3`, board deck) | distinct users, trailing 30 d, `status NOT IN (0,2,3)`, excl. `analytics.test_users`, excl. emails on example/test/internal domains or qa/test/demo localparts | **0** — 1,151 candidates → 1,150 after test_users → 0 after email rules, because 38,910 users are `@example.com` and 40 are `@gmail.example` (`LIKE '%.example'`) | `commit 2dde4f0`, [F18] |
| `daily_kpis.contactable_customers` | buyers present in `analytics.contactable_users` (opt-in AND syntactically valid AND not example/.example domain) | **always 0** (view has 0 rows) | `db_queries` 2019-12-04 `engineer-backfill:maya` view DDL, [F18] |

`docs/metrics_definitions.md` describes the first three correctly but does not say the board number is zero. Related: `email_digest` "recipients" = `COUNT(users) WHERE email NOT LIKE '%@example.com'` = **40** every day (`novamart_analytics.digest_log`) — those are the 40 emails rewritten to `cust…@gmail.example` on 2019-10-23 (`app_events` `user_email_updated`, 40 events), including QA user 424242.

### 4.5 Signups / customers / registered accounts

- `users` (38,950) is first-touch creation, not signup; 4,112 have an order, 8,481 a cart item [F26]. Monthly "new users": Oct 15,093, Nov 11,294, Dec 12,562.
- Registered accounts beta: `novamart.accounts` (UUID ids) + `novamart.account_map(uid → account_id)`, 30 rows, all created 2019-12-01 16:30 UTC (`commit b567d9d`). `redash q4 registered_conversion` (`dash4`) = 30 buyers / $18,155.71 lifetime `status = 1` revenue, mapping accounts→users **by email** (`commit b975479`, 2019-12-21; the Dec 10 version joined `account_id::text = user_id::text` and returned nothing — "FIXME(dec): numbers look low", `commit d6e34c6`). The email join and the `account_map` join give identical results today [F17]. QA user 424242 is among the 30 (`cc27b436-d6f9-4e84-adaf-e716025dd369`), which is why `brand_revenue` hard-codes that UUID (`commit adbcb7e`) — a no-op filter since `orders.user_id` is numeric.

### 4.6 Best sellers / brand revenue / category revenue (exec dashboards)

All three (`redash q9/q8/q6`, `dash7/8/6`) share: item-level CTE (`order_lines` + legacy fallback), rolling window anchored at `now()` (7 d for best sellers, 30 d for brand/category), `user_id <> 424242`, `brand NOT IN ('lucente','jetem')`, **no status filter**, **no `EXCLUDED_SKUS`**, sorted by revenue [F28]. `docs/dashboard_notes.md` documents these rules accurately.

Traps: held/cancelled/refunded items count (best-sellers row `1005284` is 2 units both non-status-1 [F28]); "test SKU" `1002544` is #6 in the 7-day list; brand `''` (blank) is the 5th largest "brand" on `brand_revenue` ($17,585 / 30 d) — 482 blank-brand products have $84,795 lifetime paid revenue [F16] (root cause: `ensure_entities` inserts with `brand = ''`, `ON CONFLICT DO NOTHING`, and an in-process `_known_products` cache skips repair; partial fix `commit ea0e97b`, upsert `commit d213f6e`; forensic table `analytics.blank_brand_products`, 5,972 rows); the category dashboard's "versioned taxonomy" (`commit 33054cd`) remaps `electronics.audio.*` → `entertainment` and `construction.tools.light` → `lighting` only from `valid_from`, which in the warehouse copy is **2026-08-13** — so no 2019 order is ever regrouped and the dashboard still says `electronics` [F19][F28]; `category_names` has duplicate codes since that insert (135 rows).

Contrast with the *jobs*: `top_products` (`novamart/jobs/top_sellers.py`) is yesterday's `status = 1` **order** rows (not items) with no brand/QA/SKU filters, top 50 by units; the API `/reports/brands?month=` (`novamart/routers/reports.py`, **not mounted**) uses `status = 1`, order-level, applies `EXCLUDED_SKUS` + denylist and labels blank as `unbranded`. Three "brand revenue" surfaces, three answers (Dec: dashboard apple $236,606.73 vs API-style $208,128.38 [F28]).

### 4.7 Fees

`fee = round(price × 0.029 + 0.30, 2)` per payment row (`orders.py:19`), flat part since the deploy at **2019-11-20 14:27 UTC** (first `+0.30` payment 14:27:41Z, last without it 14:17:41Z [F07]) — not local midnight Nov 20 as `FEE_CHANGE_AT` in `monthly_statement.py:13` assumes. Oct fee restatement (−$0.14) is purely rounding-per-order vs rounding-once [F06]. Appendix A.2.

### 4.8 Funnel / sessions

`analytics.daily_funnel(day, sessions, users_active)` from `novamart/jobs/funnel.py`: events = `cart_items` ∪ `orders` in the last 24 h (no product views), sessionized per user by an inactivity gap that changed from **30 → 120 min** on 2019-12-14 (`commit f915c1b`; `job_runs` `gap_min` 30 until Dec 14, 120 from Dec 15) — series is not comparable across that date [F25]. Nov 15–17 spike (932–1,004 sessions) is the outage/backlog.

---

## 5. System

### 5.1 Components

| component | what | evidence |
|---|---|---|
| API | FastAPI app, routers mounted today: `catalog`, `carts`, `orders`, `similar`, `payments_webhook`; `/health` | `novamart/app.py:19-23` |
| Un-mounted routers (dead code, still in repo) | `users` (`/users/{id}/email`), `reports` (`/reports/brands`) dropped in `commit f1217a8`; `accounts` (`/accounts`) dropped in `commit c49a7bb` | `git log -p novamart/app.py` |
| DB access | psycopg async pool (max 22) for app; sync autocommit for jobs; **every statement logged** to `db_queries.log` with `[app]`/`[job]` tag → `novamart_logs.db_queries` | `novamart/db.py`, `novamart/logutil.py:23` |
| Logs | `app.jsonl` → `novamart_logs.app_events`; `jobs.jsonl` → `novamart_logs.job_runs`; ad-hoc engineer sessions tagged `[engineer:dev]`, `[engineer:maya]`, `[engineer-backfill:*]` | `db_queries` actor tags [F23][F24] |
| Scheduler | crontab (local times) until Jan 2020, then Airflow DAGs (one `BashOperator` each, `python -m novamart.jobs.<x>`) | `crontab.txt`, `airflow/dags/*.py`, `commit 4bfcbe6` |
| Warehouse | BigQuery `novamart-warehouse`; `public.*` → `novamart.*`, `analytics.*` → `novamart_analytics.*`; one-shot CSV export/load driven by `warehouse_manifest.json` | `novamart/jobs/warehouse_backfill.py`, `commit 5ae1182` |
| Dashboards | Redash, data source id 1 `novamart` type `pg` (Postgres SQL, not BigQuery); 9 dashboards × 1 table widget; query text identical to `dashboards/*.sql` at `41e3537^`; no cached results | Redash API [F-redash] |
| Flags | `deploy/flags.env` (`REC_MODEL_VERSION=2.0.0`, read per request by `similar.py:37`), `deploy/cron.env` (`ENABLE_DIGEST=1`, read by `email_digest.py:13`) | files |

### 5.2 Batch jobs (what each produces, what breaks when it fails)

Schedule = local time in `crontab.txt` / same string in Airflow (see caveat at end).

| job (module) | when | reads | writes | consumer | if it fails / caveats |
|---|---|---|---|---|---|
| `reconcile` | 03:00 | `orders` | nothing; WARNING `duplicate_payment_ref` per ref (LIMIT 200) | nobody acts on it | flags the same 130 refs nightly since 2019-10-19 [F13]; batch raised 100→200 `commit 030d841` |
| `affinity` (v1) | 03:30 | `cart_items` 30 d | `analytics.product_affinity` (full rewrite) | **nothing** since 2019-12-06 | can be dropped (`docs/affinity_lineage.md`); sentinel −1 for pairs < 3 (`commit fef5c96`) |
| `affinity_v2` | 03:45 | `cart_items`, `orders`, `products` | `analytics.product_affinity_v2` (full rewrite, `model_version='2.0.1'`) | `similar` widget (default), `model_train` | **crashed Dec 3-5** (`IndexError`, 11-entry `SEASONAL_FACTORS`; `job_runs` ERROR ×3; fix `commit 3dbe4d7`); widget falls back to trending if empty |
| `model_train` | 04:15 | `rec_decision_log` (random arm), `orders`, `users`, `products`, `product_affinity_v2` | `analytics.model_registry` (append), `analytics.model_scores` (rewrite) | nobody (flag = 2.0.0) | needs ≥20 rows and both classes |
| `price_suggest` | 04:45 | `products`, `orders` 14 d | `analytics.price_suggestions` (rewrite, 500 rows) | nobody (shadow, on hold `commit cca9b0d`) | ±5% nudge vs median demand |
| `trending` | 05:15 | `orders` 30 d (`status = 1`) | `analytics.trending_daily` (delete+insert for `day`) | `similar` fallback (**75%+ of all recs**), README | window 60→30 d `commit f563dea`; if it fails the widget serves yesterday's `MAX(day)` |
| `fraud_score` | 05:45 | `orders` 24 h, `users` | `analytics.order_risk` (append); **UPDATE orders SET status = 6** | revenue metrics (silently) | the only job that mutates app tables; threshold 0.90→0.70→0.85 |
| `daily_report` | 06:00 | `orders`, `order_lines`, `products`, `test_users` | `report_rows` (append) | `daily_kpis`, `revenue_widget` | no re-run → permanent gaps |
| `kpi_daily` | 06:15 | `orders` 30 d | `analytics.kpi_daily` (append) | nothing in Redash | — |
| `funnel` | 06:20 | `cart_items`, `orders` 24 h | `analytics.daily_funnel` (append) | nothing in Redash | gap 30→120 |
| `monthly_statement` | 06:30 on 1st | `orders`, `payments` | `statements` (append) | finance via views | see §4.1 |
| `top_sellers` | 06:45 | `orders` yesterday | `top_products` (append) | nothing visible | order-level, status 1 only |
| `reorder_forecast` | 06:50 | `orders` 14 d | `analytics.reorder_hints` (rewrite, 200) | advisory | `hint = 15.6 + 162.4/(velocity+1.8)` — **decreases** with velocity (`docs/forecast_caveats.md`) |
| `email_digest` | 07:15 | `orders` 7 d, `users` | `analytics.digest_log` | marketing | ran only from 2019-12-17 (flag name mismatch `DIGEST_ON` vs `ENABLE_DIGEST`, fixed `commit 8dc520b`, env read `commit 0bd4eac`); "top product" has been the two `EXCLUDED_SKUS` (1002544, 1004856) |
| `intraday_report` | 12:00, 17:00 | same as daily | `report_rows_intraday` (append) | `daily_kpis`, `revenue_widget` | Airflow keeps only 12:00 |
| `warehouse_backfill` | manual | Cloud SQL export | all BQ tables (`--replace`) | everything here | rebuilding the warehouse re-copies hand-made analytics tables only if they still exist in Postgres |

**Airflow caveat**: `crontab.txt:3` says "times are local"; the DAGs copy the same `HH:MM` cron strings with a naive `start_date` (`airflow/dags/*.py`). If the Airflow instance runs in UTC, every job now fires 4–5 h earlier in local terms (e.g. `daily_report` at 01:00/02:00 ET) — still after local midnight, so windows are intact, but intraday snapshots and the `kpi_daily` 30-day anchor shift. Not verifiable from here; flagging it.

### 5.3 Recommender ("similar products" widget)

`GET /products/{pid}/similar` (`novamart/routers/similar.py`). Per request:

1. `intended_version()` reads `deploy/flags.env` on every call (default `2.0.0`).
2. 5% of users (`sha256(uid) % 20 == 0`) get the **random arm**: 5 random products from the first 500 ids — training data for v4.
3. Otherwise read `analytics.product_affinity_v2` (if `2.0.0`) or `analytics.model_scores` (anything else), `score >= 0`, latest `updated_at`, top 5, minus `EXCLUDED_SKUS`; in-process cache 6 h, invalidated when the table's `MAX(updated_at)` changes (`commit 8ed2971`).
4. If nothing → `fallback`: top-5 of latest `analytics.trending_daily`.
5. Every decision → `analytics.rec_decision_log` + `app_events` `rec_served`.

Version history: `1.0.0` co-cart affinity, fallback = 7-day best sellers (`commit f1217a8`, 2019-10-26); `2.0.0` dispatch + random arm, fallback = trending (`commit df4ed85`, 2019-12-06); refactor dropped random-arm logging on Dec 18 (`commit 30e8907`; zero `arm='random'` rows that day; `model_registry.train_rows` stuck at 5,798 for Dec 18–19), restored + score cache `commit a00f24c` (Dec 19; cached empty lists → 25,091 `fallback/cache` rows Dec 19–26), epoch invalidation `commit 8ed2971` (Dec 26) [F21].

Does it work? Evidence says mostly no: 326,186 / 392,630 decisions were fallback under v1 (83%); under v2 207,959 / 275,220 (75.6%) fallback, 52,695 (19.1%) affinity, 14,566 (5.3%) random [F21]. Affinity covers 449 base products with ≥1 positive score out of 42,997 distinct products requested in December [F22]. No click/purchase attribution exists; `rec_decision_log.items` is the only exposure record.

### 5.4 Fraud

`fraud_score.py`: `core = min(price/3000, 1)`, `+15%` if account < 7 d old, `+15%` if ≥3 orders in 24 h, cap 1.0; `score > FRAUD_HOLD_THRESHOLD` → `status = 6`. Scored 1,631 orders since 2019-12-04; 12 held [F26][F20]. Any order ≥ $3,000 with a 0.85 threshold is held automatically; the Dec 3 cluster was eight $2,999.99 orders. Held orders keep their `payments` rows (money was collected).

---

## 6. Data

### 6.1 Inventory (BigQuery, row counts [F02])

**`novamart` (app tables, from Postgres `public`)**: `orders` 9,127 · `order_lines` 2,284 · `payments` 9,361 · `products` 81,018 · `users` 38,950 · `cart_items` 36,938 · `accounts` 30 · `account_map` 30 · `report_rows` 6,923 · `report_rows_intraday` 2,358 · `statements` 3 · `top_products` 2,396.

**`novamart_analytics` (from Postgres `analytics`)**: `product_affinity` 3,912 · `product_affinity_v2` 3,912 · `model_scores` 948 · `model_registry` 17 · `rec_decision_log` 667,850 · `trending_daily` 2,898 · `kpi_daily` 45 · `daily_funnel` 53 · `order_risk` 1,631 · `price_history` 1,400 · `price_suggestions` 500 · `reorder_hints` 200 · `digest_log` 15 · `test_users` 1 · `chargebacks` 3 · `statement_overrides` 1 · `statement_corrections` 1 · `category_names` 135 · `category_name_history` 6 · `blank_brand_products` 5,972; views `statements_corrected`, `statements_final`, `refunds_unified`, `contactable_users` [F03].

**`novamart_logs`**: `db_queries` 3,597,650 (Postgres statement log; `textPayload` = `"<ts> [<actor>] statement: <sql> -- params: ..."`), `app_events` 1,570,017 (`jsonPayload`), `job_runs` 978; view `db_queries_normalized` (parses actor/tables).

### 6.2 Source of truth per number

| number | source of truth | not the source of truth |
|---|---|---|
| money collected / fees | `payments` (gateway is "source of truth for money", `payments_webhook.py:1`) | `orders.price` (can be edited by appends; never reduced by refunds) |
| sold items | `order_lines` (+ legacy `orders`) | `orders.product_id` (first item only) |
| published monthly revenue | `statements` (as-published) / `statements_final` (restated) | any live recompute |
| daily revenue shown to execs | `report_rows` latest version per date | live `orders` (filters differ) |
| customer count | depends — §4.4 | `users` row count |
| what the widget showed | `rec_decision_log` | `app_events` `rec_served` (lacks items) |
| what changed when | `db_queries` (every statement incl. hand edits) + git | docs |

### 6.3 Hand-made objects not in `schema.sql` or any job

Created from engineer sessions (`db_queries` `[engineer-backfill:*]`): `analytics.blank_brand_products` (2019-10-21), `analytics.statement_overrides` + view `statements_corrected` + the Oct override row (2019-11-02), `analytics.price_history` (2019-11-15), `analytics.test_users` + row 424242 (2019-11-27), `analytics.category_names` + backfill (2019-11-30), `analytics.statement_corrections` + Nov row (2019-12-02), view `contactable_users` (2019-12-04), `report_rows_intraday` DDL (2019-12-08), `analytics.chargebacks` + 3 rows + view `statements_final` (2019-12-09), `category_name_history` + remap (2019-12-12), view `refunds_unified` (2019-12-23), `UPDATE orders SET status = 1 WHERE status = 6 AND price < 2600` (2019-12-29, affected 0 rows) [F24]. The chargeback rows were chosen as "the first three October orders over $700 with a payment", `reported_at` hard-coded `2019-12-01 12:00Z` — i.e. a synthetic booking, not gateway data.

### 6.4 Known data-quality facts

- `category_name_history.valid_from` and `blank_brand_products.captured_at` are **2026-08-13** in the warehouse (the `CURRENT_DATE`/`now()` of the backfill environment), which neuters the taxonomy history for 2019 orders [F19][F16].
- `payments.payment_ref` NULL before 2019-11-22; `order_lines` absent before 2019-11-22; `report_rows_intraday` from 2019-12-08; `rec_decision_log` from 2019-10-26; `kpi_daily` from 2019-11-17; `trending_daily` from 2019-11-03; `top_products` from 2019-11-06; `daily_funnel` from 2019-11-09 [F02][F11][F25].
- Timestamps are UTC; business days/months are `America/New_York` (`constants.py:28`). DST fall-back 2019-11-03 broke one report (`commit 102c9b4`). In this emulator, `CAST(ts AS STRING)` is needed to display timestamps in CSV output.
- 17,442 products (21.5%) have blank brand, 33,514 (41%) blank category [F26].
- Everything in `users` beyond `id`/`email`/`created_at` is a hash of the id (`onboarding.py`), so "region", "channel", "device", "age band", "opt-in" segmentation is noise by construction — and `marketing_opt_in` (62% by construction) is a model-train feature candidate.

---

## 7. Experimentation

### 7.1 Recommender A/B (the only live experiment)

- Arms: `random` 5% by user hash vs `model` (= affinity v2) 95%, since 2019-12-06 (`similar.py:48-50`, `commit df4ed85`). No holdout/control for the *business* question (does the widget lift conversion?); the random arm exists only to de-bias training data.
- Exposure log: `analytics.rec_decision_log` (ts, user, base product, items, intended/effective version, source, fallback reason, arm). Dec 18 random-arm rows missing (`commit 30e8907` → `a00f24c`).
- Outcome label used by `model_train.py:32-33`: user has **any** `status = 1` order with `created_at > exposure ts`. Not tied to the recommended items, not windowed — a user who bought anything two weeks later counts as a conversion for every earlier exposure.
- Features actually in the vector (5): `n_items`, `base_price/1000`, `base_popularity/100`, `min(account_age/60, 1)`, `organic_user` (`model_train.py:52-56`). Fetched but unused: `base_stock`, `opt_in`. README's list ("device mix, region affinity, stock level, marketing opt-in, signup channel", `README.md:43`) overstates it.
- Scoring: `model_scores = affinity_v2_score × (1 + 0.1 × coef[n_items])` for pairs with `score >= 0` (`model_train.py:68-72`). Single scalar → identical ranking to v2 (ratio 0.9755–0.9756 across all 948 rows on Dec 31 [F22]). Coefficients drift sign day to day (e.g. `organic_user` −2.35 on Dec 19, +0.04 on Dec 30, −0.16 on Dec 31) with 4k–14k rows — unstable.
- Serving: `REC_MODEL_VERSION=2.0.0`; v4 never served (no `effective_version='4.0.0'` rows [F21]). `docs/rec_versions.md` is "TBD".
- Verdict for Phase 3's "does it work": no measurable evidence it does; 75%+ of impressions are the trending list, and the trained model is a rescaled copy of the heuristic.

### 7.2 Shadow / held experiments

- **Dynamic pricing**: `price_suggest` writes 500 suggestions nightly since 2019-11-25 (`job_runs`); phase 2 on hold per exec/legal (`commit cca9b0d`, `price_suggest.py:47`); no reader anywhere (`docs/pricing_status.md`; grep confirms). Rule: `+5%` if 14-day units > median of the top-500 else `−5%` → 109 up / 386 down on Dec 31 [F26].
- **Reorder hints**: advisory, hand-fit, `K` refit 141.12 → 162.4 on 2019-12-21 (`commit f85cdd2`); inverse relation to velocity (`docs/forecast_caveats.md`).
- **Fraud threshold tuning**: 0.90 (Dec 3) → 0.70 (Dec 5) → 0.85 (Dec 29) with no evaluation data beyond `order_risk`; 8 of 12 holds happened on the first run at 0.90 [F20].
- **Promo discount cap**: `DISCOUNT_CAP = 0.25` and `apply_discounts()` (`commit 35c581e`) are referenced only by the ops script `scripts/rerun_kpis.py`, which has an empty `rows = []` — no production job applies discounts. "Discounted revenue" does not exist in any table.

### 7.3 How to run a clean before/after

Because outputs are append-only and definitions moved, compare like with like: use `report_rows` only for dates after 2019-12-15 (last filter change); `daily_funnel` only after 2019-12-15 (gap change); `trending_daily` only after 2019-12-07 (window change); `kpi_daily` is consistent throughout; `rec_decision_log` from 2019-12-06 excluding Dec 18.

---

## 8. Glossary

- **active customers** — three definitions (§4.4): rollup (30 d, status 1, no exclusions), exec dashboard (per local day, any status, QA/brand filters), board (30 d, non-cancelled, test_users + email heuristics → 0).
- **affinity / affinity v2** — co-cart pair scores (`analytics.product_affinity[_v2]`); v2 adds conversion weight ×3, same-category ×1.15, price-ratio ×0.7, seasonal factor; `model_version` string `2.0.1` inside a table served as version `2.0.0`.
- **append** (`order_appended`) — second gateway callback for the same user+session within 15 min merged into the existing order (`commit 5d1300d`).
- **as-published vs restated** — `statements` vs `statements_final` (`docs/restatement_policy.md`).
- **BRAND_DENYLIST** — `['lucente','jetem']`; hidden from report/dashboards, not from finance.
- **chargeback** — `analytics.chargebacks`, 3 hand-booked October orders ($3,567.57), subtracted in `statements_final` by the order's local month.
- **contactable** — `analytics.contactable_users` view; empty.
- **duplicate_payment_ref** — nightly WARNING from `reconcile`; 130 refs from Oct 1–15, 2019.
- **EXCLUDED_SKUS** — `[1004856, 1002544]`; 1004856 = "Internal Test #4856" (`qa.test`/`internal`, 328 orders), 1002544 = Apple smartphone (139 orders, $66.7K) — hidden from daily report and `/reports/brands` only.
- **EXCLUDED_STATUSES** — `[0, 2, 3]` for the report; status 6 (held) is *not* excluded.
- **fallback** — widget served top-5 trending because no affinity score existed (`rec_source='fallback'`).
- **FEE_RATE / FEE_FLAT** — 0.029 / 0.30 (flat since 2019-11-20 14:27 UTC deploy).
- **first-sight user/product** — row created by `ensure_entities` on view/cart/order with placeholder email / blank brand.
- **held** — `orders.status = 6`, set by `fraud_score`.
- **intraday snapshot** — `report_rows_intraday` row for "today", appended at 12:00/17:00 local; always take `MAX(created_at)` per date.
- **item_orders** — the dashboard CTE unioning `order_lines` with legacy `orders` rows that have no lines (`commit 92596dc`).
- **jetem** — brand with 5 products and no orders, denylisted 2019-12-15.
- **LOCAL_TZ** — `America/New_York`; all business windows.
- **lucente** — partner brand hidden from reports since 2019-10-25.
- **random arm** — 5% of users receive 5 random products; training data for v4.
- **REC_MODEL_VERSION** — `deploy/flags.env`; `2.0.0` live; `4.0.0` exists but unused; README wrong.
- **report_date** — local business day of the sale, written the next morning.
- **sentinel −1** — affinity score for pairs seen < 3 times; "not enough data", must be filtered with `score >= 0`.
- **statement_fee_mismatch** — WARNING when collected fee ≠ formula fee; fired for all three months (−0.01, +0.14, −170.41).
- **test_users** — `analytics.test_users` = {424242}.
- **trending** — `analytics.trending_daily`: 30-day `status = 1` units × `exp(−0.05 × days since last sale)`, min 5 units, top 50.
- **unbranded / blank brand** — `products.brand = ''`; `/reports/brands` relabels to `unbranded`, dashboards show `''`.
- **units vs orders** — `report_rows.units` and dashboard `units` are item rows since 2019-12-05; `statements.orders_count` and `top_products.units` are order rows; `daily_kpis.orders` is really items.
- **version (report rows)** — `created_at` of a report run; multiple per `report_date` are possible; consumers keep the latest.

---

# Appendix

## A. Phase 1 deep dive — revenue and finance

### A.1 "What was revenue in October 2019, and why?" — the bridge

All figures in USD, from [F27][F05][F14][F29][F10].

| step | amount | why |
|---|---|---|
| Published statement gross (board deck, Nov 1) | **1,230,332.43** | `SUM(orders.price)` for 3,765 `status = 1` orders in `2019-10-01 04:00Z … 2019-11-01 04:00Z` at 10:30 UTC on Nov 1 (`monthly_statement.py`, `job_runs`). Equals `SUM(payments.gross)` for the same orders exactly. |
| − fee as published 35,679.64 → net | 1,194,652.79 | fee = `round(gross × 0.029, 2)` (code before `commit a92c96d`). |
| fee restated to Σ per-order rounded fees 35,679.50 → net | 1,194,652.93 | `statement_overrides` row inserted 2019-11-02 (`db_queries`). Difference 0.14 = rounding once vs 3,774 times. |
| − chargebacks 3,567.57 → **final net** | **1,191,085.36** | orders 46 (940.82), 49 (1,891.94), 55 (734.81), booked 2019-12-09 with `reported_at` 2019-12-01; `statements_final` view. |
| Live `status = 1` gross today | 1,206,337.32 (3,695 orders) | 70 October orders (43 cancelled $10,748.42 + 27 refunded $13,246.69 = $23,995.11) changed status in the Tuesday batches Nov 5 – Dec 31. Adding back orders with `updated_at > 2019-11-01 10:30` reproduces 1,230,332.43 / 3,765 exactly. |
| of which duplicate-callback orders still status 1 | 58,828.24 (151 orders) | second–fifth bookings of the same `payment_ref`, Oct 1–15, pre-idempotency. Each has its own `payments` row, so cash and fees are duplicated too ($1,706.05 fees). Never corrected. |
| Daily report sum (`report_rows`) | 1,201,082.08 (3,631 units) | Oct 1–7 include lucente + test SKUs and (then-paid) later-cancelled orders; Oct 8+ exclude SKUs; Oct 25+ exclude lucente; no QA exclusion until Nov 27; order-level (pre Dec 5). |
| Dashboard-style item revenue | 1,210,334.97 (3,699 items) | any status, excl. QA 424242 and lucente/jetem items, includes test SKUs. |
| Lucente paid revenue in Oct | 19,465.39 (59 units) | hidden from reports, present in finance. |

So: **$1,191,085.36** is "October revenue" for finance today; **$1,194,652.79** is what the November deck said; **~$1.21M** is what an analyst gets from `orders` today; and a correct economic figure would additionally remove ~$58.8K of double-booked callbacks and treat $23,995.11 of later cancellations/refunds consistently with how chargebacks are treated.

**November 2019**: all three statement layers agree at gross 1,101,397.01 / fee 32,110.92 / net **1,069,286.09** (3,582 orders); live recompute identical (no Nov order has been cancelled/refunded) [F27]. `report_rows` sums to only 966,974.33 because of the Nov 3 (−2,985.99), Nov 15 (no row) and Nov 17 (−74,995.96) holes [F10].

**December 2019** (statement not yet run): live `status = 1` gross 552,328.93 (1,756 orders); +40,213.29 held (status 6); payments gross 590,698.63 incl. −1,843.59 refund rows (3× duplicated) and the held orders' payments; `report_rows` through Dec 30 = 535,561.72 [F27].

**September 2019**: 12 orders / $2,702 published on Oct 1 — all 12 have since been cancelled/refunded (ids 1–25, Tuesday batches), so live revenue is $0 while `statements_final` still says $2,623.64 [F09][F27].

### A.2 The fee change and the three WARNINGs

- `app_events` `statement_fee_mismatch`: Sep −0.01, Oct +0.14, Nov −170.41 [F08].
- Sep/Oct: rounding per order vs once (Oct Σ rounded fees 35,679.50 vs 1,230,332.43 × 0.029 = 35,679.64) [F06].
- Nov: on Dec 1 the code still expected `gross × 0.029` = 31,940.51 against collected 32,110.92 (flat fees). `commit 4a58d17` (Dec 2) changed the expectation to `price × 0.029 (+0.30 after FEE_CHANGE_AT)`; the audit row in `statement_corrections` recorded delta 0.00 because the statement already uses collected fees. Recomputing with the code's assumption gives expected 32,120.54 vs collected 32,110.92 (−9.62), explained by: 64 orders between local midnight Nov 20 and the 14:27 UTC deploy were charged without the flat fee (−19.20), and 23 multi-line orders were charged $0.30 per line (+9.60) [F07][F08].

### A.3 Who changes finance numbers and how

Only `monthly_statement` writes `statements`. Everything else is manual (`db_queries` `engineer-backfill:dev`): override row (2019-11-02 14:00Z), corrections row (2019-12-02 15:00Z), chargeback rows + `statements_final` (2019-12-09 15:00Z). On 2019-12-30 `engineer:dev` queried `statements_final` for columns `booked_chargebacks, corrected_net, override_net, published_net, source` that do not exist — someone expected a richer view than the one deployed [F24].

### A.4 Refund accounting rules in force

- App cancel/refund endpoints change `orders.status` only (`orders.py:114-155`); no `payments` row, no amount.
- Gateway refund webhook inserts `payments(gross = −amount, fee = 0, net = −amount)` only; status untouched; not idempotent (`payments_webhook.py`).
- `refunds_unified` unions both and is the refunds dashboard; nothing subtracts either from statements. Only chargebacks are subtracted.

## B. Phase 2 deep dive — dashboards, one by one (Redash, as of data end 2019-12-31)

| dash | query | shows | definition traps | reproduction [F28] |
|---|---|---|---|---|
| 9 `daily_kpis` | q7 | per local day: `orders`(=items), `revenue`, `active_customers`, `contactable_customers`; today from intraday, prior 13 days from `report_rows`; latest version per date; lucente/jetem removed again | `orders` is items since Dec 5; `contactable_customers` always 0; `active_customers` is per-day distinct buyers with *no status filter* but QA/brand filters, so not comparable to `kpi_daily`; missing days (Nov 15) simply vanish | Dec 30: 81 items, $24,767.62, 65 actives, 0 contactable |
| 2 `revenue_widget` | q2 | sum of last 7 calendar days incl. today | pre-Dec 24 version double-counted (`commit 686a5d6` → `3eced24`); depends on both daily and intraday jobs having run | — |
| 7 `best_sellers` | q9 | top 20 products by item revenue, rolling 7×24 h | no status filter (held/cancelled count), no `EXCLUDED_SKUS` (1002544 appears), sorted by revenue not units | top: 1005116 apple 6 units $5,889.81 |
| 8 `brand_revenue` | q8 | brand revenue, rolling 30 d | blank brand `''` is a top-5 "brand"; UUID exclusion is a no-op | apple $236,606.73 (334), samsung $128,113.51 (427), `''` $17,585.39 |
| 6 `category_revenue` | q6 | display-group revenue, rolling 30 d, versioned mapping | `entertainment`/`lighting` never apply (valid_from 2026); blank category → `other` ($93.6K) | electronics $437,887.95; other $93,558.92 |
| 5 `statements_final` | q5 | the three restated months | see A.1; Dec absent until Jan 1 run | Oct net 1,191,085.36 |
| 4 `registered_conversion` | q4 | registered buyers & lifetime revenue | 30 accounts frozen since Dec 5 (router removed); includes QA user | 30 / $18,155.71 |
| 3 `actives_board` | q3 | one number for the board | **0** | 0 |
| 1 `refunds` | q1 | monthly refunds count/total | month = status-change month; gateway rows ×3; chargebacks absent | Nov 32/$9,691.77; Dec 59/$18,848.93 |

Redash facts: data source is Postgres (`type: pg`), so the SQL is Postgres dialect (`LATERAL`, `~`, `::date`); none of the 9 queries has a schedule or a cached result (`latest_query_data_id: null`); all were created by "Admin" with description "migrated from dashboards/<name>.sql" [F-redash].

## C. Phase 3 deep dive — ML systems and batch jobs

### C.1 Affinity v1 vs v2 (`novamart/jobs/affinity.py`, `affinity_v2.py`)

Both: `cart_items` self-join on `session` within 30 d, pair counts, `MIN_PAIRS = 3` else sentinel −1, decay `exp(−0.05 × days since last co-cart)`, full `DELETE` + `INSERT` nightly. v2 adds `W_ORDER = 3 ×` conversions (did the *second* product's user ever buy it, `status = 1`), ×1.15 same non-blank category, ×0.7 if list-price ratio > 4 or < 0.25, × seasonal factor (`[1.00 … 1.12]` for Jan–Nov, **1.0 for Dec** after the crash fix). Dec 31 snapshot: 3,912 pairs, 2,964 sentinel, 948 scored, 449 base products [F22]. v1 has the same pair set and is unused.

### C.2 v4 training (`model_train.py`) — see §7.1

`model_registry` has 17 rows (Dec 15–31), train_rows 4,197 → 14,411 [F22]. `requirements.txt` pins `scikit-learn==1.5.1`.

### C.3 Trending (`trending.py`)

30-day `status = 1` units per product (≥5), score `units × exp(−0.05 × age_days)`, top 50, `DELETE WHERE day` then insert; `job_runs` show `window_days` 60 until Dec 6 and 30 from Dec 7 [F25]. It is the real recommender for 75%+ of impressions.

### C.4 Safe-modification checklist for the batch pipelines

1. Jobs are independent processes with no DAG dependencies; ordering is by clock only (03:00 → 07:15). If you move `affinity_v2` after `model_train`, v4 trains on yesterday's scores; if you move `fraud_score` after `daily_report`, held orders will be in the report as status 1 (they already are, as status 6).
2. Jobs create their own tables with `CREATE TABLE IF NOT EXISTS`; hand-made tables/views (§6.3) will not be recreated anywhere.
3. `FAKE_NOW` env drives `timeutil.now()` for backfills (`timeutil.py:12-17`; used by `ci/run_ci.py:64`). A re-run of `daily_report` appends a second version for that `report_date`; dashboards take `MAX(created_at)` so a backfill of Nov 17 is possible and safe for `daily_kpis`/`revenue_widget` but would *not* change `statements`.
4. `email_digest` is the only job that returns silently when disabled; the others crash loudly (`job_runs` ERROR `job_crashed`).
5. Any new filter belongs in `constants.py` **and** in all 4 dashboard queries (they hard-code `424242` and the brand list) — there is no shared definition layer.
6. `warehouse_backfill` uses `bq load --replace`; re-running it drops BigQuery-side history. The Postgres serving DB is the source.

## D. Timeline of definition changes (from `git log`, [F01])

| date | commit | effect on numbers |
|---|---|---|
| 2019-09-15 | `2da4141` | initial import; dashboards: 7-day best sellers, 14-day daily KPIs, 30-day brand revenue, no filters |
| 2019-10-08 | `83fb3ed` | `EXCLUDED_SKUS = [1004856, 1002544]` in daily report |
| 2019-10-15 | `b676969` | callbacks idempotent by `payment_ref` (duplicates stop) |
| 2019-10-16 / 10-21 | `088a372`, `193f22d` | `/users/{id}/email`, `/reports/brands` added |
| 2019-10-18 | `030d841` | reconcile batch 100 → 200 |
| 2019-10-21 | `ea0e97b` | blank-brand repair on product view/feed |
| 2019-10-25 | `ba1fbfa` | `lucente` denylisted |
| 2019-10-26 | `f1217a8` | similar widget v1.0.0; `users` + `reports` routers un-mounted |
| 2019-10-28 | `8f19718` | cancel endpoint; `STATUS_CANCELLED` 4 → 2 |
| 2019-11-02 | `a92c96d` | statement fee = collected fees; Oct override inserted (db) |
| 2019-11-02 / 11-06 / 11-08 | `152a760`, `9a51155`, `4dbcf7f` | trending (60 d), top_sellers, funnel (30 min) jobs |
| 2019-11-05 | `102c9b4` | DST-safe day window |
| 2019-11-09 | `d213f6e` | price feed upserts prices |
| 2019-11-12 | `fef5c96` | affinity sentinel −1 for < 3 pairs |
| 2019-11-15 | `d87cb3d`, `795d273` | refund endpoint (status 3); `price_history` |
| 2019-11-16 | `14726e7` | `kpi_daily` 30-day actives |
| 2019-11-18 / 11-19 | `11c0a42`, `1233af8` | report excludes 2,3; removes 500 cap |
| 2019-11-20 | `12e1c68` | `FEE_FLAT = 0.30` (deployed 14:27 UTC) |
| 2019-11-21 | `35c581e` | `DISCOUNT_CAP = 0.25` (unused in prod) |
| 2019-11-22 | `5d1300d` | multi-line orders, `order_lines`, `payments.payment_ref` |
| 2019-11-24 / 11-26 / 11-28 | `894c535`, `f5e3032`, `c19a307` | price_suggest, reorder_forecast, email_digest (flag broken) |
| 2019-11-27 | `b59f077`, `b567d9d` | QA 424242 excluded; `/accounts` added |
| 2019-11-30 | `2814b3d` | category_revenue dashboard + `category_names` |
| 2019-12-02 | `89666bf`, `cca9b0d`, `4a58d17` | affinity v2; pricing on hold; flat-fee expectation + Nov audit row |
| 2019-12-03 | `e4656fb` | fraud score, threshold 0.90, status 6 |
| 2019-12-04 | `e10cb0c` | `contactable_users` view (empty) + KPI column |
| 2019-12-05 | `c49a7bb`, `92596dc`, `53f6f6c`, `3dbe4d7` | gateway refund webhook (accounts router un-mounted); per-item counting; threshold 0.70; Dec seasonal fix (`2.0.1`) |
| 2019-12-06 | `df4ed85`, `f563dea` | version dispatch + random arm; trending 60 → 30 d |
| 2019-12-08 / 12-09 | `a2e0013`, `cd559d3`, `8dc520b` | intraday snapshots; chargebacks + `statements_final`; digest flag fix |
| 2019-12-10 / 12-11 / 12-12 | `d6e34c6`, `2dde4f0`, `33054cd` | registered conversion (broken join); board actives (→0); taxonomy history |
| 2019-12-14 / 12-15 | `f915c1b`, `a1946ff`, `1169e40` | funnel gap 120; model_train v4; `jetem` denylisted |
| 2019-12-16 / 12-17 | `0bd4eac`, `30e8907` | digest reads cron.env (first digest Dec 17); similar refactor drops random logging |
| 2019-12-19 | `686a5d6`, `a00f24c` | revenue widget (double counting); random logging restored + cache |
| 2019-12-21 | `b975479`, `f85cdd2` | registered conversion via email; reorder K refit |
| 2019-12-23 / 12-24 | `a3bffec`, `3eced24` | refunds view/dashboard; widget fix |
| 2019-12-26 | `8ed2971` | cache invalidation on refresh |
| 2019-12-29 | `1cb8721` | threshold 0.85; release < $2600 (0 rows) |
| 2020-01-02 … 01-05 | `d398b0d`, `41e3537`, `4bfcbe6`, `5ae1182` | docs; dashboards → Redash; crontab → Airflow (intraday 17:00 dropped); warehouse backfill |

## E. Incident / anomaly register

| when | what | evidence | status |
|---|---|---|---|
| 2019-10-01 → 10-15 | 130 payment refs booked 2–5× (155 extra orders, $59.8K) | [F13][F14], `app_events` `duplicate_payment_ref` | fixed going forward; data never corrected; Oct statement includes it |
| 2019-10-23 | 40 user emails changed to `cust…@gmail.example` | `app_events` `user_email_updated` | these 40 are the digest "recipients" |
| 2019-11-03 | DST: report window 24 h instead of 25 h; −8 units / −$2,985.99 | [F10], `commit 102c9b4`, engineer queries Nov 5 | permanent |
| 2019-11-15 | no orders all day (checkout outage) | [F12] | permanent gap in `report_rows` |
| 2019-11-17 | report scanned 500 of 735 orders; −$74,995.96 | [F10][F11], `commit 1233af8` | permanent |
| 2019-11-20 09:27 ET | flat fee deployed mid-day; 64 orders under-charged $0.30 | [F07] | reflected in payments; statement uses collected |
| 2019-12-03 → 12-05 | `affinity_v2` crashed 3 nights (`IndexError`) | `job_runs` ERROR | fixed `3dbe4d7`; v2 table was stale/empty for the Dec 6 launch morning |
| 2019-12-03 | 8 × $2,999.99 orders held (fraud) | [F20] | still held |
| 2019-12-13/20/27 | gateway refunds replayed 3× | [F15][F29] | still in `payments`/refunds dashboard |
| 2019-12-18 | random-arm decisions not logged | [F21], `commit 30e8907` | permanent gap |
| 2019-12-19 → 12-26 | empty score lists cached → 25,091 `fallback/cache` | [F21], `commit a00f24c` → `8ed2971` | fixed |
| 2019-12-19 → 12-24 | exec revenue widget double-counted | `commit 686a5d6` → `3eced24` | fixed |
| 2019-12-29 | "release held < $2600" released 0 orders | [F24][F20] | open |
| ongoing | `actives_board` = 0; `contactable_customers` = 0 | [F18] | open |
| ongoing | Apple SKU 1002544 treated as test SKU | [F16] | open |
| ongoing | README stale (rec version 4.0.0, trending 60 d) | `README.md:35,43` vs `flags.env`, `trending.py` | open |
| Jan 2020 | Airflow kept one intraday run; schedule TZ ambiguity | `airflow/dags/intraday_report_dag.py` | open |

## F. Evidence index (files in this directory)

- `01_git_log.txt` — full commit list [F01]
- `git_dashboards/*.sql` — dashboard SQL as removed from git at `41e3537^`
- `redash/query_<1-9>.json`, `redash/dashboard_<1-9>.json` — Redash API dumps [F-redash]
- `bq/02_schemas.txt` — all tables, columns, row counts [F02]
- `bq/03_views*.{txt,csv}` — view definitions [F03]
- `bq/04_statements.txt`, `bq/04b_statements_ts.txt` — statements, overrides, corrections, chargebacks [F04][F04b]
- `bq/05_reproduce_statements.txt` — reproduction of published gross from `orders` [F05]
- `bq/06_fees_payments.txt`, `bq/07_fee_change.txt`, `bq/08_nov_fee_delta.txt` — fee analysis, deploy timing, WARNINGs [F06][F07][F08]
- `bq/09_report_rows_versions.txt`, `bq/10_report_vs_orders.txt`, `bq/11_job_runs.txt` — daily report vs truth, job history [F09][F10][F11]
- `bq/12_nov15_gap.txt` — outage evidence [F12]
- `bq/13_status_dups_reconcile.txt`, `bq/14_dup_impact.txt` — statuses, duplicate refs, reconcile [F13][F14]
- `bq/15_refunds.txt`, `bq/29_cancel_refund_cadence.txt` — refunds, cadence, gateway duplicates [F15][F29]
- `bq/16_brands.txt`, `bq/17_qa_accounts.txt`, `bq/18_contactable_actives.txt`, `bq/19_categories.txt` — brands, QA/accounts, actives, taxonomy [F16]–[F19]
- `bq/20_dec3_fraud.txt` — held orders, thresholds [F20]
- `bq/21_rec_decision_log.txt`, `bq/22_model.txt` — recommender logs, model registry, score ratio [F21][F22]
- `bq/23_logs_overview.txt`, `bq/24_engineer_queries.csv` — log structure; all 191 engineer statements [F23][F24]
- `bq/25_intraday_trending_funnel.txt`, `bq/26_users_prices_risk.txt` — intraday versions, trending/funnel changes, users, prices, risk [F25][F26]
- `bq/27_revenue_reconciliation.txt` — monthly bridge across all definitions [F27]
- `bq/28_dashboards_reproduced.txt` — dashboards re-run in BigQuery as of 2019-12-31 [F28]
- `bqq.sh` — the read-only query helper used for all of the above

## G. Method

1. Read every file in the repo at `5ae1182` (code, docs, DAGs, schema, old dashboard SQL via `git show`), then `git log -p` on the files whose definitions matter.
2. Listed all BigQuery objects, pulled view DDL from `INFORMATION_SCHEMA.VIEWS`, and recomputed each metric from base tables to confirm or contradict the code/docs.
3. Mined `novamart_logs.job_runs` for run cadence/failures, `app_events` for business events and WARNINGs, and `db_queries` for the `[engineer*]` sessions that created every hand-made table/view/row.
4. Pulled all Redash queries/dashboards via API and diffed them against git.
5. Every number above was produced by a query saved in `bq/`; where the docs and data disagreed (README, `rec_versions.md`), the data won.
