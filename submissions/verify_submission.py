"""Verify a leaderboard submission, or self-test against the released verdicts.

  python verify/verify_submission.py --from-verdicts "Claude Code"   # self-test, no API calls
  python verify/verify_submission.py --submission submissions/<dir>  # full verification:
        5 judge passes per book (scoring score-book), majority verdicts, stats

Judge credentials: GEMINI_API_KEY, or Vertex AI via VERTEX_AI_PROJECT_ID with
gcloud application-default credentials. Stats: mean claim recall over the three
runs, claim-level bootstrap 95% CI (10,000 resamples, seed 0), pass^3, any-run.
"""
import argparse, glob, json, os, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)  # so the scoring package imports from any cwd
from scoring.stats import majority, stats as shared_stats

PR_DATE = None  # set from --date: the submission PR's open date
SYSTEMS = {"Claude Code": "claude-code-2.1.252", "Cursor": "cursor-3.15.6", "Codex CLI": "codex-cli-0.120.0"}

def stats(matrix):
    """matrix: {claim_id: [bool solved per run]} with 3 runs.

    The math lives in scoring/stats.py, shared with score-book so self-scored
    and verified numbers are identical by construction; this wrapper only maps
    the generic pass_all/pass_any names to the released entry field names."""
    s = shared_stats(matrix, runs=3)
    return {"runs_sorted": s["runs_sorted"], "mean_recall": s["mean_recall"],
            "ci95": s["ci95"], "pass3": s["pass_all"], "any_run": s["pass_any"]}

def from_verdicts(system):
    return stats(matrix_from_verdicts(system))

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
    per_book, record = [], {}
    for b in books:
        passes = [score_once(b) for _ in range(5)]
        claims = sorted(passes[0])
        bk = os.path.splitext(os.path.basename(b))[0]
        record[bk] = {f"pass{i+1}": {"claim_recall": round(sum(v == "correct" for v in p.values()) / len(p), 4),
                                     "verdicts": p} for i, p in enumerate(passes)}
        per_book.append({cid: majority([p[cid] for p in passes]) == "correct" for cid in claims})
        print(f"  {os.path.basename(b)}: 5 passes done")
    json.dump({"protocol": "released verdict per claim = majority over 5 passes, ties to the worse verdict (correct>partial>missing>contradicted)",
               "judge_model": "gemini-3-flash-preview", "books": record},
              open(os.path.join(subdir, "judge_record.json"), "w"), indent=1)
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
    slug = SYSTEMS.get(system, system)
    data = json.load(open(os.path.join(ROOT, "submissions", slug, "judge_record.json")))["books"]
    books = sorted(data)
    claims = sorted(next(iter(data[books[0]].values()))["verdicts"])
    return {cid: [majority([p["verdicts"][cid] for p in data[b].values()]) == "correct"
                  for b in books] for cid in claims}

def compare_to_board(name, matrix):
    """Print paired-bootstrap deltas of this entry vs every released system,
    as part of the verification report (10,000 resamples, seed 0)."""
    import random
    board = {}
    for jr in sorted(glob.glob(os.path.join(ROOT, "submissions", "*", "judge_record.json"))):
        slug = os.path.basename(os.path.dirname(jr))
        if slug != name:
            board[slug] = matrix_from_verdicts(slug)
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
                    help="REQUIRED with --submission: the submission PR's open date, which becomes the canonical date on the leaderboard")
    a = ap.parse_args()
    if a.submission and not a.date:
        ap.error("--date is required with --submission: pass the submission PR's open date (canonical on the leaderboard)")
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
