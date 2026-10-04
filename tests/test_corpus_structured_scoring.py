"""Task 10: deterministic scoring for synthetic Claims/R2 quality gates."""

from __future__ import annotations

import hashlib
import json
from fractions import Fraction
from pathlib import Path

import pytest

from plugins.corpus.structured_scoring import (
    PILOT_CANDIDATE_POLICY,
    CandidateRecord,
    CoverageObservation,
    CoverageOutcome,
    CoverageStage,
    CoverageTarget,
    EvaluationReadiness,
    GoldRecord,
    QualityPolicy,
    RecordOrigin,
    ReportConclusion,
    Role,
    ScoringInputError,
    score_structured_quality,
)

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "corpus_structured_scoring"
COUNTEREXAMPLES = json.loads(
    (FIXTURE_ROOT / "gold-and-counterexamples.json").read_text(encoding="utf-8")
)


def _gold(record_id: str, role: Role, key: str) -> GoldRecord:
    return GoldRecord(
        record_id=record_id,
        role=role,
        source_id="synthetic-source",
        origin=RecordOrigin.LLM_PROSE,
        semantic_fields=(("key", key),),
    )


def _candidate(candidate_id: str, role: Role, key: str) -> CandidateRecord:
    return CandidateRecord(
        candidate_id=candidate_id,
        role=role,
        source_id="synthetic-source",
        origin=RecordOrigin.LLM_PROSE,
        semantic_fields=(("key", key),),
    )


def _fixture_gold(row: dict[str, object]) -> GoldRecord:
    fields = row["semantic_fields"]
    assert isinstance(fields, dict)
    return GoldRecord(
        record_id=str(row["record_id"]),
        role=Role(str(row["role"])),
        source_id=str(row["source_id"]),
        origin=RecordOrigin(str(row["origin"])),
        semantic_fields=tuple(sorted((str(key), str(value)) for key, value in fields.items())),
        critical=bool(row.get("critical", False)),
        risk_or_condition=bool(row.get("risk_or_condition", False)),
    )


def _fixture_candidate(row: dict[str, object]) -> CandidateRecord:
    fields = row["semantic_fields"]
    assert isinstance(fields, dict)
    error_code = row.get("critical_error_code")
    return CandidateRecord(
        candidate_id=str(row["candidate_id"]),
        role=Role(str(row["role"])),
        source_id=str(row["source_id"]),
        origin=RecordOrigin(str(row["origin"])),
        semantic_fields=tuple(sorted((str(key), str(value)) for key, value in fields.items())),
        critical_error_code=str(error_code) if error_code is not None else None,
    )


def test_scoring_assets_are_synthetic_frozen_and_hash_locked() -> None:
    manifest_path = FIXTURE_ROOT / "asset-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["synthetic_only"] is True
    assert manifest["real_source_ids"] == []
    assert manifest["candidate_outputs_observed_before_freeze"] is False
    source_manifest = manifest["source_fixture_manifest"]
    source_path = (FIXTURE_ROOT / source_manifest["path"]).resolve()
    assert hashlib.sha256(source_path.read_bytes()).hexdigest() == source_manifest["sha256"]
    assert {item["path"] for item in manifest["assets"]} == {
        "adjudications.json",
        "gold-and-counterexamples.json",
        "scoring-definition.json",
    }
    for item in manifest["assets"]:
        assert (
            hashlib.sha256((FIXTURE_ROOT / item["path"]).read_bytes()).hexdigest() == item["sha256"]
        )

    observed_tags = {item["coverage_tag"] for item in COUNTEREXAMPLES["counterexamples"]}
    assert observed_tags == set(manifest["required_counterexample_tags"])
    adjudications = json.loads((FIXTURE_ROOT / "adjudications.json").read_text(encoding="utf-8"))
    assert adjudications["development_scope"]["status"] == "not_authorized"
    assert adjudications["development_scope"]["real_source_ids"] == []
    assert adjudications["development_scope"]["research_questions"] == []
    assert adjudications["holdout_accessed"] is False


@pytest.mark.parametrize(
    "case",
    COUNTEREXAMPLES["counterexamples"],
    ids=lambda case: case["case_id"],
)
def test_frozen_counterexample_is_scored_as_expected(case: dict[str, object]) -> None:
    gold_by_id = {row["record_id"]: _fixture_gold(row) for row in COUNTEREXAMPLES["gold_records"]}
    gold = tuple(gold_by_id[record_id] for record_id in case["gold_ids"])
    candidates = tuple(_fixture_candidate(row) for row in case["candidates"])

    report = score_structured_quality(
        gold, raw_candidates=candidates, validated_candidates=candidates
    )

    role = gold[0].role
    metrics = report.raw.role(role)
    assert metrics.fp == case["expected_fp"]
    assert metrics.fn == case["expected_fn"]
    assert metrics.duplicate_fp == case.get("expected_duplicate_fp", 0)


def test_role_matching_counts_duplicates_as_fp_and_routing_omissions_as_fn() -> None:
    gold = (
        _gold("claim-1", Role.CLAIMS, "revenue-2026"),
        _gold("item-1", Role.MATERIAL_ITEMS, "conditional-view"),
        _gold("relation-1", Role.MATERIAL_RELATIONS, "supports:item-1:item-2"),
    )
    raw = (
        _candidate("c1", Role.CLAIMS, "revenue-2026"),
        _candidate("c1-duplicate", Role.CLAIMS, "revenue-2026"),
        _candidate("i1", Role.MATERIAL_ITEMS, "conditional-view"),
    )

    report = score_structured_quality(gold, raw_candidates=raw, validated_candidates=raw)

    claims = report.raw.role(Role.CLAIMS)
    assert (claims.tp, claims.fp, claims.fn) == (1, 1, 0)
    assert claims.precision == Fraction(1, 2)
    assert claims.recall == 1
    assert claims.duplicate_fp == 1
    assert (
        report.raw.role(Role.MATERIAL_RELATIONS).tp,
        report.raw.role(Role.MATERIAL_RELATIONS).fn,
    ) == (0, 1)
    assert "relation-1" in report.raw.missing_gold_ids
    assert report.unique_supported_sources == ("synthetic-source",)


def test_repeated_false_positive_is_classified_as_duplicate_without_hiding_either_fp() -> None:
    gold = (_gold("claim-1", Role.CLAIMS, "revenue-2026"),)
    repeated_hallucination = (
        _candidate("wrong-1", Role.CLAIMS, "revenue-2027"),
        _candidate("wrong-2", Role.CLAIMS, "revenue-2027"),
    )

    report = score_structured_quality(
        gold,
        raw_candidates=repeated_hallucination,
        validated_candidates=repeated_hallucination,
    )

    claims = report.raw.role(Role.CLAIMS)
    assert (claims.tp, claims.fp, claims.fn) == (0, 2, 1)
    assert claims.duplicate_fp == 1


def test_raw_and_validated_scores_keep_table_and_llm_claims_separate() -> None:
    table_gold = GoldRecord(
        "claim-table",
        Role.CLAIMS,
        "synthetic-source",
        RecordOrigin.DETERMINISTIC_TABLE,
        (("key", "table-revenue"),),
    )
    prose_gold = _gold("claim-prose", Role.CLAIMS, "prose-revenue")
    table = CandidateRecord(
        "table-ok",
        Role.CLAIMS,
        "synthetic-source",
        RecordOrigin.DETERMINISTIC_TABLE,
        (("key", "table-revenue"),),
    )
    wrong_prose = _candidate("prose-wrong", Role.CLAIMS, "wrong-year")

    report = score_structured_quality(
        (table_gold, prose_gold),
        raw_candidates=(table, wrong_prose),
        validated_candidates=(table,),
    )

    assert (
        report.raw.role(Role.CLAIMS).tp,
        report.raw.role(Role.CLAIMS).fp,
        report.raw.role(Role.CLAIMS).fn,
    ) == (1, 1, 1)
    assert (
        report.validated.role(Role.CLAIMS).tp,
        report.validated.role(Role.CLAIMS).fp,
        report.validated.role(Role.CLAIMS).fn,
    ) == (1, 0, 1)
    assert report.validated.role_origin(Role.CLAIMS, RecordOrigin.DETERMINISTIC_TABLE).recall == 1
    prose = report.validated.role_origin(Role.CLAIMS, RecordOrigin.LLM_PROSE)
    assert prose.precision is None
    assert prose.recall == 0


def test_coverage_failures_keep_denominators_and_background_extraction_cannot_support_report() -> (
    None
):
    gold = (_gold("claim-1", Role.CLAIMS, "conditional-revenue"),)
    candidate = _candidate("c1", Role.CLAIMS, "conditional-revenue")
    target = CoverageTarget(
        "claim-1",
        "synthetic-source",
        tuple(CoverageStage),
    )
    observations = (
        *(
            CoverageObservation("claim-1", stage, CoverageOutcome.PASS)
            for stage in (
                CoverageStage.PARSE,
                CoverageStage.PACKET,
                CoverageStage.ROUTING,
                CoverageStage.EXTRACTION,
                CoverageStage.QUERY,
            )
        ),
        CoverageObservation(
            "claim-1",
            CoverageStage.DELIVERY,
            CoverageOutcome.MISSED,
            "condition_not_in_actual_model_message",
        ),
        # CONTEXT_USE is deliberately absent: missing observation must remain in its denominator.
    )
    report = score_structured_quality(
        gold,
        raw_candidates=(candidate,),
        validated_candidates=(candidate,),
        coverage_targets=(target,),
        coverage_observations=observations,
        conclusions=(ReportConclusion("C1", ("claim-1",), ("claim-1",), critical=True),),
    )

    assert report.coverage.stage(CoverageStage.EXTRACTION).rate == 1
    assert report.coverage.stage(CoverageStage.DELIVERY).rate == 0
    assert report.coverage.stage(CoverageStage.CONTEXT_USE).rate == 0
    assert (
        "claim-1:missing_observation" in report.coverage.stage(CoverageStage.CONTEXT_USE).failures
    )
    assert report.report_support.rate == 0
    assert report.report_support.critical_failures == ("C1",)


def test_coverage_reports_micro_and_per_document_macro_rates() -> None:
    targets = (
        CoverageTarget("a-1", "source-a", (CoverageStage.PARSE,)),
        CoverageTarget("a-2", "source-a", (CoverageStage.PARSE,)),
        CoverageTarget("a-3", "source-a", (CoverageStage.PARSE,)),
        CoverageTarget("b-1", "source-b", (CoverageStage.PARSE,)),
    )
    observations = (
        CoverageObservation("a-1", CoverageStage.PARSE, CoverageOutcome.PASS),
        CoverageObservation("a-2", CoverageStage.PARSE, CoverageOutcome.PASS),
        CoverageObservation("a-3", CoverageStage.PARSE, CoverageOutcome.PASS),
        CoverageObservation("b-1", CoverageStage.PARSE, CoverageOutcome.FAILED),
    )

    report = score_structured_quality(
        (),
        raw_candidates=(),
        validated_candidates=(),
        coverage_targets=targets,
        coverage_observations=observations,
    )

    parse = report.coverage.stage(CoverageStage.PARSE)
    assert parse.rate == Fraction(3, 4)  # micro: all targets
    assert parse.macro_rate == Fraction(1, 2)  # macro: mean of source rates 1 and 0
    assert tuple((item.source_id, item.rate) for item in parse.sources) == (
        ("source-a", Fraction(1, 1)),
        ("source-b", Fraction(0, 1)),
    )


def test_coverage_keeps_frozen_family_and_channel_groups() -> None:
    targets = (
        CoverageTarget(
            "company-table",
            "source-a",
            (CoverageStage.PARSE,),
            groups=("family:company", "channel:table"),
        ),
        CoverageTarget(
            "industry-body",
            "source-b",
            (CoverageStage.PARSE,),
            groups=("family:industry", "channel:body"),
        ),
    )
    observations = (
        CoverageObservation("company-table", CoverageStage.PARSE, CoverageOutcome.PASS),
        CoverageObservation("industry-body", CoverageStage.PARSE, CoverageOutcome.FAILED),
    )

    report = score_structured_quality(
        (),
        raw_candidates=(),
        validated_candidates=(),
        coverage_targets=targets,
        coverage_observations=observations,
    )

    parse = report.coverage.stage(CoverageStage.PARSE)
    assert parse.group("family:company").rate == 1
    assert parse.group("family:industry").rate == 0
    assert parse.group("channel:table").macro_rate == 1
    assert parse.group("channel:body").macro_rate == 0


@pytest.mark.parametrize(
    "outcome",
    (CoverageOutcome.EMPTY, CoverageOutcome.INVALID, CoverageOutcome.FAILED),
)
def test_empty_invalid_and_failed_observations_remain_in_denominator(
    outcome: CoverageOutcome,
) -> None:
    target = CoverageTarget("g-1", "source-a", (CoverageStage.EXTRACTION,))
    report = score_structured_quality(
        (),
        raw_candidates=(),
        validated_candidates=(),
        coverage_targets=(target,),
        coverage_observations=(CoverageObservation("g-1", CoverageStage.EXTRACTION, outcome),),
    )

    extraction = report.coverage.stage(CoverageStage.EXTRACTION)
    assert (extraction.passed, extraction.total, extraction.rate) == (0, 1, 0)
    assert extraction.failures == (f"g-1:{outcome}",)


def test_zero_denominators_are_undefined_and_cannot_pass_gate() -> None:
    report = score_structured_quality((), raw_candidates=(), validated_candidates=())

    for role in Role:
        assert report.validated.role(role).precision is None
        assert report.validated.role(role).recall is None
        assert f"zero_denominator:{role}:precision" in report.gate.rate_blockers
        assert f"zero_denominator:{role}:recall" in report.gate.rate_blockers
    assert report.gate.risk_condition_recall is None
    assert "zero_denominator:risk_or_condition" in report.gate.rate_blockers
    assert "zero_denominator:report_support" in report.gate.rate_blockers
    assert report.gate.live_trial_ready is False


def test_validated_candidates_must_be_an_unchanged_subset_of_raw() -> None:
    candidate = _candidate("candidate-1", Role.CLAIMS, "one")
    changed = _candidate("candidate-1", Role.CLAIMS, "changed-after-validation")

    with pytest.raises(ScoringInputError, match="unchanged raw candidate"):
        score_structured_quality((), raw_candidates=(candidate,), validated_candidates=(changed,))


def test_gold_semantic_identities_must_be_unique_for_one_to_one_matching() -> None:
    duplicate_gold = (
        _gold("gold-1", Role.CLAIMS, "same-identity"),
        _gold("gold-2", Role.CLAIMS, "same-identity"),
    )

    with pytest.raises(ScoringInputError, match="duplicate gold semantic identity"):
        score_structured_quality(duplicate_gold, raw_candidates=(), validated_candidates=())


def _perfect_three_role_run(*, critical_error: str | None = None, min_sample: int = 1):
    gold = (
        GoldRecord(
            "g-claim",
            Role.CLAIMS,
            "one-source",
            RecordOrigin.LLM_PROSE,
            (("key", "claim"),),
            critical=True,
        ),
        GoldRecord(
            "g-item",
            Role.MATERIAL_ITEMS,
            "one-source",
            RecordOrigin.LLM_PROSE,
            (("key", "item"),),
            risk_or_condition=True,
        ),
        GoldRecord(
            "g-relation",
            Role.MATERIAL_RELATIONS,
            "one-source",
            RecordOrigin.LLM_PROSE,
            (("key", "relation"),),
        ),
    )
    candidates = tuple(
        CandidateRecord(
            f"c-{item.record_id}",
            item.role,
            item.source_id,
            item.origin,
            item.semantic_fields,
            critical_error_code=critical_error if item.role is Role.CLAIMS else None,
        )
        for item in gold
    )
    targets = tuple(
        CoverageTarget(item.record_id, item.source_id, tuple(CoverageStage)) for item in gold
    )
    observations = tuple(
        CoverageObservation(item.record_id, stage, CoverageOutcome.PASS)
        for item in gold
        for stage in CoverageStage
    )
    conclusion = ReportConclusion(
        "C-all",
        tuple(item.record_id for item in gold),
        tuple(item.record_id for item in gold),
        critical=True,
    )
    policy = QualityPolicy(
        role_thresholds=PILOT_CANDIDATE_POLICY.role_thresholds,
        risk_condition_recall_min=PILOT_CANDIDATE_POLICY.risk_condition_recall_min,
        report_support_min=PILOT_CANDIDATE_POLICY.report_support_min,
        min_gold_per_role=min_sample,
    )
    return gold, candidates, targets, observations, conclusion, policy


def test_candidate_thresholds_do_not_unlock_live_trial_without_frozen_development_assets() -> None:
    gold, candidates, targets, observations, conclusion, policy = _perfect_three_role_run(
        min_sample=2
    )
    report = score_structured_quality(
        gold,
        raw_candidates=candidates,
        validated_candidates=candidates,
        coverage_targets=targets,
        coverage_observations=observations,
        conclusions=(conclusion,),
        policy=policy,
        readiness=EvaluationReadiness(),
    )

    assert report.gate.rate_gate_passed is True
    assert report.gate.live_trial_ready is False
    assert report.gate.risk_condition_recall == 1
    assert "insufficient_sample:claims:1/2" in report.gate.readiness_blockers
    assert "development_gold_not_frozen" in report.gate.readiness_blockers
    assert "thresholds_not_signed_off" in report.gate.readiness_blockers


def test_signed_off_sufficient_run_can_pass_but_critical_error_is_absolute_veto() -> None:
    gold, candidates, targets, observations, conclusion, policy = _perfect_three_role_run()
    ready = EvaluationReadiness(
        development_gold_frozen=True,
        gold_frozen_before_candidates=True,
        adjudications_resolved=True,
        thresholds_signed_off=True,
    )
    passing = score_structured_quality(
        gold,
        raw_candidates=candidates,
        validated_candidates=candidates,
        coverage_targets=targets,
        coverage_observations=observations,
        conclusions=(conclusion,),
        policy=policy,
        readiness=ready,
    )
    assert passing.gate.live_trial_ready is True

    _, bad, _, _, _, _ = _perfect_three_role_run(critical_error="wrong_year")
    vetoed = score_structured_quality(
        gold,
        raw_candidates=bad,
        validated_candidates=bad,
        coverage_targets=targets,
        coverage_observations=observations,
        conclusions=(conclusion,),
        policy=policy,
        readiness=ready,
    )
    assert vetoed.gate.rate_gate_passed is False
    assert vetoed.gate.live_trial_ready is False
    assert "critical_error:wrong_year:c-g-claim" in vetoed.gate.rate_blockers
