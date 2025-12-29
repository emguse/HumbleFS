# HumbleFS Implementation Notes (Draft)

This file captures the current planning conclusions so individual tasks can reference them.

## Open Decisions Required Before Implementation

### 1) Logical key → stored key resolution (GET/DELETE)
When multiple postfix variants exist for the same logical key, the rule for which stored key
is returned or deleted must be defined.

**Decision:**
- Pick the newest by `created_at` in `*.meta.json`.

**Conflict rule:**
- If the newest stored key cannot be determined (e.g., same latest `created_at` or missing
  metadata), return 409 and require the caller to disambiguate.

**Where this affects code:**
- `GET /<bucket>/<key>` handler
- `DELETE /<bucket>/<key>` handler

---

### 2) Root path configuration + bucket creation policy
Define how `<root>` is configured and whether buckets are auto-created.

**Decision:**
- Root path is provided by the `HUMBLEFS_ROOT` environment variable.
- `HUMBLEFS_ROOT` is required at startup; the server must refuse to start if it is unset,
  does not exist, or is not writable.
- If bucket is missing on `PUT`, automatically create the bucket directory.

**Where this affects code:**
- Startup configuration
- `PUT /<bucket>/<key>` handler
- Existence checks in `GET/LIST/DELETE`

---

### 3) `hfs-postfix` specified + conflict behavior
Clarify what happens when `x-amz-meta-hfs-postfix` is provided and the target exists,
particularly when `hfs-conflict=new`.

**Decision:**
- Explicit postfix is strict: if the target exists, return 409 unless
  `hfs-conflict=overwrite`. `hfs-conflict=new` does **not** auto-generate a new
  postfix when one is explicitly provided.

**Where this affects code:**
- PUT path resolution
- Conflict handling logic

---

### 4) Content-Type precedence
Define how `Content-Type` is stored and returned when PUT omits it.

**Decision:**
- Precedence for stored `content_type`:
  1) `Content-Type` header from PUT (if provided)
  2) Infer from filename extension
  3) Default to `application/octet-stream`
- Always write the resolved value into `*.meta.json`.

**Where this affects code:**
- PUT metadata creation
- GET response headers

---

### 5) LIST response format
The LIST endpoint needs a concrete response format.

**Decision:**
- JSON response with a top-level `objects` array.
- Each object includes: `key`, `size`, `last_modified`.

**Where this affects code:**
- `GET /<bucket>?prefix=...` handler

---

## Baseline Behavior Summary (from the current spec)

- Backend: local filesystem only; single-node
- Objects stored as normal files plus `<stored_object>.meta.json`
- Path mapping: `<root>/<bucket>/<key>`
- Postfixing: `__<postfix>` on basename, `[a-z0-9]`, 3–6 chars
- Metadata control via `x-amz-meta-hfs-*` headers
- PUT uses temp file + atomic rename; then writes meta.json
- GET/DELETE resolve logical key to stored file; return/delete stored object
- LIST walks FS and returns stored keys directly
- No auth; block `../` or absolute paths
