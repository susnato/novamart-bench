# Judge validation

Every number on the leaderboard is a verdict from an LLM judge: for each of the 51 claims and each book, the judge decides whether the book states the claim (correct), states part of it (partial), misses it (missing) or asserts the opposite (contradicted), and the released verdict is the majority over five independent passes. This folder shows how the judge was chosen and how well it agrees with a human. It holds the human labels, the verdicts of every judge configuration we compared, the per-call outputs behind the summary table, and a kit to label your own sample and score the current judge against it.

Judge v2 (Claude Haiku 5.5 with `../prompts/judge_v2_system_prompt.txt`, in use since 2026-10-21) was selected with this study. Judge v1 (Gemini 3 Flash Preview with the original prompt, used from 2026-08 to 2026-10-21) is the first judge row of the table. The study was run on 2026-10-16 to 2026-10-20.

## Summary

<!-- table:start -->
| Judge | Prompt | Cohen's kappa | Raw agreement | Cost per verified submission | Model status | Model string |
|---|---|---|---|---|---|---|
| Always "not correct" (floor) | none | 0.000 | 65.4% | $0 | | |
| Gemini 3 Flash Preview (judge v1) | v1 release prompt | 0.601 | 81.5% | $26.77 | preview | `gemini-3-flash-preview` |
| Gemini 3 Flash Preview | V4 | 0.561 | 78.8% | $26.54 | preview | `gemini-3-flash-preview` |
| Gemini 3.8 Flash | v1 release prompt | 0.461 | 77.3% | $16.14 | GA | `gemini-3.8-flash` |
| Claude Sonnet 5.5 | V4 | 0.509 | 78.5% | $40.20 | GA | `bedrock/global.anthropic.claude-sonnet-5-5` |
| Claude Haiku 5.5 | v1 release prompt | 0.433 | 76.5% | $2.01 | GA | `bedrock/global.anthropic.claude-haiku-5-5` |
| Claude Haiku 5.5 | V5 (hand-written) | 0.614 | 81.5% | $2.64 | GA | `bedrock/global.anthropic.claude-haiku-5-5` |
| **Claude Haiku 5.5 (judge v2)** | **V5H6 (reflective rewrite of V5)** | **0.663** | **83.8%** | **$2.72** | **GA** | `bedrock/global.anthropic.claude-haiku-5-5` |
| GPT-6 Luna | V5 | 0.532 | 76.9% | $1.77 | GA | `bedrock/global.openai.gpt-6-luna` |
| GPT-6 Luna | V5RL3 (reflective rewrite of V5) | 0.522 | 77.7% | $2.07 | GA | `bedrock/global.openai.gpt-6-luna` |
| GPT-6.1 Sol | V3 | 0.413 | 75.4% | $8.96 | GA | `bedrock/global.openai.gpt-6.1-sol` |
<!-- table:end -->

Each row of the table is one judge configuration (a model and a prompt) run five times over the same 260 human-labelled cells; its verdict per cell is the majority of the five passes, ties to the worse label, as on the leaderboard. Kappa is Cohen's kappa against the human label on the binary the leaderboard uses, correct versus not correct, and raw agreement is the share of cells where the two agree on it. Cost per verified submission is the configuration's mean cost per call times the 765 calls of one verified entry (3 books x 51 claims x 5 passes), at the list prices in `prompts/price_table.json`.

## Every figure here is in-sample

Like MT-Bench, AlpacaEval, HealthBench, DeepResearch Bench and WebJudge, none of which holds out labels for prompt development, we compared the prompt variants on the same 260 labelled cells. 45 configurations besides judge v1 were scored on these cells during prompt development (all of them are in `results/table_full.md`), so every agreement figure in this folder is in-sample; the labels are published so that anyone can repeat the check with fresh labels.

## The labels

The population is the 459 claim-book cells of the paper's three entries (Claude Code, Cursor and Codex CLI, three books each, 51 claims). 300 cells were sampled with seed 20261010, stratified by the v1 judge's majority verdict so that partial and missing cells are over-represented, with every cell on which the five v1 passes disagreed included. Books and cells were given opaque codes, the mapping was sealed, and the human read each book once and labelled its cells with the rubric the v1 judge used (`prompts/v1_system_prompt.txt`), blind to the entry and to the judge's verdicts, between 2026-10-11 and 2026-10-16. 260 of the 300 cells were labelled, 20 to 36 per book; the sampling record and the 40 unlabelled cells are in `labels/sampling.json`, and the labels, with the sampling judge's five votes per cell, in `labels/labels.csv`.

The labels come from one rater, so inter-rater agreement has not been measured. A second rater can measure it with the kit. All nine books come from the three August entries; none comes from a later system.

## The judge configurations

Every candidate was run with the same claims, the same nine books, five passes, and the settings below, through the same study driver; each call's model string, parameters, prompt hash, token usage and cost were recorded. No provider returned a dated model snapshot, so the only version pins are the model strings in the table and the run dates (2026-10-16 to 2026-10-20) in `results/configurations.json`.

| Setting | Gemini rows | Claude rows | OpenAI rows |
|---|---|---|---|
| Surface | Gemini API | Amazon Bedrock | Amazon Bedrock |
| Reasoning | thinking level high | effort high | reasoning effort high |
| Temperature | 0 | not accepted by the API | not accepted by the API |
| Output cap, thoughts included | 32,000 tokens | 32,000 tokens | 32,000 tokens |
| JSON output | response MIME type | prompt instruction, brace parser | JSON schema |
| Parse failure | re-asked up to twice, then scored missing | same | same |

The v1 row is different: it is the paper's own judge record from August 2026, five passes with the release settings of the time (default thinking, temperature 0, output cap 10,000), whose votes are in `submissions/<entry>/judge_record_gemini-3-flash-preview.json`.

Prompt lineage, all files in `prompts/` except the selected one, which is the shipped `../prompts/judge_v2_system_prompt.txt`:

| Prompt | What it is |
|---|---|
| v1 | the release prompt: the rubric as four decision rules and a JSON schema |
| V1, V2 | v1 with rule sentences appended, written from the rater's documented standard (`prompts/variants_V1_V2.json`); GPT-6 Luna only |
| V3 | the rules rewritten into the rubric itself |
| V4 | V3 plus structure: list the relevant passages first, quote the passage for every rubric point, verdict computed from the per-point flags |
| V5 | hand-written; introduces the claim's main finding as the thing to rate, verdict from whether the book states it in full, in part or not at all |
| V6, V7, V9, V10 | hand-written variants of V5 (tighter rules; a global rule on reading the book as a map; a taxonomy of point kinds) |
| V5H1 to V5H8, V5R1 to V5R4 | rewrites of V5's rules section by a reflective loop (`reflect_loop.py`, our own script in the style of GEPA and RART: reflect on the disagreement cells, rewrite the rules, keep the best); Claude Sonnet 5.5 as the reflector; the H loop saw its failed rewrites, the R loop did not |
| V5H6 | round 6 of the H loop, the v2 prompt |
| V5RL1 to V5RL6 | the same loop seeded on GPT-6 Luna |
| effortmax | the v1 prompt at the provider's maximum reasoning setting |

## What is in this folder

```
README.md                       this file
labels/                         the human labels and how they were drawn
prompts/                        every prompt in the full table except the shipped v2 prompt; the price table
results/
  votes.csv                     per labelled cell: the human verdict and every configuration's five votes
  configurations.json           per configuration: model string, prompt, settings, run dates, calls, cost, where its outputs are
  table.md, table_full.md       the summary table above and the full table (generated)
  results.json                  every statistic behind the tables (generated)
  paired_bootstrap_*.json       the three pre-registered comparisons
  curated_rows.json             which configurations the summary table shows, and how they are named
outputs/<configuration>/passK.jsonl
                                one record per judge call for the nine candidate rows of the summary table: the parsed JSON the judge
                                returned (passages, per-point quotes, main-finding rating, verdict, justification), the verdict used for
                                scoring, and the call's model id, timestamp, prompt hash, usage, cost and latency; 11,769 records
kit/                            the scripts: compile_table.py, paired_bootstrap.py, analyze.py, build_kit.py, rate_app.py,
                                merge_labels.py, votes_from_scorecards.py
```

Every number in the tables is recomputable from `labels/labels.csv` and `results/votes.csv` alone; the outputs folder shows why each judge call gave the verdict it did. The v1 row's per-call outputs beyond the verdict were not kept in the public record.

## Label your own sample

The kit builds a blind sample from any entries on the leaderboard, serves the books and the claims side by side in the browser, and scores your labels against the judge that produced the entries' records. Thirty cells from two entries is about ninety minutes, most of it reading the two books once.

```bash
python scoring/judges/validation/kit/build_kit.py --out kit_out --entries claude-code-2.1.252 cursor-3.15.6 --n 30 --seed 1
python scoring/judges/validation/kit/rate_app.py --kit kit_out        # open http://127.0.0.1:8795/ and label; every label is saved at once
python scoring/judges/validation/kit/analyze.py --kit kit_out          # when you are done: agreement with the current judge, with a bootstrap CI
```

The kit is blind: books and cells carry opaque codes and the mapping sits in `kit_out/sealed/`, which only `analyze.py` opens. Label with the rubric shown in the app. Pass `--judge-record judge_record_gemini-3-flash-preview.json` to `build_kit.py` to stratify on the v1 judge instead. `merge_labels.py` turns a finished kit into the `labels.csv` schema; if you send us that file in a pull request we will report the agreement between your labels and the published labels on the shared cells. That gives the inter-rater agreement, which has not been measured yet.
