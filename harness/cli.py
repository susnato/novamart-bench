from __future__ import annotations

import click

from harness.commands.run import run
from harness.commands.validate import validate
from harness.commands.scaffold import scaffold
from harness.commands.export_claims import export_claims
from harness.commands.check_claim import check_claim
from harness.commands.diff import diff_cmd


@click.group()
@click.version_option(version="2.2.1")
def cli():
    """Tribal Knowledge Eval — evaluate tribal knowledge books against gold claim suites."""


cli.add_command(run)
cli.add_command(validate)
cli.add_command(scaffold)
cli.add_command(export_claims)
cli.add_command(check_claim)
cli.add_command(diff_cmd)


if __name__ == "__main__":
    cli()
