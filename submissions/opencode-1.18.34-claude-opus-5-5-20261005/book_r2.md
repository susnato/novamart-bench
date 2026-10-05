# NovaMart: Tribal Knowledge

Run ID: `b691f094-8120-4535-ba1e-c517a47339c2`. Started 2026-10-05 18:18:54 UTC.
Sources used: the repo `novamart` pinned at `5ae1182`, BigQuery project `novamart-warehouse` (local emulator), and Redash at `localhost:5054`. All access was read-only.

## How citations work

| Tag | Meaning | Where to find it |
|---|---|---|
| `[c:abc1234]` | git commit in `novamart` | `git show abc1234` (full patch log saved at `raw/git_log_patch.txt`) |
| `[F:path:line]` | file at HEAD `5ae1182` | repo |
| `[Q:name]` | a read-only BigQuery query I ran | SQL in `queries/name.sql`, output in `queries/name.out` |
| `[T:dataset.table]` | a warehouse table or view | BigQuery |
| `[V:view]` | the definition of a warehouse view | `INFORMATION_SCHEMA.VIEWS`, saved as `queries/view_definitions_analytics.out` and `queries/view_definitions_logs.out` |
| `[L:job_runs]` / `[L:app_events]` / `[L:db_queries]` | log lines from `novamart_logs.*` | dumps saved in `queries/job_runs_all.out`, `queries/app_events_lowvol.out`, `raw/engineer_queries.txt` |
| `[R:qN name]` | Redash query N | `redash/query_N_name.sql`, plus the dashboard JSON in `redash/` |

Some dates are written as "commit time = live time". That is a finding, not an assumption (see §5.1).

---

## 1. Summary

NovaMart is a small marketplace backend: FastAPI, Postgres, and about 16 nightly batch jobs. Two engineers, Maya Iyer and Dev Kapoor, built it between Sept and Dec 2019. In Jan 2020 a "platform" migration did three things: copied the serving DB into BigQuery, moved the dashboard SQL into Redash, and rewrote the cron entries as Airflow DAGs [c:d398b0d][c:41e3537][c:4bfcbe6][c:5ae1182]. The warehouse is a frozen snapshot that ends 2019-12-31 [Q:rowcounts].

The ten things a tenured person knows:

1. **"Revenue" has at least six definitions, and none of them is clean.** The finance-sanctioned number is `analytics.statements_final` [docs/restatement_policy.md]. For Oct 2019 it shows gross 1,226,764.86 and net 1,191,085.36 [Q:fin_final]. That figure still includes:
   - 155 duplicate orders created by payment-callback replays before idempotency shipped, about $59.6k [Q:dup_refs_extra][c:b676969]
   - 70 orders cancelled or refunded after publication, $23,995.11 [Q:fin_recompute]
   - a gateway refund recorded three times [Q:gateway_refunds]

   Its "chargebacks" are a hand-picked placeholder: the engineer took the first three Oct orders over $700 [L:db_queries 2019-12-09 engineer-backfill:dev]. My best "clean" Oct gross is about **$1.147M**, against **$1.230M** published (§4.1).
2. **Statements are snapshots; the orders table is mutable.** Statuses change later (cancel = 2, refund = 3, fraud hold = 6), so re-deriving a month from `orders` never matches the published `statements` row [Q:fin_recompute][Q:status_updates].
3. **The daily report and the dashboards built on it are a different "revenue".** They:
   - exclude brands `lucente` and `jetem`
   - exclude two SKUs, one of which is a real best-seller mis-flagged as a test SKU
   - exclude the QA user
   - **include fraud-held orders**

   They are never restated when the filters change [F:novamart/jobs/daily_report.py][F:novamart/constants.py:7-19][Q:report_vs_orders].
4. **Three "active customer" numbers disagree, and the board-deck one would return 0.** Every shopper's email is a synthesized `user{id}@example.com`, and the board query filters out `example.com` and `*.example` [R:q3 actives_board][Q:email_domains][Q:board_actives_asof].
5. **Order grain changed on 2019-11-22.** Before that, one order row = one item. After, an order can have several `order_lines`; `orders.price` holds the basket total and `orders.product_id` is only the first item [c:5d1300d]. Any per-product logic that reads `orders` (top sellers, trending, reorder hints, price suggestions, fraud score, the brand API, the email digest) silently mis-attributes multi-item baskets.
6. **The recommendation "ML" does not work as advertised.**
   - Serving runs v2, a co-cart heuristic, not the trained v4 model [F:deploy/flags.env][Q:rec_log_breakdown].
   - About 80% of non-random requests fall back to a site-wide "trending" top 5 [Q:rec_log_breakdown].
   - The v4 "model" output is the v2 score times a constant (0.9755), so its ranking is identical [Q:model_vs_v2].
   - The 5% random arm shows no measurable conversion lift: 3.85% vs 3.93% 7-day conversion [Q:arm_user_conv].
7. **Fraud scoring is effectively a price threshold that mutates revenue.** It moves paid orders to status 6, which drops them out of statements. It reads `orders.price`, the merged basket total, so multi-item baskets trip it; all 9 holds/releases after 12-05 were multi-line baskets [Q:held_lines]. A threshold change (0.90 → 0.70 → 0.85) plus a manual release UPDATE re-shaped Dec revenue [c:e4656fb][c:53f6f6c][c:1cb8721][L:db_queries 2019-12-29 engineer-backfill:maya].
8. **Several committed docs and the README are partly wrong.** See §5.6 and the appendix.
   - README says trending uses 60 days and v4 is served [F:README.md].
   - The restatement doc presents `statements_final` as trustworthy.
   - The board query and `contactable_users` are effectively empty.
9. **Many batch outputs are write-only.** No logged consumer reads `kpi_daily`, `daily_funnel`, `top_products`, `price_suggestions`, `reorder_hints`, `order_risk`, `digest_log`, `model_scores` or the old `product_affinity` [Q:table_readers]. The repo's Redash queries do not read them either [redash/].
10. **The Airflow migration has unverified traps.**
    - Schedules were copied as raw clock times; crontab times were local ET, Airflow defaults to UTC.
    - The second intraday run (17:00 ET) was dropped.
    - Jobs read `deploy/*.env` relative to the working directory.
    - The backfill DAG passes no required arguments, and the backfill writes to dataset `analytics`, which does not match the actual `novamart_analytics`.

    [F:crontab.txt][F:airflow/dags/*][F:novamart/jobs/warehouse_backfill.py:60]

---

## 2. Why this project

The three goals map to three questions people keep asking, and the existing artifacts answer each one inconsistently.

- **Finance: "What was revenue in month X?"** There is an append-only `statements` table, an override layer, a chargeback layer, a refunds view, and a daily report. Each tells a different story [V:statements_corrected][V:statements_final][V:refunds_unified][T:novamart.report_rows]. The engineers themselves were confused: the 2019-12-30 queries reference non-existent columns `booked_chargebacks` and `charged_at` [L:db_queries engineer:dev 2019-12-30].
- **Leadership dashboards: "Can I trust this number?"** The nine Redash queries were migrated verbatim from `dashboards/*.sql` [R:all][Q: diff in appendix]. They use rolling `now()` windows against Postgres. They carry ad-hoc cleanup filters that differ by dashboard, and at least two return structurally wrong results: board actives = 0 and contactable customers = 0 [Q:board_actives_asof][Q:kpi_dash_customer_days].
- **ML and pipelines: "Does the recommender work, and can I safely change a job?"** The README advertises a trained v4 model behind a flag [F:README.md]. The decision log shows v4 was never served [Q:rec_log_breakdown]. The jobs have no dependencies other than clock time. Most do non-transactional DELETE-then-INSERT on autocommit connections [F:novamart/db.py:21].

This document is the context needed to answer those questions correctly and to avoid repeating the mistakes visible in the history.

---

## 3. Business understanding

### 3.1 What the business is

- **Marketplace.** It sells mostly electronics: Apple and Samsung smartphones dominate revenue [Q:dash_brand_revenue_asof][Q:dash_category_asof]. Prices arrive in the payment-gateway callback body. The catalog `list_price` is maintained separately by a vendor feed [F:novamart/routers/orders.py:17-19][F:novamart/routers/catalog.py].
- **Users and products are created "on first sight."** Product views, carts and orders bootstrap user and product rows [F:novamart/routers/catalog.py ensure_entities].
  - Attributes such as name, region, channel, device, age band and marketing opt-in are **synthesized deterministically from the id** [F:novamart/onboarding.py].
  - The email is always the placeholder `user{id}@example.com` [F:novamart/routers/catalog.py _user_row].
  - So `users.created_at` means "first seen," not "signed up." `signup_channel`, `region` and the rest are hash-derived, not real.
- **Money flow.**
  1. The gateway calls `POST /orders`.
  2. The app writes an `orders` row (status 0, then 1), an `order_lines` row (since 11-22) and a `payments` row with the processor fee.
  3. The fee is 2.9%, plus $0.30 since 2019-11-20 14:27 UTC [F:novamart/routers/orders.py][Q:fee_switch].
  4. Refunds arrive two ways:
     - v1: `POST /orders/{id}/refund` sets status 3, with no money row.
     - v2: `POST /payments/gateway_refund` inserts a negative `payments` row and leaves the order at status 1.

     [c:d87cb3d][c:c49a7bb][F:novamart/routers/payments_webhook.py]
- **Business timezone is America/New_York.** Reports and statements use local days and months [F:novamart/constants.py LOCAL_TZ][F:novamart/jobs/timeutil.py].

### 3.2 Order status codes (as actually used)

| code | meaning | set by | evidence |
|---|---|---|---|
| 0 | pending: inside the create request, before payment | `create_order` | [F:novamart/routers/orders.py]; no rows remain [Q:fin_recompute] |
| 1 | paid / complete | `create_order` | |
| 2 | cancelled (was **4** before 2019-10-28) | `/orders/{id}/cancel` | [c:8f19718]; 54 rows, all on Sept/Oct orders [Q:status_updates] |
| 3 | refunded (v1 refunds) | `/orders/{id}/refund` | [c:d87cb3d]; 28 rows [Q:status_updates] |
| 4 | legacy "cancelled" (pre-10-28) | none now | [c:2da4141] constants; 0 rows today |
| 5 | unknown; excluded only by reconcile (`status <> 5`) | none | [F:novamart/jobs/reconcile.py]; 0 rows |
| 6 | fraud hold | `fraud_score` job | [F:novamart/jobs/fraud_score.py]; 12 rows, all Dec [Q:held_orders] |

Cancellations and refunds land in **weekly Tuesday 16:00 UTC batches**, oldest order ids first (11-05, 11-12, …, 12-31). Every Sept order and 70 Oct orders were reversed this way [Q:status_updates][L:app_events order_cancelled/order_refunded]. The source of these batches is not in the repo.

### 3.3 Timeline of the business and its data (key events)

| date (UTC) | event | evidence |
|---|---|---|
| 09-15 | initial import; first jobs: reconcile, daily_report, monthly_statement | [c:2da4141] |
| 09-25 | first order: the QA smoke test, user 424242, SKU 1004856, $9.99, weekly thereafter | [Q:qa_user] |
| 10-01 | real traffic starts; `lucente` catalog appears (676 products) | [Q:daily_volume][Q:jetem] |
| 10-01 → 10-15 10:27 | gateway callback replays create **285 orders on 130 payment_refs** (155 extras) | [Q:dup_refs][Q:dup_nature] |
| 10-15 14:00 | idempotency by payment_ref | [c:b676969][L:app_events first order_callback_replayed 14:12] |
| 10-23 | 40 users' emails changed to `cust…@gmail.example`, including QA user 424242 | [L:app_events user_email_updated][Q:gmail_users] |
| 10-26 14:35 | similar-products widget v1 live; **users and reports routers unmounted by the same commit** | [c:f1217a8][Q:rec_log_breakdown] |
| 11-03 | DST fall-back; daily report for 11-03 under-counts the last hour | [c:102c9b4][Q:report_vs_orders] |
| 11-15 | **zero orders recorded** despite peak cart activity (2,136 cart adds) | [Q:daily_volume] |
| 11-16/17 | promo-like spike: 401 and 735 orders; the 11-17 daily report is truncated at 500 rows | [Q:daily_volume][L:job_runs orders_scanned=500] |
| 11-20 14:27 | flat $0.30 fee goes live | [c:12e1c68][Q:fee_switch] |
| 11-22 15:00 | multi-item orders (`order_lines`, 15-minute same-session merge) | [c:5d1300d][Q:rowcounts] |
| 11-23 onward | **orders/day step down from about 110 to about 35** while cart activity holds; unexplained | [Q:daily_volume][L:app_events order_created] |
| 12-01 | 30 registered accounts created in one batch, including the QA user's (`cc27b436…`) | [Q:accounts] |
| 12-03 | 9 order lines at exactly $2,999.99 across random brands, a price-glitch pattern, held by fraud on 12-04 | [Q:price_2999][Q:held_orders] |
| 12-05 | `accounts` router unmounted (gateway refund commit) | [c:c49a7bb] |
| 12-06 16:40 | recommender v2 plus a 5% random arm live | [c:df4ed85][Q:rec_log_breakdown] |
| 12-13/20/27 | the same 3 gateway refunds replayed weekly | [Q:gateway_refunds] |
| 12-29 15:00 | manual release of held orders under $2,600 (5 orders back to status 1) | [L:db_queries engineer-backfill:maya][Q:fraud_released] |
| 2020-01-02..05 | platform migration: BigQuery backfill, Redash, Airflow | [c:d398b0d][c:41e3537][c:4bfcbe6][c:5ae1182] |

### 3.4 Who's who

- **Maya Iyer**: app and API, accounts, refunds, recommender serving, email digest, board/KPI queries [git log authors].
- **Dev Kapoor**: batch jobs, finance statements and backfills, affinity, trending, fraud, dashboards [git log authors].
- **"Novamart Platform"**: the Jan 2020 migration commits.
- Engineers also ran ad-hoc SQL and DDL directly against prod. These show up as `[engineer:*]` and `[engineer-backfill:*]` in `db_queries`, 191 statements [Q:dbq_actors][raw/engineer_queries.txt]. **Several warehouse objects exist only because of these backfills, not code:**
  - `statement_overrides`, `statement_corrections`, `chargebacks`
  - `test_users`, `category_names`, `category_name_history`, `blank_brand_products`
  - the views `contactable_users`, `refunds_unified`, `statements_corrected`, `statements_final`

---

## 4. Metrics

### 4.1 Revenue: the definitions that exist, and how to answer "revenue for month X, and why"

| # | Definition | Source | Filters / grain | Restated? |
|---|---|---|---|---|
| R1 | **Published statement** | `novamart.statements` written by `monthly_statement` on the 1st at 06:30 ET | `orders.status=1`, order `created_at` in the ET month; gross = Σ`orders.price`; fee: formula through the Oct statement, collected fees from the Nov statement on | Never (append-only) [F:novamart/jobs/monthly_statement.py][c:a92c96d] |
| R2 | **Corrected statement** | `statements_corrected` = statements LEFT JOIN `statement_overrides` | only override today: Oct fee 35,679.64 → 35,679.50 | manual [V:statements_corrected][Q:fin_overrides] |
| R3 | **"Final" statement** | `statements_final` = R2 − Σ`chargebacks` by order's ET month | the chargebacks are 3 placeholder rows | manual [V:statements_final][Q:fin_chargebacks] |
| R4 | **Current-state recompute** | `orders` with status=1 now | changes whenever statuses change | live [Q:fin_recompute] |
| R5 | **Daily report** | `report_rows` | excludes statuses 0/2/3 (**not 6**), test_users, `EXCLUDED_SKUS`, `BRAND_DENYLIST`; item grain since 12-05 | never re-run [F:novamart/jobs/daily_report.py][Q:report_rows_monthly] |
| R6 | **Cash / payments** | `payments` by payment month | includes held orders and negative gateway refunds; not status-aware | n/a [Q:payments_monthly] |

**Monthly numbers side by side** (ET months):

| month | R1 published gross | R3 final gross | R4 status=1 now | R5 Σ report_rows | R6 payments gross (pos / neg) |
|---|---|---|---|---|---|
| 2019-09 | 2,702.00 (12 orders) | 2,702.00 | **0.00** (all 12 cancelled or refunded) | 2,702.00 | 2,702.00 |
| 2019-10 | 1,230,332.43 (3,765) | 1,226,764.86 | 1,206,337.32 (3,695) | 1,201,082.08 | 1,230,332.43 |
| 2019-11 | 1,101,397.01 (3,582) | 1,101,397.01 | 1,101,397.01 (3,582) | 966,974.33 | 1,101,397.01 |
| 2019-12 | not yet published | n/a | 552,328.93 (1,756) | 535,561.72 (to 12-30) | 592,542.22 / −1,843.59 |

Sources: [Q:fin_statements][Q:fin_final][Q:fin_recompute][Q:report_rows_monthly][Q:payments_monthly].

**October 2019 bridge, the way a tenured person explains it.** Published gross $1,230,332.43 [Q:fin_statements] is made up of:

| component | amount | what it is | evidence |
|---|---|---|---|
| still paid (status 1) and unique | 1,147,509.08 | real paid orders | derived: 1,206,337.32 − 58,828.24 |
| duplicate replay orders, still status 1 | 58,828.24 (151 rows) | the same user, product and payment_ref seconds to minutes apart; created before the idempotency fix | [Q:dup_refs_extra][Q:dup_nature][c:b676969] |
| cancelled after publication (status 2) | 10,748.42 (43) | weekly batches 11-05 → 12-31; includes 2 dup rows and chargeback orders 46 and 55 | [Q:fin_recompute][Q:status_updates] |
| refunded after publication (status 3) | 13,246.69 (27) | includes 1 dup row and chargeback order 49 | same |

Other facts about October:

- **Gateway refunds.** Three Oct-31 orders (3762, 3763, 3776, $614.53 total) were refunded via webhook 3 times each, on 12-13, 12-20 and 12-27. The orders stay status 1, so R4 still counts them [Q:gateway_refunds]. The webhook has no idempotency key: `payment_ref` is NULL for these rows [F:novamart/routers/payments_webhook.py].
- **"Chargebacks" of $3,567.57.**
  - They were inserted on 12-09 by an engineer query: the first 3 status-1 Oct orders with price over $700 and a payment, `reported_at` hard-coded to 2019-12-01 [L:db_queries 2019-12-09 engineer-backfill:dev].
  - All three orders were later cancelled or refunded (46 and 55 cancelled; 49 refunded on 12-10/12-17) [Q:fin_chargeback_orders].
  - Subtracting both the chargebacks and the cancellations double-counts.
- **Fee.** The published fee was formula-based, 2.9% × gross = 35,679.64. Collected fees were 35,679.50. That is the override, and the "fee mismatch" warning delta was 0.14 [L:app_events statement_fee_mismatch 2019-11-01][Q:fin_overrides].
- **Best estimate of clean Oct paid gross: about $1,146,894.55.** That is status=1 now, minus duplicate extras, minus one copy of the gateway refunds. Use this only with the caveats above. The finance-sanctioned answer is still R3 (`statements_final`), 1,226,764.86 gross and 1,191,085.36 net [docs/restatement_policy.md][Q:fin_final].

**November 2019.**
- R1 = R4 = 1,101,397.01 (3,582 orders). No Nov order has been reversed [Q:fin_recompute].
- Fee 32,110.92 is collected fees. The run logged a **false** mismatch of −170.41 because the expectation then ignored the $0.30 flat fee [L:app_events statement_fee_mismatch 2019-12-01][c:4a58d17].
- The "November audit correction" row in `statement_corrections` has **delta 0.00** [Q:fin_corrections].
- `FEE_CHANGE_AT` assumes the flat fee started 11-20 00:00 ET. It actually went live at 14:27 UTC, so 64 payments in between carry the old fee. Under current code the expectation would overstate by $19.20 [Q:fee_switch][Q:fee_window_gap].
- Nov contains the 11-16/17 spike ($358k) and the **11-15 zero-orders day**. Treat 11-15 as a data gap, not a real zero [Q:daily_volume].
- R5 (daily report) is $134k lower:
  - lucente and the two SKUs are excluded
  - the 11-17 report was truncated at 500 rows: −$74,995.96 [c:1233af8]
  - the 11-03 DST bug: −$2,985.99 [c:102c9b4]

  [Q:report_vs_orders]

**December 2019 (not published; the job would run 2020-01-01).** If `monthly_statement` ran on current data it would publish:
- gross 552,328.93
- fee 16,600.26
- net 535,728.67
- orders 1,756

[Q:dec_statement_sim]

That gross:
- **includes** 5 orders ($10,859.73) released from fraud hold by a manual UPDATE on 12-29 [Q:fraud_released]
- **excludes** 12 held orders ($40,213.29), 9 of them $2,999.99 glitch lines from 12-03 [Q:held_orders][Q:price_2999]
- does **not** net out the gateway refunds, because those belong to Oct orders

R6 by payment month = 590,698.63. That equals all Dec orders, including held ones, minus the 3× gateway refunds [Q:dec_statement_sim].

**Rules of thumb**
- "What did we tell the board?" Use `novamart.statements` (R1).
- "Finance's current number?" Use `statements_final` (R3) and disclose its known gaps.
- Never re-derive a published month from `orders` and expect it to match. Statuses change weekly.
- Never sum `report_rows` for finance. It is ops-filtered and never restated.
- Multiple `statements` rows for one month would duplicate through both views; they are plain LEFT JOINs [V:statements_corrected]. Today there is exactly one row per month [Q:fin_statements].

### 4.2 Fees

- Order fee = round(price × 0.029 + 0.30, 2), with the flat part only after 11-20 14:27 UTC [F:novamart/routers/orders.py:19][Q:fee_switch].
- Appended lines each get their own payment row and their own flat fee [F:novamart/routers/orders.py].
- Gateway refund rows carry fee 0. The processor fee is not reversed [F:novamart/routers/payments_webhook.py].

### 4.3 Refunds

- **`refunds_unified`** [V:refunds_unified], read by [R:q1 refunds], is the union of:
  - orders with status 2 (cancelled!) or 3, amount = `orders.price` (basket total), timestamped at `updated_at`
  - every negative `payments` row
- **Known problems.**
  - It counts cancellations as refunds.
  - It triple-counts the replayed gateway refunds: 9 rows, $1,843.59, where $614.53 is real [Q:gateway_refunds].
  - It buckets by when the status changed, not by the order month.
  - It would double-count an order that is both status 3 and has a negative payment.
  - Re-expressed result [Q:dash_refunds]: Nov 32 rows / $9,691.77; Dec 59 rows / $18,848.93.
- **None of these refunds flow into published statements.** Statements use `status=1` at run time only.

### 4.4 Orders and units

| metric | definition | evidence |
|---|---|---|
| statement `orders_count` | count of `orders` rows, status=1; includes Oct dups | [F:novamart/jobs/monthly_statement.py] |
| KPI dashboard "orders" | **Σ units** (item lines) from the daily report, not orders | [R:q7 daily_kpis] |
| `top_products.units` | count of `orders` rows by `orders.product_id` (first item only), status=1 | [F:novamart/jobs/top_sellers.py] |
| best-sellers dashboard "units" | item lines (`order_lines`, with the legacy `orders` fallback), any status | [R:q9 best_sellers] |

Daily report "units" changed meaning on 12-05:
- From 11-22 to 12-04 the report counted orders, while revenue = basket total. Units are therefore lower than the item count but revenue is equal. Example: 11-24 shows 27 vs 32 units, same $6,651.97 [Q:report_vs_orders].
- From 12-05 it counts lines [c:92596dc].

### 4.5 Customers

| metric | definition | value example | evidence |
|---|---|---|---|
| **Users / "signups"** | rows in `users`, created on first sight (view/cart/order) | Oct 15,045; Nov 11,302; Dec 12,529 new | [Q:users_monthly][F:novamart/routers/catalog.py] |
| **Registered accounts** | `accounts` (UUID), linked by `account_map`; beta | 30 rows, all created 2019-12-01 16:30, including QA | [Q:accounts] |
| **kpi_daily.active_customers** | distinct buyers, status=1, trailing 30×24h from run time; no exclusions; `day` = run date (UTC) | 1,152 on 2019-12-31 | [F:novamart/jobs/kpi_daily.py][Q:kpi_daily_table][Q:kpi_recompute] |
| **KPI dashboard active_customers** | distinct buyers **per ET calendar day**, any status, excluding user 424242 and lucente/jetem (first product only) | 54 on 2019-12-31 | [R:q7 daily_kpis][Q:kpi_dash_customer_days] |
| **Board actives** | trailing 30 days, status ∉ {0,2,3} (so held orders count), minus test_users, minus "fake" email domains | **0**: every user is `@example.com` or `@gmail.example`; 1,156 without the email filter | [R:q3 actives_board][Q:email_domains][Q:board_actives_asof][Q:kpi_recompute] |
| **Contactable customers** | `analytics.contactable_users`: opt-in, valid email, not example.* | **0 users**, so the KPI dashboard column is always 0 | [V:contactable_users][Q:rowcounts_analytics] |
| **Digest recipients** | `users.email NOT LIKE '%@example.com'` | **40**: the gmail.example users, including QA 424242 and 17 users who did **not** opt in | [F:novamart/jobs/email_digest.py:51][Q:gmail_users][L:job_runs digest_sent] |
| **Registered conversion** | accounts → users by email → paid orders | 30 buyers / $18,155.71, including QA user 424242 | [R:q4 registered_conversion][Q:registered_conv] |
| **Funnel users_active / sessions** | cart and order events in the 24h before 06:20 ET; gap 30 → 120 min on 12-14; `day` = run date | e.g. 12-16: 416 sessions / 367 users | [F:novamart/jobs/funnel.py][c:f915c1b][Q:funnel_rows] |

Why `kpi_daily` fell from about 2,250 (mid-Nov) to about 1,000 (late Dec), with cliffs on 12-17 and 12-18:
- the 11-16/17 spike rolled out of the 30-day window
- the post-11-22 order step-down

[L:job_runs kpi_rollup][Q:daily_volume]

### 4.6 Product metrics

- **Best sellers** (Redash q9):
  - rolling 7×24h from `now()`; item grain; **no status filter**, so held, cancelled and refunded items count
  - excludes 424242 and lucente/jetem
  - ranked by **revenue**
  - Example: product 1005284 ranks #3 on 2 units that are both fraud-held [Q:dash_best_sellers_asof][docs/dashboard_notes.md]
- **Top sellers job** (`top_products`): yesterday, status=1, order grain by first product, ranked by units. It has no logged consumer [F:novamart/jobs/top_sellers.py][Q:table_readers].
- **Brand revenue** (q8): rolling 30 days, item grain, any status.
  - It shows a blank brand row ('' = 17,442 blank-brand products) and an **"internal"** brand, which is SKU 1004856's real sales [Q:dash_brand_revenue_asof][Q:blank_brand_now].
  - Its UUID exclusion `cc27b436…` can never match. `orders.user_id` is numeric; the UUID is the QA user's *account* id [Q:accounts][c:adbcb7e].
- **Category revenue** (q6): maps `products.category` to a display group through `category_names`, with valid-from dates.
  - The Dec-12 "lighting" and "entertainment" regrouping rows in `category_name_history` have `valid_from = 2026-08-13` (the date the backfill's CURRENT_DATE was evaluated), so they **never apply to 2019 orders** [Q:cat_history][L:db_queries 2019-12-12 engineer-backfill:dev].
  - About 16% of 30-day revenue is "other", mostly blank categories [Q:dash_category_asof].
- **Trending** (`trending_daily`): status=1, order grain, 60-day window through 12-06 and 30-day from 12-07, min 5 units, exp decay, top 50 [c:f563dea][L:job_runs trending_refresh window_days].
- **Brand report API** `/reports/brands`: uses `orders.price` per first product. It is **not mounted in the app** since 10-26 [F:novamart/app.py:7][c:f1217a8].

### 4.7 Exclusion lists: what is hidden where (high-impact)

| filter | daily/intraday report | statements | Redash dashboards | widget / random arm | trending fallback | digest |
|---|---|---|---|---|---|---|
| QA user 424242 | yes (via `test_users`, since 11-27) | **no** ($39.96–49.95/mo) | yes (hard-coded) | no | no | **no** (a recipient) |
| SKU **1004856** ("Internal Test", brand internal) | yes | no | no | yes | **no** (ranked #1–2) | no |
| SKU **1002544** (Apple smartphone) | yes | no | no | yes | **no** | no |
| brand lucente | yes since 10-25 | no | yes since 12-15 | no | no | no |
| brand jetem | yes since 12-15 | no | yes | no | no | no |
| status 6 (fraud hold) | **included** | excluded | **included** (no status filter) | n/a | excluded | excluded |

Sources: [F:novamart/constants.py:7-19][c:83fb3ed][c:ba1fbfa][c:1169e40][c:b59f077][R:q6-q9][Q:excl_breakdown][Q:trending_top][Q:fallback_items][Q:excluded_skus][Q:excluded_sku_prices].

**SKU 1004856 is not a test SKU in practice.** The QA smoke test created the product row first (category `qa.test`, brand `internal`, list price $9.99). Since then **314 real orders from 244 buyers** have bought it at about $127, about $40k [Q:excluded_skus][Q:excluded_sku_prices].

**SKU 1002544 is a real Apple smartphone** with $66.7k across 139 orders [Q:excluded_skus].

Excluding both drops $31–41k a month of paid sales from the daily report and the KPI dashboard (Oct $34.6k, Nov $40.6k, Dec $31.4k) [Q:excl_breakdown]. Jetem has 5 products and 0 orders, so hiding it changes nothing today [Q:jetem].

### 4.8 When a dashboard number should NOT be trusted at face value

| dashboard | why it can be wrong | evidence |
|---|---|---|
| all nine Redash queries | run against Postgres with `now()` windows, so on the frozen 2019 data they return empty or near-empty sets today; no cached results, schedules or widgets exist | [redash/query_*.json latest_query_data_id=null][redash/dashboard_*.json widgets=[]][redash/data_sources.json pg] |
| daily_kpis | revenue = daily report: hides 2 real SKUs, lucente/jetem, **includes fraud-held orders** (12-03 revenue $39k vs a typical $14k is the $2,999.99 glitch orders); "orders" = units; contactable always 0; active = per-day, any status; 11-15 missing; 11-17 truncated; 11-03 short | [R:q7][Q:report_vs_orders][Q:held_orders] |
| revenue_widget | after the 12-24 fix, latest daily snapshot plus today's latest intraday. Before the fix it summed every snapshot version (e.g. **$410k vs the correct $139.6k** for the 7 days to 12-31). After Airflow, "today" would come from a 07:00 ET run (UTC schedule, 17:00 run dropped) | [c:3eced24][R:q2][Q:intraday_versions][F:airflow/dags/intraday_report_dag.py] |
| actives_board | returns 0 because of placeholder emails | [Q:board_actives_asof] |
| best_sellers / brand / category | no status filter; blank and "internal" brands; category regrouping never effective; rolling windows, not calendar | §4.6 |
| refunds | cancellations counted as refunds; gateway replays triple-counted | §4.3 |
| statements_final | dups, post-publication reversals and gateway refunds ignored; placeholder chargebacks | §4.1 |
| registered_conversion | includes the QA account; joins on email (breaks if an email changes; `account_map` is the real link) | [Q:accounts] |

---

## 5. System

### 5.1 Components and deploy semantics

- **App (FastAPI).** Mounted routers: `catalog`, `carts`, `orders`, `similar`, `payments_webhook` [F:novamart/app.py:7,19-23].
  - **Unmounted** routers exist in code: `users` (dropped 10-26 by [c:f1217a8]), `reports` (dropped 10-26), `accounts` (dropped 12-05 by [c:c49a7bb]).
  - Log evidence: `user_email_updated` appears only on 10-23 and `account_created` only on 12-01 [L:app_events].
- **Code goes live at commit time.** The "trigger deploy #d2p-novamart" commits are empty, with no file changes [raw/git_log_stat.txt]. Effects appear within minutes of the functional commit:
  - flat fee: commit 14:25, first fee 14:27 [Q:fee_switch]
  - v2 serving: commit 16:40, first row 16:40:11 [Q:rec_log_breakdown]
  - random-arm logging gap: starts at commit 30e8907 (12-17 16:50), ends at a00f24c (12-19 14:55) [Q:rec_daily]
- **Jobs run from the repo HEAD** at `/srv/novamart/repo`, as the stack trace in [L:job_runs job_crashed affinity_v2] shows. A commit is picked up on the next scheduled run (e.g. `fraud_score` committed 12-03 15:20, first run 12-04 10:45) [L:job_runs].
- **Logging.** Every SQL statement goes to `db_queries.log` and from there to `novamart_logs.db_queries`. App events go to `app_events`; job events to `job_runs` [F:novamart/logutil.py][F:novamart/db.py]. Redash queries are **not** in `db_queries` [Q:dbq_actors].
- **Flags**, both read from **relative paths**, so they depend on the working directory:
  - `deploy/flags.env` → `REC_MODEL_VERSION`, read on every request [F:novamart/routers/similar.py:39]
  - `deploy/cron.env` → `ENABLE_DIGEST` [F:novamart/jobs/email_digest.py:15]

### 5.2 Order write path (gotchas)

- **Idempotency** [c:b676969][c:5d1300d]:
  - Advisory locks on session and on payment_ref.
  - Lookup by `orders.payment_ref` or `order_lines.payment_ref`.
  - Unique indexes: `order_lines(payment_ref)` and `payments(payment_ref) WHERE NOT NULL`.
- **Same-session merge.** A callback from the same user and session within 15 minutes of the last line is appended to the existing order. Its `orders.price` is incremented and the order is forced to status=1 [F:novamart/routers/orders.py:71-79].
- **Consistency.** `orders.price = Σ order_lines.price` for all 2,059 line-bearing orders. 173 orders are multi-line, with 225 appended lines [Q:orders_lines_consistency].
- **Legacy orders** (before 11-22 15:18) have no `order_lines`. Dashboards and the daily report use a "lines else orders" fallback [c:92596dc].
- **Schema is created lazily.** `order_lines`, `payments.payment_ref` and `accounts` are created at request time, not in `schema.sql` [F:novamart/routers/orders.py][F:schema.sql].

### 5.3 Scheduled jobs: what each produces, who reads it, what breaks

Crontab times were **local ET**: `daily_report` ran at 10:00Z under EDT and at 11:00Z after DST [L:job_runs]. The Airflow DAGs copy the same clock numbers with no timezone [F:airflow/dags/*]. All jobs connect with autocommit [F:novamart/db.py:21], so DELETE-then-INSERT refreshes are visible half-done to readers.

| job (ET) | writes | logic summary | consumers | failure / rerun behavior |
|---|---|---|---|---|
| reconcile 03:00 | app log warnings only | payment_refs on more than 1 order, LIMIT 200 | humans (none act) | flags the same 130 Oct dup refs nightly, 10,766 warnings, never resolved [L:app_events duplicate_payment_ref] |
| affinity 03:30 | `analytics.product_affinity` (full rebuild) | co-cart pairs, 30 days, decay 0.05, pairs < 3 → −1 sentinel | **none since 12-06 16:39** | safe to retire [Q:table_readers][docs/affinity_lineage.md] |
| affinity_v2 03:45 | `product_affinity_v2` (full rebuild), rows stamped 2.0.1 | (pairs + 3·converted) × decay × 1.15 same-category × 0.7 price-jump × seasonal factor (Jan–Nov only; Dec → 1.0 after the crash fix) | **widget**, model_train | crashed 12-03..05 on the December index [L:job_runs job_crashed][c:3dbe4d7]; partial table visible mid-refresh; failure leaves stale scores |
| model_train 04:15 | `model_registry` (append), `model_scores` (rebuild) | logistic fit on random-arm logs → v2 score × (1 + 0.1·w) | none (4.0.0 never served) | none for serving |
| price_suggest 04:45 | `price_suggestions` (rebuild, top 500) | ±5% around `list_price` vs median units (median = 1, so 386 of 500 get −5%) | **none** (shadow; phase 2 on hold) | none [Q:price_sugg][c:cca9b0d] |
| trending 05:15 | `trending_daily` (per-day delete + insert) | see §4.6 | **widget fallback** (about 80% of non-random serves) | stale list if it fails (fallback uses MAX(day)) |
| fraud_score 05:45 | `order_risk` (append), **UPDATE orders → status 6** | core = min(price/3000, 1), × (1 + 0.15 new account + 0.15 velocity); hold if above the threshold | statements (indirectly) | a rerun re-scores the last 24h of status-1 orders, appends duplicate `order_risk` rows, and can hold more orders if the threshold changed. Holds are never reviewed automatically |
| daily_report 06:00 | `report_rows` (append) | yesterday ET; see R5 | KPI dashboard, revenue widget | a missed day leaves a gap; a rerun appends a new version (dashboards take the latest `created_at`); no date argument (needs `FAKE_NOW`) [F:novamart/jobs/timeutil.py] |
| kpi_daily 06:15 | `kpi_daily` (append) | §4.5 | none | a rerun duplicates the day row |
| funnel 06:20 | `daily_funnel` (append) | §4.5 | none | a rerun duplicates |
| monthly_statement 06:30 on the 1st | `statements` (append) | §4.1 | finance, both views | a rerun appends a 2nd row for the month, which duplicates through the views; it always computes **last month relative to now** |
| top_sellers 06:45 | `top_products` (append) | §4.6 | none | a rerun duplicates |
| reorder_forecast 06:50 | `reorder_hints` (rebuild, 200) | BASE + K/(velocity + C); K 141.12 → 162.4 on 12-21; **a lower velocity gives a bigger hint** | none (advisory) | none [c:f85cdd2][Q:reorder][docs/forecast_caveats.md] |
| email_digest 07:15 | `digest_log` (append) | top paid product in 7 days (order grain) to non-example.com users | none | silently disabled until 12-16 (flag not read) [c:8dc520b][c:0bd4eac][L:job_runs first digest_sent 12-17]; promoted SKUs 1002544/1004856 |
| intraday_report 12:00 and 17:00 | `report_rows_intraday` (append) | today so far, same filters as the daily report | KPI dashboard, widget | **the Airflow DAG keeps only 12:00** [F:airflow/dags/intraday_report_dag.py] |
| warehouse_backfill (manual) | BigQuery | gcloud export → bq load | n/a | the DAG passes no `--project/--instance/--staging`, so it fails; it maps `analytics.*` to dataset `analytics`, not `novamart_analytics` [F:novamart/jobs/warehouse_backfill.py:60][F:airflow/dags/warehouse_backfill_dag.py] |

Implicit dependencies exist only through clock time. Nothing in the DAGs enforces them [F:airflow/dags/*]:
- model_train needs affinity_v2
- the widget needs affinity_v2 and trending
- the KPI dashboard needs daily_report and intraday_report

**Ops script trap.** `scripts/rerun_kpis.py` calls `apply_discounts(rows)` without a cap, so it uses the **legacy 40%** cap instead of the finance-approved `DISCOUNT_CAP = 0.25`. It also applies the cap as a flat haircut to every row [F:scripts/rerun_kpis.py][F:novamart/jobs/discounts.py:4][F:novamart/constants.py:35][c:35c581e].

**CI** only exercises one order and three jobs (reconcile, daily_report, monthly_statement) [F:ci/run_ci.py]. None of the jobs added after September is tested.

### 5.4 Recommendation system (similar-products widget)

**Request path** [F:novamart/routers/similar.py]:

1. Read `REC_MODEL_VERSION` from `deploy/flags.env`. HEAD value: **2.0.0** [F:deploy/flags.env].
2. Random arm: if `sha256(uid)[:8] % 20 == 0` (about 5% of users; 4.6% observed [Q:random_arm_users]), shuffle the **500 lowest product ids** (1000894–1004386, not the 81k catalog) [Q:random_pool]. Return 5 and log `arm='random'`.
3. Otherwise read `product_affinity_v2` (for 2.0.0) or `model_scores` (any other version), at the latest `updated_at`, score ≥ 0, top 5. Use the in-process cache (6h TTL, invalidated on `MAX(updated_at)` change since 12-26).
4. If empty, fall back to the trending top 5 from `MAX(day)` (all users see the same list). This list does **not** filter `EXCLUDED_SKUS` [Q:fallback_items].
5. Log to `analytics.rec_decision_log`: ts, user, base product, items, intended version, effective version, source, reason, arm.

**Version history** (docs/rec_versions.md is just "TBD"):

| version | period | what | evidence |
|---|---|---|---|
| 1.0.0 | 10-26 14:35 → 12-06 16:39 | `product_affinity` (v1), fallback = 7-day best sellers; **83% of serves were fallback** (326,186 vs 66,444) | [c:f1217a8][Q:rec_log_breakdown] |
| 2.0.0 (serving) / 2.0.1 (rows) | 12-06 16:40 → now | `product_affinity_v2`. The job was written to stamp 2.0.0 but crashed 12-03..05; the fix bumped it to 2.0.1 before the first successful run on 12-06, so every row says 2.0.1 | [c:89666bf][c:3dbe4d7][L:job_runs][Q:v2_scores] |
| (3.x) | never existed | | |
| 4.0.0 | trained nightly since 12-15 | `model_scores`; **never served** (no log row has intended 4.0.0); README claims otherwise | [c:a1946ff][Q:rec_log_breakdown][F:README.md] |

**Does it work? No.**
- **Coverage.** Since v2, about 80% of non-random serves are fallback: 182,868 `no_scores` plus 25,091 "cache" fallbacks, out of 260,654. The latter came from the 12-19..12-26 bug that cached empty lists. Only 449 of 1,476 base products have any graduated pair [Q:rec_log_breakdown][Q:v2_scores][c:8ed2971].
- **v4 is cosmetic.**
  - Features in code: n_items (constant 5 in the random arm), base price, base popularity, account age, organic flag. The README lists 9 features [F:novamart/jobs/model_train.py:49-57][F:README.md].
  - The label is "the user placed *any* paid order *any time* after the serve." There is no click or attribution [F:novamart/jobs/model_train.py:33].
  - The output only rescales v2 by `1 + 0.1·coef[n_items]`; it is 0.9755 × v2 for every pair [Q:model_vs_v2].
  - Coefficients flip sign day to day [Q:model_registry].
  - Training rows were flat 12-18→12-19 (5,798) because of the random-arm logging gap [L:job_runs model_trained][Q:rec_daily].
- **Online evidence.** The random arm is a valid user-level holdout. 7-day post-first-serve conversion: random 26/675 = 3.85% vs exploit 571/14,529 = 3.93%, which is not distinguishable [Q:arm_user_conv]. Conclusion: no evidence the widget lifts conversion.
- **Data quirks.**
  - v1 and v2 compute pairs from `cart_items` with a self-join, so repeated cart adds inflate pairs.
  - v2's "converted" check is unbounded in time and is per user and product, not per pair [F:novamart/jobs/affinity_v2.py].
  - `list_price` drives v2 price ratios and the v4 features. The vendor feed raises the same products **+4% every week** and writes 33 zero prices [Q:price_history_all][Q:zero_price].

### 5.5 Fraud system

- **Score** = min(price/3000, 1) × (1 + 0.15 if the account is under 7 days old + 0.15 if 3+ orders in 24h), capped at 1 [F:novamart/jobs/fraud_score.py].
  - With threshold 0.85, any order above $2,550 is held regardless of user signals.
  - "price" is the **merged basket total**: all 9 orders held or released after 12-05 were multi-line baskets (2–6 lines each) [Q:held_lines].
- **Threshold history**:
  - 0.90 (12-03, run 12-04: 8 held) [c:e4656fb][L:job_runs]
  - 0.70 (12-05) [c:53f6f6c]
  - 0.85 (12-29) [c:1cb8721]
- **The 12-29 release.** The commit message says "release held orders under $2600," but the code diff only changes the constant. The release was a manual `UPDATE orders SET status = 1, updated_at = NOW() WHERE status = 6 AND price < 2600` [L:db_queries 2019-12-29 engineer-backfill:maya].
  - It released orders 7626, 7735, 8329, 8385 and 9358.
  - In the warehouse their `updated_at` reads **2026-08-13** [Q:fraud_released].
- 12 orders remain held ($40,213.29). Nothing ever reviews or releases holds [Q:held_orders].

### 5.6 Data-access surfaces

- **Serving Postgres** (`novamart-prod-replica`) is what Redash queries: data source `pg`, host `estate-pg` [redash/data_sources.json][docs/data-access.md].
- **BigQuery** `novamart-warehouse` is a one-time copy [c:5ae1182]. Datasets:
  - `novamart` (12 tables)
  - `novamart_analytics` (20 tables + 4 views)
  - `novamart_logs` (`app_events`, `db_queries`, `job_runs`, view `db_queries_normalized`)

  [Q:rowcounts][Q:rowcounts_analytics]
- docs/data-access.md says the dataset is "`analytics`". The actual name is `novamart_analytics` [docs/data-access.md].

---

## 6. Data

### 6.1 Core tables (warehouse `novamart.*`)

| table | rows | span | grain / notes |
|---|---|---|---|
| orders | 9,127 | 09-25 → 12-31 16:51Z | one row per order (per item before 11-22); mutable status / updated_at / price; `product_id` = first item |
| order_lines | 2,284 | 11-22 15:18 → | one row per item; `payment_ref` unique |
| payments | 9,361 | | one per callback (per line); negative rows = gateway refunds; `payment_ref` NULL before 11-22 and for refunds |
| users | 38,950 | | first-seen shoppers; synthetic attributes; placeholder emails |
| products | 81,018 | | first-seen; 17,442 blank brand, 33,514 blank category, 907 zero list price |
| cart_items | 36,938 | | cart events; `session` text |
| accounts / account_map | 30 / 30 | 12-01 | registered beta |
| report_rows | 6,923 | report dates 09-25 → 12-30 | one row per date and product per run (append) |
| report_rows_intraday | 2,358 | 12-08 → 12-31 | snapshot versions (2 per day) |
| statements | 3 | 2019-09..11 | append-only published statements |
| top_products | 2,396 | 11-06 → 12-30 | append |

Sources: [Q:rowcounts][Q:blank_brand_now][Q:zero_price][Q:intraday_versions].

Orders stop at 16:51Z on 12-31 while users and carts run until about 23:45Z [Q:rowcounts]. The last intraday versions for 12-31 are identical [Q:intraday_versions].

### 6.2 Analytics tables and views (`novamart_analytics.*`)

Written by code:
- `product_affinity`, `product_affinity_v2`, `model_scores`, `model_registry`, `rec_decision_log` (667,850 rows)
- `trending_daily`, `price_suggestions`, `reorder_hints`, `order_risk`
- `kpi_daily`, `daily_funnel`, `digest_log`, `price_history` (only since 11-18; 200 rows a week)

[Q:rowcounts_analytics]

Written **only by manual engineer backfills** [raw/engineer_queries.txt]:
- `statement_overrides` (Oct fee override, 11-02)
- `statement_corrections` (Nov delta 0, 12-02)
- `chargebacks` (3 placeholder rows, 12-09)
- `test_users` (just 424242, 11-27)
- `category_names` (135 codes, 11-30 + 12-12) and `category_name_history` (6 rows, 12-12; valid_from shows 2026-08-13)
- `blank_brand_products` (snapshot 10-21; `captured_at` shows 2026-08-13)
- views: `statements_corrected` (11-02 / 12-09), `contactable_users` (12-04), `statements_final` (12-09), `refunds_unified` (12-23)

**Warehouse artifact.** Values that backfills wrote with `NOW()` or `CURRENT_DATE` carry **2026-08-13** in BigQuery: `category_name_history.valid_from`, `blank_brand_products.captured_at`, and `orders.updated_at` for the 5 released orders [Q:cat_history][Q:blank_brand_snapshot][Q:fraud_released]. Use the `db_queries` timestamp of the backfill as the real date.

### 6.3 Logs

- **`novamart_logs.job_runs`** (978 rows): one line per job event. `jsonPayload` holds job, event and stats. Crashes appear with `service:"ops"` and stderr [Q:job_runs_summary].
- **`novamart_logs.app_events`** (1.57M rows): `jsonPayload.event` ∈ {product_viewed, rec_served, cart_item_added, order_created, order_appended, order_callback_replayed, order_cancelled, order_refunded, gateway_refund, duplicate_payment_ref, statement_fee_mismatch, user_email_updated, account_created, price_feed_received} [Q:app_events_summary].
  - `rec_served` (669,190) exceeds decision-log rows (667,850) by 1,340: the random-arm serves left unlogged during the 12-17..12-19 gap.
- **`novamart_logs.db_queries`** (3.6M rows): `textPayload = "<ts> [actor] statement: <sql> -- params: …"`. Actors are app, job, engineer:dev, engineer:maya, engineer-backfill:dev and engineer-backfill:maya [Q:dbq_actors].
  - This is the **only** record of manual prod changes.
  - The view `db_queries_normalized` reshapes it like INFORMATION_SCHEMA.JOBS and maps `analytics.` to `novamart_analytics` [V:db_queries_normalized].
- **Practical tip.** On the emulator, `app_events` filters on `JSON_VALUE` are fast when written as `NOT IN (...)` over event names. Some patterns (ORDER BY on JSON, scalar subqueries with cross joins) can stall it for over 10 minutes [Q:fee_mismatch timing][Q:app_events_lowvol].

### 6.4 Data quality issues (summary)

1. Oct duplicate orders, 155 extras [Q:dup_refs_extra].
2. 11-15 no orders; step change in orders on 11-22 [Q:daily_volume].
3. Placeholder emails and synthetic user attributes, so email- and attribute-based segmentation is meaningless [F:novamart/onboarding.py][Q:email_domains].
4. Blank brand and category for a large share of products. The brand-repair path only fills a blank brand when an event carries a brand [c:ea0e97b][Q:blank_brand_now][Q:blank_brand_snapshot].
5. Vendor feed list prices +4% a week, plus zero prices [Q:price_history_all].
6. The QA user lives in the prod tables, holds a registered account and a gmail.example email [Q:qa_user][Q:accounts].
7. Gateway refunds are non-idempotent [Q:gateway_refunds].
8. `report_rows` history mixes filter definitions over time, with no restatement [Q:report_vs_orders].

---

## 7. Experimentation

- **There is no A/B framework.** The only randomization is the recommender's **5% random arm**: user-level, deterministic by sha256(uid), live since 12-06 16:40 [c:df4ed85].
  - It was designed as unbiased *training* data, not for evaluation.
  - Used as a holdout, it shows **no conversion lift** [Q:arm_user_conv].
  - Caveats: the "random" pool is only the 500 lowest product ids [Q:random_pool]; logging was lost 12-17 16:50 → 12-19 14:55 [Q:rec_daily]; there are no impression or click events, only a proxy label (any later order).
- **Shadow experiment.** Dynamic pricing phase 1 writes `price_suggestions` nightly. Phase 2 (serving) has been on hold since 12-02 per exec/legal, and nothing reads the table [c:894c535][c:cca9b0d][Q:table_readers][docs/pricing_status.md].
- **Parameter changes shipped without measurement** (do not read before/after deltas as experiment results):
  - trending window 60 → 30 [c:f563dea]
  - funnel session gap 30 → 120 min (12-14; the sessions jump on 12-16 coincides with a real traffic rise) [c:f915c1b][Q:daily_volume]
  - fraud threshold 0.90 → 0.70 → 0.85 [§5.5]
  - reorder K refit [c:f85cdd2]
  - v2 seasonal factors [c:89666bf]
- **Flags as experiment switches.**
  - `REC_MODEL_VERSION` (aliases 2/v2/4/v4/model4) is read per request from a relative path [F:novamart/routers/similar.py].
  - Setting `4.0.0` would serve `model_scores`, which are v2 scores times a constant, so customers would see the same ranking; it is only a relabel.
  - `ENABLE_DIGEST` is read from env, then `DIGEST_ON`, then `deploy/cron.env` [F:novamart/jobs/email_digest.py].
- **How to run a real experiment here.**
  1. Reuse `in_random_arm` hashing with a salt.
  2. Log the arm on every serve.
  3. Add impression and click events to `app_events`.
  4. Attribute orders to recommended items within a window.
  5. Exclude QA user 424242.
  6. Pre-register the window. ET days; watch the 11-15 gap and the 11-22 step change.

---

## 8. Glossary

| term | meaning |
|---|---|
| **status 0/1/2/3/6** | pending / paid / cancelled / refunded / fraud-held (4 = legacy cancelled, 5 = never used) [§3.2] |
| **payment_ref** | gateway transaction id. Idempotency key since 10-15 on orders, and since 11-22 on order_lines and payments |
| **order_lines / legacy orders** | item rows since 11-22. "Legacy" = orders without lines, where one order = one item |
| **append (order_appended)** | a same-session callback within 15 minutes merged into an existing order |
| **callback replay** | a duplicate gateway callback. Before 10-15 it created a duplicate order; after, it logs `order_callback_replayed` |
| **QA user 424242** | weekly smoke-test shopper. In `analytics.test_users`; its account UUID is `cc27b436-…` |
| **EXCLUDED_SKUS** | `[1004856, 1002544]`, hidden from the daily report and widget. Both are actually real sellers [§4.7] |
| **BRAND_DENYLIST** | `lucente` (partnerships, 10-25) and `jetem` (12-15), hidden from reports and dashboards |
| **report_rows / intraday** | daily and partial-day per-product snapshots (append-only versions; read the latest `created_at`) |
| **statements / overrides / corrections / chargebacks** | published monthly snapshot / replacement values / audit deltas / booked chargeback amounts |
| **statements_corrected / statements_final** | statements + overrides / corrected − chargebacks (finance's "current" number) |
| **refunds_unified** | a view of cancels + refunds + negative payments |
| **contactable_users** | opted-in users with a real-looking email (currently none) |
| **active customers** | three definitions: kpi_daily (30d, status 1), KPI dashboard (per day, any status), board (30d, cleaned, returns 0) |
| **affinity v1 / v2** | co-cart pair scores; v2 adds conversion, category and price weighting plus seasonality |
| **sentinel −1 / graduation gate** | pairs seen fewer than 3 times get score −1 ("not enough data"); serving filters score ≥ 0 |
| **intended / effective version** | the flag value vs what actually served (`fallback` when no scores) |
| **random arm** | about 5% of users who get random items from the 500 lowest product ids |
| **fallback** | trending top 5 (v2) or 7-day best sellers (v1) |
| **model 4.0.0** | the nightly logistic "model". Its scores are 0.9755 × v2 and it has never been served |
| **order_risk / hold** | fraud score rows / status 6 |
| **shadow pricing** | `price_suggestions`, not served |
| **reorder hints** | advisory inverse-velocity heuristic, not for finance |
| **ET / local day** | America/New_York business day; jobs compute UTC windows from local midnights |
| **trigger deploy commit** | empty commit with no functional meaning (code is live at commit time) |
| **engineer-backfill** | manual SQL against prod, visible only in `db_queries` |

---

# Appendix

## A. Commit-by-commit definition changes that matter for numbers

| commit | date | change | numeric impact |
|---|---|---|---|
| 2da4141 | 09-15 | statement fee = 2.9% formula; daily report scan cap 500; dashboards with no filters | Sept/Oct statements use the formula fee |
| 83fb3ed | 10-08 | EXCLUDED_SKUS = [1004856, 1002544] | daily report drops about $31–41k/mo of real sales from 10-08 [Q:excl_breakdown] |
| b676969 | 10-15 | callback idempotency | stops duplicate orders; existing 155 extras remain |
| f1217a8 | 10-26 | widget v1; **unmounts users and reports routers** | |
| ba1fbfa | 10-25 | lucente denylisted (report) | |
| 8f19718 | 10-28 | cancel endpoint; cancelled 4 → 2 | |
| a92c96d | 11-02 | statement fee = collected fees | Oct already published with the formula, hence the override |
| 102c9b4 | 11-05 | DST-correct local windows | 11-03 report short $2,985.99, never re-run |
| d87cb3d | 11-15 | refund endpoint, status 3 | |
| 11c0a42 | 11-18 | daily report excludes statuses 2/3 | |
| 1233af8 | 11-19 | removes the 500-row scan cap | 11-17 report short $74,995.96, never re-run |
| 12e1c68 | 11-20 | +$0.30 flat fee | live 14:27Z [Q:fee_switch] |
| 35c581e | 11-21 | DISCOUNT_CAP 0.25, but the helper defaults to 0.40 | ops rerun script understates |
| 5d1300d | 11-22 | order_lines + same-session merge | order grain change |
| b59f077 | 11-27 | QA user excluded (report via test_users; dashboards hard-coded) | |
| 2814b3d / 33054cd | 11-30 / 12-12 | category dashboard + versioned taxonomy | regrouping never effective (valid_from 2026) |
| 4a58d17 | 12-02 | statement expectation handles the flat fee | |
| e4656fb / 53f6f6c / 1cb8721 | 12-03 / 12-05 / 12-29 | fraud holds 0.90 / 0.70 / 0.85 | Dec revenue shaped by holds and a manual release |
| c49a7bb | 12-05 | gateway refund webhook; **unmounts accounts router** | negative payments, orders unchanged |
| 92596dc | 12-05 | report and dashboards count lines | units definition change |
| f563dea | 12-06 | trending 30d | |
| df4ed85 | 12-06 | rec v2 dispatch + random arm | |
| a2e0013 | 12-08 | intraday report + KPI dashboard rewrite (ET days, latest snapshot) | |
| cd559d3 | 12-09 | statements_final (the view itself was created by manual SQL) | |
| 2dde4f0 | 12-11 | board actives query | returns 0 |
| a1946ff | 12-14 | model v4 training | not served |
| 1169e40 | 12-15 | jetem hidden; dashboards gain the brand filter | |
| 30e8907 / a00f24c / 8ed2971 | 12-17 / 12-19 / 12-26 | random-arm logging lost and restored; empty-list cache bug; cache invalidation | |
| 3eced24 | 12-24 | revenue widget de-duplicates snapshots | |
| 41e3537 / 4bfcbe6 / 5ae1182 | Jan 2020 | Redash / Airflow / BigQuery migration | see §5.3 risks |

## B. Assessment of the committed docs

| doc | verdict | correction |
|---|---|---|
| README.md | stale | trending is 30d [c:f563dea]; v4 is not served, flags show 2.0.0 [F:deploy/flags.env]; model features are 5, not 9 [F:novamart/jobs/model_train.py]; router list incomplete |
| docs/restatement_policy.md | numbers correct, conclusion risky | `statements_final` ignores dups, reversals and gateway refunds; the chargebacks are placeholders on later-reversed orders [§4.1] |
| docs/metrics_definitions.md | definitions accurate | misses that board actives = 0, that the dashboard counts held orders, and that contactable = 0 [§4.5] |
| docs/dashboard_notes.md | accurate | the UUID exclusion is a no-op; held orders appear in best sellers [§4.6] |
| docs/affinity_lineage.md | correct | the logs also show no v1 reader after 12-06 16:39 [Q:table_readers] |
| docs/pricing_status.md | correct | add: zero list prices, the +4%/week feed drift [Q:price_history_all] |
| docs/forecast_caveats.md | correct | current snapshot: velocity 0.0714–2.7143, hints 51–102 [Q:reorder] |
| docs/trending_notes.md | correct | confirmed by `window_days` in [L:job_runs] |
| docs/rec_versions.md | "TBD" | see §5.4 |
| docs/data-access.md | mostly correct | the dataset is `novamart_analytics`, not `analytics` |

## C. Redash inventory

- 9 queries (ids 1–9) and 9 dashboards with the same names. Every query description reads "migrated from dashboards/<name>.sql" [redash/queries_list.json].
- The SQL is byte-identical to the last git version before deletion [diff of `raw/git_dashboards/*.sql` against `redash/query_*_*.sql`: all identical].
- Data source 1 = Postgres `estate-pg/novamart` [redash/data_sources.json].
- No widgets, cached results, schedules, alerts or snippets [redash/*.json; `/api/alerts` = []].

## D. Re-expressed dashboard values (BigQuery, "now" pinned to end of 2019-12-31 ET)

- **best_sellers** top 3: 1005116 ($5,889.81, 6 units), 1005115 ($5,325.55), 1005284 ($5,096.14, 2 units, both held) [Q:dash_best_sellers_asof].
- **brand_revenue**: apple $236,606.73; samsung $127,496.25; …; '' (blank) $17,391.05; internal $7,624.89 [Q:dash_brand_revenue_asof].
- **category_revenue** (30d): electronics $437,270.69; other $93,364.58; appliances $30,208.94 [Q:dash_category_asof].
- **daily_kpis** customer columns for 12-18..12-31: active 44–75 a day, contactable 0 [Q:kpi_dash_customer_days].
- **revenue_widget**: $139,598.13. The pre-fix naive version would give $410,387.39 [Q:intraday_versions][Q:report_vs_orders].
- **actives_board**: 0 [Q:board_actives_asof].
- **registered_conversion**: 30 buyers / $18,155.71 [Q:registered_conv].
- **refunds**: Nov $9,691.77; Dec $18,848.93 [Q:dash_refunds].
- **statements_final**: see §4.1 [Q:fin_final].

## E. Open questions (not resolvable from the available sources)

1. Why did order volume step down about 3× from 11-23 while cart activity held? It coincides with [c:5d1300d] but nothing in the logs shows errors [Q:daily_volume].
2. Why are there no orders on 11-15?
3. Who runs the weekly Tuesday cancel and refund batches?
4. Airflow runtime configuration is unknown: timezone, working directory, PYTHONPATH and the env for `ENABLE_DIGEST`. Verify before trusting post-migration outputs.
5. Are the 12-03 $2,999.99 orders a pricing bug or fraud? They are still held.

## F. Artifact index (this directory)

- `novamart_tribal_knowledge.md`: this document.
- `queries/*.sql|.out`: every BigQuery query and its output, referenced as `[Q:name]`.
- `raw/git_log_patch.txt`, `raw/git_log_stat.txt`: full history. `raw/git_dashboards/`: the pre-deletion dashboard SQL.
- `raw/engineer_queries.txt`: all 191 manual `engineer*` statements from `db_queries`.
- `redash/`: API dumps of queries, dashboards and the data source.
- `bqq.py`, `q.sh`: the read-only query helpers used.
