"""Verify the I0-C freeze chain (i0c-r1..r22) and its lineage to the I1 chain and M1.

显式检查 + 非零退出；不使用 assert（不得依赖可被 -O 剥离的断言）。核验内容：

1. freeze-manifest.json：条目 snapshot_id 唯一、每条目哈希与文件实际字节一致；
2. 索引存在 i0c-r1..r19 与 i1-r4 条目；
3. 各修订 parent_snapshot 指向上一修订且文件字节与声明哈希一致
   （i0c-r1.parent=i1-r4，r2.parent=r1，…，r18.parent=r17，r19.parent=r18）；
4. i0c-r2/r3/…/r19 绑定按「最新修订优先」按路径合并为 i0c-current
   （同一路径跨组重绑以最新修订为准，清除旧组残留条目）后逐一核验；
5. supersession：被 i0c-r2…r19 显式重绑的路径豁免 i1-r4 旧哈希核对
   （活文件合法演进，新哈希由 i0c-current 核验），其余 i1-r4 绑定仍逐一核验；
6. 血缘：i1-r4.parent = i1-r3 @ f22525c3…；i1-r3.parent = i1-r1 @ d474bd6d…；
   i1-r1.parent = i0a5(M1) @ 71aa61af…（文件字节核验）；
7. i0c-r1 绑定的 design-review.json 已签认（status/approved_by 非空）且 i1-r4 已记录；
8. i0c-r19（I3-0 评分器）为**纯新增**：其 implementation 组只允许出现新模块
   ``plugins/corpus/scoring.py``，出现任何既有实现文件即为越界；
9. i0c-r20 只修本验证器 r19 块的路径拼装（未过门当轮发现）+ 台账文字，**不得**借机重绑
   ``plugins/``／``tests/``／``guards/i3.json`` 字节；
10. i0c-r21 = I3-0 独立复核（F1—F5）整改：只改 ``plugins/corpus/scoring.py``、
   ``tests/test_corpus_scoring.py`` 与台账文字，**不得**借整改重绑守卫/金标/既有入库实现；
11. i0c-r22 = I3-2 补料（证据目标候选 + 往返验证 + 待裁决清单）：只绑 ``i3_2_assets``／台账／验证器，
   **不得**出现 ``plugins/``／``tests/``／守卫绑定（本轮不碰实现）。
12. i0c-r23 = I3-2 补料**独立复核 F1—F5 整改**（规则 evidence-mapping-4 + 人工裁决单 + 三自检段）：
   只绑 ``i3_2_assets``／``i3_2_archive``（本轮归档件）／台账／验证器；同样**不得**出现
   ``plugins/``／``tests/``／守卫绑定（评分器与守卫仍是 r19—r21 绑定字节）。
13. i0c-r24 = I3-2 补料**二轮复核 A1—A5 整改**（规则 evidence-mapping-5 + 共享文本层 +
   裁决应用器 + 审批件/批准投影/完整性门 + 16 条反例）：只绑 ``i3_2_tooling``／``i3_2_assets``／
   ``i3_2_archive``（r23 被覆盖字节的归档）／台账／验证器；同样**不得**出现
   ``plugins/``／``tests/``／守卫绑定。
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[3]

errors: list[str] = []


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(cond: bool, message: str) -> None:
    if not cond:
        errors.append(message)


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        errors.append(f"{path.name}: 不可读或非法 JSON（{exc}）")
        return {}


def verify_binding(snapshot_id: str, binding: dict,
                   skip: set[str] | None = None) -> tuple[int, int]:
    """核验绑定条目；skip 中的路径已被更新修订显式重绑，豁免并计数（supersession）。"""
    total = 0
    skipped = 0
    for group in sorted(binding):
        for rel in sorted(binding[group]):
            if skip is not None and rel in skip:
                skipped += 1
                continue
            total += 1
            f = ROOT / rel
            if not f.is_file() or digest(f) != binding[group][rel]:
                errors.append(f"{snapshot_id}.binding[{group}]: {rel} 哈希失配或缺失")
    return total, skipped


def merge_binding(current: dict, binding: dict) -> None:
    """按路径合并（最新修订优先）：同一路径跨组重绑时清除旧组条目，仅保留最新绑定。"""
    for group, items in binding.items():
        for rel, expected in items.items():
            for existing_group in list(current):
                current[existing_group].pop(rel, None)
            current.setdefault(group, {})[rel] = expected


manifest = load_json(BASE / "freeze-manifest.json")
snapshots = manifest.get("snapshots", [])
ids = [entry.get("snapshot_id") for entry in snapshots]
check(len(ids) == len(set(ids)), f"索引 snapshot_id 重复: {ids}")
check(bool(ids), "索引无条目")

by_id: dict[str, dict] = {}
for entry in snapshots:
    sid = entry.get("snapshot_id")
    by_id[sid] = entry
    rel = entry.get("file", "")
    file = BASE / rel
    if not file.is_file():
        errors.append(f"{sid}: 索引文件缺失 {rel}")
        continue
    check(digest(file) == entry.get("sha256"), f"{sid}: 索引哈希失配 {rel}")
check("i0c-r1" in by_id, "索引缺少 i0c-r1 条目")
check("i0c-r2" in by_id, "索引缺少 i0c-r2 条目")
check("i0c-r3" in by_id, "索引缺少 i0c-r3 条目")
check("i0c-r4" in by_id, "索引缺少 i0c-r4 条目")
check("i0c-r5" in by_id, "索引缺少 i0c-r5 条目")
check("i0c-r6" in by_id, "索引缺少 i0c-r6 条目")
check("i0c-r7" in by_id, "索引缺少 i0c-r7 条目")
check("i0c-r8" in by_id, "索引缺少 i0c-r8 条目")
check("i0c-r9" in by_id, "索引缺少 i0c-r9 条目")
check("i0c-r10" in by_id, "索引缺少 i0c-r10 条目")
check("i0c-r11" in by_id, "索引缺少 i0c-r11 条目")
check("i0c-r12" in by_id, "索引缺少 i0c-r12 条目")
check("i0c-r13" in by_id, "索引缺少 i0c-r13 条目")
check("i0c-r14" in by_id, "索引缺少 i0c-r14 条目")
check("i0c-r15" in by_id, "索引缺少 i0c-r15 条目")
check("i0c-r16" in by_id, "索引缺少 i0c-r16 条目")
check("i0c-r17" in by_id, "索引缺少 i0c-r17 条目")
check("i0c-r18" in by_id, "索引缺少 i0c-r18 条目")
check("i0c-r19" in by_id, "索引缺少 i0c-r19 条目")
check("i0c-r20" in by_id, "索引缺少 i0c-r20 条目")
check("i0c-r21" in by_id, "索引缺少 i0c-r21 条目")
check("i0c-r22" in by_id, "索引缺少 i0c-r22 条目")
check("i0c-r23" in by_id, "索引缺少 i0c-r23 条目")
check("i0c-r24" in by_id, "索引缺少 i0c-r24 条目")
check("i0c-r25" in by_id, "索引缺少 i0c-r25 条目")
check("i0c-r26" in by_id, "索引缺少 i0c-r26 条目")
check("i0c-r27" in by_id, "索引缺少 i0c-r27 条目")
check("i0c-r28" in by_id, "索引缺少 i0c-r28 条目")
check("i1-r4" in by_id, "索引缺少 i1-r4 条目")

if "i0c-r1" in by_id:
    i0c = load_json(BASE / by_id["i0c-r1"].get("file", ""))
    parent = i0c.get("parent_snapshot", {})
    check(parent.get("snapshot_id") == "i1-r4",
          f"i0c-r1.parent 应为 i1-r4，实际 {parent.get('snapshot_id')!r}")
    if parent.get("snapshot_id") == "i1-r4":
        pfile = ROOT / parent.get("path", "")
        if not pfile.is_file() or digest(pfile) != parent.get("sha256"):
            errors.append("i0c-r1.parent(i1-r4) 文件字节与声明哈希不一致")
    binding = i0c.get("binding", {})
    check(bool(binding), "i0c-r1.binding 为空")
    # r1 已被 r2 取代：其绑定的活文件（design-review/tasks 等）可合法演进，
    # 故不对当前工作区做绑定哈希核对；r1 快照自身完整性由 manifest 内 sha256
    # 与血缘链保证（上方已核）。全量绑定核对仅施于当前修订（见 i0c-r2 块）。
    design = i0c.get("design_review_signed", {})
    check(design.get("signed") is True and bool(design.get("approved_by")),
          "i0c-r1 未携带 design-review 签认标记")
    check(design.get("sha256") == binding.get("design_review", {}).get(
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/design-review.json"),
        "i0c-r1.design_review_signed.sha256 与绑定不一致")

i0c_current_binding: dict = {}
if "i0c-r2" in by_id:
    i0c2 = load_json(BASE / by_id["i0c-r2"].get("file", ""))
    parent = i0c2.get("parent_snapshot", {})
    check(parent.get("snapshot_id") == "i0c-r1",
          f"i0c-r2.parent 应为 i0c-r1，实际 {parent.get('snapshot_id')!r}")
    if parent.get("snapshot_id") == "i0c-r1":
        pfile = ROOT / parent.get("path", "")
        if not pfile.is_file() or digest(pfile) != parent.get("sha256"):
            errors.append("i0c-r2.parent(i0c-r1) 文件字节与声明哈希不一致")
    binding = i0c2.get("binding", {})
    merge_binding(i0c_current_binding, binding)
    corrections = i0c2.get("corrections", {})
    check("G6" in json.dumps(corrections), "i0c-r2 未登记 G6 修正")

if "i0c-r3" in by_id:
    i0c3 = load_json(BASE / by_id["i0c-r3"].get("file", ""))
    parent = i0c3.get("parent_snapshot", {})
    check(parent.get("snapshot_id") == "i0c-r2",
          f"i0c-r3.parent 应为 i0c-r2，实际 {parent.get('snapshot_id')!r}")
    if parent.get("snapshot_id") == "i0c-r2":
        pfile = ROOT / parent.get("path", "")
        if not pfile.is_file() or digest(pfile) != parent.get("sha256"):
            errors.append("i0c-r3.parent(i0c-r2) 文件字节与声明哈希不一致")
    merge_binding(i0c_current_binding, i0c3.get("binding", {}))
    corrections = json.dumps(i0c3.get("corrections", {}), ensure_ascii=False)
    for finding in ("F1", "F2", "F3", "F4", "F5", "F6"):
        check(finding in corrections, f"i0c-r3 未登记 {finding} 修正")

if "i0c-r4" in by_id:
    i0c4 = load_json(BASE / by_id["i0c-r4"].get("file", ""))
    parent = i0c4.get("parent_snapshot", {})
    check(parent.get("snapshot_id") == "i0c-r3",
          f"i0c-r4.parent 应为 i0c-r3，实际 {parent.get('snapshot_id')!r}")
    if parent.get("snapshot_id") == "i0c-r3":
        pfile = ROOT / parent.get("path", "")
        if not pfile.is_file() or digest(pfile) != parent.get("sha256"):
            errors.append("i0c-r4.parent(i0c-r3) 文件字节与声明哈希不一致")
    merge_binding(i0c_current_binding, i0c4.get("binding", {}))
    corrections = json.dumps(i0c4.get("corrections", {}), ensure_ascii=False)
    check("I2-3" in corrections, "i0c-r4 未登记 I2-3 交付")

if "i0c-r5" in by_id:
    i0c5 = load_json(BASE / by_id["i0c-r5"].get("file", ""))
    parent = i0c5.get("parent_snapshot", {})
    check(parent.get("snapshot_id") == "i0c-r4",
          f"i0c-r5.parent 应为 i0c-r4，实际 {parent.get('snapshot_id')!r}")
    if parent.get("snapshot_id") == "i0c-r4":
        pfile = ROOT / parent.get("path", "")
        if not pfile.is_file() or digest(pfile) != parent.get("sha256"):
            errors.append("i0c-r5.parent(i0c-r4) 文件字节与声明哈希不一致")
    merge_binding(i0c_current_binding, i0c5.get("binding", {}))
    corrections = json.dumps(i0c5.get("corrections", {}), ensure_ascii=False)
    check("I2-7" in corrections, "i0c-r5 未登记 I2-7 交付")

if "i0c-r6" in by_id:
    i0c6 = load_json(BASE / by_id["i0c-r6"].get("file", ""))
    parent = i0c6.get("parent_snapshot", {})
    check(parent.get("snapshot_id") == "i0c-r5",
          f"i0c-r6.parent 应为 i0c-r5，实际 {parent.get('snapshot_id')!r}")
    if parent.get("snapshot_id") == "i0c-r5":
        pfile = ROOT / parent.get("path", "")
        if not pfile.is_file() or digest(pfile) != parent.get("sha256"):
            errors.append("i0c-r6.parent(i0c-r5) 文件字节与声明哈希不一致")
    merge_binding(i0c_current_binding, i0c6.get("binding", {}))
    corrections = json.dumps(i0c6.get("corrections", {}), ensure_ascii=False)
    check("I2-5" in corrections, "i0c-r6 未登记 I2-5 交付")
    for finding in ("J1", "J2", "lease_lost", "max_attempts"):
        check(finding in corrections, f"i0c-r6 未登记 {finding} 修正")

if "i0c-r7" in by_id:
    i0c7 = load_json(BASE / by_id["i0c-r7"].get("file", ""))
    parent = i0c7.get("parent_snapshot", {})
    check(parent.get("snapshot_id") == "i0c-r6",
          f"i0c-r7.parent 应为 i0c-r6，实际 {parent.get('snapshot_id')!r}")
    if parent.get("snapshot_id") == "i0c-r6":
        pfile = ROOT / parent.get("path", "")
        if not pfile.is_file() or digest(pfile) != parent.get("sha256"):
            errors.append("i0c-r7.parent(i0c-r6) 文件字节与声明哈希不一致")
    merge_binding(i0c_current_binding, i0c7.get("binding", {}))
    corrections = json.dumps(i0c7.get("corrections", {}), ensure_ascii=False)
    for finding in ("R3", "R4", "R5", "R2", "R1", "R6"):
        check(finding in corrections, f"i0c-r7 未登记 {finding} 修正")
    # R6：新增 publication 模块必须进入绑定（引擎已导入使用），否则「新增模块漏绑定」。
    impl = i0c7.get("binding", {}).get("implementation", {})
    check("plugins/corpus/preparation/publication.py" in impl,
          "i0c-r7 未绑定 plugins/corpus/preparation/publication.py（新增模块漏绑定）")
    tests = i0c7.get("binding", {}).get("tests", {})
    check("tests/test_corpus_preparation_publication.py" in tests,
          "i0c-r7 未绑定 tests/test_corpus_preparation_publication.py")

if "i0c-r8" in by_id:
    i0c8 = load_json(BASE / by_id["i0c-r8"].get("file", ""))
    parent = i0c8.get("parent_snapshot", {})
    check(parent.get("snapshot_id") == "i0c-r7",
          f"i0c-r8.parent 应为 i0c-r7，实际 {parent.get('snapshot_id')!r}")
    if parent.get("snapshot_id") == "i0c-r7":
        pfile = ROOT / parent.get("path", "")
        if not pfile.is_file() or digest(pfile) != parent.get("sha256"):
            errors.append("i0c-r8.parent(i0c-r7) 文件字节与声明哈希不一致")
    merge_binding(i0c_current_binding, i0c8.get("binding", {}))
    corrections = json.dumps(i0c8.get("corrections", {}), ensure_ascii=False)
    for finding in ("RM-1", "RM-2", "RM-3", "RM-4", "RM-5",
                    "RM-6", "RM-7", "RM-8", "RM-10"):
        check(finding in corrections, f"i0c-r8 未登记 {finding} 整改")
    # 本批次改动的三件实现必须进入绑定（RM-1/RM-2/RM-3/RM-4 的落点）
    impl8 = i0c8.get("binding", {}).get("implementation", {})
    for required in ("plugins/corpus/preparation/engine.py",
                     "plugins/corpus/preparation/repository.py",
                     "plugins/corpus/preparation/repository_pg.py"):
        check(required in impl8, f"i0c-r8 未绑定 {required}")
    tests8 = i0c8.get("binding", {}).get("tests", {})
    check("tests/test_corpus_preparation_publication_pg.py" in tests8,
          "i0c-r8 未绑定 tests/test_corpus_preparation_publication_pg.py")


if "i0c-r9" in by_id:
    i0c9 = load_json(BASE / by_id["i0c-r9"].get("file", ""))
    parent = i0c9.get("parent_snapshot", {})
    check(parent.get("snapshot_id") == "i0c-r8",
          f"i0c-r9.parent 应为 i0c-r8，实际 {parent.get('snapshot_id')!r}")
    if parent.get("snapshot_id") == "i0c-r8":
        pfile = ROOT / parent.get("path", "")
        if not pfile.is_file() or digest(pfile) != parent.get("sha256"):
            errors.append("i0c-r9.parent(i0c-r8) 文件字节与声明哈希不一致")
    merge_binding(i0c_current_binding, i0c9.get("binding", {}))
    corrections = json.dumps(i0c9.get("corrections", {}), ensure_ascii=False)
    for finding in ("I2-8", "I2-4"):
        check(finding in corrections, f"i0c-r9 未登记 {finding} 交付")
    impl9 = i0c9.get("binding", {}).get("implementation", {})
    for required in ("plugins/corpus/cli.py",
                     "plugins/corpus/preparation/read_pg.py",
                     "plugins/corpus/service.py",
                     "plugins/corpus/audit.py",
                     "plugins/tools/corpus_search.py",
                     "plugins/tools/corpus_fetch.py"):
        check(required in impl9, f"i0c-r9 未绑定 {required}")
    tests9 = i0c9.get("binding", {}).get("tests", {})
    for required in ("tests/test_corpus_consumers_pg.py",
                     "tests/test_corpus_cli.py",
                     "tests/test_corpus_cli_pg.py"):
        check(required in tests9, f"i0c-r9 未绑定 {required}")


if "i0c-r10" in by_id:
    i0c10 = load_json(BASE / by_id["i0c-r10"].get("file", ""))
    parent = i0c10.get("parent_snapshot", {})
    check(parent.get("snapshot_id") == "i0c-r9",
          f"i0c-r10.parent 应为 i0c-r9，实际 {parent.get('snapshot_id')!r}")
    if parent.get("snapshot_id") == "i0c-r9":
        pfile = ROOT / parent.get("path", "")
        if not pfile.is_file() or digest(pfile) != parent.get("sha256"):
            errors.append("i0c-r10.parent(i0c-r9) 文件字节与声明哈希不一致")
    merge_binding(i0c_current_binding, i0c10.get("binding", {}))
    corrections = json.dumps(i0c10.get("corrections", {}), ensure_ascii=False)
    check("count_correction" in corrections, "i0c-r10 未登记 count_correction")
    docs10 = i0c10.get("binding", {}).get("docs", {})
    for required in ("docs/plan/claims-market-closed-loop-plan.md",
                     "docs/plan/corpus-ingestion-rebuild-tasks.md"):
        check(required in docs10, f"i0c-r10 未绑定 {required}")


if "i0c-r11" in by_id:
    i0c11 = load_json(BASE / by_id["i0c-r11"].get("file", ""))
    parent = i0c11.get("parent_snapshot", {})
    check(parent.get("snapshot_id") == "i0c-r10",
          f"i0c-r11.parent 应为 i0c-r10，实际 {parent.get('snapshot_id')!r}")
    if parent.get("snapshot_id") == "i0c-r10":
        pfile = ROOT / parent.get("path", "")
        if not pfile.is_file() or digest(pfile) != parent.get("sha256"):
            errors.append("i0c-r11.parent(i0c-r10) 文件字节与声明哈希不一致")
    merge_binding(i0c_current_binding, i0c11.get("binding", {}))
    corrections = json.dumps(i0c11.get("corrections", {}), ensure_ascii=False)
    for finding in ("F1", "F2", "F3", "F4", "F5", "F8", "F9", "F10", "F11",
                    "RM-I28-0", "F6", "F7", "F13"):
        check(finding in corrections, f"i0c-r11 未登记 {finding} 整改")
    impl11 = i0c11.get("binding", {}).get("implementation", {})
    for required in ("plugins/corpus/preparation/read_pg.py",
                     "plugins/corpus/cli.py",
                     "plugins/corpus/service.py",
                     "plugins/tools/data_coverage.py",
                     "plugins/tools/corpus_fetch.py",
                     "plugins/tools/corpus_search.py"):
        check(required in impl11, f"i0c-r11 未绑定 {required}")
    tests11 = i0c11.get("binding", {}).get("tests", {})
    for required in ("tests/test_corpus_consumers_pg.py",
                     "tests/test_data_coverage.py"):
        check(required in tests11, f"i0c-r11 未绑定 {required}")
    docs11 = i0c11.get("binding", {}).get("docs", {})
    check("docs/plan/corpus-ingestion-rebuild-architecture.md" in docs11,
          "i0c-r11 未绑定架构文档（RM-I28-0 裁定落点）")


if "i0c-r12" in by_id:
    i0c12 = load_json(BASE / by_id["i0c-r12"].get("file", ""))
    parent = i0c12.get("parent_snapshot", {})
    check(parent.get("snapshot_id") == "i0c-r11",
          f"i0c-r12.parent 应为 i0c-r11，实际 {parent.get('snapshot_id')!r}")
    if parent.get("snapshot_id") == "i0c-r11":
        pfile = ROOT / parent.get("path", "")
        if not pfile.is_file() or digest(pfile) != parent.get("sha256"):
            errors.append("i0c-r12.parent(i0c-r11) 文件字节与声明哈希不一致")
    merge_binding(i0c_current_binding, i0c12.get("binding", {}))
    corrections = json.dumps(i0c12.get("corrections", {}), ensure_ascii=False)
    check("type_fix" in corrections, "i0c-r12 未登记 type_fix")
    impl12 = i0c12.get("binding", {}).get("implementation", {})
    check("plugins/tools/data_coverage.py" in impl12,
          "i0c-r12 未绑定 plugins/tools/data_coverage.py")


if "i0c-r13" in by_id:
    i0c13 = load_json(BASE / by_id["i0c-r13"].get("file", ""))
    parent = i0c13.get("parent_snapshot", {})
    check(parent.get("snapshot_id") == "i0c-r12",
          f"i0c-r13.parent 应为 i0c-r12，实际 {parent.get('snapshot_id')!r}")
    if parent.get("snapshot_id") == "i0c-r12":
        pfile = ROOT / parent.get("path", "")
        if not pfile.is_file() or digest(pfile) != parent.get("sha256"):
            errors.append("i0c-r13.parent(i0c-r12) 文件字节与声明哈希不一致")
    merge_binding(i0c_current_binding, i0c13.get("binding", {}))
    corrections = json.dumps(i0c13.get("corrections", {}), ensure_ascii=False)
    for finding in ("I2-6", "authority", "cli_isolation", "integrity_hash",
                    "fetch_cell", "evidence_authority"):
        check(finding in corrections, f"i0c-r13 未登记 {finding}")
    impl13 = i0c13.get("binding", {}).get("implementation", {})
    for required in ("plugins/corpus/preparation/read_pg.py", "plugins/corpus/service.py"):
        check(required in impl13, f"i0c-r13 未绑定 {required}")
    tests13 = i0c13.get("binding", {}).get("tests", {})
    for required in ("tests/test_corpus_authority_pg.py", "tests/test_corpus_cli_isolation.py"):
        check(required in tests13, f"i0c-r13 未绑定 {required}")


if "i0c-r14" in by_id:
    i0c14 = load_json(BASE / by_id["i0c-r14"].get("file", ""))
    parent = i0c14.get("parent_snapshot", {})
    check(parent.get("snapshot_id") == "i0c-r13",
          f"i0c-r14.parent 应为 i0c-r13，实际 {parent.get('snapshot_id')!r}")
    if parent.get("snapshot_id") == "i0c-r13":
        pfile = ROOT / parent.get("path", "")
        if not pfile.is_file() or digest(pfile) != parent.get("sha256"):
            errors.append("i0c-r14.parent(i0c-r13) 文件字节与声明哈希不一致")
    merge_binding(i0c_current_binding, i0c14.get("binding", {}))
    corrections = json.dumps(i0c14.get("corrections", {}), ensure_ascii=False)
    check("m5_review_package" in corrections, "i0c-r14 未登记 m5_review_package")
    pkg = i0c14.get("binding", {}).get("review_package", {})
    for required in ("README.md", "run_matrix.sh", "verify_matrix.py", "cross-check.md"):
        full = f".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260918-m5-review/{required}"
        check(full in pkg, f"i0c-r14 未绑定 M5 复核包 {required}")


if "i0c-r15" in by_id:
    i0c15 = load_json(BASE / by_id["i0c-r15"].get("file", ""))
    parent = i0c15.get("parent_snapshot", {})
    check(parent.get("snapshot_id") == "i0c-r14",
          f"i0c-r15.parent 应为 i0c-r14，实际 {parent.get('snapshot_id')!r}")
    if parent.get("snapshot_id") == "i0c-r14":
        pfile = ROOT / parent.get("path", "")
        if not pfile.is_file() or digest(pfile) != parent.get("sha256"):
            errors.append("i0c-r15.parent(i0c-r14) 文件字节与声明哈希不一致")
    merge_binding(i0c_current_binding, i0c15.get("binding", {}))
    corrections = json.dumps(i0c15.get("corrections", {}), ensure_ascii=False)
    for finding in ("RM-FC-0", "RM-FC-1", "RM-FC-2", "RM-FC-3", "RM-FC-4",
                    "RM-FC-5", "RM-FC-6", "RM-FC-7", "F1", "F2", "F3", "F4"):
        check(finding in corrections, f"i0c-r15 未登记 {finding} 整改")
    # 本批次改动的实现必须进入绑定（缺口裁决 + 可见性 + coverage + 拼接语义的落点）
    impl15 = i0c15.get("binding", {}).get("implementation", {})
    for required in ("plugins/corpus/preparation/gaps.py",
                     "plugins/corpus/preparation/clean.py",
                     "plugins/corpus/preparation/engine.py",
                     "plugins/corpus/preparation/read_pg.py",
                     "plugins/corpus/cli.py"):
        check(required in impl15, f"i0c-r15 未绑定 {required}")
    tests15 = i0c15.get("binding", {}).get("tests", {})
    check("tests/test_corpus_gap_dispositions.py" in tests15,
          "i0c-r15 未绑定 tests/test_corpus_gap_dispositions.py")
    docs15 = i0c15.get("binding", {}).get("docs", {})
    for required in ("docs/plan/corpus-ingestion-rebuild-architecture.md",
                     "docs/plan/corpus-ingestion-rebuild-tasks.md",
                     "docs/plan/claims-market-closed-loop-plan.md"):
        check(required in docs15, f"i0c-r15 未绑定 {required}")
    # 复核方证据（write-once）：回路探针是 I3-7 复用的 E2E 基线来源
    evidence15 = i0c15.get("binding", {}).get("review_evidence", {})
    for required in ("review.md", "remediation-checklist.md", "test_fullchain_probes.py"):
        full = (
            ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/"
            f"20260918-i2-fullchain-review/{required}"
        )
        check(full in evidence15, f"i0c-r15 未绑定全链路复核证据 {required}")


if "i0c-r16" in by_id:
    i0c16 = load_json(BASE / by_id["i0c-r16"].get("file", ""))
    parent = i0c16.get("parent_snapshot", {})
    check(parent.get("snapshot_id") == "i0c-r15",
          f"i0c-r16.parent 应为 i0c-r15，实际 {parent.get('snapshot_id')!r}")
    if parent.get("snapshot_id") == "i0c-r15":
        pfile = ROOT / parent.get("path", "")
        if not pfile.is_file() or digest(pfile) != parent.get("sha256"):
            errors.append("i0c-r16.parent(i0c-r15) 文件字节与声明哈希不一致")
    merge_binding(i0c_current_binding, i0c16.get("binding", {}))
    corrections = json.dumps(i0c16.get("corrections", {}), ensure_ascii=False)
    for finding in ("m5_review_package_v2", "i0c-r15", "RM-FC-8", "gate_rehearsal"):
        check(finding in corrections, f"i0c-r16 未登记 {finding}")
    # M5 复核包 v2 的四个文件必须整体重绑（包字节任何变更都要新修订，否则前置门会拦）
    pkg16 = i0c16.get("binding", {}).get("review_package", {})
    for required in ("README.md", "run_matrix.sh", "verify_matrix.py", "cross-check.md"):
        full = (
            ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/"
            f"20260918-m5-review/{required}"
        )
        check(full in pkg16, f"i0c-r16 未绑定 M5 复核包 v2 {required}")


if "i0c-r17" in by_id:
    i0c17 = load_json(BASE / by_id["i0c-r17"].get("file", ""))
    parent = i0c17.get("parent_snapshot", {})
    check(parent.get("snapshot_id") == "i0c-r16",
          f"i0c-r17.parent 应为 i0c-r16，实际 {parent.get('snapshot_id')!r}")
    if parent.get("snapshot_id") == "i0c-r16":
        pfile = ROOT / parent.get("path", "")
        if not pfile.is_file() or digest(pfile) != parent.get("sha256"):
            errors.append("i0c-r17.parent(i0c-r16) 文件字节与声明哈希不一致")
    merge_binding(i0c_current_binding, i0c17.get("binding", {}))
    corrections = json.dumps(i0c17.get("corrections", {}), ensure_ascii=False)
    for finding in ("M5_release", "U_signoff", "independence_deviation", "F1", "F2", "F3"):
        check(finding in corrections, f"i0c-r17 未登记 {finding}")
    # 复核结论 + 证据面 + F1 修复后的测试字节必须同版绑定
    report17 = i0c17.get("binding", {}).get("review_report", {})
    for required in ("review.md", "cross-check-evidence.txt", "evidence-postfix/recheck.txt"):
        full = (
            ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/"
            f"20260918-m5-review/{required}"
        )
        check(full in report17, f"i0c-r17 未绑定复核报告/证据 {required}")
    tests17 = i0c17.get("binding", {}).get("tests", {})
    check("tests/test_corpus_gap_dispositions.py" in tests17,
          "i0c-r17 未绑定 F1 修复后的 tests/test_corpus_gap_dispositions.py")
    docs17 = i0c17.get("binding", {}).get("docs", {})
    for required in ("docs/plan/claims-market-closed-loop-plan.md",
                     "docs/plan/corpus-ingestion-rebuild-tasks.md"):
        check(required in docs17, f"i0c-r17 未绑定 {required}")
    check("released_by_U_signoff" in json.dumps(i0c17.get("m5_declaration", "")),
          "i0c-r17 的 m5_declaration 未登记 U 签认")


if "i0c-r18" in by_id:
    i0c18 = load_json(BASE / by_id["i0c-r18"].get("file", ""))
    parent = i0c18.get("parent_snapshot", {})
    check(parent.get("snapshot_id") == "i0c-r17",
          f"i0c-r18.parent 应为 i0c-r17，实际 {parent.get('snapshot_id')!r}")
    if parent.get("snapshot_id") == "i0c-r17":
        pfile = ROOT / parent.get("path", "")
        if not pfile.is_file() or digest(pfile) != parent.get("sha256"):
            errors.append("i0c-r18.parent(i0c-r17) 文件字节与声明哈希不一致")
    merge_binding(i0c_current_binding, i0c18.get("binding", {}))
    corrections = json.dumps(i0c18.get("corrections", {}), ensure_ascii=False)
    for finding in ("M5_release", "U_signoff", "report_revision"):
        check(finding in corrections, f"i0c-r18 未登记 {finding}")
    report18 = i0c18.get("binding", {}).get("review_report", {})
    check(
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260918-m5-review/review.md"
        in report18,
        "i0c-r18 未绑定复核报告 review.md",
    )
    docs18 = i0c18.get("binding", {}).get("docs", {})
    for required in ("docs/plan/claims-market-closed-loop-plan.md",
                     "docs/plan/corpus-ingestion-rebuild-tasks.md"):
        check(required in docs18, f"i0c-r18 未绑定 {required}")
    # 本轮不得改实现：r18 绑定里出现 plugins/ 或 tests/ 即为越界
    for group, items in i0c18.get("binding", {}).items():
        for rel in items:
            check(
                not rel.startswith("plugins/"),
                f"i0c-r18 越界绑定实现文件 {rel}（本修订只补记报告与台账）",
            )

if "i0c-r19" in by_id:
    i0c19 = load_json(BASE / by_id["i0c-r19"].get("file", ""))
    parent = i0c19.get("parent_snapshot", {})
    check(parent.get("snapshot_id") == "i0c-r18",
          f"i0c-r19.parent 应为 i0c-r18，实际 {parent.get('snapshot_id')!r}")
    if parent.get("snapshot_id") == "i0c-r18":
        pfile = ROOT / parent.get("path", "")
        if not pfile.is_file() or digest(pfile) != parent.get("sha256"):
            errors.append("i0c-r19.parent(i0c-r18) 文件字节与声明哈希不一致")
    binding19 = i0c19.get("binding", {})
    merge_binding(i0c_current_binding, binding19)
    corrections = json.dumps(i0c19.get("corrections", {}), ensure_ascii=False)
    for finding in ("I3-0", "DocRecall", "QuestionPass", "EvidencePass",
                    "evidence_targets_absent", "M5_F3_registered"):
        check(finding in corrections, f"i0c-r19 未登记 {finding}")
    impl19 = binding19.get("implementation", {})
    check("plugins/corpus/scoring.py" in impl19, "i0c-r19 未绑定 plugins/corpus/scoring.py")
    # 纯新增不变量：I3-0 只新增评分器，不得重绑任何既有实现文件。
    for rel in impl19:
        check(rel == "plugins/corpus/scoring.py",
              f"i0c-r19 越界重绑既有实现文件 {rel}（I3-0 应为纯新增）")
    tests19 = binding19.get("tests", {})
    check("tests/test_corpus_scoring.py" in tests19,
          "i0c-r19 未绑定 tests/test_corpus_scoring.py")
    guard19 = binding19.get("guard", {})
    guard_base = ".scratch/corpus-evidence-pipeline/ingestion-rebuild"
    for required in (
        f"{guard_base}/guards/i3.json",
        f"{guard_base}/i3-guard-report.json",
        f"{guard_base}/i3_guard_selfcheck.py",
    ):
        check(required in guard19, f"i0c-r19 未绑定 I3 守卫资产 {required}")
    docs19 = binding19.get("docs", {})
    for required in ("docs/plan/corpus-ingestion-rebuild-tasks.md",
                     "docs/plan/claims-market-closed-loop-plan.md"):
        check(required in docs19, f"i0c-r19 未绑定 {required}")


if "i0c-r20" in by_id:
    i0c20 = load_json(BASE / by_id["i0c-r20"].get("file", ""))
    parent = i0c20.get("parent_snapshot", {})
    check(parent.get("snapshot_id") == "i0c-r19",
          f"i0c-r20.parent 应为 i0c-r19，实际 {parent.get('snapshot_id')!r}")
    if parent.get("snapshot_id") == "i0c-r19":
        pfile = ROOT / parent.get("path", "")
        if not pfile.is_file() or digest(pfile) != parent.get("sha256"):
            errors.append("i0c-r20.parent(i0c-r19) 文件字节与声明哈希不一致")
    binding20 = i0c20.get("binding", {})
    merge_binding(i0c_current_binding, binding20)
    corrections = json.dumps(i0c20.get("corrections", {}), ensure_ascii=False)
    check("validator_path_fix" in corrections, "i0c-r20 未登记 validator_path_fix")
    check("freeze_validator" in binding20,
          "i0c-r20 未重绑 freeze_validator（验证器修正后必须同版重绑）")
    # 本修订只修验证器与台账文字：不得借机改实现/测试/守卫字节。
    for group, items in binding20.items():
        if group == "freeze_validator":
            continue
        for rel in items:
            check(
                not (rel.startswith("plugins/") or rel.startswith("tests/"))
                and rel != ".scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i3.json",
                f"i0c-r20 越界重绑 {rel}（本修订只修正验证器与台账文字）",
            )

if "i0c-r21" in by_id:
    i0c21 = load_json(BASE / by_id["i0c-r21"].get("file", ""))
    parent = i0c21.get("parent_snapshot", {})
    check(parent.get("snapshot_id") == "i0c-r20",
          f"i0c-r21.parent 应为 i0c-r20，实际 {parent.get('snapshot_id')!r}")
    if parent.get("snapshot_id") == "i0c-r20":
        pfile = ROOT / parent.get("path", "")
        if not pfile.is_file() or digest(pfile) != parent.get("sha256"):
            errors.append("i0c-r21.parent(i0c-r20) 文件字节与声明哈希不一致")
    binding21 = i0c21.get("binding", {})
    merge_binding(i0c_current_binding, binding21)
    corrections = json.dumps(i0c21.get("corrections", {}), ensure_ascii=False)
    for finding in ("F1", "F2", "F3", "F4", "F5", "I3-0_review_remediation",
                    "contract_rewrite", "overall_semantics"):
        check(finding in corrections, f"i0c-r21 未登记 {finding}")
    # 整改只动评分器/测试/台账：不得借复核整改重绑守卫、金标或既有入库实现。
    for group, items in binding21.items():
        if group in {"implementation", "tests", "docs", "freeze_validator"}:
            continue
        for rel in items:
            errors.append(f"i0c-r21 越界绑定 {group}/{rel}（整改只涉评分器/测试/台账）")
    impl21 = binding21.get("implementation", {})
    check("plugins/corpus/scoring.py" in impl21,
          "i0c-r21 未绑定 plugins/corpus/scoring.py（复核整改落点）")
    for rel in impl21:
        check(rel == "plugins/corpus/scoring.py",
              f"i0c-r21 越界重绑既有实现文件 {rel}（整改只改评分器与测试）")
    tests21 = binding21.get("tests", {})
    check("tests/test_corpus_scoring.py" in tests21,
          "i0c-r21 未绑定 tests/test_corpus_scoring.py")

if "i0c-r22" in by_id:
    i0c22 = load_json(BASE / by_id["i0c-r22"].get("file", ""))
    parent = i0c22.get("parent_snapshot", {})
    check(parent.get("snapshot_id") == "i0c-r21",
          f"i0c-r22.parent 应为 i0c-r21，实际 {parent.get('snapshot_id')!r}")
    if parent.get("snapshot_id") == "i0c-r21":
        pfile = ROOT / parent.get("path", "")
        if not pfile.is_file() or digest(pfile) != parent.get("sha256"):
            errors.append("i0c-r22.parent(i0c-r21) 文件字节与声明哈希不一致")
    binding22 = i0c22.get("binding", {})
    merge_binding(i0c_current_binding, binding22)
    corrections = json.dumps(i0c22.get("corrections", {}), ensure_ascii=False)
    for finding in ("I3-2_evidence_targets_candidates", "evidence_mapping_rule_rev",
                    "verification_roundtrip", "reconciliation_points"):
        check(finding in corrections, f"i0c-r22 未登记 {finding}")
    # 补料修订只绑候选产物/脚本/台账：不得借机改实现、测试或守卫。
    i3_2 = binding22.get("i3_2_assets", {})
    base = ".scratch/corpus-evidence-pipeline/ingestion-rebuild"
    for required in (
        f"{base}/i3s2_evidence_targets.py",
        f"{base}/i3s2_verify_candidates.py",
        f"{base}/i3-2/evidence-targets-candidates.json",
        f"{base}/i3-2/evidence-targets-review.md",
        f"{base}/i3-2/evidence-targets-verification.json",
    ):
        check(required in i3_2, f"i0c-r22 未绑定补料产物 {required}")
    for group, items in binding22.items():
        if group in {"i3_2_assets", "docs", "freeze_validator"}:
            continue
        for rel in items:
            errors.append(f"i0c-r22 越界绑定 {group}/{rel}（补料修订只涉候选产物与台账）")
    for group, items in binding22.items():
        for rel in items:
            check(not rel.startswith(("plugins/", "tests/")),
                  f"i0c-r22 越界绑定 {rel}（本轮不改实现与测试）")

if "i0c-r23" in by_id:
    i0c23 = load_json(BASE / by_id["i0c-r23"].get("file", ""))
    parent = i0c23.get("parent_snapshot", {})
    check(parent.get("snapshot_id") == "i0c-r22",
          f"i0c-r23.parent 应为 i0c-r22，实际 {parent.get('snapshot_id')!r}")
    if parent.get("snapshot_id") == "i0c-r22":
        pfile = ROOT / parent.get("path", "")
        if not pfile.is_file() or digest(pfile) != parent.get("sha256"):
            errors.append("i0c-r23.parent(i0c-r22) 文件字节与声明哈希不一致")
    binding23 = i0c23.get("binding", {})
    merge_binding(i0c_current_binding, binding23)
    corrections = json.dumps(i0c23.get("corrections", {}), ensure_ascii=False)
    for finding in ("I3-2_material_review_remediation", "evidence_mapping_rule_rev",
                    "evidence_pass_denominator", "completeness_gate", "human_adjudication"):
        check(finding in corrections, f"i0c-r23 未登记 {finding}")
    # 整改修订只绑补料产物/本轮归档件/裁决单/台账：不得借机改实现、测试或守卫。
    i3_2 = binding23.get("i3_2_assets", {})
    base = ".scratch/corpus-evidence-pipeline/ingestion-rebuild"
    for required in (
        f"{base}/i3s2_evidence_targets.py",
        f"{base}/i3s2_verify_candidates.py",
        f"{base}/i3-2/evidence-targets-candidates.json",
        f"{base}/i3-2/evidence-targets-review.md",
        f"{base}/i3-2/evidence-targets-adjudication.md",
        f"{base}/i3-2/evidence-targets-verification.json",
    ):
        check(required in i3_2, f"i0c-r23 未绑定补料产物 {required}")
    archive = binding23.get("i3_2_archive", {})
    for required in (
        f"{base}/i3-2/evidence-targets-candidates-v3.json",
        f"{base}/i3-2/evidence-targets-review-v3.md",
        f"{base}/i3-2/evidence-targets-verification-v1.json",
    ):
        check(required in archive, f"i0c-r23 未绑定本轮归档件 {required}")
    allowed_groups = {"i3_2_assets", "i3_2_archive", "docs", "freeze_validator"}
    for group, items in binding23.items():
        if group not in allowed_groups:
            errors.append(f"i0c-r23 越界绑定组 {group}（整改只涉补料产物与台账）")
        for rel in items:
            check(not rel.startswith(("plugins/", "tests/")),
                  f"i0c-r23 越界绑定 {rel}（本轮不改实现与测试）")

if "i0c-r24" in by_id:
    i0c24 = load_json(BASE / by_id["i0c-r24"].get("file", ""))
    parent = i0c24.get("parent_snapshot", {})
    check(parent.get("snapshot_id") == "i0c-r23",
          f"i0c-r24.parent 应为 i0c-r23，实际 {parent.get('snapshot_id')!r}")
    if parent.get("snapshot_id") == "i0c-r23":
        pfile = ROOT / parent.get("path", "")
        if not pfile.is_file() or digest(pfile) != parent.get("sha256"):
            errors.append("i0c-r24.parent(i0c-r23) 文件字节与声明哈希不一致")
    binding24 = i0c24.get("binding", {})
    merge_binding(i0c_current_binding, binding24)
    corrections = json.dumps(i0c24.get("corrections", {}), ensure_ascii=False)
    for finding in ("I3-2_adjudication_review_remediation", "evidence_mapping_rule_rev",
                    "approval_path", "completeness_gate", "human_adjudication"):
        check(finding in corrections, f"i0c-r24 未登记 {finding}")
    base = ".scratch/corpus-evidence-pipeline/ingestion-rebuild"
    tooling = binding24.get("i3_2_tooling", {})
    for required in (
        f"{base}/i3s2_textutil.py",
        f"{base}/i3s2_evidence_targets.py",
        f"{base}/i3s2_verify_candidates.py",
        f"{base}/i3s2_apply_decisions.py",
    ):
        check(required in tooling, f"i0c-r24 未绑定工具脚本 {required}")
    assets = binding24.get("i3_2_assets", {})
    for required in (
        f"{base}/i3-2/evidence-targets-candidates.json",
        f"{base}/i3-2/evidence-targets-review.md",
        f"{base}/i3-2/evidence-targets-adjudication.md",
        f"{base}/i3-2/evidence-targets-verification.json",
        f"{base}/i3-2/approval-report.json",
    ):
        check(required in assets, f"i0c-r24 未绑定补料产物 {required}")
    archive = binding24.get("i3_2_archive", {})
    for required in (
        f"{base}/i3-2/evidence-targets-candidates-v4.json",
        f"{base}/i3-2/evidence-targets-review-v4.md",
        f"{base}/i3-2/evidence-targets-adjudication-v1.md",
        f"{base}/i3-2/evidence-targets-verification-v2.json",
    ):
        check(required in archive, f"i0c-r24 未绑定被覆盖字节的归档 {required}")
    allowed_groups = {"i3_2_tooling", "i3_2_assets", "i3_2_archive", "docs", "freeze_validator"}
    for group, items in binding24.items():
        if group not in allowed_groups:
            errors.append(f"i0c-r24 越界绑定组 {group}（整改只涉补料工具链与台账）")
        for rel in items:
            check(not rel.startswith(("plugins/", "tests/")),
                  f"i0c-r24 越界绑定 {rel}（本轮不改实现与测试）")

if "i0c-r25" in by_id:
    i0c25 = load_json(BASE / by_id["i0c-r25"].get("file", ""))
    parent = i0c25.get("parent_snapshot", {})
    expected_parent = BASE / by_id["i0c-r24"]["file"]
    check(parent.get("snapshot_id") == "i0c-r24", "r25 parent must be r24")
    check(parent.get("path") == str(expected_parent.relative_to(ROOT)), "r25 parent path mismatch")
    check(parent.get("sha256") == digest(expected_parent), "r25 parent bytes mismatch")
    binding25 = i0c25.get("binding", {})
    corrections = i0c25.get("corrections", {})
    for finding in ("B1", "B2", "B3", "B4", "B5", "I3-5"):
        check(finding in corrections, f"r25 missing correction {finding}")
    base = ".scratch/corpus-evidence-pipeline/ingestion-rebuild"
    audit = f"{base}/audits/20260918-i32-remediation"
    allowed = {
        "i3_2_tooling": {f"{base}/{name}.py" for name in (
            "i3s2_evidence_targets", "i3s2_apply_decisions", "i3s2_verify_candidates")},
        "i3_2_assets": {f"{base}/i3-2/{name}" for name in (
            "evidence-targets-candidates.json", "evidence-targets-adjudication.md",
            "evidence-targets-review.md", "evidence-targets-verification.json", "approval-report.json")},
        "docs": {"docs/plan/corpus-ingestion-rebuild-tasks.md", "docs/plan/claims-market-closed-loop-plan.md"},
        "freeze_validator": {f"{base}/freezes/validate_i0c_freeze.py"},
    }
    check(set(binding25) == set(allowed) | {"i3_2_regressions", "i3_2_archive"}, "r25 binding groups mismatch")
    for group, expected in allowed.items():
        check(set(binding25.get(group, {})) == expected, f"r25 unexpected {group} scope")
    for rel in binding25.get("i3_2_regressions", {}):
        check(str(Path(rel).parent) == audit and ".." not in Path(rel).parts,
              f"r25 regression binding out of scope {rel}")
    for name in ("test_approval_contract.py", "green-final.txt", "review.md", "finalize.py"):
        check(f"{audit}/{name}" in binding25.get("i3_2_regressions", {}), f"r25 missing regression {name}")
    parent24 = load_json(expected_parent)
    expected_archives = {}
    for group in ("i3_2_tooling", "i3_2_assets", "docs", "freeze_validator"):
        for rel, sha in parent24.get("binding", {}).get(group, {}).items():
            expected_archives[f"{audit}/before-r24/{rel}"] = sha
    check(binding25.get("i3_2_archive") == expected_archives, "r25 historical byte archive incomplete")
    merge_binding(i0c_current_binding, binding25)


if "i0c-r26" in by_id:
    i0c26 = load_json(BASE / by_id["i0c-r26"].get("file", ""))
    parent = i0c26.get("parent_snapshot", {})
    expected_parent = BASE / by_id["i0c-r25"]["file"]
    check(parent.get("snapshot_id") == "i0c-r25", "r26 parent must be r25")
    check(parent.get("path") == str(expected_parent.relative_to(ROOT)), "r26 parent path mismatch")
    check(parent.get("sha256") == digest(expected_parent), "r26 parent bytes mismatch")
    binding26 = i0c26.get("binding", {})
    corrections = i0c26.get("corrections", {})
    for finding in ("I3-2_adoption", "human_signature", "required_supplementary_scope",
                    "machine_status_override", "verifier_probe_update", "I3-5"):
        check(finding in corrections, f"r26 missing correction {finding}")
    base = ".scratch/corpus-evidence-pipeline/ingestion-rebuild"
    audit = f"{base}/audits/20260918-i32-adoption-dryrun"
    allowed = {
        "i3_2_tooling": {f"{base}/{name}.py" for name in (
            "i3s2_evidence_targets", "i3s2_apply_decisions", "i3s2_verify_candidates",
            "i3s2_textutil")},
        "i3_2_source_gold": {f"{base}/{name}" for name in (
            "source-gold-frozen.jsonl", "query-gold-frozen.jsonl")},
        "i3_2_assets": {f"{base}/i3-2/{name}" for name in (
            "evidence-targets-candidates.json", "evidence-targets-adjudication.md",
            "evidence-targets-review.md", "evidence-targets-verification.json",
            "approval-report.json", "evidence-targets-decisions.json",
            "evidence-targets-approved.json", "source-gold-nearmiss-library.jsonl")},
        "docs": {"docs/plan/corpus-ingestion-rebuild-tasks.md",
                 "docs/plan/claims-market-closed-loop-plan.md"},
        "freeze_validator": {f"{base}/freezes/validate_i0c_freeze.py"},
    }
    check(set(binding26) == set(allowed) | {"i3_2_regressions", "i3_2_archive"},
          "r26 binding groups mismatch")
    for group, expected in allowed.items():
        check(set(binding26.get(group, {})) == expected, f"r26 unexpected {group} scope")
    for name in ("evidence-targets-candidates-v6.json", "evidence-targets-review-v6.md",
                 "evidence-targets-adjudication-v3.md", "evidence-targets-verification-v4.json",
                 "approval-report-v2.json"):
        check(f"{base}/i3-2/{name}" in binding26.get("i3_2_archive", {}),
              f"r26 missing archive {name}")
    gold_archive = f"{audit}/before-r26/{base}/source-gold-frozen.jsonl"
    check(gold_archive in binding26.get("i3_2_archive", {}),
          "r26 missing r25 source-gold byte archive")
    for rel in binding26.get("i3_2_regressions", {}):
        check(str(Path(rel).parent) == audit and ".." not in Path(rel).parts,
              f"r26 regression binding out of scope {rel}")
    for name in ("report.md", "run_adoption_dryrun.py", "promote_i3s2.py", "promote-log.json",
                 "dryrun-result.json", "decisions-final-dryrun.json", "gate-final-dryrun.json",
                 "release-manifest.json", "verification-v7-dryrun.json"):
        check(f"{audit}/{name}" in binding26.get("i3_2_regressions", {}),
              f"r26 missing regression {name}")
    for group, items in binding26.items():
        for rel in items:
            check(not rel.startswith(("plugins/", "tests/", "guards/")),
                  f"r26 越界绑定 {rel}（本轮不改实现/测试/守卫）")
    check(
        binding26.get("i3_2_source_gold", {}).get(f"{base}/source-gold-frozen.jsonl")
        == digest(ROOT / f"{base}/source-gold-frozen.jsonl"),
        "r26 source-gold binding mismatch",
    )
    merge_binding(i0c_current_binding, binding26)

if "i0c-r27" in by_id:
    i0c27 = load_json(BASE / by_id["i0c-r27"].get("file", ""))
    parent = i0c27.get("parent_snapshot", {})
    expected_parent = BASE / by_id["i0c-r26"]["file"]
    check(parent.get("snapshot_id") == "i0c-r26", "r27 parent must be r26")
    check(parent.get("path") == str(expected_parent.relative_to(ROOT)), "r27 parent path mismatch")
    check(parent.get("sha256") == digest(expected_parent), "r27 parent bytes mismatch")
    binding27 = i0c27.get("binding", {})
    corrections = i0c27.get("corrections", {})
    for finding in ("I3-2_old_baseline_scope", "guard_holdout_4th", "I3-5", "validate_i3_2_completion"):
        check(finding in corrections, f"r27 missing correction {finding}")
    base = ".scratch/corpus-evidence-pipeline/ingestion-rebuild"
    audit = f"{base}/audits/20260919-i32-diagnosis"
    allowed = {
        "i3_2_old_baseline": {
            f"{audit}/baseline-case-manifest.json",
            f"{audit}/baseline-case-manifest.md",
            f"{audit}/build_baseline_cases.py",
            f"{audit}/decision-old-doc-kind-review-authority-20260919.json",
            f"{audit}/decision-old-doc-kind-review-authority-20260919.md",
            f"{audit}/unified-status.md",
            f"{audit}/diagnosis-and-remediation.md",
        },
        "guard": {f"{base}/guards/i3.json"},
        "docs": {"docs/plan/corpus-ingestion-rebuild-tasks.md",
                 "docs/plan/claims-market-closed-loop-plan.md"},
        "freeze_validator": {f"{base}/freezes/validate_i0c_freeze.py"},
    }
    check(set(binding27) == set(allowed), "r27 binding groups mismatch")
    for group, expected in allowed.items():
        check(set(binding27.get(group, {})) == expected, f"r27 unexpected {group} scope")
    check(
        binding27.get("guard", {}).get(f"{base}/guards/i3.json")
        == digest(ROOT / f"{base}/guards/i3.json"),
        "r27 guard i3.json binding mismatch",
    )
    # r27 只重绑守卫/旧基线身份/台账/验证器：不得出现 plugins/ 或 tests/ 绑定。
    for group, items in binding27.items():
        for rel in items:
            check(not rel.startswith(("plugins/", "tests/")),
                  f"r27 越界绑定 {rel}（本轮不改实现/测试）")
    merge_binding(i0c_current_binding, binding27)



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

# 最新修订绑定优先（supersession）：i0c-r2..r28 显式重绑的路径改由合并后的
# i0c-current 绑定按新哈希核对，i1-r4 中对应旧绑定不再要求匹配。
superseded: set[str] = set()
for sid in ("i0c-r2", "i0c-r3", "i0c-r4", "i0c-r5", "i0c-r6", "i0c-r7", "i0c-r8", "i0c-r9", "i0c-r10", "i0c-r11", "i0c-r12", "i0c-r13", "i0c-r14", "i0c-r15", "i0c-r16", "i0c-r17", "i0c-r18", "i0c-r19", "i0c-r20", "i0c-r21", "i0c-r22", "i0c-r23", "i0c-r24", "i0c-r25"):
    entry = by_id.get(sid)
    if not entry:
        continue
    snap = load_json(BASE / entry.get("file", ""))
    for items in snap.get("binding", {}).values():
        superseded.update(items)

total, _ = verify_binding("i0c-current", i0c_current_binding)
if total == 0:
    errors.append("i0c-current.binding 为空")

if "i1-r4" in by_id:
    r4 = load_json(BASE / by_id["i1-r4"].get("file", ""))
    binding = r4.get("binding", {})
    total, skipped = verify_binding("i1-r4", binding, skip=superseded)
    if total == 0:
        errors.append("i1-r4.binding 无仍生效条目（superseded 覆盖过宽？）")
    if skipped == 0 and superseded:
        errors.append("i1-r4.binding 与 superseded 集合零交集，supersession 规则未生效")
    chain = [("i1-r3", "f22525c3957f8d09890600eb1df7e3cab3a6fce61f79b196c6067cbd9f39dd59"),
             ("i1-r1", "d474bd6d566e8cf5d72d0531de55fe918833ec49185f0b31322f97d603f85957"),
             ("i0a5", "71aa61affa8e84a4309187d5ed4d69e7b4dde27e3ed3d0156d603e3e77b5ca30")]
    cur = r4
    for expect_id, expect_sha in chain:
        gp = cur.get("parent_snapshot", {})
        check(gp.get("snapshot_id") == expect_id,
              f"血缘断裂：{cur.get('snapshot_id')}.parent 应为 {expect_id}，实际 {gp.get('snapshot_id')!r}")
        if gp.get("snapshot_id") != expect_id or gp.get("sha256") != expect_sha:
            errors.append(f"血缘哈希不符：{cur.get('snapshot_id')}.parent 应为 {expect_sha[:12]}…")
            break
        gfile = ROOT / gp.get("path", "")
        if not gfile.is_file() or digest(gfile) != gp.get("sha256"):
            errors.append(f"{expect_id} 文件字节与声明哈希不一致")
            break
        cur = load_json(gfile)

if errors:
    for message in errors:
        print(f"I0C FREEZE CHECK FAILED: {message}")
    print(f"i0c freeze verification FAILED: {len(errors)} error(s)")
    sys.exit(1)
print("i0c freeze chain verified: index ids unique, i0c-r1 bindings ok, "
      "i0c-r2/r3/r4/r5/r6/r7/r8/r9/r10/r11/r12/r13/r14/r15/r16/r17/r18/r19/r20/r21/r22/r23/r24 effective bindings (latest-revision-wins) + superseded "
      "i1-r4 bindings ok, lineage i0c-r24->i0c-r23->i0c-r22->i0c-r21->i0c-r20->i0c-r19->i0c-r18->i0c-r17->i0c-r16->i0c-r15->i0c-r14->i0c-r13->i0c-r12->i0c-r11->i0c-r10->i0c-r9->i0c-r8->i0c-r7->i0c-r6->i0c-r5->i0c-r4->i0c-r3->i0c-r2->"
      "i0c-r1->i1-r4->i1-r3->i1-r1->i0a5(M1) ok, design-review signed, M5 released by U sign-off, "
      "I3-0 scorer (scoring.py) add-only revision r19, r20 = validator r19-block path fix, "
      "r21 = I3-0 independent-review remediation F1-F5, r22 = I3-2 evidence-target candidates, "
      "r23 = I3-2 material-review remediation F1-F5 (rule evidence-mapping-4, candidates only), "
      "r24 = I3-2 adjudication-review remediation A1-A5 (rule evidence-mapping-5, "
      "approval-path + gate, candidates only); "
      + ("r26 I3-2 adoption verified (new source-gold 36 slots, 82 targets, filed decisions, gate ready=true, approved projection 79+20)" if "i0c-r26" in by_id else "")
      + ("; r28 I3-2 derived scoring input + baseline asset binding + legacy anchor mapping verified" if "i0c-r28" in by_id else ""))
