# Submitting to the leaderboard

Run the three-run protocol (see `docs/evaluation.md`), then open a PR adding a folder under `submissions/` named `<system>-<version>-<YYYYMMDD>/` containing:

1. `book_r1.md`, `book_r2.md`, `book_r3.md`: the three knowledge books, one per run, produced under the unmodified frozen brief (`prompts/`) with read-only access to the estate
2. `metadata.yaml`: see `template/metadata.yaml`

That is the whole submission: **you compute no statistics.** The maintainer re-scores the books with the pinned judge and computes every listed number (runs, mean recall, 95% CI, pass^3) during verification. Self-scoring first with your own judge key (`README.md`, "Scoring your book") is encouraged as a sanity check; the listed numbers are always the verification run's.

Ground rules: the brief must be unmodified, the estate is read-only, and books must be the direct output of the submitted runs. Entries within roughly 10 points of each other are statistically tied (see the statistical notes); the board reports ties as ties.
