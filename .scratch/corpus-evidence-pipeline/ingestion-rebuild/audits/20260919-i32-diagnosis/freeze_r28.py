"""Step C：冻结 i0c-r28（Step A/B 产物入链 + 被覆盖字节归档 + 台账回填 + 验证器 r28 规则）。"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1]
ROOT = HERE.parents[4]
FREEZES = BASE / "freezes"
VALIDATOR = FREEZES / "validate_i0c_freeze.py"
MANIFEST = FREEZES / "freeze-manifest.json"
R28 = FREEZES / "i0c-r28.json"
COMPLETION_GATE = FREEZES / "validate_i3_2_completion.py"
BEFORE = HERE / "before-r28"
TASKS = ROOT / "docs/plan/corpus-ingestion-rebuild-tasks.md"
PLAN = ROOT / "docs/plan/claims-market-closed-loop-plan.md"
INV = BASE / "audits/20260918-i32-remaining-inventory"
BASE_REL = ".scratch/corpus-evidence-pipeline/ingestion-rebuild"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def r27_binding() -> dict[str, str]:
    data = json.loads((FREEZES / "i0c-r27.json").read_text(encoding="utf-8"))
    return {rel_: sha for items in (data.get("binding") or {}).values() for rel_, sha in items.items()}


def archive(relative: str) -> dict:
    """第一次写入即为 r27 被覆盖字节；重跑不得覆盖归档，并与 r27 绑定哈希比对。"""

    source = ROOT / relative
    target = BEFORE / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    existed = target.is_file()
    if not existed:
        shutil.copy2(source, target)
    bound = r27_binding().get(relative)
    ok = bound is None or digest(target) == bound
    return {
        "path": relative,
        "archived_as": rel(target),
        "sha256": digest(target),
        "pre_existing": existed,
        "matches_r27_binding": ok,
    }


R28_BLOCK = '''
if "i0c-r28" in by_id:
    i0c28 = load_json(BASE / by_id["i0c-r28"].get("file", ""))
    parent = i0c28.get("parent_snapshot", {})
    expected_parent = BASE / by_id["i0c-r27"]["file"]
    check(parent.get("snapshot_id") == "i0c-r27", "r28 parent must be r27")
    check(parent.get("path") == str(expected_parent.relative_to(ROOT)), "r28 parent path mismatch")
    check(parent.get("sha256") == digest(expected_parent), "r28 parent bytes mismatch")
    binding28 = i0c28.get("binding", {})
    corrections = i0c28.get("corrections", {})
    for finding in ("I3-2_derived_scoring_input", "I3-2_baseline_asset_binding",
                    "I3-2_legacy_anchor_mapping", "I3-2_formula_inputs",
                    "I3-2_completion_gate", "I3-5"):
        check(finding in corrections, f"r28 missing correction {finding}")
    base = ".scratch/corpus-evidence-pipeline/ingestion-rebuild"
    audit = f"{base}/audits/20260919-i32-diagnosis"
    inv = f"{base}/audits/20260918-i32-remaining-inventory"
    allowed = {
        "i3_2_assets": {
            f"{base}/i3-2/query-gold-scoring-v1.jsonl",
            f"{base}/i3-2/scoring-input-manifest.json",
            f"{base}/i3s2_scoring_input.py",
            f"{inv}/p2/policy-and-lists-confirmation.json",
            f"{inv}/p3/baseline-mapping-reconciliation.json",
            f"{inv}/p4/experiment-initial-version.json",
            f"{inv}/p4/experiment-initial-version.md",
            f"{audit}/baseline-case-manifest.json",
            f"{audit}/baseline-case-manifest.md",
            f"{audit}/legacy-anchor-mapping.json",
            f"{audit}/legacy-anchor-mapping.md",
            f"{audit}/build_legacy_anchor_mapping.py",
            f"{audit}/retrospective-i32.md",
        },
        "i3_2_baseline_assets": {
            "plugins/corpus/golden.py",
            "plugins/corpus/derivation.py",
            f"{base}/i0a5-doclist-recount-20260915.json",
            f"{base}/i0a4-candidates-v3-20260915.json",
            f"{base}/baseline-bindings.json",
            ".scratch/corpus-evidence-pipeline/verify_claims_entry.py",
            ".scratch/corpus-evidence-pipeline/pilot_manifest.json",
            ".scratch/corpus-evidence-pipeline/claims-entry-27dfab4cb9a97cf8ad72d269039d822afc3f39631601d76c0bed1b87645c0cb3.json",
            ".scratch/corpus-evidence-pipeline/semantic-repair-report.md",
            ".scratch/corpus-evidence-pipeline/prose-repair-report.md",
            ".scratch/corpus-evidence-pipeline/spec.md",
            ".scratch/corpus-evidence-pipeline/prose_holdout_manifest.json",
            "data/corpus/.audit/c1_full84_doc_kind_review_20260912.csv",
        },
        "docs": {"docs/plan/corpus-ingestion-rebuild-tasks.md",
                 "docs/plan/claims-market-closed-loop-plan.md"},
        "freeze_validator": {f"{base}/freezes/validate_i0c_freeze.py",
                             f"{base}/freezes/validate_i3_2_completion.py"},
    }
    check(set(binding28) == set(allowed) | {"i3_2_archive"}, "r28 binding groups mismatch")
    for group, expected in allowed.items():
        check(set(binding28.get(group, {})) == expected, f"r28 unexpected {group} scope")
    for rel, _sha in binding28.get("i3_2_baseline_assets", {}).items():
        if rel.startswith("plugins/"):
            check(rel in {"plugins/corpus/golden.py", "plugins/corpus/derivation.py"},
                  f"r28 越界绑定 plugins 文件 {rel}（只作基线**引用资产**，不改实现）")
        check(not rel.startswith("tests/"), f"r28 越界绑定 tests {rel}")
    archive_keys = list(binding28.get("i3_2_archive", {}))
    for original in (f"{audit}/baseline-case-manifest.json",
                     f"{audit}/baseline-case-manifest.md",
                     f"{base}/freezes/validate_i0c_freeze.py",
                     "docs/plan/corpus-ingestion-rebuild-tasks.md",
                     "docs/plan/claims-market-closed-loop-plan.md"):
        matched = [key for key in archive_keys if key.endswith(original) and "before-r28" in key]
        check(len(matched) == 1, f"r28 missing archive for {original}")
    for required in (f"{base}/i3-2/query-gold-scoring-v1.jsonl",
                     f"{base}/freezes/validate_i3_2_completion.py"):
        check(required in json.dumps(binding28), f"r28 未绑定必需资产 {required}")
    merge_binding(i0c_current_binding, binding28)

'''


def patch_validator() -> dict:
    text = VALIDATOR.read_text(encoding="utf-8")
    if 'if "i0c-r28" in by_id:' in text:
        return {"already_patched": True}
    marker = 'check("i0c-r26" in by_id, "索引缺少 i0c-r26 条目")'
    assert marker in text
    text = text.replace(marker, marker + '\ncheck("i0c-r27" in by_id, "索引缺少 i0c-r27 条目")\n'
                                 'check("i0c-r28" in by_id, "索引缺少 i0c-r28 条目")', 1)
    anchor = "# 最新修订绑定优先（supersession）：i0c-r2..r26 显式重绑的路径改由合并后的"
    assert anchor in text
    text = text.replace(anchor, R28_BLOCK + anchor.replace("..r26", "..r28"), 1)
    tail = ('+ ("r26 I3-2 adoption verified (new source-gold 36 slots, 82 targets, filed decisions, '
            'gate ready=true, approved projection 79+20)" if "i0c-r26" in by_id else ""))')
    assert tail in text
    text = text.replace(tail, tail[:-2] + ' + ("r28 I3-2 derived scoring input + baseline asset binding '
                                        '+ legacy anchor mapping verified" if "i0c-r28" in by_id else ""))', 1)
    VALIDATOR.write_text(text, encoding="utf-8")
    return {"already_patched": False, "sha256": digest(VALIDATOR)}


def build_r28(archived: list[dict]) -> dict:
    assets = {
        f"{BASE_REL}/i3-2/query-gold-scoring-v1.jsonl": digest(BASE / "i3-2/query-gold-scoring-v1.jsonl"),
        f"{BASE_REL}/i3-2/scoring-input-manifest.json": digest(BASE / "i3-2/scoring-input-manifest.json"),
        f"{BASE_REL}/i3s2_scoring_input.py": digest(BASE / "i3s2_scoring_input.py"),
        f"{BASE_REL}/audits/20260918-i32-remaining-inventory/p2/policy-and-lists-confirmation.json":
            digest(INV / "p2/policy-and-lists-confirmation.json"),
        f"{BASE_REL}/audits/20260918-i32-remaining-inventory/p3/baseline-mapping-reconciliation.json":
            digest(INV / "p3/baseline-mapping-reconciliation.json"),
        f"{BASE_REL}/audits/20260918-i32-remaining-inventory/p4/experiment-initial-version.json":
            digest(INV / "p4/experiment-initial-version.json"),
        f"{BASE_REL}/audits/20260918-i32-remaining-inventory/p4/experiment-initial-version.md":
            digest(INV / "p4/experiment-initial-version.md"),
        f"{BASE_REL}/audits/20260919-i32-diagnosis/baseline-case-manifest.json": digest(HERE / "baseline-case-manifest.json"),
        f"{BASE_REL}/audits/20260919-i32-diagnosis/baseline-case-manifest.md": digest(HERE / "baseline-case-manifest.md"),
        f"{BASE_REL}/audits/20260919-i32-diagnosis/legacy-anchor-mapping.json": digest(HERE / "legacy-anchor-mapping.json"),
        f"{BASE_REL}/audits/20260919-i32-diagnosis/legacy-anchor-mapping.md": digest(HERE / "legacy-anchor-mapping.md"),
        f"{BASE_REL}/audits/20260919-i32-diagnosis/build_legacy_anchor_mapping.py": digest(HERE / "build_legacy_anchor_mapping.py"),
        f"{BASE_REL}/audits/20260919-i32-diagnosis/retrospective-i32.md": digest(HERE / "retrospective-i32.md"),
    }
    baseline_assets = {
        "plugins/corpus/golden.py": digest(ROOT / "plugins/corpus/golden.py"),
        "plugins/corpus/derivation.py": digest(ROOT / "plugins/corpus/derivation.py"),
        f"{BASE_REL}/i0a5-doclist-recount-20260915.json": digest(BASE / "i0a5-doclist-recount-20260915.json"),
        f"{BASE_REL}/i0a4-candidates-v3-20260915.json": digest(BASE / "i0a4-candidates-v3-20260915.json"),
        f"{BASE_REL}/baseline-bindings.json": digest(BASE / "baseline-bindings.json"),
        ".scratch/corpus-evidence-pipeline/verify_claims_entry.py":
            digest(ROOT / ".scratch/corpus-evidence-pipeline/verify_claims_entry.py"),
        ".scratch/corpus-evidence-pipeline/pilot_manifest.json":
            digest(ROOT / ".scratch/corpus-evidence-pipeline/pilot_manifest.json"),
        ".scratch/corpus-evidence-pipeline/claims-entry-27dfab4cb9a97cf8ad72d269039d822afc3f39631601d76c0bed1b87645c0cb3.json":
            digest(ROOT / ".scratch/corpus-evidence-pipeline/claims-entry-27dfab4cb9a97cf8ad72d269039d822afc3f39631601d76c0bed1b87645c0cb3.json"),
        ".scratch/corpus-evidence-pipeline/semantic-repair-report.md":
            digest(ROOT / ".scratch/corpus-evidence-pipeline/semantic-repair-report.md"),
        ".scratch/corpus-evidence-pipeline/prose-repair-report.md":
            digest(ROOT / ".scratch/corpus-evidence-pipeline/prose-repair-report.md"),
        ".scratch/corpus-evidence-pipeline/spec.md": digest(ROOT / ".scratch/corpus-evidence-pipeline/spec.md"),
        ".scratch/corpus-evidence-pipeline/prose_holdout_manifest.json":
            digest(ROOT / ".scratch/corpus-evidence-pipeline/prose_holdout_manifest.json"),
        "data/corpus/.audit/c1_full84_doc_kind_review_20260912.csv":
            digest(ROOT / "data/corpus/.audit/c1_full84_doc_kind_review_20260912.csv"),
    }
    r27 = json.loads((FREEZES / "i0c-r27.json").read_text(encoding="utf-8"))
    del r27
    return {
        "snapshot_id": "i0c-r28",
        "revision": "r28",
        "phase": "i0c",
        "task": (
            "I3-2 remediation Step A-C: derived formal scoring input (gate-checkable) + baseline asset binding "
            "(no unfrozen external pointers) + legacy anchor mapping 19/19 unique + formula input declaration + "
            "completion gate implemented"
        ),
        "parent_snapshot": {
            "snapshot_id": "i0c-r27",
            "path": rel(FREEZES / "i0c-r27.json"),
            "sha256": digest(FREEZES / "i0c-r27.json"),
        },
        "binding": {
            "i3_2_assets": assets,
            "i3_2_baseline_assets": baseline_assets,
            "i3_2_archive": {
                item["archived_as"]: item["sha256"] for item in archived
            },
            "docs": {
                rel(TASKS): digest(TASKS),
                rel(PLAN): digest(PLAN),
            },
            "freeze_validator": {
                rel(VALIDATOR): digest(VALIDATOR),
                rel(COMPLETION_GATE): digest(COMPLETION_GATE),
            },
        },
        "corrections": {
            "I3-2_derived_scoring_input": (
                "正式评分输入派生件 `i3-2/query-gold-scoring-v1.jsonl`（79 必需 + 20 补充、负例无目标）"
                "+ lineage 清单 + 派生器与唯一读入口 `load_scoring_input`；审批原件未改（门仍 ready=true）"
            ),
            "I3-2_baseline_asset_binding": (
                "旧基线清单**引用的资产**（golden.py/derivation.py/pilot_manifest/机器记录/报告/CSV/"
                "verify_claims_entry/v3 明细/doclist）随本轮入链，消除『未冻结的必要外部指针』；"
                "plugins 只作引用资产（golden.py、derivation.py），不改实现"
            ),
            "I3-2_legacy_anchor_mapping": (
                "19 题旧锚点 (title_contains, doc_prefix) → 新 source 身份（i0a5-doclist 的 doc_id）"
                "首轮映射：19/19 唯一命中、source_path 22/22 在磁盘、其中 5 个 doc_id 与已标注 source-gold 同源；"
                "O6 因来源留出排除；confirmed=false 待人工复核"
            ),
            "I3-2_formula_inputs": (
                "7 条公式的输入指标按 plugins/corpus/derivation.py 声明逐条登记（formula_7 契约补全）"
            ),
            "I3-2_completion_gate": (
                "阶段完成门 `freezes/validate_i3_2_completion.py` 已实现并入链；"
                "I3-2 其余冻结项（正式评分输入接线、初始 manifest、完成门）本轮补齐"
            ),
            "I3-5": (
                "真实非回归与 E2E 仍未执行（I3-5/I3-1）；本修订只完成 I3-2 冻结物与其判据"
            ),
        },
        "created_at": datetime.now(timezone.utc).isoformat(),
        "notes": [
            "零模型、零数据库写入、未读留出原文：本轮只做派生/映射/绑定与门实现。",
            "留出隔离仍由 guards/i3.json 的 4 个 forbidden_roots 承担；"
            "`prose_holdout_manifest.json`（天风 5520fab6）**未在** forbidden_roots 内——已登记为待核项，未擅自改守卫。",
            "19 题映射 confirmed=false、20 条人工同义 warning、macro-004 机器 blocked 覆盖仍属人工复核项，"
            "完成门绿灯只表示冻结物齐备，不表示语义/业务通过。",
        ],
    }


def patch_docs() -> list[str]:
    tasks = TASKS.read_text(encoding="utf-8")
    plan = PLAN.read_text(encoding="utf-8")
    if "Step A—C 整改（r28" in tasks and "r28 优先状态" in plan:
        return ["already_patched"]  # 幂等：首轮已写（首轮归档已保存 r27 字节）
    changed = []
    anchor = "**I3-2 旧基线冻结（r27，2026-09-19）**"
    assert anchor in tasks
    block = (
        "**I3-2 Step A—C 整改（r28，2026-09-19）**：按诊断稿 `20260919-i32-diagnosis` 的 Step A—C 完成三项：\n"
        "① **正式评分输入派生件** `i3-2/query-gold-scoring-v1.jsonl`（`1b018ceb…`，79 必需 + 20 补充、\n"
        "负例无目标、原字段零改动）+ `scoring-input-manifest.json` lineage + 派生器 `i3s2_scoring_input.py`\n"
        "（含唯一读入口 `load_scoring_input` 与 6 条变异反例）；审批原件未改（门仍 `ready=true`）。\n"
        "② **旧基线引用资产入链**：`golden.py`／`derivation.py`／`pilot_manifest.json`／机器记录／\n"
        "三份报告／`spec.md`／`prose_holdout_manifest.json`／doc_kind CSV／`verify_claims_entry.py`／\n"
        "`i0a5-doclist`／`i0a4-candidates-v3` 随 r28 绑定，消除『未冻结的必要外部指针』。\n"
        "③ **旧锚点映射与公式契约**：19 题旧锚点 → 新 source 身份（`i0a5-doclist` 的 `doc_id`）**19/19 唯一命中**、\n"
        "22/22 `source_path` 在磁盘、其中 5 个 doc_id 与已标注 source-gold 同源，O6 因留出排除\n"
        "（`legacy-anchor-mapping.json`，`confirmed=false` 待人工复核）；7 条公式的输入指标按\n"
        "`plugins/corpus/derivation.py` 声明登记；**阶段完成门** `validate_i3_2_completion.py` 已实现并入链。\n"
        "冻结修订 **i0c-r28**（parent=r27）。**仍未宣告 I3-2 完成**：19 题映射复核、20 条人工同义 warning、\n"
        "`macro-004` 机器 blocked 覆盖属人工复核项；I3-5/I3-1 未执行。\n\n"
    )
    tasks = tasks.replace(anchor, block + anchor, 1)
    changed.append("tasks")

    old_plan = "**r27 优先状态（2026-09-19 旧基线冻结）**"
    assert old_plan in plan
    new_plan = (
        "**r28 优先状态（2026-09-19，I3-2 Step A—C 整改）**：正式评分输入已派生并入链\n"
        "（`i3-2/query-gold-scoring-v1.jsonl` `1b018ceb…` + lineage + 唯一读入口；审批原件未改，门 ready=true）；\n"
        "旧基线**引用资产全部入链**（消除未冻结外部指针）；19 题旧锚点→新 source 身份 **19/19 唯一命中**\n"
        "（`legacy-anchor-mapping.json`，待人工复核）；7 条公式输入指标已登记；阶段完成门\n"
        "`validate_i3_2_completion.py` 已实现；冻结 **i0c-r28**（parent=r27）。其余人工复核项与 I3-5/I3-1 未变。\n\n"
        "**r27 历史状态（旧基线冻结）**"
    )
    plan = plan.replace(old_plan, new_plan, 1)
    changed.append("plan")
    TASKS.write_text(tasks, encoding="utf-8")
    PLAN.write_text(plan, encoding="utf-8")
    return changed


def main() -> int:
    archived = [
        archive(f"{BASE_REL}/audits/20260919-i32-diagnosis/baseline-case-manifest.json"),
        archive(f"{BASE_REL}/audits/20260919-i32-diagnosis/baseline-case-manifest.md"),
        archive(f"{BASE_REL}/freezes/validate_i0c_freeze.py"),
        archive("docs/plan/corpus-ingestion-rebuild-tasks.md"),
        archive("docs/plan/claims-market-closed-loop-plan.md"),
    ]
    patched = patch_validator()
    docs = patch_docs()
    r28 = build_r28(archived)
    R28.write_text(json.dumps(r28, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    entry = {
        "snapshot_id": "i0c-r28",
        "file": "i0c-r28.json",
        "sha256": digest(R28),
        "parent_snapshot_id": "i0c-r27",
        "created_at": r28["created_at"],
    }
    manifest["snapshots"] = [
        item for item in manifest["snapshots"] if item.get("snapshot_id") != "i0c-r28"
    ] + [entry]
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def run(cmd: list[str]) -> dict:
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT), check=False)
        return {"exit": proc.returncode, "out": (proc.stdout or "").strip().splitlines()[-2:],
                "err": (proc.stderr or "").strip().splitlines()[-3:]}

    chain = run([sys.executable, str(VALIDATOR)])
    gate = run([sys.executable, str(COMPLETION_GATE)])
    print(json.dumps({
        "archived": [{"file": item["archived_as"].split("/")[-1],
                      "pre_existing": item["pre_existing"],
                      "matches_r27_binding": item["matches_r27_binding"]} for item in archived],
        "validator": patched,
        "docs_changed": docs,
        "r28_sha256": digest(R28),
        "chain": chain,
        "completion_gate": gate,
    }, ensure_ascii=False, indent=2))
    return 0 if chain["exit"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
