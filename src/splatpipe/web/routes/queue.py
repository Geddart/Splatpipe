"""Queue routes: global pipeline queue panel and management."""

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

from ..runner import (
    cancel_current,
    get_queue_snapshot,
    move_in_queue,
    pause_queue,
    remove_from_queue,
    resume_queue,
)

router = APIRouter(prefix="/queue", tags=["queue"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


def _queue_panel_response(request: Request):
    """Render the queue panel partial with current state."""
    return templates.TemplateResponse("partials/queue_panel.html", {
        "request": request,
        "queue": get_queue_snapshot(),
    })


@router.get("/panel")
async def queue_panel(request: Request):
    """Self-loading queue panel (polled every 2s from projects page)."""
    return _queue_panel_response(request)


@router.post("/{entry_id}/remove")
async def remove_entry(request: Request, entry_id: str):
    """Remove a pending entry from the queue."""
    remove_from_queue(entry_id)
    return _queue_panel_response(request)


@router.post("/{entry_id}/move-up")
async def move_up(request: Request, entry_id: str):
    """Move a pending entry up in the queue."""
    move_in_queue(entry_id, -1)
    return _queue_panel_response(request)


@router.post("/{entry_id}/move-down")
async def move_down(request: Request, entry_id: str):
    """Move a pending entry down in the queue."""
    move_in_queue(entry_id, +1)
    return _queue_panel_response(request)


@router.post("/toggle-pause")
async def toggle_pause(request: Request):
    """Toggle queue pause/resume."""
    snap = get_queue_snapshot()
    if snap.paused:
        resume_queue()
    else:
        pause_queue()
    return _queue_panel_response(request)


@router.post("/cancel-current")
async def cancel_current_route(request: Request):
    """Cancel the currently running job."""
    cancel_current()
    return _queue_panel_response(request)
