"""splatpipe run — Run the full pipeline sequentially."""

from pathlib import Path

import typer
from rich.console import Console

console = Console()


def run(
    project: Path = typer.Option(
        None,
        "--project", "-p",
        help="Project directory (auto-detected if not specified)",
    ),
    skip_export: bool = typer.Option(
        False,
        "--skip-export",
        help="Stop after assembly, don't export",
    ),
) -> None:
    """Run the full pipeline: clean, train, (review pause), assemble, export."""
    from .clean_cmd import clean as run_clean
    from .train_cmd import train as run_train

    console.print("[bold]Running full pipeline[/bold]\n")

    # Step 1: Clean
    console.print("[bold cyan]Step 1/4: Cleaning COLMAP data[/bold cyan]")
    run_clean(project=project)

    # Step 2: Train
    console.print("\n[bold cyan]Step 2/4: Training splats[/bold cyan]")
    run_train(project=project, trainer=None, lods=None)

    # Step 3: Review pause
    console.print("\n[bold yellow]Step 3/4: Review[/bold yellow]")
    console.print("Review the trained PLYs in SuperSplat (superspl.at/editor)")
    console.print("PLYs are in the 04_review/ folder.")
    console.print("\nPress Enter when review is complete...")

    try:
        input()
    except (KeyboardInterrupt, EOFError):
        console.print("\n[yellow]Pipeline paused.[/yellow]")
        console.print("Resume with: [cyan]splatpipe assemble[/cyan]")
        raise typer.Exit(0)

    # Step 4: Assemble
    console.print("[bold cyan]Step 4/4: Assembling LOD output[/bold cyan]")
    from .assemble_cmd import assemble as run_assemble
    run_assemble(project=project)

    # Optional: Export
    if not skip_export:
        console.print("\n[bold cyan]Exporting output[/bold cyan]")
        from .deploy_cmd import export as run_export
        run_export(project=project, mode="folder", destination=None, workers=8, dry_run=False)

    console.print("\n[bold green]Pipeline complete![/bold green]")
