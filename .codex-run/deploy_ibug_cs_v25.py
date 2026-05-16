"""Redeploy IBUG --cluster-sh to FRESH IBUG_cs_v25.

v25 = v24 + the social share-card (template-only; fork rcf2 UNCHANGED,
scene .rad/.radc UNCHANGED):
  * html_for() now receives share_url / share_image / description, so the
    viewer <head> emits Open Graph + Twitter card meta. Pasting the link
    into Telegram/WhatsApp/iMessage/Discord/Slack/Twitter unfurls a rich
    card. og:image / twitter:image point at an ABSOLUTE
    <cdn>/IBUG_cs_v25/preview.jpg.
  * The preview.jpg itself is published separately AFTER this deploy by
    .codex-run/make_share_preview.py (Playwright-captured 1200x630 shot of
    the scene at start_view). The card degrades gracefully (title+desc)
    until the image lands.

Everything else identical to v24 (per-scene clip_xy default 1.4, budget
sync, Safari hint, #81, probe/rotate benches, 16 M pool, rcf2 fork).
Fork-version-agnostic: asserts the CURRENT SPARK_FORK_URL is clean rcf2.
"""
import os, glob, shutil, json, sys, re
from pathlib import Path
import urllib.request

sys.path.insert(0, "src")
from splatpipe.steps.deploy import load_bunny_env, deploy_to_bunny
from splatpipe.viewers.spark.template import html_for, SPARK_FORK_URL

SRC_DIR = Path(".radchunk_cs").resolve()
STAGE = Path(".radchunk_cs_deploy").resolve()
PROBE_VIEWS = Path(".codex-run/ibug_probe_views.json").resolve()
LIVE = "IBUG_23mio_v06"
FRESH = "IBUG_cs_v25"
PROJECT_NAME = "IBUG_23mio_v06"

env = load_bunny_env(Path(".env"))
cdn = env.get("BUNNY_CDN_URL", "").rstrip("/")

m = re.search(r"_sparkfork-(rcf\d+)", SPARK_FORK_URL)
assert m, f"SPARK_FORK_URL has no _sparkfork-rcfN token: {SPARK_FORK_URL}"
FORK_TAG = m.group(1)
assert FORK_TAG == "rcf2", (
    f"expected the clean rcf2 fork (known-good baseline), got {FORK_TAG}. "
    f"v25 is a template-only change; no fork rebuild is involved."
)
print("fork tag from template: %s (%s)" % (FORK_TAG, SPARK_FORK_URL), flush=True)

if STAGE.exists():
    shutil.rmtree(STAGE)
STAGE.mkdir(parents=True)

manifest = glob.glob(str(SRC_DIR / "*-lod.rad"))
radc = sorted(glob.glob(str(SRC_DIR / "*.radc")))
assert manifest and radc, "cluster-sh build missing in .radchunk_cs"
shutil.copy2(manifest[0], STAGE / "scene.rad")
for rc in radc:
    shutil.copy2(rc, STAGE / os.path.basename(rc))
print("staged scene.rad + %d .radc (%.0f MB)" % (
    len(radc), sum(os.path.getsize(STAGE / os.path.basename(r)) for r in radc) / 1e6), flush=True)

# --- viewer-config.json: preserve live config, inject probe_views + start_view ---
probe = json.loads(PROBE_VIEWS.read_text(encoding="utf-8"))
assert isinstance(probe, list) and len(probe) >= 1, "probe views json must be a non-empty list"
good = [v for v in probe if isinstance(v.get("pos"), list) and len(v["pos"]) == 3
        and isinstance(v.get("quat"), list) and len(v["quat"]) == 4]
assert len(good) == len(probe), f"some probe views malformed: {len(good)}/{len(probe)} valid"

cfg_url = f"{cdn}/{LIVE}/viewer-config.json"
try:
    req = urllib.request.Request(cfg_url, headers={"Cache-Control": "no-cache"})
    cfg_bytes = urllib.request.urlopen(req, timeout=30).read()
    cfg = json.loads(cfg_bytes)
    print("fetched live viewer-config.json (%d B); start_view: %s" % (
        len(cfg_bytes), bool(cfg.get("start_view"))), flush=True)
except Exception as e:
    print("WARN viewer-config.json: %s -> minimal {}" % e, flush=True)
    cfg = {}

cfg["probe_views"] = good
cfg["start_view"] = {  # user SPV1 ground-truth pose for #81 FG-blur repro
    "pos": [-0.56458, 0.42203, -8.31275],
    "quat": [0.00854, 0.91301, -0.01914, 0.4074],
    "target": [-1.7823, 0.49067, -7.21992],
    "fov": 60,
}
(STAGE / "viewer-config.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")
back = json.loads((STAGE / "viewer-config.json").read_text(encoding="utf-8"))
assert isinstance(back.get("probe_views"), list) and len(back["probe_views"]) == len(good), \
    "probe_views did not round-trip into staged viewer-config.json"
print("injected probe_views: %d poses; start_view preserved: %s" % (
    len(back["probe_views"]), bool(back.get("start_view"))), flush=True)

# --- index.html (with absolute share-card meta) ---
SHARE_URL = f"{cdn}/{FRESH}/index.html"
SHARE_IMAGE = f"{cdn}/{FRESH}/preview.jpg"
SHARE_DESC = ("IBUG Chemnitz — a derelict art-festival courtyard captured as a "
              "23-million-splat Gaussian scene. Explore it in 3D in your browser.")
html = html_for(PROJECT_NAME, primary_asset="scene.rad", paged=True,
                share_url=SHARE_URL, share_image=SHARE_IMAGE, description=SHARE_DESC)
(STAGE / "index.html").write_text(html, encoding="utf-8")
checks = {
    "fork_url_wired": SPARK_FORK_URL in html,
    "fork_tag_wired": f"_sparkfork-{FORK_TAG}" in html,
    "pool_16M": ("16_000_000" in html or "16000000" in html),
    "probe_bench": ("function _probeViews()" in html
                    and "async function _runProbeBench()" in html
                    and "cfg.probe_views" in html),
    "safari_hint": ('<div id="safari-hint"' in html
                    and "splatpipe.safariHintDismissed" in html),
    "clip_xy_per_scene": ("sparkOpts.clipXY = 1.4;" in html
                          and "sparkOpts.clipXY = 3.0;" not in html
                          and "_qf('clipXY')" in html),
    "budget_sync_50": "if (n > 0) selectClosestBudget(n);" in html,
    "share_card": (f'<meta property="og:image" content="{SHARE_IMAGE}">' in html
                   and f'<meta property="og:url" content="{SHARE_URL}">' in html
                   and '<meta name="twitter:card" content="summary_large_image">' in html
                   and "IBUG Chemnitz" in html),
    "no_brace_mangle": chr(8) not in html,
}
print("index.html (%d B) checks: %s" % (len(html), json.dumps(checks)), flush=True)
assert all(checks.values()), f"index.html failed self-checks: {checks}"

print("uploading to %s/%s/ ..." % (cdn, FRESH), flush=True)
gen = deploy_to_bunny(FRESH, STAGE, env, workers=12, purge=True)
result = None
try:
    last = 0
    while True:
        ev = next(gen)
        if int(ev.progress * 20) != last:
            last = int(ev.progress * 20)
            print("  %s %s" % (ev.message, ev.detail or ""), flush=True)
except StopIteration as stop:
    result = stop.value

print("\nDEPLOY RESULT:", flush=True)
print(json.dumps(result.summary if result else {"error": "no result"}, indent=2), flush=True)
if result and result.summary:
    print("\nVIEWER:        ", f"{cdn}/{FRESH}/index.html", flush=True)
    print("SHARE IMAGE:   ", SHARE_IMAGE, "(publish next: make_share_preview.py)", flush=True)
