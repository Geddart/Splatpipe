# Splatpipe Editor Architecture — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL:
> `superpowers:subagent-driven-development`. Steps use `- [ ]` syntax
> for tracking; check off as each lands.
>
> **Spec:** [docs/superpowers/specs/2026-05-20-editor-arc-design.md](../specs/2026-05-20-editor-arc-design.md)
>
> **Estimated effort:** ~12 hours dev (asset creation dominates per R5 §9).
> Phases 1-3 are the critical path to "smooth iterative authoring"; 4-7
> are per-feature editor modules; 8-9 are per-scene authoring + polish.

---

## Overview

9 phases, each independently shippable. Each phase ends with a green
test suite + a live verify cycle (Playwright pixel-check on a deployed
slug, never just a derived number — see CLAUDE.md "viewer/harness
verification" hard rules).

| Phase | Scope | Files touched | Effort |
|---|---|---|---|
| 1 | EditorModule contract + EditHistory + refactor 3 existing modules | 8 files + 2 new fragments + 2 new tests | ~3 h |
| 2 | Panorama backdrop module + PostFX module + new upload-image route | 6 files + 1 new route + 3 new tests | ~2 h |
| 3 | PHP save backend rollout per-scene (Phase 1 of save-backend cadence) | 0 code changes (mostly config + deploy) | ~1 h + per-scene authoring |
| 4 | Annotation editor (in-viewer authoring) | 2 fragments + 1 module + 2 tests | ~1.5 h |
| 5 | Cuts editor (refactor ClipPlayer into edit-time) | 1 fragment + 1 module + 2 tests | ~1.5 h |
| 6 | Audio editor | 1 fragment + 1 module + 2 tests | ~1 h |
| 7 | Titles3D editor + renderer | 2 fragments + 1 module + 2 tests | ~1.5 h |
| 8 | Per-scene authoring (7 remaining scenes after kf-fehmarn) | per-scene assets + `splatpipe publish` × 7 | ~8 h |
| 9 | Polish + release v0.8.0 | CHANGELOG + CLAUDE.md + release notes | ~30 min |

---

## Phase 1 — Foundation (EditorModule contract + EditHistory + module refactor)

**Goal:** No new user-visible features beyond the 2026-05-20 addenda
trio (timeline total-duration decoupling + total-time input/auto +
prev/next keyframe buttons & hotkeys). The existing 9 fragments using
the SceneView scaffold are refactored onto the new `EditorModule`
contract; the EditHistory ring buffer is added; Ctrl+Z/Y work for
the 3 refactored modules. All 7 deployed scenes still render
byte-identical (output-pin invariant from #118 modularization).

> **Addendum 2026-05-20 — user authoring feedback round 1.** Steps
> 1.7a / 1.7b / 1.7c carry the three timeline-UX additions surfaced
> by the user's voice 2026-05-20 17:09 after testing the UX-5
> band-aid commit (`491faa8`). They are Phase-1-scoped because they
> are CameraPathModule additions and ship alongside the EditHistory
> contract that handles their undo semantics. See spec §3.7 + §4.1.1
> + §6.5.1.

Sub-skills needed: `superpowers:test-driven-development`,
`superpowers:verification-before-completion`.

### Steps

- [ ] **1.1 Create the EditorModule + EditorModuleRegistry fragment.**
      New file `src/splatpipe/viewers/spark/template_parts/04a_editor_module.js_tmpl`
      (~150 lines). Defines `class EditorModule` (the ABC shape from
      spec §2.2) + `class EditorModuleRegistry` (spec §2.3). Wire
      `window.__editorRegistry` for the Playwright test surface.
- [ ] **1.2 Create the EditHistory fragment.** New file
      `src/splatpipe/viewers/spark/template_parts/17a_edit_history.js_tmpl`
      (~60 lines). Defines `class EditHistory` (spec §6.1, §6.2).
      Wire `window.__editHistory`.
- [ ] **1.3 Register the fragments.** Edit
      `src/splatpipe/viewers/spark/template_parts/__init__.py` to
      include the 2 new fragments at the correct positions (`04a` after
      `04`, `17a` after `17`).
- [ ] **1.4 Wire the registry into SceneView.** Edit
      `05_framework.js_tmpl` so `SceneView` instantiates the registry on
      construction. The registry is dormant until modules register
      themselves.
- [ ] **1.5 Wire Ctrl+Z / Ctrl+Y / Ctrl+Shift+Z.** Edit
      `05_framework.js_tmpl` (or `08_input.js_tmpl` — whichever owns
      keyboard binding routing today). Hook into `InteractionManager`.
      Toast on undo/redo.
- [ ] **1.6 Add undo/redo buttons.** Edit `03_body_chrome.html_tmpl` to
      add ↩ ↪ buttons in `_tlBarRow` next to the existing transport.
      Disabled-state CSS in `02b_styles_editor.css_tmpl`.
- [ ] **1.7 Refactor CameraPathModule.** Wrap the existing logic in
      `15_editor_trajectory.js_tmpl` + `16_editor_timeline.js_tmpl` +
      `17_editor_gizmo.js_tmpl` into a `CameraPathModule` class
      conforming to the contract. Behaviour preserved byte-for-byte.
      `stateKey: ["camera_paths", "default_path_id", "start_view"]`.
      Wire `beginGesture("kf-drag")` at diamond-drag start +
      `endGesture()` at mouseup.
- [ ] **1.7a Add `PathDict.total_duration_s` schema field
      (addendum 2026-05-20; spec §3.7).** Edit
      `src/splatpipe/core/path_io.py:PathDict` to add
      `total_duration_s: float | None` (optional, default-absent).
      Update `new_path()` to NOT set it (back-compat: absent = auto).
      Add a small validator-style helper
      (`path_io.py:effective_duration(path)`) returning the derived
      scrub-range ceiling per the §3.7 rule. Update
      `tests/test_path_io.py` (new test or extension) to cover the
      auto / manual / fallback branches.
- [ ] **1.7b Total-time input + auto toggle in `_tlBarRow`
      (addendum 2026-05-20; spec §4.1.1).** Edit
      `03_body_chrome.html_tmpl` to add the number-input + unit-label
      (`[ NN ] s total`) and the small `auto` / `manual` toggle button
      in the transport row. Edit `16_editor_timeline.js_tmpl` (and/or
      the CameraPathModule glue from 1.7) so the scrub-range ceiling
      reads `effective_duration(path)`; on commit (`onBlur` / Enter)
      the input writes `path.total_duration_s` AND pushes ONE
      EditHistory snapshot. Auto-toggle click writes `null` (auto) or
      the current input value (manual) and ALSO pushes ONE snapshot.
      Style block in `02b_styles_editor.css_tmpl`.
- [ ] **1.7c Prev/Next-keyframe skip buttons + hotkeys
      (addendum 2026-05-20; spec §4.1.1 + §6.5.1).** Edit
      `03_body_chrome.html_tmpl` to add the `|◀` / `▶|` buttons in
      `_tlBarRow` adjacent to play/pause. Wire to CameraPathModule
      handlers that compute the sorted-by-`t` keyframe view and jump
      the playhead to the strict-less-than / strict-greater-than
      neighbour (fallbacks: `t=0` / `total_duration_s` per §4.1.1).
      Wire `Ctrl+Left` / `Ctrl+Right` (with `event.metaKey ||
      event.ctrlKey` for Mac parity) in `InteractionManager`. These
      do NOT push undo entries (navigation, not edit). Add a small
      Playwright probe in the contract test (1.12) confirming the
      window-exposed CameraPathModule has `jumpPrevKf()` /
      `jumpNextKf()` methods that move `window.__playhead.time`.
- [ ] **1.8 Refactor AnnotationModule (render-only stub).** The viewer-
      side annotation render path (in `06_cfg.js_tmpl` or
      `07_setup_three_spark.js_tmpl` — verify with Grep before editing)
      wraps in an `AnnotationModule` stub. Authoring is Phase 4.
      `stateKey: "annotations"`.
- [ ] **1.9 Refactor CutsModule (render-only stub).** Same — wrap
      `11_clip_player.js_tmpl` in a `CutsModule` stub.
      `stateKey: ["clips", "cameras"]`. Authoring is Phase 5.
- [ ] **1.10 Update the output-pin.** Run `pytest tests/test_html_for_output_pin.py`
      (the byte-lock test from #118). Re-baseline the output-pin: all
      7 deployed scenes must regenerate the SAME `index.html` bytes
      from the new fragment layout. If bytes differ, one of the
      refactors leaked a non-additive change.
- [ ] **1.11 Add EditHistory tests.** New file
      `tests/test_edit_history.py`. Node-driven (mirrors
      `test_spcp_js_port.py` pattern): commit / undo / redo / capacity
      eviction / clear-on-mode-switch.
- [ ] **1.12 Add EditorModule contract test.** New file
      `tests/test_editor_module_contract.py`. Playwright probe of
      `window.__editorRegistry.list().forEach(m => assert all required props)`.
- [ ] **1.13 Run full pytest + ruff.** Expect green; expect the test
      count to bump by 2 new test files. Update `CLAUDE.md` test count
      line + `README.md` badge if changed.
- [ ] **1.14 Live verify (no new feature).** Playwright cold-load each
      of the 7 deployed slugs in `enduser` mode + `embed` mode + cold
      `?author=1`. Confirm pixel-identical (or at-least visually
      indistinguishable) to pre-Phase-1 screenshots; confirm Ctrl+Z
      works after a drag on `kf-fehmarn`. Additionally (addendum
      2026-05-20): on `kf-fehmarn ?author=1` confirm the scrub bar can
      be dragged past `last_kf.t` when `total_duration_s` is set
      manually (e.g. 30 s); confirm `Ctrl+Left` / `Ctrl+Right` jump
      between recorded keyframes; confirm auto-toggle round-trips
      between `null` and the entered value without breaking the scrub
      range.
- [ ] **1.15 Commit + push.** Commit message starts
      `feat(editor): phase 1 — EditorModule contract + EditHistory`.

### Output

A green test suite (~715-717 tests if pytest was 713). All 7 deployed
scenes render byte-identical (modulo the transport-row additions
from 1.7a-c). Ctrl+Z works on a camera-path keyframe drag in
kf-fehmarn. Only user-visible additions are the 2026-05-20 addenda
trio (total-time input + auto toggle + prev/next keyframe buttons +
`Ctrl+Left` / `Ctrl+Right` hotkeys); they unblock the
"author-needs-to-scrub-past-last-kf" workflow. The contract +
history are the platform every subsequent phase builds on.

---

## Phase 2 — Panorama backdrop + PostFX module

**Goal:** New `panorama_backdrop` block in the schema. PanoramaModule
+ PostFXModule render + edit. Per-scene panorama upload works on
kf-fehmarn end-to-end.

### Steps

- [ ] **2.1 Schema additions.** Edit
      `src/splatpipe/core/config_safety.py`: append
      `"panorama_backdrop"` + `"schema_version"` to
      `PUBLIC_VIEWER_CONFIG_KEYS`. Edit
      `src/splatpipe/core/config_merge.py`: append
      `"panorama_backdrop"` + `"postprocessing"` to
      `ALLOWED_PATCH_KEYS`. (Audio comes in Phase 6.)
- [ ] **2.2 publish_scene writes the schema marker.** Edit
      `src/splatpipe/steps/publish.py` so `publish_scene()` always
      writes `schema_version: 1` and a default `panorama_backdrop:
      {url: null, rotation_deg: 0, intensity: 1.0}` block if absent.
      Idempotent for scenes that already have it.
- [ ] **2.3 PanoramaModule render path.** Edit
      `07_setup_three_spark.js_tmpl`: equirect JPG load →
      `THREE.PMREMGenerator` → cubemap → `scene.background`. Honour
      `panorama_backdrop.intensity` via `scene.backgroundIntensity`.
      Skip cleanly when `url: null`. Mobile fallback to 2K equirect if
      `window.devicePixelRatio * viewport area` exceeds a heuristic
      threshold.
- [ ] **2.4 PanoramaModule editor UI.** Edit `03_body_chrome.html_tmpl`
      to add a collapsible `Panorama` panel in `author-root`. File
      picker; rotation slider `[0..360]`; intensity slider `[0..2]`;
      tooltip from spec §5.4.
- [ ] **2.5 PostFXModule editor UI.** Same panel area: `Post-FX`
      section with tonemapping dropdown + exposure slider. No new
      renderer code (`cfg.postprocessing.*` is already read).
- [ ] **2.6 PanoramaModule class.** Glue class conforming to
      EditorModule contract. `stateKey: "panorama_backdrop"`.
      `onCfgChange` re-uploads texture if `url` changed; re-rotates if
      `rotation_deg` changed; re-sets `scene.backgroundIntensity` if
      `intensity` changed.
- [ ] **2.7 PostFXModule class.** Same. `stateKey: "postprocessing"`.
      `onCfgChange` updates the renderer's tonemapping/exposure
      uniforms.
- [ ] **2.8 Register both modules.** In `05_framework.js_tmpl`'s
      SceneView init.
- [ ] **2.9 New upload-image route.** New file
      `src/splatpipe/web/routes/upload_image.py`. Mirror
      `web/routes/projects.py:upload_audio` (the bug-audit #7 hardened
      pattern): MIME filter `{image/jpeg, image/png}`, size cap 20 MB,
      `core/path_safety.ensure_contained()` gate to
      `<project>/05_output/assets/`. Mount in `web/app.py`.
- [ ] **2.10 publish bundles assets/.** Edit `publish.py` so the staged
      output includes `<slug>/assets/*` when `<project>/05_output/assets/`
      is non-empty. Test fixture: a known good 256-byte test JPG.
- [ ] **2.11 New tests.**
      - `tests/test_image_upload_security.py` — mirror
        `test_audio_upload_security.py` (path traversal, MIME, size
        cap).
      - `tests/test_panorama_backdrop_schema.py` — sanitiser + merge
        accept the new keys; older configs without the keys still pass.
      - `tests/test_publish_schema_version.py` — `publish_scene` writes
        `schema_version: 1` into every output cfg.
- [ ] **2.12 Extend sanitiser + merge tests.** Update
      `tests/test_publish_config_sanitize.py` +
      `tests/test_config_merge.py` for the 2 new public keys + 2 new
      patch keys.
- [ ] **2.13 Run full pytest + ruff.**
- [ ] **2.14 Live verify on kf-fehmarn.**
      Upload a test pano via the dashboard → publish → cold-load
      `<cdn>/kf-fehmarn/?author=1` and confirm the backdrop renders.
      A/B verify with the existing scene (no backdrop) — both should
      render correctly with the runtime defaults.
- [ ] **2.15 Update CHANGELOG.md.** Add a `### Added` entry under
      `[Unreleased]`.
- [ ] **2.16 Commit + push.**

### Output

kf-fehmarn renders a panorama backdrop loaded via the editor. The new
`schema_version: 1` marker is present in every output cfg. PostFX
sliders work in the author panel. Other 7 scenes unaffected (no
backdrop URL set; default null → no upload).

---

## Phase 3 — PHP save backend per-scene rollout (Phase 1 of R5 cadence)

**Goal:** All 8 scenes carry the v1 schema (incl. the new
`panorama_backdrop` block); 1 scene (kf-fehmarn) is the first to
flip from `save_mode="cli"` to `save_mode="http"` and prove the
PHP backend end-to-end. The 7 other scenes ship in `cli` mode and
get edits via the existing token-paste flow.

Sub-skills needed: `superpowers:verification-before-completion`.

### Steps

- [ ] **3.1 Confirm PHP adapter is live on geddart.de.** Curl the
      endpoint; confirm it returns the existing `OK` response on a
      health check. (Per R4 §1: the adapter is fully implemented +
      tested.)
- [ ] **3.2 Provision per-scene `.author-token` files.** For each of
      the 8 slugs, generate a 256-bit secret + write its sha256 hex to
      `geddart.de:/srv/geddart.de/save/scenes/<slug>/.author-token`
      (per R5 §7.2 step 1). Store the raw secrets in the user's
      password manager (NEVER in this repo). The `.secrets/` folder
      is gitignored; if used for staging, NEVER commit.
- [ ] **3.3 Per-scene `splatpipe publish` (in the R5 cadence order):**
      1. [ ] `kf-fehmarn`
      2. [ ] `fehmarn` (alias consolidation; see open question §11.1
         in the spec)
      3. [ ] `ibug`
      4. [ ] `speicher`
      5. [ ] `polygraf`
      6. [ ] `polygraf-east`
      7. [ ] `fabrik`
      8. [ ] `stettiner`
      9. [ ] `methtrailer`

      Each publish:
      - confirms the live config inherits via `_fetch_live_config()`;
      - the sanitiser drops anything outside the allow-list;
      - the post-process writes `schema_version: 1` + empty
        `panorama_backdrop` + (where missing) `clips: []`, `cameras: []`,
        `titles3d: []`;
      - Bunny Edge Rules re-applied;
      - per-scene cold-load Playwright pixel-check (PASS = scene
        renders correctly in `enduser` + `embed` modes).
- [ ] **3.4 Flip kf-fehmarn save_mode to http.** Edit kf-fehmarn's
      project config: `save_backend.type = "http"`,
      `save_backend.endpoint = "https://geddart.de/save-camera.php"`.
      Re-publish. Cold-load with `#author=<secret>` fragment; make a
      trivial edit (add a single annotation at the playhead); hit Save;
      confirm the POST round-trips (200 OK + the new annotation
      visible after `viewer-config.json` is re-fetched).
- [ ] **3.5 Retire the 5 `.kfwork/deploy_kf_fehmarn*.py` scripts.**
      `git rm` them + the `.kfwork/stage_kf_fehmarn*/` dirs +
      `.kfwork/live_*.json` + `.kfwork/live_*.html`. Confirm
      `.kfwork/check_markers.py` (the byte-lock checker) is now
      redundant (covered by `test_html_for_save_mode.py`); `git rm`
      that too. Update `CLAUDE.md` "Known Limitations / TODO" entry.
- [ ] **3.6 413 fallback live test.** Load kf-fehmarn `?author=1`,
      somehow exceed the body cap (artificially: paste a 100 MB
      annotation `text`). Confirm the viewer auto-falls back to the
      CLI clipboard path + a clear toast.
- [ ] **3.7 Document save secrets in CLAUDE.md / user secrets.**
      Briefly: secret rotation procedure (overwrite the `.author-token`
      file + update password manager).
- [ ] **3.8 Update CHANGELOG.md.**
- [ ] **3.9 Commit + push.** Two commits ideally: one
      `feat(editor): phase 3a — all 8 scenes carry v1 schema` and
      one `feat(editor): phase 3b — kf-fehmarn flips save_mode to http`.

### Output

All 8 scenes carry `schema_version: 1`. `.kfwork/` is retired (this is
the formal "no more bespoke deploys" line). kf-fehmarn can save edits
via POST to geddart.de. Other 7 scenes still save via the CLI token-
paste path (unchanged from today). The save-backend phased rollout
(remaining 7 → http) is deferred to a future iteration; this phase
proves the path on one scene.

---

## Phase 4 — Annotation editor (in-viewer authoring)

**Goal:** Click-in-3D to place an annotation; double-click to edit
text; drag to reposition; timeline lane shows `t_in..t_out` bars;
kebab → delete. Round-trip via the save flow (cli or http).

### Steps

- [ ] **4.1 AnnotationModule authoring UI.** Edit the
      `AnnotationModule` from Phase 1.8 to add author-mode entrypoints:
      - "+ Add Annotation" button in `author-root` → click-in-3D mode
        (next 3D click captures the world position + opens an inline
        text input).
      - Double-click an existing dot → opens the text input pinned at
        the dot's screen position.
      - Drag the dot → reposition (uses `OverlayScene`; `beginGesture`
        / `endGesture` wraps the drag).
      - Kebab menu on each dot → Delete (with `beginGesture("ann-del")`
        snapshot first).
- [ ] **4.2 Raycast helper.** Splat-aware raycaster: cast against the
      bounding box / depth buffer of the splat scene; pick the
      surface-most hit (so the annotation lands ON something visible).
      Fallback to a fixed-distance plane if no hit.
- [ ] **4.3 Multi-lane timeline integration.** Edit
      `16_editor_timeline.js_tmpl` to add an annotations lane (16 px
      height; one thin coloured bar per annotation at `t_in..t_out`).
- [ ] **4.4 Annotation triggers across cut boundaries.** The master
      playhead's annotation-trigger eval reads clip-local time when
      cuts are present (Phase 5 contract). For Phase 4 (no cuts in
      most scenes), master time = clip time = playhead time.
- [ ] **4.5 Annotation editor tests.**
      - `tests/test_annotation_module_editor.py` — Playwright probe of
        the click-in-3D / drag / delete flows; verify each emits the
        expected EditHistory snapshot + the expected SPCP1 patch.
- [ ] **4.6 Live verify.** Create + reposition + delete an annotation
      on kf-fehmarn `?author=1`; Save (http mode now); reload; verify
      it persisted.
- [ ] **4.7 Update CHANGELOG.md. Commit + push.**

### Output

End-to-end annotation authoring works. Annotations save via either
backend. Timeline lane shows their lifetimes. Undo works on each
gesture.

---

## Phase 5 — Cuts editor (refactor ClipPlayer into edit-time)

**Goal:** Author-mode editing of `clips` + `cameras`. Timeline lane
shows per-camera coloured clip blocks; drag to reorder / retime;
click to select; delete. Existing enduser/embed playback unchanged.

### Steps

- [ ] **5.1 CutsModule authoring UI.** Edit the `CutsModule` stub
      from Phase 1.9 to add author-mode entrypoints:
      - "+ Add Camera" → spawn a new camera entry in `cameras`
        (color-picked).
      - "+ Add Clip" at playhead → insert a clip from the currently
        selected camera at the master playhead position.
      - Drag clip body → reorder.
      - Drag clip edges → retime (`beginGesture("clip-retime")`).
      - Click → select; Delete key → remove.
- [ ] **5.2 Per-camera color assignment.** Each new camera gets a
      stable color (the existing per-camera color logic if one exists,
      or a deterministic hash → palette).
- [ ] **5.3 Master-time → clip-local-time evaluator.** Helper that
      maps the master playhead to `(clipId, clipLocalT)`. Exposes
      `playhead.localTime` for the AnnotationModule / AudioModule to
      consume.
- [ ] **5.4 Multi-lane timeline.** Cuts lane shows clip blocks at 24 px
      height; per-camera color stripes.
- [ ] **5.5 Existing playback unchanged.** The viewer-side playback
      path in `11_clip_player.js_tmpl` continues to drive enduser /
      embed mode. Only author-mode adds new chrome.
- [ ] **5.6 Tests.**
      - `tests/test_cuts_module_editor.py` — add / reorder / retime /
        delete; verify SPCP1 patch shape.
- [ ] **5.7 Live verify.** Take kf-fehmarn (which has 1 camera /
      no clips today) → add a second camera at a different start_view
      → add 2 clips that cut between them → Save → reload → verify
      enduser mode plays the cut sequence.
- [ ] **5.8 Update CHANGELOG.md. Commit + push.**

### Output

Multi-camera cut sequences are authorable. kf-fehmarn (or any scene)
can have a 2-camera cut authored in-viewer.

---

## Phase 6 — Audio editor

**Goal:** Per-track audio with volume / loop / in/out timing + optional
positional source position. Timeline lane shows audio blocks.

### Steps

- [ ] **6.1 Allow-list audio in patches.** Edit
      `core/config_merge.py:ALLOWED_PATCH_KEYS` — append `"audio"`.
- [ ] **6.2 AudioModule.** New module; `stateKey: "audio"`.
- [ ] **6.3 AudioModule editor UI.**
      - "+ Add Track" → file picker → upload via existing
        `/upload-audio` route (hardened in audit #7).
      - Per-track: volume slider, in/out time inputs, positional
        toggle, position picker (click-in-3D when positional).
- [ ] **6.4 Audio render path.** Wire `THREE.AudioListener` +
      `Audio` / `PositionalAudio` based on `kind`. Schedule playback
      against the master playhead's `t_in..t_out`.
- [ ] **6.5 Multi-lane timeline.** Audio lane: per-track row; bar
      height encodes volume. 20 px height.
- [ ] **6.6 Tests.**
      - `tests/test_audio_module_editor.py` — track CRUD + SPCP1
        patch shape.
      - `tests/test_audio_module_render.py` — playhead-driven
        scheduling (Node-driven).
- [ ] **6.7 Live verify.** Add an ambient track to kf-fehmarn; Save;
      reload; confirm playback starts at the right `t_in`.
- [ ] **6.8 Update CHANGELOG.md. Commit + push.**

### Output

Audio editing works on kf-fehmarn. The patch path round-trips correctly.

---

## Phase 7 — Titles3D editor + renderer

**Goal:** Render 3D text titles in the scene (CSS3DObject or canvas
sprite). Author via click-in-3D + text input + color/size sliders +
t_in/t_out.

### Steps

- [ ] **7.1 Titles3D renderer.** New fragment
      `src/splatpipe/viewers/spark/template_parts/14a_titles_3d.js_tmpl`
      (~80 lines). Render `cfg.titles3d` as CSS3DObjects (with
      canvas-sprite fallback for Safari/iOS where CSS3DRenderer is
      known-broken). Attach to OverlayScene.
- [ ] **7.2 TitlesModule.** New module; `stateKey: "titles3d"`.
- [ ] **7.3 Authoring UI.**
      - "+ Add Title" → click-in-3D mode → place title at hit point →
        opens inline text + color/size editor.
      - Drag title in OverlayScene → reposition.
      - Kebab → delete.
- [ ] **7.4 Multi-lane timeline.** Titles lane: 16 px height; per-title
      white bars.
- [ ] **7.5 Tests.**
      - `tests/test_titles_module_editor.py` — CRUD + patch shape.
      - `tests/test_titles_render.py` — render correctness against a
        known title list.
- [ ] **7.6 Live verify.** Add intro + outro titles to kf-fehmarn;
      verify they appear at the right times in enduser mode.
- [ ] **7.7 Update CHANGELOG.md. Commit + push.**

### Output

Titles render + edit. kf-fehmarn now has the full v1 cinematic shell
toolset working end-to-end.

---

## Phase 8 — Per-scene authoring (7 remaining scenes)

**Goal:** Each of the 7 scenes beyond kf-fehmarn gets a full
authoring pass — panorama (if available), audio (if available),
camera paths, optional cuts/annotations/titles.

Sub-skills needed: `superpowers:dispatching-parallel-agents` (one
agent per scene if assets are pre-staged); otherwise sequential.

### Steps (per scene, in the R5 §2.1 order)

For each slug in `[fehmarn, ibug, speicher, polygraf, polygraf-east,
fabrik, stettiner, methtrailer]`:

- [ ] **8.S.1 Provision panorama asset.** Per R5 §8.1: source equirect
      or capture / synthesise. Resize to 4K JPG; upload via
      dashboard `/upload-image` → ends up at
      `<project>/05_output/assets/backdrop.jpg`.
- [ ] **8.S.2 Provision audio (if applicable).** Upload via
      `/upload-audio`; pick volume / loop / positional defaults.
- [ ] **8.S.3 Author camera paths.** Open `?author=1`; record or
      hand-author camera-path keyframes; smoothness + speed sliders;
      mark a default path.
- [ ] **8.S.4 Author cuts (if multi-camera).** Most scenes are
      single-camera; skip for those.
- [ ] **8.S.5 Author annotations.** 1-3 markers per scene per R5 §9
      estimate; ~5 min per scene.
- [ ] **8.S.6 Author titles.** Intro + outro (or skip per scene).
- [ ] **8.S.7 Save + verify.** Token-paste relay via
      `splatpipe set-camera-path` (still `cli` mode at this phase);
      reload; cold-load Playwright pixel-check.
- [ ] **8.S.8 Edge Rule re-verify.** `curl -I
      <cdn>/<slug>/viewer-config.json` → `cdn-cache: BYPASS`.
- [ ] **8.S.9 Update CHANGELOG.md note (per-scene rollout milestone).**

After all 7 scenes complete:

- [ ] **8.X Final CHANGELOG entry.** A `### Added` entry capturing the
      multi-scene rollout milestone.
- [ ] **8.X Commit + push.**

### Output

All 8 scenes carry authored cinematic content. The
`splatpipe-cdn.b-cdn.net/<slug>/` URLs each present a polished
end-user experience with backdrop + camera-path + (where authored)
annotations + cuts + audio + titles.

---

## Phase 9 — Polish + finalize v0.8.0 release

**Goal:** Ship-ready. Documentation reconciled; CHANGELOG complete;
test count current; release notes drafted.

### Steps

- [ ] **9.1 Editor-module test surface.** Confirm every module exposes
      `window.__editor.<name>` for Playwright. Add the registry-level
      `list()` probe to the existing harness coverage.
- [ ] **9.2 Mobile editor restriction.** Author mode forced to desktop
      viewport ≥ 1024 px wide. Mobile cold-loads `?author=1` see a
      "Editor only on desktop" toast + fallback to enduser mode.
- [ ] **9.3 Accessibility pass.** Tab-order through editor panels;
      ARIA labels on the timeline canvas; keyboard equivalents for the
      core gestures (Up/Down for keyframe step; arrow keys for
      annotation reposition with selection).
- [ ] **9.4 CLAUDE.md reconciliation.**
      - Update Package Layout to add the 2 new fragments + new modules.
      - Update test count line.
      - Document the EditorModule contract briefly in "Critical Code
        Patterns".
      - Document the EditHistory ring-buffer + ephemeral semantics.
- [ ] **9.5 README.md.** Update test badge if changed; mention the
      editor in the "Quick Start" if appropriate.
- [ ] **9.6 CHANGELOG.md.** Move `[Unreleased]` → `[0.8.0]` section.
      Drafted entries from each phase.
- [ ] **9.7 Bump pyproject.toml.** `version = "0.8.0"`.
- [ ] **9.8 Final verify.**
      - `pytest tests/ -v` → green.
      - `ruff check src/ tests/` → green.
      - Cold-load all 8 deployed slugs → all render correctly.
- [ ] **9.9 Commit `Release v0.8.0`.**
- [ ] **9.10 Tag + push.** `git tag v0.8.0; git push origin
      feat/camera-keyframe-editor --tags`.
- [ ] **9.11 Open PR** (or merge if user prefers direct).
- [ ] **9.12 GitHub Release.** `gh release create v0.8.0 --title
      "v0.8.0" --notes "<paste CHANGELOG>"`.

### Output

v0.8.0 released. All 8 scenes editable in-viewer. Editor module contract
+ snapshot undo + new panorama + http save backend (per kf-fehmarn) all
shipped.

---

## Test count expectations

| Phase | New tests | Cumulative test count (approx; baseline 713) |
|---|---:|---:|
| Baseline | — | 713 |
| Phase 1 | +2 (history, contract) + extension of `test_path_io.py` for `total_duration_s` (addendum 2026-05-20) | ~715-717 |
| Phase 2 | +3 (img upload, pano schema, pub schema_version) | 718 |
| Phase 3 | 0 (rollout, not code) | 718 |
| Phase 4 | +1 (annotation editor) | 719 |
| Phase 5 | +1 (cuts editor) | 720 |
| Phase 6 | +2 (audio editor + render) | 722 |
| Phase 7 | +2 (titles editor + render) | 724 |
| Phase 8 | 0 (authoring, not code) | 724 |
| Phase 9 | 0 (polish) | 724 |

(Per CLAUDE.md "viewer/harness verification" hard rule 6: spec-mandated
real tests legitimately raise the count.)

---

## Risk register

| Risk | Mitigation |
|---|---|
| Output-pin baseline breaks unexpectedly in Phase 1 | Each refactor preserves behaviour byte-for-byte; if pin breaks, isolate which sub-step (1.7-1.9) introduced the delta. |
| Cross-origin chunks (the recurring trap per CLAUDE.md "viewer / harness verification" rule 1) | All Phase 2-9 live verify happens on deployed Bunny slugs (same-origin), not local harnesses with cross-origin chunk fetch. |
| 413 fallback never tested live until Phase 3.6 | Phase 3.6 forces a 413 with an artificial payload + verifies the toast + clipboard path. |
| Per-scene asset provenance unclear (spec open question §11.2) | Phase 8 is per-scene; one scene with no panorama just keeps `url: null` (renderer skips). Authoring proceeds per scene as assets become available. |
| Annotation click-in-3D raycast misses for some scenes (no clean depth) | Fallback: fixed-distance plane in front of camera. Phase 4.2 implements + tests. |
| Two-tab concurrent save (LWW) loses an annotation | Property-granular LWW (spec §7.7) — different keys don't conflict. Same-key conflicts: last save wins. Documented; not a v1 mitigation target. |
| Mobile author mode accidentally exposed | Phase 9.2 explicitly blocks; documented in CLAUDE.md UX section. |

---

## Verification of this plan

- Spec cross-references in §2-9 all map to a real `template_parts/`
  fragment or `core/` module (verified via Glob against HEAD `491faa8`).
- The phased order respects the modularization output-pin invariant
  (#118) — Phase 1 explicitly re-baselines the pin.
- Per CLAUDE.md "viewer / harness verification" rule 2: each phase has
  a real-pixels live verify step (NOT just derived-number checks).
- The 4 conflict resolutions in the spec (R1↔R8, R3↔R7, R6 module
  reshape, R4↔R6 auto-save) flow into specific module / phase steps:
  - R1↔R8 → Phase 1.2 (EditHistory fragment).
  - R3↔R7 → Phase 2 (no `lighting` block; PanoramaModule + PostFXModule
    only).
  - R6 reshape → Phase 2.6/2.7 (PanoramaModule + PostFXModule, NOT
    LightingModule).
  - R4↔R6 → Phase 1 contract definition (no auto-save in MVP).
