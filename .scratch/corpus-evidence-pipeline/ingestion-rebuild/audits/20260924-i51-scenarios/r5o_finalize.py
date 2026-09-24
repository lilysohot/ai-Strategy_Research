"""r5o 落章：I5-1 四场景复核执行入链（全绿）+ F1 登记待裁定 + 架构文档回滚事件登记。"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path("/home/administrator/FrontierAgent")
FREEZES = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes"
VALIDATOR = ".scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/validate_i0c_freeze.py"
AUDIT = ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260924-i51-scenarios"
PREV = f"{AUDIT}/previous-effective-bindings-r5o.json"
TASKS = "docs/plan/corpus-ingestion-rebuild-tasks.md"
CLAIMS = "docs/plan/claims-market-closed-loop-plan.md"
EVIDENCE = (
    f"{AUDIT}/i51-summary-report.json",
    f"{AUDIT}/i51-s1-rerun-report.json",
    f"{AUDIT}/i51-s2-srcchange-report.json",
    f"{AUDIT}/i51-s3-newrule-report.json",
    f"{AUDIT}/i51-s4-idxreb-report.json",
)


def digest(rel: str) -> str:
    return hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()


def main() -> int:
    target = FREEZES / "i0c-r5o.json"
    if target.exists():
        raise SystemExit(f"write-once snapshot already exists: {target}")
    if (ROOT / PREV).exists():
        raise SystemExit(f"write-once previous-bindings file already exists: {PREV}")
    parent = FREEZES / "i0c-r5n.json"
    r5n = json.loads(parent.read_text(encoding="utf-8"))
    flat5n = {p: h for group in r5n["binding"].values() for p, h in group.items()}
    changed = (TASKS, CLAIMS, VALIDATOR)
    prev = {p: flat5n[p] for p in changed}
    now = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%dT%H:%M:%S+08:00")
    prev_path = ROOT / PREV
    prev_path.parent.mkdir(parents=True, exist_ok=True)
    prev_path.write_text(
        json.dumps(prev, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    new_validator_sha = digest(VALIDATOR)
    snapshot = {
        "snapshot_id": "i0c-r5o", "revision": "r5o", "phase": "i0c",
        "status": "i5_1_scenarios_verified", "business_accepted": True,
        "parent_snapshot": {"snapshot_id": "i0c-r5n", "path": str(parent.relative_to(ROOT)),
                            "sha256": digest(parent.relative_to(ROOT))},
        "supersedes_validator_sha256": r5n["binding"]["freeze_validator"][VALIDATOR],
        "binding": {
            "i5_1_backfill_state": {TASKS: digest(TASKS), CLAIMS: digest(CLAIMS)},
            "i5_1_evidence": {rel: digest(rel) for rel in EVIDENCE},
            "previous_effective_bindings": {PREV: digest(PREV)},
            "freeze_validator": {VALIDATOR: new_validator_sha},
        },
        "corrections": {
            "i5_1_execution": "I5-1 四场景复核按 r5n 批准范围（全四场景×全部 8 活动源）执行全绿："
                              "场景一同源同版本重跑 8/8 幂等（逐源 build_id/units/chunks 与 I4-4 基线全等、"
                              "发布幂等、rebuild-plan 全 reuse）；场景二源变化隔离环境（6 in_scope 新 source_id "
                              "产物与 v1 全等、2 dev lane 副本白名单外拒绝、4 gap 源 check 阻断 fail-closed 且 "
                              "v1 保持活动）；场景三新规则 build 全量重解析（reparse_reason=rule_or_source_mismatch，"
                              "reader spy 8/8，8/8 新 build_id，4 直接源 gen2 活动切换、4 gap 源 fail-closed 保持 v1）；"
                              "场景四复用解析重建索引（reader spy=0、检查点逐字段未动、8/8 新 build_id、search_text "
                              "多重集全等、MD 单因 index_rev 翻转归因核验）。发现 F1：_parse_rev_for 组装在新解析路径"
                              "（ReaderResult.extractor_rev 带 <lib>-<version> 后缀）与检查点复用路径（extractor_rev_for() "
                              "回填裸 rev）不对称，检查点有效重跑下 7/8 动态 rev 源（6 PDF+DOCX）build_id 翻转"
                              "（内容全等的版本翻新）；I2 重跑探针源为单一 MD（静态 rev）故与 F1 零矛盾、仅未覆盖"
                              "动态 rev 格式；F1 修复属冻结代码变更须另提 U 裁定，裁定前生产重跑不得依赖"
                              "「重跑得同 build_id」，I5-2 维护说明须纳入 F1 重跑语义。",
            "arch_doc_revert": "2026-09-24 14:24 架构文档 docs/plan/corpus-ingestion-rebuild-architecture.md "
                               "被外部 markdown 格式化（表格补齐+下划线/星号转义，忽略空白的 diff 176 行但零内容变化）"
                               "致 i0c 冻结链校验失败（region_docs 期望哈希==git HEAD）；经 U 裁定回滚格式化"
                               "（git checkout 恢复 HEAD 字节），校验器复绿 CURRENT r5n 后方继续 r5o 落章；"
                               "事件已在 tasks.md §0 与 i51-summary-report.json incident 节登记。",
            "rebind_scope": "仅重绑 docs/plan/corpus-ingestion-rebuild-tasks.md（"
                            f"{prev[TASKS][:8]}…→{digest(TASKS)[:8]}…）与 "
                            f"docs/plan/claims-market-closed-loop-plan.md（{prev[CLAIMS][:8]}…→{digest(CLAIMS)[:8]}…）、"
                            f"验证器自哈希（{prev[VALIDATOR][:8]}…→{new_validator_sha[:8]}…，新增 r5o 节/banner/summary）"
                            "与新增 i5-1 五件证据（summary+s1+s2+s3+s4 报告）；不借机触碰实现/测试/守卫/金标字节。",
        },
        "notes": [
            "r5o 为 I5-1 执行入链修订（parent=i0c-r5n）：不触碰 i0c-r5n 及更早快照的已冻结字节（追加式索引纪律）。",
            f"archive-first：before-r5o/ 保存两份计划文档的重绑后字节（r5g/r5h/r5i/r5n 先例）与验证器改前字节"
            f"（sha256 == i0c-r5n freeze_validator 绑定 {prev[VALIDATOR][:8]}…）。",
            "F1 已登记待 U 裁定（不改冻结代码）；隔离库 i51_s1_rerun/i51_s2_srcchg/i51_s3_newrule/"
            "i51_s4_idxreb 用后待处置；I5-2/I5-3 待 F1 裁定后另行启动。",
        ],
        "m5_declaration": "not_declared",
    }
    target.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest_path = FREEZES / "freeze-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["snapshots"].append({"created_at": now, "file": target.name,
                                  "parent_snapshot_id": "i0c-r5n", "sha256": digest(target.relative_to(ROOT)),
                                  "snapshot_id": "i0c-r5o"})
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return subprocess.run([sys.executable, str(FREEZES / "validate_i0c_freeze.py")], cwd=ROOT).returncode


if __name__ == "__main__":
    raise SystemExit(main())
