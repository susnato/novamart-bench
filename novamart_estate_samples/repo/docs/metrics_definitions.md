# Active-customer metric definitions

This repo currently runs three different active-customer definitions.
They do not agree because they use different windows, filters, and refresh paths.

## 1) Nightly rollup: `analytics.kpi_daily.active_customers`

- **Lives in:** `novamart/jobs/kpi_daily.py`
- **Storage:** `analytics.kpi_daily`
- **Schedule:** `06:15 daily` in `crontab.txt`
- **Introduced:** commit `14726e7` on `2019-11-16` (`nightly kpi rollup: 30d active customers`)
- **Definition:**
  - `COUNT(DISTINCT user_id)` from `orders`
  - trailing **30 x 24 hour** window: `created_at >= <run_ts> - interval '30 days'`
  - only `status = 1`
  - no product-brand filter
  - no QA/test-user exclusion
  - no email-pattern exclusion
  - result is appended once per run to `analytics.kpi_daily`

This is the simplest definition: paid/completed buyers in the last 30 days, as of the nightly run timestamp.

## 2) Exec KPI dashboard: `dashboards/daily_kpis.sql`

- **Lives in:** `dashboards/daily_kpis.sql`
- **Surface:** KPI dashboard
- **Introduced:** file added in commit `2da4141` on `2019-09-15` (`initial import`)
- **Notable definition changes:**
  - commit `b59f077` on `2019-11-27`: exclude QA smoke-test `user_id = 424242`
  - commit `e10cb0c` on `2019-12-04`: add `contactable_customers` alongside `active_customers`
  - commit `a2e0013` on `2019-12-08`: include intraday report snapshots in the same dashboard file
  - commit `1169e40` on `2019-12-15`: hide `jetem` (and keep `lucente`) from dashboard queries
- **Definition:**
  - grouped by local calendar day: `(o.created_at AT TIME ZONE 'America/New_York')::date`
  - `COUNT(DISTINCT o.user_id)` from `orders`
  - window is the dashboard day range, currently today plus prior 13 days
  - **no order-status filter**
  - excludes `o.user_id = 424242`
  - joins `products` and excludes `p.brand IN ('lucente', 'jetem')`
  - separate from `contactable_customers`, which only counts users present in `analytics.contactable_users`

This is a daily dashboard series, not a single trailing-30-day KPI. It counts distinct ordering users per Eastern calendar day under the dashboard cleanup filters.

## 3) Board deck query: `dashboards/actives_board.sql`

- **Lives in:** `dashboards/actives_board.sql`
- **Surface:** board deck / board active-customers query
- **Introduced:** commit `2dde4f0` on `2019-12-11` (`Add board dashboard query for active customers`)
- **Definition:**
  - distinct `orders.user_id`
  - trailing **30 x 24 hour** window: `o.created_at >= now() - interval '30 days'`
  - excludes cancelled/non-active statuses with `NOT (o.status = ANY (ARRAY[0, 2, 3]))`
  - excludes rows present in `analytics.test_users`
  - excludes internal/test/demo/example-style email domains and localparts from `users.email`
  - no product-brand filter

This is the most aggressively cleaned-up definition. It is still a trailing 30-day buyer metric, but it removes known QA/test/internal accounts by both table lookup and email heuristics.

## Why the three numbers differ

In short:

- the **nightly rollup** uses trailing 30 days and `status = 1`, but keeps QA/test/internal users
- the **KPI dashboard** uses per-day distinct ordering users, with no status filter, and excludes QA `424242` plus `lucente` / `jetem`
- the **board deck** uses trailing 30 days, excludes several non-active statuses, and removes known/heuristic test users

So the three systems are not disagreeing about one shared metric; they are each computing a different one.
