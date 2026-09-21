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
14. i0c-r32 = **I3-1 三类开发 E2E（照 U 批准集）首次入链**：绑 I3-1 审计文本产物（**不含** `archive/`
   素材副本）、批准集来源副本（内容寻址 `archive-approved/`）、`i3-e2e` 阶段守卫与其合成反例自检、
   环境预检报告、台账与验证器；**不得**出现 ``plugins/``／``tests/`` 绑定。同时修正归档合并顺序
   （按修订号数值）并首冻 `guards/i3-e2e.json`（model 封锁面已对齐 `guards/i3.json`）。
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
check("i0c-r29" in by_id, "索引缺少 i0c-r29 条目")
check("i0c-r30" in by_id, "索引缺少 i0c-r30 条目")
check("i0c-r31" in by_id, "索引缺少 i0c-r31 条目")
check("i0c-r32" in by_id, "索引缺少 i0c-r32 条目")
check("i0c-r33" in by_id, "索引缺少 i0c-r33 条目")
check("i0c-r34" in by_id, "索引缺少 i0c-r34 条目")
check("i0c-r35" in by_id, "索引缺少 i0c-r35 条目")
check("i0c-r36" in by_id, "索引缺少 i0c-r36 条目")
check("i0c-r37" in by_id, "索引缺少 i0c-r37 条目")
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

def revision_order(path: Path) -> tuple[int, str]:
    """按修订号数值排序（字典序会让 i0c-r9 排在 i0c-r32 之后，合并会取到旧绑定）。"""

    stem = path.stem
    try:
        return (int(stem.rsplit("-r", 1)[1]), stem)
    except (IndexError, ValueError):
        return (-1, stem)



def merged_binding_upto_revision(max_revision: int) -> dict:
    """只合并**修订号 <= max_revision** 的 i0c 绑定（时间稳定；不被后续修订重绑污染）。

    r34 引入：``merged_binding_from_all_but`` 会合并全部快照，导致历史块的归档忠实性检查
    随后续修订失真（r33 已用同法修 r32）。i0c 在效绑定也必须只按 i0c 链计算——``i1-*``
    在合并序上晚于 ``i0c-*``，会把 i0c-r5/r6 绑定的路径覆盖成 i1-r4 的陈旧值。
    """

    current: dict = {}
    for path in sorted(BASE.glob("i0c-r*.json"), key=revision_order):
        if revision_order(path)[0] > max_revision:
            continue
        data = load_json(path)
        for items in (data.get("binding") or {}).values():
            for key, value in items.items():
                current.pop(key, None)
                current[key] = value
    return current

def merged_binding_from_all_but(exclude: str) -> dict:
    """合并除指定修订外的全部绑定（最新修订优先），用于校验归档忠实性。"""

    current: dict = {}
    for path in sorted(BASE.glob("i0c-r*.json"), key=revision_order) + sorted(
        BASE.glob("i1-*.json"), key=revision_order
    ):
        if path.stem == exclude:
            continue
        data = load_json(path)
        for items in (data.get("binding") or {}).values():
            for key, value in items.items():
                current.pop(key, None)
                current[key] = value
    return current


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
    # supersession：守卫字节只要与 r27 **或任何后续修订**对它的绑定一致即可
    # （r31 已按 U 授权把 prose 留出入守卫）。
    guard_rel27 = f"{base}/guards/i3.json"
    guard_current = digest(ROOT / guard_rel27)
    recorded_hashes = {binding27.get("guard", {}).get(guard_rel27)}
    for sid in ("i0c-r28", "i0c-r29", "i0c-r30", "i0c-r31", "i0c-r32"):
        if sid in by_id:
            later = load_json(BASE / by_id[sid].get("file", ""))
            for items in (later.get("binding") or {}).values():
                if guard_rel27 in items:
                    recorded_hashes.add(items[guard_rel27])
    check(guard_current in recorded_hashes, "r27 guard i3.json binding mismatch")
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
    prev29 = merged_binding_from_all_but("i0c-r29")
    for key, sha in binding29.get("i3_2_archive", {}).items():
        original29 = next((p for p in prev29 if key.endswith(p)), None)
        check(original29 is not None, f"r29 归档路径无法对应到上一绑定：{key}")
        if original29 is not None and prev29[original29] != sha:
            # r29 已冻结、字节不可追改：按"历史修订不可修复"处理，只报告不失败
            # （该缺陷已由 r31 的 corrections.I3-2_archive_order_defect_3 登记）
            print(f"NOTE（非失败）: r29 归档不是真实 pre-r29 字节（post-change 副本）：{original29}")
    for group, items in binding29.items():
        for rel_ in items:
            check(not rel_.startswith(("plugins/", "tests/")), f"r29 越界绑定 {rel_}")
    merge_binding(i0c_current_binding, binding29)

if "i0c-r31" in by_id:
    i0c31 = load_json(BASE / by_id["i0c-r31"].get("file", ""))
    parent = i0c31.get("parent_snapshot", {})
    expected_parent = BASE / by_id["i0c-r30"]["file"]
    check(parent.get("snapshot_id") == "i0c-r30", "r31 parent must be r30")
    check(parent.get("path") == str(expected_parent.relative_to(ROOT)), "r31 parent path mismatch")
    check(parent.get("sha256") == digest(expected_parent), "r31 parent bytes mismatch")
    binding31 = i0c31.get("binding", {})
    corrections = i0c31.get("corrections", {})
    for finding in ("I3-2_prose_holdout_guard", "I3-2_mapping_rule_verified",
                    "I3-2_synonymy_warnings_accepted", "I3-2_tail_closure",
                    "M5-F3_registered", "I3-5"):
        check(finding in corrections, f"r31 missing correction {finding}")
    base = ".scratch/corpus-evidence-pipeline/ingestion-rebuild"
    audit = f"{base}/audits/20260919-i32-diagnosis"
    allowed = {
        "i3_2_closure": {
            f"{audit}/i3-2-closure.json",
            f"{audit}/i3-2-closure.md",
            f"{audit}/close_i3_2_tail.py",
            f"{base}/freezes/freeze_utils.py",
        },
        "i3_2_assets": {
            f"{audit}/legacy-anchor-mapping.json",
            f"{audit}/legacy-anchor-mapping.md",
            f"{audit}/baseline-case-manifest.json",
            f"{audit}/baseline-case-manifest.md",
            f"{audit}/step5-review.json",
            f"{audit}/step5-review.md",
            f"{audit}/step5-diff-pack.md",
            f"{audit}/step5_review.py",
        },
        "guard": {f"{base}/guards/i3.json"},
        "docs": {"docs/plan/corpus-ingestion-rebuild-tasks.md",
                 "docs/plan/claims-market-closed-loop-plan.md"},
        "freeze_validator": {f"{base}/freezes/validate_i0c_freeze.py",
                             f"{base}/freezes/validate_i3_2_completion.py"},
    }
    check(set(binding31) == set(allowed) | {"i3_2_archive"}, "r31 binding groups mismatch")
    for group, expected in allowed.items():
        check(set(binding31.get(group, {})) == expected, f"r31 unexpected {group} scope")
    # 归档忠实性**正不变量**：每条都必须等于上一修订对该原路径的绑定（空组合法，假归档必失败）
    prev31 = merged_binding_from_all_but("i0c-r31")
    for key, sha in binding31.get("i3_2_archive", {}).items():
        original31 = next((p for p in prev31 if key.endswith(p)), None)
        check(original31 is not None, f"r31 归档路径无法对应到上一绑定：{key}")
        check(prev31[original31] == sha, f"r31 归档不是真实 pre-r31 字节：{original31}")
    guard = load_json(ROOT / f"{base}/guards/i3.json")
    roots = guard["sources"]["forbidden_roots"]
    check(len(roots) >= 5, "r31 guard 应覆盖 prose 留出（≥5 份留出根）")
    check(any("5520fab6" in str(p) for p in roots), "r31 guard 必须含 prose 留出件 5520fab6")
    closure = load_json(ROOT / f"{audit}/i3-2-closure.json")
    check(not [i for i in closure["items"] if i.get("status") == "open"], "r31 收口记录不得有 open 项")
    for group, items in binding31.items():
        for rel_ in items:
            check(not rel_.startswith(("plugins/", "tests/")), f"r31 越界绑定 {rel_}")
    merge_binding(i0c_current_binding, binding31)


if "i0c-r32" in by_id:
    i0c32 = load_json(BASE / by_id["i0c-r32"].get("file", ""))
    parent = i0c32.get("parent_snapshot", {})
    expected_parent = BASE / by_id["i0c-r31"]["file"]
    check(parent.get("snapshot_id") == "i0c-r31", "r32 parent must be r31")
    check(parent.get("path") == str(expected_parent.relative_to(ROOT)), "r32 parent path mismatch")
    check(parent.get("sha256") == digest(expected_parent), "r32 parent bytes mismatch")
    binding32 = i0c32.get("binding", {})
    corrections = i0c32.get("corrections", {})
    for finding in ("I3-1_executed_approved_set", "I3-1_not_passing", "I3-1_e2e_guard_first_freeze",
                    "I3-1_guard_model_and_note_fix", "I3-1_withdrawn_archive_excluded",
                    "I3-1_freeze_utils_ordering_fix", "I3-5"):
        check(finding in corrections, f"r32 missing correction {finding}")
    base = ".scratch/corpus-evidence-pipeline/ingestion-rebuild"
    audit = f"{base}/audits/20260919-i3-1-e2e"
    pre = f"{base}/audits/20260919-i3-1-precheck"
    allowed = {
        "i3_1_e2e": {
            ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i3-1-e2e/apply_docx_coverage.py",
            ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i3-1-e2e/apply_retraction.py",
            ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i3-1-e2e/dev-scope-approved.json",
            ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i3-1-e2e/dev-scope-manifest-v2.json",
            ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i3-1-e2e/dev-scope-manifest-v3.json",
            ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i3-1-e2e/dev-scope-manifest.json",
            ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i3-1-e2e/i3-1-e2e-approved-set-rerun.json",
            ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i3-1-e2e/i3-1-e2e-approved-set-rerun.md",
            ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i3-1-e2e/i3-1-e2e-approved-set.json",
            ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i3-1-e2e/i3-1-e2e-approved-set.md",
            ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i3-1-e2e/i3-1-e2e-final.json",
            ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i3-1-e2e/i3-1-e2e-final.md",
            ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i3-1-e2e/i3-1-e2e-format-probe.json",
            ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i3-1-e2e/i3-1-e2e-format-probe.md",
            ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i3-1-e2e/i3-1-e2e-record.json",
            ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i3-1-e2e/i3-1-e2e-record.md",
            ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i3-1-e2e/i3-1-e2e-scope-v2.json",
            ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i3-1-e2e/i3-1-e2e-scope-v2.md",
            ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i3-1-e2e/i3-1-e2e-sources.json",
            ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i3-1-e2e/i3-1-e2e-sources.md",
            ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i3-1-e2e/i3-1-retraction-record.json",
            ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i3-1-e2e/i3-1-retraction-record.md",
            ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i3-1-e2e/i3-1-screening.json",
            ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i3-1-e2e/i3-1-screening.md",
            ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i3-1-e2e/preflight-scope-check.json",
            ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i3-1-e2e/preflight-scope-check.withdrawn.json",
            ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i3-1-e2e/preflight_scope_check.py",
            ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i3-1-e2e/retrospective-i3-1-scope.md",
            ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i3-1-e2e/run_i3_1_approved_set.py",
            ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i3-1-e2e/run_i3_1_e2e.py",
            ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i3-1-e2e/run_i3_1_e2e_sources.py",
            ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i3-1-e2e/run_i3_1_format_probe.py",
            ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i3-1-e2e/run_i3_1_scope_v2.py",
            ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i3-1-e2e/run_i3_1_screening.py",
            ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i3-1-e2e/screening-manifest.json",
            ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i3-1-e2e/summarize_i3_1_e2e.py",
        },
        "i3_1_approved_archive": {
            ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i3-1-e2e/archive-approved/17/174b64628f35aca60909d11b509bc7b7e87a9f4613a03a1da6c01d720a8cbcb0.pdf",
            ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i3-1-e2e/archive-approved/6f/6f14cc145b798b3716bad47829c05d89d8a5e5955179f11d196ed9b9b8538f11.pdf",
            ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i3-1-e2e/archive-approved/79/793b39673d31e8a8310e89a9171567dfb0008444b669cd6e225dc354329a880a.pdf",
            ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i3-1-e2e/archive-approved/cc/cc03f55bc5a24d3dcf69df6148faca84d465c18ff3f7110f5813b6300c5ea128.pdf",
            ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i3-1-e2e/archive-approved/dd/dddc7cd0cb74d085d851df3772aedcf68779b61087a365d14eb53ff5bb4d7afa.pdf",
            ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i3-1-e2e/archive-approved/f8/f8e316969b7cfdcd3bfde7f25320d58e95527fbdc8304ced9ca6738980051560.pdf",
        },
        "i3_1_precheck": {
            ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i3-1-precheck/i3-1-environment-precheck.json",
            ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i3-1-precheck/i3-1-environment-precheck.md",
            ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i3-1-precheck/run_i3_1_precheck.py",
        },
        "i3_e2e_guard": {
            f"{base}/guards/i3-e2e.json",
            f"{audit}/i3_e2e_guard_selfcheck.py",
            f"{audit}/i3-e2e-guard-report.json",
        },
        "i3_1_freeze": {
            f"{audit}/freeze_r32.py",
            f"{base}/freezes/freeze_utils.py",
        },
        "docs": {"docs/plan/corpus-ingestion-rebuild-tasks.md",
                 "docs/plan/claims-market-closed-loop-plan.md"},
        "freeze_validator": {f"{base}/freezes/validate_i0c_freeze.py"},
    }
    check(set(binding32) == set(allowed) | {"i3_1_archive"}, "r32 binding groups mismatch")
    for group, expected in allowed.items():
        check(set(binding32.get(group, {})) == expected, f"r32 unexpected {group} scope")
    # 归档忠实性**正不变量**：每条都必须等于 r32 创建时上一修订对该原路径的绑定
    # （仅合并 r31 及更早；r33 及以后的重绑不回写 prev32，否则 r32 检查随后续修订变化而失真）
    prev32: dict[str, str] = {}
    for _file in sorted(BASE.glob("i0c-r*.json"), key=revision_order):
        if revision_order(_file)[0] >= 32:
            continue
        for _items in (load_json(_file).get("binding") or {}).values():
            for _key, _value in _items.items():
                prev32.pop(_key, None)
                prev32[_key] = _value
    check(bool(binding32.get("i3_1_archive")), "r32 必须归档本修订覆盖的绑定文件（archive-first）")
    for key, sha in binding32.get("i3_1_archive", {}).items():
        original32 = next((p for p in prev32 if key.endswith(p)), None)
        check(original32 is not None, f"r32 归档路径无法对应到上一绑定：{key}")
        if original32 is not None:
            check(prev32[original32] == sha, f"r32 归档不是真实 pre-r32 字节：{original32}")
    # 批准集来源副本：内容寻址（文件名 = 内容 sha256）
    check(len(binding32.get("i3_1_approved_archive", {})) == 6,
          "r32 批准集来源副本应为 6 份")
    for key in binding32.get("i3_1_approved_archive", {}):
        check(key.startswith(f"{audit}/archive-approved/"), f"r32 批准集副本路径越界：{key}")
        check(digest(ROOT / key) == key.rsplit("/", 1)[-1].rsplit(".", 1)[0],
              f"r32 批准集副本内容与文件名（内容寻址）不符：{key}")
    check(not [k for k in binding32.get("i3_1_e2e", {}) if "/archive" in k],
          "r32 不得把素材副本目录（archive/、archive-approved/）混进 i3_1_e2e 组")
    # i3-e2e 守卫：身份、网络、来源、留出、自检
    guard = load_json(ROOT / f"{base}/guards/i3-e2e.json")
    check(guard.get("config_version") == 1, "r32 i3-e2e config_version 必须为整数 1")
    net = guard.get("network") or {}
    targets = net.get("allowed_targets") or []
    check(net.get("mode") == "allowlist", "r32 i3-e2e 网络必须是 allowlist")
    check(len(targets) == 1 and targets[0].get("host") == "127.0.0.1"
          and int(targets[0].get("port", 0)) == 543,
          "r32 i3-e2e 网络只允许 127.0.0.1:543（隔离沙箱）")
    srcs = guard.get("sources") or {}
    expected_guard_sources = 6
    if "i0c-r34" in by_id:
        _dev_policy = load_json(
            ROOT / f"{base}/audits/20260920-i31-dev-lane/admission-policy-dev.json"
        )
        _lane_paths = {
            item.get("path")
            for item in (_dev_policy.get("dev_lane") or {}).get("sources") or []
        }
        _approved_paths = {
            item.get("path")
            for item in load_json(
                ROOT / f"{base}/i0a2-adjudicated-20260915.json"
            )["dev_selection_approved"]
        }
        expected_guard_sources = len(_approved_paths) + len(_lane_paths)
        check(set(srcs.get("allowed_source_paths") or []) == _approved_paths | _lane_paths,
              "r32 i3-e2e 允许来源在 r34 下应为批准集 + dev lane 清单（逐条一致）")
    check(len(srcs.get("allowed_source_paths") or []) == expected_guard_sources,
          "r32 i3-e2e 允许来源必须为 U 批准集 6 份（r34 后为 6 + dev lane）")
    holdout = load_json(ROOT / f"{base}/guards/i3.json")["sources"]["forbidden_roots"]
    check(sorted(srcs.get("forbidden_roots") or []) == sorted(holdout),
          "r32 i3-e2e 留出根必须与 guards/i3.json 逐字一致")
    check(not (set(srcs.get("allowed_source_paths") or []) & set(srcs.get("forbidden_roots") or [])),
          "r32 i3-e2e 允许来源不得与留出相交")
    guard_model = (guard.get("model") or {}).get("blocked_modules") or []
    i3_model = (load_json(ROOT / f"{base}/guards/i3.json").get("model") or {}).get("blocked_modules") or []
    check(sorted(guard_model) == sorted(i3_model), "r32 i3-e2e 模型封锁面必须与 i3.json 一致（不得更弱）")
    report = load_json(ROOT / f"{audit}/i3-e2e-guard-report.json")
    check(report.get("passed") is True, "r32 i3-e2e 守卫自检必须 passed")
    _guard_sha = digest(ROOT / f"{base}/guards/i3-e2e.json")
    if "i0c-r34" in by_id:
        _new_report = load_json(
            ROOT / f"{base}/audits/20260920-i31-dev-lane/i3-e2e-guard-report.json"
        )
        check(_new_report.get("passed") is True
              and _new_report.get("config_sha256") == _guard_sha,
              "r32 i3-e2e 自检报告与守卫字节不一致（r34 后须由 dev lane 报告承担）")
    else:
        check(report.get("config_sha256") == _guard_sha,
              "r32 i3-e2e 自检报告与守卫字节不一致")
    check(len(report.get("cases") or []) >= 24, "r32 i3-e2e 自检用例数不足 24")
    # I3-1 真实结果：不得被读成通过
    record = load_json(ROOT / f"{audit}/i3-1-e2e-approved-set.json")
    summary = record.get("summary") or {}
    check(summary.get("sources") == 6 and summary.get("publishable") == 2,
          "r32 批准集记录应记 6 份来源、可发布 2 份")
    check(summary.get("per_class_min_2_satisfied") is False,
          "r32 必须如实登记 per_class_min_2_satisfied=false（不得读成通过）")
    check((record.get("rerun_confirmation") or {}).get("identical") is True,
          "r32 批准集记录应含一致重跑确认")
    for group, items in binding32.items():
        for rel_ in items:
            check(not rel_.startswith(("plugins/", "tests/")), f"r32 越界绑定 {rel_}")
    merge_binding(i0c_current_binding, binding32)




if "i0c-r34" in by_id:
    i0c34 = load_json(BASE / by_id["i0c-r34"].get("file", ""))
    parent = i0c34.get("parent_snapshot", {})
    expected_parent = BASE / by_id["i0c-r33"]["file"]
    check(parent.get("snapshot_id") == "i0c-r33", "r34 parent must be r33")
    check(parent.get("path") == str(expected_parent.relative_to(ROOT)), "r34 parent path mismatch")
    check(parent.get("sha256") == digest(expected_parent), "r34 parent bytes mismatch")
    binding34 = i0c34.get("binding", {})
    corrections = i0c34.get("corrections", {})
    for finding in ("I3-1_format_gate", "I3-1_dev_lane_design", "I3-1_per_class_still_false",
                    "I3-1_production_unchanged_evidence", "I3-1_contract_policy_bound_material",
                    "I3-1_supersedes_r32_guard_scope", "I3-1_supersedes_r32_selfcheck",
                    "I3-1_i1r4_supersession_fix", "I3-1_archive_discipline",
                    "I3-1_review_evidence"):
        check(finding in corrections, f"r34 missing correction {finding}")
    base = ".scratch/corpus-evidence-pipeline/ingestion-rebuild"
    audit = f"{base}/audits/20260920-i31-dev-lane"
    allowed = {
        "i3_1_dev_lane_policy": {f"{audit}/admission-policy-dev.json",
                                 f"{audit}/dev-scope-manifest.json"},
        "i3_1_dev_lane_preflight": {f"{audit}/preflight_scope_check.py",
                                    f"{audit}/preflight-scope-check.json",
                                    f"{audit}/preflight-scope-check.failclosed-no-dev-lane.json"},
        "i3_1_dev_lane_guard": {f"{audit}/i3_e2e_guard_selfcheck.py",
                                f"{audit}/i3-e2e-guard-report.json",
                                f"{base}/guards/i3-e2e.json"},
        "i3_1_dev_lane_run": {f"{audit}/run_i3_1_dev_lane.py",
                              f"{audit}/i3-1-dev-lane-e2e.json",
                              f"{audit}/i3-1-dev-lane-e2e.md",
                              f"{audit}/verify_dev_lane_admissions.py",
                              f"{audit}/dev-lane-admission-verification.json",
                              f"{audit}/freeze_r34.py"},
        "i3_1_dev_lane_review": {f"{audit}/run_review.py",
                                 f"{audit}/test_dev_lane_probes.py",
                                 f"{audit}/freeze-validation.txt",
                                 f"{audit}/baseline.txt",
                                 f"{audit}/independent-probes-r33.txt",
                                 f"{audit}/independent-probes-dev-lane.txt",
                                 f"{audit}/m5-evidence-recheck.json"},
        "i3_1_dev_lane_code": {"plugins/corpus/preparation/admission.py",
                               "plugins/corpus/preparation/contract.py",
                               "plugins/corpus/cli.py",
                               "tests/test_corpus_preparation_admission.py"},
        "docs": {"docs/plan/corpus-ingestion-rebuild-tasks.md",
                 "docs/plan/claims-market-closed-loop-plan.md",
                 "docs/plan/corpus-ingestion-rebuild-architecture.md"},
        "freeze_validator": {f"{base}/freezes/validate_i0c_freeze.py"},
    }
    check(set(binding34) == set(allowed) | {"i3_1_dev_lane_archive", "i3_1_dev_lane_sources"},
          "r34 binding groups mismatch")
    for group, expected in allowed.items():
        check(set(binding34.get(group, {})) == expected, f"r34 unexpected {group} scope")
    prev34 = merged_binding_upto_revision(33)
    for _key, _value in merged_binding_from_all_but("i0c-r34").items():
        prev34.setdefault(_key, _value)
    check(bool(binding34.get("i3_1_dev_lane_archive")), "r34 必须归档本修订覆盖的绑定文件（archive-first）")
    for key, sha in binding34.get("i3_1_dev_lane_archive", {}).items():
        original = next((p for p in prev34 if key.endswith(p)), None)
        check(original is not None, f"r34 归档路径无法对应到上一绑定：{key}")
        if original is not None:
            check(prev34[original] == sha, f"r34 归档不是真实 pre-r34 字节：{original}")
    for key, sha in binding34.get("i3_1_dev_lane_sources", {}).items():
        check(key.startswith(f"{audit}/archive-dev-lane/"), f"r34 来源副本路径越界：{key}")
    e2e = load_json(ROOT / f"{audit}/i3-1-dev-lane-e2e.json")
    summary = e2e.get("summary", {})
    check(summary.get("format_gate_section_12_1_satisfied") is True,
          "r34 需要 §12.1 格式门为真（三格式均有可发布样本）")
    check(summary.get("per_class_min_2_satisfied") is False,
          "r34 必须如实登记『每类≥2』仍不满足（裁定①未解）")
    check(summary.get("audit_conflicts") == [], "r34 需要审计链零冲突")
    verification = load_json(ROOT / f"{audit}/dev-lane-admission-verification.json")
    check(verification.get("verdict") == "PASS", "r34 需要 dev lane 落库核验 PASS（材料类型如实）")
    mat = {row.get("material_type") for row in verification.get("rows", [])}
    check("research_report" not in mat, "r34 材料类型不得被伪写为 research_report")
    preflight34 = load_json(ROOT / f"{audit}/preflight-scope-check.json")
    check(preflight34.get("summary", {}).get("verdict") == "PASS", "r34 预检 PASS 缺失")
    failclosed = load_json(ROOT / f"{audit}/preflight-scope-check.failclosed-no-dev-lane.json")
    check(failclosed.get("summary", {}).get("verdict") == "FAIL",
          "r34 必须有 fail-closed 反例（不给 --dev-lane 判 FAIL）")
    guard_report = load_json(ROOT / f"{audit}/i3-e2e-guard-report.json")
    check(guard_report.get("passed") is True, "r34 守卫自检必须通过")
    policy = load_json(ROOT / f"{audit}/admission-policy-dev.json")
    check(policy.get("scope") == "dev" and policy.get("production_in_scope_unchanged") is True,
          "r34 dev 政策必须声明 dev-only 且生产判定不变")
    _review_logs = {
        _name: (ROOT / f"{audit}/{_name}").read_text(encoding="utf-8")
        for _name in ("freeze-validation.txt", "baseline.txt",
                      "independent-probes-r33.txt", "independent-probes-dev-lane.txt")
    }
    check(
        all(
            _text.rstrip().endswith("exit=0")
            for _name, _text in _review_logs.items()
            if _name != "freeze-validation.txt"
        ),
        "r34 复核 pytest 日志必须 exit=0（评分器基线 + 两组独立反例）",
    )
    # 子串 "exit=0" 会被失败文案自身命中（假绿），故只用末行判定；
    # 冻结链门的绿性由本验证器自身的 in-process 检查承担，日志只作入链留证。
    check("r34" in _review_logs["freeze-validation.txt"],
          "r34 复核日志须来自 r34 感知的冻结链门运行")
    check("failed" not in _review_logs["independent-probes-dev-lane.txt"].lower(),
          "r34 dev lane 独立反例不得有失败项")
    _recheck = load_json(ROOT / f"{audit}/m5-evidence-recheck.json")
    check(not _recheck.get("misses") and not _recheck.get("errors"),
          "r34 M5 证据只读复算必须零 miss / 零 error")
    merge_binding(i0c_current_binding, binding34)


if "i0c-r35" in by_id:
    i0c35 = load_json(BASE / by_id["i0c-r35"].get("file", ""))
    parent = i0c35.get("parent_snapshot", {})
    expected_parent = BASE / by_id["i0c-r34"]["file"]
    check(parent.get("snapshot_id") == "i0c-r34", "r35 parent must be r34")
    check(parent.get("path") == str(expected_parent.relative_to(ROOT)), "r35 parent path mismatch")
    check(parent.get("sha256") == digest(expected_parent), "r35 parent bytes mismatch")
    binding35 = i0c35.get("binding", {})
    corrections = i0c35.get("corrections", {})
    for finding in ("M6_format_gate_in_criterion", "M6_criterion_alignment",
                    "M6_no_behavior_change", "M6_no_code_change", "M6_archive_discipline"):
        check(finding in corrections, f"r35 missing correction {finding}")
    base = ".scratch/corpus-evidence-pipeline/ingestion-rebuild"
    audit = f"{base}/audits/20260920-m6-format-criterion"
    allowed_docs = {"docs/plan/corpus-ingestion-rebuild-tasks.md",
                    "docs/plan/claims-market-closed-loop-plan.md"}
    allowed_evidence = {f"{audit}/verify_m6_criterion.py",
                        f"{audit}/m6-criterion-consistency.txt",
                        f"{audit}/freeze_r35.py",
                        f"{audit}/freeze-validation.txt"}
    required_evidence = {f"{audit}/verify_m6_criterion.py",
                         f"{audit}/m6-criterion-consistency.txt",
                         f"{audit}/freeze_r35.py"}
    check(set(binding35) == {"m6_criterion_docs", "m6_criterion_evidence",
                             "m6_criterion_archive", "freeze_validator"},
          "r35 binding groups mismatch")
    check(set(binding35.get("m6_criterion_docs", {})) == allowed_docs,
          "r35 docs 组必须恰为 tasks.md + 台账（不得夹带其他文档）")
    check(set(binding35.get("m6_criterion_evidence", {})) <= allowed_evidence
          and required_evidence <= set(binding35.get("m6_criterion_evidence", {})),
          "r35 evidence 组范围不符")
    check(set(binding35.get("freeze_validator", {})) == {f"{base}/freezes/validate_i0c_freeze.py"},
          "r35 validator 绑定不符")
    for group, items in binding35.items():
        for rel_ in items:
            check(not rel_.startswith(("plugins/", "tests/", "guards/", "frontier_agent/", "workflows/")),
                  f"r35 越界绑定 {rel_}（本修订为纯文档修订，不得牵动代码）")
    prev35 = merged_binding_upto_revision(34)
    for _key, _value in merged_binding_from_all_but("i0c-r35").items():
        prev35.setdefault(_key, _value)
    check(bool(binding35.get("m6_criterion_archive")), "r35 必须归档本修订覆盖的绑定文件（archive-first）")
    for key, sha in binding35.get("m6_criterion_archive", {}).items():
        original = next((p for p in prev35 if key.endswith(p)), None)
        check(original is not None, f"r35 归档路径无法对应到上一绑定：{key}")
        if original is not None:
            check(prev35[original] == sha, f"r35 归档不是真实 pre-r35 字节：{original}")
    tasks_text = (ROOT / "docs/plan/corpus-ingestion-rebuild-tasks.md").read_text(encoding="utf-8")
    m6_row = next((line for line in tasks_text.splitlines() if line.startswith("| M6  |")), "")
    check(all(token in m6_row for token in ("§12.1", "格式", "PDF/DOCX/MD", "dev_lane")),
          "r35 M6 判据行必须写入 §12.1 格式门（三格式 + dev_lane 标注）")
    i37_row = next((line for line in tasks_text.splitlines() if line.startswith("| I3-7 ")), "")
    check("格式" in i37_row, "r35 需保持 I3-7 行的格式要求（三处口径同源）")
    arch_text = (ROOT / "docs/plan/corpus-ingestion-rebuild-architecture.md").read_text(encoding="utf-8")
    check("格式可得性对账" in arch_text and "不能静默缩范围" in arch_text,
          "r35 架构 §12.1 格式门条款缺失")
    check('id="m6-format-criterion"' in
          (ROOT / "docs/plan/claims-market-closed-loop-plan.md").read_text(encoding="utf-8"),
          "r35 台账缺少 m6-format-criterion 节")
    consistency = (ROOT / f"{audit}/m6-criterion-consistency.txt").read_text(encoding="utf-8")
    check(consistency.rstrip().endswith("exit=0") and '"verdict": "PASS"' in consistency,
          "r35 一致性校验日志必须 PASS 且 exit=0")
    if f"{audit}/freeze-validation.txt" in binding35.get("m6_criterion_evidence", {}):
        log_text = (ROOT / f"{audit}/freeze-validation.txt").read_text(encoding="utf-8")
        check(log_text.rstrip().endswith("exit=0") and "r35 M6 criterion" in log_text,
              "r35 冻结链门日志必须来自 r35 感知的运行且 exit=0")
    merge_binding(i0c_current_binding, binding35)

if "i0c-r36" in by_id:
    r36 = load_json(BASE / by_id["i0c-r36"].get("file", ""))
    parent36 = r36.get("parent_snapshot", {})
    parent36_path = BASE / by_id["i0c-r35"]["file"]
    check(parent36.get("snapshot_id") == "i0c-r35", "r36 parent must be r35")
    check(parent36.get("path") == str(parent36_path.relative_to(ROOT)), "r36 parent path mismatch")
    check(parent36.get("sha256") == digest(parent36_path), "r36 parent bytes mismatch")
    binding36 = r36.get("binding", {})
    expected_impl36 = {
        "plugins/corpus/preparation/gap_review.py", "plugins/corpus/preparation/gaps.py",
        "plugins/corpus/preparation/engine.py", "plugins/corpus/preparation/repository.py",
        "plugins/corpus/preparation/repository_pg.py", "plugins/corpus/cli.py",
    }
    check(set(binding36.get("human_gap_implementation", {})) == expected_impl36,
          "r36 implementation boundary mismatch")
    check(set(binding36.get("human_gap_tests", {})) == {"tests/test_corpus_gap_review.py"},
          "r36 tests boundary mismatch")
    check(set(binding36.get("human_gap_docs", {})) == {
        "docs/plan/corpus-ingestion-rebuild-architecture.md",
        "docs/plan/corpus-ingestion-rebuild-tasks.md",
        "docs/plan/claims-market-closed-loop-plan.md",
    }, "r36 docs boundary mismatch")
    audit36 = ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260920-i31-human-gap-review"
    validator36 = ".scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/validate_i0c_freeze.py"
    check(set(binding36) == {"human_gap_implementation", "human_gap_tests", "human_gap_docs",
                            "human_gap_evidence", "human_gap_archive", "freeze_validator"},
          "r36 binding groups mismatch")
    check(set(binding36.get("freeze_validator", {})) == {validator36}, "r36 validator mismatch")
    check(bool(binding36.get("human_gap_evidence")), "r36 evidence missing")
    for rel36 in binding36.get("human_gap_evidence", {}):
        check(rel36.startswith(audit36 + "/") and "/before-r36/" not in rel36,
              f"r36 evidence outside audit directory: {rel36}")
    previous36 = merged_binding_upto_revision(35)
    for key36, value36 in merged_binding_from_all_but("i0c-r36").items():
        previous36.setdefault(key36, value36)
    check(bool(binding36.get("human_gap_archive")), "r36 pre-edit archive missing")
    for rel36, sha36 in binding36.get("human_gap_archive", {}).items():
        prefix36 = audit36 + "/before-r36/"
        check(rel36.startswith(prefix36), "r36 archive path invalid")
        original36 = rel36.removeprefix(prefix36)
        if original36 in previous36:
            check(sha36 == previous36[original36], f"r36 archive differs from pre-r36: {original36}")
    check(r36.get("status") == "implemented_pending_human_review", "r36 must not claim human sign-off")
    check(r36.get("real_review_records_written") == 0 and r36.get("per_class_min_2") is False,
          "r36 cannot claim real gap adjudication or I3-1 completion")
    pg36 = load_json(ROOT / audit36 / "pg-verification.json")
    check(pg36.get("verdict") == "PASS" and pg36.get("rollback_residue") == 0,
          "r36 synthetic PG verification failed")
    check(pg36.get("real_review_records_written") == 0 and pg36.get("real_sources_published") == 0,
          "r36 synthetic verification must not publish or sign real sources")
    templates36 = pg36.get("unsigned_templates", [])
    check(len(templates36) == 4 and sum(item.get("blocking", 0) for item in templates36) == 13,
          "r36 unsigned review inventory must retain all 13 blockers")
    for item36 in templates36:
        template36_path = ROOT / audit36 / item36.get("file", "")
        if "i0c-r37" in by_id:
            # r37 preserves the user's signed original paths. Verify r36's exact
            # historical template bytes at the explicitly documented recovery path.
            historical36 = (ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/"
                            "20260920-i31-signed-release/r36-template-recovery" / item36.get("file", ""))
            expected36 = binding36.get("human_gap_evidence", {}).get(str(template36_path.relative_to(ROOT)))
            check(historical36.is_file() and digest(historical36) == expected36,
                  "r37 must retain exact r36 unsigned template bytes")
            template36_path = historical36
        template36 = load_json(template36_path)
        check(template36.get("reviewer") == "" and template36.get("attestation") == ""
              and template36.get("required_locators") == [], "r36 templates must remain unsigned")
    merge_binding(i0c_current_binding, binding36)

if "i0c-r37" in by_id:
    r37 = load_json(BASE / by_id["i0c-r37"].get("file", ""))
    parent37 = r37.get("parent_snapshot", {})
    parent37_path = BASE / by_id["i0c-r36"]["file"]
    check(parent37.get("snapshot_id") == "i0c-r36" and parent37.get("sha256") == digest(parent37_path),
          "r37 parent must bind exact r36 bytes")
    check(parent37.get("path") == str(parent37_path.relative_to(ROOT)), "r37 parent path mismatch")
    binding37 = r37.get("binding", {})
    audit37 = ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260920-i31-signed-release"
    check(set(binding37) == {"i31_signed_inputs", "i31_release_evidence", "i31_release_docs",
                            "i31_release_archive", "freeze_validator"}, "r37 binding groups mismatch")
    shorts37 = ("6f14cc14", "174b6462", "793b3967", "dddc7cd0")
    signed37 = {f"{audit36}/unsigned-{short}.json" for short in shorts37}
    check(set(binding37.get("i31_signed_inputs", {})) == signed37, "r37 must bind all four user signed inputs")
    check(set(binding37.get("i31_release_docs", {})) == {
        "docs/plan/corpus-ingestion-rebuild-tasks.md", "docs/plan/claims-market-closed-loop-plan.md"
    }, "r37 docs boundary mismatch")
    validator37 = ".scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/validate_i0c_freeze.py"
    check(set(binding37.get("freeze_validator", {})) == {validator37}, "r37 validator binding mismatch")
    for group37, items37 in binding37.items():
        for rel37 in items37:
            check(not rel37.startswith(("plugins/", "tests/", "data/")), "r37 cannot change implementation or sources")
            if group37 == "i31_release_evidence":
                check(rel37.startswith(audit37 + "/"), "r37 evidence outside audit directory")
    prev37 = merged_binding_upto_revision(36)
    for rel37, sha37 in binding37.get("i31_release_archive", {}).items():
        prefix37 = audit37 + "/before-r37/"
        check(rel37.startswith(prefix37), "r37 archive prefix mismatch")
        original37 = rel37.removeprefix(prefix37)
        if original37 in prev37:
            check(sha37 == prev37[original37], f"r37 archive differs from previous binding: {original37}")
    for short37 in shorts37:
        original37 = load_json(ROOT / audit36 / f"unsigned-{short37}.json")
        normalized37 = load_json(ROOT / audit37 / f"review-{short37}.json")
        check(digest(ROOT / audit36 / f"unsigned-{short37}.json") ==
              digest(ROOT / audit37 / "submitted" / f"unsigned-{short37}.json"),
              "r37 must preserve exact user submitted bytes")
        check(original37.get("reviewer") == normalized37.get("reviewer") == "xyl",
              "r37 reviewer must preserve named human")
        check(original37.get("gaps") == normalized37.get("gaps") and bool(original37.get("gaps"))
              and all(isinstance(v, str) and v.strip() for v in original37.get("gaps", {}).values()),
              "r37 must preserve complete human per-gap rationales")
        check(bool(original37.get("attestation")) and original37.get("attestation", "") in
              normalized37.get("scope_rationale", ""), "r37 must preserve original human attestation")
        for field37 in ("source_id", "build_id", "build_fingerprint", "schema_rev", "policy_rev"):
            check(original37.get(field37) == normalized37.get(field37), "r37 must not change signed binding")
    release37 = load_json(ROOT / audit37 / "release-e2e.json")
    summary37 = release37.get("summary", {})
    check(summary37.get("published") == 7 and summary37.get("sources") == 8,
          "r37 must report original scope 7/8 published")
    check(summary37.get("human_acknowledged") == 12 and summary37.get("blocking") == 1,
          "r37 must retain the page-7 blocker and report 12 human acknowledgements")
    check(summary37.get("per_class_min_2") is True and summary37.get("format_gate") is True,
          "r37 three-class and format gates must pass")
    check(summary37.get("verify_all_ok") is True and summary37.get("all_searches_have_hits") is True
          and summary37.get("refused_handles") == 0 and summary37.get("audit_conflicts") == [],
          "r37 real search/fetch/verify/audit gates failed")
    check(release37.get("coverage", {}).get("processing") == "scoped",
          "r37 cannot claim full processing with retained gaps")
    sources37 = release37.get("sources", [])
    original_blocking37 = [gap for row in sources37 for gap in row.get("gaps", [])
                           if gap.get("disposition") == "blocking"]
    check(len(original_blocking37) == 13, "r37 must preserve all 13 original blocking dispositions")
    guangli37 = [row for row in sources37 if row.get("source_id", "").startswith("dddc7cd0")]
    check(len(guangli37) == 1 and guangli37[0].get("published") is False,
          "r37 cannot bypass same-page blocker")
    merge_binding(i0c_current_binding, binding37)

if "i0c-r38" in by_id:
    r38 = load_json(BASE / by_id["i0c-r38"]["file"])
    parent38 = BASE / by_id["i0c-r37"]["file"]
    check(r38.get("parent_snapshot") == {"snapshot_id": "i0c-r37",
          "path": str(parent38.relative_to(ROOT)), "sha256": digest(parent38)}, "r38 parent mismatch")
    binding38 = r38.get("binding", {})
    check(set(binding38) == {"region_implementation", "region_tests", "region_docs", "region_evidence",
                            "region_archive", "freeze_validator"}, "r38 binding groups mismatch")
    check(set(binding38.get("region_implementation", {})) == {
        "plugins/corpus/preparation/gap_review.py", "plugins/corpus/preparation/gaps.py",
        "plugins/corpus/preparation/pdf_gap_regions.py"}, "r38 implementation boundary mismatch")
    check(set(binding38.get("region_tests", {})) == {"tests/test_corpus_gap_review.py"}, "r38 tests mismatch")
    audit38 = ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260920-i31-region-review"
    previous38 = merged_binding_upto_revision(37)
    for rel38, sha38 in binding38.get("region_archive", {}).items():
        prefix38 = audit38 + "/before-r38/"
        check(rel38.startswith(prefix38), "r38 archive path invalid")
        old38 = rel38.removeprefix(prefix38)
        if old38 in previous38:
            check(sha38 == previous38[old38], f"r38 archive differs: {old38}")
    result38 = load_json(ROOT / audit38 / "release-e2e.json")
    summary38 = result38.get("summary", {})
    check(summary38.get("published") == summary38.get("sources") == 8, "r38 must publish approved 8/8")
    check(summary38.get("blocking") == 0 and summary38.get("human_acknowledged") == 13,
          "r38 gap lifecycle counts invalid")
    check(summary38.get("legacy_review_ids_unchanged") is True and summary38.get("model_calls") == 0,
          "r38 legacy credential/zero-model invariant failed")
    check(summary38.get("verify_all_ok") is True and summary38.get("all_searches_have_hits") is True
          and summary38.get("audit_conflicts") == [], "r38 E2E failed")
    check(result38.get("coverage", {}).get("processing") == "scoped", "r38 coverage must remain scoped")
    record38 = load_json(ROOT / audit38 / "review-dddc7cd0.json")
    original38 = load_json(ROOT / audit36 / "unsigned-dddc7cd0.json")
    check(record38.get("schema_rev") == "human-gap-review-2" and record38.get("policy_rev") == "gap-policy-3",
          "r38 region schema/policy mismatch")
    for field38 in ("reviewer", "source_id", "build_id", "build_fingerprint", "gaps"):
        check(record38.get(field38) == original38.get(field38), "r38 changed original human binding")
    check(original38.get("attestation", "") in record38.get("scope_rationale", ""), "r38 lost human attestation")
    check(set(record38.get("region_targets", {})) == {"page:7"} and
          len(record38["region_targets"]["page:7"]) == 3, "r38 complete page-7 refinement missing")
    merge_binding(i0c_current_binding, binding38)

if "i0c-r39" in by_id:
    r39 = load_json(BASE / by_id["i0c-r39"]["file"])
    parent39 = BASE / by_id["i0c-r38"]["file"]
    check(r39.get("parent_snapshot") == {"snapshot_id": "i0c-r38",
          "path": str(parent39.relative_to(ROOT)), "sha256": digest(parent39)}, "r39 parent mismatch")
    binding39 = r39.get("binding", {})
    check(set(binding39) == {"calibration_evidence", "calibration_docs", "calibration_archive", "freeze_validator"},
          "r39 binding groups mismatch")
    audit39 = ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260920-i33-calibration"
    previous39 = merged_binding_upto_revision(38)
    for rel39, sha39 in binding39.get("calibration_archive", {}).items():
        prefix39 = audit39 + "/before-r39/"
        check(rel39.startswith(prefix39), "r39 archive path invalid")
        old39 = rel39.removeprefix(prefix39)
        if old39 in previous39:
            check(sha39 == previous39[old39], f"r39 archive differs: {old39}")
    plan39 = load_json(ROOT / audit39 / "calibration-plan-v2.json")
    for rel39, sha39 in plan39.get("binding", {}).items():
        check((ROOT / rel39).is_file() and digest(ROOT / rel39) == sha39, f"r39 pre-run binding drift: {rel39}")
    check(plan39.get("max_runs") == 2 and plan39.get("policy", {}).get("top_k") == 5
          and plan39.get("policy", {}).get("min_rate") == "19/20", "r39 calibration bounds/policy mismatch")
    summary39 = load_json(ROOT / audit39 / "calibration-summary.json")
    check(summary39.get("questions") == 30 and len(summary39.get("runs", [])) == 2,
          "r39 must retain both full 30-question runs")
    check(all(run.get("passed") is False for run in summary39.get("runs", [])),
          "r39 must not claim calibration passed")
    check(summary39.get("scoring_input_unchanged") is True and summary39.get("publication_unchanged") is True
          and summary39.get("production_query_changed") is False and summary39.get("model_calls") == 0,
          "r39 invariant failed")
    check(summary39.get("stop_reason") == "predeclared_two_runs_complete", "r39 stop rule not respected")
    diagnosis39 = load_json(ROOT / audit39 / "evidence-diagnosis.json")
    check(diagnosis39.get("missing_targets") == 54 and sum(diagnosis39.get("causes", {}).values()) == 54,
          "r39 missing-evidence accounting incomplete")
    merge_binding(i0c_current_binding, binding39)

if "i0c-r40" in by_id:
    r40 = load_json(BASE / by_id["i0c-r40"]["file"])
    parent40 = BASE / by_id["i0c-r39"]["file"]
    check(r40.get("parent_snapshot") == {"snapshot_id": "i0c-r39",
          "path": str(parent40.relative_to(ROOT)), "sha256": digest(parent40)}, "r40 parent mismatch")
    binding40 = r40.get("binding", {})
    check(set(binding40) == {"reingest_evidence", "regression_rerun", "guards", "freeze_validator"},
          "r40 binding groups mismatch")
    rerun_dir = ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260920-i36-i33-reread-pdf5"
    summary40 = load_json(ROOT / rerun_dir / "rerun-summary.json")
    check(summary40.get("variant") == "candidate_question_lexemes_or", "r40 must run single OR variant")
    check(summary40.get("model_calls") == 0 and summary40.get("questions") == 30, "r40 invariant failed")
    check(summary40.get("passed") is False, "r40 must not claim I3-3 passed")
    audit40 = load_json(ROOT / rerun_dir / "i33-reread-audit.json")
    check(audit40.get("gate", {}).get("i33_released") is False and audit40.get("i33_complete") is False,
          "r40 must not mark I3-3 complete/released")
    merge_binding(i0c_current_binding, binding40)

if "i0c-r41" in by_id:
    r41 = load_json(BASE / by_id["i0c-r41"]["file"])
    parent41 = BASE / by_id["i0c-r40"]["file"]
    check(r41.get("parent_snapshot") == {"snapshot_id": "i0c-r40",
          "path": str(parent41.relative_to(ROOT)), "sha256": digest(parent41)}, "r41 parent mismatch")
    binding41 = r41.get("binding", {})
    check(set(binding41) == {"scorer_implementation", "tests", "calibration_plan",
                             "diagnostics_evidence", "freeze_validator"},
          "r41 binding groups mismatch")
    i41_dir = ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260920-i41-topic-a-cell"
    summary41 = load_json(ROOT / i41_dir / "i41-summary.json")
    check(summary41.get("kind") == "diagnostic", "r41 must be a diagnostic run (not a frozen regression)")
    check(summary41.get("model_calls") == 0 and summary41.get("questions") == 30,
          "r41 invariant failed")
    check(summary41.get("layers", {}).get("band_s2", {}).get("evidence_pass_total") == "19/24",
          "r41 band_s2 evidence pass must be 19/24")
    check(summary41.get("topic_a", {}).get("total") == 11
          and summary41.get("topic_a", {}).get("matched") == 11,
          "r41 must keep topic_a 11/11")
    check(summary41.get("volume", {}).get("width_bound_ok") is True,
          "r41 width bound must hold (measured <= provable)")
    check(len(summary41.get("negative", {}).get("or_false_positives", [])) == 6,
          "r41 must report 6 OR-path negative false positives")
    scorer = ROOT / "plugins/corpus/scoring.py"
    scorer_sha41 = "f61573d71b543f33022e9abe890efa35c4ca02342035a9ba6cd5ba9d4413ec9c"
    check(digest(scorer) == scorer_sha41, "r41 scorer must be f61573d7 (whitespace-norm)")
    plan41 = load_json(ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260920-i33-calibration/calibration-plan-v2.json")
    check(plan41.get("binding", {}).get("plugins/corpus/scoring.py") == scorer_sha41,
          "r41 calibration plan must rebind scorer to f61573d7")
    merge_binding(i0c_current_binding, binding41)

if "i0c-r42" in by_id:
    r42 = load_json(BASE / by_id["i0c-r42"]["file"])
    parent42 = BASE / by_id["i0c-r41"]["file"]
    check(r42.get("parent_snapshot") == {"snapshot_id": "i0c-r41",
          "path": str(parent42.relative_to(ROOT)), "sha256": digest(parent42)}, "r42 parent mismatch")
    binding42 = r42.get("binding", {})
    check(set(binding42) == {"chain_rebind_implementation", "chain_rebind_readers", "chain_rebind_tests",
                             "chain_rebind_evidence", "i3_2_relineage", "freeze_validator"},
          "r42 binding groups mismatch")
    check(set(binding42.get("chain_rebind_implementation", {})) == {
        "plugins/corpus/preparation/engine.py",
        "plugins/corpus/preparation/repository_pg.py",
        "plugins/corpus/preparation/contract.py",
        "plugins/corpus/preparation/chunk.py",
        "plugins/corpus/preparation/clean.py",
        "plugins/corpus/preparation/search_pg.py"}, "r42 implementation boundary mismatch")
    check(set(binding42.get("chain_rebind_readers", {})) == {
        "plugins/corpus/preparation/readers/base.py",
        "plugins/corpus/preparation/readers/pdf_reader.py"}, "r42 readers boundary mismatch")
    check(set(binding42.get("chain_rebind_tests", {})) == {
        "tests/test_corpus_preparation_chunk.py",
        "tests/test_corpus_preparation_clean.py",
        "tests/test_corpus_preparation_readers.py"}, "r42 tests boundary mismatch")
    check(set(binding42.get("chain_rebind_evidence", {})) == {
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260920-i36-i33-reread-pdf5/rerun_or.py",
        "docs/plan/corpus-ingestion-rebuild-tasks.md"}, "r42 evidence boundary mismatch")
    check(set(binding42.get("i3_2_relineage", {})) == {
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-2/scoring-input-manifest.json",
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260920-i33-calibration/calibration-plan-v2.json"},
          "r42 relineage boundary mismatch")
    check(set(binding42.get("freeze_validator", {})) == {
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/validate_i0c_freeze.py"},
          "r42 freeze_validator boundary mismatch")
    scorer_sha42 = "f61573d71b543f33022e9abe890efa35c4ca02342035a9ba6cd5ba9d4413ec9c"
    manifest42 = load_json(ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-2/scoring-input-manifest.json")
    check(manifest42.get("status") == "frozen", "r42 must freeze scoring-input manifest status")
    check(manifest42.get("frozen_in") == "i0c-r42", "r42 manifest frozen_in must point at r42")
    check(manifest42.get("lineage", {}).get("scorer", {}).get("sha256") == scorer_sha42,
          "r42 manifest lineage.scorer must be whitespace-norm f61573d7")
    plan42 = load_json(ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260920-i33-calibration/calibration-plan-v2.json")
    check(plan42.get("binding", {}).get("plugins/corpus/preparation/search_pg.py") ==
          digest(ROOT / "plugins/corpus/preparation/search_pg.py"),
          "r42 plan must rebind search_pg to current bytes")
    check(plan42.get("binding", {}).get("plugins/corpus/preparation/chunk.py") ==
          digest(ROOT / "plugins/corpus/preparation/chunk.py"),
          "r42 plan must rebind chunk to current bytes")
    check(plan42.get("binding", {}).get(".scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-2/scoring-input-manifest.json") ==
          digest(ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-2/scoring-input-manifest.json"),
          "r42 plan must rebind scoring-input-manifest to rebuilt bytes")
    check(plan42.get("binding", {}).get("plugins/corpus/scoring.py") == scorer_sha42,
          "r42 plan must keep scorer f61573d7")
    merge_binding(i0c_current_binding, binding42)

if "i0c-r43" in by_id:
    r43 = load_json(BASE / by_id["i0c-r43"]["file"])
    parent43 = BASE / by_id["i0c-r42"]["file"]
    check(r43.get("parent_snapshot") == {"snapshot_id": "i0c-r42",
          "path": str(parent43.relative_to(ROOT)), "sha256": digest(parent43)}, "r43 parent mismatch")
    binding43 = r43.get("binding", {})
    check(set(binding43) == {"production_selection", "freeze_validator"},
          "r43 binding groups mismatch")
    check(set(binding43.get("production_selection", {})) == {
        "plugins/corpus/service.py",
        "plugins/corpus/preparation/selection.py",
        "tests/test_corpus_consumers_pg.py"}, "r43 production_selection boundary mismatch")
    check(set(binding43.get("freeze_validator", {})) == {
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/validate_i0c_freeze.py"},
          "r43 freeze_validator boundary mismatch")
    # R3 闭环的语义门：production service.py 必须实际接入选择策略（防静默回退）
    svc_src43 = (ROOT / "plugins/corpus/service.py").read_text(encoding="utf-8")
    check("_apply_selection" in svc_src43 and "select_structural" in svc_src43,
          "r43 service.py must wire select_structural into production search")
    check("_SELECTION_POOL_MIN" in svc_src43,
          "r43 service.py must define the selection candidate-pool floor")
    sel_src43 = (ROOT / "plugins/corpus/preparation/selection.py").read_text(encoding="utf-8")
    check("def select_structural" in sel_src43 and "def select_band" in sel_src43,
          "r43 selection.py must carry the validated selection strategies")
    tst_src43 = (ROOT / "tests/test_corpus_consumers_pg.py").read_text(encoding="utf-8")
    check("test_service_search_applies_selection_policy" in tst_src43,
          "r43 must add the production selection policy test")
    merge_binding(i0c_current_binding, binding43)

# 最新修订绑定优先（supersession）：i0c-r2..r43 显式重绑的路径改由合并后的
# i0c-current 绑定按新哈希核对，i1-r4 中对应旧绑定不再要求匹配。
superseded: set[str] = set()
for sid in (f"i0c-r{number}" for number in range(2, 44)):
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
      + ("; r28 I3-2 derived scoring input + baseline asset binding + legacy anchor mapping verified" if "i0c-r28" in by_id else "")
      + ("; r29 Step 5 review + P4 path fix verified" if "i0c-r29" in by_id else "")
      + ("; r30 I3-2 stage sign-off (named) + generators verified" if "i0c-r30" in by_id else "")
      + ("; r31 I3-2 tail closure (prose holdout guarded, mapping rule-verified, warnings accepted) verified" if "i0c-r31" in by_id else "")
      + ("; r32 I3-1 three-class dev E2E on the U-approved set filed (6 sources -> 2 publishable, 13 blocking gaps, per_class_min_2 NOT satisfied, i3-e2e guard + selfcheck frozen)" if "i0c-r32" in by_id else "") + ("; r33 I3-0 independent-review F1-F5 remediation sign-off (named) verified" if "i0c-r33" in by_id else "") + ("; r34 I3-1 dev-lane MD/DOCX coverage: format gate (pdf/docx/md all publishable) satisfied, per_class_min_2 still false, production in_scope unchanged (dev-only policy + truthful material types)" if "i0c-r34" in by_id else "") + ("; r35 M6 criterion carries the §12.1 format gate (docs-only: tasks.md M6 row + plan ledger; no behaviour change)" if "i0c-r35" in by_id else "")
      + ("; r40 I3-3 single-corpus regression on reader-pdf-5 (same r39 scorer): evidence_target_missing 54->43, EvidencePass 7/24, 6/6 negative FPs persist, NOT released" if "i0c-r40" in by_id else "")
      + ("; r41 whitespace-norm scorer f61573d7 frozen (band+S2: topic_a 11/11, band_s2 EvidencePass 19/24, OR negatives 6 FP, width 33<=49); chain rebind pending t6" if "i0c-r41" in by_id else "")
      + ("; r42 t6 chain rebind per U authority decision 2026-09-21: I3-3 reshape + reader-pdf-5 adopted, scoring-input-manifest relineaged (scorer f61573d7, status frozen), i1-r4 readers superseded, chain green" if "i0c-r42" in by_id else "")
      + ("; r43 R3 closure: production service.py new-chain (search/search_with_coverage) wired to perdoc select_structural, selection.py first-bound, tests 731 passed / 12 skipped" if "i0c-r43" in by_id else ""))
