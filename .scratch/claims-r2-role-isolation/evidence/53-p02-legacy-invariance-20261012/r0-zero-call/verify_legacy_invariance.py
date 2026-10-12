"""P02 exit criterion: the legacy arms must be unchanged by the matcher rework.

Re-runs `evidence/36-l9-redo-and-baseline-20261011`'s four arms **without editing that
historical script** (it is write-once). The script is copied to a sibling directory at the
same depth (so `HERE.parents[4]` still resolves to the repo root), its
`score_structured_quality` is wrapped to supply `matching_mode=LEGACY_IDENTITY`, and only the
copy is written. Results are compared field-by-field against `36/r0-zero-call/l9-redo.json`.

Zero model calls. The temporary copy is removed afterwards.

Usage:
    uv run python .scratch/.../53-p02-legacy-invariance-20261012/r0-zero-call/verify_legacy_invariance.py
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
E53 = HERE.parent
CLAIMS = E53.parent.parent
REPO_ROOT = HERE.parents[4]
sys.path.insert(0, str(REPO_ROOT))

from plugins.corpus.structured_scoring import MatchingMode  # noqa: E402

SOURCE_DIR = CLAIMS / "evidence" / "36-l9-redo-and-baseline-20261011" / "r0-zero-call"
COPY_DIR = CLAIMS / "evidence" / "_tmp-53-legacy-copy" / "r0-zero-call"

COMPARED_SECTIONS = (
    "arms",
    "per_record",
    "coverage",
    "carrier_availability",
    "candidate_side",
    "ec_verdicts",
    "gate28_comparison",
    "total_candidates",
    "association_caveat",
    "schema_version",
    "created_on",
    "zero_call",
)


def sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    original = json.loads((SOURCE_DIR / "l9-redo.json").read_text(encoding="utf-8"))

    shutil.rmtree(COPY_DIR, ignore_errors=True)
    COPY_DIR.mkdir(parents=True)
    for item in SOURCE_DIR.iterdir():
        if item.name == "__pycache__" or item.is_dir():
            continue
        shutil.copy2(item, COPY_DIR / item.name)

    spec = importlib.util.spec_from_file_location("legacy_l9_redo", COPY_DIR / "l9_redo.py")
    if spec is None or spec.loader is None:
        raise SystemExit("cannot load the copied l9_redo module")
    module = importlib.util.module_from_spec(spec)
    sys.modules["legacy_l9_redo"] = module
    spec.loader.exec_module(module)

    real_scorer = module.score_structured_quality
    module.score_structured_quality = functools.partial(  # type: ignore[assignment]
        real_scorer, matching_mode=MatchingMode.LEGACY_IDENTITY
    )
    sys.argv = ["l9_redo"]
    module.main()

    rerun = json.loads((COPY_DIR / "l9-redo.json").read_text(encoding="utf-8"))
    shutil.rmtree(COPY_DIR.parent, ignore_errors=True)

    diffs: list[str] = []
    for section in COMPARED_SECTIONS:
        if original.get(section) != rerun.get(section):
            diffs.append(section)

    result: dict[str, Any] = {
        "schema_version": "items-p02-legacy-invariance-1",
        "created_on": "2026-10-12",
        "zero_call": True,
        "model_requests": 0,
        "purpose": (
            "P02 改造后，evidence/36 的四臂在 LEGACY_IDENTITY 下必须逐字段不变"
            "（防止改造顺手改了 legacy 匹配语义）。"
        ),
        "method": {
            "historical_script_edited": False,
            "how": "复制到同深度的临时目录（使 HERE.parents[4] 仍指向仓库根），"
            "包装 score_structured_quality 注入 matching_mode=LEGACY_IDENTITY，"
            "只写副本；比对后删除副本。",
            "original": str((SOURCE_DIR / "l9-redo.json").relative_to(REPO_ROOT)),
            "original_sha256": sha256(SOURCE_DIR / "l9-redo.json"),
        },
        "compared_sections": list(COMPARED_SECTIONS),
        "differing_sections": diffs,
        "identical": not diffs,
        "arms_original": original.get("arms"),
        "arms_rerun": rerun.get("arms"),
        "verdict": (
            "四臂逐字段不变 ⇒ legacy（控制臂）语义未被 P02 改动。"
            if not diffs
            else f"**不一致**：{diffs} ⇒ 必须查清 P02 是否改了 legacy 语义。"
        ),
        "not_claimed": [
            "本产物只证明 legacy 臂不变；不证明裁定驱动臂在真实数据上正确（真实裁定数仍为 0）。",
            "不改动 evidence/36 的任何字节。",
        ],
    }

    (HERE / "legacy-invariance.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    manifest = {
        "schema_version": "items-p02-legacy-invariance-manifest-1",
        "created_on": "2026-10-12",
        "zero_call": True,
        "inputs": {
            str((SOURCE_DIR / "l9_redo.py").relative_to(REPO_ROOT)): sha256(
                SOURCE_DIR / "l9_redo.py"
            ),
            str((SOURCE_DIR / "l9-redo.json").relative_to(REPO_ROOT)): sha256(
                SOURCE_DIR / "l9-redo.json"
            ),
            str((SOURCE_DIR / "preregistered-l9-redo.json").relative_to(REPO_ROOT)): sha256(
                SOURCE_DIR / "preregistered-l9-redo.json"
            ),
            "plugins/corpus/structured_scoring.py": sha256(
                REPO_ROOT / "plugins" / "corpus" / "structured_scoring.py"
            ),
        },
        "outputs": {
            p.name: sha256(p)
            for p in sorted(HERE.iterdir())
            if p.is_file() and p.name != "MANIFEST.json"
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
                k: v
                for k, v in result.items()
                if k.startswith("arms") or k in ("differing_sections", "identical", "verdict")
            },
            ensure_ascii=False,
            indent=1,
        )
    )


if __name__ == "__main__":
    main()
