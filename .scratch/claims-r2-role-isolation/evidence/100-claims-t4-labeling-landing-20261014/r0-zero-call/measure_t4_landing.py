"""Land T4 (缺字段必标 reason 码) and measure it zero-call on the frozen P1R5 pool.

T4 as signed in 95/99 号: a candidate missing ``subject/metric/period/unit`` must carry the
corresponding reason code, because the stage-2 stop-loss「缺字段却无阻断码 = 0」is defined on the raw
fields. The upstream defect was exactly this: ``lint_claim`` emitted ``period_missing`` only when
*there was no period information at all*, so a document-level ``observed_at`` silently suppressed the
code for 9 in-role rows.

This script re-lints the frozen pool with the **current code path** (no model calls, no writes to the
pool) and records before/after so the change is auditable:

* the stop-loss item goes 9 → 0 without changing the size of the unbound union (the fix labels rows
  that were already counted as unbound by their empty field);
* the blast radius is listed row by row (quality_status flips, ``usable_for`` flips) instead of being
  asserted away.

Usage:
    python measure_t4_landing.py [--no-write] [--force]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Callable, Iterable
from decimal import Decimal
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]  # .scratch/claims-r2-role-isolation
REPO_ROOT = ROOT.parents[1]
sys.path.insert(0, str(REPO_ROOT))

from plugins.corpus.claim_use_axes import uses_for  # noqa: E402
from plugins.corpus.claims_detail import LINT_VERSION, ClaimRecord, lint_claim  # noqa: E402
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
PREREG_SIGNED = (
    ROOT
    / "evidence/99-claims-prereg-v3-signed-r2-20261014/r0-zero-call/claims-preregistration.json"
)
PREREG_DRAFT = ROOT / "evidence/95-claims-prereg-20261014/r0-zero-call/claims-preregistration.json"
TREATMENT_FILE = REPO_ROOT / "plugins/corpus/claims_detail.py"
CODE_CHANGE = {
    "file": "plugins/corpus/claims_detail.py",
    "git_blob_before": "cb75abf9",
    "git_blob_after": "12d27432",
    "changed_lines": "+6 / -2",
    "what": "lint_claim 的 period 判据由『无 period_end 且无 observed_at』改为『period_raw 为空』；LINT_VERSION 8→9",
}

INPUTS = {
    "p1r5_candidate_adjudications_signed": POOL,
    "claims_preregistration_signed": PREREG_SIGNED,
    "claims_preregistration_draft": PREREG_DRAFT,
}
REJECTED_CODES = {
    "evidence_not_found",
    "value_not_in_evidence",
    "subject_scope_mismatch",
    "opinion_value_projection",
    "normalized_value_mismatch",
    "normalized_unit_mismatch",
}
FIELDS = ("subject", "metric", "period_raw", "unit_raw")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _record(claim: dict[str, Any]) -> ClaimRecord:
    payload = {
        key: value
        for key, value in claim.items()
        if key in ClaimRecord.__dataclass_fields__ and key not in {"value_num", "reason_codes"}
    }
    numbers = claim.get("value_num")
    return ClaimRecord(
        **payload,  # type: ignore[arg-type]
        value_num=None if numbers is None else Decimal(str(numbers)),
        reason_codes=tuple(claim.get("reason_codes") or ()),
    )


def _status(codes: tuple[str, ...]) -> str:
    return "rejected" if set(codes) & REJECTED_CODES else ("review" if codes else "ok")


def _field_gap(claim: dict[str, Any]) -> bool:
    return any(claim.get(field) in (None, "") for field in FIELDS)


def _code_gap(claim: dict[str, Any], codes: tuple[str, ...] | None = None) -> bool:
    if codes is None:
        codes = tuple(claim.get("reason_codes") or ())
    return bool(set(codes) & set(COORDINATE_REASON_CODES))


def measure() -> dict[str, Any]:
    rows = json.loads(POOL.read_text(encoding="utf-8"))["adjudications"]
    in_role = [row for row in rows if not _is_role_external(_claim_of(row))]

    def proxies(code_of: Callable[[dict[str, Any]], tuple[str, ...]]) -> dict[str, int]:
        field_rows = [row for row in in_role if _field_gap(_claim_of(row))]
        code_rows = [row for row in in_role if _code_gap(_claim_of(row), code_of(_claim_of(row)))]
        union = {id(row) for row in field_rows} | {id(row) for row in code_rows}
        unlabelled = [
            row
            for row in in_role
            if _field_gap(_claim_of(row)) and not _code_gap(_claim_of(row), code_of(_claim_of(row)))
        ]
        return {
            "unbound_by_field": len(field_rows),
            "unbound_by_reason_code": len(code_rows),
            "unbound_union": len(union),
            "unbound_fields_without_reason_code": len(unlabelled),
        }

    def stored(claim: dict[str, Any]) -> tuple[str, ...]:
        return tuple(claim.get("reason_codes") or ())

    # Per-row comparison: stored codes versus codes the current lint produces for the same claim.
    gained: list[dict[str, Any]] = []
    status_flips: list[dict[str, Any]] = []
    use_flips: list[dict[str, Any]] = []
    relint_by_id: dict[str, tuple[str, ...]] = {}
    for row in rows:
        claim = _claim_of(row)
        codes = lint_claim(_record(claim)).reason_codes
        relint_by_id[row["candidate_id"]] = codes
        old = tuple(claim.get("reason_codes") or ())
        added = sorted(set(codes) - set(old))
        if not added:
            continue
        gained.append(
            {
                "candidate_id": row["candidate_id"],
                "judgement": row["judgement"],
                "added_codes": added,
                "missing_fields": [f for f in FIELDS if _claim_of(row).get(f) in (None, "")],
            }
        )
        old_status = claim.get("quality_status") or _status(old)
        new_status = _status(codes)
        if old_status != new_status:
            status_flips.append(
                {
                    "candidate_id": row["candidate_id"],
                    "judgement": row["judgement"],
                    "old": old_status,
                    "new": new_status,
                }
            )
        # ``has_value`` is structural and identical on both sides, so only the codes can move uses.
        has_value = bool(claim.get("value_text"))
        old_uses = uses_for(old, kind=claim.get("kind"), has_value=has_value)
        new_uses = uses_for(codes, kind=claim.get("kind"), has_value=has_value)
        if old_uses != new_uses:
            use_flips.append(
                {
                    "candidate_id": row["candidate_id"],
                    "judgement": row["judgement"],
                    "old": list(old_uses),
                    "new": list(new_uses),
                }
            )

    after_code_rows = [
        row for row in in_role if _code_gap(_claim_of(row), relint_by_id[row["candidate_id"]])
    ]
    after_union = {id(row) for row in in_role if _field_gap(_claim_of(row))} | {
        id(row) for row in after_code_rows
    }
    after_unlabelled = [
        row
        for row in in_role
        if _field_gap(_claim_of(row))
        and not _code_gap(_claim_of(row), relint_by_id[row["candidate_id"]])
    ]
    return {
        "pool": {
            "path": str(POOL.relative_to(ROOT)),
            "sha256": sha256(POOL),
            "candidates_total": len(rows),
            "in_role": len(in_role),
        },
        "lint_version_now": LINT_VERSION,
        "before": proxies(stored),
        "after": {
            "unbound_by_field": len([row for row in in_role if _field_gap(_claim_of(row))]),
            "unbound_by_reason_code": len(after_code_rows),
            "unbound_union": len(after_union),
            "unbound_fields_without_reason_code": len(after_unlabelled),
        },
        "rows_gaining_a_code": {
            "count": len(gained),
            "by_added_code": _counts(added for item in gained for added in item["added_codes"]),
            "by_judgement": _counts(item["judgement"] for item in gained),
            "rows": gained,
        },
        "quality_status_flips": {"count": len(status_flips), "rows": status_flips},
        "usable_for_flips": {"count": len(use_flips), "rows": use_flips},
    }


def _counts(values: Iterable[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for value in values:
        out[value] = out.get(value, 0) + 1
    return out


def build() -> dict[str, Any]:
    measurement = measure()
    drafted = json.loads(PREREG_DRAFT.read_text(encoding="utf-8"))
    expected_before = drafted["evidence_chain"]["proxies"]
    recorded = {
        key: measurement["before"][key]
        for key in (
            "unbound_by_field",
            "unbound_by_reason_code",
            "unbound_union",
            "unbound_fields_without_reason_code",
        )
    }
    recorded_95 = {
        key: expected_before[key]
        for key in (
            "unbound_by_field",
            "unbound_by_reason_code",
            "unbound_union",
            "unbound_fields_without_reason_code",
        )
    }
    landing = {
        "schema_version": "claims-treatment-landing-1",
        "id": "100-claims-t4-labeling-landing-20261014",
        "created_on": "2026-10-14",
        "zero_model_calls": True,
        "treatment_rule": {
            "id": "T4_missing_field_must_be_labelled",
            "prereg": str(PREREG_SIGNED.relative_to(ROOT)),
            "prereg_sha256": sha256(PREREG_SIGNED),
            "owner_proxy": "unbound_fields_without_reason_code",
        },
        "code_change": CODE_CHANGE,
        "measurement_on_frozen_pool": measurement,
        "reconciliation_with_95_record": {
            "recorded_in_95": recorded_95,
            "recomputed_before": recorded,
            "match": recorded == recorded_95,
            "note": "before 一栏必须与 95 号登记的基线逐字一致，否则说明复算口径漂了",
        },
        "conclusions": [
            (
                "止损项『缺字段却无阻断码』在冻结池上从 "
                f"{measurement['before']['unbound_fields_without_reason_code']} 条降到 "
                f"{measurement['after']['unbound_fields_without_reason_code']} 条"
            ),
            (
                "并集规模不变（"
                f"{measurement['before']['unbound_union']} → {measurement['after']['unbound_union']}）"
                "：本次只给已计入并集的行补码，不新增未绑行"
            ),
            (
                f"爆炸半径如实登记：{measurement['rows_gaining_a_code']['count']} 行获得码，"
                f"其中 {measurement['quality_status_flips']['count']} 行 quality_status 由 ok 变 review、"
                f"{measurement['usable_for_flips']['count']} 行 usable_for 收窄为 cite（无 period_raw ⇒ "
                "按已签 C4 的 period 轴不得 compare/calculate）"
            ),
            "旧帧不被改写：LINT_VERSION 8→9 后 lint-8 的既有产物仍可读，但按 validation_is_current 不再继承新保证",
        ],
        "not_done": [
            "T1（产侧不再产出 opinion/无值）、T2（坐标补齐的重抽路径）、T3（去冗余并列规则）尚未实现 ⇒ 治疗臂不可起跑",
            "本件不跑模型、不重跑抽取、不改任何冻结件字节",
        ],
        "does_not_touch": [
            "evidence/17-structured-extraction-convergence-closure-20261009/**",
            "evidence/95-claims-prereg-20261014/**",
            "evidence/99-claims-prereg-v3-signed-r2-20261014/**",
        ],
    }
    manifest = {
        "schema_version": "claims-treatment-landing-manifest-1",
        "status": "landed",
        "created_on": "2026-10-14",
        "model_calls": 0,
        "inputs": {name: sha256(path) for name, path in INPUTS.items()},
        "outputs": {},
        "blocked_on": ["治疗臂起跑条件：预算 ceiling（U）+ T1/T2/T3 产侧实现 + 裁定工时"],
    }
    return {"landing": landing, "manifest": manifest}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    result = build()
    landing_bytes = (json.dumps(result["landing"], ensure_ascii=False, indent=2) + "\n").encode(
        "utf-8"
    )
    outputs = {"treatment-landing-record.json": landing_bytes}
    manifest = result["manifest"]
    manifest["outputs"] = {name: hashlib.sha256(data).hexdigest() for name, data in outputs.items()}
    outputs["MANIFEST.json"] = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode(
        "utf-8"
    )

    if args.no_write:
        summary = {
            "before": result["landing"]["measurement_on_frozen_pool"]["before"],
            "after": result["landing"]["measurement_on_frozen_pool"]["after"],
            "rows_gaining_a_code": result["landing"]["measurement_on_frozen_pool"][
                "rows_gaining_a_code"
            ]["count"],
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        print("[no-write] nothing written.")
        return 0

    targets = {name: HERE / name for name in outputs}
    for name, target in targets.items():
        assert_writable(target, reason="100 号 T4 落地件")
        if target.exists() and not args.force:
            raise SystemExit(f"refusing to overwrite existing output {name}; use --force")
    for name, data in outputs.items():
        write_once(targets[name], data.decode("utf-8"), allow_overwrite=True)

    print(f"wrote {len(outputs)} files to {HERE}")
    print(json.dumps(manifest["outputs"], ensure_ascii=False, indent=2))
    print(
        json.dumps(result["landing"]["measurement_on_frozen_pool"]["before"], ensure_ascii=False)
        + " -> "
        + json.dumps(result["landing"]["measurement_on_frozen_pool"]["after"], ensure_ascii=False)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
