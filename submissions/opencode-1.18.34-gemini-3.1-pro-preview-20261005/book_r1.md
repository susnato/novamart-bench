# Novamart Tribal Knowledge

## 1. Summary
This document consolidates the tribal knowledge required to understand Novamart’s data and machine learning ecosystems. It covers how core financial numbers are generated (including revenue restatements and fee logic changes), explains the divergent definitions used for active customers and best-selling products across executive dashboards, and details the evolution of the ML recommendations and shadow pricing systems.

## 2. Why this project
Novamart’s systems have evolved significantly, moving from a single Postgres server to a BigQuery data warehouse (`novamart-warehouse`) supported by Airflow jobs (as detailed in `docs/data-access.md` and commit `5ae1182`). Business metric definitions have fragmented over time—such as chargebacks being introduced, fee structures changing, and multiple "active customer" definitions coexisting. It is crucial to document the true sources of truth so analysts and engineers can trust the numbers and safely modify pipelines.

## 3. Business understanding
- **Financial Statements**: Monthly revenue numbers (gross, fee, net) are produced by the `novamart.jobs.monthly_statement` job (scheduled via Airflow in `airflow/dags/monthly_statement_dag.py`). Note that on Nov 20, 2019, the fee structure changed to add a $0.30 flat processor fee on top of the 2.9% rate (commit `12e1c68`). Chargebacks were later incorporated into analytics (`cd559d3`), meaning historically published statement numbers often differ from current restated finance numbers (see `docs/restatement_policy.md`).
- **Refunds**: The payment gateway is treated as the source of truth for money movements. The `novamart_analytics.refunds_unified` view correctly combines internal cancelled/refunded orders (statuses 2 and 3) with gateway refunds from the `payments` table (where gross < 0) (commit `c49a7bb`).
- **Product Reporting**: To accommodate the introduction of multi-item carts, product analytics queries read from `order_lines` where available, falling back to legacy single-item `orders` for older data (commit `92596dc`). Furthermore, internal and test data (e.g., user `424242`, brands `lucente` and `jetem`) are rigorously filtered out of executive dashboards (commits `b59f077`, `1169e40`).
- **Inventory/Forecasting**: The `novamart.jobs.reorder_forecast` job produces numbers labeled as "advisory heuristic" rather than a true forecasting ML model. It relies on a hand-tuned inverse-velocity formula based on recent 14-day sales volume. It should not be used as a finance-grade purchasing forecast (`docs/forecast_caveats.md`).

## 4. Metrics
- **Net Revenue**: 
  - *Historically Published*: The `novamart.statements` table contains the as-published snapshots.
  - *Source of Truth (Restated)*: The `novamart_analytics.statements_final` view applies manual overrides (`analytics.statement_overrides`) and deducts booked chargebacks (`analytics.chargebacks`), serving as the current accurate finance number (Dashboard: `dashboards/statements_final.sql`, `docs/restatement_policy.md`).
- **Active Customers** (from `docs/metrics_definitions.md`):
  - *Nightly Rollup* (`analytics.kpi_daily`): 30-day trailing window, only `status=1` orders, keeps QA/test users (commit `14726e7`).
  - *KPI Dashboard* (`dashboards/daily_kpis.sql`): Groups by local calendar day, no order-status filter, excludes QA user `424242` and brands `lucente`/`jetem`.
  - *Board Deck* (`dashboards/actives_board.sql`): 30-day trailing window, excludes non-active statuses, removes QA/test accounts using both `analytics.test_users` and email regex heuristics (commit `2dde4f0`).
- **Best Sellers & Category/Brand Revenue** (Dashboards: `best_sellers`, `category_revenue`, `brand_revenue`): 
  - Based on a rolling query-time window (e.g., last 7 or 30 days). 
  - Uses the `order_lines` with legacy `orders` fallback.
  - Excludes `user_id = 424242` and brands `lucente` and `jetem`. Order status is typically unfiltered, and ranking is by revenue, not units (`docs/dashboard_notes.md`).
- **Daily/Intraday Revenue widget** (Dashboard: `revenue_widget`): Safely combines closed `report_rows` and append-only `report_rows_intraday` by grouping by `report_date` and taking the `MAX(created_at)` to avoid double counting snapshots (fixed in `3eced24`).

## 5. System
- **Scheduled Batch Jobs**: Migrated from `crontab.txt` to Airflow (`airflow/dags/`). Jobs live in `novamart/jobs/`.
  - `daily_report.py` / `intraday_report.py`: Compile yesterday's and today's item sales into `report_rows` and `report_rows_intraday`.
  - `trending.py`: Calculates trending items using a rolling 30-day window of `status=1` orders (not 60 days, altered in commit `f563dea`, `docs/trending_notes.md`).
- **Recommendation Systems (Similar Products Widget)** (`novamart/routers/similar.py`):
  - Dispatch is controlled by the `REC_MODEL_VERSION` flag in `deploy/flags.env` (commit `df4ed85`).
  - *Version 2.0.0 (Affinity v2)*: Default production model. `novamart.jobs.affinity_v2` calculates conversion-weighted co-carting affinity with seasonal adjustments, written to `analytics.product_affinity_v2` (commit `89666bf`, `docs/affinity_lineage.md`).
  - *Version 4.0.0 (Logistic Fit)*: Gated ML model trained nightly by `novamart.jobs.model_train` on unbiased random-arm data. Output is stored in `analytics.model_scores` (commit `a1946ff`).
  - *Fallback*: Reverts to `analytics.trending_daily` if cache misses or scores are unavailable.

## 6. Data
- **Warehouse**: BigQuery project `novamart-warehouse` accessed without credentials locally on `http://localhost:9052`.
- **Schemas**:
  - `novamart`: Replica of the Postgres serving DB (`orders`, `payments`, `users`, `products`, `order_lines`).
  - `novamart_analytics`: Materialized views and nightly batch outputs (e.g., `statements_final`, `refunds_unified`, `model_scores`, `reorder_hints`).
- **Data Lineage Quirk**: Legacy users are identified by a numeric `user_id` (in `users` and `orders`). A newer registered-accounts beta introduced UUID `account_id` in the `accounts` table. To link them, you must join `accounts` to `users` via the shared `email` (fixed in dashboard `registered_conversion.sql`, commit `b975479`).

## 7. Experimentation
- **Recommendation Random Arm**: 5% of traffic is sent to a random arm serving uniformly shuffled products (`arm="random"` in `similar.py`). This generates unbiased telemetry in `analytics.rec_decision_log`, which is specifically used to train the v4 logistic regression model (`novamart.jobs.model_train.py`).
- **Dynamic Pricing**: Currently in Phase 1 (shadow mode). The job `novamart.jobs.price_suggest` generates nightly price nudges and writes to `analytics.price_suggestions`. However, serving is on hold pending exec/legal review (commit `cca9b0d`). The live app still relies strictly on the vendor `list_price` (`docs/pricing_status.md`).

## 8. Glossary
- **user_id**: Legacy numeric shopper ID used in historical orders and core `users` table.
- **account_id**: UUID used for the newer registered-accounts beta in the `accounts` table.
- **contactable_customers**: Distinct users who have opted into marketing and have valid non-test email addresses (materialized in `novamart_analytics.contactable_users`, commit `e10cb0c`).
- **status = 1**: Order status indicating a completed/paid order.
- **status = 2 / 3**: Order statuses for cancelled and refunded orders respectively (`novamart/constants.py`).

---
### Appendix

#### Evidence Checklist:
- **Fee logic**: `novamart/constants.py` (`FEE_FLAT = 0.30`) & `novamart/jobs/monthly_statement.py`.
- **Restatement logic**: `docs/restatement_policy.md`, BigQuery view `novamart_analytics.statements_final`.
- **Refund webhook**: `novamart/routers/payments_webhook.py` & `novamart_analytics.refunds_unified`.
- **Dashboard filters**: `docs/dashboard_notes.md` & `dashboards/*.sql` fetched via Redash API.
- **Order lines logic**: Commit `92596dc` (`Count report and dashboard sales per item using order_lines with legacy fallback`).
- **Customer metric definitions**: `docs/metrics_definitions.md`, `novamart/jobs/kpi_daily.py`, and `dashboards/actives_board.sql`.
- **Recommendations lineage**: `docs/affinity_lineage.md`, `novamart/routers/similar.py`, and `novamart/jobs/model_train.py`.
- **Trending window**: `docs/trending_notes.md` (30 days instead of 60 days).
- **Forecasting heuristics**: `docs/forecast_caveats.md` & `novamart/jobs/reorder_forecast.py`.
- **Dynamic pricing shadow mode**: `docs/pricing_status.md` & `novamart/jobs/price_suggest.py`.
- **Account mapping**: `dashboards/registered_conversion.sql` mapping via email.
