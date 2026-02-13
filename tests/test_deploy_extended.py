"""Extended tests for deploy module: load_bunny_env, deploy_to_bunny, upload_file."""

from unittest.mock import patch, MagicMock
from urllib.error import HTTPError


from splatpipe.steps.deploy import load_bunny_env, deploy_to_bunny, upload_file
from splatpipe.core.events import ProgressEvent


def _consume_generator(gen):
    """Consume a generator, collecting events and returning the final result."""
    events = []
    try:
        while True:
            events.append(next(gen))
    except StopIteration as e:
        return events, e.value


class TestLoadBunnyEnv:
    def test_single_env_file(self, tmp_path):
        """Loads credentials from a single .env file."""
        env_file = tmp_path / ".env"
        env_file.write_text(
            "BUNNY_STORAGE_ZONE=my-zone\n"
            "BUNNY_STORAGE_PASSWORD=secret123\n"
            "BUNNY_CDN_URL=https://cdn.example.com\n"
        )
        env = load_bunny_env(env_file)
        assert env["BUNNY_STORAGE_ZONE"] == "my-zone"
        assert env["BUNNY_STORAGE_PASSWORD"] == "secret123"
        assert env["BUNNY_CDN_URL"] == "https://cdn.example.com"

    def test_first_existing_wins(self, tmp_path):
        """When multiple paths given, first existing file wins."""
        first = tmp_path / "first.env"
        second = tmp_path / "second.env"
        first.write_text("BUNNY_STORAGE_ZONE=first\nBUNNY_STORAGE_PASSWORD=pw1\n")
        second.write_text("BUNNY_STORAGE_ZONE=second\nBUNNY_STORAGE_PASSWORD=pw2\n")
        env = load_bunny_env(first, second)
        assert env["BUNNY_STORAGE_ZONE"] == "first"

    def test_skips_missing_files(self, tmp_path):
        """Missing first file, loads second."""
        missing = tmp_path / "nope.env"
        real = tmp_path / "real.env"
        real.write_text("BUNNY_STORAGE_ZONE=real\nBUNNY_STORAGE_PASSWORD=pw\n")
        env = load_bunny_env(missing, real)
        assert env["BUNNY_STORAGE_ZONE"] == "real"

    def test_env_var_fallback(self, tmp_path, monkeypatch):
        """Falls back to environment variables when .env missing."""
        monkeypatch.setenv("BUNNY_STORAGE_ZONE", "env-zone")
        monkeypatch.setenv("BUNNY_STORAGE_PASSWORD", "env-pw")
        env = load_bunny_env(tmp_path / "nonexistent.env")
        assert env["BUNNY_STORAGE_ZONE"] == "env-zone"
        assert env["BUNNY_STORAGE_PASSWORD"] == "env-pw"

    def test_partial_env_file_plus_env_var(self, tmp_path, monkeypatch):
        """File provides some keys, env vars fill in the rest."""
        env_file = tmp_path / ".env"
        env_file.write_text("BUNNY_STORAGE_ZONE=file-zone\n")
        monkeypatch.setenv("BUNNY_STORAGE_PASSWORD", "env-pw")
        env = load_bunny_env(env_file)
        assert env["BUNNY_STORAGE_ZONE"] == "file-zone"
        assert env["BUNNY_STORAGE_PASSWORD"] == "env-pw"

    def test_comments_and_blanks_ignored(self, tmp_path):
        """Comments and blank lines in .env are skipped."""
        env_file = tmp_path / ".env"
        env_file.write_text(
            "# This is a comment\n"
            "\n"
            "BUNNY_STORAGE_ZONE=zone\n"
            "   # another comment\n"
            "BUNNY_STORAGE_PASSWORD=pw\n"
        )
        env = load_bunny_env(env_file)
        assert env["BUNNY_STORAGE_ZONE"] == "zone"
        assert env["BUNNY_STORAGE_PASSWORD"] == "pw"

    def test_none_path_skipped(self):
        """None paths are safely skipped."""
        env = load_bunny_env(None, None)
        # No crash, returns whatever env vars provide (likely empty)
        assert isinstance(env, dict)


class TestDeployToBunnyValidation:
    def test_missing_credentials(self, tmp_path):
        """Missing credentials returns failure result."""
        output = tmp_path / "output"
        output.mkdir()
        (output / "file.txt").write_text("data")
        events, result = _consume_generator(
            deploy_to_bunny("proj", output, {})
        )
        assert result.success is False
        assert "BUNNY_STORAGE_ZONE" in result.error

    def test_empty_output_dir(self, tmp_path):
        """Empty output dir returns failure result."""
        output = tmp_path / "output"
        output.mkdir()
        env = {"BUNNY_STORAGE_ZONE": "zone", "BUNNY_STORAGE_PASSWORD": "pw"}
        events, result = _consume_generator(
            deploy_to_bunny("proj", output, env)
        )
        assert result.success is False
        assert "No files" in result.error


class TestUploadFile:
    def test_success(self, tmp_path):
        """Successful upload returns (path, True, status)."""
        f = tmp_path / "test.bin"
        f.write_bytes(b"hello")
        mock_resp = MagicMock()
        mock_resp.status = 201
        with patch("splatpipe.steps.deploy.urlopen", return_value=mock_resp):
            path, success, detail = upload_file("zone", "pw", "proj/test.bin", f)
        assert success is True
        assert "201" in detail

    def test_http_error(self, tmp_path):
        """HTTP error returns (path, False, error detail)."""
        f = tmp_path / "test.bin"
        f.write_bytes(b"hello")
        err = HTTPError("http://test", 403, "Forbidden", {}, None)
        with patch("splatpipe.steps.deploy.urlopen", side_effect=err):
            path, success, detail = upload_file("zone", "pw", "proj/test.bin", f)
        assert success is False
        assert "403" in detail


class TestDeployToBunnyWithMock:
    def test_upload_progress_events(self, tmp_path):
        """deploy_to_bunny yields progress events during upload."""
        output = tmp_path / "output"
        output.mkdir()
        (output / "a.txt").write_text("file_a")
        (output / "b.txt").write_text("file_b")

        env = {
            "BUNNY_STORAGE_ZONE": "zone",
            "BUNNY_STORAGE_PASSWORD": "pw",
            "BUNNY_CDN_URL": "https://cdn.example.com",
        }

        mock_resp = MagicMock()
        mock_resp.status = 201
        with patch("splatpipe.steps.deploy.urlopen", return_value=mock_resp):
            events, result = _consume_generator(
                deploy_to_bunny("testproj", output, env, workers=1)
            )

        assert result.success is True
        assert result.summary["uploaded"] == 2
        assert result.summary["failed"] == 0
        assert "cdn.example.com" in result.summary["cdn_url"]
        # Initial event + 2 per-file events
        assert len(events) >= 3
        assert all(isinstance(e, ProgressEvent) for e in events)
