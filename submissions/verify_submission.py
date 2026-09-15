"""Verify a leaderboard submission, or self-test against the released verdicts.

  python verify/verify_submission.py --from-verdicts "Claude Code"   # self-test, no API calls
  python verify/verify_submission.py --submission submissions/<dir>  # full verification:
        5 judge passes per book (scoring score-book), majority verdicts, stats

Judge credentials: GEMINI_API_KEY, or Vertex AI via VERTEX_AI_PROJECT_ID with
gcloud application-default credentials. Stats: mean claim recall over the three
runs, claim-level bootstrap 95% CI (10,000 resamples, seed 0), pass^3, any-run.
"""
import argparse, glob, json, os, subprocess, sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PR_DATE = None  # set from --date: the submission PR's open date
WORSE = ["correct", "partial", "missing", "contradicted"]  # left best -> right worst
SYSTEMS = {"Claude Code": ["cc_r1","cc_r2","cc_r3"], "Cursor": ["cur_r1","cur_r2","cur_r3"], "Codex CLI": ["cx_r1","cx_r2","cx_r3"]}

def majority(votes):
    top = max(Counter(votes).values())
    tied = [v for v, c in Counter(votes).items() if c == top]
    return max(tied, key=WORSE.index)

def stats(matrix):
    """matrix: {claim_id: [bool solved per run]} with 3 runs."""
    import random
    claims = sorted(matrix)
    n = len(claims)
    c = {cid: sum(matrix[cid]) for cid in claims}
    runs = sorted((100.0 * sum(matrix[cid][r] for cid in claims) / n for r in range(3)), reverse=True)
    scores = [c[cid] / 3.0 for cid in claims]
    mean = 100.0 * sum(scores) / n
    rng = random.Random(0)
    boots = []
    for _ in range(10_000):
        s = [scores[rng.randrange(n)] for _ in range(n)]
        boots.append(100.0 * sum(s) / n)
    boots.sort()
    ci = [boots[int(0.025 * len(boots))], boots[int(0.975 * len(boots)) - 1]]
    return {"runs_sorted": [round(r, 1) for r in runs], "mean_recall": round(mean, 1),
            "ci95": [round(ci[0], 1), round(ci[1], 1)],
            "pass3": round(100.0 * sum(1 for cid in claims if c[cid] == 3) / n, 1),
            "any_run": round(100.0 * sum(1 for cid in claims if c[cid] >= 1) / n, 1)}

def from_verdicts(system):
    data = json.load(open(os.path.join(ROOT, "results", "verdicts.json")))["books"]
    books = SYSTEMS[system]
    claims = sorted(next(iter(data[books[0]].values()))["verdicts"])
    matrix = {}
    for cid in claims:
        row = []
        for b in books:
            votes = [p["verdicts"][cid] for p in data[b].values()]
            row.append(majority(votes) == "correct")
        matrix[cid] = row
    return stats(matrix)

def score_once(book_path):
    out_root = os.path.join(ROOT, "novamart", "eval-run-outputs")
    before = set(glob.glob(os.path.join(out_root, "*")))
    r = subprocess.run([sys.executable, "-m", "scoring.cli", "score-book",
                        "--gold", os.path.join(ROOT, "novamart"), "--book", book_path],
                       cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"score-book failed: {r.stderr[-500:]}")
    new = sorted(set(glob.glob(os.path.join(out_root, "*"))) - before)
    card = json.load(open(os.path.join(new[-1], "scorecard.json")))
    return {c["claim_id"]: c["verdict"] for c in card["claim_results"]}

def verify_submission(subdir):
    books = sorted(glob.glob(os.path.join(subdir, "book_r*.md")))
    assert len(books) == 3, f"expected 3 books, found {len(books)}"
    per_book = []
    for b in books:
        passes = [score_once(b) for _ in range(5)]
        claims = sorted(passes[0])
        per_book.append({cid: majority([p[cid] for p in passes]) == "correct" for cid in claims})
        print(f"  {os.path.basename(b)}: 5 passes done")
    claims = sorted(per_book[0])
    matrix = {cid: [pb[cid] for pb in per_book] for cid in claims}
    json.dump({cid: {f"book_r{r+1}": matrix[cid][r] for r in range(3)} for cid in claims},
              open(os.path.join(subdir, "verified_verdicts.json"), "w"), indent=1)
    entry = stats(matrix)
    import datetime, yaml as _yaml
    meta = _yaml.safe_load(open(os.path.join(subdir, "metadata.yaml")))
    entry.update({"verified": True,
                  "date": PR_DATE or datetime.date.today().isoformat(),
                  "verified_at": datetime.date.today().isoformat()})
    json.dump(entry, open(os.path.join(subdir, "verified_entry.json"), "w"), indent=1)
    print(f"wrote {subdir}/verified_entry.json and verified_verdicts.json")
    print("next: python website/compile_leaderboard.py && python website/render.py")
    compare_to_board(meta.get("system_name") or os.path.basename(subdir.rstrip("/")), matrix)
    return entry

def matrix_from_verdicts(system):
    data = json.load(open(os.path.join(ROOT, "results", "verdicts.json")))["books"]
    books = SYSTEMS[system]
    claims = sorted(next(iter(data[books[0]].values()))["verdicts"])
    return {cid: [majority([p["verdicts"][cid] for p in data[b].values()]) == "correct"
                  for b in books] for cid in claims}

def compare_to_board(name, matrix):
    """Print paired-bootstrap deltas of this entry vs every released system,
    as part of the verification report (10,000 resamples, seed 0)."""
    import random
    board = {s: matrix_from_verdicts(s) for s in SYSTEMS}
    claims = sorted(matrix)
    n = len(claims)
    rng = random.Random(0)
    draws = [[rng.randrange(n) for _ in range(n)] for _ in range(10_000)]
    print(f"\nPaired comparison of {name} vs the board (95% CI; 'resolved' = CI excludes zero):")
    print("| vs | metric | delta (pts) | 95% CI | resolved? |")
    print("|---|---|---|---|---|")
    for other, om in board.items():
        for metric, f in (("mean recall", lambda m, c: sum(m[c]) / 3.0),
                          ("pass^3", lambda m, c: 1.0 if sum(m[c]) == 3 else 0.0)):
            mine = [f(matrix, c) for c in claims]
            theirs = [f(om, c) for c in claims]
            pt = 100.0 * (sum(mine) - sum(theirs)) / n
            boots = sorted(100.0 * sum(mine[k] - theirs[k] for k in d) / n for d in draws)
            lo, hi = boots[int(0.025 * len(boots))], boots[int(0.975 * len(boots)) - 1]
            res = "yes" if (lo > 0 or hi < 0) else "no (tie)"
            print(f"| {other} | {metric} | {pt:+.1f} | [{lo:+.1f}, {hi:+.1f}] | {res} |")

def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--from-verdicts", metavar="SYSTEM")
    g.add_argument("--submission", metavar="DIR")
    ap.add_argument("--date", metavar="YYYY-MM-DD", default=None,
                    help="the submission PR's open date (shown on the leaderboard); default: today")
    a = ap.parse_args()
    global PR_DATE; PR_DATE = a.date
    entry = from_verdicts(a.from_verdicts) if a.from_verdicts else verify_submission(a.submission)
    print(json.dumps(entry, indent=1))
    if a.from_verdicts:
        lb = json.load(open(os.path.join(ROOT, "website", "leaderboard.json")))
        pub = next(e for e in lb["entries"] if e["system"] == a.from_verdicts)
        keys = ["runs_sorted", "mean_recall", "ci95", "pass3", "any_run"]
        diffs = {k: (entry[k], pub[k]) for k in keys if entry[k] != pub[k]}
        print("SELF-TEST vs leaderboard.json:", "MATCH" if not diffs else f"DIFFS {diffs}")
        return 1 if diffs else 0
    return 0

if __name__ == "__main__":
    sys.exit(main())
