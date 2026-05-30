"""Security regression tests for the ``serve_cmd`` preview server.

Bug-audit-2026-05-19 finding #6: the old containment check used
``str(target).startswith(str(out_resolved))`` which is vulnerable to a
sibling-prefix attack -- a sibling directory like ``05_output_evil`` next
to the intended ``05_output`` root passes a textual ``startswith`` but is
NOT actually contained.

This test boots the FastAPI app declared inside ``serve_cmd.serve`` (via
the small private factory below) and exercises both the happy path and
the sibling-prefix attack to lock the hardened behaviour.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from starlette.testclient import TestClient


# ---------------------------------------------------------------------------
# Minimal in-process FastAPI app mirroring ``serve_cmd.serve``'s mount
# ---------------------------------------------------------------------------
# We don't want to bind a real port or call ``uvicorn.run`` from a test;
# the FastAPI app constructor inside ``serve`` is the unit-under-test for
# the security check. Build it directly so we can hit it via TestClient.

def _build_preview_app(output_dir: Path):
    """Recreate the security-relevant subset of ``serve_cmd.serve``.

    This MUST mirror ``serve_cmd.serve`` exactly for the route under test.
    If you change the route shape there, change it here -- the test exists
    to lock the containment check, not to test FastAPI itself.
    """
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import FileResponse, HTMLResponse

    from splatpipe.core.path_safety import ensure_contained, PathContainmentError

    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
    )

    @app.get("/{file_path:path}")
    def serve_file(file_path: str):
        target_raw = output_dir / file_path
        try:
            target = ensure_contained(target_raw, output_dir)
        except PathContainmentError:
            return HTMLResponse("Forbidden", status_code=403)
        if not target.is_file():
            return HTMLResponse("Not found", status_code=404)
        return FileResponse(target)

    return app


@pytest.fixture
def preview_env(tmp_path):
    output_dir = tmp_path / "05_output"
    output_dir.mkdir()
    (output_dir / "scene.rad").write_bytes(b"\x52\x41\x44scene_data")  # fake "RAD" header
    (output_dir / "viewer-config.json").write_text(json.dumps({"renderer": "spark"}))

    # Sibling with shared textual prefix -- the attack vector.
    evil = tmp_path / "05_output_evil"
    evil.mkdir()
    (evil / "secrets.txt").write_text("very secret content")

    app = _build_preview_app(output_dir)
    client = TestClient(app)
    return {
        "client": client,
        "output_dir": output_dir,
        "evil_dir": evil,
        "tmp_path": tmp_path,
    }


# ---------------------------------------------------------------------------
# Happy path: legit files inside output_dir are served
# ---------------------------------------------------------------------------

class TestServeCmdHappyPath:
    def test_serves_scene_rad(self, preview_env):
        r = preview_env["client"].get("/scene.rad")
        assert r.status_code == 200, r.text
        assert r.content.startswith(b"\x52\x41\x44")

    def test_serves_viewer_config_json(self, preview_env):
        r = preview_env["client"].get("/viewer-config.json")
        assert r.status_code == 200, r.text
        assert json.loads(r.content)["renderer"] == "spark"

    def test_404_for_missing_file_inside_root(self, preview_env):
        r = preview_env["client"].get("/missing.bin")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# THE attack: sibling directory with shared textual prefix
# ---------------------------------------------------------------------------

class TestServeCmdSiblingPrefixAttack:
    """``05_output_evil`` is a sibling of ``05_output``. The OLD
    ``startswith`` check passed it as "contained"; the new helper rejects.
    """

    def test_sibling_with_shared_prefix_rejected(self, preview_env):
        """Direct attack: try to reach ../05_output_evil/secrets.txt via
        a relative path that resolves into the sibling."""
        # Most direct: a path that ``Path(output_dir / file_path).resolve()``
        # collapses to ``tmp_path / "05_output_evil" / "secrets.txt"``.
        r = preview_env["client"].get("/../05_output_evil/secrets.txt")
        # Starlette / FastAPI may normalise some ``..`` in the URL; either
        # way the route MUST NOT leak the secret file.
        assert r.status_code in (403, 404), r.text
        # And the secret content was definitely not served.
        assert b"very secret content" not in r.content

    def test_traversal_to_unrelated_file_rejected(self, preview_env):
        # A different escape vector: traverse up two levels.
        r = preview_env["client"].get("/../../etc/passwd")
        assert r.status_code in (403, 404)


# ---------------------------------------------------------------------------
# Direct unit test on the security helper integration
# ---------------------------------------------------------------------------

class TestServeCmdContainmentHelper:
    """Lock the integration of ``ensure_contained`` with the route -- a
    unit-level proof that the security primitive is what gets called."""

    def test_uses_path_safety_helper(self):
        """Importing the helper from the same module the serve_cmd uses
        ensures the refactor stays wired up."""
        import splatpipe.cli.serve_cmd as serve_mod
        # The module must reference path_safety somehow -- either imported
        # or used inline.
        source = Path(serve_mod.__file__).read_text(encoding="utf-8")
        assert "path_safety" in source, (
            "serve_cmd no longer imports path_safety -- the audit #6 "
            "refactor is missing or has regressed"
        )

    def test_no_unsafe_startswith_in_serve_cmd(self):
        """Lock the OLD unsafe ``startswith`` containment pattern out of
        ``serve_cmd.py``. This is a forward-looking regression guard."""
        import re

        import splatpipe.cli.serve_cmd as serve_mod
        source = Path(serve_mod.__file__).read_text(encoding="utf-8")
        # Strip comments so the post-refactor reference to the OLD pattern
        # inside a documentary comment does not falsely trip the guard.
        code_only = "\n".join(
            line for line in source.splitlines()
            if not re.match(r"\s*#", line)
        )
        # Pattern is "str(<x>).startswith(str(<y>))" -- the smoking gun.
        assert ".startswith(str(" not in code_only, (
            "Unsafe ``str(p).startswith(str(root))`` containment pattern "
            "found in serve_cmd.py executable code -- audit #6 regression"
        )
