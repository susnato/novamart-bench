# Novamart Tribal Knowledge

- **Run started (wall clock):** Thu Aug 27 17:11:23 IST 2026
- **Run UUID:** `121A8C29-8416-482F-A974-D76B2D7F4CCC`
- **Sources used (only):** the repo at `<workspace>/novamart` pinned at commit `2ae79e2`; BigQuery project `<warehouse-project>` (datasets `novamart`, `novamart_analytics`, `novamart_logs`); Redash at `<redash-url>` (9 dashboards/queries, read-only). All intermediate query outputs are stored alongside this file (see Appendix E).

---

## 1. Summary

Novamart is a small e-commerce marketplace backend (FastAPI + Postgres; repo `README.md`) whose entire recorded life spans **2019-09-15 (`2da4141`, "initial import") to 2019-12-31**, after which the data platform was migrated (Jan 2020) to BigQuery + Redash + Airflow (`1179287`, `57ea43a`, `43e54a1`, `2ae79e2`). Two engineers (Maya Iyer, Dev Kapoor per `git log`) built everything.

The ten most load-bearing facts a tenured person would know:

1. **Money is defined three ways, on purpose.** Monthly finance numbers live in three layers: `novamart.statements` (as-published, append-only), `novamart_analytics.statements_corrected` (fee override applied), and `novamart_analytics.statements_final` (chargebacks subtracted). For October 2019 net revenue those are **1,194,652.79 → 1,194,652.93 → 1,191,085.36** (verified by querying all three; policy in `docs/restatement_policy.md`, commit `a576d0d`).
2. **No two revenue surfaces are meant to tie.** Statements have *no* exclusions (QA orders, test SKUs, and the hidden `lucente` brand all count); the daily report (`report_rows`) excludes QA users, 2 SKUs, 2 brands, and statuses 0/2/3; dashboards exclude QA/brands but have **no status filter** (`novamart/jobs/monthly_statement.py`, `novamart/jobs/daily_report.py`, Redash query 2 `best_sellers`).
3. **You cannot reproduce a published statement from today's `orders` table** — statuses mutate after publication. October's statement says 3,765 orders / 1,230,332.43 gross, but re-running the same window today gives 3,695 / ~1,206,337 because 82 old orders were later cancelled/refunded (BQ: orders status distribution vs `statements`).
4. **`orders` rows stopped meaning "one item" on 2019-11-22.** Commit `5d1300d` merges same-session gateway callbacks into one order row with summed `price`; items now live in `order_lines` (first seen in prod logs 2019-11-22 15:00, `novamart_logs.db_queries_normalized`). Every item-level query needs the `order_lines` + legacy-fallback CTE pattern (`92596dc`).
5. **The board's "active customers" dashboard returns 0.** Redash query 1 (`actives_board`) excludes `example.com`-style emails, but *every* auto-created user has a `user{uid}@example.com` placeholder (`novamart/routers/catalog.py::_user_row`). Verified in BQ: 1,155 candidates → **0 after email filters**, while `kpi_daily` says 1,150 for the same day.
6. **`contactable_customers` on the daily KPI dashboard is always 0** — the `analytics.contactable_users` view (0 rows in BQ) requires a non-placeholder email, and even the 40 users who updated emails got `@gmail.example`, which the view's `%.example` filter also rejects.
7. **The Nov 16–17 flash sale is permanently under-reported in `report_rows`.** The daily report used `fetchmany(REPORT_SCAN_CAP=500)`; Nov 17 had 770 orders. The fix (`1233af8`, Nov 19) was never back-filled: `report_rows` for 2019-11-17 shows 487 units / 148,857.07 while `payments` shows 735 transactions / 229,780.49.
8. **~80% of "similar products" traffic is served by the trending fallback, not the recommender.** `analytics.rec_decision_log`: 509,054 of 668k decisions have `fallback_reason='no_scores'`; affinity covers only 3,912 pairs, 75.8% of which carry the `-1` "not enough data" sentinel.
9. **Three HTTP endpoints are silently dead**: `f1217a8` (Oct 26) dropped the `users` and `reports` routers from `app.py`; `c49a7bb` (Dec 5) dropped `accounts`. `/accounts`, `/users/{id}/email`, `/reports/brands` exist in code but are not mounted at HEAD.
10. **The Airflow migration lost the 17:00 intraday report run.** `crontab.txt` had `12:00` **and** `17:00` daily; `airflow/dags/intraday_report_dag.py` only has `schedule="0 12 * * *"`.

---

## 2. Why this project

This document exists to transfer the unwritten operational knowledge of Novamart's systems to anyone who must:

- **Phase 1 — Explain the money.** Answer "what was revenue in month X, and why" the way a tenured finance/data person would: which of the three statement layers to quote, why a number changed after publication, and why live recomputation will never match a snapshot (Sections 3–4, Appendix A/B).
- **Phase 2 — Explain the dashboards.** Know what each of the 9 Redash queries actually counts, which filters are baked in, and which numbers must not be taken at face value (`actives_board` = 0, `contactable_customers` = 0, Nov-17 undercount) (Section 4).
- **Phase 3 — Judge the ML and safely touch the batch jobs.** Know how the recommender versions evolved, why most traffic is fallback, which jobs feed what, and what breaks when they fail (Sections 5 and 7, Appendix C).

The knowledge here was reconstructed exclusively from the pinned repo (`2ae79e2`), the warehouse, the log exports, and Redash — every claim cites its evidence.

---

## 3. Business understanding

### 3.1 What the company does

Novamart is a consumer marketplace ("Backend for the novamart marketplace", `README.md`). Vendors supply a catalog/price feed (`POST /catalog/prices`, `novamart/routers/catalog.py`); shoppers view products, add to carts, and pay through an external **payment gateway** that calls back `POST /orders` — the callback, not a checkout UI, is what creates orders (`novamart/routers/orders.py`, docstring "Order creation from payment-gateway callbacks"). Product range is a general marketplace: electronics (apple/samsung dominate brand revenue — BQ brand query: apple $236.6k, samsung $128.6k in the last 30 days of data), apparel, appliances, kids, construction (`analytics.category_names`, 139 codes).

### 3.2 Scale (verified in warehouse)

| Measure | Value | Evidence |
|---|---|---|
| Users (auto-created on first sight) | 38,950 | `novamart.users` count |
| Products | 81,018 (17,442 blank brand) | `novamart.products` count |
| Orders (all statuses) | 9,127 | `novamart.orders`; matches 9,127 `order_created` app events |
| Paid gross, Oct / Nov 2019 | 1,230,332.43 / 1,101,397.01 | `novamart.statements` |
| December 2019 (never published) | ~552,328.93 status-1 gross | BQ orders query; no Dec row in `statements` (job runs on the 1st; migration happened first) |
| 30-day active buyers at year end | ~1,150 | `analytics.kpi_daily` 2019-12-31 |

### 3.3 Company timeline (from `git log` + `novamart_logs.job_runs`)

- **Sep 15**: initial import (`2da4141`): app + daily report + reconcile + monthly statement + first dashboards.
- **Oct 1–15**: early chaos: duplicate gateway callbacks created duplicate orders (130 payment_refs still have >1 order — BQ; reconcile flags them nightly, 10,766 warning lines). Idempotency by `payment_ref` landed Oct 15 (`b676969`).
- **Oct**: catalog cleanup era: test SKUs excluded (`83fb3ed`), `lucente` brand hidden "per partnerships" (`ba1fbfa`), blank brand repair (`ea0e97b`), price-feed upsert fix (`d213f6e` — before it, `ON CONFLICT DO NOTHING` silently ignored price updates).
- **Oct 26**: similar-products widget ships (`f1217a8`) — and silently unmounts `users`/`reports` routers.
- **Nov 2–5**: statement fee fix (`a92c96d`), DST window fix (`102c9b4`).
- **Nov 16–17**: flash-sale spike (770 orders on Nov 17 — `app_events`); daily report scan cap bug found and fixed Nov 19 (`1233af8`), never backfilled.
- **Nov 20**: processor fee change to 2.9% + $0.30 (`12e1c68`, `FEE_CHANGE_AT` in `monthly_statement.py`).
- **Nov 22**: multi-item order merging (`5d1300d`); `order_lines` born. Order *and* transaction volume also genuinely halves right after (payments/day ~110–120 → ~35–50; BQ payments-per-day query) — a real demand drop, not just the merge artifact.
- **Nov 27 – Dec 5**: registered-accounts beta (`b567d9d`; all 30 accounts were created in a single batch at 2019-12-01 16:30 — `account_created` events in `app_events`), killed silently when `c49a7bb` unmounted the router on Dec 5.
- **Dec**: ML month: affinity v2 (`89666bf`, crashed Dec 3–5, fixed `3dbe4d7`), version-dispatched serving + 5% random arm (`df4ed85`), fraud auto-hold (`e4656fb`), model v4 training (`a1946ff`), plus finance restatement machinery (`cd559d3`, `4a58d17`, `a3bffec`).
- **Jan 2020**: platform migration — dashboards to Redash (`57ea43a`), cron to Airflow (`43e54a1`), serving Postgres snapshot loaded to BigQuery (`2ae79e2`, `warehouse_backfill_dag.py` "Triggered manually … during the Jan 2020 platform migration").

### 3.4 The order lifecycle (statuses)

From `novamart/constants.py` and `orders.py`:

| Status | Meaning | Notes |
|---|---|---|
| 0 | pending | transient within the create-order transaction; 0 rows at rest (BQ) |
| 1 | paid/complete | the only status finance counts |
| 2 | cancelled | was **4** until `8f19718` (Oct 28) renumbered it; no status-4 rows remain |
| 3 | refunded | added `d87cb3d` (Nov 15) |
| 5 | (never set) | referenced only by `reconcile.py` (`WHERE status <> 5`) — a dead sentinel, no rows |
| 6 | fraud-held | set by `fraud_score.py` since `e4656fb` (Dec 3); 12 rows / $40,213.29 at year end |

Key subtlety: **status 6 (held) orders are excluded from statements** (status = 1 filter) **but included in the daily report** (`EXCLUDED_STATUSES = [0, 2, 3]` doesn't list 6) and in dashboards (no status filter at all).

---

## 4. Metrics

### 4.1 Monthly revenue — the canonical answer

"What was revenue in month X?" has three legitimate answers (`docs/restatement_policy.md`, `a576d0d`; view definitions verified via `novamart_analytics.INFORMATION_SCHEMA.VIEWS`):

| Layer | Table/View | Oct 2019 net | Use when |
|---|---|---|---|
| As published | `novamart.statements` | 1,194,652.79 | reproducing an old board deck |
| Fee-corrected | `analytics.statements_corrected` | 1,194,652.93 | separating the fee bug from chargebacks |
| **Final restated** | `analytics.statements_final` | **1,191,085.36** | any current finance/external reporting (Redash query 9) |

Mechanics, all verified against live data:

- The monthly job (`novamart/jobs/monthly_statement.py`, runs 06:30 local on the 1st — `monthly_statement_dag.py`) computes **gross = SUM(orders.price) for status=1 in the NY-local month**, **fee = SUM(payments.fee) collected**, net = gross − fee, and appends a snapshot. Months are **America/New_York** windows (`timeutil.local_month_window_utc`, `LOCAL_TZ` in `constants.py`) — not UTC.
- **The October fee bug**: the original job computed fee = gross × 2.9% (see pre-image in `a92c96d`'s diff) → published fee 35,679.64. Actual collected per-order fees (each `ROUND`ed at booking, `orders.py` line `fee = round(price * FEE_RATE + FEE_FLAT, 2)`) totaled 35,679.50. Fixed `a92c96d` (Nov 2); the correction is carried as the single row in `analytics.statement_overrides` ("Corrected to sum of per-order collected payment fees") and applied by `statements_corrected`.
- **Chargebacks**: `analytics.chargebacks` has exactly 3 rows (orders 46, 49, 55; total 3,567.57; reported_at 2019-12-01), added with the `statements_final` view in `cd559d3` (Dec 9). The view books them against the **order's original month** (October), not the booking month.
- **The November fee-change wrinkle**: fees changed to 2.9% + $0.30 on Nov 20 (`12e1c68`). The Dec 1 statement run warned `statement_fee_mismatch delta=-170.41` (`novamart_logs.app_events`) because its expected-fee model still assumed 2.9% flat; the collected fee (32,110.92 = booked into the statement) was correct. `4a58d17` (Dec 2) taught the expectation the `FEE_CHANGE_AT` boundary and booked the audit outcome as `analytics.statement_corrections` month=2019-11, **delta = 0** ("November 2019 processor fee change audit correction") — i.e. *no restatement was needed*.
- **September 2019** (12 orders, 2,702 gross in `statements`) is unreproducible from `orders`: every pre-Oct-1 order has since been cancelled/refunded (min status-1 `created_at` is 2019-10-01 11:59 UTC — BQ).

### 4.2 Refunds

Two mechanisms that never overlap (BQ: 0 orders have both):

1. **Status flip** — `POST /orders/{id}/refund` sets status 3 (`d87cb3d`); cancel sets 2. Money rows are untouched.
2. **Gateway webhook** — `POST /payments/gateway_refund` inserts a **negative `payments` row** (gross = −amount, fee = 0); "the gateway is the source of truth for money" (`payments_webhook.py`, `c49a7bb`, Dec 5). 9 events, −1,843.59, all December.

`analytics.refunds_unified` (view; `a3bffec`) unions both: status-2/3 orders (amount = `orders.price`, at = `updated_at`) + negative payments. The Redash `refunds` dashboard (query 6) groups this **by the month the refund happened, not the order month** — so the 54 cancels + 28 refunds of Sep/Oct-era orders appear as Nov/Dec refund activity (BQ: Nov 24 cancels/8 refunds; Dec 30/20 + 9 gateway). Note the asymmetry with `statements_final`, which books chargebacks back to the *order* month.

### 4.3 Daily revenue: `report_rows` and its scars

`novamart/jobs/daily_report.py` (06:00 daily) writes yesterday's per-product units/revenue into `report_rows`, item-level with legacy fallback, excluding: statuses 0/2/3, `analytics.test_users`, `EXCLUDED_SKUS = [1004856, 1002544]`, `BRAND_DENYLIST = ["lucente", "jetem"]`. Known permanent defects:

- **2019-11-17 undercount** (`fetchmany(500)` cap; fixed forward-only by `1233af8`): report says 487 units / 148,857.07; payments say 735 / 229,780.49. **2019-11-16** is also slightly short (383 vs 401). Never re-run — BQ shows exactly one `created_at` version per report_date.
- **2019-11-03 DST hole** (`102c9b4` fixed Nov 5, forward-only): the fall-back day is 25h long; the old `start + 24h` window dropped the last local hour. 8 orders / 2,985.99 created 04:00–05:00 UTC on Nov 4 are in no report_date (BQ).
- `report_rows` is **append-only**; a re-run would create a second `created_at` version for the same date. Correct read pattern: keep only `MAX(created_at)` per `report_date` (this is what Redash queries 5/8 do, per the long comment in query 8).

`report_rows_intraday` (same shape; `a2e0013`, Dec 8) receives intraday snapshots of "today" — appended, multiple per day, and **the day's final totals also land in `report_rows`**, so naive UNIONs double count. That exact bug shipped in the first revenue widget (`686a5d6`, Dec 19) and was fixed by `3eced24` (Dec 24) — current Redash query 8 carries the fix and the explanatory comment.

### 4.4 Active customers — three coexisting definitions (`docs/metrics_definitions.md`, `dd0c8fc`)

| Surface | Definition | Value at 2019-12-31 | Trust |
|---|---|---|---|
| `analytics.kpi_daily` (job `kpi_daily.py`, `14726e7`) | distinct buyers, trailing 30×24h, status=1, **no exclusions** | 1,152 (table) | usable; includes QA/test users |
| Redash 5 `daily_kpis` | distinct ordering users per NY calendar day, **no status filter**, excl. 424242 + lucente/jetem | per-day series | usable per-day; not a 30d KPI |
| Redash 1 `actives_board` (`2dde4f0`) | trailing 30d, excl. statuses 0/2/3, `test_users`, and email heuristics | **0** (BQ-verified: 1,155 candidates → 0) | **broken** — every placeholder `@example.com` user is excluded |

Also: `contactable_customers` (Redash 5, from `analytics.contactable_users`, `e10cb0c`) is **always 0** — the view has 0 rows because all 38,910 `example.com` emails fail it and the 40 updated emails are `@gmail.example`, rejected by the `%.example` rule (BQ email-domain query). Meanwhile `email_digest.py` defines contactable as `email NOT LIKE '%@example.com'` → 40 recipients nightly (`analytics.digest_log`), including the QA account. Same word, three incompatible definitions.

### 4.5 Product metrics

- **Best sellers** (Redash 2): rolling 7×24h window, item-level CTE, excl. 424242 and lucente/jetem, **no status filter**, `COUNT(*)` as units but **sorted by revenue** (`docs/dashboard_notes.md`, `a9a4b0b`). It will not match the nightly `top_sellers.py` job (`9a51155`), which uses local calendar day, status=1, and **no** QA/brand/SKU exclusions, ranks by units into `novamart.top_products`.
- **Brand revenue** (Redash 3): 30-day rolling; excludes the QA user in *both* namespaces — `'424242'` and account UUID `'cc27b436-d6f9-4e84-adaf-e716025dd369'` (`adbcb7e`; the UUID was created for the same smoke-test account on 2019-12-01 16:30 — `account_created` app event). Note `brand='internal'` is **not** excluded and showed $7.6k/60 units in the last-30d snapshot (BQ), and blank-brand items appear as an empty-string row.
- **Category revenue** (Redash 4): maps `products.category` codes to display groups via `analytics.category_names` UNION `analytics.category_name_history` with `valid_from <= order date`, latest wins (`2814b3d`, versioned in `33054cd`). The history table holds the pre-rename mapping (electronics.audio.* was "entertainment", construction.tools.light was "lighting") stamped `valid_from = 2026-08-13` (the migration backfill date), so it never matches 2019 orders — it is an archive, not an active override. Unmapped codes fall to `'other'`.
- **Hidden brands**: `lucente` hidden "per partnerships" (`ba1fbfa`, Oct 25) — it has real money: 139 status-1 orders / $42,853.23 all-time (BQ). `jetem` (added `1169e40`) has 5 products and **zero orders ever** — purely prophylactic.
- **Excluded "test" SKUs** (`83fb3ed`): 1004856 is genuinely internal (`Internal Test #4856`, category `qa.test`; 328 orders/$40,968 of smoke traffic). **1002544 is a real Apple smartphone at $635.14 with 139 orders / $66,690** — it is nonetheless excluded from daily reports and the similar widget. Statements still count both (no exclusions).

### 4.6 Funnel & sessions

`analytics.daily_funnel` (job `funnel.py`, `4dbcf7f`): sessionizes cart+order timestamps per user with an inactivity gap — **30 min until Dec 14, 120 min after (`f915c1b`)**. Session counts before/after Dec 14 are not comparable. `registered_conversion` (Redash 7) counts buyers among the 30 beta accounts by **email-mapping accounts→users** — the original version joined UUID `account_id` to numeric `user_id` and returned ~nothing ("FIXME(dec): numbers look low", `d6e34c6`; fixed `b975479`).

---

## 5. System

### 5.1 Service (FastAPI, `novamart/app.py`)

Routers currently mounted: `catalog`, `carts`, `orders`, `similar`, `payments_webhook`. **Not mounted (dead code)**: `users` and `reports` (dropped in `f1217a8`, Oct 26), `accounts` (dropped in `c49a7bb`, Dec 5). Log evidence agrees: all 40 `user_email_updated` events are one batch at 2019-10-23 13:00 (users router live Oct 16–26), all 30 `account_created` events are one batch at 2019-12-01 16:30 (accounts router live Nov 27–Dec 5), and the `reports` router was only live Oct 21–26 (`193f22d`→`f1217a8`) — see `bq_routers_results.txt`.

Order creation (`orders.py`) is the most intricate path — three outcomes, all logged to `app_events`:
1. **replay** (`order_callback_replayed`, 522 events): payment_ref already known (advisory-locked on ref) → backfill missing payment, revive status-0.
2. **append** (`order_appended`, 225 events): same user+session order within 15 min → add `order_lines` row, add payment, `price = price + item` (since `5d1300d`).
3. **create** (`order_created`, 9,127 events): new order + line + payment; fee computed *at booking* (2.9% + $0.30 since `12e1c68`).

It also runs `CREATE TABLE IF NOT EXISTS order_lines` / `ALTER TABLE payments ADD COLUMN payment_ref` inline on every request — schema migration by traffic, a known idiom here (schema.sql only has the original 6 tables).

### 5.2 Scheduled jobs (crontab → Airflow, times local NY)

| Time | Job | Writes | First/last run in `job_runs` | What breaks if it fails |
|---|---|---|---|---|
| 03:00 | `reconcile` | log warnings only | Sep 16 → Dec 31 (107 runs) | duplicate-ref detection stops; note `388370b` moved it to 3am *into* the backup window |
| 03:30 | `affinity` (v1) | `analytics.product_affinity` | Oct 13 → Dec 31 (80) | nothing user-visible — **no reader since Dec 6** (db_queries: v1 SELECTs = 0 after Dec 6) |
| 03:45 | `affinity_v2` | `analytics.product_affinity_v2` | crashed Dec 3–5 (`job_crashed`×3, seasonal-factor index bug, fixed `3dbe4d7`), OK Dec 6→31 (26) | widget loses fresh scores → more trending fallback |
| 04:15 | `model_train` | `model_registry`, `model_scores` | Dec 15 → Dec 31 (17) | flag-gated v4 scores go stale (currently unserved) |
| 04:45 | `price_suggest` | `analytics.price_suggestions` | Nov 25 → Dec 31 (37) | nothing — shadow only, ON HOLD per exec/legal (`cca9b0d`, file NOTE) |
| 05:15 | `trending` | `analytics.trending_daily` | Nov 3 → Dec 31 (59) | **homepage trending AND the rec fallback** (~80% of rec traffic) go stale |
| 05:45 | `fraud_score` | `analytics.order_risk`, sets status 6 | Dec 4 → Dec 31 (28) | no new holds; held-order release is manual |
| 06:00 | `daily_report` | `report_rows` | Sep 16 → Dec 31 (107) | KPI dashboard/revenue widget historical days missing (they'd silently show stale MAX(created_at) data) |
| 06:15 | `kpi_daily` | `analytics.kpi_daily` | Nov 17 → Dec 31 (45) | 30d actives series gaps |
| 06:20 | `funnel` | `analytics.daily_funnel` | Nov 9 → Dec 31 (53) | funnel series gaps |
| 06:30 (1st) | `monthly_statement` | `novamart.statements` | Oct 1, Nov 1, Dec 1 | no statement published; **December 2019 was never published** (migration preempted the Jan 1 run) |
| 06:45 | `top_sellers` | `novamart.top_products` | Nov 7 → Dec 31 (55) | merchandising ranking stale |
| 06:50 | `reorder_forecast` | `analytics.reorder_hints` | Nov 27 → Dec 31 (35) | advisory only (`docs/forecast_caveats.md`) |
| 07:15 | `email_digest` | `analytics.digest_log` | **Dec 17** → Dec 31 (15) | see the flag saga below |
| 12:00 (+17:00 lost) | `intraday_report` | `report_rows_intraday` | Dec 8 → Dec 31 (47) | "today" disappears from revenue widget/daily KPIs |

All DAGs (`airflow/dags/*.py`) are thin `BashOperator` wrappers with `catchup=False`; **the intraday 17:00 cron entry has no Airflow counterpart** (compare `crontab.txt` lines `12:00`/`17:00` vs `intraday_report_dag.py` `"0 12 * * *"`).

**The email-digest flag saga** (why 15 runs instead of ~34): shipped Nov 28 reading env `DIGEST_ON` while `deploy/cron.env` set `ENABLE_DIGEST=1` (`c19a307`) → silently skipped; `8dc520b` (Dec 9) read `ENABLE_DIGEST` from the environment, but cron never sourced the file → still skipped; `0bd4eac` (Dec 16) reads `deploy/cron.env` directly → first real run Dec 17 (`job_runs`). Lesson: job "success" logs only exist when the job runs; silent `return` on a flag looks identical to not being scheduled.

### 5.3 Logging & observability

`novamart/logutil.py` writes three files, exported to BigQuery (`docs/data-access.md`):
- `app.jsonl` → `novamart_logs.app_events` (jsonPayload; 843k `product_viewed`, 669k `rec_served`, etc.)
- `db_queries.log` → `novamart_logs.db_queries` (every SQL statement, app and jobs, "postgres log_statement style" — `db.py`); `novamart_logs.db_queries_normalized` view parses it into an INFORMATION_SCHEMA.JOBS-like shape with `referenced_tables` (view definition in dataset) — the best tool for "who reads/writes table X".
- `jobs.jsonl` → `novamart_logs.job_runs` (start/finish/stats events; `job_crashed` for failures).

### 5.4 CI and ops

`ci/run_ci.py` boots the app on a scratch DB, exercises view→cart→order, checks orders/payments consistency, then runs reconcile/daily_report/monthly_statement under `FAKE_NOW` (also honored by `timeutil.now()` — "FAKE_NOW is only set in test rigs"). `scripts/rerun_kpis.py` (`35c581e`) is a stub runbook for reapplying the promo cap; note the trap: `apply_discounts` defaults to the **legacy 0.40 cap** while `constants.DISCOUNT_CAP = 0.25` — callers must pass it explicitly.

---

## 6. Data

### 6.1 Where everything lives (post-migration, `docs/data-access.md`)

- **BQ `novamart`** (12 tables) = snapshot of serving Postgres `public.*`: `users`, `products`, `cart_items`, `orders`, `order_lines`, `payments`, `report_rows`, `report_rows_intraday`, `statements`, `top_products`, `accounts`, `account_map`.
- **BQ `novamart_analytics`** (20 tables + 4 views) = `analytics.*` schema: batch outputs (`kpi_daily`, `trending_daily`, `daily_funnel`, `product_affinity{,_v2}`, `model_registry`, `model_scores`, `rec_decision_log`, `order_risk`, `price_suggestions`, `price_history`, `reorder_hints`, `digest_log`), finance restatement (`statement_overrides`, `statement_corrections`, `chargebacks`), reference (`category_names`, `category_name_history`, `test_users`, `blank_brand_products`), plus views `contactable_users`, `refunds_unified`, `statements_corrected`, `statements_final`.
- **BQ `novamart_logs`**: `app_events`, `db_queries`, `db_queries_normalized` (view), `job_runs`.
- The warehouse was loaded by `novamart.jobs.warehouse_backfill` (`2ae79e2`) as a **one-shot CSV export + `bq load --replace`** driven by `warehouse_manifest.json` — it is a point-in-time snapshot (data ends 2019-12-31), not a live sync.

### 6.2 Identity: the two-namespace trap

- `users.id` / `orders.user_id` = **legacy numeric shopper id**, minted by the storefront; user rows are auto-created on first sight with **synthetic deterministic profiles and placeholder emails** `user{uid}@example.com` (`novamart/onboarding.py` — "synthesized deterministically from the id"; `catalog.ensure_entities`).
- `accounts.account_id` = **UUID** from the registered-accounts beta (30 rows, Nov 27–Dec 5), linked via `account_map(uid, account_id)`. UUIDs and numeric ids are **not castable/comparable**; join through `account_map` or shared email (Redash query 7's NOTE, `b975479`).
- Consequences: every email-based "real user" filter nukes the whole population (Section 4.4); the QA smoke account exists in both namespaces (424242 and `cc27b436-…`), which is why brand_revenue excludes both strings.

### 6.3 Data quality landmines (each verified)

1. **130 payment_refs map to >1 order** (pre-Oct-15 duplicate callbacks; BQ GROUP BY havings). Reconcile re-flags them every night (10,766 cumulative warnings, 214 runs). De-dup by ref when counting pre-Oct-15 transactions.
2. **`orders.price` semantics changed Nov 22**: per-item before, per-order (sum of lines) after (`5d1300d`). `payments` (one row per gateway callback) is the only volume series comparable across the boundary.
3. **`statements.orders_count` is not item count nor comparable across Nov 22** (order rows merged); it also can't be re-derived after statuses mutate.
4. **Blank product metadata**: products are created from order/view context with empty category/brand (`PRODUCT_INSERT` with `""`), later repaired by feed events (`_repair_product_brand`, `ea0e97b`); still 17,442 blank brands, 33,514 blank categories; `analytics.blank_brand_products` (5,972 rows) is the repair-era snapshot.
5. **`analytics.price_history`** only starts 2019-11-18 (`795d273`; 1,400 rows / 241 products; 13 `price_feed_received` events) — no earlier price provenance exists; `products.list_price` is "current" only.
6. **Snapshot tables that are overwritten nightly** (no history): `product_affinity{,_v2}`, `model_scores`, `price_suggestions`, `reorder_hints` (all `DELETE FROM` then insert — see each job). `trending_daily` and `kpi_daily` are append-per-day and safe for time series.
7. **`report_rows`/`report_rows_intraday` are append-only with versions** — always dedupe by `MAX(created_at)` per `report_date`.
8. **September/Oct 1 cohort**: all pre-Oct-1 orders are now status 2/3; `refunds_unified` shows them as Nov/Dec activity (by `updated_at`).

---

## 7. Experimentation

### 7.1 The similar-products widget: versions, arms, and reality

Serving (`novamart/routers/similar.py`, evolution `f1217a8` → `df4ed85` → `30e8907` → `a00f24c` → `8ed2971`):

- **Version dispatch** via `deploy/flags.env` `REC_MODEL_VERSION=2.0.0`: `2.0.0` → read `analytics.product_affinity_v2`; `4.0.0` → `analytics.model_scores`; `1.0.0` retired ("kept for old log rows"). **There has never been a 3.0.0** — `git log -S'3.0.0'` finds nothing; `docs/rec_versions.md` is literally "TBD".
- **Random arm**: `sha256(uid) % 20 == 0` → ~5% of *users* get uniform-random items (2.18% of decisions — `rec_decision_log`), designed as unbiased training data.
- **Fallback**: no scores → serve latest `analytics.trending_daily` top-K with `effective_version='fallback'`.
- **Cache**: 6h in-process TTL; invalidation on nightly refresh only since `8ed2971` (Dec 26) — before that, post-refresh scores could be up to 6h stale.
- **Version-string mismatch to memorize**: the v2 *table rows* say `model_version='2.0.1'` (writer constant in `affinity_v2.py`) while the *serving flag* says `2.0.0` (`docs/affinity_lineage.md`).

Reality check from `analytics.rec_decision_log` (668k rows) — the headline finding:

| Era | Served by model | Served by fallback |
|---|---|---|
| v1 (Oct 26–Dec 6) | 66,444 (`rec_source='affinity'`) | 326,186 (83%) |
| v2 (Dec 6–Dec 31) | 52,695 (`source='model'`) | 207,959 (~80%) |

Cause: coverage. Both affinity tables hold only **3,912 pairs, 75.8% of them the −1 sentinel** ("not enough data to trust", `MIN_PAIRS=3` graduation gate from `fef5c96`; serving filters `score >= 0`). With ~81k products, almost every product page finds no scores → `fallback_reason='no_scores'` (509,054 rows). **Judgment: the "recommender" is, in production effect, mostly the trending list.**

The Dec 6 cutover is crisply visible in `db_queries_normalized`: v1-table SELECTs drop to 0 and v2 SELECTs take over on 2019-12-06 — yet the v1 job still runs nightly at 03:30 writing a table nobody reads (`docs/affinity_lineage.md` reached the same conclusion).

### 7.2 Affinity models

- **v1** (`affinity.py`, `776d674`): co-carted pairs, 30-day window, recency decay `exp(-0.05·age)`, full nightly recompute.
- **v2** (`affinity_v2.py`, `89666bf`): adds conversion weighting (cart=1, order=3), same-category ×1.15 boost, extreme price-ratio ×0.7 damping, and monthly `SEASONAL_FACTORS` — an 11-element list (Jan–Nov, "from the 2019 planning sheet") that **crashed in December** (`job_runs`: `job_crashed` Dec 3/4/5) until `3dbe4d7` added the `t.month <= len(...)` guard defaulting to 1.0. December scores therefore have *no* seasonal factor.

### 7.3 Model v4 (the trained one) — exists, never served

`model_train.py` (`a1946ff`, nightly 04:15 since Dec 15): logistic regression on random-arm exposures. Honest assessment for anyone asked "does it work":

- **Label leakage/weakness**: `converted` = user placed *any* status-1 order *any time after* the exposure — not "bought a recommended item" (SQL in the job).
- **Features** (5): served-list size, base price/1000, base popularity/100, account age (capped), organic-channel flag; `opt_in` fetched but deliberately not used ("calibration pending" NOTE). README's grander feature list ("region affinity, device mix, stock level") is aspirational, not what the code does.
- **Instability**: 17 `model_registry` rows; coefficients swing daily and flip signs (e.g. account-age coef +0.81 on Dec 30 → −0.75 on Dec 31).
- **Scores are not model outputs**: `model_scores` = affinity-v2 scores rescaled by `(1 + 0.1 × first coefficient)` — a monotone tweak of v2, 948 rows.
- **Training data has a hole**: the Dec 17 refactor (`30e8907`) dropped random-arm decision logging; restored Dec 19 (`a00f24c`). `rec_decision_log` has **0 random rows on Dec 18** while `app_events` shows 848 random `rec_served` that day — those exposures are unrecoverable for training.
- Serving is gated off (`REC_MODEL_VERSION=2.0.0`). Flipping to 4.0.0 needs a flags.env change + redeploy.

### 7.4 Fraud scoring (rules, not ML)

`fraud_score.py` (`e4656fb`, Dec 3): `score = min(price/3000, 1) × (1 + 0.15·new_account + 0.15·high_velocity)`, hold above threshold → status 6. Threshold history: 0.70 (`53f6f6c`, Dec 5) → **0.85 + manual release of held orders under $2,600** (`1cb8721`, Dec 29). Current state: 1,631 scored, 13 ever above 0.85, **12 orders / $40,213.29 still held** (all ≥ $2,655 — BQ). Remember these are excluded from statements but not from the daily report (Section 3.4).

### 7.5 Shelved / advisory experiments

- **Dynamic pricing**: `price_suggest.py` (`894c535`) writes 500 ±5% nudges nightly; **Phase 2 serving ON HOLD per exec/legal review** (`cca9b0d` + file NOTE). Zero production reads ever (`db_queries_normalized`: 0 SELECTs). 5 rows have `current_price = 0` (auto-created products) — beware division by zero.
- **Reorder hints**: `reorder_forecast.py` (`f5e3032`) — `hint = 15.6 + 162.4/(velocity + 1.8)`, hand-fit; **inverse**: slower sellers get *bigger* hints. December "refit" (`f85cdd2`) changed only K. ADVISORY per README and `docs/forecast_caveats.md`; 1 SELECT ever in prod logs.
- **Registered accounts beta**: 30 accounts, endpoint dead since Dec 5 (Section 5.1).

---

## 8. Glossary

| Term | Meaning | Evidence |
|---|---|---|
| **as-published vs restated** | `novamart.statements` snapshot vs `analytics.statements_final` after overrides+chargebacks | `docs/restatement_policy.md` |
| **statement override / correction** | `statement_overrides` = replacement values applied by `statements_corrected`; `statement_corrections` = audit record of deltas (Nov row has delta 0) | BQ tables, `4a58d17` |
| **chargeback** | gateway-reported clawback booked to the *order's* month by `statements_final` | `cd559d3`, `analytics.chargebacks` |
| **gateway refund** | negative `payments` row from webhook; money truth lives in payments | `c49a7bb` |
| **order vs order line** | since `5d1300d` an order can hold multiple `order_lines`; `orders.price` = sum | Nov 22 boundary |
| **legacy fallback (item_orders CTE)** | UNION of `order_lines` + line-less `orders` rows — mandatory for item-level counts | `92596dc` |
| **payment_ref** | gateway idempotency key; unique per callback since `b676969`; 130 historical dupes remain | reconcile warnings |
| **status 6 / held** | fraud auto-hold; not paid for statements, still visible in daily report | `e4656fb` |
| **QA smoke account** | user 424242 (`session: qa-smoke`) and account UUID `cc27b436-d6f9-4e84-adaf-e716025dd369` | `app_events`, `adbcb7e` |
| **test SKUs** | 1004856 (real internal test) and 1002544 (an actual $635 Apple phone!) hidden from daily report | `83fb3ed`, BQ |
| **lucente / jetem** | brands hidden from reports/dashboards per partnerships; lucente has real revenue, jetem none | `ba1fbfa`, `1169e40` |
| **placeholder email** | `user{uid}@example.com` auto-generated for every user; breaks email-based "real user" filters | `onboarding.py`, `catalog.py` |
| **contactable user** | 3 conflicting definitions: view (0 rows), digest rule (40 users), dashboard column (always 0) | Section 4.4 |
| **graduation gate / sentinel −1** | affinity pairs seen <3 times get score −1 = "not enough data", filtered by `score >= 0` at serving | `fef5c96` |
| **random arm** | 5% of users (sha256 uid % 20 == 0) get random recs for unbiased training data | `df4ed85` |
| **fallback** | trending-top-K served when a product has no scores; ~80% of all rec traffic | `rec_decision_log` |
| **REC_MODEL_VERSION** | deploy-time flag choosing 2.0.0 (affinity v2) vs 4.0.0 (model scores); 3.0.0 never existed | `deploy/flags.env` |
| **FAKE_NOW** | env var overriding job clock in test rigs/CI | `timeutil.py` |
| **local day / month** | all report windows are America/New_York, DST-aware since `102c9b4` | `timeutil.py` |

---

## Appendix

### A. October 2019 — the worked example (answering "what was revenue and why")

1. Board deck / originally published: **net 1,194,652.79** (`novamart.statements`, row created 2019-11-01 10:30).
2. Fee override (+0.14): statement had computed fee 35,679.64 = gross×2.9%; collected fees were 35,679.50 → **net 1,194,652.93** (`statement_overrides` note; `a92c96d`).
3. Chargebacks (−3,567.57 on orders 46/49/55, booked Dec 1 to October): → **net 1,191,085.36** (`statements_final`).
4. A live recompute from `orders` today gives ~1,206,337 gross / 3,695 orders vs the published 1,230,332.43 / 3,765 — the gap is the Sep/Oct-cohort orders cancelled or refunded *after* publication. Neither number is "wrong"; they answer different questions.

### B. Discrepancy cheat-sheet (why numbers don't match)

| Symptom | Root cause |
|---|---|
| Dashboard revenue ≠ statement gross | dashboards exclude QA/lucente/jetem and use rolling windows; statements exclude nothing, NY-month window, status=1 only |
| Hand query lower than best_sellers | you filtered status=1; the dashboard doesn't |
| Nov 17 looks weak everywhere driven by `report_rows` | permanent scan-cap undercount (487 vs 735 units) |
| Nov 3 daily total slightly short | DST 25-hour-day bug, 8 orders/$2,985.99 never reported |
| Orders/day halves at Nov 22 | half real demand drop (payments/day 120→40), half the order-merge change; use `payments` for cross-boundary volume |
| Board actives = 0 | email heuristics vs placeholder emails |
| contactable_customers = 0 | `contactable_users` view empty by construction |
| Refund months look strange | `refunds_unified` books by status-change date; statements_final books chargebacks by order month |
| Sept revenue can't be found in orders | whole cohort later cancelled/refunded; only the statement snapshot remains |
| trending churns faster in Dec | window 60→30 days on Dec 6 (`f563dea`); README's "60-day" note is stale (`docs/trending_notes.md`) |
| funnel sessions jump on Dec 14 | gap 30→120 min (`f915c1b`) |

### C. What actually breaks when jobs fail (observed failure modes)

- `affinity_v2` crashed Dec 3–5 (seasonal index): widget silently served more fallback; only visible in `job_runs.job_crashed` and the missing refresh.
- `email_digest` "failed" invisibly for ~3 weeks (flag mismatch): zero log lines — absence of evidence is the only evidence.
- `daily_report` failures would freeze the KPI dashboard on the previous `MAX(created_at)` version rather than showing gaps — check `job_runs` before trusting a flat day.
- A missed `monthly_statement` run is permanent unless re-run promptly: December 2019 was never published because the platform migrated before Jan 1's run.

### D. How to answer common asks (query recipes, BQ standard SQL)

- **Restated monthly net**: `SELECT month, net FROM novamart_analytics.statements_final ORDER BY month`.
- **Item-level units for a window** (the only correct pattern):
  `WITH io AS (SELECT o.user_id, ol.product_id, ol.price, ol.created_at FROM novamart.orders o JOIN novamart.order_lines ol ON ol.order_id=o.id UNION ALL SELECT o.user_id, o.product_id, o.price, o.created_at FROM novamart.orders o WHERE o.id NOT IN (SELECT order_id FROM novamart.order_lines)) SELECT ... FROM io`.
- **Cross-era transaction volume**: count `novamart.payments` where `gross >= 0`.
- **Who reads/writes table X**: `SELECT ... FROM novamart_logs.db_queries_normalized, UNNEST(referenced_tables) t WHERE t.table_id='X'`.
- **Job health**: `SELECT JSON_VALUE(jsonPayload,'$.job') job, JSON_VALUE(jsonPayload,'$.event') event, COUNT(*) FROM novamart_logs.job_runs GROUP BY 1,2`.

### E. Evidence inventory (files in this run's directory)

| File | Contents |
|---|---|
| `git_log_full.txt`, `repo_files.txt` | full commit history (112 commits), repo file list |
| `bq_view_definitions.txt` | all 4 analytics view definitions |
| `bq_finance_results.txt`, `bq_finance2_results.txt`, `bq_finance3_results.txt` | statement layers, overrides, chargebacks, order/payment volumes, refunds_unified, order_lines distribution |
| `bq_logs_results.txt`, `bq_logs2_results.txt` | job_runs summary, fee-mismatch warnings, QA-account evidence, contactable-email evidence, Nov 16/17 report versions |
| `bq_phase2_results.txt` | products/brands/categories, price_history, excluded SKUs |
| `bq_phase3_results.txt`, `bq_phase3b_results.txt` | affinity/model/rec_decision_log/fraud/reorder/price tables; random-arm gap; duplicate refs |
| `bq_actives_results.txt` | actives_board = 0 replication; v1→v2 read cutover; shadow-table read counts |
| `bq_final_results.txt` | DST gap orders, jetem, status audit, signups, refund-overlap check |
| `bq_routers_results.txt` | endpoint lifetimes: account_created / user_email_updated / price feed / gateway refund event timelines |
| `redash_dashboards.json`, `redash_dashboard_*.json`, `redash_query_*.json` | all 9 dashboards + query SQL (no cached results existed; nothing was refreshed) |
| `git_key_diffs_*.txt`, `git_key_stats_4.txt`, `git_key_commits_1.txt` | diffs of the pivotal commits cited throughout |
| `q_*.sql`, `run_bq.sh` | the exact queries run (read-only SELECTs) |

### F. Open questions (checked, but unresolvable from available evidence)

- Why version **3.0.0** was skipped in `REC_VERSIONS` (no trace in history; `docs/rec_versions.md` is "TBD").
- Whether the post-Nov-22 demand halving was a business event (post-sale slump) or upstream traffic change — the data shows it plainly in `payments`, but no commit/doc explains it.
- Whether SKU **1002544**'s exclusion (a revenue-bearing Apple phone) was intentional; `83fb3ed` gives no rationale.
- Whether anyone intends to re-add the dead `accounts`/`users`/`reports` routers or retire the code.
