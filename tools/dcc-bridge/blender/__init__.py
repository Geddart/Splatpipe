"""Splatpipe Bridge for Blender — author camera paths against a splat.

Adds a "Splatpipe" sidebar panel in the 3D Viewport with two operators:

  * **Pull splat** — paste a project URL, click Pull. Downloads the
    preview-LOD PLY, imports it via ``bpy.ops.wm.ply_import`` (Blender 4.0+),
    wraps it in two nested empties (outer 180°-X + inner +90°-X — see
    ``setup_stand_up_parent`` for the math), creates a default camera, and
    sets the scene frame range from the manifest.

  * **Send camera** — extracts the active camera's pose every frame,
    composes against ``splatpipe_inner.matrix_world.inverted()`` to land
    in PlayCanvas-displayed frame, and POSTs the result to
    ``/dcc/import-camera``.

Install: zip the parent ``blender`` directory and use Blender's
Edit → Preferences → Add-ons → Install. Activate "Splatpipe Bridge".

Notes
-----
- Stock PLY import shows points only (not Gaussians). For full Gaussian
  preview, install the optional `3DGS Render addon
  <https://github.com/ReshotAI/gaussian-splatting-blender-addon>`_.
- HTTP via stdlib ``urllib`` — no extra pip installs in Blender's bundled
  Python.
- See ``docs/dcc-bridge.md`` in the Splatpipe repo for the Stand-Up Parent
  coord-system contract.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
import urllib.parse
import urllib.request
from typing import Any

import bpy
from mathutils import Euler, Matrix, Quaternion, Vector


bl_info = {
    "name": "Splatpipe Bridge",
    "description": "Pull a Splatpipe project's splat into Blender, animate a camera, send it back.",
    "author": "Splatpipe",
    "version": (0, 6, 0),
    "blender": (4, 0, 0),
    "location": "View3D > Sidebar > Splatpipe",
    "category": "Import-Export",
}


OUTER_NAME = "splatpipe_outer"
INNER_NAME = "splatpipe_inner"
SPLAT_OBJ_NAME = "splatpipe_splat"
CAM_OBJ_NAME = "splatpipe_cam"


# ---- Properties on the scene ---------------------------------------------


class SplatpipeProps(bpy.types.PropertyGroup):
    project_url: bpy.props.StringProperty(
        name="Project URL",
        description="Splatpipe project URL, e.g. http://localhost:8000/projects/<path>",
        default="http://localhost:8000/projects/",
    )
    path_name: bpy.props.StringProperty(
        name="Path name",
        description="Name for the camera path that will be created in Splatpipe",
        default="Blender DCC Path",
    )


# ---- HTTP helpers --------------------------------------------------------


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


# ---- Stand-Up Parent -----------------------------------------------------


def setup_stand_up_parent(splat_obj: bpy.types.Object) -> tuple[bpy.types.Object, bpy.types.Object]:
    """Wrap `splat_obj` in two empties so it appears upright in Blender's Z-up world.

    Outer empty:  rotation 180° about world X — undoes COLMAP Y-down.
    Inner empty:  rotation +90° about world X — converts Y-up to Z-up.
    Net = 270° X = -90° X.

    Returns (outer, inner).
    """
    # Idempotent: nuke any prior bridge nodes.
    for name in (OUTER_NAME, INNER_NAME):
        existing = bpy.data.objects.get(name)
        if existing is not None:
            bpy.data.objects.remove(existing, do_unlink=True)

    coll = bpy.context.scene.collection
    outer = bpy.data.objects.new(OUTER_NAME, None)
    outer.empty_display_size = 0.5
    outer.rotation_euler = Euler((math.pi, 0.0, 0.0), "XYZ")
    coll.objects.link(outer)

    inner = bpy.data.objects.new(INNER_NAME, None)
    inner.empty_display_size = 0.4
    inner.rotation_euler = Euler((math.pi / 2, 0.0, 0.0), "XYZ")
    inner.parent = outer
    coll.objects.link(inner)

    splat_obj.parent = inner
    splat_obj.matrix_local = Matrix.Identity(4)
    return outer, inner


# ---- Operators -----------------------------------------------------------


class SPLATPIPE_OT_pull_splat(bpy.types.Operator):
    bl_idname = "splatpipe.pull_splat"
    bl_label = "Pull splat from Splatpipe"
    bl_description = "Download the project's preview PLY and set up a Stand-Up Parent rig"

    def execute(self, context):
        props = context.scene.splatpipe_bridge
        url = props.project_url.strip().rstrip("/")
        if not url:
            self.report({"ERROR"}, "Project URL is empty")
            return {"CANCELLED"}

        try:
            manifest = http_get_json(f"{url}/dcc/manifest")
        except Exception as e:
            self.report({"ERROR"}, f"Manifest fetch failed: {e}")
            return {"CANCELLED"}

        ply_url = manifest.get("splat_preview_url") or manifest.get("splat_full_url")
        if not ply_url:
            self.report({"ERROR"}, "Manifest has no splat URL")
            return {"CANCELLED"}
        if ply_url.startswith("/"):
            parsed = urllib.parse.urlparse(url)
            ply_url = f"{parsed.scheme}://{parsed.netloc}{ply_url}"

        tmp = tempfile.NamedTemporaryFile(suffix=".ply", delete=False)
        tmp.close()
        try:
            http_get_to_file(ply_url, tmp.name)
        except Exception as e:
            os.unlink(tmp.name)
            self.report({"ERROR"}, f"PLY download failed: {e}")
            return {"CANCELLED"}

        # Remove any prior splat object so re-pull is idempotent.
        prior = bpy.data.objects.get(SPLAT_OBJ_NAME)
        if prior is not None:
            bpy.data.objects.remove(prior, do_unlink=True)

        # Blender 4.0+ has wm.ply_import; older versions have import_mesh.ply.
        op = getattr(bpy.ops.wm, "ply_import", None)
        if op is not None:
            op(filepath=tmp.name)
        else:
            bpy.ops.import_mesh.ply(filepath=tmp.name)

        # The newly created mesh object is the active object.
        splat_obj = context.view_layer.objects.active
        if splat_obj is None:
            self.report({"ERROR"}, "PLY imported but no active object found")
            return {"CANCELLED"}
        splat_obj.name = SPLAT_OBJ_NAME

        outer, inner = setup_stand_up_parent(splat_obj)

        # Create / reuse a camera
        cam_obj = bpy.data.objects.get(CAM_OBJ_NAME)
        if cam_obj is None:
            cam_data = bpy.data.cameras.new(CAM_OBJ_NAME)
            cam_obj = bpy.data.objects.new(CAM_OBJ_NAME, cam_data)
            bpy.context.scene.collection.objects.link(cam_obj)
        cam_obj.location = Vector((0.0, -10.0, 5.0))
        cam_obj.rotation_euler = Euler((math.radians(75), 0.0, 0.0), "XYZ")
        cam_obj.data.lens_unit = "FOV"
        cam_obj.data.angle = math.radians(60)
        bpy.context.scene.camera = cam_obj

        fr = manifest.get("frame_range") or {"start": 1, "end": 240}
        bpy.context.scene.frame_start = int(fr.get("start", 1))
        bpy.context.scene.frame_end = int(fr.get("end", 240))
        fps = int(manifest.get("fps", 24))
        bpy.context.scene.render.fps = fps

        self.report(
            {"INFO"},
            f"Splatpipe: loaded '{manifest.get('project_name')}'. "
            f"Animate {CAM_OBJ_NAME}, then click Send camera."
        )
        return {"FINISHED"}


class SPLATPIPE_OT_send_camera(bpy.types.Operator):
    bl_idname = "splatpipe.send_camera"
    bl_label = "Send camera to Splatpipe"
    bl_description = "Sample the active camera each frame, compose against inner-empty inverse, POST to Splatpipe"

    def execute(self, context):
        props = context.scene.splatpipe_bridge
        url = props.project_url.strip().rstrip("/")
        name = props.path_name.strip() or "Blender DCC Path"

        cam_obj = bpy.data.objects.get(CAM_OBJ_NAME) or context.scene.camera
        if cam_obj is None or cam_obj.type != "CAMERA":
            self.report({"ERROR"}, f"No active camera (looked for '{CAM_OBJ_NAME}')")
            return {"CANCELLED"}

        inner = bpy.data.objects.get(INNER_NAME)
        if inner is None:
            self.report({"ERROR"}, f"No '{INNER_NAME}' empty in the scene. Pull a splat first.")
            return {"CANCELLED"}

        scene = context.scene
        fps = float(scene.render.fps)
        f_start = scene.frame_start
        f_end = scene.frame_end

        frames = []
        original_frame = scene.frame_current
        try:
            for f in range(f_start, f_end + 1):
                scene.frame_set(f)
                inner_inv = inner.matrix_world.inverted()
                composed = inner_inv @ cam_obj.matrix_world
                pos = composed.to_translation()
                # Blender quaternions are (w, x, y, z); Splatpipe expects (x, y, z, w)
                q = composed.to_quaternion()
                fov_deg = math.degrees(cam_obj.data.angle)
                frames.append({
                    "frame": f - f_start,
                    "pos": [float(pos.x), float(pos.y), float(pos.z)],
                    "quat": [float(q.x), float(q.y), float(q.z), float(q.w)],
                    "fov": fov_deg,
                })
        finally:
            scene.frame_set(original_frame)

        payload = {
            "name": name,
            "fps": fps,
            "coord_frame": "playcanvas_displayed",
            "smoothness": 1.0,
            "play_speed": 1.0,
            "loop": False,
            "frames": frames,
        }
        try:
            result = http_post_json(f"{url}/dcc/import-camera", payload)
        except Exception as e:
            self.report({"ERROR"}, f"POST failed: {e}")
            return {"CANCELLED"}

        self.report(
            {"INFO"},
            f"Splatpipe: sent {len(frames)} frames → path id {result.get('id')}"
        )
        return {"FINISHED"}


# ---- Sidebar panel -------------------------------------------------------


class SPLATPIPE_PT_main(bpy.types.Panel):
    bl_idname = "SPLATPIPE_PT_main"
    bl_label = "Splatpipe Bridge"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Splatpipe"

    def draw(self, context):
        layout = self.layout
        props = context.scene.splatpipe_bridge

        box = layout.box()
        box.label(text="Project URL")
        box.prop(props, "project_url", text="")
        box.label(text="Path name (for Send)")
        box.prop(props, "path_name", text="")

        layout.separator()
        layout.operator(SPLATPIPE_OT_pull_splat.bl_idname, icon="IMPORT")
        layout.operator(SPLATPIPE_OT_send_camera.bl_idname, icon="EXPORT")

        layout.separator()
        layout.label(text="Stand-Up Parent rig:", icon="EMPTY_AXIS")
        layout.label(text=f"  • {OUTER_NAME}: 180° X")
        layout.label(text=f"  • {INNER_NAME}: +90° X")
        layout.label(text="(see docs/dcc-bridge.md)", icon="INFO")


# ---- Registration --------------------------------------------------------


_classes = (
    SplatpipeProps,
    SPLATPIPE_OT_pull_splat,
    SPLATPIPE_OT_send_camera,
    SPLATPIPE_PT_main,
)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.splatpipe_bridge = bpy.props.PointerProperty(type=SplatpipeProps)


def unregister():
    del bpy.types.Scene.splatpipe_bridge
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
