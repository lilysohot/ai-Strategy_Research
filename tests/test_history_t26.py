"""T2.6 — multi-turn history backfill.

Maps to the T2.6 checklist:
    * prior turns -> render_session_history -> workflow_input (history.txt)
    * after a run, only the final_answer (with final_content / partial handling)
      is written back as the assistant turn
    * the workflow's internal messages are NEVER read for the backfill

Run with::
    uv run pytest tests/test_history_t26.py -q
"""

from __future__ import annotations

import os
import uuid
from unittest.mock import AsyncMock

import pytest

from server.config import get_config, run_dir_for
from server.history import (
    extract_final_answer,
    render_session_history,
    turns_to_dicts,
)
from server.orchestrator import Orchestrator, _session_uuid
from server.store import (
    append_turn,
    ensure_session,
    init_db,
    list_turns,
    reset_engine,
)


@pytest.fixture
async def db(tmp_path):
    cfg = get_config()
    orig_url, orig_key = cfg.database_url, cfg.master_key
    db_file = tmp_path / "test.db"
    cfg.database_url = f"sqlite+aiosqlite:///{db_file}"
    cfg.master_key = f"test-master-{uuid.uuid4().hex}"
    await reset_engine()
    await init_db()
    yield cfg
    cfg.database_url, cfg.master_key = orig_url, orig_key
    await reset_engine()


# ── render_session_history ─────────────────────────────────────────
def test_render_empty_returns_empty():
    assert render_session_history([]) == ""


def test_render_user_assistant_transcript():
    turns = [
        {"role": "user", "content": "What is A?"},
        {"role": "assistant", "content": "A is ..."},
        {"role": "user", "content": "And B?"},
    ]
    out = render_session_history(turns)
    assert "## Conversation so far" in out
    assert "User: What is A?" in out
    assert "Assistant: A is ..." in out
    assert "User: And B?" in out
    # ordering preserved
    assert out.index("What is A?") < out.index("And B?")


def test_render_excludes_non_conversational_roles():
    turns = [
        {"role": "user", "content": "Hi"},
        {"role": "system", "content": "secret system note"},
        {"role": "tool", "content": "tool output"},
        {"role": "assistant", "content": "hello"},
    ]
    out = render_session_history(turns)
    assert "secret system note" not in out
    assert "tool output" not in out
    assert "User: Hi" in out
    assert "Assistant: hello" in out


def test_render_limit_keeps_most_recent():
    turns = [
        {"role": "user", "content": f"m{i}"} for i in range(10)
    ]
    out = render_session_history(turns, limit=3)
    assert "m0" not in out
    assert "m9" in out
    assert out.count("User:") == 3


def test_turns_to_dicts_accepts_orm_like():
    class FakeTurn:
        def __init__(self, role, content):
            self.role = role
            self.content = content

    rows = [FakeTurn("user", "x"), FakeTurn("assistant", "y")]
    out = turns_to_dicts(rows)
    assert out == [{"role": "user", "content": "x"},
                   {"role": "assistant", "content": "y"}]


# ── extract_final_answer ───────────────────────────────────────────
def test_extract_prefers_final_answer():
    assert extract_final_answer({"final_answer": "the answer"}) == "the answer"


def test_extract_falls_back_to_final_content_str():
    assert extract_final_answer({"final_content": "via content"}) == "via content"


def test_extract_falls_back_to_final_content_dict():
    assert extract_final_answer(
        {"final_content": {"content": "nested"}}) == "nested"


def test_extract_falls_back_to_report_answer_output():
    assert extract_final_answer({"report": "rpt"}) == "rpt"
    assert extract_final_answer({"answer": "ans"}) == "ans"
    assert extract_final_answer({"output": {"text": "ot"}}) == "ot"


def test_extract_empty_when_missing():
    assert extract_final_answer({}) == ""
    assert extract_final_answer(None) == ""


# ── store: sessions & turns (T2.6) ────────────────────────────────
@pytest.mark.asyncio
async def test_ensure_session_idempotent(db):
    sid = uuid.uuid4()
    await ensure_session(session_id=sid, user_id=uuid.uuid4(), title="t")
    await ensure_session(session_id=sid, user_id=uuid.uuid4(), title="t2")
    turns = await list_turns(session_id=sid)
    assert turns == []  # no turns yet, but session exists exactly once


@pytest.mark.asyncio
async def test_append_and_list_turns_order(db):
    sid = uuid.uuid4()
    await append_turn(session_id=sid, role="user", content="q1")
    await append_turn(session_id=sid, role="assistant", content="a1")
    await append_turn(session_id=sid, role="user", content="q2")
    rows = await list_turns(session_id=sid)
    assert [t.role for t in rows] == ["user", "assistant", "user"]
    assert [t.content for t in rows] == ["q1", "a1", "q2"]
    assert [t.seq for t in rows] == [1, 2, 3]


@pytest.mark.asyncio
async def test_append_turn_links_run_id(db):
    sid = uuid.uuid4()
    rid = uuid.uuid4()
    t = await append_turn(session_id=sid, role="user", content="q", run_id=rid)
    assert t.run_id == rid


@pytest.mark.asyncio
async def test_list_turns_limit_keeps_recent(db):
    sid = uuid.uuid4()
    for i in range(5):
        await append_turn(session_id=sid, role="user", content=f"m{i}")
    rows = await list_turns(session_id=sid, limit=2)
    assert [t.content for t in rows] == ["m3", "m4"]


# ── session uuid mapping ───────────────────────────────────────────
def test_session_uuid_passthrough_for_uuid():
    u = uuid.uuid4()
    assert _session_uuid(str(u)) == u


def test_session_uuid_deterministic_for_string():
    a = _session_uuid("default")
    b = _session_uuid("default")
    assert a == b
    assert isinstance(a, uuid.UUID)
    # different strings -> different ids
    assert _session_uuid("other") != a


# ── orchestrator: history render + assistant backfill ─────────────
@pytest.mark.asyncio
async def test_orchestrator_writes_user_turn_and_renders_history(db, tmp_path, monkeypatch):
    orch = Orchestrator()
    # Stub the heavy parts: slot acquisition + the actual subprocess launch/pump.
    monkeypatch.setattr(orch, "_acquire_slot", AsyncMock())
    monkeypatch.setattr(orch, "_release_slot", AsyncMock())
    monkeypatch.setattr(orch, "_resolve_llm_env", AsyncMock(return_value=None))

    launched: dict[str, str] = {}

    def make_handle(run_id, params):
        from server.orchestrator import RunHandle

        return RunHandle(
            run_id=run_id, session_id=params["session_id"],
            proc=type("P", (), {"returncode": 0, "stdout": None})(),
        )

    async def fake_launch(self, run_id, params, *, history=""):
        launched[run_id] = history
        return make_handle(run_id, params)

    async def fake_pump(self, handle):
        # Simulate the worker emitting a run_finished frame with the answer.
        await self._backfill_assistant_turn(
            handle, {"type": "run_finished", "ok": True, "final_answer": "answer-A",
                     "stopped_by": "", "error": ""})

    monkeypatch.setattr(Orchestrator, "_launch", fake_launch)
    monkeypatch.setattr(Orchestrator, "_pump_frames", fake_pump)

    sid = "sess-t26"
    suuid = _session_uuid(sid)
    user_id = uuid.uuid4()

    # Drive the spawn path directly (bypassing the queue) for deterministic order.
    await ensure_session(session_id=suuid, user_id=user_id, title="t")
    run1 = uuid.uuid4().hex
    await append_turn(session_id=suuid, role="user", content="first question",
                      run_id=uuid.UUID(run1))
    await orch._spawn(
        run_id=run1, session_id=sid, session_uuid=suuid,
        prompt="first question", user_id=user_id,
    )
    rows = await list_turns(session_id=suuid)
    assert [t.role for t in rows] == ["user", "assistant"]
    assert rows[1].content == "answer-A"

    # Second message in the same session should render the prior transcript.
    run2 = uuid.uuid4().hex
    await append_turn(session_id=suuid, role="user", content="second question",
                      run_id=uuid.UUID(run2))
    await orch._spawn(
        run_id=run2, session_id=sid, session_uuid=suuid,
        prompt="second question", user_id=user_id,
    )
    hist = launched[run2]
    assert "first question" in hist
    assert "answer-A" in hist
    assert "second question" not in hist  # current turn excluded from history

    rows = await list_turns(session_id=suuid)
    assert [t.role for t in rows] == ["user", "assistant", "user", "assistant"]
    assert rows[2].content == "second question"
    assert rows[3].content == "answer-A"


@pytest.mark.asyncio
async def test_assistant_backfill_partial_tagging(db):
    orch = Orchestrator()
    suuid = uuid.uuid4()
    run_id = uuid.uuid4().hex
    params = {"run_id": run_id, "session_id": "x", "session_uuid": suuid}
    handle = type("H", (), {"run_id": run_id, "_params": params,
                            "session_id": "x"})()

    # Partial answer due to a user stop.
    await orch._backfill_assistant_turn(
        handle,
        {"type": "run_finished", "ok": False, "final_answer": "half done",
         "stopped_by": "user_stop", "error": ""},
    )
    rows = await list_turns(session_id=suuid)
    assert len(rows) == 1
    assert rows[0].role == "assistant"
    assert "half done" in rows[0].content
    assert "[partial: user_stop]" in rows[0].content


@pytest.mark.asyncio
async def test_assistant_backfill_skips_empty(db):
    orch = Orchestrator()
    suuid = uuid.uuid4()
    run_id = uuid.uuid4().hex
    params = {"run_id": run_id, "session_id": "x", "session_uuid": suuid}
    handle = type("H", (), {"run_id": run_id, "_params": params,
                            "session_id": "x"})()
    # Empty final answer -> no turn written.
    await orch._backfill_assistant_turn(
        handle, {"type": "run_finished", "ok": False, "final_answer": "",
                 "stopped_by": "", "error": "boom"})
    rows = await list_turns(session_id=suuid)
    assert rows == []


# ── worker: history injected as extra_input ───────────────────────
@pytest.mark.asyncio
async def test_worker_injects_history_as_extra_input(db, tmp_path, monkeypatch):
    from argparse import Namespace

    from server import worker as worker_mod

    run_id = uuid.uuid4().hex
    run_root = run_dir_for(run_id)
    run_root.mkdir(parents=True, exist_ok=True)
    (run_root / "history.txt").write_text(
        "## Conversation so far\nUser: prior q\nAssistant: prior a", encoding="utf-8")

    captured = {}

    class FakeBenchmarkSession:
        def __init__(self):
            self._entered = False

        async def __aenter__(self):
            self._entered = True
            return self

        async def __aexit__(self, *exc):
            return False

        async def run(self, instruction, *, meta=None, pipeline_id="", extra_input=None):
            captured["instruction"] = instruction
            captured["extra_input"] = extra_input or {}
            captured["meta"] = meta or {}
            return {"final_answer": "ok"}

    monkeypatch.setattr("benchmarks.public.core.kernel_adapter.BenchmarkSession",
                        FakeBenchmarkSession)
    monkeypatch.setattr("server.config.run_dir_for",
                        lambda rid: run_root if rid == run_id else run_dir_for(rid))

    args = Namespace(
        run_id=run_id, session_id="s", turn_index=1, prompt="current question",
        prompt_addendum="", pipeline_id="stateful-react-agent", backend="native",
        wall_time=10, max_turns=5, model="", base_url="", api_key="",
        agent_tools="",
    )
    # run_once is a *subprocess* entry point whose apply_env installs the
    # per-run environment into os.environ by contract. Running it in-process
    # here would leak CODING_WORKSPACE_ROOT / FRONTIER_AGENT_WORKSPACE_DIR /
    # SANDBOX_BACKEND into every later test (path authorization then resolves
    # /workspace to the leaked tmp dir and skips the sandbox branch).
    env_snapshot = dict(os.environ)
    try:
        rc = await worker_mod.run_once(args)
    finally:
        os.environ.clear()
        os.environ.update(env_snapshot)
    assert rc == 0
    assert captured["extra_input"].get("conversation_history") == (
        "## Conversation so far\nUser: prior q\nAssistant: prior a")
    assert captured["extra_input"].get("is_multi_turn") is True
    # Final answer written to summary.json for the orchestrator to read back.
    summary = (run_root / "summary.json").read_text(encoding="utf-8")
    assert "ok" in summary


@pytest.mark.asyncio
async def test_worker_no_history_when_absent(db, tmp_path, monkeypatch):
    from argparse import Namespace

    from server import worker as worker_mod

    run_id = uuid.uuid4().hex
    run_root = run_dir_for(run_id)
    run_root.mkdir(parents=True, exist_ok=True)
    # No history.txt written.

    captured = {}

    class FakeBenchmarkSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def run(self, instruction, *, meta=None, pipeline_id="", extra_input=None):
            captured["extra_input"] = extra_input or {}
            return {"final_answer": "ok"}

    monkeypatch.setattr("benchmarks.public.core.kernel_adapter.BenchmarkSession",
                        FakeBenchmarkSession)
    monkeypatch.setattr("server.config.run_dir_for",
                        lambda rid: run_root if rid == run_id else run_dir_for(rid))

    args = Namespace(
        run_id=run_id, session_id="s", turn_index=1, prompt="q",
        prompt_addendum="", pipeline_id="stateful-react-agent", backend="native",
        wall_time=10, max_turns=5, model="", base_url="", api_key="",
        agent_tools="",
    )
    env_snapshot = dict(os.environ)
    try:
        await worker_mod.run_once(args)
    finally:
        os.environ.clear()
        os.environ.update(env_snapshot)
    assert captured["extra_input"].get("conversation_history") == ""
    assert captured["extra_input"].get("is_multi_turn") is False
