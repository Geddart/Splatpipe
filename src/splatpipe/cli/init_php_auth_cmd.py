"""``splatpipe init-php-auth`` -- provision a per-scene PHP-save bearer token.

The Phase 1 PHP-save rollout introduces a per-scene bearer token that
authenticates the keyframe-editor's "Save" button against
``save-camera.php``. The split (per the locked Q4 trade-off in
``docs/superpowers/specs/2026-05-20-editor-arc-design.md`` §7.9 +
§11.4) is:

  * The **raw 32-hex-char token** lives ONLY in the operator's
    password manager + in the bookmark URL fragment
    (``#token=<token>``). It is NEVER at rest on the server, NEVER
    in any committed file, NEVER in any log.
  * Only the **lowercase hex SHA-256 hash** of the token is uploaded
    to the server, at ``<remote-base>/<slug>/.author-token``. The PHP
    adapter (``infra/php/save-camera.php:181-196``) accepts hash-or-raw
    via ``hash_equals`` -- so an attacker who steals the on-disk file
    cannot replay the token.

This command is the operator-side provisioner: it generates a fresh
token via ``secrets.token_hex(16)``, computes the sha256 hash, SFTP-
uploads the hash, and prints the raw token + bookmark URL to the
console ONCE.

A second run on the same slug REPLACES the prior hash (server stores
only the latest). Without ``--force`` the CLI prompts ``overwrite?
[y/N]`` to avoid casual rotation mistakes; ``--force`` skips the prompt.

The SFTP creds come from ``002_geddart_relaunch/.env`` (sibling project
on this workspace) -- the same file the existing geddart deploy scripts
read. Credentials are NEVER baked anywhere in the splatpipe repo.

Pattern mirrors ``set_camera_path_cmd`` for ASCII status output (the
repo's CLI is cp1252-safe: plain text, no Unicode glyphs/emoji).
"""

from __future__ import annotations

import hashlib
import re
import secrets
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

console = Console()

# Slug charset locked across the codebase: matches the PHP regex at
# ``infra/php/save-camera.php:155`` and the §H2-DECISION authoritative
# form. This also blocks path traversal (no `.`, `/`, `\`, NUL, `..`).
_SLUG_RE = re.compile(r"^[a-z0-9_-]{1,64}$")

# Default save endpoint -- the geddart.de PHP adapter.
_DEFAULT_ENDPOINT = "https://geddart.de/save-camera.php"

# Default remote base path (where ``scenes/<slug>/`` lives on the SFTP host).
_DEFAULT_REMOTE_BASE = "scenes"

# Default Bunny CDN host for the printed bookmark URL.
_DEFAULT_CDN = "https://splatpipe-cdn.b-cdn.net"


def _load_strato_env(env_file: Optional[Path] = None) -> dict[str, str]:
    """Parse ``002_geddart_relaunch/.env`` for SFTP creds.

    Returns a dict with at least ``STRATO_HOST`` / ``STRATO_USER`` /
    ``STRATO_PASSWORD``. Raises ``RuntimeError`` if the file is missing
    or incomplete -- the caller surfaces this to the operator.

    Mirrors the parsing style of the geddart deploy-strato.mjs:
    a tiny line-based KEY=VALUE reader, no dotenv dependency.
    """
    # Locate the .env file. Default path: H:/001_ProjectCache/1000_Coding/
    # 002_geddart_relaunch/.env (same workspace as splatpipe).
    if env_file is None:
        # Walk up from this module to the workspace root.
        # splatpipe/src/splatpipe/cli/init_php_auth_cmd.py
        # → splatpipe/ → 1000_Coding/ → 002_geddart_relaunch/.env
        repo_root = Path(__file__).resolve().parents[3]
        env_file = repo_root.parent / "002_geddart_relaunch" / ".env"
    if not env_file.is_file():
        raise RuntimeError(
            f"Strato .env not found at {env_file} "
            "(set --env to point at the right file)"
        )
    env: dict[str, str] = {}
    raw = env_file.read_text(encoding="utf-8")
    # Strip UTF-8 BOM if present.
    if raw and raw[0] == "﻿":
        raw = raw[1:]
    for line in raw.splitlines():
        m = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$", line)
        if m:
            env[m.group(1)] = m.group(2)
    missing = [k for k in ("STRATO_HOST", "STRATO_USER", "STRATO_PASSWORD")
               if not env.get(k)]
    if missing:
        raise RuntimeError(
            f"Strato .env missing required keys: {', '.join(missing)}"
        )
    return env


class _ParamikoSftpClient:
    """Thin paramiko-backed SFTP client matching the test-seam interface.

    The test seam is intentionally tiny (``connect`` / ``mkdir_p`` /
    ``put_text`` / ``exists`` / ``close``) so tests can replace this
    whole object with an in-memory recorder. paramiko's API is heavier
    (sftp.put / sftp.stat / etc.); this wrapper normalises it.
    """

    def __init__(self):
        self._client = None
        self._sftp = None

    def connect(self, host: str, user: str, password: str, port: int = 22):
        import paramiko  # type: ignore[import-untyped]

        self._client = paramiko.SSHClient()
        self._client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self._client.connect(
            hostname=host, port=port,
            username=user, password=password,
            timeout=30, banner_timeout=30, auth_timeout=30,
        )
        self._sftp = self._client.open_sftp()

    def mkdir_p(self, path: str):
        """Create remote dir + all parents (idempotent), like `mkdir -p`."""
        # paramiko's SFTPClient.mkdir is single-level; replicate `-p` by
        # walking each component.
        assert self._sftp is not None
        parts = [p for p in path.replace("\\", "/").strip("/").split("/") if p]
        cur = "/" if path.startswith("/") else ""
        for p in parts:
            cur = (cur.rstrip("/") + "/" + p) if cur else p
            try:
                self._sftp.stat(cur)
            except IOError:
                self._sftp.mkdir(cur)

    def put_text(self, remote_path: str, content: str):
        """Write text content to a remote file (UTF-8, no BOM)."""
        assert self._sftp is not None
        # Open for write (binary) so paramiko does not transcode.
        with self._sftp.open(remote_path, "wb") as f:
            f.write(content.encode("utf-8"))

    def exists(self, remote_path: str) -> bool:
        assert self._sftp is not None
        try:
            self._sftp.stat(remote_path)
            return True
        except IOError:
            return False

    def close(self):
        if self._sftp is not None:
            try:
                self._sftp.close()
            except Exception:
                pass
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass


def _make_sftp_client():
    """Construct the production SFTP client (paramiko-backed).

    Tests monkeypatch this single factory to inject a recorder; the rest
    of the CLI is paramiko-free.
    """
    return _ParamikoSftpClient()


def init_php_auth(
    scene: str = typer.Option(
        ..., "--scene", "-s",
        help="The scene slug to provision (e.g. 'fehmarn'). "
             "Must match ^[a-z0-9_-]{1,64}$ (the same charset save-camera.php "
             "validates).",
    ),
    endpoint: str = typer.Option(
        _DEFAULT_ENDPOINT, "--endpoint",
        help="The save-camera.php URL the viewer POSTs to. The default is "
             "the geddart.de adapter; override for other hosts.",
    ),
    remote_base: str = typer.Option(
        _DEFAULT_REMOTE_BASE, "--remote-base",
        help="Server-side base path where scenes/<slug>/ lives (default: "
             "'scenes'). May be relative (from the SFTP home) or absolute.",
    ),
    cdn: str = typer.Option(
        _DEFAULT_CDN, "--cdn",
        help="Bunny CDN host for the printed bookmark URL "
             "(default: https://splatpipe-cdn.b-cdn.net).",
    ),
    force: bool = typer.Option(
        False, "--force", "-f",
        help="Skip the overwrite-confirmation prompt (replaces any "
             "existing server-side token hash for this scene).",
    ),
    env_file: Optional[Path] = typer.Option(
        None, "--env",
        help="Path to a .env with STRATO_HOST / STRATO_USER / STRATO_PASSWORD "
             "(default: auto-discover sibling 002_geddart_relaunch/.env).",
    ),
) -> None:
    """Provision a per-scene PHP-save bearer token for save_mode=http.

    Generates a 32-hex-char random token, computes its SHA-256 hash,
    SFTP-uploads ONLY the hash to scenes/<slug>/.author-token on the
    configured host, then prints the raw token + ready-to-bookmark
    URL to the operator's console (ONCE -- the raw token is never at
    rest on the server, and cannot be recovered from it).
    """
    # 1. Validate the slug at the system boundary -- mirrors the PHP
    #    side exactly so the CLI and the server agree on what counts
    #    as a valid scene name. Reject before any SFTP work happens.
    if not _SLUG_RE.match(scene or ""):
        console.print(
            f"[red]Invalid scene slug:[/red] {scene!r} "
            "(must match ^[a-z0-9_-]{1,64}$)"
        )
        raise typer.Exit(1)

    # 2. Generate the bearer token + its sha256 hash. The raw token
    #    is the per-scene secret the operator bookmarks; only the
    #    hash leaves this command (uploaded to the server).
    raw_token = secrets.token_hex(16)              # 32 lowercase hex chars
    token_sha = hashlib.sha256(raw_token.encode("ascii")).hexdigest()

    # 3. Resolve SFTP creds (NEVER baked; loaded from .env).
    try:
        env = _load_strato_env(env_file)
    except RuntimeError as e:
        console.print(f"[red]Could not load Strato .env:[/red] {e}")
        raise typer.Exit(1)

    # 4. Open the SFTP session (test seam: _make_sftp_client).
    sftp = _make_sftp_client()
    try:
        sftp.connect(
            host=env["STRATO_HOST"],
            user=env["STRATO_USER"],
            password=env["STRATO_PASSWORD"],
        )

        # Build the remote path. The leaf scene dir is created via
        # mkdir_p so a first-time scene works on the first run, but the
        # remote_base itself is assumed to exist (the operator picks it).
        remote_base_norm = remote_base.rstrip("/")
        scene_dir = f"{remote_base_norm}/{scene}"
        tok_path = f"{scene_dir}/.author-token"

        # 5. Check for an existing token store; without --force prompt
        #    the operator before overwriting (avoids casual rotation
        #    mistakes). The prompt is plain ASCII for cp1252 consoles.
        if sftp.exists(tok_path) and not force:
            console.print(
                f"  [yellow]A token already exists for scene "
                f"{scene!r}.[/yellow]"
            )
            # typer.confirm prompts with a default of False so empty
            # input (or 'n') aborts.
            try:
                proceed = typer.confirm(
                    "  Overwrite? (the prior token will stop working)",
                    default=False,
                )
            except typer.Abort:
                proceed = False
            if not proceed:
                console.print(
                    "  [yellow]Aborted (existing token kept).[/yellow]"
                )
                raise typer.Exit(1)

        # 6. mkdir -p the scene dir, then write the hash.
        sftp.mkdir_p(scene_dir)
        # The PHP adapter trims the file content before comparing
        # (`trim((string) file_get_contents($tok_path))`); a trailing
        # newline is harmless but we write without one for cleanliness.
        sftp.put_text(tok_path, token_sha)

    finally:
        sftp.close()

    # 7. Print the operator-facing summary (the ONE place the raw
    #    token surfaces -- store it in the password manager NOW).
    #    The bookmark URL MUST be a single-line verbatim string (no
    #    Rich pretty-wrap, no soft-line truncation -- a pipe/redirect
    #    must get the exact URL). Use plain ``typer.echo`` for the URL
    #    line so Rich's terminal-width awareness does not chop it; the
    #    rest still goes through Rich for the colourised status.
    bookmark_url = f"{cdn.rstrip('/')}/{scene}/?author=1#token={raw_token}"
    console.print()
    console.print(f"  Scene:        [cyan]{scene}[/cyan]")
    console.print(f"  Author token: [bold]{raw_token}[/bold]  (32 hex chars)")
    typer.echo(f"  Bookmark URL: {bookmark_url}")
    console.print()
    console.print(
        f"  Stored on server as sha256 hash at: {tok_path}"
    )
    console.print(
        "  (htaccess-denied; raw token never at rest -- cannot be recovered)"
    )
    console.print()
    console.print(
        "  [bold yellow]Save this token in your password manager NOW.[/bold yellow]"
    )
    typer.echo(f"  Save endpoint: {endpoint}")
