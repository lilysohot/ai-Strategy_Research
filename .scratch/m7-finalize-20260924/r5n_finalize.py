"""r5n 落章：M7 放行签认入链 + M8 启动（I5-1 验证范围批准）。"""
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
PREV = (".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260923-i4-window/"
        "previous-effective-bindings-r5n.json")
SIGNOFF_MD = ".scratch/m7-rereview-20260924/signoff-record-m7.md"
SIGNOFF_JSON = ".scratch/m7-rereview-20260924/signoff-record-m7.json"


def digest(rel: str) -> str:
    return hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()


def main() -> int:
    target = FREEZES / "i0c-r5n.json"
    if target.exists():
        raise SystemExit(f"write-once snapshot already exists: {target}")
    parent = FREEZES / "i0c-r5m.json"
    r5m = json.loads(parent.read_text(encoding="utf-8"))
    now = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%dT%H:%M:%S+08:00")
    snapshot = {
        "snapshot_id": "i0c-r5n", "revision": "r5n", "phase": "i0c",
        "status": "m7_release_signoff", "business_accepted": True,
        "parent_snapshot": {"snapshot_id": "i0c-r5m", "path": str(parent.relative_to(ROOT)),
                            "sha256": digest(parent.relative_to(ROOT))},
        "supersedes_validator_sha256": r5m["binding"]["freeze_validator"][VALIDATOR],
        "binding": {
            "m7_signoff_record": {SIGNOFF_MD: digest(SIGNOFF_MD),
                                  SIGNOFF_JSON: digest(SIGNOFF_JSON)},
            "m7_release_state": {
                "docs/plan/corpus-ingestion-rebuild-tasks.md":
                    digest("docs/plan/corpus-ingestion-rebuild-tasks.md"),
                "docs/plan/claims-market-closed-loop-plan.md":
                    digest("docs/plan/claims-market-closed-loop-plan.md")},
            "previous_effective_bindings": {PREV: digest(PREV)},
            "freeze_validator": {VALIDATOR: digest(VALIDATOR)},
        },
        "corrections": {
            "m7_signoff": "U（xyl）2026-09-24 具名签认：M7 放行。放行三要件全部达成——①I4 窗口执行完毕"
                          "（I4-3→I4-6→I4-2→I4-7→I4-4→I4-5 全绿；reset 阶段 1 七表 + 阶段 2 六表 TRUNCATE "
                          "五门全过，旧九表归零、保留序列与见证不变）；②独立复核闭环（m7-review-20260924 六项"
                          "整改 G1/S1/G2/S2/G3/G4 + m7-rereview-20260924 F1–F3 修复验证 m7-finalize-20260924）；"
                          "③U 具名签认（signoff-record-m7.{md,json}，r5c/r30 先例：具名签认入链）。随签认登记"
                          "已知项：stats/list_documents 迁移残留（归 I5-3 处置）、全仓 2 既有 failed 与 49 skip "
                          "同复核基线、abstain=on 正例拒检为 M6 签认已知限制。",
            "m8_kickoff": "同日 U 裁定开启 M8（I5 增量与运维），I5-1 验证范围批准为全四场景 × 全部 8 个活动源"
                          "（同源同版本重跑、源变化、新规则 build、复用解析重建索引；源变化/新规则/复用解析在"
                          "隔离环境执行，不触碰生产活动来源），与 I2/I3 同场景结果对照。I5-1 执行结果另行回填。",
            "rebind_scope": "仅重绑 docs/plan/corpus-ingestion-rebuild-tasks.md（65c82154…→4a6980f4…）与 "
                            "docs/plan/claims-market-closed-loop-plan.md（61a27f8e…→644f3302…）、验证器自哈希"
                            "（334e0a17…→0d71b3f9…，新增 r5n 节/banner/summary）与新增签认证据两件"
                            "（signoff-record-m7.{md,json}）；不借机触碰实现/测试/守卫/金标字节。",
        },
        "notes": [
            "r5n 为 M7 放行入链修订（parent=i0c-r5m）：不触碰 i0c-r5m 及更早快照的已冻结字节（追加式索引纪律）。",
            "archive-first：before-r5n/ 保存两份计划文档的重绑后字节（r5g/r5h/r5i 先例）与验证器改前字节"
            "（sha256 == i0c-r5m freeze_validator 绑定 334e0a17…）。",
            "M7 放行三要件：I4 窗口执行通过 + 独立复核闭环 + U（xyl）具名签认——本修订后全部达成；"
            "I5 执行与放行按 §3.8 门另行回填与复核。",
        ],
        "m5_declaration": "not_declared",
    }
    target.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest_path = FREEZES / "freeze-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["snapshots"].append({"created_at": now, "file": target.name,
                                  "parent_snapshot_id": "i0c-r5m", "sha256": digest(target.relative_to(ROOT)),
                                  "snapshot_id": "i0c-r5n"})
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return subprocess.run([sys.executable, str(FREEZES / "validate_i0c_freeze.py")], cwd=ROOT).returncode


if __name__ == "__main__":
    raise SystemExit(main())
