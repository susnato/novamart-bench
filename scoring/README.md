# Judge harness

The judge harness behind every reported number. An LLM judge (Gemini 3 Flash preview, the same model and prompt for every entry) scores each book against each claim's rubric; the released verdict is the majority over five independent passes, ties resolved to the worse verdict.

## Run

Work from the repo root (the directory that contains `scoring/`, `claims/`, and `submissions/`). The judge needs Gemini credentials: either `GEMINI_API_KEY`, or Vertex AI via `VERTEX_AI_PROJECT_ID` with gcloud application-default credentials.

```bash
pip install -r setup/requirements.txt
export GEMINI_API_KEY=...        # or: export VERTEX_AI_PROJECT_ID=your-gcp-project

# make sure claims are in valid format (checks the 51 claims against claims/claim.schema.json)
python -m scoring.cli validate-claims-format claims

# one book: per-claim scorecard, recall, 95% CI
python -m scoring.cli score-book --gold claims --book book_r1.md

# your three runs: mean recall, 95% CI, pass^3 (repeat --book per book)
python -m scoring.cli score-book --gold claims --book book_r1.md --book book_r2.md --book book_r3.md

# optional: majority verdicts over multiple judge passes per book
python -m scoring.cli score-book --gold claims --book book_r1.md --judge-passes 3

# all options
python -m scoring.cli score-book --help
```

`score-book` with one `--book` runs one judge pass and writes `scorecard.json` and `scorecard.md` (per-claim verdicts with justifications, plus claim recall) under `eval-run-outputs/<book>_<timestamp>/` at the repo root (gitignored). Repeat `--book` for your three runs to get mean recall, 95% CI, pass^3 and pass@3 (stamped unofficial until verification), and add `--judge-passes N` for a majority verdict per claim over N passes (ties to the worse verdict; each pass gets its own `_p<N>` folder). The released verdicts for every leaderboard entry are in `submissions/<entry>/judge_record.json` (the raw five passes) and `verified_verdicts.json` (the majorities). If a judge call fails for good (bad credentials, or a rate limit or transient error that is still failing after six retries with backoff), `score-book` stops with the error and writes no scorecard for that pass; nothing is ever silently scored as `missing` because the API was unreachable.

Other options: `--judge-model`, `--workers`, `--output-dir` (single book, single pass only), `--yes` (skip the cost prompt shown for more than three books), `--ignore-must-include-fields` (drop the rubric's must_include list from the judge prompt; the released protocol keeps it).

The judge prompts are in `judges/llm_judge.py`; scoring and majority logic in `scoring.py`; reports in `report.py`.
