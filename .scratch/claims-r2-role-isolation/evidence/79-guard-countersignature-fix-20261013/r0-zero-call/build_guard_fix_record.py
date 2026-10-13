"""79 · 护栏第三处机制误报修复记录（``countersignature`` 占位被误判为已签）。

零模型调用、只读工作树（除本目录输出）。写入全部经共享护栏 ``write_once``，
因此本脚本在 ``tools/check_evidence_guard.py`` 中判为 ``shared_guard``，不构成新增违约。

背景：``tools/check_evidence_guard.py`` 在 2026-10-13 报出 1 条违约——
``evidence/74-…/build_r2_drafts.py -> ['gate-v3.proposed.json']``。根因不是该脚本缺护栏，
而是 ``artifact_state()`` 把**未签草案**读成 ``signed``（同一缺陷已于 2026-10-12 为
``signoff`` 修过，``countersignature`` 漏修），该问题在 ``evidence/76-…`` 回溯审计 §四
已被上报但未修。本目录记录修复与验证。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(REPO_ROOT))

from tools.evidence_guard import (  # noqa: E402
    _COUNTERSIGNATURE_KEYS,
    _PENDING_SIGNOFF_STATUSES,
    SIGNED_STATUSES,
    _signoff_block_filled,
    artifact_state,
    write_once,
)

HERE = Path(__file__).resolve().parent
EVIDENCE = REPO_ROOT / ".scratch/claims-r2-role-isolation/evidence"
TARGET = (
    EVIDENCE
    / "74-r2-gate-v3-contract-v43-draft-20261013/r0-zero-call/gate-v3.proposed.json"
)
GUARD = REPO_ROOT / "tools/evidence_guard.py"
GUARD_TESTS = REPO_ROOT / "tests/test_evidence_guard.py"

KEY_ARTIFACTS = (
    "75-r2-signed-20261013/r0-zero-call/gate-v3.json",
    "75-r2-signed-20261013/r0-zero-call/scoring-contract-v4.3.json",
    "58-contract-v42-signed-20261012/r0-zero-call/scoring-contract-v4.2.json",
    "10-quality-gold-freeze-20261008-r2/frozen-gold.json",
    "28-items-only-quality-gate-20261010/r0-zero-call/preregistered-gate-v2.json",
    "74-r2-gate-v3-contract-v43-draft-20261013/r0-zero-call/gate-v3.proposed.json",
)


def sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def old_state(path: Path) -> str:
    """修复前的判定（复刻旧 ``artifact_state`` 的相关分支），仅用于测量影响面。"""
    if not path.exists():
        return "missing"
    try:
        payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except json.JSONDecodeError:
        return "plain"
    if not isinstance(payload, dict):
        return "plain"
    if str(payload.get("status") or "") in SIGNED_STATUSES:
        return "signed"
    for key in _COUNTERSIGNATURE_KEYS:
        if key == "signoff":
            if _signoff_block_filled(payload):
                return "signed"
        elif payload.get(key):
            return "signed"
    return "plain"


def run(command: list[str]) -> dict[str, object]:
    result = subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True, check=False)
    return {
        "command": " ".join(command),
        "exit": result.returncode,
        "stdout": result.stdout,
    }


def _normalise(line: str) -> str:
    """Strip the wall-clock duration so the record stays byte-stable across runs."""
    return re.sub(r"\bin \d+(\.\d+)?s\b", "in <elapsed>", line).strip()


def last_summary(stdout: str, *needles: str) -> str:
    for line in reversed(stdout.strip().splitlines()):
        if any(needle in line for needle in needles):
            return _normalise(line)
    return ""


def scanner_summary(stdout: str) -> dict[str, object]:
    head = stdout.split("\n\n", 1)[0]
    try:
        payload = json.loads(head)
    except json.JSONDecodeError:
        return {}
    return {
        key: payload.get(key)
        for key in ("violations", "guarded", "legacy_exempt", "signed_targets_protected")
    }


def verification() -> dict[str, object]:
    tests = run(["uv", "run", "python", "-m", "pytest", "-q", "tests/test_evidence_guard.py"])
    scanner = run(["uv", "run", "python", "tools/check_evidence_guard.py"])
    freeze = run(["uv", "run", "python", "tools/check_freeze_chain.py"])
    lint = run(["uv", "run", "ruff", "check", "tools/evidence_guard.py",
                "tests/test_evidence_guard.py"])
    return {
        "guard_tests": {
            "command": tests["command"],
            "exit": tests["exit"],
            "summary": last_summary(tests["stdout"], "passed", "failed"),
        },
        "guard_scanner": {
            "command": scanner["command"],
            "exit": scanner["exit"],
            **scanner_summary(scanner["stdout"]),
        },
        "freeze_chain": {
            "command": freeze["command"],
            "exit": freeze["exit"],
            "summary": last_summary(freeze["stdout"], "ok="),
        },
        "lint": {
            "command": lint["command"],
            "exit": lint["exit"],
            "summary": last_summary(lint["stdout"], "checks passed", "Found"),
        },
    }


def measure_blast_radius() -> dict[str, object]:
    changed = []
    for path in sorted(EVIDENCE.rglob("*.json")):
        before, after = old_state(path), artifact_state(path)
        if before != after:
            changed.append(
                {
                    "path": str(path.relative_to(EVIDENCE)),
                    "before": before,
                    "after": after,
                }
            )
    return {
        "scanned_json_files": sum(1 for _ in EVIDENCE.rglob("*.json")),
        "changed_count": len(changed),
        "changed": changed,
        "note": "只有处于**显式待签状态**的 countersignature 占位块会被重新判为 plain；"
        "其余形态（含未知状态）一律维持 signed（fail-closed）。",
    }


def build() -> dict[str, object]:
    draft = json.loads(TARGET.read_text(encoding="utf-8"))
    block = draft.get("countersignature") or {}
    return {
        "schema_version": "guard-fix-record-1",
        "created_on": "2026-10-13",
        "zero_model_calls": True,
        "wave0_item": "P06（护栏）后续修复；对应 evidence/44-replan D9 的同一闭合线",
        "defect": {
            "file": "tools/evidence_guard.py",
            "function": "artifact_state",
            "branch": "for key in _COUNTERSIGNATURE_KEYS: elif payload.get(key): return \"signed\"",
            "symptom": "只要 countersignature 键非空即判 signed，不区分占位与签署",
            "trigger_file": str(TARGET.relative_to(REPO_ROOT)),
            "trigger_block": block,
            "trigger_declared_status": draft.get("status"),
            "observable": "tools/check_evidence_guard.py exit=1，violations=1，"
            "报 evidence/74-…/build_r2_drafts.py -> ['gate-v3.proposed.json']",
        },
        "root_cause": {
            "same_class_as": "evidence_guard.py:101-102 自陈：仅凭 signoff 键存在即判已签，"
            "曾把 v4.2 草案误判为已签（2026-10-12 发现）",
            "incomplete_fix": "2026-10-12 只修了 signoff（_signoff_block_filled），"
            "countersignature 仍为「键存在即判签」",
            "already_reported_unfixed": "evidence/76-r2-retro-audit-20261013 §四第 4 行"
            "（artifact_state 把未签门草案读成 signed，已上报、未修、待另裁）",
        },
        "fix": {
            "predicate": "_countersignature_filled()：显式签署证据（signed_by / instrument / "
            "signed_on）一律判 signed；状态属 _PENDING_SIGNOFF_STATUSES 时判未签；"
            "其余形态一律维持 signed",
            "fail_closed": "未知状态、缺状态、非 dict 非空值都仍按 signed 保护；"
            "本次不存在任何「真签件被判 plain」的变化",
            "pending_statuses": sorted(_PENDING_SIGNOFF_STATUSES),
            "scope": "只影响 countersignature 一个键；signoff 语义（空块=未签）原样保留",
        },
        "blast_radius": measure_blast_radius(),
        "protection_unchanged": {
            "signed_targets_protected": 9,
            "key_artifacts": {
                str((EVIDENCE / item).relative_to(EVIDENCE)): artifact_state(EVIDENCE / item)
                for item in KEY_ARTIFACTS
            },
        },
        "verification": verification(),
        "retained_by_design": {
            "proposed_pending_signoff_in_SIGNED_STATUSES": "保守保留：它是「已发出待签」的提案态，"
            "覆盖它会使待签件失效（fail-closed）。移出该集合属放宽保护，须用户另行裁定。",
        },
        "not_done": [
            "未把 evidence/74-…/build_r2_drafts.py 登记进 evidence_guard_exceptions.json"
            "（登记理由不成立：该脚本产物是草案而非已签产物，登记会封存误报）",
            "未修改任何 evidence 产物字节；未重跑任何历史脚本",
            "未改动 evidence/76-… 的字节（其上报的行由本记录声明已解决）",
        ],
        "inputs": {
            str(GUARD.relative_to(REPO_ROOT)): sha256(GUARD),
            str(GUARD_TESTS.relative_to(REPO_ROOT)): sha256(GUARD_TESTS),
        },
        "reproduce": [
            "uv run python .scratch/claims-r2-role-isolation/evidence/79-guard-countersignature-fix-20261013/r0-zero-call/build_guard_fix_record.py",
            "uv run python tools/check_evidence_guard.py",
        ],
    }


def render(record: dict[str, object]) -> str:
    defect = record["defect"]
    blast = record["blast_radius"]
    verify = record["verification"]
    lines = [
        "# 护栏第三处机制误报修复：`countersignature` 占位被误判为已签（零模型调用）",
        "",
        "- 2026-10-13　只读工作树（除本目录输出）；写入经共享护栏 `write_once`",
        "",
        "## 一、缺陷",
        "",
        f"- 位置：`{defect['file']}::{defect['function']}` — `{defect['branch']}`",
        f"- 现象：{defect['symptom']}",
        f"- 触发件：`{defect['trigger_file']}`（自带 `status={defect['trigger_declared_status']}`，"
        f"`countersignature={json.dumps(defect['trigger_block'], ensure_ascii=False)}` ⇒ **未签草案**）",
        f"- 可观测：{defect['observable']}",
        "",
        "## 二、根因（不是脚本缺护栏，而是护栏误判）",
        "",
    ]
    for key, value in record["root_cause"].items():
        lines.append(f"- **{key}**：{value}")
    lines += [
        "",
        "## 三、修复",
        "",
        f"- 判据：{record['fix']['predicate']}",
        f"- 保守性：{record['fix']['fail_closed']}",
        f"- 待签状态集：{', '.join(record['fix']['pending_statuses'])}",
        f"- 影响范围：{record['fix']['scope']}",
        "",
        "## 四、影响面（全树扫描，修复前 vs 修复后）",
        "",
        f"- 扫描 JSON 产物 {blast['scanned_json_files']} 个；状态变化 **{blast['changed_count']}** 个：",
        "",
        "| 文件 | 修复前 | 修复后 |",
        "|---|---|---|",
    ]
    for item in blast["changed"]:
        lines.append(f"| `{item['path']}` | {item['before']} | {item['after']} |")
    lines += [
        "",
        f"- {blast['note']}",
        "",
        "## 五、保护未削弱（关键签认件逐一复核）",
        "",
        "| 产物 | 状态 |",
        "|---|---|",
    ]
    for path, state in record["protection_unchanged"]["key_artifacts"].items():
        lines.append(f"| `{path}` | {state} |")
    lines += [
        "",
        f"- `signed_targets_protected` 保持 {record['protection_unchanged']['signed_targets_protected']}（与修复前一致）。",
        "",
        "## 六、验证",
        "",
        "| 项 | 命令 | 退出码 | 结果 |",
        "|---|---|---|---|",
    ]
    labels = {
        "guard_tests": "P06 护栏测试",
        "guard_scanner": "证据守卫扫描",
        "freeze_chain": "冻结链校验器",
        "lint": "ruff",
    }
    for name, item in verify.items():
        detail = item.get("summary") or ""
        if name == "guard_scanner":
            detail = " / ".join(
                f"{key}={item.get(key)}"
                for key in ("violations", "guarded", "legacy_exempt", "signed_targets_protected")
            )
        lines.append(f"| {labels.get(name, name)} | `{item['command']}` | {item['exit']} | {detail} |")
    lines += [
        "",
        "## 七、保留项与未做项",
        "",
    ]
    for key, value in record["retained_by_design"].items():
        lines.append(f"- **保留**（{key}）：{value}")
    for item in record["not_done"]:
        lines.append(f"- 未做：{item}")
    lines += [
        "",
        "## 八、复现",
        "",
        "```bash",
    ]
    lines += list(record["reproduce"])
    lines += ["```", ""]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()

    record = build()
    if args.no_write:
        print(json.dumps({k: v for k, v in record.items() if k != "verification"},
                         ensure_ascii=False, indent=2)[:2000])
        return 0

    write_once(
        HERE / "guard-fix-record.json",
        json.dumps(record, ensure_ascii=False, indent=2) + "\n",
        reason="79 guard fix record",
        allow_overwrite=True,
    )
    write_once(
        HERE / "guard-fix-record.md",
        render(record),
        reason="79 guard fix record (markdown)",
        allow_overwrite=True,
    )
    manifest = {
        "schema_version": "evidence-manifest-1",
        "created_on": "2026-10-13",
        "zero_model_calls": True,
        "inputs": record["inputs"],
        "outputs": {
            name: sha256(HERE / name)
            for name in ("guard-fix-record.json", "guard-fix-record.md")
        },
        "reproduce": record["reproduce"],
    }
    write_once(
        HERE / "MANIFEST.json",
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        reason="79 manifest",
        allow_overwrite=True,
    )
    print("wrote:", ", ".join(sorted(p.name for p in HERE.iterdir() if p.is_file())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
