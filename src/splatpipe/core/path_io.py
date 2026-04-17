"""Camera path data model + import/export helpers.

A camera path is a list of keyframes the viewer interpolates between.
The schema is renderer-neutral: PlayCanvas and Spark viewers play the same
JSON identically. The same shape is the wire format for the DCC bridge
import endpoint and for glTF / COLMAP imports.

Coordinate frame: all positions/quaternions are in **PlayCanvas-displayed
frame** (Y-up, post-180°-X flip applied by the viewer to the splat). Importers
that read PLY-native sources (glTF, COLMAP) apply the flip on the way in.
The DCC bridge composes against its stand-up parent, so its payloads are
already in PC-displayed frame.
"""

from __future__ import annotations

import uuid
from typing import Callable, Iterable, Literal, TypedDict


# ---- schema ----------------------------------------------------------------


class KeyframeDict(TypedDict, total=False):
    t: float                          # seconds from path start
    pos: list[float]                  # [x, y, z] in PC-displayed frame
    look_at: list[float]              # [x, y, z] target — OR provide quat
    quat: list[float]                 # [x, y, z, w] — OR provide look_at
    fov: float                        # vertical FOV degrees
    easing_out: str                   # "linear" | "easeInOutCubic" | ...
    hold_s: float                     # pause duration after this keyframe
    annotation_id: str | None         # highlight this annotation while passing


class PathDict(TypedDict, total=False):
    id: str
    name: str
    loop: bool
    interpolation: Literal["catmull", "linear", "bezier"]
    smoothness: float                 # 0.0 = linear (segments), 1.0 = full Catmull-Rom (default)
    play_speed: float                 # playback rate multiplier; 0.5 = half-speed, 2.0 = double-speed
    keyframes: list[KeyframeDict]


DEFAULT_EASING = "easeInOutCubic"
DEFAULT_INTERPOLATION: Literal["catmull"] = "catmull"
DEFAULT_SMOOTHNESS = 1.0
DEFAULT_PLAY_SPEED = 1.0


def new_path(
    name: str,
    *,
    keyframes: list[KeyframeDict] | None = None,
    loop: bool = False,
    interpolation: Literal["catmull", "linear", "bezier"] = DEFAULT_INTERPOLATION,
    smoothness: float = DEFAULT_SMOOTHNESS,
    play_speed: float = DEFAULT_PLAY_SPEED,
) -> PathDict:
    """Construct a fresh PathDict with a unique id."""
    return {
        "id": _new_id(),
        "name": name,
        "loop": loop,
        "interpolation": interpolation,
        "smoothness": smoothness,
        "play_speed": play_speed,
        "keyframes": list(keyframes or []),
    }


def _new_id() -> str:
    # Short, sortable, unlikely to collide. uuid4 hex prefix is plenty.
    return "p_" + uuid.uuid4().hex[:10]


# ---- mutate helper (D2: list-aware CRUD around set_scene_config_section) ---


def mutate_paths(project, fn: Callable[[list[PathDict]], list[PathDict]]) -> list[PathDict]:
    """Load camera_paths, apply fn(list)→list, persist via the merge-aware
    set_scene_config_section.

    set_scene_config_section MERGES dicts but REPLACES non-dict values
    (Splatpipe 0.5.0). camera_paths is a list, so any partial write would
    overwrite siblings — wrap every CRUD in this helper to enforce read /
    mutate / write atomically.

    Returns the new list (post-fn).
    """
    paths: list[PathDict] = list(project.scene_config.get("camera_paths") or [])
    new_paths = list(fn(paths))
    project.set_scene_config_section("camera_paths", new_paths)
    return new_paths


# ---- common ops on the in-memory list -------------------------------------


def find_path(paths: Iterable[PathDict], path_id: str) -> PathDict | None:
    for p in paths:
        if p.get("id") == path_id:
            return p
    return None


def upsert_path(paths: list[PathDict], path: PathDict) -> list[PathDict]:
    for i, existing in enumerate(paths):
        if existing.get("id") == path.get("id"):
            paths[i] = path
            return paths
    paths.append(path)
    return paths


def remove_path(paths: list[PathDict], path_id: str) -> list[PathDict]:
    return [p for p in paths if p.get("id") != path_id]


# ---- glTF importer (A4) ----------------------------------------------------


def from_gltf(
    path,
    *,
    name: str = "",
    sample_hz: float | None = None,
    camera_index: int = 0,
    flip_180_x: bool = True,
) -> PathDict:
    """Import a camera animation from a .glb / .gltf file.

    Finds the Nth perspective camera node (default first), walks parent
    transforms, samples translation+rotation tracks. Returns a renderer-neutral
    PathDict in PlayCanvas-displayed frame.

    By default applies a 180°-X flip to bring PLY-native coords (typical when
    the user authored against the splat in PLY-native orientation in Blender)
    into PC-displayed frame. **For DCC bridge round-trips, use the dedicated
    /dcc/import-camera endpoint instead** — it composes against the bridge's
    stand-up parent and sets `flip_180_x=False` to avoid double-flipping.
    """
    import math
    from pathlib import Path as _Path
    import numpy as np
    from pygltflib import GLTF2

    gltf_path = _Path(path)
    gltf = GLTF2().load(str(gltf_path))
    if gltf is None:
        raise ValueError(f"failed to load glTF: {gltf_path}")

    blob = gltf.binary_blob() if gltf_path.suffix.lower() == ".glb" else None

    cam_node_indices = [i for i, n in enumerate(gltf.nodes or []) if n.camera is not None]
    if not cam_node_indices:
        raise ValueError(f"no camera nodes in {gltf_path}")
    if camera_index >= len(cam_node_indices):
        raise IndexError(
            f"camera_index {camera_index} out of range; "
            f"{len(cam_node_indices)} camera(s) in glTF"
        )
    cam_node_idx = cam_node_indices[camera_index]
    cam_obj = gltf.cameras[gltf.nodes[cam_node_idx].camera]
    if cam_obj.type != "perspective":
        raise ValueError(f"only perspective cameras supported; got {cam_obj.type}")
    fov_y_deg = math.degrees(cam_obj.perspective.yfov)

    parents = _build_parent_map(gltf)

    times, translations, rotations = _extract_camera_tracks(
        gltf, blob, cam_node_idx
    )

    if sample_hz is not None and sample_hz > 0 and len(times) > 1:
        times, translations, rotations = _resample_tracks(
            times, translations, rotations, sample_hz
        )

    keyframes: list[KeyframeDict] = []
    flip_pos = np.diag([1.0, -1.0, -1.0]) if flip_180_x else np.eye(3)
    flip_quat = np.array([1.0, 0.0, 0.0, 0.0]) if flip_180_x else None

    for t, trans, rot in zip(times, translations, rotations):
        pos_world, quat_world = _compose_with_parents(
            cam_node_idx, parents, gltf, trans, rot
        )
        pos = (flip_pos @ np.asarray(pos_world)).tolist()
        if flip_quat is not None:
            quat_world = _quat_mul(flip_quat, np.asarray(quat_world)).tolist()
        else:
            quat_world = np.asarray(quat_world).tolist()
        keyframes.append({
            "t": float(t - times[0]),
            "pos": [float(x) for x in pos],
            "quat": [float(x) for x in quat_world],
            "fov": fov_y_deg,
            "easing_out": "linear",
            "hold_s": 0.0,
            "annotation_id": None,
        })

    return new_path(
        name or gltf_path.stem or "Imported Path",
        keyframes=keyframes,
        loop=False,
        interpolation="catmull",
    )


# ---- glTF helpers (private) ------------------------------------------------


def _build_parent_map(gltf) -> dict[int, int]:
    """Return {child_node_index: parent_node_index} for the (default) scene."""
    parents: dict[int, int] = {}
    for parent_idx, node in enumerate(gltf.nodes or []):
        for child_idx in (node.children or []):
            parents[child_idx] = parent_idx
    return parents


def _extract_camera_tracks(gltf, blob, node_idx: int):
    """Return (times, translations[T,3], rotations[T,4 xyzw]) for the node.

    If the node has no animated translation/rotation, falls back to the node's
    static TRS as a single-keyframe path.
    """
    import numpy as np

    trans_sampler = None
    rot_sampler = None
    for anim in gltf.animations or []:
        for ch in anim.channels:
            if ch.target.node != node_idx:
                continue
            sampler = anim.samplers[ch.sampler]
            if ch.target.path == "translation":
                trans_sampler = (anim, sampler)
            elif ch.target.path == "rotation":
                rot_sampler = (anim, sampler)

    if trans_sampler is None and rot_sampler is None:
        node = gltf.nodes[node_idx]
        t0 = np.array(node.translation or [0.0, 0.0, 0.0])
        r0 = np.array(node.rotation or [0.0, 0.0, 0.0, 1.0])
        return np.array([0.0]), t0[None, :], r0[None, :]

    def _read(sampler_pair, value_dim: int):
        anim, sampler = sampler_pair
        times = _read_accessor(gltf, blob, sampler.input)  # (T,)
        values = _read_accessor(gltf, blob, sampler.output)  # (T*value_dim,) or (T, value_dim)
        if sampler.interpolation == "CUBICSPLINE":
            # CUBICSPLINE has [in_tan, value, out_tan] triplets — take values only.
            values = values.reshape(-1, 3, value_dim)[:, 1, :]
        else:
            values = values.reshape(-1, value_dim)
        return times, values

    if trans_sampler:
        t_times, translations = _read(trans_sampler, 3)
    else:
        node = gltf.nodes[node_idx]
        t0 = np.array(node.translation or [0.0, 0.0, 0.0])
        t_times = None
        translations = t0

    if rot_sampler:
        r_times, rotations = _read(rot_sampler, 4)
    else:
        node = gltf.nodes[node_idx]
        r0 = np.array(node.rotation or [0.0, 0.0, 0.0, 1.0])
        r_times = None
        rotations = r0

    # Unify timeline: union of all keyframe times, interpolate the other channel.
    if t_times is None:
        times = r_times
        translations = np.tile(translations, (len(times), 1))
    elif r_times is None:
        times = t_times
        rotations = np.tile(rotations, (len(times), 1))
    else:
        times = np.union1d(t_times, r_times)
        translations = _interp_lerp(times, t_times, translations)
        rotations = _interp_slerp(times, r_times, rotations)

    return times, translations, rotations


def _read_accessor(gltf, blob, accessor_index: int):
    """Read a glTF accessor as a flat numpy array. Supports .glb binary blob and
    embedded base64 data URIs. Does NOT support external .bin files yet."""
    import base64
    import struct
    import numpy as np

    accessor = gltf.accessors[accessor_index]
    bv = gltf.bufferViews[accessor.bufferView]
    buf = gltf.buffers[bv.buffer]

    if blob is not None and bv.buffer == 0:
        data = blob
    elif buf.uri and buf.uri.startswith("data:"):
        _, b64 = buf.uri.split(",", 1)
        data = base64.b64decode(b64)
    elif buf.uri:
        # External .bin sibling file
        from pathlib import Path as _Path
        bin_path = _Path(gltf._gltf2_path).parent / buf.uri  # type: ignore[attr-defined]
        with open(bin_path, "rb") as f:
            data = f.read()
    else:
        raise ValueError(f"buffer {bv.buffer} has no uri and no binary blob")

    offset = (bv.byteOffset or 0) + (accessor.byteOffset or 0)
    component_dtype = {
        5120: np.int8, 5121: np.uint8,
        5122: np.int16, 5123: np.uint16,
        5125: np.uint32, 5126: np.float32,
    }[accessor.componentType]
    type_count = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4,
                  "MAT2": 4, "MAT3": 9, "MAT4": 16}[accessor.type]
    n_elements = accessor.count * type_count
    arr = np.frombuffer(data, dtype=component_dtype, count=n_elements, offset=offset)
    return arr.astype(np.float32)


def _interp_lerp(target_times, source_times, source_values):
    """Linear interpolation per dim. source_values shape (S, D)."""
    import numpy as np
    out = np.empty((len(target_times), source_values.shape[1]), dtype=np.float32)
    for d in range(source_values.shape[1]):
        out[:, d] = np.interp(target_times, source_times, source_values[:, d])
    return out


def _interp_slerp(target_times, source_times, source_quats):
    """Per-segment slerp on quaternions. source_quats shape (S, 4) xyzw."""
    import numpy as np
    out = np.empty((len(target_times), 4), dtype=np.float32)
    for i, t in enumerate(target_times):
        # Find the segment in source_times containing t.
        idx = int(np.searchsorted(source_times, t, side="right")) - 1
        idx = max(0, min(idx, len(source_times) - 2))
        t0, t1 = source_times[idx], source_times[idx + 1]
        u = 0.0 if t1 == t0 else float((t - t0) / (t1 - t0))
        u = max(0.0, min(1.0, u))
        out[i] = _quat_slerp(source_quats[idx], source_quats[idx + 1], u)
    return out


def _quat_slerp(q0, q1, u: float):
    import numpy as np
    q0 = np.asarray(q0, dtype=np.float64)
    q1 = np.asarray(q1, dtype=np.float64)
    dot = float(np.dot(q0, q1))
    if dot < 0.0:
        q1 = -q1
        dot = -dot
    if dot > 0.9995:
        result = q0 + u * (q1 - q0)
        return (result / np.linalg.norm(result)).astype(np.float32)
    theta_0 = np.arccos(np.clip(dot, -1.0, 1.0))
    sin_theta_0 = np.sin(theta_0)
    theta = theta_0 * u
    s0 = np.cos(theta) - dot * np.sin(theta) / sin_theta_0
    s1 = np.sin(theta) / sin_theta_0
    return (s0 * q0 + s1 * q1).astype(np.float32)


def _quat_mul(a, b):
    """Hamilton product, both xyzw."""
    import numpy as np
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return np.array([
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
        aw * bw - ax * bx - ay * by - az * bz,
    ], dtype=np.float32)


def _compose_with_parents(node_idx: int, parents: dict, gltf, trans, rot):
    """Walk parent chain, compose TRS into world translation + rotation.

    Ignores scale. Glb→Spark/PC viewers use position+quat directly.
    """
    import numpy as np

    pos = np.asarray(trans, dtype=np.float64).copy()
    quat = np.asarray(rot, dtype=np.float64).copy()

    cursor = parents.get(node_idx)
    while cursor is not None:
        pnode = gltf.nodes[cursor]
        ptrans = np.array(pnode.translation or [0.0, 0.0, 0.0], dtype=np.float64)
        prot = np.array(pnode.rotation or [0.0, 0.0, 0.0, 1.0], dtype=np.float64)
        # world_pos = parent.translation + parent.rotation * pos
        pos = ptrans + _quat_rotate(prot, pos)
        # world_quat = parent.rotation * quat
        quat = _quat_mul(prot, quat)
        cursor = parents.get(cursor)

    return pos, quat


def _quat_rotate(q, v):
    """Rotate a 3-vector by a quaternion (xyzw)."""
    import numpy as np
    q = np.asarray(q, dtype=np.float64)
    v = np.asarray(v, dtype=np.float64)
    qx, qy, qz, qw = q
    qv = np.array([qx, qy, qz])
    t = 2.0 * np.cross(qv, v)
    return v + qw * t + np.cross(qv, t)


def _resample_tracks(times, translations, rotations, sample_hz: float):
    """Resample to fixed Hz. Slerp for rotations, lerp for translations."""
    import numpy as np
    duration = float(times[-1] - times[0])
    n = max(2, int(np.ceil(duration * sample_hz)) + 1)
    new_times = np.linspace(times[0], times[-1], n)
    new_trans = _interp_lerp(new_times, np.asarray(times), np.asarray(translations))
    new_rots = _interp_slerp(new_times, np.asarray(times), np.asarray(rotations))
    return new_times, new_trans, new_rots


# ---- COLMAP importer (A5) --------------------------------------------------


def from_colmap(
    colmap_dir,
    *,
    name: str = "Capture Path",
    every_nth: int = 1,
    fps: float = 24.0,
) -> PathDict:
    """Import the original capture cameras from COLMAP as a path.

    Reads `cameras.{txt,bin}` + `images.{txt,bin}` from `colmap_dir`. For each
    (or every-Nth) image, derives world-from-camera pose, applies 180°-X flip
    (PLY-native → PC-displayed frame), and emits a keyframe at `i/fps` seconds.

    FOV is computed per image using the referenced camera's intrinsics
    (PINHOLE/SIMPLE_PINHOLE supported; others fall back to `fy`/`f`).

    Raises FileNotFoundError if `colmap_dir` doesn't exist or has no recognised
    COLMAP files (e.g. passthrough-only projects with no `01_colmap_source`).

    Reference: COLMAP image pose convention follows
    https://colmap.github.io/format.html#images-txt — `qvec` is the rotation
    from world to image coordinates (right-handed, +X right, +Y down,
    +Z into image), `tvec` is the translation in the same frame.

    Algorithm follows SuperSplat's `colmap-loader.ts` (PlayCanvas, MIT).
    """
    import math
    from pathlib import Path as _Path
    import numpy as np

    from .. import colmap
    from ..colmap.parsers import (
        detect_colmap_format,
        parse_cameras_txt,
        parse_images_txt,
    )
    from ..colmap.parsers_bin import (
        parse_cameras_bin,
        parse_images_bin,
    )

    colmap_dir = _Path(colmap_dir)
    if not colmap_dir.exists():
        raise FileNotFoundError(
            f"COLMAP source not found at {colmap_dir}. "
            f"Passthrough-only projects (`splatpipe init scene.ply`) have no "
            f"COLMAP data — use `splatpipe path-import` (glTF) or the DCC "
            f"bridge instead."
        )

    fmt = detect_colmap_format(colmap_dir)
    if fmt == "text":
        cameras = list(parse_cameras_txt(colmap_dir / "cameras.txt"))
        images = list(parse_images_txt(colmap_dir / "images.txt"))
    elif fmt == "binary":
        cameras = list(parse_cameras_bin(colmap_dir / "cameras.bin"))
        images = list(parse_images_bin(colmap_dir / "images.bin"))
    else:
        raise FileNotFoundError(
            f"No COLMAP cameras/images files found in {colmap_dir} "
            f"(expected cameras.txt+images.txt OR cameras.bin+images.bin)."
        )

    cam_by_id = {c["camera_id"]: c for c in cameras}
    images_sorted = sorted(images, key=lambda im: im["name"])
    if every_nth > 1:
        images_sorted = images_sorted[::every_nth]

    if not images_sorted:
        raise ValueError(f"No COLMAP images in {colmap_dir}")

    flip_pos = np.diag([1.0, -1.0, -1.0])
    flip_quat = np.array([1.0, 0.0, 0.0, 0.0])  # axis-angle (1,0,0), pi → xyzw

    keyframes: list[KeyframeDict] = []
    for i, im in enumerate(images_sorted):
        # COLMAP stores world→camera rotation+translation. Invert to get camera-in-world.
        q_wc = np.array([im["qx"], im["qy"], im["qz"], im["qw"]], dtype=np.float64)  # xyzw
        t_wc = np.array([im["tx"], im["ty"], im["tz"]], dtype=np.float64)
        R_wc = _quat_to_matrix(q_wc)
        # camera position in world coords
        cam_pos_world = -R_wc.T @ t_wc
        # camera orientation in world coords (rotation matrix), then back to quaternion
        R_cw = R_wc.T
        q_cw = _matrix_to_quat(R_cw)  # xyzw

        # Apply PLY-native → PC-displayed flip
        pos_pc = (flip_pos @ cam_pos_world).tolist()
        quat_pc = _quat_mul(flip_quat, q_cw).tolist()

        cam = cam_by_id.get(im["camera_id"])
        if cam is None:
            fov_y_deg = 60.0
        else:
            fov_y_deg = _colmap_camera_fov_y_deg(cam)

        keyframes.append({
            "t": i / max(0.001, fps),
            "pos": [float(x) for x in pos_pc],
            "quat": [float(x) for x in quat_pc],
            "fov": float(fov_y_deg),
            "easing_out": "linear",
            "hold_s": 0.0,
            "annotation_id": None,
        })

    return new_path(
        name,
        keyframes=keyframes,
        loop=False,
        interpolation="catmull",
    )


def _colmap_camera_fov_y_deg(cam: dict) -> float:
    """Compute vertical FOV in degrees from a COLMAP camera dict.

    Uses fy (or f) divided by image height. Supports PINHOLE,
    SIMPLE_PINHOLE, SIMPLE_RADIAL, RADIAL, OPENCV. Falls back to a
    sensible default if unknown.
    """
    import math
    model = cam.get("model", "")
    params = cam.get("params") or []
    height = cam.get("height", 0)
    if not height or not params:
        return 60.0
    if model == "PINHOLE" and len(params) >= 2:
        fy = params[1]
    elif model in ("SIMPLE_PINHOLE", "SIMPLE_RADIAL", "RADIAL") and params:
        fy = params[0]
    elif model in ("OPENCV", "FULL_OPENCV") and len(params) >= 2:
        fy = params[1]
    else:
        fy = params[0]
    return math.degrees(2.0 * math.atan(height / (2.0 * fy)))


def _quat_to_matrix(q):
    """xyzw quaternion → 3x3 rotation matrix."""
    import numpy as np
    x, y, z, w = q
    xx, yy, zz = x * x, y * y, z * z
    xy, xz, yz = x * y, x * z, y * z
    wx, wy, wz = w * x, w * y, w * z
    return np.array([
        [1 - 2 * (yy + zz),     2 * (xy - wz),     2 * (xz + wy)],
        [    2 * (xy + wz), 1 - 2 * (xx + zz),     2 * (yz - wx)],
        [    2 * (xz - wy),     2 * (yz + wx), 1 - 2 * (xx + yy)],
    ], dtype=np.float64)


def _matrix_to_quat(R):
    """3x3 rotation matrix → xyzw quaternion (Shepperd's method)."""
    import numpy as np
    R = np.asarray(R, dtype=np.float64)
    trace = R[0, 0] + R[1, 1] + R[2, 2]
    if trace > 0:
        s = 0.5 / np.sqrt(trace + 1.0)
        w = 0.25 / s
        x = (R[2, 1] - R[1, 2]) * s
        y = (R[0, 2] - R[2, 0]) * s
        z = (R[1, 0] - R[0, 1]) * s
    elif R[0, 0] > R[1, 1] and R[0, 0] > R[2, 2]:
        s = 2.0 * np.sqrt(1.0 + R[0, 0] - R[1, 1] - R[2, 2])
        w = (R[2, 1] - R[1, 2]) / s
        x = 0.25 * s
        y = (R[0, 1] + R[1, 0]) / s
        z = (R[0, 2] + R[2, 0]) / s
    elif R[1, 1] > R[2, 2]:
        s = 2.0 * np.sqrt(1.0 + R[1, 1] - R[0, 0] - R[2, 2])
        w = (R[0, 2] - R[2, 0]) / s
        x = (R[0, 1] + R[1, 0]) / s
        y = 0.25 * s
        z = (R[1, 2] + R[2, 1]) / s
    else:
        s = 2.0 * np.sqrt(1.0 + R[2, 2] - R[0, 0] - R[1, 1])
        w = (R[1, 0] - R[0, 1]) / s
        x = (R[0, 2] + R[2, 0]) / s
        y = (R[1, 2] + R[2, 1]) / s
        z = 0.25 * s
    return np.array([x, y, z, w], dtype=np.float64)
