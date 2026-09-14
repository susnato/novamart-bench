# Judge harness

The scoring harness used for all reported results: rubric-anchored LLM judging (Gemini 3 Flash preview), five independent passes per book, majority verdict with ties resolved to the worse verdict.

## Run

Work from the repo root (the directory that contains `harness/`, `claims/`, and `books/`):

    pip install click pyyaml jsonschema google-genai
    export GEMINI_API_KEY=...                                    # judge model credentials
    mkdir -p novamart/gold && cp -r claims novamart/gold/claims  # the loader expects <benchmark>/gold/claims/*.yaml
    python -m harness.cli --help
    python -m harness.cli validate-claims-format novamart        # checks the 51 claims against schemas/claim.schema.json
    python -m harness.cli score-book --gold novamart --book books/cc_r1.md

One `score-book` call is one judge pass; it writes `scorecard.json` and `scorecard.md` (per-claim verdicts with justifications, plus claim recall) under `novamart/eval-run-outputs/<book>_<timestamp>/`. The released verdicts in `../results/verdicts.json` are the majority over five such passes. A pass in which every claim comes back `missing` almost always means the judge calls failed (for example, an invalid key): the per-claim justifications in the scorecard record the API error verbatim rather than aborting the run.

The judge prompts are in `judges/llm_judge.py`; scoring and majority logic in `scoring.py`; reports in `report.py`.
