# DCC Bridge

Author camera paths in 3ds Max or Blender against a Splatpipe splat scene, send them back to Splatpipe.

There are two delivery tiers — pick whichever fits:

| Tier | UX | Requires | Best for |
|---|---|---|---|
| **Tier 1 — Claude + MCP** | Open a Claude Code session, paste a prompt; Claude drives Max / Blender via MCP and POSTs the camera back. | This project's `.mcp.json` includes `3dsmax-mcp` and (for Blender) the community [`blender-mcp`](https://github.com/ahujasid/blender-mcp). | Power users, scripting, ad-hoc shots. |
| **Tier 2 — In-DCC plugin** | Toolbar button in Max (`splatpipe_bridge.mzp`) or sidebar panel in Blender (`splatpipe_bridge.zip`): **Pull splat from Splatpipe** and **Send camera to Splatpipe**. | Install the plugin once; nothing else. | Repeated authoring, polished UX. |

Both tiers talk to the **same three HTTP endpoints** on `splatpipe web`:

| Endpoint | Purpose |
|---|---|
| `GET  /projects/{p}/dcc/manifest` | Project metadata + URLs (existing paths, available LODs, COLMAP detection, default fps + frame range). |
| `GET  /projects/{p}/dcc/splat.ply` | Streams a reviewed PLY for the DCC viewport (Range-capable). `?lod=N` to pick a specific LOD. |
| `POST /projects/{p}/dcc/import-camera` | Accepts JSON or `.glb` upload; appends a new entry to `scene_config.camera_paths`. |

---

## Coordinate-system contract — the **Stand-Up Parent**

This is the part that bites if you wing it. Read once, then forget.

**Where Splatpipe stores coords.** Both viewers (PlayCanvas + Spark) apply a **180°-X rotation to the splat** at render time (PlayCanvas: `splatEntity.setLocalEulerAngles(180, 0, 0)`; Spark: `splat.quaternion.setFromEuler(new THREE.Euler(Math.PI, 0, 0))`). This undoes the **COLMAP Y-down** convention that most Gaussian-splat trainers leave in the PLY. Annotations and recorded camera-paths are stored in this **PlayCanvas-displayed frame** (Y-up).

**The DCC problem.** Max and Blender are **Z-up**. If you load the PLY in either of them and animate a camera, the camera's pose is in DCC world coordinates, not in PlayCanvas-displayed frame.

**The fix.** The bridge wraps the splat in **two nested empties**:

```
splatpipe_outer        (rotation R_outer = 180° X — undoes COLMAP Y-down)
  └─ splatpipe_inner   (rotation R_inner =  90° X — Z-up to Y-up conversion)
       └─ splat        (PLY data; identity local rotation)
```

Net rotation = `R_outer ∘ R_inner` = `180°X ∘ 90°X` = **270°X** (i.e. **−90°X**). With this in place, the user sees a right-side-up splat in their DCC's natural Z-up world.

**On export, compose the camera against the inner empty's inverse AND a 180°-X flip:**

```python
cam_in_pc_displayed = R_180X @ inv(inner.matrix_world) @ cam.matrix_world   # column-vec (Blender)
```

In MaxScript row-vec convention the equivalent is:

```maxscript
cam_in_pc_displayed = cam.transform * inverse(inner.transform) * rotateXMatrix(180)
```

Why the extra `R_180X`? `inv(inner.matrix_world)` only takes a DCC world point into the splat's **local** frame — and the splat's local frame is **PLY-native** (the raw COLMAP-Y-down PLY data). Splatpipe stores annotations + camera-paths in **PC-displayed** frame, which is `R_180X @ PLY-native` (the PC viewer applies that flip at render time). So we need one more R_180X on top of `inv(inner)` to land in the storage frame.

> **Fixed in v0.6.2.** Earlier versions (0.6.1) shipped without the `R_180X` flip — the exported camera ended up mirrored on Y (Z=4 in DCC came back as Y=−4 in PC instead of Y=+4). The Tier-1 Blender round-trip caught the bug.

> **Fixed in v0.6.3 — Max-specific parenting order.** In Max, assigning `inner.parent = outer` *preserves the world transform*, so setting `inner.rotation = +90°X` *before* parenting leaves `inner.world = R_+90X` (only one rotation, not the documented composed `R_-90X`). The splat then appears upside-down AND the export math is off. The Max plugin now sets `inner.parent = outer` **first**, then `inner.rotation = (eulerangles 90 0 0)` — which Max interprets in local coordsys after parenting, yielding the correct `inner.world = R_-90X`. Blender is unaffected: it composes `matrix_world = parent @ local` natively, so order doesn't matter there. Caught via 3dsmax-mcp probe during the Tier-1 round-trip test.

**Equivalent shorthand for THIS specific empty configuration only:** since outer is `R_180X` and inner.matrix_world ends up = `R_180X @ R_+90X = R_-90X`, you can also write `cam_in_pc = inner.matrix_world @ cam.matrix_world` (Blender) — but that's a coincidence of the specific rotations chosen. The explicit `R_180X @ inv(inner)` form is portable to any future restructuring of the empty hierarchy.

The bridge sends this in the request payload as `coord_frame: "playcanvas_displayed"`. The importer writes it as-is (no second flip).

If you instead send `coord_frame: "ply_native"`, the importer applies the 180°-X flip on the way in. That's the path generic glTF imports take (because Blender's glTF exporter handles its own Z-up→Y-up conversion, which lands the camera in PLY-native frame).

### Worked example

User places camera at DCC world `(0, 0, 5)` — 5 units above the splat in Z-up.

```
inv(R_+90X) ∘ (0, 0, 5) = (0, 5, 0)   # 5 units above the splat in Y-up
```

Sent as `pos: [0, 5, 0]`, `coord_frame: "playcanvas_displayed"`. Splatpipe stores it as-is. Both viewers play it back as "camera 5m above splat origin", which matches what the user authored. ✓

### Sanity check before you trust the bridge

1. Place an annotation at a known splat feature (e.g. a corner).
2. Pull the splat into the DCC via the bridge.
3. Confirm the annotation visually overlaps the splat feature.
4. Place a camera at that same DCC location, send it back.
5. Confirm the recorded keyframe `pos` matches `annotation.pos` to ≤ 0.01 unit.

---

## Tier 1 — Claude + MCP

In the Splatpipe scene editor, the **Author camera in Max/Blender via Claude** button reveals a copyable prompt template:

```
Author a camera path in <DCC> for Splatpipe project <project_url>.
Endpoints: <project_url>/dcc/manifest, /splat.ply, /import-camera.
Use the Stand-Up Parent contract from docs/dcc-bridge.md.
```

Paste into a Claude Code session. Claude:

1. `WebFetch`es the manifest, downloads `splat.ply` (preview LOD) to a temp path.
2. Calls `mcp__3dsmax-mcp__create_object` (V-Ray `VRayGaussiansGeom` pointing at the PLY) and wraps it in two empty parents with the Stand-Up Parent rotations above.
3. Creates a target camera; sets the frame range from the manifest.
4. Tells you "Animate the camera now; tell me when done."
5. On your cue: extracts cam keyframes (PRS sub-controllers + FOV) via `mcp__3dsmax-mcp__inspect_controller`, samples at fixed frame steps, composes against `inv(splatpipe_inner.matrix_world)`.
6. POSTs the JSON to `/dcc/import-camera`.

For Blender: same flow via [`blender-mcp`](https://github.com/ahujasid/blender-mcp). Add it to your `.mcp.json`:

```json
{
  "mcpServers": {
    "blender-mcp": {
      "command": "uvx",
      "args": ["blender-mcp"]
    }
  }
}
```

### Prerequisites

- Splatpipe is running locally (`splatpipe web`).
- The target project has a successfully-trained `04_review/lod0_reviewed.ply`.
- 3ds Max is open with V-Ray 7+ and the `3dsmax-mcp` server visible to Claude.
- For Blender: Blender is open with `blender-mcp` connected.

---

## Tier 2 — In-DCC plugin (no Claude needed)

Single-click round trip from inside the DCC. Both plugins live in `tools/dcc-bridge/`.

### 3ds Max — `splatpipe_bridge.mzp`

Drag-drop install. Adds a "Splatpipe" toolbar button → small dialog with:

- **Pull splat from Splatpipe** — paste a project URL, click Pull. Loads the preview PLY into a fresh `VRayGaussiansGeom`, wraps it in `splatpipe_outer` + `splatpipe_inner` parents (locked + hidden), creates a default camera, sets the frame range from the manifest.
- **Send camera to Splatpipe** — extracts active camera's PRS controller keys and FOV, composes against `inv(splatpipe_inner.matrix_world)`, POSTs to `/dcc/import-camera`.

Pure-Python via `pymxs`; HTTP via `urllib.request`. No extra deps.

### Blender — `splatpipe_bridge.zip`

Edit → Preferences → Add-ons → Install. Adds a "Splatpipe" sidebar panel (View tab) in the 3D Viewport with the same two buttons.

PLY preview uses `bpy.ops.wm.ply_import` (Blender 4.0+) — points only. For full Gaussian preview install the optional [3DGS Render addon](https://github.com/ReshotAI/gaussian-splatting-blender-addon).

Camera extraction: per-frame `bpy.context.scene.frame_set(f)` + `cam.matrix_world` + `cam.data.angle`. HTTP via `urllib` (no `requests` to avoid forcing pip installs in Blender's bundled Python).

---

## Wire formats

### `GET /dcc/manifest`

```json
{
  "project_name": "Gutsmutstrasse",
  "project_path": "H:\\001_ProjectCache\\...",
  "splat_full_url": "/projects/{p}/dcc/splat.ply?lod=0",
  "splat_preview_url": "/projects/{p}/dcc/splat.ply?lod=N",
  "available_lods": [{"lod_index": 0, "name": "lod0", "size_bytes": 706480352}],
  "has_colmap_source": false,
  "frame_range": {"start": 1, "end": 240},
  "fps": 24,
  "coord_frame_contract": "playcanvas_displayed",
  "existing_paths": [{"id": "p_57a8c62e71", "name": "Path 1", "keyframe_count": 3}],
  "default_path_id": null,
  "import_camera_url": "/projects/{p}/dcc/import-camera"
}
```

### `POST /dcc/import-camera` (native JSON)

```json
{
  "name": "Tour 1",
  "fps": 24,
  "coord_frame": "playcanvas_displayed",
  "smoothness": 1.0,
  "play_speed": 1.0,
  "loop": false,
  "frames": [
    {"frame": 0,   "pos": [0, 2, -10], "quat": [0, 0, 0, 1], "fov": 60},
    {"frame": 24,  "pos": [5, 2, -5],  "quat": [0, 0, 0, 1], "fov": 75},
    {"frame": 48,  "pos": [10, 2, 0],  "quat": [0, 0, 0, 1], "fov": 90}
  ]
}
```

Response:

```json
{
  "ok": true,
  "id": "p_xxx",
  "name": "Tour 1",
  "keyframe_count": 3,
  "coord_frame_received": "playcanvas_displayed"
}
```

### `POST /dcc/import-camera` (multipart .glb)

Field name `file`. Falls through to the Phase A glTF importer with `flip_180_x=True` — used for ad-hoc Blender→glTF exports that bypass the bridge.

---

## Verification checklist

After implementing or installing the plugin, run through:

1. `curl /dcc/manifest` returns 200 with reasonable project info.
2. `curl -H "Range: bytes=0-1023" /dcc/splat.ply` returns 206 Partial Content.
3. `curl -X POST -d '{"name":"...","fps":24,"frames":[...]}' /dcc/import-camera` returns `{"ok": true, "id": "p_..."}`.
4. The Spark / PC viewer's path HUD shows the new path in its dropdown.
5. Pressing Play tweens the camera through the recorded keyframes.
6. **Coord sanity check** (see above): annotation at known position → matches in DCC viewport → camera placed there → recorded keyframe equals the annotation pos.
