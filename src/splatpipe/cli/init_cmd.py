"""splatpipe init — Create a new project from alignment data."""

import os
import shutil
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel

from ..colmap.parsers import detect_source_type, ALIGNMENT_FORMAT_LABELS
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
        help="Path to alignment data (directory or .psht file)",
        exists=True,
        file_okay=True,
        resolve_path=True,
    ),
    name: str = typer.Option(
        None,
        "--name", "-n",
        help="Project name (defaults to directory name)",
    ),
    trainer: str = typer.Option(
        None,
        "--trainer", "-t",
        help="Training backend (postshot, lichtfeld, passthrough). "
             "Defaults to passthrough for .psht/.ply, postshot otherwise.",
    ),
    lods: str = typer.Option(
        None,
        "--lods",
        help="LOD levels as comma-separated values (e.g. '25M,10M,5M,2M,1M,500K'). "
             "Defaults to 6 levels for trained pipelines, single LOD for passthrough.",
    ),
    output: Path = typer.Option(
        None,
        "--output", "-o",
        help="Project directory (defaults to current dir / name)",
    ),
) -> None:
    """Create a new splatpipe project from alignment data."""
    # Detect source type (file or directory)
    fmt = detect_source_type(colmap_dir)
    if fmt == "unknown":
        console.print(
            "[yellow]Warning: No recognized alignment format found.[/yellow]\n"
            "[yellow]Project will be created — your trainer may still handle these files.[/yellow]"
        )
    else:
        console.print(f"[green]Detected format:[/green] {ALIGNMENT_FORMAT_LABELS[fmt]}")

    # Determine project name and directory
    if name is None:
        if colmap_dir.is_file():
            name = colmap_dir.stem
        else:
            name = colmap_dir.parent.name if colmap_dir.name.lower() == "colmap" else colmap_dir.name

    if output is None:
        output = Path.cwd() / name

    # Resolve trainer default based on source format
    if trainer is None:
        trainer = "passthrough" if fmt in ("postshot", "ply") else "postshot"

    # Parse LOD levels (passthrough always uses a single LOD)
    if lods is None:
        lod_levels = None  # Project.create picks the right default for the trainer
    else:
        lod_levels = _parse_lods(lods)
        if trainer == "passthrough" and len(lod_levels) > 1:
            console.print(
                f"[yellow]Passthrough trainer uses a single LOD — "
                f"trimming {len(lod_levels)} levels to just '{lod_levels[0]['name']}'.[/yellow]"
            )
            lod_levels = [lod_levels[0]]

    # Create project
    project = Project.create(
        output,
        name,
        trainer=trainer,
        lod_levels=lod_levels,
        colmap_source=str(colmap_dir),
        source_type=fmt,
    )

    if fmt == "postshot":
        # Copy .psht file into project (never modify the original)
        source_dest = project.get_folder("01_colmap_source") / "source.psht"
        size_gb = colmap_dir.stat().st_size / 1e9
        console.print(f"Copying .psht file ({size_gb:.1f} GB)...")
        shutil.copy2(colmap_dir, source_dest)
    elif fmt == "ply":
        # Copy .ply file into project (never modify the original)
        source_dest = project.get_folder("01_colmap_source") / "source.ply"
        size_mb = colmap_dir.stat().st_size / 1e6
        console.print(f"Copying .ply file ({size_mb:.1f} MB)...")
        shutil.copy2(colmap_dir, source_dest)
    else:
        # Create symlink/junction from 01_colmap_source to the actual data
        source_link = project.get_folder("01_colmap_source")
        if source_link.exists() and not any(source_link.iterdir()):
            source_link.rmdir()
            _create_link(source_link, colmap_dir)

    # Display summary
    source_label = str(colmap_dir)
    actual_levels = project.lod_levels
    console.print(Panel(
        f"[bold]{name}[/bold]\n\n"
        f"Location:  {output}\n"
        f"Source:    {source_label}\n"
        f"Trainer:   {trainer}\n"
        f"LODs:      {len(actual_levels)} levels\n"
        f"           {', '.join(lod['name'] for lod in actual_levels)}",
        title="Project created",
        border_style="green",
    ))

    console.print("\nNext steps:")
    if trainer == "passthrough":
        console.print("  1. [cyan]splatpipe train[/cyan]    — Extract/copy splat (no training)")
        console.print("  2. [cyan]splatpipe assemble[/cyan] — Build streaming output")
        console.print("  3. [cyan]splatpipe export[/cyan]   — Upload to Bunny CDN or copy to folder")
    elif fmt == "postshot":
        console.print("  1. [cyan]splatpipe train[/cyan]   — Train Gaussian splats")
        console.print("  2. Review PLYs in SuperSplat (superspl.at/editor)")
        console.print("  3. [cyan]splatpipe assemble[/cyan] — Build LOD output")
    else:
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
