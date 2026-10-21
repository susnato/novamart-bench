from __future__ import annotations

import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from scoring.judges.llm_judge import DEFAULT_MODEL, evaluate_claim_llm, JudgeAPIError


def evaluate_claim(
    claim: dict,
    book_text: str,
    model: str = DEFAULT_MODEL,
    use_must_include_fields: bool = True,
) -> dict:
    return evaluate_claim_llm(claim, book_text, model=model, use_must_include_fields=use_must_include_fields)


def evaluate_all_claims(
    claims: list[dict],
    book_text: str,
    model: str = DEFAULT_MODEL,
    max_workers: int = 10,
    use_must_include_fields: bool = True,
) -> list[dict]:
    """One judge call per claim, in parallel. Every claim comes back with its own result, or the pass
    fails: an unexpected error in a worker is raised as JudgeAPIError, never scored as missing."""
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
        futures = {executor.submit(_evaluate_one, i): i for i in range(total)}
        for future in as_completed(futures):
            try:
                idx, result = future.result()
            except JudgeAPIError:
                executor.shutdown(wait=False, cancel_futures=True)
                raise
            except Exception as exc:
                executor.shutdown(wait=False, cancel_futures=True)
                claim_id = claims[futures[future]].get("claim_id", f"unknown_{futures[future]}")
                raise JudgeAPIError(f"claim {claim_id}: judge worker failed: {type(exc).__name__}: {exc}") from exc

            results[idx] = result

            with completed_lock:
                completed["n"] += 1
                n = completed["n"]
            print(
                f"  [{n}/{total}] {result['claim_id']:50s} -> {result['verdict']}",
                file=sys.stderr,
            )

    missing = [claims[i].get("claim_id") for i, r in enumerate(results) if r is None]
    if missing:
        raise JudgeAPIError(f"judge returned no result for {len(missing)} claim(s): {missing[:5]}")
    return [r for r in results if r is not None]
