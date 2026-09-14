# Novamart Tribal Knowledge

Run UUID: `a171b67a-42a3-4868-af3b-df906e558b87` · Started: Thu Aug 27 17:09:26 IST 2026
Sources: repo `<workspace>/novamart` pinned at `2ae79e2`; BigQuery project `<warehouse-project>` (datasets `novamart`, `novamart_analytics`, `novamart_logs`); Redash at `<redash-url>` (read-only). Every claim below cites a commit hash, table/view, SQL query, log line, or dashboard.

---

## 1. Summary

Novamart is a FastAPI + Postgres marketplace backend (repo README.md; initial import `2da4141`, 2019-09-15) whose entire business history spans 2019-09-25 → 2019-12-31 in the data (`novamart.orders` MIN/MAX `created_at`). In January 2020 the platform migrated: dashboards moved to Redash (`57ea43a`), cron schedules moved to Airflow (`43e54a1`), and the serving Postgres was copied into BigQuery by a one-shot backfill job (`2ae79e2`, `airflow/dags/warehouse_backfill_dag.py`).

The ten most load-bearing pieces of tribal knowledge, each expanded later in this document:

1. **There are three "official" revenue surfaces that legitimately disagree.** `public.statements` is the append-only as-published monthly snapshot; `analytics.statements_corrected` applies finance overrides; `analytics.statements_final` additionally subtracts chargebacks. October 2019 net is 1,194,652.79 / 1,194,652.93 / 1,191,085.36 respectively (verified by querying all three; policy in `docs/restatement_policy.md`).
2. **There are three different "active customers" numbers** (nightly rollup, exec dashboard, board deck) that use different windows, status filters, and test-user exclusions — they are three different metrics, not one metric with bugs (`docs/metrics_definitions.md`, verified against `analytics.kpi_daily`, Redash `daily_kpis`, Redash `actives_board`).
3. **Dashboards exclude things silently**: QA user 424242 (and its account UUID `cc27b436-…`), brands `lucente` and `jetem`, and test SKUs 1004856/1002544. A hand query that forgets any of these won't match the dashboards (`docs/dashboard_notes.md`, `novamart/constants.py`, Redash queries 2–5).
4. **`report_rows` undercounts busy days before 2019-11-19** because the daily report only scanned the first 500 rows (`REPORT_SCAN_CAP`; fixed in `1233af8`). Exactly one day was affected: 2019-11-17 (735 actual orders vs 487 reported units — verified in BQ).
5. **2019-11-15 was a full-day checkout outage**: 27,661 product views and 2,136 cart adds but zero orders (`novamart_logs.app_events`); the pent-up Nov 16–17 spike is what exposed the scan cap.
6. **Three HTTP routers were silently unmounted** by later commits overwriting `app.py` include lines: `users` + `reports` dead since `f1217a8` (2019-10-26), `accounts` dead since `c49a7bb` (2019-12-04). Log evidence: all 40 `user_email_updated` events are on 2019-10-23; all 30 `account_created` events are on 2019-12-01.
7. **`contactable_customers` on the exec dashboard is always 0**: the only 40 non-placeholder emails are all `…@gmail.example`, and the `analytics.contactable_users` view excludes `%.example` domains (view definition + `novamart.users` email counts).
8. **The "trained model v4" is cosmetic**: `analytics.model_scores` = `analytics.product_affinity_v2.score × (1 + 0.1·w)` — a constant rescale, rank-identical to affinity v2 (948/948 rows verified). The README's claimed v4 feature list and "serving is 4.0.0" are both false; `deploy/flags.env` pins `REC_MODEL_VERSION=2.0.0`.
9. **~80% of similar-products requests fall back to the trending list**, not affinity scores (`analytics.rec_decision_log`: 534k fallback rows of 668k total), because only 948 of 3,912 affinity pairs pass the min-pairs "graduation gate" (score ≥ 0).
10. **The Airflow migration dropped the 17:00 intraday report run** (crontab.txt had 12:00 and 17:00; `airflow/dags/intraday_report_dag.py` schedules only `0 12 * * *`), so post-migration the exec revenue widget's "today" number will be staler in the evening.

## 2. Why this project

This document exists to transfer the knowledge a tenured finance/data engineer at Novamart carries in their head, structured around three goals (from the exercise's goal context):

- **Phase 1 — Finance:** explain how orders, payments, refunds, monthly revenue and finance statements are produced end-to-end, which surfaces are source-of-truth, and why "what was revenue in month X?" has more than one defensible answer.
- **Phase 2 — Product & customer analytics:** explain every number on the company's dashboards — best sellers, brand/category revenue, active/contactable/registered customers — including exactly when a dashboard number should *not* be taken at face value.
- **Phase 3 — ML & batch jobs:** explain the recommendation/fraud/pricing/forecast systems and the 15 scheduled jobs — what each produces, what breaks when they fail, and what to check before modifying them.

The knowledge here was reconstructed exclusively from four primary sources: the git history (112 commits, 2019-09-15 → 2020-01-05), the code at `2ae79e2`, the BigQuery warehouse (app tables, analytics tables/views, and the exported Postgres statement log `novamart_logs.db_queries` including ~190 logged ad-hoc engineer queries), and the 9 Redash dashboards.

## 3. Business understanding

### What the business is

A retail marketplace: ~81k products across 6 display categories (electronics, appliances, apparel, construction, kids, other — `analytics.category_names`, 135 codes), ~39k shopper records (`novamart.users`), ~9.1k orders totaling ≈ $2.86M paid GMV over Sep 25 – Dec 31, 2019 (`novamart.orders`, status 1). Monthly paid gross: Sep $2,702 (12 orders — launch month), Oct $1.23M (3,765), Nov $1.10M (3,582) (`public.statements` rows). Products and prices arrive via a vendor price feed (`POST /catalog/prices`, `novamart/routers/catalog.py`); users and products are auto-created "on first sight" from storefront events (`ensure_entities`, `catalog.py`), with profile attributes synthesized deterministically from the id (`novamart/onboarding.py`).

### How money flows

1. The storefront sends payment-gateway callbacks to `POST /orders` (`novamart/routers/orders.py`). The order row is created status 0, then flipped to 1 (paid) in the same transaction; a `payments` row records gross/fee/net per callback.
2. Callbacks are **idempotent by `payment_ref`** (`b676969`, 2019-10-15) — replays insert nothing (522 `order_callback_replayed` events in `app_events`).
3. Since `5d1300d` (2019-11-22), callbacks in the same session within 15 minutes **merge into one multi-item order**: `orders.price` accumulates, each item becomes an `order_lines` row, each with its own `payments` row (`order_lines` first row 2019-11-22 15:18 in BQ; 225 `order_appended` events; 2,284 line rows).
4. **Processor fee**: 2.9% per order until 2019-11-19; 2.9% + $0.30 flat per transaction from 2019-11-20 (`12e1c68`; `FEE_RATE`/`FEE_FLAT` in `novamart/constants.py`). Caveat: merged orders pay the $0.30 **per line/callback**, not per order — November had 32 extra line-payments (3,614 payment rows vs 3,582 orders; verified in BQ).
5. **Refunds** have three shapes, unified in `analytics.refunds_unified` (created 2019-12-23, `db_queries` line `2019-12-23 20:00 [engineer-backfill:dev] CREATE OR REPLACE VIEW analytics.refunds_unified …`; dashboard added `a3bffec`): order cancellation (status 2, endpoint `8f19718` 2019-10-28), order refund (status 3, endpoint `d87cb3d` 2019-11-15), and gateway refund webhooks that insert **negative payments rows** (`c49a7bb` 2019-12-04, "gateway is source of truth for money"; 9 `gateway_refund` events, Dec 13–27). Note the view counts *cancellations* in "refunds" totals at full order price.
6. **Fraud**: nightly scoring (since `e4656fb` 2019-12-03) can move paid orders to status 6 (held). 12 orders (≈$40k) are currently held (`novamart.orders` status 6).

Order status codes (from `novamart/constants.py` + data): 0 = created/pre-payment (transient; zero rows at rest), 1 = paid (9,033 rows), 2 = cancelled (54; the constant was 4 until `8f19718` renumbered it — no status-4 rows exist), 3 = refunded (28), 5 = never used (vestigial `status <> 5` filter in `reconcile.py` since `2da4141`), 6 = fraud-held (12).

### The people and the era boundaries

Commits are authored by **Maya Iyer** and **Dev Kapoor** (plus "Novamart Platform" for the Jan-2020 migration; `git log`). Ad-hoc production queries are tagged `engineer:maya`, `engineer:dev`, and `engineer-backfill:*` in `novamart_logs.db_queries` — the backfill tags mark every manual production write (view creation, overrides, test-user registry, chargeback booking, held-order release).

Era boundaries every analyst must know when comparing periods:

| Boundary | Date | What changed | Evidence |
|---|---|---|---|
| Launch | 2019-09-25 | first orders | `orders` MIN(created_at) |
| Lucente import | 2019-10-01 | 676 lucente SKUs enter catalog, later hidden from all exec reporting | `docs/dashboard_notes.md`, `ba1fbfa` |
| Idempotent callbacks | 2019-10-15 | duplicate orders stop accumulating | `b676969` |
| Checkout outage | 2019-11-15 | zero orders all day; spike follows Nov 16–17 | `app_events` (0 order_created; 27,661 product_viewed) |
| Fee change | 2019-11-20 | +$0.30 flat per transaction | `12e1c68`, `FEE_CHANGE_AT` in `monthly_statement.py` |
| Multi-item orders | 2019-11-22 | `order_lines` exists; per-item counting needed | `5d1300d`, BQ `order_lines` MIN |
| Accounts beta | 2019-12-01 | 30 UUID accounts enrolled (single batch, 16:30 UTC) | `novamart.accounts`, `app_events` |
| Fraud auto-hold live | 2019-12-04→ | orders can leave status 1 | `e4656fb`, first `fraud_score` run 12-04 (`job_runs`) |
| Platform migration | Jan 2020 | Redash + Airflow + BigQuery | `57ea43a`, `43e54a1`, `2ae79e2` |

## 4. Metrics

### 4.1 Revenue: which number is right?

**Monthly (finance/board):** the chain is `public.statements` → `analytics.statements_corrected` → `analytics.statements_final` (`docs/restatement_policy.md`; view DDL in `db_queries` 2019-11-02 and 2019-12-09 `[engineer-backfill:dev]`).

| Month | As published (`statements`) | Corrected | Final | What happened |
|---|---|---|---|---|
| 2019-09 | net 2,623.64 | same | same | — |
| 2019-10 | net **1,194,652.79** (fee 35,679.64) | net **1,194,652.93** (fee 35,679.50) | net **1,191,085.36** | fee override + 3,567.57 chargebacks |
| 2019-11 | net **1,069,286.09** | same | same | audited, delta 0 |
| 2019-12 | **absent** | absent | absent | data ends 12-31; the Jan-1 statement run never happened before the export |

(All values queried directly from the three surfaces in BQ.)

- The monthly job (`novamart/jobs/monthly_statement.py`, 06:30 on the 1st): gross = SUM(`orders.price`) for status 1 orders whose `created_at` falls in the **local (America/New_York) month**; fee = SUM(`payments.fee`) (collected, per line — since `a92c96d` 2019-11-02; before that it was `gross × 2.9%`, the source of October's $0.14 fee error); net = gross − fee; appended to `public.statements`, never rewritten.
- The October **override** (`analytics.statement_overrides`, one row, note "Corrected to sum of per-order collected payment fees") was inserted manually 2019-11-02 (`db_queries` `[engineer-backfill:dev] INSERT INTO analytics.statement_overrides … '2019-10', 1230332.43, 35679.50, 1194652.93 …`).
- **Chargebacks**: 3 rows, $3,567.57 total, all against October orders > $700, booked 2019-12-09 with `reported_at` 2019-12-01 (`analytics.chargebacks`; insert visible in `db_queries` 2019-12-09). `statements_final` subtracts them from the month of the *original order*, so October was restated a month after publication.
- **November fee-mismatch warning is a red herring**: the 2019-12-01 statement run logged `statement_fee_mismatch` with delta −170.41 (`app_events`), but that run's "expected" model was still `gross × 2.9%` with no flat fee (the corrected model landed next day in `4a58d17`). ~568 post-Nov-20 orders × $0.30 ≈ $170.40 explains it. Finance audited and booked **delta 0** (`analytics.statement_corrections`, row: month 2019-11, delta 0, reason "November 2019 processor fee change audit correction") — the collected fee was right all along.

**Daily (dashboards):** `report_rows` (written by `daily_report` at 06:00 for yesterday) and `report_rows_intraday` (append-only snapshots for "today", 12:00 & 17:00, since `a2e0013` 2019-12-08). Rules for combining them safely — take **only the latest `created_at` version per report_date**, use `report_rows` for closed days and intraday **only for today** — are encoded in the Redash `revenue_widget` query comment. The first version of that widget (`686a5d6`, 2019-12-19) violated both rules and **double-counted** closed-day intraday snapshots until `3eced24` (2019-12-24), so exec-screen revenue Dec 19–24 was inflated.

**Known daily-report defects to remember when reconciling history:**
- Report days before 2019-11-19 could be capped at 500 scanned order rows (`1233af8`); only 2019-11-17 actually exceeded it (487 reported units vs 735 orders; verified in BQ — the engineer's own diagnosis queries are in `db_queries` 2019-11-19 15:00).
- Cancelled/refunded orders were **included** until `11c0a42` (2019-11-18) widened `EXCLUDED_STATUSES` from `[0]` to `[0,2,3]`.
- DST fall-back (Nov 3) day windows were wrong until `102c9b4` (2019-11-05) introduced proper local-midnight windows (`novamart/jobs/timeutil.py`).
- The daily report and dashboards exclude test SKUs / lucente / jetem / test users; `public.statements` does **not** — statements are computed straight off `orders` with only `status = 1`. The monthly statement therefore includes QA user 424242's orders and lucente/jetem revenue. This is the single most common source of "dashboard ≠ statement" confusion.

### 4.2 Active customers: three definitions (all "correct")

Documented in `docs/metrics_definitions.md` (`dd0c8fc`), verified against live surfaces:

| Surface | Window | Status filter | Exclusions | Latest value |
|---|---|---|---|---|
| `analytics.kpi_daily.active_customers` (job `kpi_daily.py`, 06:15, since `14726e7` 2019-11-16) | trailing 30×24h | `status = 1` | none | 1,152 on 2019-12-31 (BQ) |
| Redash `daily_kpis` (query 5) | per Eastern calendar day, last 14 days | **none** | user 424242; brands lucente/jetem | per-day series |
| Redash `actives_board` (query 1, `2dde4f0` 2019-12-11) | trailing 30×24h | NOT IN (0,2,3) | `analytics.test_users` + email heuristics (novamart/example/test/`.example` domains; qa/test/demo/internal/seed/sandbox/smoke localparts) | single count |

They will never agree; each answers a different question (operational buyers / daily trend under dashboard cleanup / board-grade cleaned count).

### 4.3 Contactable customers — do not trust

`analytics.contactable_users` (view, created 2019-12-04, `db_queries` `[engineer-backfill:maya]`) = opted-in users with a syntactically valid, non-example email. **It matches zero users**: only 40 of 38,950 users have non-placeholder emails (all updated in one batch on 2019-10-23 via the soon-to-die `/users/{id}/email` endpoint, `app_events`), and every one is `cust…@gmail.example`, which the view's `NOT LIKE '%.example'` filter rejects (verified: view returns 0 rows). So `contactable_customers` on the exec dashboard is structurally 0. Meanwhile the **email digest job counts recipients differently** (`email NOT LIKE '%@example.com'` → 40, including QA's `cust424242@gmail.example`; `novamart/jobs/email_digest.py`, `analytics.digest_log` recipients column = 40 every run). Two "contactable" definitions, both misleading.

### 4.4 Registered (accounts-beta) customers

30 UUID accounts, all enrolled 2019-12-01 16:30 (`novamart.accounts`, `account_map`). The first `registered_conversion` dashboard (`d6e34c6`, 2019-12-10) joined `accounts.account_id::text = orders.user_id::text` — UUID vs numeric id, matching nothing ("FIXME(dec): numbers look low" in the original SQL). Fixed `b975479` (2019-12-21) by mapping account → user **via shared email**, then joining orders on the numeric id (current Redash query 7; Maya's exploratory queries in `db_queries` 2019-12-21 20:00). The two id namespaces (numeric `users.id` vs UUID `account_id`) are *not* castable to each other — the QA account demonstrates the mapping: uid 424242 ↔ `cc27b436-d6f9-4e84-adaf-e716025dd369` (`account_map` row). Since accounts inherit users' emails and only email-updated users could enroll, registered customers ⊆ the 40 gmail.example users, QA included.

### 4.5 Product metrics

- **Best sellers (Redash query 2)**: rolling 7×24h from `now()`, counts item rows via the `item_orders` CTE (`order_lines` + legacy single-item fallback, `92596dc`), excludes 424242 and lucente/jetem, has **no status filter**, and **ranks by revenue** while displaying `COUNT(*)` as units. The nightly `top_sellers` job (public.top_products, `9a51155`, 06:45) is a *different* metric: yesterday only, `status = 1` only, no brand/user exclusions, ranked by units. They will not match (`docs/dashboard_notes.md`).
- **Brand revenue (query 3)**: 30-day rolling; also excludes the QA account UUID as text (defensive; orders.user_id is numeric, so the UUID never matches — added `adbcb7e` after the QA account was created 2019-12-01). ~21.5% of products have blank brand (17,442 rows in `novamart.products`) and appear as `unbranded` in `/reports/brands`-style queries; the analyst investigation table `analytics.blank_brand_products` (created 2019-10-21, `db_queries` `[engineer-backfill:dev] CREATE TABLE … AS SELECT`) records 5,972 blank-brand products with sales (~$38.5k) and the two suspected causes verbatim: "first inserted with blank brand; later catalog events could not repair because insert path used ON CONFLICT DO NOTHING and known-id cache skipped reprocessing" and "first seen via product view or known-id cache with no catalog metadata". The repair path (`ea0e97b` `PRODUCT_BRAND_REPAIR`, plus the `d213f6e` upsert fix — before it, `ON CONFLICT DO NOTHING` meant **vendor price updates were silently dropped**) only fixes products that get new catalog events.
- **Category revenue (query 4)**: maps `products.category` codes → display groups via `analytics.category_names` + `analytics.category_name_history`, versioned by `valid_from` with a LATERAL "latest mapping at order date" lookup (`33054cd`, 2019-12-12). **Trap:** the 2019-12-12 remap of 6 codes (`construction.tools.light` → lighting, `electronics.audio.*` → entertainment) only landed in `category_name_history` — the matching insert into `category_names` failed against the table's primary key (both inserts visible in `db_queries` 2019-12-12 20:00; `category_names` verifiably still holds the old groups from 2019-10-01). Because the LATERAL sorts `valid_from DESC, source_priority DESC`, post-remap orders pick the *history* rows: the new labels work, but they live in the table named "history" while `category_names` holds the stale mapping. Note: in the BQ export those history rows carry `valid_from` = 2026-08-13 (export-time `CURRENT_DATE`); in the original serving DB it was the remap date.
- **Trending (`analytics.trending_daily`)**: status-1 units over a rolling window with `exp(-0.05·age_days)` recency decay, min 5 units, top 50/day (`novamart/jobs/trending.py`). The window was cut 60→30 days in `f563dea` (2019-12-06) — the README's "60-day window" is stale; `docs/trending_notes.md` documents the correction and the resulting December churn (job logs show `window_days` 60→30 at 12-07).

## 5. System

### 5.1 Serving app (FastAPI)

`novamart/app.py` mounts **only**: catalog, carts, orders, similar, payments_webhook. Router lifecycle (from `git log -p novamart/app.py`):

- `users` (email update, `088a372` 10-16) and `reports` (`/reports/brands`, `193f22d` 10-21): **unmounted by `f1217a8`** (10-26) when the similar-products widget rewrote the import line. All 40 `user_email_updated` events are 2019-10-23; the brands report endpoint's server-side filters (`EXCLUDED_SKUS`, `BRAND_DENYLIST`) still exist in `novamart/routers/reports.py` but nothing serves them.
- `accounts` (`b567d9d` 11-27): **unmounted by `c49a7bb`** (12-04) when the payments webhook was added. All 30 `account_created` events are 2019-12-01. The accounts beta is therefore frozen at 30 accounts.

Neither unmount appears intentional from the commit messages; treat these as regressions that were never noticed because the callers stopped calling.

Every DB statement from app and jobs is logged in Postgres `log_statement` style (`novamart/db.py`, `novamart/logutil.py`) and exported to `novamart_logs.db_queries` (3.27M app + 331k job + 192 engineer lines; actor breakdown queried from the table). `novamart_logs.db_queries_normalized` is a BQ view that parses these lines into a jobs-style schema.

### 5.2 Batch jobs (all 15, with consumers and failure blast radius)

Schedule source: `crontab.txt` (retired) → `airflow/dags/*.py` (same times unless noted). Runs logged to `novamart_logs.job_runs`.

| Time (local) | Job | Writes | Read by | If it fails |
|---|---|---|---|---|
| 03:00 | reconcile (`reconcile.py`) | app-log WARNINGs only | humans | duplicate-ref detection stops. Flags refs on >1 order (`status <> 5` vestigial), cap 200/night (`RECONCILE_BATCH`, 100→200 in `030d841`). 130 distinct legacy dup refs get re-flagged every night (10,766 warnings ÷ 130 refs; all predate idempotency). Moved 02:00→03:00 in `388370b` (2019-11-10) because it overlapped the backup window. |
| 03:30 | affinity (v1) | `analytics.product_affinity` | **nothing** (widget moved to v2, `docs/affinity_lineage.md`) | zero user impact; pure waste. Safe-to-drop analysis already documented. |
| 03:45 | affinity_v2 | `analytics.product_affinity_v2` | similar widget (exploit arm), model_train | widget serves stale scores, then trending fallback. Crashed Dec 3–5 (IndexError: `SEASONAL_FACTORS` has 11 entries, month 12 indexed past the end; `job_runs` ERROR rows with the traceback; fixed `3dbe4d7`). |
| 04:15 | model_train | `analytics.model_registry`, `analytics.model_scores` | widget only if flag = 4.0.0 (it isn't) | nothing user-visible today. |
| 04:45 | price_suggest | `analytics.price_suggestions` | **nothing** (shadow; Phase 2 ON HOLD per exec/legal — `cca9b0d`, NOTE in `price_suggest.py`) | nothing. |
| 05:15 | trending | `analytics.trending_daily` | homepage + widget **fallback** (~80% of rec traffic) | recs fall back to *yesterday's* trending row (widget reads MAX(day)); if long-stale, recs go empty. |
| 05:45 | fraud_score | `analytics.order_risk`; **UPDATEs `orders` to status 6** | daily numbers implicitly | no new holds; also the only job that mutates order state — a bad threshold change directly moves revenue between "paid" and "held". |
| 06:00 | daily_report | `public.report_rows` | daily_kpis + revenue_widget dashboards | dashboard history goes missing for that day (append-only, one version per date; no automatic backfill — verified: no report_date has >1 created_at version). |
| 06:15 | kpi_daily | `analytics.kpi_daily` | KPI consumers | 30-day actives series gets a hole (append-only, one row/run). |
| 06:20 | funnel | `analytics.daily_funnel` | analysts | sessions/users_active gap. Sessionization gap 30→120 min (`f915c1b`, 2019-12-14): session counts before/after are not comparable. |
| 06:30 (1st) | monthly_statement | `public.statements` | board decks, restatement chain | the month never gets published — December 2019 is exactly this state (job last ran 2019-12-01, `job_runs`; export ends 12-31). |
| 06:45 | top_sellers | `public.top_products` | ops/merch | stale list. |
| 06:50 | reorder_forecast | `analytics.reorder_hints` (delete+rewrite) | merchandising humans | stale hints. **ADVISORY only** (README; `docs/forecast_caveats.md`): `hint = int(15.6 + 162.4/(velocity+1.8))` — hand-fit constants (K refit 141.12→162.4 in `f85cdd2`), top-200 by 14-day paid velocity, and mechanically **lower velocity ⇒ bigger hint**. Never a purchasing commitment. |
| 07:15 | email_digest | `analytics.digest_log` | marketing | no digest. **Silently disabled 2019-11-28 → 2019-12-16**: the job checked env `DIGEST_ON` while `deploy/cron.env` set `ENABLE_DIGEST` (`c19a307`), the rename fix (`8dc520b`) still relied on the wrapper exporting the env, and only reading cron.env directly (`0bd4eac`, 12-16) made it run — first `job_runs` entry 2019-12-17. Its "top product" query has **no exclusions**, so the first five digests promoted the excluded test SKUs 1002544/1004856 (`analytics.digest_log` top_product column). |
| 12:00 & 17:00 | intraday_report | `public.report_rows_intraday` (append-only snapshots) | daily_kpis + revenue_widget ("today") | today's number freezes. **The Airflow DAG only kept the 12:00 run** — the 17:00 cron entry was dropped in the migration (`crontab.txt` lines 28–29 vs `intraday_report_dag.py` `schedule="0 12 * * *"`). |

One-shot: `warehouse_backfill` (Airflow, `schedule=None`) copies every serving table to BigQuery via `gcloud sql export csv` + `bq load` driven by `warehouse_manifest.json` (`novamart/jobs/warehouse_backfill.py`, `2ae79e2`).

Ops helper: `scripts/rerun_kpis.py` reapplies the promo cap after a failed day — but calls `apply_discounts(rows)` with the **legacy default cap 0.40** instead of `constants.DISCOUNT_CAP = 0.25` (`novamart/jobs/discounts.py` default vs `35c581e`); anyone using the runbook as-is over-discounts by 15 points.

### 5.3 Fraud pipeline specifics

`fraud_score.py` (nightly, last-24h status-1 orders): `core = min(price/3000, 1)`, +15% multiplicative boosts for account-age < 7 days and ≥3 orders in 24h, capped at 1.0. Threshold history: 0.90 (`e4656fb`) → 0.70 (`53f6f6c`, 12-05) → 0.85 (`1cb8721`, 12-29). The 12-29 change also **manually released** held orders under $2,600 — the exact statement is in the query log (`db_queries` 2019-12-29 15:00 `[engineer-backfill:maya] UPDATE orders SET status = 1, updated_at = NOW() WHERE status = 6 AND price < 2600;`), matching the 5 released orders (scores 0.72–0.86) and 12 still-held orders (min price $2,655) in BQ. 1,631 orders were ever scored (`analytics.order_risk`).

### 5.4 Platform (post-migration)

Per `docs/data-access.md` (`1179287`): serving DB = Cloud SQL `novamart-prod-replica`; warehouse = BigQuery `<warehouse-project>`; dashboards = Redash on `novamart-ops` (IAP tunnel); schedules = Airflow on `novamart-ops`. Redash has two data sources — "novamart serving (Cloud SQL)" (pg, id 1; all 9 dashboards use it) and "novamart warehouse (BigQuery)" (id 2) — both view-only (`/api/data_sources`).

## 6. Data

### 6.1 Datasets

- **`novamart` (12 app tables)**: users (38,950), products (81,018), cart_items (36,938), orders (9,127), order_lines (2,284, from 2019-11-22), payments (9,361, incl. 9 negative gateway-refund rows), accounts (30), account_map (30), report_rows (6,923 rows, 2019-09-25→12-30), report_rows_intraday (2,358, 2019-12-08→12-31), statements (3), top_products (2,396). (Row counts/ranges queried from BQ.)
- **`novamart_analytics` (20 tables + 4 views)**: the batch outputs (`kpi_daily`, `daily_funnel`, `trending_daily`, `product_affinity`, `product_affinity_v2`, `model_scores`, `model_registry`, `order_risk`, `price_suggestions`, `reorder_hints`, `price_history` (1,400 rows / 241 products), `digest_log`, `rec_decision_log` (667,850 rows)), finance restatement tables (`statement_overrides`, `statement_corrections`, `chargebacks`), manual registries (`test_users` — exactly one row: 424242; `category_names`; `category_name_history`; `blank_brand_products`), and views (`contactable_users`, `refunds_unified`, `statements_corrected`, `statements_final` — definitions in `INFORMATION_SCHEMA.VIEWS`, mirroring the Postgres originals created in `db_queries`).
- **`novamart_logs`**: `app_events` (JSONL app log; event counts: 843k product_viewed, 669k rec_served, 36.9k cart_item_added, 9,127 order_created, …), `job_runs`, `db_queries` (raw statement log), `db_queries_normalized` (parsing view).

### 6.2 Semantics and traps

- **Timezones**: business days and months are America/New_York; timestamps are UTC (`constants.LOCAL_TZ`, `timeutil.py`). Any hand query grouping by UTC date will drift from every official surface.
- **`report_rows`/`report_rows_intraday` are append-only snapshot tables**, keyed by (report_date, created_at version). Always take the latest version per date; never sum intraday snapshots for closed days (revenue_widget comment; the Dec 19–24 double-count incident `3eced24`).
- **`orders.price` on merged orders is the order total**; per-item data lives in `order_lines`. Counting items requires the `item_orders` union-with-fallback pattern (`92596dc`) because pre-2019-11-22 orders have no lines.
- **Placeholder identity data**: emails default to `user{uid}@example.com`; names/regions/channels/devices/age bands/opt-in are hash-synthesized from the uid (`onboarding.py`), as are product vendor/cost/stock. Treat demographic splits accordingly.
- **`marketing_opt_in` is ~62% by construction** (`_h(uid,'m') % 100 < 62`, `onboarding.py`; 24,193/38,950 in BQ).
- **QA fingerprints**: user 424242 (session `qa-smoke`, 14 orders Sep 25→Dec 25), account UUID `cc27b436-d6f9-4e84-adaf-e716025dd369`, email `cust424242@gmail.example`, test SKUs 1004856 ("Internal Test #4856", category `qa.test`) and 1002544 (an apple smartphone titled "Unbranded Item #2544" — excluded as a test SKU since `83fb3ed` despite looking like a real product).
- **Export artifacts**: rows touched by manual fixes at export time carry 2026-08-13 timestamps (the released orders' `updated_at`, `category_name_history.valid_from`). Map them back to their in-sim dates (2019-12-29 release; 2019-12-12 remap) when reasoning about history.

### 6.3 Lineage (finance)

`orders`+`payments` → (06:00) `report_rows` / (12:00,17:00) `report_rows_intraday` → Redash `daily_kpis` & `revenue_widget`; `orders`+`payments` → (monthly) `statements` → `statements_corrected` (+`statement_overrides`) → `statements_final` (+`chargebacks` via order month) → Redash `statements_final`. Refunds: `orders.status ∈ (2,3)` + negative `payments` → `refunds_unified` → Redash `refunds`.

## 7. Experimentation

### 7.1 Recommendation system (the only real experiment)

**Versions** (`novamart/routers/similar.py` REC_VERSIONS; `docs/rec_versions.md` is an empty "TBD" stub):
- **1.0.0** — co-cart affinity v1 (`776d674`, 2019-10-12; widget `f1217a8` 10-26). Retired for serving; table still refreshed nightly.
- **2.0.0** — affinity v2, conversion-weighted (cart pair = 1, converted = 3), same-category boost ×1.15, extreme price-ratio damp ×0.7, monthly seasonal factor (Jan–Nov list; December crash → `season = 1.0`, `3dbe4d7`). **Currently served** (`deploy/flags.env REC_MODEL_VERSION=2.0.0`). Naming trap: the table rows are stamped `model_version = '2.0.1'` (bumped in the crash fix) while the serving flag says 2.0.0 — same pipeline (`docs/affinity_lineage.md`).
- **4.0.0** — nightly logistic regression (`model_train.py`, `a1946ff` 12-14), flag-gated and **never enabled**. The README's claims that serving is 4.0.0 and that the model uses region/device/stock features are both contradicted by the code: the feature vector is `[n_items, base_price/1000, base_popularity/100, min(account_age/60,1), organic_user]`; `opt_in` is fetched but unused (explicit NOTE in `model_train.py`).

**Assignment**: 5% uniform-random arm by `hash(uid) % 20 == 0` (`in_random_arm`), the rest get the model arm; every decision is logged to `analytics.rec_decision_log` with intended/effective version, source, fallback reason, and arm (`df4ed85`).

**Data-quality incidents an experimenter must know**:
1. **Random-arm logging gap**: `30e8907` (12-17 16:50) refactored the random arm into an early return *without* the decision-log insert; restored by `a00f24c` (12-19 14:55). Verified: zero `arm='random'` rows on 2019-12-18, partial on 12-17/12-19; consecutive `model_registry` runs show identical `train_rows` (5,798) on 12-18 and 12-19.
2. **Stale-cache window**: `a00f24c` added a 6-hour in-process score cache that could serve yesterday's scores after the nightly refresh; `8ed2971` (12-26) added epoch invalidation on `MAX(updated_at)` and pinned reads to the latest refresh batch.
3. **Fallback dominance**: of 667,850 logged decisions, ~534k are `source='fallback'` (reason `no_scores`, plus ~25k `cache` from the pre-12-26 empty-cache bug) vs ~118k affinity/model serves and 14,566 random-arm serves (grouped query on `rec_decision_log`; Maya ran the same audit on 2019-12-22, `db_queries`). Root cause: the "graduation gate" (`MIN_PAIRS=3`, `fef5c96`) leaves only 948 of 3,912 pairs servable (score ≥ 0; sentinel −1 = "not enough data", *not* negative preference — serving must filter `score >= 0`).

**Does the ML work?** Judged on this evidence: affinity v2 is a plausible heuristic but covers too few pairs to serve most traffic; v4 is **not a real ranking model** — `model_scores = affinity_v2 × (1 + 0.1·w₁)` (w₁ = the n_items coefficient), verified exact on all 948 rows, i.e., rank-identical to v2. Its label ("user placed *any* later status-1 order, ever") is not item- or exposure-scoped, and daily coefficients swing sign (e.g. organic_user −2.35 → +0.04 across two days; `model_registry` coef_json) on 4k–14k rows. Flipping the flag to 4.0.0 would change nothing except the version stamp — and that is worth knowing before anyone "ships v4".

### 7.2 Shadow experiments (not serving)

- **Dynamic pricing**: nightly ±5% suggestions for the top-500 by 14-day demand into `analytics.price_suggestions` (500 rows/night); Phase 2 serving is ON HOLD per exec/legal review (`cca9b0d`, `894c535`, NOTE in `price_suggest.py`; no read path exists — `docs/pricing_status.md` verified writes-but-no-reads in the query log).
- **Reorder hints**: advisory heuristic, see §5.2 — treat as a merchandising signal, never a forecast.
- **Fraud threshold tuning**: 0.90 → 0.70 → 0.85 with a manual release of small held orders (§5.3) — threshold changes act directly on revenue recognition (status 6 orders drop out of every status=1 metric).

## 8. Glossary

| Term | Meaning | Evidence |
|---|---|---|
| **status 0/1/2/3/5/6** | order created(pre-pay)/paid/cancelled/refunded/never-used/fraud-held; 2 was 4 before `8f19718` | `constants.py`, orders data |
| **payment_ref** | gateway idempotency key; unique per callback; dup refs = pre-Oct-15 legacy | `b676969`, `reconcile.py` |
| **order_lines** | per-item rows for merged same-session orders (since 2019-11-22) | `5d1300d` |
| **item_orders pattern** | UNION of order_lines + legacy orders-without-lines; required for per-item counts | `92596dc`, Redash queries 2–4 |
| **as-published vs restated** | `statements` (snapshot) vs `statements_final` (overrides + chargebacks) | `docs/restatement_policy.md` |
| **statement override / correction** | replacement row for a month / audit note with delta | `statement_overrides`, `statement_corrections` |
| **EXCLUDED_SKUS** | 1004856, 1002544 — hidden from reports and digest-should-have-been | `constants.py`, `83fb3ed` |
| **BRAND_DENYLIST** | lucente (hidden per partnerships, `ba1fbfa`), jetem (`1169e40`) | `constants.py` |
| **424242 / cc27b436-…** | QA smoke-test user / its beta account UUID | `b59f077`, `adbcb7e`, `account_map` |
| **test_users** | manual registry of QA user ids (currently just 424242) | `analytics.test_users` |
| **graduation gate / sentinel −1** | affinity pairs seen <3 times get score −1 = "insufficient data"; serving filters `score >= 0` | `fef5c96`, `affinity.py` |
| **random arm** | 5% uniform-random rec serving for unbiased training data | `similar.py` `in_random_arm` |
| **rec_decision_log** | per-request rec decision audit (versions, source, fallback reason, arm) | `analytics.rec_decision_log` |
| **intended vs effective version** | flag-requested vs actually-served rec version (fallback ⇒ differ) | `similar.py` |
| **2.0.0 vs 2.0.1** | serving flag vs table row stamp for the same affinity-v2 pipeline | `3dbe4d7`, `docs/affinity_lineage.md` |
| **contactable** | opted-in + real-looking email (view: 0 users) vs digest's not-example.com (40 users) | `contactable_users`, `email_digest.py` |
| **report snapshot version** | `created_at` of a (report_date, product) batch; always take latest per date | revenue_widget SQL |
| **local day/month** | America/New_York boundaries for all reports/statements | `LOCAL_TZ`, `timeutil.py` |
| **FEE_CHANGE_AT** | 2019-11-20 ET midnight: 2.9% → 2.9% + $0.30/transaction | `4a58d17`, `12e1c68` |
| **shadow job** | writes analytics output nobody serves (price_suggest; affinity v1 today) | `docs/pricing_status.md` |
| **display_group** | dashboard category rollup (6 groups) via versioned code mapping | `category_names`, `33054cd` |
| **engineer-backfill** | query-log actor tag marking manual production writes | `db_queries` |

---

## Appendix

### A. Incident log (chronological)

| Date (2019) | Incident | Fix / residue | Evidence |
|---|---|---|---|
| Sep–Oct 15 | duplicate orders from replayed callbacks | idempotency `b676969`; 130 legacy dup refs still flagged nightly | `db_queries` 10-15 Maya's dup investigation; app_events |
| Oct 1 (run) | Sep statement fee off $0.01 (rounding) | tolerated | `statement_fee_mismatch` app_event 10-01 |
| Oct 8 | test SKUs polluting daily report | `EXCLUDED_SKUS` `83fb3ed` | commit |
| Oct 21 | blank-brand products distort brand revenue | repair-on-event `ea0e97b`; investigation table `blank_brand_products` | `db_queries` 10-21 |
| Oct 26 | users+reports routers unmounted | never fixed | `f1217a8` diff |
| Nov 1 (run) | Oct statement fee modeled not collected ($0.14) | `a92c96d`; override booked 11-02 | `statement_overrides` |
| Nov 3 | DST fall-back broke day windows | `102c9b4` | commit; engineer checks `db_queries` 11-05 |
| Nov 9 | vendor price updates silently dropped | upsert `d213f6e` | commit |
| Nov 15 | full-day checkout outage (0 orders) | traffic normal; spike follows | `app_events` 11-15 |
| Nov 17 | daily report capped at 500 rows (487 vs 735) | `1233af8` 11-19; **history not backfilled** | BQ comparison; `db_queries` 11-19 |
| Nov 18 | cancelled/refunded counted in daily report | `11c0a42` | commit |
| Nov 28–Dec 16 | email digest silently disabled (flag plumbing) | `8dc520b`, `0bd4eac`; first run 12-17 | `job_runs` |
| Dec 1 (run) | Nov fee-mismatch warning (−170.41) | model fixed `4a58d17`; audit delta 0 | app_events; `statement_corrections` |
| Dec 3–5 | affinity_v2 crashed (December seasonal index) | `3dbe4d7`; v2 version → 2.0.1 | `job_runs` ERROR tracebacks |
| Dec 4 | accounts router unmounted (beta frozen at 30) | never fixed | `c49a7bb` diff |
| Dec 10→21 | registered-conversion joined UUID to numeric id (≈0 rows) | email mapping `b975479` | original SQL `d6e34c6` |
| Dec 12 | taxonomy remap insert into category_names failed; new mapping lives in *_history | works via LATERAL priority quirk | `db_queries` 12-12; BQ contents |
| Dec 17–19 | random-arm decision logging dropped in refactor | `a00f24c`; train_rows flat at 5,798 | `rec_decision_log`; `model_registry` |
| Dec 17–21 | digest promoted excluded test SKUs | unfixed (no exclusions in digest query) | `digest_log` top_product |
| Dec 19–24 | exec revenue widget double-counted intraday snapshots | `3eced24` | `686a5d6` vs fixed SQL |
| Dec 29 | fraud threshold 0.70 judged too aggressive | 0.85 + manual release < $2,600 (5 orders) | `1cb8721`; `db_queries` UPDATE; orders data |
| Jan 2020 | migration dropped 17:00 intraday run | open | crontab vs DAG |

### B. How to answer "what was revenue in month X, and why?"

1. State which surface: as-published (`public.statements`), corrected (`statements_corrected`), or final restated (`analytics.statements_final` — default for current reporting per `docs/restatement_policy.md`).
2. Definition: status-1 orders by ET-month of `created_at`; gross = SUM(orders.price); fee = collected `payments.fee`; net = gross − fee; minus chargebacks by original order month (final only).
3. Remember what statements do NOT exclude (QA user, lucente/jetem, test SKUs) and that daily dashboards DO exclude them — the two will never tie out exactly.
4. For December 2019: no statement exists (job runs on the 1st; data ends 12-31). Reconstruct from orders/payments with the rules above if asked.

### C. Job → table → dashboard matrix (quick lookup)

- Redash `daily_kpis` ← report_rows (daily_report) + report_rows_intraday (intraday_report) + orders + contactable_users
- Redash `revenue_widget` ← report_rows + report_rows_intraday
- Redash `best_sellers`/`brand_revenue`/`category_revenue` ← orders + order_lines + products (+ category_names/_history)
- Redash `actives_board` ← orders + test_users + users.email heuristics
- Redash `registered_conversion` ← accounts × users (email) × orders
- Redash `refunds` ← refunds_unified (orders 2/3 + negative payments)
- Redash `statements_final` ← statements_final chain
- Similar widget ← product_affinity_v2 (flag 2.0.0) / model_scores (4.0.0, unused) / trending_daily (fallback) / rec_decision_log (audit)

### D. Working artifacts in this run directory

`bqq.py` (BQ query helper), `notes_repo.md` (repo-phase notes), `engineer_queries.txt` (all 192 logged ad-hoc engineer queries), `redash_queries.txt` (all 9 dashboard SQL texts), and this document.
