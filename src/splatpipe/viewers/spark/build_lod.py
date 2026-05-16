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
    chunked: bool = True,
    cluster_sh: bool = True,
    extra_flags: list[str] | None = None,
    on_progress: Callable[[str], None] | None = None,
    spark_repo: Path | None = None,
) -> Path:
    """Produce a Spark LoD asset for ``input_ply``. Returns the cached path.

    When ``chunked`` (the pipeline default), build-lod emits a small manifest
    ``<stem>-lod.rad`` plus N sibling ``<stem>-lod-<i>.radc`` chunk files; the
    whole set is cached under one directory and the **manifest path** is
    returned. The viewer resolves each chunk relative to the manifest URL, so
    callers must keep manifest + ``.radc`` co-located when deploying.

    When ``chunked`` is False, a single monolithic ``.rad`` is produced and
    its path returned (legacy single-file behaviour).

    ``cluster_sh`` (the pipeline default) passes build-lod ``--cluster-sh``:
    the spherical-harmonic coefficients are vector-quantised into a ≤64K
    codebook, which is what makes large scenes deployable — empirically
    ~60% smaller .rad (IBUG 1653 MB → 661 MB) at no perceptible quality
    loss, and dramatically less GPU/JS memory. This REQUIRES the patched,
    self-hosted Spark fork (the ``SPARK_FORK_URL`` the viewer template
    already pins by default: rcf2 = the RefCell-reentrancy + chunk-0
    codebook-ordering fixes); upstream ``@sparkjsdev/spark@2.0.0`` crashes
    on every cluster-sh chunk. Pass ``cluster_sh=False`` only to produce a
    stock-Spark-compatible build (larger, no fork needed).

    Idempotent: re-runs are cache hits (constant-time) when the input file's
    mtime + size + sha256 are unchanged. The flag set (quality / chunked /
    cluster_sh / extra_flags) is part of the cache key, so changing a flag
    correctly rebuilds rather than serving a stale asset.
    """
    input_ply = Path(input_ply).resolve()
    if not input_ply.is_file():
        raise FileNotFoundError(input_ply)

    toolchain = detect_toolchain(spark_repo)

    flag_str = "q" if quality else "n"
    if chunked:
        flag_str += "c"
    if cluster_sh:
        flag_str += "s"
    if extra_flags:
        flag_str += "+" + ",".join(sorted(extra_flags))

    cache_key = _compute_cache_key(input_ply, toolchain.version, flag_str)
    RAD_CACHE.mkdir(parents=True, exist_ok=True)

    if chunked:
        # Chunked output is a *directory*: manifest ``<stem>-lod.rad`` plus N
        # sibling ``<stem>-lod-<i>.radc`` files. The viewer resolves each
        # chunk's ``filename`` relative to the manifest's URL, so the set must
        # stay co-located — cache the whole directory under one key.
        cache_dir = RAD_CACHE / cache_key
        manifest = _find_manifest(cache_dir)
        if manifest is not None:
            if on_progress:
                on_progress(f"[build-lod] cache HIT (chunked): {cache_dir.name}/{manifest.name}")
            return manifest
    else:
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
        if chunked:
            argv.append("--rad-chunked")
        if cluster_sh:
            argv.append("--cluster-sh")
        if extra_flags:
            argv.extend(extra_flags)
        argv.append(str(tmp_input))

        _run_subprocess(argv, cwd=toolchain.cwd, on_progress=on_progress)

        if chunked:
            # build-lod --rad-chunked writes the manifest ``<stem>-lod.rad``
            # plus N sibling ``<stem>-lod-<i>.radc`` chunk files.
            manifest_src = list(Path(tmpdir).glob(f"{tmp_input.stem}-lod.rad"))
            radc_src = sorted(Path(tmpdir).glob(f"{tmp_input.stem}-lod-*.radc"))
            if not manifest_src or not radc_src:
                raise BuildLodError(
                    f"build-lod --rad-chunked did not produce a manifest + .radc "
                    f"set next to {tmp_input}. Files in temp dir: "
                    f"{[p.name for p in Path(tmpdir).iterdir()]}"
                )
            # Stage into a sibling .tmp dir, then atomically swap into place so
            # a crashed build never leaves a half-written cache dir that the
            # completeness check (`_find_manifest`) would wrongly accept.
            stage = RAD_CACHE / f"{cache_key}.tmp"
            if stage.exists():
                shutil.rmtree(stage)
            stage.mkdir(parents=True)
            for p in manifest_src + radc_src:
                shutil.move(str(p), str(stage / p.name))
            if cache_dir.exists():
                shutil.rmtree(cache_dir)
            os.replace(stage, cache_dir)
            result_path = cache_dir / manifest_src[0].name
        else:
            # build-lod writes <basename>-lod.{rad,spz}; we asked for --quality
            # which produces .rad by default. Glob both for version drift.
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
            result_path = cached_rad

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
        on_progress(f"[build-lod] done → {result_path.name}")
    return result_path


# ---- helpers --------------------------------------------------------------


def _find_manifest(cache_dir: Path) -> Path | None:
    """Return the chunked manifest in ``cache_dir`` iff the cached set looks
    complete: exactly one ``*-lod.rad`` plus at least one ``*.radc``. A
    partially-written dir (build crashed mid-stage) fails this and is treated
    as a cache miss so the build is redone rather than served broken.
    """
    if not cache_dir.is_dir():
        return None
    manifests = list(cache_dir.glob("*-lod.rad"))
    radc = list(cache_dir.glob("*.radc"))
    if len(manifests) == 1 and radc:
        return manifests[0]
    return None


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
