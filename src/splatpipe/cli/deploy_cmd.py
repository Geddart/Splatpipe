"""splatpipe deploy — Upload output to CDN."""

from pathlib import Path

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn

from ..core.constants import FOLDER_OUTPUT, STEP_DEPLOY
from ..core.project import Project
from ..steps.deploy import deploy_to_bunny, load_bunny_env

console = Console()


def deploy(
    project: Path = typer.Option(
        None,
        "--project", "-p",
        help="Project directory (auto-detected if not specified)",
    ),
    target: str = typer.Option(
        "bunny",
        "--target",
        help="Deploy target (currently only 'bunny')",
    ),
    workers: int = typer.Option(
        8,
        "--workers",
        help="Number of parallel upload threads",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="List files without uploading",
    ),
) -> None:
    """Upload output files to CDN (Bunny Storage)."""
    proj = _resolve_project(project)

    output_dir = proj.get_folder(FOLDER_OUTPUT)
    if not output_dir.exists() or not any(output_dir.iterdir()):
        console.print(f"[red]No output files in {output_dir}[/red]")
        console.print("Run 'splatpipe assemble' first.")
        raise typer.Exit(1)

    # Load credentials
    env_path = proj.root / ".env"
    if not env_path.exists():
        # Try project root's parent .env
        env_path = Path(__file__).parent.parent.parent.parent / ".env"
    env = load_bunny_env(env_path)

    if not env.get("BUNNY_STORAGE_ZONE") or not env.get("BUNNY_STORAGE_PASSWORD"):
        console.print("[red]Missing Bunny CDN credentials[/red]")
        console.print("Set BUNNY_STORAGE_ZONE and BUNNY_STORAGE_PASSWORD in .env")
        raise typer.Exit(1)

    # List files
    files = list(output_dir.rglob("*"))
    files = [f for f in files if f.is_file()]
    total_size = sum(f.stat().st_size for f in files)

    console.print(f"[bold]Deploying:[/bold] {proj.name}")
    console.print(f"Target:   {target}")
    console.print(f"Files:    {len(files)}")
    console.print(f"Size:     {total_size / 1e6:.1f} MB")
    console.print()

    if dry_run:
        for f in files[:20]:
            rel = f.relative_to(output_dir).as_posix()
            console.print(f"  {rel} ({f.stat().st_size / 1e3:.1f} KB)")
        if len(files) > 20:
            console.print(f"  ... and {len(files) - 20} more")
        return

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

    # Record in state
    if result:
        proj.record_step(
            STEP_DEPLOY,
            "completed" if result.success else "failed",
            summary=result.summary,
            error=result.error,
        )


def _resolve_project(project_path: Path | None) -> Project:
    if project_path:
        return Project(project_path)
    return Project.find()
