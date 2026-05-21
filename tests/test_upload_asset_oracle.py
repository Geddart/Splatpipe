"""Server-behaviour oracle for ``infra/php/upload-asset.php``.

``upload-asset.php`` is the http-mode (``save_backend="http"``) FILE-UPLOAD
sibling of ``save-camera.php``. The deployed Spark viewers are static CDN
bundles with no backend; the keyframe-editor's panorama / audio file
pickers used to POST to ``../upload-image`` / ``../upload-audio``, which
only exist on the splatpipe web DASHBOARD. On a live CDN scene those 404
silently -- the upload feature was DEAD (UX-H3). ``upload-asset.php`` is the
replacement: the browser POSTs the picked file with the same per-scene
bearer token the Save button uses; this endpoint authenticates, validates
(extension allow-list + size cap + filename sanitisation, mirroring the
#107 / bug-audit #7 hardening in ``web/routes/projects.py``), then PUTs the
file to Bunny Storage at ``<slug>/<filename>``.

This module drives the *real* endpoint (authenticated multipart POST
through ``php -S``) and asserts its security gates:

  * OPTIONS preflight -> 204 (CORS).
  * GET / wrong method -> 405.
  * missing / bad bearer -> 401 and no side effect.
  * bad slug (traversal etc.) -> 400.
  * wrong extension (e.g. ``.exe``) -> 415.
  * oversize image (> 5 MiB) -> 413.
  * a FULLY-VALID request (good bearer + good slug + allow-listed ext +
    under-cap size) passes every gate and reaches the Bunny-push step --
    which, with NO ``.bunny_env`` configured in the test docroot, returns
    503 "asset storage is not configured". That 503 is the proof that
    auth + slug + filename + extension + size ALL passed (everything up to
    the CDN PUT). The live CDN round-trip is verified out-of-band by the
    Phase 11E curl checks against the deployed geddart.de endpoint.

Gated with ``skipif(shutil.which("php") is None)`` so the suite stays green
where PHP is absent (the project's local box has no PHP; Strato PHP 8.4 is
the deployment target / CI-Ubuntu runs it). When ``php`` IS present the
endpoint is really run (project hard rule: run the tool, capture real
output, then assert).
"""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import pytest

PHP = shutil.which("php")
PHP_ROOT = Path(__file__).parent.parent / "infra" / "php"
UPLOAD_PHP = PHP_ROOT / "upload-asset.php"

pytestmark = pytest.mark.skipif(
    PHP is None,
    reason=(
        "php CLI not on PATH -- oracle needs `php` present to drive the real "
        "endpoint (Strato PHP 8.4 is the deploy target; CI/dev without PHP "
        "skips this). Verify on a PHP host: "
        "`php -l infra/php/upload-asset.php && pytest "
        "tests/test_upload_asset_oracle.py`."
    ),
)

# The bearer the test scene's .author-token holds. Constant-time-compared
# server side; never echoed.
TOKEN = "uploadtest-token-0123456789abcdef"
SLUG = "oracle-upload-scene"

_MULTIPART_BOUNDARY = "----splatpipeUploadOracleBoundary"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _multipart_body(
    *, slug: str | None, filename: str | None, content: bytes,
    field: str = "file",
) -> bytes:
    """Build a minimal multipart/form-data body with an optional slug
    field + a file part. Mirrors what the browser FormData sends."""
    crlf = b"\r\n"
    b = _MULTIPART_BOUNDARY.encode()
    parts: list[bytes] = []
    if slug is not None:
        parts += [
            b"--" + b,
            b'Content-Disposition: form-data; name="slug"',
            b"",
            slug.encode(),
        ]
    if filename is not None:
        parts += [
            b"--" + b,
            (
                b'Content-Disposition: form-data; name="'
                + field.encode()
                + b'"; filename="'
                + filename.encode()
                + b'"'
            ),
            b"Content-Type: application/octet-stream",
            b"",
            content,
        ]
    parts += [b"--" + b + b"--", b""]
    return crlf.join(parts)


@pytest.fixture(scope="module")
def php_server(tmp_path_factory):
    """A ``php -S`` instance serving a tmp docroot with the real
    ``upload-asset.php`` + a ``scenes/<slug>/.author-token``.

    Deliberately NO ``.bunny_env`` in the docroot: a fully-valid POST then
    reaches the Bunny step and returns 503 (asset storage not configured),
    which proves every auth/validation gate before it passed.

    Yields ``base_url``.
    """
    assert UPLOAD_PHP.exists(), f"missing artifact: {UPLOAD_PHP}"
    docroot = tmp_path_factory.mktemp("php_upload_docroot")
    shutil.copy(UPLOAD_PHP, docroot / "upload-asset.php")
    scene_dir = docroot / "scenes" / SLUG
    scene_dir.mkdir(parents=True)
    (scene_dir / ".author-token").write_text(TOKEN, encoding="utf-8")

    port = _free_port()
    proc = subprocess.Popen(
        [
            PHP, "-d", "display_errors=0",
            "-d", "upload_max_filesize=64M", "-d", "post_max_size=64M",
            "-S", f"127.0.0.1:{port}", "-t", str(docroot),
        ],
        cwd=str(docroot),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    base = f"http://127.0.0.1:{port}"
    deadline = time.time() + 15
    while time.time() < deadline:
        if proc.poll() is not None:
            out, err = proc.communicate()
            raise RuntimeError(
                f"php -S exited early: {err.decode(errors='replace')}"
            )
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.25):
                break
        except OSError:
            time.sleep(0.1)
    else:
        proc.terminate()
        raise RuntimeError("php -S did not start within 15s")

    yield base

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def _post_multipart(
    base: str, body: bytes, *, token: str | None = TOKEN, method: str = "POST",
):
    """Real authenticated multipart request to the live endpoint. Returns
    ``(status, json_or_text)``."""
    req = urllib.request.Request(
        f"{base}/upload-asset.php", data=body, method=method
    )
    req.add_header(
        "Content-Type", f"multipart/form-data; boundary={_MULTIPART_BOUNDARY}"
    )
    if token is not None:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        resp = urllib.request.urlopen(req, timeout=20)
        raw, status = resp.read(), resp.status
    except urllib.error.HTTPError as e:
        raw, status = e.read(), e.code
    text = raw.decode("utf-8", errors="replace")
    try:
        return status, json.loads(text)
    except json.JSONDecodeError:
        return status, text


# A tiny but valid 1x1 PNG (the smallest legal PNG). Used for the
# happy-path-up-to-Bunny + the wrong-extension test (content is irrelevant
# to the extension gate, but a real PNG keeps the fixture honest).
_TINY_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c6360000002000154a24f9e0000000049454e44ae426082"
)


# ---------------------------------------------------------------------------
# CORS + method gates
# ---------------------------------------------------------------------------
def test_options_preflight_is_204(php_server):
    base = php_server
    status, _ = _post_multipart(base, b"", token=None, method="OPTIONS")
    assert status == 204


def test_get_is_405(php_server):
    base = php_server
    status, _ = _post_multipart(base, b"", token=None, method="GET")
    assert status == 405


# ---------------------------------------------------------------------------
# auth gates (this is auth + FS/CDN-write code)
# ---------------------------------------------------------------------------
def test_bad_bearer_is_401(php_server):
    base = php_server
    body = _multipart_body(slug=SLUG, filename="pano.jpg", content=_TINY_PNG)
    status, payload = _post_multipart(base, body, token="wrong-token")
    assert status == 401
    assert isinstance(payload, dict) and payload.get("ok") is False


def test_missing_bearer_is_401(php_server):
    base = php_server
    body = _multipart_body(slug=SLUG, filename="pano.jpg", content=_TINY_PNG)
    status, payload = _post_multipart(base, body, token=None)
    assert status == 401
    assert isinstance(payload, dict) and payload.get("ok") is False


# ---------------------------------------------------------------------------
# slug + filename + extension + size gates
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "bad_slug",
    ["../escape", "a/b", "a\\b", "UPPER", "with space", "dot.dot", "", "x" * 65],
)
def test_bad_slug_rejected_400(php_server, bad_slug):
    base = php_server
    body = _multipart_body(slug=bad_slug, filename="pano.jpg", content=_TINY_PNG)
    status, payload = _post_multipart(base, body)
    assert status == 400, f"slug {bad_slug!r} should be rejected, got {status}"
    assert isinstance(payload, dict) and payload.get("ok") is False


@pytest.mark.parametrize(
    "bad_name",
    ["../evil.jpg", "a/b.png", "a\\b.png", "C:evil.jpg", ".hidden.jpg", "."],
)
def test_filename_traversal_rejected_400(php_server, bad_name):
    """Filenames with separators / drive-colon / dotfile are rejected
    BEFORE any write (mirrors the #107 Python route hardening)."""
    base = php_server
    body = _multipart_body(slug=SLUG, filename=bad_name, content=_TINY_PNG)
    status, payload = _post_multipart(base, body)
    assert status == 400, f"name {bad_name!r} should be rejected, got {status}"
    assert isinstance(payload, dict) and payload.get("ok") is False


@pytest.mark.parametrize("bad_ext_name", ["evil.exe", "script.php", "x.svg", "noext"])
def test_wrong_extension_is_415(php_server, bad_ext_name):
    """Anything not on the image/audio allow-list -> 415 (deny-by-default)."""
    base = php_server
    body = _multipart_body(slug=SLUG, filename=bad_ext_name, content=_TINY_PNG)
    status, payload = _post_multipart(base, body)
    assert status == 415, f"ext {bad_ext_name!r} should be 415, got {status}"
    assert isinstance(payload, dict) and payload.get("ok") is False


def test_oversize_image_is_413(php_server):
    """An image over the 5 MiB cap -> 413 (the cap is enforced on the real
    received file size, not the client-reported size)."""
    base = php_server
    big = b"\x89PNG\r\n\x1a\n" + b"\x00" * (5 * 1024 * 1024 + 64)
    body = _multipart_body(slug=SLUG, filename="huge.png", content=big)
    status, payload = _post_multipart(base, body)
    assert status == 413
    assert isinstance(payload, dict) and payload.get("ok") is False


def test_empty_file_is_400(php_server):
    base = php_server
    body = _multipart_body(slug=SLUG, filename="empty.jpg", content=b"")
    status, payload = _post_multipart(base, body)
    # An empty multipart file part registers as no upload (UPLOAD_ERR_NO_FILE)
    # OR an empty body -> either way a 400.
    assert status == 400
    assert isinstance(payload, dict) and payload.get("ok") is False


@pytest.mark.parametrize(
    "ok_name",
    [
        "pano.jpg", "pano.jpeg", "backdrop.png",        # images
        "loop.mp3", "amb.wav", "track.ogg", "v.opus",   # audio
        "x.m4a", "y.aac", "z.flac", "w.webm",
    ],
)
def test_valid_upload_passes_all_gates_then_503_without_bunny(php_server, ok_name):
    """A FULLY-VALID request (good bearer + good slug + allow-listed ext +
    under-cap size) passes EVERY auth/validation gate and reaches the
    Bunny-push step. With NO ``.bunny_env`` in the test docroot that step
    returns 503 "asset storage is not configured" -- which is the proof
    that auth + slug + filename + extension + size ALL passed. (The live
    CDN PUT is verified out-of-band by the Phase 11E curl checks.)"""
    base = php_server
    body = _multipart_body(slug=SLUG, filename=ok_name, content=_TINY_PNG)
    status, payload = _post_multipart(base, body)
    assert status == 503, (
        f"valid upload {ok_name!r} should reach the (unconfigured) Bunny "
        f"step and 503, got {status} -- {payload}"
    )
    assert isinstance(payload, dict) and payload.get("ok") is False
    # The 503 message must name the storage-not-configured cause (so the
    # gate ordering is unambiguous -- it is NOT a validation rejection).
    assert "storage" in json.dumps(payload).lower()


def test_unique_named_uploads_all_reach_storage_step(php_server):
    """Sanity that the gate ordering is stable across distinct filenames
    (a fresh random name each call still passes validation -> 503)."""
    base = php_server
    name = f"_uploadtest_{uuid.uuid4().hex[:8]}.jpg"
    body = _multipart_body(slug=SLUG, filename=name, content=_TINY_PNG)
    status, payload = _post_multipart(base, body)
    assert status == 503
    assert isinstance(payload, dict) and payload.get("ok") is False


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
