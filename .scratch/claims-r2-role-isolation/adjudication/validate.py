"""裁定工作表自检：逐条跑装配器校验，给出可填进度与逐条错误。

用法（在工作表同目录）：
    uv run python .scratch/claims-r2-role-isolation/adjudication/validate.py
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from plugins.corpus.adjudication_assembly import assemble_scoring_input  # noqa: E402
from plugins.corpus.structured_scoring import ScoringInputError  # noqa: E402

HERE = Path(__file__).resolve().parent
SHEET = HERE / "worksheet.json"
CATALOG_SOURCE = (
    REPO_ROOT
    / ".scratch/claims-r2-role-isolation/evidence/38-gate33-workbench-rebuild-20261012/r0-zero-call/workbench-v2.json"
)

VALID_JUDGEMENTS = {
    "matched",
    "correct_extra",
    "incorrect",
    "duplicate",
    "unresolved",
    "out_of_scope",
}


def main() -> int:
    sheet = json.loads(SHEET.read_text(encoding="utf-8"))
    records = sheet["records"]
    catalog = {row["candidate_id"]: row for row in json.loads(CATALOG_SOURCE.read_text(encoding="utf-8"))["candidates"]}

    filled = [row for row in records if row.get("judgement")]
    unfilled = [row for row in records if not row.get("judgement")]
    bad_judgement = [
        row["candidate_id"]
        for row in filled
        if str(row["judgement"]) not in VALID_JUDGEMENTS
    ]
    unresolved = [row["candidate_id"] for row in filled if str(row["judgement"]) == "unresolved"]

    errors: list[dict[str, str]] = []
    assembled = 0
    for row in filled:
        try:
            assemble_scoring_input([row], catalog=catalog)
            assembled += 1
        except ScoringInputError as error:
            errors.append({"candidate_id": row["candidate_id"], "error": str(error)})

    matched = [row for row in filled if str(row["judgement"]) == "matched"]
    by_source = Counter(
        str(row["source_id"]).split("sha256:")[-1][:8] for row in matched
    )
    summary = {
        "total": len(records),
        "filled": len(filled),
        "unfilled": len(unfilled),
        "assembled_ok": assembled,
        "rejected": len(errors),
        "bad_judgement": bad_judgement,
        "unresolved": unresolved,
        "matched_by_source_sha8": dict(by_source),
        "gate_ready": assembled == len(records) and not unresolved and not bad_judgement,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    if errors:
        print("\n逐条错误（前 20 条）:")
        for item in errors[:20]:
            print(f"  {item['candidate_id']}: {item['error']}")
    if unfilled:
        print(f"\n未填 {len(unfilled)} 条，例如: {[row['candidate_id'] for row in unfilled[:5]]}")
    return 0 if summary["gate_ready"] else 1


if __name__ == "__main__":
    sys.exit(main())
