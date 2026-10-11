"""L9 redo (gold-blind, held-out) plus current-scorer control baseline for the items seam.

Zero call, read-only. Implements the preregistered arms A-D2 of
`r0-zero-call/preregistered-l9-redo.json` (which is write-once and must be written
before this script runs) and emits l9-redo.{json,md}, baseline-control.{json,md}
and MANIFEST.json.

Nothing here modifies gold, the contract, the scorer or any frozen artifact.

Usage:
    uv run python .scratch/claims-r2-role-isolation/evidence/36-l9-redo-and-baseline-20261011/r0-zero-call/l9_redo.py
    ... --no-write     # compute and print only, no files written
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
E36 = HERE.parent
CLAIMS = E36.parent.parent
REPO_ROOT = HERE.parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from plugins.corpus.evidence_pipeline import evidence_document_from_snapshot  # noqa: E402
from plugins.corpus.material_semantics import (  # noqa: E402
    build_candidate_slots,
    build_material_structure,
)
from plugins.corpus.structured.ledger import BatchPlan  # noqa: E402
from plugins.corpus.structured_scoring import (  # noqa: E402
    CandidateRecord,
    GoldRecord,
    RecordOrigin,
    Role,
    score_structured_quality,
)

E10 = CLAIMS / "evidence"
E32_R0 = CLAIMS / "evidence" / "32-items-v6-reasoning-refreeze-20261011" / "r0-zero-call"
E33_R0 = CLAIMS / "evidence" / "33-items-quality-scoring-20261011" / "r0-zero-call"

WORKBENCH = E33_R0 / "workbench.json"
DRAFT = E33_R0 / "adjudications.draft.json"
GOLD = E10 / "10-quality-gold-freeze-20261008-r2" / "frozen-gold.json"
CONTRACT = E10 / "10-quality-gold-expansion-20261008-r2" / "scoring-contract.json"
PREREG = HERE / "preregistered-l9-redo.json"

SOURCES = {
    "industrial-fulian-md": "md",
    "optical-module-docx": "docx",
}
DEVELOPMENT_SLUG = "optical-module-docx"
HELD_OUT_SLUG = "industrial-fulian-md"

# Contract `condition_role_read_path.required_fields_override`.
CONDITION_ROLE = "condition"
# Fields the candidate side has zero carriers for (measured, see prereg corrections).
NO_CARRIER_FIELDS = ("speaker_ref", "attribution", "source_stance")
NON_REQUIRED_TESTED = ("estimate_status",)
# arm D projection basis (symmetric, both sides)
ALIGNMENT_FIELDS = (
    "semantic_type",
    "statement_role",
    "speech_role",
    "perspective",
    "polarity",
)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def pairs(fields: dict[str, Any]) -> tuple[tuple[str, str], ...]:
    return tuple(
        sorted(
            (key, value)
            for key, value in (fields or {}).items()
            if isinstance(value, str) and value.strip()
        )
    )


def norm(value: str) -> str:
    """Preregistered projection for the proposition carrier: trim + drop trailing punctuation."""
    return value.strip().rstrip("。．.;；")


def nonempty(record: dict[str, Any], field: str) -> bool:
    value = record.get(field)
    return isinstance(value, str) and bool(value.strip())


def carrier_fields(candidate: dict[str, Any]) -> set[str]:
    """Contract fields this candidate can carry by itself (no gold involved)."""
    out: set[str] = set()
    if nonempty(candidate, "text"):
        out.add("proposition")
        if candidate.get("statement_role") == CONDITION_ROLE:
            out.add(CONDITION_ROLE)
    for field in ALIGNMENT_FIELDS + ("value", "behavior_status", "temporal_frame"):
        if nonempty(candidate, field):
            out.add(field)
    return out


def covering_slots(
    slug: str, gold_rows: list[dict[str, Any]], candidates: list[dict[str, Any]]
) -> dict[str, Any]:
    """Gold -> covering candidate slots, by span overlap only (no gold field is read)."""
    plan = BatchPlan.model_validate_json(
        (E32_R0 / f"plan-treatment-{slug}.json").read_text(encoding="utf-8")
    )
    document = evidence_document_from_snapshot(plan.snapshot, role="material_items")
    slots = build_candidate_slots(document, build_material_structure(document))
    unit_id_by_locator = {unit.locator: unit.unit_id for unit in plan.snapshot.units}
    unit_packet = {
        span.locator: packet.packet_id for packet in document.packets for span in packet.spans
    }
    span_base = {
        (packet.packet_id, span.locator): span.start
        for packet in document.packets
        for span in packet.spans
    }
    source_id = plan.snapshot.source_id
    source_id = source_id if source_id.startswith("sha256:") else f"sha256:{source_id}"
    per_gold: dict[str, Any] = {}
    for row in gold_rows:
        if row["source_id"] != source_id:
            continue
        windows: list[tuple[str, int, int]] = []
        for evidence in row.get("evidence") or []:
            locator = evidence.get("locator")
            start, end = evidence.get("start"), evidence.get("end")
            unit_id = unit_id_by_locator.get(locator)
            packet_id = unit_packet.get(unit_id) if unit_id else None
            base = span_base.get((packet_id, unit_id)) if packet_id and unit_id else None
            if packet_id is None or base is None or start is None or end is None:
                continue
            windows.append((packet_id, base + int(start), base + int(end)))
        covering = [
            slot
            for slot in slots
            if any(
                packet_id == slot.packet_id and low < slot.end and high > slot.start
                for packet_id, low, high in windows
            )
        ]
        slot_ids = [slot.candidate_slot_id for slot in covering]
        present = [c for c in candidates if c["candidate_slot_id"] in set(slot_ids)]
        per_gold[row["record_id"]] = {
            "covering_slot_count": len(slot_ids),
            "covering_slot_ids": sorted(slot_ids),
            "candidate_ids": [c["candidate_id"] for c in present],
            "carrier_fields": sorted(
                set().union(*(carrier_fields(c) for c in present)) if present else set()
            ),
        }
    return {
        "source_id": source_id,
        "slots": len(slots),
        "units": len(plan.snapshot.units),
        "packets": len(document.packets),
        "per_gold": per_gold,
    }


def gold_records(gold_items: list[dict[str, Any]]) -> tuple[GoldRecord, ...]:
    return tuple(
        GoldRecord(
            record_id=row["record_id"],
            role=Role.MATERIAL_ITEMS,
            source_id=row["source_id"],
            origin=RecordOrigin(row["origin"]),
            semantic_fields=pairs(row.get("semantic_fields")),
            critical=bool(row.get("critical")),
            risk_or_condition=bool(row.get("risk_or_condition")),
        )
        for row in gold_items
    )


def candidate_record(row: dict[str, Any], fields: dict[str, Any]) -> CandidateRecord:
    return CandidateRecord(
        candidate_id=row["candidate_id"],
        role=Role.MATERIAL_ITEMS,
        source_id=row["source_id"],
        origin=RecordOrigin(row.get("origin") or "llm_prose"),
        semantic_fields=pairs(fields),
    )


def score(gold: tuple[GoldRecord, ...], candidates: tuple[CandidateRecord, ...]) -> dict[str, Any]:
    if not candidates:
        return {"tp": 0, "fp": 0, "fn": len(gold), "matched": 0, "note": "empty candidate tuple"}
    report = score_structured_quality(
        gold, raw_candidates=candidates, validated_candidates=candidates
    )
    role = report.validated.role(Role.MATERIAL_ITEMS)
    return {
        "tp": role.tp,
        "fp": role.fp,
        "fn": role.fn,
        "duplicate_fp": role.duplicate_fp,
        "precision": None if role.precision is None else str(role.precision),
        "recall": None if role.recall is None else str(role.recall),
        "matched": len(report.validated.matched_gold_ids),
        "matched_gold_ids": list(report.validated.matched_gold_ids),
        "missing_gold_ids": list(report.validated.missing_gold_ids),
        "gate": {
            "rate_gate_passed": report.gate.rate_gate_passed,
            "live_trial_ready": report.gate.live_trial_ready,
            "risk_condition_recall": None
            if report.gate.risk_condition_recall is None
            else str(report.gate.risk_condition_recall),
            "rate_blockers": list(report.gate.rate_blockers),
            "readiness_blockers": list(report.gate.readiness_blockers),
        },
    }


def alignment_tp(
    gold: tuple[GoldRecord, ...], candidates: tuple[CandidateRecord, ...], *, containment: bool
) -> int:
    """Arm D/D2: symmetric projection to the shared field set, tp counted one-to-one."""
    remaining = {item.record_id: dict(item.semantic_fields) for item in gold}
    tp = 0
    for candidate in candidates:
        fields = dict(candidate.semantic_fields)
        hit: str | None = None
        for record_id, gold_fields in remaining.items():
            if {k: v for k, v in gold_fields.items() if k in ALIGNMENT_FIELDS} != {
                k: v for k, v in fields.items() if k in ALIGNMENT_FIELDS
            }:
                continue
            left, right = gold_fields.get("proposition", ""), fields.get("proposition", "")
            same = left in right or right in left if containment else left == right
            if same and left and right:
                hit = record_id
                break
        if hit is not None:
            tp += 1
            remaining.pop(hit)
    return tp


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-write", action="store_true", help="compute only, write nothing")
    args = parser.parse_args()

    prereg = read_json(PREREG)
    contract = read_json(CONTRACT)
    workbench = read_json(WORKBENCH)
    draft = read_json(DRAFT)
    gold_payload = read_json(GOLD)
    gold_items = [row for row in gold_payload["records"] if row["role"] == "material_items"]
    required = list(contract["role_required_fields"]["material_items"])
    candidates = workbench["candidates"]
    gold_by_id = {row["record_id"]: row for row in gold_items}

    # ---------------------------------------------------------------- carrier availability
    coverage = {
        slug: covering_slots(
            slug,
            gold_items,
            [c for c in candidates if c.get("source_slug") == slug],
        )
        for slug in SOURCES
    }
    tested = required + [CONDITION_ROLE] + list(NON_REQUIRED_TESTED)
    availability: dict[str, Any] = {}
    per_record: dict[str, Any] = {}
    for slug, blob in coverage.items():
        for record_id, info in blob["per_gold"].items():
            row = gold_by_id[record_id]
            is_condition = (row.get("semantic_fields") or {}).get("statement_role") == CONDITION_ROLE
            carried = set(info["carrier_fields"])
            applicability = [
                field
                for field in required
                if field != CONDITION_ROLE or is_condition
            ]
            if is_condition:
                applicability.append(CONDITION_ROLE)
            per_record[record_id] = {
                "source_slug": slug,
                "candidate_count": len(info["candidate_ids"]),
                "corpus_absent": not info["candidate_ids"],
                "covering_slot_count": info["covering_slot_count"],
                "carrier_fields": sorted(carried),
                "missing_fields": [
                    field for field in applicability if field not in carried
                ],
                "contract_shape_reachable_strict": bool(info["candidate_ids"])
                and all(field in carried for field in applicability),
                "contract_shape_reachable_carrier_only": bool(info["candidate_ids"])
                and all(
                    field in carried for field in applicability if field not in NO_CARRIER_FIELDS
                ),
            }
        for field in tested:
            denominator = len(blob["per_gold"])
            if field == CONDITION_ROLE:
                denominator = sum(
                    1
                    for record_id in blob["per_gold"]
                    if (gold_by_id[record_id].get("semantic_fields") or {}).get("statement_role")
                    == CONDITION_ROLE
                )
            hits = sum(
                1
                for record_id in blob["per_gold"]
                if field in coverage[slug]["per_gold"][record_id]["carrier_fields"]
            )
            availability[f"{slug}.{field}"] = {
                "hits": hits,
                "denominator": denominator,
                "rate": None if not denominator else round(hits / denominator, 4),
            }
    for field in tested:
        denominator = 48 if field != CONDITION_ROLE else sum(
            1
            for row in gold_items
            if (row.get("semantic_fields") or {}).get("statement_role") == CONDITION_ROLE
        )
        hits = sum(
            1
            for record_id, info in per_record.items()
            if field in info["carrier_fields"]
        )
        availability[f"overall.{field}"] = {
            "hits": hits,
            "denominator": denominator,
            "rate": None if not denominator else round(hits / denominator, 4),
        }

    # ---------------------------------------------------------------- arms
    native = tuple(
        candidate_record(
            c,
            {
                key: c[key]
                for key in (
                    "text",
                    "semantic_type",
                    "statement_role",
                    "speech_role",
                    "perspective",
                    "polarity",
                    "value",
                    "behavior_status",
                    "temporal_frame",
                )
            },
        )
        for c in candidates
    )
    injected_rows = [
        row for row in draft["candidates"] if row.get("judgement") == "accepted"
    ]
    gold_injected = tuple(
        candidate_record(
            row["original_candidate"],
            gold_by_id[row["matched_gold_id"]]["semantic_fields"],
        )
        for row in injected_rows
        if row.get("matched_gold_id") in gold_by_id
    )
    projection = tuple(
        candidate_record(
            c,
            {
                **{field: c[field] for field in ALIGNMENT_FIELDS if nonempty(c, field)},
                "proposition": norm(c.get("text") or ""),
                **(
                    {CONDITION_ROLE: norm(c.get("text") or "")}
                    if c.get("statement_role") == CONDITION_ROLE
                    else {}
                ),
            },
        )
        for c in candidates
    )
    gold_aligned = tuple(
        GoldRecord(
            record_id=row["record_id"],
            role=Role.MATERIAL_ITEMS,
            source_id=row["source_id"],
            origin=RecordOrigin(row["origin"]),
            semantic_fields=tuple(
                sorted(
                    [
                        ("proposition", prop)
                        for prop in [norm((row["semantic_fields"] or {}).get("proposition", ""))]
                        if prop
                    ]
                    + [
                        (field, row["semantic_fields"][field])
                        for field in ALIGNMENT_FIELDS
                        if (row["semantic_fields"] or {}).get(field)
                    ]
                )
            ),
        )
        for row in gold_items
    )
    projected_aligned = tuple(
        candidate_record(
            c,
            {
                **{field: c[field] for field in ALIGNMENT_FIELDS if nonempty(c, field)},
                "proposition": norm(c.get("text") or ""),
            },
        )
        for c in candidates
    )

    frozen_gold = gold_records(gold_items)
    arms = {
        "A_native": score(frozen_gold, native),
        "B_gold_injected": score(frozen_gold, gold_injected),
        "C_route_a_projection": score(frozen_gold, projection),
        "D_field_alignment_tp": alignment_tp(gold_aligned, projected_aligned, containment=False),
        "D2_lexical_containment_tp": alignment_tp(gold_aligned, projected_aligned, containment=True),
    }

    # ---------------------------------------------------------------- gate-28 comparison
    items = arms["A_native"]
    precision = None if items["precision"] is None else items["precision"]
    gate28 = {
        "authority": "issue28 preregistered-gate.json quality_requirements (signed)",
        "target_recall_overall_min": 0.85,
        "target_recall_per_source_min": 0.8,
        "candidate_precision_min": 0.8,
        "accepted_records_per_source_min": 20,
        "measured": {
            "material_items_precision": precision,
            "material_items_recall": items["recall"],
            "risk_or_condition_recall": items["gate"]["risk_condition_recall"],
            "critical_gold_missing": sum(
                1
                for row in gold_items
                if row.get("critical") and row["record_id"] in items["missing_gold_ids"]
            ),
            "accepted_records_per_source": "N/A (requires Stage 2 adjudication)",
        },
        "out_of_scope_for_this_gate": [
            "claims / material_relations thresholds (items-only gate)",
            "report_support (no conclusions supplied)",
        ],
        "note": "本地比较即诊断口径；不得表述为'门 28 通过/未通过'（门 28 判据另有其被测对象与流程）。",
    }

    absent_by_source = {
        slug: sum(
            1 for info in per_record.values() if info["source_slug"] == slug and info["corpus_absent"]
        )
        for slug in SOURCES
    }
    carrier_fields_measured = [
        field
        for field in tested
        if availability[f"overall.{field}"]["hits"] == 0
    ]
    ec3 = {}
    for field in ("proposition",) + ALIGNMENT_FIELDS:
        dev = availability[f"{DEVELOPMENT_SLUG}.{field}"]
        held = availability[f"{HELD_OUT_SLUG}.{field}"]
        dev_den = dev["denominator"] - absent_by_source[DEVELOPMENT_SLUG]
        held_den = held["denominator"] - absent_by_source[HELD_OUT_SLUG]
        ec3[field] = {
            "literal_diff_pp": round(abs((held["rate"] or 0) - (dev["rate"] or 0)) * 100, 1),
            "restricted_to_records_with_candidates": {
                "md": None if not held_den else round(held["hits"] / held_den, 4),
                "docx": None if not dev_den else round(dev["hits"] / dev_den, 4),
            },
        }
    ec_verdicts = {
        "EC-1": {
            "measured_zero_carrier_required_fields": carrier_fields_measured,
            "verdict": "触发：契约 material_items 必需字段中 4 个在候选上零载体（含 speaker_ref），"
            "其余非必需字段 estimate_status 亦为 0。route a 无法产出契约形态记录。",
            "conflict_with_issue34": "§3 L3 / §5.2 记 3 个（proposition/attribution/source_stance）；"
            "实测为 4 个（+ speaker_ref）。以实测为准。",
        },
        "EC-2": {
            "B_gold_injected_tp": arms["B_gold_injected"]["tp"],
            "C_route_a_projection_tp": arms["C_route_a_projection"]["tp"],
            "verdict": "成立：B=19 且 C=0 ⇒ 旧 L9 的 19/48 全部来自金标注入，该数不构成路线 a 的可行性证据。",
        },
        "EC-3": {
            "literal": ec3,
            "verdict": "字面触发（多项差 > 10pp），但差异 100% 由 corpus_absent 解释："
            "剔除覆盖槽位内无候选的记录后，md 与 docx 同为 1.0 ⇒ 规则本身跨源成立。"
            "判据字面结论与可归因结论相反，属预注册时未预见，记 backlog。",
        },
        "EC-4": {
            "strict_reachable": sum(
                1 for info in per_record.values() if info["contract_shape_reachable_strict"]
            ),
            "carrier_only_reachable": sum(
                1 for info in per_record.values() if info["contract_shape_reachable_carrier_only"]
            ),
            "corpus_absent_by_source": absent_by_source,
            "verdict": "route a 的记录级上界 = 0/48（strict 口径）；仅按候选有载体的字段计 = 35/48，"
            "其中 9 条为覆盖槽位内无候选（全部属 md）。两个数字不得合并表述。",
        },
        "EC-5": {
            "backlog": [
                {
                    "id": "B-1",
                    "finding": "覆盖槽位内无候选的 md 记录为 9 条，而非 issue-34 §6 假定的 7 条："
                    "除丢包区 char:5246-5537 的 7 条外，另有 NT-I06（char:1393-1655）与 "
                    "NT-I41（char:5055-5071）。这两条未出现在 residual-attribution 的 9 个未产出槽位归因里。",
                    "not_decided": "本项不改动任何 EC 判定；需单独裁定其性质（模型判 no_supported_item / 另一次未登记损失 / 关联方法差异）。",
                    "caveat": "identity 匹配不含槽位，故'覆盖槽位内无候选'不等于'该记录不可匹配'。",
                },
                {
                    "id": "B-2",
                    "finding": "arm D / D2 均为 0，但两臂要求 5 个枚举字段逐字相等，故 0 无法区分"
                    "'枚举值不一致'与'命题文本不一致'两种原因。",
                    "next_measurement": "逐记录比较 covering-slot 候选中是否存在与金标逐字相同的 "
                    "(semantic_type, statement_role, speech_role, perspective, polarity) 元组；"
                    "该测量未预注册，须在新一轮预注册后进行。",
                },
                {
                    "id": "B-3",
                    "finding": "条件载体在实践上近乎不存在：10 条 condition 角色金标中仅 1 条"
                    "（docx）的覆盖槽位内存在 statement_role=condition 的候选。契约 v3 新增的 "
                    "condition_role_read_path 因此几乎没有可读数据。",
                },
            ],
            "verdict": "判据外新发现已登记为 backlog，不回流本次判据。",
        },
        "EC-6": {
            "conflicts": [
                "§3 L3 / §5.2：3 个缺失必需字段 → 实测 4 个（含 speaker_ref）",
                "§6：md 天花板 15/22 = 0.682（按丢 7 条算）→ 实测覆盖槽位内有候选的 md 记录为 13/22",
            ],
            "confirmed": ["§5.5：source_stance 不可由候选字段派生（0/48 载体）"],
            "verdict": "冲突项以实测为准并留待报告修订；本产物即修订依据。",
        },
    }
    result = {
        "schema_version": "items-l9-redo-1",
        "created_on": "2026-10-11",
        "zero_call": True,
        "association_caveat": (
            "载体可得性按'设计意图的覆盖槽位'统计（与 issue-34 L1/L2 的 locator→unit→packet→slot "
            "rebasing 同法）。这不是评分器的约束：identity 匹配不含槽位，因此 39/48 是**受限口径**；"
            "不受限口径（源内任一候选）下 proposition 与 5 个枚举字段均有候选（text 非空 222/222）。"
            "两份口径都不改变 EC-1：4 个字段在两份口径下都是 0/48。"
        ),
        "preregistration": {"path": str(PREREG.name), "sha256": digest(PREREG)},
        "split": {
            "development": DEVELOPMENT_SLUG,
            "held_out": HELD_OUT_SLUG,
            "both_directions": True,
        },
        "carrier_availability": availability,
        "per_record": per_record,
        "coverage": coverage,
        "arms": arms,
        "ec_verdicts": ec_verdicts,
        "gate28_comparison": gate28,
        "candidate_side": {
            "records": len(candidates),
            "fields_present": {
                field: sum(1 for c in candidates if nonempty(c, field))
                for field in required + [CONDITION_ROLE] + list(NON_REQUIRED_TESTED)
            },
            "key_present": {
                field: sum(1 for c in candidates if field in c)
                for field in required + [CONDITION_ROLE] + list(NON_REQUIRED_TESTED)
            },
        },
        "totals": {
            "gold_records": len(gold_items),
            "corpus_absent": sum(1 for info in per_record.values() if info["corpus_absent"]),
            "contract_shape_reachable_strict": sum(
                1 for info in per_record.values() if info["contract_shape_reachable_strict"]
            ),
            "contract_shape_reachable_carrier_only": sum(
                1 for info in per_record.values() if info["contract_shape_reachable_carrier_only"]
            ),
        },
    }

    baseline = {
        "schema_version": "items-current-scorer-baseline-1",
        "created_on": "2026-10-11",
        "zero_call": True,
        "kind": "control arm: current scorer, native candidate shape, frozen gold 48",
        "scorer": "plugins/corpus/structured_scoring.score_structured_quality",
        "match_mode": "strict identity equality on (role, source_id, origin, semantic_fields)",
        "policy_used": "PILOT_CANDIDATE_POLICY (hardcoded; 0.95/0.90)",
        "arm_A_native": arms["A_native"],
        "arm_B_gold_injected_repro": arms["B_gold_injected"],
        "arm_C_route_a_projection": arms["C_route_a_projection"],
        "arm_D_field_alignment_tp": arms["D_field_alignment_tp"],
        "arm_D2_exploratory_containment_tp": arms["D2_lexical_containment_tp"],
        "gate28_comparison": gate28,
        "reading": (
            "A is the honest control: the real 222 candidates in their own field shape against the "
            "existing strict-identity scorer. B reproduces the issue-34 L9 'gold field shape' arm by "
            "injecting gold semantic_fields into candidates; C is the same projection built only from "
            "candidate data. The B/C gap is the circularity of the old number; D/D2 are diagnostic "
            "alignment upper bounds and must not be called recall."
        ),
    }

    inputs = {
        str(path.relative_to(REPO_ROOT)): digest(path)
        for path in (
            PREREG,
            WORKBENCH,
            DRAFT,
            GOLD,
            CONTRACT,
            E32_R0 / "plan-treatment-industrial-fulian-md.json",
            E32_R0 / "plan-treatment-optical-module-docx.json",
            REPO_ROOT / "plugins/corpus/structured_scoring.py",
            REPO_ROOT / "plugins/corpus/material_semantics.py",
            REPO_ROOT / "plugins/corpus/evidence_pipeline.py",
            CLAIMS / "evidence/34-chain-root-cause-audit-20261011/r0-zero-call/audit_chain.py",
        )
    }

    summary = {
        "arm_A_native": {k: arms["A_native"][k] for k in ("tp", "fp", "fn", "precision", "recall")},
        "arm_B_gold_injected": {
            k: arms["B_gold_injected"][k] for k in ("tp", "fp", "fn", "precision", "recall")
        },
        "arm_C_route_a_projection": {
            k: arms["C_route_a_projection"][k] for k in ("tp", "fp", "fn", "precision", "recall")
        },
        "arm_D_tp": arms["D_field_alignment_tp"],
        "arm_D2_tp_exploratory": arms["D2_lexical_containment_tp"],
        "totals": result["totals"],
        "availability": {
            field: availability[f"overall.{field}"] for field in tested
        },
        "candidate_key_present": result["candidate_side"]["key_present"],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if args.no_write:
        return

    (HERE / "l9-redo.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (HERE / "baseline-control.json").write_text(
        json.dumps(baseline, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (HERE / "l9-redo.md").write_text(render_l9_md(result), encoding="utf-8")
    (HERE / "baseline-control.md").write_text(render_baseline_md(baseline), encoding="utf-8")
    manifest = {
        "schema_version": "items-l9-redo-manifest-1",
        "created_on": "2026-10-11",
        "inputs": inputs,
        "outputs": {
            name: digest(HERE / name)
            for name in (
                "preregistered-l9-redo.json",
                "l9-redo.json",
                "baseline-control.json",
                "l9-redo.md",
                "baseline-control.md",
                "l9_redo.py",
            )
        },
    }
    (HERE / "MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def render_l9_md(result: dict[str, Any]) -> str:
    availability = result["carrier_availability"]
    tested = [field for field in availability if field.startswith("overall.")]
    lines = [
        "# L9 重做（金标盲 + 留出记录）",
        "",
        f"- 预注册：`{result['preregistration']['path']}` `{result['preregistration']['sha256']}`",
        f"- 切分：development = `{result['split']['development']}`，held-out = `{result['split']['held_out']}`",
        "- 归因：只按槽位跨度重叠（不读金标 semantic_fields）",
        "",
        "## 契约字段的载体可得性（按记录，48 条金标）",
        "",
        "| 契约字段 | 全体命中/分母 | md（留出） | docx（开发） |",
        "|---|---|---|---|",
    ]
    for key in tested:
        field = key.split(".", 1)[1]
        overall = availability[key]
        md = availability.get(f"industrial-fulian-md.{field}", {})
        docx = availability.get("optical-module-docx.{0}".format(field), {})
        lines.append(
            "| `{0}` | {1}/{2} | {3}/{4} | {5}/{6} |".format(
                field,
                overall["hits"],
                overall["denominator"],
                md.get("hits", "-"),
                md.get("denominator", "-"),
                docx.get("hits", "-"),
                docx.get("denominator", "-"),
            )
        )
    totals = result["totals"]
    lines += [
        "",
        "## 记录级可达性（route a 的上界，诊断口径）",
        "",
        f"- 金标记录：{totals['gold_records']}",
        f"- 覆盖槽位内无任何候选（传输事件丢包）：**{totals['corpus_absent']}**",
        f"- 全部必需字段都有载体（strict）：**{totals['contract_shape_reachable_strict']}**",
        f"- 仅按有载体的字段计（carrier-only）：**{totals['contract_shape_reachable_carrier_only']}**",
        "",
        "## 四臂（现有评分器，严格 identity 相等）",
        "",
        "| 臂 | tp | fp | fn | precision | recall |",
        "|---|---|---|---|---|---|",
    ]
    for name in ("A_native", "B_gold_injected", "C_route_a_projection"):
        arm = result["arms"][name]
        lines.append(
            "| {0} | {1} | {2} | {3} | {4} | {5} |".format(
                name, arm["tp"], arm["fp"], arm["fn"], arm["precision"], arm["recall"]
            )
        )
    lines += [
        "",
        f"- `D_field_alignment_tp` = **{result['arms']['D_field_alignment_tp']}**（诊断口径，禁止称召回）",
        f"- `D2_lexical_containment_tp` = **{result['arms']['D2_lexical_containment_tp']}**（探索性，不参与任何判据）",
        "",
        "## 候选侧实测（222 条）",
        "",
        "| 字段 | key 存在数 | 非空数 |",
        "|---|---|---|",
    ]
    for field, count in result["candidate_side"]["key_present"].items():
        lines.append(
            "| `{0}` | {1} | {2} |".format(
                field, count, result["candidate_side"]["fields_present"][field]
            )
        )
    lines += ["", "## 归因口径", "", f"> {result['association_caveat']}", ""]
    lines += ["## 预注册判据逐条回答", ""]
    for name, verdict in result["ec_verdicts"].items():
        lines.append(f"- **{name}**：{verdict.get('verdict', '')}")
    lines += ["", "## backlog（不回流本次判据）", ""]
    for item in result["ec_verdicts"]["EC-5"]["backlog"]:
        lines.append(f"- **{item['id']}**：{item['finding']}")
    return "\n".join(lines) + "\n"


def render_baseline_md(baseline: dict[str, Any]) -> str:
    arm = baseline["arm_A_native"]
    gate = baseline["gate28_comparison"]
    lines = [
        "# 现状基线（control 臂）",
        "",
        f"- 口径：{baseline['kind']}",
        f"- 匹配模式：`{baseline['match_mode']}`",
        f"- 评分器策略：`{baseline['policy_used']}`",
        "",
        "## A 臂结果（MATERIAL_ITEMS）",
        "",
        f"- tp={arm['tp']} fp={arm['fp']} fn={arm['fn']} precision={arm['precision']} recall={arm['recall']}",
        f"- 命中金标：{arm['matched']}；未命中：{len(arm['missing_gold_ids'])}",
        f"- `rate_gate_passed`={arm['gate']['rate_gate_passed']}；`live_trial_ready`={arm['gate']['live_trial_ready']}",
        f"- `risk_condition_recall`={arm['gate']['risk_condition_recall']}",
        "",
        "## 门 28 权威阈值对照（诊断口径）",
        "",
        f"- precision_min=0.80（实测 {gate['measured']['material_items_precision']}）",
        f"- target_recall_overall_min=0.85（实测 {gate['measured']['material_items_recall']}）",
        f"- risk/condition recall 门槛 0.95（实测 {gate['measured']['risk_or_condition_recall']}）",
        f"- critical 缺失条数：{gate['measured']['critical_gold_missing']}",
        f"- 分源接受数门槛 20：{gate['measured']['accepted_records_per_source']}",
        "",
        "## 评分器硬编码策略下的 blockers（原样）",
        "",
    ]
    lines += [f"- `{item}`" for item in arm["gate"]["rate_blockers"]]
    lines += ["", "## readiness blockers（原样）", ""]
    lines += [f"- `{item}`" for item in arm["gate"]["readiness_blockers"]]
    lines += [
        "",
        "> 本文件是诊断口径。不得表述为「门 28 通过／未通过」。",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
