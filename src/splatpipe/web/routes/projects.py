"""Project list, detail, creation, and step toggle routes."""

import json
import os
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ...core.config import load_defaults
from ...core.constants import STEP_CLEAN, STEP_TRAIN, STEP_ASSEMBLE, STEP_DEPLOY
from ...core.project import Project, ALL_STEPS

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


def _parse_lods(lods_str: str) -> list[dict]:
    """Parse LOD string like '20M,10M,5M,3M,1.5M' into LOD level dicts."""
    levels = []
    for i, part in enumerate(lods_str.split(",")):
        part = part.strip().upper()
        if part.endswith("M"):
            splats = int(float(part[:-1]) * 1_000_000)
        elif part.endswith("K"):
            splats = int(float(part[:-1]) * 1_000)
        else:
            splats = int(part)
        ksplats = splats // 1000
        name = f"lod{i}_{ksplats}k"
        levels.append({"name": name, "max_splats": splats})
    return levels


def _create_link(link_path: Path, target: Path) -> None:
    """Create a directory junction (Windows) or symlink (Unix)."""
    if os.name == "nt":
        import subprocess
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link_path), str(target)],
            check=True, capture_output=True,
        )
    else:
        link_path.symlink_to(target, target_is_directory=True)


# --- Project creation (must be ABOVE the catch-all route) ---

@router.get("/new", response_class=HTMLResponse)
async def new_project_form(request: Request):
    """Show project creation form."""
    return templates.TemplateResponse("create_project.html", {
        "request": request,
        "values": {},
        "error": None,
    })


@router.post("/new", response_class=HTMLResponse)
async def create_project(request: Request):
    """Handle project creation form submission."""
    form = await request.form()

    name = str(form.get("name", "")).strip()
    colmap_dir_str = str(form.get("colmap_dir", "")).strip()
    trainer = str(form.get("trainer", "postshot"))
    lods_str = str(form.get("lods", "20M,10M,5M,3M,1.5M"))

    values = {
        "name": name,
        "colmap_dir": colmap_dir_str,
        "trainer": trainer,
        "lods": lods_str,
    }

    # Collect enabled steps from checkboxes
    for step in ALL_STEPS:
        values[f"step_{step}"] = f"step_{step}" in form

    # Validation
    if not name:
        return templates.TemplateResponse("create_project.html", {
            "request": request, "values": values,
            "error": "Project name is required.",
        })

    colmap_dir = Path(colmap_dir_str)
    if not colmap_dir.exists():
        return templates.TemplateResponse("create_project.html", {
            "request": request, "values": values,
            "error": f"COLMAP directory does not exist: {colmap_dir}",
        })

    required_files = ["cameras.txt", "images.txt", "points3D.txt"]
    missing = [f for f in required_files if not (colmap_dir / f).exists()]
    if missing:
        return templates.TemplateResponse("create_project.html", {
            "request": request, "values": values,
            "error": f"Missing COLMAP files: {', '.join(missing)}",
        })

    # Parse LODs
    try:
        lod_levels = _parse_lods(lods_str)
    except (ValueError, IndexError):
        return templates.TemplateResponse("create_project.html", {
            "request": request, "values": values,
            "error": "Invalid LOD format. Use comma-separated values like '20M,10M,5M'.",
        })

    # Build enabled_steps
    enabled_steps = {step: f"step_{step}" in form for step in ALL_STEPS}

    # Create project
    config = load_defaults()
    projects_root = config.get("paths", {}).get("projects_root", "")
    if not projects_root:
        return templates.TemplateResponse("create_project.html", {
            "request": request, "values": values,
            "error": "projects_root not configured. Go to Settings first.",
        })

    project_dir = Path(projects_root) / name

    if project_dir.exists() and (project_dir / "state.json").exists():
        return templates.TemplateResponse("create_project.html", {
            "request": request, "values": values,
            "error": f"Project already exists at {project_dir}",
        })

    project = Project.create(
        project_dir,
        name,
        trainer=trainer,
        lod_levels=lod_levels,
        colmap_source=str(colmap_dir),
        enabled_steps=enabled_steps,
    )

    # Create symlink/junction from 01_colmap_source to COLMAP data
    source_link = project.get_folder("01_colmap_source")
    if source_link.exists() and not any(source_link.iterdir()):
        source_link.rmdir()
        _create_link(source_link, colmap_dir)

    return RedirectResponse(f"/projects/{project.root}/detail", status_code=303)


# --- List and detail ---

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
    enabled = proj.enabled_steps

    steps_info = []
    for step_name in STEPS:
        step_data = state.get("steps", {}).get(step_name)
        steps_info.append({
            "name": step_name,
            "status": step_data["status"] if step_data else "pending",
            "summary": step_data.get("summary") if step_data else None,
            "completed_at": step_data.get("completed_at") if step_data else None,
            "enabled": enabled.get(step_name, True),
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


# --- Step toggle ---

@router.post("/{project_path:path}/toggle-step", response_class=HTMLResponse)
async def toggle_step(request: Request, project_path: str):
    """Toggle a step's enabled/disabled state via HTMX."""
    form = await request.form()
    step_name = str(form.get("step_name", ""))
    enabled = form.get("enabled") == "true"

    proj = Project(Path(project_path))
    proj.set_step_enabled(step_name, enabled)

    # Return updated project detail
    return RedirectResponse(f"/projects/{project_path}/detail", status_code=303)
