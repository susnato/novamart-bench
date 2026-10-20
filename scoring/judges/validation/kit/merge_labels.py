#!/usr/bin/env python3
"""Unblind a finished kit: join sheet.csv with the sealed key into the labels.csv schema of this folder.

  python scoring/judges/validation/kit/merge_labels.py --kit kit_out --out my_labels.csv

Run this only when labelling is finished. The output has one row per sampled cell (labelled or not) with the
entry, book and claim behind each code, the human verdict, and the sampling judge's majority and votes.
"""
from __future__ import annotations

import argparse
import csv
import json
import os

FIELDS = ["cell", "study_book", "entry", "book", "claim_id", "human_verdict", "human_book_evidence", "rater_note",
          "sampling_judge_majority", "sampling_judge_votes"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kit", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    key = json.load(open(os.path.join(a.kit, "sealed", "key.json")))
    rows = []
    for r in csv.DictReader(open(os.path.join(a.kit, "sheet.csv"), newline="")):
        c = key["cells"][r["cell"]]
        rows.append({"cell": r["cell"], "study_book": c["book_code"], "entry": c["entry"], "book": c["book"],
                     "claim_id": r["claim_id"], "human_verdict": (r.get("verdict") or "").strip().lower(),
                     "human_book_evidence": (r.get("book_evidence") or "").strip(), "rater_note": (r.get("notes") or "").strip(),
                     "sampling_judge_majority": c["judge"], "sampling_judge_votes": "|".join(c["votes"])})
    rows.sort(key=lambda x: x["cell"])
    with open(a.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader(); w.writerows(rows)
    print(f"{a.out}: {len(rows)} cells, {sum(1 for r in rows if r['human_verdict'])} labelled")


if __name__ == "__main__":
    main()
