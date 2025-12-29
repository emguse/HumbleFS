# HumbleFS Implementation Notes (Draft)

This file captures the current planning conclusions so individual tasks can reference them.

## Open Decisions Required Before Implementation

### 1) Logical key → stored key resolution (GET/DELETE)
When multiple postfix variants exist for the same logical key, the rule for which stored key
is returned or deleted must be defined.

**Options to decide:**
- Pick the newest by `created_at` in `*.meta.json`.
- Pick the first match found on disk.
- Return conflict (e.g., 409) and require the caller to disambiguate.

**Where this affects code:**
- `GET /<bucket>/<key>` handler
- `DELETE /<bucket>/<key>` handler

---

### 2) Root path configuration + bucket creation policy
Define how `<root>` is configured and whether buckets are auto-created.

**Options to decide:**
- Root path from env var (e.g., `HUMBLEFS_ROOT`), config file, or CLI arg.
- If bucket is missing on `PUT`: auto-create vs. return 404.

**Where this affects code:**
- Startup configuration
- `PUT /<bucket>/<key>` handler
- Existence checks in `GET/LIST/DELETE`

---

### 3) `hfs-postfix` specified + conflict behavior
Clarify what happens when `x-amz-meta-hfs-postfix` is provided and the target exists,
particularly when `hfs-conflict=new`.

**Options to decide:**
- Ignore provided postfix on conflict and generate a new one.
- Treat it as `fail` when conflict occurs.
- Allow overwrite only if `hfs-conflict=overwrite`.

**Where this affects code:**
- PUT path resolution
- Conflict handling logic

---

### 4) Content-Type precedence
Define how `Content-Type` is stored and returned when PUT omits it.

**Options to decide:**
- Default to `application/octet-stream`.
- Infer from filename extension.
- Store empty and omit on GET.

**Where this affects code:**
- PUT metadata creation
- GET response headers

---

### 5) LIST response format
The LIST endpoint needs a concrete response format.

**Options to decide:**
- JSON vs XML
- Minimal fields (e.g., key, size, last_modified)

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

