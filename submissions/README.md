# Submitting to the leaderboard

One pull request adds one folder named `<system>-<version>-<YYYYMMDD>` (lowercase slug) directly under `submissions/`, containing:

1. **Books (required)**: `book_r1.md`, `book_r2.md`, `book_r3.md`, each the direct output of one run under read-only estate access.
2. **Metadata (required)**: `metadata.yaml`, copied from [`template/metadata.yaml`](template/metadata.yaml). `system_name` (shown on the leaderboard) is required.
3. **Prompts**: if you used the released brief unmodified (`default_prompts/`), include nothing; submitting under these rules attests to that, and verification checks it. If you used a custom prompt or scaffold, include the complete text (`prompt.md`, or `prompt_r1.md`..`prompt_r3.md` if it varied); entries containing prompt files are listed as custom-scaffold, with a marker, outside the headline ranking.
4. **Trajectories (optional, encouraged)**: `trajectories/` with the agent transcript and tool calls per run.

That is the whole submission: **you compute no statistics.**

## What happens after you open the PR

The maintainer re-scores your books with the pinned judge (five passes per claim, majority verdict) and computes every listed number. **Verification adds two files to your folder**: `verified_entry.json` (your entry's statistics: runs, mean recall, 95% CI, pass^3) and `verified_verdicts.json` (your per-claim results). These files are only ever written by the maintainer; a submission PR must not contain them. The leaderboard is compiled exclusively from folders carrying `verified_entry.json`, so merge + verification is what puts an entry on the board. The verification report also shows your paired comparison against every existing entry. The date shown on the leaderboard is the date your submission PR was opened; the maintainer records it at verification (`--date`) and it is canonical (the maintainer-run baselines carry their original run date).

Ground rules: the estate is read-only, books must be the direct outputs of the submitted runs, and no gold-claim content may appear in prompts or scaffolds. Custom prompts are reviewed for gold-claim leakage. Entries within roughly 10 points of each other are statistically tied and the board reports them as ties (see `docs/evaluation.md`).

The three baseline entries (`claude-code-2.1.252/`, `cursor-3.15.6/`, `codex-cli-0.120.0/`) follow this same format; their books sit inside their folders like any other entry (`book_r1..3.md`; the original release names cc_r1.., cur_r1.., cx_r1.. remain the keys in `results/verdicts.json`, noted in each metadata).
