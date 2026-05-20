# Splatpipe Editor Architecture — Spec

> Synthesised from 8 parallel research reports (R1-R8) under
> [docs/superpowers/research/2026-05-20-editor-arc/](../research/2026-05-20-editor-arc/).
>
> **User direction (2026-05-20 16:49):** ship a Sequencer-grade interactive
> editor that runs in-viewer across all 8 deployed scenes; persist
> camera-paths + cuts + annotations + audio + panorama backdrop + (post-fx
> only) lighting; eliminate the manual `.kfwork/` deploy detour so
> iterative authoring "feels smooth."
>
> Companion implementation plan:
> [docs/superpowers/plans/2026-05-20-editor-arc.md](../plans/2026-05-20-editor-arc.md).

---

## Spec addenda 2026-05-20 — user authoring feedback round 1

After testing the UX-5 band-aid commit (`491faa8`), the user reported
three timeline-UX gaps via voice 2026-05-20 17:09 (verbatim):

> "It is better, but I can still not scrub the timeline further than it
> looks like one and a half seconds after the last keyframe. Also there
> is no total time setting, which there should be. And the buttons to
> skip between keyframes. Please weave that into the plan you are
> already building."

These three items are folded into the v1 design as additive contracts —
no breaking schema change, no breaking module-contract change:

1. **Timeline total-duration decoupled from last-keyframe** — new
   optional `PathDict.total_duration_s: number | null` schema field.
   See §3.7 + §4.1.
2. **Total-time editor control** — number input + auto toggle in the
   transport row (`_tlBarRow`). See §4.1.
3. **Prev/Next-keyframe skip buttons + hotkeys** — `|◀` / `▶|`
   buttons in `_tlBarRow`; `Ctrl+Left` / `Ctrl+Right` hotkeys (no
   undo entry — navigation, not edit). See §4.1 + §6.5 hotkey table.

All three are CameraPathModule-scope and ship in Phase 1 alongside the
EditHistory contract. They are listed in the plan under §Phase 1 steps.

---

## 0. Goal + non-goals

### Goal — v1 ("cinematic shell complete")

A single in-viewer editor across all 8 deployed scenes that

1. authors camera paths (existing surface, refactored onto the new
   contract);
2. authors annotations (text + 3D position + t_in/t_out);
3. authors clip sequences ("cuts") across multiple cameras (refactor of
   existing `ClipPlayer`);
4. authors audio tracks (positional + global; in/out timing);
5. authors a panorama-backdrop image per scene (LDR JPG only, ≤4K
   equirect; see §5.2);
6. authors post-fx (tonemapping + exposure + backdrop intensity) — NO
   AmbientLight / DirectionalLight / env-map; see §5.3;
7. authors 3D titles (text + position + t_in/t_out);
8. persists everything through the existing `merge_camera_scope` patch
   path (CLI mode default; explicit-save HTTP backend per scene; see §7);
9. supports undo/redo for the whole editor session via a snapshot ring
   buffer (see §6);
10. uses the existing `SceneView` framework
    (`ModeManager`/`OverlayScene`/`InteractionManager`/`HudLayer`) so
    every editor module follows ONE contract.

### Non-goals — explicitly OUT of v1

- **HDR / IBL panorama** — JPG only in v1; EXR/HDR deferred.
- **AmbientLight / DirectionalLight / scene.environment as editor knobs**
  — Gaussian splats are pre-lit (SH baked at training); THREE scene
  lights have ZERO effect on splat pixels (R7). Don't expose them.
- **Per-light editor (color/position pickers)** — same reason.
- **Auto-save with debounce** — explicit-save only in MVP (R4 wins; see
  §7.3). The `onCfgChange()` hook stays in the module contract as a
  future extension point but does NOT trigger network I/O.
- **Real-time multi-user collaboration** — last-writer-wins suffices for
  the "tab in author mode vs CLI relay" coexistence (R1 pattern 8).
- **Persistent undo across reload** — undo is ephemeral (R8 §3).
- **Curve editor / property graph view** — dope-sheet only in v1 (R1
  pattern 9).
- **Cloudflare Worker backend rollout** — `php` is the locked first
  backend (geddart.de); Cloudflare adapter exists as a stub
  (`save_backends/cloudflare.py`) but is not rolled out in this spec.

---

## 1. Foundational principles (10 patterns, scoped to splatpipe)

R1 distilled 10 cross-tool UX patterns. Below: which apply, how they map
into splatpipe's scaffold, and the priority for v1.

| # | Pattern | Source | v1 scope |
|---|---|---|---|
| 1 | Master playhead + sub-sequences fold into it | UE Sequencer Master/Shots | **In** — one master playhead per scene (`window.__playhead`); per-clip sub-times overlay via `ClipPlayerModule`. |
| 2 | Auto-Key only if a track already has ≥1 keyframe | UE Sequencer | **In** — existing "+ Add Keyframe" is explicit; never silently add. |
| 3 | Coloured playhead during no-evaluate scrub | UE Sequencer (yellow) | **In** — desaturate / yellow-tint when scrubbing without re-rendering splats. |
| 4 | JKL transport + spacebar + I/O brackets | Premiere/Resolve/AE | **In** — wire to existing playback; near-zero cost. |
| 5 | Snap = single toggle (`N`) + Shift modifier | Resolve toggle + UE Shift drag | **In** — `N` toggles, Shift overrides one-shot. |
| 6 | Project file = recipe, never cooked output | Pro Tools/Logic/SuperSplat | **In** — `viewer-config.json` already follows this; formalise as invariant. |
| 7 | Single observable scene-state + undo/redo | three.js editor / Babylon / PlayCanvas | **In** — `window.__cfg` is the observable; **snapshot** undo (R8), not command-pattern (see §6 + §10.1). |
| 8 | Property-granular last-writer-wins | Figma multiplayer | **In** — `merge_camera_scope` already replaces whole keys; the 9 camera-scope keys are property-granular. |
| 9 | Dope-sheet + curve-editor as two views | UE Sequencer / Spline | **Dope-sheet only** in v1. |
| 10 | Events at keyframe time = annotations/audio/cuts | UE Event Track / Spline | **In** — unify under one "fire at time t" primitive served by the master playhead. |

The bonus (R1 close-out): **don't ship a third-party timeline library for
the "feels smooth" bar.** The editor model (single source of truth, modules,
snapshots) stays ours; existing fragments
(`16_editor_timeline.js_tmpl`) provide the rendering surface.

---

## 2. Architecture overview

### 2.1 The existing scaffold (R2)

HEAD `2b92e75` already ships, in `05_framework.js_tmpl`:

- **`SceneView`** — composition root for every editor surface.
- **`ModeManager`** — registers `enduser` / `embed` / `author` modes;
  toggles `document.body.dataset.mode`.
- **`OverlayScene`** — separate THREE scene for HUD overlays (gizmos,
  trajectory ribbons) that don't disturb the splat scene.
- **`InteractionManager`** — single dispatch surface for mouse/key
  events; modules subscribe.
- **`HudLayer`** — DOM overlay container.

R2's audit (full report at
[docs/superpowers/research/2026-05-20-editor-arc/R2_current_arch_audit.md](../research/2026-05-20-editor-arc/R2_current_arch_audit.md))
found 9 fragments using the scaffold today, all in
[src/splatpipe/viewers/spark/template_parts/](../../../src/splatpipe/viewers/spark/template_parts/).

**Gaps to fill in this rethink:**

- panorama backdrop: 0% (no schema, no render, no editor)
- lighting / post-fx editor: 0% editor (the `cfg.postprocessing` block
  is already wired in the renderer — the gap is "no editor surface")
- annotations: viewer-side render exists; no editor (no place, edit, drag)
- audio: renders but is not patchable through the editor save path
- titles3d: in the public allow-list but has no renderer and no editor

### 2.2 The new contract: `EditorModule` (R6)

Each editor module implements ONE ABC. Inline in
`05_framework.js_tmpl` or in a new `04a_editor_module.js_tmpl` fragment
(per phase plan).

```js
class EditorModule {
  // Identity
  get name() { /* "camera-path" | "annotation" | ... */ }
  get stateKey() { /* viewer-config key this module owns: e.g. "camera_paths" */ }
  get defaultModes() { /* ["author"] | ["author","embed"] */ }

  // Lifecycle — called by EditorModuleRegistry
  mount(sceneView, registry) {}       // wire UI, subscribe to InteractionManager
  unmount() {}                         // detach UI, unsubscribe

  // State propagation
  onCfgChange(newCfg, oldCfg) {}       // other module changed cfg; react if needed
  getDirtyState() { return false; }    // does this module have unsaved local edits?
  markClean() {}                       // called after save

  // Optional timeline / overlay surfaces
  get timelineLane() { return null; }  // { height: px, render(canvas, range) }
  get overlayGroup() { return null; }  // THREE.Object3D added to OverlayScene
  get testSurface() { return null; }   // window.__editor.<name> for Playwright

  // Optional undo hooks (for modules that want to suppress snapshots
  // during ongoing gestures — e.g. dragging a keyframe diamond)
  beginGesture(label) {}               // commits a snapshot once at gesture start
  endGesture() {}                      // marks gesture end
}
```

The contract is **a code-shape standard, not a hard interface.** Modules
that don't need a timeline lane simply return `null`; modules without a
3D overlay return `null` for `overlayGroup`. The registry inspects what's
provided.

### 2.3 The coordinator: `EditorModuleRegistry` (R6)

A small singleton over the modules, hosted in `SceneView`:

```js
class EditorModuleRegistry {
  register(module)                     // mount(sceneView, this)
  unregister(name)                     // unmount()
  get(name)                            // lookup another module
  list()                               // iterate
  collectPatch()                       // build the SPCP1-shape patch for save
  onCfgChange(newCfg, oldCfg)          // broadcast to every module
}
```

`collectPatch()` walks every module, asks it for its `stateKey` slice of
the current cfg, and assembles the patch in the same shape
`merge_camera_scope` already accepts. The save layer (§7) feeds this to
either the CLI clipboard path or the HTTP backend.

### 2.4 The undo store: `EditHistory` singleton (R8)

A new fragment `17a_edit_history.js_tmpl` (~60 lines) hosts a ring
buffer of cfg snapshots:

```js
class EditHistory {
  constructor({ capacity = 200 } = {})
  commit(label, cfg)                   // push snapshot; called on gesture start
  undo()                                // pops one; emits 'undo' event with prev cfg
  redo()                                // re-applies one
  canUndo() / canRedo()                 // boolean — for button enable state
  clear()                               // on scene reload / mode switch
}
```

`window.__editHistory` exposes it (test surface). The registry's
`beginGesture(label)` is the standard place to `commit()`. Ctrl+Z / Ctrl+Y
/ Ctrl+Shift+Z bindings live in `InteractionManager`; undo/redo buttons
(↩ ↪) live in `_tlBarRow` next to the existing play/scrub controls.

See §6 for the full design + the conflict-1 resolution with R1.

### 2.5 The save dispatcher (R4, existing)

`save_mode` is read from `viewer-config.json`; two paths today, ready
for v1:

- **`save_mode="cli"` (default, all 8 scenes today):** Save button copies
  an SPCP1 token to the clipboard; user runs `splatpipe set-camera-path
  <token>` to bake.
- **`save_mode="http"`:** Save POSTs to a configured endpoint
  (`save_backend.endpoint`) with the SPCP1 token in the body + an
  `Authorization: Bearer <token>` header where `<token>` is read from
  `window.location.hash` (`#author=<secret>`). Server-side adapter does
  the same `merge_camera_scope` and re-publishes. The PHP adapter at
  `infra/php/save-camera.php` is implemented + tested per
  `tests/test_php_save_oracle.py`; geddart.de is the locked first host.

Conflict-4 resolution (R4 vs R6 on auto-save) is in §7.3.

---

## 3. Wire schema (R3 + R7-adjusted)

### 3.1 `schema_version` (new top-level key)

```jsonc
{ "schema_version": 1 }
```

- Set publish-time only; NEVER patched from the editor.
- Informational: older viewers ignore unknown keys harmlessly (R5 §4.1);
  newer viewers may gate behaviour on `>= n`.
- Not in `ALLOWED_PATCH_KEYS` — only in `PUBLIC_VIEWER_CONFIG_KEYS`.
- The "v1 marker" for this spec rollout.

### 3.2 `panorama_backdrop` (new top-level block)

```jsonc
{
  "panorama_backdrop": {
    "url": "assets/backdrop.jpg",   // relative to slug; LDR JPG; null = no backdrop
    "rotation_deg": 0,              // [0..360); rotates the equirect around Y
    "intensity": 1.0                // [0..2]; multiplier on scene.backgroundIntensity
  }
}
```

- LDR JPG only in v1. EXR/HDR deferred (R7 §2).
- 4K equirect = 4096×2048, ~44 MB VRAM, ~0.2 ms/frame GPU at desktop
  resolutions (R7 measured).
- Asset URL is relative to the slug (`<cdn>/<slug>/assets/backdrop.jpg`)
  so per-scene rollout never needs absolute URLs.
- Stored at `<slug>/assets/` to keep slug-internal mirroring (cf the
  `audio/` convention already in use).
- The viewer renders it as a `THREE.PMREMGenerator` cubemap into
  `scene.background` only — NOT `scene.environment` (which only affects
  PBR materials; splats don't use it).
- Intensity multiplier exists so authors can dim a too-bright stock pano
  without re-encoding the JPG.

Editor-side ownership: **PanoramaModule** (§4.5).

### 3.3 NO `lighting` block (R7 wins over R3)

R3 proposed a full lighting block (`env_map_url`, `ambient_intensity`,
`directional_lights[]`, `exposure`, `tone_mapping`, `gamma`). **R7
demonstrates it's a dead knob for splats:**

- Splats render via cluster-SH (or paged ExtSH); per-splat colour
  evaluates `evaluateExtSH(splat, viewDir)` (R7 cited
  `ExtSplats.ts::evaluateExtSH`) which uses ONLY the texture-fetched SH
  coefficients baked at training. No scene light contributes.
- THREE's `AmbientLight`/`DirectionalLight`/`scene.environment` affect
  PBR materials only. Splats are not PBR.
- Therefore: any "scene lighting" editor surface would be a UI lie ("I
  moved the directional light, nothing changed").

**Resolution:** v1 ships NO `lighting` block. The post-effects that
DO work (and ARE already wired in the renderer) are
`cfg.postprocessing.tonemapping`, `cfg.postprocessing.exposure`, and the
new `panorama_backdrop.intensity`. Those become editor-visible knobs via
**PostFXModule** and **PanoramaModule** (§4.5, §4.6).

For futures: if the editor ever needs scene-graph lights (e.g. for a
non-splat 3D title or annotation that DOES use PBR), it can be added as
a separate `scene_lights` block later. Outside v1 scope.

### 3.4 Allow-list additions (one-line patches)

`src/splatpipe/core/config_safety.py:PUBLIC_VIEWER_CONFIG_KEYS` — append:

```python
"panorama_backdrop",
"schema_version",
```

(NOT `lighting` — dropped per §3.3.)

`src/splatpipe/core/config_merge.py:ALLOWED_PATCH_KEYS` — append:

```python
"panorama_backdrop",
"postprocessing",
"audio",
```

- `panorama_backdrop` — editor edits image url + rotation + intensity.
- `postprocessing` — editor edits tonemapping + exposure.
- `audio` — editor edits tracks + volumes + in/out.

`schema_version` is **NOT** in `ALLOWED_PATCH_KEYS` — set publish-time
only (see §3.1).

### 3.5 Existing keys becoming editor-visible

Already in the allow-list, gaining a new editor surface in v1:

- `postprocessing` (new editor: PostFXModule)
- `audio` (new editor: AudioModule)
- `annotations` (new in-viewer authoring: AnnotationModule)
- `titles3d` (new render + editor: TitlesModule)
- `clips` + `cameras` (refactor existing ClipPlayer into edit-time:
  CutsModule)

### 3.6 Forward/back compat (R5 §4)

Every consumer reads `cfg.<key>` defensively via `|| default`. Older
viewers receiving a v1-shape config ignore unknown keys; newer viewers
receiving a pre-v1 config fall back to legacy defaults. R5 verified this
is structurally safe: the rollout is purely additive.

### 3.7 `PathDict.total_duration_s` — timeline scrub range (addendum 2026-05-20)

`core/path_io.py:PathDict` gains a new optional field:

```python
class PathDict(TypedDict, total=False):
    # ... existing fields ...
    total_duration_s: float | None    # author-declared total duration in
                                      # seconds; null/absent => derive from
                                      # last keyframe (see below)
```

The timeline scrub range in the editor (and the playhead's max-time when
`loop=False`) is derived as:

```text
if path.total_duration_s is not None and path.total_duration_s > 0:
    range = [0, path.total_duration_s]
else:
    range = [0, max(last_kf.t, 10.0)]   # 10.0 fallback gives empty-path
                                         # UX a sensible default scrub range
```

**Why:** today the timeline ceiling is tied to `last_kf.t`, which forces
the user to record keyframes in chronological order — they cannot
"reserve" the t=15-30s slot of a 30s path while still iterating on the
opening shot. Decoupling unblocks the natural workflow: declare the
total length first, then drop keyframes anywhere along it.

**Backwards-compat:** absent / null behaves identically to today's
behaviour (range = `[0, last_kf.t]`, fallback `10.0` for empty paths).
Older viewers that don't read the field continue to derive the range
from `last_kf.t`. No allow-list change is needed: `camera_paths` is
already in `ALLOWED_PATCH_KEYS` and merges with whole-replace semantics
— the new field rides inside the existing key.

**Patch shape:** the SPCP1 token wrapping the `camera_paths` array
carries `total_duration_s` per path, like any other path-scope field.
`core/scene_cuts.py` validation accepts the new field (no-op).

Editor-side ownership: **CameraPathModule** (§4.1 — the editor surface
that authors this value).

---

## 4. Editor modules (per R6 contract)

Each module slice is keyed on ONE `stateKey` (a single `cfg` top-level
property). Modules communicate through the registry + the `cfg`
observable (NOT direct cross-imports).

### 4.1 `CameraPathModule` (refactor)

- **`stateKey`**: `camera_paths` + `default_path_id` + `start_view`
  (composite — a single module owns "camera authoring" as a whole).
- **`defaultModes`**: `["author"]`.
- **Existing surface**: fragments `15_editor_trajectory.js_tmpl` +
  `16_editor_timeline.js_tmpl` + `17_editor_gizmo.js_tmpl` + the path UI
  in `_authorTopRail` already cover keyframe authoring. v1 wraps them in
  the new contract; behaviour preserved byte-for-byte (output-pin
  invariant from the #118 modularization).
- **Timeline lane**: existing horizontal scrubber + yellow diamonds.
  The scrub-range ceiling is derived from `total_duration_s` (when set)
  or falls back to `max(last_kf.t, 10.0)` (see §3.7).
- **Overlay group**: existing trajectory ribbon + per-keyframe gizmo.
- **`beginGesture("kf-drag")`** at the start of a diamond drag;
  `endGesture()` at mouseup → ONE undo entry per drag (R8 §4.2).

#### 4.1.1 Transport-row controls (addendum 2026-05-20)

The `_tlBarRow` transport row hosts the existing play/pause + scrub
controls. v1 adds three additional controls per the user's authoring
feedback (see top-of-spec addenda block):

| Control | Visual | Behaviour |
|---|---|---|
| Total-time input | `[ 30 ] s total` (number input + unit label) | When **auto** is OFF, the number is editable and writes to `path.total_duration_s`. When **auto** is ON, the input is read-only and displays `max(last_kf.t, 10.0)`. |
| Auto toggle | small button next to the input (`auto` / `manual`) | Toggles `path.total_duration_s` between `null` (auto) and the entered number (manual). Default = `auto` for new paths and for any path without the field (back-compat). |
| `|◀` Prev-keyframe | left-pointing skip glyph | Jumps the playhead to the largest `kf.t` strictly LESS THAN the current playhead time. If no such kf exists, jumps to `t=0`. |
| `▶|` Next-keyframe | right-pointing skip glyph | Jumps the playhead to the smallest `kf.t` strictly GREATER THAN the current playhead time. If no such kf exists, jumps to `total_duration_s` (or `last_kf.t` when no total is set). |

**Sorted-time correctness.** The keyframes array is not guaranteed
chronologically ordered (the editor permits dragging a diamond past its
neighbours); prev/next must consult the **sorted-by-`t` view** as the
source of truth, NOT the raw array order. The existing
`16_editor_timeline.js_tmpl` already maintains a sorted-t cache for the
diamond render; the skip buttons reuse it.

**Undo policy (R8 §4.2 carry-over).**
- Total-time input change → ONE EditHistory snapshot on commit
  (`onBlur` or Enter — NEVER per keystroke; matches the gesture-start
  principle, where the gesture here is "value-change-finalised").
- Auto toggle change → ONE EditHistory snapshot on click.
- Prev/Next-keyframe skip → NO EditHistory snapshot (navigation, not
  edit; the playhead position itself is not part of the persisted cfg).

**Hotkeys.** `Ctrl+Left` / `Ctrl+Right` are wired in `InteractionManager`
to the same prev/next handlers. macOS uses `event.metaKey || event.ctrlKey`
(same convention as the existing undo/redo hotkeys, §6.5).

### 4.2 `AnnotationModule` (refactor + add authoring)

- **`stateKey`**: `annotations`.
- **`defaultModes`**: `["author"]` for editing; `["enduser","embed"]`
  for render (read-only).
- **Existing surface**: render-side only (annotation dots + labels).
- **New in v1**:
  - Click-in-3D to place a new annotation at the world position under
    the cursor (raycast against the splat-bound proxy or a depth
    sample).
  - Double-click an existing dot to edit the text inline.
  - Drag the dot in the OverlayScene to reposition (`beginGesture("ann-move")`).
  - Kebab menu → "Delete".
  - Timeline lane: `t_in..t_out` bars per annotation (shown on a
    dedicated row in the multi-lane timeline; see §4.10).
- **Schema** (existing, unchanged):
  ```jsonc
  { "id": "...", "pos": [x,y,z], "text": "...",
    "t_in": 0, "t_out": 5, "color": "#fff" }
  ```

### 4.3 `CutsModule` (refactor existing ClipPlayer into edit-time)

- **`stateKey`**: `clips` + `cameras` (composite, like CameraPathModule
  owns paths + defaults). `cameras` is the list of cameras to cut
  between; `clips` is the timeline order.
- **`defaultModes`**: `["author"]` for editing; `["enduser","embed"]`
  for playback (read-only).
- **Existing surface**: `11_clip_player.js_tmpl` already plays cuts; the
  data shape is in `core/scene_cuts.py`. v1 ADDS authoring.
- **New in v1**:
  - Timeline lane shows each clip as a block keyed by camera color +
    label.
  - Drag block edges → retime in/out.
  - Drag block body → reorder.
  - Click → select; del key → delete.
  - "+ Add Clip" inserts a new clip at the playhead from the currently
    selected camera.
- **Annotation triggers across cut boundaries**: when a clip ends, the
  master playhead's annotation-trigger evaluator unwinds any active
  annotation (so a `t_out` past the clip boundary doesn't survive into
  the next cut). Implementation: the master playhead fires
  `playhead.onTimeChange(masterT)` which CutsModule maps to
  `(clipId, clipLocalT)`; AnnotationModule subscribes and reads
  clip-local time.

### 4.4 `AudioModule` (NEW)

- **`stateKey`**: `audio` (already in `PUBLIC_VIEWER_CONFIG_KEYS`,
  newly added to `ALLOWED_PATCH_KEYS`).
- **`defaultModes`**: `["author"]` for editing; `["enduser","embed"]`
  for playback.
- **Schema** (existing partial, formalised in v1):
  ```jsonc
  {
    "audio": [
      {
        "id": "track1",
        "url": "audio/intro.mp3",
        "kind": "global" | "positional",
        "pos": [x,y,z],          // only if kind=positional
        "volume": 0.6,           // [0..1]
        "loop": false,
        "t_in": 0,               // master-time seconds
        "t_out": null            // null = play to end
      }
    ]
  }
  ```
- **Asset upload**: reuse existing `/upload-audio` route (already
  hardened in audit #7 against path traversal; tests in
  `test_audio_upload_security.py`). Per-scene audio lives at
  `<slug>/audio/<track>.mp3`.
- **Timeline lane**: per-track row with audio blocks at `t_in..t_out`,
  one row per track id.
- **Editor UI**:
  - "+ Add Track" → file picker.
  - Per-track: volume slider, in/out time inputs, positional toggle.
  - Click-in-3D to set positional source position (only when positional
    toggle is on).

### 4.5 `PanoramaModule` (NEW; absorbs R6's LightingModule, see §10.3)

- **`stateKey`**: `panorama_backdrop`.
- **`defaultModes`**: `["author"]` for editing; `["enduser","embed"]`
  for render.
- **Editor UI** (in `author-root`):
  - File picker → upload via new `POST /upload-image` route (follow
    audit #7 hardening pattern — see [§7.6](#76-new-upload-image-route)).
  - Rotation slider: `0..360°`.
  - Intensity slider: `0..2`.
  - Tooltip: "Backdrop only. Splats are pre-lit from training data —
    scene lights have no effect on splat pixels."
- **Renderer integration**: PMREMGenerator equirect → cubemap → assign
  to `scene.background`. NOT `scene.environment`. Setting
  `scene.backgroundIntensity = panorama_backdrop.intensity`.
- **Asset deployment**: per-scene `<slug>/assets/backdrop.jpg`; PUT via
  the existing Bunny upload helper in `steps/deploy.py:_put_file`;
  purge that specific URL on save.

### 4.6 `PostFXModule` (NEW)

- **`stateKey`**: `postprocessing`.
- **`defaultModes`**: `["author"]` for editing; `["enduser","embed"]`
  for render.
- **Schema** (already wired in the renderer):
  ```jsonc
  {
    "postprocessing": {
      "tonemapping": "ACESFilmic" | "Reinhard" | "Cineon" | "None",
      "exposure": 1.0           // [0..3]
    }
  }
  ```
- **Editor UI**: tonemapping dropdown + exposure slider.
- **Tooltip**: "Affects post-render only. Splats already carry baked
  lighting; for tonemap-equivalent feel, lower the panorama intensity
  too."

### 4.7 `TitlesModule` (NEW — render + editor)

- **`stateKey`**: `titles3d`.
- **`defaultModes`**: `["author"]` for editing; `["enduser","embed"]`
  for render.
- **Render**: `THREE.CSS3DObject` (or sprite + canvas-texture as
  fallback for stability on Safari/iOS) attached to OverlayScene; the
  splat scene clears depth as today.
- **Schema** (existing, formalised):
  ```jsonc
  {
    "titles3d": [
      {
        "id": "title1",
        "pos": [x,y,z],
        "text": "Scene 01 — kf-fehmarn",
        "size": 0.5,
        "color": "#fff",
        "t_in": 0,
        "t_out": 6
      }
    ]
  }
  ```
- **Editor UI**:
  - Click-in-3D to place; text input field; color picker; size slider.
  - Timeline lane: per-title bar at `t_in..t_out`.
  - Drag in OverlayScene to reposition (`beginGesture("title-move")`).

### 4.8 `IntroModule` (existing — minor polish)

- **`stateKey`**: `intro`.
- **`defaultModes`**: `["author"]` for editing; `["enduser","embed"]`
  for render.
- **Existing**: `intro: { type: "fade", ms: 900 }` already shipped in
  `19_intro_controller.js_tmpl`. v1 just adds a small editor block
  (dropdown for type, number input for ms) — no schema change.

### 4.9 Module registration order (boot)

In `05_framework.js_tmpl`'s SceneView init:

```js
const registry = new EditorModuleRegistry(sceneView);
registry.register(new CameraPathModule());
registry.register(new CutsModule());
registry.register(new AnnotationModule());
registry.register(new AudioModule());
registry.register(new PanoramaModule());
registry.register(new PostFXModule());
registry.register(new TitlesModule());
registry.register(new IntroModule());
window.__editorRegistry = registry;        // test surface
```

Order matters only for visual stacking (timeline lane order) and the
order they observe `onCfgChange`. CameraPathModule first because the
master playhead is its tick source; everything else subscribes downstream.

### 4.10 Multi-lane bottom-timeline (R6)

The timeline panel under the viewport hosts 5 lanes (top-to-bottom):

| Lane | Owner | Height (px) | Visual |
|---|---|---:|---|
| Cameras / paths | CameraPathModule | 32 | yellow diamonds + path color stripe |
| Cuts | CutsModule | 24 | per-camera coloured clip blocks |
| Annotations | AnnotationModule | 16 | thin coloured bars at `t_in..t_out` |
| Audio | AudioModule | 20 | per-track rows; bar height encodes volume |
| Titles | TitlesModule | 16 | thin white bars |

Total ~108 px + 10 px gutters = ~150 px panel height. Lane order is
fixed in v1; per-user customisation deferred.

Renders via canvas (existing pattern in `16_editor_timeline.js_tmpl`)
for performance with many keyframes; DOM overlay (existing) for the
playhead + brush cursor.

---

## 5. Lighting + panorama (R7 + reconciled with R3)

R7's central finding: **Gaussian splats are pre-lit**.

```
splat_color(viewDir) = base_rgb + evaluateExtSH(sh_coeffs, viewDir)
                     // ^ from ExtSplats.ts::evaluateExtSH
                     // ^ NOTHING in this path references scene lights
```

Therefore:

- `AmbientLight`, `DirectionalLight`, `PointLight`, etc. — would only
  light *non-splat* geometry. There is essentially no non-splat geometry
  in v1 (titles3d uses an unlit CSS3DObject; annotations are 2D-sprites
  facing-camera; gizmos are unlit lines).
- `scene.environment` — affects PBR `MeshStandardMaterial` etc. We don't
  use those.
- `scene.background` — sky / backdrop only. THIS is what changes pixels
  the user can see.

### 5.1 Resolution (R3 vs R7 conflict)

**R7 wins.** v1 ships no `lighting` block in the schema. The post-effect
knobs that DO work are kept under the existing `cfg.postprocessing`
top-level key (already wired in the renderer; gains an editor surface).
The backdrop gets its own `cfg.panorama_backdrop` block.

### 5.2 Panorama backdrop MVP scope (R7 §2)

- **Format**: LDR JPG only. ~4 MB on disk per 4K equirect; ~44 MB VRAM
  per texture upload (R7 measured).
- **GPU cost**: ~0.2 ms/frame on a desktop dGPU at 1080p. Negligible.
- **Mobile**: 2K equirect (2048×1024) fallback recommended; the
  PanoramaModule reads `window.devicePixelRatio` + viewport area and
  picks the smaller mip if the device looks mobile.
- **Storage**: `<slug>/assets/backdrop.jpg`. The path is per-slug so a
  scene without a backdrop simply has `url: null` and the renderer skips
  the upload.
- **Upload route**: new `POST /upload-image` (see §7.6).

### 5.3 PostFXModule scope (R7 §3 + existing `cfg.postprocessing`)

- Existing renderer code already reads `cfg.postprocessing.tonemapping`
  + `cfg.postprocessing.exposure`. v1 only adds an editor surface — no
  renderer change.
- Tonemapping options: ACESFilmic (default), Reinhard, Cineon, None.
- Exposure: continuous `[0..3]` slider; default `1.0`.

### 5.4 What the user sees (tooltip copy, drafted)

In the PanoramaModule editor panel:

> **Backdrop.** Background image behind the splat scene. Splats are
> pre-lit from training data, so scene lights have no effect on splat
> pixels. Use tonemapping + exposure (Post-FX panel) to match the
> backdrop's brightness.

---

## 6. Undo/redo (R8 — snapshot pattern)

### 6.1 The pattern (R8 §3)

A 200-entry ring buffer of `cfg` snapshots. On every gesture start
(drag begin, click-to-create, slider-pointer-down):

```js
__editHistory.commit(label, structuredClone(window.__cfg));
```

Undo restores a prior snapshot wholesale; redo re-applies one.

### 6.2 Why snapshot (not command pattern) — Conflict 1 resolution

R1 §3 documented that three.js editor / Babylon Inspector / PlayCanvas
all use the **command pattern** (`execute()`/`undo()` symmetry). It IS
the table-stakes pattern for pro editors. So why does splatpipe pick
the simpler snapshot pattern?

**Scale.** R8 §2 measured:

- A typical `cfg` after authoring 16 keyframes + 4 annotations + 2
  clips + 2 audio tracks + 1 panorama = ~8 KB JSON.
- Worst plausible case (16-keyframe path with full per-keyframe data +
  every editor surface fully populated) = ~50 KB JSON, ~200 KB JS heap
  including the structured-clone wrapper.
- 200 snapshots × 200 KB = **40 MB max heap**.

For context: a single mid-size scene's `.rad` set is 100-674 MB VRAM.
The 40 MB undo store is a **rounding error** vs the splat data.

**On the other side** of the trade-off, snapshot saves implementing
~50 inverse operations (one per CRUD entry point: addKeyframe / delKeyframe
/ retimeKeyframe / setPose / addAnnotation / delAnnotation / moveAnnotation
/ ... × 8 modules). Each inverse op is a possible bug surface and a
test target. Snapshot has ZERO per-module undo code — every undo is the
same one-line `cfg = history.undo()`.

**The trade-off flips for splatpipe** because (a) the heap cost is
trivial vs the data already in memory and (b) avoiding the inverse-op
implementation surface is a big win for a small dev team. The PRO editors
use command pattern because their state graphs are vastly larger
(PlayCanvas projects are ~MB-scale graphs of typed scene nodes,
materials, scripts, ...) where snapshotting the whole graph 200 times
would be impractical.

**Decision: snapshot.** Document R1's command-pattern recommendation as
the standard pro-editor approach + R8's defense for why splatpipe's
scale flips the trade-off.

### 6.3 Gesture-start commit (R8 §4.2)

CRITICAL: commit at gesture START, not per animation frame.

```js
// CORRECT — one undo entry for the whole drag
onMouseDown:  beginGesture("kf-drag"); __editHistory.commit(...);
onMouseMove:  mutate cfg in place; render;
onMouseUp:    endGesture();    // no commit here

// WRONG — 60 entries per second
onMouseMove:  __editHistory.commit(...);  // ← do NOT do this
```

The standard pattern: every interactive control wraps its handler in
`registry.beginGesture(label)` / `registry.endGesture()`; the registry
debounces the commit to the leading edge.

For non-gesture mutations (text input commit, dropdown change), commit
on the value-change event (i.e. one commit per typed-edit-finalised).

### 6.4 Ephemeral (R8 §5)

Undo history clears on:

- mode switch (e.g. author → enduser)
- scene reload
- save (the new "clean" state is the baseline; undoing past it doesn't
  match the saved file)

The history is NOT persisted (no localStorage). Closing the tab loses
undo state — by design, matches the "no auto-save" decision.

### 6.5 UI affordances (R8 §6)

- **Buttons** ↩ ↪ in `_tlBarRow` (the existing transport row). Disabled
  state when `canUndo()/canRedo()` is false.
- **Keys**: `Ctrl+Z` = undo, `Ctrl+Y` = redo, `Ctrl+Shift+Z` = redo
  (alternate). `Cmd+Z` / `Cmd+Y` / `Cmd+Shift+Z` on macOS via the same
  `event.metaKey || event.ctrlKey` check.
- **Toast/HUD** on undo: brief "Undid: <label>" overlay (existing HudLayer).

#### 6.5.1 Editor hotkey table (consolidated)

The full editor hotkey table after the 2026-05-20 addenda:

| Combo | Owner | Action | Undo entry? |
|---|---|---|---|
| `Ctrl+Z` / `Cmd+Z` | InteractionManager → EditHistory | Undo last gesture | n/a |
| `Ctrl+Y` / `Cmd+Y` | InteractionManager → EditHistory | Redo | n/a |
| `Ctrl+Shift+Z` / `Cmd+Shift+Z` | InteractionManager → EditHistory | Redo (alternate) | n/a |
| `Ctrl+Left` / `Cmd+Left` | InteractionManager → CameraPathModule | Jump playhead to previous keyframe (sorted-t) | No (navigation) |
| `Ctrl+Right` / `Cmd+Right` | InteractionManager → CameraPathModule | Jump playhead to next keyframe (sorted-t) | No (navigation) |
| `Space` | InteractionManager → master playhead | Play / Pause | No |
| `N` | InteractionManager → snap toggle | Toggle snap on/off (R1 pattern 5) | No |

Hotkeys are wired centrally in `InteractionManager` and dispatched to
module-owned handlers. The modifier convention (`event.metaKey ||
event.ctrlKey`) is the same on every binding for Win/Mac parity.

### 6.6 New fragment

`src/splatpipe/viewers/spark/template_parts/17a_edit_history.js_tmpl`
(~60 lines), inserted between `17_editor_gizmo.js_tmpl` and
`18_frame_loop.js_tmpl`. The numeric prefix `17a` is the existing
convention for fragments inserted between numbered slots without
renumbering the whole stack.

The `template_parts/__init__.py` fragment-list is updated to include
the new file (Phase 1 task).

---

## 7. Save flow (R4)

### 7.1 `save_mode=cli` (default, all 8 scenes today)

No change from existing behaviour. Save button:

1. `registry.collectPatch()` → builds the camera-scope patch.
2. `SPCP1.encode(patch)` (existing `spcp_token.py` codec) → token.
3. `navigator.clipboard.writeText(token)`.
4. Toast: "Token copied. Run `splatpipe set-camera-path <token>` to bake."

The user pastes into a Telegram-to-Claude channel or directly into the
CLI. `splatpipe set-camera-path` fetches the live config, runs
`merge_camera_scope`, and re-publishes (which preserves `primary_asset`
via the locked invariant).

### 7.2 `save_mode=http` (per-scene flip)

Same patch-build flow; Save POSTs to `cfg.save_backend.endpoint`:

```http
POST /save-camera.php HTTP/1.1
Authorization: Bearer <secret from window.location.hash#author=...>
Content-Type: text/plain

<SPCP1 token>
```

Server-side adapter (`infra/php/save-camera.php`, fully implemented per
R4 §1; tested by `tests/test_php_save_oracle.py`):

1. Verify `Authorization` header matches the per-scene secret in
   `<docroot>/scenes/<slug>/.author-token`.
2. Decode SPCP1 token via the PHP port of the codec.
3. Fetch current `viewer-config.json` (Bunny GET).
4. Run the PHP port of `merge_camera_scope`.
5. PUT the new config back; purge the Bunny URL.
6. Write a `.bak` of the prior config (one-step server-side undo).
7. 200 OK + `{ ok: true }` to the client.

The PHP port is byte-identical to the Python merge per the oracle test.

### 7.3 Explicit save only — Conflict 4 resolution (R4 vs R6)

R6 §5 proposed an `onCfgChange()` hook that debounces and auto-saves.
R4 §3 strongly recommends explicit save (no debounce).

**Resolution: R4 wins in v1.**

- **R4's case** (taken): explicit save matches the SuperSplat /
  three.js editor / Premiere model — the user is responsible for
  committing. Auto-save introduces:
  - Save bursts during a slider drag (60+ POSTs/s if not debounced;
    debouncing introduces "did I lose that?" ambiguity).
  - Conflict-resolution surface if the user has two tabs open.
  - "Did I actually save?" anxiety (vs the unambiguous Save button +
    toast).
- The module-contract's `onCfgChange(newCfg, oldCfg)` hook stays
  defined and stays useful (modules need to react to other modules'
  changes — e.g. CutsModule needs to re-evaluate clip boundaries when
  CameraPathModule changes a camera's `start_view`). It just doesn't
  trigger network I/O in v1.
- **Future phase** (out of v1): an opt-in "Auto-save (off)" toggle in
  the HUD can flip on the debounced auto-save path. The contract is
  ready.

### 7.4 413 fallback (R4 §6)

Some HTTP backends (PHP-on-Strato, in particular) cap POST bodies. If
the save POST returns `413 Payload Too Large`, the viewer falls back to
the CLI clipboard path automatically:

```
Save → POST → 413 → catch → copy token to clipboard
      → Toast: "Backend rejected (too large). Token copied — relay via
                splatpipe set-camera-path."
```

This is the right failure mode: the user keeps their work; the relay
mechanism is identical to the default `cli` mode they were used to.

### 7.5 Offline (R4 §7)

`onbeforeunload` if dirty + offline (navigator.onLine === false):

1. Save the in-flight patch to `localStorage["spcp-draft:<slug>"]`.
2. On next page load, if a draft exists, show "Unsaved draft from
   <date>" → Restore / Discard.
3. `window.addEventListener('online', ...)` while a draft exists: try
   to POST it automatically; on success, clear the draft.

This is opt-in safety, not auto-save: the user still hits Save to push
the *current* state. The draft path only catches the "I closed the tab
while offline" failure mode.

### 7.6 New `POST /upload-image` route

For the PanoramaModule. Mirror the `/upload-audio` route's bug-audit #7
hardening pattern (`web/routes/projects.py:upload_audio`, lines
1235-1320):

- Reject any filename containing `/` `\` or `:` separators; reject
  empty / `.` / `..` / dotfile names; reject names that change under
  `Path(name).name`.
- Allow-list extensions: `{.jpg, .jpeg, .png}` (LDR only in v1; no
  HDR/EXR).
- Cap content-length at 20 MB (Content-Length pre-check + streaming
  guard).
- Use `core/path_safety.ensure_contained()` to gate the destination
  path (`<project>/05_output/assets/`).
- Collision policy: 409 on name reuse (safer than overwriting; matches
  upload_audio behaviour).
- Tests added per `tests/test_audio_upload_security.py`'s pattern (new
  file `tests/test_image_upload_security.py`).

### 7.7 LWW conflict (R1 pattern 8 + R4 §4)

`merge_camera_scope` already replaces whole top-level keys (R5 §1.2),
so a save races at property granularity. If two tabs save
`camera_paths` simultaneously, the second write wins on that key; both
keep `audio` and `annotations` if neither touched them. This is the
Figma-multiplayer pattern, structurally enforced by the merge core.

No CRDT, no operational transform, no version vector. The R1/R4
analyses both concluded the merge granularity is right for splatpipe's
multi-tab-or-CLI concurrency surface (which is one author, not real-time
multi-author).

### 7.8 Token UX (R4 §5)

Per R4: URL fragment, `<slug>/index.html#author=<secret>`. Reasons (R5 §7.3):

- The fragment never leaves the browser (no server request includes it).
- Closing the tab drops it (matches the per-tab security boundary).
- Bookmarkable per-scene.
- No localStorage indirection.

Per-scene secrets are generated at backend-rollout time + stored in the
author's password manager (Phase 3 in the plan). The fragment is what
the author bookmarks; the secret IS the fragment.

---

## 8. Multi-scene rollout (R5)

### 8.1 Per-scene cadence (R5 §2)

NOT an atomic 8-scene batch. Order:

1. **`kf-fehmarn`** — first; already exercises camera_paths +
   paged_ext_splats; lead scene.
2. **`fehmarn`** — alias slug consolidation (R5 §1.1 + open question
   §11.1).
3. **`ibug`** — large scene; stress-test chunked LOD streaming.
4. **`speicher`** — has `clip_xy=3.0` override; verifies per-scene
   overrides survive rollout.
5. **`polygraf`** + **`polygraf-east`** + **`fabrik`** — standard
   single-camera scenes.
6. **`stettiner`** + **`methtrailer`** — last in line (less critical).

Each scene's rollout is one `splatpipe publish` invocation + a
post-deploy verify cycle (R5 §4).

### 8.2 Schema-additive (R5 §4 confirmed)

The rollout adds:

- `schema_version: 1`
- `panorama_backdrop: { url: null, rotation_deg: 0, intensity: 1.0 }`
- `clips: []`, `cameras: []`, `titles3d: []` (per-scene, populated by
  the author after deploy)

ALL of these are no-ops to an older viewer. Backwards-compat is
structurally safe (R5 §4.1).

### 8.3 `.kfwork/deploy_kf_fehmarn*.py` retirement (R5 §3)

The 5 bespoke scripts at
`.kfwork/deploy_kf_fehmarn{_<sha>}.py` bypass `publish_scene()` and
therefore bypass:

- the `sanitize_public_viewer_config()` allow-list (bug-audit #3);
- the publish_scene self-checks (`fork_rcf2` marker, etc.);
- the `bkey` rotation;
- the save-backend plumbing.

**Retirement:** on the first `splatpipe publish` of `kf-fehmarn` under
this rollout, the 5 scripts become obsolete. `git rm` them + the
`.kfwork/stage_kf_fehmarn*/` dirs. Document the retirement in CLAUDE.md
"Known Limitations / TODO" (already noted there).

### 8.4 Save backend switch DECOUPLED (R5 §6)

The save-backend switch (`cli` → `php`) is its own phase, AFTER the
editor + schema rollout completes for all 8 scenes. Rationale: bundling
multiplies the failure surface (editor regressions + backend config
bugs simultaneously). 3-phase cadence (R5 §6.2 + R4 §1):

- **Phase 1 (rollout):** all 8 scenes shipped with the new editor
  schema; `save_mode="cli"`.
- **Phase 2:** geddart.de PHP backend live + tested end-to-end against
  ONE scene (kf-fehmarn).
- **Phase 3:** per-scene config flip from `cli` to `http`, one scene at
  a time; each flip is a tiny `project.toml` edit + `splatpipe publish`.

### 8.5 Asset pipeline per scene (R5 §8)

- **Panorama**: 15-30 min if a source equirect exists; 1-2 hours if
  shooting / synthesising new.
- **Audio**: 5 min once a track is selected.
- **Camera paths**: 10-20 min per path.
- **Cuts**: 5-10 min per cut sequence (skip for single-camera scenes).
- **Annotations / titles**: 5 min each.

**Per-scene typical: ~1.5 hours.** **Total across 8 scenes: ~12 hours**
dominated by authoring, not by deploy mechanics (which take seconds per
scene once the editor exists).

### 8.6 Cache busting per slug (R5 §5)

Unchanged from existing publish flow:

- `index.html` + `viewer-config.json`: Bunny Edge Rule
  `OverrideCacheTime=0`.
- `<bkey>/*.rad`, `*.radc`: 30-day cache (immutable per-build; rotates
  via `bkey` change).
- New per-scene assets (`assets/backdrop.jpg`, `audio/<track>.mp3`):
  default cacheable; the upload routes purge that specific URL on
  upload.

---

## 9. File layout (new + modified)

### 9.1 New files

| Path | Purpose |
|---|---|
| `src/splatpipe/viewers/spark/template_parts/17a_edit_history.js_tmpl` | EditHistory ring buffer + Ctrl+Z/Y wiring (~60 lines per R8) |
| `src/splatpipe/viewers/spark/template_parts/04a_editor_module.js_tmpl` | EditorModule ABC + EditorModuleRegistry (~150 lines per R6) |
| `src/splatpipe/web/routes/upload_image.py` | new `POST /upload-image` route (panorama uploads; mirrors audio_upload pattern) |
| `tests/test_image_upload_security.py` | path-traversal tests for `/upload-image` (mirror `test_audio_upload_security.py`) |
| `tests/test_edit_history.py` | EditHistory ring buffer behaviour (Node-driven, mirrors `test_spcp_js_port.py` pattern) |
| `tests/test_editor_module_contract.py` | every concrete EditorModule satisfies the ABC shape via Playwright `window.__editor.<name>` probe |
| `tests/test_panorama_backdrop_schema.py` | sanitiser + merge accept the new keys; older configs without the keys still pass |
| `tests/test_publish_schema_version.py` | `splatpipe publish` writes `schema_version: 1` into every output cfg |

### 9.2 Modified files

| Path | Modification |
|---|---|
| `src/splatpipe/core/config_safety.py` | append `"panorama_backdrop"` + `"schema_version"` to `PUBLIC_VIEWER_CONFIG_KEYS` |
| `src/splatpipe/core/config_merge.py` | append `"panorama_backdrop"` + `"postprocessing"` + `"audio"` to `ALLOWED_PATCH_KEYS` |
| `src/splatpipe/steps/publish.py` | write `schema_version: 1` + empty `panorama_backdrop` defaults into the staged cfg in `publish_scene()` |
| `src/splatpipe/viewers/spark/template_parts/__init__.py` | register the 2 new fragments in the load order |
| `src/splatpipe/viewers/spark/template_parts/05_framework.js_tmpl` | instantiate `EditorModuleRegistry` in SceneView; wire `__editHistory` exposure |
| `src/splatpipe/viewers/spark/template_parts/15_editor_trajectory.js_tmpl` | refactor onto EditorModule contract (CameraPathModule) — behaviour preserved |
| `src/splatpipe/viewers/spark/template_parts/16_editor_timeline.js_tmpl` | add multi-lane rendering for cuts/audio/annotations/titles lanes |
| `src/splatpipe/viewers/spark/template_parts/17_editor_gizmo.js_tmpl` | wire gizmo handles to `beginGesture()` / `endGesture()` |
| `src/splatpipe/viewers/spark/template_parts/11_clip_player.js_tmpl` | refactor onto contract; add author-mode editing surface (CutsModule) |
| `src/splatpipe/viewers/spark/template_parts/07_setup_three_spark.js_tmpl` | panorama equirect → PMREMGenerator → `scene.background`; honour `panorama_backdrop.intensity` |
| `src/splatpipe/viewers/spark/template_parts/03_body_chrome.html_tmpl` | add author-root panels for each new module (collapsible accordion) |
| `src/splatpipe/viewers/spark/template_parts/02b_styles_editor.css_tmpl` | styles for new module panels + multi-lane timeline |
| `src/splatpipe/viewers/spark/assembler.py` | output-pin update post-Phase-1 (modularization invariant) |
| `src/splatpipe/web/app.py` | mount `upload_image` route |
| `tests/test_config_merge.py` | extend allow-list coverage to the 3 new patch keys |
| `tests/test_publish_config_sanitize.py` | extend allow-list coverage to the 2 new public keys |
| `tests/test_html_for_save_mode.py` | output-pin re-baseline (Phase 1) |
| `CLAUDE.md` | document the new EditorModule contract + EditHistory + the .kfwork retirement |
| `CHANGELOG.md` | per-phase entries (see plan) |

### 9.3 Files NOT changing in v1

- `src/splatpipe/core/spcp_token.py` — codec wire format unchanged.
  `merge_camera_scope` still consumes the same SPCP1 shape; the new
  patch keys (`panorama_backdrop`, `postprocessing`, `audio`) ride
  inside the same wrapper.
- `src/splatpipe/save_backends/php.py` — already routes through
  `merge_camera_scope` and gains the new keys for free via the allow-list
  expansion.
- `src/splatpipe/save_backends/cloudflare.py` — exists as a stub; not
  rolled out in v1.
- `infra/php/save-camera.php` — already implemented + tested; the new
  patch keys flow through unchanged.

---

## 10. Conflicts resolved (summary)

This synthesis reconciles 4 conflicts between the 8 research reports.
Each resolution is cross-linked above; this section is the central
index.

### 10.1 Conflict 1 — Undo pattern: command (R1) vs snapshot (R8)

- **R1** documented that three.js editor / Babylon Inspector v2 /
  PlayCanvas Editor all converged on the **command pattern**
  (`execute()` / `undo()` symmetry, with the history stack itself
  serialised to the project file). This is the standard pro-editor
  pattern.
- **R8** counter-proposed the **snapshot pattern** for splatpipe based
  on measured cfg sizes: 200 snapshots × ~200 KB worst-case = 40 MB
  heap = a rounding error vs the 100-674 MB GPU splat data already in
  memory. Snapshot saves implementing ~50 per-module inverse-op
  routines (a per-module dev-time + test-surface cost), and every undo
  is one line.

**Resolution: R8 wins for splatpipe.** Snapshot is right here because
(a) heap cost is trivial vs the splat data, (b) inverse-op
implementation surface is a real cost we avoid. R1's command-pattern
recommendation IS the standard for pro 3D editors at PlayCanvas /
three.js / Babylon scale — and would be the right call if splatpipe
ever grows to that data-graph complexity. For now, snapshot.

See §6 for the full design.

### 10.2 Conflict 2 — Lighting block scope: R3 full schema vs R7 "lights are dead knobs"

- **R3** proposed a full `lighting` block: `env_map_url`,
  `ambient_intensity`, `directional_lights[]`, `exposure`,
  `tone_mapping`, `gamma`.
- **R7** demonstrated (with cites to `ExtSplats.ts::evaluateExtSH`)
  that Gaussian splats are pre-lit from training SH coefficients; no
  THREE scene light contributes to splat pixels.

**Resolution: R7 wins.** v1 ships no `lighting` block. The post-effect
knobs that DO change pixels (tonemapping, exposure) live under the
existing `cfg.postprocessing` block; the backdrop intensity lives under
the new `cfg.panorama_backdrop` block. Editor tooltip explicitly states
the constraint so users don't expect light-rig editing.

See §5 for the full design.

### 10.3 Conflict 3 — R6's `LightingModule`

R6's module-scaffold example included a `LightingModule` mounting
AmbientLight + DirectionalLight + env_map controls. Per §10.2, those
are dead knobs.

**Resolution: replace with two narrower modules.**

- **PanoramaModule** (`stateKey: panorama_backdrop`) owns image upload
  + rotation + intensity.
- **PostFXModule** (`stateKey: postprocessing`) owns tonemapping +
  exposure.

One module per stateKey (matches R6's contract; no spanning modules).

See §4.5 + §4.6.

### 10.4 Conflict 4 — R4 explicit-save vs R6 auto-save hook

- **R4** strongly recommended explicit-save only (no debounce);
  matches SuperSplat / three.js / Premiere model + avoids slider-drag
  save bursts + multi-tab conflict-resolution surface.
- **R6** §5 mentioned an `onCfgChange()` hook that could debounce and
  trigger save.

**Resolution: R4 wins for v1.** Explicit save only. The `onCfgChange()`
hook stays in the contract (modules need it for inter-module reactions
that don't involve I/O — e.g. CutsModule re-evaluating clip boundaries
when CameraPathModule edits a camera's `start_view`). It just doesn't
trigger network I/O in v1. Auto-save toggle deferred to a future phase
(documented; the contract is ready).

See §7.3.

---

## 11. Open questions [USER-CONFIRM]

1. **`fehmarn` slug consolidation** — the current site shows "fehmarn"
   but CDN slug is "kf-fehmarn"; are these intended to be the same
   scene, or distinct (older vs newer build)? If same: which slug
   wins; do we redirect `<cdn>/fehmarn` → `<cdn>/kf-fehmarn` (Bunny
   redirect rule)? (R5 §10 Q5)
2. **Panorama asset provenance per scene** — for each of the 8
   scenes, is the backdrop:
   (a) drone/raw imagery available;
   (b) phone 360° on-location capture needed;
   (c) AI-synthesised equirect; or
   (d) stock HDRI? The asset pipeline (§8.5) takes ~30 min for (a),
   ~2 hours for (b/c). Confirm per scene. (R5 §10 Q1)
3. **Audio asset provenance per scene** — same question for tracks:
   user-supplied per scene, ambient stock loop, or no audio in v1 for
   any scene that doesn't have a track yet? (Default recommended: no
   audio unless author provides; R5 §10 Q6)
4. **PHP save backend secret storage** — Phase 3 needs per-scene
   `.author-token` files on geddart.de. Store as raw secret or
   sha256(secret)? (R5 §7.1 default: sha256 hex on the server, raw in
   the URL fragment. Confirm.)
5. **Author session bookmark format** — `<slug>/index.html?author=1#author=<secret>`
   per R4. Confirm the fragment param name (`#author=` vs `#token=`)
   — R4 uses `#author=`; R5 uses `#token=`. Pick one and freeze.
6. **Cuts UX visual** — timeline lane shows clips as per-camera
   coloured blocks (§4.3). Confirm: clip "trigger annotations across
   cut boundaries" semantics — does an annotation `t_out=10s` survive
   into the next clip if the clip ends at `t=8s` (current ClipPlayer
   behaviour) or is it clipped to the clip end (proposed v1 behaviour)?
7. **Phase ordering** — R5 proposes editor + schema rollout first
   (Phases 1-2), then backend switch (Phase 3). The plan in
   `docs/superpowers/plans/2026-05-20-editor-arc.md` follows this.
   Confirm OK — or does the user want PHP backend live for kf-fehmarn
   simultaneously with the first editor rollout?
8. **Cloudflare Worker backend** — skip in v1 (per non-goals §0)? The
   stub in `save_backends/cloudflare.py` stays; no rollout activity.

### 11.A Resolved by addendum 2026-05-20

These questions were raised by the user's verbatim voice 2026-05-20
17:09 and are CLOSED by the §Spec addenda block (top of spec) + §3.7 +
§4.1.1 + §6.5.1:

- **Timeline scrub ceiling beyond last keyframe** — resolved via the
  new optional `PathDict.total_duration_s` field (§3.7) and the
  total-time + auto-toggle transport controls (§4.1.1).
- **Prev/Next-keyframe skip affordance** — resolved via the `|◀` /
  `▶|` transport buttons + `Ctrl+Left` / `Ctrl+Right` hotkeys
  (§4.1.1 + §6.5.1).

---

## 12. Provenance

This spec is a synthesis of 8 parallel research reports
(`R1_external_ux_refs.md` through `R8_undo_redo.md`) under
[docs/superpowers/research/2026-05-20-editor-arc/](../research/2026-05-20-editor-arc/).

| Report | Topic | Key contribution to this spec |
|---|---|---|
| R1 | External UX refs | 10 distilled patterns (§1); command-pattern was the standard pro recommendation (§10.1) |
| R2 | Current arch audit | The 9-fragment scaffold inventory + gap map (§2.1) |
| R3 | Wire schema | Initial schema with `lighting` block (deprecated to §10.2) + `panorama_backdrop` block (kept §3.2) + `schema_version` (kept §3.1) |
| R4 | Save backend hardening | Explicit-save + URL fragment + 413 fallback + offline draft (§7) |
| R5 | Multi-scene rollout | Per-scene cadence + .kfwork retirement + asset pipeline timings (§8) |
| R6 | Editor module scaffold | EditorModule contract + EditorModuleRegistry coordinator + multi-lane timeline (§2.2-2.4, §4.10) |
| R7 | Lighting + panorama | "Splats are pre-lit" finding (§5) — drives §10.2 and §10.3 resolutions |
| R8 | Undo / redo | Snapshot ring buffer + 5 MB worst case + gesture-start commit (§6) |

Cross-cites are interleaved throughout the spec at the points the
specific report's reasoning applies. The 4 conflicts each get their own
named section in §10.
