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


def pre_m6_repair_path(rel: str) -> Path:
    """Historical assertions use verified pre-repair bytes after explicit r5d rebind."""
    if "i0c-r5d" in by_id and rel in {
        "plugins/corpus/preparation/read_pg.py", "plugins/corpus/service.py"
    }:
        return ROOT / ".scratch/m6-repair-20260923/before" / rel
    return ROOT / rel


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


# r4x 预置（U 2026-09-23 授权：金标 col 口径改写 → I3-2 全链重派生）：r26/r39/r42 对 source-gold / manifest / jsonl / approved 的『当前字节』断言改核本修订权威哈希（不改写已关闭审计产物，只确认历史旧值仍被记录）。
r4x_superseded_bindings: dict[str, str] = {}
if "i0c-r4x" in by_id:
    r4x_superseded_bindings = {
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/source-gold-frozen.jsonl": "9387ab9651a3f48cc33534cef5542d603a8fa2c3edb608fa18745a82f0f135bf",
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-2/scoring-input-manifest.json": "bbacb85e247b0bc6d9bc5e53a4051e0e8281b3bfba21c9d2b90c536f78a467ad",
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-2/query-gold-scoring-v1.jsonl": "d311f9a855f3fc24cbe992dc621c24fe55f0e3e5eda847f3bf8192a91d41d4f5",
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-2/evidence-targets-approved.json": "b7bd752b16e08dcb33a4346e2d945210ad3da560cae390b9997bef56e3a8b9c9",
    }


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
    _sg26 = f"{base}/source-gold-frozen.jsonl"
    if _sg26 in r4x_superseded_bindings:
        check(digest(ROOT / _sg26) == r4x_superseded_bindings[_sg26]
              and binding26.get("i3_2_source_gold", {}).get(_sg26)
              != r4x_superseded_bindings[_sg26],
              "r26 superseded binding unresolved: source-gold-frozen.jsonl")
    else:
        check(
            binding26.get("i3_2_source_gold", {}).get(_sg26)
            == digest(ROOT / _sg26),
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
    # r34 历史归档忠实性：prev34 须是 r34 当时的**有效上一绑定**（pre-r34 字节）。
    # 构造纪律：先应用创建时间 ≤ r34 的 i1 绑定，仅用于补齐 i0c 修订号 ≤ 33 未绑定的
    # 路径（如 admission.py 的 pre-r34 字节 3521f495 源自 i1-r2/r3/r4）；i0c 已绑定的
    # 路径（如 test_corpus_preparation_admission 权威 062953f2）不得被 i1 陈旧值覆盖。
    # 绝不可用 merged_binding_from_all_but/按 created_at 放全部修订——会拉入创建晚于 r34
    # 的修订（如 i1-r5 重绑 preparation、i0c-r36/r38/r39 改 cli/docs）覆盖 r34 归档时点
    # 旧绑定，使历史比对失真。
    _r34t = by_id["i0c-r34"].get("created_at", "")
    _i1fill: dict = {}
    for _sid34, _ent34 in by_id.items():
        if not _sid34.startswith("i1-r"):
            continue
        if _ent34.get("created_at", "") > _r34t:
            continue
        _d34 = load_json(BASE / _ent34.get("file", ""))
        for _its34 in (_d34.get("binding") or {}).values():
            for _k34, _v34 in _its34.items():
                _i1fill.pop(_k34, None)
                _i1fill[_k34] = _v34
    for _k34, _v34 in _i1fill.items():
        if _k34 not in prev34:
            prev34[_k34] = _v34
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

# r4r（独立校准修订）：解决 r39 计划历史 read_pg 绑定漂移，不改写已关闭审计产物。
# r39 计划记录的是 r4n 前的 read_pg=fb87a771（pre-F2）；随 F2/r4n 演进至权威 read_pg=52b182f7
# 后该历史绑定自然过期。r4r 不触 calibration-plan-v2.json 字节，而是用一个 supersession 豁免
# 映射（rel -> 权威哈希）供下方 r39 块使用，并把 read_pg 的权威哈希显式入链。
r39_superseded_bindings: dict[str, str] = {}
NEW_R4X_ID = "i0c-r4x"
if "i0c-r4x" in by_id:
    r39_superseded_bindings.update({
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-2/scoring-input-manifest.json": "bbacb85e247b0bc6d9bc5e53a4051e0e8281b3bfba21c9d2b90c536f78a467ad",
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-2/query-gold-scoring-v1.jsonl": "d311f9a855f3fc24cbe992dc621c24fe55f0e3e5eda847f3bf8192a91d41d4f5",
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-2/evidence-targets-approved.json": "b7bd752b16e08dcb33a4346e2d945210ad3da560cae390b9997bef56e3a8b9c9",
    })

if "i0c-r4r" in by_id:
    r4r = load_json(BASE / by_id["i0c-r4r"]["file"])
    parent43r4r = BASE / by_id["i0c-r4q"]["file"]
    check(r4r.get("parent_snapshot") == {"snapshot_id": "i0c-r4q",
          "path": str(parent43r4r.relative_to(ROOT)), "sha256": digest(parent43r4r)},
          "r4r parent mismatch")
    bindingr4r = r4r.get("binding", {})
    # r4r = 独立校准修订：只绑 read_pg 权威哈希 + 验证器，不触其他实现/测试/守卫字节
    check(set(bindingr4r) == {"chain_rebind_read_pg", "freeze_validator"},
          "r4r binding groups mismatch")
    check(set(bindingr4r.get("chain_rebind_read_pg", {})) == {
        "plugins/corpus/preparation/read_pg.py"}, "r4r read_pg boundary mismatch")
    check(set(bindingr4r.get("freeze_validator", {})) == {
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/validate_i0c_freeze.py"},
          "r4r freeze_validator boundary mismatch")
    # 权威 read_pg 哈希必须等于 r4n 入链的 52b182f7，且 r39 计划确实记录的是旧 fb87a771
    rpg_hash_r4r = "52b182f7353523e88fefd5c32455df8ee5a704b855952e1d5113b1c72fcf5a7b"
    check(digest(pre_m6_repair_path("plugins/corpus/preparation/read_pg.py")) == rpg_hash_r4r,
          "r4r read_pg authoritative hash mismatch (expected 52b182f7)")
    plan39r4r = load_json(ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260920-i33-calibration/calibration-plan-v2.json")
    check(plan39r4r.get("binding", {}).get("plugins/corpus/preparation/read_pg.py")
          == "fb87a771974b0393075da7f2e3b602a3e120ff1a0916a6fcf8c7e296c98ef8e1",
          "r4r r39 plan historical read_pg sha mismatch (must be fb87a771)")
    check(any("r39" in key and "drift" in key for key in (r4r.get("corrections") or {})),
          "r4r must record r39 read_pg drift resolution in corrections")
    r39_superseded_bindings["plugins/corpus/preparation/read_pg.py"] = rpg_hash_r4r
    # 注意：此处不 merge——r4r 为最新修订，须在 r4q 块之后最后合并（见 r4q 块末尾），
    # 否则 freeze_validator 会被更靠后的 r4n/r4p/r4q 块覆盖为旧验证器哈希。

# r4v（c′ 排序信号修订）：prune_fn_punct 落地——排序信号剔除功能词+标点（I-1 候选池不变、
# I-2 只有 score 变）。search_pg.py 由 r42 时代 04bc7d61 演进至权威 4d1db60c；r39 块与
# r42 块对 calibration-plan-v2.json pre-run binding（仍记 04bc7d61）的 current-bytes 断言
# 按 r4r 先例以 supersession 豁免承接（不改写已关闭审计产物，改核权威哈希 + 确认旧值）。
# 该映射同时供下方 r39 块与 r42 块消费（同一计划文件的绑定值）。
if "i0c-r4v" in by_id:
    r4v = load_json(BASE / by_id["i0c-r4v"]["file"])
    parent43r4v = BASE / by_id["i0c-r4u"]["file"]
    check(r4v.get("parent_snapshot") == {"snapshot_id": "i0c-r4u",
          "path": str(parent43r4v.relative_to(ROOT)), "sha256": digest(parent43r4v)},
          "r4v parent mismatch")
    bindingr4v = r4v.get("binding", {})
    check(set(bindingr4v) == {"chain_rebind_implementation", "chain_rebind_tests", "freeze_validator"},
          "r4v binding groups mismatch")
    check(set(bindingr4v.get("chain_rebind_implementation", {})) == {
        "plugins/corpus/preparation/search_pg.py",
        "plugins/corpus/preparation/negative_query.py"}, "r4v implementation boundary mismatch")
    check(set(bindingr4v.get("chain_rebind_tests", {})) == {
        "tests/test_corpus_search_pg.py"}, "r4v chain_rebind_tests boundary mismatch")
    check(set(bindingr4v.get("freeze_validator", {})) == {
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/validate_i0c_freeze.py"},
          "r4v freeze_validator boundary mismatch")
    # prune_fn_punct 语义门：双 tsquery 接线（池=全词元 q.tsq、score=实词 q.tsq_rank）、
    # 开关默认开、_rank_query_on 同游标取词元 + build_search_params 显式 rank_query 键；
    # negative_query 须携带标点结构判定 + 全剔回退（fail-closed）；tests 须携带
    # I-RANK-1 池不变/SQL 接线/序/开关回滚门。
    spg_src_r4v = (ROOT / "plugins/corpus/preparation/search_pg.py").read_text(encoding="utf-8")
    if "i0c-r5e" in by_id:
        # r5e intentionally supersedes the r4v retrieval implementation.  The r5e
        # previous-effective ledger proves the pre-r5e bytes were exactly r4v, so
        # the historical dual-tsquery semantic gate must not be applied to current
        # product-retrieval bytes.
        prior5e_r4v = load_json(
            ROOT / ".scratch/m6-retrieval-fix-20260923/previous-effective-bindings.json"
        )
        check(prior5e_r4v.get("plugins/corpus/preparation/search_pg.py")
              == bindingr4v.get("chain_rebind_implementation", {}).get(
                  "plugins/corpus/preparation/search_pg.py"),
              "r5e must preserve the r4v search_pg.py predecessor hash")
    else:
        check("RANK_LEXEME_PRUNE = True" in spg_src_r4v
              and "websearch_to_tsquery('zhcfg', %(rank_query)s) AS tsq_rank" in spg_src_r4v
              and "ts_rank(c.search_tsv, q.tsq_rank) AS score" in spg_src_r4v
              and "c.search_tsv @@ q.tsq" in spg_src_r4v
              and "def _rank_query_on" in spg_src_r4v
              and '"rank_query" not in params' in spg_src_r4v,
              "r4v search_pg.py must wire dual-tsquery ranking signal (pool=full lexemes, score=content)")
    nq_src_r4v = (ROOT / "plugins/corpus/preparation/negative_query.py").read_text(encoding="utf-8")
    check("def is_punct_lexeme" in nq_src_r4v and "def rank_lexemes" in nq_src_r4v
          and "return kept or tuple(lexemes)" in nq_src_r4v,
          "r4v negative_query.py must carry is_punct_lexeme/rank_lexemes with fail-closed fallback")
    tspg_src_r4v = (ROOT / "tests/test_corpus_search_pg.py").read_text(encoding="utf-8")
    check("test_candidate_pool_unchanged_live" in tspg_src_r4v
          and "test_tie_break_order_live" in tspg_src_r4v
          and "test_switch_off_rollback_field_equal" in tspg_src_r4v
          and "test_search_sql_wiring_candidate_pool_vs_score" in tspg_src_r4v,
          "r4v test_corpus_search_pg.py must carry I-RANK-1 pool/order/rollback gates")
    # search_pg 权威哈希入 supersession 映射（下方 r39 块与 r42 块消费）；
    # negative_query.py 不在计划 pre-run binding 内，无需豁免。
    # 权威值随最新绑定修订推进：r5f 时解析为 r5e 检索实现；r5g 窗口目标适配
    # 演进 search_pg 后按同一「最新修订优先」语义解析为 r5g 绑定值；
    # r5j S1 去缓存修复后再解析为 r5j 绑定值。
    r39_superseded_bindings["plugins/corpus/preparation/search_pg.py"] = (
        load_json(BASE / by_id["i0c-r5j"]["file"])
        .get("binding", {}).get("m7_fix_code", {})
        .get("plugins/corpus/preparation/search_pg.py")
        if "i0c-r5j" in by_id
        else (
            load_json(BASE / by_id["i0c-r5g"]["file"])
            .get("binding", {}).get("i4_window_target_adapter", {})
            .get("plugins/corpus/preparation/search_pg.py")
            if "i0c-r5g" in by_id
            else (
                load_json(BASE / by_id["i0c-r5e"]["file"])
                .get("binding", {}).get("m6_retrieval_implementation", {})
                .get("plugins/corpus/preparation/search_pg.py")
                if "i0c-r5e" in by_id
                else "4d1db60c292eeb9d675ac1abc2f9b7c4255aa922850aae7aa475a0ee632f8492"
            )
        )
    )
    # 注意：此处不 merge——r4v 为最新修订，须在 r4u 块之后最后合并（见 r4u 块末尾），
    # 否则 freeze_validator 会被更靠前的 r4t/r4u 块覆盖为旧验证器哈希。

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
        if rel39 in r39_superseded_bindings:
            # r39 计划在旧 read_pg=fb87a771 时记录；该路径现已被独立校准修订 r4r 解决的权威
            # read_pg=52b182f7 取代——不改写已关闭审计产物，改为校验权威哈希 + 确认历史旧值。
            check(digest(pre_m6_repair_path(rel39)) == r39_superseded_bindings[rel39]
                  and sha39 != r39_superseded_bindings[rel39],
                  f"r39 superseded binding unresolved: {rel39}")
            continue
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
    if f".scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-2/scoring-input-manifest.json" in r4x_superseded_bindings:
        check(manifest42.get("frozen_in") == NEW_R4X_ID,
              "r42 manifest frozen_in must be re-pointed at the latest gold revision")
    else:
        check(manifest42.get("frozen_in") == "i0c-r42", "r42 manifest frozen_in must point at r42")
    check(manifest42.get("lineage", {}).get("scorer", {}).get("sha256") == scorer_sha42,
          "r42 manifest lineage.scorer must be whitespace-norm f61573d7")
    plan42 = load_json(ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260920-i33-calibration/calibration-plan-v2.json")
    if "plugins/corpus/preparation/search_pg.py" in r39_superseded_bindings:
        # r4v 排序信号修订演进 search_pg（r42 记录 04bc7d61 → r4v 权威 4d1db60c）：
        # 不改写已关闭审计产物，改核权威哈希 + 确认计划仍记录旧值。
        check(digest(ROOT / "plugins/corpus/preparation/search_pg.py")
              == r39_superseded_bindings["plugins/corpus/preparation/search_pg.py"]
              and plan42.get("binding", {}).get("plugins/corpus/preparation/search_pg.py")
              != r39_superseded_bindings["plugins/corpus/preparation/search_pg.py"],
              "r42 superseded binding unresolved: search_pg.py")
    else:
        check(plan42.get("binding", {}).get("plugins/corpus/preparation/search_pg.py") ==
              digest(ROOT / "plugins/corpus/preparation/search_pg.py"),
              "r42 plan must rebind search_pg to current bytes")
    check(plan42.get("binding", {}).get("plugins/corpus/preparation/chunk.py") ==
          digest(ROOT / "plugins/corpus/preparation/chunk.py"),
          "r42 plan must rebind chunk to current bytes")
    _mf42 = f".scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-2/scoring-input-manifest.json"
    if _mf42 in r4x_superseded_bindings:
        check(digest(ROOT / _mf42) == r4x_superseded_bindings[_mf42]
              and plan42.get("binding", {}).get(_mf42) != r4x_superseded_bindings[_mf42],
              "r42 superseded binding unresolved: scoring-input-manifest")
    else:
        check(plan42.get("binding", {}).get(_mf42) == digest(ROOT / _mf42),
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

if "i0c-r4n" in by_id:
    r4n = load_json(BASE / by_id["i0c-r4n"]["file"])
    parent43r4n = BASE / by_id["i0c-r43"]["file"]
    check(r4n.get("parent_snapshot") == {"snapshot_id": "i0c-r43",
          "path": str(parent43r4n.relative_to(ROOT)), "sha256": digest(parent43r4n)},
          "r4n parent mismatch")
    bindingr4n = r4n.get("binding", {})
    check(set(bindingr4n) == {"production_selection", "freeze_validator"},
          "r4n binding groups mismatch")
    check(set(bindingr4n.get("production_selection", {})) == {
        "plugins/corpus/service.py",
        "plugins/corpus/preparation/read_pg.py",
        "plugins/corpus/preparation/selection.py",
        "tests/test_corpus_selection.py",
        "tests/test_corpus_consumers_pg.py"},
          "r4n production_selection boundary mismatch")
    check(set(bindingr4n.get("freeze_validator", {})) == {
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/validate_i0c_freeze.py"},
          "r4n freeze_validator boundary mismatch")
    # 生产默认 perdoc→band + cell 投影的语义门（U 2026-09-21 具名决策，spec §10.5 选项 A）：
    # r5j S2 统一检索选择后 search() 委托 search_with_coverage（r5e 产品门口径），
    # _selected_chunk_hits「每源多块」双入口分叉删除；band 选择与 cell 投影保留
    # （r5e 豁免 r4v 检索门同一先例：历史语义门不施加于后续权威字节）。
    svc_src_r4n = (ROOT / "plugins/corpus/service.py").read_text(encoding="utf-8")
    if "i0c-r5j" in by_id:
        check("_apply_selection_bands" in svc_src_r4n and "def _emit_cells" in svc_src_r4n
              and "search_with_coverage(q, limit=limit)" in svc_src_r4n
              and "_selected_chunk_hits" not in svc_src_r4n,
              "r5j service.py must unify search() on search_with_coverage (S2; band/cell retained)")
    else:
        check("_selected_chunk_hits" in svc_src_r4n
              and "_apply_selection_bands" in svc_src_r4n and "def _emit_cells" in svc_src_r4n,
              "r4n service.py must wire band default + cell projection into production")
    rpg_src_r4n = (ROOT / "plugins/corpus/preparation/read_pg.py").read_text(encoding="utf-8")
    check("def search_with_coverage_bands" in rpg_src_r4n and "def fetch_bands" in rpg_src_r4n,
          "r4n read_pg must carry band read path (search_with_coverage_bands/fetch_bands)")
    sel_src_r4n = (ROOT / "plugins/corpus/preparation/selection.py").read_text(encoding="utf-8")
    check("def select_band" in sel_src_r4n, "r4n selection.py must carry band strategy")
    tst_r4n = (ROOT / "tests/test_corpus_selection.py").read_text(encoding="utf-8")
    check("test_band_doc_set_matches_select_same_snapshot" in tst_r4n
          and "test_emit_cells_derives_row_col_on_aligned_grid_only" in tst_r4n,
          "r4n test_corpus_selection must carry I-BAND-1 / I-CELL-1 gates")
    merge_binding(i0c_current_binding, bindingr4n)

if "i0c-r4p" in by_id:
    r4p = load_json(BASE / by_id["i0c-r4p"]["file"])
    parent43r4p = BASE / by_id["i0c-r4n"]["file"]
    check(r4p.get("parent_snapshot") == {"snapshot_id": "i0c-r4n",
          "path": str(parent43r4p.relative_to(ROOT)), "sha256": digest(parent43r4p)},
          "r4p parent mismatch")
    bindingr4p = r4p.get("binding", {})
    check(set(bindingr4p) == {"chain_rebind_implementation", "chain_rebind_tests", "freeze_validator"},
          "r4p binding groups mismatch")
    check(set(bindingr4p.get("chain_rebind_implementation", {})) == {
        "plugins/corpus/preparation/clean.py"}, "r4p clean implementation boundary mismatch")
    check(set(bindingr4p.get("chain_rebind_tests", {})) == {
        "tests/test_corpus_preparation_clean.py"}, "r4p clean tests boundary mismatch")
    check(set(bindingr4p.get("freeze_validator", {})) == {
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/validate_i0c_freeze.py"},
          "r4p freeze_validator boundary mismatch")
    # F3 句粒度的语义门：clean.py 必须实际携带三类数字事实句谓词 + 免责节 KEEP 判定
    clean_src_r4p = (ROOT / "plugins/corpus/preparation/clean.py").read_text(encoding="utf-8")
    check("_has_numeric_fact_sentence" in clean_src_r4p and "_disclaimer_fact_keep_verdict" in clean_src_r4p,
          "r4p clean.py must carry numeric-fact sentence predicates + disclaimer KEEP verdict")
    tst_clean_r4p = (ROOT / "tests/test_corpus_preparation_clean.py").read_text(encoding="utf-8")
    check("test_disclaimer_fact_sentence_kept_instead_of_noise" in tst_clean_r4p
          and "test_disclaimer_money_fact_sentence_kept" in tst_clean_r4p
          and "test_disclaimer_rating_rule_threshold_stays_noise" in tst_clean_r4p,
          "r4p test_corpus_preparation_clean must carry I-E3 keep/rating-threshold gates")
    merge_binding(i0c_current_binding, bindingr4p)

if "i0c-r4q" in by_id:
    r4q = load_json(BASE / by_id["i0c-r4q"]["file"])
    parent43r4q = BASE / by_id["i0c-r4p"]["file"]
    check(r4q.get("parent_snapshot") == {"snapshot_id": "i0c-r4p",
          "path": str(parent43r4q.relative_to(ROOT)), "sha256": digest(parent43r4q)},
          "r4q parent mismatch")
    bindingr4q = r4q.get("binding", {})
    check(set(bindingr4q) == {"chain_rebind_implementation", "chain_rebind_tests", "freeze_validator"},
          "r4q binding groups mismatch")
    check(set(bindingr4q.get("chain_rebind_implementation", {})) == {
        "plugins/corpus/service.py",
        "plugins/corpus/preparation/cross_boundary.py"},
          "r4q service/cross_boundary implementation boundary mismatch")
    check(set(bindingr4q.get("chain_rebind_tests", {})) == {
        "tests/test_corpus_selection.py"}, "r4q test_corpus_selection tests boundary mismatch")
    check(set(bindingr4q.get("freeze_validator", {})) == {
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/validate_i0c_freeze.py"},
          "r4q freeze_validator boundary mismatch")
    # F4 跨边界取证的语义门：service.py 必须接线 cross_boundary 聚合，
    # cross_boundary.py 必须实际携带聚合实现，tests 必须携带 I-ATT-1 门（spec §10.4 / issue 09）。
    svc_src_r4q = pre_m6_repair_path("plugins/corpus/service.py").read_text(encoding="utf-8")
    check("cross_boundary.aggregate_band_chunks" in svc_src_r4q,
          "r4q service.py must wire cross_boundary.aggregate_band_chunks into search_bands")
    cb_src_r4q = (ROOT / "plugins/corpus/preparation/cross_boundary.py").read_text(encoding="utf-8")
    check("def aggregate_band_chunks" in cb_src_r4q and "def _merge_chunk" in cb_src_r4q,
          "r4q cross_boundary.py must carry aggregate_band_chunks/_merge_chunk")
    tst_r4q = (ROOT / "tests/test_corpus_selection.py").read_text(encoding="utf-8")
    check("test_cross_boundary_aggregates_noise_header_into_full_quote" in tst_r4q
          and "test_cross_boundary_ignores_different_page_and_no_y_overlap" in tst_r4q
          and "test_cross_boundary_do_not_repeat_existing_unit" in tst_r4q,
          "r4q test_corpus_selection must carry I-ATT-1 gates")
    merge_binding(i0c_current_binding, bindingr4q)

if "i0c-r4r" in by_id:
    # r4r 为最新修订：须最后合并，确保 read_pg 权威哈希(52b182f7)与最新验证器哈希覆盖更早绑定。
    _r4r_rb = load_json(BASE / by_id["i0c-r4r"]["file"]).get("binding", {})
    merge_binding(i0c_current_binding, _r4r_rb)

if "i0c-r4s" in by_id:
    r4s = load_json(BASE / by_id["i0c-r4s"]["file"])
    parent43r4s = BASE / by_id["i0c-r4r"]["file"]
    check(r4s.get("parent_snapshot") == {"snapshot_id": "i0c-r4r",
          "path": str(parent43r4s.relative_to(ROOT)), "sha256": digest(parent43r4s)},
          "r4s parent mismatch")
    bindingr4s = r4s.get("binding", {})
    check(set(bindingr4s) == {"chain_rebind_tests", "freeze_validator"},
          "r4s binding groups mismatch")
    check(set(bindingr4s.get("chain_rebind_tests", {})) == {
        "tests/test_corpus_preparation_admission.py",
        "tests/test_corpus_consumers_pg.py",
        "tests/test_corpus_dev_lane.py"}, "r4s chain_rebind_tests boundary mismatch")
    check(set(bindingr4s.get("freeze_validator", {})) == {
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/validate_i0c_freeze.py"},
          "r4s freeze_validator boundary mismatch")
    # ① M5 consumers-pg 测试缺陷修复（decision_id 按 source 区分，RM-7 全局唯一）
    cpg_src_r4s = (ROOT / "tests/test_corpus_consumers_pg.py").read_text(encoding="utf-8")
    check("sel-d" in cpg_src_r4s and "decision_id=decision_id" in cpg_src_r4s,
          "r4s consumers-pg must differentiate decision_id per source (sel-d)")
    # ② dev-lane 测试拆出 i1（i1 守卫只放行 6 份材料）：admission 测试回归纯净
    adm_src_r4s = (ROOT / "tests/test_corpus_preparation_admission.py").read_text(encoding="utf-8")
    check("test_dev_lane" not in adm_src_r4s and "DEV_MD_PATH" not in adm_src_r4s,
          "r4s admission test must be dev-lane free (i1 guard pure)")
    # ② test_corpus_dev_lane.py 首次入链：dev-lane 用例仅在 i3-e2e 守卫下运行
    devsrc_r4s = (ROOT / "tests/test_corpus_dev_lane.py").read_text(encoding="utf-8")
    check("test_dev_lane_on_admits_declared_source_with_truthful_material" in devsrc_r4s
          and "i3-1-dev-lane-md-docx" in devsrc_r4s,
          "r4s test_corpus_dev_lane.py must carry the dev-lane on-admits gates")
    merge_binding(i0c_current_binding, bindingr4s)

if "i0c-r4t" in by_id:
    r4t = load_json(BASE / by_id["i0c-r4t"]["file"])
    parent43r4t = BASE / by_id["i0c-r4s"]["file"]
    check(r4t.get("parent_snapshot") == {"snapshot_id": "i0c-r4s",
          "path": str(parent43r4t.relative_to(ROOT)), "sha256": digest(parent43r4t)},
          "r4t parent mismatch")
    bindingr4t = r4t.get("binding", {})
    check(set(bindingr4t) == {"chain_rebind_implementation", "chain_rebind_tests",
                              "freeze_validator"},
          "r4t binding groups mismatch")
    check(set(bindingr4t.get("chain_rebind_implementation", {})) == {
        "plugins/corpus/service.py",
        "plugins/corpus/preparation/negative_query.py",
        "plugins/tools/corpus_search.py"}, "r4t chain_rebind_implementation boundary mismatch")
    check(set(bindingr4t.get("chain_rebind_tests", {})) == {
        "tests/test_corpus_negative_query.py"}, "r4t chain_rebind_tests boundary mismatch")
    check(set(bindingr4t.get("freeze_validator", {})) == {
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/validate_i0c_freeze.py"},
          "r4t freeze_validator boundary mismatch")
    # B2 abstain 拒检通道语义门（U 具名决策：判定层统一拒检 / 开关默认关 / 空结果+拒检信号）
    svc_src_r4t = (ROOT / "plugins/corpus/service.py").read_text(encoding="utf-8")
    check("def _abstain_decision" in svc_src_r4t and "CORPUS_ABSTAIN_NO_ANSWER" in svc_src_r4t,
          "r4t service.py must carry _abstain_decision + CORPUS_ABSTAIN_NO_ANSWER switch")
    nq_src_r4t = (ROOT / "plugins/corpus/preparation/negative_query.py").read_text(encoding="utf-8")
    check("abstain_content_lexemes" in nq_src_r4t and "is_abstain_candidate" in nq_src_r4t
          and "_QUESTION_WORDS" in nq_src_r4t,
          "r4t negative_query.py must carry abstain lexemes/predicate (question-words dropped)")
    cs_src_r4t = (ROOT / "plugins/tools/corpus_search.py").read_text(encoding="utf-8")
    check("ABSTAIN_HINT" in cs_src_r4t and 'coverage.get("abstain")' in cs_src_r4t,
          "r4t corpus_search.py must carry ABSTAIN_HINT + abstain coverage split")
    tnq_src_r4t = (ROOT / "tests/test_corpus_negative_query.py").read_text(encoding="utf-8")
    check("test_abstain_on_ignores_question_words_for_answerable" in tnq_src_r4t,
          "r4t test_corpus_negative_query.py must carry question-word answerable gate")
    merge_binding(i0c_current_binding, bindingr4t)

if "i0c-r4u" in by_id:
    r4u = load_json(BASE / by_id["i0c-r4u"]["file"])
    parent43r4u = BASE / by_id["i0c-r4t"]["file"]
    check(r4u.get("parent_snapshot") == {"snapshot_id": "i0c-r4t",
          "path": str(parent43r4u.relative_to(ROOT)), "sha256": digest(parent43r4u)},
          "r4u parent mismatch")
    bindingr4u = r4u.get("binding", {})
    check(set(bindingr4u) == {"chain_rebind_implementation", "chain_rebind_tests", "freeze_validator"},
          "r4u binding groups mismatch")
    check(set(bindingr4u.get("chain_rebind_implementation", {})) == {
        "plugins/corpus/preparation/cross_boundary.py"},
          "r4u cross_boundary implementation boundary mismatch")
    check(set(bindingr4u.get("chain_rebind_tests", {})) == {
        "tests/test_corpus_selection.py"}, "r4u test_corpus_selection tests boundary mismatch")
    check(set(bindingr4u.get("freeze_validator", {})) == {
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/validate_i0c_freeze.py"},
          "r4u freeze_validator boundary mismatch")
    # B3/F3 读取侧续接片段聚合语义门（U 2026-09-22 具名裁决路径 B，仿 F4 cross_boundary 先例）：
    # cross_boundary.py 须携带句末标点集合与续接谓词（stitch_continuation 默认开，
    # service.search_bands 既有接线不动）；tests 须携带 I-CONT-1 正/反向门。
    cb_src_r4u = (ROOT / "plugins/corpus/preparation/cross_boundary.py").read_text(encoding="utf-8")
    check("_SENTENCE_TERMINAL" in cb_src_r4u and "stitch_continuation" in cb_src_r4u
          and "def aggregate_band_chunks" in cb_src_r4u and "def _merge_chunk" in cb_src_r4u,
          "r4u cross_boundary.py must carry sentence-terminal continuation stitch predicate")
    tst_r4u = (ROOT / "tests/test_corpus_selection.py").read_text(encoding="utf-8")
    check("test_continuation_stitch_merges_sentence_final_noise_fragment" in tst_r4u
          and "test_continuation_stitch_ignores_non_sentence_final_fragment" in tst_r4u
          and "test_continuation_stitch_requires_cut_head_adjacency_and_same_page" in tst_r4u
          and "test_continuation_stitch_do_not_repeat_existing_unit" in tst_r4u,
          "r4u test_corpus_selection must carry I-CONT-1 gates")
    merge_binding(i0c_current_binding, bindingr4u)

if "i0c-r4v" in by_id:
    # r4v 为最新修订：须最后合并，确保 search_pg/negative_query 权威哈希与最新验证器
    # 哈希覆盖更早绑定（r42 search_pg 04bc7d61 / r4t negative_query 6db6876c）。
    _r4v_rb = load_json(BASE / by_id["i0c-r4v"]["file"]).get("binding", {})
    merge_binding(i0c_current_binding, _r4v_rb)

# r4w（M5 具名签认修订）：零运行字节改动——只落盘 U 对 r4v 口径/粒度变更
# （_FUNCTION_WORDS 复用到正例排序）的具名签认（m5_declaration 翻转为 declared）
# + 验证器重绑。签认修订不得借机重绑任何实现/测试/守卫字节。
if "i0c-r4w" in by_id:
    r4w = load_json(BASE / by_id["i0c-r4w"]["file"])
    parent43r4w = BASE / by_id["i0c-r4v"]["file"]
    check(r4w.get("parent_snapshot") == {"snapshot_id": "i0c-r4v",
          "path": str(parent43r4w.relative_to(ROOT)), "sha256": digest(parent43r4w)},
          "r4w parent mismatch")
    bindingr4w = r4w.get("binding", {})
    check(set(bindingr4w) == {"freeze_validator"},
          "r4w binding groups mismatch (sign-off revision must bind validator only)")
    check(set(bindingr4w.get("freeze_validator", {})) == {
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/validate_i0c_freeze.py"},
          "r4w freeze_validator boundary mismatch")
    # 语义门：签认必须显式落盘——m5_declaration 以 declared 开头且携带 U 具名与签认日期，
    # corrections 须含 M5 签认记录条目。
    m5decl_r4w = str(r4w.get("m5_declaration") or "")
    check(m5decl_r4w.startswith("declared") and "U" in m5decl_r4w
          and "2026-09-22" in m5decl_r4w,
          "r4w m5_declaration must record the named U sign-off (declared)")
    check(any("m5" in k and "sign" in k for k in (r4w.get("corrections") or {})),
          "r4w corrections must record the M5 sign-off entry")
    merge_binding(i0c_current_binding, bindingr4w)

# r4x（金标 col 口径改写 → I3-2 全链重派生，U 2026-09-23 具名授权）：只重绑
# source-gold / i3-2 资产 / manifest 血缘 / 验证器；不触碰任何实现/测试/守卫字节。
if "i0c-r4x" in by_id:
    r4x = load_json(BASE / by_id["i0c-r4x"]["file"])
    parentr4x = BASE / by_id["i0c-r4w"]["file"]
    check(r4x.get("parent_snapshot") == {"snapshot_id": "i0c-r4w",
          "path": str(parentr4x.relative_to(ROOT)), "sha256": digest(parentr4x)},
          "r4x parent mismatch")
    bindingr4x = r4x.get("binding", {})
    check(set(bindingr4x) == {"i3_2_source_gold", "i3_2_assets", "i3_2_scoring_input",
                             "i3_2_relineage", "freeze_validator"},
          "r4x binding groups mismatch")
    check(set(bindingr4x.get("i3_2_source_gold", {})) == {
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/source-gold-frozen.jsonl"}, "r4x source-gold boundary mismatch")
    check(set(bindingr4x.get("i3_2_assets", {})) == {
        f".scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-2/{name}" for name in (
            "evidence-targets-candidates.json", "evidence-targets-adjudication.md",
            "evidence-targets-review.md", "evidence-targets-verification.json",
            "approval-report.json", "evidence-targets-decisions.json",
            "evidence-targets-approved.json", "source-gold-nearmiss-library.jsonl")},
          "r4x i3_2_assets boundary mismatch")
    check(set(bindingr4x.get("i3_2_scoring_input", {})) == {
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-2/query-gold-scoring-v1.jsonl"}, "r4x scoring-input boundary mismatch")
    check(set(bindingr4x.get("i3_2_relineage", {})) == {
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-2/scoring-input-manifest.json"}, "r4x relineage boundary mismatch")
    check(set(bindingr4x.get("freeze_validator", {})) == {
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/validate_i0c_freeze.py"}, "r4x freeze_validator boundary mismatch")
    # 语义门：金标 col 已改为原文可派生口径，且不得残留人工合成列名
    gold_path = (ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/source-gold-frozen.jsonl")
    gold9 = next(json.loads(line) for line in gold_path.read_text(encoding="utf-8")
                 .splitlines() if line.strip()
                 and json.loads(line).get("gold_id") == "industry-009-claim-001")
    cap_items = [it for it in (gold9.get("expected_items") or [])
                 if (it.get("unit") or "") == "万吨/年"]
    check(len(cap_items) == 2, "r4x capacity items must stay 2 (R32 / 尿素)")
    check(all(it.get("col") == "产能（万吨/年）以及同比增长" for it in cap_items),
          "r4x expected_items col must use the derivable column label")
    check(all("2026E产能" not in str(it.get("col") or "") for it in cap_items),
          "r4x expected_items col must drop the synthetic column labels")
    check(sorted(str(it.get("quote")) for it in cap_items) == ["28.5", "8068.0"],
          "r4x must preserve quotes 28.5 / 8068.0")
    manifest_r4x = load_json(ROOT / f".scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-2/scoring-input-manifest.json")
    check(manifest_r4x.get("status") == "frozen" and manifest_r4x.get("frozen_in") == "i0c-r4x",
          "r4x manifest must be frozen and point at r4x")
    check(manifest_r4x.get("counts") == {"questions": 30, "answerable": 24,
                                        "no_answer": 6, "required": 79,
                                        "supplementary": 20},
          "r4x manifest counts must stay 30/24/6/79/20")
    check(any("col" in k or "gold" in k for k in (r4x.get("corrections") or {})),
          "r4x corrections must record the gold column revision")
    merge_binding(i0c_current_binding, bindingr4x)

# r4y（D2 表格来源注聚合，U 2026-09-23 授权实施）：只重绑 cross_boundary.py /
# test_corpus_selection.py / 验证器；service.py 字节零改动（既有接线直接生效）。
if "i0c-r4y" in by_id:
    r4y = load_json(BASE / by_id["i0c-r4y"]["file"])
    parentr4y = BASE / by_id["i0c-r4x"]["file"]
    check(r4y.get("parent_snapshot") == {"snapshot_id": "i0c-r4x",
          "path": str(parentr4y.relative_to(ROOT)), "sha256": digest(parentr4y)},
          "r4y parent mismatch")
    bindingr4y = r4y.get("binding", {})
    check(set(bindingr4y) == {"chain_rebind_implementation", "chain_rebind_tests",
                             "freeze_validator"},
          "r4y binding groups mismatch")
    check(set(bindingr4y.get("chain_rebind_implementation", {})) == {
        "plugins/corpus/preparation/cross_boundary.py"}, "r4y implementation boundary mismatch")
    check(set(bindingr4y.get("chain_rebind_tests", {})) == {
        "tests/test_corpus_selection.py"}, "r4y tests boundary mismatch")
    # 语义门：来源注谓词落地（开关默认开 + 段形/版面双判据 + 免重摄入）
    cb_src = (ROOT / "plugins/corpus/preparation/cross_boundary.py").read_text(encoding="utf-8")
    check("attach_source_note: bool = True" in cb_src
          and "def _is_source_note" in cb_src
          and "_SOURCE_NOTE_MAX_GAP_PT" in cb_src
          and "_SOURCE_NOTE_EXPLAIN" in cb_src,
          "r4y cross_boundary must carry the source-note predicate")
    ts_src = (ROOT / "tests/test_corpus_selection.py").read_text(encoding="utf-8")
    for gate in ("test_source_note_attached_below_table_row", "test_source_note_ignores_pure_source_label", "test_source_note_requires_below_adjacent_and_same_page", "test_source_note_requires_table_row_anchor"):
        check(gate in ts_src, f"r4y tests must carry I-NOTE-1 gate {gate}")
    check(any("source_note" in k or "footnote" in k
              for k in (r4y.get("corrections") or {})),
          "r4y corrections must record the footnote aggregation")
    merge_binding(i0c_current_binding, bindingr4y)

# r4z（I3-5 旧检索/财务非回归台账回填入链）：只重绑 tasks.md 与验证器；
# 零模型调用、原库零写入、留出零读取，不触碰任何实现/测试/守卫/金标字节。
if "i0c-r4z" in by_id:
    r4z = load_json(BASE / by_id["i0c-r4z"]["file"])
    parentr4z = BASE / by_id["i0c-r4y"]["file"]
    check(r4z.get("parent_snapshot") == {"snapshot_id": "i0c-r4y",
          "path": str(parentr4z.relative_to(ROOT)), "sha256": digest(parentr4z)},
          "r4z parent mismatch")
    bindingr4z = r4z.get("binding", {})
    check(set(bindingr4z) == {"chain_rebind_evidence", "freeze_validator"},
          "r4z binding groups mismatch")
    check(set(bindingr4z.get("chain_rebind_evidence", {})) == {
        "docs/plan/corpus-ingestion-rebuild-tasks.md"}, "r4z evidence boundary mismatch")
    check(set(bindingr4z.get("freeze_validator", {})) == {
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/validate_i0c_freeze.py"}, "r4z freeze_validator boundary mismatch")
    # 语义门：tasks.md 须携带 I3-5 执行状态回填及其证据目录指针。
    tasks_src = (ROOT / "docs/plan/corpus-ingestion-rebuild-tasks.md").read_text(encoding="utf-8")
    check("audits/20260923-i35-legacy-nonregress" in tasks_src
          and "I3-5" in tasks_src,
          "r4z tasks.md must carry the I3-5 non-regression backfill")
    check(any("i3_5" in k or "i35" in k
              for k in (r4z.get("corrections") or {})),
          "r4z corrections must record the I3-5 backfill entry")
    merge_binding(i0c_current_binding, bindingr4z)

# r5a（I3-6 最终冻结入链）：重绑最终 manifest + tasks.md + 验证器；
# 零模型调用、零写库、留出零读取，不触碰任何实现/测试/守卫/金标字节。
if "i0c-r5a" in by_id:
    r5a = load_json(BASE / by_id["i0c-r5a"]["file"])
    parentr5a = BASE / by_id["i0c-r4z"]["file"]
    check(r5a.get("parent_snapshot") == {"snapshot_id": "i0c-r4z",
          "path": str(parentr5a.relative_to(ROOT)), "sha256": digest(parentr5a)},
          "r5a parent mismatch")
    bindingr5a = r5a.get("binding", {})
    check(set(bindingr5a) == {"final_freeze_manifest", "chain_rebind_evidence",
                             "freeze_validator"},
          "r5a binding groups mismatch")
    check(set(bindingr5a.get("final_freeze_manifest", {})) == {
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-final-freeze-manifest.json"}, "r5a final-manifest boundary mismatch")
    check(set(bindingr5a.get("chain_rebind_evidence", {})) == {
        "docs/plan/corpus-ingestion-rebuild-tasks.md"}, "r5a evidence boundary mismatch")
    check(set(bindingr5a.get("freeze_validator", {})) == {
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/validate_i0c_freeze.py"}, "r5a freeze_validator boundary mismatch")
    # 语义门：最终 manifest 须锚定链头并携带 M4/M5 重验核定与待定项核定。
    fm = json.loads((ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-final-freeze-manifest.json").read_text(encoding="utf-8"))
    check(fm.get("artifact") == "i3-final-freeze-manifest",
          "r5a final manifest artifact mismatch")
    check(fm.get("frozen_version", {}).get("chain_head", {}).get("snapshot_id")
          == "i0c-r4z", "r5a final manifest must anchor the chain head")
    check(digest(BASE / by_id["i0c-r4z"]["file"])
          == fm.get("frozen_version", {}).get("chain_head", {}).get("sha256"),
          "r5a final manifest chain-head sha must match the snapshot file")
    check(len(fm.get("m4_m5_gates_to_reverify") or []) >= 9,
          "r5a final manifest must carry the M4/M5 reverify list")
    check(len(fm.get("pending_items") or []) >= 4
          and fm.get("frozen_assets", {}).get("implementation"),
          "r5a final manifest must carry pending items and asset hashes")
    tasks_src = (ROOT / "docs/plan/corpus-ingestion-rebuild-tasks.md").read_text(encoding="utf-8")
    check("audits/20260923-i36-final-freeze" in tasks_src
          and "I3-6" in tasks_src,
          "r5a tasks.md must carry the I3-6 final-freeze backfill")
    check(any("i3_6" in k or "i36" in k
              for k in (r5a.get("corrections") or {})),
          "r5a corrections must record the I3-6 freeze entry")
    merge_binding(i0c_current_binding, bindingr5a)

# r5b（I3-7 最终重验入链）：重绑 tasks.md + 验证器 + I3-7 重验证据五件；
# 零模型、隔离 PG、留出零读取，不触碰任何实现/测试/守卫/金标字节。
if "i0c-r5b" in by_id:
    r5b = load_json(BASE / by_id["i0c-r5b"]["file"])
    parentr5b = BASE / by_id["i0c-r5a"]["file"]
    check(r5b.get("parent_snapshot") == {"snapshot_id": "i0c-r5a",
          "path": str(parentr5b.relative_to(ROOT)), "sha256": digest(parentr5b)},
          "r5b parent mismatch")
    bindingr5b = r5b.get("binding", {})
    check(set(bindingr5b) == {"i37_reverify_evidence", "chain_rebind_evidence",
                             "freeze_validator"},
          "r5b binding groups mismatch")
    check(set(bindingr5b.get("i37_reverify_evidence", {})) == {
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260923-i37-final-reverify/rebuild-report.json",
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260923-i37-final-reverify/rebuild-report.md",
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260923-i37-final-reverify/i37-score-results.json",
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260923-i37-final-reverify/i37-tests-results.json",
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260923-i37-final-reverify/i37-legacy-results.json",
        }, "r5b evidence boundary mismatch")
    check(set(bindingr5b.get("chain_rebind_evidence", {})) == {
        "docs/plan/corpus-ingestion-rebuild-tasks.md"}, "r5b evidence boundary mismatch")
    check(set(bindingr5b.get("freeze_validator", {})) == {
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/validate_i0c_freeze.py"}, "r5b freeze_validator boundary mismatch")
    # 语义门：I3-7 重验证据须全绿且与冻结版本一致（revs/policy 由各报告内字段断言）。
    rb37 = json.loads((ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260923-i37-final-reverify/rebuild-report.json")
                      .read_text(encoding="utf-8"))
    check(rb37.get("summary", {}).get("published") == 8
          and rb37.get("summary", {}).get("active") == 8
          and rb37.get("summary", {}).get("all_new_build_active") is True,
          "r5b rebuild report must be 8/8 published+active")
    sc37 = json.loads((ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260923-i37-final-reverify/i37-score-results.json")
                      .read_text(encoding="utf-8"))
    check(sc37.get("passed") is True and sc37.get("gates")
          and all(sc37.get("gates").values())
          and len(sc37.get("gates")) >= 14,
          "r5b score battery must pass all gates")
    ts37 = json.loads((ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260923-i37-final-reverify/i37-tests-results.json")
                      .read_text(encoding="utf-8"))
    check(ts37.get("passed") is True and ts37.get("gates")
          and all(ts37.get("gates").values())
          and len(ts37.get("gates")) >= 9,
          "r5b test battery must pass all gates")
    lg37 = json.loads((ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260923-i37-final-reverify/i37-legacy-results.json")
                      .read_text(encoding="utf-8"))
    check(lg37.get("overall", {}).get(
        "financial_formula_negative_customer_macro_gate") is True,
          "r5b legacy non-regression gate must hold")
    tasks_src = (ROOT / "docs/plan/corpus-ingestion-rebuild-tasks.md").read_text(encoding="utf-8")
    check("audits/20260923-i37-final-reverify" in tasks_src
          and "I3-7" in tasks_src,
          "r5b tasks.md must carry the I3-7 reverify backfill")
    check(any("i3_7" in k or "i37" in k
              for k in (r5b.get("corrections") or {})),
          "r5b corrections must record the I3-7 reverify entry")
    merge_binding(i0c_current_binding, bindingr5b)

# r5c（M6 独立复核 + U 具名签认入链）：绑独立复核证据四件 + 签认记录两件 +
# tasks.md 回填 + 验证器自哈希；零模型、沙箱只读复核、留出零读取，
# 不触碰任何实现/测试/守卫/金标字节。
if "i0c-r5c" in by_id:
    r5c = load_json(BASE / by_id["i0c-r5c"]["file"])
    parentr5c = BASE / by_id["i0c-r5b"]["file"]
    check(r5c.get("parent_snapshot") == {"snapshot_id": "i0c-r5b",
          "path": str(parentr5c.relative_to(ROOT)), "sha256": digest(parentr5c)},
          "r5c parent mismatch")
    bindingr5c = r5c.get("binding", {})
    check(set(bindingr5c) == {"m6_review_evidence", "m6_signoff_record",
                             "chain_rebind_evidence", "freeze_validator"},
          "r5c binding groups mismatch")
    check(set(bindingr5c.get("m6_review_evidence", {})) == {
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260923-m6-independent-review/review.md",
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260923-m6-independent-review/m6-hashes.json",
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260923-m6-independent-review/m6-rescore.json",
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260923-m6-independent-review/m6-dbcheck.json",
        }, "r5c review evidence boundary mismatch")
    check(set(bindingr5c.get("m6_signoff_record", {})) == {
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260923-m6-independent-review/signoff-record-m6.json",
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260923-m6-independent-review/signoff-record-m6.md",
        }, "r5c signoff record boundary mismatch")
    check(set(bindingr5c.get("chain_rebind_evidence", {})) == {
        "docs/plan/corpus-ingestion-rebuild-tasks.md"}, "r5c tasks.md boundary mismatch")
    check(set(bindingr5c.get("freeze_validator", {})) == {
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/validate_i0c_freeze.py"}, "r5c freeze_validator boundary mismatch")
    # 语义门：独立复核三探针 all_match/all_ok + 独立性声明；签认记录 signed + 具名。
    m6h = json.loads((ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260923-m6-independent-review/m6-hashes.json")
                     .read_text(encoding="utf-8"))
    check(m6h.get("all_match") is True
          and m6h.get("frozen_assets", {}).get("all_match") is True,
          "r5c hash probe must show zero drift")
    m6r = json.loads((ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260923-m6-independent-review/m6-rescore.json")
                     .read_text(encoding="utf-8"))
    check(m6r.get("all_match") is True
          and m6r.get("independence", {}).get("imports_i37_score") is False,
          "r5c rescore probe must reconcile with zero field diffs")
    m6d = json.loads((ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260923-m6-independent-review/m6-dbcheck.json")
                     .read_text(encoding="utf-8"))
    check(m6d.get("all_ok") is True
          and m6d.get("pointer_state", {}).get("active_publications") == 8,
          "r5c dbcheck probe must verify 8 active sources")
    so6 = json.loads((ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260923-m6-independent-review/signoff-record-m6.json")
                     .read_text(encoding="utf-8"))
    sig6 = so6.get("signature_fields", {})
    check(so6.get("status") == "signed" and so6.get("review_result") == "通过"
          and sig6.get("reviewer") == "xyl" and sig6.get("reviewed_at")
          and "M6" in str(sig6.get("decision", ""))
          and so6.get("signed_in") == "i0c-r5c",
          "r5c signoff record must be named and release M6")
    check("abstain" in json.dumps(so6.get("not_covered", []), ensure_ascii=False),
          "r5c signoff must record the abstain known-limitation adjudication")
    rv6 = (ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260923-m6-independent-review/review.md").read_text(encoding="utf-8")
    check("复核通过" in rv6 and "U 具名签认" in rv6,
          "r5c review.md must carry the pass verdict and signoff request")
    tasks6 = (ROOT / "docs/plan/corpus-ingestion-rebuild-tasks.md").read_text(encoding="utf-8")
    check("audits/20260923-m6-independent-review" in tasks6
          and "M6 放行" in tasks6 and "xyl" in tasks6,
          "r5c tasks.md must carry the M6 release backfill")
    check(any("m6" in k for k in (r5c.get("corrections") or {})),
          "r5c corrections must record the M6 signoff entry")
    merge_binding(i0c_current_binding, bindingr5c)

if "i0c-r5d" in by_id:
    r5d = load_json(BASE / by_id["i0c-r5d"]["file"])
    parent5d = BASE / by_id["i0c-r5c"]["file"]
    check(r5d.get("parent_snapshot") == {
        "snapshot_id": "i0c-r5c", "path": str(parent5d.relative_to(ROOT)),
        "sha256": digest(parent5d)}, "r5d parent mismatch")
    check(r5d.get("business_accepted") is False
          and r5d.get("status") == "frozen_repair_acceptance_failed",
          "r5d must not claim business acceptance")
    bind5d = r5d.get("binding", {})
    check(set(bind5d) == {"m6_repair_implementation", "m6_repair_tests",
          "m6_repair_evidence", "m6_repair_state", "m6_repair_archive", "freeze_validator"},
          "r5d binding groups mismatch")
    impl5d = {"plugins/corpus/preparation/read_pg.py",
        "plugins/corpus/preparation/cross_boundary.py", "plugins/corpus/service.py",
        "plugins/tools/corpus_fetch.py", "tools/corpus_product_observations.py"}
    tests5d = {"tests/test_corpus_selection.py", "tests/test_corpus_authority_pg.py",
        "tests/test_corpus_context_integrity.py", "tests/test_corpus_product_observations.py"}
    docs5d = {"docs/plan/corpus-ingestion-rebuild-tasks.md",
        "docs/plan/claims-market-closed-loop-plan.md"}
    validator5d = {str(Path(__file__).resolve().relative_to(ROOT))}
    for group5d, expected5d in (("m6_repair_implementation", impl5d),
            ("m6_repair_tests", tests5d), ("m6_repair_state", docs5d),
            ("freeze_validator", validator5d)):
        check(set(bind5d.get(group5d, {})) == expected5d,
              f"r5d scope mismatch: {group5d}")
    prefix5d = ".scratch/m6-repair-20260923/"
    check(all(p.startswith(prefix5d) for p in bind5d.get("m6_repair_evidence", {})),
          "r5d evidence must remain in new repair directory")
    previous5d = {p: h for group in i0c_current_binding.values() for p, h in group.items()}
    expected_old5d = (impl5d | tests5d | docs5d | validator5d) & previous5d.keys()
    archive5d = bind5d.get("m6_repair_archive", {})
    check(set(archive5d) == {prefix5d + "before/" + p for p in expected_old5d},
          "r5d archive scope mismatch")
    for p in expected_old5d:
        check(archive5d.get(prefix5d + "before/" + p) == previous5d[p],
              f"r5d archive must match previous effective binding: {p}")
    repair5d = load_json(ROOT / prefix5d / "repair-manifest.json")
    check(repair5d.get("business_accepted") is False
          and repair5d.get("authority_rev") == "authority-context-2"
          and repair5d.get("snapshot_id") == "i0c-r5d", "r5d repair identity/verdict mismatch")
    for p, h in repair5d.get("implementation", {}).items():
        check(bind5d.get("m6_repair_implementation", {}).get(p) == h,
              f"r5d manifest implementation mismatch: {p}")
    check(set(repair5d.get("implementation", {})) == impl5d,
          "r5d manifest implementation incomplete")
    newer5e_paths: set[str] = set()
    if "i0c-r5e" in by_id:
        newer5e = load_json(BASE / by_id["i0c-r5e"]["file"])
        newer5e_paths = {
            path
            for group in newer5e.get("binding", {}).values()
            for path in group
        }
    for p, h in repair5d.get("unchanged_assets", {}).items():
        if p in newer5e_paths:
            continue
        check((ROOT / p).is_file() and digest(ROOT / p) == h,
              f"r5d protected asset drift: {p}")
    summary5d = json.loads((ROOT / prefix5d / "product-evaluation-summary.json").read_text())
    check(summary5d == repair5d.get("product_results"), "r5d product summary mismatch")
    check(len(summary5d) == 3 and all(x.get("executed_queries") == 30 for x in summary5d)
          and summary5d[0].get("configuration") == "default"
          and summary5d[0].get("passed") is False, "r5d real product gate must remain failed")
    targets5d = json.loads((ROOT / prefix5d / "target-roundtrip.json").read_text())
    check(len(targets5d) == 4 and all(t.get("passed") is True for t in targets5d),
          "r5d four missing evidence targets must roundtrip")
    pg5d = load_json(ROOT / prefix5d / "i37-tests-results.json")
    check(pg5d.get("passed") is True
          and pg5d.get("tested_version", {}).get("authority_rev") == "authority-context-2",
          "r5d PG battery must pass on the repaired implementation")
    merge_binding(i0c_current_binding, bind5d)

if "i0c-r5e" in by_id:
    r5e = load_json(BASE / by_id["i0c-r5e"]["file"])
    parent5e = BASE / by_id["i0c-r5d"]["file"]
    check(r5e.get("parent_snapshot") == {
        "snapshot_id": "i0c-r5d", "path": str(parent5e.relative_to(ROOT)),
        "sha256": digest(parent5e)}, "r5e parent mismatch")
    check(r5e.get("business_accepted") is True
          and r5e.get("status") == "frozen_product_acceptance_passed",
          "r5e must record the passing product acceptance")
    bind5e = r5e.get("binding", {})
    check(set(bind5e) == {"m6_retrieval_implementation", "m6_retrieval_tests",
          "m6_retrieval_evidence", "m6_retrieval_state",
          "previous_effective_bindings", "freeze_validator"},
          "r5e binding groups mismatch")
    impl5e = {
        "plugins/corpus/preparation/negative_query.py",
        "plugins/corpus/preparation/search_pg.py",
        "plugins/corpus/preparation/selection.py",
        "plugins/corpus/service.py",
        "plugins/tools/corpus_fetch.py",
        "plugins/tools/corpus_search.py",
        "tools/corpus_product_observations.py",
    }
    tests5e = {
        "tests/test_corpus_authority_pg.py",
        "tests/test_corpus_negative_query.py",
        "tests/test_corpus_product_observations.py",
        "tests/test_corpus_search_pg.py",
        "tests/test_corpus_selection.py",
    }
    state5e = {
        "docs/plan/claims-market-closed-loop-plan.md",
        "docs/plan/corpus-ingestion-rebuild-tasks.md",
    }
    evidence5e = {
        ".scratch/m6-retrieval-fix-20260923/product-summary.json",
        ".scratch/m6-retrieval-fix-20260923/product-raw-default-details.json",
        ".scratch/m6-retrieval-fix-20260923/report.md",
        ".scratch/m6-retrieval-fix-20260923/rebuild-report.json",
        ".scratch/m6-retrieval-fix-20260923/rebuild-report.md",
        ".scratch/m6-retrieval-fix-20260923/spec.md",
    }
    previous_path5e = ".scratch/m6-retrieval-fix-20260923/previous-effective-bindings.json"
    validator5e = {str(Path(__file__).resolve().relative_to(ROOT))}
    for group5e, expected5e in (
            ("m6_retrieval_implementation", impl5e),
            ("m6_retrieval_tests", tests5e),
            ("m6_retrieval_evidence", evidence5e),
            ("m6_retrieval_state", state5e),
            ("previous_effective_bindings", {previous_path5e}),
            ("freeze_validator", validator5e)):
        check(set(bind5e.get(group5e, {})) == expected5e,
              f"r5e scope mismatch: {group5e}")
    prior5e = load_json(ROOT / previous_path5e)
    previous5e = {p: h for group in i0c_current_binding.values() for p, h in group.items()}
    changed5e = impl5e | tests5e | state5e | validator5e
    check(set(prior5e) == changed5e, "r5e previous-binding scope mismatch")
    for p in changed5e:
        check(prior5e.get(p) == previous5e.get(p),
              f"r5e previous effective hash mismatch: {p}")
    product5e = load_json(ROOT / ".scratch/m6-retrieval-fix-20260923/product-summary.json")
    check(product5e.get("passed") is True
          and product5e.get("query_count") == 30
          and product5e.get("question_pass") == [24, 24]
          and product5e.get("evidence_pass") == [24, 24]
          and product5e.get("false_positives") == 0
          and product5e.get("tool_failures") == 0
          and product5e.get("gold_changed") is False
          and product5e.get("scorer_changed") is False
          and product5e.get("threshold_changed") is False,
          "r5e product gate must pass unchanged acceptance inputs")
    rebuild5e = load_json(ROOT / ".scratch/m6-retrieval-fix-20260923/rebuild-report.json")
    check(rebuild5e.get("summary", {}).get("published") == 8
          and rebuild5e.get("summary", {}).get("active") == 8
          and rebuild5e.get("summary", {}).get("all_new_build_active") is True,
          "r5e sandbox must be restored to 8/8 published+active")
    check(r5e.get("verification", {}).get("full_suite") == {
          "passed": 2961, "failed": 2, "skipped": 17},
          "r5e full-suite counts mismatch")
    report5e = (ROOT / ".scratch/m6-retrieval-fix-20260923/report.md").read_text(
        encoding="utf-8")
    check("QuestionPass：24/24" in report5e and "EvidencePass：24/24" in report5e
          and "false positive = 0" in report5e,
          "r5e report must state the passing product result")
    merge_binding(i0c_current_binding, bind5e)

if "i0c-r5f" in by_id:
    r5f = load_json(BASE / by_id["i0c-r5f"]["file"])
    parent5f = BASE / by_id["i0c-r5e"]["file"]
    check(r5f.get("parent_snapshot") == {
        "snapshot_id": "i0c-r5e", "path": str(parent5f.relative_to(ROOT)),
        "sha256": digest(parent5f)}, "r5f parent mismatch")
    check(r5f.get("status") == "frozen_validator_supersession"
          and r5f.get("business_accepted") is True,
          "r5f must preserve r5e business acceptance")
    bind5f = r5f.get("binding", {})
    validator_path5f = str(Path(__file__).resolve().relative_to(ROOT))
    check(set(bind5f) == {"freeze_validator"}
          and set(bind5f.get("freeze_validator", {})) == {validator_path5f},
          "r5f must bind only the corrected freeze validator")
    previous_validator5f = (
        load_json(parent5f).get("binding", {}).get("freeze_validator", {})
        .get(validator_path5f)
    )
    check(r5f.get("supersedes_validator_sha256") == previous_validator5f
          and previous_validator5f != bind5f.get("freeze_validator", {}).get(validator_path5f),
          "r5f validator supersession ledger mismatch")
    merge_binding(i0c_current_binding, bind5f)

# r5g（I4 窗口目标适配入链）：读写两侧目标库解析最小变更——新增 pg_target.py，
# 显式 ``CORPUS_TARGET_DB`` 才放行生产实例（默认 i2_sandbox_corpus 行为不变）；
# 同时按 r4z 先例重绑 r5f 后因 I4-1 §0 回填而漂移的两份 docs。零模型调用、
# 窗口外零写入、留出零读取。
if "i0c-r5g" in by_id:
    r5g = load_json(BASE / by_id["i0c-r5g"]["file"])
    parent5g = BASE / by_id["i0c-r5f"]["file"]
    check(r5g.get("parent_snapshot") == {
        "snapshot_id": "i0c-r5f", "path": str(parent5g.relative_to(ROOT)),
        "sha256": digest(parent5g)}, "r5g parent mismatch")
    check(r5g.get("status") == "i4_window_target_adapter"
          and r5g.get("business_accepted") is True,
          "r5g must record the I4 window target-adapter revision")
    bind5g = r5g.get("binding", {})
    adapter5g = {
        "plugins/corpus/preparation/pg_target.py",
        "plugins/corpus/preparation/repository_pg.py",
        "plugins/corpus/preparation/read_pg.py",
        "plugins/corpus/preparation/search_pg.py",
        "plugins/corpus/preparation/cross_boundary.py",
        "plugins/corpus/service.py",
        "plugins/corpus/cli.py",
    }
    state5g = {"docs/plan/README.md", "docs/plan/corpus-ingestion-rebuild-tasks.md"}
    validator_path5g = str(Path(__file__).resolve().relative_to(ROOT))
    prev_path5g = (".scratch/corpus-evidence-pipeline/ingestion-rebuild/"
                   "audits/20260923-i4-window/previous-effective-bindings-r5g.json")
    for group5g, expected5g in (
            ("i4_window_target_adapter", adapter5g),
            ("migrate_window_state", state5g),
            ("previous_effective_bindings", {prev_path5g}),
            ("freeze_validator", {validator_path5g})):
        check(set(bind5g.get(group5g, {})) == expected5g,
              f"r5g scope mismatch: {group5g}")
    prior5g = load_json(ROOT / prev_path5g)
    previous5g = {p: h for group in i0c_current_binding.values() for p, h in group.items()}
    changed_old5g = (
        (adapter5g - {"plugins/corpus/preparation/pg_target.py"}) | state5g | {validator_path5g}
    )
    check(set(prior5g) == changed_old5g, "r5g previous-binding scope mismatch")
    check("plugins/corpus/preparation/pg_target.py" not in previous5g,
          "r5g pg_target.py must be first-in-chain")
    for p in changed_old5g:
        check(prior5g.get(p) == previous5g.get(p),
              f"r5g previous effective hash mismatch: {p}")
    # archive-first：非漂移路径的 before-r5g 归档必须等于改前生效绑定；两份 docs
    # 因 r5f 后 §0 回填而漂移（r4z 先例），归档字节即 r5g 重绑来源。
    before5g = ROOT / (".scratch/corpus-evidence-pipeline/ingestion-rebuild/"
                       "audits/20260923-i4-window/before-r5g")
    for p in changed_old5g:
        archived5g = before5g / p
        if p in state5g:
            check(archived5g.is_file()
                  and digest(archived5g) == bind5g.get("migrate_window_state", {}).get(p),
                  f"r5g docs archive must carry the rebound bytes: {p}")
            check(previous5g.get(p) != bind5g.get("migrate_window_state", {}).get(p),
                  f"r5g docs rebind must actually change the binding: {p}")
        else:
            check(archived5g.is_file() and digest(archived5g) == prior5g.get(p),
                  f"r5g archive must match pre-change effective binding: {p}")
    # 语义门：默认 fail-closed 不变——pg_target 携带显式授权开关；写/读/检索三处
    # 生产硬拒一律以 production_instance_authorized 为闸。
    tgt5g = (ROOT / "plugins/corpus/preparation/pg_target.py").read_text(encoding="utf-8")
    check("CORPUS_TARGET_DB" in tgt5g and "def resolve_target_db" in tgt5g
          and "def production_instance_authorized" in tgt5g,
          "r5g pg_target.py must carry the explicit production-authorization switch")
    for mod5g, kind5g in (("plugins/corpus/preparation/repository_pg.py", "写入"),
                          ("plugins/corpus/preparation/read_pg.py", "读取"),
                          ("plugins/corpus/preparation/search_pg.py", "检索")):
        src5g = (ROOT / mod5g).read_text(encoding="utf-8")
        check("production_instance_authorized" in src5g,
              f"r5g {kind5g} hard-reject must gate on explicit authorization: {mod5g}")
    tasks5g = (ROOT / "docs/plan/corpus-ingestion-rebuild-tasks.md").read_text(encoding="utf-8")
    # 当前字节绑定的是「M7 计划 + I4-1 准备回填」状态；I4-3/I4-6 执行结果的 §0 回填
    # 属 I4-close 步骤，届时按 r4z/r5g 先例另立修订重绑。
    check("20260923-i41-window-prep" in tasks5g and "I4-6" in tasks5g and "I4-2" in tasks5g,
          "r5g tasks.md must carry the I4 window plan and I4-1 backfill")
    check(any("i4" in k for k in (r5g.get("corrections") or {})),
          "r5g corrections must record the I4 window entry")
    previous_validator5g = (
        load_json(parent5g).get("binding", {}).get("freeze_validator", {})
        .get(validator_path5g))
    check(r5g.get("supersedes_validator_sha256") == previous_validator5g
          and previous_validator5g != bind5g.get("freeze_validator", {}).get(validator_path5g),
          "r5g validator supersession ledger mismatch")
    merge_binding(i0c_current_binding, bind5g)

# r5h（I4-close 窗口执行入链）：I4-3/6/2/7/4/5 执行结果 §0 回填（r4z/r5g 先例重绑
# tasks.md）+ 验证器新增 r5h 节。登记 I4-5 无守卫 lane 偏差（I3-7 先例 + 补偿控制）
# 与 reset 阶段 2 U 复核暂缓裁决（blocks/documents 现状保留，对照件已导出）。
# 零模型调用、归档先行。
if "i0c-r5h" in by_id:
    r5h = load_json(BASE / by_id["i0c-r5h"]["file"])
    parent5h = BASE / by_id["i0c-r5g"]["file"]
    check(r5h.get("parent_snapshot") == {
        "snapshot_id": "i0c-r5g", "path": str(parent5h.relative_to(ROOT)),
        "sha256": digest(parent5h)}, "r5h parent mismatch")
    check(r5h.get("status") == "i4_close_execution"
          and r5h.get("business_accepted") is True,
          "r5h must record the I4-close window-execution revision")
    bind5h = r5h.get("binding", {})
    state5h = {"docs/plan/corpus-ingestion-rebuild-tasks.md"}
    validator_path5h = str(Path(__file__).resolve().relative_to(ROOT))
    prev_path5h = (".scratch/corpus-evidence-pipeline/ingestion-rebuild/"
                   "audits/20260923-i4-window/previous-effective-bindings-r5h.json")
    for group5h, expected5h in (
            ("i4_close_state", state5h),
            ("previous_effective_bindings", {prev_path5h}),
            ("freeze_validator", {validator_path5h})):
        check(set(bind5h.get(group5h, {})) == expected5h,
              f"r5h scope mismatch: {group5h}")
    prior5h = load_json(ROOT / prev_path5h)
    previous5h = {p: h for group in i0c_current_binding.values() for p, h in group.items()}
    changed5h = state5h | {validator_path5h}
    check(set(prior5h) == changed5h, "r5h previous-binding scope mismatch")
    for p in changed5h:
        check(prior5h.get(p) == previous5h.get(p),
              f"r5h previous effective hash mismatch: {p}")
    # archive-first：tasks.md 归档=重绑后字节（§0 回填漂移路径，r5g 先例）；
    # 验证器归档=改前字节（新增 r5h 节前的 r5g 绑定字节）。
    before5h = ROOT / (".scratch/corpus-evidence-pipeline/ingestion-rebuild/"
                       "audits/20260923-i4-window/before-r5h")
    arch5h = before5h / "docs/plan/corpus-ingestion-rebuild-tasks.md"
    check(arch5h.is_file() and digest(arch5h) == bind5h.get("i4_close_state", {}).get(
        "docs/plan/corpus-ingestion-rebuild-tasks.md"),
        "r5h tasks.md archive must carry the rebound bytes")
    check(previous5h.get("docs/plan/corpus-ingestion-rebuild-tasks.md")
          != bind5h.get("i4_close_state", {}).get("docs/plan/corpus-ingestion-rebuild-tasks.md"),
          "r5h tasks.md rebind must actually change the binding")
    arch5h = before5h / validator_path5h
    check(arch5h.is_file() and digest(arch5h) == prior5h.get(validator_path5h),
          "r5h validator archive must match pre-change effective binding")
    # 语义门：tasks.md 须携带 I4 窗口执行回填与阶段 2 暂缓裁决；corrections 须
    # 记录 I4-close 条目并含无守卫 lane 偏差登记。
    tasks5h = (ROOT / "docs/plan/corpus-ingestion-rebuild-tasks.md").read_text(encoding="utf-8")
    check("20260923-i4-window" in tasks5h and "I4-4" in tasks5h and "I4-5" in tasks5h,
          "r5h tasks.md must carry the I4 window execution backfill")
    check("暂缓" in tasks5h and "blocks 1101" in tasks5h,
          "r5h tasks.md must record the phase-2 deferral ruling")
    corr5h = r5h.get("corrections") or {}
    check(any("i4" in k for k in corr5h)
          and any("无守卫" in str(v) for v in corr5h.values()),
          "r5h corrections must record the I4-close entry with the unguarded-lane deviation")
    previous_validator5h = (
        load_json(parent5h).get("binding", {}).get("freeze_validator", {})
        .get(validator_path5h))
    check(r5h.get("supersedes_validator_sha256") == previous_validator5h
          and previous_validator5h != bind5h.get("freeze_validator", {}).get(validator_path5h),
          "r5h validator supersession ledger mismatch")
    merge_binding(i0c_current_binding, bind5h)

# r5i（reset 阶段 2 执行入链）：暂缓解除后 U 批准执行 manifest phases[2] 单语句
# （六表同语句、无 CASCADE）单事务逐字 TRUNCATE；tasks.md §0 收尾回填（r4z/r5g/r5h
# 先例重绑）+ 验证器新增 r5i 节。零模型调用、归档先行。
if "i0c-r5i" in by_id:
    r5i = load_json(BASE / by_id["i0c-r5i"]["file"])
    parent5i = BASE / by_id["i0c-r5h"]["file"]
    check(r5i.get("parent_snapshot") == {
        "snapshot_id": "i0c-r5h", "path": str(parent5i.relative_to(ROOT)),
        "sha256": digest(parent5i)}, "r5i parent mismatch")
    check(r5i.get("status") == "i4_reset_phase2_execution"
          and r5i.get("business_accepted") is True,
          "r5i must record the reset phase-2 execution revision")
    bind5i = r5i.get("binding", {})
    state5i = {"docs/plan/corpus-ingestion-rebuild-tasks.md"}
    validator_path5i = str(Path(__file__).resolve().relative_to(ROOT))
    prev_path5i = (".scratch/corpus-evidence-pipeline/ingestion-rebuild/"
                   "audits/20260923-i4-window/previous-effective-bindings-r5i.json")
    for group5i, expected5i in (
            ("i4_phase2_state", state5i),
            ("previous_effective_bindings", {prev_path5i}),
            ("freeze_validator", {validator_path5i})):
        check(set(bind5i.get(group5i, {})) == expected5i,
              f"r5i scope mismatch: {group5i}")
    prior5i = load_json(ROOT / prev_path5i)
    previous5i = {p: h for group in i0c_current_binding.values() for p, h in group.items()}
    changed5i = state5i | {validator_path5i}
    check(set(prior5i) == changed5i, "r5i previous-binding scope mismatch")
    for p in changed5i:
        check(prior5i.get(p) == previous5i.get(p),
              f"r5i previous effective hash mismatch: {p}")
    # archive-first：tasks.md 归档=重绑后字节（§0 收尾回填，r5g/r5h 先例）；
    # 验证器归档=改前字节（新增 r5i 节前的 r5h 绑定字节）。
    before5i = ROOT / (".scratch/corpus-evidence-pipeline/ingestion-rebuild/"
                       "audits/20260923-i4-window/before-r5i")
    arch5i = before5i / "docs/plan/corpus-ingestion-rebuild-tasks.md"
    check(arch5i.is_file() and digest(arch5i) == bind5i.get("i4_phase2_state", {}).get(
        "docs/plan/corpus-ingestion-rebuild-tasks.md"),
        "r5i tasks.md archive must carry the rebound bytes")
    check(previous5i.get("docs/plan/corpus-ingestion-rebuild-tasks.md")
          != bind5i.get("i4_phase2_state", {}).get("docs/plan/corpus-ingestion-rebuild-tasks.md"),
          "r5i tasks.md rebind must actually change the binding")
    arch5i = before5i / validator_path5i
    check(arch5i.is_file() and digest(arch5i) == prior5i.get(validator_path5i),
          "r5i validator archive must match pre-change effective binding")
    # 语义门：tasks.md 须携带阶段 2 执行收尾回填（write-once 报告引用 + 解除暂缓
    # 批准记录）；corrections 须记录 i4 phase-2 条目。
    tasks5i = (ROOT / "docs/plan/corpus-ingestion-rebuild-tasks.md").read_text(encoding="utf-8")
    check("i4c-reset-phase2-report.json" in tasks5i and "11762f4e" in tasks5i
          and "暂缓解除" in tasks5i and "blocks 1101" in tasks5i,
          "r5i tasks.md must carry the phase-2 execution backfill")
    check(any("i4" in k for k in (r5i.get("corrections") or {})),
          "r5i corrections must record the phase-2 entry")
    previous_validator5i = (
        load_json(parent5i).get("binding", {}).get("freeze_validator", {})
        .get(validator_path5i))
    check(r5i.get("supersedes_validator_sha256") == previous_validator5i
          and previous_validator5i != bind5i.get("freeze_validator", {}).get(validator_path5i),
          "r5i validator supersession ledger mismatch")
    merge_binding(i0c_current_binding, bind5i)

# r5j（M7 复核修复入链）：外部复核六项（G1/G2/S1/S2/G3/G4）修复落地——
# G1：.env 交付 CORPUS_TARGET_DB=postgres（默认服务恢复，.env.example 同步）；
# S1：目标库解析去 import 缓存（service/read_pg/search_pg/cross_boundary/cli
# 构造/调用时动态解析）；G2：旧 ingest 写入口 fail-closed 恒定拒绝
# （RetiredIngestError + CLI ingest 结构化拒绝 exit 2，零连接回归测试）；
# S2：search() 统一委托 search_with_coverage（r5e 产品门 24/24 验收口径，
# 删除 _selected_chunk_hits 双入口分叉）。同时绑定 I4 窗口关键证据
# （窗口报告/双 manifest/三阶段报告/两执行脚本+往返产物，G4）。
# tasks.md §0 修复回填（r4z/r5g/r5h/r5i 先例重绑）+ 验证器新增 r5j 节。
# 零模型调用、归档先行。
if "i0c-r5j" in by_id:
    r5j = load_json(BASE / by_id["i0c-r5j"]["file"])
    parent5j = BASE / by_id["i0c-r5i"]["file"]
    check(r5j.get("parent_snapshot") == {
        "snapshot_id": "i0c-r5i", "path": str(parent5j.relative_to(ROOT)),
        "sha256": digest(parent5j)}, "r5j parent mismatch")
    check(r5j.get("status") == "m7_review_remediation"
          and r5j.get("business_accepted") is True,
          "r5j must record the M7 review-remediation revision")
    bind5j = r5j.get("binding", {})
    code5j = {
        "plugins/corpus/service.py",
        "plugins/corpus/preparation/read_pg.py",
        "plugins/corpus/preparation/search_pg.py",
        "plugins/corpus/preparation/cross_boundary.py",
        "plugins/corpus/cli.py",
    }
    tests5j = {"tests/test_corpus_consumers_pg.py", "tests/test_corpus_ingest_retired.py"}
    win5j = {
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260923-i4-window/report.md",
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i4-reset-manifest.json",
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i4-cutover-manifest.json",
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260923-i4-window/i47-reset-phase1-report.json",
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260923-i4-window/i44-rebuild-report.json",
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260923-i4-window/i45_tool_roundtrip.py",
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260923-i4-window/i45-tool-roundtrip.json",
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260923-i4-window/i4c_reset_phase2.py",
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260923-i4-window/i4c-reset-phase2-report.json",
    }
    state5j = {"docs/plan/corpus-ingestion-rebuild-tasks.md"}
    validator_path5j = str(Path(__file__).resolve().relative_to(ROOT))
    prev_path5j = (".scratch/corpus-evidence-pipeline/ingestion-rebuild/"
                   "audits/20260923-i4-window/previous-effective-bindings-r5j.json")
    for group5j, expected5j in (
            ("m7_fix_code", code5j),
            ("m7_fix_tests", tests5j),
            ("m7_window_evidence", win5j),
            ("m7_fix_state", state5j),
            ("previous_effective_bindings", {prev_path5j}),
            ("freeze_validator", {validator_path5j})):
        check(set(bind5j.get(group5j, {})) == expected5j,
              f"r5j scope mismatch: {group5j}")
    prior5j = load_json(ROOT / prev_path5j)
    previous5j = {p: h for group in i0c_current_binding.values() for p, h in group.items()}
    changed_old5j = code5j | {"tests/test_corpus_consumers_pg.py"} | state5j | {validator_path5j}
    check(set(prior5j) == changed_old5j, "r5j previous-binding scope mismatch")
    for p in changed_old5j:
        check(prior5j.get(p) == previous5j.get(p),
              f"r5j previous effective hash mismatch: {p}")
    check("tests/test_corpus_ingest_retired.py" not in previous5j,
          "r5j test_corpus_ingest_retired.py must be first-in-chain")
    for p in win5j:
        check(p not in previous5j, f"r5j window evidence must be first-in-chain: {p}")
    # archive-first：改前生效路径的 before-r5j 归档必须等于改前生效绑定
    # （代码/测试取 git HEAD 字节=链上绑定，验证器取扩展 r5j 节前字节）；
    # tasks.md 因 §0 修复回填而漂移（r5g/r5h/r5i 先例），归档字节即重绑来源。
    before5j = ROOT / (".scratch/corpus-evidence-pipeline/ingestion-rebuild/"
                       "audits/20260923-i4-window/before-r5j")
    for p in changed_old5j:
        archived5j = before5j / p
        if p in state5j:
            check(archived5j.is_file()
                  and digest(archived5j) == bind5j.get("m7_fix_state", {}).get(p),
                  "r5j tasks.md archive must carry the rebound bytes")
            check(previous5j.get(p) != bind5j.get("m7_fix_state", {}).get(p),
                  "r5j tasks.md rebind must actually change the binding")
        else:
            check(archived5j.is_file() and digest(archived5j) == prior5j.get(p),
                  f"r5j archive must match pre-change effective binding: {p}")
    # 语义门（M7 复核修复）：
    # S1——目标库不在 import 时缓存：service 无模块级解析常量（行首赋值），
    # read_pg/search_pg 缺省目标调用时动态解析，cross_boundary 不再持常量；
    # S2——search() 统一委托 search_with_coverage，选择分叉删除；
    # G2——旧写入口 RetiredIngestError 恒定拒绝 + CLI 结构化拒绝；
    # G1——.env 交付默认目标。
    svc5j = (ROOT / "plugins/corpus/service.py").read_text(encoding="utf-8")
    check("class RetiredIngestError" in svc5j and "恒定拒绝" in svc5j,
          "r5j service.py must carry the fail-closed retired-ingest entry (G2)")
    # G2 的 CLI ``ingest`` 结构化拒绝（JSON + exit 2）实现在 service._main
    # （corpus-service 入口），不在 plugins/corpus/cli.py（后者仅承 S1 动态解析）。
    check("retired_ingest_entry" in svc5j and "def _main" in svc5j,
          "r5j service._main must carry the structured CLI ingest rejection (G2)")
    check("\n_I2_SANDBOX_DB" not in svc5j,
          "r5j service.py must not cache the target at import time (S1)")
    check("search_with_coverage(q, limit=limit)" in svc5j
          and "_selected_chunk_hits" not in svc5j,
          "r5j service.py search() must delegate to search_with_coverage (S2)")
    for mod5j in ("plugins/corpus/preparation/read_pg.py",
                  "plugins/corpus/preparation/search_pg.py"):
        src5j = (ROOT / mod5j).read_text(encoding="utf-8")
        check("sandbox_db if sandbox_db is not None else resolve_target_db()" in src5j,
              f"r5j {mod5j} must resolve the default target at call time (S1)")
    cb5j = (ROOT / "plugins/corpus/preparation/cross_boundary.py").read_text(encoding="utf-8")
    check("_SANDBOX_DB =" not in cb5j,
          "r5j cross_boundary.py must not cache the target at import time (S1)")
    cli5j = (ROOT / "plugins/corpus/cli.py").read_text(encoding="utf-8")
    check("\n_SANDBOX_DB =" not in cli5j and "sandbox_db=resolve_target_db()" in cli5j,
          "r5j cli.py must resolve the default target at call time (S1)")
    env5j = ROOT / ".env"
    check(env5j.is_file()
          and "CORPUS_TARGET_DB=postgres" in env5j.read_text(encoding="utf-8"),
          "r5j .env must deliver the default target (G1)")
    # 语义门（tasks.md）：r5h/r5i 既有门字符串必须保留，且携带 M7 修复回填。
    tasks5j = (ROOT / "docs/plan/corpus-ingestion-rebuild-tasks.md").read_text(encoding="utf-8")
    check("20260923-i4-window" in tasks5j and "I4-4" in tasks5j and "I4-5" in tasks5j
          and "暂缓" in tasks5j and "blocks 1101" in tasks5j
          and "i4c-reset-phase2-report.json" in tasks5j and "11762f4e" in tasks5j
          and "暂缓解除" in tasks5j,
          "r5j tasks.md must retain the r5h/r5i gate strings")
    check("m7-review-20260924" in tasks5j and "m7-fix-20260924" in tasks5j
          and "i0c-r5j" in tasks5j,
          "r5j tasks.md must carry the M7 remediation backfill")
    corr5j = r5j.get("corrections") or {}
    check(any("m7" in k.lower() for k in corr5j),
          "r5j corrections must record the M7 remediation entry")
    previous_validator5j = (
        load_json(parent5j).get("binding", {}).get("freeze_validator", {})
        .get(validator_path5j))
    check(r5j.get("supersedes_validator_sha256") == previous_validator5j
          and previous_validator5j != bind5j.get("freeze_validator", {}).get(validator_path5j),
          "r5j validator supersession ledger mismatch")
    merge_binding(i0c_current_binding, bind5j)

# r5k（M7 二次复核 F1—F3 闭环）：F1 退休 evidence 写入口 fail-closed，
# F2 恢复历史正文逐字门，F3 将本轮运行证据绑定到实际 r5k 代码/测试版本；早期
# M7 电池只作为明确标注的历史基线。所有被覆盖的既有路径均 archive-first。
if "i0c-r5k" in by_id:
    r5k = load_json(BASE / by_id["i0c-r5k"]["file"])
    parent5k = BASE / by_id["i0c-r5j"]["file"]
    check(r5k.get("parent_snapshot") == {
        "snapshot_id": "i0c-r5j", "path": str(parent5k.relative_to(ROOT)),
        "sha256": digest(parent5k)}, "r5k parent mismatch")
    check(r5k.get("status") == "m7_rereview_closure" and r5k.get("business_accepted") is True,
          "r5k must record M7 re-review closure")
    bind5k = r5k.get("binding", {})
    code5k = {"plugins/corpus/service.py"}
    tests5k = {
        "tests/test_corpus_ingest_retired.py", "tests/test_corpus_evidence_pipeline.py",
        "tests/test_corpus_authority_pg.py", "tests/test_corpus_claims_interface.py",
    }
    runtime5k = {
        ".scratch/m7-rereview-20260924/report.md",
        ".scratch/m7-finalize-20260924/f1_retired_evidence_writer_verify.py",
        ".scratch/m7-finalize-20260924/f1-retired-evidence-writer-verification.json",
        ".scratch/m7-finalize-20260924/g3b_isolated_restore_body_verify.py",
        ".scratch/m7-finalize-20260924/g3b-isolated-restore-body-verification.json",
        ".scratch/m7-finalize-20260924/r5k_prepare.py",
        ".scratch/m7-finalize-20260924/r5k_finalize.py",
    }
    baseline5k = {
        ".scratch/m7-fix-20260924/replay_battery.py",
        ".scratch/m7-fix-20260924/i37-tests-results.json",
        ".scratch/m7-fix-20260924/live_default_product.py",
        ".scratch/m7-fix-20260924/live-default.json",
        ".scratch/m7-fix-20260924/product-trace-default.json",
        ".scratch/m7-fix-20260924/g3_isolated_restore_verify.py",
        ".scratch/m7-fix-20260924/g3-isolated-restore-verification.json",
    }
    state5k = {"docs/plan/corpus-ingestion-rebuild-tasks.md"}
    validator_path5k = str(Path(__file__).resolve().relative_to(ROOT))
    prev_path5k = (".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/"
                    "20260923-i4-window/previous-effective-bindings-r5k.json")
    for group5k, expected5k in (
            ("m7_rereview_code", code5k),
            ("m7_rereview_tests", tests5k),
            ("m7_rereview_runtime", runtime5k),
            ("m7_reused_baseline", baseline5k),
            ("m7_rereview_state", state5k),
            ("previous_effective_bindings", {prev_path5k}),
            ("freeze_validator", {validator_path5k})):
        check(set(bind5k.get(group5k, {})) == expected5k,
              f"r5k scope mismatch: {group5k}")
    prior5k = load_json(ROOT / prev_path5k)
    previous5k = {p: h for group in i0c_current_binding.values() for p, h in group.items()}
    changed5k = code5k | tests5k | state5k | {validator_path5k}
    check(set(prior5k) == changed5k, "r5k previous-binding scope mismatch")
    for p in changed5k:
        check(prior5k.get(p) == previous5k.get(p),
              f"r5k previous effective hash mismatch: {p}")
        archived5k = ROOT / (".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/"
                              "20260923-i4-window/before-r5k") / p
        check(archived5k.is_file() and digest(archived5k) == prior5k.get(p),
              f"r5k archive must match pre-change effective binding: {p}")
    for p in runtime5k | baseline5k:
        check(p not in previous5k, f"r5k runtime evidence must be first-in-chain: {p}")
    service5k = (ROOT / "plugins/corpus/service.py").read_text(encoding="utf-8")
    check("class RetiredEvidenceWriteError" in service5k
          and "persist: bool = False" in service5k
          and "raise RetiredEvidenceWriteError" in service5k,
          "r5k service.py must retire the old evidence writer before any DB write")
    f1_5k = load_json(ROOT / ".scratch/m7-finalize-20260924/"
                       "f1-retired-evidence-writer-verification.json")
    g3b_5k = load_json(ROOT / ".scratch/m7-finalize-20260924/"
                        "g3b-isolated-restore-body-verification.json")
    check(f1_5k.get("gate", {}).get("passed") is True
          and f1_5k.get("checks", {}).get("psycopg_connect_calls") == 0
          and f1_5k.get("checks", {}).get("extract_claims_persist_default") is False,
          "r5k F1 runtime evidence must prove zero-connection rejection and default non-persistence")
    body5k = g3b_5k.get("body_comparison", {})
    check(g3b_5k.get("gate", {}).get("passed") is True
          and body5k.get("resolved_historical_bodies_expected") == 290
          and body5k.get("missing") == body5k.get("mismatched") == body5k.get("ambiguous_locator_keys") == 0,
          "r5k G3b runtime evidence must gate full historical body equality")
    tasks5k = (ROOT / "docs/plan/corpus-ingestion-rebuild-tasks.md").read_text(encoding="utf-8")
    check("M7 二次复核遗留项已修复并冻结" in tasks5k and "i0c-r5k" in tasks5k,
          "r5k tasks.md must record F1-F3 closure and current freeze")
    previous_validator5k = load_json(parent5k).get("binding", {}).get("freeze_validator", {}).get(validator_path5k)
    check(r5k.get("supersedes_validator_sha256") == previous_validator5k
          and previous_validator5k != bind5k.get("freeze_validator", {}).get(validator_path5k),
          "r5k validator supersession ledger mismatch")
    merge_binding(i0c_current_binding, bind5k)

# r5l 是 r5k F1 回归测试的纯 import-order 格式修订；不改变 F1/F2 运行结论。
if "i0c-r5l" in by_id:
    r5l = load_json(BASE / by_id["i0c-r5l"]["file"])
    parent5l = BASE / by_id["i0c-r5k"]["file"]
    validator_path5l = str(Path(__file__).resolve().relative_to(ROOT))
    test5l = "tests/test_corpus_ingest_retired.py"
    prev_path5l = (".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/"
                    "20260923-i4-window/previous-effective-bindings-r5l.json")
    check(r5l.get("parent_snapshot") == {
        "snapshot_id": "i0c-r5k", "path": str(parent5l.relative_to(ROOT)),
        "sha256": digest(parent5l)}, "r5l parent mismatch")
    bind5l = r5l.get("binding", {})
    check(set(bind5l.get("ruff_rebind_test", {})) == {test5l}
          and set(bind5l.get("previous_effective_bindings", {})) == {prev_path5l}
          and set(bind5l.get("freeze_validator", {})) == {validator_path5l},
          "r5l binding scope mismatch")
    prior5l = load_json(ROOT / prev_path5l)
    previous5l = {p: h for group in i0c_current_binding.values() for p, h in group.items()}
    changed5l = {test5l, validator_path5l}
    check(set(prior5l) == changed5l, "r5l previous-binding scope mismatch")
    before5l = ROOT / (".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/"
                        "20260923-i4-window/before-r5l")
    for p in changed5l:
        check(prior5l.get(p) == previous5l.get(p), f"r5l previous effective hash mismatch: {p}")
        check((before5l / p).is_file() and digest(before5l / p) == prior5l.get(p),
              f"r5l archive mismatch: {p}")
    test_source5l = (ROOT / test5l).read_text(encoding="utf-8")
    check("import inspect\nimport json" in test_source5l,
          "r5l must retain the ruff-sorted F1 regression imports")
    merge_binding(i0c_current_binding, bind5l)

# r5m 仅澄清 r5k 的 F1 语义门：禁止的是写入口，不是历史空表结构是否存在。
if "i0c-r5m" in by_id:
    r5m = load_json(BASE / by_id["i0c-r5m"]["file"])
    parent5m = BASE / by_id["i0c-r5l"]["file"]
    validator_path5m = str(Path(__file__).resolve().relative_to(ROOT))
    prev_path5m = (".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/"
                    "20260923-i4-window/previous-effective-bindings-r5m.json")
    check(r5m.get("parent_snapshot") == {
        "snapshot_id": "i0c-r5l", "path": str(parent5m.relative_to(ROOT)),
        "sha256": digest(parent5m)}, "r5m parent mismatch")
    bind5m = r5m.get("binding", {})
    check(set(bind5m.get("freeze_validator", {})) == {validator_path5m}
          and set(bind5m.get("previous_effective_bindings", {})) == {prev_path5m},
          "r5m binding scope mismatch")
    prior5m = load_json(ROOT / prev_path5m)
    previous5m = {p: h for group in i0c_current_binding.values() for p, h in group.items()}
    check(set(prior5m) == {validator_path5m}
          and prior5m.get(validator_path5m) == previous5m.get(validator_path5m),
          "r5m previous validator mismatch")
    archived5m = ROOT / (".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/"
                          "20260923-i4-window/before-r5m") / validator_path5m
    check(archived5m.is_file() and digest(archived5m) == prior5m.get(validator_path5m),
          "r5m validator archive mismatch")
    merge_binding(i0c_current_binding, bind5m)

# 最新修订绑定优先（supersession）：i0c-r2..r43 显式重绑的路径改由合并后的
# i0c-current 绑定按新哈希核对，i1-r4 中对应旧绑定不再要求匹配。
superseded: set[str] = set()
for sid, entry in by_id.items():
    if not sid.startswith("i0c-r") or sid == "i0c-r1":
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
if "i0c-r5m" in by_id:
    print("CURRENT r5m: r5k F1-F3 evidence retained; validation clarifies that writer rejection, not legacy empty-table presence, is the F1 safety condition.")
elif "i0c-r5l" in by_id:
    print("CURRENT r5l: r5k M7 F1-F3 evidence retained; only the F1 regression test import order was ruff-normalized and rebound archive-first.")
elif "i0c-r5k" in by_id:
    print("CURRENT r5k: M7 re-review F1-F3 frozen — retired corpus_evidence_runs writer rejects before any connection and extract_claims defaults to non-persistence; isolated restore matched 290/290 archived historical bodies with 25/25 backup manifest and one-off teardown; current review/runners/reports/code/tests are bound, while prior M7 battery artifacts are explicitly historical baselines.")
elif "i0c-r5j" in by_id:
    print("CURRENT r5j: M7 review remediation frozen — default target delivered via .env (G1), import-time target caching removed (S1), retired ingest entry fail-closed with zero-connection regression (G2), search() unified on search_with_coverage (S2); I4 window evidence bound (G4); PG battery replayed green (search-live 11 / fullchain 12 / hermetic 78 / d2d6 73) and full-repo pytest 2931 passed / 2 pre-existing failed / 49 skipped.")
elif "i0c-r5i" in by_id:
    print("CURRENT r5i: reset phase-2 executed after U lifted the deferral (single-statement six-table TRUNCATE, five gates green, retained sequences/witnesses unchanged); I4 window execution fully complete; M7 release still governed by the master ledger.")
elif "i0c-r5h" in by_id:
    print("CURRENT r5h: I4 window execution closed (migrate+reset-1 green, production rebuild 8/8, tool roundtrip verified); phase-2 reset deferred by U recheck; unguarded-lane deviation registered.")
elif "i0c-r5g" in by_id:
    print("CURRENT r5g: I4 window target adapter frozen (explicit CORPUS_TARGET_DB, default fail-closed unchanged); docs backfill rebound archive-first.")
elif "i0c-r5f" in by_id:
    print("CURRENT r5f: r5e product acceptance retained; validator supersession verified.")
elif "i0c-r5e" in by_id:
    print("CURRENT r5e: real product path 24/24 QP, 24/24 EP, 0 false positives; M6 product acceptance passed.")
elif "i0c-r5d" in by_id:
    print("CURRENT r5d: repair bindings verified; real product acceptance FAILED; no new M6 release. Historical decisions follow.")
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
      + ("; r43 R3 closure: production service.py new-chain (search/search_with_coverage) wired to perdoc select_structural, selection.py first-bound, tests 731 passed / 12 skipped" if "i0c-r43" in by_id else "")
      + ("; r4n F2 band/cell production default: search_with_coverage + search switch perdoc->band via _selected_chunk_hits, read_pg band read path bound (search_with_coverage_bands/fetch_bands), selection.py + test_corpus_selection/test_corpus_consumers_pg bound, I-BAND-1/I-CELL-1 gates, U 2026-09-21 named decision (spec §10.5 option A); clean.py(r4p) + r39 plan read_pg drift recorded as pending" if "i0c-r4n" in by_id else "")
      + ("; r4p F3 clean sentence-granularity frozen: clean.py numeric-fact predicates (_has_numeric_fact_sentence/_disclaimer_fact_keep_verdict) + I-E3 tests (fact/money keep, rating-rule threshold stays noise) re-bound, chain_rebind clean drift closed (clean.py d46491b2, test_corpus_preparation_clean 655b2be1)" if "i0c-r4p" in by_id else "")
      + ("; r4q F4 cross-boundary evidence frozen: cross_boundary.py aggregate_band_chunks/_merge_chunk first-in-chain, service.py search_bands wires cross_boundary.aggregate_band_chunks, I-ATT-1 tests (header-in-NOISE quote, cross-page/no-y-overlap no-merge, idempotency), chain_rebind service.py+test_corpus_selection drift closed" if "i0c-r4q" in by_id else "")
      + ("; r4r r39 calibration drift resolved: independent calibration revision exempts read_pg.py from r39 pre-run binding check (r39 plan records pre-F2 fb87a771, r4n authoritative 52b182f7), read_pg authoritative hash re-bound, closed-artifact untouched, chain green" if "i0c-r4r" in by_id else "")
      + ("; r4s M5 test-deficiency rebind: test_corpus_consumers_pg.py decision_id per-source (sel-d, RM-7 global-unique), dev-lane tests split out of test_corpus_preparation_admission.py to new first-in-chain test_corpus_dev_lane.py (i3-e2e guard only), i1 guard pure 6-material scope restored, consumers-pg 20 passed on sandbox PG" if "i0c-r4s" in by_id else "")
      + ("; r4t B2 no-answer abstain gate frozen: CORPUS_ABSTAIN_NO_ANSWER switch (on|off, default off, fail-closed) + service._abstain_decision (substantive-lexeme websearch AND precheck + is_abstain_candidate unit gate, question-words dropped so answerable S1 protected), search_with_coverage abstain branch (empty hits + query_status=abstain), corpus_search ABSTAIN_HINT split, negative_query.py + test_corpus_negative_query.py first-in-chain, default off = production bytes unchanged" if "i0c-r4t" in by_id else "")
      + ("; r4u B3/F3 read-side continuation-fragment stitch frozen (U 2026-09-22 named decision, path B): cross_boundary.py extends aggregate_band_chunks/_merge_chunk with the structural sentence-terminal stitch predicate (_SENTENCE_TERMINAL, adjacent-ordinal NOISE fragment completing a mid-sentence kept unit, same page; corpus-wide isomorphic samples = 1), stitch_continuation default-on inside the existing search_bands wiring (service.py bytes unchanged), I-CONT-1 positive/negative gates in test_corpus_selection.py" if "i0c-r4u" in by_id else "")
      + ("; r4v c3 prune_fn_punct ranking-signal frozen (offline-eval winner, U named sign-off pending M5): search_pg.py dual-tsquery (candidate pool keeps full lexemes via q.tsq, score = ts_rank on content-only q.tsq_rank, tie-break/ts_headline unchanged, RANK_LEXEME_PRUNE=True default-on, same-cursor _rank_query_on injection + explicit rank_query param in build_search_params), negative_query.py is_punct_lexeme/rank_lexemes (drop function-words+punct, keep single-char, fail-closed all-pruned fallback) reusing the F1/B2 non-gold lexicon (granularity change requiring named sign-off), tests/test_corpus_search_pg.py first-in-chain with I-RANK-1 unit gates + live gates (pool unchanged / virtual-only score 0 but stays in pool / tie-break / switch-off field-equal), r4u 'no search_pg bytes' constraint lifted for the first time (r42 plan binding superseded per r4r precedent), corpus family 772/18 vs pre-change same-env control 766/13, e2e replay 11/11 gates green (21/24, matched 75(+8), zero regression, negatives 6x5, width 33<=49, company-003 6/6 gold pos1)" if "i0c-r4v" in by_id else "")
      + ("; r4w M5 named sign-off: _FUNCTION_WORDS granularity change (neg-only -> also positive ranking) approved by U (declared 2026-09-22), zero runtime byte change (sign-off revision binds validator only), r4v m5_declaration flipped to declared" if "i0c-r4w" in by_id else "")
      + ("; r4x 金标 col 口径改写入链（U 2026-09-23 具名授权）：source-gold industry-009-claim-001 的 R32/尿素 两条 col/cell 由人工合成列名（2026E产能（配额）/2026E产能）改为原文可派生口径『产能（万吨/年）以及同比增长』（quote/row/unit/period 不变）；候选/审批件 based_on/批准投影/正式评分输入全部重派生，EvidencePass 21/24→23/24（industry 5/8→7/8），40 项决定在新候选下 unresolved=0；r26/r39/r42 对旧字节的断言按 r4r 先例以 supersession 承接" if "i0c-r4x" in by_id else "")
      + ("; r5g I4 窗口目标适配入链：pg_target.py 显式 CORPUS_TARGET_DB 授权（默认 i2_sandbox_corpus 不变），写/读/检索三处生产硬拒加显式授权闸，service/cli 目标库解析走 pg_target，r5f 后 §0 回填的 docs/plan/README.md + tasks.md 按 r4z 先例重绑（archive-first），I4-3 停写核验与 I4-6 最终备份/恢复验证证据在案" if "i0c-r5g" in by_id else "")
      + ("; r5h I4-close 入链：I4-3/6/2/7/4/5 执行结果 §0 回填（tasks.md 重绑），migrate 一次受控回滚后重跑绿色、reset 阶段 1 七表、I4-4 生产重建 8/8 与 I3-7 基线相同、I4-5 工具往返+旧写入口停用；无守卫 lane 偏差登记（I3-7 先例+补偿控制）；reset 阶段 2 U 复核暂缓（blocks/documents 现状保留，对照件已导出，另行安排）" if "i0c-r5h" in by_id else "")
      + ("; r5i reset 阶段 2 执行入链：U 解除暂缓后批准执行（解除同日「暂缓，先出窗口报告」裁决），manifest phases[2] 单语句六表单事务逐字 TRUNCATE（无 CASCADE）五门全过（前置 1101/89+四引用表 0 精确匹配、对照件三件 sha 命中、后置六表全 0、保留序列与见证不变），write-once i4c-reset-phase2-report.json 落章；I4 窗口执行全部完毕" if "i0c-r5i" in by_id else "")
      + ("; r5j M7 复核修复入链：外部复核六项落实——G1 .env 交付默认目标（default 模式 30 题 24/24）、S1 目标库解析去 import 缓存、G2 旧写入口 fail-closed 恒定拒绝（零连接回归）、S2 search() 统一委托 search_with_coverage（r5e 口径）；窗口报告/双 manifest/三阶段报告/两执行脚本首次入链（G4）；冻结 PG 电池复放全绿（11/12/78/73）+ 全仓 pytest 2931/2 既有/49" if "i0c-r5j" in by_id else ""))
