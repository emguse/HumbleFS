# HumbleFS

HumbleFS is a minimal, content-addressed filesystem experiment with a tiny
HTTP API for storing and retrieving objects.

## Project layout

- `humblefs/` — Python implementation.
- `HUMBLEFS_SPEC.md` — Format specification.
- `HUMBLEFS_IMPLEMENTATION_NOTES.md` — Implementation notes and decisions.
- `humblefs.toml` — Default configuration (root path).
- `pyproject.toml` — Project metadata and dependencies.
- `uv.lock` — Locked dependency versions.
- `tests/` — Test coverage for the reference implementation.

## Getting started

Create a fresh environment with `uv`, install the project, and run it:

```bash
uv sync
uv run uvicorn humblefs.app:app --reload
```

## Initial setup

HumbleFS needs a writable root directory for storing buckets. You can set this in
one of two ways:

1) Environment variable (highest priority)

```bash
export HUMBLEFS_ROOT="/absolute/path/to/humblefs-root"
```

2) Config file (default: `humblefs.toml`)

```toml
root = "/absolute/path/to/humblefs-root"
```

You can override the config path with `HUMBLEFS_CONFIG` if needed:

```bash
export HUMBLEFS_CONFIG="/absolute/path/to/humblefs.toml"
```

The root directory must already exist and be writable.

## Usage (curl)

Assuming the server is running at `http://localhost:8000`.

Upload an object (PUT):

```bash
curl -X PUT \
  --data-binary @./path/to/file.txt \
  http://localhost:8000/my-bucket/path/to/file.txt
```

Upload with metadata and unique naming:

```bash
curl -X PUT \
  -H "x-amz-meta-hfs-mode: unique" \
  -H "x-amz-meta-hfs-conflict: new" \
  --data-binary @./path/to/file.txt \
  http://localhost:8000/my-bucket/path/to/file.txt
```

Add user metadata:

```bash
curl -X PUT \
  -H "x-amz-meta-hfs-owner: alice" \
  -H "x-amz-meta-hfs-purpose: demo" \
  --data-binary @./path/to/file.txt \
  http://localhost:8000/my-bucket/path/to/file.txt
```

Download an object (GET):

```bash
curl -o file.txt \
  http://localhost:8000/my-bucket/path/to/file.txt
```

List objects in a bucket (GET):

```bash
curl http://localhost:8000/my-bucket
```

List objects with a prefix filter:

```bash
curl "http://localhost:8000/my-bucket?prefix=path/"
```

Delete an object (DELETE):

```bash
curl -X DELETE \
  http://localhost:8000/my-bucket/path/to/file.txt
```

## Metadata and mode switches

HumbleFS accepts S3-style metadata headers with the prefix
`x-amz-meta-hfs-`. These are persisted into the `.meta.json` sidecar file.

You can control storage behavior with the following switches:

- `x-amz-meta-hfs-mode` (or query `hfs-mode`): `plain`, `unique`, `none`
- `x-amz-meta-hfs-conflict` (or query `hfs-conflict`): `overwrite`, `fail`, `new`
- `x-amz-meta-hfs-postfix` (or query `hfs-postfix`): 3-6 lowercase letters/digits

Notes:

- `plain`: use the logical key as-is.
- `unique`: append a `__<postfix>` suffix to the filename.
- `new`: only creates a new object when a unique postfix is used; otherwise conflicts.
- If `hfs-postfix` is not provided with `unique`, HumbleFS generates one.

## License

MIT. See [LICENSE](LICENSE).
