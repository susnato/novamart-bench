from __future__ import annotations

import json
import re
from pathlib import Path

import click
import yaml
from google.genai import types as genai_types

from harness.judges.llm_judge import DEFAULT_MODEL, _get_client

SYSTEM_PROMPT = """\
You are validating an atomic eval claim before it is added to a tribal-knowledge benchmark.

You are NOT evaluating a generated tribal book.
You are NOT discovering evidence.
You are NOT checking file/table existence.

You verify only:
1. claim_name and claim_text quality
2. match/rubric quality
3. semantic alignment between claim_text and resolved evidence

Return only JSON matching this schema:
{
  "verdict": "pass|needs_edit|fail",
  "issues": [{"severity": "blocking|warning", "field": "string", "message": "string"}],
  "claim_checks": {
    "claim_name_matches_text": true,
    "claim_text_is_atomic": true,
    "claim_text_is_clear": true,
    "claim_type_is_correct": true
  },
  "rubric_checks": {
    "must_include_is_sufficient": true,
    "must_not_include_is_sufficient": true,
    "rubric_is_clear": true,
    "rubric_does_not_add_unsupported_facts": true
  },
  "evidence_checks": {
    "has_primary_evidence": true,
    "primary_evidence_supports_claim": true,
    "evidence_does_not_contradict_claim": true,
    "dynamic_claim_has_sql_or_process": true,
    "no_hardcoded_dynamic_values": true
  },
  "suggested_rewrite": null,
  "short_summary": "string"
}"""


def _parse_span(span: str | None) -> tuple[int, int] | None:
    if not span:
        return None
    match = re.search(r"lines?\s*(\d+)\s*[-–]\s*(\d+)", span, re.IGNORECASE)
    if match:
        return int(match.group(1)), int(match.group(2))
    match = re.search(r"lines?\s*(\d+)", span, re.IGNORECASE)
    if match:
        line = int(match.group(1))
        return line, line
    return None


def _resolve_code_evidence(evidence: dict, project_root: Path) -> dict:
    uri = evidence.get("uri", "")
    path = Path(uri)
    if not path.is_absolute():
        path = project_root / uri

    metadata = {
        "commit_hash": evidence.get("commit_hash"),
        "file_exists": path.is_file(),
        "symbol_found": None,
        "span_found": None,
        "table_exists": None,
        "columns_exist": None,
        "sql_dry_run_passed": None,
        "sql_executed": None,
        "estimated_cost_usd": None,
        "skip_reason": None,
    }
    resolved_text = None
    validation_status = "pass" if path.is_file() else "fail"

    if path.is_file():
        text = path.read_text(encoding="utf-8", errors="replace")
        symbol = evidence.get("symbol")
        if symbol:
            metadata["symbol_found"] = symbol in text
            if not metadata["symbol_found"]:
                validation_status = "warning"

        span = _parse_span(evidence.get("span"))
        if span:
            start, end = span
            lines = text.splitlines()
            metadata["span_found"] = 1 <= start <= end <= len(lines)
            if metadata["span_found"]:
                resolved_text = "\n".join(lines[start - 1 : end])
            else:
                validation_status = "warning"
        else:
            resolved_text = text[:4000]
    else:
        metadata["skip_reason"] = "file_not_found"

    return {
        "retrieval_status": "found" if path.is_file() else "missing",
        "validation_status": validation_status,
        "resolved_text": resolved_text,
        "metadata": metadata,
    }


def _resolve_non_code_evidence(evidence: dict) -> dict:
    source_type = evidence.get("source_type")
    metadata = {
        "commit_hash": evidence.get("commit_hash"),
        "file_exists": None,
        "symbol_found": None,
        "span_found": None,
        "table_exists": None,
        "columns_exist": None,
        "sql_dry_run_passed": None,
        "sql_executed": False if source_type == "bq" else None,
        "estimated_cost_usd": None,
        "skip_reason": "bq_resolution_not_configured" if source_type == "bq" else None,
    }
    resolved_text = evidence.get("excerpt") or evidence.get("sql") or evidence.get("table") or evidence.get("uri")
    return {
        "retrieval_status": "found" if resolved_text else "skipped",
        "validation_status": "warning" if source_type == "bq" and not evidence.get("sql") else "pass",
        "resolved_text": resolved_text,
        "metadata": metadata,
    }


def resolve_evidence(claim: dict, project_root: Path) -> list[dict]:
    resolved = []
    for index, evidence in enumerate(claim.get("evidence", []) or []):
        if evidence.get("source_type") == "code":
            result = _resolve_code_evidence(evidence, project_root)
        else:
            result = _resolve_non_code_evidence(evidence)
        resolved.append(
            {
                "evidence_index": index,
                "role": evidence.get("role"),
                "source_type": evidence.get("source_type"),
                **result,
            }
        )
    return resolved


def _parse_json_response(text: str) -> dict | None:
    text = text.strip()
    if text.startswith("```"):
        text = "\n".join(line for line in text.splitlines() if not line.startswith("```"))
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
    return None


def check_claim_with_llm(claim: dict, resolved_evidence: list[dict], model: str) -> dict:
    prompt = (
        "Claim YAML:\n"
        f"{yaml.safe_dump(claim, sort_keys=False, allow_unicode=True)}\n\n"
        "Resolved evidence:\n"
        f"{json.dumps(resolved_evidence, indent=2, ensure_ascii=False)}"
    )
    response = _get_client().models.generate_content(
        model=model,
        contents=[
            genai_types.Content(
                role="user",
                parts=[genai_types.Part(text=prompt)],
            )
        ],
        config=genai_types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=0,
            max_output_tokens=4096,
            response_mime_type="application/json",
        ),
    )
    parsed = _parse_json_response(response.text or "")
    if parsed is None:
        return {
            "verdict": "fail",
            "issues": [
                {
                    "severity": "blocking",
                    "field": "llm_response",
                    "message": "Failed to parse checker response as JSON",
                }
            ],
            "short_summary": "Checker response was not valid JSON.",
        }
    return parsed


@click.command("llm-review-claims")
@click.argument("claim_path", type=click.Path(exists=True))
@click.option("--project-root", default=".", type=click.Path(exists=True), help="Root for resolving code evidence URIs")
@click.option("--model", default=DEFAULT_MODEL, help="Vertex model for the LLM checker")
@click.option("--resolved-only", is_flag=True, help="Only resolve evidence; do not call the LLM checker")
def check_claim(claim_path: str, project_root: str, model: str, resolved_only: bool) -> None:
    """Validate one claim YAML using deterministic evidence resolution and the Vertex LLM checker."""
    path = Path(claim_path)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    claim = data[0] if isinstance(data, list) and len(data) == 1 else data
    if not isinstance(claim, dict):
        raise click.ClickException("Claim file must contain a claim object or a single-item claim list")

    resolved = resolve_evidence(claim, Path(project_root))
    if resolved_only:
        click.echo(json.dumps({"resolved_evidence": resolved}, indent=2, ensure_ascii=False))
        return

    result = check_claim_with_llm(claim, resolved, model=model)
    click.echo(json.dumps(result, indent=2, ensure_ascii=False))
