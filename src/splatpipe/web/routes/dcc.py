"""DCC bridge endpoints — feed splat to Max/Blender, ingest camera back.

Three routes mounted under ``/projects/{p}/dcc/``:

  * ``GET  /manifest``        — JSON describing the project for a DCC client.
  * ``GET  /splat.ply``       — streams a reviewed PLY (Range-capable).
                                ``?lod=N`` selects a smaller LOD if present.
  * ``POST /import-camera``   — accepts JSON ``{name, fps, coord_frame, frames}``
                                or a multipart ``.glb`` upload, appends a new
                                entry to ``scene_config.camera_paths``.

Coordinate-frame contract
-------------------------
Splatpipe stores annotations + camera-paths in **PlayCanvas-displayed frame**
(Y-up, after the 180°-X COLMAP-undo flip). Two valid wire formats:

  * ``coord_frame = "playcanvas_displayed"`` — bridge has already composed
    against its stand-up parent inverse; importer writes coords as-is.
  * ``coord_frame = "ply_native"`` — importer applies the 180°-X flip.

DCC bridge clients (Tier 1 Claude+MCP, Tier 2 in-DCC plugin buttons) always
send ``"playcanvas_displayed"``; generic glTF imports go through the existing
``/import-gltf-path`` route which assumes ``"ply_native"`` and applies the flip.

See ``docs/dcc-bridge.md`` for the math.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse

from ...core.constants import FOLDER_REVIEW
from ...core.path_io import (
    DEFAULT_PLAY_SPEED,
    DEFAULT_SMOOTHNESS,
    KeyframeDict,
    PathDict,
    mutate_paths,
    new_path,
)
from ...core.project import Project

router = APIRouter(prefix="/projects", tags=["dcc"])


@router.get("/{project_path:path}/dcc/manifest")
async def dcc_manifest(project_path: str):
    """Return the metadata a DCC client needs to set up the scene."""
    proj = Project(Path(project_path))
    review_dir = proj.get_folder(FOLDER_REVIEW)

    # Find available reviewed PLYs (lod0_reviewed.ply, lod1_reviewed.ply, ...).
    available_lods = []
    for i, lod in enumerate(proj.lod_levels):
        ply = review_dir / f"lod{i}_reviewed.ply"
        if ply.is_file():
            available_lods.append({
                "lod_index": i,
                "name": lod.get("name", f"lod{i}"),
                "size_bytes": ply.stat().st_size,
            })

    has_colmap = False
    try:
        cdir = proj.colmap_dir()
        from ...colmap.parsers import detect_colmap_format
        has_colmap = detect_colmap_format(cdir) != "unknown"
    except Exception:
        pass

    base_url = f"/projects/{project_path}/dcc"
    # For the DCC viewport preview, default to a smaller LOD if available so
    # we don't ship multi-GB files just to position cameras.
    preview_lod = available_lods[-1]["lod_index"] if len(available_lods) > 1 else 0
    full_lod = available_lods[0]["lod_index"] if available_lods else 0

    return JSONResponse({
        "project_name": proj.name,
        "project_path": str(proj.root),
        "splat_full_url": f"{base_url}/splat.ply?lod={full_lod}",
        "splat_preview_url": f"{base_url}/splat.ply?lod={preview_lod}",
        "available_lods": available_lods,
        "has_colmap_source": has_colmap,
        "frame_range": {"start": 1, "end": 240},  # 10s @ 24fps default; user can override
        "fps": 24,
        "coord_frame_contract": "playcanvas_displayed",
        "existing_paths": [
            {"id": p.get("id"), "name": p.get("name"), "keyframe_count": len(p.get("keyframes") or [])}
            for p in (proj.scene_config.get("camera_paths") or [])
        ],
        "default_path_id": proj.scene_config.get("default_path_id"),
        "import_camera_url": f"{base_url}/import-camera",
    })


@router.get("/{project_path:path}/dcc/splat.ply")
async def dcc_splat_ply(project_path: str, lod: int = 0):
    """Stream a reviewed PLY for the DCC client to load (Range-capable)."""
    proj = Project(Path(project_path))
    review_dir = proj.get_folder(FOLDER_REVIEW)
    ply = review_dir / f"lod{lod}_reviewed.ply"
    if not ply.is_file():
        # Fall back to the highest-quality LOD if the requested one doesn't exist.
        candidates = sorted(review_dir.glob("lod*_reviewed.ply"))
        if not candidates:
            return JSONResponse({"error": f"no reviewed PLYs in {review_dir}"}, status_code=404)
        ply = candidates[0]
    return FileResponse(
        ply,
        media_type="application/octet-stream",
        headers={
            "Access-Control-Allow-Origin": "*",
            "Content-Disposition": f'inline; filename="{ply.name}"',
        },
    )


@router.post("/{project_path:path}/dcc/import-camera")
async def dcc_import_camera(request: Request, project_path: str):
    """Append a camera-path entry from a DCC bridge client.

    Body shapes:

    Native JSON::

        {
          "name": "Tour 1",
          "fps": 24,
          "coord_frame": "playcanvas_displayed" | "ply_native",
          "smoothness": 1.0,
          "play_speed": 1.0,
          "loop": false,
          "frames": [
            { "frame": 0,   "pos": [x,y,z], "quat": [x,y,z,w], "fov": 60 },
            { "frame": 24,  "pos": [...],   "quat": [...],     "fov": 70 },
            ...
          ]
        }

    Multipart ``.glb`` upload (field name ``file``) — falls through to the
    Phase A glTF importer with ``flip_180_x=True`` (assumes ``ply_native``).
    """
    proj = Project(Path(project_path))

    content_type = request.headers.get("content-type", "")
    if content_type.startswith("multipart/"):
        return await _import_camera_glb(request, proj)
    return await _import_camera_json(request, proj)


async def _import_camera_json(request: Request, proj: Project):
    body = await request.json()
    frames = body.get("frames") or []
    if not frames:
        return JSONResponse({"error": "no frames"}, status_code=400)

    fps = float(body.get("fps", 24.0)) or 24.0
    coord_frame = body.get("coord_frame", "playcanvas_displayed")
    if coord_frame not in ("playcanvas_displayed", "ply_native"):
        return JSONResponse({"error": f"unknown coord_frame: {coord_frame}"}, status_code=400)

    # If the client is sending PLY-native coords, apply the 180°-X flip to bring
    # them into PC-displayed frame (the storage convention).
    if coord_frame == "ply_native":
        for f in frames:
            f["pos"], f["quat"] = _flip_180_x(f.get("pos") or [0, 0, 0], f.get("quat") or [0, 0, 0, 1])

    keyframes: list[KeyframeDict] = []
    for f in frames:
        keyframes.append({
            "t": float(f["frame"]) / fps,
            "pos": [float(x) for x in f.get("pos", [0, 0, 0])],
            "quat": [float(x) for x in f.get("quat", [0, 0, 0, 1])],
            "fov": float(f.get("fov", 60.0)),
            # DCC tracks are dense (typically one kf per frame) — straight
            # linear easing reads the dense samples at face value. The
            # smoothness slider on the path can still re-spline if the user
            # wants extra interpolation.
            "easing_out": "linear",
            "hold_s": 0.0,
            "annotation_id": None,
        })

    path = new_path(
        body.get("name") or "DCC Path",
        keyframes=keyframes,
        loop=bool(body.get("loop", False)),
        smoothness=float(body.get("smoothness", DEFAULT_SMOOTHNESS)),
        play_speed=float(body.get("play_speed", DEFAULT_PLAY_SPEED)),
    )
    mutate_paths(proj, lambda paths: paths + [path])
    return JSONResponse({
        "ok": True,
        "id": path["id"],
        "name": path["name"],
        "keyframe_count": len(keyframes),
        "coord_frame_received": coord_frame,
    })


async def _import_camera_glb(request: Request, proj: Project):
    """Multipart .glb fallback — same behavior as Phase A's /import-gltf-path."""
    import tempfile
    from ...core.path_io import from_gltf

    form = await request.form()
    upload = form.get("file")
    if upload is None:
        return JSONResponse({"ok": False, "error": "missing 'file' field"}, status_code=400)
    name = request.query_params.get("name") or Path(upload.filename).stem
    sample_hz = request.query_params.get("sample_hz")
    sample_hz_f = float(sample_hz) if sample_hz else None

    suffix = ".glb" if upload.filename.lower().endswith(".glb") else ".gltf"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(await upload.read())
        tmp_path = tmp.name
    try:
        path = from_gltf(tmp_path, name=name, sample_hz=sample_hz_f, flip_180_x=True)
    finally:
        try:
            import os
            os.unlink(tmp_path)
        except OSError:
            pass

    mutate_paths(proj, lambda paths: paths + [path])
    return JSONResponse({
        "ok": True, "id": path["id"], "name": path["name"],
        "keyframe_count": len(path["keyframes"]),
        "coord_frame_received": "ply_native (glb fallback)",
    })


def _flip_180_x(pos, quat):
    """Apply 180° X rotation to a position + xyzw quaternion.

    R_180X = diag(1, -1, -1) on positions; quaternion multiplication by
    (x=1, y=0, z=0, w=0) for orientations.
    """
    px, py, pz = float(pos[0]), float(pos[1]), float(pos[2])
    qx, qy, qz, qw = float(quat[0]), float(quat[1]), float(quat[2]), float(quat[3])
    new_pos = [px, -py, -pz]
    # Hamilton product: (1,0,0,0) * (qx,qy,qz,qw) =
    #   x =  1*qw + 0*qz - 0*qy + 0*qx = qw
    #   y =  1*-qz + 0*qw + 0*qx + 0*qy = ... easier to just compute fully:
    # f = (1,0,0,0)  (xyzw)
    # f * q = (
    #   fw*qx + fx*qw + fy*qz - fz*qy,
    #   fw*qy - fx*qz + fy*qw + fz*qx,
    #   fw*qz + fx*qy - fy*qx + fz*qw,
    #   fw*qw - fx*qx - fy*qy - fz*qz )
    # with f = (1,0,0,0): fx=1, fy=0, fz=0, fw=0
    nx = 0 * qx + 1 * qw + 0 * qz - 0 * qy
    ny = 0 * qy - 1 * qz + 0 * qw + 0 * qx
    nz = 0 * qz + 1 * qy - 0 * qx + 0 * qw
    nw = 0 * qw - 1 * qx - 0 * qy - 0 * qz
    new_quat = [nx, ny, nz, nw]
    return new_pos, new_quat
