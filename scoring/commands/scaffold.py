from __future__ import annotations

import shutil
from pathlib import Path

import click

PACKAGE_ROOT = Path(__file__).resolve().parent.parent.parent


@click.command("add-new-benchmark")
@click.argument("name")
@click.option("--customer", required=True, help="Customer name")
@click.option("--system", required=True, help="System name")
@click.option("--base-dir", default="benchmarks", help="Base directory for benchmarks")
def scaffold(name: str, customer: str, system: str, base_dir: str) -> None:
    """Scaffold a new benchmark from template."""
    base = Path(base_dir)
    if not base.is_absolute():
        base = PACKAGE_ROOT / base
    template_dir = base / "_template"

    if not template_dir.is_dir():
        click.echo(f"Error: template directory not found at {template_dir}", err=True)
        raise SystemExit(1)

    target = base / name
    if target.exists():
        click.echo(f"Error: directory already exists: {target}", err=True)
        raise SystemExit(1)

    subdirs = [
        "gold/claims",
        "books",
        "eval-run-outputs",
    ]
    for sub in subdirs:
        (target / sub).mkdir(parents=True, exist_ok=True)

    for gitkeep_dir in ("books", "eval-run-outputs"):
        (target / gitkeep_dir / ".gitkeep").touch()

    replacements = {"{{CUSTOMER}}": customer, "{{SYSTEM}}": system}

    for tmpl_path in template_dir.rglob("*"):
        if not tmpl_path.is_file():
            continue

        rel = tmpl_path.relative_to(template_dir)
        dest_name = rel.name.replace(".template", "")
        dest = target / rel.parent / dest_name

        dest.parent.mkdir(parents=True, exist_ok=True)

        if tmpl_path.suffix in (".yaml", ".md", ".template"):
            content = tmpl_path.read_text(encoding="utf-8")
            for placeholder, value in replacements.items():
                content = content.replace(placeholder, value)
            dest.write_text(content, encoding="utf-8")
        else:
            shutil.copy2(tmpl_path, dest)

    claim_example = template_dir / "gold" / "claims" / "_template_claim.yaml.example"

    if claim_example.is_file():
        content = claim_example.read_text(encoding="utf-8")
        for placeholder, value in replacements.items():
            content = content.replace(placeholder, value)
        dest = target / "gold" / claim_example.name
        dest.write_text(content, encoding="utf-8")

    click.echo(f"Scaffolded benchmark: {target}")
    click.echo("")
    click.echo("Created:")
    for p in sorted(target.rglob("*")):
        rel = p.relative_to(target)
        if p.is_dir():
            click.echo(f"  {rel}/")
        else:
            click.echo(f"  {rel}")
