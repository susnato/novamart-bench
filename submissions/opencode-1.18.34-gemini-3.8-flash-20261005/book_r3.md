# Novamart Systems & Tribal Knowledge Guide

**Author:** Senior Staff Software Engineer  
**Audit Snapshot Date:** January 2020 (Analysis of historical data Sep 2019 – Dec 2019)  
**Codebase Commit:** `5ae1182`  
**Execution Timestamp:** 2026-10-05 15:11:31 UTC  
**Audit Session UUID:** `8f3a972b-f5e8-44f5-bb0c-8dba42b8a067`  

---

## 1. Summary

This document serves as the authoritative, institutional repository of tribal knowledge for Novamart's engineering, analytics, and business systems. It captures the hidden invariants, historical bug fixes, financial accounting nuances, scheduled batch pipelines, machine learning models, and executive dashboard definitions across the codebase (`pinned at commit 5ae1182`), the operational database (PostgreSQL), the analytical data warehouse (Google BigQuery project `novamart-warehouse`), and the business intelligence layer (Redash at `http://localhost:5053`).

### Core Findings & Executive Takeaways
1. **Financial Source of Truth:** Novamart operates three distinct layers of monthly financial statements:
   - `public.statements` (`novamart.statements` in BigQuery): The historical as-published audit snapshot emitted by `novamart/jobs/monthly_statement.py` on the 1st of each month.
   - `analytics.statements_corrected` (`novamart_analytics.statements_corrected`): The operational view applying manual finance overrides (`analytics.statement_overrides`) to resolve batch calculation bugs (e.g., a $0.14 rounding correction in October 2019 fees).
   - `analytics.statements_final` (`novamart_analytics.statements_final`): The **authoritative source of truth for corporate reporting**, which retroactively attributes booked chargebacks (`analytics.chargebacks`, committed `cd559d3`) to their original purchase month (deducting $3,567.57 from October 2019 net revenue).
2. **In-Place Mutation Distorts Historical Queries:** Re-running queries on `orders WHERE status = 1` against historical months will produce numbers significantly lower than published statements. Later cancellations (`status = 2`) and refunds (`status = 3`) update `orders.status` in place (commits `8f19718`, `d87cb3d`). For example, in October 2019, 43 cancellations ($10,748.42) and 27 refunds ($13,246.69) were mutated in place; a naive query today yields $1,206,337.32 instead of the true published gross revenue of $1,230,332.43.
3. **Fraud Auto-Holds Cause Financial Divergence:** In December 2019, 12 high-value orders totaling $40,213.29 were placed, paid for in `payments`, and subsequently auto-held in `status = 6` by the nightly risk scoring job (`novamart/jobs/fraud_score.py`). Because `monthly_statement.py` only scans `status = 1`, these orders are omitted from order-level revenue, creating a $40k wedge between captured payments ($590,698.63 net of refunds) and completed orders ($552,328.93).
4. **Machine Learning & Recommendations:**
   - The live storefront widget (`/products/{pid}/similar`) serves from `analytics.product_affinity_v2` (`REC_MODEL_VERSION=2.0.0` in `deploy/flags.env`).
   - Despite nightly execution of `novamart/jobs/model_train.py` (Model v4, logistic regression), **Version 4.0.0 has never been turned on for live traffic**.
   - Model v4 is mathematically a pseudo-model: it multiplies all valid pair scores by a single uniform scalar without modifying relative ranking.
   - Serving fallback rate is **~80%**: out of 81,018 products, only 948 pairs have valid affinity scores ($\ge 0$); the remaining 80% of traffic falls back to `analytics.trending_daily`.
   - 5% of all traffic is assigned to an unbiased uniform-random exploration arm (`in_random_arm(uid)`) logged to `analytics.rec_decision_log`.
5. **Advisory & Shadow Pipelines:**
   - `analytics.price_suggestions` is a **shadow-only table**; dynamic pricing rollout was halted per executive/legal review (commit `cca9b0d`). No serving path reads from it.
   - `analytics.reorder_hints` is a **hand-fit heuristic that inverts velocity**: mechanically, slower sellers produce higher reorder quantities. It must never be used for inventory commitments without human overrides (commit `f85cdd2`, `docs/forecast_caveats.md`).
6. **Customer Metrics Segmentation:** There is no single "active customer" number. The nightly batch job (`analytics.kpi_daily`), the daily exec KPI dashboard (`dashboards/daily_kpis.sql`), and the board deck (`dashboards/actives_board.sql`) use completely different windows (calendar day vs 30-day rolling), status filters, and test account exclusions.

---

## 2. Why This Project

### Historical Background
Novamart originated as a monolithic FastAPI application backed by a single PostgreSQL instance and Unix `crontab`. As transactional volume grew from 12 orders in September 2019 to over 3,700 orders per month in Q4 2019, operational requirements forced rapid architectural iterations. Engineers introduced localized schema additions, ad hoc query filters, and heuristic jobs to solve immediate business needs:
- `order_lines` was introduced on 2019-11-22 (commit `92596dc`) to support multi-item carts, requiring a dual-read legacy fallback in all downstream analytics.
- Catalog items viewed or carted prior to feed ingestion were bootstrapped with blank titles and brands via `ON CONFLICT DO NOTHING` (commit `2da4141`, `ea0e97b`), leaving 5,972 products categorized as `'unbranded'`.
- Commercial partnership agreements mandated the hard-exclusion of specific brands (`lucente` in commit `ba1fbfa`, `jetem` in commit `1169e40`) from executive reporting.
- Smoke-test accounts (`user_id = 424242` and account UUID `cc27b436-d6f9-4e84-adaf-e716025dd369`) were excluded directly in dashboard SQL rather than cleaned at the ingestion layer (commits `b59f077`, `adbcb7e`).

### The January 2020 Platform Migration
In January 2020, Novamart migrated from a single production server to a modern data platform (documented in `docs/data-access.md` and commits `4bfcbe6`, `41e3537`, `d398b0d`, `5ae1182`):
- **Serving Database:** Cloud SQL PostgreSQL replica (`novamart-prod-replica`).
- **Warehouse:** Google BigQuery (`novamart-warehouse`), holding app tables (`novamart`), transformed views (`novamart_analytics`), and structured logs (`novamart_logs`).
- **Batch Orchestration:** Apache Airflow (`airflow/dags/`), deprecating `crontab.txt`.
- **Dashboards:** Redash (`http://localhost:5053`), replacing static SQL files in `dashboards/`.
- **Warehouse Backfill:** `novamart.jobs.warehouse_backfill` (commit `5ae1182`, `warehouse_manifest.json`) extracts PostgreSQL tables to GCS CSVs with UTC timestamp formatting and loads them into BigQuery.

Without capturing the institutional tribal knowledge embedded in git history, log files, and code comments, new engineers and analysts risk corrupting financial reports, misinterpreting ML serving behaviors, or breaking delicate downstream pipelines.

---

## 3. Business Understanding

### 3.1 End-to-End Order & Payment Lifecycle

```
[Storefront / User Action]
           │
           ▼
   POST /cart ──────► cart_items (user_id, product_id, session, created_at)
           │
           ▼
   POST /orders ────► 1. Advisory Locks: pg_advisory_xact_lock(session), (ref)
           │          2. Idempotency Check on payment_ref
           │          3. 15-minute Session Merge Check:
           │             ├─ Found recent order? ──► Append to order_lines & payments
           │             │                          UPDATE orders SET price = price + p
           │             └─ No recent order?  ────► INSERT into orders (status=1)
           │                                        INSERT into order_lines
           │                                        INSERT into payments
           ▼
[Post-Order Lifecycle]
  ├─ POST /orders/{id}/cancel ──► UPDATE orders SET status = 2 (STATUS_CANCELLED)
  ├─ POST /orders/{id}/refund ──► UPDATE orders SET status = 3 (STATUS_REFUNDED)
  ├─ POST /payments/gateway_refund ──► INSERT into payments (gross < 0, net < 0)
  ├─ Nightly fraud_score.py ────► UPDATE orders SET status = 6 (FRAUD_HELD)
  └─ Monthly Chargeback Audit ──► INSERT into analytics.chargebacks
```

1. **Carting (`novamart/routers/carts.py`):** User additions are stored in `cart_items`. If the user or product has not been seen before, `ensure_entities` bootstraps them deterministically (`novamart/onboarding.py`).
2. **Order Placement (`novamart/routers/orders.py`):**
   - Receives `uid`, `pid`, `price`, `ref` (`payment_ref`), and `session`.
   - Acquires PostgreSQL transaction-level advisory locks on `hashtext(session)` and `hashtext(ref)` to prevent race conditions.
   - Enforces idempotency on `payment_ref`: duplicate callbacks do not create duplicate orders (commit `b676969`).
   - Checks if the user placed an order in the same session within the last 15 minutes (`created_at >= ts - INTERVAL '15 minutes'`). If so, merges into the existing order: increments `orders.price`, inserts a new row in `order_lines`, and logs a payment row (commit `5d1300d`).
   - If no prior order exists, inserts a new record into `orders` with initial `status = 0`, writes `order_lines`, writes `payments`, and updates `orders.status = 1`.
3. **Payment Recording (`novamart/routers/orders.py`):**
   - For every cart item/order, a matching row is inserted into `payments(order_id, gross, fee, net, payment_ref, created_at)`.
   - Fee calculation:
     - Prior to Nov 20, 2019: `round(price * 0.029, 2)`.
     - Effective Nov 20, 2019: `round(price * 0.029 + 0.30, 2)` (commit `12e1c68`).
4. **Cancellations & Refunds (`novamart/routers/orders.py`, `payments_webhook.py`):**
   - Order cancellations (`/orders/{id}/cancel`): Verifies order is not already refunded; updates `orders.status = 2` and `updated_at = ts` (commit `8f19718`).
   - Order refunds (`/orders/{id}/refund`): Verifies order is in status 1; updates `orders.status = 3` and `updated_at = ts` (commit `d87cb3d`).
   - Gateway refunds (`/payments/gateway_refund`): As of commit `c49a7bb`, payment gateway webhooks represent the ultimate source of truth for cash movements. A negative row is inserted into `payments` with `gross = -amount`, `fee = 0`, and `net = -amount`.

### 3.2 Financial Reconciliation Across History

The table below reconciles Novamart's core financial numbers across all months of operation, comparing every layer of reporting against operational reality.

| Month | Published Gross (`statements`) | Published Net (`statements`) | Restated Gross (`statements_final`) | Restated Net (`statements_final`) | Naive Orders Gross (`status=1`) | Payments Gross (`novamart.payments`) | Daily Reports Gross (`report_rows`) | Operational Nuance & Root Cause |
|---|---|---|---|---|---|---|---|---|
| **2019-09** | $2,702.00 | $2,623.64 | $2,702.00 | $2,623.64 | **$0.00** | $2,702.00 | $2,702.00 | All 12 orders were later mutated in-place to `status=2` (11 cancelled, $2,501.22) and `status=3` (1 refunded, $200.78) during Nov/Dec test runs. Zero orders remain at `status=1`. |
| **2019-10** | $1,230,332.43 | $1,194,652.79 | **$1,226,764.86** | **$1,191,085.36** | $1,206,337.32 | $1,230,332.43 | $1,201,082.08 | 1) $0.14 fee error overridden in `statements_corrected`. 2) $3,567.57 chargebacks booked Dec 9 retroactively reduced gross & net. 3) Naive query misses 43 cancelled ($10,748.42) and 27 refunded ($13,246.69) orders mutated in-place. 4) `report_rows` capped at 500 rows/day. |
| **2019-11** | $1,101,397.01 | $1,069,286.09 | $1,101,397.01 | $1,069,286.09 | $1,101,397.01 | $1,101,397.01 | $966,974.33 | Fee changed on Nov 20 to 2.9% + $0.30 flat. `statements` accurately captured collected fees. `report_rows` lower due to exclusion of brands (`lucente`, `jetem`), SKUs (`1004856`, `1002544`), and test users. |
| **2019-12** | *Unpublished* | *Unpublished* | *Unpublished* | *Unpublished* | $552,328.93 | **$590,698.63** | $535,561.72 | 12 orders ($40,213.29) auto-held in `status=6` by `fraud_score.py`; payments were captured, but orders omitted from `status=1`. Payments also include 9 gateway refunds (-$1,843.59). Total order demand: $592,542.22. |

### 3.3 "What was revenue in a given month, and why?"

When an executive or auditor asks for monthly revenue, a tenured data person must answer based on the intended purpose (`docs/restatement_policy.md`, commit `a576d0d`):

1. **For October 2019:**
   - **Originally Published (Board Deck Snapshot):** **$1,230,332.43 Gross**, **$1,194,652.79 Net** (3,765 orders). Emitted by `monthly_statement.py` on 2019-11-01 into `public.statements`.
   - **Operational Fee-Corrected:** **$1,194,652.93 Net** (+ $0.14). The original monthly statement applied an aggregate fee calculation rather than summing actual per-order fees recorded in `payments` ($35,679.50 actual vs $35,679.64 calculated). This was corrected via `analytics.statement_overrides` (commit `a92c96d`).
   - **Current Business / External Source of Truth:** **$1,226,764.86 Gross**, **$1,191,085.36 Net**. View `analytics.statements_final` subtracts $3,567.57 of chargebacks booked on 2019-12-09 (`analytics.chargebacks`, orders 55, 46, and 49) back to their original October transaction dates.
   - **Why naive queries fail:** Querying `SELECT SUM(price) FROM orders WHERE status = 1` yields **$1,206,337.32** ($23,995.11 lower) because subsequent cancellation and refund endpoints mutated historical order statuses in place.
2. **For November 2019:**
   - **Official Revenue:** **$1,101,397.01 Gross**, **$1,069,286.09 Net**, **$32,110.92 Fees** (3,582 orders).
   - **Policy Nuance:** On 2019-11-20, processor pricing shifted to 2.9% + $0.30 per transaction (`FEE_FLAT = 0.30`). An audit correction confirmed zero fee discrepancy (`analytics.statement_corrections`, commit `4a58d17`).
3. **For December 2019:**
   - **Completed Orders (`status = 1`):** **$552,328.93** (1,756 orders).
   - **Captured Payment Gross:** **$590,698.63** ($592,542.22 positive payments minus $1,843.59 gateway refunds).
   - **The $40k Discrepancy:** 12 orders totaling **$40,213.29** were auto-held in `status = 6` by `fraud_score.py`. While their credit cards were charged in `payments`, they are not marked completed. If released, gross revenue is $592,542.22.

---

## 4. Metrics

### 4.1 Active Customers: The Three Conflicting Definitions
Novamart runs three separate active customer calculations (`docs/metrics_definitions.md`, commit `dd0c8fc`). They cannot be compared directly:

| Metric Surface | Storage / Code Location | Window / Cadence | Status Filter | Exclusions Applied | Business Purpose |
|---|---|---|---|---|---|
| **Nightly Rollup** | `analytics.kpi_daily`, `novamart/jobs/kpi_daily.py` | Trailing 30 days (30 $\times$ 24h UTC) | Strict `status = 1` | None (keeps QA users, test emails, excluded brands) | Simple operational trend of paid buyers. As of 2019-12-31: **1,152 active customers**. |
| **Exec KPI Dashboard** | `dashboards/daily_kpis.sql`, Redash Query 7 | Calendar day (America/New_York), past 14 days | **None** (counts any placed order) | Excludes `user_id = 424242`; joins `products` and excludes `brand IN ('lucente', 'jetem')` | Operational daily buyer engagement for leadership. |
| **Board Deck Query** | `dashboards/actives_board.sql`, Redash Query 3 | Trailing 30 days (`now() - interval '30 days'`) | Excludes non-active (`NOT (status = ANY(0, 2, 3))`) | Excludes `analytics.test_users`; regex excludes internal domains (`novamart.com`, `example.*`, `internal.*`, `*.test`) & test localparts | Cleanest investor-grade metric for board reporting. |

### 4.2 Contactable Customers & The Email TLD Trap
- **Definition (`analytics.contactable_users`, commit `e10cb0c`):** View filtering `users` where `marketing_opt_in = TRUE`, valid email regex, domain not in (`example.com`, `example.net`, `example.org`), and `domain NOT LIKE '%.example'`.
- **The Zero Count Reality:** Querying `analytics.contactable_users` in BigQuery returns **0 rows**.
- **Root Cause:** All auto-created users (`catalog.py` line 41) receive synthetic `@example.com` emails. The only 40 users who updated their emails received `@gmail.example` (RFC 2606 test TLD). Because the view explicitly filters `NOT LIKE '%.example'`, every single user is excluded.
- **Dashboard Impact:** On `dashboards/daily_kpis.sql`, `contactable_customers` is **0 across all days**.

### 4.3 Best Sellers (`dashboards/best_sellers.sql` vs `top_sellers.py`)
- **Dashboard Query (`dashboards/best_sellers.sql`, commit `a9a4b0b`):**
  - Uses a rolling 7-day window (`io.created_at >= now() - interval '7 days'`).
  - Reads `item_orders` CTE (`order_lines` unioned with legacy `orders` fallback, commit `92596dc`).
  - Filters: `io.user_id <> 424242` and `p.brand NOT IN ('lucente', 'jetem')`.
  - **No status filter:** Includes cancelled, refunded, and held orders.
  - **Ranked by Revenue DESC, not units:** Returns `COUNT(*) AS units` but sorts by `ORDER BY revenue DESC LIMIT 20`.
- **Scheduled Batch Job (`novamart/jobs/top_sellers.py`, commit `9a51155`):**
  - Runs at 06:45 daily. Covers yesterday's local calendar day in `America/New_York`.
  - Strictly requires `orders.status = 1`.
  - Ranks by `units DESC, product_id` (Limit 50). Writes to `top_products`.
  - Does NOT exclude test users or partner brands (`lucente`, `jetem`).

### 4.4 Brand & Category Revenue Dashboards
- **Brand Revenue (`dashboards/brand_revenue.sql`, commit `adbcb7e`):**
  - Rolling 30 days. Uses `order_lines` with legacy fallback.
  - Filters out `user_id::text NOT IN ('424242', 'cc27b436-d6f9-4e84-adaf-e716025dd369')`.
  - Filters out `p.brand NOT IN ('lucente', 'jetem')`.
  - **Warning on Unbranded Items:** Products created with empty brand strings are grouped under `brand = ''`, which represents the 5th highest revenue generator ($18,014.39 in December 2019).
- **Category Revenue (`dashboards/category_revenue.sql`, commit `33054cd`):**
  - Rolling 30 days. Uses `order_lines` with fallback. Excludes QA user `424242` and partner brands.
  - Executes a `LEFT JOIN LATERAL` against `analytics.category_names` and `analytics.category_name_history` with `c.valid_from <= io.created_at::date ORDER BY c.valid_from DESC, c.source_priority DESC LIMIT 1`. This preserves point-in-time taxonomy groupings.

### 4.5 Registered Accounts Conversion (`dashboards/registered_conversion.sql`)
- **Dual Namespace Trap (Commit `b975479`, `d6e34c6`):**
  - `orders.user_id` and `users.id` are **BIGINT** (legacy numeric shopper IDs).
  - `accounts.account_id` and `account_map.account_id` are **UUIDs** (registered accounts beta).
  - They cannot be cast or joined directly.
  - **Correct Join Path:** `accounts a JOIN users u ON u.email = a.email JOIN orders o ON o.user_id = u.id WHERE o.status = 1`.
  - As of Dec 31, 2019: 30 registered buyers generating **$18,155.71** in revenue.

---

## 5. System Architecture & Pipelines

### 5.1 System Architecture Diagram

```
                 ┌────────────────────────────────────────────────────────┐
                 │                   Storefront Clients                   │
                 └───────┬───────────────────────┬────────────────┬───────┘
                         │                       │                │
            POST /cart, /orders             GET /similar     GET /reports
                         │                       │                │
                         ▼                       ▼                ▼
                 ┌────────────────────────────────────────────────────────┐
                 │                FastAPI Application Tier                │
                 │               (novamart/app.py, uvicorn)               │
                 └───────┬───────────────────────┬────────────────────────┘
                         │ (read/write)          │ (event logs)
                         ▼                       ▼
            ┌────────────────────────┐      ┌─────────────────────────────┐
            │  Cloud SQL PostgreSQL  │      │ Structured App/DB Log Files │
            │ (novamart-prod-replica)│      │  (db_queries, app_events)   │
            └────────────┬───────────┘      └──────────────┬──────────────┘
                         │                                 │
     warehouse_backfill  │                 Log Export      │
      (Airflow DAG)      ▼                                 ▼
            ┌─────────────────────────────────────────────────────────────┐
            │                 Google BigQuery Warehouse                   │
            │                  (novamart-warehouse)                       │
            │  Datasets: novamart, novamart_analytics, novamart_logs      │
            └──────────────────────────────┬──────────────────────────────┘
                                           │
                                           ▼
                               ┌──────────────────────┐
                               │   Redash BI Layer    │
                               │(http://localhost:5053│
                               └──────────────────────┘
```

### 5.2 Scheduled Batch Jobs Inventory & Blast Radius

Migrated in January 2020 from `crontab.txt` to Airflow DAGs (`airflow/dags/`, commit `4bfcbe6`):

| Job Module | Airflow DAG | Schedule (Local ET) | Primary Inputs | Output Tables | Blast Radius / Failure Impact |
|---|---|---|---|---|---|
| `novamart.jobs.reconcile` | `reconcile_dag` | 03:00 daily | `orders`, `payments` | App log (`WARNING duplicate_payment_ref`) | No table output. Audit warnings missing; finance cannot spot duplicate payment refs. |
| `novamart.jobs.affinity` | `affinity_dag` | 03:30 daily | `cart_items` (30d) | `analytics.product_affinity` | **Legacy Pipeline.** Writes unused table. Safe to deprecate for widget serving (`docs/affinity_lineage.md`). |
| `novamart.jobs.affinity_v2` | `affinity_v2_dag` | 03:45 daily | `cart_items`, `orders`, `products` | `analytics.product_affinity_v2` | **CRITICAL.** Stales the primary live recommendation table. Widget serves stale co-cart scores. |
| `novamart.jobs.model_train` | `model_train_dag` | 04:15 daily | `rec_decision_log` (random arm), `orders`, `users` | `analytics.model_scores`, `analytics.model_registry` | Model v4 scores stale; no customer impact because `REC_MODEL_VERSION` is still `2.0.0`. |
| `novamart.jobs.price_suggest` | `price_suggest_dag` | 04:45 daily | `orders` (14d), `products` | `analytics.price_suggestions` | **Shadow Pipeline.** Table becomes stale; zero serving impact (Phase 2 held in commit `cca9b0d`). |
| `novamart.jobs.trending` | `trending_dag` | 05:15 daily | `orders` (30d, `status=1`) | `analytics.trending_daily` | Stales trending list on homepage; stales the fallback recommendations in `similar.py`. |
| `novamart.jobs.fraud_score` | `fraud_score_dag` | 05:45 daily | `orders` (1d), `users` | `analytics.order_risk`, updates `orders.status=6` | **CRITICAL.** Fraudulent orders above threshold 0.85 are NOT held; financial exposure/chargeback risk. |
| `novamart.jobs.daily_report` | `daily_report_dag` | 06:00 daily | `order_lines`, `orders`, `products` | `report_rows` | **CRITICAL.** Yesterday's sales missing; breaks `dashboards/daily_kpis.sql` and `revenue_widget.sql`. |
| `novamart.jobs.kpi_daily` | `kpi_daily_dag` | 06:15 daily | `orders` (30d, `status=1`) | `analytics.kpi_daily` | 30d trailing active customer metrics chart flatlines or has missing days. |
| `novamart.jobs.funnel` | `funnel_dag` | 06:20 daily | `cart_items`, `orders` (1d) | `analytics.daily_funnel` | Sessionized funnel drop-off analytics missing for yesterday. |
| `novamart.jobs.monthly_statement`| `monthly_statement_dag`| 06:30 monthly (1st) | `orders`, `payments` | `public.statements` | **CRITICAL.** Monthly corporate financial statements missing; delays executive and board close. |
| `novamart.jobs.top_sellers` | `top_sellers_dag` | 06:45 daily | `orders` (1d, `status=1`) | `top_products` | Top selling merchandising rankings missing. |
| `novamart.jobs.reorder_forecast`| `reorder_forecast_dag` | 06:50 daily | `orders` (14d, `status=1`) | `analytics.reorder_hints` | Reorder suggestions missing (advisory only). |
| `novamart.jobs.email_digest` | `email_digest_dag` | 07:15 daily | `orders`, `users` | `analytics.digest_log` | Marketing email digest fails to send (runs only if `ENABLE_DIGEST=1`). |
| `novamart.jobs.intraday_report` | `intraday_report_dag` | 12:00, 17:00 daily | `order_lines`, `orders`, `products` | `report_rows_intraday` | Intraday partial revenue missing from executive screen widgets. |
| `novamart.jobs.warehouse_backfill`| `warehouse_backfill_dag`| On-demand manual | PostgreSQL tables | BigQuery datasets | BigQuery warehouse desynchronizes from PostgreSQL production database. |

---

## 6. Data Warehouse & Lineage

### 6.1 Warehouse Schema Inventory
The BigQuery project `novamart-warehouse` consists of three datasets (`warehouse_manifest.json`):
1. **`novamart` (App Tables, 12 tables):**
   - `accounts` (UUID account_id, email, created_at)
   - `account_map` (uid, account_id, linked_at)
   - `cart_items` (id, user_id, product_id, session, created_at)
   - `order_lines` (order_id, product_id, price, session, payment_ref, created_at)
   - `orders` (id, user_id, product_id, price, payment_ref, status, created_at, updated_at)
   - `payments` (id, order_id, gross, fee, net, created_at, payment_ref)
   - `products` (id, title, category, brand, vendor, list_price, cost_price, stock, created_at)
   - `report_rows` (report_date, product_id, units, revenue, created_at)
   - `report_rows_intraday` (report_date, product_id, units, revenue, created_at)
   - `statements` (month, gross, fee, net, orders_count, created_at)
   - `top_products` (rank, product_id, units, report_date, created_at)
   - `users` (id, email, name, region, signup_channel, device, age_band, marketing_opt_in, created_at)
2. **`novamart_analytics` (Analytics Tables & Views, 20 tables, 4 views):**
   - Tables: `blank_brand_products`, `category_name_history`, `category_names`, `chargebacks`, `daily_funnel`, `digest_log`, `kpi_daily`, `model_registry`, `model_scores`, `order_risk`, `price_history`, `price_suggestions`, `product_affinity`, `product_affinity_v2`, `rec_decision_log`, `reorder_hints`, `statement_corrections`, `statement_overrides`, `test_users`, `trending_daily`.
   - Views:
     - `contactable_users`: Filters opted-in users with real non-example emails.
     - `refunds_unified`: Combines cancelled orders (status=2), refunded orders (status=3), and gateway payment refunds (gross < 0).
     - `statements_corrected`: Replaces raw `statements` with `statement_overrides`.
     - `statements_final`: Attributed chargebacks deducted from `statements_corrected`.
3. **`novamart_logs` (System Logs, 3 tables, 1 view):**
   - `app_events`: JSONL application event records (1.57M rows).
   - `db_queries`: PostgreSQL raw statement execution logs (3.60M rows).
   - `job_runs`: Batch job start, completion, and crash logs (978 rows).
   - `db_queries_normalized`: Analytical view parsing statements into structured columns (`statement_type`, `user_email`, `referenced_tables`).

### 6.2 Data Quality Traps, Historical Bugs, and Exclusions

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                Historical Pipeline Bugs                                │
├─────────────────────────┬───────────────────────────┬──────────────────────────────────┤
│ Commit & Date           │ Component Affected        │ Nature of Bug & Resolution       │
├─────────────────────────┼───────────────────────────┼──────────────────────────────────┤
│ 102c9b4 (2019-11-05)    │ timeutil.py               │ DST Fall-Back: start + 24h       │
│                         │                           │ chopped 25th hour. Fixed window. │
├─────────────────────────┼───────────────────────────┼──────────────────────────────────┤
│ 1233af8 (2019-11-19)    │ daily_report.py           │ REPORT_SCAN_CAP=500 caused order │
│                         │                           │ undercounts. Removed fetch limit.│
├─────────────────────────┼───────────────────────────┼──────────────────────────────────┤
│ 3dbe4d7 (2019-12-06)    │ affinity_v2.py            │ December crash: IndexError on    │
│                         │                           │ SEASONAL_FACTORS[11]. Added else.│
├─────────────────────────┼───────────────────────────┼──────────────────────────────────┤
│ 3eced24 (2019-12-24)    │ revenue_widget.sql        │ Double counting intraday reports.│
│                         │                           │ Fixed to latest snapshot per day.│
└─────────────────────────┴───────────────────────────┴──────────────────────────────────┘
```

1. **DST Fall-Back Bug (Commit `102c9b4`):** Prior to Nov 5, 2019, `local_day_window_utc` computed the end of day by adding `timedelta(hours=24)` to UTC midnight. On Sunday, Nov 3, 2019 (DST transition), Eastern time had 25 hours; the 25th hour of orders was omitted from that day's daily report. Fixed by computing local midnight for day + 1 first, then converting to UTC.
2. **Daily Report 500-Row Scan Cap (Commit `1233af8`):** Prior to Nov 19, 2019, `daily_report.py` called `cur.fetchmany(REPORT_SCAN_CAP)` where `REPORT_SCAN_CAP = 500`. On busy days with >500 orders, only the first 500 orders were aggregated into `report_rows`. Fixed by calling `fetchall()`.
3. **Affinity v2 December Crash (Commit `3dbe4d7`):** On Dec 3, 4, and 5, 2019, `affinity_v2.py` crashed with `IndexError: list index out of range` because `SEASONAL_FACTORS` only had 11 entries (Jan–Nov). Fixed by defaulting to 1.0 for month 12.
4. **Intraday Snapshot Double Counting (Commit `3eced24`):** `report_rows_intraday` appends snapshots twice daily (12:00 and 17:00). Closed days also land in `report_rows`. Naive queries in `revenue_widget.sql` summed both tables directly, double- and triple-counting revenue. Fixed by filtering `report_rows` strictly to prior days (`< today`) taking the latest snapshot, and `report_rows_intraday` strictly to `= today`.
5. **Hidden Brands & SKUs:**
   - SKUs `1004856` ("Internal Test #4856", $40,968.29) and `1002544` ("Unbranded Item #2544", $66,690.18) are hard-excluded from `daily_report.py`, `similar.py`, and `reports/brands` (`EXCLUDED_SKUS`, commit `83fb3ed`). Total hidden revenue: **$107,658.47**.
   - Brands `lucente` ($43,335.35 across 141 orders) and `jetem` are hard-excluded from `daily_report.py` and all Redash executive dashboards (`BRAND_DENYLIST`, commits `ba1fbfa`, `1169e40`).
6. **Hard-Coded QA Users:**
   - User `424242` placed 14 smoke-test orders ($139.86) and is excluded across all dashboards (`analytics.test_users`, commit `b59f077`).
   - Account UUID `cc27b436-d6f9-4e84-adaf-e716025dd369` was created for the same tester and is explicitly string-excluded in `dashboards/brand_revenue.sql` (commit `adbcb7e`).

---

## 7. Experimentation

Novamart maintains four distinct experimental tracks:

### 7.1 Dynamic Pricing Phase 1 (Shadow Pipeline)
- **Job:** `novamart/jobs/price_suggest.py` (scheduled daily at 04:45 local).
- **Table Written:** `analytics.price_suggestions` (500 rows).
- **Algorithm:** Identifies top 500 products by completed order volume over the trailing 14 days. Computes median demand; applies a $+5\%$ nudge if above median or $-5\%$ if below median (`suggested_price = round(price * (1 + nudge), 2)`).
- **Current Status:** **100% SHADOW.** Serving reads were halted per executive and legal review (commit `cca9b0d`, `docs/pricing_status.md`). No serving path, API router, or scheduled job reads this table. Live storefront prices are strictly driven by vendor catalog feeds (`/catalog/prices`).

### 7.2 Similar-Products Recommendations & Exploration Arms
- **Service Router:** `novamart/routers/similar.py` (`GET /products/{pid}/similar`).
- **Feature Flag:** `REC_MODEL_VERSION` in `deploy/flags.env` (currently set to `2.0.0`).
- **Model Evolution & Lineage:**
  - **Version 1.0.0 (Retired):** Co-cart co-occurrence with recency decay (`affinity.py`). Graduation gate: pairs with $<3$ occurrences received a `-1` sentinel score.
  - **Version 2.0.0 (Live Production Default):** Conversion-weighted co-carting (`affinity_v2.py`). Weights: cart = 1.0, completed order = 3.0. Features listing adjustments: $+15\%$ boost for same category, $0.7\times$ penalty for extreme price ratios ($>4.0$ or $<0.25$), and monthly seasonal factors.
  - **Version 4.0.0 (Trained Offline, Never Activated):** Logistic regression trained nightly (`model_train.py`, commit `a1946ff`) on random-arm decisions.
- **The Epsilon-Greedy Random Arm:**
  - 5% of users are deterministically assigned to an exploration arm: `hashlib.sha256(str(uid).encode()).hexdigest()[:8] % 20 == 0`.
  - Serves 5 uniformly random products from catalog (excluding `EXCLUDED_SKUS`).
  - Decision logged to `analytics.rec_decision_log` with `arm = 'random'`, `rec_source = 'random_arm'`.
- **Efficacy Evaluation of Model v4:**
  - `model_train.py` fits a logistic regression predicting conversion from 5 features: item count, base price, base popularity, account age, and organic channel.
  - However, during scoring, it selects candidates from `analytics.product_affinity_v2 WHERE score >= 0` and multiplies their score by `(1.0 + 0.1 * w)` where `w = coef_[0][0]`.
  - **Critical Flaw:** Because `(1.0 + 0.1 * w)` is a single scalar constant applied to all candidates of all products, **it preserves the exact order of affinity v2**. It does not personalize, re-rank, or add predictive value. Furthermore, `REC_MODEL_VERSION` was never updated to 4.0.0 in `deploy/flags.env`.

### 7.3 Registered Accounts Beta
- **Endpoints:** `novamart/routers/accounts.py` (`POST /accounts`).
- **Mechanism:** Creates an explicit registered account entity (`accounts.account_id` as UUID4) mapped to legacy numeric user IDs (`account_map`).
- **Status:** Enrolled 30 users. Conversion monitored via `dashboards/registered_conversion.sql` ($18,155.71 revenue across 30 buyers).

### 7.4 Fraud Scoring Threshold Tuning
- **Job:** `novamart/jobs/fraud_score.py` (scheduled daily at 05:45 local).
- **Formula:** `core = min(price / 3000, 1.0)`. Boosted by $+15\%$ for new accounts ($<7$ days old) and $+15\%$ for velocity ($\ge 3$ orders in 24h). `score = min(core * boost, 1.0)`.
- **Threshold Progression:**
  - Introduced in commit `e4656fb` with auto-hold to `status = 6`.
  - Tightened to `0.70` in commit `53f6f6c`.
  - Relaxed to `0.85` in commit `1cb8721`, manually releasing held orders under $2,600.
- **Current Status:** 12 orders remain held in status 6 ($40,213.29).

---

## 8. Glossary

- **`account_map`:** Bridge table mapping legacy numeric user IDs (`uid` BIGINT) to modern registered account UUIDs (`account_id` UUID).
- **`actives_board`:** The board-facing active customer query; applies rigorous email domain heuristics and test user table exclusions over a 30-day window.
- **`analytics.chargebacks`:** Table recording booked credit card chargebacks by `order_id` and amount; subtracted retroactively in `analytics.statements_final`.
- **`analytics.kpi_daily`:** Append-only table produced nightly by `kpi_daily.py`; counts distinct `user_id` with `status = 1` over trailing 30 days.
- **`analytics.order_risk`:** Table storing nightly fraud risk scores, core scores, and account velocity flags per order.
- **`analytics.price_suggestions`:** Nightly batch table of dynamic price nudges ($\pm 5\%$); purely shadow-mode, never read in production.
- **`analytics.product_affinity_v2`:** Primary co-cart similarity table serving the live storefront widget; rows stamped with `model_version = '2.0.1'`.
- **`analytics.rec_decision_log`:** Durable event log capturing every recommendation served (timestamp, user, base product, items, intended/effective versions, arm, and fallback reasons).
- **`analytics.reorder_hints`:** Advisory heuristic table estimating restock units via an inverted velocity formula; not validated for procurement.
- **`analytics.statement_overrides`:** Table holding finance overrides to correct statement calculation errors (e.g., October 2019 $0.14 fee fix).
- **`analytics.statements_corrected`:** View merging `public.statements` with `statement_overrides`.
- **`analytics.statements_final`:** View subtracting booked chargebacks from `statements_corrected`; corporate source of truth for finance.
- **`analytics.test_users`:** Single-column table storing test user IDs (specifically `424242`) for exclusion from analytics.
- **`analytics.trending_daily`:** Rolling 30-day recency-decayed product rankings (top 50) used on homepage and as rec widget fallback.
- **`BRAND_DENYLIST`:** Configuration constant (`['lucente', 'jetem']`) hiding partner brands from executive reporting.
- **`contactable_users`:** Analytical view identifying marketing-eligible users; currently evaluates to 0 rows due to synthetic `.example` email domains.
- **`DISCOUNT_CAP`:** Configuration constant (`0.25`) defining maximum promo discounts allowed in financial rerun scripts.
- **`ensure_entities`:** Helper function in `catalog.py` bootstrapping users and products on first appearance using deterministic pseudo-profiles.
- **`EXCLUDED_SKUS`:** Configuration constant (`[1004856, 1002544]`) hiding test and unbranded SKUs totaling $107k in revenue from reports.
- **`EXCLUDED_STATUSES`:** Order statuses excluded from daily reports (`[0, 2, 3]` = pending, cancelled, refunded).
- **`FEE_FLAT`:** Flat transaction fee component ($0.30) instituted on Nov 20, 2019.
- **`FEE_RATE`:** Variable transaction fee rate (`0.029` = 2.9%).
- **`FRAUD_HOLD_THRESHOLD`:** Risk score threshold (`0.85`); orders scoring higher are mutated to `status = 6`.
- **`GAP_MIN`:** Inactivity gap window (120 minutes) used in `funnel.py` to delineate user sessions.
- **`order_lines`:** Table storing multi-item order lines introduced on 2019-11-22; requires fallback to `orders` for legacy single-item orders.
- **`payment_ref`:** Unique payment identifier from the gateway ensuring idempotent transaction processing.
- **`random_arm`:** 5% uniform-random recommendation bucket used to collect unbiased training data for rec models.
- **`refunds_unified`:** View combining cancelled orders (status 2), refunded orders (status 3), and gateway refund payments (gross < 0).
- **`report_rows`:** Append-only table holding finalized daily product revenue and unit rollups.
- **`report_rows_intraday`:** Append-only table storing partial intraday revenue snapshots generated at 12:00 and 17:00 local time.
- **`Sentinel Score (-1)`:** Marker in product affinity tables indicating candidate pairs carted fewer than `MIN_PAIRS = 3` times.
- **`statements`:** Core table storing monthly financial statement snapshots generated by `monthly_statement.py`.
- **`STATUS_CANCELLED (2)`:** Order status indicating cancellation via `/orders/{id}/cancel`.
- **`STATUS_REFUNDED (3)`:** Order status indicating refund via `/orders/{id}/refund`.
- **`STATUS_HELD (6)`:** Order status indicating order held for fraud review via `fraud_score.py`.

---

## Appendix: Extended Technical Details & Queries

### A.1 BigQuery Full View Definitions

#### View: `novamart_analytics.statements_corrected` (Logged at `2019-12-09T15:00:00+00:00`)
```sql
CREATE OR REPLACE VIEW analytics.statements_corrected AS 
SELECT s.month, 
       COALESCE(o.gross, s.gross) AS gross, 
       COALESCE(o.fee, s.fee) AS fee, 
       COALESCE(o.net, s.net) AS net, 
       COALESCE(o.orders_count, s.orders_count) AS orders_count, 
       COALESCE(o.created_at, s.created_at) AS created_at 
FROM statements s 
LEFT JOIN analytics.statement_overrides o ON o.month = s.month;
```

#### View: `novamart_analytics.statements_final` (Logged at `2019-12-09T15:00:00+00:00`)
```sql
CREATE OR REPLACE VIEW analytics.statements_final AS 
WITH chargebacks_by_month AS ( 
  SELECT to_char(date_trunc('month', o.created_at AT TIME ZONE 'America/New_York'), 'YYYY-MM') AS month, 
         SUM(c.amount) AS chargeback_amount 
  FROM analytics.chargebacks c 
  JOIN orders o ON o.id = c.order_id 
  GROUP BY 1 
) 
SELECT sc.month, 
       ROUND((sc.gross - COALESCE(cb.chargeback_amount, 0))::numeric, 2) AS gross, 
       sc.fee, 
       ROUND((sc.net - COALESCE(cb.chargeback_amount, 0))::numeric, 2) AS net, 
       sc.orders_count, 
       sc.created_at 
FROM analytics.statements_corrected sc 
LEFT JOIN chargebacks_by_month cb ON cb.month = sc.month;
```

#### View: `novamart_analytics.refunds_unified` (Logged at `2019-12-23T20:00:00+00:00`)
```sql
CREATE OR REPLACE VIEW analytics.refunds_unified AS 
SELECT o.id AS order_id, 
       CASE WHEN o.status = 2 THEN 'order_cancelled' WHEN o.status = 3 THEN 'order_refunded' END AS kind, 
       o.price AS amount, 
       o.updated_at AS "at" 
FROM orders o 
WHERE o.status IN (2, 3) 
UNION ALL 
SELECT p.order_id, 
       'gateway_refund' AS kind, 
       CASE WHEN p.gross < 0 THEN ABS(p.gross) ELSE ABS(p.net) END AS amount, 
       p.created_at AS "at" 
FROM payments p 
WHERE p.gross < 0 OR p.net < 0;
```

#### View: `novamart_analytics.contactable_users` (Logged at `2019-12-04T15:00:00+00:00`)
```sql
CREATE OR REPLACE VIEW analytics.contactable_users AS 
SELECT u.id AS user_id, 
       u.email, 
       u.created_at 
FROM users u 
WHERE u.marketing_opt_in 
  AND u.email ~* '^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$' 
  AND lower(split_part(u.email, '@', 2)) NOT IN ('example.com', 'example.net', 'example.org') 
  AND lower(split_part(u.email, '@', 2)) NOT LIKE '%.example';
```

### A.2 Chargeback Orders Audit
Booked in `analytics.chargebacks` (commit `cd559d3`):
- `order_id = 55`: Amount $734.81, created `2019-10-01 07:39:51 UTC`, cancelled status 2.
- `order_id = 46`: Amount $940.82, created `2019-10-01 09:55:10 UTC`, cancelled status 2.
- `order_id = 49`: Amount $1,891.94, created `2019-10-01 09:57:25 UTC`, refunded status 3.
- **Total Deducted from October 2019:** **$3,567.57**.

### A.3 Active Fraud Held Orders (Status = 6)
Scored above threshold 0.85 in December 2019 (`analytics.order_risk`):
- `order_id = 7527`: Price $2,999.99, Score 1.0000 (Dec 3)
- `order_id = 7528`: Price $2,999.99, Score 1.0000 (Dec 3)
- `order_id = 7532`: Price $2,999.99, Score 1.0000 (Dec 3)
- `order_id = 7533`: Price $5,999.98, Score 1.0000 (Dec 3)
- `order_id = 7535`: Price $2,999.99, Score 1.0000 (Dec 3)
- `order_id = 7536`: Price $2,999.99, Score 1.0000 (Dec 3)
- `order_id = 7537`: Price $2,999.99, Score 1.0000 (Dec 3)
- `order_id = 7539`: Price $2,999.99, Score 1.0000 (Dec 3)
- `order_id = 8482`: Price $4,890.17, Score 1.0000 (Dec 18)
- `order_id = 8840`: Price $2,655.33, Score 0.8851 (Dec 23)
- `order_id = 9282`: Price $2,699.23, Score 0.8997 (Dec 27)
- `order_id = 9550`: Price $2,968.65, Score 0.9896 (Dec 30)
- **Total Value Held:** **$40,213.29** across 12 orders.

### A.4 Recommendation Traffic Distribution (All Time)
Extracted from `novamart_analytics.rec_decision_log` (667,850 rows):
1. `version = 1.0.0`, fallback (`no_scores`): 326,186 (48.8%)
2. `version = 2.0.0`, fallback (`no_scores`): 182,868 (27.4%)
3. `version = 1.0.0`, served from affinity: 66,444 (9.9%)
4. `version = 2.0.0`, served from model (uncached): 31,268 (4.7%)
5. `version = 2.0.0`, fallback (`cache`): 25,091 (3.8%)
6. `version = 2.0.0`, served from model (`cache`): 21,427 (3.2%)
7. `version = 2.0.0`, served from random arm: 14,566 (2.2%)
- **Aggregate Fallback Rate:** **~80%** across both versions.
