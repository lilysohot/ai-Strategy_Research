"""把 I3-0 阶段签认写进记录 → 收口脚本入链 → 冻结 i0c-r33 → 复跑冻结链门。

先例：M5（m5_review_signoff_freeze.py）与 I3-2（sign_and_freeze_r30.py）。顺序（重要）：
1. 归档**改动前**字节（validator / 两份台账）并与上一修订绑定比对（archive-first，先改后归档即失败）；
2. 给验证器加 r33 规则；写 r33 + 索引 + 台账回填；
3. 跑冻结链门（validate_i0c_freeze.py），exit 0 即收口完成。

用法::

    env -u PYTHONPATH uv run python \
        .scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260918-i30-review/sign_and_freeze_r33.py
"""

from __future__ import annotations

import ast
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1]
ROOT = HERE.parents[4]
FREEZES = BASE / "freezes"
VALIDATOR = FREEZES / "validate_i0c_freeze.py"
MANIFEST = FREEZES / "freeze-manifest.json"
R33 = FREEZES / "i0c-r33.json"
BEFORE = HERE / "before-r33"
SIGNOFF_JSON = HERE / "signoff-record-i3-0.json"
SIGNOFF_MD = HERE / "signoff-record-i3-0.md"
REVIEW_MD = HERE / "review.md"
PROBES = HERE / "test_review_probes.py"
RUN_REVIEW = HERE / "run_review.py"
TASKS = ROOT / "docs/plan/corpus-ingestion-rebuild-tasks.md"
PLAN = ROOT / "docs/plan/claims-market-closed-loop-plan.md"
BASE_REL = ".scratch/corpus-evidence-pipeline/ingestion-rebuild"
AUDIT_REL = f"{BASE_REL}/audits/20260918-i30-review"
SIGNER = "xyl"
SIGNED_AT = "2026-09-19T09:30:00+08:00"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def revision_order(path: Path) -> tuple[int, str]:
    stem = path.stem
    try:
        return (int(stem.rsplit("-r", 1)[1]), stem)
    except (IndexError, ValueError):
        return (-1, stem)


def merged_binding(exclude: tuple[str, ...] = ("i0c-r33",)) -> dict[str, str]:
    current: dict[str, str] = {}
    for path in sorted(FREEZES.glob("i0c-r*.json"), key=revision_order) + sorted(
        FREEZES.glob("i1-*.json"), key=revision_order
    ):
        if path.stem in exclude:
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        for items in (data.get("binding") or {}).values():
            for key, value in items.items():
                current.pop(key, None)
                current[key] = value
    return current


def archive(relative: str) -> dict:
    target = BEFORE / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.is_file():
        shutil.copy2(ROOT / relative, target)
    expected = merged_binding().get(relative)
    return {
        "path": relative,
        "archived_as": rel(target),
        "sha256": digest(target),
        "matches_previous_binding": expected is None or expected == digest(target),
    }


def must_replace(text: str, old: str, new: str) -> str:
    assert text.count(old) == 1, f"锚点不唯一或缺失：{old[:40]!r}"
    return text.replace(old, new, 1)


R33_BLOCK = '''
if "i0c-r33" in by_id:
    i0c33 = load_json(BASE / by_id["i0c-r33"].get("file", ""))
    parent = i0c33.get("parent_snapshot", {})
    expected_parent = BASE / by_id["i0c-r32"]["file"]
    check(parent.get("snapshot_id") == "i0c-r32", "r33 parent must be r32")
    check(parent.get("path") == str(expected_parent.relative_to(ROOT)), "r33 parent path mismatch")
    check(parent.get("sha256") == digest(expected_parent), "r33 parent bytes mismatch")
    binding33 = i0c33.get("binding", {})
    corrections = i0c33.get("corrections", {})
    for finding in ("I3-0_signoff", "I3-0_review_evidence_bound", "I3-0_not_covered", "I3-5"):
        check(finding in corrections, f"r33 missing correction {finding}")
    base = ".scratch/corpus-evidence-pipeline/ingestion-rebuild"
    audit = f"{base}/audits/20260918-i30-review"
    allowed = {
        "i3_0_signoff": {f"{audit}/signoff-record-i3-0.json",
                         f"{audit}/signoff-record-i3-0.md",
                         f"{audit}/sign_and_freeze_r33.py"},
        "i3_0_review": {f"{audit}/review.md",
                        f"{audit}/test_review_probes.py",
                        f"{audit}/run_review.py"},
        "docs": {"docs/plan/corpus-ingestion-rebuild-tasks.md",
                 "docs/plan/claims-market-closed-loop-plan.md"},
        "freeze_validator": {f"{base}/freezes/validate_i0c_freeze.py"},
    }
    check(set(binding33) == set(allowed) | {"i3_0_archive"}, "r33 binding groups mismatch")
    for group, expected in allowed.items():
        check(set(binding33.get(group, {})) == expected, f"r33 unexpected {group} scope")
    prev33 = merged_binding_from_all_but("i0c-r33")
    check(bool(binding33.get("i3_0_archive")), "r33 必须归档本修订覆盖的绑定文件（archive-first）")
    for key, sha in binding33.get("i3_0_archive", {}).items():
        original = next((p for p in prev33 if key.endswith(p)), None)
        check(original is not None, f"r33 归档路径无法对应到上一绑定：{key}")
        if original is not None:
            check(prev33[original] == sha, f"r33 归档不是真实 pre-r33 字节：{original}")
    signoff = load_json(ROOT / f"{audit}/signoff-record-i3-0.json")
    fields = signoff.get("signature_fields") or {}
    check(signoff.get("status") == "signed", "r33 签认记录状态必须为 signed")
    check(bool(fields.get("reviewer")) and bool(fields.get("decision")),
          "r33 签认必须具名（reviewer/decision 非空）")
    for group, items in binding33.items():
        for rel_ in items:
            check(not rel_.startswith(("plugins/", "tests/", "guards/")), f"r33 越界绑定 {rel_}")
    merge_binding(i0c_current_binding, binding33)

'''


def patch_validator() -> dict:
    text = VALIDATOR.read_text(encoding="utf-8")
    if 'if "i0c-r33" in by_id:' in text:
        return {"already_patched": True}
    marker = 'check("i0c-r32" in by_id, "索引缺少 i0c-r32 条目")'
    text = must_replace(text, marker, marker + '\ncheck("i0c-r33" in by_id, "索引缺少 i0c-r33 条目")')
    anchor = "# 最新修订绑定优先（supersession）：i0c-r2..r32 显式重绑的路径改由合并后的"
    text = must_replace(text, anchor, R33_BLOCK + anchor.replace("..r32", "..r33"))
    tail = 'if "i0c-r32" in by_id else ""))'
    text = must_replace(
        text,
        tail,
        'if "i0c-r32" in by_id else "") + ("; r33 I3-0 independent-review F1-F5 remediation '
        'sign-off (named) verified" if "i0c-r33" in by_id else ""))',
    )
    ast.parse(text)
    VALIDATOR.write_text(text, encoding="utf-8")
    return {"already_patched": False, "sha256": digest(VALIDATOR)}


def patch_docs() -> list[str]:
    tasks = TASKS.read_text(encoding="utf-8")
    plan = PLAN.read_text(encoding="utf-8")
    if "I3-0 阶段签认（r33" in tasks:
        return ["already_patched"]
    anchor = "**I3-2 Step 5 针对性复核与整改（r29，2026-09-19）**"
    block = (
        "**I3-0 阶段签认（r33，2026-09-19）**：具名审核人 **xyl** 确认"
        "[I3-0 阶段签认记录](../../.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260918-i30-review/signoff-record-i3-0.md)\n"
        "（复核结论：通过；签认 4 项 claim，明确 6 项不含）。冻结修订 **i0c-r33**（parent=r32）：\n"
        "绑定签认记录 + 收口脚本 + 复核报告/独立探针/复跑入口（证据面与裁决面同一）+ 两份台账；\n"
        "I3-0 独立复核 F1—F5 以修复不变量方式闭环（探针 10/10、自身 46 passed，评分器字节 r21）。\n\n"
    )
    tasks = must_replace(tasks, anchor, block + anchor)
    tasks = must_replace(
        tasks,
        "待复核确认闭环 + U 签认\n[I3-0 评分器交付]",
        "已复核确认闭环并经 U 签认（i0c-r33）\n[I3-0 评分器交付]",
    )
    old_plan = "**r32 优先状态（2026-09-19，I3-1 首次入链）**"
    new_plan = (
        "**r33 优先状态（2026-09-19，I3-0 阶段签认）**：具名审核人 xyl 已签认 I3-0 阶段（F1—F5 整改闭环，\n"
        "探针 10/10、自身 46 passed）；冻结 **i0c-r33**（parent=r32）：签认记录 + 收口脚本 + 复核证据 + 台账。\n"
        "I3-1/I3-5/I3-7 状态不变（见下）。\n\n"
        "**r32 历史状态（I3-1 首次入链）**"
    )
    plan = must_replace(plan, old_plan, new_plan)
    plan = must_replace(
        plan,
        "**待复核确认闭环 + U 签认**",
        "**已复核确认闭环并经 U 签认（i0c-r33）**",
    )
    TASKS.write_text(tasks, encoding="utf-8")
    PLAN.write_text(plan, encoding="utf-8")
    return ["tasks", "plan"]


def build_r33(archived: list[dict]) -> dict:
    return {
        "snapshot_id": "i0c-r33",
        "revision": "r33",
        "phase": "i0c",
        "task": (
            "I3-0 stage sign-off: independent-review F1-F5 remediation closure signed by named human; "
            "review evidence face (report/probes/replay entry) bound so the ruling and its evidence share bytes"
        ),
        "parent_snapshot": {
            "snapshot_id": "i0c-r32",
            "path": rel(FREEZES / "i0c-r32.json"),
            "sha256": digest(FREEZES / "i0c-r32.json"),
        },
        "binding": {
            "i3_0_signoff": {
                f"{AUDIT_REL}/signoff-record-i3-0.json": digest(SIGNOFF_JSON),
                f"{AUDIT_REL}/signoff-record-i3-0.md": digest(SIGNOFF_MD),
                f"{AUDIT_REL}/sign_and_freeze_r33.py": digest(HERE / "sign_and_freeze_r33.py"),
            },
            "i3_0_review": {
                f"{AUDIT_REL}/review.md": digest(REVIEW_MD),
                f"{AUDIT_REL}/test_review_probes.py": digest(PROBES),
                f"{AUDIT_REL}/run_review.py": digest(RUN_REVIEW),
            },
            "i3_0_archive": {item["archived_as"]: item["sha256"] for item in archived},
            "docs": {rel(TASKS): digest(TASKS), rel(PLAN): digest(PLAN)},
            "freeze_validator": {rel(VALIDATOR): digest(VALIDATOR)},
        },
        "corrections": {
            "I3-0_signoff": (
                f"具名审核人 {SIGNER} 于 {SIGNED_AT} 确认 I3-0 阶段签认：独立复核 F1—F5 以修复不变量"
                "方式闭环（探针 10/10、自身 46 passed）；签认 4 项 claim、明确 6 项不含"
            ),
            "I3-0_review_evidence_bound": (
                "绑定复核报告 review.md、独立反例 test_review_probes.py（原文件未改）与复跑入口 run_review.py，"
                "使 I3-0 裁决的字节面与证据面同一（同 M5 先例）"
            ),
            "I3-0_not_covered": (
                "I3-1（r32 单独入链，判定未完成）、I3-2 阶段（r30 签认）、I3-5 真实非回归、I3-7 语义验收、"
                "M5 F3 均不在本签认范围；本签认不代表 I4 放行"
            ),
            "I3-5": "真实非回归与 I3-1/I3-7 仍未执行，需环境与预算授权；本修订不改变该状态",
            "r32_archive_check_time_dependence_fix": (
                "机制修正（同 r32 自身『机制缺陷修正』先例）：r32 块的 prev32 原合并『除 r32 外的全部快照』，"
                "r33 重绑 docs/validator 三路径后该检查会随后续修订变化而失真；改为仅合并 r31 及更早"
                "（revision_order >= 32 一律跳过），r32 归档忠实性断言自此对后续修订稳定"
            ),
        },
        "created_at": datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
        "notes": [
            "零模型、零数据库写入；本修订只写签认记录、收口脚本与台账，未触碰评分器/金标/守卫/审批原件。",
            "评分器与测试字节仍是 r21 绑定（本轮不重绑 plugins/ 或 tests/）；验证器 r33 块强制该不变量。",
        ],
    }


def main() -> int:
    archived = [
        archive(f"{BASE_REL}/freezes/validate_i0c_freeze.py"),
        archive("docs/plan/corpus-ingestion-rebuild-tasks.md"),
        archive("docs/plan/claims-market-closed-loop-plan.md"),
    ]
    bad = [item["path"] for item in archived if not item["matches_previous_binding"]]
    if bad:
        print(f"I0C-R33 FREEZE FAILED: 归档与上一修订绑定不符（先改后归档？）：{bad}")
        return 1
    validator = patch_validator()
    docs = patch_docs()
    r33 = build_r33(archived)
    R33.write_text(json.dumps(r33, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    manifest["snapshots"] = [s for s in manifest["snapshots"] if s.get("snapshot_id") != "i0c-r33"] + [
        {"snapshot_id": "i0c-r33", "file": "i0c-r33.json", "sha256": digest(R33),
         "parent_snapshot_id": "i0c-r32", "created_at": r33["created_at"]}
    ]
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    proc = subprocess.run([sys.executable, str(VALIDATOR)], capture_output=True, text=True,
                          cwd=str(ROOT), check=False)
    print(json.dumps({
        "archived": [{"file": item["archived_as"].split("/")[-1],
                      "matches_previous_binding": item["matches_previous_binding"]} for item in archived],
        "validator": validator, "docs": docs, "r33_sha256": digest(R33),
        "chain_exit": proc.returncode,
        "chain_tail": (proc.stdout or "").strip().splitlines()[-1:],
    }, ensure_ascii=False, indent=2))
    return 0 if proc.returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
