"""Export / deploy step: copy output to folder or upload to Bunny CDN.

Supports two modes:
  - "folder": copy 05_output/ contents to a local destination path
  - "cdn": upload to Bunny CDN Storage (reads credentials from .env)
"""

import hashlib
import json
import os
import shutil
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Generator
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from ..core.events import ProgressEvent, StepResult


def export_to_folder(
    output_dir: Path,
    destination: Path,
    *,
    purge: bool = False,
) -> Generator[ProgressEvent, None, StepResult]:
    """Copy output directory to a local destination, yielding progress events.

    Args:
        output_dir: Directory containing files to export (05_output/)
        destination: Target directory to copy files into
        purge: If True, delete all existing files in destination before copying
    """
    # Purge destination if requested
    if purge and destination.exists():
        yield ProgressEvent(step="export", progress=0.0, message="Purging destination folder...")
        for item in list(destination.iterdir()):
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()

    # Collect files
    files = sorted(f for f in output_dir.rglob("*") if f.is_file())

    if not files:
        return StepResult(
            step="export", success=False,
            error=f"No files found in {output_dir}",
        )

    total_size = sum(f.stat().st_size for f in files)
    total_count = len(files)

    yield ProgressEvent(
        step="export", progress=0.0,
        message=f"Copying {total_count} files ({total_size / 1e6:.1f} MB)",
    )

    destination.mkdir(parents=True, exist_ok=True)

    copied = 0
    copied_bytes = 0
    t0 = time.time()

    for f in files:
        rel = f.relative_to(output_dir)
        dest_file = destination / rel
        dest_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, dest_file)

        copied += 1
        copied_bytes += f.stat().st_size

        yield ProgressEvent(
            step="export",
            progress=copied / total_count,
            message=f"Copied {copied}/{total_count}",
            detail=f"{copied_bytes / 1e6:.1f} MB",
        )

    duration = time.time() - t0

    return StepResult(
        step="export",
        success=True,
        summary={
            "copied": copied,
            "total_files": total_count,
            "total_mb": round(total_size / 1e6, 1),
            "duration_s": round(duration, 1),
            "destination": str(destination),
        },
    )


def load_bunny_env(*env_paths: Path | None) -> dict:
    """Load Bunny CDN credentials from .env file(s), environment, or TOML config.

    Priority (highest first):
    1. .env file (first existing file wins)
    2. OS environment variables
    3. defaults.toml [bunny] section
    """
    env = {}

    for env_path in env_paths:
        if env_path and env_path.exists():
            for line in env_path.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, val = line.split("=", 1)
                env[key.strip()] = val.strip()
            break

    # Fall back to environment variables
    for key in ("BUNNY_STORAGE_ZONE", "BUNNY_STORAGE_PASSWORD", "BUNNY_CDN_URL",
                "BUNNY_ACCOUNT_API_KEY"):
        if key not in env:
            val = os.environ.get(key)
            if val:
                env[key] = val

    # Fall back to TOML config [bunny] section
    if not all(k in env for k in ("BUNNY_STORAGE_ZONE", "BUNNY_STORAGE_PASSWORD")):
        try:
            from ..core.config import load_defaults
            bunny_cfg = load_defaults().get("bunny", {})
            key_map = {
                "storage_zone": "BUNNY_STORAGE_ZONE",
                "storage_password": "BUNNY_STORAGE_PASSWORD",
                "cdn_url": "BUNNY_CDN_URL",
            }
            for toml_key, env_key in key_map.items():
                if env_key not in env and bunny_cfg.get(toml_key):
                    env[env_key] = bunny_cfg[toml_key]
        except Exception:
            pass

    return env


def list_bunny_folders(storage_zone: str, password: str) -> list[dict]:
    """List top-level items in Bunny CDN storage zone.

    Returns list of dicts: [{"name": "IBUG_2025", "is_dir": True}, ...]
    """
    import json as _json

    list_url = f"https://storage.bunnycdn.com/{storage_zone}/"
    req = Request(list_url, method="GET")
    req.add_header("AccessKey", password)

    try:
        resp = urlopen(req, timeout=30)
        items = _json.loads(resp.read().decode())
    except (HTTPError, Exception):
        return []

    return [
        {"name": item.get("ObjectName", ""), "is_dir": item.get("IsDirectory", False)}
        for item in items
        if item.get("ObjectName")
    ]


def _purge_bunny_folder(storage_zone: str, password: str, remote_folder: str) -> int:
    """Delete all files in a Bunny Storage folder. Returns count of deleted items."""
    import json as _json

    list_url = f"https://storage.bunnycdn.com/{storage_zone}/{remote_folder}/"
    req = Request(list_url, method="GET")
    req.add_header("AccessKey", password)

    try:
        resp = urlopen(req, timeout=30)
        items = _json.loads(resp.read().decode())
    except (HTTPError, Exception):
        return 0

    deleted = 0
    for item in items:
        obj_name = item.get("ObjectName", "")
        is_dir = item.get("IsDirectory", False)
        path = f"{remote_folder}/{obj_name}" + ("/" if is_dir else "")
        del_url = f"https://storage.bunnycdn.com/{storage_zone}/{path}"
        del_req = Request(del_url, method="DELETE")
        del_req.add_header("AccessKey", password)
        try:
            urlopen(del_req, timeout=30)
            deleted += 1
        except (HTTPError, Exception):
            pass
    return deleted


def purge_bunny_cache(api_key: str, urls: list[str]) -> tuple[int, int]:
    """Purge Bunny CDN edge cache for one or more URLs.

    Uploading a file to the Storage Zone does *not* invalidate the CDN edge
    cache — Bunny continues serving the old copy until either the cache TTL
    expires or someone explicitly purges. This helper hits the Bunny Account
    API `POST /purge` endpoint once per URL (no batch endpoint as of 2026).

    Args:
        api_key: BUNNY_ACCOUNT_API_KEY (different from BUNNY_STORAGE_PASSWORD —
                 see https://dash.bunny.net → Account → API).
        urls:    Full CDN URLs to purge (e.g. ``https://x.b-cdn.net/foo/bar.html``).

    Returns ``(purged_ok, purged_failed)``. Quiet on failure — purging is a
    best-effort post-upload nicety; we don't fail the whole deploy if it
    breaks.
    """
    ok = 0
    failed = 0
    for url in urls:
        purge_url = f"https://api.bunny.net/purge?url={url}"
        req = Request(purge_url, method="POST", data=b"")
        req.add_header("AccessKey", api_key)
        req.add_header("Content-Length", "0")
        try:
            resp = urlopen(req, timeout=30)
            if 200 <= resp.status < 300:
                ok += 1
            else:
                failed += 1
        except (HTTPError, Exception):
            failed += 1
    return ok, failed


def list_bunny_subfolders(
    storage_zone: str, password: str, remote_prefix: str
) -> list[str]:
    """Immediate subdirectory names under ``<zone>/<remote_prefix>/`` on
    Bunny Storage. Empty list on any error (caller decides if that matters).
    Used by the publish flow to find stale prior ``b<key>/`` build subfolders.
    """
    url = f"https://storage.bunnycdn.com/{storage_zone}/{remote_prefix}/"
    req = Request(url, method="GET")
    req.add_header("AccessKey", password)
    try:
        items = json.loads(urlopen(req, timeout=30).read())
    except (HTTPError, Exception):
        return []
    return [it["ObjectName"] for it in items if it.get("IsDirectory")]


# ---------------------------------------------------------------------------
# Bunny pull-zone Edge Rule: make the small permanent-slug text files
# (index.html / viewer-config.json) always edge+browser fresh while the big
# immutable .rad/.radc keep the 30-day cache. WITHOUT this a re-deployed
# stable-slug URL keeps serving a 30-day-stale shell (the pull zone's
# CacheControlMaxAgeOverride overrides the client's cache:'no-store' too;
# per-URL purge does not reach all edges). See the project memory
# `project_bunny_viewer_config_cache`. Idempotent (~2 API calls), matched by
# Description so re-runs update in place.
# ---------------------------------------------------------------------------
_EDGE_PULLZONE_HOST = "splatpipe-cdn"
_EDGE_DESC = "splatpipe: no-edge-cache for permanent-slug index/config (redeploy-safe)"
_EDGE_URL_PATTERNS = [
    "https://splatpipe-cdn.b-cdn.net/*/index.html",
    "https://splatpipe-cdn.b-cdn.net/*/viewer-config.json",
    "https://splatpipe-cdn.b-cdn.net/index.html",
    "https://splatpipe-cdn.b-cdn.net/viewer-config.json",
]


def _bunny_api(api_key: str, method: str, url: str, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = Request(url, data=data, method=method)
    req.add_header("AccessKey", api_key)
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with urlopen(req, timeout=30) as r:
        raw = r.read()
        return json.loads(raw) if raw.strip() else {}


def _find_edge_pullzone(api_key: str) -> dict:
    zs = _bunny_api(api_key, "GET",
                    "https://api.bunny.net/pullzone?page=1&perPage=100")
    items = zs.get("Items", zs if isinstance(zs, list) else [])
    for z in items:
        if z.get("Name") == _EDGE_PULLZONE_HOST:
            return z
    raise RuntimeError(f"Bunny pull zone {_EDGE_PULLZONE_HOST!r} not found")


def _desired_edge_rules(existing: list[dict]) -> list[dict]:
    """Two rules (edge cache 0, browser cache 0). Reuse Guids by Description
    so addOrUpdate edits in place instead of duplicating."""
    by_desc = {r.get("Description"): r for r in existing}
    trigger = {"Type": 0, "PatternMatchingType": 0,
               "PatternMatches": _EDGE_URL_PATTERNS, "Parameter1": ""}
    out = []
    for action, tag in ((3, "edge"), (15, "browser")):
        d = f"{_EDGE_DESC} [{tag}]"
        prev = by_desc.get(d)
        out.append({
            "Guid": prev.get("Guid") if prev else None,
            "ActionType": action,         # 3=OverrideCacheTime, 15=OverrideBrowserCacheTime
            "ActionParameter1": "0",      # 0 = do not cache
            "ActionParameter2": "",
            "Enabled": True,
            "Description": d,
            "TriggerMatchingType": 0,     # MatchAny across triggers
            "Triggers": [dict(trigger)],
        })
    return out


def ensure_edge_rules(
    api_key: str, *, verify_only: bool = False, quiet: bool = False
) -> bool:
    """Ensure (or, with ``verify_only``, just check) the no-edge-cache Edge
    Rules on the splatpipe-cdn pull zone. Returns True on success /
    present-and-enabled. Never raises on a missing key — the caller decides
    whether the absence is fatal.
    """
    def _log(msg: str) -> None:
        if not quiet:
            print(msg, flush=True)

    if not api_key:
        _log("ensure_edge_rules: no BUNNY_ACCOUNT_API_KEY — skipped")
        return False

    z = _find_edge_pullzone(api_key)
    zid = z["Id"]
    existing = z.get("EdgeRules", []) or []
    ours = [r for r in existing
            if str(r.get("Description", "")).startswith(_EDGE_DESC)]
    _log(f"edge-rule: pull zone {_EDGE_PULLZONE_HOST} id={zid} "
         f"CacheControlMaxAgeOverride={z.get('CacheControlMaxAgeOverride')} "
         f"existing={len(existing)} ours={len(ours)}")

    if verify_only:
        ok = len(ours) >= 2 and all(r.get("Enabled") for r in ours)
        _log(f"edge-rule VERIFY: {'PRESENT+ENABLED' if ok else 'MISSING/DISABLED'}")
        return ok

    for rule in _desired_edge_rules(existing):
        _bunny_api(api_key, "POST",
                   f"https://api.bunny.net/pullzone/{zid}/edgerules/addOrUpdate",
                   rule)
        _log(f"edge-rule applied: [{rule['Description']}] "
             f"ActionType={rule['ActionType']} -> cache 0")
    now = [r for r in (_find_edge_pullzone(api_key).get("EdgeRules") or [])
           if str(r.get("Description", "")).startswith(_EDGE_DESC)]
    if len(now) < 2:
        raise RuntimeError(f"expected >=2 edge rules, got {len(now)}")
    _log("edge-rule OK — */index.html + */viewer-config.json bypass "
         "edge+browser cache; .rad/.radc still long-cached")
    return True


# Per-extension Cache-Control policy. Large immutable assets (the splat
# chunks themselves) get a year + immutable so the browser disk cache can
# satisfy 206/Range re-requests across reloads without a network round-trip.
# Viewer HTML / config keep a short TTL so updates are visible quickly.
#
# Important: as of 2026-05, Bunny's pull zone overrides origin Cache-Control
# with its own default (typically `public, max-age=2592000`, 30 days, no
# `immutable`) UNLESS "Honor Origin Cache Control" is enabled in the pull
# zone settings — which is OFF by default. To make these headers take effect:
#
#   Bunny Dashboard → Pull Zone → Caching → Caching → enable
#   "Use Origin Cache-Control Header" (or equivalent label)
#
# Until that is flipped, the 30-day pull-zone default still applies to .rad
# (good for our paged-streaming cache hit rate) but viewer HTML also gets
# 30 days — re-deploys rely on the post-upload purge call to refresh users.
# Long-term we should pin the pull-zone setting via Bunny's pull-zone API
# in deploy.py setup.
_CACHE_CONTROL = {
    ".rad":  "public, max-age=31536000, immutable",
    ".radc": "public, max-age=31536000, immutable",
    ".sog":  "public, max-age=31536000, immutable",
    ".ply":  "public, max-age=31536000, immutable",
    ".ksplat": "public, max-age=31536000, immutable",
    ".splat":  "public, max-age=31536000, immutable",
    ".spz":    "public, max-age=31536000, immutable",
    ".json": "public, max-age=300",     # viewer/scene config — refresh quickly
    ".html": "public, max-age=60",      # viewer shell — refresh almost-quickly
}


def _cache_control_for(remote_path: str) -> str | None:
    """Pick a Cache-Control value based on file extension."""
    lower = remote_path.lower()
    for ext, value in _CACHE_CONTROL.items():
        if lower.endswith(ext):
            return value
    return None


def upload_file(
    storage_zone: str,
    password: str,
    remote_path: str,
    local_path: Path,
) -> tuple[str, bool, str]:
    """Upload a single file to Bunny Storage. Returns (remote_path, success, detail)."""
    data = local_path.read_bytes()
    checksum = hashlib.sha256(data).hexdigest()

    url = f"https://storage.bunnycdn.com/{storage_zone}/{remote_path}"
    req = Request(url, data=data, method="PUT")
    req.add_header("AccessKey", password)
    req.add_header("Checksum", checksum)
    req.add_header("Content-Type", "application/octet-stream")
    cc = _cache_control_for(remote_path)
    if cc:
        req.add_header("Cache-Control", cc)

    try:
        resp = urlopen(req, timeout=120)
        return (remote_path, True, f"{resp.status}")
    except HTTPError as e:
        return (remote_path, False, f"HTTP {e.code}: {e.read().decode()[:200]}")
    except Exception as e:
        return (remote_path, False, str(e)[:200])


def deploy_to_bunny(
    project_name: str,
    output_dir: Path,
    env: dict,
    *,
    workers: int = 8,
    purge: bool = False,
) -> Generator[ProgressEvent, None, StepResult]:
    """Upload output directory to Bunny CDN, yielding progress events.

    Args:
        project_name: Used as the CDN path prefix
        output_dir: Directory containing files to upload
        env: Dict with BUNNY_STORAGE_ZONE, BUNNY_STORAGE_PASSWORD, BUNNY_CDN_URL
        workers: Number of parallel upload threads
        purge: If True, delete all existing files in the CDN folder before uploading
    """
    storage_zone = env.get("BUNNY_STORAGE_ZONE", "")
    password = env.get("BUNNY_STORAGE_PASSWORD", "")
    cdn_url = env.get("BUNNY_CDN_URL", "")

    if not storage_zone or not password:
        return StepResult(
            step="export", success=False,
            error="BUNNY_STORAGE_ZONE and BUNNY_STORAGE_PASSWORD must be set in .env",
        )

    # Purge remote folder if requested
    if purge:
        yield ProgressEvent(step="export", progress=0.0, message="Purging CDN folder...")
        _purge_bunny_folder(storage_zone, password, project_name)

    # Collect files
    files = []
    for f in sorted(output_dir.rglob("*")):
        if f.is_file():
            rel = f.relative_to(output_dir).as_posix()
            remote = f"{project_name}/{rel}"
            files.append((remote, f))

    if not files:
        return StepResult(
            step="export", success=False,
            error=f"No files found in {output_dir}",
        )

    total_size = sum(f.stat().st_size for _, f in files)
    total_count = len(files)

    yield ProgressEvent(
        step="export", progress=0.0,
        message=f"Uploading {total_count} files ({total_size / 1e6:.1f} MB)",
    )

    uploaded = 0
    failed = 0
    uploaded_bytes = 0
    failed_files = []
    t0 = time.time()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(upload_file, storage_zone, password, remote, local): (remote, local)
            for remote, local in files
        }

        for future in as_completed(futures):
            remote, local = futures[future]
            path, success, detail = future.result()
            size = local.stat().st_size

            if success:
                uploaded += 1
                uploaded_bytes += size
            else:
                failed += 1
                failed_files.append(f"{path}: {detail}")

            done = uploaded + failed
            yield ProgressEvent(
                step="export",
                progress=done / total_count,
                message=f"Uploaded {uploaded}/{total_count}",
                detail=f"{uploaded_bytes / 1e6:.1f} MB",
            )

    duration = time.time() - t0
    viewer_url = f"{cdn_url}/{project_name}/index.html" if cdn_url else ""

    # Purge Bunny edge cache for the URLs we just uploaded, so visitors hit
    # the new content immediately instead of stale edge copies. Best-effort —
    # if the account API key isn't configured or purging fails, we just log it
    # in the summary and keep going (the upload itself already succeeded).
    purge_ok = 0
    purge_failed = 0
    api_key = env.get("BUNNY_ACCOUNT_API_KEY", "")
    if api_key and cdn_url and failed == 0:
        purge_urls = [f"{cdn_url}/{remote}" for remote, _ in files]
        yield ProgressEvent(
            step="export", progress=1.0,
            message=f"Purging CDN cache for {len(purge_urls)} URLs",
        )
        purge_ok, purge_failed = purge_bunny_cache(api_key, purge_urls)

    return StepResult(
        step="export",
        success=failed == 0,
        summary={
            "uploaded": uploaded,
            "failed": failed,
            "total_files": total_count,
            "total_mb": round(total_size / 1e6, 1),
            "duration_s": round(duration, 1),
            "cdn_url": f"{cdn_url}/{project_name}/" if cdn_url else "",
            "viewer_url": viewer_url,
            "failed_files": failed_files[:10],
            "cache_purged": purge_ok,
            "cache_purge_failed": purge_failed,
        },
        error=f"{failed} files failed" if failed > 0 else None,
    )
