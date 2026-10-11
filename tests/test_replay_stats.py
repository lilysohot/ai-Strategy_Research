"""S1-a: the per-turn replay/cache board (issue 01 §10.2).

The board is the observability half of phase 1: without it, "the conversation
reused 94% of the previous prompt" is a claim from one evidence run rather than
something anyone can re-print for any conversation. These tests pin the four
things that could silently rot:

  * the arithmetic — reuse is measured against the *previous turn's* prompt
    **within one conversation**, and a turn with no predecessor (or none
    metered) reports no ratio instead of a fabricated 0%;
  * the grouping — a runs root holding several conversations must not average
    across them (that is how a 112% "reuse" gets printed);
  * the directory source — counters, window and decision are read from the run's
    own artifacts, with no database involved;
  * the exit codes — "found nothing" (1) must stay distinguishable from "read
    something wrong" (2).
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import pytest

from scripts.replay_stats import (
    TurnStat,
    load_from_db,
    load_from_runs_root,
    main,
    summarise,
)

_SESSION = "3f2a1c8e-0000-4000-8000-000000000001"


def _stat(**overrides) -> TurnStat:
    base = dict(
        turn=1,
        run_id="r0",
        source="dir",
        session_id=_SESSION,
        prompt_tokens=0,
        cache_read_tokens=0,
        llm_calls=0,
        usage_status="complete",
        decision="",
        reason="",
        prior_turns=0,
        messages=0,
        est_tokens=0,
        payload_bytes=0,
        stopped_by="",
    )
    base.update(overrides)
    return TurnStat(**base)


def _write_run(
    runs_root: Path,
    name: str,
    *,
    prompt: int,
    cache: int,
    replay: dict | None,
    mtime: float,
    session_id: str = _SESSION,
    dump: bool = True,
    summary_in_run_dir: bool = False,
) -> None:
    """Lay out one run the way ``build_run_paths`` does.

    ``summary.json`` sits at the run root and ``run/`` holds the trial's own
    files (trajectory + conversation dump); ``summary_in_run_dir`` writes the
    fallback summary location instead, so the board cannot silently go empty if
    that layout ever moves.
    """
    run = runs_root / name / "run"
    (run / "agent" / "trajectories").mkdir(parents=True)
    summary: dict = {"final_answer": "ok"}
    if replay is not None:
        summary["replay"] = replay
    summary_path = (run if summary_in_run_dir else runs_root / name) / "summary.json"
    summary_path.write_text(json.dumps(summary), encoding="utf-8")
    (run / "agent" / "trajectories" / "react_agent.jsonl").write_text(
        json.dumps(
            {
                "t": "llm",
                "usage": {
                    "prompt_tokens": prompt,
                    "completion_tokens": 5,
                    "cache_read_tokens": cache,
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    if dump:
        # The dump is where a directory source learns which conversation this run
        # belongs to.
        (run / "conversation.json").write_text(
            json.dumps({"schema": "conversation-dump/1", "session_id": session_id}),
            encoding="utf-8",
        )
    os.utime(summary_path, (mtime, mtime))


# ── the arithmetic ───────────────────────────────────────────────────


def test_reuse_is_measured_against_the_previous_turn() -> None:
    board = summarise(
        [
            _stat(
                turn=1,
                run_id="a",
                prompt_tokens=1000,
                decision="skipped",
                reason="no_payload",
            ),
            _stat(
                turn=2,
                run_id="b",
                prompt_tokens=1200,
                cache_read_tokens=900,
                decision="used",
                prior_turns=2,
                messages=5,
                est_tokens=950,
            ),
        ]
    )

    # Turn 1 has no predecessor: no ratio, rather than a fabricated 0%.
    assert board["turns"][0]["reuse"] is None
    assert board["turns"][1]["reuse"] == 0.9
    assert board["summary"]["mean_reuse"] == 0.9
    assert board["summary"]["replayed"] == 1
    assert board["summary"]["skipped"] == 1
    assert board["summary"]["skip_reasons"] == {"no_payload": 1}
    assert board["summary"]["total_prompt_tokens"] == 2200
    assert board["summary"]["total_cache_read_tokens"] == 900


def test_unmetered_turns_are_flagged_and_never_averaged_in() -> None:
    board = summarise(
        [
            _stat(turn=1, run_id="a", prompt_tokens=1000),
            _stat(
                turn=2, run_id="b", prompt_tokens=0, cache_read_tokens=0, usage_status="unavailable"
            ),
        ]
    )
    assert board["summary"]["unmetered"] == ["b"]
    # A run with no metered prompt cannot produce a ratio; the previous
    # denominator carries forward instead of becoming 0%.
    assert board["turns"][1]["reuse"] is None


def test_a_run_without_a_decision_is_counted_separately() -> None:
    board = summarise([_stat(turn=1, run_id="a", prompt_tokens=10)])
    assert board["summary"]["no_decision"] == 1
    assert board["summary"]["skip_reasons"] == {}


def test_reuse_is_never_computed_across_conversations() -> None:
    """Interleaved sessions must not borrow each other's denominator."""
    board = summarise(
        [
            _stat(turn=1, run_id="a1", session_id="sess-a", prompt_tokens=1000),
            _stat(
                turn=2, run_id="b1", session_id="sess-b", prompt_tokens=2000, cache_read_tokens=1900
            ),
            _stat(
                turn=3, run_id="a2", session_id="sess-a", prompt_tokens=1500, cache_read_tokens=900
            ),
        ]
    )

    assert board["turns"][1]["reuse"] is None  # first turn of sess-b
    assert board["turns"][2]["reuse"] == 0.9  # against a1's 1000, not b1's 2000
    assert [s["runs"] for s in board["summary"]["sessions"]] == [2, 1]


def test_an_unknown_session_is_its_own_group() -> None:
    """A directory run with no dump has no verifiable session to compare with."""
    board = summarise(
        [
            _stat(turn=1, run_id="a", session_id="", prompt_tokens=1000),
            _stat(turn=2, run_id="b", session_id="", prompt_tokens=2000, cache_read_tokens=1900),
        ]
    )
    assert board["turns"][1]["reuse"] is None
    assert len(board["summary"]["sessions"]) == 2


# ── the directory source ─────────────────────────────────────────────


def test_the_board_reads_counters_window_and_decision_from_run_artifacts(tmp_path) -> None:
    _write_run(
        tmp_path,
        "run-one",
        prompt=1000,
        cache=0,
        replay={"decision": "skipped", "reason": "no_payload"},
        mtime=1_700_000_000,
    )
    _write_run(
        tmp_path,
        "run-two",
        prompt=1200,
        cache=900,
        replay={
            "decision": "used",
            "prior_turns": 2,
            "messages": 5,
            "est_tokens": 950,
            "payload_bytes": 4096,
            "stopped_by": "final",
        },
        mtime=1_700_000_100,
    )

    turns = load_from_runs_root(tmp_path)

    assert [t.run_id for t in turns] == ["run-one", "run-two"]
    assert turns[0].prompt_tokens == 1000 and turns[0].cache_read_tokens == 0
    assert turns[0].decision == "skipped"
    assert turns[0].session_id == _SESSION
    assert turns[1].prompt_tokens == 1200 and turns[1].cache_read_tokens == 900
    assert turns[1].decision == "used" and turns[1].est_tokens == 950
    assert turns[1].prior_turns == 2 and turns[1].stopped_by == "final"
    assert summarise(turns)["turns"][1]["reuse"] == 0.9


def test_runs_from_different_conversations_stay_apart(tmp_path) -> None:
    _write_run(
        tmp_path,
        "run-a1",
        prompt=1000,
        cache=0,
        replay=None,
        mtime=1_700_000_000,
        session_id="sess-a",
    )
    _write_run(
        tmp_path,
        "run-b1",
        prompt=2000,
        cache=1900,
        replay=None,
        mtime=1_700_000_100,
        session_id="sess-b",
    )
    turns = load_from_runs_root(tmp_path)
    board = summarise(turns)
    assert board["turns"][1]["reuse"] is None
    assert {s["session_id"] for s in board["summary"]["sessions"]} == {"sess-a", "sess-b"}


def test_a_run_without_a_summary_is_skipped_not_guessed(tmp_path) -> None:
    # A bare directory (no summary.json) is not a run this board can read.
    (tmp_path / "not-a-run").mkdir()
    assert load_from_runs_root(tmp_path) == []


def test_a_run_with_no_trajectory_is_flagged_unmetered(tmp_path) -> None:
    """No trajectory at all is "unavailable", never a zero-token claim."""
    run = tmp_path / "run-x" / "run"
    run.mkdir(parents=True)
    (tmp_path / "run-x" / "summary.json").write_text(
        json.dumps({"replay": {"decision": "used", "prior_turns": 1}}), encoding="utf-8"
    )
    turns = load_from_runs_root(tmp_path)
    assert turns[0].usage_status == "unavailable"
    assert turns[0].prompt_tokens == 0
    assert summarise(turns)["summary"]["unmetered"] == ["run-x"]


def test_a_trajectory_without_metered_turns_is_partial(tmp_path) -> None:
    """The file exists but no turn reported usage: partial, not complete."""
    run = tmp_path / "run-y" / "run"
    (run / "agent" / "trajectories").mkdir(parents=True)
    (tmp_path / "run-y" / "summary.json").write_text("{}", encoding="utf-8")
    (run / "agent" / "trajectories" / "react_agent.jsonl").write_text(
        json.dumps({"t": "result", "name": "bash"}) + "\n", encoding="utf-8"
    )
    turns = load_from_runs_root(tmp_path)
    assert turns[0].usage_status == "partial"


def test_a_summary_under_run_is_still_found(tmp_path) -> None:
    # The fallback location: losing a whole board to a moved file would read as
    # "no conversation ever replayed anything", which is the wrong conclusion.
    _write_run(
        tmp_path,
        "run-one",
        prompt=1000,
        cache=250,
        replay={"decision": "used", "prior_turns": 1},
        mtime=1_700_000_000,
        summary_in_run_dir=True,
    )
    turns = load_from_runs_root(tmp_path)
    assert [t.run_id for t in turns] == ["run-one"]
    assert turns[0].cache_read_tokens == 250


# ── the database source ──────────────────────────────────────────────


@pytest.fixture
async def db(tmp_path):
    """Throwaway SQLite database — the sibling suites' per-file fixture."""
    from server.config import get_config
    from server.store import init_db, reset_engine

    cfg = get_config()
    orig_url, orig_key = cfg.database_url, cfg.master_key
    cfg.database_url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
    cfg.master_key = f"test-master-{uuid.uuid4().hex}"
    await reset_engine()
    await init_db()
    yield cfg
    cfg.database_url, cfg.master_key = orig_url, orig_key
    await reset_engine()


async def _new_user_id() -> uuid.UUID:
    """A real user row: ``sessions.user_id`` is a foreign key."""
    from server.store import create_user

    user = await create_user(username=f"stats-{uuid.uuid4().hex[:10]}", password_hash="synthetic")
    return user.id


@pytest.mark.asyncio
async def test_the_db_source_scopes_to_one_session_and_reads_usage_json(db):
    """The Run row is the source: counters from columns, decision from usage_json."""
    from datetime import UTC, datetime

    from sqlalchemy import update

    from server.store import (
        Run,
        create_run,
        ensure_session,
        get_sessionmaker,
        update_run_usage,
    )

    user_id = await _new_user_id()
    session_id = uuid.uuid4()
    other_session = uuid.uuid4()
    await ensure_session(session_id=session_id, user_id=user_id, title="t")
    await ensure_session(session_id=other_session, user_id=user_id, title="other")

    created: list[uuid.UUID] = []
    for index in range(2):
        run_id = uuid.uuid4()
        await create_run(
            run_id=run_id,
            session_id=session_id,
            user_id=user_id,
            prompt="p",
            pipeline_id="stateful-react-agent",
            run_dir=f"/tmp/{run_id.hex}",
            status="completed",
        )
        await update_run_usage(
            run_id=run_id,
            usage={
                "prompt_tokens": 1000 + index,
                "cache_read_tokens": 0 if index == 0 else 900,
                "llm_calls": 1,
                "status": "complete",
                "replay": {
                    "decision": "skipped" if index == 0 else "used",
                    "reason": "no_payload" if index == 0 else "",
                },
            },
        )
        created.append(run_id)
    leaked = uuid.uuid4()
    await create_run(
        run_id=leaked,
        session_id=other_session,
        user_id=user_id,
        prompt="p",
        pipeline_id="stateful-react-agent",
        run_dir=f"/tmp/{leaked.hex}",
        status="completed",
    )
    # ``created_at`` has second resolution, so two runs inserted in the same
    # second would tie; pin distinct timestamps so the ORDER BY is really tested.
    async with get_sessionmaker()() as session:
        await session.execute(
            update(Run)
            .where(Run.id == created[0])
            .values(created_at=datetime(2026, 1, 1, tzinfo=UTC))
        )
        await session.execute(
            update(Run)
            .where(Run.id == created[1])
            .values(created_at=datetime(2026, 1, 2, tzinfo=UTC))
        )
        await session.commit()

    turns = await load_from_db(session_id.hex)

    assert [t.run_id for t in turns] == [run.hex for run in created]
    assert turns[0].session_id == session_id.hex
    assert turns[0].prompt_tokens == 1000 and turns[0].decision == "skipped"
    assert turns[0].reason == "no_payload"
    assert turns[1].prompt_tokens == 1001 and turns[1].cache_read_tokens == 900
    assert turns[1].decision == "used"
    assert summarise(turns)["turns"][1]["reuse"] == 0.9


# ── the CLI ──────────────────────────────────────────────────────────


def test_cli_prints_the_table_and_exits_zero(tmp_path, capsys) -> None:
    _write_run(
        tmp_path,
        "run-one",
        prompt=1000,
        cache=0,
        replay={"decision": "used", "prior_turns": 1, "messages": 3, "est_tokens": 400},
        mtime=1_700_000_000,
    )
    assert main(["--runs-root", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "reuse" in out
    assert "run-one" in out
    assert "used (1 turns)" in out


def test_cli_json_output_is_machine_readable(tmp_path, capsys) -> None:
    _write_run(
        tmp_path,
        "run-one",
        prompt=1000,
        cache=500,
        replay={"decision": "used", "prior_turns": 1},
        mtime=1_700_000_000,
    )
    assert main(["--runs-root", str(tmp_path), "--json"]) == 0
    board = json.loads(capsys.readouterr().out)
    assert board["summary"]["replayed"] == 1
    assert board["turns"][0]["cache_read_tokens"] == 500


def test_cli_exits_one_when_there_is_nothing_to_report(tmp_path, capsys) -> None:
    # Empty is not an error: the caller can tell "no turns" from "unreadable".
    assert main(["--runs-root", str(tmp_path)]) == 1
    assert "0 run(s)" in capsys.readouterr().out
