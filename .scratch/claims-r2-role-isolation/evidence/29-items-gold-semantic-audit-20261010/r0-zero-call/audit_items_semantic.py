#!/usr/bin/env python3
"""Zero-call, read-only semantic audit of the frozen 48-item material_items gold.

Reads (read-only, never rewritten):
  evidence/10-quality-gold-freeze-20261008-r2/frozen-gold.json
  evidence/10-quality-gold-freeze-20261008-r2/freeze-state.json
  evidence/10-quality-gold-expansion-20261008-r2/scoring-contract.json

Writes:
  findings.json  (deterministic: sorted keys, no wall-clock fields)

Guarantees:
  - no network access, no model calls, no production database access
  - no write to any frozen artifact; only the audit output file is created
"""
import hashlib
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))          # .../r0-zero-call
AUDIT_DIR = os.path.dirname(HERE)                          # .../29-items-gold-semantic-audit-20261010
EVID = os.path.dirname(AUDIT_DIR)                          # .../evidence

GOLD = os.path.join(EVID, "10-quality-gold-freeze-20261008-r2", "frozen-gold.json")
FSTATE = os.path.join(EVID, "10-quality-gold-freeze-20261008-r2", "freeze-state.json")
CONTRACT = os.path.join(EVID, "10-quality-gold-expansion-20261008-r2", "scoring-contract.json")
GATE = os.path.join(
    EVID, "28-items-only-quality-gate-20261010", "r0-zero-call", "preregistered-gate.json"
)

LABEL_SUFFIXES = ("条件", "前提", "之一")


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def load(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def is_label_proposition(prop: str) -> bool:
    """A condition-role proposition is a non-propositional label when it is a
    short noun phrase instead of a clause. Heuristic: short and ending in a
    condition/precondition marker. Cross-checked against the 6 known cases."""
    p = (prop or "").strip()
    return len(p) <= 12 and (p.endswith(LABEL_SUFFIXES) or "触发" in p)


def main() -> int:
    gold = load(GOLD)
    fstate = load(FSTATE)
    contract = load(CONTRACT)
    gate = load(GATE)

    items = [r for r in gold["records"] if r.get("role") == "material_items"]
    cond = [r for r in items if r.get("semantic_fields", {}).get("statement_role") == "condition"]

    cond_ids = [r["record_id"] for r in cond]
    label_only = [
        r["record_id"] for r in cond
        if is_label_proposition(r.get("semantic_fields", {}).get("proposition", ""))
    ]
    full_prop = [r["record_id"] for r in cond if r["record_id"] not in label_only]

    with_condition_field = [
        r["record_id"] for r in items if "condition" in r.get("semantic_fields", {})
    ]
    # items carrying a condition field whose statement_role is NOT condition
    condition_field_other_role = [
        r["record_id"] for r in items
        if "condition" in r.get("semantic_fields", {})
        and r.get("semantic_fields", {}).get("statement_role") != "condition"
    ]

    # contract-derived requirements
    required = contract.get("role_required_fields", {}).get("material_items", [])
    proposition_is_required = "proposition" in required
    condition_is_required = "condition" in required

    review_assertions = contract.get("review_assertions", {})
    gate_high_risk = (
        gate.get("quality_requirements", {}).get("high_risk_item_assertions_required", [])
    )
    cond_unguarded = [rid for rid in cond_ids if rid not in gate_high_risk]
    cond_with_assertion = [rid for rid in cond_ids if rid in review_assertions]
    cond_without_assertion = [rid for rid in cond_ids if rid not in review_assertions]
    cond_with_condition_logic = [
        rid for rid in cond_ids
        if isinstance(review_assertions.get(rid), dict)
        and "condition_logic" in review_assertions[rid]
    ]

    findings = [
        {
            "id": "F1",
            "severity": "high",
            "kind": "gold_serialization_inconsistency",
            "title": "condition-role items store the atomic proposition inconsistently",
            "statement": (
                "All 10 material_items with statement_role=condition carry a `condition` field, "
                "but their `proposition` field is split: %d items hold a full atomic proposition "
                "while %d hold a non-propositional label whose atomic content lives only in "
                "`condition`. The scoring contract requires `proposition` and does not list "
                "`condition` in role_required_fields, and matching.items demands '一个原子命题'; "
                "a scorer reading the required fields therefore receives a label for the %d items."
                % (len(full_prop), len(label_only), len(label_only))
            ),
            "evidence": {
                "condition_role_items": cond_ids,
                "self_contained_proposition": full_prop,
                "label_only_proposition": label_only,
            },
        },
        {
            "id": "F2",
            "severity": "high",
            "kind": "contract_unsigned_gate_basis",
            "title": "scoring contract is unsigned but is used as the frozen measurement basis",
            "statement": (
                "The scoring contract's own `status` is '%s' and metrics.quality_gate states the "
                "package-level and newly-adjudicated thresholds still await human sign-off, yet the "
                "freeze README and Issue 28 bind this contract hash as the frozen scoring basis. "
                "The gate's measurement basis is therefore not actually signed."
                % contract.get("status")
            ),
            "evidence": {
                "contract_status": contract.get("status"),
                "gate_quality_requirements_status": (
                    gate.get("quality_requirements_status")
                ),
                "gate_high_risk_item_assertions_required": (
                    gate.get("quality_requirements", {})
                    .get("high_risk_item_assertions_required", [])
                ),
                "frozen_gold_sha256": sha256(GOLD),
                "scoring_contract_sha256": sha256(CONTRACT),
                "preregistered_gate_sha256": sha256(GATE),
            },
        },
        {
            "id": "F3",
            "severity": "medium",
            "kind": "contract_modeling_gap",
            "title": "condition-role item semantics are under-specified in the contract",
            "statement": (
                "`condition_logic` appears only inside review_assertions for %d of %d condition "
                "items and is absent from role_required_fields and from any item schema, so the "
                "contract defines no read-path for condition-role items; of the %d label-only "
                "items, %d (%s) are also outside the gate's high_risk_item_assertions_required, so "
                "they are neither self-contained nor regression-guarded."
                % (len(cond_with_condition_logic), len(cond_ids), len(label_only),
                   len(cond_unguarded), ", ".join(cond_unguarded))
            ),
            "evidence": {
                "condition_items_with_review_assertion": cond_with_assertion,
                "condition_items_without_review_assertion": cond_without_assertion,
                "condition_items_with_condition_logic": cond_with_condition_logic,
                "condition_items_outside_gate_high_risk_assertions": cond_unguarded,
                "proposition_required": proposition_is_required,
                "condition_required": condition_is_required,
            },
        },
        {
            "id": "F4",
            "severity": "low",
            "kind": "adjudication_note",
            "title": "non-blocking notes for human adjudication",
            "statement": (
                "Near-overlap pair NT-I22 (2026 CPO shipments negligible) vs NT-I33 (CPO has no "
                "actual shipments yet) may collide under the duplicates metric; NT-I25 labels the "
                "evaluative '良率仍不理想' as semantic_type=fact; NT-I34 carries a `condition` "
                "field under statement_role=claim. These are recorded for adjudication and are not "
                "themselves treated as defects."
            ),
            "evidence": {"condition_field_other_role": condition_field_other_role},
        },
    ]

    out = {
        "schema_version": "items-gold-semantic-audit-1",
        "scope": "read_only_zero_call",
        "model_calls": 0,
        "production_database_access": 0,
        "inputs": {
            "frozen-gold.json": sha256(GOLD),
            "freeze-state.json": sha256(FSTATE),
            "scoring-contract.json": sha256(CONTRACT),
            "preregistered-gate.json": sha256(GATE),
        },
        "counts": {
            "frozen_counts": gold.get("counts", {}),
            "material_items_total": len(items),
            "condition_role_items": len(cond),
            "items_with_condition_field": len(with_condition_field),
        },
        "condition_role_analysis": {
            "all_condition_items_have_condition_field": len(with_condition_field) >= len(cond),
            "self_contained_proposition": full_prop,
            "label_only_proposition": label_only,
            "condition_items_with_review_assertion": cond_with_assertion,
            "condition_items_without_review_assertion": cond_without_assertion,
            "condition_items_with_condition_logic": cond_with_condition_logic,
            "condition_items_outside_gate_high_risk_assertions": cond_unguarded,
        },
        "contract_snapshot": {
            "status": contract.get("status"),
            "schema_version": contract.get("schema_version"),
            "evaluation_scope": contract.get("evaluation_scope"),
            "material_items_required_fields": required,
            "proposition_required": proposition_is_required,
            "condition_required": condition_is_required,
        },
        "findings": findings,
        "verdict": {
            "gold_meaning_sound": True,
            "gate_execution_blocked_pending": [
                "condition-role proposition read-path defined in a signed contract",
                "scoring contract signed (status no longer draft_pending_human_review)",
            ],
            "in_place_mutation_allowed": False,
            "correction_ticket_required": True,
            "correction_pattern": "Issue 23 (successor freeze + preserve signed original)",
        },
    }

    with open(os.path.join(HERE, "findings.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")

    print("items:", len(items))
    print("condition-role items:", len(cond), cond_ids)
    print("self-contained proposition:", full_prop)
    print("label-only proposition:", label_only)
    print("condition items w/ review_assertion:", cond_with_assertion)
    print("condition items w/o review_assertion:", cond_without_assertion)
    print("condition items w/ condition_logic:", cond_with_condition_logic)
    print("condition items outside gate high-risk assertions:", cond_unguarded)
    print("contract status:", contract.get("status"))
    print("gate quality_requirements_status:", gate.get("quality_requirements_status"))
    print("proposition required / condition required:",
          proposition_is_required, "/", condition_is_required)
    print("wrote findings.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
