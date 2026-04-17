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
from .path_cmd import path_import, path_import_colmap
from .build_lod_cmd import build_lod_cmd

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
app.command(name="path-import")(path_import)
app.command(name="path-import-colmap")(path_import_colmap)
app.command(name="build-lod")(build_lod_cmd)


if __name__ == "__main__":
    app()
