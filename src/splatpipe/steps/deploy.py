"""Deploy step: upload project output to Bunny CDN Storage.

Reads credentials from .env or environment variables.
Uploads all files in 05_output/ to Bunny Storage under /<project_name>/.
"""

import hashlib
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Generator
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from ..core.events import ProgressEvent, StepResult


def load_bunny_env(env_path: Path | None = None) -> dict:
    """Load Bunny CDN credentials from .env file or environment."""
    env = {}

    # Try .env file first
    if env_path and env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            env[key.strip()] = val.strip()

    # Fall back to environment variables
    for key in ("BUNNY_STORAGE_ZONE", "BUNNY_STORAGE_PASSWORD", "BUNNY_CDN_URL"):
        if key not in env:
            val = os.environ.get(key)
            if val:
                env[key] = val

    return env


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
) -> Generator[ProgressEvent, None, StepResult]:
    """Upload output directory to Bunny CDN, yielding progress events.

    Args:
        project_name: Used as the CDN path prefix
        output_dir: Directory containing files to upload
        env: Dict with BUNNY_STORAGE_ZONE, BUNNY_STORAGE_PASSWORD, BUNNY_CDN_URL
        workers: Number of parallel upload threads
    """
    storage_zone = env.get("BUNNY_STORAGE_ZONE", "")
    password = env.get("BUNNY_STORAGE_PASSWORD", "")
    cdn_url = env.get("BUNNY_CDN_URL", "")

    if not storage_zone or not password:
        return StepResult(
            step="deploy", success=False,
            error="BUNNY_STORAGE_ZONE and BUNNY_STORAGE_PASSWORD must be set in .env",
        )

    # Collect files
    files = []
    for f in sorted(output_dir.rglob("*")):
        if f.is_file():
            rel = f.relative_to(output_dir).as_posix()
            remote = f"{project_name}/{rel}"
            files.append((remote, f))

    if not files:
        return StepResult(
            step="deploy", success=False,
            error=f"No files found in {output_dir}",
        )

    total_size = sum(f.stat().st_size for _, f in files)
    total_count = len(files)

    yield ProgressEvent(
        step="deploy", progress=0.0,
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
                step="deploy",
                progress=done / total_count,
                message=f"Uploaded {uploaded}/{total_count}",
                detail=f"{uploaded_bytes / 1e6:.1f} MB",
            )

    duration = time.time() - t0
    viewer_url = f"{cdn_url}/{project_name}/index.html" if cdn_url else ""

    return StepResult(
        step="deploy",
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
