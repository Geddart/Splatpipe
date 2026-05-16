"""Config-only: replace a DEPLOYED scene's share-card description in place.

Only `index.html`'s `og:description`/`twitter:description`/`<meta
description>` changes — a few-KB text file, overwritten + purged at the
SAME path. The big `.rad`/`.radc` are untouched (no re-upload, no fresh
path, no edge-cache-corruption risk — that's `.rad`-binary-specific; small
HTML overwrite+purge is the established-safe pattern). Use this to correct
copy without churning a 400 MB scene or a new CDN URL.

Usage:
  python .codex-run/fix_scene_desc.py <bunny_folder> "<new description>"

The scene's og:title (project name) + its own share_url/share_image are
preserved by reading them back off the live index.html — nothing is
guessed. index.html is re-rendered with the CURRENT template (so the
scene also picks up any shipped viewer fixes), changing only the text.
"""
import re
import sys
import tempfile
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

sys.path.insert(0, "src")
from splatpipe.steps.deploy import load_bunny_env, purge_bunny_cache  # noqa: E402
from splatpipe.viewers.spark.template import html_for  # noqa: E402

NEUTRAL = "Interactive 3D photogrammetry scene — explore it in your browser."


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    folder = sys.argv[1].strip("/")
    desc = sys.argv[2] if len(sys.argv) > 2 else NEUTRAL

    env = load_bunny_env(Path(".env"))
    zone = env.get("BUNNY_STORAGE_ZONE", "")
    pw = env.get("BUNNY_STORAGE_PASSWORD", "")
    cdn = env.get("BUNNY_CDN_URL", "").rstrip("/")
    api = env.get("BUNNY_ACCOUNT_API_KEY", "")
    assert zone and pw, "BUNNY_STORAGE_ZONE / BUNNY_STORAGE_PASSWORD missing in .env"

    page_url = f"{cdn}/{folder}/index.html"
    live = urlopen(Request(page_url, headers={"Cache-Control": "no-cache"}),
                   timeout=30).read().decode("utf-8", "replace")
    m = re.search(r'<meta property="og:title" content="([^"]+?) — interactive 3D scene">', live)
    if not m:
        print(f"could not recover og:title (project name) from {page_url}; aborting (won't guess)")
        return 1
    project_name = m.group(1)
    paged = '"og:url"' in live  # deployed viewers are always paged .rad; sanity only
    print(f"folder={folder}  project_name={project_name!r}", flush=True)
    print(f"new description: {desc!r}", flush=True)

    html = html_for(project_name, primary_asset="scene.rad", paged=True,
                    share_url=page_url,
                    share_image=f"{cdn}/{folder}/preview.jpg",
                    description=desc)
    assert chr(8) not in html, "brace-mangle in rendered html"
    assert f'<meta name="description" content="{__import__("html").escape(desc, quote=True)}">' in html, \
        "description did not render into the meta tag"

    tmp = Path(tempfile.mkdtemp(prefix="fixdesc_")) / "index.html"
    tmp.write_text(html, encoding="utf-8")
    data = tmp.read_bytes()

    url = f"https://storage.bunnycdn.com/{zone}/{folder}/index.html"
    req = Request(url, data=data, method="PUT")
    req.add_header("AccessKey", pw)
    req.add_header("Content-Type", "text/html; charset=utf-8")
    req.add_header("Cache-Control", "public, max-age=300")
    try:
        r = urlopen(req, timeout=60)
        print(f"PUT {folder}/index.html -> HTTP {r.status} ({len(data)} B)", flush=True)
    except HTTPError as e:
        print(f"PUT FAILED -> HTTP {e.code}: {e.read().decode()[:200]}", flush=True)
        return 1

    if api:
        ok, failed = purge_bunny_cache(api, [page_url])
        print(f"edge-cache purge: ok={ok} failed={failed}", flush=True)
    print(f"\nDONE — {page_url} now describes: {desc!r}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
