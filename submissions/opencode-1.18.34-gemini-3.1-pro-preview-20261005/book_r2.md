# Novamart Tribal Knowledge

## 1. Summary
Novamart's reporting and ML infrastructure contains multiple concurrent definitions for core metrics, differing due to historical evolution and varying team needs. Core financial numbers require understanding the finance restatement pipeline (snapshots vs. overrides vs. chargebacks). Dashboards commonly blend a new `order_lines` table with a legacy `orders` table and apply undocumented exclusions (like QA users and test brands). ML and batch pipelines range from active algorithms to disabled shadow pipelines, and understanding their inputs, outputs, and logging logic is critical to extending them safely.

## 2. Why this project
The goal of this tribal knowledge document is to enable data, finance, and engineering teams to:
- Understand how Novamart computes its core financial numbers (orders, payments, refunds, revenue, and statements).
- Clarify product and customer analytics (active customers, best sellers, reporting assumptions) so dashboard numbers can be explained or mistrusted correctly.
- Understand the ML systems and scheduled jobs: how their outputs are produced, served, and logged, what breaks when they fail, and how to safely judge and modify them.

## 3. Business understanding
- **Order Lifecycle**: Orders progress through statuses: `0` (pending), `1` (paid), `2` (cancelled), `3` (refunded). Orders triggering a fraud score > `0.85` are held in status `6`.
- **Payment Processing**: The processor fee structure shifted on Nov 20, 2019, to include both a percentage rate (`FEE_RATE`) and a flat fee (`FEE_FLAT`), requiring conditional logic in finance queries.
- **Reporting Timezone**: Operations and statements run on `America/New_York` local time.
- **Brand Exclusions**: A massive catalog import occurred for brands `lucente` and `jetem`, skewing numbers. These are intentionally hidden from executive dashboards.

## 4. Metrics
- **Finance Net Revenue**: The ultimate source of truth is the BigQuery view `analytics.statements_final`, which rests on the initial month's `public.statements`, applies manual `analytics.statement_overrides` via `analytics.statements_corrected`, and subtracts later-booked `analytics.chargebacks`.
- **Active Customers**: Differs depending on the consumer:
  - Nightly rollup (`analytics.kpi_daily`): Trailing 30 days, `status = 1`, no test filters.
  - KPI Dashboard (`dashboards/daily_kpis.sql`): Distinct users per day. Excludes QA and test brands.
  - Board Deck (`dashboards/actives_board.sql`): Trailing 30 days. Excludes test accounts, test emails, and statuses 0/2/3.
- **Dashboard Revenue**: Uses rolling time windows (e.g., last 7x24 hours, not calendar weeks). It does *not* filter for completed order statuses.
- **Forecasts**: Reorder hints (`analytics.reorder_hints`) are *not* predictive forecasts; they are an advisory heuristic inversely correlated with sales velocity. 

## 5. System
- **Serving**: The backend runs on Postgres (`novamart`). The recommendation widget (`novamart/routers/similar.py`) controls algorithmic routing via `deploy/flags.env` and caches scores in-memory.
- **Batch Jobs**: Airflow runs Python scripts (`novamart/jobs/`) nightly to generate tables like `product_affinity_v2`, `price_suggestions`, and `report_rows`.
- **Critical Failures**: If `fraud_score.py` fails, high-risk orders are not held in status `6` and pass through. If `monthly_statement.py` fails, the `public.statements` snapshot misses its monthly publication.

## 6. Data
- **Orders vs. Order Lines**: To count item-level sales, queries must use the `order_lines` table (added in commit `92596dc`) but fall back to the legacy `orders` table when an order has no lines.
- **Namespaces**: The `novamart` Postgres DB stores raw application state. In the `novamart-warehouse` BigQuery project, `novamart` dataset is raw data, `novamart_analytics` dataset contains batch outputs and views, and `novamart_logs` holds logs and queries.
- **Customer Identities**: Users are identified by legacy numeric `user_id` (in `users` table) and new UUID `account_id` (in `accounts` table). They must be joined via email.

## 7. Experimentation
- **Dynamic Pricing**: `analytics.price_suggestions` is a purely SHADOW table. It runs nightly but nothing serves from it due to an executive/legal hold.
- **Recommendations**:
  - `v2 (2.0.0)`: The live exploit model. It relies on `analytics.product_affinity_v2` and blends cart counts, conversions, category boosts, and price ratios.
  - `v4 (4.0.0)`: A flag-gated logistic regression model trained nightly on random-arm data.
  - Random arm: 5% of recommendation traffic receives a random selection of products to build unbiased training data for v4, logging to `analytics.rec_decision_log`.
- **Trending window**: The trending jobs (`novamart/jobs/trending.py`) use a rolling 30-day window, shortened from 60 days in commit `f563dea`.

## 8. Glossary
- **`lucente` / `jetem`**: Catalog import brands hidden from executive dashboards to prevent skewed numbers.
- **`424242`**: The ID of the primary QA test user (`cust424242@gmail.example`).
- **`cc27b436-d6f9-4e84-adaf-e716025dd369`**: The UUID representation of the `424242` QA user.
- **`analytics.statements_final`**: The final view for restated monthly revenue, netting out overrides and chargebacks.
- **`analytics.reorder_hints`**: Advisory table for reordering; not a financial forecasting tool.

---

## Appendix: Extra Details & Citations

### A. Restatement Policy & Statements (`docs/restatement_policy.md`)
- `public.statements` contains the original snapshot (generated by `novamart/jobs/monthly_statement.py`).
- `analytics.statements_corrected` is a view that overlays `analytics.statement_overrides`.
- `analytics.statements_final` is a view that subtracts `analytics.chargebacks` (grouped by original order month) from the corrected statements.
- Example: October 2019 net revenue was published as 1194652.79, corrected for fee logic to 1194652.93 (commit `2019-11-02`), and finalized at 1191085.36 due to chargebacks (added to BQ `novamart_analytics.statements_final`).

### B. Dashboard Nuances (`docs/dashboard_notes.md`)
- The `best_sellers` dashboard (Redash query 9) and `category_revenue` (Redash query 6) count item rows from `order_lines` with a legacy fallback (`orders`), added in commit `92596dc`.
- They exclude the QA smoke-test user `user_id <> 424242` (commit `b59f077`).
- They exclude `brand NOT IN ('lucente', 'jetem')` (commit `1169e40`).
- Dashboard queries sort by revenue but display units, and do *not* filter by `orders.status = 1` (paid).

### C. Recommendation Versions (`docs/affinity_lineage.md`, `novamart/routers/similar.py`)
- `REC_MODEL_VERSION` is defined in `deploy/flags.env` and currently set to `2.0.0` (affinity v2 exploit).
- `analytics.product_affinity_v2` is generated by `novamart/jobs/affinity_v2.py`. It uses a 30-day window, weighting carts as 1.0 and orders as 3.0. Note: `SEASONAL_FACTORS` list only has 11 elements, meaning December defaults to a seasonality factor of 1.0.
- `analytics.product_affinity` (v1) is still generated nightly by `novamart/jobs/affinity.py` but is unused by the widget.
- 5% of users receive uniform-random items for training, which are logged to `analytics.rec_decision_log` with `arm='random'`. This is used to train v4 in `novamart/jobs/model_train.py`.

### D. Fraud Scoring (`novamart/jobs/fraud_score.py`)
- The fraud auto-hold threshold is `0.85` (`novamart/constants.py`).
- The score scales based on `price / 3000` and adds a 0.15 boost if the user account is < 7 days old, and a 0.15 boost if the user has 3+ orders in the last 24h. Orders exceeding the threshold are updated to `status = 6`.

### E. Price Suggestions and Forecasts
- `docs/pricing_status.md` and `novamart/jobs/price_suggest.py`: Phase 1 of dynamic pricing generates `analytics.price_suggestions` based on top 500 items, but Phase 2 (serving) is held pending legal/exec review (commit `cca9b0d`).
- `docs/forecast_caveats.md` and `novamart/jobs/reorder_forecast.py`: Reorder hints are an advisory heuristic. The formula is `int(15.6 + 162.4 / (velocity + 1.8))` across 14 days, refitted in commit `f85cdd2`. It is not finance-grade.

### F. Active Customer Dashboard Differences (`docs/metrics_definitions.md`)
- `analytics.kpi_daily` (run by `novamart/jobs/kpi_daily.py`): Trailing 30x24 hours, `status = 1`, no exclusions (commit `14726e7`).
- KPI Dashboard (`dashboards/daily_kpis.sql`, Redash query 7): Per calendar day, no status filter, excludes `424242`, `lucente`, and `jetem` (commits `b59f077`, `1169e40`).
- Board Deck (`dashboards/actives_board.sql`, Redash query 3): Trailing 30x24 hours, excludes statuses 0, 2, 3. Excludes `analytics.test_users` and internal emails (commit `2dde4f0`).

### G. Unified Refunds (`novamart_analytics.refunds_unified`)
- The `refunds_unified` view correctly handles both state-based order refunds (`orders.status IN (2, 3)` mapped to `orders.price`) and gateway-issued payment refunds (`payments.gross < 0 OR payments.net < 0` mapped to `ABS(payments.gross)` or `ABS(payments.net)`).
