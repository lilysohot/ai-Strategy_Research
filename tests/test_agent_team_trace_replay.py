"""T05: completed Agent Team runs remain replayable after refresh/reconnect."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from server import relay
from server.orchestrator import Orchestrator
from server.trajectory_status import TrajectoryCompleteness, inspect_trajectory

RUN_ID = "teamtrace00000000000000000000000000"


@pytest.fixture
def team_trace_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    run_dir = tmp_path / RUN_ID
    trace_dir = run_dir / "run" / "agent" / "trajectories"
    (trace_dir / "subagents").mkdir(parents=True)
    monkeypatch.setattr("server.relay.run_dir_for", lambda _run_id: run_dir)
    monkeypatch.setattr("server.trajectory_status.run_dir_for", lambda _run_id: run_dir)
    return trace_dir


def _write(path: Path, records: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )


def _team_records(trace_dir: Path) -> None:
    _write(
        trace_dir / "main_agent.jsonl",
        [
            {"t": "start", "role_id": "agent_team_main", "ts": 1.0},
            {"t": "llm", "turn": 1, "content": "coordinate", "ts": 4.0},
            {"t": "end", "ts": 9.0},
        ],
    )
    _write(
        trace_dir / "subagents" / "recon_auditor.t01.jsonl",
        [
            {"t": "start", "role_id": "agent_team_sub", "ts": 2.0},
            {"t": "llm", "turn": 1, "content": "audit", "ts": 5.0},
            {"t": "end", "ts": 7.0},
        ],
    )
    _write(
        trace_dir / "subagents" / "recon_builder.t01.jsonl",
        [
            {"t": "start", "role_id": "agent_team_sub", "ts": 3.0},
            {"t": "attempt", "turn": 1, "ts": 5.5},
            {"t": "result", "turn": 1, "name": "bash", "result": "ok", "ts": 6.0},
            {"t": "end", "ts": 8.0},
        ],
    )


def test_team_trace_page_merges_members_and_preserves_identity(team_trace_dir: Path) -> None:
    _team_records(team_trace_dir)

    page1, next_line, has_more = relay.trajectory_page(RUN_ID, limit=4)
    page2, next_line2, has_more2 = relay.trajectory_page(
        RUN_ID,
        after_line=next_line,
        limit=4,
    )
    page3, next_line3, has_more3 = relay.trajectory_page(
        RUN_ID,
        after_line=next_line2,
        limit=4,
    )

    records = page1 + page2 + page3
    assert has_more is True and has_more2 is True and has_more3 is False
    assert (next_line, next_line2, next_line3) == (4, 9, 10)
    assert [record["ts"] for record in records] == [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0]
    assert {record["agent_id"] for record in records} == {
        "agent_team_main",
        "recon_auditor",
        "recon_builder",
    }
    assert all(record.get("trajectory_source") for record in records)
    assert [record["t"] for record in records].count("attempt") == 0


async def test_team_trace_tail_replays_all_sources_with_one_cursor(team_trace_dir: Path) -> None:
    _team_records(team_trace_dir)
    (team_trace_dir.parent.parent.parent / "summary.json").write_text("{}", encoding="utf-8")

    first = [item async for item in relay.trajectory_tail(RUN_ID, after_line=0)]
    resumed = [item async for item in relay.trajectory_tail(RUN_ID, after_line=6)]

    assert [line for line, _ in first] == list(range(1, 11))
    assert [record["ts"] for _, record in resumed] == [6.0, 7.0, 8.0, 9.0]
    assert resumed[0][1]["agent_id"] == "recon_builder"


async def test_live_team_tail_discovers_new_member_without_replaying_main(
    team_trace_dir: Path,
) -> None:
    main = team_trace_dir / "main_agent.jsonl"
    _write(main, [{"t": "start", "role_id": "agent_team_main", "ts": 1.0}])
    tail = relay.trajectory_tail(RUN_ID)

    assert await tail.__anext__() == (
        1,
        {
            "t": "start",
            "role_id": "agent_team_main",
            "ts": 1.0,
            "agent_id": "agent_team_main",
            "agent_kind": "coordinator",
            "trajectory_source": "main_agent",
            "source_line": 1,
        },
    )

    with main.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"t": "llm", "turn": 1, "ts": 3.0}) + "\n")
    _write(
        team_trace_dir / "subagents" / "new_member.t01.jsonl",
        [
            {"t": "start", "role_id": "agent_team_sub", "ts": 2.0},
            {"t": "llm", "turn": 1, "ts": 4.0},
        ],
    )

    following = [await tail.__anext__() for _ in range(3)]
    assert [record["ts"] for _, record in following] == [2.0, 3.0, 4.0]
    assert [line for line, _ in following] == [2, 3, 4]
    (team_trace_dir.parent.parent.parent / "summary.json").write_text("{}", encoding="utf-8")
    with pytest.raises(StopAsyncIteration):
        await tail.__anext__()


def test_team_completeness_uses_main_as_authoritative_and_reports_sources(
    team_trace_dir: Path,
) -> None:
    _team_records(team_trace_dir)
    # A member may be interrupted after the coordinator has recorded the final
    # result. The product run is complete, while the member-level gap remains visible.
    member = team_trace_dir / "subagents" / "recon_builder.t01.jsonl"
    member.write_text(
        "\n".join(member.read_text(encoding="utf-8").splitlines()[:-1]) + "\n",
        encoding="utf-8",
    )

    inspection = inspect_trajectory(RUN_ID)
    payload = inspection.as_dict()

    assert inspection.state is TrajectoryCompleteness.COMPLETE
    assert payload["valid_lines"] == 9
    assert {source["source"] for source in payload["sources"]} == {
        "main_agent",
        "subagents/recon_auditor.t01",
        "subagents/recon_builder.t01",
    }
    builder = next(
        source for source in payload["sources"] if source["source"] == "subagents/recon_builder.t01"
    )
    assert builder["state"] == "partial"


def test_member_only_trace_is_partial_instead_of_unavailable(team_trace_dir: Path) -> None:
    _write(
        team_trace_dir / "subagents" / "orphan.t01.jsonl",
        [{"t": "start", "role_id": "agent_team_sub", "ts": 1.0}],
    )

    inspection = inspect_trajectory(RUN_ID)

    assert inspection.state is TrajectoryCompleteness.PARTIAL
    assert inspection.valid_lines == 1
    assert "主 Agent" in inspection.reason


def test_replayed_sse_events_keep_team_member_identity(team_trace_dir: Path) -> None:
    record = {
        "t": "llm",
        "turn": 1,
        "content": "finding",
        "agent_id": "recon_auditor",
        "agent_kind": "subagent",
        "trajectory_source": "subagents/recon_auditor.t01",
    }

    event = relay._traj_record_to_events(record, seq=3)[0]

    assert event["agent_id"] == "recon_auditor"
    assert event["agent_kind"] == "subagent"
    assert event["trajectory_source"] == "subagents/recon_auditor.t01"


def test_clean_team_run_detects_missing_or_empty_main_trace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "run"
    trace_dir = run_dir / "run" / "agent" / "trajectories"
    (trace_dir / "subagents").mkdir(parents=True)
    _write(trace_dir / "subagents" / "member.t01.jsonl", [{"t": "end", "ts": 2.0}])
    monkeypatch.setattr(
        "server.orchestrator.build_run_paths",
        lambda _run_id: {"root": run_dir},
    )
    run_id = "f05f05f0-0000-4000-8000-000000000000"

    assert Orchestrator._trajectory_degraded(run_id) is True
    (trace_dir / "main_agent.jsonl").write_text("", encoding="utf-8")
    assert Orchestrator._trajectory_degraded(run_id) is True
    _write(trace_dir / "main_agent.jsonl", [{"t": "end", "ts": 3.0}])
    assert Orchestrator._trajectory_degraded(run_id) is False
