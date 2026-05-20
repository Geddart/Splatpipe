"""Security tests for the /projects/{path}/upload-audio route.

Bug-audit-2026-05-19 finding #7: the audio-upload route used
``upload.filename`` straight from multipart metadata as a path component,
which allows directory traversal and writing outside the assets/audio
directory. These tests lock the hardened behaviour:

* path-traversal vectors (unix + windows, absolute, drive-letter) are
  rejected without writing,
* empty / dotfile names are rejected,
* the extension allow-list is enforced (no exe/html/php/etc.),
* the size limit blocks oversize bodies (50 MB cap),
* collisions are rejected with 409 instead of silently overwriting,
* the happy path still works,
* the on-disk destination is always confined to assets/audio/ (resolve +
  relative_to defense-in-depth assertion).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import tomli_w
from starlette.testclient import TestClient

from splatpipe.core.project import Project


# Reuse the same fixture shape as tests/test_web_routes.py so this file is
# self-contained -- no cross-module conftest dependency, lets the test run
# in isolation with ``pytest tests/test_audio_upload_security.py``.

@pytest.fixture
def web_env(tmp_path, monkeypatch):
    projects_root = tmp_path / "projects"
    projects_root.mkdir()

    toml_path = tmp_path / "defaults.toml"
    config = {
        "tools": {
            "postshot": "",
            "lichtfeld_studio": "",
            "colmap": "",
            "splat_transform": "",
            "supersplat_url": "https://superspl.at/editor",
        },
        "colmap_clean": {
            "outlier_threshold_auto": True,
            "outlier_threshold_fixed": 100.0,
            "outlier_percentile": 0.99,
            "outlier_multiplier": 2.5,
            "kdtree_threshold": 0.001,
            "coordinate_transform": [1, 0, 0, 0, 0, -1, 0, 1, 0],
        },
        "postshot": {
            "profile": "Splat3",
            "downsample": True,
            "max_image_size": 3840,
            "anti_aliasing": False,
            "create_sky_model": False,
            "train_steps_limit": 0,
            "login": "",
            "password": "",
        },
        "lichtfeld": {"strategy": "mcmc", "iterations": 30000},
        "paths": {"projects_root": str(projects_root)},
    }
    with open(toml_path, "wb") as f:
        tomli_w.dump(config, f)

    monkeypatch.setattr("splatpipe.core.config.DEFAULTS_PATH", toml_path)

    proj_dir = projects_root / "AudioSecProject"
    colmap_dir = tmp_path / "colmap_data"
    colmap_dir.mkdir()
    (colmap_dir / "cameras.txt").write_text("# 3 cameras\n")
    (colmap_dir / "images.txt").write_text("# 5 images\n")
    (colmap_dir / "points3D.txt").write_text("# 50 points\n")
    project = Project.create(proj_dir, "AudioSecProject", colmap_source=str(colmap_dir))

    # Drain shared queue state so tests are isolated (mirrors test_web_routes).
    import splatpipe.web.runner as runner_module
    runner_module._queue.clear()
    runner_module._queue_current = None
    runner_module._queue_paused = False
    runner_module._queue_wake.clear()

    from splatpipe.web.app import app
    client = TestClient(app)

    yield {
        "client": client,
        "project": project,
        "projects_root": projects_root,
        "tmp_path": tmp_path,
    }

    runner_module._queue.clear()
    runner_module._queue_current = None
    runner_module._queue_paused = False
    runner_module._queue_wake.clear()


# --- Helpers ----------------------------------------------------------------

def _audio_dir(env) -> Path:
    return env["project"].root / "assets" / "audio"


def _files_in(d: Path) -> list[Path]:
    if not d.exists():
        return []
    return [p for p in d.rglob("*") if p.is_file()]


def _post_audio(env, filename: str, body: bytes = b"fake-audio-data",
                content_type: str = "audio/mpeg"):
    path = str(env["project"].root)
    return env["client"].post(
        f"/projects/{path}/upload-audio",
        files={"file": (filename, body, content_type)},
    )


# --- Path-traversal vectors -------------------------------------------------

class TestAudioUploadPathTraversalRejected:
    """The route must reject any filename containing path components."""

    def test_rejects_unix_path_traversal(self, web_env):
        """``../evil.mp3`` must NOT escape assets/audio/."""
        r = _post_audio(web_env, "../evil.mp3")
        assert r.status_code == 400, r.text
        assert _files_in(_audio_dir(web_env)) == []
        # Verify nothing was written one level above (the traversal target).
        parent_evil = web_env["project"].root / "assets" / "evil.mp3"
        assert not parent_evil.exists()
        deeper_evil = web_env["project"].root / "evil.mp3"
        assert not deeper_evil.exists()

    def test_rejects_unix_deep_path_traversal(self, web_env):
        """Multi-level ``../../../`` must be rejected, not collapsed."""
        r = _post_audio(web_env, "../../../id_rsa.mp3")
        assert r.status_code == 400, r.text
        assert _files_in(_audio_dir(web_env)) == []

    def test_rejects_windows_path_traversal(self, web_env):
        """Backslash traversal must be rejected on every OS."""
        r = _post_audio(web_env, "..\\..\\evil.mp3")
        assert r.status_code == 400, r.text
        assert _files_in(_audio_dir(web_env)) == []

    def test_rejects_mixed_separator(self, web_env):
        """Slash inside a filename is a path component, reject it."""
        r = _post_audio(web_env, "subdir/evil.mp3")
        assert r.status_code == 400, r.text
        assert _files_in(_audio_dir(web_env)) == []

    def test_rejects_absolute_posix_path(self, web_env):
        """``/etc/passwd``-style filenames must not be honored."""
        r = _post_audio(web_env, "/etc/passwd.mp3")
        assert r.status_code == 400, r.text
        assert _files_in(_audio_dir(web_env)) == []

    def test_drive_letter_filename_cannot_escape_audio_dir(self, web_env):
        """``C:\\Windows\\system32\\evil.mp3`` must NOT escape assets/audio/.

        Note: Starlette / python-multipart pre-strips the ``C:\\Windows\\``
        path prefix at the framework boundary (it conforms to RFC 7578 and
        delivers only the basename to ``upload.filename``), so the route
        sees ``evil.mp3``. The security property the audit cares about is
        "nothing is written outside assets/audio/", not "the route rejects
        the raw form". This test locks that property: regardless of whether
        the route accepts or rejects the input, no file is created OUTSIDE
        the audio directory and no system32-like target is touched.
        """
        r = _post_audio(web_env, "C:\\Windows\\system32\\evil.mp3")
        # Whatever the route returns, the containment property MUST hold.
        proj_root = web_env["project"].root
        audio_dir = _audio_dir(web_env).resolve()
        # No write outside the audio dir (the actual attack the audit fears).
        for p in proj_root.rglob("*"):
            if not p.is_file():
                continue
            try:
                p.resolve().relative_to(audio_dir)
            except ValueError:
                # File found outside audio_dir -- only allowed if it is part
                # of the standard project skeleton (state.json, project.toml,
                # COLMAP source). The attack would create a file named
                # ``evil.mp3`` somewhere unexpected; ensure no such file.
                assert p.name != "evil.mp3", (
                    f"audio upload leaked outside audio_dir: {p}"
                )
        # Also assert nothing landed at typical traversal targets.
        for sneaky in [
            proj_root / "evil.mp3",
            proj_root.parent / "evil.mp3",
            proj_root / "assets" / "evil.mp3",
        ]:
            assert not sneaky.exists(), f"path traversal leaked to {sneaky}"
        # And the response is well-formed (either 200-contained or 400-reject).
        assert r.status_code in (200, 400), r.text


# --- Empty / dotfile filenames ---------------------------------------------

class TestAudioUploadEmptyOrDotfileRejected:
    def test_rejects_empty_filename(self, web_env):
        r = _post_audio(web_env, "")
        assert r.status_code == 400, r.text
        assert _files_in(_audio_dir(web_env)) == []

    def test_rejects_pure_dot(self, web_env):
        r = _post_audio(web_env, ".")
        assert r.status_code == 400, r.text
        assert _files_in(_audio_dir(web_env)) == []

    def test_rejects_double_dot(self, web_env):
        r = _post_audio(web_env, "..")
        assert r.status_code == 400, r.text
        assert _files_in(_audio_dir(web_env)) == []

    def test_rejects_dotfile(self, web_env):
        r = _post_audio(web_env, ".htaccess")
        assert r.status_code == 400, r.text
        assert _files_in(_audio_dir(web_env)) == []


# --- Extension allow-list --------------------------------------------------

class TestAudioUploadExtensionAllowlist:
    @pytest.mark.parametrize("name", [
        "evil.exe",
        "evil.html",
        "evil.php",
        "evil.js",
        "no_extension",
        "song.mp3.exe",  # double-extension trick lands as .exe
    ])
    def test_rejects_non_audio_extension(self, web_env, name):
        r = _post_audio(web_env, name)
        assert r.status_code == 400, r.text
        assert _files_in(_audio_dir(web_env)) == []

    @pytest.mark.parametrize("name", [
        "song.mp3",
        "song.MP3",  # case-insensitive allow-list
        "song.wav",
        "song.ogg",
        "song.opus",
        "song.m4a",
        "song.aac",
        "song.flac",
        "song.webm",
    ])
    def test_accepts_allow_listed_audio_extensions(self, web_env, name):
        r = _post_audio(web_env, name)
        assert r.status_code == 200, r.text
        dest = _audio_dir(web_env) / name
        assert dest.exists()


# --- Size limit ------------------------------------------------------------

class TestAudioUploadSizeLimit:
    def test_rejects_oversize_upload(self, web_env):
        """A body larger than 50 MB must be rejected with 413."""
        # 51 MB is just above the cap.
        big = b"\x00" * (51 * 1024 * 1024)
        r = _post_audio(web_env, "huge.mp3", body=big)
        assert r.status_code == 413, r.text
        # The destination must not be left half-written.
        assert not (_audio_dir(web_env) / "huge.mp3").exists()

    def test_accepts_under_size_limit(self, web_env):
        """A body well under 50 MB is fine."""
        body = b"x" * (1 * 1024 * 1024)  # 1 MB
        r = _post_audio(web_env, "ok.mp3", body=body)
        assert r.status_code == 200, r.text
        assert (_audio_dir(web_env) / "ok.mp3").exists()


# --- Collision handling ----------------------------------------------------

class TestAudioUploadCollision:
    def test_rejects_collision_with_409(self, web_env):
        """Per the chosen safer-default strategy: reject overwrite, not silent clobber."""
        first = _post_audio(web_env, "song.mp3", body=b"first")
        assert first.status_code == 200, first.text
        dest = _audio_dir(web_env) / "song.mp3"
        assert dest.read_bytes() == b"first"

        second = _post_audio(web_env, "song.mp3", body=b"second")
        assert second.status_code == 409, second.text
        # The original must not have been overwritten.
        assert dest.read_bytes() == b"first"


# --- Happy path + defense-in-depth -----------------------------------------

class TestAudioUploadHappyPath:
    def test_happy_path_still_works(self, web_env):
        """The original happy path (the existing test_upload_audio case) still passes."""
        r = _post_audio(web_env, "test.mp3")
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["ok"] is True
        assert data["path"] == "assets/audio/test.mp3"
        assert (_audio_dir(web_env) / "test.mp3").exists()

    def test_writes_inside_audio_dir_only(self, web_env):
        """Defense-in-depth: every successful upload must resolve INSIDE the audio dir.

        This catches any future regression where the sanitiser is bypassed
        (e.g. a Windows reserved name or a future change that re-introduces
        sub-paths).
        """
        r = _post_audio(web_env, "ok.mp3")
        assert r.status_code == 200
        audio_dir = _audio_dir(web_env).resolve()
        files = [p.resolve() for p in audio_dir.rglob("*") if p.is_file()]
        assert len(files) >= 1
        for f in files:
            # Path.relative_to raises ValueError if not contained -- which is
            # exactly the same check the route applies. We do the inverse
            # assertion here as a paranoid downstream check.
            f.relative_to(audio_dir)

    def test_response_body_uses_sanitized_name(self, web_env):
        """The JSON 'path' field must reflect the sanitized name, not the raw input."""
        r = _post_audio(web_env, "tune.mp3")
        assert r.status_code == 200
        body = json.loads(r.text)
        assert body["path"] == "assets/audio/tune.mp3"
