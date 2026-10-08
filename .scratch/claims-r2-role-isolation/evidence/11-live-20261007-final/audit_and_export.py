"""Audit selected immutable material segments and export one reviewable JSON bundle."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from plugins.corpus.evidence_pipeline import evidence_document_from_snapshot
from plugins.corpus.material_semantics import MaterialRun
from plugins.corpus.structured.config import canonical_hash
from plugins.corpus.structured.snapshot import EvidenceSnapshot

ROOT = Path(__file__).resolve().parent
EVIDENCE_ROOT = ROOT.parent
EXPECTED_SEGMENTS = {
    "01_results",
    "02_channels",
    "03_quality_cashflow",
    "04_reform_actions",
    "05_reform_outlook",
    "06_recommendation_basis",
    "07_recommendation_conclusion",
    "08_risks",
}


def read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def read_object(segment: Path, digest: str) -> dict:
    key = digest.removeprefix("sha256:")
    path = segment / "store" / "objects" / "sha256" / key[:2] / f"{key}.json"
    value = read_json(path)
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
    selection = read_json(ROOT / "selection.json")
    assert selection["schema_version"] == "material-segment-selection-v1"
    selected = selection["segments"]
    assert {entry["segment"] for entry in selected} == EXPECTED_SEGMENTS
    assert len(selected) == len(EXPECTED_SEGMENTS)

    items = []
    relations = []
    segment_results = []
    semantic_types: Counter[str] = Counter()
    statement_roles: Counter[str] = Counter()
    relation_types: Counter[str] = Counter()
    material_versions: set[str] = set()
    runner_versions: set[str] = set()
    models: set[str] = set()
    profiles: set[str] = set()
    attempts = 0
    total_tokens = 0
    unknown_cost_calls = 0
    source_spans_checked = 0
    slot_count = 0
    terminal_slots = 0

    for selected_entry in selected:
        name = selected_entry["segment"]
        run_name = selected_entry["run"]
        run_root = EVIDENCE_ROOT / run_name
        segment = run_root / name
        manifest = read_json(run_root / "manifest.json")
        freeze = read_json(segment / "freeze.json")
        summary = read_json(segment / "summary.json")
        manifest_entry = next(entry for entry in manifest["segments"] if entry["name"] == name)
        assert manifest["source_scope"] == selection["source_scope"]
        assert manifest_entry["batch_id"] == freeze["batch_id"] == summary["batch_id"]
        assert freeze["automatic_retries"] == manifest["automatic_retries"] == 0
        assert manifest["concurrency"] == 1
        material_versions.add(freeze["material_semantics_sha256"])
        runner_versions.add(freeze["runner_sha256"])
        models.add(manifest["model"])
        profiles.add(manifest["profile_sha256"])

        item_task = summary["material_items"]
        assert (
            item_task["execution_status"],
            item_task["protocol_status"],
            item_task["quality_status"],
            item_task["publication_status"],
        ) == ("succeeded", "valid", "accepted", "candidate")
        assert summary["plan_consistent"] is True
        assert all(
            (
                task["execution_status"],
                task["protocol_status"],
                task["quality_status"],
                task["publication_status"],
            )
            == ("succeeded", "valid", "accepted", "candidate")
            for task in summary["material_relations"]
        )

        snapshot = EvidenceSnapshot.model_validate_json(
            (segment / "snapshot.json").read_text(encoding="utf-8")
        )
        assert snapshot.snapshot_id == freeze["snapshot_id"]
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
                    "source_run": run_name,
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
                relation_types[relation.type] += 1
                relations.append(
                    {
                        "segment": name,
                        "source_run": run_name,
                        "batch_id": summary["batch_id"],
                        "artifact_sha256": relation_task["artifact_sha256"],
                        **relation.model_dump(mode="json"),
                    }
                )
                segment_relations += 1

        attempts += len(summary["attempts"])
        total_tokens += sum(
            (attempt.get("usage") or {}).get("total_tokens") or 0
            for attempt in summary["attempts"]
        )
        unknown_cost_calls += sum(entry["unknown_calls"] for entry in summary["cost_summary"])
        segment_results.append(
            {
                "segment": name,
                "source_run": run_name,
                "batch_id": summary["batch_id"],
                "material_semantics_sha256": freeze["material_semantics_sha256"],
                "candidate_slots": len(item_run.candidate_slots),
                "terminal_slots": len(ledger),
                "items": len(item_run.understanding.items),
                "relations": segment_relations,
                "attempts": len(summary["attempts"]),
            }
        )

    target_coverage = {
        "fact": semantic_types["fact"] > 0,
        "forecast": semantic_types["forecast"] > 0,
        "opinion": semantic_types["opinion"] > 0,
        "argument": statement_roles["evidence"] > 0 and relation_types["supports"] > 0,
        "risk": statement_roles["risk"] > 0,
        "condition": statement_roles["condition"] > 0,
        "explicit_relation": sum(relation_types.values()) > 0,
    }
    assert all(target_coverage.values()), target_coverage
    assert slot_count == terminal_slots
    assert len(models) == len(profiles) == len(runner_versions) == 1

    aggregate = {
        "schema_version": "material-live-round-export-v2",
        "run": ROOT.name,
        "selection_sha256": canonical_hash(selection),
        "source_scope": selection["source_scope"],
        "model": next(iter(models)),
        "publication_status": "candidate_not_published",
        "selected_segments": segment_results,
        "items": items,
        "relations": relations,
    }
    audit = {
        "schema_version": "material-live-round-audit-v2",
        "run": ROOT.name,
        "selection_sha256": canonical_hash(selection),
        "segments": segment_results,
        "segment_count": len(segment_results),
        "candidate_slots": slot_count,
        "terminal_slots": terminal_slots,
        "items": len(items),
        "relations": len(relations),
        "semantic_types": dict(sorted(semantic_types.items())),
        "statement_roles": dict(sorted(statement_roles.items())),
        "relation_types": dict(sorted(relation_types.items())),
        "semantic_target_coverage": target_coverage,
        "source_spans_checked": source_spans_checked,
        "attempts": attempts,
        "total_tokens": total_tokens,
        "unknown_cost_calls": unknown_cost_calls,
        "known_cost_amount": 0.0,
        "known_cost_amount_is_not_zero_cost": True,
        "runner_sha256": next(iter(runner_versions)),
        "material_semantics_sha256_versions": sorted(material_versions),
        "all_items_accepted_candidates": True,
        "all_relation_tasks_accepted_candidates": True,
        "published": False,
    }
    save(ROOT / "aggregate.json", aggregate)
    save(ROOT / "audit.json", audit)
    print(json.dumps(audit, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
