# Splatpipe DCC Bridge

Author camera paths in 3ds Max or Blender against a Splatpipe splat scene, send them back as a new path.

See **`docs/dcc-bridge.md`** at the repo root for the full design (HTTP endpoints, the Stand-Up Parent coordinate-system contract, the Tier 1 Claude+MCP workflow, and the wire formats).

## What's in this directory

```
tools/dcc-bridge/
├── README.md                          # this file
├── max/
│   └── splatpipe_bridge.py            # 3ds Max plugin (pymxs + tkinter dialog)
└── blender/
    └── __init__.py                    # Blender addon (bl_info + Operators + Sidebar Panel)
```

Both plugins are self-contained Python — no third-party packages. They speak HTTP directly to your local `splatpipe web`'s DCC bridge endpoints (`/projects/{p}/dcc/{manifest,splat.ply,import-camera}`).

## Build distribution archives (one-liner)

```bash
cd tools/dcc-bridge && python build.py
# → splatpipe_bridge.zip  (Blender)
# → splatpipe_bridge.mzp  (3ds Max)
```

Then install from the built file (below). Both archives are ~5 KB and pure stdlib — no build dependencies.

## Install — 3ds Max

Requires:
- 3ds Max 2023+ (for the bundled Python 3 + pymxs)
- V-Ray 7+ (for the `VRayGaussiansGeom` node — Gaussian splat support)
- `splatpipe web` running locally

**Option A — drag-drop installer (recommended):** drag `splatpipe_bridge.mzp` into a 3ds Max viewport. It copies the script into your user scripts folder, registers the *Splatpipe Bridge* macro, and opens the dialog. Pin the macro to a toolbar via Customize → Toolbars → Category "Splatpipe".

**Option B — manual:**

1. Copy `max/splatpipe_bridge.py` somewhere on Max's Python path. The simplest:
   - Place it in `%LOCALAPPDATA%\Autodesk\3dsMax\<version>\ENU\scripts\python\`
   - Or run via Scripting → Run Script and pick the file directly
2. To get a permanent toolbar button, run once via the script editor:
   ```python
   import splatpipe_bridge
   splatpipe_bridge.register_max_macro()
   ```
   Then Customize → Toolbars → Category "Splatpipe" → drag *Splatpipe Bridge* to your toolbar.

To launch on demand:

```python
import splatpipe_bridge
splatpipe_bridge.open_dialog()
```

## Install — Blender

Requires:
- Blender 4.0+
- `splatpipe web` running locally

1. Build `splatpipe_bridge.zip` (see above), or use a prebuilt one from a release.
2. In Blender: Edit → Preferences → Add-ons → Install... → pick `splatpipe_bridge.zip` → enable **Splatpipe Bridge**.
3. Open the 3D Viewport sidebar (`N`) → **Splatpipe** tab.

Optional: install the [3DGS Render addon](https://github.com/ReshotAI/gaussian-splatting-blender-addon) for full Gaussian preview (the bundled PLY importer shows points only).

## Usage (both DCCs)

1. **Paste your Splatpipe project URL** — e.g. `http://localhost:8000/projects/H:/.../my_project`. Bridge fetches `/dcc/manifest` to discover the splat URL + frame range.
2. **Click *Pull splat*** — downloads the preview-LOD PLY, sets up two nested empties (`splatpipe_outer` 180°-X + `splatpipe_inner` +90°-X), creates a default `splatpipe_cam`, sets the scene frame range.
3. **Animate `splatpipe_cam`** — your normal DCC workflow. Don't move or unparent the empties — the bridge composes against `inner.matrix_world.inverted()` on send, and that math relies on them.
4. **Click *Send camera*** — samples each frame, composes into PlayCanvas-displayed frame, POSTs to `/dcc/import-camera`. The new path appears in Splatpipe's scene editor (Paths tab) immediately and in the assembled viewer's path HUD on next assemble.

## Coord-system gotcha

The two empties **must** stay at their original rotations (`splatpipe_outer` = 180°-X world, `splatpipe_inner` = +90°-X *in local coordsys* — net `inner.world` = R_-90X). The Send step computes:

```
cam_in_pc_displayed = R_180X @ inv(splatpipe_inner.matrix_world) @ cam.matrix_world      # column-vec (Blender)
cam_in_pc_displayed = cam.transform * inverse(inner.transform) * rotateXMatrix(180)      # row-vec (MaxScript)
```

Why the trailing `R_180X`: `inv(inner)` only takes a DCC point into the splat's *local* frame (PLY-native, Y-down). Splatpipe stores camera-paths in PC-displayed (Y-up) frame, which is `R_180X @ PLY-native`. See `docs/dcc-bridge.md` for the full derivation and worked example.

If you accidentally reset the empties, the camera ends up in the wrong frame and the playback in Splatpipe's viewers will be visibly skewed. Re-pull to reset them.

See `docs/dcc-bridge.md` "Stand-Up Parent" for why this works and how to verify it (annotation-at-known-position sanity check).

## Tier 1 — alternative without installing anything

If you'd rather not install plugins, the **Author in Max / Blender via Claude** button in Splatpipe's scene editor opens a copyable prompt for Claude Code. With the `3dsmax-mcp` (and optionally `blender-mcp`) MCP server in your config, Claude can drive the same workflow end-to-end. See `docs/dcc-bridge.md` Tier 1.
