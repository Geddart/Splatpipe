"""Tests for the ``splatpipe set-camera-path`` CLI (Task 7).

The author-facing entrypoint of the decision-A DEFAULT save path. This
command is a THIN faithful wrapper: it decodes the viewer-emitted
``SPCP1`` token via :mod:`splatpipe.core.spcp_token` and relays the
``(slug, payload)`` to the already-built, separately-tested
:class:`splatpipe.save_backends.cli.CliRelayBackend` (fetch live
viewer-config -> ``merge_camera_scope`` [``primary_asset`` force-kept] ->
write via the configured ``DeployTarget``). It MUST NOT reimplement any of
that.

These mirror ``tests/test_cli.py`` (``typer.testing.CliRunner`` + the
shared ``splatpipe.cli.main.app``) and reuse the EXACT Task-6a test seam
from ``tests/test_save_backends.py`` — monkeypatch
``splatpipe.save_backends.cli.CliRelayBackend._fetch_live_config`` (the
live-config GET) and ``splatpipe.save_backends.cli.get_deploy_target``
(the network/build) so no I/O happens.

Cases:
  (a) valid SPCP1 token -> deploy target receives a merged config with the
      new ``camera_paths`` / ``default_path_id``, ``primary_asset``
      preserved unchanged, exit 0, ASCII success message.
  (b) bad / non-SPCP token -> SpcpError path -> non-zero exit, clear
      message, NO deploy.
  (c) a non-allow-listed payload key -> appears in the printed ``ignored``
      line, is NOT written, and a malicious ``primary_asset`` in the patch
      is never applied.
  (d) a backend failure (``SaveResult(success=False)``, e.g. fetch fail)
      -> non-zero exit, prints the error, no exception leaks.
"""

import json

from typer.testing import CliRunner

from splatpipe.cli.main import app
from splatpipe.core.events import ProgressEvent, StepResult
from splatpipe.core.spcp_token import encode_spcp

runner = CliRunner()

# Live viewer-config the (stubbed) fetch returns: it already has a
# primary_asset (the locked Bunny pointer) + an unrelated key. The merge
# core must force-keep primary_asset and preserve the unrelated key.
LIVE_CFG = {
    "primary_asset": "bLIVEKEY/scene.rad",
    "start_view": {"pos": [9, 9, 9]},
    "some_unrelated_key": {"keep": True},
}

GOOD_PAYLOAD = {
    "v": 1,
    "scope": "camera_paths",
    "camera_paths": [{"id": "p1", "name": "Tour", "keyframes": []}],
    "cameras": [],
    "clips": [],
    "default_path_id": "p1",
}


class _FakeTarget:
    """A DeployTarget stand-in that captures the staged viewer-config
    instead of touching the network (same seam as test_save_backends.py)."""

    name = "fake"

    def __init__(self, captured: dict):
        self._cap = captured

    def validate_environment(self):
        return True, "ok"

    def ensure_fresh(self, *, quiet=False):
        return True

    def deploy_staged(self, slug, staged_dir, *, workers=8):
        from pathlib import Path

        self._cap["slug"] = slug
        self._cap["staged_cfg"] = json.loads(
            (Path(staged_dir) / "viewer-config.json").read_text(
                encoding="utf-8"))
        yield ProgressEvent(step="publish", progress=1.0,
                            message="Uploaded 1/1")
        return StepResult(step="publish", success=True,
                          summary={"uploaded": 1})

    def invalidate(self, urls):
        self._cap["invalidated"] = urls


def _patch_cli_seam(monkeypatch, captured, *, live_cfg=None):
    """Stub the exact two seams CliRelayBackend exposes for tests:
    the live-config fetch and the DeployTarget construction."""
    monkeypatch.setattr(
        "splatpipe.save_backends.cli.CliRelayBackend._fetch_live_config",
        lambda self, slug: dict(LIVE_CFG if live_cfg is None else live_cfg),
    )
    monkeypatch.setattr(
        "splatpipe.save_backends.cli.get_deploy_target",
        lambda name=None, **kw: _FakeTarget(captured),
    )


# ---------------------------------------------------------------------------
# (a) valid SPCP1 token -> merged config deployed, primary_asset force-kept
# ---------------------------------------------------------------------------
def test_valid_token_merges_and_deploys(monkeypatch):
    captured: dict = {}
    _patch_cli_seam(monkeypatch, captured)

    token = encode_spcp("speicher", GOOD_PAYLOAD)
    result = runner.invoke(app, ["set-camera-path", token])

    assert result.exit_code == 0, result.output
    # Deploy happened via the resolved (fake) target with the right slug.
    assert captured["slug"] == "speicher"
    cfg = captured["staged_cfg"]
    # merge_camera_scope semantics: allow-listed keys applied wholesale ...
    assert cfg["camera_paths"] == [{"id": "p1", "name": "Tour",
                                    "keyframes": []}]
    assert cfg["default_path_id"] == "p1"
    # ... unrelated existing key preserved ...
    assert cfg["some_unrelated_key"] == {"keep": True}
    # ... primary_asset force-kept from the EXISTING live config.
    assert cfg["primary_asset"] == "bLIVEKEY/scene.rad"
    # ASCII success message naming the slug; never echoes the token.
    assert "speicher" in result.output
    assert token not in result.output
    assert result.output.isascii()


def test_positional_token_different_slug_deploys(monkeypatch):
    """Token is a Typer Argument (positional); a different slug is routed
    correctly through the backend to the deploy target."""
    captured: dict = {}
    _patch_cli_seam(monkeypatch, captured)
    token = encode_spcp("fehmarn", GOOD_PAYLOAD)
    result = runner.invoke(app, ["set-camera-path", token])
    assert result.exit_code == 0, result.output
    assert captured["slug"] == "fehmarn"


# ---------------------------------------------------------------------------
# (b) bad / non-SPCP token -> SpcpError path -> non-zero, no deploy
# ---------------------------------------------------------------------------
def test_bad_token_exits_nonzero_no_deploy(monkeypatch):
    captured: dict = {}
    _patch_cli_seam(monkeypatch, captured)

    result = runner.invoke(app, ["set-camera-path", "SPV1:x:not-a-spcp"])

    assert result.exit_code != 0
    # A clear ASCII error; no deploy was attempted.
    assert result.output.isascii()
    assert "captured" not in captured or "slug" not in captured
    assert "slug" not in captured
    lowered = result.output.lower()
    assert "spcp1" in lowered or "token" in lowered


def test_corrupt_b64_token_exits_nonzero(monkeypatch):
    captured: dict = {}
    _patch_cli_seam(monkeypatch, captured)
    result = runner.invoke(app, ["set-camera-path", "SPCP1:fehmarn:!!!notb64"])
    assert result.exit_code != 0
    assert "slug" not in captured
    assert result.output.isascii()


# ---------------------------------------------------------------------------
# (c) non-allow-listed key -> printed as ignored, NOT written; malicious
#     primary_asset in the patch is never applied
# ---------------------------------------------------------------------------
def test_non_allowlisted_key_reported_and_dropped(monkeypatch):
    captured: dict = {}
    _patch_cli_seam(monkeypatch, captured)

    payload = {
        "v": 1,
        "scope": "camera_paths",
        "camera_paths": [{"id": "p1", "keyframes": []}],
        "default_path_id": "p1",
        "primary_asset": "bMALICIOUS/scene.rad",   # must be force-dropped
        "totally_unknown_key": 123,                # must surface in ignored
    }
    token = encode_spcp("polygraf", payload)
    result = runner.invoke(app, ["set-camera-path", token])

    assert result.exit_code == 0, result.output
    cfg = captured["staged_cfg"]
    # The non-allow-listed key was NOT written ...
    assert "totally_unknown_key" not in cfg
    # ... and the malicious primary_asset never took effect (force-kept).
    assert cfg["primary_asset"] == "bLIVEKEY/scene.rad"
    # The dropped key is surfaced to the author (informational, NOT error).
    lowered = result.output.lower()
    assert "ignored" in lowered
    assert "totally_unknown_key" in result.output
    # primary_asset is a locked invariant, never an "author typo" — it must
    # NOT be listed in the ignored line.
    assert "primary_asset" not in result.output


# ---------------------------------------------------------------------------
# (d) backend failure (SaveResult(success=False)) -> non-zero, prints error
# ---------------------------------------------------------------------------
def test_backend_fetch_failure_exits_nonzero(monkeypatch):
    """A fetch failure inside CliRelayBackend becomes SaveResult(success=
    False) (not an exception); the CLI must surface result.error and exit
    non-zero without leaking a traceback."""
    import urllib.error

    # Fetch raises -> CliRelayBackend turns it into SaveResult(success=False).
    monkeypatch.setattr(
        "splatpipe.save_backends.cli.CliRelayBackend._fetch_live_config",
        lambda self, slug: (_ for _ in ()).throw(
            urllib.error.URLError("boom-network")),
    )

    class _OkTarget:
        name = "ok"

        def validate_environment(self):
            return True, "ok"

        def ensure_fresh(self, *, quiet=False):
            return True

    monkeypatch.setattr(
        "splatpipe.save_backends.cli.get_deploy_target",
        lambda name=None, **kw: _OkTarget(),
    )

    token = encode_spcp("test-slug", GOOD_PAYLOAD)
    result = runner.invoke(app, ["set-camera-path", token])

    assert result.exit_code != 0
    # The backend's error string is surfaced to the author ...
    assert "fetch" in result.output.lower()
    # ... and no exception escaped the command (CliRunner captures it).
    assert result.exception is None or isinstance(
        result.exception, SystemExit)
    assert result.output.isascii()


def test_deploy_target_failure_exits_nonzero(monkeypatch):
    """A failing DeployTarget -> SaveResult(success=False) -> non-zero."""
    monkeypatch.setattr(
        "splatpipe.save_backends.cli.CliRelayBackend._fetch_live_config",
        lambda self, slug: {"primary_asset": "bX/scene.rad"},
    )

    class _FailTarget:
        name = "fail"

        def validate_environment(self):
            return True, "ok"

        def ensure_fresh(self, *, quiet=False):
            return True

        def deploy_staged(self, slug, staged_dir, *, workers=8):
            yield from ()
            return StepResult(step="publish", success=False,
                              error="deploy-blew-up")

        def invalidate(self, urls):
            pass

    monkeypatch.setattr(
        "splatpipe.save_backends.cli.get_deploy_target",
        lambda name=None, **kw: _FailTarget(),
    )

    token = encode_spcp("scene-x", GOOD_PAYLOAD)
    result = runner.invoke(app, ["set-camera-path", token])

    assert result.exit_code != 0
    assert "deploy-blew-up" in result.output
    assert result.output.isascii()


# ---------------------------------------------------------------------------
# --help smoke: the command is registered and documents the always-available
# over-256KB / offline / CI escape (per the §H2 decision).
# ---------------------------------------------------------------------------
def test_help_lists_command():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "set-camera-path" in result.output


def test_command_help_text():
    result = runner.invoke(app, ["set-camera-path", "--help"])
    assert result.exit_code == 0
    # NOTE: Typer/rich frames --help with box-drawing glyphs (U+2502 etc.)
    # that are NOT this command's output -- the repo's cp1252 console guard
    # (main.py stdout.reconfigure errors='replace') handles those at the
    # real console. The cp1252-safety of *this command's own status lines*
    # is asserted by the case (a)-(d) runs above (result.output.isascii()).
    # Here we only assert the docstring content is present.
    assert "SPCP1" in result.output
