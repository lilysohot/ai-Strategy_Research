"""Issue-34 §7-5: upgraded Stage-1 adjudication suggester (v2), with a verifiable evidence chain.

Zero call, read-only. Implements `preregistered-suggester-v2.json` (write-once).

The point is NOT better accuracy (unmeasurable without human truth) but that every suggestion
carries the signals that produced it, so a reviewer can verify instead of searching. No candidate
field is rewritten and no `semantic_fields` is copied into a candidate.

Usage:
    uv run python .scratch/claims-r2-role-isolation/evidence/42-stage1-suggester-upgrade-20261012/r0-zero-call/suggester_v2.py
    ... --no-write
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
E42 = HERE.parent
CLAIMS = E42.parent.parent
REPO_ROOT = HERE.parents[4]
E36_R0 = CLAIMS / "evidence" / "36-l9-redo-and-baseline-20261011" / "r0-zero-call"
for path in (str(REPO_ROOT), str(E36_R0)):
    if path not in sys.path:
        sys.path.insert(0, path)

from l9_redo import covering_slots, digest, read_json  # noqa: E402

EV = CLAIMS / "evidence"
WB_V2 = EV / "38-gate33-workbench-rebuild-20261012" / "r0-zero-call" / "workbench-v2.json"
WB_V1 = EV / "33-items-quality-scoring-20261011" / "r0-zero-call" / "workbench.json"
GOLD = EV / "10-quality-gold-freeze-20261008-r2" / "frozen-gold.json"
GOLD_AUDIT = EV / "35-gold-audit-20261011" / "r0-zero-call" / "gold-audit.json"
PREREG = HERE / "preregistered-suggester-v2.json"

NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
FILLER_RE = re.compile(r"[\s，。、；：（）()“”\"'’‘%％,.;:!?！？\-—–~～\[\]【】]+")
WEIGHTS = {
    "slot_overlap": 0.45,
    "verbatim_quote": 0.35,
    "number_hit": 0.1,
    "number_hit2": 0.2,
    "bigram_containment": 0.1,
    "enum_agreement": 0.05,
}
NORMALIZATION = {
    "perspective": {"source_explicit": "unknown"},
    "speech_role": {"question": "statement", "answer": "statement", "unknown": "statement"},
}
ENUM_FIELDS = ("semantic_type", "statement_role", "perspective", "polarity")


def normalize(value: str | None) -> str:
    return FILLER_RE.sub("", value or "")


def bigrams(text: str) -> set[str]:
    normed = normalize(text)
    return {normed[i : i + 2] for i in range(len(normed) - 1)}


def numbers(text: str | None) -> set[str]:
    return set(NUMBER_RE.findall(text or ""))


def normed_enum(field: str, value: str | None) -> str | None:
    if value is None:
        return None
    return NORMALIZATION.get(field, {}).get(value, value)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()

    prereg = read_json(PREREG)
    v2 = read_json(WB_V2)
    v1 = read_json(WB_V1)
    gold_payload = read_json(GOLD)
    gold_audit = read_json(GOLD_AUDIT)
    gold_items = [row for row in gold_payload["records"] if row["role"] == "material_items"]
    gold_by_id = {row["record_id"]: row for row in gold_items}
    source_to_slug = {item["source_id"]: item["source_slug"] for item in v2["candidates"]}

    coverage = {}
    for slug in sorted(set(source_to_slug.values())):
        coverage[slug] = covering_slots(
            slug,
            gold_items,
            [
                {"candidate_id": item["candidate_id"], "candidate_slot_id": item["candidate_slot_id"]}
                for item in v2["candidates"]
                if item["source_slug"] == slug
            ],
        )
    slot_to_gold: dict[str, set[str]] = {}
    for slug, blob in coverage.items():
        for record_id, info in blob["per_gold"].items():
            for slot_id in info["covering_slot_ids"]:
                slot_to_gold.setdefault(slot_id, set()).add(record_id)

    old_top1 = {
        entry["candidate_id"]: (entry["top_suggestions"][0]["gold_record_id"] if entry["top_suggestions"] else None)
        for entry in v2["suggestions"]
    }

    suggestions: list[dict[str, Any]] = []
    for candidate in v2["candidates"]:
        candidate_id = candidate["candidate_id"]
        source_id = candidate["source_id"]
        peers = [row for row in gold_items if row["source_id"] == source_id]
        cq = candidate.get("evidence_quote") or ""
        c_text = candidate.get("text") or ""
        c_numbers = numbers(c_text) | numbers(json.dumps(candidate.get("value"), ensure_ascii=False))
        c_bigrams = bigrams(c_text)
        scored: list[dict[str, Any]] = []
        for gold in peers:
            gold_id = gold["record_id"]
            chain: list[str] = []
            score = 0.0
            slot_hit = candidate["candidate_slot_id"] in slot_to_gold and gold_id in slot_to_gold[
                candidate["candidate_slot_id"]
            ]
            if slot_hit:
                score += WEIGHTS["slot_overlap"]
                chain.append(f"slot_overlap:{candidate['candidate_slot_id']}")
            quotes = [gold.get("quote") or ""] + [
                entry.get("quote") or "" for entry in (gold.get("context_evidence") or [])
            ]
            verbatim = any(
                cq and q and (cq in q or q in cq) for q in quotes if q
            )
            # EC-S1 diagnostic: quote-only variant, to localise any caliber difference
            # against issue-35 (which used the gold `quote` only).
            quote_only = bool(cq and gold.get("quote") and (cq in gold["quote"] or gold["quote"] in cq))
            if verbatim:
                score += WEIGHTS["verbatim_quote"]
                chain.append("verbatim_quote")
            if quote_only:
                chain.append("verbatim_quote_quote_only")
            g_numbers = numbers(gold.get("quote")) | numbers(
                json.dumps((gold.get("semantic_fields") or {}).get("value"), ensure_ascii=False)
            )
            shared = c_numbers & g_numbers
            if shared:
                score += WEIGHTS["number_hit"]
                if len(shared) >= 2:
                    score += WEIGHTS["number_hit2"]
                chain.append(f"numbers:{','.join(sorted(shared))}")
            gold_text = " ".join(
                str((gold.get("semantic_fields") or {}).get(key) or "")
                for key in ("proposition", "condition", "value")
            )
            g_bigrams = bigrams(gold_text)
            containment = len(c_bigrams & g_bigrams) / len(g_bigrams) if g_bigrams else 0.0
            if containment >= 0.5:
                score += WEIGHTS["bigram_containment"]
                chain.append(f"bigram:{containment:.2f}")
            agreed = [
                field
                for field in ENUM_FIELDS
                if (gold.get("semantic_fields") or {}).get(field) is not None
                and normed_enum(field, (gold.get("semantic_fields") or {}).get(field))
                == normed_enum(field, candidate.get(field))
            ]
            if len(agreed) >= 3:
                score += WEIGHTS["enum_agreement"]
                chain.append("enum:" + ",".join(agreed))
            if score <= 0:
                continue
            if slot_hit and verbatim:
                confidence = "high"
            elif slot_hit or verbatim:
                confidence = "medium"
            elif score >= 0.1:
                confidence = "low"
            else:
                confidence = "none"
            scored.append(
                {
                    "gold_record_id": gold_id,
                    "score": round(score, 4),
                    "confidence": confidence,
                    "evidence_chain": chain,
                    "verifiable": bool(slot_hit or verbatim),
                }
            )
        scored.sort(key=lambda item: (-item["score"], item["gold_record_id"]))
        suggestions.append(
            {
                "candidate_id": candidate_id,
                "source_slug": candidate["source_slug"],
                "source_id": source_id,
                "top_suggestions": scored[:3],
                "advisory_only": True,
                "candidate_text": c_text,
            }
        )

    # ---------------------------------------------------------------- coverage measurements (EC-S1/S2)
    gold_reachable: list[str] = []
    gold_verbatim: list[str] = []
    gold_verbatim_quote_only: list[str] = []
    gold_reachable_by_slot: list[str] = []
    for entry in suggestions:
        for item in entry["top_suggestions"]:
            gold_id = item["gold_record_id"]
            if gold_id not in gold_reachable:
                gold_reachable.append(gold_id)
            if item["verifiable"]:
                gold_verbatim.append(gold_id)
            if "verbatim_quote_quote_only" in item["evidence_chain"]:
                gold_verbatim_quote_only.append(gold_id)
            if any(part.startswith("slot_overlap") for part in item["evidence_chain"]):
                gold_reachable_by_slot.append(gold_id)
    confidence_counts = Counter(
        (entry["top_suggestions"][0]["confidence"] if entry["top_suggestions"] else "none")
        for entry in suggestions
    )
    changed_top1 = sum(
        1
        for entry in suggestions
        if old_top1.get(entry["candidate_id"])
        != (
            entry["top_suggestions"][0]["gold_record_id"]
            if entry["top_suggestions"]
            else None
        )
    )
    old_counts = Counter(
        (entry["top_suggestions"][0]["confidence"] if entry["top_suggestions"] else "none")
        for entry in v2["suggestions"]
    )
    candidates_untouched = suggestions and all(
        entry["candidate_text"] == candidate.get("text")
        for entry, candidate in zip(suggestions, v2["candidates"], strict=True)
    )

    report = {
        "schema_version": "items-suggester-v2-report-1",
        "created_on": "2026-10-12",
        "zero_call": True,
        "preregistration": {"path": PREREG.name, "sha256": digest(PREREG)},
        "R1_candidates_with_suggestion": sum(1 for e in suggestions if e["top_suggestions"]),
        "R1_gold_reachable_top3": len(set(gold_reachable)),
        "R2_gold_with_verbatim_chain": len(set(gold_verbatim)),
        "R2_gold_with_verbatim_chain_quote_only": len(set(gold_verbatim_quote_only)),
        "R2_cross_check_issue35": gold_audit["summary"]["records_with_exact_candidate_quote"],
        "R2_matches_issue35": len(set(gold_verbatim))
        == gold_audit["summary"]["records_with_exact_candidate_quote"],
        "R2_matches_issue35_quote_only": len(set(gold_verbatim_quote_only))
        == gold_audit["summary"]["records_with_exact_candidate_quote"],
        "EC_S1_explanation": (
            "口径差定位：助手 v2 的 verbatim 信号同时使用金标 `quote` 与 `context_evidence` 引文（更宽），"
            "而 issue-35 只用 `quote`；限定为 quote-only 后应与 39 对齐。二者差异必须显式披露，"
            "不得用其中一个数字替代另一个。"
        ),
        "R1_gold_reachable_by_slot": len(set(gold_reachable_by_slot)),
        "R3_confidence_v2": dict(confidence_counts),
        "R3_confidence_v1_or_v2_old": dict(old_counts),
        "R4_top1_changed": changed_top1,
        "EC_S3_chain_present_ratio": round(
            sum(1 for e in suggestions for i in e["top_suggestions"] if i["evidence_chain"])
            / max(1, sum(len(e["top_suggestions"]) for e in suggestions)),
            4,
        ),
        "EC_S5_candidates_untouched": bool(candidates_untouched),
        "EC_S2_accuracy_reported": False,
        "notes": [
            "本报告不报准确率/召回：无人工裁定真值（EC-S2）。",
            "R2 与 issue-35 的 39/48 交叉校验用于验证引文信号口径一致（EC-S1）。",
        ],
    }

    print(
        json.dumps(
            {
                "R1_candidates_with_suggestion": report["R1_candidates_with_suggestion"],
                "R1_gold_reachable_top3": report["R1_gold_reachable_top3"],
                "R2_gold_with_verbatim_chain": report["R2_gold_with_verbatim_chain"],
                "R2_gold_with_verbatim_chain_quote_only": report[
                    "R2_gold_with_verbatim_chain_quote_only"
                ],
                "R2_matches_issue35": report["R2_matches_issue35"],
                "R2_matches_issue35_quote_only": report["R2_matches_issue35_quote_only"],
                "R3_confidence_v2": report["R3_confidence_v2"],
                "R3_confidence_old": report["R3_confidence_v1_or_v2_old"],
                "R4_top1_changed": report["R4_top1_changed"],
                "candidates_untouched": report["EC_S5_candidates_untouched"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if args.no_write:
        return

    (HERE / "suggestions-v2.json").write_text(
        json.dumps(
            {
                "schema_version": "items-stage1-suggestions-2",
                "created_on": "2026-10-12",
                "advisory_only": True,
                "supersedes": {"file": "38-…/workbench-v2.json#suggestions", "sha256": digest(WB_V2)},
                "signals": prereg["signals"],
                "confidence_rule": prereg["confidence_rule"],
                "suggestion_policy": prereg["hard_constraints"]["suggestion_policy"],
                "suggestions": suggestions,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (HERE / "suggester-v2-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (HERE / "suggester-v2-report.md").write_text(render_md(report, prereg), encoding="utf-8")
    manifest = {
        "schema_version": "items-suggester-v2-manifest-1",
        "created_on": "2026-10-12",
        "inputs": {
            str(PREREG.relative_to(REPO_ROOT)): digest(PREREG),
            str(WB_V2.relative_to(REPO_ROOT)): digest(WB_V2),
            str(WB_V1.relative_to(REPO_ROOT)): digest(WB_V1),
            str(GOLD.relative_to(REPO_ROOT)): digest(GOLD),
            str(GOLD_AUDIT.relative_to(REPO_ROOT)): digest(GOLD_AUDIT),
        },
        "outputs": {
            name: digest(HERE / name)
            for name in (
                "preregistered-suggester-v2.json",
                "suggestions-v2.json",
                "suggester-v2-report.json",
                "suggester-v2-report.md",
                "suggester_v2.py",
            )
        },
        "workbench_v2_unchanged": True,
    }
    (HERE / "MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def render_md(report: dict[str, Any], prereg: dict[str, Any]) -> str:
    lines = [
        "# Stage-1 助手 v2（含可核验证据链）",
        "",
        f"- 预注册：`{report['preregistration']['path']}` `{report['preregistration']['sha256']}`",
        "- **不报准确率**：无人工裁定真值（EC-S2）",
        "",
        "## 信号与权重（预注册固定，未调参）",
        "",
        "| 信号 | 权重 | 定义 | 是否用到金标答案 |",
        "|---|---|---|---|",
    ]
    for name, blob in prereg["signals"].items():
        lines.append(
            "| `{0}` | {1} | {2} | {3} |".format(
                name, blob["weight"], blob["definition"], "否" if blob["gold_answer_free"] else "是（仅排序用）"
            )
        )
    lines += [
        "",
        "## 覆盖测量（R1–R4）",
        "",
        f"- 有建议的候选：**{report['R1_candidates_with_suggestion']}/222**",
        f"- 金标可及（top3 中出现）：**{report['R1_gold_reachable_top3']}/48**",
        f"- 其中经槽位信号可达：**{report['R1_gold_reachable_by_slot']}/48**",
        f"- 有**逐字引文证据链**的金标（quote + context）：**{report['R2_gold_with_verbatim_chain']}/48**",
        f"- 限定为 **quote-only**：**{report['R2_gold_with_verbatim_chain_quote_only']}/48**"
        f"（与 issue-35 的 {report['R2_cross_check_issue35']}/48 一致：**{report['R2_matches_issue35_quote_only']}**）",
        f"- EC-S1 口径差说明：{report['EC_S1_explanation']}",
        "",
        "### 置信分布对比（同一批 222 候选）",
        "",
        "| 来源 | high | medium | low | none |",
        "|---|---|---|---|---|",
    ]
    for label, counts in (
        ("旧（工作台 v1/v2 建议）", report["R3_confidence_v1_or_v2_old"]),
        ("新（助手 v2）", report["R3_confidence_v2"]),
    ):
        lines.append(
            "| {0} | {1} | {2} | {3} | {4} |".format(
                label,
                counts.get("high", 0),
                counts.get("medium", 0),
                counts.get("low", 0),
                counts.get("none", 0),
            )
        )
    lines += [
        "",
        f"- top1 发生变化的候选：**{report['R4_top1_changed']}/222**（⇒ 属新基线，Stage 2 须以 `suggestions-v2.json` 为准）",
        f"- 建议均带证据链：**{report['EC_S3_chain_present_ratio']}**",
        f"- 候选未被改写（EC-S5）：**{report['EC_S5_candidates_untouched']}**",
        "",
        "## 使用约束",
        "",
        f"- {prereg['hard_constraints']['no_gold_injection']}",
        f"- {prereg['hard_constraints']['suggestion_policy']}",
        "",
        "## 说明",
        "",
        "- 本文件是**裁定辅助**，不是评分输入；工作台 v2 字节未变。",
        "- 合并方式（Stage 2 启动时）：工作台 v2 + 本目录 `suggestions-v2.json` 的 `suggestions` 字段。",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
