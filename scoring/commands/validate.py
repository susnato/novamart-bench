from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import click
import jsonschema

from scoring.loaders import load_claims

PACKAGE_ROOT = Path(__file__).resolve().parent.parent.parent
SCHEMAS_DIR = PACKAGE_ROOT / "claims"

VALID_EVIDENCE_SOURCE_TYPES = {
    "code",
    "bq",
    "doc",
    "dashboard",
    "experiment",
    "codebase",
    "data_warehouse",
}


def _load_json(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


def _looks_like_hardcoded_metric(text: str) -> bool:
    patterns = [
        r"\b\d+(?:\.\d+)?\s*%",
        r"\b\d+(?:\.\d+)?\s*[kKmMbB]\b",
        r"\b\d{1,3}(?:,\d{3})+\b",
    ]
    return any(re.search(pattern, text) for pattern in patterns)


def _dynamic_claim_has_process_evidence(claim: dict) -> bool:
    for evidence in claim.get("evidence", []) or []:
        if evidence.get("source_type") not in {"bq", "data_warehouse"}:
            continue
        if evidence.get("sql") or evidence.get("table") or evidence.get("columns"):
            return True
    return False


@click.command("validate-claims-format")
@click.argument("benchmark_dir", type=click.Path(exists=True))
def validate(benchmark_dir: str) -> None:
    """Validate a benchmark's claim-only gold suite."""
    bench = Path(benchmark_dir)
    errors: list[str] = []
    warnings: list[str] = []

    claim_schema = _load_json(SCHEMAS_DIR / "claim.schema.json")

    try:
        claims = load_claims(bench)
    except FileNotFoundError as e:
        click.echo(f"ERROR: {e}", err=True)
        sys.exit(1)

    seen_ids: dict[str, int] = {}

    for i, claim in enumerate(claims):
        cid = claim.get("claim_id", f"<missing-id-{i}>")
        prefix = f"claim[{cid}]"

        try:
            jsonschema.validate(instance=claim, schema=claim_schema)
        except jsonschema.ValidationError as e:
            errors.append(f"{prefix}: schema error - {e.message}")

        if cid in seen_ids:
            errors.append(f"{prefix}: duplicate claim_id (first seen at index {seen_ids[cid]})")
        else:
            seen_ids[cid] = i

        if claim.get("claim_name") == "":
            errors.append(f"{prefix}: claim_name is required")
        if not claim.get("added_at"):
            errors.append(f"{prefix}: added_at is required")
        if claim.get("claim_type") not in {"static", "dynamic"}:
            errors.append(f"{prefix}: claim_type must be static or dynamic")
        if not claim.get("claim_text"):
            errors.append(f"{prefix}: claim_text is required")
        if not isinstance(claim.get("scope"), dict):
            errors.append(f"{prefix}: scope is required")

        evidence_items = claim.get("evidence", []) or []
        if not any(e.get("role") == "primary" for e in evidence_items if isinstance(e, dict)):
            errors.append(f"{prefix}: at least one primary evidence item is required")
        for evidence_idx, evidence in enumerate(evidence_items):
            source_type = evidence.get("source_type")
            if source_type not in VALID_EVIDENCE_SOURCE_TYPES:
                errors.append(
                    f"{prefix}: evidence[{evidence_idx}].source_type must be one of "
                    f"{sorted(VALID_EVIDENCE_SOURCE_TYPES)}"
                )

        match = claim.get("match", {}) or {}
        if not match.get("must_include"):
            errors.append(f"{prefix}: match.must_include must be non-empty")
        if "must_not_include" not in match:
            errors.append(f"{prefix}: match.must_not_include must exist")
        if not match.get("rubric"):
            errors.append(f"{prefix}: match.rubric is required")

        if (
            claim.get("claim_type") == "dynamic"
            and _looks_like_hardcoded_metric(claim.get("claim_text", ""))
            and not _dynamic_claim_has_process_evidence(claim)
        ):
            warnings.append(
                f"{prefix}: dynamic claim appears to hardcode metric values without BQ process evidence"
            )

    click.echo(f"Benchmark:    {bench.name}")
    click.echo(f"Total claims: {len(claims)}")
    click.echo("")

    if warnings:
        click.echo(f"Warnings ({len(warnings)}):")
        for warning in warnings:
            click.echo(f"  - {warning}")
        click.echo("")

    if errors:
        click.echo(f"Errors ({len(errors)}):")
        for error in errors:
            click.echo(f"  - {error}")
        click.echo("")
        click.echo("Validation FAILED.")
        sys.exit(1)

    click.echo("Validation PASSED - no errors found.")
    sys.exit(0)
