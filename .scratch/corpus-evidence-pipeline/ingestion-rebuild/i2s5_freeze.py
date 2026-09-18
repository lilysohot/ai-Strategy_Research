"""生成 i0c-r6 冻结快照（I2-5 publication_pg 真库门交付）。

write-once（open('x')）：已存在即拒绝追加式为操作失误。生成后把新条目写进
freeze-manifest.json 索引（追加式，不追改历史条目），随后由
``validate_i0c_freeze.py`` 核验血缘与绑定。

用法::

    uv run python .scratch/corpus-evidence-pipeline/ingestion-rebuild/i2s5_freeze.py
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

SNAPSHOT_ID = "i0c-r6"
PARENT_ID = "i0c-r5"

# 绑定范围 = i0c-r5 全部路径（实时重算）+ 本轮新增/改动路径。
GROUPS: dict[str, tuple[str, ...]] = {
    "implementation": (
        "plugins/corpus/_semantic_validation.py",
        "plugins/corpus/audit.py",
        "plugins/corpus/claims_detail.py",
        "plugins/corpus/evidence.py",
        "plugins/corpus/evidence_pipeline.py",
        "plugins/corpus/fetch.py",
        "plugins/corpus/material_semantics.py",
        "plugins/corpus/metadata.py",
        "plugins/corpus/preparation/engine.py",
        "plugins/corpus/preparation/repository.py",  # I2-5 修复：PUBLISHED 重激活预算
        "plugins/corpus/preparation/repository_pg.py",  # I2-5 修复：J1/J2/fencing 次序
        "plugins/corpus/preparation/search_pg.py",
        "plugins/corpus/service.py",  # 导入卫生清理（I2-7 遗留）
        "scripts/corpus_holdout_eval.py",
        "scripts/truncation_ab.py",
        "scripts/truncation_metrics.py",
    ),
    "tests": (
        "tests/test_corpus_a1_ingest_search.py",
        "tests/test_corpus_claims.py",
        "tests/test_corpus_claims_detail.py",
        "tests/test_corpus_claims_interface.py",
        "tests/test_corpus_evidence_pipeline.py",
        "tests/test_corpus_layout_recovery.py",
        "tests/test_corpus_material_semantics.py",
        "tests/test_corpus_metadata.py",
        "tests/test_corpus_preparation_admission.py",
        "tests/test_corpus_preparation_chunk.py",
        "tests/test_corpus_preparation_clean.py",
        "tests/test_corpus_preparation_contract.py",
        "tests/test_corpus_preparation_engine.py",
        "tests/test_corpus_preparation_publication_pg.py",  # I2-5 新增测试族
        "tests/test_corpus_preparation_readers.py",
        "tests/test_corpus_preparation_repository_pg.py",
        "tests/test_corpus_preparation_source.py",
        "tests/test_corpus_search.py",
        "tests/test_p0a_acceptance.py",
    ),
    "docs": (
        "docs/plan/README.md",
        "docs/plan/claims-market-closed-loop-plan.md",
        "docs/plan/corpus-ingestion-rebuild-architecture.md",
        "docs/plan/corpus-ingestion-rebuild-tasks.md",
    ),
    "freeze_validator": (
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/validate_i0c_freeze.py",
    ),
    "guards": (
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i2-verify.json",
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i2-verify-guard-report.json",
    ),
    "docker_pg": (
        "docker/Dockerfile.corpus-db",
        "docker/docker-compose.yml",
        "docker/initdb/00-extensions.sql",
    ),
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fail(message: str) -> None:
    print(f"I2-5 FREEZE FAILED: {message}")
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
        "revision": "r6",
        "phase": "i0c",
        "task": (
            "I2-5 publication_pg: real-PG dual worker / lease takeover / concurrent "
            "publish gate (13 cases) + store defect fixes J1/J2/lease_lost ordering/"
            "max_attempts"
        ),
        "binding": binding,
        "corrections": {
            "I2-5": (
                "publication_pg 真库门交付：13 用例覆盖双 worker 并发 acquire/register/"
                "过期接管、真实停顿越过 TTL 的接管、陈旧 token 迟到提交（put_units/put_chunks/"
                "heartbeat/finish/publish）、提交丢响应幂等、cancelled 不复活且 PUBLISHED 例外、"
                "max_attempts 三条路径边界、并发发布与 retire 竞态、失败阶段恢复、index_rev 升级"
                "重建与读侧切换；证据：真库 31 passed（含 I2-2/I2-3 既有 18）、普通环境 312 passed"
                " / 1 skipped、i1 守卫 env 186 passed、ruff/pyright/import_smoke 356/356。"
            ),
            "J1": (
                "job 逻辑键互斥：register/acquire 的行锁无法阻止并发 INSERT（并发 register 抛 "
                "psycopg UniqueViolation 而非 StoreError；并发接管生成重复 attempt 行）→ "
                "register_job/acquire_job/heartbeat_job/finish_job 事务首语句取 "
                "pg_advisory_xact_lock(job_ns, build_id:stage)。"
            ),
            "J2": (
                "source 级发布互斥：publication 行不存在时并发发布各自按『无行』算 generation=1，"
                "后提交者以陈旧值覆盖，实测丢掉一次递增（期望 2 实得 1）→ publish/retire 取 "
                "pg_advisory_xact_lock(pub_ns, source_id)。"
            ),
            "lease_lost": (
                "fencing 判定次序：_require_ownership 改为 owner/token 不匹配先判 lease_lost，"
                "再判状态与过期——接管并结束后旧 worker 迟到写入必须得到同一 lease_lost 语义。"
            ),
            "max_attempts": (
                "PUBLISHED 终态重新取得租约不受重试预算约束（违反 §8.1.2）→ PgStore 与 MemoryStore "
                "双 Adapter 同步收敛为 attempt >= max_attempts 即拒绝。"
            ),
            "import_hygiene": (
                "清理 I2-7 遗留：plugins/corpus/audit.py（函数内未用 dict_row 导入 + 导入块排序）"
                "与 plugins/corpus/service.py（导入块排序）——CI lint 范围此前 3 项 F401/I001 失败，"
                "现恢复 All checks passed；属 I2-7 交付物的字节变更，由本修订重绑。"
            ),
        },
        "notes": [
            "i0c-r5 保留历史字节，不追改；本修订登记 I2-5 交付与四处 store 缺陷修复。",
            "绑定为当前最新状态（r5 全量路径实时重算 + repository.py 与新测试族），由 "
            "validate_i0c_freeze.py 按 latest-revision-wins 合并为 i0c-current 后逐一核验。",
            "I2-5 后待执行：I2-8（消费者接线二）、I2-4（CLI 六职责）、I2-6（authority/cli_isolation）；"
            "M5 仍 not_declared；生产库 I4 前零写入。",
            "真实停顿类用例使用 LeaseConfig(3,1,6,3)（heartbeat=1 ≤ TTL/3）；冻结运行参数 "
            "LeaseConfig(300,60,600,3) 未改动。",
        ],
        "m5_declaration": (
            "not_declared（I2-1/I2-2/I2-3/I2-5/I2-7 完成；仍需 I2-8/I2-4/I2-6 后方可声明 M5）"
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
    print(f"bindings: " + ", ".join(f"{g}={len(v)}" for g, v in binding.items()))


if __name__ == "__main__":
    main()
