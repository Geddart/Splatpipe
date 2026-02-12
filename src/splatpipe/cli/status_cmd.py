"""splatpipe status — Show project status."""

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from ..core.constants import STEP_CLEAN, STEP_TRAIN, STEP_ASSEMBLE, STEP_DEPLOY
from ..core.project import Project

console = Console()

STEP_ORDER = [STEP_CLEAN, STEP_TRAIN, STEP_ASSEMBLE, STEP_DEPLOY]

STATUS_STYLES = {
    "completed": "[green]completed[/green]",
    "failed": "[red]failed[/red]",
    "running": "[yellow]running[/yellow]",
    None: "[dim]pending[/dim]",
}


def status(
    project: Path = typer.Option(
        None,
        "--project", "-p",
        help="Project directory (auto-detected if not specified)",
    ),
) -> None:
    """Show the current status of a splatpipe project."""
    proj = _resolve_project(project)

    console.print(f"\n[bold]{proj.name}[/bold]")
    console.print(f"Location: {proj.root}")
    console.print(f"Trainer:  {proj.trainer}")
    console.print(f"LODs:     {len(proj.lod_levels)} levels")
    console.print()

    table = Table(show_header=True, header_style="bold")
    table.add_column("Step", style="cyan")
    table.add_column("Status")
    table.add_column("Details")

    for step_name in STEP_ORDER:
        step_status = proj.get_step_status(step_name)
        styled = STATUS_STYLES.get(step_status, f"[yellow]{step_status}[/yellow]")
        detail = _get_step_detail(proj, step_name)
        table.add_row(step_name, styled, detail)

    console.print(table)

    # Show LOD levels
    console.print("\n[bold]LOD Levels:[/bold]")
    for lod in proj.lod_levels:
        splats_m = lod["max_splats"] / 1_000_000
        console.print(f"  {lod['name']}: {splats_m:.1f}M splats")


def _get_step_detail(proj: Project, step_name: str) -> str:
    """Get summary detail for a step."""
    summary = proj.get_step_summary(step_name)
    if summary is None:
        return ""

    if step_name == STEP_CLEAN:
        kept = summary.get("cameras_kept", "?")
        removed = summary.get("cameras_removed", "?")
        return f"{kept} cameras kept, {removed} removed"

    if step_name == STEP_TRAIN:
        lods = summary.get("lod_count", "?")
        ok = summary.get("all_completed", False)
        return f"{lods} LODs {'all OK' if ok else 'some failed'}"

    if step_name == STEP_ASSEMBLE:
        chunks = summary.get("chunk_count", "?")
        ok = summary.get("success", False)
        return f"{chunks} chunks {'OK' if ok else 'failed'}"

    return ""


def _resolve_project(project_path: Path | None) -> Project:
    """Find project from explicit path or auto-discovery."""
    if project_path:
        return Project(project_path)
    return Project.find()
