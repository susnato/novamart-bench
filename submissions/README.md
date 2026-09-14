# Submitting to the leaderboard

## Tracks

| Track | Prompts | Listing |
|---|---|---|
| 1. Frozen brief (default) | the released brief in `prompts/`, byte-unmodified | headline ranking, directly comparable to the released baselines |
| 2. Custom scaffold | your own prompts / scaffold | listed with a marker, outside the headline ranking |

Both tracks bind to the task contract: read-only estate, the released access surface unmodified, one knowledge book per run, and **no gold-claim content anywhere in your prompts or scaffold**.

## What a submission contains

Open a PR adding a folder `submissions/<system>-<version>-<YYYYMMDD>/` containing, for the three runs:

1. **Books (required)**: `book_r1.md`, `book_r2.md`, `book_r3.md`, each the direct output of its run.
2. **Prompts (required)**: Track 1 attests in `metadata.yaml` that the released brief was used unmodified. Track 2 includes the complete prompt/scaffold text actually used: `prompt.md`, or `prompt_r1.md` / `prompt_r2.md` / `prompt_r3.md` if it varied across runs.
3. **Trajectories (optional, encouraged)**: `trajectories/` with the agent transcript and tool calls per run, any textual format.
4. **Metadata (required)**: `metadata.yaml`, see [`template/metadata.yaml`](template/metadata.yaml).

You compute no statistics: the maintainer re-scores the books with the pinned judge and computes every listed number (runs, mean recall, 95% CI, pass^3) during verification. Self-scoring first with your own judge key is encouraged as a sanity check; the listed numbers are always the verification run's.

Custom prompts are reviewed for gold-claim leakage during verification; submissions with undisclosed prompts are not listed. Entries within roughly 10 points of each other are statistically tied; the board reports ties as ties.
