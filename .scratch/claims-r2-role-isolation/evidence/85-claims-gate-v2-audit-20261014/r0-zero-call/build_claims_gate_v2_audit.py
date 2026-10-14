"""Retro-audit of the Claims gate v2 draft: machine checks + feasibility ledger.

Zero model calls, read-only with respect to every frozen artifact (84/83 included).
The conformance checks live in ``tools/check_claims_gate.py`` (single implementation, so the
gate and its audit can never drift into two rule sets); this driver adds the feasibility
ledger and writes the audit record.

Usage:
    python build_claims_gate_v2_audit.py [--no-write] [--force]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]  # .scratch/claims-r2-role-isolation
REPO_ROOT = ROOT.parents[1]
sys.path.insert(0, str(REPO_ROOT))

from tools.check_claims_gate import Inputs, render_markdown, run_checks  # noqa: E402

AUDIT_ON = "2026-10-14"

GATE_V2 = (
    ROOT / "evidence/84-claims-gate-v2-draft-20261014/r0-zero-call/claims-gate-v2.proposed.json"
)
MANIFEST_V2 = (
    ROOT / "evidence/84-claims-gate-v2-draft-20261014/r0-zero-call/MANIFEST.json"
)
DRIVER_TOOL = REPO_ROOT / "tools/check_claims_gate.py"

# Feasibility ledger: every plan component, classified, with the evidence that classifies it.
# class ∈ {landed_now, needs_human_decision, needs_call_budget, not_executable_this_round}
FEASIBILITY: list[dict[str, Any]] = [
    {
        "id": "F1-分母口径（C1）",
        "component": "候选范围：材料范围（D1）还是 claims 角色范围（D2）",
        "klass": "needs_human_decision",
        "prerequisite": "U 具名裁定 + （若取 D2）把 45 条 in-scope 候选的分类改写为可核验记录",
        "evidence": "候选池与金标均冻结；契约 scope_rules 规定范围内输出必须裁定、不得自动排除",
        "blocking_now": True,
    },
    {
        "id": "F2-duplicate 单源化（C2）",
        "component": "契约文字公式（分母含 duplicate）vs 评分器实现（分母不含）",
        "klass": "needs_human_decision",
        "prerequisite": "U 选一个源；改另一处须具名并留差异记录",
        "evidence": "audit check `caliber-divergence:duplicate` 检出：56/110 vs 56/107",
        "blocking_now": True,
    },
    {
        "id": "F3-无载体字段读路径（C3）",
        "component": "attribution/perspective/source_stance/estimate_status 的 carrier/handling",
        "klass": "needs_human_decision",
        "prerequisite": "契约新版本（只增不删，沿 items 先例）；机制已在 v4.3 read_path 中存在但 applies_to 仅 material_items",
        "evidence": "11 字段实测：四字段 0/110 载体；契约 read_path.roles.claims.implemented_in_this_revision=false",
        "blocking_now": True,
    },
    {
        "id": "F4-用途分级（C4）",
        "component": "compare/calculate 由『零 reason 全或无』改为按受影响用途分级",
        "klass": "needs_human_decision",
        "prerequisite": "U 裁定（属改默认行为类）",
        "evidence": "45/56 条正确记录带 reason ⇒ 现规则下仅 11 条可算；reason 当硬门会使召回掉到 12/20",
        "blocking_now": True,
    },
    {
        "id": "F5-阈值双线（C5/C6）",
        "component": "目标线不动 + 新增放行线（功能线）与分源下限",
        "klass": "needs_human_decision",
        "prerequisite": "U 具名登记；禁止看到分数后再定值",
        "evidence": "容忍度表可复算：0.60⇒再容忍 4 条 FP；D2 上限 0.630<0.80",
        "blocking_now": True,
    },
    {
        "id": "F6-重跑产出新池",
        "component": "在冻结金标与同一口径下用新配置重跑 claims 抽取",
        "klass": "needs_call_budget",
        "prerequisite": "U 明确授权调用额度与计划冻结",
        "evidence": "冻结池上 0.80 不可达（D2 分子上限即 0.630）；这是唯一能让目标线可达的动作",
        "blocking_now": False,
    },
    {
        "id": "F7-一致性校验器 + 复算回归",
        "component": "哨兵恒等、口径可复算、分歧检出（工具 + 常驻测试）",
        "klass": "landed_now",
        "prerequisite": "无（零调用、只读、不改默认行为）",
        "evidence": "tools/check_claims_gate.py；27 项审核，阻塞失败 0",
        "blocking_now": False,
    },
    {
        "id": "F8-契约读取器按角色参数化",
        "component": "load_contract_gate_requirements 支持 claims 角色（role_scope/target_total/哨兵子集）",
        "klass": "needs_human_decision",
        "prerequisite": "claim 专属契约字段（target_total=20、NT-C 哨兵子集）须先由 C1/C3 定值并进契约新版本",
        "evidence": "structured_scoring.py:435-525 硬编码 role_scope=MATERIAL_ITEMS 且要求恰 11 条 NT-I*；"
        "tests/test_corpus_contract_gate.py:177-217 断言该形态",
        "blocking_now": True,
    },
    {
        "id": "F9-生产侧接缝（角色边界/坐标绑定/去冗余）",
        "component": "claims 只产指标断言、坐标绑定、同坐标不重复渲染",
        "klass": "not_executable_this_round",
        "prerequisite": "需要新池（F6）才能体现效果；在冻结池上只能做反事实上界",
        "evidence": "D2 上限 0.630、D3 召回 12/20 ⇒ 反事实口径无法同时保住两轴",
        "blocking_now": False,
    },
]

UNCOVERED = [
    "本轮未核验：`.scratch` 下 evidence/01–82 的全部内容（未逐件复核）",
    "本轮未核验：benchmarks/、workflows/、plugins/ 除 structured_scoring.py 与 claims_* 之外的行为",
    "本轮未核验：冻结金标 20 条 claims 记录的语义正确性（沿用已签 Issue 29/30 结论，未重做审计）",
    "本轮未执行：任何模型调用、生产 PG 访问、发布、query/delivery/context_use、M_main 消费",
    "本轮未裁定：C1–C6 六格判据（全部保持 pending_human_decision）",
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def render_feasibility() -> str:
    lines = [
        "",
        "## 可行性分层（谓词：组件 × 类别 × 是否阻塞当前签认）",
        "",
        "类别 ∈ {landed_now, needs_human_decision, needs_call_budget, not_executable_this_round}。",
        "",
        "| 编号 | 组件 | 类别 | 前置 | 依据 | 阻塞当前 |",
        "|---|---|---|---|---|---|",
    ]
    for item in FEASIBILITY:
        lines.append(
            f"| {item['id']} | {item['component']} | **{item['klass']}** | {item['prerequisite']} "
            f"| {item['evidence']} | {'是' if item['blocking_now'] else '否'} |"
        )
    counts: dict[str, int] = {}
    for item in FEASIBILITY:
        counts[item["klass"]] = counts.get(item["klass"], 0) + 1
    lines += ["", f"计数：{json.dumps(counts, ensure_ascii=False)}", ""]
    lines += ["## 未覆盖范围（显式声明）", ""]
    lines += [f"- {text}" for text in UNCOVERED]
    lines += [
        "",
        "## 结论",
        "",
        "- 方案作为**口径与登记**方案可行：全部数字可由冻结输入复算，哨兵与契约恒等，分歧项可检出。",
        "- 方案作为**不改判定即可过目标线**不可行：D2 分子上限 0.630 < 0.80，且该上限不依赖任何未定判据。",
        "- 本轮已落地的只有 F7（校验器 + 复算回归）；F1–F5、F8 卡在 U 的六格判据，F6 卡在调用额度，"
        "F9 在候选冻结下无法执行。",
        "",
    ]
    return "\n".join(lines) + "\n"


def build() -> dict[str, Any]:
    inputs = Inputs()
    checks = run_checks(inputs)
    blocking_failures = [
        check.check_id for check in checks if check.blocking and check.verdict == "fail"
    ]
    report = {
        "schema_version": "claims-gate-v2-retro-audit-1",
        "created_on": AUDIT_ON,
        "zero_model_calls": True,
        "auditor": "agent",
        "reviewer": None,
        "signed_on": None,
        "subject": {
            "gate": str(GATE_V2.relative_to(ROOT)),
            "gate_sha256": sha256(GATE_V2),
            "manifest": str(MANIFEST_V2.relative_to(ROOT)),
            "manifest_sha256": sha256(MANIFEST_V2),
        },
        "checker": {
            "path": str(DRIVER_TOOL.relative_to(REPO_ROOT)),
            "sha256": sha256(DRIVER_TOOL),
            "check_count": len(checks),
        },
        "predicates": {
            "layers": sorted({check.layer for check in checks}),
            "kinds": sorted({check.kind for check in checks}),
            "blocking_definition": "该项失败会使门不可签认",
        },
        "checks": [asdict(check) for check in checks],
        "blocking_failures": blocking_failures,
        "divergences": [check.check_id for check in checks if check.verdict == "divergence"],
        "notes": [check.check_id for check in checks if check.verdict == "note"],
        "verdict": "pass" if not blocking_failures else "fail",
        "feasibility": FEASIBILITY,
        "uncovered_scope": UNCOVERED,
    }
    manifest = {
        "schema_version": "claims-gate-v2-audit-manifest-1",
        "status": "draft",
        "created_on": AUDIT_ON,
        "model_calls": 0,
        "production_pg_access": 0,
        "inputs": {
            "claims_gate_v2_proposed": sha256(GATE_V2),
            "claims_gate_v2_manifest": sha256(MANIFEST_V2),
            "checker_tool": sha256(DRIVER_TOOL),
            **{name: sha256(path) for name, path in _audited_inputs().items()},
        },
        "outputs": {},
        "does_not_touch": [str(GATE_V2.relative_to(ROOT)), str(MANIFEST_V2.relative_to(ROOT))],
    }
    return {"report": report, "manifest": manifest}


def _audited_inputs() -> dict[str, Path]:
    inputs = Inputs()
    return {
        "p1r5_candidate_adjudications_signed": inputs.pool,
        "scoring_contract_v4.3": inputs.contract,
        "frozen_gold": inputs.gold,
        "claims_gate_v1_proposed": inputs.v1_gate,
        "claims_gate_v1_manifest": inputs.v1_manifest,
        "claims_coverage_v1": inputs.v1_coverage,
        "items_gate_v3": REPO_ROOT
        / ".scratch/claims-r2-role-isolation/evidence/75-r2-signed-20261013/r0-zero-call/gate-v3.json",
        "claims_gate_v1_signoff_md": inputs.v1_gate.parent / "claims-gate-v1-signoff.md",
    }


AUDIT_HEAD = """> 对象：84 号 claims 门 v2 草案。本件是对它的机器可核验回溯审核 + 可行性分层。
> 零模型调用；不修改 84/83/P1R5/门 v3/契约 v4.3 的任何字节。
> 审核谓词：按【层级 × 性质 × 是否阻塞】计数；**阻塞** = 该项失败会使门不可签认；
> 口径与记账分歧一律记为 `divergence`（检出并登记，不代替人裁）。

"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-write", action="store_true", help="只打印摘要，不写文件")
    parser.add_argument("--force", action="store_true", help="允许覆盖本目录内已存在的输出")
    args = parser.parse_args()

    result = build()
    report = result["report"]
    manifest = result["manifest"]
    md = AUDIT_HEAD + render_markdown(
        [c for c in run_checks(Inputs())]
    ) + render_feasibility()
    outputs = {
        "audit-report.json": (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode(
            "utf-8"
        ),
        "audit-report.md": md.encode("utf-8"),
    }
    manifest["outputs"] = {name: hashlib.sha256(data).hexdigest() for name, data in outputs.items()}
    outputs["MANIFEST.json"] = (
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")

    if args.no_write:
        print(
            json.dumps(
                {
                    "verdict": report["verdict"],
                    "blocking_failures": report["blocking_failures"],
                    "divergences": report["divergences"],
                    "notes": report["notes"],
                    "check_count": report["checker"]["check_count"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        print(f"[no-write] {len(outputs)} outputs computed; nothing written.")
        return 0

    existing = [name for name in outputs if (HERE / name).exists()]
    if existing and not args.force:
        raise SystemExit(f"refusing to overwrite existing outputs {existing}; use --force")
    for name, data in outputs.items():
        (HERE / name).write_bytes(data)
    print(f"wrote {len(outputs)} files to {HERE}")
    print(json.dumps(manifest["outputs"], ensure_ascii=False, indent=2))
    return 0 if report["verdict"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
