# Novamart Tribal Knowledge

- **Run started:** Thu Aug 27 17:11:25 IST 2026
- **Run UUID:** `82df76d1-3acd-4478-b03f-5d2caa45b6f3`
- **Sources:** git repo `<workspace>/novamart` @ `2ae79e2`; BigQuery project `<warehouse-project>` (datasets `novamart`, `novamart_analytics`, `novamart_logs`); Redash at `<redash-url>` (9 dashboards, read-only — never refreshed or modified).
- **Data snapshot:** the warehouse is a one-shot export of the serving Postgres taken at end of day **2019-12-31** (max `orders.created_at` = 2019-12-31 16:51:39 UTC; max `app_events.timestamp` = 2019-12-31 23:57:06 UTC). Company history runs 2019-09-15 (commit `2da4141`, "initial import") through 2020-01-05 (commit `2ae79e2`).

---

## 1. Summary

Novamart is a FastAPI + Postgres marketplace backend (repo `README.md`) whose business numbers are produced by ~16 nightly cron jobs (now Airflow DAGs, commit `43e54a1`) writing into a Postgres `analytics` schema, mirrored once into BigQuery by `novamart.jobs.warehouse_backfill` (commit `2ae79e2`). Nine Redash dashboards run the exact SQL that used to live in `dashboards/*.sql` (deleted in commit `57ea43a`; verified byte-identical via `GET /api/queries/1..9`).

The ten facts that unlock everything else:

1. **Orders are created by payment-gateway callbacks, not user actions.** `POST /orders` (`novamart/routers/orders.py`) charges `fee = price*0.029 + 0.30` (`constants.FEE_RATE`, `FEE_FLAT`; flat fee since 2019-11-20, commit `12e1c68`) and writes `orders`, `order_lines`, `payments`. Since 2019-11-22 (commit `5d1300d`) same-session callbacks within 15 minutes are **merged into one order**: `orders.price` is the running total, `order_lines` has the per-item truth.
2. **There are three coexisting "monthly revenue" answers.** `novamart.statements` (as-published snapshot), `novamart_analytics.statements_corrected` (fee override applied), `novamart_analytics.statements_final` (chargebacks subtracted — the current finance number). For Oct 2019 net: **1,194,652.79 → 1,194,652.93 → 1,191,085.36** (`docs/restatement_policy.md`, verified by querying all three).
3. **Published statements cannot be reproduced from raw orders**, by design and by drift: they are append-only snapshots; order statuses keep changing after publication. All 12 of September's statement orders (gross 2,702) are now status 2/3, so a naive recompute of September revenue today returns **zero**.
4. **October revenue is silently inflated ~4.8%.** 130 payment_refs map to 285 orders (gateway retries before the idempotency fix `b676969`, 2019-10-15). 151 duplicate orders worth **$58,828.24** are still `status=1` inside October's published gross of 1,230,332.43. The nightly `reconcile` job only *warns* (10,766 `duplicate_payment_ref` warnings in `novamart_logs.app_events`); nothing ever repaired them, and no restatement was booked.
5. **Two refund generations behave differently.** v1 (`/orders/{id}/refund`, commit `d87cb3d`) just flips `orders.status` to 3 — money is untouched. v2 (`/payments/gateway_refund`, commit `c49a7bb`, 2019-12-05) inserts a *negative* `payments` row but **leaves the order status = 1**, so gateway-refunded orders still count as revenue in every status-based metric.
6. **The board's "active customers" dashboard reads 0 — always.** Every one of the 38,950 users has a placeholder email (38,910 `@example.com` from the bootstrap in `routers/catalog.py`, 40 `@gmail.example`), and the `actives_board` query (Redash query 1) excludes both patterns. Same root cause makes `analytics.contactable_users` an **empty view** and `daily_kpis.contactable_customers` always 0.
7. **The "orders" and "revenue" on the exec KPI dashboard come from report snapshots, not orders.** `daily_kpis` (Redash query 5) reads `report_rows` (+ `report_rows_intraday` for today). Those snapshots inherit historical bugs: the 500-row scan cap (removed in `1233af8`) makes **2019-11-17 permanently understated: 487 units / $148,857 reported vs 735 / $229,780 in orders**.
8. **The recommender "works" but rarely fires.** Since the v2 rollout (`df4ed85`, 2019-12-06) the similar-products widget served affinity-v2 scores only ~20% of the time; ~75–80% of serves fall back to `trending_daily` (`fallback_reason='no_scores'`: 509,054 rows in `rec_decision_log`). Where it does fire, it converts: 0.996% (model) vs 0.223% (fallback) vs 0.0% (random arm) — buy-a-recommended-item-within-3-days, Dec 6–31.
9. **The v4 "trained model" cannot change any ranking.** `model_train.py` scores are `affinity_v2.score * (1 + 0.1*w)` with a single global `w` — a rank-preserving scalar. It trains nightly (17 rows in `model_registry`) but serving is pinned to `REC_MODEL_VERSION=2.0.0` in `deploy/flags.env` anyway.
10. **Order volume halved around Nov 22–23 and never recovered** (order_created events: ~115/day → ~40/day; weekly status-1 revenue: $400k → ~$110k) while product views stayed flat (~55–60k/week). It is a demand/conversion drop, not a pipeline bug: `payments` (written per callback) fell identically. December closed at 552,328.93 status-1 gross vs November's 1,101,397.01 — and **no December statement exists** because the snapshot predates the Jan 1 statement run.

## 2. Why this project

The stated goals (goal-context doc) were: (Phase 1) understand how orders, payments, refunds, monthly revenue, and finance statements are actually produced and which surface is the source of truth for each; (Phase 2) understand product/customer analytics well enough to explain — or refuse to trust — any dashboard number; (Phase 3) judge whether the ML systems work and be able to safely modify the batch pipelines.

This document is written for the next engineer/analyst who inherits Novamart with no one left to ask. Everything below was derived only from the repo at `2ae79e2`, the BigQuery warehouse, the log exports, and the Redash API; every claim carries its evidence (commit, table/view, query, log line, or dashboard). Where the company's own docs (`docs/*.md`) make claims, I re-verified them against data and note agreement or divergence.

## 3. Business understanding

### 3.1 What the company is

Novamart is an online marketplace: ~81k products from a vendor catalog feed, ~39k shopper records, ~9.1k orders totaling ~$2.9M over Sep 25 – Dec 31, 2019 (counts from `novamart.products/users/orders`). The storefront itself is not in this repo; this codebase is the backend the storefront and the payment gateway call:

- `GET /products/{pid}` product views, `POST /cart` / `POST /cart/remove` (routers `catalog.py`, `carts.py`)
- `POST /orders` — the payment gateway's success callback creates the order (`orders.py`)
- `POST /orders/{id}/cancel`, `POST /orders/{id}/refund` — ops actions (commits `8f19718`, `d87cb3d`)
- `POST /payments/gateway_refund` — the gateway's refund webhook (commit `c49a7bb`)
- `GET /products/{pid}/similar` — the recommendation widget (commit `f1217a8`)
- `POST /catalog/prices` — bulk vendor price feed; also appends to `analytics.price_history` (commit `795d273`)
- `POST /accounts` — the Dec-2019 "registered accounts" beta: exactly **30 accounts**, all created 2019-12-01 16:30 UTC (`novamart.accounts`), mapped to legacy numeric uids via `account_map`.

Two routers exist but are **not mounted** in `novamart/app.py` at HEAD: `accounts.py`, `users.py`, and `reports.py` (the `/reports/brands` endpoint) — they ran during the beta/were used historically (30 accounts exist; `user_email_updated` events exist in `app_events`) but current deploys do not serve them.

### 3.2 Users and entity bootstrapping — why all emails are fake

Users and products are created "on first sight" from ids (`ensure_entities` in `catalog.py`): email is a placeholder `user{uid}@example.com` and profile attributes (region, signup_channel, device, age_band, marketing_opt_in ~62%) are **deterministically synthesized from the uid hash** (`novamart/onboarding.py`). The signup form data never reaches this backend. Consequences ripple through every "customer" metric (see §4.3). 40 users later got emails updated via `POST /users/{id}/email` (commit `088a372`) — to `cust…@gmail.example`, still a reserved test TLD.

### 3.3 The money path

For each gateway callback `{uid, pid, price, ref, session, ts}` (`orders.py`):

1. Idempotency: if the `ref` was seen (on `orders.payment_ref` or `order_lines.payment_ref`), replay — insert the missing `payments` row at most once (`order_callback_replayed` in app logs). Added `b676969` (2019-10-15) after two weeks of duplicate orders (see §4.1 caveat 3).
2. Merge: else if the same `session` produced an order in the last 15 minutes, add the item to it: `orders.price += price`, append `order_lines`, insert `payments` (`order_appended`). Added `5d1300d` (2019-11-22).
3. Create: else insert a new order (status 0 → 1 in the same transaction), plus `order_lines` + `payments` (`order_created`).

Every `payments` row records `gross = price`, `fee = round(price*0.029 + 0.30, 2)` (flat 30¢ since 2019-11-20, commit `12e1c68`; before that `price*0.029` only), `net = price - fee`. **Fees are per callback**, so a 3-item merged order collects 3×30¢.

Order status lifecycle (from `constants.py` and code): `0` created/pending (transient), `1` paid/active, `2` cancelled, `3` refunded (v1), `6` fraud hold (`fraud_score.py`), `5` referenced only in `reconcile.py` (`status <> 5`) and **never occurs in data** (`SELECT status, COUNT(*) FROM novamart.orders GROUP BY 1` → only 1, 2, 3, 6).

### 3.4 Refunds and chargebacks

- **v1 refund** = status flip to 3. No payments impact. 28 orders, $13,447.47 total price.
- **Cancellation** = status 2. 54 orders, $13,249.64.
- **v2 gateway refund** (since Dec 5) = negative `payments` row (`gross = -amount, fee = 0`), **order stays status 1**. 9 rows, −$1,843.59, Dec 13–27.
- **Chargebacks** live only in analytics: `novamart_analytics.chargebacks` — 3 October orders, $3,567.57, booked retroactively on 2019-12-09 by an engineer backfill (`[engineer-backfill:dev]` statements in `novamart_logs.db_queries` at 2019-12-09 15:00; commit `cd559d3` added the dashboard file the same day).
- The **refunds dashboard** (Redash query 6) reads `analytics.refunds_unified` (view created 2019-12-23, log line `[engineer-backfill:dev] CREATE OR REPLACE VIEW analytics.refunds_unified …`; commit `a3bffec`), which unions all three kinds. Caveats: it counts *cancellations* as refunds at full order price, timestamps status-flips by `updated_at` (a later hold/release would re-date them), and I verified 0 orders are double-counted today (no status-2/3 order also has a negative payment) — but nothing structurally prevents it.

### 3.5 Fraud

Nightly `fraud_score.py` (since `e4656fb`, 2019-12-03; runs 05:45 ET) scores last-day status-1 orders: `score = min(price/3000, 1) * (1 + 0.15*new_account + 0.15*high_velocity)`, cap 1.0; above `FRAUD_HOLD_THRESHOLD` → status 6. History: threshold 0.70 (`53f6f6c`, Dec 5) → 0.85 (`1cb8721`, Dec 29, Maya Iyer), with a manual release the same day — log line 2019-12-29 15:00 `[engineer-backfill:maya] UPDATE orders SET status = 1 … WHERE status = 6 AND price < 2600;` (5 orders, $10,859.73, confirmed by joining `order_risk` to orders with `updated_at >= '2019-12-29'`). 12 orders remain held ($40,213.29), including a cluster of 7×$2,999.99 orders created 2019-12-03 — the apparent fraud burst that motivated the feature. Note Maya's first two ad-hoc queries that day referenced non-existent columns (`total_amount`, `fraud_score`) — the working query used `price`.

### 3.6 Brand hygiene: lucente, jetem, blank brands

- `lucente`: a large vendor import starting ~Oct 1; hidden from reports "per partnerships" (commit `ba1fbfa`, 2019-10-25).
- `jetem`: hidden 2019-12-15 (commit `1169e40`). Both live in `constants.BRAND_DENYLIST` and are hard-coded in all exec dashboard SQL (`p.brand NOT IN ('lucente','jetem')`).
- **17,442 of 81,018 products (21.5%) have blank brand**; 33,514 blank category (`novamart.products`). Root causes documented in `analytics.blank_brand_products` (5,972 rows with revenue; created by `[engineer-backfill:dev]` 2019-10-21, same day as repair commit `ea0e97b`): products first seen via the view/order path get no catalog metadata, and `ON CONFLICT DO NOTHING` + an in-process known-id cache prevented later repair. `_repair_product_brand` (in `catalog.py`) now fixes brands when catalog events arrive. Blank brands appear as `''` rows in `brand_revenue` (or `'unbranded'` in the unmounted `/reports/brands`).

### 3.7 Platform history in one paragraph

Sep 15: initial import (`2da4141`), dashboards as SQL files, jobs on cron (`crontab.txt`). Oct–Dec: the incident-driven evolution below (§Appendix A timeline). Jan 2–5, 2020: platform migration — docs (`1179287`), dashboards → Redash (`57ea43a`), cron → Airflow (`43e54a1`), Postgres → BigQuery backfill (`2ae79e2`, `docs/data-access.md`). Airflow DAGs are 1:1 wrappers (`airflow/dags/*.py`, all `BashOperator("python -m novamart.jobs.<job>")`) — **except** `intraday_report`: crontab ran it at 12:00 *and* 17:00; the DAG only has `schedule="0 12 * * *"`, so the 17:00 refresh was silently dropped in the migration.

## 4. Metrics

### 4.1 "What was revenue in month X, and why" — the tenured-analyst answer

**Definitions.** Statement gross = `SUM(orders.price)` for `status = 1`, order `created_at` within the **America/New_York** calendar month (`monthly_statement.py`, `timeutil.local_month_window_utc`; `constants.LOCAL_TZ`). Fee = `SUM(payments.fee)` joined to those orders (collected, since `a92c96d`). Net = gross − fee. Published append-only to `novamart.statements` on the 1st at 06:30 ET.

**The three surfaces** (use the right one for the question):

| Month | `statements` (as published) | `statements_corrected` | `statements_final` (current finance truth) |
|---|---|---|---|
| 2019-09 | gross 2,702.00 / fee 78.36 / net 2,623.64 / 12 orders | same | same |
| 2019-10 | 1,230,332.43 / 35,679.64 / **1,194,652.79** / 3,765 | fee 35,679.50 / net **1,194,652.93** | gross 1,226,764.86 / net **1,191,085.36** |
| 2019-11 | 1,101,397.01 / 32,110.92 / **1,069,286.09** / 3,582 | same | same |
| 2019-12 | **missing** — snapshot predates the Jan 1 run | — | — |

(Queried directly from `novamart.statements`, `novamart_analytics.statement_overrides`, `novamart_analytics.statements_final`; policy in `docs/restatement_policy.md`: "match the old deck" → `statements`; "current number" → `statements_final`.)

**Why October was restated twice:**
1. The Nov 1 statement run used the *old* fee formula (`fee = gross*0.029`, pre-`a92c96d` code) → published fee 35,679.64. The collected per-order fee was 35,679.50 (a +0.14 rounding artifact of computing 2.9% on a monthly total instead of per order). Fixed in code Nov 2 (`a92c96d`) and booked as a row in `statement_overrides` (log: `[engineer-backfill:dev]` 2019-11-02 14:00, note "Corrected to sum of per-order collected payment fees"); `statements_corrected` view applies overrides by `COALESCE`.
2. On Dec 9 finance booked 3 October chargebacks ($3,567.57) into `analytics.chargebacks` and created `statements_final`, which subtracts chargebacks from the *order's* month (view definition in `novamart_analytics.INFORMATION_SCHEMA.VIEWS`).

**Why November triggered a fee alarm but no restatement:** the Dec 1 run logged `statement_fee_mismatch` with `delta = -170.41` (`app_events`, 2019-12-01 11:30). Cause: the *expectation* formula still lacked the Nov 20 flat fee; 568 post-change orders × $0.30 = $170.40. The published (collected) fee was correct. Commit `4a58d17` (Dec 2) made the expectation piecewise around `FEE_CHANGE_AT = 2019-11-20 00:00 ET` and booked a **zero-delta** row in `statement_corrections` ("November 2019 processor fee change audit correction") purely as an audit record.

**Caveats a veteran would recite:**
1. **You cannot reproduce a published statement from today's orders.** Statuses drift: October recomputes to 1,206,337.32 / 3,695 orders today (−70 orders vs published) because of post-publication cancels/refunds/holds; September recomputes to **zero** (all 12 orders — 11 of them created 02:45–03:55 UTC Oct 1, i.e. the evening of Sep 30 ET — were later cancelled/refunded).
2. **Gateway refunds (v2) never reduce any statement**: order stays status 1, negative payment has fee 0. December's −$1,843.59 of gateway refunds is invisible to gross and net-via-fee.
3. **October's published gross contains $58,828.24 of duplicate orders** (151 still-status-1 dupes from pre-idempotency gateway retries, all Oct 1–15; identified by grouping `orders.payment_ref HAVING COUNT(*)>1`). Never restated, never repaired; `reconcile` (03:00) has re-flagged the same ~130 refs nightly since Oct 1 — 10,766 `duplicate_payment_ref` warnings and zero fixes. Batch was bumped 100→200 in `030d841` after it was noticed the cap hid the count.
4. **Timezone**: all monthly/daily windows are NY-local; the warehouse stores UTC. Grouping by UTC month puts ~11 late-Sep-30-ET orders into October.
5. **December statement does not exist in the warehouse snapshot** — anyone asking "December revenue" must recompute (552,328.93 status-1 gross as of the snapshot) and label it non-final.

### 4.2 Daily/product revenue: report snapshots vs orders

`report_rows` (written 06:00 ET by `daily_report.py` for yesterday) and `report_rows_intraday` (12:00 ET, today-so-far; table created by backfill 2019-12-08, commit `a2e0013`) power `daily_kpis` and `revenue_widget`. Rules baked into the job (`daily_report.py` + `constants.py`): counts *item* rows (order_lines since Nov 22, `92596dc`-style union with legacy fallback), skips statuses {0,2,3} (cancelled/refunded excluded since `11c0a42`, Nov 18), excludes `analytics.test_users` (QA uid 424242, inserted by backfill Nov 27; commit `b59f077`), excludes SKUs {1004856, 1002544} (`83fb3ed`) and brands lucente/jetem. Notes:

- Snapshots are **not rerun** when history changes (one `created_at` version per `report_date` in the whole snapshot). A cancel after 06:00 stays in the report forever; statements will disagree.
- **2019-11-17 is permanently wrong** in `report_rows`: 487 units / $148,857.07 vs 735 / $229,780.49 in orders — the `REPORT_SCAN_CAP = 500` `fetchmany` bug on spike days, fixed Nov 19 (`1233af8`) without backfilling. Nov 16 is mildly low (383 vs 401). The constant still sits in `constants.py` but is dead code.
- The DST fall-back day (Nov 3) is handled *since* `102c9b4` (Nov 5): `local_day_window_utc` computes both local midnights ("some local days are not exactly 24 hours"). The Nov 2–3 reports themselves predate the fix.
- `revenue_widget` (Redash query 8) sums the **latest version** of `report_rows` for the prior 6 days + latest `report_rows_intraday` for today. Before `3eced24` (Dec 24) it double-counted: it summed *all* intraday snapshots for the last 7 days on top of finals — the exec screen over-reported revenue Dec 19–24 (widget created `686a5d6`, Dec 19).

### 4.3 Customer counts — three coexisting definitions (all different, one broken)

Per `docs/metrics_definitions.md` (verified against code/SQL/data):

| Surface | Definition | Current value @ snapshot | Trust |
|---|---|---|---|
| `analytics.kpi_daily.active_customers` (nightly `kpi_daily.py`, since `14726e7` Nov 16) | distinct buyers, trailing 30×24h, status=1, **no exclusions** | 1,152 (2019-12-31 row) | Fine as trend; includes QA user |
| `daily_kpis` dashboard (Redash query 5) | distinct ordering users per ET calendar day, **no status filter**, excludes uid 424242 and lucente/jetem products | per-day series | Fine; different beast (per-day, includes cancelled) |
| `actives_board` (Redash query 1, commit `2dde4f0`) | trailing 30d, status ∉ {0,2,3}, minus `test_users`, minus internal/test-ish **email heuristics** | **always 0** | **Broken.** Every user email is `@example.com` or `@gmail.example`; both are excluded. Reproduced in BigQuery: 0. |
| `daily_kpis.contactable_customers` | buyers ∩ `analytics.contactable_users` (view: opt-in + valid non-example email; `[engineer-backfill:maya]` Dec 4; commit `e10cb0c`) | **always 0** (view is empty: 0 rows) | **Broken** for the same reason. |

The `email_digest` job's own "recipients" count uses a *fourth* definition (`email NOT LIKE '%@example.com'`) which the `.example`-TLD updates *do* pass → `digest_log.recipients = 40` every run. So the marketing digest claims 40 reachable customers while the KPI dashboard says 0 contactable.

### 4.4 Product dashboards

All four exec product dashboards (Redash queries 2,3,4,5 = old `dashboards/*.sql`, per `docs/dashboard_notes.md`, verified identical) share: the `item_orders` CTE (order_lines + legacy fallback, `92596dc`), rolling windows anchored at `now()` (7d best_sellers, 30d brand/category), uid 424242 excluded, lucente/jetem excluded. Specifics:

- **best_sellers**: **no status filter** (cancelled/refunded/held orders count!) and ranked by *revenue* despite showing units. A hand query filtered to status=1 will read low. Contrast with the nightly `top_sellers.py` job (`top_products` table): status=1 only, counts whole orders (ignores `order_lines` — merged multi-item orders count once), no QA/brand/SKU exclusions. **The dashboard and the job disagree by design; neither is "the" best-seller list.**
- **brand_revenue**: extra exclusion `user_id::text NOT IN ('424242','cc27b436-d6f9-4e84-adaf-e716025dd369')` (commit `adbcb7e`) — the UUID is the QA account created in the Dec 1 accounts beta (`account_map`: uid 424242 ↔ `cc27b436-…`). Since `orders.user_id` is numeric, the UUID leg can never match: **defensive dead SQL**.
- **category_revenue**: maps `products.category` codes → display groups via `category_names` (+ `category_name_history` at lower priority) with `valid_from <= order date` (commits `2814b3d`, `33054cd`). **Gotcha:** the 6 history rows (`electronics.audio.*` → 'entertainment', `construction.tools.light` → 'lighting') carry `valid_from = 2026-08-13` — far after every order — so the "versioned, history-preserving" mapping is inert and the current taxonomy applies retroactively. Evidence: `SELECT * FROM novamart_analytics.category_name_history` and the Dec 12 backfill statements which used `CURRENT_DATE` as `valid_from` (`db_queries` 2019-12-12 20:00). Unmapped codes fall to `'other'`.
- **registered_conversion** (Redash query 7, commits `d6e34c6` + fix `b975479`): joins `accounts → users` **by email** to translate UUID accounts to legacy uids (the two id namespaces are not castable — the fix's whole point), then counts status-1 buyers/revenue: 30 buyers / $18,155.71 reproduced in BigQuery. Since placeholder emails are unique per uid this works, but it silently assumes email uniqueness.

### 4.5 Funnel

`analytics.daily_funnel` (`funnel.py`, since `4dbcf7f` Nov 8): sessionizes cart+order events over the trailing 1 day with an inactivity gap — 30 min originally, **120 min since `f915c1b` (Dec 14)**, so session counts before/after Dec 14 are not comparable. It sessionizes by user timestamps (ignores the actual `session` field on the events).

## 5. System

### 5.1 Components

```
storefront/gateway → FastAPI app (novamart/app.py; routers catalog, carts, orders, similar, payments_webhook)
                        └── Postgres (public schema = serving tables; analytics schema = batch outputs)
cron (crontab.txt, retired) → Airflow (airflow/dags/*.py, Jan 2020) → python -m novamart.jobs.<job>
logs: app.jsonl / jobs.jsonl / db_queries.log (novamart/logutil.py, db.py — every SQL statement logged)
   → exported to BigQuery: novamart_logs.app_events / job_runs / db_queries (+ view db_queries_normalized)
warehouse: novamart.jobs.warehouse_backfill (manifest-driven gcloud sql export csv → bq load --replace)
dashboards: Redash (9 dashboards/queries, Postgres dialect, pointed at the serving replica)
```

Deploys are marked by `trigger deploy #d2p-novamart` commits; feature flags in `deploy/flags.env` (`REC_MODEL_VERSION=2.0.0`), cron env in `deploy/cron.env` (`ENABLE_DIGEST=1`). CI (`ci/run_ci.py`) boots the app on a scratch DB, exercises view→cart→order, then runs reconcile/daily_report/monthly_statement under `FAKE_NOW`.

### 5.2 The scheduled jobs — what each produces and what breaks when it fails

Times are ET (crontab) / UTC-equivalent cron in Airflow DAGs. Run counts from `novamart_logs.job_runs` (978 rows total, Sep 16 – Dec 31).

| Job (module) | Schedule | Writes | Consumers / blast radius on failure |
|---|---|---|---|
| `reconcile` | 03:00 (moved from later by `388370b`, **overlaps the backup window** — known tradeoff) | nothing; WARN logs only | Fraud/duplicate visibility only. 214 log rows. |
| `affinity` | 03:30 | `analytics.product_affinity` (full rewrite; −1 sentinel for <3 pairs, `fef5c96`) | **Nothing serves it since Dec 6** (`docs/affinity_lineage.md`); still burns compute. 80 runs. |
| `affinity_v2` | 03:45 | `analytics.product_affinity_v2` (rewrite; conversion-weighted, seasonal factor) | Similar-products widget (exploit arm) + `model_train` candidates. Failure → widget serves stale scores until `updated_at=MAX(updated_at)` filter finds them, then falls back to trending. Crashed Dec 3–5 (§7.3). |
| `model_train` | 04:15 | `analytics.model_registry`, `model_scores` (rewrite) | Only the flag-gated 4.0.0 path (not live). 17 runs since Dec 15. |
| `price_suggest` | 04:45 | `analytics.price_suggestions` (rewrite, top-500) | **Nobody** — shadow only, phase 2 on hold per exec/legal (`cca9b0d`, file NOTE, `docs/pricing_status.md`). |
| `trending` | 05:15 | `analytics.trending_daily` (per-day rows) | Homepage trending AND the rec widget's fallback (~80% of serves!) — the single most load-bearing "ML" table. Failure → widget serves *yesterday's* trending (reads `MAX(day)`). 59 runs. |
| `fraud_score` | 05:45 | `analytics.order_risk` + mutates `orders.status` 1→6 | Held revenue; statements (status 6 excluded from gross). 28 runs. |
| `daily_report` | 06:00 | `report_rows` (append) | `daily_kpis`, `revenue_widget` history. Failure → dashboard day gap; **no automatic backfill** (ops helper `scripts/rerun_kpis.py` is a stub). 107 runs, no gaps. |
| `kpi_daily` | 06:15 | `analytics.kpi_daily` (append) | 30d actives trend. 45 runs. |
| `funnel` | 06:20 | `analytics.daily_funnel` (append) | Funnel reporting. 53 runs. |
| `monthly_statement` | 06:30 on the 1st | `novamart.statements` (append) | Finance. Failure = missing month (December!). 3 runs. |
| `top_sellers` | 06:45 | `novamart.top_products` (append) | Merch ops. 55 runs. |
| `reorder_forecast` | 06:50 | `analytics.reorder_hints` (rewrite, top-200) | ADVISORY only (`docs/forecast_caveats.md`, README): `hint = 15.6 + 162.4/(velocity+1.8)` — hints *rise* as velocity falls; K refit for Q4 in `f85cdd2`. Do not buy inventory from this. 35 runs. |
| `email_digest` | 07:15 | `analytics.digest_log` | Marketing. **Silently skipped Nov 28–Dec 16**: the `ENABLE_DIGEST` flag never reached the job env (fix attempts `8dc520b` Dec 9, working fix `0bd4eac` Dec 16 — job now reads `deploy/cron.env` directly). First real run Dec 17; 15 runs. |
| `intraday_report` | 12:00 (+17:00 in cron, **dropped in Airflow**) | `report_rows_intraday` (append) | Today's row in `daily_kpis`/`revenue_widget`. 47 runs since Dec 8. |
| `warehouse_backfill` | manual (`schedule=None`) | all of BigQuery `novamart` + `novamart_analytics` | The entire warehouse is a one-shot copy; **BQ is stale the moment it lands** until re-triggered. |

Safe-modification notes: rewrite-style jobs (`affinity*`, `model_scores`, `price_suggestions`, `reorder_hints`) `DELETE` then `INSERT` with one `updated_at`/`created_at` per batch — consumers key on `MAX(updated_at)`/`MAX(day)`, so partial failures between DELETE and INSERT leave an empty table until the next run (the widget tolerates this via trending fallback; nothing else reads them). Append-style tables (`report_rows*`, `statements`, `kpi_daily`) rely on "latest `created_at` per key" semantics in consumers — if you rerun a day manually, that's what makes it safe. All jobs are wall-clock (`timeutil.now()`, `FAKE_NOW` only for tests) — **Airflow backfills/catchup would NOT recompute historical windows**; `catchup=False` everywhere is deliberate.

### 5.3 Logs — how to reconstruct anything

- `novamart_logs.app_events` (1,570,017 rows): `jsonPayload.event` ∈ {product_viewed, cart_item_added/removed, order_created/appended/callback_replayed, order_cancelled/refunded, gateway_refund, rec_served, price_feed_received, account_created, user_email_updated, statement_fee_mismatch, duplicate_payment_ref, digest_sent…}. `duration_ms` on order creation since `7f24380`.
- `novamart_logs.db_queries` (3,597,650 rows): every SQL statement with an actor tag — `[app]` 3.27M, `[job]` 331k, `[engineer:dev]` 107, `[engineer:maya]` 52, `[engineer-backfill:dev]` 29, `[engineer-backfill:maya]` 3. The engineer-backfill lines are the **provenance of every manually-created analytics artifact** (test_users, statement_overrides/corrections, chargebacks, category tables, contactable_users, refunds_unified, the held-order release). Saved to `engineer_backfills.csv` in this run's folder.
- `novamart_logs.db_queries_normalized` (view): reshapes the text log into a BigQuery-JOBS-like schema (parses actor → `user_email`, extracts referenced tables by regex).
- `novamart_logs.job_runs` (978 rows): one JSON line per job event; `severity='ERROR'` only for the three affinity_v2 crashes.

## 6. Data

### 6.1 Datasets and tables (BigQuery, project `<warehouse-project>`)

**`novamart` (serving-table mirror, 12 tables):** `users` (38,950), `products` (81,018), `cart_items` (36,938), `orders` (9,127; ids 1–9,653 with gaps from merged/CI ids), `order_lines` (2,284; only since 2019-11-22 — older orders have no lines, hence every "legacy fallback" union), `payments` (9,361; ≥1 per order, several for merged orders, negative rows = gateway refunds), `report_rows` (6,923), `report_rows_intraday` (2,358), `top_products` (2,396), `statements` (3), `accounts` (30), `account_map` (30).

**`novamart_analytics` (24 objects):** batch outputs (`kpi_daily` 45, `daily_funnel` 53, `trending_daily` 2,898, `product_affinity` 3,912, `product_affinity_v2` 3,912, `model_scores` 948, `model_registry` 17, `rec_decision_log` 667,850, `order_risk` 1,631, `price_suggestions` 500, `reorder_hints` 200, `price_history` 1,400, `digest_log` 15), finance corrections (`statement_overrides` 1, `statement_corrections` 1, `chargebacks` 3), reference/QA (`test_users` 1 row = 424242, `category_names` 135, `category_name_history` 6, `blank_brand_products` 5,972), and 4 views (`statements_corrected`, `statements_final`, `refunds_unified`, `contactable_users` — definitions in `INFORMATION_SCHEMA.VIEWS`, quoted in §3.4/§4.1).

**`novamart_logs`:** `app_events`, `db_queries`, `job_runs`, view `db_queries_normalized` (§5.3).

### 6.2 Source-of-truth ranking (when numbers disagree)

1. **Money moved:** `payments` (per commit `c49a7bb`: "gateway is source of truth for money"). Includes duplicates' payments and negative refunds.
2. **Order state:** `orders.status` — but it is *current* state; historical state must come from `app_events`/`db_queries`.
3. **Item-level sales:** `order_lines` with legacy `orders` fallback (the `item_orders` CTE idiom).
4. **Published finance:** `statements` (frozen) → `statements_corrected` → `statements_final` (current), per `docs/restatement_policy.md`.
5. **Dashboards:** derived; each carries its own filter set (§4).

### 6.3 Data quality registry (the things that bite)

| Issue | Evidence | Status |
|---|---|---|
| 151 duplicate status-1 orders, $58.8k, all Oct 1–15 | `orders.payment_ref` group-by; `duplicate_payment_ref` warnings | Unrepaired, unrestated |
| All user emails placeholder → board actives = 0, contactable = 0 | `users` domain counts: example.com 38,910 / gmail.example 40 | Structural; every email-based metric is dead |
| Nov 17 report_rows −$81k vs orders | §4.2 comparison query | Permanent (no rerun) |
| Gateway refunds don't touch order status | `payments.gross<0` orders all status 1 | By design; revenue overstated by refunded amounts |
| `category_name_history.valid_from = 2026-08-13` | table scan; Dec 12 backfill used `CURRENT_DATE` | Taxonomy renames are retroactive on dashboards |
| 21.5% products blank brand | `blank_brand_products` + `products` scan | Partially repaired go-forward (`ea0e97b`) |
| `order_lines` starts 2019-11-22 | `MIN(created_at)` | All item-level queries need the legacy fallback |
| December statement absent | `statements` has 3 rows | Recompute + label if asked |
| `top_products` ignores exclusions & merged lines | `top_sellers.py` | Differs from best_sellers dashboard by design |
| Redash queries anchored at `now()` | query texts | Against the frozen replica, "last 7/30 days" windows return empty/stale results today |

## 7. Experimentation

### 7.1 Recommendation system versions (the only real experiment surface)

`GET /products/{pid}/similar` (`routers/similar.py`, `docs/rec_versions.md` is "TBD" — this section replaces it):

- **v1 `1.0.0`** (retired): nightly `affinity.py` co-cart counts (since `776d674`, Oct 12), widget launched `f1217a8` (Oct 26). Served `analytics.product_affinity` until Dec 6.
- **v2 `2.0.0`** (live, `deploy/flags.env`): `affinity_v2.py` (commit `89666bf`, Dec 2) — conversion-weighted (cart=1, order=3), same-category ×1.15, extreme price-ratio ×0.7, monthly seasonal factor; rows stamped `model_version='2.0.1'` (writer version ≠ serving version — known naming wart, `docs/affinity_lineage.md`). Dispatch commit `df4ed85` (Dec 6).
- **v4 `4.0.0`** (flag-gated, not live): nightly logistic regression on random-arm exposures (`model_train.py`, commit `a1946ff`, Dec 14; first registry row Dec 15). Label = "user placed *any* later order" (leaky/weak). Scoring multiplies every affinity-v2 score by `(1 + 0.1*coef[0])` — **rank-preserving; if flipped on, rankings would be identical to v2**. Coefficients are unstable across nights (sign flips in `model_registry.coef_json`), train_rows 4,197 → 14,411.
- **Random arm**: 5% of users (`sha256(uid) % 20 == 0`) get uniform-random items — the unbiased training data. Decision logging for it was lost in the Dec 17 refactor (`30e8907`) and restored Dec 19 (`a00f24c`): `rec_decision_log` has **0 random rows on 2019-12-18**, and `model_registry.train_rows` stalls at 5,798 for Dec 18–19.
- Serving caches scores in-process for 6h, invalidated when the table's `MAX(updated_at)` changes (`8ed2971`, Dec 26).

### 7.2 Does it work? (measured, Dec 6–31, `rec_decision_log` × `orders`)

Purchased-a-recommended-item within 3 days of the serve:

| source | serves | conversions | rate |
|---|---|---|---|
| model (affinity v2) | 52,695 | 525 | **0.996%** |
| fallback (trending) | 212,898 | 475 | 0.223% |
| random arm | 14,566 | 0 | 0.000% |
| affinity v1 (Dec 6 residual) | 1,313 | 1 | 0.076% |

Read with care: exploit serves are biased toward popular co-carted products, so this is not a clean uplift estimate — but the random arm's zero over 14.5k serves is strong evidence uniform-random recs are worthless, and v2-when-available beats the trending fallback ~4.5×. **The bottleneck is coverage, not ranking:** 76% of all decisions since launch are fallbacks (`fallback_reason='no_scores'` 509,054 / 667,850) because the graduation gate (score −1 for <3 co-cart pairs, `fef5c96`) plus 30-day windows leave most base products scoreless. Any real improvement effort should attack coverage before models.

### 7.3 Experiment/ops incident log

- **affinity_v2 December crash:** `SEASONAL_FACTORS` had 11 entries (Jan–Nov, "from the 2019 planning sheet"); on Dec 1–5 the job died with `IndexError: list index out of range` at `SEASONAL_FACTORS[t.month - 1]` (3 ERROR rows in `job_runs`, Dec 3/4/5 08:45). Fixed by bounds-check → season=1.0 for December (`3dbe4d7`, Dec 5). Widget kept serving via v1/fallback; first clean v2 run Dec 6 — the same day serving switched to it.
- **Random-arm logging gap Dec 18** (§7.1) — one day of training data lost.
- **Dynamic pricing:** phase-1 shadow only (`894c535`, Nov 24); phase 2 held per exec/legal review (`cca9b0d`, Dec 2). `price_suggestions` refreshes nightly, zero readers (verified: only writer statements in `db_queries`; `docs/pricing_status.md`).
- **Trending window change:** 60d → 30d (`f563dea`, Dec 6) — the December "trending churns faster" effect; README's 60-day claim is stale (`docs/trending_notes.md`).
- **Fraud threshold experiments:** 0.70 (Dec 5) → 0.85 + manual release (Dec 29), §3.5.

## 8. Glossary

| Term | Meaning (with source) |
|---|---|
| **active customers** | Ambiguous — three definitions (§4.3). Always ask "which surface?" |
| **actives_board** | Board-deck Redash query (id 1); structurally returns 0 (§4.3). |
| **affinity / affinity_v2** | Co-cart similarity tables; v2 is conversion-weighted and the one actually served (`docs/affinity_lineage.md`). |
| **arm** | `rec_decision_log.arm`: `random` (5% uniform-random serving) or `none`. |
| **chargeback** | Analytics-only negative adjustment in `analytics.chargebacks`; subtracted by `statements_final` from the order's month. |
| **contactable** | In `contactable_users` view: opt-in + real-looking non-example email. Empty in practice. |
| **fallback** | Rec widget serving `trending_daily` when no scores exist (`rec_source='fallback'`). ~76% of serves. |
| **FEE_CHANGE_AT** | 2019-11-20 00:00 ET — processor fee became 2.9% + $0.30 (`12e1c68`; constant in `monthly_statement.py`). |
| **graduation gate** | Affinity pairs seen <3 times get score −1 (sentinel = "not enough data", NOT negative preference); serving filters `score >= 0` (`fef5c96`, `affinity.py` docstring). |
| **held order** | `orders.status = 6`, set by `fraud_score` above threshold; excluded from statements (status≠1). |
| **item_orders CTE** | The `order_lines` + legacy-orders union idiom every item-level query must use (`92596dc`). |
| **jetem / lucente** | Brands hidden from all reports/dashboards (`1169e40`, `ba1fbfa`; `BRAND_DENYLIST`). |
| **merge (order)** | Same-session callbacks within 15 min appended to one order (`5d1300d`); `orders.price` = total, `order_lines` = items. |
| **order status** | 0 pending, 1 paid, 2 cancelled, 3 refunded, 6 fraud-held; 5 referenced in `reconcile.py` but never used. |
| **payment_ref** | Gateway idempotency key (`PR-…`); unique per callback since `b676969`; duplicated across 285 pre-fix orders. |
| **random arm** | `sha256(uid)%20==0` users get uniform-random recs — training data for v4. |
| **replay** | Duplicate callback absorbed idempotently (`order_callback_replayed`). |
| **report snapshot** | Append-only `report_rows(_intraday)` row-set per date; dashboards take latest `created_at` per date. |
| **restatement** | Post-publication change to a month, via `statement_overrides` (corrections) or `chargebacks` (`docs/restatement_policy.md`). |
| **statement** | Append-only monthly finance row in `novamart.statements` (as-published). |
| **statements_final** | View = corrected statements − chargebacks; the current finance number. |
| **test user 424242** | QA smoke account (`session: "qa-smoke"`); in `analytics.test_users`; its UUID account is `cc27b436-…`. |
| **trending** | 30-day (was 60), min-5-units, recency-decayed top-50 (`trending.py`, `f563dea`); doubles as rec fallback. |
| **v1/v2/v4, 2.0.1** | Rec serving versions; 2.0.1 is the *writer* stamp inside the v2 table (naming wart). |

---

## Appendix

### A. Company timeline (from `git log`, 112 commits, cross-checked with logs)

| Date | Event | Evidence |
|---|---|---|
| 2019-09-15 | Initial import: app, daily_report/reconcile/monthly_statement/top_sellers, dashboards | `2da4141` |
| 2019-09-16 | First job runs (empty DB) | `job_runs`, `db_queries` |
| 2019-09-25 | First real traffic; QA order id 1 (uid 424242) | `orders`, `app_events` |
| 2019-10-01 | Lucente catalog import begins; first duplicate orders appear | `docs/dashboard_notes.md`; payment_ref dupes |
| 2019-10-01 | First statement (Sep: 2,702 / 12 orders) + first fee-mismatch warning (−0.01 rounding) | `statements`; `app_events` |
| 2019-10-08 | Test SKUs excluded from daily report | `83fb3ed` |
| 2019-10-12/13 | Affinity v1 job ships / first run | `776d674`; `job_runs` |
| 2019-10-15 | **Idempotent callbacks by payment_ref** — duplicate-order era ends | `b676969` |
| 2019-10-16 | Email update endpoint (+audit log) | `088a372` |
| 2019-10-18 | Reconcile batch 100→200 | `030d841`; early `db_queries` show `(100,)` |
| 2019-10-21 | Blank-brand repair + `blank_brand_products` capture | `ea0e97b`; backfill log 14:00 |
| 2019-10-25/26 | Lucente hidden; similar-products widget launches | `ba1fbfa`, `f1217a8`; `rec_decision_log` starts 10-26 |
| 2019-10-28 | Cancel endpoint, status 2 | `8f19718` |
| 2019-11-02 | **Statement fee fix (collected per-order fees) + October override booked** | `a92c96d`; backfill log |
| 2019-11-02/03 | Trending job ships; DST fall-back | `152a760`; DST fix `102c9b4` (Nov 5) |
| 2019-11-08/09 | Funnel job ships / first run | `4dbcf7f`; `daily_funnel` |
| 2019-11-10 | Reconcile moved to 03:00 (overlaps backup window) | `388370b` |
| 2019-11-15 | Refund endpoint (status 3); price_history capture | `d87cb3d`, `795d273` |
| 2019-11-16/17 | Traffic spike (349/770 order_created); **500-row scan cap truncates reports** | `app_events`; §4.2 |
| 2019-11-16 | kpi_daily ships | `14726e7` |
| 2019-11-18/19 | Cancelled/refunded excluded from daily report; **scan cap removed** | `11c0a42`, `1233af8` |
| 2019-11-20 | **Processor fee change: 2.9% + $0.30** | `12e1c68` |
| 2019-11-22 | **Same-session order merging; `order_lines` born** | `5d1300d`; `MIN(order_lines.created_at)` |
| ~2019-11-23 | **Order volume halves (~115→~40/day), views flat** — demand-side | `app_events`, `payments` |
| 2019-11-24 | Dynamic pricing phase 1 (shadow) | `894c535` |
| 2019-11-26/27 | Reorder hints job; QA exclusions (`test_users`); accounts endpoint | `f5e3032`, `b59f077`, `b567d9d` |
| 2019-11-28 | Email digest ships — **but never runs (env flag bug)** | `c19a307`; `digest_log` empty until 12-17 |
| 2019-11-30 | Category revenue dashboard + `category_names` backfill | `2814b3d`; backfill log 20:00 |
| 2019-12-01 | Accounts beta: 30 accounts incl. QA; Nov statement (fee mismatch −170.41) | `accounts`; `app_events` |
| 2019-12-02 | Affinity v2 ships; pricing phase 2 held; **statement expectation fixed + zero-delta Nov audit correction** | `89666bf`, `cca9b0d`, `4a58d17`; backfill log |
| 2019-12-03–05 | **affinity_v2 crashes (Dec seasonal IndexError)**; fraud_score ships (thr 0.70); fix `3dbe4d7` | `job_runs` ERRORs; `e4656fb`, `53f6f6c` |
| 2019-12-05 | Gateway refund webhook (v2 refunds); item-level dashboards (`item_orders` CTE) | `c49a7bb`, `92596dc` |
| 2019-12-06 | **Widget switches to v2 + random arm**; trending window 60→30d | `df4ed85`, `f563dea` |
| 2019-12-08/09 | Intraday reports + KPI dashboard include them; **chargebacks + `statements_final`**; digest flag fix #1 | `a2e0013`, `cd559d3`, `8dc520b`; backfill logs |
| 2019-12-10/11 | registered_conversion dashboard; actives_board dashboard | `d6e34c6`, `2dde4f0` |
| 2019-12-12 | Versioned taxonomy (history rows inert — future valid_from) | `33054cd`; backfill log |
| 2019-12-14/15 | Funnel gap 30→120 min; **rec model v4 ships** / first training | `f915c1b`, `a1946ff`; `model_registry` |
| 2019-12-16/17 | Digest fix #2 (reads cron.env directly) → first digest run (recipients=40) | `0bd4eac`; `digest_log` |
| 2019-12-17–19 | Refactor drops random-arm logging (Dec 18 = 0 rows); restored + score cache | `30e8907`, `a00f24c` |
| 2019-12-19 | revenue_widget ships (double-counting) | `686a5d6` |
| 2019-12-21 | registered_conversion UUID→uid fix; reorder K refit | `b975479`, `f85cdd2` |
| 2019-12-23/24 | refunds_unified view + dashboard; **revenue_widget double-count fix** | `a3bffec`, `3eced24`; backfill log |
| 2019-12-26 | Cache invalidation on affinity refresh | `8ed2971` |
| 2019-12-29 | **Fraud threshold 0.70→0.85 + manual release (<$2600: 5 orders, $10,859.73)** | `1cb8721`; backfill log 15:00 |
| 2020-01-02–05 | Platform migration: docs, Redash, Airflow, BigQuery backfill | `1179287`, `57ea43a`, `43e54a1`, `2ae79e2` |

### B. How each dashboard's number is produced (quick reference)

| Redash dashboard (id) | Reads | Window | Key filters / gotchas |
|---|---|---|---|
| actives_board (1) | orders, users, test_users | rolling 30d | status ∉{0,2,3}; email heuristics → **always 0** |
| best_sellers (2) | orders+order_lines, products | rolling 7d | **no status filter**; excl. 424242, lucente/jetem; ranked by revenue |
| brand_revenue (3) | same | rolling 30d | + dead UUID exclusion; blank brands show as `''` |
| category_revenue (4) | + category_names/history | rolling 30d | taxonomy retroactive (history rows inert) |
| daily_kpis (5) | report_rows(+intraday), orders, contactable_users | today+13d | orders col = snapshot *units*; contactable always 0; Nov 17 understated |
| refunds (6) | refunds_unified | all time | counts cancellations as refunds; v2 refunds don't reduce revenue elsewhere |
| registered_conversion (7) | accounts→users(email)→orders | all time | 30 buyers / $18,155.71; email-join assumption |
| revenue_widget (8) | report_rows(+intraday) | 7 calendar days | latest-version-per-date logic; pre-Dec-24 history was double-counted on screen |
| statements_final (9) | statements_final view | all time | the current finance numbers (§4.1) |

All nine run Postgres SQL against the serving replica; all rolling windows are anchored at `now()`, so against the frozen post-2019 replica they return empty/stale data. No cached results existed in Redash (`latest_query_data_id = null` for all 9; nothing was refreshed during this exercise).

### C. Methodology & artifacts in this run folder

Read-only throughout: BigQuery SELECTs via `bq` with the provided service account; Redash via `GET` API only; git via the local clone (no fetch/push). Artifacts saved alongside this file: `git_log.txt` (112 commits), `old_dashboards/*.sql` (recovered at `57ea43a~1`), `redash_dashboards.json`, `redash_queries.json`, `redash_queries/query_[1-9].json`, `redash_cached_results.json` (all null — never executed), `engineer_backfills.csv` (the 32 manual-mutation log lines).

Key reproduction queries (BigQuery, dataset-qualified) used for the claims above:

```sql
-- three revenue surfaces
SELECT * FROM novamart.statements ORDER BY month;
SELECT * FROM novamart_analytics.statements_final ORDER BY month;

-- duplicate-order inflation
WITH dups AS (SELECT payment_ref, MIN(id) keep_id FROM novamart.orders
              GROUP BY 1 HAVING COUNT(*)>1)
SELECT COUNTIF(o.status=1) dup_orders, ROUND(SUM(IF(o.status=1,o.price,0)),2) dup_rev
FROM novamart.orders o JOIN dups d
  ON d.payment_ref=o.payment_ref AND o.id!=d.keep_id;

-- board actives = 0 root cause
SELECT SPLIT(email,'@')[SAFE_OFFSET(1)] domain, COUNT(*) FROM novamart.users GROUP BY 1;

-- scan-cap damage
SELECT report_date, SUM(units), SUM(revenue) FROM novamart.report_rows
WHERE report_date IN ('2019-11-16','2019-11-17') GROUP BY 1;

-- rec conversion by source (Dec 6-31): see §7.2 (flatten items, join orders within 3 days)
```
