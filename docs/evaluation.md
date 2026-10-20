# Evaluation protocol and statistical notes

## Protocol

Each system is evaluated as shipped, zero-shot, **three times** under the same frozen brief (`default_prompts/`), with identical read-only access to the full estate. Because whole products are evaluated, score differences reflect model and scaffolding together. Each run produces one knowledge book.

## Scoring

Every book is scored per claim by an LLM judge (Claude Haiku 5.5 with the benchmark's judge prompt, judge v2, the same model and prompt for every entry) against the claim's rubric, with verdicts correct, partial, missing, or contradicted. Each entry's `judge_record.json` names the judge that produced it. The released verdict for a claim-book cell is the **majority over five independent judge passes**; ties resolve to the worse verdict. Claim recall is the fraction of the 51 claims whose rubric the book satisfies (verdict: correct). The judge changed once, on 2026-10-21; see [Judge versions](#judge-versions).

## Metrics

| Metric      | Definition                                                                                               |
| ----------- | -------------------------------------------------------------------------------------------------------- |
| Mean recall | average claim recall over the three runs (the leaderboard sort key)                                      |
| pass^3      | fraction of claims solved in all three runs                                                              |
| 95% CI      | claim-level bootstrap over the 51 claims, 10,000 resamples, percentile interval, reported on mean recall |


All numbers are recomputable from the per-entry judge records (`submissions/*/judge_record.json`, the full five-pass verdicts). The paper's tables come from the v1 records, kept per entry as `judge_record_gemini-3-flash-preview.json`.

## Statistical notes: what this benchmark can and cannot resolve

With 51 claims, one claim is worth about 2 points of recall, and the 95% interval on a mean recall is roughly plus or minus 10 points. So a gap under 10 points between two entries is noise, and that includes the gap between your own self-scored numbers and the verified listing. Gaps of about 15 points and more hold up when two systems are compared claim by claim. We know 51 claims is not a lot, and the wide interval is the cost of that. We are working on adding more audited claims; when they land they will go out as a new version with its own board, so the v1.0 numbers stay as they are.

Two smaller cautions. The per-category tables slice the 51 claims into groups of 2 to 26, so their intervals are much wider and they describe rather than rank. And with only three runs a standard deviation would mean little, so the leaderboard shows the three run scores sorted instead.

## Judge versions

| Version | Judge | In use | Agreement with 260 maintainer-labelled cells (Cohen's kappa, majority of five) |
|---|---|---|---|
| v2 | Claude Haiku 5.5, prompt `scoring/judges/prompts/judge_v2_system_prompt.txt`, effort high, verdict from the judge's main-finding decision | since 2026-10-21 | 0.66 (in-sample: the prompt was tuned on these cells) |
| v1 | Gemini 3 Flash Preview, original prompt, temperature 0 | 2026-08 to 2026-10-21 | 0.60 |

The switch was made because v1 ran on a preview model at about ten times the judge cost per verified submission, with no loss of agreement. On 2026-10-21 every entry was rescored with v2 and the leaderboard recompiled; the v1 records and statistics stay in each entry's folder (`*_gemini-3-flash-preview.json`) and the v1 judge remains selectable with `--judge-model gemini-3-flash-preview`. The per-entry before and after is in [`scoring/README.md`](../scoring/README.md#judge-versions).

## Verification of submissions

Submitters **must send three books** and their own prompts, if their system adds any; no statistics are required from them. The maintainer re-scores every submission with the judge (five passes per cell, majority verdict) and computes all listed numbers, so every entry is scored identically. Self-scored results are a useful sanity check but the listed numbers are always the verification run's. Submissions disclose the environment mode (cloud BigQuery or local emulator stack).