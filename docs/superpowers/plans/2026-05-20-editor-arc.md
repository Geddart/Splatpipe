# Splatpipe Editor Architecture — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL:
> `superpowers:subagent-driven-development`. Steps use `- [ ]` syntax
> for tracking; check off as each lands.
>
> **Spec:** [docs/superpowers/specs/2026-05-20-editor-arc-design.md](../specs/2026-05-20-editor-arc-design.md)
>
> **Estimated effort:** ~13 hours dev (asset creation dominates per R5 §9).
> Phases 0-1 are the critical path to "smooth iterative authoring"
> (slug consolidation + proven PHP save round-trip); 2-8 are foundation
> + per-feature editor modules; 9-10 are per-scene authoring + polish.

---

## Reorder note 2026-05-20

The phase order in this plan reflects the locked Q7 decision (spec
§11.7): **backend switch FIRST, editor features SECOND.** The original
plan put PHP rollout at Phase 3 behind two editor phases; the user
chose to validate the save round-trip first so every subsequent editor
feature lands on a proven save path. Phase 0 (slug consolidation +
`.kfwork/` retirement) is new per Q1 (§11.1).

---

## Overview

11 phases (0 through 10), each independently shippable. Each phase
ends with a green test suite + a live verify cycle (Playwright
pixel-check on a deployed slug, never just a derived number — see
CLAUDE.md "viewer/harness verification" hard rules).

| Phase | Scope | Files touched | Effort |
|---|---|---|---|
| 0 | Slug consolidation `kf-fehmarn` → `fehmarn` + retire 5 `.kfwork/` bespoke scripts (per Q1) | 1 site config + Bunny CDN ops + 5 `git rm` | ~45 min |
| 1 | PHP backend infra + `splatpipe init-php-auth` CLI + flip `fehmarn` to `save_mode=http` + live-verify Save round-trips (per Q7) | 1 new CLI + 1 new test + per-scene `.author-token` provisioning | ~1.5 h |
| 2 | Foundation — EditorModule contract + EditHistory + CameraPathModule refactor + 3 timeline addenda (total_duration_s, total-time control, prev/next + Ctrl+Left/Right) + Scene Settings HudLayer panel scaffold | 8 files + 3 new fragments + 3 new tests | ~3.5 h |
| 3 | PanoramaModule (image upload + rotation + intensity slider) + new upload-image route + Scene Settings section | 5 files + 1 new route + 3 new tests | ~1.5 h |
| 4 | PostFXModule (tonemap + exposure sliders) + Scene Settings section | 2 files + 1 module + 0 new tests | ~30 min |
| 5 | AnnotationModule (EXPANDED per Q6: dot_unfold + distance + timeline-animatable) — both timeline lane AND Scene Settings section | 3 fragments + 1 module + 2 tests | ~2.5 h |
| 6 | CutsModule (refactor existing ClipPlayer into edit-time) | 1 fragment + 1 module + 2 tests | ~1.5 h |
| 7 | AudioModule (track CRUD + upload route + Scene Settings section) | 1 fragment + 1 module + 2 tests | ~1 h |
| 8 | TitlesModule (rendering + editor for `titles3d`) | 2 fragments + 1 module + 2 tests | ~1.5 h |
| 9 | Per-scene authoring (7 remaining scenes beyond `fehmarn`) + per-scene `save_mode=http` flip | per-scene assets + `splatpipe publish` × 7 + `splatpipe init-php-auth` × 7 | ~8 h |
| 10 | Polish + release v0.8.0 | CHANGELOG + CLAUDE.md + release notes | ~30 min |

---

## Phase 0 — Slug consolidation + `.kfwork/` retirement (per Q1 / spec §11.1)

**Goal:** Consolidate `kf-fehmarn` → `fehmarn` so the keyframe-editor
work ships under each scene's canonical slug. Retire the 5 bespoke
`.kfwork/deploy_kf_fehmarn*.py` scripts that bypass
`sanitize_public_viewer_config()` (bug-audit #3 carryover). After this
phase the codebase has ONE deploy path (`splatpipe publish`) and no
`kf-` slug aliases.

Sub-skills needed: `superpowers:verification-before-completion`.

### Steps

- [ ] **0.1 Stage the current `kf-fehmarn` viewer-config + index to the
      `fehmarn` slug via `splatpipe publish`.** NOT via the bespoke
      `.kfwork/` scripts. Verify the deployed `index.html` references
      the same `bkey` set already in the `kf-fehmarn/` Bunny folder
      (the `.rad` set is shared via the cross-slug pointer — see
      `project_scene_source_plys` memory) so the Bunny storage cost
      does NOT double.
- [ ] **0.2 Update the site config.** Edit
      `002_geddart_relaunch/src/data/scans/fehmarn.ts` so `splatUrl`
      changes from `kf-fehmarn/index.html` → `fehmarn/index.html`.
      Rebuild + deploy the Vite SPA per the
      `geddart_de_strato_stack` memory's deploy pattern (SFTP push
      to Strato).
- [ ] **0.3 Surgical purge of old `kf-fehmarn/*` cached entries on
      Bunny.** Use the existing `bunny_edge_rules.py` purge pattern
      (NOT a folder-wide purge — surgical per-URL). Specifically
      purge `kf-fehmarn/index.html` + `kf-fehmarn/viewer-config.json`
      (the two no-cache files). Leave the `kf-fehmarn/<bkey>/*.rad`
      / `*.radc` chunks cached for the transition period — they are
      shared with the new slug.
- [ ] **0.4 Retire the 5 `.kfwork/deploy_kf_fehmarn*.py` scripts.**
      `git rm .kfwork/deploy_kf_fehmarn*.py` (5 files). Also
      `git rm -rf .kfwork/stage_kf_fehmarn*/`,
      `.kfwork/live_*.json`, `.kfwork/live_*.html`. Confirm
      `.kfwork/check_markers.py` (the byte-lock checker) is now
      redundant (covered by `test_html_for_save_mode.py`); `git rm`
      that too.
- [ ] **0.5 Update CLAUDE.md "Known Limitations / TODO".** Remove the
      "Bespoke `.kfwork/deploy_kf_fehmarn*.py` scripts bypass
      `publish_scene`" entry — it's been resolved.
- [ ] **0.6 Live verify the consolidation.** Cold-load
      `https://splatpipe-cdn.b-cdn.net/fehmarn/` (enduser mode); cold-
      load `https://geddart.de/scans/fehmarn` and confirm the embedded
      scene loads correctly via the new `splatUrl`. Per CLAUDE.md
      "viewer/harness verification" hard rule 1: same-origin pixel
      verification on the deployed slug.
- [ ] **0.7 Update CHANGELOG.md.** Add a `### Changed` entry under
      `[Unreleased]` for the consolidation + a `### Removed` entry
      for the retired `.kfwork/` scripts.
- [ ] **0.8 Commit + push.** Commit message starts
      `chore(deploy): phase 0 — consolidate kf-fehmarn → fehmarn slug; retire .kfwork bespoke scripts`.

### Output

`https://splatpipe-cdn.b-cdn.net/fehmarn/` serves the current
keyframe-editor scene end-to-end (via canonical `splatpipe publish`,
NOT via `.kfwork/`). `kf-fehmarn/index.html` still works (graceful
transition); the `kf-fehmarn/` slug is no longer a publish target.
The CLAUDE.md known-limitation about `.kfwork/` is removed.

---

## Phase 1 — PHP backend infra + flip `fehmarn` to `save_mode=http` (per Q7 / spec §11.7)

**Goal:** Build the `splatpipe init-php-auth` CLI (spec §7.9), provision
the per-scene `.author-token` on geddart.de, flip `fehmarn` from
`save_mode=cli` to `save_mode=http`, and live-verify a Save POST
round-trips end-to-end. This phase proves the save path BEFORE the
editor module rollout piles more authoring surface on top.

Sub-skills needed: `superpowers:test-driven-development`,
`superpowers:verification-before-completion`.

### Steps

- [ ] **1.1 Confirm PHP adapter is live on geddart.de.** Per the
      `geddart_de_strato_stack` memory the PHP endpoint at
      `https://geddart.de/save-camera.php` already exists. Curl it
      for a 401/200 health check (the adapter is fully implemented
      per `infra/php/save-camera.php`).
- [ ] **1.2 Create the `splatpipe init-php-auth` CLI command.** New
      file `src/splatpipe/cli/init_php_auth_cmd.py` (per spec §7.9).
      Behaviour:
      - Generate `secrets.token_hex(16)` → 32-hex-char raw token.
      - Compute `hashlib.sha256(raw.encode()).hexdigest()` → 64-hex
        sha256 string.
      - SFTP push the hash to
        `scenes/<slug>/.author-token` on geddart.de (creds from
        `002_geddart_relaunch/.env`).
      - Print the raw token + bookmark URL to stdout in the format
        specified in spec §7.9.
      - `--regenerate` flag overwrites an existing token (narrow
        guard to avoid casual rotation mistakes).
      - Register the subcommand in `src/splatpipe/cli/main.py`.
- [ ] **1.3 Test the new CLI.** New file `tests/test_init_php_auth_cli.py`.
      Mock the SFTP push (`pytest-mock` or `unittest.mock.patch`);
      verify:
      - Generated token is 32 lowercase hex chars
        (`re.fullmatch(r"[0-9a-f]{32}", raw)`).
      - sha256 hash is correct
        (`hashlib.sha256(raw.encode()).hexdigest() == hash`).
      - Printed bookmark URL contains the slug + raw token + the
        `?author=1#token=` format.
      - `--regenerate` overwrites; default behaviour errors if a
        hash already exists at the remote path.
- [ ] **1.4 Provision `.author-token` for `fehmarn`.** Run
      `splatpipe init-php-auth --scene fehmarn` once. Capture the
      printed bookmark URL into the user's password manager (NEVER
      this repo).
- [ ] **1.5 Flip `fehmarn` to `save_mode=http`.** Edit `fehmarn`'s
      project config: `save_backend.type = "http"`,
      `save_backend.endpoint = "https://geddart.de/save-camera.php"`.
      Re-publish via `splatpipe publish`. The publish must:
      - Pass `sanitize_public_viewer_config()` (allow-list gate).
      - Carry the `save_backend.type` + `save_backend.endpoint` in
        the public viewer-config (per the existing `save_backend`
        sub-key allow-list).
      - NOT carry any `save_backend.secret` (already filtered by
        the sanitiser per bug-audit #3).
- [ ] **1.6 Live verify the Save round-trip.** Cold-load
      `https://splatpipe-cdn.b-cdn.net/fehmarn/?author=1#token=<raw-token>`.
      Make a trivial edit (move the existing keyframe by 1 m on X);
      click Save; confirm:
      - The browser network panel shows a POST to
        `https://geddart.de/save-camera.php` with
        `Authorization: Bearer <raw-token>` and the SPCP1 token in
        the body.
      - The PHP endpoint returns `200 OK` + `{ ok: true }`.
      - A second cold-load (no `?author=1`) of `fehmarn/` shows the
        moved keyframe persisted (i.e. `viewer-config.json` on
        Bunny was updated and the Bunny Edge Rule served it fresh).
- [ ] **1.7 Live verify the 413 fallback.** Cold-load `fehmarn`
      `?author=1`; somehow exceed the body cap (paste a 50 MB
      annotation `text` field). Confirm the viewer auto-falls back
      to the CLI clipboard path + the toast message
      "Backend rejected (too large). Token copied — relay via
      `splatpipe set-camera-path`."
- [ ] **1.8 Document save secrets in CLAUDE.md.** Briefly: per-scene
      `.author-token` rotation procedure
      (`splatpipe init-php-auth --scene <slug> --regenerate` +
      update password manager).
- [ ] **1.9 Update CHANGELOG.md.** Add a `### Added` entry for the
      new `splatpipe init-php-auth` CLI + a `### Changed` entry for
      the `fehmarn` save-mode flip.
- [ ] **1.10 Commit + push.** Commit message starts
      `feat(cli): phase 1 — splatpipe init-php-auth + flip fehmarn save_mode=http`.

### Output

`fehmarn` saves edits via POST to geddart.de end-to-end. The
`splatpipe init-php-auth` CLI is the only path a user needs to
provision new scene tokens. The 7 other scenes still save via
`save_mode=cli` (token-paste relay); their per-scene HTTP flip is
deferred to Phase 9 (per-scene authoring) so the editor work in
Phases 2-8 lands on a known-good save path without per-scene
provisioning overhead.

---

## Phase 2 — Foundation (EditorModule contract + EditHistory + module refactor + Scene Settings scaffold)

**Goal:** No new user-visible features beyond the 2026-05-20 addenda
trio (timeline total-duration decoupling + total-time input/auto +
prev/next keyframe buttons & hotkeys) + an empty Scene Settings
drawer scaffold (cog-icon toggles a right-side panel that modules
will populate in later phases). The existing 9 fragments using the
SceneView scaffold are refactored onto the new `EditorModule`
contract; the EditHistory ring buffer is added; Ctrl+Z/Y work for
the 3 refactored modules. All 8 deployed scenes still render
byte-identical (output-pin invariant from #118 modularization;
`fehmarn` per Phase 0).

> **Addendum 2026-05-20 — user authoring feedback round 1.** Steps
> 2.7a / 2.7b / 2.7c carry the three timeline-UX additions surfaced
> by the user's voice 2026-05-20 17:09 after testing the UX-5
> band-aid commit (`491faa8`). They are Phase-2-scoped because they
> are CameraPathModule additions and ship alongside the EditHistory
> contract that handles their undo semantics. See spec §3.7 + §4.1.1
> + §6.5.1.

> **Addendum 2026-05-20 — user authoring feedback round 2.** Step
> 2.16 carries the Scene Settings HudLayer panel scaffold per spec
> §12. The scaffold ships empty (no sections); Phase 3-8 modules
> populate their sections via the new `renderSceneSettings(parentEl)`
> hook on the EditorModule contract.

Sub-skills needed: `superpowers:test-driven-development`,
`superpowers:verification-before-completion`.

### Steps

- [ ] **2.1 Create the EditorModule + EditorModuleRegistry fragment.**
      New file `src/splatpipe/viewers/spark/template_parts/04a_editor_module.js_tmpl`
      (~150 lines). Defines `class EditorModule` (the ABC shape from
      spec §2.2, INCLUDING the optional `renderSceneSettings(parentEl)`
      hook) + `class EditorModuleRegistry` (spec §2.3). Wire
      `window.__editorRegistry` for the Playwright test surface.
- [ ] **2.2 Create the EditHistory fragment.** New file
      `src/splatpipe/viewers/spark/template_parts/17a_edit_history.js_tmpl`
      (~60 lines). Defines `class EditHistory` (spec §6.1, §6.2).
      Wire `window.__editHistory`.
- [ ] **2.3 Register the fragments.** Edit
      `src/splatpipe/viewers/spark/template_parts/__init__.py` to
      include the 2 new fragments at the correct positions (`04a` after
      `04`, `17a` after `17`). Phase 2.16 registers the third
      (`18a_scene_settings`).
- [ ] **2.4 Wire the registry into SceneView.** Edit
      `05_framework.js_tmpl` so `SceneView` instantiates the registry on
      construction. The registry is dormant until modules register
      themselves.
- [ ] **2.5 Wire Ctrl+Z / Ctrl+Y / Ctrl+Shift+Z.** Edit
      `05_framework.js_tmpl` (or `08_input.js_tmpl` — whichever owns
      keyboard binding routing today). Hook into `InteractionManager`.
      Toast on undo/redo.
- [ ] **2.6 Add undo/redo buttons.** Edit `03_body_chrome.html_tmpl` to
      add ↩ ↪ buttons in `_tlBarRow` next to the existing transport.
      Disabled-state CSS in `02b_styles_editor.css_tmpl`.
- [ ] **2.7 Refactor CameraPathModule.** Wrap the existing logic in
      `15_editor_trajectory.js_tmpl` + `16_editor_timeline.js_tmpl` +
      `17_editor_gizmo.js_tmpl` into a `CameraPathModule` class
      conforming to the contract. Behaviour preserved byte-for-byte.
      `stateKey: ["camera_paths", "default_path_id", "start_view"]`.
      Wire `beginGesture("kf-drag")` at diamond-drag start +
      `endGesture()` at mouseup.
- [ ] **2.7a Add `PathDict.total_duration_s` schema field
      (addendum 2026-05-20; spec §3.7).** Edit
      `src/splatpipe/core/path_io.py:PathDict` to add
      `total_duration_s: float | None` (optional, default-absent).
      Update `new_path()` to NOT set it (back-compat: absent = auto).
      Add a small validator-style helper
      (`path_io.py:effective_duration(path)`) returning the derived
      scrub-range ceiling per the §3.7 rule. Update
      `tests/test_path_io.py` (new test or extension) to cover the
      auto / manual / fallback branches.
- [ ] **2.7b Total-time input + auto toggle in `_tlBarRow`
      (addendum 2026-05-20; spec §4.1.1).** Edit
      `03_body_chrome.html_tmpl` to add the number-input + unit-label
      (`[ NN ] s total`) and the small `auto` / `manual` toggle button
      in the transport row. Edit `16_editor_timeline.js_tmpl` (and/or
      the CameraPathModule glue from 2.7) so the scrub-range ceiling
      reads `effective_duration(path)`; on commit (`onBlur` / Enter)
      the input writes `path.total_duration_s` AND pushes ONE
      EditHistory snapshot. Auto-toggle click writes `null` (auto) or
      the current input value (manual) and ALSO pushes ONE snapshot.
      Style block in `02b_styles_editor.css_tmpl`.
- [ ] **2.7c Prev/Next-keyframe skip buttons + hotkeys
      (addendum 2026-05-20; spec §4.1.1 + §6.5.1).** Edit
      `03_body_chrome.html_tmpl` to add the `|◀` / `▶|` buttons in
      `_tlBarRow` adjacent to play/pause. Wire to CameraPathModule
      handlers that compute the sorted-by-`t` keyframe view and jump
      the playhead to the strict-less-than / strict-greater-than
      neighbour (fallbacks: `t=0` / `total_duration_s` per §4.1.1).
      Wire `Ctrl+Left` / `Ctrl+Right` (with `event.metaKey ||
      event.ctrlKey` for Mac parity) in `InteractionManager`. These
      do NOT push undo entries (navigation, not edit). Add a small
      Playwright probe in the contract test (2.12) confirming the
      window-exposed CameraPathModule has `jumpPrevKf()` /
      `jumpNextKf()` methods that move `window.__playhead.time`.
- [ ] **2.8 Refactor AnnotationModule (render-only stub).** The viewer-
      side annotation render path (in `06_cfg.js_tmpl` or
      `07_setup_three_spark.js_tmpl` — verify with Grep before editing)
      wraps in an `AnnotationModule` stub. Authoring is Phase 5
      (EXPANDED per Q6). `stateKey: "annotations"`.
- [ ] **2.9 Refactor CutsModule (render-only stub).** Same — wrap
      `11_clip_player.js_tmpl` in a `CutsModule` stub.
      `stateKey: ["clips", "cameras"]`. Authoring is Phase 6.
- [ ] **2.10 Update the output-pin.** Run `pytest tests/test_html_for_output_pin.py`
      (the byte-lock test from #118). Re-baseline the output-pin: all
      8 deployed scenes (incl. `fehmarn` per Phase 0) must regenerate
      the SAME `index.html` bytes from the new fragment layout. If
      bytes differ, one of the refactors leaked a non-additive change.
- [ ] **2.11 Add EditHistory tests.** New file
      `tests/test_edit_history.py`. Node-driven (mirrors
      `test_spcp_js_port.py` pattern): commit / undo / redo / capacity
      eviction / clear-on-mode-switch.
- [ ] **2.12 Add EditorModule contract test.** New file
      `tests/test_editor_module_contract.py`. Playwright probe of
      `window.__editorRegistry.list().forEach(m => assert all required props)`,
      including the optional `renderSceneSettings(parentEl)` hook.
- [ ] **2.13 Run full pytest + ruff.** Expect green; expect the test
      count to bump by 3 new test files (+ extensions of `test_path_io.py`).
      Update `CLAUDE.md` test count line + `README.md` badge if changed.
- [ ] **2.14 Live verify (no new feature beyond timeline addenda).**
      Playwright cold-load each of the 8 deployed slugs (incl.
      `fehmarn` per Phase 0) in `enduser` mode + `embed` mode + cold
      `?author=1`. Confirm pixel-identical (or at-least visually
      indistinguishable) to pre-Phase-2 screenshots; confirm Ctrl+Z
      works after a drag on `fehmarn`. Additionally (addendum
      2026-05-20): on `fehmarn ?author=1` confirm the scrub bar can
      be dragged past `last_kf.t` when `total_duration_s` is set
      manually (e.g. 30 s); confirm `Ctrl+Left` / `Ctrl+Right` jump
      between recorded keyframes; confirm auto-toggle round-trips
      between `null` and the entered value without breaking the scrub
      range. Confirm Save still works via `save_mode=http` (Phase 1
      regression check).
- [ ] **2.15 Rename `_gzAuthorSecret()` → `_gzReadAuthToken()`.** Per
      spec §11.5 (Q5). Edit `05_framework.js_tmpl` (or whichever
      template_part owns the auth-fragment parser). The function
      reads from `window.location.hash` and now parses `#token=`
      instead of `#author=`. Live verify: the `fehmarn` bookmark URL
      uses the new `#token=` form and still authenticates against the
      PHP endpoint (the server side doesn't change — `Authorization:
      Bearer <token>` carries the same raw secret regardless of the
      fragment param name).
- [ ] **2.16 Create the Scene Settings panel scaffold fragment.**
      New file
      `src/splatpipe/viewers/spark/template_parts/18a_scene_settings.js_tmpl`
      (~80 lines per spec §12.1). Hosts:
      - The right-side drawer DOM (a `<aside class="spcp-scene-settings">`
        in `author-root`).
      - The cog-icon toggle in the editor header
        (`03_body_chrome.html_tmpl` companion edit).
      - The `EditorModuleRegistry.populateSceneSettings()` method
        that iterates registered modules and calls each
        `renderSceneSettings(parentEl)` in registration order
        (per §12.3).
      - sessionStorage persistence of the open/closed state
        (`spcp:scene-settings:open`).
      Phase 2 ships the scaffold EMPTY — no module has a
      `renderSceneSettings` implementation yet; later phases populate
      it. Register the fragment in `template_parts/__init__.py` at
      `18a` (between `18_frame_loop` and `19_intro_controller`).
- [ ] **2.17 Add Scene Settings panel test.** New file
      `tests/test_scene_settings_panel.py`. Playwright probe:
      - The cog-icon toggle button exists in author mode.
      - Clicking it adds/removes a `[data-open]` attribute on
        `aside.spcp-scene-settings`.
      - sessionStorage `spcp:scene-settings:open` persists across
        reloads (cold-load with the key set → drawer opens on boot).
      - In Phase 2 the drawer is EMPTY (zero `<details>` children);
        Phase 3+ tests will assert sections appear.
- [ ] **2.18 Commit + push.** Commit message starts
      `feat(editor): phase 2 — EditorModule contract + EditHistory + Scene Settings scaffold`.

### Output

A green test suite (~717-720 tests if pytest was 713). All 8 deployed
scenes render byte-identical (modulo the transport-row additions
from 2.7a-c + the cog-icon for the empty Scene Settings drawer).
Ctrl+Z works on a camera-path keyframe drag in `fehmarn`. The new
user-visible additions are: (1) the 2026-05-20 timeline addenda
trio (total-time input + auto toggle + prev/next keyframe buttons +
`Ctrl+Left` / `Ctrl+Right` hotkeys); (2) the cog-icon → empty Scene
Settings drawer. The fragment-rename `#author=` → `#token=` is live.
The contract + history + Scene Settings scaffold are the platform
every subsequent phase builds on.

---

## Phase 3 — PanoramaModule (backdrop image + Scene Settings section)

**Goal:** New `panorama_backdrop` block in the schema. PanoramaModule
renders the backdrop + provides editor UI (image upload + rotation +
intensity slider) + populates the first section of the Scene Settings
drawer. Per-scene panorama upload works on `fehmarn` end-to-end.

### Steps

- [ ] **3.1 Schema additions.** Edit
      `src/splatpipe/core/config_safety.py`: append
      `"panorama_backdrop"` + `"schema_version"` to
      `PUBLIC_VIEWER_CONFIG_KEYS`. Edit
      `src/splatpipe/core/config_merge.py`: append
      `"panorama_backdrop"` to `ALLOWED_PATCH_KEYS`. (PostFX comes in
      Phase 4; audio in Phase 7.)
- [ ] **3.2 publish_scene writes the schema marker.** Edit
      `src/splatpipe/steps/publish.py` so `publish_scene()` always
      writes `schema_version: 1` and a default `panorama_backdrop:
      {url: null, rotation_deg: 0, intensity: 1.0}` block if absent.
      Idempotent for scenes that already have it.
- [ ] **3.3 PanoramaModule render path.** Edit
      `07_setup_three_spark.js_tmpl`: equirect JPG load →
      `THREE.PMREMGenerator` → cubemap → `scene.background`. Honour
      `panorama_backdrop.intensity` via `scene.backgroundIntensity`.
      Skip cleanly when `url: null`. Mobile fallback to 2K equirect if
      `window.devicePixelRatio * viewport area` exceeds a heuristic
      threshold.
- [ ] **3.4 PanoramaModule editor UI (Scene Settings section).** Edit
      the new fragment to add `renderSceneSettings(parentEl)`:
      append a `<details>` section titled "Backdrop" with file picker
      + rotation slider `[0..360]` + intensity slider `[0..2]` +
      tooltip from spec §5.4. (Per §12: this is the FIRST module
      populating the Scene Settings drawer.)
- [ ] **3.5 PanoramaModule class.** Glue class conforming to
      EditorModule contract. `stateKey: "panorama_backdrop"`.
      `onCfgChange` re-uploads texture if `url` changed; re-rotates if
      `rotation_deg` changed; re-sets `scene.backgroundIntensity` if
      `intensity` changed. Register in `05_framework.js_tmpl`'s
      SceneView init.
- [ ] **3.6 New upload-image route.** New file
      `src/splatpipe/web/routes/upload_image.py`. Mirror
      `web/routes/projects.py:upload_audio` (the bug-audit #7 hardened
      pattern): MIME filter `{image/jpeg, image/png}`, size cap 20 MB,
      `core/path_safety.ensure_contained()` gate to
      `<project>/05_output/assets/`. Mount in `web/app.py`.
- [ ] **3.7 publish bundles assets/.** Edit `publish.py` so the staged
      output includes `<slug>/assets/*` when `<project>/05_output/assets/`
      is non-empty. Test fixture: a known good 256-byte test JPG.
- [ ] **3.8 thread `panorama_backdrop` through `publish_scene` per the
      `sh_encoding` precedent.** Per the existing `paged_ext_splats`
      / `sh_encoding` pattern (memory: `paged_ext_splats_first_class`),
      `publish_scene()` threads new fields into the staged
      `viewer-config.json` so the public CDN sees the defaults.
- [ ] **3.9 New tests.**
      - `tests/test_image_upload_security.py` — mirror
        `test_audio_upload_security.py` (path traversal, MIME, size
        cap).
      - `tests/test_panorama_backdrop_schema.py` — sanitiser + merge
        accept the new keys; older configs without the keys still pass.
      - `tests/test_publish_schema_version.py` — `publish_scene` writes
        `schema_version: 1` into every output cfg.
- [ ] **3.10 Extend sanitiser + merge tests.** Update
      `tests/test_publish_config_sanitize.py` +
      `tests/test_config_merge.py` for the new public + patch key.
- [ ] **3.11 Run full pytest + ruff.**
- [ ] **3.12 Live verify on `fehmarn`.**
      Upload a test pano via the dashboard → publish → cold-load
      `<cdn>/fehmarn/?author=1#token=<t>` and confirm:
      - The backdrop renders.
      - The Backdrop section appears as the first item in the
        Scene Settings drawer.
      - Rotation slider live-updates the cubemap.
      - Intensity slider dims/brightens the backdrop.
      - Save POSTs the new `panorama_backdrop` block to geddart.de;
        a reload shows it persisted.
      A/B verify with one other scene (no backdrop) — should render
      correctly with the runtime defaults (`url: null` → no upload).
- [ ] **3.13 Update CHANGELOG.md.** Add a `### Added` entry under
      `[Unreleased]`.
- [ ] **3.14 Commit + push.** Commit message starts
      `feat(editor): phase 3 — PanoramaModule + Scene Settings first section`.

### Output

`fehmarn` renders a panorama backdrop loaded via the editor. The new
`schema_version: 1` marker is present in every output cfg. The Scene
Settings drawer now has 1 section (Backdrop) populated. The save
round-trips the new key via the PHP backend. Other 7 scenes
unaffected (no backdrop URL set; default null → no upload).

---

## Phase 4 — PostFXModule (tonemap + exposure)

**Goal:** Surface the existing `cfg.postprocessing` knobs in a Scene
Settings section so the user can tune tonemapping + exposure
in-viewer. No renderer change (the postprocessing path already reads
these values).

### Steps

- [ ] **4.1 Schema allow-list extension.** Edit
      `src/splatpipe/core/config_merge.py`: append `"postprocessing"`
      to `ALLOWED_PATCH_KEYS`. (`config_safety.py` already permits it
      in `PUBLIC_VIEWER_CONFIG_KEYS` since the renderer reads it
      today.)
- [ ] **4.2 PostFXModule class.** New module conforming to EditorModule
      contract. `stateKey: "postprocessing"`. `onCfgChange` updates
      the renderer's tonemapping/exposure uniforms (the renderer
      side already exists; this just routes the cfg change to it).
- [ ] **4.3 PostFXModule Scene Settings section.**
      `renderSceneSettings(parentEl)` appends a `<details>` section
      titled "Post-FX" with: tonemapping dropdown
      (`ACESFilmic` | `Reinhard` | `Cineon` | `None`) + exposure
      slider `[0..3]` + tooltip from spec §5.4. (Section 2 in
      registration order.)
- [ ] **4.4 Register the module.** In `05_framework.js_tmpl`'s
      SceneView init, between PanoramaModule and AnnotationModule
      (per spec §4.9 order).
- [ ] **4.5 Extend `tests/test_config_merge.py`** with `postprocessing`
      patch-key coverage.
- [ ] **4.6 Run full pytest + ruff.**
- [ ] **4.7 Live verify on `fehmarn`.** Change tonemapping to Reinhard,
      slide exposure to 2.0; confirm the rendered pixels change;
      hit Save; reload; confirm both values persisted via the PHP
      backend.
- [ ] **4.8 Update CHANGELOG.md. Commit + push.** Commit message
      starts `feat(editor): phase 4 — PostFXModule + Scene Settings section`.

### Output

`fehmarn`'s Scene Settings drawer now has 2 sections (Backdrop +
Post-FX). Tonemap + exposure live-update the rendered pixels.

---

## Phase 5 — AnnotationModule (EXPANDED per Q6 / spec §11.6 + §4.2)

**Goal:** Annotations are BOTH timeline-animatable (`t_in` / `t_out`
fade in/out with the playhead) AND distance-based interactive (a dot
always visible while in-window; unfolds into title + text panel when
the camera enters `unfold_radius_m` or the user clicks). This is the
EXPANDED scope from Q6 (user voice 17:38); the original simple-label
sketch is replaced. Both authoring and the Scene Settings section
land in this phase.

### Steps

- [ ] **5.1 Expand the annotation schema (per spec §4.2).** Edit
      `src/splatpipe/core/path_io.py` (or wherever the
      `AnnotationDict` shape lives) to add the new fields:
      `kind` (default `"dot_unfold"`), `label`, `title`,
      `unfold_radius_m` (default 5.0), `fade_ms` (default 300),
      `media_url` (default null), `billboard` (default true).
      Back-compat: legacy entries without `kind` upgrade to
      `"dot_unfold"` at read time.
- [ ] **5.2 AnnotationModule authoring UI.** Edit the
      `AnnotationModule` from Phase 2.8 to add author-mode
      entrypoints:
      - "+ Add Annotation" button in `author-root` → click-in-3D mode
        (next 3D click captures the world position + opens an inline
        title/text editor).
      - Double-click an existing dot → opens the title/text editor
        pinned at the dot's screen position.
      - Drag the dot → reposition (uses `OverlayScene`; `beginGesture`
        / `endGesture` wraps the drag).
      - Kebab menu on each dot → Delete / Set radius / Set media URL
        / Set t_in..t_out (with `beginGesture("ann-<op>")` snapshot
        before each).
- [ ] **5.3 Splat-aware raycast helper.** Cast against the bounding
      box / depth buffer of the splat scene; pick the surface-most
      hit (so the annotation lands ON something visible). Fallback
      to a fixed-distance plane if no hit.
- [ ] **5.4 Renderer: distance-based unfold.** Per-frame in the
      update loop (cheap — ≤16 annotations per scene): compute
      `camera.position.distanceTo(annotation.pos)`; if
      `< unfold_radius_m`, expand the dot into the full content
      panel (DOM overlay anchored via `worldToScreen(pos)`).
      Manual click toggle overrides distance until camera moves
      away again.
- [ ] **5.5 Renderer: timeline fade.** Per-frame: compute
      `opacity = smoothstep(t_in, t_in + fade_ms/1000, time) -
       smoothstep(t_out - fade_ms/1000, t_out, time)`.
      Annotation is fully hidden outside `[t_in, t_out]`.
- [ ] **5.6 Multi-lane timeline integration.** Edit
      `16_editor_timeline.js_tmpl` to add an annotations lane
      (16 px height; one thin coloured bar per annotation at
      `t_in..t_out`).
- [ ] **5.7 AnnotationModule Scene Settings section.**
      `renderSceneSettings(parentEl)` appends a `<details>` section
      titled "Annotations" with: a list of all annotations + per-row
      controls (kind dropdown / label / title / text / pos / radius /
      t_in / t_out / fade_ms / media_url) + a "+ Add" button mirroring
      the in-viewer click-in-3D entrypoint. (Section 3 in
      registration order.)
- [ ] **5.8 Annotation triggers across cut boundaries.** The master
      playhead's annotation-trigger eval reads clip-local time when
      cuts are present (Phase 6 contract). For Phase 5 (no cuts in
      most scenes), master time = clip time = playhead time.
- [ ] **5.9 New tests.**
      - `tests/test_annotations_schema_q6.py` — `kind` defaults to
        `dot_unfold`; `unfold_radius_m` default 5.0; legacy entries
        without `kind` upgrade correctly; distance-trigger eval
        boundary cases.
      - `tests/test_annotation_module_editor.py` — Playwright probe
        of the click-in-3D / drag / delete flows + the Scene Settings
        section CRUD; verify each emits the expected EditHistory
        snapshot + the expected SPCP1 patch.
- [ ] **5.10 Live verify on `fehmarn`.** Cold-load
      `<cdn>/fehmarn/?author=1#token=<t>`:
      - Click "+ Add Annotation" → click on the bamboo splat → set
        title "Bamboo detail" + text + radius 3 m + t_in 5 / t_out 15.
      - Hit Save (POSTs to geddart.de).
      - Reload (no `?author=1`); confirm:
        - Dot is visible at the bamboo position while `playhead.time ∈
          [5, 15]`.
        - Walking the camera within 3 m unfolds the panel.
        - Outside the time window, the dot is hidden.
- [ ] **5.11 Update CHANGELOG.md.** Add a `### Added` entry for the
      EXPANDED annotation schema + authoring.
- [ ] **5.12 Commit + push.** Commit message starts
      `feat(editor): phase 5 — AnnotationModule expanded (Q6: dot_unfold + distance + timeline)`.

### Output

End-to-end annotation authoring works on `fehmarn` with the EXPANDED
Q6 scope: dot_unfold + distance + timeline-animatable. The Scene
Settings drawer now has 3 sections (Backdrop + Post-FX + Annotations).
Saves round-trip via the PHP backend. Undo works on each gesture.

---

## Phase 6 — CutsModule (refactor ClipPlayer into edit-time)

**Goal:** Author-mode editing of `clips` + `cameras`. Timeline lane
shows per-camera coloured clip blocks; drag to reorder / retime;
click to select; delete. Existing enduser/embed playback unchanged.

### Steps

- [ ] **6.1 CutsModule authoring UI.** Edit the `CutsModule` stub
      from Phase 2.9 to add author-mode entrypoints:
      - "+ Add Camera" → spawn a new camera entry in `cameras`
        (color-picked).
      - "+ Add Clip" at playhead → insert a clip from the currently
        selected camera at the master playhead position.
      - Drag clip body → reorder.
      - Drag clip edges → retime (`beginGesture("clip-retime")`).
      - Click → select; Delete key → remove.
- [ ] **6.2 Per-camera color assignment.** Each new camera gets a
      stable color (the existing per-camera color logic if one exists,
      or a deterministic hash → palette).
- [ ] **6.3 Master-time → clip-local-time evaluator.** Helper that
      maps the master playhead to `(clipId, clipLocalT)`. Exposes
      `playhead.localTime` for the AnnotationModule / AudioModule to
      consume.
- [ ] **6.4 Multi-lane timeline.** Cuts lane shows clip blocks at 24 px
      height; per-camera color stripes.
- [ ] **6.5 Existing playback unchanged.** The viewer-side playback
      path in `11_clip_player.js_tmpl` continues to drive enduser /
      embed mode. Only author-mode adds new chrome.
- [ ] **6.6 Tests.**
      - `tests/test_cuts_module_editor.py` — add / reorder / retime /
        delete; verify SPCP1 patch shape.
- [ ] **6.7 Live verify on `fehmarn`.** `fehmarn` has 1 camera / no
      clips today → add a second camera at a different start_view →
      add 2 clips that cut between them → Save (POSTs to geddart.de)
      → reload → verify enduser mode plays the cut sequence.
- [ ] **6.8 Update CHANGELOG.md. Commit + push.** Commit message
      starts `feat(editor): phase 6 — CutsModule edit-time refactor`.

### Output

Multi-camera cut sequences are authorable. `fehmarn` (or any scene)
can have a 2-camera cut authored in-viewer. Saves round-trip via the
PHP backend.

---

## Phase 7 — AudioModule (track CRUD + Scene Settings section)

**Goal:** Per-track audio with volume / loop / in/out timing + optional
positional source position. Timeline lane shows audio blocks. Scene
Settings drawer gains an Audio section.

### Steps

- [ ] **7.1 Allow-list audio in patches.** Edit
      `core/config_merge.py:ALLOWED_PATCH_KEYS` — append `"audio"`.
- [ ] **7.2 AudioModule.** New module; `stateKey: "audio"`.
      Default `cfg.audio = []` for any scene without tracks (per
      Q3 / spec §11.3).
- [ ] **7.3 AudioModule editor UI.**
      - "+ Add Track" → file picker → upload via existing
        `/upload-audio` route (hardened in audit #7).
      - Per-track: volume slider, in/out time inputs, positional
        toggle, position picker (click-in-3D when positional).
- [ ] **7.4 AudioModule Scene Settings section.**
      `renderSceneSettings(parentEl)` appends a `<details>` section
      titled "Audio" with: track list + per-row controls (volume /
      loop / kind / pos / t_in / t_out / file replace) + the same
      "+ Add Track" button. (Section 4 in registration order.)
- [ ] **7.5 Audio render path.** Wire `THREE.AudioListener` +
      `Audio` / `PositionalAudio` based on `kind`. Schedule playback
      against the master playhead's `t_in..t_out`.
- [ ] **7.6 Multi-lane timeline.** Audio lane: per-track row; bar
      height encodes volume. 20 px height.
- [ ] **7.7 Tests.**
      - `tests/test_audio_module_editor.py` — track CRUD + SPCP1
        patch shape.
      - `tests/test_audio_module_render.py` — playhead-driven
        scheduling (Node-driven).
- [ ] **7.8 Live verify on `fehmarn`.** Per Q3 the user provides
      audio assets later; this verify uses a tiny test MP3 (256-byte
      silent stub) just to prove the round-trip. Add the test track
      → set volume 0.5 → t_in 0 → Save → reload → confirm the
      `audio` array persists. (Skip the actual-playback check until
      a real asset is provided.)
- [ ] **7.9 Update CHANGELOG.md. Commit + push.** Commit message
      starts `feat(editor): phase 7 — AudioModule + Scene Settings section`.

### Output

Audio editing surface works on `fehmarn`. The Scene Settings drawer
now has 4 sections (Backdrop + Post-FX + Annotations + Audio). The
patch path round-trips correctly via the PHP backend.

---

## Phase 8 — TitlesModule (titles3d render + editor)

**Goal:** Render 3D text titles in the scene (CSS3DObject or canvas
sprite). Author via click-in-3D + text input + color/size sliders +
t_in/t_out.

### Steps

- [ ] **8.1 Titles3D renderer.** New fragment
      `src/splatpipe/viewers/spark/template_parts/14a_titles_3d.js_tmpl`
      (~80 lines). Render `cfg.titles3d` as CSS3DObjects (with
      canvas-sprite fallback for Safari/iOS where CSS3DRenderer is
      known-broken). Attach to OverlayScene.
- [ ] **8.2 TitlesModule.** New module; `stateKey: "titles3d"`.
- [ ] **8.3 Authoring UI.**
      - "+ Add Title" → click-in-3D mode → place title at hit point →
        opens inline text + color/size editor.
      - Drag title in OverlayScene → reposition.
      - Kebab → delete.
- [ ] **8.4 Multi-lane timeline.** Titles lane: 16 px height; per-title
      white bars.
- [ ] **8.5 Tests.**
      - `tests/test_titles_module_editor.py` — CRUD + patch shape.
      - `tests/test_titles_render.py` — render correctness against a
        known title list.
- [ ] **8.6 Live verify on `fehmarn`.** Add intro + outro titles;
      verify they appear at the right times in enduser mode. Save
      via PHP backend; reload; confirm persisted.
- [ ] **8.7 Update CHANGELOG.md. Commit + push.** Commit message
      starts `feat(editor): phase 8 — TitlesModule render + editor`.

### Output

Titles render + edit. `fehmarn` now has the full v1 cinematic shell
toolset working end-to-end. The IntroModule + CameraPathModule
(start-view) Scene Settings sections (Sections 5 + 6 per spec §12.2)
also light up via their existing modules' `renderSceneSettings` hooks
— pending the IntroModule polish in Phase 10.

---

## Phase 9 — Per-scene authoring (7 remaining scenes beyond `fehmarn`)

**Goal:** Each of the 7 scenes beyond `fehmarn` gets a full
authoring pass — panorama (if available), audio (if available),
camera paths, optional cuts/annotations/titles. Per Q7 (spec §11.7)
each scene's `save_mode` is ALSO flipped from `cli` to `http` in
this phase (the PHP backend was proven on `fehmarn` in Phase 1; this
extends it scene-by-scene).

Sub-skills needed: `superpowers:dispatching-parallel-agents` (one
agent per scene if assets are pre-staged); otherwise sequential.

### Steps (per scene, in the R5 §2.1 order, post-consolidation per Q1)

For each slug in `[ibug, speicher, polygraf, polygraf-east, fabrik,
stettiner, methtrailer]` (`fehmarn` already completed via Phase 1 +
Phases 3-8 verify steps):

- [ ] **9.S.1 Provision PHP author token.** Run
      `splatpipe init-php-auth --scene <slug>` (per spec §7.9 / Phase 1
      CLI). Bookmark URL goes into the user's password manager.
- [ ] **9.S.2 Flip `save_mode` to `http`.** Edit the project config:
      `save_backend.type = "http"`,
      `save_backend.endpoint = "https://geddart.de/save-camera.php"`.
- [ ] **9.S.3 Provision panorama asset (per Q2 / spec §11.2).** Mixed
      sources allowed (drone / phone 360 / AI-synthesised); whatever
      the user has for that scene. Resize to 4K JPG; upload via
      dashboard `/upload-image` → ends up at
      `<project>/05_output/assets/backdrop.jpg`. Scenes with no
      panorama keep `url: null` (renderer skips).
- [ ] **9.S.4 Provision audio (per Q3 / spec §11.3).** Default
      `audio: []` (no audio) is fine; user provides assets later.
      For scenes with a track ready: upload via `/upload-audio`;
      pick volume / loop / positional defaults.
- [ ] **9.S.5 Author camera paths.** Open
      `<cdn>/<slug>/?author=1#token=<t>`; record or hand-author
      camera-path keyframes; smoothness + speed sliders; mark a
      default path; set `total_duration_s` if the natural length
      differs from `last_kf.t`.
- [ ] **9.S.6 Author cuts (if multi-camera).** Most scenes are
      single-camera; skip for those.
- [ ] **9.S.7 Author annotations (EXPANDED per Q6).** 1-3 markers per
      scene per R5 §9 estimate; ~5 min per scene. Use the new
      `dot_unfold` schema with appropriate `unfold_radius_m` per
      scene scale.
- [ ] **9.S.8 Author titles.** Intro + outro (or skip per scene).
- [ ] **9.S.9 Save via PHP backend.** Hit Save in the viewer; verify
      the POST returns `200 OK` + the new config is fetched on
      reload.
- [ ] **9.S.10 Edge Rule re-verify.** `curl -I
      <cdn>/<slug>/viewer-config.json` → `cdn-cache: BYPASS`.
- [ ] **9.S.11 Update CHANGELOG.md note (per-scene rollout milestone).**

After all 7 scenes complete:

- [ ] **9.X Final CHANGELOG entry.** A `### Added` entry capturing the
      multi-scene rollout milestone.
- [ ] **9.X Commit + push.** Commit message starts
      `feat(editor): phase 9 — per-scene authoring complete (7 scenes + http save flip)`.

### Output

All 8 scenes carry authored cinematic content + `save_mode=http`. The
`splatpipe-cdn.b-cdn.net/<slug>/` URLs each present a polished
end-user experience with backdrop + camera-path + (where authored)
annotations + cuts + audio + titles. Every scene now saves via the
PHP backend — the CLI token-paste relay stays available as the
fallback (413 path + manual `splatpipe set-camera-path`).

---

## Phase 10 — Polish + finalize v0.8.0 release

**Goal:** Ship-ready. Documentation reconciled; CHANGELOG complete;
test count current; release notes drafted.

### Steps

- [ ] **10.1 Editor-module test surface.** Confirm every module
      exposes `window.__editor.<name>` for Playwright. Add the
      registry-level `list()` probe to the existing harness coverage.
- [ ] **10.2 IntroModule polish (Scene Settings section).** Wire
      `IntroModule.renderSceneSettings(parentEl)` so the existing
      `intro: { type, ms }` config gets a section in the Scene
      Settings drawer (Section 5 per spec §12.2).
- [ ] **10.3 CameraPathModule Start View Scene Settings section.**
      Wire CameraPathModule's `renderSceneSettings(parentEl)` so the
      drawer's Section 6 has a "Save current camera as start view"
      button + a read-only display of the current `start_view`.
- [ ] **10.4 Mobile editor restriction.** Author mode forced to
      desktop viewport ≥ 1024 px wide. Mobile cold-loads `?author=1`
      see a "Editor only on desktop" toast + fallback to enduser mode.
- [ ] **10.5 Accessibility pass.** Tab-order through editor panels;
      ARIA labels on the timeline canvas; keyboard equivalents for
      the core gestures (Up/Down for keyframe step; arrow keys for
      annotation reposition with selection).
- [ ] **10.6 CLAUDE.md reconciliation.**
      - Update Package Layout to add the 3 new fragments + new
        modules + the new `cli/init_php_auth_cmd.py`.
      - Update test count line.
      - Document the EditorModule contract briefly in "Critical Code
        Patterns" (incl. the `renderSceneSettings(parentEl)` hook).
      - Document the EditHistory ring-buffer + ephemeral semantics.
      - Document the Scene Settings panel concept.
      - Document the `splatpipe init-php-auth` workflow.
- [ ] **10.7 README.md.** Update test badge if changed; mention the
      editor + the new CLI in the "Quick Start" if appropriate.
- [ ] **10.8 CHANGELOG.md.** Move `[Unreleased]` → `[0.8.0]` section.
      Drafted entries from each phase.
- [ ] **10.9 Bump pyproject.toml.** `version = "0.8.0"`.
- [ ] **10.10 Final verify.**
      - `pytest tests/ -v` → green.
      - `ruff check src/ tests/` → green.
      - Cold-load all 8 deployed slugs → all render correctly.
- [ ] **10.11 Commit `Release v0.8.0`.**
- [ ] **10.12 Tag + push.** `git tag v0.8.0; git push origin
      feat/camera-keyframe-editor --tags`.
- [ ] **10.13 Open PR** (or merge if user prefers direct).
- [ ] **10.14 GitHub Release.** `gh release create v0.8.0 --title
      "v0.8.0" --notes "<paste CHANGELOG>"`.

### Output

v0.8.0 released. All 8 scenes editable in-viewer + canonical-slug
consolidated + saving via PHP backend. Editor module contract +
snapshot undo + Scene Settings panel + panorama + post-fx +
expanded annotations + cuts + audio + titles all shipped.

---

## Test count expectations

| Phase | New tests | Cumulative test count (approx; baseline 713) |
|---|---:|---:|
| Baseline | — | 713 |
| Phase 0 | 0 (deploy + docs only) | 713 |
| Phase 1 | +1 (`test_init_php_auth_cli.py`) | 714 |
| Phase 2 | +3 (`test_edit_history.py`, `test_editor_module_contract.py`, `test_scene_settings_panel.py`) + extension of `test_path_io.py` for `total_duration_s` | ~717-720 |
| Phase 3 | +3 (`test_image_upload_security.py`, `test_panorama_backdrop_schema.py`, `test_publish_schema_version.py`) | 720-723 |
| Phase 4 | 0 (extension of `test_config_merge.py` only) | 720-723 |
| Phase 5 | +2 (`test_annotations_schema_q6.py`, `test_annotation_module_editor.py`) | 722-725 |
| Phase 6 | +1 (`test_cuts_module_editor.py`) | 723-726 |
| Phase 7 | +2 (`test_audio_module_editor.py`, `test_audio_module_render.py`) | 725-728 |
| Phase 8 | +2 (`test_titles_module_editor.py`, `test_titles_render.py`) | 727-730 |
| Phase 9 | 0 (authoring, not code) | 727-730 |
| Phase 10 | 0 (polish) | 727-730 |

(Per CLAUDE.md "viewer/harness verification" hard rule 6: spec-mandated
real tests legitimately raise the count.)

---

## Risk register

| Risk | Mitigation |
|---|---|
| Output-pin baseline breaks unexpectedly in Phase 2 | Each refactor preserves behaviour byte-for-byte; if pin breaks, isolate which sub-step (2.7-2.9) introduced the delta. |
| Slug consolidation (Phase 0) breaks live site | Phase 0.6 explicitly cold-loads `https://geddart.de/scans/fehmarn` AFTER the site config + Bunny purge; if the embed breaks, the bespoke `.kfwork/` `kf-fehmarn` URL still works as the fallback path until next site rebuild. |
| PHP auth provisioning fails (SFTP creds) | Phase 1.3 tests the CLI with mocked SFTP; Phase 1.4 is a single live run against `fehmarn` with all upstream creds visible — if it fails, the cause is SFTP/network, not the CLI logic. |
| Cross-origin chunks (the recurring trap per CLAUDE.md "viewer / harness verification" rule 1) | All Phase 3-9 live verify happens on deployed Bunny slugs (same-origin), not local harnesses with cross-origin chunk fetch. |
| 413 fallback never tested live until Phase 1.7 | Phase 1.7 forces a 413 with an artificial payload + verifies the toast + clipboard path BEFORE editor features pile on. |
| Per-scene asset provenance unclear (Q2) | Q2 locked to "mixed sources"; Phase 9 is per-scene; one scene with no panorama just keeps `url: null` (renderer skips). Authoring proceeds per scene as assets become available. |
| Annotation EXPANDED scope creep (Q6) | Phase 5 explicitly carries the EXPANDED scope (dot_unfold + distance + timeline); the new schema fields all default to back-compat values so existing render code keeps working until the new code lands. |
| Annotation click-in-3D raycast misses for some scenes (no clean depth) | Fallback: fixed-distance plane in front of camera. Phase 5.3 implements + tests. |
| Two-tab concurrent save (LWW) loses an annotation | Property-granular LWW (spec §7.7) — different keys don't conflict. Same-key conflicts: last save wins. Documented; not a v1 mitigation target. |
| Scene Settings drawer accidentally shows in enduser mode | Phase 2.16 explicitly gates the drawer behind author mode; Phase 2.17 test asserts the cog-icon is absent in enduser. |
| Mobile author mode accidentally exposed | Phase 10.4 explicitly blocks; documented in CLAUDE.md UX section. |

---

## Verification of this plan

- Spec cross-references in §2-9 all map to a real `template_parts/`
  fragment or `core/` module (verified via Glob against HEAD `491faa8`).
- The phased order respects the modularization output-pin invariant
  (#118) — Phase 2 explicitly re-baselines the pin.
- Per CLAUDE.md "viewer / harness verification" rule 2: each phase has
  a real-pixels live verify step (NOT just derived-number checks).
- The 4 conflict resolutions in the spec (R1↔R8, R3↔R7, R6 module
  reshape, R4↔R6 auto-save) flow into specific module / phase steps:
  - R1↔R8 → Phase 2.2 (EditHistory fragment).
  - R3↔R7 → Phases 3 + 4 (no `lighting` block; PanoramaModule +
    PostFXModule only).
  - R6 reshape → Phases 3 + 4 (PanoramaModule + PostFXModule, NOT
    LightingModule).
  - R4↔R6 → Phase 2 contract definition (no auto-save in MVP).
- The 8 Q-decisions (Q1-Q8 in spec §11) flow into specific phases:
  - Q1 (slug consolidation) → Phase 0.
  - Q2 (panorama mixed sources) → Phase 9.S.3 explicitly documents.
  - Q3 (audio capacity now, assets later) → Phase 7 (capacity) +
    Phase 9.S.4 (assets).
  - Q4 (sha256 + CLI) → Phase 1.2 (CLI creation) + Phase 1.4
    (`fehmarn` provisioning) + Phase 9.S.1 (the rest).
  - Q5 (`#token=` rename) → Phase 2.15.
  - Q6 (expanded annotation scope) → Phase 5.
  - Q7 (backend FIRST) → Phase 1 (PHP) precedes Phases 2-8 (editor).
  - Q8 (Cloudflare skip) → no phase; documented in spec §0 + §11.8.
