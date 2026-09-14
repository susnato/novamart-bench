from __future__ import annotations

import csv
import json
from pathlib import Path

import click

from harness.loaders import load_claims


@click.command("export-claims-to-csv")
@click.option("--benchmark", required=True, type=click.Path(exists=True))
@click.option("--to", "output_path", required=True, help="Output CSV path")
@click.option("--filter", "filter_expr", default=None, help="Filter expression (e.g., claim_type=dynamic)")
def export_claims(benchmark: str, output_path: str, filter_expr: str | None) -> None:
    """Export claim-only gold claims to a reviewable CSV."""
    bench = Path(benchmark)
    claims = load_claims(bench)

    if filter_expr:
        key, _, val = filter_expr.partition("=")
        key = key.strip()
        val = val.strip()
        claims = [c for c in claims if str(c.get(key, "")) == val]

    columns = [
        "claim_id",
        "claim_name",
        "added_at",
        "claim_type",
        "claim_text",
        "scope_customer",
        "scope_product_area",
        "scope_system",
        "scope_surface",
        "primary_evidence_source_type",
        "primary_evidence_uri",
        "primary_evidence_span",
        "evidence_json",
        "must_include_json",
        "must_not_include_json",
        "rubric",
    ]

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    with open(out, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()

        for claim in claims:
            scope = claim.get("scope", {}) or {}
            evidence_items = claim.get("evidence", []) or []
            primary = next((e for e in evidence_items if e.get("role") == "primary"), {})
            if not primary and evidence_items:
                primary = evidence_items[0]
            match = claim.get("match", {}) or {}

            writer.writerow(
                {
                    "claim_id": claim.get("claim_id", ""),
                    "claim_name": claim.get("claim_name", ""),
                    "added_at": claim.get("added_at", ""),
                    "claim_type": claim.get("claim_type", ""),
                    "claim_text": claim.get("claim_text", ""),
                    "scope_customer": scope.get("customer", ""),
                    "scope_product_area": scope.get("product_area", ""),
                    "scope_system": scope.get("system", ""),
                    "scope_surface": scope.get("surface", ""),
                    "primary_evidence_source_type": primary.get("source_type", ""),
                    "primary_evidence_uri": primary.get("uri", ""),
                    "primary_evidence_span": primary.get("span", ""),
                    "evidence_json": json.dumps(evidence_items, ensure_ascii=False),
                    "must_include_json": json.dumps(match.get("must_include", []), ensure_ascii=False),
                    "must_not_include_json": json.dumps(match.get("must_not_include", []), ensure_ascii=False),
                    "rubric": match.get("rubric", ""),
                }
            )

    click.echo(f"{len(claims)} claims exported to {out}")
