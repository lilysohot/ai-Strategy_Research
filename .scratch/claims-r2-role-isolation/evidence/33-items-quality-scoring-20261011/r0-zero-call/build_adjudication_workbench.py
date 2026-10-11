"""Stage 1 of the issue-33 quality gate: build the human adjudication workbench.

Zero call, read-only. Exports the 222 treatment candidates with their full semantic fields,
the 48 signed gold items, an automatic alignment *suggestion* (advisory only — contract v3
forbids automated semantic scoring), and the empty 11-field adjudication skeleton the
reviewer fills in during Stage 2.

Writes workbench.json, workbench.md and adjudications.json.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
E33 = HERE.parent
CLAIMS = E33.parent.parent
E32 = CLAIMS / "evidence" / "32-items-v6-reasoning-refreeze-20261011"
E10 = CLAIMS / "evidence"
GOLD = E10 / "10-quality-gold-freeze-20261008-r2" / "frozen-gold.json"
CONTRACT = E10 / "10-quality-gold-expansion-20261008-r2" / "scoring-contract.json"
RESIDUAL = E32 / "live" / "residual-attribution.json"
SOURCES = ("industrial-fulian-md", "optical-module-docx")

from plugins.corpus.structured.ledger import BatchPlan, check_batch  # noqa: E402

NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
FILLER_RE = re.compile(r"[\s，。、；：（）()“”\"'’‘%％,.;:!?！？\-—–~～\[\]【】]+")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def normalize(text: str) -> str:
    return FILLER_RE.sub("", text or "")


def bigrams(text: str) -> set[str]:
    normalized = normalize(text)
    return {normalized[index : index + 2] for index in range(len(normalized) - 1)}


def numbers(text: str) -> set[str]:
    return set(NUMBER_RE.findall(text or ""))


def similarity(candidate: dict[str, Any], gold: dict[str, Any]) -> dict[str, Any]:
    candidate_text = candidate.get("text") or ""
    gold_text = " ".join(
        str(value)
        for key, value in (gold.get("semantic_fields") or {}).items()
        if key in {"proposition", "condition", "metric", "value", "period"}
    )
    candidate_bigrams = bigrams(candidate_text)
    gold_bigrams = bigrams(gold_text)
    overlap = candidate_bigrams & gold_bigrams
    containment = len(overlap) / len(gold_bigrams) if gold_bigrams else 0.0
    candidate_numbers = numbers(candidate_text) | numbers(json.dumps(candidate.get("value")))
    gold_numbers = numbers(gold_text) | numbers(gold.get("quote"))
    shared_numbers = candidate_numbers & gold_numbers
    score = round(0.65 * containment + 0.35 * min(len(shared_numbers) / 3, 1.0), 4)
    if len(shared_numbers) >= 2 and containment >= 0.5:
        confidence = "high"
    elif containment >= 0.45 or (len(shared_numbers) >= 1 and containment >= 0.25):
        confidence = "medium"
    else:
        confidence = "low"
    return {
        "gold_record_id": gold["record_id"],
        "score": score,
        "confidence": confidence,
        "shared_numbers": sorted(shared_numbers),
        "text_containment": round(containment, 4),
    }


def load_candidates(slug: str) -> tuple[str, list[dict[str, Any]]]:
    store = E32 / "live" / "treatment-store" / slug
    plan = BatchPlan.model_validate_json(
        (E32 / "r0-zero-call" / f"plan-treatment-{slug}.json").read_text(encoding="utf-8")
    )
    plan.verify_identity()
    batch = check_batch(plan.batch_id, store_root=str(store.resolve()))
    task = next(item for item in batch.ledger.tasks if item.role == "material_items")
    connection = sqlite3.connect(
        f"file:{store / 'index' / 'structured.sqlite3'}?mode=ro", uri=True
    )
    try:
        sha = connection.execute(
            "SELECT payload_object_sha256 FROM tasks WHERE task_id=?", (task.task_id,)
        ).fetchone()[0]
    finally:
        connection.close()
    hexd = str(sha).removeprefix("sha256:")
    payload = json.loads(
        (store / "objects" / "sha256" / hexd[:2] / f"{hexd}.json").read_text(encoding="utf-8")
    )
    raw_source_id = plan.snapshot.source_id
    # Gold records carry the prefixed form; the snapshot stores the bare digest.
    source_id = raw_source_id if raw_source_id.startswith("sha256:") else f"sha256:{raw_source_id}"
    items = payload["understanding"]["items"]
    slot_ledger = payload["understanding"]["coverage"]["slot_ledger"]
    slot_of_item: dict[str, str] = {}
    for entry in slot_ledger:
        for ref in entry.get("item_refs") or []:
            slot_of_item[ref] = entry.get("candidate_slot_id")
    candidates = [
        {
            "candidate_id": item["item_id"],
            "role": "material_items",
            "source_id": source_id,
            "origin": "llm_prose",
            "source_slug": slug,
            "candidate_slot_id": slot_of_item.get(item["item_id"]),
            "text": item.get("text"),
            "semantic_type": item.get("semantic_type"),
            "statement_role": item.get("statement_role"),
            "speech_role": item.get("speech_role"),
            "perspective": item.get("perspective"),
            "polarity": item.get("polarity"),
            "value": item.get("value"),
            "behavior_status": item.get("behavior_status"),
            "temporal_frame": item.get("temporal_frame"),
            "unknown_fields": item.get("unknown_fields"),
            "evidence_quote": (item.get("evidence") or [{}])[0].get("quote"),
            "evidence_locator": (item.get("evidence") or [{}])[0].get("locator"),
        }
        for item in items
    ]
    return source_id, candidates


def main() -> None:
    gold_payload = read_json(GOLD)
    contract = read_json(CONTRACT)
    residual = read_json(RESIDUAL)
    assert gold_payload["formal_gold_frozen"] and gold_payload["reviewer"] == "xyl"
    assert contract["schema_version"].startswith("non-table-selected-target-scoring-contract-v3")
    assert contract["evaluation_scope"] == gold_payload["evaluation_scope"]

    gold_items = [row for row in gold_payload["records"] if row["role"] == "material_items"]
    gold_by_source: dict[str, list[dict[str, Any]]] = {}
    for row in gold_items:
        gold_by_source.setdefault(row["source_id"], []).append(row)

    candidates: list[dict[str, Any]] = []
    suggestions: list[dict[str, Any]] = []
    for slug in SOURCES:
        source_id, source_candidates = load_candidates(slug)
        peers = gold_by_source.get(source_id, [])
        for candidate in source_candidates:
            scored = sorted(
                (similarity(candidate, gold) for gold in peers),
                key=lambda item: item["score"],
                reverse=True,
            )
            top = [item for item in scored[:3] if item["score"] > 0]
            candidates.append(candidate)
            suggestions.append(
                {
                    "candidate_id": candidate["candidate_id"],
                    "source_slug": slug,
                    "source_id": source_id,
                    "text": candidate["text"],
                    "top_suggestions": top,
                    "advisory_only": True,
                }
            )

    skeleton = {
        "schema_version": "items-quality-adjudications-1",
        "status": "pending_human_adjudication",
        "gate": "33-items-quality-scoring-gate",
        "contract": "non-table-selected-target-scoring-contract-v3",
        "reviewer": "",
        "signed_on": "",
        "instructions": (
            "Stage 2: for every candidate fill judgement (accepted|edited|rejected|pending) and "
            "matched_gold_id; when judgement=accepted the candidate's semantic fields are "
            "canonicalised to the matched gold record's fields and the original stays in "
            "original_candidate; predictions from Stage 1 are advisory only and must not be "
            "copied into matched_gold_id without checking."
        ),
        "candidates": [
            {
                "candidate_id": item["candidate_id"],
                "stage": "raw",
                "role": "material_items",
                "source_id": item["source_id"],
                "original_candidate": item,
                "judgement": "pending",
                "matched_gold_id": None,
                "suggested_gold_ids": [
                    entry["gold_record_id"]
                    for entry in next(
                        s for s in suggestions if s["candidate_id"] == item["candidate_id"]
                    )["top_suggestions"]
                ],
                "canonical_observed_fields": {},
                "reviewer": "",
                "reason": "",
                "evidence": "",
            }
            for item in candidates
        ],
        "gold_reference": [
            {
                "record_id": row["record_id"],
                "source_id": row["source_id"],
                "proposition": (row.get("semantic_fields") or {}).get("proposition"),
                "semantic_type": (row.get("semantic_fields") or {}).get("semantic_type"),
                "statement_role": (row.get("semantic_fields") or {}).get("statement_role"),
                "critical": row.get("critical"),
                "risk_or_condition": row.get("risk_or_condition"),
                "quote": row.get("quote"),
            }
            for row in gold_items
        ],
    }

    counts = {"high": 0, "medium": 0, "low": 0, "none": 0}
    for entry in suggestions:
        top = entry["top_suggestions"]
        counts[top[0]["confidence"] if top else "none"] += 1
    summary = {
        "schema_version": "items-quality-workbench-1",
        "created_on": "2026-10-11",
        "gate": "33-items-quality-scoring-gate",
        "candidates_total": len(candidates),
        "candidates_by_source": {
            slug: sum(1 for item in candidates if item["source_slug"] == slug)
            for slug in SOURCES
        },
        "gold_total": len(gold_items),
        "gold_by_source": {source: len(rows) for source, rows in gold_by_source.items()},
        "suggestion_confidence": counts,
        "unproduced_slots": residual["totals"],
        "unproduced_collateral_items": residual["conclusion"]["collateral_item_loss"],
        "inputs": {
            "frozen_gold": digest(GOLD),
            "scoring_contract": digest(CONTRACT),
            "residual_attribution": digest(RESIDUAL),
        },
        "candidates": candidates,
        "suggestions": suggestions,
        "advisory_note": (
            "Stage-1 suggestions are computed from number overlap and character bigrams only; "
            "contract v3 requires human adjudication before any scoring input is produced"
        ),
        "model_requests": 0,
        "production_database_access": 0,
    }
    (HERE / "workbench.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (HERE / "adjudications.json").write_text(
        json.dumps(skeleton, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    lines: list[str] = [
        "# 门 33 · Stage 1 裁定工作台",
        "",
        f"- 候选：{len(candidates)} 条（md {summary['candidates_by_source']['industrial-fulian-md']} / "
        f"docx {summary['candidates_by_source']['optical-module-docx']}）",
        f"- 金标：{len(gold_items)} 条（material_items）",
        f"- 建议置信分布：{counts}",
        f"- 未产出槽位：{residual['totals']}（连带丢失条目 {summary['unproduced_collateral_items']}）",
        "",
        "> Stage 1 的匹配建议只是辅助（数值交集 + 字符 2-gram），**不能直接作为评分输入**；",
        "> 契约 v3 要求逐条人工裁定后才能评分。",
        "",
        "## 按金标查看（每个金标下列出建议候选 top3）",
        "",
    ]
    for row in gold_items:
        lines.append(
            f"### {row['record_id']} · {'critical' if row.get('critical') else 'normal'}"
            f"{' / risk_or_condition' if row.get('risk_or_condition') else ''}"
        )
        lines.append(f"- 主张：{(row.get('semantic_fields') or {}).get('proposition')}")
        lines.append(
            f"- 类型/角色：{(row.get('semantic_fields') or {}).get('semantic_type')}"
            f" / {(row.get('semantic_fields') or {}).get('statement_role')}"
        )
        lines.append(f"- 原文：{row.get('quote')}")
        peers = [
            entry
            for entry in suggestions
            if entry["source_id"] == row["source_id"]
            and any(item["gold_record_id"] == row["record_id"] for item in entry["top_suggestions"])
        ]
        ranked = sorted(
            peers,
            key=lambda entry: next(
                item["score"]
                for item in entry["top_suggestions"]
                if item["gold_record_id"] == row["record_id"]
            ),
            reverse=True,
        )
        if ranked:
            for entry in ranked[:3]:
                item = next(
                    value
                    for value in entry["top_suggestions"]
                    if value["gold_record_id"] == row["record_id"]
                )
                lines.append(
                    f"  - [{item['confidence']} {item['score']}] {entry['candidate_id']}："
                    f"{entry['text']}"
                )
        else:
            lines.append("  - （无建议候选）")
        lines.append("")
    (HERE / "workbench.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "candidates": summary["candidates_total"],
                "candidates_by_source": summary["candidates_by_source"],
                "gold_total": summary["gold_total"],
                "suggestion_confidence": counts,
                "unproduced_slots": residual["totals"],
                "files": ["workbench.json", "workbench.md", "adjudications.json"],
                "model_requests": 0,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
