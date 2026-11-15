"""Immutable evidence packets for checks; no retrieval or sufficiency inference."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any


def digest(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def build_review_packet(
    checks: list[dict[str, Any]],
    *,
    bus: Any,
    task_id: str,
    max_inline_records: int | None = None,
) -> dict[str, Any]:
    """Pin originals at dispatch, verifying the versions already bound by bind_checks.

    A handoff ``ref`` names a model research product, not source text. The
    originals captured by the owning job stay in a version-pinned background
    snapshot for targeted readback; the inlined records are only the ones this
    check must read in one pass. Both binding shapes share this path, so a file
    ref cannot turn a bound packet into an empty "small" job.
    """
    if max_inline_records is None:
        from plugins.tools._verification import MAX_BOUND_RECORDS_PER_CHECK

        max_inline_records = MAX_BOUND_RECORDS_PER_CHECK
    sources: dict[str, Any] = {}
    bindings: dict[str, list[str]] = {}
    for check in checks:
        keys = []
        for source in [check["subject"], *check["evidence"]]:
            key = source["key"]
            keys.append(key)
            if key in sources or not source.get("job_id"):
                continue
            found = bus.get_job_result(task_id, source["job_id"])
            if found is None:
                raise ValueError(f"bound source disappeared: {key}")
            metadata = found[1].metadata
            records: list[dict[str, Any]] = []
            for field in ("corpus_evidence", "web_evidence", "corpus_document_reads"):
                values = metadata.get(field) or []
                expected = source.get(field + "_sha256")
                if expected and digest(values) != expected:
                    raise ValueError(f"bound source version changed: {key}/{field}")
                if not expected:
                    continue
                if field != "corpus_document_reads":
                    records.extend(deepcopy(values))
            document_reads = deepcopy(metadata.get("corpus_document_reads") or []) if source.get(
                "corpus_document_reads_sha256"
            ) else []
            declares_originals = any(
                source.get(field + "_sha256") for field in ("corpus_evidence", "web_evidence")
            )
            if declares_originals and not records:
                raise ValueError(f"bound source has no readable captured originals: {key}")
            on_demand = bool(source.get("ref")) and len(records) > max_inline_records
            snapshot: dict[str, Any] = {
                "scope": "bound_evidence_snapshot",
                "content_kind": "captured_tool_observations",
                "report_content_kind": (
                    "model_research_product" if source.get("ref") else "job_report"
                ),
                "origin_job_id": source["job_id"],
                "handoff_ref": str(source.get("ref") or ""),
                "record_count": len(records),
                "document_reads": document_reads,
                "sha256": digest({"records": records, "document_reads": document_reads}),
            }
            if on_demand:
                # Keep one copy of the full originals in the background, never
                # duplicate them into the inlined selection.
                snapshot["records"] = records
            sources[key] = {
                "records": [] if on_demand else records,
                "document_reads": document_reads,
                "selection_mode": "on_demand" if on_demand else "inline",
                "snapshot": snapshot,
            }
        bindings[check["binding_id"]] = list(dict.fromkeys(keys))
    body = {"bindings": bindings, "sources": sources}
    return {**body, "packet_sha256": digest(body)}


def packet_index(packet: dict[str, Any]) -> dict[str, Any]:
    """Pointers for omitted originals; these are not newly observed source content."""
    return {
        "packet_sha256": packet["packet_sha256"],
        "scope": "bound_evidence_snapshot", "fresh_observation": False,
        "source_availability": "not_rechecked",
        "sources": {
            key: {
                "record_count": len(
                    source.get("records") or (source.get("snapshot") or {}).get("records") or []
                ),
                "inline_record_count": len(source.get("records") or []),
                "snapshot_record_count": (source.get("snapshot") or {}).get(
                    "record_count", len(source.get("records") or [])
                ),
                "selection_mode": source.get("selection_mode", "inline"),
                "report_content_kind": (source.get("snapshot") or {}).get(
                    "report_content_kind", "job_report"
                ),
                "document_reads": source.get("document_reads") or [],
            }
            for key, source in packet["sources"].items()
        },
    }
