"""r5j Phase C（落章）：tasks.md 归档拷贝 + i0c-r5j.json 写入 + manifest 追加 + 验证器 exit 0。

前置（Phase A/B 已完成）：before-r5j/ 归档（7 件 + validator）、
previous-effective-bindings-r5j.json、验证器 r5j 节、tasks.md §0 回填。
本脚本：
1. 拷贝回填后 tasks.md → before-r5j/（r5j 节检查归档==重绑后字节，r5g 先例）；
2. 按验证器 r5j 节六个 binding 组计算磁盘哈希（修复后/回填后/扩展后字节）；
3. 写 freezes/i0c-r5j.json（parent=r5i 实测哈希、supersedes=r5i 绑定 validator 哈希）；
4. freeze-manifest.json 追加 i0c-r5j 条目（幂等：重跑先移除旧条目）；
5. 运行验证器，要求 exit 0 且打印 CURRENT r5j。
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path("/home/administrator/FrontierAgent")
WIN = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260923-i4-window"
FRZ = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes"
HERE = ROOT / ".scratch/m7-fix-20260924"

CODE = [
    "plugins/corpus/service.py",
    "plugins/corpus/preparation/read_pg.py",
    "plugins/corpus/preparation/search_pg.py",
    "plugins/corpus/preparation/cross_boundary.py",
    "plugins/corpus/cli.py",
]
TESTS = ["tests/test_corpus_consumers_pg.py", "tests/test_corpus_ingest_retired.py"]
EVIDENCE = [
    ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260923-i4-window/report.md",
    ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i4-reset-manifest.json",
    ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i4-cutover-manifest.json",
    ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260923-i4-window/i47-reset-phase1-report.json",
    ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260923-i4-window/i44-rebuild-report.json",
    ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260923-i4-window/i45_tool_roundtrip.py",
    ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260923-i4-window/i45-tool-roundtrip.json",
    ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260923-i4-window/i4c_reset_phase2.py",
    ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260923-i4-window/i4c-reset-phase2-report.json",
]
STATE = ["docs/plan/corpus-ingestion-rebuild-tasks.md"]
PREV = (".scratch/corpus-evidence-pipeline/ingestion-rebuild/"
        "audits/20260923-i4-window/previous-effective-bindings-r5j.json")
VALIDATOR = ".scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/validate_i0c_freeze.py"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    now = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%dT%H:%M:%S+08:00")

    # 0) 前置 sanity
    for rel in [*TESTS, *EVIDENCE, *STATE, (PREV), (VALIDATOR)]:
        assert (ROOT / rel).is_file(), f"missing: {rel}"
    assert "CORPUS_TARGET_DB=postgres" in (ROOT / ".env").read_text(encoding="utf-8"), "G1 .env 缺交付"
    tasks_text = (ROOT / STATE[0]).read_text(encoding="utf-8")
    for gate in ("20260923-i4-window", "i4c-reset-phase2-report.json", "11762f4e",
                 "暂缓解除", "m7-review-20260924", "m7-fix-20260924", "i0c-r5j"):
        assert gate in tasks_text, f"tasks.md 语义门缺失: {gate}"

    # 1) tasks.md 归档拷贝（回填后字节即重绑来源）
    before = WIN / "before-r5j"
    archived_tasks = before / STATE[0]
    archived_tasks.parent.mkdir(parents=True, exist_ok=True)
    archived_tasks.write_bytes((ROOT / STATE[0]).read_bytes())
    # 归档一致性：改前生效件必须等于 previous-effective-bindings-r5j.json 声明
    prev_map = json.loads((ROOT / PREV).read_text(encoding="utf-8"))
    for rel in prev_map:
        if rel == STATE[0]:
            continue  # tasks.md 走 drift 路径：归档 == 重绑后字节
        assert digest(before / rel) == prev_map[rel], f"archive drift: {rel}"
    assert digest(archived_tasks) == digest(ROOT / STATE[0]), "tasks.md 归档字节失配"
    assert prev_map[STATE[0]] != digest(ROOT / STATE[0]), "tasks.md 重绑必须实际改变绑定"

    # 2) 六组 binding（磁盘现字节）
    binding = {
        "m7_fix_code": {rel: digest(ROOT / rel) for rel in CODE},
        "m7_fix_tests": {rel: digest(ROOT / rel) for rel in TESTS},
        "m7_window_evidence": {rel: digest(ROOT / rel) for rel in EVIDENCE},
        "m7_fix_state": {rel: digest(ROOT / rel) for rel in STATE},
        "previous_effective_bindings": {PREV: digest(ROOT / PREV)},
        "freeze_validator": {VALIDATOR: digest(ROOT / VALIDATOR)},
    }

    # 3) i0c-r5j.json（parent/supersedes 从链文件实测，不手抄）
    r5i_path = FRZ / "i0c-r5i.json"
    r5i = json.loads(r5i_path.read_text(encoding="utf-8"))
    snapshot = {
        "snapshot_id": "i0c-r5j",
        "revision": "r5j",
        "phase": "i0c",
        "status": "m7_review_remediation",
        "business_accepted": True,
        "parent_snapshot": {
            "snapshot_id": "i0c-r5i",
            "path": str(r5i_path.relative_to(ROOT)),
            "sha256": digest(r5i_path),
        },
        "supersedes_validator_sha256": r5i["binding"]["freeze_validator"][VALIDATOR],
        "binding": binding,
        "correction": (
            "M7 external-review remediation frozen: G1 default target delivered via .env "
            "(CORPUS_TARGET_DB=postgres, default-mode acceptance 24/24), S1 target-db "
            "resolution de-cached from import time (service/read_pg/search_pg/cross_boundary/"
            "cli resolve at construction/call time), G2 retired ingest entry fail-closed "
            "(RetiredIngestError + CLI structured rejection, zero-connection regression test), "
            "S2 search() unified on search_with_coverage (r5e product-gate acceptance, "
            "_selected_chunk_hits removed); I4 window key evidence bound first-in-chain "
            "(window report, reset/cutover manifests, phase reports + exec scripts + roundtrip "
            "artifact, G4); frozen PG battery replayed green (search-live 11 / fullchain 12 / "
            "hermetic 78 / d2d6 73) and full-repo pytest 2931 passed / 2 pre-existing failed / "
            "49 skipped. G3 isolated-restore supplementary verification runs separately."
        ),
        "corrections": {
            "m7_review_remediation": (
                "r5j: M7 复核六项修复入链（G1 .env 交付默认目标、S1 目标库解析去 import 缓存、"
                "G2 旧写入口 fail-closed 恒定拒绝（零连接回归）、S2 search() 统一委托 "
                "search_with_coverage；G4 窗口关键证据首次绑定；G3 隔离恢复补验另行执行）；"
                "tasks.md §0 回填重绑（archive-first，r4z/r5g/r5h/r5i 先例）。"
            )
        },
        "created_at": now,
    }
    r5j_path = FRZ / "i0c-r5j.json"
    r5j_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # 4) manifest 追加（幂等）
    manifest_path = FRZ / "freeze-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["snapshots"] = [
        e for e in manifest.get("snapshots", []) if e.get("snapshot_id") != "i0c-r5j"
    ]
    manifest["snapshots"].append({
        "created_at": now,
        "file": "i0c-r5j.json",
        "parent_snapshot_id": "i0c-r5i",
        "sha256": digest(r5j_path),
        "snapshot_id": "i0c-r5j",
    })
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")

    # 5) 验证器（exit 0 + CURRENT r5j 打印）
    proc = subprocess.run([sys.executable, str(FRZ / "validate_i0c_freeze.py")],
                          cwd=ROOT, capture_output=True, text=True)
    out = (proc.stdout + proc.stderr).strip()
    print(out[-3000:])
    if proc.returncode != 0:
        print(f"VALIDATOR FAILED exit={proc.returncode}", file=sys.stderr)
        return proc.returncode
    assert "CURRENT r5j:" in proc.stdout, "验证器未打印 CURRENT r5j"
    (HERE / "r5j-finalize.json").write_text(json.dumps({
        "snapshot_id": "i0c-r5j",
        "created_at": now,
        "snapshot_sha256": digest(r5j_path),
        "binding": binding,
        "validator_stdout_tail": proc.stdout.strip().splitlines()[-3:],
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n[r5j] 落章完成：{r5j_path} sha256={digest(r5j_path)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
