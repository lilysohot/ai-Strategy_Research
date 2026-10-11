"""Zero-call attribution of the residual unproduced slots in the issue-32 gate.

Read-only. For every slot the treatment arm did not resolve, it collects the frozen slot
text, the controller's reason codes, the attempt-level transport evidence and — when the
model response object is on disk — the model's own line for that slot. Each residual is
then assigned to a root-cause layer: infrastructure / model behaviour / our contract.

Writes residual-attribution.json. No model call, no store mutation.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
E32 = HERE.parent
R0 = E32 / "r0-zero-call"
E28_R0 = E32.parent / "28-items-only-quality-gate-20261010" / "r0-zero-call"
ORDER = ("industrial-fulian-md", "optical-module-docx")
CLEAN_SLOT_STATUSES = {"extracted", "no_supported_item"}
STRUCTURAL_NO_ITEM_REASONS = {
    "affirmation_fragment",
    "intro_fragment",
    "metadata_only",
    "no_proposition",
    "structural_fragment",
    "title_only",
}
HARD_SIGNALS = {"question", "forecast", "condition", "risk", "negation", "behavior", "evidence"}
CATEGORIES = (
    "infrastructure",
    "model_behavior",
    "our_contract_signal_overlabelling",
    "unclassified",
)

# User adjudication (2026-10-11): reading both docx fragments, the reviewer judged our own
# signal labels too strong, not the model wrong. Recorded verbatim so the automated layer
# verdict stays visible next to the human one.
USER_ADJUDICATIONS: dict[str, dict[str, Any]] = {
    "slot_c1712c2b5d649478": {
        "category": "our_contract_signal_overlabelling",
        "reason": (
            "reviewer: '预测说不上，确实更像是评论' — the forecast signal on this fragment is "
            "too strong; the model's commentary_only terminal is the better read"
        ),
        "adjudicated_by": "xyl",
        "adjudicated_on": "2026-10-11",
    },
    "slot_1cf7098f1c258900": {
        "category": "our_contract_signal_overlabelling",
        "reason": (
            "reviewer: '更偏向是事实…更多是说明当前的情况' — the evidence signal is too strong; "
            "the model's fact/claim reading fits the text better"
        ),
        "adjudicated_by": "xyl",
        "adjudicated_on": "2026-10-11",
        "collateral_item_loss": 2,
        "collateral_note": (
            "the ledger kept item_refs for this slot while the payload items list dropped them, "
            "so two model-produced items were discarded together with the slot"
        ),
    },
}

from plugins.corpus.evidence_pipeline import evidence_document_from_snapshot  # noqa: E402
from plugins.corpus.material_semantics import (  # noqa: E402
    build_candidate_slot_batches,
    build_candidate_slots,
    build_material_structure,
)
from plugins.corpus.structured.ledger import BatchPlan, check_batch  # noqa: E402


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def load_responses(store: Path) -> dict[str, list[dict[str, Any]]]:
    """Index the stored raw responses by their diagnostics.attempt_id.

    The store keeps each raw response as an object whose file name is *not* the
    ``response_sha256`` column, so the attempt_id in its diagnostics is the only stable
    join key between the ledger and the model's own output.
    """
    index: dict[str, list[dict[str, Any]]] = {}
    root = store / "objects" / "sha256"
    if not root.exists():
        return index
    for path in root.rglob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict) or "content" not in payload:
            continue
        attempt_id = (payload.get("diagnostics") or {}).get("attempt_id")
        if not isinstance(attempt_id, str):
            continue
        rows: list[dict[str, Any]] = []
        for line in str(payload["content"]).splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                rows.append({"_unparsable": line[:120]})
                continue
            rows.append(value if isinstance(value, dict) else {"_nonobject": value})
        index[attempt_id] = rows
    return index


def row_digest(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(row, dict):
        return None
    items = row.get("items")
    return {
        "status": row.get("status"),
        "reason_code": row.get("reason_code"),
        "item_roles": [item.get("statement_role") for item in items if isinstance(item, dict)]
        if isinstance(items, list)
        else None,
        "item_semantic_types": [item.get("semantic_type") for item in items if isinstance(item, dict)]
        if isinstance(items, list)
        else None,
    }


def classify(reason_codes: list[str], *, model_row: dict[str, Any] | None) -> dict[str, Any]:
    codes = set(reason_codes)
    if any(code.startswith("items_error:LlmCallError") for code in codes):
        return {
            "category": "infrastructure",
            "basis": (
                "the whole batch aborted with LlmCallError (transport outcome unknown, "
                "zero automatic retry); no model verdict exists for these slots"
            ),
        }
    if "controller_semantic_validation_failed" in codes:
        rejected = sorted(code for code in codes if code.startswith("detected_signal_rejected:"))
        missing = sorted(code for code in codes if code.startswith("missing_signal:"))
        hard_axes = sorted(
            {
                code.split(":", 1)[1]
                for code in rejected + missing
                if code.split(":", 1)[1] in HARD_SIGNALS
            }
        )
        summary: dict[str, Any] = {"model_row_for_slot": model_row}
        digest_value = row_digest(model_row)
        if digest_value is not None:
            summary.update(digest_value)
        return {
            "category": "model_behavior",
            "basis": (
                "the model returned an explicit terminal for the slot while the controller "
                "held a hard signal on it; the slot text and its signal_types were both in "
                "the prompt, so 'visible and already flagged' holds"
            ),
            "controller_signals_rejected": rejected,
            "controller_signals_missing": missing,
            "hard_signal_axes": hard_axes,
            "model_terminal_seen": summary,
        }
    return {
        "category": "unclassified",
        "basis": "no rule matched; needs manual review",
        "model_terminal_seen": {"model_row_for_slot": model_row},
    }


def main() -> None:
    baseline = {
        entry["slug"]: entry
        for entry in read_json(E28_R0 / "freeze-manifest.json")["sources"]
    }
    report = read_json(HERE / "post-run-check.json")
    residual: dict[str, Any] = {
        "schema_version": "items-v6-residual-attribution-1",
        "created_on": "2026-10-11",
        "gate_sha256": digest(R0 / "preregistered-gate.json"),
        "post_run_check_sha256": digest(HERE / "post-run-check.json"),
        "sources": {},
        "model_requests_during_attribution": 0,
        "store_mutations": 0,
    }

    for slug in ORDER:
        plan = BatchPlan.model_validate_json(
            (R0 / f"plan-treatment-{slug}.json").read_text(encoding="utf-8")
        )
        plan.verify_identity()
        store = HERE / "treatment-store" / slug
        batch = check_batch(plan.batch_id, store_root=str(store.resolve()))
        ledger = batch.ledger

        document = evidence_document_from_snapshot(plan.snapshot, role="material_items")
        slots = build_candidate_slots(document, build_material_structure(document))
        slot_by_id = {slot.candidate_slot_id: slot for slot in slots}
        packets = {packet.packet_id: packet for packet in document.packets}
        batches = build_candidate_slot_batches(
            slots,
            max_slots_per_batch=24,
            max_items_per_batch=64,
            max_estimated_tokens_per_batch=8192,
        )
        batch_of_slot: dict[str, int] = {}
        index_in_batch: dict[str, int] = {}
        for index, group in enumerate(batches):
            for position, slot in enumerate(group):
                batch_of_slot[slot.candidate_slot_id] = index
                index_in_batch[slot.candidate_slot_id] = position

        payload_sha = None
        payload = None
        items_task = next((task for task in ledger.tasks if task.role == "material_items"), None)
        if items_task is not None:
            import sqlite3

            connection = sqlite3.connect(
                f"file:{store / 'index' / 'structured.sqlite3'}?mode=ro", uri=True
            )
            try:
                row = connection.execute(
                    "SELECT payload_object_sha256 FROM tasks WHERE batch_id=? AND task_id=?",
                    (ledger.batch_id, items_task.task_id),
                ).fetchone()
                payload_sha = row[0] if row else None
            finally:
                connection.close()
            if payload_sha:
                hexd = str(payload_sha).removeprefix("sha256:")
                payload = json.loads(
                    (store / "objects" / "sha256" / hexd[:2] / f"{hexd}.json").read_text(
                        encoding="utf-8"
                    )
                )

        slot_ledger = (payload or {}).get("understanding", {}).get("coverage", {}).get(
            "slot_ledger", []
        )
        failed = [
            row for row in slot_ledger if row.get("status") not in CLEAN_SLOT_STATUSES
        ]
        attempts = {item.attempt_number: item for item in ledger.attempts}
        responses = load_responses(store)
        rows_by_attempt: dict[int, list[dict[str, Any]] | None] = {
            number: responses.get(item.attempt_id) for number, item in attempts.items()
        }

        entries: list[dict[str, Any]] = []
        for row in failed:
            slot_id = str(row.get("candidate_slot_id"))
            slot = slot_by_id.get(slot_id)
            reason_codes = list(row.get("reason_codes") or [])
            signal_types = list(slot.signal_types) if slot is not None else []
            batch_index = batch_of_slot.get(slot_id)
            attempt_number = None if batch_index is None else batch_index + 1
            model_rows = rows_by_attempt.get(attempt_number) if attempt_number else None
            position = index_in_batch.get(slot_id)
            row_for_slot: dict[str, Any] | None = None
            if model_rows is not None and position is not None:
                for candidate in model_rows:
                    if (
                        isinstance(candidate, dict)
                        and candidate.get("obligation_index") == position
                    ):
                        row_for_slot = candidate
                        break
            hard_signals = sorted(set(signal_types) & HARD_SIGNALS)
            contrast: list[dict[str, Any]] = []
            if (
                position is not None
                and batch_index is not None
                and model_rows is not None
                and hard_signals
            ):
                for other_pos, other in enumerate(batches[batch_index]):
                    if other_pos == position:
                        continue
                    shared = sorted(set(other.signal_types) & set(hard_signals))
                    if not shared:
                        continue
                    other_row = None
                    for candidate in model_rows:
                        if (
                            isinstance(candidate, dict)
                            and candidate.get("obligation_index") == other_pos
                        ):
                            other_row = candidate
                            break
                    contrast.append(
                        {
                            "position": other_pos,
                            "candidate_slot_id": other.candidate_slot_id,
                            "signal_types": list(other.signal_types),
                            "shared_hard_signals": shared,
                            "model_row": row_digest(other_row),
                        }
                    )
            verdict = classify(reason_codes, model_row=row_for_slot)
            verdict["response_object_retained"] = model_rows is not None
            verdict["same_batch_contrast"] = contrast
            verdict["automated_category"] = verdict["category"]
            adjudication = USER_ADJUDICATIONS.get(slot_id)
            if adjudication is not None:
                verdict["category"] = adjudication["category"]
                verdict["basis"] = adjudication["reason"]
                verdict["adjudicated_by"] = adjudication["adjudicated_by"]
                verdict["adjudicated_on"] = adjudication["adjudicated_on"]
                if adjudication.get("collateral_item_loss"):
                    verdict["collateral_item_loss"] = adjudication["collateral_item_loss"]
                    verdict["collateral_note"] = adjudication["collateral_note"]
            entries.append(
                {
                    "candidate_slot_id": slot_id,
                    "status": row.get("status"),
                    "reason_codes": reason_codes,
                    "ledger_item_refs": list(row.get("item_refs") or []),
                    "payload_items_kept": sum(
                        1
                        for item in (payload or {})
                        .get("understanding", {})
                        .get("items", [])
                        if item.get("candidate_slot_id") == slot_id
                    ),
                    "packet_id": slot.packet_id if slot is not None else None,
                    "section": list(packets[slot.packet_id].context)[-2:]
                    if slot is not None and slot.packet_id in packets
                    else None,
                    "signal_types": signal_types,
                    "hard_signals": sorted(set(signal_types) & HARD_SIGNALS),
                    "slot_text": slot.text if slot is not None else None,
                    "batch_index": batch_index,
                    "attempt_number": attempt_number,
                    "attempt_status": (
                        attempts[attempt_number].execution_status
                        if attempt_number in attempts
                        else None
                    ),
                    "attempt_usage": (
                        attempts[attempt_number].usage if attempt_number in attempts else None
                    ),
                    "verdict": verdict,
                }
            )

        residual["sources"][slug] = {
            "batch_id": ledger.batch_id,
            "expected_attempts": plan.role_max_attempts["material_items"],
            "attempts": len(ledger.attempts),
            "attempt_status": {
                status: sum(1 for item in ledger.attempts if item.execution_status == status)
                for status in {item.execution_status for item in ledger.attempts}
            },
            "unproduced_slots": len(failed),
            "clean_slots": sum(
                1 for row in slot_ledger if row.get("status") in CLEAN_SLOT_STATUSES
            ),
            "total_slots": baseline[slug]["candidate_slot_count"],
            "residuals": entries,
            "category_counts": {
                category: sum(1 for entry in entries if entry["verdict"]["category"] == category)
                for category in CATEGORIES
            },
        }

    counts = {
        category: sum(
            source["category_counts"][category] for source in residual["sources"].values()
        )
        for category in CATEGORIES
    }
    collateral = sum(
        entry["verdict"].get("collateral_item_loss", 0)
        for source in residual["sources"].values()
        for entry in source["residuals"]
    )
    residual["totals"] = counts
    residual["conclusion"] = {
        "contract_defects_found": counts["our_contract_signal_overlabelling"],
        "summary": (
            f"{counts['infrastructure']} slot(s) lost to one transport outcome-unknown event "
            "(no model verdict exists); "
            f"{counts['our_contract_signal_overlabelling']} slot(s) adjudicated by the reviewer "
            "as our own over-strong signal labelling, not model behaviour; "
            f"{counts['model_behavior']} slot(s) left attributed to the model"
        ),
        "collateral_item_loss": collateral,
        "automated_vs_adjudicated": (
            "the automated layer had classed both docx slots as model behaviour; the reviewer "
            "read the fragments and reassigned them to our signal rule. Both verdicts are kept "
            "in every residual as automated_category and category"
        ),
        "gate_32_unmet_nature": {
            "protocol_status_valid": "not reached because the items task never succeeded",
            "failed_partial_batches": "1 partial packet per source",
            "execution_status_succeeded": (
                "1 outcome-unknown attempt (md) + 2 slots rejected by our own signal rule (docx)"
            ),
        },
        "quality_gate_input": (
            "score the produced items with the 9 unproduced slots disclosed as coverage gaps: "
            "7 are an infrastructure loss, 2 are our own signal-rule loss (one of them took "
            "2 model-produced items down with it)"
        ),
        "nuance": {
            "slot_c1712c2b5d649478": (
                "reviewer: the fragment reads as commentary, not a forecast; the model's "
                "commentary_only terminal was the better judgement, our forecast signal was "
                "too strong"
            ),
            "slot_1cf7098f1c258900": (
                "reviewer: the fragment states the current situation rather than serving as "
                "evidence; the model's fact/claim reading fits, our evidence signal was too "
                "strong, and two already-produced items were discarded with the slot"
            ),
        },
        "evidence_indexing": (
            "raw responses are stored under objects/sha256 as {content, diagnostics} objects "
            "keyed by diagnostics.attempt_id, not by the response_sha256 ledger column"
        ),
        "boundary": (
            "no rule, prompt, threshold or gold was changed on the basis of this attribution; "
            "the signal-rule question is recorded for a separate decision"
        ),
    }
    (HERE / "residual-attribution.json").write_text(
        json.dumps(residual, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "totals": counts,
                "sources": {
                    slug: {
                        "attempt_status": source["attempt_status"],
                        "clean_slots": source["clean_slots"],
                        "total_slots": source["total_slots"],
                        "category_counts": source["category_counts"],
                        "residuals": [
                            {
                                "candidate_slot_id": entry["candidate_slot_id"],
                                "reason_codes": entry["reason_codes"],
                                "signal_types": entry["signal_types"],
                                "attempt_number": entry["attempt_number"],
                                "attempt_status": entry["attempt_status"],
                                "category": entry["verdict"]["category"],
                                "basis": entry["verdict"]["basis"],
                            }
                            for entry in source["residuals"]
                        ],
                    }
                    for slug, source in residual["sources"].items()
                },
                "conclusion": residual["conclusion"],
                "model_requests": 0,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
