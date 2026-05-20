"""Spark 2 viewer template — emits a self-contained index.html.

Loads a single ``scene.rad`` (from Spark's Rust build-lod) via
``new SplatMesh({url, paged: true})`` for HTTP-Range streaming.
Falls back to ``scene.sog`` if configured. Mirrors the PlayCanvas viewer's
feature set: annotations (CSS2DObject), camera-path HUD, foveation,
conditional audio + camera bounds, tone mapping.

Pinned versions (bump in lockstep):
  - @sparkjsdev/spark 2.0.0   (released)
  - three 0.180.0             (peer dep of @sparkjsdev/spark 2.0.0)

Structure (modularized 2026-05-20, T1 of 6; #118):
  The viewer body lives in fragment files under ``template_parts/`` and is
  assembled here at runtime. Fragments are raw JS / CSS / HTML (no
  brace-doubling). Python placeholders use the ``@@NAME@@`` protocol
  (zero collisions in JS / CSS / HTML / template-literal content). The
  orchestrator concatenates fragments in lexical filename order and
  substitutes the placeholders via :func:`_substitute`.

  See ``docs/superpowers/plans/2026-05-20-modularize-spark-viewer-template-v2.md``
  for the design rationale.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path


SPARK_VERSION = "2.0.0"  # upstream base the fork derives from
THREE_VERSION = "0.180.0"
# Patched Spark fork. Upstream @sparkjsdev/spark 2.0.0 has two --cluster-sh
# aborts that surface as a generic browser "Out of Memory" page:
#   1. RefCell re-entrancy in ChunkDecoder::push (BUFFER thread-local held
#      across the re-entrant receiver callback) — fixed in decoder.rs.
#   2. Chunk-0 codebook ordering race: a non-zero chunk decodes before
#      chunk 0's SH codebook arrives, so set_sh_labels indexes an empty
#      Vec ("index out of bounds: the len is 0") — fixed in SplatPager.ts
#      by gating non-zero cluster-sh chunks on chunk 0.
# Self-hosted, version-pinned path; never float and never reuse the path
# (Bunny edge-cache). Bump -rcfN whenever the fork changes.
SPARK_FORK_URL = "https://splatpipe-cdn.b-cdn.net/_sparkfork-rcf2/spark.module.min.js"


_PARTS_DIR = Path(__file__).parent / "template_parts"

# Match @@NAME@@ where NAME is [A-Z_][A-Z0-9_]*. Anchored to @@ on both
# sides so it never matches a bare @, @-something, or a longer @@@@. Zero
# collisions in the body's JS / CSS / HTML / ES template-literal content
# (audited at refactor time; see v2 plan §4.1).
_PLACEHOLDER = re.compile(r"@@([A-Z_][A-Z0-9_]*)@@")


@lru_cache(maxsize=1)
def _load_template_body() -> str:
    """Concatenate every ``*.html_tmpl`` / ``*.css_tmpl`` / ``*.js_tmpl``
    file in ``template_parts/`` sorted by filename. Cached per process.
    Glob-sort is stable and human-readable; the NN_ filename prefix orders
    dependencies (head -> styles -> body chrome -> JS prologue -> JS body
    -> closing).
    """
    chunks: list[str] = []
    for p in sorted(_PARTS_DIR.iterdir()):
        if p.suffix in (".html_tmpl", ".css_tmpl", ".js_tmpl"):
            chunks.append(p.read_text(encoding="utf-8"))
    return "".join(chunks)


def _substitute(body: str, fields: dict[str, str]) -> str:
    """``@@NAME@@`` -> ``fields[NAME]``. Unknown name => KeyError (loud).
    Any unsubstituted ``@@...@@`` after the sweep => AssertionError
    (safety net for a fragment that introduces a syntactically valid but
    not-registered name).
    """

    def repl(m: re.Match[str]) -> str:
        name = m.group(1)
        if name not in fields:
            raise KeyError(
                f"unknown placeholder @@{name}@@ in template "
                f"(known: {sorted(fields)})"
            )
        return fields[name]

    out = _PLACEHOLDER.sub(repl, body)
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
    """Render the Spark viewer HTML for a given project.

    `primary_asset` is the filename the SplatMesh loads (relative to index.html).
    `paged=True` enables HTTP-Range streaming for `.rad`; should be False for `.sog`.

    Share-card (Open Graph + Twitter) so a pasted viewer link shows a rich
    preview in Telegram / WhatsApp / iMessage / Discord / Slack / Twitter:
      * `share_url`   — absolute URL of the deployed index.html. Optional;
                        when given it's emitted as `og:url`. Scrapers fall
                        back to the fetched URL when absent, so it's safe to
                        omit for the local dashboard preview.
      * `share_image` — preview image. Defaults to the relative
                        `"preview.jpg"` (a scraper resolves it against the
                        page URL); deploy scripts pass an ABSOLUTE Bunny URL
                        for maximum cross-platform compatibility. The image
                        itself is generated + uploaded separately
                        (`.codex-run/make_share_preview.py`).
      * `description` — card text; a sensible generic default otherwise.
    Backward-compatible: every arg is optional, so existing callers
    (`SparkAssembler`, older deploy scripts) keep working and still get a
    title/description card (plus the image card once `preview.jpg` exists).

    Save-backend plumbing (publish-time only; NO Save UI yet — a later task):
      * `save_mode`     — ``"cli"`` (default) or ``"http"``. Baked verbatim
                          as the ``SAVE_MODE`` JS const. With the default the
                          generated HTML is byte-identical to before apart
                          from the two new (inert) consts — existing scenes
                          are untouched. NOTHING reads these consts yet.
      * `save_endpoint` — POST URL for ``"http"`` mode (``None``/empty for
                          ``"cli"``); baked as ``SAVE_ENDPOINT``.
    The per-scene SECRET is intentionally NOT a parameter here and is never
    baked into the template nor written to viewer-config.json — in http mode
    it lives only in the author URL fragment (a later task).
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
    # Joined value is substituted as a single @@SHARE_META@@ slot; the
    # orchestrator's _substitute() does NOT re-scan substituted text, so
    # no escaping is needed here.
    share_meta = "\n  ".join(_meta)

    return _substitute(
        _load_template_body(),
        {
            "PROJECT_NAME": project_name,
            "SPARK_VERSION": SPARK_VERSION,
            "THREE_VERSION": THREE_VERSION,
            "SPARK_FORK_URL": SPARK_FORK_URL,
            "PRIMARY_ASSET": primary_asset,
            "PAGED_JSON": json.dumps(bool(paged)),
            "SAVE_MODE_JSON": json.dumps(save_mode),
            "SAVE_ENDPOINT_JSON": json.dumps(save_endpoint or ""),
            "SHARE_META": share_meta,
        },
    )
