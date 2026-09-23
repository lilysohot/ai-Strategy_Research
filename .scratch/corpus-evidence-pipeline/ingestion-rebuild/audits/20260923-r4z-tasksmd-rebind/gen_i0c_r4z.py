"""生成冻结修订 ``i0c-r4z``（parent = i0c-r4y）：把 I3-5 旧检索/财务非回归的台账回填入链。

本轮改动（I3-5 执行收尾，复跑证据见 audits/20260923-i35-legacy-nonregress/）：
  ``docs/plan/corpus-ingestion-rebuild-tasks.md`` §0/§3.6 回填 I3-5 执行状态
  （财务 47/47+公式 7/7+高盛负控 PASS、golden 19/19、客户表 12/12、正文 2/2、
  宏观 0/3 单列、guosen_maotai held_out、审批契约门 32 passed）。
  零模型调用、原库零写入、留出零读取；不触碰任何实现/测试/守卫/金标字节。

archive-first：
  - tasks.md 改前字节取自 ``git show HEAD:``（sha256 断言 == i0c-r42
    chain_rebind_evidence 绑定 14006ef8…）；
  - 验证器改块前字节取自当前盘面（sha256 断言 == i0c-r4y freeze_validator 绑定 6031239c…）。

用法： uv run python gen_i0c_r4z.py [--no-write]
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
AUDIT = BASE / "audits/20260923-r4z-tasksmd-rebind"
BEFORE = AUDIT / "before-r4z"
VALIDATOR = FREEZES / "validate_i0c_freeze.py"
MANIFEST_LIST = FREEZES / "freeze-manifest.json"

NEW_ID = "i0c-r4z"
PARENT_ID = "i0c-r4y"
TASKS = "docs/plan/corpus-ingestion-rebuild-tasks.md"
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
    # tasks.md：改前字节只能来自 git HEAD（盘面已是回填后字节），须与 r42 绑定一致。
    tasks_prev = binding_of("i0c-r42", "chain_rebind_evidence").get(TASKS)
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
    # 验证器：改块前字节 = 当前盘面（本轮尚未触碰），须与 r4y 绑定一致。
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

    vt = VALIDATOR.read_text(encoding="utf-8")
    if f'if "{NEW_ID}" in by_id:' in vt:
        print("[validator] r4z 补丁已存在，跳过（幂等）")
    else:
        anchor = "    merge_binding(i0c_current_binding, bindingr4y)\n"
        if anchor not in vt:
            raise RuntimeError("锚点缺失：r4y 块末尾")
        block = (
            "\n# r4z（I3-5 旧检索/财务非回归台账回填入链）：只重绑 tasks.md 与验证器；\n"
            "# 零模型调用、原库零写入、留出零读取，不触碰任何实现/测试/守卫/金标字节。\n"
            f'if "{NEW_ID}" in by_id:\n'
            f'    r4z = load_json(BASE / by_id["{NEW_ID}"]["file"])\n'
            f'    parentr4z = BASE / by_id["{PARENT_ID}"]["file"]\n'
            '    check(r4z.get("parent_snapshot") == {"snapshot_id": "' + PARENT_ID + '",\n'
            '          "path": str(parentr4z.relative_to(ROOT)), "sha256": digest(parentr4z)},\n'
            '          "r4z parent mismatch")\n'
            '    bindingr4z = r4z.get("binding", {})\n'
            '    check(set(bindingr4z) == {"chain_rebind_evidence", "freeze_validator"},\n'
            '          "r4z binding groups mismatch")\n'
            '    check(set(bindingr4z.get("chain_rebind_evidence", {})) == {\n'
            '        "' + TASKS + '"}, "r4z evidence boundary mismatch")\n'
            '    check(set(bindingr4z.get("freeze_validator", {})) == {\n'
            '        "' + VAL_REL + '"}, "r4z freeze_validator boundary mismatch")\n'
            '    # 语义门：tasks.md 须携带 I3-5 执行状态回填及其证据目录指针。\n'
            '    tasks_src = (ROOT / "' + TASKS + '").read_text(encoding="utf-8")\n'
            '    check("audits/20260923-i35-legacy-nonregress" in tasks_src\n'
            '          and "I3-5" in tasks_src,\n'
            '          "r4z tasks.md must carry the I3-5 non-regression backfill")\n'
            '    check(any("i3_5" in k or "i35" in k\n'
            '              for k in (r4z.get("corrections") or {})),\n'
            '          "r4z corrections must record the I3-5 backfill entry")\n'
            '    merge_binding(i0c_current_binding, bindingr4z)\n'
        )
        vt = vt.replace(anchor, anchor + block, 1)
        VALIDATOR.write_text(vt, encoding="utf-8")
        print("[validator] r4z 块已写入")
    h_validator = digest(VALIDATOR)
    print(f"[validator] {VAL_REL} sha256={h_validator[:12]}")

    snapshot = {
        "snapshot_id": NEW_ID,
        "revision": "r4z",
        "phase": "i0c",
        "status": "frozen",
        "parent_snapshot": {
            "snapshot_id": PARENT_ID,
            "path": str((FREEZES / f"{PARENT_ID}.json").relative_to(ROOT)),
            "sha256": digest(FREEZES / f"{PARENT_ID}.json"),
        },
        "binding": {
            "chain_rebind_evidence": {TASKS: h_tasks},
            "freeze_validator": {VAL_REL: h_validator},
        },
        "corrections": {
            "i3_5_nonregress_backfill": (
                "I3-5 旧检索/财务非回归已执行并回填 tasks.md §0/§3.6"
                "（audits/20260923-i35-legacy-nonregress/，零模型、原库零写入、留出零读取）："
                "财务 47/47+公式 7/7+高盛负控 PASS（库级等价路径 build_evidence_run+冻结 "
                "field_checks/calculations，I2-7 后冻结契约不可原样执行的偏差已登记）；"
                "golden 19/19（O6 按 r27 排除，旧库 legacy 读链只读）；客户表 12/12（冻结 run 复验）；"
                "正文冻结 2 例 2/2；宏观 0/3 保留单列；guosen_maotai 10 格 held_out_not_run_in_dev；"
                "答案约束登记/投影保真门（test_approval_contract.py）32 passed。"
                "I3-6/I3-7 另做，本修订不构成最终版本放行。"
            ),
            "rebind_scope": (
                "仅重绑 docs/plan/corpus-ingestion-rebuild-tasks.md（14006ef8…→"
                f"{h_tasks[:8]}…）与验证器自哈希（6031239c…→{h_validator[:8]}…）；"
                "其余绑定沿用上游修订，不借机触碰实现/测试/守卫字节。"
            ),
        },
        "notes": [
            "r4z 为 I3-5 台账回填入链修订（parent=i0c-r4y）：只重绑 tasks.md 与验证器，"
            "不触碰 i0c-r4y 及更早快照的已冻结字节（追加式索引纪律）。",
            "archive-first：before-r4z/ 保存改前字节——tasks.md 取自 git HEAD"
            "（sha256 == i0c-r42 chain_rebind_evidence 绑定 14006ef8…），"
            "validator 取自改块前盘面字节（sha256 == i0c-r4y freeze_validator 绑定 6031239c…）。",
            "I3-5 结果为非回归核验（适用旧基线逐项见 audits/20260923-i35-legacy-nonregress/README.md）；"
            "真实答案语义测试未授权前 not_run 不计作通过；此处不是最终版本放行。",
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
