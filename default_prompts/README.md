# The frozen brief prompts

These prompts guide the agent define the goals, regarding what to extract, analyze and put in the Tribal Book. And gives it a quick introduction about the services and how to access them as well as ask it to only use read only queries to access the state. Identifiers are replaced with placeholders such as `<warehouse-project>`, `<redash-url>`, `<workspace>` .

We recommend using these briefs.


| File                            | Role                                                                  |
| ------------------------------- | --------------------------------------------------------------------- |
| `novamart_sim_launcher.md`      | the kick-off: one line that points the agent at the two context files |
| `novamart_sim_goal_context.md`  | what to find out, phase by phase                                      |
| `novamart_sim_extra_context.md` | how to work: data sources, rules, output format                       |


If you have successfully setup novamart estate, then go to `~/novamart-estate/access-pack/` (the default location; it is wherever you pointed `--estate-dir` otherwise) it has updated `novamart_sim_goal_context.md` and `novamart_sim_extra_context.md`, with updated values for `<warehouse-project>`, `<redash-url>`, `<workspace>` etc. We recommend using them.