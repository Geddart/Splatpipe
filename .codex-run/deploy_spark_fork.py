"""Host the PATCHED Spark fork bundle on Bunny at a fresh versioned path.

The fork carries the decoder.rs RefCell-re-entrancy fix (ChunkDecoder::push
no longer holds the BUFFER thread-local borrow across self.receiver.push(),
which is what made --cluster-sh builds panic + "OOM" the tab).

Single self-contained file: spark.module.js has the patched WASM inlined as
base64, so hosting is one PUT. Fresh path (never reused) => no Bunny edge-cache
staleness. Bump VERSION when the fork changes.
"""
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "src")
from splatpipe.steps.deploy import (  # noqa: E402
    load_bunny_env,
    deploy_to_bunny,
    purge_bunny_cache,
)

VERSION = "rcf5"  # rcf2 (refcell + chunk-0 codebook gate) + 3-deep PIXEL_UNPACK_BUFFER ring async per-page texture upload in SplatPager.uploadPage (ANGLE-Metal PBO blit fast-path; TS-only, rcf2 WASM unchanged). rcf3 (frame-budget) + rcf4 (direct texSubImage3D) both A/B-disproven + reverted.
REMOTE = f"_sparkfork-{VERSION}"
BUNDLE_NAME = "spark.module.min.js"  # vite --mode production ESM output
SPARK_DIST = Path("H:/001_ProjectCache/1000_Coding/spark/dist") / BUNDLE_NAME

env = load_bunny_env(Path(".env"))
cdn = env.get("BUNNY_CDN_URL", "").rstrip("/")

assert SPARK_DIST.is_file(), f"built bundle missing: {SPARK_DIST}"
size_mb = SPARK_DIST.stat().st_size / 1e6
print(f"fork bundle: {SPARK_DIST} ({size_mb:.2f} MB)", flush=True)

# 'three' must stay a bare import (resolved by the page importmap to jsdelivr).
txt = SPARK_DIST.read_text(encoding="utf-8", errors="replace")
has_bare_three = ('from"three"' in txt) or ("from 'three'" in txt) or ('from "three"' in txt)
has_wasm_inline = "data:application/wasm;base64," in txt
print(f"  bare 'three' import present: {has_bare_three}", flush=True)
print(f"  wasm base64-inlined:         {has_wasm_inline}", flush=True)
assert has_bare_three, "built bundle does not import bare 'three' — importmap will not resolve it"
assert has_wasm_inline, "built bundle has no inlined wasm — separate .wasm hosting would be required"

stage = Path(tempfile.mkdtemp(prefix="sparkfork_"))
shutil.copy2(SPARK_DIST, stage / BUNDLE_NAME)

print(f"uploading to {cdn}/{REMOTE}/{BUNDLE_NAME} ...", flush=True)
gen = deploy_to_bunny(REMOTE, stage, env, workers=4, purge=True)
result = None
try:
    while True:
        ev = next(gen)
        print(f"  {ev.message} {ev.detail or ''}", flush=True)
except StopIteration as stop:
    result = stop.value

bundle_url = f"{cdn}/{REMOTE}/{BUNDLE_NAME}"
api_key = env.get("BUNNY_ACCOUNT_API_KEY", "")
if api_key:
    ok, failed = purge_bunny_cache(api_key, [bundle_url])
    print(f"edge-cache purge: ok={ok} failed={failed}", flush=True)

print("\nDEPLOY RESULT:", flush=True)
print(json.dumps(result.summary if result else {"error": "no result"}, indent=2), flush=True)
print(f"\nSPARK_FORK_URL: {bundle_url}", flush=True)
