"""Per-fragment output pins for the Spark viewer template.

Replaces the whole-assembled-HTML byte-lock (the retired
``test_html_for_output_pin.py``) with ONE pin per ``template_parts/*``
fragment. WHY (2026-05-28): the whole-HTML pin hashed the entire assembled
``html_for(...)`` output, so editing ANY single fragment forced a re-baseline
of the one shared hash — which made two agents editing *different* fragments
collide (each re-baseline reflected the other's uncommitted delta → red on a
clean checkout; cost real time in the 2026-05-21 11D/11E race). Per-fragment
pins are DISJOINT: editing fragment X re-baselines only X's line, so parallel
fragment work no longer contends on this test.

NO COVERAGE IS LOST. ``template.py::_substitute`` replaces each ``@@NAME@@``
independently and no placeholder straddles a fragment boundary, so
``_substitute(concat(fragments), fields) == "".join(_substitute(frag_i, fields))``
— the whole-HTML output decomposes exactly into per-fragment contributions.
That invariant is asserted in ``test_assembly_integrity.py``, which also pins
the join itself (fragment order, placeholder resolution, substitution-value
constants, structural sentinels) — the parts a per-fragment RAW pin can't see.

PIN CONVENTION (matches the retired whole-HTML pin): ``length`` is
``len(text)`` CODE POINTS (Unicode scalar count, NOT UTF-8 bytes — the
fragments carry multi-byte chars like the em-dash / degree sign); ``sha`` is
the SHA-256 of the UTF-8 encoding.

RE-BASELINING ONE FRAGMENT: after a deliberate edit to fragment X, run
``python tests/test_fragment_pins.py`` to print the current manifest and
copy ONLY X's line into ``FRAGMENT_PINS`` below. (Do NOT touch other lines —
that's the whole point.) Then add a CHANGELOG entry describing the edit.
A new/removed/renamed fragment is caught by ``test_fragment_manifest_complete``
(here) + ``test_fragment_order`` (assembly test); update both.
"""

from __future__ import annotations

import hashlib

import pytest

from splatpipe.viewers.spark import template as _tmpl

_PARTS_DIR = _tmpl._PARTS_DIR
_FRAGMENT_SUFFIXES = (".html_tmpl", ".css_tmpl", ".js_tmpl")


def _fragment_files() -> list:
    return [
        p
        for p in sorted(_PARTS_DIR.iterdir())
        if p.suffix in _FRAGMENT_SUFFIXES
    ]


# (code_point_len, sha256_hex_of_utf8). One line per fragment — a deliberate
# edit re-baselines ONLY that fragment's line. Regen with
# ``python tests/test_fragment_pins.py``.
FRAGMENT_PINS: dict[str, tuple[int, str]] = {
    "01_head.html_tmpl": (763, "91b52c9ba0c20e585c703c6fbabffda29e47fce8027064f4018f0e57e2122afc"),
    "02a_styles_main.css_tmpl": (12673, "c833cef926db7d04776c949eed7b90825b6d7cdaee1906f4c6187b080feba025"),
    "02b_styles_editor.css_tmpl": (4225, "6504d4c94352eb3ec4222b1d5ca24dd0572af529128eb76578e7ddb84038a1ed"),
    "03_body_chrome.html_tmpl": (10690, "dfda8ed0a4c9bd5ef9929a79b3ac544016517884cf220e38aa82107e5f517c27"),
    "04_js_prologue.js_tmpl": (6366, "a74c60af5865558923f3e375d62dc5f3f393761feb18eaf63141a6a7fe66344b"),
    "04a_editor_module_registry.js_tmpl": (12221, "b89d8665f095afeabbb1fb5a0e9eb142c08ec1b7993b1937f35c5795029bfd1f"),
    "04b_context_menu.js_tmpl": (15299, "7288602790ba60c980f71bfa376f47bd03695c4cfd62fd7fd0d578df67926679"),
    "05_framework.js_tmpl": (12787, "8ed640ea5e121903cef2987f2a68f4d55f6a81b43b5acdbeb8c8231c048eb3bb"),
    "06_cfg.js_tmpl": (3402, "ef3f093aa3459ef63564d512e97466e1e2310a70990c6dd5992dd5921646b903"),
    "07_setup_three_spark.js_tmpl": (16787, "5d021a86ad8eef95bf60dccb88ef9a8298eb5ae9b2169c1823ad0622d9246847"),
    "08_input.js_tmpl": (36759, "5a07ca84e4cc7a84fe4f0cca3ccb6dc39858360fc072d9f73c6e8e6ace98c2ca"),
    "09_playback_spline.js_tmpl": (22904, "4e0a311ea3a417119a1f6dca355564f6b2391e5e223bf0bb944d7a94e2add5f3"),
    "10_camera_select.js_tmpl": (56229, "f6c394368ccb912903668f5a05e4f3653af6994527e1fddb5d2a8735d5b664f5"),
    "11_clip_player.js_tmpl": (20853, "c02d40492c70f517d0a4f332f9a3ec4ba379b0ebf4c9a2b298c5821cdd49d60d"),
    "12_user_transport.js_tmpl": (18620, "a29fd6dee4a7faabbd614b5dfad468bdd8abc73c4dbaa7afb9501566b9c3ddec"),
    "13_bench.js_tmpl": (27625, "4beea02b6c7851b473ff260bae84eab13ffc8616a21a8346e4262e471a6dcc1c"),
    "14_splat_budget.js_tmpl": (4417, "aa9fa72e755fb1874e6438f7de954e1b75643fbcf3c34f62f48fa59c0b615782"),
    "15_editor_trajectory.js_tmpl": (49897, "015a46c277f06d6e588839ddb9843aa2c84acb4d12c129819c9491efdfa052c1"),
    "15a_camera_path_module.js_tmpl": (7358, "37dba5d9bde2d4186845ddb30481f7f35829426444d7de2b9c35de086367f628"),
    "15b_panorama_module.js_tmpl": (33409, "0eed9320cfda9e9e7c63354d6aa0a1152b214bc2e13c316be997d0858f2e4749"),
    "15c_annotation_module.js_tmpl": (47435, "c1de5a6abf95662d28e6d10292fbe5f05f809ecc5e3990b169fa82175c3686dd"),
    "15d_cuts_module.js_tmpl": (35782, "7b4254c6998b39e56b310abc25cf01fb221f9770c6dea3f17a8a663eb32dc6f4"),
    "15e_postfx_module.js_tmpl": (19748, "55796c168431be26434aafb2c7b035c25de692b2cd085f0907ac37010b42154f"),
    "15f_audio_module.js_tmpl": (34017, "541504f4e5850dcd3f6bdfa9f435d14e596f136c6035808eb3a67d1eb5cf2ba2"),
    "15g_titles_module.js_tmpl": (46650, "fe503715dbea122f62cc6f68a51224ce8a0cd68bd7eced763bcf49f9d66bbc96"),
    "15h_intro_module.js_tmpl": (10071, "4129b70a1933aacb842eadf5e05b60e00874c5f2427b64e7e329c94665dbee0d"),
    "15i_startview_module.js_tmpl": (9543, "43c4793643223e1b63d85ec5919025349e457eb3039d0ad624101e1276973bbc"),
    "16_editor_timeline.js_tmpl": (130279, "24f587e4e31babb785499066331eeed16b3e8b7c0efec9aa907eca575eff9ac7"),
    "17_editor_gizmo.js_tmpl": (137209, "481f115c7887be8ceea7aa6f2c9712642270b8ac399ca3d97497b0996023cd26"),
    "17a_edit_history.js_tmpl": (17737, "b7ee3feae79a210adb93a30d47375610cf08e4fc926945715d7c22b30537bdc5"),
    "17b_scene_settings_drawer.js_tmpl": (18654, "32b8933992f6c65452b1b6e9adbf450d05ac18dadde81a7efb5e88c358d95006"),
    "18_frame_loop.js_tmpl": (52260, "7415ebdf822288577602555b6602a25af0af22d0370fb24e41fdd90d7ad0fae5"),
    "19_intro_controller.js_tmpl": (5831, "57cf8b23899cb199c100d081726fd9c44e4226b7e6394cd229247b24cf061f74"),
    "99_closing.html_tmpl": (172, "28daaba7acd71828f3292475355046bbaec5c5f6c6f54619cadcb594f57b1b59"),
}


@pytest.mark.parametrize(
    "filename,expected",
    sorted(FRAGMENT_PINS.items()),
    ids=sorted(FRAGMENT_PINS),
)
def test_fragment_pin(filename: str, expected: tuple[int, str]) -> None:
    """Each fragment's raw content matches its pinned (code-point-len, sha256).

    A drift names the EXACT fragment (the whole point vs the retired
    whole-HTML pin, which only said "something in ~800KB changed"). If the
    edit was deliberate, re-baseline ONLY this fragment's line in
    ``FRAGMENT_PINS`` (regen: ``python tests/test_fragment_pins.py``).
    """
    exp_len, exp_sha = expected
    raw = (_PARTS_DIR / filename).read_text(encoding="utf-8")
    actual_len = len(raw)
    actual_sha = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    assert actual_len == exp_len, (
        f"[{filename}] code-point length drift: {actual_len} != {exp_len} "
        f"(delta {actual_len - exp_len:+d}) — re-baseline ONLY this line if deliberate"
    )
    assert actual_sha == exp_sha, (
        f"[{filename}] sha256 drift: {actual_sha} != {exp_sha} — "
        f"re-baseline ONLY this line if deliberate"
    )


def test_fragment_manifest_complete() -> None:
    """The set of fragment files on disk == the pinned manifest keys.

    Catches an UNPINNED new fragment (someone added a ``template_parts/*``
    file without a pin) OR a deleted/renamed fragment (a stale pin).
    """
    on_disk = {p.name for p in _fragment_files()}
    pinned = set(FRAGMENT_PINS)
    missing = on_disk - pinned
    stale = pinned - on_disk
    assert not missing, f"fragments on disk with NO pin: {sorted(missing)}"
    assert not stale, f"pins for fragments NOT on disk: {sorted(stale)}"


def test_no_bom_or_crlf_in_fragments() -> None:
    """Fragments must be UTF-8 (no BOM) with LF line endings.

    A Windows tool that wrote a BOM or CRLF would shift the pin sha + break
    the byte-identical assembly across platforms; catch it here with a clear
    cause rather than as an opaque pin drift. (.gitattributes forces eol=lf
    for ``*_tmpl``; this is the test-side belt.)
    """
    for p in _fragment_files():
        raw = p.read_bytes()
        assert not raw.startswith(b"\xef\xbb\xbf"), f"{p.name}: UTF-8 BOM"
        assert not raw.startswith(b"\xff\xfe"), f"{p.name}: UTF-16 LE BOM"
        assert b"\r" not in raw, f"{p.name}: CRLF/CR — write with newline='\\n'"


if __name__ == "__main__":
    # Regen helper: prints the current manifest so re-baselining one fragment
    # is a copy-paste of one line.  `python tests/test_fragment_pins.py`
    print("FRAGMENT_PINS: dict[str, tuple[int, str]] = {")
    for p in _fragment_files():
        raw = p.read_text(encoding="utf-8")
        sha = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        print(f'    "{p.name}": ({len(raw)}, "{sha}"),')
    print("}")
