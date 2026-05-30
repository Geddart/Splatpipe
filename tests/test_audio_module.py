"""AudioModule contract tests (Phase 7 -- editor-arc-design #122 §4.4).

The AudioModule is a pure-JS IIFE shipped in
``viewers/spark/template_parts/15f_audio_module.js_tmpl`` and registered
with the Phase 2 ``EditorModuleRegistry``. Its job:

  * Own ``cfg.audio`` (the schema slot; ``[{file, positional, volume,
    loop, pos?}, ...]`` -- already in ``PUBLIC_VIEWER_CONFIG_KEYS``).
  * Build ``HTMLAudioElement`` per track + auto-play (matches the legacy
    08_input behaviour the AudioModule supersedes when registered).
  * Populate the "Audio" section of the Scene Settings drawer (17b)
    with: per-track cards (volume slider, loop toggle, positional
    toggle, delete) + "+ Add track" button (POST ``../upload-audio``,
    bug-audit #7 hardened).
  * Push ONE ``EditHistory`` snapshot per gesture (R8 §4.2 -- never
    per-frame during a slider drag).
  * Register a ``defaultModes`` that includes ALL three modes -- audio
    plays everywhere; the editor UI is gated separately by the drawer's
    HudLayer mode filter in 17b.
  * Contribute a continuous full-width timeline lane (audio is a
    background loop in v1; per-track t_in/t_out is deferred).

Per the user-locked Q3 (2026-05-20): the user provides assets later;
Phase 7 just ships the editor capacity. ``cfg.audio`` defaults to ``[]``
(empty array -- no audio).

Static-only tests: the rendered HTML carries the documented surface
markers and the editor wiring. Mirrors ``test_panorama_module.py`` for
Phase 3 + ``test_annotation_module.py`` for Phase 5 layering.
"""

from __future__ import annotations

from pathlib import Path

from splatpipe.core.config_merge import ALLOWED_PATCH_KEYS, merge_camera_scope
from splatpipe.viewers.spark.template import html_for


def _rendered_html() -> str:
    """Render the Spark viewer with a generic project name. The
    AudioModule fragment is mode-agnostic -- it always registers --
    so the static-marker assertions hold regardless of any kwarg here."""
    return html_for("HarnessScene")


# --------------------------------------------------------------------------
# (a) Fragment file is present + at the documented location
# --------------------------------------------------------------------------


def test_audio_module_fragment_file_exists():
    """The 15f fragment is on disk at the expected location. Lexical
    ordering puts it after 15a-e (other modules) and before 16 (editor
    timeline) so the THREE.Scene + cfg from 06/07 are in scope when its
    IIFE runs."""
    from splatpipe.viewers.spark import template as tmpl

    parts = Path(tmpl.__file__).parent / "template_parts"
    frag = parts / "15f_audio_module.js_tmpl"
    assert frag.exists(), f"missing fragment: {frag}"
    raw = frag.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf"), "BOM corruption"
    # CRLF check: the orchestrator concatenates fragments byte-for-byte
    # and a stray CR in a JS template literal can corrupt the IIFE body.
    assert b"\r" not in raw, "CRLF corruption"
    txt = raw.decode("utf-8")
    assert "AudioModule" in txt
    assert "EditorModuleRegistry.register(audioModule)" in txt


# --------------------------------------------------------------------------
# (b) Module contract: shape + stateKey + mode visibility
# --------------------------------------------------------------------------


# Surface markers that lock the EditorModule contract for the AudioModule
# (per spec §4.4). Each marker pins one promise: presence of the module
# instance, its stateKey, its mode visibility, its lifecycle hooks, and
# its registration with the shared coordinator.
_CONTRACT_MARKERS = (
    # IIFE entry + module-init signal
    "//  AudioModule (Phase 7 -- editor-arc-design #122 §4.4)",
    "(function _audioInit() {",
    "name: 'audio',",
    "stateKey: 'audio',",
    # defaultModes -- audio plays in EVERY mode (author/user/embed); the
    # editor UI is gated separately by the drawer's HudLayer registration.
    "defaultModes: ['author', 'user', 'embed'],",
    # Required lifecycle hooks
    "mount: function (overlay, hud, interaction, modes)",
    "unmount: function ()",
    "getDirtyState: function ()",
    "markClean: function ()",
    "onCfgChange: function (prev, next, stateKey)",
    "renderSceneSettings: function (parentEl)",
    # Registration with the Phase 2 coordinator
    "EditorModuleRegistry.register(audioModule);",
    # Timeline lane (continuous full-width audio blocks in v1)
    "timelineLane: {",
    "label: 'audio',",
    # EditHistory gesture-end snapshot labels (per spec §6.5.1, R8 §4.2)
    "'audio-add'",
    "'audio-delete'",
    "'audio-volume'",
    "'audio-loop'",
    "'audio-positional'",
    # HTMLAudioElement management (the canonical playback primitive)
    "new Audio(",
    "_audioElements",
    # Add-track button (the upload trigger)
    "'+ Add track'",
    # Test surface
    "testSurface:",
)


def test_audio_module_contract_markers_present():
    """The rendered viewer HTML carries every EditorModule-contract marker
    that the spec §4.4 + the Phase 2 registry require."""
    html = _rendered_html()
    for mk in _CONTRACT_MARKERS:
        assert mk in html, f"AudioModule contract marker missing: {mk!r}"


# --------------------------------------------------------------------------
# (b2) UX-H3 fix: upload POSTs to the derived upload-asset.php (NOT the
#      dashboard-only ../upload-audio which 404s on a live CDN scene)
# --------------------------------------------------------------------------

# The audio upload was DEAD on every deployed scene: the "+ Add track"
# picker POSTed to ``../upload-audio`` which only exists on the splatpipe
# web dashboard (FastAPI). On a Bunny CDN scene that 404s silently. The fix
# derives a SIBLING ``upload-asset.php`` from the baked SAVE_ENDPOINT and
# POSTs the file there as multipart with the per-scene Bearer token.
_UX_H3_UPLOAD_MARKERS = (
    "function _assetUploadEndpoint()",
    "'upload-asset.php$1'",
    "SAVE_MODE !== 'http'",
    "function _readAuthToken()",
    "headers['Authorization'] = 'Bearer ' + token;",
    "fd.append('slug', _uploadSlug());",
    "fd.append('file', file);",
    "function _uploadAsset(file)",
    "function _setStatus(msg, isError)",
    "Asset upload requires the http save backend.",
    "audio-upload-status",
)


def test_audio_upload_targets_derived_asset_endpoint_not_dashboard():
    """UX-H3: the audio "+ Add track" upload must POST to the http-mode
    ``upload-asset.php`` derived from SAVE_ENDPOINT (with a Bearer token +
    slug), NOT the dashboard-only ``../upload-audio`` that 404s on a live
    CDN scene. cli-mode surfaces an inline message instead of silently
    failing."""
    html = _rendered_html()
    for mk in _UX_H3_UPLOAD_MARKERS:
        assert mk in html, f"UX-H3 audio upload marker missing: {mk!r}"
    # NEGATIVE: the dead dashboard-only fetch CODE must be GONE from the
    # AudioModule fragment. We pin the actual dead-code forms (a fetch
    # built off the relative ../upload-audio target), NOT any mention --
    # the explanatory comments legitimately name the retired target.
    frag = (
        Path(__file__).parent.parent / "src" / "splatpipe" / "viewers"
        / "spark" / "template_parts" / "15f_audio_module.js_tmpl"
    ).read_text(encoding="utf-8")
    assert "new URL('../upload-audio'" not in frag, (
        "15f must no longer build a fetch URL off the dashboard-only "
        "../upload-audio (UX-H3: dead on every deployed CDN scene)"
    )
    assert "fetch(url, { method: 'POST', body: fd })" not in frag, (
        "15f must no longer POST the bare dashboard FormData (the old "
        "tokenless, relative-target upload path) -- it now goes through "
        "_uploadAsset(file) which derives upload-asset.php + adds the "
        "Bearer token"
    )


def test_audio_upload_error_paths_surface_inline_not_silent():
    """UX-H3: 401 / 413 / unsupported / network failures must surface an
    inline message, not a silent console.warn-only."""
    html = _rendered_html()
    assert "Upload unauthorized (401)." in html
    assert "File too large (413)." in html
    assert "Upload failed (network error). " in html
    assert "_setStatus(msg, true);" in html


def test_audio_module_concatenates_before_18_frame_loop():
    """Fragment-ordering invariant: 15f must concatenate BEFORE
    18_frame_loop (which contains the master render loop). The
    AudioModule registers itself with the registry at fragment load
    time, so its presence must come BEFORE the framework's frame loop
    that drives any per-frame ticks."""
    html = _rendered_html()
    audio_i = html.index("//  AudioModule (Phase 7")
    fl_i = html.index("css2d.render(scene, camera);")
    assert audio_i < fl_i, (
        "15f (AudioModule) must concatenate BEFORE 18_frame_loop so "
        "its registration is complete by the time the render loop "
        "starts"
    )


def test_audio_module_concatenates_after_other_15_modules():
    """The lexical-ordering invariant: 15f loads AFTER 15a-15d so the
    registry-section ordering (CameraPath, Panorama, Annotations, Cuts,
    PostFX, Audio) honours the registration order (per spec §4.9)."""
    html = _rendered_html()
    cam_i = html.index("//  CameraPathModule (Phase 2B")
    pan_i = html.index("//  PanoramaModule (Phase 3")
    ann_i = html.index("//  AnnotationModule (Phase 5")
    cuts_i = html.index("//  CutsModule (Phase 6")
    audio_i = html.index("//  AudioModule (Phase 7")
    # 15f must come after every other 15* module fragment
    assert cam_i < audio_i
    assert pan_i < audio_i
    assert ann_i < audio_i
    assert cuts_i < audio_i


# --------------------------------------------------------------------------
# (c) 08_input guard so legacy audio loader no-ops when module is present
# --------------------------------------------------------------------------


def test_legacy_08_audio_guard_present_and_safe():
    """The minimal guard added to 08_input.js_tmpl wraps the legacy
    audio loader so a future load-order change (15f before 08) cleanly
    no-ops the legacy auto-play without double-instantiating audio
    elements. The guard MUST evaluate against
    window.__sceneview.modules at runtime so it tolerates the case
    where the registry is not yet wired (defensive)."""
    html = _rendered_html()
    # Guard symbol present.
    assert "_audioOwnedByModule" in html, (
        "08_input must declare `_audioOwnedByModule` as the legacy "
        "guard for the AudioModule (mirrors `_annotationsOwnedByModule` "
        "from Phase 5)"
    )
    # The guard is wrapped in `if (!_audioOwnedByModule) { ... }` which
    # is the safe form (legacy runs when module is NOT registered).
    assert "if (!_audioOwnedByModule)" in html
    # The legacy audio loop must still be inside the guarded block --
    # we wrapped the existing unconditional loop rather than removing it.
    g_i = html.index("if (!_audioOwnedByModule)")
    # The block ends at the next top-level section comment.
    g_end = html.index("// ---- Annotations (CSS2DObject)", g_i)
    block = html[g_i:g_end]
    assert "THREE.AudioListener" in block, (
        "the legacy AudioListener construction must stay inside the "
        "guarded block so it runs when the AudioModule is absent"
    )
    assert "audioLoader.load(src.file" in block, (
        "the legacy audioLoader.load must still be inside the guard"
    )


def test_legacy_08_audio_guard_uses_sceneview_modules_lookup():
    """The guard must check window.__sceneview.modules.get('audio') so
    a registered AudioModule is correctly detected (same pattern as
    Phase 5's annotation guard)."""
    html = _rendered_html()
    # Find the guard declaration and verify the lookup signature.
    g_decl_i = html.index("const _audioOwnedByModule = ")
    # The next ~6 lines contain the boolean expression.
    g_decl_block = html[g_decl_i:g_decl_i + 400]
    assert "window.__sceneview" in g_decl_block
    assert "window.__sceneview.modules" in g_decl_block
    assert "modules.get" in g_decl_block
    assert "'audio'" in g_decl_block


# --------------------------------------------------------------------------
# (d) Python-side: `audio` joins the ALLOWED_PATCH_KEYS allow-list
# --------------------------------------------------------------------------


def test_audio_is_in_allowed_patch_keys():
    """``audio`` joins the camera-scope allow-list so the AudioModule
    can save audio edits through the same shared
    ``merge_camera_scope`` core every other camera-scope patch uses
    (mirrors the panorama_backdrop addition in Phase 3)."""
    assert "audio" in ALLOWED_PATCH_KEYS


def test_audio_patch_whole_replaces():
    """An audio in the patch wholesale-replaces the existing array
    (no per-track merge). This matches the contract for every other
    allow-listed key in ``ALLOWED_PATCH_KEYS``."""
    existing = {
        "primary_asset": "bSPEICHER/scene.rad",
        "audio": [
            {"file": "audio/old.mp3", "volume": 0.5, "loop": True},
            {"file": "audio/stale.mp3", "volume": 0.3, "loop": False},
        ],
    }
    patch = {
        "audio": [
            {"file": "audio/new.mp3", "volume": 0.8, "loop": True},
        ],
    }
    out = merge_camera_scope(existing, patch)
    # Whole-replace: the second old track is gone, NOT deep-merged.
    assert out["audio"] == [
        {"file": "audio/new.mp3", "volume": 0.8, "loop": True},
    ]
    assert len(out["audio"]) == 1
    # primary_asset force-kept (the locked Speicher-blank invariant).
    assert out["primary_asset"] == "bSPEICHER/scene.rad"


def test_audio_primary_asset_force_keep_invariant():
    """The Speicher-blank locked invariant holds: a hostile patch that
    also carries a ``primary_asset`` pointer can NEVER win, even when
    the patch's legitimate audio edit is applied."""
    existing = {
        "primary_asset": "bSPEICHER/scene.rad",
        "audio": [],
    }
    patch = {
        "audio": [{"file": "audio/new.mp3", "volume": 1.0, "loop": True}],
        "primary_asset": "EVIL/attacker.rad",  # MUST NEVER apply
    }
    out = merge_camera_scope(existing, patch)
    # Legitimate audio edit applied.
    assert out["audio"] == [
        {"file": "audio/new.mp3", "volume": 1.0, "loop": True},
    ]
    # LOCKED INVARIANT: pointer is always existing's, never patch's.
    assert out["primary_asset"] == "bSPEICHER/scene.rad"


def test_audio_empty_array_patch_clears_existing():
    """A patch with ``audio: []`` clears all existing audio tracks
    (whole-replace semantics). The 'delete all tracks' shape."""
    existing = {
        "primary_asset": "bSPEICHER/scene.rad",
        "audio": [{"file": "audio/old.mp3", "volume": 0.5}],
    }
    patch = {"audio": []}
    out = merge_camera_scope(existing, patch)
    assert out["audio"] == []
    assert out["primary_asset"] == "bSPEICHER/scene.rad"


# --------------------------------------------------------------------------
# (e) Drawer integration -- 17b's audio placeholder must be findable
# --------------------------------------------------------------------------


def test_audio_module_drawer_placeholder_section_present():
    """The 17b Phase-2D scaffold emits an ``audio`` placeholder
    section as the 4th item. The AudioModule's
    ``renderSceneSettings`` hook attaches to it (mirrors the
    PanoramaModule pattern for the ``panorama`` placeholder)."""
    html = _rendered_html()
    # 17b's _SS_PLACEHOLDER_ORDER entry for audio.
    assert "['audio', 'Audio', 'AudioModule (Phase 7)']," in html, (
        "17b must keep the 'audio' placeholder section -- the "
        "AudioModule attaches to it via renderSceneSettings(parentEl)"
    )
