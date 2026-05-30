"""Tests for ``publish_scene(sh_encoding=...)`` plumbing.

The CLI ``--sh-encoding`` choice threads through ``publish_scene`` to
the staged ``viewer-config.json`` as ``spark_render.paged_ext_splats``:

* ``auto`` -- inherit whatever base_config / live_slug already carried
  (key untouched).
* ``paged`` -- force ``paged_ext_splats = True``.
* ``clamped`` -- force ``paged_ext_splats = False``.

The Rust ``build-lod`` invocation is mocked; only the
viewer-config and deploy plumbing are under test.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from splatpipe.core.events import ProgressEvent, StepResult
from splatpipe.core.sh_encoding import ShEncoding
from splatpipe.steps.publish import publish_scene

ENV = {
    "BUNNY_CDN_URL": "https://splatpipe-cdn.b-cdn.net",
    "BUNNY_STORAGE_ZONE": "splatpipe",
    "BUNNY_STORAGE_PASSWORD": "pw",
    "BUNNY_ACCOUNT_API_KEY": "ak",
}


def _drain(gen):
    try:
        while True:
            next(gen)
    except StopIteration as stop:
        return stop.value


@pytest.fixture
def rad_dir(tmp_path: Path) -> Path:
    """A minimal prebuilt chunked set (matches tests/test_publish.py)."""
    d = tmp_path / "prebuilt"
    d.mkdir()
    (d / "scene-lod.rad").write_bytes(b"RADMANIFEST")
    (d / "scene-lod-0.radc").write_bytes(b"CHUNK0")
    return d


@pytest.fixture
def captured():
    return {}


def _fake_deploy(captured):
    def _gen(slug, stage, env, *, workers=8, purge=False):
        captured["slug"] = slug
        captured["purge"] = purge
        captured["index_html"] = (Path(stage) / "index.html").read_text(encoding="utf-8")
        captured["viewer_config"] = json.loads(
            (Path(stage) / "viewer-config.json").read_text(encoding="utf-8"))
        yield ProgressEvent(step="export", progress=1.0, message="OK")
        return StepResult(step="export", success=True,
                          summary={"uploaded": 2, "failed": 0, "failed_files": []})
    return _gen


def test_publish_sh_encoding_paged_sets_paged_ext_splats_true(rad_dir, captured):
    """--sh-encoding=paged -> viewer-config.spark_render.paged_ext_splats=True."""
    with patch("splatpipe.steps.publish.ensure_edge_rules", return_value=True), \
         patch("splatpipe.steps.publish.deploy_to_bunny", _fake_deploy(captured)), \
         patch("splatpipe.steps.publish.list_bunny_subfolders", return_value=[]), \
         patch("splatpipe.steps.publish.purge_bunny_cache", return_value=(2, 0)):
        result = _drain(publish_scene(
            scene_name="P", slug="p", env=ENV, rad_dir=rad_dir,
            sh_encoding=ShEncoding.paged,
        ))
    assert result.success, result.error
    vc = captured["viewer_config"]
    assert vc.get("spark_render", {}).get("paged_ext_splats") is True


def test_publish_sh_encoding_clamped_sets_paged_ext_splats_false(rad_dir, captured):
    """--sh-encoding=clamped -> viewer-config.spark_render.paged_ext_splats=False."""
    with patch("splatpipe.steps.publish.ensure_edge_rules", return_value=True), \
         patch("splatpipe.steps.publish.deploy_to_bunny", _fake_deploy(captured)), \
         patch("splatpipe.steps.publish.list_bunny_subfolders", return_value=[]), \
         patch("splatpipe.steps.publish.purge_bunny_cache", return_value=(2, 0)):
        result = _drain(publish_scene(
            scene_name="P", slug="p", env=ENV, rad_dir=rad_dir,
            sh_encoding=ShEncoding.clamped,
        ))
    assert result.success, result.error
    vc = captured["viewer_config"]
    assert vc.get("spark_render", {}).get("paged_ext_splats") is False


def test_publish_sh_encoding_auto_preserves_inherited_paged_ext_splats(rad_dir, captured):
    """auto inherits the base_config value -- it must NOT be clobbered."""
    base = {"spark_render": {"paged_ext_splats": True, "clip_xy": 1.4}}
    with patch("splatpipe.steps.publish.ensure_edge_rules", return_value=True), \
         patch("splatpipe.steps.publish.deploy_to_bunny", _fake_deploy(captured)), \
         patch("splatpipe.steps.publish.list_bunny_subfolders", return_value=[]), \
         patch("splatpipe.steps.publish.purge_bunny_cache", return_value=(2, 0)):
        result = _drain(publish_scene(
            scene_name="P", slug="p", env=ENV, rad_dir=rad_dir,
            base_config=base, sh_encoding=ShEncoding.auto,
        ))
    assert result.success, result.error
    vc = captured["viewer_config"]
    # auto + inherited True -> stays True (inherited value preserved).
    assert vc.get("spark_render", {}).get("paged_ext_splats") is True
    # Other inherited spark_render keys must also survive.
    assert vc["spark_render"]["clip_xy"] == 1.4


def test_publish_sh_encoding_auto_no_base_config_omits_key(rad_dir, captured):
    """auto + no inherited value -> the key is NOT introduced."""
    with patch("splatpipe.steps.publish.ensure_edge_rules", return_value=True), \
         patch("splatpipe.steps.publish.deploy_to_bunny", _fake_deploy(captured)), \
         patch("splatpipe.steps.publish.list_bunny_subfolders", return_value=[]), \
         patch("splatpipe.steps.publish.purge_bunny_cache", return_value=(2, 0)):
        result = _drain(publish_scene(
            scene_name="P", slug="p", env=ENV, rad_dir=rad_dir,
            sh_encoding=ShEncoding.auto,
        ))
    assert result.success, result.error
    vc = captured["viewer_config"]
    # auto + no inherited -> the flag is not introduced (viewer template
    # default applies).
    spark_render = vc.get("spark_render", {})
    assert "paged_ext_splats" not in spark_render


def test_publish_sh_encoding_paged_overrides_inherited(rad_dir, captured):
    """paged overrides an inherited False value (re-publish to switch ON)."""
    base = {"spark_render": {"paged_ext_splats": False}}
    with patch("splatpipe.steps.publish.ensure_edge_rules", return_value=True), \
         patch("splatpipe.steps.publish.deploy_to_bunny", _fake_deploy(captured)), \
         patch("splatpipe.steps.publish.list_bunny_subfolders", return_value=[]), \
         patch("splatpipe.steps.publish.purge_bunny_cache", return_value=(2, 0)):
        result = _drain(publish_scene(
            scene_name="P", slug="p", env=ENV, rad_dir=rad_dir,
            base_config=base, sh_encoding=ShEncoding.paged,
        ))
    assert result.success, result.error
    vc = captured["viewer_config"]
    assert vc["spark_render"]["paged_ext_splats"] is True


def test_publish_default_sh_encoding_is_auto(rad_dir, captured):
    """Calling publish_scene() with no sh_encoding kwarg -> auto behaviour."""
    with patch("splatpipe.steps.publish.ensure_edge_rules", return_value=True), \
         patch("splatpipe.steps.publish.deploy_to_bunny", _fake_deploy(captured)), \
         patch("splatpipe.steps.publish.list_bunny_subfolders", return_value=[]), \
         patch("splatpipe.steps.publish.purge_bunny_cache", return_value=(2, 0)):
        result = _drain(publish_scene(
            scene_name="P", slug="p", env=ENV, rad_dir=rad_dir,
        ))
    assert result.success, result.error
    vc = captured["viewer_config"]
    spark_render = vc.get("spark_render", {})
    assert "paged_ext_splats" not in spark_render


def test_publish_sh_encoding_paged_threads_through_build(tmp_path, captured):
    """--ply path: publish_scene(sh_encoding=paged) calls build(sh_encoding=paged)."""
    ply = tmp_path / "src.ply"
    ply.write_bytes(b"PLYDATA")
    cache_dir = tmp_path / "abcdef0123456789-5c63bd5-qcsep"
    cache_dir.mkdir()
    manifest = cache_dir / "src-lod.rad"
    manifest.write_bytes(b"M")
    (cache_dir / "src-lod-0.radc").write_bytes(b"C")

    with patch("splatpipe.steps.publish.ensure_edge_rules", return_value=True), \
         patch("splatpipe.steps.publish.build", return_value=manifest) as build_mock, \
         patch("splatpipe.steps.publish.deploy_to_bunny", _fake_deploy(captured)), \
         patch("splatpipe.steps.publish.list_bunny_subfolders", return_value=[]), \
         patch("splatpipe.steps.publish.purge_bunny_cache", return_value=(2, 0)):
        result = _drain(publish_scene(
            scene_name="P", slug="p", env=ENV, ply=ply,
            sh_encoding=ShEncoding.paged,
        ))

    assert result.success, result.error
    build_mock.assert_called_once()
    # sh_encoding must reach build() so the cache key namespaces properly.
    assert build_mock.call_args.kwargs.get("sh_encoding") is ShEncoding.paged
