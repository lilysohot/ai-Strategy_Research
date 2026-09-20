"""I3-2 **阶段完成门**：逐项输出 pass / fail / not_run / not_applicable（不分小分，只报事实）。

对齐 `audits/20260919-i32-diagnosis/diagnosis-and-remediation.md` 卡点 4 与
`docs/plan/corpus-ingestion-rebuild-tasks.md:321` 的 I3-2 定义：
确认 source/query gold、旧基线映射、各类阈值/关键题/负例，冻结评分器与试验初始版本。

只读取既有产物与冻结链，不重算指标、不新增评分算法；零模型、零数据库。

用法::

    env -u PYTHONPATH uv run python \\
      .scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/validate_i3_2_completion.py
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent  # ingestion-rebuild
ROOT = BASE.parents[2]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

AUDIT = BASE / "audits/20260919-i32-diagnosis"
INVENTORY = BASE / "audits/20260918-i32-remaining-inventory"
FREEZES = BASE / "freezes"
GOLD = BASE / "query-gold-frozen.jsonl"
SOURCE_GOLD = BASE / "source-gold-frozen.jsonl"
CANDIDATES = BASE / "i3-2/evidence-targets-candidates.json"
DECISIONS = BASE / "i3-2/evidence-targets-decisions.json"
PROJECTION = BASE / "i3-2/evidence-targets-approved.json"
SCORING_INPUT = BASE / "i3-2/query-gold-scoring-v1.jsonl"
SCORING_MANIFEST = BASE / "i3-2/scoring-input-manifest.json"
SCORING_TOOL = BASE / "i3s2_scoring_input.py"
P2 = INVENTORY / "p2/policy-and-lists-confirmation.json"
P3 = INVENTORY / "p3/baseline-mapping-reconciliation.json"
P4 = INVENTORY / "p4/experiment-initial-version.json"
BASELINE_MANIFEST = AUDIT / "baseline-case-manifest.json"
GUARD = BASE / "guards/i3.json"
SCORER = ROOT / "plugins/corpus/scoring.py"
PROSE_HOLDOUT = ROOT / ".scratch/corpus-evidence-pipeline/prose_holdout_manifest.json"
CLOSURE_JSON_REL = ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i32-diagnosis/i3-2-closure.json"
CLOSURE = AUDIT / "i3-2-closure.json"
MAPPING = AUDIT / "legacy-anchor-mapping.json"
SIGNOFF_JSON = AUDIT / "signoff-record-i3-2.json"

results: list[dict] = []


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader, path
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def merged_binding() -> dict[str, str]:
    """复刻验证器的『最新修订优先』合并语义，得到 i0c-current 的路径 → 哈希。"""

    current: dict[str, str] = {}
    for path in sorted(FREEZES.glob("i0c-r*.json")) + sorted(FREEZES.glob("i1-*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for items in (data.get("binding") or {}).values():
            for rel, expected in items.items():
                current.pop(rel, None)
                current[rel] = expected
    return current


def record(item: str, status: str, evidence: list[str]) -> None:
    results.append({"item": item, "status": status, "evidence": evidence})


def check_upstream_approval() -> None:
    applier = load_module(BASE / "i3s2_apply_decisions.py", "i3s2_applier_gate_completion")
    payload = json.loads(CANDIDATES.read_text(encoding="utf-8"))
    report = applier.evaluate(
        payload,
        load_jsonl(GOLD),
        load_jsonl(SOURCE_GOLD),
        json.loads(DECISIONS.read_text(encoding="utf-8")),
    )
    record(
        "上游审批有效（建议件 → 批准投影 → 完整性门）",
        "pass" if report["ready"] else "fail",
        [
            f"ready={report['ready']}；blockers={len(report.get('blockers') or [])}；"
            f"warnings={len(report.get('warnings') or [])}",
            f"approval-report 与 decisions 绑定：based_on={json.dumps(report.get('based_on') or {}, ensure_ascii=False)[:80]}",
        ],
    )


def check_scoring_input() -> None:
    if not (SCORING_INPUT.is_file() and SCORING_MANIFEST.is_file() and SCORING_TOOL.is_file()):
        record("正式评分输入派生件一致", "fail", ["派生件/清单/工具缺失"])
        return
    tool = load_module(SCORING_TOOL, "i3s2_scoring_input_gate")
    applier = load_module(BASE / "i3s2_apply_decisions.py", "i3s2_applier_gate_scoring")
    errors = tool.validate(
        load_jsonl(SCORING_INPUT),
        load_jsonl(GOLD),
        json.loads(PROJECTION.read_text(encoding="utf-8")),
        load_jsonl(SOURCE_GOLD),
        json.loads(SCORING_MANIFEST.read_text(encoding="utf-8")),
        applier,
    )
    manifest = json.loads(SCORING_MANIFEST.read_text(encoding="utf-8"))
    stale = str(manifest.get("status") or "") != "frozen"
    record(
        "正式评分输入派生件一致",
        "pass" if not errors else "fail",
        [
            f"派生件 sha256={digest(SCORING_INPUT)[:12]}…；counts={json.dumps(manifest.get('counts') or {}, ensure_ascii=False)}",
            f"manifest.status={manifest.get('status')!r}" + ("（**仍标 pending**，未随冻结更新）" if stale else "（已随冻结更新）"),
            *errors[:4],
        ],
    )


def check_p2() -> None:
    if not P2.is_file():
        record("P2 阈值/关键题/负例与冻结物一致", "fail", ["缺 P2 确认单"])
        return
    scoring = __import__("plugins.corpus.scoring", fromlist=["DEFAULT_POLICY"])
    policy = scoring.DEFAULT_POLICY
    confirmation = json.loads(P2.read_text(encoding="utf-8"))
    recorded = next(i for i in confirmation["items"] if i["id"] == "P2-1")["values"]
    actual = {
        "top_k": policy.top_k,
        "min_rate": str(policy.min_rate),
        "require_critical_all_pass": policy.require_critical_all_pass,
        "max_false_positives": policy.max_false_positives,
        "max_fabricated_citations": policy.max_fabricated_citations,
    }
    gold = load_jsonl(GOLD)
    critical = [str(r["query_id"]) for r in gold if r.get("critical")]
    negatives = [str(r["query_id"]) for r in gold if r.get("answer_existence") == "no_answer"]
    critical_ok = len(critical) == confirmation["items"][1]["critical_count"]
    negatives_ok = negatives == confirmation["items"][2]["negative_ids"]
    record(
        "P2 阈值/关键题/负例与冻结物一致",
        "pass" if (recorded == actual and critical_ok and negatives_ok) else "fail",
        [
            f"policy 记录={json.dumps(recorded, ensure_ascii=False)}；代码现值={json.dumps(actual, ensure_ascii=False)}",
            f"关键题 {len(critical)}（记录 {confirmation['items'][1]['critical_count']}）；负例 {len(negatives)}（记录 {confirmation['items'][2]['negative_count']}）",
        ],
    )


def check_old_baseline() -> None:
    if not BASELINE_MANIFEST.is_file():
        record("旧基线身份/范围闭环", "fail", ["缺 baseline-case-manifest"])
        return
    manifest = json.loads(BASELINE_MANIFEST.read_text(encoding="utf-8"))
    blocked = [b for b in manifest.get("blocked_items") or [] if str(b.get("status", "")).startswith("blocked")]
    pending_freeze = manifest.get("status") != "frozen_r27"
    # 『无未冻结的必要外部指针』：清单引用的预期资产是否在链上
    binding = merged_binding()
    referenced: dict[str, str] = {}
    for category in manifest["categories"]:
        asset = category.get("expected_asset") or {}
        if asset.get("path"):
            referenced[f"{category['categories'][0]}.expected_asset"] = str(asset["path"])
        record_ref = (category.get("historical_record_ref") or {}).get("path")
        if record_ref:
            referenced[f"{category['categories'][0]}.historical_record_ref"] = str(record_ref)
        entry = (category.get("rerun_contract") or {}).get("entry")
        if isinstance(entry, str) and entry.endswith(".py"):
            referenced[f"{category['categories'][0]}.rerun_entry"] = entry
    unbound = {
        label: path
        for label, path in referenced.items()
        if path not in binding or (ROOT / path).is_file() and digest(ROOT / path) != binding.get(path)
    }
    missing_files = {label: path for label, path in referenced.items() if not (ROOT / path).is_file()}
    unresolved = [
        {"category": c["categories"][0], "status": g["status"], "item": g.get("item")}
        for c in manifest["categories"]
        for g in c["gaps"]
        if str(g["status"]) in {"to_be_resolved", "needs_definition", "needs_user_scope"}
    ]
    status = "pass" if not blocked and not unbound and not missing_files and not unresolved else "fail"
    record(
        "旧基线身份/范围闭环（含『无未冻结指针』）",
        status,
        [
            f"manifest.status={manifest.get('status')!r}（pending_freeze={pending_freeze}）；待你定/补={len(blocked)}",
            f"引用资产**未入链** {len(unbound)}/{len(referenced)}：{json.dumps(unbound, ensure_ascii=False)[:400]}",
            f"引用资产文件缺失：{json.dumps(missing_files, ensure_ascii=False)[:200]}",
            f"仍未解决条（to_be_resolved/needs_definition/needs_user_scope）：{json.dumps(unresolved, ensure_ascii=False)[:300]}",
        ],
    )


def check_initial_manifest() -> None:
    if not P4.is_file():
        record("唯一初始实验 manifest", "fail", ["缺 P4 清单"])
        return
    p4 = json.loads(P4.read_text(encoding="utf-8"))
    components = p4.get("components") or {}
    required = {
        "scorer",
        "query_gold",
        "approved_projection",
        "decisions",
        "source_gold",
        "policy",
        "lists",
        "baseline_mapping",
    }
    missing = sorted(required - set(components))
    query_gold = components.get("query_gold", {})
    unique_input = query_gold.get("scoring_input_path")
    reference_only = (query_gold.get("lineage") or {}).get("p1_draft_reference_only")
    execution = components.get("execution") or p4.get("execution") or {}
    status = p4.get("status")
    ok = (
        not missing
        and str(status).startswith("frozen")
        and bool(execution)
        and query_gold.get("unique") is True
        and bool(unique_input)
        and reference_only is not None
    )
    record(
        "唯一初始实验 manifest",
        "pass" if ok else "fail",
        [
            f"status={status!r}；缺组件={missing}",
            f"唯一评分输入={unique_input!r}（unique={query_gold.get('unique')}；"
            f"草稿仅作 lineage 对照={bool(reference_only)}）",
            f"执行段（命令/环境/初始参数）={'有' if execution else '**缺**'}；"
            f"未实现入口登记={len(execution.get('unimplemented_entrypoints') or [])} 项",
        ],
    )


def check_assets_in_chain() -> None:
    binding = merged_binding()
    required = {
        "正式评分输入": SCORING_INPUT,
        "评分输入清单": SCORING_MANIFEST,
        "评分输入派生器": SCORING_TOOL,
        "P2 确认单": P2,
        "P3 对账": P3,
        "P4 清单": P4,
        "旧基线用例清单": BASELINE_MANIFEST,
        "阶段完成门": Path(__file__).resolve(),
    }
    rows = []
    for label, path in required.items():
        relative = str(path.relative_to(ROOT))
        bound = binding.get(relative)
        state = "入链" if bound == digest(path) else ("**未入链**" if bound is None else "哈希不符")
        rows.append(f"{label}: {state}")
    failed = sum(1 for row in rows if "未入链" in row or "不符" in row)
    record("全部必要资产哈希入链", "pass" if failed == 0 else "fail", rows)


def check_signoff() -> None:
    """阶段签认：必须具名（reviewer/decision 非空）且记录已入链。"""

    if not SIGNOFF_JSON.is_file():
        record("阶段签认（具名 + 入链）", "fail", ["缺 signoff-record-i3-2.json"])
        return
    data = json.loads(SIGNOFF_JSON.read_text(encoding="utf-8"))
    fields = data.get("signature_fields") or {}
    named = bool(fields.get("reviewer")) and bool(fields.get("decision"))
    bound = merged_binding().get(str(SIGNOFF_JSON.relative_to(ROOT))) == digest(SIGNOFF_JSON)
    record(
        "阶段签认（具名 + 入链）",
        "pass" if named and bound else "fail",
        [
            f"status={data.get('status')!r}；reviewer={fields.get('reviewer')!r}；"
            f"decision={fields.get('decision')!r}；reviewed_at={fields.get('reviewed_at')!r}",
            f"记录入链={'是' if bound else '**否**'}",
        ],
    )


def check_holdout_isolation() -> None:
    """留出隔离：guard 的 forbidden_roots 必须覆盖各留出清单声明的来源。"""

    guard = json.loads(GUARD.read_text(encoding="utf-8"))
    roots = [str(p) for p in guard["sources"]["forbidden_roots"]]
    declared: dict[str, str] = {}
    prose = json.loads(PROSE_HOLDOUT.read_text(encoding="utf-8"))
    for sample in prose.get("samples") or []:
        pattern = str(sample.get("pattern") or "").lstrip("*")
        declared[str(sample.get("name"))] = pattern
    missing = [
        f"{name}（{pattern}）"
        for name, pattern in declared.items()
        if not any(pattern and pattern in root for root in roots)
    ]
    record(
        "留出隔离覆盖（guard ⊇ 留出清单）",
        "pass" if not missing else "fail",
        [
            f"forbidden_roots={len(roots)} 份；声明留出 {len(declared)} 项",
            f"未被覆盖：{missing or '无'}",
        ],
    )


def check_mapping_rule_verified() -> None:
    """19 题锚点映射必须已完成规则级复核关闭。"""

    mapping = json.loads(MAPPING.read_text(encoding="utf-8"))
    closure = mapping.get("closure") or {}
    anchors = [a for q in mapping["questions"] for a in q["anchors"]]
    unconfirmed = [a for a in anchors if not a.get("confirmed")]
    record(
        "旧锚点映射规则级复核关闭",
        "pass" if not unconfirmed and closure.get("kind") else "fail",
        [
            f"status={mapping.get('status')!r}；锚点 {len(anchors)} 个；未确认 {len(unconfirmed)}",
            f"复核 {closure.get('anchors_verified')} 通过 / {closure.get('anchors_failed')} 失败；"
            f"授权={closure.get('authorized_by')!r}",
        ],
    )


def check_tail_closure() -> None:
    """尾巴收口记录必须存在、入链，且没有仍为 open 的条目。"""

    if not CLOSURE.is_file():
        record("尾巴收口记录（无 open 项 + 入链）", "fail", ["缺 i3-2-closure.json"])
        return
    closure = json.loads(CLOSURE.read_text(encoding="utf-8"))
    open_items = [i["id"] for i in closure["items"] if i.get("status") == "open"]
    bound = merged_binding().get(CLOSURE_JSON_REL) == digest(CLOSURE)
    record(
        "尾巴收口记录（无 open 项 + 入链）",
        "pass" if not open_items and bound else "fail",
        [
            f"条目 {len(closure['items'])} 个；open={open_items or '无'}；入链={'是' if bound else '**否**'}",
            "；".join(f"{i['id']}={i['status']}" for i in closure["items"]),
        ],
    )


def main() -> int:
    check_upstream_approval()
    check_scoring_input()
    check_p2()
    check_old_baseline()
    check_initial_manifest()
    check_assets_in_chain()
    check_signoff()
    check_holdout_isolation()
    check_mapping_rule_verified()
    check_tail_closure()

    verdicts = {r["item"]: r["status"] for r in results}
    failed = [r["item"] for r in results if r["status"] == "fail"]
    payload = {
        "artifact": "i3-2-completion-gate",
        "generated_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
        "verdicts": verdicts,
        "results": results,
        "failed_items": failed,
        "i3_2_complete": not failed,
        "note": (
            "本门只判『I3-2 的冻结物是否齐备且一致』；真实非回归与 E2E 属 I3-5/I3-1，"
            "恒为 not_run，不得用本门通过代替业务通过。"
        ),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
