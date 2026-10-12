"""Issue-34 §7-10: rebuild the gate-33 Stage-1 adjudication workbench (superset, zero call).

Gate 33's workbench candidates omitted `speaker_ref` (layer A, 222/222 affected) and carried
no layer-B fields, so Stage 2 adjudication could not read those axes. This script produces
`workbench-v2.json` as a **strict superset** of v1: the candidate set, every pre-existing
field, and the Stage-1 suggestions are reproduced byte-for-byte; only the missing fields and
the contract view are added.

Nothing here modifies gold, the contract, the scorer or any gate-33 artifact.

Usage:
    uv run python .scratch/claims-r2-role-isolation/evidence/38-gate33-workbench-rebuild-20261012/r0-zero-call/rebuild_workbench.py
    ... --no-write
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
E38 = HERE.parent
CLAIMS = E38.parent.parent
REPO_ROOT = HERE.parents[4]
E36_R0 = CLAIMS / "evidence" / "36-l9-redo-and-baseline-20261011" / "r0-zero-call"
for path in (str(REPO_ROOT), str(E36_R0)):
    if path not in sys.path:
        sys.path.insert(0, path)

from l9_redo import digest, norm, read_json  # noqa: E402
from plugins.corpus.material_semantics import MaterialRun  # noqa: E402
from plugins.corpus.structured.ledger import BatchPlan  # noqa: E402
from plugins.corpus.structured.store import _material_records  # noqa: E402

E33_R0 = CLAIMS / "evidence" / "33-items-quality-scoring-20261011" / "r0-zero-call"
E32 = CLAIMS / "evidence" / "32-items-v6-reasoning-refreeze-20261011"
E10 = CLAIMS / "evidence"
WB_V1 = E33_R0 / "workbench.json"
GOLD = E10 / "10-quality-gold-freeze-20261008-r2" / "frozen-gold.json"
CONTRACT = E10 / "10-quality-gold-expansion-20261008-r2" / "scoring-contract.json"
PREREG = HERE / "preregistered-workbench-rebuild.json"
SOURCES = ("industrial-fulian-md", "optical-module-docx")

# v1 candidate fields that must be reproduced unchanged (AC-2).
V1_FIELDS = (
    "candidate_id",
    "role",
    "source_id",
    "origin",
    "source_slug",
    "candidate_slot_id",
    "text",
    "semantic_type",
    "statement_role",
    "speech_role",
    "perspective",
    "polarity",
    "value",
    "behavior_status",
    "temporal_frame",
    "unknown_fields",
    "evidence_quote",
    "evidence_locator",
)

# `requires` labels are taken from the measurements in evidence/37 (EC-A2/EC-A3/EC-A4).
CONTRACT_VIEW_REQUIREMENTS = {
    "proposition": ("item.text", "normalization"),
    "semantic_type": ("item.semantic_type", "caliber_clause"),
    "statement_role": ("item.statement_role", "caliber_clause"),
    "speech_role": ("item.speech_role", "caliber_clause"),
    "perspective": ("item.perspective", "caliber_clause"),
    "speaker_ref": ("item.speaker_ref", "id_mapping_or_exclusion"),
    "polarity": ("item.polarity", "none"),
    "attribution": ("layer_b.attribution", "caliber_clause"),
    "source_stance": ("none", "source_read"),
    "condition": ("item.text (statement_role==condition) | layer_b.condition", "caliber_clause"),
}
FIELD_PROVENANCE = {
    "speaker_ref": {"layer": "A", "source": "understanding.items[].speaker_ref"},
    "attribution": {"layer": "B", "source": "structured/store.py::_material_records"},
    "condition": {"layer": "B", "source": "structured/store.py::_material_records"},
    "factuality": {"layer": "B", "source": "structured/store.py::_material_records"},
}


def load_layer_a() -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """item_id -> layer A item, plus per-slug store object paths."""
    items: dict[str, dict[str, Any]] = {}
    objects: dict[str, Any] = {}
    for slug in SOURCES:
        payloads = [
            path
            for path in sorted(
                glob.glob(str(E32 / "live" / "treatment-store" / slug / "objects" / "sha256" / "*" / "*.json"))
            )
        ]
        for path in payloads:
            blob = json.loads(Path(path).read_text(encoding="utf-8"))
            if not blob.get("understanding"):
                continue
            objects[slug] = {
                "path": path,
                "sha256": "sha256:" + Path(path).name.removesuffix(".json"),
                "extractor_version": blob.get("extractor_version"),
            }
            for item in blob["understanding"]["items"]:
                items[item["item_id"]] = item
            break
    return items, objects


def load_layer_b() -> dict[str, Any]:
    """item_id -> layer B record (attribution/condition/factuality/polarity/value)."""
    records: dict[str, Any] = {}
    for slug in SOURCES:
        object_path = None
        for path in sorted(
            glob.glob(str(E32 / "live" / "treatment-store" / slug / "objects" / "sha256" / "*" / "*.json"))
        ):
            candidate = json.loads(Path(path).read_text(encoding="utf-8"))
            if candidate.get("understanding"):
                object_path = path
                payload = candidate
                break
        if object_path is None:
            continue
        run = MaterialRun.model_validate(payload)
        plan = BatchPlan.model_validate_json(
            (E32 / "r0-zero-call" / f"plan-treatment-{slug}.json").read_text(encoding="utf-8")
        )
        layer_b, _ = _material_records(run, plan.snapshot)
        for item_id, record in layer_b.items():
            records[item_id] = {
                "attribution": record.attribution,
                "condition": record.condition,
                "factuality": record.factuality,
                "polarity": record.polarity,
                "value": record.value,
            }
    return records


def load_slot_ledger() -> dict[str, str]:
    """item_id -> candidate_slot_id via the store's own coverage.slot_ledger (authoritative)."""
    ledger: dict[str, str] = {}
    for slug in SOURCES:
        for path in sorted(
            glob.glob(str(E32 / "live" / "treatment-store" / slug / "objects" / "sha256" / "*" / "*.json"))
        ):
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
            if not payload.get("understanding"):
                continue
            for entry in payload["understanding"]["coverage"]["slot_ledger"]:
                for ref in entry.get("item_refs") or []:
                    ledger[ref] = entry.get("candidate_slot_id")
            break
    return ledger


def slot_by_span(item: dict[str, Any], slots: list[dict[str, Any]]) -> str | None:
    evidence = (item.get("evidence") or [{}])[0]
    for slot in slots:
        if (
            slot.get("packet_id") == evidence.get("packet_id")
            and evidence.get("start") is not None
            and slot.get("start") <= evidence["start"]
            and evidence["end"] <= slot.get("end")
        ):
            return slot["candidate_slot_id"]
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()

    prereg = read_json(PREREG)
    v1 = read_json(WB_V1)
    contract = read_json(CONTRACT)
    gold_payload = read_json(GOLD)
    required = list(contract["role_required_fields"]["material_items"])

    layer_a, store_objects = load_layer_a()
    layer_b = load_layer_b()
    ledger_slots = load_slot_ledger()

    # slot cross-check for AC-1
    slots_by_slug: dict[str, list[dict[str, Any]]] = {}
    for slug in SOURCES:
        for path in sorted(
            glob.glob(str(E32 / "live" / "treatment-store" / slug / "objects" / "sha256" / "*" / "*.json"))
        ):
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
            if payload.get("understanding"):
                slots_by_slug[slug] = payload["candidate_slots"]
                break

    mismatches: list[dict[str, Any]] = []
    slot_disagreements: list[dict[str, Any]] = []
    candidates_v2: list[dict[str, Any]] = []
    added_counts: Counter = Counter()
    slot_field_counter: Counter = Counter()

    for candidate in v1["candidates"]:
        item_id = candidate["candidate_id"]
        item = layer_a.get(item_id)
        record = layer_b.get(item_id, {})
        if item is None:
            mismatches.append({"candidate_id": item_id, "issue": "missing_in_layer_a"})
            continue
        for field in V1_FIELDS:
            if field in ("candidate_id", "source_slug", "role", "origin", "source_id"):
                continue
            if field == "candidate_slot_id":
                continue  # cross-checked separately below (v1 slot vs span vs slot_ledger)
            expected = candidate.get(field)
            actual = (
                (item.get("evidence") or [{}])[0].get("quote")
                if field == "evidence_quote"
                else (item.get("evidence") or [{}])[0].get("locator")
                if field == "evidence_locator"
                else item.get(field)
            )
            if field == "source_id":
                continue
            if expected != actual:
                mismatches.append(
                    {"candidate_id": item_id, "field": field, "v1": expected, "store": actual}
                )
        span_slot = slot_by_span(item, slots_by_slug.get(candidate["source_slug"], []))
        ledger_slot = ledger_slots.get(item_id)
        if span_slot != candidate["candidate_slot_id"] or ledger_slot != candidate[
            "candidate_slot_id"
        ]:
            slot_disagreements.append(
                {
                    "candidate_id": item_id,
                    "v1_slot": candidate["candidate_slot_id"],
                    "span_slot": span_slot,
                    "slot_ledger_slot": ledger_slot,
                }
            )
        contract_view: dict[str, Any] = {}
        for field in required + ["condition"]:
            carrier, requires = CONTRACT_VIEW_REQUIREMENTS[field]
            if field == "proposition":
                value = item.get("text")
            elif field == "condition":
                value = (
                    norm(item.get("text") or "")
                    if item.get("statement_role") == "condition"
                    else None
                )
            elif field == "source_stance":
                value = None
            elif field == "attribution":
                value = record.get("attribution")
            elif field == "speaker_ref":
                value = item.get("speaker_ref")
            else:
                value = item.get(field)
            contract_view[field] = {"value": value, "carrier": carrier, "requires": requires}
            if value not in (None, "", []):
                slot_field_counter[field] += 1
        enriched = dict(candidate)
        enriched.update(
            {
                "speaker_ref": item.get("speaker_ref"),
                "attribution": record.get("attribution"),
                "condition": record.get("condition"),
                "factuality": record.get("factuality"),
                "contract_view": contract_view,
                "field_provenance": FIELD_PROVENANCE,
            }
        )
        for field in ("speaker_ref", "attribution", "condition", "factuality"):
            if enriched.get(field) not in (None, ""):
                added_counts[field] += 1
        candidates_v2.append(enriched)

    v1_ids = [item["candidate_id"] for item in v1["candidates"]]
    v2_ids = [item["candidate_id"] for item in candidates_v2]
    superset_check = {
        "candidate_ids_identical_and_ordered": v1_ids == v2_ids,
        "candidate_count_v1": len(v1_ids),
        "candidate_count_v2": len(v2_ids),
        "v1_field_mismatches": mismatches,
        "slot_assignment_cross_check_disagreements": slot_disagreements,
        "added_field_coverage": dict(added_counts),
        "contract_view_coverage": {
            field: slot_field_counter.get(field, 0) for field in required + ["condition"]
        },
    }
    result = {
        "schema_version": "items-quality-workbench-2",
        "created_on": "2026-10-12",
        "gate": "33-items-quality-scoring-gate",
        "supersedes": {
            "schema_version": v1["schema_version"],
            "sha256": digest(WB_V1),
            "note": "v2 是 v1 的严格超集：候选集合、既有字段值与 Stage-1 建议逐条不变，仅补齐 layer A/B 字段与契约视图。",
        },
        "candidates_total": len(candidates_v2),
        "candidates_by_source": Counter(item["source_slug"] for item in candidates_v2),
        "gold_total": v1["gold_total"],
        "gold_by_source": v1["gold_by_source"],
        "suggestion_confidence": v1["suggestion_confidence"],
        "unproduced_slots": v1["unproduced_slots"],
        "unproduced_collateral_items": v1["unproduced_collateral_items"],
        "inputs": {
            **v1["inputs"],
            "workbench_v1": digest(WB_V1),
            "store_objects": {slug: store_objects[slug]["sha256"] for slug in store_objects},
            "store_module": digest(REPO_ROOT / "plugins/corpus/structured/store.py"),
            "material_semantics_module": digest(REPO_ROOT / "plugins/corpus/material_semantics.py"),
        },
        "field_provenance": FIELD_PROVENANCE,
        "contract_view_requirements": {
            field: {"carrier": carrier, "requires": requires}
            for field, (carrier, requires) in CONTRACT_VIEW_REQUIREMENTS.items()
        },
        "contract_view_note": (
            "carrier/requires 取自 evidence/37 的实测：perspective/speech_role/statement_role/semantic_type 存在口径差，"
            "speaker_ref 存在 ID 空间差，source_stance 无载体须读原文，polarity 无需条款。"
        ),
        "superset_check": superset_check,
        "candidates": candidates_v2,
        "suggestions": v1["suggestions"],
        "advisory_note": v1["advisory_note"],
        "model_requests": 0,
        "production_database_access": 0,
    }
    result["candidates_by_source"] = dict(result["candidates_by_source"])
    serialized = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    roundtrip = json.loads(serialized)
    superset_check["suggestions_deep_equal_after_serialization"] = (
        roundtrip["suggestions"] == v1["suggestions"] and roundtrip["candidates"] == candidates_v2
    )
    serialized = json.dumps(result, ensure_ascii=False, indent=2) + "\n"

    print(
        json.dumps(
            {
                "candidates": len(candidates_v2),
                "superset_ok": superset_check["candidate_ids_identical_and_ordered"]
                and not mismatches
                and not slot_disagreements,
                "v1_field_mismatches": len(mismatches),
                "slot_disagreements": len(slot_disagreements),
                "added_field_coverage": dict(added_counts),
                "contract_view_coverage": superset_check["contract_view_coverage"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if args.no_write:
        return

    (HERE / "workbench-v2.json").write_text(serialized, encoding="utf-8")
    (HERE / "workbench-v2.md").write_text(render_md(result, required), encoding="utf-8")
    manifest = {
        "schema_version": "items-workbench-rebuild-manifest-1",
        "created_on": "2026-10-12",
        "inputs": {
            str(PREREG.relative_to(REPO_ROOT)): digest(PREREG),
            str(WB_V1.relative_to(REPO_ROOT)): digest(WB_V1),
            str(GOLD.relative_to(REPO_ROOT)): digest(GOLD),
            str(CONTRACT.relative_to(REPO_ROOT)): digest(CONTRACT),
            "plugins/corpus/structured/store.py": digest(
                REPO_ROOT / "plugins/corpus/structured/store.py"
            ),
            **{f"store_object::{slug}": store_objects[slug]["sha256"] for slug in store_objects},
        },
        "outputs": {
            name: digest(HERE / name)
            for name in (
                "preregistered-workbench-rebuild.json",
                "workbench-v2.json",
                "workbench-v2.md",
                "rebuild_workbench.py",
            )
        },
    }
    (HERE / "MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def render_md(result: dict[str, Any], required: list[str]) -> str:
    check = result["superset_check"]
    lines = [
        "# 门 33 Stage 1 工作台 v2（超集增强）",
        "",
        f"- 取代：`workbench.json` `{result['supersedes']['sha256']}`（{result['supersedes']['note']}）",
        f"- 候选：{result['candidates_total']} 条 ；金标：{result['gold_total']} 条",
        "",
        "## 超集自检（AC-1/AC-2/AC-3）",
        "",
        f"- candidate_id 集合与顺序一致：**{check['candidate_ids_identical_and_ordered']}**",
        f"- v1 既有字段逐条不一致数：**{len(check['v1_field_mismatches'])}**",
        f"- 槽位分配交叉校验分歧数：**{len(check['slot_assignment_cross_check_disagreements'])}**",
        "- Stage-1 建议与候选序列化后仍逐条等于 v1："
        f"**{check['suggestions_deep_equal_after_serialization']}**",
        "",
        "## 新增字段覆盖（AC-4/AC-8）",
        "",
        "| 字段 | 有值候选数 / 222 |",
        "|---|---|",
    ]
    for field, count in check["added_field_coverage"].items():
        lines.append(f"| `{field}` | {count} |")
    lines += ["", "## 契约视图覆盖（Stage 2 可执行性）", "", "| 契约字段 | 有值候选数 / 222 |", "|---|---|"]
    for field, count in check["contract_view_coverage"].items():
        lines.append(f"| `{field}` | {count} |")
    lines += [
        "",
        "## 契约视图承运与前置条款",
        "",
        "| 契约字段 | 载体 | 前置条款 |",
        "|---|---|---|",
    ]
    for field, blob in result["contract_view_requirements"].items():
        lines.append(f"| `{field}` | `{blob['carrier']}` | {blob['requires']} |")
    lines += [
        "",
        f"> {result['contract_view_note']}",
        "",
        "## 说明",
        "",
        "- 逐条裁定清单仍沿用门 33 的 `workbench.md`（按金标组织，未受本次缺陷影响）。",
        "- 本文件只补候选侧字段与契约视图，**不改变** Stage-1 建议，也不产出任何评分输入。",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
