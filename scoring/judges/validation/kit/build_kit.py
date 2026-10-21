#!/usr/bin/env python3
"""Build a blind labelling kit: a seeded, stratified sample of claim-book cells from one or more leaderboard
entries, their books under opaque codes, a rating sheet, per-book reading guides, and a sealed key.

  python scoring/judges/validation/kit/build_kit.py --out kit_out --entries claude-code-2.1.252 cursor-3.15.6 --n 30 --seed 1

Reads submissions/<entry>/<judge record> (default judge_record.json, the current judge) for the verdict strata,
submissions/<entry>/book_rK.md for the books, and claims/ for the guides. Writes only under --out.
Do not open <out>/sealed/ until labelling is finished; analyze.py opens it for you.

Requires PyYAML (already needed by the scoring harness).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import random
import shutil
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import LABELS, REPO_ROOT, compact_evidence, load_claims, majority  # noqa: E402


def load_cells(repo: str, entries: list[str], record_name: str) -> list[dict]:
    """One row per (entry, book, claim): the judge record's majority label, its votes, and whether the passes disagreed."""
    cells = []
    for e in entries:
        path = os.path.join(repo, "submissions", e, record_name)
        if not os.path.exists(path):
            raise SystemExit(f"no {record_name} under submissions/{e}")
        rec = json.load(open(path))
        for book, passes in rec["books"].items():
            pv = {p: passes[p]["verdicts"] for p in passes if p.startswith("pass")}
            for cid in next(iter(pv.values())):
                votes = [pv[p][cid] for p in sorted(pv)]
                cells.append({"entry": e, "book": book, "claim_id": cid, "judge": majority(votes),
                              "votes": votes, "disagree": len(set(votes)) > 1})
    return cells


def allocate(cells: list[dict], n: int, override: dict[str, int] | None) -> tuple[dict[str, int], dict[str, int]]:
    """Cells per stratum: proportional to the population (every contradicted cell is taken, they are rare),
    or an explicit allocation such as correct=10,partial=10,missing=10."""
    pop = Counter(c["judge"] for c in cells)
    if override:
        alloc = {k: v for k, v in override.items() if pop.get(k)}
    else:
        alloc = {"contradicted": pop["contradicted"]}
        rest = n - alloc["contradicted"]
        others = [s for s in LABELS if s != "contradicted" and pop[s]]
        tot = sum(pop[s] for s in others)
        for s in others:
            alloc[s] = max(1, round(rest * pop[s] / tot))
        while sum(alloc.values()) > n:
            biggest = max(others, key=lambda s: alloc[s]); alloc[biggest] -= 1
        while sum(alloc.values()) < n:
            smallest = min(others, key=lambda s: alloc[s] / pop[s]); alloc[smallest] += 1
    for k, v in alloc.items():
        if v > pop[k]:
            raise SystemExit(f"stratum {k}: asked {v}, population {pop[k]}")
    return alloc, dict(pop)


def sample(cells: list[dict], alloc: dict[str, int], rng: random.Random) -> list[dict]:
    """Within each stratum: every cell on which the passes disagreed first, then a random fill balanced across books."""
    chosen = []
    by_stratum = defaultdict(list)
    for c in cells:
        by_stratum[c["judge"]].append(c)
    for label, k in alloc.items():
        pool = by_stratum[label][:]
        rng.shuffle(pool)
        forced = [c for c in pool if c["disagree"]][:k]
        rest = [c for c in pool if not c["disagree"]]
        by_book = defaultdict(list)
        for c in rest:
            by_book[(c["entry"], c["book"])].append(c)
        books = sorted(by_book)
        rng.shuffle(books)
        picked = list(forced)
        i = 0
        while len(picked) < k and any(by_book.values()):
            b = books[i % len(books)]
            if by_book[b]:
                picked.append(by_book[b].pop())
            i += 1
        chosen.extend(picked[:k])
    return chosen


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=REPO_ROOT, help="repository root (default: this checkout)")
    ap.add_argument("--out", required=True, help="kit directory to create")
    ap.add_argument("--entries", nargs="+", required=True, help="submissions/<entry> folders to sample from")
    ap.add_argument("--judge-record", default="judge_record.json",
                    help="judge record file inside each entry folder that defines the strata (default: the current judge)")
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--allocation", default=None, help="explicit cells per stratum, e.g. correct=10,partial=10,missing=10")
    a = ap.parse_args()
    rng = random.Random(a.seed)
    override = None
    if a.allocation:
        override = {k: int(v) for k, v in (kv.split("=") for kv in a.allocation.split(","))}
        a.n = sum(override.values())

    claims = load_claims(a.repo)
    cells = load_cells(a.repo, a.entries, a.judge_record)
    alloc, pop = allocate(cells, a.n, override)
    chosen = sample(cells, alloc, rng)
    assert len(chosen) == a.n, len(chosen)

    # opaque codes: books in seeded order, cells C-#### in seeded order
    books = sorted({(c["entry"], c["book"]) for c in cells})
    rng.shuffle(books)
    book_code = {b: chr(ord("A") + i) for i, b in enumerate(books)}
    order = chosen[:]
    rng.shuffle(order)
    cell_code = {(c["entry"], c["book"], c["claim_id"]): f"C-{i + 1:04d}" for i, c in enumerate(order)}

    os.makedirs(os.path.join(a.out, "books"), exist_ok=True)
    os.makedirs(os.path.join(a.out, "sealed"), exist_ok=True)
    for (entry, book), code in book_code.items():
        shutil.copy(os.path.join(a.repo, "submissions", entry, f"{book}.md"), os.path.join(a.out, "books", f"book_{code}.md"))

    key = {"seed": a.seed, "n": a.n, "entries": a.entries, "sampling_judge_record": a.judge_record,
           "allocation": alloc, "population": pop,
           "books": {code: {"entry": e, "book": b} for (e, b), code in book_code.items()},
           "population_cells": [{"entry": c["entry"], "book": c["book"], "claim_id": c["claim_id"], "judge": c["judge"]} for c in cells],
           "cells": {}}
    for c in chosen:
        code = cell_code[(c["entry"], c["book"], c["claim_id"])]
        key["cells"][code] = {"entry": c["entry"], "book": c["book"], "claim_id": c["claim_id"],
                              "book_code": book_code[(c["entry"], c["book"])], "judge": c["judge"],
                              "votes": c["votes"], "disagree": c["disagree"]}
    key_path = os.path.join(a.out, "sealed", "key.json")
    json.dump(key, open(key_path, "w"), indent=1)
    digest = hashlib.sha256(open(key_path, "rb").read()).hexdigest()
    open(os.path.join(a.out, "sealed", "key.sha256"), "w").write(digest + "\n")

    # rating sheet, grouped by book so each book is read once, shuffled within a book
    rows = []
    for (entry, book), code in sorted(book_code.items(), key=lambda kv: kv[1]):
        here = [c for c in chosen if (c["entry"], c["book"]) == (entry, book)]
        rng.shuffle(here)
        for c in here:
            rows.append({"cell": cell_code[(c["entry"], c["book"], c["claim_id"])], "book": code,
                         "claim_id": c["claim_id"], "verdict": "", "book_evidence": "", "notes": ""})
    with open(os.path.join(a.out, "sheet.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["cell", "book", "claim_id", "verdict", "book_evidence", "notes"])
        w.writeheader(); w.writerows(rows)

    # per-book reading guide: claim, match points, gold evidence as context only
    for (entry, book), code in sorted(book_code.items(), key=lambda kv: kv[1]):
        here = [r for r in rows if r["book"] == code]
        if not here:
            continue
        lines = [f"# Book {code}: {len(here)} cells", "", f"Read `books/book_{code}.md` once, then label each cell below in `sheet.csv` (or run rate_app.py).", ""]
        for r in here:
            cl = claims[r["claim_id"]]
            m = cl.get("match") or {}
            lines += [f"## {r['cell']}  (claim {r['claim_id']})", "", "**Claim.** " + " ".join(str(cl.get("claim_text", "")).split()), ""]
            if m.get("must_include"):
                lines += ["**Must include (all of these for correct):**"] + [f"- {x}" for x in m["must_include"]] + [""]
            if m.get("must_not_include"):
                lines += ["**Must not include (any of these means contradicted):**"] + [f"- {x}" for x in m["must_not_include"]] + [""]
            ev = compact_evidence(cl.get("evidence"))
            if ev:
                lines += ["**Gold evidence, context only. Do not count it as evidence in the book.**"] + [f"- {x}" for x in ev] + [""]
            lines += ["Verdict: correct | partial | missing | contradicted", ""]
        open(os.path.join(a.out, f"guide_book_{code}.md"), "w").write("\n".join(lines))

    print(f"kit written to {a.out}: n={a.n} seed={a.seed} entries={a.entries} strata from {a.judge_record}")
    print("population by judge label:", pop)
    print("sample by judge label:", dict(Counter(c["judge"] for c in chosen)))
    print("cells on which the judge passes disagreed: population", sum(c["disagree"] for c in cells), "sample", sum(c["disagree"] for c in chosen))
    print("cells per book:", dict(sorted(Counter(r["book"] for r in rows).items())))
    print(f"sealed key sha256 {digest[:16]}... (do not open sealed/ until you are done)")


if __name__ == "__main__":
    main()
