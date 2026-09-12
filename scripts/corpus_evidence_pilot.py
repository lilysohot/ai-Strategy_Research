"""Small, reproducible corpus usability pilot; writes only shadow runs and local artifacts.

uv run python scripts/corpus_evidence_pilot.py --manifest .scratch/corpus-evidence-pipeline/pilot_manifest.json --out data/corpus/.evidence/pilot --persist --prose-calls 2
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from decimal import Decimal
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from plugins.corpus.claims import build_default_llm, configured_model
from plugins.corpus.derivation import derive, reconcile_net_margin
from plugins.corpus.evidence import fingerprint
from plugins.corpus.evidence_pipeline import EvidenceRun
from plugins.corpus.service import CorpusService


def save_artifact(target: Path, content: str) -> None:
    """Publish a complete file atomically, never replacing an existing revision."""
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=target.parent, delete=False
    ) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        os.link(temporary, target)
    except FileExistsError:
        if target.read_text(encoding="utf-8") != content:
            raise ValueError("existing artifact differs from expected content") from None
    finally:
        temporary.unlink(missing_ok=True)


def field_checks(run: EvidenceRun, sample: dict[str, Any]) -> list[dict[str, object]]:
    checks = []
    for row in sample.get("gold", []):
        for column, expected in zip(row["columns"], row["values"], strict=True):
            candidates = [
                c
                for p in run.document.packets
                for c in p.cells
                if c.row == row["row"] and c.column == column
            ]
            exact = [c for c in candidates if c.value == expected and c.unit == row["unit"]]
            checks.append(
                {
                    "row": row["row"],
                    "column": column,
                    "expected": expected,
                    "unit": row["unit"],
                    "passed": len(candidates) == len(exact) == 1,
                    "actual": [{"value": c.value, "unit": c.unit} for c in candidates],
                }
            )
    return checks


def calculations(run: EvidenceRun) -> list[dict[str, object]]:
    # Independently evaluated from frozen source cells, not from extraction output.
    expected = {
        "revenue_growth": "3.837749",
        "parent_profit_growth": "2.865646",
        "operating_cash_growth": "-58.135301",
        "cash_profit_ratio": "30.416042",
        "net_margin": "49.167399",
        "balance_residual": "0",
        "profit_residual": "0",
    }

    def one(metric: str, period: str) -> str:
        found = [
            f
            for f in run.facts
            if f.metric_id == metric
            and f.claim.period_raw == period
            and "calculate" in f.usable_for
        ]
        if len(found) != 1:
            raise ValueError(f"expected one usable {metric}/{period}, got {len(found)}")
        return found[0].fact_id

    recipes = [
        ("revenue_growth", (("revenue", "2026E"), ("revenue", "2025A"))),
        ("parent_profit_growth", (("parent_net_profit", "2026E"), ("parent_net_profit", "2025A"))),
        (
            "operating_cash_growth",
            (("operating_cash_flow", "2026E"), ("operating_cash_flow", "2025A")),
        ),
        ("cash_profit_ratio", (("operating_cash_flow", "2026E"), ("parent_net_profit", "2026E"))),
        ("net_margin", (("net_profit", "2026E"), ("revenue", "2026E"))),
        ("balance_residual", (("assets", "2026E"), ("liabilities", "2026E"), ("equity", "2026E"))),
        (
            "profit_residual",
            (("net_profit", "2026E"), ("parent_net_profit", "2026E"), ("minority_profit", "2026E")),
        ),
    ]
    results = []
    for formula, inputs in recipes:
        try:
            result = derive(run, formula, tuple(one(*item) for item in inputs))
            tolerance = Decimal("0") if formula.endswith("_residual") else Decimal("0.000001")
            results.append(
                {
                    "passed": abs(result.value - Decimal(expected[formula])) <= tolerance,
                    "expected": expected[formula],
                    "tolerance": str(tolerance),
                    **result.model_dump(mode="json"),
                }
            )
        except ValueError as exc:
            results.append({"passed": False, "formula": formula, "reason": str(exc)})
    return results


def reconciliation(run: EvidenceRun) -> list[dict[str, object]]:
    """Use the same all-period review as the service; never rewrite the source ratio."""
    return reconcile_net_margin(run)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=Path("data/corpus"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--persist", action="store_true")
    parser.add_argument("--prose-calls", type=int, default=0)
    parser.add_argument("--packet-chars", type=int, default=2000)
    args = parser.parse_args()
    load_dotenv(".env")
    os.environ.setdefault("CORPUS_LLM_TIMEOUT", "60")
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    args.out.mkdir(parents=True, exist_ok=True)
    usage: dict[str, int] = {}
    llm = build_default_llm(usage) if args.prose_calls else None
    results = []
    service = CorpusService()
    for sample in manifest["samples"]:
        paths = list(args.root.glob(sample["pattern"]))
        if len(paths) != 1:
            raise ValueError(f"sample {sample['name']} must resolve to exactly one file")
        print(f"Running {sample['name']} ...", flush=True)
        use_model = sample.get("model_extract", False)
        run = service.extract_claims(
            paths[0],
            pages=tuple(sample["pages"]),
            llm=llm if use_model else None,
            model=configured_model() if use_model and llm else None,
            max_prose_calls=args.prose_calls if use_model else 0,
            packet_chars=args.packet_chars,
            persist=args.persist,
        )
        run.verify_identity()
        # Content-addressed artifacts never overwrite an earlier different result.
        target = args.out / f"{run.run_id}.json"
        serialized = run.model_dump_json(indent=2)
        save_artifact(target, serialized)
        restored = EvidenceRun.model_validate_json(target.read_text(encoding="utf-8"))
        restored.verify_identity()
        persisted = False
        if args.persist:
            restored = service.load_evidence_run(run.run_id)
            assert service.fetch_evidence(run.run_id, run.document.packets[0].packet_id)
            projection = service.claims_of(
                run_id=run.run_id,
                purpose="audit",
                quality_status=None,
                limit=1000,
            )
            assert projection["total"] == len(run.facts)
            persisted = True
        checks = field_checks(restored, sample)
        prose_checks = []
        for gold in sample.get("prose_gold", []):
            found = [
                f
                for f in run.facts
                if f.claim.subject == gold["subject"]
                and f.claim.metric == gold["metric"]
                and f.claim.period_end == gold["period_end"]
                and str(f.claim.value_num) == gold["value_num"]
                and f.claim.unit == gold["unit"]
                and f.claim.qualifiers.get("state") == gold["state"]
                and f.claim.quality_status == gold.get("quality_status", "ok")
                and (gold["period_end"] is None or "period_not_in_packet" not in f.reasons)
                and all(reason in f.reasons for reason in gold.get("required_reasons", []))
                and (not gold.get("must_not_calculate") or "calculate" not in f.usable_for)
                and f.claim.evidence_quote is not None
                and f.claim.evidence_quote in run.document.fetch(f.packet_id).text
            ]
            prose_checks.append(
                {
                    "expected": gold,
                    "passed": bool(found),
                    "usable_for": [list(f.usable_for) for f in found],
                    "fact_ids": [f.fact_id for f in found],
                }
            )
        result = {
            "name": sample["name"],
            "role": sample["role"],
            **run.summary(),
            "source_rev": run.document.source_rev,
            "parse_rev": run.document.parse_rev,
            "persisted_and_reloaded": persisted,
            "field_checks": checks,
            "field_passed": sum(bool(c["passed"]) for c in checks),
            "field_total": len(checks),
            "prose_checks": prose_checks,
            "calculations": calculations(restored) if sample.get("derive") else [],
            "reconciliation": reconciliation(restored) if sample.get("derive") else [],
            "negative_control_passed": any(p.status == "unknown" for p in run.document.packets)
            if sample.get("expect_unknown")
            else None,
        }
        results.append(result)
        print(
            json.dumps(
                {
                    k: result[k]
                    for k in ("name", "facts", "field_passed", "field_total", "calculation_ready")
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
    table_gate = all(
        r["field_passed"] == r["field_total"]
        and all(c["passed"] for c in r["calculations"])
        and r["negative_control_passed"] is not False
        for r in results
    )
    prose_gate = all(c["passed"] for r in results for c in r["prose_checks"])
    report = {
        "manifest_hash": fingerprint(manifest),
        "samples": results,
        "usage": usage,
        "table_gate_pass": table_gate,
        "prose_gate_pass": prose_gate,
        "overall_pass": table_gate and prose_gate,
        "execution": {
            "prose_calls_per_document": args.prose_calls,
            "packet_chars": args.packet_chars,
            "output_token_limit": os.getenv("CORPUS_LLM_MAX_TOKENS", "4096"),
            "timeout_seconds": os.getenv("CORPUS_LLM_TIMEOUT"),
            "reasoning_effort_override": os.getenv("CORPUS_LLM_REASONING_EFFORT"),
        },
        "limitations": [
            "small nonrandom sample",
            "deferred prose is not complete extraction",
            "field checks measure selected cells, not all extracted cells",
            "source publication authenticity not independently verified",
        ],
    }
    report_id = fingerprint(report)
    report_path = args.out / f"report-{report_id}.json"
    save_artifact(report_path, json.dumps(report, ensure_ascii=False, indent=2))
    print(f"Report: {report_path}")
    return int(not (table_gate and prose_gate))


if __name__ == "__main__":
    raise SystemExit(main())
