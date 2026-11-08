"""Evaluator integrity: never turn missing evidence or execution failure into a pass."""

import json
from pathlib import Path

import pytest

from benchmarks.team_workflow.fixtures import fixed_tools
from benchmarks.team_workflow.metrics import measure, percentile
from benchmarks.team_workflow.run import (
    apply_review,
    catalog,
    compare,
    digest,
    frozen_result,
    mark_unassessed,
    protocol_result,
    summarize,
    write,
)


def test_batch_stop_preserves_completed_errors_and_partial_traces(tmp_path):
    write(
        tmp_path / "manifest.json",
        {
            "samples": [
                {"sample": f"F0{i}-r1", "case": f"F0{i}", "layer": "frozen", "dimension": "test"}
                for i in range(1, 4)
            ]
        },
    )
    for i in range(1, 4):
        (tmp_path / f"F0{i}-r1").mkdir()
    error = {"status": "error", "reason": "llm_error", "elapsed_s": 100}
    write(tmp_path / "F01-r1/result.json", error)
    partial = tmp_path / "F02-r1/agent"
    partial.mkdir()
    (partial / "trace.jsonl").write_text("partial evidence")
    mark_unassessed(tmp_path, "stopped after errors", mode="manual")
    assert json.loads((tmp_path / "F01-r1/result.json").read_text()) == error
    assert (partial / "trace.jsonl").read_text() == "partial evidence"
    assert json.loads((tmp_path / "F02-r1/result.json").read_text())["partial_trace_retained"]
    assert not json.loads((tmp_path / "F03-r1/result.json").read_text())["partial_trace_retained"]
    assert summarize(tmp_path)["states"] == {"error": 1, "unassessed": 2}


def test_consecutive_execution_errors_stop_model_launches_without_dropping_cases(
    tmp_path, monkeypatch
):
    import argparse

    from benchmarks.team_workflow import run as runner

    launches = []

    class FailedWorker:
        def __init__(self, command, **kwargs):
            launches.append(command)
            trial = Path(command[command.index("--out") + 1])
            write(trial / "worker.json", {"ok": False, "error": "model unavailable"})

        def wait(self, timeout):
            return 0

    monkeypatch.setattr(runner.subprocess, "Popen", FailedWorker)
    monkeypatch.setattr(runner, "source_fingerprint", lambda: {"test": True})
    out = tmp_path / "batch"
    assert (
        runner.run(
            argparse.Namespace(
                layer="frozen",
                case=None,
                repeats=1,
                profile="default",
                max_consecutive_errors=2,
                out=out,
            )
        )
        == 1
    )
    assert len(launches) == 2
    assert summarize(out)["states"] == {"error": 2, "unassessed": 15}
    stop = json.loads((out / "batch_stop.json").read_text())
    assert stop["mode"] == "automatic"
    assert len(stop["unassessed"]) == 15


def test_catalog_has_reproducible_cases_and_no_unseen_holdout_claim():
    cases = catalog()
    assert len(cases) == 71
    assert {c["split"] for c in cases} == {"development", "transfer"}
    assert len([c for c in cases if c["layer"] == "protocol"]) == 54
    for case in cases:
        assert case["origin"] and case["goal"]


async def test_fixture_tools_cannot_fall_through_to_network_or_file_tools():
    case = next(c for c in catalog() if c["id"] == "F05")
    tools = fixed_tools(case["sources"])
    assert not {"bash", "read_file", "download_file", "corpus_search"} & tools.keys()
    out = json.loads(
        await tools["web_fetch"].func(
            url=[
                case["sources"][0]["url"],
                case["sources"][1]["url"],
                "https://example.com/unlisted",
            ]
        )
    )
    assert out["acquired_count"] == 1 and out["failed_count"] == 2
    assert out["items"][0]["content"] == case["sources"][0]["content"]
    assert all(not item["content"] for item in out["items"][1:])
    search = await tools["web_search"].func(query="unanticipated query")
    assert all(rule not in search for rule in case["rubric"])
    assert all(source["content"] not in search for source in case["sources"] if source["content"])


@pytest.mark.parametrize(
    "child,code,status",
    [
        ("", 0, "pass"),
        ("<skipped/>", 0, "unassessed"),
        ("<failure>real defect</failure>", 1, "fail"),
        ("<error/>", 1, "error"),
    ],
)
def test_protocol_verdicts_keep_skip_failure_error_distinct(tmp_path, child, code, status):
    xml = tmp_path / "report.xml"
    xml.write_text(
        f'<testsuites><testsuite><testcase name="a">{child}</testcase></testsuite></testsuites>'
    )
    assert protocol_result(xml, code)["status"] == status


def test_no_tests_or_missing_xml_never_passes(tmp_path):
    xml = tmp_path / "report.xml"
    assert protocol_result(xml, 0)["status"] == "error"
    xml.write_text("<testsuites/>")
    assert protocol_result(xml, 0)["status"] == "error"


def test_generation_completion_never_implies_semantic_pass():
    case = next(c for c in catalog() if c["id"] == "F04")
    worker = {"ok": True, "elapsed_s": 20, "result": {"final_answer": "unreviewed"}}
    metrics = {
        "available": True,
        "agents": [1, 2],
        "known_prompt_tokens": 10,
        "research_dispatch_attempts": 2,
        "unknown_usage_attempts": 0,
    }
    assert frozen_result(worker, metrics, case)["status"] == "needs_review"
    assert frozen_result({**worker, "ok": False}, metrics, case)["status"] == "error"
    assert (
        frozen_result({**worker, "result": {"stopped_by": "llm_error"}}, metrics, case)["status"]
        == "error"
    )
    assert frozen_result(worker, {**metrics, "agents": [1]}, case)["status"] == "fail"
    assert (
        frozen_result({**worker, "elapsed_s": case["budgets"]["wall_s"] + 1}, metrics, case)[
            "status"
        ]
        == "fail"
    )
    assert (
        frozen_result(worker, {**metrics, "known_prompt_tokens": 900000}, case)["status"] == "fail"
    )


def test_rejected_dispatch_retries_do_not_count_as_new_research_jobs():
    case = next(c for c in catalog() if c["id"] == "F04")
    worker = {
        "ok": True,
        "elapsed_s": 20,
        "result": {
            "final_answer": "answer",
            "report_contract": {
                "job_outcomes": [
                    {"verification_checks": []},
                    {"verification_checks": []},
                    {"verification_checks": [{"check_id": "verify"}]},
                ]
            },
        },
    }
    metrics = {"available": True, "agents": [1, 2], "research_dispatch_attempts": 6}
    graded = frozen_result(worker, metrics, case)
    assert graded["status"] == "needs_review"
    assert graded["research_jobs_accepted"] == 2


def test_summary_does_not_hide_missing_or_unreviewed_samples(tmp_path):
    samples = [
        {"sample": f"F04-r{i}", "case": "F04", "layer": "frozen", "dimension": "orchestration"}
        for i in range(1, 4)
    ]
    write(tmp_path / "manifest.json", {"samples": samples})
    for sample, status in zip(samples, ["pass", "needs_review"], strict=False):
        trial = tmp_path / sample["sample"]
        trial.mkdir()
        write(trial / "result.json", {"status": status})
    result = summarize(tmp_path)
    assert result["states"] == {"pass": 1, "needs_review": 1, "missing": 1}
    assert not result["all_passed"]


def test_review_bound_to_case_and_answer_and_cannot_override_hard_failure(tmp_path):
    case = next(c for c in catalog() if c["id"] == "F04")
    sample = {"sample": "F04-r1", "case": "F04", "layer": "frozen", "dimension": "orchestration"}
    write(tmp_path / "manifest.json", {"samples": [sample], "cases": [case]})
    trial = tmp_path / "F04-r1"
    trial.mkdir()
    worker = {"result": {"final_answer": "B costs 120"}}
    write(trial / "worker.json", worker)
    write(trial / "result.json", {"status": "needs_review"})
    review = {
        "reviewer": "test reviewer",
        "review_type": "human",
        "worker_sha256": digest(worker),
        "case_sha256": digest(case),
        "criteria": [{"verdict": "pass", "evidence": "fixture and answer"}] * 3,
    }
    path = tmp_path / "manual.json"
    write(path, {**review, "worker_sha256": "stale"})
    with pytest.raises(ValueError, match="exact worker"):
        apply_review(tmp_path, "F04-r1", path)
    write(path, review)
    write(trial / "result.json", {"status": "fail", "hard_failures": ["empty answer"]})
    with pytest.raises(ValueError, match="cannot override"):
        apply_review(tmp_path, "F04-r1", path)
    write(trial / "result.json", {"status": "needs_review"})
    apply_review(tmp_path, "F04-r1", path)
    assert json.loads((trial / "result.json").read_text())["status"] == "pass"
    write(path, {**review, "review_type": "model"})
    apply_review(tmp_path, "F04-r1", path)
    reviewed = json.loads((trial / "result.json").read_text())
    assert reviewed["status"] == "needs_review"
    assert reviewed["diagnostic_verdict"] == "pass"
    assert len(list(trial.glob("review-*.json"))) == 2


def test_timing_keeps_parallel_work_separate_from_wall_time(tmp_path):
    folder = tmp_path / "agent/trajectories"
    folder.mkdir(parents=True)
    for name, start, finish in [("main_agent", 10, 30), ("member.t01", 12, 25)]:
        rows = [
            {"t": "start", "ts": start},
            {
                "t": "attempt",
                "ts": finish,
                "phase": "finished",
                "duration_ms": 15000,
                "usage": {},
                "outcome": "failed",
                "reason": "stream_stalled",
            },
        ]
        (folder / f"{name}.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
    metrics = measure(tmp_path)
    assert metrics["trajectory_wall_s"] == 20
    assert metrics["llm_attempt_seconds_sum"] == 30
    assert metrics["unknown_usage_attempts"] == 2
    assert metrics["first_research_report_s"] is None
    assert percentile([], 0.5) is None
    assert not measure(Path("/nonexistent-team-eval-trial"))["available"]
    assert metrics["cache_hit_rate_on_known_usage"] is None
    with (folder / "main_agent.jsonl").open("a") as stream:
        stream.write('\n{"t":')
    assert measure(tmp_path)["malformed_events"] == 1


def test_budget_reports_real_dispatch_window_not_just_total_wall(monkeypatch):
    from benchmarks.team_workflow.worker import budget_layout

    monkeypatch.delenv("FRONTIER_AGENT_TASK_WALL_TIME_S", raising=False)
    layout = budget_layout(
        {
            "wall_deadline_s": 300,
            "tool_timeout_s": 15,
            "finalization_timeout_s": 45,
            "team_wind_down_timeout_s": 15,
            "publication_phase_timeout_s": 90,
            "verification_phase_timeout_s": 90,
            "wall_deadline_reserve_s": 90,
        }
    )
    assert layout["research_cutoff_s"] == 59
    assert 0 < layout["research_dispatch_cutoff_s"] < 59


async def test_infeasible_budget_fails_before_creating_model_client(tmp_path, monkeypatch):
    from benchmarks.team_workflow.worker import execute
    from workflows.agent_team import profile as profiles

    monkeypatch.delenv("FRONTIER_AGENT_TASK_WALL_TIME_S", raising=False)
    monkeypatch.setattr(
        profiles,
        "load_swarm_profile",
        lambda *a, **kw: {
            "llm": {"model": "must-not-call"},
            "agent": {
                key: value for key, value in kw["overrides"]["agent"].items() if value is not None
            },
        },
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("invalid budget must fail before model construction")

    monkeypatch.setattr(profiles, "create_swarm_llm", forbidden)
    case = next(c for c in catalog() if c["id"] == "F04")
    case = {**case, "budgets": {**case["budgets"], "wall_s": 300}}
    result = await execute(case, tmp_path, "default")
    assert not result["ok"]
    assert result["error_type"] == "EvaluationBudgetError"


def test_comparison_exposes_regression_and_rejects_changed_cases(tmp_path):
    before, after = tmp_path / "before", tmp_path / "after"
    for out, status in [(before, "pass"), (after, "error")]:
        out.mkdir()
        write(
            out / "manifest.json",
            {
                "catalog_sha256": "frozen",
                "profile": "default",
                "samples": [{"sample": "P01-r1", "layer": "protocol", "dimension": "evidence"}],
            },
        )
        trial = out / "P01-r1"
        trial.mkdir()
        write(trial / "result.json", {"status": status, "elapsed_s": 1})
    assert compare(before, after)["regressions"] == 1
    manifest = json.loads((after / "manifest.json").read_text())
    write(after / "manifest.json", {**manifest, "catalog_sha256": "changed-budget"})
    with pytest.raises(ValueError, match="not paired"):
        compare(before, after)


async def test_worker_runs_real_bus_member_tools_and_delivery_with_scripted_llm(
    tmp_path, monkeypatch
):
    from benchmarks.team_workflow.worker import execute
    from frontier_agent.core.llm import LLMResponse
    from frontier_agent.core.runtime.registries import services
    from workflows.agent_team import profile as profiles
    from workflows.agent_team.nodes import main_agent as node

    class ScriptedClient:
        model = "offline-eval"
        main_step = 0
        member_step = 0

        async def chat(self, messages, **kwargs):
            available = {t["function"]["name"] for t in kwargs.get("tools", [])}
            if "submit_report" in available:
                self.member_step += 1
                if self.member_step == 1:
                    name, args = "web_fetch", {"url": "https://fixtures.invalid/atlas/cost"}
                else:
                    assert "每单位12元" in str(messages)
                    name, args = (
                        "submit_report",
                        {"content": "B costs 120元 for 10 units.", "finish": True},
                    )
            else:
                steps = [
                    (
                        "create_subagent",
                        {
                            "agents": [
                                {
                                    "name": "fixture_research",
                                    "system_prompt": "Read the assigned fixed source and report its contents.",
                                }
                            ]
                        },
                    ),
                    (
                        "assign_task",
                        {
                            "tasks": [
                                {
                                    "agent": "fixture_research",
                                    "prompt": "Fetch the Atlas cost page and report.",
                                }
                            ]
                        },
                    ),
                    ("collect_reports", {"timeout": 5}),
                    (
                        "deliver_answer",
                        {
                            "content": "B costs 120元 for ten units, according to the fixed cost source.",
                            "updates": [],
                        },
                    ),
                ]
                assert self.main_step < len(steps), str(messages[-2:])
                name, args = steps[self.main_step]
                self.main_step += 1
            return LLMResponse(
                tool_calls=[
                    {"id": f"call-{self.main_step}-{self.member_step}", "name": name, "args": args}
                ]
            )

    client = ScriptedClient()

    def load(*args, **kwargs):
        return {
            "llm": {"model": "offline-eval", "max_tokens": 8192},
            "agent": {
                **{
                    key: value
                    for key, value in kwargs.get("overrides", {}).get("agent", {}).items()
                    if value is not None
                },
                "reasoning_only_timeout_s": 0,
                "reasoning_only_max_tokens": 0,
                "context_compaction": "off",
                "replay_max_tokens": 0,
            },
        }

    monkeypatch.setattr(profiles, "load_swarm_profile", load)
    monkeypatch.setattr(profiles, "create_swarm_llm", lambda *args, **kwargs: client)
    monkeypatch.setattr(profiles, "build_swarm_model_profile", lambda *args, **kwargs: None)
    # No filesystem tools are registered. Keep the test independent of bwrap availability.
    monkeypatch.setattr(node, "resolve_sandbox_mode", lambda *args: "bwrap")
    monkeypatch.setattr(node, "bwrap_available", lambda: False)
    before = services.snapshot()
    try:
        result = await execute(next(c for c in catalog() if c["id"] == "F04"), tmp_path, "default")
        assert result["ok"], result
        metrics = measure(tmp_path)
        assert metrics["tools"]["web_fetch"] == 1
        assert metrics["tools"]["submit_report"] == 1
        assert metrics["tools"]["deliver_answer"] == 1
        assert len(metrics["agents"]) == 2
        assert "120" in result["result"]["final_answer"]
    finally:
        services.restore(before)
