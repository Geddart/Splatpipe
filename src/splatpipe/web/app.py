"""FastAPI web dashboard for Splatpipe."""

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .routes import projects, settings, steps
from ..core.config import load_defaults

TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="Splatpipe", docs_url=None, redoc_url=None)

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Mount static files
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Include route modules
app.include_router(projects.router)
app.include_router(settings.router)
app.include_router(steps.router)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Redirect to projects list, or to settings on first run."""
    config = load_defaults()
    projects_root = config.get("paths", {}).get("projects_root", "")
    if not projects_root:
        return RedirectResponse("/settings/?setup=true", status_code=303)

    return templates.TemplateResponse("projects.html", {
        "request": request,
        "projects": projects.list_all_projects(),
    })
