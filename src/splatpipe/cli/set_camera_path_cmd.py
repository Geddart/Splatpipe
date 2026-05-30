"""splatpipe set-camera-path -- apply a viewer-emitted camera-path token.

The deployed Spark viewers are static files on Bunny CDN with no backend
(and the storage key must never live in client JS). The viewer's keyframe
editor "Save" button therefore only *emits* an ``SPCP1`` token; this
command is the trusted, author-facing side of the decision-A DEFAULT save
path. It is a THIN faithful wrapper over two already-built, separately
tested pieces:

  * :func:`splatpipe.core.spcp_token.decode_spcp` -- parse
    ``SPCP1:<slug>:<b64url>`` into ``(slug, payload)`` (Task 3).
  * :class:`splatpipe.save_backends.cli.CliRelayBackend` -- fetch the
    scene's live ``viewer-config.json``, ``merge_camera_scope`` the patch
    onto it (``primary_asset`` force-kept, non-allow-listed keys dropped),
    and write it via the configured ``DeployTarget`` (Task 6a).

It reimplements NONE of the decode / merge / deploy logic -- it only wires
them together and prints an ASCII status (the repo's CLI output is
cp1252-safe: plain text + ASCII rich-markup tags, no Unicode glyphs/emoji,
mirroring ``set_start_view_cmd``).

This command is ALWAYS available and is the documented escape hatch for
any ``save_mode`` when the editor cannot POST directly -- payloads over
the 256 KB browser limit, an offline author, or CI (per the §H2-DECISION).

See also ``cli/set_start_view_cmd.py`` (the proven sibling relay) and
docs/plans/2026-05-18-camera-keyframe-editor-implementation.md.
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from ..core.config import load_defaults, load_project_config
from ..core.spcp_token import SpcpError, decode_spcp
from ..save_backends.registry import get_save_backend

console = Console()


def set_camera_path(
    token: str = typer.Argument(
        ..., help="The SPCP1 token emitted by the viewer's keyframe-editor "
                  "'Save' button (SPCP1:<slug>:<data>)."
    ),
    project_path: Path = typer.Option(
        None, "--project-path", "-p",
        help="Local project dir whose config (save_backend.deploy_target) "
             "selects how/where to write. Defaults to the global config.",
    ),
    env_file: Path = typer.Option(
        None, "--env",
        help="Path to .env with Bunny creds (default: auto-discover).",
    ),
) -> None:
    """Decode a viewer camera-path token and save it for everyone.

    Relays the editor's SPCP1 token through the configured ``cli`` save
    backend: fetch the scene's live viewer-config.json, merge the camera
    scope onto it (primary_asset force-kept), and redeploy it via the
    configured DeployTarget. ALWAYS available -- the over-256KB / offline
    / CI escape for any save_mode.
    """
    # 1. Decode the untrusted token at the system boundary. A malformed /
    #    non-SPCP1 token is a clear, ASCII user error -> non-zero exit.
    try:
        slug, payload = decode_spcp(token)
    except SpcpError as e:
        console.print(f"[red]Not a valid SPCP1 camera-path token:[/red] {e}")
        raise typer.Exit(1)

    n_paths = len(payload.get("camera_paths") or [])
    default_path = payload.get("default_path_id")
    console.print(f"[bold]Camera paths[/bold] for [cyan]{slug}[/cyan]")
    console.print(
        f"  paths={n_paths}  default_path_id={default_path!r}"
    )

    # 2. Load the merged config. With a --project-path use that project's
    #    project.toml merged over defaults (so its save_backend /
    #    deploy_target wins); standalone -> the global defaults. The cli
    #    backend reads save_backend.deploy_target (default bunny) and
    #    resolves Bunny creds itself via load_bunny_env.
    if project_path is not None:
        if not project_path.exists():
            console.print(
                f"[red]Project path not found:[/red] {project_path}"
            )
            raise typer.Exit(1)
        config = load_project_config(project_path / "project.toml")
    else:
        config = load_defaults()

    # 3. Construct the cli save backend via the registry (same idiom as
    #    the trainer / deploy-target registries) and relay slug+payload to
    #    it. The fetch -> merge_camera_scope -> deploy is entirely the
    #    backend's job; this command adds NO save logic. (env_file is
    #    accepted for parity with set-start-view; CliRelayBackend._bunny_env()
    #    auto-discovers .env via the module-level load_bunny_env -- it is not
    #    re-plumbed here so the deploy stays byte-identical to publish.)
    backend = get_save_backend("cli", config)
    result = backend.save_keyframes(slug, payload, token)

    # 4. Surface an ASCII status from the SaveResult. ignored_keys is the
    #    Task-4 carry-forward: keys merge_camera_scope silently dropped --
    #    informational, NOT an error (a success with ignored keys is a
    #    normal outcome). Never echo the token or any secret.
    if result.ignored_keys:
        console.print(
            "  [yellow]ignored non-camera keys:[/yellow] "
            + ", ".join(result.ignored_keys)
        )

    if not result.success:
        console.print(
            f"[red]Save failed:[/red] {result.error or 'unknown error'}"
        )
        raise typer.Exit(1)

    if result.message:
        console.print(f"  [green]{result.message}[/green]")
    console.print(
        f"[bold green]Camera paths saved for {result.slug}.[/bold green]"
    )
