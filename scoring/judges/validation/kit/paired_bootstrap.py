#!/usr/bin/env python3
"""Paired cell bootstrap of the kappa difference between two judge configurations on the labelled cells.

  python scoring/judges/validation/kit/paired_bootstrap.py --a claude-haiku-5-5__V5H6 --b claude-haiku-5-5__V5
  python scoring/judges/validation/kit/paired_bootstrap.py --a claude-haiku-5-5__V5H6 --b gemini-3-flash-preview__v1

Both configurations are scored on the same cells, so the difference is resampled per cell (paired). Each
configuration's verdict per cell is the majority over its passes (ties to the worse label); kappa is Cohen's
kappa on correct versus not correct, the statistic of results/table.md. Writes results/paired_bootstrap_<a>_vs_<b>.json.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import VALIDATION_DIR, kappa, majority, read_labels, read_votes, votes_of  # noqa: E402


def binary_kappa(cells, pred, human):
    tp = fn = fp = tn = 0
    for cell in cells:
        j, h = pred[cell] == "correct", human[cell] == "correct"
        if j and h:
            tp += 1
        elif j:
            fn += 1
        elif h:
            fp += 1
        else:
            tn += 1
    return kappa(tp, fn, fp, tn)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", required=True, help="configuration column of results/votes.csv, the candidate")
    ap.add_argument("--b", required=True, help="configuration column of results/votes.csv, the comparison")
    ap.add_argument("--resamples", type=int, default=10000)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()

    human = {r["cell"]: r["human_verdict"] for r in read_labels()}
    rows, configs = read_votes()
    for c in (a.a, a.b):
        if c not in configs:
            raise SystemExit(f"{c} is not a column of votes.csv; choose from {configs}")
    pred_a = {r["cell"]: majority(votes_of(r, a.a)) for r in rows if votes_of(r, a.a)}
    pred_b = {r["cell"]: majority(votes_of(r, a.b)) for r in rows if votes_of(r, a.b)}
    cells = sorted(set(pred_a) & set(pred_b) & set(human))

    k_a, k_b = binary_kappa(cells, pred_a, human), binary_kappa(cells, pred_b, human)
    rng = random.Random(a.seed)
    diffs = []
    for _ in range(a.resamples):
        sample = [cells[rng.randrange(len(cells))] for _ in cells]
        diffs.append(binary_kappa(sample, pred_a, human) - binary_kappa(sample, pred_b, human))
    diffs.sort()
    lo, hi = diffs[int(0.025 * len(diffs))], diffs[int(0.975 * len(diffs)) - 1]
    same = sum(pred_a[c] == pred_b[c] for c in cells)
    res = {"a": a.a, "b": a.b, "cells": len(cells), "kappa_a": k_a, "kappa_b": k_b, "diff": k_a - k_b,
           "ci95": [lo, hi], "share_diff_positive": sum(d > 0 for d in diffs) / len(diffs),
           "cells_same_majority_verdict": same, "resamples": a.resamples, "seed": a.seed,
           "reading": "interval excludes zero: a and b differ on this set; interval includes zero: same agreement within noise"}
    path = os.path.join(VALIDATION_DIR, "results", f"paired_bootstrap_{a.a}_vs_{a.b}.json")
    json.dump(res, open(path, "w"), indent=1)
    print(f"{a.a} vs {a.b}: cells {len(cells)}, kappa {k_a:.3f} vs {k_b:.3f}, diff {k_a - k_b:+.3f}, "
          f"95% CI [{lo:+.3f}, {hi:+.3f}], P(diff > 0) {res['share_diff_positive']:.2f}, same verdict on {same} cells")
    print("written", os.path.relpath(path))


if __name__ == "__main__":
    main()
