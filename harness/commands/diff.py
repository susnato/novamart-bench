from __future__ import annotations

import json
from pathlib import Path

import click

CORRECT_VERDICTS = {"correct"}


def _load_scorecard(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


def _compute_deltas(sc1: dict, sc2: dict) -> dict:
    results1 = {r["claim_id"]: r for r in sc1.get("claim_results", [])}
    results2 = {r["claim_id"]: r for r in sc2.get("claim_results", [])}
    ids1 = set(results1)
    ids2 = set(results2)

    resolved: list[dict] = []
    regressed: list[dict] = []
    changed: list[dict] = []
    for cid in sorted(ids1 & ids2):
        r1 = results1[cid]
        r2 = results2[cid]
        was_correct = r1["verdict"] in CORRECT_VERDICTS
        is_correct = r2["verdict"] in CORRECT_VERDICTS
        if not was_correct and is_correct:
            resolved.append({"claim_id": cid, "verdict_1": r1["verdict"], "verdict_2": r2["verdict"]})
        elif was_correct and not is_correct:
            regressed.append({"claim_id": cid, "verdict_1": r1["verdict"], "verdict_2": r2["verdict"]})
        elif r1["verdict"] != r2["verdict"]:
            changed.append({"claim_id": cid, "verdict_1": r1["verdict"], "verdict_2": r2["verdict"]})

    new_issues = [
        {"claim_id": cid, "verdict": results2[cid]["verdict"]}
        for cid in sorted(ids2 - ids1)
        if results2[cid]["verdict"] not in CORRECT_VERDICTS
    ]

    return {
        "from": {
            "benchmark": sc1.get("benchmark", ""),
            "book": sc1.get("book", ""),
            "timestamp": sc1.get("timestamp", ""),
            "claim_recall": sc1.get("claim_recall", 0),
            "evidence_coverage": sc1.get("evidence_coverage", 0),
        },
        "to": {
            "benchmark": sc2.get("benchmark", ""),
            "book": sc2.get("book", ""),
            "timestamp": sc2.get("timestamp", ""),
            "claim_recall": sc2.get("claim_recall", 0),
            "evidence_coverage": sc2.get("evidence_coverage", 0),
        },
        "claim_recall_delta": round(sc2.get("claim_recall", 0) - sc1.get("claim_recall", 0), 4),
        "evidence_coverage_delta": round(
            sc2.get("evidence_coverage", 0) - sc1.get("evidence_coverage", 0), 4
        ),
        "resolved": resolved,
        "regressed": regressed,
        "changed": changed,
        "new_issues": new_issues,
    }


def _fmt_delta(value: float) -> str:
    return f"{value * 100:+.1f}pp"


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _render_markdown(deltas: dict) -> str:
    lines: list[str] = []

    lines.append("# Scorecard Diff")
    lines.append("")
    lines.append(f"**From:** {deltas['from']['book']} ({deltas['from']['timestamp']})")
    lines.append(f"**To:** {deltas['to']['book']} ({deltas['to']['timestamp']})")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append("| Metric | From | To | Delta |")
    lines.append("|---|---:|---:|---:|")
    lines.append(
        f"| Claim Recall | {_pct(deltas['from']['claim_recall'])} "
        f"| {_pct(deltas['to']['claim_recall'])} | {_fmt_delta(deltas['claim_recall_delta'])} |"
    )
    lines.append(
        f"| Evidence Coverage | {_pct(deltas['from']['evidence_coverage'])} "
        f"| {_pct(deltas['to']['evidence_coverage'])} | {_fmt_delta(deltas['evidence_coverage_delta'])} |"
    )
    lines.append("")

    for title, key in (
        ("Resolved Claims", "resolved"),
        ("Regressions", "regressed"),
        ("Changed Claims", "changed"),
        ("New Issues", "new_issues"),
    ):
        rows = deltas.get(key, [])
        if not rows:
            continue
        lines.append(f"## {title} ({len(rows)})")
        lines.append("")
        for row in rows[:20]:
            if "verdict_1" in row:
                lines.append(f"- **{row['claim_id']}**: {row['verdict_1']} -> {row['verdict_2']}")
            else:
                lines.append(f"- **{row['claim_id']}**: {row['verdict']}")
        lines.append("")

    if not any(deltas.get(key) for key in ("resolved", "regressed", "changed", "new_issues")):
        lines.append("_No claim-level changes detected._")
        lines.append("")

    return "\n".join(lines)


def _run_label(scorecard: dict) -> str:
    return f"{scorecard.get('book', '?')} ({scorecard.get('timestamp', '?')})"


def _claim_results(scorecard: dict) -> dict[str, dict]:
    return {result["claim_id"]: result for result in scorecard.get("claim_results", [])}


def _compute_multi_run(scorecards: list[dict]) -> dict:
    result_maps = [_claim_results(scorecard) for scorecard in scorecards]
    claim_sets = [set(results) for results in result_maps]
    common_claim_ids = set.intersection(*claim_sets) if claim_sets else set()
    all_claim_ids = set.union(*claim_sets) if claim_sets else set()

    runs = []
    for index, scorecard in enumerate(scorecards):
        runs.append(
            {
                "index": index,
                "label": _run_label(scorecard),
                "book": scorecard.get("book", "?"),
                "timestamp": scorecard.get("timestamp", "?"),
                "judge_model": scorecard.get("judge_model", "?"),
                "total_claims": scorecard.get("total_claims", 0),
                "correct": scorecard.get("correct", 0),
                "partial": scorecard.get("partial", 0),
                "missing": scorecard.get("missing", 0),
                "contradicted": scorecard.get("contradicted", 0),
                "claim_recall": scorecard.get("claim_recall", 0),
                "evidence_coverage": scorecard.get("evidence_coverage", 0),
            }
        )

    claim_matrix = []
    for claim_id in sorted(common_claim_ids):
        entries = []
        verdicts = []
        for result_map in result_maps:
            result = result_map[claim_id]
            verdict = result.get("verdict", "missing")
            verdicts.append(verdict)
            entries.append(
                {
                    "verdict": verdict,
                    "book_evidence": result.get("book_evidence", "none"),
                    "justification": result.get("justification", ""),
                }
            )
        claim_matrix.append(
            {
                "claim_id": claim_id,
                "verdicts": verdicts,
                "entries": entries,
                "all_correct": all(verdict in CORRECT_VERDICTS for verdict in verdicts),
                "none_correct": all(verdict not in CORRECT_VERDICTS for verdict in verdicts),
                "has_disagreement": len(set(verdicts)) > 1,
                "has_contradiction": "contradicted" in verdicts,
            }
        )

    unique_correct_by_run: list[dict] = []
    for index, result_map in enumerate(result_maps):
        other_maps = [m for i, m in enumerate(result_maps) if i != index]
        claims = []
        for claim_id in sorted(common_claim_ids):
            if result_map[claim_id].get("verdict") not in CORRECT_VERDICTS:
                continue
            if all(other[claim_id].get("verdict") not in CORRECT_VERDICTS for other in other_maps):
                claims.append(claim_id)
        unique_correct_by_run.append({"run_index": index, "claims": claims})

    return {
        "runs": runs,
        "common_claim_count": len(common_claim_ids),
        "union_claim_count": len(all_claim_ids),
        "all_correct": [row for row in claim_matrix if row["all_correct"]],
        "none_correct": [row for row in claim_matrix if row["none_correct"]],
        "contradicted_any": [row for row in claim_matrix if row["has_contradiction"]],
        "disagreements": [row for row in claim_matrix if row["has_disagreement"]],
        "unique_correct_by_run": unique_correct_by_run,
    }


def _render_claim_matrix(rows: list[dict], runs: list[dict], limit: int = 50) -> list[str]:
    if not rows:
        return ["_None._", ""]

    lines = []
    headers = " | ".join(run["book"] for run in runs)
    lines.append(f"| Claim | {headers} |")
    lines.append("|---" + "|---" * len(runs) + "|")
    for row in rows[:limit]:
        verdicts = " | ".join(row["verdicts"])
        lines.append(f"| `{row['claim_id']}` | {verdicts} |")
    if len(rows) > limit:
        lines.append(f"| _... {len(rows) - limit} more_ | " + " | ".join(" " for _ in runs) + " |")
    lines.append("")
    return lines


def _render_multi_markdown(comparison: dict) -> str:
    runs = comparison["runs"]
    lines: list[str] = []

    lines.append("# Multi-Run Scorecard Comparison")
    lines.append("")
    lines.append("## Runs")
    lines.append("")
    lines.append("| Run | Timestamp | Correct | Partial | Missing | Contradicted | Recall | Evidence Coverage |")
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|")
    for run in runs:
        lines.append(
            f"| {run['book']} | {run['timestamp']} | {run['correct']}/{run['total_claims']} "
            f"| {run['partial']} | {run['missing']} | {run['contradicted']} "
            f"| {_pct(run['claim_recall'])} | {_pct(run['evidence_coverage'])} |"
        )
    lines.append("")

    lines.append("## Intersection")
    lines.append("")
    lines.append(f"- Common claims across all runs: **{comparison['common_claim_count']}**")
    lines.append(f"- Union of claims across all runs: **{comparison['union_claim_count']}**")
    lines.append("")

    lines.append("## Correct In All Runs")
    lines.append("")
    lines.extend(_render_claim_matrix(comparison["all_correct"], runs))

    lines.append("## Not Correct In Any Run")
    lines.append("")
    lines.append("Claims where every compared book failed to get a `correct` verdict.")
    lines.append("")
    lines.extend(_render_claim_matrix(comparison["none_correct"], runs))

    lines.append("## Contradicted By At Least One Run")
    lines.append("")
    lines.extend(_render_claim_matrix(comparison["contradicted_any"], runs))

    lines.append("## Unique Correct Claims")
    lines.append("")
    for item in comparison["unique_correct_by_run"]:
        run = runs[item["run_index"]]
        claims = item["claims"]
        lines.append(f"### {run['book']} ({len(claims)})")
        lines.append("")
        if claims:
            for claim_id in claims[:50]:
                lines.append(f"- `{claim_id}`")
            if len(claims) > 50:
                lines.append(f"- _... {len(claims) - 50} more_")
        else:
            lines.append("_None._")
        lines.append("")

    lines.append("## Verdict Disagreements")
    lines.append("")
    lines.extend(_render_claim_matrix(comparison["disagreements"], runs, limit=80))

    return "\n".join(lines)


@click.command("compare-runs")
@click.argument("scorecards", nargs=-1, type=click.Path(exists=True), required=True)
@click.option("--format", "output_format", default="markdown", type=click.Choice(["markdown", "json"]))
@click.option("--output", "output_path", default=None, help="Optional path to write comparison output")
def diff_cmd(scorecards: tuple[str, ...], output_format: str, output_path: str | None) -> None:
    """Compare two or more claim-only scorecards and show deltas."""
    if len(scorecards) < 2:
        raise click.ClickException("compare-runs requires at least two scorecard JSON files")

    loaded = [_load_scorecard(Path(path)) for path in scorecards]
    if len(loaded) == 2:
        payload = _compute_deltas(loaded[0], loaded[1])
        rendered = json.dumps(payload, indent=2, default=str) if output_format == "json" else _render_markdown(payload)
    else:
        payload = _compute_multi_run(loaded)
        rendered = json.dumps(payload, indent=2, default=str) if output_format == "json" else _render_multi_markdown(payload)

    if output_path:
        Path(output_path).write_text(rendered, encoding="utf-8")
        click.echo(f"Wrote comparison to {output_path}")
    else:
        click.echo(rendered)
