"""Tests for the ``splatpipe init-php-auth`` CLI (Phase 1 §1a).

The Phase 1 PHP-save rollout adds one new CLI command:

    splatpipe init-php-auth --scene <slug> [--endpoint <url>]
                            [--remote-base <path>] [--force] [--env <file>]

What it does (per the locked Q4 decision +
``docs/superpowers/specs/2026-05-20-editor-arc-design.md`` §7.9):

  1. Generate a 32-hex-char random token via ``secrets.token_hex(16)``.
  2. Compute ``sha256(token).hexdigest()`` (lowercase hex).
  3. SFTP-upload the **hash** to ``<remote-base>/<slug>/.author-token``
     on the configured host (creds from ``002_geddart_relaunch/.env``).
  4. Print the raw token + bookmark URL to the operator's console ONCE.
  5. Idempotent: a second run REPLACES the prior hash (server stores only
     the latest). The CLI prompts ``overwrite? [y/N]`` -- bypass via
     ``--force``.

The raw token is the per-scene bearer that lives ONLY in the URL fragment
(``#token=<token>``); ONLY the hash sits on the server (the live PHP
adapter at ``infra/php/save-camera.php:181-196`` accepts hash-or-raw via
``hash_equals``, so no PHP change is needed for the hash form).

These tests mock the SFTP layer (no real network), assert the printed
output shape, token randomness/format, sha256 correctness, slug-charset
validation, and the ``--force`` / overwrite-prompt behaviour. Pattern
mirrors ``tests/test_set_camera_path.py`` (``typer.testing.CliRunner`` +
the shared ``splatpipe.cli.main.app``).
"""

from __future__ import annotations

import hashlib
import re

import pytest
from typer.testing import CliRunner

from splatpipe.cli.main import app

runner = CliRunner()

# Strip SGR/ANSI colour escapes so substring asserts on `--help` output are
# robust to whether Rich colourises (CI/TTY) or not (Windows runner, no
# colour). Typer+Rich highlights option flags like ``--scene`` with a colour
# escape INSIDE the token (``-\x1b[1;36m-scene\x1b[0m``), which splits the
# literal ``--scene`` substring when colour is on -- the green-on-Windows /
# red-on-ubuntu split that broke this test in CI. Stripping first makes the
# check deterministic on every platform.
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


# 32 lowercase hex chars (`secrets.token_hex(16)`).
TOKEN_RE = re.compile(r"^[0-9a-f]{32}$")

# Match: sha256 hex of a 32-char hex token = 64 lowercase hex.
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class _FakeSftp:
    """In-memory SFTP recorder.

    Records every `put_text`/`mkdir_p`/`exists` call so a test can assert
    what the CLI wrote and where, without touching the network. The CLI
    seam is the module-level ``_sftp_put_text`` / ``_sftp_exists`` / etc.
    helpers in ``init_php_auth_cmd``.
    """

    def __init__(self, preexisting: dict[str, str] | None = None):
        self.files: dict[str, str] = dict(preexisting or {})
        self.dirs_created: list[str] = []
        self.host: str | None = None
        self.user: str | None = None
        # The CLI must never log the password.
        self.password: str | None = None
        self.connected = False
        self.disconnected = False

    def connect(self, host: str, user: str, password: str, port: int = 22):
        self.host = host
        self.user = user
        self.password = password
        self.connected = True

    def mkdir_p(self, path: str):
        # Allow idempotent calls (mirrors `mkdir -p`).
        if path not in self.dirs_created:
            self.dirs_created.append(path)

    def put_text(self, remote_path: str, content: str):
        self.files[remote_path] = content

    def exists(self, remote_path: str) -> bool:
        return remote_path in self.files

    def close(self):
        self.disconnected = True


@pytest.fixture
def fake_sftp_factory(monkeypatch):
    """Return a callable that installs a fresh ``_FakeSftp`` into the CLI
    seam and returns the instance for inspection.

    The CLI module exposes one factory function, ``_make_sftp_client``,
    that the production code calls once per invocation; tests replace it
    with a lambda that returns the recorder instance.
    """
    def _install(preexisting: dict[str, str] | None = None) -> _FakeSftp:
        sftp = _FakeSftp(preexisting=preexisting)
        monkeypatch.setattr(
            "splatpipe.cli.init_php_auth_cmd._make_sftp_client",
            lambda: sftp,
        )
        # And neutralise the env lookup so tests never read a real .env.
        monkeypatch.setattr(
            "splatpipe.cli.init_php_auth_cmd._load_strato_env",
            lambda env_file=None: {
                "STRATO_HOST": "fake.host",
                "STRATO_USER": "fake_user",
                "STRATO_PASSWORD": "fake_pw",
            },
        )
        return sftp
    return _install


# ---------------------------------------------------------------------------
# Help / registration smoke tests
# ---------------------------------------------------------------------------
def test_help_lists_command():
    """The init-php-auth subcommand is registered on the shared app."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    # ANSI-robust: command names are not split by Rich today, but stripping
    # keeps every help-text substring check uniform + future-proof.
    assert "init-php-auth" in _strip_ansi(result.output)


def test_command_help_text_documents_scene_arg():
    result = runner.invoke(app, ["init-php-auth", "--help"])
    assert result.exit_code == 0
    # Strip ANSI first: Rich injects a colour escape INSIDE the ``--scene``
    # flag when colour is on (CI/ubuntu), splitting the literal substring.
    clean = _strip_ansi(result.output)
    # The headline doc string should call out the scene slug, the
    # bookmark URL contract, and the password-manager hint.
    assert "--scene" in clean
    assert "token" in clean.lower()


# ---------------------------------------------------------------------------
# --scene is required + slug-charset validation matches the PHP side
# ---------------------------------------------------------------------------
def test_missing_scene_arg_is_rejected(fake_sftp_factory):
    sftp = fake_sftp_factory()
    result = runner.invoke(app, ["init-php-auth"])
    # Typer's "missing required option" path => exit != 0, no SFTP
    # connection was opened.
    assert result.exit_code != 0
    assert sftp.connected is False


@pytest.mark.parametrize(
    "bad_slug",
    [
        "Fehmarn",          # uppercase rejected (mirrors PHP regex)
        "fehmarn slug",     # space
        "fehmarn/sub",      # path-traversal vector
        "../etc",           # ditto
        "fehmarn.evil",     # dot
        "",                 # empty
        "a" * 65,           # over 64-char cap
    ],
)
def test_bad_slug_rejected_no_sftp(bad_slug, fake_sftp_factory):
    """The CLI's slug-charset validation MUST mirror the PHP side
    (``^[a-z0-9_-]{1,64}$`` per ``infra/php/save-camera.php:155``).
    A bad slug exits non-zero BEFORE any SFTP work."""
    sftp = fake_sftp_factory()
    result = runner.invoke(app, ["init-php-auth", "--scene", bad_slug, "--force"])
    assert result.exit_code != 0
    assert sftp.connected is False
    # Helpful error message names the constraint or the slug.
    assert "slug" in result.output.lower() or "scene" in result.output.lower()


@pytest.mark.parametrize(
    "good_slug",
    ["fehmarn", "polygraf-east", "stettiner_test", "a", "0", "abc123"],
)
def test_good_slug_accepted(good_slug, fake_sftp_factory):
    """All slugs that match ``^[a-z0-9_-]{1,64}$`` are accepted."""
    sftp = fake_sftp_factory()
    result = runner.invoke(
        app, ["init-php-auth", "--scene", good_slug, "--force"]
    )
    assert result.exit_code == 0, result.output
    assert sftp.connected is True


# ---------------------------------------------------------------------------
# Token generation: format + randomness + sha256 correctness
# ---------------------------------------------------------------------------
def test_generated_token_is_32_hex(fake_sftp_factory):
    """The CLI prints exactly one 32-hex-char token (lowercase) and
    uploads ONLY the sha256 hash to the server."""
    sftp = fake_sftp_factory()
    result = runner.invoke(
        app, ["init-php-auth", "--scene", "fehmarn", "--force"]
    )
    assert result.exit_code == 0, result.output

    # The 32-hex token appears in the printed output; pluck it.
    m = re.search(r"\b([0-9a-f]{32})\b", result.output)
    assert m is not None, f"no 32-hex token in:\n{result.output}"
    raw_token = m.group(1)
    assert TOKEN_RE.match(raw_token)

    # The server-side store holds the SHA256 hash of that token, NOT
    # the raw token. Path is /scenes/<slug>/.author-token.
    assert "scenes/fehmarn/.author-token" in sftp.files
    stored = sftp.files["scenes/fehmarn/.author-token"].strip()
    assert SHA256_RE.match(stored)
    assert stored == hashlib.sha256(raw_token.encode("ascii")).hexdigest()


def test_two_runs_generate_different_tokens(fake_sftp_factory):
    """Sanity: ``secrets.token_hex(16)`` is random; two invocations
    produce distinct tokens (probability of collision = 2^-128)."""
    # The factory side-effect (monkeypatching the seam) is the
    # contract here -- we don't need to inspect the recorder.
    fake_sftp_factory()
    r1 = runner.invoke(app, ["init-php-auth", "--scene", "fehmarn", "--force"])
    t1 = re.search(r"\b([0-9a-f]{32})\b", r1.output).group(1)

    fake_sftp_factory()
    r2 = runner.invoke(app, ["init-php-auth", "--scene", "fehmarn", "--force"])
    t2 = re.search(r"\b([0-9a-f]{32})\b", r2.output).group(1)

    assert t1 != t2


# ---------------------------------------------------------------------------
# Printed output: bookmark URL + password-manager hint + slug context
# ---------------------------------------------------------------------------
def test_printed_output_includes_bookmark_url(fake_sftp_factory):
    fake_sftp_factory()
    result = runner.invoke(
        app, ["init-php-auth", "--scene", "fehmarn", "--force"]
    )
    assert result.exit_code == 0
    out = result.output

    # The bookmark URL is the user's ONE artifact to save. It must be
    # printed verbatim with the #token= fragment and ?author=1 query.
    m = re.search(r"\b([0-9a-f]{32})\b", out)
    raw_token = m.group(1)
    assert "?author=1" in out
    assert f"#token={raw_token}" in out

    # The slug must appear too (operator wants visual confirmation).
    assert "fehmarn" in out

    # The output reminds the operator the raw token is one-shot.
    lowered = out.lower()
    assert "password manager" in lowered or "save" in lowered or "now" in lowered


def test_output_warns_raw_token_not_at_rest(fake_sftp_factory):
    """The printed output must clearly tell the operator that the raw
    token is NOT recoverable from the server (sha256 hash only)."""
    fake_sftp_factory()
    result = runner.invoke(
        app, ["init-php-auth", "--scene", "fehmarn", "--force"]
    )
    assert result.exit_code == 0
    out_lowered = result.output.lower()
    # Either explicit "sha256" mention OR "never at rest" / "cannot be
    # recovered" -- something that conveys the irreversibility.
    assert (
        "sha256" in out_lowered
        or "hash" in out_lowered
        or "cannot be recovered" in out_lowered
        or "not at rest" in out_lowered
        or "never at rest" in out_lowered
    )


# ---------------------------------------------------------------------------
# Overwrite prompt + --force
# ---------------------------------------------------------------------------
def test_force_overwrites_existing_without_prompt(fake_sftp_factory):
    """``--force`` skips the overwrite prompt and replaces the hash."""
    # Pre-existing hash on the server.
    sftp = fake_sftp_factory(
        preexisting={"scenes/fehmarn/.author-token": "a" * 64}
    )
    result = runner.invoke(
        app, ["init-php-auth", "--scene", "fehmarn", "--force"]
    )
    assert result.exit_code == 0, result.output
    # Hash replaced with a fresh value.
    new_hash = sftp.files["scenes/fehmarn/.author-token"]
    assert new_hash != "a" * 64
    assert SHA256_RE.match(new_hash)


def test_existing_token_no_force_aborts_with_no_input(fake_sftp_factory):
    """Without ``--force``, an existing token store triggers a
    confirmation; declining (``n`` or empty) aborts the write."""
    sftp = fake_sftp_factory(
        preexisting={"scenes/fehmarn/.author-token": "a" * 64}
    )
    # Pipe "n" + newline to the typer.confirm()
    result = runner.invoke(
        app, ["init-php-auth", "--scene", "fehmarn"], input="n\n"
    )
    assert result.exit_code != 0
    # Server-side hash UNCHANGED (confirm-declined aborts write).
    assert sftp.files["scenes/fehmarn/.author-token"] == "a" * 64


def test_existing_token_no_force_confirm_yes_overwrites(fake_sftp_factory):
    """``y`` at the confirmation prompt does proceed with the overwrite."""
    sftp = fake_sftp_factory(
        preexisting={"scenes/fehmarn/.author-token": "a" * 64}
    )
    result = runner.invoke(
        app, ["init-php-auth", "--scene", "fehmarn"], input="y\n"
    )
    assert result.exit_code == 0, result.output
    new_hash = sftp.files["scenes/fehmarn/.author-token"]
    assert new_hash != "a" * 64
    assert SHA256_RE.match(new_hash)


# ---------------------------------------------------------------------------
# Remote path + directory creation
# ---------------------------------------------------------------------------
def test_creates_scene_dir_via_mkdir_p(fake_sftp_factory):
    """The CLI does ``mkdir -p`` on the scene dir BEFORE writing the
    token file (idempotent: a fresh scene with no parent dir works on
    the first run)."""
    sftp = fake_sftp_factory()
    result = runner.invoke(
        app, ["init-php-auth", "--scene", "fehmarn", "--force"]
    )
    assert result.exit_code == 0
    # Each path component appears as a created dir (loose check: at
    # least the leaf scene dir is created).
    assert any("fehmarn" in d for d in sftp.dirs_created), sftp.dirs_created


def test_custom_remote_base_used(fake_sftp_factory):
    """``--remote-base /custom/base/`` is respected for the token path."""
    sftp = fake_sftp_factory()
    result = runner.invoke(
        app,
        [
            "init-php-auth",
            "--scene", "fehmarn",
            "--remote-base", "/custom/base",
            "--force",
        ],
    )
    assert result.exit_code == 0, result.output
    # Either /custom/base/fehmarn/.author-token or custom/base/fehmarn/... is
    # acceptable (some sftp libs treat absolute vs relative differently).
    keys = list(sftp.files.keys())
    assert any("custom/base/fehmarn/.author-token" in k for k in keys), keys


def test_custom_endpoint_in_bookmark_url(fake_sftp_factory):
    """``--endpoint`` does NOT change the bookmark URL (the bookmark is
    the AUTHOR URL on the CDN, not the save endpoint), but it MAY
    surface in the printed output for the operator's reference."""
    fake_sftp_factory()
    result = runner.invoke(
        app,
        [
            "init-php-auth",
            "--scene", "fehmarn",
            "--endpoint", "https://example.com/save.php",
            "--force",
        ],
    )
    assert result.exit_code == 0, result.output


# ---------------------------------------------------------------------------
# Secrets discipline: the password / raw token must NOT leak into logs
# ---------------------------------------------------------------------------
def test_password_not_in_printed_output(fake_sftp_factory):
    """The Strato SFTP password must NEVER appear in the printed output;
    the CLI should NOT log creds even at the highest verbosity."""
    fake_sftp_factory()
    result = runner.invoke(
        app, ["init-php-auth", "--scene", "fehmarn", "--force"]
    )
    assert result.exit_code == 0
    assert "fake_pw" not in result.output


def test_idempotent_run_with_force(fake_sftp_factory):
    """Two consecutive ``--force`` runs both succeed; the second replaces
    the first hash (overwrite is the documented behaviour)."""
    # First run creates the token store.
    sftp = fake_sftp_factory()
    r1 = runner.invoke(app, ["init-php-auth", "--scene", "fehmarn", "--force"])
    assert r1.exit_code == 0
    h1 = sftp.files["scenes/fehmarn/.author-token"]
    assert SHA256_RE.match(h1)

    # Second run replaces the hash (different token).
    sftp2 = fake_sftp_factory(preexisting={"scenes/fehmarn/.author-token": h1})
    r2 = runner.invoke(app, ["init-php-auth", "--scene", "fehmarn", "--force"])
    assert r2.exit_code == 0
    h2 = sftp2.files["scenes/fehmarn/.author-token"]
    assert SHA256_RE.match(h2)
    assert h1 != h2


# ---------------------------------------------------------------------------
# ASCII output discipline (cp1252 console safety mirrors set-camera-path)
# ---------------------------------------------------------------------------
def test_output_is_ascii_for_status_lines(fake_sftp_factory):
    """The CLI's own status/printed output must be ASCII-only so it does
    not break on a non-UTF-8 (cp1252) console. (rich/typer's --help may
    inject box-drawing glyphs at the framework level; this test runs the
    REAL command, not --help.)"""
    fake_sftp_factory()
    result = runner.invoke(
        app, ["init-php-auth", "--scene", "fehmarn", "--force"]
    )
    assert result.exit_code == 0
    assert result.output.isascii(), (
        "non-ASCII glyph in status output -- "
        f"{[c for c in result.output if ord(c) >= 0x80][:5]}"
    )
