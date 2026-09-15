# Evaluation protocol and statistical notes

## Protocol

Each system is evaluated as shipped, zero-shot, **three times** under the same frozen brief (`default_prompts/`), with identical read-only access to the full estate. Because whole products are evaluated, score differences reflect model and scaffolding together. Each run produces one knowledge book.

## Scoring

Every book is scored per claim by a pinned LLM judge (Gemini 3 Flash preview) against the claim's rubric, with verdicts correct, partial, missing, or contradicted. The released verdict for a claim-book cell is the **majority over five independent judge passes**; ties resolve to the worse verdict. Claim recall is the fraction of the 51 claims whose rubric the book satisfies (verdict: correct).

## Metrics

| Metric | Definition |
|---|---|
| Mean recall | average claim recall over the three runs (the leaderboard sort key) |
| pass^3 | fraction of claims solved in all three runs (the dependable core) |
| Any-run | fraction of claims solved in at least one run (capability ceiling) |
| 95% CI | claim-level bootstrap over the 51 claims, 10,000 resamples, percentile interval, reported on mean recall |

All numbers are recomputable from `results/verdicts.json`.

## Statistical notes: what this benchmark can and cannot resolve

With 51 claims, one claim is worth about 2 points of recall, and the 95% confidence interval on a mean recall is roughly plus or minus 10 points. Consequences, stated up front:

1. **Large gaps are real, small gaps are weather.** Paired on the shared claims, gaps of roughly 15 points and above are resolvable; the released 29-point gap between the strongest and weakest system is comfortably real. The 3.9-point gap between the top two systems is inside the judge spread and they are reported as statistically tied.
2. **Treat sub-10-point differences between leaderboard entries as noise**, including differences between your self-scored numbers and the verified listing.
3. **Category and stratum tables are descriptive.** Slices of 2-26 claims inherit correspondingly wider intervals and should not be read inferentially.
4. **Run-to-run variance is shown raw.** With three runs, a standard deviation would be a poor estimate, so the leaderboard prints the sorted run triple instead.

## Verification of submissions

Submitters send books only and compute no statistics. The maintainer re-scores every submission with the pinned judge (five passes per cell, majority verdict) and computes all listed numbers. Self-scored results are a useful sanity check but the listed numbers are always the verification run's. Submissions disclose the environment mode (cloud BigQuery or local emulator stack).
