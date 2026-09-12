"""Reproduce the visually checked four-year financial-basis review; no model calls."""

import json
from decimal import Decimal
from pathlib import Path

from plugins.corpus.evidence import fingerprint
from plugins.corpus.service import CorpusService
from scripts.corpus_evidence_pilot import calculations, save_artifact

GOLD = {
    "2025A": ("50.5", "172054", "85310", "82320", "2990"),
    "2026E": ("50.2", "178657", "87841", "84679", "3162"),
    "2027E": ("50.2", "186196", "91774", "88470", "3304"),
    "2028E": ("50.3", "194063", "95749", "92302", "3447"),
}


def counts(service):
    with service._connect() as conn:
        return conn.execute(
            "SELECT (SELECT count(*) FROM documents) AS documents, "
            "(SELECT count(*) FROM blocks) AS blocks, "
            "(SELECT count(*) FROM claims) AS claims, "
            "(SELECT count(*) FROM claims_v2) AS claims_v2"
        ).fetchone()


def main():
    paths = list(Path("data/corpus").glob("*e034bdac.pdf"))
    assert len(paths) == 1
    service = CorpusService()
    before = counts(service)
    run = service.extract_claims(paths[0], pages=(3,))
    reviews = service.reconcile_claims(run_id=run.run_id)
    assert {row["period"] for row in reviews} == set(GOLD)
    for row in reviews:
        margin, revenue, profit, parent, minority = GOLD[row["period"]]
        for metric, expected in zip(
            ("net_margin", "revenue", "net_profit", "parent_net_profit", "minority_profit"),
            (margin, revenue, profit, parent, minority), strict=True,
        ):
            found = [f for f in run.facts if f.metric_id == metric and f.claim.period_raw == row["period"]]
            assert len(found) == 1
            fact = found[0]
            scale = Decimal(1) if metric == "net_margin" else Decimal(1000000)
            assert fact.claim.value_num == Decimal(expected) * scale
            evidence = service.fetch_evidence(run.run_id, fact.packet_id)
            assert fact.claim.evidence_quote in evidence["text"]
        assert row["source_value"] == margin
        assert Decimal(row["derived_value"]) == Decimal(profit) / Decimal(revenue) * 100
        assert Decimal(row["profit_residual"]) == 0
        assert row["status"] == "review_definition_or_source"
        assert row["source_usable_for"] == ["cite"]
        assert row["definition_verified"] is False
    calc = service.claims_of(run_id=run.run_id, purpose="calculate", limit=1000)
    assert not any(row["metric_id"] == "net_margin" for row in calc["items"])
    formulas = calculations(run)
    assert len(formulas) == 7 and all(row["passed"] for row in formulas)
    after = counts(service)
    assert before == after
    report = {
        "status": "review_completed_definition_unresolved", "model_calls": 0,
        "source_path": str(paths[0]), "source_rev": run.document.source_rev,
        "run_id": run.run_id, "pipeline_version": run.pipeline_version,
        "visually_checked_pages": [1, 2, 3], "gold_fields_passed": 20,
        "reviews": reviews, "existing_formula_checks": formulas,
        "legacy_counts_before": before, "legacy_counts_after": after,
    }
    target = Path(".scratch/corpus-evidence-pipeline") / f"net-margin-{fingerprint(report)}.json"
    save_artifact(target, json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({
        "report": str(target), "run_id": run.run_id, "source_rev": run.document.source_rev,
        "gold_fields_passed": 20, "formulas_passed": 7,
        "reviews": [{k: row[k] for k in ("period", "source_value", "derived_value", "difference_percentage_points", "status")} for row in reviews],
        "legacy_counts": after,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
