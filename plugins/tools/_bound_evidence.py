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
            # Model layer: legal evidence_refs resolved to internal locators.
            # Runtime layer: only those records are inlined; every other
            # captured original stays in the version-pinned background snapshot.
            # On-demand readback is a property of packet size, NOT of whether
            # the job happened to publish a handoff attachment.
            locators = list(source.get("record_locators") or [])
            if locators:
                allowed = set(locators)
                inline_records = [
                    deepcopy(record)
                    for record in records
                    if any(
                        record.get(field) in allowed
                        for field in ("locator", "evidence_ref", "source")
                    )
                ]
                if not inline_records:
                    raise ValueError(f"selected evidence refs have no readable records: {key}")
                selection_mode = "selected"
            elif len(records) > max_inline_records:
                inline_records = []
                selection_mode = "on_demand"
            else:
                inline_records = records
                selection_mode = "inline"
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
            if selection_mode != "inline":
                snapshot["records"] = records
            if locators:
                snapshot["selected_record_count"] = len(inline_records)
            sources[key] = {
                "records": inline_records,
                "document_reads": document_reads,
                "selection_mode": selection_mode,
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
