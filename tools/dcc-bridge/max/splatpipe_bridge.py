"""Splatpipe Bridge for 3ds Max.

Adds a tiny dockable dialog with two buttons:

  * **Pull splat from Splatpipe** — paste a project URL, click Pull. Loads
    the preview-LOD PLY into a fresh VRayGaussiansGeom node, wraps it in
    two nested empties (outer R_180X + inner R_+90X — see the docstring
    of `setup_stand_up_parent`), creates a target camera, sets the active
    frame range from the manifest.

  * **Send camera to Splatpipe** — extracts the active camera's PRS
    controller keyframes and FOV per frame, composes against
    `inv(splatpipe_inner.matrix_world)` to convert into PlayCanvas-displayed
    frame, POSTs the result to ``/dcc/import-camera``.

Install: drag this file into a Max viewport (or run it once via Scripting →
Run Script). Adds itself to a top-level "Splatpipe" menu.

Requires:
  * 3ds Max 2023+ (for the bundled Python 3 + pymxs)
  * V-Ray 7+ (for the VRayGaussiansGeom node)
  * Splatpipe web running locally (http://localhost:8000 by default)

No third-party Python packages: only urllib + json + tempfile + tkinter,
all in Max's bundled stdlib.

Coord-system contract: see ``docs/dcc-bridge.md`` in the Splatpipe repo.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
import urllib.request
import urllib.parse
from urllib.error import HTTPError, URLError

# pymxs is provided by 3ds Max's Python interpreter.
try:
    from pymxs import runtime as rt
except ImportError as e:
    raise SystemExit(
        "splatpipe_bridge requires 3ds Max's bundled Python (pymxs missing). "
        "Run this script from inside Max, not standalone."
    ) from e


OUTER_NAME = "splatpipe_outer"
INNER_NAME = "splatpipe_inner"
SPLAT_NAME = "splatpipe_splat"
CAM_NAME = "splatpipe_cam"


# ---- HTTP helpers ---------------------------------------------------------


def http_get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def http_get_to_file(url: str, dest_path: str) -> None:
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=600) as resp, open(dest_path, "wb") as f:
        chunk = 1 << 20
        while True:
            data = resp.read(chunk)
            if not data:
                break
            f.write(data)


def http_post_json(url: str, body: dict) -> dict:
    payload = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload, method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ---- Stand-Up Parent ------------------------------------------------------


def setup_stand_up_parent(splat_node) -> tuple[object, object]:
    """Wrap `splat_node` in two empties to make it look right in DCC's Z-up world.

    Outer (`splatpipe_outer`):  rotation 180° about world X — undoes COLMAP Y-down.
    Inner (`splatpipe_inner`):  rotation  90° X in **local** coordsys — converts
                                Y-up to Z-up. Composed with outer this yields
                                inner.world = R_-90X.

    Net splat orientation = R_-90X (right-side up in Z-up DCC). Returns
    (outer, inner). The export step composes
    `cam.transform * inverse(inner.transform) * rotateXMatrix(180)` to land
    the camera in PlayCanvas-displayed (Y-up) frame — see send_camera().
    """
    # Remove any prior bridge nodes so re-pulling is idempotent.
    for n in (OUTER_NAME, INNER_NAME):
        existing = rt.getNodeByName(n, exact=True)
        if existing is not None:
            rt.delete(existing)

    outer = rt.Dummy(name=OUTER_NAME)
    outer.rotation = rt.eulerangles(180.0, 0.0, 0.0)
    outer.isHidden = False  # visible so the user knows the bridge owns these

    inner = rt.Dummy(name=INNER_NAME)
    # IMPORTANT: parent FIRST, then set inner rotation. If we set rotation
    # before parenting, Max preserves the world transform on parent assignment
    # — leaving inner.world = R_+90X instead of the documented R_-90X composed
    # result. That breaks the export math and the splat appears upside-down.
    # After parenting, `inner.rotation = ...` is interpreted in local coordsys,
    # which is what we want. Confirmed via 3dsmax-mcp probe (v0.6.3).
    inner.parent = outer
    inner.rotation = rt.eulerangles(90.0, 0.0, 0.0)

    splat_node.parent = inner
    return outer, inner


# ---- Pull splat -----------------------------------------------------------


def pull_splat(project_url: str) -> dict:
    """Download the splat PLY and set up the scene. Returns the manifest dict."""
    project_url = project_url.rstrip("/")
    manifest = http_get_json(f"{project_url}/dcc/manifest")

    # Download the preview LOD PLY (smaller; full LOD is huge).
    preview_url = manifest.get("splat_preview_url") or manifest.get("splat_full_url")
    if not preview_url:
        raise RuntimeError("Manifest has no splat URL")
    if preview_url.startswith("/"):
        # Resolve relative URL against the project URL's origin
        parsed = urllib.parse.urlparse(project_url)
        preview_url = f"{parsed.scheme}://{parsed.netloc}{preview_url}"

    tmp = tempfile.NamedTemporaryFile(suffix=".ply", delete=False)
    tmp.close()
    rt.format("Splatpipe: downloading preview PLY to %\n", tmp.name)
    http_get_to_file(preview_url, tmp.name)

    # Create a VRayGaussiansGeom node loading the PLY. V-Ray's MaxScript
    # exposes it as VRayGaussiansGeom; the file is set via .file property.
    cls = getattr(rt, "VRayGaussiansGeom", None)
    if cls is None:
        raise RuntimeError(
            "VRayGaussiansGeom not found. Install V-Ray 7+ (which adds Gaussian "
            "splat support) and reload this dialog."
        )
    splat = cls(name=SPLAT_NAME)
    splat.file = tmp.name

    outer, inner = setup_stand_up_parent(splat)

    # Camera + frame range
    cam = rt.getNodeByName(CAM_NAME, exact=True)
    if cam is None:
        cam = rt.FreeCamera(name=CAM_NAME)
    cam.position = rt.point3(0, -10, 5)  # in DCC frame: 10 units back, 5 up
    cam.fov = 60

    fr = manifest.get("frame_range") or {"start": 1, "end": 240}
    rt.animationRange = rt.interval(int(fr.get("start", 1)), int(fr.get("end", 240)))

    rt.format("Splatpipe: scene ready. Animate %, then click Send.\n", CAM_NAME)
    return manifest


# ---- Send camera ----------------------------------------------------------


def send_camera(project_url: str, name: str = "Max DCC Path") -> dict:
    """Sample the active camera each frame, compose against inner inverse, POST."""
    project_url = project_url.rstrip("/")

    cam = rt.getNodeByName(CAM_NAME, exact=True)
    if cam is None:
        raise RuntimeError(
            f"No camera named '{CAM_NAME}'. Pull a splat first (creates the camera) "
            f"or rename your camera to '{CAM_NAME}'."
        )
    inner = rt.getNodeByName(INNER_NAME, exact=True)
    if inner is None:
        raise RuntimeError(
            f"No '{INNER_NAME}' empty in the scene. Pull a splat first to set up "
            f"the Stand-Up Parent."
        )

    fr = rt.animationRange
    f_start = int(fr.start)
    f_end = int(fr.end)
    fps = float(rt.framerate)

    # Stand-Up Parent compose math (row-vec MaxScript form).
    #
    # We want: cam_in_pc_displayed = R_180X @ inv(inner.matrix_world) @ cam (col-vec).
    # In MaxScript row-vec convention this is:
    #     cam.transform * inverse(inner.transform) * rotateXMatrix(180)
    # — apply cam first, then map into inner-local (= PLY-native), then flip
    # 180° X to land in PC-displayed.
    #
    # The previous version of this code shipped without the rotateXMatrix(180)
    # — the exported camera ended up mirrored on Y. Fixed in v0.6.2.
    flip_180_x = rt.rotateXMatrix(180.0)
    inner_inv = rt.inverse(inner.transform)

    frames = []
    for f in range(f_start, f_end + 1):
        rt.sliderTime = f  # advances animation evaluation
        cam_world = cam.transform
        composed = cam_world * inner_inv * flip_180_x
        pos = composed.translation
        # Max's quat order is (x, y, z, w) for `composed.rotation`.
        q = composed.rotation
        qx, qy, qz, qw = float(q.x), float(q.y), float(q.z), float(q.w)
        fov_deg = float(cam.fov)
        frames.append({
            "frame": f - f_start,
            "pos": [float(pos.x), float(pos.y), float(pos.z)],
            "quat": [qx, qy, qz, qw],
            "fov": fov_deg,
        })

    payload = {
        "name": name,
        "fps": fps,
        "coord_frame": "playcanvas_displayed",
        "smoothness": 1.0,
        "play_speed": 1.0,
        "loop": False,
        "frames": frames,
    }
    result = http_post_json(f"{project_url}/dcc/import-camera", payload)
    rt.format("Splatpipe: posted % frames → path id %\n", len(frames), result.get("id"))
    return result


# ---- Tiny tkinter dialog --------------------------------------------------


def open_dialog():
    """Open a small floating dialog with the two buttons. Tkinter is bundled
    with Max's Python so no install needed."""
    import tkinter as tk
    from tkinter import messagebox

    win = tk.Tk()
    win.title("Splatpipe Bridge")
    win.geometry("420x180")
    win.resizable(False, False)

    tk.Label(win, text="Splatpipe project URL:").pack(anchor="w", padx=12, pady=(12, 0))
    url_var = tk.StringVar(value="http://localhost:8000/projects/")
    url_entry = tk.Entry(win, textvariable=url_var, width=58)
    url_entry.pack(padx=12, pady=4)

    tk.Label(win, text="Path name (for Send):").pack(anchor="w", padx=12, pady=(8, 0))
    name_var = tk.StringVar(value="Max DCC Path")
    tk.Entry(win, textvariable=name_var, width=58).pack(padx=12, pady=4)

    def on_pull():
        try:
            manifest = pull_splat(url_var.get().strip())
            messagebox.showinfo(
                "Splatpipe",
                f"Loaded splat for '{manifest.get('project_name')}'. "
                f"Animate the camera, then click Send."
            )
        except (HTTPError, URLError) as e:
            messagebox.showerror("Splatpipe", f"Network error: {e}")
        except Exception as e:
            messagebox.showerror("Splatpipe", str(e))

    def on_send():
        try:
            r = send_camera(url_var.get().strip(), name=name_var.get().strip() or "Max DCC Path")
            messagebox.showinfo("Splatpipe", f"Sent. Path id: {r.get('id')}")
        except (HTTPError, URLError) as e:
            messagebox.showerror("Splatpipe", f"Network error: {e}")
        except Exception as e:
            messagebox.showerror("Splatpipe", str(e))

    btn_frame = tk.Frame(win)
    btn_frame.pack(pady=12)
    tk.Button(btn_frame, text="Pull splat", width=18, command=on_pull).pack(side="left", padx=6)
    tk.Button(btn_frame, text="Send camera", width=18, command=on_send).pack(side="left", padx=6)

    win.mainloop()


# ---- Macro registration ---------------------------------------------------


def register_max_macro():
    """Register a Max macro so the dialog can be launched from the menu/toolbar."""
    macro_src = """
        macroScript SplatpipeBridge
            category:"Splatpipe"
            buttonText:"Splatpipe Bridge"
            tooltip:"Open the Splatpipe DCC Bridge dialog"
        (
            python.execute "import splatpipe_bridge; splatpipe_bridge.open_dialog()"
        )
    """
    rt.execute(macro_src)
    rt.format("Splatpipe Bridge macro registered (Customize -> category 'Splatpipe').\n")


if __name__ == "__main__":
    # When run directly via Max's "Run Script" command, just open the dialog.
    open_dialog()
