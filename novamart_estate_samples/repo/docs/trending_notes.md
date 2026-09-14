# Trending notes

README is stale here.

## What the job is actually doing

`novamart/jobs/trending.py` currently uses a **30-day** rolling window, not 60 days.

The nightly job:

- runs at `05:15` daily (`crontab.txt`)
- reads from `orders`
- keeps only `status = 1` orders
- counts units per `product_id` over `created_at >= run_time - 30 days`
- requires at least `5` units to qualify
- applies recency decay with `score = units * exp(-0.05 * age_days_since_last_order)`
- writes the top `50` rows into `analytics.trending_daily` for that day

So the window is:

- **rolling**, not calendar-month based
- anchored to the job run timestamp
- effectively **30 x 24 hours** of order history

## Why the list started churning faster in December

The lookback was shortened from **60 days** to **30 days** in commit `f563dea` (`trending: fresher window`) on 2019-12-06.

Production logs show the job still logging `window_days: 60` through 2019-12-06, then `window_days: 30` starting on 2019-12-07. That matches the faster churn the analyst noticed: with half the history, older demand drops out sooner and the recency decay has more influence.

## Bottom line

The README note saying trending uses a **60-day window** is no longer true.

What is live in production is a **30-day rolling window** with the same min-5-units filter, recency decay, and top-50 output.
