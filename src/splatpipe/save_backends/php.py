"""``php`` save backend — THIN: the save runs browser→PHP, not in Python.

This backend represents "this scene's viewer POSTs the camera-scope patch
directly to an external ``save.php`` endpoint". The actual fetch → merge →
write happens server-side in the PHP artifact (``infra/php/save.php``, a
SEPARATE later task — Task 6b), NOT here. The splatpipe-side role is
**config only**: hold the configured endpoint URL and validate it.

``save_keyframes`` is therefore deliberately NOT a Python save path — it
returns an unsuccessful :class:`SaveResult` whose message explains the save
is performed in-browser against the configured endpoint.
"""

from __future__ import annotations

from .base import SaveBackend, SaveResult, _looks_like_url


class PhpEndpointBackend(SaveBackend):
    """Config-only adapter for a browser→PHP save endpoint."""

    @property
    def name(self) -> str:
        return "php"

    @property
    def endpoint(self) -> str:
        """The configured ``save.php`` URL the viewer POSTs to."""
        return (self.config.get("save_backend", {}) or {}).get("endpoint", "") or ""

    def save_keyframes(self, slug: str, payload: dict, token: str) -> SaveResult:
        return SaveResult(
            backend=self.name,
            success=False,
            slug=slug,
            error=(
                "php backend performs the save in-browser (viewer POSTs to "
                f"the configured endpoint {self.endpoint!r}); there is no "
                "Python save path — the splatpipe-side role is config only."
            ),
        )

    def validate_environment(self) -> tuple[bool, str]:
        ep = self.endpoint
        if not ep:
            return False, "save_backend.endpoint is not configured"
        if not _looks_like_url(ep):
            return False, f"save_backend.endpoint does not look like a URL: {ep!r}"
        return True, f"php endpoint configured → {ep}"
