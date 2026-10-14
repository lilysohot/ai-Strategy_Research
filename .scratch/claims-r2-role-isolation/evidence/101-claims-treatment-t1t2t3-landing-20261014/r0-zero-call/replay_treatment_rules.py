"""Land the produce-side treatment rules T1/T2/T3 and replay them zero-call on the frozen pool.

The signed 95/99 号 treatment arm repairs the production side in four ways; 100 号 landed T4
(reason-code labelling). This package lands the other three and measures them without any model call,
by replaying the rules over the frozen P1R5 pool:

* **T1** drop opinion / valueless candidates at the produce side (``claims_detail.is_claims_scope_candidate``,
  the mirror of the signed C1 caliber);
* **T2** fill a missing ``period``/``unit`` from a carrier inside the same packet
  (``claims_binding.recover_packet_coordinates``), never by guessing;
* **T3** merge repeated renderings of one subject+metric+quote span with the pre-registered
  deterministic priority (``evidence_pipeline._merge_repeated_facts``), never by looking at gold.

The replay is a **lower bound, and not the real pool**: the new pool will be produced by a prompt
contract that no longer invites rating opinions and by bind/recovery that run on real packet text.
What it does answer is whether the stage-2 stop-loss proxies move at all, and whether the T3 tie-break
keeps the row the adjudicator had matched (the load-bearing case in 95 号).

Usage:
    python replay_treatment_rules.py [--no-write] [--force]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections import defaultdict
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]  # .scratch/claims-r2-role-isolation
REPO_ROOT = ROOT.parents[1]
sys.path.insert(0, str(REPO_ROOT))

from plugins.corpus.claims_binding import recover_packet_coordinates  # noqa: E402
from plugins.corpus.claims_detail import (  # noqa: E402
    EXTRACTOR_VERSION_V2,
    LINT_VERSION,
    ClaimRecord,
    is_claims_scope_candidate,
    lint_claim,
)
from plugins.corpus.evidence_pipeline import (  # noqa: E402
    EvidenceFact,
    _merge_repeated_facts,
    _render_key,
)
from tools.check_claims_gate import (  # noqa: E402
    COORDINATE_REASON_CODES,
    _claim_of,
    _is_role_external,
)
from tools.evidence_guard import assert_writable, write_once  # noqa: E402

POOL = (
    ROOT
    / "evidence/17-structured-extraction-convergence-closure-20261009"
    / "p1r5-claims-adjudication-v2/candidate-adjudications.signed.json"
)
PREREG = (
    ROOT
    / "evidence/99-claims-prereg-v3-signed-r2-20261014/r0-zero-call/claims-preregistration.json"
)
T4_LANDING = (
    ROOT
    / "evidence/100-claims-t4-labeling-landing-20261014/r0-zero-call/treatment-landing-record.json"
)
FILES_CHANGED = (
    "plugins/corpus/claims_detail.py",
    "plugins/corpus/claims_binding.py",
    "plugins/corpus/evidence_pipeline.py",
)
FIELDS = ("subject", "metric", "period_raw", "unit_raw")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_blob(path: str) -> str:
    out = subprocess.run(
        ["git", "hash-object", path], cwd=REPO_ROOT, capture_output=True, text=True, check=False
    )
    return out.stdout.strip()[:8] or "unknown"


# Codes ``lint_claim`` produces. The frozen pool stores the *previous* lint's verdict, so re-deriving
# the after-measurement requires dropping them first — otherwise the old conclusion is counted as the
# new one (the first version of this replay did exactly that). Pipeline-seeded codes
# (``period_unanchored`` / ``period_not_in_packet`` / ``time_invalid``) are kept: they are inputs.
LINT_OUTPUT_CODES = (
    "qualifier_invalid",
    "subject_ambiguous",
    "subject_scope_mismatch",
    "metric_missing",
    "opinion_value_projection",
    "value_missing",
    "unit_missing",
    "period_missing",
    "period_ambiguous",
    "unit_unknown",
    "normalized_value_mismatch",
    "normalized_unit_mismatch",
    "evidence_not_found",
    "value_not_in_evidence",
    "prompt_injection_detected",
)


def fresh_record(claim: dict[str, Any]) -> ClaimRecord:
    """The claim as the *current* pipeline would hand it to ``lint_claim`` (lint outputs dropped)."""
    record = record_of(claim)
    return replace(
        record,
        reason_codes=tuple(code for code in record.reason_codes if code not in LINT_OUTPUT_CODES),
    )


def record_of(claim: dict[str, Any]) -> ClaimRecord:
    payload = {
        key: value
        for key, value in claim.items()
        if key in ClaimRecord.__dataclass_fields__ and key not in {"value_num", "reason_codes"}
    }
    value = claim.get("value_num")
    return ClaimRecord(
        **payload,  # type: ignore[arg-type]
        value_num=None if value is None else Decimal(str(value)),
        reason_codes=tuple(claim.get("reason_codes") or ()),
    )


def field_gap(record: ClaimRecord) -> bool:
    return any(not getattr(record, name) for name in FIELDS)


def coordinate_codes(record: ClaimRecord) -> set[str]:
    return set(lint_claim(record).reason_codes) & set(COORDINATE_REASON_CODES)


def proxies(records: list[ClaimRecord]) -> dict[str, int]:
    """95 号 stage-2 代理的同一套判据（field-first 并集 + 无码计数）。"""
    in_role = [record for record in records if is_claims_scope_candidate(record)]
    field_rows = [record for record in in_role if field_gap(record)]
    code_rows = [record for record in in_role if coordinate_codes(record)]
    union = {id(r) for r in field_rows} | {id(r) for r in code_rows}
    unlabelled = [r for r in in_role if field_gap(r) and not coordinate_codes(r)]
    keys: dict[tuple[str, str, str], int] = defaultdict(int)
    for record in in_role:
        keys[_render_key(record)] += 1
    return {
        "in_role": len(in_role),
        "field_gap": len(field_rows),
        "coordinate_code": len(code_rows),
        "union": len(union),
        "unlabelled": len(unlabelled),
        "redundant_groups": sum(1 for count in keys.values() if count > 1),
    }


def replay() -> dict[str, Any]:
    rows = json.loads(POOL.read_text(encoding="utf-8"))["adjudications"]
    by_packet: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_packet[str(row["original_candidate"].get("packet_id"))].append(row)

    before_records = [record_of(_claim_of(row)) for row in rows]
    before_proxies = proxies(before_records)
    alignment = [
        {
            "candidate_id": row["candidate_id"],
            "produce_side_in_scope": is_claims_scope_candidate(record_of(_claim_of(row))),
            "caliber_role_external": _is_role_external(_claim_of(row)),
        }
        for row in rows
    ]
    misaligned = [
        item for item in alignment if item["produce_side_in_scope"] == item["caliber_role_external"]
    ]

    recovered_total = {
        "period_from_same_quote": 0,
        "period_from_same_metric": 0,
        "unit_from_same_metric": 0,
    }
    kept: list[tuple[str, ClaimRecord]] = []
    row_of_claim: dict[int, dict[str, Any]] = {}
    for packet_id, packet_rows in by_packet.items():
        records = [fresh_record(_claim_of(row)) for row in packet_rows]
        recovered, notes = recover_packet_coordinates(records)
        for key, value in notes.items():
            recovered_total[key] += value
        for record, row in zip(recovered, packet_rows, strict=True):
            if is_claims_scope_candidate(record):
                kept.append((packet_id, record))
                row_of_claim[id(record)] = row

    facts = [
        EvidenceFact(fact_id=f"replay-{index:04d}", packet_id=packet_id, claim=record)
        for index, (packet_id, record) in enumerate(kept)
    ]
    merged_facts, dedupe = _merge_repeated_facts(facts)
    after_proxies = proxies([fact.claim for fact in merged_facts])

    pool_index: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        claim = _claim_of(row)
        if not is_claims_scope_candidate(record_of(claim)):
            continue
        pool_index[
            (
                str(row["original_candidate"].get("packet_id")),
                *_render_key(record_of(claim)),
                str(claim.get("value_text")),
            )
        ].append(row)

    detail: list[dict[str, Any]] = []
    for item in dedupe["detail"]:
        key = tuple(item["key"])
        members = pool_index.get(
            (str(item["kept_packet_id"]), *key, str(item["kept_value_text"])), []
        )
        detail.append(
            {
                "key": list(key),
                "kept_packet_id": item["kept_packet_id"],
                "kept_value_text": item["kept_value_text"],
                "dropped_packet_ids": item["dropped_packet_ids"],
                "kept_row_judgements": sorted({row["judgement"] for row in members}),
                "kept_row_was_matched": any(row["judgement"] == "matched" for row in members),
            }
        )

    # 并集「是不是精度代理」的决定性证据：按裁定分解 unbound_union。
    def composition(
        pairs: list[tuple[dict[str, Any], ClaimRecord, tuple[str, ...]]],
    ) -> dict[str, int]:
        out: dict[str, int] = defaultdict(int)
        for row, record, codes in pairs:
            if field_gap(record) or set(codes) & set(COORDINATE_REASON_CODES):
                out[str(row["judgement"])] += 1
        return dict(out)

    before_pairs = [
        (row, record, tuple(_claim_of(row).get("reason_codes") or ()))
        for row, record in zip(rows, before_records, strict=True)
        if is_claims_scope_candidate(record)
    ]
    after_pairs = [
        (row_of_claim[id(fact.claim)], fact.claim, tuple(lint_claim(fact.claim).reason_codes))
        for fact in merged_facts
    ]
    after_histogram: dict[str, int] = defaultdict(int)
    for _row, _record, codes in after_pairs:
        for code in sorted(set(codes) & set(COORDINATE_REASON_CODES)):
            after_histogram[code] += 1

    return {
        "pool": {
            "path": str(POOL.relative_to(ROOT)),
            "sha256": sha256(POOL),
            "candidates_total": len(rows),
            "packets": len(by_packet),
        },
        "union_composition": {
            "before_by_judgement": composition(before_pairs),
            "after_by_judgement": composition(after_pairs),
            "after_coordinate_code_histogram": dict(after_histogram),
            "why_it_matters": (
                "unbound_union 里 matched/correct_extra 占多数 ⇒ 它是『标注覆盖率』而不是精度代理："
                "减半它既非达成放行线的必要条件也非充分条件。真正决定去留的是 FP（incorrect）那一支。"
            ),
        },
        "c1_alignment": {
            "rows_checked": len(alignment),
            "misaligned": misaligned,
            "aligned": not misaligned,
            "note": "产出侧 is_claims_scope_candidate 与读数侧 _is_role_external 必须互补",
        },
        "t1": {
            "role_external_rows": len(rows) - before_proxies["in_role"],
            "in_role_before": before_proxies["in_role"],
            "in_role_after": len(kept),
        },
        "t2": {
            "recovered": recovered_total,
            "recovered_rows": sum(recovered_total.values()),
            "basis_note": "载体只能是同一 packet 内的兄弟记录（同引用区间 / 同 subject+metric）",
        },
        "t3": {
            "groups_merged": dedupe["groups"],
            "rows_merged": dedupe["merged_facts"],
            "detail": detail,
            "tie_break_note": "优先级：坐标更完整 > value 与引用一致 > 文件序；禁用金标/裁定",
        },
        "stage2_proxies": {
            "before": before_proxies,
            "after_replay": after_proxies,
            "targets": {
                "role_external_candidates": "== 0",
                "unbound_union": "≤ 27",
                "redundant_renderings": "== 0",
                "unbound_fields_without_reason_code": "== 0",
            },
            "replay_verdict": {
                "role_external_candidates_zero": True,
                "role_external_note": (
                    "T1 在产出侧按同一判据剔除 ⇒ 该项按构造为 0；回放中 before 为 "
                    f"{len(rows) - before_proxies['in_role']} 条"
                ),
                "redundant_renderings_zero": after_proxies["redundant_groups"] == 0,
                "unlabelled_zero": after_proxies["unlabelled"] == 0,
                "unbound_union_passed": after_proxies["union"] <= 27,
            },
        },
        "versions": {
            "extractor_version_v2_now": EXTRACTOR_VERSION_V2,
            "lint_version_now": LINT_VERSION,
            "frozen_pool_extractor_version": sorted(
                {_claim_of(row)["extractor_version"] for row in rows}
            ),
            "frozen_pool_lint_version": sorted({_claim_of(row)["lint_version"] for row in rows}),
        },
        "code_change": {path: {"git_blob": git_blob(path)} for path in FILES_CHANGED},
        "not_the_real_pool": (
            "本回放不含新契约下的重抽，也不含真实 packet 文本驱动的 bind；它只回答"
            "『三条规则在旧池等输入上会不会动闸门数字、T3 并列是否保住 matched 行』"
        ),
    }


def build() -> dict[str, Any]:
    replay_record = replay()
    landing = {
        "schema_version": "claims-treatment-landing-1",
        "id": "101-claims-treatment-t1t2t3-landing-20261014",
        "created_on": "2026-10-14",
        "zero_model_calls": True,
        "treatment_rules": {
            "T1_no_opinion": {
                "status": "landed",
                "where": "claims_detail.V2_OUTPUT_CONTRACT + is_claims_scope_candidate；evidence_pipeline.apply_production_rules",
                "note": "契约不再邀请评级观点；产出侧按 C1 判据剔除（bind 之后判定，避免误杀分类状态值）",
            },
            "T2_unbound_disposition": {
                "status": "landed（确定性部分）",
                "where": "claims_binding.recover_packet_coordinates",
                "note": "只从同 packet 兄弟记录补齐 period/unit，补不上留空；模型侧重抽只能由实跑验证",
            },
            "T3_dedupe_tie_break": {
                "status": "landed",
                "where": "evidence_pipeline._merge_repeated_facts（跨 packet，run 级）",
                "note": "并列优先级：坐标更完整 > value 与引用一致 > 文件序；禁用金标/裁定",
            },
            "T4_missing_field_must_be_labelled": {
                "status": "landed（100 号）",
                "where": "claims_detail.lint_claim + LINT_VERSION 9",
            },
        },
        "replay": replay_record,
        "prereg": {"path": str(PREREG.relative_to(ROOT)), "sha256": sha256(PREREG)},
        "t4_landing": {"path": str(T4_LANDING.relative_to(ROOT)), "sha256": sha256(T4_LANDING)},
        "does_not_touch": [
            "evidence/17-structured-extraction-convergence-closure-20261009/**",
            "evidence/95-claims-prereg-20261014/**",
            "evidence/99-claims-prereg-v3-signed-r2-20261014/**",
            "evidence/100-claims-t4-labeling-landing-20261014/**",
        ],
        "next": [
            "阶段 1 活跑入口（prepare/execute 对）与新池裁定工作表仍待建",
            "起跑前置：预算 ceiling（U）+ 人工裁定工时（U）",
        ],
    }
    manifest = {
        "schema_version": "claims-treatment-landing-manifest-1",
        "status": "landed",
        "created_on": "2026-10-14",
        "model_calls": 0,
        "inputs": {
            "p1r5_candidate_adjudications_signed": sha256(POOL),
            "claims_preregistration_signed": sha256(PREREG),
            "t4_landing_record": sha256(T4_LANDING),
        },
        "outputs": {},
        "blocked_on": ["预算 ceiling（U）", "人工裁定工时（U）", "活跑入口与新池裁定工作表"],
    }
    return {"landing": landing, "manifest": manifest}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    result = build()
    outputs = {
        "treatment-landing-record.json": (
            json.dumps(result["landing"], ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8")
    }
    manifest = result["manifest"]
    manifest["outputs"] = {name: hashlib.sha256(data).hexdigest() for name, data in outputs.items()}
    outputs["MANIFEST.json"] = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode(
        "utf-8"
    )

    if args.no_write:
        print(
            json.dumps(result["landing"]["replay"]["stage2_proxies"], ensure_ascii=False, indent=2)
        )
        print(json.dumps(result["landing"]["replay"]["t3"], ensure_ascii=False, indent=2))
        print("[no-write] nothing written.")
        return 0

    targets = {name: HERE / name for name in outputs}
    for name, target in targets.items():
        assert_writable(target, reason="101 号治疗落地件")
        if target.exists() and not args.force:
            raise SystemExit(f"refusing to overwrite existing output {name}; use --force")
    for name, data in outputs.items():
        write_once(targets[name], data.decode("utf-8"), allow_overwrite=True)

    print(f"wrote {len(outputs)} files to {HERE}")
    print(json.dumps(manifest["outputs"], ensure_ascii=False, indent=2))
    print(json.dumps(result["landing"]["replay"]["stage2_proxies"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
