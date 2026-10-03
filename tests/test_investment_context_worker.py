from __future__ import annotations

import json
import os
import uuid
from argparse import Namespace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from server.config import run_dir_for
from server.investment_context import ResolvedInvestmentContext


@pytest.mark.asyncio
async def test_worker_injects_context_as_data_and_binds_only_guarded_tool(monkeypatch) -> None:
    from server import worker

    run_id = uuid.uuid4().hex
    run_root = run_dir_for(run_id)
    run_root.mkdir(parents=True, exist_ok=True)
    context = {
        "schema_version": "business-snapshot/1",
        "run_id": run_id,
        "research_id": str(uuid.uuid4()),
        "snapshot_id": str(uuid.uuid4()),
        "use_case": "plan_analysis",
        "values": {"account.total_capital": {"value": "100000", "status": "user_provided"}},
        "missing": {},
    }
    (run_root / "investment-context.json").write_text(
        json.dumps(context), encoding="utf-8"
    )
    captured: dict[str, object] = {}

    class FakeBenchmarkSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def run(self, instruction, *, meta=None, pipeline_id="", extra_input=None):
            captured["instruction"] = instruction
            captured["meta"] = meta or {}
            return {"final_answer": "ok"}

    monkeypatch.setattr(
        "benchmarks.public.core.kernel_adapter.BenchmarkSession", FakeBenchmarkSession
    )
    args = Namespace(
        run_id=run_id,
        session_id="research",
        turn_index=1,
        prompt="analyse this plan",
        prompt_addendum="",
        pipeline_id="stateful-react-agent",
        backend="native",
        wall_time=10,
        max_turns=5,
        model="",
        base_url="",
        api_key="",
        agent_tools="position_sizing,market_quote",
    )
    env = dict(os.environ)
    try:
        assert await worker.run_once(args) == 0
    finally:
        os.environ.clear()
        os.environ.update(env)

    instruction = str(captured["instruction"])
    assert instruction.count("<investment_context_data>") == 1
    assert '"account.total_capital"' in instruction
    metadata = captured["meta"]
    tools = metadata["profile_overrides"]["agent"]["agent_tools"]
    assert "investment_context" in tools
    assert "investment_position_sizing" in tools
    assert "position_sizing" not in tools
    assert "BUSINESS CONTEXT POLICY" in metadata["_sys_prompt_addendum"]
    assert json.loads((run_root / "investment-context-tools.json").read_text()) == {
        "context_reads": 0,
        "lint_calls": 0,
        "sizing_calls": 0,
    }


def test_worker_rejects_context_from_another_run(tmp_path) -> None:
    from server.worker import _load_investment_context

    (tmp_path / "investment-context.json").write_text(
        json.dumps({"run_id": uuid.uuid4().hex}), encoding="utf-8"
    )
    with pytest.raises(RuntimeError, match="does not belong"):
        _load_investment_context(tmp_path, uuid.uuid4().hex)


@pytest.mark.asyncio
async def test_metrics_write_failure_still_releases_context(monkeypatch, tmp_path) -> None:
    from plugins.tools.investment_context import bind_investment_context, investment_context
    from server.worker import _finalize_investment_context

    tokens = bind_investment_context({"run_id": uuid.uuid4().hex, "values": {}})

    def fail_write(*args, **kwargs):
        raise OSError("disk unavailable")

    monkeypatch.setattr("pathlib.Path.write_text", fail_write)
    _finalize_investment_context(tmp_path, tokens)
    result = json.loads(await investment_context.ainvoke({}))
    assert result["ok"] is False


@pytest.mark.asyncio
async def test_orchestrator_materializes_authenticated_context_without_db_credentials(
    monkeypatch,
) -> None:
    from server.orchestrator import Orchestrator

    run_id = uuid.uuid4()
    user_id = uuid.uuid4()
    data = {
        "schema_version": "business-snapshot/1",
        "run_id": run_id.hex,
        "research_id": str(uuid.uuid4()),
        "values": {},
        "missing": {},
    }

    class FakeResolver:
        calls = 1
        cache_reads = 0
        cache_writes = 1

        async def resolve(self, *, run_id, user_id):
            return ResolvedInvestmentContext(data=data, digest="digest", cache_hit=False)

    fake_process = SimpleNamespace(stdin=SimpleNamespace(), stdout=None, returncode=None, pid=1)
    spawn = AsyncMock(return_value=fake_process)
    monkeypatch.setattr("asyncio.create_subprocess_exec", spawn)
    orchestrator = Orchestrator()
    orchestrator._investment_context_resolver = FakeResolver()
    monkeypatch.setattr(orchestrator, "_acquire_slot", AsyncMock())
    monkeypatch.setattr(
        orchestrator,
        "_resolve_llm_env",
        AsyncMock(
            return_value={
                "OPENAI_MODEL": "model",
                "OPENAI_BASE_URL": "https://example.test/v1",
                "OPENAI_API_KEY": "secret",
            }
        ),
    )
    await orchestrator._launch(
        run_id.hex,
        {
            "session_id": str(uuid.uuid4()),
            "prompt": "q",
            "turn_index": 1,
            "user_id": user_id,
            "agent_tools": "",
            "prompt_addendum": "",
        },
    )
    assert json.loads((run_dir_for(run_id.hex) / "investment-context.json").read_text()) == data
    child_env = spawn.await_args.kwargs["env"]
    assert child_env["SERVER_DATABASE_URL"] == "sqlite+aiosqlite:///:memory:"
    assert child_env["SERVER_DATABASE_URL_DOCKER"] == ""
    assert child_env["SERVER_MASTER_KEY"] == ""
    assert child_env["SERVER_JWT_SECRET"] == ""
    assert child_env["OPENAI_API_KEY"] == "secret"


@pytest.mark.asyncio
async def test_orchestrator_removes_stale_context_after_failed_auth_resolution(
    monkeypatch,
) -> None:
    from server.orchestrator import Orchestrator

    run_id = uuid.uuid4()
    user_id = uuid.uuid4()
    run_root = run_dir_for(run_id.hex)
    run_root.mkdir(parents=True, exist_ok=True)
    context_path = run_root / "investment-context.json"
    metrics_path = run_root / "investment-context-resolver.json"
    context_path.write_text(json.dumps({"run_id": run_id.hex}), encoding="utf-8")
    metrics_path.write_text("{}", encoding="utf-8")

    class MissingResolver:
        async def resolve(self, *, run_id, user_id):
            return None

    fake_process = SimpleNamespace(stdin=SimpleNamespace(), stdout=None, returncode=None, pid=1)
    spawn = AsyncMock(return_value=fake_process)
    monkeypatch.setattr("asyncio.create_subprocess_exec", spawn)
    orchestrator = Orchestrator()
    orchestrator._investment_context_resolver = MissingResolver()
    monkeypatch.setattr(orchestrator, "_acquire_slot", AsyncMock())
    monkeypatch.setattr(orchestrator, "_resolve_llm_env", AsyncMock(return_value=None))
    await orchestrator._launch(
        run_id.hex,
        {
            "session_id": str(uuid.uuid4()),
            "prompt": "q",
            "turn_index": 1,
            "user_id": user_id,
            "agent_tools": "",
            "prompt_addendum": "",
        },
    )
    assert not context_path.exists()
    assert not metrics_path.exists()
