# `infra/php/` — generic PHP save adapter (`save_backend="php"`)

This is the **server side of `save_backend="php"`**: a single self-hostable
PHP endpoint that persists a viewer-emitted camera-scope patch into a
scene's `viewer-config.json`. It is the opt-in, true-in-browser one-click
save tier. The default tier (`save_backend="cli"`) needs no server at all —
this adapter is for users who want the editor's **Save** button to write
directly, on a host they already run.

It is **generic by construction** — plain PHP 8, no framework, no Composer,
no DB. It works on the most ubiquitous server on earth (any LAMP / shared
host / VPS with `mod_php` or `php-fpm`). **geddart.de / Strato is just ONE
such host** — nothing here is hardcoded to it; the deploy is "point
`save_backend="php"`'s `endpoint` at wherever you dropped these files".

## Files

| File | What it is |
|---|---|
| `save-camera.php` | The single save endpoint (~305 LOC: ~170 logic, ~105 inline documentation). |
| `.htaccess` | Generic Apache rules: deny the secret/scratch files; no-cache the two mutable text files. |

## Deploy model (generic)

1. Drop `save-camera.php` + `.htaccess` onto your PHP host, next to a
   `scenes/<slug>/` tree (the documented relative layout):

   ```
   <docroot>/
     save-camera.php
     .htaccess
     scenes/
       <slug>/
         index.html          # the Spark viewer (static; chunks load from the CDN)
         viewer-config.json   # the mutable config this endpoint rewrites
         .author-token        # per-scene secret store (denied to the web)
   ```

   The scenes root is configurable at the top of `save-camera.php`
   (`SCENES_ROOT`); the default is `scenes/` next to the script.

2. For each authorable scene, create `scenes/<slug>/.author-token`
   containing either the raw per-scene token **or** its lowercase hex
   SHA-256 (both are accepted; the endpoint constant-time-compares with
   `hash_equals`). The `.htaccess` denies it to the web; store it
   server-side only — it is **never** in `viewer-config.json` or client JS.

3. Set `save_backend="php"` and
   `endpoint="https://<your-host>/save-camera.php"` for the scene. The
   author opens the private link (the per-scene bearer lives only in the
   URL fragment, never sent to a server/log); the editor's **Save** POSTs
   the camera-scope patch with `Authorization: Bearer <token>`; end-users
   get the plain link and read-only playback.

## The contract (cross-language, locked)

`save-camera.php`'s merge is the **cross-language twin** of the Python
source of truth `src/splatpipe/core/config_merge.py::merge_camera_scope`.
It must stay *semantically identical* — same `(existing, patch)` in ⇒
deep-equal `viewer-config.json` out. (Byte-identical serialization is **not**
required: PHP `json_encode` ≠ Python `json.dumps`; the viewer parses JSON
order-independently. **Data** equality is the contract.)

This is locked by `tests/test_php_save_oracle.py`, which drives the real
endpoint and asserts `json.loads(written) == merge_camera_scope(existing,
patch)` for representative fixtures (incl. the malicious one). If you change
the allow-list or merge semantics: change `config_merge.py` **first** (it is
the single source of truth), this file second, and re-run the oracle.

- **The 9 allow-listed keys** (mirrors `ALLOWED_PATCH_KEYS` verbatim):
  `start_view`, `camera_paths`, `clips`, `cameras`, `default_path_id`,
  `intro`, `titles3d`, `spark_render`, `annotations`.
- **Whole-key replace**, not deep-merge: a patched allowed key replaces the
  existing one wholesale (a nested dict in an allowed key replaces it
  entirely — exactly Python's `result[key] = value`).
- **`primary_asset` is force-kept** from the existing config, applied last
  and independent of the patch. A `patch.primary_asset` can **never** take
  effect (the locked "Speicher-blank" invariant: a moved pointer would aim
  a live scene at a non-existent build). If `existing` had none, none is
  synthesized.
- **Non-allow-listed patch keys are silently dropped** (mirrors the core's
  contract — *not* a 400) and returned in the success body's `ignored`
  array: `{"ok":true,"ignored":[...]}` — informational, never an error.
- **Slug charset:** `^[a-z0-9_-]{1,64}$` — matches the only slug-charset
  code that exists Python-side (the viewer slug sanitizer
  `[^A-Za-z0-9_-]` after the codebase-wide `slug.strip("/").lower()`;
  §H2-DECISION's authoritative form). This also blocks path traversal — all
  filesystem paths are built from the validated slug only.

## Security model

- **Constant-time** per-scene bearer check (`hash_equals`); the token is
  never echoed or logged. Missing/bad bearer → `401` and no write.
- **Error output is suppressed** via `.htaccess` `php_flag` on mod_php hosts
  (guarded with `<IfModule>` so it never hard-fails on php-fpm); php-fpm
  operators must set `display_errors=Off` in their pool's `php.ini`.
- The `.author-token` store is **server-side only**, denied to the web by
  `.htaccess`. The only client-held secret is the per-scene bearer
  (delivered via the author URL fragment), which can do exactly one thing:
  POST a camera-scope patch for one slug to this endpoint — which itself
  force-keeps `primary_asset`. **No storage/CDN/object key ever touches the
  client or this endpoint.**
- Slug sanitized → no path traversal (`.` `/` `\` NUL and `..` are all
  rejected by the charset); paths are built from the validated slug only.
- Atomic write: exclusive `flock` → write a sibling `.tmp` (the live file is
  never truncated) → snapshot the prior live file to `.bak` →
  POSIX-atomic `rename()` over the live path. A crash mid-write leaves the
  live config intact; concurrent saves are serialized (single author ⇒
  last-write-wins is acceptable, but never a torn file).
- `OPTIONS` → `204` (CORS preflight; same-origin is the default
  deployment). `POST` + `application/json` only (else `405`/`415`). Body
  capped at **256 KB** → `413` whose message directs the author to
  `splatpipe set-camera-path` (the always-available over-cap escape).
- No `eval`, no shelling out, no `include` of user input.

## Verifying parity on a PHP host

```sh
php -l infra/php/save-camera.php                 # syntax lint
pytest tests/test_php_save_oracle.py -v          # the cross-language oracle
```

The oracle is `skipif`-gated on `php` being absent, so the Python suite
stays green on hosts/CI without PHP; where `php` is present it really runs
the endpoint and asserts data parity against `merge_camera_scope`.
