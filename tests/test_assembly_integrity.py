"""Assembly / join integrity for the Spark viewer template.

Companion to ``test_fragment_pins.py``. The per-fragment pins lock each
fragment's RAW bytes; this module locks the JOIN — the parts a per-fragment
raw pin cannot see:

  * the decomposition invariant that makes per-fragment pinning SOUND,
  * every ``@@NAME@@`` resolving in the assembled output,
  * the fragment concatenation ORDER (rename / reorder / add / remove),
  * the Python-side substitution VALUES (version/url constants),
  * coarse structural sentinels (still a valid viewer shell).

Together, ``test_fragment_pins`` + this module are a strict superset of the
guarantee the retired whole-HTML ``test_html_for_output_pin.py`` gave —
without the single-writer collision that pin caused (see test_fragment_pins
docstring). Replaced the whole-HTML pin on 2026-05-28.
"""

from __future__ import annotations

import pytest

from splatpipe.viewers.spark import template as _tmpl

_PARTS_DIR = _tmpl._PARTS_DIR
_FRAGMENT_SUFFIXES = (".html_tmpl", ".css_tmpl", ".js_tmpl")


# (name, args, kwargs) — every kwargs branch of html_for(). Mirrors the
# corpus the retired whole-HTML pin used; here it only needs to exercise
# the substitution branches (no pins — those moved to test_fragment_pins).
CORPUS: list[tuple[str, tuple, dict]] = [
    ("harness_defaults", ("HarnessScene",), {}),
    ("http_basic", ("S",), {"save_mode": "http", "save_endpoint": "https://x.example/api/save"}),
    ("http_endpoint_quotes", ("S",), {"save_endpoint": 'https://x/"+evil()+"'}),
    ("none_endpoint", ("S",), {"save_mode": "http", "save_endpoint": None}),
    ("sog_fallback", ("LegacySogScene",), {"primary_asset": "scene.sog", "paged": False}),
    (
        "share_card",
        ("ShareScene",),
        {
            "share_url": "https://splatpipe-cdn.b-cdn.net/share/index.html",
            "share_image": "https://splatpipe-cdn.b-cdn.net/share/preview.jpg",
            "description": "Custom share description text.",
        },
    ),
]


# Exact sorted concatenation order. A rename / reorder / add / remove of a
# fragment trips this (complements test_fragment_pins' manifest-complete).
FRAGMENT_ORDER: tuple[str, ...] = (
    "01_head.html_tmpl",
    "02a_styles_main.css_tmpl",
    "02b_styles_editor.css_tmpl",
    "03_body_chrome.html_tmpl",
    "04_js_prologue.js_tmpl",
    "04a_editor_module_registry.js_tmpl",
    "04b_context_menu.js_tmpl",
    "05_framework.js_tmpl",
    "06_cfg.js_tmpl",
    "07_setup_three_spark.js_tmpl",
    "08_input.js_tmpl",
    "09_playback_spline.js_tmpl",
    "10_camera_select.js_tmpl",
    "11_clip_player.js_tmpl",
    "12_user_transport.js_tmpl",
    "13_bench.js_tmpl",
    "14_splat_budget.js_tmpl",
    "15_editor_trajectory.js_tmpl",
    "15a_camera_path_module.js_tmpl",
    "15b_panorama_module.js_tmpl",
    "15c_annotation_module.js_tmpl",
    "15d_cuts_module.js_tmpl",
    "15e_postfx_module.js_tmpl",
    "15f_audio_module.js_tmpl",
    "15g_titles_module.js_tmpl",
    "15h_intro_module.js_tmpl",
    "15i_startview_module.js_tmpl",
    "16_editor_timeline.js_tmpl",
    "16_editor_timeline_b_dom.js_tmpl",
    "16_editor_timeline_c_draw.js_tmpl",
    "16_editor_timeline_d_playhead_edit.js_tmpl",
    "16_editor_timeline_e_input.js_tmpl",
    "16_editor_timeline_z_tail.js_tmpl",
    "17_editor_gizmo.js_tmpl",
    "17a_edit_history.js_tmpl",
    "17b_scene_settings_drawer.js_tmpl",
    "18_frame_loop.js_tmpl",
    "19_intro_controller.js_tmpl",
    "99_closing.html_tmpl",
)


def _fragment_files() -> list:
    return [
        p
        for p in sorted(_PARTS_DIR.iterdir())
        if p.suffix in _FRAGMENT_SUFFIXES
    ]


@pytest.mark.parametrize("name,args,kwargs", CORPUS, ids=[c[0] for c in CORPUS])
def test_decomposition_invariant(name: str, args: tuple, kwargs: dict) -> None:
    """``_substitute(concat(fragments), fields)`` ==
    ``"".join(_substitute(frag_i, fields))``.

    This is what makes PER-FRAGMENT pinning lossless: the whole assembled
    output is exactly the concatenation of each fragment's independently
    substituted contribution (no ``@@NAME@@`` straddles a boundary, and
    ``_substitute`` does not re-scan its own output). If this ever fails,
    per-fragment pins would no longer fully cover the assembled HTML — STOP
    and re-evaluate before trusting the pins.
    """
    fields = _tmpl._fields_for(*args, **kwargs)
    whole = _tmpl._substitute(_tmpl._load_template_body(), fields)
    per_fragment = "".join(
        _tmpl._substitute(p.read_text(encoding="utf-8"), fields)
        for p in _fragment_files()
    )
    assert per_fragment == whole, (
        f"[{name}] decomposition broke: a placeholder may straddle a fragment "
        f"boundary, or substitution became order-dependent — per-fragment pins "
        f"would no longer cover the assembled output."
    )
    # And html_for() is exactly that whole (the _fields_for split is byte-inert).
    assert _tmpl.html_for(*args, **kwargs) == whole


@pytest.mark.parametrize("name,args,kwargs", CORPUS, ids=[c[0] for c in CORPUS])
def test_all_placeholders_resolve(name: str, args: tuple, kwargs: dict) -> None:
    """No ``@@NAME@@`` remains in the assembled output for any fixture.

    ``_substitute`` already raises on a leftover at runtime; pin it as a test
    so a fragment that introduces an unregistered placeholder fails loudly in
    CI, not on a live deploy.
    """
    html = _tmpl.html_for(*args, **kwargs)
    leftover = _tmpl._PLACEHOLDER.search(html)
    assert leftover is None, (
        f"[{name}] unresolved placeholder {leftover.group(0)!r} at "
        f"offset {leftover.start()}"
    )


def test_fragment_order() -> None:
    """The assembler concatenates fragments in this exact sorted order.

    Complements test_fragment_pins' manifest-complete: that catches an
    unpinned/stale fragment; this catches a rename/reorder that changes the
    assembled sequence even when every individual fragment still pins.
    """
    actual = tuple(p.name for p in _fragment_files())
    assert actual == FRAGMENT_ORDER, (
        f"fragment order changed:\n  expected {FRAGMENT_ORDER}\n  actual   {actual}"
    )


def test_substitution_constants() -> None:
    """The assembled output carries the Python-side substitution VALUES.

    A per-fragment RAW pin can't see a drift in ``html_for``'s field values
    (the fragments hold ``@@SPARK_VERSION@@`` etc., not the resolved string).
    Assert against ``template.*`` so an intentional bump updates in one place.
    """
    html = _tmpl.html_for("Probe")
    # Pin the EXACT literal values (not just "current constant in html", which
    # would be tautological). The retired whole-HTML pin locked these as a
    # side effect of hashing the output; pinning them here keeps that strength
    # — a deliberate version/fork/font bump must update this one assertion (the
    # same lockstep the old pin imposed, just localized + named). SPARK_VERSION
    # is an inert field (no fragment references @@SPARK_VERSION@@; the viewer
    # pins the FORK url, not upstream) so it's value-pinned but not html-checked.
    assert _tmpl.SPARK_VERSION == "2.0.0"
    assert _tmpl.THREE_VERSION == "0.180.0"
    assert _tmpl.SPARK_FORK_URL == (
        "https://splatpipe-cdn.b-cdn.net/_sparkfork-rcf2/spark.module.min.js"
    )
    assert _tmpl.FONT_URL == (
        "https://cdn.jsdelivr.net/npm/three@0.180.0"
        "/examples/fonts/helvetiker_bold.typeface.json"
    )
    # ...and that each substituted value actually lands in the assembled output
    # (catches a fragment that drops its @@...@@ reference).
    assert _tmpl.THREE_VERSION in html
    assert _tmpl.SPARK_FORK_URL in html
    assert _tmpl.FONT_URL in html
    # The @@..._JSON@@ slots resolve to JSON literals, not bare values.
    assert '"cli"' in html  # default SAVE_MODE_JSON
    assert "true" in html  # default PAGED_JSON


def test_structural_sentinels() -> None:
    """Coarse 'still a valid viewer shell' markers in the assembled output."""
    html = _tmpl.html_for("Probe").lower()
    assert "<!doctype html" in html
    assert "<html" in html and "</html>" in html
    assert "<script" in html and "</script>" in html
    # Load-bearing editor + viewer surfaces present.
    for marker in ("editormoduleregistry", "save_mode", "splatmesh"):
        assert marker in html, f"missing structural sentinel: {marker!r}"
