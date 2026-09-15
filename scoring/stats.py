"""Shared statistics for book scoring and submission verification.

These are the exact functions the maintainer's verifier uses
(submissions/verify_submission.py); `score-book` imports them too, so
self-scored numbers and verified numbers are the same math by construction.
"""
from __future__ import annotations

import random
from collections import Counter

WORSE = ["correct", "partial", "missing", "contradicted"]  # left best -> right worst


def majority(votes):
    """Majority verdict; ties resolve to the worse verdict."""
    top = max(Counter(votes).values())
    tied = [v for v, c in Counter(votes).items() if c == top]
    return max(tied, key=WORSE.index)


def stats(matrix, runs=3):
    """matrix: {claim_id: [bool solved per run]} with `runs` runs.

    Returns run recalls (sorted desc), mean recall, claim-level bootstrap 95%
    CI (10,000 resamples, seed 0, percentile interval), pass_all (solved in
    all runs) and pass_any (solved in at least one run), all in percent.
    """
    claims = sorted(matrix)
    n = len(claims)
    c = {cid: sum(matrix[cid]) for cid in claims}
    run_recalls = sorted((100.0 * sum(matrix[cid][r] for cid in claims) / n for r in range(runs)), reverse=True)
    scores = [c[cid] / float(runs) for cid in claims]
    mean = 100.0 * sum(scores) / n
    rng = random.Random(0)
    boots = []
    for _ in range(10_000):
        s = [scores[rng.randrange(n)] for _ in range(n)]
        boots.append(100.0 * sum(s) / n)
    boots.sort()
    ci = [boots[int(0.025 * len(boots))], boots[int(0.975 * len(boots)) - 1]]
    return {"runs_sorted": [round(r, 1) for r in run_recalls], "mean_recall": round(mean, 1),
            "ci95": [round(ci[0], 1), round(ci[1], 1)],
            "pass_all": round(100.0 * sum(1 for cid in claims if c[cid] == runs) / n, 1),
            "pass_any": round(100.0 * sum(1 for cid in claims if c[cid] >= 1) / n, 1)}
