"""T2.11 usage-metering tests (mock LLM for the end-to-end path).

Covers what plan.md T2.11 asks for:

  * token usage is aggregated from the **runtime trajectory** (one ``llm`` record
    per turn, each carrying the normalised ``usage`` dict) — the platform never
    installs its own UsageObserver;
  * prompt / completion / total / cache_read / cache_write / reasoning tokens and
    the metered call count land on the Run row at the run's terminal state;
  * a stopped run is still metered (the tokens were spent regardless).
"""

from __future__ import annotations

import asyncio
import json
import uuid

import pytest

from deploy.huggingface.mock_llm import MockLLMServer, text_turn, tool_call_turn
from server.config import get_config, run_dir_for
from server.store import (
    create_run,
    get_run,
    init_db,
    update_run_usage,
)
from server.usage import aggregate_usage, usage_for_run


@pytest.fixture
async def app_client():
    from httpx import ASGITransport, AsyncClient

    from server.app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
async def auth_headers(app_client):
    await init_db()
    pwd = "Str0ngPass1"
    reg = await app_client.post(
        "/api/auth/register", json={"username": "t211-user", "password": pwd}
    )
    assert reg.status_code in (201, 409), reg.text
    login = await app_client.post(
        "/api/auth/login", json={"username": "t211-user", "password": pwd}
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _user_id(auth_headers: dict) -> uuid.UUID:
    from server.security import decode_access_token

    token = auth_headers["Authorization"].removeprefix("Bearer ").strip()
    return decode_access_token(token)


def _llm_rec(usage: dict) -> dict:
    return {"t": "llm", "turn": 1, "content": "hi", "usage": usage}


# ── aggregate_usage ─────────────────────────────────────────────


def test_aggregate_sums_every_turn():
    """One llm record per turn; the aggregate is their sum."""
    recs = [
        _llm_rec({"prompt_tokens": 100, "completion_tokens": 20,
                  "total_tokens": 120, "cache_read_tokens": 5,
                  "cache_write_tokens": 2, "reasoning_tokens": 0,
                  "model": "m", "provider": "p"}),
        _llm_rec({"prompt_tokens": 50, "completion_tokens": 10,
                  "total_tokens": 60, "cache_read_tokens": 1,
                  "cache_write_tokens": 0, "reasoning_tokens": 3,
                  "model": "m", "provider": "p"}),
    ]
    agg = aggregate_usage(recs)
    assert agg["prompt_tokens"] == 150
    assert agg["completion_tokens"] == 30
    assert agg["total_tokens"] == 180
    assert agg["cache_read_tokens"] == 6
    assert agg["cache_write_tokens"] == 2
    assert agg["reasoning_tokens"] == 3
    assert agg["llm_calls"] == 2
    assert agg["models"] == ["m"]
    assert agg["providers"] == ["p"]


def test_aggregate_ignores_non_llm_records():
    """start / result / compaction carry no usage and contribute nothing."""
    recs = [
        {"t": "start", "model_name": "m"},
        {"t": "result", "name": "bash", "ms": 12},
        {"t": "compaction"},
        _llm_rec({"prompt_tokens": 7, "completion_tokens": 3}),
    ]
    agg = aggregate_usage(recs)
    assert agg["llm_calls"] == 1
    assert agg["prompt_tokens"] == 7


def test_aggregate_derives_total_when_provider_omits_it():
    """A missing/zero total_tokens falls back to prompt + completion."""
    agg = aggregate_usage([
        _llm_rec({"prompt_tokens": 40, "completion_tokens": 10}),
    ])
    assert agg["total_tokens"] == 50


def test_aggregate_counts_only_metered_turns():
    """A turn that reported no usage is not a billable call."""
    recs = [
        _llm_rec({"prompt_tokens": 1, "completion_tokens": 1}),
        {"t": "llm", "turn": 2, "content": "no usage here"},
        {"t": "llm", "turn": 3, "content": "", "usage": {}},
    ]
    agg = aggregate_usage(recs)
    assert agg["llm_calls"] == 1
    assert agg["prompt_tokens"] == 1


def test_aggregate_falls_back_to_legacy_cache_aliases():
    """Pre-split adapters expose cached_tokens / cache_creation_tokens."""
    agg = aggregate_usage([
        _llm_rec({"prompt_tokens": 10, "cached_tokens": 4,
                  "cache_creation_tokens": 9}),
    ])
    assert agg["cache_read_tokens"] == 4
    assert agg["cache_write_tokens"] == 9


def test_aggregate_empty_is_zeroed():
    agg = aggregate_usage([])
    assert agg["prompt_tokens"] == 0
    assert agg["llm_calls"] == 0
    assert agg["models"] == []


def test_usage_for_run_missing_trajectory_is_best_effort(monkeypatch, tmp_path):
    """A run with no trajectory meters as zero rather than raising."""
    monkeypatch.setattr(get_config(), "runs_root", tmp_path)
    agg = usage_for_run("no-such-run-id")
    assert agg["total_tokens"] == 0
    assert agg["llm_calls"] == 0


def test_usage_for_run_reads_trajectory_file(monkeypatch, tmp_path):
    """The aggregate is read from the runtime's own react_agent.jsonl."""
    monkeypatch.setattr(get_config(), "runs_root", tmp_path)
    run_id = "abc123"
    traj = tmp_path / run_id / "run" / "agent" / "trajectories"
    traj.mkdir(parents=True)
    (traj / "react_agent.jsonl").write_text(
        json.dumps(_llm_rec({"prompt_tokens": 11, "completion_tokens": 4}))
        + "\n"
        + json.dumps({"t": "result", "name": "bash"})
        + "\n",
        encoding="utf-8",
    )
    agg = usage_for_run(run_id)
    assert agg["prompt_tokens"] == 11
    assert agg["completion_tokens"] == 4
    assert agg["llm_calls"] == 1


# ── persistence ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_run_usage_persists_counters(app_client, auth_headers):
    await init_db()
    uid = _user_id(auth_headers)
    rid = uuid.uuid4()
    sid = uuid.uuid4()
    from server.store import ensure_session

    await ensure_session(session_id=sid, user_id=uid, title="t")
    await create_run(run_id=rid, session_id=sid, user_id=uid, prompt="p",
                     pipeline_id="stateful-react-agent", run_dir="/tmp/x",
                     status="completed")

    usage = {
        "prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120,
        "cache_read_tokens": 5, "cache_write_tokens": 2,
        "reasoning_tokens": 1, "llm_calls": 3,
        "models": ["m"], "providers": ["p"],
    }
    await update_run_usage(run_id=rid, usage=usage)

    row = await get_run(run_id=rid, user_id=uid)
    assert row is not None
    assert row.prompt_tokens == 100
    assert row.completion_tokens == 20
    assert row.total_tokens == 120
    assert row.cache_read_tokens == 5
    assert row.cache_write_tokens == 2
    assert row.reasoning_tokens == 1
    assert row.llm_calls == 3
    assert row.usage_json["models"] == ["m"]


# ── end-to-end: a real run is metered from its trajectory ───────


@pytest.fixture
async def mock_llm_two_turns():
    server = MockLLMServer(script=[
        tool_call_turn("create_file", {
            "path": "/outputs/note.md",
            "content": "# Note\nmetered run\n",
        }),
        text_turn("Wrote the note."),
    ]).start()
    yield server
    server.stop()


@pytest.fixture
def isolated_orchestrator(monkeypatch):
    """Swap in a private Orchestrator so a leftover run from another test file
    cannot occupy the concurrency slot this test's run needs."""
    import server.orchestrator as orch_mod

    orch = orch_mod.Orchestrator()
    monkeypatch.setattr(orch_mod, "_orchestrator", orch)
    return orch


def _spawn_approver(orch, run_id: str, client, headers):
    """Answer the P3.2 approval gate the way a user would.

    Since the gate landed (P3.2), a worker's ``create_file`` suspends on
    ``approval_requested`` until a decision arrives — an old e2e that never
    answers would hang the worker for the gate's 300s timeout. This task
    subscribes to the run's event fan-out and approves ``once`` via the real
    API route, so the approval path itself stays exercised.
    """

    async def run() -> None:
        q = orch.subscribe(run_id)
        while True:
            evt = await asyncio.wait_for(q.get(), timeout=90)
            if evt and evt.get("type") == "approval_requested":
                resp = await client.post(
                    f"/api/runs/{run_id}/approve",
                    json={"approval_id": evt["approval_id"], "decision": "once"},
                    headers=headers,
                )
                assert resp.status_code == 200, resp.text
                return

    return asyncio.ensure_future(run())


@pytest.mark.asyncio
async def test_run_is_metered_from_trajectory(mock_llm_two_turns, app_client,
                                              auth_headers, isolated_orchestrator,
                                              monkeypatch):
    """T2.11 end-to-end: a finished run's tokens are summed onto the Run row."""
    monkeypatch.setenv("OPENAI_BASE_URL", mock_llm_two_turns.base_url)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-spike-mock")
    monkeypatch.setenv("OPENAI_MODEL", mock_llm_two_turns.model)
    cfg = get_config()
    monkeypatch.setattr(cfg, "wall_timeout_s", 120)
    monkeypatch.setattr(cfg, "worker_pool_size", 1)
    await init_db()

    resp = await app_client.post(
        "/api/runs",
        json={"message": "write a note with create_file",
              "session_id": "t211-usage"},
        headers=auth_headers,
    )
    assert resp.status_code == 202, resp.text
    run_id = resp.json()["run_id"]
    approver = _spawn_approver(
        isolated_orchestrator, run_id, app_client, auth_headers
    )

    # The orchestrator meters once the worker is gone; poll for the counters.
    row = None
    for _ in range(120):
        await asyncio.sleep(0.5)
        row = await get_run(run_id=uuid.UUID(run_id), user_id=_user_id(auth_headers))
        if row is not None and row.finished_at is not None and row.llm_calls:
            break
    assert row is not None
    assert row.finished_at is not None, "run never reached a terminal state"
    assert row.llm_calls and row.llm_calls >= 1, "run was never metered"
    assert row.prompt_tokens and row.prompt_tokens > 0
    assert row.completion_tokens and row.completion_tokens > 0
    assert row.total_tokens == row.prompt_tokens + row.completion_tokens
    # cache_* are summed independently (mock reports 0, but the columns must be
    # populated rather than left NULL).
    assert row.cache_read_tokens is not None
    assert row.cache_write_tokens is not None
    assert row.reasoning_tokens is not None

    # Metering agrees with a fresh re-aggregation of the same trajectory —
    # the file is the source of truth, so a re-scan must reproduce the numbers.
    fresh = usage_for_run(run_id)
    assert fresh["prompt_tokens"] == row.prompt_tokens
    assert fresh["completion_tokens"] == row.completion_tokens
    assert fresh["llm_calls"] == row.llm_calls

    # The trajectory the aggregate came from really exists for this run.
    assert (run_dir_for(run_id) / "run" / "agent" / "trajectories"
            / "react_agent.jsonl").exists()

    # The approver task has posted its decision and returned.
    await asyncio.wait_for(approver, timeout=5)
