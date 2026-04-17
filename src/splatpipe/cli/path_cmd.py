"""splatpipe path-import / path-import-colmap — Import camera paths."""

from pathlib import Path

import typer
from rich.console import Console

from ..core.path_io import from_colmap, from_gltf, mutate_paths
from ..core.project import Project

console = Console()


def path_import(
    gltf_file: Path = typer.Argument(..., help="Path to .glb or .gltf with animated camera"),
    project: Path = typer.Option(
        None, "--project", "-p", help="Project directory (auto-detected if not specified)"
    ),
    name: str = typer.Option("", "--name", "-n", help="Path name (default: glTF filename)"),
    sample_hz: float = typer.Option(
        0.0, "--sample-hz",
        help="Resample to fixed Hz (0 = use glTF's native keyframe times)",
    ),
    camera_index: int = typer.Option(
        0, "--camera-index",
        help="If multiple cameras in glTF, pick this one (0-indexed)",
    ),
    no_flip: bool = typer.Option(
        False, "--no-flip",
        help="Skip 180°-X flip (use when glTF cam is already in PC-displayed frame)",
    ),
) -> None:
    """Import a camera animation from a glTF file as a new camera path."""
    proj = _resolve_project(project)
    if not gltf_file.exists():
        console.print(f"[red]glTF file not found:[/red] {gltf_file}")
        raise typer.Exit(1)

    console.print(f"[bold]Importing camera path from:[/bold] {gltf_file}")
    try:
        path = from_gltf(
            gltf_file,
            name=name,
            sample_hz=sample_hz if sample_hz > 0 else None,
            camera_index=camera_index,
            flip_180_x=not no_flip,
        )
    except Exception as e:
        console.print(f"[red]Import failed:[/red] {e}")
        raise typer.Exit(1)

    def _append(paths):
        paths.append(path)
        return paths

    mutate_paths(proj, _append)
    console.print(
        f"[green]Added path[/green] {path['name']!r} (id={path['id']}, "
        f"{len(path['keyframes'])} keyframes)"
    )


def path_import_colmap(
    project: Path = typer.Option(
        None, "--project", "-p", help="Project directory (auto-detected if not specified)"
    ),
    name: str = typer.Option(
        "Capture Path", "--name", "-n", help="Path name (default: 'Capture Path')"
    ),
    every_nth: int = typer.Option(
        1, "--every-nth",
        help="Use every Nth image (1 = all, 5 = subsample 5×)",
    ),
    fps: float = typer.Option(
        24.0, "--fps", help="Frames per second for inter-keyframe spacing",
    ),
) -> None:
    """Import the original COLMAP capture cameras as a camera path."""
    proj = _resolve_project(project)

    console.print(f"[bold]Importing capture cameras from COLMAP[/bold]")
    try:
        path = from_colmap(
            proj.colmap_dir(),
            name=name,
            every_nth=every_nth,
            fps=fps,
        )
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Import failed:[/red] {e}")
        raise typer.Exit(1)

    def _append(paths):
        paths.append(path)
        return paths

    mutate_paths(proj, _append)
    console.print(
        f"[green]Added path[/green] {path['name']!r} (id={path['id']}, "
        f"{len(path['keyframes'])} keyframes)"
    )


def _resolve_project(project_path: Path | None) -> Project:
    if project_path:
        return Project(project_path)
    return Project.find()
