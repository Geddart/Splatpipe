"""Project list, detail, creation, inline edit, and thumbnail routes."""

import json
import os
import shutil
from pathlib import Path

from fastapi import APIRouter, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.templating import Jinja2Templates

from ...core.config import load_defaults
from ...core.constants import (
    STEP_CLEAN, STEP_TRAIN, STEP_ASSEMBLE, STEP_EXPORT,
    FOLDER_COLMAP_SOURCE, FOLDER_COLMAP_CLEAN, FOLDER_TRAINING, FOLDER_REVIEW, FOLDER_OUTPUT,
)
from ...core.project import Project, ALL_STEPS
from ..runner import get_runner

router = APIRouter(prefix="/projects", tags=["projects"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

STEPS = [STEP_CLEAN, STEP_TRAIN, STEP_ASSEMBLE, STEP_EXPORT]

# Maps step names to their output folders
STEP_OUTPUT_FOLDERS = {
    STEP_CLEAN: FOLDER_COLMAP_CLEAN,
    STEP_TRAIN: FOLDER_TRAINING,
    STEP_ASSEMBLE: FOLDER_OUTPUT,
}
# Additional folders to clear when a step is cleared
STEP_EXTRA_FOLDERS = {
    STEP_TRAIN: [FOLDER_REVIEW],
}


def _format_size(size_bytes: int) -> str:
    """Format bytes as human-readable string."""
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.0f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def _folder_stats(folder: Path) -> dict:
    """Count files and total size in a folder (recursive). Includes top-level item listing."""
    if not folder.exists():
        return {"exists": False, "file_count": 0, "total_bytes": 0, "display": "", "file_list": []}
    files = [f for f in folder.rglob("*") if f.is_file()]
    total = sum(f.stat().st_size for f in files)
    if total == 0 and len(files) == 0:
        display = ""
    else:
        display = f"{len(files)} files, {_format_size(total)}"
    # Top-level items with sizes (for delete confirmation)
    items = []
    for item in sorted(folder.iterdir()):
        if item.is_symlink() or (hasattr(item, 'is_junction') and item.is_junction()):
            items.append(f"{item.name}/ (link)")
        elif item.is_dir():
            sub_files = list(item.rglob("*"))
            sub_size = sum(f.stat().st_size for f in sub_files if f.is_file())
            items.append(f"{item.name}/ ({_format_size(sub_size)})")
        else:
            items.append(f"{item.name} ({_format_size(item.stat().st_size)})")
    return {"exists": True, "file_count": len(files), "total_bytes": total, "display": display, "file_list": items}


def _toast(message: str, level: str = "success") -> HTMLResponse:
    trigger = json.dumps({"showToast": {"message": message, "level": level}})
    return HTMLResponse("", headers={"HX-Trigger": trigger})


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
                    "has_thumbnail": state.get("has_thumbnail", False),
                })
            except (json.JSONDecodeError, KeyError):
                continue
    return projects


def _parse_lods(lods_str: str) -> list[dict]:
    """Parse LOD string like '20M,10M,5M,2M,1M,500K' into LOD level dicts."""
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


def _parse_single_lod(lod_str: str, index: int) -> dict:
    """Parse a single LOD string like '5M' into a LOD dict."""
    part = lod_str.strip().upper()
    if part.endswith("M"):
        splats = int(float(part[:-1]) * 1_000_000)
    elif part.endswith("K"):
        splats = int(float(part[:-1]) * 1_000)
    else:
        splats = int(part)
    ksplats = splats // 1000
    name = f"lod{index}_{ksplats}k"
    return {"name": name, "max_splats": splats}


def _renumber_lods(lods: list[dict]) -> list[dict]:
    """Renumber LOD names after add/remove."""
    result = []
    for i, lod in enumerate(lods):
        ksplats = lod["max_splats"] // 1000
        result.append({"name": f"lod{i}_{ksplats}k", "max_splats": lod["max_splats"]})
    return result


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
    lods_str = str(form.get("lods", "20M,10M,5M,2M,1M,500K"))

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


# --- Inline edit endpoints (must be ABOVE catch-all) ---

@router.post("/{project_path:path}/move")
async def move_project(request: Request, project_path: str):
    """Move the entire project folder to a new parent directory.

    Uses os.rename (fast, preserves junctions/symlinks) for same-filesystem
    moves. Falls back to a junction-aware copy for cross-filesystem moves:
    recreates junctions at the destination instead of copying their targets.
    """
    from urllib.parse import quote

    form = await request.form()
    destination = str(form.get("destination", "")).strip()
    if not destination:
        return _toast("Destination is required", "error")

    src = Path(project_path)
    if not src.exists():
        return _toast("Project not found", "error")

    dest_parent = Path(destination)
    if not dest_parent.exists() or not dest_parent.is_dir():
        return _toast("Destination folder does not exist", "error")

    dest = dest_parent / src.name
    if dest.exists():
        return _toast(f"Already exists: {dest}", "error")

    try:
        # os.rename is atomic on same filesystem and preserves junctions
        src.rename(dest)
    except OSError:
        # Cross-filesystem: manual move that preserves junctions
        try:
            _move_project_cross_fs(src, dest)
        except (OSError, shutil.Error) as e:
            return _toast(f"Move failed: {e}", "error")

    # URL-encode the path for the redirect (spaces, special chars)
    dest_url = quote(str(dest), safe=":/\\")
    trigger = json.dumps({"showToast": {"message": f"Moved to {dest}", "level": "success"}})
    return HTMLResponse("", headers={
        "HX-Trigger": trigger,
        "HX-Redirect": f"/projects/{dest_url}/detail",
    })


def _move_project_cross_fs(src: Path, dest: Path) -> None:
    """Move a project across filesystems, preserving junctions/symlinks.

    Junctions are recreated at dest pointing to the same target.
    Regular files/dirs are copied normally, then the source is removed.
    """
    dest.mkdir(parents=True, exist_ok=True)

    for item in src.iterdir():
        src_item = src / item.name
        dest_item = dest / item.name

        if src_item.is_symlink() or (hasattr(src_item, 'is_junction') and src_item.is_junction()):
            # Recreate the junction/symlink at destination
            target = src_item.resolve()
            if os.name == "nt":
                import subprocess
                subprocess.run(
                    ["cmd", "/c", "mklink", "/J", str(dest_item), str(target)],
                    check=True, capture_output=True,
                )
            else:
                dest_item.symlink_to(target, target_is_directory=True)
            # Remove old junction (unlink, not rmtree!)
            src_item.unlink()
        elif src_item.is_dir():
            shutil.copytree(str(src_item), str(dest_item))
            shutil.rmtree(str(src_item))
        else:
            shutil.copy2(str(src_item), str(dest_item))
            src_item.unlink()

    # Remove the now-empty source directory
    src.rmdir()


@router.post("/{project_path:path}/update-name")
async def update_name(request: Request, project_path: str):
    form = await request.form()
    name = str(form.get("name", "")).strip()
    if not name:
        return _toast("Name cannot be empty", "error")
    proj = Project(Path(project_path))
    proj.set_name(name)
    return _toast("Name updated")


@router.post("/{project_path:path}/update-trainer")
async def update_trainer(request: Request, project_path: str):
    form = await request.form()
    trainer = str(form.get("trainer", "postshot"))
    proj = Project(Path(project_path))
    proj.set_trainer(trainer)
    return _toast(f"Trainer set to {trainer}")


@router.post("/{project_path:path}/update-lods")
async def update_lods(request: Request, project_path: str):
    form = await request.form()
    lods_str = str(form.get("lods", ""))
    if not lods_str:
        return _toast("LODs cannot be empty", "error")
    try:
        levels = _parse_lods(lods_str)
    except (ValueError, IndexError):
        return _toast("Invalid LOD format", "error")
    proj = Project(Path(project_path))
    proj.set_lod_levels(levels)
    return _toast(f"{len(levels)} LODs updated")


@router.post("/{project_path:path}/add-lod")
async def add_lod(request: Request, project_path: str):
    form = await request.form()
    lod_str = str(form.get("lod", "")).strip()
    if not lod_str:
        return _toast("LOD value required", "error")
    proj = Project(Path(project_path))
    levels = list(proj.lod_levels)
    try:
        new_lod = _parse_single_lod(lod_str, len(levels))
    except (ValueError, IndexError):
        return _toast("Invalid LOD format (e.g. 5M, 500K)", "error")
    levels.append(new_lod)
    levels = _renumber_lods(levels)
    proj.set_lod_levels(levels)
    # Return updated LOD list partial
    return templates.TemplateResponse("partials/lod_list.html", {
        "request": request,
        "lod_levels": levels,
        "project_path": project_path,
    }, headers={"HX-Trigger": json.dumps({"showToast": {"message": f"Added {lod_str}", "level": "success"}})})


@router.post("/{project_path:path}/remove-lod")
async def remove_lod(request: Request, project_path: str):
    form = await request.form()
    index = int(form.get("index", -1))
    proj = Project(Path(project_path))
    levels = list(proj.lod_levels)
    if 0 <= index < len(levels):
        removed = levels.pop(index)
        levels = _renumber_lods(levels)
        proj.set_lod_levels(levels)
        msg = f"Removed {removed['name']}"
    else:
        msg = "Invalid LOD index"
    return templates.TemplateResponse("partials/lod_list.html", {
        "request": request,
        "lod_levels": levels,
        "project_path": project_path,
    }, headers={"HX-Trigger": json.dumps({"showToast": {"message": msg, "level": "success"}})})


@router.post("/{project_path:path}/update-alignment-file")
async def update_alignment_file(request: Request, project_path: str):
    form = await request.form()
    path = str(form.get("alignment_file", "")).strip()
    proj = Project(Path(project_path))
    proj.set_alignment_file(path)
    return _toast("Alignment file updated")


@router.post("/{project_path:path}/update-colmap-source")
async def update_colmap_source(request: Request, project_path: str):
    form = await request.form()
    path = str(form.get("colmap_source", "")).strip()
    if not path:
        return _toast("COLMAP source path cannot be empty", "error")
    proj = Project(Path(project_path))
    proj.set_colmap_source(path)
    # Re-create the junction/symlink if the folder exists
    source_link = proj.get_folder(FOLDER_COLMAP_SOURCE)
    target = Path(path)
    if target.exists() and target.is_dir():
        # Remove old link/dir if empty
        if source_link.exists():
            if source_link.is_symlink() or (hasattr(source_link, 'is_junction') and source_link.is_junction()):
                source_link.unlink()
            elif source_link.is_dir() and not any(source_link.iterdir()):
                source_link.rmdir()
        if not source_link.exists():
            _create_link(source_link, target)
    return _toast("COLMAP source updated")


@router.post("/{project_path:path}/upload-thumbnail")
async def upload_thumbnail(request: Request, project_path: str):
    form = await request.form()
    file: UploadFile = form.get("file")
    if not file or not file.filename:
        return _toast("No file selected", "error")

    proj = Project(Path(project_path))
    thumb_path = proj.thumbnail_path

    with open(thumb_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    proj.set_has_thumbnail(True)

    # Return updated thumbnail HTML
    html = f'<img src="/projects/{project_path}/thumbnail?t={os.path.getmtime(thumb_path)}" class="w-full h-full object-cover rounded-lg" alt="Thumbnail">'
    return HTMLResponse(html, headers={
        "HX-Trigger": json.dumps({"showToast": {"message": "Thumbnail updated", "level": "success"}})
    })


@router.get("/{project_path:path}/thumbnail")
async def serve_thumbnail(project_path: str):
    proj = Project(Path(project_path))
    if proj.thumbnail_path.exists():
        return FileResponse(proj.thumbnail_path, media_type="image/jpeg")
    return HTMLResponse("", status_code=404)


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
    config = load_defaults()

    steps_info = []
    for step_name in STEPS:
        step_data = state.get("steps", {}).get(step_name)
        # Compute folder stats for steps with output folders
        output_folder_name = STEP_OUTPUT_FOLDERS.get(step_name)
        if output_folder_name:
            stats = _folder_stats(proj.get_folder(output_folder_name))
        else:
            stats = {"exists": False, "file_count": 0, "total_bytes": 0, "display": "", "file_list": []}
        # Runner-aware stale detection: only reset "running" if no runner backs it
        status = step_data["status"] if step_data else "pending"
        is_actively_running = False
        if status == "running":
            r = get_runner(project_path)
            if r and r.snapshot.status == "running":
                is_actively_running = True
            else:
                proj.record_step(step_name, "failed", error="Interrupted (no active runner)")
                status = "failed"
        steps_info.append({
            "name": step_name,
            "status": status,
            "summary": step_data.get("summary") if step_data else None,
            "completed_at": step_data.get("completed_at") if step_data else None,
            "enabled": enabled.get(step_name, True),
            "folder_stats": stats,
            "output_folder": str(proj.get_folder(output_folder_name)) if output_folder_name else "",
            "is_actively_running": is_actively_running,
        })

    # Collect LOD training folder paths
    training_dir = proj.get_folder(FOLDER_TRAINING)
    lod_folders = []
    for lod in proj.lod_levels:
        lod_dir = training_dir / lod["name"]
        lod_folders.append({
            "name": lod["name"],
            "path": str(lod_dir),
            "exists": lod_dir.exists(),
        })

    # Resolve COLMAP source path
    colmap_source_dir = proj.get_folder(FOLDER_COLMAP_SOURCE)
    if colmap_source_dir.is_symlink() or colmap_source_dir.is_junction():
        colmap_source_resolved = str(colmap_source_dir.resolve())
    else:
        colmap_source_resolved = state.get("colmap_source", str(colmap_source_dir))

    # Build step defaults from global config (project overrides applied on top)
    clean_cfg = config.get("colmap_clean", {})
    step_overrides = proj.step_settings
    clean_defaults = {
        "outlier_threshold_auto": clean_cfg.get("outlier_threshold_auto", True),
        "outlier_percentile": clean_cfg.get("outlier_percentile", 0.99),
        "outlier_multiplier": clean_cfg.get("outlier_multiplier", 2.5),
        "kdtree_threshold": clean_cfg.get("kdtree_threshold", 0.001),
    }
    # Apply per-project overrides
    if "clean" in step_overrides:
        clean_defaults.update(step_overrides["clean"])

    class _Obj:
        """Simple attribute-access wrapper for template dicts."""
        def __init__(self, d):
            self.__dict__.update(d)

    postshot_cfg = config.get("postshot", {})
    train_defaults = {
        "profile": postshot_cfg.get("profile", "Splat3"),
        "downsample": postshot_cfg.get("downsample", True),
        "max_image_size": int(postshot_cfg.get("max_image_size", 3840)),
        "anti_aliasing": postshot_cfg.get("anti_aliasing", False),
        "create_sky_model": postshot_cfg.get("create_sky_model", False),
        "train_steps_limit": int(postshot_cfg.get("train_steps_limit", 0)),
    }
    if "train" in step_overrides:
        train_defaults.update(step_overrides["train"])

    export_overrides = step_overrides.get("export", {})
    export_defaults = {
        "export_mode": proj.export_mode,
        "export_folder": proj.export_folder,
        "purge_before_export": export_overrides.get("purge_before_export", False),
    }
    step_defaults = {"clean": _Obj(clean_defaults), "train": _Obj(train_defaults), "export": _Obj(export_defaults)}

    # Build proper subfolder paths (avoid Jinja2 string concat with mixed slashes)
    project_root = proj.root
    folders = {
        "root": str(project_root),
        "colmap_source": colmap_source_resolved,
        "colmap_clean": str(project_root / "02_colmap_clean"),
        "training": str(project_root / "03_training"),
        "review": str(project_root / "04_review"),
        "output": str(project_root / "05_output"),
    }

    return templates.TemplateResponse("project_detail.html", {
        "request": request,
        "project": {
            "name": state["name"],
            "path": str(proj.root),
            "trainer": state.get("trainer", "postshot"),
            "lod_levels": state.get("lod_levels", []),
            "created_at": state.get("created_at", ""),
            "alignment_file": proj.alignment_file,
            "has_thumbnail": proj.has_thumbnail,
            "colmap_source": colmap_source_resolved,
        },
        "steps": steps_info,
        "lod_levels": state.get("lod_levels", []),
        "lod_distances": proj.lod_distances,
        "project_path": str(proj.root),
        "folders": folders,
        "step_defaults": step_defaults,
        "supersplat_url": config.get("tools", {}).get("supersplat_url", "https://superspl.at/editor"),
    })


# --- LOD toggle ---

@router.post("/{project_path:path}/toggle-lod")
async def toggle_lod(request: Request, project_path: str):
    """Toggle a LOD's enabled/disabled state."""
    form = await request.form()
    index = int(form.get("index", -1))
    enabled = form.get("enabled") == "true"
    proj = Project(Path(project_path))
    proj.set_lod_enabled(index, enabled)
    levels = proj.lod_levels
    return templates.TemplateResponse("partials/lod_list.html", {
        "request": request,
        "lod_levels": levels,
        "project_path": project_path,
    }, headers={"HX-Trigger": json.dumps({"showToast": {
        "message": f"LOD {levels[index]['name']} {'enabled' if enabled else 'disabled'}",
        "level": "success",
    }})})


# --- Per-LOD train steps ---

@router.post("/{project_path:path}/update-lod-train-steps")
async def update_lod_train_steps(request: Request, project_path: str):
    """Update per-LOD training steps override."""
    form = await request.form()
    index = int(form.get("index", -1))
    train_steps = int(form.get("train_steps", 0))
    proj = Project(Path(project_path))
    levels = list(proj.lod_levels)
    if 0 <= index < len(levels):
        levels[index]["train_steps"] = train_steps
        proj.set_lod_levels(levels)
        return _toast(f"LOD {levels[index]['name']} train steps: {'auto' if train_steps == 0 else f'{train_steps} kSteps'}")
    return _toast("Invalid LOD index", "error")


# --- Per-step settings ---

@router.post("/{project_path:path}/update-step-settings")
async def update_step_settings(request: Request, project_path: str):
    """Save per-step setting overrides."""
    form = await request.form()
    step_name = str(form.get("step_name", ""))
    if not step_name:
        return _toast("Missing step name", "error")

    # Collect all form fields except step_name
    settings = {}
    for key, value in form.items():
        if key == "step_name":
            continue
        # Convert string booleans
        if value in ("true", "false"):
            settings[key] = value == "true"
        else:
            try:
                settings[key] = float(value)
            except ValueError:
                settings[key] = value

    proj = Project(Path(project_path))
    proj.set_step_settings(step_name, settings)
    return _toast(f"{step_name} settings updated")


# --- Assemble settings ---

@router.post("/{project_path:path}/update-lod-distances")
async def update_lod_distances(request: Request, project_path: str):
    form = await request.form()
    proj = Project(Path(project_path))
    lod_count = len(proj.lod_levels)
    distances = []
    for i in range(lod_count):
        val = form.get(f"dist_{i}", "0")
        try:
            distances.append(float(val))
        except ValueError:
            distances.append(0.0)
    proj.set_lod_distances(distances)
    return _toast("LOD distances updated")


# --- Export settings ---

@router.post("/{project_path:path}/update-export-mode")
async def update_export_mode(request: Request, project_path: str):
    form = await request.form()
    mode = str(form.get("export_mode", "folder"))
    if mode not in ("folder", "cdn"):
        return _toast("Invalid export mode", "error")
    proj = Project(Path(project_path))
    proj.set_export_mode(mode)
    return _toast(f"Export mode set to {mode}")


@router.post("/{project_path:path}/update-export-folder")
async def update_export_folder(request: Request, project_path: str):
    form = await request.form()
    path = str(form.get("export_folder", "")).strip()
    proj = Project(Path(project_path))
    proj.set_export_folder(path)
    return _toast("Export folder updated")


# --- Clear step data ---

def _clear_folder(folder: Path) -> tuple[int, list[str]]:
    """Delete all contents of a folder, preserving the folder itself.

    Removes symlinks/junctions via unlink (not rmtree).
    Returns (count_removed, list_of_failed_paths). Continues on per-item errors
    so locked files don't block deletion of the rest.
    """
    if not folder.exists():
        return 0, []
    count = 0
    failed: list[str] = []
    for item in list(folder.iterdir()):
        try:
            if item.is_symlink() or (hasattr(item, 'is_junction') and item.is_junction()):
                item.unlink()
            elif item.is_dir():
                shutil.rmtree(str(item))
            else:
                item.unlink()
            count += 1
        except OSError:
            failed.append(item.name)
    return count, failed


@router.post("/{project_path:path}/clear-step/{step_name}")
async def clear_step(project_path: str, step_name: str):
    """Clear output files for a step and reset its status."""
    proj = Project(Path(project_path))
    removed = 0
    all_failed: list[str] = []
    folder_name = STEP_OUTPUT_FOLDERS.get(step_name)
    if folder_name:
        n, failed = _clear_folder(proj.get_folder(folder_name))
        removed += n
        all_failed.extend(failed)
    for extra in STEP_EXTRA_FOLDERS.get(step_name, []):
        n, failed = _clear_folder(proj.get_folder(extra))
        removed += n
        all_failed.extend(failed)
    proj.reset_step(step_name)
    if all_failed:
        locked = ", ".join(all_failed)
        return _toast(f"Cleared {step_name}: {removed} removed, {len(all_failed)} locked ({locked})", level="warning")
    return _toast(f"Cleared {step_name}: {removed} items removed")


@router.post("/{project_path:path}/clear-all")
async def clear_all(project_path: str):
    """Clear all step output folders and reset all step statuses."""
    proj = Project(Path(project_path))
    total_removed = 0
    all_failed: list[str] = []
    for step_name, folder_name in STEP_OUTPUT_FOLDERS.items():
        folder = proj.get_folder(folder_name)
        n, failed = _clear_folder(folder)
        total_removed += n
        all_failed.extend(failed)
    proj.reset_all_steps()
    if all_failed:
        locked = ", ".join(all_failed)
        return _toast(f"Cleared all: {total_removed} removed, {len(all_failed)} locked ({locked})", level="warning")
    return _toast(f"Cleared all data: {total_removed} items removed")


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
