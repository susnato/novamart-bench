# Dashboard notes

## Best sellers: what the official dashboard is actually counting

`dashboards/best_sellers.sql` applies these filters/rules:

- **Rolling 7-day window**: `io.created_at >= now() - interval '7 days'`
  - This is a rolling **7 x 24 hour** window anchored to query time, not a calendar week.
  - It has been there since the initial dashboard import in commit `2da4141`.

- **Count item rows, not just order rows**: the query reads from an `item_orders` CTE.
  - For newer multi-item orders it counts rows from `order_lines`.
  - For legacy single-item orders it falls back to the row on `orders`, but only when that order has no `order_lines`.
  - This was added in commit `92596dc` (`Count report and dashboard sales per item using order_lines with legacy fallback`).
  - Production DB logs line up with that change: `order_lines` first appears on 2019-11-22, so older orders still need the fallback.

- **Exclude the QA smoke-test user**: `io.user_id <> 424242`
  - This was added in commit `b59f077` (`Exclude QA smoke-test users from daily report and dashboards`).
  - Production app logs show repeated `session: "qa-smoke"` orders for `user_id = 424242`, so this is a dashboard cleanup filter rather than a business segmentation rule.

- **Hide Lucente and Jetem products**: `p.brand NOT IN ('lucente', 'jetem')`
  - This was added in commit `1169e40` (`Hide jetem from report and dashboard queries`).
  - That same change added the `products` join so dashboard queries could filter by brand.
  - Production DB logs show a large `lucente` catalog import starting 2019-10-01; those SKUs are intentionally excluded from exec dashboards.

## Things people often miss when reproducing it by hand

These are not extra filters, but they are common reasons for a small mismatch:

- **No order-status filter**: `dashboards/best_sellers.sql` does **not** require `orders.status = 1`.
  - This is different from the nightly `novamart/jobs/top_sellers.py` job, which does filter to `status = 1`.
  - So a hand query that only counts completed/paid orders will come out lower.

- **Ranking is by revenue, not units**: the dashboard returns `COUNT(*) AS units` but sorts by `ORDER BY revenue DESC`.

## Same cleanup filters in the other exec dashboards

The best-sellers dashboard is not the only place these rules show up:

- `dashboards/category_revenue.sql`
  - same `order_lines` + legacy `orders` fallback from `92596dc`
  - rolling `30 days`
  - excludes `user_id = 424242`
  - excludes `brand IN ('lucente', 'jetem')`

- `dashboards/brand_revenue.sql`
  - same `order_lines` + legacy `orders` fallback from `92596dc`
  - rolling `30 days`
  - excludes `user_id::text NOT IN ('424242', 'cc27b436-d6f9-4e84-adaf-e716025dd369')`
  - excludes `brand IN ('lucente', 'jetem')`
  - app logs show `cc27b436-d6f9-4e84-adaf-e716025dd369` was later created for the same smoke-test account on 2019-12-01, which is why this query has the extra string-form exclusion.

- `dashboards/daily_kpis.sql`
  - excludes `brand IN ('lucente', 'jetem')` in both historical and intraday revenue reads
  - excludes `o.user_id = 424242` in the `customer_days` CTE

## Bottom line

If you want a hand-written query to match `dashboards/best_sellers.sql`, it needs to do all of the following:

- use a rolling last-7-days window
- count from `order_lines` when present, with a fallback to legacy `orders` rows
- exclude `user_id = 424242`
- exclude products whose `brand` is `lucente` or `jetem`
- leave order status unfiltered
- sort by revenue, not units
