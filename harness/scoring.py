from __future__ import annotations

from collections import Counter

VALID_VERDICTS = {"correct", "partial", "missing", "contradicted"}
VALID_BOOK_EVIDENCE = {"specific", "weak", "none"}


def _pct(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return round(numerator / denominator, 4)


def _primary_source_type(claim: dict) -> str:
    for evidence in claim.get("evidence", []) or []:
        if evidence.get("role") == "primary":
            return evidence.get("source_type") or "unknown"
    if claim.get("evidence"):
        return claim["evidence"][0].get("source_type") or "unknown"
    return "unknown"


def _rollup(results: list[dict]) -> dict:
    counts = Counter(r.get("verdict", "missing") for r in results)
    evidence_specific = sum(1 for r in results if r.get("book_evidence") == "specific")
    total = len(results)
    return {
        "total": total,
        "correct": counts.get("correct", 0),
        "partial": counts.get("partial", 0),
        "missing": counts.get("missing", 0),
        "contradicted": counts.get("contradicted", 0),
        "claim_recall": _pct(counts.get("correct", 0), total),
        "evidence_coverage": _pct(evidence_specific, total),
    }


def _group_rollups(claims: list[dict], claim_results: list[dict], key_fn) -> dict:
    result_lookup = {r["claim_id"]: r for r in claim_results}
    grouped: dict[str, list[dict]] = {}
    for claim in claims:
        result = result_lookup.get(claim["claim_id"])
        if result is None:
            continue
        key = key_fn(claim) or "unknown"
        grouped.setdefault(key, []).append(result)
    return {key: _rollup(results) for key, results in sorted(grouped.items())}


def compute_scorecard(
    claim_results: list[dict],
    claims: list[dict],
    metadata: dict,
) -> dict:
    claim_lookup: dict[str, dict] = {c["claim_id"]: c for c in claims}
    normalized_results: list[dict] = []
    for result in claim_results:
        claim = claim_lookup.get(result["claim_id"], {})
        verdict = result.get("verdict", "missing")
        if verdict not in VALID_VERDICTS:
            verdict = "missing"
        book_evidence = result.get("book_evidence", "none")
        if book_evidence not in VALID_BOOK_EVIDENCE:
            book_evidence = "none"
        scope = claim.get("scope", {}) or {}
        normalized_results.append(
            {
                "claim_id": result["claim_id"],
                "claim_name": claim.get("claim_name", ""),
                "claim_type": claim.get("claim_type", "static"),
                "source_type": claim.get("source_type", "unknown"),
                "acquisition": claim.get("acquisition", "unknown"),
                "product_area": scope.get("product_area", "unknown"),
                "verdict": verdict,
                "book_evidence": book_evidence,
                "must_include_found": result.get("must_include_found", []) or [],
                "must_include_missing": result.get("must_include_missing", []) or [],
                "must_not_include_found": result.get("must_not_include_found", []) or [],
                "justification": result.get("justification", ""),
                "confidence": result.get("confidence", "low"),
            }
        )

    overall = _rollup(normalized_results)
    failures = [r for r in normalized_results if r["verdict"] in ("missing", "contradicted")]
    top_failures = [
        f"{r['claim_id']} — {r['verdict']} — {r.get('justification', '')}"
        for r in failures[:10]
    ]

    scorecard: dict = {
        "benchmark": metadata.get("benchmark", ""),
        "book": metadata.get("book", ""),
        "book_path": metadata.get("book_path", ""),
        "timestamp": metadata.get("timestamp", ""),
        "judge_model": metadata.get("judge_model", ""),
        "use_must_include_fields": metadata.get("use_must_include_fields", True),
        "total_claims": len(claim_results),
        "correct": overall["correct"],
        "partial": overall["partial"],
        "missing": overall["missing"],
        "contradicted": overall["contradicted"],
        "claim_recall": overall["claim_recall"],
        "evidence_coverage": overall["evidence_coverage"],
        "by_product_area": _group_rollups(claims, normalized_results, lambda c: (c.get("scope") or {}).get("product_area")),
        "by_source_type": _group_rollups(claims, normalized_results, lambda c: c.get("source_type")),
        "by_acquisition": _group_rollups(claims, normalized_results, lambda c: c.get("acquisition")),
        "claim_results": normalized_results,
        "top_failures": top_failures,
    }
    return scorecard
