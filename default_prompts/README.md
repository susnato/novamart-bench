# The frozen brief prompts

These prompts guide the agent define the goals, regarding what to extract, analyze and put in the Tribal Book. And gives it a quick introduction about the services and how to access them as well as ask it to only use read only queries to access the state. Identifiers are replaced with placeholders such as `<warehouse-project>`, `<redash-url>`, `<workspace>` .

We recommend using these briefs.


| File                            | Role                                                                  |
| ------------------------------- | --------------------------------------------------------------------- |
| `novamart_sim_launcher.md`      | the kick-off: one line that points the agent at the two context files |
| `novamart_sim_goal_context.md`  | what to find out, phase by phase                                      |
| `novamart_sim_extra_context.md` | how to work: data sources, rules, output format                       |


If you have successfully setup novamart estate, then go to `~/novamart-estate/access-pack/` (the default location; it is wherever you pointed `--estate-dir` otherwise) it has updated `novamart_sim_goal_context.md` and `novamart_sim_extra_context.md`, with updated values for `<warehouse-project>`, `<redash-url>`, `<workspace>` etc. We recommend using them.

In local mode there is no service-account key, so one sentence in `novamart_sim_extra_context.md` is swapped in the rendered copy:


| **BigQuery mode**                                                     | Local mode                                                                                                                                                                                                     |
| --------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| read-only service-account credentials at `<access-pack>/sa-key.json`. | served by a local emulator at [http://localhost:9050](http://localhost:9050) that needs no credentials. Run `source <access-pack>/env.sh` first; `bq` and the client libraries then work with no Google login. |


We recommend running your agent with the rendered prompt; if you use a different prompt and want to submit please include it in your submission and make sure it carries no prior knowledge of the estate. The goal context and everything else in the extra context is identical in both modes.