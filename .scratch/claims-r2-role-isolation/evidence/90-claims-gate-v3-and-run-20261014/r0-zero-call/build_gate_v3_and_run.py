"""Claims gate v3 draft + the first honest claims run under the signed caliber.

Two jobs in one zero-call driver (they must agree byte-for-byte, so they are built together):

1. **Run**: assemble the frozen P1R5 claims adjudications through the signed read path
   (contract v4.4) and score them with the signed gate requirements, under three variants of
   the still-undecided accepted-count floors (a = items 40/20, b = scaled 17/8, c = machine
   approximation of "diagnostic only" = minimum 1/1).
2. **Gate v3 draft**: preregister the caliber + dual thresholds and embed the measured run, so
   the artifact states what it was measured against.

Adapter decisions recorded in the output (they are measurements, not inventions):
* ``stage`` — the pool's vocabulary is ``human_adjudicated_candidate`` (110/110); it is presented
  as the validated slice (raw slice empty).
* ``source_id`` — rows carry no source_id; the doc -> source mapping is derived from the 20
  matched rows and asserted functional and total over the two docs.
* C1 role scope — candidates with ``kind == "opinion"`` or no value are adjudicated
  ``out_of_scope`` and listed for the items/relations-side coverage registration.

Usage:
    python build_gate_v3_and_run.py [--no-write] [--force]
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]  # .scratch/claims-r2-role-isolation
REPO_ROOT = ROOT.parents[1]
sys.path.insert(0, str(REPO_ROOT))

from plugins.corpus.adjudication_assembly import ABSENT, assemble_scoring_input  # noqa: E402
from plugins.corpus.structured_scoring import (  # noqa: E402
    CandidateRecord,
    ContractGateRequirements,
    GoldRecord,
    MatchingMode,
    RecordOrigin,
    Role,
    load_contract_gate_requirements,
    score_structured_quality,
)
from tools.check_claims_gate import recompute_calibers  # noqa: E402

RUN_ON = "2026-10-14"
SIGNED_CONTRACT = (
    ROOT
    / "evidence/88-claims-contract-v44-signed-20261014/r0-zero-call/scoring-contract-v4.4.json"
)
POOL = (
    ROOT
    / "evidence/17-structured-extraction-convergence-closure-20261009"
    / "p1r5-claims-adjudication-v2/candidate-adjudications.signed.json"
)
GOLD = ROOT / "evidence/10-quality-gold-freeze-20261008-r2/frozen-gold.json"
COVERAGE_V1 = (
    ROOT / "evidence/83-claims-scope-gate-draft-20261014/r0-zero-call/coverage-measurements.json"
)
GATE_V2_SUPERSEDED = (
    ROOT / "evidence/84-claims-gate-v2-draft-20261014/r0-zero-call/claims-gate-v2.proposed.json"
)
C2_MEASUREMENT = (
    ROOT / "evidence/88-claims-contract-v44-signed-20261014/r0-zero-call/c2-measurement.json"
)
GATE_V3_SIGNOFF = "claims-gate-v3-signoff.md"

INPUTS = {
    "signed_scoring_contract_v4.4": SIGNED_CONTRACT,
    "p1r5_candidate_adjudications_signed": POOL,
    "frozen_gold_r2": GOLD,
    "coverage_measurements_v1": COVERAGE_V1,
    "claims_gate_v2_superseded": GATE_V2_SUPERSEDED,
    "c2_measurement": C2_MEASUREMENT,
}

FLOOR_VARIANTS = {
    "a_items_40_20": {"accepted_records_total_min": 40, "accepted_records_per_source_min": 20},
    "b_scaled_17_8": {"accepted_records_total_min": 17, "accepted_records_per_source_min": 8},
    "c_diagnostic_min": {"accepted_records_total_min": 1, "accepted_records_per_source_min": 1},
}
FLOOR_VARIANT_NOTES = {
    "a_items_40_20": "平移 items 门 v3 原值；未按 claims 的 20 条目标缩放",
    "b_scaled_17_8": "按 0.85 × 20 = 17 与两源各 0.85 × 10 = 8.5 → 8 派生",
    "c_diagnostic_min": "机器近似：下限取契约允许的最小值 1/1（等价于不 binding）；"
    "真实实现需把该轴改为诊断计数，属契约修订",
}
FIELD_TO_CARRIER_KEY = {
    "subject": "subject",
    "metric": "metric",
    "period": "period_raw",
    "unit": "unit_raw",
    "value": "value_text",
    "factuality": "kind",
    "qualifier": "qualifiers",
}
RELEASE_LINE = {"candidate_precision_min": 0.6, "per_source_precision_min": 0.55}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def is_role_external(claim: dict[str, Any]) -> bool:
    """Signed C1 role scope: claims carries metric assertions only."""
    return claim.get("kind") == "opinion" or claim.get("value_text") in (None, "")


def build_gold() -> tuple[GoldRecord, ...]:
    rows = [r for r in load(GOLD)["records"] if r["role"] == "claims"]
    records = []
    for row in rows:
        fields = tuple(
            sorted(
                (str(key), str(value))
                for key, value in (row.get("semantic_fields") or {}).items()
                if str(value) != ""
            )
        )
        records.append(
            GoldRecord(
                record_id=row["record_id"],
                role=Role.CLAIMS,
                source_id=row["source_id"],
                origin=RecordOrigin(str(row.get("origin") or "llm_prose")),
                semantic_fields=fields or (("value", row["record_id"]),),
            )
        )
    return tuple(records)


def doc_to_source(pool: dict[str, Any], gold: tuple[GoldRecord, ...]) -> dict[str, str]:
    """Derive doc_id -> source_id from the matched rows; assert functional and total."""
    by_id = {item.record_id: item.source_id for item in gold}
    mapping: dict[str, set[str]] = {}
    for row in pool["adjudications"]:
        if row.get("judgement") != "matched":
            continue
        doc = str(row["original_candidate"]["claim"].get("doc_id"))
        gold_id = str(row.get("matched_gold_id"))
        mapping.setdefault(doc, set()).add(by_id[gold_id])
    ambiguous = {doc: sorted(sources) for doc, sources in mapping.items() if len(sources) != 1}
    if ambiguous:
        raise SystemExit(f"doc->source mapping is not functional: {ambiguous}")
    expected_docs = {
        str(row["original_candidate"]["claim"].get("doc_id")) for row in pool["adjudications"]
    }
    if set(mapping) != expected_docs:
        raise SystemExit("doc->source mapping does not cover every candidate doc_id")
    return {doc: next(iter(sources)) for doc, sources in mapping.items()}


def catalog_entry(claim: dict[str, Any]) -> dict[str, Any]:
    entry: dict[str, Any] = {}
    for carrier_key in FIELD_TO_CARRIER_KEY.values():
        value = claim.get(carrier_key)
        entry[carrier_key] = ABSENT if value in (None, "") else str(value)
    entry["origin"] = "llm_prose"
    return entry


def declared_fields(entry: dict[str, Any]) -> dict[str, str]:
    declared = {field: entry[key] for field, key in FIELD_TO_CARRIER_KEY.items()}
    for human_only in ("attribution", "perspective", "source_stance", "estimate_status"):
        declared[human_only] = ABSENT
    return declared


def build_adjudications(pool: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    sources = doc_to_source(pool, build_gold())
    adjudications: list[dict[str, Any]] = []
    catalog: dict[str, Any] = {}
    moved_out: list[str] = []
    for row in pool["adjudications"]:
        claim = row["original_candidate"]["claim"]
        candidate_id = row["candidate_id"]
        source_id = sources[str(claim.get("doc_id"))]
        entry = catalog_entry(claim)
        catalog[candidate_id] = entry
        role_external = is_role_external(claim)
        if role_external:
            moved_out.append(candidate_id)
        adjudications.append(
            {
                "candidate_id": candidate_id,
                "stage": "validated",
                "role": "claims",
                "source_id": source_id,
                "original_candidate": {
                    "role": "claims",
                    "source_id": source_id,
                    "origin": "llm_prose",
                },
                "judgement": "out_of_scope" if role_external else str(row["judgement"]),
                "matched_gold_id": row.get("matched_gold_id"),
                "canonical_observed_fields": declared_fields(entry),
                "reviewer": str(row.get("reviewer") or "xyl"),
                "reason": "C1 role scope + signed adjudication; deterministic carriers recomputed",
                "evidence": str(row.get("decision_basis") or "signed P1R5 adjudication"),
            }
        )
    return adjudications, catalog, moved_out


def run_variants(
    gold: tuple[GoldRecord, ...], assembly: Any, base: ContractGateRequirements
) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for name, floors in FLOOR_VARIANTS.items():
        requirements = dataclasses.replace(base, **floors)
        report = score_structured_quality(
            gold,
            matching_mode=MatchingMode.ADJUDICATED,
            # The pool has a single adjudication pass, so both slices carry the same tuples
            # (the scorer requires validated candidates to be unchanged raw candidates).
            raw_candidates=assembly.validated,
            validated_candidates=assembly.validated,
            raw_mappings=assembly.mappings,
            validated_mappings=assembly.mappings,
            gate_requirements=requirements,
        )
        metrics = report.validated.role(Role.CLAIMS)
        matched = set(report.validated.matched_gold_ids)
        sentinels = list(requirements.high_risk_item_assertions_required)
        per_source_recall = {}
        for source in sorted({item.source_id for item in gold}):
            total = [item for item in gold if item.source_id == source]
            hit = [item for item in total if item.record_id in matched]
            per_source_recall[source[:20]] = f"{len(hit)}/{len(total)}"
        results[name] = {
            "floors": floors,
            "note": FLOOR_VARIANT_NOTES[name],
            "target_recall": f"{metrics.tp}/{metrics.tp + metrics.fn}",
            "candidate_precision": (
                f"{metrics.tp + metrics.correct_extra}/"
                f"{metrics.tp + metrics.correct_extra + metrics.fp} = "
                f"{(metrics.tp + metrics.correct_extra) / (metrics.tp + metrics.correct_extra + metrics.fp):.4f}"
            ),
            "ledger": {
                "tp": metrics.tp,
                "correct_extra": metrics.correct_extra,
                "fp_includes_duplicates": metrics.fp,
                "duplicate_fp": metrics.duplicate_fp,
                "fn": metrics.fn,
            },
            "per_source_recall": per_source_recall,
            "sentinels": {
                "required": sentinels,
                "matched": [key for key in sentinels if key in matched],
            },
            "rate_gate_passed": report.gate.rate_gate_passed,
            "rate_blockers": list(report.gate.rate_blockers),
            "readiness_blockers": list(report.gate.readiness_blockers),
            "live_trial_ready": report.gate.live_trial_ready,
        }
    return results


def build() -> dict[str, Any]:
    contract = load(SIGNED_CONTRACT)
    pool = load(POOL)
    gold = build_gold()
    base = load_contract_gate_requirements(SIGNED_CONTRACT, role=Role.CLAIMS)
    adjudications, catalog, moved_out = build_adjudications(pool)
    assembly = assemble_scoring_input(adjudications, catalog=catalog, allowed_source_ids=None)
    run = run_variants(gold, assembly, base)
    calibers = recompute_calibers(pool, load(COVERAGE_V1), load(GOLD))
    d2 = calibers["D2_in_role_only"]

    per_source_precision = {
        source: ratio["display"] for source, ratio in d2["per_source_precision"].items()
    }
    release_check = {
        "candidate_precision_min": RELEASE_LINE["candidate_precision_min"],
        "measured_candidate_precision": d2["precision_contract_formula"]["value"],
        "candidate_axis_passes": d2["precision_contract_formula"]["value"]
        >= RELEASE_LINE["candidate_precision_min"],
        "per_source_precision_min": RELEASE_LINE["per_source_precision_min"],
        "measured_per_source_precision": per_source_precision,
        "per_source_axis_passes": all(
            entry["value"] >= RELEASE_LINE["per_source_precision_min"]
            for entry in d2["per_source_precision"].values()
        ),
        "per_source_axis_note": (
            "放行线的分源轴是**分源精度**；契约的六项里没有分源精度轴，"
            "故该轴当前只能报告、不能 gating（须契约修订才能生效）"
        ),
    }
    gate = {
        "schema_version": "claims-gate-v3-preregistration-1",
        "status": "draft_pending_human_signature",
        "created_on": RUN_ON,
        "role": "claims",
        "zero_model_calls": True,
        "purpose": "在已签 claims 契约 v4.4 的读数与角色范围下，为 claims 角色预注册度量与双线阈值",
        "supersedes": {
            "path": str(GATE_V2_SUPERSEDED.relative_to(ROOT)),
            "sha256": sha256(GATE_V2_SUPERSEDED),
            "status_at_supersede": load(GATE_V2_SUPERSEDED)["status"],
            "reason": "v2 的两处缺陷：D4 行不完整；『实现公式 56/107』为读数错误（C2 已更正）",
        },
        "authority": {
            "signed_contract": {
                "path": str(SIGNED_CONTRACT.relative_to(ROOT)),
                "sha256": sha256(SIGNED_CONTRACT),
                "status": contract["status"],
                "signed_by": contract["signoff"]["signed_by"],
                "signed_on": contract["signoff"]["signed_on"],
            },
            "role_sections_claims": contract["role_sections"]["claims"],
            "thresholds_source": "契约 v4.4 threshold_source.effective（六项，逐字沿用 v4.3）",
            "dispositions": contract["signoff_dispositions"],
        },
        "calibers": calibers,
        "false_positive_decomposition": {
            **load(GATE_V2_SUPERSEDED)["false_positive_decomposition"],
            "note": "沿用 84/85 号的三分口径（角色外 / 坐标未绑 / 结构齐备不匹配）",
            "source": str(GATE_V2_SUPERSEDED.relative_to(ROOT)),
        },
        "measured_run": {
            "pool": {
                "path": str(POOL.relative_to(ROOT)),
                "sha256": sha256(POOL),
                "candidates_total": len(pool["adjudications"]),
                "stage_vocabulary": {"human_adjudicated_candidate": len(pool["adjudications"])},
            },
            "adapter_decisions": {
                "stage": "池只有一轮裁定；raw 与 validated 两个切片携带同一组元组",
                "source_id": "doc→source 由 20 条 matched 派生，函数式且覆盖两个 doc（已断言）",
                "c1_role_scope": (
                    f"{len(moved_out)} 条判为 out_of_scope（kind==opinion 或无 value），"
                    "须在 material_items/relations 侧登记覆盖"
                ),
                "doc_to_source": doc_to_source(pool, gold),
                "caliber_key_alignment": (
                    "calibers 的分源键用 doc_id 前 12 位（f16e7fde9553/dca4bad7f85b），"
                    "run 的分源键用 source sha256；两者对应关系见 doc_to_source"
                ),
                "fraction_display": (
                    "gate blocker 里的 17/27 是 51/81 的约分（Fraction 规范化），同一数值"
                ),
            },
            "readiness_note": (
                "readiness/live_trial_ready 走 harness 默认值（全 False），其中"
                "insufficient_sample:material_items|material_relations 是跨角色样本门，"
                "claims-only 运行按设计必然触发；本轮的判定量是 rate_gate_passed"
            ),
            "assembled": {
                "validated_candidates": len(assembly.validated),
                "mappings": len(assembly.mappings),
                "out_of_scope": len(assembly.out_of_scope),
                "out_of_scope_ids": list(assembly.out_of_scope),
            },
            "variants": run,
        },
        "thresholds": {
            "target_line": {
                "target_recall_overall_min": float(base.target_recall_overall_min),
                "target_recall_per_source_min": float(base.target_recall_per_source_min),
                "candidate_precision_min": float(base.candidate_precision_min),
                "unresolved_candidates_max": base.unresolved_candidates_max,
                "sentinels_required": list(base.high_risk_item_assertions_required),
                "accepted_records_total_min": base.accepted_records_total_min,
                "accepted_records_per_source_min": base.accepted_records_per_source_min,
                "accepted_floor_status": "未按 claims 定值；三个变体的实测见 measured_run.variants",
                "granularity_warning": "目标仅 20 条 ⇒ 0.85 ≙ 17/20，每错 1 条 −5.0pp",
            },
            "release_line": {"status": f"signed_{RUN_ON}_xyl（契约 claims_thresholds）", **release_check},
            "unreachable_registration": {
                "target_line_on_frozen_pool": "不可达",
                "evidence": f"D2 分子上限 {d2['precision_contract_formula']['display']} < 0.80；"
                f"分源精度 {per_source_precision}",
                "implication": "要达目标线须另立授权的重跑（新池），不得通过改分母实现",
            },
        },
        "open_decisions": [
            {
                "id": "D-1 accepted 总数/分源下限",
                "question": "claims 的 accepted_records_total_min / per_source_min 取哪套？",
                "measured_verdicts": {
                    name: value["rate_gate_passed"] for name, value in run.items()
                },
                "options": {
                    "a": "平移 items 门 v3 的 40/20",
                    "b": "按 0.85 × 20 与两源派生 17/8",
                    "c": "不设数值，仅作诊断计数（须契约修订）",
                },
            },
            {
                "id": "D-2 分源精度轴",
                "question": "放行线的分源轴（0.55）在六项里没有对应字段，是否新增该轴？",
                "measured": per_source_precision,
            },
        ],
        "prior_record_updates": [
            {
                "record": "evidence/89-claims-v44-signed-landing-20261014/r0-zero-call",
                "line": "still_pending: 『claims 门 v3（…）并具名签认』",
                "now": "v3 草案已产出（本件），仍待具名签认",
            },
            {
                "record": "evidence/89-claims-v44-signed-landing-20261014/r0-zero-call",
                "line": "still_pending: 『claims 全量实跑：需先建 doc→source_id 映射与 stage 词表适配』",
                "now": "已完成：映射与词表适配落在本件的 adapter_decisions，110 条全量出分见 measured_run",
            },
        ],
        "not_in_scope": [
            "不改 frozen-gold / P1R5 已签裁定 / items 门 v3 / 契约 v4.3 v4.4 字节",
            "不执行模型调用、不重跑抽取、不发布、不进 query/delivery/context_use",
        ],
        "signoff": {
            "reviewer": None,
            "adjudicator": None,
            "signed_on": None,
            "instrument": GATE_V3_SIGNOFF,
        },
    }
    manifest = {
        "schema_version": "claims-gate-v3-manifest-1",
        "status": "draft",
        "created_on": RUN_ON,
        "model_calls": 0,
        "production_pg_access": 0,
        "inputs": {name: sha256(path) for name, path in INPUTS.items()},
        "outputs": {},
        "does_not_touch": [
            str(SIGNED_CONTRACT.relative_to(ROOT)),
            str(GATE_V2_SUPERSEDED.relative_to(ROOT)),
            str(POOL.relative_to(ROOT)),
            str(GOLD.relative_to(ROOT)),
        ],
    }
    return {"gate": gate, "manifest": manifest}


SIGNOFF_MD = """# Claims 门 v3 草案 · 签认件

状态：草稿，**未签认**。以已签契约 v4.4 为唯一权威；不改任何冻结字节；零模型调用。

## 一、本次实测（首个在已签读数下跑出的 claims 分）

口径 C1（角色范围）下：候选 {kept} 条（判出角色外 {moved} 条已登记待覆盖），
召回 {recall}、精度 {precision}；分源精度 {per_source}；哨兵 {sentinels}。

| accepted 下限变体 | 目标线判定 | 卡点 |
|---|---|---|
{rows}

## 二、双线阈值

- **目标线（不动）**：0.85 / 0.80 / 0.80 / 0 + 哨兵 NT-C11/C12/C13 —— 冻结池上**不可达**（D2 上限 {precision}）。
- **放行线（C5 已签）**：精度 0.60（实测 {precision} ⇒ {cand_ok}）；分源精度 0.55（实测 {per_source} ⇒ {src_ok}，
  但六项里无该轴，须契约修订才能 gating）。

## 三、待裁两项

- **D-1 accepted 总数/分源下限**：a 平移 items 40/20 ｜ b 由 0.85×20 派生 17/8 ｜ c 改为诊断（须修契约）。
- **D-2 分源精度轴**：是否为放行线新增该轴。

## 四、硬约束

- 目标线是"目标"，放行线是"功能线"，二者并列登记；**不得用放行线通过宣称质量达标**。
- C1 判出的 {moved} 条角色外候选须在 material_items/relations 侧登记覆盖，不得就地丢弃。

## 签名

reviewer: ____________    adjudicator: ____________    signed_on: ____________
"""


def render_signoff(gate: dict[str, Any], run: dict[str, Any]) -> str:
    d2 = gate["calibers"]["D2_in_role_only"]
    rows = []
    for name, value in run.items():
        blockers = value["rate_blockers"]
        precision_blockers = [b for b in blockers if "candidate_precision" in b]
        floor_blockers = [b for b in blockers if "accepted_records" in b]
        summary = []
        if precision_blockers:
            summary.append(f"精度 {value['candidate_precision']} < 0.80（约分显示 17/27）")
        if floor_blockers:
            summary.append(f"accepted 下限 {len(floor_blockers)} 项不达")
        rows.append(
            f"| {name}（{value['note']}） | {'PASS' if value['rate_gate_passed'] else 'FAIL'} | "
            f"{'；'.join(summary) if summary else '—'} |"
        )
    release = gate["thresholds"]["release_line"]
    return SIGNOFF_MD.format(
        kept=d2["judgements"]["matched"] + d2["judgements"]["correct_extra"]
        + d2["judgements"]["incorrect"] + d2["judgements"]["duplicate"],
        moved=gate["measured_run"]["assembled"]["out_of_scope"],
        recall=d2["target_recall"]["display"],
        precision=d2["precision_contract_formula"]["display"],
        per_source=release["measured_per_source_precision"],
        sentinels=gate["thresholds"]["target_line"]["sentinels_required"],
        rows="\n".join(rows),
        cand_ok="过" if release["candidate_axis_passes"] else "不过",
        src_ok="过" if release["per_source_axis_passes"] else "不过",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    result = build()
    gate = result["gate"]
    outputs = {
        "claims-gate-v3.proposed.json": (
            json.dumps(gate, ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8"),
        "claims-run-record.json": (
            json.dumps(gate["measured_run"], ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8"),
        GATE_V3_SIGNOFF: render_signoff(gate, gate["measured_run"]["variants"]).encode("utf-8"),
    }
    manifest = result["manifest"]
    manifest["outputs"] = {name: hashlib.sha256(data).hexdigest() for name, data in outputs.items()}
    outputs["MANIFEST.json"] = (
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")

    if args.no_write:
        print(json.dumps(gate["measured_run"]["variants"], ensure_ascii=False, indent=2))
        print(f"[no-write] {len(outputs)} outputs computed; nothing written.")
        return 0

    existing = [name for name in outputs if (HERE / name).exists()]
    if existing and not args.force:
        raise SystemExit(f"refusing to overwrite existing outputs {existing}; use --force")
    for name, data in outputs.items():
        (HERE / name).write_bytes(data)
    print(f"wrote {len(outputs)} files to {HERE}")
    print(json.dumps(manifest["outputs"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
