# Novamart Tribal Knowledge

- **Run started:** Mon Oct 5 17:39:33 UTC 2026 (wall clock)
- **Run UUID:** `720a0d02-a786-45b8-a96d-515426d81b0b`
- **Repo:** `/home/susnato/lb/runs/claude-fable-5/r1/workspace/novamart`, pinned at commit `5ae1182` ("feat: warehouse backfill job"), 112 commits, 2019-09-15 → 2020-01-05 (`git log`)
- **Warehouse:** BigQuery project `novamart-warehouse` (emulator), datasets `novamart`, `novamart_analytics`, `novamart_logs`
- **Dashboards:** Redash at `http://localhost:5054` — 9 dashboards / 9 queries, all pointed at the Postgres data source `novamart` (Redash API `/api/dashboards`, `/api/queries`, `/api/data_sources`)
- Evidence conventions used below: `commit <hash>` = git commit in the repo; `table`/`view` names are BigQuery (`novamart.*` mirrors Postgres `public.*`, `novamart_analytics.*` mirrors Postgres `analytics.*`); "db_queries" = `novamart_logs.db_queries` (Postgres statement log export); "job_runs" = `novamart_logs.job_runs`; "app_events" = `novamart_logs.app_events`; "Redash query N" = `GET /api/queries/N`.

---

## 1. Summary

Novamart is a FastAPI + Postgres marketplace backend (`README.md`, commit `2da4141` initial import, 2019-09-15). Orders arrive as **payment-gateway callbacks**, not checkout flows; users and products are **bootstrapped on first sight** with synthesized profile attributes and placeholder `user{uid}@example.com` emails (`novamart/routers/catalog.py::ensure_entities`, `novamart/onboarding.py`). Everything analytical is produced by ~16 nightly cron jobs (now Airflow DAGs, commit `4bfcbe6`) writing into an `analytics` schema, surfaced through 9 Redash dashboards that were moved out of the repo's `dashboards/` directory in commit `41e3537`.

The ten most load-bearing pieces of tribal knowledge, each expanded later in this document:

1. **There is no single "revenue."** The published monthly statement (`novamart.statements`), the corrected statement (`novamart_analytics.statements_corrected`), the final restated statement (`novamart_analytics.statements_final`), the daily report (`novamart.report_rows`), and the rolling-window dashboards all give different numbers by design. October 2019 net is `1,194,652.79` as published, `1,194,652.93` fee-corrected, and `1,191,085.36` final (queries against those three tables/views; `docs/restatement_policy.md`).
2. **Statements are point-in-time snapshots over a mutable orders table.** October's published gross (`1,230,332.43`) equals the sum of *all* October orders today, while a fresh `status = 1` query returns only `1,206,337.32`, because 70 October orders were cancelled/refunded *after* the statement ran (status breakdown query on `novamart.orders`; `novamart/jobs/monthly_statement.py`).
3. **The December 2019 monthly statement was never generated.** `novamart.statements` has 3 rows (2019-09/10/11, last `created_at` 2019-12-01); job_runs shows only 3 `statement_generated` events; the schedule migrated to Airflow on 2020-01-04 with `catchup=False` (commit `4bfcbe6`), so the 2019-12 statement (status-1 gross ≈ `552,328.93` by the statement's own rules) silently fell through the migration gap.
4. **Three different "active customers" definitions coexist** (nightly `kpi_daily` rollup, exec `daily_kpis` dashboard, board `actives_board` query) and intentionally disagree (`docs/metrics_definitions.md`, commit `dd0c8fc`; Redash queries 3 and 7; `novamart/jobs/kpi_daily.py`).
5. **"Contactable customers" on the exec KPI dashboard is always 0, and the email digest's "40 recipients" are all test addresses.** The `contactable_users` view excludes `%.example` domains; the only 40 non-placeholder emails in `users` are `@gmail.example` QA addresses (view definition in `novamart_analytics.INFORMATION_SCHEMA.VIEWS`; `SELECT COUNT(*) FROM novamart_analytics.contactable_users` = 0; `digest_log.recipients` = 40).
6. **The gateway-refund webhook is not idempotent and the orders stay `status = 1`.** Replayed webhooks inserted the same refund 3× for orders 3762/3763/3776 (9 negative `payments` rows for 3 real refunds), so `refunds_unified` and the Redash `refunds` dashboard triple-count them, while the orders still count as paid revenue (`novamart/routers/payments_webhook.py`, commit `c49a7bb`; rows in `novamart.payments` with `gross < 0`).
7. **Historical daily-report rows contain permanent, known undercounts**: 2019-11-17 is recorded as 487 units / `148,857.07` but the same rules against `orders` give 704 units / `223,853.03` (the old `REPORT_SCAN_CAP = 500` bug, fixed in commit `1233af8` but never backfilled), and 2019-11-03 is missing the 11pm–midnight EST hour (8 orders / `2,985.99`) from the pre-DST-fix window (commit `102c9b4`). 2019-11-15 genuinely had zero orders.
8. **The similar-products "ML" system mostly serves fallbacks, and v4 is not live.** 83% of v1-era and ~75% of v2-era requests fell back to trending/bestsellers (`rec_decision_log` aggregation); `deploy/flags.env` still says `REC_MODEL_VERSION=2.0.0`, so the trained v4 model only writes `model_scores` nightly that nothing reads; the v4 model itself has label leakage and only rescales affinity-v2 scores by a constant (`novamart/jobs/model_train.py`).
9. **Several API endpoints in the repo are dead code**: the `users`, `reports`, and `accounts` routers were silently dropped from `app.py` in commits `f1217a8` (2019-10-26) and `c49a7bb` (2019-12-05); the current `app.py` only wires catalog, carts, orders, similar, payments_webhook.
10. **Manual one-off SQL is part of the production history.** The statement log shows `[engineer-backfill:*]` actors creating override/chargeback/category tables and, on 2019-12-29, Maya manually releasing fraud-held orders: `UPDATE orders SET status = 1 ... WHERE status = 6 AND price < 2600;` (db_queries, actor `engineer-backfill:maya`, 2019-12-29 15:00 UTC; matches commit `1cb8721`).

---

## 2. Why this project

This document captures the tribal knowledge needed to execute the three goals from the task brief (`rendered_novamart_sim_goal_context.md`):

- **Phase 1 — Financial numbers end to end.** Be able to answer "what was revenue in a given month, and why" the way a tenured finance/data person would: which tables, jobs, and dashboards are the source of truth for orders, payments, refunds, monthly revenue and the finance statements, and how those definitions changed over the company's history.
- **Phase 2 — Product & customer analytics.** Explain every number on the dashboards — best sellers, brand/category revenue, signups, active customers — including when a dashboard number should *not* be trusted at face value.
- **Phase 3 — ML systems and scheduled jobs.** Judge whether the recommendation/fraud/pricing/forecast systems actually work, know what every batch job produces and what breaks when it fails, and be able to safely modify or extend the pipelines.

Why a tribal-knowledge document is required at all: the definitions here live in four places that routinely disagree — the code at HEAD, the git history (behavior changed mid-stream, e.g. fee formula, trending window, order statuses), the warehouse data (which still carries artifacts of old bugs), and the dashboards (which encode cleanup filters nowhere else documented). Several critical facts (manual data fixes, the never-run December statement, replayed refund webhooks) are visible *only* in the log exports, not in any code or doc.

---

## 3. Business understanding

### 3.1 What the business is

A retail marketplace ("novamart marketplace", `README.md`) selling vendor-supplied products across categories like `electronics.*`, `appliances.*`, `apparel.*`, `construction.*`, `kids.*` (category codes observed by `[engineer:dev]` in db_queries 2019-11-30; `analytics.category_names` backfill). Operating timezone is **America/New_York**: "reports and statements are business-local" (`novamart/constants.py::LOCAL_TZ`). Activity in the warehouse snapshot spans 2019-09-25 → 2019-12-31 (min/max `created_at` on `novamart.orders`).

Scale (warehouse row counts as of the snapshot): 38,950 `users`, 81,018 `products`, 9,127 `orders`, 2,284 `order_lines`, 9,361 `payments`, 36,938 `cart_items`. Monthly gross (all statuses, NY-local months): Sep `2,702.00` (12 orders), Oct `1,230,332.43` (3,765), Nov `1,101,397.01` (3,582), Dec `592,542.22` (1,768) — December volume genuinely halved (query on `novamart.orders` grouped by `FORMAT_TIMESTAMP('%Y-%m', created_at, 'America/New_York')`).

### 3.2 How money flows

1. **Catalog**: a vendor price feed `POST /catalog/prices` upserts products and appends to `analytics.price_history` (`novamart/routers/catalog.py`; upsert fixed in commit `d213f6e`, history added in `795d273`). Product views `GET /products/{pid}` bootstrap user/product rows on first sight ("cheap MVP bootstrap", `ensure_entities`). Blank brands are repaired when later events carry a brand (commit `ea0e97b`); 5,972 products still have blank brands worth `38,499.83` in order revenue (`novamart_analytics.blank_brand_products`, created by `[engineer-backfill:dev]` 2019-10-21 in db_queries).
2. **Carts**: `POST /cart` / `POST /cart/remove` write/delete `cart_items` keyed by `(user_id, product_id, session)` (`novamart/routers/carts.py`).
3. **Orders**: `POST /orders` is a *payment-gateway callback*. The handler is idempotent by `payment_ref` (commit `b676969`) and, since commit `5d1300d` (2019-11-22), merges same-session callbacks within 15 minutes into one order: `orders.price` accumulates the total, each item becomes an `order_lines` row, and each callback writes a `payments` row (gross/fee/net). `orders.product_id`/`orders.price` on a multi-line order are therefore "first product id + whole-order total". `order_lines` first appears in production on 2019-11-22 15:18:05 UTC (min `created_at` in `novamart.order_lines`; also `docs/dashboard_notes.md`).
4. **Fees**: processor fee charged per callback = `price * 0.029` before 2019-11-20, `price * 0.029 + 0.30` after (`FEE_RATE`, `FEE_FLAT` in `novamart/constants.py`; fee change commit `12e1c68` dated 2019-11-20).
5. **Cancels/refunds**: `POST /orders/{id}/cancel` → status 2, `POST /orders/{id}/refund` → status 3 (commits `8f19718`, `d87cb3d`). Since 2019-12-05 the gateway also pushes refunds via `POST /payments/gateway_refund`, which inserts a *negative* `payments` row and leaves the order status untouched — "the gateway is the source of truth for money" (commit `c49a7bb`, `novamart/routers/payments_webhook.py`).
6. **Fraud**: a nightly job scores yesterday's paid orders and auto-holds high scores at **status 6** (commit `e4656fb`; `novamart/jobs/fraud_score.py`). 12 orders totalling `40,213.29` are currently held (query on `novamart.orders WHERE status=6`).
7. **Finance**: a monthly job snapshots last month's gross/fee/net into `statements`; corrections and chargebacks are layered on via analytics views (section 4.1).

### 3.3 Customer identity

- **Legacy numeric ids**: `users.id` comes from the storefront's numeric `uid`; email is a placeholder `user{uid}@example.com`; name/region/channel/device/age-band/opt-in are *deterministically synthesized from the id* (`novamart/onboarding.py` — "The storefront only relays ids, so these are synthesized deterministically"). Downstream jobs treat them as ordinary columns, which matters when the rec model "learns" from them (section 7.4).
- **Accounts beta (UUIDs)**: `POST /accounts` created `accounts` + `account_map` rows (commit `b567d9d`, 2019-11-27). Exactly 30 accounts exist, all created 2019-12-01 16:30 UTC (query on `novamart.accounts`). The two id namespaces are **not castable to each other**; the registered-conversion dashboard initially joined `accounts.account_id::text = orders.user_id::text` and showed near-zero numbers ("FIXME(dec): numbers look low", commit `d6e34c6`) until commit `b975479` mapped accounts→users via shared email.
- **Known test identities**: QA smoke-test user `424242` (14 orders / `139.86`; sessions `qa-smoke` per `docs/dashboard_notes.md`; the only row in `novamart_analytics.test_users`, inserted by `[engineer-backfill:dev]` 2019-11-27) and its account UUID `cc27b436-d6f9-4e84-adaf-e716025dd369` (email `cust424242@gmail.example` in `novamart.accounts`; hard-excluded in commit `adbcb7e`).
- **Partnership-hidden brands**: `lucente` (hidden 2019-10-25, commit `ba1fbfa`, "per partnerships"; 141 orders / `43,335.35` of real revenue is excluded from reports) and `jetem` (hidden 2019-12-15, commit `1169e40`; 5 products, zero sales in the snapshot — queries on `novamart.orders`/`novamart.order_lines` joined to `products`).

### 3.4 Who did what

Two engineers wrote essentially all of it: **Maya Iyer** (app endpoints, idempotency, similar-products widget, digest, fraud-threshold tuning) and **Dev Kapoor** (reports, statements, affinity, pricing, forecasts, dashboards) — `git log` author fields; their ad-hoc investigations also appear in db_queries as `[engineer:maya]` (52 statements) and `[engineer:dev]` (107). "Novamart Platform" did the Jan-2020 platform migration (commits `d398b0d`…`5ae1182`). Deploys are marked by empty `trigger deploy #d2p-novamart` commits — a feature flag flip is "a redeploy, not a code change" (commit `df4ed85` docstring).

---

## 4. Metrics

This is the heart of the tribal knowledge: for every reported number, which table/job/dashboard is the source of truth, and the known reasons it can be "wrong."

### 4.1 Monthly revenue and the finance statements (Phase 1 final goal)

**Producer:** `novamart/jobs/monthly_statement.py`, scheduled monthly at 06:30 local (crontab) / `30 6 1 * *` (Airflow `monthly_statement_dag.py`). For the prior NY-local month it computes:

- `gross = SUM(orders.price) WHERE status = 1` in the local-month UTC window (`local_month_window_utc` in `novamart/jobs/timeutil.py`)
- `fee = SUM(payments.fee)` joined to those status-1 orders — *collected* fees, since commit `a92c96d` (2019-11-02); before that it was the formula `gross * 0.029`
- `net = gross - fee`; appends one row to `statements` (append-only; never rewritten).
- It also computes an `expected_fee` using the rate schedule (2.9% before `FEE_CHANGE_AT` = 2019-11-20 00:00 NY, +$0.30 after; commit `4a58d17`) and logs `statement_fee_mismatch` warnings — 3 such warnings exist in app_events (months 2019-09 delta −0.01, 2019-10 delta +0.14, 2019-11 delta −170.41; the big November delta was the pre-`4a58d17` expectation missing the flat fee, and the booked "audit correction" for November computed to **0.00** once the formula was fixed — see `novamart_analytics.statement_corrections` and the `[engineer-backfill:dev]` INSERT of 2019-12-02 in db_queries).

**The three layers of truth** (`docs/restatement_policy.md`, commit `a576d0d`; view definitions from `novamart_analytics.INFORMATION_SCHEMA.VIEWS`; creation DDL in db_queries by `[engineer-backfill:dev]` 2019-11-02 and 2019-12-09):

| Layer | Surface | October 2019 net | Use when |
|---|---|---|---|
| As published | `novamart.statements` | **1,194,652.79** | reproducing an old board deck |
| Fee-corrected | `novamart_analytics.statements_corrected` = statements overridden by `statement_overrides` | **1,194,652.93** | statement-generation bug fixes only |
| Final restated | `novamart_analytics.statements_final` = corrected − chargebacks by order month | **1,191,085.36** | current finance/external reporting (Redash query 5 / dashboard `statements_final`) |

- The only override row: month 2019-10, `fee 35,679.64 → 35,679.50`, note "Corrected to sum of per-order collected payment fees" (`novamart_analytics.statement_overrides`).
- The only chargebacks: orders 46, 49, 55 (all 2019-10-01), total `3,567.57` (`novamart_analytics.chargebacks`). Caveat a finance person should know: db_queries shows the 2019-12-09 booking was a backfill that selected "first 3 October status-1 orders with price > 700" — i.e. synthesized/representative bookings, not a feed from a processor.
- `statements_final` attributes chargebacks to the **order's month** (NY time), not the booking month (view SQL).

**Why "what was revenue in month X?" has several correct answers:**

1. **Statements are snapshots over mutable rows.** All 3,765 October orders were status 1 when the statement ran on Nov 1 (statement gross = today's all-status October gross `1,230,332.43`); 43 orders were later cancelled (−`10,748.42`) and 27 refunded (−`13,246.69`), so re-running the statement SQL today yields `1,206,337.32` (status breakdown query on `novamart.orders` for the NY October window). Refunded orders *vanish from gross* retroactively rather than appearing as a refund line.
2. **Fraud holds remove revenue from status-1 math.** 12 held orders (status 6, `40,213.29`) are excluded by the `status = 1` filter even though they were paid (query on `novamart.orders`; `novamart/jobs/fraud_score.py` sets status 6).
3. **Gateway refunds never reduce statement gross at all** — they only add negative `payments` rows while the order stays status 1 (`novamart/routers/payments_webhook.py`), so refunds-v2 money is invisible to `statements` (and the fee join picks up `fee = 0` rows harmlessly).
4. **December 2019 is simply missing.** `novamart.statements` ends at 2019-11; job_runs has only 3 `statement_generated` events (2019-10-01, 2019-11-01, 2019-12-01); crontab was retired in Jan 2020 (commit `4bfcbe6`) and Airflow started with `catchup=False` — nothing ever ran on 2020-01-01. If asked, December status-1 gross by the statement's own window is `552,328.93` / 1,756 orders (query on `novamart.orders`, window `2019-12-01 05:00Z → 2020-01-01 05:00Z`), but no published number exists.

### 4.2 Refunds

**Source of truth:** `novamart_analytics.refunds_unified` view + Redash query 1 (`refunds` dashboard), both added 2019-12-23 (commit `a3bffec`; view DDL in db_queries by `[engineer-backfill:dev]`). The view unions three kinds:

- `order_cancelled`: orders status 2 — 54 rows / `13,249.64`
- `order_refunded`: orders status 3 — 28 rows / `13,447.47`
- `gateway_refund`: payments rows with `gross < 0 OR net < 0` — 9 rows / `1,843.59`
(aggregation query on the view)

**Trust caveats:**

- **Webhook replays are triple-counted.** Orders 3762, 3763, 3776 each have identical negative payments on 2019-12-13, -20 and -27 15:30 UTC (rows in `novamart.payments`); the webhook has no idempotency key (`payments_webhook.py` inserts unconditionally, `payment_ref` NULL). True gateway refunds: 3 orders / `614.53`; the view reports 9 / `1,843.59`.
- The `amount` for cancelled/refunded orders is the **current whole-order price** at `updated_at`, not the paid amount at refund time; status flips also *retroactively remove* the order from status-1 revenue (section 4.1).
- There is zero overlap between status-3 orders and negative-payment orders in the snapshot (join query = 0 rows), so no double counting across kinds *yet*, but nothing structurally prevents it.

### 4.3 Daily revenue: report_rows, intraday, and the exec widgets

**Producers:** `daily_report` (06:00 local; yesterday) and `intraday_report` (12:00 & 17:00 local; today so far) write append-only `report_rows` / `report_rows_intraday` snapshots (`novamart/jobs/daily_report.py`, `intraday_report.py`, commit `a2e0013`). Shared rules at HEAD: count item rows from `order_lines` with legacy fallback to `orders` (commit `92596dc`); skip statuses `[0, 2, 3]` (commit `11c0a42`; note status 6 "held" **is counted** — holds don't exist in `EXCLUDED_STATUSES`); exclude `analytics.test_users` (commit `b59f077`), `EXCLUDED_SKUS = [1004856, 1002544]` (commit `83fb3ed`) and `BRAND_DENYLIST = ['lucente','jetem']` (commits `ba1fbfa`, `1169e40`); NY-local day windows DST-correct since commit `102c9b4`.

**Consumers:** Redash `daily_kpis` (query 7) and `revenue_widget` (query 2). Both must pick **only the latest `created_at` version per report_date** and use intraday **only for today** — the first revenue widget (commit `686a5d6`, 2019-12-19) summed every snapshot and double/multi-counted; fixed in commit `3eced24` (2019-12-24). The current `report_rows` has no multi-version dates (0 report_dates with >1 `created_at`), but `report_rows_intraday` has ~2 versions/day by design (2,358 rows since 2019-12-08), so the latest-version discipline still matters.

**Permanent historical artifacts a finance person must know (all verified against `novamart.orders` with the daily-report rules):**

| Date (local) | report_rows says | Truth by same rules | Cause |
|---|---|---|---|
| 2019-11-03 | 123 units / 35,429.68 | +8 orders / +2,985.99 missing | pre-fix DST window ended at 11pm EST; fixed `102c9b4` on 2019-11-05, never backfilled (also `[engineer:dev]` investigation 2019-11-05 in db_queries) |
| 2019-11-15 | 0 units | 0 orders — **real zero-order day** | genuine outage/no sales (orders table has no rows that local day) |
| 2019-11-17 | 487 units / 148,857.07 | 704 units / 223,853.03 | `REPORT_SCAN_CAP = 500` row cap on a 735-order day; fixed `1233af8` on 2019-11-19, never backfilled (job_runs `orders_scanned = 500` for report_date 2019-11-17) |

### 4.4 Best sellers, brand revenue, category revenue (Phase 2)

Authoritative current logic = Redash queries 9 (`best_sellers`), 8 (`brand_revenue`), 6 (`category_revenue`) — identical to the last git versions in `dashboards/` before commit `41e3537`. Decoded (also in `docs/dashboard_notes.md`, commit `a9a4b0b`):

- **Windows are rolling**, anchored to query time: 7×24h for best sellers, 30×24h for brand/category — not calendar weeks/months.
- **Item counting**: `item_orders` CTE = `order_lines` rows UNION legacy `orders` rows that have no lines (commit `92596dc`). A hand query against `orders` alone misattributes multi-line orders (173 orders have ≥2 lines; `orders.product_id` is only the first item and `orders.price` is the whole-order total — line-count query on `novamart.order_lines`).
- **No status filter** — cancelled/refunded/held orders still count on these dashboards. This is the single most common reproduce-by-hand mismatch (`docs/dashboard_notes.md`: "leave order status unfiltered").
- **Exclusions**: user `424242` everywhere; brand_revenue additionally excludes the QA account UUID string (commit `adbcb7e`); brands `lucente`/`jetem` excluded everywhere.
- **Ranking**: best sellers returns `COUNT(*) AS units` but sorts by `revenue` (`docs/dashboard_notes.md`).
- **Category revenue** resolves `products.category` codes through a **versioned taxonomy**: union of `analytics.category_names` (priority 0) and `analytics.category_name_history` (priority 1), picking the latest `valid_from <= order date`. The 2019-12-12 renames (`construction.tools.light*` → `lighting`, `electronics.audio*` → `entertainment`, effective that day, with pre-rename rows backdated) were installed by `[engineer-backfill:dev]` statements in db_queries (commits `2814b3d`, `33054cd`). Unmapped codes fall into `'other'`.
- The nightly `top_sellers` job (`novamart/jobs/top_sellers.py` → `novamart.top_products`, 2,396 rows) is a **different** metric: yesterday only, `status = 1`, counts `orders` rows (not lines), **no** QA/SKU/brand exclusions, ranked by units. Don't reconcile it against the dashboard.

### 4.5 Customers: signups, active, contactable, registered

- **"Signups" barely exist as a concept**: `users` rows are created on first sight of any event with placeholder emails (`ensure_entities`), so `users.created_at` ≈ first-touch, not registration. The only explicit registrations are the 30 accounts-beta rows (section 3.3). Only 40 users ever got a real-looking email, via the now-unwired `POST /users/{id}/email` endpoint (40 `user_email_updated` events in app_events; endpoint added `088a372`, router dropped from `app.py` in `f1217a8`), and all 40 are `@gmail.example` test addresses (`[engineer:maya]` audit 2019-12-04 in db_queries).
- **Active customers — three coexisting definitions** (`docs/metrics_definitions.md`, commit `dd0c8fc`):
  1. `novamart_analytics.kpi_daily.active_customers` (nightly `kpi_daily` job, commit `14726e7`): distinct buyers, trailing 30×24h, `status = 1`, **no** QA/test exclusions. 45 rows, 2019-11-17 → 2019-12-31; e.g. 1,152 on 2019-12-31 (table query).
  2. Exec `daily_kpis` dashboard `customer_days` CTE (Redash query 7): distinct ordering users per NY calendar day, **no status filter**, excludes `424242` and lucente/jetem-only orders.
  3. Board `actives_board` (Redash query 3, commit `2dde4f0`): trailing 30 days, excludes statuses 0/2/3, excludes `analytics.test_users` **and** a large email-heuristic denylist. Most conservative.
  These are three different metrics, not one metric with bugs; never present them as comparable.
- **Contactable customers = 0, always.** The `contactable_users` view (created by `[engineer-backfill:maya]` 2019-12-04, commit `e10cb0c`) requires `marketing_opt_in`, a syntactically valid email, and excludes `example.com/net/org` **and `%.example` domains**. Placeholder emails fail the example.com rule; the 40 "real" emails fail the `%.example` rule → `SELECT COUNT(*) FROM novamart_analytics.contactable_users` = **0**. The `contactable_customers` column on the exec KPI dashboard has therefore never been non-zero.
- **Email digest "recipients" is a vanity number**: `email_digest` counts `users WHERE email NOT LIKE '%@example.com'` = the same 40 test addresses (`novamart/jobs/email_digest.py`; `digest_log.recipients = 40` for all 15 runs). Also note the digest **silently never ran** from its 2019-11-28 launch until 2019-12-17 due to a flag-name mismatch (`DIGEST_ON` vs `ENABLE_DIGEST`, commit `c19a307`; fixed in `8dc520b` then made env-file-robust in `0bd4eac`; first `digest_sent` in job_runs/digest_log = 2019-12-17).
- **Registered conversion** (Redash query 4): counts buyers among users email-mapped from `accounts`; fixed version per commit `b975479`. Remember the UUID↔numeric-id trap if you ever rewrite it.

### 4.6 Funnel and sessions

`novamart/jobs/funnel.py` (nightly 06:20) sessionizes the last day of cart+order events per user with an inactivity gap, writing `analytics.daily_funnel` (53 rows since 2019-11-09). The gap was changed from **30 to 120 minutes** on 2019-12-14 (commit `f915c1b`), so session counts before/after that date are not comparable.

---

## 5. System

### 5.1 Serving app

- FastAPI app `novamart/app.py`; routers wired at HEAD: `catalog`, `carts`, `orders`, `similar`, `payments_webhook`. **Not wired (dead code): `users`, `reports`, `accounts`** — `users`+`reports` were dropped by commit `f1217a8` (2019-10-26, while adding `similar`) and `accounts` by commit `c49a7bb` (2019-12-05, while adding `payments_webhook`); both look like accidental edits since the commit messages don't mention removals. Practical consequence: `GET /reports/brands` (which, note, attributes multi-line order totals to the first product's brand — `novamart/routers/reports.py`) and account creation are currently unreachable.
- `novamart/db.py` logs **every SQL statement** with a source tag to `db_queries.log` → exported to `novamart_logs.db_queries` (3,597,650 lines, 2019-09-16 → 2019-12-31). Actor tags observed: `app` (3.27M), `job` (331k), `engineer:dev` (107), `engineer:maya` (52), `engineer-backfill:dev` (29), `engineer-backfill:maya` (3). The `db_queries_normalized` view re-presents these as BQ-jobs-style rows (view definition in `novamart_logs.INFORMATION_SCHEMA.VIEWS`).
- App JSONL logs → `novamart_logs.app_events` (event counts: `product_viewed` 843,085; `rec_served` 669,190; `cart_item_added` 36,925; `duplicate_payment_ref` 10,766; `order_created` 9,127; `order_callback_replayed` 522; `order_appended` 225; `order_cancelled` 54; `user_email_updated` 40; `account_created` 30; `order_refunded` 28; `price_feed_received` 13; `gateway_refund` 9; `statement_fee_mismatch` 3).
- **Schema management is ad hoc**: `schema.sql` covers only the core 7 tables; `order_lines`, the `payments.payment_ref` column, `report_rows_intraday`, `accounts`, and every `analytics.*` table are created lazily by request handlers/jobs via `CREATE TABLE IF NOT EXISTS` (e.g. `orders.py` runs DDL **on every order callback**) or by engineer backfills (db_queries). When modifying pipelines, never assume `schema.sql` is complete.
- Config: `NOVAMART_DSN`, `NOVAMART_LOG_DIR` (`novamart/config.py`); business constants in `novamart/constants.py` ("Change with care — finance reads the numbers these produce"); feature flags in `deploy/flags.env` (currently only `REC_MODEL_VERSION=2.0.0`), cron flags in `deploy/cron.env` (`ENABLE_DIGEST=1`). CI (`ci/run_ci.py`) boots the app on a scratch DB, exercises view→cart→order, and runs reconcile/daily_report/monthly_statement under `FAKE_NOW`.

### 5.2 Scheduled jobs (Phase 3): what each produces and what breaks when it fails

Schedules: `crontab.txt` (RETIRED Jan 2020, kept for reference) → `airflow/dags/*_dag.py` (commit `4bfcbe6`), same times, all `catchup=False`, `BashOperator` running `python -m novamart.jobs.<job>`. Times below are the local cron times.

| Time | Job | Writes | Blast radius if it fails / quirks |
|---|---|---|---|
| 03:00 | `reconcile` | nothing; logs `duplicate_payment_ref` warnings, capped `RECONCILE_BATCH=200`/night (commits `030d841`, `388370b` "overlaps with backup window") | silent loss of dup-ref visibility; 130 distinct refs are duplicated across orders today (query on `novamart.orders`); filter `status <> 5` references a status that doesn't exist in data |
| 03:30 | `affinity` (v1) | `analytics.product_affinity`, full nightly recompute, −1 sentinel for pairs seen <3 (commits `776d674`, `fef5c96`) | **nothing reads it anymore** — widget moved to v2 (`docs/affinity_lineage.md`); pure zombie compute |
| 03:45 | `affinity_v2` | `analytics.product_affinity_v2` (3,912 rows, 2,964 = 76% sentinel −1) | similar-products widget starves → trending fallback. **Crashed 3 nights (Dec 3–5, 2019)**: `SEASONAL_FACTORS` had only 11 entries, `IndexError` in December (job_runs severity=ERROR stderr; fixed commit `3dbe4d7`). Table rows say `model_version 2.0.1` while serving version is `2.0.0` — naming mismatch only |
| 04:15 | `model_train` | `analytics.model_registry` (17 rows since 2019-12-15), `analytics.model_scores` (948 rows) | nothing user-visible (v4 not served; section 7) |
| 04:45 | `price_suggest` | `analytics.price_suggestions` (500 rows, delete+rewrite) | nothing — shadow only, Phase 2 ON HOLD (commits `894c535`, `cca9b0d`; `docs/pricing_status.md`) |
| 05:15 | `trending` | `analytics.trending_daily` (top 50/day; 2,898 rows since 2019-11-03) | similar-products **fallback source** breaks → widget can return empty; window halved 60→30 days on 2019-12-06 (commit `f563dea`; README's "60-day" note is stale — `docs/trending_notes.md`) |
| 05:45 | `fraud_score` | `analytics.order_risk` (1,631 rows since 2019-12-04); UPDATEs orders to status 6 | revenue-affecting! held orders leave status-1 metrics (section 4.1) |
| 06:00 | `daily_report` | `report_rows` (append snapshot per day) | KPI dashboard + revenue widget lose "yesterday"; historical quirks in section 4.3 |
| 06:15 | `kpi_daily` | `analytics.kpi_daily` | nightly actives series gaps |
| 06:20 | `funnel` | `analytics.daily_funnel` | sessions series gaps; GAP_MIN changed 30→120 on 2019-12-14 (`f915c1b`) |
| 06:30 (1st) | `monthly_statement` | `statements` (append) | **finance statement missing — exactly what happened for 2019-12** (section 4.1) |
| 06:45 | `top_sellers` | `novamart.top_products` | internal ranking only |
| 06:50 | `reorder_forecast` | `analytics.reorder_hints` (200 rows, delete+rewrite) | advisory only; **hints grow as velocity falls** (`hint = 15.6 + 162.4/(velocity+1.8)`, K refit from 141.12 in commit `f85cdd2`); finance must not commit spend on it (`docs/forecast_caveats.md`, README) |
| 07:15 | `email_digest` | `analytics.digest_log` | marketing digest; flag-gating saga in section 4.5 |
| 12:00, 17:00 | `intraday_report` | `report_rows_intraday` | exec "today" number goes stale |
| manual | `warehouse_backfill` | all 32 Postgres tables → BigQuery via `gcloud sql export csv` + `bq load --replace`, driven by `warehouse_manifest.json` (commit `5ae1182`) | warehouse staleness; it is a full-replace snapshot copier, not CDC |

Job health: query `novamart_logs.job_runs` (975 INFO / 3 ERROR events; the only ERRORs are the affinity_v2 December crashes). Ops rerun helper for discounted-revenue recomputes: `scripts/rerun_kpis.py` + `novamart/jobs/discounts.py` — note the function default `cap=0.40` is the *legacy* cap; the finance-approved value is `constants.DISCOUNT_CAP = 0.25` and callers must pass it (commit `35c581e`).

### 5.3 Platform (Jan 2020 migration)

`docs/data-access.md` (commit `d398b0d`): serving Postgres = Cloud SQL `novamart-prod-replica`; warehouse = BigQuery `novamart-warehouse` (datasets `novamart` = public app tables, `novamart_analytics`, `novamart_logs`); dashboards = Redash on `novamart-ops` (via IAP tunnel in real prod; locally port 5054); schedules = Airflow on `novamart-ops`. The Redash data source is the **Postgres replica** (`/api/data_sources` → type `pg`), so dashboard SQL is Postgres dialect even though analysts also get BigQuery.

---

## 6. Data

### 6.1 Dataset inventory (from `bq ls` + queries)

**`novamart` (app tables, 12):** `users` (38,950), `products` (81,018), `cart_items` (36,938), `orders` (9,127; statuses now 1=paid 9,033 / 2=cancelled 54 / 3=refunded 28 / 6=held 12), `order_lines` (2,284; exists only since 2019-11-22), `payments` (9,361; includes 9 negative refund rows; `payment_ref` column added later and NULL on old rows), `report_rows` (6,923), `report_rows_intraday` (2,358), `statements` (3), `top_products` (2,396), `accounts` (30), `account_map` (30).

**`novamart_analytics` (20 tables + 4 views):** tables `product_affinity`, `product_affinity_v2`, `model_registry`, `model_scores`, `rec_decision_log` (667,850), `trending_daily`, `order_risk`, `price_history` (1,400), `price_suggestions` (500), `reorder_hints` (200), `kpi_daily` (45), `daily_funnel` (53), `digest_log` (15), `test_users` (1), `category_names` (135), `category_name_history` (6), `blank_brand_products` (5,972), `chargebacks` (3), `statement_overrides` (1), `statement_corrections` (1); views `contactable_users`, `refunds_unified`, `statements_corrected`, `statements_final` (definitions in `INFORMATION_SCHEMA.VIEWS`).

**`novamart_logs`:** `db_queries` (3,597,650), `app_events`, `job_runs`, view `db_queries_normalized`.

### 6.2 Lineage (writer → table → reader)

- `orders` endpoint → `orders`/`order_lines`/`payments` → read by daily/intraday reports, top_sellers, trending, kpi_daily, funnel, fraud_score, price_suggest, reorder_forecast, monthly_statement, affinity_v2 conversion check, model_train labels, and 7 of 9 dashboards.
- `report_rows`(+`_intraday`) → `daily_kpis` + `revenue_widget` dashboards only (latest-version semantics required).
- `statements` → `statement_overrides` → `statements_corrected` → (+`chargebacks`) → `statements_final` → `statements_final` dashboard.
- `cart_items` → affinity v1/v2 → `product_affinity(_v2)` → similar widget (v2 only) → `rec_decision_log` → model_train → `model_scores` → (nothing, flag off).
- `orders` → fraud_score → `order_risk` + status-6 UPDATEs → back into every status-filtered metric.
- Postgres → `warehouse_backfill` → BigQuery (full replace, 32 tables in `warehouse_manifest.json`).

### 6.3 Data quirks that bite queries

- **`orders.price` is an order total; `orders.product_id` is the first line only.** Always use the `item_orders` CTE pattern (order_lines UNION legacy fallback) for per-product/per-brand work (commit `92596dc`; Redash queries 6/8/9).
- **Statuses**: 0 = created-unpaid transient, 1 = paid, 2 = cancelled, 3 = refunded, 6 = fraud-held. Historical trap: cancelled was briefly **4** (commit `ba1fbfa` shows `STATUS_CANCELLED = 4`) before being aligned to 2 in commit `8f19718`; no status-4/5 rows exist in the snapshot.
- **Timestamps are UTC; business days/months are NY-local** (`timeutil.py`). The 2019-11-03 DST fall-back day is 25h long — any hand query using `date + 24h` windows is wrong for that day (commit `102c9b4`).
- **Emails are 99.9% placeholders** (`user{uid}@example.com`); profile attributes are hash-synthesized from ids (`onboarding.py`). Any demographic/email-based analysis is analyzing a hash function.
- **130 payment_refs appear on >1 order** (pre-idempotency legacy; reconcile logs 10,766 cumulative `duplicate_payment_ref` warnings but caps at 200/night and fixes nothing).
- **Append-only snapshot tables** (`report_rows`, `report_rows_intraday`, `statements`) vs **delete-and-rewrite nightly tables** (`product_affinity*`, `model_scores`, `price_suggestions`, `reorder_hints`, `trending_daily` per-day) — the latter keep **no history**, so you cannot audit yesterday's recommendations/suggestions from the tables; use `rec_decision_log`/`job_runs` instead.
- The warehouse is a point-in-time full copy (section 5.2); "now()-relative" dashboard windows evaluated today return empty/odd results against 2019 data — judge dashboard logic by its SQL, not its current rendering.

---

## 7. Experimentation

### 7.1 Recommendation system version history (`docs/rec_versions.md` is literally "TBD"; real history below)

| Version | What | Status | Evidence |
|---|---|---|---|
| 1.0.0 | co-cart affinity (`analytics.product_affinity`), widget launched 2019-10-26 | retired for serving; job still runs nightly (zombie) | commits `776d674`, `f1217a8`; `docs/affinity_lineage.md` |
| 2.0.0 | affinity v2: conversion-weighted (cart=1, order=3), same-category ×1.15 boost, price-ratio dampener ×0.7, monthly seasonal factor | **live default** (`deploy/flags.env REC_MODEL_VERSION=2.0.0`) | commit `89666bf`; `novamart/jobs/affinity_v2.py`; version dispatch in `similar.py` (commit `df4ed85`) |
| 2.0.1 | the *row-stamp* inside `product_affinity_v2` after the December crash fix — not a serving version | cosmetic mismatch | commit `3dbe4d7`; `docs/affinity_lineage.md` |
| 4.0.0 | nightly logistic model (`model_train.py`) scoring affinity-v2 pairs | **flag-gated, NOT live**; README's "Serving is version 4.0.0" is aspirational — the flag still says 2.0.0 | commit `a1946ff`; `deploy/flags.env` |

### 7.2 The random arm (the company's only real experiment infrastructure)

5% of users (`sha256(uid) % 20 == 0`) get uniformly random recommendations to collect unbiased training data (commit `df4ed85`; `similar.py::in_random_arm`). Every serve is logged to `analytics.rec_decision_log` with `intended_version`, `effective_version`, `rec_source`, `fallback_reason`, `arm`. First random-arm rows: 2019-12-06 (daily aggregation of `rec_decision_log`).

**Known data gap:** the 2019-12-17 refactor (commit `30e8907`) dropped the decision-log INSERT on the random path; restored 2019-12-19 (commit `a00f24c` "missed in refactor"). `rec_decision_log` has **zero `arm='random'` rows on 2019-12-18** (daily aggregation), and overall the table has ~1,340 fewer rows than app_events `rec_served` (667,850 vs 669,190). Any model/analysis using random-arm data must treat 2019-12-18 as missing.

### 7.3 Does the widget actually work? Mostly it serves fallbacks

Aggregating all 667,850 decisions (`rec_decision_log` GROUP BY versions/source/reason):

- v1 era: 326,186 fallback (`no_scores`) vs 66,444 affinity-served → **83% fallback**.
- v2 era (non-random): 182,868 fallback-`no_scores` + 25,091 fallback-`cache` vs 52,695 model-served (31,268 fresh + 21,427 cache) → **~75% fallback to trending**.
- Root cause: 76% of affinity pairs are below the `MIN_PAIRS = 3` graduation gate and carry the **−1 sentinel** ("NOT a negative preference — serving must filter < 0", `affinity.py` docstring, commit `fef5c96`); 2,964 of 3,912 v2 rows are sentinels (table query).
- The 25,091 `fallback_reason='cache'` rows are a scar from commit `a00f24c`, which cached **empty** score lists for 6h; fixed by commit `8ed2971` (cache only non-empty, epoch-invalidate on nightly refresh, and only serve rows from the latest `updated_at` batch).

So the honest judgment for Phase 3: the "ML system" is primarily a trending-products widget with an affinity-ranked head for popular pairs.

### 7.4 Model v4: trained nightly, never served, and methodologically shaky

`model_train.py` (04:15 nightly since 2019-12-15; 17 registry rows, train_rows 4,197 → 14,411):

- **Label leakage / weak labels**: `converted = EXISTS(order by same user with created_at > exposure ts)` — any later purchase of *anything*, ever, counts as conversion for that exposure.
- **Features are 5, not 9**: `[n_items, base_price, base_popularity, account_age, organic_user]`; `opt_in` is fetched but "not yet in the vector (calibration pending)" (code comment), and README's claimed "user region affinity, device mix, stock level" features don't exist in the code (README `## Rec model v4` vs `model_train.py` — README overstates).
- **Scoring is a no-op for ranking**: `model_scores.score = affinity_v2_score × (1 + 0.1 × w)` where `w` is one scalar coefficient — a constant multiplier that preserves affinity-v2 order exactly. Flipping `REC_MODEL_VERSION` to 4.0.0 would change *nothing* about ranking except reading a smaller table (948 rows).
- Coefficients are unstable day-to-day (e.g. `base_price` coef swings −1.36 → +0.39 → −0.53 across December; `model_registry.coef_json`), consistent with noisy labels.

### 7.5 Other experiments and tuning history

- **Dynamic pricing**: phase-1 shadow job writes `price_suggestions` nightly (±5% nudges, top-500 by 14-day paid units); **phase 2 serving is ON HOLD per exec/legal review** since 2019-12-02 and nothing reads the table — verified by repo grep, and by absence of SELECTs in db_queries (commits `894c535`, `cca9b0d`; `docs/pricing_status.md`).
- **Fraud threshold tuning**: 0.90 at launch (commit `e4656fb`, 2019-12-03) → 0.70 (commit `53f6f6c`, 2019-12-05) → 0.85 + **manual release of held orders under $2,600** (commit `1cb8721`, 2019-12-29; the actual release is the `[engineer-backfill:maya]` UPDATE in db_queries). Score = `min(price/3000, 1) × (1 + 0.15·new_account + 0.15·high_velocity)` — i.e. mostly a price threshold: a $3,000 order scores 1.0 regardless of signals. 1,631 orders scored; 12 currently held, all ≥ $2,655 (queries on `order_risk`, `orders`).
- **Trending window**: 60 → 30 days on 2019-12-06 (commit `f563dea`) — explains the December churn speedup; job_runs logged `window_days: 60` through 2019-12-06 and 30 after (`docs/trending_notes.md`).
- **Funnel session gap**: 30 → 120 min on 2019-12-14 (commit `f915c1b`).
- **Reorder forecast refit**: K 141.12 → 162.4 on 2019-12-21 (commit `f85cdd2`) — a one-constant retune, not a model change (`docs/forecast_caveats.md`).

---

## 8. Glossary

| Term | Meaning | Evidence |
|---|---|---|
| **order status 0/1/2/3/6** | created-unpaid / paid / cancelled / refunded / fraud-held; 4 was briefly "cancelled" in Oct 2019, 5 unused | `constants.py`; commits `8f19718`, `d87cb3d`, `e4656fb`; status counts on `novamart.orders` |
| **order_lines** | per-item rows for merged same-session orders (since 2019-11-22); `orders` row keeps first product + running total | commit `5d1300d`; min(created_at) in `novamart.order_lines` |
| **item_orders CTE** | canonical "count items with legacy fallback" pattern all exec dashboards use | commit `92596dc`; Redash queries 6/8/9 |
| **payment_ref** | gateway idempotency key; unique per callback; 130 legacy refs still duplicated across orders | commit `b676969`; reconcile warnings in app_events |
| **statements / statements_corrected / statements_final** | published snapshot / + fee overrides / + chargebacks = current finance truth | `docs/restatement_policy.md`; view DDL in db_queries 2019-12-09 |
| **report_rows / report_rows_intraday** | append-only daily / intraday sales snapshots; consumers must take latest `created_at` per date | commits `a2e0013`, `3eced24` |
| **EXCLUDED_SKUS / BRAND_DENYLIST / test_users / 424242** | report-cleanup filters: test SKUs 1004856+1002544; hidden brands lucente+jetem; QA smoke user | commits `83fb3ed`, `ba1fbfa`, `1169e40`, `b59f077`; `analytics.test_users` |
| **active customers (×3)** | kpi_daily rollup vs daily_kpis per-day vs actives_board — three different definitions | `docs/metrics_definitions.md` |
| **contactable_users** | opt-in + real-email view; currently empty (=0) | view SQL; count query |
| **affinity sentinel −1** | "not enough data" marker for pairs seen <3; serving must filter `score >= 0` | commit `fef5c96` |
| **random arm** | 5% uniform-random rec traffic for unbiased training data | commit `df4ed85` |
| **REC_MODEL_VERSION** | deploy-time flag choosing rec table; 2.0.0 live, 4.0.0 dormant | `deploy/flags.env`; `similar.py` |
| **reorder hints** | advisory inverse-velocity heuristic; NOT finance-grade | README; `docs/forecast_caveats.md` |
| **FEE_RATE / FEE_FLAT / FEE_CHANGE_AT** | 2.9%; +$0.30 per transaction from 2019-11-20 | commits `12e1c68`, `4a58d17` |
| **LOCAL_TZ** | America/New_York; all report/statement windows are local, data is UTC | `constants.py`; `timeutil.py` |
| **engineer / engineer-backfill tags** | ad-hoc human SQL vs human data-mutating one-offs in the statement log | actor aggregation on db_queries |
| **trigger deploy #d2p-novamart** | empty commit = production deploy marker | `git log` |
| **crontab.txt (retired) / Airflow DAGs** | schedule source of truth before/after Jan 2020 | commit `4bfcbe6` |

---

## Appendix

### A. How to answer "what was revenue in month X, and why" (worked procedure)

1. **Current finance answer**: `SELECT * FROM novamart_analytics.statements_final WHERE month = 'X'` (Redash `statements_final`). For 2019-10: gross `1,226,764.86`, fee `35,679.50`, net `1,191,085.36`.
2. **"Match the old deck"**: `novamart.statements` (2019-10 net `1,194,652.79`, created 2019-11-01 10:30Z).
3. **Explain any delta** via: `statement_overrides` (fee-rounding correction, commit `a92c96d` context), `chargebacks` (orders 46/49/55, `3,567.57`, attributed to order month), post-publication status flips (Oct: 43 cancels + 27 refunds = `23,995.11` that a fresh status-1 query won't show), fraud holds (status 6 excluded), gateway refunds (don't touch gross at all), and for 2019-12: **no statement exists** — compute `SUM(price) WHERE status=1` over `2019-12-01 05:00Z → 2020-01-01 05:00Z` = `552,328.93` / 1,756 orders and label it unofficial.
4. Expect `statement_fee_mismatch` warnings in app_events as the audit trail of fee-formula drift (3 instances; Nov delta −170.41 was the flat-fee blind spot, remediated by commit `4a58d17` with a zero-delta booked correction).

### B. Dashboard-by-dashboard trust notes (Redash ids)

| Dashboard (query id) | Trust at face value? | Caveats |
|---|---|---|
| statements_final (5) | **Yes** — canonical finance | chargebacks are backfill-booked (db_queries 2019-12-09); Dec 2019 missing |
| refunds (1) | **No** | gateway webhook replays triple-count (orders 3762/3763/3776); amounts are current order totals |
| daily_kpis (7) | Mostly | revenue inherits report_rows artifacts (Nov 3 / Nov 17); `contactable_customers` always 0; actives have no status filter |
| revenue_widget (2) | Yes since 2019-12-24 | before commit `3eced24` it double-counted intraday snapshots — don't trust screenshots older than that |
| best_sellers (9) | Yes, with definition | rolling 7×24h; **no status filter**; sorted by revenue not units; QA/brand exclusions |
| brand_revenue (8) | Yes, with definition | 30d rolling; excludes 424242 + QA UUID string; lucente (`43,335.35` of real revenue) & jetem hidden |
| category_revenue (6) | Yes, with definition | versioned taxonomy; `other` = unmapped codes; renames effective 2019-12-12 |
| actives_board (3) | Yes — most-cleaned actives | definition differs from both other actives metrics; email heuristics operate on placeholder emails |
| registered_conversion (4) | Yes since commit `b975479` | pre-fix version joined UUIDs to numeric ids (near-zero result); beta = 30 accounts incl. QA |

### C. Incident/change timeline (dates are commit dates / log timestamps)

- 2019-09-15 initial import (`2da4141`); 2019-09-25 first traffic (orders/users min created_at).
- 2019-10-01 lucente catalog import begins (`docs/dashboard_notes.md`); 2019-10-08 test SKUs excluded (`83fb3ed`); 2019-10-15 payment_ref idempotency (`b676969`) after dup-ref investigation (`[engineer:maya]` db_queries 2019-10-15); 2019-10-21 blank-brand repair + snapshot table (`ea0e97b`, backfill); 2019-10-25 lucente hidden (`ba1fbfa`); 2019-10-26 similar widget ships, **users/reports routers silently dropped** (`f1217a8`); 2019-10-28 cancel endpoint, status 4→2 (`8f19718`).
- 2019-11-01 Oct statement published with formula fee (mismatch warning); 2019-11-02 collected-fee fix (`a92c96d`) + Oct override backfilled; 2019-11-03 DST undercount (fixed `102c9b4` on 11-05); 2019-11-15 **zero-order day**; 2019-11-16/17 order surge, 11-17 report capped at 500 rows (fixed `1233af8` on 11-19, no backfill); 2019-11-18 cancelled/refunded excluded from reports (`11c0a42`); 2019-11-20 processor fee +$0.30 (`12e1c68`); 2019-11-22 same-session merge + order_lines born (`5d1300d`); 2019-11-27 QA exclusions (`b59f077`), accounts endpoint (`b567d9d`); 2019-11-28 digest launched **but silently disabled by flag-name bug** (`c19a307`); 2019-11-30 category dashboard + mapping backfill (`2814b3d`).
- 2019-12-01 30 beta accounts created; Nov statement published (−170.41 fee mismatch); 2019-12-02 flat-fee expectations + zero-delta Nov correction (`4a58d17`), affinity v2 (`89666bf`), pricing phase 2 held (`cca9b0d`); 2019-12-03..05 affinity_v2 crashes nightly (IndexError; job_runs ERRORs; fixed `3dbe4d7`); 2019-12-04 fraud scoring live at 0.90 (`e4656fb`), contactable_users view (`e10cb0c`); 2019-12-05 threshold→0.70 (`53f6f6c`), order_lines counting in reports/dashboards (`92596dc`), gateway refund webhook + **accounts router silently dropped** (`c49a7bb`); 2019-12-06 rec version dispatch + random arm (`df4ed85`), trending 60→30d (`f563dea`); 2019-12-08 intraday snapshots (`a2e0013`); 2019-12-09 digest flag fix (`8dc520b`), chargebacks + statements_final (`cd559d3` + backfill); 2019-12-11 board actives (`2dde4f0`); 2019-12-12 taxonomy renames (`33054cd` + backfill); 2019-12-13/20/27 gateway-refund webhook replays (payments rows); 2019-12-14 funnel gap 120m (`f915c1b`), model v4 training (`a1946ff`); 2019-12-15 jetem hidden (`1169e40`); 2019-12-16 digest reads cron.env directly (`0bd4eac`); 2019-12-17 first digest actually sent (digest_log), similar refactor **drops random-arm logging** (`30e8907`); 2019-12-18 random-arm data gap; 2019-12-19 logging restored + empty-list caching bug (`a00f24c`), buggy revenue widget (`686a5d6`); 2019-12-21 conversion dashboard fixed (`b975479`), reorder K refit (`f85cdd2`); 2019-12-23 refunds_unified (`a3bffec`); 2019-12-24 revenue widget fixed (`3eced24`); 2019-12-26 cache epoch invalidation (`8ed2971`); 2019-12-29 threshold→0.85 + **manual release UPDATE** (`1cb8721`; db_queries).
- 2020-01-01 **December statement never runs**; 2020-01-02..05 platform migration: docs (`d398b0d`), dashboards→Redash (`41e3537`), crontab→Airflow (`4bfcbe6`), warehouse backfill (`5ae1182`).

### D. Where every number was verified (intermediate artifacts in this directory)

- `git_log.txt` — full commit list; `key_commits.txt` — 55 key diffs dumped via `git show`.
- `old_dashboards/*.sql` — the 9 dashboard SQL files recovered from git (`git show 41e3537^:dashboards/...`); byte-equivalent to current Redash queries 1–9.
- `redash_queries.txt` — Redash API dump of all 9 queries + data source.
- `backfill_queries.txt` / `engineer_queries.txt` — all `engineer-backfill:*` (32) and `engineer:*` (159) statements from db_queries.
- `bqq.py` — the REST helper used for every warehouse query cited above (the stock `bq` CLI crashes on multi-UNION results against the emulator; single-table `bq query` works).

### E. Safe-modification checklist for the batch pipelines (Phase 3 final goal)

1. Schedules live in `airflow/dags/` (crontab.txt is dead); ordering is implicit by clock time — e.g. affinity_v2 (03:45) must precede widget cache epoch bumps and model_train (04:15), and daily_report (06:00) must precede kpi dashboard reads; there are **no** Airflow dependencies encoded, only times.
2. Nightly tables are delete-and-rewrite; if you need history, snapshot before changing (`product_affinity*`, `model_scores`, `price_suggestions`, `reorder_hints`).
3. Anything touching `orders.status` changes finance numbers retroactively (sections 4.1–4.2). Treat `fraud_score`'s UPDATE as a finance-impacting write.
4. Serving reads `deploy/flags.env` from the process working directory (`similar.py::intended_version` uses a relative path) — run the app from repo root or the flag silently defaults to 2.0.0.
5. Keep the `score >= 0` sentinel filter and the `updated_at = MAX(updated_at)` batch filter in any new consumer of affinity/model tables (commits `fef5c96`, `8ed2971`).
6. If you fix the gateway-refund webhook, dedupe on an idempotency key *and* decide the status-flip policy; both halves are currently missing (`payments_webhook.py`).
7. Remember the daily report's exclusion set (statuses 0/2/3, test_users, SKUs, brands) is duplicated in code and dashboards; change both or they diverge (constants vs Redash SQL).
8. The December-statement gap shows migrations need an explicit "did the monthly job run?" check — `SELECT MAX(month) FROM novamart.statements` is the one-liner.
