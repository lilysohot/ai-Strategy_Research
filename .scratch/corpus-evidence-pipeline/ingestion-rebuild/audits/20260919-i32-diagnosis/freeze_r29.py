"""r29：Step 5 复核整改（P4 路径统一）+ 复核/差异包入链 + 台账 + 验证器 r29 规则。"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("/home/administrator/FrontierAgent")
BASE = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild"
HERE = BASE / "audits/20260919-i32-diagnosis"
INV = BASE / "audits/20260918-i32-remaining-inventory"
FREEZES = BASE / "freezes"
VALIDATOR = FREEZES / "validate_i0c_freeze.py"
MANIFEST = FREEZES / "freeze-manifest.json"
R29 = FREEZES / "i0c-r29.json"
BEFORE = HERE / "before-r29"
TASKS = ROOT / "docs/plan/corpus-ingestion-rebuild-tasks.md"
PLAN = ROOT / "docs/plan/claims-market-closed-loop-plan.json".replace(".json", ".md")
BASE_REL = ".scratch/corpus-evidence-pipeline/ingestion-rebuild"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


# ── 0. 复核脚本的路径解析改健壮（ROOT 优先，退回 BASE）


def fix_review_resolution() -> bool:
    path = HERE / "step5_review.py"
    text = path.read_text(encoding="utf-8")
    if "def resolve_path(" in text:
        return False
    helper = '''def resolve_path(raw: str) -> Path:
    """路径字段一律按仓库根解析；历史字段可能相对 ingestion-rebuild，退回尝试。"""

    candidate = ROOT / raw
    return candidate if candidate.exists() else BASE / raw


'''
    text = text.replace("def digest(path: Path) -> str:", helper + "def digest(path: Path) -> str:", 1)
    text = text.replace('''    lineage_checks = {
        "scorer": ROOT / components["scorer"]["path"],
        "source_gold": BASE / components["source_gold"]["path"],
        "approved_projection": BASE / components["approved_projection"]["path"],
        "decisions": BASE / components["decisions"]["path"],
        "policy": ROOT / components["policy"]["confirmation"],
    }''', '''    lineage_checks = {
        "scorer": resolve_path(components["scorer"]["path"]),
        "source_gold": resolve_path(components["source_gold"]["path"]),
        "approved_projection": resolve_path(components["approved_projection"]["path"]),
        "decisions": resolve_path(components["decisions"]["path"]),
        "policy": resolve_path(components["policy"]["confirmation"]),
    }''', 1)
    path.write_text(text, encoding="utf-8")
    import ast

    ast.parse(text)
    return True


# ── 1. 验证器 r29 规则

R29_BLOCK = '''
if "i0c-r29" in by_id:
    i0c29 = load_json(BASE / by_id["i0c-r29"].get("file", ""))
    parent = i0c29.get("parent_snapshot", {})
    expected_parent = BASE / by_id["i0c-r28"]["file"]
    check(parent.get("snapshot_id") == "i0c-r28", "r29 parent must be r28")
    check(parent.get("path") == str(expected_parent.relative_to(ROOT)), "r29 parent path mismatch")
    check(parent.get("sha256") == digest(expected_parent), "r29 parent bytes mismatch")
    binding29 = i0c29.get("binding", {})
    corrections = i0c29.get("corrections", {})
    for finding in ("I3-2_step5_review", "I3-2_initial_manifest_paths", "I3-5"):
        check(finding in corrections, f"r29 missing correction {finding}")
    base = ".scratch/corpus-evidence-pipeline/ingestion-rebuild"
    audit = f"{base}/audits/20260919-i32-diagnosis"
    inv = f"{base}/audits/20260918-i32-remaining-inventory"
    allowed = {
        "i3_2_assets": {
            f"{inv}/p2/policy-and-lists-confirmation.json",
            f"{inv}/p3/baseline-mapping-reconciliation.json",
            f"{inv}/p4/experiment-initial-version.json",
            f"{inv}/p4/experiment-initial-version.md",
        },
        "i3_2_step5": {
            f"{audit}/step5-review.json",
            f"{audit}/step5-review.md",
            f"{audit}/step5-diff-pack.md",
            f"{audit}/step5_review.py",
        },
        "docs": {"docs/plan/corpus-ingestion-rebuild-tasks.md",
                 "docs/plan/claims-market-closed-loop-plan.md"},
        "freeze_validator": {f"{base}/freezes/validate_i0c_freeze.py"},
    }
    check(set(binding29) == set(allowed) | {"i3_2_archive"}, "r29 binding groups mismatch")
    for group, expected in allowed.items():
        check(set(binding29.get(group, {})) == expected, f"r29 unexpected {group} scope")
    archive_keys = list(binding29.get("i3_2_archive", {}))
    for original in (f"{inv}/p2/policy-and-lists-confirmation.json",
                     f"{inv}/p3/baseline-mapping-reconciliation.json",
                     f"{inv}/p4/experiment-initial-version.json",
                     f"{inv}/p4/experiment-initial-version.md",
                     f"{base}/freezes/validate_i0c_freeze.py",
                     "docs/plan/corpus-ingestion-rebuild-tasks.md",
                     "docs/plan/claims-market-closed-loop-plan.md"):
        matched = [key for key in archive_keys if key.endswith(original) and "before-r29" in key]
        check(len(matched) == 1, f"r29 missing archive for {original}")
    for group, items in binding29.items():
        for rel_ in items:
            check(not rel_.startswith(("plugins/", "tests/", "guards/")),
                  f"r29 越界绑定 {rel_}")
    merge_binding(i0c_current_binding, binding29)

'''


def patch_validator() -> dict:
    text = VALIDATOR.read_text(encoding="utf-8")
    if 'if "i0c-r29" in by_id:' in text:
        return {"already_patched": True}
    marker = 'check("i0c-r28" in by_id, "索引缺少 i0c-r28 条目")'
    assert marker in text
    text = text.replace(marker, marker + '\ncheck("i0c-r29" in by_id, "索引缺少 i0c-r29 条目")', 1)
    anchor = "# 最新修订绑定优先（supersession）：i0c-r2..r28 显式重绑的路径改由合并后的"
    assert anchor in text
    text = text.replace(anchor, R29_BLOCK + anchor.replace("..r28", "..r29"), 1)
    VALIDATOR.write_text(text, encoding="utf-8")
    return {"already_patched": False, "sha256": digest(VALIDATOR)}


def patch_docs() -> list[str]:
    tasks = TASKS.read_text(encoding="utf-8")
    plan = PLAN.read_text(encoding="utf-8")
    if "Step 5 复核整改（r29" in tasks:
        return ["already_patched"]
    anchor = "**I3-2 Step A—C 整改（r28，2026-09-19）**"
    assert anchor in tasks
    block = (
        "**I3-2 Step 5 针对性复核与整改（r29，2026-09-19）**：复核范围限定『新增派生关系／旧基线范围／初始版本』，\n"
        "复用既有审批（不重审补料链）。方法为**独立重推**（未复用产物自校验）+ 通用路径可解析检查。\n"
        "**抓到并修掉 4 处 P4 路径缺陷**：`policy.confirmation` 与 `baseline_mapping.reconciliation`、\n"
        "`decisions.path`、`approved_projection.path`（含 `source_gold`/`index`/`case_level`）基准目录不一致，\n"
        "从仓库根解析不到 → 统一为仓库根相对路径并重算 lineage。复核结论：**通过**\n"
        "（[step5-review.md](../../.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i32-diagnosis/step5-review.md)），\n"
        "另 1 项观察项：prose 留出（天风 `5520fab6`）未纳入 `guards/i3.json` 的 `forbidden_roots`（待定，未擅自改守卫）。\n"
        "冻结修订 **i0c-r29**（parent=r28）：绑 P2/P3/P4 修正件 + Step 5 复核/差异包 + 台账；\n"
        "**阶段签认记录 `signoff-record-i3-2.{md,json}` 保持 `pending_user_signoff`，待 U 具名签认后再入链**。\n\n"
    )
    tasks = tasks.replace(anchor, block + anchor, 1)
    old_plan = "**r28 优先状态（2026-09-19，I3-2 Step A—C 整改）**"
    assert old_plan in plan
    new_plan = (
        "**r29 优先状态（2026-09-19，Step 5 复核整改）**：针对性复核通过并修掉 P4 的 4 处路径基准缺陷，\n"
        "冻结 **i0c-r29**（parent=r28；绑修正后的 P2/P3/P4 + 复核/差异包 + 台账）。**阶段签认待 U**\n"
        "（`signoff-record-i3-2.md` 状态 `pending_user_signoff`，签认后另立修订入链）。\n\n"
        "**r28 历史状态（Step A—C 整改）**"
    )
    plan = plan.replace(old_plan, new_plan, 1)
    TASKS.write_text(tasks, encoding="utf-8")
    PLAN.write_text(plan, encoding="utf-8")
    return ["tasks", "plan"]


def r29_binding() -> dict:
    data = json.loads((FREEZES / "i0c-r28.json").read_text(encoding="utf-8"))
    r28_paths = {rel_ for items in data["binding"].values() for rel_ in items}
    return r28_paths


def archive(relative: str) -> dict:
    target = BEFORE / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.is_file():
        shutil.copy2(ROOT / relative, target)
    bound = r29_binding()
    return {"path": relative, "archived_as": rel(target), "sha256": digest(target),
            "in_r28_binding": relative in bound}


def build_r29(archived: list[dict]) -> dict:
    r28 = json.loads((FREEZES / "i0c-r28.json").read_text(encoding="utf-8"))
    del r28
    return {
        "snapshot_id": "i0c-r29",
        "revision": "r29",
        "phase": "i0c",
        "task": (
            "I3-2 Step 5 targeted review + remediation: P4 path baseline fixed to repo-root relative "
            "(4 defects found by independent review), review/diff-pack bound; stage sign-off pending U"
        ),
        "parent_snapshot": {
            "snapshot_id": "i0c-r28",
            "path": rel(FREEZES / "i0c-r28.json"),
            "sha256": digest(FREEZES / "i0c-r28.json"),
        },
        "binding": {
            "i3_2_assets": {
                f"{BASE_REL}/audits/20260918-i32-remaining-inventory/p2/policy-and-lists-confirmation.json":
                    digest(INV / "p2/policy-and-lists-confirmation.json"),
                f"{BASE_REL}/audits/20260918-i32-remaining-inventory/p3/baseline-mapping-reconciliation.json":
                    digest(INV / "p3/baseline-mapping-reconciliation.json"),
                f"{BASE_REL}/audits/20260918-i32-remaining-inventory/p4/experiment-initial-version.json":
                    digest(INV / "p4/experiment-initial-version.json"),
                f"{BASE_REL}/audits/20260918-i32-remaining-inventory/p4/experiment-initial-version.md":
                    digest(INV / "p4/experiment-initial-version.md"),
            },
            "i3_2_step5": {
                f"{BASE_REL}/audits/20260919-i32-diagnosis/step5-review.json": digest(HERE / "step5-review.json"),
                f"{BASE_REL}/audits/20260919-i32-diagnosis/step5-review.md": digest(HERE / "step5-review.md"),
                f"{BASE_REL}/audits/20260919-i32-diagnosis/step5-diff-pack.md": digest(HERE / "step5-diff-pack.md"),
                f"{BASE_REL}/audits/20260919-i32-diagnosis/step5_review.py": digest(HERE / "step5_review.py"),
            },
            "i3_2_archive": {item["archived_as"]: item["sha256"] for item in archived},
            "docs": {rel(TASKS): digest(TASKS), rel(PLAN): digest(PLAN)},
            "freeze_validator": {rel(VALIDATOR): digest(VALIDATOR)},
        },
        "corrections": {
            "I3-2_step5_review": (
                "Step 5 针对性复核（独立重推 + 通用路径可解析检查）：派生关系/旧基线范围/初始版本逐项复核，"
                "结论通过；1 项观察项（prose 留出天风 5520fab6 未在 guard forbidden_roots）登记待定"
            ),
            "I3-2_initial_manifest_paths": (
                "抓到并修掉 P4 的 4 处路径基准不一致（policy.confirmation、baseline_mapping.reconciliation、"
                "decisions.path、approved_projection.path，含 source_gold/index/case_level），统一仓库根相对并重算 lineage"
            ),
            "I3-5": "真实非回归与 E2E 仍未执行；阶段签认（signoff-record-i3-2）待 U 具名签署后另立修订入链",
        },
        "created_at": datetime.now(timezone.utc).isoformat(),
        "notes": [
            "零模型、零数据库写入；只改 P2/P3/P4 的路径字段与复核产物，未触碰评分器/金标/守卫/审批原件。",
            "签认记录有意**不**在本轮入链：签名会改变其字节，须在签名后由下一修订绑定（与 M5 放行先例一致）。",
        ],
    }


def main() -> int:
    fixed = fix_review_resolution()
    archived = [
        archive(f"{BASE_REL}/audits/20260918-i32-remaining-inventory/p2/policy-and-lists-confirmation.json"),
        archive(f"{BASE_REL}/audits/20260918-i32-remaining-inventory/p3/baseline-mapping-reconciliation.json"),
        archive(f"{BASE_REL}/audits/20260918-i32-remaining-inventory/p4/experiment-initial-version.json"),
        archive(f"{BASE_REL}/audits/20260918-i32-remaining-inventory/p4/experiment-initial-version.md"),
        archive(f"{BASE_REL}/freezes/validate_i0c_freeze.py"),
        archive("docs/plan/corpus-ingestion-rebuild-tasks.md"),
        archive("docs/plan/claims-market-closed-loop-plan.md"),
    ]
    # 先跑一次复核（更新 step5-review.* 与差异包），再冻结
    subprocess.run([sys.executable, str(HERE / "step5_review.py")], cwd=str(ROOT), check=False)
    patched = patch_validator()
    docs = patch_docs()
    r29 = build_r29(archived)
    R29.write_text(json.dumps(r29, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    manifest["snapshots"] = [s for s in manifest["snapshots"] if s.get("snapshot_id") != "i0c-r29"] + [
        {"snapshot_id": "i0c-r29", "file": "i0c-r29.json", "sha256": digest(R29),
         "parent_snapshot_id": "i0c-r28", "created_at": r29["created_at"]}
    ]
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def run(cmd: list[str]) -> dict:
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT), check=False)
        return {"exit": proc.returncode, "tail": (proc.stdout or "").strip().splitlines()[-1:]}

    chain = run([sys.executable, str(VALIDATOR)])
    gate = run([sys.executable, str(FREEZES / "validate_i3_2_completion.py")])
    review = run([sys.executable, str(HERE / "step5_review.py"), "--no-write"])
    print(json.dumps({
        "review_resolution_fixed": fixed,
        "archived": [{"file": item["archived_as"].split("/")[-1], "in_r28": item["in_r28_binding"]} for item in archived],
        "validator": patched, "docs": docs, "r29_sha256": digest(R29),
        "chain": chain, "completion_gate": gate, "step5_review": review,
    }, ensure_ascii=False, indent=2))
    return 0 if chain["exit"] == 0 and gate["exit"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
