"""Build a source PLY (chunked --cluster-sh) and deploy it to a scene's
STABLE Bunny slug — a permanent URL that never changes across rebuilds.

Layout per scene slug (e.g. `polygraf`):
    <slug>/index.html          stable — overwritten + purged each deploy
    <slug>/viewer-config.json  stable — overwritten + purged (fetched no-store)
    <slug>/preview.jpg         stable — published by make_share_preview.py
    <slug>/b<key>/scene.rad    BUILD-VERSIONED subfolder (key = PLY sha256[:16])
    <slug>/b<key>/<*.radc>     "      "
The big .rad/.radc never overwrite an existing object path (new b<key>/
subfolder per build) → zero Bunny edge-cache-corruption risk; only the
small stable text/image files are overwritten (the established-safe
pattern). index.html's PRIMARY_ASSET = `b<key>/scene.rad` (the viewer
resolves the manifest's .radc basenames relative to that). Stale b*/
subfolders from prior builds are deleted after a successful deploy.

The public URL is forever `https://<cdn>/<slug>/index.html` (+ `?embed=1`).
geddart embeds that once and never changes it.

Usage:
  python .codex-run/deploy_scene_cs.py --scene "Polygraf" \
     --ply ".../LeutschPolygraphenwerk_v01.ply" --slug polygraf \
     [--live Polygraf_Leutzsch_cs_v4] [--clip-xy 3.0]
     [--move-speed-mult 0.25] [--splat-budget 3000000] [--desc "..."]

`--desc` defaults to a NEUTRAL honest line (never fabricate scene specifics
— feedback_no_fabricated_scene_descriptions). Pass real user copy verbatim.
"""
import argparse
import json
import os
import shutil
import sys
import urllib.request
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

sys.path.insert(0, "src")
from splatpipe.steps.deploy import (  # noqa: E402
    load_bunny_env, deploy_to_bunny, purge_bunny_cache, _purge_bunny_folder,
)
from splatpipe.viewers.spark.build_lod import build  # noqa: E402
from splatpipe.viewers.spark.template import html_for  # noqa: E402

SPARK_REPO = Path(os.environ.get("SPARK_REPO", "H:/001_ProjectCache/1000_Coding/spark"))
NEUTRAL_DESC = "Interactive 3D photogrammetry scene — explore it in your browser."


def _list_subdirs(zone: str, pw: str, slug: str) -> list[str]:
    """Names of immediate subdirectories of <zone>/<slug>/ on Bunny Storage."""
    url = f"https://storage.bunnycdn.com/{zone}/{slug}/"
    req = urllib.request.Request(url, method="GET")
    req.add_header("AccessKey", pw)
    try:
        items = json.loads(urllib.request.urlopen(req, timeout=30).read())
    except Exception as e:
        print(f"  (could not list {slug}/ for cleanup: {e})", flush=True)
        return []
    return [it["ObjectName"] for it in items if it.get("IsDirectory")]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene", required=True, help="display name (og:title / project_name)")
    ap.add_argument("--ply", required=True, help="absolute source PLY path")
    ap.add_argument("--slug", required=True, help="STABLE scene slug, e.g. polygraf (permanent URL)")
    ap.add_argument("--live", default=None, help="existing Bunny folder to inherit viewer-config.json from")
    ap.add_argument("--clip-xy", type=float, default=None, help="per-scene spark_render.clip_xy (Speicher=3.0)")
    ap.add_argument("--move-speed-mult", type=float, default=None,
                    help="per-scene spark_render.move_speed_mult (WASD speed; <1.0 slower)")
    ap.add_argument("--splat-budget", type=int, default=None,
                    help="per-scene splat_budget (top-level; capable desktop only, e.g. 3000000)")
    ap.add_argument("--desc", default=None, help="share-card description — REAL user copy only, never invented")
    args = ap.parse_args()

    slug = args.slug.strip("/").lower()
    ply = Path(args.ply)
    assert ply.is_file(), f"source PLY not found: {ply}"
    print(f"[{slug}] source PLY: {ply} ({ply.stat().st_size/1e9:.2f} GB)", flush=True)

    env = load_bunny_env(Path(".env"))
    cdn = env.get("BUNNY_CDN_URL", "").rstrip("/")
    zone = env.get("BUNNY_STORAGE_ZONE", "")
    pw = env.get("BUNNY_STORAGE_PASSWORD", "")
    api = env.get("BUNNY_ACCOUNT_API_KEY", "")
    assert zone and pw, "BUNNY_STORAGE_ZONE / BUNNY_STORAGE_PASSWORD missing"

    # 1. BUILD chunked --cluster-sh (cache HIT if this PLY built before)
    print(f"[{slug}] build-lod --quality --rad-chunked --cluster-sh ...", flush=True)
    manifest = build(ply, quality=True, chunked=True, cluster_sh=True,
                      on_progress=lambda l: print(f"  {l}", flush=True), spark_repo=SPARK_REPO)
    cache_dir = manifest.parent
    radc = sorted(cache_dir.glob("*.radc"))
    assert radc, f"no .radc next to {manifest}"
    # build-versioned subfolder: PLY-content sha256[:16] (cache_dir name's 1st field)
    bkey = "b" + cache_dir.name.split("-")[0][:16]
    total_mb = (manifest.stat().st_size + sum(p.stat().st_size for p in radc)) / 1e6
    print(f"[{slug}] built: {len(radc)} .radc, {total_mb:.0f} MB → subfolder {bkey}/", flush=True)

    # 2. STAGE: stable root files + versioned b<key>/ subfolder
    stage = Path(f".scene_deploy_{slug}").resolve()
    if stage.exists():
        shutil.rmtree(stage)
    (stage / bkey).mkdir(parents=True)
    shutil.copy2(manifest, stage / bkey / "scene.rad")
    for rc in radc:                       # original basenames — manifest refs them relatively
        shutil.copy2(rc, stage / bkey / rc.name)

    # 3. viewer-config.json (inherit live + per-scene injects)
    cfg = {}
    if args.live:
        try:
            req = urllib.request.Request(f"{cdn}/{args.live}/viewer-config.json",
                                         headers={"Cache-Control": "no-cache"})
            cfg = json.loads(urllib.request.urlopen(req, timeout=30).read())
            print(f"[{slug}] inherited config from {args.live} (start_view={bool(cfg.get('start_view'))})", flush=True)
        except Exception as e:
            print(f"[{slug}] WARN no live config ({e})", flush=True)
            cfg = {}
    if args.clip_xy is not None:
        cfg.setdefault("spark_render", {})["clip_xy"] = args.clip_xy
    if args.move_speed_mult is not None:
        cfg.setdefault("spark_render", {})["move_speed_mult"] = args.move_speed_mult
    if args.splat_budget is not None:
        cfg["splat_budget"] = args.splat_budget
    (stage / "viewer-config.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    print(f"[{slug}] cfg: clip_xy={cfg.get('spark_render',{}).get('clip_xy')} "
          f"move_speed_mult={cfg.get('spark_render',{}).get('move_speed_mult')} "
          f"splat_budget={cfg.get('splat_budget')}", flush=True)

    # 4. index.html — stable URL, PRIMARY_ASSET points into the versioned subfolder
    share_url = f"{cdn}/{slug}/index.html"
    share_image = f"{cdn}/{slug}/preview.jpg"
    desc = args.desc or NEUTRAL_DESC
    html = html_for(args.scene, primary_asset=f"{bkey}/scene.rad", paged=True,
                    share_url=share_url, share_image=share_image, description=desc)
    (stage / "index.html").write_text(html, encoding="utf-8")
    checks = {
        "fork_rcf2": "_sparkfork-rcf2" in html,
        "primary_asset_subfolder": f"'{bkey}/scene.rad'" in html,
        "share_card_abs": (f'content="{share_image}"' in html and f'content="{share_url}"' in html),
        "no_brace_mangle": chr(8) not in html,
        "desc_not_fabricated": not any(w in html for w in
            ("derelict", "brewery", "Sterni", "printworks", "art-festival")) or args.desc is not None,
    }
    print(f"[{slug}] index.html ({len(html)} B) checks: {json.dumps(checks)}", flush=True)
    assert all(checks.values()), f"self-checks failed: {checks}"

    # 5. DEPLOY to the stable slug
    print(f"[{slug}] uploading to {cdn}/{slug}/ ...", flush=True)
    gen = deploy_to_bunny(slug, stage, env, workers=12, purge=True)
    result = None
    try:
        last = 0
        while True:
            ev = next(gen)
            if int(ev.progress * 20) != last:
                last = int(ev.progress * 20)
                print(f"  {ev.message} {ev.detail or ''}", flush=True)
    except StopIteration as stop:
        result = stop.value
    summ = result.summary if result else {"error": "no result"}
    if summ.get("failed_files"):
        print(f"[{slug}] DEPLOY FAILED: {json.dumps(summ)}", flush=True)
        return 1

    # 6. purge the stable root files (small text — safe) so the new build shows
    purge_bunny_cache(api, [share_url, f"{cdn}/{slug}/viewer-config.json"]) if api else None

    # 7. delete stale prior b*/ build subfolders (keep only the current bkey)
    for d in _list_subdirs(zone, pw, slug):
        if d.startswith("b") and d != bkey:
            n = _purge_bunny_folder(zone, pw, f"{slug}/{d}")
            print(f"[{slug}] cleaned stale build subfolder {d}/ ({n} files)", flush=True)

    print(f"\n[{slug}] DEPLOY RESULT: {json.dumps(summ)}", flush=True)
    print(f"[{slug}] PERMANENT URL: {share_url}", flush=True)
    print(f"[{slug}] (next: capture 1200x630 ?embed=1 shot, make_share_preview.py {slug} <shot>)", flush=True)
    shutil.rmtree(stage, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
