from __future__ import annotations

import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from scoring.judges.llm_judge import evaluate_claim_llm, JudgeAPIError


def evaluate_claim(
    claim: dict,
    book_text: str,
    model: str = "gemini-3-flash-preview",
    use_must_include_fields: bool = True,
) -> dict:
    return evaluate_claim_llm(claim, book_text, model=model, use_must_include_fields=use_must_include_fields)


def evaluate_all_claims(
    claims: list[dict],
    book_text: str,
    model: str = "gemini-3-flash-preview",
    max_workers: int = 10,
    use_must_include_fields: bool = True,
) -> list[dict]:
    total = len(claims)
    if total == 0:
        return []

    workers = max(1, min(max_workers, total))
    print(
        f"Evaluating {total} claims with {workers} parallel workers "
        f"(model={model}, use_must_include_fields={use_must_include_fields})...",
        file=sys.stderr,
    )

    results: list[dict | None] = [None] * total
    completed_lock = threading.Lock()
    completed = {"n": 0}

    def _evaluate_one(i: int) -> tuple[int, dict]:
        claim = claims[i]
        claim_id = claim.get("claim_id", f"unknown_{i}")
        result = evaluate_claim_llm(claim, book_text, model=model, use_must_include_fields=use_must_include_fields)
        result["claim_id"] = claim_id
        return i, result

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(_evaluate_one, i) for i in range(total)]
        for future in as_completed(futures):
            try:
                idx, result = future.result()
            except JudgeAPIError:
                executor.shutdown(wait=False, cancel_futures=True)
                raise
            except Exception as exc:
                # Should not happen since llm_judge handles its own errors,
                # but defensive: synthesize a failure result.
                idx = -1
                result = {
                    "claim_id": "unknown",
                    "verdict": "missing",
                    "book_evidence": "none",
                    "must_include_found": [],
                    "must_include_missing": [],
                    "must_not_include_found": [],
                    "justification": f"Worker error: {exc}",
                    "confidence": "low",
                }
                # Find first None slot for this orphan result
                for i, r in enumerate(results):
                    if r is None:
                        idx = i
                        break

            results[idx] = result

            with completed_lock:
                completed["n"] += 1
                n = completed["n"]
            print(
                f"  [{n}/{total}] {result['claim_id']:50s} -> {result['verdict']}",
                file=sys.stderr,
            )

    return [r for r in results if r is not None]
