"""Unified step execution routes with SSE progress streaming.

Replaces the old training-only route. Handles all pipeline steps:
clean, train, assemble, deploy.
"""

import asyncio
import json
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from sse_starlette.sse import EventSourceResponse

from ...core.config import load_project_config
from ...core.constants import (
    FOLDER_COLMAP_SOURCE,
    FOLDER_COLMAP_CLEAN,
    FOLDER_OUTPUT,
    STEP_CLEAN,
    STEP_TRAIN,
    STEP_ASSEMBLE,
    STEP_DEPLOY,
)
from ...core.project import Project
from ...steps.colmap_clean import ColmapCleanStep
from ...steps.lod_assembly import LodAssemblyStep
from ...steps.deploy import deploy_to_bunny, load_bunny_env
from ...trainers.registry import get_trainer

router = APIRouter(prefix="/steps", tags=["steps"])


@router.post("/{project_path:path}/run/{step_name}", response_class=HTMLResponse)
async def run_step(project_path: str, step_name: str):
    """Start a step and return HTML partial with SSE connection."""
    proj = Project(Path(project_path))

    # Guard: don't re-run if already running
    current = proj.get_step_status(step_name)
    if current == "running":
        return HTMLResponse(
            '<div class="alert alert-warning">Step is already running.</div>'
        )

    # Mark as running
    proj.record_step(step_name, "running")

    # Return SSE-connected progress panel
    html = f'''
    <div hx-ext="sse" sse-connect="/steps/{project_path}/progress/{step_name}"
         sse-close="complete" class="space-y-2">
        <div class="flex items-center gap-2 mb-2">
            <span class="loading loading-spinner loading-sm"></span>
            <span class="font-bold">Running: {step_name}</span>
        </div>
        <progress class="progress progress-primary w-full" value="0" max="100"
                  sse-swap="progress" hx-swap="outerHTML"></progress>
        <div class="text-sm font-mono opacity-70" sse-swap="message" hx-swap="innerHTML"></div>
        <div sse-swap="complete" hx-swap="outerHTML"></div>
    </div>
    '''
    return HTMLResponse(html)


@router.get("/{project_path:path}/progress/{step_name}")
async def step_progress(request: Request, project_path: str, step_name: str):
    """SSE endpoint for step execution progress."""

    async def event_generator():
        proj = Project(Path(project_path))
        config = load_project_config(proj.config_path)

        try:
            if step_name == STEP_CLEAN:
                yield from _wrap_sync_events(
                    await _run_clean(proj, config), step_name
                )
            elif step_name == STEP_TRAIN:
                async for event in _run_train(proj, config):
                    yield event
            elif step_name == STEP_ASSEMBLE:
                yield from _wrap_sync_events(
                    await _run_assemble(proj, config), step_name
                )
            elif step_name == STEP_DEPLOY:
                async for event in _run_deploy(proj, config):
                    yield event
            else:
                yield _error_event(f"Unknown step: {step_name}")
                return

        except Exception as e:
            proj.record_step(step_name, "failed", error=str(e))
            yield _error_event(str(e))
            return

        yield {
            "event": "complete",
            "data": f'''<div class="alert alert-success shadow-lg">
                <span>{step_name} completed successfully.</span>
                <a href="/projects/{project_path}/detail" class="btn btn-sm btn-ghost">Refresh</a>
            </div>''',
        }

    return EventSourceResponse(event_generator())


async def _run_clean(proj: Project, config: dict) -> dict:
    """Run COLMAP clean step in a thread."""
    step = ColmapCleanStep(proj, config)
    result = await asyncio.to_thread(step.execute)
    return result


async def _run_assemble(proj: Project, config: dict) -> dict:
    """Run LOD assembly step in a thread."""
    step = LodAssemblyStep(proj, config)
    result = await asyncio.to_thread(step.execute)
    return result


async def _run_train(proj: Project, config: dict):
    """Run training step, yielding SSE events."""
    trainer_name = proj.trainer
    trainer_instance = get_trainer(trainer_name, config)

    # Determine source directory: use clean output if clean was run and enabled
    clean_dir = proj.get_folder(FOLDER_COLMAP_CLEAN)
    if proj.is_step_enabled(STEP_CLEAN) and (clean_dir / "cameras.txt").exists():
        source_dir = clean_dir
    else:
        source_dir = proj.colmap_dir()

    lod_levels = proj.lod_levels

    for i, lod in enumerate(lod_levels):
        lod_name = lod["name"]
        max_splats = lod["max_splats"]
        lod_dir = proj.get_folder("03_training") / lod_name

        gen = trainer_instance.train_lod(source_dir, lod_dir, lod_name, max_splats)

        try:
            while True:
                event = await asyncio.to_thread(next, gen)
                overall = (i + event.sub_progress) / len(lod_levels)
                yield {
                    "event": "progress",
                    "data": f'<progress class="progress progress-primary w-full" value="{int(overall * 100)}" max="100"></progress>',
                }
                yield {
                    "event": "message",
                    "data": f"LOD {lod_name} ({i+1}/{len(lod_levels)}): {event.message}",
                }
                await asyncio.sleep(0.1)
        except StopIteration as e:
            result = e.value
            yield {
                "event": "message",
                "data": f"LOD {lod_name} complete ({result.duration_s:.1f}s)",
            }

    proj.record_step(STEP_TRAIN, "completed", summary={"lod_count": len(lod_levels)})


async def _run_deploy(proj: Project, config: dict):
    """Run deploy step, yielding SSE events."""
    env = load_bunny_env(proj.root / ".env")
    output_dir = proj.get_folder(FOLDER_OUTPUT)
    gen = deploy_to_bunny(proj.name, output_dir, env)

    try:
        while True:
            event = await asyncio.to_thread(next, gen)
            pct = int(event.progress * 100)
            yield {
                "event": "progress",
                "data": f'<progress class="progress progress-primary w-full" value="{pct}" max="100"></progress>',
            }
            yield {
                "event": "message",
                "data": event.message,
            }
            await asyncio.sleep(0.05)
    except StopIteration as e:
        result = e.value
        if result.success:
            proj.record_step(STEP_DEPLOY, "completed", summary=result.summary)
        else:
            proj.record_step(STEP_DEPLOY, "failed", error=result.error)


def _wrap_sync_events(result: dict, step_name: str):
    """Wrap a synchronous step result into SSE events."""
    pct = 100
    yield {
        "event": "progress",
        "data": f'<progress class="progress progress-primary w-full" value="{pct}" max="100"></progress>',
    }
    summary = result.get("summary", {})
    yield {
        "event": "message",
        "data": json.dumps(summary),
    }


def _error_event(msg: str) -> dict:
    return {
        "event": "complete",
        "data": f'<div class="alert alert-error shadow-lg"><span>Error: {msg}</span></div>',
    }
