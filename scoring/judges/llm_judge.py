"""The LLM judge: one claim, one book, one verdict.

Judge versions
--------------
v2 (current, since 2026-10-21): Claude Haiku 5.5, system prompt ``prompts/judge_v2_system_prompt.txt``,
    effort high, verdict derived from the judge's main-finding decision (``main_finding_in_book``:
    full -> correct, part -> partial, none -> missing; any must_not_include point found -> contradicted).
    Reached through the Anthropic API (model ``claude-haiku-5-5``) or Amazon Bedrock
    (``bedrock/global.anthropic.claude-haiku-5-5``, the maintainer's verification route).
v1 (2026-08 to 2026-10-21): Gemini 3 Flash Preview with the original prompt, temperature 0, verdict taken
    from the model. Selected by ``--judge-model gemini-3-flash-preview``; kept so the v1 records in
    ``submissions/*/*_gemini-3-flash-preview.json`` stay reproducible.

The judge version follows from the model name (``judge_config_for``). Any other model name runs the v2
rubric and is reported as a custom judge: fine for experiments, never for verification.

Operational environment variables (all optional):
  JUDGE_MAX_ATTEMPTS           retries per call before the pass aborts (default 10)
  JUDGE_ANTHROPIC_TIMEOUT_S    Anthropic API request timeout (default 600)
  JUDGE_BEDROCK_READ_TIMEOUT   Bedrock Converse read timeout in seconds (default 600)
  JUDGE_GEMINI_TIMEOUT_MS      Gemini request timeout (default 300000)
  JUDGE_RAW_LOG                append one JSON line per call: prompt hash, parameters, reasoning, raw text, usage
  JUDGE_LEDGER                 append one JSON line per call with token counts and priced cost
  JUDGE_PRICE_TABLE            JSON file {model: {"in": $/M, "out": $/M, "cache_read": $/M, "cache_write": $/M}}
  JUDGE_COST_CAP_USD           hard cap: no call starts once the ledger total reaches it
  JUDGE_RUN_TAG                free-text tag copied into the log and ledger lines
"""
from __future__ import annotations

import datetime as _dt
import fcntl
import hashlib
import json
import os
import random
import threading
import time
from dataclasses import dataclass

_HERE = os.path.dirname(os.path.abspath(__file__))

DEFAULT_MODEL = os.getenv("TRIBAL_EVALS_JUDGE_MODEL", "claude-haiku-5-5")

# ---------------------------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------------------------

def _read_prompt(name: str) -> str:
    with open(os.path.join(_HERE, "prompts", name), encoding="utf-8") as f:
        return f.read().rstrip("\n")


SYSTEM_PROMPT_V2 = _read_prompt("judge_v2_system_prompt.txt")

SYSTEM_PROMPT_V1 = """\
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

SYSTEM_PROMPT_WITH_MUST_INCLUDE = SYSTEM_PROMPT_V1   # name kept for older imports

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

# ---------------------------------------------------------------------------------------------
# Response schemas (used as the structured-output schema where the provider supports one; the
# prompt itself carries the same schema in words for the others)
# ---------------------------------------------------------------------------------------------

_SCHEMA_V1 = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": sorted(["correct", "partial", "missing", "contradicted"])},
        "book_evidence": {"type": "string", "enum": sorted(["specific", "weak", "none"])},
        "must_include_found": {"type": "array", "items": {"type": "string"}},
        "must_include_missing": {"type": "array", "items": {"type": "string"}},
        "must_not_include_found": {"type": "array", "items": {"type": "string"}},
        "justification": {"type": "string"},
        "confidence": {"type": "string", "enum": sorted(["high", "medium", "low"])},
    },
    "required": ["verdict", "book_evidence", "must_include_found", "must_include_missing",
                 "must_not_include_found", "justification", "confidence"],
    "additionalProperties": False,
}

_SCHEMA_V2 = {
    "type": "object",
    "properties": {
        "relevant_passages": {"type": "array", "items": {"type": "object", "properties": {
            "section": {"type": "string"}, "quote": {"type": "string"}},
            "required": ["section", "quote"], "additionalProperties": False}},
        "main_finding": {"type": "string"},
        "points": {"type": "array", "items": {"type": "object", "properties": {
            "point": {"type": "string"}, "found": {"type": "boolean"},
            "quotes": {"type": "array", "items": {"type": "string"}}, "note": {"type": "string"}},
            "required": ["point", "found", "quotes", "note"], "additionalProperties": False}},
        "forbidden_points": {"type": "array", "items": {"type": "object", "properties": {
            "point": {"type": "string"}, "found": {"type": "boolean"},
            "quotes": {"type": "array", "items": {"type": "string"}}},
            "required": ["point", "found", "quotes"], "additionalProperties": False}},
        "main_finding_in_book": {"type": "string", "enum": sorted(["full", "part", "none"])},
        **_SCHEMA_V1["properties"],
    },
    "required": ["relevant_passages", "main_finding", "points", "forbidden_points", "main_finding_in_book"]
                + _SCHEMA_V1["required"],
    "additionalProperties": False,
}

# ---------------------------------------------------------------------------------------------
# Judge configurations
# ---------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class JudgeConfig:
    name: str
    system_prompt: str
    schema: dict
    verdict_rule: str            # "main_finding" (v2) or "model" (v1)
    effort: str | None           # Claude output_config.effort / OpenAI reasoning.effort
    temperature: float | None    # Gemini only; None = provider default
    max_output_tokens: int
    reasks: int                  # fresh calls allowed when a response is not valid JSON

    @property
    def prompt_sha256(self) -> str:
        return hashlib.sha256(self.system_prompt.encode("utf-8")).hexdigest()


JUDGE_V2 = JudgeConfig("haiku-5-5-v5h6", SYSTEM_PROMPT_V2, _SCHEMA_V2, "main_finding", "high", None, 32000, 2)
JUDGE_V1 = JudgeConfig("gemini-3-flash-preview-v1", SYSTEM_PROMPT_V1, _SCHEMA_V1, "model", None, 0.0, 10000, 2)
_ABLATION_NO_MUST_INCLUDE = JudgeConfig("ablation-no-must-include", SYSTEM_PROMPT_WITHOUT_MUST_INCLUDE, _SCHEMA_V1,
                                        "model", "high", 0.0, 10000, 2)

_BEDROCK_PREFIX = "bedrock/"


def judge_config_for(model: str, use_must_include_fields: bool = True) -> JudgeConfig:
    """The judge version a model name selects. Haiku 5.5 on either route is the benchmark judge (v2);
    gemini-3-flash-preview reproduces v1; anything else runs the v2 rubric as a custom judge."""
    if not use_must_include_fields:
        return _ABLATION_NO_MUST_INCLUDE
    bare = model[len(_BEDROCK_PREFIX):] if model.startswith(_BEDROCK_PREFIX) else model
    if "claude-haiku-5-5" in bare:
        return JUDGE_V2
    if bare == "gemini-3-flash-preview":
        return JUDGE_V1
    return JudgeConfig(f"custom:{model}", SYSTEM_PROMPT_V2, _SCHEMA_V2, "main_finding", "high", None, 32000, 2)


def judge_description(model: str, use_must_include_fields: bool = True) -> dict:
    """What a scorecard and a judge record carry about the judge that produced them."""
    cfg = judge_config_for(model, use_must_include_fields)
    return {"judge_model": model, "judge_name": cfg.name, "judge_prompt_sha256": cfg.prompt_sha256,
            "judge_effort": cfg.effort, "judge_verdict_rule": cfg.verdict_rule}


# ---------------------------------------------------------------------------------------------
# Errors and retries
# ---------------------------------------------------------------------------------------------

class JudgeAPIError(RuntimeError):
    """A judge call failed for good (bad credentials, or retries exhausted). Scoring must stop:
    a claim must never be recorded as "missing" because the API was unreachable."""


_RETRYABLE = ("429", "RESOURCE_EXHAUSTED", "500", "INTERNAL", "502", "503", "UNAVAILABLE",
              "504", "DEADLINE_EXCEEDED", "Connection", "connection", "timed out", "Timeout",
              # transient name resolution and credential refresh failures (laptop networks)
              "nodename nor servname", "Name or service not known", "Temporary failure in name resolution",
              "getaddrinfo", "Could not resolve API token",
              # Anthropic API
              "RateLimitError", "APIConnectionError", "APITimeoutError", "InternalServerError", "overloaded", "529",
              # Amazon Bedrock (Converse API)
              "ThrottlingException", "Too many requests", "ServiceUnavailableException", "ModelNotReadyException",
              "InternalServerException", "ModelTimeoutException", "EndpointConnectionError", "ReadTimeoutError",
              # SSO credential refresh can fail transiently when many worker threads refresh at once
              "TokenRetrievalError", "Token has expired", "refresh failed",
              # a request signed before a long connect stall reaches Bedrock after the 5-minute signature window;
              # the call never ran, so re-signing and resending is free
              "InvalidSignatureException", "Signature expired")


def _is_retryable(exc: Exception) -> bool:
    text = f"{type(exc).__name__}: {exc}"
    return any(tok in text for tok in _RETRYABLE) or "Read timeout" in text


# ---------------------------------------------------------------------------------------------
# Providers. Each returns (text, reasoning, usage, meta).
# ---------------------------------------------------------------------------------------------

_clients: dict = {}
_client_lock = threading.Lock()
_io_lock = threading.Lock()
_price_table: dict | None = None


def _get_anthropic_client():
    with _client_lock:
        if "anthropic" not in _clients:
            import anthropic
            if not os.getenv("ANTHROPIC_API_KEY"):
                raise JudgeAPIError("Judge credentials not configured: set ANTHROPIC_API_KEY for the Anthropic API, "
                                    "or use --judge-model bedrock/global.anthropic.claude-haiku-5-5 with AWS credentials.")
            # our own loop retries, so the SDK must not retry underneath it
            _clients["anthropic"] = anthropic.Anthropic(timeout=float(os.getenv("JUDGE_ANTHROPIC_TIMEOUT_S", "600")),
                                                       max_retries=0)
        return _clients["anthropic"]


def _call_anthropic(model: str, system_prompt: str, user_prompt: str, cfg: JudgeConfig):
    client = _get_anthropic_client()
    kwargs = {"model": model, "system": system_prompt, "max_tokens": cfg.max_output_tokens,
              "messages": [{"role": "user", "content": user_prompt}]}
    if cfg.effort:
        kwargs["output_config"] = {"effort": cfg.effort}
    resp = client.messages.create(**kwargs)
    text = "".join(getattr(b, "text", "") for b in resp.content if getattr(b, "type", "") == "text")
    reasoning = "".join(getattr(b, "thinking", "") or "" for b in resp.content if getattr(b, "type", "") == "thinking")
    u = resp.usage
    usage = {"input_tokens": getattr(u, "input_tokens", None), "output_tokens": getattr(u, "output_tokens", None),
             "thoughts_tokens": None, "cache_read_tokens": getattr(u, "cache_read_input_tokens", None),
             "cache_write_tokens": getattr(u, "cache_creation_input_tokens", None)}
    meta = {"provider": "anthropic", "model_id": model, "model_version": getattr(resp, "model", model),
            "request_id": getattr(resp, "_request_id", None), "stop_reason": getattr(resp, "stop_reason", None),
            "request_params": {"effort": cfg.effort, "max_output_tokens": cfg.max_output_tokens, "temperature": None,
                               "json_mode": "prompt"}}
    return text, reasoning, usage, meta


def _get_bedrock_client():
    with _client_lock:
        if "bedrock" not in _clients:
            import boto3
            from botocore.config import Config
            region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1"
            # botocore retries disabled so that every attempt is visible to the retry loop below
            _clients["bedrock"] = boto3.client(
                "bedrock-runtime", region_name=region,
                config=Config(read_timeout=int(os.getenv("JUDGE_BEDROCK_READ_TIMEOUT", "600")), connect_timeout=30,
                              retries={"total_max_attempts": 1}))
        return _clients["bedrock"]


def _call_bedrock(model_id: str, system_prompt: str, user_prompt: str, cfg: JudgeConfig):
    effort = cfg.effort or "high"
    kwargs = {
        "modelId": model_id,
        "messages": [{"role": "user", "content": [{"text": user_prompt}]}],
        "system": [{"text": system_prompt}],
        "inferenceConfig": {"maxTokens": cfg.max_output_tokens},
    }
    params = {"effort": effort, "max_output_tokens": cfg.max_output_tokens, "temperature": None}
    if "anthropic." in model_id:
        # Claude 5.5: adaptive thinking is on by default; effort is the depth control. No JSON mode,
        # the prompt's "return only JSON" instruction plus _parse_response handle the format.
        kwargs["additionalModelRequestFields"] = {"output_config": {"effort": effort}}
        params["json_mode"] = "prompt"
    elif "openai." in model_id:
        kwargs["additionalModelRequestFields"] = {"reasoning": {"effort": effort}, "text": {"format": {"strict": True}}}
        kwargs["outputConfig"] = {"textFormat": {"type": "json_schema", "structure": {
            "jsonSchema": {"name": "BookClaimJudgeResult", "schema": json.dumps(cfg.schema)}}}}
        params["json_mode"] = "json_schema"
    else:
        raise JudgeAPIError(f"unsupported Bedrock judge model id: {model_id}")
    resp = _get_bedrock_client().converse(**kwargs)
    blocks = resp["output"]["message"]["content"]
    text = "".join(b.get("text", "") for b in blocks if "text" in b)
    reasoning = "".join(((b.get("reasoningContent") or {}).get("reasoningText") or {}).get("text", "")
                        for b in blocks if "reasoningContent" in b)
    u = resp.get("usage", {})
    usage = {"input_tokens": u.get("inputTokens"), "output_tokens": u.get("outputTokens"), "thoughts_tokens": None,
             "cache_read_tokens": u.get("cacheReadInputTokens"), "cache_write_tokens": u.get("cacheWriteInputTokens")}
    meta = {"provider": "bedrock", "model_id": model_id, "model_version": model_id,
            "request_id": (resp.get("ResponseMetadata") or {}).get("RequestId"),
            "stop_reason": resp.get("stopReason"), "request_params": params}
    return text, reasoning, usage, meta


def _get_gemini_client():
    with _client_lock:
        if "gemini" not in _clients:
            from google import genai
            from google.genai import types as genai_types
            # a stalled call fails after the timeout and is retried instead of hanging a worker for ever
            http_options = genai_types.HttpOptions(timeout=int(os.getenv("JUDGE_GEMINI_TIMEOUT_MS", "300000")))
            api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
            if api_key:
                _clients["gemini"] = genai.Client(api_key=api_key, http_options=http_options)
            else:
                # Deliberately NOT GOOGLE_CLOUD_PROJECT: the local access pack exports it as the
                # emulator's fake project id, which would send the judge to a non-existent Vertex project.
                project = os.getenv("VERTEX_AI_HIGH_PROJECT_ID") or os.getenv("VERTEX_AI_PROJECT_ID")
                if not project:
                    raise JudgeAPIError("Judge credentials not configured for a Gemini model: set GEMINI_API_KEY, or "
                                        "VERTEX_AI_PROJECT_ID with gcloud application-default credentials.")
                location = os.getenv("VERTEX_AI_LOCATION") or os.getenv("GOOGLE_CLOUD_LOCATION") or "global"
                _clients["gemini"] = genai.Client(vertexai=True, project=project, location=location,
                                                  http_options=http_options)
        return _clients["gemini"]


def _call_gemini(model: str, system_prompt: str, user_prompt: str, cfg: JudgeConfig):
    from google.genai import types as genai_types
    client = _get_gemini_client()
    gcfg = {"system_instruction": system_prompt, "max_output_tokens": cfg.max_output_tokens,
            "response_mime_type": "application/json"}
    if cfg.temperature is not None:
        gcfg["temperature"] = cfg.temperature
    response = client.models.generate_content(
        model=model,
        contents=[genai_types.Content(role="user", parts=[genai_types.Part(text=user_prompt)])],
        config=genai_types.GenerateContentConfig(**gcfg),
    )
    text = response.text or ""
    finish_reason = str(response.candidates[0].finish_reason) if response.candidates else None
    um = response.usage_metadata
    usage = {"input_tokens": getattr(um, "prompt_token_count", None), "output_tokens": getattr(um, "candidates_token_count", None),
             "thoughts_tokens": getattr(um, "thoughts_token_count", None),
             "cache_read_tokens": getattr(um, "cached_content_token_count", None), "cache_write_tokens": None}
    meta = {"provider": "gemini", "model_id": model, "model_version": getattr(response, "model_version", None),
            "request_id": getattr(response, "response_id", None), "stop_reason": finish_reason,
            "request_params": {"effort": None, "max_output_tokens": cfg.max_output_tokens, "temperature": cfg.temperature,
                               "json_mode": "response_mime_type"}}
    return text, "", usage, meta


def _call_model(model: str, system_prompt: str, user_prompt: str, cfg: JudgeConfig):
    if model.startswith(_BEDROCK_PREFIX):
        return _call_bedrock(model[len(_BEDROCK_PREFIX):], system_prompt, user_prompt, cfg)
    if model.startswith("gemini"):
        return _call_gemini(model, system_prompt, user_prompt, cfg)
    if model.startswith("claude"):
        return _call_anthropic(model, system_prompt, user_prompt, cfg)
    raise JudgeAPIError(f"unsupported judge model {model!r}: use claude-<model> (Anthropic API), "
                        f"bedrock/<model id> (Amazon Bedrock) or gemini-<model> (Gemini)")


# ---------------------------------------------------------------------------------------------
# Logging, ledger and cost cap
# ---------------------------------------------------------------------------------------------

def _append_jsonl(path: str, record: dict) -> None:
    line = json.dumps(record, ensure_ascii=False, default=str) + "\n"
    with _io_lock:
        with open(path, "a", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            f.write(line)
            f.flush()
            fcntl.flock(f, fcntl.LOCK_UN)


def _price_for(model: str) -> dict | None:
    global _price_table
    path = os.getenv("JUDGE_PRICE_TABLE")
    if not path:
        return None
    if _price_table is None:
        with open(path) as f:
            _price_table = json.load(f)
    return _price_table.get(model)


def _ledger_total(path: str) -> float:
    total = 0.0
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    total += float(json.loads(line).get("cost_usd") or 0.0)
                except (ValueError, AttributeError):
                    continue
    except FileNotFoundError:
        pass
    return total


def _check_cost_cap(model: str) -> None:
    """Hard stop: once the shared ledger reaches the cap, no further call starts. Raised as a
    JudgeAPIError so the scorer aborts the pass instead of recording anything."""
    ledger, cap = os.getenv("JUDGE_LEDGER"), os.getenv("JUDGE_COST_CAP_USD")
    if ledger and cap:
        total = _ledger_total(ledger)
        if total >= float(cap):
            raise JudgeAPIError(f"cost cap reached: ledger {ledger} at ${total:.4f} >= cap ${float(cap):.2f}; "
                                f"refusing to call {model}")


def _record_call(model, cfg, claim_id, system_prompt, user_prompt, raw_text, reasoning, usage, meta,
                 latency_s, attempts, errors, result, parse_failed, reask=0, superseded=False, extra=None) -> None:
    raw_log, ledger = os.getenv("JUDGE_RAW_LOG"), os.getenv("JUDGE_LEDGER")
    if not raw_log and not ledger:
        return
    price = _price_for(model) or {}
    u = usage or {}
    inp, out, thoughts, cread, cwrite = (u.get("input_tokens") or 0), (u.get("output_tokens") or 0), \
        (u.get("thoughts_tokens") or 0), (u.get("cache_read_tokens") or 0), (u.get("cache_write_tokens") or 0)
    cost = None
    if price:
        # Bedrock reports cached-prefix writes separately from input tokens (OpenAI models cache the whole prompt
        # implicitly, so input_tokens can be near zero and cache_write_tokens carry the prompt); Gemini folds cached
        # reads into prompt_token_count. Cache writes bill at 1.25x the input rate unless the table says otherwise.
        gemini_cached = cread if (meta or {}).get("provider") == "gemini" else 0
        cost = (inp - gemini_cached) * price.get("in", 0) / 1e6 \
            + cread * price.get("cache_read", price.get("in", 0)) / 1e6 \
            + cwrite * price.get("cache_write", 1.25 * price.get("in", 0)) / 1e6 \
            + (out + thoughts) * price.get("out", 0) / 1e6
    now = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
    prompt_hash = hashlib.sha256((system_prompt + "\n\x00\n" + user_prompt).encode("utf-8")).hexdigest()
    if ledger:
        _append_jsonl(ledger, {"ts": now, "model": model, "claim_id": claim_id, "input_tokens": inp, "output_tokens": out,
                               "thoughts_tokens": thoughts, "cache_read_tokens": cread, "cache_write_tokens": cwrite,
                               "cost_usd": cost, "run_tag": os.getenv("JUDGE_RUN_TAG")})
    if raw_log:
        _append_jsonl(raw_log, {
            "ts": now, "model": model, "judge_name": cfg.name, "claim_id": claim_id, "run_tag": os.getenv("JUDGE_RUN_TAG"),
            "provider": (meta or {}).get("provider"), "model_id": (meta or {}).get("model_id"),
            "model_version": (meta or {}).get("model_version"), "request_id": (meta or {}).get("request_id"),
            "request_params": (meta or {}).get("request_params"), "prompt_sha256": prompt_hash,
            "system_prompt_sha256": cfg.prompt_sha256,
            "system_prompt_chars": len(system_prompt), "user_prompt_chars": len(user_prompt),
            "attempts": attempts, "errors": errors, "latency_s": round(latency_s, 3),
            "stop_reason": (meta or {}).get("stop_reason"), "usage": usage, "cost_usd": cost,
            "reasoning": reasoning, "raw_text": raw_text, "parse_failed": parse_failed, "result": result,
            "reask": reask, "superseded": superseded,
            **(extra or {}),
        })


# ---------------------------------------------------------------------------------------------
# Prompt assembly and response handling
# ---------------------------------------------------------------------------------------------

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
    """The JSON object in the response, or None when there is none (a JSON array counts as none)."""
    text = text.strip()
    if text.startswith("```"):
        lines = [line for line in text.splitlines() if not line.startswith("```")]
        text = "\n".join(lines)
    parsed = None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                parsed = json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                parsed = None
    return parsed if isinstance(parsed, dict) else None


def _main_finding_verdict(parsed: dict) -> tuple[str | None, str]:
    """v2 verdict rule: contradicted if any must_not_include point is found, otherwise the main-finding
    decision decides. Returns (verdict, note); verdict None keeps the model's own verdict."""
    forbidden = parsed.get("forbidden_points") or []
    if any(bool(f.get("found")) for f in forbidden if isinstance(f, dict)):
        return "contradicted", "a must_not_include point was found"
    mf = str(parsed.get("main_finding_in_book") or "").strip().lower()
    if mf not in ("full", "part", "none"):
        return None, f"main_finding_in_book missing or invalid ({mf!r}); model verdict kept"
    return {"full": "correct", "part": "partial", "none": "missing"}[mf], f"main finding {mf}"


def _apply_verdict_rule(parsed: dict, cfg: JudgeConfig) -> tuple[dict, dict | None]:
    if cfg.verdict_rule != "main_finding":
        return parsed, None
    model_verdict = parsed.get("verdict")
    dv, note = _main_finding_verdict(parsed)
    if dv is not None:
        pts = [p for p in parsed.get("points") or [] if isinstance(p, dict)]
        parsed = dict(parsed, verdict=dv,
                      must_include_found=[str(p.get("point", "")) for p in pts if p.get("found")],
                      must_include_missing=[str(p.get("point", "")) for p in pts if not p.get("found")],
                      must_not_include_found=[str(f.get("point", "")) for f in parsed.get("forbidden_points") or []
                                              if isinstance(f, dict) and f.get("found")])
    return parsed, {"model_verdict": model_verdict, "rule_verdict": dv, "rule_note": note}


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


# ---------------------------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------------------------

def evaluate_claim_llm(
    claim: dict,
    book_text: str,
    model: str = DEFAULT_MODEL,
    use_must_include_fields: bool = True,
) -> dict:
    cfg = judge_config_for(model, use_must_include_fields)
    system_prompt = cfg.system_prompt
    user_prompt = _build_user_prompt(claim, book_text, use_must_include_fields)
    max_attempts = int(os.getenv("JUDGE_MAX_ATTEMPTS") or 10)
    claim_id = claim.get("claim_id", "?")
    reask = 0
    while True:
        errors: list[str] = []
        t0 = time.time()
        for attempt in range(1, max_attempts + 1):
            _check_cost_cap(model)
            t0 = time.time()
            try:
                raw_text, reasoning, usage, meta = _call_model(model, system_prompt, user_prompt, cfg)
                break
            except JudgeAPIError:
                raise
            except Exception as exc:
                errors.append(f"attempt {attempt}: {type(exc).__name__}: {str(exc)[:300]}")
                if not _is_retryable(exc):
                    _record_call(model, cfg, claim_id, system_prompt, user_prompt, "", "", None, None, time.time() - t0,
                                 attempt, errors, None, None, reask)
                    raise JudgeAPIError(f"claim {claim_id}: {exc}") from exc
                if attempt == max_attempts:
                    _record_call(model, cfg, claim_id, system_prompt, user_prompt, "", "", None, None, time.time() - t0,
                                 attempt, errors, None, None, reask)
                    raise JudgeAPIError(f"claim {claim_id}: still failing after {attempt} attempts: {exc}") from exc
                # rate limits start at 5 s, other transient errors at 2 s; doubling, capped at 60 s, with jitter
                base = 5 if any(t in str(exc) for t in ("429", "RESOURCE_EXHAUSTED", "Throttling", "Too many requests",
                                                        "RateLimit", "overloaded", "529")) else 2
                time.sleep(min(60, base * 2 ** (attempt - 1)) + random.random())

        parsed = _parse_response(raw_text)
        if parsed is None and reask < cfg.reasks:
            # a response that is not a JSON object is kept on record and asked again with a fresh call
            _record_call(model, cfg, claim_id, system_prompt, user_prompt, raw_text, reasoning, usage, meta,
                         time.time() - t0, attempt, errors, None, True, reask, superseded=True)
            reask += 1
            continue
        break

    extra = None
    if parsed is not None:
        parsed, extra = _apply_verdict_rule(parsed, cfg)
    fallback = None
    if parsed is None:
        fallback = f"Judge returned no JSON object in {reask + 1} call(s); recorded as missing"
    result = _normalize_result(parsed, claim, fallback_reason=fallback, use_must_include_fields=use_must_include_fields)
    _record_call(model, cfg, claim_id, system_prompt, user_prompt, raw_text, reasoning, usage, meta, time.time() - t0,
                 attempt, errors, result, parsed is None, reask, extra=extra)
    return result
