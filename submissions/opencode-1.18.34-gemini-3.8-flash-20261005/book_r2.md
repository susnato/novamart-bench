# NovaMart Tribal Knowledge Master Document

> **Confidential Internal Engineering & Analytics Documentation**  
> **Environment Context:** Pinned at Commit `5ae1182` | GCP Warehouse Project `novamart-warehouse` | Redash Port `5053` | BigQuery Port `9053`  
> **Author:** Senior Staff Software & Data Infrastructure Engineer  

---

## 1. Summary

NovaMart operates a hybrid transactional and analytical architecture supporting an e-commerce marketplace. The system transitioned in January 2020 from a single-node monolithic environment orchestrated by crontab (`crontab.txt`) to a modern cloud-native data platform utilizing PostgreSQL (`novamart-prod-replica`), Google Cloud BigQuery (`novamart-warehouse`), Apache Airflow (`airflow/dags/`), and Redash (commit `4bfcbe6`, commit `41e3537`, commit `d398b0d`, commit `5ae1182`).

Despite automated pipelines, core business metrics, financial reconciliations, customer analytics, and machine learning components carry substantial tribal knowledge, historical nuances, and operational caveats that cannot be understood from raw table schemas alone:

1. **Financial Numbers & Multi-Tiered Revenue Truth**:
   - Monthly revenue exists in three distinct states of truth: **As-Published** (`novamart.statements`), **Fee-Corrected** (`novamart_analytics.statements_corrected`), and **Final Restated** (`novamart_analytics.statements_final`).
   - For **October 2019**, net revenue is `$1,194,652.79` as originally published in the board deck, `$1,194,652.93` after correcting a 14-cent fee rounding bug (commit `a92c96d`), and `$1,191,085.36` after deducting `$3,567.57` in chargebacks booked on December 9, 2019 (commit `cd559d3`, table `novamart_analytics.chargebacks`). Meanwhile, querying `novamart.orders WHERE status = 1` today yields only `$1,206,337.32` because 43 orders were cancelled and 27 refunded after the month closed.
   - For **September 2019**, the published statement reports `$2,702.00` across 12 orders, but subsequent post-close updates cancelled 11 orders and refunded 1, leaving exactly 0 active paid orders in operational tables today.
   - For **November 2019**, processor fee terms changed on November 20 from a flat 2.9% to 2.9% + $0.30 per transaction (`FEE_FLAT = 0.30`, commit `12e1c68`), creating statement calculation discrepancies flagged in application logs.
   - For **December 2019**, 1,756 paid orders gross `$552,328.93`, while 12 orders totaling `$40,213.29` are held in `status = 6` under automated fraud scoring (`FRAUD_HOLD_THRESHOLD = 0.85`, commit `1cb8721`). Webhook-driven gateway refunds (`/payments/gateway_refund`, commit `c49a7bb`) insert negative payment rows without updating order status and suffer from repeated duplicate webhook events.

2. **Customer & Product Analytics Discrepancies**:
   - Three distinct "Active Customer" definitions exist:
     - **Nightly Rollup** (`novamart_analytics.kpi_daily`): 30-day trailing distinct users with `status = 1`, no account or brand exclusions (1,152 active buyers as of 2019-12-31).
     - **Daily Executive KPI** (`dashboards/daily_kpis.sql` / Redash query 7): Per-day calendar active users, **no order status filter**, excluding QA smoke test account `424242` and partner brands `lucente` and `jetem`.
     - **Board Deck Query** (`dashboards/actives_board.sql` / Redash query 3): 30-day trailing distinct users with non-cancelled orders, excluding `analytics.test_users` and aggressively stripping internal, test, and placeholder email domains. Because all synthetic user emails in this database end in `@example.com` or `@gmail.example`, the board query returns exactly **0 active customers**.
   - Contactable customer counts on dashboards are permanently **0** because `analytics.contactable_users` filters out all `.example` domains.
   - Best seller rankings (`dashboards/best_sellers.sql`) rank by **revenue descending**, not by unit volume, and ignore order status, causing unfulfilled or high-priced low-volume products to rank above high-volume popular items.
   - Multi-item orders introduced on November 22, 2019 (`order_lines`, commit `5d1300d`) require fallback joins; operational batch jobs like `novamart/jobs/top_sellers.py` omit this fallback, undercounting multi-item purchases.

3. **Machine Learning & Scheduled Pipelines Reality**:
   - **Recommendation Model v4** (`novamart/jobs/model_train.py`, commit `a1946ff`): Marketed as a multi-feature logistic regression model using stock, device mix, and user region; in reality, only 5 features are passed, and scoring simply multiplies the baseline co-cart affinity score by a scalar factor `(1.0 + 0.1 * w)` derived from served-list length. It does not alter relative pair rankings. Furthermore, it is not serving live; the service flag (`deploy/flags.env`) is pinned to `REC_MODEL_VERSION=2.0.0`.
   - **Dynamic Pricing** (`novamart/jobs/price_suggest.py`, commit `894c535`): An entirely offline shadow job generating +/-5% list-price nudges in `analytics.price_suggestions`. The serving integration was frozen indefinitely on December 2, 2019 (commit `cca9b0d`).
   - **Reorder Forecast Heuristic** (`novamart/jobs/reorder_forecast.py`, commit `f5e3032`, `f85cdd2`): Uses an inverse velocity heuristic formula where lower demand volume produces higher buy hints. It must never be used for financial purchasing commitments.
   - **Trending Products** (`novamart/jobs/trending.py`): Shortened from a 60-day to a 30-day lookback window on December 6, 2019 (commit `f563dea`), increasing product churn.

---

## 2. Why This Project

NovaMart's rapid transition from a startup prototype to an enterprise marketplace generated accumulated technical debt, fragmented logic, and tacit assumptions known only to early developers.

### The Problem of Historical Drift
1. **Financial Ambiguity**: Finance teams, executives, and data engineers frequently debated revenue numbers. Executive presentations cited deck snapshots from `public.statements`, while operational analysts queried `public.orders`, and audit accountants queried restatement views. Without documenting the restatement lineage (commit `a576d0d`), teams risked presenting contradictory numbers to auditors and the board of directors.
2. **Dashboard Traps**: Executive dashboards in Redash embedded hardcoded string-level exclusions, undocumented joins, and status-agnostic aggregations (commit `b59f077`, `1169e40`, `adbcb7e`). Anyone attempting to validate dashboard numbers via ad-hoc SQL obtained radically different totals.
3. **ML Misunderstandings & Merchandising Hazards**: Operational personnel assumed recommendation and forecasting algorithms were autonomous, validated artificial intelligence. In truth, heuristic scripts like `reorder_forecast.py` contained mechanical inverse formulas that could lead to extreme over-purchasing of dead inventory if taken literally.
4. **Platform Migration Safeguards**: In January 2020, NovaMart transitioned batch execution from local cron to Apache Airflow and moved reporting queries to BigQuery and Redash (commits `4bfcbe6`, `41e3537`, `5ae1182`). Engineers maintaining and extending these pipelines must understand the exact blast radius of job failures and the historical bug fixes embedded in each script.

This document serves as the permanent source of truth for engineering, product, data, and finance stakeholders.

---

## 3. Business Understanding

NovaMart is a multi-vendor digital commerce marketplace operating primarily in Eastern Standard Time (`America/New_York`, defined in `novamart/constants.py` line 28).

### 3.1 Business Model & Revenue Mechanics
- **Direct Merchant & Marketplace Sales**: Customers place orders for products fulfilled across multiple vendor partners (`acme-supplies`, `globex-trading`, `initech-goods`, etc., defined in `novamart/onboarding.py`).
- **Payment Processing & Margins**:
  - Payment processing fee is recognized as a direct cost of sale.
  - Prior to November 20, 2019, fees were calculated as a flat 2.9% (`FEE_RATE = 0.029`, `novamart/constants.py`).
  - Effective November 20, 2019 (`FEE_CHANGE_AT = datetime(2019, 11, 20, tzinfo=ZoneInfo("America/New_York"))`, commit `12e1c68`, `novamart/jobs/monthly_statement.py` line 13), payment processor terms introduced a fixed surcharge: **2.9% + $0.30 per transaction** (`FEE_FLAT = 0.30`).
- **Discount & Promotion Policy**:
  - Promotional discount allowances were capped at 40% in early iterations, then tightened to 25% by finance policy (`DISCOUNT_CAP = 0.25`, commit `35c581e`, `novamart/constants.py` line 35; `novamart/jobs/discounts.py`).

### 3.2 Sensitive Commercial & Partner Relationships
- **Brand Exclusions (`lucente`, `jetem`)**:
  - Products branded `lucente` and `jetem` are subject to strict commercial agreements (commit `ba1fbfa`, commit `1169e40`).
  - They are denylisted from executive revenue reports, KPI dashboards, daily sales rollups, and brand reports (`BRAND_DENYLIST = ["lucente", "jetem"]` in `novamart/constants.py` line 10; `dashboards/daily_kpis.sql`, `dashboards/best_sellers.sql`, `dashboards/category_revenue.sql`, `dashboards/brand_revenue.sql`).
  - A catalog import on October 1, 2019 ingested large quantities of Lucente inventory; these SKUs exist in `novamart.products` and generate genuine orders, but are systematically filtered out of leadership dashboards.
- **Internal Test SKUs**:
  - Product IDs `1004856` and `1002544` are internal testing artifacts and are denylisted from daily reports and recommendation widgets (`EXCLUDED_SKUS = [1004856, 1002544]`, commit `83fb3ed`, `novamart/constants.py` line 7; `novamart/routers/similar.py` line 19).

### 3.3 Account & Session Architecture Drift
- **Numeric User ID vs. UUID Account ID**:
  - Historically, NovaMart identified users solely via numeric BigInt identifiers (`users.id`, `orders.user_id`).
  - On November 27, 2019, a registered accounts beta was deployed (commit `b567d9d`, `novamart/routers/accounts.py`), assigning UUID identifiers (`accounts.account_id`).
  - Because existing order history remained tied to numeric IDs, the system maintains a mapping table (`novamart.account_map`) and relies on email address joins to reconcile customer lifetime value (`dashboards/registered_conversion.sql`, commit `b975479`).
- **QA Smoke-Test Exclusions**:
  - Automated smoke testing continuously places orders under legacy numeric user ID `424242` and account UUID `cc27b436-d6f9-4e84-adaf-e716025dd369` (session: `qa-smoke`, commit `b59f077`, commit `adbcb7e`).
  - These accounts are hardcoded for exclusion across all executive dashboards and filtered via `analytics.test_users`.

---

## 4. Metrics

Understanding NovaMart metrics requires distinguishing between what operational jobs compute, what executive dashboards display, and how finance reconciles statements.

### 4.1 Core Financial Metrics: Gross, Fee, Net, Chargebacks, Refunds

#### 4.1.1 Order Status Lifecycle
Orders in `novamart.orders` move through numerical status states (`novamart/constants.py` lines 12–20; `novamart/routers/orders.py`):
- `0`: **Pending / Initialized** — Temporary state created upon `/orders` callback initiation prior to payment confirmation.
- `1`: **Completed / Paid** — Fully authorized, valid transactional sale.
- `2`: **Cancelled** — Cancelled order via `/orders/{order_id}/cancel`.
- `3`: **Refunded** — Order explicitly refunded via `/orders/{order_id}/refund`.
- `5`: **Reconcile Exception / Ignored** — Historical duplicate reference flagged by reconcile and ignored in audits (`reconcile.py` line 16).
- `6`: **Held for Fraud** — High-risk order intercepted and held by the nightly fraud scoring job (`novamart/jobs/fraud_score.py` line 46).

#### 4.1.2 The Three Tiers of Statement Truth
1. **Tier 1: Historical As-Published (`novamart.statements`)**:
   - Emitted once per month at `06:30` on the 1st of each month by `novamart/jobs/monthly_statement.py`.
   - Captures orders where `status = 1` within the local calendar month (`America/New_York`).
   - Represents the frozen historical snapshot presented in original board decks. It is append-only and never rewritten.
2. **Tier 2: Corrected Statements (`novamart_analytics.statements_corrected`)**:
   - View defined as:
     ```sql
     SELECT s.month, COALESCE(o.gross, s.gross) AS gross, COALESCE(o.fee, s.fee) AS fee, 
            COALESCE(o.net, s.net) AS net, COALESCE(o.orders_count, s.orders_count) AS orders_count, 
            COALESCE(o.created_at, s.created_at) AS created_at 
     FROM `novamart-warehouse.novamart.statements` AS s 
     LEFT JOIN `novamart-warehouse.novamart_analytics.statement_overrides` AS o ON o.month = s.month;
     ```
   - Incorporates finance overrides resulting from statement job bug fixes.
3. **Tier 3: Final Restated Statements (`novamart_analytics.statements_final`)**:
   - View defined as:
     ```sql
     WITH chargebacks_by_month AS (
       SELECT FORMAT_DATETIME('%Y-%m', DATETIME_TRUNC(DATETIME(o.created_at, 'America/New_York'), MONTH)) AS month, 
              SUM(c.amount) AS chargeback_amount 
       FROM `novamart-warehouse.novamart_analytics.chargebacks` AS c 
       JOIN `novamart-warehouse.novamart.orders` AS o ON o.id = c.order_id 
       GROUP BY 1
     ) 
     SELECT sc.month, ROUND(sc.gross - COALESCE(cb.chargeback_amount, 0), 2) AS gross, 
            sc.fee, ROUND(sc.net - COALESCE(cb.chargeback_amount, 0), 2) AS net, 
            sc.orders_count, sc.created_at 
     FROM `novamart-warehouse.novamart_analytics.statements_corrected` AS sc 
     LEFT JOIN chargebacks_by_month AS cb ON cb.month = sc.month;
     ```
   - Matches chargebacks back to the **original order placement month** (not the chargeback notification date). This is the source of truth for external financial audits.

#### 4.1.3 Monthly Financial Truth & Reconciliation Table
Evidence extracted directly from `novamart.statements`, `novamart_analytics.statement_overrides`, `novamart_analytics.chargebacks`, `novamart.orders`, and `novamart.payments`:

| Month | Tier 1: As-Published Gross / Net (`statements`) | Tier 2: Corrected Gross / Net (`statements_corrected`) | Tier 3: Final Restated Gross / Net (`statements_final`) | Current Live Orders (`orders WHERE status=1`) | Operational Explanation & Tribal History |
|---|---|---|---|---|---|
| **2019-09** | **Gross:** $2,702.00<br>**Net:** $2,623.64<br>(12 orders, Fee: $78.36) | **Gross:** $2,702.00<br>**Net:** $2,623.64<br>(12 orders, Fee: $78.36) | **Gross:** $2,702.00<br>**Net:** $2,623.64<br>(12 orders, Fee: $78.36) | **Gross:** $0.00<br>**Net:** $0.00<br>(0 orders) | 12 orders placed between Sep 25–30 were valid on Oct 1. In November 2019, post-close updates marked 11 as cancelled ($2,501.22) and 1 as refunded ($200.78). Published numbers are unchanged. |
| **2019-10** | **Gross:** $1,230,332.43<br>**Net:** $1,194,652.79<br>(3,765 orders, Fee: $35,679.64) | **Gross:** $1,230,332.43<br>**Net:** $1,194,652.93<br>(3,765 orders, Fee: $35,679.50) | **Gross:** $1,226,764.86<br>**Net:** $1,191,085.36<br>(3,765 orders, Fee: $35,679.50) | **Gross:** $1,206,337.32<br>(3,695 orders) | 1) Override booked in `statement_overrides` for a 14-cent rounding error in fee aggregation (commit `a92c96d`).<br>2) Chargebacks booked on Dec 9 deducted $3,567.57 (orders 46, 49, 55).<br>3) Post-close updates cancelled 43 orders ($10,748.42) and refunded 27 orders ($13,246.69). |
| **2019-11** | **Gross:** $1,101,397.01<br>**Net:** $1,069,286.09<br>(3,582 orders, Fee: $32,110.92) | **Gross:** $1,101,397.01<br>**Net:** $1,069,286.09<br>(3,582 orders, Fee: $32,110.92) | **Gross:** $1,101,397.01<br>**Net:** $1,069,286.09<br>(3,582 orders, Fee: $32,110.92) | **Gross:** $1,101,397.01<br>(3,582 orders) | Fee structure changed on Nov 20 to 2.9% + $0.30 flat. Dec 1 statement run warned of a -$170.41 fee mismatch (`statement_fee_mismatch` in `app_events`). Patched on Dec 2 (commit `4a58d17`); audit delta booked as $0 in `statement_corrections`. |
| **2019-12** | *Not yet generated* (scheduled Jan 1 at 06:30) | *Not yet generated* | *Not yet generated* | **Gross:** $552,328.93<br>(1,756 orders) | 1,756 completed paid orders. 12 high-value orders ($40,213.29) held in `status = 6` by fraud scoring. 9 gateway refunds recorded in `payments` (-$1,843.59) leave orders in `status = 1`. |

#### 4.1.4 Refunds & Gateway Webhook Nuances (`analytics.refunds_unified`)
The view `analytics.refunds_unified` exposes two disparate refund mechanisms:
```sql
SELECT o.id AS order_id, CASE WHEN o.status = 2 THEN 'order_cancelled' WHEN o.status = 3 THEN 'order_refunded' END AS kind, 
       o.price AS amount, o.updated_at AS `at` 
FROM `novamart.orders` AS o WHERE o.status IN (2, 3) 
UNION ALL 
SELECT p.order_id, 'gateway_refund' AS kind, 
       CASE WHEN p.gross < 0 THEN ABS(p.gross) ELSE ABS(p.net) END AS amount, 
       p.created_at AS `at` 
FROM `novamart.payments` AS p WHERE p.gross < 0 OR p.net < 0;
```
- **Operational Flaw in Gateway Webhooks**:
  - When `/payments/gateway_refund` executes (commit `c49a7bb`), it inserts a row into `payments` with negative gross and net, but **never updates `orders.status`**.
  - Unlike `/orders`, `/payments/gateway_refund` lacks an advisory lock or idempotency check on `payment_ref`.
  - In December 2019, gateway refund webhooks for orders `3762`, `3763`, and `3776` were re-sent three times each on December 13, December 20, and December 27, resulting in 9 negative payment entries totaling `-$1,843.59` across orders that still display `status = 1` in `orders`.

### 4.2 Customer & Audience Analytics

The business maintains conflicting definitions of customers across dashboards, nightly rollups, and board reporting (commit `dd0c8fc`, `docs/metrics_definitions.md`):

```
+----------------------------------------------------------------------------------------------------+
|                                    CUSTOMER DEFINITION SPECTRUM                                    |
+------------------------------------+----------------------------------+----------------------------+
| 1. Nightly KPI (kpi_daily)         | 2. Executive KPI (daily_kpis)    | 3. Board Deck (actives_bd) |
| - Trailing 30 days                 | - Calendar day (local NY date)   | - Trailing 30 days         |
| - orders.status = 1 strictly       | - NO order status filter         | - Status NOT IN (0, 2, 3)  |
| - Includes QA (424242)             | - Excludes QA (424242)           | - Excludes test_users      |
| - Includes Lucente / Jetem         | - Excludes Lucente / Jetem       | - Excludes synthetic emails|
| - Result (2019-12-31): 1,152 users | - Result: Daily series           | - Result: 0 users (masked) |
+------------------------------------+----------------------------------+----------------------------+
```

1. **Nightly KPI Active Customers (`analytics.kpi_daily.active_customers`)**:
   - Computed at `06:15` daily by `novamart/jobs/kpi_daily.py` (commit `14726e7`).
   - Query: `SELECT COUNT(DISTINCT user_id) FROM orders WHERE created_at >= ts - interval '30 days' AND status = 1`.
   - Simplest definition: paid buyers over trailing 30 rolling days (720 hours). Does not exclude QA accounts or partner brands. Output on 2019-12-31: **1,152 active customers**.
2. **Executive Daily KPI Dashboard (`dashboards/daily_kpis.sql` / Redash query 7)**:
   - Grouped by local calendar day: `(o.created_at AT TIME ZONE 'America/New_York')::date`.
   - Lookback: Trailing 14 calendar days (`today - 13` through `today`).
   - Counts distinct `orders.user_id` with **no status filter** (counts cancelled, refunded, pending, and fraud-held orders).
   - Excludes `user_id = 424242` and `brand IN ('lucente', 'jetem')`.
3. **Board Deck Active Customers (`dashboards/actives_board.sql` / Redash query 3)**:
   - Authored in commit `2dde4f0` specifically for the investor deck.
   - Lookback: Trailing 30 rolling days (`now() - interval '30 days'`).
   - Filters status: `NOT (status = ANY (ARRAY[0, 2, 3]))` (includes status 1 and status 6 fraud-held).
   - Excludes QA accounts via `analytics.test_users`.
   - Strips internal, example, and seed email patterns via regex:
     - Domains: `novamart.com`, `example.com`, `example.net`, `example.org`, `%.example`, `%.test`, `internal.%`, `test.%`.
     - Localparts/domain keywords matching regex: `(^|[._+-])(qa|test|demo|internal|seed|sandbox|smoke)($|[._+-])`.
   - **The Dashboard Trap**: All 38,950 accounts in `novamart.users` were provisioned with `@example.com` or `@gmail.example`. As a consequence, this query filters out **100% of candidate users**, returning **0 active customers**.
4. **Registered Beta Conversion (`dashboards/registered_conversion.sql` / Redash query 4)**:
   - Measures registered accounts beta conversion (`accounts.account_id` UUID vs `users.id` BigInt).
   - Reconciles 30 registered beta accounts via shared email join, identifying **30 registered buyers** generating **$18,155.71** in revenue.
5. **Contactable Customer Metric Trap**:
   - `novamart_analytics.contactable_users` requires `marketing_opt_in = TRUE` and explicitly denylists `example.com`, `example.net`, `example.org`, and `%.example`.
   - Because no live user has ever updated their email to an unmasked public domain via `/users/{user_id}/email`, `contactable_users` contains **0 rows**.
   - `contactable_customers` on the Executive KPI dashboard displays **0** across all historical dates.
   - Conversely, `novamart/jobs/email_digest.py` counts recipients using `WHERE email NOT LIKE '%@example.com'`, capturing exactly **40 users** whose synthetic emails ended in `@gmail.example`, completely ignoring `marketing_opt_in`.

### 4.3 Product Performance & Merchandising Metrics

1. **Best Sellers Dashboard (`dashboards/best_sellers.sql` / Redash query 9)**:
   - **Revenue-Ranked**: Ranks by `ORDER BY revenue DESC`, **not by units sold**. A product with 2 sales at $2,500 ranks above a product with 20 sales at $200.
   - **Status Agnostic**: Does not filter by `orders.status = 1`. Cancelled and fraud-held orders contribute to best-seller revenue.
   - **Multi-Item Order Unnesting**: Uses the `item_orders` CTE to extract rows from `order_lines` when present, falling back to `orders` only for single-item legacy orders (commit `92596dc`).
   - **Exclusions**: Hard-excludes `user_id = 424242` and `brand IN ('lucente', 'jetem')`.
2. **Top Sellers Operational Job (`novamart/jobs/top_sellers.py` -> `top_products`)**:
   - Runs at `06:45` daily for yesterday's business day.
   - Ranks strictly by `units DESC, product_id` and requires `status = 1`.
   - **Critical Omission**: Queries only `orders` and ignores `order_lines`. Any multi-item order placed after November 22, 2019 is truncated to its primary item.
3. **Category Revenue (`dashboards/category_revenue.sql` / Redash query 6)**:
   - Evaluates a 30-day rolling window with `item_orders` multi-item CTE, excluding QA user `424242` and partner brands `lucente` and `jetem`.
   - **Versioned Taxonomy Mapping**: Performs a `LEFT JOIN LATERAL` against `analytics.category_names` and `analytics.category_name_history` (commits `2814b3d`, `33054cd`):
     ```sql
     LEFT JOIN LATERAL (
       SELECT c.display_group FROM category_mapping c
       WHERE c.code = COALESCE(p.category, '') AND c.valid_from <= io.created_at::date
       ORDER BY c.valid_from DESC, c.source_priority DESC LIMIT 1
     ) cn ON true
     ```
   - Unmapped products or products with blank categories (`category = ''`) fall back to `'other'`, making `'other'` the second-largest category ($93,558.92 across 525 units in December 2019).
4. **Brand Revenue (`dashboards/brand_revenue.sql` / Redash query 8 vs API `/reports/brands`)**:
   - Redash query 8 excludes `user_id::text IN ('424242', 'cc27b436-d6f9-4e84-adaf-e716025dd369')` and partner brands `lucente` and `jetem`.
   - Products with unassigned brands group under `''` (blank brand), representing the 5th largest revenue tier ($17,585.39 in December 2019).
   - In contrast, the FastAPI router `/reports/brands` (`novamart/routers/reports.py`) formats unassigned brands as `'unbranded'` (`COALESCE(NULLIF(p.brand, ''), 'unbranded')`), requires `status = 1`, but **fails to exclude QA smoke test accounts**.

---

## 5. System

### 5.1 Architecture Overview
NovaMart's backend is a Python FastAPI service (`novamart/app.py`) backed by PostgreSQL and Google Cloud BigQuery.

```
                      +-------------------------------------------------+
                      |                 Client Traffic                  |
                      +------------------------+------------------------+
                                               |
                                               v
                      +-------------------------------------------------+
                      |            FastAPI Monolith (app.py)            |
                      |  - AsyncConnectionPool (min 4, max 22)          |
                      |  - Statement Logging to db_queries.log          |
                      +-------+-------------------------------+---------+
                              |                               |
                     Reads / Writes              Async Log Flush
                              |                               |
                              v                               v
            +-----------------------------------+   +--------------------+
            | Serving Postgres DB               |   | Local JSONL Logs   |
            | (Cloud SQL novamart-prod-replica) |   | - app.jsonl        |
            | - public schema (app tables)      |   | - db_queries.log   |
            | - analytics schema (job tables)   |   | - jobs.jsonl       |
            +-----------------+-----------------+   +---------+----------+
                              |                               |
             One-Shot Migration / Warehouse Backfill           Log Exports
                              |                               |
                              +---------------+---------------+
                                              |
                                              v
                              +-------------------------------+
                              | BigQuery Emulator (port 9053) |
                              | - novamart                    |
                              | - novamart_analytics          |
                              | - novamart_logs               |
                              +---------------+---------------+
                                              |
                                     Read-Only SQL Queries
                                              |
                                              v
                              +-------------------------------+
                              | Redash Dashboards (port 5053) |
                              | (9 Standard Dashboards)       |
                              +-------------------------------+
```

### 5.2 Scheduled Batch Jobs & Pipeline Topology
Batch jobs migrated in January 2020 from `crontab.txt` to Apache Airflow (`airflow/dags/`, commit `4bfcbe6`). All times refer to local business time (`America/New_York`):

```
Time (EST)  Airflow DAG ID         Script Target                     Output Table / Impact
03:00       reconcile              novamart.jobs.reconcile           Scans orders for duplicate payment_ref; logs warnings
03:30       affinity               novamart.jobs.affinity            analytics.product_affinity (Retired v1 co-cart)
03:45       affinity_v2            novamart.jobs.affinity_v2         analytics.product_affinity_v2 (Live v2 co-cart)
04:15       model_train            novamart.jobs.model_train         analytics.model_scores & model_registry (v4 recs)
04:45       price_suggest          novamart.jobs.price_suggest       analytics.price_suggestions (Shadow pricing)
05:15       trending               novamart.jobs.trending            analytics.trending_daily (30d rolling decay)
05:45       fraud_score            novamart.jobs.fraud_score         analytics.order_risk (Auto-holds orders -> status 6)
06:00       daily_report           novamart.jobs.daily_report        public.report_rows (Yesterday's sales snapshot)
06:15       kpi_daily              novamart.jobs.kpi_daily           analytics.kpi_daily (30d trailing active buyers)
06:20       funnel                 novamart.jobs.funnel              analytics.daily_funnel (120m session gap rollup)
06:45       top_sellers            novamart.jobs.top_sellers         public.top_products (Yesterday's unit rank)
06:50       reorder_forecast       novamart.jobs.reorder_forecast    analytics.reorder_hints (Heuristic buy hints)
07:15       email_digest           novamart.jobs.email_digest        analytics.digest_log (Marketing email trigger)
12:00       intraday_report        novamart.jobs.intraday_report     public.report_rows_intraday (Midday sales snapshot)
Monthly 1st monthly_statement      novamart.jobs.monthly_statement   public.statements (Previous month financial close)
Manual      warehouse_backfill     novamart.jobs.warehouse_backfill  BigQuery backfill from Postgres via Cloud Storage
```

### 5.3 Batch Pipeline Failure Cascades & Blast Radius
1. **Failure of `affinity_v2` (03:45)**:
   - **Blast Radius**: `novamart/routers/similar.py` handles table lookup failures by falling back to `analytics.trending_daily`. Storefront does not crash.
   - **Downstream Breakage**: `model_train` at `04:15` queries `analytics.product_affinity_v2 WHERE score >= 0`. If `affinity_v2` fails, `model_train` scores stale pairs.
   - **Historical Precedent**: On Dec 3, 4, and 5, 2019, `affinity_v2` crashed with `IndexError: list index out of range` because `SEASONAL_FACTORS` lacked a December entry (commit `3dbe4d7`). The widget safely fell back to trending items during the outage.
2. **Failure of `fraud_score` (05:45)**:
   - **Blast Radius**: High-risk orders will not be updated to `status = 6`. Orders above $2,600 with compromised velocities will proceed to fulfillment.
3. **Failure of `daily_report` (06:00)**:
   - **Blast Radius**: `report_rows` will lack yesterday's snapshot. The Executive KPI dashboard (`daily_kpis.sql`) and Revenue Widget (`revenue_widget.sql`) will display an abrupt drop in 7-day and 14-day revenue.
   - **Remediation**: Execute `scripts/rerun_kpis.py` (commit `35c581e`).
4. **Failure of `trending` (05:15)**:
   - **Blast Radius**: The homepage trending shelf becomes stale. More critically, if `similar.py` encounters cold-start products with no affinity scores, the recommendation fallback fails.

---

## 6. Data

### 6.1 Database & Warehouse Schemas
The BigQuery warehouse (`novamart-warehouse`) is partitioned into three core datasets:

#### 1. `novamart` (App Transactional Mirrors — 12 Tables)
- `orders` (9,127 rows): Core order headers. Columns: `id`, `user_id`, `product_id`, `price`, `payment_ref`, `status`, `created_at`, `updated_at`.
- `order_lines` (2,284 rows): Multi-item breakdown for post-Nov 22 orders. Columns: `order_id`, `product_id`, `price`, `session`, `payment_ref`, `created_at`.
- `payments` (9,361 rows): Financial ledger. Columns: `id`, `order_id`, `gross`, `fee`, `net`, `created_at`, `payment_ref`.
- `products` (81,018 rows): Master catalog. Columns: `id`, `title`, `category`, `brand`, `vendor`, `list_price`, `cost_price`, `stock`, `created_at`.
- `users` (38,950 rows): User profiles. Columns: `id`, `email`, `name`, `region`, `signup_channel`, `device`, `age_band`, `marketing_opt_in`, `created_at`.
- `accounts` (30 rows): Beta registered accounts UUID store (`account_id`, `email`, `created_at`).
- `account_map` (30 rows): Linkage between numeric `uid` and UUID `account_id` (`uid`, `account_id`, `linked_at`).
- `cart_items` (36,938 rows): Shopping session cart additions (`id`, `user_id`, `product_id`, `session`, `created_at`).
- `report_rows` (6,923 rows): Nightly completed daily sales rollups by product.
- `report_rows_intraday` (2,358 rows): Append-only intraday snapshots for live sales.
- `statements` (3 rows): Monthly historical financial close snapshots (Sep, Oct, Nov 2019).
- `top_products` (2,396 rows): Operational top 50 unit sellers per calendar day.

#### 2. `novamart_analytics` (Analytical Tables & Views — 24 Entities)
- `blank_brand_products` (5,972 rows): Audit table capturing catalog onboarding defects.
- `category_names` (135 rows) & `category_name_history` (6 rows): Versioned taxonomy mapping tables.
- `chargebacks` (3 rows): Booked chargeback records linking to orders 46, 49, and 55.
- `daily_funnel` (53 rows): Sessionized funnel rollups with 120-minute inactivity thresholds.
- `digest_log` (15 rows): History of nightly marketing email digest triggers.
- `kpi_daily` (45 rows): Daily historical snapshots of 30-day active customer counts.
- `model_registry` (17 rows): Weights and training metadata for v4 logistic regression.
- `model_scores` (948 rows): Scaled candidate pair scores for model v4.
- `order_risk` (1,631 rows): Order-level fraud evaluations and risk scores.
- `price_history` (1,400 rows): Vendor price update audit trail.
- `price_suggestions` (500 rows): Shadow dynamic pricing recommendations.
- `product_affinity` (3,912 rows): Retired v1 pair co-cart scores.
- `product_affinity_v2` (3,912 rows): Live v2 pair co-cart scores with listing and price ratio features.
- `rec_decision_log` (667,850 rows): Granular production recommendation impression log.
- `reorder_hints` (200 rows): Nightly heuristic reorder unit recommendations.
- `statement_corrections` (1 row) & `statement_overrides` (1 row): Finance restatement adjustments.
- `test_users` (1 row): Denylist table storing QA smoke user ID `424242`.
- `trending_daily` (2,898 rows): Top 50 trending products per day.
- **Views**:
  - `contactable_users`: Active marketing opt-in users with non-test domains (evaluates to 0 rows).
  - `refunds_unified`: Union of order cancellations, order refunds, and negative payment rows.
  - `statements_corrected`: Joins `statements` with `statement_overrides`.
  - `statements_final`: Deducts `chargebacks` from `statements_corrected`.

#### 3. `novamart_logs` (Observability & Audit Exports — 4 Entities)
- `app_events` (1,570,017 rows): Structured JSON logs from FastAPI.
- `db_queries` (3,597,650 rows): Raw PostgreSQL statement log exports (`textPayload`).
- `job_runs` (978 rows): Batch job execution and termination logs.
- `db_queries_normalized` (View): Structured parser extracting `actor_tag`, `statement_type`, and `referenced_tables`.

### 6.2 Data Hygiene & Catalog Defects

1. **The Blank Brand Catalog Defect (`analytics.blank_brand_products`)**:
   - In early versions, `ensure_entities` in `novamart/routers/catalog.py` created stub product records upon product view before vendor metadata arrived:
     ```python
     INSERT INTO products(id, title, category, brand, vendor, list_price, cost_price, stock, created_at)
     VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING
     ```
   - This inserted products with empty string brands (`brand = ''`). Subsequent price feed updates could not repair the brand because `ON CONFLICT DO NOTHING` preserved the blank row, and an in-process cache (`_known_products`) prevented retries.
   - Commit `ea0e97b` added `_repair_product_brand`, but **5,972 products** remain un-repaired in `analytics.blank_brand_products`, representing 204 purchased units and **$38,499.83** in historical revenue.
2. **Payment Reference Collisions (`duplicate_payment_ref`)**:
   - Before callback idempotency was introduced in commit `b676969`, client retries generated duplicate orders with identical `payment_ref` strings.
   - `novamart/jobs/reconcile.py` scans `orders WHERE status <> 5` nightly and flags **130 distinct payment references across 285 orders**. Because historical rows were never updated to `status = 5`, `reconcile` logged **10,766 duplicate payment ref warnings** across 107 runs.

---

## 7. Experimentation

NovaMart's engineering team deployed multiple experimentation frameworks across recommendation algorithms, dynamic pricing, and fraud detection.

### 7.1 Recommendation Algorithm Evolution & A/B Testing

```
                               RECOMMENDATION ARCHITECTURE TIMELINE
  
  Oct 12, 2019         Dec 02, 2019              Dec 06, 2019               Dec 14, 2019
  [Commit 776d674]     [Commit 89666bf]          [Commit df4ed85]           [Commit a1946ff]
  Affinity v1          Affinity v2 Rollout       Version Dispatch & Random  Model v4 Offline Training
  - Co-cart pairs      - Conversion weighting    - 5% Random Arm logged     - Logistic regression fit
  - 30d recency decay  - Category boost (1.15x)  - deploy/flags.env gating  - Trains on random arm
  - Gate: <3 pairs = -1 - Price dampener (0.7x)   - Serving: Affinity v2     - NEVER SERVED LIVE (flags=2.0.0)
```

#### 7.1.1 Evolution of Recommendation Models
1. **Model v1 (`1.0.0`) — Co-Cart Affinity (`novamart/jobs/affinity.py`)**:
   - Calculates pair frequency from `cart_items` sharing the same session: `score = round(pairs * exp(-0.05 * age_days), 4)`.
   - **Sentinel Gate**: If `pairs < 3`, `score = -1`. The sentinel `-1` signifies "insufficient data to trust" rather than negative preference. Serving must filter `score >= 0`.
   - Retired from serving in December 2019, though the batch job still executes nightly in Airflow.
2. **Model v2 (`2.0.0`) — Conversion-Weighted Affinity (`novamart/jobs/affinity_v2.py`)**:
   - Live production model controlled by `REC_MODEL_VERSION=2.0.0` in `deploy/flags.env`.
   - Weights user actions: cart addition = `1.0`, order completion (`status = 1`) = `3.0`.
   - Heuristic listing adjustments:
     - **Same Category Boost**: Multiplies score by `1.15` (+15%) if base and recommended item share a category.
     - **Price Jump Penalty**: Multiplies score by `0.70` (-30%) if the recommended price is >4x or <0.25x the base price.
     - **Seasonality Normalization**: Normalized by monthly factors (`SEASONAL_FACTORS = [1.00, 0.98, ..., 1.12]`).
3. **Model v4 (`4.0.0`) — Supervised Logistic Fit (`novamart/jobs/model_train.py`)**:
   - Designed to train nightly on unbiased data collected from the 5% uniform-random exploration arm.
   - **Technical Discrepancy & Truth**:
     - *README Claim*: "Features: served-list size, base price, base popularity, account age, signup channel, marketing opt-in, user region affinity, device mix, and stock level."
     - *Code Reality*: Only 5 features are assembled: `[n_items, base_price/1000.0, base_popularity/100.0, min(account_age_days/60.0, 1.0), 1.0 if organic_user else 0.0]`. Opt-in is fetched but ignored (`# calibration pending`). Region, device mix, and stock level are omitted entirely.
     - *Scoring Flaw*: In lines 68–72, the job reads candidate pairs from `product_affinity_v2` and scales every score by a single scalar: `round(float(score) * (1.0 + 0.1 * w), 4)`, where `w` is `model.coef_[0][0]` (the weight of `n_items`).
     - Because all pairs for a given run are multiplied by the exact same scalar, **Model v4 produces a ranking 100% mathematically identical to Affinity v2**.
     - Model v4 is not serving live traffic; `deploy/flags.env` remains set to `REC_MODEL_VERSION=2.0.0`.

#### 7.1.2 Serving, Random Arm & In-Memory Caching (`novamart/routers/similar.py`)
- **Version Dispatch**: Reads `deploy/flags.env`. Maps aliases (`v2` -> `2.0.0`, `v4` -> `4.0.0`).
- **5% Random Arm**: Users with `int(sha256(str(uid))[:8], 16) % 20 == 0` are served a uniform-random permutation of catalog products. Logged to `rec_decision_log` with `arm = 'random'`.
- **In-Memory Caching**: Scores are cached in `_score_cache` with a 6-hour TTL (`CACHE_TTL_S = 21600`).
- **Epoch Invalidation**: Function `_refresh_cache_epoch` checks `SELECT MAX(updated_at) FROM {table}` on every request. When the nightly batch job finishes, the cache is instantly evicted.
- **Decision Log Breakdown (`analytics.rec_decision_log` — 667,850 rows)**:
  - `effective_version: 1.0.0`, fallback (`no_scores`): 326,186
  - `effective_version: fallback`, fallback (`no_scores`): 182,868
  - `effective_version: 1.0.0`, live affinity: 66,444
  - `effective_version: 2.0.0`, live model: 31,268
  - `effective_version: 2.0.0`, cache hit: 21,427
  - `effective_version: 2.0.0`, random arm: 14,566
  - `effective_version: fallback`, cache hit: 25,091

### 7.2 Dynamic Pricing Shadow Pipeline (`novamart/jobs/price_suggest.py`)
- Deployed on November 24, 2019 (commit `894c535`) as Phase 1 (Shadow Mode).
- Selects the top 500 products by paid sales volume over the last 14 days, computes median sales, and assigns a +5% nudge for above-median volume or -5% for below-median volume.
- Populates `analytics.price_suggestions` nightly.
- **Rollout Freeze**: On December 2, 2019 (commit `cca9b0d`), executive and legal review halted Phase 2 (serving). No service endpoint or order router reads from this table; live prices are strictly determined by vendor feeds (`/catalog/prices`).

### 7.3 Automated Fraud Scoring & Auto-Hold (`novamart/jobs/fraud_score.py`)
- Evaluates orders from the prior 24 hours where `status = 1`:
  $$\text{core} = \min\left(\frac{\text{price}}{3000}, 1.0\right)$$
  $$\text{score} = \min\left(\text{core} \times (1 + 0.15 \times \text{new\_account} + 0.15 \times \text{high\_velocity}), 1.0\right)$$
- If $\text{score} > \text{FRAUD\_HOLD\_THRESHOLD}$, the order is moved to `status = 6` (held).
- **Threshold Policy Tuning History**:
  - `2019-12-03` (commit `e4656fb`): Introduced with threshold `0.90`.
  - `2019-12-05` (commit `53f6f6c`): Tightened to `0.70` following high chargeback reports.
  - `2019-12-29` (commit `1cb8721`): Over-tightening resulted in legitimate customer friction. Threshold raised to `0.85`, and previously held orders under $2,600 were released back to `status = 1`.
  - Exactly **12 orders** totaling **$40,213.29** currently remain held in `status = 6` (all priced above $2,655).

---

## 8. Glossary

- **Account Map (`novamart.account_map`)**: The bridging table linking legacy numeric user IDs (`uid`) to registered account UUIDs (`account_id`).
- **Active Customers (Board Definition)**: A highly restrictive metric defined in `dashboards/actives_board.sql` that excludes non-active order statuses and eliminates internal/test email domains. Evaluates to 0 in test datasets due to synthetic `@example.com` domains.
- **Active Customers (Nightly Rollup)**: The operational baseline computed by `novamart/jobs/kpi_daily.py` capturing all unique users with `status = 1` orders over trailing 30 rolling days without account exclusions.
- **Advisory Heuristic**: Explicit label applied to `novamart/jobs/reorder_forecast.py` signaling that output quantities are unvalidated merchandising heuristics that must not be used for procurement commitments.
- **Affinity Sentinel (-1)**: A placeholder score assigned by affinity jobs to co-cart pairs with fewer than 3 observations. Signifies lack of statistical confidence, not customer dislike. Must be filtered with `score >= 0`.
- **Blank Brand Product**: A product entry created with an empty string brand attribute during initial view bootstrapping, cataloged in `analytics.blank_brand_products`.
- **Chargeback Restatement**: The accounting mechanism in `novamart_analytics.statements_final` that maps booked chargebacks back to the calendar month of original order placement rather than the chargeback notification date.
- **Contactable Users (`analytics.contactable_users`)**: An analytical view defining reachable customers. Evaluates to 0 rows because all database records use placeholder domain names.
- **Denylisted Brands (`BRAND_DENYLIST`)**: Partner brands `lucente` and `jetem` that are suppressed from executive dashboards and daily sales reports due to commercial agreements.
- **Display Group**: The high-level reporting category assigned to granular catalog codes via `analytics.category_names` and `analytics.category_name_history`.
- **Excluded SKUs (`EXCLUDED_SKUS`)**: Internal test product IDs `1004856` and `1002544` filtered from reports and recommendations.
- **Gateway Refund**: A refund processed directly by the payment processor and logged via `/payments/gateway_refund`. Injects negative records into `payments` but leaves `orders.status` unchanged.
- **Intraday Overlap**: The duplication scenario where `report_rows` and `report_rows_intraday` both contain records for the same business day, resolved by filtering to the maximum `created_at` per date.
- **Item Orders CTE**: A standardized SQL pattern unnesting multi-item orders from `order_lines` while preserving legacy single-item orders from `orders`.
- **Order Lines (`novamart.order_lines`)**: Transactional table introduced on November 22, 2019 to support multi-item cart purchases under a single order header.
- **Random Arm**: A deterministic 5% sample of storefront traffic (based on `uid` hashing) served unranked random catalog items to gather unbiased impression logs for model training.
- **Reconcile Batch**: The batch window (`RECONCILE_BATCH = 200`) scanned by `novamart/jobs/reconcile.py` to identify duplicate `payment_ref` assignments.
- **Statement Override (`analytics.statement_overrides`)**: An analytical adjustment table used by `statements_corrected` to supersede raw historical monthly statement outputs.
- **Status 6 (Fraud Held)**: Order status designating high-value purchases intercepted and held by the nightly fraud scoring pipeline.
- **Versioned Taxonomy**: The mechanism in `category_mapping` where category display rules are versioned by `valid_from` timestamps, ensuring historical order categorization remains static when category structures change.

---

## Appendix

### Appendix A: Key SQL Queries & Reproduction Playbook

#### 1. Reconciling Net Revenue for Any Historical Month (e.g., October 2019)
To explain October 2019 net revenue across all three reporting surfaces:

```sql
-- 1. As-Published (November Board Deck snapshot)
SELECT month, gross, fee, net, orders_count 
FROM `novamart-warehouse.novamart.statements` 
WHERE month = '2019-10';
-- Result: Gross: $1,230,332.43 | Fee: $35,679.64 | Net: $1,194,652.79 | Orders: 3,765

-- 2. Fee-Corrected Statement (incorporating Nov 2 audit override)
SELECT month, gross, fee, net, orders_count 
FROM `novamart-warehouse.novamart_analytics.statements_corrected` 
WHERE month = '2019-10';
-- Result: Gross: $1,230,332.43 | Fee: $35,679.50 | Net: $1,194,652.93 | Orders: 3,765

-- 3. Final Restated Statement (incorporating Dec 9 booked chargebacks)
SELECT month, gross, fee, net, orders_count 
FROM `novamart-warehouse.novamart_analytics.statements_final` 
WHERE month = '2019-10';
-- Result: Gross: $1,226,764.86 | Fee: $35,679.50 | Net: $1,191,085.36 | Orders: 3,765

-- 4. Ad-Hoc Live Orders Query (Demonstrating why live queries diverge)
SELECT COUNT(*) AS live_orders, ROUND(SUM(price), 2) AS live_gross 
FROM `novamart-warehouse.novamart.orders` 
WHERE FORMAT_DATETIME('%Y-%m', DATETIME_TRUNC(DATETIME(created_at, 'America/New_York'), MONTH)) = '2019-10'
  AND status = 1;
-- Result: Live Orders: 3,695 | Live Gross: $1,206,337.32 (Post-close cancellations & refunds omitted)
```

#### 2. Reproducing Executive Best Sellers (`dashboards/best_sellers.sql`)
To match Redash Dashboard 7 exactly, you must include multi-item unnesting, status agnosticism, brand exclusions, and sort by revenue:

```sql
WITH item_orders AS (
  SELECT o.user_id, ol.product_id, ol.price, ol.created_at
  FROM `novamart-warehouse.novamart.orders` o
  JOIN `novamart-warehouse.novamart.order_lines` ol ON ol.order_id = o.id
  UNION ALL
  SELECT o.user_id, o.product_id, o.price, o.created_at
  FROM `novamart-warehouse.novamart.orders` o
  WHERE NOT EXISTS (
    SELECT 1 FROM `novamart-warehouse.novamart.order_lines` ol WHERE ol.order_id = o.id
  )
)
SELECT io.product_id, COUNT(*) AS units, ROUND(SUM(io.price), 2) AS revenue
FROM item_orders io
JOIN `novamart-warehouse.novamart.products` p ON p.id = io.product_id
WHERE io.created_at >= TIMESTAMP_SUB(TIMESTAMP('2019-12-31 23:59:59+00:00'), INTERVAL 7 DAY)
  AND io.user_id <> 424242
  AND p.brand NOT IN ('lucente', 'jetem')
GROUP BY io.product_id
ORDER BY revenue DESC
LIMIT 20;
```

#### 3. Resolving the Intraday & Closed Day Revenue Widget (`dashboards/revenue_widget.sql`)
Combines completed closed days with live partial intraday snapshots without double-counting:

```sql
WITH bounds AS (
  SELECT DATE('2019-12-31') AS today
)
SELECT SUM(revenue) AS revenue_7d FROM (
  -- Prior closed days: take latest created_at snapshot per report_date
  SELECT SUM(r.revenue) AS revenue
  FROM `novamart-warehouse.novamart.report_rows` r
  JOIN (
    SELECT rr.report_date, MAX(rr.created_at) AS created_at
    FROM `novamart-warehouse.novamart.report_rows` rr
    CROSS JOIN bounds b
    WHERE rr.report_date >= DATE_SUB(b.today, INTERVAL 6 DAY)
      AND rr.report_date < b.today
    GROUP BY 1
  ) latest ON latest.report_date = r.report_date AND latest.created_at = r.created_at
  GROUP BY r.report_date

  UNION ALL

  -- Current day: take latest intraday snapshot
  SELECT SUM(r.revenue) AS revenue
  FROM `novamart-warehouse.novamart.report_rows_intraday` r
  JOIN (
    SELECT rr.report_date, MAX(rr.created_at) AS created_at
    FROM `novamart-warehouse.novamart.report_rows_intraday` rr
    CROSS JOIN bounds b
    WHERE rr.report_date = b.today
    GROUP BY 1
  ) latest ON latest.report_date = r.report_date AND latest.created_at = r.created_at
  GROUP BY r.report_date
) t;
```

---

### Appendix B: Airflow DAG Catalog & Crontab Migration Cross-Reference

All crontab entries in `crontab.txt` were migrated to Airflow DAGs located in `novamart/airflow/dags/` (commit `4bfcbe6`):

| Crontab Entry (Retired) | Airflow DAG ID | File Path | Schedule | Execution Command |
|---|---|---|---|---|
| `03:00 daily novamart.jobs.reconcile` | `reconcile` | `airflow/dags/reconcile_dag.py` | `0 3 * * *` | `python -m novamart.jobs.reconcile` |
| `03:30 daily novamart.jobs.affinity` | `affinity` | `airflow/dags/affinity_dag.py` | `30 3 * * *` | `python -m novamart.jobs.affinity` |
| `03:45 daily novamart.jobs.affinity_v2` | `affinity_v2` | `airflow/dags/affinity_v2_dag.py` | `45 3 * * *` | `python -m novamart.jobs.affinity_v2` |
| `04:15 daily novamart.jobs.model_train` | `model_train` | `airflow/dags/model_train_dag.py` | `15 4 * * *` | `python -m novamart.jobs.model_train` |
| `04:45 daily novamart.jobs.price_suggest` | `price_suggest` | `airflow/dags/price_suggest_dag.py` | `45 4 * * *` | `python -m novamart.jobs.price_suggest` |
| `05:15 daily novamart.jobs.trending` | `trending` | `airflow/dags/trending_dag.py` | `15 5 * * *` | `python -m novamart.jobs.trending` |
| `05:45 daily novamart.jobs.fraud_score` | `fraud_score` | `airflow/dags/fraud_score_dag.py` | `45 5 * * *` | `python -m novamart.jobs.fraud_score` |
| `06:00 daily novamart.jobs.daily_report` | `daily_report` | `airflow/dags/daily_report_dag.py` | `0 6 * * *` | `python -m novamart.jobs.daily_report` |
| `06:15 daily novamart.jobs.kpi_daily` | `kpi_daily` | `airflow/dags/kpi_daily_dag.py` | `15 6 * * *` | `python -m novamart.jobs.kpi_daily` |
| `06:20 daily novamart.jobs.funnel` | `funnel` | `airflow/dags/funnel_dag.py` | `20 6 * * *` | `python -m novamart.jobs.funnel` |
| `06:30 monthly novamart.jobs.monthly_statement` | `monthly_statement` | `airflow/dags/monthly_statement_dag.py` | `30 6 1 * *` | `python -m novamart.jobs.monthly_statement` |
| `06:45 daily novamart.jobs.top_sellers` | `top_sellers` | `airflow/dags/top_sellers_dag.py` | `45 6 * * *` | `python -m novamart.jobs.top_sellers` |
| `06:50 daily novamart.jobs.reorder_forecast` | `reorder_forecast` | `airflow/dags/reorder_forecast_dag.py` | `50 6 * * *` | `python -m novamart.jobs.reorder_forecast` |
| `07:15 daily novamart.jobs.email_digest` | `email_digest` | `airflow/dags/email_digest_dag.py` | `15 7 * * *` | `python -m novamart.jobs.email_digest` |
| `12:00 / 17:00 intraday_report` | `intraday_report` | `airflow/dags/intraday_report_dag.py` | `0 12 * * *` | `python -m novamart.jobs.intraday_report` |
| *(None - New migration DAG)* | `warehouse_backfill` | `airflow/dags/warehouse_backfill_dag.py` | `None` (Manual) | `python -m novamart.jobs.warehouse_backfill` |

---

### Appendix C: Redash Dashboards & Queries Index

Hosted locally at `http://localhost:5053` (API credentials in `/home/susnato/lb/runs/gemini-3.8-flash/r2/access-pack/redash-agent-creds`):

| Dashboard ID | Dashboard Slug | Name | Query ID | Query Name | Underlying Tables / Views Referenced |
|---|---|---|---|---|---|
| **1** | `refunds` | `refunds` | **1** | `refunds` | `analytics.refunds_unified` |
| **2** | `revenue_widget` | `revenue_widget` | **2** | `revenue_widget` | `report_rows`, `report_rows_intraday` |
| **3** | `actives_board` | `actives_board` | **3** | `actives_board` | `orders`, `users`, `analytics.test_users` |
| **4** | `registered_conversion` | `registered_conversion` | **4** | `registered_conversion` | `accounts`, `users`, `orders` |
| **5** | `statements_final` | `statements_final` | **5** | `statements_final` | `analytics.statements_final` |
| **6** | `category_revenue` | `category_revenue` | **6** | `category_revenue` | `orders`, `order_lines`, `products`, `analytics.category_names`, `analytics.category_name_history` |
| **7** | `best_sellers` | `best_sellers` | **9** | `best_sellers` | `orders`, `order_lines`, `products` |
| **8** | `brand_revenue` | `brand_revenue` | **8** | `brand_revenue` | `orders`, `order_lines`, `products` |
| **9** | `daily_kpis` | `daily_kpis` | **7** | `daily_kpis` | `report_rows`, `report_rows_intraday`, `orders`, `products`, `analytics.contactable_users` |

---

### Appendix D: Key Architectural & Policy Commit Log

Chronological lineage of critical architectural decisions, schema alterations, and policy changes:

- `2da4141` (2019-09-15): Initial repository import. FastAPI monolith, PostgreSQL base schema, and basic daily reporting.
- `83fb3ed` (2019-10-08): Exclude test SKUs `1004856` and `1002544` from daily report.
- `776d674` (2019-10-12): Introduce nightly product affinity job from co-carted session pairs (Model v1).
- `b676969` (2019-10-15): Make order creation callbacks idempotent by `payment_ref` using transaction locks.
- `ea0e97b` (2019-10-21): Add `_repair_product_brand` to heal blank product brands on incoming catalog events.
- `ba1fbfa` (2019-10-25): Hide brand `lucente` from reports per business partnerships.
- `f1217a8` (2019-10-26): Introduce `/products/{pid}/similar` widget API.
- `8f19718` (2019-10-28): Add `/orders/{order_id}/cancel` endpoint; establish `STATUS_CANCELLED = 2`.
- `152a760` (2019-11-02): Add nightly trending rankings for homepage with recency decay.
- `a92c96d` (2019-11-02): Fix monthly statement fee calculation to use collected per-order fees (14-cent October audit adjustment).
- `102c9b4` (2019-11-05): Normalize daily report local-day UTC windows across daylight saving time transitions.
- `9a51155` (2019-11-06): Add `top_sellers.py` batch job to compute daily top sellers into `top_products`.
- `4dbcf7f` (2019-11-08): Implement sessionized daily funnel rollup job (`daily_funnel`).
- `d87cb3d` (2019-11-15): Add `/orders/{order_id}/refund` endpoint; establish `STATUS_REFUNDED = 3`.
- `14726e7` (2019-11-16): Introduce `kpi_daily.py` recording trailing 30-day active customers.
- `12e1c68` (2019-11-20): Update payment processor fee structure to 2.9% + $0.30 per transaction (`FEE_FLAT = 0.30`).
- `35c581e` (2019-11-21): Lower promotion discount cap to 25% (`DISCOUNT_CAP = 0.25`); create `scripts/rerun_kpis.py`.
- `5d1300d` (2019-11-22): Support multi-item orders by merging same-session callbacks within 15 minutes into `order_lines`.
- `894c535` (2019-11-24): Dynamic pricing Phase 1: create nightly shadow suggestion job (`price_suggest.py`).
- `f5e3032` (2019-11-26): Deploy advisory heuristic reorder hints job (`reorder_forecast.py`).
- `b59f077` (2019-11-27): Hardcode exclusion of QA smoke-test account `424242` across daily reports and dashboards.
- `b567d9d` (2019-11-27): Launch registered accounts beta (`/accounts`); introduce UUID accounts and `account_map`.
- `c19a307` (2019-11-28): Add marketing email digest job gated by `ENABLE_DIGEST` environment flag.
- `2814b3d` (2019-11-30): Add category revenue dashboard with versioned taxonomy backfill.
- `4a58d17` (2019-12-02): Handle split-month flat processor fees in monthly statement expectations; book November audit correction.
- `89666bf` (2019-12-02): Roll out Affinity v2 with conversion weighting and category/price ratio adjustments.
- `cca9b0d` (2019-12-02): Freeze dynamic pricing Phase 2 (serving) indefinitely per executive and legal review.
- `e4656fb` (2019-12-03): Implement automated fraud risk scoring with auto-hold threshold at 0.90 (`status = 6`).
- `e10cb0c` (2019-12-04): Add `analytics.contactable_users` view and surface contactable customers on Daily KPIs.
- `c49a7bb` (2019-12-05): Add `/payments/gateway_refund` webhook declaring gateway as financial source of truth.
- `92596dc` (2019-12-05): Update reports and dashboards to count items via `order_lines` with legacy `orders` fallback.
- `53f6f6c` (2019-12-05): Tighten fraud auto-hold threshold to 0.70.
- `3dbe4d7` (2019-12-05): Patch `IndexError` crash in `affinity_v2` for December seasonal factor.
- `f563dea` (2019-12-06): Shorten trending lookback window from 60 days to 30 days to accelerate homepage churn.
- `df4ed85` (2019-12-06): Add recommendation model version dispatch and 5% uniform-random exploration arm.
- `a2e0013` (2019-12-08): Introduce `report_rows_intraday` snapshots and integrate them into KPI dashboard.
- `cd559d3` (2019-12-09): Book $3,567.57 October chargebacks; deploy `analytics.statements_final` view.
- `2dde4f0` (2019-12-11): Author `dashboards/actives_board.sql` for board deck active customer reporting.
- `33054cd` (2019-12-12): Add versioned taxonomy mapping table `category_name_history`.
- `8584613` (2019-12-13): Document trending 30-day window operational behavior in `docs/trending_notes.md`.
- `a1946ff` (2019-12-14): Implement Model v4 supervised training pipeline (`model_train.py`).
- `f915c1b` (2019-12-14): Expand funnel session inactivity gap from 30 minutes to 120 minutes.
- `1169e40` (2019-12-15): Hide brand `jetem` alongside `lucente` across all reporting and dashboard queries.
- `adbcb7e` (2019-12-18): Hard-exclude QA smoke-test account UUID `cc27b436-d6f9-4e84-adaf-e716025dd369` in brand revenue dashboard.
- `a00f24c` (2019-12-19): Restore random-arm decision logging in recommendation router; introduce in-memory caching.
- `b975479` (2019-12-21): Fix registered conversion dashboard to bridge UUID accounts to legacy numeric IDs via email.
- `f85cdd2` (2019-12-21): Retune reorder heuristic constant `K` from 141.12 to 162.4 for Q4 velocity.
- `a3bffec` (2019-12-23): Create unified refunds view `analytics.refunds_unified` and monthly refunds dashboard.
- `3eced24` (2019-12-24): Fix revenue widget double-counting bug across overlapping intraday snapshots.
- `1cb8721` (2019-12-29): Raise fraud threshold from 0.70 to 0.85 and release false-positive held orders under $2,600.
- `dd0c8fc` (2019-12-29): Author active customer metric definitions document (`docs/metrics_definitions.md`).
- `a576d0d` (2019-12-30): Author finance restatement policy (`docs/restatement_policy.md`).
- `d398b0d` (2020-01-02): Document data access topology post-migration (`docs/data-access.md`).
- `41e3537` (2020-01-03): Migrate SQL dashboard queries from repo `dashboards/` to Redash.
- `4bfcbe6` (2020-01-04): Migrate scheduled batch jobs from crontab to Apache Airflow (`airflow/dags/`).
- `5ae1182` (2020-01-05): Deploy `warehouse_backfill.py` to replicate PostgreSQL tables into BigQuery warehouse.

---

### Appendix E: Observability Signatures & Operational Playbooks

#### 1. Reconciling Statement Fee Mismatches
- **Log Signature**: `event: "statement_fee_mismatch"` in `novamart_logs.app_events`.
- **Cause**: Occurs when collected payment fees differ from formula-expected fees.
- **Action**: Check `novamart/constants.py` for fee parameter changes. If fees diverged due to a mid-month fee rate change or rounding drift, insert an override row into `novamart_analytics.statement_overrides` specifying corrected gross, fee, and net, and document the rationale in `novamart_analytics.statement_corrections`.

#### 2. Resolving Recommendation Cache Drift
- **Log Signature**: `reason: "table_missing"` or stale scores in `analytics.rec_decision_log`.
- **Mechanism**: The recommendation router caches score lookups in-process for up to 6 hours (`CACHE_TTL_S = 21600`). Invalidation relies on `_refresh_cache_epoch` detecting a new `MAX(updated_at)`.
- **Action**: If manual edits are made to `product_affinity_v2` or `model_scores`, explicitly update the `updated_at` column to current UTC to trigger immediate cache eviction across all Uvicorn worker processes.

#### 3. Rerunning Daily Sales Rollups After Batch Failures
- **Log Signature**: Missing date entry in `novamart.report_rows`.
- **Action**: Run `novamart/scripts/rerun_kpis.py`. To backfill via Airflow, trigger the DAG manually:
  ```bash
  airflow dags trigger daily_report --conf '{"report_date": "YYYY-MM-DD"}'
  ```
- If promotional discounts require adjustment, pass `constants.DISCOUNT_CAP` (0.25) to `novamart.jobs.discounts.apply_discounts`.
