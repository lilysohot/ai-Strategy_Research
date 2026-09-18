"""生成 i0c-r7 冻结快照（I2-3/I2-7 独立审核 R1—R6 整改）。

write-once（open('x')）：已存在即拒绝追加式为操作失误。生成后把新条目写进
freeze-manifest.json 索引（追加式，不追改历史条目），随后由
``validate_i0c_freeze.py`` 核验血缘与绑定。

本次整改范围（audits/20260917-i23-i27-review）：
- R3：service.py 内容寻址短路仅在无显式 review_decision_ids 时生效；
- R4：publication.py 只认显式报告日期声明（文件名/事件日期不构成发布依据）；
- R5：chunk/search_pg 共享 normalize_search_text（% 与全角 ％），index_rev 升 index-3；
- R2：service.py document_text/fetch/blocks_of 对 cv2: 句柄读 corpus_units，不查旧 blocks；
- R1：evidence_pipeline.build_evidence_run_from_units 投影函数（extract_claims 接线待后续）；
- R6：补绑定 publication.py 与 test_corpus_preparation_publication.py。

用法::

    uv run python .scratch/corpus-evidence-pipeline/ingestion-rebuild/i0c_r7_freeze.py
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

SNAPSHOT_ID = "i0c-r7"
PARENT_ID = "i0c-r6"

# 本轮改动/新增路径（latest-revision-wins 合并进 i0c-current）。
GROUPS: dict[str, tuple[str, ...]] = {
    "implementation": (
        "plugins/corpus/preparation/publication.py",  # R6：此前从未绑定，现补
        "plugins/corpus/preparation/chunk.py",  # R5：normalize_search_text
        "plugins/corpus/preparation/search_pg.py",  # R5：查询侧 % 归一化
        "plugins/corpus/preparation/engine.py",  # R5：INDEX_REV_V3
        "plugins/corpus/service.py",  # R3 短路 + R2 基础读取迁移
        "plugins/corpus/evidence_pipeline.py",  # R1：build_evidence_run_from_units
    ),
    "tests": (
        "tests/test_corpus_preparation_publication.py",  # R6：此前从未绑定，现补
        "tests/test_corpus_preparation_chunk.py",  # R5：normalize_search_text 用例
        "tests/test_corpus_metadata.py",  # R4：ingest 钩子显式报告日期
        "tests/test_corpus_preparation_publication_pg.py",  # R5：INDEX_REV_V3
        "tests/test_corpus_preparation_repository_pg.py",  # R5：INDEX_REV_V3
        "tests/test_corpus_claims_interface.py",  # R1：extract_claims units 投影接线
        "tests/test_corpus_evidence_pipeline.py",  # R1：roundtrip 改走 build_evidence_run
    ),
    "freeze_validator": (
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/validate_i0c_freeze.py",
    ),
    "docs": (
        # i0c-r6 冻结后这四个计划文档被外部/本轮改动，全部按当前字节重绑，避免
        # 逐个追 staleness（tasks.md 本轮回填台账；claims-market 被外部更新）。
        "docs/plan/README.md",
        "docs/plan/claims-market-closed-loop-plan.md",
        "docs/plan/corpus-ingestion-rebuild-architecture.md",
        "docs/plan/corpus-ingestion-rebuild-tasks.md",
    ),
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fail(message: str) -> None:
    print(f"I0C-R7 FREEZE FAILED: {message}")
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
        "revision": "r7",
        "phase": "i0c",
        "task": (
            "I2-3/I2-7 independent review remediation (audits/20260917-i23-i27-review): "
            "R3 short-circuit re-evaluation, R4 publication-date explicit declaration, "
            "R5 FTS %/fullwidth normalization + index_rev v3, R2 basic read migration "
            "to corpus_units, R1 evidence projection function, R6 binding completion"
        ),
        "binding": binding,
        "corrections": {
            "R3": (
                "service._ingest_via_engine 内容寻址短路仅在无显式 review_decision_ids 时生效："
                "调用方显式传入新审核决定（新排除/缩小范围/新 index_rev 重评）必须走 plan/engine "
                "求值新决定，不得被旧活动发布静默跳过（同源身份稳定 ≠ 处理状态/范围/版本不变）。"
            ),
            "R4": (
                "probe_report_publication 只认原文显式报告日期声明（报告发布日期/发布日期/出具日期/"
                "落款日期等字段）：文件名日期前缀与正文历史事件日期（成立日/财报截止日/回顾）不再构成"
                "发布依据；无显式声明落 unknown。title 字段不再参与日期判定。"
            ),
            "R5": (
                "chunk.normalize_search_text（% 与全角 ％ → 空格）为写侧与查询侧同一规范化契约；"
                "search_pg.search_chunks 查询侧经该函数归一化，修复写侧已规范化而查询侧 token 不一致"
                "的百分比漏召回。索引文本规则变更（新增 ％）→ index_rev 由 index-2-zhcfg-2 升 "
                "index-3-zhcfg-2（INDEX_REV_V3），进入 build_id 全量重建。"
            ),
            "R2": (
                "document_text/fetch/blocks_of 对 cv2:<source_id> 新式句柄改读 corpus.corpus_units "
                "（经 corpus_publications.active_build_id），不再查旧 blocks；旧句柄显式走旧 blocks "
                "归档路径（I2-8 精确版本句柄/归档策略前保留），不静默互换正文。"
            ),
            "R1": (
                "extract_claims 由同源 corpus_units 投影（evidence_pipeline.build_evidence_run_from_"
                "units），不再二次解析原文件：source_id 由字节决定、units 经 _active_build_units 取、"
                "发布日期读 admission.report_publication（_active_report_publication，R4 唯一落点）、"
                "标题/主体由文件名+正文派生。parse_evidence 的 PDF/DOCX/MD 解析退出 canonical 入口；"
                "test_corpus_claims_interface.py 服务夹具改为模拟已入链 units + admission，"
                "test_corpus_evidence_pipeline.py roundtrip 改走 build_evidence_run（其 scratch schema "
                "无 corpus schema）。"
            ),
            "R6": (
                "补绑定 plugins/corpus/preparation/publication.py 与 tests/test_corpus_preparation_"
                "publication.py（此前从未进入绑定，engine 已导入使用前者）。validate_i0c_freeze.py "
                "新增 i0c-r7 校验与血缘；新增模块漂移反例由 review 探针覆盖。"
            ),
        },
        "notes": [
            "i0c-r6 保留历史字节，不追改；本修订登记 R1—R6 整改（部分交付：R1 接线待独立复核）。",
            "绑定为当前最新状态（本轮改动/新增路径实时重算），由 validate_i0c_freeze.py 按 "
            "latest-revision-wins 合并为 i0c-current 后逐一核验。",
            "R5 变更了索引文本规则（新增 ％ 归一化），index_rev 已升 index-3-zhcfg-2（INDEX_REV_V3），"
            "存量 build 的 search_tsv/GIN 需以新 index_rev 重建后才与查询侧一致。",
            "M5 仍 not_declared；生产库 I4 前零写入；I2-8/I2-4/I2-6 未完成。",
        ],
        "m5_declaration": "not_declared（I2-1/I2-2/I2-3/I2-5/I2-7 完成；仍需 I2-8/I2-4/I2-6）",
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
    print("bindings: " + ", ".join(f"{g}={len(v)}" for g, v in binding.items()))


if __name__ == "__main__":
    main()
