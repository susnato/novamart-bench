from __future__ import annotations

import json
from pathlib import Path


def _fmt_pct(value: float | int) -> str:
    return f"{value * 100:.1f}%"


def _render_rollup_table(title: str, rollups: dict) -> list[str]:
    if not rollups:
        return []

    lines = [f"## {title}", ""]
    lines.append("| Group | Total | Correct | Partial | Missing | Contradicted | Recall | Evidence Coverage |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for key, row in sorted(rollups.items()):
        lines.append(
            f"| {key} | {row.get('total', 0)} | {row.get('correct', 0)} "
            f"| {row.get('partial', 0)} | {row.get('missing', 0)} "
            f"| {row.get('contradicted', 0)} | {_fmt_pct(row.get('claim_recall', 0))} "
            f"| {_fmt_pct(row.get('evidence_coverage', 0))} |"
        )
    lines.append("")
    return lines


def _render_markdown(scorecard: dict) -> str:
    lines: list[str] = []

    lines.append("# Tribal Knowledge Eval Scorecard")
    lines.append("")
    lines.append(f"**Benchmark:** {scorecard.get('benchmark', 'N/A')}")
    lines.append(f"**Book:** {scorecard.get('book', 'N/A')}")
    lines.append(f"**Timestamp:** {scorecard.get('timestamp', 'N/A')}")
    lines.append(f"**Judge model:** {scorecard.get('judge_model', 'N/A')}")
    lines.append(f"**Use must_include fields:** {scorecard.get('use_must_include_fields', True)}")
    lines.append(f"**Claims evaluated:** {scorecard.get('total_claims', 0)}")
    lines.append("")
    lines.append("---")
    lines.append("")

    lines.append("## Overall")
    lines.append("")
    lines.append("| Total | Correct | Partial | Missing | Contradicted | Claim Recall | Evidence Coverage |")
    lines.append("|---:|---:|---:|---:|---:|---:|---:|")
    lines.append(
        f"| {scorecard.get('total_claims', 0)} "
        f"| {scorecard.get('correct', 0)} "
        f"| {scorecard.get('partial', 0)} "
        f"| {scorecard.get('missing', 0)} "
        f"| {scorecard.get('contradicted', 0)} "
        f"| {_fmt_pct(scorecard.get('claim_recall', 0))} "
        f"| {_fmt_pct(scorecard.get('evidence_coverage', 0))} |"
    )
    lines.append("")

    lines.extend(_render_rollup_table("By Product Area", scorecard.get("by_product_area", {})))
    lines.extend(_render_rollup_table("By Source Type", scorecard.get("by_source_type", {})))
    lines.extend(_render_rollup_table("By Acquisition", scorecard.get("by_acquisition", {})))

    lines.append("## Top Failures")
    lines.append("")
    for i, failure in enumerate(scorecard.get("top_failures", []), 1):
        lines.append(f"{i}. {failure}")
    if not scorecard.get("top_failures"):
        lines.append("_No failures detected._")
    lines.append("")

    lines.append("## Claim Details")
    lines.append("")
    lines.append(
        "| Claim | Source Type | Acquisition | Product Area | Verdict | Book Evidence | Confidence | Justification |"
    )
    lines.append("|---|---|---|---|---|---|---|---|")
    for cr in scorecard.get("claim_results", []):
        justification = (cr.get("justification") or "").replace("|", "\\|")
        lines.append(
            f"| {cr.get('claim_id', '')} "
            f"| {cr.get('source_type', '')} "
            f"| {cr.get('acquisition', '')} "
            f"| {cr.get('product_area', '')} "
            f"| {cr.get('verdict', '')} "
            f"| {cr.get('book_evidence', '')} "
            f"| {cr.get('confidence', '')} "
            f"| {justification} |"
        )
    lines.append("")

    return "\n".join(lines)


def write_scorecard(scorecard: dict, output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = output_dir / "scorecard.json"
    json_path.write_text(json.dumps(scorecard, indent=2, default=str), encoding="utf-8")

    md_path = output_dir / "scorecard.md"
    md_path.write_text(_render_markdown(scorecard), encoding="utf-8")

    update_index(output_dir.parent)

    return json_path, md_path


def update_index(runs_dir: Path) -> Path | None:
    """Scan all claim-only scorecards and compile a single INDEX.md."""
    if not runs_dir.exists():
        return None

    rows: list[dict] = []
    for scorecard_path in sorted(runs_dir.glob("*/scorecard.json")):
        try:
            sc = json.loads(scorecard_path.read_text())
        except Exception:
            continue

        total = sc.get("total_claims", 0)
        rows.append(
            {
                "run_dir": scorecard_path.parent.name,
                "book": sc.get("book", "?"),
                "timestamp": sc.get("timestamp", "?"),
                "judge_model": sc.get("judge_model", "?"),
                "total_claims": total,
                "correct": sc.get("correct", 0),
                "partial": sc.get("partial", 0),
                "missing": sc.get("missing", 0),
                "contradicted": sc.get("contradicted", 0),
                "claim_recall": sc.get("claim_recall", 0),
                "evidence_coverage": sc.get("evidence_coverage", 0),
            }
        )

    rows.sort(key=lambda r: r["timestamp"], reverse=True)

    lines: list[str] = []
    lines.append("# Eval Runs Index")
    lines.append("")
    lines.append(f"_Auto-generated. {len(rows)} run(s) across all books._")
    lines.append("")

    if not rows:
        lines.append("No runs yet. Run `python -m harness.cli score-book --gold <benchmark-dir> --book <book.md>`.")
    else:
        lines.append("## Latest run per book")
        lines.append("")
        latest_by_book: dict[str, dict] = {}
        for row in rows:
            if row["book"] not in latest_by_book:
                latest_by_book[row["book"]] = row

        lines.append("| Book | Correct | Partial | Missing | Contradicted | Recall | Evidence Coverage | Run |")
        lines.append("|---|---:|---:|---:|---:|---:|---:|---|")
        for row in sorted(latest_by_book.values(), key=lambda x: x["book"]):
            lines.append(
                f"| **{row['book']}** "
                f"| {row['correct']}/{row['total_claims']} "
                f"| {row['partial']} "
                f"| {row['missing']} "
                f"| {row['contradicted']} "
                f"| {_fmt_pct(row['claim_recall'])} "
                f"| {_fmt_pct(row['evidence_coverage'])} "
                f"| [`{row['run_dir']}`]({row['run_dir']}/scorecard.md) |"
            )
        lines.append("")

        lines.append("## All Runs")
        lines.append("")
        lines.append("| Timestamp | Book | Correct | Recall | Judge | Run |")
        lines.append("|---|---|---:|---:|---|---|")
        for row in rows:
            lines.append(
                f"| {row['timestamp']} "
                f"| {row['book']} "
                f"| {row['correct']}/{row['total_claims']} "
                f"| {_fmt_pct(row['claim_recall'])} "
                f"| {row['judge_model']} "
                f"| [`{row['run_dir']}`]({row['run_dir']}/scorecard.md) |"
            )
        lines.append("")

    index_path = runs_dir / "INDEX.md"
    index_path.write_text("\n".join(lines), encoding="utf-8")
    return index_path
