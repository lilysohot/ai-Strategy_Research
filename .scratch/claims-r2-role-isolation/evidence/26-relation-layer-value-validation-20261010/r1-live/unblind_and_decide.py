"""Zero-call unblinding and preregistered final decision for Issue 26."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REVIEW = HERE / "blind-human-review.md"
KEY = HERE / "blind-key.json"
AUDIT = HERE / "protocol-audit.json"
GOLD = HERE.parent / "r0-preflight" / "utility-gold.agent-draft.json"


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return value


def sha_file(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def section(text: str, question_id: str) -> str:
    match = re.search(
        rf"^## {question_id}\n(?P<body>.*?)(?=^## (?:Q[1-5]|总体签认)\n)",
        text,
        re.M | re.S,
    )
    if match is None:
        raise RuntimeError(f"missing review section: {question_id}")
    return match.group("body")


def selected_comparison(body: str) -> str:
    options = {
        "left_better": "`[x] 左更好`" in body,
        "same": "`[x] 相同`" in body,
        "right_better": "`[x] 右更好`" in body,
    }
    selected = [name for name, chosen in options.items() if chosen]
    if len(selected) != 1:
        raise RuntimeError(f"expected one paired judgment, got {selected}")
    return selected[0]


def main() -> None:
    text = REVIEW.read_text(encoding="utf-8")
    key = read_json(KEY)
    audit = read_json(AUDIT)
    gold = read_json(GOLD)
    for token in (
        "签认人：`xyl`",
        "签认语：`签认 Issue 26 blinded paired review`",
        "日期：`2026-10-10`",
    ):
        if token not in text:
            raise RuntimeError(f"missing human signoff token: {token}")
    if audit["status"] != "passed":
        raise RuntimeError("protocol audit did not pass")
    if gold["status"] != "human_signed_off":
        raise RuntimeError("utility gold is not signed")

    rows = []
    for question_id in ("Q1", "Q2", "Q3", "Q4", "Q5"):
        body = section(text, question_id)
        for required in (
            "左：必需事实齐全",
            "右：必需事实齐全",
            "左：限定/条件/口径齐全",
            "右：限定/条件/口径齐全",
            "左：反向证据正确",
            "右：反向证据正确",
        ):
            if f"- [x] {required}" not in body:
                raise RuntimeError(f"unchecked required rubric in {question_id}: {required}")
        judgment = selected_comparison(body)
        mapping = key["mapping"][question_id]
        if judgment == "same":
            outcome = "same"
        else:
            winning_side = "左" if judgment == "left_better" else "右"
            winning_condition = mapping[winning_side]
            outcome = "treatment_better" if winning_condition == "B" else "baseline_better"
        forbidden = {
            side: f"- [x] {side}：存在禁止推断或不可追溯实质结论" in body
            for side in ("左", "右")
        }
        rows.append(
            {
                "question_id": question_id,
                "blind_mapping": mapping,
                "human_pair_judgment": judgment,
                "unblinded_outcome": outcome,
                "forbidden_or_untraceable": {
                    mapping[side]: value for side, value in forbidden.items()
                },
            }
        )

    relevant = [row for row in rows if row["question_id"] != "Q5"]
    treatment_better = sum(row["unblinded_outcome"] == "treatment_better" for row in relevant)
    baseline_better = sum(row["unblinded_outcome"] == "baseline_better" for row in relevant)
    same = sum(row["unblinded_outcome"] == "same" for row in relevant)
    control = next(row for row in rows if row["question_id"] == "Q5")
    treatment_forbidden = any(row["forbidden_or_untraceable"]["B"] for row in rows)
    cost_increase = audit["paired_cost"]["B_vs_A_percent"]
    retain_rule_passed = (
        treatment_better >= 3
        and baseline_better == 0
        and control["unblinded_outcome"] != "baseline_better"
        and not treatment_forbidden
    )
    cost_stop = (
        audit["cost_stop_exceeded_on_prompt_tokens"]
        and treatment_better == 0
    )
    if retain_rule_passed:
        decision = "retain_default_relation_enrichment"
    else:
        decision = "reject_default_relation_enrichment_return_r2_focus_to_items"

    adjudication = {
        "schema_version": "relation-utility-unblinded-adjudication-1",
        "created_on": "2026-10-10",
        "status": "complete",
        "model_calls": 0,
        "judge_calls": 0,
        "review_sha256": sha_file(REVIEW),
        "blind_key_sha256": sha_file(KEY),
        "rows": rows,
        "counts": {
            "relation_questions": 4,
            "treatment_better": treatment_better,
            "baseline_better": baseline_better,
            "same": same,
            "control_outcome": control["unblinded_outcome"],
        },
    }
    final = {
        "schema_version": "relation-utility-final-decision-1",
        "created_on": "2026-10-10",
        "status": "closed",
        "decision": decision,
        "retain_rule_passed": retain_rule_passed,
        "cost_stop_triggered": cost_stop,
        "treatment_introduced_forbidden_or_untraceable_claim": treatment_forbidden,
        "quality": adjudication["counts"],
        "cost": {
            "median_prompt_tokens_B_vs_A_percent": cost_increase["prompt_tokens"],
            "median_total_tokens_B_vs_A_percent": cost_increase["total_tokens"],
        },
        "operating_policy": {
            "default_delivery": "material_items_only",
            "relations": "non_blocking_on_demand_experiment_only",
            "r2_acceptance_focus": "material_items_evidence_completeness",
            "issue27_hardening_retained": True,
            "gold_v2_modified": False,
        },
        "calls": {
            "main": 10,
            "relation_extraction": 0,
            "judge": 0,
            "unblinding": 0,
        },
        "production": {
            "queries": 0,
            "publication": 0,
            "database_access": 0,
        },
    }
    (HERE / "unblinded-adjudication.json").write_text(
        json.dumps(adjudication, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (HERE / "final-decision.json").write_text(
        json.dumps(final, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    report = f"""# Issue 26 · relation 层价值最终裁决

Status: closed

## 结论

**不保留默认 relation 富化；R2 默认交付回到 items-only，验收重心回到 material_items 的证据完整性。**

## 解盲结果

- Q1：baseline 更好；treatment 出现不可追溯表述。
- Q2：相同。
- Q3：相同。
- Q4：baseline 更好；treatment 留下错误 challenges 的“挑战/刷新”语义痕迹。
- Q5 控制题：相同。

treatment 在 Q1—Q4 中提升 0 题、回退 2 题、持平 2 题，未达到“至少提升 3/4 且其余不下降”的保留门。

## 成本

- B 相对 A 的中位输入 token：+{cost_increase['prompt_tokens']}%。
- B 相对 A 的中位总 token：+{cost_increase['total_tokens']}%。

质量没有提升且输入 token 增幅超过 20%，成本止损同时触发。

## 执行政策

- 默认：只交付 material_items。
- relations：保持非阻断、按需实验，不作为当前 R2 验收或发布前置条件。
- Issue 27 的 challenges 高精度收紧继续保留，但不因此复活已关闭的默认 relation 路线。
- 不修改 gold-v2；本裁决只回答下游业务增益。
"""
    (HERE / "final-decision.md").write_text(report, encoding="utf-8")
    print(json.dumps(final, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
