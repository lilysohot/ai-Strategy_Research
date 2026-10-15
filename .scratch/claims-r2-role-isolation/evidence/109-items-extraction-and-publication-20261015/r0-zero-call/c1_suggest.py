"""C1 pending-coverage suggestions (109 号, zero-call): match the 29 role-external candidates
against the round-3 pool by normalized text similarity. Suggestions only — the human confirms or
overrules each disposition in the worksheet; nothing here is pre-filled into the adjudication.
"""

from __future__ import annotations

import difflib
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
REPO_ROOT = ROOT.parents[1]

WORKSHEET = HERE / "items-reextract-adjudication-r3/candidate-adjudications.worksheet.json"
PREREG = HERE / "items-reextraction-preregistration-v2.json"
SUGGEST_THRESHOLD = 0.55


def norm(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "")).lower()


def main() -> int:
    worksheet = json.loads(WORKSHEET.read_text(encoding="utf-8"))
    prereg = json.loads(PREREG.read_text(encoding="utf-8"))
    binding = prereg["adjudication_clause"]["c1_pending_coverage"]
    registration = json.loads(
        (REPO_ROOT / binding["source"]).read_text(encoding="utf-8")
    )
    entries = [
        e
        for e in registration["entries"]
        if e.get("owner_role") == "material_items" and e.get("status") == "pending_coverage"
    ]
    assert len(entries) == binding["count"], "C1 count drift"
    pool = [
        (row["candidate_id"], norm(row["original_candidate"].get("text", "")), row["run"])
        for row in worksheet["adjudications"]
    ]
    suggestions = []
    for entry in entries:
        target = norm(entry["claim_text"])
        best_id, best_ratio, best_run = None, 0.0, None
        for candidate_id, text, run in pool:
            ratio = difflib.SequenceMatcher(None, target, text).ratio()
            if ratio > best_ratio:
                best_id, best_ratio, best_run = candidate_id, ratio, run
        suggestions.append(
            {
                "c1_candidate_id": entry["candidate_id"],
                "claim_text": entry["claim_text"],
                "suggested_disposition": (
                    "covered_by_candidate" if best_ratio >= SUGGEST_THRESHOLD else "no_candidate"
                ),
                "suggested_covered_by_candidate_id": (
                    best_id if best_ratio >= SUGGEST_THRESHOLD else None
                ),
                "best_similarity": round(best_ratio, 3),
                "best_match_run": best_run,
                "suggestion_only": True,
            }
        )
    out = HERE / "items-reextract-adjudication-r3/c1-suggestions.json"
    out.write_text(
        json.dumps(
            {
                "schema_version": "items-c1-suggestions-1",
                "suggestion_only": True,
                "threshold": SUGGEST_THRESHOLD,
                "suggestions": suggestions,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    covered = sum(1 for s in suggestions if s["suggested_disposition"] == "covered_by_candidate")
    print(json.dumps({"total": len(suggestions), "suggest_covered": covered}, ensure_ascii=False))
    for s in suggestions:
        print(
            f"{s['c1_candidate_id'][:22]}  sim={s['best_similarity']:.2f}  "
            f"{s['suggested_disposition']}  {str(s['suggested_covered_by_candidate_id'])[:22]}  "
            f"{s['claim_text'][:44]}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
