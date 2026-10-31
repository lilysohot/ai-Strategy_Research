"""Explicit source boundaries for incremental contextual indexing."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from plugins.corpus.preparation.intake import source_hash
from plugins.corpus.retrieval.contextual import ContextNoteError


def validate_ids(values: object) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)) or not values:
        raise ContextNoteError("source_scope_requires_nonempty_ids")
    if any(
        not isinstance(v, str) or len(v) != 64 or any(c not in "0123456789abcdef" for c in v)
        for v in values
    ):
        raise ContextNoteError("source_scope_invalid_hash")
    if len(set(values)) != len(values):
        raise ContextNoteError("source_scope_duplicate_id")
    return tuple(values)


def load_scope(path: Path) -> tuple[str, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ContextNoteError("source_scope_requires_object")
    return validate_ids(payload.get("source_allowlist"))


def extend_scope(base: Sequence[str], manifest_path: Path) -> dict:
    old = validate_ids(list(base))
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    sources = payload.get("sources") if isinstance(payload, dict) else None
    if not isinstance(sources, list) or not sources:
        raise ContextNoteError("source_scope_requires_manifest_sources")
    added = []
    for source in sources:
        if not isinstance(source, dict) or not isinstance(source.get("path"), str):
            raise ContextNoteError("source_scope_invalid_source")
        sid = source.get("source_id")
        validate_ids([sid])
        if source_hash(source["path"]) != sid:
            raise ContextNoteError("source_scope_source_hash_mismatch")
        added.append(sid)
    validate_ids(added)
    return {
        "source_allowlist": sorted(set(old) | set(added)),
        "base_sources": len(old),
        "added_source_ids": sorted(set(added) - set(old)),
    }


def select_sources(
    active: dict[str, dict[str, Any]],
    source_ids: Sequence[str] | None,
) -> dict[str, dict[str, Any]]:
    if source_ids is None:
        return active
    wanted = validate_ids(list(source_ids))
    missing = set(wanted) - set(active)
    if missing:
        raise ContextNoteError("source_scope_not_active:" + ",".join(sorted(missing)))
    return {sid: active[sid] for sid in sorted(wanted)}
