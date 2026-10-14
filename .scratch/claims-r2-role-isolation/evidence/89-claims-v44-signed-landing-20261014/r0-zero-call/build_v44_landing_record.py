"""Landing record: signed claims contract v4.4, the C2 correction, and the C3 read path.

Runs the focused verification battery and records: commands, exit codes, changed-file hashes,
frozen-file hashes, the signed-contract digest, the C2 retraction, and the state changes since
the 87-号 landing record. Zero model calls; read-only with respect to every frozen artifact.

Usage:
    python build_v44_landing_record.py [--no-write] [--force]
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
    "plugins/corpus/adjudication_assembly.py",
    "tools/check_claims_gate.py",
    "tests/test_claims_gate_invariants.py",
    "tests/test_claims_contract_role.py",
)
FROZEN_WITH_EXPECTED_HASH = {
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
    "evidence/86-claims-contract-v44-draft-20261014/r0-zero-call"
    "/scoring-contract-v4.4.proposed.json": (
        "79e8651d12d917c6f62d2d9416ca9de205e68a7caf710387319168990cb4dea2"
    ),
}
SIGNED_ARTIFACTS = (
    "evidence/88-claims-contract-v44-signed-20261014/r0-zero-call/scoring-contract-v4.4.json",
    "evidence/88-claims-contract-v44-signed-20261014/r0-zero-call/c2-measurement.json",
    "evidence/88-claims-contract-v44-signed-20261014/r0-zero-call/contract-v4.4-signed-diff.json",
)

COMMANDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "ruff_check_changed",
        ("uv", "run", "ruff", "check", "plugins/corpus/structured_scoring.py",
         "plugins/corpus/adjudication_assembly.py", "tools/check_claims_gate.py"),
    ),
    (
        "focused_tests",
        (
            "uv", "run", "pytest",
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
            "uv", "run", "python",
            ".scratch/claims-r2-role-isolation/evidence/78-p03-binding-catchup-20261013"
            "/r0-zero-call/verify_p03_binding.py",
            "--no-write",
        ),
    ),
    ("claims_gate_checker", ("uv", "run", "python", "tools/check_claims_gate.py")),
    (
        "c2_duplicate_accounting",
        (
            "uv", "run", "python",
            ".scratch/claims-r2-role-isolation/evidence/88-claims-contract-v44-signed-20261014"
            "/r0-zero-call/verify_c2_duplicate_accounting.py",
        ),
    ),
)

CORRECTIONS = [
    {
        "id": "C-1",
        "artifact": "evidence/84-…/claims-gate-v2.proposed.json（以及 85/86 号转述）",
        "retracted": "D1 记录『评分器实现公式 56/107 = 0.5234』",
        "replacement": "评分器实现 = 56/110 = 0.5091，与契约文字公式同源",
        "reason": "草案把裁定文件的 incorrect 计数当成评分器的 fp；实测评分器 fp=54（已在 false_positives 内含 DUPLICATE 3 条）",
        "evidence": "88 号 verify_c2_duplicate_accounting.py（ledger: tp 20 / ce 36 / fp 54 / duplicate_fp 3 / fn 0）",
    },
    {
        "id": "C-2",
        "artifact": "evidence/85-…/audit-report.json（审核项 caliber-divergence:duplicate）",
        "retracted": "『契约文字公式与评分器实现不同源』的分歧判定",
        "replacement": "同源；新审核项 duplicate-accounting-single-source（blocking）+ gate-recorded-implemented-formula（记录 84 号残留读数）",
        "reason": "同上；85 号字节不改写，以本记录登记取代",
        "evidence": "tools/check_claims_gate.py 现版本；tests/test_claims_gate_invariants.py",
    },
    {
        "id": "C-3",
        "artifact": "evidence/86-…/scoring-contract-v4.4.proposed.json 的 C2 叶",
        "retracted": "『须改 RoleMetrics.precision 计入 duplicate_fp』",
        "replacement": "单一口径 = 含 duplicate 的契约公式（已满足）；该实现改动作废",
        "reason": "若照草案实现会得 56/113 = 0.4956（重复计数）",
        "evidence": "88 号 scoring-contract-v4.4.json 的 claims_precision_single_source.correction",
    },
    {
        "id": "C-4",
        "artifact": "evidence/87-…/landing-record.json 的 changed_files 哈希",
        "retracted": "87 号记录的改动文件快照哈希（C2 更正与 C3 接线前的字节）",
        "replacement": "本记录 changed_files 为当前字节；87 号作为上一轮快照保留",
        "reason": "本轮改动了 structured_scoring.py 与 adjudication_assembly.py，87 号快照随之过期",
        "evidence": "本记录 changed_files",
    },
]

STATE_CHANGES = [
    {
        "id": "C1-claims 角色范围",
        "was": "待签（agent 提案）",
        "now": "已签（契约 v4.4 claims_scope）",
        "note": "分母口径取值已定；候选池分类的移出仍需在 items/relations 侧登记覆盖（未做）",
    },
    {
        "id": "C2-精度单一口径",
        "was": "待签（前提有误）",
        "now": "已签 + 具名更正",
        "note": "契约文字与实现本就同源；实现改动作废，禁止补加 duplicate_fp",
    },
    {
        "id": "C3-claims 读路径",
        "was": "待签（只提案）",
        "now": "已签 + 代码接线完成",
        "note": "adjudication_assembly 惰性读取 read_path.roles_proposed.claims.carriers；实测 11 字段、"
        "一条真实裁定行进装配成功（matching basis 10 项、absent 4 项）",
    },
    {
        "id": "C4-用途分级",
        "was": "待签",
        "now": "已签，**未实现**",
        "note": "须先拆 reason_codes 为『阻断匹配』与『阻断用途』两类；属改默认行为",
    },
    {
        "id": "C5/C6-双线阈值 + 不可达登记",
        "was": "待签",
        "now": "已签（契约 claims_thresholds）",
        "note": "目标线不动；放行线 0.60 / 分源 0.55；冻结池不可达已登记",
    },
    {
        "id": "claims 门 artifact",
        "was": "84 号草案（D4 行不完整 + 实现公式读数错误）",
        "now": "仍为 84 号；须出 gate v3（补 D4 行、改读数、钉已签契约）",
        "note": "门与契约互钉：契约已签，门待生成并签",
    },
    {
        "id": "claims 全量实跑（110 条）",
        "was": "未做",
        "now": "未做",
        "note": "前置已解除（读路径可用），仍缺 doc→source_id 映射（P1R5 行无 source_id 字段，"
        "且 stage 词表为 human_adjudicated_candidate）",
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
        path: {"expected": expected, "on_disk": sha256(ROOT / path), "unchanged": sha256(ROOT / path) == expected}
        for path, expected in FROZEN_WITH_EXPECTED_HASH.items()
    }
    signed = {path: sha256(ROOT / path) for path in SIGNED_ARTIFACTS}
    signed_contract = json.loads((ROOT / SIGNED_ARTIFACTS[0]).read_text(encoding="utf-8"))
    record = {
        "schema_version": "claims-v44-signed-landing-1",
        "created_on": RECORD_ON,
        "zero_model_calls": True,
        "model_calls": 0,
        "production_pg_access": 0,
        "commands": results,
        "all_commands_ok": all(item["ok"] for item in results.values()),
        "changed_files": {path: sha256(REPO_ROOT / path) for path in CHANGED_FILES},
        "frozen_files": frozen,
        "all_frozen_unchanged": all(entry["unchanged"] for entry in frozen.values()),
        "signed_artifacts": signed,
        "signed_contract": {
            "path": SIGNED_ARTIFACTS[0],
            "status": signed_contract["status"],
            "signed_by": signed_contract["signoff"]["signed_by"],
            "signed_on": signed_contract["signoff"]["signed_on"],
            "instrument": signed_contract["signoff"]["instrument"],
            "claims_sentinels": signed_contract["role_sections"]["claims"]["review_assertions"],
            "claims_target_total": signed_contract["role_sections"]["claims"]["target_total"],
            "c2_correction_applied": bool(
                signed_contract["claims_precision_single_source"].get("correction")
            ),
        },
        "corrections": CORRECTIONS,
        "state_changes_since_87": STATE_CHANGES,
        "still_pending": [
            "claims 门 v3（补 D4 行、改正读数、钉已签契约）并具名签认",
            "claims 全量实跑：需先建 doc→source_id 映射与 stage 词表适配，再出分",
            "C4 用途分级实现（改默认行为，已签待落地）",
            "C1 移出项的 items/relations 侧覆盖登记",
            "F6：是否授权重跑产出新池",
        ],
        "uncovered_scope": [
            "未做 claims 池的 110 条全量评分（只做了 1 条装配冒烟）",
            "未复核 .scratch/evidence/01–82 全部内容",
            "未执行任何模型调用、发布、query/delivery/context_use、M_main 消费",
        ],
    }
    manifest = {
        "schema_version": "claims-v44-signed-landing-manifest-1",
        "status": "draft",
        "created_on": RECORD_ON,
        "model_calls": 0,
        "inputs": {**{f"frozen::{k}": v for k, v in signed.items()}},
        "outputs": {},
        "does_not_touch": [*FROZEN_WITH_EXPECTED_HASH, *SIGNED_ARTIFACTS],
    }
    return {"record": record, "manifest": manifest}


def render_md(record: dict[str, Any]) -> str:
    lines = [
        "# Claims 契约 v4.4 签认落地记录（机器生成）",
        "",
        f"日期 {record['created_on']}；零模型调用；冻结件全部未变：{record['all_frozen_unchanged']}；"
        f"验证命令全绿：{record['all_commands_ok']}。",
        "",
        "## 一、已签契约",
        "",
        f"- `{record['signed_contract']['path']}`（status=`{record['signed_contract']['status']}`，"
        f"signed_by={record['signed_contract']['signed_by']}，"
        f"signed_on={record['signed_contract']['signed_on']}）",
        f"- 签署工具：`{record['signed_contract']['instrument']['path']}` "
        f"`{record['signed_contract']['instrument']['sha256'][:19]}…`",
        f"- claims 哨兵 {record['signed_contract']['claims_sentinels']}，"
        f"target_total={record['signed_contract']['claims_target_total']}，"
        f"C2 更正已附：{record['signed_contract']['c2_correction_applied']}",
        "",
        "## 二、验证命令",
        "",
        "| 命令 | 退出码 | 判定 |",
        "|---|---|---|",
    ]
    for name, item in record["commands"].items():
        lines.append(f"| `{name}` | {item['exit_code']} | {'ok' if item['ok'] else 'FAIL'} |")
    lines += ["", "## 三、更正登记（取代关系，旧字节未改）", "", "| 编号 | 被取代的表述 | 取代为 | 依据 |", "|---|---|---|---|"]
    for item in record["corrections"]:
        lines.append(f"| {item['id']} | {item['retracted']} | {item['replacement']} | {item['evidence']} |")
    lines += ["", "## 四、状态变化（相对 87 号）", "", "| 组件 | 87 号时 | 现在 | 说明 |", "|---|---|---|---|"]
    for item in record["state_changes_since_87"]:
        lines.append(f"| {item['id']} | {item['was']} | **{item['now']}** | {item['note']} |")
    lines += ["", "## 五、仍未完成", ""]
    lines += [f"- {text}" for text in record["still_pending"]]
    lines += ["", "## 六、未覆盖范围", ""]
    lines += [f"- {text}" for text in record["uncovered_scope"]]
    lines += ["", "## 七、冻结件逐条哈希", "", "| 文件 | 未变 |", "|---|---|"]
    for path, entry in record["frozen_files"].items():
        lines.append(f"| `{path}` | {entry['unchanged']} |")
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
                    "all_frozen_unchanged": result["record"]["all_frozen_unchanged"],
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
