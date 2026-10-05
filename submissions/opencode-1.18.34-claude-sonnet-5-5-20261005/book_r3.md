# Novamart tribal knowledge: how the numbers are made, and when not to trust them

- Run start (wall clock): **2026-10-05 18:51:29 UTC**. Run UUID: **cfbced3d-1572-44da-a48e-69ad32f49ba0**. This file and all intermediate output live in the directory named by that UUID.
- Sources used (only these): repo `novamart` pinned at `5ae1182` (2020-01-05); BigQuery emulator, project `novamart-warehouse` (datasets `novamart`, `novamart_analytics`, `novamart_logs`); Redash at `localhost:5055` (read-only GETs). Nothing was written, refreshed or mutated anywhere. The only queries run were SELECTs.
- Data window: orders 2019-09-25 to 2019-12-31. Warehouse loaded 2020-01-05 by a one-shot backfill. The real clock is 2026, so every `now()`-anchored dashboard is a time bomb (see section 4.9).

**How to read citations.** Every claim carries evidence in square brackets.
- `[git abc1234]` is a commit in the pinned repo. Full history: `notes/repo/git_log_oneline.txt`, code patches: `notes/repo/git_log_patches_code_only.txt`.
- `[repo path:line]` is a file at `5ae1182`.
- `[Q name]` is a warehouse query. The SQL is `queries/name.sql` and the result is `queries/name.out`.
- `[T dataset.table]` or `[V dataset.view]` is a warehouse table or view.
- `[LOG job_runs|app_events|db_queries ...]` is a log export row.
- `[Redash #id name]` is a Redash query or dashboard. JSON in `redash/`.
- `[adhoc N]` is an engineer ad-hoc statement in the Postgres statement log (`[engineer:*]` or `[engineer-backfill:*]` sources), line N of `notes/engineer_adhoc_queries.txt`.

Where something is my inference rather than directly observed, it says **inference**.

---

# 1. Summary

**What novamart is.** A marketplace backend (FastAPI plus Postgres) that records product views, cart adds and orders (created from payment-gateway callbacks). A set of nightly batch jobs turns those rows into reports, finance statements, rankings and recommendation scores [repo README.md; repo novamart/app.py; repo novamart/jobs/*]. Dashboards moved from SQL files in git to Redash on 2020-01-03 [git 41e3537]. Schedules moved from cron to Airflow on 2020-01-04 [git 4bfcbe6]. The warehouse was bulk-loaded into BigQuery on 2020-01-05 [git 5ae1182].

**Ten things a tenured person knows that the code and docs do not say**

1. **There is no single "revenue".** For October 2019 there are at least six defensible answers, from 1,147,509 to 1,230,332 gross (table in 4.1). The canonical finance answer is `analytics.statements_final` (October net 1,191,085.36). The as-published answer is `novamart.statements` (1,194,652.79). Neither matches the orders table, because statements are append-only snapshots taken on the 1st of the following month and never re-cut for later cancellations, refunds or duplicate callbacks [T novamart.statements; V analytics.statements_final; Q month_variants; docs/restatement_policy.md].
2. **October is inflated by ~$58.8k of duplicate-callback orders.** 130 payment refs have 2 to 5 orders each, all created between 2019-10-01 and 2019-10-15. The idempotency fix [git b676969] landed 2019-10-15. Nothing ever removed the duplicates. The nightly `reconcile` job only logs them, 10,766 WARNING lines so far [Q dup_refs; Q dup_refs_dates; Q dup_refs_month; LOG app_events duplicate_payment_ref; repo novamart/jobs/reconcile.py].
3. **All cancellations and refunds hit the very first orders.** Every order in status 2 (cancelled) or 3 (refunded) was created between 2019-09-25 and 2019-10-01 13:48 UTC. They were flipped weekly from 2019-11-05 onward, after the September and October statements had already been published. The published October statement still counts 70 of them ($23,995.11), and September's 12-order statement is now 100% cancelled or refunded [Q orders_status; Q cancel_updated; Q month_variants; Q stmts_raw].
4. **Daily report rows are frozen snapshots under the rules of the day they ran.** `report_rows` has exactly one version per date (92 dates) and is never restated. Known distortions, none backfilled:
   - 2019-11-17 undercounted ~$75k, from the 500-row scan cap fixed [git 1233af8] on 11-19.
   - 2019-11-03 undercounted ~$3k, from the DST window bug fixed [git 102c9b4] on 11-05.
   - 2019-11-15 has no orders at all.
   - 2019-10-01 is overstated ~$24k because it counted orders cancelled later.
   - Pre-10-08 days include the two "test" SKUs, and pre-10-25 days include `lucente`
   [Q rr_versions; Q report_vs_ideal; Q dr_cap; Q nov15].
5. **The board "active customers" query returns 0.** It excludes `example.com` and `*.example` emails. 38,910 of 38,950 users have the placeholder `userNNN@example.com`, and the other 40 have `custNNN@gmail.example`. So all of them are filtered out [Redash #3 actives_board; Q users_domain; Q dash_actives_board]. The trailing-30-day count of status-1 buyers at year end is ~1,146 [Q actives_defs]. `contactable_customers` in the KPI dashboard is also always 0, because `analytics.contactable_users` is empty for the same reason [Q contactable_cnt; Q dash_daily_kpis].
6. **The recommendation widget mostly serves "fallback" items, and every fallback list contains a QA/test SKU.** The fallback is the 7-day best sellers before 2019-12-06 and `trending_daily` top 5 after. 534,145 of 534,145 fallback exposures include SKU 1004856 ("Internal Test #4856", brand `internal`, category `qa.test`) or 1002544. The fallback path does not apply the `EXCLUDED_SKUS` filter. Fallback was 83% of v1-era exposures and ~80% of non-random exposures since v2 [Q excl_in_fallback; Q rec_groups; repo novamart/routers/similar.py].
7. **"Rec model v4" has never been served.** `deploy/flags.env` says `REC_MODEL_VERSION=2.0.0`, and no `4.0.0` row exists in `rec_decision_log`. The README claims v4 serves, which is false. Mechanically v4 scores are `affinity_v2.score × (1 + 0.1·w)`, where `w` is the coefficient of a feature that is constant (always 5 items). The ranking is identical to v2 [repo deploy/flags.env; Q rec_groups; Q model_vs_v2_rank; Q rand_nitems; repo novamart/jobs/model_train.py].
8. **The "uniform-random" arm is not uniform.** It draws from `SELECT id FROM products ... ORDER BY id LIMIT 500`, the 500 lowest product ids out of 81,018. It also covers only ~4.6% of users, from 942 distinct users, and its decision logging was dropped by mistake from 2019-12-17 to 12-19 [Q rand_items; Q prod_500; Q rand_users; Q rec_daily; git 30e8907; git a00f24c].
9. **User attributes are synthetic.** Region, channel, device, age band and marketing opt-in are `sha256(user_id)` buckets, and emails are placeholders. `users` rows are created on first sight of a user id in a view, cart or order, so `users` (38,950) is "everyone seen", not "signups". Any cut by signup channel is noise (counts are ~6.4k to 6.6k per channel) [repo novamart/onboarding.py; Q users_by_channel; Q viewer_to_user]. Product `title`, `vendor`, `cost_price` and `stock` are also hash-synthesized.
10. **Orders collapsed ~65% on 2019-11-23 with no matching change in views or carts.** Orders per day went from ~100 to ~35, while views stayed ~7k to 9k per day and carts ~330 to 350 per day. The drop is across every channel, category and price band. Nothing in the repo or logs explains it (see 4.8). It coincides with the order-merge deploy of 2019-11-22 [git 5d1300d], but merges account for only 2 to 8 orders a day, so that is a lead, not an explanation [Q daily_events; Q drop_by_channel; Q drop_by_cat; Q drop_by_price].

**Answering "what was revenue in month X, and why", the way a tenured person does**

1. Ask what the consumer needs: the as-published number, the current restated finance number, or the operational "paid orders now" number.
2. Published: `novamart.statements` (the `public.statements` of the docs). Current finance: `analytics.statements_final`.
3. Explain any gap to a status=1 orders sum with the waterfall in 4.1: post-publication cancellations or refunds, duplicate callback refs, chargebacks, un-netted gateway refunds, held orders, and local-vs-UTC month windows.
4. Never use `report_rows` or dashboards for finance totals (they hide brands and SKUs and have the snapshot flaws above).

**Where each number lives**

| Number | Source of truth | Do not use |
|---|---|---|
| Monthly finance revenue | `analytics.statements_final` (current) / `novamart.statements` (as published) | dashboards, `report_rows` |
| Order-level money | `novamart.orders` + `novamart.payments` | `orders.price` alone for multi-line orders when attributing to products |
| Product units / revenue by day | `novamart.order_lines` with legacy fallback to `orders` (dashboards, report jobs) | `top_products`, `trending_daily` (they count `orders.product_id` only) |
| Active customers | none; four competing definitions (4.5) | the board query |
| Recommendations quality | `analytics.rec_decision_log` + orders | `model_registry` coefficients |

---

# 2. Why this project

**Purpose of this knowledge base.** The brief is to understand how novamart computes its core financial numbers, how product and customer analytics are reported, and how the ML and batch systems work, so a newcomer can (a) answer "what was revenue in month X and why", (b) explain any dashboard number including when it is untrustworthy, and (c) judge the ML systems and modify the batch pipelines safely. The source system is a code base with no maintained docs. The `docs/` notes are previous investigations, several partly stale (Appendix C).

**Why the numbers are hard.** Four forces combine, each evidenced below:
- **Overlapping definitions.** Revenue, "orders", "units", "active customers" and "best sellers" each have 3 to 6 competing definitions, written at different times by different people (timeline in Appendix A).
- **Append-only snapshots plus after-the-fact mutation.** Statements, reports and KPI rows are appended once and never restated, while order statuses change weeks later.
- **Hand-applied fixes.** Overrides, corrections, chargebacks and views were created by hand through ad-hoc scripts (`[engineer-backfill:*]` sources in the statement log), not through migrations in the repo [adhoc 47, 63, 69, 159, 169, 239, 241, 257, 259, 325].
- **Platform migration.** In January 2020 dashboards went to Redash, schedules to Airflow, and data to BigQuery. Redash still queries Postgres (`estate-pg`), not BigQuery [Redash data_sources/1: type `pg`, host `estate-pg`; docs/data-access.md].

**People and ownership signals** (from authorship; no org chart exists in the sources):
- *Maya Iyer* (54 commits) wrote most of the serving app: orders and refunds endpoints, accounts, the rec widget, dashboards (board actives, registered conversion, revenue widget), the fraud threshold changes, and the email digest [git log, author column].
- *Dev Kapoor* (54 commits) wrote most batch jobs and finance corrections: monthly statement fix, affinity v1 and v2, trending, KPI rollup, price_suggest, reorder, fraud_score, and the docs on pricing, forecast and restatement.
- *Novamart Platform* (4 commits) did the January 2020 migration.
- `trigger deploy #d2p-novamart` commits are empty deploy markers. 35 of them exist at the pin. (`origin/main` is 2 commits ahead of the pinned `5ae1182`; those were deliberately not read.) Code on `main` is not live until the next marker (e.g. [git 96cfd0b]).

---

# 3. Business understanding

## 3.1 What the business does

A marketplace selling mostly electronics (apple 49% and samsung 18% of status-1 revenue), plus appliances, apparel, construction, kids [Q brand_all; T analytics.category_names]. The catalogue is built "on first sight": product and user rows are created when an id first appears in a view, cart or order callback, with metadata filled from the onboarding hashing or the weekly vendor price feed [repo README.md "Notes"; repo novamart/routers/catalog.py ensure_entities; repo novamart/onboarding.py].

Scale (warehouse snapshot) [Q orders_misc; Q cust_counts; Q prod_ids]:

| Entity | Count |
|---|---|
| Orders | 9,127 (9,033 status 1) |
| Order lines | 2,284 (on 2,059 orders) |
| Payments rows | 9,361 |
| Users seen | 38,950 |
| Users with a cart | 8,481 |
| Users with an order | 4,112 (4,089 with a paid order) |
| Repeat paid buyers | 1,650 |
| Products | 81,018 (21.5% have blank brand: 17,442) |
| Registered accounts (beta) | 30 |

## 3.2 Order lifecycle and money flow

1. A payment-gateway callback `POST /orders` carries `uid, pid, ts, session, price, ref` [repo novamart/routers/orders.py]. The order price is whatever the callback says. It is not validated against `products.list_price` (paid price averages 1.385× list on single-product orders; only 2,369 of 8,765 equal list) [Q order_price_vs_list].
2. The handler is idempotent on `payment_ref` (since [git b676969] 2019-10-15). A replay logs `order_callback_replayed` (522 events) [LOG app_events].
3. Since [git 5d1300d] (2019-11-22), a callback from the same user and session within 15 minutes of an existing non-cancelled, non-refunded order is **merged**: `orders.price += price`, a new `order_lines` row and a new `payments` row are added, and `order_appended` is logged (225 events). Consequences:
   - `orders.product_id` is only the first line's product (173 of 173 multi-line orders match their first line) [Q lines_first_product].
   - `orders.price` equals the sum of line prices (2,059 of 2,059) [Q lines_vs_orderprice].
   - `payments` has one row per line (fee is per line).
4. Status codes (status constants and logs):

| Code | Meaning | Evidence |
|---|---|---|
| 0 | pending, transient (inserted then set to 1 in the same request) | [repo orders.py] |
| 1 | paid / completed | [repo orders.py] |
| 2 | cancelled | `STATUS_CANCELLED` was 4 until [git 8f19718] (2019-10-28) changed it to 2. No status-4 rows exist. |
| 3 | refunded | [git d87cb3d] `/orders/{id}/refund` |
| 5 | never written. The reconcile job still filters `status <> 5` (stale) | [repo reconcile.py] |
| 6 | fraud hold | [git e4656fb] |

   Current distribution: 1 = 9,033, 2 = 54, 3 = 28, 6 = 12 [Q orders_status].
5. **Fees.** `fee = round(price × 0.029, 2)` until [git 12e1c68] (2019-11-20), then `round(price × 0.029 + 0.30, 2)` per payment row. The change took effect mid-day 2019-11-20 (avg extra over % rises 0.141 on 11-20 and 0.300 from 11-21), not at local midnight as `FEE_CHANGE_AT` assumes [Q fee_change_boundary; Q fee_when_changed; repo novamart/jobs/monthly_statement.py].
6. **Refund paths** (three, not reconciled with each other):
   - Order-status refund or cancel via the app endpoints. This changes `orders.status` only. No negative payment row is written.
   - `POST /payments/gateway_refund` [git c49a7bb] writes a negative `payments` row with zero fee but leaves the order at status 1. "The gateway is the source of truth for money."
   - Chargebacks booked by hand in `analytics.chargebacks` (4.1).
7. **Fraud hold.** The nightly `fraud_score` job scores orders from the last day (status 1): `core = min(price/3000, 1)`, `score = min(core × (1 + 0.15·new_account + 0.15·high_velocity), 1)`. It moves orders above `FRAUD_HOLD_THRESHOLD` to status 6 [repo novamart/jobs/fraud_score.py]. The threshold went 0.90 [git e4656fb], then 0.70 [git 53f6f6c], then 0.85 [git 1cb8721]. The 2019-12-29 manual statement `UPDATE orders SET status = 1 ... WHERE status = 6 AND price < 2600` released 5 orders [adhoc 343; Q risk_mid]. Twelve orders ($40,213.29) remain held [Q held_orders]. Held orders are excluded from statements (status = 1 only) but are **included** in the daily report, because `EXCLUDED_STATUSES = [0, 2, 3]` [repo constants.py].
8. **Who counts as test or internal.** QA smoke user `424242` (weekly Wednesday orders, session `qa-smoke`, 13 paid orders of $9.99, product `1004856`) is in `analytics.test_users` [adhoc 159; Q qa_orders; Q qa_sessions; Q qa_orders_dates]. The brand `internal` is not on any denylist. The "hard-exclude QA account UUID" [git adbcb7e] casts `bigint user_id` to text and compares to an account UUID, so it can never match. It is a no-op (the UUID is `account_map` for user 424242) [Redash #8 brand_revenue; Q qa_account].

## 3.3 Business events timeline that affects interpretation

| Date | Event | Evidence |
|---|---|---|
| 2019-09-15 | repo import. First dashboards (`best_sellers`, `brand_revenue`, `daily_kpis`) | [git 2da4141] |
| 2019-09-25 | First data (QA smoke order; internal test SKU created) | [Q fresh_novamart_orders; Q excl_skus_products] |
| 2019-10-01 | First real day: 107 orders, of which 70 are later cancelled or refunded | [Q rr_vs_orders_daily] |
| 2019-10-08 | Two SKUs hidden from the daily report | [git 83fb3ed] |
| 2019-10-15 | Order idempotency fix. Last duplicate-ref order created 2019-10-15 10:27 UTC | [git b676969; Q dup_refs_dates] |
| 2019-10-23 | 40 users' emails changed to `custNNN@gmail.example` (the only non-placeholder emails) | [LOG app_events user_email_updated; adhoc 211] |
| 2019-10-25 | `lucente` brand hidden from reports (partnerships) | [git ba1fbfa] |
| 2019-11-01 | October statement published (gross 1,230,332.43) | [LOG job_runs monthly_statement] |
| 2019-11-02 | Fee correction override for October | [git a92c96d; adhoc 63] |
| 2019-11-03 | DST fall-back day; report window bug (fixed 11-05) | [git 102c9b4; adhoc 81] |
| 2019-11-15 | Zero orders (carts 2,284 and views 28.7k, ~3× normal). 11-16 and 11-17 then carry 401 and 735 orders | [Q daily_events; Q spike_hours] |
| 2019-11-20 | Processor fee becomes 2.9% + $0.30 | [git 12e1c68] |
| 2019-11-22/23 | Order merge deploy, then orders collapse ~65% | [git 5d1300d; Q daily_events] |
| 2019-12-01 | 30 beta accounts created. December statement not yet generated (the monthly job runs the 1st) | [LOG app_events account_created] |
| 2019-12-03..05 | `affinity_v2` crashed 3 nights (IndexError, no December seasonal factor); fixed | [LOG job_runs job_crashed ×3; git 3dbe4d7] |
| 2019-12-06 | Widget switches from affinity v1 to v2 plus a random arm; trending window 60→30 days | [git df4ed85; git f563dea; Q stmt_templates] |
| 2019-12-09 | Chargebacks booked (3 orders) and `statements_final` view created | [git cd559d3; adhoc 239, 241] |
| 2019-12-13 | First of three weekly replays of 3 gateway refunds | [Q gw_events] |
| 2019-12-17 | Email digest first actually sends (wired since 11-28) | [LOG job_runs email_digest; T analytics.digest_log] |
| 2019-12-29 | Fraud threshold to 0.85 and manual release of held orders under $2,600 | [git 1cb8721; adhoc 343] |
| 2020-01-02..05 | Platform migration: docs, dashboards to Redash, schedules to Airflow, BigQuery backfill | [git d398b0d, 41e3537, 4bfcbe6, 5ae1182] |

---

# 4. Metrics

Common convention: "month" in finance means a **local (America/New_York) calendar month**, converted to a UTC window [repo constants.py `LOCAL_TZ`; repo jobs/timeutil.py `local_month_window_utc`]. Dashboards that say "last N days" use a rolling `now()` window instead.

## 4.1 Monthly revenue (gross, net) and the reconciliation waterfall

**Canonical pipeline.**
- `monthly_statement` runs on the 1st at 06:30 local. It sums `orders.price` for the previous local month where `status = 1`, counts orders, sums `payments.fee` joined to those orders, and inserts one row into `statements` (gross, fee, net = gross − fee, orders_count) [repo novamart/jobs/monthly_statement.py; repo airflow/dags/monthly_statement_dag.py].
- The job then checks fees against an "expected fee". It only logs `statement_fee_mismatch` as a warning; it never changes the row.
- Three rows exist: 2019-09, 2019-10 and 2019-11 [Q stmts_raw]. No December row exists (the 2020-01-01 run is after the data cut).
- Restatement layers, all hand-created [docs/restatement_policy.md; adhoc 47, 63, 229, 239, 241]:
  - `analytics.statement_overrides` (1 row: Oct fee 35,679.50, net 1,194,652.93, "Corrected to sum of per-order collected payment fees").
  - `analytics.statements_corrected`: view, `COALESCE(override, statement)`.
  - `analytics.chargebacks` (3 rows) and `analytics.statements_final`: view, corrected minus chargebacks by *original order month*.
  - `analytics.statement_corrections`: 1 row (2019-11, delta 0.00, "November 2019 processor fee change audit correction"), not read by any view.

**Published vs restated** [Q stmts_raw; Q stmt_ov; Q chargebacks; Q sel_statements_final]:

| Month | Published gross / net | Final gross / net (`statements_final`) | Orders |
|---|---|---|---|
| 2019-09 | 2,702.00 / 2,623.64 | same | 12 |
| 2019-10 | 1,230,332.43 / 1,194,652.79 | 1,226,764.86 / 1,191,085.36 | 3,765 |
| 2019-11 | 1,101,397.01 / 1,069,286.09 | same | 3,582 |

October's published fee was 35,679.64 (= gross × 0.029, computed before [git a92c96d] switched the job to collected per-order fees). The override sets the fee to the collected 35,679.50 (net +0.14). The three chargebacks total 3,567.57, subtracted from both gross and net for October. The `statements_final` view takes chargebacks by the order's *creation* month, not the booking month [V analytics.statements_final].

**Why none of these equals "paid orders today".** Waterfall for October 2019 (local month, 3,765 orders) [Q month_variants; Q dup_refs; Q gw_orders]:

| Step | Gross | Evidence |
|---|---|---|
| All October orders (= published statement) | 1,230,332.43 | statement row; `month_variants.all_status` |
| − 70 orders cancelled (43) or refunded (27) after publication (changed 2019-11-05 to 12-31) | −23,995.11 → 1,206,337.32 (3,695 orders) | `month_variants.status1` |
| − duplicate-callback orders (same `payment_ref`; keep the lowest order id; status 1) | ≈ −58,828.24 → 1,147,509.08 | `month_variants.status1_dedup_ref` |
| − gateway refunds on 3 Oct-31 orders, counted once | −614.53 → 1,146,894.55 | `month_variants.dedup_minus_gw_once` |

Notes:
- The statements/final view deduct **only** the 3 chargebacks. Those three orders (46, 49, 55, created 2019-10-01) are *themselves* now cancelled (46 and 55) or refunded (49) since 2019-12-10 and 12-17, so deducting them from gross and also dropping cancelled orders would double count [Q chargeback_orders_upd].
- The chargebacks were selected by SQL, not loaded from a processor feed: `INSERT ... SELECT o.id, o.price ... WHERE status = 1 AND price > 700 ... ORDER BY created_at LIMIT 3`, with `reported_at` hard-coded to 2019-12-01 [adhoc 241]. Treat them as a placeholder or test booking until finance confirms (**inference**).
- Gross sums are identical across `orders.price` and `payments.gross` for every order: no order lacks payments, and none has payments ≠ price [Q orders_vs_pay_diff; Q orders_nopay; Q pay_vs_orders_month].

**November 2019:** published = final = 1,101,397.01 gross (3,582 orders, all status 1 today). Collected fees 32,110.92. The job's own expected fee (rate before the change, +0.30 after at local midnight 11-20) is 32,120.54, a 9.62 difference (**inference**: the fee actually changed mid-day on 11-20, not at local midnight, and the flat fee is charged per payment row while the job's expectation is per order). The `statement_fee_mismatch` log shows −170.41 because the 12-01 run still used the percent-only formula [Q fee_check; Q fee_actual_by_month; Q fee_mismatch_logs; git 4a58d17].

**December 2019 (no statement yet).** Paid orders: 1,756 for gross 552,328.93 (includes the 5 released holds). Held, not counted: 12 orders, 40,213.29. By the "orders" unit, December has 1,756 orders but 1,942 line items [Q month_variants; Q lines_dec_units; Q lines_dec_lines].

**Fee notes.** Fees are collected per payments row (per line). Gateway refund rows have `fee = 0`, so fees are never returned [repo payments_webhook.py; Q pay_neg]. The statement `orders_count` is orders, not lines.

## 4.2 Daily and intraday sales reports (`report_rows`, `report_rows_intraday`)

- `daily_report` writes yesterday's (local day) units and revenue per product. It uses `order_lines` with a fallback to `orders` for orders with no lines, excludes `EXCLUDED_STATUSES [0,2,3]`, `analytics.test_users`, `EXCLUDED_SKUS [1004856, 1002544]` and `BRAND_DENYLIST ['lucente','jetem']` [repo daily_report.py; repo constants.py].
- `intraday_report` (12:00 and 17:00 local) writes append-only snapshots of "today so far" into `report_rows_intraday`. It started 2019-12-08 [git a2e0013; Q intraday_versions].
- Both tables are append-only. Consumers must pick the latest `created_at` per `report_date` (the logic in `revenue_widget` and `daily_kpis`) [Redash #2; git 3eced24].
- `report_rows`: 6,923 rows, 92 dates, exactly 1 version each [Q rr_versions; Q rr_dates].

**What distorts daily-report totals vs a clean recomputation** (days where |diff| > $0.5, ideal = current statuses not in 0,2,3, excluding test SKUs, `lucente`/`jetem`, user 424242) [Q report_vs_ideal]:
- **Rules changed over time without restating.** SKU exclusion from 10-08 [git 83fb3ed], `lucente` from 10-25 [git ba1fbfa], status exclusion [0,2,3] from 11-18 [git 11c0a42], QA-user exclusion from 11-27 [git b59f077], `jetem` from 12-15 [git 1169e40]. October days run before those dates still include the SKUs and brand (October daily diffs of −$0.1k to −$3.2k).
- **2019-10-01** report 47,897.98 vs ideal 23,801.97, because the 70 later-cancelled orders were still live that morning.
- **2019-11-03** report 35,429.68 vs ideal 38,415.67 (DST fall-back day is 25 h; the original window was start + 24 h) [git 102c9b4; adhoc 81].
- **2019-11-17** report 148,857.07 vs ideal 223,853.03. `daily_report` logged `orders_scanned: 500` (the cap) of 735 orders; fixed [git 1233af8] 11-19, never backfilled [LOG job_runs daily_report 2019-11-17; Q dr_cap].
- **2019-11-15**: no orders, no rows [Q nov15; LOG job_runs daily_report 2019-11-15 `orders_scanned: 0`].
- **2019-12-31** has no `report_rows` yet (the job reports yesterday); the intraday snapshot is used for "today".
- Units are line items, not orders, so `units` exceed order counts on multi-line days [Q rr_vs_orders_daily].
- Monthly sums of `report_rows`: Oct 1,201,082.08; Nov 966,974.33; Dec (to 12-30) 535,561.72 [Q rr_month].

## 4.3 Orders vs units vs payments (counting units)

| Term | Meaning | Where |
|---|---|---|
| order | one row in `orders` (a merged same-session purchase of 1 to 6 lines) | [Q lines_multi] |
| line / "unit" in reports and dashboards | one `order_lines` row; legacy orders (before 2019-11-22) have no lines and use the orders row | [repo daily_report.py; Redash #9] |
| payment row | one per line plus gateway refund rows | [Q pay_per_order] |

Jobs that read `orders.product_id` directly (`top_sellers`, `trending`, `reorder_forecast`, `price_suggest`, `email_digest`, `affinity_v2` conversion flag, `fraud_score`) ignore appended lines (225 lines, ~2.5% of lines). Jobs and dashboards that use `order_lines` do not.

## 4.4 Best sellers (four independent definitions)

| Definition | Window | Unit | Ranking | Status filter | Exclusions | Source |
|---|---|---|---|---|---|---|
| Dashboard "best_sellers" [Redash #9 best_sellers] | rolling 7 × 24 h from `now()` | lines | revenue DESC, top 20 | none (includes held, cancelled and refunded) | user 424242, brands `lucente`/`jetem` | [docs/dashboard_notes.md; git 92596dc; git b59f077; git 1169e40] |
| `top_sellers` job → `novamart.top_products` | yesterday local day | orders | units DESC, ties by product id, top 50 | status = 1 | none | [repo top_sellers.py; git 9a51155] |
| `trending` job → `analytics.trending_daily` | rolling 30 d (was 60 d until 2019-12-06) | orders | `units × exp(−0.05 × days since last order)`, min 5 units, top 50 | status = 1 | none | [repo trending.py; git f563dea; Q trending_window_logs] |
| `email_digest` top product | 7 d | orders | units | status = 1 | none | [repo email_digest.py] |

Observations:
- The two "test" SKUs lead the unfiltered rankings. Trending #1 on 2019-12-06 was 1004856; on 2019-12-31 the order is 1004767, 1004856, 1002544 (the two test SKUs are ranks 2 and 3). The digest's "top product" was 1002544 or 1004856 on 12-17 to 12-21 [Q trending_top; Q digest_log].
- The two SKUs account for 5.09% of status-1 orders and 3.72% of revenue (~$106.5k): 1004856 has 322 paid orders from 241 users (avg price $125.17, min $9.99), 1002544 has 138 orders from 87 users ($66k). So 1004856 is *not* only a QA product: 309 paid orders are by non-QA users. 1002544 has brand `apple`, category `electronics.smartphone`, title "Unbranded Item #2544" (blank-brand repair artefact), and there is no repo evidence why it is excluded (**open question**) [Q excl_skus_products; Q excl_skus_orders; Q test_sku_prices; Q nonqa_testsku_order_share; Q test_sku_share_orders].
- The `top_sellers` job output is tiny and tie-driven: on 2019-12-30 the top product sold 3 units [Q job_top_sellers_last].
- As of the data end, the dashboard's 7-day top 20 is led by Apple/Samsung smartphones with 6 to 20 units; revenue ranking, not units [Q dash_best_sellers_7d].

## 4.5 Brand and category revenue

- **Brand revenue (30 d)** [Redash #8 brand_revenue; Q dash_brand_30d]. Top brands at 2020-01-01: apple 236,607; samsung 128,114; xiaomi 20,819; lg 18,454; blank brand 17,585; huawei 14,086; `internal` 7,625. The blank-brand row exists because 17,442 products (21.5%) have no brand [Q blank_brand_now]. The `/reports/brands` API in `routers/reports.py` is **not mounted** (removed from `app.py` in [git f1217a8]), so it is dead code.
- **Blank brands.** `analytics.blank_brand_products` is a one-time snapshot (5,972 rows, $38.5k revenue, created ad hoc) made when [git ea0e97b] added the repair UPDATE; two causes recorded: first insert blank plus `ON CONFLICT DO NOTHING`, or first seen via a view with no catalog metadata [T analytics.blank_brand_products; adhoc 23]. It is stale; compare against `products` for current state.
- **Lucente** (676 catalogue products, 79 of them ordered; 141 orders, $43k) is excluded from reports and dashboards "per partnerships" [git ba1fbfa] but **is** in statements. **Jetem** has 5 products and **zero** orders, so the denylist entry has had no numerical effect to date [Q jetem; Q brand_lj].
- **Category revenue (30 d)** [Redash #6 category_revenue]. It maps `products.category` (a dotted code) to a `display_group` through `analytics.category_names` (valid_from = first-created date of the product's code) plus `analytics.category_name_history` (versioned override rows) [git 33054cd; git 2814b3d; adhoc 169, 181, 271, 273].
  - History rows reclassify `construction.tools.light*` → `lighting` and `electronics.audio*` → `entertainment`. They were created with `valid_from = CURRENT_DATE`.
  - In the warehouse they carry **valid_from = 2026-08-13** (the load/replay date), so for any 2019 order date the lookup `valid_from <= order date` never matches them. As materialised, `lighting` and `entertainment` never appear.
  - At 2020-01-01 the dashboard gives electronics 437,887.95 (1,098 units) and no entertainment/lighting. With a valid_from of 2019-12-12 (the intended date) it would show electronics 424,195.12, entertainment 13,692.83, lighting 2,253.51, construction 1,459.50 [T analytics.category_name_history; Q cat_hist; Q dash_category_30d; Q dash_category_30d_intended].
  - Category codes in `category_names` with duplicate code rows: none [Q cat_names_dupes]. Blank category (9,426 products) lands in `other` [Q blank_brand_now].

## 4.6 Customers: signups, actives, segments

**Signups.** There is no signup event in the system. `users` rows are inserted on the first view/cart/order with a placeholder email and hash-derived profile [repo catalog.py ensure_entities; repo onboarding.py]. `users.created_at` therefore means "first seen". Rows by month: Sep 74, Oct 15,045, Nov 11,302, Dec 12,529 [Q users_month]. Only 4,112 of 38,950 users ever ordered [Q viewer_to_user]. The fraud rule `new_account` is `order.created_at − users.created_at < 7 days`, i.e. first-seen recency [repo fraud_score.py].

**"Registered" customers.** 30 beta accounts created on 2019-12-01 by `POST /accounts` (router later unmounted [git c49a7bb]). `accounts.account_id` is a UUID with no relation to `orders.user_id` (bigint); the bridge is `account_map(uid, account_id)` or email equality [repo accounts.py; T novamart.account_map; adhoc 305 to 311]. The `registered_conversion` dashboard (fixed [git b975479]) joins accounts → users by email: 30 registered buyers, $18,155.71 (100% "conversion"; all 30 accounts belong to buyers, 63 of 74 of their orders pre-date enrollment, and the QA user 424242 is one of the 30) [Redash #4; Q dash_registered; Q acct_buyers_mix; Q acct_preenroll; Q qa_account].

**Contactable customers.** `analytics.contactable_users` = opted-in users with a syntactically valid non-`example.*`/`*.example` email [V analytics.contactable_users definition from INFORMATION_SCHEMA; git e10cb0c; adhoc 205]. It is **empty**: the only non-`example.com` addresses are `*@gmail.example`, which the view excludes [Q contactable_cnt; Q users_domain]. The `email_digest` job does not use this view: it counts `users WHERE email NOT LIKE '%@example.com'` (40 recipients every day since 12-17, which includes the QA user and the 17 opted-out users) and ignores `marketing_opt_in` [repo email_digest.py; T analytics.digest_log; Q users_gmail].

**Active customers: four different metrics** (as of the 2019-12-31 end of day) [docs/metrics_definitions.md; repo kpi_daily.py; Redash #3, #9]:

| # | Where | Definition | Value | Evidence |
|---|---|---|---|---|
| 1 | `analytics.kpi_daily.active_customers` (job `kpi_daily`, [git 14726e7]) | distinct `user_id` with a **status = 1** order in the trailing 30 × 24 h at the 06:15 local run; no test-user or brand filter | 1,152 on 12-31 (peak 2,256 on 11-19; 974 on 12-22) | [T analytics.kpi_daily; Q kpi_daily] |
| 2 | `daily_kpis` dashboard (Redash #9) | per **local day**, distinct ordering users, **no status filter**, excludes user 424242 and `lucente`/`jetem`; window = today and prior 13 days | e.g. 54 on 12-31, 65 on 12-30 | [Q dash_daily_kpis] |
| 3 | `actives_board` (Redash #3, [git 2dde4f0]) | trailing 30 d from `now()`, status NOT IN (0,2,3), minus `analytics.test_users`, minus fake/internal email patterns | **0** | [Q dash_actives_board] |
| 4 | status-agnostic reference | distinct users with any order in 30 d | 1,151 (1,146 if status = 1 only) | [Q actives_defs; Q dash_actives_board_no_domain] |

The 30-day curve in #1 falls from 1,560 (12-16) to 1,031 (12-18) in two days. That is the 11-16/11-17 order spike leaving the window, not churn [Q kpi_daily; Q spike_hours]. Monthly paid-order buyers: Oct 1,780; Nov 1,983; Dec 1,175 (first-time buyers: Oct 1,780, Nov 1,523, Dec 786) [Q monthly_buyers; Q new_vs_returning].

**Funnel** (`analytics.daily_funnel`). Sessionised from `cart_items` UNION `orders` only (product views are not included) over the trailing 24 h at run time, so `day` is the run date and `users_active` means cart or order active. The inactivity gap was 30 minutes, changed to 120 minutes [git f915c1b] on 2019-12-14, a change with almost no visible effect on the series (sessions per user ~1.1 to 1.2 both before and after) [repo funnel.py; Q daily_funnel].

## 4.7 Refunds metric

The `refunds` dashboard reads `analytics.refunds_unified`, which unions (a) orders with status 2 (kind `order_cancelled`) and 3 (kind `order_refunded`) valued at `orders.price` and timestamped `orders.updated_at`, and (b) every `payments` row with negative gross or net (kind `gateway_refund`) [V analytics.refunds_unified; git a3bffec].

Consequences [Q dash_refunds; Q gw_events; Q gw_payment_full]:
- Cancellations are reported as "refunds".
- The three Oct-31 gateway refunds (334.34, 254.71, 25.48 = 614.53) were replayed on 2019-12-13, 12-20 and 12-27, giving 9 rows and 1,843.59.
- Those orders stay status 1, so they are still in revenue.
- The view is reported by *event* month (Nov: cancelled 6,511.32 and refunded 3,180.45; Dec: cancelled 6,738.32, refunded 10,267.02, gateway 1,843.59), while statements allocate refunds to nothing.

## 4.8 Traffic, conversion and the November discontinuities

- Weekly (local weeks) views / carts / paid orders / revenue: 2019-09-29 week 30.9k views, 509 orders; peak 11-10 week 111k views, 6,722 carts, 885 orders; 11-17 week 1,314 orders ($400.6k); 11-24 week **241 orders ($78.4k)** with 56.1k views and 2,552 carts; December weeks 303 to 455 orders [Q weekly_funnel].
- **11-14 to 11-17 traffic and cart surge** (views 13.7k, 28.7k, 27.7k, 27.5k vs ~9k baseline; carts 863, 2,284, 2,008, 1,786 vs ~340) with **zero orders on 11-15** and a catch-up of 349 and 770 `order_created` events on 11-16 and 11-17, plus elevated replays (27 and 56). **Inference:** a checkout or callback outage on 11-15 with delayed delivery. The order timestamps are event times of callbacks, so daily revenue on these days is misallocated while monthly November revenue is unaffected [Q daily_events; Q spike_hours; Q orders_days_missing].
- **11-23 collapse:** cart-to-order (same user and product within 24 h) 33% before 11-22 vs 19% after; orders fall across all signup channels (−69% to −82% in a 14-day before/after comparison whose baseline includes the 11-16/17 catch-up spike), every category, and every price band [Q drop_cart_conv_prod; Q drop_by_channel; Q drop_by_cat; Q drop_by_price]. No code change or log event explains it in the data I have. A candidate to check first is the 11-22 order-merge deploy [git 5d1300d], and the 11-20 fee change [git 12e1c68] is the other nearby deploy. Do not state a cause externally without checking with the owners (Maya Iyer for orders).
- Weekly vendor price feed (`acme_feed_v2`, 200 items each Monday, 13 times) raises every feed product's list price ~4.0% per week (avg ratio 1.0400 each week) [LOG app_events price_feed_received; Q price_change_effect; Q feed_products]. 241 feed products, 53 of which were ordered (542 paid orders, $299k) [Q feed_vs_orders].

## 4.9 Time-bomb and trust summary for dashboards (detail in Appendix B)

Redash holds 9 queries and 9 dashboards (one table widget each), all created 2026-10-05 as "migrated from dashboards/*.sql", with no schedule and no cached result (`latest_query_data_id` null; `GET /api/queries/5/results.json` returns 404 "No cached result found") [redash/queries.json; Redash #1..#9]. Every windowed query is anchored on `now()`, and the Redash data source is Postgres `estate-pg`. **Inference:** when someone refreshes them today (real clock 2026), the 7-day, 14-day and 30-day windows contain none of the 2019 data, so those tables come back empty (or the single aggregate returns NULL/0). I did not execute them (read-only rule). All "as-of" values in this document recompute the same SQL against the warehouse with the anchor **2020-01-01 00:00 UTC**.

---

# 5. System

## 5.1 Architecture at a glance

```
payment gateway callbacks, storefront events
        |
 FastAPI app (novamart/app.py; uvicorn --workers 4)
   mounted: /products/{id} (view), /catalog/prices, /cart, /cart/remove,
            /orders, /orders/{id}/cancel, /orders/{id}/refund,
            /products/{id}/similar, /payments/gateway_refund, /health
   NOT mounted (dead code): /accounts, /users/{id}/email, /reports/brands
        |  writes
 Postgres (public.* + analytics.*): users, products, cart_items, orders, order_lines,
        payments, report_rows, report_rows_intraday, statements, top_products, accounts,
        account_map; analytics.* job outputs
        |  nightly batch jobs (cron -> Airflow DAGs)           logs: app.jsonl, db_queries.log, jobs.jsonl
        v
 Redash (queries on Postgres)                BigQuery warehouse (one-shot backfill 2020-01-05)
```

Evidence: [repo novamart/app.py; git f1217a8, c49a7bb (router removals); repo novamart/logutil.py; docs/data-access.md; git 5ae1182].

- The accounts router was mounted only 2019-11-27 to 12-05, yet 30 accounts exist because creation happened 2019-12-01 [LOG app_events account_created; git b567d9d, c49a7bb]. The `/users/{id}/email` endpoint was live only 2019-10-16 to 10-26 and produced the 40 `gmail.example` emails on 2019-10-23 [git 088a372, f1217a8; LOG app_events user_email_updated].
- Every statement is written to `db_queries.log` as `<ts> [app|job] statement: ... -- params: ...` [repo db.py; repo logutil.py]. Ad-hoc engineer SQL shows up with sources `engineer:<name>` and `engineer-backfill:<name>` (191 lines) [Q dbq_src; adhoc].
- **Schema drift.** `schema.sql` defines only 8 base tables. `order_lines`, `payments.payment_ref`, `accounts`, `account_map` are created lazily inside request handlers; `analytics.price_history`, `chargebacks`, `statement_overrides`, `statement_corrections`, `category_names`, `category_name_history`, `blank_brand_products`, all four views, and the `analytics` tables for several jobs are created by jobs or by hand, not in `schema.sql`. CI (`ci/run_ci.py`) loads `schema.sql`, truncates 7 tables, exercises view → cart → order, and runs `reconcile`, `daily_report`, `monthly_statement` only [repo schema.sql; repo ci/run_ci.py; repo orders.py CREATE TABLE IF NOT EXISTS (executed on every order request: 7,116 times) ; Q stmt_templates].
- **`FAKE_NOW` env var.** `jobs/timeutil.now()` returns a fake time when `FAKE_NOW` is set ("only set in test rigs") [repo jobs/timeutil.py]. If it leaks into a scheduler environment every job runs on the wrong date. Job log timestamps in this estate land on whole hours and quarter hours, consistent with replay.

## 5.2 Scheduled batch jobs

Schedules: `crontab.txt` is retired (Jan 2020); live schedules are the Airflow DAGs, each a single `BashOperator` running `python -m novamart.jobs.<module>`, **with no inter-DAG dependencies, no retries, no alerts** and `catchup=False` [repo airflow/dags/*.py; repo crontab.txt]. Crontab comments say times are *local*; the DAG cron strings carry no timezone. Airflow's default timezone is not set in the repo, so unless the deployment configures America/New_York, runs shift 4 to 5 hours earlier relative to local days (**inference**, unverified; log timestamps are in UTC with 06:00 local daily_report at 10:00 or 11:00 UTC, consistent with EDT/EST).

| Job (schedule local; Airflow cron) | Reads | Writes | First seen / runs | Fails → what breaks / notes |
|---|---|---|---|---|
| `reconcile` 03:00 (`0 3 * * *`) | `orders` | logs `duplicate_payment_ref` (WARNING) | 2019-09-16 / 107 | Nothing downstream; it never fixes data (130 refs flagged nightly). `status <> 5` filter is stale. |
| `affinity` 03:30 | `cart_items` | `analytics.product_affinity` (full DELETE + insert), also creates `analytics.rec_decision_log` | 2019-10-13 / 80 | **Widget no longer reads it** (since 2019-12-06) but it is the only DDL for `rec_decision_log`. Do not drop without moving that DDL. [Q reads_affinity_v1; Q stmt_templates] |
| `affinity_v2` 03:45 | `cart_items`, `orders`, `products` | `analytics.product_affinity_v2` (stamped `model_version 2.0.1`) | 2019-12-06 / 26 (crashed 12-03..05) | If it fails the table is stale; since [git 8ed2971] the widget reads only rows at the table's `MAX(updated_at)`. Feeds `model_train`. |
| `model_train` 04:15 | `rec_decision_log` (arm = random), `orders`, `products`, `users`, `affinity_v2` | `analytics.model_scores`, `analytics.model_registry` | 2019-12-15 / 17 | Not served (flag). See 7. |
| `price_suggest` 04:45 | `products`, `orders` | `analytics.price_suggestions` | 2019-11-25 / 37 | Shadow only; nothing reads it. |
| `trending` 05:15 | `orders` (status 1) | `analytics.trending_daily` (top 50 per `day`) | 2019-11-03 / 59 | **Widget fallback depends on it** (`SELECT MAX(day)` then top 5). If it fails the fallback serves yesterday's list; if the table is empty the widget returns no items. |
| `fraud_score` 05:45 | `orders`, `users` | `analytics.order_risk`; **updates `orders.status` to 6** | 2019-12-04 / 28 | Mutating job. Held orders vanish from statements and the status-1 jobs. |
| `daily_report` 06:00 | `orders`, `order_lines`, `products`, `test_users` | `report_rows` | 2019-09-16 / 107 | Missing days leave gaps (e.g. 11-15 had zero orders). Dashboards `daily_kpis`, `revenue_widget` read it. |
| `kpi_daily` 06:15 | `orders` | `analytics.kpi_daily` | 2019-11-17 / 45 | Series gap if it fails; not restated. |
| `funnel` 06:20 | `cart_items`, `orders` | `analytics.daily_funnel` | 2019-11-09 / 53 | |
| `monthly_statement` 06:30 on day 1 (`30 6 1 * *`) | `orders`, `payments` | `statements` (append-only) | 2019-10-01 / 3 | If it fails or is re-run, a duplicate or missing month row; the append-only table will have two versions and `statements_corrected` joins on `month`, so it would double-count (**inference**). |
| `top_sellers` 06:45 | `orders` | `top_products` | 2019-11-07 / 55 | |
| `reorder_forecast` 06:50 | `orders` | `analytics.reorder_hints` (full replace, top 200) | 2019-11-27 / 35 | Advisory only. |
| `email_digest` 07:15 | `orders`, `users` | `analytics.digest_log` | 2019-12-17 / 15 | Gated by `ENABLE_DIGEST`; sends nothing real (just logs). |
| `intraday_report` 12:00 and 17:00 | like `daily_report` | `report_rows_intraday` | 2019-12-08 / 47 runs, 24 days | |
| `warehouse_backfill` (manual, `schedule=None`) | all tables via `gcloud sql export csv` | BigQuery `bq load --replace` per table | one-shot 2020-01 | Full replace; no incremental refresh exists; warehouse = snapshot. [repo warehouse_backfill.py; repo warehouse_backfill_dag.py] |

Run counts: [Q job_gaps; Q job_list]. All jobs ran once daily without gaps except the documented crashes. Only `affinity_v2` has crash records (`service: ops`, `job` is the module path, not the job name, so a naive `job = 'affinity_v2'` filter misses them) [LOG job_runs job_crashed ×3; Q job_crashed].

**Ordering hazards.** The logical chain is `fraud_score` (05:45, sets status 6) → `daily_report`/`kpi_daily`/`top_sellers` (06:00 to 06:45), and `trending` (05:15) before the fraud job. So `trending` counts orders that `daily_report` (which does not exclude status 6) later sees differently. Nothing in Airflow expresses these dependencies.

**Safe-change checklist for batch pipelines**
1. Use `jobs.timeutil.now()` and `local_day_window_utc`/`local_month_window_utc`; never `start + 24 h` (the DST bug, [git 102c9b4]).
2. If you add a table, add its DDL to the repo and to `warehouse_manifest.json`, otherwise the backfill misses it (the manifest's 32 tables = 12 `public` + 20 `analytics`; views are not in it) [repo warehouse_manifest.json].
3. Any change to exclusion rules (SKUs, brands, statuses, test users) will not restate old snapshots. Decide up front whether to backfill and document it.
4. Do not change `orders.status` semantics without updating `EXCLUDED_STATUSES`, the statement filter (`status = 1`), `refunds_unified`, and `fraud_score`.
5. Remember jobs that delete-and-reinsert (`affinity*`, `reorder_hints`, `price_suggestions`, `model_scores`) are not transactional (`autocommit=True`): the widget can read an empty table mid-run (**inference**; mitigated since [git 8ed2971] by reading only the max `updated_at`, which an empty table does not satisfy).
6. Counts of line items vs orders must be chosen deliberately (4.3).

## 5.3 Recommendation / similar-products widget

`GET /products/{pid}/similar?uid&ts&session` [repo routers/similar.py]:
1. Version = `REC_MODEL_VERSION` from `deploy/flags.env` (default 2.0.0; aliases 2, v2, 4, v4, model4). It is "read at deploy time", but the file is read per request in code.
2. **Random arm** if `sha256(uid)[:8] % 20 == 0` (~5% of users). Items are a seeded shuffle of the first 500 product ids excluding the test SKUs; `arm='random'`, `rec_source='random_arm'` [Q rand_items; Q prod_500].
3. Otherwise read the score table (`product_affinity_v2` for 2.0.0, `model_scores` otherwise) where `score >= 0` and `updated_at = MAX(updated_at)`, top K = 5 excluding `EXCLUDED_SKUS`, with an in-process cache (TTL 6 h per table and product, invalidated when `MAX(updated_at)` changes since [git 8ed2971]).
4. If empty, fall back to `analytics.trending_daily` top 5 for the latest `day` (no SKU exclusion) and mark `effective_version='fallback'`.
5. Log every decision to `analytics.rec_decision_log` and an `rec_served` app event.

Version history: [git f1217a8] v1.0.0 co-cart affinity with 7-day bestseller fallback → [git df4ed85] 2019-12-06 version dispatch, random arm, trending fallback → [git a00f24c] cache → [git 8ed2971] cache invalidation. Version enum `1.0.0 / 2.0.0 / 4.0.0`; `docs/rec_versions.md` says only "TBD" [repo similar.py REC_VERSIONS; repo docs/rec_versions.md; git 4396fbb].

Naming traps:
- `rec_source = 'model'` is the heuristic `affinity_v2` (version 2.0.0), **not** a learned model.
- `affinity_v2` rows carry `model_version = '2.0.1'` while serving calls it `2.0.0`. The table is `analytics.product_affinity_v2`, but the doc and flag say 2.0.0 [docs/affinity_lineage.md; T analytics.product_affinity_v2].
- `intended_version` vs `effective_version`: the latter becomes `'fallback'` when the primary path returned nothing.
- Between 2019-12-19 and 12-26, `fallback_reason = 'cache'` rows (25,091) are empty-result cache hits: the cache stored empty lists until the `if items:` guard [git 8ed2971] [Q rec_groups; Q rec_daily].

**Coverage and fallback.** Of 81,017 products viewed, only 449 have any non-sentinel v2 recommendation (948 pairs, `score >= 0`); 2,964 of 3,912 `affinity_v2` pairs (76%) hold the −1 sentinel. Decision rows: 667,850; fallback is 83.1% of v1-era non-random exposures (326,186 / 392,630) and 79.8% since 2019-12-06 (207,959 / 260,654) [Q aff2_sum; Q model_scores_sum; Q prod_views; Q rec_groups].

**The `-1` sentinel.** `affinity` and `affinity_v2` store `score = -1` for pairs seen fewer than 3 times; "NOT a negative preference. Serving must filter < 0" [repo affinity.py docstring; git fef5c96]. Any new consumer must filter `score >= 0`.

## 5.4 Other analytics systems

- **Reorder hints** (`analytics.reorder_hints`): `hint_units = int(15.6 + 162.4 / (velocity + 1.8))`, velocity = paid orders in 14 days / 14, top 200 products. **Lower velocity gives a larger hint** (mechanical inverse). The December refit changed only K from 141.12 to 162.4 [git f85cdd2; docs/forecast_caveats.md; Q reorder_top]. It includes the test SKUs (1004856 gets 62, 1002544 gets 67). Labelled advisory in code and README. Current snapshot: velocity 0.0714 to 2.7143, hints 51 to 102 [Q reorder_stats].
- **Price suggestions** (`analytics.price_suggestions`): top 500 products by 14-day paid orders, ±5% nudge: `+5%` if units > median of the sorted list else `−5%`. 109 up and 386 down (ties and the median rule skew down). Shadow only, phase 2 on hold since 2019-12-02 [git cca9b0d; repo price_suggest.py; docs/pricing_status.md; Q price_sugg_stats; Q stmt_templates (no reads)].
- **Fraud scoring**: 4.x above. 1,631 risk rows, 28 nights. The first run (2019-12-04) held 8 orders created on 12-03: seven at exactly $2,999.99 (two of them from the same user) and one at $5,999.98, all with score 1.0. Scores above 0.85: 12 orders now [Q risk_dist; Q held_orders].
- **Email digest**: top product of the week plus a recipient count. It has been enabled by `ENABLE_DIGEST=1` in `deploy/cron.env` since 2019-11-28 [git c19a307] but the first digest ran 2019-12-17: the job read env var `DIGEST_ON` [git c19a307], then `ENABLE_DIGEST` from the process env only [git 8dc520b], then the file directly [git 0bd4eac] [T analytics.digest_log].

## 5.5 Warehouse and dashboards plumbing

- Postgres `public.*` → BigQuery dataset `novamart` (12 tables); `analytics.*` → `novamart_analytics` (20 tables); the four views were created in Postgres by ad-hoc `engineer-backfill` statements and re-created in BigQuery (definitions retrievable via `INFORMATION_SCHEMA.VIEWS`) [repo warehouse_backfill.py; docs/data-access.md; adhoc 47, 205, 229, 239, 325; `queries/views_infoschema.out`].
- The backfill casts timestamps to UTC strings and uses the sentinel `__PGNULL__` for NULLs so blank text stays blank. All columns are typed from `warehouse_manifest.json`; `numeric` becomes BQ NUMERIC (9 decimals displayed) [repo warehouse_backfill.py].
- **Redash** queries are Postgres SQL against the `public` and `analytics` schemas on `estate-pg` [Redash data_sources/1]. The BigQuery copies are the same tables with different dataset names (`public.orders` → `novamart.orders`, `analytics.x` → `novamart_analytics.x`), so BigQuery re-runs need dataset renames and `now()`/interval syntax changes.
- Redash dashboard id and slug are crossed for two dashboards: dashboard 7 "best_sellers" shows query 9, dashboard 9 "daily_kpis" shows query 7. Query 7 is `daily_kpis` and query 9 is `best_sellers` (the names match; the ids are swapped) [redash/dash_7.json; redash/dash_9.json].

---

# 6. Data

## 6.1 Warehouse inventory (rows from the snapshot; ranges in UTC)

**Dataset `novamart` (Postgres `public`)**

| Table | Rows | Grain / key | Range / freshness | Notes |
|---|---|---|---|---|
| `orders` | 9,127 | one per order (`id`) | 2019-09-25 to 2019-12-31 16:51 | no session column; `product_id` = first line; 8,972 distinct refs [Q orders_misc] |
| `order_lines` | 2,284 | one per line (`payment_ref` unique) | 2019-11-22 15:18 to 2019-12-31 | only orders from 2019-11-22 have lines (2,050 of 2,050 after 21:00 UTC; 9 before) [Q lines_cov] |
| `payments` | 9,361 | one per line plus refund rows | to 2019-12-31 | 9 negative rows; `payment_ref` is null on all Sept/Oct payments, on 3,291 of 3,614 Nov payments (those before 2019-11-22) and on the 9 refund rows [Q pay_summary] |
| `products` | 81,018 | `id` | to 2019-12-31 | titles, vendors, cost and stock hash-synthesized; weekly price feed updates `list_price` |
| `users` | 38,950 | `id` | to 2019-12-31 | placeholders; 40 `gmail.example` |
| `cart_items` | 36,938 | event | to 2019-12-31 23:12 | `session` is the join key for co-cart pairs |
| `report_rows` / `report_rows_intraday` | 6,923 / 2,358 | per date × product × snapshot | 2019-09-26 / 2019-12-08 onward | latest `created_at` per date is the final |
| `statements` | 3 | per month snapshot | 10-01, 11-01, 12-01 | the "published" table |
| `top_products` | 2,396 | per report_date × rank | 2019-11-07 onward | |
| `accounts` / `account_map` | 30 / 30 | | 2019-12-01 | |

**Dataset `novamart_analytics`** (`analytics.*`): `kpi_daily` 45, `daily_funnel` 53, `trending_daily` 2,898 (59 days × ≤ 50), `order_risk` 1,631, `rec_decision_log` 667,850, `product_affinity` 3,912, `product_affinity_v2` 3,912, `model_scores` 948, `model_registry` 17, `price_suggestions` 500, `price_history` 1,400, `reorder_hints` 200, `digest_log` 15, `chargebacks` 3, `statement_overrides` 1, `statement_corrections` 1, `test_users` 1, `category_names` 135, `category_name_history` 6, `blank_brand_products` 5,972; views `contactable_users`, `refunds_unified`, `statements_corrected`, `statements_final` [bq ls; notes/schema_analytics_*.json; notes/freshness.txt].

The tables with delete-and-replace semantics (`product_affinity*`, `model_scores`, `reorder_hints`, `price_suggestions`) only hold the latest night (2019-12-31). Append-only history tables are `report_rows*`, `kpi_daily`, `daily_funnel`, `trending_daily`, `order_risk`, `top_products`, `statements`, `rec_decision_log`, `model_registry`, `digest_log` [Q fresh_*; Q aff1_sum; Q aff2_sum].

**Dataset `novamart_logs`**
- `app_events` (1,570,017): JSON in `jsonPayload` (`event`, `ts`, `user_id`, `product_id`, `session`, ...). Event counts: `product_viewed` 843,085; `rec_served` 669,190; `cart_item_added` 36,925; `duplicate_payment_ref` 10,766; `order_created` 9,127; `order_callback_replayed` 522; `order_appended` 225; `order_cancelled` 54; `user_email_updated` 40; `account_created` 30; `order_refunded` 28; `price_feed_received` 13; `gateway_refund` 9; `statement_fee_mismatch` 3 [Q app_event_types].
- `db_queries` (3,597,650): `textPayload` is the raw statement-log line; sources `app` (3,266,348), `job` (331,111), and `engineer:*` / `engineer-backfill:*` (191).
- `job_runs` (978): `jsonPayload` job events (`job_started`, `job_finished`, `*_refresh`, ...).
- The row-level `timestamp` column is the event time for these exports, but some other timestamp columns display as out of range in the CLI; use `JSON_VALUE(jsonPayload,'$.ts')` for the business time.
- `db_queries_normalized` is a view over `db_queries`; scanning it is very slow on the emulator (my query timed out), avoid it.

## 6.2 Data quality and gotchas (all verified)

1. **Duplicate callback orders**: 130 refs, 285 orders (155 more than one per ref); all before 2019-10-15 [Q dup_refs; Q dup_refs_status].
2. **Statuses mutate after publication**; every status-2 and status-3 order was created 2019-09-25 to 10-01 [Q cancel_updated; Q orders_status].
3. **Released holds carry a replay-date `updated_at`** (2026-08-13) on 5 orders, the only rows with an `updated_at` after the data window: a signature of the 2019-12-29 manual UPDATE [Q upd_after_2020; adhoc 343]. The same 2026-08-13 date appears on `category_name_history.valid_from` and `blank_brand_products.captured_at`. In any analysis, 2026-08-13 means "replay date", not business time.
4. **Zero-order day** 2019-11-15, and a 2-day catch-up spike (4.8).
5. **Time zones**: all stored timestamps are UTC; finance months and report days are America/New_York local. Statement month windows (EDT/EST) differ from UTC months by 4 to 5 hours (some Sep/Oct and Oct/Nov orders sit on the boundary; e.g. one "September" duplicate-ref order) [Q dup_refs_month].
6. **Order price ≠ list price**; `products.list_price` changes weekly by the feed; `price_history` starts only 2019-11-18 [Q order_price_vs_list; Q price_hist].
7. **Synthetic dimensions** (users, product titles/vendors/cost/stock): do not analyse by them [repo onboarding.py].
8. **Blank brand and category**: 17,442 products have blank brand and 9,426 blank category (a first-insert-wins bug; the repair `UPDATE` runs on every view, 609,853 times) [Q blank_brand_now; Q stmt_templates].
9. **NUMERIC display**: values come back with 9 decimals and `0E-9` for zero; fees are rounded per row.
10. **Reorder-hint and price tables hold one snapshot**; there is no history to audit past hints.

## 6.3 Lineage of the headline numbers

- `statements` ← `orders` (status 1) + `payments.fee`, window = local month. `statements_corrected` ← `statements` + `statement_overrides`. `statements_final` ← `statements_corrected` − `chargebacks` (joined to `orders` for month) [V definitions].
- `report_rows` ← `orders` ⋈ `order_lines` ⋈ `products` minus `test_users`, SKUs, brands, statuses `[0,2,3]` [repo daily_report.py].
- `kpi_daily` ← `orders` status 1 trailing 30 d. `trending_daily` ← `orders` status 1 30 d. `top_products` ← `orders` yesterday status 1.
- `product_affinity(_v2)` ← `cart_items` self-join on `session` (30-day window, `MIN_PAIRS = 3`); v2 also ← `orders` (conversion) and `products` (category match ×1.15, price ratio outside [0.25, 4.0] ×0.7, monthly season factor).
- `model_scores` ← `product_affinity_v2` × (1 + 0.1·w); `model_registry` ← logistic fit on `rec_decision_log` (arm = random) ⋈ `orders`, `users`, `products`.
- `rec_decision_log` ← widget on every request (app writes, not a job).

---

# 7. Experimentation

There is no experimentation platform: no assignment table, no exposure/outcome schema other than `analytics.rec_decision_log`, and no holdout. The pieces that act like experiments:

## 7.1 Random-arm data collection (since 2019-12-06)

- Assignment: `sha256(uid)[:8] % 20 == 0` ⇒ ~5% of users by id; observed 4.56% of active users (942 users, 14,566 exposures) [Q random_arm_share; Q rand_users].
- Treatment: 5 items from a seeded shuffle of the 500 lowest product ids (excluding the two SKUs). **Not uniform over the catalogue** (81,018 products; the 500th lowest id is 1,004,386; 552 distinct ids served over time) [Q rand_items; Q prod_500; repo similar.py].
- Outcome in the model's training label: "did the user place **any** status-1 order after the exposure time". It is not tied to the items shown. Overall label rate is 0.1328 [Q rand_label_rate; repo model_train.py].
- **Logging gap**: [git 30e8907] (2019-12-17 16:50) dropped the decision-log insert on the random path; [git a00f24c] (12-19 14:55) restored it. Logged random rows: 549 on 12-17 (vs 658 served), 0 on 12-18 (vs 848), 407 on 12-19 (vs 822), so ~1,370 exposures are missing from training data [Q rec_daily; Q rec_served_daily].

## 7.2 Model versions and how they evolved

| Version | Mechanism | Served? | Evidence |
|---|---|---|---|
| 1.0.0 | co-cart pairs `score = pairs × exp(−0.05·age)`, ≥ 3 pairs, 7-day bestseller fallback | 2019-10-26 to 12-06 (392,630 non-random decisions) | [git f1217a8; git 776d674; git fef5c96; Q rec_groups] |
| 2.0.0 (table `product_affinity_v2`, stamped 2.0.1) | `(1·pairs + 3·converted pairs) × decay × 1.15 same-category × 0.7 price-jump × monthly season factor`; trending fallback | 2019-12-06 onward | [git 89666bf; git 3dbe4d7; git df4ed85] |
| 4.0.0 | logistic fit on random-arm data; `model_scores = v2 score × (1 + 0.1 × coef[0])` | **never** | [git a1946ff; repo flags.env; Q rec_groups] |

Notes on 2.0.0: the monthly `SEASONAL_FACTORS` list stops at November; December falls back to 1.0 [git 3dbe4d7]. A single global factor multiplies every score, so it cannot change rankings within a night.

## 7.3 Does the ML actually work? (my assessment, evidence-backed)

**Affinity v1/v2 ("model" source): modest, real lift, tiny coverage.** Within 24 h of an exposure, the user ordered one of the recommended items in:

| Source | Exposures | Order of rec'd item | Cart add of rec'd item |
|---|---|---|---|
| v1 affinity (pre 12-06) | 66,444 | 596 (0.90%) | 1,377 (2.07%) |
| v1 fallback | 326,186 | 958 (0.29%) | 2,878 (0.88%) |
| v2 model (12-06 to 12-31) | 52,688 | 389 (0.74%) | 1,871 (3.55%) |
| v2 fallback (trending) | 207,865 | 282 (0.14%) | 1,224 (0.59%) |
| random arm | 14,566 | 0 | 18 (0.12%) |

[Q rec_hit; Q rec_hit_v1]. Caveats (**inference**): these are observational hit rates with selection effects (affinity items are only shown on products with co-cart history, i.e. higher-intent pages); the random arm's items are from the 500 lowest ids, which are rarely purchased. But the ordering "model > fallback > random" holds, and v2 is better than v1 on cart adds. Coverage is the problem: ~80% of non-random traffic is fallback and every fallback list carries a QA/test SKU [Q excl_in_fallback].

**v4 "learned model": not a working system.**
- It is not served (flag 2.0.0) and has no online evaluation [repo flags.env; Q rec_groups].
- Its only downstream effect is the scalar `0.9755` (= 1 + 0.1 × w, w = coefficient of `n_items`), multiplying every v2 score: ratio min = max = 0.9755/0.9756 over 948 pairs, so rank order equals v2's [Q model_vs_v2_rank].
- Feature `n_items` is constant 5 in all 14,566 training rows, so its coefficient is not identifiable [Q rand_nitems].
- The README lists nine features (`stock`, `marketing opt-in`, `region affinity`, `device mix`, `signup channel`...); the code uses five: `n_items`, base price, base popularity (all-time paid orders, including **future** orders: leakage), account age, `organic` flag. `opt_in` and `base_stock` are fetched and unused [repo model_train.py; README Rec model v4].
- The label is "any later order by this user", mostly measuring user intent and right-censoring (4% positive rate for users under 1 day old, 32% for 7 to 30 days; late-December rows have less time to convert), not recommendation quality [Q v4_feature_signal; Q rand_label_rate].
- Training data is 14,411 rows from only 942 users (pseudo-replication), with unstable fits: the account-age coefficient goes 1.59 → 0.85 → ... → −0.75 over 17 nights, and three of the five coefficients flip sign on 2019-12-31 [Q model_registry; Q model_train_users].

**Shadow and heuristic systems.** Price suggestions are shadow (unconsumed). Reorder hints invert velocity and include test SKUs. Fraud scoring is a deterministic price-driven rule that holds high-priced orders (e.g. any order ≥ $2,550 without boosts) rather than a model. Treat none as validated.

## 7.4 Feature flags and gradual rollout

- `deploy/flags.env`: `REC_MODEL_VERSION=2.0.0` (flip and redeploy, per the file header). `deploy/cron.env`: `ENABLE_DIGEST=1`. `FRAUD_HOLD_THRESHOLD` is a code constant (three changes in 26 days) [repo deploy/*; repo constants.py].
- There is no kill switch for the random arm or the cache.

## 7.5 How to run a trustworthy experiment here (recommendations)

1. Assign by hash (as the random arm does) but sample **over the whole catalogue**, or over the same candidate set the model scores.
2. Log exposure and outcome for the same item (item-level label), include a control arm and a pre-registered window; do not use "any later order".
3. Fix the fallback first: apply `EXCLUDED_SKUS` (or drop the SKU concept) and compare recommendations on products that actually have scores.
4. Make sure the decision logging cannot regress (add a CI check that every returned path inserts a row; the `similar` tidy-up silently lost the random-arm insert [git 30e8907]).

---

# 8. Glossary

| Term | Meaning (evidence) |
|---|---|
| **active customer** | not one metric: see 4.6 (kpi_daily, daily_kpis, actives_board, any-status) |
| **actives_board** | Redash #3 board query; returns 0 because of its email filter [Q dash_actives_board] |
| **advisory** | label on `reorder_hints`: directional only, not for finance [repo reorder_forecast.py] |
| **affinity** | co-cart pair score; v1 = `product_affinity`, v2 = `product_affinity_v2` |
| **app / job / engineer / engineer-backfill** | sources in `db_queries`: the API, batch jobs, manual SQL, manual DDL/DML scripts [Q dbq_src] |
| **arm** | `rec_decision_log.arm`: `none` or `random` |
| **board deck** | the number that goes to the board; Nov deck used the as-published October net 1,194,652.79 [docs/restatement_policy.md] |
| **BRAND_DENYLIST** | `['lucente','jetem']`, hidden from daily/intraday reports and dashboards [repo constants.py] |
| **chargeback** | a deduction booked in `analytics.chargebacks` and subtracted in `statements_final` |
| **contactable users** | `analytics.contactable_users`; opted-in with non-example email; empty |
| **EXCLUDED_SKUS** | `[1004856, 1002544]`, hidden from daily/intraday reports only |
| **EXCLUDED_STATUSES** | `[0,2,3]` for the daily report (does not exclude 6 = held) |
| **fallback** | widget path when the score table has nothing: trending top 5 (formerly 7-day best sellers) |
| **FAKE_NOW** | env var that overrides the job clock |
| **FEE_RATE / FEE_FLAT** | 0.029 per transaction; +0.30 per payment row from 2019-11-20 |
| **graduation gate / sentinel `-1`** | pairs with < 3 sightings are stored with `score = -1`; filter `score >= 0` |
| **held order** | status 6, set by `fraud_score` when score > threshold |
| **intended vs effective version** | requested version from the flag vs version actually served |
| **line / order_lines** | per-item rows for an order; created only since 2019-11-22 |
| **local day / month** | America/New_York calendar day or month |
| **model_scores** | v4 output table; v2 scores × constant |
| **override / correction** | `statement_overrides` replaces a published row; `statement_corrections` is an unused audit row |
| **payment_ref (`PR-<hex>-<productid>`)** | the idempotency key from the gateway callback |
| **public.* / analytics.*** | Postgres schemas; in BigQuery, `novamart` and `novamart_analytics` |
| **random arm** | 5% of users shown 5 products from the lowest-500 product ids |
| **registered customer** | one of 30 users with an `accounts` row (beta) |
| **reconcile** | nightly job that logs duplicate payment refs |
| **report_rows / intraday** | append-only daily and intraday sales snapshots |
| **restatement** | the corrected/final statements layers |
| **shadow** | job whose output nothing consumes (price_suggest) |
| **smoke user 424242** | QA account `cust424242@gmail.example`, session `qa-smoke` |
| **statements / corrected / final** | published snapshot; overrides applied; chargebacks subtracted |
| **trending** | 30-day, recency-decayed top 50 by orders |
| **units** | line items in reports and dashboards, orders in job rankings |
| **v4 / model 4.0.0** | the logistic job `model_train`; never served |
| **velocity** | paid orders in the last 14 days ÷ 14 (reorder formula) |

---

# Appendix A. Chronology of definition changes (git)

| Date | Commit | Change | Effect on numbers |
|---|---|---|---|
| 2019-10-08 | 83fb3ed | `EXCLUDED_SKUS = [1004856, 1002544]` | daily report loses those two SKUs from this date |
| 2019-10-12 | 776d674 | affinity v1 job | |
| 2019-10-15 | b676969 | order callbacks idempotent by `payment_ref` | stops new duplicate orders |
| 2019-10-18 | 030d841 | `RECONCILE_BATCH` 100 → 200 | flagged list no longer truncated |
| 2019-10-25 | ba1fbfa | denylist `lucente` | hidden from reports |
| 2019-10-28 | 8f19718 | `STATUS_CANCELLED` 4 → 2; cancel endpoint | |
| 2019-11-02 | a92c96d | monthly fee = collected per-order fees | net now = gross − collected fee |
| 2019-11-05 | 102c9b4 | local-day windows computed on local midnights | fixes DST day |
| 2019-11-12 | fef5c96 | `MIN_PAIRS = 3`, sentinel −1 | |
| 2019-11-15 | d87cb3d | refunded status 3 and endpoint | |
| 2019-11-16 | 14726e7 | `kpi_daily` 30-day active customers (status 1) | first active metric |
| 2019-11-18 | 11c0a42 | `EXCLUDED_STATUSES [0] → [0,2,3]` | report excludes cancelled/refunded |
| 2019-11-19 | 1233af8 | remove 500-row report scan cap | fixes busy-day undercount (not backfilled) |
| 2019-11-20 | 12e1c68 | fee = 2.9% + $0.30 | fees up ~$0.30 per line |
| 2019-11-22 | 5d1300d | merge same-session callbacks; `order_lines`; payment refs on payments | orders vs lines diverge |
| 2019-11-27 | b59f077 | `analytics.test_users` (424242) excluded in report/dashboards | |
| 2019-12-02 | 4a58d17 | statement expected-fee logic with flat fee; Nov correction (delta 0) | |
| 2019-12-02 | 89666bf | affinity v2 | |
| 2019-12-03 | e4656fb | fraud scoring (threshold 0.90) | status 6 appears |
| 2019-12-05 | 53f6f6c | threshold 0.70 | more holds |
| 2019-12-05 | 92596dc | daily report and dashboards use `order_lines` with fallback | units = lines |
| 2019-12-05 | c49a7bb | gateway refund webhook (negative payments) | refunds outside order status |
| 2019-12-05 | 3dbe4d7 | affinity_v2 December crash fix (version 2.0.1) | |
| 2019-12-06 | f563dea | trending window 60 → 30 | faster list churn |
| 2019-12-06 | df4ed85 | widget version dispatch; random arm; trending fallback | rec_decision_log semantics change |
| 2019-12-08 | a2e0013 | intraday report | `daily_kpis` adds today |
| 2019-12-09 | cd559d3 | chargebacks and `statements_final` | Oct final net 1,191,085.36 |
| 2019-12-11 | 2dde4f0 | `actives_board` | board actives = 0 |
| 2019-12-12 | 33054cd | versioned taxonomy mapping | lighting/entertainment (future-dated in warehouse) |
| 2019-12-14 | a1946ff | `model_train` v4 | not served |
| 2019-12-14 | f915c1b | funnel gap 30 → 120 min | |
| 2019-12-15 | 1169e40 | denylist `jetem` | no orders affected |
| 2019-12-17..19 | 30e8907, a00f24c | random-arm logging lost then restored | training-data gap |
| 2019-12-18 | adbcb7e | "hard-exclude QA account UUID" | no-op (type mismatch) |
| 2019-12-19 | 686a5d6 | `revenue_widget` | |
| 2019-12-21 | b975479 | registered conversion maps accounts to users by email | |
| 2019-12-21 | f85cdd2 | reorder `K` 141.12 → 162.4 | hints larger |
| 2019-12-23 | a3bffec | `refunds_unified` and refunds dashboard | cancellations counted as refunds |
| 2019-12-24 | 3eced24 | revenue widget stops double counting intraday snapshots | |
| 2019-12-26 | 8ed2971 | widget score cache invalidated on refresh; read latest rows only | |
| 2019-12-29 | 1cb8721 | threshold 0.85; manual release of holds under $2,600 | |
| 2020-01-03 | 41e3537 | dashboards moved to Redash | now() anchored on 2026 |
| 2020-01-04 | 4bfcbe6 | cron → Airflow | no dependencies |
| 2020-01-05 | 5ae1182 | warehouse backfill job | BigQuery snapshot |

# Appendix B. Redash catalog and trust notes

All queries are Admin-owned, created 2026-10-05, version 1, no schedule, no cache (`redash/queries.json`). The SQL is identical to `dashboards/*.sql` just before [git 41e3537] (`notes/repo/dashboard_*.sql`). Values below are recomputed in BigQuery at the anchor 2020-01-01 00:00 UTC.

| Redash | Reads | As-of value / what it really is | Do not trust when |
|---|---|---|---|
| #1 refunds | `analytics.refunds_unified` | by month: Nov 32 events 9,691.77 (6,511.32 cancelled + 3,180.45 refunded); Dec 59 events 18,848.93 [Q dash_refunds] | counted as "refunds": includes cancellations and replayed gateway refunds |
| #2 revenue_widget | `report_rows` (closed days) + `report_rows_intraday` (today) | 7-day revenue 139,598.13 (121,396.04 closed + 18,202.09 intraday) vs status-1 orders over the same local days 141,611.09 [Q widget_7d; Q orders_7d_actual] | after 2019-12-24 fix only; excludes brands/SKUs; undercounts bad days |
| #3 actives_board | `orders`, `test_users`, `users` | **0** | always (placeholder emails excluded) |
| #4 registered_conversion | `accounts` ⋈ `users` ⋈ `orders` | 30 buyers, $18,155.71 | as a conversion rate: it only counts registered buyers (all 30), includes QA |
| #5 statements_final | `analytics.statements_final` | see 4.1 | does not net post-publication cancellations or duplicates |
| #6 category_revenue | orders/lines + category mapping | electronics 437.9k, other 93.6k, appliances 30.2k, construction 3.7k, apparel 3.7k, kids 0.6k [Q dash_category_30d] | `lighting`/`entertainment` absent (future valid_from); rolling window; no status filter |
| #7 daily_kpis (dashboard "daily_kpis" = id 9) | `report_rows(_intraday)`, `orders`, `contactable_users` | 14 rows: e.g. 12-31 60 units, 18,202.09, 54 active, 0 contactable [Q dash_daily_kpis] | `orders` column is units; contactable always 0; actives have no status filter |
| #8 brand_revenue | orders/lines + products | apple 236.6k (334 units), samsung 128.1k, ..., `internal` 7.6k [Q dash_brand_30d] | UUID exclusion is a no-op; includes blank brand and `internal` |
| #9 best_sellers (dashboard id 7) | orders/lines + products | top: 1005116 $5,889.81 (6 units), 1005115 $5,325.55, 1005284 $5,096.14 ... [Q dash_best_sellers_7d] | ranked by revenue; includes held/cancelled/refunded; includes test SKUs |

# Appendix C. Doc-vs-reality contradictions

| Claim (source) | Reality | Evidence |
|---|---|---|
| README: trending uses a 60-day window | 30 days since 2019-12-06 | [docs/trending_notes.md; git f563dea; Q trending_window_logs] |
| README: "Serving is version 4.0.0" | flag = 2.0.0; no 4.0.0 decisions | [repo deploy/flags.env; Q rec_groups] |
| README v4 features include signup channel, opt-in, region affinity, device mix, stock | only 5 features, none of those | [repo model_train.py] |
| `docs/rec_versions.md`: "TBD" | empty; use 7.2 | [repo docs/rec_versions.md] |
| `crontab.txt` schedule | retired; Airflow DAGs are live | [repo crontab.txt header; git 4bfcbe6] |
| README layout lists `dashboards/` / SQL files | removed from `main` 2020-01-03 | [git 41e3537] |
| docs refer to `public.statements` | in BigQuery it is `novamart.statements` | [docs/restatement_policy.md; bq ls] |
| `docs/forecast_caveats.md`: velocity 0.0714 to 2.2857, hints 55 to 102 | snapshot of 12-28; at 12-31: 0.0714 to 2.7143, 51 to 102 | [Q reorder_stats] |
| `docs/affinity_lineage.md`: widget reads v2, v1 unused | confirmed: last v1 widget read 2019-12-06 | [Q reads_affinity_v1; Q stmt_templates] |
| `docs/pricing_status.md`: nothing reads `price_suggestions` | confirmed (no SELECT in the statement log) | [Q stmt_templates] |
| `docs/metrics_definitions.md`: board query is the "most aggressively cleaned" | it cleans away every user | [Q dash_actives_board] |
| `docs/dashboard_notes.md` | accurate for the SQL, but silent on the `now()`-anchoring problem and the dead UUID filter | [Redash #8; Redash #9] |
| `docs/restatement_policy.md` | accurate on the three layers; does not mention post-publication cancellations, duplicates or the arbitrary chargeback selection | [Q month_variants; adhoc 241] |

# Appendix D. Open questions (could not verify from the sources)

1. Why `1002544` is in `EXCLUDED_SKUS` (only `1004856` is evidently a QA product).
2. What caused the 2019-11-15 outage and the 2019-11-23 order collapse.
3. The real source of the three chargebacks (script-selected orders; see 4.1).
4. Whether Airflow runs in UTC or America/New_York (the DAG files do not say).
5. What Redash returns today against `estate-pg` (not executed; `now()` is 2026).
6. Who consumes `analytics.model_scores` / `reorder_hints` / `price_suggestions` outside the repo (no reader found in the repo or the statement log).
7. Whether `public.statements` rows were ever manually edited besides the override layer (the audit queries in the log are read-only apart from the overrides and corrections inserts) [adhoc 47..71, 187..203].

# Appendix E. Reproduction and evidence index

Everything lives in this directory.
- `novamart_tribal_knowledge.md`: this file.
- `queries/*.sql` / `*.out`: every warehouse query and its output (about 200).
- `q.sh`: the read-only runner (uses `bq query` against the emulator).
- `notes/engineer_adhoc_queries.txt`: the 191 manual SQL statements from `db_queries`.
- `notes/repo/`: git history and the deleted dashboard SQL.
- `notes/schema_*.json` and `notes/freshness.txt`: schemas and freshness.
- `redash/`: dashboards and queries as served by the Redash API (GET only).
- `notes/start.txt`: start time and UUID.

Run end time (wall clock): 2026-10-05 19:21 UTC (started 18:51:29 UTC).
