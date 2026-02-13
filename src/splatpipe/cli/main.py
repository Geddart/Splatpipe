"""Splatpipe CLI — Typer application with subcommands."""

import typer

from .init_cmd import init
from .clean_cmd import clean
from .train_cmd import train
from .assemble_cmd import assemble
from .deploy_cmd import export
from .serve_cmd import serve
from .run_cmd import run
from .web_cmd import web
from .status_cmd import status

app = typer.Typer(
    name="splatpipe",
    help="Automated photogrammetry-to-Gaussian-splatting pipeline.",
    no_args_is_help=True,
)

app.command()(init)
app.command()(clean)
app.command()(train)
app.command()(assemble)
app.command(name="export")(export)
app.command()(serve)
app.command()(run)
app.command()(web)
app.command()(status)


if __name__ == "__main__":
    app()
