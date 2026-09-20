"""冻结 i0c-r35（M6 判据补齐 §12.1 格式门；纯文档修订）→ 复跑冻结链门。

背景（U 2026-09-20 指令）：`tasks.md` 的 M6 判据行原无「格式」字样，而架构 §12.1 与 I3-7 行都含格式规则 →
完成口径不一致；本轮把 §12.1 格式门显式写入 M6 判据。**只改判据文字：不新增/关闭任何门、代码零改动。**

顺序（先例 r33 / r34）：
1. **先归档**：本修订覆盖 2 条绑定路径（tasks.md、plan.md），其 **pre-r35 字节**由本脚本按「编辑逆向」精确
   还原，并逐条断言 sha256 == 在效的上一修订绑定（任一不符即中止，不留假归档）；
2. 给验证器加 r35 规则（可重入，锚点一律锚定顶层）；写 r35 + 索引；
3. 跑冻结链门 → 日志落 `freeze-validation.txt` → **重绑日志后复跑**，两次输出必须逐字节一致。

用法::

    # 只读干跑（还原 + 归档忠实性 + 验证器补丁锚点/幂等/语法，不写任何文件）
    env -u PYTHONPATH uv run python <本文件> --no-write

    # 正式冻结
    env -u PYTHONPATH uv run python <本文件>
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
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
R35 = FREEZES / "i0c-r35.json"
BEFORE = HERE / "before-r35"
CONSISTENCY = HERE / "m6-criterion-consistency.txt"
CHAIN_LOG = HERE / "freeze-validation.txt"
SELF = HERE / "freeze_r35.py"
BASE_REL = ".scratch/corpus-evidence-pipeline/ingestion-rebuild"
AUDIT_REL = f"{BASE_REL}/audits/20260920-m6-format-criterion"
REL_VALIDATOR = f"{BASE_REL}/freezes/validate_i0c_freeze.py"

TASKS_REL = "docs/plan/corpus-ingestion-rebuild-tasks.md"
PLAN_REL = "docs/plan/claims-market-closed-loop-plan.md"

# --- 编辑逆向（new → old）：把当前字节还原为 pre-r35 字节 -----------------------

M6_OLD = "宏观 0/3 单列；缺资产/必需环境不通过"
M6_NEW = (
    "宏观 0/3 单列；**声称支持的格式（PDF/DOCX/MD）按架构 §12.1 各有真实已用开发样本、"
    "无未处置缺格（dev lane 样本计入但须标注 `dev_lane`）**；缺资产/必需环境不通过"
)

NAV_OLD = (
    "| I3-1 第二轮 dev lane | [U 裁决 dev lane 纳入 MD/DOCX（8 份 → 可发布 4/8、**§12.1 格式门 true**、"
    "`每类≥2` 仍 false）；生产判定不变由 dev lane 反例族 + 预检 fail-closed 反例双证；i0c-r34 入链]"
    "(claims-market-closed-loop-plan.md#i3-1-dev-lane) |"
)
NAV_NEW = (
    NAV_OLD
    + "\n| M6 判据补齐格式门 | [U 指令：把架构 §12.1 格式门显式写入 M6 判据（与 I3-7 行、§12.1 口径对齐）；"
    "只改判据文字，门行为与代码零改动、不新增阻塞；i0c-r35 入链](claims-market-closed-loop-plan.md#m6-format-criterion) |"
)

PLAN_ANCHOR = '<a id="i3-1-dev-lane"></a>'
PLAN_INSERT = """<a id="m6-format-criterion"></a>

### 2026-09-20 M6 判据补齐格式门（i0c-r35 入链）

**U 指令（2026-09-20）**：`tasks.md` 的 M6 判据行原无“格式”字样，而架构 §12.1 与 I3-7 行都有格式规则 →
完成口径不一致；现把 §12.1 格式门**显式写入 M6 判据**。**只改判据文字，不改门的行为、不新增阻塞**：
格式门的实际执行仍是 §12.1「格式可得性对账」（`dev-manifest.json` 的 `format_availability` + 取样前
`preflight_scope_check.py` 核对），规则一字未改。

**改动内容**：`tasks.md` M6 行追加“**声称支持的格式（PDF/DOCX/MD）按架构 §12.1 各有真实已用开发样本、
无未处置缺格（dev lane 样本计入但须标注 `dev_lane`）**”，与 §12.1「缺格式样本则该格式真实门未通过，
不能静默缩范围」、I3-7 行「分母/格式/必需环境缺失不通过」三处对齐；`tasks.md` 导航表补一行。

**影响**：I3-1 的 §12.1 格式门已于 i0c-r34 为 true（pdf 2/6、docx 1/1、md 1/1），故本改动**不新增阻塞**，
只消除“格式门算不算完成条件”的歧义；裁定①（阻断缺口处置路径）、company 0/2 与
I3-3/I3-4/I3-5/I3-6/I3-7 状态**不变**。

**r35 入链**：仅两条文档路径（`tasks.md`、本台账）按 `archive_first()` 归档后重绑，**代码零改动**；
三门复跑（冻结链 / I3-2 完成门 / 语料族）全绿后收口。

"""

REVERSES: list[tuple[str, str, str]] = [
    (TASKS_REL, M6_NEW, M6_OLD),
    (TASKS_REL, NAV_NEW, NAV_OLD),
    (PLAN_REL, PLAN_INSERT + PLAN_ANCHOR, PLAN_ANCHOR),
]

# --- 验证器 r35 规则块（可重入；只断言，不改门的行为） -------------------------

R35_BLOCK = '''
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

'''

INDEX_ANCHOR = 'check("i0c-r34" in by_id, "索引缺少 i0c-r34 条目")'
SUPERSEDE_TUPLE = '"i0c-r33", "i0c-r34"):'
SUPERSEDE_COMMENT = "# 最新修订绑定优先（supersession）：i0c-r2..r34 显式重绑的路径改由合并后的"
SUMMARY_TAIL = 'unchanged (dev-only policy + truthful material types)" if "i0c-r34" in by_id else ""))'
SUMMARY_R35 = (
    'unchanged (dev-only policy + truthful material types)" if "i0c-r34" in by_id else "")'
    ' + ("; r35 M6 criterion carries the §12.1 format gate (docs-only: tasks.md M6 row + plan ledger; '
    'no behaviour change)" if "i0c-r35" in by_id else ""))'
)


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


def merged_binding(exclude: tuple[str, ...] = ()) -> dict[str, str]:
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


def merged_binding_upto_revision(max_revision: int) -> dict[str, str]:
    """只合并**修订号 <= max_revision** 的 i0c 绑定（时间稳定，不被后续修订重绑污染）。"""

    current: dict[str, str] = {}
    for path in sorted(FREEZES.glob("i0c-r*.json"), key=revision_order):
        if revision_order(path)[0] > max_revision:
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        for items in (data.get("binding") or {}).values():
            for key, value in items.items():
                current.pop(key, None)
                current[key] = value
    return current


def previous_effective_binding() -> dict[str, str]:
    """在效的「上一修订绑定」= i0c ≤34 合并值优先，缺失路径回落全量合并。"""

    effective = merged_binding_upto_revision(34)
    for key, value in merged_binding(exclude=("i0c-r35",)).items():
        effective.setdefault(key, value)
    return effective


def must_replace(text: str, old: str, new: str) -> str:
    count = text.count(old)
    assert count == 1, f"锚点不唯一或缺失：{old[:60]!r}（命中 {count} 次）"
    return text.replace(old, new, 1)


def reconstruct() -> dict[str, bytes]:
    """产出每条被覆盖绑定路径的 pre-r35 字节（由「编辑逆向」精确还原）。"""

    originals: dict[str, bytes] = {}
    grouped: dict[str, list[tuple[str, str]]] = {}
    for path, new, old in REVERSES:
        grouped.setdefault(path, []).append((new, old))
    for relative, ops in grouped.items():
        text = (ROOT / relative).read_text(encoding="utf-8")
        for new, old in ops:
            count = text.count(new)
            assert count == 1, f"{relative} 逆向锚点命中 {count} 次：{new[:60]!r}"
            text = text.replace(new, old, 1)
        if not text.endswith("\n"):
            text += "\n"
        originals[relative] = text.encode("utf-8")
    return originals


def archive(originals: dict[str, bytes], previous: dict[str, str]) -> list[dict]:
    records: list[dict] = []
    for relative, payload in originals.items():
        target = BEFORE / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        actual = hashlib.sha256(payload).hexdigest()
        expected = previous.get(relative)
        records.append(
            {
                "path": relative,
                "archived_as": str(target.relative_to(ROOT)),
                "sha256": actual,
                "matches_previous_binding": expected is not None and expected == actual,
                "previous_binding": expected,
            }
        )
    return records


def patch_text(text: str) -> str:
    """返回打了 r35 补丁的验证器源码（纯函数；可重入，锚点锚定顶层）。"""

    if '\nif "i0c-r35" in by_id:' in text:
        start = text.index('\nif "i0c-r35" in by_id:') + 1
        end = text.index("# 最新修订绑定优先（supersession）", start)
        body = R35_BLOCK[1:]  # 去首换行：文件中该块前的换行由前一段落提供
        if text[start:end] == body:
            return text
        return text[:start] + body + text[end:]
    text = must_replace(
        text, INDEX_ANCHOR, INDEX_ANCHOR + '\ncheck("i0c-r35" in by_id, "索引缺少 i0c-r35 条目")'
    )
    text = must_replace(text, SUPERSEDE_TUPLE, '"i0c-r33", "i0c-r34", "i0c-r35"):')
    text = must_replace(text, SUPERSEDE_COMMENT, R35_BLOCK + SUPERSEDE_COMMENT.replace("..r34", "..r35"))
    text = must_replace(text, SUMMARY_TAIL, SUMMARY_R35)
    return text


def patch_validator() -> dict:
    text = VALIDATOR.read_text(encoding="utf-8")
    patched = patch_text(text)
    ast.parse(patched)
    if patched == text:
        return {"already_patched": True, "sha256": digest(VALIDATOR)}
    VALIDATOR.write_text(patched, encoding="utf-8")
    return {"updated": True, "sha256": hashlib.sha256(patched.encode("utf-8")).hexdigest()}


def run_validator() -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, str(VALIDATOR)], capture_output=True, text=True, cwd=str(ROOT), check=False
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def write_manifest() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    created_at = json.loads(R35.read_text(encoding="utf-8"))["created_at"]
    manifest["snapshots"] = [s for s in manifest["snapshots"] if s.get("snapshot_id") != "i0c-r35"] + [
        {
            "snapshot_id": "i0c-r35",
            "file": "i0c-r35.json",
            "sha256": digest(R35),
            "parent_snapshot_id": "i0c-r34",
            "created_at": created_at,
        }
    ]
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_r35(archived: list[dict], *, with_chain_log: bool) -> dict:
    evidence = {
        f"{AUDIT_REL}/verify_m6_criterion.py": digest(HERE / "verify_m6_criterion.py"),
        f"{AUDIT_REL}/m6-criterion-consistency.txt": digest(CONSISTENCY),
        f"{AUDIT_REL}/freeze_r35.py": digest(SELF),
    }
    if with_chain_log:
        evidence[f"{AUDIT_REL}/freeze-validation.txt"] = digest(CHAIN_LOG)
    created_at = (
        json.loads(R35.read_text(encoding="utf-8")).get("created_at")
        if R35.is_file()
        else datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")
    )
    return {
        "snapshot_id": "i0c-r35",
        "revision": "r35",
        "phase": "i0c",
        "task": (
            "M6 completion criterion now carries the §12.1 format gate (U instruction 2026-09-20): "
            "criterion wording only — no gate behaviour change, no code change"
        ),
        "parent_snapshot": {
            "snapshot_id": "i0c-r34",
            "path": rel(FREEZES / "i0c-r34.json"),
            "sha256": digest(FREEZES / "i0c-r34.json"),
        },
        "binding": {
            "m6_criterion_docs": {
                TASKS_REL: digest(ROOT / TASKS_REL),
                PLAN_REL: digest(ROOT / PLAN_REL),
            },
            "m6_criterion_evidence": evidence,
            "m6_criterion_archive": {item["archived_as"]: item["sha256"] for item in archived},
            "freeze_validator": {REL_VALIDATOR: digest(VALIDATOR)},
        },
        "corrections": {
            "M6_format_gate_in_criterion": (
                "M6 判据行追加「声称支持的格式（PDF/DOCX/MD）按架构 §12.1 各有真实已用开发样本、"
                "无未处置缺格（dev lane 样本计入但须标注 dev_lane）」——格式门自本修订起是 M6 的完成判据之一"
            ),
            "M6_criterion_alignment": (
                "三处口径对齐：M6 判据行 ↔ 架构 §12.1「缺格式样本则该格式真实门未通过，不能静默缩范围」"
                "↔ I3-7 行「分母/格式/必需环境缺失不通过」；此前 M6 行独缺「格式」字样"
            ),
            "M6_no_behavior_change": (
                "只改判据文字：格式门的执行仍在 §12.1 格式可得性对账（dev-manifest.format_availability）"
                "+ 取样前 preflight_scope_check.py 核对，门的行为与阈值一字未改；I3-1 格式门已于 r34 为 true，"
                "故本修订不新增阻塞（裁定①/company 0/2 状态不变）"
            ),
            "M6_no_code_change": (
                "纯文档修订：绑定范围内不得出现 plugins/ tests/ guards/ frontier_agent/ workflows/ 路径，"
                "由验证器 r35 块的越界绑定检查强制"
            ),
            "M6_archive_discipline": (
                "归档忠实性：本修订覆盖 2 条绑定路径（tasks.md、plan.md），其 pre-r35 字节由生成器按"
                "「编辑逆向」还原，逐条断言等于 i0c ≤34 的在效上一绑定（取值口径见 r34 教训：只在 i0c 链上"
                "绑定的路径必须取 i0c ≤34 合并值，不得被 i1-* 的陈旧值覆盖）"
            ),
        },
        "created_at": created_at,
        "notes": [
            "零代码改动、零模型、零 PG 写入；仅 tasks.md M6 判据行与导航表 + 台账回填两条文档路径。",
            "改动前字节由生成器按编辑逆向还原，并逐条与在效上一修订绑定核对 sha256。",
            "冻结链门日志在重绑日志后复跑产生，两次输出逐字节一致（日志即当前链门输出）。",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="冻结 i0c-r35（M6 判据格式门，纯文档修订）")
    parser.add_argument("--no-write", action="store_true", help="只读干跑：还原/归档核对/补丁锚点，不写文件")
    args = parser.parse_args()

    previous = previous_effective_binding()
    originals = reconstruct()

    if args.no_write:
        mismatches = [
            {"path": rel_, "reconstructed": sha, "previous_binding": previous.get(rel_)}
            for rel_, payload in originals.items()
            if (sha := hashlib.sha256(payload).hexdigest()) != previous.get(rel_)
        ]
        fresh = patch_text(VALIDATOR.read_text(encoding="utf-8"))
        ast.parse(fresh)
        idempotent = patch_text(fresh) == fresh
        print(
            json.dumps(
                {
                    "mode": "no-write",
                    "reconstructed_paths": sorted(originals),
                    "archive_faithfulness": "OK" if not mismatches else "MISMATCH",
                    "mismatches": mismatches,
                    "validator_patch": {
                        "syntax_ok": True,
                        "idempotent": idempotent,
                        "changes_file": fresh != VALIDATOR.read_text(encoding="utf-8"),
                    },
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if (not mismatches and idempotent) else 1

    archived = archive(originals, previous)
    bad = [item for item in archived if not item["matches_previous_binding"]]
    if bad:
        print("I0C-R35 FREEZE FAILED: 归档与上一修订绑定不符：")
        for item in bad:
            print(
                f"  {item['path']}\n    archived={item['sha256']}\n    binding ={item['previous_binding']}"
            )
        return 1
    if not CONSISTENCY.is_file():
        print(f"I0C-R35 FREEZE FAILED: 缺少一致性校验日志 {CONSISTENCY}（须先跑 verify_m6_criterion.py）")
        return 1

    validator = patch_validator()

    r35 = build_r35(archived, with_chain_log=False)
    R35.write_text(json.dumps(r35, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_manifest()
    first_code, first_out = run_validator()
    if first_code != 0:
        print("I0C-R35 FREEZE FAILED: 首次链门非 0\n" + first_out)
        return 1
    CHAIN_LOG.write_text(first_out + "\nexit=0\n", encoding="utf-8")

    r35 = build_r35(archived, with_chain_log=True)
    R35.write_text(json.dumps(r35, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_manifest()
    second_code, second_out = run_validator()
    if second_code != 0:
        print("I0C-R35 FREEZE FAILED: 重绑后链门非 0\n" + second_out)
        return 1
    if second_out != first_out:
        print("I0C-R35 FREEZE FAILED: 重绑前后链门输出不一致（绑定的日志不是当前链门输出）")
        return 1
    print(
        json.dumps(
            {
                "archived": [
                    {
                        "path": item["path"],
                        "archived_as": item["archived_as"].split("audits/")[-1],
                        "match": item["matches_previous_binding"],
                    }
                    for item in archived
                ],
                "validator": validator,
                "r35_sha256": digest(R35),
                "chain_exit": second_code,
                "chain_tail": [line for line in second_out.strip().splitlines() if line][-1:],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
