# NovaMart Tribal Knowledge Document

- **Run started:** Mon Oct 5 17:39:37 UTC 2026
- **Run UUID:** `792da7a9-8d28-4fe9-9d45-01da8ed828f5`
- **Sources used:** git repo `novamart` pinned at commit `5ae1182` (112 commits of history); BigQuery warehouse `novamart-warehouse` (datasets `novamart`, `novamart_analytics`, `novamart_logs`) via the local emulator; Redash at `http://localhost:5054` (9 dashboards, read-only).
- **Intermediate research notes** (same directory): `notes_codebase_finance.md`, `notes_warehouse.md`, `notes_redash.md`, `notes_ml_jobs.md`.

---

## 1. Summary

NovaMart is an e-commerce company whose business data lives in three places: a Python/FastAPI monolith + nightly batch jobs (git repo, HEAD `5ae1182`), a Postgres application database exported to BigQuery (`novamart` app tables, `novamart_analytics` analytics tables/views, `novamart_logs` log exports), and 9 Redash dashboards. The business window covered by the data is **2019‑09‑15 → 2019‑12‑31** (orders, logs, job runs), with a platform migration (Redash `41e3537`, Airflow `4bfcbe6`, warehouse backfill `5ae1182`) in early January 2020.

The ten facts a tenured insider knows:

1. **Money is in dollars, never cents.** `orders.price`, `payments.gross/fee/net` are NUMERIC dollars rounded with `round(x,2)` (`novamart/routers/orders.py`).
2. **There are four different "revenues"** that never reconcile by design: the daily report (`report_rows`, excludes cancelled/refunded/test/QA/two hidden brands), the monthly statement (`statements`, status=1 only, **no exclusions at all**), the restated finance view (`analytics.statements_final` = statements + overrides − chargebacks), and dashboards that query raw orders with **no status filter**. For "what was revenue in month X", current finance policy says use `analytics.statements_final` (`docs/restatement_policy.md`, commit `a576d0d`): Sep 2019 net **2,623.64**, Oct 2019 net **1,191,085.36** (restated from the published 1,194,652.79), Nov 2019 net **1,069,286.09**. **December 2019 has no statement** — the monthly job last ran 2019‑12‑01 (for November) and the Airflow migration happened before 2020‑01‑01's run was observed.
3. **Refunds are three disjoint systems**: app refund = order status flip to 3 with no money reversal; gateway refund webhook = negative `payments` row with no status change (`c49a7bb`, "gateway is source of truth for money"); chargebacks = `analytics.chargebacks`, subtracted only in `statements_final`. `analytics.refunds_unified` unions the first two — and currently **triple-counts $614.53** because three December refunds were each replayed weekly (orders 3762/3763/3776).
4. **Fee math changed twice.** Per‑transaction fee: 2.9% until 2019‑11‑20, then 2.9% + $0.30 per payment row (`12e1c68`). Statement fee: computed as 2.9% of monthly gross (rounded once) until `a92c96d` (2019‑11‑02), then the sum of actually collected per‑payment fees. October 2019's fee was off by $0.14 due to rounding and was corrected via `analytics.statement_overrides` (`4a58d17`).
5. **The daily report silently undercounted** two eras: a 500‑order scan cap dropped ~$91k on the 2019‑11‑17 flash sale (fixed `1233af8`), and the DST fall‑back day 2019‑11‑03 lost an hour (fixed `102c9b4`). Also 2019‑11‑15 is a genuine zero‑order outage day and 2019‑12‑31 has no report row. These holes are permanent in `report_rows`.
6. **"Active customers" has three incompatible definitions** (documented in `docs/metrics_definitions.md`, `dd0c8fc`): kpi_daily's trailing‑30d distinct status=1 buyers with no exclusions; daily_kpis dashboard's per‑day distinct buyers with QA/brand exclusions and no status filter; actives_board's 30‑day non‑cancelled buyers with aggressive test‑account scrubbing. They are all "right" per their own definition and all different.
7. **The recommendation system serves affinity v2 ("2.0.0", table stamped 2.0.1)**; v1 is a zombie still computed nightly but unread since `df4ed85`; model v4 (logistic regression on random‑arm data, `a1946ff`) trains nightly but is **never served**, and its score is a constant multiple of v2's, so it couldn't change rankings anyway. 76% of pairs in both affinity tables carry the **sentinel score −1 = "not enough data"**, which serving must filter out (`fef5c96`).
8. **Fraud auto‑hold is a one‑way door.** A nightly heuristic (`e4656fb`) flips risky status‑1 orders to status 6; thresholds moved 0.90→0.70→0.85. Commit `1cb8721` *promises* to release held orders under $2,600 but the diff only changes the constant — 12 orders worth **$40,213** sit permanently in status 6, excluded from statements but still inside the daily report.
9. **Dynamic pricing is shadow‑only** (`cca9b0d`, `docs/pricing_status.md`) and **reorder hints are advisory with an inverse‑velocity formula** (slower sellers get bigger hints, `docs/forecast_caveats.md`) — neither should drive decisions.
10. **The warehouse backfill (`5ae1182`) exports 32 tables but no views** per `novamart/jobs/warehouse_manifest.json`; the restatement/refund views exist in the warehouse because they were recreated there, but any pipeline consuming the manifest alone misses them. The Airflow migration (`4bfcbe6`) also **silently dropped the 17:00 intraday report run**.

---

## 2. Why this project

- **Bus factor.** Every number NovaMart reports is shaped by undocumented history: fee eras, status‑code renumbering (cancelled was 4, became 2 in `8f19718`), exclusion lists added incrementally (`83fb3ed`, `b59f077`, `ba1fbfa`, `1169e40`, `adbcb7e`), and one‑off audit corrections (`4a58d17`). None of this is discoverable from the current schema; it lives in commit messages, `docs/*.md`, and the query log.
- **Platform migration risk.** The company just moved cron→Airflow, ad‑hoc SQL→Redash, and prod Postgres→BigQuery (`4bfcbe6`, `41e3537`, `5ae1182`, `d398b0d`). Migrations like these are exactly when definitions silently fork (the dropped 17:00 intraday run already proves it). A written record of "which table is the source of truth for which number" is the only defense.
- **The goals in the brief** map directly: Phase 1 (finance numbers end to end) → §3–§4 and Appendix A; Phase 2 (product/customer analytics, when not to trust a dashboard) → §4 and Appendix B; Phase 3 (ML systems and batch jobs, do they work, how to modify safely) → §5, §7 and Appendix C.
- **Concrete payoffs already found:** a $134k hole in November's `report_rows`, a triple‑counted refund feed, a dead "release held orders" promise, a dead‑code QA exclusion in the brand dashboard, and an exec revenue widget whose history of double counting (`686a5d6` → `3eced24`) explains past "revenue dipped then recovered" confusion.

---

## 3. Business understanding

### 3.1 What the business is
An online retail marketplace: a catalog of **81,018 products** (title, category, brand, vendor, list/cost price, stock — `novamart.products`) sold to **38,950 registered users** (`novamart.users`), with carts (`cart_items`), orders (`orders`, `order_lines`), and payments processed by an external gateway (`payments`, `novamart/routers/payments_webhook.py`). Catalog data arrives from vendor feeds (`novamart/routers/catalog.py`; price upsert fixed in `d213f6e`, list‑price history recorded in `analytics.price_history` per `795d273`, blank brands repaired on ingest per `ea0e97b`).

### 3.2 Scale and timeline (verified in warehouse)
- Orders: 9,127 total — 9,033 completed (status 1, $2,860,063.26), 54 cancelled (2), 28 refunded (3), 12 fraud‑held (6, $40,213.29). Query: `SELECT status, COUNT(*), SUM(price) FROM novamart.orders GROUP BY status`.
- Signups by month (`novamart.users.created_at`): 2019‑09: 1, 2019‑10: 15,093, 2019‑11: 11,294, 2019‑12: 12,562.
- Published monthly statements (`novamart.statements`): Sep gross 2,702.00 / Oct 1,230,332.43 / Nov 1,101,397.01. Restated (`analytics.statements_final`): Oct gross 1,226,764.86, net 1,191,085.36.
- Activity log window: `novamart_logs.db_queries` spans 2019‑09‑16 → 2019‑12‑31 (3,597,650 queries; actors: `app@novamart.sim` 3.27M, `job@novamart.sim` 331k, four human engineer accounts ~190 queries).

### 3.3 How an order becomes money (end to end)
1. The payment gateway calls `POST /orders` with `{ts, uid, pid, price, ref, session}` (`novamart/routers/orders.py:14–111`). The app writes an `orders` row (status 0→1), an `order_lines` row, and a `payments` row (`gross=price`, `fee`, `net=price−fee`).
2. **Idempotency** by `payment_ref` since `b676969` (2019‑10‑15); before that, gateway retries created duplicate orders (10,766 `duplicate_payment_ref` warnings and 522 `order_callback_replayed` events in `novamart_logs.app_events`).
3. **Same‑session merge** since `5d1300d` (2019‑11‑22): a second callback within 15 minutes for the same user+session **adds to `orders.price`** and appends another `order_lines` + `payments` row. Consequence: after 2019‑11‑22 `orders.price` is an order *total*, `payments` is per *line* (so the $0.30 flat fee applies per line), and `orders.product_id` only reflects the first line.
4. Cancellation (`8f19718`) and refund (`d87cb3d`) endpoints flip `orders.status` to 2/3 — **no payments reversal rows are written**.
5. The gateway refund webhook (`c49a7bb`, `novamart/routers/payments_webhook.py:11–21`) writes `payments(gross=−amount, fee=0, net=−amount)` and **does not touch order status**.
6. Nightly jobs aggregate into `report_rows` (daily), `report_rows_intraday` (12:00/17:00 snapshots), `statements` (monthly), `analytics.kpi_daily`, etc. All reporting tables are **append‑only**; consumers must take the latest `created_at` version per date (this is what the Redash queries do after the `3eced24` fix).
7. Finance restatements happen in analytics, never in `statements`: `statement_overrides` → view `statements_corrected` → minus `chargebacks` → view `statements_final` (`cd559d3`, `a576d0d`).

### 3.4 Organizational decisions encoded in code
- **Partnership‑sensitive brands `lucente` and `jetem` are hidden** from reports and dashboards (`ba1fbfa` "hide lucente from reports per partnerships", `1169e40`) — but *not* from monthly statements.
- **QA artifacts live in prod**: numeric user `424242` (in `analytics.test_users`, 14 orders), test SKUs `1004856`/`1002544` (`83fb3ed`), an accounts‑beta QA UUID `cc27b436-d6f9-4e84-adaf-e716025dd369` (`adbcb7e`), ~40 users with `@gmail.example` emails.
- **Accounts beta**: a new UUID‑keyed `accounts` table (30 rows) bridged to legacy numeric `users` via `account_map` / email (`b567d9d`, dashboards fixed in `b975479`).
- **Dynamic pricing was built and then halted by exec/legal review** (`cca9b0d`, `docs/pricing_status.md`); prices actually come from the vendor feed.

---

## 4. Metrics

### 4.1 Revenue — "what was revenue in month X, and why"

**The tenured‑person answer:** quote `analytics.statements_final` for finance, and explain the deltas to every other surface.

| Month (NY tz) | payments Σgross | `statements` gross/net | `statements_final` gross/net | Σ`report_rows` revenue |
|---|---|---|---|---|
| 2019‑09 | 2,702.00 | 2,702.00 / 2,623.64 | 2,702.00 / 2,623.64 | 2,702.00 |
| 2019‑10 | 1,230,332.43 | 1,230,332.43 / 1,194,652.79 | 1,226,764.86 / **1,191,085.36** | 1,201,082.08 |
| 2019‑11 | 1,101,397.01 | 1,101,397.01 / 1,069,286.09 | 1,101,397.01 / 1,069,286.09 | 966,974.33 |
| 2019‑12 | 590,698.63 | **none** | **none** | 535,561.72 |

(Queries in `notes_warehouse.md` §8; verified directly against `novamart.statements` and `analytics.statements_final`.)

Why the columns differ:
- **statements vs payments:** identical when bucketed by America/New_York month — statements use NY‑local month windows (`novamart/jobs/timeutil.py`, `monthly_statement.py:26–46`), include status=1 only, and include **everything** (QA user, test SKUs, hidden brands).
- **statements_final vs statements:** Oct fee override −$0.14 (per‑order rounding audit, `statement_overrides`, `4a58d17`, `docs/restatement_policy.md`) and −$3,567.57 of chargebacks (3 rows in `analytics.chargebacks`, mapped to the original orders' NY month, `cd559d3`). Policy (`a576d0d`): historical decks match `statements`; current finance uses `statements_final`.
- **report_rows vs statements:** daily report excludes cancelled/refunded orders, test SKUs, test users, lucente/jetem (`novamart/jobs/daily_report.py:28–65`), *plus* the November holes: 2019‑11‑15 total outage (zero orders), 2019‑11‑17 flash sale scan‑capped at 500 orders (~$91,490 lost; `job_runs` logged `orders_scanned: 500`; fixed by `1233af8` on 2019‑11‑19), DST hour lost on 2019‑11‑03 (fixed `102c9b4`). **Never backfill‑compare report_rows to statements without this list.**
- **No December statement:** `monthly_statement` runs on the 1st at 06:30 for the prior month; the last run in `job_runs` is 2019‑12‑01. Dec 2019 revenue must be derived from `payments`/`orders` directly (Σ payments Dec = 590,698.63 NY‑tz).

**Fee eras** (needed to sanity‑check any fee number):
- Transaction fee: `round(price × 0.029, 2)` until 2019‑11‑20; `round(price × 0.029 + 0.30, 2)` per payment row after (`12e1c68`). The flat 30¢ applies **per line** after order merging (`5d1300d`).
- Statement fee: `round(month_gross × 0.029, 2)` until `a92c96d` (2019‑11‑02); thereafter Σ collected `payments.fee`. The era‑aware expectation check with `FEE_CHANGE_AT = 2019‑11‑20 00:00 ET` landed in `4a58d17` (`monthly_statement.py:13,36–42`); November's in‑place fee fix left a delta‑0 audit row in `analytics.statement_corrections` ("processor fee change audit correction") and `statement_fee_mismatch` events in `app_events` (31,940.51 expected vs 32,110.92 collected).

### 4.2 Refund metrics
`analytics.refunds_unified` (added with the refunds dashboard, `a3bffec`) = status‑2 orders ('order_cancelled') ∪ status‑3 orders ('order_refunded') ∪ negative `payments` rows ('gateway_refund'). Caveats:
- App refunds remove **100%** of an order from reports even if the gateway refunded partially; gateway refunds never flip status, so those orders stay fully counted in statements.
- **Known data bug:** orders 3762/3763/3776 each have the *same* negative payment inserted 3× (Dec 13/20/27 weekly replays) → the refunds dashboard overstates December gateway refunds by $1,229.06 (counts $614.53 three times each). Verify: `SELECT order_id, COUNT(*) FROM novamart.payments WHERE gross < 0 GROUP BY order_id HAVING COUNT(*) > 1`.
- Chargebacks are **not** in refunds_unified; they only hit `statements_final`.

### 4.3 Product metrics (best sellers, brand, category)
- **best_sellers dashboard (Redash q9):** top 20 by revenue, rolling 7×24h from `now()`, per‑item via `order_lines` with a legacy header fallback for pre‑2019‑11‑22 orders (`92596dc` pattern), excludes user 424242 + lucente/jetem, **no order‑status filter** (cancelled/refunded revenue included — documented deliberately in `docs/dashboard_notes.md`, `a9a4b0b`).
- **brand_revenue (q8)** and **category_revenue (q6):** rolling 30d, same fallback and exclusions; brand_revenue also "excludes" the QA UUID via `user_id::text NOT IN (...)` which is **dead code** (orders.user_id is numeric, never a UUID — `adbcb7e` was a no‑op). Category names resolve via time‑versioned `analytics.category_names` + `category_name_history` (`2814b3d`, `33054cd`); the tiebreak `ORDER BY valid_from DESC, source_priority DESC` lets stale history rows beat corrections with equal valid_from.
- **top_products table** (nightly `top_sellers` job, `9a51155`): *yesterday*, NY day, status=1, ranked by **order‑row count** (not order_lines → undercounts multi‑item orders), append‑only. It will **never** match the best_sellers dashboard; that's expected (`docs/dashboard_notes.md`).
- **units everywhere = `COUNT(*)` of line rows** — there is no quantity column; multi‑qty purchases are invisible.
- **Catalog hygiene caveats:** 33,514 products with blank category and 17,442 with blank brand (`analytics.blank_brand_products` documents causes); blank brands get repaired on later feed events (`ea0e97b`) but history isn't rewritten.

### 4.4 Customer metrics
- **Signups** = `novamart.users.created_at` (bootstrap rows can also be created from unknown numeric uids via `b567d9d`). Accounts beta = `accounts` (30 UUID rows) + `account_map`.
- **Active customers — three definitions, know which one you're quoting** (`docs/metrics_definitions.md`, `dd0c8fc`):
  1. `analytics.kpi_daily.active_customers_30d` (job `kpi_daily.py`, `14726e7`): trailing‑30d distinct status=1 buyers, **no test exclusions**.
  2. daily_kpis dashboard (q7): per‑NY‑day distinct buyers from report tables + orders joined via `orders.product_id` (drops multi‑line orders whose header pid is NULL), excludes 424242 + lucente/jetem, no status filter.
  3. actives_board (q3, `2dde4f0`): distinct users with a non‑cancelled order in the last 30 days, scrubbing `analytics.test_users`, novamart/example/test email domains and qa|test|demo|internal|seed|sandbox|smoke tokens.
- **Contactable customers:** `analytics.contactable_users` view (opt‑in + "valid" email domain, excludes example.* domains) — **currently returns 0 rows** because every user email in the dataset is `@example.com`/`@gmail.example`. The daily KPI "contactable" number (`e10cb0c`) is therefore 0/meaningless, and the view has no definition in the repo (prod‑only object).
- **registered_conversion dashboard (q4,** `d6e34c6`, fixed `b975479`): accounts‑beta buyers via email join to legacy users; sums header `o.price` (double counts merged orders if lines were also summed elsewhere), status=1 only, no QA exclusions; email joins can fan out on shared emails.

### 4.5 When not to trust a dashboard (quick reference)
| Dashboard | Trust caveat |
|---|---|
| revenue_widget (2) | Correct post‑`3eced24` snapshot dedup, but **no QA/brand exclusions** — structurally higher than daily_kpis; history before 2019‑12‑24 double counted (`686a5d6` bug). |
| daily_kpis (9) | "orders" column is actually **units**; customer counts drop multi‑line orders; contactable is always 0. |
| best_sellers (7) / brand (8) / category (6) | No status filter; rolling windows ≠ calendar days; brand's UUID exclusion is dead code; units = line counts. |
| refunds (1) | Triple‑counted December gateway refunds; chargebacks absent. |
| statements_final (5) | Correct for finance; just remember old decks were cut from `statements` (pre‑restatement). |
| actives_board (3) vs daily_kpis actives | Different definitions — never compare directly. |
| registered_conversion (4) | No QA exclusions; email fan‑out risk. |

---

## 5. System

### 5.1 Components
- **App:** FastAPI monolith `novamart/app.py`; routers: `orders` (create/cancel/refund), `payments_webhook`, `carts`, `catalog` (vendor feed), `users`/`accounts`, `similar` (rec serving), `reports` (**dead code** — the brand‑sales endpoint `193f22d` was unwired from `app.py` since `f1217a8`).
- **Database:** Postgres (`schema.sql`): `public` app tables + `analytics` schema. Mirrored to BigQuery datasets `novamart` / `novamart_analytics` by the backfill DAG (`5ae1182`): per‑table `gcloud sql export csv` → `bq load --replace`, 32 tables per `novamart/jobs/warehouse_manifest.json`, **views excluded**.
- **Scheduling:** cron (`crontab.txt`) until `4bfcbe6` migrated to 15 Airflow BashOperator DAGs (`airflow/dags/`). The nightly order (NY‑relevant, times UTC): 03:00 reconcile → 03:30 affinity → 03:45 affinity_v2 → 04:15 model_train → 04:45 price_suggest → 05:15 trending → 05:45 fraud_score → 06:00 daily_report → 06:15 kpi_daily → 06:20 funnel → 06:30 monthly_statement (1st) → 06:45 top_sellers → 06:50 reorder_forecast → 07:15 email_digest → 12:00 (+17:00, **dropped in Airflow**) intraday_report. Dependencies are **by clock time only** — fraud mutates orders 15 minutes before daily_report reads them.
- **Dashboards:** Redash (`41e3537`), 9 dashboards, one query each, over the Cloud SQL replica (`docs/data-access.md`, `d398b0d`).
- **Logging:** structured app logs → `novamart_logs.app_events` (1.57M rows); job telemetry → `job_runs` (978 rows; the only ERRORs ever are 3 `affinity_v2` crashes, 2019‑12‑02..04); every DB statement → `db_queries` (3.6M) with `db_queries_normalized` view parsing actor + SQL (actors: app, job, 4 engineers).

### 5.2 Order/payment semantics (statuses)
`orders.status`: 0=pending, 1=completed, 2=cancelled (**was 4 before `8f19718`**), 3=refunded (`d87cb3d`), 5=legacy exclusion in reconcile (unexplained, `reconcile.py`), 6=fraud‑held (`e4656fb`). `payments` has **no status**; refunds are negative‑gross rows (`c49a7bb`).

### 5.3 Batch jobs — what breaks when they fail
| Job | Output | If it fails / known failures |
|---|---|---|
| reconcile (03:00) | log‑only dup `payment_ref` flags | Log noise only; batch 100→200 (`030d841`); moved into backup window (`388370b`) → slow runs. |
| daily_report (06:00) | `report_rows` (append) | Hole in dashboards (revenue_widget closed days, daily_kpis). Known holes: 2019‑11‑03 DST hour, 2019‑11‑15 outage, 2019‑11‑17 scan cap, 2019‑12‑31 missing. |
| intraday_report (12:00) | `report_rows_intraday` | "Today" tile goes stale; 2 snapshots/day historically (17:00 run dropped by Airflow migration). Never SUM across snapshots — dedup by MAX(created_at). |
| monthly_statement (06:30/1st) | `statements` (append) | Finance has no month row (December 2019 is actually missing). Era‑aware fee check (`4a58d17`). |
| kpi_daily (06:15) | `analytics.kpi_daily` | Board actives trend gaps. |
| funnel (06:20) | `analytics.daily_funnel` | Sessionized on trailing 24h from run time; gap 30→120 min on 2019‑12‑14 (`f915c1b`) = series discontinuity. |
| top_sellers (06:45) | `novamart.top_products` | Homepage/ops list stale. |
| affinity / affinity_v2 (03:30/03:45) | `analytics.product_affinity(_v2)` | Rec widget falls back to trending (`rec_decision_log.fallback_reason='no_scores'`). v2 crashed Dec 2–4 2019 (`IndexError: SEASONAL_FACTORS[t.month-1]`, fixed `3dbe4d7`). v1 is a zombie — safe to decommission after confirming no readers (`docs/affinity_lineage.md`). |
| model_train (04:15) | `analytics.model_scores`, `model_registry` | Nothing user‑visible — never served. |
| fraud_score (05:45) | `analytics.order_risk` + `orders.status=6` | Fraud holds stop; **mutates orders** — the only nightly job that writes app tables. |
| price_suggest (04:45) | `analytics.price_suggestions` (rewrite) | Nothing — zero readers (shadow). |
| reorder_forecast (06:50) | `analytics.reorder_hints` (rewrite) | Advisory only; **not finance‑grade** (`442b135`, `docs/forecast_caveats.md`). |
| email_digest (07:15) | `analytics.digest_log` | Was dark 2019‑11‑28 → 12‑16 due to env‑flag mismatch chain (`c19a307`→`8dc520b`→`0bd4eac`); "sends" nothing, only logs. |
| trending (05:15) | `analytics.trending_daily` | Homepage + rec fallback degrade; window 60→30d on 2019‑12‑06 (`f563dea`) churned rankings; README stale (`8584613`). |
| warehouse_backfill (manual DAG) | BigQuery datasets | Analysts see stale warehouse; views not exported (manifest). |

### 5.4 Safe‑modification notes (Phase‑3 final goal)
- All reporting tables are **append‑only, versioned by `created_at`** — reruns are safe *if* consumers dedup (Redash queries do; naive SQL doesn't).
- Rerunning KPIs via `scripts/rerun_kpis.py` is a **trap**: it calls `apply_discounts` with the legacy default `cap=0.40` instead of `DISCOUNT_CAP=0.25` (`35c581e`, `novamart/jobs/discounts.py`) — don't use it without passing the constant.
- Serving flags are deploy‑time: `deploy/flags.env` `REC_MODEL_VERSION` (flip = redeploy, and watch the score cache: fixed only in `8ed2971` to key by (table,pid) + epoch invalidation).
- The sequencing hazard: anything you add between 05:45 and 06:00 UTC races fraud_score's `UPDATE orders`.
- `db_queries_normalized` is the audit trail — any historical "who computed what" question can be answered from it (e.g., the engineer backfill accounts show the warehouse backfill activity).

---

## 6. Data

### 6.1 Datasets and source‑of‑truth map
| Number | Source of truth | NOT the source of truth |
|---|---|---|
| Monthly revenue/fee/net (current finance) | `novamart_analytics.statements_final` (view) | `novamart.statements` (pre‑restatement; use only to reproduce old decks per `a576d0d`) |
| Money movements | `novamart.payments` (incl. negative refunds; `c49a7bb`) | `orders.status` (no money), `refunds_unified` (triple‑count bug) |
| Daily product revenue (operational) | `novamart.report_rows` latest version per date | Σ over all versions (reruns), `report_rows_intraday` (partial days, 2 snapshots) |
| Order facts | `novamart.orders` + `order_lines` (lines only exist from 2019‑11‑22; 100% of Sep/Oct and 92% of Nov orders have no lines — always use the NOT EXISTS legacy fallback, `92596dc`) | `orders.product_id` alone (first line only) |
| Customers | `novamart.users`; beta: `accounts` + `account_map` | email joins (fan‑out) |
| Rec scores served | `analytics.product_affinity_v2` (version stamp 2.0.1 ≙ serving alias 2.0.0) | `product_affinity` (zombie), `model_scores` (never served) |
| Rec decisions / experiment data | `analytics.rec_decision_log` (668k rows) | app logs alone (Dec 17–19 random‑arm hole) |
| Fraud | `analytics.order_risk` + `orders.status=6` | — |
| Job health | `novamart_logs.job_runs` (`jsonPayload.job/event`) | — |
| Historical query audit | `novamart_logs.db_queries(_normalized)` | — |

### 6.2 Schema essentials
- `novamart.orders(id, user_id, product_id, price, payment_ref, status, created_at, updated_at)` — dollars.
- `novamart.payments(order_id, gross, fee, net, created_at, payment_ref)` — one row per line post‑merge; negative rows = gateway refunds (fee=0).
- `novamart.order_lines(order_id, product_id, price, session, payment_ref, created_at)` — begins 2019‑11‑22; where present, Σ lines.price = orders.price (verified).
- `novamart.statements(month 'YYYY‑MM', gross, fee, net, orders_count)`; `analytics.statement_overrides` (1 row: Oct fee), `statement_corrections` (1 row: Nov delta‑0 audit marker), `chargebacks` (3 rows, $3,567.57, all October orders).
- `report_rows(_intraday)(report_date, product_id, units, revenue, created_at)` — append‑only snapshots.
- Views (verbatim SQL in `notes_warehouse.md`): `statements_corrected` = statements ⟕ overrides with COALESCE; `statements_final` = corrected − chargebacks by NY order‑month; `refunds_unified` = status 2/3 orders ∪ negative payments; `contactable_users` = opt‑in + email‑domain filter (0 rows in practice); `db_queries_normalized` = regex‑parsed query log.

### 6.3 Known data quality issues (checklist before any analysis)
1. QA user 424242 + test SKUs 1004856/1002544 + `@gmail.example` users pollute raw tables (statements include them).
2. lucente/jetem excluded from reports/dashboards, present in statements/payments.
3. `report_rows` holes: 2019‑11‑03 (partial), 2019‑11‑15 (outage/zero), 2019‑11‑17 (~$91k capped), 2019‑12‑31 (missing).
4. Duplicate negative payments on orders 3762/3763/3776 (weekly replays ×3).
5. Fraud‑held $40,213 excluded from statements but inside daily reports.
6. Pre‑idempotency (before 2019‑10‑15) duplicate orders flagged nightly by reconcile but never cleaned.
7. 33,514 blank categories / 17,442 blank brands in products; `category_name_history` has future‑dated rows (2026‑08‑13).
8. 76% of affinity pairs are sentinel −1 ("not enough data"); never average scores without filtering `score >= 0`.
9. `report_rows_intraday` has 2 snapshots/day (17:00 & 22:00 UTC) until Airflow dropped the 17:00; the 22:00 one is still a partial NY day.
10. December 2019 statement does not exist.

---

## 7. Experimentation

NovaMart has exactly **one** experiment framework: the recommendation **random data‑collection arm**, introduced in `df4ed85` (2019‑12‑06).

- **Assignment:** deterministic hash bucketing — `int(sha256(uid)[:8],16) % 20 == 0` → **5% of users** always get the random arm (`novamart/routers/similar.py`). The "random" slate is a seeded shuffle (`uid:session:pid`) of the first 500 product ids — deterministic per request context, exploration not uniform over the full catalog.
- **Logging:** every rec request writes `analytics.rec_decision_log(ts, user_id, base_pid, items, intended_version, effective_version, rec_source, fallback_reason, arm)`. Verified distribution (668k rows): v1 era 392,630 requests (326,186 of them fell back on `no_scores` — **83%**); v2 era: 31,268 clean + 21,427 cache‑served vs 182,868 `no_scores` + 25,091 `cache` fallbacks (**~76% of v2‑intended traffic fell back**); `arm='random'`: 14,566.
- **Known log holes:** the `30e8907` refactor dropped random‑arm logging; restored `a00f24c` → **no random‑arm rows Dec 17–19, 2019**. Any off‑policy analysis must exclude or impute that window.
- **The consumer of the experiment** is `jobs/model_train.py` (`a1946ff`): nightly logistic regression trained only on `arm='random'` rows. Caveats that make it unfit to judge "does the model work": label = *any* later status‑1 order by the user (label leakage, not slate‑attributable conversion); features are `[n_items, price/1000, popularity/100, min(age/60,1), organic]` (README's claimed region/device/stock features don't exist); and the final `model_scores = affinity_v2_score × (1 + 0.1·w)` is a **constant multiplier** — v4 ranking ≡ v2 ranking by construction. `model_registry` holds 17 daily rows, all version 4.0.0 (Dec 15–31). `docs/rec_versions.md` (`4396fbb`) is literally "TBD".
- **Judgement (Phase‑3 goal):** the serving plumbing works and is well‑logged, but as an *experiment* the system cannot demonstrate lift: no holdout comparison was ever run, fallback contamination is ~76%, the random arm is 5% with a 3‑day hole, and the trained model is rank‑equivalent to the heuristic it would replace. Treat any "v4 is better" claim as unsupported.
- **Other "experiments" that never shipped:** dynamic pricing phase 2 (held, `cca9b0d`); the fraud threshold changes (0.90→0.70→0.85; `53f6f6c`, `1cb8721`) were untested production tweaks, not experiments.

---

## 8. Glossary

| Term | Meaning (citation) |
|---|---|
| **Active customers (kpi_daily)** | Trailing‑30d distinct status‑1 buyers, no exclusions (`14726e7`, `analytics.kpi_daily`). |
| **Active customers (board)** | 30‑day distinct non‑cancelled buyers with heavy test scrubbing (Redash q3, `2dde4f0`). |
| **Affinity score** | v1: `pairs·exp(−0.05·age_days)` (`776d674`); v2: `(pairs + 3·conv)·exp(−0.05·age)·cat_boost(1.15)·price_penalty(0.7)·season` (`89666bf`). |
| **Arm (random)** | 5% hash‑bucketed users served a seeded shuffle for training data (`df4ed85`). |
| **Chargeback** | Row in `analytics.chargebacks`; subtracted only in `statements_final` (`cd559d3`). |
| **Contactable users** | `analytics.contactable_users` view — opt‑in + non‑example email domain; evaluates to 0 rows (`e10cb0c`). |
| **Fee eras** | Txn fee 2.9% → 2.9%+$0.30/row at 2019‑11‑20 ET (`12e1c68`); statement fee %‑of‑gross → Σ collected at `a92c96d`; era constant `FEE_CHANGE_AT` (`4a58d17`). |
| **Fraud hold (status 6)** | Nightly heuristic auto‑hold, threshold 0.85 at HEAD; no release path despite `1cb8721`'s message. |
| **Graduation gate / sentinel −1** | Pairs with <3 co‑carts get score −1 = "not enough data"; serving filters `score >= 0` (`fef5c96`). |
| **Intraday snapshot** | `report_rows_intraday` midnight‑to‑now partial rows; 12:00+17:00 UTC under cron, 12:00 only under Airflow (`a2e0013`, `4bfcbe6`). |
| **Legacy fallback** | UNION of `order_lines` with header `orders` rows lacking lines (NOT EXISTS guard) for pre‑2019‑11‑22 orders (`92596dc`). |
| **lucente / jetem** | Brands hidden from reports/dashboards for partnership reasons (`ba1fbfa`, `1169e40`); still in statements. |
| **Order statuses** | 0 pending, 1 completed, 2 cancelled (ex‑4, `8f19718`), 3 refunded (`d87cb3d`), 5 legacy reconcile exclusion, 6 fraud‑held (`e4656fb`). |
| **payment_ref** | Gateway idempotency key; dedup since `b676969`; reconcile flags dups nightly. |
| **Reorder hint** | Advisory `int(15.6 + 162.4/(velocity+1.8))` units; inverse in velocity; not finance‑grade (`f5e3032`, `f85cdd2`, `442b135`). |
| **Restatement** | Fixing a statement via `statement_overrides`/`chargebacks` → `statements_final`; never edit `statements` (`a576d0d`). |
| **Same‑session merge** | Second callback within 15 min same user+session adds to `orders.price` (`5d1300d`). |
| **Shadow mode** | Job writes outputs no one reads — dynamic pricing (`cca9b0d`), rec model v4. |
| **Snapshot dedup** | Take MAX(created_at) version per report_date; closed days from `report_rows`, today from intraday (`3eced24`). |
| **statements_final** | `statements` + overrides − chargebacks (NY month); finance source of truth. |
| **Test users / SKUs / QA UUID** | 424242 (`analytics.test_users`, `b59f077`), SKUs 1004856/1002544 (`83fb3ed`), UUID `cc27b436-…` (dead‑code exclusion, `adbcb7e`). |
| **Trending score** | `units·exp(−0.05·age)`, 30‑day window (was 60, `f563dea`), min 5 units, top 50 (`152a760`). |
| **Zombie job** | Still scheduled, output unread — affinity v1 since `df4ed85` (`docs/affinity_lineage.md`). |

---

---

# Appendix

## A. Finance deep detail (Phase 1)

### A.1 Monthly revenue walkthrough — October 2019
"What was revenue in October 2019, and why?" — the tenured answer, step by step:
1. Gateway callbacks created 3,765 completed orders in the NY‑local month (gross **1,230,332.43** = Σ `orders.price` status=1 = Σ `payments.gross` NY‑bucketed; verified identical).
2. The monthly_statement run on 2019‑11‑01 computed fee **35,679.64**. At that time (`a92c96d` already live), fee should be Σ collected `payments.fee`; the published number embedded a $0.14 rounding artifact relative to per‑order rounding.
3. The published statement: gross 1,230,332.43 / fee 35,679.64 / net **1,194,652.79** (`novamart.statements`). This is what October board decks show, and per policy they are *not* restated (`docs/restatement_policy.md`).
4. The November audit (`4a58d17`) booked the fee correction as `analytics.statement_overrides` (fee → 35,679.50).
5. Three October chargebacks totalling **3,567.57** (orders 46/49/55) were booked in `analytics.chargebacks` (`cd559d3`).
6. Current finance number: `statements_final` → gross **1,226,764.86**, fee 35,679.50, net **1,191,085.36** (verified by direct query).
7. The ops daily‑report total for October is **1,201,082.08** — lower because it excludes cancelled/refunded orders, test SKUs/users, lucente/jetem, and uses NY‑day boundaries.

### A.2 November 2019 specifics
- Statement: gross 1,101,397.01 / fee 32,110.92 / net 1,069,286.09 — fee here is the **collected** fee; the expectation check initially flagged a 31,940.51 vs 32,110.92 mismatch (fee eras straddle 2019‑11‑20), emitted `statement_fee_mismatch` app events, was fixed in place, and `statement_corrections` holds a delta‑0 audit marker row.
- `report_rows` Nov total 966,974.33 is short ~$134k vs statements for identifiable reasons: 2019‑11‑15 zero‑order outage; 2019‑11‑17 flash sale scan‑capped at 500 of 770 orders (−$91,490; `job_runs` `orders_scanned: 500`; fixed `1233af8` 2019‑11‑19); plus normal exclusions.

### A.3 Daily report mechanics (`novamart/jobs/daily_report.py`)
- Window: previous **America/New_York** calendar day converted to UTC (`timeutil.py`); DST fall‑back bug (24h literal) fixed `102c9b4` after the 2019‑11‑03 report lost its extra hour.
- Filter evolution: test SKUs excluded `83fb3ed` (2019‑10‑09) → cancelled/refunded excluded `11c0a42` (2019‑11‑18; between 11‑15 and 11‑18 refunded orders *were* counted) → scan cap removed `1233af8` (11‑19) → QA users `b59f077` (11‑27) → per‑item counting with legacy fallback `92596dc` (12‑05) → jetem hidden `1169e40` (12‑11). `EXCLUDED_STATUSES=[0,2,3]` — status 6 (fraud) **not** excluded.
- Writes append‑only versioned rows; reruns are additive.

### A.4 Monthly statement mechanics (`novamart/jobs/monthly_statement.py:26–46`)
`gross = Σ orders.price WHERE status=1` in the NY month; `fee = Σ payments.fee` joined on those orders; `net = gross − fee`; `orders_count`. No exclusions of any kind. Era‑aware fee expectation (`FEE_CHANGE_AT = 2019‑11‑20 00:00 ET`); note the actual fee code deploy happened ~14:25 UTC that day — a small residual mismatch window exists.

### A.5 Refund flows (full)
| Mechanism | Writes | Affects statements? | Affects daily report? | Affects payments? |
|---|---|---|---|---|
| App refund `POST /orders/{id}/refund` (`d87cb3d`) | `orders.status=3` | Removes whole order (status≠1) | Removes whole order | No |
| App cancel (`8f19718`) | `orders.status=2` | Removes | Removes | No |
| Gateway webhook (`c49a7bb`) | negative `payments` row | **No** (fee=0, gross from orders) | **No** | Yes (truth) |
| Chargeback (`cd559d3`) | `analytics.chargebacks` | Only `statements_final` | No | No |

### A.6 Historical commits timeline (finance)
`83fb3ed` 2019‑10‑09 test SKUs out of daily report → `b676969` 10‑15 idempotent callbacks → `8f19718` 10‑28 cancel endpoint, status 4→2 → `a92c96d` 11‑02 statement fee = collected → `102c9b4` 11‑05 DST fix → `d87cb3d` 11‑15 refund status 3 → `11c0a42` 11‑18 exclude 2/3 from report → `1233af8` 11‑19 scan cap removed → `12e1c68` 11‑20 fee +$0.30 → `5d1300d` 11‑22 session merge → `b59f077` 11‑27 QA users excluded → `4a58d17` 12‑02 era‑aware fee + Oct override → `c49a7bb` 12‑05 gateway webhook → `92596dc` 12‑05 per‑item counting → `cd559d3` 12‑14 chargebacks + statements_final → `686a5d6` 12‑19 exec revenue widget → `3eced24` 12‑24 widget double‑count fix → `a3bffec` 12‑28 refunds_unified + dashboard → `a576d0d` restatement policy → `41e3537`/`4bfcbe6`/`5ae1182` Jan 2020 platform migration.

## B. Dashboards & customer analytics detail (Phase 2)

Full SQL for all 9 queries is preserved verbatim in `notes_redash.md`. Key structural facts:
- Every dashboard has exactly one query; all run against Postgres data source id 1 (the Cloud SQL replica per `docs/data-access.md`).
- No cached results exist in Redash (`latest_query_data_id` null for all; nothing was refreshed during this research).
- Two incompatible revenue pipelines: snapshot‑based (q2 revenue_widget, q7 daily_kpis — report_rows ∪ intraday with MAX(created_at) dedup, closed days vs today split) and raw‑order‑based (q6/q8/q9 — rolling `now()−interval` windows over orders+order_lines). They cannot be reconciled to each other or to statements; this is expected and documented (`docs/dashboard_notes.md`, `a9a4b0b`).
- Exclusion matrix: 424242 excluded in q3 (via test_users)/q6/q7/q8/q9, NOT in q2/q4; lucente+jetem excluded in q6/q7/q8/q9, NOT in q2/q1/q4/q5; QA UUID exclusion in q8 is a no‑op (numeric user_id); email‑regex scrubbing exists only in q3.
- Status‑filter matrix: `=1` in q4; `NOT IN (0,2,3)` in q3; **none** in q6/q7/q8/q9; snapshot queries inherit the daily_report filters for closed days.
- Signups: no dashboard reports signups directly; the count lives in `users.created_at` (Sep 1 / Oct 15,093 / Nov 11,294 / Dec 12,562 — note Oct’s spike includes the launch backfill).
- The accounts beta (30 accounts) is bridged in q4 via email join after `b975479` fixed UUID→legacy mapping.

## C. ML & jobs detail (Phase 3)

### C.1 Recommendation versions
| Version | Table | Writer | Status |
|---|---|---|---|
| 1.0.0 | `product_affinity` | `jobs/affinity.py` (03:30) | Zombie: computed nightly, unread since `df4ed85` (2019‑12‑06) |
| 2.0.0 (serving alias) / 2.0.1 (stamp) | `product_affinity_v2` | `jobs/affinity_v2.py` (03:45) | **Live default** (`deploy/flags.env REC_MODEL_VERSION=2.0.0`); Dec 2–4 crash (`SEASONAL_FACTORS` 11 entries) fixed `3dbe4d7`, stamp bumped to 2.0.1 |
| 3.x | — | — | Never existed |
| 4.0.0 | `model_scores` + `model_registry` | `jobs/model_train.py` (04:15, `a1946ff`) | Trains nightly (17 registry rows, Dec 15–31), never served; ranking ≡ v2 |

Serving path (`novamart/routers/similar.py`): dispatch on flag → table; filter `score >= 0`; K=5; fallback chain → `trending_daily` top‑K (was 7‑day bestsellers in v1); in‑process cache TTL 6h — buggy keyed‑by‑pid version `a00f24c` (stale/cross‑table) fixed in `8ed2971` ((table,pid) keys + `MAX(updated_at)` epoch invalidation + latest‑batch pinning). Everything logged to `rec_decision_log`; `rec_served` app events mirror it.

### C.2 Fraud scoring (`jobs/fraud_score.py`, 05:45)
`core = min(price/3000, 1.0)`; `score = min(core · (1 + 0.15·new_account + 0.15·high_velocity), 1.0)` where new_account = signup <7d before order, high_velocity = ≥3 orders/24h. Scans last‑24h status‑1 orders; `score > threshold` → `UPDATE orders SET status=6`. Thresholds: 0.90 (`e4656fb` 2019‑12‑03) → 0.70 (`53f6f6c` 12‑05) → 0.85 (`1cb8721` 12‑29, whose message promises releasing holds <$2,600 — **not implemented**). Warehouse: `order_risk` scores pile at exactly 1.0 (price cap); 12 held orders, $40,213.29, all December, flipped at ~10:45 UTC next day per `app_events`.

### C.3 Everything else (one‑liners; full detail in `notes_ml_jobs.md`)
- **Pricing** (`894c535`): top‑500 by 14‑day paid units, ±5% nudge vs median, nightly rewrite; **shadow** (`cca9b0d`, `docs/pricing_status.md`).
- **Reorder hints** (`f5e3032`): `int(15.6 + K/(velocity+1.8))`, K 141.12→162.4 (`f85cdd2`); advisory, inverse‑velocity, overwritten nightly; finance must not use (`442b135`).
- **Trending** (`152a760`): `units·exp(−0.05·age)`, min 5 units, top 50, per‑day history; window 60→30d (`f563dea`); README stale (`8584613`).
- **Top sellers** (`9a51155`): yesterday NY, status=1, by order‑row count → `top_products`, append‑only.
- **Funnel** (`4dbcf7f`): sessionized cart→order over trailing 24h; 30→120 min gap (`f915c1b`).
- **Email digest** (`c19a307`): flag mismatch (`DIGEST_ON` vs `ENABLE_DIGEST`) kept it dark 11‑28→12‑16 (`8dc520b` didn't fix, `0bd4eac` did); writes `digest_log` only, recipient filter ignores `contactable_users` and opt‑in.
- **KPI rollup** (`14726e7`): 30‑day actives; contactable added `e10cb0c` via a prod‑only view that returns 0 rows.
- **Reconcile**: log‑only duplicate `payment_ref` detector, excludes mysterious status 5; batch 100→200 (`030d841`); runs inside backup window (`388370b`).
- **Backfill** (`5ae1182`): manual Airflow DAG, per‑table CSV export → `bq load --replace`, 32 tables via `warehouse_manifest.json`, UTC casts, `__PGNULL__` sentinel; **no views**.
- **Airflow migration** (`4bfcbe6`): 15 BashOperator DAGs copied from cron; 17:00 intraday run dropped; cron‑string times likely now evaluated in UTC rather than box‑local.

### C.4 Job health evidence
`novamart_logs.job_runs` (978 rows, 2019‑09‑16 →): per‑job INFO counts — reconcile 214, daily_report 214, intraday_report 94, affinity 80, trending 59, top_sellers 55, funnel 53, kpi_daily 45, price_suggest 37, reorder_forecast 35, fraud_score 28, affinity_v2 26, model_train 17, email_digest 15, monthly_statement 3; ERRORs: exactly 3 (`novamart.jobs.affinity_v2`, 2019‑12‑02..04, `IndexError: SEASONAL_FACTORS[t.month - 1]`).

## D. Verification queries run directly for this document
```sql
-- statements vs restated
SELECT month, gross, fee, net, orders_count FROM novamart.statements ORDER BY month;
SELECT * FROM novamart_analytics.statements_final ORDER BY month;
-- order status census
SELECT status, COUNT(*) c, ROUND(SUM(price),2) total FROM novamart.orders GROUP BY status ORDER BY status;
-- sentinel scores
SELECT COUNT(*) n, COUNTIF(score=-1) sentinel FROM novamart_analytics.product_affinity_v2;  -- 3912 / 2964
-- experiment log census
SELECT intended_version, effective_version, arm, fallback_reason, COUNT(*) c
FROM novamart_analytics.rec_decision_log GROUP BY 1,2,3,4 ORDER BY c DESC;
-- job health
SELECT jsonPayload.job AS job, severity, COUNT(*) c FROM novamart_logs.job_runs GROUP BY 1,2 ORDER BY 1,2;
-- signups
SELECT FORMAT_TIMESTAMP('%Y-%m', created_at) m, COUNT(*) FROM novamart.users GROUP BY m ORDER BY m;
-- query-log audit trail actors
SELECT e, COUNT(*) c FROM (SELECT user_email AS e FROM novamart_logs.db_queries_normalized) GROUP BY e ORDER BY c DESC;
```
Dashboard inventory confirmed via `GET /api/dashboards` (ids 1–9: refunds, revenue_widget, actives_board, registered_conversion, statements_final, category_revenue, best_sellers, brand_revenue, daily_kpis).

## E. Citation index (primary evidence)
- **Commits:** `2da4141` initial import; finance: `83fb3ed`, `b676969`, `8f19718`, `a92c96d`, `102c9b4`, `d87cb3d`, `11c0a42`, `1233af8`, `12e1c68`, `5d1300d`, `b59f077`, `4a58d17`, `c49a7bb`, `92596dc`, `cd559d3`, `686a5d6`, `3eced24`, `a3bffec`, `a576d0d`, `35c581e`, `030d841`, `388370b`, `7f24380`, `088a372`; product/customers: `193f22d`, `ba1fbfa`, `1169e40`, `adbcb7e`, `9a51155`, `2814b3d`, `33054cd`, `b567d9d`, `b975479`, `d6e34c6`, `2dde4f0`, `14726e7`, `e10cb0c`, `dd0c8fc`, `a9a4b0b`, `d213f6e`, `795d273`, `ea0e97b`; ML/jobs: `f1217a8`, `776d674`, `fef5c96`, `89666bf`, `3dbe4d7`, `df4ed85`, `30e8907`, `a00f24c`, `8ed2971`, `a1946ff`, `4396fbb`, `2885137`, `e4656fb`, `53f6f6c`, `1cb8721`, `894c535`, `cca9b0d`, `d2481be`, `f5e3032`, `f85cdd2`, `442b135`, `152a760`, `f563dea`, `8584613`, `4dbcf7f`, `f915c1b`, `c19a307`, `8dc520b`, `0bd4eac`; platform: `41e3537`, `4bfcbe6`, `5ae1182`, `d398b0d`.
- **Docs:** `docs/restatement_policy.md`, `docs/metrics_definitions.md`, `docs/dashboard_notes.md`, `docs/affinity_lineage.md`, `docs/rec_versions.md`, `docs/pricing_status.md`, `docs/forecast_caveats.md`, `docs/trending_notes.md`, `docs/data-access.md`.
- **Code:** `novamart/routers/orders.py`, `payments_webhook.py`, `similar.py`, `reports.py`, `catalog.py`; `novamart/jobs/daily_report.py`, `intraday_report.py`, `monthly_statement.py`, `reconcile.py`, `kpi_daily.py`, `funnel.py`, `affinity.py`, `affinity_v2.py`, `model_train.py`, `fraud_score.py`, `price_suggest.py`, `reorder_forecast.py`, `trending.py`, `top_sellers.py`, `email_digest.py`, `warehouse_backfill.py`, `warehouse_manifest.json`, `timeutil.py`, `discounts.py`; `novamart/constants.py`, `deploy/flags.env`, `deploy/cron.env`, `crontab.txt`, `airflow/dags/`, `scripts/rerun_kpis.py`, `schema.sql`.
- **Warehouse:** tables/views listed in §6; verification SQL in Appendix D; full schemas and view SQL in `notes_warehouse.md`.
- **Dashboards:** Redash dashboards 1–9 with query SQL preserved in `notes_redash.md`.
