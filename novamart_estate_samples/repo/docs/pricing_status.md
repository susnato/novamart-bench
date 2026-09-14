# Pricing status

## Short answer

`analytics.price_suggestions` is a nightly **shadow-output analytics table** from the dynamic-pricing experiment.

It contains up to 500 suggested list-price nudges based on the last 14 days of paid-order volume:

- `product_id`
- `current_price`
- `suggested_price`
- `demand_units`
- `created_at`

**Nothing in the live app currently serves from this table.** We are **not** dynamically adjusting storefront prices from it.

## Evidence

### 1) The nightly job still writes fresh rows

`crontab.txt` schedules:

```txt
04:45  daily    novamart.jobs.price_suggest
```

`jobs.jsonl` shows the job running every day and writing `n=500` rows, for example on 2019-12-27:

```json
{"job": "price_suggest", "event": "suggestions_written", "n": 500}
```

`novamart/jobs/price_suggest.py` creates and repopulates `analytics.price_suggestions` each run by:

- selecting the top 500 products by paid units in the last 14 days
- applying a `+/- 5%` nudge around the current product `list_price`
- deleting the prior contents of `analytics.price_suggestions`
- inserting the fresh suggestions

So the table is real and refreshed nightly, but only as batch output.

### 2) The job itself says it is shadow-only

At the top of `novamart/jobs/price_suggest.py`:

```python
"""Dynamic pricing, phase 1 (SHADOW): nightly price suggestions.

Phase 2 (serving reads behind a flag) is planned; until then nothing
consumes this table.
"""
```

And the file ends with:

```python
# NOTE(dec 2): Phase 2 (serving) ON HOLD per exec/legal review. Shadow job keeps running.
```

`git log novamart/jobs/price_suggest.py` also shows:

- `894c535` — `dynamic pricing phase 1: nightly shadow suggestions`
- `cca9b0d` — `hold dynamic pricing rollout per exec review`

That lines up with a write-only shadow pipeline, not a live pricing system.

### 3) Repo search found no serving path that reads the table

I checked the service entrypoints and routers (`novamart/app.py`, `novamart/routers/catalog.py`, `carts.py`, `orders.py`, plus the scheduled jobs) and found no code path that selects from `analytics.price_suggestions`.

The only repo reference to that table is the writer job itself: `novamart/jobs/price_suggest.py`.

### 4) Production query logs show writes, but no reads

In `db_queries.log` I found repeated nightly statements like:

```sql
CREATE TABLE IF NOT EXISTS analytics.price_suggestions (...)
DELETE FROM analytics.price_suggestions
INSERT INTO analytics.price_suggestions VALUES (...)
```

I did **not** find app or job queries of the form:

```sql
SELECT ... FROM analytics.price_suggestions
```

So in production the table is being populated, but not read by the service.

### 5) Live prices come from other paths

The current app updates product prices through the vendor feed in `novamart/routers/catalog.py`:

- `/catalog/prices` writes incoming `list_price` values into `products`
- it also appends to `analytics.price_history`

Orders also use the request body `price` directly in `novamart/routers/orders.py`; there is no lookup into `analytics.price_suggestions` before charging or writing orders.

So the live price surface is the vendor/catalog path, not the suggestion table.

## Conclusion

`analytics.price_suggestions` is a nightly analytics/shadow table produced by the shelved dynamic-pricing experiment.

- **What it is:** top-500 product price recommendations based on recent demand
- **Fresh rows every night:** yes
- **Anything serves from it:** **no**
- **Are we dynamically adjusting prices from it today:** **no**

## How I verified it

I verified this by combining:

1. repo inspection of `novamart/jobs/price_suggest.py`
2. repo inspection of app routers and entrypoints for any read path
3. cron schedule review in `crontab.txt`
4. production log review of `jobs.jsonl` for nightly runs
5. production SQL log review showing nightly writes and no reads from `analytics.price_suggestions`
6. git history on `novamart/jobs/price_suggest.py` showing rollout was held in shadow mode
