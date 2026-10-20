#!/usr/bin/env python3
"""Add a judge configuration to results/votes.csv from score-book scorecards, so it can be compared with the
published labels like every other row.

  python scoring/judges/validation/kit/votes_from_scorecards.py --configuration my-judge__v2 --scorecards eval-run-outputs/*

Each scorecard is one judge pass over one book (the scorecard.json that `score-book` writes). The book is
matched to the labelled cells through its path (submissions/<entry>/<book>.md); passes are ordered by the
scorecard timestamp. Every labelled cell must be covered by the same number of passes; cells outside the
labelled set are ignored. Then run compile_table.py.
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import VALIDATION_DIR, read_labels  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--configuration", required=True, help="column name to add, for example my-judge__v2")
    ap.add_argument("--scorecards", nargs="+", required=True, help="scorecard.json files or the run folders that hold them")
    ap.add_argument("--votes", default=os.path.join(VALIDATION_DIR, "results", "votes.csv"))
    a = ap.parse_args()

    files = []
    for s in a.scorecards:
        files += [s] if s.endswith(".json") else glob.glob(os.path.join(s, "*.json"))
    labelled = {(r["entry"], r["book"], r["claim_id"]): r["cell"] for r in read_labels()}
    per_book = defaultdict(list)   # (entry, book) -> [(timestamp, {claim: verdict})]
    for f in files:
        sc = json.load(open(f))
        parts = os.path.normpath(sc.get("book_path", "")).split(os.sep)
        if "submissions" not in parts:
            raise SystemExit(f"{f}: book_path does not point into submissions/<entry>/<book>.md")
        i = parts.index("submissions")
        entry, book = parts[i + 1], os.path.splitext(parts[i + 2])[0]
        per_book[(entry, book)].append((sc["timestamp"], {c["claim_id"]: c["verdict"] for c in sc["claim_results"]}))

    votes = {}
    for (entry, book), passes in per_book.items():
        passes.sort()
        for (e, b, cid), cell in labelled.items():
            if (e, b) == (entry, book):
                votes[cell] = [v[cid] for _, v in passes if cid in v]
    missing = [cell for cell in labelled.values() if not votes.get(cell)]
    if missing:
        raise SystemExit(f"{len(missing)} labelled cells have no verdict (first: {missing[:5]}); score every book the labels cover")
    counts = {len(v) for v in votes.values()}
    if len(counts) != 1:
        raise SystemExit(f"uneven number of passes across cells: {sorted(counts)}")

    with open(a.votes, newline="") as f:
        reader = csv.DictReader(f)
        rows, fields = list(reader), list(reader.fieldnames)
    if a.configuration not in fields:
        fields.append(a.configuration)
    for r in rows:
        r[a.configuration] = "|".join(votes[r["cell"]])
    with open(a.votes, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader(); w.writerows(rows)
    print(f"{a.configuration}: {len(votes)} cells, {counts.pop()} pass(es), written to {os.path.relpath(a.votes)}; now run compile_table.py")


if __name__ == "__main__":
    main()
