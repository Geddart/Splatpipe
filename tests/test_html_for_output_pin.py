"""Output-pin byte-lock for the Spark viewer template.

Added 2026-05-20 as the modularization-safe successor to the (now-retired)
excised-region source-level byte-lock in ``test_html_for_save_mode.py``.

GOAL: pin ``(length, sha256)`` of ``html_for(...)`` output for a corpus of
representative scene fixtures so the refactor (#118) -- which moved the
viewer body from a single 9.6k-line Python format string into
``viewers/spark/template_parts/`` fragment files assembled by an
``@@NAME@@`` orchestrator -- is provably byte-identical for every fixture,
and any future template change that should be byte-inert (e.g. a code
move that should preserve generated HTML) is locked here.

CORPUS DESIGN (6 fixtures, all kwargs branches of ``html_for``):

  * ``harness_defaults``       -- the same fixture the retired excised-region
                                  lock covered (defaults: cli + empty endpoint).
  * ``http_basic``             -- http save_mode + real endpoint.
  * ``http_endpoint_quotes``   -- endpoint with embedded quotes (JSON escape).
  * ``none_endpoint``          -- save_endpoint=None serialises to "".
  * ``sog_fallback``           -- primary_asset=scene.sog + paged=False.
  * ``share_card``             -- all three share-card kwargs supplied
                                  (share_url + share_image + description).

EXPECTED VALUES (length + sha256) were captured against the pre-refactor
``template.py`` at HEAD ``f46fa67`` (the commit before T1 landed; see the
v2 plan at
``docs/superpowers/plans/2026-05-20-modularize-spark-viewer-template-v2.md``).
T1's verification step asserted ALL 6 fixtures produce byte-identical
output from the orchestrator + fragments.

WHEN TO UPDATE THE PINS: only when a DELIBERATE generated-HTML change is
made (a real feature edit). Then update both the length and the sha256
in lockstep. Do NOT update for a "byte-inert" refactor -- that's exactly
the change this test should catch.

PIN UPDATES:
  * 2026-05-20 (UX-5): user-reported regression in the live ?author=1
    editor on kf-fehmarn -- "<2-keyframe path is unscrub-able + record
    overwrites at t=0". The fix in 10_camera_select / 17_editor_gizmo
    fragments deliberately changes the generated HTML (lifts the
    stale-player stop + controls re-enable OUT of the snap block in
    ``_camSelApply``, adds a ``_GZ_DEFAULT_KF_DT`` constant in the K
    recorder for the 1-kf -> 2-kf bridge, and rewords the
    ``startPath`` <2-kf alert). All 6 fixtures shifted by the same
    +4383 byte delta in lockstep; pins updated to the new baseline.
  * 2026-05-20 (Phase 1 Q5): #author=<secret> -> #token=<token> URL
    fragment param rename (decouples the bearer name from the
    ?author=1 mode flag). The fragment parser ``_gzAuthorSecret()``
    was renamed to ``_gzReadAuthToken()`` with a backwards-compat
    branch that still reads ``#author=`` and ``console.warn``s. The
    Save body shape was also corrected to ``{slug, ...patch}`` (flat
    top-level, matching the PHP adapter wire contract) from the prior
    ``{slug, patch}`` wrapper that was wrong for the live PHP
    round-trip. All 6 fixtures shifted by the same +1408 byte delta
    in lockstep; pins re-pinned to the new baseline.
  * 2026-05-20 (Phase 1 live-verify): ``_gzSlug`` is now lower-cased
    before the character-class sanitiser strips non-``[a-z0-9_-]``
    chars. The mixed-case display name "Fehmarn" was being sent as
    the slug to ``save-camera.php`` which validates with
    ``^[a-z0-9_-]{1,64}$`` -- so every http-mode Save 400'd with
    "invalid slug". Caught by the Phase-1 live-verify against the
    deployed ``fehmarn`` slug. The fix lower-cases the H1 text first
    so the JS slug matches the canonical Bunny CDN convention (which
    is itself lowercase). SPCP1's ``encode_spcp`` is case-tolerant,
    so the cli-mode token continues to work; only http-mode was
    broken. All 6 fixtures shifted by the same +430 byte delta in
    lockstep; pins re-pinned to the new baseline.
  * 2026-05-20 (#123 hot-fix): the ``startPath`` <2-keyframe alert
    is now a silent ``console.warn`` + early-return (user feedback:
    the modal interrupted the authoring loop). Identical behaviour
    other than the suppressed alert. All 6 fixtures shifted by the
    same -16 byte delta in lockstep; pins re-pinned.
  * 2026-05-21 (Phase 2A #122): new ``EditorModuleRegistry`` (04a)
    and ``EditHistory`` (17a) fragments concatenated into the bundle,
    plus the ``05_framework`` wiring patch that exposes them at
    ``window.__sceneview.modules`` / ``.history`` and the keydown
    hotkey wiring (Ctrl+Z / Ctrl+Y / Ctrl+Shift+Z) at the tail of
    17a. All 6 fixtures shifted by the same +23616 byte delta in
    lockstep; pins re-pinned to the new baseline.
  * 2026-05-21 (Phase 2B #122): new ``CameraPathModule`` thin-wrapper
    fragment (15a) that registers with the EditorModuleRegistry as the
    canonical owner of the ``camera_paths`` slot, plus the
    ``17_editor_gizmo`` ``_buildPatch`` refactor that overlays
    ``EditorModuleRegistry.collectPatch()`` over the legacy
    ``_PATCH_KEYS`` walk (registered module slots WIN over legacy
    duplicates; an empty registry is a clean fallback to legacy). All
    6 fixtures shifted by the same +9515 byte delta in lockstep; pins
    re-pinned to the new baseline.
  * 2026-05-21 (Phase 2C #122 §3.7 + §4.1.1): three timeline addenda
    in ``16_editor_timeline.js_tmpl`` -- (1) total-time numeric input
    + auto toggle (writes ``path.total_duration_s``; one EditHistory
    snapshot on commit, never per keystroke); (2) Prev/Next-keyframe
    skip buttons (navigation, no snapshot); (3) Ctrl+Left / Ctrl+Right
    hotkeys (NAVIGATION; same author-mode gate + text-input skip
    pattern the 17a Ctrl+Z handler uses). Plus the JS mirror of the
    Python ``effective_scrub_range`` helper. All 6 fixtures shifted by
    the same +10141 byte delta in lockstep; pins re-pinned.
  * 2026-05-21 (Phase 2D #122 §12 + §4.10): new ``17b`` Scene Settings
    drawer scaffold (one HudLayer panel + cog toggle + sessionStorage
    persistence + 6 placeholder sections in registration order) plus
    a multi-lane timeline registry in ``16`` (infrastructure only;
    CameraPathModule's lane auto-registered via the EditorModuleRegistry
    'register' event). All 6 fixtures shifted by the same +16029 byte
    delta in lockstep; pins re-pinned.
  * 2026-05-21 (Phases 3-8 integration #122): six new editor module
    fragments concatenated into the bundle in one integration pass --
    PanoramaModule (equirect backdrop + rotation + intensity),
    PostFXModule (tonemapping + exposure sliders), AnnotationModule
    (dot_unfold + animatable + distance), CutsModule (edit-time NLE
    wrapping ClipPlayer), AudioModule (track CRUD + edit-time UI),
    TitlesModule (CSS2D renderer + editor for titles3d). Each phase
    deselected this output-pin during its individual commit to avoid
    double-baselining; this pin update re-baselines all 6 fixtures in
    ONE integration pass. All 6 fixtures shifted by the same +180878
    byte delta in lockstep -- perfect proof the module additions are
    additive only (no spooky-action elsewhere). Pins re-pinned to the
    new baseline.
  * 2026-05-21 (Phase 11A Issues 1+2): two UX fixes in the
    Perspective / camera-switch hot path. (1) ``_camSelApply``'s
    Perspective branch now UNCONDITIONALLY re-enables OrbitControls
    and clears any paused-scrub state -- the prior conditional
    re-enable only fired when ``_player`` was truthy, so a
    scrub-then-Perspective workflow left the controls dead and the
    user could not orbit-drag. (2) ``_trajActivePath`` (author
    mode, Perspective) now prefers paths with >=2 keyframes over an
    empty kf path in its fallback walk, so the trajectory overlay
    stays visible when the last-bound camera was a freshly-added
    empty one. Both regions are interior to existing T16-TRAJ-via-
    10-camera-select / T16-TRAJ excisions. All 6 fixtures shifted
    by the same +2720 byte delta in lockstep; pins re-pinned.
"""

from __future__ import annotations

import hashlib

import pytest

from splatpipe.viewers.spark.template import html_for


# CORPUS: list of (name, args, kwargs, expected_len, expected_sha256).
# Pins captured 2026-05-20 at HEAD f46fa67 (before T1 of #118), then
# re-pinned 2026-05-20 (UX-5 fix; +4383 bytes in lockstep), then
# re-pinned 2026-05-20 again (Phase 1 Q5: #author= -> #token= rename +
# Save body shape correction; all 6 fixtures +1408 bytes in lockstep),
# then re-pinned 2026-05-20 a third time (Phase 1 live-verify slug
# lower-case fix; all 6 fixtures +430 bytes in lockstep), then re-pinned
# 2026-05-20 (#123 hot-fix: startPath empty-path alert -> silent
# console.warn; all 6 fixtures -16 bytes in lockstep), then re-pinned
# 2026-05-21 (Phase 2A #122: EditorModuleRegistry + EditHistory +
# framework wiring + Ctrl+Z hotkeys; all 6 fixtures +23616 bytes in
# lockstep), then re-pinned 2026-05-21 (Phase 2B #122: CameraPathModule
# 15a wrapper + Save dispatch via registry collectPatch; all 6 fixtures
# +9515 bytes in lockstep), then re-pinned 2026-05-21 (Phase 2C #122:
# 3 timeline addenda -- total-time UI, Prev/Next, Ctrl+Left/Right;
# all 6 fixtures +10141 bytes in lockstep), then re-pinned 2026-05-21
# (Phase 2D #122: Scene Settings 17b + multi-lane registry; all 6
# fixtures +16029 bytes in lockstep), then re-pinned 2026-05-21
# (Phases 3-8 integration #122: six editor module fragments --
# Panorama + PostFX + Annotations + Cuts + Audio + Titles3D -- all 6
# fixtures +180878 bytes in lockstep; modules are additive only), then
# re-pinned 2026-05-21 (Phase 11A Issues 1+2: Perspective controls
# re-enable + trajectory fallback skips empty paths; +2720 in lockstep).
CORPUS: list[tuple[str, tuple, dict, int, str]] = [
    (
        "harness_defaults",
        ("HarnessScene",),
        {},
        716817,
        "1d7bca6e5ffb1d22ccc5f68e6d41bbcceaf1bd38c3462fb541feea5fa9927e51",
    ),
    (
        "http_basic",
        ("S",),
        {"save_mode": "http", "save_endpoint": "https://x.example/api/save"},
        716789,
        "79d09fc985599a825b9206605d7fd727281d5be15549dfa06e7dcf71e640f452",
    ),
    (
        "http_endpoint_quotes",
        ("S",),
        {"save_endpoint": 'https://x/"+evil()+"'},
        716784,
        "2a40fa683e6cd1a1d62bab9490443db931f3ec8c7eec18512cafb4ceb5f7d867",
    ),
    (
        "none_endpoint",
        ("S",),
        {"save_mode": "http", "save_endpoint": None},
        716763,
        "d3e3ec0fc9dfd05b1c899f780f8f870d7cca7a83ba83f826d6f2984baf0002af",
    ),
    (
        "sog_fallback",
        ("LegacySogScene",),
        {"primary_asset": "scene.sog", "paged": False},
        716828,
        "4dcc916b56306bd68acd7b125eaea635dfbd39979220669d339d4f962a024915",
    ),
    (
        "share_card",
        ("ShareScene",),
        {
            "share_url": "https://splatpipe-cdn.b-cdn.net/share/index.html",
            "share_image": "https://splatpipe-cdn.b-cdn.net/share/preview.jpg",
            "description": "Custom share description text.",
        },
        716687,
        "3136ec9b38641d339fefc98dffc00b934e2b4e9a59f63e42d3285bf370fed9eb",
    ),
]


@pytest.mark.parametrize(
    "name,args,kwargs,expected_len,expected_sha",
    CORPUS,
    ids=[c[0] for c in CORPUS],
)
def test_output_pin(
    name: str,
    args: tuple,
    kwargs: dict,
    expected_len: int,
    expected_sha: str,
) -> None:
    """``html_for(*args, **kwargs)`` produces exactly ``expected_len`` bytes
    and ``expected_sha`` SHA-256. A drift here means the generated HTML has
    changed -- if that's deliberate, update the pin in CORPUS; if not,
    that's the regression this test exists to catch."""
    html = html_for(*args, **kwargs)
    actual_len = len(html)
    actual_sha = hashlib.sha256(html.encode("utf-8")).hexdigest()

    assert actual_len == expected_len, (
        f"[{name}] length drift: {actual_len} != {expected_len} "
        f"(delta {actual_len - expected_len:+d})"
    )
    assert actual_sha == expected_sha, (
        f"[{name}] sha256 drift: {actual_sha} != {expected_sha}"
    )


def test_corpus_count_sanity() -> None:
    """A floor on the corpus size so a future edit can't silently drop
    fixtures and have the byte-lock effectively disappear."""
    assert len(CORPUS) >= 4, (
        f"corpus drop-detection: only {len(CORPUS)} fixtures "
        f"(expected >=4 to cover the kwarg branches)"
    )


def test_no_bom_in_fragments() -> None:
    """Fragment files must be UTF-8 with no BOM and LF line endings.
    A Windows tool that wrote a BOM or CRLF would shift the output SHA;
    catch it here rather than at the output-pin level (clearer cause)."""
    from pathlib import Path

    from splatpipe.viewers.spark import template as tmpl

    parts_dir = Path(tmpl.__file__).parent / "template_parts"
    for p in sorted(parts_dir.iterdir()):
        if p.suffix not in (".html_tmpl", ".css_tmpl", ".js_tmpl"):
            continue
        raw = p.read_bytes()
        assert not raw.startswith(b"\xef\xbb\xbf"), (
            f"{p.name}: UTF-8 BOM detected -- write with encoding='utf-8' "
            f"(no BOM) via Path.write_text"
        )
        assert not raw.startswith(b"\xff\xfe"), (
            f"{p.name}: UTF-16 LE BOM -- a Windows tool corrupted the file"
        )
        assert b"\r" not in raw, (
            f"{p.name}: CRLF line endings -- write with newline='\\n'"
        )
