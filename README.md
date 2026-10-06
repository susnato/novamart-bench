# NovaMart: A Causally Consistent Simulated Enterprise for Measuring Tribal Knowledge Extraction

[Website](https://novamartbench.com) • [Leaderboard](https://novamartbench.com/#leaderboard) • [Paper](website/paper.pdf) • [Submit](submissions/README.md)

**Paper accepted at the 2nd Workshop on Agentic AI Benchmarks and Applications for Enterprise Tasks (AABA4ET), NeurIPS 2026.**

## 👋 Overview

![The NovaMart pipeline](./website/pipeline.png)

How much of a company's undocumented knowledge can an AI agent excavate from the data estate alone: the code, the git history, the warehouse, the logs, the dashboards?

NovaMart is a simulated e-commerce retailer that is **executed rather than authored**. Real shopper traffic (the public REES46 event stream) is replayed hourly through a live application and database while LLM-powered engineers work through an authored script of incidents, migrations and half-finished fixes against it, on one shared clock, for 3.5 simulated months. We never write the data ourselves: rows, logs, queries and dashboards pile up as a side effect of the work. Then we freeze everything. Agents get read-only access and a single brief: write the company's missing knowledge book. **51 audited gold claims**, each with a recomputable evidence chain, decide how much they found.


| Estate surface                     | Scale                         |
| ---------------------------------- | ----------------------------- |
| Application repo, full git history | 112 commits                   |
| Warehouse tables                   | 32 (plus 3 log export tables) |
| Warehouse rows                     | 878,918                       |
| Runtime + query log lines          | 5,168,645                     |
| Redash dashboards                  | 9                             |
| Simulated history                  | 3.5 months                    |
| Audited gold claims                | 51                            |
| Baseline books from the paper      | 9 (3 systems × 3 runs)        |


Every order and payment traces back to a real browsing session in the replayed REES46 stream. Every claim is re-verifiable against the shipped estate without the generator.

## 📦 What's in this repo


| Path                             | Contents                                                                                                                                                                                                                                                                                                                                         |
| -------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `claims/`                        | the 51 gold claims (YAML): claim text, recomputable evidence chain, scoring rubric                                                                                                                                                                                                                                                               |
| `scoring/`                       | the scoring harness (LLM judge, majority-of-five protocol)                                                                                                                                                                                                                                                                                       |
| `default_prompts/`               | the frozen brief given to every agent, verbatim                                                                                                                                                                                                                                                                                                  |
| `setup/`                         | one-command environment setup: the local docker compose stack (BigQuery emulator, seeded Redash, estate Postgres) and the real-BigQuery loader, plus the access check (`verify_access.py`) and the emulator parity harness (`setup/parity/`)                                                                                                     |
| `submissions/`                   | everything the leaderboard is built from: one folder per entry (baselines included) with its books, `judge_record.json` (the raw five-pass judge record, all four verdict labels), `verified_verdicts.json` (the majority verdicts) and `verified_entry.json` (the entry's statistics); plus the submission template and the verification script |
| `website/`                       | source of the benchmark website                                                                                                                                                                                                                                                                                                                  |
| `docs/`                          | setup guides, the evaluation protocol and statistical notes, the provenance record, and the baselines claim matrix                                                                                                                                                                                                                               |
| `reproduce_figures_tables.ipynb` | reproduces the paper's tables from the per-entry judge records                                                                                                                                                                                                                                                                                   |


The estate itself is not in this repo. The warehouse fixtures, database dump, log exports and Redash export live in a versioned Hugging Face dataset, and the application repo with its full git history is its own GitHub repo (`novamart-sim/novamart`). The setup scripts pull both; see [Setup](#%EF%B8%8F-setup). That keeps this repo small enough to clone in a few seconds.

## 🏗️ The access surface

Agents reach the estate through the same interfaces enterprise data actually lives behind:

- **BigQuery API** over three datasets: `novamart` (application tables), `novamart_analytics` (analytics tables and views), `novamart_logs` (log exports, including the query log)
- **git** over the application repo
- **Redash** for dashboards



## ⚙️ Setup

Once Python, Docker and git are installed, the local setup is one command and takes about 10 minutes end to end on a laptop; we measured 8 minutes on a fresh 4-CPU, 8 GB machine, Docker image pulls included. Nothing needs attention while it runs.



### Before you start

Both modes need the same tools. Make sure you have them installed, otherwise follow their official pages to install them:


| Tool                                 | Where are they used                                                                                                                                                                                                        | Install                                                                                |
| ------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| Python 3.10 or newer                 | the setup, verify and scoring scripts                                                                                                                                                                                      | [https://www.python.org/downloads/](https://www.python.org/downloads/)                 |
| Docker with the compose plugin       | Redash, the estate Postgres, and in local mode the BigQuery emulator                                                                                                                                                       | [https://docs.docker.com/get-docker/](https://docs.docker.com/get-docker/)             |
| git                                  | clones the application repo at the pinned commit                                                                                                                                                                           | [https://git-scm.com/downloads](https://git-scm.com/downloads)                         |
| Google Cloud SDK (`gcloud` and `bq`) | `bq` is what the baseline agents used to query the warehouse; `~/novamart-estate/access-pack/env.sh` makes it work against the local emulator with no Google login. `gcloud` itself is needed only for cloud-bigquery mode | [https://cloud.google.com/sdk/docs/install](https://cloud.google.com/sdk/docs/install) |


Then, from the repo root, install the Python packages every script uses (the Hugging Face download, the BigQuery client, the judge client, the CLI):

```bash
pip install -r setup/requirements.txt
```

A virtual environment is a good idea but not required.

**Local (recommended)**: See [`docs/setup_local.md`](docs/setup_local.md) for full guide, `python setup/setup_local.py` sets up everything with docker compose: [bqemulator](https://github.com/jjviscomi/bqemulator) serving the BigQuery API, loaded with all tables and views in project `novamart-warehouse`, a seeded Redash with the dashboards and the estate Postgres. The application repo is cloned and checked out at the commit hash. Both the repo checkout and the access pack are written to `~/novamart-estate/` by default (outside this repo, so your agent never sees the ground truth claims); pass `--estate-dir` to put them elsewhere. You need to run `source ~/novamart-estate/access-pack/env.sh` which points `bq` and the BQ client libraries at the local emulator rather than hitting googles bq server, `bq` then works without Google login.

**Real BigQuery (**`cloud-bigquery` **mode)**: See [`docs/setup_cloud_bigquery.md`](docs/setup_cloud_bigquery.md) for full guide, `python setup/setup_gcp.py --project your-project-id` loads the novamart datasets into your own BigQuery project (permission is checked first, `roles/bigquery.user` is needed for this operation), then run `python setup/setup_local.py --warehouse-project your-project-id --no-download` brings up Redash and the repo locally. if you are setting this up then all costs related to BQ call are billed to your gcp project billing account. Submissions disclose which mode produced the runs.

After setting up, you can call `setup/verify_access.py` which verifies all access and the access pack is setup by the setup command which writes the needed files such as `~/novamart-estate/access-pack/env.sh`, `rendered_novamart_sim_extra_context.md` etc to make your local setup ready to start running your agent on novamart estate.

## 🚀 Run your agent

If you have successfully setup novamart estate then you should see a root folder in HOME directory (or to preferred one if you passed `--estate-dir`) and two subdirectories, `<estate-dir>/workspace/` and `<estate-dir>/access-pack/`. The first one holds the checked out repo and the second one holds the files for connecting your agent to the estate: warehouse project, Redash URL and API key, workspace path etc and rendered copies of the prompts with those placeholders filled and a `env.sh` file that points bq and the BigQuery client libraries at the warehouse, and a short README.

**To run your agent first source the** `env.sh` **from the access pack in the same terminal you will run your agent in and then run your agent on Novamart estate!**

(We recommend running your agent with the rendered brief from the pack; if you use a different prompt, include it in your submission and make sure it carries no knowledge of the estate)

```bash
# source 
source ~/novamart-estate/access-pack/env.sh

# check to make sure the bq command works
bq ls

# OUTPUT
#      datasetId       
# -------------------- 
#  novamart            
#  novamart_analytics  
#  novamart_logs      

# Run your agent from the same terminal
your-agent run --prompt-filepath "~/novamart-estate/access-pack/rendered_novamart_sim_launcher.md"
```



## 📊 Scoring your agent's generated book

See [`docs/evaluation.md`](docs/evaluation.md) for the full protocol, metric definitions, and the other notes.

We use `gemini-3-flash-preview` model for the LLM Judge, the judge needs Gemini credentials: either `GEMINI_API_KEY`, or Vertex AI via `VERTEX_AI_PROJECT_ID` with gcloud application-default credentials. From the repo root:

```bash
# make sure claims are in valid format
python -m scoring.cli validate-claims-format claims

# one book: per-claim scorecard, recall, 95% CI
python -m scoring.cli score-book --gold claims --book book_r1.md

# your three runs: mean recall, 95% CI, pass^3 (repeat --book per book)
python -m scoring.cli score-book --gold claims --book book_r1.md --book book_r2.md --book book_r3.md

# optional: majority verdicts over multiple judge passes per book
python -m scoring.cli score-book --gold claims --book book_r1.md --judge-passes 3
```



## 🏆 Leaderboard and submissions

The leaderboard at [https://novamartbench.com](https://novamartbench.com) is generated from [`website/leaderboard.json`](website/leaderboard.json). To submit: run your agent on the estate three times with the [released brief](default_prompts/), then open a PR adding your three books, a metadata file, and your system's own prompts (if any) under `submissions/`. We recommend the rendered brief; if you use a different prompt, include it in your submission and make sure it carries no knowledge of the estate. Please don't worry about computing any statistics: the maintainer re-runs the judge on every submitted book and computes all listed numbers during verification, so every entry on the board is scored the same way. See [`submissions/README.md`](submissions/README.md).

## 🔎 Verification and provenance

Every number in this repo is recomputable: books are scored against the released claims, verdicts are released per claim-book cell, and evidence SQL runs against the shipped estate.

During release preparation a single internal infrastructure identifier was renamed across the world repo and the distributed fixtures, which re-hashed the six final world commits (the released books cite the original hashes). The full record, including the commit hash map, every field updated, and an evidence SQL fix, is in [`docs/provenance.md`](docs/provenance.md). It is an artifact naming change and does not alter the benchmark's content.

## 📄 Licenses and attribution

Code is Apache-2.0 (`LICENSE`). The estate (the Hugging Face dataset and the `novamart-sim/novamart` application repo with its full git history), the claims, books, results, the paper, and the website are CC BY 4.0 (`LICENSE-DATA`). The application repo is additionally available under Apache-2.0 for use as software (SPDX: `Apache-2.0 OR CC-BY-4.0`); it carries no LICENSE file of its own because its git history is the benchmark artifact. Ambient shopper traffic is replayed from the REES46 eCommerce behavior dataset ([https://www.kaggle.com/datasets/mkechinov/ecommerce-behavior-data-from-multi-category-store](https://www.kaggle.com/datasets/mkechinov/ecommerce-behavior-data-from-multi-category-store), provided by the REES46 Marketing Platform, [https://rees46.com](https://rees46.com)), a designated attribution party; see [`ATTRIBUTION.md`](ATTRIBUTION.md).

## Citation

```bibtex
@inproceedings{dhar2026novamart,
  title     = {NovaMart: A Causally Consistent Simulated Enterprise
               for Measuring Tribal Knowledge Extraction},
  author    = {Dhar, Susnato and Saket, Srijan and Mehrotra, Rishabh},
  booktitle = {2nd Workshop on Agentic AI Benchmarks and Applications
               for Enterprise Tasks (AABA4ET), NeurIPS 2026},
  year      = {2026},
  url       = {https://novamartbench.com}
}
```

Maintained by [@susnato](https://github.com/susnato). Questions: please open an issue; or email [susnatodhar10@gmail.com](mailto:susnatodhar10@gmail.com).