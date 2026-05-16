# Plan: Splatpipe Spark viewer — performance optimization

**Created:** 2026-05-14
**Status:** Awaiting user approval
**Author:** Claude (8 parallel research agents + synthesis)

## Why

User-reported problems with the Spark viewer at `IBUG_23mio_v06`:

- **iPhone 13 mini (Safari iOS 18)** — double-tap-and-hold-drag gesture broken (iOS native callout/loupe intercepts), splat quality "good around 1.5 M" but hard ceiling unclear.
- **MacBook M1 Pro (Brave)** — only ~22 fps at 2 M splats.
- **Workstation RTX 5090 (Brave)** — fine, but no measurement to confirm.
- Chunk-loading visibly destroys frame time mid-experience.
- No adaptive quality; budget is set once at load.
- No per-device benchmark harness.

User asked for a comprehensive plan first, no code yet.

## Research

Eight parallel agents covered: iOS Safari pointer event quirks, adaptive FPS-targeting algorithms (drei/Babylon/Unreal), pre-cache + front-load strategies, frame-time + jank measurement instrumentation, per-device perf baselines (A15 / M1 Pro / RTX 5090), competing Gaussian-splat viewer perf strategies, Spark 2.0.0 internal knobs deep-dive, and Brave-specific quirks.

Key findings consolidated into the work pillars below. Full agent transcripts in
`C:\Users\sasch\AppData\Local\Temp\claude\H--001-ProjectCache-1000-Coding-Splatpipe\7f47efa8-4f44-48af-8a35-ff4ac786b8c9\tasks\`.

## Six work pillars

### I. iOS pointer-event fix (small, separate from perf work)

**Problem identified (agent E, high confidence).** iOS Safari dispatches TouchEvents *before* synthesizing PointerEvents. The OS-level long-press timer (callout / loupe / selection) starts on `touchstart`. By the time our `pointerdown` handler runs and calls `preventDefault()`, the OS has already started its gesture pipeline and `preventDefault` on the synthesized event does NOT propagate back to UIKit's gesture recognizers.

Playwright simulation doesn't hit this because it synthesizes PointerEvents directly without going through UIKit.

**Fix.** Add a `touchstart` + `touchmove` listener on the canvas with `{ passive: false }` that calls `preventDefault()` on the second tap of a potential double-tap-and-hold. Keep all existing PointerEvent logic untouched — the TouchEvent wedge just suppresses the OS-level gesture before it starts.

```js
let lastTapTime = 0;
const DOUBLE_TAP_WINDOW_MS = 350;
canvas.addEventListener('touchstart', (e) => {
  if (e.touches.length !== 1) return;
  const now = e.timeStamp;
  if (now - lastTapTime < DOUBLE_TAP_WINDOW_MS) {
    e.preventDefault();              // kills iOS callout, loupe, click-delay
  }
  lastTapTime = now;
}, { passive: false });
canvas.addEventListener('touchmove', (e) => {
  if (gestureActive) e.preventDefault();
}, { passive: false });
```

Same approach Mapbox's `tap_drag_zoom.ts` uses for the same gesture.

Also tighten CSS — add `-webkit-user-select: none; user-select: none; -webkit-touch-callout: none; touch-action: none` directly on the canvas element (not just body) since iOS 15+ has regressed selection-engine behavior on canvas children.

**Estimated effort:** 30 minutes. Surgical patch to existing handler.

### II. Universal mobile baseline wins

Adopted by every shipping Gaussian-splat viewer with mobile-perf docs (Spark, SuperSplat, mkkellogg, Luma, Babylon community). Free uplift, low risk.

| Change | Where | Effect |
|---|---|---|
| `antialias: false` on `WebGLRenderer` | template.py renderer init | Splats are pre-anti-aliased. MSAA on iOS is the dominant fill cost. Reported wins: Babylon 15→60 fps on iPhone. |
| `renderer.setPixelRatio(Math.min(devicePixelRatio, 1.5))` | template.py | M1 Pro at native DPR is fill-bound. DPR cap at 1.5 saves 30%+ on Retina. |
| `clipXY: 1.05` (mobile) | sparkOpts (currently 1.4 default) | Tightens per-splat frustum cull in vertex shader. ~10-15% fewer fragments. |
| `minPixelRadius: 1.5` (mobile) | sparkOpts | Discards sub-pixel splats. Agent A called it "best mobile lever after lodSplatScale." |
| `maxStdDev: Math.sqrt(5)` (mobile) | sparkOpts (default ~2.83) | Tighter Gaussian footprint. Fewer shaded pixels. |
| `minSortIntervalMs: 50` (mobile) | sparkOpts (default 0) | Throttles per-frame radix sort during slow camera. ~5-10% CPU savings. |
| `splat.maxSh = 1` for paged meshes (mobile) | template.py | Default 3. Dropping to 1 skips SH2/SH3 texture allocs entirely — bandwidth + shader win. |

**Estimated effort:** 1 hour. Pure config change.

### III. Smart device-tier picker (replaces current UA regex)

**Current state.** `_deviceProfile` in `template.py` uses `navigator.maxTouchPoints` + screen short-side for phone/tablet/desktop. `pickDefaultBudget()` adds `navigator.deviceMemory` and a `UNMASKED_RENDERER_WEBGL` regex.

**Problems uncovered by research.**
- iOS Safari since 12.2 always returns `"Apple GPU"` for the renderer string. Cannot distinguish iPhone 8 from iPhone 15 Pro.
- Brave Shields (default Standard mode) farbles `hardwareConcurrency` to `[2, real]`, `deviceMemory` to `[0.5, real]`, and normalizes `UNMASKED_RENDERER_WEBGL` to a coarse generic string. Both Sascha's desktops are Brave → the current picker is randomly underestimating both machines.
- Even on vanilla Chrome the desktop tier is too coarse — M1 Pro 14-core vs RTX 5090 should not share one budget.

**Replacement.** Layered tier picker:

1. **Side-channel hardware fingerprint (Brave-safe)** — use `WebGLRenderingContext` parameters that aren't farbled: `MAX_TEXTURE_SIZE`, `MAX_RENDERBUFFER_SIZE`, `MAX_VARYING_VECTORS`, presence/absence of `EXT_color_buffer_float`. These form an effective device-class fingerprint without violating privacy intent.
2. **`navigator.brave.isBrave()` detection** — if Brave, skip the GPU regex bump; emit a console + one-time toast pointing the user at "Shields → Down for this site → reload" for higher quality.
3. **1-second performance probe at startup** — render the loaded splat at a pinned 200 K-splat budget for 1 second, count frames, commit a tier from the probe result:
   - `<25 fps` → tier 0 (old phone)
   - `25-50 fps` → tier 1 (modern phone)
   - `50-80 fps` → tier 4 (pro laptop)
   - `80-110 fps` → tier 5 (high desktop)
   - `>110 fps` → tier 6 (flagship)
4. **User override** — existing `#splat-budget` dropdown stays; selecting an explicit value pins it and disables the probe + adaptive controller.

**Seven-tier ladder** (from agent F; Spark's own defaults at the corresponding rows):

| Tier | `lodSplatCount` | `maxPagedSplats` | `lodSplatScale` | Foveation | Typical device |
|---|---|---|---|---|---|
| 0 | 500 K | 4 M | 0.6 | on | iPhone 11/12, low-end Android |
| 1 | 1.5 M | **8 M** (Spark default 16 M would blow past iOS Safari's 256 MB canvas memory cap → tab reload) | 0.7 | on | iPhone 13 mini, iPhone 13/14 |
| 2 | 2 M | 12 M | 1.0 | on | iPhone 15 Pro, iPad Pro |
| 3 | 2 M | 12 M | 1.0 | on | M1/M2 Air, integrated-GPU laptops |
| 4 | 2.5 M | 16 M | 1.2 | on (mild) | M1 Pro, RTX 3060-4070 |
| 5 | 4 M | 16 M | 2.0 | off | RTX 4080+, RTX 5080 |
| 6 | 6 M | 16 M | 3.0 | off | RTX 4090/5090 |

**Estimated effort:** ~3-4 hours. Picker + probe + Brave detection + UI wiring.

### IV. Adaptive FPS controller (safety net)

**Disagreement among the research** — agent G says no shipping splat viewer ships an adaptive controller (they all use fixed per-device budgets). Agent B says general game-engine practice (drei `PerformanceMonitor`, Unreal Dynamic Resolution, Babylon SceneOptimizer) does. **Reconciliation:** fixed tier budget from pillar III is the **baseline**. Adaptive controller is a **safety net** that only kicks in when measured FPS drops more than N below the tier target (thermal throttling, hot phone, slow CDN, big chunk load, etc.) and only adjusts `lodSplatScale` (the multiplier), never `lodSplatCount` (which the user explicitly picked).

**Algorithm (composite — drei's voting pattern + Unreal's asymmetric step + a stutter-rejection layer):**

| Constant | Value | Source |
|---|---|---|
| Target FPS | tier-dependent (30 for phone, 60 for desktop) | F |
| Sample window | 500 ms × 4 buckets = 2 s decision interval | B (matches Babylon's empirically stable cadence) |
| Vote threshold | 75% of buckets must agree | B (drei) |
| Dead band | target-5 to target | B |
| Step down | 0.15 (aggressive) | B (UE — users feel drops fast) |
| Step up | 0.05 (conservative) | B (don't undo a good state) |
| Cooldown | 1500 ms between adjustments | B |
| Flipflop bailout | 6 reversals → freeze at last "down" value | B (drei `onFallback`) |
| Scale floor | 0.20 (20% of tier budget) | B |
| Scale ceiling | 1.50 | B |
| **Stutter reject** | any frame > 100 ms = excluded from FPS bucket | B (this is the chunk-load fix) |

**Stutter rejection is the killer feature** for our use case. When a `.rad` chunk decodes + uploads, it spikes one frame to 100-250 ms. Without rejection, the controller would think the whole device is slow and drop quality. Rejecting frames > 100 ms means chunk-load spikes don't trigger a quality drop. Stutters are surfaced as a separate metric in the HUD ("stutters: 3 in last 30 s") so the user knows their network is straining, but the controller stays calm.

**Surface to user:**
- Console log every change.
- HUD shows current scale.
- One-time toast on first decline ("Quality reduced for smoother playback").
- Splat-budget dropdown user-choice pins the budget and disables the controller (otherwise the controller fights the dropdown).

**Estimated effort:** ~3 hours. Tiny algorithm, all glue.

### V. Front-load + loading bar (kills mid-experience stutters)

**Two root causes of mid-experience hitches identified:**

**Root cause #1:** `SplatPager.processUploads()` is unbudgeted. It drains *every* ready chunk per call. If 5 chunks finish decoding in the same frame, all 5 upload (CPU memcpy + `texSubImage3D`) in that one frame → visible 100-200 ms freeze.

**Fix #1 — monkey-patch `processUploads` to upload max N chunks/frame.** ~10 lines, no Spark fork required. Start with N=2. Spark's pager exposes `pager.readyUploads[]` directly — we slice it, restore the rest, and call the underlying upload. Frame stays at 16 ms even under chunk-burst pressure.

**Root cause #2:** lazy chunk streaming means the first interactive frame happens before the cache is warm enough. The user immediately sees stutter as the camera moves.

**Fix #2 — explicit front-load phase.** Spark exposes `pager.autoDrive`, `pager.fetchPriority`, `pager.driveFetchers()`. The flow:

1. Show loading bar, hide canvas.
2. `splats.getRadMeta()` → read TOC.
3. `pager.autoDrive = false`, `spark.enableLodFetching = false`.
4. Pick first N chunks (priority sum ≈ 150-300 MB → 10-20% of file → 5-15 s loading bar at typical connections).
5. Set `pager.fetchPriority = [those chunks]`, call `driveFetchers()` in a loop.
6. Loading bar = `bytesFetched / bytesPriorityTotal`.
7. When done: `pager.autoDrive = true`, `enableLodFetching = true`, fade in canvas.

**Camera-path prefetch using `lodPosOverride`.** Agent A found an undocumented hook on `SparkRenderer`: `spark.lodPosOverride` + `spark.lodQuatOverride`. When set, LOD traversal uses that pose instead of the camera. During camera-path playback we can set the override one frame ahead of the camera's actual pose to pre-pull chunks along the route. This is exactly what camera paths need.

**Free wins around it:**

- Add `<link rel="preconnect" href="https://splatpipe-cdn.b-cdn.net">` to viewer `<head>` → saves 50-300 ms TLS handshake on cold connect.
- `deploy.py` emits `Cache-Control: public, max-age=31536000, immutable` on `.rad` PUT → browser HTTP cache handles 206/Range responses natively, zero client code, free cross-reload caching.
- **Skip Service Worker.** Cache API rejects 206 responses by spec; Workbox's workaround forces full-file download which defeats paging on a 1.58 GB asset.
- **Skip IndexedDB caching.** iOS Safari evicts after 7 days of no user interaction. Not worth the complexity vs. the browser disk cache.

**Estimated effort:** ~5 hours. The `processUploads` throttle is the biggest single user-visible win and the smallest patch.

### VI. Instrumentation HUD + benchmark mode

**Three-tier visibility:**

1. **Always-on HUD** — replace the current 1-second-window FPS counter with a 120-frame ring buffer. Display `FPS · p95ms · splats`. The p95 catches what mean hides (a 60 fps avg with 80 ms p95 feels janky).
2. **Debug HUD** — `?debug=1` URL param or `D` keypress toggles. Drop in [stats-gl](https://github.com/RenaudRohlinger/stats-gl) (10 KB, three.js-native, GPU panel for free via `EXT_disjoint_timer_query_webgl2` when available). Pooled 4-deep GPU timer query so reads never block. Long-task panel from `PerformanceObserver({type:'longtask'})`. Sparkline shows frame time + chunk-load events as overlay ticks.
3. **Bench mode** — `?bench=1&budget=2M&path=tour-a` URL params. Pins DPR=1, viewport=1920×1080, waits for first ring of pages around start camera, plays project's default camera path, records per-frame trace (timestamp, CPU ms, GPU ms, splats, pages resident, heap, longtasks, INP entries). Auto-downloads JSON at path end.

**Companion** — small Jupyter notebook in `tests/perf/compare.ipynb` that loads N traces from each device, plots CPU/GPU per frame side-by-side, marks longtasks as red dots, dumps mean/p95/p99 summary.

**Brave caveats baked in:**
- `performance.memory` works in Brave (Chromium API; not stripped). Values slightly diverge from Chrome but are advisory anyway.
- Skip `UNMASKED_RENDERER_WEBGL` for device-tier metadata (farbled). Use `MAX_TEXTURE_SIZE` etc. instead.

**iOS caveats:**
- `EXT_disjoint_timer_query_webgl2` is feature-flagged behind `Develop → Feature Flags → WebGL Timer Queries` in iOS Safari 18. Degrades to CPU-only on the iPhone. User can flip the flag once on the test device.

**Estimated effort:** ~4 hours. Ring buffer + stats-gl + bench mode + Jupyter starter.

## Asset-side option (separate decision)

For mobile, rebake `.rad` with the Spark CLI flags:

- `--csplat` — drops the ext-texture pool, ~half file size, slight quality hit. Lower GPU memory ceiling.
- `--max-sh=1` — caps spherical harmonics at degree 1 (skips SH2/SH3). ~3-4× smaller file, much faster to page on mobile networks.

Could ship as `scene_mobile.rad` + tier-aware selection. Adds asset-pipeline complexity. **Recommend deferring to v2** — the runtime wins in pillars I-V are enough for now.

## Per-device test protocol

For each of iPhone 13 mini / M1 Pro / RTX 5090 desktop:

1. Cold reload + hard refresh.
2. Run bench mode three times: `?bench=1&budget=1M`, `&budget=2M`, `&budget=4M` (and 8M / 15M on desktop).
3. Download the JSON traces.
4. iPhone-only: enable WebGL Timer Queries feature flag for GPU timing (one-time).
5. Drop traces into `tests/perf/compare.ipynb`, render comparison plots.

Pass criteria per device:
- iPhone 13 mini: 30 fps p95 at 1.5 M tier budget, < 3 stutters/min.
- M1 Pro: 60 fps p95 at 2 M, < 1 stutter/min.
- RTX 5090: 60 fps p95 at 5 M, no stutters.

## What we are NOT doing

| Excluded | Reason |
|---|---|
| Service Workers / IndexedDB caching | Cache API rejects 206 / iOS 7-day eviction. Browser HTTP cache covers 90% of the win at zero code cost. |
| WebGPU path | Spark doesn't expose one yet. |
| SPZ v4 ingest | Shelved separately in `docs/plans/2026-05-07_spz4_integration.md`. |
| Forking Spark to fix `processUploads` upstream | Monkey-patch from our side works, ~10 lines, no fork to maintain. Can submit a PR after we know N is right. |
| `lodInflate` baked-into-`.rad` | Per-mesh runtime knob is enough for current use case. |
| Per-tour camera-path metadata baked into `.rad` | Spark doesn't read it. Runtime prefetch via `lodPosOverride` is the right hook. |

## Recommended implementation order

1. **I — iOS touch fix.** ~30 min. Independently testable. User can verify on their iPhone before anything else lands.
2. **V — `processUploads` throttle + preconnect + `Cache-Control` header.** ~1 hour. Biggest visible-stutter win for the smallest patch. Independently testable on every device.
3. **II — Universal mobile baseline wins.** ~1 hour. Drop-in, can land alongside (2).
4. **VI — Always-on FPS p95 HUD + bench mode skeleton.** ~3 hours. Lets us *measure* impact of (3) instead of guessing.
5. **III — Smart device-tier picker.** ~3-4 hours. Now we have measurements, the probe constants are grounded in real data.
6. **V — Front-load + loading bar.** ~3 hours.
7. **IV — Adaptive controller.** ~3 hours. Layered on top of everything else.
8. **VI debug HUD + Jupyter notebook polish.** ~2 hours.

Total ~17-20 hours of implementation. (1)-(3) get the user a noticeable win in one sitting.

## Open questions for the user

- **M1 Pro variant.** 14-core GPU or 16-core GPU? 16 GB or 32 GB RAM? Changes the budget by ~15%.
- **Adaptive vs fixed budget UX.** Should the splat-budget dropdown set the *ceiling* the adaptive controller can climb to, or *pin* the budget and disable the controller? Two viable UX shapes.
- **Asset rebake.** Ship a separate `scene_mobile.rad` (--csplat --max-sh=1)? Or defer until we see whether runtime knobs are enough?
- **Adaptive-controller default state.** ON or OFF by default? Industry pattern is fixed-tier-budget-only (no controller), with the controller as opt-in.
- **iOS WebGL Timer Queries.** Acceptable to ask the user to flip the iOS feature flag once on the test phone for GPU timing? (Alternative: ship CPU-only timing on iOS.)
