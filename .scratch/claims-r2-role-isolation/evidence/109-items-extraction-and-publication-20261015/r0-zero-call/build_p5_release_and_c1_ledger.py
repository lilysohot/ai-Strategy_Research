"""P5 release record (draft) + C1 pending-coverage ledger for the 109-号 round-3 pool.

Two outputs, one pass, zero model calls, no production writes:

1. ``p5-release-record.json`` — the readable gate verdict for the U-authored round-3 candidate set,
   produced by the **real scorer** (``MatchingMode.ADJUDICATED`` + the signed contract v4.3 gate
   requirements + signed gate v3 sentinels), not by a re-implementation. The verdict is recorded
   **as-is**; the publication basis is separate and comes from the 72-号 decoupling ruling
   (structural completeness, not the gate thresholds). Left unsigned: release is a named human act.
2. ``p4-c1-disposition.json`` — the 29 条 claims role-external candidates of 92 号, each given a
   disposition (``covered_by_candidate_id`` or ``no_candidate``) as preregistration v2 requires.
   Written as a **new record**; the U-authored candidate set is never edited.

Neither output claims a gate PASS. The gate reading is FAIL and stays FAIL; what this record
supports is "publish with an explicit gap list", which is a different claim.

Usage:
    python build_p5_release_and_c1_ledger.py [--no-write] [--force]
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
import sys
from fractions import Fraction
from math import floor
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
REPO_ROOT = ROOT.parents[1]
sys.path.insert(0, str(REPO_ROOT))

from plugins.corpus.adjudication_assembly import AdjudicatedMapping  # noqa: E402
from plugins.corpus.structured_scoring import (  # noqa: E402
    CandidateRecord,
    GoldRecord,
    MatchingMode,
    RecordOrigin,
    Role,
    load_contract_gate_requirements,
    score_structured_quality,
)
from tools.evidence_guard import write_once  # noqa: E402

CREATED_ON = "2026-10-15"
C1_THRESHOLD = 0.55
HIGH_CONFIDENCE = 0.80
REVIEW_BAND = 0.40

AUTHORED_SET = HERE / "items-reextract-adjudication-r3/candidate-adjudications.worksheet.json"
SCOREABLE_COPY = (
    HERE / "items-reextract-adjudication-r3-blank/candidate-adjudications.worksheet.json"
)
GOLD = ROOT / "evidence/33-items-quality-scoring-20261011/r0-zero-call/adjudications.json"
GATE_V3 = ROOT / "evidence/75-r2-signed-20261013/r0-zero-call/gate-v3.json"
CONTRACT_V43 = ROOT / "evidence/75-r2-signed-20261013/r0-zero-call/scoring-contract-v4.3.json"
PREREG_V2 = HERE / "items-reextraction-preregistration-v2.json"
GAP_ANALYSIS = HERE / "p4-remaining-gap-analysis.json"
C1_SUGGESTIONS = HERE / "items-reextract-adjudication-r3/c1-suggestions.json"
CLAIMS_PREREG_99 = (
    ROOT
    / "evidence/99-claims-prereg-v3-signed-r2-20261014/r0-zero-call/claims-preregistration.json"
)
C1_RATIFICATION = HERE / "p5-c1-reading-ratification.json"
U_RULINGS = HERE / "p5-u-rulings-20261015.json"
C1_FINAL = HERE / "p4-c1-disposition-final.json"
C1_WORKSHEET = (
    HERE / "items-reextract-adjudication-r3-c1ruled/candidate-adjudications.worksheet.json"
)

OUT_RELEASE = HERE / "p5-release-record.json"
OUT_C1 = HERE / "p4-c1-disposition.json"

SOURCE_LABEL = {
    "sha256:f8fa22084535e3696fed0bc4da1e9a1b71c863ddb1a883603dcb3d251839cbcb": "industrial-fulian-md",
    "sha256:48c05895798ba0096b5ac5cc6fbf42fcc9d63929c2a7a2df61e7b16b3a4a659f": "optical-module-docx",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sf_pairs(fields: dict[str, Any]) -> tuple[tuple[str, str], ...]:
    pairs = tuple(sorted((str(k), str(v)) for k, v in fields.items() if v not in (None, "")))
    return pairs or (("proposition", "<empty>"),)


def norm(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "")).lower()


def score_pool() -> dict[str, Any]:
    """Run the real scorer over the round-3 pool and return its own verdict verbatim."""
    worksheet = load(SCOREABLE_COPY)
    gold_payload = load(GOLD)
    gate = load(GATE_V3)
    requirements = load_contract_gate_requirements(CONTRACT_V43, Role.MATERIAL_ITEMS)

    gold = tuple(
        GoldRecord(
            record_id=record["record_id"],
            role=Role.MATERIAL_ITEMS,
            source_id=record["source_id"],
            origin=RecordOrigin.LLM_PROSE,
            semantic_fields=sf_pairs(
                {
                    "proposition": record.get("quote") or "",
                    "semantic_type": record.get("semantic_type") or "",
                    "statement_role": record.get("statement_role") or "",
                }
            ),
            critical=bool(record.get("critical")),
            risk_or_condition=bool(record.get("risk_or_condition")),
        )
        for record in gold_payload["gold_reference"]
    )

    origins = {item.value for item in RecordOrigin}
    candidates: list[CandidateRecord] = []
    mappings: list[AdjudicatedMapping] = []
    for row in worksheet["adjudications"]:
        fields = row["canonical_observed_fields"]
        declared_origin = str((row.get("original_candidate") or {}).get("origin") or "")
        origin = (
            RecordOrigin(declared_origin) if declared_origin in origins else RecordOrigin.LLM_PROSE
        )
        candidates.append(
            CandidateRecord(
                candidate_id=row["candidate_id"],
                role=Role.MATERIAL_ITEMS,
                source_id=row["source_id"],
                origin=origin,
                semantic_fields=sf_pairs(
                    {
                        "proposition": fields.get("proposition") or "",
                        "semantic_type": fields.get("semantic_type") or "",
                        "statement_role": fields.get("statement_role") or "",
                    }
                ),
            )
        )
        mappings.append(
            AdjudicatedMapping(
                candidate_id=row["candidate_id"],
                gold_record_id=row.get("matched_gold_id"),
                judgement=row["judgement"],
                stage=row["stage"],
            )
        )

    report = score_structured_quality(
        gold,
        raw_candidates=tuple(candidates),
        validated_candidates=tuple(candidates),
        matching_mode=MatchingMode.ADJUDICATED,
        raw_mappings=tuple(mappings),
        validated_mappings=tuple(mappings),
    )
    items = report.raw.role(Role.MATERIAL_ITEMS)
    matched = set(report.raw.matched_gold_ids)
    by_id = {record["record_id"]: record for record in gold_payload["gold_reference"]}

    per_source: dict[str, dict[str, Any]] = {}
    for source_id, label in SOURCE_LABEL.items():
        gold_ids = [rid for rid, rec in by_id.items() if rec["source_id"] == source_id]
        hits = [rid for rid in gold_ids if rid in matched]
        per_source[label] = {
            "candidates": sum(
                1 for row in worksheet["adjudications"] if row["source_id"] == source_id
            ),
            "gold": len(gold_ids),
            "matched": len(hits),
            # Unreduced on purpose: ``Fraction`` would print 18/22 as 9/11, i.e. a different denominator.
            "recall": f"{len(hits)}/{len(gold_ids)}" if gold_ids else None,
            "correct_extra": sum(
                1
                for row in worksheet["adjudications"]
                if row["source_id"] == source_id and row["judgement"] == "correct_extra"
            ),
            "duplicate": sum(
                1
                for row in worksheet["adjudications"]
                if row["source_id"] == source_id and row["judgement"] == "duplicate"
            ),
        }

    sentinels = requirements.high_risk_item_assertions_required
    thresholds = gate["quality_requirements"]

    def criterion(
        number: int, name: str, threshold: Any, measured: str, passed: bool
    ) -> dict[str, Any]:
        return {
            "n": number,
            "id": name,
            "threshold": threshold,
            "measured": measured,
            "verdict": "PASS" if passed else "FAIL",
        }

    source_ok = all(
        Fraction(value["matched"], value["gold"])
        >= Fraction(
            int(thresholds["target_recall_per_source_min"] * 100),
            100,
        )
        for value in per_source.values()
    )
    source_floor_ok = all(
        value["matched"] >= thresholds["accepted_records_per_source_min"]
        for value in per_source.values()
    )
    criteria = [
        criterion(
            1,
            "target_recall_overall_min",
            thresholds["target_recall_overall_min"],
            f"{items.tp}/{len(by_id)} = {float(Fraction(items.tp, len(by_id))):.4f}",
            Fraction(items.tp, len(by_id))
            >= Fraction(int(thresholds["target_recall_overall_min"] * 100), 100),
        ),
        criterion(
            2,
            "target_recall_per_source_min",
            thresholds["target_recall_per_source_min"],
            "；".join(
                f"{label} {value['matched']}/{value['gold']}" for label, value in per_source.items()
            ),
            source_ok,
        ),
        criterion(
            3,
            "candidate_precision_min",
            thresholds["candidate_precision_min"],
            str(items.precision),
            items.precision is not None
            and float(items.precision) >= thresholds["candidate_precision_min"],
        ),
        criterion(
            4,
            "unresolved_candidates_max",
            thresholds["unresolved_candidates_max"],
            "0",
            all(mapping.judgement != "unresolved" for mapping in mappings),
        ),
        criterion(
            5,
            "accepted_records_total_min",
            thresholds["accepted_records_total_min"],
            str(len(matched)),
            len(matched) >= thresholds["accepted_records_total_min"],
        ),
        criterion(
            6,
            "accepted_records_per_source_min",
            thresholds["accepted_records_per_source_min"],
            "；".join(f"{label} {value['matched']}" for label, value in per_source.items()),
            source_floor_ok,
        ),
        criterion(
            7,
            "high_risk_item_assertions_required",
            f"{len(sentinels)}/{len(sentinels)}",
            f"{sum(1 for s in sentinels if s in matched)}/{len(sentinels)}；"
            f"未中 {[s for s in sentinels if s not in matched]}",
            all(s in matched for s in sentinels),
        ),
    ]

    # 合同的条数下限按其自身的派生规模复算一次。规则 floor(0.85 × 目标规模) 取自 93 号 M1
    # （b_scaled_floor）；它能把合同的 total 下限逐字复现出来，说明它就是合同自己的派生规则。
    def derived_floor(target: int) -> int:
        return floor(0.85 * target)

    total_target = len(by_id)
    per_source_targets = {label: value["gold"] for label, value in per_source.items()}
    derived_per_source = {
        label: derived_floor(value) for label, value in per_source_targets.items()
    }
    contract_per_source_floor = thresholds["accepted_records_per_source_min"]
    balanced_split = total_target // 2
    count_floor_derivation = {
        "rule": "floor(0.85 × 角色目标规模)（93 号 M1 b_scaled_floor；本件只复算，不改任何已签件）",
        "self_consistency": {
            "total": f"floor(0.85 × {total_target}) = {derived_floor(total_target)}",
            "contract_total_floor": thresholds["accepted_records_total_min"],
            "matches": derived_floor(total_target) == thresholds["accepted_records_total_min"],
        },
        "origin_of_contract_per_source_floor": {
            "value": contract_per_source_floor,
            "hypothesis": f"floor(0.85 × {total_target}/2) = floor(0.85 × {balanced_split}) = {derived_floor(balanced_split)}",
            "matches": derived_floor(balanced_split) == contract_per_source_floor,
            "reading": (
                "合同的分源下限与『两源按 48/2 均分』的假设相符 ⇒ 它是均分假设的产物，"
                "而非按实际分源目标 22/26 派生"
            ),
        },
        "actual_per_source_targets": per_source_targets,
        "recomputed_per_source_floors": derived_per_source,
        "measured_matched": {label: value["matched"] for label, value in per_source.items()},
        "consequence": {
            label: (
                f"{per_source[label]['matched']} vs 复算下限 {derived_per_source[label]}"
                f"（合同字面 {contract_per_source_floor}）"
                f" ⇒ {'达标' if per_source[label]['matched'] >= derived_per_source[label] else '未达标'}"
            )
            for label in per_source
        },
        "status": "复算结论待 U 裁；合同 v4.3 字节未动、评分器未改",
    }

    axis_to_criterion = {
        "target_recall_overall": "target_recall_overall_min",
        "target_recall_per_source": "target_recall_per_source_min",
        "candidate_precision": "candidate_precision_min",
        "unresolved_candidates": "unresolved_candidates_max",
        "sentinel_assertions": "high_risk_item_assertions_required",
    }
    by_criterion = {item["id"]: item["verdict"] for item in criteria}
    axes_outcome = {axis: by_criterion[criterion] for axis, criterion in axis_to_criterion.items()}

    return {
        "gate": gate,
        "requirements": requirements,
        "criteria": criteria,
        "count_floor_derivation": count_floor_derivation,
        "criteria_axes_outcome": axes_outcome,
        "items": {
            "tp": items.tp,
            "fp": items.fp,
            "fn": items.fn,
            "duplicate_fp": items.duplicate_fp,
            "correct_extra": items.correct_extra,
            "precision": str(items.precision) if items.precision is not None else None,
            "recall": str(items.recall) if items.recall is not None else None,
        },
        "per_source": per_source,
        "matched": sorted(matched),
        "missing": [rid for rid in by_id if rid not in matched],
        "unmatched_critical": [
            rid for rid, rec in by_id.items() if rec.get("critical") and rid not in matched
        ],
        "rate_gate_passed": report.gate.rate_gate_passed,
        "live_trial_ready": report.gate.live_trial_ready,
        "rate_blockers": list(report.gate.rate_blockers),
        "readiness_blockers": list(report.gate.readiness_blockers),
        "pilot_policy_blockers": list(report.gate.pilot_policy_blockers),
    }


def build_c1_ledger() -> dict[str, Any]:
    """Disposition every 92-号 pending_coverage entry against the round-3 pool."""
    worksheet = load(AUTHORED_SET)
    prereg = load(PREREG_V2)
    binding = prereg["adjudication_clause"]["c1_pending_coverage"]
    registration_path = REPO_ROOT / binding["source"]
    registration = load(registration_path)
    entries = [
        entry
        for entry in registration["entries"]
        if entry.get("owner_role") == "material_items" and entry.get("status") == "pending_coverage"
    ]
    if len(entries) != binding["count"]:
        raise SystemExit(f"C1 count drift: {len(entries)} != {binding['count']}")

    pool = [
        (
            row["candidate_id"],
            norm((row.get("original_candidate") or {}).get("text", "")),
            row["run"],
            row["judgement"],
            row.get("matched_gold_id"),
        )
        for row in worksheet["adjudications"]
    ]
    suggestions = {item["c1_candidate_id"]: item for item in load(C1_SUGGESTIONS)["suggestions"]}

    dispositions = []
    for entry in entries:
        target = norm(entry["claim_text"])
        best = max(pool, key=lambda item: difflib.SequenceMatcher(None, target, item[1]).ratio())
        ratio = round(difflib.SequenceMatcher(None, target, best[1]).ratio(), 3)
        suggested = suggestions.get(entry["candidate_id"])
        if suggested is None:
            raise SystemExit(f"suggestion missing for {entry['candidate_id']}")
        if suggested["best_similarity"] != ratio:
            raise SystemExit(
                f"similarity drift for {entry['candidate_id']}: "
                f"{suggested['best_similarity']} != {ratio}"
            )
        covered = ratio >= C1_THRESHOLD
        # Text similarity is a screening rule, not an equivalence test: within the band the
        # mechanical verdict is unreliable in both directions, so each row carries how much human
        # attention it needs. The 0.49 row below is a live example (see known_limits).
        if ratio >= HIGH_CONFIDENCE:
            review_flag = "mechanical_high_confidence"
        elif ratio >= REVIEW_BAND:
            review_flag = "near_threshold_needs_human_eye"
        else:
            review_flag = "no_plausible_candidate"
        dispositions.append(
            {
                "c1_candidate_id": entry["candidate_id"],
                "claim_text": entry["claim_text"],
                "owner_role": "material_items",
                "disposition": "covered_by_candidate" if covered else "no_candidate",
                "covered_by_candidate_id": best[0] if covered else None,
                "review_flag": review_flag,
                "evidence": {
                    "best_similarity": ratio,
                    "threshold": C1_THRESHOLD,
                    "matched_run": best[2],
                    "matched_candidate_text": best[1][:120],
                    "matched_candidate_judgement": best[3],
                    "matched_candidate_gold": best[4],
                },
            }
        )

    covered_rows = [row for row in dispositions if row["disposition"] == "covered_by_candidate"]
    uncovered_rows = [row for row in dispositions if row["disposition"] == "no_candidate"]
    return {
        "schema_version": "items-c1-disposition-1",
        "id": "109-p4-c1-disposition",
        "created_on": CREATED_ON,
        "model_calls": 0,
        "status": "recorded_pending_human_confirmation",
        "basis": {
            "prereg_v2": {
                "path": str(PREREG_V2.relative_to(ROOT)),
                "sha256": sha256(PREREG_V2),
                "clause": "adjudication_clause.c1_pending_coverage",
                "rule": "有对应新池候选者入裁定、无对应者记 no_candidate；不得就地丢弃",
            },
            "registration": {
                "path": str(registration_path.relative_to(ROOT)),
                "sha256": sha256(registration_path),
                "count": len(entries),
            },
            "candidate_set": {
                "path": str(AUTHORED_SET.relative_to(ROOT)),
                "sha256": sha256(AUTHORED_SET),
            },
            "suggestions": {
                "path": str(C1_SUGGESTIONS.relative_to(ROOT)),
                "sha256": sha256(C1_SUGGESTIONS),
                "threshold": C1_THRESHOLD,
                "note": "本件逐条复算该建议（同算法同阈值，偏差即拒绝出件），并由人复核后才生效",
            },
        },
        "dispositions": dispositions,
        "summary": {
            "total": len(dispositions),
            "covered_by_candidate": len(covered_rows),
            "no_candidate": len(uncovered_rows),
            "by_review_flag": {
                flag: sum(1 for row in dispositions if row["review_flag"] == flag)
                for flag in (
                    "mechanical_high_confidence",
                    "near_threshold_needs_human_eye",
                    "no_plausible_candidate",
                )
            },
            "meaning": (
                "no_candidate = 该内容在新池中无承载候选 ⇒ 跨角色仍未被覆盖，须在发布件里作为显式缺口列出；"
                "covered_by_candidate 只表示池内存在承载候选，不表示该候选已被判 matched"
            ),
            "review_rule": (
                f"review_flag 由 best_similarity 分档：≥{HIGH_CONFIDENCE} 机械高置信；"
                f"{REVIEW_BAND}–{HIGH_CONFIDENCE} 需人眼；<{REVIEW_BAND} 无近似候选。"
                f"disposition 仍按 {C1_THRESHOLD} 阈值给出，但 near-threshold 行的方向由人定"
            ),
        },
        "known_limits": {
            "threshold_is_a_screen_not_an_equivalence_test": True,
            "worked_example": {
                "c1_candidate_id": "13edee989550a682308e39675b2c5978c743a9cecd12aaa9dcbb026a4656bdde",
                "claim_text": "工业富联观察仓止损条件为下季OCF/扣非<0.5",
                "mechanical_disposition": "no_candidate（sim 0.49 < 0.55）",
                "actually_present_in_pool": (
                    "itm_ 候选『下季ocf盖不住扣非的一半（ocf/扣非<0.5）』判 matched（NT-I15）"
                    "——同一断言，字面相似度不足"
                ),
                "correct_reading": "该条实为 covered_by_candidate；机械阈值在此漏判",
            },
            "consequence": "15 条 no_candidate 中有多少属于此类漏判需人眼确认后才能当作发布缺口",
        },
        "untouched": [
            "U 候选集与可出分副本字节未改（本件为新增记录）",
            "92 号登记件、预注册 v2、冻结件、已签门/契约均未动",
        ],
    }


def build_release(score: dict[str, Any]) -> dict[str, Any]:
    gaps = load(GAP_ANALYSIS) if GAP_ANALYSIS.exists() else None
    c1 = load(OUT_C1) if OUT_C1.exists() else None
    # 读法认可件是 P5 判档措辞的依据之一；缺件即拒绝出件（fail closed），不静默降级。
    if not C1_RATIFICATION.exists():
        raise SystemExit("缺少 p5-c1-reading-ratification.json：判档措辞的依据不在位")
    ratification = load(C1_RATIFICATION)
    if ratification["status"] not in (
        "stated_effective_pending_countersignature",
        "countersigned_effective",
    ):
        raise SystemExit(f"读法认可件状态不可用：{ratification['status']}")
    if not U_RULINGS.exists():
        raise SystemExit("缺少 p5-u-rulings-20261015.json：本批 U 裁定不在位")
    # 29 条处置的定稿是缺口清单的唯一来源；缺件即拒绝出件。
    if not C1_FINAL.exists() or not C1_WORKSHEET.exists():
        raise SystemExit("缺少 29 条处置定稿（p4-c1-disposition-final.json / c1ruled 工作表）")
    c1_final = load(C1_FINAL)
    unfilled = [
        row["serial"]
        for row in c1_final["dispositions"]
        if row["disposition"] not in ("covered_by_candidate", "no_candidate")
    ]
    if unfilled:
        raise SystemExit(f"29 条处置未定稿：{unfilled}")
    return {
        "schema_version": "items-p5-release-record-1",
        "id": "109-p5-release-round3-pool",
        "created_on": CREATED_ON,
        "model_calls": 0,
        "production_pg_writes": 0,
        "status": "draft_pending_human_signature",
        "title": "items 门评分（round-3 单池）与放行依据",
        "basis": {
            "gate": {"path": str(GATE_V3.relative_to(ROOT)), "sha256": sha256(GATE_V3)},
            "contract": {
                "path": str(CONTRACT_V43.relative_to(ROOT)),
                "sha256": sha256(CONTRACT_V43),
                "role": "material_items",
            },
            "gold": {"path": str(GOLD.relative_to(ROOT)), "sha256": sha256(GOLD)},
            "candidate_set_u_authored": {
                "path": str(AUTHORED_SET.relative_to(ROOT)),
                "sha256": sha256(AUTHORED_SET),
            },
            "scoreable_copy": {
                "path": str(SCOREABLE_COPY.relative_to(ROOT)),
                "sha256": sha256(SCOREABLE_COPY),
                "derivation": "唯一机械处置：8 行 duplicate 的 matched_gold_id 置 null（装配器拒收该组合）；其余字段 0 差异",
            },
            "gap_analysis": (
                {"path": str(GAP_ANALYSIS.relative_to(ROOT)), "sha256": sha256(GAP_ANALYSIS)}
                if gaps
                else None
            ),
            "c1_disposition_superseded": (
                {
                    "path": str(OUT_C1.relative_to(ROOT)),
                    "sha256": sha256(OUT_C1),
                    "role": "assistant 机械初判（阈值 0.55）——已被 U 裁定取代，字节保留供审计",
                }
                if c1
                else None
            ),
            "c1_disposition_final": {
                "path": str(C1_FINAL.relative_to(ROOT)),
                "sha256": sha256(C1_FINAL),
                "role": "U 具名裁定后的定稿；29 条处置的唯一权威来源",
            },
            "c1_ruled_worksheet": {
                "path": str(C1_WORKSHEET.relative_to(ROOT)),
                "sha256": sha256(C1_WORKSHEET),
                "role": "disposition 已落回器件原意位置（工作表 checklist）的修订版",
            },
        },
        "mode": "structured_scoring.MatchingMode.ADJUDICATED（只消费人工裁定映射，零金标注入）",
        "gate_reading": {
            "rate_gate_passed": score["rate_gate_passed"],
            "live_trial_ready": score["live_trial_ready"],
            "rate_blockers": score["rate_blockers"],
            "readiness_blockers": score["readiness_blockers"],
            "pilot_policy_blockers": score["pilot_policy_blockers"],
            "items_role": score["items"],
            "per_source": score["per_source"],
            "criteria": score["criteria"],
            "predicate_note": (
                "accepted_records_per_source 按评分器实现 = 该源 matched 数"
                "（plugins/corpus/structured_scoring.py:1218）；"
                "72 号终局记录里的 accepted 读法（matched+correct_extra）不是评分器口径，本件不采用"
            ),
            "two_booleans": (
                "rate_gate_passed 是唯一的契约判定；live_trial_ready / readiness_blockers 是"
                "就绪前置（本件未接线到本轮运行，逐字录出仅供参考），不得互相代替"
            ),
        },
        "reading_layers": {
            "why": (
                "同一份已签集合里，合同层（评分器布尔）与判定轴层（预注册 v2 reading_axes）不必同义；"
                "本件把三层逐字并列登记，不把其中任何一层说成另一层"
            ),
            "layer_1_contract_boolean": {
                "value": score["rate_gate_passed"],
                "blockers": score["rate_blockers"],
                "meaning": "评分器 rate_gate_passed，逐字照录；含条数下限与 critical 派生项",
            },
            "layer_2_derived_count_floor": score["count_floor_derivation"],
            "layer_3_judgement_axes": {
                "in_verdict": load(PREREG_V2)["reading_axes"]["primary"],
                "diagnostic_only": load(PREREG_V2)["reading_axes"]["diagnostic_only"],
                "outcome": score["criteria_axes_outcome"],
                "sole_failing_axis": "sentinel_assertions（缺 NT-I43）",
                "precedent": {
                    "path": str(CLAIMS_PREREG_99.relative_to(ROOT)),
                    "sha256": sha256(CLAIMS_PREREG_99),
                    "what": (
                        "claims 侧已签 v3 用 reading_axes.in_verdict（4 项）+ excluded 登记"
                        "『accepted 条数下限不参与读数』（95 号 v2 教训）；items 侧预注册 v2 同旨"
                    ),
                },
            },
            "convergence": (
                "三层读法各自的未达标项：合同层 2 类 blocker（哨兵 + 条数下限，critical 项与哨兵同源）；"
                "派生复算层 1 项（哨兵）；判定轴层 1 项（哨兵）⇒ **三读在『唯一实质未达标 = 哨兵 NT-I43』上收敛**"
            ),
            "not_a_relaxation": (
                "本层不修改合同 v4.3 任何字节、不改评分器、不改阈值；只是把合同的条数下限按其自身的派生规模复算一次，"
                "并把『均分假设』这一来源登记出来"
            ),
            "ratification": {
                "path": str(C1_RATIFICATION.relative_to(ROOT)),
                "sha256": sha256(C1_RATIFICATION),
                "status": ratification["status"],
                "u_statement": ratification["u_statement"],
                "meaning": (
                    "本读法已由 U 认可（会话口谕落成记录，签署栏留空）；"
                    "P5 判档措辞据此写成『轴内 1 项未达标（哨兵）』并并列保留合同层布尔"
                ),
            },
        },
        "verdict_reading": {
            "gate": "FAIL（如实读数，不得读作 PASS）",
            "tier": "判档 FAIL（单轴）：判定轴 5 项中 4 项达标、1 项（哨兵 NT-I43）未达标",
            "contract_layer_boolean": {
                "rate_gate_passed": score["rate_gate_passed"],
                "status": "逐字保留为合同层读数，不参与判档措辞",
            },
            "what_this_record_does_not_claim": [
                "不主张质量达标",
                "不主张门通过",
                "不主张缺口清单为等价替代",
                "不主张 rate_gate_passed 为 true",
            ],
            "what_it_does_claim": (
                "候选集可评分、可复算，缺口已枚举；判档按轴读为单轴未达标（依据见 reading_layers 与其 ratification）；"
                "发布依据另立（见下）"
            ),
        },
        "publication_basis": {
            "authority": "72 号 terminal-decision.json:178 / corrections.md:53 —— 发布标准（结构完备性）与门阈值/金标解耦，store 对 gold/recall/assertion 零引用；按 U 裁定走『显式缺口』路线",
            "reading": "发布理由写『结构完备 + coverage 补全 + 缺口清单明示』，不写『门 PASS』",
            "route": "U 2026-10-15 15:24 裁定『乙』：门判档按 round-3 单池如实读数；跨轮累积读数为登记对照、不是判定池",
        },
        "explicit_gaps": {
            "uncovered_gold": score["missing"],
            "unmatched_critical_gold": score["unmatched_critical"],
            "c1_no_candidate": [
                {
                    "serial": row["serial"],
                    "c1_candidate_id": row["c1_candidate_id"],
                    "claim_text": row["claim_text"],
                    "provenance": row["provenance"],
                }
                for row in c1_final["dispositions"]
                if row["disposition"] == "no_candidate"
            ],
            "c1_no_candidate_note": (
                "12 条由 U 具名裁定（口径：语义相同即算，不看字面相似度）。"
                "其中 U 显式点名的 5 条（#2/#9/#17/#20/#24）与未点名、按机械初判落档并标 "
                "confirmed_by_omission 的 7 条（#7/#12/#13/#14/#19/#27/#28）分列 provenance，"
                "U 可随时更正后者。发布件须逐条列出，不得只写总数。"
            ),
        },
        "next_step": {
            "p6": "structured/cli.py --import-items-artifact → plan_batch(imported_material_items=…) → publish_semantic 全门 → 生产 store 两源 material_items coverage missing→complete → 查询验收",
            "p7": "web items 查询端点 + 常驻测试 + 落地记录",
            "boundary": "零调用、不写生产 PG（沿用 108 号边界）",
        },
        "countersignature": {
            "required": True,
            "status": "pending_human_signoff",
            "reviewer": None,
            "adjudicator": None,
            "signed_on": None,
        },
        "u_rulings": {
            "record": {"path": str(U_RULINGS.relative_to(ROOT)), "sha256": sha256(U_RULINGS)},
            "status": load(U_RULINGS)["status"],
            "items": [
                {
                    "id": item["id"],
                    "subject": item["subject"],
                    "u_statement": item["verbatim"],
                    "decision": item["decision"],
                }
                for item in load(U_RULINGS)["rulings"]
            ],
            "reading_effect": (
                "R3 维持 NT-I46/I47 ⇒ 召回 41/48 不变、判档 tier 不变；"
                "R2 确认署名 ⇒ P4 署名出处项闭合；"
                "R1 不授权机械裁定 ⇒ 15 条由 U 亲判；U 已逐条给方向，落档见 c1_ruling_record"
            ),
            "c1_ruling_record": {
                "path": str(C1_FINAL.relative_to(ROOT)),
                "sha256": sha256(C1_FINAL),
                "u_ruling_verbatim": load(C1_FINAL)["u_ruling_verbatim"],
                "summary": load(C1_FINAL)["summary"],
                "effect": "P4 全量闭合：候选集具名 + 29 条处置定稿（covered 17 / no_candidate 12）",
            },
        },
        "untouched": [
            "U 候选集、92 号登记件、预注册 v2、冻结件、已签门 v3/契约 v4.3、83–108 号产物：字节全未动",
            "未写生产 PG、未发布任何东西、未代签",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    score = score_pool()
    c1 = build_c1_ledger()
    c1_text = json.dumps(c1, ensure_ascii=False, indent=2) + "\n"
    # The release record cites the C1 ledger by hash, so the ledger must exist on disk first.
    if not args.no_write:
        write_once(OUT_C1, c1_text, reason="C1 29 条处置落账", allow_overwrite=args.force)
    release = build_release(score)
    release_text = json.dumps(release, ensure_ascii=False, indent=2) + "\n"
    if args.no_write:
        print(release_text)
        return 0
    write_once(OUT_RELEASE, release_text, reason="109 号 P5 放行件草案", allow_overwrite=args.force)
    print(f"wrote {OUT_C1.name}")
    print(f"wrote {OUT_RELEASE.name}")
    print(
        json.dumps(
            {
                "rate_gate_passed": score["rate_gate_passed"],
                "rate_blockers": score["rate_blockers"],
                "unmatched_critical": score["unmatched_critical"],
                "c1": c1["summary"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
