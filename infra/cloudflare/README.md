# `infra/cloudflare/` — serverless save exemplar (`save_backend="cloudflare"`)

This is the **server side of `save_backend="cloudflare"`**: one Cloudflare
Worker that persists a viewer-emitted camera-scope patch into a scene's
`viewer-config.json` on Bunny Storage.

It is an **OPT-IN exemplar, not the default.** The default save tier is
`save_backend="cli"` (no server at all — the author runs one
`splatpipe set-camera-path` command). `save_backend="php"` (`infra/php/`)
is the generic self-hostable adapter for any LAMP/shared host. This
Cloudflare Worker is **one documented serverless example** of the same
contract — kept in-repo for provenance and as the worked port for other
serverless platforms (see the last section).

## Files

| File | What it is |
|---|---|
| `worker.js` | The single save Worker (modern ES-module `export default { fetch }`). |
| `wrangler.toml` | Minimal Worker config: KV binding + non-secret `[vars]`. Secrets are **not** here. |

## One-time setup

```sh
# 0. cd infra/cloudflare/ ; wrangler login   (or use a CF API token)

# 1. create the KV namespace and paste the printed id into wrangler.toml
wrangler kv namespace create SCENE_SECRETS

# 2. the two account-wide Bunny ACCESS KEYS — server-side secrets only
wrangler secret put BUNNY_STORAGE_PASSWORD     # Bunny Storage zone password
wrangler secret put BUNNY_ACCOUNT_API_KEY      # Bunny account API key (purge)

# 3. set the non-secret config in wrangler.toml [vars]:
#      BUNNY_STORAGE_ZONE, BUNNY_CDN_HOST, VIEWER_ORIGIN

# 4. per scene, store the LOWERCASE-HEX sha256 of that scene's author secret
#    (sha256sum also prints "  -" after the hex — copy only the 64-char hex)
printf %s "<scene-secret>" | sha256sum | cut -c1-64          # -> <64-char hex>
wrangler kv key put --binding=SCENE_SECRETS "<slug>" "<hex>"

# 5. deploy
wrangler deploy
```

Then set `save_backend = "cloudflare"` and
`save_backend.endpoint = "https://<your-worker-host>/"` for the scene. The
author opens the private link (the per-scene bearer lives only in the URL
fragment, never sent to a server/log); the editor's **Save** POSTs the
camera-scope patch with `Authorization: Bearer <secret>`; end-users get the
plain link and read-only playback.

## The contract (cross-language, locked)

`worker.js`'s merge is the **cross-language twin** of the Python source of
truth `src/splatpipe/core/config_merge.py::merge_camera_scope` (and the
sibling `infra/php/save-camera.php`). It must stay *semantically identical*
— same `(existing, patch)` in ⇒ deep-equal `viewer-config.json` out.
(Byte-identical serialization is **not** required: `JSON.stringify` ≠
Python `json.dumps`; the viewer parses JSON order-independently. **Data**
equality is the contract.)

This is locked by `tests/test_cloudflare_save_oracle.py`, which drives the
real exported JS merge through `node` and asserts
`json.loads(<node merge>) == merge_camera_scope(existing, patch)` for the
same fixtures the PHP oracle uses (incl. the malicious one). **Change-order
discipline:** if you change the allow-list or merge semantics, change
`config_merge.py` **first** (it is the single source of truth), then
**this file and `save-camera.php`**, and re-run **both** cross-language
oracles.

- **The 9 allow-listed keys** (mirrors `ALLOWED_PATCH_KEYS` verbatim):
  `start_view`, `camera_paths`, `clips`, `cameras`, `default_path_id`,
  `intro`, `titles3d`, `spark_render`, `annotations`.
- **Whole-key replace**, not deep-merge: a patched allowed key replaces the
  existing one wholesale (a nested dict in an allowed key replaces it
  entirely — exactly Python's `result[key] = value`).
- **`primary_asset` is force-kept** from the existing config, applied last
  and independent of the patch. A `patch.primary_asset` can **never** take
  effect (the locked **"Speicher-blank"** invariant: a moved pointer would
  aim a live scene at a non-existent build). If `existing` had none, none is
  synthesized.
- **Non-allow-listed patch keys are silently dropped** (mirrors the core's
  contract — *not* a 400) and returned in the success body's `ignored`
  array: `{"ok":true,"ignored":[...]}` — informational, never an error.
  `primary_asset` (the force-keep) and `slug` (the transport field) are
  excluded from `ignored`.
- **Slug charset:** `^[a-z0-9_-]{1,64}$` — identical to the Python/spcp
  side and `save-camera.php` (§H2-DECISION's authoritative form). This also
  blocks path traversal; every Bunny path is built from the validated slug
  only.
- **Single PUT, no delete:** the Worker GETs the live
  `<slug>/viewer-config.json`, merges, and does **one** PUT back to the
  **same** path, then purges **only** that one config CDN URL. It never
  deletes anything and never writes `index.html` or the heavy `b<key>/`
  `.radc` chunks — so the **Bunny async-delete-race invariant** (a folder
  delete + immediate re-PUT that blanked Speicher twice) cannot occur here.

## Security model

- **Bunny keys are server-side secrets, NEVER client-side.** This is the
  unmissable rule. `BUNNY_STORAGE_PASSWORD` and `BUNNY_ACCOUNT_API_KEY` are
  set via `wrangler secret put`, live only in the Worker `env`, and are
  **never** in client JS, **never** in `wrangler.toml`, **never** in git,
  **never** echoed in any response, **never** logged. A Bunny key has no
  scoped/presigned form — leaking it is full account compromise. That is
  precisely *why* the editor never holds it and the Worker (server-side)
  owns the only copy.
- **Constant-time per-scene bearer check.** KV maps `slug` →
  lowercase-hex sha256 of the per-scene secret. The Worker hashes the
  *given* token with Web Crypto and compares digests with a constant-time
  hex compare (no early return — Workers has no
  `crypto.subtle.timingSafeEqual`). Missing KV entry → `404`; mismatch →
  `401`; the raw token is never stored, echoed, or logged.
- **A patched `primary_asset` is structurally incapable of landing.** It is
  not in the allow-list *and* `existing.primary_asset` is force-kept last,
  independent of the patch. Belt-and-braces for the locked Bunny invariant.
- **No async-delete race.** Single PUT to the same path, no delete, purge
  only the one config URL; `index.html` / `b<key>/` chunks are never
  touched.
- **Slug traversal-safe.** `^[a-z0-9_-]{1,64}$` rejects `.` `/` `\` NUL and
  `..`; all Storage/CDN paths are built from the validated slug only.
- **`OPTIONS` → `204`** with CORS preflight headers; `POST` +
  `application/json` only (else `405`/`415`). CORS
  `Access-Control-Allow-Origin` is the configured `VIEWER_ORIGIN`.
- **Body capped at 256 KB → `413`** whose JSON message directs the author
  to `splatpipe set-camera-path` (the always-available over-cap escape for
  very large imported camera paths). Both the declared `Content-Length` and
  the actual UTF-8 byte length are checked.
- **A transient Bunny read failure does not clobber.** A `404` on the GET
  is treated as `{}` (older deploy); any other non-2xx returns a structured
  `502` and performs **no** write — mirroring the Python `cli` backend's
  fetch-fail posture.
- **Request data is parsed, never `eval`'d.**

## Port to Netlify / Vercel / Lambda

**The merge + auth logic is identical (~80 lines).** To run this on
another serverless platform you swap **only**:

1. **The secret store.** Cloudflare Workers KV → that platform's
   secret/env store (Netlify Blobs / env, Vercel KV / env, AWS Secrets
   Manager / DynamoDB, etc.).
2. **The one KV `.get` call.** `await env.SCENE_SECRETS.get(slug)` →
   that store's lookup for `slug → sha256(secret)`.

Everything else is unchanged: `mergeCameraScope`, `computeIgnored`,
`ALLOWED_PATCH_KEYS`, the constant-time hex compare, the slug regex, the
256 KB cap, the Bunny GET → merge → single-PUT-same-path → purge-one-URL
flow, and the CORS/preflight handling. The pure merge functions are
exported standalone (no dependency on the Workers `fetch` runtime), which
is exactly what makes them portable *and* what the cross-language oracle
imports directly.

## Verifying parity

```sh
node --check infra/cloudflare/worker.js          # syntax lint
pytest tests/test_cloudflare_save_oracle.py -v   # the cross-language oracle
```

The oracle is `skipif`-gated on `node` being absent so the Python suite
stays green on hosts/CI without Node; where `node` is present it really
runs the exported JS merge and asserts data parity against
`merge_camera_scope` for every fixture (the same set the PHP twin uses).
The auth / CORS / Bunny GET-PUT-purge relay is statically verified against
the §H spec and `save-camera.php` (§H2-DECISION downscoped `cloudflare` to
"one exemplar, doc'd" — no Miniflare runtime); the cross-language **merge**
is the contract that is executably locked.
