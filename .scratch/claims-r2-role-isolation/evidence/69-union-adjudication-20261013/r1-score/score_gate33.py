#!/usr/bin/env python3
"""Honest gate-33 scoring from the confirmed union adjudication (zero model calls).

Inputs: A (222 pool adjudications, authoritative), plus the signed r5 (15) and base
(16) batches — 253 mappings total. A's 5 out_of_scope candidates are excluded from
scoring per adjudication_clause.scope_rules (recorded, not silently dropped).
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(REPO_ROOT))

from plugins.corpus.adjudication_assembly import AdjudicatedMapping  # noqa: E402
from plugins.corpus.structured_scoring import (  # noqa: E402
    CandidateRecord,
    GoldRecord,
    MatchingMode,
    RecordOrigin,
    Role,
    score_structured_quality,
)

HERE = Path(__file__).resolve().parent
UNION = HERE.parent
E = REPO_ROOT / ".scratch/claims-r2-role-isolation/evidence"


def sha(p: Path) -> str:
    return "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest()


def sf_pairs(fields: dict[str, Any] | None) -> tuple[tuple[str, str], ...]:
    pairs = tuple(
        sorted((str(k), str(v)) for k, v in (fields or {}).items() if v not in (None, ""))
    )
    return pairs or (("proposition", "<empty>"),)


def main() -> int:
    A = json.loads(
        (REPO_ROOT / ".scratch/claims-r2-role-isolation/adjudication/worksheet.json").read_text(
            encoding="utf-8"
        )
    )
    signed_signed = json.loads(
        (
            E / "65-rerun-two-arm-protocol-20261013/r6-assembly/assembled-scoring-input.json"
        ).read_text(encoding="utf-8")
    )
    signed_base = json.loads(
        (
            E / "66-base-protocol-change-proposal-20261013/r4-assembly/assembled-scoring-input.json"
        ).read_text(encoding="utf-8")
    )
    gate33 = json.loads(
        (E / "33-items-quality-scoring-20261011/r0-zero-call/adjudications.json").read_text(
            encoding="utf-8"
        )
    )

    gold = []
    for g in gate33["gold_reference"]:
        gold.append(
            GoldRecord(
                record_id=g["record_id"],
                role=Role.MATERIAL_ITEMS,
                source_id=g["source_id"],
                origin=RecordOrigin.LLM_PROSE,
                semantic_fields=sf_pairs(
                    {"proposition": g.get("quote") or "", **(g.get("semantic_fields") or {})}
                ),
                critical=bool(g.get("critical")),
                risk_or_condition=bool(g.get("risk_or_condition")),
            )
        )

    candidates: list[CandidateRecord] = []
    mappings: list[AdjudicatedMapping] = []
    excluded_oos: list[str] = []

    def norm_source(sid: str) -> str:
        # gold uses the prefixed form; snapshots record the bare digest
        return sid if sid.startswith("sha256:") else f"sha256:{sid}"

    def add_from_record(rec: dict[str, Any]) -> None:
        cid = rec["candidate_id"]
        judgement = rec["judgement"]
        if judgement == "out_of_scope":
            excluded_oos.append(cid)
            return
        oc = rec.get("original_candidate") or {}
        candidates.append(
            CandidateRecord(
                candidate_id=cid,
                role=Role.MATERIAL_ITEMS,
                source_id=norm_source(rec["source_id"]),
                origin=RecordOrigin(str(oc.get("origin") or "llm_prose")),
                semantic_fields=sf_pairs(
                    {
                        "proposition": (oc.get("text") or rec.get("proposition") or ""),
                        "semantic_type": rec.get("semantic_type")
                        or (oc.get("semantic_type") or ""),
                        "statement_role": rec.get("statement_role") or "",
                        "polarity": (oc.get("polarity") or ""),
                    }
                ),
            )
        )
        mappings.append(
            AdjudicatedMapping(
                candidate_id=cid,
                gold_record_id=rec.get("matched_gold_id"),
                judgement=judgement,
                stage="raw",
            )
        )

    for rec in A["records"]:
        add_from_record(rec)
    n_pool = len(candidates)
    for payload in (signed_signed, signed_base):
        by_id = {c["candidate_id"]: c for c in payload.get("raw", [])}
        for m in payload.get("mappings", []):
            if m["judgement"] == "out_of_scope":
                excluded_oos.append(m["candidate_id"])
                continue
            c = by_id[m["candidate_id"]]
            candidates.append(
                CandidateRecord(
                    candidate_id=c["candidate_id"],
                    role=Role.MATERIAL_ITEMS,
                    source_id=norm_source(c["source_id"]),
                    origin=RecordOrigin(str(c.get("origin") or "llm_prose")),
                    semantic_fields=sf_pairs(
                        {
                            "proposition": (c.get("text") or ""),
                            "semantic_type": c.get("semantic_type") or "",
                            "statement_role": c.get("statement_role") or "",
                            "polarity": c.get("polarity") or "",
                        }
                    ),
                )
            )
            mappings.append(
                AdjudicatedMapping(
                    candidate_id=m["candidate_id"],
                    gold_record_id=m.get("gold_record_id"),
                    judgement=m["judgement"],
                    stage=m.get("stage") or "raw",
                )
            )
    n_signed = len(candidates) - n_pool

    report = score_structured_quality(
        gold=tuple(gold),
        raw_candidates=tuple(candidates),
        validated_candidates=(),
        matching_mode=MatchingMode.ADJUDICATED,
        raw_mappings=tuple(mappings),
        validated_mappings=(),
    )
    raw_score = report.raw
    items = next(r for r in raw_score.roles if r.role is Role.MATERIAL_ITEMS)
    matched = list(raw_score.matched_gold_ids)
    missing = list(raw_score.missing_gold_ids)
    recall = items.recall
    precision = items.precision

    out = {
        "schema_version": "gate33-honest-score-1",
        "created_on": "2026-10-13",
        "zero_model_calls": True,
        "authority": "69-union-adjudication（A 权威；r5/base 已签批并入）",
        "inputs": {
            "gold_scope": 48,
            "pool_adjudications": n_pool,
            "signed_rerun_batches": n_signed,
            "scored_candidates": len(candidates),
            "excluded_out_of_scope": excluded_oos,
        },
        "items_role": {
            "tp": items.tp,
            "fp": items.fp,
            "fn": items.fn,
            "duplicate_fp": items.duplicate_fp,
            "correct_extra": items.correct_extra,
            "precision": str(precision) if precision is not None else None,
            "recall": str(recall) if recall is not None else None,
        },
        "recall": str(recall) if recall is not None else None,
        "precision": str(precision) if precision is not None else None,
        "matched_gold_ids": matched,
        "missing_gold_ids": missing,
        "gate33_thresholds": {"recall_min": 0.85, "precision_min": 0.80},
        "gate33_verdict": {
            "recall_pass": bool(
                recall is not None and recall >= __import__("fractions").Fraction(85, 100)
            ),
            "verdict": (
                "PASS"
                if recall is not None and recall >= __import__("fractions").Fraction(85, 100)
                else "FAIL — 召回未达 0.85；缺口为真实 FN（金标无候选匹配），非流程问题"
            ),
        },
        "inputs_hashes": {
            "A_worksheet": sha(
                REPO_ROOT / ".scratch/claims-r2-role-isolation/adjudication/worksheet.json"
            ),
            "r6_assembled": sha(
                E / "65-rerun-two-arm-protocol-20261013/r6-assembly/assembled-scoring-input.json"
            ),
            "r4_assembled": sha(
                E / "66-base-protocol-change-proposal-20261013/r4-assembly/assembled-scoring-input.json"
            ),
        },
    }
    (HERE / "gate33-honest-score.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "scored": len(candidates),
                "excluded_oos": len(excluded_oos),
                "recall": out["recall"],
                "precision": out["precision"],
                "verdict": out["gate33_verdict"]["verdict"],
                "matched": len(matched),
                "missing": len(missing),
            },
            ensure_ascii=False,
            indent=1,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
