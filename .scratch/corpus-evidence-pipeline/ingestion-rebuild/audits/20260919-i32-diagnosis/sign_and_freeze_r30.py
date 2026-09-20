"""Step 6：把 U 的阶段签认写进记录 → 生成器/脚本入链 → 冻结 i0c-r30 → 复跑三门。

顺序（重要）：
1. 归档**改动前**字节（validator / 完成门 / 两份台账）并与上一修订绑定哈希比对；
2. 给完成门加"阶段签认已具名且入链"判据；给验证器加 r30 规则；
3. 复核脚本加"已签记录不得被重写"守卫；写入 U 的签名；把本轮执行脚本从 /tmp 收入审计目录；
4. 写 r30 + 索引 + 台账回填；
5. 跑三门（冻结链 / 完成门 / 复核 --no-write）。
"""

from __future__ import annotations

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
GATE = FREEZES / "validate_i3_2_completion.py"
MANIFEST = FREEZES / "freeze-manifest.json"
R30 = FREEZES / "i0c-r30.json"
BEFORE = HERE / "before-r30"
REVIEW = HERE / "step5_review.py"
SIGNOFF_JSON = HERE / "signoff-record-i3-2.json"
SIGNOFF_MD = HERE / "signoff-record-i3-2.md"
STEP_ABC = HERE / "step-abc-record.md"
GENERATOR = BASE / "audits/20260918-i32-remaining-inventory/generate_p2_p3_p4.py"
TASKS = ROOT / "docs/plan/corpus-ingestion-rebuild-tasks.md"
PLAN = ROOT / "docs/plan/claims-market-closed-loop-plan.md"
BASE_REL = ".scratch/corpus-evidence-pipeline/ingestion-rebuild"
AUDIT_REL = f"{BASE_REL}/audits/20260919-i32-diagnosis"
SIGNER = "xyl"
SIGNED_AT = "2026-09-19T20:10:00+08:00"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def now() -> str:
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


def merged_binding(exclude: tuple[str, ...] = ("i0c-r30",)) -> dict[str, str]:
    current: dict[str, str] = {}
    for path in sorted(FREEZES.glob("i0c-r*.json")) + sorted(FREEZES.glob("i1-*.json")):
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
    previous = merged_binding()
    expected = previous.get(relative)
    return {
        "path": relative,
        "archived_as": rel(target),
        "sha256": digest(target),
        "matches_previous_binding": expected is None or expected == digest(target),
    }


# ── 2. 完成门加"阶段签认"判据


def patch_completion_gate() -> bool:
    text = GATE.read_text(encoding="utf-8")
    if "check_signoff" in text:
        return False
    text = text.replace('    check_assets_in_chain()', '    check_assets_in_chain()\n    check_signoff()', 1)
    text = text.replace('"artifact": "i3-2-completion-gate",', '"artifact": "i3-2-completion-gate",', 1)
    block = '''def check_signoff() -> None:
    """阶段签认：必须具名（reviewer/decision 非空）且记录已入链。"""

    if not SIGNOFF_JSON.is_file():
        record("阶段签认（具名 + 入链）", "fail", ["缺 signoff-record-i3-2.json"])
        return
    data = json.loads(SIGNOFF_JSON.read_text(encoding="utf-8"))
    fields = data.get("signature_fields") or {}
    named = bool(fields.get("reviewer")) and bool(fields.get("decision"))
    bound = merged_binding().get(str(SIGNOFF_JSON.relative_to(ROOT))) == digest(SIGNOFF_JSON)
    record(
        "阶段签认（具名 + 入链）",
        "pass" if named and bound else "fail",
        [
            f"status={data.get('status')!r}；reviewer={fields.get('reviewer')!r}；"
            f"decision={fields.get('decision')!r}；reviewed_at={fields.get('reviewed_at')!r}",
            f"记录入链={'是' if bound else '**否**'}",
        ],
    )


'''
    anchor = "def main() -> int:"
    text = text.replace(anchor, block + anchor, 1)
    GATE.write_text(text, encoding="utf-8")
    import ast

    ast.parse(text)
    return True


# ── 3a. 复核脚本：已签记录不得重写


def patch_review_guard() -> bool:
    text = REVIEW.read_text(encoding="utf-8")
    if "已签记录不重写" in text:
        return False
    old = '''    if not no_write:
        (HERE / "step5-review.json").write_text('''
    new = '''    # 已签记录不重写（防签名被覆盖）
    if SIGNOFF_JSON.is_file():
        signed = (json.loads(SIGNOFF_JSON.read_text(encoding="utf-8")).get("signature_fields") or {})
        if signed.get("reviewer") and signed.get("decision"):
            no_write = True
    if not no_write:
        (HERE / "step5-review.json").write_text('''
    assert old in text
    text = text.replace(old, new, 1)
    text = text.replace('SIGNOFF_JSON', 'SIGNOFF_JSON')  # noop
    if "SIGNOFF_JSON = " not in text:
        text = text.replace(
            "COMPLETION_GATE = FREEZES / \"validate_i3_2_completion.py\"",
            "COMPLETION_GATE = FREEZES / \"validate_i3_2_completion.py\"\n"
            "SIGNOFF_JSON = HERE / \"signoff-record-i3-2.json\"",
            1,
        )
    REVIEW.write_text(text, encoding="utf-8")
    import ast

    ast.parse(text)
    return True


# ── 3b. 写入签名


def sign() -> dict:
    data = json.loads(SIGNOFF_JSON.read_text(encoding="utf-8"))
    data["status"] = "signed"
    data["signature_fields"] = {
        "reviewer": SIGNER,
        "reviewed_at": SIGNED_AT,
        "decision": "批准（I3-2 阶段签认）",
        "note": (
            "具名审核人于 2026-09-19 会话中确认签认；签认范围与不含范围见本记录 claim/not_covered 两节。"
            "复核结论：通过（step5-review：17 项检查 0 fail / 1 观察项）。"
        ),
    }
    data["signed_in"] = "i0c-r30"
    SIGNOFF_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    md = SIGNOFF_MD.read_text(encoding="utf-8")
    md = md.replace("- 状态：**pending_user_signoff**", f"- 状态：**已签认（{SIGNER}，{SIGNED_AT}）**", 1)
    md = md.replace(
        "| reviewer | （待填） |", f"| reviewer | {SIGNER} |"
    ).replace(
        "| reviewed_at | （待填） |", f"| reviewed_at | {SIGNED_AT} |"
    ).replace(
        "| decision | （待填） |", "| decision | 批准（I3-2 阶段签认） |"
    ).replace(
        "| note | （待填） |",
        "| note | 具名审核人于 2026-09-19 会话确认；复核通过（0 fail / 1 观察项） |",
    )
    SIGNOFF_MD.write_text(md, encoding="utf-8")
    return data["signature_fields"]


# ── 3c. 把本轮执行脚本收入审计目录（可复现）


def collect_scripts() -> list[str]:
    moved = []
    for source in (
        Path("/tmp/freeze_r29.py"),
        Path("/tmp/rebuild_r29.py"),
        Path("/tmp/fix_r29_archive.py"),
        Path("/tmp/fix_paths_r29.py"),
        Path("/tmp/freeze_r28_probe.py"),
    ):
        if not source.is_file():
            continue
        target = HERE / source.name
        if source.name in {"freeze_r28_probe.py"}:
            continue
        shutil.copy2(source, target)
        moved.append(target.name)
    return moved


# ── 2b. 验证器 r30 规则

R30_BLOCK = '''
if "i0c-r30" in by_id:
    i0c30 = load_json(BASE / by_id["i0c-r30"].get("file", ""))
    parent = i0c30.get("parent_snapshot", {})
    expected_parent = BASE / by_id["i0c-r29"]["file"]
    check(parent.get("snapshot_id") == "i0c-r29", "r30 parent must be r29")
    check(parent.get("path") == str(expected_parent.relative_to(ROOT)), "r30 parent path mismatch")
    check(parent.get("sha256") == digest(expected_parent), "r30 parent bytes mismatch")
    binding30 = i0c30.get("binding", {})
    corrections = i0c30.get("corrections", {})
    for finding in ("I3-2_stage_signoff", "I3-2_generator_binding", "I3-2_review_no_write_guard", "I3-5"):
        check(finding in corrections, f"r30 missing correction {finding}")
    base = ".scratch/corpus-evidence-pipeline/ingestion-rebuild"
    audit = f"{base}/audits/20260919-i32-diagnosis"
    allowed = {
        "i3_2_signoff": {
            f"{audit}/signoff-record-i3-2.json",
            f"{audit}/signoff-record-i3-2.md",
            f"{audit}/sign_and_freeze_r30.py",
            f"{audit}/step-abc-record.md",
            f"{audit}/step5_review.py",
        },
        "i3_2_generators": {
            f"{base}/audits/20260918-i32-remaining-inventory/generate_p2_p3_p4.py",
            f"{audit}/freeze_r29.py",
            f"{audit}/rebuild_r29.py",
            f"{audit}/fix_r29_archive.py",
            f"{audit}/fix_paths_r29.py",
        },
        "docs": {"docs/plan/corpus-ingestion-rebuild-tasks.md",
                 "docs/plan/claims-market-closed-loop-plan.md"},
        "freeze_validator": {f"{base}/freezes/validate_i0c_freeze.py",
                             f"{base}/freezes/validate_i3_2_completion.py"},
    }
    check(set(binding30) == set(allowed) | {"i3_2_archive"}, "r30 binding groups mismatch")
    for group, expected in allowed.items():
        check(set(binding30.get(group, {})) == expected, f"r30 unexpected {group} scope")
    archive_keys = list(binding30.get("i3_2_archive", {}))
    for original in (f"{base}/freezes/validate_i0c_freeze.py",
                     f"{base}/freezes/validate_i3_2_completion.py",
                     "docs/plan/corpus-ingestion-rebuild-tasks.md",
                     "docs/plan/claims-market-closed-loop-plan.md"):
        matched = [key for key in archive_keys if key.endswith(original) and "before-r30" in key]
        check(len(matched) == 1, f"r30 missing archive for {original}")
    signoff = load_json(ROOT / f"{audit}/signoff-record-i3-2.json")
    fields = signoff.get("signature_fields") or {}
    check(signoff.get("status") == "signed", "r30 签认记录状态必须为 signed")
    check(bool(fields.get("reviewer")) and bool(fields.get("decision")),
          "r30 签认必须具名（reviewer/decision 非空）")
    for group, items in binding30.items():
        for rel_ in items:
            check(not rel_.startswith(("plugins/", "tests/", "guards/")), f"r30 越界绑定 {rel_}")
    merge_binding(i0c_current_binding, binding30)

'''


def patch_validator() -> dict:
    text = VALIDATOR.read_text(encoding="utf-8")
    if 'if "i0c-r30" in by_id:' in text:
        return {"already_patched": True}
    marker = 'check("i0c-r29" in by_id, "索引缺少 i0c-r29 条目")'
    assert marker in text
    text = text.replace(marker, marker + '\ncheck("i0c-r30" in by_id, "索引缺少 i0c-r30 条目")', 1)
    anchor = "# 最新修订绑定优先（supersession）：i0c-r2..r29 显式重绑的路径改由合并后的"
    assert anchor in text
    text = text.replace(anchor, R30_BLOCK + anchor.replace("..r29", "..r30"), 1)
    VALIDATOR.write_text(text, encoding="utf-8")
    return {"already_patched": False, "sha256": digest(VALIDATOR)}


def patch_docs() -> list[str]:
    tasks = TASKS.read_text(encoding="utf-8")
    plan = PLAN.read_text(encoding="utf-8")
    if "阶段签认（r30" in tasks:
        return ["already_patched"]
    anchor = "**I3-2 Step 5 针对性复核与整改（r29，2026-09-19）**"
    assert anchor in tasks
    block = (
        "**I3-2 阶段签认（r30，2026-09-19）**：具名审核人 **xyl** 于 2026-09-19 确认"
        "[阶段签认记录](../../.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i32-diagnosis/signoff-record-i3-2.md)\n"
        "（复核结论：通过，0 fail／1 观察项；签认 4 项 claim，明确 6 项不含）。冻结修订 **i0c-r30**（parent=r29）：\n"
        "绑定签认记录 + 复核脚本（含『已签记录不得重写』守卫）+ 执行记录 + **生成器入链**\n"
        "（`generate_p2_p3_p4.py` 与 r28/r29 冻结脚本，修正 r29 登记的『生成器不可追溯』缺陷）+ 两份台账；\n"
        "完成门新增判据：**阶段签认必须具名且记录已入链**。I3-5/I3-1 仍未执行；prose 留出（天风 5520fab6）\n"
        "是否纳入 `guards/i3.json` 待定。\n\n"
    )
    tasks = tasks.replace(anchor, block + anchor, 1)
    old_plan = "**r29 优先状态（2026-09-19，Step 5 复核整改）**"
    assert old_plan in plan
    new_plan = (
        "**r30 优先状态（2026-09-19，I3-2 阶段签认）**：具名审核人 xyl 已签认 I3-2 阶段（复核通过，0 fail／1 观察项）；\n"
        "冻结 **i0c-r30**（parent=r29）：签认记录 + 复核脚本（含防重写守卫）+ 执行记录 + 生成器入链 + 台账；\n"
        "完成门新增『签认须具名且入链』判据。I3-5/I3-1 未执行（需授权）；prose 留出纳入 guard 与否待定。\n\n"
        "**r29 历史状态（Step 5 复核整改）**"
    )
    plan = plan.replace(old_plan, new_plan, 1)
    TASKS.write_text(tasks, encoding="utf-8")
    PLAN.write_text(plan, encoding="utf-8")
    return ["tasks", "plan"]


def build_r30(archived: list[dict], scripts: list[str]) -> dict:
    return {
        "snapshot_id": "i0c-r30",
        "revision": "r30",
        "phase": "i0c",
        "task": (
            "I3-2 stage sign-off: named human sign-off recorded and bound; generators bound (fixing the "
            "r29 'generator not traceable' defect); completion gate now requires a named, in-chain sign-off"
        ),
        "parent_snapshot": {
            "snapshot_id": "i0c-r29",
            "path": rel(FREEZES / "i0c-r29.json"),
            "sha256": digest(FREEZES / "i0c-r29.json"),
        },
        "binding": {
            "i3_2_signoff": {
                f"{AUDIT_REL}/signoff-record-i3-2.json": digest(SIGNOFF_JSON),
                f"{AUDIT_REL}/signoff-record-i3-2.md": digest(SIGNOFF_MD),
                f"{AUDIT_REL}/sign_and_freeze_r30.py": digest(HERE / "sign_and_freeze_r30.py"),
                f"{AUDIT_REL}/step-abc-record.md": digest(STEP_ABC),
                f"{AUDIT_REL}/step5_review.py": digest(REVIEW),
            },
            "i3_2_generators": {
                f"{BASE_REL}/audits/20260918-i32-remaining-inventory/generate_p2_p3_p4.py": digest(GENERATOR),
                **{
                    f"{AUDIT_REL}/{name}": digest(HERE / name)
                    for name in ("freeze_r29.py", "rebuild_r29.py", "fix_r29_archive.py", "fix_paths_r29.py")
                    if (HERE / name).is_file()
                },
            },
            "i3_2_archive": {item["archived_as"]: item["sha256"] for item in archived},
            "docs": {rel(TASKS): digest(TASKS), rel(PLAN): digest(PLAN)},
            "freeze_validator": {rel(VALIDATOR): digest(VALIDATOR), rel(GATE): digest(GATE)},
        },
        "corrections": {
            "I3-2_stage_signoff": (
                f"具名审核人 {SIGNER} 于 {SIGNED_AT} 确认 I3-2 阶段签认（复核通过 0 fail／1 观察项；"
                "签认 4 项 claim、明确 6 项不含：I3-5/I3-1/I3-7、20 条同义 warning、19 题映射人工复核、"
                "prose 留出、M5 F3）"
            ),
            "I3-2_generator_binding": (
                "修正 r29 登记的『生成器不可追溯』：绑 generate_p2_p3_p4.py 与 r28/r29 冻结脚本，"
                "产物自此可由生成器 + 输入复现"
            ),
            "I3-2_review_no_write_guard": (
                "复核脚本加『已签记录不得重写』守卫（原先每次运行都会重写含时间戳的签认/复核产物，"
                "会在签认后破坏签名与已绑定字节）"
            ),
            "I3-5": "真实非回归与 I3-1 E2E 仍未执行，需环境与预算授权；本修订不改变该状态",
        },
        "created_at": datetime.now(timezone.utc).isoformat(),
        "notes": [
            "零模型、零数据库写入；本修订只写签认记录、脚本与台账，未触碰评分器/金标/守卫/审批原件。",
            "完成门新增判据后，I3-2 的完成判定包含『签认具名且入链』——避免未签认即宣告完成。",
        ],
    }


def main() -> int:
    archived = [
        archive(f"{BASE_REL}/freezes/validate_i0c_freeze.py"),
        archive(f"{BASE_REL}/freezes/validate_i3_2_completion.py"),
        archive("docs/plan/corpus-ingestion-rebuild-tasks.md"),
        archive("docs/plan/claims-market-closed-loop-plan.md"),
    ]
    gate_patched = patch_completion_gate()
    validator = patch_validator()
    review_guard = patch_review_guard()
    scripts = collect_scripts()
    signature = sign()
    docs = patch_docs()
    r30 = build_r30(archived, scripts)
    # 自绑定脚本需先落盘（sign_and_freeze_r30.py 已存在）
    R30.write_text(json.dumps(r30, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    manifest["snapshots"] = [s for s in manifest["snapshots"] if s.get("snapshot_id") != "i0c-r30"] + [
        {"snapshot_id": "i0c-r30", "file": "i0c-r30.json", "sha256": digest(R30),
         "parent_snapshot_id": "i0c-r29", "created_at": r30["created_at"]}
    ]
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def run(cmd: list[str]) -> dict:
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT), check=False)
        return {"exit": proc.returncode, "tail": (proc.stdout or "").strip().splitlines()[-1:]}

    chain = run([sys.executable, str(VALIDATOR)])
    gate = run([sys.executable, str(GATE)])
    review = run([sys.executable, str(REVIEW), "--no-write"])
    chain_after = run([sys.executable, str(VALIDATOR)])
    print(json.dumps({
        "archived": [{"file": item["archived_as"].split("/")[-1],
                      "matches_previous_binding": item["matches_previous_binding"]} for item in archived],
        "gate_patched": gate_patched, "validator": validator, "review_guard": review_guard,
        "scripts_collected": scripts, "signature": signature, "docs": docs,
        "r30_sha256": digest(R30),
        "chain": chain["exit"], "completion_gate": gate["exit"], "review": review["exit"],
        "chain_after_review": chain_after["exit"],
    }, ensure_ascii=False, indent=2))
    return 0 if chain["exit"] == 0 and gate["exit"] == 0 and chain_after["exit"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
