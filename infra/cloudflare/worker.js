/**
 * worker.js — the server side of save_backend="cloudflare".
 *
 * OPT-IN serverless EXEMPLAR (the default tier is save_backend="cli", which
 * needs no server at all; "php" is the generic self-hostable adapter). This
 * is ONE documented serverless example — the merge + auth logic is ~80
 * lines and portable: to run it on Netlify / Vercel / Lambda you swap only
 * the secret store (Workers KV -> that platform's secret/env) and the one
 * `SCENE_SECRETS.get(slug)` call. Everything else is identical.
 *
 * What it does: a viewer's keyframe editor emits an UNTRUSTED camera-scope
 * patch and POSTs it here with a per-scene bearer token. This Worker
 * authenticates (constant-time, KV slug -> sha256(secret)), then
 * fetch -> merge -> single-PUT-back the scene's viewer-config.json on Bunny
 * Storage and purges ONLY that one config CDN URL.
 *
 * THE MERGE IS A CROSS-LANGUAGE TWIN of the Python source of truth
 * `src/splatpipe/core/config_merge.py::merge_camera_scope` (and the sibling
 * PHP adapter `infra/php/save-camera.php`). It MUST stay semantically
 * identical (locked by tests/test_cloudflare_save_oracle.py — same
 * (existing, patch) in => deep-equal viewer-config.json out). Byte-identical
 * serialization is NOT required (the viewer parses JSON order-independently);
 * DATA equality is the contract. CHANGE ORDER DISCIPLINE: if you change the
 * 9-key allow-list or the merge semantics, change config_merge.py FIRST (it
 * is the single source of truth), then THIS file AND save-camera.php, and
 * re-run BOTH cross-language oracles.
 *
 * Locked, security-critical invariants:
 *  - "Speicher-blank" failure class: the patch can NEVER move the
 *    `primary_asset` Bunny pointer. existing's primary_asset is force-kept,
 *    applied LAST, independent of the patch (and not in the allow-list).
 *  - Bunny async-delete race: this NEVER deletes — it is a SINGLE PUT to
 *    the SAME viewer-config.json path, then a purge of that one URL only.
 *    `index.html` and the heavy `b<key>/` .radc chunks are NEVER written.
 *  - Account-wide Bunny keys (BUNNY_STORAGE_PASSWORD / BUNNY_ACCOUNT_API_KEY)
 *    live ONLY in `env` (wrangler secrets). They are NEVER in client JS,
 *    NEVER echoed in any response, NEVER logged.
 */

/**
 * The §H2 locked camera-scope allow-list — the ONLY keys an untrusted patch
 * may set. MIRRORS splatpipe.core.config_merge.ALLOWED_PATCH_KEYS verbatim
 * (that module is the single source of truth — keep these in lockstep with
 * it AND infra/php/save-camera.php; the cross-language oracles fail if they
 * drift). `primary_asset` is deliberately ABSENT: it is force-kept from the
 * existing config and can never be moved by a patch.
 *
 * Exported so the cross-language oracle can assert it has not drifted from
 * the Python source of truth.
 */
export const ALLOWED_PATCH_KEYS = new Set([
  "start_view",
  "camera_paths",
  "clips",
  "cameras",
  "default_path_id",
  "intro",
  "titles3d",
  "spark_render",
  "annotations",
  "panorama_backdrop",
  "postprocessing",
  "audio",
]);

// `slug` is the transport field carried in the POST body, not config; like
// `primary_asset` (the locked force-keep) it must never be surfaced as an
// author "ignored" diagnostic. Mirrors save-camera.php's `if ($key === 'slug')
// continue;` + its `elseif ($key !== 'primary_asset')`.
const TRANSPORT_KEYS = new Set(["slug"]);

// Slug charset — matches the Python/spcp side AND save-camera.php EXACTLY
// (`^[a-z0-9_-]{1,64}$`, §H2-DECISION's authoritative form). This also
// blocks path traversal: no `.`, `/`, `\`, NUL, or `..`. Every Bunny path
// below is built from the validated slug only.
const SLUG_RE = /^[a-z0-9_-]{1,64}$/;

const MAX_BODY_BYTES = 256 * 1024; // 256 KB

const OVER_CAP_MSG =
  "request body exceeds 256 KB; for very large imported camera paths run " +
  "`splatpipe set-camera-path <token>` (the admin CLI handles over-cap " +
  "saves) instead of the in-browser Save.";

/* ===== pure merge — cross-language twin of merge_camera_scope =========== *
 * Python (config_merge.py), parity-critical lines:
 *   result = copy.deepcopy(existing)
 *   for key, value in patch.items():
 *       if key in ALLOWED_PATCH_KEYS:
 *           result[key] = copy.deepcopy(value)        # WHOLE-key replace
 *   if "primary_asset" in existing:
 *       result["primary_asset"] = copy.deepcopy(existing["primary_asset"])
 *
 * JS equivalents:
 *  - `structuredClone(existing)` — the deep-copy base, preserving every
 *    non-allow-listed key + nested data unchanged (Python copy.deepcopy).
 *  - whole-key REPLACE (`result[k] = structuredClone(patch[k])`), NOT a
 *    recursive merge — a nested dict in an allowed key replaces wholesale,
 *    exactly like Python `result[key] = value` (oracle:
 *    nested_dict_whole_replace). The clone matches deepcopy(value) so the
 *    result never aliases the patch's nested mutable data.
 *  - force-keep existing's primary_asset, applied LAST and independent of
 *    the patch loop, so a patch primary_asset can NEVER win. The membership
 *    test uses Object.prototype.hasOwnProperty so a JSON `null`/falsey
 *    value still counts as present — matching Python's `in` (which is true
 *    even for `existing["primary_asset"] is None`); no synthesis when
 *    absent (the original never added one).
 *
 * Pure: no I/O, no network, no `env`. Exported standalone so the
 * cross-language oracle (tests/test_cloudflare_save_oracle.py) can drive it
 * via plain `node` without the Workers `fetch` runtime.
 */
export function mergeCameraScope(existing, patch) {
  const result = structuredClone(existing); // deep-copy base (Python deepcopy)
  for (const key of Object.keys(patch)) {
    if (ALLOWED_PATCH_KEYS.has(key)) {
      result[key] = structuredClone(patch[key]); // whole-key replace
    }
  }
  // Force-keep the existing pointer (locked invariant). Last + independent of
  // the loop so a patched primary_asset can never take effect. hasOwnProperty
  // mirrors Python's `"primary_asset" in existing` (true even for a JSON
  // null); no synthesis when absent.
  if (Object.prototype.hasOwnProperty.call(existing, "primary_asset")) {
    result["primary_asset"] = structuredClone(existing["primary_asset"]);
  }
  return result;
}

/**
 * The non-allow-listed patch key names — INFORMATIONAL (Task-4
 * carry-forward; mirrors save-camera.php's `$ignored` and the Python
 * SaveResult.ignored_keys). `primary_asset` (the locked force-keep) and
 * `slug` (the transport field) are excluded — neither is an author
 * diagnostic. Sorted + de-duplicated for a stable contract.
 */
export function computeIgnored(patch) {
  const out = [];
  for (const key of Object.keys(patch)) {
    if (TRANSPORT_KEYS.has(key)) continue; // transport field, not config
    if (ALLOWED_PATCH_KEYS.has(key)) continue; // applied, not ignored
    if (key === "primary_asset") continue; // locked force-keep, not a diag
    out.push(key);
  }
  return [...new Set(out)].sort();
}

/* ===== tiny helpers ==================================================== */

function corsHeaders(env) {
  // Restrict to the configured viewer origin (the deployed Spark scene).
  // `*` would also work for an authed POST but the explicit origin is the
  // §H contract ("CORS to the viewer origin").
  return {
    "Access-Control-Allow-Origin": env.VIEWER_ORIGIN || "*",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Authorization, Content-Type",
    Vary: "Origin",
  };
}

function jsonResponse(status, body, env) {
  // The token / Bunny keys are NEVER part of `body` (we never put them
  // there). `no-store`: the save response itself must never be cached.
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
      ...corsHeaders(env),
    },
  });
}

const fail = (status, error, env) =>
  jsonResponse(status, { ok: false, error }, env);

/** Constant-time equality of two equal-length hex strings (Workers has no
 * crypto.subtle.timingSafeEqual). No early return: every char is compared
 * and the differences OR-accumulated, so timing does not leak the token. */
function timingSafeHexEqual(a, b) {
  if (typeof a !== "string" || typeof b !== "string") return false;
  if (a.length !== b.length) return false; // both are fixed 64-char sha256 hex
  // SECURITY — do NOT replace this loop with === or an early return.
  // The fixed-length OR-accumulate is the constant-time guarantee: every
  // char is compared regardless of mismatch position, so response timing
  // never leaks how many chars of the per-scene bearer token matched.
  let diff = 0;
  for (let i = 0; i < a.length; i++) {
    diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  }
  return diff === 0;
}

/** Lowercase hex sha256 of a UTF-8 string (Web Crypto; available in
 * Workers). Used only to hash the *given* bearer for the constant-time
 * compare against the KV-stored hash — the raw token is never stored,
 * echoed, or logged. */
async function sha256Hex(text) {
  const buf = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(text)
  );
  return [...new Uint8Array(buf)]
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

/* ===== the Worker ====================================================== */

export default {
  /**
   * env (all server-side; secrets via `wrangler secret put`, the rest via
   * [vars] — NEVER in client JS, NEVER in any response):
   *   SCENE_SECRETS          KV: slug -> lowercase-hex sha256 of the
   *                          per-scene author secret.
   *   BUNNY_STORAGE_PASSWORD Bunny Storage zone password (AccessKey for
   *                          storage.bunnycdn.com GET/PUT). SECRET.
   *   BUNNY_ACCOUNT_API_KEY  Bunny account API key (AccessKey for
   *                          api.bunny.net/purge). SECRET.
   *   BUNNY_STORAGE_ZONE     Bunny Storage zone name (path segment).
   *   BUNNY_CDN_HOST         The scene's CDN host, e.g.
   *                          splatpipe-cdn.b-cdn.net (for the purge URL).
   *   VIEWER_ORIGIN          The viewer origin for the CORS allow-list.
   */
  async fetch(request, env, ctx) {
    // --- 1. CORS preflight ---------------------------------------------
    if (request.method === "OPTIONS") {
      return new Response(null, {
        status: 204,
        headers: { ...corsHeaders(env), "Access-Control-Max-Age": "600" },
      });
    }

    // --- 2. method + content-type --------------------------------------
    if (request.method !== "POST") {
      return fail(405, "method not allowed; POST application/json only", env);
    }
    const ctype = request.headers.get("Content-Type") || "";
    if (!ctype.toLowerCase().includes("application/json")) {
      return fail(415, "Content-Type must be application/json", env);
    }

    // --- 3. body-size cap ----------------------------------------------
    // Cheap pre-check via the declared length, then a hard cap on what we
    // actually read (a lying/absent Content-Length cannot smuggle past us).
    const declared = parseInt(
      request.headers.get("Content-Length") || "0",
      10
    );
    if (Number.isFinite(declared) && declared > MAX_BODY_BYTES) {
      return fail(413, OVER_CAP_MSG, env);
    }
    const raw = await request.text();
    // String length is not byte length; measure UTF-8 bytes exactly.
    if (new TextEncoder().encode(raw).length > MAX_BODY_BYTES) {
      return fail(413, OVER_CAP_MSG, env);
    }

    // --- 4. parse JSON + resolve slug ----------------------------------
    let patch;
    try {
      patch = JSON.parse(raw); // request data is PARSED, never eval'd
    } catch {
      return fail(400, "request body must be a JSON object", env);
    }
    if (
      patch === null ||
      typeof patch !== "object" ||
      Array.isArray(patch)
    ) {
      return fail(400, "request body must be a JSON object", env);
    }

    const slug = patch.slug;
    if (typeof slug !== "string") {
      return fail(400, "slug must be a string", env);
    }
    // Slug charset == Python/php side EXACTLY; also blocks path traversal.
    if (!SLUG_RE.test(slug)) {
      return fail(400, "invalid slug (must match ^[a-z0-9_-]{1,64}$)", env);
    }

    // --- 5. auth: constant-time per-scene bearer -----------------------
    const auth = request.headers.get("Authorization") || "";
    const m = /^Bearer\s+(.+)$/i.exec(auth.trim());
    const given = m ? m[1].trim() : "";

    // KV maps slug -> lowercase-hex sha256 of the per-scene secret.
    const storedHash = await env.SCENE_SECRETS.get(slug);
    if (storedHash === null) { // Workers KV .get() returns null (never undefined) on miss
      // Slug is valid but unknown: no secret on file. Do not reveal more.
      return fail(404, "scene not found", env);
    }
    // Hash the GIVEN token and constant-time-compare hex digests. The raw
    // token is never stored, echoed, or logged.
    const ok =
      given !== "" &&
      timingSafeHexEqual(
        storedHash.trim().toLowerCase(),
        await sha256Hex(given)
      );
    if (!ok) {
      return fail(401, "unauthorized", env);
    }

    // --- 6. fetch the live config (404 => {}; other non-2xx => 502) ----
    // Mirror the Python `cli` backend's fetch-fail posture: a structured
    // error, NOT a write — a transient Bunny read failure must not clobber
    // the live config.
    const zone = env.BUNNY_STORAGE_ZONE;
    const storageBase = `https://storage.bunnycdn.com/${zone}/${slug}`;
    const cfgUrl = `${storageBase}/viewer-config.json`;

    let existing = {};
    const getResp = await fetch(cfgUrl, {
      method: "GET",
      headers: { AccessKey: env.BUNNY_STORAGE_PASSWORD },
    });
    if (getResp.status === 404) {
      existing = {}; // older deploy / config not yet present
    } else if (!getResp.ok) {
      return fail(
        502,
        "could not read the live viewer-config.json (upstream); not " +
          "overwriting on a transient fetch failure",
        env
      );
    } else {
      const text = await getResp.text();
      if (text.trim() !== "") {
        try {
          const decoded = JSON.parse(text);
          if (
            decoded === null ||
            typeof decoded !== "object" ||
            Array.isArray(decoded)
          ) {
            return fail(
              502,
              "existing viewer-config.json is not a JSON object",
              env
            );
          }
          existing = decoded;
        } catch {
          return fail(
            502,
            "existing viewer-config.json is not valid JSON",
            env
          );
        }
      }
    }

    // --- 7. MERGE (cross-language twin of merge_camera_scope) ----------
    const result = mergeCameraScope(existing, patch);
    const ignored = computeIgnored(patch);

    // --- 8. SINGLE PUT, SAME path, NO delete --------------------------
    // NEVER PUT index.html or any b<key>/ chunk — only this one config
    // file, to its exact existing path. No delete => no Bunny async-delete
    // race (the locked invariant that blanked Speicher twice).
    const putResp = await fetch(cfgUrl, {
      method: "PUT",
      headers: {
        AccessKey: env.BUNNY_STORAGE_PASSWORD,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(result),
    });
    if (!putResp.ok) {
      return fail(
        502,
        `failed to write merged config (upstream ${putResp.status})`,
        env
      );
    }

    // Purge ONLY that one config CDN URL (not the zone, not the chunks).
    const cdnUrl = `https://${env.BUNNY_CDN_HOST}/${slug}/viewer-config.json`;
    const purgeResp = await fetch(
      `https://api.bunny.net/purge?url=${encodeURIComponent(cdnUrl)}`,
      {
        method: "POST",
        headers: { AccessKey: env.BUNNY_ACCOUNT_API_KEY },
      }
    );
    // A failed purge is not fatal — the write succeeded; the edge TTL will
    // catch up. Surface it as a soft warning, never with any key/URL-key.
    const purgeWarning = purgeResp.ok
      ? undefined
      : `config written; CDN purge returned ${purgeResp.status} (edge will ` +
        `refresh on TTL)`;

    // --- 9. success ----------------------------------------------------
    const body = { ok: true, ignored };
    if (purgeWarning) body.warning = purgeWarning;
    return jsonResponse(200, body, env);
  },
};
