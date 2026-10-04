# The frozen brief prompts

These prompts guide the agent define the goals, regarding what to extract, analyze and put in the Tribal Book. And gives it a quick introduction about the services and how to access them as well as ask it to only use read only queries to access the state. Identifiers are replaced with placeholders such as `<warehouse-project>`, `<redash-url>`, `<workspace>` .

We recommend using these briefs.


| File                            | Role                                                                  |
| ------------------------------- | --------------------------------------------------------------------- |
| `novamart_sim_launcher.md`      | the kick-off: one line that points the agent at the two context files |
| `novamart_sim_goal_context.md`  | what to find out, phase by phase                                      |
| `novamart_sim_extra_context.md` | how to work: data sources, rules, output format                       |


If you have successfully setup novamart estate, then go to `~/novamart-estate/access-pack/` (the default location; it is wherever you pointed `--estate-dir` otherwise) it has updated `novamart_sim_goal_context.md` and `novamart_sim_extra_context.md`, with updated values for `<warehouse-project>`, `<redash-url>`, `<workspace>` etc. We recommend using them.

The rendered copies are the released text with the placeholders filled in. In `cloud-bigquery` mode that is all that changes. In local mode there is no service-account key and no GitHub token, so three sentences in `novamart_sim_extra_context.md` are swapped in the rendered copy (the files in this folder are never modified):

| Released text | Local rendering |
|---|---|
| A read-only GitHub token (org `<github-org>`) is stored at `<access-pack>/agent-github-pat` if you need remote git operations. | The repo is public and already checked out; `git log` works offline and no GitHub token is needed. |
| read-only service-account credentials at `<access-pack>/sa-key.json`. | served by a local emulator at http://localhost:9050 that needs no credentials. Run `source <access-pack>/env.sh` first; `bq` and the client libraries then work with no Google login. |
| Do not modify the repository or push via the GitHub token. | Do not modify the repository or push to GitHub. |

We recommend running your agent with the rendered brief; if you use a different prompt, include it in your submission and make sure it carries no knowledge of the estate. The goal context and everything else in the extra context is identical in both modes.
