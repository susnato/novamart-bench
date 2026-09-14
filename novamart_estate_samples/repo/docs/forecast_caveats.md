# Forecast caveats

## Short answer

The `reorder-hint` numbers are **not** coming from a learned forecasting system.

They come from a nightly batch job, `novamart/jobs/reorder_forecast.py`, that writes `analytics.reorder_hints` using a small hand-fit heuristic:

```python
hint_units = int(BASE + K / (velocity + C))
```

where:

- `velocity = paid orders in the last 14 days / 14`
- `BASE = 15.6`
- `K = 162.4`
- `C = 1.8`

This output is explicitly labeled in code and README as **ADVISORY** / **directional only**.

**Finance should not treat these numbers as trustworthy buy-commit quantities on their own.** They are useful as a rough signal that a product is moving, but not as a finance-grade purchasing forecast.

## Where the numbers come from

The nightly job is scheduled in `crontab.txt`:

```txt
06:50  daily    novamart.jobs.reorder_forecast
```

`novamart/jobs/reorder_forecast.py` does the following each run:

1. creates `analytics.reorder_hints` if needed
2. selects the top `200` products by recent paid-order velocity
3. computes `velocity` as `COUNT(*) / 14.0` from `orders`
4. keeps only `status = 1` orders from the last `14 days`
5. computes `hint_units = int(BASE + K / (velocity + C))`
6. deletes the prior contents of `analytics.reorder_hints`
7. inserts the fresh `200` rows with one `created_at` timestamp

So the numbers are based only on:

- recent paid-order counts
- a 14-day lookback
- the top 200 recent products
- three hard-coded constants

They are **not** using:

- vendor lead times
- current on-hand inventory targets
- open POs
- returns/refunds/cancellations beyond the `status = 1` filter
- seasonality / holidays
- stockout effects
- price changes / promotions
- margin or cash constraints
- safety-stock policy

## What changed in the December refit

Git history for `novamart/jobs/reorder_forecast.py` shows two relevant commits:

- `f5e3032` — `reorder hints job (advisory heuristic)`
- `f85cdd2` — `refit reorder constant for Q4 velocity`

Blame on the file shows the December change touched only the `K` line. `BASE` and `C`, the SQL, the 14-day window, the top-200 cutoff, and the table-writing pattern all stayed the same.

So the December refit was **not** a redesign of the method. It was a **single-constant retune** of the inverse-velocity formula.

In other words:

- same data source
- same window
- same product cutoff
- same formula shape
- one hand-fit constant changed

That makes the refit closer to a manual calibration pass than to a new validated forecasting model.

## What production is doing now

Production logs show `reorder_forecast` running daily and logging:

```json
{"job": "reorder_forecast", "event": "hints_written", "n": 200}
```

The current production table snapshot shows one fresh batch with:

- `200` rows
- `velocity` from about `0.0714` to `2.2857` orders/day
- `hint_units` from `55` to `102`

That range is itself a caveat: with this formula, **lower recent velocity produces a larger hint** because `K / (velocity + C)` gets larger as velocity falls.

So if someone reads `hint_units` as “buy more of the faster seller,” this heuristic does **not** behave that way. It does the opposite mechanically.

## Should finance trust these numbers?

Short answer: **no, not as a sole basis for committing real money.**

Reasons:

1. **The code says not to.**
   - file docstring: `ADVISORY heuristic`
   - README: `Do not use it for finance or commitments unless specifically told to.`

2. **It is hand-fit, not validated.**
   The file header says the constants were hand-fit in a notebook against October sell-through. The December refit changed one constant, but there is no evidence in repo of holdout testing, error bars, service levels, or PO-cost optimization.

3. **It only sees a narrow slice of demand.**
   The job uses only paid-order counts over 14 days. That is too thin for a purchasing commitment without inventory context and seasonality.

4. **It only covers the current top 200 products.**
   Anything outside that recent top-200 list gets no hint at all.

5. **The formula shape is hard to justify as a buy quantity.**
   Since hints rise as velocity falls, the number is better understood as a heuristic score/output from an old notebook than as a conventional reorder quantity recommendation.

6. **The table is overwritten nightly.**
   The job deletes the prior contents before inserting the new batch, so the operational table is not a durable audit trail of forecast history.

## Bottom line for finance

Use `analytics.reorder_hints` only as a **rough merchandising signal**.

Do **not** let purchasing commit spend directly from it without a human review layer that adds:

- on-hand inventory
- lead time
- MOQ / case-pack constraints
- supplier reliability
- seasonal demand expectations
- stockout history
- budget / margin constraints

If finance wants a number they can truly commit against, this job should be treated as a starting point for a replacement, not as the final forecasting system.