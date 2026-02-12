"""splatpipe clean — Run COLMAP cleaning on project data."""

from pathlib import Path

import typer
from rich.console import Console

from ..core.config import load_project_config
from ..core.constants import STEP_CLEAN
from ..core.project import Project
from ..steps.colmap_clean import ColmapCleanStep

console = Console()


def clean(
    project: Path = typer.Option(
        None,
        "--project", "-p",
        help="Project directory (auto-detected if not specified)",
    ),
) -> None:
    """Clean COLMAP data: remove outlier cameras, filter points, fix references."""
    proj = _resolve_project(project)
    config = load_project_config(proj.config_path)

    # Check prerequisites
    colmap_dir = proj.colmap_dir()
    required = ["cameras.txt", "images.txt", "points3D.txt"]
    missing = [f for f in required if not (colmap_dir / f).exists()]
    if missing:
        console.print(f"[red]Missing COLMAP files:[/red] {', '.join(missing)}")
        console.print(f"Expected in: {colmap_dir}")
        raise typer.Exit(1)

    # Check if already run
    prev_status = proj.get_step_status(STEP_CLEAN)
    if prev_status == "completed":
        console.print("[yellow]Clean step already completed. Re-running...[/yellow]")

    console.print(f"[bold]Cleaning COLMAP data for:[/bold] {proj.name}")
    console.print(f"Source: {colmap_dir}")

    step = ColmapCleanStep(proj, config)

    with console.status("[bold green]Running COLMAP clean..."):
        result = step.execute()

    summary = result["summary"]
    console.print()
    console.print(f"  Cameras:  {summary['cameras_kept']} kept, "
                  f"{summary['cameras_removed']} outliers removed "
                  f"(of {summary['cameras_total']})")

    if summary.get("points_before") is not None:
        console.print(f"  Points:   {summary['points_after']:,} kept, "
                      f"{summary['points_before'] - summary['points_after']:,} removed "
                      f"(of {summary['points_before']:,})")
    else:
        console.print("  Points:   [dim]no PLY found, skipped KD-tree filter[/dim]")

    console.print(f"  Refs:     {summary['points2d_kept']:,} kept, "
                  f"{summary['points2d_cleaned']:,} cleaned "
                  f"(of {summary['points2d_total']:,})")

    console.print(f"\n[green]Done in {result['duration_s']:.1f}s[/green]")
    console.print(f"Debug: {proj.get_folder('02_colmap_clean') / 'clean_debug.json'}")


def _resolve_project(project_path: Path | None) -> Project:
    """Find project from explicit path or auto-discovery."""
    if project_path:
        return Project(project_path)
    return Project.find()
