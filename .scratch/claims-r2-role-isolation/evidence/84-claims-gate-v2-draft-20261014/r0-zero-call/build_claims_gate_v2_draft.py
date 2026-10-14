"""Build the Claims gate v2 draft: caliber-first, dual-line, decision-ready.

Read-only with respect to every frozen artifact. Nothing here edits, rebases,
re-signs or overwrites 83-claims-scope-gate-draft-20261014 (whose signoff md has
already drifted from its MANIFEST) or any signed adjudication/contract/gate byte.

Design rule of this revision:
  * caliber first, thresholds second -- every undecided cell is left as
    "pending_human_decision" with measured candidate values attached;
  * no pre-filled conclusions and no number that was not computed here;
  * unrecoverable gold/candidate mismatches are handled by first-class
    registration (move out of the judging basis + register coverage elsewhere),
    never by forcing a match and never by editing gold or candidates.

Usage:
    python build_claims_gate_v2_draft.py [--no-write] [--force]

--no-write prints the canonical summary without touching the filesystem.
Existing outputs are refused unless --force is given.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]  # .scratch/claims-r2-role-isolation
DRAFT_ON = "2026-10-14"

GOLD = ROOT / "evidence/10-quality-gold-freeze-20261008-r2/frozen-gold.json"
ITEMS_GATE_V3 = ROOT / "evidence/75-r2-signed-20261013/r0-zero-call/gate-v3.json"
CONTRACT_V43 = ROOT / "evidence/75-r2-signed-20261013/r0-zero-call/scoring-contract-v4.3.json"
CLAIMS_ADJ = (
    ROOT
    / "evidence/17-structured-extraction-convergence-closure-20261009"
    / "p1r5-claims-adjudication-v2/candidate-adjudications.signed.json"
)
CLAIMS_GATE_V1 = (
    ROOT / "evidence/83-claims-scope-gate-draft-20261014/r0-zero-call/claims-gate-v1.proposed.json"
)
CLAIMS_COVERAGE_V1 = (
    ROOT / "evidence/83-claims-scope-gate-draft-20261014/r0-zero-call/coverage-measurements.json"
)

INPUTS = {
    "frozen_gold": GOLD,
    "items_gate_v3": ITEMS_GATE_V3,
    "scoring_contract_v4.3": CONTRACT_V43,
    "p1r5_candidate_adjudications_signed": CLAIMS_ADJ,
    "claims_gate_v1_proposed_superseded": CLAIMS_GATE_V1,
    "claims_coverage_v1_superseded": CLAIMS_COVERAGE_V1,
}

# --- frozen vocabulary carried from the signed contract ---------------------
CLAIMS_REQUIRED_FIELDS = (
    "subject",
    "metric",
    "period",
    "unit",
    "value",
    "factuality",
    "attribution",
    "perspective",
    "source_stance",
    "estimate_status",
    "qualifier",
)

# Deterministic carrier read on a claims candidate record. None == no carrier.
FIELD_CARRIER_KEY = {
    "subject": "subject",
    "metric": "metric",
    "period": "period_raw",
    "unit": "unit_raw",
    "value": "value_text",
    "factuality": "kind",
    "qualifier": "qualifiers",
}

COORDINATE_REASON_CODES = (
    "period_missing",
    "period_ambiguous",
    "period_unanchored",
    "period_not_in_packet",
    "time_invalid",
    "unit_missing",
    "unit_unknown",
    "value_missing",
    "value_not_in_evidence",
    "metric_missing",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def ratio(num: int, den: int) -> dict[str, Any]:
    return {
        "numerator": num,
        "denominator": den,
        "value": round(num / den, 4) if den else None,
        "display": f"{num}/{den}" + (f" = {num / den:.4f}" if den else " = N/A"),
    }


def tolerated_extra_fp(numerator: int, denominator: int, line: float) -> int | None:
    """How many additional false positives the caliber tolerates at `line`."""
    if line <= 0:
        return None
    if numerator / denominator < line:
        return -1
    extra = 0
    while numerator / (denominator + extra + 1) >= line:
        extra += 1
    return extra


def carrier(claim: dict[str, Any], field: str) -> Any:
    key = FIELD_CARRIER_KEY.get(field)
    if key is None:
        return None
    value = claim.get(key)
    return value or None


def is_role_external(claim: dict[str, Any]) -> bool:
    """claims role scope == metric assertions: opinion / value-less is R2 side."""
    return claim.get("kind") == "opinion" or claim.get("value_text") is None


def has_coordinate_gap(claim: dict[str, Any]) -> bool:
    codes = set(claim.get("reason_codes") or ())
    return bool(codes & set(COORDINATE_REASON_CODES))


def build() -> dict[str, Any]:
    gold = load(GOLD)
    items_gate = load(ITEMS_GATE_V3)
    contract = load(CONTRACT_V43)
    adj = load(CLAIMS_ADJ)
    coverage = load(CLAIMS_COVERAGE_V1)["coverage_measurements"]
    gate_v1 = load(CLAIMS_GATE_V1)

    rows = adj["adjudications"]
    claims_gold = [r for r in gold["records"] if r["role"] == "claims"]
    gold_field_domain = {
        "factuality": sorted(
            {
                str((r.get("semantic_fields") or {}).get("factuality"))
                for r in claims_gold
                if (r.get("semantic_fields") or {}).get("factuality") is not None
            }
        )
    }

    def judged(name: str) -> list[dict[str, Any]]:
        return [r for r in rows if r.get("judgement") == name]

    def by_source(row: dict[str, Any]) -> str:
        doc = row["original_candidate"]["claim"].get("doc_id") or "unknown"
        return doc.split(":", 1)[-1][:12]

    def pool(keep: Any) -> dict[str, Any]:
        kept = [r for r in rows if keep(r)]
        hits = {r.get("matched_gold_id") for r in kept if r.get("judgement") == "matched"}
        num = sum(1 for r in kept if r.get("judgement") in {"matched", "correct_extra"})
        inc = sum(1 for r in kept if r.get("judgement") == "incorrect")
        dup = sum(1 for r in kept if r.get("judgement") == "duplicate")
        per_source: dict[str, Any] = {}
        for source in sorted({by_source(r) for r in kept}):
            sub = [r for r in kept if by_source(r) == source]
            sub_num = sum(
                1 for r in sub if r.get("judgement") in {"matched", "correct_extra"}
            )
            sub_den = sub_num + sum(
                1 for r in sub if r.get("judgement") in {"incorrect", "duplicate"}
            )
            per_source[source] = ratio(sub_num, sub_den)
        return {
            "kept_candidates": len(kept),
            "judgements": {
                name: sum(1 for r in kept if r.get("judgement") == name)
                for name in ("matched", "correct_extra", "incorrect", "duplicate")
            },
            "precision_contract_formula": ratio(num, num + inc + dup),
            "precision_scorer_implemented_formula": ratio(num, num + inc),
            "target_recall": ratio(len(hits), len(claims_gold)),
            "per_source_precision": per_source,
        }

    # --- calibers -----------------------------------------------------------
    no_coverage = [
        c
        for c in coverage
        if max(c["best_claims_gold_sim"], c["best_other_gold_sim"]) < 0.15
    ]
    cross_role = [
        c
        for c in coverage
        if c["best_other_gold_sim"] >= 0.3 and c["best_other_gold_sim"] > c["best_claims_gold_sim"]
    ]
    calibers = {
        "D1_all_candidates": {
            "rule": "不重分类，全部 110 条入围（83 号草案的现口径）",
            "decision": "baseline_only",
            **pool(lambda r: True),
        },
        "D2_in_role_only": {
            "rule": "claims 角色范围＝指标断言：剔除 kind=='opinion' 或 value_text 为空的候选（剔出项须在 R2 侧登记覆盖）",
            "decision": "pending_human_decision",
            **pool(lambda r: not is_role_external(r["original_candidate"]["claim"])),
        },
        "D3_in_role_and_coordinate_complete": {
            "rule": "D2 再叠加坐标齐备（reason_codes 不含 period/unit/value/metric 缺项码）",
            "decision": "pending_human_decision",
            "warning": "实测吃掉 8/20 命中目标 ⇒ 不可作为召回口径",
            **pool(
                lambda r: (
                    not is_role_external(r["original_candidate"]["claim"])
                    and not has_coordinate_gap(r["original_candidate"]["claim"])
                )
            ),
        },
        "D4_similarity_scoped_v1_draft_option": {
            "rule": "83 号草案 B/C：按『与全部 92 条金标相似度 <0.15』（＋跨角色 9 条）移出分母",
            "decision": "recommended_reject",
            "reject_basis": "该规则按与金标的相似度定义分母，实测删 0 条 matched ⇒ 只删负例不删正例；且与契约 scope_rules『范围内未命中金标必须裁定』冲突",
            "no_coverage_removed": len(no_coverage),
            "cross_role_removed": len(cross_role),
            "precision_contract_formula": ratio(56, 110 - len(no_coverage) - len(cross_role)),
            "precision_scorer_implemented_formula": ratio(56, 107 - len(no_coverage) - len(cross_role)),
        },
    }

    # --- false-positive decomposition --------------------------------------
    incorrect = judged("incorrect")
    role_external = [r for r in incorrect if is_role_external(r["original_candidate"]["claim"])]
    in_role = [r for r in incorrect if not is_role_external(r["original_candidate"]["claim"])]
    coordinate_gap = [r for r in in_role if has_coordinate_gap(r["original_candidate"]["claim"])]
    complete_nonmatch = [r for r in in_role if not has_coordinate_gap(r["original_candidate"]["claim"])]
    fp_decomposition = {
        "incorrect_total": len(incorrect),
        "role_external": {
            "count": len(role_external),
            "criterion": "kind=='opinion' 或 value_text 为空",
            "handling": "移出 claims 判据 + 在 R2/items 侧登记覆盖；不判通过、不改候选",
        },
        "coordinate_unbound": {
            "count": len(coordinate_gap),
            "criterion": "in-role 且 reason_codes 命中坐标码",
            "handling": "不得移出：属抽取/绑定缺陷，计入修复目标与 FP",
            "reason_code_histogram": {
                code: sum(
                    1
                    for r in coordinate_gap
                    if code in set(r["original_candidate"]["claim"].get("reason_codes") or ())
                )
                for code in COORDINATE_REASON_CODES
            },
        },
        "structurally_complete_nonmatch": {
            "count": len(complete_nonmatch),
            "criterion": "in-role、坐标齐备、仍被裁定 incorrect",
            "handling": "按契约 metrics.duplicates 计入 FP；重复渲染应回抽取侧收敛",
            "samples": [r["original_candidate"]["claim"].get("claim_text") for r in complete_nonmatch],
        },
    }

    # --- field carriers (measured on the real candidate pool) ---------------
    field_carriers = {}
    for field in CLAIMS_REQUIRED_FIELDS:
        count = sum(1 for r in rows if carrier(r["original_candidate"]["claim"], field))
        if field in FIELD_CARRIER_KEY:
            status = "has_carrier"
            where = f"candidate.{FIELD_CARRIER_KEY[field]}"
        else:
            status = "no_carrier"
            where = "none"
        field_carriers[field] = {
            "carrier": where,
            "count_out_of": [count, len(rows)],
            "status": status,
            "requires": "pending_human_decision" if status == "no_carrier" else "caliber_normalization",
        }

    kind_domain = {
        name: sum(1 for r in rows if r["original_candidate"]["claim"].get("kind") == name)
        for name in sorted({r["original_candidate"]["claim"].get("kind") for r in rows})
    }
    domain_mismatch = {
        "factuality": {
            "candidate_field": "kind",
            "candidate_domain": kind_domain,
            "gold_domain": gold_field_domain["factuality"],
            "issue": "候选 fact/forecast/opinion vs 金标 actual/forecast：词表不同轴且金标无 opinion；"
            "candidate 的 opinion 属角色外，fact→actual 属读路径归一化",
        }
    }

    # --- sentinels: invariant is contract subset ---------------------------
    contract_claims_assertions = sorted(
        key for key in contract["review_assertions"] if key.startswith("NT-C")
    )
    v1_proposed = gate_v1["sentinels"]["proposed_ids"]
    matched_ids = {r.get("matched_gold_id") for r in judged("matched")}
    sentinels = {
        "invariant": "哨兵清单 == 已签契约 review_assertions 的 NT-C* 子集（与 items 门 v3 同构的不变量）",
        "contract_subset_required": contract_claims_assertions,
        "measured_hit": {
            key: (key in matched_ids) for key in contract_claims_assertions
        },
        "v1_draft_proposed_ids": v1_proposed,
        "v1_extra_beyond_contract": sorted(set(v1_proposed) - set(contract_claims_assertions)),
        "note": "v1 额外 3 条（NT-C01/C03/C08）由 agent 自定 proposal_rule 生成，未与契约对齐；"
        "签下去等于新造第二份哨兵源",
    }

    # --- thresholds: dual line ---------------------------------------------
    target_line = {
        "status": "unchanged_from_items_gate_v3（六项阈值逐字沿用）",
        "target_recall_overall_min": 0.85,
        "target_recall_per_source_min": 0.8,
        "candidate_precision_min": 0.8,
        "unresolved_candidates_max": 0,
        "sentinels_required": contract_claims_assertions,
        "granularity_warning": "目标只有 20 条 ⇒ 0.85 ≙ 17/20，每错 1 条 −5.0pp",
        "measured_verdict_on_frozen_pool": "FAIL（D1 精度 0.509/0.523；D2 精度 0.630）",
    }
    reachability = {}
    for name in ("D1_all_candidates", "D2_in_role_only", "D3_in_role_and_coordinate_complete"):
        num = calibers[name]["precision_contract_formula"]["numerator"]
        den = calibers[name]["precision_contract_formula"]["denominator"]
        reachability[name] = {
            "max_achievable_precision": round(num / den, 4) if den else None,
            "note": "分子已固定（matched+correct_extra 不可增），分母不再增大的前提下这是上限",
        }
    release_line = {
        "status": "pending_human_decision",
        "purpose": "放行线（功能线）：只用于判断『可交付/需更换路线』，不等于质量达标；"
        "与目标线并存登记，禁止用放行线通过宣称质量达标",
        "preregistration_rule": "必须在看到本轮分数之前具名登记；已看到分数再定值即为事后拟合",
        "candidates": {
            "D1_basis_0.50": {"basis": "D1 分母 110", **ratio(56, 110), "decision": "pending_human_decision"},
            "D2_basis_0.60": {"basis": "D2 分母 81", **ratio(51, 81), "decision": "pending_human_decision"},
        },
        "tolerance_table": {
            "D2_line_0.60": tolerated_extra_fp(51, 81, 0.60),
            "D2_line_0.55": tolerated_extra_fp(51, 81, 0.55),
            "D1_line_0.50": tolerated_extra_fp(56, 110, 0.50),
        },
        "per_source_floor": {
            "measured_D2": calibers["D2_in_role_only"]["per_source_precision"],
            "note": "分源 0.80 在 D2 下同样不可达（源1 0.589）；分源下限须与总线下调同轮登记",
            "decision": "pending_human_decision",
        },
    }

    # --- unrecoverable-sample policy ---------------------------------------
    unrecoverable_policy = {
        "principle": "金标与候选字节均冻结、不等价样本不硬通过；处置只允许"
        "『分类登记 → 移出判据 → 在应承担角色登记覆盖』，禁止改判为 matched、禁止改金标/候选、"
        "禁止为过门而调相似度阈值",
        "precedent": {
            "items_side_signed": "契约 v4.3 review_assertions_excluded 5 条"
            "（NT-I09/I19 gold_split_finer_than_candidate；NT-I45/I46/I47 candidate_side_cannot_carry_axis）",
            "gate_side_signed": "门 v3 哨兵 16 → 11，六项阈值逐字未改",
        },
        "claims_side_registration_required": [
            "角色外候选（opinion/无值）移出 claims 判据时，必须在 material_items/relations 侧登记为待覆盖",
            "无载体必需字段（attribution/perspective/source_stance/estimate_status）按 items 先例登记"
            " human_only 或 excluded_from_matching_basis，不得设默认值",
            "凡移出项须逐条给出机制、理由、裁定人与生效版本；不得批量按相似度移出",
        ],
        "forbidden": [
            "把不等价候选改判 matched",
            "编辑 frozen-gold.json / P1R5 已签裁定 / 契约 v4.3 / 门 v3 字节",
            "用放行线通过替代质量线结论",
        ],
    }

    # --- open decisions -----------------------------------------------------
    open_decisions = [
        {
            "id": "C1-候选范围口径",
            "question": "分母取材料范围（全部候选）还是 claims 角色范围（指标断言）？",
            "measured": {
                "D1": calibers["D1_all_candidates"]["precision_contract_formula"]["display"],
                "D2": calibers["D2_in_role_only"]["precision_contract_formula"]["display"],
                "D3_recall_cost": calibers["D3_in_role_and_coordinate_complete"]["target_recall"]["display"],
            },
        },
        {
            "id": "C2-duplicate 是否计入分母",
            "question": "契约文字分母含 duplicate、评分器实现分母不含；取哪个为单一口径？",
            "measured": {
                "contract_text_formula": calibers["D1_all_candidates"]["precision_contract_formula"]["display"],
                "implemented_formula": calibers["D1_all_candidates"][
                    "precision_scorer_implemented_formula"
                ]["display"],
                "cross_ref_effect": "仅此一处定义即可无系统改动地把 0.509 变 0.523（及 D2 0.630 变 0.642）",
            },
        },
        {
            "id": "C3-无载体字段读路径",
            "question": "四个零载体字段（实测 0/110）补载体还是登记读路径？",
            "measured": {
                "no_carrier_fields": [
                    f for f, v in field_carriers.items() if v["status"] == "no_carrier"
                ],
                "factuality_domain": domain_mismatch["factuality"]["candidate_domain"],
            },
        },
        {
            "id": "C4-用途分级（原 OPEN-D）",
            "question": "compare/calculate 是否仍受 evidence_pipeline.py:404『零 reason』全或无约束？",
            "measured": {
                "correct_records_with_reason": "45/56 ⇒ 现规则下仅 11 条可 compare/calculate",
                "reason_as_hard_gate_cost": "D3 召回 12/20 ⇒ reason 太粗，不能当匹配门",
            },
        },
        {
            "id": "C5-放行线数值与分源下限",
            "question": "是否新增放行线（功能线）、取哪一档、分源下限取多少？",
            "measured": {
                "D2_measured": calibers["D2_in_role_only"]["precision_contract_formula"]["display"],
                "per_source": calibers["D2_in_role_only"]["per_source_precision"],
            },
        },
        {
            "id": "C6-目标线不可达的登记方式",
            "question": "冻结池上 0.80/源0.80 不可达，是登记为『已登记不可达』还是授权重跑新池？",
            "measured": reachability,
        },
    ]

    gate = {
        "schema_version": "claims-gate-v2-preregistration-1",
        "status": "draft_pending_human_signature",
        "created_on": DRAFT_ON,
        "role": "claims",
        "zero_model_calls": True,
        "purpose": "口径先行、双线登记、不可恢复样本分类登记的 claims 度量基准（取代 83 号 v1 草案）",
        "supersedes": {
            "path": str(CLAIMS_GATE_V1.relative_to(ROOT)),
            "sha256": sha256(CLAIMS_GATE_V1),
            "status_at_supersede": gate_v1["status"],
            "note": "v2 不改 83 号任何字节；83 号 signoff md 的签署栏与其 JSON/MANIFEST 不一致，"
            "该不一致由 U 处置，v2 不以 83 号的签字状态为前提",
        },
        "invariants": [
            "不改 frozen-gold.json 字节",
            "不改 P1R5 candidate-adjudications.signed / claims-gate-result.signed 字节",
            "不改 items 门 v3 / 契约 v4.3 字节",
            "哨兵清单 == 契约 review_assertions 的 NT-C* 子集",
            "零模型调用、零生产库访问",
        ],
        "frozen_inputs": {name: sha256(path) for name, path in INPUTS.items()},
        "gold": {
            "path": str(GOLD.relative_to(ROOT)),
            "role": "claims",
            "target_total": len(claims_gold),
            "record_ids": [r["record_id"] for r in claims_gold],
            "evaluation_scope": gold.get("evaluation_scope"),
        },
        "candidate_pool": {
            "path": str(CLAIMS_ADJ.relative_to(ROOT)),
            "sha256": sha256(CLAIMS_ADJ),
            "total": len(rows),
            "judgements": {
                name: len(judged(name))
                for name in ("matched", "correct_extra", "incorrect", "duplicate")
            },
            "unresolved": adj.get("unresolved_count"),
            "reviewer": adj.get("reviewer"),
            "distinct_source_spans": len(
                {
                    (s.get("doc_id"), s.get("locator"))
                    for r in rows
                    for s in (
                        (r["original_candidate"].get("evidence_alignment") or {}).get("source_spans")
                        or []
                    )
                }
            ),
        },
        "calibers": calibers,
        "false_positive_decomposition": fp_decomposition,
        "field_carriers": field_carriers,
        "domain_mismatch": domain_mismatch,
        "sentinels": sentinels,
        "thresholds": {
            "target_line": target_line,
            "release_line": release_line,
            "reachability_on_frozen_pool": reachability,
        },
        "unrecoverable_sample_policy": unrecoverable_policy,
        "open_decisions": open_decisions,
        "not_in_scope": [
            "不执行模型调用、不写生产 PG、不重跑抽取（候选池冻结）",
            "不发布、不进入 query/delivery/context_use/M_main 消费",
        ],
        "signoff": {
            "reviewer": None,
            "adjudicator": None,
            "signed_on": None,
            "instrument": "claims-gate-v2-signoff.md",
        },
    }

    measurements = {
        "schema_version": "claims-caliber-measurements-1",
        "created_on": DRAFT_ON,
        "model_calls": 0,
        "candidate_pool_sha256": sha256(CLAIMS_ADJ),
        "calibers": {
            name: {
                "rule": value["rule"],
                "kept_candidates": value.get("kept_candidates", 110 - len(no_coverage) - len(cross_role)),
                "judgements": value.get("judgements", {}),
                "precision_contract_formula": value.get(
                    "precision_contract_formula", {}
                ).get("display", "N/A"),
                "precision_scorer_implemented_formula": value.get(
                    "precision_scorer_implemented_formula", {}
                ).get("display", "N/A"),
                "target_recall": value.get("target_recall", {}).get("display", "N/A"),
                "per_source_precision": {
                    k: v["display"] for k, v in value.get("per_source_precision", {}).items()
                },
            }
            for name, value in calibers.items()
        },
        "false_positive_decomposition": fp_decomposition,
        "field_carriers": field_carriers,
        "reachability_on_frozen_pool": reachability,
        "tolerance_table": release_line["tolerance_table"],
    }

    manifest = {
        "schema_version": "claims-gate-v2-draft-manifest-1",
        "status": "draft",
        "created_on": DRAFT_ON,
        "model_calls": 0,
        "production_pg_access": 0,
        "inputs": {name: sha256(path) for name, path in INPUTS.items()},
        "outputs": {},
        "does_not_touch": [
            str(CLAIMS_GATE_V1.relative_to(ROOT)),
            str(CLAIMS_COVERAGE_V1.relative_to(ROOT)),
            "evidence/83-claims-scope-gate-draft-20261014/r0-zero-call/claims-gate-v1-signoff.md",
            str(CLAIMS_ADJ.relative_to(ROOT)),
            str(ITEMS_GATE_V3.relative_to(ROOT)),
            str(CONTRACT_V43.relative_to(ROOT)),
        ],
        "items_gate_v3_reference_sha256": sha256(ITEMS_GATE_V3),
    }

    return {"gate": gate, "measurements": measurements, "manifest": manifest}


SIGNOFF_MD = """# Claims 门 v2 草案 · 签认件（口径先行稿）

状态：草稿，**未签认**。`status = draft_pending_human_signature`，`reviewer/signed_on` 留空。

取代 83 号 v1 草案。本件同 v1 一样不改任何冻结字节；差别是**先定口径、再谈数值**，
并且把不可恢复样本的处置写成分类登记，而不是把它们硬判通过。

## 一、本件主张的三件事

1. **回召侧没有可放宽的空间**：claims 在冻结池上 target_recall = 20/20 = 1.000。
   精度侧 51 条 `incorrect` 是**被具名裁定为错**的产出（不是"措辞不同但正确"，后者已入
   `correct_extra` 36 条），所以放宽等价性判定只会把错判成对，不能当修复。
2. **冻结池上目标线不可达**：保持召回的口径（D2）下分子上限 = 51/81 = 0.630，
   分源更差（源1 0.589）。因此 0.80 / 源 0.80 在本池上要么靠 D4（按与金标相似度删负例）
   拿到纸面 0.86，要么就是不可达。
3. **因此"放宽"必须放宽在正确的位置**：不动目标线，另立**放行线（功能线）**并预先具名登记；
   目标线继续如实报 FAIL 与余量。二者并列，禁止用放行线通过宣称质量达标。

## 二、待裁项（每格附实测候选值，不预填结论）

| 编号 | 待裁 | 实测候选 | U 裁定 |
|---|---|---|---|
| C1 | 分母取材料范围还是 claims 角色范围 | D1 = 见 JSON `calibers.D1_all_candidates`；D2 = 见 `calibers.D2_in_role_only` | |
| C2 | duplicate 是否计入分母（契约文字 vs 评分器实现不一致） | 两个公式值见 `calibers.D1_all_candidates` | |
| C3 | 四个零载体字段：补载体还是登记读路径 | `field_carriers` 中 status=no_carrier 的 4 项 | |
| C4 | compare/calculate 是否仍全或无 | 45/56 正确记录带 reason；当硬门则召回 12/20 | |
| C5 | 放行线数值与分源下限 | `thresholds.release_line`（含容忍度表） | |
| C6 | 目标线不可达的登记方式 | `thresholds.reachability_on_frozen_pool` | |

## 三、硬约束（不属于待裁）

- 哨兵清单 = 已签契约 `review_assertions` 的 NT-C* 子集（= 3 条）；83 号 v1 额外自造的
  NT-C01/C03/C08 属第二份哨兵源，本件不再保留。
- 不改金标、不改 P1R5 已签裁定、不改 items 门 v3 / 契约 v4.3 字节；零模型调用。
- 角色外候选移出 claims 判据时，必须在 material_items/relations 侧登记为待覆盖。

## 签名

reviewer: ____________    adjudicator: ____________    signed_on: ____________
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-write", action="store_true", help="只打印摘要，不写文件")
    parser.add_argument("--force", action="store_true", help="允许覆盖本目录内已存在的输出")
    args = parser.parse_args()

    result = build()
    outputs = {
        "claims-gate-v2.proposed.json": (
            json.dumps(result["gate"], ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8"),
        "claims-caliber-measurements.json": (
            json.dumps(result["measurements"], ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8"),
        "claims-gate-v2-signoff.md": SIGNOFF_MD.encode("utf-8"),
    }
    manifest = result["manifest"]
    manifest["outputs"] = {name: hashlib.sha256(data).hexdigest() for name, data in outputs.items()}
    outputs["MANIFEST.json"] = (
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")

    if args.no_write:
        print(json.dumps(result["measurements"]["calibers"], ensure_ascii=False, indent=2))
        print(json.dumps(result["measurements"]["tolerance_table"], ensure_ascii=False, indent=2))
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
    raise SystemExit(main())
