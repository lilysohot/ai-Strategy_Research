"""Read-only audit and convenient export for the completed r6 material round."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from plugins.corpus.evidence_pipeline import evidence_document_from_snapshot
from plugins.corpus.material_semantics import MaterialRun
from plugins.corpus.structured.config import canonical_hash
from plugins.corpus.structured.snapshot import EvidenceSnapshot

ROOT = Path(__file__).resolve().parent


def read_object(segment: Path, digest: str) -> dict:
    key = digest.removeprefix("sha256:")
    path = segment / "store" / "objects" / "sha256" / key[:2] / f"{key}.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    assert canonical_hash(value) == digest
    return value


def payload(segment: Path, artifact_sha256: str) -> MaterialRun:
    artifact = read_object(segment, artifact_sha256)
    return MaterialRun.model_validate(read_object(segment, artifact["payload_sha256"]))


def save(path: Path, value: object) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def main() -> None:
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    items = []
    relations = []
    segment_results = []
    semantic_types: Counter[str] = Counter()
    statement_roles: Counter[str] = Counter()
    attempts = 0
    total_tokens = 0
    unknown_cost_calls = 0
    source_spans_checked = 0
    slot_count = 0
    terminal_slots = 0
    for entry in manifest["segments"]:
        name = entry["name"]
        segment = ROOT / name
        summary = json.loads((segment / "summary.json").read_text(encoding="utf-8"))
        item_task = summary["material_items"]
        assert (
            item_task["execution_status"],
            item_task["protocol_status"],
            item_task["quality_status"],
            item_task["publication_status"],
        ) == ("succeeded", "valid", "accepted", "candidate")
        assert summary["plan_consistent"] is True
        assert all(
            (task["execution_status"], task["protocol_status"], task["quality_status"])
            == ("succeeded", "valid", "accepted")
            for task in summary["material_relations"]
        )
        snapshot = EvidenceSnapshot.model_validate_json(
            (segment / "snapshot.json").read_text(encoding="utf-8")
        )
        document = evidence_document_from_snapshot(snapshot, role="material_items")
        packets = {packet.packet_id: packet for packet in document.packets}
        item_run = payload(segment, item_task["artifact_sha256"])
        ledger = item_run.understanding.coverage.slot_ledger
        slot_count += len(item_run.candidate_slots)
        terminal_slots += sum(
            entry.status in {"extracted", "no_supported_item"} for entry in ledger
        )
        assert len(item_run.candidate_slots) == len(ledger) == summary["candidate_slot_count"]
        assert all(entry.status in {"extracted", "no_supported_item"} for entry in ledger)
        segment_item_ids = {item.item_id for item in item_run.understanding.items}
        for item in item_run.understanding.items:
            for evidence in item.evidence:
                packet = packets[evidence.packet_id]
                assert packet.text[evidence.start : evidence.end] == evidence.quote
                source_spans_checked += 1
            semantic_types[item.semantic_type] += 1
            statement_roles[item.statement_role] += 1
            items.append(
                {
                    "segment": name,
                    "batch_id": summary["batch_id"],
                    "artifact_sha256": item_task["artifact_sha256"],
                    **item.model_dump(mode="json"),
                }
            )
        segment_relations = 0
        for relation_task in summary["material_relations"]:
            relation_run = payload(segment, relation_task["artifact_sha256"])
            for relation in relation_run.understanding.relations:
                assert relation.from_item in segment_item_ids
                assert relation.to_item in segment_item_ids
                for evidence in relation.evidence:
                    packet = packets[evidence.packet_id]
                    assert packet.text[evidence.start : evidence.end] == evidence.quote
                    source_spans_checked += 1
                relations.append(
                    {
                        "segment": name,
                        "batch_id": summary["batch_id"],
                        "artifact_sha256": relation_task["artifact_sha256"],
                        **relation.model_dump(mode="json"),
                    }
                )
                segment_relations += 1
        attempts += len(summary["attempts"])
        total_tokens += sum(
            (attempt.get("usage") or {}).get("total_tokens") or 0 for attempt in summary["attempts"]
        )
        unknown_cost_calls += sum(entry["unknown_calls"] for entry in summary["cost_summary"])
        segment_results.append(
            {
                "segment": name,
                "candidate_slots": len(item_run.candidate_slots),
                "items": len(item_run.understanding.items),
                "relations": segment_relations,
                "attempts": len(summary["attempts"]),
            }
        )
    aggregate = {
        "schema_version": "material-live-round-export-v1",
        "run": ROOT.name,
        "source_scope": manifest["source_scope"],
        "model": manifest["model"],
        "publication_status": "candidate_not_published",
        "items": items,
        "relations": relations,
    }
    audit = {
        "run": ROOT.name,
        "segments": segment_results,
        "segment_count": len(segment_results),
        "candidate_slots": slot_count,
        "terminal_slots": terminal_slots,
        "items": len(items),
        "relations": len(relations),
        "semantic_types": dict(sorted(semantic_types.items())),
        "statement_roles": dict(sorted(statement_roles.items())),
        "source_spans_checked": source_spans_checked,
        "attempts": attempts,
        "total_tokens": total_tokens,
        "unknown_cost_calls": unknown_cost_calls,
        "known_cost_amount": 0.0,
        "known_cost_amount_is_not_zero_cost": True,
        "all_items_accepted_candidates": True,
        "all_relation_tasks_accepted_candidates": True,
        "published": False,
    }
    save(ROOT / "aggregate.json", aggregate)
    save(ROOT / "audit.json", audit)
    print(json.dumps(audit, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
