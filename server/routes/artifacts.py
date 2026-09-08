"""Artifact listing + download + preview (T2.9, P2.3).

  GET /api/runs/{run_id}/artifacts                    list a run's deliverables
  GET /api/runs/{run_id}/artifacts/download?path=...  download one by rel_path
  GET /api/runs/{run_id}/artifacts/preview?path=...   read-only preview payload

All routes declare ``get_current_user``: artifacts belong to a run, the run
belongs to a user, and ownership is enforced at the DB layer (``store`` checks the
run's ``user_id``) so a guessed run id yields 404 rather than another user's file.

Path traversal is the one real risk on the download route. The caller supplies a
``rel_path`` (posix-relative to the run's ``ws/outputs``), and it is turned into a
filesystem path in exactly one place — :func:`server.artifacts.resolve_artifact_path`
— which rejects absolute paths, ``..`` traversal and symlinks that escape the
outputs root. We never join an untrusted path ourselves.
"""

from __future__ import annotations

import base64
import json
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse

from server.artifacts import resolve_artifact_path
from server.config import run_dir_for
from server.deps import get_current_user
from server.store import User as UserModel
from server.store import get_run, list_artifacts

router = APIRouter(prefix="/api/runs", tags=["artifacts"])


def _artifact_view(a: object) -> dict[str, object]:
    """Project an artifact row; ``rel_path`` is the download handle."""
    return {
        "rel_path": a.rel_path,  # type: ignore[attr-defined]
        "size": a.size,  # type: ignore[attr-defined]
        "sha256": a.sha256,  # type: ignore[attr-defined]
        "created_at": (  # type: ignore[attr-defined]
            a.created_at.isoformat() if a.created_at else None  # type: ignore[attr-defined]
        ),
    }


async def _owned_run(run_id: str, user_id: uuid.UUID) -> uuid.UUID:
    """Resolve ``run_id`` to a UUID, enforcing ownership (404 on mismatch)."""
    try:
        rid = uuid.UUID(run_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="run not found"
        ) from None
    run = await get_run(run_id=rid, user_id=user_id)
    if run is None:
        # Uniform 404: don't distinguish "not yours" from "doesn't exist".
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="run not found"
        ) from None
    return rid


@router.get("/{run_id}/artifacts")
async def list_run_artifacts(
    run_id: str, user: UserModel = Depends(get_current_user)
) -> dict[str, object]:
    """List the run's output artifacts (owner-only, metadata views)."""
    # _owned_run enforces ownership (404 on mismatch); its return value is the
    # normalised id used for the store lookup.
    rid = await _owned_run(run_id, user.id)
    rows = await list_artifacts(run_id=rid, user_id=user.id)
    return {"run_id": str(rid), "artifacts": [_artifact_view(a) for a in rows]}


@router.get("/{run_id}/artifacts/download")
async def download_artifact(
    run_id: str,
    path: str = Query(..., description="rel_path relative to ws/outputs"),
    user: UserModel = Depends(get_current_user),
) -> FileResponse:
    """Stream one artifact file back to the owner (path contained to ws/outputs)."""
    # Ownership gate only — the id itself is not needed; the path is resolved
    # against the run's own outputs dir below.
    await _owned_run(run_id, user.id)
    # Containment happens inside resolve_artifact_path — the only place an
    # untrusted string becomes a filesystem path. It returns None for anything
    # that escapes the run's outputs dir (absolute paths, ../, escaping symlinks).
    resolved = resolve_artifact_path(run_id, path)
    if resolved is None:
        # 404 (not 400) for a traversal attempt: confirming that a path is
        # *malformed* is a small oracle for probing the filesystem layout.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="artifact not found"
        ) from None
    # Belt and braces: the resolved file must still sit under this run's outputs
    # after ownership passed, so a stale/renamed row cannot widen the read.
    filename = resolved.name
    return FileResponse(
        resolved,
        filename=filename,
        media_type="application/octet-stream",
        headers={"X-Content-Type-Options": "nosniff"},
    )


# ── preview (P2.3, cli-web-parity.md §5.4) ─────────────────────

# Extension allowlists for the preview classifier. SVG deliberately counts as
# text: its source is shown in a <pre>, never injected as markup.
_PREVIEW_IMAGE_EXTS = {"png", "jpg", "jpeg", "gif", "webp", "bmp", "ico"}
_PREVIEW_TEXT_EXTS = {
    "md", "markdown", "txt", "log", "csv", "tsv", "json", "jsonl", "yaml",
    "yml", "toml", "ini", "cfg", "env", "xml", "svg", "html", "css", "js",
    "mjs", "cjs", "ts", "tsx", "jsx", "py", "pyi", "sh", "bash", "sql", "rs",
    "go", "java", "kt", "c", "h", "cpp", "hpp", "cs", "rb", "php", "lua",
    "ipynb", "gitignore", "dockerfile", "makefile",
}
# Containers/office documents the web UI never renders inline (download-only).
_PREVIEW_BINARY_EXTS = {
    "pdf", "zip", "gz", "tgz", "tar", "7z", "rar", "doc", "docx", "xls",
    "xlsx", "ppt", "pptx", "bin", "exe", "so", "dylib", "pyc", "pkl", "pickle",
    "parquet", "feather", "sqlite", "db", "h5", "npz", "npy", "pt", "onnx",
}
_IMAGE_MIME = {
    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
    "gif": "image/gif", "webp": "image/webp", "bmp": "image/bmp",
    "ico": "image/x-icon",
}
_PREVIEW_MAX_BYTES = 256 * 1024
_PREVIEW_MAX_LINES = 2_000
_PREVIEW_IMAGE_MAX_BYTES = 5 * 1024 * 1024
_SNIFF_BYTES = 8_192


def _preview_kind(rel_path: str, resolved: Path) -> str:
    """Classify a resolved file as ``image`` | ``text`` | ``binary``.

    Unknown extensions are sniffed for NUL bytes (a cheap binary oracle);
    text-ish content still previews as text.
    """
    ext = Path(rel_path).suffix.lower().lstrip(".")
    if ext in _PREVIEW_IMAGE_EXTS:
        return "image"
    if ext in _PREVIEW_TEXT_EXTS:
        return "text"
    if ext in _PREVIEW_BINARY_EXTS:
        return "binary"
    try:
        with resolved.open("rb") as fh:
            return "binary" if b"\x00" in fh.read(_SNIFF_BYTES) else "text"
    except OSError:
        return "binary"


@router.get("/{run_id}/artifacts/preview")
async def preview_artifact(
    run_id: str,
    path: str = Query(..., description="rel_path relative to ws/outputs"),
    user: UserModel = Depends(get_current_user),
) -> dict[str, object]:
    """Read-only preview payload: ``{kind, content?, truncated}``.

    Same ownership + containment contract as download; the path is turned
    into a filesystem path only inside ``resolve_artifact_path``. Text is
    capped by bytes and lines (full content lives on disk); images ride back
    as data URLs; binary returns no content so the UI offers the download.
    """
    await _owned_run(run_id, user.id)
    resolved = resolve_artifact_path(run_id, path)
    if resolved is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="artifact not found"
        ) from None

    kind = _preview_kind(path, resolved)
    try:
        size = resolved.stat().st_size
    except OSError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="artifact not found"
        ) from None

    if kind == "image":
        if size > _PREVIEW_IMAGE_MAX_BYTES:
            # Too big to inline — the download button is the fallback.
            return {"kind": "binary", "truncated": False}
        mime = _IMAGE_MIME.get(Path(path).suffix.lower().lstrip("."), "application/octet-stream")
        payload = base64.b64encode(resolved.read_bytes()).decode("ascii")
        return {"kind": "image", "content": f"data:{mime};base64,{payload}", "truncated": False}

    if kind == "binary":
        return {"kind": "binary", "truncated": False}

    # Text: read at most the byte cap, then cut to the line cap.
    truncated = size > _PREVIEW_MAX_BYTES
    try:
        raw = resolved.open("rb").read(_PREVIEW_MAX_BYTES)
    except OSError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="artifact not found"
        ) from None
    text = raw.decode("utf-8", errors="replace")
    lines = text.split("\n")
    if len(lines) > _PREVIEW_MAX_LINES:
        text = "\n".join(lines[:_PREVIEW_MAX_LINES])
        truncated = True
    return {"kind": "text", "content": text, "truncated": truncated}


# ── run diff (P2.5, cli-web-parity.md §5.4) ─────────────────────


@router.get("/{run_id}/diff")
async def run_diff(
    run_id: str, user: UserModel = Depends(get_current_user)
) -> dict[str, object]:
    """Serve the worker-generated ``<run_root>/diff.json`` verbatim.

    No path handling at all on this route: the worker already resolved every
    path against the writable roots when it built the payload. A run without a
    generated diff (older run / crash / no changes recorded) is a 404 so the
    UI can hide the Diff tab. Contents are the agent's own deliverable data,
    same trust level as download/preview.
    """
    # Ownership gate only — the file is keyed by the raw run_id below, so the
    # normalised id is not needed.
    await _owned_run(run_id, user.id)
    try:
        return json.loads(
            # run_id as-is (the worker's run-dir key is the same hex string the
            # orchestrator minted; no UUID re-normalisation).
            (run_dir_for(run_id) / "diff.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="diff not available"
        ) from None
