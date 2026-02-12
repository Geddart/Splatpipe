"""Project list and detail routes."""

import json
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from ...core.config import load_defaults
from ...core.constants import STEP_CLEAN, STEP_TRAIN, STEP_ASSEMBLE, STEP_DEPLOY
from ...core.project import Project

router = APIRouter(prefix="/projects", tags=["projects"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

STEPS = [STEP_CLEAN, STEP_TRAIN, STEP_ASSEMBLE, STEP_DEPLOY]


def list_all_projects() -> list[dict]:
    """Scan projects_root for splatpipe projects."""
    config = load_defaults()
    root = config.get("paths", {}).get("projects_root", "")
    if not root or not Path(root).exists():
        return []

    projects = []
    for d in sorted(Path(root).iterdir()):
        state_path = d / "state.json"
        if state_path.exists():
            try:
                state = json.loads(state_path.read_text())
                projects.append({
                    "name": state.get("name", d.name),
                    "path": str(d),
                    "trainer": state.get("trainer", "postshot"),
                    "steps": state.get("steps", {}),
                    "lod_count": len(state.get("lod_levels", [])),
                })
            except (json.JSONDecodeError, KeyError):
                continue
    return projects


@router.get("/", response_class=HTMLResponse)
async def project_list(request: Request):
    """Show all projects."""
    return templates.TemplateResponse("projects.html", {
        "request": request,
        "projects": list_all_projects(),
    })


@router.get("/{project_path:path}/detail", response_class=HTMLResponse)
async def project_detail(request: Request, project_path: str):
    """Show project detail view."""
    proj = Project(Path(project_path))
    state = proj.state

    steps_info = []
    for step_name in STEPS:
        step_data = state.get("steps", {}).get(step_name)
        steps_info.append({
            "name": step_name,
            "status": step_data["status"] if step_data else "pending",
            "summary": step_data.get("summary") if step_data else None,
            "completed_at": step_data.get("completed_at") if step_data else None,
        })

    return templates.TemplateResponse("project_detail.html", {
        "request": request,
        "project": {
            "name": state["name"],
            "path": str(proj.root),
            "trainer": state.get("trainer", "postshot"),
            "lod_levels": state.get("lod_levels", []),
            "created_at": state.get("created_at", ""),
        },
        "steps": steps_info,
    })
