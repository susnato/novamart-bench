# NovaMart: A Causally Consistent Simulated Enterprise for Measuring Tribal Knowledge Extraction

<p align="center">
  <a href="https://novamart-bench.github.io">Website</a> •
  <a href="https://novamart-bench.github.io">Leaderboard</a> •
  <a href="#citation">Paper</a> •
  <a href="submissions/README.md">Submit</a>
</p>

## 👋 Overview

![The NovaMart pipeline](./website/pipeline.png)

How much of a company's undocumented knowledge can an AI agent excavate from the data estate alone: the code, the git history, the warehouse, the logs, the dashboards?

NovaMart is a simulated e-commerce retailer that is **executed rather than authored**. Real shopper traffic (the public REES46 event stream) is replayed through a live application and database while LLM-powered engineers act out an authored script of incidents, migrations, and half-finished fixes. Everything a company accumulates builds up as a side effect, then the estate is frozen. Agents get read-only access and a single brief: write the company's missing knowledge book. **51 audited gold claims**, each with a recomputable evidence chain, decide how much they found.

| Estate surface | Scale |
|---|---|
| Application repo, full git history | 112 commits |
| Warehouse tables | 32 |
| Warehouse rows | 878,918 |
| Runtime + query log lines | 5,168,645 |
| Redash dashboards | 9 |
| Simulated history | 3.5 months |
| Audited gold claims | 51 |
| Released baseline books | 9 (3 systems × 3 runs) |

Every order and payment traces back to a real browsing session in the replayed REES46 stream. Every claim is re-verifiable against the shipped estate without the generator.

## 📦 What's in this repo

| Path | Contents |
|---|---|
| `claims/` | the 51 gold claims (YAML): claim text, recomputable evidence chain, scoring rubric |
| `scoring/` | the scoring harness (pinned LLM judge, majority-of-five protocol) |
| `default_prompts/` | the frozen brief given to every agent, verbatim |
| `setup/` | one-command environment setup: the local docker compose stack (BigQuery emulator, seeded Redash, estate Postgres) and the GCP loader, plus the emulator parity harness (`setup/parity/`) |
| `submissions/` | the canonical home of everything leaderboard: entries (baselines included) each carrying books, `judge_record.json` (the raw five-pass judge record, all four verdict labels), `verified_verdicts.json` (derived majorities), and `verified_entry.json` (stats); plus the template and the verification script |
| `website/` | source of the benchmark website |
| `docs/` | setup guides, the evaluation protocol and statistical notes, the provenance record, and the baselines claim matrix |
| `reproduce_figures_tables.ipynb` | reproduces the paper's tables from the per-entry judge records |

The **full frozen estate** (repo bundle, warehouse dump, logs, Redash export) is distributed separately as a versioned dataset; see [Setup](#%EF%B8%8F-setup). This repo stays small on purpose.

## 🏗️ The access surface

Agents reach the estate through the same interfaces enterprise data actually lives behind:

- **BigQuery API** over three datasets: `novamart` (application tables), `novamart_analytics` (analytics tables and views), `novamart_logs` (log exports, including the query log)
- **git** over the application repo
- **Redash** for dashboards

## ⚙️ Setup

**Local (recommended)**: `python setup/setup_local.py` stands up everything with docker compose: [bqemulator](https://github.com/jjviscomi/bqemulator) serving the BigQuery API, loaded with all 35 tables and the 5 estate views (project `novamart-warehouse`, matching the in-world docs), a seeded Redash with the 9 dashboards, the estate Postgres they query, the application repo checked out at the pin, and your access pack. See [`docs/setup_local.md`](docs/setup_local.md).

**GCP**: `python setup/setup_gcp.py --project your-project-id` loads the three datasets into your own BigQuery project (permission preflight first, nothing created on failure; `roles/bigquery.user` suffices). Agents then use the real BigQuery API at your own scale and cost. Submissions disclose which mode produced the runs. See [`docs/setup_gcp.md`](docs/setup_gcp.md).

## 🧪 Evaluation

Each system runs as shipped, zero-shot, **three times** under the same frozen brief (`default_prompts/`), with read-only access to the full estate; each run produces one knowledge book. Books are scored per claim by a pinned LLM judge against the claim's rubric, majority over five independent passes. Headline metrics: **mean claim recall** over the three runs and **pass³** (claims solved in all three runs), with claim-level bootstrap 95% CIs.

See [`docs/evaluation.md`](docs/evaluation.md) for the full protocol, metric definitions, and the statistical notes: what score differences this benchmark can and cannot resolve.

## Scoring your book

The judge needs Gemini credentials: either `GEMINI_API_KEY`, or Vertex AI via `VERTEX_AI_PROJECT_ID` with gcloud application-default credentials. From the repo root:

```bash
pip install -r setup/requirements.txt
mkdir -p novamart/gold && cp -r claims novamart/gold/claims
python -m scoring.cli validate-claims-format novamart

# one book: per-claim scorecard, recall, 95% CI
python -m scoring.cli score-book --gold novamart --book book_r1.md

# your three runs: mean recall, 95% CI, pass^3, pass@3 (repeat --book per book)
python -m scoring.cli score-book --gold novamart --book book_r1.md --book book_r2.md --book book_r3.md

# optional: majority verdicts over multiple judge passes per book
python -m scoring.cli score-book --gold novamart --book book_r1.md --judge-passes 3
```

The summary uses the exact statistics code the maintainer's verifier runs, so your self-scored numbers and the verified listing are the same math; they are still unofficial until verification. `scoring/README.md` documents options, judge pinning, and the five-pass majority protocol.

## 🏆 Leaderboard and submissions

The leaderboard at https://novamart-bench.github.io is generated from [`website/leaderboard.json`](website/leaderboard.json). To submit: run the three-run protocol, then open a PR adding your three books and a metadata file under `submissions/`. Please don't worry about computing any statistics: the verifier (the maintainer of this repo) re-runs the pinned judge on every submitted book and computes all listed numbers during verification, so every entry on the board is scored the same way. See [`submissions/README.md`](submissions/README.md).

## 🔎 Verification and provenance

Every number in this repo is recomputable: books are scored against the released claims, verdicts are released per claim-book cell, and evidence SQL runs against the shipped estate.

During release preparation a single internal infrastructure identifier was renamed across the world repo and the distributed fixtures, which re-hashed the six final world commits (the released books cite the original hashes). The full record, including the commit hash map, every field updated, and an evidence SQL fix, is in [`docs/provenance.md`](docs/provenance.md). It is an artifact naming change and does not alter the benchmark's content.

## 📄 Licenses and attribution

Code is Apache-2.0 (`LICENSE`). The estate, claims, books, and results are CC BY 4.0 (`LICENSE-DATA`). Ambient shopper traffic is replayed from the REES46 eCommerce behavior dataset; see [`ATTRIBUTION.md`](ATTRIBUTION.md).

## Citation

```bibtex
@article{novamart2026,
  title   = {NovaMart: A Causally Consistent Simulated Enterprise
             for Measuring Tribal Knowledge Extraction},
  author  = {<authors, added at release>},
  journal = {arXiv preprint arXiv:26XX.XXXXX},
  year    = {2026}
}
```

Maintained by [@susnato](https://github.com/susnato). Questions: please open an issue; or email [susnatodhar10@gmail.com](mailto:susnatodhar10@gmail.com).
