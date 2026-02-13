"""Actions router: launch tools, open files/folders."""

import json
import os
import subprocess
import webbrowser
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from ...core.config import load_defaults, get_postshot_gui, get_lichtfeld_exe, get_colmap_exe

router = APIRouter(prefix="/actions", tags=["actions"])


def _toast(message: str, level: str = "success") -> HTMLResponse:
    """Return empty HTML with a showToast HX-Trigger."""
    trigger = json.dumps({"showToast": {"message": message, "level": level}})
    return HTMLResponse("", headers={"HX-Trigger": trigger})


def _open_in_foreground(path: str) -> None:
    """Open a file or folder via explorer so it appears in the foreground.

    ``os.startfile`` spawns from the server process which lacks foreground
    rights on Windows, causing the window to open behind the browser.
    Launching ``explorer.exe`` directly gives it its own activation context.
    """
    if os.name == "nt":
        # /select, highlights the item in its parent — and always foregrounds
        subprocess.Popen(["explorer", "/select,", path])
    else:
        subprocess.Popen(["xdg-open", path])


@router.post("/{project_path:path}/open-folder")
async def open_folder(request: Request, project_path: str):
    """Open a folder in the system file manager."""
    form = await request.form()
    raw = str(form.get("folder", ""))

    if not raw:
        return _toast("No folder specified", "error")

    # Normalize mixed slashes (Jinja2 concat can produce H:\foo/bar)
    folder = str(Path(raw))

    if not Path(folder).exists():
        # Try opening the parent if the subfolder hasn't been created yet
        parent = str(Path(folder).parent)
        if Path(parent).exists():
            _open_in_foreground(parent)
            return _toast(f"Folder not yet created, opened parent")
        return _toast(f"Folder not found: {folder}", "error")

    _open_in_foreground(folder)
    return _toast("Opened folder")


@router.post("/{project_path:path}/open-file")
async def open_file(request: Request, project_path: str):
    """Open a file with its default system application."""
    form = await request.form()
    file_path = str(form.get("file", ""))

    if not file_path or not Path(file_path).exists():
        return _toast(f"File not found: {file_path}", "error")

    _open_in_foreground(file_path)
    return _toast("Opened file")


@router.post("/{project_path:path}/open-tool")
async def open_tool(request: Request, project_path: str):
    """Launch an external tool (Postshot, LichtFeld, COLMAP, SuperSplat)."""
    form = await request.form()
    tool = str(form.get("tool", ""))
    config = load_defaults()
    tools = config.get("tools", {})

    if tool == "postshot":
        try:
            gui_path = get_postshot_gui(config)
            subprocess.Popen([str(gui_path)], start_new_session=True)
            return _toast("Launched Postshot")
        except (ValueError, FileNotFoundError) as e:
            return _toast(str(e), "error")

    elif tool == "lichtfeld":
        try:
            lf_exe = get_lichtfeld_exe(config)
            subprocess.Popen([str(lf_exe)], start_new_session=True)
            return _toast("Launched LichtFeld Studio")
        except (ValueError, FileNotFoundError) as e:
            return _toast(str(e), "error")

    elif tool == "colmap":
        try:
            colmap_exe = get_colmap_exe(config)
            subprocess.Popen([str(colmap_exe), "gui"], start_new_session=True)
            return _toast("Launched COLMAP GUI")
        except (ValueError, FileNotFoundError) as e:
            return _toast(str(e), "error")

    elif tool == "supersplat":
        url = tools.get("supersplat_url", "https://superspl.at/editor")
        webbrowser.open(url)
        return _toast("Opened SuperSplat in browser")

    return _toast(f"Unknown tool: {tool}", "error")
