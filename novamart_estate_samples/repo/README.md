# novamart

Backend for the novamart marketplace. FastAPI + Postgres.

## Layout

- `novamart/` — the service
  - `app.py` — FastAPI app, lifespan wiring
  - `routers/` — catalog, carts, orders
  - `jobs/` — batch jobs run by cron (see `crontab.txt`)
  - `db.py` — connection pool + statement logging
  - `constants.py` — business/config constants
- `schema.sql` — database schema (apply once at setup)
- `ci/run_ci.py` — CI entrypoint (boots the app against a scratch DB, checks core flows)
- `crontab.txt` — job schedule

## Run

```bash
pip install -r requirements.txt
psql "$NOVAMART_DSN" -f schema.sql
uvicorn novamart.app:app --workers 4
```

Environment: `NOVAMART_DSN` (Postgres), `NOVAMART_LOG_DIR` (where app/db logs go).

## Notes

- Prices come from the catalog feed; product rows are created on first sight.
- Nightly `reconcile` flags anything odd in payments; check the logs if finance asks.


## Trending

Nightly job `novamart/jobs/trending.py`: ranks products by units over a **60-day window** (min 5 units to qualify), recency-decayed. Output: `analytics.trending_daily`.

## Reorder hints

`analytics.reorder_hints` is an ADVISORY heuristic (hand-fit constants). Do not use it for finance or commitments unless specifically told to.

## Rec model v4

`novamart/jobs/model_train.py` trains the learned similar-products model nightly (random-arm data). Features: served-list size, base price, base popularity, account age, signup channel, marketing opt-in, user region affinity, device mix, and stock level. Serving is version `4.0.0` behind `REC_MODEL_VERSION` in deploy/flags.env.

Dashboards moved to Redash (see docs/data-access.md); the old SQL files remain in git history under dashboards/.
