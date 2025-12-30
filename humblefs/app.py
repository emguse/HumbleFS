import json
import mimetypes
import os
import re
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from tempfile import NamedTemporaryFile
from urllib.parse import unquote

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from tomllib import TOMLDecodeError, load as toml_load

POSTFIX_PATTERN = re.compile(r"^[a-z0-9]{3,6}$")
META_PREFIX = "x-amz-meta-hfs-"
AMZ_META_PREFIX = "x-amz-meta-"

@asynccontextmanager
async def lifespan(_: FastAPI):
    _validate_root()
    yield


app = FastAPI(title="HumbleFS", lifespan=lifespan)


def _utc_timestamp(value: float | None = None) -> str:
    if value is None:
        current = datetime.now(timezone.utc)
    else:
        current = datetime.fromtimestamp(value, tz=timezone.utc)
    return current.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _validate_root() -> Path:
    root_value = os.environ.get("HUMBLEFS_ROOT")
    if not root_value:
        config_path = os.environ.get("HUMBLEFS_CONFIG", "humblefs.toml")
        config_file = Path(config_path)
        if config_file.exists():
            try:
                with config_file.open("rb") as handle:
                    config = toml_load(handle)
            except (OSError, TOMLDecodeError) as exc:
                raise RuntimeError("Failed to read HUMBLEFS_CONFIG") from exc
            root_value = config.get("root")
            if not isinstance(root_value, str):
                raise RuntimeError("HUMBLEFS_ROOT is required")
    if not root_value:
        raise RuntimeError("HUMBLEFS_ROOT is required")
    root_path = Path(root_value)
    if not root_path.exists():
        raise RuntimeError("HUMBLEFS_ROOT does not exist")
    if not root_path.is_dir():
        raise RuntimeError("HUMBLEFS_ROOT must be a directory")
    if not os.access(root_path, os.W_OK):
        raise RuntimeError("HUMBLEFS_ROOT is not writable")
    return root_path


def _reject_invalid_metadata_headers(headers: dict[str, str]) -> None:
    for header_name in headers:
        if header_name.startswith(AMZ_META_PREFIX) and not header_name.startswith(META_PREFIX):
            raise HTTPException(status_code=400, detail="Invalid metadata header")


def _parse_user_meta(headers: dict[str, str]) -> dict[str, str]:
    user_meta = {}
    for header_name, value in headers.items():
        if header_name.startswith(META_PREFIX):
            key = f"hfs-{header_name[len(META_PREFIX) :]}"
            user_meta[key] = value
    return user_meta


def _validate_bucket(bucket: str) -> None:
    if not bucket:
        raise HTTPException(status_code=400, detail="Bucket is required")
    if bucket in {".", ".."}:
        raise HTTPException(status_code=400, detail="Invalid bucket")
    if "/" in bucket or "\\" in bucket:
        raise HTTPException(status_code=400, detail="Invalid bucket")


def _decode_and_validate_key(key: str) -> str:
    decoded = unquote(key)
    if decoded.startswith(("/", "\\")):
        raise HTTPException(status_code=400, detail="Invalid key")
    if re.match(r"^[A-Za-z]:", decoded):
        raise HTTPException(status_code=400, detail="Invalid key")
    normalized = decoded.replace("\\", "/")
    parts = PurePosixPath(normalized).parts
    if any(part == ".." for part in parts):
        raise HTTPException(status_code=400, detail="Invalid key")
    return decoded


def _generate_postfix() -> str:
    length = secrets.choice([3, 4, 5, 6])
    return "".join(secrets.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(length))


def _split_key(key: str) -> tuple[Path, str, str]:
    key_path = Path(key)
    directory = key_path.parent if key_path.parent != Path(".") else Path("")
    filename = key_path.name
    base, ext = os.path.splitext(filename)
    return directory, base, ext


def _build_stored_key(logical_key: str, mode: str, postfix: str | None) -> str:
    directory, base, ext = _split_key(logical_key)
    if mode in {"plain", "none"}:
        return logical_key
    if postfix is None:
        postfix = _generate_postfix()
    stored_filename = f"{base}__{postfix}{ext}"
    return str(directory / stored_filename) if directory.as_posix() else stored_filename


def _resolve_content_type(
    stored_key: str, request: Request, upload_content_type: str | None = None
) -> str:
    if upload_content_type:
        return upload_content_type
    header_value = request.headers.get("content-type")
    if header_value and not header_value.startswith("multipart/"):
        return header_value
    guessed, _ = mimetypes.guess_type(stored_key)
    return guessed or "application/octet-stream"


def _collect_candidates(bucket_root: Path, logical_key: str) -> list[Path]:
    directory, base, ext = _split_key(logical_key)
    target_dir = bucket_root / directory
    if not target_dir.exists():
        return []
    candidates: list[Path] = []
    for entry in target_dir.iterdir():
        if not entry.is_file():
            continue
        if entry.name.endswith(".meta.json"):
            continue
        if entry.name == f"{base}{ext}":
            candidates.append(entry)
            continue
        if ext:
            prefix = f"{base}__"
            if entry.name.startswith(prefix) and entry.name.endswith(ext):
                postfix = entry.name[len(prefix) : -len(ext)]
                if POSTFIX_PATTERN.match(postfix):
                    candidates.append(entry)
        else:
            prefix = f"{base}__"
            if entry.name.startswith(prefix):
                postfix = entry.name[len(prefix) :]
                if POSTFIX_PATTERN.match(postfix):
                    candidates.append(entry)
    return candidates


def _select_newest_candidate(candidates: list[Path]) -> Path:
    newest_time: str | None = None
    newest_path: Path | None = None
    tied = False
    for candidate in candidates:
        meta_path = candidate.with_name(candidate.name + ".meta.json")
        if not meta_path.exists():
            raise HTTPException(status_code=409, detail="Unable to resolve stored key")
        try:
            with meta_path.open("r", encoding="utf-8") as handle:
                meta = json.load(handle)
            created_at = meta.get("created_at")
        except (OSError, json.JSONDecodeError):
            raise HTTPException(status_code=409, detail="Unable to resolve stored key")
        if not created_at:
            raise HTTPException(status_code=409, detail="Unable to resolve stored key")
        if newest_time is None or created_at > newest_time:
            newest_time = created_at
            newest_path = candidate
            tied = False
        elif created_at == newest_time:
            tied = True
    if newest_path is None or tied:
        raise HTTPException(status_code=409, detail="Unable to resolve stored key")
    return newest_path


@app.put("/{bucket}/{key:path}")
async def put_object(
    bucket: str,
    key: str,
    request: Request,
    hfs_mode: str | None = Query(
        None, alias="hfs-mode", description="Override x-amz-meta-hfs-mode \"plain\", \"unique\""
    ),
    hfs_conflict: str | None = Query(
        None, alias="hfs-conflict", description="Override x-amz-meta-hfs-conflict \"fail\", \"overwrite\", \"new\""
    ),
    hfs_postfix: str | None = Query(
        None, alias="hfs-postfix", description="Override x-amz-meta-hfs-postfix"
    ),
    user_meta_raw: str | None = Form(
        None, description="JSON object for user metadata (keys map to x-amz-meta-hfs-*)"
    ),
    file: UploadFile | None = File(
        None, description="Upload file via multipart/form-data for Swagger UI"
    ),
) -> JSONResponse:
    _validate_bucket(bucket)
    decoded_key = _decode_and_validate_key(key)
    headers = {name.lower(): value for name, value in request.headers.items()}
    _reject_invalid_metadata_headers(headers)
    user_meta = _parse_user_meta(headers)
    if hfs_mode is not None:
        user_meta["hfs-mode"] = hfs_mode
    if hfs_conflict is not None:
        user_meta["hfs-conflict"] = hfs_conflict
    if hfs_postfix is not None:
        user_meta["hfs-postfix"] = hfs_postfix
    if user_meta_raw:
        try:
            extra_meta = json.loads(user_meta_raw)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail="Invalid user_meta JSON") from exc
        if not isinstance(extra_meta, dict):
            raise HTTPException(status_code=400, detail="Invalid user_meta JSON")
        for key, value in extra_meta.items():
            if not isinstance(key, str):
                raise HTTPException(status_code=400, detail="Invalid user_meta JSON")
            if not isinstance(value, str):
                raise HTTPException(status_code=400, detail="Invalid user_meta JSON")
            stored_key = key if key.startswith("hfs-") else f"hfs-{key}"
            user_meta[stored_key] = value

    mode = user_meta.get("hfs-mode", "plain") or "plain"
    conflict = user_meta.get("hfs-conflict", "overwrite") or "overwrite"
    postfix = user_meta.get("hfs-postfix")

    if mode not in {"plain", "unique", "none"}:
        raise HTTPException(status_code=400, detail="Invalid hfs-mode")
    if conflict not in {"fail", "overwrite", "new"}:
        raise HTTPException(status_code=400, detail="Invalid hfs-conflict")
    if postfix is not None and not POSTFIX_PATTERN.match(postfix):
        raise HTTPException(status_code=400, detail="Invalid hfs-postfix")

    root = _validate_root()
    bucket_root = root / bucket
    target_dir = bucket_root / Path(decoded_key).parent
    target_dir.mkdir(parents=True, exist_ok=True)

    stored_key = _build_stored_key(decoded_key, mode, postfix)
    target_path = bucket_root / stored_key

    if postfix is not None and target_path.exists() and conflict != "overwrite":
        raise HTTPException(status_code=409, detail="Object already exists")

    if conflict == "fail" and target_path.exists():
        raise HTTPException(status_code=409, detail="Object already exists")

    if conflict == "new" and mode == "unique" and postfix is None:
        while target_path.exists():
            stored_key = _build_stored_key(decoded_key, mode, None)
            target_path = bucket_root / stored_key

    if conflict == "new" and mode in {"plain", "none"} and target_path.exists():
        raise HTTPException(status_code=409, detail="Object already exists")

    if file is not None:
        data = await file.read()
        await file.close()
    else:
        data = await request.body()
    with NamedTemporaryFile(delete=False, dir=target_dir) as temp_handle:
        temp_handle.write(data)
        temp_handle.flush()
        os.fsync(temp_handle.fileno())
        temp_name = temp_handle.name

    os.replace(temp_name, target_path)

    upload_content_type = file.content_type if file is not None else None
    content_type = _resolve_content_type(stored_key, request, upload_content_type)
    meta = {
        "logical_key": decoded_key,
        "stored_key": stored_key,
        "size": len(data),
        "content_type": content_type,
        "created_at": _utc_timestamp(),
        "user_meta": {k: v for k, v in user_meta.items() if k != "hfs-postfix"},
    }
    meta_path = target_path.with_name(target_path.name + ".meta.json")
    with meta_path.open("w", encoding="utf-8") as handle:
        json.dump(meta, handle, indent=2)

    return JSONResponse({"stored_key": stored_key}, status_code=200)


@app.get("/{bucket}/{key:path}")
async def get_object(bucket: str, key: str) -> FileResponse:
    _validate_bucket(bucket)
    decoded_key = _decode_and_validate_key(key)
    root = _validate_root()
    bucket_root = root / bucket
    candidates = _collect_candidates(bucket_root, decoded_key)
    if not candidates:
        raise HTTPException(status_code=404, detail="Object not found")
    stored_path = _select_newest_candidate(candidates)
    meta_path = stored_path.with_name(stored_path.name + ".meta.json")
    with meta_path.open("r", encoding="utf-8") as handle:
        meta = json.load(handle)
    content_type = meta.get("content_type") or "application/octet-stream"
    return FileResponse(stored_path, media_type=content_type)


@app.delete("/{bucket}/{key:path}")
async def delete_object(bucket: str, key: str) -> JSONResponse:
    _validate_bucket(bucket)
    decoded_key = _decode_and_validate_key(key)
    root = _validate_root()
    bucket_root = root / bucket
    candidates = _collect_candidates(bucket_root, decoded_key)
    if not candidates:
        raise HTTPException(status_code=404, detail="Object not found")
    stored_path = _select_newest_candidate(candidates)
    meta_path = stored_path.with_name(stored_path.name + ".meta.json")
    stored_path.unlink(missing_ok=True)
    meta_path.unlink(missing_ok=True)
    return JSONResponse({"deleted": True}, status_code=200)


@app.get("/{bucket}")
async def list_objects(bucket: str, prefix: str | None = None) -> JSONResponse:
    _validate_bucket(bucket)
    root = _validate_root()
    bucket_root = root / bucket
    if not bucket_root.exists():
        raise HTTPException(status_code=404, detail="Bucket not found")
    objects = []
    for path in bucket_root.rglob("*"):
        if not path.is_file():
            continue
        if path.name.endswith(".meta.json"):
            continue
        key = str(path.relative_to(bucket_root).as_posix())
        if prefix and not key.startswith(prefix):
            continue
        stat = path.stat()
        objects.append(
            {
                "key": key,
                "size": stat.st_size,
                "last_modified": _utc_timestamp(stat.st_mtime),
            }
        )
    return JSONResponse({"objects": objects}, status_code=200)
