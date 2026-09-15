# Novamart Tribal Knowledge

- **Run ID:** `03bb25d5-84f9-4ee0-84a9-0c2945793850` — started Thu Aug 27 17:11:21 IST 2026
- **Sources (all evidence gathered on the fly during this run):**
  - Codebase: `<workspace>/novamart` pinned at commit `2ae79e2` (112 commits, 2019-09-15 → 2020-01-05)
  - Warehouse: BigQuery project `<warehouse-project>`, datasets `novamart` (12 app tables), `novamart_analytics` (24 tables/views), `novamart_logs` (`db_queries`, `app_events`, `job_runs`, `db_queries_normalized` view)
  - Dashboards: Redash at `<redash-url>` (9 dashboards / 9 queries, read-only)
- **Intermediate artifacts:** all saved under this run directory — `bq/results/*.sql|*.csv` (every warehouse query run), `redash/*.json` (all dashboards/queries), `repo/git_log.txt`, `repo/commits/*.diff`, `repo/dashboards_last_git/*.sql`.
- Citation style: `(<commit>)` = git commit in the repo; `dataset.table` = BigQuery; `Redash q<N>` = Redash query id; `bq/results/<name>.csv` = saved query evidence in this run dir.

---

## 1. Summary

Novamart is a small e-commerce marketplace backend: a FastAPI + Postgres monolith (`README.md`, initial import `2da4141`, 2019-09-15) with ~16 nightly cron jobs (later Airflow DAGs), file-based JSONL/statement logs exported to BigQuery, and 9 Redash dashboards that were migrated verbatim from `dashboards/*.sql` in git (`57ea43a`; I verified all 9 Redash queries are byte-identical to the last git versions — `bq/results` + `redash/query_*.json` vs `repo/dashboards_last_git/`).

The ten facts a tenured person would tell you on day one:

1. **Revenue has three layers.** `novamart.statements` is the append-only as-published snapshot; `novamart_analytics.statements_corrected` applies finance overrides (`statement_overrides`); `novamart_analytics.statements_final` further subtracts booked chargebacks. October 2019 net is 1,194,652.79 → 1,194,652.93 → 1,191,085.36 across the three layers (`bq/results/statements_all.csv`, `docs/restatement_policy.md`, commits `a92c96d`, `4a58d17`, `cd559d3`).
2. **Statements freeze at publication.** Orders cancelled/refunded after month close are *not* restated — October's published gross exceeds today's live status-1 gross by exactly the 23,995.11 of October orders later cancelled/refunded (43 cancels 10,748.42 + 27 refunds 13,246.69; `bq/results/orders_by_month.csv` vs `statements_all.csv`). Only chargebacks restate.
3. **October revenue is inflated ~$59.8k by duplicate orders.** Before idempotency (`b676969`, Oct 15) gateway callback retries created 130 duplicate payment_refs → 155 extra orders worth 59,810.59, still status 1 today (`bq/results/dup_inflation.csv`). Nightly `reconcile` has warned about the same 130 refs every night since — 10,766 `duplicate_payment_ref` warnings, zero cleanups (`novamart_logs.app_events`).
4. **The board "active customers" number is 0.** The board query (Redash q1, `2dde4f0`) excludes `example.com`-style email domains — but *every* user has a synthesized `user{uid}@example.com` placeholder (`novamart/onboarding.py`, `novamart/routers/catalog.py`). Emulated: 1,151 candidates before the email filter, **0 after** (`bq/results/actives_board_emulation.csv`).
5. **"Contactable customers" is structurally 0 too.** `analytics.contactable_users` (created 2019-12-04, `e10cb0c` + engineer SQL in `db_queries`) excludes `%.example` domains; the only non-placeholder emails are 40 users batch-updated to `@gmail.example` on 2019-10-23 (`app_events` `user_email_updated`). Meanwhile the marketing digest counts those same 40 as recipients — and featured excluded *test SKUs* (1002544, 1004856) as "top product" Dec 17–21 (`analytics.digest_log`).
6. **Daily revenue history has two permanent holes.** A 500-row scan cap (`REPORT_SCAN_CAP`, fixed `1233af8` Nov 19, never backfilled) makes 2019-11-17 report 148,857.07 vs 229,780.49 actual; and 2019-11-15 has **zero orders** at all — a payment-callback outage (28,666 product views, 2,284 cart adds, 0 `order_created`; `bq/results/nov15_events.csv`).
7. **The December 2019 statement was never generated.** `monthly_statement` ran only Oct 1, Nov 1, Dec 1 (`novamart_logs.job_runs`); the Jan 1 run never happened (platform migration). If run against the snapshot it would be gross 552,328.93, fee 16,600.26, net 535,728.67, 1,756 orders (`bq/results/dec_statement_preview.csv`) — excluding 12 still-held fraud orders worth 40,213.29.
8. **The "chargebacks" were booked by hand.** An engineer inserted exactly 3 rows on Dec 9 by selecting the first three October status-1 orders over $700 and booking their full price (940.82 + 1,891.94 + 734.81 = 3,567.57) — see the literal SQL in `novamart_logs.db_queries` (engineer-backfill:dev, 2019-12-09). Those same 3 orders are now status 2/3, so they *also* appear in the refunds dashboard.
9. **The recommender mostly serves the trending fallback, not ML.** 76% of affinity pairs are −1 "not enough data" sentinels (948 usable of 3,912; `bq/results/affinity_sentinels.csv`), so ~75–85% of widget responses are `fallback` (trending list) every single day (`analytics.rec_decision_log`). The "v4 trained model" has never served (flag still `REC_MODEL_VERSION=2.0.0`), its nightly coefficients swing sign-to-sign, and its "scores" are just affinity-v2 scores × (1 + 0.1·one-coefficient) (`novamart/jobs/model_train.py`).
10. **Dashboards ≠ jobs ≠ statements.** Each surface applies different filters (status, QA users, brands, SKUs, windows, timezones). Section 4 has the full matrix; if two numbers disagree, the answer is almost always "different definition", not "bug".

## 2. Why this project

This document exists to transfer the unwritten operating knowledge of Novamart's data systems so that a newcomer can:

- **Phase 1 (finance):** answer "what was revenue in month X, and why" the way a tenured finance/data person would — including which of the three statement layers to quote, what changed between them, and which known data defects (duplicates, undercounts, missing December) affect each month.
- **Phase 2 (product/customer analytics):** explain any number on the 9 Redash dashboards — including when a number should *not* be trusted at face value (board actives = 0, contactable = 0, best-sellers has no status filter, category groups are time-versioned, etc.).
- **Phase 3 (ML & batch):** judge whether the recommendation/fraud/pricing/forecast systems actually work, and safely modify the ~16 scheduled jobs knowing what breaks downstream when each fails.

The knowledge below was reconstructed exclusively from the pinned repo (code + git history + in-repo docs), the BigQuery warehouse (app tables, analytics tables, log exports), and the Redash dashboards.

## 3. Business understanding

**What the business is.** A marketplace storefront selling consumer goods — top brands by revenue: apple (1.43M), samsung (533k), xiaomi (107k), plus appliances/apparel/construction/kids categories (`bq/results/brand_landscape.csv`; category prefixes in `analytics.category_names`). 81,018 products, 38,950 users, 9,127 orders totaling ~2.9M gross over Oct–Dec 2019 (`bq/results/table_counts.csv`, `orders_status_dist.csv`). The storefront itself is *not* in this repo — the backend only receives product views, cart events, and **payment-gateway order callbacks** (`novamart/routers/orders.py` docstring: "Order creation from payment-gateway callbacks").

**Company timeline (all verified against git + logs):**

| When | Event | Evidence |
|---|---|---|
| 2019-09-15 | Initial import: FastAPI app, catalog/carts/orders routers, daily_report/reconcile/top-sellers/monthly-statement cron, dashboards/ SQL | `2da4141` |
| 2019-09-25 | First order (QA smoke user 424242, session `qa-smoke`) | `app_events` `order_created`; `bq/results/qa_user_activity.csv` |
| 2019-10-01 | Real order volume starts (~100–150/day); large lucente catalog import | `bq/results/report_rows_vs_orders.csv`; `docs/dashboard_notes.md` |
| 2019-10-01→15 | Callback-retry duplicate orders era (130 refs, +59,810.59) | `b676969` fix; `bq/results/dup_inflation.csv` |
| 2019-10-25 | lucente hidden from reports "per partnerships" | `ba1fbfa` |
| 2019-10-26 | Similar-products widget ships — and silently unmounts the `users`/`reports` routers | `f1217a8` (`app.py` diff) |
| 2019-11-03 | DST fall-back day; daily-report window bug found/fixed Nov 5, data never regenerated | `102c9b4`; engineer analysis SQL 2019-11-05 in `db_queries` |
| 2019-11-15 | Payment-callback outage: zero orders all day, site traffic normal | `bq/results/nov15_events.csv` |
| 2019-11-16/17 | Recovery spike (401/735 orders); Nov 17 daily report permanently undercounted by scan cap | `1233af8`; `report_rows_vs_orders.csv` |
| 2019-11-20 | Processor fee change: 2.9% → 2.9% + $0.30 flat | `12e1c68`; `FEE_CHANGE_AT` in `monthly_statement.py` |
| 2019-11-22 | Multi-item orders: same-session callbacks merge into one order, `order_lines` born | `5d1300d` |
| 2019-11-27 | Accounts beta endpoint added; QA user catalogued in `analytics.test_users` | `b567d9d`, `b59f077` |
| 2019-12-01 | Accounts beta enrolls exactly 30 accounts (one batch, 16:30 UTC) | `app_events` `account_created`; `novamart.accounts` |
| 2019-12-02 | Dynamic pricing phase 2 put ON HOLD per exec/legal review (shadow job keeps running) | `cca9b0d`; `docs/pricing_status.md` |
| 2019-12-03→05 | Fraud auto-hold ships (threshold 0.90→0.70); affinity_v2 crashes 3 nights (December seasonal-factor bug) | `e4656fb`, `53f6f6c`, `3dbe4d7`; `job_runs` `job_crashed` |
| 2019-12-04 | Gateway-refund webhook ships — silently unmounts the `accounts` router (beta dead after 30 signups) | `c49a7bb` (`app.py` diff) |
| 2019-12-06 | Rec-model version dispatch + 5% random arm; trending window 60→30 days | `df4ed85`, `f563dea`; `job_runs` `window_days` flip Dec 7 |
| 2019-12-09 | Chargebacks booked manually; `statements_final` view created | `cd559d3`; engineer SQL in `db_queries` |
| 2019-12-17→19 | Random-arm logging lost in a refactor (Dec 18 has zero random rows), restored | `30e8907`, `a00f24c`; `bq/results/rec_arms_by_day.csv` |
| 2019-12-29 | Fraud threshold 0.70→0.85; engineer releases held orders < $2,600 (5 released, 12 remain) | `1cb8721`; `UPDATE orders SET status=1 ... WHERE status=6 AND price<2600` in `db_queries` |
| 2020-01-02→05 | Platform migration: docs (`1179287`), dashboards→Redash (`57ea43a`), crontab→Airflow (`43e54a1`), Postgres→BigQuery backfill (`2ae79e2`) | those commits + `docs/data-access.md` |

**How money flows.** The gateway calls `POST /orders` with `(uid, pid, price, session, ref)`. The app creates/merges the order, writes a `payments` row (gross, fee = price×2.9%+$0.30, net), and marks status 1 (paid). Cancels (`/orders/{id}/cancel` → status 2) and refunds (`/orders/{id}/refund` → status 3) only flip status; since Dec 4 the gateway also pushes real money movements as negative `payments` rows via `/payments/gateway_refund` ("the gateway is the source of truth for money", `c49a7bb`) — note gateway-refunded orders **stay status 1** (3 orders, 9 partial-refund rows, 1,843.59 total; `bq/results/refund_overlap.csv`).

## 4. Metrics

### 4.1 Monthly revenue (the finance number)

Computed by `novamart/jobs/monthly_statement.py` (monthly, 06:30 local): gross = `SUM(price)` of **status 1** orders in the local (America/New_York) calendar month, fee = `SUM(payments.fee)` for those orders (since `a92c96d`), net = gross − fee, appended to `novamart.statements`. Answer "what was revenue in month X" in two parts (`docs/restatement_policy.md`):

- **As originally published:** `novamart.statements`
- **As currently restated:** `novamart_analytics.statements_final` (= `statements_corrected` = statements + `statement_overrides`, then minus `chargebacks` grouped to the order's month) — this is what Redash q9 (`statements_final` dashboard) shows.

| Month | Published (gross / fee / net / orders) | Final restated net | Why different |
|---|---|---|---|
| 2019-09 | 2,702.00 / 78.36 / 2,623.64 / 12 | 2,623.64 | none — but *all 12* September orders were later cancelled/refunded; statements don't restate for that |
| 2019-10 | 1,230,332.43 / 35,679.64 / 1,194,652.79 / 3,765 | **1,191,085.36** | fee override −0.14 (statement used gross×2.9% instead of collected per-order fees, fixed `a92c96d`, override note in `statement_overrides`); chargebacks −3,567.57 (`cd559d3`) |
| 2019-11 | 1,101,397.01 / 32,110.92 / 1,069,286.09 / 3,582 | 1,069,286.09 | fee-change audit booked **delta 0** (`statement_corrections`, `4a58d17`) — the Dec 1 `statement_fee_mismatch` warning (−170.41) was a false alarm from the pre-flat-fee expected formula |
| 2019-12 | **never published** | — | Jan 1 run never happened (migration). Would be 552,328.93 / 16,600.26 / 535,728.67 / 1,756 (`bq/results/dec_statement_preview.csv`) |

Known distortions inside those numbers: October includes ~59,810.59 duplicate-order inflation (§1.3); December excludes 12 fraud-held orders (40,213.29) that will re-enter if released; gateway-refunded revenue (1,843.59) is *never* deducted from any statement layer.

### 4.2 Daily revenue & orders (KPI dashboard, revenue widget)

Daily numbers do **not** come from `orders` — they come from report snapshots:

- `novamart.report_rows` — one batch per local day, written next morning 06:00 by `jobs/daily_report.py`. Excludes statuses {0,2,3} (since `11c0a42`), test SKUs 1004856/1002544 (`83fb3ed`), brands lucente+jetem (`ba1fbfa`, `1169e40`), users in `analytics.test_users` (`b59f077`). Counts per **item** (order_lines with legacy fallback) since `92596dc`.
- `novamart.report_rows_intraday` — same logic for "today so far", written 12:00 & 17:00 local (`a2e0013`), two versions per day (`bq/results/intraday_versions.csv`).

Both tables are **append-only with multiple `created_at` versions per report_date**; always take `MAX(created_at)` per date (Redash q5/q8 do). The original exec revenue widget (`686a5d6`, Dec 19) naively summed both tables → double/triple counting; fixed `3eced24` (Dec 24). Current 7-day widget value emulated: 139,598.13 (`bq/results/revenue_widget_emulation.csv`).

Permanent report_rows defects: Nov 17 undercount (scan cap), Nov 3 missing 23:00–24:00 local hour (DST bug `102c9b4`; engineer quantified but never regenerated — see 2019-11-05 SQL in `db_queries`), Sept 16–24 & Nov 15 legitimately zero, Dec 31 absent (job would have run Jan 1).

### 4.3 Active customers — three coexisting definitions (`docs/metrics_definitions.md`)

| Surface | Window | Status filter | Cleanup | Current value |
|---|---|---|---|---|
| `analytics.kpi_daily` (nightly `kpi_daily.py`, `14726e7`) | trailing 30×24h | status = 1 | none | 1,152 (Dec 31; `bq/results/kpi_actives_funnel.csv`) |
| Daily KPIs dashboard (Redash q5) `customer_days` | per local calendar day, 14 days | **none** | excludes uid 424242, brands lucente/jetem | per-day series |
| Board deck (Redash q1, `2dde4f0`) | trailing 30×24h | NOT IN (0,2,3) | `test_users` + email heuristics | **0 — broken** (§1.4) |

The three numbers never agreed *by construction*; the board one is additionally broken because the email hygiene filter excludes the universal `@example.com` placeholder. If asked for a real 30-day active number, use the kpi_daily definition minus `test_users` (= 1,151).

### 4.4 Contactable customers

`analytics.contactable_users` view = marketing_opt_in AND syntactically valid email AND domain not example.* / *.example (created 2019-12-04, `e10cb0c` + view SQL in `db_queries`). **Contains 0 rows** — see §1.5. The daily KPI dashboard's `contactable_customers` column is therefore always 0. The email digest job uses a *different* rule (`email NOT LIKE '%@example.com'`) and reports 40 recipients nightly (`analytics.digest_log`) — the 40 `@gmail.example` users from the Oct 23 batch update, one of which is the QA smoke account itself (`cust424242@gmail.example`; `bq/results/qa_email.csv`). Two "contactable" definitions, both effectively counting nobody real.

### 4.5 Refunds (Redash q6)

`analytics.refunds_unified` (created `a3bffec` + view SQL in `db_queries` 2019-12-23) unions three kinds: `order_cancelled` (status 2, full price at `updated_at`), `order_refunded` (status 3, same), `gateway_refund` (negative payments rows at payment `created_at`). Caveats a veteran knows:

- Cancels are counted as "refunds" even though no money may have moved.
- Status-2/3 amounts use the **current** order price and the *update* month, not the order month.
- The 3 manually-booked chargeback orders (46, 49, 55) are status 2/3, so their value appears in this dashboard *and* is deducted in `statements_final` — do not add the two surfaces.
- Zero overlap currently between gateway refunds and status-3 orders (`bq/results/refund_overlap.csv`) but nothing prevents it structurally.
- Monthly totals: Nov = 24 cancels 6,511.32 + 8 refunds 3,180.45; Dec = 30 cancels 6,738.32 + 20 refunds 10,267.02 + 9 gateway 1,843.59 (`bq/results/refunds_unified_monthly.csv`).

### 4.6 Best sellers / brand / category revenue (Redash q2/q3/q4; `docs/dashboard_notes.md`)

All three use the `item_orders` CTE (order_lines + legacy fallback, `92596dc`) and exclude uid 424242 and brands lucente/jetem. Differences that bite people: best sellers is a rolling **7×24h** window ranked **by revenue** (not units) with **no status filter** (unlike `jobs/top_sellers.py`, which is status=1 and has *no* brand/QA exclusions — the two "top sellers" surfaces disagree by design); brand revenue is rolling 30d and *additionally* excludes the QA account UUID string `cc27b436-d6f9-4e84-adaf-e716025dd369` (`adbcb7e` — defensive, since `orders.user_id` is numeric); category revenue maps `products.category` codes to display groups **as of the order date** via versioned `analytics.category_names` + `category_name_history` (`2814b3d`, `33054cd`) — on 2019-12-12 `construction.tools.light*` became "lighting" and `electronics.audio*` became "entertainment" (backfill SQL in `db_queries`), so the same order can legitimately appear under different groups depending on its date. Products with no mapping fall into `other`; 17,442 products have blank brands entirely (`analytics.blank_brand_products`, cause documented in its own `suspected_cause` column: `ON CONFLICT DO NOTHING` insert + in-process known-id cache prevented repair — `ea0e97b`, engineer SQL 2019-10-21).

Also: `EXCLUDED_SKUS = [1004856, 1002544]` (`constants.py`) — 1004856 is genuinely "Internal Test #4856" (brand `internal`, category `qa.test`, 328 orders/40,968.29 of QA volume), but 1002544 now looks like a real apple smartphone with 139 orders/66,690.18 (`bq/results/test_skus_and_jetem.csv`). Its exclusion removes real-looking revenue from daily reports. Jetem, denylisted Dec 15 (`1169e40`), has **zero orders ever** — that exclusion is optics only.

### 4.7 Registered conversion (Redash q7)

Two id namespaces: legacy numeric `users.id` (on orders) vs UUID `accounts.account_id` (beta). They are not castable; the original dashboard (`d6e34c6`) joined `account_id::text = user_id::text`, matched nothing ("FIXME: numbers look low"), fixed `b975479` to map accounts→users **via shared email**, then join orders on numeric id. Current value: 30 buyers, 18,155.71 lifetime status-1 revenue (`bq/results/registered_conversion_emulation.csv`). Only 30 accounts ever existed (batch, Dec 1) because the router was unmounted Dec 4 (§3 timeline).

### 4.8 Funnel & trending

- `analytics.daily_funnel` (`4dbcf7f`): sessions = activity runs (cart_items ∪ orders) split by inactivity gap — 30 min until `f915c1b` (Dec 14) raised it to **120 min**, so pre/post sessions counts are not comparable. ~300–400 sessions/day (`bq/results/kpi_actives_funnel.csv`).
- `analytics.trending_daily` (`152a760`): status-1 units over a rolling window with `score = units·exp(−0.05·days_since_last_order)`, min 5 units, top 50. Window cut 60→30 days `f563dea`; production flipped Dec 7 (`job_runs` `window_days`; `bq/results/trending_window_change.csv`). **README still says 60 days — stale**; `docs/trending_notes.md` is the correct reference.

## 5. System

### 5.1 Service

`novamart/app.py` mounts `catalog`, `carts`, `orders`, `similar`, `payments_webhook`. Router history (all from `git log -p novamart/app.py`): `users` (email update, `088a372`) and `reports` (monthly brand sales, `193f22d`) were mounted in October and **silently dropped** by the similar-widget commit `f1217a8` (Oct 26); `accounts` (`b567d9d`, Nov 27) was **silently dropped** by the webhook commit `c49a7bb` (Dec 4). Those three routers are live-looking dead code — `/reports/brands`, `/users/{id}/email`, `/accounts` return 404 in the current app.

Key service behaviors:

- `ensure_entities` (`routers/catalog.py`) creates users/products on first sight with **synthesized profiles** (deterministic hash of id → name/region/channel/device/age/opt-in, vendor/cost/stock; `novamart/onboarding.py`). This is why every user has a placeholder email and why "signup channel/region" analytics look plausible but are synthetic.
- Order callback flow (`routers/orders.py`): advisory locks on session+ref → replay detection by payment_ref (in `orders` or `order_lines`) → else merge into a same-session order updated within 15 min (adds an `order_lines` row + payment, `5d1300d`) → else create new order (+line +payment). Statuses: 0 created → 1 paid; 2 cancelled (was **4** before `8f19718` — no status-4 rows survive); 3 refunded (`d87cb3d`); 6 fraud-held (`e4656fb`); status 5 appears only in reconcile's `status <> 5` filter and exists nowhere in data (`bq/results/orders_status_dist.csv`).
- DDL-at-runtime idiom: endpoints/jobs `CREATE TABLE IF NOT EXISTS` their own tables (`order_lines`, `accounts`, `analytics.*`), so the real schema is discovered from production, not `schema.sql` (which is only the day-one schema).

### 5.2 Jobs & scheduling

Schedule lived in `crontab.txt` (now RETIRED, kept commented) → Airflow DAGs `airflow/dags/*.py` (one BashOperator each, same times, `43e54a1`). Full job reference in Appendix A.2. Operationally important:

- `reconcile` (03:00) only *logs* duplicate refs (200/night cap `RECONCILE_BATCH`, moved from 02:00 into the backup window by `388370b` — the commit message itself flags the overlap). It never fixes anything.
- `daily_report`/`intraday_report` feed `report_rows(_intraday)` → KPI dashboard + revenue widget. If they fail, dashboards go stale but raw `orders` are fine; recompute by re-running the job (append-only versioning makes reruns safe — dashboards take latest `created_at`).
- `monthly_statement` publishes once; a failed run = missing month (December!). There is no rerun tooling.
- `fraud_score` (05:45) mutates `orders.status` 1→6 above `FRAUD_HOLD_THRESHOLD` (0.90 `e4656fb` → 0.70 `53f6f6c` → 0.85 `1cb8721`). 17 orders were held in total; 5 released by hand Dec 29 (engineer UPDATE in `db_queries`); 12 remain held, price 2,655.33–5,999.98 (`bq/results/fraud_holds.csv`, `held_remaining.csv`). Held orders vanish from *every* status-1 metric.
- `email_digest` (07:15) was dead for ~3 weeks after launch (`c19a307` Nov 28) due to flag plumbing (`8dc520b`, `0bd4eac`); first real send Dec 17 (`job_runs`). Gated by `ENABLE_DIGEST=1` in `deploy/cron.env`.
- `scripts/rerun_kpis.py` + `jobs/discounts.py` are an ops stub for reapplying the promo cap (`DISCOUNT_CAP = 0.25`; the function's *default* cap is the legacy 0.40 — pass the constant explicitly, `35c581e`).

### 5.3 Deploys, flags, CI, logging

- Deploys are marked by `trigger deploy #d2p-novamart` commits — code is live only after the next trigger, which explains data gaps like the Dec 17–19 random-arm hole. Flags in `deploy/flags.env` (`REC_MODEL_VERSION=2.0.0`; "flip + redeploy, no code change") — never flipped in history.
- CI (`ci/run_ci.py`): boots the app on a scratch DB, exercises view→cart→order, checks orders/payments consistency, runs reconcile/daily_report/monthly_statement under `FAKE_NOW`.
- Logging (`novamart/logutil.py`, `db.py`): `app.jsonl` → `novamart_logs.app_events` (jsonPayload), `db_queries.log` (every SQL statement with `[app]`/`[job]`/`[engineer:*]` actor tags) → `novamart_logs.db_queries` (textPayload), `jobs.jsonl` → `novamart_logs.job_runs`. `novamart_logs.db_queries_normalized` is a convenience view parsing statement type + referenced tables.
- Warehouse: `novamart/jobs/warehouse_backfill.py` (+ manifest of 32 tables) exports serving Postgres → GCS CSV → BigQuery (`public.*` → dataset `novamart`, `analytics.*` → `novamart_analytics`), one-shot, triggered manually during the Jan 2020 migration (`2ae79e2`, `warehouse_backfill_dag.py`, `docs/data-access.md`). The warehouse is a **point-in-time snapshot** (~Jan 2020), not a live replica.

## 6. Data

### 6.1 `novamart` (app tables — serving Postgres snapshot)

| Table | Rows | What a veteran knows |
|---|---|---|
| `orders` | 9,127 | One row per order (merged multi-item orders keep summed `price`). Statuses: 1=9,033 (2.86M), 2=54, 3=28, 6=12. `created_at` = first callback; `updated_at` moves on status flips (refunds dashboard keys off it). Contains the 155 duplicate orders (§1.3). |
| `order_lines` | 2,284 | Exists since Nov 22 (`5d1300d`); 2,059 orders have lines, 173 are true multi-item. Pre-Nov-22 orders have **no** lines — hence every item-level query needs the legacy fallback. |
| `payments` | 9,361 | ≥1 row per paid order; `payment_ref` column added Nov 22 (NULL before); negative rows = gateway refunds (fee 0). Fees: 2.9% (+$0.30 after 2019-11-20 05:00 UTC). |
| `users` / `products` | 38,950 / 81,018 | Bootstrapped on first sight; profiles synthetic (`onboarding.py`). 17,442 products blank-brand; brand repair only works when the storefront later sends a brand (`ea0e97b`, `d213f6e`). |
| `cart_items` | 36,938 | Raw add-to-cart events (removes delete rows); fuel for affinity + funnel. |
| `accounts` / `account_map` | 30 / 30 | The whole registered-accounts beta (Dec 1). uid 424242 ↔ `cc27b436-d6f9-4e84-adaf-e716025dd369`. |
| `report_rows` / `report_rows_intraday` | 6,923 / 2,358 | Append-only snapshot tables; always dedupe by latest `created_at` per report_date (§4.2). |
| `top_products` | 2,396 | Nightly top-50 by units, status=1 only, **no QA/brand/SKU exclusions** (`9a51155`) — disagrees with the best-sellers dashboard by design. |
| `statements` | 3 | As-published monthly snapshots; never rewrite (policy in `docs/restatement_policy.md`). |

### 6.2 `novamart_analytics`

Finance: `statement_overrides` (1 row, Oct fee fix), `statement_corrections` (1 row, Nov delta 0), `chargebacks` (3 manual rows), views `statements_corrected`/`statements_final` (definitions captured in §4.1 and `db_queries` 2019-12-09), `refunds_unified` (view, §4.5).

Product/customer: `kpi_daily` (45 rows since Nov 17), `daily_funnel` (53), `trending_daily` (2,898; top-50/day), `category_names` (135; **no PK — versioned**, multiple rows per code) + `category_name_history` (6), `blank_brand_products` (5,972 with self-documenting cause column), `price_history` (1,400 rows from 13 vendor feed events; `795d273`), `contactable_users` (view, 0 rows), `test_users` (1 row: 424242), `digest_log` (15).

ML: `product_affinity` (v1, 3,912) and `product_affinity_v2` (3,912; `model_version='2.0.1'` stamped inside — writer version ≠ serving version 2.0.0, a known naming wart per `docs/affinity_lineage.md`), `model_scores` (948), `model_registry` (17 nightly v4 fits), `rec_decision_log` (667,850 — one row per widget serve), `order_risk` (1,631), `price_suggestions` (500, overwritten nightly), `reorder_hints` (200, overwritten nightly — **advisory only**, inverse-velocity heuristic where *slower* sellers get *bigger* hints; `docs/forecast_caveats.md`, `f5e3032`, `f85cdd2`).

### 6.3 `novamart_logs`

- `db_queries`: every SQL statement since 2019-09-16 with actor tags. The `engineer:*` / `engineer-backfill:*` rows (191 statements, saved in `bq/results/engineer_sql.csv`) are the audit trail of *every* manual intervention: duplicate investigation (Oct 15), blank-brand forensics + table (Oct 21), statement override (Nov 2), DST quantification (Nov 5), scan-cap forensics (Nov 19), test_users insert (Nov 27), category backfills (Nov 30, Dec 12), contactable view (Dec 4), chargebacks + statements_final (Dec 9), refunds view (Dec 23), held-order release (Dec 29).
- `app_events`: business events (see inventory `bq/results/app_events_inventory.csv`); includes the three `statement_fee_mismatch` warnings decoded in §4.1.
- `job_runs`: per-run job stats — the ground truth for "did the job run / with what parameters" (window_days, threshold, held, train_rows, recipients…).

### 6.4 Cross-cutting data gotchas

- **Timezones:** business days/months are America/New_York (`LOCAL_TZ`); storage is UTC. Month boundary example: October = `2019-10-01 04:00Z → 2019-11-01 04:00Z`. DST fall-back days are 25h (`timeutil.py` after `102c9b4`).
- **The QA account** is uid 424242 (email `qa.smoke@novamart.sim` implied by exclusion regexes; 14 orders, $139.86, one per ~week, session `qa-smoke`) + UUID account. Excluded via `test_users` (jobs) and hardcoded predicates (dashboards) — but **not** from `kpi_daily`, `top_products`, statements, funnel, or trending.
- **Emails are almost all fake** (38,910 `@example.com` placeholders + 40 `@gmail.example`); any email-based segmentation silently collapses.

## 7. Experimentation

**Recommendation system (the only real experiment loop).** `GET /products/{pid}/similar` (`routers/similar.py`):

- Versions: 1.0.0 = retired co-cart affinity (`776d674`, served Oct 26–Dec 6); 2.0.0 = affinity v2 "exploit" (conversion-weighted: carted=1/converted=3, same-category ×1.15, extreme price-ratio ×0.7, monthly seasonal factor — which **crashed in December** because `SEASONAL_FACTORS` only had 11 months, `3dbe4d7`); 4.0.0 = nightly logistic model, flag-gated, never enabled. `docs/rec_versions.md` is literally "TBD" — `docs/affinity_lineage.md` is the real doc.
- **Random arm:** 5% of users (`sha256(uid) % 20 == 0`) get uniform-random recommendations to generate unbiased training data (`df4ed85`). Every serve logs `(intended, effective, source, reason, arm)` to `analytics.rec_decision_log`. Known hole: the Dec 17 "tidy response path" refactor (`30e8907`) dropped random-arm logging; restored `a00f24c` — Dec 18 has **zero** random rows (`bq/results/rec_arms_by_day.csv`). Any model trained on that window is missing a day of exposures.
- **Does it work?** Mostly no: ~75–85% of non-random serves fall back to the trending list because affinity coverage is thin (76% sentinel rows). The v4 model trains nightly on random-arm exposures (4,197 → 14,411 rows) with 5 features (served-list size, base price/1000, base popularity/100, capped account age, organic-channel flag — the README's claim of marketing-opt-in/region/device/stock features is **wrong**; opt-in is fetched but unused, the rest never fetched) and predicts "user converted to *any* later order", not item relevance. Its coefficients flip signs nightly (`bq/results/model_registry.csv`) and its output is just `affinity_v2_score × (1 + 0.1 × coef[0])` — a monotone rescaling that cannot change ranking. Serving 4.0.0 would effectively serve affinity-v2 with extra steps.
- Caching: 6h in-process score cache (`a00f24c`), epoch-invalidated on nightly refresh since `8ed2971` (between Dec 19–26 it could serve day-old scores after the 03:45 refresh).
- **Fallback rule to remember:** if a base product has no usable scores, users see *trending*, logged as `source='fallback'` — so "the widget looks the same for everything" usually means sparse affinity, not an outage.

**Dynamic pricing** — phase 1 shadow only (`894c535`): nightly ±5% nudges for top-500 products into `analytics.price_suggestions`; phase 2 (serving) **ON HOLD per exec/legal review** (`cca9b0d`, code NOTE); nothing reads the table (verified: no SELECTs in `db_queries`; `docs/pricing_status.md`).

**Fraud threshold tuning** — de facto experiment by constants: 0.90 (8 held Dec 4) → 0.70 (Dec 5) → 0.85 + manual release <$2,600 (Dec 29). No evaluation loop, no labels; score = `min(price/3000,1)·(1+0.15·new_account+0.15·high_velocity)` — i.e., mostly "is the order expensive".

**A/B infrastructure otherwise:** none. Flag flips (`flags.env`) are redeploys; dashboard-visible "experiments" (fee change, trending window, funnel gap) are unversioned constant changes — you detect them from `job_runs` parameters and git blame, not from any experiment registry.

## 8. Glossary

| Term | Meaning (with source of truth) |
|---|---|
| **Order status** | 0 created/pre-payment, 1 paid, 2 cancelled (was 4 pre-`8f19718`), 3 refunded, 5 reserved-but-unused (only in reconcile's filter), 6 fraud-held (`constants.py`, `fraud_score.py`) |
| **payment_ref** | Gateway's idempotency key; unique per callback; duplicated across orders only in the pre-Oct-15 defect window |
| **order_lines** | Per-item rows for merged same-session orders (since `5d1300d`); legacy orders have none → "legacy fallback" pattern |
| **item_orders CTE** | Dashboard idiom: order_lines UNION legacy orders-without-lines (`92596dc`) |
| **report_rows / _intraday** | Append-only daily/intraday sales snapshots; dedupe by latest `created_at` per date |
| **statements / statements_corrected / statements_final** | Published snapshot → + finance overrides → − chargebacks; quote `statements_final` unless asked to match an old deck (`docs/restatement_policy.md`) |
| **statement_overrides / statement_corrections / chargebacks** | Override rows (replace month), audit deltas (explain month), manually-booked chargebacks by order |
| **refunds_unified** | View unioning cancels, refunds, gateway refunds — mixed semantics, see §4.5 |
| **active customers** | Three definitions (kpi_daily rollup / KPI dashboard per-day / board 30d-cleaned); board version currently returns 0 |
| **contactable_users** | Opt-in + real-email view; empty because all emails are placeholders |
| **test_users / 424242 / qa-smoke** | The QA smoke account (email `cust424242@gmail.example`, UUID account `cc27b436-…`; `bq/results/qa_email.csv`); excluded from reports/dashboards but not from statements/kpi_daily/top_products — and it *is* one of the digest's 40 "recipients" |
| **EXCLUDED_SKUS** | 1004856 ("Internal Test", brand `internal`) and 1002544 (now apple-branded, $66.7k) — hidden from daily reports and rec serving only |
| **BRAND_DENYLIST** | lucente (real revenue, hidden Oct 25 "per partnerships") + jetem (zero orders, hidden Dec 15) |
| **FEE_RATE / FEE_FLAT / FEE_CHANGE_AT** | 2.9%, $0.30, 2019-11-20 local — per-order collected fee is authoritative; formula is only an expectation check |
| **LOCAL_TZ** | America/New_York; all "days"/"months" in reports/statements are local |
| **duplicate_payment_ref** | Nightly reconcile warning; 130 refs, never remediated |
| **REPORT_SCAN_CAP** | Removed 500-row cap that permanently undercounts Nov 16–17 report_rows |
| **arm / random arm** | 5% uniform-random rec serving for unbiased training data; logged in rec_decision_log |
| **sentinel score (−1)** | Affinity "not enough data" marker (pairs seen < 3); serving must filter `score >= 0` (`fef5c96`) |
| **seasonal factor** | affinity_v2 monthly multiplier from "the 2019 planning sheet"; Jan–Nov only (December crash fixed `3dbe4d7`) |
| **REC_MODEL_VERSION** | Serving flag in `deploy/flags.env` (2.0.0 = affinity_v2 table; 4.0.0 = model_scores table; never flipped) |
| **model_version 2.0.1** | Version stamp *inside* product_affinity_v2 rows — batch writer's version, not the serving version |
| **reorder_hints** | Advisory inverse-velocity heuristic (`BASE + K/(velocity+C)`); never use for purchasing commitments |
| **trigger deploy #d2p-novamart** | Empty marker commit = production release point; code between triggers is not live yet |
| **engineer / engineer-backfill actors** | Manual-SQL tags in db_queries — the audit trail of every hand edit to production data |

---

## Appendix

### A.1 How to answer "what was revenue in <month>, and why" (the tenured answer)

1. Quote `novamart_analytics.statements_final` for the current number; `novamart.statements` for "what we said at the time" (`docs/restatement_policy.md`).
2. Explain deltas via `statement_overrides` (generation bugs), `statement_corrections` (audits), `chargebacks` (post-hoc money reversals).
3. Add the unwritten caveats per month: **Sep** — 12 orders, all later cancelled/refunded, never restated. **Oct** — contains ~59,810.59 duplicate inflation (130 refs pre-idempotency) and the 3 hand-booked chargebacks; fee corrected by override. **Nov** — clean statement; fee-change audit delta 0; underlying daily reports have the Nov 15 outage and Nov 16–17 scan-cap undercount (statement unaffected — it reads `orders`, not `report_rows`). **Dec** — no statement exists; recompute gives 552,328.93 / 16,600.26 / 535,728.67 / 1,756; 12 held orders (40,213.29) excluded; 1,843.59 gateway refunds not deducted.
4. Never mix surfaces: statements (status-1 orders, local month, no exclusions) ≠ report_rows dailies (status/QA/brand/SKU exclusions) ≠ dashboards (their own filters).

### A.2 Job reference (schedule local; module → output → consumers → failure blast radius)

| Time | Job | Output | Consumers / if it fails |
|---|---|---|---|
| 03:00 | reconcile | warnings only | Log-only; failure = lost duplicate visibility |
| 03:30 | affinity (v1, legacy) | analytics.product_affinity | Nothing serves it since Dec 6 (`docs/affinity_lineage.md`) — safe to drop for the widget, still burning compute |
| 03:45 | affinity_v2 | analytics.product_affinity_v2 | Similar widget (2.0.0) + model_train candidates; failure → widget cache serves stale then falls back to trending (Dec 3–5 crash precedent) |
| 04:15 | model_train (v4) | model_registry + model_scores | Nothing (flag never flipped) |
| 04:45 | price_suggest | analytics.price_suggestions | Nothing (shadow, ON HOLD) |
| 05:15 | trending | analytics.trending_daily | Homepage + rec fallback — failure degrades the *majority* of rec serves (fallback reads `MAX(day)`, so it silently serves yesterday) |
| 05:45 | fraud_score | analytics.order_risk + status 6 holds | Mutates orders! Failure = no holds; over-aggressive threshold = revenue hidden from all status-1 metrics |
| 06:00 | daily_report | report_rows | KPI dashboard + revenue widget history; failure = stale dashboards, rerun-safe |
| 06:15 | kpi_daily | analytics.kpi_daily | 30d actives rollup |
| 06:20 | funnel | analytics.daily_funnel | Sessions/users_active |
| 06:30 (monthly) | monthly_statement | statements | Finance; failure = missing month (see December) |
| 06:45 | top_sellers | novamart.top_products | Unfiltered top-50 (≠ dashboard) |
| 06:50 | reorder_forecast | analytics.reorder_hints | Advisory merchandising only |
| 07:15 | email_digest | analytics.digest_log | Marketing; gated by ENABLE_DIGEST; picks top product with **no test-SKU filter** |
| 12:00 & 17:00 | intraday_report | report_rows_intraday | "Today" on KPI dashboard + widget |
| manual | warehouse_backfill | BigQuery datasets | Warehouse rebuild (`2ae79e2`) |

### A.3 Data-quality issue register (all verified in this run)

| # | Issue | Impact | Status | Evidence |
|---|---|---|---|---|
| 1 | Duplicate callback orders Oct 1–15 | +155 orders / +59,810.59 in Oct metrics & statement | Open (flagged nightly, never fixed) | `dup_inflation.csv`; `b676969` |
| 2 | Nov 15 payment-callback outage | 0 orders that day everywhere | Permanent | `nov15_events.csv` |
| 3 | Scan-cap undercount Nov 16–17 | report_rows −80,923.42 on Nov 17 vs actual | Permanent (code fixed `1233af8`, no backfill) | `report_rows_vs_orders.csv`; engineer SQL Nov 19 |
| 4 | DST 25h-day miss Nov 3 | report_rows missing local 23:00–24:00 | Permanent (fixed `102c9b4`, no backfill) | engineer SQL Nov 5 |
| 5 | Board actives = 0 | Board deck metric meaningless | Open | `actives_board_emulation.csv` |
| 6 | contactable_users empty; digest counts 40 fake-domain users | Contactable KPI = 0; digest recipients misleading | Open | `digest_and_emails.csv` |
| 7 | December statement missing | No published Dec revenue | Open | `job_runs_summary.csv`; `statements_all.csv` |
| 8 | 12 fraud-held orders (40,213.29) | Excluded from all status-1 revenue; will shift Dec numbers if released | Open | `held_remaining.csv` |
| 9 | Gateway refunds never hit statements | Net overstated by 1,843.59 (Dec) | Open by design | `refund_overlap.csv`; view SQL |
| 10 | Chargebacks manually booked, overlap refunds dashboard | Double-representation across surfaces | By design — never sum the two | `chargebacks.csv`; engineer SQL Dec 9 |
| 11 | 17,442 blank-brand products (94,357.87 revenue) fall out of brand dashboards | Brand revenue under-attributes | Documented in `blank_brand_products` | `brand_landscape.csv` |
| 12 | Dead routers (`/accounts`, `/reports/brands`, `/users/{id}/email`) | Accounts beta frozen at 30; code misleads readers | Open since `c49a7bb`/`f1217a8` | app.py git history |
| 13 | Random-arm log gap Dec 17–19 | Training data hole | Permanent | `rec_arms_by_day.csv`; `30e8907`/`a00f24c` |
| 14 | README stale: trending 60d (actual 30d), v4 feature list overstated | Doc rot | Use `docs/trending_notes.md` / code | `trending.py`, `model_train.py` |
| 15 | 1002544 "test SKU" now apple-branded with real-looking $66.7k | Daily reports exclude possibly-real revenue | Needs business decision | `test_skus_and_jetem.csv` |

### A.4 Where every number on each Redash dashboard comes from

| Dashboard (id) | Reads | One-line trust note |
|---|---|---|
| best_sellers (q2) | orders+order_lines live, 7×24h | No status filter; ranked by revenue; excludes QA uid + lucente/jetem |
| brand_revenue (q3) | same, 30×24h | + UUID exclusion; blank brands invisible |
| category_revenue (q4) | same + versioned category mapping | Groups are date-dependent (Dec 12 remap) |
| daily_kpis (q5) | report_rows(+intraday) latest-version + orders for customers | revenue/orders inherit report exclusions; actives have **no status filter**; contactable always 0 |
| refunds (q6) | analytics.refunds_unified | Mixes cancels/refunds/gateway; months keyed to update time |
| actives_board (q1) | orders+test_users+users emails | **Returns 0** — placeholder-email exclusion |
| registered_conversion (q7) | accounts→users via email→orders | 30 frozen beta accounts, lifetime status-1 revenue |
| revenue_widget (q8) | report_rows(+intraday) latest-version, 7 calendar days | Correct since `3eced24`; before Dec 24 double-counted |
| statements_final (q9) | analytics.statements_final | The finance number; no December row |

### A.5 Verification ledger (what I ran)

All queries and outputs are preserved in `bq/results/` (42 result sets: `orders_status_dist`, `orders_by_month`, `refunds_unified_monthly`, `refund_overlap`, `statements_all`, `overrides`, `corrections`, `chargebacks`, `job_runs_summary`, `dup_payment_refs`, `dup_inflation`, `report_rows_vs_orders`, `accounts_timeline`, `rec_arms_by_day`, `model_registry`, `table_counts`, `digest_and_emails`, `app_events_inventory`, `nov15_events`, `fee_mismatch`, `qa_user_activity`, `manual_ops`, `actors`, `engineer_sql`, `brand_landscape`, `kpi_actives_funnel`, `funnel_sample`, `order_risk_stats`, `test_skus_and_jetem`, `intraday_versions`, `dec_statement_preview`, `actives_board_emulation`, `registered_conversion_emulation`, `revenue_widget_emulation`, `trending_window_change`, `order_lines_stats`, `affinity_sentinels`, `fraud_holds`, `held_remaining`), Redash dumps in `redash/`, and 48 key commit diffs in `repo/commits/`. BigQuery view definitions were captured via `bq show`. No data anywhere was mutated; Redash was accessed read-only via GET; the repo was never modified.
