# Submitting to the leaderboard

Please open one pull request that adds one folder named `<system>-<version>-<YYYYMMDD>` (lowercase slug) directly under `submissions/`, containing:

1. **Books (required)**: `book_r1.md`, `book_r2.md`, `book_r3.md`, each the direct output of one run under read-only estate access.
2. **Metadata (required)**: `metadata.yaml`, copied from [`template/metadata.yaml`](template/metadata.yaml). `system_name` (shown on the leaderboard) is required.
3. **Prompts**: If you use the [default prompts](../default_prompts/) for your agent (we encourage it as well), nothing is required here but if not, then please include them as (`prompt.md`, or `prompt_r1.md`..`prompt_r3.md` if they varied). **No gold-claim content may appear in them.**
4. **Trajectories (optional, encouraged)**: `trajectories/` with the agent transcript and tool calls per run.

You do not need to compute any statistics: the maintainer runs the judge on your books and computes every listed number, so all entries are scored the same way.

## What happens after you open the PR

The maintainer re-scores your books with the judge (five passes per claim, majority verdict; the same model and prompt for every entry) and computes every listed number. **Verification adds two files to your folder**: `verified_entry.json` (your entry's statistics: runs, mean recall, 95% CI, pass^3) and `verified_verdicts.json` (your per-claim results). These files are only ever written by the maintainer; a submission PR must not contain them. The leaderboard is compiled exclusively from folders carrying `verified_entry.json`, so an entry appears on the board once its PR is merged and verified. The verification report also shows your paired comparison against every existing entry. The date shown on the leaderboard is the date your submission PR was opened; the maintainer records it at verification (`--date`); the baseline entries carry their original run dates.

Ground rules: the estate is read-only, books must be the direct outputs of the submitted runs, and no gold-claim content may appear in prompts or scaffolds. Included prompts are reviewed for gold-claim leakage.

By opening a submission PR you release the submitted books, prompts and trajectories under CC BY 4.0 (`LICENSE-DATA`). Books are verbatim agent outputs and may contain factual errors; the leaderboard measures them, it does not endorse them. Differences under roughly 10 points fall inside the 95% CI, see `docs/evaluation.md`.

The three baseline entries (`claude-code-2.1.252/`, `cursor-3.15.6/`, `codex-cli-0.120.0/`) follow this same format; their books sit inside their folders like any other entry (`book_r1..3.md`; the original release names cc_r1.., cur_r1.., cx_r1.. are preserved in each entry's `judge_record.json` under `released_book_names`).
