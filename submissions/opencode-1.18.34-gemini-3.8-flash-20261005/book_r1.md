# Novamart Systems & Tribal Knowledge Handbook

## 1. Summary

This document serves as the comprehensive source of truth and repository of tribal knowledge for the Novamart marketplace, data platform, batch scheduling architecture, and analytics reporting ecosystem. It synthesizes operational realities across the service codebase (`novamart` pinned at commit `5ae1182`), the BigQuery data warehouse (`novamart-warehouse`), the Airflow orchestrator, and the Redash executive dashboard suite.

The core findings and operational truths documented herein include:
- **Financial Architecture & Source of Truth:** Financial reporting at Novamart is multi-tiered and temporally anchored. The raw operational table `public.statements` (loaded to BigQuery as `novamart.statements`) records the historical, append-only monthly statement frozen at generation time. Due to subsequent audit discoveries—specifically per-order payment processing fee rounding errors (commit `a92c96d`), flat gateway transaction fees introduced on 2019-11-20 (commit `12e1c68`, commit `4a58d17`), and chargebacks booked retroactively (commit `cd559d3`)—finance reports diverge by design between as-published snapshots and restated figures. For all modern business, executive, and board reporting, `analytics.statements_final` is the definitive source of truth (documented in `docs/restatement_policy.md`, commit `a576d0d`).
- **Product & Customer Analytics Nuances:** Executive dashboards (`dashboards/best_sellers.sql`, `dashboards/brand_revenue.sql`, `dashboards/category_revenue.sql`, `dashboards/daily_kpis.sql`) do **not** filter by completed order status (`status = 1`), meaning cancelled, refunded, and fraud-held orders are routinely included in merchandising charts. Furthermore, aggressive sanitization filters (e.g., hardcoded QA user exclusions for `424242` and `cc27b436-d6f9-4e84-adaf-e716025dd369`, catalog brand suppressions for `lucente` and `jetem`, and regex-based email exclusions in `dashboards/actives_board.sql`) cause sharp discrepancies with raw transactional rollups. In synthetic or sandbox environments, `actives_board.sql` reports 0 active customers because all simulated customer emails match `.example` domain patterns.
- **Machine Learning & Algorithmic Serving Reality:** While the public documentation (`README.md`) claims that recommendation version 4.0.0 is live in production with a 9-feature logistic regression model, production inspection reveals that `deploy/flags.env` enforces `REC_MODEL_VERSION=2.0.0` (Affinity v2 exploit). Model v4 (`novamart/jobs/model_train.py`, commit `a1946ff`) only extracts 5 features from random-arm exposures, does not score item pairs via model inference, and merely multiplies Affinity v2 scores by a scalar `(1.0 + 0.1 * w)` derived from the list-length coefficient, producing a ranking 100% identical to v2. Similarly, `analytics.reorder_hints` (`novamart/jobs/reorder_forecast.py`) is an inverse-velocity heuristic that mechanically outputs larger buy quantities for slower-selling items and must never be used for financial purchasing commitments (`docs/forecast_caveats.md`). Dynamic pricing (`analytics.price_suggestions`) runs strictly in shadow mode with zero live serving reads (`docs/pricing_status.md`).

---

## 2. Why This Project

Novamart is a fast-growing multi-category marketplace. Over its lifecycle, rapid feature development, database migrations, changes in payment terms, and organizational reporting requirements created significant layers of tacit, unwritten knowledge ("tribal knowledge").

The objectives of this project are:
1. **Demystify Financial Numbers (Phase 1):** Explain exactly how gross revenue, processor fees, net revenue, refunds, cancellations, chargebacks, and monthly finance statements are calculated end-to-end, resolving historical discrepancies between board deck snapshots and modern restated ledgers.
2. **Reconcile Product & Customer Metrics (Phase 2):** Provide clear explanations for merchandising metrics (best sellers, brand revenue, category revenue) and customer counts (signups, active buyers, contactable users, registered account beta conversion), identifying when dashboards cannot be taken at face value.
3. **Audit Machine Learning & Scheduled Pipelines (Phase 3):** Demarcate operational reality from architectural aspirations across recommendations, forecasting, dynamic pricing, and scheduled batch jobs, documenting pipeline failure modes, downstream impacts, and maintenance safeguards.

---

## 3. Business Understanding

### 3.1 Business Model & Transaction Lifecycle
Novamart operates an e-commerce platform where customers browse catalog items, add them to carts, and complete purchases via payment gateway callbacks:
1. **Product Listing & Catalog Ingestion:** Products are registered via vendor price feeds (`POST /catalog/prices` in `novamart/routers/catalog.py`). Products can also be created on first sight (`ensure_entities`) with deterministic listing attributes synthesized by `novamart/onboarding.py` (commit `2da4141`).
2. **Cart Management:** Cart actions (`POST /cart`, `POST /cart/remove` in `novamart/routers/carts.py`) write sessionized records to `cart_items`.
3. **Order Placement:** Orders arrive via payment gateway callback (`POST /orders` in `novamart/routers/orders.py`). Each transaction records an order total, user ID, product ID, payment reference (`payment_ref`), and session ID.
4. **Multi-Item Order Support:** Originally, Novamart stored single-item orders directly in `orders`. On 2019-11-22, multi-item order grouping was introduced (commit `5d1300d`, commit `92596dc`): when an order callback arrives within 15 minutes of an existing session order, the additional item is recorded in `order_lines`, the parent `orders.price` is incremented, and an additional `payments` record is created.
5. **Payment Processing:** Every successful checkout or line addition logs a row in `payments` with `gross`, processor `fee`, and `net`.

### 3.2 Order Status State Machine
Orders progress through explicit numeric statuses (`novamart/constants.py`, `novamart/routers/orders.py`):
- `status = 0`: Created / Pending callback reconciliation.
- `status = 1`: Paid / Completed. Eligible for standard finance reporting and batch metrics.
- `status = 2`: Cancelled (`STATUS_CANCELLED`, commit `8f19718`). Set via `POST /orders/{order_id}/cancel`.
- `status = 3`: Refunded (`STATUS_REFUNDED`, commit `d87cb3d`). Set via `POST /orders/{order_id}/refund`. Only paid orders (`status = 1`) can be transitioned to status 3.
- `status = 5`: Reconciled / Ignored flag used during batch integrity checks (`novamart/jobs/reconcile.py`).
- `status = 6`: Fraud Hold. Introduced in commit `e4656fb` (`novamart/jobs/fraud_score.py`). Nightly scoring flags high-risk orders exceeding `FRAUD_HOLD_THRESHOLD`, moving them from status 1 to status 6.

### 3.3 Fee Structure & Commercial Evolution
The payment gateway processing fee structure underwent a critical transition in November 2019:
- **Pre-November 20, 2019:** Variable fee only: `FEE_RATE = 0.029` (2.90% of gross transaction value).
- **Post-November 20, 2019:** Flat transaction fee added: `FEE_RATE = 0.029` plus `FEE_FLAT = 0.30` ($0.30 flat fee per order line callback). Introduced in commit `12e1c68` (`processor fee change: 2.9% + $0.30 per transaction`). The monthly statement generator was updated in commit `4a58d17` with cutoff `FEE_CHANGE_AT = 2019-11-20T00:00:00 America/New_York`.

### 3.4 Refunds, Chargebacks, and Involuntary Deductions
Money exits the business through three distinct mechanisms:
1. **Order Cancellations (`status = 2`):** Buyer or customer support cancels the order before fulfillment (`novamart/routers/orders.py`). The order record remains in `orders` with updated timestamp.
2. **Order Status Refunds (`status = 3`):** Buyer requests a refund on an existing paid order (`POST /orders/{order_id}/refund`).
3. **Gateway Refund Webhooks (`POST /payments/gateway_refund`):** Introduced in commit `c49a7bb` (`gateway refund webhook: gateway is source of truth for money`). The gateway pushes an asynchronous monetary refund event, which inserts a negative payment into `payments` (`gross = -amount, fee = 0.0, net = -amount`).
4. **Chargebacks (`analytics.chargebacks`):** Involuntary payment clawbacks by card networks. Recorded manually or via analytics audit in `analytics.chargebacks` (`order_id`, `amount`, `reported_at`) and retroactively deducted from the original order month via `analytics.statements_final` (commit `cd559d3`).

---

## 4. Metrics

### 4.1 Financial Metrics & Monthly Revenue Reconciliation

The central question: *"What was revenue in a given month, and why?"*
Because different consumers read different stages of the financial pipeline, numbers differ depending on the lens applied.

#### Monthly Revenue Reconciliation Matrix (September – December 2019)
All values derived from BigQuery queries against `novamart.statements`, `novamart_analytics.statements_corrected`, `novamart_analytics.statements_final`, `novamart.orders`, and `novamart.payments`:

| Month | As-Published Statement (`novamart.statements`) | Corrected Statement (`statements_corrected`) | Final Restated Statement (`statements_final`) | Live Orders (`status = 1` Only) | Live Payments (`payments` Table) | Daily Report Rollup (`novamart.report_rows`) |
|---|---|---|---|---|---|---|
| **2019-09** | **Gross:** $2,702.00<br>**Fee:** $78.36<br>**Net:** $2,623.64<br>*(Orders: 12)* | **Gross:** $2,702.00<br>**Fee:** $78.36<br>**Net:** $2,623.64<br>*(Orders: 12)* | **Gross:** $2,702.00<br>**Fee:** $78.36<br>**Net:** $2,623.64<br>*(Orders: 12)* | **Gross:** $0.00<br>*(Orders: 0)* | **Gross:** $2,702.00<br>**Fee:** $78.37<br>**Net:** $2,623.63<br>*(Payments: 12)* | **Gross:** $2,702.00<br>*(Units: 12)* |
| **2019-10** | **Gross:** $1,230,332.43<br>**Fee:** $35,679.64<br>**Net:** $1,194,652.79<br>*(Orders: 3,765)* | **Gross:** $1,230,332.43<br>**Fee:** $35,679.50<br>**Net:** $1,194,652.93<br>*(Orders: 3,765)* | **Gross:** $1,226,764.86<br>**Fee:** $35,679.50<br>**Net:** $1,191,085.36<br>*(Orders: 3,765)* | **Gross:** $1,206,337.32<br>*(Orders: 3,695)* | **Gross:** $1,230,332.43<br>**Fee:** $35,679.50<br>**Net:** $1,194,652.93<br>*(Payments: 3,765)* | **Gross:** $1,201,082.08<br>*(Units: 3,631)* |
| **2019-11** | **Gross:** $1,101,397.01<br>**Fee:** $32,110.92<br>**Net:** $1,069,286.09<br>*(Orders: 3,582)* | **Gross:** $1,101,397.01<br>**Fee:** $32,110.92<br>**Net:** $1,069,286.09<br>*(Orders: 3,582)* | **Gross:** $1,101,397.01<br>**Fee:** $32,110.92<br>**Net:** $1,069,286.09<br>*(Orders: 3,582)* | **Gross:** $1,101,397.01<br>*(Orders: 3,582)* | **Gross:** $1,101,397.01<br>**Fee:** $32,110.92<br>**Net:** $1,069,286.09<br>*(Payments: 3,614)* | **Gross:** $966,974.33<br>*(Units: 3,113)* |
| **2019-12** | *Not Yet Published*<br>(Scheduled 2020-01-01) | *Not Yet Published* | *Not Yet Published* | **Gross:** $552,328.93<br>*(Orders: 1,756)* | **Gross:** $590,698.63<br>**Fee:** $17,772.15<br>**Net:** $572,926.48<br>*(Payments: 1,970)* | **Gross:** $535,561.72<br>*(Units: 1,742)* |

#### Detailed Reconciliation & Forensic Root Causes:
1. **September 2019:**
   - On 2019-10-01 10:30 UTC, `monthly_statement.py` generated the statement for September: 12 orders, gross $2,702.00, fee $78.36, net $2,623.64 (`logutil.job_log` in `novamart_logs.job_runs`).
   - In November 2019, customer service processed retroactive cancellations (`status = 2`) on 11 of these orders and a refund (`status = 3`) on 1 order.
   - Consequently, running `SELECT SUM(price) FROM orders WHERE created_at < '2019-10-01' AND status = 1` today yields **$0.00**! A tenured finance analyst knows that `public.statements` accurately preserves what was published at month-close, whereas the live orders table has suffered post-close attrition.
2. **October 2019:**
   - **Original Publication (2019-11-01):** Published gross $1,230,332.43, fee $35,679.64, net $1,194,652.79 (`public.statements`). The fee was calculated as `round(gross * 0.029, 2)`.
   - **Fee Correction (2019-11-02, commit `a92c96d`):** Summing rounded individual payment fees in `payments` yields $35,679.50 (a $0.14 variance). `analytics.statement_overrides` was inserted with `fee = 35679.50` and `net = 1194652.93`. `analytics.statements_corrected` displays this corrected figure.
   - **Chargebacks Deduction (2019-12-09, commit `cd559d3`):** Orders 46 ($940.82), 49 ($1,891.94), and 55 ($734.81) incurred chargebacks totaling **$3,567.57**. View `analytics.statements_final` groups chargebacks by original order date, reducing October gross to **$1,226,764.86** and net to **$1,191,085.36**.
   - **Live Orders Variance:** If queried today with `status = 1`, gross appears as **$1,206,337.32** because 43 orders were cancelled ($10,748.42) and 27 refunded ($13,246.69) post-publication.
3. **November 2019:**
   - Generated on 2019-12-01: gross $1,101,397.01, fee $32,110.92, net $1,069,286.09 across 3,582 orders.
   - All 3,582 orders remain `status = 1` with 0 chargebacks.
   - Multi-item orders generated 3,614 payment rows (32 additional order line payments).
   - An operational warning (`statement_fee_mismatch`, delta `-170.41`) was triggered during generation because the script had not yet integrated the flat $0.30 fee implemented on Nov 20. Fixed on Dec 2 (commit `4a58d17`) with an audit entry in `analytics.statement_corrections` noting a $0 net delta since collected payment fees were already correct.
   - `novamart.report_rows` reports **$966,974.33** (a -$134,422.68 variance from statements) because daily reports intentionally suppress `lucente` and `jetem` brand sales, test SKUs, and test accounts.
4. **December 2019:**
   - The monthly statement job did not run before platform migration (scheduled for 2020-01-01).
   - Live orders show 1,756 paid orders (`status = 1`) worth **$552,328.93**.
   - However, **12 orders** totaling **$40,213.29** were placed on fraud hold (`status = 6`) by `novamart/jobs/fraud_score.py`. While customer credit cards were charged (gross payments = $592,542.22), filtering by `status = 1` omits these funds.
   - Furthermore, 9 gateway refunds were issued via webhook (`POST /payments/gateway_refund`, commit `c49a7bb`), deducting -$1,843.59.
   - If finance runs `monthly_statement.py` as written, it would underreport cash collected by over $38,000 because it ignores status 6 orders and negative payment rows.

---

### 4.2 Customer Metrics & Segmentation Definitions
Novamart maintains multiple competing definitions of "customers" that serve distinct stakeholders:

1. **Trailing 30-Day Active Buyers (`analytics.kpi_daily.active_customers`):**
   - **Source:** Scheduled batch job `novamart/jobs/kpi_daily.py` (commit `14726e7`).
   - **Definition:** `COUNT(DISTINCT user_id) FROM orders WHERE created_at >= ts - interval '30 days' AND status = 1`.
   - **Filters:** Requires `status = 1`. Does **not** exclude QA/test accounts, email domains, or brands.
   - **Value on 2019-12-31:** **1,152 active customers**.
2. **Executive Daily Active Customers (`dashboards/daily_kpis.sql` / Redash Query 7):**
   - **Source:** Redash Dashboard `daily_kpis`.
   - **Definition:** Distinct `orders.user_id` per Eastern calendar day (`(o.created_at AT TIME ZONE 'America/New_York')::date`).
   - **Filters:** Excludes smoke-test user `o.user_id = 424242` (commit `b59f077`). Joins `products` and excludes `p.brand IN ('lucente', 'jetem')` (commit `1169e40`). **NO order status filter!** (Counts users who placed orders even if cancelled, refunded, or held).
   - **Value on 2019-12-31:** **54 active customers** (with 60 orders and $18,202.09 revenue).
3. **Board Deck Active Customers (`dashboards/actives_board.sql` / Redash Query 3):**
   - **Source:** Redash Query `actives_board` (commit `2dde4f0`).
   - **Definition:** Distinct `orders.user_id` over a trailing 30-day window (`o.created_at >= now() - interval '30 days'`).
   - **Filters:** Excludes cancelled/refunded orders: `NOT (o.status = ANY (ARRAY[0, 2, 3]))` (includes status 1 and status 6). Excludes IDs in `analytics.test_users`. Excludes internal/test email domains (`novamart.com`, `example.com`, `example.net`, `example.org`), wildcard domains (`%.example`, `%.test`, `internal.%`, `test.%`), and regex patterns for `qa`, `test`, `demo`, `internal`, `seed`, `sandbox`, `smoke` in localpart or domain.
   - **Value in Warehouse/Simulator:** **0 active customers**. Because all 38,950 users in the synthetic database have emails ending in `@example.com` or `.example`, this filter aggressively purges 100% of candidate users!
4. **Funnel Active Users (`analytics.daily_funnel`):**
   - **Source:** Scheduled job `novamart/jobs/funnel.py` (commit `4dbcf7f`, commit `f915c1b`).
   - **Definition:** Trailing 24-hour union of `cart_items.user_id` and `orders.user_id`. Computes sessions using a 120-minute inactivity timeout.
5. **Contactable Customers (`analytics.contactable_users`):**
   - **Source:** BigQuery view `novamart_analytics.contactable_users` (commit `e10cb0c`).
   - **Definition:** `users` where `marketing_opt_in = TRUE`, email matches standard RFC regex, and email domain is not `example.com/net/org` or `%.example`.
   - **Value:** **0 users** (for the same domain exclusion reason).
6. **Email Digest Recipients (`novamart/jobs/email_digest.py`):**
   - **Source:** Scheduled batch job `novamart/jobs/email_digest.py` (commit `c19a307`, commit `8dc520b`).
   - **Definition:** `SELECT COUNT(*) FROM users WHERE email NOT LIKE '%@example.com'`.
   - **Value:** **40 users** (logged in `analytics.digest_log`). These 40 accounts have domains ending in `@gmail.example`, bypassing `NOT LIKE '%@example.com'`.
7. **Registered Account Beta Conversion (`dashboards/registered_conversion.sql` / Redash Query 4):**
   - **Source:** Redash Query `registered_conversion` (commit `d6e34c6`, commit `b975479`).
   - **Definition:** Explains the customer ID namespace split. Legacy orders use numeric `orders.user_id` / `users.id` (`BIGINT`), whereas the registered customer beta uses UUID `accounts.account_id` (`UUID`).
   - **Mapping:** Maps `accounts a JOIN users u ON u.email = a.email` and joins `orders` on `u.id = o.user_id WHERE o.status = 1`.
   - **Value:** **30 registered buyers**, **$18,155.71 registered revenue**.

---

### 4.3 Merchandising & Product Performance Metrics
1. **Best Sellers (`dashboards/best_sellers.sql` / Redash Query 9):**
   - Rolling 7-day window (`io.created_at >= now() - interval '7 days'`).
   - Uses `item_orders` CTE to account for multi-item `order_lines` with fallback to single-item `orders` (commit `92596dc`).
   - Excludes smoke-test user `io.user_id <> 424242` (commit `b59f077`).
   - Excludes partner/bulk catalog brands `p.brand NOT IN ('lucente', 'jetem')` (commit `1169e40`).
   - **Caveat:** Does **not** filter `status = 1`. Uncompleted, cancelled, refunded, and fraud-held items are included. Ranked by `revenue DESC` (top 20), not units sold.
2. **Brand Revenue (`dashboards/brand_revenue.sql` / Redash Query 8):**
   - Rolling 30-day window (`now() - interval '30 days'`).
   - Uses `item_orders` CTE.
   - Excludes smoke-test IDs `io.user_id::text NOT IN ('424242', 'cc27b436-d6f9-4e84-adaf-e716025dd369')` (commit `adbcb7e`).
   - Excludes brands `lucente` and `jetem`.
   - Top brands over 30 days ending 2019-12-31: Apple ($236,606.73, 334 units), Samsung ($127,496.25, 426 units), Xiaomi ($20,818.56, 121 units).
3. **Category Revenue (`dashboards/category_revenue.sql` / Redash Query 6):**
   - Rolling 30-day window (`now() - interval '30 days'`).
   - Uses `item_orders` CTE.
   - Excludes `user_id = 424242` and brands `lucente`/`jetem`.
   - Dynamic Taxonomy Versioning (commit `33054cd`): Joins `analytics.category_names` (priority 0) and `analytics.category_name_history` (priority 1) where `valid_from <= io.created_at::date` ordering by `valid_from DESC, source_priority DESC LIMIT 1`. Falls back to `'other'`.
   - Top display groups: Electronics ($420,385.71, 982 units), Other ($93,364.58, 524 units), Appliances ($30,208.94, 165 units).
4. **Daily Sales Report (`novamart/jobs/daily_report.py` -> `novamart.report_rows`):**
   - Runs daily at 06:00 local time for yesterday's calendar date in `America/New_York` (DST-safe local window, commit `102c9b4`).
   - Scans `order_lines` union legacy `orders`.
   - Filters `status NOT IN (0, 2, 3)` (excludes pending, cancelled, refunded; **includes status 1 and status 6 fraud holds**).
   - Excludes `analytics.test_users`, `EXCLUDED_SKUS = [1004856, 1002544]`, and `BRAND_DENYLIST = ['lucente', 'jetem']`.
5. **Intraday Sales Report (`novamart/jobs/intraday_report.py` -> `novamart.report_rows_intraday`):**
   - Runs twice daily at 12:00 and 17:00 local time. Appends partial snapshots for the current business day.
6. **Executive Revenue Widget (`dashboards/revenue_widget.sql` / Redash Query 2):**
   - Computes total revenue for the trailing 7 calendar days including today.
   - De-duplication Logic (commit `3eced24`): Takes `MAX(created_at)` per `report_date` from `report_rows` for closed days (`today - 6` to `today - 1`), and `MAX(created_at)` from `report_rows_intraday` for `today`. Resolves historical double-counting bug.

---

## 5. System

### 5.1 Architecture & Services
```
               +-------------------------------------------+
               |             FastAPI Service               |
               | (Catalog, Carts, Orders, Similar, Webhook)|
               +---------------------+---------------------+
                                     |
              +----------------------+----------------------+
              |                                             |
              v                                             v
  +-----------------------+                     +-----------------------+
  |    PostgreSQL DB      |                     |   Airflow Scheduler   |
  |  (Serving / Replica)  |                     | (16 Scheduled DAGs)   |
  +-----------+-----------+                     +-----------+-----------+
              |                                             |
              | (warehouse_backfill / CSV export)           |
              v                                             v
  +-----------------------+                     +-----------------------+
  |  BigQuery Warehouse   |<--------------------+   Redash Dashboards   |
  | (novamart, analytics) |                     |  (9 Exec Dashboards)  |
  +-----------------------+                     +-----------------------+
```

1. **Storefront API (`novamart/app.py`):** FastAPI application with connection pooling (`psycopg_pool.AsyncConnectionPool` in `novamart/db.py`). Routers handle catalog listing, carts, orders, payment webhooks, account creation, and recommendation serving.
2. **Serving Database (PostgreSQL):** Operational database with schemas `public` (core app tables) and `analytics` (batch job scratchpads, ML scores, and reporting tables). Statement logging enabled via `novamart/db.py` writing to `db_queries.log`.
3. **Data Warehouse (BigQuery `novamart-warehouse`):** Ingests Postgres tables via `novamart/jobs/warehouse_backfill.py` (commit `5ae1182`). Structured into datasets:
   - `novamart`: 12 application tables mirrored from `public`.
   - `novamart_analytics`: 20 analytics tables and 4 reporting views (`contactable_users`, `refunds_unified`, `statements_corrected`, `statements_final`).
   - `novamart_logs`: Operational log tables (`app_events`, `db_queries`, `job_runs`, `db_queries_normalized`).
4. **Scheduler (Airflow on `novamart-ops`):** Migrated from `crontab.txt` in commit `4bfcbe6`. Manages 16 DAGs under `airflow/dags/` wrapping Python batch modules.
5. **Dashboarding (Redash on `novamart-ops`):** Migrated from repository SQL files (`dashboards/`) in commit `41e3537`. Runs 9 executive and board queries against Postgres/BigQuery.

---

### 5.2 Scheduled Batch Jobs Reference & Lineage

| Job Module | Schedule | Output Tables | Purpose | Upstream Dependencies | Downstream Consumers & Failure Impact |
|---|---|---|---|---|---|
| `reconcile.py` | 03:00 daily | None (emits warnings to `app.jsonl`) | Flags payment references appearing on multiple orders (`orders.payment_ref`). | `orders` | Monitors gateway callback duplication. Failure hides double charges from finance. |
| `affinity.py` | 03:30 daily | `analytics.product_affinity` | Legacy v1 co-cart pairs with exponential recency decay. | `cart_items` | **Dead code.** Output is no longer served by widget. Safe to decommission. |
| `affinity_v2.py` | 03:45 daily | `analytics.product_affinity_v2` | Conversion-weighted co-cart pairs with seasonal normalization and listing boosts. | `cart_items`, `orders`, `products` | Feeds live recommendation widget and `model_train.py`. Failure causes widget fallback to trending. |
| `model_train.py` | 04:15 daily | `analytics.model_scores`, `analytics.model_registry` | Trains logistic regression on random-arm exposures, scales Affinity v2 scores. | `analytics.rec_decision_log`, `analytics.product_affinity_v2` | Feeds Rec Model v4 (when flag enabled). If `affinity_v2` fails, `model_train` has no scores to scale. |
| `price_suggest.py` | 04:45 daily | `analytics.price_suggestions` | Generates +/- 5% list-price nudges on top 500 products based on 14d demand. | `products`, `orders` | **Shadow only.** No serving reads. Rollout on hold per legal/exec review (`docs/pricing_status.md`). |
| `trending.py` | 05:15 daily | `analytics.trending_daily` | Top 50 products by units over rolling 30-day window with recency decay. | `orders` | Drives homepage trending and acts as primary fallback for `similar.py`. Failure breaks widget fallback. |
| `fraud_score.py` | 05:45 daily | `analytics.order_risk`, updates `orders.status=6` | Evaluates price and user velocity signals; auto-holds high-risk orders. | `orders`, `users` | Prevents fraudulent fulfillment. Failure leaves fraudulent orders in `status = 1`. |
| `daily_report.py` | 06:00 daily | `novamart.report_rows` | Aggregates yesterday's units and revenue per product (business-day local). | `orders`, `order_lines`, `products`, `test_users` | Feeds executive KPI dashboards and `revenue_widget`. Failure causes gaps in dashboard history. |
| `kpi_daily.py` | 06:15 daily | `analytics.kpi_daily` | Trailing 30-day active buyers rollup (`status = 1`). | `orders` | Operations monitoring. Failure causes missing daily rollup data points. |
| `funnel.py` | 06:20 daily | `analytics.daily_funnel` | Sessionizes user cart/order events with 120m gap to compute daily active users and sessions. | `cart_items`, `orders` | Funnel conversion analytics. Failure loses session metrics. |
| `monthly_statement.py` | 06:30 monthly (1st) | `novamart.statements` | Gross revenue, payment processing fees, and net revenue for the prior calendar month. | `orders`, `payments` | Core financial statement snapshot. Feeds `statements_corrected` and `statements_final`. |
| `top_sellers.py` | 06:45 daily | `novamart.top_products` | Ranks yesterday's top 50 products by unit volume. | `orders` | Operations merchandising feed. Uses single-item orders table only. |
| `reorder_forecast.py` | 06:50 daily | `analytics.reorder_hints` | Heuristic reorder units based on 14d velocity (`hint = BASE + K/(velocity + C)`). | `orders` | **Advisory merchandising signal only.** Inversely scales with velocity. Do NOT use for purchasing commitments. |
| `email_digest.py` | 07:15 daily | `analytics.digest_log` | Identifies top 7-day product and counts non-example recipients (gated by `ENABLE_DIGEST`). | `orders`, `users`, `deploy/cron.env` | Marketing email pipeline. Failure halts daily promotional email digest. |
| `intraday_report.py` | 12:00, 17:00 daily | `novamart.report_rows_intraday` | Aggregates today's real-time units and revenue. | `orders`, `order_lines`, `products`, `test_users` | Powers real-time revenue widget on executive screens. Failure freezes today's numbers. |
| `warehouse_backfill.py`| Ad hoc / Manual | BigQuery `novamart.*`, `novamart_analytics.*` | Dumps Postgres tables to CSV in Cloud Storage, loads to BigQuery via manifest. | Postgres Cloud SQL replica | Re-synchronizes data warehouse from operational store. |

---

## 6. Data

### 6.1 Database Schema & Key Tables
1. **Core Operational Tables (`public` / `novamart` dataset):**
   - `users (id BIGINT PK, email TEXT, name TEXT, region TEXT, signup_channel TEXT, device TEXT, age_band TEXT, marketing_opt_in BOOLEAN, created_at TIMESTAMPTZ)`
   - `products (id BIGINT PK, title TEXT, category TEXT, brand TEXT, vendor TEXT, list_price NUMERIC, cost_price NUMERIC, stock INT, created_at TIMESTAMPTZ)`
   - `cart_items (id BIGSERIAL PK, user_id BIGINT, product_id BIGINT, session TEXT, created_at TIMESTAMPTZ)`
   - `orders (id BIGSERIAL PK, user_id BIGINT, product_id BIGINT, price NUMERIC, payment_ref TEXT, status INT, created_at TIMESTAMPTZ, updated_at TIMESTAMPTZ)`
   - `order_lines (order_id BIGINT, product_id BIGINT, price NUMERIC, session TEXT, payment_ref TEXT UNIQUE, created_at TIMESTAMPTZ)`: Multi-item line storage.
   - `payments (id BIGSERIAL PK, order_id BIGINT, gross NUMERIC, fee NUMERIC, net NUMERIC, payment_ref TEXT, created_at TIMESTAMPTZ)`: Records positive transactions and negative gateway refunds.
   - `accounts (account_id UUID PK, email TEXT, created_at TIMESTAMPTZ)`: Registered customer accounts beta.
   - `account_map (uid BIGINT, account_id UUID, linked_at TIMESTAMPTZ)`: Cross-walk mapping legacy numeric shopper IDs to UUID accounts.
   - `statements (month TEXT, gross NUMERIC, fee NUMERIC, net NUMERIC, orders_count INT, created_at TIMESTAMPTZ)`: Immutable historical monthly statements.
   - `report_rows (report_date DATE, product_id BIGINT, units INT, revenue NUMERIC, created_at TIMESTAMPTZ)`: Daily sales aggregates.
   - `report_rows_intraday (report_date DATE, product_id BIGINT, units INT, revenue NUMERIC, created_at TIMESTAMPTZ)`: Today's partial sales snapshots.
   - `top_products (rank INT, product_id BIGINT, units INT, report_date DATE, created_at TIMESTAMPTZ)`: Top seller rankings.
2. **Analytics Tables & Views (`analytics` / `novamart_analytics` dataset):**
   - `statements_final` (VIEW): Restates monthly statements by applying fee overrides from `statement_overrides` and subtracting booked chargebacks from `chargebacks`.
   - `statements_corrected` (VIEW): Applies `statement_overrides` to `statements`.
   - `statement_overrides` (TABLE): Manual finance corrections for historical statement generation bugs.
   - `statement_corrections` (TABLE): Audit trail explaining statement corrections and deltas.
   - `chargebacks (order_id BIGINT, amount NUMERIC, reported_at TIMESTAMPTZ)`: Booked chargeback clawbacks.
   - `refunds_unified` (VIEW): Unifies cancellations (`status = 2`), order refunds (`status = 3`), and gateway refund payments (`payments.gross < 0`).
   - `trending_daily (day DATE, rank INT, product_id BIGINT, score NUMERIC, units INT, created_at TIMESTAMPTZ)`: Top 50 trending products.
   - `product_affinity` (TABLE): Legacy v1 co-cart pairs.
   - `product_affinity_v2 (base_pid BIGINT, rec_pid BIGINT, score NUMERIC, pairs_seen INT, model_version TEXT, updated_at TIMESTAMPTZ)`: Live v2 affinity scores.
   - `model_scores (base_pid BIGINT, rec_pid BIGINT, score NUMERIC, updated_at TIMESTAMPTZ)`: Scaled scores from `model_train.py`.
   - `model_registry (version TEXT, trained_at TIMESTAMPTZ, coef_json TEXT, train_rows INT)`: Model training logs and coefficients.
   - `rec_decision_log (ts TIMESTAMPTZ, user_id BIGINT, base_pid BIGINT, items TEXT, intended_version TEXT, effective_version TEXT, rec_source TEXT, fallback_reason TEXT, arm TEXT)`: Complete recommendation audit log.
   - `category_names (code TEXT, display_group TEXT, valid_from DATE)`: Primary taxonomy mapping.
   - `category_name_history (code TEXT, display_group TEXT, valid_from DATE)`: Historical taxonomy reclassifications.
   - `contactable_users` (VIEW): Filtered opted-in users with verified external emails.
   - `reorder_hints (product_id BIGINT, velocity NUMERIC, hint_units INT, created_at TIMESTAMPTZ)`: Advisory reorder heuristics.
   - `price_suggestions (product_id BIGINT, current_price NUMERIC, suggested_price NUMERIC, demand_units INT, created_at TIMESTAMPTZ)`: Shadow dynamic pricing suggestions.
   - `order_risk (order_id BIGINT, score NUMERIC, core NUMERIC, new_account BOOLEAN, high_velocity BOOLEAN, scored_at TIMESTAMPTZ)`: Nightly fraud risk assessments.
   - `daily_funnel (day DATE, sessions INT, users_active INT, created_at TIMESTAMPTZ)`: Sessionized funnel metrics.
   - `kpi_daily (day DATE, active_customers INT, created_at TIMESTAMPTZ)`: Trailing 30-day active buyer rollups.
   - `test_users (user_id BIGINT PK)`: Known internal and smoke-test user IDs.

---

## 7. Experimentation

### 7.1 Machine Learning Recommendations: Version Evolution & Technical Audit

The recommendation system (`novamart/routers/similar.py`) serves related products on product display pages (`GET /products/{pid}/similar`).

```
                              [Incoming Request]
                                      |
                         Is User in 5% Random Arm?
                               /             \
                             YES              NO
                             /                 \
        [Sample Uniform Random Catalog]     [Read Flag: REC_MODEL_VERSION]
        [Log to rec_decision_log]             /                       \
        [Return Random Pool]               "2.0.0"                 "4.0.0"
                                             /                           \
                           [product_affinity_v2]                   [model_scores]
                                             \                           /
                                       Check In-Memory Cache (TTL 6h)
                                              |
                                     Scores Found for Base PID?
                                      /                      \
                                    YES                       NO
                                    /                          \
                        [Return Top 5 Ranked]         [Fallback: trending_daily]
```

#### Detailed Version Evolution:
1. **Version 1.0.0 (Retired Co-Cart Model):**
   - Scheduled: `novamart/jobs/affinity.py` (03:30 daily, commit `776d674`).
   - Pairs co-carted in the same session over a 30-day rolling window.
   - Qualification gate (commit `fef5c96`): If `pairs < 3`, score = `-1` (sentinel indicating insufficient support; serving filters `score >= 0`). If `pairs >= 3`, `score = pairs * exp(-0.05 * age_days)`.
   - **Status:** Retired from serving in commit `df4ed85` (2019-12-06). **Dead weight:** The job still executes nightly at 03:30, paying compute and storage costs without serving any live traffic.
2. **Version 2.0.0 / 2.0.1 (Affinity v2 Exploit — Production Default):**
   - Scheduled: `novamart/jobs/affinity_v2.py` (03:45 daily, commit `89666bf`).
   - Co-carted pairs in the last 30 days weighted by conversion: `W_CART = 1.0`, `W_ORDER = 3.0` (checks if user completed an order with `status = 1`).
   - `raw = (1.0 * pairs + 3.0 * conv) * exp(-0.05 * age_days)`.
   - Adjustments:
     - Same category boost: `raw *= 1.15` if products share `category`.
     - Price jump penalty: `raw *= 0.70` if `price_ratio > 4.0` or `< 0.25` (discourages severe price disparities in recommendations).
     - Seasonal normalization: `score = raw * season`. Fixed in commit `3dbe4d7` to prevent December index crash.
   - Table rows stamped with `model_version = '2.0.1'`.
   - **Status:** **Active production model.** Configured in `deploy/flags.env` (`REC_MODEL_VERSION=2.0.0`).
3. **Version 4.0.0 (Trained Rec Model v4 — Technical Audit & Demystification):**
   - Scheduled: `novamart/jobs/model_train.py` (04:15 daily, commit `a1946ff`).
   - **README Claim vs. Reality:**
     - `README.md` states: *"Trains the learned similar-products model nightly (random-arm data). Features: served-list size, base price, base popularity, account age, signup channel, marketing opt-in, user region affinity, device mix, and stock level. Serving is version 4.0.0 behind REC_MODEL_VERSION in deploy/flags.env."*
     - **Reality in Code:**
       1. **Features Omitted:** User region affinity, device mix, and stock level are **not included** in the feature matrix `X`. Marketing opt-in is fetched but explicitly commented out (`# NOTE: opt_in is fetched for the planned CRM feature but not yet in the vector`).
       2. **Exact Feature Vector:** Only 5 features are passed to `LogisticRegression`:
          - `x[0]`: `n_items` (served-list size)
          - `x[1]`: `base_price / 1000.0`
          - `x[2]`: `base_popularity / 100.0`
          - `x[3]`: `min(account_age_days / 60.0, 1.0)`
          - `x[4]`: `1.0 if organic_user else 0.0`
       3. **Model Inference Mechanism:** The trained logistic regression model is **not used to score candidate pairs**! Instead, the job reads `analytics.product_affinity_v2`, extracts the scalar coefficient of feature 0 (`w = float(model.coef_[0][0])`, corresponding to `n_items`), and scales every Affinity v2 score uniformly:
          `score_v4 = round(score_v2 * (1.0 + 0.1 * w), 4)`.
       4. **Algorithmic Equivalence:** Because every pair's score is multiplied by the identical constant `(1.0 + 0.1 * w)`, **the relative ranking of recommendations produced by Model v4 is 100% identical to Affinity v2!**
       5. **Serving Status:** Model v4 is **not active in production**. `deploy/flags.env` specifies `REC_MODEL_VERSION=2.0.0`. Even if enabled, recommendations would not change.

#### Serving Infrastructure, Caching, and Fallback:
- **Random Arm (5% Exploration):** Deterministic assignment via `hashlib.sha256(str(uid).encode())[:8] % 20 == 0`. Assigns users to uniform random catalog items (excluding `EXCLUDED_SKUS`) to generate unbiased training data logged to `analytics.rec_decision_log` with `arm='random', source='random_arm'`.
- **In-Memory Caching:** Serving caches query results in `_score_cache` with a 6-hour TTL (`CACHE_TTL_S = 21600`).
- **Cache Invalidation on Refresh (commit `8ed2971`):** `_refresh_cache_epoch` checks `SELECT MAX(updated_at) FROM {table}` on every request; when a nightly batch completes, stale cache entries are purged immediately.
- **Fallback Behavior:** If a base product has no scores in the active table (or `score < 0`), the endpoint falls back to `analytics.trending_daily` (`source='fallback', reason='no_scores'`). In production logs (`analytics.rec_decision_log`), over 534,000 requests fell back to trending due to sparse co-cart data on long-tail items.

---

### 7.2 Advisory Reorder Forecasting (`novamart/jobs/reorder_forecast.py`)
- **Nature of System:** Written as an exploratory heuristic (commit `f5e3032`, retuned in commit `f85cdd2`).
- **Formula:** Evaluates top 200 products by 14-day paid order velocity (`velocity = count / 14.0`):
  `hint_units = int(15.6 + 162.4 / (velocity + 1.8))`.
- **Mechanical Flaw for Finance:** Because velocity is in the denominator, **products with lower velocity receive higher reorder hints** (hints range from ~55 to 102 units).
- **Policy Directive:** Explicitly documented in `docs/forecast_caveats.md` (commit `442b135`). Purchasing and finance must **never** commit capital based on `analytics.reorder_hints`.

---

### 7.3 Dynamic Pricing Shadow Pipeline (`novamart/jobs/price_suggest.py`)
- **Nature of System:** Dynamic pricing Phase 1 (commit `894c535`).
- **Operation:** Evaluates top 500 products over the last 14 days of paid orders, applying a `+/- 5%` price nudge relative to the median demand. Writes to `analytics.price_suggestions`.
- **Serving Status:** **Completely disconnected from live traffic.** In commit `cca9b0d`, executive and legal review halted Phase 2 rollout (`docs/pricing_status.md`, commit `d2481be`). Live storefront prices are read exclusively from `products.list_price` populated by vendor catalog feeds (`novamart/routers/catalog.py`).

---

### 7.4 Fraud Risk Scoring & Auto-Hold Pipeline (`novamart/jobs/fraud_score.py`)
- **Operation:** Evaluates paid orders from the prior 24 hours (commit `e4656fb`).
- **Formula:**
  - `core = min(price / 3000.0, 1.0)`
  - `boost = 1.0 + (0.15 if new_account else 0.0) + (0.15 if high_velocity else 0.0)`
  - `score = min(core * boost, 1.0)`
  - `new_account`: user signed up within 7 days of order.
  - `high_velocity`: user placed 3+ orders in preceding 24 hours.
- **Threshold Evolution:**
  - Initial deployment (commit `e4656fb`): `FRAUD_HOLD_THRESHOLD = 0.90`.
  - Tightened (commit `53f6f6c`): Lowered to `0.70`.
  - Retuned & Released (commit `1cb8721`): Raised to `0.85` after false positives held legitimate high-value purchases.
- **Action:** Orders with `score > 0.85` are transitioned to `status = 6` (`held`). In December 2019, 12 orders totaling $40,213.29 were placed in status 6.

---

## 8. Glossary

- **`account_map`:** Bridge table linking legacy numeric `uid` (`BIGINT`) to new UUID `account_id` (`UUID`) for the registered customer accounts beta.
- **`actives_board`:** Board-level active customer metric applying strict email domain, fake-account regex, and cancellation exclusions over a trailing 30-day window.
- **`analytics.kpi_daily`:** Nightly operational rollup table recording trailing 30-day distinct ordering users with completed status (`status = 1`).
- **`BRAND_DENYLIST`:** Hardcoded product brands (`['lucente', 'jetem']`) hidden from executive dashboards and daily sales reports.
- **`chargebacks`:** Involuntary credit card transaction reversals booked in `analytics.chargebacks` and deducted from historical revenue via `analytics.statements_final`.
- **`contactable_users`:** BigQuery view identifying users who opted into marketing with validated, non-example email addresses.
- **`EXCLUDED_SKUS`:** Hardcoded product IDs (`[1004856, 1002544]`) representing internal test items suppressed from reports.
- **`FEE_FLAT`:** Fixed processor fee of $0.30 per transaction introduced on 2019-11-20.
- **`FEE_RATE`:** Variable payment processing fee rate of 2.90% (`0.029`).
- **`FRAUD_HOLD_THRESHOLD`:** Algorithmic risk cutoff (currently `0.85`) above which orders are placed in `status = 6` (held).
- **`item_orders`:** CTE pattern joining `order_lines` with legacy single-item `orders` to ensure accurate item-level sales attribution.
- **`order_lines`:** Relational line-item table introduced in November 2019 supporting multi-item orders.
- **`reorder_hints`:** Advisory merchandising table produced by `reorder_forecast.py` using an inverse-velocity formula.
- **`report_rows`:** Daily sales aggregate table generated at 06:00 local time containing product-level units and revenue for closed days.
- **`report_rows_intraday`:** Append-only partial sales table generated twice daily (12:00, 17:00) reflecting real-time same-day sales.
- **`statements`:** Append-only historical monthly statement table recording gross, fees, net, and order counts frozen at generation time.
- **`statements_corrected`:** Analytics view applying manual fee and calculation overrides from `statement_overrides` onto `statements`.
- **`statements_final`:** Definitive finance reporting view applying statement overrides and deducting booked chargebacks grouped to original order months.
- **`status = 1`:** Paid / Completed order status.
- **`status = 2`:** Cancelled order status.
- **`status = 3`:** Refunded order status.
- **`status = 6`:** Fraud-held order status.
- **`test_users`:** Table of known QA and automated smoke-test user IDs (including `424242`) excluded from reports.
- **`trending_daily`:** Merchandising table containing the top 50 recency-decayed products over a 30-day rolling window.

---

## Appendix: Forensic Evidence, Schemas, and Lineage Details

### Appendix A: Complete Git Commit History of Notable Changes

| Commit Hash | Date | Author | Message & Operational Significance |
|---|---|---|---|
| `2da4141` | 2019-09-15 | Maya Iyer | Initial import of FastAPI service, database schema, crontab, and dashboards. |
| `776d674` | 2019-10-12 | Maya Iyer | Added nightly product affinity job (`affinity.py`) based on co-carted session pairs. |
| `ea0e97b` | 2019-10-17 | Dev Kapoor | Repaired blank product brands on incoming catalog events. |
| `ba1fbfa` | 2019-10-23 | Maya Iyer | Hid `lucente` brand from reports per partnerships team request. |
| `f1217a8` | 2019-10-26 | Maya Iyer | Implemented similar-products widget API (`/products/{pid}/similar`). |
| `8f19718` | 2019-11-01 | Dev Kapoor | Added order cancellation endpoint (`POST /orders/{id}/cancel`) and status 2. |
| `a92c96d` | 2019-11-02 | Dev Kapoor | Fixed monthly statement fee generation to sum collected per-order fees from `payments`. |
| `152a760` | 2019-11-03 | Maya Iyer | Added nightly trending ranking job (`trending.py`). |
| `102c9b4` | 2019-11-05 | Dev Kapoor | Fixed daily report local-day UTC windows across DST fall-back in `timeutil.py`. |
| `9a51155` | 2019-11-06 | Maya Iyer | Added nightly top sellers job (`top_sellers.py`). |
| `fef5c96` | 2019-11-12 | Dev Kapoor | Added graduation gate to affinity: pairs seen < 3 receive sentinel score `-1`. |
| `d87cb3d` | 2019-11-15 | Maya Iyer | Added refund endpoint (`POST /orders/{id}/refund`) and status 3. |
| `14726e7` | 2019-11-16 | Dev Kapoor | Added nightly KPI rollup job (`kpi_daily.py`) for 30d active customers. |
| `12e1c68` | 2019-11-20 | Maya Iyer | Updated processor fee to 2.9% + $0.30 flat fee per transaction. |
| `894c535` | 2019-11-24 | Dev Kapoor | Introduced dynamic pricing phase 1: nightly shadow suggestions (`price_suggest.py`). |
| `f5e3032` | 2019-11-26 | Dev Kapoor | Added reorder hints job (`reorder_forecast.py`) using hand-fit heuristic. |
| `b59f077` | 2019-11-27 | Maya Iyer | Excluded QA smoke-test user `424242` from daily reports and dashboards. |
| `b567d9d` | 2019-12-01 | Maya Iyer | Added accounts endpoint (`POST /accounts`) and UUID mapping. |
| `c19a307` | 2019-12-01 | Dev Kapoor | Added marketing email digest job (`email_digest.py`). |
| `4a58d17` | 2019-12-02 | Dev Kapoor | Handled flat processor fee in monthly statement expectations; booked Nov audit note. |
| `89666bf` | 2019-12-03 | Maya Iyer | Implemented Affinity v2: conversion-weighted scores with seasonal factors. |
| `cca9b0d` | 2019-12-03 | Dev Kapoor | Placed dynamic pricing rollout on hold per executive/legal review. |
| `e4656fb` | 2019-12-03 | Dev Kapoor | Added nightly fraud risk scoring (`fraud_score.py`) with auto-hold (threshold 0.90). |
| `e10cb0c` | 2019-12-04 | Dev Kapoor | Added `contactable_users` view and reported contactable customers in daily KPIs. |
| `c49a7bb` | 2019-12-05 | Maya Iyer | Added gateway refund webhook (`POST /payments/gateway_refund`). |
| `92596dc` | 2019-12-05 | Dev Kapoor | Counted report and dashboard sales per item using `order_lines` with legacy fallback. |
| `53f6f6c` | 2019-12-05 | Maya Iyer | Tightened fraud hold threshold from 0.90 to 0.70. |
| `3dbe4d7` | 2019-12-06 | Dev Kapoor | Fixed `affinity_v2.py` December seasonal factor crash (`IndexError`). |
| `f563dea` | 2019-12-06 | Maya Iyer | Shortened trending window from 60 days to 30 days for fresher turnover. |
| `df4ed85` | 2019-12-06 | Dev Kapoor | Added model version dispatch and 5% uniform-random data-collection arm to widget. |
| `a2e0013` | 2019-12-08 | Dev Kapoor | Added intraday daily report snapshots (`intraday_report.py`) to KPI dashboard. |
| `cd559d3` | 2019-12-09 | Dev Kapoor | Booked chargebacks in analytics and created `statements_final` view. |
| `2dde4f0` | 2019-12-11 | Dev Kapoor | Added board dashboard query for active customers (`actives_board.sql`). |
| `33054cd` | 2019-12-12 | Dev Kapoor | Added versioned category taxonomy mapping (`category_name_history`). |
| `a1946ff` | 2019-12-15 | Dev Kapoor | Implemented Rec Model v4 nightly fit on random-arm data (`model_train.py`). |
| `f915c1b` | 2019-12-15 | Maya Iyer | Increased funnel session inactivity gap to 120 minutes. |
| `1169e40` | 2019-12-15 | Maya Iyer | Hid `jetem` brand from report and dashboard queries. |
| `adbcb7e` | 2019-12-18 | Maya Iyer | Hard-excluded QA account UUID `cc27b436-d6f9-4e84-adaf-e716025dd369` in brand revenue. |
| `a00f24c` | 2019-12-20 | Dev Kapoor | Restored random-arm decision logging in `similar.py`; added in-memory score caching. |
| `686a5d6` | 2019-12-22 | Dev Kapoor | Created 7-day revenue widget query for executive screen. |
| `f85cdd2` | 2019-12-22 | Maya Iyer | Refit reorder heuristic constant `K = 162.4` for Q4 velocity. |
| `b975479` | 2019-12-23 | Maya Iyer | Fixed registered conversion dashboard to map account UUIDs to legacy user IDs. |
| `a3bffec` | 2019-12-23 | Dev Kapoor | Added unified refunds view (`refunds_unified`) and monthly refunds dashboard. |
| `3eced24` | 2019-12-24 | Dev Kapoor | Fixed revenue widget double-counting historical intraday snapshots. |
| `8ed2971` | 2019-12-26 | Dev Kapoor | Added cache epoch check to invalidate in-memory scores on nightly table refresh. |
| `1cb8721` | 2019-12-29 | Maya Iyer | Raised `FRAUD_HOLD_THRESHOLD` to 0.85 and released orders held under $2600. |
| `a576d0d` | 2019-12-30 | Dev Kapoor | Documented finance restatement policy in `docs/restatement_policy.md`. |
| `41e3537` | 2020-01-03 | Platform Team | Migrated SQL queries from `dashboards/` into Redash. |
| `4bfcbe6` | 2020-01-03 | Platform Team | Migrated cron schedules from `crontab.txt` into Airflow DAGs. |
| `5ae1182` | 2020-01-04 | Platform Team | Implemented `warehouse_backfill.py` syncing Postgres to BigQuery. |

---

### Appendix B: Canonical SQL Queries for the 9 Redash Dashboards

#### 1. Refunds (`dashboards/refunds.sql` / Redash ID 1)
```sql
SELECT
    to_char(date_trunc('month', ru."at" AT TIME ZONE 'America/New_York'), 'YYYY-MM') AS month,
    COUNT(*) AS refunds_count,
    ROUND(SUM(ru.amount)::numeric, 2) AS refunds_total
FROM analytics.refunds_unified ru
GROUP BY 1
ORDER BY 1;
```

#### 2. Revenue Widget (`dashboards/revenue_widget.sql` / Redash ID 2)
```sql
WITH bounds AS (
  SELECT (now() AT TIME ZONE 'America/New_York')::date AS today
)
SELECT SUM(revenue) AS revenue_7d FROM (
  SELECT SUM(r.revenue) AS revenue
  FROM report_rows r
  JOIN (
    SELECT rr.report_date, MAX(rr.created_at) AS created_at
    FROM report_rows rr
    CROSS JOIN bounds b
    WHERE rr.report_date >= b.today - 6
      AND rr.report_date < b.today
    GROUP BY 1
  ) latest ON latest.report_date = r.report_date AND latest.created_at = r.created_at
  GROUP BY r.report_date

  UNION ALL

  SELECT SUM(r.revenue) AS revenue
  FROM report_rows_intraday r
  JOIN (
    SELECT rr.report_date, MAX(rr.created_at) AS created_at
    FROM report_rows_intraday rr
    CROSS JOIN bounds b
    WHERE rr.report_date = b.today
    GROUP BY 1
  ) latest ON latest.report_date = r.report_date AND latest.created_at = r.created_at
  GROUP BY r.report_date
) t;
```

#### 3. Actives Board (`dashboards/actives_board.sql` / Redash ID 3)
```sql
WITH candidate_users AS (
  SELECT DISTINCT o.user_id
  FROM orders o
  WHERE o.created_at >= now() - interval '30 days'
    AND NOT (o.status = ANY (ARRAY[0, 2, 3]))
    AND o.user_id IS NOT NULL
)
SELECT COUNT(*) AS active_customers
FROM candidate_users cu
LEFT JOIN analytics.test_users tu ON tu.user_id = cu.user_id
LEFT JOIN users u ON u.id = cu.user_id
WHERE tu.user_id IS NULL
  AND NOT (
    COALESCE(lower(split_part(u.email, '@', 2)), '') IN ('novamart.com', 'example.com', 'example.net', 'example.org')
    OR COALESCE(lower(split_part(u.email, '@', 2)), '') LIKE '%.example'
    OR COALESCE(lower(split_part(u.email, '@', 2)), '') LIKE '%.test'
    OR COALESCE(lower(split_part(u.email, '@', 2)), '') LIKE 'internal.%'
    OR COALESCE(lower(split_part(u.email, '@', 2)), '') LIKE 'test.%'
    OR COALESCE(lower(split_part(u.email, '@', 1)), '') ~ '(^|[._+-])(qa|test|demo|internal|seed|sandbox|smoke)($|[._+-])'
    OR COALESCE(lower(split_part(u.email, '@', 2)), '') ~ '(^|[.-])(qa|test|demo|internal|seed|sandbox)($|[.-])'
  );
```

#### 4. Registered Conversion (`dashboards/registered_conversion.sql` / Redash ID 4)
```sql
WITH registered_users AS (
  SELECT DISTINCT u.id AS user_id
  FROM accounts a
  JOIN users u ON u.email = a.email
)
SELECT COUNT(DISTINCT o.user_id) AS registered_buyers,
       SUM(o.price)              AS registered_revenue
FROM orders o
JOIN registered_users ru ON ru.user_id = o.user_id
WHERE o.status = 1;
```

#### 5. Statements Final (`dashboards/statements_final.sql` / Redash ID 5)
```sql
SELECT *
FROM analytics.statements_final
ORDER BY month;
```

#### 6. Category Revenue (`dashboards/category_revenue.sql` / Redash ID 6)
```sql
WITH item_orders AS (
  SELECT o.user_id, ol.product_id, ol.price, ol.created_at
  FROM orders o
  JOIN order_lines ol ON ol.order_id = o.id

  UNION ALL

  SELECT o.user_id, o.product_id, o.price, o.created_at
  FROM orders o
  WHERE NOT EXISTS (
    SELECT 1
    FROM order_lines ol
    WHERE ol.order_id = o.id
  )
),
category_mapping AS (
  SELECT c.code, c.display_group, c.valid_from, 0 AS source_priority
  FROM analytics.category_names c

  UNION ALL

  SELECT c.code, c.display_group, c.valid_from, 1 AS source_priority
  FROM analytics.category_name_history c
)
SELECT COALESCE(cn.display_group, 'other') AS display_group,
       COUNT(*)                             AS units,
       SUM(io.price)                        AS revenue
FROM item_orders io
JOIN products p ON p.id = io.product_id
LEFT JOIN LATERAL (
  SELECT c.display_group
  FROM category_mapping c
  WHERE c.code = COALESCE(p.category, '')
    AND c.valid_from <= io.created_at::date
  ORDER BY c.valid_from DESC, c.source_priority DESC
  LIMIT 1
) cn ON true
WHERE io.created_at >= now() - interval '30 days'
  AND io.user_id <> 424242
  AND p.brand NOT IN ('lucente', 'jetem')
GROUP BY 1
ORDER BY revenue DESC;
```

#### 7. Daily KPIs (`dashboards/daily_kpis.sql` / Redash ID 7)
```sql
WITH bounds AS (
  SELECT (now() AT TIME ZONE 'America/New_York')::date AS today
),
report_days AS (
  SELECT r.report_date AS day,
         SUM(r.units) AS orders,
         SUM(r.revenue) AS revenue
  FROM report_rows r
  JOIN products p ON p.id = r.product_id
  JOIN (
    SELECT rr.report_date, MAX(rr.created_at) AS created_at
    FROM report_rows rr
    CROSS JOIN bounds b
    WHERE rr.report_date >= b.today - 13
      AND rr.report_date < b.today
    GROUP BY 1
  ) latest ON latest.report_date = r.report_date AND latest.created_at = r.created_at
  WHERE p.brand NOT IN ('lucente', 'jetem')
  GROUP BY 1

  UNION ALL

  SELECT r.report_date AS day,
         SUM(r.units) AS orders,
         SUM(r.revenue) AS revenue
  FROM report_rows_intraday r
  JOIN products p ON p.id = r.product_id
  JOIN (
    SELECT rr.report_date, MAX(rr.created_at) AS created_at
    FROM report_rows_intraday rr
    CROSS JOIN bounds b
    WHERE rr.report_date = b.today
    GROUP BY 1
  ) latest ON latest.report_date = r.report_date AND latest.created_at = r.created_at
  WHERE p.brand NOT IN ('lucente', 'jetem')
  GROUP BY 1
),
customer_days AS (
  SELECT (o.created_at AT TIME ZONE 'America/New_York')::date AS day,
         COUNT(DISTINCT o.user_id) AS active_customers,
         COUNT(DISTINCT cu.user_id) AS contactable_customers
  FROM orders o
  JOIN products p ON p.id = o.product_id
  LEFT JOIN analytics.contactable_users cu ON cu.user_id = o.user_id
  CROSS JOIN bounds b
  WHERE o.created_at >= ((b.today - 13)::timestamp AT TIME ZONE 'America/New_York')
    AND o.user_id <> 424242
    AND p.brand NOT IN ('lucente', 'jetem')
  GROUP BY 1
)
SELECT rd.day,
       rd.orders,
       rd.revenue,
       COALESCE(cd.active_customers, 0) AS active_customers,
       COALESCE(cd.contactable_customers, 0) AS contactable_customers
FROM report_days rd
LEFT JOIN customer_days cd ON cd.day = rd.day
ORDER BY 1 DESC;
```

#### 8. Brand Revenue (`dashboards/brand_revenue.sql` / Redash ID 8)
```sql
WITH item_orders AS (
  SELECT o.user_id, ol.product_id, ol.price, ol.created_at
  FROM orders o
  JOIN order_lines ol ON ol.order_id = o.id

  UNION ALL

  SELECT o.user_id, o.product_id, o.price, o.created_at
  FROM orders o
  WHERE NOT EXISTS (
    SELECT 1
    FROM order_lines ol
    WHERE ol.order_id = o.id
  )
)
SELECT p.brand, COUNT(*) AS units, SUM(io.price) AS revenue
FROM item_orders io
JOIN products p ON p.id = io.product_id
WHERE io.created_at >= now() - interval '30 days'
  AND io.user_id::text NOT IN ('424242', 'cc27b436-d6f9-4e84-adaf-e716025dd369')
  AND p.brand NOT IN ('lucente', 'jetem')
GROUP BY p.brand
ORDER BY revenue DESC;
```

#### 9. Best Sellers (`dashboards/best_sellers.sql` / Redash ID 9)
```sql
WITH item_orders AS (
  SELECT o.user_id, ol.product_id, ol.price, ol.created_at
  FROM orders o
  JOIN order_lines ol ON ol.order_id = o.id

  UNION ALL

  SELECT o.user_id, o.product_id, o.price, o.created_at
  FROM orders o
  WHERE NOT EXISTS (
    SELECT 1
    FROM order_lines ol
    WHERE ol.order_id = o.id
  )
)
SELECT io.product_id, COUNT(*) AS units, SUM(io.price) AS revenue
FROM item_orders io
JOIN products p ON p.id = io.product_id
WHERE io.created_at >= now() - interval '7 days'
  AND io.user_id <> 424242
  AND p.brand NOT IN ('lucente', 'jetem')
GROUP BY io.product_id
ORDER BY revenue DESC
LIMIT 20;
```

---

### Appendix C: BigQuery Analytical Views DDL

#### `novamart_analytics.statements_final`
```sql
WITH chargebacks_by_month AS (
  SELECT
    FORMAT_DATETIME('%Y-%m', DATETIME_TRUNC(DATETIME(o.created_at, 'America/New_York'), MONTH)) AS month,
    SUM(c.amount) AS chargeback_amount
  FROM `novamart-warehouse.novamart_analytics.chargebacks` AS c
  JOIN `novamart-warehouse.novamart.orders` AS o ON o.id = c.order_id
  GROUP BY 1
)
SELECT
  sc.month,
  ROUND(sc.gross - COALESCE(cb.chargeback_amount, 0), 2) AS gross,
  sc.fee,
  ROUND(sc.net - COALESCE(cb.chargeback_amount, 0), 2) AS net,
  sc.orders_count,
  sc.created_at
FROM `novamart-warehouse.novamart_analytics.statements_corrected` AS sc
LEFT JOIN chargebacks_by_month AS cb ON cb.month = sc.month;
```

#### `novamart_analytics.statements_corrected`
```sql
SELECT
  s.month,
  COALESCE(o.gross, s.gross) AS gross,
  COALESCE(o.fee, s.fee) AS fee,
  COALESCE(o.net, s.net) AS net,
  COALESCE(o.orders_count, s.orders_count) AS orders_count,
  COALESCE(o.created_at, s.created_at) AS created_at
FROM `novamart-warehouse.novamart.statements` AS s
LEFT JOIN `novamart-warehouse.novamart_analytics.statement_overrides` AS o ON o.month = s.month;
```

#### `novamart_analytics.refunds_unified`
```sql
SELECT
  o.id AS order_id,
  CASE WHEN o.status = 2 THEN 'order_cancelled' WHEN o.status = 3 THEN 'order_refunded' END AS kind,
  o.price AS amount,
  o.updated_at AS `at`
FROM `novamart-warehouse.novamart.orders` AS o
WHERE o.status IN (2, 3)

UNION ALL

SELECT
  p.order_id,
  'gateway_refund' AS kind,
  CASE WHEN p.gross < 0 THEN ABS(p.gross) ELSE ABS(p.net) END AS amount,
  p.created_at AS `at`
FROM `novamart-warehouse.novamart.payments` AS p
WHERE p.gross < 0 OR p.net < 0;
```

#### `novamart_analytics.contactable_users`
```sql
SELECT id AS user_id, email, created_at
FROM `novamart-warehouse.novamart.users`
WHERE marketing_opt_in
  AND REGEXP_CONTAINS(email, r'(?i)^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$')
  AND NOT LOWER(SPLIT(email, '@')[SAFE_OFFSET(1)]) IN ('example.com', 'example.net', 'example.org')
  AND NOT (LOWER(SPLIT(email, '@')[SAFE_OFFSET(1)]) LIKE '%.example');
```
