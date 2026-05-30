# Spark Viewer Template Modularization — v2 (dev-mode)

> **Supersedes** [v1 plan](./2026-05-20-modularize-spark-viewer-template.md) (shipped in
> `4ddb567`) per user direction on 2026-05-20 ~08:20:
>
> > "make a proper plan for the breakout. I do want a smaller file that's
> > easier to read into agents memory. But you need to get it right! Make
> > a real plan and trace through it to make sure everything works after
> > implementation. Stuff CAN go offline. we're in dev mode..."
>
> **v1** was conservative — 16 TDD tasks, byte-identity-per-commit, recipe-2c
> ceremony preserved throughout, multi-day estimate.
>
> **v2** is practical:
> - Dev-mode permission allows individual scenes to go offline temporarily.
> - Verification is end-to-end and batched, not per-commit.
> - The legacy excised-region byte-lock is removed during the refactor and
>   replaced with an output-pin at the end.
> - Fewer, bigger commits per logical extraction unit.
>
> The acceptance criteria shift from "every commit byte-identical for live
> scenes" to "the FINAL refactored state produces working scenes equivalent
> to pre-refactor". Trace-throughs (section 5) are the user's main quality
> bar — they are concrete, not hand-waved.

**Author:** autonomous plan session (task #117).
**Date:** 2026-05-20.
**File under spec:** `src/splatpipe/viewers/spark/template.py` (9,610 LF lines at
HEAD `5190301`; `_VIEWER_TEMPLATE` body is 460,435 bytes / ~9,485 lines).
**Companion spec (v1, still authoritative for the logical block map):**
`docs/superpowers/specs/2026-05-20-modularize-spark-viewer-template-design.md`

---

## 1. Goal

`template.py` shrinks from ~9,610 lines (almost entirely one giant Python
format-string) to a **~150-line orchestrator**. The bulk becomes **18–22
focused fragment files** under
`src/splatpipe/viewers/spark/template_parts/`, each ≤1,500 lines (with
explicit accepted outliers documented), agent-context-friendly.

Side benefits:
- Brace-doubling (`{{` / `}}` for every JS object literal) disappears from
  the fragments. The orchestrator does substitution; fragments are raw
  JS / CSS / HTML.
- The 14-region excised-region byte-lock in `tests/test_html_for_save_mode.py`
  retires — replaced by a small output-pin that hashes the generated HTML
  for a corpus of representative scene fixtures.
- The 3 NEGATIVE-CONTROL tests (`my16`/`my17`/`my18`) survive intact (they
  import a pre-fix `template.py` via `git cat-file blob`, which is
  self-contained at that historical revision).

## 2. Why v1 was rejected

1. **Too much ceremony.** 16 tasks each with their own commit, output-pin
   check, legacy lock check, full-suite check. Hours of pure verification
   overhead for an extraction that is fundamentally text-rearrangement.
2. **Recipe-2c discipline = no real refactor possible without contortion.**
   Maintaining byte-identity per-commit forced "extract one logical leaf, ship
   it, extract the next" — but the most useful fragments span dependencies.
3. **The user wants quality and traceability, not micro-step ritual.** The
   trace-throughs in this v2 are the real safety net. The output-pin at the
   end is the real assertion. Everything in between is permitted to be in
   flux.

## 3. Acceptance criteria (final state, NOT per-step)

After all extraction tasks land:

1. **`splatpipe publish` works for all 7 live scenes** (verify the slug list
   against deployed Bunny pull-zone — current known set: `kf-fehmarn`,
   `fehmarn`, `ibug`, `polygraf`, `fabrik`, `speicher`, `stettiner`. Confirm
   actual slug list at start of execution via the deploy-script inventory
   in `.kfwork/` and the user's mental list).
2. **Camera-keyframe editor works in author mode** for the active branch's
   scenes: kebab open/close, Add camera, Rename, Delete, and the
   timeline-strip diamond drag + scrub.
3. **`?bench=probe` / `?bench=rotate` / `?bench=orbit`** auto-run and
   download their JSON traces (rotate + probe also save contact sheets).
4. **`save_mode=cli` round-trip:** the viewer emits an SPCP1 token to the
   clipboard; `splatpipe set-camera-path <token>` decodes + merges + redeploys
   correctly.
5. **Cinematic playback shell** + **multi-camera Cuts** work end-to-end.
   Click-interrupt + bottom resume + idle orbit + the intro fade all behave
   as before.
6. **pytest passes** (`pytest tests/ -q` → CLEAN GREEN). The legacy byte-lock
   in `test_html_for_save_mode.py` is REPLACED by the output-pin (added; old
   one removed). Total test count moves modestly — the output-pin adds N
   parametrized cases; the legacy lock removes 1 monster test.
7. **ruff PASS** across `src` / `tests` / `tools`.
8. **No visual regression on cold-load** — eyeball one canonical scene
   (recommend `kf-fehmarn` since it has the editor + multi-camera + the
   newer SH-encoding path).

## 4. Design

### 4.1 Placeholder syntax: `@@NAME@@`

**Audit results** (run on HEAD `5190301`):

| candidate | matches in `template.py` | safe? |
|-----------|----------------------------|-------|
| `${name}` (`string.Template` default)  | **19 literal `${{...}}`** inside JS template literals (lines 8706, 8707, 8865, …) | **NO** — collision |
| `<<name>>` | 0 | safe, but `>>` is JS bitshift (2 hits at line 5431); regex must not key on `>>` alone |
| `@@name@@` | **0 hits** for `@@` | **safe** |
| `$name` (no-braces Template) | bitten by lines 6784, 8890 (`/=+$/`) | NO — collision |

**Choice: `@@NAME@@`** (uppercase by convention; A-Z + 0-9 + `_`).

Rationale:
- Zero collisions in current JS / CSS / HTML / template-literal content.
- Visually distinct from every JS / Python / CSS / HTML token. Hard to
  miss in a fragment file.
- Easy regex: `re.compile(r"@@([A-Z_][A-Z0-9_]*)@@")`.
- The orchestrator's substitution can throw loudly on any unresolved
  `@@…@@` after substitution — a safety net (TT-3).

### 4.2 File layout

```
src/splatpipe/viewers/spark/
  template.py                              # ~150 lines: orchestrator
  template_parts/
    __init__.py                            # empty package marker
    01_head.html_tmpl                      # ~15 lines  — <head> meta + share-meta
    02_styles_main.css_tmpl                # ~270 lines — body/canvas/header/stats/hint/embed
    02_styles_editor.css_tmpl              # ~30  lines — dual-UI + kebab + loading-blur
    03_body_chrome.html_tmpl               # ~90  lines — <body>, header, quality, bench-mode
    03_body_camera_select.html_tmpl        # ~60  lines — camera-select + kebab + +Add
    03_body_hud_loading.html_tmpl          # ~50  lines — stats, hints, loading, css2d, path-hud, path-mini, dual-UI roots, intro-fade
    04_js_prologue.js_tmpl                 # ~30  lines — importmap + <script type=module> + ES imports + SAVE_* / STOCK consts
    05_framework.js_tmpl                   # ~245 lines — ModeManager / OverlayScene / InteractionManager / HudLayer / __sceneview
    06_cfg.js_tmpl                         # ~65  lines — viewer cfg + _DEFAULTS
    07_setup_three_spark.js_tmpl           # ~280 lines — THREE + Spark + sparkOpts + paged_ext_splats
    08_input.js_tmpl                       # ~625 lines — URL overrides + WASD + look + pivot + focus + HUD + touch + iOS callout + annotations (B08-B16 combined)
    09_playback_spline.js_tmpl             # ~415 lines — CubicSpline + buildPlayer (B17)
    10_camera_select.js_tmpl               # ~750 lines — camera-select / kebab / dropdown wiring (B18)
    11_clip_player.js_tmpl                 # ~415 lines — ClipPlayer (B19)
    12_user_transport.js_tmpl              # ~410 lines — End-user transport + _orbitPathAround (B20)
    13_bench.js_tmpl                       # ~580 lines — Bench launchers + ?bench= auto-trigger (B21)
    14_splat_budget.js_tmpl                # ~90  lines — Splat budget dropdown (B22)
    15_editor_trajectory.js_tmpl           # ~945 lines — Author editor — trajectory overlay (B23)  [OUTLIER]
    16_editor_timeline.js_tmpl             # ~990 lines — Author editor — bottom timeline (B24)    [OUTLIER]
    17_editor_gizmo.js_tmpl                # ~2085 lines — Author editor — gizmo + Save + SPCP (B25) [HEAVY OUTLIER]
    18_frame_loop.js_tmpl                  # ~885 lines — Frame loop + bench recorder + setstart + preload IIFE (B26)
    19_intro_controller.js_tmpl            # ~125 lines — Intro controller (B27)
    99_closing.html_tmpl                   # ~10  lines — _spDebug + </script></body></html>
```

**Total: 21 fragment files** (excluding `__init__.py`).

**Median fragment size:** ~280 lines. **Three outliers** explicitly accepted
this round (gizmo/Save 2085, timeline 990, trajectory 945). Subdivision of
those into sub-fragments is deferred (separate plan/task; they are *self-
contained* author-mode-gated blocks).

**Note on B08-B16 combined into one fragment** vs v1's 8 separate input
fragments: in practice the input/annotation block is one tight reading unit
(~625 lines) that an agent loads once. Eight separate ~80-line files would
bloat the directory without buying readability. Keep as one fragment unless
a future task needs to touch them differently.

### 4.3 Orchestrator (~150 lines, sketch)

```python
"""Spark 2 viewer template — emits a self-contained index.html.

Loads a single ``scene.rad`` … (existing module docstring preserved
verbatim — same SPARK_VERSION / THREE_VERSION / SPARK_FORK_URL pins).
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

# Dunder pins — UNCHANGED from pre-refactor.
SPARK_VERSION = "2.0.0"
THREE_VERSION = "0.180.0"
SPARK_FORK_URL = "https://splatpipe-cdn.b-cdn.net/_sparkfork-rcf2/spark.module.min.js"

_PARTS_DIR = Path(__file__).parent / "template_parts"

# Match @@NAME@@ where NAME is [A-Z_][A-Z0-9_]*. Anchored to @@ on both
# sides so it never matches a bare @, @-something, or a longer @@@@.
_PLACEHOLDER = re.compile(r"@@([A-Z_][A-Z0-9_]*)@@")


@lru_cache(maxsize=1)
def _load_template_body() -> str:
    """Concatenate every ``*.html_tmpl`` / ``*.css_tmpl`` / ``*.js_tmpl``
    file in ``template_parts/`` sorted by filename. Cached per process.
    Glob-sort is stable and human-readable; the NN_ prefix orders deps."""
    chunks: list[str] = []
    for p in sorted(_PARTS_DIR.iterdir()):
        if p.suffix in (".html_tmpl", ".css_tmpl", ".js_tmpl"):
            chunks.append(p.read_text(encoding="utf-8"))
    return "".join(chunks)


def _substitute(body: str, fields: dict[str, str]) -> str:
    """@@NAME@@ -> fields[NAME]. Unknown name => KeyError (loud).
    Unsubstituted @@..@@ after the sweep => AssertionError (safety net).
    """
    def repl(m: re.Match[str]) -> str:
        name = m.group(1)
        if name not in fields:
            raise KeyError(f"unknown placeholder @@{name}@@ in template "
                           f"(known: {sorted(fields)})")
        return fields[name]
    out = _PLACEHOLDER.sub(repl, body)
    # Safety net: any @@...@@ remaining means the regex above had a bug
    # OR a fragment introduced a syntactically valid but-not-registered
    # name. Loud failure beats silent leakage.
    leftover = _PLACEHOLDER.search(out)
    assert leftover is None, (
        f"unresolved @@…@@ remains after substitution: "
        f"{leftover.group(0)!r} at offset {leftover.start()}"
    )
    return out


def html_for(
    project_name: str,
    *,
    primary_asset: str = "scene.rad",
    paged: bool = True,
    share_url: str | None = None,
    share_image: str | None = None,
    description: str | None = None,
    save_mode: str = "cli",
    save_endpoint: str | None = None,
) -> str:
    """Same signature, same docstring, same return contract as pre-refactor."""
    import html as _h

    # ... share-meta computation kept verbatim from pre-refactor (uses _e()
    #     to HTML-escape and may insert og:url at index 5) ...

    return _substitute(_load_template_body(), {
        "PROJECT_NAME": project_name,
        "SPARK_VERSION": SPARK_VERSION,
        "THREE_VERSION": THREE_VERSION,
        "SPARK_FORK_URL": SPARK_FORK_URL,
        "PRIMARY_ASSET": primary_asset,
        "PAGED_JSON": json.dumps(bool(paged)),
        "SAVE_MODE_JSON": json.dumps(save_mode),
        "SAVE_ENDPOINT_JSON": json.dumps(save_endpoint or ""),
        "SHARE_META": share_meta,
    })
```

**Note on fragment ordering:** glob-sort by filename is stable and
deterministic. The numeric prefix encodes dependency order (framework
before everything that depends on it; spline before editor; cfg before
setup; etc.). A future insertion between 14 and 15 can use `14a_` /
`145_` etc. Glob-sort handles all of these.

**Note on cache:** `lru_cache(maxsize=1)` reads fragments once per process.
The web dashboard reloads the module manually when needed (already does);
the publish CLI is one-shot. No watcher.

### 4.4 The 9 Python format-string placeholders → 9 `@@NAME@@` slots

Mapping (verified via audit script):

| pre-refactor `{name}` | post-refactor `@@NAME@@` | source of value |
|------------------------|----------------------------|------------------|
| `{project_name}`         | `@@PROJECT_NAME@@`         | kwarg |
| `{spark_version}`        | `@@SPARK_VERSION@@`        | module dunder |
| `{three_version}`        | `@@THREE_VERSION@@`        | module dunder |
| `{spark_fork_url}`       | `@@SPARK_FORK_URL@@`       | module dunder |
| `{primary_asset}`        | `@@PRIMARY_ASSET@@`        | kwarg |
| `{paged_json}`           | `@@PAGED_JSON@@`           | `json.dumps(paged)` |
| `{save_mode_json}`       | `@@SAVE_MODE_JSON@@`       | `json.dumps(save_mode)` |
| `{save_endpoint_json}`   | `@@SAVE_ENDPOINT_JSON@@`   | `json.dumps(save_endpoint or "")` |
| `{share_meta}`           | `@@SHARE_META@@`           | locally-built HTML meta lines |

**Audit-verified count:** 9 (audit script in `.tmp_audit.py` during planning;
keep that script handy as a re-runnable diagnostic if a new placeholder
appears in future).

The three "false positives" the naive regex picked up
(`decoded` / `fps` / `resident`) are JS template-literal interpolations
inside `${{…}}` doubled blocks. They un-double to bare `${…}` — they
become RAW JS in the fragment files, not orchestrator placeholders. The
orchestrator MUST NOT register them.

## 5. Extraction sequence

Five batches, ~3-4 fragments per batch. After each batch: a quick local
smoke check (render `kf-fehmarn` HTML, eyeball-load in browser). After all
batches: full re-deploy + verify of every live scene.

### Pre-flight (one-time setup before batch 1)

- **PF-1.** Confirm no third-party touched `template.py` since `5190301`:
  ```
  git log --oneline src/splatpipe/viewers/spark/template.py | head -3
  ```
  Expected: `5190301` is the most recent change. If not, rebase + retry.

- **PF-2.** Compute the pre-refactor baseline SHA for the corpus:
  ```python
  # tools/audit_template_corpus.py (NEW — committed before batch 1)
  import hashlib
  from splatpipe.viewers.spark.template import html_for
  CORPUS = [
      ("harness_defaults", ("HarnessScene",), {}),
      ("http_basic", ("S",),
        {"save_mode": "http", "save_endpoint": "https://x.example/api/save"}),
      ("http_endpoint_quotes", ("S",),
        {"save_endpoint": 'https://x/"+evil()+"'}),
      ("none_endpoint", ("S",),
        {"save_mode": "http", "save_endpoint": None}),
      ("sog_fallback", ("LegacySogScene",),
        {"primary_asset": "scene.sog", "paged": False}),
      ("share_card", ("ShareScene",),
        {"share_url": "https://splatpipe-cdn.b-cdn.net/share/index.html",
         "share_image": "https://splatpipe-cdn.b-cdn.net/share/preview.jpg",
         "description": "Custom share description text."}),
  ]
  for name, args, kwargs in CORPUS:
      h = html_for(*args, **kwargs)
      print(f"{name}: len={len(h)} sha={hashlib.sha256(h.encode()).hexdigest()}")
  ```
  Save the 6 (len, sha) tuples to a SCRATCH file
  (`docs/superpowers/plans/.scratch_2026-05-20_pre_refactor_corpus.txt`,
  NEVER committed) for use in the final output-pin (T6).

- **PF-3.** Confirm pytest GREEN, ruff GREEN.

### Batch 1 — orchestrator + leaf fragments (T1)

**T1.** Land the orchestrator + the smallest leaves in ONE commit. This is
the biggest cognitive lift of the refactor (the brace-undouble + placeholder
rewrite). If T1 is right, the rest is mechanical.

**WHAT to extract:**
- Module dunders + `html_for(...)` signature/docstring/share-meta → KEEP in `template.py`.
- `_VIEWER_TEMPLATE` body → SPLIT into fragments **AND** brace-undoubled +
  `{name}` → `@@NAME@@` substituted in a single mechanical pass.
- Initial fragments:
  - `01_head.html_tmpl` (lines 126-140)
  - `99_closing.html_tmpl` (lines 9602-9610)
  - `02_styles_main.css_tmpl` + `02_styles_editor.css_tmpl` (B02; lines 141-440)
  - `03_body_chrome.html_tmpl` + `03_body_camera_select.html_tmpl` +
    `03_body_hud_loading.html_tmpl` (B03; lines 442-623)
  - `04_js_prologue.js_tmpl` (B04; lines 625-654)
  - All remaining JS → ONE temporary fragment `00_legacy_remainder.js_tmpl`
    (lines 656-9601, brace-undoubled + placeholder-rewritten).

**HOW:**

1. Read the body string (between `_VIEWER_TEMPLATE = """\` and the closing
   `"""`).
2. Brace-undouble: `{{` → SENTINEL_OPEN; `}}` → SENTINEL_CLOSE; then
   `{name}` (the 9 known fields, exact-match — NO catchall regex) →
   `@@NAME@@`; then SENTINEL_OPEN → `{`; SENTINEL_CLOSE → `}`. Order
   matters; use sentinels to avoid double-substitution.
3. Split the resulting body at known section boundaries (use the banner
   comments — see TT-2 for boundary-recognition strategy).
4. Write each fragment + the orchestrator code.
5. Delete `_VIEWER_TEMPLATE` from `template.py`.

**HOW TO VERIFY:**

```bash
# Compute post-refactor SHA for the same corpus
python tools/audit_template_corpus.py > .scratch_2026-05-20_post_refactor_corpus.txt

# Diff
diff .scratch_2026-05-20_pre_refactor_corpus.txt \
     .scratch_2026-05-20_post_refactor_corpus.txt
```

Expected: **zero diff** (all 6 corpus entries identical lens + shas).

Then:
- `pytest tests/test_html_for_save_mode.py -k "test_defaults_bake_cli_and_empty_endpoint or test_explicit_http or test_none_endpoint or test_endpoint_with_quotes or test_html_for_has_no_secret or test_secret_value_never or test_camera_path_overlay or test_motion_ticks or test_real_gizmo_handle_drag or test_publish_call_site or test_assembler_call_site" -v`
- Expected: PASS (these tests do NOT rely on the byte-lock — they check
  HTML *output* content or call-site threading).
- `pytest tests/test_html_for_save_mode.py::test_defaults_are_regression_safe_existing_scenes_byte_identical` — EXPECTED FAIL after T1 because the
  source remainder has restructured. **This failure is expected and
  permitted in dev mode.** It is one of the tests T6 retires.
- `pytest tests/ -q --deselect tests/test_html_for_save_mode.py::test_defaults_are_regression_safe_existing_scenes_byte_identical` — expected: PASS.

**WHAT COULD BREAK:**
- Brace-undoubling misses a `{{` that's inside a JS regex or string literal
  → orchestrator throws `KeyError` on a wrong placeholder OR produces a
  syntactically-broken HTML.
- A literal `${{name}}` un-doubled to `${name}` is correct JS template
  literal — no orchestrator action — but the audit must distinguish "real
  Python placeholder" (only the 9 known names, hand-rolled exact-match)
  from "JS template literal interpolation". DO NOT use a catchall regex
  like `\{(\w+)\}` here.
- Encoding: a Windows tool writes the fragment as UTF-16 BOM → reads back
  as garbage → output-pin SHA shifts. **Always read/write fragments via
  `Path.write_text(s, encoding="utf-8")` and `Path.read_text(encoding="utf-8")`**
  — never PowerShell `>` redirection.
- Line endings: CRLF leak. Same `write_text` rule. Verify with
  `python -c "import sys; print(sys.stdin.buffer.read().count(b'\\r'))" < fragment`
  → must be 0.

**HOW TO DETECT BREAKAGE:**
- The 6-line SHA diff (above) is the canonical detector.
- The `_PLACEHOLDER` regex safety-net in `_substitute()` throws on any
  un-resolved `@@…@@`.

**ROLLBACK:**
`git checkout -- src/splatpipe/viewers/spark/template.py src/splatpipe/viewers/spark/template_parts/`
+ retry from PF-2.

### Batch 2 — framework / cfg / setup (T2)

**T2.** Split `00_legacy_remainder.js_tmpl` into `05_framework.js_tmpl` +
`06_cfg.js_tmpl` + `07_setup_three_spark.js_tmpl`.

- `05_framework.js_tmpl`: from `// ============` + `Unified SceneView
  framework` (line ~656) through (exclusive) `// ---- Viewer config ----`
  (line ~900).
- `06_cfg.js_tmpl`: `// ---- Viewer config ----` through (exclusive)
  `// ---- THREE + Spark setup ----` (line ~965).
- `07_setup_three_spark.js_tmpl`: `// ---- THREE + Spark setup ----`
  through (exclusive) `// ---- Detail-lever URL overrides …` (line ~1244).

**VERIFY:** Re-run T1's SHA-diff. Expected zero diff.

### Batch 3 — input + spline + camera-select (T3)

**T3.** Three fragments:
- `08_input.js_tmpl`: B08-B16 combined; banner `// ---- Detail-lever URL
  overrides ---` through (exclusive) `// ---- Camera-path playback ---`
  (line ~1935).
- `09_playback_spline.js_tmpl`: B17; `// ---- Camera-path playback ---`
  through (exclusive) the next `// ============` block at line ~2348.
- `10_camera_select.js_tmpl`: B18; `// ============` + `Camera selector
  — single-list union` (line 2348) through (exclusive) `// ============` +
  `ClipPlayer (Task 14` (line ~3097).

**VERIFY:** Re-run T1's SHA-diff. Expected zero diff.

**BREAK CHECK:** The spline + camera-select are dependency roots for the
editor surfaces in batch 5. If the spline-camera-select interaction
("camera-select calls into buildPlayer") got broken by an extraction
boundary, the editor tests fail loudly. Light smoke: open `kf-fehmarn` in
the dashboard preview and click through the camera dropdown — perspective
+ each named camera should switch correctly.

### Batch 4 — playback (clip player + transport + bench + budget) (T4)

**T4.** Four fragments:
- `11_clip_player.js_tmpl`: B19; `// ============` + `ClipPlayer (Task 14`
  (line 3097) through (exclusive) `// ============` + `End-user transport`
  (line ~3509).
- `12_user_transport.js_tmpl`: B20; `// ============` + `End-user
  transport` through (exclusive) `// ---- Bench launchers …` (line ~3916).
- `13_bench.js_tmpl`: B21; `// ---- Bench launchers …` through (exclusive)
  `// ---- Splat budget dropdown ---` (line ~4494).
- `14_splat_budget.js_tmpl`: B22; `// ---- Splat budget dropdown ---`
  through (exclusive) `// ============` + `Author editor — viewport
  trajectory` (line ~4581).

**VERIFY:** Re-run T1's SHA-diff. Expected zero diff.

**SMOKE CHECK** (recommended at this batch boundary): cold-load
`kf-fehmarn` in `?bench=probe` mode and confirm a trace downloads. The
bench-related JS is large and bench mode exercises the bulk of the
playback / preload code path.

### Batch 5 — editor + frame loop + intro (T5)

**T5.** Five fragments (largest batch):
- `15_editor_trajectory.js_tmpl`: B23; `// ============` + `Author editor
  — viewport trajectory` (line 4581) through (exclusive) `// ============`
  + `Author editor — bottom timeline` (line ~5525). **~945 lines.**
- `16_editor_timeline.js_tmpl`: B24; `// ============` + `Author editor
  — bottom timeline` (line 5525) through (exclusive) `// ============` +
  `Author editor — select-key gizmo` (line ~6512). **~990 lines.**
- `17_editor_gizmo.js_tmpl`: B25; `// ============` + `Author editor —
  select-key gizmo` (line 6512) through (exclusive) `// ---- Frame loop
  ---` (line ~8597). **~2085 lines.**
- `18_frame_loop.js_tmpl`: B26; `// ---- Frame loop ---` (line 8597)
  through (exclusive) `// ============` + `Intro controller (Task 13`
  (line ~9481). **~885 lines.**
- `19_intro_controller.js_tmpl`: B27; `// ============` + `Intro
  controller (Task 13` (line 9481) through (exclusive) `// Debug hook for
  Playwright smoke tests` (line ~9605; that line is already in
  `99_closing.html_tmpl` from T1). **~125 lines.**

After T5: delete `00_legacy_remainder.js_tmpl` — it must be empty.

**VERIFY:** Re-run T1's SHA-diff. Expected zero diff.

**SMOKE CHECK** (mandatory at this batch boundary, the heaviest):
1. Cold-load `kf-fehmarn?author=1` in the browser.
2. Open the camera-select kebab → Add a new camera "Test".
3. Press R to record a couple of keyframes.
4. Press the timeline diamond, drag it — confirm camera updates live.
5. Press the Save button → confirm an SPCP1 token lands on the clipboard
   that looks like `SPCP1:test:...`.
6. Press the `Set start view` button → confirm the SPV1 token + Claude
   relay UI shows.
7. Hit Esc → reload without `?author=1` → confirm the end-user transport
   appears and the auto-tour starts.

If any of these is broken: the offending fragment was extracted with a
wrong boundary. Bisect by reverting the most recently-extracted fragment
and re-checking.

### Batch 6 — output-pin retire (T6)

**T6.** Add the output-pin test, remove the legacy excised-region byte-lock.

- **Add:** `tests/test_html_for_output_pin.py`:
  ```python
  """Output-pin byte-lock — modularization-safe successor to the
  excised-region lock. Pins (len, sha256) of html_for(...) for a corpus
  of representative scene fixtures.
  """
  import hashlib
  import pytest

  from splatpipe.viewers.spark.template import html_for

  # CORPUS: list of (name, args, kwargs, expected_len, expected_sha256)
  # Pins from PF-2 pre-refactor baseline.
  CORPUS = [
      ("harness_defaults",
       ("HarnessScene",), {},
       <LEN_HARNESS_FROM_PRE_REFACTOR>,
       "<SHA_HARNESS_FROM_PRE_REFACTOR>"),
      # ... 5 more entries from .scratch_2026-05-20_pre_refactor_corpus.txt
  ]

  @pytest.mark.parametrize("name,args,kwargs,expected_len,expected_sha",
                            CORPUS, ids=[c[0] for c in CORPUS])
  def test_output_pin(name, args, kwargs, expected_len, expected_sha):
      html = html_for(*args, **kwargs)
      assert len(html) == expected_len, (
          f"[{name}] length drift: {len(html)} != {expected_len}")
      actual = hashlib.sha256(html.encode()).hexdigest()
      assert actual == expected_sha, (
          f"[{name}] sha256 drift: {actual} != {expected_sha}")

  def test_corpus_count_sanity():
      assert len(CORPUS) >= 4, "corpus drop-detection (≥4 fixtures expected)"
  ```

- **Remove from `tests/test_html_for_save_mode.py`:**
  - All `_PRE_TASK*_REMAINDER_*` / `_PRE_TASK*_FULL_*` pin constants.
  - All `_T*_*_START` / `_T*_*_END` anchor consts (`_T12_CSS`, `_T12_DOM`,
    `_T12_MM`, `_T13_LB`, `_T13_AS`, `_T13_IC`, `_T14_PW`, `_T14_AF`,
    `_T15_OB`, `_T16_TRAJ`, `_T19_CSS`, `_T19_JS`, `_T20_CAMSEL_DOM`,
    `_SPLINE_REGION`).
  - The `_excise(...)` helper.
  - The 700-line `test_defaults_are_regression_safe_existing_scenes_byte_identical` function.

- **KEEP** in `tests/test_html_for_save_mode.py`:
  - `_INSERT_ANCHOR`, `_SECRET_SENTINEL`, `_drain` helper (still used).
  - All `test_defaults_bake_cli_and_empty_endpoint`,
    `test_explicit_http_mode_and_endpoint_are_baked`,
    `test_none_endpoint_serialises_to_empty_string`,
    `test_endpoint_with_quotes_is_json_escaped_not_injected`,
    `test_html_for_has_no_secret_kwarg`,
    `test_secret_value_never_appears_in_generated_html`.
  - All NEGATIVE-CONTROL tests: `test_camera_path_overlay_is_scene_relative_not_fixed`,
    `test_motion_ticks_are_tiny_white_and_line_has_gradient`,
    `test_real_gizmo_handle_drag_wiring_present_and_author_tour_suppressed`.
  - The `_git_blob_module(...)` helper (used by my16/17/18 NEGATIVE-CONTROLs;
    loads a self-contained pre-fix `template.py` blob — works regardless of
    HEAD's structure).
  - All `test_publish_call_site_*`, `test_assembler_call_site_*`.

- **Add a brief docstring** to the file explaining the retirement (the
  `tests/test_html_for_save_mode.py` module now only carries the
  kwarg-shape tests + the 3 NEGATIVE-CONTROL tests + the publish/assembler
  call-site tests; the byte-lock has moved to `test_html_for_output_pin.py`).

**VERIFY:**
- `pytest tests/test_html_for_output_pin.py -v` → all parametrize cases PASS.
- `pytest tests/test_html_for_save_mode.py -v` → all retained tests PASS;
  total file's test count drops by 1 (the monster lock).
- `pytest tests/ -q` → CLEAN GREEN. Net test count moves modestly:
  ~+5 (output-pin) ~-1 (legacy lock) = ~+4.
- `ruff check src tests tools` → PASS.

### Final acceptance (after T6)

1. **Redeploy each live scene** via its bespoke `.kfwork/deploy_*.py` script
   OR via `splatpipe publish` for the projects that use it. Open each in
   the browser. Confirm cold-load, camera-paths play, no console errors.

2. Update `CLAUDE.md` Package Layout to reflect the new
   `viewers/spark/template_parts/` directory (the 21 fragments + the
   orchestrator).

3. Update `CHANGELOG.md` with an `[Unreleased]` entry:
   ```
   ### Changed
   - Spark viewer template refactored from a single ~9.6k-line string
     into 21 focused fragment files under `viewers/spark/template_parts/`.
     Orchestrator loads + concatenates fragments + substitutes via the
     `@@NAME@@` placeholder protocol. Generated HTML byte-identical for
     every test fixture and every deployed scene at the time of refactor.
     Brace-doubling pain is gone.
   - Replaced excised-region byte-lock with output-pin
     (`tests/test_html_for_output_pin.py`).

   ### Removed
   - `tests/test_html_for_save_mode.py::test_defaults_are_regression_safe_existing_scenes_byte_identical`
     and its 14 source-anchor constants (replaced by the output-pin).
   ```

## 6. Trace-throughs (CRITICAL — the user's main quality bar)

Each TT is a concrete question with a concrete trace. Where the v1 plan
hand-waved, I trace.

### TT-1: Generated HTML byte-identity after fragment extraction

**Question:** How do we guarantee `html_for(...)` produces the same bytes
after extraction?

**Trace:**

The body of `_VIEWER_TEMPLATE` is 460,435 bytes. `html_for("HarnessScene")`
returns 458,679 bytes (verified at HEAD). The diff is the share-meta + the
9 placeholder substitutions (small).

After extraction:
- Each fragment file is **UTF-8, LF-only, with the exact original bytes**
  for its span. The orchestrator reads each fragment with
  `Path.read_text(encoding="utf-8")` (which decodes UTF-8 + keeps `\n`
  newlines as-is) and concatenates with `"".join(...)`. Concatenation =
  body if and only if **every fragment boundary aligns with a `\n`
  boundary in the original body** AND the brace-undoubling +
  placeholder-rewrite are perfect inverses of the original.

Verification command:
```bash
# Compute corpus SHAs before + after
python tools/audit_template_corpus.py
diff .scratch_2026-05-20_pre_refactor_corpus.txt \
     .scratch_2026-05-20_post_refactor_corpus.txt
```

Expected: **zero diff** for all 6 entries. Any drift means one of:

1. **Boundary not on `\n`**: a fragment starts mid-line. Hyper-rare with
   the banner-comment boundaries (banners are at column 0 lines); but
   defensively, the post-extraction diff catches it.
2. **Encoding leak**: the fragment was written as UTF-16 LE BOM or with
   CRLF. The orchestrator reads BOM bytes verbatim → output has BOM → SHA
   shifts. Detector: the first byte of the concatenation is `\xef\xbb\xbf`
   (UTF-8 BOM) or `\xff\xfe` (UTF-16 LE BOM). Sanity:
   `python -c "import pathlib; print(pathlib.Path('viewers/spark/template_parts/01_head.html_tmpl').read_bytes()[:4])"` should print `b'<!DO'`.
3. **Brace-undouble inverse mistake**: `{{` → `{` on one side, but the
   reverse `{` → `{{` in some new generation step is missing. Since we're
   replacing `_VIEWER_TEMPLATE.format()` with `_substitute()`, there is NO
   reverse step — `string.format()` is gone. So this can't happen by
   accident. (It WOULD happen if someone re-introduced a `.format()` call
   later. Guard: ruff config could forbid `.format()` calls on the loaded
   body. Light recommendation; not mandatory.)
4. **A placeholder rewrite mistake**: a `{project_name}` got
   `@@PROJECTNAME@@` (typo'd). The audit catches it — the SHA shifts AND
   the `_PLACEHOLDER` regex's safety net fires (`@@PROJECTNAME@@` not in
   the orchestrator's field dict → `KeyError`).

**Mitigation:**
- Before-and-after SHA diff at every batch boundary (T1, T2, T3, T4, T5).
- The orchestrator's `_substitute()` safety net (KeyError on unknown name +
  AssertionError on any leftover `@@…@@` after substitution).

### TT-2: Brace-undoubling correctness

**Question:** When extracting JS from `_VIEWER_TEMPLATE` (where `{` is
escaped as `{{`), we must un-double to single `{` in the fragment file.
How do we do this safely?

**Trace:**

The brace map of the body (audit script output):
- `{{`: **1,390 instances** (Python-format escape for `{`)
- `}}`: **1,389 instances** (one orphan — common from line-spanning
  closures where the `}}` closer ends a multi-line `function() {{ ... }}`
  and the opener was on a prior line — they balance over the file)
- `{name}`: **9 distinct Python format-string fields** (audit-verified
  exact list above; 11 names match the naive regex but 3 are inside `{{
  ${decoded} }}` interpolations and are not Python fields).
- ES template literal `${{…}}`: **19 instances** (lines 8706, 8707, 8865,
  etc. — `${{window.innerWidth}}` etc.).
- Solo `{` or `}` after stripping `{{` / `}}` / `{name}`: **0**
  (audit-verified).

Un-doubling algorithm (sentinels prevent double-substitution):
```python
SENT_OPEN = "\x00ZZ_OPEN\x00"
SENT_CLOSE = "\x00ZZ_CLOSE\x00"

body = body.replace("{{", SENT_OPEN)        # 1390 → 0 / 0 → 1390
body = body.replace("}}", SENT_CLOSE)       # 1389 → 0 / 0 → 1389

# After these two: every remaining { and } MUST be a Python placeholder
# (since solo-brace count was 0 in audit). EXACT-MATCH the 9 known names
# — DO NOT use a catchall regex.
for python_name, at_at_name in [
    ("project_name", "PROJECT_NAME"),
    ("spark_version", "SPARK_VERSION"),
    ("three_version", "THREE_VERSION"),
    ("spark_fork_url", "SPARK_FORK_URL"),
    ("primary_asset", "PRIMARY_ASSET"),
    ("paged_json", "PAGED_JSON"),
    ("save_mode_json", "SAVE_MODE_JSON"),
    ("save_endpoint_json", "SAVE_ENDPOINT_JSON"),
    ("share_meta", "SHARE_META"),
]:
    src_str = "{" + python_name + "}"
    dst_str = "@@" + at_at_name + "@@"
    if src_str not in body:
        raise RuntimeError(f"expected placeholder {src_str!r} not found")
    body = body.replace(src_str, dst_str)

# Sanity: no solo { or } should remain.
assert "{" not in body, "solo { remains — un-double missed a {{"
assert "}" not in body, "solo } remains — un-double missed a }}"

# Restore literal braces (becomes plain JS / CSS object braces).
body = body.replace(SENT_OPEN, "{")
body = body.replace(SENT_CLOSE, "}")
```

**Why this is byte-safe:**

1. **Sentinels are byte sequences guaranteed absent from JS / CSS / HTML
   content** (`\x00` NUL is the discriminator).
2. **Exact-string `.replace()` on the 9 known names** is collision-free
   because the body's solo-brace count is 0 after step 1+2.
3. **The final restore is byte-identical** to inserting `{` / `}` where the
   sentinels were.

**Edge case — ES template literals (the `${{...}}` blocks):**

`${{window.innerWidth}}` → after step 1: `$<SENT_OPEN>window.innerWidth<SENT_CLOSE>` → after step 5: `${window.innerWidth}`. This is the CORRECT JS template
literal syntax — the fragment file has raw `${window.innerWidth}` exactly
as a JS author would write it. The orchestrator's `_PLACEHOLDER` regex
`@@([A-Z_][A-Z0-9_]*)@@` does NOT match `${...}` — they are distinct prefixes.
**No collision.**

**Verification:**
- After step 5: the body has `${window.innerWidth}` as raw JS — no further
  Python action needed.
- The orchestrator's `_substitute()` runs `@@NAME@@` substitution; the
  `${...}` strings pass through untouched and reach the browser as valid
  JS template-literal interpolations at runtime.

### TT-3: Placeholder migration exhaustiveness

**Question:** Every `{varname}` in `_VIEWER_TEMPLATE` is a Python format
placeholder. When extracted, we rewrite `{varname}` → `@@VARNAME@@`. How
do we guarantee no placeholder is missed?

**Trace:**

Pre-flight audit (proven by running the audit script):
```
placeholders found: ['decoded', 'fps', 'paged_json', 'primary_asset',
                     'project_name', 'resident', 'save_endpoint_json',
                     'save_mode_json', 'share_meta', 'spark_fork_url',
                     'three_version']
```

11 candidate names match the naive `\{(\w+)\}` regex. **9 of them are
real Python fields** (cross-referenced against the `html_for` Python code
that does `.format(...)`):
- `{project_name}` `{spark_version}` `{three_version}` `{spark_fork_url}`
  `{primary_asset}` `{paged_json}` `{save_mode_json}` `{save_endpoint_json}`
  `{share_meta}` → all listed in `html_for`'s `.format(...)` call site
  (lines 112-121).

**3 are FALSE POSITIVES** — JS template-literal interpolations inside
`${{...}}` doubled blocks (the inner `{...}` matches the naive regex):
- `decoded` (line 9438): `${{decoded}}` (un-doubles to `${decoded}` — JS
  template literal)
- `fps` (line 8971): `${{fps}}` (same)
- `resident` (line 9436): `${{resident}}` (same)

**The un-doubling algorithm (TT-2) does NOT touch them** because the
algorithm rewrites only the 9 KNOWN Python-field placeholders by exact
string match (`{project_name}` → `@@PROJECT_NAME@@` etc.) — it does NOT
do a catchall regex over `{...}`. The 3 false positives are inside
sentinel-protected `{{` / `}}` and stay as part of the un-double restore.

**Safety net:**

After substitution + concatenation, the orchestrator's `_substitute()` runs
`_PLACEHOLDER.search(out)` over the resulting HTML. ANY leftover `@@...@@`
sequence triggers an AssertionError loud. This is the catch-all in case a
NEW placeholder is added to a fragment later but the orchestrator's field
dict isn't updated.

**Verification:**
- Before T1, run audit script; confirm placeholder list. Add an assertion
  in T1's extraction pass that the 9 known names appear at least once each
  in the body.
- After T1, `pytest tests/test_html_for_output_pin.py` (added in T6) is
  the canonical verifier.

### TT-4: Byte-lock evolution

**Question:** `tests/test_html_for_save_mode.py` currently pins a 151,172
length / SHA-256 remainder of `template.py` SOURCE bytes (after excising
14 named regions). The refactor breaks the source-level pin. What replaces
it?

**Trace:**

The GOAL of the byte-lock has always been: **"generated HTML stays
byte-identical for known scenes"**. The 14-region excision was an
approximation — it bounded *source* drift outside named regions. But:

1. It cannot see inside the regions (which now hold ~5,000 lines of editor
   code).
2. It is source-coupled — any line move (even one byte!) breaks it.
3. It only covers `HarnessScene` (the single corpus entry).

The OUTPUT-pin is the right invariant. It hashes `html_for(scene_args)`
for a **corpus of fixtures** and asserts the bytes are unchanged. It
survives ANY source restructuring as long as the bytes come out the same.

**Corpus design (matches v1 spec §5.3 minus the live-production-scenes
entries — those need values fetched from production at T6 time):**

```python
CORPUS = [
    # Defaults — the same fixture the legacy lock covered.
    ("harness_defaults", ("HarnessScene",), {}),
    # http + endpoint
    ("http_basic", ("S",), {"save_mode": "http",
                            "save_endpoint": "https://x.example/api/save"}),
    # Endpoint with quotes (JSON escape edge case)
    ("http_endpoint_quotes", ("S",),
        {"save_endpoint": 'https://x/"+evil()+"'}),
    # None endpoint
    ("none_endpoint", ("S",),
        {"save_mode": "http", "save_endpoint": None}),
    # SOG fallback path
    ("sog_fallback", ("LegacySogScene",),
        {"primary_asset": "scene.sog", "paged": False}),
    # Share-card with all metadata
    ("share_card", ("ShareScene",),
        {"share_url": "https://splatpipe-cdn.b-cdn.net/share/index.html",
         "share_image": "https://splatpipe-cdn.b-cdn.net/share/preview.jpg",
         "description": "Custom share description text."}),
]
```

**6 fixtures** — exercises every kwarg branch in `html_for`. Adding more
fixtures (e.g. snapshots of the actual live scenes once we have their
exact share_url/image/description values) is trivial: just append a
`(name, args, kwargs, len, sha)` tuple.

**Implementation:** see T6 (section 5 above) for the concrete test code.

### TT-5: Deploy verification cadence

**Question:** What's the verify cadence in dev mode? Per-commit is
overkill; verify-only-at-end is too risky.

**Trace:**

**Recommendation:** **Verify at every batch boundary** (5 batches in
section 5 = 5 verification points), AND a final end-to-end verify after T6.

Verification at each batch boundary is light (~2 minutes):
- Run the corpus-SHA diff (TT-1 verification command).
- Run the smoke check (a quick `kf-fehmarn` cold-load + dropdown click).

This catches a regression within ~3-4 fragment extractions, so the bisect
to find the offending fragment is small (one batch = 3-5 fragments).

**Why not per-commit?** Per-commit verification is what v1 demanded and
the user explicitly rejected. The brace-undouble + 9 placeholder rewrites
happen in T1 — once T1 is right, every subsequent T is a pure split of
the already-correct `00_legacy_remainder.js_tmpl` at a `\n` boundary,
which is trivially byte-safe by construction.

**Why not end-only?** A bug introduced in T2 that survives through T5
requires bisecting 5 batches × ~5 fragments each = 25 files. Bisecting
1 batch × 5 fragments is much faster.

### TT-6: Tests that read template.py source directly

**Question:** Any test that opens `template.py` as text and inspects it
for patterns? After the refactor, those tests break.

**Trace:**

Grep result: `_VIEWER_TEMPLATE` + `template.py` references in `tests/`:
- `tests/test_html_for_save_mode.py` — extensively. This is the byte-lock
  file. T6 retires it.
- `tests/test_scene_cuts.py:124` — comment-only reference. No code dependency.

Additional check — anything that imports `_VIEWER_TEMPLATE` from outside
`viewers/spark/template.py`:
```
src/splatpipe/cli/serve_cmd.py:21    — refers to steps/lod_assembly._VIEWER_TEMPLATE (PlayCanvas, different file — UNRELATED)
src/splatpipe/steps/lod_assembly.py:49 — defines its OWN _VIEWER_TEMPLATE (PlayCanvas, UNRELATED)
```

The Spark `_VIEWER_TEMPLATE` is private to `viewers/spark/template.py`
and is **only consumed via `html_for(...)`**. Two external importers exist
(`steps/publish.py:51`, `viewers/spark/assembler.py:32`,
`viewers/spark/_gen_harness_viewer.py:30`); all use `from .template import
html_for`. None reference `_VIEWER_TEMPLATE`. **No external consumer
breaks.**

**Therefore:** the ONLY test that needs rewriting is
`tests/test_html_for_save_mode.py::test_defaults_are_regression_safe_existing_scenes_byte_identical`. T6 handles this.

The NEGATIVE-CONTROL tests (`test_camera_path_overlay_is_scene_relative_not_fixed`,
`test_motion_ticks_are_tiny_white_and_line_has_gradient`,
`test_real_gizmo_handle_drag_wiring_present_and_author_tour_suppressed`)
use `_git_blob_module()` to load a HISTORICAL `template.py` blob via
`git cat-file blob`. The HISTORICAL blob is the OLD `template.py` (with
the giant `_VIEWER_TEMPLATE` string) — self-contained at that revision,
imports fine, exposes `html_for(...)`. The NEW post-refactor `template.py`
on HEAD also exposes `html_for(...)`. The NEGATIVE-CONTROL tests call
`html_for("HarnessScene")` on BOTH (HEAD + pre-fix blob) and compare the
HTML output. Both work. **These tests survive intact.**

### TT-7: Live deployed scenes (already-shipped HTML on CDN)

**Question:** Do the refactor changes affect already-deployed scenes?

**Trace:**

A deployed scene on Bunny is a frozen static HTML file. The browser
fetches it and runs the JS. The HTML doesn't re-evaluate Python.

**Therefore:** the refactor only affects scenes that we redeploy
DURING/AFTER the refactor. Scenes that were deployed before the refactor
keep working unchanged until we redeploy them.

**Implication:** we can pace the redeploys however we want. Live traffic
to existing slugs is unaffected during the refactor itself.

**Post-refactor verification plan:**
1. Re-run a `splatpipe publish` (or the bespoke `.kfwork/deploy_*.py`
   script) for each live slug to redeploy a fresh `index.html`.
2. Compare against the corpus SHA (TT-1) — for the slugs in the corpus,
   the SHA must match.
3. Visual cold-load eyeball for the slugs not in the corpus.

### TT-8: Brace-undoubling automation safety (edge cases)

**Question:** Regex `{{` → `{` is simple, but what if some JS literal
ACTUALLY needs `{{` (e.g. JSX-style)? Or what if a comment contains `{{`?

**Trace:**

JSX is NOT used in this template — the audit confirms only JS template
literals (the `${{...}}` escapes mapped to `${...}` after un-doubling).

Comments containing `{{`: audit shows comments use `//` (line-comment) or
`/* ... */` (block-comment) syntax, neither of which has `{{`/`}}` escape
semantics. A comment text like `// note: {{count}}` would be un-doubled
to `// note: {count}` — still a comment, still byte-equivalent to what
`.format(...)` would have produced. (The pre-refactor Python `.format(...)`
would either substitute `count` if it were a field — which it isn't, hence
the `KeyError` would have been a pre-existing bug — or leave it alone with
a doubled `{{count}}`.)

**Mitigation:** TT-1's SHA-diff is the final safety net. If un-doubling
collides with anything, the diff catches it.

### TT-9: Order of extraction

**Question:** What order to extract fragments? Risky-first or easy-first?

**Recommendation:** **Easy-first**.

Rationale:
- T1 (orchestrator + brace-undouble + smallest leaves) is the only HARD
  step. After T1 is right, every subsequent T is a pure `\n`-boundary
  split of the already-correct `00_legacy_remainder.js_tmpl`.
- T1 isolates the risk: if T1 fails, only T1 needs revisiting. The smallest
  leaves (head, closing, CSS, body chrome) are byte-isomorphic to their
  pre-refactor positions — they have no JS embedded, so no `{{` un-doubling
  needed beyond placeholder substitution.
- T2-T5 grow in complexity from framework (T2) → editor (T5). The
  editor's interdependencies with the spline (T3) + camera-select (T3)
  + clip-player (T4) mean if any of those is wrong, T5 surfaces it loudly.

**Alternative considered:** start with the editor (T5) — it's the
largest, most-interdependent surface. **Rejected** because if T5
extraction is wrong, the agent that wrote it doesn't have the easy-first
batches to compare against. Easy-first is the safer learn-by-doing path.

### TT-10: Branch strategy

**Question:** New branch off `feat/camera-keyframe-editor`? Off `main`
after the editor PR merges? Continue on this branch?

**Recommendation:** **Continue on `feat/camera-keyframe-editor` (the
current branch)**.

Rationale:
- The user is in dev mode; the editor PR (#108? — unclear from this
  context — verify the live PR number) is still being shaped. Forking a
  new branch off main now would require either:
  - Merging the editor first (premature; user is iterating);
  - OR rebasing the refactor across the editor's `template.py` edits at
    merge time (a merge conflict on every fragment is much worse than
    one merge conflict on `template.py`).
- The refactor will be a series of ~6 commits (one per batch + T6). All
  land on `feat/camera-keyframe-editor` before the next editor task.
- After the refactor lands on `feat/camera-keyframe-editor`, subsequent
  editor commits modify ONE fragment file at a time — no more
  recipe-2c gymnastics on the 9.6k-line monolith.

**Alternative considered:** dedicated `refactor/spark-template-modular`
branch. Rejected: adds a merge step + the rebase pain noted above.

**[USER-CONFIRM]** if user prefers a dedicated branch instead, that's the
ONLY question on this — recommend continuing on `feat/camera-keyframe-editor`
as the default.

## 7. Risks + mitigations

| Risk | Mitigation |
|------|-----------|
| Someone else commits to `template.py` during the refactor → merge conflict | Refactor on a dedicated branch (or `feat/camera-keyframe-editor` if no parallel work expected). Small batches, rebase often. Realistic estimate: 1 working day, low probability of a parallel commit. |
| An extracted fragment's runtime semantics differ from inline (closure scoping) | Extraction is text-level. The orchestrator concatenates fragments into ONE string before the browser sees them. NO closure boundary crossed. The whole `_VIEWER_TEMPLATE` body remains ONE IIFE-equivalent JS surface. |
| Brace-undoubling collides with a JS regex / string literal containing `{{` | Audit pre-T1: confirm only the 9 known Python fields + 19 ES `${{…}}` blocks; no JSX. **Confirmed via audit script.** TT-1 SHA-diff is the final guard. |
| Encoding leak (UTF-16 BOM, CRLF) on Windows | Always use `Path.read_text(encoding="utf-8")` / `Path.write_text(s, encoding="utf-8")`. Never PowerShell `>` redirection. CI: a small test in `test_html_for_output_pin.py` could byte-assert no BOM bytes in any fragment file. |
| Output-pin pin drift unexpected at T6 | If T6's SHA-diff vs PF-2 baseline is nonzero, something in T1-T5 was wrong. Bisect by batch. The orchestrator's `_substitute()` safety net `_PLACEHOLDER.search(out) is None` would also catch leftover placeholders. |
| `string.Template` semantics surprise vs `str.format` | We're NOT using `string.Template` — we're using a custom `@@NAME@@` regex sub. Avoids `string.Template`'s `$$` literal-dollar rule entirely. Wins also: no rule for identifier name characters (we hard-code `[A-Z_][A-Z0-9_]*`). |
| A future fragment adds a NEW Python field | The orchestrator's `_PLACEHOLDER` regex will match `@@NEW_FIELD@@`, the `_substitute()` `KeyError` will be loud. The fix is: add the field to the dict in `html_for(...)`. Self-documenting. |
| Live scene visual regression | The corpus output-pin covers the byte invariant for the corpus fixtures. The visual eyeball at the end of the refactor + the smoke check at every batch boundary covers the rest. |
| Tests in `test_html_for_save_mode.py` that DEPEND on the byte-lock fail | They DO fail at T1 (expected). Deselect them in the pytest invocations during T1-T5; restore at T6 by removing them entirely. |
| Bespoke `.kfwork/deploy_*.py` scripts use a hardcoded `template.py` import | All scripts use `from splatpipe.viewers.spark.template import html_for`. The orchestrator preserves `html_for`'s signature + return contract. **No `.kfwork/` script breaks.** |

## 8. Estimated effort

**Realistic ranges** (now that v1's ceremony is dropped):

- **For a focused engineer with deep `template.py` knowledge:** ~6-8 hours
  (1 working day). T1 is the dense step (~3 hours); T2-T5 are mechanical
  splits (~30 min each); T6 is cleanup (~1 hour).
- **For an agent-driven extraction with verify-at-end-of-batch cadence:**
  ~10-12 hours wall-clock, less concurrent agent time. The agent can
  parallelize T2-T5 partially (each is an independent split of the
  remainder file — except they all WRITE to the same file, so they must
  serialize).
- **With one unexpected blocker** (e.g. a brace-undouble surprise): add
  ~2 hours.

**Range: 8 to 12 hours for an agent-driven extraction; 6 to 10 hours for
a human.**

This is **substantially less** than v1's 1.5-3 working days, because:
- Per-commit byte-identity ceremony is dropped (≥10 verification cycles
  saved across 16 tasks).
- Batches of 3-5 fragments per commit reduce commit overhead.
- The brace-undouble strategy is concrete (single mechanical pass in T1,
  verified by one SHA-diff).

## 9. [USER-CONFIRM] open items

Genuinely-ambiguous items the user should decide. Defaults proposed; ask
once at execution kickoff.

1. **Branch strategy.** Default: continue on `feat/camera-keyframe-editor`.
   Alternative: dedicated `refactor/spark-template-modular` off main after
   the editor PR merges. Recommend the default unless user prefers
   isolation.

2. **Output-pin corpus.** Default: the 6 synthetic fixtures listed in TT-4
   (covers every kwarg branch). Alternative: add the 7 live production
   scenes — but that requires fetching their exact `share_url` /
   `share_image` / `description` values from the deployed `index.html`
   (or from each scene's `.kfwork/deploy_*.py`). Recommend the default
   for first pass; add live scenes in a follow-up if/when needed.

3. **Sub-divide the heavy outliers (B23 945 / B24 990 / B25 2085 lines)?**
   Default: defer to a follow-up. These are coherent author-mode surfaces;
   sub-dividing further requires per-feature context the refactor doesn't
   have. Recommend: ship the first split, revisit after.

4. **Mid-refactor scene-offline tolerance.** Default: dev-mode permission
   granted; verification at batch boundaries (5 verification points). Recommend
   the default. **No deploy mid-refactor recommended** unless the user
   explicitly requests one — the corpus output-pin will catch any drift
   once T6 lands; verifying mid-refactor live deploys is wasted effort.

## 10. Provenance

- **v1 spec:** [`docs/superpowers/specs/2026-05-20-modularize-spark-viewer-template-design.md`](../specs/2026-05-20-modularize-spark-viewer-template-design.md)
- **v1 plan:** [`docs/superpowers/plans/2026-05-20-modularize-spark-viewer-template.md`](./2026-05-20-modularize-spark-viewer-template.md) (shipped in `4ddb567`)
- **User direction triggering v2:** verbatim message on 2026-05-20 ~08:20:
  > "make a proper plan for the breakout. I do want a smaller file that's
  > easier to read into agents memory. But you need to get it right! Make
  > a real plan and trace through it to make sure everything works after
  > implementation. Stuff CAN go offline. we're in dev mode..."
- **Audit findings (this plan):**
  - Source = `5190301` (HEAD at plan time).
  - `_VIEWER_TEMPLATE` body = 460,435 bytes.
  - `html_for("HarnessScene")` = 458,679 bytes, SHA
    `4d159096d4e8e891df023662102f921539b37b0011c462095100293e37084fab`.
  - Brace counts: 1,390 `{{` / 1,389 `}}` / 0 solo `{` or `}` after strip.
  - Python format-string fields: 9 (audit-verified, listed in 4.4).
  - `${` literal collisions (with v1's `string.Template` choice): **19**
    (ES template literals in bench profile + bench filename) — **rules
    out `${name}` placeholder syntax**. **`@@NAME@@` chosen** (zero
    collisions in source).
  - Importers of `html_for`: 3 (`steps/publish.py`, `viewers/spark/assembler.py`,
    `viewers/spark/_gen_harness_viewer.py`). All use
    `from .template import html_for`. None import `_VIEWER_TEMPLATE`.
  - Bespoke deploys in `.kfwork/`: all import `html_for` only. Untouched.

---

*This v2 plan supersedes v1 but does not delete it (provenance kept).*
