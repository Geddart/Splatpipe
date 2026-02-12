"""splatpipe train — Train Gaussian splats for all LOD levels."""

import json
import shutil
import time
from pathlib import Path

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn

from ..core.config import load_project_config
from ..core.constants import FOLDER_COLMAP_CLEAN, FOLDER_TRAINING, FOLDER_REVIEW, STEP_TRAIN
from ..core.project import Project
from ..trainers.registry import get_trainer

console = Console()


def train(
    project: Path = typer.Option(
        None,
        "--project", "-p",
        help="Project directory (auto-detected if not specified)",
    ),
    trainer: str = typer.Option(
        None,
        "--trainer", "-t",
        help="Training backend (overrides project setting)",
    ),
    lods: str = typer.Option(
        None,
        "--lods",
        help="Override LOD levels (e.g. '3M,1.5M')",
    ),
) -> None:
    """Train Gaussian splats for all configured LOD levels."""
    proj = _resolve_project(project)
    config = load_project_config(proj.config_path)

    # Determine trainer
    trainer_name = trainer or proj.trainer
    try:
        trainer_instance = get_trainer(trainer_name, config)
    except KeyError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    # Validate environment
    ok, msg = trainer_instance.validate_environment()
    if not ok:
        console.print(f"[red]Trainer {trainer_name!r} not available:[/red] {msg}")
        raise typer.Exit(1)

    # Determine source directory
    clean_dir = proj.get_folder(FOLDER_COLMAP_CLEAN)
    if not clean_dir.exists() or not (clean_dir / "cameras.txt").exists():
        # Fall back to colmap source
        clean_dir = proj.colmap_dir()
        if not (clean_dir / "cameras.txt").exists():
            console.print("[red]No COLMAP data found. Run 'splatpipe clean' first.[/red]")
            raise typer.Exit(1)
        console.print("[yellow]Using uncleaned COLMAP data[/yellow]")

    # Parse LOD levels
    if lods:
        from .init_cmd import _parse_lods
        lod_levels = _parse_lods(lods)
    else:
        lod_levels = proj.lod_levels

    training_dir = proj.get_folder(FOLDER_TRAINING)
    review_dir = proj.get_folder(FOLDER_REVIEW)
    review_dir.mkdir(parents=True, exist_ok=True)

    console.print(f"[bold]Training {len(lod_levels)} LODs with {trainer_name}[/bold]")
    console.print(f"Source: {clean_dir}")
    console.print()

    all_results = []
    t0 = time.time()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        overall = progress.add_task("Overall", total=len(lod_levels))

        for i, lod in enumerate(lod_levels):
            lod_name = lod["name"]
            max_splats = lod["max_splats"]
            lod_dir = training_dir / lod_name
            splats_m = max_splats / 1_000_000

            lod_task = progress.add_task(
                f"  {lod_name} ({splats_m:.1f}M)", total=1.0,
            )

            gen = trainer_instance.train_lod(
                clean_dir, lod_dir, lod_name, max_splats,
            )

            # Consume progress events
            result = None
            try:
                while True:
                    event = next(gen)
                    progress.update(lod_task, completed=event.sub_progress)
            except StopIteration as e:
                result = e.value

            progress.update(lod_task, completed=1.0)
            all_results.append(result)

            # Copy PLY to review folder
            if result.output_ply and Path(result.output_ply).exists():
                review_ply = review_dir / f"lod{i}_reviewed.ply"
                shutil.copy2(result.output_ply, review_ply)

            progress.update(overall, advance=1)

    total_time = time.time() - t0

    # Write debug JSON
    debug_data = {
        "step": "train",
        "trainer": trainer_name,
        "source_dir": str(clean_dir),
        "lod_results": [
            {
                "lod_name": r.lod_name,
                "max_splats": r.max_splats,
                "success": r.success,
                "command": r.command,
                "returncode": r.returncode,
                "stdout": r.stdout[-2000:] if r.stdout else "",
                "stderr": r.stderr[-2000:] if r.stderr else "",
                "duration_s": r.duration_s,
                "output_ply": r.output_ply,
            }
            for r in all_results
        ],
        "duration_s": round(total_time, 2),
    }

    debug_path = training_dir / "train_debug.json"
    training_dir.mkdir(parents=True, exist_ok=True)
    with open(debug_path, "w") as f:
        json.dump(debug_data, f, indent=2)

    # Record in state
    summary = {
        "trainer": trainer_name,
        "lod_count": len(all_results),
        "all_completed": all(r.success for r in all_results),
        "lod_names": [r.lod_name for r in all_results],
        "duration_s": round(total_time, 2),
    }
    status = "completed" if summary["all_completed"] else "failed"
    proj.record_step(STEP_TRAIN, status, summary=summary)

    # Display results
    console.print()
    for r in all_results:
        icon = "[green]OK[/green]" if r.success else "[red]FAIL[/red]"
        console.print(f"  {r.lod_name}: {icon} ({r.duration_s:.0f}s)")
        if not r.success and r.stderr:
            console.print(f"    [dim]{r.stderr[:200]}[/dim]")

    console.print(f"\n[green]Done in {total_time:.0f}s[/green]")
    console.print(f"PLYs copied to: {review_dir}")
    console.print("\nNext: Review PLYs in SuperSplat (superspl.at/editor)")
    console.print("Then: [cyan]splatpipe assemble[/cyan]")


def _resolve_project(project_path: Path | None) -> Project:
    if project_path:
        return Project(project_path)
    return Project.find()
