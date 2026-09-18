"""生成 i0c-r9 冻结快照（I2-8 消费者接线二 + I2-4 CLI 六职责）。

write-once（open('x')）：已存在即拒绝。生成后追加 freeze-manifest 索引条目，
随后由 ``freezes/validate_i0c_freeze.py`` 核验血缘（r9→r8→…→i1-r4→i0a5）与绑定。

用法::

    uv run python .scratch/corpus-evidence-pipeline/ingestion-rebuild/i2s8_i2s4_freeze.py
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent
FREEZES = BASE / "freezes"
ROOT = BASE.parents[2]  # ingestion-rebuild → corpus-evidence-pipeline → .scratch → 仓库根

SNAPSHOT_ID = "i0c-r9"
PARENT_ID = "i0c-r8"

GROUPS: dict[str, tuple[str, ...]] = {
    "implementation": (
        "plugins/corpus/cli.py",
        "plugins/corpus/audit.py",
        "plugins/corpus/service.py",
        "plugins/corpus/preparation/read_pg.py",
        "plugins/corpus/preparation/search_pg.py",
        "plugins/corpus/preparation/engine.py",
        "plugins/corpus/preparation/repository_pg.py",
        "plugins/tools/corpus_search.py",
        "plugins/tools/corpus_fetch.py",
    ),
    "tests": (
        "tests/test_corpus_consumers_pg.py",
        "tests/test_corpus_cli.py",
        "tests/test_corpus_cli_pg.py",
        "tests/test_corpus_coverage.py",
    ),
    "docs": (
        "docs/plan/claims-market-closed-loop-plan.md",
        "docs/plan/corpus-ingestion-rebuild-tasks.md",
    ),
    "freeze_validator": (
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/validate_i0c_freeze.py",
    ),
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fail(message: str) -> None:
    print(f"I2-8/I2-4 FREEZE FAILED: {message}")
    sys.exit(1)


def main() -> None:
    manifest_path = FREEZES / "freeze-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    parents = {entry["snapshot_id"]: entry for entry in manifest.get("snapshots", [])}
    if PARENT_ID not in parents:
        fail(f"索引缺少父快照 {PARENT_ID}")
    if SNAPSHOT_ID in parents:
        fail(f"{SNAPSHOT_ID} 已存在（write-once：不得重发或覆盖）")

    parent_file = FREEZES / parents[PARENT_ID]["file"]
    if not parent_file.is_file() or digest(parent_file) != parents[PARENT_ID]["sha256"]:
        fail(f"{PARENT_ID} 文件字节与索引哈希不一致")

    binding: dict[str, dict[str, str]] = {}
    for group, paths in GROUPS.items():
        table: dict[str, str] = {}
        for rel in paths:
            file = ROOT / rel
            if not file.is_file():
                fail(f"绑定文件缺失: {rel}")
            table[rel] = digest(file)
        binding[group] = table

    created_at = datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")
    snapshot = {
        "snapshot_id": SNAPSHOT_ID,
        "revision": "r9",
        "phase": "i0c",
        "task": (
            "I2-8 consumer wiring (2) + I2-4 CLI six duties: version handles "
            "cv2:<build_id>/chunk:<chunk_id>, archive_required for legacy handles, "
            "coverage three axes, new-chain audit, CLI plan/build/check/publish/"
            "status/rebuild-plan with exit codes and operator record"
        ),
        "binding": binding,
        "corrections": {
            "I2-8": (
                "消费者接线（二）：新增 preparation/read_pg.py 作为读侧唯一权威入口——"
                "句柄 cv2:<build_id> + chunk:<chunk_id>、跨发布取回原 build、旧句柄 "
                "LegacyHandleError(archive_required)、跨 build/坏哈希 UnknownHandleError、"
                "来源撤销 WithdrawnError、§7.3 coverage_snapshot 三轴；service.py 增加读链"
                "判定（CORPUS_READ_CHAIN=new|legacy|auto）并把 search/fetch/文档级读取/"
                "source_resolver/coverage 迁到新链（旧句柄不静默换正文）；search_pg 命中"
                "增加 snippet/published；tools corpus_search/corpus_fetch 返回版本句柄与"
                "coverage 对象，空命中改述『当前已发布范围无匹配』；audit.py 新增 "
                "audit_corpus_chain（活动版本决定/执行台账/引用闭合）并纳入 run_audit 冲突。"
            ),
            "I2-4": (
                "CLI 六职责：新增 plugins/corpus/cli.py（plan/build/check/publish/status/"
                "rebuild-plan），一律复用正式编排——check 调新增公开门 "
                "engine.check_build_publishable（与 publish 第 3 步同一实现），rebuild-plan "
                "用新增 engine.current_revs() 与引擎同公式重算 parse_rev；publish 必填 "
                "--operator 且操作者/generation 落 PUBLISHED job 检查点（publish-record-1）；"
                "退出码 0/2/3/4/5 显式区分（目标拒绝以『拒绝』前缀路由到 3）。"
            ),
            "coverage": (
                "§7.3 三轴：search 空命中返回 query_status=no_match 且 availability=unknown，"
                "不自动转 absent；test_corpus_coverage 的旧『coverage==none』断言按新契约"
                "更新为 coverage 对象断言（契约升级而非放宽）。"
            ),
            "golden_deferred": (
                "golden.py 按 design-review 消费者矩阵路由 I3-5（retire_after_i3），"
                "本轮未迁移、未以新链验收替代，如实登记。"
            ),
        },
        "notes": [
            "i0c-r8 保留历史字节，不追改；本修订登记 I2-8/I2-4 交付与读侧/CLI 新接口。",
            "supersession 沿用：本修订绑定的路径由合并后的 i0c-current 按新哈希核验。",
            "I2-8 后待执行：I2-6（authority + cli_isolation；前置 I2-4/8/5 已齐）；"
            "M5 仍 not_declared；生产库 I4 前零写入。",
            "真库门 run 环境为 i2-verify 守卫 env + env -u PYTHONPATH（去宿主 IDE sitecustomize），"
            "写入仅限 i2_sandbox_corpus 的 corpus schema。",
        ],
        "m5_declaration": (
            "not_declared（I2-1/2/3/4/5/7/8 完成；仍需 I2-6 与独立复核后方可声明 M5）"
        ),
        "created_at": created_at,
        "parent_snapshot": {
            "snapshot_id": PARENT_ID,
            "path": f".scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/{parent_file.name}",
            "sha256": digest(parent_file),
        },
    }

    target = FREEZES / f"{SNAPSHOT_ID}.json"
    with target.open("x", encoding="utf-8") as handle:
        json.dump(snapshot, handle, ensure_ascii=False, indent=2, sort_keys=False)
        handle.write("\n")

    manifest.setdefault("snapshots", []).append(
        {
            "snapshot_id": SNAPSHOT_ID,
            "file": target.name,
            "sha256": digest(target),
            "parent_snapshot_id": PARENT_ID,
            "created_at": created_at,
        }
    )
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"{SNAPSHOT_ID} frozen: {target} sha256={digest(target)}")
    print("bindings: " + ", ".join(f"{group}={len(v)}" for group, v in binding.items()))


if __name__ == "__main__":
    main()
