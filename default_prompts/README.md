# The frozen brief prompts

These prompts guide the agent define the goals, regarding what to extract, analyze and put in the Tribal Book. And gives it a quick introduction about the services and how to access them as well as ask it to only use read only queries to access the state. Identifiers are replaced with placeholders such as `<warehouse-project>`, `<redash-url>`, `<workspace>` .

We recommend using these briefs.


| File                            | Role                                                                  |
| ------------------------------- | --------------------------------------------------------------------- |
| `novamart_sim_launcher.md`      | the kick-off: one line that points the agent at the two context files |
| `novamart_sim_goal_context.md`  | what to find out, phase by phase                                      |
| `novamart_sim_extra_context.md` | how to work: data sources, rules, output format                       |


If you have successfully setup novamart estate, then go to `~/novamart-estate/access-pack/` (the default location; it is wherever you pointed `--estate-dir` otherwise) it has updated `novamart_sim_goal_context.md` and `novamart_sim_extra_context.md`, with updated values for `<warehouse-project>`, `<redash-url>`, `<workspace>` etc. We recommend using them.

In local mode there is no service-account key, so one sentence in `novamart_sim_extra_context.md` is swapped in the rendered copy (the files in this folder are never modified):

| Released text | Local rendering |
|---|---|
| read-only service-account credentials at `<access-pack>/sa-key.json`. | served by a local emulator at http://localhost:9050 that needs no credentials. Run `source <access-pack>/env.sh` first; `bq` and the client libraries then work with no Google login. |

The GitHub sentence is the same in both modes: the repo is public and checked out locally, and `<access-pack>/agent-github-pat` exists in both modes, empty by default (no token needed; put a read-only PAT of your own in it only if your agent needs the GitHub API).

We recommend running your agent with the rendered brief; if you use a different prompt, include it in your submission and make sure it carries no knowledge of the estate. The goal context and everything else in the extra context is identical in both modes.