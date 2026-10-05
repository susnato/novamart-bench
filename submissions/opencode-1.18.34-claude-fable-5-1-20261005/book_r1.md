# Novamart — Tribal Knowledge Document

- Run UUID: `001cd24c-33db-4793-aec6-647e493aea78`
- Started: Mon Oct 5 17:39:23 UTC 2026
- Sources (and only these): repo `novamart` @ `5ae1182`; BigQuery emulator project `novamart-warehouse` (datasets `novamart`, `novamart_analytics`, `novamart_logs`); Redash at `localhost:5056` (read-only). All queries were read-only `SELECT`s; nothing in Redash was touched.
- Evidence files produced during this run live next to this document (see Appendix J). Query result files are cited as `[file: <name>]`.

---

## 1. Summary

Novamart is a small FastAPI + Postgres marketplace backend (`README.md`, commit `2da4141`, 2019-09-15) whose "numbers" are produced by three loosely coupled layers: (a) the app writing `orders` / `order_lines` / `payments` from payment-gateway callbacks (`novamart/routers/orders.py`), (b) ~15 nightly cron jobs (now Airflow DAGs) that write report/analytics tables (`crontab.txt`, `airflow/dags/`), and (c) 9 Redash dashboards that are verbatim copies of the SQL that used to live in `dashboards/*.sql` (commit `41e3537`). The warehouse (`novamart-warehouse`) is a one-shot BigQuery copy of the serving Postgres taken in Jan 2020 (`novamart/jobs/warehouse_backfill.py`, commit `5ae1182`); data spans 2019-09-25 → 2019-12-31 `[file: table_counts.txt]`.

The ten things a tenured finance/data person knows that nobody wrote down in one place:

1. **"Revenue" has at least five live definitions** that legitimately disagree: the as-published monthly statement (`novamart.statements`), the restated statement (`novamart_analytics.statements_final`), the daily report (`novamart.report_rows`, which excludes test SKUs / denylisted brands / cancelled+refunded / `analytics.test_users`), the exec dashboards (no status filter at all), and payments (`novamart.payments`, which also carries held orders and negative refund rows). For October 2019 these range from **$1,230,332.43** (published) to **$1,098,611.98** (fully cleaned) `[file: phase1_waterfall.txt]`.
2. **October 2019 is overstated by ~$58.8k of duplicate orders.** 130 payment refs were booked 2–4 times each between 2019-09-30 and 2019-10-15 (before idempotency fix `b676969`); 151 of the replay orders are still `status=1` and worth $58,828.24. The nightly `reconcile` job has flagged exactly 130 refs every night since 2019-10-19 and nobody has ever acted on it `[file: phase1_dup_refs.txt, phase1_dup_refs2.txt]`.
3. **Statements are append-only snapshots; cancellations/refunds never restate them.** September's statement ($2,702.00 / 12 orders) is made of 11 orders that were all cancelled and 1 refunded later, plus the QA smoke order. `statements_final` still shows $2,623.64 net for September `[file: phase1_statements.txt, phase1_refunds.txt]`.
4. **The only restatements that exist were done by hand in SQL**, not in code: the October fee override (`analytics.statement_overrides`, 2019-11-02) and three "chargebacks" (`analytics.chargebacks`, 2019-12-09) that were simply the first three October orders over $700 — those same three orders were later cancelled/refunded and so also appear in `refunds_unified` (double representation) `[file: logs_engineer_statements.txt, phase1_statements.txt]`.
5. **Order volume fell ~70% after 2019-11-23** (from ~900–1,300 orders/week to ~240–450) while product views and cart adds stayed flat or rose; 2019-11-15 had zero order callbacks at all. This is upstream of the code (no order `INSERT`s reached the DB that day) and is the single biggest "why did revenue drop" fact in the dataset `[file: phase1_volume_check.txt, phase1_nov15_dec.txt]`.
6. **Two daily reports are permanently wrong and were never re-run**: 2019-11-03 (DST bug, 8 orders / $2,985.99 missing, fixed by `102c9b4`) and 2019-11-17 (500-row scan cap, 222 orders / ~$75.8k missing, fixed by `1233af8`) `[file: phase1_dst_and_misc.txt, phase1_nov_anomaly.txt]`.
7. **"Active customers" is three different metrics** (nightly rollup 1,152 on 2019-12-31; per-day dashboard ~45–75; board query **0** because every user email is `@example.com`/`@gmail.example` and the board query excludes those) `[file: phase2_active_customers.txt]`. `contactable_customers` is always 0 for the same reason `[file: phase2_users.txt]`.
8. **The recommendation system mostly does not recommend.** 80% of `rec_decision_log` rows are trending fallbacks; only 449 of 81,018 products have any affinity score; and since 2019-12-20 **100% of fallback responses include the internal test SKU 1004856** because trending ranks it #2 and the fallback path skips `EXCLUDED_SKUS` `[file: phase3_rec_log.txt, phase1_dst_and_misc.txt, phase3_models.txt]`.
9. **"Model v4" is affinity v2 multiplied by a constant** (`model_scores = v2_score × 0.9755` on 2019-12-31), has never served traffic (`REC_MODEL_VERSION=2.0.0`), and the README's feature list does not match the code `[file: phase3_models.txt]`.
10. **Three routers are silently unmounted** (`users`, `reports` since `f1217a8`; `accounts` since `c49a7bb`), the fraud job auto-holds orders that the monthly statement then excludes but the daily report includes, and the Airflow migration dropped the 17:00 intraday run and left schedule timezone unspecified.

---

## 2. Why this project

Novamart's engineering team is two people (Maya Iyer and Dev Kapoor per `git log`), the data platform was moved off "the single prod box" in Jan 2020 (`docs/data-access.md`, commit `d398b0d`), and the dashboards/schedules were lifted into Redash/Airflow without changing a line of SQL (`41e3537`, `4bfcbe6`). Every finance number is the product of accumulated small decisions: a constant changed here (`constants.py` history), a hand-run `INSERT` there (`[engineer-backfill:*]` lines in `novamart_logs.db_queries`), a dashboard filter added after someone noticed QA data (`b59f077`). Those decisions are spread across 112 commits, 191 ad-hoc engineer SQL statements, 978 job-run log lines, 9 dashboards and 8 one-page docs, several of which are stale (`README.md` still says trending uses 60 days; `docs/rec_versions.md` is literally "TBD").

The three goals this document supports (`rendered_novamart_sim_goal_context.md`):

- Phase 1: answer "what was revenue in month X, and why" the way finance would — Sections 3–4, Appendix A.
- Phase 2: explain any dashboard number, and know when not to trust it — Section 4, Appendix B–C.
- Phase 3: judge whether the ML systems work and modify the batch pipelines safely — Section 5, 7, Appendix D–E.

---

## 3. Business understanding

### 3.1 What the business does (as the data shows it)

- A marketplace storefront relays events to this backend: product views (`GET /products/{pid}`), cart adds/removes (`POST /cart`, `/cart/remove`), gateway payment callbacks that create orders (`POST /orders`), cancels/refunds (`POST /orders/{id}/cancel|refund`), gateway refund webhooks (`POST /payments/gateway_refund`), a vendor price feed (`POST /catalog/prices`) and a similar-products widget (`GET /products/{pid}/similar`) — `novamart/app.py`, `novamart/routers/*`.
- Users and products are **created on first sight** with synthetic profile attributes derived from the id hash (`novamart/onboarding.py`, `catalog.ensure_entities`). Consequences: every user email is a placeholder `user<id>@example.com` (38,910 of 38,950 users; the other 40 were renamed to `cust<id>@gmail.example` on 2019-10-23 via `user_email_updated` events) `[file: phase2_users.txt]`; 17,442 of 81,018 products have a blank brand and 33,514 a blank category because the first sighting carried no catalog metadata and the insert path was `ON CONFLICT DO NOTHING` (`analytics.blank_brand_products.suspected_cause`, created by `[engineer-backfill:dev]` on 2019-10-21) `[file: phase2_products_brands.txt]`.
- Catalog: 81,018 products; the brand mix is dominated by `apple` (49% of all-time paid gross: $1.40M of $2.86M) and `samsung` ($517k) `[file: phase2_products_brands.txt]`. A `lucente` catalog import of 676 SKUs started 2019-10-01 and partnerships asked that the brand be hidden from reports (`ba1fbfa`, 2019-10-25); `jetem` (5 SKUs, zero orders) was added to the denylist on 2019-12-15 (`1169e40`).
- Price: `orders.price` is whatever the gateway callback body says, not the catalog `list_price` (only 2,080 of 7,068 single-line orders match list price) `[file: misc_checks.txt]`. The vendor feed `acme_feed_v2` arrives every Monday 11:00 UTC with 200 items (`price_feed_received` events) but **did not update existing prices until `d213f6e` (2019-11-09)** because it used `ON CONFLICT DO NOTHING`; price history is only recorded from 2019-11-18 (`795d273`, `analytics.price_history`, 1,400 rows) `[file: phase2_brands2.txt]`.
- Fees: processor fee was 2.9% of price (`FEE_RATE=0.029`) until the 2019-11-20 change to 2.9% + $0.30 per transaction (`FEE_FLAT`, commit `12e1c68`). Fees are computed per callback and stored in `payments.fee`.
- Timezone: business days/months are `America/New_York`; data timestamps are UTC (`constants.LOCAL_TZ`, `jobs/timeutil.py`).

### 3.2 Order lifecycle and statuses

`orders.status` (`novamart/constants.py` history; `[file: phase1_statements.txt]`):

| status | meaning | how it is set | count (2019-12-31) |
|---|---|---|---|
| 0 | pending (inserted, before payment row) | `create_order` inserts with 0 then updates to 1 in the same transaction | 0 |
| 1 | paid / complete | `create_order` | 9,033 ($2,860,063.26) |
| 2 | cancelled | `/orders/{id}/cancel` (`8f19718`, 2019-10-28). Was `4` in initial constants, never used | 54 ($13,249.64) |
| 3 | refunded | `/orders/{id}/refund` (`d87cb3d`, 2019-11-15) | 28 ($13,447.47) |
| 4 | (legacy constant for cancelled, never written) | — | 0 |
| 5 | referenced only by `reconcile.py` (`status <> 5`), never written | — | 0 |
| 6 | fraud hold | `jobs/fraud_score.py` (`e4656fb`, 2019-12-03) | 12 ($40,213.29) |

Cancels/refunds arrive in weekly batches every Tuesday 16:00 UTC (6 cancels + 4 refunds) from 2019-11-05 (`order_cancelled` / `order_refunded` events) `[file: phase1_refunds.txt]`. Gateway refund webhooks (`c49a7bb`, 2019-12-05) insert **negative `payments` rows** and do **not** change `orders.status`; the only 9 such rows are the same three October orders (3762, 3763, 3776) refunded three times each on Dec 13/20/27 ($1,843.59 total) `[file: phase1_refunds.txt]`.

### 3.3 Multi-item orders (since 2019-11-22)

Commit `5d1300d` introduced `order_lines`: a callback within 15 minutes of another callback for the same user+session is **appended** to the existing order (`orders.price += line price`, `order_appended` event). `orders.product_id` stays the first line's product. Effects: 2,059 orders have lines, 173 have >1 line (max 6), `orders.price == SUM(order_lines.price)` always `[file: phase1_revenue_definitions.txt]`; order counts fall and average order value rises after 11-22; any query that attributes `orders.price` to `orders.product_id` misattributes $52,812.06 across 173 orders `[file: phase1_waterfall.txt]`. Dashboards and the daily report were fixed to count lines (`92596dc`); `top_sellers`, `trending`, `reorder_forecast`, `price_suggest`, `email_digest`, `affinity_v2`, `model_train`, `fraud_score` and `kpi_daily` still read `orders.product_id` / 1 unit per order.

### 3.4 Timeline of events that changed the numbers

| date | what | evidence |
|---|---|---|
| 2019-09-25 | first QA smoke order (user 424242, SKU 1004856, $9.99) | `orders.id=1`, `PR-qa-2019-09-25…` |
| 2019-09-30 → 10-15 | gateway callback replays create 130 duplicate payment refs (285 orders) | `[file: phase1_dup_refs.txt]`; fix `b676969` (10-15) |
| 2019-10-01 | `lucente` catalog import begins | `products.created_at` |
| 2019-10-08 | test SKUs 1004856, 1002544 excluded from daily report | `83fb3ed` |
| 2019-10-25 | `lucente` hidden from daily report | `ba1fbfa` |
| 2019-10-26 | similar-products widget v1.0.0 live; `users`/`reports` routers dropped from `app.py` | `f1217a8` |
| 2019-10-28 | cancel endpoint; `STATUS_CANCELLED` 4→2 | `8f19718` |
| 2019-11-01 | October statement published with formula fee (35,679.64) | `statement_generated` log |
| 2019-11-02 | statement job switched to collected fees; October override hand-inserted | `a92c96d`; `[engineer-backfill:dev]` |
| 2019-11-03 | DST fall-back; daily report window bug | `102c9b4` (11-05) |
| 2019-11-15 | zero order callbacks all day; refund endpoint added | `[file: phase1_nov15_dec.txt]`; `d87cb3d` |
| 2019-11-16/17 | order spike (401 / 735); 11-17 report capped at 500 rows | `1233af8` (11-19) |
| 2019-11-18 | cancelled/refunded excluded from daily report (`EXCLUDED_STATUSES=[0,2,3]`) | `11c0a42` |
| 2019-11-20 | fee becomes 2.9% + $0.30 | `12e1c68` |
| 2019-11-22 | `order_lines` / same-session merging | `5d1300d` |
| 2019-11-23 → | order volume collapses ~70% | `[file: phase1_volume_check.txt]` |
| 2019-11-27 | QA user 424242 excluded (`analytics.test_users`, dashboards); `/accounts` added | `b59f077`, `b567d9d` |
| 2019-12-01 | 30 accounts created (16:30 UTC); November statement published | `account_created`; `statement_generated` |
| 2019-12-03/04/05 | `affinity_v2` crashes (December seasonal index) | `job_crashed` ×3; fix `3dbe4d7` |
| 2019-12-04 | fraud job's first run holds 8 orders ($27k) | `fraud_scored held=8` |
| 2019-12-05 | `/accounts` router dropped; gateway refund webhook added; threshold 0.90→0.70 | `c49a7bb`, `53f6f6c` |
| 2019-12-06 | widget v2.0.0 + 5% random arm; trending window 60→30d | `df4ed85`, `f563dea` |
| 2019-12-08 | intraday snapshots (12:00/17:00 local) | `a2e0013` |
| 2019-12-09 | chargebacks + `statements_final` hand-created | `[engineer-backfill:dev]`; `cd559d3` |
| 2019-12-12 | versioned category mapping (`category_name_history`) | `33054cd` |
| 2019-12-14 | model v4 training job; funnel gap 30→120 min | `a1946ff`, `f915c1b` |
| 2019-12-15 | `jetem` added to denylist | `1169e40` |
| 2019-12-17 | email digest finally runs (flag bug) | `digest_sent` first on 12-17 |
| 2019-12-19 → 12-26 | widget cache bug serves empty lists → fallback | `a00f24c`, `8ed2971` |
| 2019-12-29 | threshold 0.70→0.85; 5 held orders < $2,600 released by hand | `1cb8721`; `[engineer-backfill:maya] UPDATE orders` |
| 2020-01-02 → 01-05 | platform migration: Redash, Airflow, BigQuery backfill | `d398b0d`, `41e3537`, `4bfcbe6`, `5ae1182` |

---

## 4. Metrics

### 4.1 Revenue — which number, from where

| Consumer | Source of truth | Definition | Oct-2019 value |
|---|---|---|---|
| Board deck "as published" | `novamart.statements` (job `monthly_statement`, 06:30 local on the 1st) | `SUM(orders.price)` where `status=1` **at run time**, local-month window; fee = `SUM(payments.fee)` (since `a92c96d`); net = gross − fee. Append-only; one row per run. | gross 1,230,332.43 / fee 35,679.64 / net **1,194,652.79** / 3,765 orders |
| Finance "corrected" | `novamart_analytics.statements_corrected` (view, hand-created 2019-11-02) | statements with `statement_overrides` applied by month | fee 35,679.50 / net 1,194,652.93 |
| Finance "current" | `novamart_analytics.statements_final` (view, hand-created 2019-12-09; Redash dashboard `statements_final`) | corrected − `analytics.chargebacks` summed by **order's** local month | gross 1,226,764.86 / net **1,191,085.36** |
| Exec daily KPI / revenue widget | `novamart.report_rows` (+ `report_rows_intraday` for today) | daily job at 06:00 local; counts `order_lines` (fallback `orders`); excludes `status IN (0,2,3)`, SKUs 1004856/1002544, brands lucente/jetem, users in `analytics.test_users`; takes latest snapshot per `report_date` | 3,631 units / 1,201,082.08 (31 days) |
| Best sellers / brand / category dashboards | live `orders`+`order_lines` | rolling `now()` windows (7d / 30d / 30d), **no status filter**, exclude user 424242 (+UUID in brand), brands lucente/jetem | n/a (rolling) |
| Cash-ish | `novamart.payments` | one row per callback (incl. held orders) + negative gateway refunds | 3,765 rows / 1,230,332.43 |
| Current ledger | `novamart.orders` `status=1` | what a query today returns | 3,695 / 1,206,337.32 |

`[file: phase1_statements.txt, phase1_revenue_definitions.txt, phase1_waterfall.txt]`

**October 2019 waterfall** (local month, `[file: phase1_waterfall.txt]`):

| step | orders | gross |
|---|---|---|
| A. published statement | 3,765 | 1,230,332.43 |
| B. currently `status=1` (70 later cancelled/refunded) | 3,695 | 1,206,337.32 |
| C. minus 151 duplicate-ref replays | 3,544 | 1,147,509.08 |
| D. minus test SKUs 1004856 / 1002544 | 3,391 | 1,115,528.51 |
| E. minus lucente/jetem | 3,339 | 1,098,611.98 |
| G. `statements_final` (A − 3,567.57 chargebacks) | 3,765 | 1,226,764.86 |

**How to answer "what was revenue in October and why"**: "$1,194,652.79 net as published 2019-11-01; restated to $1,191,085.36 in `statements_final` because the fee was corrected to collected fees (+$0.14) and three chargebacks totalling $3,567.57 were booked on 2019-12-09. Neither number removes the 70 orders cancelled/refunded after publication ($23,995.11), the 151 duplicate callback orders ($58,828.24), the remaining test-SKU orders ($31,980.57 after de-duplication) or `lucente` ($16,916.53 after the previous steps); the daily report ($1,201,082.08) removes the SKUs/brand but not the duplicates." The same logic for November: published $1,069,286.09 net (fee $32,110.92 includes $0.30/txn after 11-20; the "audit correction" in `statement_corrections` is a **zero** delta because the job already used collected fees) `[file: phase1_statements.txt, phase1_fee_and_exclusions.txt]`; the daily report shows only $966,974.33 because the Nov-17 cap lost ~$75.8k and brands/SKUs remove ~$56k `[file: phase1_waterfall.txt]`. December has **no statement yet** (job runs on the 1st; data ends 12-31); `status=1` Dec = $552,328.93; held orders add $40,213.29 to `payments` and to `report_rows` but will be excluded from the statement `[file: phase1_nov15_dec.txt]`.

### 4.2 Refunds

- `novamart_analytics.refunds_unified` (view, hand-created 2019-12-23; Redash `refunds`) = `orders` with status 2/3 (amount = full `orders.price`, time = `updated_at`) ∪ negative `payments` rows (`gateway_refund`). Monthly: Nov 24 cancels $6,511.32 + 8 refunds $3,180.45; Dec 30 cancels $6,738.32 + 20 refunds $10,267.02 + 9 gateway refunds $1,843.59 `[file: phase1_refunds.txt]`.
- Caveats: cancellations and refunds are dated by `updated_at` (the Tuesday batch), not by order month; the 9 gateway refunds are 3 orders refunded 3× each (webhook not idempotent); the 3 chargeback orders (46, 49, 55) are also in `refunds_unified` → **subtracting refunds from `statements_final` double counts $3,567.57**.

### 4.3 Product performance

- **Best sellers** (Redash `best_sellers`, query 9): last 7×24h from `now()`, line-level, no status filter, excl. user 424242 and lucente/jetem, **sorted by revenue** (shows `units`). As of 2019-12-31: #1 Apple Smartphone #5116 ($5,889.81), #6 is test SKU 1002544 ($4,498.52) `[file: phase2_dashboards_repro.txt]`. The nightly `top_products` job (`top_sellers.py`) is a different list: yesterday only, `status=1`, order-level, ranked by units.
- **Brand revenue** (query 8): 30d, same rules plus string exclusion of QA account UUID `cc27b436-…` (harmless—`orders.user_id` is numeric). Blank brand is the 5th largest "brand" ($17,585 in Dec-30d) `[file: phase2_dashboards_repro.txt]`; `internal` (the test SKU) shows as a brand ($7,624.89).
- **Category revenue** (query 6): maps `products.category` → `display_group` via `analytics.category_names` ∪ `category_name_history` with an as-of `valid_from`. Only prefixes electronics/appliances/apparel/construction/kids get a group; everything else (computers, furniture, auto, sport, blank) is `other` (52 codes) — `other` is the 2nd largest group ($93,558.92 of $569k) `[file: phase2_dashboards_repro.txt, phase2_products_brands.txt]`. The 12-12 remap of `electronics.audio.*`→`entertainment` and `construction.tools.light`→`lighting` is **inert**: the history rows carry `valid_from = 2026-08-13` (the `CURRENT_DATE` of when the backfill statements were actually replayed), later than any order `[file: phase2_products_brands.txt, logs_engineer_statements.txt]`.
- **Trending** (`analytics.trending_daily`): 30-day rolling (not 60 as README says — `f563dea`, logs switch `window_days` 60→30 on 2019-12-07), `status=1`, ≥5 units, score = units·e^(−0.05·days since last sale), top 50, keeps history by day. On 2019-12-31 ranks #2 and #3 are the test SKUs 1004856 and 1002544 `[file: phase3_models.txt]`.
- **Reorder hints / price suggestions**: advisory heuristics, overwritten nightly, nothing reads them (Appendix D).

### 4.4 Customers

| metric | where | definition | value 2019-12-31 |
|---|---|---|---|
| signups | `novamart.users` by `created_at` | first-sight auto-insert, not real registrations | 38,950 total; Oct 15,045 / Nov 11,302 / Dec 12,529 |
| active customers (nightly) | `analytics.kpi_daily` (`kpi_daily.py`) | distinct `user_id`, `status=1`, trailing 30 days from run ts; no exclusions | 1,152 |
| active customers (exec KPI) | Redash `daily_kpis` | distinct ordering users per local day, any status, excl. 424242 & lucente/jetem (via `orders.product_id`) | 44–75 per day |
| active customers (board) | Redash `actives_board` | trailing 30d, status ∉ {0,2,3}, excl. `test_users` and test-like emails incl. `example.com`/`*.example` | **0** (all 38,950 emails are excluded) |
| contactable customers | `analytics.contactable_users` view (hand-created 2019-12-04) | opt-in ∧ valid email ∧ not example.com/.net/.org/`*.example` | **0 rows** |
| digest recipients | `email_digest.py` | `email NOT LIKE '%@example.com'` (ignores opt-in) | 40 |
| registered buyers | Redash `registered_conversion` | `accounts` → `users` by email → orders `status=1` | 30 buyers / $18,155.71 (identical via `account_map`) |

`[file: phase2_active_customers.txt, phase2_users.txt, docs/metrics_definitions.md]`. The 30 accounts were all created 2019-12-01 16:30 UTC during the 8 days the `/accounts` router was mounted (`b567d9d` → `c49a7bb`); one is the QA user (`cc27b436-…`).

### 4.5 Funnel

`analytics.daily_funnel`: sessions = runs of `cart_items` ∪ `orders` events per user split by an inactivity gap (30 min until `f915c1b` on 2019-12-14, then 120 min); `users_active` = distinct users with a cart or order event in the trailing 24h. It never sees product views. Sessions jumped from ~230 to ~400/day on 2019-12-16 because cart adds rose, not because of the gap change `[file: phase2_dashboards_repro.txt]`.

---

## 5. System

### 5.1 Components

- **App**: FastAPI, `novamart/app.py`; psycopg async pool (`db.py`); every statement logged to `db_queries.log` with actor tag `[app]`/`[job]` (`logutil.db_log`) — this log is what `novamart_logs.db_queries` contains (3.6M lines). Mounted routers at HEAD: `catalog`, `carts`, `orders`, `similar`, `payments_webhook`. **Not mounted**: `users` (`/users/{id}/email`) and `reports` (`/reports/brands`) — dropped by `f1217a8` on 2019-10-26; `accounts` — dropped by `c49a7bb` on 2019-12-05 (`git log -p novamart/app.py`). `/reports/brands` is the only code path that honours `EXCLUDED_SKUS`+`BRAND_DENYLIST`+`status=1` together, and it is dead.
- **Order creation** (`routers/orders.py`): advisory locks on session and ref; look up ref in `orders` and `order_lines`; replay → add missing payment / flip status 0→1 (`order_callback_replayed`, 522 events); same-session within 15 min → append line (`order_appended`, 225); else new order + line + payment (`order_created`, 9,127). DDL (`CREATE TABLE IF NOT EXISTS order_lines…`, `ALTER TABLE payments ADD COLUMN payment_ref`) runs on **every** request.
- **Jobs**: `novamart/jobs/*.py`, each opens its own connection (`db.job_connect`), creates its own tables (`CREATE TABLE IF NOT EXISTS` — schema lives in code, not `schema.sql`), logs to `jobs.jsonl` (→ `novamart_logs.job_runs`). Schedule in `crontab.txt` (retired) → `airflow/dags/*_dag.py` (one BashOperator each). See Appendix D.
- **Flags**: `deploy/flags.env` (`REC_MODEL_VERSION=2.0.0`, read from the working directory at request time) and `deploy/cron.env` (`ENABLE_DIGEST=1`).
- **Warehouse**: `warehouse_backfill.py` exports each table via `gcloud sql export csv` and `bq load --replace` per `warehouse_manifest.json` (12 `public.*` → `novamart.*`, 20 `analytics.*` → `analytics.*`; in the emulator the dataset is `novamart_analytics`). Views (`contactable_users`, `refunds_unified`, `statements_corrected`, `statements_final`) exist in BQ with translated SQL `[file: view_definitions.json]`. `novamart_logs` holds `app_events` (1.57M), `db_queries` (3.6M), `job_runs` (978) and a `db_queries_normalized` view that fakes `INFORMATION_SCHEMA.JOBS` columns.
- **Dashboards**: Redash, one data source `novamart` (type `pg`, i.e. the serving replica, **not** BigQuery), 9 queries/9 dashboards, each a single table widget, no schedule, never executed (`latest_query_data_id: null`) `[file: redash_queries_sql.txt, redash_dashboards.json]`. Query text is identical to `git show 41e3537^:dashboards/*.sql` `[file: legacy_dashboards_sql.txt]`.

### 5.2 Scheduled jobs (local times from `crontab.txt`; Airflow cron strings are numerically identical)

| local time | job | reads | writes | write mode | failure impact |
|---|---|---|---|---|---|
| 03:00 | `reconcile` | `orders` | nothing (WARN logs `duplicate_payment_ref`) | — | none; nobody consumes |
| 03:30 | `affinity` | `cart_items` 30d | `analytics.product_affinity` (+creates `rec_decision_log`) | full overwrite | none (unused since 12-06) |
| 03:45 | `affinity_v2` | `cart_items`, `orders`, `products` | `analytics.product_affinity_v2` | full overwrite | widget serves stale scores; crashed 12-03..05 |
| 04:15 | `model_train` | `rec_decision_log` (random arm), `affinity_v2` | `model_registry` (append), `model_scores` (overwrite) | — | none (v4 not served) |
| 04:45 | `price_suggest` | `orders` 14d | `analytics.price_suggestions` | overwrite | none (shadow) |
| 05:15 | `trending` | `orders` 30d | `analytics.trending_daily` | delete+insert same day (history kept) | widget fallback breaks (`MAX(day)` stale) |
| 05:45 | `fraud_score` | `orders` 1d, `users` | `analytics.order_risk` (append), **`UPDATE orders SET status=6`** | — | holds not applied |
| 06:00 | `daily_report` | `orders`,`order_lines`,`products`,`test_users` | `report_rows` | append; dashboards take `MAX(created_at)` per date | KPI dashboard/revenue widget miss a day |
| 06:15 | `kpi_daily` | `orders` 30d | `analytics.kpi_daily` | append | gap in series |
| 06:20 | `funnel` | `cart_items`,`orders` 1d | `analytics.daily_funnel` | append | gap |
| 06:30 (1st) | `monthly_statement` | `orders`,`payments` | `statements` | append | no statement → `statements_final` row missing |
| 06:45 | `top_sellers` | `orders` yesterday | `top_products` | append | none consumes |
| 06:50 | `reorder_forecast` | `orders` 14d | `analytics.reorder_hints` | overwrite | none |
| 07:15 | `email_digest` | `orders` 7d, `users` | `analytics.digest_log` | append | none |
| 12:00, 17:00 | `intraday_report` | as daily | `report_rows_intraday` | append | today's widget value stale |

Ordering matters: `fraud_score` (05:45) runs **before** `daily_report` (06:00), so held orders (status 6, not in `EXCLUDED_STATUSES=[0,2,3]`) are counted in `report_rows` and dashboards but not in `monthly_statement`/`kpi_daily`/`trending` (`status=1`) `[file: phase3_fraud2.txt]`.

### 5.3 Airflow migration risks (`airflow/dags/`, commit `4bfcbe6`, `5ae1182`)

- `intraday_report_dag.py` schedules only `0 12 * * *`; the 17:00 run in `crontab.txt` was dropped.
- `crontab.txt` says "times are local"; DAGs use naive `start_date=datetime(2019,9,15)` and no timezone → schedules will run in Airflow's default timezone (UTC unless configured), 5 hours earlier in local terms. The `report_day = local yesterday` logic still works, but `kpi_daily.day`/`daily_funnel.day` (UTC date of run) and intraday coverage change.
- `warehouse_backfill_dag.py` runs `python -m novamart.jobs.warehouse_backfill` without the required `--project/--instance/--staging` args → argparse exits 2 if triggered.
- No job_runs exist after 2019-12-31, so none of this has been observed running.

---

## 6. Data

### 6.1 Tables (BigQuery `novamart-warehouse`, snapshot as of 2020-01; `[file: table_counts.txt, schema_*.csv]`)

**`novamart` (serving `public.*`)**

| table | rows | range | notes |
|---|---|---|---|
| `orders` | 9,127 | 2019-09-25 → 12-31 | one row per order; `price` = order total; `product_id` = first line; `payment_ref` = first callback ref |
| `order_lines` | 2,284 | 2019-11-22 → | one per callback since `5d1300d`; `payment_ref` unique |
| `payments` | 9,361 | | one per callback (+9 negative gateway refunds); `payment_ref` NULL before 11-22 |
| `users` | 38,950 | | synthetic profiles; emails placeholders |
| `products` | 81,018 | | 17,442 blank brand; 33,514 blank category |
| `cart_items` | 36,938 | | |
| `report_rows` | 6,923 | 2019-09-25 → 12-30 | 1 snapshot per date (no reruns ever) |
| `report_rows_intraday` | 2,358 | 2019-12-08 → 12-31 | 2 snapshots/day (17:00, 22:00 UTC) |
| `statements` | 3 | 2019-09, 10, 11 | append-only |
| `top_products` | 2,396 | 2019-11-06 → 12-30 | |
| `accounts` / `account_map` | 30 / 30 | 2019-12-01 | UUID namespace; map to `users.id` via `account_map.uid` or email |

**`novamart_analytics` (serving `analytics.*`)**

| table/view | rows | produced by | notes |
|---|---|---|---|
| `kpi_daily` | 45 | job | 2019-11-17 → |
| `daily_funnel` | 53 | job | 2019-11-09 → |
| `trending_daily` | 2,898 | job | history by day |
| `product_affinity` / `_v2` | 3,912 each | jobs | 2,964 sentinel −1 rows, 948 scored, 449 base products with scores; v2 rows stamped `model_version='2.0.1'` |
| `rec_decision_log` | 667,850 | app | every widget decision (gaps: random arm 12-17→12-19) |
| `model_registry` / `model_scores` | 17 / 948 | `model_train` | |
| `order_risk` | 1,631 | `fraud_score` | |
| `price_history` | 1,400 | app price feed | from 2019-11-18 |
| `price_suggestions` / `reorder_hints` | 500 / 200 | jobs | overwritten nightly, no history |
| `digest_log` | 15 | `email_digest` | 2019-12-17 → |
| `test_users` | 1 | hand (`424242`) | 2019-11-27 |
| `blank_brand_products` | 5,972 | hand CTAS | 2019-10-21 (captured_at shows 2026-08-13) |
| `category_names` / `category_name_history` | 135 / 6 | hand | history `valid_from=2026-08-13` |
| `statement_overrides` / `statement_corrections` / `chargebacks` | 1 / 1 / 3 | hand | see Appendix F |
| `contactable_users` (view) | 0 | hand | |
| `refunds_unified`, `statements_corrected`, `statements_final` (views) | | hand | |

**`novamart_logs`**: `app_events.jsonPayload` (events: `product_viewed` 843k, `rec_served` 669k, `cart_item_added` 37k, `duplicate_payment_ref` 10.8k, `order_created` 9,127, `order_callback_replayed` 522, `order_appended` 225, `order_cancelled` 54, `user_email_updated` 40, `account_created` 30, `order_refunded` 28, `price_feed_received` 13, `gateway_refund` 9, `statement_fee_mismatch` 3) `[file: phase1_logs_overview.txt]`; `db_queries.textPayload` = `"<ts> [<actor>] statement: <sql> -- params: <tuple>"` with actors `app`, `job`, `engineer:dev|maya`, `engineer-backfill:dev|maya` `[file: logs_db_queries_actors.txt]`; `job_runs.jsonPayload` = `jobs.jsonl`.

### 6.2 Data quality facts to keep in your head

1. Duplicate orders (130 refs / 285 orders, Sep-30→Oct-15) are still present and `status=1` `[file: phase1_dup_refs2.txt]`.
2. `report_rows` is never recomputed: 2019-11-03 and 2019-11-17 are permanently short; September has only 2 report days.
3. Test SKU 1004856 ("Internal Test #4856", brand `internal`, category `qa.test`, list $9.99) has 322 **paid** orders from 241 distinct users at real-looking prices ($40,304.68) and is the #2 trending product; 1002544 is an Apple phone with 138 paid orders from 87 users ($66,226.12) that is nevertheless on the "test SKU" list `[file: phase2_brands2.txt, phase1_fee_and_exclusions.txt, verify_test_skus.txt]`.
4. All emails are placeholders; any email-based exclusion zeroes the metric.
5. Products/users rows are created by whichever event saw them first — `created_at` is "first sighting", not signup/listing date; blank brand/category are structural, not rare.
6. `updated_at` values of `2026-08-13 21:12:33` on 5 orders and `captured_at`/`valid_from` = 2026-08-13 are artefacts of the hand statements being replayed when the estate was built; the log timestamps (2019-12-29, 2019-10-21, 2019-12-12) are the business dates `[file: phase3_fraud2.txt, logs_engineer_statements.txt]`.
7. Month windows: statements use local-month UTC bounds (`2019-10-01 04:00Z` → `2019-11-01 04:00Z`; November ends `2019-12-01 05:00Z` after DST). Using UTC calendar months moves ~4–5 hours of orders.
8. Redash runs `now()`-relative windows against the Postgres replica; the warehouse is a frozen copy, so dashboard numbers cannot be reproduced from BQ without pinning `now()` (this document pins it to `2019-12-31 23:59:59 UTC`).

---

## 7. Experimentation

### 7.1 Similar-products widget (`novamart/routers/similar.py`)

- **Versions**: 1.0.0 (co-cart affinity, 2019-10-26 → 12-06; fallback = 7-day best sellers from `orders`), 2.0.0 (affinity v2 "exploit", default via `deploy/flags.env`), 4.0.0 (trained `model_scores`, flag-gated, never enabled). Table rows stamp `model_version='2.0.1'` while serving calls it `2.0.0` (`docs/affinity_lineage.md`).
- **Random arm**: 5% of users (`sha256(uid) % 20 == 0`) get 5 uniformly shuffled products from the first 500 ids (`ORDER BY id LIMIT 500`), deterministic per `(uid, session, pid)`. 14,566 logged decisions; ~1,370 random-arm decisions in 12-17→12-19 were not logged (`30e8907` dropped it, `a00f24c` restored) `[file: phase3_rec_log.txt]`.
- **Outcomes by source** (all time, `[file: phase3_rec_log.txt]`): fallback 534,145 (80.0%; of which 25,091 are `fallback_reason='cache'` from the 12-19→12-26 empty-cache bug fixed by `8ed2971`), affinity v1 66,444, v2 "model" 52,695 (21,427 served from the 6h in-process cache), random 14,566.
- **Coverage**: 449 base products have a non-sentinel score vs 47,240 distinct products viewed in December → the exploit arm essentially never fires `[file: phase1_dst_and_misc.txt]`.
- **Fallback contamination**: the fallback reads `trending_daily` **without** filtering `EXCLUDED_SKUS`; 103,142 of 103,142 fallback responses since 2019-12-20 contain test SKU 1004856 `[file: phase1_dst_and_misc.txt]`.
- **No evaluation exists**: nothing joins `rec_decision_log.items` to subsequent carts/orders; there is no CTR/conversion metric for any arm.

### 7.2 Model v4 (`jobs/model_train.py`, `a1946ff`)

- Trains a 5-feature logistic regression on **all** random-arm decisions (no holdout, no time split) with label `converted` = "user placed any paid order after the impression" — not tied to the recommended items. Features in code: `n_items`, `base_price/1000`, `base_popularity/100`, `min(account_age/60,1)`, `organic_user`. README lists nine features (region, device, stock, opt-in…) that are not in the vector.
- Scoring: `model_scores = affinity_v2.score × (1 + 0.1·coef[0])` — a single scalar on 2019-12-31 (0.97545…0.97556 across all 948 pairs) → identical ranking to v2 `[file: phase3_models.txt]`. Coefficients swing sign day to day (e.g. `organic_user` from −2.35 to +0.04) with 4k–14k rows `[file: phase3_models.txt]`.
- Verdict: v4 adds nothing over v2 and is not an experiment that can be read out.

### 7.3 Affinity v2 scoring (`jobs/affinity_v2.py`)

`score = (1·pairs + 3·conversions) · e^(−0.05·age) · 1.15[same category] · 0.7[price ratio >4 or <0.25] · season[month]`. `SEASONAL_FACTORS` has 11 entries (Jan–Nov); December indexed out of range and crashed the job on 12-03/04/05 (`job_crashed` ×3) until `3dbe4d7` defaulted it to 1.0 `[file: phase3_models.txt]`. Pairs seen <3 times get sentinel −1 (serving filters `score >= 0`).

### 7.4 Other "experiments"

- **Dynamic pricing** (`price_suggest.py`): ±5% nudge around median demand for top-500 SKUs; phase 2 ON HOLD per exec/legal (`cca9b0d`); nothing reads it (`docs/pricing_status.md`).
- **Reorder hints** (`reorder_forecast.py`): `int(15.6 + 162.4/(velocity+1.8))`; K refit 141.12→162.4 (`f85cdd2`); hints *increase* as velocity falls (`docs/forecast_caveats.md`).
- **Fraud auto-hold** (`fraud_score.py`): `score = min(price/3000,1)·(1+0.15·new_account+0.15·high_velocity)`; threshold 0.90 (12-03) → 0.70 (12-05) → 0.85 (12-29). 17 holds total; 12 remain ($40,213.29, all ≥ $2,655); 5 released by a hand `UPDATE … WHERE status = 6 AND price < 2600` on 2019-12-29 `[file: phase3_fraud.txt, phase3_fraud2.txt]`. It is a price rule, not a model.
- **Email digest**: top 7-day product to 40 "recipients"; the top product was the internal test SKU on 12-19→12-21 `[file: phase2_users.txt]`.

---

## 8. Glossary

- **Published statement** — row in `novamart.statements` written by `monthly_statement` on the 1st; never edited.
- **Corrected / final statement** — `analytics.statements_corrected` (overrides applied) / `analytics.statements_final` (minus chargebacks). Use `statements_final` for current finance numbers, `statements` to match an old deck (`docs/restatement_policy.md`).
- **Override** — `analytics.statement_overrides` row that replaces a statement month (only 2019-10).
- **Correction** — `analytics.statement_corrections` audit delta (only 2019-11, delta 0.00).
- **Chargeback** — `analytics.chargebacks` row (3 rows, hand-picked), subtracted in `statements_final` by the *order's* month.
- **Gross / fee / net** — `SUM(orders.price)` / `SUM(payments.fee)` / gross − fee, `status=1`, local month.
- **FEE_RATE / FEE_FLAT** — 0.029 / 0.30 (`constants.py`); flat fee applies to callbacks after 2019-11-20 (`FEE_CHANGE_AT` = 2019-11-20 00:00 local).
- **Local day / month** — `America/New_York` boundaries converted to UTC (`timeutil.py`).
- **Daily report / `report_rows`** — per-product units & revenue for yesterday (local), with report exclusions; "units" = order lines, not orders.
- **Intraday snapshot** — `report_rows_intraday`, today's partial totals; use latest `created_at` per `report_date`.
- **Report exclusions** — `EXCLUDED_STATUSES=[0,2,3]`, `EXCLUDED_SKUS=[1004856,1002544]`, `BRAND_DENYLIST=['lucente','jetem']`, `analytics.test_users={424242}`.
- **Dashboard exclusions** — `user_id <> 424242` (brand: also `'cc27b436-…'`), `brand NOT IN ('lucente','jetem')`; **no** status or SKU filter.
- **QA smoke user** — `users.id=424242` (`cust424242@gmail.example`), session `qa-smoke`, account UUID `cc27b436-d6f9-4e84-adaf-e716025dd369`.
- **Test SKUs** — 1004856 "Internal Test #4856" (brand `internal`, category `qa.test`) and 1002544.
- **Duplicate ref** — same `payment_ref` on >1 order (130 refs, pre-`b676969`); flagged nightly by `reconcile`, never cleaned.
- **Replay** — callback with an already-seen ref (`order_callback_replayed`), idempotent since 2019-10-15.
- **Appended order / order line** — same user+session callback within 15 min merges into the open order (`order_appended`, `order_lines`).
- **Held order** — `status=6`, set by `fraud_score`; excluded from statement/kpi/trending, included in daily report and dashboards.
- **Active customers** — three definitions (nightly 30d `status=1`; dashboard per-day any status; board 30d with email heuristics) — see §4.4.
- **Contactable users** — `analytics.contactable_users` view (opt-in + real-looking email); always empty here.
- **Registered customer** — row in `accounts` (UUID), link to legacy `users.id` via `account_map.uid` or shared email.
- **Affinity v1 / v2** — co-cart pair scores (`product_affinity` / `product_affinity_v2`); sentinel −1 = "too few pairs", not negative preference.
- **Random arm** — 5% of users served uniform-random items for training data (`arm='random'`).
- **Fallback** — widget response from `trending_daily` latest day (`rec_source='fallback'`, `fallback_reason` ∈ {`no_scores`,`table_missing`,`cache`}).
- **REC_MODEL_VERSION** — `deploy/flags.env` flag choosing `2.0.0` (affinity v2) or `4.0.0` (model_scores).
- **Trending** — 30-day decayed unit ranking (`trending_daily`), top 50/day.
- **Top products** — `top_products` nightly yesterday-only ranking (unused by dashboards).
- **Reorder hint / price suggestion** — advisory heuristic tables, overwritten nightly, no consumers.
- **Display group** — category roll-up in `analytics.category_names` (electronics, appliances, apparel, construction, kids, other).
- **Blank brand** — `products.brand=''` from first-sight inserts; catalogued in `analytics.blank_brand_products`.
- **`[engineer-backfill:*]`** — actor tag in `db_queries` for hand-run DDL/DML; the only record of out-of-band changes.

---

## Appendix A — Finance deep-dive

### A.1 Monthly statement job, line by line (`novamart/jobs/monthly_statement.py`)

1. `month` = previous local month; window via `local_month_window_utc`.
2. `gross, n` = `SUM(price), COUNT(*)` from `orders` where `created_at` in window and `status = 1`.
3. `fee` = `SUM(payments.fee)` joined to those orders (since `a92c96d`; before, `round(gross·0.029, 2)`).
4. `expected_fee` = per-order `ROUND(price·0.029[+0.30 if created ≥ FEE_CHANGE_AT],2)` (since `4a58d17`); a `statement_fee_mismatch` WARNING is logged if |fee − expected| > 0.01 — logged all three months (Sep −0.01, Oct +0.14, Nov −170.41 because the Dec-1 run predated `4a58d17`) `[file: phase1_logs_overview.txt]`.
5. `INSERT INTO statements` (append). Nothing ever updates or deletes.

Known gaps: counts orders not lines; ignores negative payments; ignores status 2/3/6 changes after the run; `payments` for duplicate orders are summed (so the fee is also overstated for October).

### A.2 Fee change reconciliation (November)

Payments on orders before 2019-11-20 05:00Z: 2,981 rows, fee 26,434.34 = exactly `ROUND(gross·0.029)` per row; after: 633 rows, fee 5,676.58 vs 5,505.90 at 2.9% → +170.68 ≈ 633 × $0.30 less rounding `[file: phase1_fee_and_exclusions.txt]`. The hand-inserted `statement_corrections` row for 2019-11 computed `statement.fee − SUM(payments.fee)` = 0.00 `[file: logs_engineer_statements.txt]`.

### A.3 Duplicate payment refs

- Pattern: identical user/product/price, 1–17 minutes apart, 2019-09-30 → 2019-10-15 (127 refs identical, 3 refs with differing fields) `[file: phase1_dup_refs2.txt]`.
- 285 orders, 285 payments ($106,943.01 gross); extras still paid: 151 orders / $58,828.24.
- `reconcile` output: `flagged` grows 1→100 (capped by `RECONCILE_BATCH=100`), bump to 200 on 2019-10-18 (`030d841`) reveals 130 from 10-19, constant thereafter `[file: phase1_dup_refs.txt]`. 10,766 `duplicate_payment_ref` WARNINGs in `app_events`.
- Maya investigated on 2019-10-15 (`[engineer:maya]` queries on `PR-5fa7482f-1004767`) and shipped `b676969`; no cleanup followed.

### A.4 Daily report defects

- **DST (2019-11-03)**: `local_day_window_utc` used `start + 24h`; the 25-hour local day lost 23:00–24:00 local (04:00–05:00Z Nov 4): report 123 units/$35,429.68 vs 131/$38,415.67 `[file: phase1_dst_and_misc.txt]`; Dev's 11-05 queries compare `buggy_cnt` vs `correct_cnt`; fixed `102c9b4`; not re-run.
- **Scan cap (2019-11-17)**: `fetchmany(REPORT_SCAN_CAP=500)` → `orders_scanned=500`, 487 units/$148,857.07 vs 709 paid non-test orders/$224,626.79 `[file: phase1_nov_anomaly.txt, phase1_fee_and_exclusions.txt]`; fixed `1233af8` (11-19); not re-run. `REPORT_SCAN_CAP` still exists in `constants.py`, unused.
- **2019-11-15**: `orders_scanned=0` — genuinely zero orders (0 `INSERT INTO orders` in `db_queries`, 2,284 cart inserts) `[file: phase1_nov15_dec.txt]`.
- Status drift: the report runs at 06:00 next day; later cancellations are never reflected (Oct report 3,631 units incl. orders cancelled weeks later).
- `scripts/rerun_kpis.py` + `jobs/discounts.py` (`DISCOUNT_CAP` 0.25 vs legacy default 0.40) is a stub "ops runbook" with an empty `rows=[]`; no report ever had discounts applied.

### A.5 Payments table semantics

One row per gateway callback (`gross=price, fee, net=gross−fee`), so merged orders have N rows; held orders have rows; gateway refunds are negative rows with `fee=0`. `payment_ref` populated only since 2019-11-22 (2,284 of 9,361). Orders with 2–6 payment rows: 176 `[file: phase1_dup_refs.txt]`.

---

## Appendix B — Customer definitions, reproduced

Reproductions as of 2019-12-31 `[file: phase2_active_customers.txt]`:

- `kpi_daily` 2019-12-31 = 1,152 = `COUNT(DISTINCT user_id)` for `status=1`, `created_at` in `[2019-12-01 11:15Z, 2019-12-31 11:15Z]`.
- Board query candidates 1,151 → 1,150 after `test_users` → **0** after email heuristics.
- Exec KPI `customer_days`: 44–75 distinct users/day, `contactable=0` every day.
- `registered_conversion`: 30 buyers / $18,155.71 (email join == `account_map` join).

Why they differ: window (per-day vs 30d), status filter (none vs `=1` vs `∉{0,2,3}`), exclusions (none vs 424242+brands vs test_users+emails). The board query is the only one that would survive real emails; with placeholders it is useless (`docs/metrics_definitions.md` documents the first two differences but not that the board number is zero).

---

## Appendix C — Dashboards: filters, assumptions, gotchas (`[file: redash_queries_sql.txt]`)

| Redash dashboard / query id | window | grain | status filter | exclusions | gotchas |
|---|---|---|---|---|---|
| `daily_kpis` / 7 | today−13 → today (local) | per day | report: 0,2,3 excluded (via `report_rows`); customers: none | brands lucente/jetem (both parts), 424242 (customers only) | "orders" column is **units** from `report_rows`; revenue inherits report defects (11-03, 11-17); customers use `orders.product_id` brand (first line) |
| `revenue_widget` / 2 | today−6 → today | total | as report | none beyond report | pre-`3eced24` version double counted intraday+daily snapshots; correct version takes latest snapshot per date |
| `best_sellers` / 9 | `now()−7d` | product (lines) | **none** | 424242, lucente/jetem | includes held/cancelled/refunded orders and test SKUs; sorted by revenue |
| `brand_revenue` / 8 | `now()−30d` | brand (lines) | none | 424242 + UUID string, lucente/jetem | blank brand and `internal` appear as brands |
| `category_revenue` / 6 | `now()−30d` | display group (lines) | none | 424242, lucente/jetem | `other` bucket large; history remap inert (valid_from 2026) |
| `actives_board` / 3 | `now()−30d` | count | ∉{0,2,3} | test_users + email heuristics | returns 0 on this data |
| `registered_conversion` / 4 | all time | count/sum | `=1` | none | first version joined UUID to numeric id (returned 0, `d6e34c6` "numbers look low"); fixed `b975479` |
| `refunds` / 1 | all time by month of `at` | month | 2,3 + negative payments | none | dated by `updated_at`; gateway refunds triple-posted; overlaps chargebacks |
| `statements_final` / 5 | all | month | `=1` at publish time | none | see A.1 |

Reproduced values (now pinned to 2019-12-31 23:59:59Z) are in `[file: phase2_dashboards_repro.txt]`.

---

## Appendix D — Batch job catalogue (details beyond §5.2)

- **`daily_report.py`** — `report_day = local yesterday`; `has_order_lines` branch; aggregates in Python; `INSERT` per product. Log: `report_generated {report_date, products, orders_scanned}`. 107 runs 2019-09-16 → 12-31.
- **`intraday_report.py`** — same with `end = now`; writes `report_rows_intraday`. 47 runs from 2019-12-08 (first day only one run at 22:00Z).
- **`monthly_statement.py`** — see A.1. 3 runs.
- **`reconcile.py`** — `GROUP BY payment_ref HAVING COUNT(*)>1 … LIMIT RECONCILE_BATCH`; `status <> 5` (meaningless). 107 runs.
- **`kpi_daily.py`**, **`funnel.py`**, **`top_sellers.py`**, **`trending.py`**, **`email_digest.py`** — see §4/§5.2. `email_digest` ran 0 times 2019-11-28 → 12-16 because `c19a307` read `DIGEST_ON` while `cron.env` set `ENABLE_DIGEST`; `8dc520b` and `0bd4eac` fixed it (first `digest_sent` 2019-12-17) `[file: phase1_logs_overview.txt, phase2_users.txt]`.
- **`affinity.py` / `affinity_v2.py` / `model_train.py`** — see §7. `affinity` 80 runs from 2019-10-13; `affinity_v2` 26 successes from 12-06 + 3 crashes; `model_train` 17 runs from 12-15.
- **`fraud_score.py`** — 28 runs from 2019-12-04; `UPDATE orders` 17 times (= 17 holds) `[file: misc_checks.txt]`.
- **`price_suggest.py`** (37 runs from 11-25), **`reorder_forecast.py`** (35 runs from 11-27).
- **`warehouse_backfill.py`** — manual; `--replace` loads; casts timestamps to UTC strings; `__PGNULL__` sentinel.

Modifying safely: every job owns its table DDL; adding a column means editing the `CREATE TABLE IF NOT EXISTS` *and* handling the existing table (no migrations). Overwrite-style tables (`product_affinity*`, `model_scores`, `price_suggestions`, `reorder_hints`) lose history on every run; append-style tables (`report_rows`, `kpi_daily`, `statements`, `order_risk`, `top_products`) require "latest snapshot" logic downstream. Jobs read `deploy/*.env` relative to CWD — run from repo root.

---

## Appendix E — Recommendation lineage and how to evaluate it

- Lineage: `cart_items` → (`affinity.py` → `product_affinity`) and (`affinity_v2.py` → `product_affinity_v2`) → `similar.py` (version dispatch, cache, fallback to `trending_daily`) → `rec_decision_log` + `rec_served` events. `model_train.py`: `rec_decision_log[arm='random']` + `orders` + `users` + `products` → `model_registry`, `model_scores` (= rescaled `product_affinity_v2`).
- To evaluate, join `rec_decision_log` (split `items`) to `cart_items`/`orders` for the same `user_id` after `ts`, by `arm`/`rec_source`. No such query exists in the engineer logs or dashboards.
- Serving cache: in-process per worker (4 uvicorn workers → 4 caches), 6h TTL, invalidated when `MAX(updated_at)` changes (`8ed2971`); every request issues `SELECT MAX(updated_at) FROM <table>`.
- Flag flip to 4.0.0 would read `analytics.model_scores`, which is the same ranking as v2.

---

## Appendix F — Out-of-band DB changes (`[engineer-backfill:*]` in `novamart_logs.db_queries`, `[file: logs_engineer_statements.txt]`)

| log ts | actor | statement |
|---|---|---|
| 2019-10-21 14:00 | dev | `CREATE SCHEMA analytics`; `CREATE TABLE analytics.blank_brand_products AS SELECT …` (with `suspected_cause` text) |
| 2019-11-02 14:00 | dev | `CREATE TABLE analytics.statement_overrides`; `INSERT … ('2019-10', 1230332.43, 35679.50, 1194652.93, 3765, …, 'Corrected to sum of per-order collected payment fees')`; `CREATE OR REPLACE VIEW analytics.statements_corrected` |
| 2019-11-15 15:00 | dev | `CREATE TABLE analytics.price_history` + index |
| 2019-11-27 15:00 | dev | `CREATE TABLE analytics.test_users`; `INSERT … (424242)` |
| 2019-11-30 20:00 | dev | `CREATE TABLE analytics.category_names (code PK…)`; `INSERT` prefix→display_group mapping with `valid_from = MIN(products.created_at)` |
| 2019-12-02 15:00 | dev | `CREATE TABLE analytics.statement_corrections`; `INSERT ('2019-11', <stmt fee − collected fee>, 'November 2019 processor fee change audit correction')` → 0.00 |
| 2019-12-04 15:00 | maya | `CREATE OR REPLACE VIEW analytics.contactable_users` |
| 2019-12-08 20:00 | dev | `CREATE TABLE public.report_rows_intraday` + index |
| 2019-12-09 15:00 | dev | `CREATE TABLE analytics.chargebacks`; `INSERT` first 3 October `status=1` orders with `price > 700` (ids 55, 46, 49) `reported_at='2019-12-01 12:00Z'`; `CREATE OR REPLACE VIEW analytics.statements_final`; re-create `statements_corrected` |
| 2019-12-12 20:00 | dev | `CREATE TABLE analytics.category_name_history`; `INSERT` lighting/entertainment rows with `valid_from = CURRENT_DATE`; guarded `INSERT` into `category_names` (no-op because PK exists) |
| 2019-12-23 20:00 | dev | `CREATE OR REPLACE VIEW analytics.refunds_unified` |
| 2019-12-29 15:00 | maya | `UPDATE orders SET status = 1, updated_at = NOW() WHERE status = 6 AND price < 2600` (5 orders: 7626, 7735, 8329, 8385, 9358) |

None of these are in the repo; commits `4a58d17`, `cd559d3`, `a3bffec`, `e10cb0c`, `2814b3d`, `33054cd`, `b59f077` reference them only in messages or dashboard SQL.

---

## Appendix G — Constants history (`novamart/constants.py`)

| constant | initial (`2da4141`) | changes |
|---|---|---|
| `FEE_RATE` | 0.029 | — |
| `FEE_FLAT` | — | 0.30 (`12e1c68`, 2019-11-20) |
| `EXCLUDED_SKUS` | `[]` | `[1004856, 1002544]` (`83fb3ed`, 10-08) |
| `BRAND_DENYLIST` | `[]` | `['lucente']` (`ba1fbfa`, 10-25) → `+ 'jetem'` (`1169e40`, 12-15) |
| `STATUS_CANCELLED` | 4 | 2 (`8f19718`, 10-28) |
| `STATUS_REFUNDED` | — | 3 (`d87cb3d`, 11-15) |
| `EXCLUDED_STATUSES` | `[0]` | `[0,2,3]` (`11c0a42`, 11-18) |
| `RECONCILE_BATCH` | 100 | 200 (`030d841`, 10-18) |
| `REPORT_SCAN_CAP` | 500 | unused since `1233af8` (11-19) |
| `DISCOUNT_CAP` | — | 0.25 (`35c581e`, 11-21; unused) |
| `FRAUD_HOLD_THRESHOLD` | — | 0.90 (`e4656fb`, 12-03) → 0.70 (`53f6f6c`, 12-05) → 0.85 (`1cb8721`, 12-29) |
| trending `WINDOW_DAYS` | 60 (`152a760`) | 30 (`f563dea`, 12-06) |
| funnel `GAP_MIN` | 30 (`4dbcf7f`) | 120 (`f915c1b`, 12-14) |
| reorder `K` | 141.12 (`f5e3032`) | 162.4 (`f85cdd2`, 12-21) |
| affinity `MIN_PAIRS` | — | 3 (`fef5c96`, 11-12) |
| `REC_MODEL_VERSION` | (absent) | `2.0.0` (`df4ed85`, 12-06) |

---

## Appendix H — How to query this estate

- BigQuery emulator: `source access-pack/env.sh`; `bq ls` works; `bq query` from stdin crashes on some result sets (CLI bug: missing `statementType`), so use the REST helper `bqq.py` in this folder (`python3 bqq.py file.sql`, statements separated by a line `--;`). Table names: `novamart.<table>`, `novamart_analytics.<table>`, `novamart_logs.<table>`; JSON fields via `JSON_VALUE(jsonPayload, '$.event')`; `textPayload` for `db_queries`.
- Pin `now()` to `2019-12-31 23:59:59+00` to reproduce dashboards. Local month bounds: Oct `['2019-10-01 04:00Z','2019-11-01 04:00Z')`, Nov `['2019-11-01 04:00Z','2019-12-01 05:00Z')`, Dec `['2019-12-01 05:00Z','2020-01-01 05:00Z')`.
- Redash API: `GET /api/queries/{1..9}`, `/api/dashboards/{1..9}` with header `Authorization: Key …` (`/api/dashboards/<slug>` returns 500 on this instance).

---

## Appendix I — Open risks and the fix a tenured person would propose

1. Clean or exclude the 151 duplicate-ref orders (`ROW_NUMBER() OVER (PARTITION BY payment_ref ORDER BY id) > 1`) and restate October; make `reconcile` actionable.
2. Decide whether statements should be restated for status changes; today `statements_final` only knows about 3 hand-picked chargebacks that overlap `refunds_unified`.
3. Re-run `daily_report` for 2019-11-03 and 2019-11-17 (append a newer snapshot; dashboards already take `MAX(created_at)`).
4. Add `EXCLUDED_SKUS` filtering to the widget fallback and to `trending`; decide whether 1002544 is really a test SKU.
5. Align `fraud_score`/`EXCLUDED_STATUSES` (status 6) across daily report, dashboards and statements.
6. Fix Airflow: restore the 17:00 intraday run, set `America/New_York` on DAGs, pass args to `warehouse_backfill`.
7. Re-mount or delete `users`, `reports`, `accounts` routers; the `/reports/brands` logic is the closest thing to a correct brand report.
8. Fix `category_name_history.valid_from` (should be 2019-12-12) and extend `category_names` beyond the 5 prefixes.
9. Replace placeholder emails or drop email-based exclusions from `actives_board`/`contactable_users`.
10. Either evaluate the widget (join decisions to outcomes by arm) or retire `affinity`, `model_train`, `price_suggest`, `reorder_forecast`, `top_sellers` — none has a consumer.

---

## Appendix J — Evidence files in this folder

`git_log.txt`, `commit_stats.txt`, `all_commit_diffs.txt` (every non-deploy commit diff), `legacy_dashboards_sql.txt` (`dashboards/*.sql` at `41e3537^`), `schema_novamart.csv`, `schema_novamart_analytics.csv`, `schema_novamart_logs.csv`, `view_definitions.json`, `table_counts.txt`, `phase1_statements.txt`, `phase1_logs_overview.txt`, `phase1_revenue_definitions.txt`, `phase1_volume_check.txt`, `phase1_nov_anomaly.txt`, `phase1_dup_refs.txt`, `phase1_dup_refs2.txt`, `phase1_refunds.txt`, `phase1_fee_and_exclusions.txt`, `phase1_dst_and_misc.txt`, `phase1_nov15_dec.txt`, `phase1_waterfall.txt`, `phase2_products_brands.txt`, `phase2_brands2.txt`, `phase2_users.txt`, `phase2_active_customers.txt`, `phase2_dashboards_repro.txt`, `phase3_fraud.txt`, `phase3_fraud2.txt`, `phase3_rec_log.txt`, `phase3_models.txt`, `logs_db_queries_actors.txt`, `logs_engineer_statements.txt`, `misc_checks.txt`, `verify_test_skus.txt`, `redash_dashboards.json`, `redash_queries.json`, `redash_query_{1..9}.json`, `redash_dashboard_{1..9}.json`, `redash_queries_sql.txt`, `bqq.py` (read-only REST query helper).
