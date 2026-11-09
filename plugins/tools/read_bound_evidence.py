"""Read version-bound tool evidence already captured by the current check's sources."""

from __future__ import annotations

import json

from frontier_agent.core.tool import tool


@tool
async def read_bound_evidence(
    binding_id: str, source_key: str, record_index: int = 0, offset: int = 0, locator: str = "",
) -> str:
    """Read captured tool evidence from this verification's immutable packet.

    No network or corpus query occurs. This reads historical tool observations,
    not a fresh availability check. Use inline original evidence first. Missing
    evidence stays an unchecked result with unresolved_issues for the coordinator.
    Preserve content_kind and coverage: model-assisted extraction is not original text.

    Args:
        binding_id: Exact binding_id of the current check.
        source_key: Exact subject/evidence key bound to that check.
        record_index: Zero-based captured record; follow next for additional records.
        offset: Character offset within that record; follow next for a long record.
        locator: Optional exact captured locator or evidence_ref to read just that record.
    """
    from plugins.tools._verification import get_verification_scope

    def error(code: str) -> str:
        return json.dumps({"ok": False, "code": code, "fresh_observation": False})

    scope = get_verification_scope()
    if scope is None:
        return error("no_verification_scope")
    packet = scope.packet
    if source_key not in packet.get("bindings", {}).get(binding_id, []):
        return error("unbound_source")
    source = packet.get("sources", {}).get(source_key)
    if not source or not source["records"]:
        return error("no_captured_originals")
    records = source["records"]
    if locator:
        matches = [i for i, r in enumerate(records) if locator in {
            r.get("locator"), r.get("source"), r.get("evidence_ref"),
        }]
        if len(matches) != 1:
            return json.dumps({
                "ok": False, "code": "locator_not_unique_in_bound_source",
                "fresh_observation": False, "matching_record_count": len(matches),
                "record_indices": matches[:50],
                "hint": "Use record_index without locator to select a captured fragment; "
                "no matches means this original is absent from the bound packet.",
            })
        record_index = matches[0]
    if not 0 <= record_index < len(records):
        return error("invalid_record_index")
    record = records[record_index]
    text = record.get("text", "")
    if not isinstance(text, str) or not 0 <= offset <= len(text):
        return error("invalid_offset")
    end = min(len(text), offset + 4000)
    # Preserve provenance and limitations, including model-assisted/partial web text.
    # Oversized metadata fails explicitly below rather than silently dropping its limits.
    pointer = {k: record[k] for k in (
        "doc_id", "locator", "source", "evidence_ref", "sha256",
        "content_kind", "status", "coverage", "detail",
    ) if k in record}
    while True:
        next_position = (
            {"record_index": record_index, "offset": end} if end < len(text)
            else {"record_index": record_index + 1, "offset": 0}
            if not locator and record_index + 1 < len(records)
            else None
        )
        payload = {
            "ok": True, "scope": "bound_evidence_snapshot", "fresh_observation": False,
            "source_availability": "not_rechecked", "packet_sha256": packet["packet_sha256"],
            "binding_id": binding_id, "source_key": source_key,
            "record_index": record_index, "record_count": len(records),
            "record": {**pointer, "text": text[offset:end], "source_fragment": record.get("fragment")},
            "range_in_record": {"start": offset, "end": end},
            "record_complete": offset == 0 and end == len(text),
            "next": next_position, "end_of_selection": next_position is None,
            "document_coverage": "not_inferred_from_snapshot_pagination",
        }
        encoded = json.dumps(payload, ensure_ascii=False)
        if len(encoded) <= 6000:
            return encoded
        if end <= offset:
            return error("record_metadata_too_large")
        end = offset + (end - offset) // 2
