# Judge harness

The judge harness behind every reported number. An LLM judge (Claude Haiku 5.5 with the prompt in `judges/prompts/judge_v2_system_prompt.txt`, the same model and prompt for every entry) scores each book against each claim's rubric; the released verdict is the majority over five independent passes, ties resolved to the worse verdict. See [Judge versions](#judge-versions) for what changed on 2026-10-21 and how to reproduce older records.

## Run

Work from the repo root (the directory that contains `scoring/`, `claims/`, and `submissions/`). The judge needs either an Anthropic API key (`ANTHROPIC_API_KEY`; the default model string `claude-haiku-5-5` uses it) or AWS credentials with Amazon Bedrock access (`--judge-model bedrock/global.anthropic.claude-haiku-5-5`; this is the route the maintainer uses for verification). Both routes serve the same model with the same prompt and settings; judge calls are stochastic, so two runs can differ by a claim or two either way, whichever route they use.

```bash
pip install -r setup/requirements.txt
export ANTHROPIC_API_KEY=...     # or AWS credentials plus --judge-model bedrock/global.anthropic.claude-haiku-5-5

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

Other options: `--judge-model` (see below), `--workers`, `--output-dir` (single book, single pass only), `--yes` (skip the cost prompt shown for more than three books), `--ignore-must-include-fields` (drop the rubric's must_include list from the judge prompt; the released protocol keeps it).

Every scorecard records the judge it came from (`judge_model`, `judge_name`, `judge_prompt_sha256`), and so does each entry's `judge_record.json`.

The judge prompts are in `judges/llm_judge.py` and `judges/prompts/`; scoring and majority logic in `scoring.py`; reports in `report.py`.

## Judge versions

The judge version follows from the model name passed to `--judge-model`; nothing else selects it.

| Version | Model string | Prompt | Verdict rule | In use |
|---|---|---|---|---|
| v2 (current) | `claude-haiku-5-5` (Anthropic API) or `bedrock/global.anthropic.claude-haiku-5-5` (Amazon Bedrock) | `judges/prompts/judge_v2_system_prompt.txt`, effort high | the judge first lists the book passages that touch the claim, then states the claim's main finding and decides whether the book states it in full, in part, or not at all; that decision is the verdict (full = correct, part = partial, none = missing), and any must_not_include point found is contradicted | since 2026-10-21 |
| v1 | `gemini-3-flash-preview` | the original prompt in `judges/llm_judge.py`, temperature 0 | the judge's own verdict | 2026-08 to 2026-10-21 |

Any other model string runs the v2 prompt and rule and is reported as a custom judge; fine for experiments, never for a listed number.

How the v2 judge was chosen, with the 260 human-labelled cells, the verdicts and per-call outputs of every candidate, and a kit to label your own sample: [`judges/validation/`](judges/validation/README.md).

**What changed on 2026-10-21.** The judge moved from Gemini 3 Flash Preview (a preview model, about $27 of judge calls per verified submission) to Claude Haiku 5.5 (generally available, about $2.75 per verified submission) with a rewritten prompt. On 260 claim-book cells labelled by the maintainer, the majority-of-five verdict of the v2 judge agrees with the labels at Cohen's kappa 0.66, against 0.60 for v1; the v2 prompt was tuned on those same cells, so the number is in-sample. Every entry was rescored with v2 and the board was recompiled; the v1 records stay in each entry's folder as `judge_record_gemini-3-flash-preview.json`, `verified_verdicts_gemini-3-flash-preview.json` and `verified_entry_gemini-3-flash-preview.json`, and `reproduce_figures_tables.ipynb` still reads them, so the paper's tables reproduce unchanged. Mean recall before and after, by entry:

| System | Model | v1 (Gemini) | v2 (Haiku 5.5) |
|---|---|---|---|
| OpenCode 1.18.34 | Claude Fable 5.1 | 75.8 | 77.1 |
| OpenCode 1.18.34 | Claude Opus 5.5 | 74.5 | 70.6 |
| OpenCode 1.18.34 | Claude Sonnet 5.5 | 70.6 | 69.9 |
| Claude Code 2.1.252 | Claude Fable 5 | 62.7 | 66.0 |
| OpenCode 1.18.34 | GPT-6 Astra | 74.5 | 62.7 |
| Cursor 3.15.6 | Claude Fable 5 | 58.8 | 59.5 |
| OpenCode 1.18.34 | GPT-6.1 Sol | 66.7 | 57.5 |
| OpenCode 1.18.34 | Claude Fable 5 | 56.2 | 51.6 |
| Codex CLI 0.120.0 | GPT-5.6 Sol | 33.3 | 32.7 |
| OpenCode 1.18.34 | Gemini 3.8 Flash | 30.1 | 30.1 |
| OpenCode 1.18.34 | Gemini 3.1 Pro Preview | 1.3 | 7.2 |

Three fixes shipped with the switch: a response that is not a JSON object is asked again (up to two fresh calls) instead of being scored missing; a failed judge worker now aborts the pass instead of dropping that claim from the scorecard; Gemini calls carry a request timeout (5 minutes) so a stalled call is retried instead of hanging a worker.
