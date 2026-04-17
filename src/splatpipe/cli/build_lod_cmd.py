"""splatpipe build-lod — Manually prime the Spark .rad cache for a project."""

from pathlib import Path

import typer
from rich.console import Console

from ..core.constants import FOLDER_REVIEW
from ..core.project import Project
from ..viewers.spark.build_lod import BuildLodError, build, verify_toolchain

console = Console()


def build_lod_cmd(
    project: Path = typer.Option(
        None, "--project", "-p", help="Project directory (auto-detected if not specified)"
    ),
    quick: bool = typer.Option(
        False, "--quick",
        help="Use the faster `tiny-lod` algorithm instead of the default high-quality `bhatt-lod`",
    ),
    spark_repo: Path = typer.Option(
        None, "--spark-repo",
        help="Path to the sparkjsdev/spark clone (default: $SPARK_REPO env var)",
    ),
) -> None:
    """Pre-build the Spark .rad LoD tree for a project's lod0 PLY.

    Useful to warm the cache before running `splatpipe assemble` (so the slow
    Rust build-lod work runs once, not during every assemble). Idempotent:
    re-runs are cache hits.
    """
    proj = _resolve_project(project)
    review_dir = proj.get_folder(FOLDER_REVIEW)

    enabled = [lod for lod in proj.lod_levels if lod.get("enabled", True)]
    if not enabled:
        console.print(f"[red]No enabled LODs in project[/red]")
        raise typer.Exit(1)
    lod_name = enabled[0]["name"]

    # Find the matching reviewed PLY (lod0_reviewed.ply by convention)
    candidates = list(review_dir.glob(f"{lod_name}_reviewed.ply"))
    if not candidates:
        console.print(
            f"[red]No reviewed PLY for {lod_name} in {review_dir}.[/red]\n"
            f"Train + review the project first."
        )
        raise typer.Exit(1)
    input_ply = candidates[0]

    try:
        info = verify_toolchain(spark_repo)
    except BuildLodError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    console.print(f"[bold]build-lod[/bold]")
    console.print(f"  Toolchain : {info['command'][0]} ({info['version']}, {'cargo' if info['is_cargo'] else 'binary'})")
    console.print(f"  Input     : {input_ply.name} ({input_ply.stat().st_size / (1<<20):.1f} MB)")
    console.print(f"  Algorithm : {'quick (tiny-lod)' if quick else 'quality (bhatt-lod)'}")

    try:
        rad_path = build(
            input_ply,
            quality=not quick,
            on_progress=lambda line: console.print(f"  [dim]{line}[/dim]"),
            spark_repo=spark_repo,
        )
    except BuildLodError as e:
        console.print(f"\n[red]Build failed:[/red] {e}")
        raise typer.Exit(1)

    size_mb = rad_path.stat().st_size / (1 << 20)
    console.print(f"\n[green]Done[/green] → {rad_path} ({size_mb:.1f} MB)")


def _resolve_project(project_path: Path | None) -> Project:
    if project_path:
        return Project(project_path)
    return Project.find()
