"""Settings route."""

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from ...core.config import load_defaults

router = APIRouter(prefix="/settings", tags=["settings"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@router.get("/", response_class=HTMLResponse)
async def settings_page(request: Request):
    """Show settings page."""
    config = load_defaults()
    return templates.TemplateResponse("settings.html", {
        "request": request,
        "config": config,
    })
