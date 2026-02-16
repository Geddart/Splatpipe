"""Step execution routes: thin HTTP/SSE adapter over PipelineRunner.

POST routes create a runner and return an SSE panel.
A single GET /progress endpoint polls the runner for state.
Browser disconnect has zero effect on execution.
"""

import asyncio
import subprocess
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from sse_starlette.sse import EventSourceResponse

from ...core.config import load_defaults, load_project_config, get_postshot_cli
from ...core.constants import (
    STEP_REVIEW,
    FOLDER_REVIEW,
    FOLDER_TRAINING,
    FOLDER_OUTPUT,
)
from ...core.project import Project
from ..runner import (
    STEP_ORDER,
    _normalize_key,
    enqueue_run,
    find_queue_entry,
    get_queue_snapshot,
    get_runner,
    cancel_run,
    queue_position,
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


def _queued_panel_html(project_path: str, entry) -> str:
    """Return a polling panel for a queued (not yet running) job."""
    pos = queue_position(entry.id) or "?"
    return f'''
    <div id="progress-panel"
         hx-get="/steps/queue/{entry.id}/item-status?project_path={project_path}"
         hx-trigger="every 2s"
         hx-swap="outerHTML"
         class="p-4 bg-base-100 rounded-lg shadow">
        <div class="flex items-center gap-3">
            <span class="badge badge-info">Queued — #{pos}</span>
            <span class="text-sm opacity-60">{entry.project_name}</span>
            <button class="btn btn-error btn-xs btn-outline"
                    hx-post="/queue/{entry.id}/remove"
                    hx-target="#progress-panel"
                    hx-swap="outerHTML">Remove from queue</button>
        </div>
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
    # Always offer local preview if output has index.html and no CDN viewer
    output_dir = proj.get_folder(FOLDER_OUTPUT)
    if (output_dir / "index.html").exists() and not extra.startswith('<a href="http'):
        preview_url = f"/projects/{project_path}/preview/index.html"
        extra += f' <a href="{preview_url}" target="_blank" class="btn btn-sm btn-ghost">Preview</a>'
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


@router.post("/{project_path:path}/approve-review", response_class=HTMLResponse)
async def approve_review(request: Request, project_path: str):
    """Mark the review step as completed (manual approval gate)."""
    form = await request.form()
    reexport = form.get("reexport") == "on"

    proj = Project(Path(project_path))
    review_dir = proj.get_folder(FOLDER_REVIEW)
    training_dir = proj.get_folder(FOLDER_TRAINING)

    # Re-export PLYs from edited .psht files if requested
    if reexport and training_dir.exists():
        try:
            postshot_cli = get_postshot_cli(load_defaults())
            for i, lod in enumerate(proj.lod_levels):
                lod_name = lod["name"]
                lod_dir = training_dir / lod_name
                if not lod_dir.is_dir():
                    continue
                psht_files = list(lod_dir.glob("*.psht"))
                if not psht_files:
                    continue
                psht = psht_files[0]
                out_ply = review_dir / f"lod{i}_reviewed.ply"
                cmd = [
                    str(postshot_cli), "export",
                    "-f", str(psht),
                    "--export-splat", str(out_ply),
                ]
                subprocess.run(cmd, check=True, capture_output=True)
        except Exception as e:
            return HTMLResponse(
                f'<div class="alert alert-error shadow-lg">'
                f'<span>Re-export failed: {e}</span>'
                f'</div>',
                status_code=500,
            )

    # Count reviewed PLYs and read vertex counts from headers
    lod_count = 0
    total_vertices = 0
    if review_dir.exists():
        for ply in sorted(review_dir.glob("*.ply")):
            lod_count += 1
            try:
                with open(ply, "rb") as f:
                    while True:
                        line = f.readline().decode("ascii", errors="replace").strip()
                        if line.startswith("element vertex"):
                            total_vertices += int(line.split()[-1])
                            break
                        if line == "end_header" or not line:
                            break
            except (OSError, ValueError):
                pass

    proj.record_step(STEP_REVIEW, "completed", summary={
        "lod_count": lod_count,
        "total_vertices": total_vertices,
    })

    return HTMLResponse(
        f'<div class="alert alert-success shadow-lg">'
        f'<span>Review approved: {lod_count} LODs</span>'
        f'<a href="/projects/{project_path}/detail" class="btn btn-sm btn-ghost">Refresh</a>'
        f'</div>'
    )


@router.post("/{project_path:path}/run/{step_name}", response_class=HTMLResponse)
async def run_step(project_path: str, step_name: str):
    """Start a single step (or queue it if something is already running)."""
    proj = Project(Path(project_path))

    # Guard: already running or queued for this project
    snap = get_queue_snapshot()
    norm = _normalize_key(project_path)
    if snap.current and _normalize_key(snap.current.project_path) == norm:
        return HTMLResponse(
            '<div class="alert alert-warning">Already running.</div>'
        )
    for p in snap.pending:
        if _normalize_key(p.project_path) == norm:
            return HTMLResponse(
                '<div class="alert alert-warning">Already in queue.</div>'
            )

    config = load_project_config(proj.config_path)
    entry, started = enqueue_run(project_path, [step_name], config)

    if started:
        return HTMLResponse(_sse_panel_html(project_path))
    return HTMLResponse(_queued_panel_html(project_path, entry))


@router.post("/{project_path:path}/run-all", response_class=HTMLResponse)
async def run_all(project_path: str):
    """Start all enabled steps (or queue if something is already running)."""
    proj = Project(Path(project_path))

    # Guard: already running or queued for this project
    snap = get_queue_snapshot()
    norm = _normalize_key(project_path)
    if snap.current and _normalize_key(snap.current.project_path) == norm:
        return HTMLResponse(
            '<div class="alert alert-warning">Already running.</div>'
        )
    for p in snap.pending:
        if _normalize_key(p.project_path) == norm:
            return HTMLResponse(
                '<div class="alert alert-warning">Already in queue.</div>'
            )

    enabled = proj.enabled_steps
    enabled_steps = [s for s in STEP_ORDER if enabled.get(s, True)]

    if not enabled_steps:
        return HTMLResponse(
            '<div class="alert alert-error">No steps enabled.</div>'
        )

    config = load_project_config(proj.config_path)
    entry, started = enqueue_run(project_path, enabled_steps, config)

    if started:
        return HTMLResponse(_sse_panel_html(project_path))
    return HTMLResponse(_queued_panel_html(project_path, entry))


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


@router.get("/queue/{entry_id}/item-status", response_class=HTMLResponse)
async def queue_item_status(entry_id: str, project_path: str = ""):
    """Polling endpoint for queued jobs — transitions to SSE panel when running."""
    snap = get_queue_snapshot()

    # Currently running? → switch to SSE panel
    if snap.current and snap.current.id == entry_id:
        return HTMLResponse(_sse_panel_html(project_path))

    # Still queued? → keep polling
    pos = queue_position(entry_id)
    if pos is not None:
        entry = find_queue_entry(entry_id)
        return HTMLResponse(_queued_panel_html(project_path, entry))

    # Gone (completed or removed) — check runner for final status
    if project_path:
        runner = get_runner(project_path)
        if runner and runner.snapshot.status != "running":
            proj = Project(Path(project_path))
            s = runner.snapshot
            if s.status == "completed":
                extra = ""
                export_summary = proj.get_step_summary("export")
                if export_summary:
                    viewer_url = export_summary.get("viewer_url", "")
                    if viewer_url:
                        extra = f'<a href="{viewer_url}" target="_blank" class="btn btn-sm btn-ghost">Open Viewer</a>'
                return HTMLResponse(
                    f'<div class="alert alert-success shadow-lg">'
                    f'<span>Pipeline completed.</span>{extra}'
                    f'<a href="/projects/{project_path}/detail" class="btn btn-sm btn-ghost">Refresh</a>'
                    f'</div>'
                )
            elif s.status == "cancelled":
                return HTMLResponse(
                    f'<div class="alert alert-warning shadow-lg">'
                    f'<span>Cancelled.</span>'
                    f'<a href="/projects/{project_path}/detail" class="btn btn-sm btn-ghost">Refresh</a>'
                    f'</div>'
                )
            else:
                return HTMLResponse(
                    f'<div class="alert alert-error shadow-lg">'
                    f'<span>Failed: {s.error or "Unknown error"}</span>'
                    f'</div>'
                )

    return HTMLResponse('<div></div>')
