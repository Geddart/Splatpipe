"""Reusable: build a source PLY as chunked --cluster-sh and deploy it to a
fresh Bunny path with the final viewer template (share-card + per-scene config).

This is the #57 generalisation of deploy_ibug_cs_v25.py. Unlike the IBUG
scripts (which stage a pre-built .radchunk_cs), this BUILDS from the source
PLY via splatpipe.viewers.spark.build_lod.build():
  build(ply, quality=True, chunked=True, extra_flags=["--cluster-sh"])
→ cached ~/.cache/splatpipe/rad/<key>/  (manifest <stem>-lod.rad + N .radc).
Toolchain auto-resolves to the prebuilt spark/rust/target/release/build-lod.exe
(no cargo). Idempotent: re-runs are cache hits on the same PLY.

Usage:
  python .codex-run/deploy_scene_cs.py \
      --scene "Polygraf" \
      --ply  "H:/001_ProjectCache/660 Drone/_Photogrammetry/Leutzsch_Bahnhof/Mission2/Output/Splat/LeutschPolygraphenwerk_v01.ply" \
      --folder Polygraf_Leutzsch_cs_v1 \
      [--live Polygraf_Leutzsch] [--clip-xy 3.0] [--desc "..."]

After this, capture a 1200x630 start-view shot via the Playwright MCP and run
.codex-run/make_share_preview.py <folder> <shot> to publish its card image.
"""
import argparse
import glob
import json
import os
import shutil
import sys
import urllib.request
from pathlib import Path

# build-lod streams unicode (e.g. "[build-lod] done → …", the U+2192 arrow)
# through on_progress; the Windows console is cp1252 and a plain print()
# of it raises UnicodeEncodeError mid-run (lost the v1 Polygraf attempt at
# the very end — after a successful ~30 min cached build). Force UTF-8
# stdout/stderr so any tool output is printable. errors="replace" is a
# belt-and-braces fallback for anything UTF-8 still can't represent.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

sys.path.insert(0, "src")
from splatpipe.steps.deploy import load_bunny_env, deploy_to_bunny  # noqa: E402
from splatpipe.viewers.spark.build_lod import build  # noqa: E402
from splatpipe.viewers.spark.template import html_for, SPARK_FORK_URL  # noqa: E402

SPARK_REPO = Path(os.environ.get("SPARK_REPO", "H:/001_ProjectCache/1000_Coding/spark"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene", required=True, help="display name (og:title / project_name)")
    ap.add_argument("--ply", required=True, help="absolute source PLY path")
    ap.add_argument("--folder", required=True, help="FRESH Bunny folder (never reuse)")
    ap.add_argument("--live", default=None, help="existing Bunny folder to inherit viewer-config.json from")
    ap.add_argument("--clip-xy", type=float, default=None, help="per-scene spark_render.clip_xy (Speicher=3.0)")
    ap.add_argument("--move-speed-mult", type=float, default=None,
                    help="per-scene spark_render.move_speed_mult (WASD speed; <1.0 = slower, e.g. Polygraf 0.5)")
    ap.add_argument("--splat-budget", type=int, default=None,
                    help="per-scene splat_budget (top-level; honored on capable desktop only, e.g. Polygraf 3000000)")
    ap.add_argument("--desc", default=None, help="share-card description")
    args = ap.parse_args()

    ply = Path(args.ply)
    assert ply.is_file(), f"source PLY not found: {ply}"
    sz = ply.stat().st_size / 1e9
    print(f"[{args.scene}] source PLY: {ply}  ({sz:.2f} GB)", flush=True)

    env = load_bunny_env(Path(".env"))
    cdn = env.get("BUNNY_CDN_URL", "").rstrip("/")

    # 1. BUILD chunked --cluster-sh (cache HIT if this PLY was built before)
    print(f"[{args.scene}] build-lod --quality --rad-chunked --cluster-sh ...", flush=True)
    # cluster_sh + chunked are now the splatpipe build() defaults; explicit here.
    manifest = build(
        ply, quality=True, chunked=True, cluster_sh=True,
        on_progress=lambda l: print(f"  {l}", flush=True), spark_repo=SPARK_REPO,
    )
    cache_dir = manifest.parent
    radc = sorted(cache_dir.glob("*.radc"))
    assert radc, f"no .radc next to manifest {manifest}"
    total_mb = (manifest.stat().st_size + sum(p.stat().st_size for p in radc)) / 1e6
    print(f"[{args.scene}] built: {manifest.name} + {len(radc)} .radc ({total_mb:.0f} MB) in {cache_dir}", flush=True)

    # 2. STAGE  scene.rad + every .radc (basename preserved — manifest refs them relatively)
    stage = Path(f".scene_deploy_{args.folder}").resolve()
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    shutil.copy2(manifest, stage / "scene.rad")
    for rc in radc:
        shutil.copy2(rc, stage / rc.name)

    # 3. viewer-config.json — inherit live (if any) + inject per-scene clip_xy
    cfg = {}
    if args.live:
        try:
            req = urllib.request.Request(f"{cdn}/{args.live}/viewer-config.json",
                                         headers={"Cache-Control": "no-cache"})
            cfg = json.loads(urllib.request.urlopen(req, timeout=30).read())
            print(f"[{args.scene}] inherited viewer-config.json from {args.live} "
                  f"(start_view={bool(cfg.get('start_view'))})", flush=True)
        except Exception as e:
            print(f"[{args.scene}] WARN no live config ({e}) -> minimal", flush=True)
            cfg = {}
    if args.clip_xy is not None:
        cfg.setdefault("spark_render", {})["clip_xy"] = args.clip_xy
        print(f"[{args.scene}] injected spark_render.clip_xy = {args.clip_xy}", flush=True)
    if args.move_speed_mult is not None:
        cfg.setdefault("spark_render", {})["move_speed_mult"] = args.move_speed_mult
        print(f"[{args.scene}] injected spark_render.move_speed_mult = {args.move_speed_mult}", flush=True)
    if args.splat_budget is not None:
        cfg["splat_budget"] = args.splat_budget  # top-level, not under spark_render
        print(f"[{args.scene}] injected splat_budget = {args.splat_budget}", flush=True)
    (stage / "viewer-config.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    back = json.loads((stage / "viewer-config.json").read_text(encoding="utf-8"))
    if args.clip_xy is not None:
        assert back["spark_render"]["clip_xy"] == args.clip_xy, "clip_xy did not round-trip"
    if args.move_speed_mult is not None:
        assert back["spark_render"]["move_speed_mult"] == args.move_speed_mult, "move_speed_mult did not round-trip"
    if args.splat_budget is not None:
        assert back["splat_budget"] == args.splat_budget, "splat_budget did not round-trip"

    # 4. index.html with absolute share-card meta
    share_url = f"{cdn}/{args.folder}/index.html"
    share_image = f"{cdn}/{args.folder}/preview.jpg"
    desc = args.desc or (f"{args.scene} — a photogrammetry capture as a Gaussian-splat "
                         f"scene. Explore it in 3D in your browser. Splatpipe / Spark 2.")
    html = html_for(args.scene, primary_asset="scene.rad", paged=True,
                    share_url=share_url, share_image=share_image, description=desc)
    (stage / "index.html").write_text(html, encoding="utf-8")
    checks = {
        "fork_rcf2": "_sparkfork-rcf2" in html,
        "share_card": (f'<meta property="og:image" content="{share_image}">' in html
                       and f'<meta property="og:url" content="{share_url}">' in html
                       and '<meta name="twitter:card" content="summary_large_image">' in html),
        "clip_xy_wired": ("sparkOpts.clipXY = 1.4;" in html
                          and "sparkOpts.clipXY = 3.0;" not in html
                          and "sr.clip_xy" in html),
        "no_brace_mangle": chr(8) not in html,
    }
    print(f"[{args.scene}] index.html ({len(html)} B) checks: {json.dumps(checks)}", flush=True)
    assert all(checks.values()), f"self-checks failed: {checks}"

    # 5. DEPLOY to the FRESH folder + purge
    print(f"[{args.scene}] uploading to {cdn}/{args.folder}/ ...", flush=True)
    gen = deploy_to_bunny(args.folder, stage, env, workers=12, purge=True)
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
    print(f"\n[{args.scene}] DEPLOY RESULT: {json.dumps(summ)}", flush=True)
    print(f"[{args.scene}] VIEWER:  {cdn}/{args.folder}/index.html", flush=True)
    print(f"[{args.scene}] (next: capture 1200x630 start-view shot via Playwright "
          f"MCP, then make_share_preview.py {args.folder} <shot>)", flush=True)
    shutil.rmtree(stage, ignore_errors=True)
    return 0 if (result and not summ.get("failed_files")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
