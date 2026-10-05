# NovaMart — Tribal Knowledge Document

- Run ID (uuid printed at start): `b56b9ca6-60e6-44ed-96e7-cabbddfda1b4`
- Started: Mon Oct 5 16:42:33 UTC 2026 (wall clock). Finished: Mon Oct 5 17:11 UTC 2026.
- Sources used (only these): repo `novamart-sim` pinned at `5ae1182` (+ its full git history, 112 commits), BigQuery emulator project `novamart-warehouse` (datasets `novamart`, `novamart_analytics`, `novamart_logs`), Redash at `localhost:5055` (read-only GETs only; no query was executed/refreshed in Redash).
- Nothing was mutated: only `SELECT`s against BigQuery, only `GET`s against Redash, no writes to the repo. All raw outputs are in this directory (`queries.log`, `dumps/`, `redash/`, `git_log_full.txt`, `commit_timeline.txt`).
- **Evidence notation.** `git:<hash>` = commit; `repo:<path>` = file at `5ae1182`; `bq:<dataset.table>` = warehouse table/view; `Q<n>` = query defined in Appendix B (outputs in `queries.log`); `log:db_queries` / `log:job_runs` / `log:app_events` = `novamart_logs.*`; `redash:q<id>` / `redash:d<id>` = Redash query / dashboard id.
- **Time conventions.** Warehouse timestamps are UTC. The business timezone is `America/New_York` (`repo:novamart/constants.py` `LOCAL_TZ`). "ET" below means that. Data covers 2019-09-25 → 2019-12-31 (`bq:novamart.orders` min/max created_at, Q1); git history 2019-09-15 → 2020-01-05.
- **Anchor for "rolling" queries.** Every dashboard window is `now()`-anchored; I re-anchored them at `2020-01-01 00:00Z` (end of data) when replicating.

---

# 1. Summary

**What NovaMart is.** A small marketplace backend (FastAPI + Postgres, `repo:README.md`) that records views, carts, orders and payment-gateway callbacks, plus 15 scheduled nightly/intraday/monthly batch jobs (+1 manual backfill) that write `analytics.*` tables and `public.report_rows`/`statements`. In Jan 2020 (`git:d398b0d`, `git:41e3537`, `git:4bfcbe6`, `git:5ae1182`) the stack moved to Cloud SQL → BigQuery, Redash and Airflow. Over Oct–Dec 2019 it recorded 9,127 orders (9,033 currently paid) and $2.86M paid gross (Q1).

**The ten things a tenured person would tell you first**

1. **There is no single "revenue".** There are at least six numbers for a month (statement as published, statement corrected, statement final, live `orders status=1`, `report_rows`, payments). They legitimately differ. Oct-2019 gross: published **1,230,332.43**, final **1,226,764.86**, live paid **1,206,337.32**, my "cleaned" bridge **≈1,146,894.55** (Section 4.1, Q1/Q2/Q3/Q5).
2. **Published statements are append-only snapshots and are never restated for later cancellations/refunds.** All 82 cancelled/refunded orders (ids 1–82, created 2019-09-25…2019-10-01) were flipped in weekly batches between 2019-11-05 and 2019-12-31, *after* the Sept and Oct statements were generated, so the Sept statement ($2,702.00, 12 orders) is now worth $0 of live revenue (Q1, Q4, `bq:novamart.statements`).
3. **Duplicate orders inflate October.** 130 `payment_ref`s have more than one order row (155 extra orders, $59,812.52; 151 paid / $58,828.24 in Oct) because order callbacks were not idempotent until `git:b676969` (2019-10-15). `reconcile` re-flags the same 130 refs every night and nothing ever fixes them (Q3, `log:job_runs` flagged=130 daily).
4. **`statements_final` (the "current finance number") double-deducts.** Its 3 chargebacks (orders 46, 49, 55, $3,567.57) are orders that were *already* cancelled/refunded (status 2/3) by 2019-12-17, so they are subtracted from a gross that still contains them *and* they are no longer paid in the live table (Q2, `bq:novamart_analytics.statements_final`, `bq:novamart_analytics.chargebacks`). It also has no December row — the Dec statement job has not run in the data (Q2).
5. **Three "active customer" numbers that do not agree, and the board one is broken.** 12-31: `kpi_daily` = **1,152**; KPI dashboard = **54** (per day, not 30-day); board query (`redash:q3`) = **0** because it excludes every `@example.com`/`.example` email and every user in the warehouse has one (Q10, Q11).
6. **`contactable_customers` on the KPI dashboard is always 0** and the marketing digest sends to 40 "recipients" (`email NOT LIKE '%@example.com'`), i.e. the 40 users whose email is `@gmail.example` (Q11, `bq:novamart_analytics.digest_log`).
7. **The daily report under-counts and is not restated.** Nov-2019 `report_rows` = 966,974.33 vs 1,101,397.01 paid; the main hole is 2019-11-17 (500-row scan cap, fixed 11-19 in `git:1233af8` but never backfilled). 2019-11-15 has no orders at all (checkout outage-like gap), then a surge (11-16/11-17 = $358,016 = 32.5% of November) (Q7, Q12).
8. **Held (status 6) orders are counted by some reports and not others.** `daily_report` excludes statuses `[0,2,3]` only, so fraud-held orders ($40,213.29, 12 orders) remain in `report_rows`/KPI dashboard but are outside `status=1` (statements, trending, kpi_daily) (Q9, `repo:novamart/constants.py`).
9. **The "ML" rec system is, in effect, a rule-based widget.** v1 served a real list only 17% of the time (83% fell back to trending); v2 (current, `REC_MODEL_VERSION=2.0.0`) only has usable scores for 449 of 81,018 products so ~80% of non-random traffic still gets the trending fallback — which includes two "test/internal" SKUs because the fallback path does not filter `EXCLUDED_SKUS`. The trained "v4" model is a no-op: its scores are `affinity_v2 × 0.9755` for every row, so the ranking is identical to v2, and it is not served anyway (Q13–Q15).
10. **Jobs are fragile in ways that matter for changes.** All writers are autocommit `DELETE`-then-`INSERT` loops, jobs append snapshots with no uniqueness keys, schedules in Airflow carry no timezone and the migration silently dropped the 17:00 intraday run and made the backfill DAG un-runnable as written (Section 5.5, `repo:airflow/dags/*`).

**What would I trust?** `public.orders` + `public.payments` for what happened (once duplicates and test/held orders are understood); `public.statements` for "what we said at the time"; `analytics.statements_final` only with the caveats in point 4; `report_rows` only per-day and per-definition-era; none of the three active-customer numbers without stating which; the rec "model" metrics not at all.

---

# 2. Why this project

**Why the system exists.** Marketplace backend that bootstraps users/products "on first sight" from ids relayed by the storefront (`repo:novamart/routers/catalog.py::ensure_entities`, `repo:novamart/onboarding.py` docstring: "The storefront only relays ids, so these are synthesized deterministically from the id"). Orders arrive as payment-gateway callbacks (`repo:novamart/routers/orders.py` docstring "Order creation from payment-gateway callbacks"). The batch layer exists because finance and leadership want daily/monthly numbers (`repo:novamart/constants.py` header: "Change with care — finance reads the numbers these produce"; README: "Nightly reconcile flags anything odd in payments; check the logs if finance asks").

**Why this knowledge doc is needed (the pain).**
- Definitions changed repeatedly in ~16 weeks with no restatement of history (Section 4.2). The rationale (two engineers, Maya Iyer and Dev Kapoor, plus the Jan-2020 platform account) lives only in commit messages and an ad-hoc query log (`log:db_queries` tags `engineer:dev`, `engineer:maya`, `engineer-backfill:*`, 191 statements, Q17).
- In-repo docs (`repo:docs/*.md`) were written after the fact and are partly right, partly stale (corrections in Section 8 / Appendix C). `docs/rec_versions.md` is literally "TBD" (`git:4396fbb`).
- The Jan-2020 platform migration moved dashboards out of git (`git:41e3537`), crontab to Airflow (`git:4bfcbe6`) and the DB into BigQuery (`git:5ae1182`, `repo:docs/data-access.md`); the context for why queries look the way they do now sits only in git history.

**Project timeline (from git; deploy-time stamps line up with data changes — e.g. the flat $0.30 fee first appears in `payments` at 2019-11-20 14:27Z, two minutes after `git:12e1c68` at 14:25Z, Q6).**

| Date | Event | Evidence |
|---|---|---|
| 2019-09-15 | Initial import: orders/carts/catalog routers, daily_report, monthly_statement, reconcile, 3 dashboards (SQL files) | `git:2da4141` |
| 2019-10-08 / 10-25 / 12-15 | Exclusion lists: test SKUs → brand `lucente` → brand `jetem` | `git:83fb3ed`, `git:ba1fbfa`, `git:1169e40` |
| 2019-10-15 | Order callbacks made idempotent by `payment_ref` | `git:b676969` |
| 2019-10-26 | Similar-products widget v1.0.0 (affinity from v1 job) | `git:f1217a8` |
| 2019-11-02 | Statement fee changed to "collected per-order fees"; Oct override booked | `git:a92c96d`, engineer-backfill log 2019-11-02 (Q17) |
| 2019-11-05 | DST fall-back fix for local-day windows | `git:102c9b4` |
| 2019-11-15…18 | Refund endpoint; checkout gap + surge in data | `git:d87cb3d`, Q12 |
| 2019-11-18/19 | Cancelled/refunded excluded from daily report; 500-row scan cap removed | `git:11c0a42`, `git:1233af8` |
| 2019-11-20 | Processor fee 2.9% → 2.9% + $0.30 | `git:12e1c68` |
| 2019-11-22 | Same-session order merging + `order_lines` table | `git:5d1300d`; first `order_lines` row 2019-11-22 15:18Z (Q8) |
| 2019-11-22/23 | Paid-order volume falls ~65–70% while carts are flat (unexplained, Section 4.5) | Q12 |
| 2019-12-02 | Affinity v2; dynamic pricing held; flat-fee statement logic + Nov audit correction | `git:89666bf`, `git:cca9b0d`, `git:4a58d17` |
| 2019-12-03/05/29 | Fraud scoring; threshold 0.90 → 0.70 → 0.85 + manual release of held < $2,600 | `git:e4656fb`, `git:53f6f6c`, `git:1cb8721` |
| 2019-12-05 | `order_lines` aware reports; v2 Dec seasonal crash fixed | `git:92596dc`, `git:3dbe4d7` |
| 2019-12-06 | Widget v2 dispatch + 5% random arm; trending 60→30d | `git:df4ed85`, `git:f563dea` |
| 2019-12-08 / 12-09 | Intraday snapshots; chargebacks + `statements_final` | `git:a2e0013`, `git:cd559d3` |
| 2019-12-14 | Rec model v4 trainer | `git:a1946ff` |
| 2019-12-17→19 | Random-arm decision logging accidentally dropped (≈1,371 rows lost) | `git:30e8907`, `git:a00f24c`, Q13 |
| 2020-01-02…05 | Platform migration commits (docs, Redash, Airflow, BigQuery backfill) | `git:d398b0d`, `git:41e3537`, `git:4bfcbe6`, `git:5ae1182` |

---

# 3. Business understanding

## 3.1 What the business looks like in the data (Q1, Q19, Q12)

- **Scale (Oct–Dec 2019):** 9,127 orders, 9,033 with `status=1` ($2,860,063.26 gross); 38,950 user rows; 81,018 product rows of which 3,298 have a paid order (`bq:novamart.orders`, `bq:novamart.users`, `bq:novamart.products`).
- **Brand/category concentration:** paid revenue by brand — apple $1.40M (49%), samsung $0.52M (18%), xiaomi $0.11M, blank brand $0.085M, huawei, lg … Electronics dominates the last-30-day category view ($437.9K of $569.7K) (Q18, Q19). 41% of products (33,514) have blank category and 22% (17,442) blank brand (`bq:novamart.products`).
- **Order volume regimes (paid orders/week, ET ISO weeks, Q1/Q12):** W40–W45 ≈ 630–950/wk; W46 = 1,512 (surge); W47 = 607; W48 onward ≈ 257–462/wk; weekly revenue fell from ~$250–355K to ~$87–136K. Carts per week *rose* (W45 1,536 → W48 2,600 → W51 5,203) so cart→order conversion collapsed from ≈0.9 orders per cart-session to ≈0.17.
- **Customers:** 8,481 distinct users carted, 4,112 ever ordered (4,089 paid) of 38,950 user rows (Q10/Q11) — i.e. user rows are mostly browsers.
- **Vendors:** 8 synthetic vendor names (`repo:novamart/onboarding.py::VENDORS`; `bq:novamart.products` distinct vendor = 8).

## 3.2 How an order and its money are produced (the "why" behind every revenue number)

1. Storefront calls `POST /orders` with `uid, pid, price, ref, session, ts` (`repo:novamart/routers/orders.py::create_order`). **The price is taken from the request body** — not from `products.list_price` and not from `analytics.price_suggestions`; the catalog price feed only updates `products.list_price` (`repo:routers/catalog.py::price_feed`, `repo:docs/pricing_status.md` verified by code).
2. Fee: `fee = round(price*0.029 + 0.30, 2)` since `git:12e1c68` (before: `price*0.029`), written to a `payments` row per callback (`repo:orders.py`, `repo:constants.py`).
3. Idempotency: advisory locks on session and ref; lookup of existing order by `orders.payment_ref` or `order_lines.payment_ref`; replays only add a missing payment row / flip status 0→1 (`git:b676969`, `git:5d1300d`). 522 replays are logged as `order_callback_replayed` (`log:app_events`).
4. **Merging (since 2019-11-22 `git:5d1300d`):** a new callback from the same user + session within 15 min of an existing non-cancelled/non-refunded order *adds to `orders.price`* and inserts an `order_lines` row and a new `payments` row (225 `order_appended` events). So `orders.price` is an order total, **`orders.product_id` is only the first product**, and `payments` has one row per callback/line (Q8: 173 multi-line orders, 398 lines, $113,405.23; 9,352 positive payment rows for 9,127 orders; per-order `SUM(payments.gross)` = `orders.price` for all 9,127 orders).
5. Status lifecycle (constants `repo:novamart/constants.py`; data Q1): `0` created (transient, 0 rows today), `1` paid, `2` cancelled (`STATUS_CANCELLED` was `4` until `git:8f19718` on 2019-10-28; no `4` ever appears in data), `3` refunded (`git:d87cb3d`), `6` fraud-hold (`git:e4656fb`); `5` is referenced only by `reconcile` (`status <> 5`) and is never written.
6. Cancel/refund endpoints flip `orders.status` only; **no money row is written** (`repo:orders.py::cancel_order/refund_order`). The *gateway refund webhook* (`git:c49a7bb`) instead inserts a **negative `payments` row and does not touch `orders.status`**, and it is not idempotent: orders 3762, 3763, 3776 were refunded on 12-13, again 12-20 and again 12-27 (9 negative rows, −$1,843.59 vs a one-time −$614.53) while their status stays 1 (Q5).

## 3.3 Business rules that are baked into reports (assumptions to know)

| Rule | Where | Notes / evidence |
|---|---|---|
| Hide test SKUs `1004856`, `1002544` | `daily_report`, `intraday_report`, `similar` (model path only) via `EXCLUDED_SKUS` (`git:83fb3ed`) | These SKUs have 322 / 138 *paid* orders by 241 / 87 distinct users and $40,304.68 / $66,226.12 revenue (Q19) — hiding them removes ≈$106.5K of real-looking sales from report_rows; they are **not** excluded from statements, dashboards (`best_sellers`, `brand_revenue`), trending, top_sellers, digest. Product 1004856 is "Internal Test #4856" (brand `internal`, category `qa.test`); 1002544 is titled "Unbranded Item #2544" but brand `apple`, category smartphone. Whether they are truly test SKUs is **unresolved** (Section 9). |
| Hide brands `lucente` (since 10-25) and `jetem` (since 12-15) | `BRAND_DENYLIST` in jobs; `NOT IN ('lucente','jetem')` in dashboards | `git:ba1fbfa`, `git:1169e40`; 676 lucente / 5 jetem products (Q19). Historical `report_rows` keeps $17,255.56 of lucente from before the filter; dashboards re-filter by joining `products` at read time so they hide it anyway (Q19). |
| Hide QA user `424242` | `analytics.test_users` (jobs, since 11-27) and hard-coded `<> 424242` (dashboards) | `git:b59f077`; test_users has 1 row (`bq:novamart_analytics.test_users`). The QA user still places a paid order roughly daily (13 paid orders, 2019-10-02…12-25, Q10) and **is counted by `kpi_daily`** (no exclusion) and by `top_sellers`/trending. The "QA account UUID" in `brand_revenue` (`git:adbcb7e`) can never match: `orders.user_id` is BIGINT (`bq:novamart.accounts` account `cc27b436-…` maps to uid 424242 via `bq:novamart.account_map`). |
| Business day = ET, DST-aware | `timeutil.local_day_window_utc` fixed in `git:102c9b4` | Report for 2019-11-03 (25-hour day) ran 11-04 before the fix landed, so that day is short ≈1 hour (Q7 gap 11-03 = $5,583 vs ~$2.5K typical). |
| Fees are per transaction, not per order | `payments.fee` | After 11-22 a multi-line order pays the flat $0.30 per line (Q6) — the statement job's *expected* fee counts it once per order (Section 4.3). |
| No promo/discount in revenue | `DISCOUNT_CAP = 0.25` exists but nothing reads it | Only `scripts/rerun_kpis.py` imports `apply_discounts`, calling it with the **legacy default `cap=0.40`** instead of `constants.DISCOUNT_CAP` (`git:35c581e`; grep of repo). No discount columns exist in `schema.sql`. Treat the ops script as untrustworthy. |
| Synthetic profile data | `repo:novamart/onboarding.py` | `name, region, signup_channel, device, age_band, marketing_opt_in` (62% true) and product `title, vendor, cost_price (55–80% of price), stock (20–500)` are *hash-derived from the id*, not captured data. Any segmentation by region/channel/device/age, any margin analysis from `cost_price`, any stock-based logic is analyzing synthetic values. User emails are `user<id>@example.com` placeholders. |

---

# 4. Metrics

## 4.1 Revenue: "what was revenue in month X, and why" (Phase 1)

### Sources of truth and what each really measures

| Number | Table/view/job | Definition (as coded) | Trust notes |
|---|---|---|---|
| **Statement (as published)** | `public.statements` ← `novamart.jobs.monthly_statement`, Airflow `monthly_statement` `30 6 1 * *` | `gross = SUM(orders.price)` for orders with `status=1` and `created_at` in the ET month window; `fee = SUM(payments.fee)` joined to those orders; `net = gross − fee`; one append-only row per run (`repo:monthly_statement.py`) | Snapshot of statuses at run time (1st of next month, 10:30/11:30Z). Includes duplicates. Never restated by the job. Only Sep/Oct/Nov rows exist (Q2). |
| **Statement (fee-corrected)** | `analytics.statements_corrected` (view) | `COALESCE(override, statement)` joined on month | One override row: Oct fee 35,679.64 → 35,679.50 (`bq:novamart_analytics.statement_overrides`). If `monthly_statement` is ever re-run for a month, the left join will duplicate that month (statements is append-only). |
| **Statement (final)** | `analytics.statements_final` (view) | corrected gross/net minus `analytics.chargebacks` grouped to the **ET month of the original order** | Policy doc says "use for current finance reporting" (`repo:docs/restatement_policy.md`). Double-deducts (see below). |
| **Live paid** | `public.orders` `status=1` | Current state | Best view of "paid today" but still contains duplicate-ref orders and gateway-refunded orders. |
| **Daily report** | `public.report_rows` ← `daily_report` (06:00 ET, for *yesterday* ET) | Units and revenue per product from `orders ∪ order_lines` (see below), excluding statuses `[0,2,3]`, test users, `EXCLUDED_SKUS`, `BRAND_DENYLIST` | Snapshot; a day is never recomputed; filters/definitions drift by era (Section 4.2). |
| **Intraday report** | `public.report_rows_intraday` ← `intraday_report` (12:00 + 17:00 ET until migration) | Same logic over "today so far" | Overlaps `report_rows` once a day closes; each date has several `created_at` versions (`git:3eced24`). |
| **Payments** | `public.payments` | One row per gateway callback; negative rows = gateway refunds | `SUM(gross)` for paid orders equals `orders.price` exactly (Q8). |

### Monthly revenue, side by side (ET months; gross unless stated; Q1, Q2, Q3, Q6, Q7)

| Month | Published stmt gross / fee / net / orders | Final gross / net | Live paid gross (orders) | Held (status 6) | `report_rows` | Why they differ |
|---|---|---|---|---|---|---|
| 2019-09 | 2,702.00 / 78.36 / 2,623.64 / 12 | 2,702.00 / 2,623.64 | **0.00** (all 12 later cancelled/refunded) | – | 2,702.00 (2 days) | Statement published 10-01 10:30Z; cancellations came 11-05→12-31 (Q4). Never restated. |
| 2019-10 | 1,230,332.43 / 35,679.64 / **1,194,652.79** / 3,765 | **1,226,764.86 / 1,191,085.36** (corrected net before chargebacks 1,194,652.93) | **1,206,337.32** (3,695) | – | 1,201,082.08 | See bridge below. |
| 2019-11 | 1,101,397.01 / 32,110.92 / 1,069,286.09 / 3,582 | same (no override, `statement_corrections` delta 0, no chargebacks) | 1,101,397.01 (3,582) | – | 966,974.33 | Report under-count: SKU/brand/QA exclusions (≈$56.7K, Q19) plus a residual ≈$77.7K dominated by 11-17 (scan cap; $80.9K gap that day) and the short DST day 11-03; no 11-15 data. |
| 2019-12 | **no statement in the warehouse** (job would run 2020-01-01) | – | 552,328.93 (1,756 orders; fee 16,600.26 on 1,942 payment rows → net 535,728.67) | 40,213.29 (12 orders) | 535,561.72 (30 days; 12-31 not yet reported) | Held orders are excluded by statement/`status=1` logic but included by `daily_report` (EXCLUDED_STATUSES omits 6). |

### Bridge for October 2019 (Q1, Q2, Q3, Q5)

| Step | Amount | Evidence |
|---|---|---|
| Published statement gross (3,765 orders) | 1,230,332.43 | `bq:novamart.statements` |
| − later **cancelled** (43 orders) | −10,748.42 | Q1 (status 2, Oct) |
| − later **refunded** (27 orders) | −13,246.69 | Q1 (status 3, Oct) |
| = live paid (3,695) | **1,206,337.32** | Q1 |
| − duplicate-`payment_ref` extra orders still paid (151) | −58,828.24 | Q3 |
| − gateway refunds on Oct orders 3762/3763/3776, counted once | −614.53 | Q5 |
| = "cleaned" paid revenue | **≈1,146,894.55** | derived (my calculation, not a company number) |
| `statements_final` for comparison | 1,226,764.86 | also subtracts 3,567.57 for orders 46/49/55 that are *already* in the cancelled/refunded buckets above → double deduction |

**How to answer "what was revenue in <month> and why" (template):**
1. Say which layer: *as-published* (`public.statements`), *as-restated* (`statements_final`), or *live paid* (`orders status=1`, ET month window).
2. For published: state it was generated on the 1st at 10:30/11:30Z and includes everything paid at that moment.
3. Explain the movement since publication: cancellations/refunds (weekly Tuesday 16:00Z batches against ids 1–82), chargebacks (3 rows, reported 2019-12-01 12:00Z), fee override (Oct only), duplicate-ref orders (Oct 1–15 only), gateway refunds (Dec 13/20/27, status unchanged).
4. For Nov: remember 32.5% of the month's gross arrived on 11-16/11-17 after a 2019-11-15 day with zero orders despite 2,284 cart events (Q12).
5. Net = gross − processor fees (not net of refunds).

### Fee mechanics (Q6)
- Before 2019-11-20 14:25Z `fee = round(price*0.029,2)`; after, `+0.30` per payment row. October collected fee (live paid) = 34,983.61 = 2.9% exactly; November = 32,110.92 containing 567 flat-fee rows; December = 16,600.26, all 1,942 rows flat.
- The original statements computed fee from `gross × 2.9%` (Oct `git:2da4141` code) — Oct's published fee 35,679.64 = `round(1,230,332.43×0.029,2)`; the fee-collected fix (`git:a92c96d`) landed 2019-11-02, **after** the 11-01 run, hence the Oct override to 35,679.50 (`log:app_events` `statement_fee_mismatch` 2019-11-01, delta 0.14; Q17 engineer-backfill 2019-11-02).
- The November "mismatch" warning (statement_fee 31,940.51 vs collected 32,110.92, delta −170.41, 2019-12-01) was a **false alarm**: the run used the pre-flat-fee expectation (`git:a92c96d`); `git:4a58d17` (2019-12-02) taught the expectation about the flat fee and booked a *zero-delta* Nov correction row (`bq:novamart_analytics.statement_corrections` delta 0). Even the new expectation uses `FEE_CHANGE_AT = 2019-11-20 00:00 ET (05:00Z)` and counts the flat fee per **order**, whereas the real switch happened at 14:25Z and fees are per **payment row** → residual Nov delta +9.62; **Dec will log a spurious mismatch of −55.93** (expected 16,544.33 vs collected 16,600.26; my calculation, Q6).

## 4.2 How definitions changed (change log; none of these restated history)

| Metric / rule | Change | Date | Commit |
|---|---|---|---|
| Daily-report statuses excluded | `[0]` → `[0,2,3]` (cancelled/refunded) — 6 (held) never added | 2019-11-18 | `git:11c0a42` (+ `git:8f19718`, `git:d87cb3d` for status ids) |
| Daily-report scan | `fetchmany(500)` → `fetchall()` (cap constant left in `constants.py`, unused) | 2019-11-19 | `git:1233af8` |
| Daily-report source | `orders` → `orders ∪ order_lines` (order_lines when present, else legacy order row) | 2019-12-05 | `git:92596dc` |
| Daily-report exclusions | SKUs → lucente → QA user (`analytics.test_users`) → jetem | 10-08 / 10-25 / 11-27 / 12-15 | `git:83fb3ed`, `git:ba1fbfa`, `git:b59f077`, `git:1169e40` |
| Day boundaries | UTC+24h → local midnight-to-midnight (DST aware) | 2019-11-05 | `git:102c9b4` |
| Statement fee | `gross×2.9%` → collected fees → expected-fee check with flat | 11-02 / 12-02 | `git:a92c96d`, `git:4a58d17` |
| Order callback semantics | insert-always → idempotent by ref → merge same-session | 10-15 / 11-22 | `git:b676969`, `git:5d1300d` |
| Status ids | cancelled `4` → `2`; refunded `3` added; held `6` added | 10-28 / 11-15 / 12-03 | `git:8f19718`, `git:d87cb3d`, `git:e4656fb` |
| Processor fee | 2.9% → 2.9% + $0.30 | 2019-11-20 | `git:12e1c68` |
| Dashboards | Items from `orders` → `order_lines` union; QA exclusion; brand exclusion; daily KPIs rebuilt on `report_rows` + intraday + ET days | 11-27 / 12-05 / 12-08 / 12-15 | `git:b59f077`, `git:92596dc`, `git:a2e0013`, `git:1169e40` |
| Finance restatement | statement → +override → +chargebacks (`statements_final`) | 11-02 / 12-09 | engineer-backfill log (Q17), `git:cd559d3` |
| Platform | crontab → Airflow; dashboards → Redash; Postgres → BigQuery | Jan 2020 | `git:4bfcbe6`, `git:41e3537`, `git:5ae1182` |

**Implication:** `report_rows` is a time series made of different definitions: (i) before 10-08 includes test SKUs ($9,187.76 across 14 rows), (ii) before 10-25 includes lucente ($17,255.56, 46 rows), (iii) before 11-18 includes cancelled/refunded *if* they were still status 1 at report time (all of them were), (iv) before 11-19 capped at 500 rows (only 11-17 hit it: `orders_scanned=500`), (v) before 11-27 includes QA (Q19, Q7, `log:job_runs`).

## 4.3 Where the numbers do not tie (known defects, with sizes)

| Defect | Size | Evidence |
|---|---|---|
| Duplicate `payment_ref` orders (Oct 1–15) | 155 extra orders, $59,812.52 (Oct: 154 / $59,555.83; paid 151 / $58,828.24) | Q3; fix `git:b676969`; nightly `duplicate_payment_ref` warnings = 10,766 total (`log:app_events`) |
| Statements not restated for cancel/refund | Sep −$2,702.00 (100%), Oct −$23,995.11 | Q1, Q4 |
| `statements_final` double-deduct | −$3,567.57 on orders already cancelled/refunded | Q2 |
| Gateway refunds repeated 3× and status unchanged | recorded −1,843.59 vs −614.53 real | Q5 |
| `refunds_unified` mixes cancellations (not money movement) with refunds and triple-counts gateway rows → Redash `refunds` dashboard | Nov 32 rows $9,691.77; Dec 59 rows $18,848.93 (of which cancelled $13,249.64 total, gateway $1,843.59) | Q5, `redash:q1`, `bq:novamart_analytics.refunds_unified` |
| Report 11-17 cap | report 148,857 vs orders 229,780 (gap $80.9K) | Q7 |
| Report 11-15 | no orders (zero) yet 2,284 carts / 28,666 views that UTC day | Q12 |
| Held orders in `report_rows` | 12-03 report 39,127 vs live paid 13,168 (+$25.96K = 8 held orders × ~$3K) | Q7, Q9 |
| UTC vs ET month grouping | Orders 2019-09-30 22:00–2019-10-01 04:00Z belong to Sep ET; naive UTC grouping moves 10 orders | Q1 (Sep has 12 orders in ET) |
| `NOW()`/`CURRENT_DATE` run in a manual UPDATE/backfill stamps wall-clock rather than business date | 5 released held orders have `updated_at = 2026-08-13 21:12:33`; `analytics.category_name_history.valid_from = 2026-08-13`; `blank_brand_products.captured_at = 2026-08-13` | Q9, Q18, `bq:novamart_analytics.blank_brand_products` |

## 4.4 Customer metrics (Phase 2)

### Three active-customer definitions (plus the others) — who uses which (Q10, Q11)

| Metric | Defined in | Definition | Value at end of data |
|---|---|---|---|
| **`kpi_daily.active_customers`** | job `kpi_daily` (06:15 ET) → `bq:novamart_analytics.kpi_daily` (`git:14726e7`) | `COUNT(DISTINCT user_id)` from `orders`, trailing `30 days` from run timestamp, `status = 1`; **no QA/brand/email filter**; one row per run, `day = run date (UTC)` | **1,152** on 2019-12-31 (replicated exactly: 1,152). Includes QA 424242. Trajectory 2,093 (11-17) → 974 (12-22) → 1,152; the 12-17/12-18 drop (1,560→1,259→1,031) is the 11-16/17 surge leaving the window. **No reader found** in repo, Redash or query log (Q17). |
| **KPI dashboard `active_customers`** | `redash:q7` (`git:2da4141` … `git:1169e40`) | Per **ET day**: `COUNT(DISTINCT user_id)` over orders (**no status filter**), excl. user 424242 and brand `lucente`/`jetem`; window = today−13 … today; "orders" column is `SUM(units)` of report rows, not orders | 54 (12-31), 65 (12-30), 75 (12-29)… a daily series, not a 30-day KPI |
| **Board deck `active_customers`** | `redash:q3` (`git:2dde4f0`) | Distinct users, trailing 30d from `now()`, `NOT status IN (0,2,3)` (so held 6 counts), minus `analytics.test_users`, minus email-heuristic exclusions | **0** — all 38,910 non-updated users are `userNNN@example.com` and the 40 updated users are `@gmail.example`; both match the exclusion list (`IN ('example.com',…)`, `LIKE '%.example'`). Replicated: 1,151 candidates → 1,150 non-test → 0. Never non-zero in this dataset. |
| `contactable_customers` (KPI dashboard) | view `analytics.contactable_users` (`git:e10cb0c`) | `marketing_opt_in` AND valid-looking email AND domain not example.* | **0 users** in the view → dashboard column always 0 |
| Digest recipients | `email_digest` | `COUNT(*) FROM users WHERE email NOT LIKE '%@example.com'` | 40 (all `@gmail.example`), `bq:novamart_analytics.digest_log`; not the contactable definition |
| Registered (accounts beta) | `redash:q4` (`git:d6e34c6`, fixed `git:b975479`) | distinct buyers whose `users.email` matches an `accounts.email`, `status=1`, **all-time** | 30 buyers, $18,155.71 (includes QA 424242: 13 orders $129.87). 30 accounts all created 2019-12-01 16:30Z (`bq:novamart.account_map`). First version joined `account_id::text = user_id::text` (never matches → "numbers look low", `git:d6e34c6` FIXME). |
| Funnel `users_active` | job `funnel` → `bq:novamart_analytics.daily_funnel` | distinct users with a **cart or order event** in the last 24h of the run (not calendar day, not views); sessions split at `GAP_MIN` (30 → 120 min on 2019-12-14 `git:f915c1b`, no restatement) | 308 on 12-31; spike 688–768/day on 11-15→17 |
| Fraud `new_account` | `fraud_score` | `order.created_at − users.created_at < 7 days` — `users.created_at` is *first sight*, not signup | |

**"Signups".** There is no signup event. `users` rows are created on first product view/cart/order (`ensure_entities`, `view_product`), so 38,950 "users" ≈ distinct ids ever seen; new rows per month: Sep 74, Oct 15,045, Nov 11,302, Dec 12,529 (Q10). Real registrations are the 30 beta accounts (`POST /accounts`, router **not mounted** at HEAD — Section 5.1).

### Who consumes what
`report_rows` → `redash:q7` (KPI), `redash:q2` (revenue widget); `statements_final` → `redash:q5`; `refunds_unified` → `redash:q1`; `analytics.test_users` → jobs; `analytics.contactable_users` → `redash:q7`. The `log:db_queries` consumer scan (Q17) found **no reader at all** for `kpi_daily`, `daily_funnel`, `top_products`, `digest_log`, `order_risk`, `price_suggestions` and only one-off engineer reads for `reorder_hints`, `model_registry`, `model_scores`.

## 4.5 Product, brand, category reports (Phase 2)

| Report | Source | Assumptions baked in | Pitfalls |
|---|---|---|---|
| **Best sellers (dashboard)** `redash:q9` / dashboard 7 | `orders ∪ order_lines`, rolling 7×24h from `now()`, `user_id <> 424242`, brand not lucente/jetem, **no status filter**, **no SKU exclusion**, ranked by **revenue** (units shown) (`repo:docs/dashboard_notes.md` verified vs. SQL) | Counts cancelled/refunded/held lines | SKU 1002544 ranks 4th by revenue in the last 7 days (replicated, Q18); dashboard 7 points to query 9 and dashboard 9 to query 7 (ids swapped but names consistent, `redash:d7`,`d9`) |
| **Top sellers job** → `public.top_products` | `top_sellers` 06:45 ET | **yesterday only**, `status=1`, counts **orders by `orders.product_id`** (first product of merged orders), no brand/SKU/QA exclusion, top 50 | Different from the dashboard (status filter, window, unit-ranked, order-level) |
| **Brand revenue** `redash:q8` | same item_orders, 30 days | brand `''` appears as its own bucket (blank brand = 17,442 products); brand `internal` (QA SKU) not hidden | Last-30-day: apple 236.6K, samsung 128.1K, xiaomi 20.8K, lg 18.5K, (blank) 17.6K (Q18); the UUID user exclusion is a no-op |
| **Category revenue** `redash:q6` | `analytics.category_names` (135 codes → 6 groups, `ELSE 'other'`) + `category_name_history` | Groups only electronics/appliances/apparel/construction/kids/other: computers, furniture, sport, auto, blank category and the QA category all land in `other` ($93.6K of $569.7K in the last 30 days) | `category_name_history` (lighting/entertainment renames of 6 codes, `git:33054cd`) has `valid_from = 2026-08-13` (CURRENT_DATE when backfilled), which is later than every order date → the rename **never applies**; electronics/construction totals still include audio/lighting (Q18, Q19) |
| **Trending** → `analytics.trending_daily` | `trending` 05:15 ET | top 50 by `COUNT(*) × exp(−0.05×days since last order)`, min 5 units, status 1, window 60 → **30 days** on 2019-12-06 (`git:f563dea`; `log:job_runs` `window_days` 60 until 12-06, 30 after) | No SKU/brand/QA exclusion: test SKUs 1004856 and 1002544 are in the top-3 on all 59 days (118 rows) and feed the widget fallback (Q15). README still says 60 days (stale; `docs/trending_notes.md` is right). |
| **Reorder hints** | `reorder_forecast` | `int(15.6 + K/(velocity+1.8))`, K 141.12 → 162.4 (`git:f85cdd2`), 14-day velocity, top 200 | Inverse relationship — slower products get *bigger* hints (51–102; velocity 0.0714–2.7143, Q20). README and `docs/forecast_caveats.md` say advisory only; confirmed by code. |
| **Price suggestions** | `price_suggest` (shadow) | ±5% around list price by 14-day paid-unit rank vs median | 500 rows nightly; 386 down / 109 up (ties at the median go down); nothing reads it (Q17, `repo:docs/pricing_status.md` verified) |

**Unexplained but crucial:** paid orders collapse ~65–70% from 2019-11-22/23 (118 → 82 → 39 → 28/day) while views/carts are flat or rising (Q12). Two deploys coincide (`git:12e1c68` fee change 11-20, `git:5d1300d` order merge 11-22); merging cannot explain it (lines ≈ orders in Dec: 1,961 lines vs 1,768 orders). Any dashboard trend across 11-22 is a step change with no code-level explanation in this repo.

---

# 5. System

## 5.1 Components (`repo:`)

```
Storefront ──HTTP──> FastAPI app (novamart/app.py; uvicorn --workers 4)
   routers MOUNTED:  catalog (/products/{id}, /catalog/prices), carts, orders, similar, payments_webhook
   routers NOT mounted at HEAD (code present, dead): accounts, users, reports
        │ every SQL statement logged: db.py → logutil.db_log → db_queries.log
        ▼
 Postgres (public.* app tables + analytics.* batch tables)  ──scheduled──> 15 batch jobs (novamart/jobs)
        │  logs: app.jsonl, db_queries.log, jobs.jsonl
        ▼ (Jan 2020 migration)
 Cloud SQL replica ──warehouse_backfill (gcloud export csv + bq load --replace)──> BigQuery novamart / novamart_analytics
 Logs ──> BigQuery novamart_logs.{app_events, db_queries, job_runs}
 Redash (novamart-ops) ──live Postgres queries──> 9 dashboards;  Airflow (novamart-ops) ──> 16 DAGs
```

- `routers/accounts.py`, `users.py`, `reports.py` exist but `app.py` mounts only catalog, carts, orders, similar, payments_webhook (`repo:novamart/app.py`). History: `reports`/`users` were dropped from the include list in `git:f1217a8`, `accounts` in `git:c49a7bb` (unrelated commits that rewrote `app.py`'s router list). The logs prove they ran earlier: 40 `user_email_updated` (2019-10-23), 30 `account_created` (2019-12-01) (`log:app_events`). The `/reports/brands` monthly brand report (status 1, SKU/brand filtered, uses `orders.product_id`) is **not served**.
- `db.py` jobs use `autocommit=True`; `DELETE` then per-row `INSERT` loops are non-atomic (all analytics refresh jobs). Readers can see an empty or partial table mid-run.
- `ensure_entities` caches known user/product ids in process memory (`_known_users`/`_known_products`): a product first seen via a view with no metadata is never enriched by `ON CONFLICT DO NOTHING` — the origin of blank brands (`bq:novamart_analytics.blank_brand_products.suspected_cause`: 3,907 products "first seen via product view or known-id cache with no catalog metadata", 2,065 "first inserted with blank brand; later catalog events could not repair…"; partial fix `git:ea0e97b`).
- Feature flags: `deploy/flags.env` `REC_MODEL_VERSION=2.0.0` (re-read from the **current working directory** on every request by `similar.py::intended_version`, despite the header "read at deploy time"); `deploy/cron.env` `ENABLE_DIGEST=1`. The digest was written 11-28 (`git:c19a307`, env var `DIGEST_ON`), renamed 12-09 (`git:8dc520b`) and finally reads the file itself 12-16 (`git:0bd4eac`); the first digest row is 2019-12-17 12:15Z (`bq:novamart_analytics.digest_log`, `log:job_runs`).
- CI: `ci/run_ci.py` boots the app on a scratch DB and exercises view→cart→order, then runs **only** `reconcile`, `daily_report`, `monthly_statement` with `FAKE_NOW=2019-09-22T07:00Z`; it does not cover similar/model_train/affinity/fraud/etc. `FAKE_NOW` is the only time-travel hook (`repo:timeutil.py::now`).

## 5.2 Job catalog (Phase 3): outputs, consumers, what breaks

Times are ET in git history; observed UTC run times in `log:job_runs` shift by one hour at DST end (e.g. `daily_report` 10:00Z → 11:00Z on 2019-11-03; Q16). Runs observed: reconcile 107, daily_report 107, affinity 80, trending 59, top_sellers 55, funnel 53, intraday 47, kpi_daily 45, price_suggest 37, reorder 35, fraud 28, affinity_v2 26 (+3 crashes), model_train 17, digest 15, monthly_statement 3.

| Job (ET time) | Writes | Consumers | If it fails / re-runs |
|---|---|---|---|
| `reconcile` 03:00 (was 02:00 until `git:388370b`) | app log warnings only | none (human check "if finance asks") | Flags the same **130** refs forever (cap `RECONCILE_BATCH` 100→200 `git:030d841`); no remediation path. Predicates `status <> 5` (status 5 unused). |
| `daily_report` 06:00 | `public.report_rows` (append) | `redash:q7`, `redash:q2` | A missed day = missing day (11-15 shows 0 rows because 0 orders; 12-31 is simply not yet run). Re-run appends another snapshot (dashboards take latest `created_at`). Must run **after** `fraud_score` 05:45 if held orders should be excluded — but it does not exclude status 6 at all. |
| `intraday_report` 12:00 & 17:00 | `public.report_rows_intraday` (append) | `redash:q7`, `redash:q2` | Partial-day numbers; **Airflow DAG has only `0 12 * * *`**: the 17:00 run was dropped in migration (`repo:airflow/dags/intraday_report_dag.py` vs `repo:crontab.txt`). |
| `top_sellers` 06:45 | `public.top_products` (append) | none found | Re-run duplicates ranks for the day. |
| `monthly_statement` 06:30 on the 1st | `public.statements` (append) | views `statements_corrected/final`, `redash:q5` | **Re-run duplicates a month and duplicates it again in the views** (left join). Uses ET month window. Run on the 1st at ~10:30–11:30Z. |
| `kpi_daily` 06:15 | `analytics.kpi_daily` (append) | none found | Re-run adds a second row for the day. |
| `funnel` 06:20 | `analytics.daily_funnel` (append) | none found | Same. |
| `affinity` 03:30 (v1) | `analytics.product_affinity` (delete+insert) | **none since 2019-12-06** (app reads end 12-06 16:39Z, Q17) | Safe to stop for serving, still runs nightly (80 runs). Model version stamps/`pairs_seen` = co-carts within a session over 30d; score −1 = "not enough data" sentinel (<3 pairs) — consumers must filter `< 0` (`git:fef5c96`). |
| `affinity_v2` 03:45 | `analytics.product_affinity_v2` (delete+insert; rows stamped `2.0.1`) | widget (v2), `model_train` | Crashed 2019-12-03/04/05 (`IndexError` — `SEASONAL_FACTORS` had Jan..Nov only), fixed `git:3dbe4d7`; December factor is 1.0 (`log:job_runs` season=1). Nothing served v2 until 12-06 so no user impact; if it fails after the DELETE the table is empty → widget fallback. |
| `trending` 05:15 | `analytics.trending_daily` (delete today + insert) | widget fallback | Stale `MAX(day)` served if it fails. |
| `price_suggest` 04:45 | `analytics.price_suggestions` (delete+insert) | none (shadow; phase 2 on hold `git:cca9b0d`) | none |
| `reorder_forecast` 06:50 | `analytics.reorder_hints` (delete+insert) | none | none |
| `fraud_score` 05:45 | `analytics.order_risk` (append), **mutates `orders.status` 1 → 6** | everything keyed to `status=1` | Re-runs re-score the same last-24h orders (duplicates in `order_risk`: 1,631 rows, 1,631 distinct orders because each order is only in one 24h window). A failure means held orders stay paid. |
| `email_digest` 07:15 | `analytics.digest_log` | (marketing send not modeled) | Silently returns when flag off — no log line. |
| `model_train` 04:15 | `analytics.model_registry` (append), `analytics.model_scores` (delete+insert) | `similar` only if `REC_MODEL_VERSION=4.0.0` | Needs ≥20 rows and 2 classes else writes a "note" row and leaves scores untouched; ~4 s runtime. |
| `warehouse_backfill` (manual) | BigQuery tables via `bq load --replace` | all warehouse consumers | Overwrites each table; does **not** create views; required args `--project/--instance/--staging` are missing from the DAG's `bash_command` so it fails as written (`repo:airflow/dags/warehouse_backfill_dag.py`). |

**Modification checklist (derived):**
- Pick the correct clock: use `timeutil.now()` and `local_day_window_utc`; never `now()` in SQL for business logic (dashboards do and are non-reproducible).
- Jobs are not idempotent; add natural keys or `DELETE … WHERE report_date=…` before inserting.
- Make refresh jobs transactional (single `BEGIN`), or write to a staging table and swap.
- If you change a filter (SKU/brand/status), decide explicitly whether to restate `report_rows`; otherwise you create another era (Section 4.2).
- When adding a status value, update `EXCLUDED_STATUSES`, `monthly_statement` (`status = 1` literal), `kpi_daily`/`trending`/`top_sellers` (literal `status = 1`), `actives_board` (`ARRAY[0,2,3]`) — all hard-coded separately.
- `scripts/rerun_kpis.py` is unsafe (legacy 40% default).
- Airflow DAGs set no timezone: cron strings were authored as ET and give different wall-clock times unless the Airflow default timezone is ET (**unverified**; Airflow was not accessible). Order dependencies (fraud 05:45 → report 06:00, affinity 03:30/03:45 → model_train 04:15) exist only as clock ordering, not DAG dependencies.

## 5.3 Recommendation (similar-products) serving path (`repo:novamart/routers/similar.py`)

1. `intended = REC_MODEL_VERSION` (aliases `2`,`v2`→2.0.0, `4`,`v4`,`model4`→4.0.0).
2. If `sha256(uid)[:8] % 20 == 0` (5% of *users*, 942 distinct users in the log) → **random arm**: `SELECT id FROM products WHERE id NOT IN (excluded) ORDER BY id LIMIT 500`, shuffle by seeded RNG, take 5. Logged to `analytics.rec_decision_log` with `arm='random'`.
3. Else read `analytics.product_affinity_v2` (when effective=2.0.0) or `analytics.model_scores`, `score >= 0 AND updated_at = MAX(updated_at)`, top 5, filter `EXCLUDED_SKUS`; in-process cache (6 h TTL) keyed `(table, pid)`, invalidated when `MAX(updated_at)` changes (`git:8ed2971`).
4. If empty → **fallback** to the latest `analytics.trending_daily` top 5 (no SKU filter), logged as `effective_version='fallback'`, `rec_source='fallback'`.
5. Every serve inserts a row in `analytics.rec_decision_log`; the same event is in `log:app_events` (`rec_served`).

Version history (`bq:novamart_analytics.rec_decision_log`, Q13):
- **v1.0.0** (2019-10-26 → 2019-12-06 16:40Z): reads `analytics.product_affinity`; 326,186 of 392,630 serves (83%) were `fallback/no_scores` yet logged `effective_version = 1.0.0` (the constant was written for both) — so *version* is not a reliable "model actually used" field in the v1 era; use `rec_source`.
- **v2.0.0** (from 12-06): `intended=2.0.0`; 31,268 `model` + 21,427 `model/cache` vs 182,868 `fallback/no_scores` + 25,091 `fallback/cache`. The `fallback/cache` rows (12-19 → 12-26) are an artefact of `git:a00f24c` caching **empty** lists keyed only by `pid`, fixed by `git:8ed2971` (cache key `(table,pid)`, only non-empty cached).
- **v4.0.0** (trainer from 12-15): never served: no decision-log row has `effective_version='4.0.0'` and `deploy/flags.env` is still `2.0.0`.
- Table version string `2.0.1` (`affinity_v2.py`) ≠ serving "2.0.0" — cosmetic, and `2.0.0` never existed in the table because its only run crashed (`bq:novamart_analytics.product_affinity_v2.model_version` = 2.0.1 for all 3,912 rows).

---

# 6. Data

## 6.1 Catalog (warehouse, row counts from `bq show`; writers from `repo:`)

**`novamart` (12 app tables; PG schema `public`)**

| Table | Rows | Grain / semantics | Notes |
|---|---|---|---|
| `orders` | 9,127 | one per merged order; `price` = order total, `product_id` = first product | statuses 1/2/3/6 only; `payment_ref` not unique (130 dup refs) |
| `order_lines` | 2,284 (2,059 orders) | line items since 2019-11-22 15:18Z | earlier orders have no lines (91 orders on 11-21/22 predate deploy; ids with lines before 11-22: 0) |
| `payments` | 9,361 | per gateway callback; 9 negative rows (gateway refunds); `payment_ref` NULL on 7,068 old rows | `SUM(gross)` per order = `orders.price` |
| `users` | 38,950 | first-seen ids | emails: 38,910 `@example.com`, 40 `@gmail.example` (all updated 2019-10-23) |
| `products` | 81,018 | catalog | 3,411 brands; 136 category codes; synthetic title/vendor/cost/stock |
| `cart_items` | 36,938 | cart adds (removes delete rows) | feeds affinity/funnel |
| `accounts`, `account_map` | 30, 30 | beta accounts | created 2019-12-01 16:30Z |
| `report_rows` | 6,923 | per (date, product) per run; 92 report dates | snapshot, no unique key |
| `report_rows_intraday` | 2,358 | per (date, product) per snapshot (2/day since 12-08) | |
| `statements` | 3 | Sep, Oct, Nov | no Dec |
| `top_products` | 2,396 | daily top 50 | |

**`novamart_analytics` (20 tables + 4 views)**

`kpi_daily` 45, `daily_funnel` 53, `trending_daily` 2,898, `product_affinity` 3,912 (2,964 sentinel −1; only 449 base products with ≥1 usable score), `product_affinity_v2` 3,912 (identical shape/coverage), `model_scores` 948, `model_registry` 17, `rec_decision_log` 667,850, `order_risk` 1,631, `price_suggestions` 500, `reorder_hints` 200, `price_history` 1,400 (weekly 200-item feed snapshots since 2019-11-18, 241 products), `digest_log` 15, `chargebacks` 3, `statement_overrides` 1, `statement_corrections` 1, `test_users` 1, `category_names` 135, `category_name_history` 6, `blank_brand_products` 5,972. Views: `contactable_users` (0 rows), `refunds_unified`, `statements_corrected`, `statements_final` (BigQuery DDL in `dumps/views_ddl_analytics.json`; original Postgres DDL in the engineer-backfill statements, `dumps/engineer_queries.txt`).

**`novamart_logs`:** `app_events` 1,570,017 (JSON events; types: product_viewed 843,085; rec_served 669,190; cart_item_added 36,925; duplicate_payment_ref 10,766; order_created 9,127; order_callback_replayed 522; order_appended 225; order_cancelled 54; order_refunded 28; user_email_updated 40; account_created 30; price_feed_received 13; gateway_refund 9; statement_fee_mismatch 3); `db_queries` 3,597,650 (raw Postgres statement log: tags `app` 3,266,348, `job` 331,111, `engineer:dev` 107, `engineer:maya` 52, `engineer-backfill:dev` 29, `engineer-backfill:maya` 3); `job_runs` 978 (JSON; includes `job_crashed` rows with service `ops`); view `db_queries_normalized` (reshapes `db_queries` statements into a BigQuery-JOBS-like schema: query text, statement_type, user_email=`<actor>@novamart.sim`, referenced_tables). The statement log records statements regardless of success (e.g. engineer queries referencing non-existent columns `total_amount`, `fraud_score`, `external_ref`, `charged_at` are present) — presence is **not** proof of effect (Q17).

## 6.2 Lineage (who writes, who reads) (Q17 consumer scan)

- `orders/payments/order_lines/cart_items/products/users` ← app routers; read by all jobs.
- `report_rows`, `report_rows_intraday` ← daily/intraday jobs → `redash:q7`, `q2`.
- `statements` ← `monthly_statement` → `statements_corrected` → `statements_final` → `redash:q5`.
- `trending_daily` ← `trending` → widget fallback (415,900 app table references 12-06→12-31; each fallback serve references it twice because of the `MAX(day)` subselect).
- `product_affinity` ← `affinity` → widget until 12-06 (392,630 reads), then nobody.
- `product_affinity_v2` ← `affinity_v2` → widget (306,838 app table references; each serve references it 2–3 times because of the `MAX(updated_at)` subselects) and `model_train` (17 job reads).
- `rec_decision_log` ← widget (insert) → `model_train` (select where `arm='random'`).
- `model_scores`/`model_registry` ← `model_train` → widget only if flag=4.0.0.
- `test_users` ← manual engineer insert (2019-11-27) → daily/intraday jobs (81 reads).
- `refunds_unified` ← orders statuses + negative payments → `redash:q1`.

## 6.3 Data quality traps (compact)

- Timestamp semantics: all UTC; business month/day = ET. `kpi_daily.day`/`daily_funnel.day` are run dates in UTC (`::date` of run ts).
- `orders.status=0` never persists; `updated_at` ≠ event time for batch mutations (cancel/refund at Tuesday 16:00Z; released orders carry a 2026 date).
- `statements` are append-only snapshots: do not "fix" them, add an override/restatement row and a view (existing pattern: `statement_overrides` PK on month).
- `analytics.*` tables rewritten nightly keep only the latest snapshot (affinity, model_scores, reorder_hints, price_suggestions); history exists only in logs.
- Blank brand/category: 21.5% / 41.4% of products; `brand=''` is a revenue bucket.
- Warehouse = one-shot copy: `bq load --replace` per table; columns typed by manifest (`NUMERIC` everywhere for money; ints as INT64) (`repo:warehouse_manifest.json`).
- `db_queries` has a Postgres statement log with parameters; Redash traffic is not in it (the log ends 2019-12-31, before Redash).

## 6.4 Recipes (copy/paste starting points)

- Live paid revenue for an ET month: `SELECT SUM(price) FROM novamart.orders WHERE status=1 AND created_at >= TIMESTAMP('2019-10-01','America/New_York') AND created_at < TIMESTAMP('2019-11-01','America/New_York')` (Q1 variant).
- De-duplicated: add `QUALIFY ROW_NUMBER() OVER (PARTITION BY payment_ref ORDER BY id) = 1` (Q3 logic).
- Per-product revenue after 2019-11-22: use `order_lines` (not `orders.product_id`) (Q8, dashboard `item_orders` CTE).
- Re-anchored dashboard replicas used in this study are in Appendix B (Q10, Q18).

---

# 7. Experimentation

There is no experimentation platform; there are four things that behave like experiments, all weakly instrumented.

## 7.1 Random-arm "data-collection" experiment (`git:df4ed85`)

- **Assignment:** `sha256(str(uid))[:8] % 20 == 0` → 5% of *users* (deterministic and permanent; 942 users in the log). The decision log records `arm` (`none`/`random`); there is no holdout *within* the non-random arm and no user-level experiment table.
- **Design flaws:** (1) the pool is the lowest 500 product ids (`ORDER BY id LIMIT 500`; ids 1,000,894–1,004,386, 483 of them smartphones) = 0.6% of a catalog of 81,018 — not "uniform random" over the catalog; (2) every exposure is 5 items, so the `served-list size` feature is constant; (3) logging was lost from 2019-12-17 16:50Z (`git:30e8907`) to 2019-12-19 14:55Z (`git:a00f24c`): 15,937 random serves in `app_events` vs 14,566 rows in `rec_decision_log` (1,371 missing; Q13); (4) same 5% of users forever means their exposure to bad recs is permanent.
- **Outcome measurement (Q13, my analysis, indicative only, 1-day window after exposure, 2019-12-06 16:40Z →):**

| arm / source | serves | any paid order within 1d | ordered one of the shown items within 1d |
|---|---|---|---|
| none / fallback (trending) | 207,959 | 5.87% | 0.136% |
| none / model (affinity v2) | 52,695 | 7.90% | 0.738% |
| random / random_arm | 14,566 | 5.51% | 0.000% |

Confounded: the model arm only serves base products that have scores (449 of 81,018) i.e. popular pages; the random arm is the only unbiased comparator and shows zero hits within 1 day over 14,566 exposures. No click/impression-visibility events exist, so CTR is unknowable.

## 7.2 Model versions

| Version | What it is | Evidence | Verdict |
|---|---|---|---|
| 1.0.0 | co-cart count × exp(−0.05·age), 30d window, `MIN_PAIRS=3` sentinel −1 | `git:776d674`, `git:fef5c96`, `git:f1217a8` | Real list only 17% of serves |
| 2.0.0 (table stamp 2.0.1) | `(1×pairs + 3×converted) × decay × 1.15 same-category × 0.7 if price ratio >4 or <0.25 × monthly factor` | `git:89666bf`, `git:3dbe4d7`, `repo:affinity_v2.py` | Same coverage as v1 (3,912 pairs, 449 usable base products); Dec factor falls back to 1.0 |
| 4.0.0 | logistic regression on random-arm exposures; label = *any* paid order by the user after the exposure (no time bound, positive rate 13.28%); 5 features (list size, base price/1000, base popularity/100, account age/60 capped, organic channel) | `git:a1946ff`, `repo:model_train.py`, Q14 | **No-op for ranking.** `score = v2_score × (1 + 0.1·coef[0])` where coef[0] is the weight on the constant `n_items`; on 12-31 coef[0] = −0.2448 → factor 0.9755 for all 948 rows (940 exactly 0.9755, 8 at 0.9756 from rounding). README claims features (signup channel, opt-in, region, device, stock) that are not in the vector. Coefficients flip sign between runs (price −1.36 → +0.39 → −0.53; organic −1.44 → +0.04 → −0.16) and there is no validation, holdout or metric in `model_registry`. |

## 7.3 Other tunings / flags (treated as experiments by the team)

| Knob | History | Evidence | Outcome |
|---|---|---|---|
| Fraud hold threshold | 0.90 (12-03) → 0.70 (12-05) → 0.85 (12-29) + manual `UPDATE orders SET status=1 WHERE status=6 AND price<2600` | `git:e4656fb`, `git:53f6f6c`, `git:1cb8721`, `log:db_queries` engineer-backfill:maya 2019-12-29 15:00Z; `log:job_runs` fraud_scored held counts (8 on 12-04, then 0–1/day) | 12 orders still held (≥ $2,655); 5 released (ids 7626, 7735, 8329, 8385, 9358) carry `updated_at=2026-08-13`; one released order (8329, score 0.857) would still exceed the new 0.85 threshold. No precision/recall data. Score = `min(price/3000,1)×(1+0.15 new_account+0.15 high_velocity)`, so it is essentially a price threshold (9 of 12 held have score exactly 1.0). |
| Dynamic pricing phase 1 | shadow suggestions nightly since 11-25; phase 2 on hold | `git:894c535`, `git:cca9b0d`, Q17 (no reads) | Pure shadow: orders use request price. |
| Trending window | 60 → 30 days | `git:f563dea` | Faster churn; README stale |
| Reorder constant K | 141.12 → 162.4 | `git:f85cdd2` | Hand fit; no validation |
| Funnel session gap | 30 → 120 min | `git:f915c1b` | Sessions not comparable across 12-14 |
| Seasonal factors | Jan–Nov planning sheet, Dec = 1.0 | `repo:affinity_v2.py` | Crash fixed, not modeled |
| `REC_MODEL_VERSION`, `ENABLE_DIGEST` | file flags | `repo:deploy/*` | Flags are read ad hoc (cwd-relative file reads) |

## 7.4 Judging "does the ML work?"
No: v1/v2 serve nothing for ~80% of traffic and mostly the trending list (including test SKUs), v4 is not served and is mathematically equivalent to v2 in ranking, the training label does not depend on the recommended items, the "random" arm is not catalog-random, and no impression/click instrumentation exists. Reorder hints are an inverse-velocity heuristic and price suggestions are unused shadow output.

---

# 8. Glossary

| Term | Meaning (with where it lives) |
|---|---|
| ET / local day | `America/New_York`; business day/month (`constants.LOCAL_TZ`) |
| Paid / `status=1` | order paid; the only status counted by statements, trending, top_sellers, kpi_daily |
| Status 0 / 2 / 3 / 6 | created / cancelled / refunded / fraud-held (5 and 4 unused) |
| Held order | status 6 set by `fraud_score`; counted by `daily_report` and KPI dashboard but not statements |
| Statement (published / corrected / final) | `public.statements` / `analytics.statements_corrected` / `analytics.statements_final` |
| Override / correction / chargeback | `statement_overrides` (value replacement), `statement_corrections` (audit delta), `chargebacks` (order-level booked amounts) |
| `report_rows` / intraday | per-product daily snapshot (units, revenue) / partial-day snapshots |
| Units | in reports = order lines (or legacy orders); in `top_products`/trending = orders by first product |
| Order line / merged order | `order_lines` row; orders merged within 15 min by same user+session (since 2019-11-22) |
| `payment_ref` (`PR-…`) | gateway reference; idempotency key since 2019-10-15; 130 duplicated historically |
| Gateway refund | negative payments row from `/payments/gateway_refund`; status unchanged |
| Active customer | one of three different definitions — always say which |
| Contactable | opted-in, valid non-example email (view returns 0) |
| Registered | accounts-beta user (30), mapped by email |
| QA user / test SKUs | user `424242`; SKUs `1004856`, `1002544` |
| Lucente / Jetem | brands hidden from exec reports |
| Item orders | dashboard CTE: `order_lines` ∪ legacy orders without lines |
| Affinity (v1/v2) | co-cart recommendation scores; v2 adds conversion weighting; −1 = insufficient data sentinel |
| Fallback | trending top-5 used when no affinity score |
| Random arm | 5% of users get 5 random of the 500 lowest-id products |
| `intended` vs `effective` version | flag value vs what was actually served (`fallback`) |
| Model v4 | logistic-regression scorer; rescales v2 scores uniformly |
| Reorder hint | `15.6 + K/(velocity+1.8)` heuristic |
| Price suggestion | ±5% shadow nudge |
| Digest | marketing email job; recipients = non-`@example.com` users (40) |
| FAKE_NOW | env var that overrides `timeutil.now()` |
| Engineer-backfill | tag in `db_queries` for manual DDL/DML by engineers (the source of the correction/override/test-user/category tables) |
| Surge (11-16/17) | 735+401 orders after a 0-order day 11-15 |

---

# Appendix A. Corrections to in-repo documentation and other stale statements

| Claim | Reality | Evidence |
|---|---|---|
| README: trending uses a 60-day window | 30 days since 2019-12-07 | `git:f563dea`, `log:job_runs` window_days |
| README "Rec model v4 features: … signup channel, marketing opt-in, region affinity, device mix, stock" | vector has 5 features; opt-in and stock are fetched and unused; region/device not used | `repo:model_train.py` |
| README "Serving is version 4.0.0 behind REC_MODEL_VERSION" | flag is 2.0.0; no 4.0.0 serves ever | `repo:deploy/flags.env`, Q13 |
| `docs/rec_versions.md` | "TBD" | `git:4396fbb` |
| `docs/affinity_lineage.md` "both nightly jobs still run; old job safe to drop for the widget" | correct for the widget; additionally the v1 table has had zero reads since 2019-12-06 | Q17 |
| `docs/restatement_policy.md` "use `statements_final` for current finance reporting" | numbers verified (1,194,652.79 / .93 / 1,191,085.36) but the view double-deducts and is incomplete (no Dec) | Q2 |
| `docs/metrics_definitions.md` three active definitions | accurate; omits that the board one evaluates to 0 and that kpi_daily includes QA | Q10 |
| `docs/dashboard_notes.md` | accurate vs SQL; omits that best_sellers does not exclude `EXCLUDED_SKUS`, and the UUID exclusion is a no-op | `redash:q9`, `q8` |
| `docs/forecast_caveats.md` "hint_units 55–102, velocity to 2.2857" | current table: 51–102, velocity to 2.7143 (newer snapshot) — formula and caveats correct | Q20 |
| `crontab.txt` "RETIRED" | runs observed under cron through 2019-12-31; Airflow DAGs: 16 files, intraday has one slot, backfill DAG lacks args | `repo:airflow/dags` |
| `docs/data-access.md` "analytics (20 tables + views)" | 20 tables + 4 views ✔; Redash data source is Postgres (`type: pg`), not BigQuery | `redash` `/api/data_sources` |

# Appendix B. Key queries (all read-only; full outputs in `queries.log`)

Let `P = novamart-warehouse.novamart`, `A = novamart-warehouse.novamart_analytics`, `L = novamart-warehouse.novamart_logs`.

- **Q1** `SELECT format_date('%Y-%m', date(created_at,'America/New_York')) m, status, count(*) n, round(sum(price),2) gross FROM P.orders GROUP BY 1,2 ORDER BY 1,2` (also counts by status; min/max created_at 2019-09-25 12:30Z / 2019-12-31 16:51:39Z).
- **Q2** `SELECT * FROM P.statements; SELECT * FROM A.statement_overrides; SELECT * FROM A.statement_corrections; SELECT * FROM A.chargebacks; SELECT * FROM A.statements_corrected ORDER BY month; SELECT * FROM A.statements_final ORDER BY month` and `SELECT table_name, view_definition FROM novamart-warehouse.novamart_analytics.INFORMATION_SCHEMA.VIEWS`.
- **Q3** `WITH r AS (SELECT o.*, row_number() OVER (PARTITION BY payment_ref ORDER BY id) rn, count(*) OVER (PARTITION BY payment_ref) c FROM P.orders o) SELECT month, countif(c>1 AND rn>1), sum(if(c>1 AND rn>1, price,0)), countif(c>1 AND rn>1 AND status=1), … GROUP BY month` → 130 refs / 285 orders / 155 extra / $59,812.52; also 226 refs ×2, 30 ×3, 24 ×4, 5 ×5; 152 of 155 duplicates identical on user/product/price.
- **Q4** `SELECT cast(updated_at as string), status, count(*), min(id), max(id), sum(price) FROM P.orders WHERE status IN (2,3) GROUP BY 1,2` → weekly Tuesday 16:00Z batches, ids 1–82.
- **Q5** `SELECT sign(gross), count(*), sum(gross), sum(fee) FROM P.payments GROUP BY 1` (+9 negative rows) and `SELECT format_timestamp('%Y-%m', at,'America/New_York'), count(*), sum(amount), countif(kind=…) FROM A.refunds_unified GROUP BY 1`.
- **Q6** per-payment fee pattern: `abs(fee − round(gross×0.029,2)) < 0.006` vs `+0.30` per month; first flat payment 2019-11-20 14:27:41Z, last pct-only 14:17:41Z; expected vs collected fee by month (Oct 0.00, Nov +9.62, Dec −55.93).
- **Q7** `WITH o AS (SELECT date(created_at,'America/New_York') d, count(*), sum(price) FROM P.orders WHERE status=1 GROUP BY 1), r AS (SELECT report_date, sum(units), sum(revenue) FROM P.report_rows GROUP BY 1) SELECT … o LEFT JOIN r` plus month sums of `report_rows` and the list of dates without report rows (2019-11-15, 2019-12-31).
- **Q8** `order_lines` min/max created_at; `SUM(order_lines.price)=orders.price` for 2,059 orders; multi-line orders (173, 398 lines, $113,405.23); `SUM(payments.gross)=orders.price` for 9,127 orders; orders on 11-21/22 without lines (91).
- **Q9** held orders (status 6) with prices/scores; `order_risk` joined to `orders` for score > 0.68; orders with `updated_at` on 2019-12-29 15–16Z / 2026-08-13.
- **Q10** active customers: `kpi_daily` replica `COUNT(DISTINCT user_id) … created_at >= ts − 30d AND status=1` = 1,152; board SQL translated to BigQuery = 0 (1,151 candidates, 1,150 non-test); KPI dashboard SQL re-anchored at 2019-12-31 (Section 4.4).
- **Q11** `SELECT split(email,'@')[offset(1)], count(*), countif(marketing_opt_in) FROM P.users GROUP BY 1` (38,910 example.com, 40 gmail.example); `SELECT count(*) FROM A.contactable_users` = 0; account_map ↔ accounts ↔ users mapping (30 rows incl. 424242).
- **Q12** daily views/carts/orders from `L.app_events` (event in `jsonPayload`), orders and carts per ET day Nov 8 – Dec 2, weekly orders/carts.
- **Q13** `SELECT intended_version, effective_version, rec_source, fallback_reason, arm, count(*), min(ts), max(ts) FROM A.rec_decision_log GROUP BY …`; random-arm loss check (`app_events rec_served arm='random'` 15,937 vs log 14,566); 1-day hit-rate query joining `rec_decision_log` to `orders`.
- **Q14** `model_scores` ÷ `product_affinity_v2` on (base_pid, rec_pid) = 0.9755 (940) / 0.9756 (8); `model_registry` coefficients (17 runs); random-arm `n_items`=5 for all 14,566 rows; positive rate 0.1328.
- **Q15** `trending_daily` for 2019-12-31 (ranks 2 and 3 = test SKUs); 118 test-SKU rows on 59 days; `rec_decision_log` fallback items `1004767,1004856,1002544,1005115,1005100` (13,672 serves on 12-30/31).
- **Q16** `L.job_runs` parsed (`dumps/job_runs_parsed.json`): counts by job/event; 3 `job_crashed` rows 2019-12-03/04/05 (`IndexError` in `affinity_v2.py:26`); run-time shifts after DST end; durations.
- **Q17** `L.db_queries`: actor-tag counts; all 191 `engineer*` statements (`dumps/engineer_queries.txt`); regex consumer scan `(FROM|JOIN) <table>` by tag/time.
- **Q18** best sellers / brand / category dashboard SQL translated to BigQuery and re-anchored at 2020-01-01Z.
- **Q19** brand/SKU facts: `internal` brand, 676 lucente / 5 jetem products, SKU 1004856 & 1002544 paid orders/revenue, excluded SKU/brand/QA revenue per month, `report_rows` contribution of excluded SKU/brand.
- **Q20** `reorder_hints`, `price_suggestions`, `digest_log`, `price_history` summaries.

Redash facts (`redash/` directory): 9 dashboards each with one TABLE widget over one query; all queries have `data_source_id=1` (`novamart`, type `pg`), no schedule, no cached result (`latest_query_data_id = null`); each query body is byte-identical to the last git version of the corresponding `dashboards/*.sql` before `git:41e3537` (verified programmatically). Dashboard→query: 1→1 refunds, 2→2 revenue_widget, 3→3 actives_board, 4→4 registered_conversion, 5→5 statements_final, 6→6 category_revenue, 7→9 best_sellers, 8→8 brand_revenue, 9→7 daily_kpis. API keys were redacted in the saved JSON.

# Appendix C. Open questions / things I could not verify

1. Whether `1004856` / `1002544` are really test SKUs (hundreds of distinct paying users, normal-range prices) — decides whether `EXCLUDED_SKUS` hides ~$106K of real revenue.
2. Root cause of the 11-15 zero-order day (carts/views surged but no `order_created`) and of the post-11-22 conversion drop; the repo and logs show no error events for either.
3. Airflow's configured timezone and whether `schedule` strings run in ET or UTC; Airflow UI/run history was not reachable.
4. Whether any leadership report reads `analytics.kpi_daily` (no reader found in repo, Redash or query log).
5. Whether the Dec-2019 statement will be produced as expected (job would run 2020-01-01; not in data) — my prediction of a −55.93 fee mismatch is derived from Q6, not observed.
6. Whether cancel/refund batches (ids 1–82) are complete or the pattern continues for other months.
7. The Redash queries were not executed (read-only constraint); values attributed to dashboards are from my BigQuery replicas of their SQL, re-anchored at 2020-01-01Z.

*End of document. Finished: Mon Oct 5 17:11 UTC 2026.*
