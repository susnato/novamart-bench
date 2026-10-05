from __future__ import annotations

import json
import os
import random
import time

from google import genai
from google.genai import types as genai_types

DEFAULT_MODEL = os.getenv("TRIBAL_EVALS_JUDGE_MODEL", "gemini-3-flash-preview")

SYSTEM_PROMPT_WITH_MUST_INCLUDE = """\
You are evaluating whether a generated tribal knowledge book contains one gold atomic claim.

Gold evidence explains why the gold claim is true.
Do NOT count gold evidence as evidence in the book.
Only score what the book itself says.

Use match.must_include to decide required coverage.
Use match.must_not_include to detect contradictions.

Return ONLY a JSON object matching this schema:
{
  "verdict": "correct|partial|missing|contradicted",
  "book_evidence": "specific|weak|none",
  "must_include_found": ["string"],
  "must_include_missing": ["string"],
  "must_not_include_found": ["string"],
  "justification": "short explanation",
  "confidence": "high|medium|low"
}

Decision rules:
- Any must_not_include point found in the book means verdict = contradicted.
- All must_include points found and no forbidden point found means verdict = correct.
- Some required points present but important ones missing means verdict = partial.
- Most or all required points missing means verdict = missing.
- book_evidence = specific only when the book itself provides a code path, table/query,
  dashboard, experiment, or source reference.
- book_evidence = weak when the book gives vague support but no concrete source reference.
- book_evidence = none when the book states the fact without support or omits it."""

SYSTEM_PROMPT_WITHOUT_MUST_INCLUDE = """\
You are evaluating whether a generated tribal knowledge book contains one gold atomic claim.

Gold evidence explains why the gold claim is true.
Do NOT count gold evidence as evidence in the book.
Only score what the book itself says.

Use claim_text as the required claim.
Match constraints have been intentionally omitted for this run.

Return ONLY a JSON object matching this schema:
{
  "verdict": "correct|partial|missing|contradicted",
  "book_evidence": "specific|weak|none",
  "must_include_found": ["string"],
  "must_include_missing": ["string"],
  "must_not_include_found": ["string"],
  "justification": "short explanation",
  "confidence": "high|medium|low"
}

Decision rules:
- If the book directly conflicts with claim_text, verdict = contradicted.
- If the book clearly supports the claim_text, verdict = correct.
- If the book supports only part of the claim_text, verdict = partial.
- If the book omits most or all of the claim_text, verdict = missing.
- Leave must_include_found, must_include_missing, and must_not_include_found empty
  unless you infer them directly from claim_text.
- book_evidence = specific only when the book itself provides a code path, table/query,
  dashboard, experiment, or source reference.
- book_evidence = weak when the book gives vague support but no concrete source reference.
- book_evidence = none when the book states the fact without support or omits it."""

VALID_VERDICTS = {"correct", "partial", "missing", "contradicted"}
VALID_BOOK_EVIDENCE = {"specific", "weak", "none"}
VALID_CONFIDENCE = {"high", "medium", "low"}

_client: genai.Client | None = None


class JudgeAPIError(RuntimeError):
    """A judge call failed for good (bad credentials, or retries exhausted). Scoring must stop:
    a claim must never be recorded as "missing" because the API was unreachable."""


_RETRYABLE = ("429", "RESOURCE_EXHAUSTED", "500", "INTERNAL", "502", "503", "UNAVAILABLE",
              "504", "DEADLINE_EXCEEDED", "Connection", "connection", "timed out", "Timeout",
              # transient name resolution and credential refresh failures (laptop networks)
              "nodename nor servname", "Name or service not known", "Temporary failure in name resolution",
              "getaddrinfo", "Could not resolve API token")


def _is_retryable(exc: Exception) -> bool:
    return any(tok in str(exc) for tok in _RETRYABLE)


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        # Gemini API key mode: same models, key-based auth.
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if api_key:
            _client = genai.Client(api_key=api_key)
            return _client
        # Deliberately NOT GOOGLE_CLOUD_PROJECT: the local access pack exports it as the
        # emulator's fake project id, which would send the judge to a non-existent Vertex project.
        project = os.getenv("VERTEX_AI_HIGH_PROJECT_ID") or os.getenv("VERTEX_AI_PROJECT_ID")
        if not project:
            raise JudgeAPIError(
                "Judge credentials not configured: set GEMINI_API_KEY (Gemini API) or "
                "VERTEX_AI_PROJECT_ID (Vertex AI with gcloud application-default credentials)."
            )
        location = (
            os.getenv("VERTEX_AI_LOCATION")
            or os.getenv("GOOGLE_CLOUD_LOCATION")
            or "global"
        )
        _client = genai.Client(vertexai=True, project=project, location=location)
    return _client


def _claim_packet(claim: dict, use_must_include_fields: bool = True) -> dict:
    match = dict(claim.get("match", {}) or {})
    if not use_must_include_fields:
        match.pop("must_include", None)
        match.pop("must_not_include", None)

    return {
        "claim_id": claim.get("claim_id"),
        "claim_name": claim.get("claim_name"),
        "claim_type": claim.get("claim_type"),
        "source_type": claim.get("source_type"),
        "claim_text": claim.get("claim_text"),
        "scope": claim.get("scope", {}),
        "match": match,
        "gold_evidence_for_context_only": claim.get("evidence", []),
    }


def _build_user_prompt(claim: dict, book_text: str, use_must_include_fields: bool = True) -> str:
    packet = json.dumps(_claim_packet(claim, use_must_include_fields), indent=2, ensure_ascii=False)
    return (
        "Claim packet:\n"
        f"{packet}\n\n"
        "Generated book:\n"
        f"{book_text}\n\n"
        "Return only JSON matching the requested BookClaimJudgeResult schema."
    )


def _parse_response(text: str) -> dict | None:
    text = text.strip()
    if text.startswith("```"):
        lines = [line for line in text.splitlines() if not line.startswith("```")]
        text = "\n".join(lines)
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


def _normalize_result(
    parsed: dict | None,
    claim: dict,
    fallback_reason: str | None = None,
    use_must_include_fields: bool = True,
) -> dict:
    if parsed is None:
        must_include_missing = []
        if use_must_include_fields:
            must_include_missing = claim.get("match", {}).get("must_include", []) or []
        return {
            "verdict": "missing",
            "book_evidence": "none",
            "must_include_found": [],
            "must_include_missing": must_include_missing,
            "must_not_include_found": [],
            "justification": fallback_reason or "Failed to parse LLM response as JSON",
            "confidence": "low",
        }

    verdict = parsed.get("verdict", "missing")
    if verdict not in VALID_VERDICTS:
        verdict = "missing"

    book_evidence = parsed.get("book_evidence", "none")
    if book_evidence not in VALID_BOOK_EVIDENCE:
        book_evidence = "none"

    confidence = parsed.get("confidence", "low")
    if confidence not in VALID_CONFIDENCE:
        confidence = "low"

    return {
        "verdict": verdict,
        "book_evidence": book_evidence,
        "must_include_found": parsed.get("must_include_found", []) or [],
        "must_include_missing": parsed.get("must_include_missing", []) or [],
        "must_not_include_found": parsed.get("must_not_include_found", []) or [],
        "justification": parsed.get("justification", "No justification provided"),
        "confidence": confidence,
    }


def evaluate_claim_llm(
    claim: dict,
    book_text: str,
    model: str = DEFAULT_MODEL,
    use_must_include_fields: bool = True,
) -> dict:
    user_prompt = _build_user_prompt(claim, book_text, use_must_include_fields)
    system_prompt = SYSTEM_PROMPT_WITH_MUST_INCLUDE if use_must_include_fields else SYSTEM_PROMPT_WITHOUT_MUST_INCLUDE

    max_attempts = 6
    claim_id = claim.get("claim_id", "?")
    for attempt in range(1, max_attempts + 1):
        try:
            client = _get_client()
            response = client.models.generate_content(
                model=model,
                contents=[
                    genai_types.Content(
                        role="user",
                        parts=[genai_types.Part(text=user_prompt)],
                    )
                ],
                config=genai_types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=0,
                    max_output_tokens=10000,
                    response_mime_type="application/json",
                ),
            )
            raw_text = response.text or ""
            break
        except JudgeAPIError:
            raise
        except Exception as exc:
            if not _is_retryable(exc):
                raise JudgeAPIError(f"claim {claim_id}: {exc}") from exc
            if attempt == max_attempts:
                raise JudgeAPIError(f"claim {claim_id}: still failing after {attempt} attempts: {exc}") from exc
            # rate limits start at 5 s, other transient errors at 2 s; doubling, capped at 60 s, with jitter
            base = 5 if ("429" in str(exc) or "RESOURCE_EXHAUSTED" in str(exc)) else 2
            time.sleep(min(60, base * 2 ** (attempt - 1)) + random.random())

    return _normalize_result(_parse_response(raw_text), claim, use_must_include_fields=use_must_include_fields)
