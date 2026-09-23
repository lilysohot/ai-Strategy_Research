"""生成冻结修订 ``i0c-r4x``（parent = i0c-r4w）：把「金标 col 口径改写 + I3-2 全链重跑」入链。

本轮改动（U 2026-09-23 具名授权，见 audits/20260923-b5-e2-col-probe/）：
  source-gold-frozen.jsonl 的 industry-009-claim-001 两条 col/cell 由人工合成列名改为
  原文可派生口径「产能（万吨/年）以及同比增长」→ 候选/审批/批准投影/正式评分输入全部重派生，
  EvidencePass 21/24 → 23/24。本修订只负责**入链**（重绑 + 语义门 + supersession 承接），
  不再改动任何金标/实现/测试字节。

archive-first：被覆盖的字节先用 ``git show HEAD:<path>`` 取回改前版本落到 ``before-r4x/``，
并逐条断言 sha256 == 上一修订绑定值（未绑定路径跳过断言，仅留档）。

用法： uv run python gen_i0c_r4x.py [--no-write]
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
AUDIT = BASE / "audits/20260923-r4x-gold-rebind"
BEFORE = AUDIT / "before-r4x"
VALIDATOR = FREEZES / "validate_i0c_freeze.py"
MANIFEST_LIST = FREEZES / "freeze-manifest.json"
SCORING_MANIFEST = BASE / "i3-2/scoring-input-manifest.json"

NEW_ID = "i0c-r4x"
PARENT_ID = "i0c-r4w"
SB = ".scratch/corpus-evidence-pipeline/ingestion-rebuild"

I3_2_ASSETS = (
    "evidence-targets-candidates.json",
    "evidence-targets-adjudication.md",
    "evidence-targets-review.md",
    "evidence-targets-verification.json",
    "approval-report.json",
    "evidence-targets-decisions.json",
    "evidence-targets-approved.json",
    "source-gold-nearmiss-library.jsonl",
)
GOLD_FILES = ("source-gold-frozen.jsonl", "query-gold-frozen.jsonl")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def previous_binding() -> dict[str, str]:
    """上一修订对本轮被覆盖路径的绑定值。

    不用「按修订号数值合并」的通用实现：字母修订号（r4n/r4v/r4w…）无法被 int() 解析，
    排序会错乱。本轮被覆盖路径的上游绑定来源明确且单一：
      source-gold / i3-2 资产 ← i0c-r26（i3_2_source_gold / i3_2_assets）
      scoring-input-manifest ← i0c-r42（i3_2_relineage）
      validate_i0c_freeze.py ← i0c-r4w（freeze_validator）
    已逐一核验：这些值 == git HEAD~1 对应文件字节的 sha256。
    """

    def binding_of(snapshot: str, group: str) -> dict[str, str]:
        path = FREEZES / f"{snapshot}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        return (data.get("binding") or {}).get(group, {})

    out: dict[str, str] = {}
    out.update(binding_of("i0c-r26", "i3_2_source_gold"))
    out.update(binding_of("i0c-r26", "i3_2_assets"))
    out.update(binding_of("i0c-r42", "i3_2_relineage"))
    out.update(binding_of("i0c-r4w", "freeze_validator"))
    return out


def git_show(relpath: str) -> bytes | None:
    """取回**改前**字节：本次会话的改动已被随后的提交带入 HEAD，故用 HEAD~1。"""

    r = subprocess.run(["git", "show", f"HEAD~1:{relpath}"], cwd=ROOT,
                       capture_output=True)
    return r.stdout if r.returncode == 0 else None


def archive_first(paths: list[str]) -> list[dict]:
    prev = previous_binding()
    records = []
    for r in paths:
        target = BEFORE / r
        target.parent.mkdir(parents=True, exist_ok=True)
        # 总是覆盖写入：保证重跑幂等（避免残留的错误副本被当成改前字节）。
        data = git_show(r)
        if data is None:
            data = (ROOT / r).read_bytes()
        target.write_bytes(data)
        expected = prev.get(r)
        actual = digest(target)
        records.append({"path": r, "sha256": actual,
                        "matches_previous_binding": expected is None or expected == actual})
    bad = [x["path"] for x in records if not x["matches_previous_binding"]]
    if bad:
        raise RuntimeError(f"归档与上一修订绑定不符（先改后归档？）：{bad}")
    return records


def patch(text: str, anchor: str, new: str, *, after: bool = True) -> str:
    if anchor not in text:
        raise RuntimeError(f"锚点缺失: {anchor[:60]}…")
    if after:
        return text.replace(anchor, anchor + new, 1)
    return text.replace(anchor, new + anchor, 1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args()

    paths = ([f"{SB}/{n}" for n in GOLD_FILES]
             + [f"{SB}/i3-2/{n}" for n in I3_2_ASSETS]
             + [f"{SB}/i3-2/query-gold-scoring-v1.jsonl",
                rel(SCORING_MANIFEST), rel(VALIDATOR)])
    records = archive_first(paths)
    print(f"[archive-first] {len(records)} 份归档 → {rel(BEFORE)}，逐条与上一绑定一致")

    h_gold = digest(ROOT / f"{SB}/source-gold-frozen.jsonl")
    h_manifest_before = digest(SCORING_MANIFEST)

    # ---- 1) manifest status/frozen_in 归位（i3s2_scoring_input.py 把它重置成 frozen_r28/r28）----
    sm = json.loads(SCORING_MANIFEST.read_text(encoding="utf-8"))
    sm["status"] = "frozen"
    sm["frozen_in"] = NEW_ID
    sm_new = json.dumps(sm, ensure_ascii=False, indent=2) + "\n"
    tmp = SCORING_MANIFEST.with_suffix(".json.tmp")
    h_manifest = hashlib.sha256(sm_new.encode()).hexdigest() if False else None
    # 先算：写到临时文件再取哈希（不改原文件）
    tmp.write_text(sm_new, encoding="utf-8")
    h_manifest = digest(tmp)
    tmp.unlink()
    print(f"[manifest] status {sm.get('status')} / frozen_in {sm.get('frozen_in')}"
          f" ；{h_manifest_before[:12]} → {h_manifest[:12]}")

    h_jsonl = digest(ROOT / f"{SB}/i3-2/query-gold-scoring-v1.jsonl")
    h_approved = digest(ROOT / f"{SB}/i3-2/evidence-targets-approved.json")

    # ---- 2) 验证器补丁 ----
    vt = VALIDATOR.read_text(encoding="utf-8")
    if 'if "i0c-r4x" in by_id:' in vt:
        print("[validator] r4x 补丁已存在，跳过（幂等）")
    else:
        vt = patch(
            vt,
            f'\nif "i0c-r26" in by_id:\n    i0c26 = load_json(BASE / by_id["i0c-r26"].get("file", ""))\n',
            (
                "\n# r4x 预置（U 2026-09-23 授权：金标 col 口径改写 → I3-2 全链重派生）："
                "r26/r39/r42 对 source-gold / manifest / jsonl / approved 的『当前字节』断言"
                "改核本修订权威哈希（不改写已关闭审计产物，只确认历史旧值仍被记录）。\n"
                "r4x_superseded_bindings: dict[str, str] = {}\n"
                f'if "{NEW_ID}" in by_id:\n'
                '    r4x_superseded_bindings = {\n'
                f'        "{SB}/source-gold-frozen.jsonl": "{h_gold}",\n'
                f'        "{SB}/i3-2/scoring-input-manifest.json": "{h_manifest}",\n'
                f'        "{SB}/i3-2/query-gold-scoring-v1.jsonl": "{h_jsonl}",\n'
                f'        "{SB}/i3-2/evidence-targets-approved.json": "{h_approved}",\n'
                "    }\n\n"
            ),
            after=False,
        )
        vt = patch(
            vt,
            '    check(\n'
            '        binding26.get("i3_2_source_gold", {}).get(f"{base}/source-gold-frozen.jsonl")\n'
            '        == digest(ROOT / f"{base}/source-gold-frozen.jsonl"),\n'
            '        "r26 source-gold binding mismatch",\n'
            '    )\n',
            '    _sg26 = f"{base}/source-gold-frozen.jsonl"\n'
            "    if _sg26 in r4x_superseded_bindings:\n"
            "        check(digest(ROOT / _sg26) == r4x_superseded_bindings[_sg26]\n"
            "              and binding26.get(\"i3_2_source_gold\", {}).get(_sg26)\n"
            "              != r4x_superseded_bindings[_sg26],\n"
            "              \"r26 superseded binding unresolved: source-gold-frozen.jsonl\")\n"
            "    else:\n"
            "        check(\n"
            "            binding26.get(\"i3_2_source_gold\", {}).get(_sg26)\n"
            "            == digest(ROOT / _sg26),\n"
            "            \"r26 source-gold binding mismatch\",\n"
            "        )\n",
        )
        vt = patch(
            vt,
            'r39_superseded_bindings: dict[str, str] = {}\n',
            f'if "{NEW_ID}" in by_id:\n'
            '    r39_superseded_bindings.update({\n'
            f'        "{SB}/i3-2/scoring-input-manifest.json": "{h_manifest}",\n'
            f'        "{SB}/i3-2/query-gold-scoring-v1.jsonl": "{h_jsonl}",\n'
            f'        "{SB}/i3-2/evidence-targets-approved.json": "{h_approved}",\n'
            '    })\n',
        )
        vt = patch(
            vt,
            '    check(manifest42.get("frozen_in") == "i0c-r42", "r42 manifest frozen_in must point at r42")\n',
            '    if f"{SB}/i3-2/scoring-input-manifest.json" in r4x_superseded_bindings:\n'
            '        check(manifest42.get("frozen_in") == NEW_R4X_ID,\n'
            '              "r42 manifest frozen_in must be re-pointed at the latest gold revision")\n'
            '    else:\n'
            '        check(manifest42.get("frozen_in") == "i0c-r42", "r42 manifest frozen_in must point at r42")\n',
        )
        vt = patch(
            vt,
            '    check(plan42.get("binding", {}).get(".scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-2/scoring-input-manifest.json") ==\n'
            '          digest(ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-2/scoring-input-manifest.json"),\n'
            '          "r42 plan must rebind scoring-input-manifest to rebuilt bytes")\n',
            '    _mf42 = f"{SB}/i3-2/scoring-input-manifest.json"\n'
            '    if _mf42 in r4x_superseded_bindings:\n'
            '        check(digest(ROOT / _mf42) == r4x_superseded_bindings[_mf42]\n'
            '              and plan42.get("binding", {}).get(_mf42) != r4x_superseded_bindings[_mf42],\n'
            '              "r42 superseded binding unresolved: scoring-input-manifest")\n'
            '    else:\n'
            '        check(plan42.get("binding", {}).get(_mf42) == digest(ROOT / _mf42),\n'
            '              "r42 plan must rebind scoring-input-manifest to rebuilt bytes")\n',
        )
        vt = patch(
            vt,
            '    merge_binding(i0c_current_binding, bindingr4w)\n',
            "\n# r4x（金标 col 口径改写 → I3-2 全链重派生，U 2026-09-23 具名授权）：只重绑\n"
            "# source-gold / i3-2 资产 / manifest 血缘 / 验证器；不触碰任何实现/测试/守卫字节。\n"
            f'if "{NEW_ID}" in by_id:\n'
            f'    r4x = load_json(BASE / by_id["{NEW_ID}"]["file"])\n'
            f'    parentr4x = BASE / by_id["{PARENT_ID}"]["file"]\n'
            '    check(r4x.get("parent_snapshot") == {"snapshot_id": "' + PARENT_ID + '",\n'
            '          "path": str(parentr4x.relative_to(ROOT)), "sha256": digest(parentr4x)},\n'
            '          "r4x parent mismatch")\n'
            '    bindingr4x = r4x.get("binding", {})\n'
            '    check(set(bindingr4x) == {"i3_2_source_gold", "i3_2_assets", "i3_2_relineage",\n'
            '                             "freeze_validator"},\n'
            '          "r4x binding groups mismatch")\n'
            '    check(set(bindingr4x.get("i3_2_source_gold", {})) == {\n'
            f'        "{SB}/source-gold-frozen.jsonl"'
            '}, "r4x source-gold boundary mismatch")\n'
            '    check(set(bindingr4x.get("i3_2_assets", {})) == {\n'
            f'        f"{{SB}}/i3-2/{{name}}" for name in (\n'
            '            "evidence-targets-candidates.json", "evidence-targets-adjudication.md",\n'
            '            "evidence-targets-review.md", "evidence-targets-verification.json",\n'
            '            "approval-report.json", "evidence-targets-decisions.json",\n'
            '            "evidence-targets-approved.json", "source-gold-nearmiss-library.jsonl")},\n'
            '          "r4x i3_2_assets boundary mismatch")\n'
            '    check(set(bindingr4x.get("i3_2_relineage", {})) == {\n'
            f'        "{SB}/i3-2/scoring-input-manifest.json"'
            '}, "r4x relineage boundary mismatch")\n'
            '    check(set(bindingr4x.get("freeze_validator", {})) == {\n'
            f'        "{SB}/freezes/validate_i0c_freeze.py"'
            '}, "r4x freeze_validator boundary mismatch")\n'
            '    # 语义门：金标 col 已改为原文可派生口径，且不得残留人工合成列名\n'
            '    gold_src = (ROOT / f"{SB}/source-gold-frozen.jsonl").read_text(encoding="utf-8")\n'
            '    check("2026E产能" not in gold_src and "产能（配额）" not in gold_src,\n'
            '          "r4x source-gold must drop the synthetic column labels")\n'
            '    check("产能（万吨/年）以及同比增长" in gold_src,\n'
            '          "r4x source-gold must carry the derivable column label")\n'
            '    manifest_r4x = load_json(ROOT / f"{SB}/i3-2/scoring-input-manifest.json")\n'
            '    check(manifest_r4x.get("status") == "frozen" and manifest_r4x.get("frozen_in") == "' + NEW_ID + '",\n'
            '          "r4x manifest must be frozen and point at r4x")\n'
            '    check(manifest_r4x.get("counts") == {"questions": 30, "answerable": 24,\n'
            '                                        "no_answer": 6, "required": 79,\n'
            '                                        "supplementary": 20},\n'
            '          "r4x manifest counts must stay 30/24/6/79/20")\n'
            '    check(any("col" in k or "gold" in k for k in (r4x.get("corrections") or {})),\n'
            '          "r4x corrections must record the gold column revision")\n'
            '    merge_binding(i0c_current_binding, bindingr4x)\n',
        )
        vt = patch(
            vt,
            'if "i0c-r4w" in by_id else ""))',
            'if "i0c-r4w" in by_id else "")\n'
            '      + ("; r4x 金标 col 口径改写入链（U 2026-09-23 具名授权）：source-gold '
            'industry-009-claim-001 的 R32/尿素 两条 col/cell 由人工合成列名（2026E产能（配额）/'
            '2026E产能）改为原文可派生口径『产能（万吨/年）以及同比增长』（quote/row/unit/period '
            '不变）；候选/审批件 based_on/批准投影/正式评分输入全部重派生，EvidencePass '
            '21/24→23/24（industry 5/8→7/8），40 项决定在新候选下 unresolved=0；'
            'r26/r39/r42 对旧字节的断言按 r4r 先例以 supersession 承接" if "i0c-r4x" in by_id else ""))',
        )
        # NEW_R4X_ID 常量（供 r42 分支使用）
        vt = patch(vt, 'r39_superseded_bindings: dict[str, str] = {}\n',
                   '', after=True)  # no-op guard
        vt = vt.replace('r39_superseded_bindings: dict[str, str] = {}\n',
                        'r39_superseded_bindings: dict[str, str] = {}\nNEW_R4X_ID = "' + NEW_ID + '"\n', 1)
        VALIDATOR.write_text(vt, encoding="utf-8")
        print("[validator] r4x 块 + supersession 分支已写入")

    h_validator = digest(VALIDATOR)
    print(f"[validator] {rel(VALIDATOR)} sha256={h_validator[:12]}")

    # ---- 3) 写快照 ----
    parent_file = FREEZES / f"{PARENT_ID}.json"
    assets = {f"{SB}/i3-2/{n}": digest(ROOT / f"{SB}/i3-2/{n}") for n in I3_2_ASSETS}
    snapshot = {
        "snapshot_id": NEW_ID,
        "revision": "r4x",
        "phase": "i0c",
        "status": "frozen",
        "parent_snapshot": {
            "snapshot_id": PARENT_ID,
            "path": rel(parent_file),
            "sha256": digest(parent_file),
        },
        "binding": {
            "i3_2_source_gold": {f"{SB}/source-gold-frozen.jsonl": h_gold},
            "i3_2_assets": assets,
            "i3_2_scoring_input": {f"{SB}/i3-2/query-gold-scoring-v1.jsonl": h_jsonl},
            "i3_2_relineage": {rel(SCORING_MANIFEST): h_manifest},
            "freeze_validator": {rel(VALIDATOR): h_validator},
        },
        "corrections": {
            "gold_column_derivability": (
                "U 2026-09-23 具名授权：I0A-4 标注 industry-009-claim-001 的两条 table_cell "
                "（row=R32 / row=尿素）的 col 原写作人工合成列名『2026E产能（配额）』『2026E产能』，"
                "机器不可派生。经原文机读核对（build 1227c2a34d… page:10：产能组列=2024/2025/2026E，"
                "ord563 R32=24.0/28.5/28.5、ord529 尿素=7696.0/7956.0/8068.0，两个 quote 均正确）"
                "与反事实探针（audits/20260923-b5-e2-col-probe/e2-col-probe.json：唯一可派生候选）"
                "，改为原文列组标签『产能（万吨/年）以及同比增长』；quote/row/unit/period/text "
                "一律不动。候选/审批件 based_on/批准投影/正式评分输入随之重派生。"
                "语义代价：locator 只锁产能列组、不再锁 2026E 年份列（当前两题取值无歧义）。"
            ),
            "r26_r39_r42_supersession": (
                "source-gold / scoring-input-manifest / query-gold-scoring-v1.jsonl / "
                "evidence-targets-approved.json 四路径的当前字节已随本修订演进；r26 的 "
                "source-gold 绑定、r39 与 r42 对已关闭审计产物 calibration-plan-v2.json 的 "
                "pre-run binding 断言按 r4r 先例以 supersession 承接（改核权威哈希 + 确认历史旧值），"
                "不改写任何已关闭审计产物字节。"
            ),
        },
        "notes": [
            "r4x 为金标 col 口径改写的入链修订（parent=i0c-r4w）：零实现/测试/守卫字节改动，"
            "只重绑 source-gold、i3-2 八项资产、manifest 血缘与验证器；不触碰 i0c-r4w 及更早快照的已冻结字节（追加式索引纪律）。",
            "archive-first：before-r4x/ 保存改前字节（git HEAD 提取），逐条与上一修订绑定一致。",
            "EvidencePass 21/24 → 23/24（industry 5/8 → 7/8）；剩余 industry-008 a-3/a-5（表注未进带）"
            "未处置，故 M6 逐类门仍红（87.5% < 95%），本修订不构成 M6 放行。",
        ],
        "m5_declaration": "not_declared",
    }

    # ---- 4) 更新 freeze-manifest ----
    fl = json.loads(MANIFEST_LIST.read_text(encoding="utf-8"))
    fl.setdefault("snapshots", [])

    if args.no_write:
        print("[--no-write] 预览完成，未写盘")
        print(json.dumps(snapshot, ensure_ascii=False, indent=1)[:1200])
        return 0

    SCORING_MANIFEST.write_text(sm_new, encoding="utf-8")
    print(f"[manifest] 已写 status=frozen / frozen_in={NEW_ID}")

    snap_path = FREEZES / f"{NEW_ID}.json"
    snap_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    h_snap = digest(snap_path)
    print(f"[snapshot] {rel(snap_path)} sha256={h_snap[:12]}")

    existing = next((s for s in fl["snapshots"] if s.get("snapshot_id") == NEW_ID), None)
    if existing is None:
        fl["snapshots"].append({
            "snapshot_id": NEW_ID,
            "file": f"{NEW_ID}.json",
            "sha256": h_snap,
            "parent_snapshot_id": PARENT_ID,
            "created_at": datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
        })
        print("[manifest-list] snapshots 追加", NEW_ID)
    elif existing.get("sha256") != h_snap:
        # 重跑时快照字节可能因验证器哈希变化而更新，索引条目必须同步（否则索引指向过期字节）。
        existing["sha256"] = h_snap
        print(f"[manifest-list] snapshots 同步 {NEW_ID} sha256 → {h_snap[:12]}")
    else:
        print("[manifest-list] 已存在且一致，跳过（幂等）")
    MANIFEST_LIST.write_text(json.dumps(fl, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
