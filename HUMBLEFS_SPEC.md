# HumbleFS
## A low-ambition S3-like API that stores plainly on the local filesystem

This document defines the design for a **minimal, performance-agnostic, retreat-friendly**
S3-compatible-ish storage API.

---

## 0. Concept

**HumbleFS** explicitly keeps the scope small:

- No large-scale distribution or high performance goals
- Objects are stored as plain files
- Data remains human-readable on disk
- Prioritize easy retreat (`rsync` / `cp` / `tar`)

> "Not as ambitious as Ceph, but the data stays in your hands."

---

## 1. Assumptions

- **Backend is local filesystem**
  - ext4 / xfs / zfs / ntfs / fuse / network mounts are all acceptable
- Single-node only
- LAN / PoC / research use
- Full S3 API compatibility is not a goal

---

## 2. Root configuration (startup requirement)

- Root path comes from `HUMBLEFS_ROOT` or `humblefs.toml`.
- `HUMBLEFS_ROOT` overrides config file values.
- The config file location defaults to `./humblefs.toml` and can be overridden with
  `HUMBLEFS_CONFIG`.
- `HUMBLEFS_ROOT` (or `root` in config) is **required** at startup.
- The server must refuse to start if the resolved root is unset, does not exist, or is not
  writable.

---

## 3. Backend directory layout

```
<root>/
  <bucket>/
    <prefix1>/
      <prefix2>/
        <stored_object>
        <stored_object>.meta.json
```

### Terms
- **logical key**  
  The S3 key specified by the client (URL key)
- **stored key**  
  The actual filename created on disk (with postfix)

---

## 4. Key-to-path mapping

### 4.1 Basic mapping

```
PUT /bucket/path/to/result.json
```

↓

```
<root>/bucket/path/to/result.json
```

---

## 5. Collision avoidance (postfix)

HumbleFS can use postfixes to avoid same-name collisions, but the default behavior
stores plain keys and overwrites like S3.

### 5.1 Postfix format (recommended)

```
<basename>__<postfix>.<ext>
```

Examples:

```
result__a9f3.json
image__k2m8.png
```

- postfix is a short random string (3–6 chars)
- character set recommended: `[a-z0-9]`
- UUIDs are intentionally avoided for readability

---

## 6. Postfix control via metadata headers

`x-amz-meta-*` headers are interpreted as the control plane.

> This is an intentional S3 deviation.

### 6.1 Reserved metadata headers

| Header | Description |
|------|----|
| `x-amz-meta-hfs-mode` | Storage mode |
| `x-amz-meta-hfs-conflict` | Conflict behavior |
| `x-amz-meta-hfs-postfix` | Explicit postfix (optional) |

### 6.2 Storage mode (`hfs-mode`)

```
x-amz-meta-hfs-mode: plain | unique | None
```

- `plain` (default)
  - Store the specified key as-is
  - No postfix
- `unique`
  - Always add a postfix and generate a unique stored key
- `None`
  - Behaves like `plain`

### 6.3 Conflict behavior (`hfs-conflict`)

```
x-amz-meta-hfs-conflict: fail | overwrite | new
```

- `fail`
  - Return 409 Conflict if the name exists
- `overwrite` (default)
  - Overwrite existing file
- `new`
  - Generate a new postfix and store as a distinct file
  - If an explicit postfix is provided and it already exists, return 409 (no
    auto-regeneration)

### 5.4 Explicit postfix (optional)

```
x-amz-meta-hfs-postfix: a9f3
```

- Use the specified postfix
- If the target exists:
  - `overwrite` is allowed
  - `fail` or `new` returns 409 (no auto-regeneration)

### 5.5 curl example

```sh
curl -X PUT http://host:9000/bucket/exp1/result.json \
  -H "x-amz-meta-hfs-mode=unique" \
  -H "x-amz-meta-hfs-conflict=new" \
  -H "x-amz-meta-hfs-postfix=a9f3" \
  --data-binary @result.json
```

↓

```
<root>/bucket/exp1/result__a9f3.json
```

If `result__a9f3.json` already exists, this request returns 409 (explicit postfix
is strict). Use `x-amz-meta-hfs-conflict=overwrite` to overwrite instead.

---

## 6. Metadata file format

### 6.1 Location

```
<stored_object>.meta.json
```

### 6.2 Example content

```json
{
  "logical_key": "exp1/result.json",
  "stored_key": "exp1/result__a9f3.json",
  "size": 12345,
  "content_type": "application/json",
  "created_at": "2025-01-01T12:34:56Z",
  "user_meta": {
    "hfs-mode": "unique",
    "hfs-conflict": "new"
  }
}
```

### 6.3 `content_type` resolution

- If the PUT request includes `Content-Type`, store that value.
- If omitted, infer from the stored key’s filename extension when possible.
- If inference fails, default to `application/octet-stream`.
- Always write the resolved value into `*.meta.json` as `content_type`.

---

## 7. PUT (store)

```
PUT /<bucket>/<key>
```

### Steps

1. Compute the target path on local FS
   - If the bucket directory does not exist, create it.
2. Interpret metadata headers
3. Write to a temporary file
4. `rename()` into place atomically
5. Write `.meta.json`

---

## 8. GET (fetch)

```
GET /<bucket>/<key>
```

- Resolve a stored key matching the logical key
- Return the file contents
- Use `meta.json` for `Content-Type` (per the PUT resolution rules: header → extension
  inference → `application/octet-stream`)
- Stored key resolution: collect all stored keys that match the logical key, then select
  the one with the newest `created_at` in its `*.meta.json`.
- Conflict handling: if the newest stored key cannot be determined (e.g., multiple candidates
  share the same latest `created_at` or metadata is missing), return `409 Conflict`.

---

## 9. DELETE (remove)

```
DELETE /<bucket>/<key>
```

- Resolve the stored key using the same rule as GET (newest `created_at`)
- Delete the stored key
- Delete the matching `.meta.json`
- Conflict handling: if the newest stored key cannot be determined, return `409 Conflict`.

---

## 10. LIST

```
GET /<bucket>?prefix=xxx
```

- Walk the local filesystem
- Return stored keys as-is
- Grouping and logical-name mapping can be added later

### 10.1 Response format (JSON)

- Response body is JSON.
- Top-level shape:

```json
{
  "objects": [
    {
      "key": "path/to/stored__a9f3.json",
      "size": 12345,
      "last_modified": "2025-01-01T12:34:56Z"
    }
  ]
}
```

#### Fields

- `key` (string): stored key (includes postfix).
- `size` (number): object size in bytes (from filesystem stat).
- `last_modified` (string): RFC 3339 timestamp in UTC (from filesystem mtime).

---

## 11. Security (minimal)

- No auth (LAN / PoC)
- Path validation is required before mapping to local FS:
  - URL-decode the key (once) before validation.
  - Reject if the decoded key contains `..` path segments or attempts traversal.
  - Reject absolute paths (`/`, drive letters, or `\`-rooted paths on Windows).
- Only accept metadata headers with the explicit prefix `x-amz-meta-hfs-*`.
  - Reject any other `x-amz-meta-*` keys.
- On rejection:
  - Use `400 Bad Request` for invalid paths or invalid metadata headers.
  - Use `403 Forbidden` if policy-enforced denial is desired (e.g., future auth).

---

## 12. Easy retreat

- Data stays as **plain files**
- Metadata is **JSON**
- Data remains after stopping HumbleFS
- Migration works via `cp` / `rsync` / `tar`

---

## 13. Out of scope

- multipart upload
- versioning (postfix covers it)
- lifecycle / policy / ACL
- presigned URLs
- high performance / high concurrency

---

## 14. Summary

**HumbleFS is low-ambition, but strong in retreat.**

- Avoid over-engineering
- Leverage the simplicity of local FS
- Keep structures human-readable
- Enable easy exit from PoC
