#!/usr/bin/env python3
"""Draft prefill for the 203 unresolved workbench candidates (zero model calls).

Drafting rules (all traceable to contract v4.1), applied in order:

1. 1:1 mapping — a gold claimed by any signed sheet (or proposed for a specific pool
   candidate by the signed r5 sheet) cannot be proposed for a second candidate;
   an overlapping candidate is proposed ``duplicate``.
2. Mechanical semantic correspondence (difflib ratio >= 0.75 on normalized text against
   the gold quote/proposition) with an UNCLAIMED gold → propose ``matched``.
3. No correspondence + candidate's own evidence_quote present → propose
   ``correct_extra`` (content truthfulness flagged for human review).
4. No correspondence + evidence_quote missing → leave judgement EMPTY for the human
   (the agent does not guess).

Every row is ``drafted_by=agent`` / ``status=pending_human_verification``: a proposal,
never an adjudication.
"""

from __future__ import annotations

import difflib
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[5]
W = json.loads(
    (
        REPO
        / ".scratch/claims-r2-role-isolation/evidence/38-gate33-workbench-rebuild-20261012/r0-zero-call/workbench-v2.json"
    ).read_text(encoding="utf-8")
)
GOLD = json.loads(
    (
        REPO
        / ".scratch/claims-r2-role-isolation/evidence/10-quality-gold-expansion-20261008-r2/gold-review-candidates.json"
    ).read_text(encoding="utf-8")
)
OUT = Path(__file__).resolve().parent


def norm(s: str) -> str:
    return re.sub(r"[\s，。；：、「」（）()【】\[\]…—－\-+%/]", "", str(s or "")).lower()


gold_records = GOLD.get("records") or GOLD.get("gold") or GOLD
if isinstance(gold_records, dict):
    gold_records = list(gold_records.values())
# Scope: gate-33's authoritative 48-gold reference (adjudications.json gold_reference).
# The expansion file holds 92 records — 44 are outside the scoring scope and must not
# receive matched proposals (the scorer rejects gold outside the frozen reference).
_signed = json.loads(
    (REPO / ".scratch/claims-r2-role-isolation/evidence/33-items-quality-scoring-20261011/r0-zero-call/adjudications.json").read_text(encoding="utf-8")
)
_scope = {g["record_id"] for g in _signed["gold_reference"]}
gold_records = [g for g in gold_records if g["record_id"] in _scope]
gold_by_id = {g["record_id"]: g for g in gold_records}

# ---- occupation baseline -----------------------------------------------------
claimed: dict[str, str] = {}  # gold_id -> candidate_id
# (a) signed r5 sheet: I06 matched; I05/I07/I08/I41 anticipated pool matches
claimed["NT-I06"] = "slot_60052220425de312#1"
for gid, cid in (
    ("NT-I05", "itm_abebb2a7163927e9"),
    ("NT-I07", "itm_d0e9f3a0a75f5157"),
    ("NT-I08", "itm_9960b6f5d20e37ed"),
    ("NT-I41", "itm_c71e15d5cebf1e85"),
):
    claimed[gid] = cid
# (b) signed base sheet: 7 matched golds
for gid in ("NT-I13", "NT-I14", "NT-I15", "NT-I16", "NT-I17", "NT-I42", "NT-I43"):
    claimed[gid] = "base-sheet-signed"
r5_anticipated = {cid: gid for gid, cid in claimed.items() if cid.startswith("itm_")}

already = {"slot_60052220425de312#1"}  # I06/I41/base candidates already adjudicated


def gold_text(g: dict) -> str:
    sf = g.get("semantic_fields") or {}
    return (
        norm(str(g.get("quote") or ""))
        + "|"
        + norm(str(sf.get("proposition") or sf.get("text") or ""))
    )


def best_match(cand: dict) -> tuple[str | None, float]:
    ct = norm(cand.get("text") or "")
    ev = norm(cand.get("evidence_quote") or "")
    best, score = None, 0.0
    for g in gold_records:
        gt = gold_text(g)
        for target in (ct, ev):
            if not target:
                continue
            r = difflib.SequenceMatcher(None, target, gt).ratio()
            contained = (
                norm(str(g.get("quote") or "")) and norm(str(g.get("quote") or "")) in target
            )
            s = max(r, 0.92 if contained else 0)
            if s > score:
                best, score = g["record_id"], s
    return best, score


rows = []
tally = {
    "matched_proposed": 0,
    "duplicate_proposed": 0,
    "correct_extra_proposed": 0,
    "left_for_human": 0,
}
for c in W["candidates"]:
    cid = c["candidate_id"]
    if cid in already:
        continue
    if cid in r5_anticipated:
        gid = r5_anticipated[cid]
        rows.append(
            {
                "candidate_id": cid,
                "proposition": c.get("text"),
                "model_suggestion": {
                    "semantic_type": c.get("semantic_type"),
                    "statement_role": c.get("statement_role"),
                    "polarity": c.get("polarity"),
                    "evidence_quote": c.get("evidence_quote"),
                },
                "draft": {
                    "judgement": "matched",
                    "matched_gold_id": gid,
                    "reason": f"r5 署名工作表预判配对（{gid}）；请人工核对语义等价",
                },
            }
        )
        tally["matched_proposed"] += 1
        continue
    gid, score = best_match(c)
    if gid and score >= 0.75 and gid not in claimed:
        rows.append(
            {
                "candidate_id": cid,
                "proposition": c.get("text"),
                "model_suggestion": {
                    "semantic_type": c.get("semantic_type"),
                    "statement_role": c.get("statement_role"),
                    "polarity": c.get("polarity"),
                    "evidence_quote": c.get("evidence_quote"),
                },
                "draft": {
                    "judgement": "matched",
                    "matched_gold_id": gid,
                    "reason": f"机械匹配（相似度 {score:.2f}）金标 {gid}「{gold_by_id[gid].get('quote')}」；语义等价请人工核对",
                },
            }
        )
        claimed[gid] = cid
        tally["matched_proposed"] += 1
    elif gid and score >= 0.75 and gid in claimed:
        rows.append(
            {
                "candidate_id": cid,
                "proposition": c.get("text"),
                "model_suggestion": {
                    "semantic_type": c.get("semantic_type"),
                    "statement_role": c.get("statement_role"),
                    "polarity": c.get("polarity"),
                    "evidence_quote": c.get("evidence_quote"),
                },
                "draft": {
                    "judgement": "duplicate",
                    "matched_gold_id": "",
                    "reason": f"金标 {gid} 已被 {claimed[gid]} 占用（1:1 映射）；语义等价请人工复核",
                },
            }
        )
        tally["duplicate_proposed"] += 1
    elif c.get("evidence_quote"):
        rows.append(
            {
                "candidate_id": cid,
                "proposition": c.get("text"),
                "model_suggestion": {
                    "semantic_type": c.get("semantic_type"),
                    "statement_role": c.get("statement_role"),
                    "polarity": c.get("polarity"),
                    "evidence_quote": c.get("evidence_quote"),
                },
                "draft": {
                    "judgement": "correct_extra",
                    "matched_gold_id": "",
                    "reason": "48 条金标无机械对应；evidence_quote 在案，内容真实性请人工复核",
                },
            }
        )
        tally["correct_extra_proposed"] += 1
    else:
        rows.append(
            {
                "candidate_id": cid,
                "proposition": c.get("text"),
                "model_suggestion": {},
                "draft": {
                    "judgement": "",
                    "matched_gold_id": "",
                    "reason": "证据缺失且无金标对应——留人工判定",
                },
            }
        )
        tally["left_for_human"] += 1

ws = {
    "schema_version": "unresolved-prefill-draft-1",
    "created_on": "2026-10-13",
    "status": "draft_pending_human_verification",
    "drafted_by": "agent",
    "zero_model_calls": True,
    "drafting_rules": [
        "1:1 映射：已认领金标不得二次 matched",
        "机械对应阈值 0.75（difflib 归一化），逐字包含按 0.92 计",
        "r5 署名工作表预判的 4 组池内配对直接提议 matched",
        "correct_extra 的内容真实性一律留人工复核",
        "证据缺失且无对应的行留空给人工",
    ],
    "occupation_baseline": {
        "signed_claimed_golds": [
            "NT-I06",
            "NT-I13",
            "NT-I14",
            "NT-I15",
            "NT-I16",
            "NT-I17",
            "NT-I42",
            "NT-I43",
        ],
        "r5_anticipated_pool_matches": {g: c for c, g in r5_anticipated.items()},
    },
    "tally": tally,
    "rows": rows,
}
(OUT / "prefill-draft-203.json").write_text(
    json.dumps(ws, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)
print(json.dumps({"tally": tally, "rows": len(rows)}, ensure_ascii=False, indent=1))
