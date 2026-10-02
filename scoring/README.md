# Judge harness

The judge harness behind every reported number. An LLM judge (Gemini 3 Flash preview, the same model and prompt for every entry) scores each book against each claim's rubric; the released verdict is the majority over five independent passes, ties resolved to the worse verdict.

## Run

Work from the repo root (the directory that contains `scoring/`, `claims/`, and `submissions/`):

    pip install -r setup/requirements.txt
    export GEMINI_API_KEY=...                                    # judge model credentials
    mkdir -p novamart/gold && cp -r claims novamart/gold/claims  # the loader expects <benchmark>/gold/claims/*.yaml
    python -m scoring.cli --help
    python -m scoring.cli validate-claims-format novamart        # checks the 51 claims against claims/claim.schema.json
    python -m scoring.cli score-book --gold novamart --book submissions/claude-code-2.1.252/book_r1.md

`score-book` with one `--book` runs one judge pass and writes `scorecard.json` and `scorecard.md` (per-claim verdicts with justifications, plus claim recall) under `novamart/eval-run-outputs/<book>_<timestamp>/`. Repeat `--book` for your three runs to get mean recall, 95% CI, pass^3 and pass@3 (stamped unofficial until verification), and add `--judge-passes N` for a majority verdict per claim over N passes (ties to the worse verdict; each pass gets its own `_p<N>` folder). The released verdicts for every leaderboard entry are in `submissions/<entry>/judge_record.json` (the raw five passes) and `verified_verdicts.json` (the majorities). A pass in which every claim comes back `missing` almost always means the judge calls failed (for example, an invalid key): the per-claim justifications record the API error verbatim rather than aborting the run.

Other options: `--judge-model`, `--workers`, `--output-dir` (single book, single pass only), `--yes` (skip the cost prompt shown for more than three books), `--ignore-must-include-fields` (drop the rubric's must_include list from the judge prompt; the released protocol keeps it).

The judge prompts are in `judges/llm_judge.py`; scoring and majority logic in `scoring.py`; reports in `report.py`.
