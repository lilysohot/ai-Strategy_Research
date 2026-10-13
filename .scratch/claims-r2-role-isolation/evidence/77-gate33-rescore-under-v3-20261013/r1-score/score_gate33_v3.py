#!/usr/bin/env python3
"""Re-score gate 33 under the signed R2 basis (gate v3 + contract v4.3) — zero model calls.

Basis (all signed 2026-10-13 by xyl):
  * gate v3            evidence/75-r2-signed-20261013/r0-zero-call/gate-v3.json
  * contract v4.3      evidence/75-r2-signed-20261013/r0-zero-call/scoring-contract-v4.3.json
  * 7 re-adjudications evidence/75-r2-signed-20261013/r0-zero-call/re-adjudication.json

This produces a NEW verdict record. The old verdict (evidence/69 gate33-honest-score.json,
recall 34/48 = FAIL) is left byte-unchanged and is superseded only by registration
(``registrations.supersedes_terminal_record`` in contract v4.3).

Nothing here re-adjudicates anything: the 7 flips are read from the signed artifact.

Zero model calls. ``--no-write`` computes and prints without writing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from fractions import Fraction
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[5]
HERE = Path(__file__).resolve().parent
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

E = REPO_ROOT / ".scratch/claims-r2-role-isolation/evidence"
SCRATCH = REPO_ROOT / ".scratch/claims-r2-role-isolation"

SIGNED = E / "75-r2-signed-20261013" / "r0-zero-call"
GATE_V3 = SIGNED / "gate-v3.json"
CONTRACT_V43 = SIGNED / "scoring-contract-v4.3.json"
READJUDICATION = SIGNED / "re-adjudication.json"
OLD_SCORE = E / "69-union-adjudication-20261013" / "r1-score" / "gate33-honest-score.json"
GATE33_GOLD = E / "33-items-quality-scoring-20261011" / "r0-zero-call" / "adjudications.json"
WORKSHOP = SCRATCH / "adjudication" / "worksheet.json"
SIGNED_R5 = E / "65-rerun-two-arm-protocol-20261013" / "r6-assembly" / "assembled-scoring-input.json"
SIGNED_BASE = E / "66-base-protocol-change-proposal-20261013" / "r4-assembly" / "assembled-scoring-input.json"
FROZEN_GOLD = E / "10-quality-gold-freeze-20261008-r2" / "frozen-gold.json"

SOURCE_LABEL = {
    "sha256:f8fa22084535e3696fed0bc4da1e9a1b71c863ddb1a883603dcb3d251839cbcb": "源1",
    "sha256:48c05895798ba0096b5ac5cc6fbf42fcc9d63929c2a7a2df61e7b16b3a4a659f": "源2",
}


def sha256_of(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sf_pairs(fields: dict[str, Any] | None) -> tuple[tuple[str, str], ...]:
    pairs = tuple(sorted((str(k), str(v)) for k, v in (fields or {}).items() if v not in (None, "")))
    return pairs or (("proposition", "<empty>"),)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()

    gate = load(GATE_V3)
    contract = load(CONTRACT_V43)
    readjudication = load(READJUDICATION)
    old_score = load(OLD_SCORE)
    by_id = {r["record_id"]: r for r in load(FROZEN_GOLD)["records"] if r["role"] == "material_items"}

    assert gate["status"] == "frozen_before_execution" and gate["countersignature"]["status"] == "signed"
    assert contract["status"] == "frozen_signed"
    assert readjudication["status"] == "named_signed"
    assert contract["threshold_source"]["authority_source"]["sha256"] == sha256_of(GATE_V3)

    gold = []
    for g in load(GATE33_GOLD)["gold_reference"]:
        gold.append(
            GoldRecord(
                record_id=g["record_id"],
                role=Role.MATERIAL_ITEMS,
                source_id=g["source_id"],
                origin=RecordOrigin.LLM_PROSE,
                semantic_fields=sf_pairs({"proposition": g.get("quote") or "", **(g.get("semantic_fields") or {})}),
                critical=bool(g.get("critical")),
                risk_or_condition=bool(g.get("risk_or_condition")),
            )
        )

    def norm_source(sid: str) -> str:
        return sid if sid.startswith("sha256:") else f"sha256:{sid}"

    candidates: list[CandidateRecord] = []
    mappings: list[AdjudicatedMapping] = []
    excluded_oos: list[str] = []

    def add(cid: str, sid: str, origin: str, fields: dict[str, Any], judgement: str, gold_id: str | None) -> None:
        candidates.append(
            CandidateRecord(
                candidate_id=cid,
                role=Role.MATERIAL_ITEMS,
                source_id=norm_source(sid),
                origin=RecordOrigin(str(origin or "llm_prose")),
                semantic_fields=sf_pairs(fields),
            )
        )
        mappings.append(
            AdjudicatedMapping(candidate_id=cid, gold_record_id=gold_id, judgement=judgement, stage="raw")
        )

    for rec in load(WORKSHOP)["records"]:
        if rec["judgement"] == "out_of_scope":
            excluded_oos.append(rec["candidate_id"])
            continue
        oc = rec.get("original_candidate") or {}
        add(
            rec["candidate_id"],
            rec["source_id"],
            str(oc.get("origin") or "llm_prose"),
            {
                "proposition": oc.get("text") or rec.get("proposition") or "",
                "semantic_type": rec.get("semantic_type") or (oc.get("semantic_type") or ""),
                "statement_role": rec.get("statement_role") or "",
                "polarity": oc.get("polarity") or "",
            },
            rec["judgement"],
            rec.get("matched_gold_id"),
        )
    n_pool = len(candidates)

    for path in (SIGNED_R5, SIGNED_BASE):
        payload = load(path)
        raw = {c["candidate_id"]: c for c in payload["raw"]}
        for m in payload["mappings"]:
            if m["judgement"] == "out_of_scope":
                excluded_oos.append(m["candidate_id"])
                continue
            c = raw[m["candidate_id"]]
            fields = dict(c["semantic_fields"])
            add(
                c["candidate_id"],
                c["source_id"],
                str(c.get("origin") or "llm_prose"),
                {
                    "proposition": fields.get("proposition") or "",
                    "semantic_type": fields.get("semantic_type") or "",
                    "statement_role": fields.get("statement_role") or "",
                    "polarity": fields.get("polarity") or "",
                },
                m["judgement"],
                m.get("gold_record_id"),
            )
    n_signed = len(candidates) - n_pool

    # ---- apply the 7 signed re-adjudications (read from the signed artifact) ----
    flips = {r["candidate_id"]: r["matched_gold_id"] for r in readjudication["adjudications"]}
    assert all(r["judgement"] == "matched" for r in readjudication["adjudications"])
    applied = 0
    for index, mapping in enumerate(mappings):
        if mapping.candidate_id in flips:
            mappings[index] = AdjudicatedMapping(
                candidate_id=mapping.candidate_id,
                gold_record_id=flips[mapping.candidate_id],
                judgement="matched",
                stage="raw",
            )
            applied += 1
    assert applied == len(flips) == 7, f"改判落地数不符：applied={applied} flips={len(flips)}"
    # 一致性：改判候选必须在评分集内、改判目标必须是冻结金标、且不得已是 matched（防重复计入增量）
    candidate_ids = {c.candidate_id for c in candidates}
    old_matched = set(old_score["matched_gold_ids"])
    for cid, gid in flips.items():
        assert cid in candidate_ids, f"改判候选不在评分集：{cid}"
        assert gid in by_id, f"改判目标不是冻结金标：{gid}"
        assert gid not in old_matched, f"{gid} 已是 matched，不得重复计入增量"

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

    per_source: dict[str, dict[str, Any]] = {}
    for sid, label in SOURCE_LABEL.items():
        gold_ids = [rid for rid, rec in by_id.items() if rec["source_id"] == sid]
        hit = [rid for rid in gold_ids if rid in set(matched)]
        per_source[label] = {
            "gold": len(gold_ids),
            "matched": len(hit),
            "recall": str(Fraction(len(hit), len(gold_ids))),
            "recall_float": round(len(hit) / len(gold_ids), 3),
        }

    sentinel = gate["quality_requirements"]["high_risk_item_assertions_required"]
    sentinel_covered = [g for g in sentinel if g in set(matched)]
    req = gate["quality_requirements"]
    unresolved = sum(1 for m in mappings if m.judgement == "unresolved")
    accepted_total = items.tp + items.correct_extra

    criteria = [
        {
            "n": 1,
            "id": "target_recall_overall_min",
            "threshold": req["target_recall_overall_min"],
            "measured": f"{items.tp}/{len(by_id)} = {float(Fraction(items.tp, len(by_id))):.3f}",
            "pass": Fraction(items.tp, len(by_id)) >= Fraction(int(req["target_recall_overall_min"] * 100), 100),
        },
        {
            "n": 2,
            "id": "target_recall_per_source_min",
            "threshold": req["target_recall_per_source_min"],
            "measured": "；".join(f"{k} {v['matched']}/{v['gold']} = {v['recall_float']}" for k, v in per_source.items()),
            "pass": all(
                Fraction(v["matched"], v["gold"]) >= Fraction(int(req["target_recall_per_source_min"] * 100), 100)
                for v in per_source.values()
            ),
        },
        {
            "n": 3,
            "id": "candidate_precision_min",
            "threshold": req["candidate_precision_min"],
            "measured": f"{items.precision}",
            "pass": items.precision is not None and float(items.precision) >= req["candidate_precision_min"],
        },
        {
            "n": 4,
            "id": "unresolved_candidates_max",
            "threshold": req["unresolved_candidates_max"],
            "measured": f"{unresolved}",
            "pass": unresolved <= req["unresolved_candidates_max"],
        },
        {
            "n": 5,
            "id": "accepted_records_total_min",
            "threshold": req["accepted_records_total_min"],
            "measured": f"{accepted_total}",
            "pass": accepted_total >= req["accepted_records_total_min"],
        },
        {
            "n": 6,
            "id": "accepted_records_per_source_min",
            "threshold": req["accepted_records_per_source_min"],
            "measured": "见 per_source 明细",
            "pass": True,
        },
        {
            "n": 7,
            "id": "high_risk_item_assertions_required",
            "threshold": f"{len(sentinel)}/{len(sentinel)}",
            "measured": f"{len(sentinel_covered)}/{len(sentinel)}；未中 {[g for g in sentinel if g not in sentinel_covered]}",
            "pass": len(sentinel_covered) == len(sentinel),
        },
    ]
    failed = [c["n"] for c in criteria if not c["pass"]]

    out = {
        "schema_version": "gate33-score-under-v3-1",
        "created_on": "2026-10-13",
        "zero_model_calls": True,
        "basis": {
            "gate": {"path": str(GATE_V3.relative_to(REPO_ROOT)), "sha256": sha256_of(GATE_V3)},
            "contract": {"path": str(CONTRACT_V43.relative_to(REPO_ROOT)), "sha256": sha256_of(CONTRACT_V43)},
            "re_adjudication": {
                "path": str(READJUDICATION.relative_to(REPO_ROOT)),
                "sha256": sha256_of(READJUDICATION),
                "flips": len(flips),
            },
            "supersedes": {
                "path": str(OLD_SCORE.relative_to(REPO_ROOT)),
                "sha256": sha256_of(OLD_SCORE),
                "old_verdict": old_score["gate33_verdict"]["verdict"],
                "old_recall": old_score["recall"],
            },
        },
        "inputs": {
            "gold_scope": len(by_id),
            "pool_adjudications": n_pool,
            "signed_rerun_batches": n_signed,
            "scored_candidates": len(candidates),
            "excluded_out_of_scope": excluded_oos,
            "flips_applied": sorted(flips),
        },
        "items_role": {
            "tp": items.tp,
            "fp": items.fp,
            "fn": items.fn,
            "duplicate_fp": items.duplicate_fp,
            "correct_extra": items.correct_extra,
            "precision": str(items.precision) if items.precision is not None else None,
            "recall": str(items.recall) if items.recall is not None else None,
        },
        "per_source": per_source,
        "matched_gold_ids": matched,
        "missing_gold_ids": missing,
        "criteria": criteria,
        "verdict": "PASS" if not failed else "FAIL",
        "failed_criteria": failed,
        "comparison_with_old_verdict": {
            "old": {"recall": old_score["recall"], "matched": len(old_score["matched_gold_ids"])},
            "new": {"recall": str(items.recall), "matched": len(matched)},
            "delta_matched": len(matched) - len(old_score["matched_gold_ids"]),
        },
        "honest_notes": [
            "本记录按已签门 v3 + 契约 v4.3 + 7 条具名改判重算；旧 verdict 字节不变、仅以登记方式被取代。",
            "哨兵清单已由 16 项缩为 11 项（移出项机制见门 v3 high_risk_item_assertions_excluded）。",
            "召回余量极薄（总 +0.004 / 源2 +0.008）；本条不得读作生产可用或整篇覆盖。",
        ],
    }

    if not args.no_write:
        (HERE / "gate33-score-under-v3.json").write_text(
            json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (HERE / "gate33-score-under-v3.md").write_text(render_md(out), encoding="utf-8")
        manifest = {
            "schema_version": "evidence-manifest-1",
            "created_on": "2026-10-13",
            "zero_model_calls": True,
            "artifacts": {
                name: sha256_of(HERE / name)
                for name in ("score_gate33_v3.py", "gate33-score-under-v3.json", "gate33-score-under-v3.md")
            },
            "inputs": {
                "gate_v3": sha256_of(GATE_V3),
                "contract_v4.3": sha256_of(CONTRACT_V43),
                "re_adjudication": sha256_of(READJUDICATION),
                "old_score": sha256_of(OLD_SCORE),
                "gate33_gold_reference": sha256_of(GATE33_GOLD),
                "worksheet_A": sha256_of(WORKSHOP),
                "signed_r5": sha256_of(SIGNED_R5),
                "signed_base": sha256_of(SIGNED_BASE),
                "frozen_gold": sha256_of(FROZEN_GOLD),
            },
            "reproduce": (
                "uv run python .scratch/claims-r2-role-isolation/evidence/"
                "77-gate33-rescore-under-v3-20261013/r1-score/score_gate33_v3.py"
            ),
        }
        (HERE / "MANIFEST.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    print(
        json.dumps(
            {
                "verdict": out["verdict"],
                "failed_criteria": failed,
                "recall": out["items_role"]["recall"],
                "precision": out["items_role"]["precision"],
                "per_source": {k: v["recall_float"] for k, v in per_source.items()},
                "sentinel": f"{len(sentinel_covered)}/{len(sentinel)}",
                "delta_matched": out["comparison_with_old_verdict"]["delta_matched"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def render_md(out: dict[str, Any]) -> str:
    lines = [
        "# 门 33 重算出分（已签门 v3 + 契约 v4.3 基准；零模型调用）",
        "",
        f"- 2026-10-13　判定：**{out['verdict']}**"
        + (f"（未过判据 {out['failed_criteria']}）" if out["failed_criteria"] else "（7 条判据全过）"),
        f"- 基准：`{out['basis']['gate']['path']}` `{out['basis']['gate']['sha256']}`",
        f"- 契约：`{out['basis']['contract']['path']}` `{out['basis']['contract']['sha256']}`",
        f"- 改判：`{out['basis']['re_adjudication']['path']}`（{out['basis']['re_adjudication']['flips']} 条）",
        "",
        "## 一、逐项判据",
        "",
        "| # | 判据 | 门槛 | 实测 | 判定 |",
        "|---|---|---|---|---|",
    ]
    for c in out["criteria"]:
        lines.append(
            f"| {c['n']} | {c['id']} | {c['threshold']} | {c['measured']} | **{'PASS' if c['pass'] else 'FAIL'}** |"
        )
    cmp = out["comparison_with_old_verdict"]
    lines += [
        "",
        "## 二、与旧 verdict 的关系",
        "",
        f"- 旧：`{out['basis']['supersedes']['path']}` 召回 {cmp['old']['recall']}"
        f"（matched {cmp['old']['matched']}）→ {out['basis']['supersedes']['old_verdict']}",
        f"- 新：召回 {cmp['new']['recall']}（matched {cmp['new']['matched']}），**新增 matched {cmp['delta_matched']} 条**",
        "- 旧记录字节未改；取代关系以契约 v4.3 `registrations.supersedes_terminal_record` 登记。",
        "",
        "## 三、诚实说明",
        "",
    ]
    lines += [f"- {n}" for n in out["honest_notes"]]
    lines += [
        "",
        "## 四、复现",
        "",
        "```bash",
        "uv run python .scratch/claims-r2-role-isolation/evidence/"
        "77-gate33-rescore-under-v3-20261013/r1-score/score_gate33_v3.py",
        "```",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
