"""Issue 36 · Stage-2 裁定助手修正版（零调用、只读、幂等）。

与 v1（`33-.../r0-zero-call/build_adjudication_draft.py`）的差别只有一处，但是关键的一处：

- v1 把**金标的** `semantic_fields` 写进候选的 `canonical_observed_fields`，并把 `judgement`
  预置为 `accepted`。这恰好是契约 `matching.normalization` 明文禁止的「不从金标反填候选缺字段」，
  也等于 `matching.projection` 禁止的「把目标字符串直接赋给候选并宣称自动语义评分」。v1 的
  `19/48` 因此测的是这次拷贝，不是抽取。
- v2 只做三件事：① `canonical_observed_fields` 一律取**候选自身**字段；② 所有候选保持
  `judgement = pending`，建议只留在 `suggested_gold_ids`（词法建议，非裁定）；③ 机读暴露
  「契约必需字段 vs 候选字段」的缺口，并算出「在契约合法操作下能自动成立多少匹配」。

v1 的产物字节不动；v2 写入独立目录。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
CLAIMS = HERE.parents[2]
EV = CLAIMS / "evidence"
E33 = EV / "33-items-quality-scoring-20261011" / "r0-zero-call"

SKELETON = E33 / "adjudications.json"
GOLD = EV / "10-quality-gold-freeze-20261008-r2" / "frozen-gold.json"
FREEZE_STATE = EV / "10-quality-gold-freeze-20261008-r2" / "freeze-state.json"
CONTRACT = EV / "10-quality-gold-expansion-20261008-r2" / "scoring-contract.json"

CANDIDATE_FIELD_KEYS = (
    "text",
    "semantic_type",
    "statement_role",
    "speech_role",
    "perspective",
    "polarity",
    "value",
    "behavior_status",
    "temporal_frame",
    "speaker_ref",
)
SCHEMA_VERSION = "items-quality-adjudications-v2"
REPORT_VERSION = "items-contract-gap-1"
CREATED_ON = "2026-10-12"

Projection = Callable[[dict[str, str]], dict[str, str]]


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def candidate_fields(original: dict[str, Any]) -> dict[str, str]:
    """Non-empty string fields the candidate itself carries."""
    return {
        key: original[key]
        for key in CANDIDATE_FIELD_KEYS
        if isinstance(original.get(key), str) and original[key]
    }


def gold_fields(record: dict[str, Any]) -> dict[str, str]:
    return {
        key: value
        for key, value in (record.get("semantic_fields") or {}).items()
        if isinstance(value, str) and value
    }


def pairs(fields: dict[str, str]) -> tuple[tuple[str, str], ...]:
    return tuple(sorted(fields.items()))


def greedy_one_to_one(
    candidates: list[dict[str, Any]],
    gold_items: list[dict[str, Any]],
    project: Projection,
) -> list[tuple[str, str]]:
    """Greedy exact-identity one-to-one matching under one field projection."""
    gold_index = {
        (row["source_id"], pairs(project(gold_fields(row)))): row["record_id"] for row in gold_items
    }
    used_gold: set[str] = set()
    matched: list[tuple[str, str]] = []
    for entry in candidates:
        original = entry["original_candidate"]
        projection = pairs(project(candidate_fields(original)))
        gold_id = gold_index.get((original["source_id"], projection))
        if gold_id is None or gold_id in used_gold:
            continue
        used_gold.add(gold_id)
        matched.append((entry["candidate_id"], gold_id))
    return matched


def restrict_to(keys: list[str]) -> Projection:
    def project(fields: dict[str, str]) -> dict[str, str]:
        return {key: value for key, value in fields.items() if key in set(keys)}

    return project


def identity(fields: dict[str, str]) -> dict[str, str]:
    return fields


def main() -> None:
    skeleton = read_json(SKELETON)
    gold = read_json(GOLD)
    freeze_state = read_json(FREEZE_STATE)
    contract = read_json(CONTRACT)

    gold_items = [row for row in gold["records"] if row["role"] == "material_items"]
    snapshot = freeze_state["contract_snapshot"]
    contract_required = list(snapshot["role_required_fields"]["material_items"])
    required = set(contract_required)

    candidates: list[dict[str, Any]] = []
    for entry in skeleton["candidates"]:
        fields = candidate_fields(entry["original_candidate"])
        candidates.append(
            {
                **entry,
                "judgement": "pending",
                "matched_gold_id": None,
                "canonical_observed_fields": fields,
                "contract_required_fields_missing": sorted(required - set(fields)),
                "hint": (
                    "suggested_gold_ids are lexical (number overlap + character bigrams); they "
                    "are not a judgement and must not be copied into matched_gold_id"
                ),
                "reviewer": "",
                "reason": "",
                "evidence": "",
            }
        )

    candidate_union = sorted(
        {key for row in candidates for key in row["canonical_observed_fields"]}
    )
    gold_union = sorted({key for row in gold_items for key in gold_fields(row)})

    legal_matches = greedy_one_to_one(candidates, gold_items, identity)

    shared = [key for key in contract_required if key in set(candidate_union)]
    sizing_matches = greedy_one_to_one(candidates, gold_items, restrict_to(shared))

    draft = {
        "schema_version": SCHEMA_VERSION,
        "status": "reviewer_worksheet_pending_human_adjudication",
        "gate": "33-items-quality-scoring-gate",
        "contract": contract["schema_version"],
        "created_on": CREATED_ON,
        "supersedes": "adjudications.draft.json (issue 33 r0-zero-call)",
        "v1_violation_removed": (
            "canonical_observed_fields is no longer copied from the gold record, and no "
            "judgement is pre-set to accepted"
        ),
        "reviewer": "",
        "signed_on": "",
        "counts": {
            "candidates_total": len(candidates),
            "preset_accepted": 0,
            "pending": len(candidates),
        },
        "candidates": candidates,
        "gold_reference": skeleton["gold_reference"],
    }
    (HERE / "adjudications.v2.json").write_text(
        json.dumps(draft, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    report = {
        "schema_version": REPORT_VERSION,
        "created_on": CREATED_ON,
        "question": "can any candidate be matched without an operation the contract forbids?",
        "inputs": {
            "skeleton": digest(SKELETON),
            "frozen_gold": digest(GOLD),
            "freeze_state": digest(FREEZE_STATE),
            "scoring_contract": digest(CONTRACT),
        },
        "contract_required_fields_material_items": contract_required,
        "candidate_semantic_fields": candidate_union,
        "fields_missing_in_candidate": sorted(required - set(candidate_union)),
        "gold_fields_not_required_by_contract": sorted(set(gold_union) - required),
        "contract_legal_matching": {
            "definition": "exact identity over the candidate's own fields, both sides key-sorted",
            "matches": len(legal_matches),
            "gold_total": len(gold_items),
        },
        "forbidden_operation": {
            "normalization_clause": snapshot["matching"]["normalization"],
            "projection_clause": contract["matching"]["projection"],
            "v1_did": (
                "filled each auto-accepted candidate's canonical_observed_fields with the gold "
                "record's semantic_fields, which is back-filling absent candidate fields from the "
                "gold and is what produced the 19/48 figure"
            ),
            "v2_does": "records the candidate's own fields only; no match is asserted",
        },
        "sizing_counterfactual": {
            "status": "not_contract_legal_not_a_score_threshold_free",
            "shared_fields_used": shared,
            "matches": len(sizing_matches),
            "gold_total": len(gold_items),
            "purpose": "size how many records a future read-path rule could recover",
        },
        "blocking_decision_required": (
            "Stage 2 cannot complete under the current contract: the candidate carries no "
            "proposition/attribution/source_stance (nor a condition carrier for condition-role "
            "records), and rewriting those fields by hand is exactly what matching.projection "
            "forbids. A read-path rule, or an extended extraction protocol, must be signed first."
        ),
        "model_requests": 0,
        "production_database_access": 0,
    }
    (HERE / "contract-gap-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "candidates": len(candidates),
                "preset_accepted": 0,
                "contract_legal_matches": len(legal_matches),
                "sizing_counterfactual_matches": len(sizing_matches),
                "fields_missing_in_candidate": report["fields_missing_in_candidate"],
                "shared_fields_used": shared,
                "model_requests": 0,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
