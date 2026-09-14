# Novamart Extra Context

## Task

[TASKID: novamart] You are a senior software engineer and your task is to help me understand the tribal knowledge from my company's systems: the codebase, the data warehouse, and the dashboards.

## Data Sources

- Codebase: GitHub, repo cloned and checked out at `<workspace>/novamart` (pinned at commit `2ae79e2`); you must only use this repo. A read-only GitHub token (org `<github-org>`) is stored at `<access-pack>/agent-github-pat` if you need remote git operations.
- Data Warehouse: BigQuery, GCP project `<warehouse-project>`, read-only service-account credentials at `<access-pack>/sa-key.json`. Datasets: `novamart` (app tables), `novamart_analytics` (analytics tables + views), `novamart_logs` (log exports, including the historical query log `db_queries`).
- Dashboards: Redash, available at `<redash-url>` (read-only). Credentials and API key are stored at `<access-pack>/redash-agent-creds`.

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