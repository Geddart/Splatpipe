"""Tests for the pluggable DeployTarget abstraction (bunny default + folder).

These lock two things:

  * The registry mirrors the trainer registry exactly (name-string selector,
    ``list_deploy_targets()``, ``KeyError`` with the available list, default
    is ``bunny``).
  * ``BunnyDeployTarget`` is a FAITHFUL DELEGATION to the battle-tested
    ``steps/deploy.py`` functions — it MUST call them with byte-identical
    arguments to the old direct call (``purge=False`` preserved, the edge
    rule asserted, only the two stable text files invalidated). This is the
    behaviour-preservation proof for the invariant-locked Bunny path.
  * ``FolderDeployTarget`` copies a staged dir tree to a local destination,
    idempotently / overwrite-safe; "invalidate" + "ensure_fresh" are no-ops.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from splatpipe.core.constants import STEP_PUBLISH
from splatpipe.core.events import ProgressEvent, StepResult
from splatpipe.deploy_targets.base import DeployTarget
from splatpipe.deploy_targets.bunny import BunnyDeployTarget
from splatpipe.deploy_targets.folder import FolderDeployTarget
from splatpipe.deploy_targets.registry import (
    get_deploy_target,
    list_deploy_targets,
)

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


# ---------------------------------------------------------------------------
# Registry (mirrors tests/test_trainers.py::TestRegistry)
# ---------------------------------------------------------------------------
class TestRegistry:
    def test_list_deploy_targets(self):
        targets = list_deploy_targets()
        assert "bunny" in targets
        assert "folder" in targets

    def test_get_bunny(self):
        t = get_deploy_target("bunny", env=ENV)
        assert isinstance(t, BunnyDeployTarget)
        assert t.name == "bunny"

    def test_get_folder(self, tmp_path):
        t = get_deploy_target("folder", destination=tmp_path)
        assert isinstance(t, FolderDeployTarget)
        assert t.name == "folder"

    def test_default_is_bunny(self):
        """No name given → the bunny adapter (the documented default)."""
        t = get_deploy_target(env=ENV)
        assert isinstance(t, BunnyDeployTarget)
        assert t.name == "bunny"

    def test_unknown_target(self):
        with pytest.raises(KeyError, match="Unknown deploy target"):
            get_deploy_target("nonexistent")

    def test_unknown_target_lists_available(self):
        with pytest.raises(KeyError) as ei:
            get_deploy_target("s3")
        msg = str(ei.value)
        assert "bunny" in msg and "folder" in msg

    def test_all_targets_are_deploytarget_subclasses(self):
        from splatpipe.deploy_targets.registry import DEPLOY_TARGETS

        for cls in DEPLOY_TARGETS.values():
            assert issubclass(cls, DeployTarget)


# ---------------------------------------------------------------------------
# FolderDeployTarget — pure local FS, no network
# ---------------------------------------------------------------------------
class TestFolderDeployTarget:
    def _staged(self, root: Path) -> Path:
        stage = root / "stage"
        (stage / "bKEY").mkdir(parents=True)
        (stage / "index.html").write_text("<html>shell</html>", encoding="utf-8")
        (stage / "viewer-config.json").write_text('{"primary_asset": "bKEY/scene.rad"}',
                                                  encoding="utf-8")
        (stage / "bKEY" / "scene.rad").write_bytes(b"RADMANIFEST")
        (stage / "bKEY" / "scene-0.radc").write_bytes(b"CHUNK0")
        return stage

    def test_copies_tree(self, tmp_path):
        stage = self._staged(tmp_path)
        dest = tmp_path / "dest"
        t = FolderDeployTarget(destination=dest)
        result = _drain(t.deploy_staged("speicher", stage))

        assert isinstance(result, StepResult)
        assert result.success, result.error
        out = dest / "speicher"
        assert (out / "index.html").read_text(encoding="utf-8") == "<html>shell</html>"
        assert (out / "viewer-config.json").exists()
        assert (out / "bKEY" / "scene.rad").read_bytes() == b"RADMANIFEST"
        assert (out / "bKEY" / "scene-0.radc").read_bytes() == b"CHUNK0"

    def test_idempotent_overwrite_safe(self, tmp_path):
        """Re-deploying the same slug overwrites without error and leaves
        the destination matching the new staged content."""
        stage = self._staged(tmp_path)
        dest = tmp_path / "dest"
        t = FolderDeployTarget(destination=dest)
        _drain(t.deploy_staged("speicher", stage))

        # Mutate the staged shell + chunk; re-deploy.
        (stage / "index.html").write_text("<html>NEW</html>", encoding="utf-8")
        (stage / "bKEY" / "scene.rad").write_bytes(b"RADMANIFEST_V2")
        result = _drain(t.deploy_staged("speicher", stage))

        assert result.success, result.error
        out = dest / "speicher"
        assert (out / "index.html").read_text(encoding="utf-8") == "<html>NEW</html>"
        assert (out / "bKEY" / "scene.rad").read_bytes() == b"RADMANIFEST_V2"

    def test_yields_progress_events(self, tmp_path):
        stage = self._staged(tmp_path)
        dest = tmp_path / "dest"
        t = FolderDeployTarget(destination=dest)
        events = []
        gen = t.deploy_staged("p", stage)
        try:
            while True:
                events.append(next(gen))
        except StopIteration:
            pass
        assert events
        assert all(isinstance(e, ProgressEvent) for e in events)

    def test_invalidate_and_ensure_fresh_are_noops(self, tmp_path):
        """A local folder is inherently fresh — no network calls."""
        t = FolderDeployTarget(destination=tmp_path)
        assert t.ensure_fresh(quiet=True) is True
        assert t.invalidate(["http://whatever/index.html"]) is None

    def test_validate_environment(self, tmp_path):
        ok, _ = FolderDeployTarget(destination=tmp_path).validate_environment()
        assert ok is True


# ---------------------------------------------------------------------------
# BunnyDeployTarget — FAITHFUL DELEGATION (the byte-identity proof)
# ---------------------------------------------------------------------------
class TestBunnyDeployTargetDelegation:
    def test_deploy_staged_delegates_with_purge_false(self, tmp_path):
        """The bunny target calls the EXISTING deploy_to_bunny with the EXACT
        same positional/keyword args the old direct publish call used —
        crucially purge=False (the async-delete race fix)."""
        stage = tmp_path / "stage"
        stage.mkdir()
        seen = {}

        def _fake(slug, output_dir, env, *, workers=8, purge=False):
            seen["args"] = (slug, output_dir, env)
            seen["workers"] = workers
            seen["purge"] = purge
            yield ProgressEvent(step="export", progress=1.0, message="Uploaded 1/1")
            return StepResult(step="export", success=True, summary={"uploaded": 1})

        # No injection → the adapter resolves the REAL steps.deploy
        # function at call time, so patching steps.deploy intercepts it.
        # This proves the default delegation target is the battle-tested
        # function (not a reimplementation).
        t = BunnyDeployTarget(env=ENV)
        with patch("splatpipe.steps.deploy.deploy_to_bunny", _fake):
            result = _drain(t.deploy_staged("speicher", stage, workers=12))

        assert seen["args"] == ("speicher", stage, ENV)
        assert seen["workers"] == 12
        assert seen["purge"] is False          # INVARIANT preserved
        assert result.success
        assert result.summary["uploaded"] == 1

    def test_ensure_fresh_delegates_to_ensure_edge_rules(self):
        """ensure_fresh must call the existing ensure_edge_rules with the
        account API key + quiet flag (the cache-freshness REQUIREMENT for
        bunny IS the Edge-Rule mechanism — not weakened)."""
        seen = {}

        def _fake(api_key, *, verify_only=False, quiet=False):
            seen["api_key"] = api_key
            seen["quiet"] = quiet
            return True

        t = BunnyDeployTarget(env=ENV)
        with patch("splatpipe.steps.deploy.ensure_edge_rules", _fake):
            out = t.ensure_fresh(quiet=True)

        assert out is True
        assert seen["api_key"] == "ak"
        assert seen["quiet"] is True

    def test_invalidate_delegates_to_purge_bunny_cache(self):
        """invalidate must call the existing purge_bunny_cache with the
        account API key and exactly the URLs passed (the two stable text
        files — never the immutable chunks)."""
        seen = {}

        def _fake(api_key, urls):
            seen["api_key"] = api_key
            seen["urls"] = urls
            return (len(urls), 0)

        urls = [
            "https://splatpipe-cdn.b-cdn.net/speicher/index.html",
            "https://splatpipe-cdn.b-cdn.net/speicher/viewer-config.json",
        ]
        t = BunnyDeployTarget(env=ENV)
        with patch("splatpipe.steps.deploy.purge_bunny_cache", _fake):
            t.invalidate(urls)

        assert seen["api_key"] == "ak"
        assert seen["urls"] == urls

    def test_invalidate_no_api_key_is_safe_noop(self):
        """No account API key → invalidate must not call purge (mirrors the
        `if api:` guard in publish_scene); no crash."""
        called = {"n": 0}

        def _fake(api_key, urls):
            called["n"] += 1
            return (0, 0)

        t = BunnyDeployTarget(env={"BUNNY_STORAGE_ZONE": "z",
                                   "BUNNY_STORAGE_PASSWORD": "p"})
        with patch("splatpipe.steps.deploy.purge_bunny_cache", _fake):
            t.invalidate(["http://x/index.html"])
        assert called["n"] == 0

    def test_validate_environment_requires_creds(self):
        ok, _ = BunnyDeployTarget(env={}).validate_environment()
        assert ok is False
        ok, _ = BunnyDeployTarget(env=ENV).validate_environment()
        assert ok is True


# ---------------------------------------------------------------------------
# Behaviour preservation: publish_scene's bunny path is byte-identical
# ---------------------------------------------------------------------------
class TestPublishStillUsesBunnyByteIdentically:
    """After routing publish through get_deploy_target, the default (bunny)
    path must produce the SAME deploy_to_bunny(..., purge=False) call,
    edge-rule assertion, and selective purge as before."""

    @pytest.fixture
    def rad_dir(self, tmp_path: Path) -> Path:
        d = tmp_path / "prebuilt"
        d.mkdir()
        (d / "scene-lod.rad").write_bytes(b"RADMANIFEST")
        (d / "scene-lod-0.radc").write_bytes(b"CHUNK0")
        return d

    def test_publish_default_path_preserves_invariants(self, rad_dir):
        from splatpipe.steps.publish import publish_scene

        captured = {}
        purged = {}

        def _fake_deploy(slug, stage, env, *, workers=8, purge=False):
            captured["slug"] = slug
            captured["purge"] = purge
            captured["workers"] = workers
            import json
            captured["index_html"] = (Path(stage) / "index.html").read_text(
                encoding="utf-8")
            captured["viewer_config"] = json.loads(
                (Path(stage) / "viewer-config.json").read_text(encoding="utf-8"))
            yield ProgressEvent(step="export", progress=1.0, message="Uploaded 2/2")
            return StepResult(step="export", success=True,
                              summary={"uploaded": 2, "failed": 0,
                                       "failed_files": []})

        # publish injects its own (patchable) module-level deploy refs into
        # the bunny adapter, so the EXISTING oracle's patch targets
        # (splatpipe.steps.publish.*) still intercept — proving the bunny
        # path is byte-identical through the abstraction.
        with patch("splatpipe.steps.publish.deploy_to_bunny", _fake_deploy), \
             patch("splatpipe.steps.publish.ensure_edge_rules",
                   return_value=True) as edge, \
             patch("splatpipe.steps.publish.list_bunny_subfolders",
                   return_value=[]), \
             patch("splatpipe.steps.publish.purge_bunny_cache",
                   side_effect=lambda api, urls:
                       purged.setdefault("urls", urls) or (len(urls), 0)):
            result = _drain(publish_scene(
                scene_name="Speicher", slug="speicher", env=ENV,
                rad_dir=rad_dir))

        assert result.success, result.error
        # INVARIANT: purge=False preserved through the abstraction
        assert captured["purge"] is False
        assert captured["workers"] == 12
        # INVARIANT: edge rule asserted every run
        edge.assert_called_once()
        # INVARIANT: only the two stable text files purged
        assert purged["urls"] == [
            "https://splatpipe-cdn.b-cdn.net/speicher/index.html",
            "https://splatpipe-cdn.b-cdn.net/speicher/viewer-config.json",
        ]
        # INVARIANT: index.html build-agnostic, pointer in viewer-config.json
        bkey = result.summary["bkey"]
        assert bkey not in captured["index_html"]
        assert captured["viewer_config"]["primary_asset"] == f"{bkey}/scene.rad"


# ---------------------------------------------------------------------------
# Fix 1 locking test: folder path NEVER calls list_bunny_subfolders
# ---------------------------------------------------------------------------
class TestFolderPublishSkipsBunnySubfolderCall:
    """Guard for Fix 1 (Important bug): publish_scene(..., deploy_target='folder')
    must never call list_bunny_subfolders — the prune block is Bunny-only and
    the function would make a spurious HTTPS request on non-bunny targets."""

    @pytest.fixture
    def rad_dir(self, tmp_path: Path) -> Path:
        d = tmp_path / "prebuilt"
        d.mkdir()
        (d / "scene-lod.rad").write_bytes(b"RADMANIFEST")
        (d / "scene-lod-0.radc").write_bytes(b"CHUNK0")
        return d

    def test_folder_path_never_calls_list_bunny_subfolders(self, rad_dir, tmp_path):
        """The folder deploy path must skip step-8 entirely (no network call)
        and still produce a successful deploy with the correct step name."""
        from splatpipe.steps.publish import publish_scene

        mock_list_subs = MagicMock(return_value=[])
        dest = tmp_path / "out"

        with patch("splatpipe.steps.publish.list_bunny_subfolders", mock_list_subs):
            result = _drain(publish_scene(
                scene_name="TestScene",
                slug="testscene",
                env={},
                rad_dir=rad_dir,
                deploy_target="folder",
                deploy_dest=dest,
            ))

        # The folder deploy must succeed.
        assert result.success, result.error
        assert result.step == STEP_PUBLISH

        # INVARIANT (Fix 1): list_bunny_subfolders must NEVER be called for
        # a non-bunny target — no spurious outbound HTTPS request.
        mock_list_subs.assert_not_called()

        # The output files must be present under <dest>/<slug>/.
        out = dest / "testscene"
        assert (out / "index.html").exists()
        assert (out / "viewer-config.json").exists()
        bkey = result.summary["bkey"]
        assert (out / bkey / "scene.rad").read_bytes() == b"RADMANIFEST"

    def test_folder_deploy_result_step_is_publish(self, rad_dir, tmp_path):
        """FolderDeployTarget.deploy_staged returns step=STEP_PUBLISH
        (Fix 2: the hardcoded 'export' literal is replaced)."""
        from splatpipe.deploy_targets.folder import FolderDeployTarget

        dest = tmp_path / "out"
        stage = tmp_path / "stage"
        (stage / "bKEY").mkdir(parents=True)
        (stage / "index.html").write_text("<html/>", encoding="utf-8")
        (stage / "viewer-config.json").write_text("{}", encoding="utf-8")
        (stage / "bKEY" / "scene.rad").write_bytes(b"R")
        (stage / "bKEY" / "s.radc").write_bytes(b"C")

        t = FolderDeployTarget(destination=dest)
        result = _drain(t.deploy_staged("slug", stage))

        assert result.step == STEP_PUBLISH, (
            f"expected step={STEP_PUBLISH!r}, got {result.step!r} — "
            "Fix 2 regression: 'export' literal still present in folder.py"
        )
