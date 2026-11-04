"""Keep evaluation labels hidden and malformed judge output out of aggregate scores."""

import json

import pytest

from benchmarks.team_synthesis.run import (
    ROOT,
    generation_messages,
    judge_messages,
    parse_judgment,
    summarize,
    write_json,
)


def test_generation_does_not_receive_answer_rubric_or_split():
    cases = json.loads((ROOT / "cases.json").read_text())
    assert len({c["id"] for c in cases}) == len(cases)
    assert {c["split"] for c in cases} == {"development", "holdout"}
    for case in cases:
        messages = generation_messages(case, "frozen baseline")
        text = messages[-1]["content"]
        assert case["question"] in text and case["reports"] in text
        assert all(rule not in text for rule in case["rubric"])
        assert "provenance" not in text
        judge = judge_messages(case, {"A": "first answer", "B": "second answer"})
        assert "candidate" not in judge[-1]["content"]
        assert "baseline" not in judge[-1]["content"]


@pytest.mark.parametrize("scores", [[1, 1], [1, 1, 2], [True, 1, 1], ["1", 1, 1]])
def test_invalid_judge_output_is_not_counted(scores):
    with pytest.raises(ValueError):
        parse_judgment(json.dumps({key: {"scores": scores, "reason": "reason"} for key in "AB"}))


def test_summary_keeps_missing_calls_out_of_success_denominator(tmp_path):
    manifest = {
        "fingerprint": "test",
        "pairs": [
            {
                "id": "pair",
                "case": "case",
                "repeat": 0,
                "split": "holdout",
                "labels": {"A": "candidate", "B": "baseline"},
            }
        ],
    }
    write_json(
        tmp_path / "pair-A.json",
        {
            "ok": True,
            "content": "A useful answer",
            "elapsed_s": 1,
            "usage": {},
        },
    )
    result = summarize(tmp_path, manifest)
    assert result["aggregates"]["candidate"]["holdout"]["scored"] == 0
    assert result["failures"] == [{"pair": "pair", "arm": "baseline", "error": "missing"}]
    assert result["paired_deltas"] == []
