"""Generate + serve the Spark viewer-under-test for the Playwright harness.

Companion to ``tests/manual/keyframe-editor.html`` (the shared in-viewer
verification harness for the camera-keyframe-editor plan, Tasks 0 and 6-14).

Same "locally-served generated index.html + browser automation pass" pattern
the repo already uses for viewer verification (cf. ``splatpipe serve`` and the
other ``tests/manual/*.html`` comparison pages) — just scripted so the
harness is reproducible.

  # regenerate the viewer-under-test into tests/manual/_viewer/
  python -m splatpipe.viewers.spark._gen_harness_viewer

  # …and serve tests/manual/ with HTTP Range support (Spark needs Range)
  python -m splatpipe.viewers.spark._gen_harness_viewer --serve 8777
  #   -> http://localhost:8777/keyframe-editor.html

The Task-0 framework (``window.__sceneview``) is built during the viewer
module's synchronous init, BEFORE the async ``scene.rad`` load — so the
harness needs no real ``.rad`` and a 404 on it is expected/irrelevant.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .template import html_for

# tests/manual/ relative to the repo root (…/src/splatpipe/viewers/spark/ → up 4).
_MANUAL_DIR = Path(__file__).resolve().parents[4] / "tests" / "manual"
_VIEWER_DIR = _MANUAL_DIR / "_viewer"
# Task-10 variant: same generated viewer, but its viewer-config.json carries a
# 2-keyframe camera path with `default_path_id` set so the path PLAYER
# auto-starts on init. The shared harness drives this iframe to verify the
# tab-background pause (visibilitychange rebase of the path-player clock).
# Separate dir so Task-0's `_viewer/` (its 15 framework checks) is byte-
# identical and unaffected.
_VIEWER_PATH_DIR = _MANUAL_DIR / "_viewer_path"

# A trivial straight-line 2-keyframe path. `duration` = max kf.t = 600 s, so
# the player keeps ticking for the whole test (no early stopPath). Schema
# matches buildPlayer (sortedKfs needs >= 2 kfs, each with pos[3]; quat[4]
# optional). `default_path_id` makes init call startPath() synchronously.
_HARNESS_PATH_CONFIG = {
    "annotations": [],
    "default_path_id": "harness-path",
    "camera_paths": [
        {
            "id": "harness-path",
            "name": "Harness straight line",
            "loop": False,
            "smoothness": 1.0,
            "play_speed": 1.0,
            "keyframes": [
                {"t": 0.0, "pos": [0.0, 0.0, 0.0],
                 "quat": [0.0, 0.0, 0.0, 1.0], "fov": 60.0},
                {"t": 600.0, "pos": [0.0, 0.0, -100.0],
                 "quat": [0.0, 0.0, 0.0, 1.0], "fov": 60.0},
            ],
        }
    ],
}


def generate() -> Path:
    """Write the viewer-under-test (index.html + stub config) and return its dir.

    Also writes a sibling ``_viewer_path/`` variant (same generated HTML, a
    config with an auto-starting 2-keyframe camera path) used by the shared
    harness's Task-10 tab-background check. Returns the Task-0 ``_viewer/``
    dir (the harness page resolves both relatively).
    """
    _VIEWER_DIR.mkdir(parents=True, exist_ok=True)
    _VIEWER_PATH_DIR.mkdir(parents=True, exist_ok=True)
    # Same generated viewer for both variants — only the config differs.
    html = html_for("HarnessScene")
    (_VIEWER_DIR / "index.html").write_text(html, encoding="utf-8")
    (_VIEWER_PATH_DIR / "index.html").write_text(html, encoding="utf-8")
    # A stub config so the no-store fetch succeeds and the viewer takes its
    # normal (non-error) path; no scene.rad is referenced/needed for the
    # framework-init assertions.
    (_VIEWER_DIR / "viewer-config.json").write_text(
        json.dumps({"annotations": [], "camera_paths": []}), encoding="utf-8"
    )
    (_VIEWER_PATH_DIR / "viewer-config.json").write_text(
        json.dumps(_HARNESS_PATH_CONFIG), encoding="utf-8"
    )
    return _VIEWER_DIR


def serve(port: int) -> None:
    """Serve tests/manual/ with Range support (mirrors serve_cmd.py)."""
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import FileResponse, HTMLResponse
    import uvicorn

    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
    )
    root = _MANUAL_DIR.resolve()

    @app.get("/{file_path:path}")
    def serve_file(file_path: str):
        rel = file_path or "keyframe-editor.html"
        target = (root / rel).resolve()
        if not target.is_relative_to(root):
            return HTMLResponse("Forbidden", status_code=403)
        if not target.is_file():
            return HTMLResponse("Not found", status_code=404)
        return FileResponse(target)

    print(f"Serving {root} on http://localhost:{port}")
    print(f"Harness: http://localhost:{port}/keyframe-editor.html")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--serve", type=int, metavar="PORT", default=None,
        help="After generating, serve tests/manual/ on PORT (Range-capable).",
    )
    args = ap.parse_args(argv)
    d = generate()
    print(f"generated {d / 'index.html'} ({(d / 'index.html').stat().st_size} bytes)")
    print(f"generated {_VIEWER_PATH_DIR / 'index.html'} "
          f"({(_VIEWER_PATH_DIR / 'index.html').stat().st_size} bytes)")
    if args.serve is not None:
        serve(args.serve)
    return 0


if __name__ == "__main__":
    sys.exit(main())
