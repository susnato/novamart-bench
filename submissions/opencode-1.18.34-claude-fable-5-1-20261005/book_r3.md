# Novamart Tribal Knowledge

Run id: `be7f8dbc-000a-4d8b-9a84-269d865e540b` · Started: Mon Oct 5 17:39:27 UTC 2026
Sources: repo `novamart` @ `5ae1182` (112 commits, 2019‑09‑15 → 2020‑01‑05); BigQuery project `novamart-warehouse` (datasets `novamart`, `novamart_analytics`, `novamart_logs`); Redash at `localhost:5056` (9 dashboards / 9 queries).
Evidence conventions used below: `commit <hash>` = git; `table`/`view` = BigQuery object; `bq/NN_name.txt` = saved query + result in this run folder (`bq/`); `redash/query_N.json` = Redash export; `job_runs`/`app_events`/`db_queries` = `novamart_logs.*` rows.

---

## 1. Summary

Novamart is a FastAPI + Postgres marketplace backend (`README.md`, commit `2da4141`). Three months of production data exist (orders 2019‑09‑25 → 2019‑12‑31; 9,127 orders, 38,950 users, 81,018 products — `bq/00_counts.txt`), copied into BigQuery by `novamart.jobs.warehouse_backfill` (commit `5ae1182`). Dashboards were moved from `dashboards/*.sql` into Redash verbatim (commit `41e3537`; `redash/query_*.json` match the last git versions), and cron schedules were re‑expressed as Airflow DAGs (commit `4bfcbe6`).

The ten things a tenured finance/data person knows that nobody wrote down:

1. **There is no single "revenue".** Finance statements (`novamart.statements` → `statements_corrected` → `statements_final`) are *as‑of snapshots of `orders.price` where `status=1`*; the KPI dashboard reads nightly `report_rows` snapshots that apply different exclusions; exec dashboards (best sellers / brand / category) query live `orders`+`order_lines` with **no status filter**. October 2019 "revenue" is legitimately 1,230,332.43 (published), 1,226,764.86 (restated gross), 1,206,337.32 (status=1 today), 1,147,509.08 (deduplicated), or 1,098,611.98 (daily‑report rules) depending on which rule you apply (`bq/10_statements.txt`, `bq/10e_stmt_views.txt`, `bq/19_month_reconciliation.txt`).
2. **October gross is inflated by ~$58.8k of duplicate orders.** 130 payment_refs appear on 285 order rows (gateway callback retries before idempotency landed in commit `b676969` on 2019‑10‑15); 151 extra rows are still `status=1` and were included in the published statement (`bq/14_dup_refs.txt`, `bq/14d_dup_inflation.txt`). The nightly `reconcile` job has flagged the same 130 refs every night since (`bq/14c_reconcile_runs.txt`); nobody acts on it.
3. **Every customer email is a placeholder** (`user<id>@example.com`; 40 users were re‑pointed to `@gmail.example` on 2019‑10‑23 — `bq/22_users_emails.txt`, `bq/22d_email_updates.txt`). Consequently the board "active customers" query returns **0** (`bq/23_actives_board_repro.txt`), `analytics.contactable_users` has **0 rows** (`bq/01_counts_analytics.txt`), KPI‑dashboard `contactable_customers` is always 0, and the marketing digest counts 40 recipients including the QA account (`bq/23c_digest_log.txt`).
4. **The "Internal Test #4856" SKU is the #1 trending product and is recommended to ~80% of widget traffic.** The similar‑products widget falls back to `analytics.trending_daily` whenever no affinity scores exist (449 of 81k products have scores — `bq/32b_affinity_state.txt`); the fallback path does not apply `EXCLUDED_SKUS`, so 212,898 / 212,898 fallback decisions since Dec 6 contain product 1004856 (`bq/34_rec_test_sku_served.txt`, `novamart/routers/similar.py:118-123`).
5. **"Rec model v4" is a constant multiple of affinity v2.** `model_scores = affinity_v2.score × (1 + 0.1·w)` where `w` is the coefficient of a feature that is always 5 (`novamart/jobs/model_train.py:68-72`; ratio 0.9755 for all 948 pairs — `bq/32_model_scores_vs_v2.txt`). The README feature list (region, device, stock, opt‑in) is not implemented (`model_train.py:49-56`).
6. **Fraud holds silently move money between metrics.** `fraud_score` sets `status=6` for orders > ~$2,550 (`core = price/3000`, threshold 0.85 — `novamart/jobs/fraud_score.py`, `constants.py:38`). Held orders drop out of statements/KPI rollups (`status=1`) but *stay in* the daily report and every exec dashboard (`EXCLUDED_STATUSES=[0,2,3]`); Dec 3 KPI revenue is 39,127 vs ~14k normal because 8 held $2,999.99 orders are counted (`bq/52_held_in_report.txt`, `bq/52b_dec3_total.txt`).
7. **Refunds are triple‑counted and never reduce revenue.** The gateway refund webhook (commit `c49a7bb`) inserts negative `payments` rows but does not change `orders.status`; the same 3 orders received identical webhooks on Dec 13, 20 and 27 (9 rows, 1,843.59 vs 614.53 real — `bq/13c_gateway_refunds.txt`, `bq/13d_neg_payments.txt`). The Redash `refunds` dashboard sums cancellations + refunds + all 9 gateway rows (`bq/45b_refund_paths.txt`).
8. **Three documented active‑customer definitions exist and a fourth (`daily_funnel.users_active`) is undocumented**; none agree (`docs/metrics_definitions.md`, `bq/23b_kpi_daily.txt`, `bq/42_funnel.txt`). The mid‑December drop in `kpi_daily.active_customers` (1,560 → 1,031 on Dec 16‑18) is the Nov 15‑17 traffic surge rolling out of the 30‑day window, not churn.
9. **Daily report history has known, un‑backfilled holes**: Nov 3 (DST, 8 orders/$2,986 missed — commit `102c9b4`, `bq/44c_dst_hour.txt`), Nov 17 (500‑row scan cap, 217 units/~$75k missed — commit `1233af8`, `bq/16_report_vs_orders.txt`), Nov 15 (zero orders recorded despite 3× traffic — `bq/17_nov15_outage.txt`), and Nov 22 – Dec 5 (multi‑line orders counted as one unit — commit `92596dc`). `report_rows` has never been re‑generated (`bq/15_report_rows_versions.txt`).
10. **Several endpoints and tables are dead or orphaned.** `/reports/brands` and `/users/{id}/email` were unmounted by commit `f1217a8` (Oct 26); `/accounts` by commit `c49a7bb` (Dec 5); `analytics.product_affinity` (v1) is still computed nightly but unread since Dec 6 (`bq/50_dbq_readers.txt`); `analytics.price_suggestions` is write‑only (phase 2 on hold — commit `cca9b0d`).

---

## 2. Why this project

- **Purpose.** Build the tribal knowledge needed to (a) explain "what was revenue in month X and why", (b) explain or distrust any dashboard number, and (c) judge whether the ML/batch systems work and can be safely modified (goal context: `rendered_novamart_sim_goal_context.md`).
- **Why it is needed.** The repo's own docs are partial and sometimes stale: `README.md` still says trending uses a 60‑day window (fixed to 30 in commit `f563dea`; `docs/trending_notes.md` says so); `docs/rec_versions.md` is literally "TBD" (commit `4396fbb`); the README's v4 feature list does not match `model_train.py`. Metric definitions changed roughly weekly from Oct to Dec 2019 (see §4 timelines), and the dashboards were lifted into Redash without the history that explains them (commit `41e3537`).
- **Why now.** The Jan 2020 platform migration (commits `d398b0d`, `41e3537`, `4bfcbe6`, `5ae1182`) moved dashboards to Redash and schedules to Airflow. Two migration‑era risks are documented in §5: Airflow cron strings copied the *local* times from `crontab.txt` (which says "times are local") without a DAG timezone, and the intraday 17:00 run was dropped (`airflow/dags/intraday_report_dag.py` vs `crontab.txt:28-29`).
- **What this document is not.** It does not restate `docs/*.md`; where a doc exists it is cited and then verified or corrected against warehouse data and logs.

---

## 3. Business understanding

### 3.1 What the business does (as seen in code and data)

- Marketplace storefront that relays only ids; the backend synthesizes user/product attributes deterministically from ids (`novamart/onboarding.py:1-6`). `users` rows are created on first product view / cart / order, so `users.created_at` is **first‑touch**, not signup (`novamart/routers/catalog.py:58-66`; 38,932 of 38,950 users' first event is `product_viewed` — `bq/46b_first_touch.txt`).
- Orders arrive as **payment‑gateway callbacks** (`POST /orders`, `novamart/routers/orders.py:14`). The charged `price` is the callback body's price, not the catalog `list_price` (82% of order lines differ from list price; mean ratio 1.45 — `bq/54_price_vs_list.txt`). Catalog prices come from a weekly vendor feed (`POST /catalog/prices`, Mondays 11:00 UTC, 200 items, source `acme_feed_v2` — `bq/42f_price_feeds.txt`).
- Volume: Oct 3,765 orders / Nov 3,582 / Dec 1,768; views rose Oct→Dec (207k → 322k) while order callbacks halved (3,763 → 1,962) (`bq/11_recompute_month.txt`, `bq/53_monthly_funnel.txt`). A traffic surge on Nov 15‑17 (≈28k views/day vs ≈10k) produced **0 orders on Nov 15** and 349 / 770 on Nov 16 / 17 (`bq/17_nov15_outage.txt`).
- Money: processor fee 2.9% (`constants.FEE_RATE`), plus $0.30 flat from 2019‑11‑20 (`FEE_FLAT`, commit `12e1c68`; `FEE_CHANGE_AT` in `monthly_statement.py:13`). Fees are computed by the app at order time and stored per payment row (`orders.py:19,60`).

### 3.2 People and process signals

- Two engineers do everything: **Maya Iyer** (order/payment paths, similar‑products widget, accounts, digest) and **Dev Kapoor** (batch jobs, reports, statements, dashboards, docs) (`git_log.txt`). A "Novamart Platform" author did the Jan 2020 migration.
- Deploys show up in git as separate "trigger deploy #d2p-novamart" commits, but they are **not** reliable markers of when code took effect: job output reflects a change at the next scheduled run after the code commit (fraud threshold 0.70 committed Dec 5 15:00 UTC → the Dec 6 10:45 UTC run already logs `threshold: 0.7`, hours before the Dec 6 20:37 "trigger deploy" commit — `bq/18b_fraud_runs.txt`; trending 30‑day window committed Dec 6 15:30 → Dec 7 run logs `window_days: 30` — `bq/33b_trending_runs.txt`).
- A **weekly back‑office cleanup** runs every Tuesday 16:00 UTC: 6 cancellations + 4 refunds, walking the oldest orders in id order (ids 1→82 by Dec 31) (`bq/45_cancel_pattern.txt`). These are not customer‑initiated; they are why September/October revenue keeps shrinking after publication.
- Engineers run ad‑hoc SQL on prod tagged `[engineer:dev]`, `[engineer:maya]`, `[engineer-backfill:*]` (`bq/51_dbq_sources.txt`, `bq/51b_dbq_nonapp.txt`). Several "analytics" tables were created by hand this way rather than by a job: `blank_brand_products` (Oct 21), `statement_overrides` + `statements_corrected` (Nov 2), `test_users` (Nov 27), `category_names` (Nov 30, Dec 12), `statement_corrections` (Dec 2), `contactable_users` (Dec 4), `chargebacks` + `statements_final` (Dec 9), `category_name_history` (Dec 12), `refunds_unified` (Dec 23), and the fraud release `UPDATE orders SET status=1 … WHERE status=6 AND price<2600` (Dec 29).

### 3.3 Business rules encoded as constants (`novamart/constants.py`)

| Rule | Value | History |
|---|---|---|
| Fee rate / flat | 0.029 / 0.30 | flat added commit `12e1c68` (2019‑11‑20) |
| Excluded "test" SKUs | 1004856, 1002544 | commit `83fb3ed` (Oct 8). **1002544 is an Apple smartphone bought by 88 distinct real users (139 orders, ≈$635 each)** — `bq/20b_excluded_skus.txt`. 1004856 "Internal Test" (brand `internal`, category `qa.test`) was nevertheless bought by 244 distinct users. |
| Brand denylist | lucente, jetem | lucente commit `ba1fbfa` (Oct 25, "per partnerships"; 676 products, ~$15‑20k/month of real sales); jetem commit `1169e40` (Dec 15; **5 products, 0 orders** — a no‑op) — `bq/19_month_reconciliation.txt`, `bq/20c_jetem.txt`. `lucentesilver` (1 product) is not excluded. |
| Order statuses | 0 pending, 1 paid, 2 cancelled, 3 refunded, 6 held | `STATUS_CANCELLED` was 4 until commit `8f19718` (Oct 28); `reconcile.py:16` still excludes a never‑used status 5. Current distribution: 1=9,033, 2=54, 3=28, 6=12 (`bq/52c_status_dist.txt`). |
| Report exclusions | statuses [0,2,3] | [0] until commit `11c0a42` (Nov 18). Status 6 (held) is **not** excluded. |
| Discount cap | 0.25 | commit `35c581e`; `scripts/rerun_kpis.py` calls `apply_discounts(rows)` without passing it, so the ops helper silently uses the legacy 0.40 default (`novamart/jobs/discounts.py:4`). |
| Fraud hold threshold | 0.85 | 0.90 (commit `e4656fb`, Dec 3) → 0.70 (`53f6f6c`, Dec 5) → 0.85 (`1cb8721`, Dec 29) |
| Local timezone | America/New_York | all "days" and "months" in reports/statements are Eastern; data timestamps are UTC (`jobs/timeutil.py`) |

---

## 4. Metrics

### 4.1 Revenue — the full lineage

**Write path.** `POST /orders` (`routers/orders.py:14-111`): lock on `session` and `ref`; if the `payment_ref` is already known → replay (insert a missing `payments` row, flip status 0→1); else if the same user has a non‑cancelled order in the same `session` within 15 minutes → **append** a line (`UPDATE orders SET price = price + …`, insert `order_lines` + `payments`); else create `orders` (status 0) + `order_lines` + `payments` and set status 1. Consequences: `orders.price` is the **order total**, `orders.product_id` is the **first line's product** (verified for all 2,059 line‑bearing orders — `bq/43b_first_product_check.txt`); 173 multi‑line orders hide 225 items from any consumer that reads `orders` alone (`bq/43_multiline.txt`). `order_lines` exists only from 2019‑11‑22 (commit `5d1300d`); older orders have no lines, hence the "legacy fallback" UNION in reports/dashboards (commit `92596dc`).

**Monthly statement** (`jobs/monthly_statement.py`, runs 06:30 local on the 1st): `gross = SUM(orders.price) WHERE status=1` in the local month; `fee = SUM(payments.fee)` for those orders; `net = gross − fee`; appended to `novamart.statements` (append‑only; 3 rows — `bq/10_statements.txt`). Changes: fee was `gross × 0.029` until commit `a92c96d` (Nov 2); expected‑fee check learned the flat fee in commit `4a58d17` (Dec 2). The `statement_fee_mismatch` warning fired for all three months (−0.01, +0.14, −170.41 — `bq/13_fee_mismatch.txt`).

**Restatement layers** (`docs/restatement_policy.md`, verified):
- `analytics.statement_overrides` (1 row, Oct fee 35,679.64 → 35,679.50; inserted by hand Nov 2 — `bq/10b_overrides.txt`, `bq/51b_dbq_nonapp.txt`).
- `analytics.statements_corrected` = statements LEFT JOIN overrides (view def in `bq/`‑adjacent `INFORMATION_SCHEMA.VIEWS` output above).
- `analytics.chargebacks` (3 rows, 3,567.57, `reported_at` 2019‑12‑01) and `analytics.statements_final` = corrected − chargebacks grouped by the **order's** month. The chargeback rows were created on Dec 9 by selecting "the first 3 October paid orders with price > 700" (`db_queries` 2019‑12‑09 15:00 `[engineer-backfill:dev]`) — i.e. they are not a gateway feed. All three orders have since been cancelled/refunded by the Tuesday batch (status 2/3 — `bq/10d_chargebacks.txt`), so anyone recomputing October from `orders` *and* subtracting chargebacks double‑counts them.
- `analytics.statement_corrections` (Nov, delta 0.00, "processor fee change audit correction") is informational only — nothing reads it (`bq/10c_corrections.txt`).

**October 2019 waterfall** (`bq/19_month_reconciliation.txt`, `bq/11_recompute_month.txt`, `bq/14d_dup_inflation.txt`):

| Number | Value | Source / rule |
|---|---|---|
| Published gross / net | 1,230,332.43 / 1,194,652.79 | `novamart.statements` (Nov 1 10:30 UTC; fee = gross×2.9%) |
| Corrected net | 1,194,652.93 | `statements_corrected` (fee = Σ payments.fee) |
| **Final (finance) gross / net** | **1,226,764.86 / 1,191,085.36** | `statements_final` (− 3,567.57 chargebacks) |
| status=1 recomputed today | 1,206,337.32 (3,695 orders) | 70 orders cancelled/refunded since Nov 1 |
| … minus duplicate payment_refs | 1,147,509.08 | 151 duplicate rows, 58,828.24 |
| … minus QA user 424242 | 1,147,459.13 | 5 orders × 9.99 |
| … minus lucente + excluded SKUs | 1,098,611.98 | the daily‑report rule set |
| Gateway refunds on Oct orders | −1,843.59 recorded / −614.53 unique | `payments.gross<0`; orders still status 1 |

Rule of thumb: *board/finance* → `statements_final`; *"what did we say then"* → `statements`; never recompute from `orders` without deduplicating `payment_ref` and deciding on statuses 2/3/6.

**Other months.** Sep 2019: 2,702.00 (12 orders: the QA order of Sep 25 plus 11 orders placed late Sep 30 Eastern = Oct 1 02:45–03:55 UTC; all 12 have since been cancelled/refunded by the Tuesday batch — `bq/44_sept_orders.txt`). Nov 2019: 1,101,397.01 / 32,110.92 / 1,069,286.09 (no corrections; fee includes the Nov 20 flat change). Dec 2019: **no statement exists yet** (would run 2020‑01‑01); a preview under the same rule is 1,756 orders, gross 552,328.93, fee 16,600.26 (`bq/54b_dec_statement_preview.txt`), excluding $40,213 of held orders.

### 4.2 Daily revenue / KPI dashboard (`report_rows`, `report_rows_intraday`, Redash `daily_kpis`)

- `jobs/daily_report.py` (06:00 local) writes yesterday's per‑product units/revenue for item rows with status ∉ {0,2,3}, excluding `analytics.test_users`, `EXCLUDED_SKUS`, `BRAND_DENYLIST`. Append‑only; the dashboard takes `MAX(created_at)` per `report_date` but no day has ever been re‑run (`bq/15_report_rows_versions.txt`).
- `jobs/intraday_report.py` (12:00 and 17:00 local in cron; 22:00 UTC only in Airflow) appends today's partial totals; two versions per day exist from Dec 9 (`bq/25_intraday_versions.txt`). The first revenue widget double‑counted both tables (commit `686a5d6`, fixed `3eced24`).
- The KPI column named **`orders` is SUM(units) = item count**, not orders. `active_customers` there is per‑Eastern‑day distinct buyers with no status filter; `contactable_customers` is always 0 (see §4.4). Reproduction for the last 14 days: `bq/25b_daily_kpis_repro.txt`.
- Known bad days in `report_rows`: 2019‑10‑01 → 10‑14 include duplicate orders, lucente and later‑cancelled orders (as‑of rules); 11‑03 missing 8 orders/$2,985.99 (DST window bug, commit `102c9b4`); 11‑15 zero; 11‑17 capped at 500 scanned rows → 487 units vs 704 actual (commit `1233af8`); 11‑22 → 12‑04 multi‑line orders counted as one unit under the first product (commit `92596dc`); 12‑03 includes $26,999.91 of orders later held for fraud (`bq/16_report_vs_orders.txt`, `bq/52_held_in_report.txt`).

### 4.3 Product metrics

| Surface | Window | Status filter | Exclusions | Gotchas |
|---|---|---|---|---|
| Redash `best_sellers` (query 9) | rolling 7×24h from `now()` | none | user 424242; brands lucente/jetem | ranks by revenue; counts `order_lines` with legacy fallback; fraud‑held orders included (e.g. Samsung #5284 at #3 with 2 held units — `bq/24_best_sellers_repro.txt`); excluded SKU 1002544 appears |
| Redash `brand_revenue` (query 8) | rolling 30d | none | `user_id::text NOT IN ('424242','cc27b436-…')` — the UUID clause can never match a bigint column (no‑op, commit `adbcb7e`) | brand `''` (17,442 blank‑brand products, $17.6k/30d) and brand `internal` ($7.6k) appear as rows (`bq/55_brand_rev_repro.txt`) |
| Redash `category_revenue` (query 6) | rolling 30d | none | 424242; lucente/jetem | maps `products.category` via `category_names` ∪ `category_name_history` with `valid_from <= order date`; blank category (33,514 products, $294k lifetime) → `other` (`bq/21h_cat_coverage.txt`). In the warehouse copy `category_name_history.valid_from` = 2026‑08‑13, so the "entertainment"/"lighting" regroup **never applies** (`bq/21f_cat_audio.txt`) |
| `novamart.top_products` (job `top_sellers`, 06:45 local) | yesterday, local day | status=1 | **none** | "Internal Test #4856" was in the top 50 on 45 of 55 days and top 5 on 28 (`bq/24c_top_products_1004856.txt`); reads `orders` only (multi‑line items hidden); no Redash consumer (`bq/50_dbq_readers.txt`) |
| `analytics.trending_daily` (job `trending`, 05:15 local) | rolling 30d (60d before commit `f563dea`, 2019‑12‑06; log flips `window_days` 60→30 on Dec 7 — `bq/33b_trending_runs.txt`) | status=1 | none | #1 is product 1004856 almost every day (`bq/33_trending.txt`); feeds the widget fallback |
| `/reports/brands` (`routers/reports.py`) | local month | status=1 | SKUs + denylist, maps `''`→`unbranded` | **not mounted** since commit `f1217a8` (Oct 26) — never served |

Dashboard time anchor: all Redash queries use `now()`; the data ends 2019‑12‑31, so running them today returns empty rolling windows. Reproductions in this run pin `now := 2019‑12‑31 23:59:59 UTC`.

### 4.4 Customer metrics

| Definition | Where | Rule | Value at 2019‑12‑31 | Trust |
|---|---|---|---|---|
| Nightly 30‑day actives | `analytics.kpi_daily` (`jobs/kpi_daily.py`, 06:15 local) | distinct `user_id`, `status=1`, trailing 30×24h from run time; includes QA user | 1,152 (`bq/23b_kpi_daily.txt`) | Fine as a trend; the Dec 16‑18 cliff (1,560→1,031) is the Nov 15‑17 surge leaving the window |
| KPI dashboard actives | Redash `daily_kpis` | per‑Eastern‑day distinct buyers, no status filter, −424242, −lucente/jetem | 44–75/day | Different metric (daily, not 30d) |
| Board actives | Redash `actives_board` | 30d, status ∉{0,2,3}, −test_users, −email heuristics | **0** (1,151 candidates all have `example.com` / `.example` emails — `bq/23_actives_board_repro.txt`) | Do not use; broken by placeholder emails |
| Contactable | view `analytics.contactable_users` | opt‑in AND real‑looking email AND not example domains | **0 rows** | Broken for the same reason; digest instead counts `email NOT LIKE '%@example.com'` = 40, including QA (`jobs/email_digest.py:50-52`, `bq/23c_digest_log.txt`) |
| Funnel users_active / sessions | `analytics.daily_funnel` (`jobs/funnel.py`, 06:20 local) | cart+order events in the 24h before the run, sessionized by inactivity gap (30 min → 120 min, commit `f915c1b`, Dec 14; log shows gap=120 from Dec 15 — `bq/42b_funnel_runs.txt`) | 308 users / 345 sessions | Ignores the `session` column; "day" = run date |
| Registered buyers | Redash `registered_conversion` | accounts→users by shared email → orders status=1 | 30 buyers / 18,155.71, 13 QA rows included (`bq/46c_registered_conv.txt`) | Only works because placeholder emails are unique; first version joined UUID to bigint and returned 0 (commit `d6e34c6` → `b975479`) |
| Signups | `users.created_at` | first touch, not registration | 15,093 / 11,294 / 12,562 (Oct/Nov/Dec) (`bq/46_users_signups.txt`) | `accounts` (30 rows, all created 2019‑12‑01 16:30 UTC) is the only true registration table; endpoint live Nov 27 – Dec 5 only |

Test/QA identity: `user_id 424242`, session `qa-smoke`, one 9.99 order every Wednesday (`bq/44b_qa_user.txt`); `analytics.test_users` contains only 424242; its account UUID is `cc27b436-d6f9-4e84-adaf-e716025dd369` (`bq/22e_accounts.txt`).

### 4.5 Refunds

- Two unrelated refund mechanisms: `POST /orders/{id}/refund` sets `status=3` without a payments row (commit `d87cb3d`); `POST /payments/gateway_refund` inserts `payments(gross=-amount, fee=0)` without touching the order (commit `c49a7bb`). Cancellations (`status=2`) are a third.
- `analytics.refunds_unified` (view, created by hand Dec 23) unions all three with `amount = orders.price` for cancels/refunds and the event month = `updated_at` month. Redash `refunds` therefore shows Nov 32 / 9,691.77 and Dec 59 / 18,848.93 (`bq/45c_refund_dashboard_repro.txt`), of which 9 rows / 1,843.59 are three webhooks replayed three times (`bq/13c_gateway_refunds.txt`).
- None of these flows reduce `statements`, `report_rows` (after the fact), or dashboard revenue for the original month.

---

## 5. System

### 5.1 Components

- **API** (`novamart/app.py`): mounted routers = `catalog`, `carts`, `orders`, `similar`, `payments_webhook`. Unmounted (code exists, no traffic possible): `reports` and `users` (dropped in commit `f1217a8`), `accounts` (dropped in commit `c49a7bb`). Evidence of their brief lives: 40 `user_email_updated` events on 2019‑10‑23 only; 30 `account_created` on 2019‑12‑01 only (`bq/12b_events_by_type.txt`).
- **DB** (`schema.sql` + DDL executed at runtime): `order_lines`, `payments.payment_ref`, `accounts`, `account_map`, `report_rows_intraday`, `top_products` and all `analytics.*` tables are created by `CREATE TABLE IF NOT EXISTS` inside request handlers or jobs, not by `schema.sql` (`orders.py:24-36`, `accounts.py:29-35`, each job's `main()`).
- **Logging** (`novamart/logutil.py`): `app.jsonl` → `novamart_logs.app_events`; `jobs.jsonl` → `novamart_logs.job_runs`; `db_queries.log` (every SQL statement with `[app]`/`[job]` tag, plus ad‑hoc `[engineer:*]` lines) → `novamart_logs.db_queries` (3.6M rows).
- **Warehouse**: `novamart.*` = `public.*` tables, `novamart_analytics.*` = `analytics.*`; copied by `jobs/warehouse_backfill.py` from `warehouse_manifest.json` (20 analytics tables, 12 public). Views were recreated in BigQuery SQL (`INFORMATION_SCHEMA.VIEWS`). Hand‑made tables that used `now()`/`CURRENT_DATE` show load‑time values (`blank_brand_products.captured_at`, `category_name_history.valid_from` = 2026‑08‑13 — `bq/21_blank_brand.txt`, `bq/21d_categories.txt`).
- **Dashboards**: Redash data source `novamart` (type `pg`) — Redash queries the serving Postgres replica, not BigQuery; each of the 9 dashboards has exactly one table widget over one query (`redash/dashboard_id_*.json`); no cached results (`latest_query_data_id: null`).

### 5.2 Scheduled jobs (local times from `crontab.txt`; observed UTC run times from `job_runs` — `bq/40_job_runs_summary.txt`)

| Job | Local | Writes | Reads | Mode | Failure impact |
|---|---|---|---|---|---|
| reconcile | 03:00 | app log warnings only | orders | – | none; 130 dup refs flagged nightly, never fixed |
| affinity (v1) | 03:30 | `analytics.product_affinity` (full rewrite) | cart_items 30d | overwrite | nothing reads it since Dec 6 |
| affinity_v2 | 03:45 | `analytics.product_affinity_v2` (full rewrite, `model_version='2.0.1'`) | cart_items, orders, products | overwrite | widget falls back to trending for everything; crashed Dec 3‑5 (`IndexError` on December seasonal factor — `bq/41_crashes.txt`, fixed commit `3dbe4d7`) |
| model_train | 04:15 | `analytics.model_registry` (append), `analytics.model_scores` (rewrite) | rec_decision_log random arm, affinity_v2 | overwrite | only matters if `REC_MODEL_VERSION=4.0.0` (it is 2.0.0) |
| price_suggest | 04:45 | `analytics.price_suggestions` (rewrite, 500 rows) | orders 14d | overwrite | nothing reads it |
| trending | 05:15 | `analytics.trending_daily` (delete+insert for today) | orders 30d status=1 | per‑day replace | widget fallback would serve yesterday's list (`MAX(day)`) |
| fraud_score | 05:45 | `analytics.order_risk` (append); `UPDATE orders SET status=6` | orders last 24h status=1 | mutates orders | if it fails, held orders stay in statements |
| daily_report | 06:00 | `report_rows` (append) | orders, order_lines, products, test_users | append | KPI dashboard day missing; never backfilled historically |
| kpi_daily | 06:15 | `analytics.kpi_daily` (append) | orders 30d | append | gap in series |
| funnel | 06:20 | `analytics.daily_funnel` (append) | cart_items, orders 24h | append | gap |
| monthly_statement | 06:30 on 1st | `statements` (append) | orders, payments | append | finance number missing; re‑run appends a second row for the month, which `statements_corrected`'s month join would then duplicate |
| top_sellers | 06:45 | `top_products` (append) | orders status=1 | append | none observed |
| reorder_forecast | 06:50 | `analytics.reorder_hints` (rewrite, 200 rows) | orders 14d | overwrite | advisory only |
| email_digest | 07:15 | `analytics.digest_log` (append) | orders 7d, users | append | gated by `ENABLE_DIGEST` in `deploy/cron.env`; silently did nothing Nov 28 → Dec 16 because it read `DIGEST_ON` (commits `c19a307` → `8dc520b` → `0bd4eac`); first run Dec 17 (`bq/23c_digest_log.txt`) |
| intraday_report | 12:00, 17:00 | `report_rows_intraday` (append) | same as daily_report | append | today's row on KPI dashboard stale |

Timing dependencies that matter: fraud_score (05:45) runs **before** daily_report (06:00) yet held orders still land in `report_rows` because status 6 is not excluded; model_train (04:15) must follow affinity_v2 (03:45); trending (05:15) must precede the day's widget traffic.

### 5.3 Airflow migration risks (commit `4bfcbe6`, not yet observable in logs)

- Every DAG uses a cron string equal to the *local* HH:MM from `crontab.txt` with no `timezone`/`start_date` tz; Airflow interprets these as UTC, so all jobs would run 4‑5 hours earlier than before (e.g. `intraday_report` at 12:00 UTC = 07:00 Eastern, when the "today" window is nearly empty).
- `intraday_report_dag.py` schedules only `0 12 * * *`; the 17:00 run was dropped.
- `warehouse_backfill_dag.py` is manual (`schedule=None`); the warehouse is a one‑shot copy as of 2019‑12‑31 and will not refresh on its own.

### 5.4 Serving: similar‑products widget (`routers/similar.py`)

- `GET /products/{pid}/similar`: 5% of users (sha256(uid) mod 20 == 0) get a deterministic shuffle of the first 500 product ids (`random` arm); otherwise read top‑5 `rec_pid` with `score >= 0` and `updated_at = MAX(updated_at)` from `analytics.product_affinity_v2` (version 2.0.0) or `analytics.model_scores` (4.0.0), cached in‑process 6h and invalidated when the table's `MAX(updated_at)` changes; if empty → top‑5 from latest `analytics.trending_daily` **without** the `EXCLUDED_SKUS` filter. Every decision is written to `analytics.rec_decision_log`.
- Version flag: `deploy/flags.env` `REC_MODEL_VERSION=2.0.0` (default also 2.0.0). Version 1.0.0 (table `product_affinity`, fallback = 7‑day bestsellers) served Oct 26 → Dec 6 (`bq/30_rec_log_by_version.txt`).
- Known logging/caching defects: random‑arm decisions were not logged Dec 17 16:50 → Dec 19 14:55 (commit `30e8907` → `a00f24c`; 1,372 `rec_served` app events vs 0 log rows; `model_registry.train_rows` stuck at 5,798 for two days — `bq/34b_rec_vs_app_events.txt`, `bq/31_model_registry.txt`); empty results were cached for 6h Dec 19 → 26 producing 25,091 `fallback/cache` rows (fixed commit `8ed2971`).

---

## 6. Data

### 6.1 Core tables (`novamart.*`) — what each column really means

- `orders` (9,127): `price` = order total (sum of lines); `product_id` = first line; `payment_ref` = gateway ref of the *first* callback (unique index only on `order_lines.payment_ref`, so the 130 pre‑Oct‑15 duplicates persist); `status` as in §3.3; `updated_at` changes on cancel/refund/hold/release.
- `order_lines` (2,284, from 2019‑11‑22): one row per callback; `payment_ref` unique; `session` is the storefront session id.
- `payments` (9,361 = 9,127 orders + 225 appended lines + 9 gateway refunds): `fee` is what the app computed at order time (2.9% [+0.30 after Nov 20]); `payment_ref` NULL for rows written before Nov 22 and for gateway refunds (7,077 NULLs — `bq/54c_payments_integrity.txt`); negative `gross` = refund.
- `users` (38,950): all attributes synthesized from id (`onboarding.py`); `email` is a placeholder for 100% of rows; `marketing_opt_in` is a hash (≈62% true).
- `products` (81,018): created on first sight with blank `category`/`brand` unless the view/feed carried them; `brand=''` for 17,442 products (causes: `ON CONFLICT DO NOTHING` + in‑process known‑id cache — `blank_brand_products.suspected_cause`; repair path added commit `ea0e97b`, upsert commit `d213f6e`); `list_price` = latest weekly feed value, not what customers paid; `cost_price`/`stock` are deterministic fakes (`onboarding.py:42-47`).
- `cart_items` (36,938): raw add events; removals delete rows (`carts.py:23-31`), so cart history is lossy.
- `report_rows` (6,923) / `report_rows_intraday` (2,358): snapshots; see §4.2. `statements` (3): see §4.1. `top_products` (2,396): see §4.3. `accounts`/`account_map` (30/30): registered‑accounts beta, Dec 1 only.

### 6.2 Analytics tables/views (`novamart_analytics.*`)

Produced by jobs: `product_affinity`, `product_affinity_v2`, `model_scores`, `model_registry`, `rec_decision_log` (667,850), `trending_daily`, `kpi_daily`, `daily_funnel`, `order_risk` (1,631), `price_suggestions`, `reorder_hints`, `digest_log`, `price_history` (1,400 rows; feed prices since Nov 18 only — `bq/42e_price_history.txt`).
Hand‑made (see §3.2): `test_users` (1 row), `blank_brand_products` (5,972‑row snapshot from Oct 21), `category_names` (135), `category_name_history` (6), `statement_overrides` (1), `statement_corrections` (1), `chargebacks` (3).
Views: `contactable_users` (0 rows), `refunds_unified` (91), `statements_corrected` (3), `statements_final` (3).

### 6.3 Logs (`novamart_logs.*`)

- `app_events` (1.57M): `jsonPayload.event` ∈ product_viewed 843k, rec_served 669k, cart_item_added 37k, duplicate_payment_ref 10.8k (reconcile warnings), order_created 9,127, order_callback_replayed 522, order_appended 225, order_cancelled 54, user_email_updated 40, account_created 30, order_refunded 28, price_feed_received 13, gateway_refund 9, statement_fee_mismatch 3 (`bq/12b_events_by_type.txt`).
- `job_runs` (978): one or two rows per job run; 3 `ERROR` rows (affinity_v2 crash). No daily_report run is missing (`bq/41c_daily_report_gaps.txt`).
- `db_queries` (3.6M): `textPayload` = `<ts> [<source>] statement: <sql> -- params: (...)`. Sources: `[app]`, `[job]`, `[engineer:dev|maya]`, `[engineer-backfill:dev|maya]` (`bq/51_dbq_sources.txt`). Use it to prove consumers: e.g. `analytics.product_affinity` last read by the app 2019‑12‑06 16:39:58; `analytics.price_suggestions` and `top_products` have zero app/job reads (`bq/50_dbq_readers.txt`).
- `db_queries_normalized` is a 1:1 view over `db_queries` (3,597,650 rows — `bq/56_dbq_normalized.txt`) presenting a BigQuery‑jobs‑style schema (`job_id`, `query`, `statement_type`, `user_email`, `creation_time`, …); filtered scans of it time out on the emulator, so all evidence in this document was taken from `db_queries.textPayload` directly.

### 6.4 Data quality register (verified)

| Issue | Scope | Evidence |
|---|---|---|
| Duplicate orders per payment_ref | 130 refs / 155 extra rows / $59.8k, Oct 1‑15 | `bq/14_dup_refs.txt`, `bq/14e_dup_payments.txt` |
| Gateway refund webhooks replayed ×3 | 3 orders, Dec 13/20/27 | `bq/13d_neg_payments.txt` |
| Placeholder emails | 100% of users | `bq/22_users_emails.txt` |
| Blank brand / blank category | 17,442 / 33,514 products; $84.8k / $294k lifetime | `bq/21c_blank_now.txt`, `bq/21h_cat_coverage.txt` |
| "Test" SKU 1002544 is a real Apple product | 139 orders / 88 buyers | `bq/20b_excluded_skus.txt` |
| Nov 15 zero orders, Nov 17 report capped | see §4.2 | `bq/17_nov15_outage.txt`, `bq/16_report_vs_orders.txt` |
| Held orders in dashboards but not statements | 12 orders / $40,213 | `bq/18_held_orders.txt` |
| Chargebacks synthetic & on now‑cancelled orders | 3 rows | `bq/10d_chargebacks.txt`, `db_queries` 2019‑12‑09 |
| `category_name_history.valid_from` in 2026 | 6 rows | `bq/21d_categories.txt` |
| `statements_corrected` month join would duplicate on statement re‑run | design | view definition |

---

## 7. Experimentation

### 7.1 Recommendation versions (the real `docs/rec_versions.md`)

| Version | Period | Scores from | Fallback | Share of decisions |
|---|---|---|---|---|
| 1.0.0 | 2019‑10‑26 → 12‑06 | `analytics.product_affinity` (co‑cart pairs, 30d, exp decay; −1 sentinel below 3 pairs from commit `fef5c96`) | 7‑day bestsellers | affinity 66,444 / fallback 326,186 (83% fallback) |
| 2.0.0 (table stamped 2.0.1) | 2019‑12‑06 → now | `analytics.product_affinity_v2` (pairs ×1 + conversions ×3, same‑category ×1.15, price‑ratio ×0.7, seasonal factor; Dec factor = 1.0 after crash fix) | `trending_daily` top‑5 | model 52,695 / fallback 207,959 / random 14,566 (76% fallback) |
| 4.0.0 (flag‑gated, never enabled) | trained nightly since 12‑15 | `analytics.model_scores` = v2 score × constant | same | 0 served |

(`bq/30_rec_log_by_version.txt`, `bq/30b_rec_log_daily.txt`)

### 7.2 Does the ML work? Assessment

- **Coverage is the binding constraint.** Only 449 base products have any non‑sentinel affinity score (948 pairs) because the graduation gate needs ≥3 co‑cart pairs in 30 days (`bq/32b_affinity_state.txt`). Hence ~3 in 4 widget impressions show the same five trending items, led by the internal test SKU (§1 #4).
- **v4 is not a model in effect.** Training label = "user placed any paid order after the impression" (not a click/purchase of a recommended item); features = [n_items (always 5), base price, base popularity, account age, organic flag]; `opt_in`/`stock` fetched but unused; scoring multiplies v2 scores by `(1 + 0.1·coef[n_items])`, a constant per night (`model_train.py:30-72`). Coefficients swing sign night to night (`bq/31_model_registry.txt`). Flipping `REC_MODEL_VERSION=4.0.0` would change nothing except the table read.
- **Random arm** (5% of users, deterministic by uid) is the only unbiased data; 14,566 logged decisions, minus the Dec 17‑19 logging gap. No holdout, no metric, no evaluation job exists in the repo.
- **Trending** is a popularity ranker over `orders` (not lines); switching 60→30 days on Dec 6 made the list churn faster (`docs/trending_notes.md`, verified `bq/33b_trending_runs.txt`).

### 7.3 Other "experiments"

- **Dynamic pricing** (`price_suggest`): shadow table of ±5% nudges around `list_price` by demand rank (above median units → +5%, else −5%); 500 rows nightly, 109 up / 386 down at Dec 31 (`bq/42d_price_sugg.txt`). Phase 2 on hold (commit `cca9b0d`); no reader (`bq/50_dbq_readers.txt`). `docs/pricing_status.md` is accurate.
- **Reorder hints** (`reorder_forecast`): `int(15.6 + 162.4/(velocity+1.8))` over the top‑200 14‑day velocities; K was 141.12 until commit `f85cdd2` (Dec 21). Hints are inversely related to velocity (51–102 units for velocities 0.07–2.71/day — `bq/42c_reorder.txt`). `docs/forecast_caveats.md` is accurate; advisory only.
- **Fraud scoring** (`fraud_score`): a price rule, not a model — `core = min(price/3000, 1)`, +15% each for new account / ≥3 orders in 24h; threshold history 0.90→0.70→0.85. Held 16 orders total; 4 released by hand on Dec 29 (`UPDATE … price < 2600`); 12 remain held, 10 of them with score exactly 1.0 (price ≥ $3,000) (`bq/18_held_orders.txt`, `bq/18c_risk_dist.txt`).
- **Registered‑accounts beta** (`/accounts`): 30 accounts created in one batch on 2019‑12‑01 16:30 UTC, endpoint removed from `app.py` on Dec 5; conversion dashboard only works via email join (§4.4).
- **Email digest**: top 7‑day product (which is 1004856 "Internal Test" or 1002544 on 5 of 15 days — `bq/23c_digest_log.txt`) to 40 "recipients".

---

## 8. Glossary

- **Appended order / order line** — a second gateway callback in the same `session` within 15 min is merged into the existing order (`orders.price += price`, new `order_lines` row) (commit `5d1300d`).
- **As‑published vs restated** — `novamart.statements` (snapshot at run time) vs `analytics.statements_final` (overrides + chargebacks) (`docs/restatement_policy.md`).
- **BRAND_DENYLIST / EXCLUDED_SKUS** — report/dashboard exclusions (`lucente`, `jetem`; 1004856, 1002544) (`constants.py`). Not applied by `top_sellers`, `trending`, `kpi_daily`, statements, or the widget fallback.
- **Chargeback** — row in `analytics.chargebacks`; subtracted from the order's month in `statements_final`; currently 3 hand‑inserted rows.
- **Contactable customer** — user in view `analytics.contactable_users` (opt‑in + real email); empty in practice.
- **Duplicate payment_ref** — same gateway ref on >1 `orders` row (pre‑2019‑10‑15 retries); flagged nightly by `reconcile`.
- **Effective vs intended version** — `rec_decision_log` columns: intended = flag value; effective = what was served (`'fallback'` when trending was used; `'1.0.0'` in the v1 era even for fallbacks).
- **Held order** — `orders.status = 6`, set by `fraud_score`; excluded from `status=1` metrics only.
- **Item rows** — the `order_lines` ∪ legacy `orders` CTE used by dashboards and `daily_report` since commit `92596dc`.
- **Local day / month** — America/New_York calendar window converted to UTC (`jobs/timeutil.py`); dashboards use `AT TIME ZONE 'America/New_York'`.
- **Placeholder email** — `user<id>@example.com` assigned on first sight (`catalog.py:39-42`); `cust<id>@gmail.example` for the 40 users updated Oct 23.
- **QA smoke account** — `user_id 424242`, session `qa-smoke`, account `cc27b436-d6f9-4e84-adaf-e716025dd369`; the only row in `analytics.test_users`.
- **Random arm** — 5% of users served a seeded shuffle of the first 500 product ids; training data for v4.
- **Report date** — the local business day a `report_rows` row describes; `created_at` is the run time (versions).
- **Sentinel score (−1)** — affinity pair seen fewer than `MIN_PAIRS=3` times; serving filters `score >= 0`.
- **Statement fee mismatch** — app warning when Σ`payments.fee` ≠ expected formula fee for the month.
- **Status codes** — 0 pending, 1 paid, 2 cancelled (was 4 before Oct 28), 3 refunded, 5 unused, 6 held.
- **Trending** — `analytics.trending_daily`: 30‑day unit count × e^(−0.05·days since last sale), ≥5 units, top 50 per day.
- **Tuesday batch** — weekly back‑office cancel/refund run at 16:00 UTC touching the oldest orders.

---

## Appendix

### A. How to answer "what was revenue in month X, and why" (procedure)

1. Read `novamart.statements` for the as‑published row, then `novamart_analytics.statements_final` for the restated row; explain the delta via `statement_overrides` and `chargebacks` (`bq/10*.txt`).
2. Recompute from `orders` with the statement rule (`status=1`, local month) and show the gap = orders cancelled/refunded/held after publication (`bq/11_recompute_month.txt`, `bq/12_status_changes.txt`).
3. Deduplicate `payment_ref` (ROW_NUMBER over `payment_ref ORDER BY id`) and quantify (`bq/14d_dup_inflation.txt`).
4. Decide whether the asker means finance revenue or dashboard revenue; if dashboard, apply QA/brand/SKU exclusions and item‑level counting (`bq/19_month_reconciliation.txt`).
5. Mention gateway refunds (`payments.gross<0`, de‑duplicated by order) and that they are not in any statement.

### B. Reproduction snippets (BigQuery, pinned `now := 2019‑12‑31 23:59:59 UTC`)

- Item rows CTE used by every dashboard reproduction: see header of `bq/24_best_sellers_repro.txt`.
- Best sellers: `bq/24_best_sellers_repro.txt`; brand: `bq/55_brand_rev_repro.txt`; category: `bq/55b_cat_rev_repro.txt`; daily KPIs: `bq/25b_daily_kpis_repro.txt`; board actives: `bq/23_actives_board_repro.txt`; registered conversion: `bq/46c_registered_conv.txt`; refunds: `bq/45c_refund_dashboard_repro.txt`.

### C. Metric‑definition change timeline (commit → effect)

| Date | Commit | Effect on numbers |
|---|---|---|
| 2019‑09‑15 | `2da4141` | initial: fee = gross×2.9%; report excludes status 0; dashboards UTC day, no filters; `REPORT_SCAN_CAP=500` |
| 10‑08 | `83fb3ed` | exclude SKUs 1004856, 1002544 from daily report |
| 10‑15 | `b676969` | order callbacks idempotent by payment_ref (stops duplicate orders) |
| 10‑25 | `ba1fbfa` | hide lucente from reports |
| 10‑26 | `f1217a8` | similar widget v1; `/reports`, `/users` unmounted |
| 10‑28 | `8f19718` | cancelled status 4→2; cancel endpoint |
| 11‑02 | `a92c96d` | statement fee = Σ payments.fee; Oct override inserted by hand |
| 11‑05 | `102c9b4` | DST‑safe local day windows (Nov 3 report not re‑run) |
| 11‑09 | `d213f6e` | price feed upserts (feeds Oct 7 – Nov 4 never updated existing prices) |
| 11‑12 | `fef5c96` | affinity −1 sentinel below 3 pairs |
| 11‑15 | `d87cb3d`, `795d273` | refunded status 3; `price_history` |
| 11‑16 | `14726e7` | `kpi_daily` 30‑day actives |
| 11‑18 | `11c0a42` | report excludes statuses 0,2,3 |
| 11‑19 | `1233af8` | report scans all rows (Nov 17 not re‑run) |
| 11‑20 | `12e1c68` | +$0.30 flat fee |
| 11‑22 | `5d1300d` | `order_lines`; same‑session merge; `payments.payment_ref` |
| 11‑27 | `b59f077`, `b567d9d` | QA user excluded (test_users + 424242 in dashboards); `/accounts` |
| 11‑30 | `2814b3d` | category dashboard + `category_names` |
| 12‑02 | `4a58d17`, `89666bf`, `cca9b0d` | flat fee in statement check; affinity v2 job; pricing phase 2 on hold |
| 12‑03 | `e4656fb` | fraud hold (0.90) |
| 12‑04 | `e10cb0c` | `contactable_users` view + KPI column |
| 12‑05 | `c49a7bb`, `92596dc`, `53f6f6c`, `3dbe4d7` | gateway refund webhook (`/accounts` unmounted); item‑level counting; fraud 0.70; v2 crash fix |
| 12‑06 | `f563dea`, `df4ed85` | trending 30d; widget v2 + random arm + version flag |
| 12‑08 | `a2e0013` | intraday snapshots; KPI dashboard reads `report_rows` instead of `orders` |
| 12‑09 | `cd559d3`, `8dc520b` | chargebacks + `statements_final`; digest flag fix |
| 12‑10/11 | `d6e34c6`, `2dde4f0` | registered conversion (broken join); board actives |
| 12‑12 | `33054cd` | versioned taxonomy (`category_name_history`) |
| 12‑14 | `a1946ff`, `f915c1b` | model_train v4; funnel gap 120 min |
| 12‑15 | `1169e40` | jetem denylisted; brand filter added to all dashboards |
| 12‑16/17/19 | `0bd4eac`, `30e8907`, `a00f24c` | digest reads cron.env; widget refactor drops random logging; restored + cache |
| 12‑19/24 | `686a5d6`, `3eced24` | revenue widget (double count) → fixed |
| 12‑21 | `f85cdd2`, `b975479` | reorder K refit; registered conversion via email |
| 12‑23 | `a3bffec` | `refunds_unified` + refunds dashboard |
| 12‑26 | `8ed2971` | cache invalidation on table refresh |
| 12‑29 | `1cb8721` | fraud 0.85; held orders < $2,600 released by hand |
| 2020‑01‑03/04/05 | `41e3537`, `4bfcbe6`, `5ae1182` | Redash, Airflow, warehouse backfill |

### D. Files in this run folder

- `novamart_tribal_knowledge.md` — this document.
- `git_log.txt`, `git_full_history.patch` — full commit history with diffs.
- `old_dashboards/*.sql` — dashboard SQL as of commit `41e3537^`.
- `redash/*.json` — Redash dashboards, queries, data sources (read‑only API pulls).
- `bq/NN_*.txt` — every warehouse query run, with results.
- `bqq.py` — the read‑only REST query helper used (the `bq` CLI crashes on this emulator's responses).

### E. Open questions / things not verifiable from the sources

- Whether Airflow DAGs were given a timezone at deploy time (no `job_runs` after 2019‑12‑31).
- Whether the Nov 15 zero‑order day was a checkout outage or a gateway outage (no error logs in `app_events`).
- Why 8 distinct users each bought a $2,999.99 item within four hours on Dec 3 (fraud ring vs. promotion) — `order_risk` only records price‑based scores.
- Who consumes `top_products`, `reorder_hints`, `price_suggestions`, `digest_log` outside this repo (no reads in `db_queries`).
