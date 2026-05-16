# Set Start View — design (2026-05-15)

Approved by user on Telegram ("ok for setting start plan", 2026-05-15).
Persistence route: **Option A (relay)** — viewer emits a token, the
pipeline writes it back. No backend, no client-side secret.

## Goal

Let the user frame a deployed Spark viewer to a nice starting position
and make that the initial camera for every future load of that viewer —
set → confirm → saved for all.

## Constraint

Deployed viewers are static files on Bunny CDN (`index.html`,
`viewer-config.json`, `scene.rad`). No backend; the Bunny storage key
must never be in client JS. So the viewer cannot persist anything
itself — it emits a token; a trusted side (the Splatpipe CLI, run by
the assistant when the user pastes the token) writes it back.

## Token format

`SPV1:<projectName>:<base64url(JSON)>` where JSON is:

```json
{ "pos":[x,y,z], "quat":[x,y,z,w], "target":[x,y,z], "fov":<deg> }
```

`projectName` identifies which `viewer-config.json` to patch. The token
carries only a camera pose — harmless to share over Telegram.

## Viewer changes (`viewers/spark/template.py`)

1. `_DEFAULTS.start_view = null` so `cfg.start_view` is always defined.
2. **Highest-priority initial camera.** In the early synchronous camera
   block (currently: default-path kf → any-path kf → annotation →
   `(0,2,10)`), add `cfg.start_view` as the *first* check: set
   `camera.position`, `camera.quaternion`, `camera.fov`,
   `controls.target` from it and return. `_origCamPos/_origCamQuat/
   _origCamFov/_origTarget` (snapshotted from the live camera right
   after this block) therefore auto-capture it, so Reset/Home and the
   orbit bench return to the start view too — no extra wiring.
3. Add `cfg.start_view` to the `hasAuthoredView` predicate in the async
   post-`splat.initialized` block so the sqrt-distance fallback does not
   override an explicit start view.
4. **"Set start view" button** in the `#quality-buttons` header row
   (next to the budget dropdown / Bench). Click → capture
   `{pos,quat,target,fov}` from `camera` + `controls.target` → show a
   small on-demand confirm overlay ("Save this as the start view?"
   Confirm / Cancel). Confirm → build the token,
   `navigator.clipboard.writeText(token)` (inside the click gesture, so
   Safari allows it) and also render the token on-screen selectable as a
   fallback, plus a short instruction to paste it to Claude on Telegram.

No new globals; overlay is created on demand and removed on
Cancel/Confirm. STOCK mode unaffected (button still present — harmless).

## Relay CLI (`cli/set_start_view_cmd.py`, registered in `main.py`)

`splatpipe set-start-view "<token>" [--project-path PATH]`

- Decode `SPV1:project:b64` → validate JSON shape (pos/quat len 3/4,
  finite numbers, fov in (0,180)).
- Patch Bunny: GET `…/<project>/viewer-config.json` from the storage
  origin, set `start_view`, PUT back, purge the CDN URL. Reuses
  `deploy.load_bunny_env` / `upload_file` / `purge_bunny_cache`.
- If a local project folder matches (explicit `--project-path`, else
  best-effort `projects/<name>`), also
  `Project.set_scene_config_section("start_view", pose)` so future
  re-exports keep it. The assembler already serialises whole
  `scene_config` → `viewer-config.json`, so no assembler change.
- Idempotent; re-running with a new token overwrites.

This is the command the assistant runs when the user pastes a token.

## Scope / YAGNI

In: one start pose per project; overwrite on a new Set; clipboard +
on-screen fallback; CLI relay; highest-priority initial camera + reset
seeding.

Out: multiple/per-device start views; animated intro; token expiry/auth;
any in-viewer write path (that is the future Option B — only step "relay"
changes, viewer + config stay identical).

## Test plan

- Playwright: button present; click → confirm overlay → Confirm yields a
  parseable `SPV1:` token (decode in test, assert shape).
- Inject a `start_view` into a config and verify: camera spawns there,
  Reset/Home returns there, sqrt-fallback suppressed, path/annotation no
  longer override it.
- CLI round-trip on one real Bunny project: token in →
  `viewer-config.json` on Bunny has `start_view` → reload viewer →
  camera spawns at the pose. Then revert if it was a throwaway pose.
- Deploy all 5; CHANGELOG entry; send usage + benchmark links.
