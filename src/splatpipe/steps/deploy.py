"""Export / deploy step: copy output to folder or upload to Bunny CDN.

Supports two modes:
  - "folder": copy 05_output/ contents to a local destination path
  - "cdn": upload to Bunny CDN Storage (reads credentials from .env)
"""

import hashlib
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
    """Load Bunny CDN credentials from .env file(s) or environment.

    Accepts multiple paths; the first existing file wins.
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
    for key in ("BUNNY_STORAGE_ZONE", "BUNNY_STORAGE_PASSWORD", "BUNNY_CDN_URL"):
        if key not in env:
            val = os.environ.get(key)
            if val:
                env[key] = val

    return env


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
        },
        error=f"{failed} files failed" if failed > 0 else None,
    )
