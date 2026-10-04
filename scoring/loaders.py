from __future__ import annotations

from pathlib import Path

import yaml


def resolve_claims_dir(path: Path) -> tuple[Path, Path]:
    """Return (claims_dir, benchmark_root) for either claims layout.

    This repo keeps the gold claims at the root, in ``claims/*.yaml``, so passing ``claims``
    (or any directory that holds the claim YAMLs directly) works. The original harness layout,
    ``<benchmark>/gold/claims/*.yaml``, is still accepted so scaffolded benchmarks and the
    reviewed copy keep working; both ``<benchmark>`` and ``<benchmark>/gold/claims`` resolve.
    ``benchmark_root`` is where ``eval-run-outputs/`` goes: the parent of a bare claims
    directory, or ``<benchmark>`` for the nested layout, never inside the claims folder.
    """
    path = Path(path)
    nested = path / "gold" / "claims"
    if nested.is_dir():
        return nested, path
    if path.is_dir() and any(path.glob("*.yaml")):
        if path.name == "claims" and path.parent.name == "gold":
            return path, path.parent.parent
        return path, path.parent
    raise FileNotFoundError(
        f"Claims directory not found: {path}. Pass the directory that holds the claim YAMLs "
        f"(in this repo: claims/), or a benchmark directory laid out as <benchmark>/gold/claims/*.yaml"
    )


def load_claims(benchmark_dir: Path) -> list[dict]:
    claims_dir, _ = resolve_claims_dir(Path(benchmark_dir))

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
