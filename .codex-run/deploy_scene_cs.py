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
import hashlib
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
    ap.add_argument("--ply", default=None, help="source PLY to build from — XOR --rad-dir")
    ap.add_argument("--slug", required=True, help="STABLE scene slug, e.g. polygraf (permanent URL)")
    ap.add_argument("--live", default=None, help="existing Bunny folder to inherit viewer-config.json from")
    ap.add_argument("--clip-xy", type=float, default=None, help="per-scene spark_render.clip_xy (Speicher=3.0)")
    ap.add_argument("--move-speed-mult", type=float, default=None,
                    help="per-scene spark_render.move_speed_mult (WASD speed; <1.0 slower)")
    ap.add_argument("--splat-budget", type=int, default=None,
                    help="per-scene splat_budget (top-level; capable desktop only, e.g. 3000000)")
    ap.add_argument("--rad-dir", default=None,
                    help="prebuilt chunked dir (one *-lod.rad + *.radc) staged as-is instead of "
                         "building, e.g. .radchunk_cs for IBUG — XOR --ply")
    ap.add_argument("--crop-within", default=None,
                    help="build-lod --within-dist crop 'x,y,z,radius' — drop training-outlier "
                         "splats at source so no clip_xy hack is needed (Speicher)")
    ap.add_argument("--desc", default=None, help="share-card description — REAL user copy only, never invented")
    ap.add_argument("--prune-stale", action="store_true",
                    help="delete prior b*/ build subfolders after deploy. OFF by default: a "
                         "30-day-edge-cached OLD-design index.html (hardcoded b<key>, no cfg "
                         "pointer) still needs its subfolder alive through the cache TTL. Only "
                         "the deliberate #85 final consolidation passes this.")
    args = ap.parse_args()
    assert bool(args.ply) ^ bool(args.rad_dir), "give exactly one of --ply or --rad-dir"
    assert not (args.crop_within and args.rad_dir), "--crop-within only applies to a --ply build"

    slug = args.slug.strip("/").lower()
    env = load_bunny_env(Path(".env"))
    cdn = env.get("BUNNY_CDN_URL", "").rstrip("/")
    zone = env.get("BUNNY_STORAGE_ZONE", "")
    pw = env.get("BUNNY_STORAGE_PASSWORD", "")
    api = env.get("BUNNY_ACCOUNT_API_KEY", "")
    assert zone and pw, "BUNNY_STORAGE_ZONE / BUNNY_STORAGE_PASSWORD missing"

    # Re-assert the Bunny Edge Rule that makes */index.html +
    # */viewer-config.json bypass the pull zone's 30-day force-cache
    # (CacheControlMaxAgeOverride). WITHOUT this the permanent-slug design
    # is unreliable: an overwritten stable index.html/viewer-config.json
    # keeps serving a 30-day-stale copy (cache:'no-store' is overridden by
    # the pull zone; purge doesn't reach all edges) → blank scene. The big
    # .rad/.radc stay 30-day cached (immutable per-build subfolders).
    # Idempotent (~2 API calls); see memory project_bunny_viewer_config_cache.
    if api:
        try:
            import bunny_edge_rules
            bunny_edge_rules.apply(api, quiet=True)
            print(f"[{slug}] Bunny edge-rule (no-cache index/config) ensured", flush=True)
        except Exception as e:  # never block a deploy on this
            print(f"[{slug}] WARN edge-rule ensure failed: {e!r}", flush=True)
    else:
        print(f"[{slug}] WARN no BUNNY_ACCOUNT_API_KEY — cannot ensure edge-rule "
              f"(permanent-slug freshness depends on it)", flush=True)

    # 1. Obtain the chunked cluster-sh set — build from --ply, or stage a
    #    prebuilt --rad-dir as-is (IBUG: its set is the repo .radchunk_cs,
    #    produced by an earlier pipeline, not a PLY this script builds).
    if args.rad_dir:
        rd = Path(args.rad_dir)
        mans = sorted(rd.glob("*-lod.rad"))
        assert len(mans) == 1, f"expected exactly one *-lod.rad in {rd}, found {len(mans)}"
        manifest = mans[0]
        radc = sorted(rd.glob("*.radc"))
        assert radc, f"no .radc in {rd}"
        _h = hashlib.sha256()
        with open(manifest, "rb") as _fh:
            for _c in iter(lambda: _fh.read(1 << 20), b""):
                _h.update(_c)
        bkey = "b" + _h.hexdigest()[:16]   # stable per manifest content
        print(f"[{slug}] prebuilt set: {rd} ({manifest.name} + {len(radc)} .radc)", flush=True)
    else:
        ply = Path(args.ply)
        assert ply.is_file(), f"source PLY not found: {ply}"
        print(f"[{slug}] source PLY: {ply} ({ply.stat().st_size/1e9:.2f} GB)", flush=True)
        _xf = [f"--within-dist={args.crop_within}"] if args.crop_within else None
        print(f"[{slug}] build-lod --quality --rad-chunked --cluster-sh"
              f"{(' ' + _xf[0]) if _xf else ''} ...", flush=True)
        manifest = build(ply, quality=True, chunked=True, cluster_sh=True,
                         extra_flags=_xf,
                         on_progress=lambda l: print(f"  {l}", flush=True), spark_repo=SPARK_REPO)
        rd = manifest.parent
        radc = sorted(rd.glob("*.radc"))
        assert radc, f"no .radc next to {manifest}"
        # bkey MUST be unique per (PLY + build flags), not just PLY content —
        # else a rebuild of the same PLY with different flags (e.g. adding
        # --within-dist) reuses the subfolder and OVERWRITES .rad/.radc in
        # place → Bunny edge-cache corruption (the exact thing fresh
        # subfolders prevent). cache_dir.name = <sha256[:16]>-<rev>-<flags>,
        # so hash the whole thing.
        bkey = "b" + hashlib.sha256(rd.name.encode()).hexdigest()[:16]
    total_mb = (manifest.stat().st_size + sum(p.stat().st_size for p in radc)) / 1e6
    print(f"[{slug}] {len(radc)} .radc, {total_mb:.0f} MB -> subfolder {bkey}/", flush=True)

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
    # THE build pointer lives here (viewer-config.json is fetched no-store →
    # always fresh), NOT hardcoded in the 30-day-edge-cached index.html.
    # Redeploy = new subfolder + this fresh pointer; the permanent /slug/
    # URL never serves a stale subfolder reference.
    cfg["primary_asset"] = f"{bkey}/scene.rad"
    (stage / "viewer-config.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    print(f"[{slug}] cfg: primary_asset={cfg['primary_asset']} "
          f"clip_xy={cfg.get('spark_render',{}).get('clip_xy')} "
          f"move_speed_mult={cfg.get('spark_render',{}).get('move_speed_mult')} "
          f"splat_budget={cfg.get('splat_budget')}", flush=True)

    # 4. index.html — BUILD-AGNOSTIC (no b<key> baked in → identical every
    #    deploy → its 30-day Bunny edge cache is harmless). The real pointer
    #    is cfg.primary_asset in the no-store viewer-config.json (set above);
    #    the viewer's `_PRIMARY` reads that, falling back to this constant.
    share_url = f"{cdn}/{slug}/index.html"
    share_image = f"{cdn}/{slug}/preview.jpg"
    desc = args.desc or NEUTRAL_DESC
    html = html_for(args.scene, primary_asset="scene.rad", paged=True,
                    share_url=share_url, share_image=share_image, description=desc)
    (stage / "index.html").write_text(html, encoding="utf-8")
    _cfg_back = json.loads((stage / "viewer-config.json").read_text(encoding="utf-8"))
    checks = {
        "fork_rcf2": "_sparkfork-rcf2" in html,
        "cfg_has_pointer": _cfg_back.get("primary_asset") == f"{bkey}/scene.rad",
        "html_reads_cfg_pointer": "typeof cfg.primary_asset === 'string'" in html,
        "html_build_agnostic": bkey not in html,   # b<key> must NOT be in the cached index
        "share_card_abs": (f'content="{share_image}"' in html and f'content="{share_url}"' in html),
        "no_brace_mangle": chr(8) not in html,
        "desc_not_fabricated": not any(w in html for w in
            ("derelict", "brewery", "Sterni", "printworks", "art-festival")) or args.desc is not None,
    }
    print(f"[{slug}] index.html ({len(html)} B) checks: {json.dumps(checks)}", flush=True)
    assert all(checks.values()), f"self-checks failed: {checks}"

    # 5. DEPLOY to the stable slug.
    #    purge=False is REQUIRED, not an optimisation. purge=True →
    #    _purge_bunny_folder issues a Bunny *recursive directory DELETE*
    #    on <slug>/<b...>/ that returns immediately but runs
    #    ASYNCHRONOUSLY server-side. The re-upload then writes the same
    #    paths (a stable bkey — e.g. --rad-dir's sha256(manifest) — maps
    #    to the SAME subfolder every deploy), so the lagging async delete
    #    eats the freshly-uploaded chunks AND clobbers the re-PUT
    #    index.html/viewer-config.json (observed: IBUG redeploy left OLD
    #    index + a config with no primary_asset, 480/0 "uploaded"). This
    #    is the [[project-bunny-rad-edgecache-corruption]] family: never
    #    delete-then-reupload the same Bunny path. With purge=False the
    #    two tiny top-level text files overwrite cleanly (the Edge Rule
    #    keeps them edge-fresh) and chunks live in immutable b<key>/
    #    subfolders; stale old subfolders are pruned deliberately in #85,
    #    never mid-deploy.
    print(f"[{slug}] uploading to {cdn}/{slug}/ (purge=False — no async-delete race) ...", flush=True)
    gen = deploy_to_bunny(slug, stage, env, workers=12, purge=False)
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

    # 7. delete stale prior b*/ build subfolders (keep only the current bkey).
    #    OFF unless --prune-stale: an OLD-design index.html still in Bunny's
    #    30-day edge cache hardcodes a b<key>/ and has no cfg pointer to fall
    #    back on — deleting that subfolder mid-transition blanks the scene for
    #    every cached client. Keep all subfolders until the cache TTL has
    #    passed; the deliberate #85 consolidation prunes with full knowledge.
    if args.prune_stale:
        for d in _list_subdirs(zone, pw, slug):
            if d.startswith("b") and d != bkey:
                n = _purge_bunny_folder(zone, pw, f"{slug}/{d}")
                print(f"[{slug}] cleaned stale build subfolder {d}/ ({n} files)", flush=True)
    else:
        kept = [d for d in _list_subdirs(zone, pw, slug)
                if d.startswith("b") and d != bkey]
        if kept:
            print(f"[{slug}] kept {len(kept)} prior subfolder(s) {kept} "
                  f"(no --prune-stale; protects 30-day-cached old index)", flush=True)

    print(f"\n[{slug}] DEPLOY RESULT: {json.dumps(summ)}", flush=True)
    print(f"[{slug}] PERMANENT URL: {share_url}", flush=True)
    print(f"[{slug}] (next: capture 1200x630 ?embed=1 shot, make_share_preview.py {slug} <shot>)", flush=True)
    shutil.rmtree(stage, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
