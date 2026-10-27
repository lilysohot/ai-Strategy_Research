"""Durable aliases for fetch cursors and exact source excerpts.

Receipts bind data, never authority or delivery. Manifests materialize the original
text/coordinates and still verify them against live sources and the run ledger.
Only returned pages are persisted; pagination's sizing probes perform no writes.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from plugins.corpus.cursor import CursorError

logger = logging.getLogger(__name__)
_REF = re.compile(r"(ce|cpage):([0-9a-f]{32})\Z")
_MAX_BYTES = 1_000_000


class ToolReferenceError(ValueError):
    """Missing, corrupt or mismatched receipt; callers must not guess."""


def _root() -> Path:
    configured = os.environ.get("CORPUS_TOOL_REF_ROOT", "").strip()
    return (
        Path(configured).expanduser().resolve()
        if configured
        else Path(__file__).resolve().parents[2] / "data/corpus-tool-refs"
    )


def _encode(kind: str, value: Any) -> tuple[str, bytes]:
    record = {
        "version": 1,
        "target": os.environ.get("CORPUS_TARGET_DB", ""),
        "kind": kind,
        "value": value,
    }
    raw = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return f"{kind}:" + hashlib.sha256(raw).hexdigest()[:32], raw


def _store(kind: str, value: Any) -> str:
    ref, raw = _encode(kind, value)
    if len(raw) > _MAX_BYTES:
        raise ToolReferenceError("tool_receipt_too_large")
    root = _root()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = root / (ref.split(":")[1] + ".json")
    if path.exists():
        with path.open("rb") as stream:
            if stream.read(_MAX_BYTES + 1) != raw:
                raise ToolReferenceError("tool_receipt_integrity_error")
        return ref
    fd, name = tempfile.mkstemp(prefix=".receipt-", dir=root)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)
    return ref


def _load(ref: str, kind: str) -> Any:
    match = _REF.fullmatch(ref) if isinstance(ref, str) else None
    if not match or match[1] != kind:
        raise ToolReferenceError("invalid_tool_reference")
    try:
        with (_root() / (match[2] + ".json")).open("rb") as stream:
            raw = stream.read(_MAX_BYTES + 1)
        if len(raw) > _MAX_BYTES or hashlib.sha256(raw).hexdigest()[:32] != match[2]:
            raise ToolReferenceError("tool_receipt_integrity_error")
        record = json.loads(raw)
        if (
            record["version"] != 1
            or record["kind"] != kind
            or record["target"] != os.environ.get("CORPUS_TARGET_DB", "")
        ):
            raise ToolReferenceError("tool_receipt_binding_mismatch")
        return record["value"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ToolReferenceError("tool_receipt_unavailable_or_invalid；请重新取回原文") from exc


def _evidence(doc_id: str, item: dict[str, Any]) -> dict[str, Any]:
    start = (item.get("fragment") or {}).get("start", 0)
    return {
        "doc_id": doc_id,
        "locator": item["locator"],
        "quote": item["text"],
        "source_start": start,
        "source_end": start + len(item["text"]),
    }


def fetch_evidence_ref(doc_id: str, item: dict[str, Any]) -> str:
    """Compute the eventual receipt ID, including its cost in page sizing."""
    return _encode("ce", _evidence(doc_id, item))[0]


def publish_fetch_references(body: str) -> str:
    """Persist only emitted evidence and replace the encoded cursor with a short ID."""
    payload = json.loads(body)
    items = payload.get("items", [payload])
    cursor = payload.get("next_cursor")
    try:
        for item in items:
            if "evidence_ref" in item:
                _store("ce", _evidence(payload["doc_id"], item))
        if cursor:
            payload["next_cursor"] = _store("cpage", cursor)
    except (OSError, ToolReferenceError):
        # Keep the self-contained legacy contract when durable storage is down.
        # Never emit an ID that another worker cannot resolve; never grow a page.
        logger.warning("corpus fetch reference storage unavailable; using inline evidence/cursor")
        for item in items:
            item.pop("evidence_ref", None)
        if cursor:
            payload["next_cursor"] = cursor
    return json.dumps(payload, ensure_ascii=False)


def resolve_cursor_reference(cursor: str) -> str:
    """Accept historical self-contained cursors as well as persistent aliases."""
    if not isinstance(cursor, str) or not cursor.startswith("cpage:"):
        return cursor
    try:
        value = _load(cursor, "cpage")
        if not isinstance(value, str):
            raise ToolReferenceError("invalid_cursor_receipt")
        return value
    except ToolReferenceError as exc:
        raise CursorError(str(exc)) from exc


def resolve_evidence_reference(ref: str) -> dict[str, Any]:
    """Materialize one selected excerpt, without accepting model-authored text."""
    if isinstance(ref, str) and ref.startswith("eref:"):
        from plugins.corpus.search_refs import resolve_evidence_selection

        return resolve_evidence_selection(ref)
    value = _load(ref, "ce")
    if not isinstance(value, dict):
        raise ToolReferenceError("invalid_evidence_receipt")
    return value
