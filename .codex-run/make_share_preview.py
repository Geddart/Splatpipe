"""Publish a scene's social-share preview image to Bunny.

Usage:
    python .codex-run/make_share_preview.py <bunny_folder> <local_image>

e.g. python .codex-run/make_share_preview.py IBUG_cs_v25 ./preview-ibug.jpg

What it does
------------
The Spark viewer's <head> (template.py html_for, share_image arg) points
og:image / twitter:image at  <cdn>/<folder>/preview.jpg . This script takes a
locally-captured screenshot of the deployed scene, normalises it to the
ideal Open Graph card size (1200x630, center cover-crop, optimised JPEG),
PUTs it to  <storage_zone>/<folder>/preview.jpg  with a proper image/jpeg
content-type and a short edge cache, then purges that one URL so the new
card shows immediately. Fits the static-CDN constraint: no backend, the
Bunny storage key never leaves this machine.

The screenshot itself is captured by the deploy orchestrator via the
Playwright MCP (python `playwright` is not installed in this venv): load
<cdn>/<folder>/index.html, hide #header/#stats/#controls-hint/#safari-hint/
#loading/#path-hud, wait for the scene to settle at start_view, screenshot
at a 1200x630 viewport. Pillow here still cover-crops to exactly 1200x630
so the result is correct regardless of the capture viewport.

Reusable for every scene (IBUG + the #57 redeploys): same script, just a
different <bunny_folder> + freshly captured image.
"""
import hashlib
import sys
import tempfile
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

sys.path.insert(0, "src")
from splatpipe.steps.deploy import load_bunny_env, purge_bunny_cache  # noqa: E402

from PIL import Image  # Pillow is available in this venv  # noqa: E402

OG_W, OG_H = 1200, 630  # Open Graph "summary_large_image" ideal (1.91:1)


def normalise_card(src: Path) -> Path:
    """Center cover-crop `src` to exactly 1200x630, return an optimised JPEG."""
    im = Image.open(src).convert("RGB")
    sw, sh = im.size
    # scale so the image covers the 1.91:1 frame, then center-crop the overflow
    scale = max(OG_W / sw, OG_H / sh)
    nw, nh = round(sw * scale), round(sh * scale)
    im = im.resize((nw, nh), Image.LANCZOS)
    left, top = (nw - OG_W) // 2, (nh - OG_H) // 2
    im = im.crop((left, top, left + OG_W, top + OG_H))
    out = Path(tempfile.mkdtemp(prefix="sharecard_")) / "preview.jpg"
    im.save(out, "JPEG", quality=85, optimize=True, progressive=True)
    return out


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    folder = sys.argv[1].strip("/")
    local_image = Path(sys.argv[2])
    assert local_image.is_file(), f"image not found: {local_image}"

    env = load_bunny_env(Path(".env"))
    zone = env.get("BUNNY_STORAGE_ZONE", "")
    password = env.get("BUNNY_STORAGE_PASSWORD", "")
    cdn = env.get("BUNNY_CDN_URL", "").rstrip("/")
    api_key = env.get("BUNNY_ACCOUNT_API_KEY", "")
    assert zone and password, "BUNNY_STORAGE_ZONE / BUNNY_STORAGE_PASSWORD missing in .env"

    card = normalise_card(local_image)
    data = card.read_bytes()
    size_kb = len(data) / 1024
    print(f"normalised card: {card} ({OG_W}x{OG_H}, {size_kb:.0f} KB)", flush=True)

    remote_path = f"{folder}/preview.jpg"
    url = f"https://storage.bunnycdn.com/{zone}/{remote_path}"
    req = Request(url, data=data, method="PUT")
    req.add_header("AccessKey", password)
    req.add_header("Checksum", hashlib.sha256(data).hexdigest())
    req.add_header("Content-Type", "image/jpeg")  # NOT octet-stream — OG scrapers care
    # Short cache: a re-deploy's new card must show; immediate purge below
    # handles the edge, this caps staleness if a purge is ever missed.
    req.add_header("Cache-Control", "public, max-age=300")
    try:
        resp = urlopen(req, timeout=120)
        print(f"PUT {remote_path} -> HTTP {resp.status}", flush=True)
    except HTTPError as e:
        print(f"PUT FAILED {remote_path} -> HTTP {e.code}: {e.read().decode()[:200]}", flush=True)
        return 1
    except Exception as e:
        print(f"PUT FAILED {remote_path} -> {e}", flush=True)
        return 1

    preview_url = f"{cdn}/{remote_path}"
    if api_key:
        ok, failed = purge_bunny_cache(api_key, [preview_url])
        print(f"edge-cache purge: ok={ok} failed={failed}", flush=True)

    print(f"\nPREVIEW IMAGE: {preview_url}", flush=True)
    print("Card meta is already wired in index.html (og:image / twitter:image).", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
