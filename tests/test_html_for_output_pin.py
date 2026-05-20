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
"""

from __future__ import annotations

import hashlib

import pytest

from splatpipe.viewers.spark.template import html_for


# CORPUS: list of (name, args, kwargs, expected_len, expected_sha256).
# Pins captured 2026-05-20 at HEAD f46fa67 (before T1 of #118), then
# re-pinned 2026-05-20 (UX-5 fix; +4383 bytes in lockstep), then
# re-pinned 2026-05-20 again (Phase 1 Q5: #author= -> #token= rename +
# Save body shape correction; all 6 fixtures +1408 bytes in lockstep).
CORPUS: list[tuple[str, tuple, dict, int, str]] = [
    (
        "harness_defaults",
        ("HarnessScene",),
        {},
        473262,
        "dfc2b1565e6f0513b41d18fbc5ddc4f030c07241b808f58ff3a64a5c9c7909a2",
    ),
    (
        "http_basic",
        ("S",),
        {"save_mode": "http", "save_endpoint": "https://x.example/api/save"},
        473234,
        "cd2a64148dad7af992d0aef1c866f9febb0da971618a2811faafa3b144111511",
    ),
    (
        "http_endpoint_quotes",
        ("S",),
        {"save_endpoint": 'https://x/"+evil()+"'},
        473229,
        "854efcc59fbd803b338a109957fbb80384ca0264e02caa7b7c51c1e9b2808f60",
    ),
    (
        "none_endpoint",
        ("S",),
        {"save_mode": "http", "save_endpoint": None},
        473208,
        "3d9a0046e88bd828a37944d64d83f57fa42876d51325753654479a7400821c6d",
    ),
    (
        "sog_fallback",
        ("LegacySogScene",),
        {"primary_asset": "scene.sog", "paged": False},
        473273,
        "80986510c8ec46d9f363920a6998b6d24b191a2257652ee3339beaa964724ca1",
    ),
    (
        "share_card",
        ("ShareScene",),
        {
            "share_url": "https://splatpipe-cdn.b-cdn.net/share/index.html",
            "share_image": "https://splatpipe-cdn.b-cdn.net/share/preview.jpg",
            "description": "Custom share description text.",
        },
        473132,
        "31478dd551a4c6f324b8ade963097d6443f33d9f42d6dfec7fe7e5313419b06f",
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
