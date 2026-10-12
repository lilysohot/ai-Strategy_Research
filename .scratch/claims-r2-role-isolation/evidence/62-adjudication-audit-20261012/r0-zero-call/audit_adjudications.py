"""Sample audit + mechanical consistency check of the 222 adjudications.

Follows ``preregistered-audit.json`` (written before this run). Zero model calls. Read-only on
the worksheet — it is never modified.

Mechanical checks run on **all 222** records; a stratified deterministic sample is emitted as
audit **cards** for human re-verification. This tool cannot judge semantic equivalence — that
is the adjudicator's job — so it never claims "verified correct".

Usage:
    uv run python .scratch/.../62-adjudication-audit-20261012/r0-zero-call/audit_adjudications.py
"""

from __future__ import annotations

import hashlib
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
E62 = HERE.parent
CLAIMS = E62.parent.parent
REPO_ROOT = HERE.parents[4]
sys.path.insert(0, str(REPO_ROOT))

WORK = CLAIMS / "adjudication"
SHEET = WORK / "worksheet.json"
GOLD_REF = WORK / "gold-reference.json"
GATE_V2 = (
    CLAIMS / "evidence/28-items-only-quality-gate-20261010/r0-zero-call/preregistered-gate-v2.json"
)
FROZEN_GOLD = CLAIMS / "evidence/10-quality-gold-freeze-20261008-r2/frozen-gold.json"

# Field-shaped assertions among the 16 (from gate 28 high_risk_item_annotations).
FIELD_ASSERTIONS: dict[str, dict[str, str]] = {
    "NT-I37": {"semantic_type": "opinion"},
    "NT-I38": {"semantic_type": "opinion", "polarity": "mixed"},
    "NT-I45": {"perspective": "quoted_other", "source_stance": "challenged"},
    "NT-I46": {"perspective": "quoted_other", "source_stance": "challenged"},
    "NT-I47": {"perspective": "quoted_other", "source_stance": "challenged"},
    "NT-I48": {"perspective": "quoted_other", "source_stance": "challenged"},
}


def sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def load() -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    sheet = json.loads(SHEET.read_text(encoding="utf-8"))
    gold_ref = json.loads(GOLD_REF.read_text(encoding="utf-8"))
    gate = json.loads(GATE_V2.read_text(encoding="utf-8"))
    frozen = json.loads(FROZEN_GOLD.read_text(encoding="utf-8"))
    return sheet, gold_ref["records"], gate, frozen


def mechanical(sheet: dict[str, Any], gold_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    records = sheet["records"]
    findings: dict[str, list[str]] = defaultdict(list)

    for row in records:
        cid = row["candidate_id"]
        fields = row.get("canonical_observed_fields") or {}
        text = (row.get("original_candidate") or {}).get("text") or ""
        evidence = row.get("evidence") or {}
        quote = str(evidence.get("quote") or "")
        locator = str(evidence.get("locator") or "")
        reason = str(row.get("reason") or "").strip()
        judgement = str(row.get("judgement") or "")
        gold_id = row.get("matched_gold_id")

        if not quote and not locator:
            findings["C1_evidence_empty"].append(cid)
        elif quote and quote not in text:
            findings["C2_quote_not_attributable"].append(cid)
        if len(reason) < 8:
            findings["C3_reason_too_short"].append(cid)
        if judgement == "matched" and gold_id:
            gold_row = gold_by_id.get(str(gold_id), {})
            gold_stance = str(gold_row.get("source_stance") or "")
            if gold_stance and str(fields.get("source_stance") or "") == "absent":
                findings["C5_stance_absent_on_matched"].append(cid)
            expected = FIELD_ASSERTIONS.get(str(gold_id))
            if expected:
                mismatched = {
                    key: (expected[key], str(fields.get(key) or ""))
                    for key in expected
                    if str(fields.get(key) or "") != expected[key]
                }
                if mismatched:
                    findings["C6_high_risk_field_mismatch"].append(
                        f"{cid}→{gold_id}:{json.dumps(mismatched, ensure_ascii=False)}"
                    )
        if (
            str(fields.get("statement_role") or "") == "condition"
            and str(fields.get("condition") or "") == "absent"
        ):
            findings["C8_condition_absent_on_condition_role"].append(cid)

    # C4: copy-paste reasons.
    reason_counts = Counter(str(row.get("reason") or "").strip() for row in records)
    for reason, count in reason_counts.items():
        if reason and count >= 5:
            findings["C4_reason_copypaste"].append(f"{count}×「{reason[:40]}」")

    # C7: identical text, divergent judgement.
    by_text: dict[str, set[str]] = defaultdict(set)
    by_text_ids: dict[str, list[str]] = defaultdict(list)
    for row in records:
        text = (row.get("original_candidate") or {}).get("text") or ""
        if not text:
            continue
        by_text[text].add(str(row.get("judgement") or ""))
        by_text_ids[text].append(row["candidate_id"])
    for text, judgements in by_text.items():
        if len(judgements) > 1:
            findings["C7_same_text_divergent_judgement"].append(
                f"{by_text_ids[text]}→{sorted(judgements)}"
            )

    # C9: duplicate without a matched sibling on the same gold.
    matched_golds = {
        str(row["matched_gold_id"])
        for row in records
        if str(row.get("judgement")) == "matched" and row.get("matched_gold_id")
    }
    for row in records:
        if str(row.get("judgement")) != "duplicate":
            continue
        fields = row.get("canonical_observed_fields") or {}
        proposition = str(fields.get("proposition") or "")
        siblings = {
            str(other["matched_gold_id"])
            for other in records
            if str(other.get("judgement")) == "matched"
            and str((other.get("canonical_observed_fields") or {}).get("proposition") or "")
            == proposition
        }
        if not (siblings & matched_golds):
            findings["C9_duplicate_claims_no_matched_sibling"].append(row["candidate_id"])

    return {key: sorted(set(value)) for key, value in findings.items()}


def sample_ids(
    sheet: dict[str, Any], high_risk: tuple[str, ...]
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    records = sheet["records"]
    seed = hashlib.sha256(SHEET.read_bytes()).hexdigest()[:8]
    rng = random.Random(seed)
    forced: list[dict[str, Any]] = []
    rest: list[dict[str, Any]] = []
    for row in records:
        judgement = str(row.get("judgement") or "")
        gold_id = str(row.get("matched_gold_id") or "")
        if gold_id in high_risk or judgement in ("correct_extra", "duplicate"):
            forced.append(row)
        else:
            rest.append(row)
    rest_sample = [row for row in rest if rng.random() < 0.2]
    chosen = forced + rest_sample
    chosen.sort(key=lambda row: row["candidate_id"])
    stats = {
        "seed": seed,
        "forced": len(forced),
        "rest_population": len(rest),
        "rest_sampled": len(rest_sample),
        "total": len(chosen),
    }
    return chosen, stats


def card(row: dict[str, Any], gold_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    fields = row.get("canonical_observed_fields") or {}
    gold_id = str(row.get("matched_gold_id") or "")
    gold = gold_by_id.get(gold_id, {})
    return {
        "candidate_id": row["candidate_id"],
        "judgement": row.get("judgement"),
        "matched_gold_id": gold_id or None,
        "candidate_text": (row.get("original_candidate") or {}).get("text"),
        "evidence": row.get("evidence"),
        "gold_proposition": gold.get("proposition"),
        "gold_fields": {
            key: gold.get(key)
            for key in ("semantic_type", "statement_role", "polarity", "source_stance", "condition")
        },
        "recorded_fields": fields,
        "reason": row.get("reason"),
        "reviewer": row.get("reviewer"),
    }


def main() -> int:
    sheet, gold_records, gate, frozen = load()
    gold_by_id = {row["record_id"]: row for row in gold_records}
    high_risk = tuple(gate["quality_requirements"]["high_risk_item_assertions_required"])

    findings = mechanical(sheet, gold_by_id)
    chosen, stats = sample_ids(sheet, high_risk)
    cards = [card(row, gold_by_id) for row in chosen]

    judgement_counts = Counter(str(row.get("judgement")) for row in sheet["records"])
    matched_golds = sorted(
        {
            str(row["matched_gold_id"])
            for row in sheet["records"]
            if str(row.get("judgement")) == "matched" and row.get("matched_gold_id")
        }
    )
    unmatched_gold = sorted(set(gold_by_id) - set(matched_golds))
    critical_matched = sorted(
        {
            str(row["matched_gold_id"])
            for row in sheet["records"]
            if str(row.get("judgement")) == "matched"
        }
        & {
            row["record_id"]
            for row in frozen["records"]
            if row.get("critical") and row["role"] == "material_items"
        }
    )
    critical_missing = sorted(
        {
            row["record_id"]
            for row in frozen["records"]
            if row.get("critical") and row["role"] == "material_items"
        }
        - set(matched_golds)
    )

    report: dict[str, Any] = {
        "schema_version": "items-adjudication-audit-1",
        "created_on": "2026-10-12",
        "zero_call": True,
        "preregistration": "preregistered-audit.json（先于本运行落盘）",
        "inputs": {
            str(SHEET.relative_to(REPO_ROOT)): sha256(SHEET),
            str(GOLD_REF.relative_to(REPO_ROOT)): sha256(GOLD_REF),
            str(GATE_V2.relative_to(REPO_ROOT)): sha256(GATE_V2),
        },
        "sample": stats,
        "distribution": {
            "judgements": dict(judgement_counts),
            "matched_gold_total": len(matched_golds),
            "gold_total": len(gold_by_id),
            "unmatched_gold_ids": unmatched_gold,
            "high_risk_matched": sorted(set(matched_golds) & set(high_risk)),
            "high_risk_unmatched": sorted(set(high_risk) - set(matched_golds)),
            "critical_matched": critical_matched,
            "critical_missing": critical_missing,
        },
        "mechanical_findings": findings,
        "mechanical_findings_counts": {key: len(value) for key, value in findings.items()},
        "cards_count": len(cards),
        "verdict": (
            "机械一致性检查完成；**语义正确性未经验证**——需由人逐张复核卡确认。"
            if not findings
            else f"机械一致性发现 {sum(len(v) for v in findings.values())} 处待复核项。"
        ),
        "not_claimed": [
            "本工具不判定语义等价（裁定人职责）；机械检查通过 ≠ 标记正确。",
            "不修改 worksheet.json 的字节。",
        ],
        "in_place_edits": 0,
    }

    (HERE / "audit-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (WORK / "audit-sample.json").write_text(
        json.dumps(
            {
                "schema_version": "items-audit-cards-1",
                "seed": stats["seed"],
                "how_to_use": "逐张看 candidate_text vs gold_proposition，确认 judgement 与字段；可疑处改 worksheet.json 后重跑 validate.py",
                "cards": cards,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (WORK / "audit-sample.md").write_text(render_cards(cards, stats, report), encoding="utf-8")
    manifest = {
        "schema_version": "items-audit-manifest-1",
        "created_on": "2026-10-12",
        "zero_call": True,
        "inputs": report["inputs"],
        "outputs": {
            item.name: sha256(item)
            for item in sorted(HERE.iterdir())
            if item.is_file() and item.name != "MANIFEST.json"
        },
        "written_to_workdir": {
            str((WORK / "audit-sample.json").relative_to(REPO_ROOT)): sha256(
                WORK / "audit-sample.json"
            ),
            str((WORK / "audit-sample.md").relative_to(REPO_ROOT)): sha256(
                WORK / "audit-sample.md"
            ),
        },
        "in_place_edits": 0,
    }
    (HERE / "MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(json.dumps(report["mechanical_findings_counts"], ensure_ascii=False, indent=1))
    print(json.dumps({k: v for k, v in stats.items()}, ensure_ascii=False, indent=1))
    print(
        json.dumps(
            {
                "matched_gold": len(matched_golds),
                "high_risk_matched": len(report["distribution"]["high_risk_matched"]),
                "critical_missing": len(critical_missing),
            },
            ensure_ascii=False,
        )
    )
    return 0


def render_cards(cards: list[dict[str, Any]], stats: dict[str, int], report: dict[str, Any]) -> str:
    lines = [
        "# 抽样复核卡（待人工复核）",
        "",
        f"- 抽样：强制 {stats['forced']} 条（16 条 high-risk 断言命中 + 全部 correct_extra/duplicate）"
        f" ＋ 其余随机 20%（{stats['rest_sampled']}/{stats['rest_population']}）＝ **{stats['total']} 条**",
        f"- 种子：`{stats['seed']}`（worksheet 文件哈希 ⇒ 可复现）",
        "- **怎么用**：逐张看 `candidate_text` 与 `gold_proposition`，确认 judgement 与 4 个人判字段；"
        "有疑问就改 `worksheet.json` 对应记录，改完重跑 `validate.py`",
        "",
        "## 机械一致性检查（对全部 222 条执行）",
        "",
        "| 检查 | 命中 |",
        "|---|---|",
    ]
    for key, count in report["mechanical_findings_counts"].items():
        lines.append(f"| `{key}` | {count} |")
    lines += [
        "",
        "> 机械检查通过 ≠ 标记正确；它只标“结构上可疑”。语义等价由你复核。",
        "",
        "## 复核卡",
        "",
    ]
    for index, item in enumerate(cards, start=1):
        lines += [
            f"### {index}. `{item['candidate_id']}` → judgement=`{item['judgement']}`",
            "",
            f"- **候选原文**：{item['candidate_text']}",
            f"- **引文**：{item['evidence']}",
            f"- **金标** `{item['matched_gold_id'] or '—'}`：{item['gold_proposition'] or '—'}",
            f"- **金标字段**：{json.dumps(item['gold_fields'], ensure_ascii=False)}",
            f"- **已录字段**：{json.dumps(item['recorded_fields'], ensure_ascii=False)}",
            f"- **reason**：{item['reason']}",
            "",
        ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.exit(main())
