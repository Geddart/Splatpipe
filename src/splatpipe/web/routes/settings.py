"""Settings route: editable config form, auto-detect tools, dependency check."""

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from ...core.config import (
    load_defaults,
    save_defaults,
    auto_detect_tools,
    check_dependencies,
)

router = APIRouter(prefix="/settings", tags=["settings"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

# Config sections and their fields with types for form rendering
CONFIG_SCHEMA: dict[str, dict[str, str]] = {
    "paths": {
        "projects_root": "str",
    },
    "tools": {
        "postshot_cli": "str",
        "lichtfeld_studio": "str",
        "colmap": "str",
        "splat_transform": "str",
        "supersplat_url": "str",
    },
    "colmap_clean": {
        "outlier_threshold_auto": "bool",
        "outlier_threshold_fixed": "float",
        "outlier_percentile": "float",
        "outlier_multiplier": "float",
        "kdtree_threshold": "float",
    },
    "postshot": {
        "profile": "str",
        "login": "str",
        "password": "str",
    },
    "lichtfeld": {
        "strategy": "str",
        "iterations": "int",
    },
}


def _parse_value(value: str, type_hint: str):
    """Coerce a form string value to the appropriate Python type."""
    if type_hint == "bool":
        return value.lower() in ("true", "on", "1", "yes")
    if type_hint == "int":
        return int(value) if value else 0
    if type_hint == "float":
        return float(value) if value else 0.0
    return value


def _tool_status(config: dict) -> dict[str, bool]:
    """Check which configured tool paths actually exist on disk."""
    tools = config.get("tools", {})
    status = {}
    for name, path_str in tools.items():
        if not path_str:
            status[name] = False
        elif name == "supersplat_url":
            status[name] = bool(path_str)
        elif path_str in ("splat-transform",):
            # CLI tool checked differently — assume available if configured
            status[name] = True
        else:
            status[name] = Path(path_str).exists()
    return status


@router.get("/", response_class=HTMLResponse)
async def settings_page(request: Request, setup: bool = False):
    """Show settings page."""
    config = load_defaults()
    return templates.TemplateResponse("settings.html", {
        "request": request,
        "config": config,
        "schema": CONFIG_SCHEMA,
        "tool_status": _tool_status(config),
        "setup": setup,
    })


@router.post("/", response_class=HTMLResponse)
async def save_settings(request: Request):
    """Save settings form data to defaults.toml."""
    form = await request.form()
    config = load_defaults()

    for section, fields in CONFIG_SCHEMA.items():
        if section not in config:
            config[section] = {}
        for key, type_hint in fields.items():
            form_key = f"{section}__{key}"
            if type_hint == "bool":
                # Checkboxes only send value when checked
                config[section][key] = form_key in form
            elif form_key in form:
                config[section][key] = _parse_value(str(form[form_key]), type_hint)

    # Preserve coordinate_transform (list type, not in form)
    defaults = load_defaults()
    if "coordinate_transform" in defaults.get("colmap_clean", {}):
        config.setdefault("colmap_clean", {})["coordinate_transform"] = (
            defaults["colmap_clean"]["coordinate_transform"]
        )

    save_defaults(config)

    # Check if this was first-run setup — redirect to projects
    if form.get("_setup") == "true":
        from starlette.responses import RedirectResponse
        return RedirectResponse("/", status_code=303)

    return templates.TemplateResponse("settings.html", {
        "request": request,
        "config": config,
        "schema": CONFIG_SCHEMA,
        "tool_status": _tool_status(config),
        "setup": False,
        "saved": True,
    }, headers={"HX-Trigger": '{"showToast": {"message": "Settings saved", "level": "success"}}'})


@router.get("/detect-tools", response_class=JSONResponse)
async def detect_tools():
    """Auto-detect tool paths and return as JSON."""
    found = auto_detect_tools()
    return found


@router.get("/check-deps", response_class=JSONResponse)
async def check_deps():
    """Check Python package availability."""
    return check_dependencies()


@router.get("/browse", response_class=JSONResponse)
async def browse_filesystem(path: str = "", mode: str = "dir"):
    """List directory contents for the file browser modal.

    Args:
        path: Directory to list. Empty = filesystem roots (drive letters on Windows).
        mode: 'dir' to pick directories, 'file' to pick files.
    """
    import os
    import string

    entries: list[dict] = []

    # No path = list drive roots on Windows, or / on Unix
    if not path:
        if os.name == "nt":
            for letter in string.ascii_uppercase:
                drive = f"{letter}:\\"
                if Path(drive).exists():
                    entries.append({"name": f"{letter}:\\", "path": drive, "is_dir": True})
            return {"current": "", "parent": "", "entries": entries}
        else:
            path = "/"

    p = Path(path)
    if not p.exists() or not p.is_dir():
        return {"current": str(p), "parent": str(p.parent), "entries": [], "error": "Directory not found"}

    parent = str(p.parent) if p.parent != p else ""

    try:
        for item in sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
            # Skip hidden files/dirs
            if item.name.startswith("."):
                continue
            try:
                is_dir = item.is_dir()
            except PermissionError:
                continue
            # In file mode show everything, in dir mode only show dirs
            if mode == "dir" and not is_dir:
                continue
            entries.append({
                "name": item.name,
                "path": str(item),
                "is_dir": is_dir,
            })
    except PermissionError:
        return {"current": str(p), "parent": parent, "entries": [], "error": "Permission denied"}

    return {"current": str(p), "parent": parent, "entries": entries}
