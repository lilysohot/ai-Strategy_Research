"""生成 i0c-r17 冻结快照：M5 复核报告 + U 签认 + F1 修复重绑。

背景：i0c-r16 出包后完成 M5 复核（矩阵 20 块 MATRIX OK、X1—X15 全过），复核自身发现并闭环
F1（缺口回归用例的顺序依赖假红，修 `tests/test_corpus_gap_dispositions.py`）与 F2（备料包锚点
过时，已在 r16 重发）；U 于 2026-09-18 签认 M5 放行（接受复核独立性偏差）。本修订把
「复核报告 + 交叉核验原始输出 + F1 修复后复验证据 + 修复后的测试字节 + 台账回填」纳入冻结，
使 M5 裁决的字节面与证据面同一。

write-once；生成后追加 freeze-manifest 条目，由 validate_i0c_freeze.py 核验血缘（r17→r16→…）。

用法::

    uv run python .scratch/corpus-evidence-pipeline/ingestion-rebuild/m5_review_signoff_freeze.py
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent
FREEZES = BASE / "freezes"
ROOT = BASE.parents[2]

SNAPSHOT_ID = "i0c-r17"
PARENT_ID = "i0c-r16"
M5 = ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260918-m5-review"

GROUPS: dict[str, tuple[str, ...]] = {
    "review_report": (
        f"{M5}/review.md",
        f"{M5}/cross-check-evidence.txt",
        f"{M5}/evidence-postfix/recheck.txt",
        f"{M5}/evidence/index.txt",
        f"{M5}/evidence/matrix-summary.json",
        f"{M5}/evidence/environment.txt",
        f"{M5}/evidence/postflight-hashes.txt",
        # 首次调用被前置门拦下的原始产物（保留字节，改名说明）
        f"{M5}/evidence-aborted-r15-pregate/README-ABORTED.txt",
        f"{M5}/evidence-aborted-r15-pregate/index.txt",
        f"{M5}/evidence-aborted-r15-pregate/freeze-validator.log",
        f"{M5}/evidence-aborted-r15-pregate/environment.txt",
    ),
    "tests": (
        # 本轮无实现（plugins/）改动；重绑 F1 修复后的测试文件（仅 stdout 解析，行为与用例数不变）
        "tests/test_corpus_gap_dispositions.py",
    ),
    "docs": (
        "docs/plan/claims-market-closed-loop-plan.md",
        "docs/plan/corpus-ingestion-rebuild-tasks.md",
    ),
    "freeze_validator": (
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/validate_i0c_freeze.py",
    ),
    "freeze_generator": (
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/m5_review_signoff_freeze.py",
    ),
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fail(message: str) -> None:
    print(f"I0C-R17 FREEZE FAILED: {message}")
    sys.exit(1)


def main() -> None:
    manifest_path = FREEZES / "freeze-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    parents = {entry["snapshot_id"]: entry for entry in manifest.get("snapshots", [])}
    if PARENT_ID not in parents:
        fail(f"索引缺少父快照 {PARENT_ID}")
    if SNAPSHOT_ID in parents:
        fail(f"{SNAPSHOT_ID} 已存在（write-once）")
    parent_file = FREEZES / parents[PARENT_ID]["file"]
    if not parent_file.is_file() or digest(parent_file) != parents[PARENT_ID]["sha256"]:
        fail(f"{PARENT_ID} 文件字节与索引哈希不一致")

    binding: dict[str, dict[str, str]] = {}
    for group, paths in GROUPS.items():
        table: dict[str, str] = {}
        for rel in paths:
            file = ROOT / rel
            if not file.is_file():
                fail(f"绑定文件缺失: {rel}")
            table[rel] = digest(file)
        binding[group] = table

    created_at = datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")
    snapshot = {
        "snapshot_id": SNAPSHOT_ID,
        "revision": "r17",
        "phase": "i0c",
        "task": (
            "M5 independent review executed (matrix 20/20 MATRIX OK, X1-X15) + U sign-off "
            "+ F1 test-hygiene fix rebind"
        ),
        "binding": binding,
        "corrections": {
            "M5_release": (
                "M5 放行：复核包 v2（锚点 r15）矩阵 20 块全绿零 skip（publication 17 / repository 18 / "
                "authority 8 / cli_isolation 5 / consumers 19 / cli 4 / i28-i24 6 / fullchain 12 / "
                "gap_dispositions 13 / i1 业务 188 / guard 19），前置门 4/4、运行后零漂移门过、"
                "装置自证 SELFTEST_OK，交叉核验 X1—X15 全部符合预期。"
            ),
            "U_signoff": (
                "U 于 2026-09-18 签认 M5 放行（依据 U 明确指令「独立复核 + U 签认」）。"
            ),
            "independence_deviation": (
                "复核执行者 = I0—I2 制备方会话，不满足复核包 §9「全新会话」要求；已在 review.md §0 "
                "显著登记，并由 U 在签认时明确接受；若 U 不再认可，M5 立即回到 not_declared 并另派复核人。"
            ),
            "F1": (
                "复核发现（P2 测试卫生）：test_corpus_gap_dispositions.py 直接 json.loads(stdout) 被 "
                "pymupdf 一次性提示行污染 → 单独运行/被 -k 选中时假红；修复为 _cli_json() 从首个 { 解析，"
                "修复后逐用例单独运行 + 整文件 13 + 组合面 96 全绿，证据 evidence-postfix/recheck.txt。"
            ),
            "F2": (
                "复核发现（P3 备料缺陷）：复核包 v1 锚点 i0c-r13 与 import-smoke 固定计数在 r15 后过时；"
                "首次矩阵调用被前置门（绑定零漂移门）正确拦下（证据 evidence-aborted-r15-pregate/）。"
                "处置：包 v2 + i0c-r16 重绑，未放宽任何既有块计数。"
            ),
            "F3": (
                "既有状态（非本轮引入）：validate_i1_freeze.py 对 i1-r3 的工作区绑定自 I0-C/I2 起失配；"
                "M5 矩阵只以 validate_i0c_freeze.py 为冻结门，建议 I3 前置修订理顺。"
            ),
        },
        "notes": [
            "本轮无实现（plugins/）改动：F1 只改测试的 stdout 解析，断言与用例数不变。",
            "证据面冻结：矩阵 evidence 关键件 + 交叉核验原始输出 + F1 复验输出一并绑定；"
            "重跑 verify_matrix.py 必须产出逐字节相同的 matrix-summary.json，否则视为漂移。",
            "生产库 I4 前零写入；本轮真库动作仅限 i2_sandbox_corpus 的 corpus schema。",
            "I3 前置：M5 已放行，但 I3 仍须先做 I3-0/I3-2（评分器与预期冻结）；I3-1 另需其 F1 前置（已闭环）。",
        ],
        "m5_declaration": "released_by_U_signoff（2026-09-18；独立性偏差已登记并由 U 接受）",
        "created_at": created_at,
        "parent_snapshot": {
            "snapshot_id": PARENT_ID,
            "path": f".scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/{parent_file.name}",
            "sha256": digest(parent_file),
        },
    }

    target = FREEZES / f"{SNAPSHOT_ID}.json"
    with target.open("x", encoding="utf-8") as handle:
        json.dump(snapshot, handle, ensure_ascii=False, indent=2, sort_keys=False)
        handle.write("\n")
    manifest.setdefault("snapshots", []).append(
        {
            "snapshot_id": SNAPSHOT_ID,
            "file": target.name,
            "sha256": digest(target),
            "parent_snapshot_id": PARENT_ID,
            "created_at": created_at,
        }
    )
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"{SNAPSHOT_ID} frozen: {target} sha256={digest(target)}")
    print("bindings: " + ", ".join(f"{group}={len(v)}" for group, v in binding.items()))


if __name__ == "__main__":
    main()
