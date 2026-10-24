"""Persistent, content-addressed search receipts; never evidence delivery by themselves.

One receipt retains the original v1 hit, including its complete scope and hashes.
Short references are aliases, not authority: fetch still checks the live source,
and the ledger counts only intact text actually present in a tool message.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

CONTRACT = "native-search-evidence-v2"
_SCOPE = re.compile(r"sref:([0-9a-f]{64})\Z")
_EVIDENCE = re.compile(r"eref:([0-9a-f]{64}):(0|[1-9][0-9]{0,3})\Z")
_MAX_BYTES = 256_000


class SearchReferenceError(ValueError):
    """An unavailable, damaged, or mismatched receipt; callers must not guess."""


def _root() -> Path:
    configured = os.environ.get("CORPUS_SEARCH_REF_ROOT", "").strip()
    return (
        Path(configured).expanduser().resolve()
        if configured
        else (Path(__file__).resolve().parents[2] / "data/corpus-search-refs")
    )


def _store(hit: dict[str, Any]) -> str:
    record = {"version": 1, "target": os.environ.get("CORPUS_TARGET_DB", ""), "hit": hit}
    raw = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    if len(raw) > _MAX_BYTES:
        raise SearchReferenceError("search_receipt_too_large")
    digest = hashlib.sha256(raw).hexdigest()
    root = _root()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".receipt-", dir=root)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, root / (digest + ".json"))
    finally:
        Path(name).unlink(missing_ok=True)
    return digest


def _load(digest: str, doc_id: str) -> dict[str, Any]:
    try:
        with (_root() / (digest + ".json")).open("rb") as stream:
            raw = stream.read(_MAX_BYTES + 1)
        if len(raw) > _MAX_BYTES or hashlib.sha256(raw).hexdigest() != digest:
            raise SearchReferenceError("search_receipt_integrity_error")
        record = json.loads(raw)
        hit = record["hit"]
        if (
            record["version"] != 1
            or record["target"] != os.environ.get("CORPUS_TARGET_DB", "")
            or hit["doc_id"] != doc_id
            or doc_id != "cv2:" + hit["build_id"]
            or hit.get("evidence_contract") not in (None, "native-search-evidence-v1")
        ):
            raise SearchReferenceError("search_receipt_binding_mismatch")
        return hit
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise SearchReferenceError("search_receipt_unavailable_or_invalid") from exc


def resolve_scope(doc_id: str, ref: str) -> dict[str, Any]:
    """Restore one immutable offered scope; does not register its text as read."""
    match = _SCOPE.fullmatch(ref) if isinstance(ref, str) else None
    if not match:
        raise SearchReferenceError("invalid_search_scope_reference")
    return _load(match[1], doc_id)


def resolve_evidence(doc_id: str, ref: str) -> dict[str, Any]:
    """Restore an excerpt's canonical locator and full verification metadata."""
    from plugins.corpus.search_evidence import search_evidence_items

    match = _EVIDENCE.fullmatch(ref) if isinstance(ref, str) else None
    if not match:
        raise SearchReferenceError("invalid_search_evidence_reference")
    items = search_evidence_items(_load(match[1], doc_id))
    index = int(match[2])
    if index >= len(items):
        raise SearchReferenceError("search_evidence_member_missing")
    return items[index]


def canonical_locator(doc_id: str, locator: str) -> str:
    """Leave historical chunk handles intact, resolve only explicit evidence aliases."""
    if locator.startswith("eref:"):
        return str(resolve_evidence(doc_id, locator)["locator"])
    return locator


def offered_hit(hit: dict[str, Any]) -> dict[str, Any]:
    """Decode scope metadata for the ledger, never promote stored excerpts to delivered."""
    if hit.get("evidence_contract") != CONTRACT:
        return hit
    try:
        return resolve_scope(hit.get("doc_id", ""), hit.get("scope_ref", ""))
    except SearchReferenceError:
        return {}


def evidence_items(hit: dict[str, Any]) -> list[dict[str, Any]]:
    """Verify each visible text against its own persisted receipt and scope binding."""
    from plugins.corpus.search_evidence import search_evidence_items

    original = offered_hit(hit)
    if not original:
        return []
    expected = search_evidence_items(original)
    prefix = "eref:" + hit["scope_ref"][5:] + ":"
    excerpts = hit.get("excerpts")
    if not isinstance(excerpts, list):
        return []
    result = []
    for excerpt in excerpts:
        if not isinstance(excerpt, dict):
            continue
        ref = excerpt.get("ref")
        match = _EVIDENCE.fullmatch(ref) if isinstance(ref, str) else None
        if not isinstance(ref, str) or not match or not ref.startswith(prefix):
            continue
        index = int(match[2])
        if index < len(expected) and excerpt.get("text") == expected[index]["text"]:
            result.append(expected[index])
    return result


def compact_hit(hit: dict[str, Any]) -> dict[str, Any]:
    """Move verified metadata to disk while preserving all selected raw text."""
    from plugins.corpus.search_evidence import search_evidence_items

    items = search_evidence_items(hit)
    spans = hit.get("evidence_spans", [])
    if len(items) != len(spans):
        raise SearchReferenceError("invalid_producer_evidence")
    digest = _store(hit)
    # Remove only exact verified substrings and their immediately preceding renderer
    # labels. Any unmarked/partial text stays an explicitly non-citable preview.
    snippet = hit["snippet"]
    pieces = []
    pos = 0
    label = re.compile(r"【\d+/\d+(?:｜p[^】]*)?】〔原文字符\d+:\d+[^〕]*〕$")
    for span in spans:
        left, right = span["snippet_start"], span["snippet_end"]
        pieces.append(label.sub("", snippet[pos:left]))
        pos = right
    pieces.append(snippet[pos:])
    preview = "".join(pieces).strip()
    # The available block count replaces the renderer's final hidden-block notice.
    preview = re.sub(r"(?:^|\n)（同源另有\d+块未展示，可按句柄补读）$", "", preview).strip()
    return {
        "doc_id": hit["doc_id"],
        "title": hit["title"],
        "published": hit["published"],
        "excerpts": [
            {"text": item["text"], "ref": f"eref:{digest}:{i}"} for i, item in enumerate(items)
        ],
        **({"preview": preview} if preview else {}),
        "evidence_contract": CONTRACT,
        "scope_ref": "sref:" + digest,
        "available_blocks": len(hit["context_locators"]),
    }
