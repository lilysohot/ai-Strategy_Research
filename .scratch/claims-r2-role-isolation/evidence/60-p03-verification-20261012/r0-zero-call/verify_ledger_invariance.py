"""P03 exit criterion: the legacy arms' **ledger** must be unchanged by the gate rework.

P03 (threshold single-source) changes the *gate* semantics — declared and signed via
OPEN-1=A. It must NOT change the matching ledger. So this run compares, per arm, exactly the
ledger fields (tp / fp / fn / duplicate_fp / precision / recall / matched) and explicitly
excludes the ``gate`` sub-dict, whose change is the signed deliverable.

Method is the one proven in ``evidence/53``: copy the historical script to a sibling directory
at the same depth (so ``HERE.parents[4]`` still resolves to the repo root), wrap its scorer to
inject ``matching_mode=LEGACY_IDENTITY``, write only the copy, compare, delete the copy.

Zero model calls. Usage:
    uv run python .scratch/.../60-p03-verification-20261012/r0-zero-call/verify_ledger_invariance.py
"""

from __future__ import annotations

import functools
import hashlib
import importlib.util
import json
import shutil
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
E60 = HERE.parent
CLAIMS = E60.parent.parent
REPO_ROOT = HERE.parents[4]
sys.path.insert(0, str(REPO_ROOT))

from plugins.corpus.structured_scoring import MatchingMode  # noqa: E402

SOURCE_DIR = CLAIMS / "evidence" / "36-l9-redo-and-baseline-20261011" / "r0-zero-call"
COPY_DIR = CLAIMS / "evidence" / "_tmp-60-ledger-copy" / "r0-zero-call"

LEDGER_FIELDS = (
    "tp",
    "fp",
    "fn",
    "duplicate_fp",
    "precision",
    "recall",
    "matched",
    "matched_gold_ids",
)


def sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def ledger(arm: dict[str, Any]) -> dict[str, Any]:
    return {key: arm[key] for key in LEDGER_FIELDS if key in arm}


def main() -> None:
    original = json.loads((SOURCE_DIR / "l9-redo.json").read_text(encoding="utf-8"))

    shutil.rmtree(COPY_DIR, ignore_errors=True)
    COPY_DIR.mkdir(parents=True)
    for item in SOURCE_DIR.iterdir():
        if item.name == "__pycache__" or item.is_dir():
            continue
        shutil.copy2(item, COPY_DIR / item.name)

    spec = importlib.util.spec_from_file_location("p03_ledger_l9_redo", COPY_DIR / "l9_redo.py")
    if spec is None or spec.loader is None:
        raise SystemExit("cannot load the copied l9_redo module")
    module = importlib.util.module_from_spec(spec)
    sys.modules["p03_ledger_l9_redo"] = module
    spec.loader.exec_module(module)
    module.score_structured_quality = functools.partial(  # type: ignore[assignment]
        module.score_structured_quality, matching_mode=MatchingMode.LEGACY_IDENTITY
    )
    sys.argv = ["l9_redo"]
    module.main()

    rerun = json.loads((COPY_DIR / "l9-redo.json").read_text(encoding="utf-8"))
    shutil.rmtree(COPY_DIR.parent, ignore_errors=True)

    per_arm: dict[str, dict[str, Any]] = {}
    ledger_identical = True
    gate_changed: list[str] = []
    for arm_name, original_arm in original["arms"].items():
        rerun_arm = rerun["arms"][arm_name]
        if not isinstance(original_arm, dict):  # D/D2 arms are bare scalars
            same_ledger = original_arm == rerun_arm
            ledger_identical = ledger_identical and same_ledger
            per_arm[arm_name] = {"ledger_identical": same_ledger, "gate_blockers_changed": False}
            continue
        same_ledger = ledger(original_arm) == ledger(rerun_arm)
        ledger_identical = ledger_identical and same_ledger
        per_arm[arm_name] = {
            "ledger_identical": same_ledger,
            "gate_blockers_changed": original_arm.get("gate", {}).get("rate_blockers")
            != rerun_arm.get("gate", {}).get("rate_blockers"),
        }
        if per_arm[arm_name]["gate_blockers_changed"]:
            gate_changed.append(arm_name)

    result: dict[str, Any] = {
        "schema_version": "items-p03-ledger-invariance-1",
        "created_on": "2026-10-12",
        "zero_call": True,
        "model_requests": 0,
        "purpose": (
            "P03 改的是门判定（已签决策的落实），不得改匹配账本。逐臂比对账本字段，"
            "显式排除 gate 区块——其变更即本轮已签交付物。"
        ),
        "ledger_fields_compared": list(LEDGER_FIELDS),
        "per_arm": per_arm,
        "ledger_identical": ledger_identical,
        "gate_blockers_changed_in_arms": gate_changed,
        "gate_change_declaration": (
            "rate_gate_passed 语义已切换为契约轴（contract v4.2 threshold_source.effective），"
            "旧按角色阈值降级为 pilot_policy_blockers 诊断清单。gate 区块变更属已签交付物。"
        ),
        "verdict": (
            "四臂账本逐字段不变 ⇒ P03 未触碰匹配语义；gate 区块变更即本轮已签交付物。"
            if ledger_identical
            else "**账本不一致** ⇒ P03 改动了匹配语义，必须回滚排查。"
        ),
        "not_claimed": [
            "不证明裁定驱动臂在真实数据上正确（真实裁定仍为 0）。",
            "不改动 evidence/36 的任何字节。",
        ],
    }

    (HERE / "ledger-invariance.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    manifest = {
        "schema_version": "items-p03-verification-manifest-1",
        "created_on": "2026-10-12",
        "zero_call": True,
        "inputs": {
            str((SOURCE_DIR / "l9_redo.py").relative_to(REPO_ROOT)): sha256(
                SOURCE_DIR / "l9_redo.py"
            ),
            str((SOURCE_DIR / "l9-redo.json").relative_to(REPO_ROOT)): sha256(
                SOURCE_DIR / "l9-redo.json"
            ),
            "plugins/corpus/structured_scoring.py": sha256(
                REPO_ROOT / "plugins/corpus/structured_scoring.py"
            ),
            "evidence/59-p03-design-20261012/r0-zero-call/p03-design-evaluation.md": sha256(
                CLAIMS / "evidence/59-p03-design-20261012/r0-zero-call/p03-design-evaluation.md"
            ),
        },
        "outputs": {
            item.name: sha256(item)
            for item in sorted(HERE.iterdir())
            if item.is_file() and item.name != "MANIFEST.json"
        },
        "in_place_edits": 0,
        "historical_scripts_edited": False,
    }
    (HERE / "MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "ledger_identical": ledger_identical,
                "per_arm": {k: v["ledger_identical"] for k, v in per_arm.items()},
                "gate_changed": gate_changed,
            },
            ensure_ascii=False,
            indent=1,
        )
    )


if __name__ == "__main__":
    main()
