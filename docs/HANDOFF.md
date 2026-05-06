# Splatpipe — Handoff to OpenAI Codex

Last updated: 2026-04-17, just after `v0.7.0` was tagged.

## Read these first (10 minutes)

1. **`CLAUDE.md`** — the source of truth for project conventions, architecture,
   design decisions, package layout, tool chain, and release process. Every
   convention that matters lives here. Read it end-to-end. Don't skim the
   "Quality Discipline" section — those rules came from real bugs.
2. **`CHANGELOG.md`** — what shipped in each release. The `[Unreleased]` section
   is currently empty (we just cut `v0.7.0`); next user-facing change lands
   there.
3. **`README.md`** — public-facing pipeline overview.

CLAUDE.md is written for Claude Code but applies verbatim to any agent. The
"using-superpowers" / "Skill" tool references are Claude-specific and can be
ignored — the underlying *guidance* still applies.

## Where we are right now

- Branch: `main`, in sync with `origin/main`.
- Latest tag: `v0.7.0` (released 2026-04-17 — bumps Python floor to 3.12, adds
  Windows CI runner, drops `is_junction` polyfills).
- Recent release run: `v0.5.0` → `v0.6.0` (camera paths + Spark 2 renderer) →
  `v0.6.1` (DCC bridge for Max + Blender) → `v0.6.2` / `v0.6.3` (DCC math fixes)
  → `v0.7.0`. Read those CHANGELOG entries before touching the camera-path,
  Spark, or DCC bridge code — there is a lot of subtle coordinate-frame math.
- `pytest --co -q` → **439 tests**. Full suite runs in ~22 s.
- `ruff check src/ tests/` → clean.

## Working tree state (after `v0.7.0` tag)

```
M .mcp.json
?? docs/plans/
?? docs/postshot_feature_request.md
?? docs/HANDOFF.md          ← this file
```

- **`.mcp.json`** — modified locally to hardcode
  `C:\Users\sasch\miniconda3\python.exe` for the LichtFeld MCP server. **Do not
  commit.** Repo version uses `"command": "python"` (PATH-resolved).
- **`docs/plans/2026-02-14_collision.md`** — design doc for the camera
  constraints / collision feature. **Phase 1 (camera constraints) shipped in
  v0.5.0.** Phase 2 (Ammo.js collision mesh against a Reality Capture mesh)
  is the obvious next chunk of viewer work if the user wants to continue
  there. Self-hosting Ammo WASM is required (no ESM CDN).
- **`docs/postshot_feature_request.md`** — feature request drafted for the
  Jawset/Postshot devs (CLI flag to retrain an existing `.psht`). External
  ask, not internal work.

If stray screenshots (`*.png` at repo root) or a `.playwright-mcp/` folder
reappear after debugging sessions, neither belongs in the repo — delete or
extend `.gitignore`.

## Known doc drift (small, safe wins)

- `CLAUDE.md` Quick Start says **"429 tests, ~22s"** — actual is **439**.
- `README.md` (line ~166) says **"Run all 417 tests"** — actual is **439**.
  The badge on line 15 is already correct (`tests-439%20passed`).

These count as user-facing doc fixes and qualify for a CHANGELOG entry under
"Changed" only if they ride along with other work; a standalone fix can skip
the CHANGELOG (internal-only doc cleanup is exempt per CLAUDE.md rule 4).

## Project conventions most likely to bite

These are pulled from CLAUDE.md but worth re-stating because they are
non-obvious and we have lost time to all of them:

1. **Every user-facing change → `CHANGELOG.md` `[Unreleased]` entry, before
   commit.** Internal-only changes (CI config, test refactors, this file)
   are exempt.
2. **Version lives in exactly one place: `pyproject.toml` → `[project].version`.**
   Update at release time, nowhere else.
3. **SemVer, pre-1.0 dialect:** breaking changes are allowed in MINOR bumps;
   document them clearly. PATCH = bug fixes / lint / no-behavior refactor.
   MINOR = new features, CLI commands, pipeline steps, config options.
4. **Pre-push doc check:** confirm test count, Package Layout in CLAUDE.md,
   README pipeline diagram + CLI reference, and `[Unreleased]` against actual
   changes. The release process in CLAUDE.md spells out the exact sequence.
5. **Debug data over fallbacks — no `try/except` to swallow errors.** Every
   step writes a `_debug.json` with full command, stdin/stdout/stderr, file
   stats, metrics, timing, environment. This is the most-broken-when-violated
   convention in the codebase.
6. **Run the external tool first; then write the parser.** Postshot v1.0.185's
   stdout was `Training Radiance Field: 2%, ... 46 Steps of 2.00 kSteps,
   1.38 MSplats` — completely different from the assumed `Step X/Y` format.
   Hours wasted; 30-second fix once real output was inspected. Same lesson
   applies to LichtFeld Studio, splat-transform, etc.
7. **Inspect real directory contents before writing globs / path joins / clear
   operations.** Listing the folder takes 10 seconds and prevents an entire
   class of bugs.
8. **Windows path strings as dict keys are dangerous.** URL params use `/`,
   `str(Path(...))` on Windows uses `\`. Normalize through `Path()` before
   using as a key. `runner.py` has `_normalize_key()` for this.
9. **State lifecycle thinking** before touching `state.json` / step status /
   SSE: server restart, SSE disconnect, navigation away, cancel button,
   re-run after partial failure. CLAUDE.md "State Lifecycle Checklist" is
   the canonical version.
10. **"Would I ship this?"** Walk through every code path that renders a UI
    change and look at the actual visual output. A progress bar at 0% with
    no animation looks broken, not "in progress."

## Tool chain pins (current as of v0.7.0)

| Tool | Version | Notes |
|------|---------|-------|
| Python floor | 3.12 | Bumped from 3.11 in v0.7.0; uses native `Path.is_junction()`. |
| PlayCanvas | **2.17.0 exactly** | 2.17.1 / 2.17.2 have an engine-update-loop regression that breaks splat rendering. Pin is intentional. |
| `@playcanvas/splat-transform` | ^2.0.4 | LOD assembly + SOG compression. v2.0 refactored progress output — parser handles the `▸ [N/M] X_Y` chunk format and we pass `--no-tty` to keep stderr line-stable. |
| `@sparkjsdev/spark` | 2.0.0 | Spark 2 renderer (`scene.rad`). |
| `three` | 0.180.0 | Spark peer dep — must match. |
| Postshot CLI | 1.0.331 | `--pose-quality` 1=Fast, 4=Best, default 3. Splat3 / MCMC profiles via `-p`. |
| LichtFeld Studio | 0.5.1 | Always `--headless --train`; PPISP optional. CUDA 12.8+ / driver 570+. |
| Spark Rust toolchain | sibling clone | `H:/001_ProjectCache/1000_Coding/spark` or `$SPARK_REPO`. First `cargo build --release` ~2 min; subsequent runs use cached `build-lod` in `~/.cache/splatpipe/spark/`. |

## Likely next chunks of work

In rough priority order, based on what's sitting around the repo:

1. **Phase 2 collision** (`docs/plans/2026-02-14_collision.md`) — Ammo.js
   collision mesh against a Reality Capture GLB. Requires self-hosting Ammo
   WASM. Outlined in the plan but not started.
2. **Doc-drift cleanup** — bring CLAUDE.md ("429 tests") and README ("417
   tests") in line with the actual 439. Trivial; can ride with anything.
3. **DCC bridge follow-up** — manual smoke tests for the Max + Blender plugin
   buttons (D4 / D5 / D8 in the original plan) are still user-facing-only and
   not covered by CI. v0.6.3 already fixed the Max math; if more bugs surface
   in dogfooding, they go to a `v0.6.4` patch.
4. **Whatever the user actually wants** — ask them. The list above is inferred
   from leftover artifacts, not from a stated roadmap.

## Codex-specific notes

- This repo has historically been worked on through Claude Code. Some files
  reference Claude-only constructs that Codex should *not* try to use:
  - The `memory/` directory at
    `C:\Users\sasch\.claude\projects\H--001-ProjectCache-1000-Coding-Splatpipe\memory\`
    is a Claude-Code-only persistence layer. Codex cannot read it and should
    not try to write to it. Useful learnings live in `CLAUDE.md` or `docs/`.
  - `.mcp.json` is the Claude-Code MCP server registry. Codex has its own
    MCP mechanism — leave the file alone unless explicitly asked.
  - References to "Skill", "superpowers:*", or "/loop" / "/schedule" in
    other docs are Claude-specific tooling. Ignore them.
- If you need to durably record agent-facing instructions for Codex
  specifically, the conventional name is `AGENTS.md` at repo root. We
  don't have one yet — feel free to create it if it would help, and have
  it point at `CLAUDE.md` rather than duplicating content.
- The release flow at the bottom of `CLAUDE.md` ("Release Process") works
  identically under Codex — it's just `git`, `gh`, and editor commands.

## Quick "am I set up?" checklist

```bash
cd H:/001_ProjectCache/1000_Coding/Splatpipe
pip install -e ".[dev,web]"
pytest --co -q | tail -1          # expect: 439 tests collected
ruff check src/ tests/             # expect: All checks passed!
git status --short                 # expect: M .mcp.json + ?? docs/...
git log --oneline -1               # expect: latest commit + v0.7.0 tag nearby
splatpipe --help                   # CLI sanity check
```

If any of those don't match, something has drifted since this handoff was
written — start by reading the most recent commits to find out what.
