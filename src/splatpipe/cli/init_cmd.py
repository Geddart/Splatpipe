"""splatpipe init — Create a new project from COLMAP data."""

import os
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel

from ..core.project import Project

console = Console()


def _parse_lods(lods_str: str) -> list[dict]:
    """Parse LOD string like '25M,10M,5M,2M,1M,500K' into LOD level dicts."""
    levels = []
    for i, part in enumerate(lods_str.split(",")):
        part = part.strip().upper()
        if part.endswith("M"):
            splats = int(float(part[:-1]) * 1_000_000)
        elif part.endswith("K"):
            splats = int(float(part[:-1]) * 1_000)
        else:
            splats = int(part)
        name = f"lod{i}"
        levels.append({"name": name, "max_splats": splats})
    return levels


def init(
    colmap_dir: Path = typer.Argument(
        ...,
        help="Path to COLMAP data directory (with cameras.txt, images.txt, points3D.txt)",
        exists=True,
        file_okay=False,
        resolve_path=True,
    ),
    name: str = typer.Option(
        None,
        "--name", "-n",
        help="Project name (defaults to directory name)",
    ),
    trainer: str = typer.Option(
        "postshot",
        "--trainer", "-t",
        help="Training backend to use",
    ),
    lods: str = typer.Option(
        "25M,10M,5M,2M,1M,500K",
        "--lods",
        help="LOD levels as comma-separated values (e.g. '25M,10M,5M,2M,1M,500K')",
    ),
    output: Path = typer.Option(
        None,
        "--output", "-o",
        help="Project directory (defaults to current dir / name)",
    ),
) -> None:
    """Create a new splatpipe project from COLMAP data."""
    # Validate COLMAP directory
    required_files = ["cameras.txt", "images.txt", "points3D.txt"]
    missing = [f for f in required_files if not (colmap_dir / f).exists()]
    if missing:
        console.print(
            f"[red]Missing COLMAP files in {colmap_dir}:[/red] {', '.join(missing)}"
        )
        raise typer.Exit(1)

    # Determine project name and directory
    if name is None:
        name = colmap_dir.parent.name if colmap_dir.name.lower() == "colmap" else colmap_dir.name

    if output is None:
        output = Path.cwd() / name

    # Parse LOD levels
    lod_levels = _parse_lods(lods)

    # Create project
    project = Project.create(
        output,
        name,
        trainer=trainer,
        lod_levels=lod_levels,
        colmap_source=str(colmap_dir),
    )

    # Create symlink from 01_colmap_source to the actual COLMAP data
    source_link = project.get_folder("01_colmap_source")
    if source_link.exists() and not any(source_link.iterdir()):
        # Remove empty dir and replace with symlink
        source_link.rmdir()
        _create_link(source_link, colmap_dir)

    # Display summary
    console.print(Panel(
        f"[bold]{name}[/bold]\n\n"
        f"Location:  {output}\n"
        f"COLMAP:    {colmap_dir}\n"
        f"Trainer:   {trainer}\n"
        f"LODs:      {len(lod_levels)} levels\n"
        f"           {', '.join(lod['name'] for lod in lod_levels)}",
        title="Project created",
        border_style="green",
    ))

    console.print("\nNext steps:")
    console.print("  1. [cyan]splatpipe clean[/cyan]   — Clean COLMAP data")
    console.print("  2. [cyan]splatpipe train[/cyan]   — Train Gaussian splats")
    console.print("  3. Review PLYs in SuperSplat (superspl.at/editor)")
    console.print("  4. [cyan]splatpipe assemble[/cyan] — Build LOD output")


def _create_link(link_path: Path, target: Path) -> None:
    """Create a directory junction (Windows) or symlink (Unix)."""
    if os.name == "nt":
        # Use junction on Windows (no admin required)
        import subprocess
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link_path), str(target)],
            check=True, capture_output=True,
        )
    else:
        link_path.symlink_to(target, target_is_directory=True)
