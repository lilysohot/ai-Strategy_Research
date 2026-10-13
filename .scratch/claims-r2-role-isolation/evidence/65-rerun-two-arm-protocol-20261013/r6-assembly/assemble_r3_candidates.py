#!/usr/bin/env python3
"""Assemble the signed r3 candidate adjudications (I06/I41) into scorer input.

Zero model calls. Adjudications come from the signed worksheet (reviewer xyl,
2026-10-13); the catalog is built ONLY from the candidates' own store records, so the
assembler's deterministic-carrier recomputation has real values to check against.
"""

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
D = HERE.parent
SHEET = D / "r5-adjudication-sheet" / "adjudication-worksheet.json"
R3 = D / "r3-control-live"


def sha(p: Path) -> str:
    return "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest()


def load_catalog() -> dict[str, dict[str, Any]]:
    catalog: dict[str, dict[str, Any]] = {}
    for pkt in ("NT-I06", "NT-I41"):
        snap = json.loads((R3 / pkt / "snapshot.json").read_text(encoding="utf-8"))
        for f in (R3 / pkt / "store").rglob("*.json"):
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
                if rec.get("record_type") != "item":
                    continue
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
    return catalog


def main() -> int:
    sheet = json.loads(SHEET.read_text(encoding="utf-8"))
    catalog = load_catalog()
    adjudications = []
    reason_by_judgement = {
        "matched": "人工核对：候选与金标命题语义等价（1:1 映射，金标未被占用）",
        "duplicate": "人工核对：目标金标已被既有候选 1:1 占用，按契约判 duplicate",
        "correct_extra": "人工核对：内容为真但 48 条金标无对应原子命题",
    }
    for row in sheet["candidates"]:
        cid = row["candidate_id"]
        c = catalog.get(cid)
        if c is None:
            raise SystemExit(f"candidate missing from store: {cid}")
        tf = row["to_fill"]
        judgement = tf["judgement"]
        adj = {
            "candidate_id": cid,
            "stage": "raw",
            "role": "material_items",
            "source_id": c["source_id"],
            "original_candidate": c,
            "judgement": judgement,
            # contract shape: only `matched` carries a matched_gold_id
            "matched_gold_id": (tf.get("matched_gold_id") or None)
            if judgement == "matched"
            else None,
            "reviewer": "xyl",
            "reason": reason_by_judgement.get(judgement, "人工核对"),
            "evidence": row["model_suggestion"].get("evidence_quote") or tf.get("evidence") or "",
            # deterministic carriers are declared from the candidate's OWN fields; the
            # assembler recomputes and rejects any mismatch.
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
    (HERE / "assembled-scoring-input.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "assembled": len(payload.get("assembled", [])),
                "rejected": len(payload.get("rejected", [])),
                "rejected_detail": payload.get("rejected", [])[:5],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
