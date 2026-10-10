"""Zero-call protocol audit and blinded human-review packet for Issue 26."""

from __future__ import annotations

import hashlib
import json
import re
import statistics
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "freeze-manifest.json"
SUMMARY = HERE / "execution-summary.json"
RESULTS = HERE / "results"


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return value


def sha_file(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def parse_response(value: Any) -> dict[str, Any]:
    if not isinstance(value, str):
        raise ValueError("response is not text")
    parsed = json.loads(value)
    if not isinstance(parsed, dict) or set(parsed) != {"answer", "claims", "limitations"}:
        raise ValueError("response does not match the requested top-level object")
    if not isinstance(parsed["answer"], str):
        raise ValueError("answer is not text")
    if not isinstance(parsed["claims"], list) or not isinstance(parsed["limitations"], list):
        raise ValueError("claims or limitations is not a list")
    return parsed


def main() -> None:
    manifest = read_json(MANIFEST)
    summary = read_json(SUMMARY)
    if summary["freeze_manifest_sha256"] != sha_file(MANIFEST):
        raise RuntimeError("execution did not use the current freeze manifest")
    if summary["calls_attempted"] != 10 or summary["calls_succeeded"] != 10:
        raise RuntimeError("the bounded execution is not complete")

    audits: list[dict[str, Any]] = []
    responses: dict[str, dict[str, Any]] = {}
    prompt_tokens: dict[str, list[int]] = {"A": [], "B": []}
    total_tokens: dict[str, list[int]] = {"A": [], "B": []}
    for run in summary["runs"]:
        path = RESULTS / run["result_file"]
        if sha_file(path) != run["result_sha256"]:
            raise RuntimeError(f"result hash drifted: {path.name}")
        record = read_json(path)
        parsed = parse_response(record["response"])
        cell = record["cell"]
        condition = record["condition"]
        delivered = set(record["consumption_ledger"]["delivered_item_ids"])
        cited_text = set(re.findall(r"itm_[0-9a-f]{16}", record["response"]))
        claim_ids: set[str] = set()
        claim_shape_valid = True
        for claim in parsed["claims"]:
            if not isinstance(claim, dict) or set(claim) != {"statement", "evidence_item_ids"}:
                claim_shape_valid = False
                continue
            ids = claim["evidence_item_ids"]
            if not isinstance(claim["statement"], str) or not isinstance(ids, list) or not all(
                isinstance(value, str) for value in ids
            ):
                claim_shape_valid = False
                continue
            claim_ids.update(ids)
        usage = record["diagnostics"]["usage"]
        prompt_tokens[condition].append(int(usage["prompt_tokens"]))
        total_tokens[condition].append(int(usage["total_tokens"]))
        audit = {
            "cell": cell,
            "json_contract_valid": True,
            "claim_shape_valid": claim_shape_valid,
            "claim_ids_subset_of_delivery": claim_ids <= delivered,
            "text_citations_subset_of_delivery": cited_text <= delivered,
            "uncited_claim_objects": sum(
                not claim.get("evidence_item_ids", [])
                for claim in parsed["claims"]
                if isinstance(claim, dict)
            ),
            "relation_id_leaked_to_answer": bool(re.search(r"rel_[0-9a-f]{16}", record["response"])),
            "tool_calls": record["diagnostics"]["tool_calls"],
            "delivered_item_count": len(delivered),
            "delivered_relation_count": len(
                record["consumption_ledger"]["delivered_relation_ids"]
            ),
        }
        audit["protocol_pass"] = (
            audit["json_contract_valid"]
            and audit["claim_shape_valid"]
            and audit["claim_ids_subset_of_delivery"]
            and audit["text_citations_subset_of_delivery"]
            and audit["uncited_claim_objects"] == 0
            and not audit["relation_id_leaked_to_answer"]
            and audit["tool_calls"] == 0
        )
        audits.append(audit)
        responses[cell] = parsed

    medians = {
        condition: {
            "prompt_tokens": statistics.median(prompt_tokens[condition]),
            "total_tokens": statistics.median(total_tokens[condition]),
        }
        for condition in ("A", "B")
    }
    medians["B_vs_A_percent"] = {
        metric: round((medians["B"][metric] / medians["A"][metric] - 1) * 100, 2)
        for metric in ("prompt_tokens", "total_tokens")
    }
    protocol_audit = {
        "schema_version": "relation-utility-protocol-audit-1",
        "created_on": "2026-10-10",
        "status": "passed" if all(row["protocol_pass"] for row in audits) else "failed",
        "model_calls": 0,
        "judge_calls": 0,
        "relation_extraction_calls": 0,
        "production_queries": 0,
        "publication_calls": 0,
        "runs": audits,
        "paired_cost": medians,
        "cost_stop_threshold_percent": 20,
        "cost_stop_exceeded_on_prompt_tokens": medians["B_vs_A_percent"]["prompt_tokens"] > 20,
        "semantic_utility_requires_human_review": True,
    }
    (HERE / "protocol-audit.json").write_text(
        json.dumps(protocol_audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    blind_key: dict[str, dict[str, str]] = {}
    lines = [
        "# Issue 26 · 盲化配对人工裁定",
        "",
        "本页仅用于语义价值裁定；两个答案的 A/B 条件已隐藏。请不要打开 `blind-key.json`，直至五题全部裁定。",
        "程序已经核验：10 个输出均为合法 JSON；所有 claim 引用均来自该格实际交付 items；工具调用为 0。",
        "",
        "逐题先核对必需事实、限定、反向证据、禁止推断和可追溯性，再选择 `左更好 / 相同 / 右更好`。",
        "只有实质质量差异才判更好；篇幅更长不算增益。任何足以改变研报结论的禁止推断需单独勾出。",
        "",
    ]
    for question_id in ("Q1", "Q2", "Q3", "Q4", "Q5"):
        order = sorted(
            ("A", "B"),
            key=lambda condition: hashlib.sha256(
                f"{manifest['immutable_inputs']['utility_gold_sha256']}|blind-v1|{question_id}|{condition}".encode()
            ).hexdigest(),
        )
        blind_key[question_id] = {"左": order[0], "右": order[1]}
        lines.extend([f"## {question_id}", ""])
        for label, condition in zip(("左", "右"), order, strict=True):
            response = responses[f"{question_id}-{condition}"]
            lines.extend(
                [
                    f"### {label}",
                    "",
                    response["answer"],
                    "",
                    "Claims：",
                    "",
                    *[
                        f"- {claim['statement']}（{', '.join(claim['evidence_item_ids'])}）"
                        for claim in response["claims"]
                    ],
                    "",
                    "Limitations：",
                    "",
                    *[f"- {value}" for value in response["limitations"]],
                    "",
                ]
            )
        lines.extend(
            [
                "人工核对：",
                "",
                "- [ ] 左：必需事实齐全",
                "- [ ] 右：必需事实齐全",
                "- [ ] 左：限定/条件/口径齐全",
                "- [ ] 右：限定/条件/口径齐全",
                "- [ ] 左：反向证据正确（无要求则记不适用）",
                "- [ ] 右：反向证据正确（无要求则记不适用）",
                "- [ ] 左：存在禁止推断或不可追溯实质结论",
                "- [ ] 右：存在禁止推断或不可追溯实质结论",
                "- 配对裁定：`[ ] 左更好`　`[ ] 相同`　`[ ] 右更好`",
                "- 理由：",
                "",
            ]
        )
    lines.extend(
        [
            "## 总体签认",
            "",
            "- 签认人：`xyl`",
            "- 签认语：`签认 Issue 26 blinded paired review`",
            "- 日期：`2026-10-10`",
            "",
            "签认后才运行零调用解盲与最终裁决；不允许按条件身份回改本页裁定。",
        ]
    )
    (HERE / "blind-human-review.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (HERE / "blind-key.json").write_text(
        json.dumps(
            {
                "schema_version": "relation-utility-blind-key-1",
                "created_on": "2026-10-10",
                "do_not_open_before_human_review": True,
                "mapping": blind_key,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps(protocol_audit, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
