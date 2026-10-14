"""Stage 2 + stage 3 entry of the treatment arm (95/99 号 前置缺件②): proxies, then worksheet.

Stage 2 (zero-call, no human time): the four pre-registered stop-loss proxies are measured on the new
pool with the *same predicates* as 95 号, and the rules are read from the signed pre-registration
rather than hardcoded — so if the signed rule is ever amended, this script follows it. Per the signed
text, a failed proxy stops the run before the adjudication round: this script then refuses to emit a
worksheet and writes ``stage2-failed.json`` instead.

Stage 3: the worksheet the named human fills — one row per candidate, ``reviewer``/``adjudicator``
left blank, ``review_status="pending_named_human_signoff"``, plus the eleven fields the signed scoring
contract requires downstream (``adjudication_assembly`` rebuilds the rest). Gold is never read here.

Usage:
    python build_treatment_adjudication_worksheet.py [--freeze DIR] [--out DIR] [--force]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]  # .scratch/claims-r2-role-isolation
REPO_ROOT = ROOT.parents[1]
sys.path.insert(0, str(REPO_ROOT))

from plugins.corpus.claim_use_axes import uses_for  # noqa: E402
from tools.check_claims_gate import (  # noqa: E402
    COORDINATE_REASON_CODES,
    _is_role_external,
)
from tools.evidence_guard import assert_writable, write_once  # noqa: E402

FREEZE_DEFAULT = HERE / "claims-treatment-plan-freeze"
OUT_DEFAULT = HERE / "treatment-adjudication"
SIGNED_PREREG = (
    ROOT
    / "evidence/99-claims-prereg-v3-signed-r2-20261014/r0-zero-call/claims-preregistration.json"
)
OBSERVED_FIELDS = (
    "quote",
    "subject",
    "scope",
    "metric",
    "period_raw",
    "period_end",
    "value_num",
    "value_text",
    "value_lower",
    "value_upper",
    "unit",
    "kind",
    "quality_status",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def pool_of(store: Path) -> list[dict[str, Any]]:
    """Every claims candidate payload object in one run's store, in task order."""
    index = store / "index/structured.sqlite3"
    if not index.exists():
        raise SystemExit(f"refusing to build a worksheet: no store at {store}")
    connection = sqlite3.connect(index)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            "SELECT task_id, payload_object_sha256 FROM tasks WHERE role = 'claims'"
        ).fetchall()
    finally:
        connection.close()
    facts: list[dict[str, Any]] = []
    for row in rows:
        digest = str(row["payload_object_sha256"]).removeprefix("sha256:")
        payload = json.loads(
            (store / "objects/sha256" / digest[:2] / f"{digest}.json").read_text(encoding="utf-8")
        )
        facts.extend(payload.get("facts") or [])
    return facts


def observed(claim: dict[str, Any]) -> dict[str, Any]:
    return {
        "quote": claim.get("evidence_quote"),
        "subject": claim.get("subject"),
        "scope": claim.get("scope"),
        "metric": claim.get("metric"),
        "period_raw": claim.get("period_raw"),
        "period_end": claim.get("period_end"),
        "value_num": claim.get("value_num"),
        "value_text": claim.get("value_text"),
        "value_lower": (claim.get("qualifiers") or {}).get("value_lower"),
        "value_upper": (claim.get("qualifiers") or {}).get("value_upper"),
        "unit": claim.get("unit"),
        "kind": claim.get("kind"),
        "quality_status": claim.get("quality_status"),
    }


def _norm(text: str | None) -> str:
    return re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff%]", "", text or "").lower()


def stage2(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    """The four signed stop-loss proxies, measured with the 95-号 predicates."""
    in_role = [item for item in candidates if not _is_role_external(item["claim"])]
    field_gap = [
        item
        for item in in_role
        if any(
            item["claim"].get(name) in (None, "")
            for name in ("subject", "metric", "period_raw", "unit_raw")
        )
    ]
    code_gap = [
        item
        for item in in_role
        if set(item["claim"].get("reason_codes") or ()) & set(COORDINATE_REASON_CODES)
    ]
    union = {item["candidate_id"] for item in field_gap} | {
        item["candidate_id"] for item in code_gap
    }
    unlabelled = [
        item
        for item in field_gap
        if item["candidate_id"] not in {x["candidate_id"] for x in code_gap}
    ]
    keys: dict[tuple[str, str, str, str], int] = {}
    for item in in_role:
        claim = item["claim"]
        key = (
            _norm(claim.get("subject")),
            _norm(claim.get("metric")),
            _norm(claim.get("evidence_quote"))[:80],
            str(claim.get("kind")),
        )
        keys[key] = keys.get(key, 0) + 1
    return {
        "role_external_candidates": len(candidates) - len(in_role),
        "unbound_union": len(union),
        "redundant_renderings": sum(1 for count in keys.values() if count > 1),
        "unbound_fields_without_reason_code": len(unlabelled),
        "candidates_total": len(candidates),
        "in_role_candidates": len(in_role),
    }


def apply_signed_rules(measured: dict[str, int]) -> dict[str, Any]:
    """Evaluate the signed rules literally: ``== 0`` and ``≤ baseline × 0.5``."""
    signed = load(SIGNED_PREREG)["exit_rules"]["early_stop_before_human_adjudication"]
    verdicts: list[dict[str, Any]] = []
    for name, spec in signed["stage2_proxies"].items():
        rule = str(spec["rule"])
        baseline = spec.get("baseline")
        value = measured.get(name)
        if rule.startswith("== 0"):
            passed = value == 0
        elif "× 0.5" in rule or "* 0.5" in rule:
            passed = (
                isinstance(value, int) and isinstance(baseline, int) and value <= baseline * 0.5
            )
        else:
            raise SystemExit(f"unsupported signed stop-loss rule for {name}: {rule!r}")
        verdicts.append(
            {"proxy": name, "rule": rule, "baseline": baseline, "measured": value, "passed": passed}
        )
    return {
        "stage2_proxies_source": str(SIGNED_PREREG.relative_to(ROOT)),
        "verdicts": verdicts,
        "passed": all(item["passed"] for item in verdicts),
    }


def build(freeze: Path, out: Path) -> dict[str, Any]:
    summary_path = freeze / "execution-summary.json"
    manifest_path = freeze / "manifest.json"
    if not summary_path.exists():
        raise SystemExit(f"refusing to build a worksheet: {summary_path} 不存在（先跑 execute）")
    manifest = load(manifest_path)
    summary = load(summary_path)
    candidates: list[dict[str, Any]] = []
    for entry in manifest["entries"]:
        name = str(entry["name"])
        facts = pool_of(freeze / name / "live-store")
        for fact in facts:
            claim = fact["claim"]
            candidates.append(
                {
                    "candidate_id": fact["fact_id"],
                    "role": "claims",
                    "run": name,
                    "claim": claim,
                    "fact": fact,
                }
            )
    measured = stage2(candidates)
    rules = apply_signed_rules(measured)
    rows = [
        {
            "candidate_id": item["candidate_id"],
            "role": "claims",
            "run": item["run"],
            "original_candidate": item["fact"],
            "judgement": None,
            "matched_gold_id": None,
            "canonical_observed_fields": observed(item["claim"]),
            "decision_basis": "pending_named_human_adjudication",
            "agent_reason": None,
            "reviewer": None,
            "adjudicator": None,
            "review_status": "pending_named_human_signoff",
            "usable_for": list(
                uses_for(
                    item["claim"].get("reason_codes") or (),
                    kind=str(item["claim"].get("kind") or "fact"),
                    has_value=bool(item["claim"].get("value_text")),
                )
            ),
        }
        for item in candidates
    ]
    worksheet = {
        "schema_version": "claims-treatment-adjudication-worksheet-1",
        "status": "pending_named_human_adjudication",
        "created_on": "2026-10-14",
        "model_calls": 0,
        "gold_not_exposed_to_model": True,
        "freeze": {
            "manifest": str(manifest_path.relative_to(ROOT)),
            "manifest_sha256": sha256(manifest_path),
            "execution_summary_sha256": sha256(summary_path),
        },
        "execution": {
            "new_model_calls": summary.get("new_model_calls"),
            "authorised_ceiling": summary.get("authorised_ceiling"),
        },
        "signed_rules": rules,
        "stage2_measured": measured,
        "candidate_count": len(rows),
        "adjudication_fields_required_by_contract": [
            "candidate_id",
            "stage",
            "role",
            "source_id",
            "original_candidate",
            "judgement",
            "matched_gold_id",
            "canonical_observed_fields",
            "reviewer",
            "reason",
            "evidence",
        ],
        "instructions": (
            "逐条裁定：把 judgement 填 matched / correct_extra / incorrect / duplicate，matched 时填 "
            "matched_gold_id；reviewer 与 adjudicator 具名、review_status 改 accepted。"
            "填完后由冻结脚本补 stage/source_id/reason/evidence 四项并产出 signed 件。"
        ),
        "adjudications": rows,
    }
    return {"worksheet": worksheet, "rules": rules}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze", type=Path, default=FREEZE_DEFAULT)
    parser.add_argument("--out", type=Path, default=OUT_DEFAULT)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    result = build(args.freeze, args.out)
    measured = result["worksheet"]["stage2_measured"]
    rules = result["rules"]
    measure_payload = (
        json.dumps({"measured": measured, "signed_rules": rules}, ensure_ascii=False, indent=2)
        + "\n"
    ).encode("utf-8")

    outputs: dict[str, bytes] = {"stage2-proxies.json": measure_payload}
    if rules["passed"]:
        outputs["candidate-adjudications.worksheet.json"] = (
            json.dumps(result["worksheet"], ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8")
    else:
        outputs["stage2-failed.json"] = (
            json.dumps(
                {
                    "schema_version": "claims-treatment-stage2-failed-1",
                    "verdict": "产出侧修复未达预期（按已签止损判据）",
                    "measured": measured,
                    "signed_rules": rules,
                    "consequence": "不生成工作表、不进入阶段 3、不消耗人工裁定预算",
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        ).encode("utf-8")

    args.out.mkdir(parents=True, exist_ok=True)
    targets = {name: args.out / name for name in outputs}
    for name, target in targets.items():
        assert_writable(target, reason="102 号新池裁定工作表")
        if target.exists() and not args.force:
            raise SystemExit(f"refusing to overwrite existing output {name}; use --force")
    for name, data in outputs.items():
        write_once(targets[name], data.decode("utf-8"), allow_overwrite=True)
    print(
        json.dumps({"measured": measured, "passed": rules["passed"]}, ensure_ascii=False, indent=2)
    )
    return 0 if rules["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
