"""C2 re-check: does the scorer's precision already equal the contract's duplicate-inclusive formula?

The v2 draft asserted a caliber divergence (contract text 56/110 vs "implemented" 56/107) by
reading the adjudication file's ``incorrect`` count as if it were the scorer's ``fp``. This
script measures what the scorer actually reports for the frozen claims pool, using one constant
source id so the matched-mapping identity check passes without needing a doc->source registry:

    RoleMetrics.fp  counts duplicates as well (``_match_by_adjudication`` appends DUPLICATE to
    false_positives), so the implemented denominator is numerator + fp, which already contains
    the duplicates. Adding ``duplicate_fp`` on top would double count.

Zero model calls; read-only.

Usage:
    python verify_c2_duplicate_accounting.py [--json out.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from fractions import Fraction
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
REPO_ROOT = ROOT.parents[1]
sys.path.insert(0, str(REPO_ROOT))

from plugins.corpus.structured_scoring import (  # noqa: E402
    CandidateRecord,
    GoldRecord,
    MatchingMode,
    RecordOrigin,
    Role,
    score_structured_quality,
)

GOLD = ROOT / "evidence/10-quality-gold-freeze-20261008-r2/frozen-gold.json"
POOL = (
    ROOT
    / "evidence/17-structured-extraction-convergence-closure-20261009"
    / "p1r5-claims-adjudication-v2/candidate-adjudications.signed.json"
)
SOURCE = "sha256:" + "c" * 64


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


class _Mapping:
    """Duck-typed adjudication mapping (the scorer reads attributes only)."""

    def __init__(self, candidate_id: str, gold_record_id: str | None, judgement: str) -> None:
        self.candidate_id = candidate_id
        self.gold_record_id = gold_record_id
        self.judgement = judgement
        self.stage = "raw"


def build() -> dict[str, Any]:
    gold_rows = [r for r in load(GOLD)["records"] if r["role"] == "claims"]
    gold = tuple(
        GoldRecord(
            record_id=row["record_id"],
            role=Role.CLAIMS,
            source_id=SOURCE,
            origin=RecordOrigin.LLM_PROSE,
            semantic_fields=(("value", row["record_id"]),),
        )
        for row in gold_rows
    )
    rows = load(POOL)["adjudications"]
    candidates = tuple(
        CandidateRecord(
            candidate_id=row["candidate_id"],
            role=Role.CLAIMS,
            source_id=SOURCE,
            origin=RecordOrigin.LLM_PROSE,
            semantic_fields=(("claim_text", row["candidate_id"]),),
        )
        for row in rows
    )
    mappings = tuple(
        _Mapping(row["candidate_id"], row.get("matched_gold_id"), str(row["judgement"]))
        for row in rows
    )
    report = score_structured_quality(
        gold,
        matching_mode=MatchingMode.ADJUDICATED,
        raw_candidates=candidates,
        validated_candidates=candidates,
        raw_mappings=mappings,
        validated_mappings=mappings,
    )
    metrics = report.raw.role(Role.CLAIMS)
    numerator = metrics.tp + metrics.correct_extra
    implemented = Fraction(numerator, numerator + metrics.fp)
    double_counted = Fraction(numerator, numerator + metrics.fp + metrics.duplicate_fp)
    ledger = {
        "tp": metrics.tp,
        "correct_extra": metrics.correct_extra,
        "fp_includes_duplicates": metrics.fp,
        "duplicate_fp_subset": metrics.duplicate_fp,
        "fn": metrics.fn,
    }
    return {
        "pool_size": len(rows),
        "ledger": ledger,
        "precision_implemented": f"{implemented.numerator}/{implemented.denominator} = {float(implemented):.4f}",
        "precision_contract_text": "56/110 = 0.5091",
        "precision_if_duplicate_added_again": (
            f"{double_counted.numerator}/{double_counted.denominator} = {float(double_counted):.4f}"
        ),
        "implementation_equals_contract": implemented == Fraction(56, 110),
        "fp_equals_incorrect_plus_duplicate": metrics.fp
        == sum(1 for r in rows if r["judgement"] in {"incorrect", "duplicate"}),
        "conclusion": (
            "评分器 precision 已等于契约文字公式（fp 已含 duplicate）；C2 的『实现分歧』是读数错误，"
            "补加 duplicate_fp 会造成重复计数"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    result = build()
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.json:
        args.json.write_text(payload, encoding="utf-8")
    print(payload)
    return 0 if result["implementation_equals_contract"] else 1


if __name__ == "__main__":
    sys.exit(main())
