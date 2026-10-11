"""Zero-call pre-flight: count the runtime-style per-packet model calls.

The frozen plans budget one model call per candidate-slot batch. The freeze
scripts counted batches across the whole document, but the runtime batches
*per packet*, so the real call count can only be proven by simulating the
runtime grouping. This script rebuilds both signed snapshots and counts
batches the way ``extract_material_understanding`` does. No model call, no
store write.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
FREEZE_DIR = HERE.parent / "r0-zero-call"
sys.path.insert(0, str(FREEZE_DIR))
import freeze_items_only_plan as frozen  # noqa: E402

from plugins.corpus.evidence_pipeline import (  # noqa: E402
    build_evidence_run_from_snapshot,
    evidence_document_from_snapshot,
)
from plugins.corpus.material_semantics import (  # noqa: E402
    build_candidate_slot_batches,
    build_candidate_slots,
    build_material_structure,
)

EXPECTED = {"industrial-fulian-md": 10, "optical-module-docx": 14}


def per_packet_calls(snapshot: object) -> dict[str, object]:
    """Count batches exactly like the runtime loop does."""

    # Runtime path: build_evidence_run_from_snapshot(...).document
    run = build_evidence_run_from_snapshot(snapshot, role="material_items")  # type: ignore[arg-type]
    document = run.document
    slots = build_candidate_slots(document, build_material_structure(document))
    by_packet: dict[str, list[object]] = {}
    for slot in slots:
        by_packet.setdefault(slot.packet_id, []).append(slot)

    total = 0
    packets_detail = []
    for packet in document.packets:
        if packet.kind == "table":
            packets_detail.append(
                {"packet_id": packet.packet_id, "kind": packet.kind, "slots": 0, "batches": 0}
            )
            continue
        packet_slots = tuple(by_packet.get(packet.packet_id, ()))
        if not packet_slots:
            packets_detail.append(
                {"packet_id": packet.packet_id, "kind": packet.kind, "slots": 0, "batches": 0}
            )
            continue
        batches = build_candidate_slot_batches(
            packet_slots,
            max_slots_per_batch=frozen.SELECTOR_MAX_SLOTS,
            max_items_per_batch=frozen.SELECTOR_MAX_ITEMS,
            max_estimated_tokens_per_batch=frozen.SELECTOR_MAX_TOKENS,
        )
        total += len(batches)
        packets_detail.append(
            {
                "packet_id": packet.packet_id,
                "kind": packet.kind,
                "slots": len(packet_slots),
                "batches": len(batches),
            }
        )

    # Cross-check with the freeze-time global count.
    freeze_document = evidence_document_from_snapshot(snapshot, role="material_items")  # type: ignore[arg-type]
    freeze_slots = build_candidate_slots(
        freeze_document, build_material_structure(freeze_document)
    )
    global_batches = build_candidate_slot_batches(
        freeze_slots,
        max_slots_per_batch=frozen.SELECTOR_MAX_SLOTS,
        max_items_per_batch=frozen.SELECTOR_MAX_ITEMS,
        max_estimated_tokens_per_batch=frozen.SELECTOR_MAX_TOKENS,
    )
    return {
        "packets": packets_detail,
        "packet_count": len(document.packets),
        "slot_count": len(slots),
        "runtime_calls": total,
        "freeze_global_batches": len(global_batches),
    }


def main() -> None:
    report: dict[str, object] = {
        "schema_version": "items-only-live-preflight-runtime-batches-1",
        "model_requests": 0,
        "sources": {},
    }
    ok = True
    for item in frozen.scoped_sources():
        slug = item["slug"]
        result = per_packet_calls(item["snapshot"])
        expected = EXPECTED[slug]
        result["expected_budget"] = expected
        result["match"] = result["runtime_calls"] == expected
        ok = ok and bool(result["match"])
        report["sources"][slug] = result  # type: ignore[index]
    report["all_match"] = ok
    (HERE / "preflight-runtime-batches.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    if not ok:
        raise SystemExit("runtime call budget mismatch; live run would defer batches")


if __name__ == "__main__":
    main()