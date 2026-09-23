"""生成冻结修订 ``i0c-r4y``（parent = i0c-r4x）：把 D2「表格来源注聚合」入链。

本轮改动（U 2026-09-23 授权实施，复验见 audits/20260923-d2-footnote-landing/d2-replay.json）：
  ``plugins/corpus/preparation/cross_boundary.py`` 新增 ``attach_source_note``（默认开）
  ——块内含表格行（``UnitEvidence.cells`` 非空）时，同页、版面在其下方且垂直间距
  < 12pt、形似「来源注 + 说明性分句」的 kept 注段保序聚合进块证据。
  效果：industry-008 的 a-3/a-5 转绿 ⇒ EvidencePass 23/24 → **24/24**，
  逐类门 company/industry/macro **8/8 全过**，82 目标零回退、负例 6×0、选择不变。
  ``service.py`` 字节零改动（既有 ``aggregate_band_chunks`` 接线直接生效）。

archive-first：被覆盖字节先用 ``git show HEAD:<path>`` 取回改前版本落到 ``before-r4y/``，
逐条断言 sha256 == 上一修订绑定值（cross_boundary ← i0c-r4u、tests ← i0c-r4u、
validator ← i0c-r4x）。

用法： uv run python gen_i0c_r4y.py [--no-write]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path("/home/administrator/FrontierAgent").resolve()
BASE = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild"
FREEZES = BASE / "freezes"
AUDIT = BASE / "audits/20260923-r4y-footnote-rebind"
BEFORE = AUDIT / "before-r4y"
VALIDATOR = FREEZES / "validate_i0c_freeze.py"
MANIFEST_LIST = FREEZES / "freeze-manifest.json"

NEW_ID = "i0c-r4y"
PARENT_ID = "i0c-r4x"
CROSS = "plugins/corpus/preparation/cross_boundary.py"
TESTS = "tests/test_corpus_selection.py"
VAL_REL = str(VALIDATOR.relative_to(ROOT))

I_NOTE_GATES = (
    "test_source_note_attached_below_table_row",
    "test_source_note_ignores_pure_source_label",
    "test_source_note_requires_below_adjacent_and_same_page",
    "test_source_note_requires_table_row_anchor",
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def binding_of(snapshot: str, group: str) -> dict[str, str]:
    data = json.loads((FREEZES / f"{snapshot}.json").read_text(encoding="utf-8"))
    return (data.get("binding") or {}).get(group, {})


def previous_binding() -> dict[str, str]:
    out: dict[str, str] = {}
    out.update(binding_of("i0c-r4u", "chain_rebind_implementation"))
    out.update(binding_of("i0c-r4u", "chain_rebind_tests"))
    out.update(binding_of("i0c-r4x", "freeze_validator"))
    return out


def git_show(relpath: str) -> bytes | None:
    r = subprocess.run(["git", "show", f"HEAD:{relpath}"], cwd=ROOT, capture_output=True)
    return r.stdout if r.returncode == 0 else None


def archive_first(paths: list[str]) -> None:
    prev = previous_binding()
    for rel in paths:
        target = BEFORE / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        data = git_show(rel)
        if data is None:
            raise RuntimeError(f"git HEAD 无该文件（无法归档改前字节）: {rel}")
        target.write_bytes(data)  # 总是覆盖 ⇒ 幂等
        actual = digest(target)
        expected = prev.get(rel)
        if expected is not None and expected != actual:
            raise RuntimeError(
                f"归档与上一修订绑定不符（先改后归档？）: {rel} {expected[:12]} != {actual[:12]}")
    print(f"[archive-first] {len(paths)} 份归档 → {BEFORE.relative_to(ROOT)}，逐条与上一绑定一致")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args()

    paths = [CROSS, TESTS, VAL_REL]
    archive_first(paths)

    h_cross = digest(ROOT / CROSS)
    h_tests = digest(ROOT / TESTS)

    vt = VALIDATOR.read_text(encoding="utf-8")
    if f'if "{NEW_ID}" in by_id:' in vt:
        print("[validator] r4y 补丁已存在，跳过（幂等）")
    else:
        anchor = "    merge_binding(i0c_current_binding, bindingr4x)\n"
        if anchor not in vt:
            raise RuntimeError("锚点缺失：r4x 块末尾")
        block = (
            "\n# r4y（D2 表格来源注聚合，U 2026-09-23 授权实施）：只重绑 cross_boundary.py /\n"
            "# test_corpus_selection.py / 验证器；service.py 字节零改动（既有接线直接生效）。\n"
            f'if "{NEW_ID}" in by_id:\n'
            f'    r4y = load_json(BASE / by_id["{NEW_ID}"]["file"])\n'
            f'    parentr4y = BASE / by_id["{PARENT_ID}"]["file"]\n'
            '    check(r4y.get("parent_snapshot") == {"snapshot_id": "' + PARENT_ID + '",\n'
            '          "path": str(parentr4y.relative_to(ROOT)), "sha256": digest(parentr4y)},\n'
            '          "r4y parent mismatch")\n'
            '    bindingr4y = r4y.get("binding", {})\n'
            '    check(set(bindingr4y) == {"chain_rebind_implementation", "chain_rebind_tests",\n'
            '                             "freeze_validator"},\n'
            '          "r4y binding groups mismatch")\n'
            '    check(set(bindingr4y.get("chain_rebind_implementation", {})) == {\n'
            '        "' + CROSS + '"}, "r4y implementation boundary mismatch")\n'
            '    check(set(bindingr4y.get("chain_rebind_tests", {})) == {\n'
            '        "' + TESTS + '"}, "r4y tests boundary mismatch")\n'
            '    # 语义门：来源注谓词落地（开关默认开 + 段形/版面双判据 + 免重摄入）\n'
            '    cb_src = (ROOT / "' + CROSS + '").read_text(encoding="utf-8")\n'
            '    check("attach_source_note: bool = True" in cb_src\n'
            '          and "def _is_source_note" in cb_src\n'
            '          and "_SOURCE_NOTE_MAX_GAP_PT" in cb_src\n'
            '          and "_SOURCE_NOTE_EXPLAIN" in cb_src,\n'
            '          "r4y cross_boundary must carry the source-note predicate")\n'
            '    ts_src = (ROOT / "' + TESTS + '").read_text(encoding="utf-8")\n'
            '    for gate in (' + ", ".join(f'"{g}"' for g in I_NOTE_GATES) + '):\n'
            '        check(gate in ts_src, f"r4y tests must carry I-NOTE-1 gate {gate}")\n'
            '    check(any("source_note" in k or "footnote" in k\n'
            '              for k in (r4y.get("corrections") or {})),\n'
            '          "r4y corrections must record the footnote aggregation")\n'
            '    merge_binding(i0c_current_binding, bindingr4y)\n'
        )
        vt = vt.replace(anchor, anchor + block, 1)
        VALIDATOR.write_text(vt, encoding="utf-8")
        print("[validator] r4y 块已写入")
    h_validator = digest(VALIDATOR)
    print(f"[validator] {VAL_REL} sha256={h_validator[:12]}")

    snapshot = {
        "snapshot_id": NEW_ID,
        "revision": "r4y",
        "phase": "i0c",
        "status": "frozen",
        "parent_snapshot": {
            "snapshot_id": PARENT_ID,
            "path": str((FREEZES / f"{PARENT_ID}.json").relative_to(ROOT)),
            "sha256": digest(FREEZES / f"{PARENT_ID}.json"),
        },
        "binding": {
            "chain_rebind_implementation": {CROSS: h_cross},
            "chain_rebind_tests": {TESTS: h_tests},
            "freeze_validator": {VAL_REL: h_validator},
        },
        "corrections": {
            "footnote_aggregation": (
                "D2 表格来源注聚合落地（U 2026-09-23 授权）：cross_boundary.aggregate_band_chunks "
                "新增 attach_source_note（默认开）——块内表格行（UnitEvidence.cells 非空）时，同页、"
                "版面在其下方且垂直间距 < 12pt、形似「来源注 + 说明性分句」的 kept 注段按 "
                "(ordinal, unit_id) 保序聚合。service.py 零改动。复验 A/B（d2-replay.json）："
                "industry-008 a-3/a-5 off→on 转绿，82 目标零回退且新增恰为此两条，"
                "EvidencePass 23/24 → 24/24，逐类 8/8 全过，负例 6×0，选择不变（带宽 33≤49），"
                "产品路径逐字段相等。"
            ),
            "generality": (
                "普遍性按 r4u 三层扫描法论证（audits/20260923-d2-footnote-scan）：裸谓词 91 段 → "
                "含说明性分句 16 段/5 份语料 → 同页+上方紧邻表格行（Δ<12pt）**4 条配对/2 份语料**；"
                "判据纯结构（不绑金标），触发面与 r4u（全库 1 处）同量级。注意 ordinal 序 ≠ 版面序，"
                "上下关系只能按 bbox 判定。"
            ),
        },
        "notes": [
            "r4y 为 D2 落地入链修订（parent=i0c-r4x）：只动 cross_boundary.py 与 test_corpus_selection.py，"
            "不触碰 i0c-r4x 及更早快照的已冻结字节（追加式索引纪律）。",
            "archive-first：before-r4y/ 保存改前字节（git HEAD 提取），逐条与 i0c-r4u/i0c-r4x 绑定一致。",
            "M6 判据『逐类 ≥95%』与『关键引用题 100%』本轮达成（24/24、8/8）；"
            "I3-5 非回归 / I3-6 最终冻结 / I3-7 重验 / M6 独立复核 + U 具名签认仍未执行 ⇒ 本修订不放行 M6。",
        ],
        "m5_declaration": "not_declared",
    }

    if args.no_write:
        print("[--no-write] 预览完成，未写盘")
        print(json.dumps(snapshot, ensure_ascii=False, indent=1)[:900])
        return 0

    snap_path = FREEZES / f"{NEW_ID}.json"
    snap_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    h_snap = digest(snap_path)
    print(f"[snapshot] {NEW_ID}.json sha256={h_snap[:12]}")

    fl = json.loads(MANIFEST_LIST.read_text(encoding="utf-8"))
    existing = next((s for s in fl["snapshots"] if s.get("snapshot_id") == NEW_ID), None)
    if existing is None:
        fl["snapshots"].append({
            "snapshot_id": NEW_ID, "file": f"{NEW_ID}.json", "sha256": h_snap,
            "parent_snapshot_id": PARENT_ID,
            "created_at": datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
        })
        print("[manifest-list] snapshots 追加", NEW_ID)
    elif existing.get("sha256") != h_snap:
        existing["sha256"] = h_snap
        print(f"[manifest-list] snapshots 同步 {NEW_ID} sha256 → {h_snap[:12]}")
    else:
        print("[manifest-list] 已存在且一致，跳过（幂等）")
    MANIFEST_LIST.write_text(json.dumps(fl, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
