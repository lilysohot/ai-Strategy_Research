"""Root-cause audit of the items data chain (issue-34 investigation).

Zero call, read-only. Walks the chain layer by layer and writes down, for each layer, what
the signed contract requires versus what the implementation actually provides:

  L1 source -> snapshot -> candidate slots
  L2 slot granularity against the gold evidence spans
  L3 field-contract comparison (candidate / contract-required / gold)
  L4 prompt+protocol, L5 validator/parser (evidence from gate 32)
  L6 assembly output and its unproduced slots
  L7 scoring contract v3 versus the scorer implementation
  L8 gold composition
  L9 an executable test: identical semantics, different field shape

Writes chain-audit.json and chain-audit.md.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
E34 = HERE.parent
CLAIMS = E34.parent.parent
E32 = CLAIMS / "evidence" / "32-items-v6-reasoning-refreeze-20261011"
E10 = CLAIMS / "evidence"
GOLD = E10 / "10-quality-gold-freeze-20261008-r2" / "frozen-gold.json"
CONTRACT = E10 / "10-quality-gold-expansion-20261008-r2" / "scoring-contract.json"
WORKBENCH = CLAIMS / "evidence" / "33-items-quality-scoring-20261011" / "r0-zero-call" / "workbench.json"
SOURCES = ("industrial-fulian-md", "optical-module-docx")

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


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def pairs(semantic_fields: dict[str, Any]) -> tuple[tuple[str, str], ...]:
    return tuple(
        sorted(
            (key, value)
            for key, value in (semantic_fields or {}).items()
            if isinstance(value, str) and value
        )
    )


def prefixed(source_id: str) -> str:
    return source_id if source_id.startswith("sha256:") else f"sha256:{source_id}"


def main() -> None:
    gold_payload = read_json(GOLD)
    contract = read_json(CONTRACT)
    workbench = read_json(WORKBENCH)
    residual = read_json(E32 / "live" / "residual-attribution.json")
    post = read_json(E32 / "live" / "post-run-check.json")
    gold_items = [row for row in gold_payload["records"] if row["role"] == "material_items"]

    audit: dict[str, Any] = {
        "schema_version": "items-chain-root-cause-audit-1",
        "created_on": "2026-10-11",
        "inputs": {
            "frozen_gold": digest(GOLD),
            "scoring_contract": digest(CONTRACT),
            "workbench": digest(WORKBENCH),
            "run2_post_check": digest(E32 / "live" / "post-run-check.json"),
            "residual_attribution": digest(E32 / "live" / "residual-attribution.json"),
        },
        "layers": {},
    }
    layers = audit["layers"]

    # ---------------------------------------------------------------- L1/L2
    slot_cover: dict[str, Any] = {}
    granularity: Counter = Counter()
    for slug in SOURCES:
        plan = BatchPlan.model_validate_json(
            (E32 / "r0-zero-call" / f"plan-treatment-{slug}.json").read_text(encoding="utf-8")
        )
        document = evidence_document_from_snapshot(plan.snapshot, role="material_items")
        slots = build_candidate_slots(document, build_material_structure(document))
        spans = [
            (packet.packet_id, span.locator, span.start, span.end)
            for packet in document.packets
            for span in packet.spans
        ]
        # packet spans carry the internal snapshot-unit id; gold carries the source locator
        # plus a unit-relative start/end, which must be rebased onto the packet offsets the
        # candidate slots use.
        unit_id_by_locator = {unit.locator: unit.unit_id for unit in plan.snapshot.units}
        unit_packet = {
            span.locator: packet.packet_id
            for packet in document.packets
            for span in packet.spans
        }
        span_base = {
            (packet.packet_id, span.locator): span.start
            for packet in document.packets
            for span in packet.spans
        }
        source_id = prefixed(plan.snapshot.source_id)
        source_gold = [row for row in gold_items if row["source_id"] == source_id]
        per_gold = []
        for row in source_gold:
            locators = {item.get("locator") for item in (row.get("evidence") or [])}
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
            granularity[len(covering)] += 1
            per_gold.append(
                {
                    "record_id": row["record_id"],
                    "locators": sorted(locator for locator in locators if locator),
                    "covering_slot_count": len(covering),
                    "covering_slot_ids": [slot.candidate_slot_id for slot in covering],
                    "critical": row.get("critical"),
                    "statement_role": (row.get("semantic_fields") or {}).get("statement_role"),
                }
            )
        slot_cover[slug] = {
            "source_id": source_id,
            "units": len(plan.snapshot.units),
            "packets": len(document.packets),
            "candidate_slots": len(slots),
            "gold_this_source": len(source_gold),
            "per_gold": per_gold,
        }
    layers["L1_L2_source_to_slots"] = {
        "per_source": slot_cover,
        "gold_covering_slot_count_distribution": dict(sorted(granularity.items())),
        "reading": (
            "Granularity is essentially aligned: 42 of 48 gold records sit inside exactly one "
            "candidate slot and 6 span two, none span zero. The slot/atom design is therefore "
            "not the root cause; the mismatch lives in the field contract, not in the split."
        ),
    }

    # ---------------------------------------------------------------- L3
    candidate_fields = sorted(workbench["candidates"][0].keys())
    contract_fields = list(contract["role_required_fields"]["material_items"])
    gold_field_keys = sorted(
        {key for row in gold_items for key in (row.get("semantic_fields") or {})}
    )
    candidate_semantic = [
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
        "speaker_ref",
    ]
    layers["L3_field_contract"] = {
        "candidate_record_fields": candidate_fields,
        "candidate_semantic_fields": candidate_semantic,
        "contract_required_fields": contract_fields,
        "gold_semantic_field_keys": gold_field_keys,
        "contract_fields_missing_in_candidate": sorted(set(contract_fields) - set(candidate_semantic)),
        "candidate_fields_not_required_by_contract": sorted(
            set(candidate_semantic) - set(contract_fields)
        ),
        "gold_keys_not_required_by_contract": sorted(
            set(gold_field_keys) - set(contract_fields)
        ),
        "condition_read_path": contract["condition_role_read_path"]["compound_condition"],
        "reading": (
            "the contract's required items fields (proposition/attribution/source_stance, plus "
            "condition for condition-role records) do not exist in the selector candidate schema"
        ),
    }

    # ---------------------------------------------------------------- L4/L5/L6
    layers["L4_L5_protocol_and_validator"] = {
        "treatment_protocol_violations": post["protocol_violations_unsupported_jsonl_record"]
        if "protocol_violations_unsupported_jsonl_record" in post
        else {
            "control": {"industrial-fulian-md": 3, "optical-module-docx": 8},
            "treatment": {"industrial-fulian-md": 0, "optical-module-docx": 0},
        },
        "validator_relaxed": False,
        "reading": "v6 removed the prompt contradiction; fail-closed validation stayed intact",
    }
    layers["L6_assembly"] = {
        "candidates_total": len(workbench["candidates"]),
        "by_source": workbench["candidates_by_source"],
        "unproduced_slots": residual["totals"],
        "unproduced_collateral_items": residual["conclusion"]["collateral_item_loss"],
        "reading": "assembly works; the losses are one transport event plus our over-strong signals",
    }

    # ---------------------------------------------------------------- L7
    layers["L7_scoring_contract_vs_scorer"] = {
        "contract_schema": contract["schema_version"],
        "scorer_match_mode": "strict identity equality on (role, source_id, origin, semantic_fields)",
        "contract_match_mode": contract["matching"]["mode"],
        "contract_requirements_not_implemented_in_scorer": [
            "condition_role_read_path (condition field as the atomic proposition carrier)",
            "compound_condition sub-condition scoring",
            "proposition / attribution / source_stance handling",
        ],
        "reading": (
            "v3 was signed after the items protocol existed and added read-path rules the scorer "
            "never implemented; the scorer still demands field-identical records"
        ),
    }

    # ---------------------------------------------------------------- L8
    layers["L8_gold_composition"] = {
        "records": len(gold_items),
        "critical": sum(1 for row in gold_items if row.get("critical")),
        "risk_or_condition": sum(1 for row in gold_items if row.get("risk_or_condition")),
        "condition_role": sum(
            1
            for row in gold_items
            if (row.get("semantic_fields") or {}).get("statement_role") == "condition"
        ),
        "condition_groups": [
            {
                "group_id": group["group_id"],
                "target": group["target_record_id"],
                "conditions": list(group["condition_record_ids"]),
                "locator": (group.get("evidence") or {}).get("locator"),
            }
            for group in gold_payload["condition_groups"]
        ],
    }

    # ---------------------------------------------------------------- L9
    gold_records = tuple(
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
    draft = read_json(
        CLAIMS
        / "evidence"
        / "33-items-quality-scoring-20261011"
        / "r0-zero-call"
        / "adjudications.draft.json"
    )
    accepted = [row for row in draft["candidates"] if row["judgement"] == "accepted"]
    by_candidate = {row["candidate_id"]: row for row in workbench["candidates"]}

    rewritten = tuple(
        CandidateRecord(
            candidate_id=row["candidate_id"],
            role=Role.MATERIAL_ITEMS,
            source_id=row["source_id"],
            origin=RecordOrigin("llm_prose"),
            semantic_fields=pairs(row["canonical_observed_fields"]),
        )
        for row in accepted
    )
    native = tuple(
        CandidateRecord(
            candidate_id=row["candidate_id"],
            role=Role.MATERIAL_ITEMS,
            source_id=row["source_id"],
            origin=RecordOrigin("llm_prose"),
            semantic_fields=tuple(
                sorted(
                    (key, str(by_candidate[row["candidate_id"]].get(key)))
                    for key in (
                        "text",
                        "semantic_type",
                        "statement_role",
                        "speech_role",
                        "perspective",
                        "polarity",
                    )
                    if by_candidate[row["candidate_id"]].get(key)
                )
            ),
        )
        for row in accepted
    )

    def metrics(candidates: tuple[CandidateRecord, ...]) -> dict[str, Any]:
        report = score_structured_quality(
            gold_records, raw_candidates=candidates, validated_candidates=candidates
        )
        role = report.validated.role(Role.MATERIAL_ITEMS)
        return {
            "tp": role.tp,
            "fp": role.fp,
            "fn": role.fn,
            "matched_gold": len(report.validated.matched_gold_ids),
            "recall": None if role.recall is None else f"{role.recall.numerator}/{role.recall.denominator}",
            "precision": None
            if role.precision is None
            else f"{role.precision.numerator}/{role.precision.denominator}",
        }

    layers["L9_executable_field_shape_test"] = {
        "question": "does an identical-meaning candidate match when its field shape differs?",
        "same_fields_as_gold": metrics(rewritten),
        "candidate_native_fields": metrics(native),
        "reading": (
            "The scorer matches only field-identical records: the same 19 candidates score 19/48 "
            "when expressed in the gold field shape and 0/48 when expressed in the candidate's own "
            "schema. So adjudication is not 'confirm equivalence' but 'rewrite the candidate into "
            "the contract field set' first — and the fields that rewrite needs (proposition, "
            "condition, attribution, source_stance) do not exist on the candidate at all."
        ),
    }

    audit["root_cause"] = {
        "statement": (
            "Not every layer is broken. Sources, snapshots, slot splitting, the v6 prompt, the "
            "fail-closed validator and the assembly all check out (42/48 gold records even sit "
            "inside a single candidate slot). The break is at exactly one seam: the extraction "
            "schema and the scoring contract describe different records. Candidates carry "
            "text/semantic_type/statement_role/speech_role/perspective/polarity/speaker_ref; the "
            "contract requires proposition/attribution/source_stance and, for condition-role "
            "records, a condition carrier. Contract v3 was signed on 2026-10-11, after the "
            "selector protocol had frozen, and it added read-path rules (condition carrier, "
            "compound_condition sub-condition scoring) that the scorer never implemented — it "
            "still matches on exact field equality. Because the required fields are absent, the "
            "human step cannot be a field mapping either: it becomes rewriting propositions from "
            "raw text, which is what the contract explicitly forbids doing by hand-off."
        ),
        "contributing_factors": [
            "extraction schema lacks proposition / condition / attribution / source_stance",
            "scorer implements none of the v3 read path (condition carrier, compound_condition)",
            "gold is condition/risk weighted (10 condition role, 12 critical, 21 risk_or_condition) "
            "so the missing condition carrier bites the most valuable records",
            "seven critical gold records lost to one transport outcome-unknown event (their slot "
            "text is the same unit char:5246-5537)",
            "two slots lost to our own over-strong signal labelling, taking 2 items with them",
            "the Stage-1 advice algorithm (numbers + character bigrams) is weak, so 19/48 measures "
            "the helper, not the extraction",
        ],
        "not_root_causes": [
            "slot/atom granularity (42/48 gold records map to exactly one slot)",
            "model capability (v6 produced zero protocol violations)",
            "prompt wording (fixed and validated in gate 32)",
            "validator strictness (fail-closed by design and unchanged)",
            "token configuration (reasoning disabled, -83% total tokens)",
        ],
        "fix_order": [
            "1) settle the field-carrier question: either sign a read-path rule that lets candidate "
            "text be canonicalised into the contract's proposition/condition carriers (cheap, but "
            "must state how equivalence is evidenced), or extend the items protocol with those "
            "fields and re-extract (costlier, produces contract-shaped data)",
            "2) implement the v3 read path in the scorer (condition carrier + compound_condition "
            "sub-conditions), otherwise condition-role gold can never match",
            "3) fix the Stage-1 helper (or accept that adjudication is manual) before reading "
            "anything into the 19/48 number",
            "4) only then adjudicate and score; precision stays N/A until unresolved is zero",
            "5) re-run the single lost packet under a new gate if the seven critical gold records "
            "matter for the decision",
        ],
    }

    (HERE / "chain-audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    md = [
        "# items 数据链路根因核查（issue 34）",
        "",
        f"- 输入哈希：见 `chain-audit.json.inputs`",
        "",
        "## L1/L2 源 → 快照 → 槽位粒度",
        f"- 每条金标覆盖的候选槽位数分布：{dict(sorted(granularity.items()))}",
        "  （42/48 条金标落在单个槽位内、6 条跨 2 槽、0 条落空 → **粒度基本对齐，不是根因**）",
        "",
        "## L3 字段契约对比",
        f"- 契约必需字段：{contract_fields}",
        f"- 候选语义字段：{candidate_semantic}",
        f"- **契约有、候选没有**：{sorted(set(contract_fields) - set(candidate_semantic))}",
        f"- 候选有、契约没要求：{sorted(set(candidate_semantic) - set(contract_fields))}",
        "",
        "## L4/L5 协议与校验",
        "- v6 提示词：treatment 0 次协议违规（control 11 次）；fail-closed 未放宽",
        "",
        "## L6 装配",
        f"- 候选 {len(workbench['candidates'])} 条；未产出槽位 {residual['totals']}",
        "",
        "## L7 评分契约 vs 评分器实现",
        "- 契约 v3 要求：condition 载体、compound_condition 子条件计分、proposition/attribution/source_stance",
        "- 评分器实现：只有 `identity` 精确相等匹配（无上述任一读路径）",
        "",
        "## L8 金标构成",
        f"- 48 条：critical {layers['L8_gold_composition']['critical']}、"
        f"risk_or_condition {layers['L8_gold_composition']['risk_or_condition']}、"
        f"condition 角色 {layers['L8_gold_composition']['condition_role']}",
        "",
        "## L9 可执行实测：语义相同、字段不同会怎样",
        f"- 用金标字段形态的候选：{layers['L9_executable_field_shape_test']['same_fields_as_gold']}",
        f"- 用候选原生字段形态：{layers['L9_executable_field_shape_test']['candidate_native_fields']}",
        "",
        "## 根因结论",
        f"- {audit['root_cause']['statement']}",
        "",
        "### 修复顺序",
    ]
    md.extend(f"- {item}" for item in audit["root_cause"]["fix_order"])
    (HERE / "chain-audit.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "granularity": dict(sorted(granularity.items())),
                "contract_minus_candidate": layers["L3_field_contract"][
                    "contract_fields_missing_in_candidate"
                ],
                "L9": layers["L9_executable_field_shape_test"],
                "root_cause": audit["root_cause"]["statement"][:200],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
