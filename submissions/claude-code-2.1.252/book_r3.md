# Novamart Tribal Knowledge

**Run ID:** `ed8c92ad-efd2-4c55-995a-89f684646955` · **Prepared:** 2026-08-27 (started 17:09:38 IST) · **Sources:** repo `<workspace>/novamart` @ `2ae79e2`; BigQuery project `<warehouse-project>` (datasets `novamart`, `novamart_analytics`, `novamart_logs`); Redash `<redash-url>` (read-only). Every claim below cites a commit, table/view, dashboard, query, or log evidence. Extra depth is in the Appendix.

---

## 1. Summary

Novamart is a FastAPI + Postgres marketplace (README.md @ `2da4141`) that operated Sep 25 – Dec 31, 2019 in the data, then froze at a Jan 2020 platform migration: serving Postgres was copied into BigQuery (`novamart.jobs.warehouse_backfill`, commit `2ae79e2`), cron schedules became Airflow DAGs (`43e54a1`), and the repo's `dashboards/*.sql` became nine Redash dashboards (`57ea43a`) that still point at the serving Postgres replica (Redash data source 1, "novamart serving (Cloud SQL)"), not BigQuery.

The company's numbers are produced by a single service plus ~16 nightly cron jobs, and almost every number carries history you must know before trusting it:

- **Monthly revenue** lives in three layers: as-published snapshots (`novamart.statements`), override-corrected (`novamart_analytics.statements_corrected`), and chargeback-restated (`novamart_analytics.statements_final` — the current finance surface, per docs/restatement_policy.md @ `a576d0d`). October 2019 net is 1,194,652.79 → 1,194,652.93 → 1,191,085.36 across those layers (verified by query against all three).
- Known unfixed distortions remain **inside** even the restated numbers: ~$58.8k of duplicate October orders from the pre-idempotency era (130 duplicated `payment_ref`s, verified in `novamart.orders`), ~$40.3k of internal test-SKU revenue (product 1004856), and three orders each triple-refunded by a replayed gateway webhook that never flips order status.
- **Active customers** has three coexisting definitions (docs/metrics_definitions.md @ `dd0c8fc`) that disagree by design — and the "board" definition reproduces to **zero** against current data because its email heuristic excludes the placeholder `@example.com` addresses that all 38,910 users carry.
- **ML systems**: the similar-products widget serves affinity-v2 scores under flag `REC_MODEL_VERSION=2.0.0` (deploy/flags.env), falls back to trending for ~75–80% of requests (verified from `app_events.rec_served`), and the "trained v4 model" (`model_train.py`) only rescales affinity-v2 scores by a global constant — its ranking is identical to v2. Trending and the fallback path recommend the internal test SKUs to real customers (ranks #2–3 in `trending_daily` on 2019-12-31).
- **December 2019 has no statement row** — the migration killed the Jan 1 run. Computed from the warehouse: gross 552,328.93, collected fee 16,600.26, net 535,728.67 (1,756 status=1 orders, ET month window).

## 2. Why this project

This document exists to transfer the unwritten operating knowledge of Novamart's data systems to someone who must (a) answer "what was revenue in month X, and why" the way a tenured finance/data person would, (b) explain any dashboard number including when not to trust it, and (c) judge whether the ML systems work and safely modify the batch pipelines. The knowledge is scattered across 112 commits (git log), nine internal docs written in late Dec 2019 (docs/), a 3.6M-line database statement log (`novamart_logs.db_queries`), job-run history (`novamart_logs.job_runs`), app events (`novamart_logs.app_events`), and a small but decisive trail of 32 manual production mutations by two engineers (`db_queries_normalized`, actors `engineer-backfill.dev/maya@novamart.sim`). None of it is in one place; most of the dangerous facts (silent router unmounts, unfixed duplicates, structurally-zero metrics) are in **no** doc at all and were established here by cross-checking code, logs, and warehouse data.

## 3. Business understanding

### What the business is
A retail marketplace. Customers browse products (`GET /products/{pid}`, routers/catalog.py), add to carts (`POST /cart`, routers/carts.py), and pay through an external **payment gateway** which calls back `POST /orders` (routers/orders.py) — the order row is *created by the payment callback*, not by checkout. Product and price data arrive from vendors via a weekly-ish price feed (`POST /catalog/prices`; 13 `price_feed_received` events Oct 7–Dec 30 in `app_events`). Users and products are auto-created on first sight with deterministic placeholder attributes (novamart/onboarding.py): every user starts with email `user{id}@example.com`, and region/channel/device/age/opt-in are synthesized from the id.

### Operating timeline (from git log + warehouse)
- **Sep 25**: first order (single order for 9.99; `novamart.orders` min `created_at`). Traffic ramps Oct 1.
- **Oct 1**: large **lucente** catalog import begins (first lucente order Oct 1; docs/dashboard_notes.md @ `a9a4b0b`). Lucente is later hidden from reports "per partnerships" (`ba1fbfa`, Oct 25) but its $42,853.23 of paid revenue stays in the statements.
- **Oct 1–15**: the **duplicate-order era**. Order callbacks were not idempotent until `b676969` (Oct 15); replayed gateway callbacks created 155 extra order rows across 130 payment_refs, all in October (verified: `SELECT payment_ref ... HAVING COUNT(*)>1` on `novamart.orders`).
- **Nov 15**: **checkout outage** — 27,661 product views and 2,136 cart adds but **zero** `order_created` events all day (`app_events`); the daily report for Nov 15 legitimately shows 0 (`job_runs`: `orders_scanned: 0`).
- **Nov 16–17**: flash-sale surge (401 and 735 orders; `novamart.orders` by ET day). The Nov 17 daily report undercounted by ~$75k due to a 500-row scan cap (see §4).
- **Nov 20**: processor fee changes to 2.9% + $0.30 per transaction (`12e1c68`).
- **Nov 22**: multi-item orders begin — same-session callbacks within 15 minutes merge into one order; `order_lines` table appears (`5d1300d`; first row 2019-11-22 in `novamart.order_lines`).
- **Dec 1**: registered-accounts beta: 30 accounts created in a single batch at 16:30 UTC (`novamart.accounts`; 30 `account_created` events).
- **Dec 3**: fraud burst — 8 orders of 2,999.99–5,999.98 placed 14:01–17:46; auto-held next morning by the new fraud job (`novamart_analytics.order_risk`; orders now status 6).
- **Dec 8+**: intraday reporting (12:00/17:00 ET snapshots) feeds an exec revenue widget.
- **Jan 2020**: migration; data frozen at Dec 31.

### People (from commit authorship and query-log actors)
- **Maya Iyer** (`maya@novamart.sim`) — app/service side: idempotency, cancel/refund endpoints, accounts, webhook, fee change, order merging.
- **Dev Kapoor** (`dev@novamart.sim`) — jobs/reporting/analytics side: daily report fixes, statements, dashboards, backfills, and most manual production mutations (`engineer-backfill.dev@novamart.sim` in `db_queries_normalized`).
- "Novamart Platform" — deploy triggers (`trigger deploy #d2p-novamart` commits carry no code) and the Jan 2020 migration commits.

## 4. Metrics

### 4.1 Monthly revenue ("what was revenue in month X, and why")

**Definition (the statement job):** `novamart/jobs/monthly_statement.py` runs on the 1st (06:30 ET; crontab.txt / `monthly_statement_dag.py`) for the prior **America/New_York calendar month** (constants.LOCAL_TZ; timeutil.local_month_window_utc): `gross = SUM(orders.price) WHERE status = 1`, `fee = SUM(payments.fee)` joined to those orders, `net = gross − fee`, appended to `novamart.statements`. Status is read **as of run time**, so later refunds/cancels/holds are not reflected in the published snapshot.

**The three-layer answer (docs/restatement_policy.md @ `a576d0d`, verified against warehouse):**

| Month | As published (`novamart.statements`) | Corrected (`…statements_corrected`) | Final (`…statements_final`) |
|---|---|---|---|
| 2019-09 | gross 2,702.00 / fee 78.36 / net 2,623.64 / 12 orders | same | same |
| 2019-10 | 1,230,332.43 / 35,679.64 / **1,194,652.79** / 3,765 | fee 35,679.50 / net **1,194,652.93** | gross 1,226,764.86 / net **1,191,085.36** |
| 2019-11 | 1,101,397.01 / 32,110.92 / **1,069,286.09** / 3,582 | same | same |
| 2019-12 | **no row** (migration killed the Jan 1 run) | — | — |

Why October moved twice:
1. The Nov 1 run used the pre-fix formula `fee = gross × 2.9%` (fixed the next day by `a92c96d`, "use collected per-order fees"). Finance booked an override row (INSERT into `analytics.statement_overrides` on 2019-11-02 by `engineer-backfill.dev`, visible in `db_queries_normalized`): fee 35,679.50, net 1,194,652.93. `statements_corrected` = statements overlaid with overrides.
2. On Dec 9, three October chargebacks totaling 3,567.57 were booked (`analytics.chargebacks`; the backfill INSERT selected the first 3 October status=1 orders with price > 700 — see backfill audit in Appendix A.4). `statements_final` subtracts chargebacks (by original order month) from gross and net, giving 1,191,085.36.

November's Dec 2 "audit correction" (`4a58d17`, `analytics.statement_corrections`) has **delta 0** — the Nov statement already used collected fees, so nothing changed; the row only documents the check.

**Every statement run warned.** All three runs emitted `statement_fee_mismatch` (`app_events`): Sep −0.01 (rounding), Oct +0.14 (per-order rounding of 2.9%), Nov −170.41 — the expected-fee formula didn't yet include the Nov 20 flat $0.30 (`12e1c68`); `4a58d17` fixed the expectation with `FEE_CHANGE_AT = 2019-11-20 00:00 ET`.

**Known distortions still inside the "final" numbers** (nothing in the restatement chain touches these):
- **October duplicates, ~+$58,828.24**: 151 of the 155 duplicate-callback order rows are still status=1 with payments rows (verified). They are inside gross 1,230,332.43 and were never removed; `reconcile` (jobs/reconcile.py) only *logs* `duplicate_payment_ref` warnings — 10,766 of them across the period (`app_events`).
- **Test-SKU revenue, ~+$40,304.68**: product 1004856 "Internal Test #4856" (brand `internal`, category `qa.test`, $9.99 — `novamart.products`) has 322 paid units by ~327 distinct users; the statement job has **no** SKU/brand/test-user filter.
- **Replayed gateway refunds**: orders 3776/3763/3762 each have 3 negative payments rows (Dec 13/20/27 15:30 — a weekly webhook replay; `routers/payments_webhook.py` has no idempotency) and remain **status=1**, so their full price is still in gross and their refunds never reduce any statement.
- **Fraud-held orders drop out of gross**: status 6 ≠ 1, so the $40,213.29 currently held (12 orders) is excluded from statement gross — but *included* in the daily report (below), a permanent reconciliation gap between the two surfaces.

**December 2019** (no statement exists): computed from the warehouse with the statement's own definition — gross **552,328.93**, collected fee **16,600.26**, net **535,728.67**, 1,756 orders (ET window 2019-12-01 05:00Z → 2020-01-01 05:00Z, current statuses).

### 4.2 Daily revenue (report_rows and its scars)

`novamart/jobs/daily_report.py` (06:00 daily) aggregates *yesterday's ET day* per product into `novamart.report_rows`: item rows from `order_lines` with legacy fallback to `orders` (`92596dc`), excluding statuses [0,2,3], SKUs [1004856, 1002544], brands lucente/jetem, and `analytics.test_users` members. Each filter has a start date — stored rows were **never backfilled** after rule changes:

| Date | Stored report is wrong because | Evidence |
|---|---|---|
| pre-Oct 25 | includes lucente (denylisted `ba1fbfa`) | recompute delta up to −24k on Oct 1 |
| pre-Nov 18 | includes later-cancelled/refunded orders (statuses `[0]`→`[0,2,3]` in `11c0a42`) | recompute deltas |
| **Nov 3** | DST fall-back: window was `local midnight + 24h`, missing an hour (fixed `102c9b4` Nov 5) | stored 35,429.68 vs actual 38,415.67 |
| **Nov 17** | `fetchmany(REPORT_SCAN_CAP=500)` scan cap on a 735-order day (fixed `1233af8` Nov 19) | stored 487 units/148,857.07 vs actual 704/223,853.03 — **~$75k missing** |
| Nov 15 | correctly zero — checkout outage (see §3) | `job_runs` `orders_scanned: 0` |
| Dec 31 | **no row at all** — Jan 1 run never happened | `report_rows` max report_date = 2019-12-30 |

Note the constant `REPORT_SCAN_CAP` still sits in constants.py with a comment claiming the report uses it — it no longer does.

### 4.3 Active customers — three coexisting definitions

Per docs/metrics_definitions.md (@ `dd0c8fc`), verified in code and data:

1. **Nightly rollup** `novamart_analytics.kpi_daily.active_customers` (jobs/kpi_daily.py, since `14726e7` Nov 16): trailing 30×24h distinct buyers, status=1, **no exclusions** — so QA/test buyers count. Dec 31 value: **1,152**.
2. **KPI dashboard** (Redash `daily_kpis`, query 5): distinct ordering users per **ET day** (last 14 days), **no status filter**, excludes user 424242 and brands lucente/jetem.
3. **Board deck** (Redash `actives_board`, query 1): trailing 30d, excludes statuses [0,2,3], `analytics.test_users`, and any user whose email domain/localpart looks internal or fake — **including `example.com` and `%.example`**.

**The board number is structurally ~zero**: all 38,910 users carry placeholder `user{id}@example.com` emails; the only 40 real-looking emails (a single batch of `user_email_updated` events at 2019-10-23 13:00) are all `cust…@gmail.example`, which the `%.example` rule also excludes. Reproducing the board query against the warehouse returns **0**. Treat any non-zero historical board number with suspicion, and never use this query for real reporting until the email heuristic is fixed.

Similarly, `analytics.contactable_users` (view, created Dec 4 by `engineer-backfill.maya`, commit `e10cb0c`) is **empty** (opt-in ∧ valid email ∧ non-example domain — no user qualifies), so `contactable_customers` on the KPI dashboard is always 0, while the email digest independently counts "recipients = 40" using a different rule (`email NOT LIKE '%@example.com'`, jobs/email_digest.py) that ignores opt-in entirely.

### 4.4 Product metrics (best sellers, brand, category)

- **Redash dashboards** (best_sellers/brand_revenue/category_revenue, queries 2/3/4; SQL identical to git `dashboards/*.sql` at `57ea43a^`): item-level counting via `order_lines` + legacy fallback (`92596dc`), rolling windows (7d/30d/30d), exclude user 424242 (brand_revenue additionally excludes QA account UUID `cc27b436-d6f9-4e84-adaf-e716025dd369`, `adbcb7e`), exclude brands lucente/jetem — but **no status filter** (unpaid/cancelled/refunded/held all count) and **no test-SKU filter** (1002544 has brand `apple`, so its $635.14 sales appear in exec dashboards). Best sellers sorts by **revenue** despite showing units (docs/dashboard_notes.md).
- **Nightly `top_sellers` job** → `novamart.top_products` (jobs/top_sellers.py, `9a51155`): differs from the dashboard — status=1 only, calendar ET day, units-ranked, **no exclusions at all**: the test SKU appears on 50 of ~55 days (86 rows).
- **Category revenue** maps `products.category` → 6 display groups via `analytics.category_names` (backfill Nov 30, `2814b3d`). On Dec 12 six codes were regrouped (electronics.audio.* : entertainment→electronics; construction.tools.light : lighting→construction) with the old mapping "preserved" in `category_name_history` (`33054cd`) — but history rows are stamped `valid_from = 2026-08-13` (the backfill used `CURRENT_DATE`; visible in the backfill SQL and the table), so the history layer **never matches any 2019 order**: the dashboard silently applies current groupings to all history. Blank categories map to 'other'.
- **Brand reality** (status=1, whole period): apple ≈ 1.40M (≈49%), samsung 517k, xiaomi 106k, blank-brand 84.8k, lucente 42.9k (hidden from dashboards, inside statements), internal (test) 40.3k. **jetem has 5 products and zero orders** — hiding it (`1169e40`) was precautionary. 5,972 products have blank brands; causes are documented in `analytics.blank_brand_products` (Oct 21 backfill): first-sight inserts with `ON CONFLICT DO NOTHING` plus the in-process known-id cache blocked later repair; `ea0e97b` added a repair path.

### 4.5 Refunds

Two generations plus a view:
1. `POST /orders/{id}/refund` (since `d87cb3d` Nov 15) flips status to 3. No money row. 28 orders / $13,447.47.
2. `POST /payments/gateway_refund` (since `c49a7bb` Dec 5; "gateway is source of truth for money") inserts a negative payments row and does **not** flip status. 9 rows — but only 3 real refunds ($614.53), each replayed 3× weekly (no idempotency) totaling $1,843.59.
3. `analytics.refunds_unified` (view, `a3bffec` Dec 23) unions: status-2 orders labeled `order_cancelled` (54 / $13,249.64 — **cancellations counted as refunds**), status-3 `order_refunded` (full order price regardless of actual refund amount), and negative payments (`gateway_refund` — triple-counted where replayed). The Redash `refunds` dashboard (query 6) groups this by ET month of `updated_at`/`created_at`: 2019-11 = 32/9,691.77, 2019-12 = 59/18,848.93 (reproduced). Do not read this as money returned.

## 5. System

### 5.1 Service (novamart/, FastAPI)
Routers mounted at HEAD (`app.py`): catalog, carts, orders, similar, payments_webhook. **Three routers exist but are unmounted, each silently dropped when a later commit rewrote the import line:**
- `users.py` (email update): mounted `088a372` Oct 16 → dropped by `f1217a8` Oct 26. All 40 `user_email_updated` events sit inside that 10-day window.
- `reports.py` (`GET /reports/brands`): mounted `193f22d` Oct 21 → dropped by `f1217a8` Oct 26.
- `accounts.py` (`POST /accounts`): mounted `b567d9d` Nov 27 → dropped by `c49a7bb` Dec 5. All 30 accounts were created Dec 1. **Account creation has been dead since Dec 5.**

Order lifecycle (routers/orders.py): callback → advisory locks on session+ref → if ref known: replay (522 `order_callback_replayed` events); else if an open order exists for the same user+session within 15 min: append item (`order_lines` row + price increment; 225 `order_appended`); else create (status 0 → 1 in the same transaction). Cancel: status→2 (refunded orders can't be cancelled). Refund: status→3 (only from paid). Fee per callback: `price × 0.029 + 0.30` (flat part since Nov 20; constants.FEE_RATE/FEE_FLAT).

Statuses: 0 created, 1 paid, 2 cancelled (**was 4 before `8f19718` Oct 28** — no 4s exist in data because the cancel endpoint shipped with the change), 3 refunded, 5 legacy (excluded by reconcile since the initial import; none in data), 6 fraud-held (jobs/fraud_score.py). Snapshot counts: 9,033 / 54 / 28 / 12 (statuses 1/2/3/6).

### 5.2 Batch jobs (crontab.txt, retired → identical Airflow DAGs in airflow/dags/)
Nightly, ET: 03:00 reconcile (flags duplicate payment_refs, `LIMIT 200`; moved from 02:00 by `388370b` "overlaps with backup window") · 03:30 affinity (v1) · 03:45 affinity_v2 · 04:15 model_train · 04:45 price_suggest (shadow) · 05:15 trending · 05:45 fraud_score · 06:00 daily_report · 06:15 kpi_daily · 06:20 funnel · 06:30 monthly_statement (1st only) · 06:45 top_sellers · 06:50 reorder_forecast · 07:15 email_digest · 12:00/17:00 intraday_report. All log JSONL to `jobs.jsonl` → `novamart_logs.job_runs`.

**What breaks when they fail** (observed failure modes):
- `affinity_v2` **crashed Dec 3–5** (`job_runs` `job_crashed`: `IndexError` — `SEASONAL_FACTORS` has only Jan–Nov entries; fixed `3dbe4d7`). While a score table is missing/stale the widget silently falls back to trending.
- `daily_report` missing a run leaves a hole in `report_rows` that `daily_kpis`/`revenue_widget` render as a zero/missing day (Dec 31 is such a hole).
- `intraday_report` failure makes "today" vanish from the KPI dashboard and revenue widget (they read only the latest intraday snapshot for today).
- `email_digest` was a **silent no-op Nov 28–Dec 16** through two broken flag mechanisms (wrong env name `DIGEST_ON` in `c19a307`, env not exported to cron in `8dc520b`) until `0bd4eac` read `deploy/cron.env` directly; first real digest Dec 17 (`digest_log`). Its "top product" every single day was a test SKU.
- `model_train` needs ≥20 random-arm rows and both classes or it records a registry row without scores (jobs/model_train.py).

### 5.3 Data platform (post-migration; docs/data-access.md @ `1179287`)
Serving Postgres → Cloud SQL replica (Redash queries it). Warehouse: BigQuery `<warehouse-project>` — `novamart` (12 app tables), `novamart_analytics` (20 tables + 4 views), `novamart_logs` (`db_queries` raw statement log + `db_queries_normalized` view, `app_events`, `job_runs`). Loaded by `warehouse_backfill.py` (manifest-driven `gcloud sql export csv` → `bq load --replace`). Note the doc/code say dataset "analytics"; the real dataset is `novamart_analytics` (the `db_queries_normalized` view does this mapping explicitly). Redash's BigQuery data source (id 2) has no queries yet — all nine dashboards still hit Postgres.

## 6. Data

### 6.1 Core tables (dataset `novamart`; ranges verified)
- `orders` (9,127; Sep 25–Dec 31): one row per order; `price` = **order total** after Nov 22 merging; `payment_ref` = first callback's ref. Contains the 155 October duplicate rows.
- `order_lines` (2,284; from Nov 22): per-item rows (unique `payment_ref`); `SUM(order_lines.price) = orders.price` holds for all 2,059 multi-line orders (verified). **Pre-Nov-22 orders have no lines** — hence every item-level consumer needs the legacy-fallback UNION pattern (`92596dc`).
- `payments` (9,361): one row per callback (gross/fee/net), plus 9 negative gateway-refund rows; `payment_ref` column added Nov 22 (NULL before).
- `users` (38,950): placeholder emails; 40 exceptions (`@gmail.example`, Oct 23 batch). `products` (81,018): 5,972 blank brands; test SKUs 1004856/1002544.
- `report_rows` (6,923) / `report_rows_intraday` (2,358; Dec 8+): append-only snapshots keyed by report_date + created_at; one version per date in practice (verified) except intraday which has 2/day (12:00, 17:00 ET). Consumers must take latest `created_at` per date and only intraday-for-today (the `3eced24` revenue-widget fix; docs in the query text itself).
- `statements` (3), `top_products` (2,396; Nov 7+), `accounts`/`account_map` (30 each; Dec 1), `cart_items` (36,938).

### 6.2 Analytics tables/views (dataset `novamart_analytics`)
Finance: `statement_overrides` (1 row: 2019-10), `statement_corrections` (1 row: 2019-11, delta 0), `chargebacks` (3 rows, all Oct orders, booked Dec 9 retroactive to Dec 1), views `statements_corrected` / `statements_final` (definitions in Appendix A.3). Customers: `test_users` (exactly one row: 424242), `contactable_users` (view; **empty**), `kpi_daily` (45 rows), `daily_funnel` (53 rows; GAP_MIN 30→120 min on Dec 14 `f915c1b`). Product/ML: `product_affinity` and `product_affinity_v2` (3,912 rows each, 2,964 sentinel −1 rows, 1,476 base products), `model_scores` (948), `model_registry` (17), `rec_decision_log` (667,834), `trending_daily` (59 days), `reorder_hints` (200, overwritten nightly), `price_suggestions` (500, overwritten nightly, **zero readers** — verified in the query log), `price_history` (1,400), `blank_brand_products` (5,972), `category_names`/`category_name_history`, `digest_log` (15), `order_risk` (1,631), `refunds_unified` (view).

### 6.3 Logs (dataset `novamart_logs`)
- `db_queries` (3.6M lines) / `db_queries_normalized`: every SQL statement with an actor tag. Actors: `app` 3.27M, `job` 331k, `engineer.dev` 107, `engineer.maya` 52, `engineer-backfill.dev` 29, `engineer-backfill.maya` 3. The backfill actors are the **complete manual-mutation audit trail** (Appendix A.4) — including the Dec 29 release of fraud-held orders under $2,600 (`UPDATE orders SET status=1 WHERE status=6 AND price<2600`, matching commit `1cb8721` raising the threshold to 0.85).
- `app_events`: business events. Highlights: 843k `product_viewed`, 669k `rec_served`, 10,766 `duplicate_payment_ref` warnings, 3 `statement_fee_mismatch` warnings.
- `job_runs`: per-run stats for every job — the fastest way to establish when a job's behavior changed (e.g., trending logs `window_days: 60` through Dec 6 and `30` from Dec 7, matching `f563dea`; README's "60-day window" is stale per docs/trending_notes.md @ `8584613`).

## 7. Experimentation

### 7.1 Recommendation system lineage (docs/affinity_lineage.md @ `2885137`, verified end-to-end)
- **v1** (`776d674` Oct 12; jobs/affinity.py): co-cart pair counts, 30d window, exp(−0.05·age) decay; pairs seen <3 get **sentinel score −1** ("not enough data", *not* negative preference — serving must filter `score >= 0`; `fef5c96`). Served Oct 26–Dec 6 (app reads of `analytics.product_affinity` in the query log span exactly those dates). Still recomputed nightly at HEAD though nothing reads it.
- **v2** (`89666bf` Dec 2; jobs/affinity_v2.py): adds conversion weighting (cart=1, order=3), same-category ×1.15, extreme price-ratio ×0.7, monthly seasonal factor. **Version-string trap**: serving flag "2.0.0" selects the table whose rows are stamped `model_version='2.0.1'`. Crashed Dec 3–5 (Dec missing from `SEASONAL_FACTORS`), first success Dec 6.
- **v4** (`a1946ff` Dec 14; jobs/model_train.py): nightly logistic regression on random-arm exposures. **Judgment: it does not add signal.** The label is "user placed *any* later status=1 order" (not on recommended items); only 5 features enter the vector (README's claimed region-affinity/device-mix/stock-level features are absent; opt_in and stock are fetched but unused — noted in code); coefficients flip signs run to run (`model_registry`, e.g. account-age +0.81 on Dec 30, −0.75 on Dec 31); and `model_scores = affinity_v2_score × (1 + 0.1·coef[0])` — a single global multiplier, so **v4's ranking is exactly v2's ranking**. README claims serving is 4.0.0; `deploy/flags.env` still says `REC_MODEL_VERSION=2.0.0`, so **v4 has never served** (all non-random serves post-Dec-6 read `product_affinity_v2`).
- **Serving** (routers/similar.py): 5% random arm (`sha256(uid) % 20 == 0`) for unbiased training data (`df4ed85`); 6h in-process score cache with invalidation on nightly refresh (`a00f24c`, `8ed2971`). **Logging gap**: the Dec 17 refactor (`30e8907`) dropped random-arm decision logging until `a00f24c` — `rec_decision_log` has zero `arm='random'` rows on Dec 18.
- **Effectiveness**: coverage is thin (948 servable pairs over 449 of 81,018 products), so **~75–80% of `rec_served` events are `fallback`** (326k+208k of 669k) — first live 7-day bestsellers, then (post-Dec 6) `trending_daily`. The fallback path applies **no test-SKU filter**, and the test SKUs sit in trending's top ranks (#2/#3 on Dec 31; present all 59 days) — so the widget's dominant real-world behavior is recommending trending items including "Internal Test #4856".

### 7.2 Shelved / advisory experiments
- **Dynamic pricing** (docs/pricing_status.md @ `d2481be`): phase-1 shadow job (`894c535`) writes 500 ±5% nudges nightly to `price_suggestions`; phase 2 **ON HOLD per exec/legal review** (`cca9b0d`; NOTE in price_suggest.py). Query log confirms writes-only, zero reads. Live prices come solely from the vendor feed upsert (`d213f6e` fixed it to actually update prices).
- **Reorder hints** (docs/forecast_caveats.md @ `442b135`): `hint = 15.6 + 162.4/(velocity+1.8)` — hand-fit, **inverse to velocity** (slower sellers get bigger hints), top-200 only, overwritten nightly; Dec refit (`f85cdd2`) changed only K. Explicitly ADVISORY (README); finance must not commit spend from it. No consumers in the query log.
- **Fraud auto-hold** (`e4656fb` Dec 3): score = min(price/3000,1)·(1+0.15·new_account+0.15·high_velocity); threshold history 0.70 (`53f6f6c` Dec 5) → 0.85 with sub-$2,600 release (`1cb8721` Dec 29). 12 orders remain held ($40,213.29). Held revenue is invisible to statements but visible to the daily report — see §4.1.
- **Accounts beta**: 30 accounts (Dec 1), UUID namespace incompatible with legacy numeric user ids; the registered_conversion dashboard must map via shared email (`b975479` fixed the original broken join; the query's own comment documents the two-namespace trap). Reproduces to 30 buyers / $18,155.71 lifetime (status=1).

## 8. Glossary

- **Order** — row in `orders`, created by a payment-gateway callback; after Nov 22 may aggregate several same-session items (`order_lines`). `orders.price` = order total.
- **Order line** — per-item row (`order_lines`), exists only from Nov 22; older orders are single-item, represented by the order row itself ("legacy fallback").
- **payment_ref** — gateway's payment id; idempotency key since Oct 15. Duplicate refs before that = duplicate orders (unfixed, October only).
- **Status** — orders.status: 0 created, 1 paid, 2 cancelled (pre-Oct-28 code used 4), 3 refunded, 5 legacy-excluded, 6 fraud-held.
- **Gross / fee / net** — SUM(orders.price) / SUM(payments.fee) / difference, per ET month over status=1 (monthly_statement.py).
- **As-published vs corrected vs final** — `statements` (snapshot, never rewritten) vs `statements_corrected` (+ overrides) vs `statements_final` (+ chargebacks); use final for current reporting, statements to reproduce old decks (restatement_policy.md).
- **Chargeback** — `analytics.chargebacks`, subtracted from the *original order month* in statements_final.
- **Daily report** — `report_rows`, yesterday-ET per product, with SKU/brand/status/test-user filters (daily_report.py). **Intraday** — same shape for today, 12:00/17:00 ET snapshots (`report_rows_intraday`).
- **EXCLUDED_SKUS** — [1004856, 1002544], the two test SKUs (constants.py) — filtered from the daily report and the widget primary path only, nowhere else.
- **BRAND_DENYLIST** — [lucente, jetem]; report/dashboard cosmetic filter, not applied to statements.
- **Test user** — 424242 (in `analytics.test_users` and email-heuristic filters); the accounts-era QA UUID is `cc27b436-d6f9-4e84-adaf-e716025dd369`.
- **Active customers** — three different metrics; see §4.3 before quoting any number.
- **Contactable** — member of `analytics.contactable_users` (currently empty by construction).
- **Affinity / v2 / v4** — co-cart score table; conversion-weighted successor (rows say 2.0.1, flag says 2.0.0); logistic rescale of v2 (trained, never served).
- **Sentinel −1** — "too little data" affinity score; serving filters `score >= 0`.
- **Random arm** — 5% of users get uniform-random recommendations to generate unbiased training data (`arm='random'` in `rec_decision_log`).
- **Fallback** — widget's default when scores are missing: trending (post-Dec 6) / live bestsellers (before); ~75–80% of serves.
- **Trending** — `trending_daily`, 30-day (60-day before Dec 7) decayed unit ranking, top 50, min 5 units.
- **Reorder hint** — advisory inverse-velocity heuristic; not a forecast.
- **d2p** — "deploy to prod" trigger commits (`trigger deploy #d2p-novamart`), no code changes.
- **novamart-ops** — VM hosting Airflow + Redash post-migration (IAP tunnel; data-access.md).

---

## Appendix

### A.1 How each dashboard number is produced (Redash id → source → gotchas)
| Dashboard (id) | Reads | Gotchas |
|---|---|---|
| actives_board (1) | orders+users+test_users, Postgres | **Reproduces to 0** — placeholder-email exclusion removes everyone (§4.3) |
| best_sellers (2) | orders/order_lines/products | No status filter; revenue-sorted; includes test-SKU 1002544 (brand apple) |
| brand_revenue (3) | same | Extra QA-UUID exclusion (`adbcb7e`); blank brands appear as '' |
| category_revenue (4) | + category_names/history | History layer inert (valid_from 2026-08-13); blank→'other' |
| daily_kpis (5) | report_rows(+intraday)+orders | "orders" column is really item units; contactable always 0; inherits report_rows scars (§4.2) |
| refunds (6) | refunds_unified | Mixes cancellations, status flips (full price), replayed gateway rows (§4.5) |
| registered_conversion (7) | accounts→users(email)→orders | Two id namespaces; email join is the only valid bridge (`b975479`) |
| revenue_widget (8) | report_rows + intraday | Take-latest-version logic added `3eced24` after double-counting; Dec 31 exists only intraday |
| statements_final (9) | analytics.statements_final | The finance surface; inherits §4.1 caveats (duplicates, test SKU, no Dec) |

All nine queries are textually identical to `dashboards/*.sql` at `57ea43a^` (diffed) and run against the Postgres replica (data source 1), not BigQuery.

### A.2 Fee arithmetic
Per callback: `fee = round(price × 0.029, 2)` before 2019-11-20 00:00 ET, `round(price × 0.029 + 0.30, 2)` after (`12e1c68`; orders.py). Statement `fee` = sum of *collected* per-callback fees (post-`a92c96d`); the September and October snapshots predate that fix (Sep's tiny −0.01 delta was left alone; Oct got the override). Multi-item orders pay the flat $0.30 **per item callback**.

### A.3 View definitions (BigQuery `novamart_analytics`, INFORMATION_SCHEMA.VIEWS)
- `statements_corrected`: statements LEFT JOIN statement_overrides ON month, COALESCE each column.
- `statements_final`: statements_corrected minus chargebacks aggregated by ET month of the *original order's* created_at (gross and net reduced; fee untouched).
- `refunds_unified`: status-2/3 orders (full price, `updated_at` as event time) UNION negative payments rows.
- `contactable_users`: opt-in ∧ regex-valid email ∧ domain not example.com/net/org ∧ not `%.example`.

### A.4 Manual production mutations (complete list, from `db_queries_normalized` actors `engineer-backfill.*`)
Oct 21 (dev): create `analytics.blank_brand_products` snapshot with suspected causes. Nov 2 (dev): create `statement_overrides` + insert 2019-10 correction + create `statements_corrected` view. Nov 15 (dev): create `analytics.price_history` (+index). Nov 27 (dev): create `analytics.test_users`, insert 424242. Nov 30 (dev): create+backfill `category_names` (split_part rules). Dec 2 (dev): create `statement_corrections`, insert 2019-11 (computed delta = 0). Dec 4 (maya): create `contactable_users` view. Dec 8 (dev): create `report_rows_intraday` (+index). Dec 9 (dev): create `chargebacks`, insert 3 rows (first 3 Oct status=1 orders with price>700, full price, reported_at 2019-12-01), recreate corrected/final views. Dec 12 (dev): versioned taxonomy rework (history rows stamped CURRENT_DATE → the 2026-08-13 artifact). Dec 23 (dev): create `refunds_unified` view. Dec 29 (maya): **release fraud holds**: `UPDATE orders SET status=1 WHERE status=6 AND price<2600`.

### A.5 Safe-modification notes for the batch pipelines
- Jobs are idempotent-by-overwrite (`DELETE` then `INSERT`: affinity, v2, model_scores, trending-day, price_suggestions, reorder_hints) or append-only (report_rows, kpi_daily, daily_funnel, statements, top_products, order_risk, digest_log). Re-running an append-only job **duplicates rows** — consumers of report_rows already guard by taking MAX(created_at) per date; `statements`/`kpi_daily`/`top_products` consumers do not.
- Every job creates its own tables (`CREATE TABLE IF NOT EXISTS`) — schema.sql is **not** the full schema (order_lines, accounts, account_map, report_rows_intraday, top_products and all analytics tables are created at runtime by app/jobs/backfills).
- Time handling: business days/months are America/New_York; always use `timeutil.local_day_window_utc` (DST-safe since `102c9b4`). `FAKE_NOW` env var drives test-rig time (timeutil.now; used by ci/run_ci.py).
- The affinity **sentinel −1 convention** must survive any refactor: serving filters `score >= 0`; writing real negative scores would silently hide items.
- `similar.py` builds SQL with f-strings for the table name — only 'analytics.product_affinity_v2' / 'analytics.model_scores' are valid inputs by construction; keep it that way.
- Airflow DAGs are thin BashOperator wrappers (`python -m novamart.jobs.<name>`) with `catchup=False` — backfills must be run manually with FAKE_NOW-style control or code changes.
- CI (`ci/run_ci.py`) boots the app against a scratch DB, runs one view/cart/order flow and three jobs under `FAKE_NOW=2019-09-22`; it will not catch reporting-rule regressions.

### A.6 Open risks a new owner should fix first
1. Remove/adjust the 151 duplicate October orders (or book an override) — October is overstated by ~$58.8k even in `statements_final` (§4.1).
2. Idempotency for `gateway_refund` (dedupe by a gateway refund id) and reconcile refund events against order status.
3. Statements: filter test SKU 1004856 / brand `internal`, and decide the policy for held (status 6) orders so statements and daily reports agree.
4. Fix the actives_board / contactable email heuristics (placeholder-domain problem) before anyone quotes those numbers.
5. Exclude test SKUs from trending/top_products/digest and the widget fallback path.
6. Generate the missing 2019-12 statement (numbers in §4.1) and the missing Dec 31 daily report.
7. Re-mount or delete the dead routers (accounts/users/reports) — silent unmounting is the repo's recurring failure mode.
8. Repair `category_name_history.valid_from` (currently 2026-08-13) if historical category regrouping is ever supposed to work.
