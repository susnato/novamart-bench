# NovaMart Tribal Knowledge

- **Run started (wall clock):** Mon Oct 5 17:39:38 UTC 2026
- **Run UUID:** `12a24985-ca65-441b-8bbb-fa254fafc682`
- **Sources used:** repo `novamart` pinned at commit `5ae1182`; BigQuery project `novamart-warehouse` (datasets `novamart`, `novamart_analytics`, `novamart_logs`); serving Postgres replica (the same source Redash queries); Redash at `localhost:5054` (9 dashboards, read-only).
- Every claim cites a commit hash, table/view, query, log event, or dashboard. Supporting artifacts (schemas, query dumps, evidence notes) live next to this file.

---

## 1. Summary

NovaMart is a FastAPI + Postgres marketplace backend (`README.md`, commit `2da4141`, 2019-09-15) that operated from late September to December 31, 2019, after which the data platform was migrated: the serving DB stayed Postgres, analytics moved to BigQuery via a backfill job (`novamart/jobs/warehouse_backfill.py`, commit `5ae1182`), schedules moved from crontab to Airflow (`4bfcbe6`), and dashboards moved to Redash (`41e3537`).

**The money path:** payment-gateway callbacks create `orders` + `payments` rows (`novamart/routers/orders.py`); a nightly `daily_report` writes product-day `report_rows`; a monthly `monthly_statement` writes an append-only `statements` snapshot; finance restatements layer on top via `analytics.statement_overrides` → `statements_corrected` view → `statements_final` view (chargebacks subtracted). The company's answer to "what was revenue in month X" depends on which of three layers you read, and the as-published numbers legitimately differ from the restated ones (`docs/restatement_policy.md`, commits `a92c96d`, `4a58d17`, `cd559d3`).

**Headline numbers** (from `novamart.statements` and `novamart_analytics.statements_final`):

| Month | As published (statements) | Final restated (statements_final) |
|---|---|---|
| 2019-09 | net 2,623.64 | net 2,623.64 |
| 2019-10 | net 1,194,652.79 | net **1,191,085.36** (fee override + 3,567.57 chargebacks) |
| 2019-11 | net 1,069,286.09 | net 1,069,286.09 |
| 2019-12 | **no statement exists** (job runs on the 1st; data ends Dec 31) | — |

**The biggest things a new person must know, none of which are written in any single place:**

1. **October revenue is overstated by ~$58.8k** by webhook-replay duplicate orders (130 payment refs → 285 orders, created Oct 1–15, before idempotency fix `b676969`). 126 refs still have duplicate `status=1` orders worth an extra **$58,830.17**. The nightly `reconcile` job only logs warnings (10,766 `duplicate_payment_ref` events in `novamart_logs.app_events`); no statement correction was ever booked for this.
2. **The Nov 17 daily report permanently understates revenue by $74,995.96** (487 units/$148,857.07 in `report_rows` vs 704 units/$223,853.03 recomputed) — the `REPORT_SCAN_CAP=500` bug hit during the post-outage catch-up spike; the fix (`1233af8`) was never backfilled.
3. **There was a ~38-hour checkout outage**: zero orders between 2019-11-14 18:08:40 UTC and 2019-11-16 08:33:07 UTC (query on `novamart.orders`), while carting continued (2,284 `cart_items` on Nov 15). `report_rows` has **no row at all** for 2019-11-15.
4. **Three incompatible "active customers" definitions** coexist (`docs/metrics_definitions.md`), and the board-deck one (`actives_board` Redash query) currently returns **0** because every user email is a placeholder (`user{uid}@example.com`; 38,910 `example.com` + 40 `gmail.example` in `novamart.users`) and the query excludes example-style domains. Likewise `analytics.contactable_users` has **0 rows**, so `contactable_customers` on the KPI dashboard is always 0.
5. **The recommendations widget mostly serves the trending fallback, not the model**: per `analytics.rec_decision_log`, ~83% of v1-era and ~80% of v2-era decisions were `fallback/no_scores`. The "trained model v4" exists but is not serving (`REC_MODEL_VERSION=2.0.0` in `deploy/flags.env`), and its daily-retrained coefficients flip signs day to day (`analytics.model_registry`).
6. **Dashboards exclude lucente/jetem brands and QA user 424242; finance statements do not.** Lucente alone is ~$19.5k of October status-1 revenue included in statements but hidden from every dashboard (`ba1fbfa`, `1169e40`, `b59f077`).
7. **All Redash dashboards use rolling windows anchored to `now()`** against a dataset that ends 2019-12-31, so today they all render empty/zero — any current screenshot of them is meaningless (verified: all 9 Redash queries have `latest_query_data_id: null`).

---

## 2. Why this project

This document was produced to execute the three phases of the goal context:

- **Phase 1 — financial numbers:** be able to answer "what was revenue in a given month, and why" the way a tenured finance/data person would — including which table is source of truth for each number and how definitions changed (fee change, statement fee bug, chargebacks, restatements).
- **Phase 2 — product & customer analytics:** explain every number on the dashboards (best sellers, brand/category revenue, actives, contactables), including when a dashboard's number should **not** be trusted at face value.
- **Phase 3 — ML & batch jobs:** judge whether the ML systems actually work (they mostly serve fallback), and know what each scheduled job produces, what breaks when it fails, and how outputs feed reporting and serving — enough to safely modify or extend the pipelines.

The knowledge here is "tribal" because it lives scattered across 112 commits (`git_log.txt`), six months of `db_queries`/`app_events`/`job_runs` logs, nine Redash queries, warehouse view definitions, and a handful of `docs/*.md` notes — several of which are stale (e.g. `README.md` still says trending uses a 60-day window; `docs/trending_notes.md` corrects it to 30; `docs/rec_versions.md` is literally "TBD").

---

## 3. Business understanding

### 3.1 What the business is

A marketplace storefront. The storefront relays events to this backend: product views (`GET /products/{pid}`), cart adds/removes (`POST /cart`, `/cart/remove`), payment-gateway order callbacks (`POST /orders`), cancellations/refunds (`POST /orders/{id}/cancel`, `/refund`), a gateway refund webhook (`POST /payments/gateway_refund`), a vendor price feed (`POST /catalog/prices`), an accounts beta (`POST /accounts`), and a similar-products widget (`GET /products/{pid}/similar`). Routers: `novamart/routers/*.py`.

Key business idioms baked into code:

- **Users and products are created lazily on first sight** (`ensure_entities` in `novamart/routers/catalog.py`): user emails are placeholders (`user{uid}@example.com`), and profile attributes (name, region, signup channel, device, age band, opt-in) are *synthesized deterministically from the id* (`novamart/onboarding.py`). Consequence: email-based customer filters and "contactable" counts are structurally broken (see Metrics).
- **An order starts as one row per item**; since `5d1300d` (2019-11-22) callbacks in the same session within 15 minutes are *merged* into one order: `orders.price` accumulates the total, each item becomes an `order_lines` row, and `orders.product_id` keeps only the **first** item. Anything joining brand/category via `orders.product_id` misattributes multi-item orders — which is why dashboards use the `order_lines`-with-legacy-fallback pattern (`92596dc`).
- **Order statuses** (`novamart/constants.py`): 0 pending (transient during creation), 1 paid/complete, 2 cancelled, 3 refunded, 6 fraud-held. Historical trap: cancelled was **4** until `8f19718` (2019-10-28) aligned it to 2; the daily report didn't exclude cancelled/refunded at all until `11c0a42` (2019-11-18) set `EXCLUDED_STATUSES=[0,2,3]`. Status 5 appears only in the reconcile job's filter (`status <> 5`, `novamart/jobs/reconcile.py`) and never occurs in data (status counts: 1→9,033, 2→54, 3→28, 6→12).
- **Fees:** 2.9% per order until 2019-11-20, then 2.9% + $0.30 (`12e1c68`; constants `FEE_RATE`, `FEE_FLAT`; cutover `FEE_CHANGE_AT` in `novamart/jobs/monthly_statement.py`).
- **Brands excluded from reporting for business reasons:** `lucente` hidden "per partnerships" (`ba1fbfa`, 2019-10-25; a large lucente catalog import started 2019-10-01 per `docs/dashboard_notes.md`), `jetem` added later (`1169e40`, 2019-12-15; jetem has 5 products and zero orders in the data). These are hidden from the daily report and dashboards but **not** from finance statements.

### 3.2 Company timeline as told by the history (selected)

| Date | Event | Evidence |
|---|---|---|
| 2019-09-15 | Initial import; dashboards, daily report, monthly statement, reconcile | `2da4141` |
| 2019-10-01..15 | Payment webhook replays create duplicate orders (130 refs/285 orders) | `novamart.orders` dupe query; fixed by `b676969` |
| 2019-10-26 | Similar-products widget launches (first `rec_served` app event 2019-10-26 14:35) | `f1217a8`; `novamart_logs.app_events` |
| 2019-11-01 | October statement published with wrong fee (gross×2.9% = 35,679.64) | `job_runs` statement_generated; fixed `a92c96d` |
| 2019-11-03 | DST fall-back day; report window missed the 25th hour (~$2,986) | `102c9b4`; `daily_report_vs_raw.csv` |
| 2019-11-14→16 | **Checkout outage ~38h**, zero orders; carting continued | `novamart.orders` gap query |
| 2019-11-17 | Catch-up spike (704 item rows); daily report capped at 500 rows → $75k undercount, never backfilled | `1233af8`; `report_rows` vs recompute |
| 2019-11-20 | Processor fee change 2.9% + $0.30 | `12e1c68` |
| 2019-11-22 | Multi-item order merging + `order_lines` table | `5d1300d` |
| 2019-12-01 | Accounts beta: 30 accounts created (all `account_created` events at 2019-12-01 16:30) | `b567d9d`; `app_events` |
| 2019-12-02 | Dynamic pricing phase 2 put ON HOLD per exec/legal review | `cca9b0d`; `docs/pricing_status.md` |
| 2019-12-03..05 | affinity_v2 crashes nightly (`IndexError` — December missing from `SEASONAL_FACTORS`) | `job_runs` `job_crashed`; fixed `3dbe4d7` |
| 2019-12-06 | Rec version dispatch + 5% random arm; trending window 60→30 days | `df4ed85`, `f563dea`; `job_runs` `window_days` |
| 2019-12-19→24 | Naive exec revenue widget triple-counts (would show $410,387.39 vs correct $139,598.13 anchored at Dec 31) | `686a5d6` → fixed `3eced24` |
| 2019-12-29 | Fraud threshold 0.70→0.85; held orders under $2,600 released (12 remain held, $40,213.29) | `1cb8721`; `novamart.orders` status 6 |
| Jan 2020 | Platform migration: Airflow, Redash, BigQuery backfill | `d398b0d`, `41e3537`, `4bfcbe6`, `5ae1182` |

### 3.3 Who's who

Two engineers wrote essentially everything: **Dev Kapoor** (reports, statements, affinity, fraud, pricing, docs) and **Maya Iyer** (orders/carts/accounts, similar widget, digest, dashboards) — see author fields in `git_log.txt`. "Novamart Platform" authored the Jan-2020 migration commits. Frequent `trigger deploy #d2p-novamart` commits mark deploys; code behavior changes only after the next deploy (e.g. digest fix committed `0bd4eac` Dec 16, deploy `4c37825` Dec 17, first digest sent Dec 17 12:15 UTC per `analytics.digest_log`).

---

## 4. Metrics

### 4.1 Revenue — the four layers, and which to use

**Layer 0 — raw orders/payments (`novamart.orders`, `novamart.payments`).**
Gross revenue = `SUM(orders.price) WHERE status=1` over a *local-month window* (`America/New_York`; `constants.LOCAL_TZ`, `timeutil.local_month_window_utc`). This number **drifts after the fact**: statuses change (cancellations/refunds/fraud holds), so a recompute today gives Oct = $1,206,337.32 (3,695 orders) vs the published $1,230,332.43 (3,765) — 70 October orders were cancelled/refunded later. All 12 September orders are now status 2/3, so a naive recompute of September gives **zero**.

**Layer 1 — published statements (`novamart.statements`, written by `novamart/jobs/monthly_statement.py` on the 1st).**
Append-only; records what was published at the time. Columns: month, gross, fee, net, orders_count. Fee history: originally `gross × 2.9%` (`2da4141`); from `a92c96d` (2019-11-02) fee = **sum of collected per-order `payments.fee`** — one day too late for the October statement, hence the override. The job also computes an *expected* fee and logs `statement_fee_mismatch` when it deviates (3 warnings in `app_events`; the Dec 1 one, delta −170.41, is the flat $0.30 missing from the expectation formula, fixed next day in `4a58d17`).

**Layer 2 — `novamart_analytics.statements_corrected` (view).**
`statements` LEFT JOIN `statement_overrides` with COALESCE. One override exists: 2019-10 fee 35,679.50 / net 1,194,652.93, note "Corrected to sum of per-order collected payment fees". `analytics.statement_corrections` is the audit note table (one row: 2019-11, delta 0, "November 2019 processor fee change audit correction" — the audit concluded November needed no change).

**Layer 3 — `novamart_analytics.statements_final` (view; the finance/board surface, Redash query `statements_final`).**
`statements_corrected` minus booked chargebacks grouped to the **original order's NY month** (`analytics.chargebacks`: 3 rows, $3,567.57, all reported 2019-12-01, all against October orders). October final: gross 1,226,764.86 / net **1,191,085.36**.

**Policy (from `docs/restatement_policy.md`, commit `a576d0d`):** "match the old deck" → `statements`; current finance number → `statements_final`.

**How a tenured person answers "what was revenue in month X and why":**
- Sep 2019: $2,702 gross as published (`statements`); note all 12 orders were later cancelled/refunded, so order-table recomputes show 0.
- Oct 2019: published net 1,194,652.79; restated net 1,191,085.36 (fee override + chargebacks). *Also know*: ~$58.8k of October's gross is webhook-replay duplicates that were never corrected (see 4.6) and ~$19.5k is lucente revenue that dashboards hide but statements include.
- Nov 2019: 1,069,286.09, same in all layers (fee = collected fees; audit delta 0).
- Dec 2019: **no statement exists**. Best available: orders status=1 gross $552,328.93 (1,756 orders) — but $40,213.29 sits in fraud-held status 6, 9 gateway refunds (−$1,843.59) hit `payments` without changing order status, and 50 Dec orders are cancelled/refunded.

### 4.2 Daily revenue — `report_rows` / `report_rows_intraday`

- `daily_report` (06:00 daily, `airflow/dags/daily_report_dag.py`): writes yesterday's per-product units/revenue into `report_rows` using NY-local day windows, item-level counting (`order_lines` + legacy fallback), excluding statuses (0,2,3), `analytics.test_users`, `EXCLUDED_SKUS` (1004856, 1002544), and brands lucente/jetem.
- `intraday_report` (12:00 & 17:00 NY since `a2e0013`, 2019-12-08): same logic for *today so far*, append-only into `report_rows_intraday` (2 snapshots/day in data).
- **Rows are never rewritten.** Historical `report_rows` reflect the *rules in force on the day they were generated*: before 2019-10-08 test SKUs included (`83fb3ed`), before 2019-10-25 lucente included (`ba1fbfa`), before 2019-11-18 cancelled/refunded included (`11c0a42`), before 2019-11-20 only first 500 rows scanned (`1233af8`), before 2019-11-27 QA user included (`b59f077`), before 2019-12-05 orders-only counting (`92596dc`), before 2019-12-15 jetem included (`1169e40`). The full day-by-day delta between `report_rows` and a current-rules recompute is in `daily_report_vs_raw.csv`; biggest: 2019-11-17 (−$74,995.96, scan cap), 2019-11-03 (−$2,985.99, DST), 2019-10-01 (+$24,096 reported vs current recompute, mostly later-cancelled orders).

### 4.3 Refunds

Two mechanisms (and the view that unifies them, `a3bffec`):

1. **Status flips:** `/orders/{id}/refund` sets status 3; `/orders/{id}/cancel` sets status 2 (no payments rows written). 28 refunds, 54 cancels in `app_events`/`orders`.
2. **Gateway refunds (money truth):** `POST /payments/gateway_refund` (`c49a7bb`, "the gateway is the source of truth for money") inserts **negative `payments` rows** (gross=−amount, fee=0). 9 events, −$1,843.59, Dec 13–27. **The 3 affected orders remain status=1**, so orders-based revenue still counts them.

`novamart_analytics.refunds_unified` (view; Redash dashboard `refunds`, query id 1) = status-2 and status-3 orders at full `orders.price` (timestamped by `updated_at`) UNION negative payments. Caveats: (a) it **includes cancellations**, so "refunds_total" ≠ money returned; (b) status-flip "amounts" are order totals, not actual movements; (c) no overlap/double count across kinds was found (0 status-3 orders have negative payments — verified by query).

### 4.4 Customer counts — three definitions that never agree (`docs/metrics_definitions.md`, `dd0c8fc`)

| Definition | Where | Rules | Value at 2019-12-31 |
|---|---|---|---|
| Nightly KPI | `novamart/jobs/kpi_daily.py` → `analytics.kpi_daily` (`14726e7`) | trailing 30×24h, `status=1`, **no** QA/test exclusions | **1,152** (table) / 1,150 recomputed at day end |
| KPI dashboard | Redash `daily_kpis` (query 7) | per NY calendar day, **no status filter**, excludes uid 424242 + lucente/jetem via products join | daily series |
| Board deck | Redash `actives_board` (query 3, `2dde4f0`) | trailing 30d, excludes statuses {0,2,3}, `analytics.test_users`, and email-heuristic test accounts | **0** — all 38,950 users have placeholder emails (38,910 `@example.com`, 40 `@gmail.example`, both excluded) |

The board number is the "most honest" definition on paper and the most wrong in practice. Any board deck built from it would show zero active customers.

**Contactables:** `analytics.contactable_users` (view, `e10cb0c`) = opted-in users with valid non-example emails → **0 rows**, so `contactable_customers` in `daily_kpis` is always 0. Meanwhile the email digest counts recipients as `email NOT LIKE '%@example.com'` → **40** (the 40 users whose emails were batch-updated to `cust…@gmail.example` on 2019-10-23 13:00, `app_events` `user_email_updated`; one of them is the QA account). Two different "contactable" definitions, both effectively broken.

**Registered customers:** `accounts` (UUID namespace) vs `users`/`orders` (numeric uid). They are **not castable to each other**; the `registered_conversion` Redash query (4; fixed in `b975479`) maps account→user **via shared email**, then joins orders on numeric uid. Current value: 30 buyers, $18,155.71. QA mapping proof: `account_map` links uid 424242 ↔ `cc27b436-d6f9-4e84-adaf-e716025dd369` — which is why `brand_revenue` excludes both id forms (`adbcb7e`); the UUID literal can never match a numeric `orders.user_id`, so that filter is belt-and-braces.

### 4.5 Product metrics

- **Best sellers** (Redash query 9; rules documented in `docs/dashboard_notes.md`): rolling 7×24h window from `now()`, item-level counting with legacy fallback (`92596dc`), excludes uid 424242 and lucente/jetem, **no status filter**, ranked by **revenue** (not units). Hand-reproductions that filter `status=1` will come out lower.
- **Nightly `top_sellers` job** (`9a51155`) → `novamart.top_products`: yesterday, `status=1`, **orders-table only** (`orders.product_id`) — so it both filters status (unlike the dashboard) and miscounts multi-item orders (unlike the dashboard). Two "best seller" surfaces, two definitions.
- **Brand revenue** (query 8): 30-day rolling, same cleanups + the UUID exclusion.
- **Category revenue** (query 6): 30-day rolling; maps `products.category` → display group via `analytics.category_names` with a versioned lateral (`valid_from <= order date`, latest wins, history preferred on tie; `33054cd`). **The taxonomy versioning is broken in practice** (see 6.4).
- **Trending** (`novamart/jobs/trending.py` → `analytics.trending_daily`): status=1 units over a rolling window with `exp(-0.05 × days_since_last_order)` decay, min 5 units, top 50. Window shortened 60→30 days in `f563dea`; `job_runs` shows `window_days:60` through 2019-12-06 and `30` from 2019-12-07 — the cause of the December "faster churn" (`docs/trending_notes.md`; the README's "60-day" claim is stale).
- **Blank brands:** 5,972 products sold with blank brand (`analytics.blank_brand_products`): first-seen inserts via `ensure_entities` used `ON CONFLICT DO NOTHING` plus an in-process known-id cache, so later catalog metadata couldn't repair them until `ea0e97b`/`d213f6e`. These land in "unbranded"/"other" buckets in brand/category reports.

### 4.6 Known revenue-quality issues no dashboard shows

1. **Replay duplicates (Oct 1–15):** 130 payment refs → 285 orders, $106,943.01 total price; the extra copies beyond one order per ref = **$59,812.52**, of which **$58,830.17 is still status=1** and therefore inside the October statement. Every one of these refs also has duplicated `payments` rows. Fixed going forward by `b676969` (idempotency by payment_ref) and the advisory-lock + ref-lookup logic now in `novamart/routers/orders.py`; `reconcile` (03:00) flags them nightly (capped `RECONCILE_BATCH`, 100→200 in `030d841`) but **only warns** — the data was never corrected and no statement override was booked for it.
2. **Fraud holds remove revenue silently:** `fraud_score` moves `status 1→6` ($40,213.29 currently held, all December). Threshold history: 0.90 (`e4656fb`) → 0.70 (`53f6f6c`) → 0.85 + release of held orders under $2,600 (`1cb8721`). Held orders vanish from every status=1 metric but are not refunds.
3. **Gateway-refunded orders stay status=1** (3 orders): money left via `payments`, revenue stays in `orders`-based metrics.
4. **Statements include brands/users that dashboards exclude** (lucente ~$19.5k Oct / $15.9k Nov / $7.5k Dec status-1 revenue; QA uid 424242 = $139.86 across 14 orders). Dashboard revenue and finance revenue are *definitionally different populations*.

---

## 5. System

### 5.1 Service

`novamart/app.py` wires routers {catalog, carts, orders, similar, payments_webhook} over an async psycopg pool (`novamart/db.py`). **Every SQL statement is logged** (`db_log` → `db_queries.log` → exported to `novamart_logs.db_queries`; app JSONL → `app_events`; job stats → `job_runs`). The `db_queries_normalized` view parses the raw statement log into a BigQuery-jobs-like shape (actor, statement type, referenced tables).

Order creation (`novamart/routers/orders.py`) is the most intricate path: DDL-on-demand for `order_lines`/`payments.payment_ref`, two advisory locks (session, ref), ref-idempotency across both `orders.payment_ref` and `order_lines.payment_ref`, 15-minute same-session merge (append line + accumulate `orders.price`), and payment insertion with fee = `price×0.029 + 0.30`. Events: `order_created` (9,127), `order_appended` (225), `order_callback_replayed` (522).

### 5.2 Scheduled jobs (Airflow `airflow/dags/*.py`, migrated from `crontab.txt` which is retired but kept for reference)

| Time (local) | Job | Writes | What breaks if it fails |
|---|---|---|---|
| 03:00 | `reconcile` | warnings only (`duplicate_payment_ref`) | lose dup-detection signal; moved to 3am overlapping backup window (`388370b`) |
| 03:30 | `affinity` (v1, legacy) | `analytics.product_affinity` (full nightly recompute; score −1 sentinel for pairs seen <3, `fef5c96`) | nothing user-facing — widget no longer reads it (`docs/affinity_lineage.md`); pure waste candidate |
| 03:45 | `affinity_v2` | `analytics.product_affinity_v2` (model_version stamp `2.0.1`) | widget serves stale scores until cache epoch sees new `updated_at` (`8ed2971`); if table empty → trending fallback. Crashed 3 nights in Dec (seasonal index bug `3dbe4d7`) |
| 04:15 | `model_train` | `analytics.model_registry`, `analytics.model_scores` | only matters if `REC_MODEL_VERSION=4.0.0` were enabled; currently inert for serving |
| 04:45 | `price_suggest` | `analytics.price_suggestions` (top-500, ±5% nudge; **shadow only**, phase 2 ON HOLD `cca9b0d`) | nothing consumes it (verified in `docs/pricing_status.md`: writes but no reads in `db_queries`) |
| 05:15 | `trending` | `analytics.trending_daily` (top 50) | homepage trending stale **and** the similar-widget fallback breaks (most served recs!) |
| 05:45 | `fraud_score` | `analytics.order_risk` + flips orders to status 6 | no new holds; revenue metrics unaffected until it runs |
| 06:00 | `daily_report` | `novamart.report_rows` | KPI dashboard/revenue widget lose the day; **never rerun historically** |
| 06:15 | `kpi_daily` | `analytics.kpi_daily` | nightly actives series gap; recoverable (ops helper `scripts/rerun_kpis.py` exists — but see Discount trap below) |
| 06:20 | `funnel` | `analytics.daily_funnel` (sessionized; gap 30→**120** min `f915c1b`, confirmed in `job_runs` `gap_min`) | funnel series gap; pre/post-Dec-15 session counts not comparable |
| 06:45 | `top_sellers` | `novamart.top_products` | merch top-sellers feed stale |
| 06:50 | `reorder_forecast` | `analytics.reorder_hints` (ADVISORY; `hint = 15.6 + 162.4/(velocity+1.8)` — **larger hints for slower sellers**; K refit in `f85cdd2`) | nothing critical; must never drive purchasing (`docs/forecast_caveats.md`, README) |
| 07:15 | `email_digest` | `analytics.digest_log` | marketing digest skipped — exactly what happened Nov 28–Dec 16 (flag plumbing: `c19a307` → `8dc520b` → `0bd4eac`; first send 2019-12-17, 40 recipients/day) |
| 12:00/17:00 | `intraday_report` | `novamart.report_rows_intraday` | exec widget/KPI "today" row missing |
| monthly 1st 06:30 | `monthly_statement` | `novamart.statements` | the month's statement simply doesn't exist (December's never ran — data ends Dec 31) |
| manual | `warehouse_backfill` | all BQ tables (per `novamart/jobs/warehouse_manifest.json`: Cloud SQL CSV export → `bq load --replace`) | warehouse staleness; it is a full-replace snapshot copy of the serving DB |

**Overwrite-nightly tables (no history):** `product_affinity`, `product_affinity_v2`, `model_scores`, `price_suggestions`, `reorder_hints`; `trending_daily` deletes same-day rows. **Append-only:** `report_rows(_intraday)`, `statements`, `kpi_daily`, `daily_funnel`, `order_risk`, `rec_decision_log`, `digest_log`, `model_registry`, `price_history`.

**Discount trap for pipeline modifiers:** `novamart/jobs/discounts.py:apply_discounts(rows, cap=0.40)` defaults to the **legacy 40% cap**; the finance-approved value is `constants.DISCOUNT_CAP=0.25` (`35c581e`). The ops runbook `scripts/rerun_kpis.py` calls `apply_discounts(rows)` **without** passing the constant — anyone reusing it reproduces the legacy cap.

### 5.3 Dashboards (Redash, `http://localhost:5054`)

Nine dashboards, each backed by one query of the same name (ids: 1 refunds, 2 revenue_widget, 3 actives_board, 4 registered_conversion, 5 statements_final, 6 category_revenue, 7 daily_kpis, 8 brand_revenue, 9 best_sellers), all on data source 1 "novamart" (**Postgres**, i.e. the serving replica — not BigQuery). SQL is byte-identical to the old `dashboards/*.sql` deleted in `41e3537`; full text saved in `redash_queries.txt`.

- `revenue_widget` combines last-of-day `report_rows` versions for closed days + latest intraday snapshot for today. The original naive version (`686a5d6`) summed *all* snapshots and used an 8-day window; anchored at 2019-12-31 it would show **$410,387.39 vs the correct $139,598.13** (~2.9×). Fixed in `3eced24` after 5 days live.
- `daily_kpis` merges `report_rows` (closed days) + `report_rows_intraday` (today) for orders/revenue, plus per-day actives/contactables from `orders` (no status filter) — note its "orders" column is actually **units** (`SUM(r.units)`).
- All of {2,3,6,7,8,9} anchor to `now()`; with the dataset frozen at 2019-12-31 they render empty today. `refunds` (1), `registered_conversion` (4) and `statements_final` (5) are all-time and still render.

### 5.4 Platform migration (Jan 2020)

Post-migration layout per `docs/data-access.md` (`d398b0d`): serving Postgres replica; warehouse BigQuery `novamart-warehouse` (`novamart` = `public.*`, `novamart_analytics` = `analytics.*`); logs exported to `novamart_logs` (`db_queries` raw statement lines, `app_events` JSONL, `job_runs`); Airflow DAGs are thin `BashOperator` wrappers (`python -m novamart.jobs.<name>`) preserving the cron times; `crontab.txt` retired.

---

## 6. Data

### 6.1 Datasets and tables (schemas dumped to `schema_novamart.csv`, `schema_analytics.csv`)

**`novamart` (serving copies):** `users` (38,950), `products` (81,018), `cart_items` (36,938), `orders` (9,127), `order_lines` (2,284; exists only from 2019-11-22 — older orders *must* use the legacy fallback), `payments` (9,361; includes 9 negative refund rows; `payment_ref` column added later, NULL on old rows), `report_rows`, `report_rows_intraday`, `statements`, `top_products`, `accounts` (30), `account_map` (30).

**`novamart_analytics`:** job outputs (`kpi_daily`, `daily_funnel`, `trending_daily`, `top`-style tables, `product_affinity[_v2]`, `model_scores`, `model_registry`, `order_risk`, `price_suggestions`, `reorder_hints`, `digest_log`, `rec_decision_log`, `price_history`), finance restatement tables (`statement_overrides`, `statement_corrections`, `chargebacks`), reference/cleanup tables (`test_users` = {424242}, `category_names`, `category_name_history`, `blank_brand_products`), and 4 views (`contactable_users`, `refunds_unified`, `statements_corrected`, `statements_final` — definitions dumped in `view_definitions.json`).

**`novamart_logs`:** `app_events` (1.56M+ rows across 14 event types), `db_queries` (raw `[app|job|engineer…] statement:` lines), `job_runs`, `db_queries_normalized` view.

### 6.2 Identity model

- `users.id` (numeric) is the only id on orders/carts. `accounts.account_id` (UUID) is the beta namespace; `account_map` links them. **Join via email or account_map, never cast** (comment block in `registered_conversion` query; `b975479`).
- Emails are placeholders by construction (`accounts.py`/`catalog.py`: `user{uid}@example.com`); 40 were later updated to `…@gmail.example` (`088a372` added the endpoint; the batch ran 2019-10-23). **Any email-based segmentation is operating on synthetic data.**

### 6.3 Timezones

Data timestamps are UTC; *business days and months are `America/New_York`* (`constants.LOCAL_TZ`, `jobs/timeutil.py`). DST matters: the Nov 3 2019 fall-back day is 25h; windows computed as `start+24h` undercounted it until `102c9b4`. When reproducing any daily/monthly number, build windows from local midnights.

### 6.4 The category-taxonomy trap

The Dec 12 "versioned taxonomy" migration (`33054cd`) intended: old orders keep old display groups via `category_name_history`, new orders get renamed groups. What actually happened (from `novamart_logs.db_queries`, 2019-12-12 20:00, actor `engineer-backfill:dev`):

1. The INSERT of the new names (`construction.tools.light*`→`lighting`, `electronics.audio*`→`entertainment`) into `category_names` was guarded by `AND NOT EXISTS (…pg_constraint… contype='p')` — i.e. *only if the table has no primary key*. The table **was created with `code text PRIMARY KEY`** on 2019-11-30, so **the insert silently inserted nothing**.
2. Only `category_name_history` received the 6 new-name rows, with `valid_from := CURRENT_DATE` (materialized as 2026-08-13 in the warehouse snapshot) — a date *after every order*, so the lateral `valid_from <= order_date` can never select them.

Net effect: the rename **never took effect anywhere**; `category_names` still maps those codes to `electronics`/`construction` (verified: no `entertainment`/`lighting` display groups exist in `category_names`), and the "history" is unreachable dead rows. Anyone asked "why doesn't the entertainment category show up" — this is why.

### 6.5 Data-quality register (quick reference)

| Issue | Scope | Evidence |
|---|---|---|
| Webhook replay duplicates | Oct 1–15 orders/payments; +$58.8k status-1 gross | dupe-ref query; `b676969`; `app_events` warnings |
| Nov 15 outage / missing report day | orders, report_rows | gap query; no `report_rows` for 2019-11-15 |
| Nov 17 scan-cap undercount | report_rows (−$74,996) | `daily_report_vs_raw.csv`; `1233af8` |
| Historical report_rows frozen under old rules | all days before each filter's deploy | commit dates vs `report_rows` |
| Placeholder emails | users, board actives (=0), contactables (=0), digest (=40) | domain histogram; `contactable_users`; `digest_log` |
| Blank brands (5,972 products) | brand/category reports' "unbranded"/"other" | `analytics.blank_brand_products`; `ea0e97b` |
| Taxonomy rename never landed | category_revenue dashboard | §6.4 log lines |
| `orders.product_id` = first item only on merged orders | any orders-only product join (incl. `top_sellers`, `/reports/brands`) | `5d1300d`; `92596dc` |
| Gateway-refunded orders still status=1 | orders-based revenue | refund-overlap queries |
| Sept orders all cancelled/refunded later; Oct 1 cohort cleaned up every Tuesday Nov 5–Dec 31 | month recomputes vs statements | `updated_at` histogram |
| `statements` timestamps display oddly in `bq` CLI; use CAST AS STRING | tooling | observed emulator behavior |

---

## 7. Experimentation

### 7.1 Recommendations (the only real experiment framework)

- **Versions** (`novamart/routers/similar.py`, `REC_VERSIONS`): `1.0.0` retired co-cart affinity; `2.0.0` = affinity-v2 exploit (**current**, via `deploy/flags.env REC_MODEL_VERSION=2.0.0`); `4.0.0` = trained model behind the same flag (not enabled). Naming trap: serving version `2.0.0` reads `product_affinity_v2` whose rows are stamped `model_version='2.0.1'` (`docs/affinity_lineage.md`). `docs/rec_versions.md` is "TBD" — this section is its replacement.
- **Random arm:** 5% of users (`sha256(uid) % 20 == 0`) get uniform-random items (`df4ed85`, 2019-12-06) to collect unbiased training data. Decisions log to `analytics.rec_decision_log` (ts, user, base_pid, items, intended/effective version, source, fallback_reason, arm). **Logging gap on 2019-12-18 only** — the Dec 17 refactor (`30e8907`) dropped the random-arm insert; restored by `a00f24c` (commit message says so; confirmed by the daily arm counts).
- **Does it work?** Mostly no — by decision volume the widget is a trending-list server:
  - v1 era: 326,186 fallback(`no_scores`) vs 66,444 affinity-served (**83% fallback**).
  - v2 era: 182,868 fallback(`no_scores`) + 25,091 cache-then-empty→fallback vs 31,268 model + 21,427 model-from-cache + 14,566 random (**~80% fallback**).
  Root cause: the `MIN_PAIRS=3` graduation gate writes score **−1 sentinels** (not preferences! serving must filter `score >= 0`, `fef5c96`) and most base products have no qualifying pairs; serving additionally restricts to the latest `updated_at` batch.
- **Model v4** (`novamart/jobs/model_train.py`, `a1946ff`): nightly logistic regression on random-arm exposures (features: served-list size, base price/1000, base popularity/100, capped account age, organic-channel flag; `opt_in` fetched but deliberately not in the vector yet). It then *rescales affinity-v2 scores* by `(1 + 0.1 × first_coefficient)` into `model_scores` — i.e. v4 is a thin multiplier over v2, not an independent ranker. `model_registry` shows train_rows growing 4,197→14,411 (Dec 15→31) with **coefficient sign flips across days** — not stable enough to trust; keeping `REC_MODEL_VERSION=2.0.0` is the right call until evaluated.
- **affinity v2 scoring** (`89666bf`): `(1×pairs + 3×conversions) × exp(−0.05×age) × same-category 1.15 × price-ratio-damping 0.7 × seasonal factor`; `SEASONAL_FACTORS` had only Jan–Nov entries → December crash for 3 nights (`job_runs` ERROR rows; fixed `3dbe4d7` with a bounds check).

### 7.2 Dynamic pricing — shadow experiment, held

Phase 1 writes nightly ±5% nudges for the top 500 demand products into `analytics.price_suggestions` (`894c535`). Phase 2 (serving) is **ON HOLD per exec/legal review** (`cca9b0d`; code NOTE dated Dec 2). Nothing reads the table (no SELECTs in `db_queries`; `docs/pricing_status.md`). Storefront prices come solely from the vendor feed (`/catalog/prices` → `products.list_price`, history in `analytics.price_history` since `795d273`).

### 7.3 Threshold/parameter tuning (changes that look like experiments in the data)

- **Fraud hold threshold:** 0.90 → 0.70 (Dec 5, `53f6f6c`) → 0.85 + release held < $2,600 (Dec 29, `1cb8721`). Score = `min(price/3000,1) × (1 + 0.15·new_account + 0.15·high_velocity)` — essentially a price-outlier detector with user boosts; the 12 still-held orders are all ≥ $2,655.
- **Trending window** 60→30 days (Dec 6, `f563dea`): any trending time series spanning Dec 6/7 compares different definitions.
- **Funnel session gap** 30→120 min (Dec 14, `f915c1b`): session counts before/after Dec 15 are not comparable (`job_runs` `gap_min`).
- **Reorder constant refit** (`f85cdd2`): single-constant retune, no validation — explicitly not finance-grade (`docs/forecast_caveats.md`).

There is no holdout/metrics layer for any of these: no experiment assignment table other than `rec_decision_log`, no significance tooling, no backtesting artifacts. Treat all tuning as judgment calls, not measured wins.

---

## 8. Glossary

| Term | Meaning (and source of truth) |
|---|---|
| **Order statuses** | 0 pending (transient), 1 paid/complete, 2 cancelled (was 4 before `8f19718`), 3 refunded, 6 fraud-held; 5 referenced only in `reconcile`, unused. `novamart/constants.py` |
| **Gross / fee / net** | gross = `SUM(orders.price)` status=1 in NY month; fee = collected `payments.fee` (post-`a92c96d`); net = gross − fee. `monthly_statement.py` |
| **Statement** | Append-only monthly publication snapshot, `novamart.statements` |
| **Override / correction / chargeback** | `statement_overrides` replaces a month's values in `statements_corrected`; `statement_corrections` is the audit note; `chargebacks` subtract in `statements_final` grouped to the original order month |
| **statements_final** | The current finance/board revenue surface (Redash query 5) |
| **report_rows / report_rows_intraday** | Per-product daily (final/partial) units+revenue snapshots under reporting rules; frozen as-generated |
| **Reporting rules** | status NOT IN (0,2,3), exclude `test_users`, SKUs 1004856/1002544, brands lucente/jetem, item-level counting with legacy fallback |
| **item_orders pattern** | `order_lines` joined to orders UNION legacy orders without lines — the only correct way to count items/brands since `5d1300d`/`92596dc` |
| **payment_ref** | Gateway idempotency key; unique per charge; pre-Oct-15 replays created duplicate orders per ref |
| **Active customers** | Three definitions: kpi_daily (30d, status=1), daily_kpis dashboard (per-day, no status filter, cleanups), actives_board (30d, status/test/email cleanups — currently 0). `docs/metrics_definitions.md` |
| **Contactable** | `analytics.contactable_users` view (opt-in + real-looking email) — 0 rows; digest uses a different rule → 40 |
| **test_users** | `analytics.test_users` = {424242}, the QA smoke account (also account UUID `cc27b436-…`, email `cust424242@gmail.example`) |
| **Brand denylist** | lucente (partnerships, `ba1fbfa`), jetem (`1169e40`) — hidden from reports/dashboards, included in statements |
| **Affinity / affinity_v2** | Co-cart pair scores; v2 adds conversion weighting, category boost, price-ratio damping, seasonality; −1 = "insufficient data" sentinel, serving filters `score >= 0` |
| **REC_MODEL_VERSION** | Serving flag in `deploy/flags.env` (2.0.0 ⇒ read `product_affinity_v2`; 4.0.0 ⇒ `model_scores`); rows in v2 table self-stamp 2.0.1 |
| **Random arm** | 5% uid-hash bucket served uniform-random recs for training data; logged in `rec_decision_log` with `arm='random'` |
| **Fallback** | Widget serving `trending_daily` top-K when scores are missing — the majority outcome |
| **Trending** | status=1 units, 30-day rolling (60 before Dec 7), ×exp(−0.05·age), min 5 units, top 50 |
| **Reorder hints** | ADVISORY `15.6 + 162.4/(velocity+1.8)`; inversely related to velocity; never commit spend from it |
| **Fraud hold** | `order_risk.score > FRAUD_HOLD_THRESHOLD` (0.85) ⇒ status 6 |
| **DISCOUNT_CAP** | 0.25 approved (`constants.py`); `apply_discounts` *defaults to legacy 0.40* — always pass the constant |
| **LOCAL_TZ** | `America/New_York`; business days/months are local, storage is UTC |
| **d2p commits** | `trigger deploy #d2p-novamart` — deploy markers; behavior changes land at the next one |

---

## Appendix

### A. How to answer "what was revenue in month X?" (worked procedure)

1. Board/external, current: `SELECT * FROM novamart_analytics.statements_final WHERE month='X'` (Redash query 5).
2. "Match the old deck": `novamart.statements` (expect 2019-10 fee 35,679.64/net 1,194,652.79 in the Nov deck).
3. Explain any delta: check `statement_overrides` (fee restatement, note field), then `chargebacks` joined to orders' NY month (Oct −3,567.57), then — beyond the official layers — the replay-duplicate overhang (+$58,830.17 of October status-1 gross) and later status flips (70 Oct orders → status 2/3 after publication).
4. For a month with no statement (Dec 2019): orders status=1 NY-month gross $552,328.93, with caveats: $40,213.29 held (status 6), −$1,843.59 gateway refunds not reflected in order status, 50 cancels/refunds already excluded, and no fee/net published.

### B. Reproducing dashboard numbers by hand

- Anchor windows explicitly (dataset ends 2019-12-31 16:51:39 UTC; `now()`-anchored queries return nothing today).
- Use the `item_orders` CTE pattern; do **not** add a status filter to best_sellers/brand/category/daily-KPIs customer counts (they don't have one); do add `status=1` when matching `top_products`, `kpi_daily`, trending, statements.
- Verified reference values at anchor 2019-12-31: revenue widget $139,598.13 (naive variant $410,387.39); kpi actives 1,152 (11:15 run) / 1,150 (day-end anchor); board actives 0; registered conversion 30 / $18,155.71.

### C. Where everything lives

- Repo: `/home/susnato/lb/runs/claude-fable-5/r2/workspace/novamart` @ `5ae1182`; old dashboard SQL at `41e3537^:dashboards/`.
- Warehouse: BQ emulator `http://localhost:9054`, project `novamart-warehouse` (`source access-pack/env.sh`; note: the stock `bq` CLI crashes on some UNION queries — a Python client works, see `q.py`).
- Serving replica: Postgres `localhost:15437`, db/user `novamart` (same source as Redash data source 1), helper `pg.py`.
- Redash: `http://localhost:5054`, 9 dashboards; full SQL dump in `redash_queries.txt`.
- Intermediate artifacts in this directory: `evidence_notes.md` (all query results backing this doc), `git_log.txt`, `schema_novamart.csv`, `schema_analytics.csv`, `view_definitions.json`, `daily_report_vs_raw.csv`, `redash_queries.txt`, `q.py`, `pg.py`.

### D. Open risks / recommended follow-ups (not yet done by anyone)

1. Book a statement override for the October replay-duplicate overhang (+$58.8k) or formally accept it.
2. Backfill `report_rows` for 2019-11-15 (empty), 2019-11-17 (−$75k), 2019-11-03 (DST), or annotate the KPI dashboard.
3. Decommission the legacy `affinity` job/table (widget-unused per `docs/affinity_lineage.md`; confirm no external readers first).
4. Fix the taxonomy migration (insert new names into `category_names` with correct `valid_from`; today's history rows are unreachable).
5. Decide what "contactable"/"board actives" should mean given placeholder emails; both currently compute 0.
6. Fix `scripts/rerun_kpis.py` to pass `constants.DISCOUNT_CAP`.
7. December 2019 statement was never generated; if the business needs it, run `monthly_statement` logic against the frozen data.
