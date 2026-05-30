# Spec — Modularize Spark Viewer Template (#112)

**Status:** SPEC + PLAN only (this document + the paired plan).
**File under spec:** `src/splatpipe/viewers/spark/template.py` (9,610 LF lines as of HEAD `18263dd`).
**Generated HTML size:** ~458,679 bytes for `html_for("HarnessScene")` (post-task-20 SH-encoding pin).
**Author:** autonomous spec session (task #112).
**Date:** 2026-05-20.

---

## 1. Goals

1. **Maintainability.** A single ~9.6k-line file makes any change feel high-stakes. Concerns are interleaved (CSS next to DOM next to JS next to byte-lock anchor comments). Splitting by concern unlocks faster navigation, smaller diffs, smaller blast radius per change.
2. **Smaller, focused files.** Target: each module ≤500 lines (with explicit ceilings on the largest sub-regions, which will exceed that — see section 4); no single file responsible for more than one logical surface.
3. **Clearer responsibilities.** CSS is CSS; DOM markup is DOM; framework primitives are framework primitives; the editor surfaces are clearly separated from the playback engine. Adjacent concerns become discoverable rather than buried in a ~9k-line scroll.
4. **Faster iteration.** A localized edit no longer needs the byte-lock-anchor mental model to make a change inside its module. The byte-lock continues to enforce *generated-HTML* invariants — but the source no longer needs recipe-2c contortions because the anchor scheme moves up a layer (output-pin; see section 6).
5. **Fewer recipe-2c contortions.** The current byte-lock excises *source-level* anchors. Recipe-2c (region-interior-only) was invented because nearly every editor task lands inside a single region (T16-TRAJ — ~944 lines and growing). With the proposed output-pin (section 6), the modularization step preserves the *output* invariant directly, and intra-module reorganization is no longer constrained by anchor stability.

## 2. Non-goals

1. **No change to the generated HTML behavior** for any of the 6 live production scenes (IBUG, Speicher, Fehmarn, Gutsmutstrasse, Polygraf-Bahnhof, kf-fehmarn) or the under-development scene `kf-fehmarn-author`. The output-pin (section 6) hard-asserts this.
2. **No change to the viewer's user-facing UX** — no DOM removed, no CSS visually altered, no JS handler semantics changed. Diff at the `html_for(...)` output should be byte-identical for the existing scene corpus.
3. **No change to the SPCP1 wire format.** `core/spcp_token.py` is untouched. The JS port (`_encodeSpcp` / `_spcpNum`) inside `_VIEWER_TEMPLATE` is moved as bytes, not edited.
4. **No change to the save-backend contract** (CLI / PHP / Cloudflare). `save_mode_json` / `save_endpoint_json` still flow through `html_for(...)` kwargs into the generated `SAVE_MODE` / `SAVE_ENDPOINT` consts. Same defaults (`"cli"` / `""`), same plumbing through `assembler.py` and `steps/publish.py`.
5. **No new tests for editor behavior.** The output-pin and existing 713 tests must all pass. Behavioral coverage of the editor surfaces is in the Playwright keyframe-editor harness — out of scope here.
6. **No re-format / no whitespace touch-up.** A reformatter that "looks reasonable" but changes a byte in the generated output is a hard fail of this work.

## 3. Current file analysis

### 3.1 High-level shape

`template.py` is 9,610 LF lines. Two top-level definitions:

| Span (lines) | What | Approx. size |
|--------------|------|--------------|
| 1–32         | module docstring + 3 module dunders (`SPARK_VERSION`, `THREE_VERSION`, `SPARK_FORK_URL`) | 32 |
| 34–122       | `html_for(...)` Python wrapper (kwargs, share-meta, `.format()` call) | 89 |
| 125–9610     | `_VIEWER_TEMPLATE` — one Python `str.format`-style string literal | 9,485 |

`html_for(...)` produces the final HTML via `_VIEWER_TEMPLATE.format(project_name=…, spark_version=…, three_version=…, spark_fork_url=…, primary_asset=…, paged_json=…, save_mode_json=…, save_endpoint_json=…, share_meta=…)`. There are nine `{field}` placeholders and ~1,308 `{{` / ~1,258 `}}` brace-doubled JS objects/blocks (the imbalance is real — many JS lines contain `}}` from nested ES `function(){{ ... }}` closers and not always paired `{{` on the same line). Brace-doubling is fragile and is the single biggest source of pain when editing `_VIEWER_TEMPLATE` in place.

### 3.2 Logical-block map (rough; line numbers at HEAD `18263dd`)

The `_VIEWER_TEMPLATE` constant is one giant string but is internally marked with banner comments (`// ============`, `// ----`). The following 22 blocks correspond to those banners and the natural HTML structure:

| # | Block | Span | Approx. lines | Excised? |
|---|-------|------|---------------|----------|
| B01 | `<head>` (meta, preconnect, share-meta) | 128–140 | 13 | no |
| B02 | CSS in `<style>` (header, stats, hint, embed, dual-UI, intro/loading) | 141–440 | 300 | partial (`_T12_CSS`, `_T19_CSS`) |
| B03 | `<body>` DOM (header, quality buttons, camera-select, kebab, stats, path-hud, path-mini, loading, css2d, intro-fade) | 442–623 | 182 | partial (`_T12_DOM`, `_T13_LB`, `_T20_CAMSEL_DOM`) |
| B04 | Importmap + JS prologue (`SAVE_MODE`, `SAVE_ENDPOINT`, `STOCK`) | 625–654 | 30 | inline (`_INSERT_ANCHOR`) |
| B05 | Unified SceneView framework (`ModeManager`, `OverlayScene`, `InteractionManager`, `HudLayer`, `window.__sceneview`) | 656–898 | 243 | partial (`_T12_MM`) |
| B06 | Viewer config (`cfg`, `_DEFAULTS`) | 900–964 | 65 | no |
| B07 | THREE + Spark setup (scene, camera, renderer, splat mesh, sparkOpts, paged_ext_splats opt-in) | 965–1243 | 279 | no (pagedExtSplats is a 2b re-pin at HEAD) |
| B08 | Detail-lever URL overrides | 1244–1361 | 118 | no |
| B09 | WASD / arrow-key fly nav | 1362–1445 | 84 | no |
| B10 | Right-drag look (FPS yaw/pitch) | 1446–1512 | 67 | no |
| B11 | Double-click / double-tap pivot | 1513–1548 | 36 | no |
| B12 | Auto view-tracking focus (`_autoFocusTick`) | 1549–1632 | 84 | partial (`_T14_AF`) |
| B13 | Toggleable on-screen HUD ('H') | 1633–1671 | 39 | no |
| B14 | Touch gesture state machine | 1672–1734 | 63 | no |
| B15 | iOS callout wedge | 1735–1917 | 183 | no |
| B16 | Annotations (CSS2DObject) | 1918–1934 | 17 | no |
| B17 | Camera-path playback (spline = `class CubicSpline` + `buildPlayer`) | 1935–2347 | 413 | full (`_SPLINE_REGION`) |
| B18 | Camera-select / dropdown / kebab menu wiring (T19-JS, T20-CAMSEL absorbed) | 2348–3096 | 749 | partial (`_T19_JS`) |
| B19 | ClipPlayer (Task 14 — multi-camera cuts tour) | 3097–3508 | 412 | full (`_T13_AS` grown) |
| B20 | End-user transport (Task 15 — click-interrupt + bottom resume + idle orbit) + shared `_orbitPathAround` | 3509–3915 | 407 | full (`_T13_AS` grown, `_T15_OB`) |
| B21 | Bench launchers (orbit / probe / rotate / dolly / cold) + `?bench=` auto-trigger | 3916–4493 | 578 | no |
| B22 | Splat-budget dropdown + initial budget pick (device tier) | 4494–4580 | 87 | no |
| B23 | Author editor — trajectory overlay (T16-TRAJ: polyline + frusta + tick dots + active marker + path-scale) | 4581–5524 | 944 | full (`_T16_TRAJ`) |
| B24 | Author editor — bottom timeline (T17 — scrub/diamonds/transport/zoom/multiselect/scale) | 5525–6511 | 987 | full (region-interior in T16-TRAJ) |
| B25 | Author editor — select-key gizmo + interp popover + Record/Save (T18, incl. `_encodeSpcp` + `_spcpNum` SPCP JS port) | 6512–8596 | 2085 | full (region-interior in T16-TRAJ) |
| B26 | Frame loop + Bench recorder + Set-start-view (Option A relay) + Centre-first / Early reveal / Front-load preload IIFE + LoD root-chunk eviction guard + T14-PW prewarm guard-twin | 8597–9480 | 884 | partial (`_T14_PW`) |
| B27 | Intro controller (T13 — cinematic loading-blur + fade IIFE) | 9481–9601 | 121 | full (`_T13_IC`) |
| B28 | Tail + debug hook + closing `</script></body></html>` | 9602–9610 | 9 | no |

**Heaviest blocks:** B25 (gizmo + Save, ~2085 lines), B24 (timeline, ~987), B23 (trajectory overlay, ~944), B26 (frame loop + preload, ~884), B18 (camera-select wiring, ~749).

**Cross-cutting concerns** (variables/functions referenced across multiple blocks):

- `_VALID_INTERP`, `_kfMeta`, sortedKfs / `times` (B17 spline ↔ B18 dropdown ↔ B23/24/25 editor)
- `applySplatBudget`, `_initialBudget`, `pickDefaultBudget` (B22 ↔ B26 frame loop)
- `_autoFocusTick`, `_afReady`, `spark.lodPosOverride` (B12 ↔ B26 frame loop ↔ B19 ClipPlayer)
- `_clipMode`, `_clipState`, `_clipSeq`, `_buildClipPlayer` (B19 ↔ B26 frame loop ↔ B23/25 author overlay)
- `_orbitPathAround` (B20 ↔ B21 bench orbit)
- `OverlayScene.register(...)` (B05 framework ↔ B19/20/23/24/25 layer registrations)
- `ModeManager.is('author' | 'user' | 'embed')` (B05 framework ↔ ~30 call sites across editor + transport + camera-select)
- `_pathIconSync`, `_pathStep`, `_pathSeekHold` (B18 #path-mini wiring ↔ B20 transport ↔ B23/24/25 editor)
- `_encodeSpcp`, `_spcpNum`, `_PATCH_KEYS` (B25 gizmo ↔ B25 Set-start-view ↔ B26 set-start-view block at 8876)

Most cross-cutting variables are declared once at module scope inside `_VIEWER_TEMPLATE` and reused. The structure is already "single global lexical scope" — a module split must concatenate the chunks in dependency order or accept that the chunks remain logically one IIFE.

### 3.3 Excised-region map (current byte-lock)

The byte-lock asserts `html_for("HarnessScene")` matches a pinned baseline length + SHA-256 *after* excising 14 named regions from both sides. Region anchors (`_TXX_*_START` / `_END`) and which logical block they cover:

| Region (anchor const) | Logical block(s) | Excision recipe |
|------------------------|------------------|-----------------|
| `_SPLINE_REGION` (CubicSpline + buildPlayer) | B17 | 2c-style "all of buildPlayer" |
| `_T12_CSS` | B02 (CSS strip tail) | 2b |
| `_T12_DOM` | B03 (#path-time → importmap) | 2b |
| `_T12_MM` | B05 (ModeManager dual-UI line) | 2b |
| `_T13_LB` | B03 (loading + #loading-blur backdrop + #css2d-root) | 2b |
| `_T13_AS` | B19+B20 (default-path autostart, ClipPlayer, end-user transport all absorbed in-place) | 2b grown each task |
| `_T13_IC` | B27 (intro controller IIFE) | 2b |
| `_T14_PW` | B26 (next-cut LOD prewarm guard-twin) | 2a additive |
| `_T14_AF` | B12 (broadened `_autoFocusTick` early-return guard) | 2b |
| `_T15_OB` | B20 (`_buildOrbitPath` delegation refactor) | 2b |
| `_T16_TRAJ` | B23+B24+B25 (trajectory overlay + bottom timeline + gizmo all absorbed) | 2c-grown |
| `_T19_CSS` | B02 (#controls-hint → #safari-hint) | 2b |
| `_T19_JS` | B18 (#path-* wiring + camera-select wiring + #path-mini handlers) | 2b grown |
| `_T20_CAMSEL_DOM` | B03 (#camera-select <select> markup) | 2b |

**Key observation:** the 14 regions are *anchored at lines that pre-exist UNCHANGED in both the baseline and current source*. This means each region is essentially a black box whose interior the byte-lock cannot see. The metaphor has held for ~12 editor tasks but it has clear limits:

1. **The byte-lock only proves "no drift outside the regions".** It *cannot* assert anything about region interiors (which currently include ~5,000 lines of editor code). Behavior inside a region is verified by per-task `in stripped` / `not in stripped` checks + the test's docstring claim that the in-region change is byte-runtime-inert for non-author scenes — i.e. it relies on author-mode gating + on the per-task author confirming "this delta lives only inside this region".
2. **Region anchors are source-coupled.** A pure refactor that moves an anchor line (even one byte!) breaks the lock. Recipe-2c works around this by demanding all in-flight edits land *inside* an existing region — but that pushes more and more code into single regions (T16-TRAJ is now ~944+987+2085 = ~4,000 lines).
3. **The lock is brittle under modularization.** Splitting `_VIEWER_TEMPLATE` into multiple files will move anchor lines — the lock fails immediately. So the lock must be replaced *before* extraction starts.

### 3.4 Brace-doubling fragility

JS objects use `{` and `}`. Python `str.format` requires those to be doubled: `{{` and `}}`. The current file has ~1,308 `{{` and ~1,258 `}}` (the imbalance is from line-spanning closures where a line ends with `}}` matching `{{` on a prior line). Every edit to JS object literals risks introducing an unbalanced single `{` (which would cause `.format()` to crash with `IndexError` / `KeyError`) or producing wrong output (a single `{name}` accidentally substituted as a format field).

This fragility is the **second** strongest motivation for modularization. Option C below (plain-text template chunks) eliminates it entirely.

## 4. Target file structure

### 4.1 Three options considered

**Option A — sibling Python modules.** `template.py` becomes a tiny orchestrator that imports `RENDER_CSS()`, `RENDER_DOM()`, `RENDER_FRAMEWORK()`, etc., from sibling files (`_editor_css.py`, `_editor_dom.py`, ...). Each module returns a string (or a `str.format`-able fragment). Pros: explicit Python imports, easy IDE navigation, can use module-level constants. Cons: brace-doubling persists in every module that contains JS; Python module boilerplate per file; circular-import risk.

**Option B — sub-package.** `template.py` becomes `template/__init__.py` exposing `html_for(...)`; siblings under `template/` contain logical chunks. Pros: cleaner namespace (`viewers.spark.template.editor_css`); per-feature module discovery. Cons: same brace-doubling issue as A; renaming a Python module (`template.py` → `template/`) is a small but real refactor risk for any caller using `from splatpipe.viewers.spark.template import html_for` (verified: `assembler.py` line 32 uses exactly this import — keeping `__init__.py` exporting `html_for` makes this a no-op for callers, but Python imports involving the path object are a known footgun on Windows). Equivalent to A in benefits.

**Option C — plain-text template fragments + Python orchestrator.** Each logical chunk lives as a `.html_tmpl` file in `viewers/spark/template_parts/`, with a small Python registry. The orchestrator (`template.py`) reads each fragment at module-load time, substitutes Python placeholders, and concatenates. Pros: **brace-doubling vanishes** — `.html_tmpl` files contain raw JS with single `{` / `}` and a clearly-distinguished placeholder syntax (e.g. `${field}` à la JS template literals, or `<<field>>`); each fragment is loadable in any text editor with JS/CSS/HTML syntax highlighting; trivial to diff; trivial to lock-pin individual fragments. Cons: file-on-disk I/O at module import (negligible; cached once); placeholder syntax must be chosen carefully to never collide with literal content in JS / CSS / HTML; loses Python introspection of the chunks (acceptable — we want the chunks to be content, not code).

### 4.2 Recommendation: Option C

**Recommend Option C** (plain-text fragments + Python orchestrator). Rationale:

1. **Eliminates brace-doubling.** This is the single biggest source of editor pain. Fragments are raw JS/CSS/HTML; the orchestrator does substitution via a `Template`-like class with a non-brace placeholder syntax.
2. **Each fragment gets the right editor mode.** A `.html_tmpl` file opens with HTML/JS/CSS highlighting in every editor without extra config (mode hint: `<!-- vim: ft=html -->` or `// @ts-check` on first line). Python files with embedded JS get neither.
3. **Output-pin is still the right invariant.** Whether chunks are Python strings or text files, the output-pin (section 6) tests `html_for(...)` end-to-end.
4. **Smaller commits.** Splitting one Python string into many text files is a series of low-risk, automated extractions. Each extracted fragment is asserted byte-equal to the source-of-truth slice via the output-pin.
5. **Eases the JS-IDE story.** If/when we want to lint or unit-test JS in the editor surface, fragments can be loaded by a JS test runner directly — no Python middleman.

**Trade-off accepted:** the chunks are no longer Python-introspectable. We accept this — they were never *meant* to be Python; they were JS smuggled through a string. Plain text is the truth.

### 4.3 Proposed directory layout

```
src/splatpipe/viewers/spark/
  template.py                    # orchestrator: html_for(...), placeholder
                                 #   substitution, fragment loading
  template_parts/                # NEW — fragments loaded at module-import
    __init__.py                  # empty package marker (no Python code)
    01_head_meta.html_tmpl       # B01 (~13 lines)
    02_styles.css_tmpl           # B02 main viewer CSS (~250 lines)
    02_styles_editor.css_tmpl    # B02 editor-specific CSS (T12, T13, T19) (~50)
    03_body_main.html_tmpl       # B03 main DOM (header, stats, hint, css2d) (~80)
    03_body_camera_select.html_tmpl  # B03 camera dropdown + kebab + +Add (~50)
    03_body_path_hud.html_tmpl   # B03 #path-hud + #path-mini + dual-UI roots + intro-fade (~50)
    04_js_prologue.js_tmpl       # B04 (~30 lines)
    05_framework.js_tmpl         # B05 SceneView framework (~245)
    06_cfg.js_tmpl               # B06 viewer config (~65)
    07_three_spark_setup.js_tmpl # B07 THREE + Spark + sparkOpts (~280)
    08_url_overrides.js_tmpl     # B08 detail-lever URL overrides (~120)
    09_input_wasd.js_tmpl        # B09 WASD nav (~85)
    09_input_look.js_tmpl        # B10 right-drag look (~70)
    09_input_pivot.js_tmpl       # B11 double-click pivot (~40)
    09_input_focus.js_tmpl       # B12 auto-focus tick (~85)
    09_input_hud.js_tmpl         # B13 'H' HUD toggle (~40)
    09_input_touch.js_tmpl       # B14 touch gestures (~65)
    09_input_ios_callout.js_tmpl # B15 iOS callout wedge (~185)
    10_annotations.js_tmpl       # B16 annotations (~20)
    11_playback_spline.js_tmpl   # B17 CubicSpline + buildPlayer (~415)
    12_camera_select.js_tmpl     # B18 camera-select / kebab / dropdown (~750)
    13_clip_player.js_tmpl       # B19 ClipPlayer (~415)
    14_user_transport.js_tmpl    # B20 end-user transport + orbit helper (~410)
    15_bench.js_tmpl             # B21 bench launchers + ?bench= (~580)
    16_splat_budget.js_tmpl      # B22 splat budget dropdown (~90)
    17_editor_trajectory.js_tmpl # B23 author editor — trajectory (~945)
    18_editor_timeline.js_tmpl   # B24 author editor — bottom timeline (~990)
    19_editor_gizmo.js_tmpl      # B25 author editor — gizmo + Save + SPCP port (~2085)
    20_frame_loop.js_tmpl        # B26 frame loop + bench recorder + setstart + preload (~885)
    21_intro_controller.js_tmpl  # B27 intro controller IIFE (~125)
    99_closing.html_tmpl         # B28 tail + debug hook + closing tags (~10)
```

29 fragment files; the orchestrator `template.py` concatenates them in numerical order. The numeric prefix encodes dependency order (the only constraint: framework before everything that uses it; spline before everything that uses spline; cfg before everything that uses cfg). Heaviest fragments (B25 at 2085, B24 at 990, B23 at 945, B26 at 885, B18 at 750) all exceed the 500-line target. **These are accepted as-is for the FIRST modularization commit** — splitting them further into sub-fragments is a follow-up. The point of the first split is to bring the *median* file size under 500; the outliers stay outliers until a per-block deep-dive.

**Placeholder syntax.** Reuse Python's `string.Template`-style `${field}` (NOT `{field}` — too easy to collide with literal JS object braces). Fragments use `${project_name}`, `${spark_version}`, etc. — and JS objects use bare `{` / `}` with no doubling. `string.Template.substitute(...)` is the substitution. Field names must be sanitized to `[A-Za-z_][A-Za-z0-9_]*` (already true today; the existing 9 fields all pass).

**Orchestrator (`template.py`) sketch:**

```python
# pseudocode — actual code in plan task T03
from pathlib import Path
from string import Template
import json

SPARK_VERSION = "2.0.0"
THREE_VERSION = "0.180.0"
SPARK_FORK_URL = "https://splatpipe-cdn.b-cdn.net/_sparkfork-rcf2/spark.module.min.js"

_PARTS_DIR = Path(__file__).parent / "template_parts"

def _load_fragments() -> str:
    """Concatenate every *.html_tmpl / *.css_tmpl / *.js_tmpl in template_parts/
    sorted by filename. Cached on first call."""
    if not hasattr(_load_fragments, "_cache"):
        chunks = []
        for p in sorted(_PARTS_DIR.glob("*_tmpl")):  # NN_name.<ext>_tmpl
            chunks.append(p.read_text(encoding="utf-8"))
        _load_fragments._cache = "".join(chunks)
    return _load_fragments._cache

def html_for(project_name: str, *, primary_asset: str = "scene.rad", ...):
    """Same signature, same semantics; share-meta computed in Python as before."""
    # ... (share-meta, _e, etc.) ...
    return Template(_load_fragments()).substitute(
        project_name=project_name,
        spark_version=SPARK_VERSION,
        ...
    )
```

**Why glob-sort by filename works:** the numeric prefix encodes dependency order. A future change that needs a new chunk between 14 and 15 inserts `14a_*` or `145_*`. Glob-sort is stable and human-readable.

**Why per-fragment newlines are safe:** each fragment ends with `\n` in its on-disk form. Concatenation = original `_VIEWER_TEMPLATE` byte-for-byte if and only if every fragment boundary aligns with a `\n` boundary in the original. This is achievable for all 29 splits (every block in section 3.2 ends with `\n` in the current template).

## 5. Byte-lock evolution — the output-pin

### 5.1 Why the current excised-region byte-lock must retire

The current lock (`tests/test_html_for_save_mode.py::test_defaults_are_regression_safe_existing_scenes_byte_identical`):

1. Asserts `html_for("HarnessScene")` length + SHA-256 *after* excising 14 source-anchored regions from both the current source and the pinned baseline.
2. Region anchors are *source lines* like `"  applySplatBudget(_initialBudget);\n"` — fragile to *any* refactor.
3. The lock cannot see inside regions; behavior inside is asserted by ad-hoc `in stripped` / `not in stripped` markers + per-task narratives in docstrings.
4. The lock requires recipe-2c gymnastics for every editor task that lands inside an existing region (the case for ~80% of tasks since T14).

A modularization that moves anchor lines into different files breaks the lock immediately. It cannot survive this work without being replaced.

### 5.2 Output-pin: what it does

**The right invariant has always been: the generated HTML for our deployed scenes is byte-identical to a known-good baseline.** The current lock approximates this by pinning the source remainder — but the source remainder is incidental. What matters is the output bytes.

The output-pin is a test that:

1. Builds a small corpus of `(scene_args, expected_sha256, expected_len)` tuples representing the 6 live production scenes + 2 development scenes + the `HarnessScene` default.
2. Calls `html_for(*scene_args)` for each entry.
3. Asserts `len(html)` and `hashlib.sha256(html.encode()).hexdigest()` match the pinned tuple.
4. On any unintended drift, *the test fails with which scene drifted*.

**Crucially:** the output-pin is invariant to ANY source restructuring as long as the bytes come out unchanged. It is the *real* contract.

### 5.3 Corpus design

The output-pin corpus must cover:

| Scene fingerprint | save_mode | save_endpoint | primary_asset | paged | share_url | share_image | description |
|-------------------|-----------|---------------|---------------|-------|-----------|-------------|-------------|
| `HarnessScene` | `"cli"` | None | `"scene.rad"` | True | None | None | None |
| `"S"` (http test fixture) | `"http"` | `"https://x.example/api/save"` | default | default | None | None | None |
| `IBUG_2025` | `"cli"` | None | `"scene.rad"` | True | absolute Bunny URL | absolute preview | scene-specific |
| `Speicher_Lindenau_01` | `"cli"` | None | `"scene.rad"` | True | absolute Bunny URL | absolute preview | scene-specific |
| `Fehmarn` | `"cli"` | None | `"scene.rad"` | True | absolute Bunny URL | absolute preview | scene-specific |
| `Gutsmutstrasse` | `"cli"` | None | `"scene.rad"` | True | absolute Bunny URL | absolute preview | scene-specific |
| `Polygraf-Bahnhof` | `"cli"` | None | `"scene.rad"` | True | absolute Bunny URL | absolute preview | scene-specific |
| `kf-fehmarn` | `"cli"` | None | `"scene.rad"` | True | absolute Bunny URL | absolute preview | scene-specific |
| `legacy_sog_scene` | `"cli"` | None | `"scene.sog"` | False | None | None | None |
| `http_endpoint_with_quotes` | `"http"` | `'https://x/"+evil()+"'` | default | default | None | None | None |
| `none_endpoint` | `"http"` | None | default | default | None | None | None |

11 fixtures. The five non-default fields (`share_url`, `share_image`, `description`, `primary_asset`, `paged`) exercise every kwarg branch in `html_for`. Output-pin invariant: each fixture's pinned `(len, sha256)` pair survives the modularization unchanged.

**[USER-CONFIRM]** the exact scene arg values for the live production scenes — the spec proposes the deployed scene names + their Bunny URLs as the corpus, but the actual `share_url` / `share_image` / `description` values for the 6 live scenes need to be sourced from a recent `splatpipe publish` invocation (or equivalent). The plan's first task fetches these from the deployed `index.html` HTTP HEAD + first-MB-GET, so the corpus is derived from production rather than guessed.

### 5.4 Output-pin file location + structure

```
tests/test_html_for_output_pin.py
```

Self-contained; imports `html_for` and `hashlib`; one test per fixture; one module-level corpus dict. Total ~120 lines.

### 5.5 What the output-pin is NOT

- **Not a behavior test.** It does not verify the viewer works in a browser. That is the Playwright keyframe-editor harness's job.
- **Not a no-drift-anywhere lock.** It only locks the 11 fixtures. A *new* (yet-unbaselined) scene_args combination could drift unnoticed. **Mitigation:** the corpus is the same set of scenes that publish through the production pipeline. If a new scene is added, the publish CLI prints its `html_for(...)` SHA so the human adding it can confirm it matches expectations.
- **Not a structural test.** It does not assert presence/absence of any source-level marker. Source restructuring is invisible to it (by design).

### 5.6 Migration path: legacy + output-pin run in parallel briefly

For the FIRST few extraction commits, both the legacy excised-region lock AND the output-pin run. Both must pass. This is overlap insurance:

- The legacy lock catches drift the output-pin might miss (e.g. a fixture not in the corpus).
- The output-pin catches drift the legacy lock might miss (e.g. drift *inside* an excised region — which the legacy lock cannot see).

The **first** extraction task adds the output-pin. The **last** extraction task retires the legacy lock (`_PRE_TASK20_REMAINDER_*`, `_T*_*` anchors, and the `test_defaults_are_regression_safe_existing_scenes_byte_identical` assertion's main length+sha check). The 11 NEGATIVE-CONTROL `_git_blob_module` tests (camera-overlay, ticks, gizmo-realdrag, etc.) survive — they pin specific code-level invariants and remain a useful belt-and-braces.

## 6. Extraction sequence

Each step is a single commit. Each commit must:

1. Add or modify code per the step.
2. Run `pytest tests/test_html_for_output_pin.py tests/test_html_for_save_mode.py -v` — both pass.
3. Run `pytest -q` — full 713-test suite passes (+1 for output-pin = 714).

### 6.1 Sequence overview (matches plan tasks T01–T16)

| # | Task | Type | Risk | Approx. effort |
|---|------|------|------|----------------|
| T01 | Add output-pin test (legacy lock UNCHANGED) | additive | low | 1 hour |
| T02 | Create `template_parts/` directory + `__init__.py` (empty) | additive | none | 5 min |
| T03 | Orchestrator skeleton in `template.py`: implement `_load_fragments()` + switch `html_for` to call it; ZERO fragments yet | refactor | medium | 1 hour |
| T04 | Extract B28 (closing tail, 9 lines) → `99_closing.html_tmpl` | extract leaf | very low | 15 min |
| T05 | Extract B01 (head meta, 13 lines) → `01_head_meta.html_tmpl` | extract leaf | very low | 15 min |
| T06 | Extract B02 (CSS, 300 lines) → `02_styles.css_tmpl` + `02_styles_editor.css_tmpl` | extract pure leaf | low | 1 hour |
| T07 | Extract B03 (DOM, 182 lines) → `03_body_main.html_tmpl` + `03_body_camera_select.html_tmpl` + `03_body_path_hud.html_tmpl` | extract pure leaf | low | 1 hour |
| T08 | Extract B04 (JS prologue, 30 lines) → `04_js_prologue.js_tmpl` | extract leaf | very low | 15 min |
| T09 | Extract B05–B07 (framework, cfg, three+spark setup, ~590 lines) → 3 fragments | extract framework | medium | 2 hours |
| T10 | Extract B08–B16 (URL overrides, input handlers, annotations, ~600 lines) → 8 fragments | extract input layer | medium | 2 hours |
| T11 | Extract B17 (CubicSpline + buildPlayer, 415 lines) → `11_playback_spline.js_tmpl` | extract spline | low | 30 min |
| T12 | Extract B18 (camera-select, 750 lines) → `12_camera_select.js_tmpl` | extract editor leaf | medium | 1 hour |
| T13 | Extract B19–B22 (ClipPlayer, user transport, bench, budget, ~1500 lines) → 4 fragments | extract playback | medium | 2 hours |
| T14 | Extract B23–B25 (editor — trajectory, timeline, gizmo+SPCP, ~4015 lines) → 3 fragments | extract editor core | high | 3 hours |
| T15 | Extract B26+B27 (frame loop + preload + intro IIFE, ~1005 lines) → 2 fragments | extract tail | medium | 1 hour |
| T16 | Retire legacy excised-region byte-lock; delete 14 `_T*_*` anchor consts + the main length+sha assertion. Keep the NEGATIVE-CONTROL tests. | cleanup | low | 30 min |

**Total: 16 tasks. Estimated effort: ~2 working days for an engineer who hasn't worked on `template.py` before; ~1 day for one who has.**

### 6.2 Ordering rationale

- **T01 first:** the output-pin must exist before any extraction so we can detect drift from step 0.
- **T03 (orchestrator skeleton) before any extraction:** the skeleton must be in place so each subsequent extraction is "move N lines from `template.py` to fragment + add a `read fragment` line in the skeleton".
- **T04–T08 (small leaves) before big surfaces:** lower-risk extractions go first to build confidence in the recipe.
- **T11 (spline) before T12–T14:** the spline is a dependency root for the editor surfaces. Extracting it cleanly is a check that the orchestrator can handle a medium-sized refactor (the spline is a class definition + a closure, dependency-sensitive).
- **T12 (camera-select) before T14 (editor):** the editor relies on `_camSelReflect` (camera-select) for path-binding updates.
- **T13 (playback) before T14 (editor):** the editor calls into ClipPlayer for live preview.
- **T14 (editor) before T15 (frame loop):** the frame loop registers OverlayScene layers that the editor populates.
- **T16 last:** the legacy lock retires only after every extraction is done. Until T16, both locks run side-by-side.

### 6.3 Mid-extraction recovery

If an extraction commit's output-pin fails:

1. **Diagnose**, do not paper over. The output-pin failure means the extracted fragment is one byte different from the source. Common causes: missing trailing `\n`, missing leading `\n`, accidentally dropping the line break before/after the extracted span, accidentally substituting an `${` placeholder where a literal `${` appears in JS (e.g. ES template literals — none exist in current template, verified by `grep -F '${' template.py` → 0 matches).
2. **Revert and re-do.** Each task is small enough to revert and redo in <30 min.

## 7. Test coverage strategy

### 7.1 What protects what

| Concern | Test |
|---------|------|
| Generated HTML byte-identity for known scenes | `tests/test_html_for_output_pin.py` (NEW) |
| `html_for` API contract (kwargs, defaults, no secret leak) | Existing `test_html_for_save_mode.py::test_defaults_*`, `test_explicit_*`, `test_none_endpoint_*`, `test_endpoint_with_quotes_*`, `test_html_for_has_no_secret_kwarg`, `test_secret_value_never_appears_*` — UNCHANGED |
| publish.py + assembler.py call sites threading save_backend | Existing `test_publish_call_site_*`, `test_assembler_call_site_*` — UNCHANGED |
| Scene-relative trajectory overlay (my16) | Existing `test_camera_path_overlay_is_scene_relative_not_fixed` — UNCHANGED |
| Motion ticks tiny/white + line gradient (my17) | Existing `test_motion_ticks_are_tiny_white_and_line_has_gradient` — UNCHANGED |
| Real-drag gizmo + author tour suppression (my18) | Existing `test_real_gizmo_handle_drag_wiring_present_and_author_tour_suppressed` — UNCHANGED |

### 7.2 Why the NEGATIVE-CONTROL tests survive

The 3 NEGATIVE-CONTROL tests (`my16`, `my17`, `my18`) load the template from `git cat-file blob <pre-fix-rev>:...` and assert specific markers are absent there but present at HEAD. These tests:

- DO NOT depend on the source line layout — they only check string presence in the rendered HTML output.
- DO discriminate against the actual pre-fix code (verified by their own `pre_html` checks).

They survive the modularization unchanged — `html_for` still produces the same HTML, and `git cat-file blob` still loads the pre-fix template the same way.

### 7.3 What the output-pin does not cover

- **In-browser viewer behavior.** Playwright keyframe-editor harness covers this. Out of scope for the byte-lock layer.
- **Network/streaming behavior.** Same — Playwright + manual probe runs cover this.
- **NEW scene combinations.** A new scene's args could drift unnoticed. Mitigation: the publish CLI prints the SHA of the generated HTML so the publisher confirms it visually.

## 8. Risks + mitigations

| Risk | Mitigation |
|------|-----------|
| A fragment extraction drops a leading/trailing `\n` and the output-pin fails | Output-pin gives a clear `len(html)` delta and SHA mismatch; reverting + redoing is a 15-min loop |
| Fragment contains a literal `${name}` that looks like a placeholder | Audit `template.py` for `${` BEFORE T01 (one-liner: `grep -nF '\${' template.py`). If 0, safe to use Template syntax. If >0, switch to a custom `<<name>>` syntax (or escape `${` as `${{` à la string.Template's safe substitution) |
| Cross-cutting variable referenced from a fragment extracted in a later commit | Glob-sort by filename means fragments are concatenated in numeric-prefix order; if commit Tk extracts a fragment depending on commit Tk+1, the output-pin will catch nothing (the source still works because we extract the consumer first, then the producer, both in correct numeric position). **The trap is wanting to extract producers first.** Defense: always extract DOWN dependency direction (leaves first); the proposed ordering in section 6.2 follows this |
| Brace-doubling in the orchestrator (Python `str.format`-equivalent code path) — string.Template doesn't have brace-doubling but does have `$$` for literal `$` | Audit `template.py` for literal `$` chars. Count: ~ a handful of `$` in CSS classes / regex. Each is a single literal `$` — `Template.substitute` requires `$$`. The extraction process must convert literal `$` → `$$` in fragments. Plan T03 does this conversion |
| String.Template's identifier rules differ from `.format`'s | `string.Template` allows `${name}` with `[a-z_][a-z_0-9]*` — same as `str.format`'s named fields. No issue. Confirmed by reading CPython docs |
| Edge case: a fragment ends mid-line and concatenation merges with the next fragment's start, producing different bytes than `_VIEWER_TEMPLATE.format(...)` | Each fragment ends with `\n`. Concatenation just works. Output-pin verifies byte-identity |
| Editor IDE search-and-replace across modules | Each fragment is small (<500 lines target; outliers explicit). Cross-fragment references are explicit imports in the orchestrator. `grep` across `template_parts/` still finds things across the whole template surface |
| Encoding: UTF-8 vs. UTF-16 BOM if a Windows tool writes a fragment | `Template.substitute` expects str. `Path.read_text(encoding="utf-8")` is explicit. Any BOM gets read as a BOM character and breaks output-pin loudly. Caught at first run |
| Recipe regen for an in-flight task (post-extraction) | After T16, the legacy lock is gone — no recipe to regen. The output-pin's pin moves only when a fixture's expected output legitimately changes (a deliberate viewer edit). The pin update is mechanical: run the test, get the new SHA, paste it in. Far simpler than current excised-region regen |
| Bigger risk to coastline: a hidden bug in `template.py` is exposed by the modularization | Acceptable — bugs surfaced are bugs to fix |
| Production deploy during the modularization | Acceptable — the output-pin asserts byte-identity for the 6 live scenes, so a deploy mid-extraction is safe as long as the output-pin passes at the deploy commit |

## 9. Effort estimate

**Multi-day for full execution.** Ballpark range:

- Engineer who knows the file: ~1.5 working days (12 hours).
- Engineer who does not: ~2.5 working days (20 hours).
- With one round of unexpected blockers (e.g. a Windows newline corruption surprise): add 4-8 hours.

**Range: 1.5 to 3 working days for an experienced engineer.** Tonight's spec + plan deliverables are well under one day.

## 10. Open questions + [USER-CONFIRM] items

1. **[USER-CONFIRM]** the output-pin scene corpus. The spec proposes the 6 live production scenes + 3 development scenes + 2 synthetic test fixtures. The exact `share_url` / `share_image` / `description` values for live scenes must come from deployed `index.html` files (the plan's T01 fetches these — but it must hit the live URLs, so the user needs to confirm the scene set + URLs). Alternative: pin a smaller corpus (just `HarnessScene` + the 4 test fixtures from `test_html_for_save_mode.py`) and rely on the publish CLI's SHA print for scene-specific drift detection.

2. **[USER-CONFIRM]** the placeholder syntax. Spec recommends `${name}` (Python `string.Template` standard). Alternative: `<<name>>` if `${` is found anywhere in JS literal content (audit pending in T01). **Default if no objection: `${name}`.**

3. **[USER-CONFIRM]** the legacy byte-lock retirement. T16 deletes the main length+SHA assertion + all 14 `_T*_*` anchor constants in `test_html_for_save_mode.py`. The 11 fields and assertions (a)/(b)/(c)/(d) — kwarg shape, secret leak protection, call-site threading — stay. The 3 NEGATIVE-CONTROL `my*` tests stay. **Default if no objection: retire as proposed.**

4. **[USER-CONFIRM]** subdividing the heaviest fragments (B23 945 lines, B24 990 lines, B25 2085 lines) in a follow-up. Spec accepts the heavy fragments as-is for the first split. A follow-up could break B25 into sub-fragments (gizmo init / TC proxy / interp popover / Record / Save+SPCP). **Default if no objection: defer to a follow-up.**

5. **[USER-CONFIRM]** whether modularization should commit on `feat/camera-keyframe-editor` (the current branch) or on a new branch (`refactor/spark-template-modular`). Spec assumes a new branch off `main` to keep the editor work isolated. The legacy lock's "moving baseline" advances on the editor branch — extracting now could conflict with future editor commits. **Default if no objection: new branch off main after the editor work merges.**

---

## Appendix A — One-line summary of each block (for the plan's task-card cross-reference)

- **B01** `<head>` meta + preconnect + share-meta substitution
- **B02** CSS (header, hint, embed, dual-UI, loading, intro-fade)
- **B03** Body HTML markup (header, quality buttons, camera-select, kebab, stats, path-hud, path-mini, loading, css2d, intro-fade)
- **B04** Importmap + JS prologue (SAVE_MODE/ENDPOINT consts, STOCK flag)
- **B05** SceneView framework (ModeManager, OverlayScene, InteractionManager, HudLayer, __sceneview)
- **B06** Viewer config (`cfg`, `_DEFAULTS`)
- **B07** THREE + Spark setup (scene, camera, renderer, splat mesh, sparkOpts, paged_ext_splats opt-in)
- **B08** Detail-lever URL overrides (?lodRenderScale, ?lodSplatScale, ?clipXY, ?focalAdjustment, ?blurAmount, ?preBlurAmount, ?maxStdDev)
- **B09** WASD / arrow-key fly navigation
- **B10** Right-drag look (FPS yaw/pitch)
- **B11** Double-click pivot
- **B12** Auto view-tracking focus (`_autoFocusTick`)
- **B13** 'H' settings HUD toggle
- **B14** Touch gesture state machine
- **B15** iOS callout wedge
- **B16** Annotations (CSS2DObject)
- **B17** Camera-path playback (CubicSpline + buildPlayer)
- **B18** Camera-select / dropdown / kebab menu wiring
- **B19** ClipPlayer (multi-camera Camera-Cuts tour)
- **B20** End-user transport + shared `_orbitPathAround`
- **B21** Bench launchers + `?bench=` auto-trigger
- **B22** Splat budget dropdown + initial pick
- **B23** Author editor — trajectory overlay (polyline + frusta + tick dots + active marker)
- **B24** Author editor — bottom timeline (scrub/diamonds/transport/zoom/multiselect/scale)
- **B25** Author editor — gizmo + interp popover + Record + Save (incl. SPCP1 JS port)
- **B26** Frame loop + bench recorder + Set-start-view + Centre-first / Early reveal / Front-load preload IIFE + LoD root-chunk eviction guard
- **B27** Intro controller IIFE (cinematic loading-blur + fade)
- **B28** Tail + debug hook + closing tags

---

## Appendix B — Audit: literal `${` in current template

If any literal `${...}` already exists in `_VIEWER_TEMPLATE` (e.g. an ES2015 template literal in JS), the recommended `${name}` placeholder syntax collides. Audit BEFORE T01:

```bash
grep -nF '${' src/splatpipe/viewers/spark/template.py
```

If `0` matches: `${name}` is safe. If `>0`: switch to `<<name>>` and adjust `string.Template` with a subclass that overrides `delimiter = '<<'` and `pattern` (string.Template supports this).

A previous quick scan suggested 0 matches, but T01 must run this audit and record the result.
