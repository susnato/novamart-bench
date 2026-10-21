"""Shared pieces of the judge validation kit: file readers, the majority rule and Cohen's kappa.

Every script in this folder is plain Python 3.10+ with no third-party imports except where noted.
"""
from __future__ import annotations

import csv
import json
import os
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
VALIDATION_DIR = os.path.dirname(HERE)
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(VALIDATION_DIR)))   # validation -> judges -> scoring -> repo

LABELS = ["correct", "partial", "missing", "contradicted"]


def load_claims(repo: str = REPO_ROOT) -> dict[str, dict]:
    """The gold claims of claims/*.yaml keyed by claim id (needs PyYAML, as the scoring harness does)."""
    import glob
    import yaml
    claims = {}
    for f in sorted(glob.glob(os.path.join(repo, "claims", "*.yaml"))):
        d = yaml.safe_load(open(f))
        for c in (d["claims"] if isinstance(d, dict) and "claims" in d else d):
            claims[c["claim_id"]] = c
    return claims


def compact_evidence(ev) -> list[str]:
    """One line per gold evidence item for the reading guides: role, source, locator, a short excerpt."""
    out = []
    for e in ev or []:
        bits = [e.get("role", ""), e.get("source_type", "")]
        for k in ("path", "table", "uri", "commit_hash"):
            if e.get(k):
                bits.append(f"{k}={e[k]}")
        ex = (e.get("excerpt") or "").strip().replace("\n", " ")
        if ex:
            bits.append("excerpt: " + (ex[:400] + ("..." if len(ex) > 400 else "")))
        out.append(" | ".join(b for b in bits if b))
    return out
WORSE_FIRST = ["contradicted", "missing", "partial", "correct"]

# the leaderboard protocol: 3 books x 51 claims x 5 judge passes per verified submission
CALLS_PER_VERIFIED_SUBMISSION = 3 * 51 * 5


def majority(votes: list[str]) -> str:
    """Majority verdict over judge passes; a tie resolves to the worse label (the released scoring rule)."""
    counts = Counter(votes)
    top = max(counts.values())
    return next(v for v in WORSE_FIRST if counts.get(v) == top)


def kappa(tp: float, fn: float, fp: float, tn: float) -> float:
    """Cohen's kappa on a 2x2 table (rows: judge found yes/no, columns: human found yes/no)."""
    n = tp + fn + fp + tn
    if n == 0:
        return float("nan")
    po = (tp + tn) / n
    pj = (tp + fn) / n
    ph = (tp + fp) / n
    pe = pj * ph + (1 - pj) * (1 - ph)
    return (po - pe) / (1 - pe) if pe < 1 else float("nan")


def read_labels(path: str | None = None, labelled_only: bool = True) -> list[dict]:
    """Rows of labels/labels.csv; by default only the rows that carry a human verdict."""
    path = path or os.path.join(VALIDATION_DIR, "labels", "labels.csv")
    rows = list(csv.DictReader(open(path, newline="")))
    for r in rows:
        v = r["human_verdict"].strip().lower()
        if v and v not in LABELS:
            raise SystemExit(f"{path}: cell {r['cell']} has verdict {v!r}, expected one of {LABELS}")
        r["human_verdict"] = v
    return [r for r in rows if r["human_verdict"]] if labelled_only else rows


def read_votes(path: str | None = None) -> tuple[list[dict], list[str]]:
    """Rows of results/votes.csv and the list of configuration columns (every column after human_verdict).
    A configuration cell holds the per-pass verdicts joined by '|', in pass order."""
    path = path or os.path.join(VALIDATION_DIR, "results", "votes.csv")
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fields = reader.fieldnames or []
    configs = fields[fields.index("human_verdict") + 1:]
    return rows, configs


def read_json(name: str) -> dict:
    return json.load(open(os.path.join(VALIDATION_DIR, name)))


def votes_of(row: dict, config: str) -> list[str]:
    cell = row.get(config, "")
    return cell.split("|") if cell else []


def stratum_weights(rows: list[dict], population: dict[str, int]) -> dict[str, float]:
    """Weight per sampling-judge stratum so that the labelled sample stands in for the full population:
    population share over sample share."""
    n_by = Counter(r["sampling_judge_majority"] for r in rows)
    pop_total = sum(population.values())
    return {s: (population[s] / pop_total) / (n_by[s] / len(rows)) for s in n_by}


def two_by_two(rows: list[dict], predict, weights: dict[str, float] | None = None) -> tuple[float, float, float, float]:
    """Binary table (found = verdict 'correct') of a predictor against the human labels.
    predict(row) returns a verdict or None (cell skipped). Rows are weighted by their sampling-judge stratum when weights are given."""
    tp = fn = fp = tn = 0.0
    for r in rows:
        v = predict(r)
        if v is None:
            continue
        w = weights[r["sampling_judge_majority"]] if weights else 1.0
        j, h = v == "correct", r["human_verdict"] == "correct"
        if j and h:
            tp += w
        elif j:
            fn += w      # judge found, human did not: lenient error
        elif h:
            fp += w      # judge did not find, human did: strict error
        else:
            tn += w
    return tp, fn, fp, tn


def metrics(rows: list[dict], predict, weights: dict[str, float] | None) -> dict:
    tp, fn, fp, tn = two_by_two(rows, predict)
    n = tp + fn + fp + tn
    out = {"n": int(n), "agreement": (tp + tn) / n if n else None, "kappa": kappa(tp, fn, fp, tn) if n else None,
           "table": {"judge_found_human_found": tp, "judge_found_human_not": fn,
                     "judge_not_human_found": fp, "judge_not_human_not": tn}}
    if weights:
        wtp, wfn, wfp, wtn = two_by_two(rows, predict, weights)
        wn = wtp + wfn + wfp + wtn
        out["agreement_reweighted"] = (wtp + wtn) / wn if wn else None
        out["kappa_reweighted"] = kappa(wtp, wfn, wfp, wtn) if wn else None
    return out
