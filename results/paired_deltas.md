# Paired system deltas

Pairwise differences with claim-level PAIRED bootstrap 95% CIs (10,000 resamples, seed 0): both systems are evaluated on the same drawn claims in every resample, so shared claim difficulty cancels. A CI excluding zero marks a statistically resolved gap; overlapping MARGINAL CIs do not imply a tie (see docs/evaluation.md). Regenerate with `python verify/verify_submission.py --paired-deltas` whenever the leaderboard changes.

| Pair | Metric | Delta (pts) | 95% CI | Resolved? |
|---|---|---|---|---|
| Claude Code - Cursor | mean recall | +3.9 | [-3.9, +11.8] | no (tie) |
| Claude Code - Cursor | pass^3 | +0.0 | [-13.7, +13.7] | no (tie) |
| Claude Code - Codex CLI | mean recall | +29.4 | [+18.3, +40.5] | yes |
| Claude Code - Codex CLI | pass^3 | +15.7 | [+2.0, +29.4] | yes |
| Cursor - Codex CLI | mean recall | +25.5 | [+15.7, +35.9] | yes |
| Cursor - Codex CLI | pass^3 | +15.7 | [+3.9, +27.5] | yes |
