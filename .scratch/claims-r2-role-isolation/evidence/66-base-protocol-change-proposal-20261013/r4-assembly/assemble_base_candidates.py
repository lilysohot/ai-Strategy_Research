#!/usr/bin/env python3
"""Assemble the signed base-packet adjudications (16 candidates, reviewer xyl) into
scorer input. Zero model calls. Contract shape enforcement identical to the r6 batch:
duplicate/other judgements must not carry matched_gold_id (stripped, preserved in
reason); deterministic carriers declared from the candidate's own store records."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(REPO_ROOT))

from plugins.corpus.adjudication_assembly import assemble_scoring_input  # noqa: E402

HERE = Path(__file__).resolve().parent
P66 = HERE.parent
SHEET = P66 / "r3-cumulative" / "adjudication-worksheet-base.json"


def sha(p: Path) -> str:
    return "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest()


def load_catalog() -> tuple[dict[str, dict[str, Any]], str]:
    """candidate_id -> the candidate's own fields (flat), plus the snapshot source_id."""
    catalog: dict[str, dict[str, Any]] = {}
    source_id = ""
    for run_dir in (
        (
            REPO_ROOT
            / ".scratch/claims-r2-role-isolation/evidence/65-rerun-two-arm-protocol-20261013/r3-control-live/base-7critical"
        ),
        (
            REPO_ROOT
            / ".scratch/claims-r2-role-isolation/evidence/65-rerun-two-arm-protocol-20261013/r4-control-official/base-7critical"
        ),
        (P66 / "r2-publish/store-run4-final"),
    ):
        snap_path = run_dir / "snapshot.json"
        if snap_path.exists():  # executor runs don't persist snapshot.json
            snap = json.loads(snap_path.read_text(encoding="utf-8"))
            source_id = snap["source_id"]
        for f in (run_dir / "store").rglob("*.json"):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            content = d.get("content") if isinstance(d, dict) else None
            if not content:
                continue
            for line in content.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if rec.get("record_type") == "item":
                    catalog[rec["item_id"]] = {
                        "role": "material_items",
                        "source_id": snap["source_id"],
                        "origin": "llm_prose",
                        "text": rec.get("text"),
                        "semantic_type": rec.get("semantic_type"),
                        "statement_role": rec.get("statement_role"),
                        "speech_role": rec.get("speech_role"),
                        "perspective": rec.get("perspective"),
                        "polarity": rec.get("polarity"),
                        "speaker_ref": rec.get("speaker_ref"),
                    }
    return catalog, source_id


def main() -> int:
    sheet = json.loads(SHEET.read_text(encoding="utf-8"))
    catalog, source_id = load_catalog()
    stripped: list[str] = []
    adjudications = []
    reason_by_judgement = {
        "matched": "人工核对：候选与金标命题语义等价（1:1 映射）",
        "duplicate": "人工核对：目标金标已被既有候选 1:1 占用",
        "correct_extra": "人工核对：内容为真但金标无对应原子命题",
    }
    for row in sheet["candidates"]:
        cid = row.get("candidate_id")
        tf = row.get("to_fill") or {}
        c = catalog.get(cid)
        if c is None:
            raise SystemExit(f"candidate missing from store: {cid}")
        judgement = tf["judgement"]
        gold = tf.get("matched_gold_id") or None
        reason = reason_by_judgement.get(judgement, "人工核对")
        if judgement != "matched" and gold:
            stripped.append(f"{cid}: 关联金标 {gold}（非 matched，按契约剥离）")
            reason = f"{reason}；关联金标 {gold}"
            gold = None
        adj = {
            "candidate_id": cid,
            "stage": "raw",
            "role": "material_items",
            "source_id": c["source_id"],
            "original_candidate": c,
            "judgement": judgement,
            "matched_gold_id": gold,
            "reviewer": "xyl",
            "reason": reason,
            "evidence": (row.get("model_suggestion") or {}).get("evidence_quote")
            or tf.get("evidence")
            or "",
            "canonical_observed_fields": {
                "proposition": c["text"],
                "semantic_type": tf["semantic_type"],
                "statement_role": tf["statement_role"],
                "speech_role": c["speech_role"] or "statement",
                "perspective": c["perspective"] or "source_explicit",
                "polarity": c["polarity"],
                "speaker_ref": c["speaker_ref"] or "absent",
                "attribution": "absent",
                "source_stance": tf["source_stance"],
                "condition": tf["condition"],
            },
        }
        adjudications.append(adj)

    result = assemble_scoring_input(adjudications, catalog=catalog)
    import dataclasses

    payload = json.loads(json.dumps(dataclasses.asdict(result), ensure_ascii=False, default=str))
    payload["provenance"] = {
        "signed_sheet_sha256": sha(SHEET),
        "sheet_date_note": "工作表签名日期为 2026-10-30（疑为 2026-10-13 笔误），按原样存档",
        "stripped_annotations": stripped,
    }
    (HERE / "assembled-scoring-input.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "raw": len(payload.get("raw", [])),
                "mappings": len(payload.get("mappings", [])),
                "out_of_scope": len(payload.get("out_of_scope", [])),
                "stripped": stripped,
            },
            ensure_ascii=False,
            indent=1,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
