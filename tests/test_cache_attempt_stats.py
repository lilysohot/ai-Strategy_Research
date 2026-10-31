def test_retry_cache_does_not_hide_unknown_first_request():
    from server.usage import cache_attempt_stats

    records = [
        {
            "t": "attempt",
            "phase": "finished",
            "attempt_id": "a",
            "attempt_index": 1,
            "outcome": "discarded",
            "duration_ms": 64000,
        },
        {
            "t": "attempt",
            "phase": "finished",
            "attempt_id": "b",
            "attempt_index": 2,
            "outcome": "accepted",
            "duration_ms": 50000,
            "usage": {"prompt_tokens": 100000, "cached_tokens": 98000},
        },
        {"t": "llm", "usage": {"prompt_tokens": 100000, "cached_tokens": 98000}},
    ]
    stats = cache_attempt_stats(records)
    assert stats["first_attempts"]["hit_rate"] is None
    assert stats["first_attempts"]["unknown_usage_attempts"] == 1
    assert stats["retries"]["hit_rate"] == 0.98
    assert stats["all_attempts"]["attempts"] == 2
    assert stats["all_attempts"]["duration_ms"] == 114000
    assert stats["all_attempts"]["hit_rate"] is None
    assert stats["all_attempts"]["known_hit_rate"] == 0.98


def test_missing_cache_field_is_unknown_and_explicit_zero_is_known():
    from server.usage import cache_attempt_stats

    for usage, expected in [
        ({"prompt_tokens": 100}, None),
        ({"prompt_tokens": 100, "cached_tokens": 0}, 0.0),
    ]:
        stats = cache_attempt_stats(
            [{"t": "attempt", "phase": "finished", "attempt_index": 1, "usage": usage}]
        )
        assert stats["first_attempts"]["hit_rate"] == expected


def test_legacy_traces_do_not_fabricate_first_attempt_statistics():
    from server.usage import cache_attempt_stats

    stats = cache_attempt_stats([{"t": "llm", "usage": {"prompt_tokens": 100}}])
    assert stats["status"] == "unavailable"
    assert stats["first_attempts"]["hit_rate"] is None


def test_started_attempt_without_finish_remains_unknown():
    from server.usage import cache_attempt_stats

    stats = cache_attempt_stats(
        [
            {"t": "attempt", "phase": "started", "attempt_id": "a", "attempt_index": 1},
            {"t": "attempt", "phase": "started", "attempt_id": "b", "attempt_index": 2},
            {
                "t": "attempt",
                "phase": "finished",
                "attempt_id": "b",
                "attempt_index": 2,
                "usage": {"prompt_tokens": 100, "cached_tokens": 90},
                "duration_ms": 1000,
            },
        ]
    )
    assert stats["all_attempts"]["attempts"] == 2
    assert stats["all_attempts"]["unknown_usage_attempts"] == 1
    assert stats["all_attempts"]["hit_rate"] is None


def test_team_directory_statistics_include_attempts_and_do_not_double_bill(tmp_path, monkeypatch):
    import json

    from scripts.replay_stats import load_from_runs_root, render, summarise
    from server import usage

    root = tmp_path / "one"
    trace = root / "run/agent/trajectories"
    trace.mkdir(parents=True)
    (root / "summary.json").write_text(json.dumps({"session_id": "session"}))
    events = [
        {"t": "attempt", "phase": "started", "turn": 1, "attempt_id": "a", "attempt_index": 1},
        {
            "t": "attempt",
            "phase": "finished",
            "turn": 1,
            "attempt_id": "a",
            "attempt_index": 1,
            "usage": {"prompt_tokens": 100, "cached_tokens": 20},
            "duration_ms": 200,
        },
        {"t": "llm", "usage": {"prompt_tokens": 100, "cached_tokens": 20}},
    ]
    (trace / "main_agent.jsonl").write_text("\n".join(json.dumps(x) for x in events) + "\n")
    rows = load_from_runs_root(tmp_path)
    assert rows[0].prompt_tokens == 100
    assert rows[0].cache_attempts["coordinator_entry"]["hit_rate"] == 0.2
    assert "entry=20.0%" in render(summarise(rows))
    monkeypatch.setattr(usage, "run_dir_for", lambda _: root)
    monkeypatch.setattr(usage, "trajectory_records", lambda _: events)
    result = usage.usage_for_run("one")
    assert result["cache_attempts"]["all_attempts"]["attempts"] == 1
    assert result["prompt_tokens"] == 100


async def test_real_loop_does_not_turn_absent_cache_usage_into_zero(tmp_path):
    import json

    from frontier_agent.components.observers.trajectory import TrajectoryFileObserver
    from frontier_agent.core.llm import LLMResponse
    from frontier_agent.core.loop_types import LoopConfig
    from frontier_agent.core.runtime.loop.agent_loop import run_agent_loop
    from server.usage import cache_attempt_stats

    class Client:
        async def chat(self, messages, **kwargs):
            return LLMResponse(content="done", usage={"prompt_tokens": 100, "completion_tokens": 1})

    await run_agent_loop(
        system_prompt="system", user_message="question", llm=Client(), tools=[],
        config=LoopConfig(task_id="cache"),
        observers=[TrajectoryFileObserver(tmp_path, filename="main", formats=("jsonl",))],
    )
    events = [json.loads(x) for x in (tmp_path / "main.jsonl").read_text().splitlines()]
    assert cache_attempt_stats(events)["first_attempts"]["hit_rate"] is None
