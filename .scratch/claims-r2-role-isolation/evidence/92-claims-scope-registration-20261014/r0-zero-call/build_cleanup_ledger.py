"""Zero-call cleanup ledger: C1 scope registration + the C4 axis-table landing.

Two signed-but-unlanded items are closed here:

1. **C1 scope registration** (contract v4.4 ``claims_scope``): every candidate the claims gate
   moved out of its scope must be registered on the items/relations side as *pending coverage*,
   never silently dropped. The ledger lists all of them with their owner role and status, and
   ``tools/check_claims_gate.py`` asserts set equality against the gate's own out-of-scope list.
2. **C4 use grading** (contract v4.4 ``claims_use_grading``): the axis mechanism is in code
   (``plugins/corpus/claim_use_axes``). The default mapping is the conservative reading and
   reproduces the legacy outcome on the frozen pool; the alternative reading is measured here as
   a counterfactual, because switching to it is a caliber change needing a signed revision.

Zero model calls; read-only with respect to every frozen artifact.

Usage:
    python build_cleanup_ledger.py [--no-write] [--force]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]  # .scratch/claims-r2-role-isolation
REPO_ROOT = ROOT.parents[1]
sys.path.insert(0, str(REPO_ROOT))

from plugins.corpus.claim_use_axes import REASON_AXIS, uses_for  # noqa: E402
from tools.check_claims_gate import Inputs, run_checks  # noqa: E402

LEDGER_ON = "2026-10-14"
SIGNED_GATE = (
    ROOT / "evidence/91-claims-gate-v3-signed-20261014/r0-zero-call/claims-gate-v3.json"
)
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
GATE_V3_DRAFT = (
    ROOT / "evidence/90-claims-gate-v3-and-run-20261014/r0-zero-call/claims-gate-v3.proposed.json"
)
C4_AXES_SWITCH = (
    "source_qualified_context_requires_review",
    "qualifier_definition_unverified",
)

INPUTS = {
    "claims_gate_v3_signed": SIGNED_GATE,
    "signed_scoring_contract_v4.4": SIGNED_CONTRACT,
    "p1r5_candidate_adjudications_signed": POOL,
    "frozen_gold_r2": GOLD,
    "claims_gate_v3_draft": GATE_V3_DRAFT,
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def is_role_external(claim: dict[str, Any]) -> bool:
    return claim.get("kind") == "opinion" or claim.get("value_text") in (None, "")


def doc_to_source(pool: dict[str, Any], gold: dict[str, Any]) -> dict[str, str]:
    by_id = {
        row["record_id"]: row["source_id"]
        for row in gold["records"]
        if row["role"] == "claims"
    }
    mapping: dict[str, set[str]] = {}
    for row in pool["adjudications"]:
        if row.get("judgement") != "matched":
            continue
        doc = str(row["original_candidate"]["claim"].get("doc_id"))
        mapping.setdefault(doc, set()).add(by_id[str(row["matched_gold_id"])])
    ambiguous = {doc: sorted(s) for doc, s in mapping.items() if len(s) != 1}
    if ambiguous:
        raise SystemExit(f"doc->source not functional: {ambiguous}")
    return {doc: next(iter(s)) for doc, s in mapping.items()}


def build_registration(
    gate: dict[str, Any], contract: dict[str, Any]
) -> dict[str, Any]:
    pool = load(POOL)
    sources = doc_to_source(pool, load(GOLD))
    moved = list((gate["measured_run"]["assembled"] or {}).get("out_of_scope_ids") or [])
    by_id = {row["candidate_id"]: row for row in pool["adjudications"]}
    entries = []
    for candidate_id in sorted(moved):
        row = by_id[candidate_id]
        claim = row["original_candidate"]["claim"]
        doc_id = str(claim.get("doc_id"))
        entries.append(
            {
                "candidate_id": candidate_id,
                "doc_id": doc_id,
                "source_id": sources[doc_id],
                "claim_text": claim.get("claim_text"),
                "role_external_reason": (
                    "kind=opinion" if claim.get("kind") == "opinion" else "no value_text"
                ),
                "owner_role": "material_items",
                "owner_source_id": sources[doc_id],
                "status": "pending_coverage",
                "registered_on": LEDGER_ON,
            }
        )
    return {
        "schema_version": "claims-scope-registration-1",
        "created_on": LEDGER_ON,
        "zero_model_calls": True,
        "basis": {
            "contract": str(SIGNED_CONTRACT.relative_to(ROOT)),
            "clause": contract["claims_scope"]["predicate"],
            "rule": "移出 claims 判据的候选必须在 items/relations 侧登记为待覆盖，不得就地丢弃",
            "gate": str(SIGNED_GATE.relative_to(ROOT)),
        },
        "entries": entries,
        "summary": {
            "moved_out": len(entries),
            "by_reason": {
                reason: sum(1 for e in entries if e["role_external_reason"] == reason)
                for reason in sorted({e["role_external_reason"] for e in entries})
            },
            "by_source": {
                source: sum(1 for e in entries if e["source_id"] == source)
                for source in sorted({e["source_id"] for e in entries})
            },
            "coverage_status_note": (
                "pending_coverage 表示该内容尚未由任何角色覆盖；本条目不构成 items/relations 的"
                "已覆盖证明，须由对应角色的门另行出分"
            ),
        },
    }


def c4_counterfactual() -> dict[str, Any]:
    """Measure the axis-table landing: default vs the two-code remap, on the frozen pool."""
    pool = load(POOL)
    correct = [r for r in pool["adjudications"] if r["judgement"] in {"matched", "correct_extra"}]

    def grant(claim: dict[str, Any], table: dict[str, str]) -> tuple[bool, bool]:
        codes = list(claim.get("reason_codes") or ())
        remapped = {code: table.get(code, REASON_AXIS.get(code)) for code in codes}
        # Re-evaluate through the module's own semantics with the alternative mapping.
        withdrawn: set[str] = set()
        for code, axis in remapped.items():
            if axis is None:
                withdrawn |= {"compare", "calculate"}
            elif axis in {"attribution", "perspective", "source_stance"}:
                continue
            else:
                withdrawn |= {"compare", "calculate"}
        if claim.get("kind") == "opinion" or claim.get("value_text") in (None, ""):
            withdrawn |= {"compare", "calculate"}
        return ("compare" not in withdrawn, "calculate" not in withdrawn)

    default_ok = sum(1 for r in correct if uses_for(
        r["original_candidate"]["claim"].get("reason_codes") or (),
        kind=r["original_candidate"]["claim"].get("kind") or "fact",
        has_value=r["original_candidate"]["claim"].get("value_text") not in (None, ""),
    ) == ("cite", "compare", "calculate"))
    switch_table = {code: "attribution" for code in C4_AXES_SWITCH}
    switch_ok = sum(
        1
        for r in correct
        if all(grant(r["original_candidate"]["claim"], switch_table))
    )
    legacy_ok = sum(1 for r in correct if not (r["original_candidate"]["claim"].get("reason_codes") or ()))
    return {
        "correct_records": len(correct),
        "legacy_all_or_nothing": legacy_ok,
        "landed_default_policy": default_ok,
        "default_equals_legacy": default_ok == legacy_ok,
        "counterfactual_two_code_remap": switch_ok,
        "counterfactual_remap_codes": list(C4_AXES_SWITCH),
        "counterfactual_needs": "把这两个码从 condition 轴改挂 attribution 轴（口径变更，须签认）",
        "vocabulary_note": (
            "attribution/perspective/source_stance 是 cite 侧轴，在 {cite, compare, calculate} "
            "词表下不撤任何用途；因此该改动等于放行带条件语境的数值断言参与比较与计算"
        ),
    }


def build() -> dict[str, Any]:
    gate = load(SIGNED_GATE)
    contract = load(SIGNED_CONTRACT)
    registration = build_registration(gate, contract)
    counterfactual = c4_counterfactual()
    ledger = {
        "schema_version": "claims-zero-call-cleanup-1",
        "created_on": LEDGER_ON,
        "zero_model_calls": True,
        "items_closed": [
            {
                "id": "C1-scope-registration",
                "status": "landed",
                "artifact": "claims-scope-registration.json",
                "check": "tools/check_claims_gate.py::c1-scope-registration",
                "entries": len(registration["entries"]),
            },
            {
                "id": "C4-use-grading",
                "status": "landed_mechanism_default_conservative",
                "artifact": "plugins/corpus/claim_use_axes.py",
                "check": "tests/test_corpus_claim_use_axes.py（含词表一致性 AST 扫描）",
                "measured": counterfactual,
            },
        ],
        "c4_axis_table": {
            "in_force": "conservative（condition/qualifier 轴撤去 compare/calculate）",
            "cite_side_axes": ["attribution", "perspective", "source_stance"],
            "registered_codes": sorted(REASON_AXIS),
        },
        "prior_record_updates": [
            {
                "record": "evidence/89-claims-v44-signed-landing-20261014/r0-zero-call",
                "line": "still_pending: 『C4 用途分级实现』『C1 移出项的 items/relations 侧覆盖登记』",
                "now": "两项均已落地（见 items_closed）；89 号字节不改写",
            },
            {
                "record": "evidence/89-claims-v44-signed-landing-20261014/r0-zero-call",
                "line": "changed_files 中 tools/check_claims_gate.py 的哈希",
                "now": "该文件在本轮继续演进（新增 c1-scope-registration、输入名映射、形状兼容），89 号记录为上一轮快照",
            },
        ],
        "pending_human_decision": [
            "D-1 accepted 总数/分源下限（a/b/c）",
            "D-2 放行线的分源精度轴是否新增",
            "C4 是否把 source_qualified_context_requires_review / qualifier_definition_unverified "
            "改挂 attribution 轴（+16 条可算，见 measured.counterfactual）",
        ],
        "not_in_scope": [
            "不改 frozen-gold / P1R5 已签裁定 / items 门 v3 / 契约 v4.3 v4.4 / 已签门 v3 字节",
            "不执行模型调用、不重跑抽取、不发布",
        ],
    }
    manifest = {
        "schema_version": "claims-zero-call-cleanup-manifest-1",
        "status": "draft",
        "created_on": LEDGER_ON,
        "model_calls": 0,
        "inputs": {name: sha256(path) for name, path in INPUTS.items()},
        "outputs": {},
    }
    return {"registration": registration, "ledger": ledger, "manifest": manifest}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    result = build()
    outputs = {
        "claims-scope-registration.json": (
            json.dumps(result["registration"], ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8"),
        "cleanup-ledger.json": (
            json.dumps(result["ledger"], ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8"),
    }
    if args.no_write:
        print(json.dumps(result["ledger"], ensure_ascii=False, indent=2))
        print(f"[no-write] {len(outputs)} outputs computed; nothing written.")
        return 0

    for name, data in outputs.items():
        (HERE / name).write_bytes(data)
    checks = run_checks(Inputs())
    blocking = [c.check_id for c in checks if c.blocking and c.verdict == "fail"]
    manifest = result["manifest"]
    manifest["outputs"] = {name: hashlib.sha256(data).hexdigest() for name, data in outputs.items()}
    manifest["conformance"] = {
        "check_count": len(checks),
        "blocking_failures": blocking,
        "c1_scope_registration": next(
            c.verdict for c in checks if c.check_id == "c1-scope-registration"
        ),
    }
    (HERE / "MANIFEST.json").write_bytes(
        (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    )
    print(f"wrote {len(outputs) + 1} files to {HERE}")
    print(json.dumps(manifest["outputs"], ensure_ascii=False, indent=2))
    print(json.dumps(manifest["conformance"], ensure_ascii=False, indent=2))
    return 1 if blocking else 0


if __name__ == "__main__":
    sys.exit(main())
