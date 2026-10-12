"""Generate the Stage-2 adjudication worksheet (222 records) + gold reference + validator.

Zero model calls; read-only on inputs. The worksheet is written to the **working directory**
``.scratch/claims-r2-role-isolation/adjudication/`` (not an evidence directory) because it is
meant to be edited by the human adjudicator; once complete it is archived into evidence.

Per record the deterministic carriers are pre-filled from the candidate's own fields (the
assembler recomputes and rejects any mismatch), the human-only slots are left for the
adjudicator, and — per contract ``adjudication_clause.tooling.suggestion_policy`` — Stage-1
suggestions are **omitted entirely** so independent adjudication is not primed.

Usage:
    uv run python .scratch/.../61-adjudication-worksheet-20261012/r0-zero-call/generate_worksheet.py
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
E61 = HERE.parent
CLAIMS = E61.parent.parent
REPO_ROOT = HERE.parents[4]
sys.path.insert(0, str(REPO_ROOT))

WORK = CLAIMS / "adjudication"
WORKBENCH = (
    CLAIMS
    / "evidence"
    / "38-gate33-workbench-rebuild-20261012"
    / "r0-zero-call"
    / "workbench-v2.json"
)
FROZEN_GOLD = CLAIMS / "evidence" / "10-quality-gold-freeze-20261008-r2" / "frozen-gold.json"

ABSENT = "absent"
HUMAN_ONLY = ("semantic_type", "statement_role", "source_stance", "condition")
DETERMINISTIC = ("proposition", "speech_role", "perspective", "polarity")
EXCLUDED = ("speaker_ref", "attribution")


def sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_field(name: str, candidate: dict[str, Any]) -> str:
    """Pre-fill one canonical field from the candidate's own carrier (rename only)."""
    key = {
        "proposition": "text",
        "semantic_type": "semantic_type",
        "statement_role": "statement_role",
        "speech_role": "speech_role",
        "perspective": "perspective",
        "polarity": "polarity",
        "speaker_ref": "speaker_ref",
        "attribution": "attribution",
        "condition": "condition",
    }.get(name)
    value = candidate.get(key) if key else None
    return str(value) if value not in (None, "") else ABSENT


def main() -> None:
    workbench = json.loads(WORKBENCH.read_text(encoding="utf-8"))
    gold_all = json.loads(FROZEN_GOLD.read_text(encoding="utf-8"))
    gold_items = [row for row in gold_all["records"] if row["role"] == "material_items"]

    worksheet: list[dict[str, Any]] = []
    for candidate in workbench["candidates"]:
        fields = {
            name: canonical_field(name, candidate)
            for name in (
                "proposition",
                "semantic_type",
                "statement_role",
                "speech_role",
                "perspective",
                "speaker_ref",
                "polarity",
                "attribution",
                "source_stance",
                "condition",
            )
        }
        fields["source_stance"] = ABSENT  # 无载体 ⇒ 必须读原文判定（caliber_rules）
        worksheet.append(
            {
                "candidate_id": candidate["candidate_id"],
                "stage": "raw",
                "role": candidate["role"],
                "source_id": candidate["source_id"],
                "original_candidate": {
                    key: candidate[key]
                    for key in (
                        "candidate_id",
                        "role",
                        "source_id",
                        "origin",
                        "source_slug",
                        "candidate_slot_id",
                        "text",
                        "semantic_type",
                        "statement_role",
                        "speech_role",
                        "perspective",
                        "polarity",
                        "value",
                        "behavior_status",
                        "temporal_frame",
                        "unknown_fields",
                        "evidence_quote",
                        "evidence_locator",
                        "speaker_ref",
                        "attribution",
                        "condition",
                        "factuality",
                    )
                    if key in candidate
                },
                "judgement": None,
                "matched_gold_id": None,
                "canonical_observed_fields": fields,
                "reviewer": "xyl",
                "reason": "",
                "evidence": {
                    "quote": candidate.get("evidence_quote") or "",
                    "locator": candidate.get("evidence_locator") or "",
                },
            }
        )

    gold_reference = [
        {
            "record_id": row["record_id"],
            "proposition": (row["semantic_fields"] or {}).get("proposition", ""),
            "semantic_type": (row["semantic_fields"] or {}).get("semantic_type", ""),
            "statement_role": (row["semantic_fields"] or {}).get("statement_role", ""),
            "polarity": (row["semantic_fields"] or {}).get("polarity", ""),
            "source_stance": (row["semantic_fields"] or {}).get("source_stance", ""),
            "condition": (row["semantic_fields"] or {}).get("condition", ""),
            "critical": row.get("critical", False),
            "risk_or_condition": row.get("risk_or_condition", False),
        }
        for row in gold_items
    ]

    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / "worksheet.json").write_text(
        json.dumps(
            {
                "schema_version": "items-adjudication-worksheet-1",
                "created_on": "2026-10-12",
                "instructions": "见同目录 README.md；填完跑 python validate.py 自检",
                "candidates_total": len(worksheet),
                "records": worksheet,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (WORK / "gold-reference.json").write_text(
        json.dumps(
            {
                "schema_version": "items-gold-reference-1",
                "note": "裁定人匹配用的 48 条金标参照（人类裁定者可见金标；禁止的是把金标抄进候选）",
                "total": len(gold_reference),
                "records": gold_reference,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "worksheet": str((WORK / "worksheet.json").relative_to(REPO_ROOT)),
                "records": len(worksheet),
                "gold_reference": str((WORK / "gold-reference.json").relative_to(REPO_ROOT)),
                "gold_records": len(gold_reference),
                "inputs": {
                    str(WORKBENCH.relative_to(REPO_ROOT)): sha256(WORKBENCH),
                    str(FROZEN_GOLD.relative_to(REPO_ROOT)): sha256(FROZEN_GOLD),
                },
                "suggestions_included": False,
            },
            ensure_ascii=False,
            indent=1,
        )
    )


if __name__ == "__main__":
    main()
