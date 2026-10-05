# NovaMart: Tribal Knowledge Handbook

- **Run ID (UUID):** `62a5b1a0-e5f1-4c44-8179-11c1a8544309`. **Started:** 2026-10-05 18:55:11 UTC.
- **Sources used (only these):**
  - Repo `novamart` pinned at `5ae1182`, plus its full git history (112 commits).
  - BigQuery emulator project `novamart-warehouse`, datasets `novamart`, `novamart_analytics`, `novamart_logs`.
  - Redash at `localhost:5054`, read-only.
- **Data window:**
  - Orders run from 2019-09-25 12:30 UTC to 2019-12-31 16:51 UTC (`novamart.orders`, [Q3]).
  - Logs run from 2019-09-16 to 2019-12-31 23:57 UTC (`novamart_logs.*`, [Q1]).
- **Citation conventions:**
  - `abc1234` is a git commit.
  - `dataset.table` is a warehouse table or view.
  - `[Qn]` is a query in Appendix B; the raw SQL and output are also in `queries_log.md` in this directory.
  - `[R-n]` is Redash query id *n*.
  - `[log: …]` is a log line from `novamart_logs.*`.
  - `file.py:line` is a repo path at `5ae1182`.

---

## 1. Summary

NovaMart is a FastAPI and Postgres marketplace backend. Its business numbers come from a handful of nightly batch jobs, a monthly statement job and nine Redash queries. Those surfaces **disagree with each other by design and by accident**. The things a tenured finance or data person knows:

1. **Revenue has at least six "official" numbers per month.** The published statement (`novamart.statements`), the fee-corrected view (`novamart_analytics.statements_corrected`) and the restated view (`novamart_analytics.statements_final`) are three of them. The other three are today's `status=1` orders, the daily report (`novamart.report_rows`) and the exec KPI and revenue widgets ([R-7], [R-2]).
   - For **October 2019** these are $1,230,332.43, $1,230,332.43, $1,226,764.86, $1,206,337.32, $1,201,082.08 and the dashboard-filtered variants ([Q2], [Q4], [Q11]).
   - Statements are **frozen snapshots of order status at generation time**. Later cancellations, refunds and fraud holds never flow back into them (`monthly_statement.py:26-46`, [Q5]).
2. **October is inflated by duplicate orders.** Gateway callback retries created 155 extra orders on 130 payment refs before idempotency shipped (`b676969`, 2019-10-15).
   - 151 of those duplicates are still `status=1`, worth **$58,828.24** ([Q7]).
   - They are in every October number, including `statements_final`.
   - `reconcile` has flagged the same 130 refs every night since 2019-10-19 and nobody acts on it ([Q25], [log: `duplicate_payment_ref`]).
3. **December revenue fell to ~$552k (from ~$1.1M in November). The evidence points to a silent checkout-callback failure, not lower demand.**
   - Since `5d1300d` (2019-11-22), every `/orders` call runs DDL (`ALTER TABLE payments ADD COLUMN IF NOT EXISTS …`).
   - In December, 6,142 callbacks started but only 1,961 persisted, so **about 68% failed**.
   - Most failures happen at the DDL step. Some fail after the `INSERT` and get rolled back ([Q9]).
   - Orders per day dropped from about 115 to about 35, while cart adds and views held or rose ([Q8], [Q9]).
   - Callback latency rose from about 4 ms to 400–700 ms on average, with a maximum of about 2 s ([Q10]).
4. **Other events shape November:**
   - **Zero orders on 2019-11-15** (no `/orders` statements at all that day).
   - A **sale-like spike on Nov 16–17** worth $358k, about a third of November ([Q8]).
   - The daily report **truncated Nov 17 at 500 rows**, missing $80.9k. This was fixed in `1233af8` but the stored history was never corrected ([Q11]).
5. **The "restated" October number rests on hand-picked chargebacks.**
   - `analytics.chargebacks` holds three orders (46, 49, 55). An engineer inserted them as "the first 3 October orders over $700" ([Q31], engineer-backfill 2019-12-09).
   - Two of those orders were later cancelled and one refunded ([Q2]).
   - Subtracting both chargebacks and refunds therefore double-counts them.
6. **Refund numbers are wrong in two ways.**
   - `analytics.refunds_unified` ([R-1]) counts **cancellations as refunds**.
   - The gateway refund webhook (`c49a7bb`) is not idempotent: the same three refunds were **replayed weekly, three times**, so $614.53 shows as $1,843.59 ([Q6]).
7. **The "test SKU" exclusion list is wrong.** `EXCLUDED_SKUS = [1004856, 1002544]` (`83fb3ed`):
   - **1002544** is a real Apple smartphone with about $66k of revenue.
   - **1004856** is a real Samsung phone whose catalog row was claimed first by a QA smoke test. It is now titled "Internal Test", brand `internal`, with 314 real orders worth $40.8k ([Q14]).
   - Both SKUs are hidden from the daily report and KPI dashboard.
   - Both are **served in 99% / 44% of all similar-product fallback impressions** and promoted by the email digest ([Q19], [Q25]).
8. **The three "active customer" definitions disagree (documented in `docs/metrics_definitions.md`). The board-deck one returns zero.**
   - Every user email is a placeholder `@example.com` or a `@gmail.example` address, and the board query excludes both ([Q21], [Q22], [R-3]).
   - `contactable_customers` is likewise always 0 ([Q22]).
9. **The ML recommender does not demonstrably work.**
   - About 80% of widget impressions are the trending fallback ([Q15]).
   - "Model v4" is only affinity v2 times a constant: identical top-5 for 449 of 449 products ([Q18]).
   - v4 has **never been served** (`deploy/flags.env` = `2.0.0`; zero decisions with intended version 4.0.0, [Q15]).
   - The 5% random-arm holdout converts as well as or better than treated users: 5.31% vs 4.96% ([Q17]).
10. **The batch platform is fragile.** Jobs are append-only and non-idempotent (daily report, statement, KPI, funnel). Many outputs have **no reader at all** ([Q24]). The Jan-2020 Airflow migration (`4bfcbe6`) silently changed several behaviours (see §5.4).
11. **Replay artefacts.** Backfill statements that used `NOW()` or `CURRENT_DATE` were stamped **2026-08-13** in the warehouse ([Q13], [Q23]). This affects the fraud-release `updated_at` and the category-taxonomy history.

**How to answer "what was revenue in month X, and why":** use §4.1. It has a per-month bridge that starts at the published statement and walks through every adjustment, each with evidence.

---

## 2. Why this project

- **The platform just moved and the knowledge did not.**
  - Data access moved: `d398b0d`, 2020-01-02.
  - Dashboards moved to Redash: `41e3537`, 2020-01-03.
  - Schedules moved to Airflow: `4bfcbe6`, 2020-01-04.
  - The warehouse was backfilled to BigQuery: `5ae1182`, 2020-01-05.
  - The SQL that defines the dashboards now lives only in Redash and in git history. The README says so explicitly: "old SQL files remain in git history under dashboards/" (README.md:45).
- **Two engineers hold the context.** Dev Kapoor and Maya Iyer authored every non-platform commit (`git log`). They ran 159 ad-hoc and 32 backfill statements directly against production (`novamart_logs.db_queries`, actors `engineer:*` and `engineer-backfill:*`, [Q31]). Several "official" tables were created only by those backfills and appear nowhere in code:
  - `analytics.statement_overrides`, `statements_corrected`, `statements_final`, `chargebacks`
  - `contactable_users`, `refunds_unified`, `category_names`, `category_name_history`, `test_users`, `price_history`
- **The numbers disagree and leadership sees them.** Finance asked "which October number is right" (`docs/restatement_policy.md`). An analyst saw trending churn (`docs/trending_notes.md`). Someone asked about pricing (`docs/pricing_status.md`) and about reorder hints (`docs/forecast_caveats.md`). The registered-conversion dashboard said "numbers look low" (`d6e34c6`).
- **Some repo docs are stale or wrong.**
  - The README claims a 60-day trending window. It has been 30 days since `f563dea`.
  - The README claims rec serving is version 4.0.0. `deploy/flags.env` says 2.0.0.
  - The README lists nine model features; five are used (`model_train.py:52-56`).
  - `docs/rec_versions.md` says "TBD".
- **The goal of this handbook:** let a newcomer answer revenue and KPI questions the way a tenured person would, know when not to trust a dashboard, judge whether the ML works, and change the batch jobs safely.

---

## 3. Business understanding

### 3.1 What the business is

- NovaMart is an online marketplace. Electronics dominate, especially Apple and Samsung smartphones ([Q28]).
- A storefront or payment gateway relays events to the backend, which records them in Postgres:
  - product views
  - cart adds and removes
  - payment-gateway order callbacks
  - cancels and refunds
  - gateway refund webhooks
  - a weekly vendor price feed (`source: acme_feed_v2`, 200 items each Monday, [log: `price_feed_received`])
- Sources: `novamart/routers/*.py`, `novamart/app.py`.
- **Order prices are taken from the callback body, not the catalog** (`orders.py:18`).
  - Order prices can be far from list price.
  - Example: $2,999.99 charged on a $28.83 bath item (order 7539, [Q13]).
- **Revenue model:** customers pay the order price (gross). The payment processor takes a fee. Net = gross − fee (`monthly_statement.py`).
  - No COGS exists. `products.cost_price` is **synthetic**: a deterministic hash giving 55–80% of price (`onboarding.py:42`). Do not use it for margin.
  - No discount data exists. `DISCOUNT_CAP` and `apply_discounts` are not used by any statement or report. The ops helper `scripts/rerun_kpis.py` calls `apply_discounts` without a cap, so it silently uses the **legacy 40% cap instead of the finance-approved 25%** (`35c581e`, `discounts.py:4`).
- **Processor fee:**
  - 2.9% per payment until 2019-11-20.
  - 2.9% + $0.30 per payment afterwards (`12e1c68`).
  - The flat fee actually starts at 2019-11-20 14:27 UTC, the deploy time. The statement's expected-fee logic assumes local midnight (`FEE_CHANGE_AT`, `monthly_statement.py:13`), so 64 payments on Nov 20 are mismatched ([Q30]).
  - Multi-line orders pay the $0.30 **per line** (one payment row per line), not per order ([Q26]).
- **Business timezone** is `America/New_York` (`constants.py:28`). Months and report days are local. Warehouse timestamps are UTC.
  - October in UTC is `2019-10-01 04:00` to `2019-11-01 04:00`.
  - November ends at `2019-12-01 05:00` UTC (engineers use exactly these bounds, [Q31]).

### 3.2 Core entities

| Entity | Table | Key facts |
|---|---|---|
| User | `novamart.users` (38,950) | Created on **first sight** (any view, cart or order), not at signup (`catalog.py:58-66`). Email is a placeholder `user{id}@example.com`. 40 users changed it to `cust{id}@gmail.example` on 2019-10-23 ([log: `user_email_updated`]). Region, channel, device, age band and opt-in are **hash-synthesized from the id** (`onboarding.py:25-35`), so channels split exactly evenly ([Q22]). |
| Account | `novamart.accounts` / `account_map` (30) | UUID "registered accounts beta". All 30 were created in one batch at 2019-12-01 16:30 UTC, including the QA user 424242 ([log: `account_created`]). The `/accounts` router was only mounted from 2019-11-27 to 2019-12-05 (`b567d9d` added it; `c49a7bb` dropped it from `app.py`). |
| Product | `novamart.products` (81,018) | Created on first sight with `ON CONFLICT DO NOTHING`, so **the first writer wins**. 17,442 products have a blank brand and 33,514 a blank category ([Q23]). A brand-repair UPDATE fills blank brands only (`ea0e97b`). |
| Cart item | `novamart.cart_items` (36,938) | Hard-deleted on removal (`carts.py:28`), so the history is lossy. |
| Order | `novamart.orders` (9,127) | One row per checkout. `product_id` is the **first item only**. `price` is the **sum of all lines** (`orders.py:79`). |
| Order line | `novamart.order_lines` (2,284) | Exists only since 2019-11-22 15:18 UTC (`5d1300d`). 173 orders have more than one line, and 225 lines were appended ([Q4] notes). |
| Payment | `novamart.payments` (9,361) | 9,127 initial payments + 225 appended-line payments + 9 negative gateway refunds = 9,361. `payment_ref` is NULL before 2019-11-22. |

### 3.3 Order status codes (tribal; never documented in one place)

| Code | Meaning | Evidence |
|---|---|---|
| 0 | Created, pending payment row (transient inside the callback) | `orders.py:93` |
| 1 | Paid / complete | `orders.py:104` |
| 2 | Cancelled (since 2019-10-28) | `8f19718` changed `STATUS_CANCELLED` from 4 to 2 |
| 3 | Refunded via `/orders/{id}/refund` (since 2019-11-15) | `d87cb3d` |
| 4 | Legacy "cancelled" constant before 2019-10-28. No rows exist today ([Q3]). An engineer still checked for it on 2019-11-19 ([Q31]). | initial import, `constants.py` |
| 5 | Unknown. Excluded by `reconcile` (`status <> 5`) since the initial import. No rows. | `reconcile.py:16` |
| 6 | Held by the fraud job (since 2019-12-04) | `e4656fb`, `fraud_score.py:46` |

- The cancel endpoint can cancel **paid** orders. It writes no negative payment (`orders.py:114-133`).
- Refund endpoint v1 flips status only. Refund v2 is the gateway webhook, which writes a negative payment and **leaves status at 1** (`payments_webhook.py`). **The two mechanisms are never reconciled.**

### 3.4 Company timeline

| Date (UTC) | Event | Evidence |
|---|---|---|
| 2019-09-15 | Initial import. Three cron jobs (reconcile, daily_report, monthly_statement) and four dashboards. | `2da4141` |
| 2019-09-25 | First order: the QA smoke test, user 424242, product 1004856. This created the "Internal Test" catalog row. | [Q14] |
| 2019-10-01 | Real traffic starts, along with gateway callback retries that create duplicate orders. | [Q7], [Q8] |
| 2019-10-08 | `EXCLUDED_SKUS` added | `83fb3ed` |
| 2019-10-15 | Callback idempotency by `payment_ref` | `b676969` |
| 2019-10-25 | `lucente` brand hidden "per partnerships" | `ba1fbfa` |
| 2019-10-26 | Similar-products widget v1.0.0 | `f1217a8` |
| 2019-11-02 | Statement fee switched to collected fees; October override booked | `a92c96d`, [Q31] |
| 2019-11-03 | DST fall-back undercounts the daily report; fixed 11-05 | `102c9b4` |
| 2019-11-14 to 17 | Traffic spike. 11-15 has zero orders; 11-17 hits the report's 500-row cap. | [Q8], [Q11], `1233af8` |
| 2019-11-20 | Fee becomes 2.9% + $0.30 | `12e1c68` |
| 2019-11-22 | Same-session order merging plus per-request DDL. Callback failures begin. | `5d1300d`, [Q9] |
| 2019-12-03 to 05 | affinity_v2 crashes in December (seasonal index) | [Q25], `3dbe4d7` |
| 2019-12-04 | Fraud auto-hold goes live (threshold 0.90, then 0.70 on 12-05, then 0.85 on 12-29) | `e4656fb`, `53f6f6c`, `1cb8721` |
| 2019-12-05 | Gateway refund webhook; order_lines-aware reporting | `c49a7bb`, `92596dc` |
| 2019-12-06 | Rec v2.0.0 plus 5% random arm; trending window cut to 30 days | `df4ed85`, `f563dea` |
| 2019-12-09 | Chargebacks and `statements_final` | `cd559d3`, [Q31] |
| 2019-12-14 | Rec "model v4" training (never served) | `a1946ff` |
| 2019-12-29 | Held orders under $2,600 released manually | [Q13] |
| 2020-01-02 to 05 | Platform migration (Redash, Airflow, BigQuery) | `d398b0d`, `41e3537`, `4bfcbe6`, `5ae1182` |

---

## 4. Metrics

### 4.1 Revenue: the definitive guide

#### 4.1.1 Revenue surfaces and what each counts

| Surface | Where | Window and grain | Status filter | Exclusions | Mutable? |
|---|---|---|---|---|---|
| **Published statement** | `novamart.statements` (writer: `monthly_statement.py`, 06:30 local on the 1st) | Local calendar month by **order `created_at`** | `status=1` **at run time** | none (includes test SKUs, QA, lucente, duplicates) | Append-only; a rerun appends a second row |
| Fee-corrected | `novamart_analytics.statements_corrected` (view) | same | same | same | Overrides from `analytics.statement_overrides` (1 row: Oct) |
| **Restated ("final")** | `novamart_analytics.statements_final` (view), Redash [R-5] | same | same | minus `analytics.chargebacks` grouped by order month | Changes whenever chargebacks are inserted |
| Live orders | `novamart.orders` | anything | usually `status=1` today | none | Changes with every cancel, refund or hold |
| **Daily report** | `novamart.report_rows` (writer: `daily_report.py`, 06:00 local) | Local day | **excludes 0, 2, 3 at run time; includes 6 (held)** | `EXCLUDED_SKUS` (since 10-08), `BRAND_DENYLIST` (lucente since 10-25, jetem since 12-15), `analytics.test_users` (since 11-27) | Frozen per day; reruns duplicate rows |
| Intraday snapshots | `novamart.report_rows_intraday` (12:00 and 17:00 local, since 12-08) | Today so far | same as daily | same | Append-only; multiple versions per day |
| Exec KPI dashboard | [R-7] `daily_kpis` | Last 13 closed days from report_rows, plus today from the latest intraday version | inherited | plus brand filter | n/a |
| Exec revenue widget | [R-2] `revenue_widget` | 6 closed days plus today | inherited | inherited | n/a |
| Brand / category / best sellers | [R-8], [R-6], [R-9] | **Rolling 30 / 30 / 7 × 24 h from `now()`** | **none**: includes cancelled, refunded and held | QA 424242, lucente/jetem; **not** `EXCLUDED_SKUS` | n/a |

#### 4.1.2 Per-month bridge

All figures in USD, local-month windows. Sources: [Q2], [Q4], [Q7], [Q11], [Q26].

| | Sep-2019 | Oct-2019 | Nov-2019 | Dec-2019 |
|---|---|---|---|---|
| Published statement gross / net (`statements`) | 2,702.00 / 2,623.64 (12 orders) | 1,230,332.43 / 1,194,652.79 (3,765) | 1,101,397.01 / 1,069,286.09 (3,582) | *not generated (job would run 2020-01-01)* |
| Fee-corrected net (`statements_corrected`) | same | 1,194,652.93 (fee 35,679.64 → 35,679.50) | same | n/a |
| Restated gross / net (`statements_final`) | same | 1,226,764.86 / 1,191,085.36 (−3,567.57 chargebacks) | same | n/a |
| All orders today, any status | 2,702.00 | 1,230,332.43 | 1,101,397.01 | 592,542.22 |
| `status=1` today | **0.00** (all 12 cancelled or refunded later) | 1,206,337.32 (3,695) | 1,101,397.01 | 552,328.93 (1,756) |
| …of which duplicate-callback orders | 0 | **58,828.24** (151 orders) | 0 | 0 |
| `status=1`, de-duplicated by `payment_ref` | 0 | 1,147,509.08 | 1,101,397.01 | 552,328.93 |
| Held (status 6), excluded from status=1 | 0 | 0 | 0 | 40,213.29 (12 orders) |
| Daily report sum (`report_rows`) | 2,702.00 | 1,201,082.08 | 966,974.33 | 535,561.72 (Dec 1–30) |
| Would-be Dec statement (current data) | | | | gross 552,328.93, fee 16,600.26, net 535,728.67 |

#### 4.1.3 Why each month looks the way it does

**September**
- Only 12 orders: QA on 09-25, then 11 real orders on 09-30.
- The statement used `gross × 2.9%` as the fee ($78.36). Collected fees were $78.37 ([log: `statement_fee_mismatch` delta −0.01]).
- All 12 orders were later cancelled or refunded in weekly batches ([Q5]). The statement still shows $2,702. This is the clearest example of statements being snapshots.

**October** (all items are evidence-backed)
1. The statement was generated 2019-11-01 10:30 UTC, **before** `a92c96d`. Fee = 2.9% × gross = 35,679.64, while collected per-payment fees were 35,679.50 (rounding per payment). Dev booked an override on 11-02 ([Q31] engineer-backfill), which is the source of `statements_corrected`.
   - The override reuses the original `created_at` (2019-11-01 10:30), so the correction's real date (11-02) is invisible in the view.
2. **151 duplicate orders** ($58,828.24) from gateway retries between 10-01 and 10-15 are still counted ([Q7]). `b676969` stopped new duplicates but **did not clean up** existing ones. `reconcile` logs the same 130 refs nightly ([Q25]).
3. 70 October orders were later cancelled (43, $10,748.42) or refunded (27, $13,246.69). This happened in weekly batches on Tuesdays, 11-05 to 12-31 ([Q5]). The statement and `statements_final` ignore all of them.
4. `statements_final` subtracts 3 "chargebacks" (orders 46, 49, 55; $3,567.57). They were inserted on 12-09 by a heuristic: the first three October orders over $700, `LIMIT 3`, with a fixed `reported_at` of 2019-12-01 12:00 ([Q31]).
   - Orders 46 and 49 were then cancelled or refunded on 12-10, and order 55 was cancelled on 12-17 ([Q2]).
   - **Do not subtract both chargebacks and refunds for these orders.**
5. Three October orders (3762, 3763, 3776) received the **same gateway refund three times** (12-13, 12-20, 12-27; [Q6]). Their status is still 1, so the statement ignores them. `refunds_unified` triple-counts them (true refund $614.53).
6. Test SKUs (1004856, 1002544) were in the statement but excluded from `report_rows` from 10-08. Lucente was excluded from 10-25. These two exclusions explain the statement-to-report gap day by day ([Q11]).

**November**
- The statement ($1,101,397.01) still equals today's `status=1`. No November order has changed status, and there are no overrides or chargebacks.
- `statement_corrections` has an "audit correction" with **delta 0.00** ([Q2]). No view uses it.
- The fee mismatch warning (delta −170.41) came from the expected-fee formula ignoring the $0.30 flat fee. It was fixed in `4a58d17`.
- Shape of the month:
  - 11-15 has zero recorded orders: no `/orders` SQL that day despite 27.6k views and 2.1k cart adds ([Q8]).
  - 11-16 and 11-17 together = $358,016.02 (1,136 orders), roughly a third of the month.
  - From 11-22 orders per day collapse (see December).
- The daily report total ($966,974.33) is low because:
  - 11-17 was truncated by `REPORT_SCAN_CAP=500`: 487 units reported of 735 orders, −$80,923.42 ([Q11]; job log `orders_scanned: 500`).
  - 11-03 lost the 23:00–24:00 hour to the DST bug: about −$2,986 beyond normal exclusions ([Q11], `102c9b4`, engineer query 11-05).
  - The normal SKU and brand exclusions apply.

**December**
- No statement exists yet. Rerunning the job logic on current data gives gross $552,328.93, fee $16,600.26 and net $535,728.67 ([Q26]).
  - The job would also log `statement_fee_mismatch` of about −$55.93, because the expected-fee formula charges $0.30 per order while multi-line orders pay $0.30 per line.
- Held orders are excluded from status=1 revenue:
  - 12 orders worth $40,213.29 remain held. Eight of them are $2,999.99 orders on 12-03 for items listing at $28–$1,905 ([Q13]).
  - 5 orders ($10,859.73) were released by hand on 12-29 with `UPDATE orders SET status = 1, updated_at = NOW() WHERE status = 6 AND price < 2600` ([Q13]). The release cutoff of $2,600 does not match the new 0.85 threshold, which corresponds to $2,550 with no boosts. Order 8329 (score 0.857) was released even though it exceeds 0.85.
- **The big one: recorded December is structurally understated.**
  - db_queries shows 6,142 `/orders` requests started in December ([Q9]).
  - Only 2,598 of them passed `ALTER TABLE payments ADD COLUMN IF NOT EXISTS payment_ref`.
  - Only 1,961 persisted: 1,768 new orders plus 193 appended lines. The `order_created` and `order_appended` app events match those counts.
  - 2,261 `INSERT INTO orders` statements were logged but only 1,768 orders exist, so **493 inserts were rolled back**. Before 11-22, logged inserts equal persisted orders (October 3,765 = 3,765) ([Q9]).
  - Gaps between failed requests have the same distribution as gaps between successful ones (median ~200 s), so failures are not quick retries ([Q9b]).
  - If each failed attempt was a distinct purchase, December lost about 4.2k checkouts. At December's ~$300 average per persisted callback, that is **up to about $1.2M**.
  - **Treat this as an unverified upper bound.** Whether the gateway captured that money cannot be checked from available data.
  - The likely mechanism (inference):
    - App requests run inside one transaction per pooled connection. `db.py` uses psycopg's `AsyncConnectionPool`, which is non-autocommit, unlike `job_connect(autocommit=True)`.
    - So the per-request `ALTER TABLE payments …` takes a table-level lock on `payments` and holds it until commit.
    - That serializes concurrent callbacks, which then fail on lock timeout and roll back. Callback durations jumped from ~4 ms to ~400–700 ms average with a ~2 s ceiling on 11-22 ([Q10]). The app logs no errors, so nothing alerted.

#### 4.1.4 Which number to use

| Question | Use | Caveat to say out loud |
|---|---|---|
| "What did we publish?" | `novamart.statements` | Snapshot at generation; includes duplicates and test SKUs |
| "Current restated finance number" | `statements_final` (per `docs/restatement_policy.md`) | Includes 151 October duplicates ($58.8k) and the 70 later October cancellations/refunds. Chargebacks are a hand-picked placeholder. |
| "Economically true October" | `status=1`, de-duplicated by `payment_ref`, minus true gateway refunds | $1,147,509.08 − $614.53 ≈ $1,146,894.55 gross ([Q4], [Q6]). Not an official number. |
| Daily or product trend | `report_rows`, latest version per day | Excludes 1002544 and 1004856 (real products). Includes held orders. Pre-11-19 busy days may be truncated. |
| December | Compute from orders (`status=1`, local window) | Understated by failed callbacks |

### 4.2 Orders and units

- **"Orders" on [R-7] is not orders.** It is `SUM(report_rows.units)`, i.e. item lines, since `92596dc` (2019-12-05). On Dec 29 the dashboard shows 89 "orders" for 79 actual orders ([Q11]).
- `top_products.units` (`top_sellers.py`) is a **count of orders per first product** (`orders.product_id`). Multi-item orders undercount secondary items.
- These consumers still key on `orders.product_id` and therefore ignore 225 appended lines:
  - trending
  - affinity_v2 conversion
  - price_suggest
  - reorder_forecast
  - email_digest
  - fraud velocity (counts orders)
- Source: code in the respective `jobs/*.py`.
- Order merging: callbacks in the same session within 15 minutes are appended to the open order (`orders.py:67-89`). Order counts after 11-22 are therefore not comparable with earlier ones.

### 4.3 Payments and fees

- `SUM(payments.gross WHERE gross>0)` equals order gross per month (Oct 1,230,332.43; Nov 1,101,397.01; Dec 592,542.22) ([Q4]). Payments **mirror** orders. They are not gateway truth, except the negative webhook rows.
- Fee rule check:
  - All 6,758 payments before the change are exactly `round(gross×0.029, 2)`.
  - 2,528 of 2,594 payments after local-midnight Nov 20 are `round(gross×0.029+0.30, 2)`; the other 64 are from Nov 20 before the 14:27 UTC deploy ([Q30]).

### 4.4 Refunds and cancellations

- [R-1] `refunds` reads `analytics.refunds_unified`, created by an engineer backfill on 2019-12-23 ([Q31]). That view is the union of:
  - status 2 orders labelled `order_cancelled`
  - status 3 orders labelled `order_refunded`
  - every payment row with negative gross or net, labelled `gateway_refund`
- Trust issues:
  - Cancellations count as refunds.
  - `at` = `orders.updated_at`, which is mutable and is not the refund time for later updates.
  - Webhook replays are counted multiple times.
  - Legacy status 4 is not covered.
  - Refunds are grouped by **event month**, while statements group by **order month**.
- Values:
  - Nov: 24 cancellations ($6,511.32) and 8 refunds ($3,180.45).
  - Dec: 30 cancellations ($6,738.32), 20 refunds ($10,267.02) and 9 gateway rows ($1,843.59, of which $614.53 is unique) ([Q6]).

### 4.5 Customer metrics

| Metric | Definition | Value at end of 2019 | Trust |
|---|---|---|---|
| `analytics.kpi_daily.active_customers` | Distinct `orders.user_id` with `status=1`, trailing 30×24 h from 06:15 local; no QA exclusion (`kpi_daily.py`, `14726e7`) | 1,152 on 12-31; recomputes exactly ([Q21]) | Mechanically OK. Collapses 1,560 → 1,011 between 12-16 and 12-19 because the Nov 16–17 spike leaves the window. Statuses mutate, so recomputing older days won't match. **No reader anywhere** ([Q24]). |
| [R-7] `active_customers` | Distinct ordering users per local day, **no status filter**, excludes 424242, brand filter applied to the **first product only** | 44–75 per day in late Dec ([Q21]) | A daily count, not 30-day. Not comparable with kpi_daily. |
| [R-7] `contactable_customers` | Users in `analytics.contactable_users` (opted in, valid email, not example.* or *.example) | **0 every day** ([Q22]) | The view is empty: every email is `@example.com` or `@gmail.example`. |
| [R-3] Board actives | 30 days, status not in (0, 2, 3) (so **held orders count**), excludes `test_users` plus email heuristics (`2dde4f0`) | **0** (1,149 candidates → 0) ([Q21]) | **Never trust.** The email filter removes every user. |
| [R-4] Registered conversion | Accounts mapped to users by email, then `status=1` orders (`b975479`) | 30 buyers, $18,155.71 ([Q29]) | All 30 accounts were backfilled for existing buyers, so "conversion" is 100% by construction. Includes the QA user (13 orders). `account_map` gives the same answer more directly. |
| "Signups" / new users | No signup event exists. `users.created_at` = first sighting. | Oct 15,045; Nov 11,302; Dec 12,529 ([Q22]) | Measures first-seen visitors, not registrations. |
| Email digest recipients | `users` with email `NOT LIKE '%@example.com'` (`email_digest.py:51`) | 40 per day ([Q25]) | Ignores `marketing_opt_in`: 17 of the 40 did not opt in. Includes QA 424242. Does not use `contactable_users`. |

**Segments in use**
- `analytics.test_users`: one row, 424242 (inserted 11-27, [Q31]).
- The QA account UUID `cc27b436-…` is excluded as a string in [R-8] (`adbcb7e`). That exclusion is a no-op: `orders.user_id` is always numeric.
- `new_account`: first seen less than 7 days before the order (fraud job).
- Random-arm users: `sha256(uid) % 20 == 0` (similar.py).
- Opted-in users: hash-synthesized, 62% target (`onboarding.py:34`).

### 4.6 Product performance metrics

| Metric | Source | Assumptions that matter |
|---|---|---|
| Best sellers | [R-9] | Rolling 7×24 h from `now()`. Counts order_lines with a legacy fallback. **No status filter** (includes held and cancelled). Excludes 424242 and lucente/jetem. **Ranked by revenue, not units.** Does **not** exclude `EXCLUDED_SKUS`, so 1002544 ranks #7 ([Q28]). |
| Top sellers (nightly) | `novamart.top_products` (`top_sellers.py`) | Yesterday local, `status=1`, **units = orders on `orders.product_id`**, no exclusions, top 50 by units. **No reader** ([Q24]). |
| Trending | `analytics.trending_daily` (`trending.py`) | 30-day window (60 until 12-06; [Q25] logs `window_days`). ≥5 orders. Score = orders × exp(−0.05 × days since last order). No SKU, QA or brand exclusion: on 12-31 **1004856 is #2 and 1002544 is #3** ([Q19]). Feeds the homepage and the widget fallback. |
| Brand revenue | [R-8] | 30 days, no status filter. Blank brand appears as a `''` row (~$17k per 30 days). The "internal" brand is the 1004856 collision ([Q28]). Lucente has 141 orders lifetime; **jetem has zero orders**, so hiding it changed nothing ([Q14b]). |
| Category revenue | [R-6] | 30 days. Taxonomy from `analytics.category_names` (top-level prefix map; 52 of 135 codes → "other") plus `category_name_history`. The Dec-12 remap of audio → "entertainment" and lights → "lighting" carries `valid_from = 2026-08-13` in the warehouse (replay artefact), so **it never applies** to 2019 orders ([Q23]). |
| Monthly brand API | `/reports/brands` (`reports.py`) | **Not mounted**: dropped from `app.py` by `f1217a8` on 2019-10-26. Dead code. |

### 4.7 Funnel

- Table: `analytics.daily_funnel` (`funnel.py`).
- Sessions are built from **cart and order events only** (views are ignored). The gap was 30 min until 12-14, then 120 min (`f915c1b`; [Q25] `gap_min`).
- `day` = the run date (UTC `ts::date`), but the data is the **previous 24 h**, so labels are off by one day.
- **No reader** ([Q24]).

### 4.8 Recommendation metrics

- Logged per impression in `analytics.rec_decision_log`, with `intended_version`, `effective_version`, `rec_source`, `fallback_reason` and `arm`.
- There is **no click logging**. The only outcome is subsequent orders.
- See §7 for results.

---

## 5. System

### 5.1 Architecture

```
Storefront / payment gateway ──HTTP──> FastAPI app (novamart/app.py, uvicorn --workers 4, pool max 22)
   routers mounted: catalog, carts, orders, similar, payments_webhook   (users/reports/accounts NOT mounted)
        │ every statement logged → db_queries.log ([app]/[job] tags) → BQ novamart_logs.db_queries
        │ app events → app.jsonl → BQ novamart_logs.app_events; job events → jobs.jsonl → novamart_logs.job_runs
        ▼
Postgres (serving; Cloud SQL replica per docs/data-access.md)  ◄── Redash data source "novamart" (type pg) [R-1..9]
        │ one-shot export (novamart.jobs.warehouse_backfill, Jan 2020)
        ▼
BigQuery novamart / novamart_analytics (snapshot; no scheduled refresh)
Batch jobs: crontab (local times, retired) → Airflow DAGs (airflow/dags/*.py)
```

Evidence: `novamart/app.py`, `db.py`, `logutil.py`, `config.py`, `docs/data-access.md`, Redash `/api/data_sources` (type `pg`).

**Redash reads Postgres, not BigQuery.** The two will drift, because the warehouse DAG is manual (`schedule=None`).

### 5.2 API behaviour that shapes the data

- `/orders`:
  - Idempotent by `payment_ref` (advisory locks on session and ref).
  - Merges same-session callbacks within 15 minutes.
  - Runs **5 DDL statements on every call** (`orders.py:24-36`), which is the root cause of the post-11-22 failures ([Q9]).
  - Pre-11-22 duplicates are not reconciled.
  - The replay check treats a gateway-refund payment row (NULL `payment_ref`) as "has payment" (`orders.py:46-47`), an edge case for replays after a refund.
- `/payments/gateway_refund`: inserts a negative payment and does **not** de-duplicate (`payments_webhook.py`, [Q6]).
- `/products/{pid}` and the price feed:
  - First writer wins (`ON CONFLICT DO NOTHING`).
  - The feed upserts prices since `d213f6e` (11-09). Before that, price updates for existing products were ignored (engineer queries on 11-09, [Q31]).
  - The feed sends no brand or category, so products first seen via the feed are "Unbranded Item" (`catalog.py`, [Q14]).
  - It writes `analytics.price_history`, a table created by an engineer backfill and absent from `schema.sql` ([Q31]).
- `/products/{pid}/similar`: see §5.5.

### 5.3 Batch job inventory

Schedules are crontab local times (`crontab.txt`) and are mirrored as Airflow cron strings in `airflow/dags/*`.

| Job | Schedule | Writes | Pattern | Read by | When it fails |
|---|---|---|---|---|---|
| reconcile | 03:00 (02:00 before `388370b`) | app log `duplicate_payment_ref` | read-only; `LIMIT 200` | humans only | Nothing; it re-flags the same 130 refs nightly ([Q25]) |
| affinity (v1) | 03:30 | `analytics.product_affinity` | DELETE + row INSERTs | **nobody since 2019-12-06 16:40 UTC** ([Q24]) | **But it is the only code that creates `analytics.rec_decision_log`** (`affinity.py:29-33`). Deleting the job (as `docs/affinity_lineage.md` suggests) breaks fresh environments: the widget INSERT into the log is not in try/except. |
| affinity_v2 | 03:45 | `analytics.product_affinity_v2` (stamped `2.0.1`) | DELETE + INSERTs | widget (v2.0.0), model_train | Crashed 12-03 to 12-05 (`IndexError` in December, [Q25]). Widget falls back to trending. |
| model_train | 04:15 | `analytics.model_registry`, `analytics.model_scores` | DELETE + INSERTs | **nobody** (flag never flipped, [Q24]) | No user impact |
| price_suggest | 04:45 | `analytics.price_suggestions` | DELETE + INSERTs | **nobody** (shadow, held 12-02, `cca9b0d`) | None |
| trending | 05:15 | `analytics.trending_daily` | delete-by-day, idempotent | widget fallback (~80% of impressions), homepage | Stale fallback items |
| fraud_score | 05:45 | `analytics.order_risk`; **mutates `orders.status` → 6** | append | statements, KPI and trending exclude status 6 | Held orders drop out of revenue until released by hand ([Q13]) |
| daily_report | 06:00 | `report_rows` | **append, non-idempotent** | [R-7], [R-2] | A missing day shows as missing on the dashboard; a rerun duplicates rows (the dashboard uses the latest `created_at`, but the old widget did not) |
| kpi_daily | 06:15 | `analytics.kpi_daily` | append | nobody | none |
| funnel | 06:20 | `analytics.daily_funnel` | append | nobody | none |
| monthly_statement | 06:30 on the 1st | `statements` | append | statements views, [R-5] | A rerun appends a second row for the month, which **duplicates months in `statements_corrected/final`** (LEFT JOIN on month). The job takes no month argument (uses "last month" or `FAKE_NOW`). |
| top_sellers | 06:45 | `top_products` | append | nobody | none |
| reorder_forecast | 06:50 | `analytics.reorder_hints` | DELETE + INSERTs | nobody (1 human read) | Advisory only. The formula is inverse in velocity: hints of 102 at velocity 0.07 vs 51 at 2.7 ([Q25]; `docs/forecast_caveats.md`). |
| email_digest | 07:15 | `analytics.digest_log` | append | n/a | First ran 12-17, three weeks after it was added (flag bugs `8dc520b`, `0bd4eac`). Sends to non-opted-in users and promotes excluded SKUs ([Q25]). |
| intraday_report | 12:00 and 17:00 | `report_rows_intraday` | append | [R-7], [R-2] | Today's tile is missing |
| warehouse_backfill | manual | BigQuery | `bq load --replace` | warehouse | The DAG passes **no** required `--project/--instance/--staging` arguments, so argparse exits if triggered as-is (`warehouse_backfill_dag.py:18-19` vs `warehouse_backfill.py:48-50`). The manifest targets dataset `analytics`, but the live dataset is `novamart_analytics`. |

### 5.4 What the Airflow migration changed silently (`4bfcbe6`)

- **The intraday report lost its 17:00 run.** The DAG is `0 12 * * *` only.
- **Times were local in crontab ("times are local").** Airflow cron strings with a naive `start_date` run in Airflow's default timezone, which is UTC unless configured. This could not be verified (no Airflow access). If it is UTC:
  - intraday runs at about 07:00 ET (a nearly empty "today")
  - the statement runs at about 01:30 ET
- **The DAGs have no inter-DAG dependencies.** Ordering used to be implicit in cron times: affinity_v2 → model_train, trending → widget fallback.
- **The flag files are read relative to the working directory.** `email_digest.cron_env_flag` opens `deploy/cron.env` and `similar.intended_version` opens `deploy/flags.env`. A `BashOperator` does not run from the repo root by default, so the digest may silently disable itself.
  - The widget falls back to `2.0.0` on `OSError`, which hides a missing flag file (`similar.py:37-45`).

### 5.5 The recommendation system ("similar products" widget)

**Version history** (`similar.py`, `REC_VERSIONS`; [Q15])

| Version | Live | Source table | Notes |
|---|---|---|---|
| 1.0.0 | 2019-10-26 → 2019-12-06 ~16:40 UTC (last v1 decision 16:39:58, first v2 16:40:11) | `analytics.product_affinity` (co-cart pairs, 30 days, exp decay; `-1` sentinel for pairs seen fewer than 3 times since `fef5c96`) | Fallback = 7-day best sellers from orders. **83% of 392,630 impressions were fallback.** |
| 2.0.0 ("affinity v2 exploit") | 2019-12-06 → now (`deploy/flags.env`) | `analytics.product_affinity_v2` | Score = (pairs + 3 × "converted") × decay × 1.15 for same category × 0.7 for price jumps × **seasonal factor**. The seasonal factor multiplies every score by the same number, so it cannot change rankings; it only crashed December runs. "Converted" = the co-carting user ever ordered `c2.product_id` (any time, first-line only). Rows are stamped `2.0.1` (`3dbe4d7`). Fallback = trending. |
| 4.0.0 ("trained model") | **never served** | `analytics.model_scores` | See below. Zero decisions with `intended_version='4.0.0'` ([Q15]). The README claim "Serving is version 4.0.0" is false. |

**Serving logic** (`similar.py:68-131`)
- 5% of users are in the random arm (`sha256(uid)[:8] % 20 == 0`).
  - The pool is `SELECT id FROM products … ORDER BY id LIMIT 500`: the **500 lowest product ids** (1000894–1004386), not the catalog. Only 107 of them ever sold ([Q17b]).
- Everyone else gets the top-5 rows from the version's table where `score >= 0` and `updated_at = MAX(updated_at)`.
  - Empty results fall back to the latest `trending_daily` top 5. **This path does not filter `EXCLUDED_SKUS`** ([Q19]).
- Caching:
  - 6 h in-process cache from `a00f24c` (12-19).
  - Until `8ed2971` (12-26) the cache stored **empty** results. That produced 25,091 `fallback/cache` impressions, where products got the fallback for up to 6 h even after scores existed ([Q15]).
  - Since 12-26, each request issues `SELECT MAX(updated_at)` to invalidate the cache, so the cache saves little DB load.
- **Random-arm decision logging was dropped** by the refactor `30e8907` (12-17 16:50) and restored by `a00f24c` (12-19). That lost 1,340 random exposures from the training data (served events vs logged rows, [Q20]).
  - `model_registry.train_rows` is identical (5,798) on 12-18 and 12-19 ([Q18]).

**"Model v4"** (`model_train.py`)
- Logistic regression on random-arm impressions.
- Label = the user placed **any** `status=1` order **at any time after** the impression. The label is unrelated to the recommended items and has no window, so older impressions have more time to "convert".
- Features actually used (5):
  - `n_items`, which is constant at 5 in the random arm, so it is collinear with the intercept
  - base price
  - base popularity
  - account age (from first-seen time)
  - `organic` channel (hash-synthesized noise)
- README-listed features that are absent: opt-in (fetched, unused), region, device, stock (fetched, unused).
- Scoring: `model_scores = affinity_v2.score × (1 + 0.1 × coef[n_items])`. That is **a positive constant (≈0.92–0.98) times v2**, so the ranking is identical to v2 for 449 of 449 base products ([Q18]).
- Coefficients swing sign from night to night (`model_registry.coef_json`, [Q18]).
- Conclusion: v4 is not a model of recommendation quality, and flipping the flag would change nothing user-visible.

**Coverage**
- Only 449 of 81,018 products have any usable (≥0) affinity row.
- 2,964 of 3,912 pairs are the `-1` sentinel ([Q18]).
- v1 and v2 tables have the same pair set. v2's top-5 equals v1's for 392 of 449 products ([Q18]).

### 5.6 Fraud scoring

- `core = min(price/3000, 1)`, boosted by +15% for a new account (first seen under 7 days) and +15% for 3 or more orders in 24 h.
- Orders above the threshold are moved to status 6 (`fraud_score.py`).
- Threshold history:
  - 0.90 (`e4656fb`, 12-03)
  - 0.70 (`53f6f6c`, 12-05)
  - 0.85 (`1cb8721`, 12-29), plus the manual release ([Q13])
- In effect the job is a price cap: any order of $2,550 or more is held unless boosted.
- Held orders are **excluded** from:
  - statements
  - kpi_daily
  - trending
  - top_sellers
- Held orders are **included** in:
  - report_rows (`EXCLUDED_STATUSES=[0,2,3]`)
  - the brand, category and best-seller dashboards
  - the board actives query
- So the same order is revenue in one place and not another.
- The job scores only orders from the last 24 h. Releasing an order does not re-score it.

### 5.7 Safe-modification checklist (tribal)

1. **Table creation is scattered.** Many tables are created lazily by code paths you might delete:

   | Table | Created by |
   |---|---|
   | `rec_decision_log` | affinity v1 job |
   | `test_users` | daily/intraday report |
   | `order_lines` | `/orders` per request |
   | `accounts` | `/accounts` (not mounted) |
   | `price_history`, `category_*`, `statement_*`, `chargebacks`, views | engineer backfills only ([Q31]) |

   `schema.sql` creates only 7 tables. CI (`ci/run_ci.py`) exercises only reconcile, daily_report and monthly_statement.
2. **Never rerun** `daily_report`, `monthly_statement`, `kpi_daily`, `funnel` or `top_sellers` without deleting the prior rows: they append. Dashboards pick the latest `created_at` for report tables, but other consumers do not.
3. **DELETE-then-INSERT under autocommit** (affinity, affinity_v2, model_scores, price_suggestions, reorder_hints) exposes empty or partial tables to readers while the job runs. Today each run takes about 0.2 s (job_runs `duration_ms`). It becomes a real risk if data grows.
4. Any change to `EXCLUDED_STATUSES`, `EXCLUDED_SKUS` or `BRAND_DENYLIST` changes **future** report_rows only. History is not restated.
5. Do not put DDL in request handlers (§4.1.3, [Q9]).
6. `FAKE_NOW` is the only way to backfill a specific day or month (`timeutil.py:12-17`).

---

## 6. Data

### 6.1 Warehouse catalog

Row counts are from [Q1]. "No reader" means no app, job or Redash query reads the table ([Q24]; Redash SQL [R-1..9]).

**`novamart` (12 app tables; serving `public.*`)**

| Table | Rows | Grain | Notes |
|---|---|---|---|
| users | 38,950 | user (first sighting) | Synthetic attributes; placeholder emails |
| accounts / account_map | 30 / 30 | UUID account | Batch-created 2019-12-01 |
| products | 81,018 | product | First writer wins; 1004856 is "Internal Test" (QA collision) |
| cart_items | 36,938 | cart add | Removals hard-delete |
| orders | 9,127 | checkout | Status mutates; 155 duplicate rows; `updated_at` of 5 released orders = 2026-08-13 (replay `NOW()`) |
| order_lines | 2,284 | item line since 2019-11-22 | |
| payments | 9,361 | payment event | NULL `payment_ref` before 11-22 and on gateway refunds |
| report_rows | 6,923 | local day × product | One version per day (no reruns so far) |
| report_rows_intraday | 2,358 | snapshot × product | 2 versions per day (17:00 and 22:00 UTC) |
| statements | 3 | month | Sep, Oct, Nov |
| top_products | 2,396 | day × rank | No reader |

**`novamart_analytics` (20 tables + 4 views)**

| Object | Writer | Notes |
|---|---|---|
| statement_overrides (1) | engineer backfill 11-02 | October fee fix |
| statement_corrections (1) | engineer backfill 12-02 | November delta 0.00; unused by any view |
| chargebacks (3) | engineer backfill 12-09 | Heuristic picks (§4.1.3) |
| statements_corrected (view) | engineer backfill | Statements LEFT JOIN overrides by month |
| statements_final (view) | engineer backfill | Corrected minus chargebacks by order month; **fee not adjusted** |
| refunds_unified (view) | engineer backfill 12-23 | §4.4 |
| contactable_users (view) | engineer backfill 12-04 | Empty |
| test_users (1) | engineer backfill 11-27 | 424242 |
| category_names (135) / category_name_history (6) | engineer backfills 11-30, 12-12 | History `valid_from` = 2026-08-13 (artefact) |
| blank_brand_products (5,972) | engineer backfill 10-21 | Point-in-time diagnostic snapshot, with a `suspected_cause` text |
| price_history (1,400) | catalog price feed (since 11-15) | 7 feeds × 200 items |
| product_affinity / _v2 (3,912 each) | jobs | 2,964 sentinel rows |
| model_registry (17) / model_scores (948) | model_train | Unused |
| rec_decision_log (667,850) | widget | Missing 1,340 random-arm rows |
| order_risk (1,631) | fraud_score | |
| trending_daily (2,898) | trending | |
| kpi_daily (45), daily_funnel (53), digest_log (15), price_suggestions (500), reorder_hints (200) | jobs | No reader |

**`novamart_logs`**

| Object | Contents |
|---|---|
| `db_queries` (3.6M) | Every SQL statement. `textPayload` = `"<ts> [actor] statement: <sql> -- params: <params>"`. Actors are `app`, `job`, `engineer:dev`, `engineer:maya`, `engineer-backfill:dev`, `engineer-backfill:maya` ([Q31]). The best source for "what really happened". |
| `db_queries_normalized` (view) | Parses actor, statement type and referenced tables. It maps `analytics.*` to `novamart_analytics`. |
| `app_events` (1.57M) | JSONL app events, including `duration_ms` on order callbacks. No error events are logged. |
| `job_runs` (978) | Job start/finish stats, including the `job_crashed` stderr for affinity_v2. |

### 6.2 Data-quality and gotcha register

| # | Issue | Impact | Evidence |
|---|---|---|---|
| D1 | Duplicate orders from callback retries (10-01 to 10-15) | October +$58.8k | [Q7], `b676969` |
| D2 | ~60–70% of order callbacks fail since 11-22 (DDL step, or rollback after INSERT) | Dec/late-Nov orders and revenue understated | [Q9], [Q10], `5d1300d` |
| D3 | 11-15 zero orders | November dip | [Q8] |
| D4 | report_rows 11-17 truncated at 500 rows; 11-03 DST hour missing | Report history understated | [Q11], `1233af8`, `102c9b4` |
| D5 | `EXCLUDED_SKUS` contains real products; 1004856 ID collision with QA | Report and KPI understate ~$2–3k per day; widget serves them | [Q14], [Q19] |
| D6 | Gateway refund replays | Refunds 3× | [Q6] |
| D7 | Cancellations counted as refunds | Refunds overstated | `refunds_unified` definition |
| D8 | Chargebacks are hand-picked placeholders | statements_final arbitrary | [Q31] |
| D9 | Synthetic user and product attributes (region, channel, device, age, opt-in, vendor, cost, stock, title) | Any segmentation or margin analysis on them is meaningless; model features are noise | `onboarding.py` |
| D10 | Placeholder emails | Board actives = 0, contactable = 0 | [Q21], [Q22] |
| D11 | First-writer-wins catalog | 17,442 blank brands; stale titles; wrong brand for 1004856 | [Q14], [Q23] |
| D12 | Replay timestamps (`NOW()`/`CURRENT_DATE` → 2026-08-13) | Released orders' `updated_at`; category history never effective | [Q13], [Q23] |
| D13 | `orders.product_id` = first item only | Product metrics that key on it miss appended items | `orders.py:79` |
| D14 | Rolling dashboards use `now()` | Run today, [R-6], [R-8] and [R-9] return **empty** (data ends 2019-12-31); [R-3] returns 0 anyway | Redash SQL |
| D15 | Funnel `day` label off by one; sessions exclude views | Funnel misread | `funnel.py` |
| D16 | Cart removals hard-delete | Cart history lossy | `carts.py:28` |

### 6.3 Reproducing numbers in BigQuery

- Convert local-month or local-day windows with `TIMESTAMP('YYYY-MM-DD 00:00:00','America/New_York')` ([Q26]).
- Anchor "now" at end of data, e.g. `TIMESTAMP '2020-01-01 05:00:00+00'`, when replicating Redash queries ([Q21], [Q28]).
- The warehouse is a one-shot copy. Redash reads the live serving DB, so values can differ.

---

## 7. Experimentation

### 7.1 What exists

1. **Random-arm holdout (rec widget)**, since 2019-12-06 (`df4ed85`).
   - 5% of users by hash get 5 random products from the lowest-id 500 products.
   - 14,566 logged impressions plus 1,340 unlogged ones ([Q15], [Q20]).
   - Intended purpose: unbiased training data for v4.
2. **Version flag `REC_MODEL_VERSION`** (`deploy/flags.env`). It has only ever been `2.0.0` ([Q15]). There was never an A/B between versions. v1 → v2 was a hard cutover, so v1 and v2 cannot be compared causally (different weeks, seasonality and traffic).
3. **Dynamic pricing phase 1: shadow only.** `analytics.price_suggestions` is never read ([Q24]) and is on hold per exec/legal (`cca9b0d`).
   - The ±5% rule: products above the median 14-day units get +5%. 386 of 500 have 1 unit and get −5% ([Q25]).
4. **Uncontrolled "experiments" that break time series:**
   - fraud threshold 0.90 → 0.70 → 0.85 with a manual release
   - trending window 60 → 30
   - funnel gap 30 → 120
   - reorder constant K 141.12 → 162.4 (`f85cdd2`)
   - None of these had a holdout ([Q13], [Q25]).

### 7.2 Does the recommender work? (analysis performed here)

**Rec items bought within 7 days of an impression** ([Q16]):

| Version / source | Impressions | Rec item bought ≤7 d | Any order ≤7 d |
|---|---|---|---|
| 1.0.0 affinity | 66,444 | 1.54% | 19.06% |
| 1.0.0 fallback | 326,186 | 0.72% | 17.38% |
| 2.0.0 model (affinity v2) | 52,695 | 1.43% | 12.29% |
| 2.0.0 fallback (trending) | 207,959 | 0.35% | 10.41% |
| 2.0.0 random arm | 14,566 | 0.00% | 11.08% |

**User-level holdout comparison, v2 era** ([Q17]):

| Group | Users | Converted after first exposure (status 1 or 6) | Revenue per user |
|---|---|---|---|
| Random arm | 942 | 5.31% | $26.01 |
| Treated | 19,707 | 4.96% | $23.05 |

**Interpretation**
- Affinity recs are bought more often than random ones, but co-carted items get bought regardless of the widget, and **no clicks are logged**. That means no causal attribution exists.
- The holdout shows **no lift** from the widget. The difference is small and not significant with 942 users, and if anything it points the other way.
- About 80% of treated impressions are trending fallback, which is dominated by the mislabelled SKUs 1004856 and 1002544 ([Q19]).
- Verdict: **no evidence that the ML systems add value.** v4 is a rescaling of v2 (§5.5).

### 7.3 How to run this properly next time

- Log clicks or add-to-cart from the widget with an impression id.
- Sample the random arm from the whole eligible catalog, not `ORDER BY id LIMIT 500`.
- Use a fixed outcome window and an item-level label.
- Keep logging tests in CI: the random-arm logging regression went unnoticed for two days.
- Compare arms on the same dates.
- Freeze thresholds during an evaluation (fraud), or hold out a slice.

---

## 8. Glossary

| Term | Meaning |
|---|---|
| **Statement** | Monthly gross / fee / net row in `novamart.statements`; a snapshot of `status=1` orders by order month |
| **Override / correction** | `analytics.statement_overrides` replaces a statement row (October fee fix). `statement_corrections` is an audit record and unused. |
| **Restated / final** | `analytics.statements_final` = corrected minus chargebacks |
| **Chargeback** | Row in `analytics.chargebacks`. Currently 3 heuristic placeholders. |
| **Gross / fee / net** | Order price sum / processor fee (2.9%, plus $0.30 per payment after 2019-11-20) / gross − fee |
| **Local day / month** | America/New_York calendar boundaries used by reports and statements |
| **payment_ref** | Gateway reference `PR-<session8>-<pid>`; the idempotency key since 2019-10-15 |
| **Session** | Storefront session id. Used for order merging (15 min) and affinity pairs. |
| **Order line** | Item row in `order_lines` (since 2019-11-22); `orders.price` = sum of lines |
| **Appended order** | A callback merged into a recent same-session order (`order_appended` event) |
| **Callback replayed** | Idempotent repeat of a known `payment_ref` |
| **Status 0/1/2/3/4/5/6** | Pending / paid / cancelled / refunded / legacy-cancelled / unknown / held (§3.3) |
| **Held** | Status 6, set by `fraud_score` when the score is above `FRAUD_HOLD_THRESHOLD` |
| **report_rows / intraday** | Daily per-product revenue snapshot / same-day partial snapshots |
| **EXCLUDED_SKUS** | `[1004856, 1002544]`, labelled "test/internal" but actually real products (§6.2 D5) |
| **BRAND_DENYLIST** | `lucente` (partnerships, 10-25) and `jetem` (12-15; no orders) |
| **QA user** | `424242`, session `qa-smoke`, weekly $9.99 order on 1004856. UUID `cc27b436-…` in accounts. |
| **test_users** | `analytics.test_users`, the exclusion list (424242 only) |
| **Contactable** | Opted in, valid non-example email (`analytics.contactable_users`). Empty today. |
| **Registered customer** | User with a UUID account (`accounts`/`account_map`); 30 users |
| **Active customer** | Three different definitions (§4.5) |
| **Affinity** | Co-cart pair score. `-1` = sentinel for "not enough data" (graduation gate `MIN_PAIRS=3`). |
| **Trending** | 30-day decayed order count, top 50; widget fallback |
| **Intended / effective version** | Flag value vs what was served (`fallback` when there are no scores) |
| **Random arm** | 5% hash-selected users served random products for unbiased data |
| **Model v4** | `model_train.py` output: v2 scores × constant; never served |
| **Shadow pricing** | `price_suggestions`, which is computed but never used |
| **Reorder hint** | Advisory inverse-velocity heuristic (`reorder_hints`) |
| **Digest** | Daily marketing email job gated by `ENABLE_DIGEST` |
| **trigger deploy #d2p-novamart** | Empty commits used as deploy markers (`git show --stat`) |
| **engineer-backfill** | db_queries actor for manual production writes by an engineer |
| **FAKE_NOW** | Env var that overrides job "now" for backfills and tests |

---

# Appendix

## A. Commit timeline (non-deploy commits)

All "trigger deploy #d2p-novamart" commits are empty deploy markers.

| Commit | Date | What changed (tribal meaning) |
|---|---|---|
| 2da4141 | 09-15 | Initial import. `STATUS_CANCELLED=4`, `EXCLUDED_STATUSES=[0]`, `REPORT_SCAN_CAP=500`, daily report uses 24 h UTC windows (DST bug). Statement fee = 2.9% × gross. Dashboards: best_sellers, brand_revenue, daily_kpis (no filters). |
| 83fb3ed | 10-08 | `EXCLUDED_SKUS=[1004856,1002544]` (the mislabelled pair) |
| 776d674 | 10-12 | Affinity v1 job (also creates `rec_decision_log`) |
| b676969 | 10-15 | Order callbacks idempotent by `payment_ref` (stops new duplicates only) |
| 7f24380 | 10-15 | `duration_ms` in order logs (enables [Q10]) |
| 088a372 | 10-16 | `/users/{id}/email` endpoint (mounted 10-16 to 10-26) |
| 030d841 | 10-18 | `RECONCILE_BATCH` 100 → 200 |
| ea0e97b | 10-21 | Repair blank brands on catalog events |
| 193f22d | 10-21 | `/reports/brands` (unmounted 10-26) |
| ba1fbfa | 10-25 | Hide lucente |
| f1217a8 | 10-26 | Similar widget v1.0.0. **Removed users and reports routers from app.** |
| 8f19718 | 10-28 | Cancel endpoint; `STATUS_CANCELLED` 4 → 2 |
| a92c96d | 11-02 | Statement fee = collected payment fees |
| 152a760 | 11-02 | Trending (60 days) |
| 102c9b4 | 11-05 | DST-correct local-day windows |
| 9a51155 | 11-06 | top_sellers job |
| 4dbcf7f | 11-08 | Funnel (30 min gap) |
| d213f6e | 11-09 | Price feed upserts prices |
| 388370b | 11-10 | Reconcile at 03:00 |
| fef5c96 | 11-12 | Affinity graduation gate (`-1` sentinel) |
| 795d273 | 11-15 | `price_history` writes |
| d87cb3d | 11-15 | Refund endpoint, status 3 |
| 14726e7 | 11-16 | kpi_daily |
| 11c0a42 | 11-18 | `EXCLUDED_STATUSES=[0,2,3]` |
| 1233af8 | 11-19 | Remove the 500-row scan cap |
| 12e1c68 | 11-20 | Fee + $0.30 |
| 35c581e | 11-21 | `DISCOUNT_CAP` 0.25; `rerun_kpis.py` uses legacy 0.40 |
| 5d1300d | 11-22 | order_lines, merge, **per-request DDL** |
| 894c535 | 11-24 | Shadow pricing |
| f5e3032 | 11-26 | Reorder hints (K=141.12) |
| b59f077 | 11-27 | QA exclusions (`test_users`, 424242 in dashboards) |
| b567d9d | 11-27 | `/accounts` (unmounted 12-05) |
| c19a307 | 11-28 | Email digest (read `DIGEST_ON`; cron.env set `ENABLE_DIGEST`, so it never ran) |
| 2814b3d | 11-30 | Category dashboard plus mapping |
| 4a58d17 | 12-02 | Expected fee handles the flat fee |
| 89666bf | 12-02 | Affinity v2 (December crash latent) |
| cca9b0d | 12-02 | Pricing phase 2 on hold |
| e4656fb | 12-03 | Fraud scoring, threshold 0.90 |
| e10cb0c | 12-04 | `contactable_customers` in KPI dashboard |
| c49a7bb | 12-05 | Gateway refund webhook (non-idempotent). **Dropped accounts router.** |
| 92596dc | 12-05 | order_lines-aware report and dashboards |
| 53f6f6c | 12-05 | Fraud threshold 0.70 |
| 3dbe4d7 | 12-05 | Fix December seasonal crash; stamp 2.0.1 |
| f563dea | 12-06 | Trending 30 days |
| df4ed85 | 12-06 | Version dispatch, random arm, flag 2.0.0 |
| a2e0013 | 12-08 | Intraday report; KPI dashboard uses report tables |
| cd559d3 | 12-09 | statements_final dashboard |
| 8dc520b | 12-09 | Digest reads `ENABLE_DIGEST` env (still not set in the env, so no runs) |
| d6e34c6 | 12-10 | Registered conversion (UUID-vs-int join, so it returned 0) |
| 2dde4f0 | 12-11 | Board actives query |
| 33054cd | 12-12 | Versioned taxonomy |
| 8584613 | 12-13 | Trending notes doc |
| a1946ff | 12-14 | Model v4 training |
| f915c1b | 12-14 | Funnel gap 120 |
| 1169e40 | 12-15 | Hide jetem |
| 0bd4eac | 12-16 | Digest reads cron.env file, so first send was 12-17 |
| 30e8907 | 12-17 | Refactor that dropped random-arm logging |
| adbcb7e | 12-18 | UUID string exclusion in brand dashboard |
| a00f24c | 12-19 | Restore logging; 6 h cache (caches empties) |
| 686a5d6 | 12-19 | Revenue widget (double counts, ~2.9×) |
| a9a4b0b | 12-20 | Dashboard notes doc |
| f85cdd2 | 12-21 | Reorder K=162.4 |
| b975479 | 12-21 | Registered conversion via email |
| 4396fbb | 12-22 | rec_versions.md "TBD" |
| a3bffec | 12-23 | Refunds dashboard |
| 3eced24 | 12-24 | Fix revenue widget (latest versions) |
| 2885137 | 12-26 | Affinity lineage doc |
| 8ed2971 | 12-26 | Cache epoch invalidation; don't cache empties |
| d2481be | 12-27 | Pricing status doc |
| 442b135 | 12-28 | Forecast caveats doc |
| 1cb8721 | 12-29 | Fraud threshold 0.85 (+ manual release in DB) |
| dd0c8fc | 12-29 | Metric definitions doc |
| a576d0d | 12-30 | Restatement policy doc |
| d398b0d | 01-02 | Data-access doc |
| 41e3537 | 01-03 | Dashboards moved to Redash (SQL deleted from repo) |
| 4bfcbe6 | 01-04 | crontab → Airflow DAGs |
| 5ae1182 | 01-05 | Warehouse backfill job and manifest |

## B. Key queries

The full SQL and outputs are in `queries_log.md`. Abbreviated forms:

- **Q1 Table counts.** `SELECT COUNT(*)` for every table; logs `MIN/MAX(timestamp)`.
  - orders 9,127; order_lines 2,284; payments 9,361; users 38,950; products 81,018; cart_items 36,938; accounts 30; report_rows 6,923; intraday 2,358; statements 3; top_products 2,396.
  - rec_decision_log 667,850; contactable_users 0; refunds_unified 91.
- **Q2 Statement layers.**
  - `SELECT * FROM novamart.statements`, `…statement_overrides`, `…statement_corrections`, `…chargebacks`, `…statements_corrected`, `…statements_final`.
  - Orders 46, 49, 55 have status 2, 3, 2 and `updated_at` 12-10, 12-10, 12-17.
- **Q3 Orders by local month × status.**
  - Sep: 2 → 11, 3 → 1.
  - Oct: 1 → 3,695, 2 → 43, 3 → 27.
  - Nov: 1 → 3,582.
  - Dec: 1 → 1,756, 6 → 12.
- **Q4 Revenue bridge.** Per local month: all, `status=1`, held, cancelled/refunded, `ROW_NUMBER() OVER (PARTITION BY payment_ref)` de-dup, gateway refunds, payment sums (table §4.1.2).
- **Q5 Status changes.** `SELECT status, DATE(updated_at), COUNT(*) … WHERE status<>1`. Weekly batches every Tuesday from 11-05 (6 cancels, plus 4 refunds from 11-19).
- **Q6 Gateway refunds.** `payments WHERE gross<0` joined to orders: 3 orders × 3 identical refunds (12-13, 12-20, 12-27), orders still status 1.
- **Q7 Duplicates.** Rows with `rn>1` per `payment_ref`, by month and status.
  - 130 refs and 285 orders in total.
  - Extra rows: Oct status 1 = 151 ($58,828.24); Oct status 2 = 2; Oct status 3 = 1; Sep status 2 = 1.
- **Q8 Daily orders.** `GROUP BY DATE(DATETIME(created_at,'America/New_York'))`; 11-15 missing; 11-16 = 401, 11-17 = 735; about 35 per day after 11-22.
  - App events per day for 11-09 to 11-30 (views, carts, created, appended, replayed).
- **Q9 Callback funnel** (db_queries `[app]`).
  - Count of `CREATE TABLE IF NOT EXISTS order_lines` (request started) vs `idx_payments_payment_ref` (passed the ALTER) vs `INSERT INTO orders`.
  - Nov (from 11-22): 974 / 382 / 414 new orders + 32 appended.
  - Dec: 6,142 / 2,598 / 2,261 + 197.
  - Persisted (`order_lines` by local month): Nov 323 (291 first + 32 appended); Dec 1,961 (1,768 + 193). App events agree: Dec `order_created` 1,768, `order_appended` 193.
  - Logged `INSERT INTO orders` by month: Sep 12, Oct 3,765, Nov 3,614, Dec 2,261. Persisted orders: 12, 3,765, 3,582, 1,768. So rollbacks start only after 11-22.
  - 2019-11-24 statement breakdown: 124 DDL vs 36 past the ALTER.
- **Q9b Retry test.** Inter-arrival gap after failed vs successful requests (from 11-23): quantiles [1, 79, 198, 479] s vs [1, 90, 216, 492] s. Failures are not followed by quick successes, so they are not retries.
- **Q10 Callback latency.** `AVG/MAX(duration_ms)` of `order_created`/`order_appended`: ~4 ms until 11-21, then 72–678 ms average with a ~2,000 ms max (13.7 s on 11-28).
- **Q11 Report vs orders by day.** `report_rows` units and revenue vs orders all-status, with SKU, brand and QA splits.
  - 11-03 diff 5,583.81 vs exclusions 2,597.82.
  - 11-17: 487 report units vs 735 orders, diff 80,923.42.
  - Dec 3 report includes held orders.
- **Q12 Intraday versions.** Two `created_at` per day (17:00 and 22:00 UTC) from 12-09.
- **Q13 Fraud.** Held orders joined to `order_risk`. Daily counts above 0.70 / 0.85 / 0.90.
  - Released orders 7626, 7735, 8329, 8385, 9358 have `updated_at` 2026-08-13.
  - Engineer statement: `UPDATE orders SET status = 1, updated_at = NOW() WHERE status = 6 AND price < 2600` (2019-12-29T15:00 `[engineer-backfill:maya]`).
- **Q14 Excluded SKUs.**
  - 1004856: 314 non-QA orders, $40,828.43, avg $130.03; 14 QA orders at $9.99.
  - 1002544: 139 orders, $66,690.18.
  - The insert log shows `(1004856, 'Internal Test #4856', 'qa.test', 'internal', …)` on 2019-09-25, then `(1004856, 'Samsung Smartphone #4856', 'electronics.smartphone', 'samsung', …)` on 2019-10-01, which was ignored by `ON CONFLICT DO NOTHING`.
  - Monthly `status=1` revenue: test SKUs, lucente and blank-brand by month.
- **Q14b Brands.** Lucente has 676 products and 141 orders; jetem has 5 products and 0 orders.
- **Q15 Rec decision breakdown.** `GROUP BY intended_version, effective_version, rec_source, fallback_reason, arm` (§5.5 numbers). `intended_version` ∈ {1.0.0, 2.0.0} only.
- **Q16 Rec purchase attribution.** Explode `items`, join order items by user and product within 7 days (table §7.2).
- **Q17 Holdout.** User-level conversion after first v2 exposure, by arm.
- **Q17b Random pool.** Lowest 500 ids are 1000894–1004386; 107 of them ever sold.
- **Q18 Models.** `model_registry` coefficients over 17 nights.
  - `model_scores`: 948 rows = v2 rows with score ≥ 0.
  - Top-5 lists: v2 = v4 for 449/449 base products; v1 = v2 for 392/449.
  - Score ratio v4/v2 = 0.9755 on 12-31.
  - Pair counts: 3,912 pairs, 2,964 sentinel, 449 usable base products.
- **Q19 Fallback contents.** 534,145 fallback impressions; 530,000 contain 1004856 and 235,068 contain 1002544. trending_daily on 12-31: #2 is 1004856, #3 is 1002544.
- **Q20 Random-arm logging gap.** Logged random rows per day: 12-17 = 549, 12-18 = 0, 12-19 = 407. `rec_served arm=random`: 658, 848, 822. 669,190 served vs 667,850 logged.
- **Q21 Active customers.**
  - kpi-style at 2019-12-31 11:15 UTC = 1,152, matching `kpi_daily`.
  - Board logic at 2020-01-01 05:00 UTC: 1,149 candidates → 1,148 after test_users → **0**.
  - [R-7] replica with today = 2019-12-31.
- **Q22 Emails.** `example.com` = 38,910 users; `gmail.example` = 40 (23 opted in). Digest definition: 40 recipients, 17 not opted in. New users by month. Channel split even.
- **Q23 Taxonomy.** `category_name_history.valid_from` = 2026-08-13 for 6 codes. `category_names` has 135 codes (52 map to "other"). Products: 136 categories, 33,514 blank category, 17,442 blank brand.
- **Q24 Readers.** db_queries `SELECT … FROM` each analytics table by actor.
  - App reads only `product_affinity` (until 12-06) and `product_affinity_v2`.
  - `model_scores` and `reorder_hints` had one human read each.
  - No reads at all of `price_suggestions`, `kpi_daily`, `daily_funnel`, `top_products`, `order_risk`.
- **Q25 Job runs.**
  - Per-job event counts and date ranges.
  - Statement events, including the Nov `statement_fee_mismatch` delta −170.41.
  - affinity_v2 `job_crashed` stderr (`IndexError` at `SEASONAL_FACTORS[t.month - 1]`, 12-03/04/05).
  - Digest: recipients 40; top products 1002544 (12-17/18), 1004856 (12-19 to 21), then 1004767.
  - Reconcile `flagged`: ramps 1 → 130, capped at 100 from 10-14 to 10-18.
  - Trending `window_days` 60 → 30 on 12-07; funnel `gap_min` 30 → 120 on 12-15.
  - Price suggestions by `demand_units`; reorder hints (velocity 0.0714–2.7143 maps to hints 102–51).
- **Q26 December would-be statement.** `status=1` in `[TIMESTAMP('2019-12-01','America/New_York'), TIMESTAMP('2020-01-01','America/New_York'))`.
  - Result: n = 1,756; gross 552,328.93; fee 16,600.26; formula fee 16,544.33.
  - October fee today: `status=1` = 34,983.61; all = 35,679.50.
- **Q27 Revenue widget at 2019-12-31.** Fixed version 139,598.13 vs the original `686a5d6` logic 410,387.39.
- **Q28 Brand / best-seller / category replicas** at now = 2020-01-01 05:00 UTC: apple $236.6k, samsung $127.5k, blank `''` $17.4k, internal $7.6k, …
- **Q29 Registered conversion.** 30 buyers, $18,155.71 (13 QA orders). The same via `account_map`.
- **Q30 Fee schedule.** All 6,758 pre-change payments match 2.9% exactly. Post-change: 2,528 match +$0.30, 64 match 2.9% only. The first flat-fee payment was 2019-11-20 14:27 UTC.
- **Q31 Engineer activity.** `SELECT textPayload FROM novamart_logs.db_queries WHERE REGEXP_CONTAINS(textPayload, r'^\S+ \[engineer')`: 191 rows, saved to `engineer_queries.txt`. Highlights are in Appendix E.

## C. Audit of repo docs

| Doc | Verdict |
|---|---|
| README.md | **Stale.** Trending is 30 days, not 60 (`f563dea`, [Q25]). "Serving is version 4.0.0" is false ([Q15]). The 9-feature list is false; 5 are used (`model_train.py`). |
| docs/restatement_policy.md | Numbers correct ([Q2]). It omits that chargebacks are heuristic placeholders, that the duplicates and later cancellations are not reflected, and the double-count risk for orders 46/49/55. |
| docs/metrics_definitions.md | Definitions correct. It misses that board actives and contactable both evaluate to **0** ([Q21], [Q22]). |
| docs/dashboard_notes.md | Mostly correct. "Large lucente catalog import starting 2019-10-01" overstates it: 676 products created gradually, max 49 per day ([Q14b]). It misses that excluded SKUs are not filtered in dashboards. |
| docs/affinity_lineage.md | Correct about reads ([Q24]). It **misses that `affinity.py` creates `rec_decision_log`**, so dropping the job is not "safe" without moving the DDL. |
| docs/pricing_status.md | Correct ([Q24]). |
| docs/trending_notes.md | Correct ([Q25]). |
| docs/forecast_caveats.md | Correct. Ranges have since changed (51–102 on 12-31, [Q25]). |
| docs/data-access.md | Table counts match. The warehouse dataset is `novamart_analytics`, not `analytics`. |
| docs/rec_versions.md | Empty ("TBD"). §5.5 replaces it. |

## D. Redash catalog

- 9 queries, 9 dashboards (one table widget each).
- Data source id 1, "novamart", type `pg`.
- All queries have `latest_query_data_id = null` (never executed in this Redash) and no schedule.
- All descriptions read "migrated from dashboards/*.sql". The SQL is identical to the last git version before `41e3537`.

| Id | Name | What it computes | Trust |
|---|---|---|---|
| R-1 | refunds | Monthly count and total from `refunds_unified` by event month | Low (§4.4) |
| R-2 | revenue_widget | 7-day revenue from latest report and intraday versions | OK post-`3eced24`; inherits report exclusions |
| R-3 | actives_board | Board active customers | **Returns 0** |
| R-4 | registered_conversion | Accounts beta buyers | Tautological (backfilled accounts) |
| R-5 | statements_final | Restated statements | See §4.1 caveats |
| R-6 | category_revenue | 30-day category revenue | Remap ineffective; no status filter; empty when run today |
| R-7 | daily_kpis | 14-day revenue, "orders" (= lines), actives, contactable | Contactable always 0; "orders" are lines |
| R-8 | brand_revenue | 30-day brand revenue | No status filter; "internal" brand row; UUID exclusion no-op |
| R-9 | best_sellers | 7-day top 20 by revenue | No status filter; includes "excluded" SKUs |

## E. Engineer ad-hoc activity (from `novamart_logs.db_queries`; full text in `engineer_queries.txt`)

| When | Who | What |
|---|---|---|
| 10-15 | maya | Duplicate `payment_ref` analysis, then the idempotency fix |
| 10-21 | dev | Blank-brand investigation; created `analytics.blank_brand_products`, with `suspected_cause` blaming `ON CONFLICT DO NOTHING` and the known-id cache |
| 11-02 | dev | October fee rounding analysis; created `statement_overrides` and `statements_corrected` |
| 11-05 | dev | DST: compared "correct" (`04:00 → 05:00` next day) vs "buggy" windows for 11-03 |
| 11-09 | maya | acme-supplies price-feed check |
| 11-15 | dev | Created `price_history` |
| 11-19 | dev | Report undercount analysis (Oct 5–6, Nov 16–17), including a status-4 check |
| 11-27 | dev | QA 424242 inserted into `test_users` |
| 11-30 and 12-12 | dev | Category taxonomy and history backfills (`CURRENT_DATE`-based) |
| 12-02 | dev | November flat-fee audit; `statement_corrections` (delta 0) |
| 12-04 | maya | Email-domain profiling; created `contactable_users` (excludes `*.example`, so it is empty) |
| 12-09 | dev | Booked 3 chargebacks by heuristic; created `statements_final` |
| 12-21 | maya | Registered-conversion debugging (UUID vs int) |
| 12-22 | maya | Rec decision-log and model checks |
| 12-23 | dev | Created `refunds_unified` |
| 12-29 | maya | Queried non-existent columns (`total_amount`, `fraud_score`), then released held orders under $2,600 |
| 12-30 | dev | Restatement review. Queried columns that do not exist in `statements_final` (`booked_chargebacks`, …). |

## F. Open questions and unknowns

1. Was money captured by the gateway for the ~4.2k failed December callbacks and the 11-15 outage? Gateway settlement data is not available.
2. Meaning of status 5, which `reconcile` excludes. No rows and no docs.
3. Why 1002544 was added to `EXCLUDED_SKUS`. No test traffic is visible.
4. Airflow's timezone and working-directory configuration. No Airflow access.
5. Whether the cause of the Nov 14–17 traffic spike was a promotion. No commit or log mentions one.
6. Whether Postgres has the same 2026-dated replay artefacts that the warehouse shows (Redash reads Postgres).

## G. Method and artifacts in this directory

| File | Contents |
|---|---|
| `novamart_tribal_knowledge.md` | This document |
| `queries_log.md` | Every warehouse query run, with raw output (all read-only `SELECT`/`WITH`) |
| `q.py` | Read-only query helper (REST `jobs.query` against the emulator; asserts the statement starts with SELECT/WITH) |
| `git_log_full.txt` | `git log -p --reverse` of the pinned repo |
| `engineer_queries.txt` | All 191 human-issued SQL statements from `db_queries` |
| `redash/*.json` | Read-only API dumps of Redash dashboards and queries |

- No data, Redash objects or repository content were modified. All Redash calls were HTTP GETs.
- **Disclosure:** one GET to `/api/data_sources/1/schema` made Redash enqueue a background schema-introspection job. This was a metadata read and did not modify any query, dashboard or data, but it is mentioned for transparency.
