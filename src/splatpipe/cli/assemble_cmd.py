"""splatpipe assemble — Build LOD streaming output from reviewed PLYs."""

from pathlib import Path

import typer
from rich.console import Console

from ..core.config import load_project_config
from ..core.project import Project
from ..steps.lod_assembly import LodAssemblyStep

console = Console()


def assemble(
    project: Path = typer.Option(
        None,
        "--project", "-p",
        help="Project directory (auto-detected if not specified)",
    ),
) -> None:
    """Build LOD streaming output (lod-meta.json + SOG chunks) from reviewed PLYs."""
    proj = _resolve_project(project)
    config = load_project_config(proj.config_path)

    review_dir = proj.get_folder("04_review")
    plys = list(review_dir.glob("lod*_reviewed.ply"))
    if not plys:
        console.print(f"[red]No reviewed PLY files in {review_dir}[/red]")
        console.print("Train splats first, then review in SuperSplat.")
        raise typer.Exit(1)

    console.print(f"[bold]Assembling LOD output for:[/bold] {proj.name}")
    console.print(f"Input PLYs: {len(plys)} reviewed files")

    step = LodAssemblyStep(proj, config)

    with console.status("[bold green]Running splat-transform..."):
        result = step.execute()

    summary = result["summary"]

    if summary.get("success"):
        console.print("\n[green]Assembly complete[/green]")
        console.print(f"  LODs: {summary['lod_count']}")
        console.print(f"  Chunks: {summary['chunk_count']}")
        console.print(f"  Output: {proj.get_folder('05_output')}")
        console.print("\nNext: [cyan]splatpipe deploy --target bunny[/cyan]")
        console.print("  Or: [cyan]splatpipe serve[/cyan] for local preview")
    else:
        console.print("\n[red]Assembly failed[/red]")
        stderr = result.get("lod_streaming", {}).get("stderr", "")
        if stderr:
            console.print(f"[dim]{stderr[:500]}[/dim]")


def _resolve_project(project_path: Path | None) -> Project:
    if project_path:
        return Project(project_path)
    return Project.find()
