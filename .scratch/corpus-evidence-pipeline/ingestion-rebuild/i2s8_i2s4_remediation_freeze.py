"""生成 i0c-r11 冻结快照：I2-8 / I2-4 独立复核整改（F1—F11 / RM-I28-0～13）。

write-once；生成后追加 freeze-manifest 条目，由 validate_i0c_freeze.py 核验血缘
（r11→r10→…→i1-r4→i0a5）与绑定。历史快照 r9/r10 字节不改写。

用法::

    uv run python .scratch/corpus-evidence-pipeline/ingestion-rebuild/i2s8_i2s4_remediation_freeze.py
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

SNAPSHOT_ID = "i0c-r11"
PARENT_ID = "i0c-r10"

GROUPS: dict[str, tuple[str, ...]] = {
    "implementation": (
        "plugins/corpus/cli.py",
        "plugins/corpus/service.py",
        "plugins/corpus/preparation/read_pg.py",
        "plugins/corpus/preparation/search_pg.py",
        "plugins/corpus/preparation/engine.py",
        "plugins/tools/corpus_search.py",
        "plugins/tools/corpus_fetch.py",
        "plugins/tools/data_coverage.py",
    ),
    "tests": (
        "tests/test_corpus_consumers_pg.py",
        "tests/test_corpus_cli.py",
        "tests/test_corpus_cli_pg.py",
        "tests/test_corpus_coverage.py",
        "tests/test_data_coverage.py",
    ),
    "docs": (
        "docs/plan/claims-market-closed-loop-plan.md",
        "docs/plan/corpus-ingestion-rebuild-tasks.md",
        "docs/plan/corpus-ingestion-rebuild-architecture.md",
    ),
    "freeze_validator": (
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/validate_i0c_freeze.py",
    ),
    "audit_evidence": (
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260918-i2-8-i2-4-review/review.md",
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260918-i2-8-i2-4-review/remediation-checklist.md",
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260918-i2-8-i2-4-review/test_review_probes.py",
    ),
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fail(message: str) -> None:
    print(f"I0C-R11 FREEZE FAILED: {message}")
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
        "revision": "r11",
        "phase": "i0c",
        "task": (
            "I2-8/I2-4 independent-review remediation: handle-version document reads, "
            "withdrawn document signal, coverage publication_snapshot_ref + same-snapshot "
            "search, data_coverage three-axis, fetch spans, legacy chain unreachable, "
            "engine.expected_parse_rev single source, unified exit codes, argparse exit"
        ),
        "binding": binding,
        "corrections": {
            "RM-I28-0": (
                "裁定写入架构 §7.2/§7.3 与 tasks.md I2-8 验收门：①文档级读取遵循句柄 build；"
                "②迁移目标 legacy 读路径不可达。"
            ),
            "F1": (
                "read_pg._DOC_SQL 改为按句柄 build 读取，DocumentEvidence.build_id=实际读取 build；"
                "fetch_document 先核来源当前准入（非 in_scope 抛 WithdrawnError）。"
            ),
            "F2": "撤销后文档级返回 None（不再空串）；零单元 build 仍返回 \"\"，两者可区分。",
            "F3": (
                "coverage 补 publication_snapshot_ref（(source_id,active_build_id,generation) 全集 md5，"
                "与计数同一条 SQL）；新增 read_pg.search_with_coverage：命中与覆盖同一 REPEATABLE READ "
                "事务读取，service/tools 改用组合读取。"
            ),
            "F4": (
                "data_coverage 透出 research_coverage（§7.3 三轴，与市场字段分层，verdict/guidance 不动）；"
                "补普通环境与真库回归并纳入本修订绑定。"
            ),
            "F5": (
                "corpus_fetch 透出 source_ranges（权威 code point）与 spans（text 内偏移，可复算 text）；"
                "引用不存在单元时返回空 text/空 spans，不伪造区间。"
            ),
            "F6": (
                "旧引用 doc_id→source_id 归档 manifest 顺延 I4（precondition=新链重建核对后），"
                "写入架构 §7.2 与 tasks.md；I2-8 仅交付 archive_required 拒绝路径。"
            ),
            "F7": "golden carry-over 至 I3-5（design-review 矩阵 [6]）登记入 tasks.md。",
            "F8": (
                "read_chain() 严格化：迁移目标请求 legacy 即拒绝；无 corpus schema 库请求 new 亦拒绝；"
                "auto 仅作未迁移旧库过渡兜底。"
            ),
            "F9": (
                "parse 复用判定下沉 engine.expected_parse_rev(source)（_parse_rev_for 为唯一公式落点），"
                "CLI 只调用；补 DOCX 与非 MD、规则分量变化回归。"
            ),
            "F10": "退出码同因同码：check/status 的 build 不存在统一 EXIT_UNAVAILABLE(5)，门未过保持 4。",
            "F11": "main() 捕获 argparse SystemExit 归一为 EXIT_INPUT(2)。",
            "F13": (
                "批处理 scripts/corpus_holdout_eval.py、truncation_ab.py、truncation_metrics.py、"
                "corpus_evidence_pilot.py 归属裁定为 I3-5/I5-3（评测与退休核验）。"
            ),
        },
        "notes": [
            "i0c-r9/r10 保留历史字节，不追改；本修订登记复核整改后的实现/测试/文档。",
            "证据：复核探针 5 failed/1 passed → 6 passed；真库 consumers_pg(19)+cli_pg(4) 全 passed 零 skip；"
            "普通环境语料全量 425 passed/1 skipped；i1 守卫 env 188 passed。",
            "I2-8 由 partial 转 complete（整改 DoD 1—6 满足）；M5 仍 not_declared（待 I2-6 与独立复核）。",
            "生产库 I4 前零写入；真库动作仅限 i2_sandbox_corpus 的 corpus schema。",
        ],
        "m5_declaration": "not_declared（I2-1/2/3/4/5/7/8 完成；仍需 I2-6 与独立复核）",
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
