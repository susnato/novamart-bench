"""Compile leaderboard.json from the canonical submissions folder.

Entries = every submissions/*/ folder carrying a maintainer-written
verified_entry.json. The header (benchmark, protocol, notes) is kept from the
existing leaderboard.json; the entries array is machine-owned by this script.

  python verify/compile_leaderboard.py            # rewrite leaderboard.json
  python verify/compile_leaderboard.py --check    # exit 1 if the file drifts
"""
import glob, json, os, sys
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def compile_entries():
    entries = []
    for vp in sorted(glob.glob(os.path.join(ROOT, "submissions", "*", "verified_entry.json"))):
        d = os.path.dirname(vp)
        meta = yaml.safe_load(open(os.path.join(d, "metadata.yaml")))
        ve = json.load(open(vp))
        entries.append({
            "system": meta["system_name"], "version": str(meta.get("version", "")),
            "model": meta.get("model", ""), "effort": meta.get("effort", ""),
            "date": ve.get("date", ""),
            "runs_sorted": ve["runs_sorted"], "mean_recall": ve["mean_recall"],
            "ci95": ve["ci95"], "pass3": ve["pass3"], "any_run": ve["any_run"],
            "mode": meta.get("environment_mode", ""),
            "verified": bool(ve.get("verified")),
            "submitted_by": meta.get("submitted_by", ""),
        })
    entries.sort(key=lambda e: -e["mean_recall"])
    for i, e in enumerate(entries, 1): e["rank"] = i
    return entries

def main():
    path = os.path.join(ROOT, "website", "leaderboard.json")
    lb = json.load(open(path))
    fresh = compile_entries()
    if "--check" in sys.argv:
        current = [{k: e[k] for k in fresh[0]} for e in lb["entries"]] if fresh else lb["entries"]
        if current != fresh:
            print("leaderboard.json DRIFTS from submissions/: run python verify/compile_leaderboard.py")
            return 1
        print(f"leaderboard.json matches submissions/ ({len(fresh)} entries)")
        return 0
    lb["entries"] = fresh
    json.dump(lb, open(path, "w"), indent=2)
    print(f"compiled {len(fresh)} entries into leaderboard.json")
    return 0

if __name__ == "__main__":
    sys.exit(main())
