"""生成冻结修订 ``i0c-r5c``（parent = i0c-r5b）：M6 独立复核 + U 具名签认入链。

本轮改动（M6 放行收尾，证据见 audits/20260923-m6-independent-review/）：
  独立复核三份 write-once 探针产物 + review.md + 签认记录 signoff-record-m6.{md,json}；
  ``docs/plan/corpus-ingestion-rebuild-tasks.md`` §0/§3.6 I3-7 行回填 M6 放行状态。
  零模型、沙箱只读复核、留出零读取；不触碰任何实现/测试/守卫/金标字节。

archive-first（**取当前盘面字节**——tasks.md 工作区未 commit，禁用 git show HEAD 模式）：
  - tasks.md 改前字节已归档至 before-r5c/（断言 == i0c-r5b chain_rebind_evidence 3e2413be…）；
  - 验证器改块前字节已归档至 before-r5c/（断言 == i0c-r5b freeze_validator 1e1b63ec…）。
  本脚本**只复核**归档与上一绑定一致（fail-closed），不重复归档。

用法： uv run python gen_i0c_r5c.py [--no-write]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path("/home/administrator/FrontierAgent").resolve()
BASE = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild"
FREEZES = BASE / "freezes"
AUDIT = BASE / "audits/20260923-m6-independent-review"
BEFORE = AUDIT / "before-r5c"
VALIDATOR = FREEZES / "validate_i0c_freeze.py"
MANIFEST_LIST = FREEZES / "freeze-manifest.json"

NEW_ID = "i0c-r5c"
PARENT_ID = "i0c-r5b"
TASKS = "docs/plan/corpus-ingestion-rebuild-tasks.md"
AUDIT_REL = str(AUDIT.relative_to(ROOT))
REVIEW_EVIDENCE = [
    f"{AUDIT_REL}/review.md",
    f"{AUDIT_REL}/m6-hashes.json",
    f"{AUDIT_REL}/m6-rescore.json",
    f"{AUDIT_REL}/m6-dbcheck.json",
]
SIGNOFF_RECORD = [f"{AUDIT_REL}/signoff-record-m6.json", f"{AUDIT_REL}/signoff-record-m6.md"]
VAL_REL = str(VALIDATOR.relative_to(ROOT))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def binding_of(snapshot: str, group: str) -> dict[str, str]:
    data = json.loads((FREEZES / f"{snapshot}.json").read_text(encoding="utf-8"))
    return (data.get("binding") or {}).get(group, {})


def verify_archive_first() -> None:
    tasks_prev = binding_of(PARENT_ID, "chain_rebind_evidence").get(TASKS)
    target = BEFORE / TASKS
    if not target.exists():
        raise RuntimeError(f"缺 archive-first 归档（须为改前当前盘面字节）: {TASKS}")
    actual = digest(target)
    if actual != tasks_prev:
        raise RuntimeError(f"tasks.md 归档 != r5b 绑定（归档时机错误？）: {actual[:12]}")
    val_prev = binding_of(PARENT_ID, "freeze_validator").get(VAL_REL)
    vtarget = BEFORE / VAL_REL
    if not vtarget.exists():
        raise RuntimeError(f"缺 archive-first 归档: {VAL_REL}")
    vactual = digest(vtarget)
    if vactual != val_prev:
        raise RuntimeError(f"验证器归档 != r5b 绑定: {vactual[:12]}")
    cur = digest(ROOT / TASKS)
    if cur == tasks_prev:
        raise RuntimeError("tasks.md 尚未回填（当前字节仍等于 r5b 绑定）——先回填再入链")
    print(f"[archive-first] 2 份归档已复核 == {PARENT_ID} 绑定；tasks.md 已回填（{cur[:12]}…）")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args()

    verify_archive_first()

    h_tasks = digest(ROOT / TASKS)
    h_review = {rel: digest(ROOT / rel) for rel in REVIEW_EVIDENCE}
    h_signoff = {rel: digest(ROOT / rel) for rel in SIGNOFF_RECORD}

    vt = VALIDATOR.read_text(encoding="utf-8")
    if f'if "{NEW_ID}" in by_id:' in vt:
        print("[validator] r5c 补丁已存在，跳过（幂等）")
    else:
        anchor = "    merge_binding(i0c_current_binding, bindingr5b)\n"
        if anchor not in vt:
            raise RuntimeError("锚点缺失：r5b 块末尾")
        block = (
            "\n# r5c（M6 独立复核 + U 具名签认入链）：绑独立复核证据四件 + 签认记录两件 +\n"
            "# tasks.md 回填 + 验证器自哈希；零模型、沙箱只读复核、留出零读取，\n"
            "# 不触碰任何实现/测试/守卫/金标字节。\n"
            f'if "{NEW_ID}" in by_id:\n'
            f'    r5c = load_json(BASE / by_id["{NEW_ID}"]["file"])\n'
            f'    parentr5c = BASE / by_id["{PARENT_ID}"]["file"]\n'
            '    check(r5c.get("parent_snapshot") == {"snapshot_id": "' + PARENT_ID + '",\n'
            '          "path": str(parentr5c.relative_to(ROOT)), "sha256": digest(parentr5c)},\n'
            '          "r5c parent mismatch")\n'
            '    bindingr5c = r5c.get("binding", {})\n'
            '    check(set(bindingr5c) == {"m6_review_evidence", "m6_signoff_record",\n'
            '                             "chain_rebind_evidence", "freeze_validator"},\n'
            '          "r5c binding groups mismatch")\n'
            '    check(set(bindingr5c.get("m6_review_evidence", {})) == {\n'
            + "".join(f'        "{rel}",\n' for rel in REVIEW_EVIDENCE)
            + '        }, "r5c review evidence boundary mismatch")\n'
            '    check(set(bindingr5c.get("m6_signoff_record", {})) == {\n'
            + "".join(f'        "{rel}",\n' for rel in SIGNOFF_RECORD)
            + '        }, "r5c signoff record boundary mismatch")\n'
            '    check(set(bindingr5c.get("chain_rebind_evidence", {})) == {\n'
            '        "' + TASKS + '"}, "r5c tasks.md boundary mismatch")\n'
            '    check(set(bindingr5c.get("freeze_validator", {})) == {\n'
            '        "' + VAL_REL + '"}, "r5c freeze_validator boundary mismatch")\n'
            '    # 语义门：独立复核三探针 all_match/all_ok + 独立性声明；签认记录 signed + 具名。\n'
            '    m6h = json.loads((ROOT / "' + AUDIT_REL + '/m6-hashes.json")\n'
            '                     .read_text(encoding="utf-8"))\n'
            '    check(m6h.get("all_match") is True\n'
            '          and m6h.get("frozen_assets", {}).get("all_match") is True,\n'
            '          "r5c hash probe must show zero drift")\n'
            '    m6r = json.loads((ROOT / "' + AUDIT_REL + '/m6-rescore.json")\n'
            '                     .read_text(encoding="utf-8"))\n'
            '    check(m6r.get("all_match") is True\n'
            '          and m6r.get("independence", {}).get("imports_i37_score") is False,\n'
            '          "r5c rescore probe must reconcile with zero field diffs")\n'
            '    m6d = json.loads((ROOT / "' + AUDIT_REL + '/m6-dbcheck.json")\n'
            '                     .read_text(encoding="utf-8"))\n'
            '    check(m6d.get("all_ok") is True\n'
            '          and m6d.get("pointer_state", {}).get("active_publications") == 8,\n'
            '          "r5c dbcheck probe must verify 8 active sources")\n'
            '    so6 = json.loads((ROOT / "' + AUDIT_REL + '/signoff-record-m6.json")\n'
            '                     .read_text(encoding="utf-8"))\n'
            '    sig6 = so6.get("signature_fields", {})\n'
            '    check(so6.get("status") == "signed" and so6.get("review_result") == "通过"\n'
            '          and sig6.get("reviewer") == "xyl" and sig6.get("reviewed_at")\n'
            '          and "M6" in str(sig6.get("decision", ""))\n'
            '          and so6.get("signed_in") == "' + NEW_ID + '",\n'
            '          "r5c signoff record must be named and release M6")\n'
            '    check("abstain" in json.dumps(so6.get("not_covered", []), ensure_ascii=False),\n'
            '          "r5c signoff must record the abstain known-limitation adjudication")\n'
            '    rv6 = (ROOT / "' + AUDIT_REL + '/review.md").read_text(encoding="utf-8")\n'
            '    check("复核通过" in rv6 and "U 具名签认" in rv6,\n'
            '          "r5c review.md must carry the pass verdict and signoff request")\n'
            '    tasks6 = (ROOT / "' + TASKS + '").read_text(encoding="utf-8")\n'
            '    check("audits/20260923-m6-independent-review" in tasks6\n'
            '          and "M6 放行" in tasks6 and "xyl" in tasks6,\n'
            '          "r5c tasks.md must carry the M6 release backfill")\n'
            '    check(any("m6" in k for k in (r5c.get("corrections") or {})),\n'
            '          "r5c corrections must record the M6 signoff entry")\n'
            '    merge_binding(i0c_current_binding, bindingr5c)\n'
        )
        vt = vt.replace(anchor, anchor + block, 1)
        if not args.no_write:
            VALIDATOR.write_text(vt, encoding="utf-8")
        print("[validator] r5c 块已写入")
    h_validator = digest(VALIDATOR)
    print(f"[validator] {VAL_REL} sha256={h_validator[:12]}")

    snapshot = {
        "snapshot_id": NEW_ID,
        "revision": "r5c",
        "phase": "i0c",
        "status": "frozen",
        "parent_snapshot": {
            "snapshot_id": PARENT_ID,
            "path": str((FREEZES / f"{PARENT_ID}.json").relative_to(ROOT)),
            "sha256": digest(FREEZES / f"{PARENT_ID}.json"),
        },
        "binding": {
            "m6_review_evidence": h_review,
            "m6_signoff_record": h_signoff,
            "chain_rebind_evidence": {TASKS: h_tasks},
            "freeze_validator": {VAL_REL: h_validator},
        },
        "corrections": {
            "m6_signoff": (
                "M6 独立复核与 U 具名签认已完成并入链（audits/20260923-m6-independent-review/，"
                "零模型、沙箱只读、留出零读取）：全新探针不 import I3-7 脚本；三门验证器 exit 0；"
                "r5b 绑定 13 项对账 + 冻结 manifest 62 资产零漂移（chain_manifest 冻结时点字节在 "
                "git 8ec0cb6 精确复得，当前面=冻结面前缀相等+仅追加 r5a/r5b——追加式演进实证）；"
                "独立重评分 30 题逐字段对账零差异（QP/EP 24/24、三类 DocRecall=1、FP=0/伪引用=0、"
                "b5 零回退、prune 名单一致、abstain 负例 6/6、正例拒检 24/24 独立复现、authority "
                "自选样本回环过）；DB 直读 8 源 active、revs 逐 build 冻结公式重算全对、独立 "
                "search→fetch 回环 3/3、i2_d2d6_corpus 确已 DROP；纪律审计与静态门复跑全过。"
                "U（xyl）2026-09-23 具名签认：M6 放行；abstain=on 下 24/24 正例拒检裁决为"
                "接受为已知限制（关闭 S1 设计宣称并登记，负例冻结口径与评分层不受影响）。"
                "签认记录 signoff-record-m6.{md,json}（r30 先例：具名签认入链）。"
            ),
            "rebind_scope": (
                "仅重绑 docs/plan/corpus-ingestion-rebuild-tasks.md（3e2413be…→" + h_tasks[:8]
                + "…）、验证器自哈希（1e1b63ec…→" + h_validator[:8] + "…）与新增 M6 复核/签认"
                "证据六件（review + 三探针产物 + 签认记录两件）；i3-final-freeze-manifest.json 与 "
                "I3-7 证据五件沿用先前绑定不重复；不借机触碰实现/测试/守卫/金标字节。"
            ),
        },
        "notes": [
            "r5c 为 M6 放行入链修订（parent=i0c-r5b）：不触碰 i0c-r5b 及更早快照的已冻结字节"
            "（追加式索引纪律）。",
            "archive-first：before-r5c/ 保存改前字节——tasks.md 取自**当前盘面**"
            "（sha256 == i0c-r5b chain_rebind_evidence 绑定 3e2413be…；工作区未 commit，"
            "禁用 git show HEAD 模式），validator 取自改块前盘面字节"
            "（sha256 == i0c-r5b freeze_validator 绑定 1e1b63ec…）。",
            "M6 放行三要件：I3-7 通过 + 独立复核通过 + U（xyl）具名签认——本修订后全部达成；"
            "M6 后变更须按 I4 前置纪律另立版本冻结与授权。",
        ],
        "m5_declaration": "not_declared",
    }

    if args.no_write:
        print("[--no-write] 预览完成，未写盘")
        print(json.dumps(snapshot, ensure_ascii=False, indent=1)[:900])
        return 0

    snap_path = FREEZES / f"{NEW_ID}.json"
    snap_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=1) + "\n",
                         encoding="utf-8")
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
    MANIFEST_LIST.write_text(json.dumps(fl, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
