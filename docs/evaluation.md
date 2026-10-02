# Evaluation protocol and statistical notes

## Protocol

Each system is evaluated as shipped, zero-shot, **three times** under the same frozen brief (`default_prompts/`), with identical read-only access to the full estate. Because whole products are evaluated, score differences reflect model and scaffolding together. Each run produces one knowledge book.

## Scoring

Every book is scored per claim by an LLM judge (Gemini 3 Flash preview, the same model and prompt for every entry) against the claim's rubric, with verdicts correct, partial, missing, or contradicted. The three released baseline entries were scored with `gemini-3-flash-preview`, recorded per entry in `judge_record.json`; that judge is fixed as the benchmark's judge. The released verdict for a claim-book cell is the **majority over five independent judge passes**; ties resolve to the worse verdict. Claim recall is the fraction of the 51 claims whose rubric the book satisfies (verdict: correct).

## Metrics

| Metric      | Definition                                                                                               |
| ----------- | -------------------------------------------------------------------------------------------------------- |
| Mean recall | average claim recall over the three runs (the leaderboard sort key)                                      |
| pass^3      | fraction of claims solved in all three runs                                                              |
| Any-run     | fraction of claims solved in at least one run (ceiling)                                                  |
| 95% CI      | claim-level bootstrap over the 51 claims, 10,000 resamples, percentile interval, reported on mean recall |


All numbers are recomputable from the per-entry judge records (`submissions/*/judge_record.json`, the full five-pass verdicts).

## Statistical notes: what this benchmark can and cannot resolve

With 51 claims, one claim is worth about 2 points of recall, and the 95% interval on a mean recall is roughly plus or minus 10 points. So a gap under 10 points between two entries is noise, and that includes the gap between your own self-scored numbers and the verified listing. Gaps of about 15 points and more hold up when two systems are compared claim by claim. We know 51 claims is not a lot, and the wide interval is the cost of that. We are working on adding more audited claims; when they land they will go out as a new version with its own board, so the v1.0 numbers stay as they are.

Two smaller cautions. The per-category tables slice the 51 claims into groups of 2 to 26, so their intervals are much wider and they describe rather than rank. And with only three runs a standard deviation would mean little, so the leaderboard shows the three run scores sorted instead.

## Verification of submissions

Submitters **must send three books** and their own prompts, if their system adds any; no statistics are required from them. The maintainer re-scores every submission with the judge (five passes per cell, majority verdict) and computes all listed numbers, so every entry is scored identically. Self-scored results are a useful sanity check but the listed numbers are always the verification run's. Submissions disclose the environment mode (cloud BigQuery or local emulator stack).