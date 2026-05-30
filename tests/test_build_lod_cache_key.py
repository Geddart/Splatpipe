"""Tests for the build-lod cache key encoding of ``sh_encoding``.

Different ``sh_encoding`` values MUST produce DISTINCT cache entries so a
re-run with a different mode never silently serves a stale entry. The
choice is also passed through to the cargo invocation as a no-op flag
(the Rust binary doesn't care — both decode paths share the same
``.rad`` bytes), so the encoding is a viewer-side toggle.

These tests use ``isolated_cache`` + ``fake_toolchain`` from
``test_spark_chunked.py``'s pattern (re-implemented locally to keep
imports clean).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from splatpipe.core.sh_encoding import ShEncoding
from splatpipe.viewers.spark import build_lod
from splatpipe.viewers.spark.build_lod import Toolchain, build


@pytest.fixture
def fake_toolchain(monkeypatch):
    monkeypatch.setattr(
        build_lod,
        "detect_toolchain",
        lambda spark_repo=None: Toolchain(
            cmd_prefix=["dummy-build-lod"], cwd=None,
            version="testrev", is_cargo=False,
        ),
    )


@pytest.fixture
def isolated_cache(tmp_path, monkeypatch):
    cache = tmp_path / "radcache"
    monkeypatch.setattr(build_lod, "RAD_CACHE", cache)
    return cache


def _tiny_input(tmp_path) -> Path:
    p = tmp_path / "lod0_reviewed.ply"
    p.write_bytes(
        b"ply\nformat binary_little_endian 1.0\nend_header\n" + b"\x00" * 64
    )
    return p


def _fake_run_factory(stems_seen):
    def _fake_run(argv, *, cwd, on_progress):
        tmp_input = Path(argv[-1])
        stem = tmp_input.stem
        stems_seen.append(list(argv))
        (tmp_input.parent / f"{stem}-lod.rad").write_bytes(b"RAD0")
        if "--rad-chunked" in argv:
            (tmp_input.parent / f"{stem}-lod-0.radc").write_bytes(b"RADC0")
    return _fake_run


def test_cache_key_changes_with_sh_encoding(
    tmp_path, fake_toolchain, isolated_cache, monkeypatch
):
    """Paged vs clamped produce DIFFERENT cache entries on the same PLY."""
    inp = _tiny_input(tmp_path)
    seen = []
    monkeypatch.setattr(build_lod, "_run_subprocess", _fake_run_factory(seen))

    paged_path = build(inp, sh_encoding=ShEncoding.paged)
    clamped_path = build(inp, sh_encoding=ShEncoding.clamped)

    assert paged_path != clamped_path, (
        "sh_encoding mode must NAMESPACE the cache key: a re-run with a "
        "different mode must not silently serve the prior entry"
    )
    assert paged_path.parent != clamped_path.parent


def test_cache_key_auto_distinct_from_paged_and_clamped(
    tmp_path, fake_toolchain, isolated_cache, monkeypatch
):
    """All THREE modes produce distinct cache entries on the same PLY."""
    inp = _tiny_input(tmp_path)
    seen = []
    monkeypatch.setattr(build_lod, "_run_subprocess", _fake_run_factory(seen))

    auto_path = build(inp, sh_encoding=ShEncoding.auto)
    paged_path = build(inp, sh_encoding=ShEncoding.paged)
    clamped_path = build(inp, sh_encoding=ShEncoding.clamped)

    assert len({auto_path, paged_path, clamped_path}) == 3


def test_cache_key_auto_resolves_consistently(
    tmp_path, fake_toolchain, isolated_cache, monkeypatch
):
    """Calling build(sh_encoding=auto) twice returns the SAME cache entry."""
    inp = _tiny_input(tmp_path)
    seen = []
    monkeypatch.setattr(build_lod, "_run_subprocess", _fake_run_factory(seen))

    p1 = build(inp, sh_encoding=ShEncoding.auto)
    p2 = build(inp, sh_encoding=ShEncoding.auto)
    assert p1 == p2
    # Second call should be a cache HIT (subprocess ran exactly once).
    assert len(seen) == 1


def test_cache_key_default_is_auto(
    tmp_path, fake_toolchain, isolated_cache, monkeypatch
):
    """build() with no sh_encoding kwarg uses auto (the documented default)."""
    inp = _tiny_input(tmp_path)
    seen = []
    monkeypatch.setattr(build_lod, "_run_subprocess", _fake_run_factory(seen))

    default_path = build(inp)
    auto_path = build(inp, sh_encoding=ShEncoding.auto)
    assert default_path == auto_path


def test_cache_key_includes_recognisable_encoding_marker(
    tmp_path, fake_toolchain, isolated_cache, monkeypatch
):
    """The cache directory name contains the encoding-mode marker char.

    The naming is documented in CLAUDE.md (flag string convention); this
    test pins it as a contract so cross-mode cache directories are easy
    to identify on disk (and so the marker char isn't silently dropped).
    """
    inp = _tiny_input(tmp_path)
    seen = []
    monkeypatch.setattr(build_lod, "_run_subprocess", _fake_run_factory(seen))

    paged_path = build(inp, sh_encoding=ShEncoding.paged, chunked=True)
    clamped_path = build(inp, sh_encoding=ShEncoding.clamped, chunked=True)

    # The encoding marker is encoded via a leading 'e' (so it never
    # collides with the existing chunked 'c' / cluster-sh 's' flags).
    # e.g. "<sha>-<rev>-qcsep" for paged, "qcsec" for clamped.
    assert "ep" in paged_path.parent.name, (
        f"paged cache dir name {paged_path.parent.name!r} lacks 'ep' marker"
    )
    assert "ec" in clamped_path.parent.name, (
        f"clamped cache dir name {clamped_path.parent.name!r} lacks 'ec' marker"
    )
