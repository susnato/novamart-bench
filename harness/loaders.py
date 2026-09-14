from __future__ import annotations

from pathlib import Path

import yaml


def load_claims(benchmark_dir: Path) -> list[dict]:
    claims_dir = benchmark_dir / "gold" / "claims"
    if not claims_dir.is_dir():
        raise FileNotFoundError(
            f"Claims directory not found: {claims_dir}. "
            f"Expected structure: {benchmark_dir}/gold/claims/*.yaml"
        )

    all_claims: list[dict] = []
    for path in sorted(claims_dir.glob("*.yaml")):
        with open(path) as f:
            data = yaml.safe_load(f)
        if isinstance(data, list):
            all_claims.extend(data)
        elif isinstance(data, dict):
            all_claims.append(data)

    return all_claims


def load_book(book_path: Path) -> str:
    if not book_path.is_file():
        raise FileNotFoundError(f"Book file not found: {book_path}")
    return book_path.read_text(encoding="utf-8")
