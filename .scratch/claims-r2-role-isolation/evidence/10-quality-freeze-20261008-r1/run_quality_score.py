"""Run the signed partial-critical-check diagnostic exactly once."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from enum import Enum
from fractions import Fraction
from pathlib import Path
from typing import Any

from plugins.corpus.structured_scoring import (
    PILOT_CANDIDATE_POLICY,
    CandidateRecord,
    CoverageObservation,
    CoverageOutcome,
    CoverageStage,
    CoverageTarget,
    EvaluationReadiness,
    GoldRecord,
    RecordOrigin,
    ReportConclusion,
    Role,
    score_structured_quality,
)

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
EVIDENCE = HERE.parent
AGGREGATE = EVIDENCE / "11-live-20261008-optimized" / "aggregate.json"
READER = EVIDENCE / "11-live-20261004-r1" / "reader-capture.json"
GOLD = HERE / "critical-check-gold.json"
FREEZE_STATE = HERE / "freeze-state.json"
SCORER = REPO / "plugins" / "corpus" / "structured_scoring.py"
REPORT = HERE / "quality-report.json"
MANIFEST = HERE / "freeze-manifest.json"
SOURCE_ID = "sha256:6f14cc145b798b3716bad47829c05d89d8a5e5955179f11d196ed9b9b8538f11"
STAGES = tuple(CoverageStage)


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _jsonable(value: Any) -> Any:
    if isinstance(value, Fraction):
        return f"{value.numerator}/{value.denominator}"
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    return value


def _rate(value: Fraction | None) -> dict[str, str | float] | None:
    if value is None:
        return None
    return {
        "fraction": f"{value.numerator}/{value.denominator}",
        "decimal": round(float(value), 6),
    }


def _contains(text: str, *needles: str) -> bool:
    return all(needle in text for needle in needles)


def _load_gold(payload: dict[str, Any]) -> tuple[GoldRecord, ...]:
    records = []
    for item in payload["records"]:
        records.append(
            GoldRecord(
                record_id=item["record_id"],
                role=Role(item["role"]),
                source_id=payload["source_id"],
                origin=RecordOrigin(item["origin"]),
                semantic_fields=tuple(tuple(pair) for pair in item["semantic_fields"]),
                critical=item["critical"],
                risk_or_condition=item["risk_or_condition"],
            )
        )
    return tuple(records)


def _checkpoint_results(aggregate: dict[str, Any]) -> dict[str, bool]:
    items = aggregate["items"]
    text_by_id = {item["item_id"]: item.get("text", "") for item in items}
    text = "\n".join(text_by_id.values())
    relations = aggregate["relations"]
    cause_relation = any(
        relation["type"] == "supports"
        and _contains(text_by_id.get(relation["from_item"], ""), "财务公司", "存款")
        and "经营性现金流" in text_by_id.get(relation["to_item"], "")
        for relation in relations
    )
    return {
        "E01-valuation-anchor": _contains(text, "2030", "1341.99", "2026-08-14", "华创证券"),
        "E02-h1-revenue": _contains(text, "26H1", "总收入922.8", "同增1.3%"),
        "E03-h1-profit": _contains(text, "445.2亿元", "同降2.0%"),
        "E04-q2-revenue-profit": _contains(
            text, "单Q2总收入375.8亿元", "同降5.2%", "172.7 亿元", "同降6.9%"
        ),
        "E05-direct-channel": _contains(text, "直销占比", "17.8pcts", "61.1%"),
        "E06-imoutai-and-series": _contains(
            text, "i 茅台收入同增282.6%至187.1 亿", "系列酒营收同降25%"
        ),
        "E07-cashflow-facts": _contains(
            text, "销售回款同增7.9%", "经营性现金流", "同增915.8%", "财务公司", "存款"
        ),
        "E08-eps-forecast": _contains(text, "26-28年EPS预测值", "67.74/70.77/73.84 元", "华创证券"),
        "E09-forecast-table": _contains(
            text, "2025A", "2026E", "2027E", "2028E", "百万元", "每股盈利"
        ),
        "E10-balanced-opinion": _contains(text, "强推", "宏观消费环境未见明显好转"),
        "E10-three-risks": _contains(text, "宏观需求持续疲软", "消费复苏不及预期", "行业竞争加剧"),
        "E12-dividend-interest-composite": _contains(
            text, "股利及利息支付", "2025A", "2026E", "2027E", "2028E"
        ),
        "E07-cashflow-cause-relation": cause_relation,
    }


def _coverage(
    gold: tuple[GoldRecord, ...], results: dict[str, bool]
) -> tuple[tuple[CoverageTarget, ...], tuple[CoverageObservation, ...]]:
    targets = [
        CoverageTarget(
            target_id=item.record_id,
            source_id=SOURCE_ID,
            required_stages=STAGES,
            groups=("moutai_pdf", "partial_critical_checks"),
        )
        for item in gold
    ]
    targets.append(
        CoverageTarget(
            target_id="E11-image-table-gap",
            source_id=SOURCE_ID,
            required_stages=STAGES,
            groups=("moutai_pdf", "partial_critical_checks", "reader_gap"),
        )
    )
    observations: list[CoverageObservation] = []
    out_of_candidate_scope = {
        "E01-valuation-anchor",
        "E09-forecast-table",
        "E12-dividend-interest-composite",
    }
    for item in gold:
        observations.append(
            CoverageObservation(item.record_id, CoverageStage.PARSE, CoverageOutcome.PASS)
        )
        if item.record_id in out_of_candidate_scope:
            for stage in (CoverageStage.PACKET, CoverageStage.ROUTING, CoverageStage.EXTRACTION):
                observations.append(
                    CoverageObservation(
                        item.record_id,
                        stage,
                        CoverageOutcome.MISSED,
                        "excluded_from_candidate_scope",
                    )
                )
            continue
        observations.extend(
            (
                CoverageObservation(item.record_id, CoverageStage.PACKET, CoverageOutcome.PASS),
                CoverageObservation(item.record_id, CoverageStage.ROUTING, CoverageOutcome.PASS),
                CoverageObservation(
                    item.record_id,
                    CoverageStage.EXTRACTION,
                    CoverageOutcome.PASS if results[item.record_id] else CoverageOutcome.INVALID,
                    "" if results[item.record_id] else "required_attribution_missing",
                ),
            )
        )
    observations.extend(
        (
            CoverageObservation(
                "E11-image-table-gap",
                CoverageStage.PARSE,
                CoverageOutcome.FAILED,
                "image_table_values_not_parsed",
            ),
            CoverageObservation(
                "E11-image-table-gap",
                CoverageStage.PACKET,
                CoverageOutcome.MISSED,
                "upstream_parse_gap",
            ),
            CoverageObservation(
                "E11-image-table-gap",
                CoverageStage.ROUTING,
                CoverageOutcome.MISSED,
                "upstream_parse_gap",
            ),
            CoverageObservation(
                "E11-image-table-gap",
                CoverageStage.EXTRACTION,
                CoverageOutcome.MISSED,
                "upstream_parse_gap",
            ),
        )
    )
    return tuple(targets), tuple(observations)


def main() -> None:
    if REPORT.exists() or MANIFEST.exists():
        raise SystemExit("refusing to overwrite immutable score outputs")
    gold_payload = _load(GOLD)
    aggregate = _load(AGGREGATE)
    reader = _load(READER)
    if gold_payload["status"] != "frozen":
        raise SystemExit("gold is not frozen")
    if "股利及利息支付" not in json.dumps(reader, ensure_ascii=False):
        raise SystemExit("reader evidence for E12 is absent")
    gold = _load_gold(gold_payload)
    results = _checkpoint_results(aggregate)
    candidates = tuple(
        CandidateRecord(
            candidate_id=f"candidate:{item.record_id}",
            role=item.role,
            source_id=item.source_id,
            origin=item.origin,
            semantic_fields=item.semantic_fields,
        )
        for item in gold
        if results[item.record_id]
    )
    targets, observations = _coverage(gold, results)
    conclusion = ReportConclusion(
        conclusion_id="moutai_investment_assessment",
        required_record_ids=tuple(item.record_id for item in gold),
        cited_record_ids=(),
        critical=True,
    )
    report = score_structured_quality(
        gold,
        raw_candidates=candidates,
        validated_candidates=candidates,
        coverage_targets=targets,
        coverage_observations=observations,
        conclusions=(conclusion,),
        policy=PILOT_CANDIDATE_POLICY,
        readiness=EvaluationReadiness(
            development_gold_frozen=True,
            gold_frozen_before_candidates=True,
            adjudications_resolved=True,
            thresholds_signed_off=True,
        ),
    )
    output = {
        "schema_version": "corpus-structured-partial-quality-report-v1",
        "evaluation_classification": "seen-development_partial-critical-check_diagnostic",
        "formal_quality_release_eligible": False,
        "precision_limitation": gold_payload["precision_limitation"],
        "checkpoint_results": results,
        "gold_record_count": len(gold),
        "aggregate_item_count": len(aggregate["items"]),
        "aggregate_relation_count": len(aggregate["relations"]),
        "metric_summary": {
            "roles": {
                metrics.role.value: {
                    "tp": metrics.tp,
                    "fp": metrics.fp,
                    "fn": metrics.fn,
                    "precision": _rate(metrics.precision),
                    "recall": _rate(metrics.recall),
                }
                for metrics in report.validated.roles
            },
            "risk_condition_recall": _rate(report.gate.risk_condition_recall),
            "report_support": _rate(report.report_support.rate),
            "coverage": {
                metrics.stage.value: {
                    "passed": metrics.passed,
                    "total": metrics.total,
                    "rate": _rate(metrics.rate),
                }
                for metrics in report.coverage.stages
            },
            "rate_gate_passed": report.gate.rate_gate_passed,
            "live_trial_ready": report.gate.live_trial_ready,
        },
        "scorer_report": _jsonable(asdict(report)),
    }
    REPORT.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest = {
        "schema_version": "corpus-structured-quality-freeze-manifest-v1",
        "created_on": "2026-10-08",
        "exclusive": "x",
        "classification": "seen-development_partial_critical_checks",
        "inputs": {
            str(path.relative_to(REPO)): f"sha256:{_sha256(path)}"
            for path in (GOLD, FREEZE_STATE, AGGREGATE, READER, Path(__file__), SCORER)
        },
        "output": {
            REPORT.name: f"sha256:{_sha256(REPORT)}",
        },
        "formal_quality_release_eligible": False,
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
