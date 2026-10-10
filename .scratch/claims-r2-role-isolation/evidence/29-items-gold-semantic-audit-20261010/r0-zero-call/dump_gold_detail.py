#!/usr/bin/env python3
"""Zero-call, read-only detail dump of the audited items.

Prints (and writes condition-items-detail.json) the concrete sentences behind
the Issue 29 findings:

  - all 10 statement_role=condition items: proposition / condition /
    condition_logic / locator / quote
  - the pairing needed to see F1: which proposition is a label vs a full
    proposition, and where the atomic content actually lives
  - the F4 adjudication-note items (NT-I22 / NT-I25 / NT-I33 / NT-I34)

Read-only: never rewrites any frozen artifact. No network, no model, no DB.
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
AUDIT_DIR = os.path.dirname(HERE)
EVID = os.path.dirname(AUDIT_DIR)
GOLD = os.path.join(EVID, "10-quality-gold-freeze-20261008-r2", "frozen-gold.json")

CONDITION_IDS = ["NT-I09", "NT-I13", "NT-I15", "NT-I17", "NT-I19",
                 "NT-I29", "NT-I35", "NT-I39", "NT-I42", "NT-I43"]
NOTE_IDS = ["NT-I22", "NT-I25", "NT-I33", "NT-I34"]

# Human determination (not computed): is the label-only item's `condition`
# value a single atomic proposition, or a compound (needs decomposition)?
ATOMICITY = {
    "NT-I09": {
        "label_only": True,
        "atomic": False,
        "kind": "disjunction",
        "atoms": ["毛利率继续下降", "Rubin延期"],
        "rationale": "condition 由连词「或」连接两个独立条件，是二元析取而非单一原子命题。",
    },
    "NT-I15": {"label_only": True, "atomic": True, "kind": "comparison",
               "atoms": ["下季OCF/扣非净利润<0.5"],
               "rationale": "单一数值比较，含指标/周期/算子/阈值，自足可判断。"},
    "NT-I19": {"label_only": True, "atomic": True, "kind": "single",
               "atoms": ["出口管制影响GPU系统集成"],
               "rationale": "单一因果式命题，无并列连词。"},
    "NT-I29": {"label_only": True, "atomic": True, "kind": "single",
               "atoms": ["政策变化导致成本上升"],
               "rationale": "单一因果式命题，无并列连词。"},
    "NT-I35": {"label_only": True, "atomic": True, "kind": "single",
               "atoms": ["无差别相信所有公司的份额陈述"],
               "rationale": "单一假设式命题，无并列连词。"},
    "NT-I39": {"label_only": True, "atomic": True, "kind": "single",
               "atoms": ["海外产能税率增加"],
               "rationale": "单一命题，无并列连词。"},
}


def main() -> int:
    with open(GOLD, "r", encoding="utf-8") as f:
        gold = json.load(f)
    by_id = {r["record_id"]: r for r in gold["records"] if r.get("role") == "material_items"}

    def row(rid: str) -> dict:
        r = by_id[rid]
        sf = r.get("semantic_fields", {})
        d = {
            "record_id": rid,
            "statement_role": sf.get("statement_role"),
            "semantic_type": sf.get("semantic_type"),
            "proposition": sf.get("proposition"),
            "condition": sf.get("condition"),
            "condition_logic": r.get("condition_logic"),
            "critical": r.get("critical"),
            "risk_or_condition": r.get("risk_or_condition"),
            "locator": r.get("locator"),
            "quote": r.get("quote"),
        }
        if rid in ATOMICITY:
            d["atomicity_determination"] = ATOMICITY[rid]
        return d

    out = {
        "schema_version": "items-gold-audit-detail-2",
        "scope": "read_only_zero_call",
        "model_calls": 0,
        "atomicity_summary": {
            "label_only_items": 6,
            "condition_is_single_atomic_proposition": 5,
            "condition_is_compound_not_atomic": 1,
            "compound_items": ["NT-I09"],
        },
        "condition_role_items": [row(rid) for rid in CONDITION_IDS],
        "adjudication_note_items": [row(rid) for rid in NOTE_IDS],
    }
    with open(os.path.join(HERE, "condition-items-detail.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print("=== statement_role=condition items (10) ===")
    for d in out["condition_role_items"]:
        has_logic = "condition_logic" if d["condition_logic"] else "-"
        det = d.get("atomicity_determination")
        if det is None:
            tag = "self-contained(proposition)"
        elif det["atomic"]:
            tag = "label-only / condition=原子命题"
        else:
            tag = "label-only / condition=非原子(%s)" % det["kind"]
        print("\n[%s] role=%s type=%s critical=%s logic=%s  <-- %s"
              % (d["record_id"], d["statement_role"], d["semantic_type"],
                 d["critical"], has_logic, tag))
        print("  proposition : %s" % d["proposition"])
        print("  condition   : %s" % d["condition"])
        if det is not None:
            print("  rationale   : %s" % det["rationale"])
        print("  quote       : %s" % d["quote"])

    print("\n=== adjudication-note items (F4) ===")
    for d in out["adjudication_note_items"]:
        print("\n[%s] role=%s type=%s" % (d["record_id"], d["statement_role"], d["semantic_type"]))
        print("  proposition : %s" % d["proposition"])
        print("  condition   : %s" % d["condition"])
        print("  quote       : %s" % d["quote"])
    print("\nwrote condition-items-detail.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
