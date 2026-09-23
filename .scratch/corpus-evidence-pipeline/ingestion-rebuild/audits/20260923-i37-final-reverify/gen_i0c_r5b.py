"""生成冻结修订 ``i0c-r5b``（parent = i0c-r5a）：把 I3-7 最终重验入链。

本轮改动（I3-7 执行收尾，证据见 audits/20260923-i37-final-reverify/）：
  ``docs/plan/corpus-ingestion-rebuild-tasks.md`` §0/§3.6 回填 I3-7 执行状态；
  审计目录新增重建/评分/电池/legacy 四份 write-once 结果与 README。
  零模型、隔离 PG（沙箱 + 临时第三库用后 DROP）、留出零读取；
  不触碰任何实现/测试/守卫/金标字节。

archive-first：
  - tasks.md 改前字节取自 ``git show HEAD:``（sha256 断言 == i0c-r5a chain_rebind_evidence
    绑定 fd254523…）；
  - 验证器改块前字节取自当前盘面（sha256 断言 == i0c-r5a freeze_validator 绑定 971312ae…）。

用法： uv run python gen_i0c_r5b.py [--no-write]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path("/home/administrator/FrontierAgent").resolve()
BASE = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild"
FREEZES = BASE / "freezes"
AUDIT = BASE / "audits/20260923-i37-final-reverify"
BEFORE = AUDIT / "before-r5b"
VALIDATOR = FREEZES / "validate_i0c_freeze.py"
MANIFEST_LIST = FREEZES / "freeze-manifest.json"

NEW_ID = "i0c-r5b"
PARENT_ID = "i0c-r5a"
TASKS = "docs/plan/corpus-ingestion-rebuild-tasks.md"
AUDIT_REL = str(AUDIT.relative_to(ROOT))
EVIDENCE_FILES = [
    f"{AUDIT_REL}/rebuild-report.json",
    f"{AUDIT_REL}/rebuild-report.md",
    f"{AUDIT_REL}/i37-score-results.json",
    f"{AUDIT_REL}/i37-tests-results.json",
    f"{AUDIT_REL}/i37-legacy-results.json",
]
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
    h_evidence = {rel: digest(ROOT / rel) for rel in EVIDENCE_FILES}

    vt = VALIDATOR.read_text(encoding="utf-8")
    if f'if "{NEW_ID}" in by_id:' in vt:
        print("[validator] r5b 补丁已存在，跳过（幂等）")
    else:
        anchor = "    merge_binding(i0c_current_binding, bindingr5a)\n"
        if anchor not in vt:
            raise RuntimeError("锚点缺失：r5a 块末尾")
        block = (
            "\n# r5b（I3-7 最终重验入链）：重绑 tasks.md + 验证器 + I3-7 重验证据五件；\n"
            "# 零模型、隔离 PG、留出零读取，不触碰任何实现/测试/守卫/金标字节。\n"
            f'if "{NEW_ID}" in by_id:\n'
            f'    r5b = load_json(BASE / by_id["{NEW_ID}"]["file"])\n'
            f'    parentr5b = BASE / by_id["{PARENT_ID}"]["file"]\n'
            '    check(r5b.get("parent_snapshot") == {"snapshot_id": "' + PARENT_ID + '",\n'
            '          "path": str(parentr5b.relative_to(ROOT)), "sha256": digest(parentr5b)},\n'
            '          "r5b parent mismatch")\n'
            '    bindingr5b = r5b.get("binding", {})\n'
            '    check(set(bindingr5b) == {"i37_reverify_evidence", "chain_rebind_evidence",\n'
            '                             "freeze_validator"},\n'
            '          "r5b binding groups mismatch")\n'
            '    check(set(bindingr5b.get("i37_reverify_evidence", {})) == {\n'
            + "".join(f'        "{rel}",\n' for rel in EVIDENCE_FILES)
            + '        }, "r5b evidence boundary mismatch")\n'
            '    check(set(bindingr5b.get("chain_rebind_evidence", {})) == {\n'
            '        "' + TASKS + '"}, "r5b evidence boundary mismatch")\n'
            '    check(set(bindingr5b.get("freeze_validator", {})) == {\n'
            '        "' + VAL_REL + '"}, "r5b freeze_validator boundary mismatch")\n'
            '    # 语义门：I3-7 重验证据须全绿且与冻结版本一致（revs/policy 由各报告内字段断言）。\n'
            '    rb37 = json.loads((ROOT / "' + AUDIT_REL + '/rebuild-report.json")\n'
            '                      .read_text(encoding="utf-8"))\n'
            '    check(rb37.get("summary", {}).get("published") == 8\n'
            '          and rb37.get("summary", {}).get("active") == 8\n'
            '          and rb37.get("summary", {}).get("all_new_build_active") is True,\n'
            '          "r5b rebuild report must be 8/8 published+active")\n'
            '    sc37 = json.loads((ROOT / "' + AUDIT_REL + '/i37-score-results.json")\n'
            '                      .read_text(encoding="utf-8"))\n'
            '    check(sc37.get("passed") is True and sc37.get("gates")\n'
            '          and all(sc37.get("gates").values())\n'
            '          and len(sc37.get("gates")) >= 14,\n'
            '          "r5b score battery must pass all gates")\n'
            '    ts37 = json.loads((ROOT / "' + AUDIT_REL + '/i37-tests-results.json")\n'
            '                      .read_text(encoding="utf-8"))\n'
            '    check(ts37.get("passed") is True and ts37.get("gates")\n'
            '          and all(ts37.get("gates").values())\n'
            '          and len(ts37.get("gates")) >= 9,\n'
            '          "r5b test battery must pass all gates")\n'
            '    lg37 = json.loads((ROOT / "' + AUDIT_REL + '/i37-legacy-results.json")\n'
            '                      .read_text(encoding="utf-8"))\n'
            '    check(lg37.get("overall", {}).get(\n'
            '        "financial_formula_negative_customer_macro_gate") is True,\n'
            '          "r5b legacy non-regression gate must hold")\n'
            '    tasks_src = (ROOT / "' + TASKS + '").read_text(encoding="utf-8")\n'
            '    check("audits/20260923-i37-final-reverify" in tasks_src\n'
            '          and "I3-7" in tasks_src,\n'
            '          "r5b tasks.md must carry the I3-7 reverify backfill")\n'
            '    check(any("i3_7" in k or "i37" in k\n'
            '              for k in (r5b.get("corrections") or {})),\n'
            '          "r5b corrections must record the I3-7 reverify entry")\n'
            '    merge_binding(i0c_current_binding, bindingr5b)\n'
        )
        vt = vt.replace(anchor, anchor + block, 1)
        VALIDATOR.write_text(vt, encoding="utf-8")
        print("[validator] r5b 块已写入")
    h_validator = digest(VALIDATOR)
    print(f"[validator] {VAL_REL} sha256={h_validator[:12]}")

    snapshot = {
        "snapshot_id": NEW_ID,
        "revision": "r5b",
        "phase": "i0c",
        "status": "frozen",
        "parent_snapshot": {
            "snapshot_id": PARENT_ID,
            "path": str((FREEZES / f"{PARENT_ID}.json").relative_to(ROOT)),
            "sha256": digest(FREEZES / f"{PARENT_ID}.json"),
        },
        "binding": {
            "i37_reverify_evidence": h_evidence,
            "chain_rebind_evidence": {TASKS: h_tasks},
            "freeze_validator": {VAL_REL: h_validator},
        },
        "corrections": {
            "i3_7_final_reverify": (
                "I3-7 最终重验已执行并入链（audits/20260923-i37-final-reverify/，零模型、隔离 PG、"
                "留出零读取；对 I3-6 冻结版本 i0c-r4z）：重建 8/8 published+active（revs 与冻结报告"
                "逐一复现）；评分/取证/负例 14 门全绿（QuestionPass/EvidencePass 24/24、三类 "
                "DocRecall=1、关键题 22/22、FP=0/伪引用=0、b5 基线零回退、prune on 非劣化、"
                "abstain=on 负例 6/6、authority 回环全过）；测试电池 9 门全绿（7 lanes + 恢复后 "
                "build_id 确定性复现 + active 指针严格=8 源）；legacy 非回归与 I3-5 同口径全过。"
                "偏差登记：D2/D6 双重偏差（守卫对 CORPUS_DSN 投毒 → 无守卫 lane；legacy 形态前提 → "
                "第三库 i2_d2d6_corpus 用后 DROP）与守卫 Popen 注入运行纪律（父 runner 不装守卫、"
                "恢复经 --restore 子进程）——均 fail-closed 行为正确非缺陷。pending（非 I3-7 门）："
                "abstain=on 下 24/24 正例被拒检待 U 裁决。全部结果与冻结版本一致；"
                "M6 不放行（须独立复核 + U 具名签认）。"
            ),
            "rebind_scope": (
                "仅重绑 docs/plan/corpus-ingestion-rebuild-tasks.md（fd254523…→" + h_tasks[:8] + "…）、"
                "验证器自哈希（971312ae…→" + h_validator[:8] + "…）与新增 I3-7 重验证据五件"
                "（rebuild/score/tests/legacy）；i3-final-freeze-manifest.json 沿用 r5a 绑定不重复；"
                "不借机触碰实现/测试/守卫/金标字节。"
            ),
        },
        "notes": [
            "r5b 为 I3-7 最终重验入链修订（parent=i0c-r5a）：不触碰 i0c-r5a 及更早快照的"
            "已冻结字节（追加式索引纪律）。",
            "archive-first：before-r5b/ 保存改前字节——tasks.md 取自 git HEAD"
            "（sha256 == i0c-r5a chain_rebind_evidence 绑定 fd254523…），"
            "validator 取自改块前盘面字节（sha256 == i0c-r5a freeze_validator 绑定 971312ae…）。",
            "I3-7 重验证据五件以 i37_reverify_evidence 组哈希绑定，语义门断言各报告全绿；"
            "M6 放行仍须独立复核 + U 具名签认。",
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
