"""splatpipe export — Export output to folder or deploy to CDN."""

from pathlib import Path

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn

from ..core.constants import FOLDER_OUTPUT, STEP_EXPORT
from ..core.project import Project
from ..steps.deploy import deploy_to_bunny, export_to_folder, load_bunny_env

console = Console()


def export(
    project: Path = typer.Option(
        None,
        "--project", "-p",
        help="Project directory (auto-detected if not specified)",
    ),
    mode: str = typer.Option(
        "folder",
        "--mode",
        help="Export mode: 'folder' (copy to local path) or 'cdn' (Bunny CDN upload)",
    ),
    destination: Path = typer.Option(
        None,
        "--destination", "-d",
        help="Destination folder (required for folder mode)",
    ),
    workers: int = typer.Option(
        8,
        "--workers",
        help="Number of parallel upload threads (CDN mode only)",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="List files without exporting",
    ),
) -> None:
    """Export output files to a local folder or deploy to CDN."""
    proj = _resolve_project(project)

    output_dir = proj.get_folder(FOLDER_OUTPUT)
    if not output_dir.exists() or not any(output_dir.iterdir()):
        console.print(f"[red]No output files in {output_dir}[/red]")
        console.print("Run 'splatpipe assemble' first.")
        raise typer.Exit(1)

    # List files
    files = list(output_dir.rglob("*"))
    files = [f for f in files if f.is_file()]
    total_size = sum(f.stat().st_size for f in files)

    console.print(f"[bold]Exporting:[/bold] {proj.name}")
    console.print(f"Mode:     {mode}")
    console.print(f"Files:    {len(files)}")
    console.print(f"Size:     {total_size / 1e6:.1f} MB")

    if dry_run:
        console.print()
        for f in files[:20]:
            rel = f.relative_to(output_dir).as_posix()
            console.print(f"  {rel} ({f.stat().st_size / 1e3:.1f} KB)")
        if len(files) > 20:
            console.print(f"  ... and {len(files) - 20} more")
        return

    if mode == "folder":
        _run_folder_export(proj, output_dir, destination)
    elif mode == "cdn":
        _run_cdn_deploy(proj, output_dir, workers)
    else:
        console.print(f"[red]Unknown mode: {mode}[/red]")
        console.print("Use --mode folder or --mode cdn")
        raise typer.Exit(1)


def _run_folder_export(proj: Project, output_dir: Path, destination: Path | None) -> None:
    """Export to a local folder."""
    if destination is None:
        # Fall back to project's saved export_folder
        saved = proj.export_folder
        if saved:
            destination = Path(saved)
        else:
            console.print("[red]Destination required for folder export[/red]")
            console.print("Use --destination <path> or set export folder in project settings")
            raise typer.Exit(1)

    console.print(f"Dest:     {destination}")
    console.print()

    gen = export_to_folder(output_dir, destination)

    result = None
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Copying", total=1.0)

        try:
            while True:
                event = next(gen)
                progress.update(task, completed=event.progress,
                                description=event.message)
        except StopIteration as e:
            result = e.value

    if result and result.success:
        summary = result.summary
        console.print("\n[green]Export complete[/green]")
        console.print(f"  Copied: {summary['copied']} files")
        console.print(f"  Size: {summary['total_mb']} MB")
        console.print(f"  Duration: {summary['duration_s']}s")
        console.print(f"  Destination: {summary['destination']}")
    else:
        console.print(f"\n[red]Export failed:[/red] {result.error if result else 'unknown error'}")

    if result:
        proj.record_step(
            STEP_EXPORT,
            "completed" if result.success else "failed",
            summary=result.summary,
            error=result.error,
        )


def _run_cdn_deploy(proj: Project, output_dir: Path, workers: int) -> None:
    """Deploy to Bunny CDN."""
    env_path = proj.root / ".env"
    if not env_path.exists():
        env_path = Path(__file__).parent.parent.parent.parent / ".env"
    env = load_bunny_env(env_path)

    if not env.get("BUNNY_STORAGE_ZONE") or not env.get("BUNNY_STORAGE_PASSWORD"):
        console.print("[red]Missing Bunny CDN credentials[/red]")
        console.print("Set BUNNY_STORAGE_ZONE and BUNNY_STORAGE_PASSWORD in .env")
        raise typer.Exit(1)

    console.print()

    gen = deploy_to_bunny(proj.name, output_dir, env, workers=workers)

    result = None
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Uploading", total=1.0)

        try:
            while True:
                event = next(gen)
                progress.update(task, completed=event.progress,
                                description=event.message)
        except StopIteration as e:
            result = e.value

    if result and result.success:
        summary = result.summary
        console.print("\n[green]Deploy complete[/green]")
        console.print(f"  Uploaded: {summary['uploaded']} files")
        console.print(f"  Size: {summary['total_mb']} MB")
        console.print(f"  Duration: {summary['duration_s']}s")
        if summary.get("viewer_url"):
            console.print(f"\n  Viewer: {summary['viewer_url']}")
    else:
        console.print(f"\n[red]Deploy failed:[/red] {result.error if result else 'unknown error'}")

    if result:
        proj.record_step(
            STEP_EXPORT,
            "completed" if result.success else "failed",
            summary=result.summary,
            error=result.error,
        )


def _resolve_project(project_path: Path | None) -> Project:
    if project_path:
        return Project(project_path)
    return Project.find()
