"""Tests for the pluggable SaveBackend abstraction (cli default + thin php/cloudflare).

These lock, mirroring ``tests/test_trainers.py`` / ``tests/test_deploy_targets.py``:

  * The registry mirrors the trainer registry exactly (name-string selector,
    ``list_save_backends()``, ``KeyError`` with the available list, default
    is ``cli``).
  * ``CliRelayBackend`` is a FAITHFUL REUSE — it fetches the live
    viewer-config via the explored ``set_start_view`` fetch helper, merges
    the patch via the shared ``merge_camera_scope`` core (so
    ``primary_asset`` is force-kept), and writes via the resolved
    pluggable ``DeployTarget`` — it does NOT reimplement merge/deploy.
    Non-allow-listed patch keys surface in ``SaveResult.ignored_keys``
    (the Task-4 review carry-forward; informational, not an error).
  * ``Project.save_backend`` mirrors ``trainer`` / ``renderer`` exactly:
    state-root flag, defaults to ``"cli"``, round-trips through
    ``state.json``, ``_migrate_state`` adds it to a legacy state dict.
  * ``PhpEndpointBackend`` / ``CloudflareWorkerBackend`` are THIN: the save
    happens browser→server, not in Python — their ``save_keyframes``
    clearly signals that and ``validate_environment`` keys off the
    configured endpoint.
"""

import json

import pytest

from splatpipe.core.project import Project
from splatpipe.save_backends.base import SaveBackend, SaveResult
from splatpipe.save_backends.cli import CliRelayBackend
from splatpipe.save_backends.cloudflare import CloudflareWorkerBackend
from splatpipe.save_backends.php import PhpEndpointBackend
from splatpipe.save_backends.registry import (
    SAVE_BACKENDS,
    get_save_backend,
    list_save_backends,
)


# ---------------------------------------------------------------------------
# Registry (mirrors tests/test_trainers.py::TestRegistry)
# ---------------------------------------------------------------------------
class TestRegistry:
    def test_list_save_backends(self):
        backends = list_save_backends()
        assert "cli" in backends
        assert "php" in backends
        assert "cloudflare" in backends

    def test_get_cli(self):
        b = get_save_backend("cli", {})
        assert isinstance(b, CliRelayBackend)
        assert b.name == "cli"

    def test_get_php(self):
        b = get_save_backend("php", {})
        assert isinstance(b, PhpEndpointBackend)
        assert b.name == "php"

    def test_get_cloudflare(self):
        b = get_save_backend("cloudflare", {})
        assert isinstance(b, CloudflareWorkerBackend)
        assert b.name == "cloudflare"

    def test_unknown_backend(self):
        with pytest.raises(KeyError, match="Unknown save backend"):
            get_save_backend("nonexistent", {})

    def test_unknown_backend_lists_available(self):
        with pytest.raises(KeyError) as ei:
            get_save_backend("s3", {})
        msg = str(ei.value)
        assert "cli" in msg and "php" in msg and "cloudflare" in msg

    def test_all_backends_are_savebackend_subclasses(self):
        for cls in SAVE_BACKENDS.values():
            assert issubclass(cls, SaveBackend)


# ---------------------------------------------------------------------------
# Project.save_backend wiring (mirrors test_project.py trainer/renderer)
# ---------------------------------------------------------------------------
class TestProjectSaveBackend:
    def test_default_is_cli(self, tmp_path):
        project = Project.create(tmp_path / "proj", "Test")
        assert project.save_backend == "cli"

    def test_set_save_backend_persists(self, tmp_path):
        project = Project.create(tmp_path / "proj", "Test")
        project.set_save_backend("php")
        assert project.save_backend == "php"
        # Verify persisted to state.json
        project2 = Project(project.root)
        assert project2.save_backend == "php"
        assert json.loads(project.state_path.read_text())["save_backend"] == "php"

    def test_migrate_state_adds_save_backend_to_legacy(self, tmp_path):
        """A legacy state dict lacking save_backend gets the field via
        _migrate_state (setdefault). Mirrors trainer/renderer: a defaulted
        root field — it does NOT, on its own, flip the migration's
        ``changed`` flag (the `.get` property already covers backward-compat
        reads; forcing a write would regress the annotation no-op contract).
        """
        legacy = {"name": "Old", "trainer": "postshot", "steps": {}}
        changed = Project._migrate_state(legacy)
        # Field is now present and defaulted …
        assert legacy["save_backend"] == "cli"
        # … but a save_backend-only default does not force a persist
        # (matches test_path_io.py's annotation no-op contract).
        assert changed is False

    def test_migrate_state_idempotent_when_present(self, tmp_path):
        """_migrate_state preserves an already-set save_backend (no clobber)."""
        state = {"name": "X", "save_backend": "php"}
        changed = Project._migrate_state(state)
        assert state["save_backend"] == "php"
        assert changed is False

    def test_old_project_loads_with_cli_default(self, tmp_path):
        """An on-disk state.json without save_backend reads back as 'cli'."""
        project = Project.create(tmp_path / "proj", "Test")
        st = json.loads(project.state_path.read_text())
        st.pop("save_backend", None)
        project.state_path.write_text(json.dumps(st))
        fresh = Project(project.root)
        assert fresh.save_backend == "cli"

    def test_set_save_backend_valid_roundtrip(self, tmp_path):
        """Fix 2: valid backend names are accepted and persisted."""
        project = Project.create(tmp_path / "proj", "Test")
        project.set_save_backend("php")
        assert project.save_backend == "php"
        project2 = Project(project.root)
        assert project2.save_backend == "php"

    def test_set_save_backend_invalid_raises_value_error(self, tmp_path):
        """Fix 2: set_save_backend("bogus") raises ValueError whose message
        lists the available backends, and does NOT mutate the project state.
        """
        project = Project.create(tmp_path / "proj", "Test")
        original_backend = project.save_backend  # "cli"
        with pytest.raises(ValueError) as ei:
            project.set_save_backend("bogus")
        msg = str(ei.value)
        # Error message must name the bad value …
        assert "bogus" in msg
        # … and list the valid options.
        assert "cli" in msg
        assert "php" in msg
        assert "cloudflare" in msg
        # State is unchanged after the failed call (both in-memory and on-disk).
        assert project.save_backend == original_backend
        # On-disk: the key may be absent (cli default) or explicitly "cli" —
        # either way it must not have been set to "bogus".
        persisted = json.loads(project.state_path.read_text())
        assert persisted.get("save_backend", "cli") == original_backend


# ---------------------------------------------------------------------------
# CliRelayBackend — FAITHFUL REUSE (fetch + merge_camera_scope + DeployTarget)
# ---------------------------------------------------------------------------
class TestCliRelayBackend:
    BASE_CFG = {
        "primary_asset": "bLIVEKEY/scene.rad",
        "start_view": {"pos": [0, 0, 0]},
        "some_unrelated_key": {"keep": True},
    }

    def _backend(self):
        # save_backend.deploy_target left default (bunny); env carries creds.
        return CliRelayBackend({
            "save_backend": {"type": "cli", "deploy_target": "bunny"},
            "bunny": {},
        })

    def test_save_keyframes_merges_and_deploys(self, monkeypatch, tmp_path):
        """save_keyframes must:
        - fetch the existing live viewer-config (via the set_start_view helper),
        - merge_camera_scope it (primary_asset force-kept, payload applied),
        - deploy via the resolved DeployTarget,
        - return a successful SaveResult,
        - list a non-allow-listed payload key in ignored_keys.
        """
        captured = {}

        # 1. Stub the fetch helper that CliRelayBackend reuses.
        def fake_fetch(self):
            return dict(self.BASE_CFG) if False else dict(TestCliRelayBackend.BASE_CFG)

        monkeypatch.setattr(
            "splatpipe.save_backends.cli.CliRelayBackend._fetch_live_config",
            lambda self, slug: dict(TestCliRelayBackend.BASE_CFG),
        )

        # 2. Stub the DeployTarget so no network/build happens; capture the
        #    staged viewer-config it would deploy.
        from splatpipe.core.events import ProgressEvent, StepResult

        class FakeTarget:
            name = "fake"

            def validate_environment(self):
                return True, "ok"

            def ensure_fresh(self, *, quiet=False):
                captured["ensure_fresh"] = True
                return True

            def deploy_staged(self, slug, staged_dir, *, workers=8):
                from pathlib import Path
                captured["slug"] = slug
                captured["staged_cfg"] = json.loads(
                    (Path(staged_dir) / "viewer-config.json").read_text(
                        encoding="utf-8"))
                yield ProgressEvent(step="publish", progress=1.0,
                                    message="Uploaded 1/1")
                return StepResult(step="publish", success=True,
                                  summary={"uploaded": 1})

            def invalidate(self, urls):
                captured["invalidated"] = urls

        monkeypatch.setattr(
            "splatpipe.save_backends.cli.get_deploy_target",
            lambda name=None, **kw: FakeTarget(),
        )

        backend = self._backend()
        payload = {
            "v": 1,
            "scope": "camera_paths",
            "camera_paths": [{"id": "p1", "keyframes": []}],
            "primary_asset": "bMALICIOUS/scene.rad",  # must be force-dropped
            "totally_unknown_key": 123,               # must surface in ignored
        }
        result = backend.save_keyframes("speicher", payload, token="SPCP1:speicher:x")

        assert isinstance(result, SaveResult)
        assert result.success is True
        assert result.backend == "cli"
        assert result.slug == "speicher"
        # Deploy happened via the resolved target.
        assert captured["slug"] == "speicher"
        # merge_camera_scope semantics: allow-listed key applied …
        assert captured["staged_cfg"]["camera_paths"] == [
            {"id": "p1", "keyframes": []}]
        # … unrelated existing key preserved …
        assert captured["staged_cfg"]["some_unrelated_key"] == {"keep": True}
        # … primary_asset force-kept from EXISTING (never the patch's value).
        assert captured["staged_cfg"]["primary_asset"] == "bLIVEKEY/scene.rad"
        # Task-4 carry-forward: the non-allow-listed key is reported.
        assert "totally_unknown_key" in result.ignored_keys
        # primary_asset is NEVER reported as ignored (it's a locked invariant,
        # not an "author typo" diagnostic).
        assert "primary_asset" not in result.ignored_keys

    def test_save_keyframes_deploy_failure_unsuccessful(self, monkeypatch):
        """A failing DeployTarget yields an unsuccessful SaveResult with the error."""
        monkeypatch.setattr(
            "splatpipe.save_backends.cli.CliRelayBackend._fetch_live_config",
            lambda self, slug: {"primary_asset": "bX/scene.rad"},
        )
        from splatpipe.core.events import StepResult

        class FailTarget:
            name = "fail"

            def validate_environment(self):
                return True, "ok"

            def ensure_fresh(self, *, quiet=False):
                return True

            def deploy_staged(self, slug, staged_dir, *, workers=8):
                yield from ()
                return StepResult(step="publish", success=False,
                                  error="boom")

            def invalidate(self, urls):
                pass

        monkeypatch.setattr(
            "splatpipe.save_backends.cli.get_deploy_target",
            lambda name=None, **kw: FailTarget(),
        )
        backend = self._backend()
        result = backend.save_keyframes(
            "s", {"v": 1, "scope": "camera_paths", "camera_paths": []},
            token="t")
        assert result.success is False
        assert "boom" in (result.error or "")

    def test_validate_environment_delegates_to_target(self, monkeypatch):
        """validate_environment is true iff the resolved DeployTarget's env is."""
        class OkTarget:
            name = "ok"

            def validate_environment(self):
                return True, "creds present"

        class BadTarget:
            name = "bad"

            def validate_environment(self):
                return False, "missing creds"

        backend = self._backend()

        monkeypatch.setattr(
            "splatpipe.save_backends.cli.get_deploy_target",
            lambda name=None, **kw: OkTarget(),
        )
        ok, msg = backend.validate_environment()
        assert ok is True

        monkeypatch.setattr(
            "splatpipe.save_backends.cli.get_deploy_target",
            lambda name=None, **kw: BadTarget(),
        )
        ok, msg = backend.validate_environment()
        assert ok is False
        assert "missing creds" in msg

    def test_validate_environment_unknown_target_is_unsuccessful(self, monkeypatch):
        """An unresolvable deploy target → (False, msg), not a raised KeyError."""
        def _raise(name=None, **kw):
            raise KeyError(f"Unknown deploy target: {name!r}. Available: bunny, folder")

        monkeypatch.setattr(
            "splatpipe.save_backends.cli.get_deploy_target", _raise)
        backend = CliRelayBackend({
            "save_backend": {"type": "cli", "deploy_target": "nope"}})
        ok, msg = backend.validate_environment()
        assert ok is False
        assert "nope" in msg

    def test_save_keyframes_fetch_exception_returns_save_result(self, monkeypatch):
        """Fix 1: when _fetch_live_config raises (e.g. HTTPError / URLError),
        save_keyframes must return SaveResult(success=False) with a fetch-fail
        error — it must NOT let the exception escape the ABC contract.
        """
        import urllib.error

        monkeypatch.setattr(
            "splatpipe.save_backends.cli.CliRelayBackend._fetch_live_config",
            lambda self, slug: (_ for _ in ()).throw(
                urllib.error.URLError("boom")),
        )
        # DeployTarget must be resolvable and env-valid so we reach the fetch.
        class OkTarget:
            name = "ok"

            def validate_environment(self):
                return True, "ok"

            def ensure_fresh(self, *, quiet=False):
                return True

        monkeypatch.setattr(
            "splatpipe.save_backends.cli.get_deploy_target",
            lambda name=None, **kw: OkTarget(),
        )
        backend = self._backend()
        payload = {
            "v": 1,
            "scope": "camera_paths",
            "camera_paths": [],
            "totally_unknown_key": 999,
        }
        result = backend.save_keyframes("test-slug", payload, token="t")
        assert isinstance(result, SaveResult)
        assert result.success is False
        assert result.slug == "test-slug"
        assert "fetch" in (result.error or "").lower()
        assert "failed" in (result.error or "").lower()
        # ignored_keys is still populated (derived from payload before the fetch)
        assert "totally_unknown_key" in result.ignored_keys


# ---------------------------------------------------------------------------
# Thin php / cloudflare backends — save is in-browser, not Python
# ---------------------------------------------------------------------------
class TestThinHttpBackends:
    @pytest.mark.parametrize(
        "cls,name",
        [(PhpEndpointBackend, "php"), (CloudflareWorkerBackend, "cloudflare")],
    )
    def test_validate_environment_keys_off_endpoint(self, cls, name):
        # No endpoint configured → not valid.
        b = cls({"save_backend": {"type": name, "endpoint": ""}})
        ok, msg = b.validate_environment()
        assert ok is False
        assert b.name == name

        # A configured URL-looking endpoint → valid.
        b2 = cls({"save_backend": {"type": name,
                                   "endpoint": "https://example.com/save.php"}})
        ok2, _ = b2.validate_environment()
        assert ok2 is True
        assert b2.endpoint == "https://example.com/save.php"

    @pytest.mark.parametrize(
        "cls", [PhpEndpointBackend, CloudflareWorkerBackend])
    def test_validate_environment_rejects_non_url(self, cls):
        b = cls({"save_backend": {"endpoint": "not-a-url"}})
        ok, _ = b.validate_environment()
        assert ok is False

    @pytest.mark.parametrize(
        "cls", [PhpEndpointBackend, CloudflareWorkerBackend])
    def test_save_keyframes_signals_in_browser(self, cls):
        """The Python side is config-only for these; save_keyframes must
        clearly signal the save is performed in-browser against the
        configured endpoint (NOT a Python save path)."""
        b = cls({"save_backend": {
            "endpoint": "https://example.com/save"}})
        result = b.save_keyframes(
            "slug", {"v": 1, "scope": "camera_paths"}, token="t")
        assert isinstance(result, SaveResult)
        assert result.success is False
        msg = (result.error or "").lower()
        assert "browser" in msg
        assert "endpoint" in msg
