# Plan: Niantic SPZ 4 integration — SHELVED 2026-05-07

> **Status:** Shelved. SPZ 4 dropped 2026-05-05 and the ecosystem hasn't
> caught up yet — splat-transform, Spark, SuperSplat, and the popular
> three.js libs are all still on SPZ v2/v3. Babylon is the only major
> frontend with v4 support, and even there the early adopters report bugs.
> Re-evaluate when at least one of the trigger conditions below fires.

## Context

Niantic Spatial published [SPZ 4](https://www.nianticspatial.com/blog/spz4)
on 2026-05-05. The format claims:

- 3–5× faster encoding (six parallel ZSTD streams, one per attribute,
  replacing single-threaded gzip).
- 1.5–2× faster end-to-end load.
- 20× faster in-browser via a rebuilt WASM/TS binding layer.
- No more 10 M point cap.
- Forward-compatible vendor-tag extension architecture (Adobe drove this;
  `SPZ_ADOBE_safe_orbit_camera` is the first extension).
- ~10× smaller than PLY, no perceptible quality loss, MIT-licensed.

User asked whether we should integrate it into a Splatpipe viewer or use a
Niantic-shipped viewer.

## Wire-format facts that matter to us

- Magic `NGSP` (`0x5053474e`), 32-byte little-endian `NgspFileHeader`.
- File layout: `Header → ILV extensions (optional) → TOC (N×16 bytes) →
  N independent ZSTD streams`. Each attribute stream compresses
  independently → parallel decode.
- Coordinate convention: **RUB** (right-up-back, three.js convention).
  `PackOptions` / `UnpackOptions` carry source/target frames, so the
  encoder/decoder handle PLY (RDF) ↔ GLB (LUF) ↔ Unity (RUF) flips.
  **Implication:** if we ever ingest SPZ directly, we can drop the
  180°-X PLY-native flip we currently do in the viewer.
- v4 decoders read v1–v3 via the legacy gzip path. v3 decoders **cannot**
  read v4 (different magic). Bumping any consumer is one-way.

## Ecosystem support snapshot (2026-05-07)

| Tool | SPZ in | SPZ out | SPZ 4? |
|---|---|---|---|
| `@playcanvas/splat-transform` 2.0.4 | ✅ v2/v3 (clean-room TS reader) | ❌ | ❌ |
| Spark `build-lod` (Rust) + `@sparkjsdev/spark@2.0.0` (JS runtime) | ✅ v3 (clean-room) | ❌ | ❌ — both decoders explicitly reject `version > 3` |
| PlayCanvas SuperSplat editor | ✅ v3 (via splat-transform family) | — | ❌ |
| three.js `mkkellogg/GaussianSplats3D` | ✅ likely v3 (predates SPZ 4) | — | ❌ |
| Babylon.js | ✅ TS fallback (v1–v3) or `@adobe/spz` WASM (v4 + SH4, opt-in via `SPLATLoadingOptions.spzLibraryUrl`) | ❌ | ✅ but buggy — late PR comment reports `RangeError` in Sandbox |
| `@spz-loader/playcanvas` (community, drumath2237, npm 0.3.1, MIT) | ✅ via `@spz-loader/core` WASM | — | ✅ inherits Niantic WASM |
| `nianticlabs.github.io/spz` | converter only — not a viewer |

## Integration paths that were on the table

### Path 1 — accept `.spz` as a project source (cheapest)

Wire `.spz` as a third project source format alongside `.psht` / `.ply`.
splat-transform decodes on ingest, rest of pipeline (assemble → SOG/RAD,
deploy) runs unchanged.

- **Cost:** ~1 day. Mirrors the existing `.ply`/`.psht` wiring
  (`init_cmd.py`, `parsers.detect_source_type()`, `Project.source_type`,
  passthrough trainer).
- **Caveat:** splat-transform 2.0.4 only handles SPZ v2/v3. Users with
  fresh SPZ 4 captures (Scaniverse latest, Adobe-export, etc.) would get
  an "Unsupported SPZ version" error. We get v4 for free whenever
  `slimbuck` bumps splat-transform.
- **UX win:** users with Scaniverse mobile captures can drop the file in
  directly instead of converting to PLY first.

### Path 2 — drop in `@spz-loader/playcanvas` for in-browser SPZ rendering

Add a custom PlayCanvas `ResourceHandler` that fetches `.spz` URLs and
decodes them via Niantic's WASM (wrapped by `@spz-loader/core`). Returns
a PC `GSplat` entity, drops into the existing viewer.

- **Cost:** ~3–5 days (asset handler, viewer wiring, scene-config field
  for SPZ source URL, mobile-test page like the PC 2.18 compare).
- **Bundle cost:** a few hundred KB WASM, loaded dynamically only on
  pages that touch SPZ.
- **SPZ 4 today:** yes — `@spz-loader/core` wraps Niantic's reference
  WASM, which IS on v4. (Better v4 status than splat-transform's
  clean-room reader.)
- **UX win:** users can paste a Scaniverse permalink (or any public SPZ
  URL) into the dashboard and the viewer renders it directly — no LOD
  build step, no chunked SOG / RAD on our CDN.

### Path 3 — SPZ as an export format

Currently blocked. Neither splat-transform nor Spark writes SPZ. Would
need to either wait for upstream or wrap Niantic's WASM encoder
ourselves. **Park.**

### Path 4 — bump Spark to SPZ 4

Non-trivial (~500–800 LOC per side, Rust + JS, needs `zstd`/`fzstd` deps
added). Adobe's Babylon work doesn't help directly. **Park** — Spark's
own `.rad` format already serves us better for HTTP-Range LoD streaming
than SPZ would.

## Why shelved

1. **splat-transform** — our PlayCanvas-side decoder — doesn't speak v4
   yet. Path 1 today only handles legacy SPZ files.
2. **Spark** doesn't speak v4 either, and there's no upstream PR.
3. **Babylon's v4 support is buggy at release**. Even the early adopter
   has issues. Worth letting the ecosystem settle for ~3–6 months.
4. No user has actually asked for SPZ support yet — this came from a
   LinkedIn announcement, not a real-world need.
5. Path 2 (community PlayCanvas loader) does work today, but spending
   3–5 days on a dependency-heavy in-browser feature with no concrete
   user is the wrong cost/benefit shape right now.

## Triggers to re-open this plan

Pick this back up if any of the following happens:

- **`@playcanvas/splat-transform` ships SPZ 4 read support** (watch
  https://github.com/playcanvas/splat-transform/releases for the
  upgrade past 2.0.6). At that point Path 1 becomes a clean win — get
  it in.
- **A real user asks** to import a Scaniverse / SPZ file into Splatpipe.
  At that point Path 1 becomes the lowest-friction answer (decode at
  ingest, even if only legacy SPZ works initially).
- **Spark releases past 2.0.0 with SPZ 4** — trivial path-1 follow-up
  (Spark's runtime already loads `.spz`, just bump the version cap).
- **A user wants in-browser SPZ playback** (drop-a-permalink-and-it-renders
  workflow) — that's Path 2; reach for `@spz-loader/playcanvas`.

## References saved during research

- Niantic blog: https://www.nianticspatial.com/blog/spz4
- Reference repo: https://github.com/nianticlabs/spz (MIT, C++ + Python +
  WASM, README.md + `src/cc/load-spz.cc` carry the format details)
- Adobe WASM npm: `@adobe/spz`
- Babylon loader: `packages/dev/loaders/src/SPLAT/spz.ts` in BabylonJS;
  feature PR 18267 (raymondyfei, merged 2026-04-15)
- Community PlayCanvas loader: `@spz-loader/playcanvas` (npm 0.3.1, MIT,
  drumath2237). Backed by `@spz-loader/core`.
- PoC repos confirming the PC loader works: drumath2237's
  `playcanvas-spz-investigation`, `learning-2025-playcanvas-spz`.
