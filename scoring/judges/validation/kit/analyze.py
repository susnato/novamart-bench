#!/usr/bin/env python3
"""Agreement between human labels and a judge, on the binary the leaderboard uses (found = verdict correct).

Two ways to run it:

  # your own kit, against the judge record it was sampled from (opens sealed/, so only when you are done)
  python scoring/judges/validation/kit/analyze.py --kit kit_out

  # any labels file in the labels.csv schema, against any judge record file name under submissions/<entry>/
  python scoring/judges/validation/kit/analyze.py --labels scoring/judges/validation/labels/labels.csv --judge-record judge_record.json
  python scoring/judges/validation/kit/analyze.py --labels scoring/judges/validation/labels/labels.csv --judge-record judge_record_gemini-3-flash-preview.json

Reports raw agreement and Cohen's kappa with a stratified cell bootstrap, the 2x2 table with both error
directions named, and what the human said per judge label. When the labels carry sampling strata (the
sampling judge's majority per cell) and the population counts are known, the reweighted figures give each
stratum its population share. Writes <out>.md and <out>.json.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (LABELS, REPO_ROOT, VALIDATION_DIR, kappa, majority, read_labels,  # noqa: E402
                    stratum_weights, two_by_two)


def judge_from_record(repo: str, rows: list[dict], record_name: str) -> dict[str, list[str]]:
    """Votes per cell from submissions/<entry>/<record_name> for the entries the labels cover."""
    votes = {}
    recs = {}
    for r in rows:
        e = r["entry"]
        if e not in recs:
            path = os.path.join(repo, "submissions", e, record_name)
            if not os.path.exists(path):
                raise SystemExit(f"no {record_name} under submissions/{e}")
            recs[e] = json.load(open(path))
        passes = recs[e]["books"][r["book"]]
        votes[r["cell"]] = [passes[p]["verdicts"][r["claim_id"]] for p in sorted(passes) if p.startswith("pass")]
    return votes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kit", help="kit directory built by build_kit.py and labelled in sheet.csv")
    ap.add_argument("--labels", help="labels file in the labels.csv schema")
    ap.add_argument("--judge-record", default="judge_record.json", help="judge record file name under submissions/<entry>/ (with --labels)")
    ap.add_argument("--repo", default=REPO_ROOT)
    ap.add_argument("--population", default=None, help="JSON {label: count} of the population by sampling-judge majority; default: the kit's key, or labels/sampling.json for the published labels")
    ap.add_argument("--boot", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", default=None, help="output path without extension (default: next to the input)")
    a = ap.parse_args()
    if bool(a.kit) == bool(a.labels):
        raise SystemExit("give exactly one of --kit or --labels")

    population = json.load(open(a.population)) if a.population else None
    if a.kit:
        import csv
        key = json.load(open(os.path.join(a.kit, "sealed", "key.json")))
        rows = []
        for r in csv.DictReader(open(os.path.join(a.kit, "sheet.csv"), newline="")):
            v = (r.get("verdict") or "").strip().lower()
            if not v:
                continue
            if v not in LABELS:
                raise SystemExit(f"cell {r['cell']}: verdict {v!r} is not one of {LABELS}")
            c = key["cells"][r["cell"]]
            rows.append({"cell": r["cell"], "entry": c["entry"], "book": c["book"], "claim_id": r["claim_id"],
                         "human_verdict": v, "sampling_judge_majority": c["judge"]})
        judge_votes = {r["cell"]: key["cells"][r["cell"]]["votes"] for r in rows}
        judge_name = key.get("sampling_judge_record", "the sampling judge")
        population = population or key["population"]
        out = a.out or os.path.join(a.kit, "results")
    else:
        rows = read_labels(a.labels)
        judge_votes = judge_from_record(a.repo, rows, a.judge_record)
        judge_name = a.judge_record
        if population is None and os.path.abspath(a.labels) == os.path.join(VALIDATION_DIR, "labels", "labels.csv"):
            population = json.load(open(os.path.join(VALIDATION_DIR, "labels", "sampling.json")))["population_by_sampling_judge_majority"]
        out = a.out or os.path.splitext(a.labels)[0] + f"_vs_{os.path.splitext(a.judge_record)[0]}"
    if not rows:
        raise SystemExit("no labelled cells")

    judge_maj = {cell: majority(v) for cell, v in judge_votes.items()}
    predict = lambda r: judge_maj.get(r["cell"])  # noqa: E731
    weights = stratum_weights(rows, population) if population and all(r.get("sampling_judge_majority") for r in rows) else None

    def summary(sample_rows, w):
        tp, fn, fp, tn = two_by_two(sample_rows, predict, w)
        n = tp + fn + fp + tn
        return {"raw_agreement": (tp + tn) / n, "kappa": kappa(tp, fn, fp, tn),
                "table": {"judge_found_human_found": tp, "judge_found_human_not": fn, "judge_not_human_found": fp, "judge_not_human_not": tn}}

    res = {"judge": judge_name, "n_labelled": len(rows), "population": population,
           "unweighted": summary(rows, None), "reweighted": summary(rows, weights) if weights else None}
    # stratified cell bootstrap
    rng = random.Random(a.seed)
    by_s = defaultdict(list)
    for r in rows:
        by_s[r.get("sampling_judge_majority") or "all"].append(r)
    for name, w in (("unweighted", None), ("reweighted", weights)):
        if res[name] is None:
            continue
        ks, ags = [], []
        for _ in range(a.boot):
            samp = [x for s, lst in by_s.items() for x in rng.choices(lst, k=len(lst))]
            m = summary(samp, w)
            ks.append(m["kappa"]); ags.append(m["raw_agreement"])
        ks.sort(); ags.sort()
        lo, hi = int(0.025 * a.boot), int(0.975 * a.boot) - 1
        res[name]["kappa_ci95"] = [ks[lo], ks[hi]]
        res[name]["raw_agreement_ci95"] = [ags[lo], ags[hi]]
    # what the human said per judge label
    per = {}
    for s in LABELS:
        here = [r["human_verdict"] for r in rows if judge_maj.get(r["cell"]) == s]
        if here:
            per[s] = {"n": len(here), "human_correct_rate": sum(h == "correct" for h in here) / len(here), "human_labels": dict(Counter(here))}
    res["by_judge_label"] = per

    json.dump(res, open(out + ".json", "w"), indent=1)
    head = res["reweighted"] or res["unweighted"]
    L = [f"# Human labels versus {judge_name}", "",
         f"Labelled cells: {len(rows)}. Binary: found means verdict correct; the judge's verdict per cell is the majority over its passes (ties to the worse label)."
         + (" Reweighted to the population mix of sampling-judge labels." if res["reweighted"] else ""), "",
         "| Measure | Value | 95% CI (stratified bootstrap) |", "|---|---|---|",
         f"| Raw agreement | {100 * head['raw_agreement']:.1f}% | {100 * head['raw_agreement_ci95'][0]:.1f} to {100 * head['raw_agreement_ci95'][1]:.1f} |",
         f"| Cohen's kappa | {head['kappa']:.3f} | {head['kappa_ci95'][0]:.3f} to {head['kappa_ci95'][1]:.3f} |"]
    if res["reweighted"]:
        u = res["unweighted"]
        L += [f"| Cohen's kappa, unweighted sample | {u['kappa']:.3f} | {u['kappa_ci95'][0]:.3f} to {u['kappa_ci95'][1]:.3f} |"]
    t = head["table"]
    L += ["", "## 2 x 2 table" + (" (population-weighted cell counts)" if res["reweighted"] else ""), "",
          "| | human: found | human: not found |", "|---|---|---|",
          f"| judge: found | {t['judge_found_human_found']:.1f} | {t['judge_found_human_not']:.1f} (lenient) |",
          f"| judge: not found | {t['judge_not_human_found']:.1f} (strict) | {t['judge_not_human_not']:.1f} |", "",
          "## What the human said, by judge label", "", "| Judge label | n | human says correct | human label mix |", "|---|---|---|---|"]
    for s, p in per.items():
        L.append(f"| {s} | {p['n']} | {100 * p['human_correct_rate']:.1f}% | {p['human_labels']} |")
    open(out + ".md", "w").write("\n".join(L) + "\n")
    print("\n".join(L))
    print(f"\nwritten {out}.md and {out}.json")


if __name__ == "__main__":
    main()
