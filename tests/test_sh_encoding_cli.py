"""Tests for the ``splatpipe build-lod --sh-encoding`` CLI option.

The flag must be a typed enum (auto/paged/clamped) so a typo at the CLI
boundary fails loudly instead of silently writing a wrong viewer-config.
``auto`` is the documented default.

These tests mock the build-lod toolchain + ``build()`` call so no Rust
binary or real PLY is required.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from splatpipe.cli.main import app
from splatpipe.core.constants import FOLDER_REVIEW
from splatpipe.core.project import Project
from splatpipe.core.sh_encoding import ShEncoding

runner = CliRunner()


@pytest.fixture
def proj_with_lod0(tmp_path: Path) -> Project:
    """Minimal project with a reviewed lod0 PLY on disk so build-lod resolves it."""
    project_root = tmp_path / "proj"
    proj = Project.create(
        root=project_root,
        name="ShEncTest",
        lod_levels=[{"name": "lod0", "max_splats": 100_000}],
    )
    review = proj.get_folder(FOLDER_REVIEW)
    review.mkdir(parents=True, exist_ok=True)
    (review / "lod0_reviewed.ply").write_bytes(
        b"ply\nformat binary_little_endian 1.0\nend_header\n" + b"\x00" * 64
    )
    return proj


def _verify_toolchain_ok(spark_repo=None):
    return {
        "command": ["dummy-build-lod"],
        "cwd": None,
        "version": "testrev",
        "is_cargo": False,
        "platform": "win32",
    }


def test_build_lod_cli_accepts_sh_encoding_auto(proj_with_lod0, tmp_path):
    """--sh-encoding=auto threads ShEncoding.auto to build()."""
    seen = {}

    def _fake_build(input_ply, **kw):
        seen.update(kw)
        return tmp_path / "cache" / "auto" / "scene-lod.rad"

    with patch("splatpipe.cli.build_lod_cmd.verify_toolchain", _verify_toolchain_ok), \
         patch("splatpipe.cli.build_lod_cmd.build", _fake_build):
        result = runner.invoke(app, [
            "build-lod", "-p", str(proj_with_lod0.root),
            "--sh-encoding", "auto",
        ])
    # The cache path doesn't exist for stat() below, but the CLI failure
    # mode is what matters here -- we only assert sh_encoding made it
    # through to the build() kwargs.
    assert "sh_encoding" in seen, f"CLI did not thread sh_encoding (kwargs={list(seen)})"
    assert seen["sh_encoding"] is ShEncoding.auto
    # exit code may be nonzero due to the fake build returning a non-existent
    # path (the post-build glob/stat fails) -- that's fine; the thread-through
    # is what's under test.
    assert "Usage" not in (result.output or "")


def test_build_lod_cli_accepts_sh_encoding_paged(proj_with_lod0, tmp_path):
    """--sh-encoding=paged threads ShEncoding.paged to build()."""
    seen = {}

    def _fake_build(input_ply, **kw):
        seen.update(kw)
        return tmp_path / "cache" / "paged" / "scene-lod.rad"

    with patch("splatpipe.cli.build_lod_cmd.verify_toolchain", _verify_toolchain_ok), \
         patch("splatpipe.cli.build_lod_cmd.build", _fake_build):
        runner.invoke(app, [
            "build-lod", "-p", str(proj_with_lod0.root),
            "--sh-encoding", "paged",
        ])
    assert seen.get("sh_encoding") is ShEncoding.paged


def test_build_lod_cli_accepts_sh_encoding_clamped(proj_with_lod0, tmp_path):
    """--sh-encoding=clamped threads ShEncoding.clamped to build()."""
    seen = {}

    def _fake_build(input_ply, **kw):
        seen.update(kw)
        return tmp_path / "cache" / "clamped" / "scene-lod.rad"

    with patch("splatpipe.cli.build_lod_cmd.verify_toolchain", _verify_toolchain_ok), \
         patch("splatpipe.cli.build_lod_cmd.build", _fake_build):
        runner.invoke(app, [
            "build-lod", "-p", str(proj_with_lod0.root),
            "--sh-encoding", "clamped",
        ])
    assert seen.get("sh_encoding") is ShEncoding.clamped


def test_build_lod_cli_rejects_invalid_sh_encoding(proj_with_lod0):
    """An unknown --sh-encoding value MUST fail loudly (Typer choice gating)."""
    result = runner.invoke(app, [
        "build-lod", "-p", str(proj_with_lod0.root),
        "--sh-encoding", "bogus-mode",
    ])
    assert result.exit_code != 0
    # Typer reports the invalid choice in stderr or output (rich rendering).
    combined = (result.output or "") + (
        result.stderr_bytes.decode("utf-8", "replace") if result.stderr_bytes else ""
    )
    # Typer / Click writes "Invalid value" or "is not one of" -- accept either.
    assert "bogus-mode" in combined or "Invalid" in combined or "not one of" in combined


def test_build_lod_cli_default_is_auto(proj_with_lod0, tmp_path):
    """Omitting --sh-encoding defaults to ShEncoding.auto."""
    seen = {}

    def _fake_build(input_ply, **kw):
        seen.update(kw)
        return tmp_path / "cache" / "default" / "scene-lod.rad"

    with patch("splatpipe.cli.build_lod_cmd.verify_toolchain", _verify_toolchain_ok), \
         patch("splatpipe.cli.build_lod_cmd.build", _fake_build):
        runner.invoke(app, [
            "build-lod", "-p", str(proj_with_lod0.root),
        ])
    assert seen.get("sh_encoding") is ShEncoding.auto


# -- ShEncoding enum basic invariants ----------------------------------------

def test_sh_encoding_enum_values():
    """The enum has exactly three string-valued members."""
    assert {m.value for m in ShEncoding} == {"auto", "paged", "clamped"}


def test_sh_encoding_cache_flag_distinct():
    """Each mode maps to a DISTINCT one-char cache flag."""
    flags = {m.cache_flag for m in ShEncoding}
    assert flags == {"a", "p", "c"}


def test_sh_encoding_resolve_paged_ext_splats():
    """auto returns inherited; paged forces True; clamped forces False."""
    assert ShEncoding.auto.resolve_paged_ext_splats(None) is None
    assert ShEncoding.auto.resolve_paged_ext_splats(True) is True
    assert ShEncoding.auto.resolve_paged_ext_splats(False) is False
    assert ShEncoding.paged.resolve_paged_ext_splats(None) is True
    assert ShEncoding.paged.resolve_paged_ext_splats(False) is True
    assert ShEncoding.clamped.resolve_paged_ext_splats(None) is False
    assert ShEncoding.clamped.resolve_paged_ext_splats(True) is False
