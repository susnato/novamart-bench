Execute this task as mentioned at `/home/susnato/lb/runs/claude-opus-5-5/r1/access-pack/rendered_novamart_sim_goal_context.md`. MUST follow the extra context at `/home/susnato/lb/runs/claude-opus-5-5/r1/access-pack/rendered_novamart_sim_extra_context.md`
DO NOT deviate from the task and follow it line by line as mentioned in the doc.


The two documents named above are reproduced here in full.

===== rendered_novamart_sim_goal_context.md =====
# Novamart Tribal Knowledge Goal Context

## Goal

Accomplish the following end goals:

### Phase 1: Understand how the business numbers are actually produced

- Understand how novamart computes its core financial numbers end to end: orders, payments, refunds, monthly revenue, and the finance statements.
- Identify which tables, jobs, and dashboards are treated as the source of truth for each number, and how the definitions have changed over the company's history.
- Final Goal: Be able to answer "what was revenue in a given month, and why" the way a tenured finance/data person at the company would.

### Phase 2: Understand product and customer analytics

- Understand how product performance is reported: best sellers, brand and category revenue, and the assumptions baked into those reports.
- Understand how the company counts its customers: signups, active customers, and any other customer segments in use — and which definition each consumer (dashboards, jobs, leadership reporting) actually uses.
- Final Goal: Be able to explain any number on the company's dashboards, including when a dashboard's number should not be trusted at face value.

### Phase 3: Understand the ML systems and scheduled jobs

- Understand any machine-learning or recommendation systems the company runs: how their outputs are produced, served, and logged, and how they have evolved across versions.
- Understand the scheduled batch jobs: what each one produces, what breaks when they fail, and how their outputs feed reporting and serving.
- Final Goal: Be able to judge whether the company's ML systems actually work, and to safely modify or extend the batch pipelines.

## Tribal Knowledge Requirement

The tribal knowledge document should be comprehensive enough to support executing these goals.
===== rendered_novamart_sim_extra_context.md =====
# Novamart Extra Context

## Task

[TASKID: novamart] You are a senior software engineer and your task is to help me understand the tribal knowledge from my company's systems: the codebase, the data warehouse, and the dashboards.

## Data Sources

- Codebase: GitHub, repo cloned and checked out at `/home/susnato/lb/runs/claude-opus-5-5/r1/workspace/novamart` (pinned at commit `5ae1182`); you must only use this repo. A read-only GitHub token (org `novamart-sim`) is stored at `/home/susnato/lb/runs/claude-opus-5-5/r1/access-pack/agent-github-pat` if you need remote git operations.
- Data Warehouse: BigQuery, GCP project `novamart-warehouse`, served by a local emulator at http://localhost:9054 that needs no credentials. Run `source /home/susnato/lb/runs/claude-opus-5-5/r1/access-pack/env.sh` first; `bq` and the client libraries then work with no Google login. Datasets: `novamart` (app tables), `novamart_analytics` (analytics tables + views), `novamart_logs` (log exports, including the historical query log `db_queries`).
- Dashboards: Redash, available at `http://localhost:5054` (read-only). Credentials and API key are stored at `/home/susnato/lb/runs/claude-opus-5-5/r1/access-pack/redash-agent-creds`.

## Instructions

Your understanding MUST only come from the searching and understanding you do on the fly and not using any external knowledge you find in the machine.

Starting: When starting this exercise you must print starting time in wall clock time and then print a random uuid string.

## Don'ts

- DO NOT MUTATE OR DELETE ANY DATA anywhere. Run SELECT and other read-only queries only. Do not create, edit, archive, or refresh anything in Redash.
- Do not modify the repository or push via the GitHub token.

## Output

- Output MUST be in a single markdown file.
- It is a MUST thing that the output surfaces these 8 pillars on top, in this numbered order. Extra detail lives in an appendix.
  1. Summary
  2. Why this project
  3. Business understanding
  4. Metrics
  5. System
  6. Data
  7. Experimentation
  8. Glossary
- Every claim in the document must cite its evidence: a commit hash, table/view name, query, log line, or dashboard.
- All outputs and intermediate outputs MUST and only be stored in the sub-directory: create a sub-directory named with the uuid you printed at start and dump everything there, including the final markdown file.

## Time Limit

You don't have any time limit on it, take as much time as needed.