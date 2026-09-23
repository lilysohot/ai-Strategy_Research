"""生成冻结修订 ``i0c-r5a``（parent = i0c-r4z）：把 I3-6 最终冻结入链。

本轮改动（I3-6 执行收尾，证据见 audits/20260923-i36-final-freeze/）：
  新增 ``.scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-final-freeze-manifest.json``
  （不可变最终 manifest：冻结版本=i0c-r4z 链头 + 关键资产哈希 + 运行时配置 + 校准收口
  + M4/M5 重验核定九组 + 待定项核定）；
  ``docs/plan/corpus-ingestion-rebuild-tasks.md`` §0/§3.6 回填 I3-6 执行状态。
  零模型、零写库、留出零读取；不触碰任何实现/测试/守卫/金标字节。

archive-first：
  - tasks.md 改前字节取自 ``git show HEAD:``（sha256 断言 == i0c-r4z chain_rebind_evidence
    绑定 aef577bd…）；
  - 验证器改块前字节取自当前盘面（sha256 断言 == i0c-r4z freeze_validator 绑定 817b7779…）。

用法： uv run python gen_i0c_r5a.py [--no-write]
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
AUDIT = BASE / "audits/20260923-i36-final-freeze"
BEFORE = AUDIT / "before-r5a"
VALIDATOR = FREEZES / "validate_i0c_freeze.py"
MANIFEST_LIST = FREEZES / "freeze-manifest.json"

NEW_ID = "i0c-r5a"
PARENT_ID = "i0c-r4z"
TASKS = "docs/plan/corpus-ingestion-rebuild-tasks.md"
FINAL_MANIFEST = ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-final-freeze-manifest.json"
VAL_REL = str(VALIDATOR.relative_to(ROOT))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def binding_of(snapshot: str, group: str) -> dict[str, str]:
    data = json.loads((FREEZES / f"{snapshot}.json").read_text(encoding="utf-8"))
    return (data.get("binding") or {}).get(group, {})


def git_show(relpath: str) -> bytes | None:
    r = subprocess.run(["git", "show", f"HEAD:{relpath}"], cwd=ROOT, capture_output=True)
    return r.stdout if r.returncode == 0 else None


def archive_first() -> None:
    tasks_prev = binding_of(PARENT_ID, "chain_rebind_evidence").get(TASKS)
    target = BEFORE / TASKS
    target.parent.mkdir(parents=True, exist_ok=True)
    data = git_show(TASKS)
    if data is None:
        raise RuntimeError(f"git HEAD 无该文件（无法归档改前字节）: {TASKS}")
    target.write_bytes(data)  # 总是覆盖 ⇒ 幂等
    actual = digest(target)
    if actual != tasks_prev:
        raise RuntimeError(
            f"归档与上一绑定不符（先改后归档？）: {TASKS} {str(tasks_prev)[:12]} != {actual[:12]}")
    val_prev = binding_of(PARENT_ID, "freeze_validator").get(VAL_REL)
    vtarget = BEFORE / VAL_REL
    vtarget.parent.mkdir(parents=True, exist_ok=True)
    vtarget.write_bytes(VALIDATOR.read_bytes())
    vactual = digest(vtarget)
    if vactual != val_prev:
        raise RuntimeError(
            f"归档与上一绑定不符（验证器已被他人改动？）: {VAL_REL} {str(val_prev)[:12]} != {vactual[:12]}")
    print(f"[archive-first] 2 份归档 → {BEFORE.relative_to(ROOT)}，逐条与上一绑定一致")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args()

    archive_first()

    h_tasks = digest(ROOT / TASKS)
    h_final = digest(ROOT / FINAL_MANIFEST)

    vt = VALIDATOR.read_text(encoding="utf-8")
    if f'if "{NEW_ID}" in by_id:' in vt:
        print("[validator] r5a 补丁已存在，跳过（幂等）")
    else:
        anchor = "    merge_binding(i0c_current_binding, bindingr4z)\n"
        if anchor not in vt:
            raise RuntimeError("锚点缺失：r4z 块末尾")
        block = (
            "\n# r5a（I3-6 最终冻结入链）：重绑最终 manifest + tasks.md + 验证器；\n"
            "# 零模型调用、零写库、留出零读取，不触碰任何实现/测试/守卫/金标字节。\n"
            f'if "{NEW_ID}" in by_id:\n'
            f'    r5a = load_json(BASE / by_id["{NEW_ID}"]["file"])\n'
            f'    parentr5a = BASE / by_id["{PARENT_ID}"]["file"]\n'
            '    check(r5a.get("parent_snapshot") == {"snapshot_id": "' + PARENT_ID + '",\n'
            '          "path": str(parentr5a.relative_to(ROOT)), "sha256": digest(parentr5a)},\n'
            '          "r5a parent mismatch")\n'
            '    bindingr5a = r5a.get("binding", {})\n'
            '    check(set(bindingr5a) == {"final_freeze_manifest", "chain_rebind_evidence",\n'
            '                             "freeze_validator"},\n'
            '          "r5a binding groups mismatch")\n'
            '    check(set(bindingr5a.get("final_freeze_manifest", {})) == {\n'
            '        "' + FINAL_MANIFEST + '"}, "r5a final-manifest boundary mismatch")\n'
            '    check(set(bindingr5a.get("chain_rebind_evidence", {})) == {\n'
            '        "' + TASKS + '"}, "r5a evidence boundary mismatch")\n'
            '    check(set(bindingr5a.get("freeze_validator", {})) == {\n'
            '        "' + VAL_REL + '"}, "r5a freeze_validator boundary mismatch")\n'
            '    # 语义门：最终 manifest 须锚定链头并携带 M4/M5 重验核定与待定项核定。\n'
            '    fm = json.loads((ROOT / "' + FINAL_MANIFEST + '").read_text(encoding="utf-8"))\n'
            '    check(fm.get("artifact") == "i3-final-freeze-manifest",\n'
            '          "r5a final manifest artifact mismatch")\n'
            '    check(fm.get("frozen_version", {}).get("chain_head", {}).get("snapshot_id")\n'
            '          == "' + PARENT_ID + '", "r5a final manifest must anchor the chain head")\n'
            '    check(digest(BASE / by_id["' + PARENT_ID + '"]["file"])\n'
            '          == fm.get("frozen_version", {}).get("chain_head", {}).get("sha256"),\n'
            '          "r5a final manifest chain-head sha must match the snapshot file")\n'
            '    check(len(fm.get("m4_m5_gates_to_reverify") or []) >= 9,\n'
            '          "r5a final manifest must carry the M4/M5 reverify list")\n'
            '    check(len(fm.get("pending_items") or []) >= 4\n'
            '          and fm.get("frozen_assets", {}).get("implementation"),\n'
            '          "r5a final manifest must carry pending items and asset hashes")\n'
            '    tasks_src = (ROOT / "' + TASKS + '").read_text(encoding="utf-8")\n'
            '    check("audits/20260923-i36-final-freeze" in tasks_src\n'
            '          and "I3-6" in tasks_src,\n'
            '          "r5a tasks.md must carry the I3-6 final-freeze backfill")\n'
            '    check(any("i3_6" in k or "i36" in k\n'
            '              for k in (r5a.get("corrections") or {})),\n'
            '          "r5a corrections must record the I3-6 freeze entry")\n'
            '    merge_binding(i0c_current_binding, bindingr5a)\n'
        )
        vt = vt.replace(anchor, anchor + block, 1)
        VALIDATOR.write_text(vt, encoding="utf-8")
        print("[validator] r5a 块已写入")
    h_validator = digest(VALIDATOR)
    print(f"[validator] {VAL_REL} sha256={h_validator[:12]}")

    snapshot = {
        "snapshot_id": NEW_ID,
        "revision": "r5a",
        "phase": "i0c",
        "status": "frozen",
        "parent_snapshot": {
            "snapshot_id": PARENT_ID,
            "path": str((FREEZES / f"{PARENT_ID}.json").relative_to(ROOT)),
            "sha256": digest(FREEZES / f"{PARENT_ID}.json"),
        },
        "binding": {
            "final_freeze_manifest": {FINAL_MANIFEST: h_final},
            "chain_rebind_evidence": {TASKS: h_tasks},
            "freeze_validator": {VAL_REL: h_validator},
        },
        "corrections": {
            "i3_6_final_freeze": (
                "I3-6 最终冻结已执行并入链（audits/20260923-i36-final-freeze/，零模型、零写库、"
                "留出零读取）：冻结版本=i0c-r4z 链头；不可变最终 manifest "
                "i3-final-freeze-manifest.json（关键资产哈希 62 项 + 运行时配置 + 校准收口"
                " 三类 DocRecall=100%、QuestionPass/EvidencePass 24/24、关键题 22/22、FP=0 + "
                "M4/M5 重验核定九组 + 待定项核定——均为另立授权型 not_run，无冻结必需待定项）。"
                "仅冻结版本，M6 不放行（须 I3-7 重验 + 独立复核 + U 具名签认）。"
            ),
            "rebind_scope": (
                "仅重绑 i3-final-freeze-manifest.json（新增，" + h_final[:8] + "…）、"
                f"docs/plan/corpus-ingestion-rebuild-tasks.md（aef577bd…→{h_tasks[:8]}…）"
                f"与验证器自哈希（817b7779…→{h_validator[:8]}…）；其余绑定沿用上游修订，"
                "不借机触碰实现/测试/守卫字节。"
            ),
        },
        "notes": [
            "r5a 为 I3-6 最终冻结入链修订（parent=i0c-r4z）：不触碰 i0c-r4z 及更早快照的"
            "已冻结字节（追加式索引纪律）。",
            "archive-first：before-r5a/ 保存改前字节——tasks.md 取自 git HEAD"
            "（sha256 == i0c-r4z chain_rebind_evidence 绑定 aef577bd…），"
            "validator 取自改块前盘面字节（sha256 == i0c-r4z freeze_validator 绑定 817b7779…）。",
            "I3-7 重验须对本冻结版本执行；I3-6 后任何影响运行的变化将使最终报告失效，"
            "回到新的版本冻结与 I3-7。",
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
