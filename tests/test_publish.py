"""Tests for `splatpipe publish` — the permanent-slug deploy.

These lock the hard-won, load-bearing invariants (six live production scenes
depend on them; see project memories `project_bunny_viewer_config_cache` and
`project_bunny_purge_reupload_race`):

  * index.html is BUILD-AGNOSTIC (no b<key> baked in; reads cfg.primary_asset)
  * viewer-config.json carries `primary_asset = "<bkey>/scene.rad"`
  * deploy_to_bunny is called with purge=False
  * the edge-cache rule is asserted every run
  * only index.html + viewer-config.json are cache-purged (never chunks)

`html_for` is deliberately NOT mocked — the real template is what makes the
build-agnostic guarantee true, so the tests exercise it for real.
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from splatpipe.cli.main import app
from splatpipe.core.events import ProgressEvent, StepResult
from splatpipe.steps.publish import STEP_PUBLISH, publish_scene

runner = CliRunner()

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
    """A minimal prebuilt chunked set: one manifest + one .radc."""
    d = tmp_path / "prebuilt"
    d.mkdir()
    (d / "scene-lod.rad").write_bytes(b"RADMANIFEST")
    (d / "scene-lod-0.radc").write_bytes(b"CHUNK0")
    return d


@pytest.fixture
def captured():
    """Holds what the mocked deploy_to_bunny saw (staged files + kwargs)."""
    return {}


def _fake_deploy(captured):
    def _gen(slug, stage, env, *, workers=8, purge=False):
        # snapshot the staged tree + the all-important purge kwarg
        captured["slug"] = slug
        captured["purge"] = purge
        captured["index_html"] = (Path(stage) / "index.html").read_text(encoding="utf-8")
        captured["viewer_config"] = json.loads(
            (Path(stage) / "viewer-config.json").read_text(encoding="utf-8"))
        captured["subdirs"] = sorted(
            p.name for p in Path(stage).iterdir() if p.is_dir())
        yield ProgressEvent(step="export", progress=1.0, message="Uploaded 2/2")
        return StepResult(step="export", success=True,
                          summary={"uploaded": 2, "failed": 0, "failed_files": []})
    return _gen


def test_raddir_publish_invariants(rad_dir, captured):
    """Standalone --rad-dir: index build-agnostic, cfg pointer, purge=False."""
    purged = {}
    with patch("splatpipe.steps.publish.ensure_edge_rules", return_value=True) as edge, \
         patch("splatpipe.steps.publish.deploy_to_bunny", _fake_deploy(captured)), \
         patch("splatpipe.steps.publish.list_bunny_subfolders", return_value=[]), \
         patch("splatpipe.steps.publish.purge_bunny_cache",
               side_effect=lambda api, urls: purged.setdefault("urls", urls) or (len(urls), 0)):
        result = _drain(publish_scene(
            scene_name="Speicher", slug="speicher", env=ENV, rad_dir=rad_dir))

    assert result.success, result.error
    assert result.step == STEP_PUBLISH
    bkey = result.summary["bkey"]
    assert bkey.startswith("b") and len(bkey) == 17

    # INVARIANT: edge rule asserted every run
    edge.assert_called_once()

    # INVARIANT: deploy with purge=False (the async-delete race fix)
    assert captured["purge"] is False
    assert captured["slug"] == "speicher"

    # INVARIANT: index.html is build-agnostic — bkey NOT baked in,
    # reads cfg.primary_asset, fallback constant is the bare name.
    html = captured["index_html"]
    assert bkey not in html
    assert "typeof cfg.primary_asset === 'string'" in html
    assert "const PRIMARY_ASSET = 'scene.rad'" in html
    assert "_sparkfork-rcf2" in html

    # INVARIANT: the real pointer lives in viewer-config.json
    assert captured["viewer_config"]["primary_asset"] == f"{bkey}/scene.rad"

    # INVARIANT: chunks staged under the immutable b<key>/ subfolder
    assert captured["subdirs"] == [bkey]

    # INVARIANT: only the two stable text files are purged (never chunks)
    assert purged["urls"] == [
        "https://splatpipe-cdn.b-cdn.net/speicher/index.html",
        "https://splatpipe-cdn.b-cdn.net/speicher/viewer-config.json",
    ]
    assert result.summary["viewer_url"] == \
        "https://splatpipe-cdn.b-cdn.net/speicher/index.html"


def test_ply_build_path_uses_cache_dir_bkey(tmp_path, captured):
    """--ply: build() is invoked; bkey derives from the cache dir NAME."""
    ply = tmp_path / "src.ply"
    ply.write_bytes(b"PLYDATA")
    cache_dir = tmp_path / "abcdef0123456789-5c63bd5-qcs"
    cache_dir.mkdir()
    manifest = cache_dir / "src-lod.rad"
    manifest.write_bytes(b"M")
    (cache_dir / "src-lod-0.radc").write_bytes(b"C")

    import hashlib
    expect_bkey = "b" + hashlib.sha256(cache_dir.name.encode()).hexdigest()[:16]

    with patch("splatpipe.steps.publish.ensure_edge_rules", return_value=True), \
         patch("splatpipe.steps.publish.build", return_value=manifest) as build_mock, \
         patch("splatpipe.steps.publish.deploy_to_bunny", _fake_deploy(captured)), \
         patch("splatpipe.steps.publish.list_bunny_subfolders", return_value=[]), \
         patch("splatpipe.steps.publish.purge_bunny_cache", return_value=(2, 0)):
        result = _drain(publish_scene(
            scene_name="Src", slug="src", env=ENV, ply=ply,
            crop_within="0,0,0,5000"))

    assert result.success, result.error
    build_mock.assert_called_once()
    # crop_within must reach build() as a --within-dist extra flag
    assert build_mock.call_args.kwargs["extra_flags"] == ["--within-dist=0,0,0,5000"]
    assert result.summary["bkey"] == expect_bkey
    assert captured["viewer_config"]["primary_asset"] == f"{expect_bkey}/scene.rad"
    assert captured["purge"] is False


def test_per_scene_overrides_and_inherit(rad_dir, captured):
    """base_config is inherited and per-scene knobs are injected."""
    with patch("splatpipe.steps.publish.ensure_edge_rules", return_value=True), \
         patch("splatpipe.steps.publish.deploy_to_bunny", _fake_deploy(captured)), \
         patch("splatpipe.steps.publish.list_bunny_subfolders", return_value=[]), \
         patch("splatpipe.steps.publish.purge_bunny_cache", return_value=(2, 0)):
        result = _drain(publish_scene(
            scene_name="P", slug="p", env=ENV, rad_dir=rad_dir,
            base_config={"start_view": {"pos": [1, 2, 3]}, "spark_render": {}},
            clip_xy=3.0, move_speed_mult=0.25, splat_budget=3_000_000))

    assert result.success, result.error
    vc = captured["viewer_config"]
    assert vc["start_view"] == {"pos": [1, 2, 3]}          # inherited
    assert vc["spark_render"]["clip_xy"] == 3.0            # injected
    assert vc["spark_render"]["move_speed_mult"] == 0.25   # injected
    assert vc["splat_budget"] == 3_000_000                 # injected
    assert vc["primary_asset"].endswith("/scene.rad")      # pointer still set


def test_prune_stale_opt_in(rad_dir, captured):
    """--prune-stale deletes only OTHER b*/ subfolders; default keeps them."""
    with patch("splatpipe.steps.publish.ensure_edge_rules", return_value=True), \
         patch("splatpipe.steps.publish.deploy_to_bunny", _fake_deploy(captured)), \
         patch("splatpipe.steps.publish.list_bunny_subfolders",
               return_value=["bOLDKEY000000000", "notabuild"]), \
         patch("splatpipe.steps.publish.purge_bunny_cache", return_value=(2, 0)), \
         patch("splatpipe.steps.publish._purge_bunny_folder", return_value=9) as rm:
        # default: keep
        r1 = _drain(publish_scene(scene_name="P", slug="p", env=ENV, rad_dir=rad_dir))
        rm.assert_not_called()
        assert "bOLDKEY000000000" in r1.summary["kept_subfolders"]
        assert "notabuild" not in r1.summary["kept_subfolders"]  # only b* considered
        # opt-in: prune the stale b*/ (never the current bkey, never non-b)
        _drain(publish_scene(scene_name="P", slug="p", env=ENV,
                             rad_dir=rad_dir, prune_stale=True))
        rm.assert_called_once_with("splatpipe", "pw", "p/bOLDKEY000000000")


def test_validation_failures(rad_dir, tmp_path):
    ply = tmp_path / "x.ply"
    ply.write_bytes(b"P")
    # both sources
    r = _drain(publish_scene(scene_name="X", slug="x", env=ENV,
                             ply=ply, rad_dir=rad_dir))
    assert not r.success and "exactly one" in r.error
    # crop with rad-dir
    r = _drain(publish_scene(scene_name="X", slug="x", env=ENV,
                             rad_dir=rad_dir, crop_within="0,0,0,1"))
    assert not r.success and "crop_within only applies" in r.error
    # missing creds
    r = _drain(publish_scene(scene_name="X", slug="x",
                             env={"BUNNY_CDN_URL": "x"}, rad_dir=rad_dir))
    assert not r.success and "BUNNY_STORAGE" in r.error


def test_cli_arg_validation():
    """CLI rejects bad arg combos before doing any work (no network)."""
    r = runner.invoke(app, ["publish", "--ply", "a.ply", "--rad-dir", "b/"])
    assert r.exit_code == 1 and "exactly one" in r.output
    r = runner.invoke(app, ["publish", "--ply", "a.ply", "--rad-dir", "b/",
                            "--project", "."])
    assert r.exit_code == 1 and "mutually exclusive" in r.output
    r = runner.invoke(app, ["publish", "--rad-dir", "b/", "--crop-within",
                            "0,0,0,1", "--slug", "s"])
    assert r.exit_code == 1 and "crop-within only applies" in r.output


class _Resp:
    def __init__(self, b): self._b = b
    def read(self): return self._b


def _fake_publish(captured):
    def _gen(**kw):
        captured.update(kw)
        yield ProgressEvent(step="publish", progress=1.0, message="done")
        return StepResult(step="publish", success=True, summary={
            "slug": kw["slug"], "viewer_url": "u", "embed_url": "u?embed=1",
            "bkey": "babc", "uploaded": 1, "total_mb": 1.0, "chunks": 1,
            "kept_subfolders": []})
    return _gen


_FAKE_ENV = {"BUNNY_STORAGE_ZONE": "z", "BUNNY_STORAGE_PASSWORD": "p",
             "BUNNY_CDN_URL": "https://cdn"}


def test_cli_redeploy_recovers_name_and_desc(tmp_path):
    """Standalone redeploy with --scene/--desc omitted recovers the live
    display name + description (the title-clobber footgun is gone)."""
    ply = tmp_path / "x.ply"
    ply.write_bytes(b"P")
    live = ('<meta property="og:title" content="My Real Name '
            '— interactive 3D scene">'
            '<meta name="description" content="Real Desc Here">').encode()
    cap = {}
    with patch("splatpipe.cli.publish_cmd.load_bunny_env", return_value=_FAKE_ENV), \
         patch("splatpipe.cli.publish_cmd.urlopen", lambda *a, **k: _Resp(live)), \
         patch("splatpipe.cli.publish_cmd.publish_scene", _fake_publish(cap)):
        r = runner.invoke(app, ["publish", "--ply", str(ply), "--slug", "ibug"])
    assert r.exit_code == 0, r.output
    assert cap["scene_name"] == "My Real Name"   # NOT "ibug"
    assert cap["desc"] == "Real Desc Here"
    assert cap["slug"] == "ibug"


def test_cli_new_slug_falls_back_to_slug_name(tmp_path):
    """A genuinely new slug (live fetch fails) still defaults name=slug."""
    ply = tmp_path / "x.ply"
    ply.write_bytes(b"P")

    def _boom(*a, **k):
        raise OSError("404 not found")

    cap = {}
    with patch("splatpipe.cli.publish_cmd.load_bunny_env", return_value=_FAKE_ENV), \
         patch("splatpipe.cli.publish_cmd.urlopen", _boom), \
         patch("splatpipe.cli.publish_cmd.publish_scene", _fake_publish(cap)):
        r = runner.invoke(app, ["publish", "--ply", str(ply), "--slug", "brandnew"])
    assert r.exit_code == 0, r.output
    assert cap["scene_name"] == "brandnew"   # slug fallback, no crash
    assert cap["desc"] is None               # → publish_scene applies NEUTRAL
