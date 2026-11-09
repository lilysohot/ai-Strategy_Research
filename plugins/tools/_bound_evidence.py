"""Immutable evidence packets for checks; no retrieval or sufficiency inference."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any


def digest(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def build_review_packet(checks: list[dict[str, Any]], *, bus: Any, task_id: str) -> dict[str, Any]:
    """Pin originals at dispatch, verifying the versions already bound by bind_checks."""
    sources = {}
    bindings = {}
    for check in checks:
        keys = []
        for source in [check["subject"], *check["evidence"]]:
            key = source["key"]
            keys.append(key)
            if key in sources or not source.get("job_id") or source.get("ref"):
                continue
            found = bus.get_job_result(task_id, source["job_id"])
            if found is None:
                raise ValueError(f"bound source disappeared: {key}")
            metadata = found[1].metadata
            records = []
            for field in ("corpus_evidence", "web_evidence", "corpus_document_reads"):
                values = metadata.get(field) or []
                expected = source.get(field + "_sha256")
                if expected and digest(values) != expected:
                    raise ValueError(f"bound source version changed: {key}/{field}")
                if not expected:
                    continue
                if field != "corpus_document_reads":
                    records.extend(deepcopy(values))
            sources[key] = {
                "records": records,
                "document_reads": deepcopy(metadata.get("corpus_document_reads") or [])
                if source.get("corpus_document_reads_sha256") else [],
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
                "record_count": len(source["records"]),
                "document_reads": source["document_reads"],
            }
            for key, source in packet["sources"].items()
        },
    }
