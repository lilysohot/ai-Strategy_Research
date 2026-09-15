"""Replay frozen financial targets through the updated canonical chain; no model calls."""

import json
from pathlib import Path

from plugins.corpus.evidence import fingerprint
from plugins.corpus.service import CorpusService
from scripts.corpus_evidence_pilot import calculations, field_checks, save_artifact
from scripts.corpus_holdout_eval import code_hashes, synthetic_probes


def legacy_counts(service):
    with service._connect() as conn:
        return conn.execute(
            "SELECT (SELECT count(*) FROM documents) documents, "
            "(SELECT count(*) FROM blocks) blocks, "
            "(SELECT count(*) FROM claims) claims, "
            "(SELECT count(*) FROM claims_v2) claims_v2"
        ).fetchone()


def main():
    service = CorpusService()
    before = legacy_counts(service)
    manifest = json.loads(Path(".scratch/corpus-evidence-pipeline/pilot_manifest.json").read_text())
    samples = []
    for sample in manifest["samples"][:3]:
        path = next(Path("data/corpus").glob(sample["pattern"]))
        run = service.extract_claims(path, pages=tuple(sample["pages"]), max_prose_calls=0)
        restored = service.load_evidence_run(run.run_id)
        restored.verify_identity()
        checks = field_checks(restored, sample)
        formulas = calculations(restored) if sample.get("derive") else []
        assert all(c["passed"] for c in checks)
        assert all(c["passed"] for c in formulas)
        samples.append({"name": sample["name"], "run_id": run.run_id,
                        "fields_passed": len(checks), "formulas": formulas,
                        "pipeline_version": run.pipeline_version})
    customer = json.loads(Path(
        ".scratch/corpus-evidence-pipeline/expanded_holdout_manifest.json"
    ).read_text())["samples"][0]
    path = next(Path("data/corpus").glob(customer["pattern"]))
    customer_run = service.extract_claims(path, pages=(4,), max_prose_calls=0)
    customer_checks = field_checks(customer_run, customer)
    assert len(customer_checks) == 12 and all(c["passed"] for c in customer_checks)
    assert service.load_evidence_run(customer_run.run_id) == customer_run
    assert all("calculate" not in f.usable_for for f in customer_run.facts)
    for packet in customer_run.document.packets:
        assert service.fetch_evidence(customer_run.run_id, packet.packet_id)
    after = legacy_counts(service)
    assert before == after
    probes = synthetic_probes()
    assert all(p["passed"] for p in probes)
    report = {"model_calls": 0, "financial_samples": samples, "synthetic_probes": probes,
              "customer_run_id": customer_run.run_id, "customer_checks": customer_checks,
              "legacy_counts_before": before, "legacy_counts_after": after,
              "code_hashes": code_hashes()}
    target = Path(".scratch/corpus-evidence-pipeline/semantic-repair-runs") / f"financial-{fingerprint(report)}.json"
    save_artifact(target, json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({"report": str(target), "fields": sum(s["fields_passed"] for s in samples),
                      "formulas": sum(len(s["formulas"]) for s in samples),
                      "adverse_passed": len(probes)-1, "customer_cells": len(customer_checks),
                      "customer_run_id": customer_run.run_id, "legacy_counts": after}, ensure_ascii=False))


if __name__ == "__main__":
    main()
