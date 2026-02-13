"""Step execution routes: thin HTTP/SSE adapter over PipelineRunner.

POST routes create a runner and return an SSE panel.
A single GET /progress endpoint polls the runner for state.
Browser disconnect has zero effect on execution.
"""

import asyncio
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from sse_starlette.sse import EventSourceResponse

from ...core.config import load_project_config
from ...core.constants import (
    STEP_CLEAN,
    STEP_TRAIN,
    STEP_ASSEMBLE,
    STEP_EXPORT,
)
from ...core.project import Project
from ..runner import (
    STEP_ORDER,
    STEP_LABELS,
    start_run,
    get_runner,
    cancel_run,
)

router = APIRouter(prefix="/steps", tags=["steps"])


def _progress_bar(pct: int) -> str:
    """Generate a DaisyUI progress bar with percentage label."""
    return (
        f'<div class="flex items-center gap-3">'
        f'<progress class="progress progress-primary flex-1 h-3" value="{pct}" max="100"></progress>'
        f'<span class="text-sm font-mono font-bold w-12 text-right">{pct}%</span>'
        f'</div>'
    )


def _sse_panel_html(project_path: str) -> str:
    """Return the SSE-connected progress panel HTML."""
    return f'''
    <div hx-ext="sse" sse-connect="/steps/{project_path}/progress"
         sse-close="complete" class="space-y-2 p-4 bg-base-100 rounded-lg shadow">
        <div class="flex items-center justify-between mb-2">
            <div class="flex items-center gap-2">
                <span class="loading loading-spinner loading-sm"></span>
                <span class="font-bold" sse-swap="step-label" hx-swap="innerHTML">Starting pipeline...</span>
            </div>
            <button class="btn btn-error btn-sm btn-outline"
                    hx-post="/steps/{project_path}/cancel"
                    hx-swap="outerHTML">Cancel</button>
        </div>
        <div sse-swap="progress" hx-swap="innerHTML">{_progress_bar(0)}</div>
        <div class="text-sm font-mono opacity-70" sse-swap="message" hx-swap="innerHTML"></div>
        <div sse-swap="complete" hx-swap="outerHTML"></div>
    </div>
    '''


def _error_event(msg: str) -> dict:
    return {
        "event": "complete",
        "data": f'<div class="alert alert-error shadow-lg"><span>Error: {msg}</span></div>',
    }


def _success_event(proj: Project, project_path: str, message: str) -> dict:
    """Build a success completion event, including CDN/export link if available."""
    extra = ""
    export_summary = proj.get_step_summary("export")
    if export_summary:
        viewer_url = export_summary.get("viewer_url", "")
        cdn_url = export_summary.get("cdn_url", "")
        folder_dest = export_summary.get("destination", "")
        if viewer_url:
            extra = f'<a href="{viewer_url}" target="_blank" class="btn btn-sm btn-ghost">Open Viewer</a>'
        elif cdn_url:
            extra = f'<a href="{cdn_url}" target="_blank" class="btn btn-sm btn-ghost">Open CDN</a>'
        elif folder_dest:
            extra = f'<span class="text-sm opacity-70">{folder_dest}</span>'
    return {
        "event": "complete",
        "data": f'''<div class="alert alert-success shadow-lg">
            <span>{message}</span>
            {extra}
            <a href="/projects/{project_path}/detail" class="btn btn-sm btn-ghost">Refresh</a>
        </div>''',
    }


def _cancelled_event(project_path: str) -> dict:
    return {
        "event": "complete",
        "data": f'''<div class="alert alert-warning shadow-lg">
            <span>Cancelled.</span>
            <a href="/projects/{project_path}/detail" class="btn btn-sm btn-ghost">Refresh</a>
        </div>''',
    }


# ── Routes ────────────────────────────────────────────────────────


@router.post("/{project_path:path}/cancel")
async def cancel_step(project_path: str):
    """Cancel any running step for this project."""
    cancel_run(project_path)
    return HTMLResponse(
        '<span class="text-warning font-bold">Cancelling...</span>'
    )


@router.post("/{project_path:path}/run/{step_name}", response_class=HTMLResponse)
async def run_step(project_path: str, step_name: str):
    """Start a single step and return SSE panel."""
    proj = Project(Path(project_path))

    # Guard: already running
    runner = get_runner(project_path)
    if runner and runner.snapshot.status == "running":
        return HTMLResponse(
            '<div class="alert alert-warning">A step is already running.</div>'
        )

    config = load_project_config(proj.config_path)
    start_run(project_path, [step_name], config)

    return HTMLResponse(_sse_panel_html(project_path))


@router.post("/{project_path:path}/run-all", response_class=HTMLResponse)
async def run_all(project_path: str):
    """Start all enabled steps sequentially. Returns SSE panel."""
    proj = Project(Path(project_path))

    # Guard: already running
    runner = get_runner(project_path)
    if runner and runner.snapshot.status == "running":
        return HTMLResponse(
            '<div class="alert alert-warning">Pipeline is already running.</div>'
        )

    enabled = proj.enabled_steps
    enabled_steps = [s for s in STEP_ORDER if enabled.get(s, True)]

    if not enabled_steps:
        return HTMLResponse(
            '<div class="alert alert-error">No steps enabled.</div>'
        )

    config = load_project_config(proj.config_path)
    start_run(project_path, enabled_steps, config)

    return HTMLResponse(_sse_panel_html(project_path))


@router.get("/{project_path:path}/progress")
async def progress_stream(request: Request, project_path: str):
    """Single SSE endpoint: polls runner snapshot, yields events."""

    async def event_generator():
        runner = get_runner(project_path)
        if not runner:
            yield _error_event("No active run")
            return

        last_label = ""
        while True:
            if await request.is_disconnected():
                return  # Browser gone — runner continues!

            snap = runner.snapshot

            # Step label updates
            if snap.step_label != last_label:
                yield {"event": "step-label", "data": snap.step_label}
                last_label = snap.step_label

            # Progress bar
            pct = int(snap.progress * 100)
            yield {"event": "progress", "data": _progress_bar(pct)}

            # Message
            if snap.message:
                yield {"event": "message", "data": snap.message}

            # Terminal states
            if snap.status != "running":
                proj = Project(Path(project_path))
                if snap.status == "completed":
                    yield _success_event(proj, project_path, "Pipeline completed successfully.")
                elif snap.status == "cancelled":
                    yield _cancelled_event(project_path)
                else:
                    yield _error_event(snap.error or "Unknown error")
                return

            await asyncio.sleep(0.3)

    return EventSourceResponse(event_generator())
