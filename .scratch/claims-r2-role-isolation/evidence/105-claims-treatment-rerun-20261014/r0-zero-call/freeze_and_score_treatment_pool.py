"""Freeze the xyl-signed treatment worksheet and score the new pool (105 号, two subcommands).

``freeze`` — turn the explicitly signed ``candidate-adjudications.worksheet.json`` (93/93 accepted,
reviewer/adjudicator = xyl) into the immutable ``candidate-adjudications.signed.json``: the signed
worksheet bytes are pinned by hash, the judgement roster is asserted (matched 20 covering
NT-C01..NT-C20 exactly), and stage/source_id/reason/evidence are filled deterministically — the
doc→source mapping is derived from the matched rows and asserted functional and total over the two
docs (the same measurement the 90-号 adapter recorded, not an invention).

``score`` — assemble the signed pool through the signed read path (contract v4.4) and score it with
the signed gate requirements, then read the result through the pre-registered tiers of the effective
v4 record (A ≥ 0.80 + guardrails green / B 0.60–0.80 / C < 0.60 or a guardrail broken). Zero model
calls; nothing here can change a judgement.

Usage:
    python freeze_and_score_treatment_pool.py freeze
    python freeze_and_score_treatment_pool.py score
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]  # .scratch/claims-r2-role-isolation
REPO_ROOT = ROOT.parents[1]
sys.path.insert(0, str(REPO_ROOT))

from tools.evidence_guard import assert_writable, write_once  # noqa: E402

WORKSHEET = HERE / "treatment-adjudication/candidate-adjudications.worksheet.json"
SIGNED = HERE / "treatment-adjudication/candidate-adjudications.signed.json"
FREEZE_STATE = HERE / "treatment-adjudication/adjudication-freeze-state.json"
RUN_RECORD = HERE / "claims-treatment-run-record.json"
GATE_V3_DRIVER = (
    ROOT / "evidence/90-claims-gate-v3-and-run-20261014/r0-zero-call/build_gate_v3_and_run.py"
)
CONTRACT = (
    ROOT / "evidence/88-claims-contract-v44-signed-20261014/r0-zero-call/scoring-contract-v4.4.json"
)
V4_EFFECTIVE = (
    ROOT / "evidence/104-claims-prereg-v4-amendment-20261014/r0-zero-call/claims-preregistration-v4.json"
)

SIGNER = "xyl"
TERMINAL = {"matched", "correct_extra", "incorrect", "duplicate"}
EXPECTED_MATCHED_IDS = [f"NT-C{index:02d}" for index in range(1, 21)]
ACCEPTANCE_NOTE = (
    "U 于 2026-10-14 在 105 号 worksheet 上逐行具名裁定并签认"
    "（93/93 accepted，reviewer/adjudicator=xyl，judgement 分布 matched 20 / correct_extra 64 / "
    "incorrect 3 / duplicate 6）；本件原样冻结，不代改任何 judgement。"
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_gate_driver() -> Any:
    spec = importlib.util.spec_from_file_location("build_gate_v3_and_run", GATE_V3_DRIVER)
    if spec is None or spec.loader is None:
        raise SystemExit(f"refusing: cannot load 90-号 scoring driver at {GATE_V3_DRIVER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check_signed_worksheet(rows: list[dict[str, Any]]) -> Counter[str]:
    if len(rows) != 93 or len({row["candidate_id"] for row in rows}) != 93:
        raise SystemExit("refusing to freeze: worksheet roster is not 93 unique candidates")
    for row in rows:
        if row.get("review_status") != "accepted":
            raise SystemExit(f"refusing to freeze: {row['candidate_id']} is not accepted")
        if row.get("reviewer") != SIGNER or row.get("adjudicator") != SIGNER:
            raise SystemExit(f"refusing to freeze: {row['candidate_id']} is not named-signed")
        if row.get("judgement") not in TERMINAL:
            raise SystemExit(f"refusing to freeze: {row['candidate_id']} judgement is not terminal")
    counts = Counter(str(row["judgement"]) for row in rows)
    matched_ids = sorted(
        str(row["matched_gold_id"]) for row in rows if row["judgement"] == "matched"
    )
    if matched_ids != EXPECTED_MATCHED_IDS:
        raise SystemExit(f"refusing to freeze: matched roster is {matched_ids}")
    if counts["matched"] != 20:
        raise SystemExit("refusing to freeze: matched count is not 20")
    return counts


def derive_doc_to_source(rows: list[dict[str, Any]], gold_by_id: dict[str, str]) -> dict[str, str]:
    mapping: dict[str, set[str]] = {}
    for row in rows:
        if row["judgement"] != "matched":
            continue
        doc = str(row["original_candidate"]["claim"]["doc_id"])
        mapping.setdefault(doc, set()).add(gold_by_id[str(row["matched_gold_id"])])
    ambiguous = {doc: sorted(sources) for doc, sources in mapping.items() if len(sources) != 1}
    if ambiguous:
        raise SystemExit(f"doc->source mapping is not functional: {ambiguous}")
    expected_docs = {str(row["original_candidate"]["claim"]["doc_id"]) for row in rows}
    if set(mapping) != expected_docs:
        raise SystemExit("doc->source mapping does not cover every candidate doc_id")
    return {doc: next(iter(sources)) for doc, sources in mapping.items()}


def cmd_freeze() -> int:
    if SIGNED.exists() or FREEZE_STATE.exists():
        raise SystemExit("refusing to overwrite immutable signed outputs; they are write-once")
    worksheet = load(WORKSHEET)
    rows = worksheet["adjudications"]
    counts = check_signed_worksheet(rows)

    driver = load_gate_driver()
    gold = driver.build_gold()
    gold_by_id = {item.record_id: item.source_id for item in gold}
    doc_to_source = derive_doc_to_source(rows, gold_by_id)

    signed_rows = []
    for row in rows:
        claim = row["original_candidate"]["claim"]
        signed = dict(row)
        signed["stage"] = "human_adjudicated_candidate"
        signed["source_id"] = doc_to_source[str(claim["doc_id"])]
        signed["reason"] = (
            "C1 role scope + signed treatment adjudication; deterministic carriers recomputed"
        )
        signed["evidence"] = ACCEPTANCE_NOTE
        signed["human_acceptance_reason"] = ACCEPTANCE_NOTE
        signed_rows.append(signed)

    signed = {
        "schema_version": "claims-treatment-adjudications-signed-1",
        "id": "105-claims-treatment-rerun-20261014",
        "status": "frozen_signed",
        "created_on": "2026-10-14",
        "model_calls": 0,
        "candidate_count": len(signed_rows),
        "source_worksheet": {
            "path": str(WORKSHEET.relative_to(ROOT)),
            "sha256": sha256(WORKSHEET),
            "note": "签认的是这份字节：93/93 accepted、judgement 分布见 freeze-state",
        },
        "doc_to_source": doc_to_source,
        "adjudications": signed_rows,
    }
    state = {
        "schema_version": "claims-treatment-adjudication-freeze-state-1",
        "frozen_on": "2026-10-14",
        "worksheet_sha256": sha256(WORKSHEET),
        "signed_sha256": hashlib.sha256(
            (json.dumps(signed, ensure_ascii=False, indent=2) + "\n").encode()
        ).hexdigest(),
        "judgement_counts": dict(counts),
        "matched_gold_ids": EXPECTED_MATCHED_IDS,
        "doc_to_source": doc_to_source,
        "reviewer": SIGNER,
        "adjudicator": SIGNER,
    }
    for path, payload in ((SIGNED, signed), (FREEZE_STATE, state)):
        assert_writable(path, reason="105 号裁定冻结件")
        write_once(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    print(f"froze {len(signed_rows)} rows -> {SIGNED.name}")
    print(json.dumps(state, ensure_ascii=False, indent=2))
    return 0


def cmd_score() -> int:
    if not SIGNED.exists():
        raise SystemExit("refusing to score: signed pool missing (run `freeze` first)")
    if RUN_RECORD.exists():
        raise SystemExit("refusing to overwrite the run record (write-once)")
    driver = load_gate_driver()
    pool = load(SIGNED)
    gold = driver.build_gold()
    base = driver.load_contract_gate_requirements(CONTRACT, role=driver.Role.CLAIMS)
    adjudications, catalog, moved_out = driver.build_adjudications(pool)
    assembly = driver.assemble_scoring_input(adjudications, catalog=catalog, allowed_source_ids=None)
    report = driver.score_structured_quality(
        gold,
        matching_mode=driver.MatchingMode.ADJUDICATED,
        raw_candidates=assembly.validated,
        validated_candidates=assembly.validated,
        raw_mappings=assembly.mappings,
        validated_mappings=assembly.mappings,
        gate_requirements=base,
    )
    metrics = report.validated.role(driver.Role.CLAIMS)
    matched_gold = sorted(report.validated.matched_gold_ids)
    numerator = metrics.tp + metrics.correct_extra
    denominator = numerator + metrics.fp
    precision = numerator / denominator
    recall = f"{metrics.tp}/{metrics.tp + metrics.fn}"
    unresolved = metrics.fn  # gold targets with no candidate (unresolved candidates)
    sentinels = [item for item in base.high_risk_item_assertions_required]
    sentinels_hit = [item for item in sentinels if item in matched_gold]

    guardrails = {
        "target_recall": {"value": recall, "passed": metrics.tp == 20},
        "unresolved_candidates": {"value": unresolved, "passed": unresolved == 0},
        "sentinels": {
            "value": f"{len(sentinels_hit)}/{len(sentinels)}",
            "passed": len(sentinels_hit) == len(sentinels),
        },
    }
    guardrails_green = all(item["passed"] for item in guardrails.values())
    if guardrails_green and precision >= 0.80:
        tier, reading = "A_keep_and_pass_target", "claims 保留，且目标线达成"
    elif guardrails_green and precision >= 0.60:
        tier, reading = "B_conditional_keep", "有条件保留：停在放行线，不宣称质量达标"
    else:
        tier, reading = "C_drop_from_default_path", "产出侧修复不足以支撑 claims 角色"

    per_source_precision: dict[str, str] = {}
    for source in sorted({item.source_id for item in gold}):
        rows = [r for r in pool["adjudications"] if r["source_id"] == source]
        num = sum(1 for r in rows if r["judgement"] in {"matched", "correct_extra"})
        per_source_precision[source[:20]] = f"{num}/{len(rows)} = {num / len(rows):.4f}"

    record = {
        "schema_version": "claims-treatment-run-record-1",
        "id": "105-claims-treatment-rerun-20261014",
        "run_on": "2026-10-14",
        "model_calls": 0,
        "pool": {
            "path": str(SIGNED.relative_to(ROOT)),
            "sha256": sha256(SIGNED),
            "worksheet_sha256": sha256(WORKSHEET),
            "stage": "human_adjudicated_candidate（呈现为 validated 切片，raw 切片为空——与 90 号同构）",
        },
        "criteria": {
            "contract": str(CONTRACT.relative_to(ROOT)),
            "contract_sha256": sha256(CONTRACT),
            "tiers_source": str(V4_EFFECTIVE.relative_to(ROOT)),
            "tiers_source_sha256": sha256(V4_EFFECTIVE),
            "note": "档位判定读 99/104 号预注册：主指标 + 质量护栏；accepted 下限轴已退出判定",
        },
        "metrics": {
            "candidate_precision": f"{numerator}/{denominator} = {precision:.4f}",
            "target_recall": recall,
            "unresolved_candidates": unresolved,
            "sentinels": f"{len(sentinels_hit)}/{len(sentinels)}",
            "per_source_precision_diagnostic": per_source_precision,
        },
        "ledger": {
            "judgement_counts": dict(Counter(str(r["judgement"]) for r in pool["adjudications"])),
            "matched_gold_ids": matched_gold,
            "assembled": {
                "validated_candidates": len(assembly.validated),
                "mappings": len(assembly.mappings),
                "out_of_scope": len(assembly.out_of_scope),
            },
        },
        "guardrails": guardrails,
        "tier": {"id": tier, "reading": reading},
        "exit_rule_applied": (
            "99/104 号预注册档位：A = precision ≥ 0.80 且护栏全绿；B = 0.60 ≤ precision < 0.80 且护栏全绿；"
            "C = precision < 0.60 或护栏任一破"
        ),
    }
    assert_writable(RUN_RECORD, reason="105 号评分记录")
    write_once(RUN_RECORD, json.dumps(record, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(record["metrics"], ensure_ascii=False, indent=2))
    print(json.dumps(record["tier"], ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in {"freeze", "score"}:
        raise SystemExit(__doc__)
    return cmd_freeze() if sys.argv[1] == "freeze" else cmd_score()


if __name__ == "__main__":
    raise SystemExit(main())
