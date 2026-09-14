from __future__ import annotations

from datetime import datetime
from pathlib import Path

import click

from harness.loaders import load_claims, load_book
from harness.judges.composite import evaluate_all_claims
from harness.judges.llm_judge import DEFAULT_MODEL
from harness.scoring import compute_scorecard
from harness.report import write_scorecard


@click.command("score-book")
@click.option("--gold", required=True, type=click.Path(exists=True), help="Path to benchmark directory")
@click.option("--book", required=True, type=click.Path(exists=True), help="Path to markdown book under test")
@click.option("--judge-model", default=DEFAULT_MODEL, help="Model for LLM judge")
@click.option("--workers", default=10, type=int, help="Parallel workers for LLM judge calls")
@click.option("--output-dir", default=None, help="Custom output directory for scorecard")
@click.option(
    "--use-must-include-fields/--ignore-must-include-fields",
    default=True,
    help="Whether to include match.must_include fields in the LLM judge prompt.",
)
def run(
    gold: str,
    book: str,
    judge_model: str,
    workers: int,
    output_dir: str | None,
    use_must_include_fields: bool,
) -> None:
    """Evaluate a tribal knowledge book against a gold claim suite."""
    gold_path = Path(gold)
    book_path = Path(book)

    click.echo(f"Loading benchmark from {gold_path} ...")
    claims = load_claims(gold_path)
    book_text = load_book(book_path)

    click.echo(f"Loaded {len(claims)} claims, book={book_path.name}")
    click.echo(f"Judge model: {judge_model} (workers={workers})")
    click.echo(f"Use must_include fields: {use_must_include_fields}")

    claim_results = evaluate_all_claims(
        claims,
        book_text,
        model=judge_model,
        max_workers=workers,
        use_must_include_fields=use_must_include_fields,
    )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    metadata = {
        "benchmark": gold_path.name,
        "book": book_path.stem,
        "book_path": str(book_path),
        "timestamp": timestamp,
        "judge_model": judge_model,
        "use_must_include_fields": use_must_include_fields,
    }
    scorecard = compute_scorecard(claim_results, claims, metadata)

    if output_dir is None:
        out = gold_path / "eval-run-outputs" / f"{book_path.stem}_{timestamp}"
    else:
        out = Path(output_dir)

    json_path, md_path = write_scorecard(scorecard, out)

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
