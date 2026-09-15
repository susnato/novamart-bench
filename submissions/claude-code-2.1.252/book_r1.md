# Novamart Tribal Knowledge

- **Run ID:** `c8246f49-f049-4887-a4c5-c5fedc971445`
- **Started:** Thu Aug 27 17:09:22 IST 2026
- **Evidence sources (only these were used):**
  - Codebase: `<workspace>/novamart` pinned at commit `2ae79e2` (112 commits, 2019-09-15 → 2020-01-05)
  - Warehouse: BigQuery project `<warehouse-project>`, datasets `novamart`, `novamart_analytics`, `novamart_logs`
  - Dashboards: Redash at `<redash-url>` (9 dashboards / 9 queries, read-only)
- Citation convention: `commit <hash>` = git commit in the repo; `dataset.table` = BigQuery table/view; "query N (name)" = Redash query id; log evidence = `novamart_logs.db_queries` / `app_events` / `job_runs` rows quoted or aggregated. All verification SQL is in Appendix D.

---

## 1. Summary

Novamart is a marketplace backend: a FastAPI + Postgres service (`README.md`, commit `2da4141`) that ingests storefront traffic (product views, carts, payment-gateway order callbacks), a fleet of 16 scheduled batch jobs that produce every reporting/serving table, and 9 Redash dashboards. Business data covers **2019-09-25 → 2019-12-31** (min/max `created_at` across `novamart.orders`, `novamart.users`); in January 2020 the platform migrated: dashboards to Redash (commit `57ea43a`), schedules from `crontab.txt` to Airflow (commit `43e54a1`), and a one-shot copy of the serving Postgres into BigQuery (commit `2ae79e2`, `novamart/jobs/warehouse_backfill.py`). **All 9 Redash dashboards still query the Postgres serving replica (Redash data source 1, "novamart serving (Cloud SQL)", type `pg`), not BigQuery** — the warehouse is an analysis copy.

The ten facts a tenured person knows that nobody writes down (each expanded below, with evidence):

1. **Monthly revenue truth is layered**: `novamart.statements` (as-published, append-only) → `novamart_analytics.statements_corrected` (fee override for Oct) → `novamart_analytics.statements_final` (chargebacks subtracted). October 2019 net is 1,194,652.79 / 1,194,652.93 / 1,191,085.36 respectively (`docs/restatement_policy.md`, verified against the three tables/views).
2. **October revenue is still inflated by ~58,828.24** from 151 duplicate orders created by payment-callback retries before idempotency landed (commit `b676969`, 2019-10-15). The duplicates were flagged nightly by `reconcile` (10,766 `duplicate_payment_ref` warnings in `app_events`) but never removed or restated — they sit in every statement layer including `statements_final`.
3. **September 2019 revenue cannot be recomputed from orders**: all 12 September orders (gross 2,702.00, matching the statement exactly) were later flipped to cancelled/refunded in weekly November batches, so a `status = 1` recompute yields zero. Only `novamart.statements` preserves the published number.
4. **There is no December 2019 statement** — the warehouse snapshot ends 2019-12-31, before the monthly job's Jan 1 run. Best recompute using statement logic: gross 552,328.93 / net 535,728.67 (partial day Dec 31; 40,213.29 more is sitting in 12 fraud-held status-6 orders).
5. **The company runs three different "active customers" definitions** that disagree wildly on the same day: nightly rollup `novamart_analytics.kpi_daily` = 1,152 on Dec 31; the board-deck query (query 1, `actives_board`) computes ≈ **0** because its email-hygiene filters exclude the placeholder `@example.com` emails that ~99.9% of users have; the exec dashboard (query 5, `daily_kpis`) counts per-day buyers (54 on partial Dec 31). Documented in `docs/metrics_definitions.md`, verified by recomputation.
6. **`contactable_customers` on the exec KPI dashboard is structurally 0**: the `analytics.contactable_users` view has zero rows because every "real" email in `novamart.users` is `@gmail.example`, which the view excludes.
7. **The similar-products widget served its trending fallback for ~76–83% of traffic, and every one of the 534,145 fallback serves recommended a QA test SKU** — the fallback path in `novamart/routers/similar.py` is the only serve path that does not filter `EXCLUDED_SKUS`. Real customers bought test SKUs 1004856/1002544 for ~107k of status-1 revenue, which is excluded from daily reports but **included** in monthly statements.
8. **The daily report silently undercounted busy days before 2019-11-19** (`fetchmany(REPORT_SCAN_CAP=500)`, fixed in commit `1233af8`): Nov 17 alone is missing 74,995.96 in `novamart.report_rows` and was never backfilled, so dashboard history understates it forever.
9. **"Refunds" on the refunds dashboard mixes three different things** (`analytics.refunds_unified`): full-price cancellations, full-price legacy status flips, and actual gateway refund amounts (v2, commit `c49a7bb`) — and v2 gateway refunds **never reduce any statement revenue number** because statements read `orders.price` + `payments.fee` only.
10. **The trained rec model v4 does not demonstrably work**: its label is "user placed *any* later order," not "converted on a recommendation," its output is affinity-v2 scores rescaled by one coefficient, and its nightly coefficients flip sign day to day (`novamart_analytics.model_registry`).

---

## 2. Why this project

This document exists to transfer the tribal knowledge needed for three goals (from the task brief):

- **Phase 1 — Finance numbers end-to-end**: be able to answer "what was revenue in month X, and why" the way a tenured finance/data person would — including which of the several conflicting numbers is the right one for a given purpose, and which published numbers are unreproducible or known-wrong.
- **Phase 2 — Product & customer analytics**: explain any number on the 9 dashboards, including the ones that should not be trusted at face value (board actives ≈ 0, contactable = 0, best-sellers with no status filter, refunds mixing cancellations).
- **Phase 3 — ML systems & batch jobs**: judge whether the recommendation/fraud/pricing/forecast systems actually work, and modify the 16 batch jobs safely (knowing each table's overwrite semantics, the scheduler migration's dropped run, and what breaks downstream when a job fails).

The knowledge here was reconstructed exclusively from the repo (code + git history + `docs/`), the BigQuery warehouse (data + the exported Postgres statement log `novamart_logs.db_queries`, app log `app_events`, job log `job_runs`), and the Redash API. Nothing was mutated anywhere; every Redash/BigQuery access was read-only.

---

## 3. Business understanding

### What the business is

A retail marketplace ("novamart marketplace" — `README.md`). ~81,018 products (`novamart.products`), ~38,950 shopper records (`novamart.users`), 9,127 orders totaling ~2.97M gross across Sept 25 – Dec 31 2019 (`novamart.orders`). Product catalog spans electronics (apple/samsung dominate revenue: 1.40M and 0.52M status-1 revenue respectively), appliances, apparel, construction, kids (category codes in `analytics.category_names`). Vendors are wholesale feeds (`novamart/onboarding.py` VENDORS list); prices arrive via a vendor price feed (`POST /catalog/prices`, `novamart/routers/catalog.py`, 13 `price_feed_received` events in `app_events`).

### How money is made (order lifecycle)

- **Orders are created from payment-gateway callbacks**, not a checkout UI: `POST /orders` receives `{uid, pid, price, ref, session, ts}` (`novamart/routers/orders.py`). The price charged is whatever the callback says — there is no lookup against `products.list_price`.
- **Multi-item orders** exist since 2019-11-22: callbacks in the same `session` within 15 minutes merge into one order; each item becomes a `novamart.order_lines` row and the order's `price` accumulates the total (commit `5d1300d` "Merge same-session order callbacks into recent orders"; first `order_lines` statement in `db_queries` at 2019-11-22 15:00Z). Before that, one order = one item; `orders.product_id`/`orders.price` are the item. **Consequence**: for merged orders, `orders.product_id` is only the *first* item, so any query that joins brand/category via `orders.product_id` (e.g. `/reports/brands` in `novamart/routers/reports.py`, `daily_kpis` customer CTE) attributes the whole order to the first item's brand.
- **Fees**: each payment carries `fee = round(price * 0.029 + 0.30, 2)` (`novamart/constants.py` FEE_RATE/FEE_FLAT). The flat $0.30 was added by the November processor fee change effective 2019-11-20 (commit `12e1c68`; `FEE_CHANGE_AT` in `novamart/jobs/monthly_statement.py`). Because each *line callback* creates its own payments row, a 3-item order pays the $0.30 three times — this is why the Dec 1 statement run logged `statement_fee_mismatch` with collected fees 170.41 *above* the per-order expectation (`app_events` 2019-12-01, delta -170.41), and why the "November audit correction" concluded delta = 0 (`analytics.statement_corrections`, commit `4a58d17`).
- **Idempotency**: callbacks are replayed by the gateway (522 `order_callback_replayed` events). Made idempotent by `payment_ref` on 2019-10-15 (commit `b676969`). Before that, retries created duplicate orders — see §4 (October inflation).
- **Cancellations** (`POST /orders/{id}/cancel` → status 2, commit `8f19718`) and **legacy refunds** (`POST /orders/{id}/refund` → status 3, commit `d87cb3d`) are status flips only — no money-movement row is written. Since 2019-12-04, **refunds v2**: the gateway is the source of truth for money and posts `POST /payments/gateway_refund`, which inserts a *negative* payments row (gross = -amount, fee = 0) without touching order status (commit `c49a7bb`, `novamart/routers/payments_webhook.py`). 9 gateway refunds totaling 1,843.59 exist, all December (`novamart.payments` where gross < 0).
- **Fraud holds**: nightly `fraud_score` job moves orders scoring above threshold to status 6 (held). 12 orders (40,213.29) are currently held, including a Dec 3 wave of 8 near-$3,000 orders all scoring 1.0 (`novamart_analytics.order_risk` joined to orders).

### Partnerships & catalog quirks (why dashboards exclude things)

- **Lucente**: a partner brand whose 676-product catalog import began 2019-10-01 (first lucente product `created_at` 2019-10-01 03:10Z). Hidden from reports "per partnerships" on 2019-10-25 (commit `ba1fbfa`, `BRAND_DENYLIST`). It still sells (~43k status-1 revenue Oct–Dec) — the revenue is in statements but invisible on dashboards and daily reports.
- **Jetem**: added to the denylist 2019-12-15 (commit `1169e40`). Only 5 jetem products exist (first 2019-10-15) and **zero orders ever** — the exclusion is currently a no-op safeguard.
- **QA smoke account**: `user_id = 424242` (email `cust424242@gmail.example`) places $9.99 test orders on SKU 1004856 roughly weekly (14 orders). Registered in `analytics.test_users` (manual insert 2019-11-27, `db_queries` `[engineer-backfill:dev]`) and hard-excluded in dashboards (commit `b59f077`). A second QA identity — account UUID `cc27b436-d6f9-4e84-adaf-e716025dd369` — was created 2019-12-01 and is string-excluded only in the brand-revenue dashboard (commit `adbcb7e`; `docs/dashboard_notes.md`).
- **Test SKUs**: `EXCLUDED_SKUS = [1004856, 1002544]` since 2019-10-08 (commit `83fb3ed`). 1004856 is literally "Internal Test #4856" (brand `internal`, category `qa.test`, $9.99). **But** 1002544 is titled "Unbranded Item #2544", brand `apple`, category `electronics.smartphone`, list 635.14 — and real customers bought both (453 non-QA orders, ~107k). See §4 for why that matters and §7 for why customers were steered to them.
- **Blank brands**: products are auto-created on first sight with empty metadata (`ensure_entities` in `novamart/routers/catalog.py`, "cheap MVP bootstrap"); later catalog events could not always repair them (`ON CONFLICT DO NOTHING` + in-process known-id cache). 640 status-1 orders (~84.8k) have blank-brand products. The investigation snapshot lives in `analytics.blank_brand_products` (manual CTAS 2019-10-21, `db_queries`), with `suspected_cause` per product; repair logic was added in commits `ea0e97b` and `d213f6e`.
- **Registered-accounts beta**: 30 UUID accounts created 2019-12-01 16:30Z (`novamart.accounts`, `account_map`; endpoint added in commit `b567d9d`). Two id namespaces exist — legacy numeric `users.id` on all orders vs UUID `accounts.account_id` — mapped via shared email or `account_map` (both give the same 30 links). The registered-conversion dashboard (query 7) was fixed on 2019-12-21 to map UUIDs back to numeric ids (commit `b975479`): 30 registered buyers, 18,155.71 status-1 revenue (recomputed, matches approach).
- **People**: commits are authored by Maya Iyer and Dev Kapoor (54 each) plus "Novamart Platform" (4 migration commits). The manual-intervention history in `db_queries` uses session tags `[engineer:maya]`, `[engineer:dev]`, `[engineer-backfill:*]` — Maya did the October duplicate-ref investigation and the Dec 29 fraud-hold release; Dev did the statement overrides, chargeback booking, and most analytics DDL.

---

## 4. Metrics

### 4.1 Monthly revenue — the canonical numbers and why

**Source-of-truth policy** (`docs/restatement_policy.md`, commit `a576d0d`): *as-published* numbers come from `novamart.statements` (append-only snapshots written by `novamart/jobs/monthly_statement.py` on the 1st, 06:30 ET); *current finance* numbers come from `novamart_analytics.statements_final`. The middle layer `statements_corrected` applies `analytics.statement_overrides`.

| Month | Published gross / fee / net (`novamart.statements`) | Corrected (`statements_corrected`) | Final (`statements_final`) | Orders |
|---|---|---|---|---|
| 2019-09 | 2,702.00 / 78.36 / 2,623.64 | unchanged | unchanged | 12 |
| 2019-10 | 1,230,332.43 / 35,679.64 / 1,194,652.79 | fee → 35,679.50, net → 1,194,652.93 | gross → 1,226,764.86, net → **1,191,085.36** | 3,765 |
| 2019-11 | 1,101,397.01 / 32,110.92 / 1,069,286.09 | unchanged | unchanged | 3,582 |
| 2019-12 | **no statement exists** (snapshot ends before the Jan 1 run) | — | — | — |

**Statement math** (`novamart/jobs/monthly_statement.py`): gross = `SUM(orders.price)` for `status = 1` orders whose `created_at` falls in the *America/New_York* month (`timeutil.local_month_window_utc`); fee = `SUM(payments.fee)` joined via those orders (collected fees — fixed by commit `a92c96d` after the Nov 1 run wrote the *computed* fee instead, which is exactly what the Oct override corrects; note in `analytics.statement_overrides`); net = gross − fee. No SKU/brand/test-user exclusions. An `expected_fee` cross-check models the 2019-11-20 fee change and logs `statement_fee_mismatch` on >1¢ delta — it fired on all three runs (−0.01 rounding for Sept; +0.14 for Oct; −170.41 for Nov from per-line flat fees, see §3).

**Restatement mechanics** (all found in `db_queries` `[engineer-backfill:dev]` sessions — none of this is in schema.sql):
- 2019-11-02: `analytics.statement_overrides` created; October override inserted (fee 35,679.50 = collected); `statements_corrected` view created.
- 2019-12-09: `analytics.chargebacks` created and backfilled with **the 3 earliest October status-1 orders with price > 700**, full order price booked as chargeback amount (3,567.57 total), `reported_at` backdated to 2019-12-01; `statements_final` view created (subtracts chargebacks from gross and net of the *order's* month; fee untouched). Commit `cd559d3` is the paired repo commit.
- 2019-12-02: `analytics.statement_corrections` audit row for November (delta 0 — the fee gap was legitimate per-transaction flat fees; commit `4a58d17`).

**Why the published numbers can't be reproduced from raw orders today:**
- *September*: all 12 orders (sum exactly 2,702.00) were flipped to status 2/3 in weekly Tuesday-16:00Z batches during November (`orders.updated_at` = Nov 5/12/19/26). Recomputing `status = 1` September gross gives **0**.
- *October*: recomputed status-1 gross is 1,206,337.32 vs published 1,230,332.43. The 23,995.11 gap is *exactly* the later cancels (10,748.42) + legacy refunds (13,246.69) of October orders.
- *October is also over-stated*: before idempotency (commit `b676969`, Oct 15), gateway retries created 130 duplicate `payment_ref` groups → 151 surplus orders still `status = 1` totaling **58,828.24**, each with its own payments row (fees double-collected too). Maya investigated on Oct 15 (`db_queries` `[engineer:maya]` duplicate-ref queries) and `reconcile` has flagged them nightly ever since (10,766 `duplicate_payment_ref` warnings in `app_events`), but no restatement was ever booked. Every layer including `statements_final` contains this inflation.
- *Gateway refunds don't touch statements at all*: they are negative `payments` rows with fee = 0 and no order-status change, and statement math reads only `orders.price` (status 1) and `payments.fee`. December's 1,843.59 of gateway refunds would be invisible to a December statement.

**"What was revenue in December 2019?"** — the tenured answer: *There is no December statement; the December close never ran before the platform froze. Recomputing with statement logic on the warehouse snapshot: gross 552,328.93, collected fees 16,600.26, net 535,728.67 across 1,756 status-1 orders — knowing that (a) Dec 31 is partial (orders end 16:51Z ≈ 11:51 ET), (b) 12 held orders worth 40,213.29 are excluded and may later be released or cancelled, (c) 1,843.59 of gateway refunds is not netted out, and (d) if you instead sum the daily report (`report_rows`), you get 535,561.72 — but that excludes lucente/jetem/test SKUs/test users and is missing Dec 31 entirely (last `report_date` is 2019-12-30).*

### 4.2 Daily revenue (report_rows) and its history

`novamart/jobs/daily_report.py` (06:00 ET daily) writes yesterday's per-product units/revenue into `novamart.report_rows` (append-only; re-runs would add a second `created_at` version — none exist in the snapshot, so `MAX(created_at)` per date is safe but required, per query 8's comment). Since commit `92596dc` (2019-12-05) it counts **per item** from `order_lines` with a legacy fallback to `orders` rows. Exclusions: statuses (see below), `analytics.test_users`, `EXCLUDED_SKUS`, `BRAND_DENYLIST` — all read at *run time*, so historical rows reflect the rules of their day:

- Until 2019-10-25, lucente was **in** the daily report; until 2019-12-15, jetem was (vacuously) in.
- Until 2019-11-18 (commit `11c0a42`), `EXCLUDED_STATUSES` was `[0]` — cancelled/refunded orders **counted**.
- Until 2019-11-19 (commit `1233af8`), the job read only `fetchmany(REPORT_SCAN_CAP = 500)` rows: busy days were silently truncated. **Worst case 2019-11-17: report shows 487 units / 148,857.07 vs a clean recompute of 704 units / 223,853.03 — 74,995.96 missing.** Never backfilled (no second snapshot version exists for that date). `REPORT_SCAN_CAP` still sits in `novamart/constants.py` but is dead code.
- The daily windows are true **local (America/New_York) days** including the DST fall-back 25-hour day (commit `102c9b4`, `timeutil.local_day_window_utc`).

`novamart.report_rows_intraday` (since 2019-12-08, commit `a2e0013`; table DDL via `[engineer-backfill:dev]` in `db_queries`) holds append-only *partial-day* snapshots for "today", written 12:00 ET and 17:00 ET (47 runs in `job_runs` = 24 days × 2 − 1). Consumers must take only the latest `created_at` per date — the exec revenue widget originally summed **all** snapshots and double-counted (commit `686a5d6`, fixed 2019-12-24 by commit `3eced24`; the current Redash query 8 SQL is byte-identical to the fixed file).

### 4.3 Active customers — three definitions that never agree

(Reference: `docs/metrics_definitions.md`, commit `dd0c8fc`; all three recomputed on the warehouse, Appendix D.)

| Definition | Where | Rules | Value @ 2019-12-31 |
|---|---|---|---|
| Nightly rollup | `novamart_analytics.kpi_daily` (job `kpi_daily`, 06:15 ET, commit `14726e7`) | distinct buyers, trailing 30×24h, `status = 1`, **no exclusions** | **1,152** (table) / 1,146 recomputed at 23:59Z |
| Exec dashboard | query 5 `daily_kpis` | distinct buyers per ET calendar day, **no status filter**, excludes 424242 + lucente/jetem (brand via first product) | 54 on (partial) Dec 31 |
| Board deck | query 1 `actives_board` (commit `2dde4f0`) | trailing 30d, excludes statuses {0,2,3} (**status 6 held still counts**), excludes `analytics.test_users` + email-heuristic test/internal accounts | **≈ 0** |

The board number is the one that must never be trusted at face value: its email hygiene excludes domain `example.com` *and* `%.example` — but the app synthesizes **every** shopper email as `user{id}@example.com` (`novamart/routers/catalog.py` `_user_row`), and the only 40 updated emails are `cust…@gmail.example`. The filter therefore removes essentially the entire customer base.

### 4.4 Contactable customers — always zero

`analytics.contactable_users` (view, created 2019-12-04 by `[engineer-backfill:maya]`, commit `e10cb0c`) = `marketing_opt_in` AND syntactically valid email AND domain not example.com/.net/.org and not `%.example`. Result: **0 rows** (38,910 of 38,950 users have `@example.com`; the 40 others are `@gmail.example`). So `contactable_customers` on the exec KPI dashboard is structurally 0. Meanwhile the **email digest** uses a *different* definition — `email NOT LIKE '%@example.com'` (`novamart/jobs/email_digest.py`) — and happily reports 40 recipients nightly (`analytics.digest_log`), all of them undeliverable `.example` addresses.

### 4.5 Refunds

Query 6 (`refunds`) reads `analytics.refunds_unified` (view, created 2019-12-23 by `[engineer-backfill:dev]`, commit `a3bffec`), which unions three kinds: `order_cancelled` (status 2, **full order price**, timestamped by `updated_at`), `order_refunded` (status 3, full price, `updated_at`), `gateway_refund` (negative payments, actual amount, payment `created_at`). Current totals: 54 / 13,249.64, 28 / 13,447.47, 9 / 1,843.59. Caveats a tenured person mentions: (a) cancellations aren't refunds of money; (b) legacy events are dated by the *flip* time, so September/October orders cancelled in November all pile into the November bucket; (c) an order that both got status-flipped *and* gateway-refunded would double-count (currently none do — verified); (d) none of this feeds statements (§4.1).

### 4.6 Best sellers / brand / category revenue

- Query 2 (`best_sellers`, 7-day rolling), query 3 (`brand_revenue`, 30-day), query 4 (`category_revenue`, 30-day) all share: per-item counting from `order_lines` with legacy `orders` fallback (commit `92596dc`), exclude 424242 (+ the UUID string in brand_revenue), exclude lucente/jetem, **no order-status filter**, rank by revenue (not units). `docs/dashboard_notes.md` (commit `a9a4b0b`) is the checklist for reproducing them by hand.
- The nightly `top_sellers` job (06:45 ET, commit `9a51155`) writing `novamart.top_products` is a *different* metric: `status = 1` only, counts **order rows** (multi-item orders count once, attributed to the first product), ranked by units. Its numbers will not match the best-sellers dashboard; that's expected.
- Category revenue uses the **versioned taxonomy**: `analytics.category_names` (current) + `analytics.category_name_history`, with `valid_from` dating and a temporal lateral join, so a sale is labeled with the display group in force on its order date (commit `33054cd`; initial mapping backfilled 2019-11-30 and the 2019-12-12 renames — `construction.tools.light%` → `lighting`, `electronics.audio%` → `entertainment` — recorded in both tables via `[engineer-backfill:dev]`). Unmapped codes fall to `'other'`.

### 4.7 Funnel & sessions

`novamart_analytics.daily_funnel` (job `funnel`, 06:20 ET, commit `4dbcf7f`): sessionizes cart+order events per user with an inactivity gap. The gap changed **30 → 120 minutes** on 2019-12-14 (commit `f915c1b`), so session counts before/after are not comparable. Series runs 2019-11-09 →; sessions jumped Dec 16 (416) with holiday traffic.

---

## 5. System

### 5.1 Service

FastAPI app (`novamart/app.py`) with routers: `catalog` (product views, vendor price feed, entity bootstrap + brand repair), `carts`, `orders` (create/cancel/refund), `similar` (rec widget), `payments_webhook` (gateway refunds), plus `accounts`, `users` (email update, commit `088a372`), `reports` (`/reports/brands` monthly endpoint, commit `193f22d`). DB access via async pool; **every SQL statement is logged** in Postgres `log_statement` style (`novamart/db.py`, `novamart/logutil.py`) — that log is exported to `novamart_logs.db_queries` (3.6M rows; `novamart_logs.db_queries_normalized` view reshapes it into a BigQuery-jobs-like schema). App JSONL log → `novamart_logs.app_events` (1.57M rows); job log → `novamart_logs.job_runs` (978 rows).

Actor tags in `db_queries`: `[app]` (3.27M), `[job]` (331k), and 191 human-session statements (`[engineer:maya]`, `[engineer:dev]`, `[engineer-backfill:*]`) — the latter are the complete record of manual DDL/DML: every `analytics.*` table/view creation, the statement override, the chargeback backfill, the test-user registration, the taxonomy renames, and the 2019-12-29 hold release (`UPDATE orders SET status = 1 ... WHERE status = 6 AND price < 2600` — 5 orders, 10,859.73, matching commit `1cb8721`).

### 5.2 Batch jobs (the complete roster)

Times are the original `crontab.txt` local (ET) times; Airflow DAG in `airflow/dags/` since Jan 2020 (commit `43e54a1`).

| Job (module) | Schedule | Writes | Semantics | Notes / breakage |
|---|---|---|---|---|
| `reconcile` | 03:00 (was 02:00; moved commit `388370b`) | app_events warnings only | read-only | Flags payment_refs on >1 order, `status <> 5` (status 5 never existed anywhere — dead filter from initial import), cap `RECONCILE_BATCH` 100→200 (commit `030d841`). Nobody consumes the flags. |
| `affinity` | 03:30 | `analytics.product_affinity` | **delete-all + insert** | v1 co-cart pairs, 30d, exp decay, `-1` sentinel for <3 pairs. **Unused by serving since 2019-12-06** but still runs (`docs/affinity_lineage.md`; last `[app]` read of v1 2019-12-06 16:39Z, first v2 read 16:40Z). |
| `affinity_v2` | 03:45 | `analytics.product_affinity_v2` | delete-all + insert | Conversion-weighted (cart=1, order=3), same-category ×1.15, price-ratio damping, monthly seasonal factor. **Crashed Dec 3–5** (`job_runs` ERROR `job_crashed`: `SEASONAL_FACTORS[t.month-1]` IndexError — the hand-entered list had only Jan–Nov); fixed commit `3dbe4d7`. Rows stamped `model_version = 2.0.1` while serving flag says `2.0.0` — known naming mismatch. |
| `model_train` | 04:15 | `analytics.model_registry`, `analytics.model_scores` | registry append; scores delete+insert | Rec model v4 — see §7. |
| `price_suggest` | 04:45 | `analytics.price_suggestions` | delete-all + insert | Dynamic-pricing **shadow**; phase 2 ON HOLD per exec/legal (commit `cca9b0d`, code NOTE). Zero SELECTs against the table in all of `db_queries` — verified. |
| `trending` | 05:15 | `analytics.trending_daily` | delete+insert per day | status=1, min 5 units, decay 0.05, top 50. Window **60d → 30d** on 2019-12-06 (commit `f563dea`); README's "60-day" note is stale — `docs/trending_notes.md` is right, and `job_runs` shows `window_days` flip on Dec 7. Feeds homepage and the rec fallback. **No test-SKU exclusion** — Dec 31 top-3 includes both test SKUs. |
| `fraud_score` | 05:45 | `analytics.order_risk` (+ mutates `orders.status`→6) | append | `core = min(price/3000, 1)`, +15% each for new-account (<7d) / high-velocity (3+ orders in 24h). Threshold 0.90 → 0.70 (commit `53f6f6c`) → 0.85 with sub-$2,600 release (commit `1cb8721`). This is the **only job that mutates order data**. |
| `daily_report` | 06:00 | `novamart.report_rows` | append (versioned by `created_at`) | See §4.2. Failure = missing day on the KPI dashboard and revenue widget history. |
| `kpi_daily` | 06:15 | `analytics.kpi_daily` | append | 30d active buyers, status=1, no exclusions. |
| `funnel` | 06:20 | `analytics.daily_funnel` | append | Gap 30→120 min (commit `f915c1b`). |
| `monthly_statement` | 06:30 on the 1st | `novamart.statements` | append | See §4.1. Failure = no statement for the month (this actually happened for Dec, by migration timing). |
| `top_sellers` | 06:45 | `novamart.top_products` | append | Order-level units, status=1. |
| `reorder_forecast` | 06:50 | `analytics.reorder_hints` | delete-all + insert | ADVISORY heuristic `BASE + K/(velocity+C)` (15.6, 162.4→refit commit `f85cdd2`, 1.8), top-200 by 14d paid velocity. **Hints grow as velocity falls** — do not treat as buy quantities (`docs/forecast_caveats.md`, README). |
| `email_digest` | 07:15 | `analytics.digest_log` | append | Gated by `ENABLE_DIGEST` in `deploy/cron.env`. Broken silently Nov 28 – Dec 16 (flag never reached the job): fixed twice — commit `8dc520b`, then commit `0bd4eac` reads the file directly. First real send 2019-12-17 (`digest_log`). Top product = raw 7d status-1 order count — it promoted test SKUs 1002544/1004856 for the first 5 sends. |
| `intraday_report` | 12:00 & 17:00 | `novamart.report_rows_intraday` | append (versioned) | See §4.2. |
| `warehouse_backfill` | manual (schedule=None) | BigQuery datasets | `bq load --replace` | Per-table `gcloud sql export csv` → `bq load`, driven by `novamart/jobs/warehouse_manifest.json` (schema of record for the BQ copy). |

**Scheduler-migration gotchas** (compare `crontab.txt` vs `airflow/dags/*.py`):
1. The **17:00 intraday run was dropped**: crontab had `12:00` and `17:00` daily; `intraday_report_dag.py` has only `schedule="0 12 * * *"`.
2. Cron times were **local ET** ("times are local", `crontab.txt`); Airflow schedules are plain cron strings with no timezone declared — under Airflow's UTC default, every job would shift 5 hours earlier ET. The logs end 2019-12-31 so there is no run evidence either way; verify the Airflow instance timezone before trusting post-migration report dates.
3. `crontab.txt` is explicitly RETIRED (header comment) — the DAG files are the live schedule.

### 5.3 Deploy & CI

- Deploys are marked by `trigger deploy #d2p-novamart` commits — code changes take effect at the *next* deploy, not at commit time (e.g. funnel gap committed Dec 14, deploy `f96bdf1` same day).
- Feature flags: `deploy/flags.env` (`REC_MODEL_VERSION=2.0.0` — read at request time by `similar.py` `intended_version()`); job flags: `deploy/cron.env` (`ENABLE_DIGEST=1`).
- CI (`ci/run_ci.py`): boots the app on a scratch DB, drives view→cart→order, checks order/payment row consistency, then runs reconcile/daily_report/monthly_statement under `FAKE_NOW`. `timeutil.now()` honors `FAKE_NOW` only for test rigs.

### 5.4 Dashboards (Redash)

9 dashboards, one query each, ids: 1 `actives_board`, 2 `best_sellers`, 3 `brand_revenue`, 4 `category_revenue`, 5 `daily_kpis`, 6 `refunds`, 7 `registered_conversion`, 8 `revenue_widget`, 9 `statements_final` (which is just `SELECT * FROM analytics.statements_final ORDER BY month`). All use data source 1 = Postgres serving replica ("novamart serving (Cloud SQL)"); a BigQuery source (id 2) exists but nothing uses it. The SQL was migrated verbatim from the repo's old `dashboards/` directory (deleted in commit `57ea43a`; recoverable via `git show <hash>:dashboards/<file>.sql`). Query 8's `updated_at` shows a 2026-08-19 touch, but its text is byte-identical to the final repo version (fix `3eced24`) — no drift.

---

## 6. Data

### 6.1 Where data lives

(Post-migration map: `docs/data-access.md`, commit `1179287`.)

- **Serving Postgres** (Cloud SQL `novamart-prod-replica`): what the app and Redash read. Two schemas: `public` (app tables) and `analytics` (batch/analyst scratch — "app tables stay clean", `schema.sql`).
- **BigQuery `<warehouse-project>`**: `novamart` = copy of `public.*` (12 tables), `novamart_analytics` = copy of `analytics.*` (19 tables) **plus 5 views recreated in BQ dialect** (`contactable_users`, `refunds_unified`, `statements_corrected`, `statements_final`, `db_queries_normalized` — definitions retrieved from `INFORMATION_SCHEMA.VIEWS`, saved in `bq_view_definitions.json` in this run's folder), `novamart_logs` = log exports.
- `schema.sql` is only the *initial* schema. Tables added later were created by application code at runtime (`order_lines`, `accounts`, `account_map` — `CREATE TABLE IF NOT EXISTS` inside `novamart/routers/orders.py` / `accounts.py`; `report_rows_intraday`, `top_products` and all `analytics.*` job tables — inside jobs) or by hand (`analytics` views/backfills — see the `[engineer-backfill:*]` ledger in `db_queries`). `novamart/jobs/warehouse_manifest.json` is the closest thing to a complete, typed schema census.

### 6.2 Core tables and their sharp edges

| Table | Key facts (evidence) |
|---|---|
| `novamart.orders` | One row per order; `price` = *sum of lines* after 2019-11-22 merges; `product_id` = first item only; `payment_ref` unique only after commit `b676969`; statuses: 1 paid (9,033), 2 cancelled (54), 3 refunded (28), 6 fraud-held (12); status 0 = pending-at-create (transient), 4 = pre-Oct-28 cancelled code (commit `8f19718`; none survive), 5 = never used. |
| `novamart.order_lines` | Item-level truth since 2019-11-22 (2,284 rows); older orders have none — always use the union-with-fallback pattern (commit `92596dc`). |
| `novamart.payments` | One row per *callback* (9,361 = 9,127 creates + 225 appended lines + 9 negative refunds); fee per line includes its own $0.30 after Nov 20; negative rows are gateway refunds; `payment_ref` column added later by app DDL (nullable on old rows). |
| `novamart.users` | 38,950; emails are synthesized placeholders `user{id}@example.com` except 40 `@gmail.example` updates — this poisons every email-based filter (§4.3/4.4). Profile fields (region, channel, device…) are deterministic synthetics from the id (`novamart/onboarding.py`). |
| `novamart.products` | 81,018; created on first sight, possibly with blank metadata (see blank-brand story §3); `list_price` updated by vendor feed with history in `analytics.price_history` (1,400 rows since 2019-11-18, commit `795d273`). |
| `novamart.report_rows` / `report_rows_intraday` | Append-only, versioned by `created_at`; latest-version-per-date is mandatory; intraday only for "today". |
| `novamart.statements` | Append-only as-published monthly snapshots. Never overwrite — restatements go through `analytics.statement_overrides` / `chargebacks`. |
| `analytics.kpi_daily`, `daily_funnel`, `digest_log`, `order_risk`, `model_registry` | Append-only history. |
| `analytics.trending_daily` | Delete+insert per day (history preserved across days). |
| `analytics.product_affinity(_v2)`, `model_scores`, `price_suggestions`, `reorder_hints` | **Full overwrite nightly — no history**; don't audit yesterday from them. |
| `analytics.rec_decision_log` | Every widget serve: intended/effective version, source, fallback reason, arm. 667,850 rows; ~1,340 random-arm rows missing for Dec 18 (see §7). |
| `novamart_logs.db_queries` | Every SQL statement ever executed (app/job/human) with timestamps — the forensic backbone; use `db_queries_normalized` for parsed access. |

### 6.3 Lineage (who writes → who reads)

- `orders`/`order_lines`/`payments` ← app callbacks → read by: daily/intraday reports, monthly statement, kpi_daily, top_sellers, trending, fraud_score, reorder_forecast, price_suggest, affinity_v2 (conversion check), model_train (labels), all dashboards.
- `cart_items` ← app → affinity v1/v2, funnel.
- `report_rows(_intraday)` ← report jobs → queries 5 & 8 (the only dashboard surfaces reading report tables — everything else reads orders directly).
- `product_affinity_v2` → widget (flag 2.0.0) and → `model_scores` (rescored copy) → widget (flag 4.0.0). `product_affinity` (v1) → nothing since Dec 6 (safe-to-drop analysis: `docs/affinity_lineage.md`).
- `trending_daily` → homepage + widget fallback (the dominant serve path).
- `statements` → `statements_corrected` (+overrides) → `statements_final` (+chargebacks via orders join) → query 9.

### 6.4 Warehouse copy mechanics

`novamart/jobs/warehouse_backfill.py` (commit `2ae79e2`): per manifest table, `gcloud sql export csv` with explicit column casts (UTC-rendered timestamps, `__PGNULL__` sentinel) → `bq load --replace` into `novamart.*` / `novamart_analytics.*`. It is a manual, full-replace snapshot (DAG `schedule=None`) — the BQ copy is **frozen at 2019-12-31/Jan-2020** and will drift from serving until re-run. Anyone comparing "warehouse vs dashboard" numbers must remember the dashboards read live Postgres.

---

## 7. Experimentation

### 7.1 The recommendation experiment stack (the only real A/B machinery)

- **Assignment**: `in_random_arm(uid)` = `sha256(uid) % 20 == 0` → deterministic ~5% of users get uniform-random recommendations "for unbiased training data" (`novamart/routers/similar.py`, commit `df4ed85`, 2019-12-06). Not time-bounded, not configurable.
- **Version dispatch**: `REC_MODEL_VERSION` in `deploy/flags.env` — `2.0.0` (current) serves `analytics.product_affinity_v2`; `4.0.0` would serve `analytics.model_scores`; `1.0.0` retired (enum kept for old log rows). Version history: `docs/rec_versions.md` is literally "TBD" (commit `4396fbb`) — the real map lives in the `similar.py` docstring and `REC_VERSIONS` dict.
- **Logging**: every serve → `analytics.rec_decision_log` (and `rec_served` in `app_events`). **Known gap**: the Dec 17 refactor (commit `30e8907`) dropped random-arm logging; restored Dec 19 (commit `a00f24c`). Result: zero `arm='random'` rows on 2019-12-18 and a 1,340-row deficit vs `rec_served` events — any random-arm analysis spanning Dec 18 undercounts exposures.
- **What the log shows about serving quality** (Appendix D query): v1 era — 83% of serves fell back to trending (`no_scores`); v2 era (Dec 6–31) — model 52,695 (19%), fallback 207,959 (76%), random 14,566 (5%). Root cause: affinity coverage is tiny — 3,912 pair rows, 76% of them the `-1` "not enough data" sentinel (graduation gate, commit `fef5c96`), only 449 base products servable out of 81,018.
- **The fallback bug that moved real money**: the model and random paths filter `EXCLUDED_SKUS`; the **fallback path does not**, and trending includes test SKUs. Verified: **all 534,145 fallback serves contained a test SKU** in items; real (non-QA) customers placed 453 orders on SKUs 1004856/1002544 totaling ~107k, revenue that daily reports hide but statements include. If you ever wonder why "Internal Test #4856" sells: this is why, amplified by the email digest promoting it (§4.4).

### 7.2 Model v4 — does the ML actually work?

Judgment: **no evidence it works, several signs it can't.** (`novamart/jobs/model_train.py`, commit `a1946ff`; registry data.)

1. **Label leakage/mismatch**: the training label is "user placed *any* order after the exposure" (`EXISTS orders o WHERE o.created_at > d.ts`), not "bought a recommended item". A frequent shopper converts every exposure regardless of what was shown.
2. **Output is cosmetic**: `model_scores = affinity_v2_score × (1 + 0.1 × coef[n_items])` — a single global monotone rescale of v2 scores. Ranking within a base product is unchanged; flipping the flag to 4.0.0 would serve v2's ordering with different numbers.
3. **Instability**: nightly coefficients in `analytics.model_registry` flip sign across consecutive days (e.g. the 5th coefficient: −2.18 (Dec 24) → −0.96 (Dec 29) → +0.045 (Dec 30) → −0.156 (Dec 31); first coefficient −0.59 → −0.24). Train rows grow 9k → 14.4k but nothing converges.
4. **No evaluation exists**: no holdout, no CTR/conversion attribution of served items anywhere in repo or logs. The `opt_in` feature is fetched but deliberately unused ("calibration pending" note in code).
5. It has never served: flag has stayed `2.0.0` (`deploy/flags.env`).

### 7.3 Other experiment-like things

- **Dynamic pricing**: phase-1 shadow only (±5% nudges by demand median split, top-500, `analytics.price_suggestions`); serving phase 2 ON HOLD per exec/legal review (commits `894c535`, `cca9b0d`); zero reads of the table in `db_queries` (`docs/pricing_status.md` verified).
- **Fraud threshold tuning**: 0.90 (commit `e4656fb`, Dec 3) → 0.70 (commit `53f6f6c`, Dec 5) → 0.85 + manual release of held orders < $2,600 (commit `1cb8721`, Dec 29; the release UPDATE is in `db_queries` `[engineer-backfill:maya]`). 1,631 orders scored; 17 exceeded 0.70; 13 exceeded 0.85; 12 remain held.
- **Affinity v2 vs v1**: not an A/B — a hard cutover on deploy (Dec 6 16:40Z in `db_queries`), with v1 left running as an orphan job.
- **Seasonal factors**: hand-entered Jan–Nov list "from the 2019 planning sheet" (`affinity_v2.py`) — the December gap crashed the job for 3 days (§5.2) and the fix defaults season to 1.0 for December rather than adding a December value.
- **Metric-affecting parameter changes to know when reading history**: funnel gap 30→120 min (Dec 14); trending window 60→30d (Dec 6); reorder K refit 162.4 (Dec 21, commit `f85cdd2`); discount cap 0.25 in constants vs legacy 0.40 default in `novamart/jobs/discounts.py` (only caller is the ops one-off `scripts/rerun_kpis.py` — passing the right cap is on the operator).

---

## 8. Glossary

| Term | Meaning (evidence) |
|---|---|
| **Order status codes** | 0 = created/pending (transient during callback); 1 = paid/complete; 2 = cancelled (was 4 before commit `8f19718`); 3 = refunded (legacy flip, commit `d87cb3d`); 5 = never used anywhere (dead `status <> 5` filter in `reconcile.py` since initial import); 6 = fraud-held (`fraud_score.py`). |
| **payment_ref** | Gateway's payment id (`PR-…`); idempotency key after commit `b676969`. "Duplicate payment ref" = pre-fix retry artifact (130 refs, 151 surplus paid orders, Oct 2019). |
| **Session merge** | Same-`session` callbacks within 15 min append to the existing order as `order_lines` (commit `5d1300d`). |
| **Legacy fallback (per-item counting)** | `order_lines` UNION orders-without-lines pattern required for any per-item metric (commit `92596dc`). |
| **as-published vs corrected vs final** | `novamart.statements` → `analytics.statements_corrected` (overrides) → `analytics.statements_final` (minus chargebacks). Use final for current finance, statements for "what did we say then" (`docs/restatement_policy.md`). |
| **Statement overrides / corrections / chargebacks** | `analytics.statement_overrides` (replacement values, Oct fee fix); `analytics.statement_corrections` (audit deltas, Nov = 0); `analytics.chargebacks` (3 Oct orders, 3,567.57, booked Dec 9 backdated Dec 1). |
| **Fee model** | 2.9% per payment; + $0.30 flat per *payment row* since 2019-11-20 (commits `12e1c68`); multi-line orders collect the flat fee per line. |
| **BRAND_DENYLIST** | lucente (partnerships, Oct 25) + jetem (Dec 15, zero sales) — hidden from reports/dashboards, **not** from statements. |
| **EXCLUDED_SKUS** | 1004856 ("Internal Test", brand `internal`) and 1002544 (apple smartphone!) — hidden from daily report and non-fallback rec paths since Oct 8 (commit `83fb3ed`); ~107k of real status-1 revenue still flows through them into statements. |
| **Test users** | `analytics.test_users` = {424242} (QA smoke; `session: qa-smoke` orders); plus the Dec 1 QA account UUID `cc27b436-…` excluded by string in query 3. |
| **Sentinel score −1** | Affinity pairs seen < 3 times: "not enough data", not negative preference; serving must filter `score >= 0` (commit `fef5c96`). |
| **Random arm** | `sha256(uid) % 20 == 0` → 5% uniform-random recs for training data (commit `df4ed85`). |
| **Rec versions** | 1.0.0 = retired v1 co-cart; 2.0.0 = affinity v2 serving (table rows confusingly stamped 2.0.1); 4.0.0 = trained model behind flag; "fallback" = trending top-K. |
| **Contactable** | Two conflicting definitions: `analytics.contactable_users` view (opt-in + real-looking domain → 0 rows) vs email digest's `NOT LIKE '%@example.com'` (→ 40 undeliverable `.example` users). |
| **REPORT_SCAN_CAP** | Dead constant (500); caused pre-Nov-19 daily-report undercounts (commit `1233af8`). |
| **Intraday snapshots** | Append-only partial-day rows; consumers take latest `created_at` for today only (query 8 comment; fix `3eced24`). |
| **`[engineer:*]` / `[engineer-backfill:*]`** | Human session tags in `db_queries` — the manual-change audit trail. |
| **d2p deploys** | `trigger deploy #d2p-novamart` commits mark when code actually reached prod. |
| **novamart-ops** | Ops VM hosting Airflow (:8080) and Redash (:5000) behind IAP (`docs/data-access.md`). |
| **People** | Maya Iyer & Dev Kapoor (engineering, 54 commits each); "Novamart Platform" (Jan 2020 migration commits). |

---

---

# Appendix

## A. Company timeline (from `git log`, `job_runs`, `db_queries`)

| Date (2019) | Event | Evidence |
|---|---|---|
| 09-15 | Initial import: app, schema, reconcile/daily_report/top_sellers(monthly stub)/monthly_statement, dashboards/ dir | commit `2da4141` |
| 09-16 | First job runs (reconcile 06:00Z=02:00 ET, daily_report 10:00Z=06:00 ET) | `job_runs` |
| 09-25 12:30Z | First business data (users/products/cart/orders bootstrap) | table minima |
| 10-01 | Lucente catalog import begins; September statement published (2,702.00) | products `created_at`; `statements` |
| 10-08 | Test SKUs excluded from daily report | commit `83fb3ed` |
| 10-15 | Duplicate-ref investigation (maya) + callback idempotency fix | `db_queries` `[engineer:maya]`; commit `b676969` |
| 10-21 | Blank-brand snapshot table created | `db_queries` backfill; `analytics.blank_brand_products` |
| 10-25 | Lucente hidden "per partnerships" | commit `ba1fbfa` |
| 10-26 | Similar-products widget ships | commit `f1217a8` |
| 10-28 | Cancel endpoint; cancelled status 4→2 | commit `8f19718` |
| 11-01 | October statement published (fee bug: computed not collected) | `statements`; `app_events` mismatch warning |
| 11-02 | Statement fee fix + October override + `statements_corrected` | commits `a92c96d`; `db_queries` backfill |
| 11-02→11-09 | Trending (11-02), funnel (11-08), top_sellers daily (11-06 first run) | commits `152a760`, `4dbcf7f`, `9a51155`; `job_runs` |
| 11-15/11-16 | Refund endpoint (status 3); price_history; kpi_daily rollup | commits `d87cb3d`, `795d273`, `14726e7` |
| 11-17/11-18/11-19 | Worst undercount day; statuses 2/3 excluded from report; scan-cap fix | data; commits `11c0a42`, `1233af8` |
| 11-20/11-21 | Processor fee change (+$0.30); discount cap constant | commits `12e1c68`, `35c581e` |
| 11-22 | Session merge / order_lines live | commit `5d1300d`; `db_queries` first order_lines |
| 11-24/11-26/11-27 | Price shadow job; reorder hints; accounts endpoint + test_users registered | commits `894c535`, `f5e3032`, `b567d9d`; `db_queries` |
| 11-05→11-26 | September/October cleanup: weekly Tue 16:00Z cancel/refund batches | orders `updated_at` |
| 11-28 | Email digest job added (but silently disabled) | commit `c19a307` |
| 11-30 | Category-revenue dashboard + taxonomy backfill | commit `2814b3d`; `db_queries` |
| 12-01 | November statement (clean); accounts beta cohort (30); QA UUID created | `statements`; `accounts`; `docs/dashboard_notes.md` |
| 12-02 | Affinity v2 committed; pricing phase 2 held; Nov audit correction | commits `89666bf`, `cca9b0d`, `4a58d17` |
| 12-03→12-05 | affinity_v2 crashes (Dec seasonal factor); fraud scoring live (12-04 first run, 8 holds); fix + threshold 0.70 | `job_runs` ERRORs; commits `3dbe4d7`, `53f6f6c`, `e4656fb` |
| 12-04 | Gateway-refund webhook (money source of truth); contactable view | commits `c49a7bb`, `e10cb0c` |
| 12-06 | v1→v2 rec cutover mid-day + random arm; trending window 30d | commit `df4ed85`; `db_queries` 16:40Z; commit `f563dea` |
| 12-08/12-09 | Intraday snapshots + KPI dashboard union; chargebacks + `statements_final`; digest flag fix #1 | commits `a2e0013`, `cd559d3`, `8dc520b` |
| 12-11 | Board actives query | commit `2dde4f0` |
| 12-12 | Taxonomy renames (lighting, entertainment) with history | `db_queries` backfill; commit `33054cd` |
| 12-14/12-15 | Funnel gap 120 min; jetem hidden; model v4 training starts | commits `f915c1b`, `1169e40`, `a1946ff`; `model_registry` |
| 12-16/12-17 | Digest reads cron.env directly; first digest actually sent (40 recipients, top = test SKU) | commit `0bd4eac`; `digest_log` |
| 12-17→12-19 | similar.py refactor loses random-arm logging (Dec 18 gap); restored + caching | commits `30e8907`, `a00f24c` |
| 12-19→12-24 | Exec revenue widget added (buggy) → double-counting fixed | commits `686a5d6`, `3eced24` |
| 12-21/12-23 | Registered-conversion UUID fix; refunds view + dashboard; reorder refit | commits `b975479`, `a3bffec`, `f85cdd2` |
| 12-26 | Cache invalidation on nightly affinity refresh | commit `8ed2971` |
| 12-29 | Fraud threshold 0.85; manual release of 5 held orders (10,859.73) | commit `1cb8721`; `db_queries` UPDATE |
| 12-30/12-31 | Restatement policy + metrics docs; last data day | commits `a576d0d`, `dd0c8fc` |
| 2020-01-02→01-05 | Platform migration: data-access doc, Redash, Airflow, warehouse backfill | commits `1179287`, `57ea43a`, `43e54a1`, `2ae79e2` |

## B. Known incidents & standing caveats (the "don't get burned" ledger)

1. **October duplicate-order inflation (+58,828.24, unrestated)** — 130 refs / 151 surplus paid orders, each with payments; visible via `reconcile` warnings; never cleaned. Any per-order October analysis should dedupe by `payment_ref` (keep lowest order id).
2. **September revenue only exists as a snapshot** — raw recompute = 0 after November flips.
3. **No December statement** — compute it yourself with statement logic; state the caveats (§4.1).
4. **Nov 17 report undercount (−74,995.96)** and generally pre-Nov-19 truncation; pre-Oct-25 reports include lucente; pre-Nov-18 reports include cancelled orders. `report_rows` history ≠ today's rules.
5. **Board actives ≈ 0** (placeholder-email filter) and **contactable = 0** — both structurally broken numbers, not data outages.
6. **Fallback recs push test SKUs** (100% of 534k fallback serves); test-SKU revenue hidden from reports but inside statements.
7. **Gateway refunds never reduce statement revenue**; legacy refunds/cancels drop the whole order out of `status = 1` retroactively. Refund accounting is asymmetric across the two generations.
8. **affinity_v2 December crash pattern** — any hand-edited monthly list (seasonal factors) is a time bomb; the v1 job still runs for nothing (cost, and a stale table someone may query).
9. **Dec 18 random-arm log gap** — exclude that day from experiment analysis.
10. **Airflow migration dropped the 17:00 intraday run and has an undeclared timezone** — intraday freshness and all job timings may differ post-Jan-2020.
11. **Redash reads serving Postgres, warehouse is a frozen copy** — numbers will disagree; know which you're quoting.
12. **`orders.product_id`/brand attribution** on multi-line orders goes to the first item (affects `/reports/brands`, `daily_kpis` customer CTE, `top_products`).
13. **Digest recipients are undeliverable** `.example` addresses; recipients metric ≠ reachable customers.
14. **kpi_daily is append-only with no dedupe** — a rerun day would double-write; `scripts/rerun_kpis.py` exists for discount reruns and defaults to the *legacy* 0.40 cap if called without `constants.DISCOUNT_CAP`.

## C. How to answer "what was revenue in month X and why" (worked method)

1. Read `analytics.statements_final` (query 9 dashboard) for the current finance number; read `novamart.statements` for the as-published number; diff explained by `statement_overrides` + `chargebacks` (October: −0.14 fee, −3,567.57 chargebacks).
2. If asked to reproduce from raw data: `SUM(orders.price)` for `status = 1` in the ET month − expect it to be **lower** than published for old months (later cancels/refunds) and **higher** than clean truth for October (dupes). Show the reconciliation: published 1,230,332.43 − cancels 10,748.42 − refunds 13,246.69 = recomputed 1,206,337.32 (exact).
3. Never use `report_rows` for finance: it excludes test users/SKUs/denylist brands, applied at run time, with the pre-fix undercounts.
4. For December: no statement; recompute and disclose partial Dec 31, held orders, gateway refunds (§4.1).

## D. Verification queries (run against `<warehouse-project>`, read-only)

Monthly recompute vs statements:
```sql
WITH o AS (SELECT id, price, FORMAT_DATETIME('%Y-%m', DATETIME(created_at,'America/New_York')) m
           FROM `<warehouse-project>.novamart.orders` WHERE status = 1)
SELECT o.m, COUNT(*) orders, ROUND(SUM(o.price),2) gross,
       ROUND(SUM((SELECT SUM(p.fee) FROM `<warehouse-project>.novamart.payments` p WHERE p.order_id=o.id)),2) fee
FROM o GROUP BY 1 ORDER BY 1;
```
Duplicate-ref surplus:
```sql
WITH ranked AS (SELECT id, payment_ref, price, status, created_at,
  ROW_NUMBER() OVER (PARTITION BY payment_ref ORDER BY id) rn,
  COUNT(*) OVER (PARTITION BY payment_ref) c FROM `<warehouse-project>.novamart.orders`)
SELECT COUNT(*) surplus, ROUND(SUM(price),2) gross FROM ranked WHERE c>1 AND rn>1 AND status=1;
-- 151 / 58,828.24
```
Daily-report undercount (per-item recompute with report filters vs latest snapshot): see §4.2 numbers; full SQL used in this run is reproducible from the pattern in query 5/8 plus the union-fallback CTE.
Fallback test-SKU exposure:
```sql
SELECT rec_source, COUNTIF(REGEXP_CONTAINS(items, r'(^|,)(1004856|1002544)(,|$)')) with_test, COUNT(*) total
FROM `<warehouse-project>.novamart_analytics.rec_decision_log` GROUP BY 1;
```
Manual-intervention ledger:
```sql
SELECT timestamp, textPayload FROM `<warehouse-project>.novamart_logs.db_queries`
WHERE REGEXP_CONTAINS(textPayload, r'\[engineer') ORDER BY timestamp;  -- 191 rows
```
Three actives definitions, job history, fee-mismatch warnings, view definitions: see saved intermediates below.

## E. Run artifacts (this folder)

- `novamart_tribal_knowledge.md` — this document
- `git_log.txt` — full commit history with dates
- `redash/` — `dashboards_list.json`, `dashboard_1..9.json`, `queries_list.json`, `query_1..9.json` (full SQL)
- `bq_view_definitions.json` — the 5 BigQuery view definitions
- `bq_table_profile.txt`, `bq_order_status.txt` — table counts/ranges, status distribution
- `manual_statements.json` — all 191 human-session statements from `db_queries`
