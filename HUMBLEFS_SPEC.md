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

## 2. Backend directory layout

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

## 3. Key-to-path mapping

### 3.1 Basic mapping

```
PUT /bucket/path/to/result.json
```

↓

```
<root>/bucket/path/to/result.json
```

---

## 4. Collision avoidance (postfix)

HumbleFS uses postfixes to avoid same-name collisions by default.

### 4.1 Postfix format (recommended)

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

## 5. Postfix control via metadata headers

`x-amz-meta-*` headers are interpreted as the control plane.

> This is an intentional S3 deviation.

### 5.1 Reserved metadata headers

| Header | Description |
|------|----|
| `x-amz-meta-hfs-mode` | Storage mode |
| `x-amz-meta-hfs-conflict` | Conflict behavior |
| `x-amz-meta-hfs-postfix` | Explicit postfix (optional) |

### 5.2 Storage mode (`hfs-mode`)

```
x-amz-meta-hfs-mode: plain | unique | None
```

- `plain`
  - Store the specified key as-is
  - No postfix
- `unique` (default)
  - Always add a postfix and generate a unique stored key
- `None`
  - Behaves like `plain`

### 5.3 Conflict behavior (`hfs-conflict`)

```
x-amz-meta-hfs-conflict: fail | overwrite | new
```

- `fail`
  - Return 409 Conflict if the name exists
- `overwrite`
  - Overwrite existing file
- `new` (default)
  - Generate a new postfix and store as a distinct file

### 5.4 Explicit postfix (optional)

```
x-amz-meta-hfs-postfix: a9f3
```

- Use the specified postfix
- Conflict behavior follows `hfs-conflict`

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

---

## 7. PUT (store)

```
PUT /<bucket>/<key>
```

### Steps

1. Compute the target path on local FS
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
- Use `meta.json` for `Content-Type`

---

## 9. DELETE (remove)

```
DELETE /<bucket>/<key>
```

- Delete the stored key
- Delete the matching `.meta.json`

---

## 10. LIST

```
GET /<bucket>?prefix=xxx
```

- Walk the local filesystem
- Return stored keys as-is
- Grouping and logical-name mapping can be added later

---

## 11. Security (minimal)

- No auth (LAN / PoC)
- Reject `../` and absolute paths
- Whitelist `hfs-*` metadata headers

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
