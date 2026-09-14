# Affinity lineage

## Short answer

The similar-products widget currently reads `analytics.product_affinity_v2`, not `analytics.product_affinity`.

The old nightly job/table pair (`novamart.jobs.affinity` -> `analytics.product_affinity`) appears unused by the widget in the current code path, so it looks safe to drop **for the widget**. I did not find evidence here that any other consumer still reads the old table, but that should be confirmed before removal because both jobs are still scheduled.

## Evidence

### 1) Current widget code dispatches v2 for the active recommendation version

`novamart/routers/similar.py`:

- `REC_VERSIONS` maps `"2.0.0"` to `"affinity v2 exploit"`.
- `intended_version()` reads `deploy/flags.env`.
- For the non-random arm, the widget selects:

```python
table = ("analytics.product_affinity_v2" if effective == "2.0.0"
         else "analytics.model_scores")
```

and then queries:

```sql
SELECT rec_pid FROM analytics.product_affinity_v2
WHERE base_pid = %s AND score >= 0
ORDER BY score DESC LIMIT %s
```

There is no current code path in `similar.py` that reads `analytics.product_affinity`.

### 2) The active flag is set to recommendation version 2.0.0

`deploy/flags.env` contains:

```env
REC_MODEL_VERSION=2.0.0
```

So the widget's intended version is the affinity-v2 path by default.

### 3) App query logs show the widget switched from the old table to v2

Older app traffic used the legacy table. Example from `db_queries.log` on 2019-10-26:

```sql
SELECT rec_pid FROM analytics.product_affinity
WHERE base_pid = %s AND score >= 0
ORDER BY score DESC LIMIT %s
```

After the v2 rollout, app traffic hits the v2 table instead. Examples from `db_queries.log` on 2019-12-06:

```sql
SELECT rec_pid FROM analytics.product_affinity_v2
WHERE base_pid = %s AND score >= 0
ORDER BY score DESC LIMIT %s
```

I also found the rollout commit in `git log novamart/routers/similar.py`:

- `df4ed85` (2019-12-06): `similar: model version dispatch + random data-collection arm`

That lines up with the first observed app reads from `analytics.product_affinity_v2`.

### 4) Both nightly jobs still run

`crontab.txt` shows both jobs scheduled:

```txt
03:30  daily    novamart.jobs.affinity
03:45  daily    novamart.jobs.affinity_v2
```

So the old pipeline is still paying a nightly compute/storage cost even though the widget code now points at v2.

### 5) The two jobs write different tables

- `novamart/jobs/affinity.py` writes `analytics.product_affinity`
- `novamart/jobs/affinity_v2.py` writes `analytics.product_affinity_v2`

The v2 job also stamps `model_version = '2.0.1'` in the table rows, while the serving layer chooses the table based on serving version `2.0.0`. In other words:

- serving version `2.0.0` => read table `analytics.product_affinity_v2`
- batch writer version string inside that table => `2.0.1`

That naming mismatch is a little confusing, but it does not change which table the widget reads.

## Conclusion

For the widget specifically:

- **In use:** `analytics.product_affinity_v2`
- **Not used by current widget code:** `analytics.product_affinity`

## Is the old one safe to drop?

**Probably yes for widget-serving purposes.** The current widget code will not read `analytics.product_affinity` as long as `REC_MODEL_VERSION=2.0.0` (or a later non-legacy path) remains in place.

Caveat: I only verified the widget path plus the available logs/repo references. Before dropping the old job/table entirely, I would still do a quick search outside the widget for any ad hoc dashboards, notebooks, or external jobs that may still read `analytics.product_affinity`.

Based on the repo and logs reviewed here, I did not find such a consumer.
