# HumbleFS Implementation Notes

This document captures the current, implementation-ready decisions derived from the spec.
It is intended as a single, up-to-date reference for developers.

---

## 1) Root configuration (startup requirement)

**Decision**
- Root path is provided by the `HUMBLEFS_ROOT` environment variable.
- `HUMBLEFS_ROOT` is **required** at startup.
- The server must refuse to start if `HUMBLEFS_ROOT` is unset, does not exist, or is not writable.

**Where this affects code**
- Startup configuration and validation

---

## 2) Bucket creation policy (PUT)

**Decision**
- If the target bucket directory does not exist on `PUT`, create it automatically.

**Where this affects code**
- `PUT /<bucket>/<key>` handler
- Filesystem creation utilities

---

## 3) Postfix rules and conflict behavior

**Decision**
- Default mode is `unique`: always add a postfix.
- `hfs-conflict` values:
  - `fail`: return 409 if target exists
  - `overwrite`: overwrite existing target
  - `new` (default): generate a new postfix and store a distinct file
- **Explicit postfix is strict**:
  - If `x-amz-meta-hfs-postfix` is provided and the target exists, return 409 unless
    `hfs-conflict=overwrite`.
  - `hfs-conflict=new` does **not** auto-generate a new postfix when one is explicitly provided.

**Where this affects code**
- PUT path resolution
- Conflict handling logic

---

## 4) Logical key → stored key resolution (GET/DELETE)

**Decision**
- When multiple stored keys match a logical key, select the one with the newest
  `created_at` from `*.meta.json`.

**Conflict rule**
- If the newest stored key cannot be determined (e.g., multiple candidates share the same
  latest `created_at` or metadata is missing), return `409 Conflict` and require the caller
  to disambiguate.

**Where this affects code**
- `GET /<bucket>/<key>` handler
- `DELETE /<bucket>/<key>` handler

---

## 5) Content-Type precedence

**Decision**
- Resolve `content_type` in this order:
  1. `Content-Type` header from PUT (if provided)
  2. Inferred from filename extension
  3. Default to `application/octet-stream`
- Always write the resolved value into `*.meta.json`.

**Where this affects code**
- PUT metadata creation
- GET response headers

---

## 6) LIST response format

**Decision**
- JSON response with a top-level `objects` array.
- Each object includes: `key`, `size`, `last_modified`.

**Where this affects code**
- `GET /<bucket>?prefix=...` handler

---

## 7) Path validation and metadata header policy

**Decision**
- URL-decode the key (once) before validation.
- Reject keys with `..` path segments or any path traversal attempt.
- Reject absolute paths (`/`, drive letters, or `\`-rooted paths on Windows).
- Only accept `x-amz-meta-hfs-*` headers; reject all other `x-amz-meta-*` headers.

**Where this affects code**
- Request validation middleware/utilities

---

## 8) Baseline behavior summary

- Backend: local filesystem only; single-node
- Objects stored as normal files plus `<stored_object>.meta.json`
- Path mapping: `<root>/<bucket>/<key>`
- Postfixing: `__<postfix>` on basename, `[a-z0-9]`, 3–6 chars
- Metadata control via `x-amz-meta-hfs-*` headers
- PUT uses temp file + atomic rename; then writes meta.json
- GET/DELETE resolve logical key to stored file; return/delete stored object
- LIST walks FS and returns stored keys directly
- No auth; block `../` or absolute paths

---

## 9) Testing strategy (plan)

### 9.1 Test layers
1. **Unit tests**
   - Path validation, metadata parsing, postfix generation, key resolution.
2. **Filesystem integration tests**
   - Temp file + atomic rename, meta file creation/removal, bucket auto-creation.
3. **HTTP/API tests**
   - PUT/GET/DELETE/LIST conformance and error handling.
4. **Edge/abuse cases**
   - Conflict resolution, missing metadata, invalid headers, traversal attempts.

### 9.2 Priority coverage
- Startup validation for `HUMBLEFS_ROOT`.
- Explicit postfix conflict behavior (`409` unless overwrite).
- GET/DELETE newest `created_at` selection, and 409 on ambiguity.
- Content-Type precedence: header → extension → default.
- LIST JSON format and `prefix` filtering.

### 9.3 Test data hygiene
- Create a temporary root directory per test.
- Keep tests isolated by unique bucket names and keys.
- Avoid sleep-based time ordering; use deterministic metadata when possible.
