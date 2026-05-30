# Modularize Spark Viewer Template — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor `src/splatpipe/viewers/spark/template.py` (~9,610 lines, of which ~9,485 are the `_VIEWER_TEMPLATE` string constant) into focused fragment files under `src/splatpipe/viewers/spark/template_parts/`, preserving generated HTML byte-identity for every existing deployed scene + every test fixture.

**Architecture:** Option C from the spec — plain-text fragments (`*.html_tmpl`, `*.css_tmpl`, `*.js_tmpl`) loaded at module-import, glob-sorted by numeric-prefix filename, and concatenated. `html_for(...)` keeps the same signature and substitutes via `string.Template`. The current excised-region byte-lock retires in favor of an output-pin (`tests/test_html_for_output_pin.py`) that asserts `html_for(...)` returns byte-identical HTML for a corpus of representative scenes.

**Tech Stack:** Python (`string.Template`), `pathlib`, pytest, hashlib.

**Companion spec:** `docs/superpowers/specs/2026-05-20-modularize-spark-viewer-template-design.md`

---

## Pre-flight (read once before starting)

1. **Read the spec.** It documents the design and risk-vs-mitigation tradeoffs that drove the task order below.
2. **Run the full test suite once on a clean working tree** and capture the result: `pytest -q` must show `713 passed` (or whatever the current pass count is at HEAD).
3. **Audit literal `${` in the template** (the placeholder-collision risk from spec §8):
   ```powershell
   Select-String -Path src/splatpipe/viewers/spark/template.py -Pattern '\$\{' -SimpleMatch
   ```
   - If 0 matches: proceed with `${name}` placeholder syntax (string.Template default).
   - If >0 matches: stop and switch the syntax to `<<name>>` (a string.Template subclass). Document the audit result in T01's commit message.
4. **Verify the 9 format-string placeholders in current `template.py`.** Expected: `{project_name}` `{spark_version}` `{three_version}` `{spark_fork_url}` `{primary_asset}` `{paged_json}` `{save_mode_json}` `{save_endpoint_json}` `{share_meta}`. Confirm with:
   ```powershell
   Select-String -Path src/splatpipe/viewers/spark/template.py -Pattern '\{[a-z_]+\}' -AllMatches | ForEach-Object { $_.Matches.Value } | Sort-Object -Unique
   ```
5. **Audit literal `$` in the template** (string.Template requires `$$` for literal `$`):
   ```powershell
   Select-String -Path src/splatpipe/viewers/spark/template.py -Pattern '\$' -AllMatches | Measure-Object -Line
   ```
   Record the count. Every literal `$` in extracted fragments must be converted to `$$`.

## Task list

T01. Add output-pin test (legacy lock UNCHANGED)
T02. Create `template_parts/` skeleton
T03. Orchestrator skeleton in `template.py`
T04. Extract B28 (closing tail, ~9 lines)
T05. Extract B01 (head meta, ~13 lines)
T06. Extract B02 (CSS, ~300 lines)
T07. Extract B03 (DOM body, ~182 lines)
T08. Extract B04 (JS prologue, ~30 lines)
T09. Extract B05–B07 (framework / cfg / setup, ~590 lines)
T10. Extract B08–B16 (input + annotations, ~600 lines)
T11. Extract B17 (CubicSpline + buildPlayer, ~415 lines)
T12. Extract B18 (camera-select wiring, ~750 lines)
T13. Extract B19–B22 (ClipPlayer, user transport, bench, budget, ~1500 lines)
T14. Extract B23–B25 (editor core: trajectory, timeline, gizmo+SPCP, ~4015 lines)
T15. Extract B26–B27 (frame loop + intro IIFE, ~1005 lines)
T16. Retire legacy excised-region byte-lock

---

### Task T01: Add output-pin test (legacy lock UNCHANGED)

**Files:**
- Create: `tests/test_html_for_output_pin.py`

- [ ] **Step 1: Compute the baseline corpus shas**

The output-pin needs pinned (len, sha256) tuples for each fixture. Run a quick Python snippet to compute them from the current `html_for`:

```powershell
python - <<'PY'
import hashlib
from splatpipe.viewers.spark.template import html_for

cases = [
    {"name": "harness_defaults", "args": ("HarnessScene",), "kwargs": {}},
    {"name": "http_basic",
     "args": ("S",),
     "kwargs": {"save_mode": "http", "save_endpoint": "https://x.example/api/save"}},
    {"name": "http_endpoint_quotes",
     "args": ("S",),
     "kwargs": {"save_endpoint": 'https://x/"+evil()+"'}},
    {"name": "none_endpoint",
     "args": ("S",),
     "kwargs": {"save_mode": "http", "save_endpoint": None}},
    {"name": "sog_fallback",
     "args": ("LegacySogScene",),
     "kwargs": {"primary_asset": "scene.sog", "paged": False}},
    {"name": "share_card",
     "args": ("ShareScene",),
     "kwargs": {"share_url": "https://splatpipe-cdn.b-cdn.net/share/index.html",
                "share_image": "https://splatpipe-cdn.b-cdn.net/share/preview.jpg",
                "description": "Custom share description text."}},
]
for c in cases:
    h = html_for(*c["args"], **c["kwargs"])
    digest = hashlib.sha256(h.encode()).hexdigest()
    print(f'{c["name"]}: len={len(h)} sha256={digest}')
PY
```

Record the 6 (len, sha) tuples. These become the pins in step 2.

- [ ] **Step 2: Write the failing test (replace pin placeholders with step-1 values)**

```python
# tests/test_html_for_output_pin.py
"""Output-pin byte-lock — the modularization-safe successor to
test_html_for_save_mode.py's excised-region lock.

Asserts that html_for(...) produces byte-identical HTML for a small corpus of
representative scenes. Survives ANY source restructuring as long as the
generated output is unchanged.

Corpus design (see spec §5.3): defaults + http + edge cases + sog fallback +
share-card. Live production scenes are excluded from the FIRST pin until
[USER-CONFIRM] of their exact share_url / share_image / description values
(spec §10, q1). The publish CLI prints html SHA on each publish so live-scene
drift is still detectable.
"""

import hashlib
import pytest

from splatpipe.viewers.spark.template import html_for


# (name, args, kwargs, expected_len, expected_sha256)
# Pins computed from current HEAD via the pre-flight snippet — see plan T01.
CORPUS = [
    ("harness_defaults",
     ("HarnessScene",), {},
     <LEN_HARNESS>,
     "<SHA_HARNESS>"),
    ("http_basic",
     ("S",), {"save_mode": "http",
              "save_endpoint": "https://x.example/api/save"},
     <LEN_HTTP>,
     "<SHA_HTTP>"),
    ("http_endpoint_quotes",
     ("S",), {"save_endpoint": 'https://x/"+evil()+"'},
     <LEN_QUOTES>,
     "<SHA_QUOTES>"),
    ("none_endpoint",
     ("S",), {"save_mode": "http", "save_endpoint": None},
     <LEN_NONE>,
     "<SHA_NONE>"),
    ("sog_fallback",
     ("LegacySogScene",), {"primary_asset": "scene.sog", "paged": False},
     <LEN_SOG>,
     "<SHA_SOG>"),
    ("share_card",
     ("ShareScene",), {"share_url": "https://splatpipe-cdn.b-cdn.net/share/index.html",
                       "share_image": "https://splatpipe-cdn.b-cdn.net/share/preview.jpg",
                       "description": "Custom share description text."},
     <LEN_SHARE>,
     "<SHA_SHARE>"),
]


@pytest.mark.parametrize("name,args,kwargs,expected_len,expected_sha",
                         CORPUS, ids=[c[0] for c in CORPUS])
def test_html_for_output_pin(name, args, kwargs, expected_len, expected_sha):
    """html_for(args, **kwargs) must produce byte-identical HTML to the pin.

    On modularization, this test is the SOLE byte-identity guarantee for
    the corresponding scene_args. Any drift here means the modularization
    has changed the generated HTML — STOP and diagnose.
    """
    html = html_for(*args, **kwargs)
    actual_sha = hashlib.sha256(html.encode()).hexdigest()
    assert len(html) == expected_len, (
        f"[{name}] length drift: {len(html)} != {expected_len} "
        f"(generated HTML changed bytes; if this is a deliberate edit, "
        f"re-pin via the pre-flight snippet)"
    )
    assert actual_sha == expected_sha, (
        f"[{name}] SHA drift: {actual_sha} != {expected_sha} "
        f"(generated HTML changed content; if this is a deliberate edit, "
        f"re-pin via the pre-flight snippet)"
    )


def test_corpus_count():
    """Corpus size sanity — drop-detection (if a fixture vanishes from a future
    edit this fails BEFORE individual SHA assertions, with a clearer message)."""
    assert len(CORPUS) == 6, (
        f"output-pin corpus changed size unexpectedly: {len(CORPUS)} != 6"
    )
```

Replace `<LEN_*>` and `<SHA_*>` with the values from step 1.

- [ ] **Step 3: Run the output-pin test**

```powershell
pytest tests/test_html_for_output_pin.py -v
```

Expected: 7 passed (6 parametrize cases + 1 corpus-count).

- [ ] **Step 4: Run the legacy lock + full suite**

```powershell
pytest tests/test_html_for_save_mode.py -v
pytest -q
```

Expected: legacy lock still passes; full suite shows 720 passed (713 + 6 parametrize + 1 corpus).

- [ ] **Step 5: Commit**

```bash
git add tests/test_html_for_output_pin.py
git commit -m "test(modular): add output-pin byte-lock for html_for (#112 T01)

Successor to the excised-region lock. Asserts byte-identical HTML for a
6-fixture corpus covering defaults / http / edge cases / sog / share-card.
Survives ANY source restructuring as long as the generated bytes are
unchanged. Legacy excised-region lock remains active and unchanged
until T16.

Corpus pinned from HEAD; live production scenes excluded pending
[USER-CONFIRM] of their share_url/image/description values (spec §10 q1).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task T02: Create `template_parts/` skeleton

**Files:**
- Create: `src/splatpipe/viewers/spark/template_parts/__init__.py`

- [ ] **Step 1: Create the directory and empty package marker**

```powershell
New-Item -ItemType Directory -Path src/splatpipe/viewers/spark/template_parts -Force
```

- [ ] **Step 2: Create the empty package marker**

```python
# src/splatpipe/viewers/spark/template_parts/__init__.py
"""Plain-text fragment files for the Spark viewer template.

This package is a *container* for ``*.html_tmpl`` / ``*.css_tmpl`` /
``*.js_tmpl`` plain-text files; it has NO Python code. The orchestrator
in ``../template.py`` loads them via ``Path.glob('*_tmpl')``, sorted by
filename, and concatenates them in numeric-prefix order.

See ``docs/superpowers/specs/2026-05-20-modularize-spark-viewer-template-design.md``
for the design rationale.
"""
```

- [ ] **Step 3: Verify no tests break**

```powershell
pytest -q
```

Expected: same pass count as T01 (720 passed). Adding an empty package can't break anything.

- [ ] **Step 4: Commit**

```bash
git add src/splatpipe/viewers/spark/template_parts/__init__.py
git commit -m "refactor(modular): add empty template_parts/ package (#112 T02)

Container for the upcoming plain-text fragment files. No code yet —
just the package marker so the directory is git-tracked.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task T03: Orchestrator skeleton in `template.py`

**Files:**
- Modify: `src/splatpipe/viewers/spark/template.py`

This task is the trickiest. We're replacing the giant `_VIEWER_TEMPLATE` constant + `.format(...)` call with a fragment-loader + `string.Template.substitute(...)` call, but with ZERO fragments yet — the entire current `_VIEWER_TEMPLATE` content is preserved as ONE file (`00_legacy_blob.html_tmpl`) to start. Subsequent tasks split that blob progressively.

This also performs the `{` → `${` placeholder migration (for the 9 named fields) and the `{{` → `{` and `}}` → `}` un-doubling. The output-pin asserts byte-identity, so any mistake here fails the test loudly.

- [ ] **Step 1: Extract the existing `_VIEWER_TEMPLATE` body to a temporary file**

```powershell
python - <<'PY'
import re
from pathlib import Path

src = Path("src/splatpipe/viewers/spark/template.py").read_text(encoding="utf-8")
# Find _VIEWER_TEMPLATE = """\\\n...\n"""
m = re.search(r'_VIEWER_TEMPLATE = """\\\n(.*?)\n"""', src, re.DOTALL)
assert m, "_VIEWER_TEMPLATE marker not found"
body = m.group(1)

# Un-double the braces (str.format → string.Template will use ${name}).
# Order matters: temporarily replace {{ with a sentinel, then }} with another,
# then revert. This avoids the trap where a {{ is followed by a })) etc.
SENT_OPEN = "\x00ZZ_OPEN\x00"
SENT_CLOSE = "\x00ZZ_CLOSE\x00"
body = body.replace("{{", SENT_OPEN).replace("}}", SENT_CLOSE)
# At this point the only remaining { and } are str.format named-field
# placeholders (per pre-flight audit, there are no literal single-brace
# escapes in the template body). Convert them to ${name}.
def to_template(m):
    name = m.group(1)
    return "${" + name + "}"
body = re.sub(r'\{([a-z_][a-z_0-9]*)\}', to_template, body)
# Now restore the literal braces.
body = body.replace(SENT_OPEN, "{").replace(SENT_CLOSE, "}")
# And escape any literal $ to $$ for string.Template (per pre-flight audit).
# We only do this if there are no `${` left after the substitution above —
# which there are, but the audit said the only `${` in the rendered output
# comes from the placeholders we just inserted. So we have to walk and
# substitute literal $ NOT followed by { with $$.
body = re.sub(r'\$(?!\{)', '$$', body)

Path("/tmp/00_legacy_blob.html_tmpl").write_text(body, encoding="utf-8")
print(f"wrote {len(body)} bytes")
PY
```

Note on Windows: `/tmp` may not exist — use `$env:TEMP` instead. PowerShell-friendly version:

```powershell
python - <<'PY'
import os, re
from pathlib import Path

src = Path("src/splatpipe/viewers/spark/template.py").read_text(encoding="utf-8")
m = re.search(r'_VIEWER_TEMPLATE = """\\\n(.*?)\n"""', src, re.DOTALL)
assert m, "_VIEWER_TEMPLATE marker not found"
body = m.group(1)
SENT_OPEN = "\x00ZZ_OPEN\x00"
SENT_CLOSE = "\x00ZZ_CLOSE\x00"
body = body.replace("{{", SENT_OPEN).replace("}}", SENT_CLOSE)
def to_template(mm):
    return "${" + mm.group(1) + "}"
body = re.sub(r'\{([a-z_][a-z_0-9]*)\}', to_template, body)
body = body.replace(SENT_OPEN, "{").replace(SENT_CLOSE, "}")
body = re.sub(r'\$(?!\{)', '$$', body)
out = Path(os.environ["TEMP"]) / "00_legacy_blob.html_tmpl"
out.write_text(body, encoding="utf-8")
print(f"wrote {out}, {len(body)} bytes")
PY
```

- [ ] **Step 2: Inspect the produced fragment**

```powershell
Get-Content $env:TEMP\00_legacy_blob.html_tmpl -Head 30
Get-Content $env:TEMP\00_legacy_blob.html_tmpl -Tail 5
```

Confirm: starts with `<!DOCTYPE html>`, ends with the closing `</body></html>`. Spot-check a `${name}` placeholder appears (e.g. `${project_name}` near the title). Spot-check `{{` is now bare `{` (e.g. `body { overflow: hidden;`).

- [ ] **Step 3: Copy the legacy blob into `template_parts/`**

```powershell
Copy-Item $env:TEMP\00_legacy_blob.html_tmpl `
  src/splatpipe/viewers/spark/template_parts/00_legacy_blob.html_tmpl
```

- [ ] **Step 4: Rewrite `template.py` to be the orchestrator**

Replace the entire body from `def html_for` onwards (keep the docstring + dunders at the top) with:

```python
"""Spark 2 viewer template — emits a self-contained index.html.

(... existing docstring kept verbatim ...)
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from string import Template


SPARK_VERSION = "2.0.0"
THREE_VERSION = "0.180.0"
SPARK_FORK_URL = "https://splatpipe-cdn.b-cdn.net/_sparkfork-rcf2/spark.module.min.js"

_PARTS_DIR = Path(__file__).parent / "template_parts"


@lru_cache(maxsize=1)
def _load_template_body() -> str:
    """Concatenate every fragment file in ``template_parts/`` sorted by
    filename. Cached; reads once per process. Glob picks up
    ``*.html_tmpl``, ``*.css_tmpl``, and ``*.js_tmpl`` (the file-extension
    discriminator is for editor highlighting, not for ordering)."""
    chunks: list[str] = []
    for p in sorted(_PARTS_DIR.iterdir()):
        if p.suffix in {".html_tmpl", ".css_tmpl", ".js_tmpl"}:
            chunks.append(p.read_text(encoding="utf-8"))
    return "".join(chunks)


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
    """Render the Spark viewer HTML for a given project.

    (... existing docstring body kept verbatim ...)
    """
    import html as _h

    _title = f"{project_name} — interactive 3D scene"
    _desc = description or (
        "Explore this photogrammetry capture in 3D, right in your browser — "
        "a Gaussian-splat scene streamed with Splatpipe / Spark 2."
    )
    _img = share_image or "preview.jpg"

    def _e(s: object) -> str:
        return _h.escape(str(s), quote=True)

    _meta = [
        f'<meta name="description" content="{_e(_desc)}">',
        '<meta property="og:type" content="website">',
        '<meta property="og:site_name" content="Splatpipe">',
        f'<meta property="og:title" content="{_e(_title)}">',
        f'<meta property="og:description" content="{_e(_desc)}">',
        f'<meta property="og:image" content="{_e(_img)}">',
        '<meta property="og:image:width" content="1200">',
        '<meta property="og:image:height" content="630">',
        f'<meta property="og:image:alt" content="{_e(_title)}">',
        '<meta name="twitter:card" content="summary_large_image">',
        f'<meta name="twitter:title" content="{_e(_title)}">',
        f'<meta name="twitter:description" content="{_e(_desc)}">',
        f'<meta name="twitter:image" content="{_e(_img)}">',
    ]
    if share_url:
        _meta.insert(5, f'<meta property="og:url" content="{_e(share_url)}">')
    share_meta = "\n  ".join(_meta)

    return Template(_load_template_body()).substitute(
        project_name=project_name,
        spark_version=SPARK_VERSION,
        three_version=THREE_VERSION,
        spark_fork_url=SPARK_FORK_URL,
        primary_asset=primary_asset,
        paged_json=json.dumps(bool(paged)),
        save_mode_json=json.dumps(save_mode),
        save_endpoint_json=json.dumps(save_endpoint or ""),
        share_meta=share_meta,
    )
```

The `_VIEWER_TEMPLATE` constant is completely removed.

- [ ] **Step 5: Run the output-pin test**

```powershell
pytest tests/test_html_for_output_pin.py -v
```

Expected: 7 passed. If any test fails with a SHA mismatch:
- Diagnose: most likely a brace unescaping error or a literal `$` not converted to `$$`. Recompute the conversion + diff.

- [ ] **Step 6: Run the legacy lock**

```powershell
pytest tests/test_html_for_save_mode.py -v
```

Expected: legacy lock STILL passes. The byte-identity guarantee through `_load_template_body()` keeps the excised regions intact.

- [ ] **Step 7: Run full suite**

```powershell
pytest -q
```

Expected: 720 passed (same as T01).

- [ ] **Step 8: Commit**

```bash
git add src/splatpipe/viewers/spark/template.py src/splatpipe/viewers/spark/template_parts/00_legacy_blob.html_tmpl
git commit -m "refactor(modular): orchestrator + monolithic legacy fragment (#112 T03)

template.py now loads fragments from template_parts/*.html_tmpl/.css_tmpl/
.js_tmpl via string.Template.substitute. ONE fragment (00_legacy_blob.html_tmpl)
contains the entire previous _VIEWER_TEMPLATE body, brace-undoubled and
\${field}-substituted. Subsequent tasks split the legacy blob into logical
chunks.

Output-pin (T01) + legacy excised-region lock both still pass — proves the
substitution mechanics produce byte-identical HTML.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task T04: Extract B28 (closing tail, ~9 lines)

**Files:**
- Create: `src/splatpipe/viewers/spark/template_parts/99_closing.html_tmpl`
- Modify: `src/splatpipe/viewers/spark/template_parts/00_legacy_blob.html_tmpl`

Smallest possible leaf extraction — proves the recipe works.

- [ ] **Step 1: Identify the byte boundary in `00_legacy_blob.html_tmpl`**

The B28 block is from the line that opens the closing `</script>` through the file's last `</html>` (currently `template.py` lines 9602–9610). In the fragment file, locate the same span:

```powershell
Select-String -Path src/splatpipe/viewers/spark/template_parts/00_legacy_blob.html_tmpl -Pattern '_spDebug = '
```

The matching line + the next ~8 lines (through `</html>`) are the extraction target.

- [ ] **Step 2: Write `99_closing.html_tmpl`**

```html
  // Debug hook for Playwright smoke tests (same pattern as PC viewer)
  window._spDebug = { camera, scene, splat, controls, renderer, spark };
  </script>
</body>
</html>
```

Mind: leading whitespace and trailing `\n` must match what was in the legacy blob.

- [ ] **Step 3: Remove the same bytes from `00_legacy_blob.html_tmpl`**

Open `00_legacy_blob.html_tmpl` in an editor, locate the `// Debug hook ...` line, and delete from that line through the file's final `</html>\n`. The legacy blob now ends one line before that — typically on `  })();` or similar (verify with the diff in step 4).

- [ ] **Step 4: Verify byte-equality of concatenation**

```powershell
python - <<'PY'
from pathlib import Path
d = Path("src/splatpipe/viewers/spark/template_parts")
parts = sorted(d.glob("*_tmpl"))
total = "".join(p.read_text(encoding="utf-8") for p in parts)
print(f"concatenated {len(parts)} files, total bytes = {len(total)}")
PY
```

The byte count should match the legacy blob's original byte count (compute with `Get-Item ... | Select-Object -ExpandProperty Length` if you saved the original count in T03).

- [ ] **Step 5: Run output-pin**

```powershell
pytest tests/test_html_for_output_pin.py -v
```

Expected: 7 passed.

- [ ] **Step 6: Run legacy lock**

```powershell
pytest tests/test_html_for_save_mode.py -v
```

Expected: passes.

- [ ] **Step 7: Commit**

```bash
git add src/splatpipe/viewers/spark/template_parts/99_closing.html_tmpl src/splatpipe/viewers/spark/template_parts/00_legacy_blob.html_tmpl
git commit -m "refactor(modular): extract B28 closing tail (#112 T04)

Extract the closing _spDebug / </script> / </body> / </html> tail
into 99_closing.html_tmpl. Output-pin + legacy lock both pass —
proves the byte-identity-preserving extraction recipe is sound.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task T05: Extract B01 (head meta, ~13 lines)

**Files:**
- Create: `src/splatpipe/viewers/spark/template_parts/01_head_meta.html_tmpl`
- Modify: `src/splatpipe/viewers/spark/template_parts/00_legacy_blob.html_tmpl`

- [ ] **Step 1: Identify the byte boundary in `00_legacy_blob.html_tmpl`**

B01 spans from the top of the file through the `${share_meta}` line. The exact text:

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <!-- three loads cross-origin from jsdelivr and blocks first paint (the
       app can't boot until it arrives). Kicking off the DNS+TLS handshake
       here, before the importmap is discovered, saves ~1 RTT on the
       critical path. The patched @sparkjsdev/spark fork + scene.rad/.radc
       are same-origin as this HTML so that connection is already warm —
       no preconnect there would be redundant. -->
  <link rel="preconnect" href="https://cdn.jsdelivr.net" crossorigin>
  <link rel="dns-prefetch" href="https://cdn.jsdelivr.net">
  <title>${project_name} — Splatpipe Viewer (Spark)</title>
  ${share_meta}
```

- [ ] **Step 2: Write `01_head_meta.html_tmpl`** with that exact content (including trailing `\n` after the `${share_meta}` line).

- [ ] **Step 3: Remove the same bytes from `00_legacy_blob.html_tmpl`**

Delete from the top of `00_legacy_blob.html_tmpl` through (and including) the `  ${share_meta}\n` line.

- [ ] **Step 4: Verify byte-equality of concatenation**

```powershell
python - <<'PY'
from pathlib import Path
d = Path("src/splatpipe/viewers/spark/template_parts")
parts = sorted(d.glob("*_tmpl"))
total = "".join(p.read_text(encoding="utf-8") for p in parts)
print(f"concatenated {len(parts)} files, total bytes = {len(total)}")
PY
```

Total bytes should match the T04 count exactly.

- [ ] **Step 5: Run output-pin + legacy lock**

```powershell
pytest tests/test_html_for_output_pin.py tests/test_html_for_save_mode.py -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/splatpipe/viewers/spark/template_parts/
git commit -m "refactor(modular): extract B01 head meta (#112 T05)

Extract <!DOCTYPE html>..\${share_meta} into 01_head_meta.html_tmpl.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task T06: Extract B02 (CSS, ~300 lines)

**Files:**
- Create: `src/splatpipe/viewers/spark/template_parts/02_styles_main.css_tmpl`
- Create: `src/splatpipe/viewers/spark/template_parts/02_styles_editor.css_tmpl`
- Modify: `src/splatpipe/viewers/spark/template_parts/00_legacy_blob.html_tmpl`

B02 splits naturally into:
- `02_styles_main.css_tmpl` — body, canvas, header, stats, quality buttons, loading, controls-hint, safari-hint, embed rules
- `02_styles_editor.css_tmpl` — dual-UI gate (Task 12 CSS region), kebab popup (v2-C Phase 2), loading-blur + intro-fade (Task 13 CSS)

- [ ] **Step 1: Identify the boundaries**

`02_styles_main.css_tmpl` starts at the `  <style>\n` line and ends at the line just before the `/* Task 12 -- dual-UI gate ... */` comment.

`02_styles_editor.css_tmpl` starts at the `/* Task 12 -- dual-UI gate ... */` comment and ends at the `  </style>\n` line.

- [ ] **Step 2: Write `02_styles_main.css_tmpl`**

Copy the bytes from the legacy blob between the two markers. The file must START with `  <style>\n` and END with the last main-CSS rule's closing `}\n` followed by a blank line (the blank that precedes `/* Task 12 ... */`).

- [ ] **Step 3: Write `02_styles_editor.css_tmpl`**

Copy the bytes from the legacy blob between the `/* Task 12 ... */` line and `  </style>\n`. File ends with `  </style>\n`.

- [ ] **Step 4: Remove the same bytes from `00_legacy_blob.html_tmpl`**

Delete from `  <style>\n` through `  </style>\n` inclusive.

- [ ] **Step 5: Verify byte-equality of concatenation**

```powershell
python - <<'PY'
from pathlib import Path
d = Path("src/splatpipe/viewers/spark/template_parts")
parts = sorted(d.glob("*_tmpl"))
total = "".join(p.read_text(encoding="utf-8") for p in parts)
print(f"concatenated {len(parts)} files, total bytes = {len(total)}")
PY
```

Same count as T05.

- [ ] **Step 6: Run output-pin + legacy lock + full suite**

```powershell
pytest tests/test_html_for_output_pin.py tests/test_html_for_save_mode.py -v
pytest -q
```

Expected: all pass. Full suite: 720 passed (output-pin's 7 + legacy 713).

- [ ] **Step 7: Commit**

```bash
git add src/splatpipe/viewers/spark/template_parts/
git commit -m "refactor(modular): extract B02 CSS (#112 T06)

Extract <style>..</style> into 02_styles_main.css_tmpl (main viewer)
+ 02_styles_editor.css_tmpl (Task 12 dual-UI gate, Task 13 loading-blur,
v2-C kebab popup).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task T07: Extract B03 (DOM body, ~182 lines)

**Files:**
- Create: `src/splatpipe/viewers/spark/template_parts/03_body_main.html_tmpl`
- Create: `src/splatpipe/viewers/spark/template_parts/03_body_camera_select.html_tmpl`
- Create: `src/splatpipe/viewers/spark/template_parts/03_body_path_hud.html_tmpl`
- Modify: `src/splatpipe/viewers/spark/template_parts/00_legacy_blob.html_tmpl`

Three sub-fragments:
- `03_body_main.html_tmpl` — `<body>`, `<div id="header">`, title, quality-buttons opener with quality dropdowns + bench-mode dropdown (up to but NOT including the camera-select comment)
- `03_body_camera_select.html_tmpl` — camera-select comment + `<select id="camera-select">` + +Add camera + kebab buttons + popup (up to but NOT including bench-btn)
- `03_body_path_hud.html_tmpl` — bench-btn + setstart-btn + quality-buttons close + stats + controls-hint + safari-hint + loading + css2d-root + path-hud + path-mini + dual-UI roots + intro-fade (up to but NOT including importmap)

- [ ] **Step 1: Identify the boundaries**

Cross-reference the current `template.py` lines 442–623 (spec §3.2 B03). Markers:
- Start of `03_body_main`: `<body>\n`
- Start of `03_body_camera_select`: `      <!-- v2-C Phase 1: the top-bar Camera selector.`
- Start of `03_body_path_hud`: `      <button id="bench-btn" class="quality-btn"`
- End of `03_body_path_hud`: the blank line just before `  <script type="importmap">`

- [ ] **Step 2: Write the three fragments** by copying the corresponding byte ranges from the legacy blob.

- [ ] **Step 3: Remove the same bytes from `00_legacy_blob.html_tmpl`**

Delete from `<body>\n` through the line just before `  <script type="importmap">`.

- [ ] **Step 4: Verify + tests**

```powershell
python - <<'PY'
from pathlib import Path
d = Path("src/splatpipe/viewers/spark/template_parts")
parts = sorted(d.glob("*_tmpl"))
total = "".join(p.read_text(encoding="utf-8") for p in parts)
print(f"concatenated {len(parts)} files, total bytes = {len(total)}")
PY

pytest tests/test_html_for_output_pin.py tests/test_html_for_save_mode.py -v
```

Expected: byte count unchanged; all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/splatpipe/viewers/spark/template_parts/
git commit -m "refactor(modular): extract B03 body DOM (#112 T07)

Extract <body>..(before importmap) into 03_body_main / 03_body_camera_select
/ 03_body_path_hud. Three sub-fragments by surface: main header+quality,
camera-select+kebab, stats+path-hud+loading+dual-UI roots+intro-fade.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task T08: Extract B04 (JS prologue, ~30 lines)

**Files:**
- Create: `src/splatpipe/viewers/spark/template_parts/04_js_prologue.js_tmpl`
- Modify: `src/splatpipe/viewers/spark/template_parts/00_legacy_blob.html_tmpl`

B04 = importmap + `<script type="module">` open + ES imports + `PRIMARY_ASSET` / `PAGED` / `SAVE_MODE` / `SAVE_ENDPOINT` / `STOCK` consts.

- [ ] **Step 1: Identify the boundaries**

Start: `  <script type="importmap">\n`
End: the line `if (STOCK) console.info('[Splatpipe] STOCK mode: all perf mods disabled');\n` (inclusive)

- [ ] **Step 2: Write `04_js_prologue.js_tmpl`** by copying the bytes.

- [ ] **Step 3: Remove the same bytes from `00_legacy_blob.html_tmpl`**.

- [ ] **Step 4: Verify + tests**

```powershell
pytest tests/test_html_for_output_pin.py tests/test_html_for_save_mode.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/splatpipe/viewers/spark/template_parts/
git commit -m "refactor(modular): extract B04 JS prologue (#112 T08)

Extract importmap + <script type=module> + ES imports + the SAVE_*/STOCK
consts into 04_js_prologue.js_tmpl.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task T09: Extract B05–B07 (framework / cfg / setup, ~590 lines)

**Files:**
- Create: `src/splatpipe/viewers/spark/template_parts/05_framework.js_tmpl`
- Create: `src/splatpipe/viewers/spark/template_parts/06_cfg.js_tmpl`
- Create: `src/splatpipe/viewers/spark/template_parts/07_three_spark_setup.js_tmpl`
- Modify: `src/splatpipe/viewers/spark/template_parts/00_legacy_blob.html_tmpl`

Three fragments in dependency order.

- [ ] **Step 1: Identify the boundaries**

`05_framework.js_tmpl` starts at `  // ============================================================\n  //  Unified SceneView framework (Task 0 — FOUNDATION)` and ends at the line just before `  // ---- Viewer config ----`.

`06_cfg.js_tmpl` starts at `  // ---- Viewer config ----` and ends at the line just before `  // ---- THREE + Spark setup ----`.

`07_three_spark_setup.js_tmpl` starts at `  // ---- THREE + Spark setup ----` and ends at the line just before `  // ---- Detail-lever URL overrides ...`.

- [ ] **Step 2: Write the three fragments** by copying bytes.

- [ ] **Step 3: Remove the same bytes from `00_legacy_blob.html_tmpl`**.

- [ ] **Step 4: Verify + tests**

```powershell
pytest tests/test_html_for_output_pin.py tests/test_html_for_save_mode.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/splatpipe/viewers/spark/template_parts/
git commit -m "refactor(modular): extract B05-B07 framework + cfg + setup (#112 T09)

Extract SceneView framework (ModeManager/OverlayScene/InteractionManager/
HudLayer), viewer config, and THREE+Spark setup into three fragments.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task T10: Extract B08–B16 (input + annotations, ~600 lines)

**Files:**
- Create: 8 fragment files in `template_parts/`
- Modify: `src/splatpipe/viewers/spark/template_parts/00_legacy_blob.html_tmpl`

Eight sequential fragments — each a self-contained block:

- `08_url_overrides.js_tmpl` (B08, ~120 lines)
- `09a_input_wasd.js_tmpl` (B09, ~85 lines)
- `09b_input_look.js_tmpl` (B10, ~70 lines)
- `09c_input_pivot.js_tmpl` (B11, ~40 lines)
- `09d_input_focus.js_tmpl` (B12 — includes `_autoFocusTick`; the T14-AF region anchor lives here)
- `09e_input_hud.js_tmpl` (B13, ~40 lines)
- `09f_input_touch.js_tmpl` (B14, ~65 lines)
- `09g_input_ios_callout.js_tmpl` (B15, ~185 lines)
- `10_annotations.js_tmpl` (B16, ~20 lines)

- [ ] **Step 1: Identify the boundaries**

Each block opens with its `// ----` banner line and ends at the line just before the next block's banner. The boundary list:

| Fragment | Starts at | Ends at (exclusive) |
|----------|-----------|----------------------|
| `08_url_overrides.js_tmpl` | `// ---- Detail-lever URL overrides ----` | `// ---- WASD / arrow-key fly navigation ----` |
| `09a_input_wasd.js_tmpl` | `// ---- WASD / arrow-key fly navigation ----` | `// ---- Right-drag "look" ----` |
| `09b_input_look.js_tmpl` | `// ---- Right-drag "look" ----` | `// ---- Double-click / double-tap pivot ----` |
| `09c_input_pivot.js_tmpl` | `// ---- Double-click / double-tap pivot ----` | `// ---- Auto view-tracking focus ----` |
| `09d_input_focus.js_tmpl` | `// ---- Auto view-tracking focus ----` | `// ---- Toggleable on-screen settings HUD ('H') ----` |
| `09e_input_hud.js_tmpl` | `// ---- Toggleable on-screen settings HUD ('H') ----` | `// ---- Touch gesture state machine ----` |
| `09f_input_touch.js_tmpl` | `// ---- Touch gesture state machine ----` | `// ---- iOS callout wedge ----` |
| `09g_input_ios_callout.js_tmpl` | `// ---- iOS callout wedge ----` | `// ---- Annotations (CSS2DObject) ----` |
| `10_annotations.js_tmpl` | `// ---- Annotations (CSS2DObject) ----` | `// ---- Camera-path playback ----` |

- [ ] **Step 2: Write each fragment** by copying bytes from the legacy blob.

- [ ] **Step 3: Remove the same bytes from `00_legacy_blob.html_tmpl`**.

- [ ] **Step 4: Verify + tests**

```powershell
pytest tests/test_html_for_output_pin.py tests/test_html_for_save_mode.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/splatpipe/viewers/spark/template_parts/
git commit -m "refactor(modular): extract B08-B16 input + annotations (#112 T10)

Extract URL overrides + WASD + look + pivot + focus + HUD + touch +
iOS-callout + annotations into 9 fragments.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task T11: Extract B17 (CubicSpline + buildPlayer, ~415 lines)

**Files:**
- Create: `src/splatpipe/viewers/spark/template_parts/11_playback_spline.js_tmpl`
- Modify: `src/splatpipe/viewers/spark/template_parts/00_legacy_blob.html_tmpl`

This is the `_SPLINE_REGION` (Task 11 in the legacy lock). Pure leaf — no side imports, no shared state.

- [ ] **Step 1: Identify the boundaries**

Start: `// ---- Camera-path playback ----` (line ~1935 in original `template.py`).
End: the line just before `// ============================================================\n  //  Camera selector — single-list union ...`.

- [ ] **Step 2: Write `11_playback_spline.js_tmpl`**.

- [ ] **Step 3: Remove the same bytes from `00_legacy_blob.html_tmpl`**.

- [ ] **Step 4: Verify + tests**

```powershell
pytest tests/test_html_for_output_pin.py tests/test_html_for_save_mode.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/splatpipe/viewers/spark/template_parts/
git commit -m "refactor(modular): extract B17 CubicSpline + buildPlayer (#112 T11)

Extract the camera-path spline (CubicSpline class + buildPlayer
factory + path utilities) into 11_playback_spline.js_tmpl.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task T12: Extract B18 (camera-select wiring, ~750 lines)

**Files:**
- Create: `src/splatpipe/viewers/spark/template_parts/12_camera_select.js_tmpl`
- Modify: `src/splatpipe/viewers/spark/template_parts/00_legacy_blob.html_tmpl`

Carries `_T19_JS` + `_T20_CAMSEL_DOM`-absorbed wiring. Includes the kebab menu wiring + `_camSelInit` / `_camSelApply` / `_camSelReflect` / `_camSelCreate` / `_camSelRename` / `_camSelDelete`.

- [ ] **Step 1: Identify the boundaries**

Start: `// ============================================================\n  //  Camera selector — single-list union ...`
End: the line just before `// ============================================================\n  //  ClipPlayer (Task 14 ...`

- [ ] **Step 2: Write `12_camera_select.js_tmpl`**.

- [ ] **Step 3: Remove from legacy blob**.

- [ ] **Step 4: Verify + tests**

```powershell
pytest tests/test_html_for_output_pin.py tests/test_html_for_save_mode.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/splatpipe/viewers/spark/template_parts/
git commit -m "refactor(modular): extract B18 camera-select (#112 T12)

Extract camera-select / kebab menu / #path-mini wiring (T19-JS absorbed +
T20-CAMSEL-DOM-related JS) into 12_camera_select.js_tmpl.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task T13: Extract B19–B22 (ClipPlayer, user transport, bench, budget, ~1500 lines)

**Files:**
- Create: 4 fragment files
- Modify: legacy blob

Sub-fragments:
- `13_clip_player.js_tmpl` (B19, ~415 lines) — ClipPlayer + `_buildClipPlayer` + `_clipStart` + next-cut LOD prewarm scheduler
- `14_user_transport.js_tmpl` (B20, ~410 lines) — End-user transport + `_orbitPathAround` + `_stopTour` + `_resumeTour` + `_startIdleOrbit` + `_userPlayBtn` + transport layer
- `15_bench.js_tmpl` (B21, ~580 lines) — Bench launchers (orbit / probe / rotate / dolly / cold) + `?bench=` auto-trigger
- `16_splat_budget.js_tmpl` (B22, ~90 lines) — Splat budget dropdown + initial pick

- [ ] **Step 1: Identify the boundaries**

| Fragment | Starts at | Ends at (exclusive) |
|----------|-----------|----------------------|
| `13_clip_player.js_tmpl` | `// ============================================================\n  //  ClipPlayer (Task 14 ...` | `// ============================================================\n  //  End-user transport (Task 15 ...` |
| `14_user_transport.js_tmpl` | `// ============================================================\n  //  End-user transport (Task 15 ...` | the line just before `// ---- Bench launchers ...` |
| `15_bench.js_tmpl` | `// ---- Bench launchers ...` | `// ---- Splat budget dropdown ----` |
| `16_splat_budget.js_tmpl` | `// ---- Splat budget dropdown ----` | the line just before `// ============================================================\n  //  Author editor -- viewport trajectory ...` |

- [ ] **Step 2: Write each fragment**.

- [ ] **Step 3: Remove from legacy blob**.

- [ ] **Step 4: Verify + tests**

```powershell
pytest tests/test_html_for_output_pin.py tests/test_html_for_save_mode.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/splatpipe/viewers/spark/template_parts/
git commit -m "refactor(modular): extract B19-B22 playback (#112 T13)

Extract ClipPlayer + end-user transport + bench launchers + splat-budget
dropdown into 4 fragments.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task T14: Extract B23–B25 (editor core, ~4015 lines)

**Files:**
- Create: 3 fragment files
- Modify: legacy blob

The editor extraction. Three large fragments (each exceeds the 500-line target — accepted per spec §10 q4):
- `17_editor_trajectory.js_tmpl` (B23, ~945 lines) — Trajectory overlay: polyline + frusta + tick dots + active marker + `_trajPathScale` + `_trajApplyScale` + scene-relative sizing
- `18_editor_timeline.js_tmpl` (B24, ~990 lines) — Bottom timeline: scrub / diamonds / transport / zoom / multiselect / scale
- `19_editor_gizmo.js_tmpl` (B25, ~2085 lines) — Gizmo + interp popover + Record + Save (incl. SPCP1 JS port `_encodeSpcp` / `_spcpNum`)

These three together replace what the legacy lock excised as `_T16_TRAJ` (one big region absorbing all three sub-features per recipe 2c).

- [ ] **Step 1: Identify the boundaries**

| Fragment | Starts at | Ends at (exclusive) |
|----------|-----------|----------------------|
| `17_editor_trajectory.js_tmpl` | `// ============================================================\n  //  Author editor -- viewport trajectory ...` | `// ============================================================\n  //  Author editor -- bottom timeline (Task 17 ...` |
| `18_editor_timeline.js_tmpl` | `// ============================================================\n  //  Author editor -- bottom timeline (Task 17 ...` | `// ============================================================\n  //  Author editor -- select-key gizmo ...` |
| `19_editor_gizmo.js_tmpl` | `// ============================================================\n  //  Author editor -- select-key gizmo ...` | `// ---- Frame loop ----` |

Note: this is the largest single extraction. Take care with `${` audit for the SPCP JS port (string formatting). The pre-flight `${` audit (pre-flight step 3) should have caught any ES template literals — if any are present in B25 (e.g. in the SPCP1 token construction), they will have been converted in T03 to literal `${` via `$$$$` and will substitute back to `${` in `Template.substitute`. Verify with the output-pin.

- [ ] **Step 2: Write each fragment**.

- [ ] **Step 3: Remove from legacy blob**.

- [ ] **Step 4: Verify + tests**

```powershell
pytest tests/test_html_for_output_pin.py tests/test_html_for_save_mode.py -v
```

Expected: all pass. **Most likely failure mode:** the SPCP encoder fragment contains a literal `${...}` that was wrongly transformed in T03. Diagnose by `grep -nF '${' 19_editor_gizmo.js_tmpl` and confirm any occurrences are legitimate placeholders (not literal JS template literal escapes).

- [ ] **Step 5: Commit**

```bash
git add src/splatpipe/viewers/spark/template_parts/
git commit -m "refactor(modular): extract B23-B25 editor core (#112 T14)

Extract author editor surfaces (trajectory overlay + bottom timeline +
gizmo+Save+SPCP) into 3 fragments. Replaces the legacy T16-TRAJ region.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task T15: Extract B26–B27 (frame loop + intro IIFE, ~1005 lines)

**Files:**
- Create: 2 fragment files
- Modify: legacy blob (should now be very small — just the leftover bytes)

- `20_frame_loop.js_tmpl` (B26, ~885 lines) — Frame loop + bench recorder + Set-start-view + Centre-first / Early reveal / Front-load preload IIFE + LoD root-chunk eviction guard + T14-PW prewarm guard-twin
- `21_intro_controller.js_tmpl` (B27, ~125 lines) — Intro controller IIFE (cinematic loading-blur + fade)

- [ ] **Step 1: Identify the boundaries**

| Fragment | Starts at | Ends at (exclusive) |
|----------|-----------|----------------------|
| `20_frame_loop.js_tmpl` | `// ---- Frame loop ----` | `// ============================================================\n  //  Intro controller (Task 13 ...` |
| `21_intro_controller.js_tmpl` | `// ============================================================\n  //  Intro controller (Task 13 ...` | `tick();\n  // Debug hook for Playwright smoke tests` (this last line is in `99_closing.html_tmpl`) |

Note: `tick();\n` lives at the end of `21_intro_controller.js_tmpl`; the next line (`// Debug hook ...`) is the first line of `99_closing.html_tmpl` (already extracted in T04).

- [ ] **Step 2: Write each fragment**.

- [ ] **Step 3: Remove from legacy blob**

At this point `00_legacy_blob.html_tmpl` should be EMPTY (or contain only the trailing newline if any). Delete it.

```powershell
Remove-Item src/splatpipe/viewers/spark/template_parts/00_legacy_blob.html_tmpl
```

- [ ] **Step 4: Verify + tests**

```powershell
python - <<'PY'
from pathlib import Path
d = Path("src/splatpipe/viewers/spark/template_parts")
parts = sorted(d.glob("*_tmpl"))
total = "".join(p.read_text(encoding="utf-8") for p in parts)
print(f"concatenated {len(parts)} files, total bytes = {len(total)}")
PY

pytest tests/test_html_for_output_pin.py tests/test_html_for_save_mode.py -v
pytest -q
```

Expected: all pass. Concatenated byte count exactly matches the count from T03's legacy blob.

- [ ] **Step 5: Commit**

```bash
git add src/splatpipe/viewers/spark/template_parts/
git commit -m "refactor(modular): extract B26-B27 frame loop + intro IIFE; delete legacy blob (#112 T15)

Extract frame loop + bench recorder + setstart + preload IIFE +
intro controller. The 00_legacy_blob.html_tmpl is now empty and
removed. The template is fully modularized.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task T16: Retire legacy excised-region byte-lock

**Files:**
- Modify: `tests/test_html_for_save_mode.py`

After T15, every legacy `_T*_*` anchor const may reference text that no longer occupies a recognizable position in the *source* (it's split across files). The legacy lock has been passing all this time because `html_for(...)` STILL produces byte-identical HTML for the `HarnessScene` fixture — the excision happens on the *generated* HTML, not the source. So technically the legacy lock could survive forever.

**The reason to retire it:** with the output-pin, the legacy lock is now strictly weaker (it only covers `HarnessScene`, the output-pin covers 6 fixtures including `HarnessScene`) and adds ~2000 lines of moving-baseline narrative that is no longer actionable. Retire just the main assertion + the 14 region anchor consts. Keep the `(a)/(b)/(c)/(d)` API-shape tests, the `_INSERT_ANCHOR` for SAVE_* contract, and the 3 NEGATIVE-CONTROL `my*` tests.

- [ ] **Step 1: Remove the legacy lock's main test function**

Open `tests/test_html_for_save_mode.py`. Delete:
- The `_PRE_TASK20_REMAINDER_LEN` / `_PRE_TASK20_REMAINDER_SHA` / `_PRE_TASK20_FULL_LEN` / `_PRE_TASK20_FULL_SHA` pin constants (and the prior `_PRE_TASK20VC_*`, `_PRE_TASK19_*`, `_PRE_TASK17_*`, `_PRE_TASK16_*`, `_PRE_TASK15_*`, `_PRE_TASK14_*` provenance blocks).
- All `_T*_*` anchor constants (`_T12_CSS_START` / `_END`, `_T12_DOM_*`, `_T12_MM_*`, `_T13_LB_*`, `_T13_AS_*`, `_T13_IC_*`, `_T14_PW_*`, `_T14_AF_*`, `_T15_OB_*`, `_T16_TRAJ_*`, `_T19_CSS_*`, `_T19_JS_*`, `_T20_CAMSEL_DOM_*`, `_SPLINE_REGION_*`).
- The `_excise(...)` helper function.
- The `test_defaults_are_regression_safe_existing_scenes_byte_identical(...)` function (the main excised-region assertion — ~700 lines).

**Keep:**
- `_INSERT_ANCHOR` (used for the SAVE_* contract assertion).
- `_SECRET_SENTINEL`.
- `_drain` helper.
- All `test_defaults_bake_cli_and_empty_endpoint`, `test_explicit_http_mode_and_endpoint_are_baked`, `test_none_endpoint_serialises_to_empty_string`, `test_endpoint_with_quotes_is_json_escaped_not_injected`, `test_html_for_has_no_secret_kwarg`, `test_secret_value_never_appears_in_generated_html`.
- All NEGATIVE-CONTROL tests: `test_camera_path_overlay_is_scene_relative_not_fixed`, `test_motion_ticks_are_tiny_white_and_line_has_gradient`, `test_real_gizmo_handle_drag_wiring_present_and_author_tour_suppressed`.
- The `_git_blob_module(...)` helper (used by the my16/17/18 tests).
- All `test_publish_call_site_*`, `test_assembler_call_site_*` tests in section (d).

- [ ] **Step 2: Add a brief docstring at the top of the file explaining the retirement**

```python
"""Save-backend plumbing + the per-fix NEGATIVE-CONTROL tests.

Originally this file held the EXCISED-REGION BYTE-LOCK (a giant
test_defaults_are_regression_safe_existing_scenes_byte_identical that
pinned ~5000 lines of editor code via 14 source-anchored regions).
As of #112 (the Spark viewer template modularization), that lock has
been RETIRED in favor of the output-pin in test_html_for_output_pin.py
— which pins the GENERATED HTML for a corpus of scenes and survives
ANY source restructuring.

This file now keeps:
  (a) defaults / explicit / edge case tests for html_for's kwarg shape
      (cli/http, endpoint quoting/escaping, None handling, secret leak
      protection)
  (b) NEGATIVE-CONTROL tests for specific per-fix invariants (my16/17/18:
      scene-relative trajectory overlay, tiny-white motion ticks + line
      gradient, real-drag gizmo wiring + author-tour suppression). These
      load a pre-fix template via git cat-file blob and prove the fix is
      a real discriminator.
  (d) Both call sites (publish.py + assembler.py) threading
      save_backend from config.

The output-pin in test_html_for_output_pin.py is the SOLE byte-identity
guarantee for html_for now.
"""
```

- [ ] **Step 3: Run the cut-down test file**

```powershell
pytest tests/test_html_for_save_mode.py -v
```

Expected: all retained tests pass. Test count drops from ~21 to ~14 in this file (the main lock's ~700-line function gone; the my16/17/18 + (a)+(c)+(d) tests remain).

- [ ] **Step 4: Run the output-pin + full suite**

```powershell
pytest tests/test_html_for_output_pin.py -v
pytest -q
```

Expected: ~720 passed total. The main lock test (`test_defaults_are_regression_safe_existing_scenes_byte_identical`) is a single pytest function — we drop 1 test and add the 7 output-pin tests, so the net is ~720 (713 + 7) — exact count depends on whether parametrize cases count individually in your pytest version.

- [ ] **Step 5: Update the CLAUDE.md test-count badge if it changed**

```powershell
Select-String -Path CLAUDE.md -Pattern '593 collected' -List
Select-String -Path README.md -Pattern '593 collected' -List
```

Both reference 593. After this work, run `pytest --co -q | tail -3` to get the new count, and update CLAUDE.md (Quick Start + Tests sections) and README.md (badge + Development section) accordingly.

- [ ] **Step 6: Commit**

```bash
git add tests/test_html_for_save_mode.py CLAUDE.md README.md
git commit -m "refactor(modular): retire legacy excised-region byte-lock (#112 T16)

The 14-region excised lock served us for ~12 editor tasks but was always
a source-coupled approximation of the real invariant (generated HTML
byte-identity). The output-pin in test_html_for_output_pin.py is the
direct, modularization-safe replacement.

Retained: the kwarg-shape tests, the my16/17/18 negative-control tests,
the publish/assembler call-site tests. The _T*_* anchor consts and the
main length+sha assertion are removed.

Test count: <NEW_COUNT> (updated in CLAUDE.md + README.md).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Post-completion checklist

After T16 the file structure is:

```
src/splatpipe/viewers/spark/
  template.py  (~140 lines — orchestrator + share-meta + html_for)
  template_parts/
    __init__.py
    01_head_meta.html_tmpl
    02_styles_main.css_tmpl
    02_styles_editor.css_tmpl
    03_body_main.html_tmpl
    03_body_camera_select.html_tmpl
    03_body_path_hud.html_tmpl
    04_js_prologue.js_tmpl
    05_framework.js_tmpl
    06_cfg.js_tmpl
    07_three_spark_setup.js_tmpl
    08_url_overrides.js_tmpl
    09a_input_wasd.js_tmpl
    09b_input_look.js_tmpl
    09c_input_pivot.js_tmpl
    09d_input_focus.js_tmpl
    09e_input_hud.js_tmpl
    09f_input_touch.js_tmpl
    09g_input_ios_callout.js_tmpl
    10_annotations.js_tmpl
    11_playback_spline.js_tmpl
    12_camera_select.js_tmpl
    13_clip_player.js_tmpl
    14_user_transport.js_tmpl
    15_bench.js_tmpl
    16_splat_budget.js_tmpl
    17_editor_trajectory.js_tmpl
    18_editor_timeline.js_tmpl
    19_editor_gizmo.js_tmpl
    20_frame_loop.js_tmpl
    21_intro_controller.js_tmpl
    99_closing.html_tmpl
```

30 fragment files. Median size: ~125 lines (the input fragments). Largest: 19_editor_gizmo.js_tmpl at ~2085 lines (accepted per spec §10 q4 — follow-up split deferred).

### Update CLAUDE.md Package Layout

```powershell
# Update the Package Layout tree in CLAUDE.md to list:
#   viewers/spark/template.py — orchestrator (loads + substitutes fragments)
#   viewers/spark/template_parts/ — 30 plain-text fragments
```

Update CLAUDE.md → Package Layout → `viewers/spark/` section to reflect the new structure.

### Update CHANGELOG.md

```markdown
## [Unreleased]

### Changed
- Spark viewer template (`viewers/spark/template.py`) refactored from a
  single ~9.6k-line string into 30 plain-text fragment files under
  `viewers/spark/template_parts/`. Orchestrator loads + concatenates
  fragments and uses `string.Template` for placeholder substitution.
  Zero behavior change — generated HTML is byte-identical for every
  test fixture and every deployed scene. Brace-doubling is gone.
- Replaced excised-region byte-lock with output-pin
  (`tests/test_html_for_output_pin.py`) — modularization-safe and a
  more direct expression of the real invariant.

### Removed
- `tests/test_html_for_save_mode.py::test_defaults_are_regression_safe_existing_scenes_byte_identical`
  and its 14 source-anchor constants (replaced by the output-pin above).
```

---

## Notes for the engineer executing this plan

1. **Use UTF-8 with LF endings.** Every fragment file must be UTF-8, no BOM, LF line endings. PowerShell `>` redirection is unsafe on Windows — use the Python subprocess pattern from the CRLF-foot-gun note in `test_html_for_save_mode.py:990-1036` if you need to round-trip a fragment through a subprocess. Better: edit fragments directly via the Edit tool, never via shell redirection.

2. **Each task ends with both byte-locks passing.** If either fails, the task is not done. Revert and diagnose.

3. **Each task is one commit.** No "fix-up" follow-ups inside a task. If you need to fix something, that's a new commit.

4. **The output-pin is your safety net.** If you're ever uncertain whether an extraction is byte-safe, run `pytest tests/test_html_for_output_pin.py -v` — it tells you definitively in <2 seconds whether the bytes changed.

5. **The brace-undoubling in T03 is the trickiest step.** Verify the output by spot-checking the produced fragment: every `body {` should be `body {` (not `body {{`), every `if (foo)` followed by `{` should look like JS, and `${project_name}` should appear at the title spot. If anything looks off, do not commit T03 — fix the regex first.

6. **The largest fragments (B25 at 2085, B24 at 990, B23 at 945) can be split further in a follow-up.** Don't try to subdivide them in this work — the first split is already a major win, and the follow-up has more context-bound expertise about where the natural sub-boundaries are.
