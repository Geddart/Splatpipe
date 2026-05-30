"""Multi-camera CLIP EDITOR contract tests (#164 -- stacked two-level
bottom timeline: a Cuts master track <-> per-clip camera keyframes).

The clip editor is a pure-JS extension shipped INSIDE the existing
``16_editor_timeline.js_tmpl`` IIFE (author-mode only). It reuses the
EXISTING substrate -- the CutsModule timeline lane
(``15d_cuts_module.js_tmpl``), the ClipPlayer (``11_clip_player``), the
``_camSelApply`` drill primitive (``10_camera_select``), and the diamond
row -- to add a two-level model:

  * ``_tlLevel === 'sequence'`` : the cuts track is the PRIMARY band
    (master clip sequence + master-time ruler). Click a clip block ->
    load that clip's camera (via ``_camSelApply``) + drop to clip level.
    Master Play = ``window.__clip.restart()`` (the cut chain); master
    scrub previews the active clip's camera, cutting at clip boundaries.
  * ``_tlLevel === 'clip'`` : the diamond row is the live keyframe editor
    for the selected clip's camera -- the EXISTING behaviour, byte-
    unchanged. DEFAULT level is 'sequence' when ``cfg.clips`` is non-empty,
    else 'clip' (so a single-camera / no-clip scene -- the 6 live scenes --
    stays at clip level and behaves EXACTLY as today).

Two test layers (mirrors ``test_cuts_module.py`` / ``test_undo_redo_ui.py``):

(a) STATIC: the generated viewer HTML carries the documented surface
    markers (the level state, the click->load primitive reuse, the back
    button + breadcrumb, the master-time draw, the sequence-scrub-via-
    the-existing-path reuse, the test surface). Pure Python -- no browser.

(b) DYNAMIC (Node): extract the SELF-CONTAINED master-time helpers
    (``_tlClipsLive`` + ``_tlSeqTotalDur`` + ``_tlClipAtMasterT``) and
    assert the clip-boundary resolution math (which clip owns a given
    master time, including the "last clip owns t == total" edge). Skips
    cleanly if Node is unavailable (CI provides it).

The full interactive verification (all 10 workflows) is the live-scene
Playwright pass; these tests lock the surface + the boundary math.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from splatpipe.viewers.spark.template import html_for

_NODE = shutil.which("node")


# --------------------------------------------------------------------------
# (a) STATIC: rendered HTML carries the clip-editor surface markers
# --------------------------------------------------------------------------


_CLIP_EDITOR_MARKERS = (
    # Two-level state + the default-level rule (sequence when clips exist,
    # else clip -> the 6 live no-clip scenes stay byte-runtime-identical).
    "let _tlLevel = _tlHasClips() ? 'sequence' : 'clip';",
    "let _tlActiveClipId = null;",
    "function _tlHasClips() { return _tlClipsLive().length > 0; }",
    # Click-a-clip -> load its camera via the EXISTING _camSelApply drill
    # primitive (NOT a duplicated bind).
    "function _tlEnterClip(clipId) {",
    "if (typeof _camSelApply === 'function') {",
    # Back to the cuts track (reuses stopPath, never a new mechanism).
    "function _tlEnterSequence() {",
    "function _tlSyncLevelUI() {",
    # The clip -> camera_paths resolution reuses the EXISTING two-step
    # _clipPath (NEVER assumes camera_id === path_id).
    "function _tlClipPath(clip) {",
    "if (typeof _clipPath === 'function') {",
    # Sequence-level draw: cuts track as the PRIMARY band + master ruler +
    # master playhead + dimmed context diamonds.
    "function _tlDrawSequence(ctx) {",
    "function _tlSeqTotalDur() {",
    "function _tlSeqPlayheadT() {",
    "function _tlClipAtMasterT(t) {",
    "function _tlHitClip(x, y) {",
    # The PRIMARY band reuses the registered CutsModule lane render.
    "function _tlCutsLane() {",
    # Sequence-level scrub reuses the EXISTING per-clip scrub path (NO
    # parallel clock); the cut goes through the EXISTING _camSelApply.
    "function _tlSeqScrubToMasterT(t) {",
    # The back button + breadcrumb DOM (built in JS, no new HTML markup).
    "const _tlSeqBack = _tlBtn('◂ Sequence', 'Back to the clip sequence');",
    "const _tlCrumb = document.createElement('span');",
    # Sequence-level Play drives the cut chain via the EXISTING ClipPlayer.
    "if (window.__clip && typeof window.__clip.restart === 'function') {",
    # Test surface hooks (functions/getters merged onto window.__editor).
    "tlEnterClip(clipId) {",
    "tlEnterSequence() { _tlEnterSequence(); return _tlLevel; },",
    "tlSeqScrub(masterT) {",
    "tlSeqPlay() {",
    "get tlLevel() { return _tlLevel; },",
    "get tlActiveClipId() { return _tlActiveClipId; },",
    "tlClipPathId(clipId) {",
)


def test_clip_editor_markers_present_in_rendered_html():
    """Every documented clip-editor surface marker is present in the
    generated viewer HTML."""
    html = html_for("HarnessScene")
    for mk in _CLIP_EDITOR_MARKERS:
        assert mk in html, f"clip-editor marker missing: {mk!r}"


def test_clip_editor_reuses_camsel_apply_not_a_new_bind():
    """The click->load primitive MUST be the EXISTING _camSelApply (which
    binds selEl + rebuilds trajectory/gizmo/diamond row + snaps the camera
    pose) -- NOT a re-implemented bind. _tlEnterClip resolves the clip's
    path then calls _camSelApply(path.id)."""
    html = html_for("HarnessScene")
    enter_i = html.index("function _tlEnterClip(clipId) {")
    seg = html[enter_i:enter_i + 1600]
    assert "_camSelApply(path.id)" in seg, (
        "_tlEnterClip must call the EXISTING _camSelApply drill primitive"
    )
    # And it must NOT assume camera_id === path_id (resolve via _clipPath).
    assert "_tlClipPath(clip)" in seg


def test_clip_editor_sequence_scrub_reuses_existing_scrub_path():
    """The sequence-level master scrub MUST reuse the EXISTING per-clip
    #path-scrub mechanism (_tlScrubToTime), NOT a second scrub clock (a
    parallel clock re-introduces the camera-hijack the R3 #6 fix closed).
    The cut at a clip boundary goes through the EXISTING _camSelApply."""
    html = html_for("HarnessScene")
    seq_i = html.index("function _tlSeqScrubToMasterT(t) {")
    seg = html[seq_i:seq_i + 1700]
    assert "_tlScrubToTime(" in seg, (
        "sequence scrub must drive the EXISTING _tlScrubToTime (no new clock)"
    )
    assert "_camSelApply(path.id)" in seg, (
        "the boundary cut must reuse _camSelApply"
    )


def test_clip_editor_default_level_is_clip_for_no_clip_scenes():
    """A no-clip scene defaults to 'clip' level so the 6 live single-camera
    scenes behave EXACTLY as today (the sequence-level branches are present
    but inert -- _tlHasClips() is false). The DEFAULT-level expression is
    the single lever that guarantees this."""
    html = html_for("HarnessScene")
    assert "let _tlLevel = _tlHasClips() ? 'sequence' : 'clip';" in html
    # The _tlDraw sequence branch is gated on BOTH _tlLevel==='sequence'
    # AND _tlHasClips() so a no-clip scene can never enter the sequence
    # draw path (belt-and-braces).
    assert "if (_tlLevel === 'sequence' && _tlHasClips()) {" in html


def test_clip_editor_does_not_redeclare_clip_player_or_timeline_globals():
    """#164 invariant: the clip editor lives INSIDE the 16 IIFE and reuses
    11_clip_player's module-level globals via closure -- it MUST NOT
    redeclare them (a shadow would break end-user playback + the editor)."""
    from splatpipe.viewers.spark import template as tmpl

    parts = Path(tmpl.__file__).parent / "template_parts"
    tl = (parts / "16_editor_timeline.js_tmpl").read_text(encoding="utf-8")
    for global_name in ("_clipState", "_clipMode", "_clipSeq", "_clipPath",
                        "_buildClipPlayer", "_clipStart", "_camSelApply"):
        for form in ("let " + global_name + " ", "const " + global_name + " ",
                     "var " + global_name + " "):
            assert form not in tl, (
                f"clip editor must NOT redeclare the shared global "
                f"{global_name!r} -- found {form!r} which would shadow the "
                "module-level binding owned by 10/11"
            )


def test_clip_editor_fragment_clean_no_bom_no_crlf():
    """The 16 fragment (which now carries the clip editor) is UTF-8 with no
    BOM + LF line endings (a Windows tool slip would shift the output-pin
    SHA)."""
    from splatpipe.viewers.spark import template as tmpl

    parts = Path(tmpl.__file__).parent / "template_parts"
    raw = (parts / "16_editor_timeline.js_tmpl").read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf"), "BOM corruption"
    assert not raw.startswith(b"\xff\xfe"), "UTF-16 BOM corruption"
    assert b"\r" not in raw, "CRLF line endings"


# --------------------------------------------------------------------------
# (b) DYNAMIC (Node): master-time clip-boundary resolution math
# --------------------------------------------------------------------------


def _extract_fn(html: str, signature: str) -> str:
    """Extract a balanced ``function name(...) { ... }`` body by brace-
    counting from a single-occurrence signature. Used to pull the SELF-
    CONTAINED master-time helpers for a Node unit test."""
    a = html.index(signature)
    # Walk from the first '{' counting braces.
    i = html.index("{", a)
    depth = 0
    j = i
    while j < len(html):
        c = html[j]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return html[a:j + 1]
        j += 1
    raise AssertionError(f"unbalanced braces for {signature!r}")


def _run_node(script: str) -> dict:
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "clip_editor_test.mjs"
        f.write_text(script, encoding="utf-8")
        out = subprocess.run(
            [_NODE, str(f)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=60,
        )
    if out.returncode != 0:
        raise AssertionError(
            "node failed (rc=%d):\n--- stderr ---\n%s\n--- stdout ---\n%s"
            % (
                out.returncode,
                out.stderr.decode("utf-8", "replace"),
                out.stdout.decode("utf-8", "replace"),
            )
        )
    return json.loads(out.stdout.decode("utf-8"))


def _master_time_preamble() -> str:
    """A minimal shim + the three SELF-CONTAINED master-time helpers pulled
    verbatim from the rendered HTML. ``_tlClipsLive`` reads ``cfg.clips``;
    ``_tlSeqTotalDur`` + ``_tlClipAtMasterT`` build on it. No DOM / no
    _tlW / no zoom needed for the boundary-resolution assertions."""
    html = html_for("HarnessScene")
    body = (
        "globalThis.window = globalThis;\n"
        "globalThis.cfg = { clips: [] };\n"
        + _extract_fn(html, "function _tlClipsLive() {") + "\n"
        + _extract_fn(html, "function _tlSeqTotalDur() {") + "\n"
        + _extract_fn(html, "function _tlClipAtMasterT(t) {") + "\n"
    )
    return body


@pytest.mark.skipif(_NODE is None, reason="node not available")
def test_master_time_total_dur_sums_clip_durations():
    """_tlSeqTotalDur is the sum of clip durations (the master sequence
    length) -- read live from cfg.clips, sorted by clip_start."""
    js = _master_time_preamble() + r"""
cfg.clips = [
  { id: 'a', camera_id: 'ca', clip_start: 0, duration: 4, in: 0 },
  { id: 'b', camera_id: 'cb', clip_start: 4, duration: 6, in: 0 },
  { id: 'c', camera_id: 'cc', clip_start: 10, duration: 5, in: 0 },
];
process.stdout.write(JSON.stringify({ total: _tlSeqTotalDur() }));
"""
    r = _run_node(js)
    assert r["total"] == 15


@pytest.mark.skipif(_NODE is None, reason="node not available")
def test_master_time_clip_at_resolves_boundaries():
    """_tlClipAtMasterT maps a master time -> the active clip (the cut
    boundary logic). A time inside clip N returns clip N + the within-clip
    offset; the LAST clip owns t == total (so the sequence end previews the
    final clip's last pose) -- the documented edge."""
    js = _master_time_preamble() + r"""
cfg.clips = [
  { id: 'a', camera_id: 'ca', clip_start: 0, duration: 4, in: 0 },
  { id: 'b', camera_id: 'cb', clip_start: 4, duration: 6, in: 0 },
  { id: 'c', camera_id: 'cc', clip_start: 10, duration: 5, in: 0 },
];
function probe(t) {
  const at = _tlClipAtMasterT(t);
  return at ? { id: at.clip.id, idx: at.idx, clipStart: at.clipStart,
    within: Math.round(at.within * 1000) / 1000 } : null;
}
process.stdout.write(JSON.stringify({
  t0: probe(0),       // start of clip a
  t2: probe(2),       // mid clip a
  tBoundary: probe(4),// exactly the a->b cut -> clip b, within 0
  t7: probe(7),       // mid clip b
  t12: probe(12),     // mid clip c
  tTotal: probe(15),  // == total -> LAST clip (c) owns it
  tPast: probe(99),   // past the end -> still the last clip (c)
}));
"""
    r = _run_node(js)
    assert r["t0"] == {"id": "a", "idx": 0, "clipStart": 0, "within": 0}
    assert r["t2"] == {"id": "a", "idx": 0, "clipStart": 0, "within": 2}
    # t == 4 is the a->b cut boundary: clip b owns it (clip_start <= t).
    assert r["tBoundary"] == {"id": "b", "idx": 1, "clipStart": 4,
                              "within": 0}
    assert r["t7"] == {"id": "b", "idx": 1, "clipStart": 4, "within": 3}
    assert r["t12"] == {"id": "c", "idx": 2, "clipStart": 10, "within": 2}
    # t == total and t past the end both resolve to the LAST clip (c).
    assert r["tTotal"]["id"] == "c"
    assert r["tPast"]["id"] == "c"


@pytest.mark.skipif(_NODE is None, reason="node not available")
def test_master_time_empty_clips_is_null_and_zero():
    """A no-clip scene: _tlSeqTotalDur is 0 and _tlClipAtMasterT returns
    null (so the sequence-level draw shows the empty-state hint, never
    crashes -- the degenerate workflow #10 baseline)."""
    js = _master_time_preamble() + r"""
cfg.clips = [];
process.stdout.write(JSON.stringify({
  total: _tlSeqTotalDur(),
  at0: _tlClipAtMasterT(0),
}));
"""
    r = _run_node(js)
    assert r["total"] == 0
    assert r["at0"] is None


@pytest.mark.skipif(_NODE is None, reason="node not available")
def test_master_time_reads_clips_in_clip_start_order():
    """_tlClipsLive sorts by clip_start (playback order), so an out-of-
    array-order clips list still resolves boundaries by playback order."""
    js = _master_time_preamble() + r"""
// Deliberately store clips OUT of clip_start order.
cfg.clips = [
  { id: 'second', camera_id: 'c2', clip_start: 5, duration: 5, in: 0 },
  { id: 'first', camera_id: 'c1', clip_start: 0, duration: 5, in: 0 },
];
const at = _tlClipAtMasterT(2);   // master time 2 -> the FIRST clip
process.stdout.write(JSON.stringify({
  orderIds: _tlClipsLive().map(k => k.id),
  at2Id: at ? at.clip.id : null,
}));
"""
    r = _run_node(js)
    assert r["orderIds"] == ["first", "second"]
    assert r["at2Id"] == "first"
