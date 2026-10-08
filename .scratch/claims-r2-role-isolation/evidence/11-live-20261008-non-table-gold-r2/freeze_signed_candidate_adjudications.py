"""Freeze the explicitly signed r2 candidate-adjudication draft exactly once."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
DRAFT = HERE / "candidate-adjudications.agent-draft.json"
COVERAGE = HERE / "coverage-observations.agent-draft.json"
PRE_SIGN_MANIFEST = HERE / "adjudication-manifest.agent-draft.json"
SIGNED = HERE / "candidate-adjudications.signed.json"
STATE = HERE / "candidate-adjudication-freeze-state.json"
SUMMARY = HERE / "candidate-adjudication-summary.signed.md"
MANIFEST = HERE / "candidate-adjudication-freeze-manifest.json"
OUTPUTS = (SIGNED, STATE, SUMMARY, MANIFEST)
SIGNER = "xyl"
SIGNOFF_EVIDENCE = [
    "user_file_edit_2026-10-08_human_gate_satisfied_xyl",
    "user_chat_2026-10-08_candidate-adjudications.agent-draft.json_signed",
]


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative(path: Path) -> str:
    return str(path.relative_to(REPO))


def save(path: Path, value: object) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def checked_inputs() -> tuple[dict[str, Any], dict[str, Any]]:
    draft = read_json(DRAFT)
    coverage = read_json(COVERAGE)
    pre_sign_manifest = read_json(PRE_SIGN_MANIFEST)
    rows = draft.get("adjudications", [])
    ids = [row.get("candidate_id") for row in rows]
    terminal = {"matched", "correct_extra", "incorrect", "duplicate", "out_of_scope"}
    if draft.get("status") != "human_signed_pending_freeze":
        raise SystemExit("unexpected signed candidate-adjudication status")
    if (
        draft.get("human_gate_satisfied") is not True
        or draft.get("reviewer") != SIGNER
        or draft.get("adjudicator") != SIGNER
        or draft.get("signoff_evidence") != SIGNOFF_EVIDENCE
    ):
        raise SystemExit("candidate-adjudication signature mismatch")
    if draft.get("candidate_count") != 267 or len(rows) != 267 or len(set(ids)) != 267:
        raise SystemExit("candidate roster changed")
    if draft.get("unresolved_count") != 0:
        raise SystemExit("draft still has unresolved candidates")
    if any(row.get("judgement") not in terminal for row in rows):
        raise SystemExit("non-terminal candidate judgement")
    original = dict(draft)
    original["status"] = "agent_pre_adjudicated_pending_named_human_signoff"
    original["human_gate_satisfied"] = False
    for field in ("reviewer", "adjudicator", "signoff_evidence"):
        original.pop(field, None)
    original_bytes = (json.dumps(original, ensure_ascii=False, indent=2) + "\n").encode()
    original_sha = hashlib.sha256(original_bytes).hexdigest()
    expected_original = pre_sign_manifest["outputs"][DRAFT.name]
    if original_sha != expected_original.removeprefix("sha256:"):
        raise SystemExit("signed draft changed beyond the explicit signature fields")
    if coverage.get("status") != "observed_prepublication_block":
        raise SystemExit("coverage observation state changed")
    queries = coverage.get("query_observations", [])
    if len(queries) != 2 or any(
        query["result"].get("page_status") != "not_published"
        or query["result"].get("error_codes") != ["CS_NOT_PUBLISHED"]
        or query["result"].get("records")
        for query in queries
    ):
        raise SystemExit("query observation does not prove the prepublication block")
    return draft, coverage


def build_payloads() -> tuple[dict[str, Any], dict[str, Any], str]:
    draft, coverage = checked_inputs()
    rows = []
    for row in draft["adjudications"]:
        signed = dict(row)
        signed["stage"] = "human_adjudicated_candidate"
        signed["agent_reason"] = signed.pop("reason")
        signed["reviewer"] = SIGNER
        signed["adjudicator"] = SIGNER
        signed["review_status"] = "accepted"
        signed["reason"] = (
            "用户于 2026-10-08 明确签认 candidate-adjudications.agent-draft.json；"
            "按逐条建议原样接受。"
        )
        signed["changes"] = []
        rows.append(signed)
    payload = {
        "schema_version": "corpus-candidate-adjudications-freeze-v1",
        "status": "frozen",
        "formal_candidate_adjudications_frozen": True,
        "human_gate_satisfied": True,
        "signed_on": "2026-10-08",
        "reviewer": SIGNER,
        "adjudicator": SIGNER,
        "signoff_evidence": SIGNOFF_EVIDENCE,
        "parent_draft": relative(DRAFT),
        "parent_draft_sha256": f"sha256:{sha256(DRAFT)}",
        "coverage_observation": relative(COVERAGE),
        "coverage_observation_sha256": f"sha256:{sha256(COVERAGE)}",
        "candidate_count": draft["candidate_count"],
        "unresolved_count": 0,
        "metrics": draft["metrics"],
        "quality_gate_passed": False,
        "publication_authorized": False,
        "m_main_calls": 0,
        "adjudications": rows,
    }
    state = {
        "schema_version": "corpus-candidate-adjudication-freeze-state-v1",
        "status": "frozen_quality_gate_failed",
        "formal_candidate_adjudications_frozen": True,
        "human_gate_satisfied": True,
        "quality_gate_passed": False,
        "publication_authorized": False,
        "reviewer": SIGNER,
        "adjudicator": SIGNER,
        "signoff_evidence": SIGNOFF_EVIDENCE,
        "candidate_count": 267,
        "unresolved_count": 0,
        "metrics": draft["metrics"],
        "query_status": [
            {
                "source_slug": query["source_slug"],
                "page_status": query["result"]["page_status"],
                "error_codes": query["result"]["error_codes"],
                "record_count": len(query["result"]["records"]),
            }
            for query in coverage["query_observations"]
        ],
        "delivery_status": coverage["delivery_observation"]["status"],
        "context_use_status": coverage["context_use_observation"]["status"],
        "model_calls_during_freeze": 0,
        "m_main_calls": 0,
        "production_database_access": 0,
        "next_gate": (
            "quality gate remains failed; do not publish or run M_main; fix and refreeze a new "
            "candidate version before any successor trial"
        ),
    }
    metrics = draft["metrics"]
    summary = "\n".join(
        [
            "# Signed r2 candidate adjudication and prepublication observation",
            "",
            "Date: 2026-10-08  ",
            f"Reviewer/adjudicator: `{SIGNER}`  ",
            "Status: signed and frozen; quality gate failed",
            "",
            "The user explicitly signed `candidate-adjudications.agent-draft.json`. The frozen "
            "successor preserves all 267 terminal decisions unchanged and records the agent rationale "
            "beside the human acceptance. No model or production-database call was made during freeze.",
            "",
            "| role | candidates | matched | correct extra | incorrect | duplicate | precision | target recall |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
            _metric_line("claims", metrics["claims"]),
            _metric_line("material_items", metrics["material_items"]),
            _metric_line("material_relations", metrics["material_relations"]),
            "",
            "Both exact source/build queries returned `CS_NOT_PUBLISHED` and zero records. Therefore "
            "delivery remained `not_delivered`, context use remained `not_used`, and M_main calls remained "
            "zero. The signed adjudication resolves the human-review gate only; it does not authorize "
            "publication and cannot turn these failed rates into a passing quality result.",
            "",
        ]
    )
    return payload, state, summary


def _metric_line(role: str, row: dict[str, Any]) -> str:
    counts = row["judgements"]
    precision = row["candidate_precision"]["decimal"]
    recall = row["target_recall"]["decimal"]
    p = "N/A" if precision is None else f"{precision:.2%}"
    r = "N/A" if recall is None else f"{recall:.2%}"
    return (
        f"| {role} | {row['raw_candidate_count']} | {counts.get('matched', 0)} | "
        f"{counts.get('correct_extra', 0)} | {counts.get('incorrect', 0)} | "
        f"{counts.get('duplicate', 0)} | {p} | {r} |"
    )


def build() -> None:
    if any(path.exists() for path in OUTPUTS):
        raise SystemExit("refusing to overwrite immutable signed adjudication outputs")
    payload, state, summary = build_payloads()
    save(SIGNED, payload)
    save(STATE, state)
    with SUMMARY.open("x", encoding="utf-8") as stream:
        stream.write(summary)
    inputs = (DRAFT, COVERAGE, PRE_SIGN_MANIFEST)
    outputs = (Path(__file__), SIGNED, STATE, SUMMARY)
    save(
        MANIFEST,
        {
            "schema_version": "corpus-candidate-adjudication-freeze-manifest-v1",
            "status": "frozen",
            "created_on": "2026-10-08",
            "reviewer": SIGNER,
            "adjudicator": SIGNER,
            "signoff_evidence": SIGNOFF_EVIDENCE,
            "human_gate_satisfied": True,
            "quality_gate_passed": False,
            "publication_authorized": False,
            "inputs": {relative(path): sha256(path) for path in inputs},
            "outputs": {relative(path): sha256(path) for path in outputs},
            "model_calls": 0,
            "m_main_calls": 0,
            "production_database_access": 0,
        },
    )


def verify() -> None:
    checked_inputs()
    manifest = read_json(MANIFEST)
    if (
        manifest.get("status") != "frozen"
        or manifest.get("human_gate_satisfied") is not True
        or manifest.get("quality_gate_passed") is not False
        or manifest.get("publication_authorized") is not False
    ):
        raise SystemExit("invalid signed adjudication manifest state")
    for group in ("inputs", "outputs"):
        for name, expected in manifest[group].items():
            if sha256(REPO / name) != expected:
                raise SystemExit(f"hash mismatch: {name}")
    signed = read_json(SIGNED)
    rows = signed["adjudications"]
    if (
        signed.get("candidate_count") != 267
        or signed.get("unresolved_count") != 0
        or len(rows) != 267
        or any(
            row.get("reviewer") != SIGNER
            or row.get("adjudicator") != SIGNER
            or row.get("review_status") != "accepted"
            for row in rows
        )
    ):
        raise SystemExit("signed adjudication roster is incomplete")
    print(
        json.dumps(
            {
                "status": "verified",
                "candidate_count": len(rows),
                "human_gate_satisfied": True,
                "quality_gate_passed": False,
            },
            ensure_ascii=False,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    verify() if args.verify else build()


if __name__ == "__main__":
    main()
