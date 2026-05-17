"""splatpipe publish - build/stage a scene and deploy it to a PERMANENT
Bunny slug URL that never changes across rebuilds.

Two modes:

  * **Project**  ``splatpipe publish -p <project>``
    Source = the project's first enabled LOD ``04_review/<lod>_reviewed.ply``;
    config inherits the project's ``scene_config``; slug defaults to the
    project's ``cdn_name``; records a ``publish`` step in ``state.json``.

  * **Standalone**  ``splatpipe publish --ply X.ply --slug speicher``
    (or ``--rad-dir`` for a prebuilt chunked set). Config inherits an
    existing live slug via ``--live`` if given, else starts empty.

The public URL is forever ``https://<cdn>/<slug>/index.html`` (+ ``?embed=1``)
- embed it once; re-running ``publish`` swaps the build behind it with zero
consumer change. ``--desc`` defaults to a neutral, non-fabricated line; pass
real user copy verbatim.
"""

from pathlib import Path

import typer
from rich.console import Console
from rich.progress import (
    BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn,
)

from ..core.constants import FOLDER_REVIEW, STEP_PUBLISH
from ..core.project import Project
from ..steps.deploy import load_bunny_env
from ..steps.publish import publish_scene

console = Console()


def publish(
    project: Path = typer.Option(
        None, "--project", "-p",
        help="Project dir (auto-detected if omitted). Uses its reviewed lod0 "
             "PLY + scene_config. Mutually exclusive with --ply/--rad-dir.",
    ),
    ply: Path = typer.Option(
        None, "--ply", help="Standalone: source PLY to build. XOR --rad-dir / --project."),
    rad_dir: Path = typer.Option(
        None, "--rad-dir",
        help="Standalone: prebuilt chunked dir (one *-lod.rad + *.radc) to "
             "stage as-is instead of building. XOR --ply / --project."),
    slug: str = typer.Option(
        None, "--slug",
        help="Permanent CDN slug (the forever URL). Required in standalone "
             "mode; defaults to the project's cdn_name in project mode."),
    scene: str = typer.Option(
        None, "--scene", help="Display name (og:title). Defaults to project name / slug."),
    live: str = typer.Option(
        None, "--live",
        help="Standalone: existing slug to inherit viewer-config.json from "
             "(start_view etc.). Ignored in project mode."),
    clip_xy: float = typer.Option(
        None, "--clip-xy", help="Per-scene spark_render.clip_xy override."),
    move_speed_mult: float = typer.Option(
        None, "--move-speed-mult", help="Per-scene spark_render.move_speed_mult."),
    splat_budget: int = typer.Option(
        None, "--splat-budget", help="Per-scene top-level splat_budget (capable desktop only)."),
    crop_within: str = typer.Option(
        None, "--crop-within",
        help="build-lod --within-dist crop 'x,y,z,radius' (drops training-"
             "outlier splats at source). Only valid with --ply."),
    desc: str = typer.Option(
        None, "--desc", help="Share-card description - REAL user copy only, never invented."),
    prune_stale: bool = typer.Option(
        False, "--prune-stale",
        help="Delete prior b*/ build subfolders after deploy. OFF by default: "
             "a 30-day-edge-cached old index may still need its subfolder."),
    spark_repo: Path = typer.Option(
        None, "--spark-repo", help="sparkjsdev/spark clone (default: $SPARK_REPO)."),
    env_file: Path = typer.Option(
        None, "--env", help="Path to .env with Bunny creds (default: auto-discover)."),
) -> None:
    """Deploy a scene to its permanent slug URL (redeploy-safe forever)."""
    if project is not None and (ply is not None or rad_dir is not None):
        console.print("[red]--project is mutually exclusive with --ply/--rad-dir[/red]")
        raise typer.Exit(1)
    if project is None and bool(ply) == bool(rad_dir):
        console.print("[red]Give exactly one of --project, --ply, or --rad-dir[/red]")
        raise typer.Exit(1)
    if crop_within and rad_dir is not None:
        console.print("[red]--crop-within only applies to a --ply build[/red]")
        raise typer.Exit(1)

    proj: Project | None = None
    base_config: dict | None = None
    src_ply: Path | None = ply
    src_rad: Path | None = rad_dir

    if project is not None or (ply is None and rad_dir is None):
        # Project mode (explicit -p, or neither source -> auto-detect project)
        proj = Project(project) if project else Project.find()
        review_dir = proj.get_folder(FOLDER_REVIEW)
        enabled = [lod for lod in proj.lod_levels if lod.get("enabled", True)]
        if not enabled:
            console.print("[red]No enabled LODs in project[/red]")
            raise typer.Exit(1)
        lod_name = enabled[0]["name"]
        cands = sorted(review_dir.glob(f"{lod_name}_reviewed.ply"))
        if not cands:
            console.print(f"[red]No {lod_name}_reviewed.ply in {review_dir}[/red]")
            console.print("Train + review the project first.")
            raise typer.Exit(1)
        src_ply, src_rad = cands[0], None
        base_config = proj.scene_config
        slug = (slug or proj.cdn_name).strip("/").lower()
        scene = scene or proj.name
        env_path = proj.root / ".env"
        if not env_path.exists():
            env_path = Path(__file__).parent.parent.parent.parent / ".env"
    else:
        if not slug:
            console.print("[red]--slug is required in standalone mode[/red]")
            raise typer.Exit(1)
        slug = slug.strip("/").lower()
        scene = scene or slug
        env_path = env_file or (Path(__file__).parent.parent.parent.parent / ".env")

    env = load_bunny_env(env_path)
    if not env.get("BUNNY_STORAGE_ZONE") or not env.get("BUNNY_STORAGE_PASSWORD"):
        console.print("[red]Missing Bunny CDN credentials[/red]")
        console.print("Set BUNNY_STORAGE_ZONE and BUNNY_STORAGE_PASSWORD in .env")
        raise typer.Exit(1)

    console.print(f"[bold]Publishing[/bold] [cyan]{scene}[/cyan] -> "
                  f"{env.get('BUNNY_CDN_URL', '').rstrip('/')}/{slug}/")
    if proj is not None:
        console.print(f"  source: {src_ply.name} (project {proj.name})")
    console.print()

    pub_kw = dict(
        scene_name=scene, slug=slug, env=env,
        ply=src_ply, rad_dir=src_rad,
        base_config=base_config, live_slug=live,
        clip_xy=clip_xy, move_speed_mult=move_speed_mult,
        splat_budget=splat_budget, crop_within=crop_within,
        desc=desc, prune_stale=prune_stale, spark_repo=spark_repo,
    )
    result = None
    if console.is_terminal:
        # Interactive terminal: the live rich progress bar.
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Publishing", total=1.0)
            gen = publish_scene(
                **pub_kw,
                on_build_line=lambda l: progress.update(
                    task, description=(l.strip()[:80] or "building")),
            )
            try:
                while True:
                    event = next(gen)
                    progress.update(task, completed=event.progress,
                                    description=event.message)
            except StopIteration as e:
                result = e.value
    else:
        # Non-interactive (background / piped / CI): a rich live bar emits
        # almost nothing here, so stream plain flushed lines instead - the
        # same per-line visibility the pre-productization script had. Every
        # build-lod line + every publish ProgressEvent is printed live.
        gen = publish_scene(
            **pub_kw,
            on_build_line=lambda l: print(f"  {l.rstrip()}", flush=True),
        )
        try:
            while True:
                event = next(gen)
                pct = int(round(event.progress * 100))
                print(f"[{pct:3d}%] {event.message}"
                      + (f"  {event.detail}" if event.detail else ""),
                      flush=True)
        except StopIteration as e:
            result = e.value

    if proj is not None and result is not None:
        proj.record_step(
            STEP_PUBLISH,
            "completed" if result.success else "failed",
            summary=result.summary, error=result.error,
        )

    if result and result.success:
        s = result.summary
        console.print("\n[green]Published[/green]")
        console.print(f"  Slug:   {s['slug']}  ({s['chunks']} chunks, {s['total_mb']} MB)")
        console.print(f"  Build:  {s['bkey']}/")
        if s.get("kept_subfolders"):
            console.print(f"  [dim]kept prior: {s['kept_subfolders']} "
                          f"(--prune-stale to remove)[/dim]")
        console.print(f"\n  Viewer: {s['viewer_url']}")
        console.print(f"  Embed:  {s['embed_url']}")
    else:
        console.print(f"\n[red]Publish failed:[/red] "
                      f"{result.error if result else 'unknown error'}")
        raise typer.Exit(1)
