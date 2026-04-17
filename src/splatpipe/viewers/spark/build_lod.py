"""Wrapper around Spark's Rust ``build-lod`` CLI.

``build-lod`` (sparkjsdev/spark, MIT) takes a splat file (.ply/.spz/.sog/.splat/.ksplat)
and emits ``<input>-lod.rad`` — a precomputed LoD splat tree that Spark's
viewer streams via HTTP Range requests when loaded with
``new SplatMesh({url, paged: true})``.

This wrapper:

  * Detects the toolchain (cached binary → ``$SPARK_REPO`` release → cargo).
  * Caches results by ``sha256(input)+build-lod git rev+flags`` so re-assembling
    a project is instant when the input PLY hasn't changed.
  * Streams stderr to a callable so the FastAPI dashboard can show progress.
  * Returns the canonical cached ``.rad`` path; the assembler ``shutil.copy``s
    it into ``05_output/scene.rad``.

Verified empirically (2026-04): a 382 MB PLY builds to a 122 MB .rad in ~33 s
on a workstation GPU. First-time ``cargo build --release`` of the workspace
takes ~2 min — pre-cached after that.
"""

from __future__ import annotations

import hashlib
import os
import platform
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

# Default location for the user's Spark clone. Override with SPARK_REPO env var.
DEFAULT_SPARK_REPO_HINTS = (
    Path("H:/001_ProjectCache/1000_Coding/spark"),
    Path.home() / "spark",
    Path.cwd().parent / "spark",
)

CACHE_DIR = Path.home() / ".cache" / "splatpipe"
RAD_CACHE = CACHE_DIR / "rad"
BIN_CACHE = CACHE_DIR / "spark"
BIN_NAME = "build-lod.exe" if os.name == "nt" else "build-lod"


class BuildLodError(RuntimeError):
    """Raised when ``build-lod`` is unavailable or fails."""


@dataclass
class Toolchain:
    """Resolved path to invoke ``build-lod``.

    `cmd_prefix` is the argv prefix; callers append the input file(s) and flags.
    `cwd` is the working directory for subprocess (matters for cargo).
    `version` is a short identifier (binary path or git rev) used in cache keys.
    """

    cmd_prefix: list[str]
    cwd: Path | None
    version: str
    is_cargo: bool


def detect_toolchain(spark_repo: Path | None = None) -> Toolchain:
    """Resolve how to invoke ``build-lod``. Order:

    1. Pre-built cached binary at ``~/.cache/splatpipe/spark/build-lod[.exe]``
       (populated on first successful cargo build — subsequent runs skip cargo).
    2. ``$SPARK_REPO/rust/build-lod/target/release/build-lod[.exe]`` if it
       already exists from a manual ``cargo build``.
    3. ``cargo run --manifest-path $SPARK_REPO/rust/build-lod/Cargo.toml --release --``
       — first-call cost ~1–2 min, copies the built binary into step 1's
       cache afterwards.
    4. Friendly ``BuildLodError`` listing install steps.
    """
    cached = BIN_CACHE / BIN_NAME
    if cached.is_file():
        return Toolchain(cmd_prefix=[str(cached)], cwd=None, version=str(cached), is_cargo=False)

    repo = spark_repo or _find_spark_repo()
    if repo is None:
        raise BuildLodError(
            "Cannot locate the sparkjsdev/spark repo. Either:\n"
            "  • clone it next to this project: "
            "  git clone https://github.com/sparkjsdev/spark "
            "H:/001_ProjectCache/1000_Coding/spark\n"
            "  • or set SPARK_REPO=/path/to/spark in the environment.\n"
            "And install Rust + cargo from https://rustup.rs/ if you haven't."
        )

    crate_dir = repo / "rust" / "build-lod"
    manifest = crate_dir / "Cargo.toml"
    if not manifest.is_file():
        raise BuildLodError(
            f"SPARK_REPO points to {repo} but rust/build-lod/Cargo.toml is missing. "
            f"Make sure the clone is complete (it includes a Rust workspace under rust/)."
        )

    prebuilt = repo / "rust" / "target" / "release" / BIN_NAME
    if prebuilt.is_file():
        return Toolchain(
            cmd_prefix=[str(prebuilt)],
            cwd=None,
            version=_git_rev_short(repo) or str(prebuilt),
            is_cargo=False,
        )

    if shutil.which("cargo") is None:
        raise BuildLodError(
            f"Found Spark repo at {repo}, but `cargo` is not on PATH. "
            f"Install the Rust toolchain from https://rustup.rs/ and retry."
        )

    rev = _git_rev_short(repo) or "unknown"
    return Toolchain(
        cmd_prefix=["cargo", "run", "--manifest-path", str(manifest), "--release", "--"],
        cwd=crate_dir,
        version=rev,
        is_cargo=True,
    )


def build(
    input_ply: Path,
    *,
    quality: bool = True,
    extra_flags: list[str] | None = None,
    on_progress: Callable[[str], None] | None = None,
    spark_repo: Path | None = None,
) -> Path:
    """Produce a ``.rad`` for ``input_ply``. Returns path to cached file.

    Idempotent: re-runs are cache hits (constant-time) when the input file's
    mtime + size + sha256 are unchanged.
    """
    input_ply = Path(input_ply).resolve()
    if not input_ply.is_file():
        raise FileNotFoundError(input_ply)

    toolchain = detect_toolchain(spark_repo)

    flag_str = "q" if quality else "n"
    if extra_flags:
        flag_str += "+" + ",".join(sorted(extra_flags))

    cache_key = _compute_cache_key(input_ply, toolchain.version, flag_str)
    RAD_CACHE.mkdir(parents=True, exist_ok=True)
    cached_rad = RAD_CACHE / f"{cache_key}.rad"
    if cached_rad.is_file():
        if on_progress:
            on_progress(f"[build-lod] cache HIT: {cached_rad.name}")
        return cached_rad

    if on_progress:
        on_progress("[build-lod] cache MISS, building (~33s/GB; first cargo build ~2 min)")

    # Run build-lod with input copied into a temp dir so it can write
    # `<basename>-lod.rad` next to the input without polluting 04_review/.
    with tempfile.TemporaryDirectory(prefix="splatpipe-build-lod-") as tmpdir:
        tmp_input = Path(tmpdir) / input_ply.name
        # Hardlink if same volume (instant), else copy.
        try:
            os.link(input_ply, tmp_input)
        except OSError:
            shutil.copy2(input_ply, tmp_input)

        argv = list(toolchain.cmd_prefix)
        if quality:
            argv.append("--quality")
        else:
            argv.append("--quick")
        if extra_flags:
            argv.extend(extra_flags)
        argv.append(str(tmp_input))

        _run_subprocess(argv, cwd=toolchain.cwd, on_progress=on_progress)

        # build-lod writes <basename>-lod.{rad,spz}; we asked for --quality which
        # produces .rad by default. Glob both to be safe across version drift.
        produced = list(Path(tmpdir).glob(f"{tmp_input.stem}-lod.*"))
        produced = [p for p in produced if p.suffix in {".rad", ".spz"}]
        if not produced:
            raise BuildLodError(
                f"build-lod did not produce a .rad or .spz next to {tmp_input}. "
                f"Files in temp dir: {[p.name for p in Path(tmpdir).iterdir()]}"
            )
        winner = produced[0]

        # Atomic move into the cache.
        tmp_cache = cached_rad.with_suffix(cached_rad.suffix + ".tmp")
        shutil.move(str(winner), str(tmp_cache))
        os.replace(tmp_cache, cached_rad)

    # If we just used cargo for the first time, copy the built binary into
    # the cache so future builds skip the cargo overhead.
    if toolchain.is_cargo:
        repo = spark_repo or _find_spark_repo()
        if repo:
            built = repo / "rust" / "target" / "release" / BIN_NAME
            if built.is_file():
                BIN_CACHE.mkdir(parents=True, exist_ok=True)
                try:
                    shutil.copy2(built, BIN_CACHE / BIN_NAME)
                    if on_progress:
                        on_progress(f"[build-lod] cached binary at {BIN_CACHE / BIN_NAME}")
                except OSError as e:
                    if on_progress:
                        on_progress(f"[build-lod] could not cache binary: {e}")

    if on_progress:
        on_progress(f"[build-lod] done → {cached_rad.name}")
    return cached_rad


# ---- helpers --------------------------------------------------------------


def _find_spark_repo() -> Path | None:
    env = os.environ.get("SPARK_REPO")
    if env:
        p = Path(env)
        if p.is_dir():
            return p
    for hint in DEFAULT_SPARK_REPO_HINTS:
        if (hint / "rust" / "build-lod" / "Cargo.toml").is_file():
            return hint
    return None


def _git_rev_short(repo: Path) -> str | None:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(repo),
            stderr=subprocess.DEVNULL,
            text=True,
        )
        return out.strip()
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return None


def _compute_cache_key(input_ply: Path, version: str, flags: str) -> str:
    """Cache key. Uses sha256 of the file (slow for huge files but reliable).

    Future optimisation (B7 in plan): mtime+size pre-check with sha256 only on
    miss. For now, full hash — typical Splatpipe PLYs are 100 MB–2 GB and
    sha256 streams at ~500 MB/s on modern hardware, so cost is bounded.
    """
    h = hashlib.sha256()
    with open(input_ply, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    digest = h.hexdigest()[:16]
    return f"{digest}-{version[:7]}-{flags}"


def _run_subprocess(
    argv: list[str],
    *,
    cwd: Path | None,
    on_progress: Callable[[str], None] | None,
) -> None:
    """Run argv, stream merged stdout/stderr line-by-line via on_progress."""
    proc = subprocess.Popen(
        argv,
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            if on_progress:
                on_progress(line.rstrip())
    finally:
        rc = proc.wait()
    if rc != 0:
        raise BuildLodError(f"build-lod exited with code {rc} (argv={argv!r})")


def verify_toolchain(spark_repo: Path | None = None) -> dict:
    """Sanity check the toolchain. Returns metadata; raises BuildLodError on failure.

    Useful to call early in `splatpipe assemble` before slow asset prep so the
    user sees a clear error if Rust/SPARK_REPO is missing.
    """
    tc = detect_toolchain(spark_repo)
    return {
        "command": tc.cmd_prefix,
        "cwd": str(tc.cwd) if tc.cwd else None,
        "version": tc.version,
        "is_cargo": tc.is_cargo,
        "platform": platform.platform(),
    }
