# NovaMart

**A causally consistent simulated enterprise for measuring tribal knowledge extraction.**

How much of a company's undocumented knowledge can an AI agent excavate from the data estate alone: the code, the git history, the warehouse, the logs, the dashboards? NovaMart is a simulated e-commerce retailer that is executed rather than authored: real shopper traffic (the public REES46 event stream) is replayed through a live application and database while LLM-powered engineers act out an authored script of incidents, migrations, and half-finished fixes. Everything a company accumulates builds up as a side effect, then the estate is frozen. Agents get read-only access and a single brief: write the company's missing knowledge book. 51 audited gold claims, each with a recomputable evidence chain, decide how much they found.

Website and leaderboard: https://novamart-bench.github.io &middot; Paper: arXiv link coming at release.

## What's in this repo

| Path | Contents |
|---|---|
| `claims/` | the 51 gold claims (YAML), each with claim text, evidence chain (recomputable SQL or source references), and scoring rubric |
| `harness/` | the scoring harness (LLM judge, majority-of-five protocol) |
| `books/` | the 9 released baseline knowledge books (3 systems x 3 runs) |
| `results/` | released verdicts for every claim-book cell, plus the claim matrix |
| `prompts/` | the frozen brief given to every agent, verbatim |
| `schemas/` | claim schema |
| `novamart_estate_samples/` | small head samples of every estate surface (the full estate ships as a release asset) |
| `submissions/` | leaderboard submission format and template |
| `website/` | source of the benchmark website |
| `docs/` | evaluation protocol and statistical notes |
| `reproduce_figures_tables.ipynb` | reproduces the paper's tables from `results/` |

## The estate

The full frozen estate is distributed as a release asset (see Releases): the application repo with full git history (108 commits), the warehouse dump (32 tables, 878,918 rows), runtime and query logs (5,168,645 lines), and the Redash dashboard export. Every order and payment traces back to a real browsing session in the replayed REES46 stream; every claim is re-verifiable against the shipped estate without the generator.

Agents access the estate through the same interfaces enterprise data actually lives behind:

- **BigQuery API** over three datasets: `novamart` (application tables), `novamart_analytics` (analytics tables and views), `novamart_logs` (log exports, including the query log)
- **git** over the application repo
- **Redash** for dashboards

## Setup

### Local (docker compose)

Status: tooling lands in an upcoming commit; tracked in the repo issues. The stack is three containers, all API-faithful: the BigQuery emulator ([goccy/bigquery-emulator](https://github.com/goccy/bigquery-emulator)) preloaded with the three datasets, a seeded Redash instance, and the application repo mounted read-only. Your agent uses the standard `google-cloud-bigquery` client with an endpoint override; the SQL dialect is identical to the cloud setup.

### GCP (official mode, matches the released baselines)

Status: the public BigQuery datasets go live with the full release. The three datasets are hosted as public BigQuery datasets; queries bill to your own GCP project (requester pays, pennies at this scale). This mode uses the real BigQuery API and is the reference environment for leaderboard entries.

## Evaluation

Each system runs as shipped, zero-shot, **three times** under the same frozen brief (`prompts/`), with read-only access to the estate. Each run produces one knowledge book. See `docs/evaluation.md` for the full protocol, metric definitions, and statistical notes (what score differences this benchmark can and cannot resolve).

## Scoring your book

The judge needs a Gemini API key (`GEMINI_API_KEY`). From the repo root:

```bash
pip install click pyyaml jsonschema google-genai
mkdir -p novamart/gold && cp -r claims novamart/gold/claims
python -m harness.cli validate-claims-format novamart
python -m harness.cli score-book --gold novamart --book books/cc_r1.md
```

Replace `books/cc_r1.md` with your own book. `harness/README.md` documents options, judge pinning, and the five-pass majority protocol. Scoring is per claim against the rubric; recall is the fraction of the 51 claims satisfied.

## Leaderboard

The leaderboard lives at https://novamart-bench.github.io and is generated from [`leaderboard.json`](leaderboard.json). To submit: run the three-run protocol and open a PR adding a folder under `submissions/` with your three books and a metadata file; you compute no statistics. The maintainer re-scores every submission with the pinned judge and computes all listed numbers (runs, mean recall, 95% CI, pass^3) during verification. See `submissions/README.md`.

## Licenses, attribution, citation

Code is Apache-2.0 (`LICENSE`). The estate, claims, books, and results are CC BY 4.0 (`LICENSE-DATA`). Ambient shopper traffic is replayed from the REES46 eCommerce behavior dataset; see `ATTRIBUTION.md`. To cite the benchmark, see `CITATION.cff` (bibtex on the website).

Note: `<warehouse-project>` placeholders in claims and books resolve to the public BigQuery project at release.

Maintained by [@susnato](https://github.com/susnato).
