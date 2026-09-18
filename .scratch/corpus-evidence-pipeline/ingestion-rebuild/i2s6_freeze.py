"""生成 i0c-r13 冻结快照：I2-6（authority + cli_isolation）。

write-once；生成后追加 freeze-manifest 条目，由 validate_i0c_freeze.py 核验血缘
（r13→r12→…→i1-r4→i0a5）与绑定。历史快照字节不改写。

用法::

    uv run python .scratch/corpus-evidence-pipeline/ingestion-rebuild/i2s6_freeze.py
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent
FREEZES = BASE / "freezes"
ROOT = BASE.parents[2]

SNAPSHOT_ID = "i0c-r13"
PARENT_ID = "i0c-r12"

GROUPS: dict[str, tuple[str, ...]] = {
    "implementation": (
        "plugins/corpus/preparation/read_pg.py",
        "plugins/corpus/service.py",
    ),
    "tests": (
        "tests/test_corpus_authority_pg.py",
        "tests/test_corpus_cli_isolation.py",
        "tests/test_corpus_consumers_pg.py",
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
    print(f"I2-6 FREEZE FAILED: {message}")
    sys.exit(1)


def main() -> None:
    manifest_path = FREEZES / "freeze-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    parents = {entry["snapshot_id"]: entry for entry in manifest.get("snapshots", [])}
    if PARENT_ID not in parents:
        fail(f"索引缺少父快照 {PARENT_ID}")
    if SNAPSHOT_ID in parents:
        fail(f"{SNAPSHOT_ID} 已存在（write-once）")
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
        "revision": "r13",
        "phase": "i0c",
        "task": (
            "I2-6 authority + cli_isolation: one authoritative read Interface for all "
            "consumers, integrity gates (content hash on chunk/document/cell, dangling "
            "unit refs, cell lookup), evidence-copy authority fingerprint, real CLI "
            "subprocess isolation with zero-model and network allowlist traps"
        ),
        "binding": binding,
        "corrections": {
            "I2-6": (
                "新增 authority 族（tests/test_corpus_authority_pg.py，8 用例）与 cli_isolation 族"
                "（tests/test_corpus_cli_isolation.py，5 用例）：真库逐项对照 ground truth 证明所有"
                "消费者接同一权威 Interface；真实 CLI 子进程（守卫注入引导）往返、重启续跑、退出码、"
                "模型陷阱、网络允许清单、旧句柄拒绝。"
            ),
            "authority": (
                "同一权威 Interface 真库实测：fetch_verbatim/fetch/document_text/source_resolver/"
                "fetch_cell/工具层/审计读出同一份 corpus_units.raw_text。"
            ),
            "integrity_hash": (
                "读侧补齐内容哈希核验：chunk 取回、文档级取回、cell 取回三路均核 content_hash；"
                "**文档级原先不核哈希**（本任务新发现：被篡改单元会作为文档正文外流并被 verify "
                "采用），现已拒绝。引用悬空（chunk 指向不存在单元）抛 IntegrityError，不返回"
                "「其余部分」。"
            ),
            "fetch_cell": (
                "新增 read_pg.fetch_cell / service.fetch_cell：按 (页,行,列) 取权威单元格；"
                "错 cell、定位不唯一、哈希不符一律拒绝。"
            ),
            "evidence_authority": (
                "新增 service.verify_evidence_against_authority：证据副本的 units 指纹"
                "（parse_rev = f(source_id, 投影版本, units 文本序列)）必须与权威集合一致；"
                "自洽但内容不符的 JSONB 副本/导出件在 load 时拒绝。"
            ),
            "cli_isolation": (
                "真实 CLI 子进程隔离：build→check→publish(operator)→status 往返、重跑幂等复用、"
                "退出码 2/3/5、openai 客户端 import/构造被守卫拒绝、非允许地址连接被拒而 "
                "127.0.0.1:543 放行、旧句柄 LegacyHandleError 不兜底。"
            ),
        },
        "notes": [
            "i0c-r9～r12 保留历史字节，不追改；本修订登记 I2-6 交付。",
            "I2 全部任务（I2-1～I2-8）交付完毕；M5 技术门条件已齐（M3+M4+I2 全完成、"
            "publication_pg/authority/cli_isolation 真库零 skip），按纪律待独立复核 + U 签认后声明。",
            "真库动作仅限 i2_sandbox_corpus 的 corpus schema；生产库 I4 前零写入。",
        ],
        "m5_declaration": (
            "conditions_met_pending_review（I2 全部完成；M5 待独立复核 + U 签认，本轮不自我宣告）"
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
