"""Tests for the Spark --rad-chunked pipeline default.

Covers the pure-Python contract that can silently break without the Rust
build-lod binary: the chunked-cache completeness guard and the
chunked/non-chunked cache layout + return value.
"""

from pathlib import Path

import pytest

from splatpipe.viewers.spark import build_lod
from splatpipe.viewers.spark.build_lod import Toolchain, _find_manifest, build


# ---- _find_manifest: the crash-safety / completeness guard ----------------


def test_find_manifest_missing_dir(tmp_path):
    assert _find_manifest(tmp_path / "nope") is None


def test_find_manifest_complete_set(tmp_path):
    d = tmp_path / "cache_key"
    d.mkdir()
    man = d / "scene-lod.rad"
    man.write_bytes(b"RAD0")
    (d / "scene-lod-0.radc").write_bytes(b"RADC")
    (d / "scene-lod-1.radc").write_bytes(b"RADC")
    assert _find_manifest(d) == man


def test_find_manifest_manifest_without_chunks_is_incomplete(tmp_path):
    d = tmp_path / "cache_key"
    d.mkdir()
    (d / "scene-lod.rad").write_bytes(b"RAD0")
    # No .radc — a crashed/partial build must read as a MISS, not a hit.
    assert _find_manifest(d) is None


def test_find_manifest_chunks_without_manifest_is_incomplete(tmp_path):
    d = tmp_path / "cache_key"
    d.mkdir()
    (d / "scene-lod-0.radc").write_bytes(b"RADC")
    assert _find_manifest(d) is None


def test_find_manifest_ambiguous_two_manifests(tmp_path):
    d = tmp_path / "cache_key"
    d.mkdir()
    (d / "a-lod.rad").write_bytes(b"RAD0")
    (d / "b-lod.rad").write_bytes(b"RAD0")
    (d / "a-lod-0.radc").write_bytes(b"RADC")
    assert _find_manifest(d) is None


# ---- build(): chunked vs single-file cache layout -------------------------


@pytest.fixture
def fake_toolchain(monkeypatch):
    monkeypatch.setattr(
        build_lod,
        "detect_toolchain",
        lambda spark_repo=None: Toolchain(
            cmd_prefix=["dummy-build-lod"], cwd=None, version="testrev", is_cargo=False
        ),
    )


@pytest.fixture
def isolated_cache(tmp_path, monkeypatch):
    cache = tmp_path / "radcache"
    monkeypatch.setattr(build_lod, "RAD_CACHE", cache)
    return cache


def _tiny_input(tmp_path) -> Path:
    p = tmp_path / "lod0_reviewed.ply"
    p.write_bytes(b"ply\nformat binary_little_endian 1.0\nend_header\n" + b"\x00" * 64)
    return p


def test_build_chunked_cache_hit_returns_manifest(
    tmp_path, fake_toolchain, isolated_cache, monkeypatch
):
    """A pre-populated chunked cache dir is returned without running build-lod."""
    inp = _tiny_input(tmp_path)
    monkeypatch.setattr(build_lod, "_compute_cache_key", lambda *a, **k: "KEY")

    def _boom(*a, **k):  # build-lod must NOT be invoked on a hit
        raise AssertionError("subprocess ran on a cache hit")

    monkeypatch.setattr(build_lod, "_run_subprocess", _boom)

    cdir = isolated_cache / "KEY"
    cdir.mkdir(parents=True)
    man = cdir / "lod0_reviewed-lod.rad"
    man.write_bytes(b"RAD0")
    (cdir / "lod0_reviewed-lod-0.radc").write_bytes(b"RADC")

    result = build(inp, chunked=True)
    assert result == man


def test_build_chunked_miss_stages_dir_and_returns_manifest(
    tmp_path, fake_toolchain, isolated_cache, monkeypatch
):
    """On a miss, build-lod's manifest + .radc are cached as a dir; manifest returned."""
    inp = _tiny_input(tmp_path)
    monkeypatch.setattr(build_lod, "_compute_cache_key", lambda *a, **k: "KEY")

    def _fake_run(argv, *, cwd, on_progress):
        # build-lod writes <stem>-lod.rad + <stem>-lod-<i>.radc next to input.
        tmp_input = Path(argv[-1])
        stem = tmp_input.stem
        (tmp_input.parent / f"{stem}-lod.rad").write_bytes(b"RAD0")
        (tmp_input.parent / f"{stem}-lod-0.radc").write_bytes(b"RADC0")
        (tmp_input.parent / f"{stem}-lod-1.radc").write_bytes(b"RADC1")
        assert "--rad-chunked" in argv

    monkeypatch.setattr(build_lod, "_run_subprocess", _fake_run)

    result = build(inp, chunked=True)
    cdir = isolated_cache / "KEY"
    assert result == cdir / "lod0_reviewed-lod.rad"
    assert result.is_file()
    assert sorted(p.name for p in cdir.glob("*.radc")) == [
        "lod0_reviewed-lod-0.radc",
        "lod0_reviewed-lod-1.radc",
    ]
    # No leftover staging dir.
    assert not (isolated_cache / "KEY.tmp").exists()


def test_build_non_chunked_still_single_file(
    tmp_path, fake_toolchain, isolated_cache, monkeypatch
):
    """chunked=False keeps the legacy single .rad cache file + return."""
    inp = _tiny_input(tmp_path)
    monkeypatch.setattr(build_lod, "_compute_cache_key", lambda *a, **k: "KEY")

    def _fake_run(argv, *, cwd, on_progress):
        tmp_input = Path(argv[-1])
        (tmp_input.parent / f"{tmp_input.stem}-lod.rad").write_bytes(b"RAD0")
        assert "--rad-chunked" not in argv

    monkeypatch.setattr(build_lod, "_run_subprocess", _fake_run)

    result = build(inp, chunked=False)
    assert result == isolated_cache / "KEY.rad"
    assert result.is_file()
    assert not (isolated_cache / "KEY").exists()


def test_build_chunked_and_non_chunked_keys_do_not_collide(
    tmp_path, fake_toolchain, isolated_cache, monkeypatch
):
    """The 'c' flag marker keeps chunked/non-chunked cache entries distinct."""
    inp = _tiny_input(tmp_path)

    def _fake_run(argv, *, cwd, on_progress):
        tmp_input = Path(argv[-1])
        stem = tmp_input.stem
        (tmp_input.parent / f"{stem}-lod.rad").write_bytes(b"RAD0")
        if "--rad-chunked" in argv:
            (tmp_input.parent / f"{stem}-lod-0.radc").write_bytes(b"RADC")

    monkeypatch.setattr(build_lod, "_run_subprocess", _fake_run)

    chunked_path = build(inp, chunked=True)
    single_path = build(inp, chunked=False)
    assert chunked_path != single_path
    assert chunked_path.suffix == ".rad" and chunked_path.parent.is_dir()
    assert single_path.suffix == ".rad" and single_path.is_file()


# ---- build(): cluster-sh is the large-scene pipeline DEFAULT ---------------


def test_build_cluster_sh_is_default(
    tmp_path, fake_toolchain, isolated_cache, monkeypatch
):
    """build() with all defaults passes --cluster-sh (+ --rad-chunked --quality)."""
    inp = _tiny_input(tmp_path)
    monkeypatch.setattr(build_lod, "_compute_cache_key", lambda *a, **k: "KEY")
    seen = {}

    def _fake_run(argv, *, cwd, on_progress):
        seen["argv"] = list(argv)
        stem = Path(argv[-1]).stem
        (Path(argv[-1]).parent / f"{stem}-lod.rad").write_bytes(b"RAD0")
        (Path(argv[-1]).parent / f"{stem}-lod-0.radc").write_bytes(b"RADC")

    monkeypatch.setattr(build_lod, "_run_subprocess", _fake_run)
    build(inp)  # all defaults
    assert "--cluster-sh" in seen["argv"]
    assert "--rad-chunked" in seen["argv"]
    assert "--quality" in seen["argv"]


def test_build_no_cluster_sh_opts_out_with_distinct_key(
    tmp_path, fake_toolchain, isolated_cache, monkeypatch
):
    """cluster_sh=False omits the flag AND yields a distinct cache key, so a
    prior cluster-sh build is never wrongly served when cluster-sh is off."""
    inp = _tiny_input(tmp_path)
    seen = {"argvs": []}

    def _fake_run(argv, *, cwd, on_progress):
        seen["argvs"].append(list(argv))
        stem = Path(argv[-1]).stem
        (Path(argv[-1]).parent / f"{stem}-lod.rad").write_bytes(b"RAD0")
        if "--rad-chunked" in argv:
            (Path(argv[-1]).parent / f"{stem}-lod-0.radc").write_bytes(b"RADC")

    monkeypatch.setattr(build_lod, "_run_subprocess", _fake_run)
    default_path = build(inp, chunked=True, cluster_sh=True)
    nosh_path = build(inp, chunked=True, cluster_sh=False)
    assert any("--cluster-sh" in a for a in seen["argvs"])
    assert any("--cluster-sh" not in a for a in seen["argvs"])
    # 's' flag marker keeps the two cache entries distinct
    assert default_path != nosh_path
    assert default_path.parent != nosh_path.parent
