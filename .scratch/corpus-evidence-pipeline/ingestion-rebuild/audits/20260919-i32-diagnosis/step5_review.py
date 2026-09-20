"""Step 5：I3-2 **针对性复核** + 最终差异包 + 阶段签认模板。

复核范围严格按诊断稿：**只审** ①新增派生关系 ②旧基线范围 ③初始版本；复用既有审批（不重审补料/审批链）。
复核方法：**不复用产物自身的自校验**，而是用独立代码路径重新推导/比对（同源 helper 仅用于 locator 令牌），
并逐条给出可复现命令。

产出（均未入绑定，供 Step 6 冻结）：
- `step5-review.md` / `step5-review.json`
- `step5-diff-pack.md`（自 r26 起的改动清单 + 绑定状态 + 复现命令）
- `signoff-record-i3-2.md` / `.json`（**待 U 签认**，含签认声明与不含范围）
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1]
ROOT = HERE.parents[4]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FREEZES = BASE / "freezes"
GOLD = BASE / "query-gold-frozen.jsonl"
SOURCE_GOLD = BASE / "source-gold-frozen.jsonl"
PROJECTION = BASE / "i3-2/evidence-targets-approved.json"
DECISIONS = BASE / "i3-2/evidence-targets-decisions.json"
SCORING_INPUT = BASE / "i3-2/query-gold-scoring-v1.jsonl"
SCORING_MANIFEST = BASE / "i3-2/scoring-input-manifest.json"
SCORING_TOOL = BASE / "i3s2_scoring_input.py"
P2 = BASE / "audits/20260918-i32-remaining-inventory/p2/policy-and-lists-confirmation.json"
P3 = BASE / "audits/20260918-i32-remaining-inventory/p3/baseline-mapping-reconciliation.json"
P4 = BASE / "audits/20260918-i32-remaining-inventory/p4/experiment-initial-version.json"
BASELINE_MANIFEST = HERE / "baseline-case-manifest.json"
MAPPING = HERE / "legacy-anchor-mapping.json"
GUARD = BASE / "guards/i3.json"
DOC_KIND_CSV = ROOT / "data/corpus/.audit/c1_full84_doc_kind_review_20260912.csv"
COMPLETION_GATE = FREEZES / "validate_i3_2_completion.py"
SIGNOFF_JSON = HERE / "signoff-record-i3-2.json"

findings: list[dict] = []


def resolve_path(raw: str) -> Path:
    """路径字段一律按仓库根解析；历史字段可能相对 ingestion-rebuild，退回尝试。"""

    candidate = ROOT / raw
    return candidate if candidate.exists() else BASE / raw


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def now() -> str:
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader, path
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def add(area: str, item: str, status: str, evidence: list[str]) -> None:
    findings.append({"area": area, "item": item, "status": status, "evidence": evidence})


def merged_binding() -> dict[str, str]:
    current: dict[str, str] = {}
    def _order(path: Path) -> tuple:
        parts = path.stem.split("-")
        return (parts[0], int(parts[1][1:]) if parts[1][1:].isdigit() else 0)

    for path in sorted(FREEZES.glob("i0c-r*.json"), key=_order) + sorted(
        FREEZES.glob("i1-*.json"), key=_order
    ):
        data = json.loads(path.read_text(encoding="utf-8"))
        for items in (data.get("binding") or {}).values():
            for rel, expected in items.items():
                current.pop(rel, None)
                current[rel] = expected
    return current


# ────────────────────────────────────────── ① 新增派生关系


def review_derivation() -> None:
    gold = load_jsonl(GOLD)
    source_gold = load_jsonl(SOURCE_GOLD)
    projection = json.loads(PROJECTION.read_text(encoding="utf-8"))
    derivative = load_jsonl(SCORING_INPUT)
    applier = load_module(BASE / "i3s2_apply_decisions.py", "applier_step5")
    slot_by_id = {str(slot["gold_id"]): slot for slot in source_gold}
    proj_by_id = {str(q["query_id"]): q for q in projection["questions"]}
    deriv_by_id = {str(r["query_id"]): r for r in derivative}

    problems: list[str] = []
    keys = ("target_id", "quote", "locator", "source_id")
    for record in gold:
        qid = str(record["query_id"])
        got = deriv_by_id.get(qid)
        if got is None:
            problems.append(f"{qid}: 派生件缺题")
            continue
        if str(record.get("answer_existence")) == "answerable":
            want = [{k: t[k] for k in keys} for t in proj_by_id[qid]["approved_required"]]
            have = [{k: t[k] for k in keys} for t in got.get("evidence_targets") or []]
            if want != have:
                problems.append(f"{qid}: 必需目标与投影不一致")
            want_s = [{k: t[k] for k in keys} for t in proj_by_id[qid]["supplementary"]]
            have_s = [{k: t[k] for k in keys} for t in got.get("supplementary_evidence_targets") or []]
            if want_s != have_s:
                problems.append(f"{qid}: 补充目标与投影不一致")
            if set(t["target_id"] for t in have) & set(t["target_id"] for t in have_s):
                problems.append(f"{qid}: 补充混入必需")
        elif got.get("evidence_targets") or got.get("supplementary_evidence_targets"):
            problems.append(f"{qid}: 负例题携带目标")
    add(
        "①派生关系",
        "派生件 = 批准投影的确定性材料化（独立重推，未复用派生器自校验）",
        "pass" if not problems else "fail",
        problems[:6] or [f"30 题逐题比对一致；必需 {sum(len(r.get('evidence_targets') or []) for r in derivative)} 条、"
                         f"补充 {sum(len(r.get('supplementary_evidence_targets') or []) for r in derivative)} 条"],
    )

    # 回链：每条 target 的 source_id / quote / locator 必须能在 source-gold 找到
    bad: list[str] = []
    for record in derivative:
        for target in (record.get("evidence_targets") or []) + (
            record.get("supplementary_evidence_targets") or []
        ):
            basis = target.get("basis") or {}
            slot = slot_by_id.get(str(basis.get("gold_id")))
            item = dict(applier.split_items(slot)).get(basis.get("item_index")) if slot else None
            if not isinstance(item, dict):
                bad.append(f"{record['query_id']}#{target['target_id']}: 槽位/条目不存在")
                continue
            if str(target["source_id"]) != str(slot["source_id"]):
                bad.append(f"{record['query_id']}#{target['target_id']}: source_id 不符")
            if str(target["quote"]) != str(item.get("quote")):
                bad.append(f"{record['query_id']}#{target['target_id']}: quote 不符")
            if list(target.get("locator") or []) != list(applier._locator_tokens(slot, item) or []):
                bad.append(f"{record['query_id']}#{target['target_id']}: locator 不符")
    add("①派生关系", "条目级回链 source-gold（source_id/quote/locator）", "pass" if not bad else "fail", bad[:6] or ["全部回链通过"])

    # 唯一读入口
    tool = load_module(SCORING_TOOL, "scoring_tool_step5")
    manifest = json.loads(SCORING_MANIFEST.read_text(encoding="utf-8"))
    try:
        loaded = tool.load_scoring_input(SCORING_MANIFEST)
        ok = digest(SCORING_INPUT) == manifest["scoring_input"]["sha256"] and len(loaded) == len(derivative)
    except Exception as exc:  # noqa: BLE001
        ok = False
        add("①派生关系", "唯一读入口", "fail", [f"{type(exc).__name__}: {exc}"])
        return
    add(
        "①派生关系",
        "唯一读入口按 manifest 路径 + 哈希读取（不依赖默认路径/最新文件）",
        "pass" if ok else "fail",
        [f"manifest.status={manifest.get('status')}；scoring_input={manifest['scoring_input']['path']}"],
    )
    add(
        "①派生关系",
        "审批原件未被派生改动",
        "pass" if digest(GOLD) == "6f6c5a25d55be2b58c7f7ae65152b9b58c8e876aeb60101d13c08c9ccca7b39f" else "fail",
        [f"query-gold-frozen.jsonl sha256={digest(GOLD)[:12]}…（r26 起未变）"],
    )


# ────────────────────────────────────────── ② 旧基线范围


def review_baseline() -> None:
    manifest = json.loads(BASELINE_MANIFEST.read_text(encoding="utf-8"))
    mapping = json.loads(MAPPING.read_text(encoding="utf-8"))
    categories = {c["categories"][0]: c for c in manifest["categories"]}

    counts = {
        "legacy_retrieval_golden": len(categories["legacy_retrieval_golden"]["cases"]),
        "financial_controlled_recalc_57": len(categories["financial_controlled_recalc_57"]["cases"]),
        "formula_7": len(categories["formula_7"]["cases"]),
        "prose_numbers_3": len(categories["prose_numbers_3"]["cases"]),
        "macro_legacy_fields_0_of_3": len(categories["macro_legacy_fields_0_of_3"]["cases"]),
    }
    expected = {
        "legacy_retrieval_golden": 19,
        "financial_controlled_recalc_57": 57,
        "formula_7": 7,
        "prose_numbers_3": 2,
        "macro_legacy_fields_0_of_3": 2,
    }
    add(
        "②旧基线范围",
        "用例计数与 U 圈定范围一致（19/57/7/2/2，O6 留出排除）",
        "pass" if counts == expected else "fail",
        [f"实测 {json.dumps(counts, ensure_ascii=False)}"],
    )
    blocked = [b for b in manifest.get("blocked_items") or [] if str(b.get("status", "")).startswith("blocked")]
    add("②旧基线范围", "无残留 blocked 项", "pass" if not blocked else "fail", [f"blocked={len(blocked)}"])

    # 57 格拆分
    split: dict[str, int] = {}
    for case in categories["financial_controlled_recalc_57"]["cases"]:
        split[str(case["sample"])] = split.get(str(case["sample"]), 0) + 1
    add(
        "②旧基线范围",
        "57 格拆分 = maotai 32 / guangli 15 / guosen 10（含 holdout 标记）",
        "pass" if split == {"maotai_financial_tables": 32, "guangli_financial_table": 15, "guosen_maotai_holdout": 10} else "fail",
        [json.dumps(split, ensure_ascii=False)],
    )

    # 公式输入
    inputs = {c["case_id"]: c.get("input_metrics") for c in categories["formula_7"]["cases"]}
    add(
        "②旧基线范围",
        "7 条公式均有输入指标声明（来自 derivation.py）",
        "pass" if all(inputs.values()) and len(inputs) == 7 else "fail",
        [json.dumps(inputs, ensure_ascii=False)[:220]],
    )

    # 锚点映射
    anchors = [a for q in mapping["questions"] for a in q["anchors"]]
    unresolved = [a for a in anchors if len(a["candidates"]) != 1]
    paths_bad = [a for a in anchors if not (ROOT / str(a["candidates"][0]["source_path"])).is_file()]
    annotated = set()
    for line in SOURCE_GOLD.read_text(encoding="utf-8").splitlines():
        if line.strip():
            annotated.add(json.loads(line)["source_id"])
    same_source = sorted({str(a["candidates"][0]["doc_id"]) for a in anchors} & annotated)
    add(
        "②旧基线范围",
        "19 题锚点映射唯一命中 + 指向文件存在",
        "pass" if not unresolved and not paths_bad else "fail",
        [
            f"锚点 {len(anchors)} 个；非唯一 {len(unresolved)}；source_path 缺失 {len(paths_bad)}",
            f"与已标注 source-gold 同源的 doc_id {len(same_source)} 个：{same_source}",
            f"confirmed=false 待人工复核：{sum(1 for a in anchors if not a['confirmed'])} 个锚点",
        ],
    )

    # doc_kind 权威版本
    decision = json.loads((HERE / "decision-old-doc-kind-review-authority-20260919.json").read_text(encoding="utf-8"))
    declared = json.dumps(decision)
    add(
        "②旧基线范围",
        "doc_kind 导出权威版本：决定件哈希与现文件一致",
        "pass" if str(decision.get("sha256") or decision.get("asset_sha256") or "")== digest(DOC_KIND_CSV)
        or str(digest(DOC_KIND_CSV))[:12] in declared else "fail",
        [f"CSV sha256={digest(DOC_KIND_CSV)[:12]}…；决定件含该哈希={'是' if digest(DOC_KIND_CSV) in declared else '否'}"],
    )

    # 留出一致性
    guard = json.loads(GUARD.read_text(encoding="utf-8"))
    roots = [p.split("/")[-1] for p in guard["sources"]["forbidden_roots"]]
    prose_holdout = json.loads(
        (ROOT / ".scratch/corpus-evidence-pipeline/prose_holdout_manifest.json").read_text(encoding="utf-8")
    )
    prose_pattern = str((prose_holdout["samples"][0]).get("pattern") or "").lstrip("*")
    covered = [r for r in roots if prose_pattern and prose_pattern in r]
    add(
        "②旧基线范围",
        "留出隔离：guard 4 根覆盖旧基线涉及来源；prose 留出（天风）是否覆盖",
        "observe" if not covered else "pass",
        [
            f"forbidden_roots={len(roots)} 个：{[r[:28] for r in roots]}",
            f"prose_holdout_manifest pattern={prose_pattern} → guard 覆盖={'是' if covered else '**否（待定项）**'}",
            f"文件在磁盘={any(prose_pattern in f for f in __import__('os').listdir(ROOT / 'data/corpus'))}",
        ],
    )


# ────────────────────────────────────────── ③ 初始版本


def review_initial() -> None:
    p4 = json.loads(P4.read_text(encoding="utf-8"))
    components = p4["components"]
    lineage_checks = {
        "scorer": resolve_path(components["scorer"]["path"]),
        "source_gold": resolve_path(components["source_gold"]["path"]),
        "approved_projection": resolve_path(components["approved_projection"]["path"]),
        "decisions": resolve_path(components["decisions"]["path"]),
        "policy": resolve_path(components["policy"]["confirmation"]),
    }
    bad = []
    for name, path in lineage_checks.items():
        declared = str(components[name]["sha256"])
        if not path.is_file() or digest(path) != declared:
            bad.append(f"{name}: 声明 {declared[:12]}… ≠ 现况")
    scoring_declared = str(components["query_gold"]["scoring_input_sha256"])
    if digest(SCORING_INPUT) != scoring_declared:
        bad.append("query_gold.scoring_input_sha256 与现文件不符")
    add(
        "③初始版本",
        "P4 lineage 哈希逐项可复算（评分器/金标/投影/裁决件/阈值确认单/评分输入）",
        "pass" if not bad else "fail",
        bad or [f"6 项 lineage 全部与现文件一致；评分输入 sha256={scoring_declared[:12]}…"],
    )

    p2 = json.loads(P2.read_text(encoding="utf-8"))
    policy_values = p2["items"][0]["values"]
    if components["policy"]["values"] != policy_values:
        add("③初始版本", "P4 policy 与 P2 一致", "fail", ["取值不一致"])
    else:
        add("③初始版本", "P4 policy 与 P2 一致", "pass", [json.dumps(policy_values, ensure_ascii=False)])

    lists_ok = (
        components["lists"]["critical"]["count"] == p2["items"][1]["critical_count"]
        and components["lists"]["negatives"]["count"] == p2["items"][2]["negative_count"]
    )
    add("③初始版本", "P4 关键题/负例计数与 P2 一致", "pass" if lists_ok else "fail",
        [f"critical={components['lists']['critical']['count']}；negatives={components['lists']['negatives']['count']}"])

    execution = components.get("execution") or {}
    add(
        "③初始版本",
        "执行段完整且未实现入口显式登记（不写成已可执行）",
        "pass" if execution and execution.get("unimplemented_entrypoints") else "fail",
        [f"status={execution.get('status')}；未实现入口={len(execution.get('unimplemented_entrypoints') or [])} 项；"
         f"运行时显式 policy={'有' if execution.get('runtime_policy') else '缺'}"],
    )

    binding = merged_binding()
    unbound = [
        label
        for label, path in {
            "P4 清单": P4,
            "评分输入": SCORING_INPUT,
            "评分输入清单": SCORING_MANIFEST,
            "旧基线用例清单": BASELINE_MANIFEST,
            "锚点映射": MAPPING,
            "阶段完成门": COMPLETION_GATE,
        }.items()
        if binding.get(str(path.relative_to(ROOT))) != digest(path)
    ]
    add("③初始版本", "初始版本组成资产均已入链", "pass" if not unbound else "fail", [f"未入链：{unbound or '无'}"])


def review_paths() -> None:
    """通用检查：P2/P3/P4 里凡是"路径样"字符串都必须能从仓库根解析到真实文件。"""

    bad: list[str] = []
    pattern = re.compile(r"^[\w./\-]+\.(json|jsonl|md|py|csv)$")
    for label, path in (("P2", P2), ("P3", P3), ("P4", P4)):
        data = json.loads(path.read_text(encoding="utf-8"))
        stack = [data]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                stack.extend(node.values())
            elif isinstance(node, list):
                stack.extend(node)
            elif isinstance(node, str) and pattern.match(node) and "/" in node:
                if not (ROOT / node).is_file():
                    bad.append(f"{label}: {node}")
    add(
        "③初始版本",
        "P2/P3/P4 内的路径字段均可从仓库根解析",
        "pass" if not bad else "fail",
        bad[:6] or ["全部可解析"],
    )


def diff_pack() -> dict:
    binding = merged_binding()
    groups: dict[str, list[str]] = {}
    for snapshot in ("i0c-r27", "i0c-r28"):
        data = json.loads((FREEZES / f"{snapshot}.json").read_text(encoding="utf-8"))
        for group, items in (data.get("binding") or {}).items():
            for rel in items:
                groups.setdefault(f"{snapshot}:{group}", []).append(rel)
    new_files: list[str] = []
    for directory in (HERE, BASE / "audits/20260918-i32-remaining-inventory", BASE / "i3-2"):
        for path in sorted(directory.rglob("*")):
            if path.is_file() and path.suffix in {".md", ".json", ".jsonl", ".py"}:
                rel = str(path.relative_to(ROOT))
                if rel not in binding:
                    new_files.append(rel)
    return {"bound_groups": groups, "unbound_files": new_files}


def run(command: list[str]) -> dict:
    proc = subprocess.run(command, capture_output=True, text=True, cwd=str(ROOT), check=False)
    return {"exit": proc.returncode, "tail": (proc.stdout or "").strip().splitlines()[-1:]}


def write_artifacts(review: dict, diff: dict, write_signoff: bool = True) -> None:
    failed = [f for f in findings if f["status"] == "fail"]
    observed = [f for f in findings if f["status"] == "observe"]

    lines = ["# Step 5 针对性复核（只审新增派生关系／旧基线范围／初始版本）", ""]
    lines.append(f"- 复核时间：{review['generated_at']}；复核对象：i0c-r28（及 r27 的旧基线冻结）")
    lines.append(f"- 结论：**{'通过' if not failed else '有 ' + str(len(failed)) + ' 项未通过'}**"
                 + (f"；另有 {len(observed)} 项观察项" if observed else ""))
    lines.append("")
    lines.append("| 区域 | 复核项 | 结论 | 证据 |")
    lines.append("|---|---|---|---|")
    for finding in findings:
        evidence = "<br>".join(str(e) for e in finding["evidence"])
        lines.append(f"| {finding['area']} | {finding['item']} | **{finding['status']}** | {evidence} |")
    lines.append("")
    lines.append("## 复核用可复现命令")
    lines.append("")
    for command in review["commands"]:
        lines.append(f"- `{command}` → exit {review['command_results'][command]['exit']}")
    lines.append("")
    lines.append("## 未入链文件（Step 6 待绑）")
    lines.append("")
    for rel in diff["unbound_files"]:
        lines.append(f"- `{rel}`")
    (HERE / "step5-review.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    diff_lines = ["# 最终差异包（自 r26 起）", ""]
    diff_lines.append(f"生成：{review['generated_at']}；结论与复核见 [step5-review.md](step5-review.md)。")
    diff_lines.append("")
    for snapshot, paths in diff["bound_groups"].items():
        diff_lines.append(f"## {snapshot}（{len(paths)} 项，已入链）")
        diff_lines.append("")
        for rel in sorted(paths):
            diff_lines.append(f"- `{rel}`")
        diff_lines.append("")
    diff_lines.append(f"## 未入链（{len(diff['unbound_files'])} 项，Step 6 待绑）")
    diff_lines.append("")
    for rel in diff["unbound_files"]:
        diff_lines.append(f"- `{rel}`")
    (HERE / "step5-diff-pack.md").write_text("\n".join(diff_lines) + "\n", encoding="utf-8")

    signoff = {
        "artifact": "i3-2-stage-signoff-record",
        "status": "pending_user_signoff",
        "scope": "I3-2 阶段签认（预期与评分器冻结 + 派生评分输入 + 旧基线身份与范围 + 初始实验版本）",
        "prepared_at": review["generated_at"],
        "review_result": "通过" if not failed else f"{len(failed)} 项未通过",
        "claim_upon_signoff": [
            "source/query gold 与批准投影已冻结（r26），正式评分输入已派生并与其一致（r28）",
            "7 类旧基线的身份/范围/预期经 U 圈定并冻结（r27），19 题旧锚点→新 source 身份映射唯一命中（r28）",
            "阈值/关键题/负例取值已确认并冻结（P2 + r28）",
            "评分器与试验初始版本已冻结（P4 + r28），执行器按唯一评分输入读取",
        ],
        "not_covered": [
            "I3-5 真实非回归（旧检索/财务/公式/客户表/正文/宏观）未执行",
            "I3-1 三类开发 E2E 未执行；I3-5·I3-7 真实答案语义验收未执行（需预算授权）",
            "20 条人工同义映射 warning 与 macro-004 机器 blocked 覆盖保留为语义审计风险",
            "19 题锚点映射 confirmed=false 待人工复核（本记录不替代该复核）",
            "prose 留出（天风 5520fab6）未纳入 guards/i3.json forbidden_roots（待定项）",
            "M5 F3（validate_i1_freeze.py 13 项失配）单列跟踪",
        ],
        "signature_fields": {
            "reviewer": None,
            "reviewed_at": None,
            "decision": None,
            "note": "签认由具名人工填写；Agent 不代签",
        },
    }
    if write_signoff:
        (HERE / "signoff-record-i3-2.json").write_text(
            json.dumps(signoff, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    md = ["# I3-2 阶段签认记录（**待 U 签认**）", ""]
    md.append(f"- 状态：**{signoff['status']}**；准备时间：{signoff['prepared_at']}；复核结论：{signoff['review_result']}")
    md.append(f"- 签认范围：{signoff['scope']}")
    md.append("")
    md.append("## 签认即确认（claim）")
    md.append("")
    for item in signoff["claim_upon_signoff"]:
        md.append(f"- {item}")
    md.append("")
    md.append("## 明确不含（not covered）")
    md.append("")
    for item in signoff["not_covered"]:
        md.append(f"- {item}")
    md.append("")
    md.append("## 签署栏")
    md.append("")
    md.append("| 字段 | 值 |")
    md.append("|---|---|")
    for key, value in signoff["signature_fields"].items():
        md.append(f"| {key} | {value if value is not None else '（待填）'} |")
    if write_signoff:
        (HERE / "signoff-record-i3-2.md").write_text("\n".join(md) + "\n", encoding="utf-8")


def main() -> int:
    review_derivation()
    review_baseline()
    review_initial()
    review_paths()
    diff = diff_pack()
    commands = {
        "冻结链": [sys.executable, str(FREEZES / "validate_i0c_freeze.py")],
        "阶段完成门": [sys.executable, str(COMPLETION_GATE)],
        "派生件自校验": [sys.executable, str(SCORING_TOOL), "--check"],
    }
    results = {name: run(cmd) for name, cmd in commands.items()}
    review = {
        "artifact": "i3-2-step5-review",
        "generated_at": now(),
        "findings": findings,
        "failed": [f["item"] for f in findings if f["status"] == "fail"],
        "observed": [f["item"] for f in findings if f["status"] == "observe"],
        "commands": list(commands),
        "command_results": results,
    }
    no_write = "--no-write" in sys.argv
    # 已签记录不重写（防签名被覆盖）：只跳过签认文件，复核产物仍按需刷新
    signoff_signed = False
    if SIGNOFF_JSON.is_file():
        signed = (json.loads(SIGNOFF_JSON.read_text(encoding="utf-8")).get("signature_fields") or {})
        signoff_signed = bool(signed.get("reviewer") and signed.get("decision"))
    if not no_write:
        (HERE / "step5-review.json").write_text(
            json.dumps({**review, "diff_pack": diff}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        write_artifacts(review, diff, write_signoff=not signoff_signed)
    print(json.dumps({
        "failed": review["failed"],
        "observed": review["observed"],
        "commands": results,
        "unbound_files": len(diff["unbound_files"]),
    }, ensure_ascii=False, indent=2))
    return 0 if not review["failed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
