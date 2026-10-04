from __future__ import annotations

from datetime import datetime
from pathlib import Path

import sys

import click

from scoring.loaders import load_claims, load_book, resolve_claims_dir
from scoring.judges.composite import evaluate_all_claims
from scoring.judges.llm_judge import DEFAULT_MODEL, JudgeAPIError
from scoring.scoring import compute_scorecard
from scoring.report import write_scorecard
from scoring.stats import majority, stats


@click.command("score-book")
@click.option("--gold", required=True, type=click.Path(exists=True), help="Gold claims: the directory holding the claim YAMLs (claims/ in this repo), or a <benchmark>/gold/claims layout")
@click.option("--book", "books", required=True, multiple=True, type=click.Path(exists=True),
              help="Path to a markdown book under test; repeat for multiple books (the leaderboard protocol uses 3)")
@click.option("--judge-passes", default=1, type=int,
              help="Judge passes per book; a book's verdicts are the majority across passes (ties to the worse verdict)")
@click.option("--judge-model", default=DEFAULT_MODEL, help="Model for LLM judge")
@click.option("--workers", default=10, type=int, help="Parallel workers for LLM judge calls")
@click.option("--output-dir", default=None, help="Custom output directory for scorecard (single book, single pass only)")
@click.option("--yes", is_flag=True, help="Skip the confirmation prompt shown for more than 3 books")
@click.option(
    "--use-must-include-fields/--ignore-must-include-fields",
    default=True,
    help="Whether to include match.must_include fields in the LLM judge prompt.",
)
def run(
    gold: str,
    books: tuple[str, ...],
    judge_passes: int,
    judge_model: str,
    workers: int,
    output_dir: str | None,
    yes: bool,
    use_must_include_fields: bool,
) -> None:
    """Evaluate one or more tribal knowledge books against a gold claim suite."""
    gold_path = Path(gold)
    book_paths = [Path(b) for b in books]
    single = len(book_paths) == 1 and judge_passes == 1
    if judge_passes < 1:
        raise click.UsageError("--judge-passes must be >= 1")
    if output_dir is not None and not single:
        raise click.UsageError("--output-dir only applies to a single book with a single judge pass")

    claims_dir, bench_root = resolve_claims_dir(gold_path)
    click.echo(f"Loading claims from {claims_dir} ...")
    claims = load_claims(gold_path)
    click.echo(f"Loaded {len(claims)} claims, {len(book_paths)} book(s), {judge_passes} judge pass(es) per book")
    click.echo(f"Judge model: {judge_model} (workers={workers})")
    click.echo(f"Use must_include fields: {use_must_include_fields}")

    if len(book_paths) > 3 and not yes:
        total_calls = len(claims) * len(book_paths) * judge_passes
        click.confirm(
            f"{len(book_paths)} books x {judge_passes} judge pass(es) = {total_calls} judge calls; "
            f"the leaderboard protocol needs at most 3 books. Continue?", abort=True)

    per_book_solved, per_book_recall = [], []
    for book_path in book_paths:
        book_text = load_book(book_path)
        pass_verdicts = []
        for p in range(judge_passes):
            try:
                claim_results = evaluate_all_claims(
                    claims,
                    book_text,
                    model=judge_model,
                    max_workers=workers,
                    use_must_include_fields=use_must_include_fields,
                )
            except JudgeAPIError as exc:
                click.echo(f"\nJUDGE FAILED on {book_path.name} pass {p + 1}: {exc}", err=True)
                click.echo("No scorecard was written for this pass and nothing was scored. Fix the credentials "
                           "(GEMINI_API_KEY or VERTEX_AI_PROJECT_ID) or wait for the quota, then re-run.", err=True)
                sys.exit(2)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            metadata = {
                "benchmark": bench_root.resolve().name,
                "book": book_path.stem,
                "book_path": str(book_path),
                "timestamp": timestamp,
                "judge_model": judge_model,
                "use_must_include_fields": use_must_include_fields,
            }
            scorecard = compute_scorecard(claim_results, claims, metadata)
            if output_dir is not None:
                out = Path(output_dir)
            elif single:
                out = bench_root / "eval-run-outputs" / f"{book_path.stem}_{timestamp}"
            else:
                out = bench_root / "eval-run-outputs" / f"{book_path.stem}_{timestamp}_p{p + 1}"
            json_path, md_path = write_scorecard(scorecard, out)
            pass_verdicts.append({c["claim_id"]: c["verdict"] for c in scorecard["claim_results"]})
            if single:
                _echo_scorecard(scorecard, json_path, md_path)
            else:
                click.echo(f"  {book_path.name} pass {p + 1}/{judge_passes}: "
                           f"recall {scorecard['claim_recall'] * 100:.1f}% ({json_path})")
        cids = sorted(pass_verdicts[0])
        solved = {cid: majority([pv[cid] for pv in pass_verdicts]) == "correct" for cid in cids}
        per_book_solved.append(solved)
        per_book_recall.append(100.0 * sum(solved.values()) / len(cids))

    k = len(book_paths)
    matrix = {cid: [b[cid] for b in per_book_solved] for cid in per_book_solved[0]}
    agg = stats(matrix, runs=k)
    click.echo("")
    click.echo("═" * 60)
    click.echo(f"  SELF-SCORED SUMMARY ({k} book(s), {judge_passes} judge pass(es) per book)")
    click.echo("═" * 60)
    for bp, r in zip(book_paths, per_book_recall):
        click.echo(f"  {bp.name}: recall {r:.1f}%" + (" (majority verdicts)" if judge_passes > 1 else ""))
    click.echo(f"  Mean recall: {agg['mean_recall']}%  95% CI [{agg['ci95'][0]}, {agg['ci95'][1]}] "
               "(claim-level bootstrap, 10,000 resamples)")
    if k >= 2:
        click.echo(f"  pass^{k} (solved in all {k} books): {agg['pass_all']}%")
        click.echo(f"  pass@{k} (solved in at least one book): {agg['pass_any']}%")
        if k != 3:
            click.echo("  note: the leaderboard protocol requires exactly 3 books (pass^3)")
    else:
        click.echo("  note: single book, so pass^k / pass@k are not computed; the leaderboard requires 3 books")
    click.echo("  Self-scored and unofficial: listed numbers always come from maintainer verification.")
    click.echo("═" * 60)


def _echo_scorecard(scorecard, json_path, md_path) -> None:
    click.echo("")
    click.echo("═" * 60)
    click.echo("  SCORECARD SUMMARY")
    click.echo("═" * 60)
    click.echo(f"  Total claims: {scorecard['total_claims']}")
    click.echo(f"  Correct:      {scorecard['correct']}")
    click.echo(f"  Partial:      {scorecard['partial']}")
    click.echo(f"  Missing:      {scorecard['missing']}")
    click.echo(f"  Contradicted: {scorecard['contradicted']}")
    click.echo(f"  Claim recall: {scorecard['claim_recall'] * 100:.1f}%")
    click.echo("")
    click.echo(f"  JSON: {json_path}")
    click.echo(f"  Markdown: {md_path}")
    click.echo("═" * 60)
