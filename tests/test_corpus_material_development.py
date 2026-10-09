"""Regression checks for the frozen material development scorer."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest


def _scorer() -> ModuleType:
    path = (
        Path(__file__).resolve().parents[1]
        / ".scratch/corpus-evidence-pipeline/run_material_development.py"
    )
    spec = importlib.util.spec_from_file_location("material_development_scorer", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_value_comparison_accepts_raw_or_normalized_gold_representation() -> None:
    values_equivalent = _scorer().values_equivalent

    assert values_equivalent(
        {"raw": "2030 元", "normalized": "2030 CNY/share"},
        "2030元",
    )
    assert values_equivalent(
        {"raw": "2030 元", "normalized": "2030 CNY/share"},
        "2030 CNY/share",
    )


def test_value_comparison_rejects_incomplete_compound_value() -> None:
    values_equivalent = _scorer().values_equivalent

    assert not values_equivalent(
        {
            "raw": "10,000 at 14.76; 100 $15 calls at .16",
            "normalized": None,
        },
        "10,000 at 14.76",
    )


def _scoring_item(*, polarity: str, value: object, speaker_ref: str = "author") -> dict:
    return {
        "item_id": f"item-{polarity}-{value}",
        "text": "atomic text",
        "semantic_type": "opinion" if value is None else "behavior",
        "statement_role": "answer" if value is None else "claim",
        "speech_role": "answer" if value is None else "statement",
        "perspective": "source_explicit",
        "speaker_ref": speaker_ref,
        "polarity": polarity,
        "value": value,
        "behavior_status": None if value is None else "claimed_executed",
        "temporal_frame": "contemporaneous",
        "evidence": [{"quote": "同一逐字复合引文"}],
        "unknown_fields": [],
    }


def test_match_items_allows_mixed_gold_to_use_two_atomic_polarities() -> None:
    match_items = _scorer().match_items
    gold = _scoring_item(polarity="mixed", value=None)
    predicted = [
        _scoring_item(polarity="affirmed", value=None),
        _scoring_item(polarity="negated", value=None),
        _scoring_item(polarity="affirmed", value=None, speaker_ref="other"),
    ]

    matches = match_items([gold], predicted)

    assert matches[0]["predicted_indices"] == [0, 1]


def test_match_items_allows_compound_value_to_use_two_atomic_items() -> None:
    scorer = _scorer()
    gold = _scoring_item(
        polarity="affirmed",
        value={"raw": "10,000 at 14.76; 100 $15 calls at .16", "normalized": None},
    )
    predicted = [
        _scoring_item(polarity="affirmed", value="10,000 at 14.76"),
        _scoring_item(polarity="affirmed", value="100 $15 calls at .16"),
    ]

    matches = scorer.match_items([gold], predicted)

    assert matches[0]["predicted_indices"] == [0, 1]
    assert scorer.grouped_values_equivalent(gold["value"], [item["value"] for item in predicted])


def test_score_sample_aggregates_atomic_fields_and_relation_endpoints() -> None:
    scorer = _scorer()
    gold_answer = _scoring_item(polarity="mixed", value=None)
    gold_answer.update(
        {
            "item_id": "gold-answer",
            "critical": True,
            "unknown_fields": ["positive_axis", "negative_axis"],
        }
    )
    gold_question = _scoring_item(polarity="unknown", value=None, speaker_ref="questioner")
    gold_question.update(
        {
            "item_id": "gold-question",
            "semantic_type": "unknown",
            "statement_role": "question",
            "speech_role": "question",
            "critical": False,
            "evidence": [{"quote": "独立问题引文"}],
        }
    )
    affirmed = _scoring_item(polarity="affirmed", value=None)
    affirmed.update({"item_id": "pred-affirmed", "unknown_fields": ["positive_axis"]})
    negated = _scoring_item(polarity="negated", value=None)
    negated.update({"item_id": "pred-negated", "unknown_fields": ["negative_axis"]})
    question = dict(gold_question)
    question.update({"item_id": "pred-question", "critical": False})
    speakers = [
        {
            "speaker_id": "author",
            "display_name": "作者",
            "role": "source_author",
            "identity_status": "explicit",
        },
        {
            "speaker_id": "questioner",
            "display_name": "投资者",
            "role": "investor_participant",
            "identity_status": "unknown",
        },
    ]
    payload = {
        "speakers": speakers,
        "items": [affirmed, negated, question],
        "relations": [
            {
                "relation_id": "pred-relation",
                "type": "answers",
                "from_item": "pred-negated",
                "to_item": "pred-question",
                "provenance": "source_explicit",
            }
        ],
    }
    sample = {
        "sample_id": "sample",
        "speakers": speakers,
        "items": [gold_answer, gold_question],
        "relations": [
            {
                "relation_id": "gold-relation",
                "type": "answers",
                "from_item": "gold-answer",
                "to_item": "gold-question",
                "provenance": "source_explicit",
            }
        ],
    }
    understanding = SimpleNamespace(
        model_dump=lambda **_kwargs: payload,
        source=SimpleNamespace(source_rev="source-rev"),
    )
    material_run = SimpleNamespace(
        understanding=understanding,
        run_id="run-id",
        summary=lambda: {"complete": True, "packet_status": {"completed": 1}},
    )

    result = scorer.score_sample(sample, material_run)

    assert result["critical_all_fields_accuracy"] == 1.0
    assert result["source_relation_recall"] == 1.0
    assert result["detail"][0]["predicted_items"] == ["pred-affirmed", "pred-negated"]


def test_attempt_recorder_persists_success_before_packet_scoring(tmp_path: Path) -> None:
    scorer = _scorer()
    recorder = scorer.AttemptRecorder(
        lambda _prompt: "response body",
        audit_dir=tmp_path,
        budget_version="budget-v1",
        round_id="round-v1",
        sample_id="sample-v1",
    )

    assert recorder("prompt body") == "response body"
    assert recorder.attempts[0]["status"] == "succeeded"
    assert Path(recorder.attempts[0]["started_path"]).is_file()
    assert Path(recorder.attempts[0]["response_path"]).read_text() == "response body"
    assert json.loads(Path(recorder.attempts[0]["terminal_path"]).read_text())["status"] == (
        "succeeded"
    )


def test_attempt_recorder_marks_unclassified_exception_outcome_unknown(tmp_path: Path) -> None:
    scorer = _scorer()

    def fail(_prompt: str) -> str:
        raise RuntimeError("provider outcome is not known")

    recorder = scorer.AttemptRecorder(
        fail,
        audit_dir=tmp_path,
        budget_version="budget-v1",
        round_id="round-v1",
        sample_id="sample-v1",
    )

    with pytest.raises(RuntimeError, match="outcome is not known"):
        recorder("prompt body")
    assert recorder.attempts[0]["status"] == "outcome_unknown"
    terminal = json.loads(Path(recorder.attempts[0]["terminal_path"]).read_text())
    assert terminal["status"] == "outcome_unknown"


def test_stage1_partial_stops_before_the_next_sample() -> None:
    scorer = _scorer()
    root = Path(__file__).resolve().parents[1]
    budget = json.loads(
        (
            root / ".scratch/corpus-evidence-pipeline/"
            "r2-extraction-convergence-development-budget-v10.json"
        ).read_text()
    )
    result = {
        "sample_id": "dev-industry-qa-report",
        "item_recall": 1.0,
        "critical_item_recall": 1.0,
        "semantic_target_accuracy": 1.0,
        "attribution_target_accuracy": 1.0,
        "critical_all_fields_accuracy": 1.0,
        "summary": {"packet_status": {"partial": 1}, "complete": False},
    }

    assert scorer.stage1_stop_reason(budget, result) == "any_failed_or_partial_packet"


def test_direct_live_entry_is_disabled_before_provider_setup(monkeypatch) -> None:
    scorer = _scorer()
    monkeypatch.setattr(sys, "argv", ["run_material_development.py", "--round", "round-v1"])

    with pytest.raises(ValueError, match="formal ledger owns authorization"):
        scorer.main()
