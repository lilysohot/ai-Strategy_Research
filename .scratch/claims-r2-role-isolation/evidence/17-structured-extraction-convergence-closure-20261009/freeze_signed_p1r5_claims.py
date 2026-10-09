"""Freeze the explicitly xyl-signed P1R5 Claims adjudication draft."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
ROOT = HERE / "p1r5-claims-adjudication-v2"
DRAFT = ROOT / "candidate-adjudications.agent-draft.json"
PREVIEW = ROOT / "gate-preview.json"
SIGNED = ROOT / "candidate-adjudications.signed.json"
STATE = ROOT / "candidate-adjudication-freeze-state.json"
GATE = ROOT / "claims-gate-result.signed.json"
SUMMARY = ROOT / "candidate-adjudication-summary.signed.md"
MANIFEST = ROOT / "candidate-adjudication-freeze-manifest.json"
OUTPUTS = (SIGNED, STATE, GATE, SUMMARY, MANIFEST)
SIGNER = "xyl"
SIGNED_ON = "2026-10-09"
SIGNOFF_EVIDENCE = [
    "user_chat_2026-10-09_p1r5_candidate_adjudications_agent_draft_signed",
]
EXPECTED_UNSIGNED_DRAFT_SHA256 = (
    "f93ca445834b16a7110fb32f984d87876fcdf2c44fd515e78e3b3297ca5d39f0"
)
TERMINAL = {"matched", "correct_extra", "incorrect", "duplicate", "out_of_scope"}


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative(path: Path) -> str:
    return str(path.relative_to(REPO))


def save_json(path: Path, value: object) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def checked_inputs() -> tuple[dict[str, Any], dict[str, Any], Counter[str]]:
    draft = read_json(DRAFT)
    preview = read_json(PREVIEW)
    if draft.get("reviewer") != SIGNER or draft.get("adjudicator") != SIGNER:
        raise SystemExit("P1R5 draft does not contain the named xyl signature")
    unsigned = dict(draft)
    unsigned["reviewer"] = None
    unsigned["adjudicator"] = None
    unsigned_bytes = (json.dumps(unsigned, ensure_ascii=False, indent=2) + "\n").encode()
    unsigned_sha256 = hashlib.sha256(unsigned_bytes).hexdigest()
    if unsigned_sha256 != EXPECTED_UNSIGNED_DRAFT_SHA256:
        raise SystemExit("P1R5 signed draft changed beyond the two signature fields")
    if (
        preview.get("evidence", {}).get("adjudication_draft_sha256")
        != EXPECTED_UNSIGNED_DRAFT_SHA256
    ):
        raise SystemExit("gate preview does not bind the signed draft")
    if draft.get("status") != "agent_pre_adjudicated_pending_named_human_signoff":
        raise SystemExit("unexpected P1R5 draft status")
    rows = draft.get("adjudications", [])
    ids = [row.get("candidate_id") for row in rows]
    if draft.get("candidate_count") != 110 or len(rows) != 110 or len(set(ids)) != 110:
        raise SystemExit("P1R5 candidate roster changed")
    if draft.get("pending_delta_decisions") != 36:
        raise SystemExit("P1R5 pending delta decision count changed")
    if any(row.get("role") != "claims" or row.get("judgement") not in TERMINAL for row in rows):
        raise SystemExit("P1R5 draft contains a non-terminal or non-Claims row")
    counts: Counter[str] = Counter(str(row["judgement"]) for row in rows)
    expected = {"matched": 20, "correct_extra": 36, "incorrect": 51, "duplicate": 3}
    if dict(counts) != expected or preview.get("judgements") != expected:
        raise SystemExit(f"P1R5 judgement counts changed: {dict(counts)}")
    matched_ids = sorted(
        str(row["matched_gold_id"])
        for row in rows
        if row["judgement"] == "matched"
    )
    expected_ids = [f"NT-C{index:02d}" for index in range(1, 21)]
    if matched_ids != expected_ids or preview.get("matched_gold_ids") != expected_ids:
        raise SystemExit("P1R5 matched gold roster changed")
    return draft, preview, counts


def build() -> None:
    if any(path.exists() for path in OUTPUTS):
        raise SystemExit("refusing to overwrite immutable P1R5 signed outputs")
    draft, preview, counts = checked_inputs()
    rows = []
    for row in draft["adjudications"]:
        signed = dict(row)
        signed["stage"] = "human_adjudicated_candidate"
        signed["reviewer"] = SIGNER
        signed["adjudicator"] = SIGNER
        signed["review_status"] = "accepted"
        signed["human_acceptance_reason"] = (
            "用户于 2026-10-09 具名签认 P1R5 candidate-adjudications.agent-draft.json；"
            "逐条代理建议原样接受。"
        )
        signed["changes"] = []
        rows.append(signed)

    precision = (counts["matched"] + counts["correct_extra"]) / len(rows)
    recall = counts["matched"] / 20
    precision_floor = float(preview["candidate_precision_floor"])
    recall_floor = float(preview["target_recall_floor"])
    quality_passed = precision >= precision_floor and recall >= recall_floor
    if not quality_passed:
        raise SystemExit("signed P1R5 Claims metrics do not pass the frozen floor")

    signed = {
        "schema_version": "claims-p1r5-candidate-adjudications-freeze-1",
        "status": "frozen",
        "formal_candidate_adjudications_frozen": True,
        "human_gate_satisfied": True,
        "signed_on": SIGNED_ON,
        "reviewer": SIGNER,
        "adjudicator": SIGNER,
        "signoff_evidence": SIGNOFF_EVIDENCE,
        "parent_draft": relative(DRAFT),
        "parent_draft_sha256": f"sha256:{sha256(DRAFT)}",
        "gate_preview": relative(PREVIEW),
        "gate_preview_sha256": f"sha256:{sha256(PREVIEW)}",
        "candidate_count": len(rows),
        "unresolved_count": 0,
        "inherited_signed_decisions": draft["inherited_signed_decisions"],
        "newly_signed_delta_decisions": draft["pending_delta_decisions"],
        "judgements": dict(counts),
        "candidate_precision": precision,
        "target_recall": recall,
        "quality_gate_passed": True,
        "copper_execution_authorized": True,
        "publication_authorized": False,
        "model_calls_during_freeze": 0,
        "production_database_access": 0,
        "adjudications": rows,
    }
    state = {
        "schema_version": "claims-p1r5-candidate-adjudication-freeze-state-1",
        "status": "frozen_quality_gate_passed_copper_authorized",
        "formal_candidate_adjudications_frozen": True,
        "human_gate_satisfied": True,
        "quality_gate_passed": True,
        "copper_execution_authorized": True,
        "publication_authorized": False,
        "reviewer": SIGNER,
        "adjudicator": SIGNER,
        "signoff_evidence": SIGNOFF_EVIDENCE,
        "candidate_count": len(rows),
        "unresolved_count": 0,
        "model_calls_during_freeze": 0,
        "production_database_access": 0,
        "next_gate": "execute frozen copper material_items, then material_relations only if items are valid",
    }
    gate = {
        "schema_version": "claims-p1r5-signed-gate-result-1",
        "status": "passed",
        "signed_on": SIGNED_ON,
        "reviewer": SIGNER,
        "adjudicator": SIGNER,
        "candidate_count": len(rows),
        "judgements": dict(counts),
        "candidate_precision": precision,
        "candidate_precision_floor": precision_floor,
        "target_recall": recall,
        "target_recall_floor": recall_floor,
        "matched_gold_ids": preview["matched_gold_ids"],
        "pending_delta_decisions": 0,
        "human_gate_satisfied": True,
        "quality_gate_passed": True,
        "authorize_copper_execution": True,
        "authorize_publication": False,
        "signed_adjudication": relative(SIGNED),
        "model_calls": 0,
        "production_database_access": 0,
    }
    save_json(SIGNED, signed)
    save_json(STATE, state)
    save_json(GATE, gate)
    with SUMMARY.open("x", encoding="utf-8") as stream:
        stream.write(
            "# P1R5 Claims signed adjudication\n\n"
            f"Date: {SIGNED_ON}  \nReviewer/adjudicator: `{SIGNER}`  \n"
            "Status: frozen; Claims quality gate passed; copper execution authorized; publication blocked\n\n"
            f"The signed roster contains {len(rows)} candidates: {counts['matched']} matched, "
            f"{counts['correct_extra']} correct extra, {counts['incorrect']} incorrect, and "
            f"{counts['duplicate']} duplicate. Candidate precision is {precision:.2%} "
            f"(floor {precision_floor:.2%}); target recall is {recall:.2%} "
            f"(floor {recall_floor:.2%}).\n\n"
            "The freeze made zero model calls and performed no production-database or publication writes.\n"
        )
    save_json(
        MANIFEST,
        {
            "schema_version": "claims-p1r5-candidate-adjudication-freeze-manifest-1",
            "status": "frozen",
            "created_on": SIGNED_ON,
            "reviewer": SIGNER,
            "adjudicator": SIGNER,
            "signoff_evidence": SIGNOFF_EVIDENCE,
            "human_gate_satisfied": True,
            "quality_gate_passed": True,
            "copper_execution_authorized": True,
            "publication_authorized": False,
            "inputs": {relative(path): sha256(path) for path in (DRAFT, PREVIEW)},
            "outputs": {
                relative(path): sha256(path)
                for path in (Path(__file__), SIGNED, STATE, GATE, SUMMARY)
            },
            "model_calls": 0,
            "production_database_access": 0,
        },
    )


def verify() -> None:
    checked_inputs()
    manifest = read_json(MANIFEST)
    if (
        manifest.get("status") != "frozen"
        or manifest.get("human_gate_satisfied") is not True
        or manifest.get("quality_gate_passed") is not True
        or manifest.get("copper_execution_authorized") is not True
        or manifest.get("publication_authorized") is not False
    ):
        raise SystemExit("invalid P1R5 signed freeze state")
    for group in ("inputs", "outputs"):
        for name, expected in manifest[group].items():
            if sha256(REPO / name) != expected:
                raise SystemExit(f"hash mismatch: {name}")
    signed = read_json(SIGNED)
    rows = signed["adjudications"]
    if (
        signed.get("candidate_count") != 110
        or signed.get("unresolved_count") != 0
        or len(rows) != 110
        or any(
            row.get("reviewer") != SIGNER
            or row.get("adjudicator") != SIGNER
            or row.get("review_status") != "accepted"
            for row in rows
        )
    ):
        raise SystemExit("signed P1R5 adjudication roster is incomplete")
    gate = read_json(GATE)
    if gate.get("status") != "passed" or gate.get("authorize_copper_execution") is not True:
        raise SystemExit("signed P1R5 gate does not authorize copper")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("build", "verify"))
    args = parser.parse_args()
    if args.action == "build":
        build()
    verify()
    print(json.dumps(read_json(GATE), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

