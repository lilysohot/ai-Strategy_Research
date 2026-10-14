"""Landing record: role-parameterised contract loader + claims contract v4.4 draft.

Runs the focused verification battery and writes the record (commands, exit codes, tail of
output, changed-file hashes, and the state changes since the 85 audit). Zero model calls; every
command is read-only with respect to frozen artifacts.

Usage:
    python build_landing_record.py [--no-write] [--force]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]  # .scratch/claims-r2-role-isolation
REPO_ROOT = ROOT.parents[1]

RECORD_ON = "2026-10-14"

CHANGED_FILES = (
    "plugins/corpus/structured_scoring.py",
    "tools/check_claims_gate.py",
    "tests/test_claims_gate_invariants.py",
    "tests/test_claims_contract_role.py",
)
FROZEN_UNTOUCHED = (
    "evidence/75-r2-signed-20261013/r0-zero-call/scoring-contract-v4.3.json",
    "evidence/75-r2-signed-20261013/r0-zero-call/gate-v3.json",
    "evidence/10-quality-gold-freeze-20261008-r2/frozen-gold.json",
    "evidence/17-structured-extraction-convergence-closure-20261009"
    "/p1r5-claims-adjudication-v2/candidate-adjudications.signed.json",
    "evidence/83-claims-scope-gate-draft-20261014/r0-zero-call/claims-gate-v1.proposed.json",
    "evidence/84-claims-gate-v2-draft-20261014/r0-zero-call/claims-gate-v2.proposed.json",
)
EXPECTED_FROZEN_HASHES = {
    "evidence/75-r2-signed-20261013/r0-zero-call/scoring-contract-v4.3.json": (
        "d7b4f8a81ef42e3cd5d619eae92bc34df7b7aa683d34aeba4f1a22719ae69a2f"
    ),
    "evidence/75-r2-signed-20261013/r0-zero-call/gate-v3.json": (
        "340b312d9c0cec278e828d8303a03e9daf953feef4c0eef688f3d257971a9732"
    ),
    "evidence/10-quality-gold-freeze-20261008-r2/frozen-gold.json": (
        "603de5e6c532463db8ae2788b830c2c1a74400b4ba736292bd5503468dfa7de2"
    ),
    "evidence/17-structured-extraction-convergence-closure-20261009"
    "/p1r5-claims-adjudication-v2/candidate-adjudications.signed.json": (
        "d12f3d276dc17d2ff5bb5455b78bc4da75b43c191d498af59d2aea61238b38a8"
    ),
    "evidence/83-claims-scope-gate-draft-20261014/r0-zero-call/claims-gate-v1.proposed.json": (
        "28f19286cbe9c72e298c6ba05625d6ca1f24159c3321ce652e72cc50bdfa1f4c"
    ),
    "evidence/84-claims-gate-v2-draft-20261014/r0-zero-call/claims-gate-v2.proposed.json": (
        "ad9b080e9a52b50b50f55498ba460956285a997ec934e132a39bbe090bd22a8c"
    ),
}

COMMANDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ruff_check_changed", ("uv", "run", "ruff", "check", *CHANGED_FILES)),
    (
        "focused_tests",
        (
            "uv",
            "run",
            "pytest",
            "tests/test_claims_gate_invariants.py",
            "tests/test_claims_contract_role.py",
            "tests/test_corpus_contract_gate.py",
            "tests/test_corpus_structured_scoring.py",
            "tests/test_corpus_structured_scoring_adjudicated.py",
            "tests/test_corpus_adjudication_assembly.py",
            "-q",
        ),
    ),
    ("import_smoke_stage1", ("uv", "run", "python", "tools/import_smoke.py", "--stage", "1")),
    ("check_symbols", ("uv", "run", "python", "tools/check_symbols.py")),
    (
        "p03_binding_verifier",
        (
            "uv",
            "run",
            "python",
            ".scratch/claims-r2-role-isolation/evidence/78-p03-binding-catchup-20261013"
            "/r0-zero-call/verify_p03_binding.py",
            "--no-write",
        ),
    ),
    ("claims_gate_checker", ("uv", "run", "python", "tools/check_claims_gate.py")),
)

FULL_SUITE = {
    "command": "uv run pytest tests -q",
    "performed_on": RECORD_ON,
    "result": "13 failed, 3194 passed, 238 skipped",
    "attributed": "environment/pre-existing",
    "attribution_evidence": "失败文件均不导入被改模块（structured_scoring / adjudication_assembly / "
    "ContractGateRequirements）；失败形态为 TimeoutError、wall_deadline、reader-pdf 环境断言",
    "failing_files": [
        "tests/test_artifacts_t29.py",
        "tests/test_corpus_preparation_readers.py",
        "tests/test_hf_space_runtime.py",
        "tests/test_market_gate.py",
        "tests/test_market_golden.py",
        "tests/test_research_discipline.py",
        "tests/test_stop_t28.py",
        "tests/test_upload_t210.py",
        "tests/test_usage_t211.py",
        "tests/test_web_m1.py",
        "tests/test_web_p3_steer.py",
    ],
    "not_attributed_scope": "上述断言失败未逐条归因到既有缺陷；本记录只声明它们不由本次改动引入",
}

STATE_CHANGES_SINCE_AUDIT = [
    {
        "id": "F7-一致性校验器 + 复算回归",
        "was": "landed_now",
        "now": "landed_now",
        "note": "无变化（85 号已落地）",
    },
    {
        "id": "F8-契约读取器按角色参数化",
        "was": "needs_human_decision",
        "now": "landed_now",
        "note": "本轮落地：loader 支持 role 参数、role_sections 分支与 schema v4.4 白名单；items 行为逐字不变"
        "（P03 绑定校验 8/0、既有测试全过）；claims 分支在 v4.3 上 fail-closed",
    },
    {
        "id": "C3-claims 读路径取值",
        "was": "needs_human_decision",
        "now": "needs_human_decision",
        "note": "仍未实施：86 号只给 carrier 提案（四字段 0 载体），生效须签认",
    },
    {
        "id": "C1/C2/C4/C5/C6",
        "was": "needs_human_decision",
        "now": "needs_human_decision",
        "note": "86 号写为 agent 提案并附实测值；未签认前不改任何默认行为",
    },
    {
        "id": "门侧（claims gate）",
        "was": "84 号草案（D4 行不完整）",
        "now": "84 号字节未动；D4 行补全并入『契约签认后生成 claims 门 v3』这一步",
        "note": "门必须与已签契约互钉，故门版本在契约签认后再出，避免草案互钉成环",
    },
    {
        "id": "F9-生产侧接缝",
        "was": "not_executable_this_round",
        "now": "not_executable_this_round",
        "note": "候选池仍冻结；要体现效果须 F6 重跑授权",
    },
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command: tuple[str, ...]) -> dict[str, Any]:
    completed = subprocess.run(
        command, cwd=REPO_ROOT, capture_output=True, text=True, timeout=1800, check=False
    )
    tail = (completed.stdout + completed.stderr).strip().splitlines()
    return {
        "command": " ".join(command),
        "exit_code": completed.returncode,
        "tail": tail[-6:],
        "ok": completed.returncode == 0,
    }


def build() -> dict[str, Any]:
    results = {name: run(command) for name, command in COMMANDS}
    frozen = {
        path: {"expected": EXPECTED_FROZEN_HASHES[path], "on_disk": sha256(ROOT / path)}
        for path in FROZEN_UNTOUCHED
    }
    changed = {path: sha256(REPO_ROOT / path) for path in CHANGED_FILES}
    contract_draft = (
        ROOT
        / "evidence/86-claims-contract-v44-draft-20261014/r0-zero-call"
        / "scoring-contract-v4.4.proposed.json"
    )
    diff_draft = contract_draft.parent / "contract-v4.4-diff.json"
    diff_payload = json.loads(diff_draft.read_text(encoding="utf-8"))
    record = {
        "schema_version": "claims-role-parameterization-landing-1",
        "created_on": RECORD_ON,
        "zero_model_calls": True,
        "model_calls": 0,
        "production_pg_access": 0,
        "runner": "uv",
        "commands": results,
        "all_commands_ok": all(item["ok"] for item in results.values()),
        "changed_files": changed,
        "frozen_files_unchanged": {
            path: entry["expected"] == entry["on_disk"] for path, entry in frozen.items()
        },
        "frozen_files_detail": frozen,
        "contract_v44_draft": {
            "path": str(contract_draft.relative_to(ROOT)),
            "sha256": sha256(contract_draft),
            "status": json.loads(contract_draft.read_text(encoding="utf-8"))["status"],
            "diff": {
                "removed_leaf_paths": diff_payload["removed_leaf_paths"],
                "unexpected_changed": diff_payload["unexpected_changed"],
                "thresholds_byte_identical": diff_payload["thresholds_byte_identical"],
            },
        },
        "full_suite": FULL_SUITE,
        "state_changes_since_audit": STATE_CHANGES_SINCE_AUDIT,
        "still_pending": [
            "C1/C2/C3/C4/C5/C6 六格签认（86 号 claims-contract-v4.4-signoff.md）",
            "契约签认后：生成 claims 门 v3（含 84 号 D4 行补全）+ 与契约互钉",
            "C2 落地：RoleMetrics.precision 计入 duplicate_fp（改默认行为，须具名）",
            "C3 落地：claims 读路径 + 装配器 ROLE_CARRIERS[claims]",
            "C4 落地：用途分级（拆 reason 轴）",
            "F6：是否授权重跑产出新池（唯一能让目标线可达）",
        ],
        "uncovered_scope": [
            "未复核 .scratch/evidence/01–82 的全部内容",
            "未归因 full_suite 中 13 项既有失败的根因（只声明非本次引入）",
            "未执行任何模型调用、发布、query/delivery/context_use、M_main 消费",
        ],
    }
    manifest = {
        "schema_version": "claims-role-parameterization-landing-manifest-1",
        "status": "draft",
        "created_on": RECORD_ON,
        "model_calls": 0,
        "inputs": {
            **{f"frozen::{path}": EXPECTED_FROZEN_HASHES[path] for path in FROZEN_UNTOUCHED},
            "contract_v44_draft": sha256(contract_draft),
            "contract_v44_diff": sha256(diff_draft),
        },
        "outputs": {},
        "does_not_touch": list(FROZEN_UNTOUCHED),
    }
    return {"record": record, "manifest": manifest}


def render_md(record: dict[str, Any]) -> str:
    lines = [
        "# Claims 角色参数化落地记录（机器生成）",
        "",
        f"日期 {record['created_on']}；零模型调用；改动文件 {len(record['changed_files'])} 个，"
        f"冻结件全部未变：{all(record['frozen_files_unchanged'].values())}。",
        "",
        "## 一、验证命令",
        "",
        "| 命令 | 退出码 | 判定 |",
        "|---|---|---|",
    ]
    for name, item in record["commands"].items():
        lines.append(f"| `{name}`: {item['command']} | {item['exit_code']} | {'ok' if item['ok'] else 'FAIL'} |")
    lines += ["", "## 二、改动文件哈希", "", "| 文件 | sha256 |", "|---|---|"]
    for path, digest in record["changed_files"].items():
        lines.append(f"| `{path}` | `{digest}` |")
    lines += [
        "",
        "## 三、冻结件未变（逐条哈希）",
        "",
        "| 文件 | 期望 == 实测 |",
        "|---|---|",
    ]
    for path, ok in record["frozen_files_unchanged"].items():
        lines.append(f"| `{path}` | {ok} |")
    contract = record["contract_v44_draft"]
    lines += [
        "",
        "## 四、契约 v4.4 草案",
        "",
        f"- 路径：`{contract['path']}`（`{contract['sha256'][:12]}…`，status=`{contract['status']}`）",
        f"- 删除叶子：{contract['diff']['removed_leaf_paths'] or '无'}；"
        f"计划外改动：{contract['diff']['unexpected_changed'] or '无'}；"
        f"六项阈值逐字不变：{contract['diff']['thresholds_byte_identical']}",
        "",
        "## 五、85 号审核后的状态变化（回扫）",
        "",
        "| 组件 | 审核时 | 现在 | 说明 |",
        "|---|---|---|---|",
    ]
    for item in record["state_changes_since_audit"]:
        lines.append(f"| {item['id']} | {item['was']} | **{item['now']}** | {item['note']} |")
    lines += ["", "## 六、仍未完成", ""]
    lines += [f"- {text}" for text in record["still_pending"]]
    lines += ["", "## 七、未覆盖范围", ""]
    lines += [f"- {text}" for text in record["uncovered_scope"]]
    full = record["full_suite"]
    lines += [
        "",
        "## 八、全量测试（本次手动执行，非本脚本）",
        "",
        f"- 命令：`{full['command']}`；结果：{full['result']}；归因：{full['attributed']}",
        f"- 依据：{full['attribution_evidence']}",
        f"- 未归因声明：{full['not_attributed_scope']}",
        "",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    result = build()
    outputs = {
        "landing-record.json": (
            json.dumps(result["record"], ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8"),
        "landing-record.md": render_md(result["record"]).encode("utf-8"),
    }
    manifest = result["manifest"]
    manifest["outputs"] = {name: hashlib.sha256(data).hexdigest() for name, data in outputs.items()}
    outputs["MANIFEST.json"] = (
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")

    if args.no_write:
        print(
            json.dumps(
                {
                    "all_commands_ok": result["record"]["all_commands_ok"],
                    "frozen_unchanged": all(
                        result["record"]["frozen_files_unchanged"].values()
                    ),
                },
                ensure_ascii=False,
            )
        )
        print(f"[no-write] {len(outputs)} outputs computed; nothing written.")
        return 0

    existing = [name for name in outputs if (HERE / name).exists()]
    if existing and not args.force:
        raise SystemExit(f"refusing to overwrite existing outputs {existing}; use --force")
    for name, data in outputs.items():
        (HERE / name).write_bytes(data)
    print(f"wrote {len(outputs)} files to {HERE}")
    print(json.dumps(manifest["outputs"], ensure_ascii=False, indent=2))
    return 0 if result["record"]["all_commands_ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
