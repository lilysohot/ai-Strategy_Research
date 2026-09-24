"""Frozen, bounded holdout evaluation. Never changes extraction rules or legacy rows.

Run with uv run python -m scripts.corpus_holdout_eval --manifest PATH --out PATH.
Exit 1 means business acceptance failed, not necessarily a broken test harness.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from plugins.corpus.claims import build_default_llm, configured_model
from plugins.corpus.evidence import EvidenceDocument, EvidencePacket, content_hash, fingerprint
from plugins.corpus.evidence_pipeline import EvidenceRun, align_quote, extract_evidence
from plugins.corpus.service import CorpusService
from scripts.corpus_evidence_pilot import field_checks, save_artifact


def score_prose(run: EvidenceRun, target: dict[str, Any]) -> dict[str, Any]:
    """Separate retrieval from typed, unique, evidence-bound usability."""
    found = []
    for fact in run.facts:
        claim = fact.claim
        quote = claim.evidence_quote or ""
        compact = re.sub(r"\s+", "", quote)
        if (
            claim.value_num == Decimal(target["number"])
            and all(term in compact for term in target["quote_terms"])
            and align_quote(quote, run.document.fetch(fact.packet_id).text)
        ):
            found.append(fact)
    exact = [
        fact
        for fact in found
        if fact.claim.subject == target["subject"]
        and fact.claim.metric in target["metrics"]
        and fact.claim.unit in target["units"]
        and fact.claim.qualifiers.get("state") == target["state"]
        and (target["basis"] is None or fact.claim.qualifiers.get("basis") == target["basis"])
        and fact.claim.period_end == target["period_end"]
        and fact.claim.quality_status == "review"
        and "calculate" not in fact.usable_for
    ]
    return {
        "target": target,
        "retrieved": bool(found),
        "coordinate_pass": len(found) == len(exact) == 1,
        "matches": [fact.model_dump(mode="json") for fact in found],
    }


def negative_checks(run: EvidenceRun, rules: list[str]) -> list[dict[str, Any]]:
    results = []
    nfp = [
        fact
        for fact in run.facts
        if "非农"
        in " ".join(
            (fact.claim.evidence_quote or "", fact.claim.claim_text, fact.claim.metric or "")
        )
        or fact.claim.metric == "NFP"
    ]
    for rule in rules:
        if rule == "no_calculate":
            wrong = [f for f in nfp if "calculate" in f.usable_for]
        elif rule == "no_inferred_year":
            wrong = [f for f in nfp if f.claim.period_end is not None]
        elif rule == "revision_not_previous":
            wrong = [
                f
                for f in nfp
                if f.claim.value_num == Decimal("5.5")
                and f.claim.qualifiers.get("state") == "previous"
            ]
        elif rule == "no_borrowed_actual_consensus":
            wrong = [f for f in nfp if f.claim.value_num in {Decimal("16.2"), Decimal("5.6")}]
        else:
            raise ValueError(f"Unknown negative rule: {rule}")
        results.append(
            {
                "rule": rule,
                "passed": not wrong,
                "observed_nfp_facts": len(nfp),
                "vacuous": not nfp,
                "wrong_fact_ids": [f.fact_id for f in wrong],
            }
        )
    return results


def synthetic_probes() -> list[dict[str, Any]]:
    """Known adversarial cases are regressions, NOT independent holdout observations."""
    base = {
        "claim_text": "2026E营业收入100元",
        "evidence_quote": "2026E营业收入100元",
        "scope": "company",
        "subject": "600519.SH",
        "metric": "营业收入",
        "value_text": "100元",
        "period_raw": "2026E",
        "kind": "forecast",
    }
    cases = [
        ("valid_control", "2026E营业收入100元", [base], True),
        (
            "wrong_period",
            "2025A营业收入100元。2026E营业收入120元。",
            [{**base, "evidence_quote": "2025A营业收入100元"}],
            False,
        ),
        (
            "wrong_metric_value",
            "2026E营业收入100元，净利润20元。",
            [
                {
                    **base,
                    "claim_text": "2026E营业收入20元",
                    "value_text": "20元",
                    "evidence_quote": "2026E营业收入100元，净利润20元。",
                }
            ],
            False,
        ),
        ("fabricated_known_at", "2026E营业收入100元", [{**base, "known_at": "1990-01-01"}], False),
        ("forecast_as_fact", "2026E营业收入100元", [{**base, "kind": "fact"}], False),
        ("duplicate_identity", "2026E营业收入100元", [base, {**base, "kind": "fact"}], False),
    ]
    results = []
    for name, source, payload, allow in cases:
        packet = EvidencePacket(packet_id="p", locator="1", kind="prose", text=source)
        document = EvidenceDocument(
            doc_id="synthetic",
            title="600519.SH财务预测",
            source_path="synthetic",
            source_rev=fingerprint(source),
            parse_rev=fingerprint(source),
            parser_version="probe-1",
            subject="600519.SH",
            published="2026-09-01",
            pages=(),
            packets=(packet,),
        )
        run = extract_evidence(
            document,
            llm=lambda _, items=payload: json.dumps(items, ensure_ascii=False),
            model="frozen-synthetic",
            max_prose_calls=1,
        )
        allowed = any("calculate" in f.usable_for for f in run.facts)
        unique = len({f.fact_id for f in run.facts}) == len(run.facts)
        passed = (allowed == allow) and (unique or not allowed)
        results.append(
            {
                "name": name,
                "expected_calculate": allow,
                "passed": passed,
                "actual_calculate": allowed,
                "unique_identity": unique,
                "facts": [f.model_dump(mode="json") for f in run.facts],
            }
        )
    return results


def code_hashes() -> dict[str, str]:
    paths = [
        *Path("plugins/corpus").glob("*.py"),
        Path(__file__),
        Path("scripts/corpus_evidence_pilot.py"),
    ]
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=Path("data/corpus"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--replay-report",
        type=Path,
        help="Rescore saved runs only; no model calls or database writes",
    )
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    args.out.mkdir(parents=True, exist_ok=True)
    if args.replay_report:
        previous = json.loads(args.replay_report.read_text(encoding="utf-8"))
        if previous["manifest_hash"] != fingerprint(manifest):
            raise ValueError("Cannot rescore a different gold manifest")
        for sample, result in zip(manifest["samples"], previous["samples"], strict=True):
            run = EvidenceRun.model_validate_json(
                (args.replay_report.parent / f"{result['run_id']}.json").read_text(encoding="utf-8")
            )
            run.verify_identity()
            if run.document.source_rev != sample["source_rev"]:
                raise ValueError("Replay source mismatch")
            result["negative_checks"] = negative_checks(run, sample.get("negative_rules", []))
        previous["rescore"] = {
            "parent_report": args.replay_report.name,
            "code_hashes": code_hashes(),
            "model_calls": 0,
            "reason": "Include claim text and metric in NFP negative scope; gold unchanged",
        }
        previous["business_acceptance"] = (
            all(c["passed"] for r in previous["samples"] for c in r["table_checks"])
            and all(c["coordinate_pass"] for r in previous["samples"] for c in r["prose_checks"])
            and all(c["passed"] for r in previous["samples"] for c in r["negative_checks"])
            and all(c["passed"] for c in previous["synthetic_probes"])
        )
        target = args.out / f"report-{fingerprint(previous)}.json"
        save_artifact(target, json.dumps(previous, ensure_ascii=False, indent=2))
        print(f"Rescored report: {target}")
        return int(not previous["business_acceptance"])
    frozen = {
        "manifest": manifest,
        "manifest_hash": fingerprint(manifest),
        "code_hashes": code_hashes(),
        "started_at": datetime.now(UTC).isoformat(),
    }
    # Freeze all resolved source identities BEFORE any model request.
    paths = []
    for sample in manifest["samples"]:
        matches = list(args.root.glob(sample["pattern"]))
        if len(matches) != 1 or content_hash(matches[0]) != sample["source_rev"]:
            raise ValueError(f"Source identity mismatch: {sample['name']}")
        paths.append(matches[0])
    save_artifact(
        args.out / f"freeze-{fingerprint(frozen)}.json",
        json.dumps(frozen, ensure_ascii=False, indent=2),
    )
    load_dotenv(".env")
    os.environ["CORPUS_LLM_TIMEOUT"] = str(manifest["limits"]["timeout_seconds"])
    usage: dict[str, int] = {}
    llm = build_default_llm(usage)
    service = CorpusService()
    results = []
    for sample, path in zip(manifest["samples"], paths, strict=True):
        print(f"Running {sample['name']}", flush=True)
        use_model = sample.get("model_extract", False)
        run = service.extract_claims(
            path,
            pages=tuple(sample["pages"]),
            llm=llm if use_model else None,
            model=configured_model() if use_model else None,
            max_prose_calls=manifest["limits"]["prose_calls_per_macro_document"]
            if use_model
            else 0,
            packet_chars=manifest["limits"]["packet_chars"],
            # I4-5 retired corpus_evidence_runs.  Holdout evidence is frozen in
            # the content-addressed artifact immediately below.
            persist=False,
        )
        run.verify_identity()
        save_artifact(args.out / f"{run.run_id}.json", run.model_dump_json(indent=2))
        restored = EvidenceRun.model_validate_json(
            (args.out / f"{run.run_id}.json").read_text(encoding="utf-8")
        )
        restored.verify_identity()
        assert len(restored.facts) == len(run.facts)
        for packet in restored.document.packets:
            assert restored.document.fetch(packet.packet_id).packet_id == packet.packet_id
        result = {
            "name": sample["name"],
            "source_path": str(path),
            "source_rev": run.document.source_rev,
            **run.summary(),
            "artifact_reloaded_audited": True,
            "table_checks": field_checks(restored, sample),
            "prose_checks": [score_prose(restored, g) for g in sample.get("targets", [])],
            "negative_checks": negative_checks(restored, sample.get("negative_rules", [])),
        }
        results.append(result)
        print(json.dumps(run.summary(), ensure_ascii=False), flush=True)
    probes = synthetic_probes()
    overall = all(c["passed"] for r in results for c in r["table_checks"])
    overall &= all(c["coordinate_pass"] for r in results for c in r["prose_checks"])
    overall &= all(c["passed"] for r in results for c in r["negative_checks"])
    overall &= all(c["passed"] for c in probes)
    report = {
        **frozen,
        "finished_at": datetime.now(UTC).isoformat(),
        "samples": results,
        "synthetic_probes": probes,
        "usage": usage,
        "business_acceptance": overall,
        "limitations": [
            "Not population accuracy; only frozen targets are annotated",
            "Synthetic probes are known regressions, not new holdout data",
            "No production macro calculator is enabled",
            "Source publication authenticity not independently verified",
        ],
    }
    target = args.out / f"report-{fingerprint(report)}.json"
    save_artifact(target, json.dumps(report, ensure_ascii=False, indent=2))
    print(f"Report: {target}", flush=True)
    return int(not overall)


if __name__ == "__main__":
    raise SystemExit(main())
