# Plan: PlayCanvas Viewer Camera Constraints & Collision

## Context

The Splatpipe viewer (`src/splatpipe/web/static/viewer.html`) uses PlayCanvas `CameraControls` with zero constraints — the camera can flip upside down, zoom to infinity, fly through the ground, and get lost in empty space. For drone photogrammetry scenes, this makes the viewer disorienting. We need per-project configurable camera limits and, eventually, collision against a rough mesh exported from Reality Capture.

## Scope: Two Phases

**Phase 1 (this PR):** Camera constraints — pitch, zoom, ground height, bounds. Per-project config in `state.json`, UI in the dashboard, viewer reads config from a JSON file.

**Phase 2 (future PR):** Collision mesh — load a GLB from Reality Capture as an invisible Ammo.js collision body, raycast each frame to prevent camera from clipping through geometry. Requires self-hosting Ammo.js WASM (no ESM CDN exists). Outlined at the bottom for future reference.

---

## Phase 1: Camera Constraints

### What CameraControls Already Supports (no custom code)

| Property | Type | Default | Our Use |
|----------|------|---------|---------|
| `pitchRange` | Vec2 | (-360, 360) | Limit to (-89, 89) to prevent flip |
| `zoomRange` | Vec2 | (0.01, 0) | Limit zoom distance from focus |

### What Needs Custom Code

- **Ground plane collision** — per-frame Y-minimum clamp
- **Bounding box** — per-frame XYZ clamp to prevent flying away

### Step 1: Add `camera_constraints` to Project model

**File:** `src/splatpipe/core/project.py`

Add property + setter following the same pattern as `lod_distances`:

```python
DEFAULT_CAMERA_CONSTRAINTS = {
    "pitch_min": -89,
    "pitch_max": 89,
    "zoom_min": 1,
    "zoom_max": 200,
    "ground_height": 0.3,
    "bounds_radius": 150,
}

@property
def camera_constraints(self) -> dict:
    defaults = dict(self.DEFAULT_CAMERA_CONSTRAINTS)
    saved = self.state.get("camera_constraints", {})
    defaults.update(saved)
    return defaults

def set_camera_constraints(self, constraints: dict) -> None:
    self.state["camera_constraints"] = constraints
    self._save_state()
```

### Step 2: Write `viewer-config.json` during assembly

**File:** `src/splatpipe/steps/lod_assembly.py`

At the end of the assembly step (after writing `lod-meta.json`), also write a `viewer-config.json` to the output directory:

```json
{
  "camera": {
    "pitch_min": -89,
    "pitch_max": 89,
    "zoom_min": 1,
    "zoom_max": 200,
    "ground_height": 0.3,
    "bounds_radius": 150
  }
}
```

This is read from `project.camera_constraints`. The viewer loads this file alongside `lod-meta.json`.

### Step 3: Update viewer.html to load and apply config

**File:** `src/splatpipe/web/static/viewer.html`

After loading `lod-meta.json`, fetch `viewer-config.json` (with fallback to defaults if not found):

```javascript
// Load config (non-blocking, fallback to defaults)
let viewerConfig = { camera: { pitch_min: -89, pitch_max: 89, zoom_min: 1, zoom_max: 200, ground_height: 0.3, bounds_radius: 150 } };
try {
    const resp = await fetch('viewer-config.json');
    if (resp.ok) viewerConfig = await resp.json();
} catch (e) { /* use defaults */ }

const cam = viewerConfig.camera;
```

Then apply constraints:

```javascript
// Built-in CameraControls constraints
cc.pitchRange = new pc.Vec2(cam.pitch_min, cam.pitch_max);
cc.zoomRange = new pc.Vec2(cam.zoom_min, cam.zoom_max);

// Per-frame ground + bounds clamp
app.on('update', () => {
    const pos = camera.getLocalPosition();
    const clamped = new pc.Vec3(
        pc.math.clamp(pos.x, -cam.bounds_radius, cam.bounds_radius),
        Math.max(pos.y, cam.ground_height),
        pc.math.clamp(pos.z, -cam.bounds_radius, cam.bounds_radius)
    );
    if (!pos.equals(clamped)) {
        camera.setLocalPosition(clamped);
    }
});
```

### Step 4: Add UI for camera constraints in dashboard

**File:** `src/splatpipe/web/templates/project_detail.html`

Add a "Camera Constraints" section in the Assemble step settings (next to the existing LOD Distances UI). Form fields for:
- Pitch min/max (degrees)
- Zoom min/max (meters)
- Ground height (meters)
- Bounds radius (meters)

Auto-submit on change, same pattern as LOD distances.

### Step 5: Add route handler for updating camera constraints

**File:** `src/splatpipe/web/routes/projects.py`

New POST endpoint:
```
POST /projects/{project_path}/update-camera-constraints
```

Reads form fields, calls `project.set_camera_constraints(...)`, returns toast.

### Step 6: Add `splatpipe serve` support

**File:** `src/splatpipe/cli/serve_cmd.py`

The `serve` command serves the output folder statically. It already picks up `lod-meta.json`. Since `viewer-config.json` will be in the same output directory, it's automatically served — no changes needed unless the serve command generates its own viewer.html (check if it does).

### Step 7: Tests

**File:** `tests/test_project_extended.py`
- Test `camera_constraints` property returns defaults when unset
- Test `set_camera_constraints` round-trips through state.json
- Test partial override (set only `ground_height`, others stay default)

**File:** `tests/test_lod_assembly.py`
- Test that assembly writes `viewer-config.json` to output dir
- Test that it contains the project's camera constraints

**File:** `tests/test_web_routes.py`
- Test `POST /projects/.../update-camera-constraints` endpoint

---

## Files Modified

| File | Change |
|------|--------|
| `src/splatpipe/core/project.py` | Add `camera_constraints` property + setter + defaults |
| `src/splatpipe/steps/lod_assembly.py` | Write `viewer-config.json` during assembly |
| `src/splatpipe/web/static/viewer.html` | Load config, apply pitch/zoom/ground/bounds constraints |
| `src/splatpipe/web/templates/project_detail.html` | Camera constraints UI form |
| `src/splatpipe/web/routes/projects.py` | POST endpoint for camera constraints |
| `src/splatpipe/cli/serve_cmd.py` | Check if needs viewer-config.json support |
| `tests/test_project_extended.py` | Project model tests |
| `tests/test_lod_assembly.py` | Assembly output tests |
| `tests/test_web_routes.py` | Route tests |
| `CHANGELOG.md` | Add entries under [Unreleased] |

## Verification

1. Run `pytest tests/ -v` — all tests pass including new ones
2. Open dashboard → project detail → Assemble settings → verify Camera Constraints UI appears
3. Change values → verify they persist in `state.json`
4. Run assemble step → verify `viewer-config.json` is written to `05_output/`
5. Open viewer → verify pitch stops at ±89°, zoom is limited, camera can't go below ground, can't fly past bounds
6. `splatpipe serve` → verify viewer-config.json is served and constraints work

## CHANGELOG

```markdown
### Added
- Per-project camera constraints (pitch, zoom, ground height, scene bounds)
- Camera constraints UI in project settings
- `viewer-config.json` output during assembly step
- Viewer applies constraints from config (prevents flip, ground clip, flying away)
```

---

## Phase 2 Outline: Collision Mesh (Future PR)

### Approach
1. User exports a rough low-poly mesh from Reality Capture as GLB
2. User places the GLB in the project folder (e.g., `collision.glb` in project root or `05_output/`)
3. Assembly step copies it to output alongside `lod-meta.json`
4. Viewer loads Ammo.js WASM → initializes physics → loads GLB as invisible mesh collision
5. Each frame: raycast from orbit focus point toward camera position; if hit, clamp camera distance

### Technical Requirements
- **Ammo.js**: Must be self-hosted (no ESM CDN). Host `ammo.wasm.js` + `ammo.wasm.wasm` in static dir
- **Component systems**: Add `pc.RigidBodyComponentSystem`, `pc.CollisionComponentSystem` to app init
- **Collision entity**: `entity.addComponent('collision', { type: 'mesh', asset: ... })` + `entity.addComponent('rigidbody', { type: 'static' })`
- **No render component** on collision entity → invisible
- **Raycast**: `app.systems.rigidbody.raycastFirst(focusPoint, cameraPos)` each frame
- **Mesh type limitation**: Must be `rigidbody.type: 'static'` (Ammo.js limitation for mesh colliders)
- Physics runs independently of WebGPU/WebGL2 — no compatibility issues

### New state.json field
```json
"collision_mesh": "collision.glb"
```

### Complexity
Significant — Ammo.js WASM loading, self-hosting, mesh alignment with splat coordinate system, performance tuning for high-poly meshes. Recommend keeping the collision mesh low-poly (Reality Capture can export simplified meshes).
