"""Integrity of incremental cases and diagnostic telemetry, not production probes."""

import json
from pathlib import Path

import pytest

from benchmarks.team_workflow.metrics import measure
from benchmarks.team_workflow.run import catalog, digest, frozen_result


def test_original_40_case_objects_are_unchanged():
    root = Path(__file__).resolve().parents[1] / "benchmarks/team_workflow"
    baseline = json.loads((root / "baseline-40.lock.json").read_text())
    current = {c["id"]: c for c in catalog()}
    assert len(baseline["cases"]) == 40
    for key, expected in baseline["cases"].items():
        assert digest(current[key]) == expected, f"Historical case/rubric/budget changed: {key}"


def test_increment_has_paired_controls_and_no_claim_of_blind_holdout():
    cases = {c["id"]: c for c in catalog()}
    assert len(cases) == 71
    assert cases["F08"]["pair"] == "F09"
    assert cases["F09"]["pair"] == "F08"
    assert cases["F09"]["split"] == "transfer"
    for key in ["P34", "P35", "P36", "P37", "P38", "F08", "F09", "F10"]:
        assert cases[key]["origin"] and cases[key]["goal"]
        assert cases[key]["split"] != "holdout"


def test_original_48_case_objects_are_unchanged():
    root = Path(__file__).resolve().parents[1] / "benchmarks/team_workflow"
    baseline = json.loads((root / "baseline-48.lock.json").read_text())
    current = {c["id"]: c for c in catalog()}
    assert len(baseline["cases"]) == 48
    for key, expected in baseline["cases"].items():
        assert digest(current[key]) == expected


def test_original_53_case_objects_are_unchanged():
    root = Path(__file__).resolve().parents[1] / "benchmarks/team_workflow"
    baseline = json.loads((root / "baseline-53.lock.json").read_text())
    current = {c["id"]: c for c in catalog()}
    assert len(baseline["cases"]) == 53
    for key, expected in baseline["cases"].items():
        assert digest(current[key]) == expected
    assert current["F12"]["pair"] == "F13"
    assert current["F13"]["pair"] == "F12"
    assert current["F12"]["sources"] == current["F13"]["sources"]


def test_original_59_case_objects_are_unchanged():
    root = Path(__file__).resolve().parents[1] / "benchmarks/team_workflow"
    baseline = json.loads((root / "baseline-59.lock.json").read_text())
    current = {c["id"]: c for c in catalog()}
    assert len(baseline["cases"]) == 59
    for key, expected in baseline["cases"].items():
        assert digest(current[key]) == expected


def test_tool_timings_preserve_missing_and_parallel_durations(tmp_path):
    folder = tmp_path / "agent/trajectories"
    folder.mkdir(parents=True)
    rows = [
        {"t": "start", "ts": 0},
        {
            "t": "llm",
            "ts": 1,
            "tool_calls": [
                {"name": "corpus_search", "args": {"query": "sample"}},
                {"name": "corpus_search", "args": {"query": "sample"}},
                {"name": "bash", "args": {"command": "count draft"}},
            ],
        },
        {"t": "result", "ts": 6, "name": "corpus_search", "ms": 5000},
        {"t": "result", "ts": 6, "name": "corpus_search", "ms": 5000},
        {"t": "result", "ts": 6, "name": "corpus_fetch", "error": True},
        {"t": "result", "ts": 6, "name": "bash", "ms": 0, "error": True},
        {"t": "attempt", "ts": 6, "phase": "finished", "usage": {"prompt_tokens": 120}},
        {"t": "end", "ts": 6},
    ]
    (folder / "main_agent.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
    metrics = measure(tmp_path)
    assert metrics["trajectory_wall_s"] == 6
    assert metrics["tool_latency_ms"]["corpus_search"]["sum"] == 10000
    assert metrics["tool_latency_ms"]["corpus_search"]["p50"] == 5000
    fetch = metrics["tool_latency_ms"]["corpus_fetch"]
    assert fetch["known"] == 0 and fetch["unknown"] == 1 and fetch["p50"] is None
    assert metrics["tool_latency_ms"]["bash"]["known"] == 1
    assert metrics["tool_latency_ms"]["bash"]["explicit_errors"] == 1
    assert metrics["exact_repeated_tool_requests"] == 1
    assert not metrics["tool_sum_is_wall_time"]
    assert metrics["retrieval_stage_timings"] is None
    assert metrics["agents"][0]["tool_attempts"]["bash"] == 1
    assert metrics["max_prompt_tokens"] == 120


@pytest.mark.parametrize(
    "metric,budget",
    [
        ("attempts", "max_model_attempts"),
        ("max_prompt_tokens", "max_single_prompt_tokens"),
        ("exact_repeated_tool_requests", "max_exact_repeated_requests"),
    ],
)
def test_optional_efficiency_budgets_fail_closed_without_changing_old_cases(metric, budget):
    old_case = next(c for c in catalog() if c["id"] == "F04")
    worker = {"ok": True, "elapsed_s": 1, "result": {"final_answer": "B meets the threshold."}}
    metrics = {"available": True, "agents": [1, 2], "known_prompt_tokens": 120}
    assert frozen_result(worker, metrics, old_case)["status"] == "needs_review"
    case = {**old_case, "budgets": {**old_case["budgets"], budget: 2}}
    assert frozen_result(worker, metrics, case)["status"] == "fail"
    assert frozen_result(worker, {**metrics, metric: 3}, case)["status"] == "fail"
    assert frozen_result(worker, {**metrics, metric: 2}, case)["status"] == "needs_review"
