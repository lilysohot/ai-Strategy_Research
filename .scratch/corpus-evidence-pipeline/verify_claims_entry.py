"""Small real-source smoke; new evidence writes only, no model calls or old-row changes."""

import json
from pathlib import Path

from plugins.corpus.evidence import fingerprint
from plugins.corpus.service import CorpusService
from scripts.corpus_evidence_pilot import calculations, field_checks, save_artifact


def counts(service):
    with service._connect() as conn:
        return conn.execute(
            "SELECT (SELECT count(*) FROM documents) AS documents, "
            "(SELECT count(*) FROM blocks) AS blocks, "
            "(SELECT count(*) FROM claims) AS claims, "
            "(SELECT count(*) FROM claims_v2) AS claims_v2"
        ).fetchone()


def main():
    service = CorpusService()
    before = counts(service)
    root = Path("data/corpus")
    manifest = json.loads(Path(".scratch/corpus-evidence-pipeline/pilot_manifest.json").read_text())
    samples = []
    for sample in manifest["samples"]:
        if not sample.get("gold"):
            continue
        paths = list(root.glob(sample["pattern"]))
        assert len(paths) == 1
        run = service.extract_claims(paths[0], pages=tuple(sample["pages"]))
        loaded = service.load_evidence_run(run.run_id)
        checks = field_checks(loaded, sample)
        assert all(check["passed"] for check in checks)
        projection = service.claims_of(
            run_id=run.run_id, purpose="audit", quality_status=None, limit=1000,
        )
        assert projection["total"] == len(loaded.facts)
        assert any(r["run_id"] == run.run_id for r in service.claim_runs(doc_id=run.document.doc_id))
        for row in projection["items"]:
            packet = service.fetch_evidence(run.run_id, row["packet_id"])
            assert row["evidence_quote"] in packet["text"]
        formulas = []
        for result in calculations(loaded) if sample.get("derive") else []:
            assert result["passed"]
            actual = service.derive_claims(
                run_id=run.run_id, formula=result["formula"], input_ids=tuple(result["inputs"]),
            )
            assert actual.model_dump(mode="json")["value"] == result["value"]
            formulas.append(result)
        samples.append({
            "name": sample["name"], "run_id": run.run_id,
            "fields_passed": len(checks), "facts_read": projection["total"],
            "selected_scope_complete": projection["complete"], "formulas": formulas,
        })
    macro_id = "552942996489beb4f1f44b66d2ab944a48b1d5b9ff2e81ef59b6c61c71c65fbf"
    macro = service.claims_of(run_id=macro_id, subject="US", limit=1000)
    targets = [row for row in macro["items"] if row["metric"] == "NFP"
               and row["period_end"] == "2026-08-31"
               and row["qualifiers"].get("state") in {"actual", "consensus"}]
    assert {(row["qualifiers"]["state"], row["value_num"]) for row in targets} == {
        ("actual", "16.2"), ("consensus", "5.6"),
    }
    assert all("calculate" not in row["usable_for"] for row in targets)
    compare = service.claim_observation_projection(run_id=macro_id, subject="US")
    assert compare["total"] == 0
    after = counts(service)
    assert before == after
    report = {
        "status": "passed", "model_calls": 0, "samples": samples,
        "macro_reused_run": macro_id, "macro_targets": len(targets),
        "macro_comparison_rows": compare["total"],
        "legacy_counts_before": before, "legacy_counts_after": after,
    }
    target = Path(".scratch/corpus-evidence-pipeline") / f"claims-entry-{fingerprint(report)}.json"
    save_artifact(target, json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({"report": str(target), **report}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
