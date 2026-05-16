"""splatpipe set-start-view — apply a viewer-emitted start-view token.

The deployed Spark viewers are static files on Bunny CDN with no backend
(and the storage key must never live in client JS). The viewer's "Set
start view" button therefore only *emits* a token; this command is the
trusted side of the Option-A relay: it decodes the token and writes a
``start_view`` field into that project's ``viewer-config.json`` on Bunny
(and, if a local project folder is given, into its scene_config so future
re-exports keep it). See docs/plans/2026-05-15_set-start-view.md.
"""

from __future__ import annotations

import base64
import json
import tempfile
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import typer
from rich.console import Console

from ..core.project import Project
from ..steps.deploy import load_bunny_env, purge_bunny_cache, upload_file

console = Console()


def _decode_token(token: str) -> tuple[str, dict]:
    """Parse ``SPV1:<slug>:<base64url(JSON)>`` → (project_name, start_view).

    Raises typer.BadParameter on any malformed input (system boundary).
    """
    token = token.strip().strip('"').strip("'")
    parts = token.split(":", 2)
    if len(parts) != 3 or parts[0] != "SPV1":
        raise typer.BadParameter(
            "Not a start-view token (expected 'SPV1:<slug>:<data>')."
        )
    b64 = parts[2].replace("-", "+").replace("_", "/")
    b64 += "=" * (-len(b64) % 4)  # restore stripped padding
    try:
        payload = json.loads(base64.b64decode(b64).decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        raise typer.BadParameter(f"Token payload is not valid base64/JSON: {e}")

    if not isinstance(payload, dict):
        raise typer.BadParameter("Token payload is not a JSON object.")
    project = payload.get("project")
    if not isinstance(project, str) or not project.strip():
        raise typer.BadParameter("Token is missing a 'project' name.")

    def _vec(name: str, n: int) -> list[float]:
        v = payload.get(name)
        if (not isinstance(v, list) or len(v) != n
                or not all(isinstance(x, (int, float)) for x in v)):
            raise typer.BadParameter(f"Token '{name}' must be {n} numbers.")
        return [float(x) for x in v]

    pos = _vec("pos", 3)
    quat = _vec("quat", 4)
    target = _vec("target", 3)
    fov = payload.get("fov")
    if not isinstance(fov, (int, float)) or not (0.0 < float(fov) < 180.0):
        raise typer.BadParameter("Token 'fov' must be a number in (0, 180).")

    start_view = {"pos": pos, "quat": quat, "target": target, "fov": float(fov)}
    return project.strip(), start_view


def _fetch_remote_config(zone: str, password: str, remote_dir: str) -> dict:
    """GET the project's current viewer-config.json from Bunny storage origin.

    Returns {} if it does not exist yet (older deploy / missing file).
    """
    url = f"https://storage.bunnycdn.com/{zone}/{remote_dir}/viewer-config.json"
    req = Request(url, headers={"AccessKey": password})
    try:
        raw = urlopen(req, timeout=60).read()
    except HTTPError as e:
        if e.code == 404:
            return {}
        raise
    text = raw.decode("utf-8").strip()
    if not text:
        return {}
    data = json.loads(text)
    if not isinstance(data, dict):
        raise RuntimeError(
            f"Remote viewer-config.json for '{remote_dir}' is not a JSON object."
        )
    return data


def set_start_view(
    token: str = typer.Argument(
        ..., help="The SPV1 token emitted by the viewer's 'Set start view' button."
    ),
    remote_name: str = typer.Option(
        None, "--remote-name",
        help="Bunny folder name, if it differs from the token's project name.",
    ),
    project_path: Path = typer.Option(
        None, "--project-path", "-p",
        help="Local project dir to also persist into (so future re-exports keep it).",
    ),
    env_file: Path = typer.Option(
        None, "--env", help="Path to .env with Bunny creds (default: auto-discover)."
    ),
) -> None:
    """Decode a viewer start-view token and save it for everyone.

    Patches the project's viewer-config.json on Bunny (+ purges the CDN),
    and optionally the local project's scene_config.
    """
    project_name, start_view = _decode_token(token)
    remote_dir = remote_name or project_name

    console.print(f"[bold]Start view[/bold] for [cyan]{project_name}[/cyan]")
    console.print(
        f"  pos={start_view['pos']}  fov={start_view['fov']:.2f}\n"
        f"  target={start_view['target']}"
    )

    env = load_bunny_env(env_file) if env_file else load_bunny_env()
    zone = env.get("BUNNY_STORAGE_ZONE", "")
    password = env.get("BUNNY_STORAGE_PASSWORD", "")
    cdn = env.get("BUNNY_CDN_URL", "")
    api_key = env.get("BUNNY_ACCOUNT_API_KEY", "")
    if not zone or not password:
        console.print(
            "[red]BUNNY_STORAGE_ZONE / BUNNY_STORAGE_PASSWORD missing in .env[/red]"
        )
        raise typer.Exit(1)

    cfg = _fetch_remote_config(zone, password, remote_dir)
    cfg["start_view"] = start_view

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td) / "viewer-config.json"
        tmp.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        remote_path = f"{remote_dir}/viewer-config.json"
        _, ok, detail = upload_file(zone, password, remote_path, tmp)

    if not ok:
        console.print(f"[red]Upload failed:[/red] {detail}")
        raise typer.Exit(1)
    console.print(f"  [green]uploaded[/green] {remote_path} ({detail})")

    if api_key and cdn:
        purged_ok, purged_fail = purge_bunny_cache(
            api_key, [f"{cdn}/{remote_dir}/viewer-config.json"]
        )
        console.print(f"  purge: {purged_ok} ok, {purged_fail} failed")
    else:
        console.print("  [yellow]purge skipped[/yellow] (no account API key / CDN URL)")

    if project_path is not None:
        if not project_path.exists():
            console.print(
                f"  [yellow]local project not found at {project_path} — skipped[/yellow]"
            )
        else:
            Project(project_path).set_scene_config_section("start_view", start_view)
            console.print(f"  [green]local scene_config updated[/green] ({project_path})")

    if cdn:
        console.print(
            f"\nVerify: [link]{cdn}/{remote_dir}/index.html[/link] "
            "(hard-reload - the start view is applied on load)."
        )
    console.print("[bold green]Start view saved.[/bold green]")
