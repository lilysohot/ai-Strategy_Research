"""真 PG 联合验收：DATA-15 可控模型端到端链路与成本计量（server-side DATA 部分）。

与既有批次证据的关系（本文件不重复覆盖的场景登记在 issue 与环境基线）：

* 领取后崩溃及恢复（租约过期回收 / 已启动不重投）→ ``test_run_dispatch.py``；
* 幂等重放 / 提交原子性 → ``test_run_dispatch.py``、``test_business_repairs.py``；
* 所有者隔离、监控零模型、预算阻塞、取消竞争 → 各 watch/business 测试文件。

本文件新增三类联合场景：

1. **真实 worker 端到端**：路由提交（PG 快照冻结）→ outbox 派发 → 真实
   ``Orchestrator`` 派发真实 worker 子进程（MockLLMServer，用户 LLM 配置经真实
   解密注入链）→ 轨迹/产物/diff 文件链路 → Run 终态与用量计量 → 快照不变
   （AC-06）；随后生成的活体数据直接通过 DATA-14 恢复核对（AC-18）。
2. **AC-20 缓存读写分列**：合成轨迹（新旧两种 usage 别名）→ 聚合 → Run 行 →
   ``usage_summary_for_runs`` 分列报告，不塌缩成单一 "cached"。
3. **零用量 Run 可见**：成本比较不得静默丢弃未计量 Run。
"""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import select

from deploy.huggingface.mock_llm import MockLLMServer, text_turn
from server import business_service as biz
from server import dispatch_outbox as dispatch
from server import orchestrator as orch_mod
from server import restore_check, store, usage
from server.app import app
from server.config import run_dir_for
from server.crypto import encrypt_api_key
from server.security import create_access_token
from server.store import update_run_usage

pytestmark = pytest.mark.pg

TERMINAL_STATUSES = {"completed", "failed", "stopped"}
MOCK_MODEL = "mock-frontier-model"


@pytest.fixture
async def case(pg_clean, monkeypatch):
    """业务资料 + HTTP 客户端（与 test_business_repairs.case 同构，最小化）。"""
    monkeypatch.setenv("OPENAI_BASE_URL", "http://unset-in-test.invalid")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-data15-fallback-guard")
    monkeypatch.setenv("OPENAI_MODEL", MOCK_MODEL)
    uid, rid = uuid.uuid4(), uuid.uuid4()
    async with biz.business_transaction() as session:
        session.add(store.User(id=uid, username=f"data15-{uid.hex[:8]}", password_hash="unused"))
        await session.flush()
        session.add(store.Session(id=rid, user_id=uid, title="data15"))
        await session.flush()
        account = await biz.create_account(
            session,
            user_id=uid,
            name="data15-account",
            base_currency="CNY",
            declared={
                "total_capital": "100000",
                "currency": "CNY",
                "capital_basis": "total",
                "as_of": "2026-10-07T00:00:00Z",
            },
            idempotency_key=uuid.uuid4().hex,
        )
        plan = await biz.create_plan(
            session,
            user_id=uid,
            research_id=rid,
            name="data15-plan",
            declared={
                "symbol": "600519.SH",
                "market": "CN",
                "direction": "buy",
                "plan_price": "20",
                "target_price": "25",
                "currency": "CNY",
            },
            idempotency_key=uuid.uuid4().hex,
        )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://data15.test"
    ) as client:
        yield SimpleNamespace(
            uid=uid,
            rid=rid,
            aid=uuid.UUID(account.result["account_id"]),
            pid=uuid.UUID(plan.result["plan_id"]),
            client=client,
            headers={"Authorization": f"Bearer {create_access_token(uid)}"},
        )


@pytest.fixture
async def real_orchestrator(case, monkeypatch, stub_orchestrator):
    """把三处 get_orchestrator 调用点换回真实编排器（本文件需要真实 worker）。"""
    real = orch_mod.Orchestrator()
    monkeypatch.setattr(orch_mod, "get_orchestrator", lambda: real)
    monkeypatch.setattr("server.routes.runs.get_orchestrator", lambda: real)
    monkeypatch.setattr("server.routes.business.get_orchestrator", lambda: real)
    return real


async def _wait_terminal(run_id: uuid.UUID, *, timeout_s: float = 120.0) -> store.Run:
    """等终态 + 用量落盘：终态先写、用量紧随其后（update_run_result → update_run_usage），
    是设计上的两个写入点，测试必须等到计量完成再断言。"""
    deadline = asyncio.get_event_loop().time() + timeout_s
    while asyncio.get_event_loop().time() < deadline:
        async with biz.business_transaction() as session:
            row = await session.get(store.Run, run_id)
            if row is not None and row.status in TERMINAL_STATUSES and row.usage_json:
                await session.refresh(row)
                return row
        await asyncio.sleep(0.5)
    raise AssertionError(f"Run {run_id} 未在 {timeout_s}s 内到达终态并完成用量计量")


async def test_real_worker_chain_end_to_end(case, real_orchestrator):
    with MockLLMServer(script=[text_turn("analysis complete from mock model")]) as mock:
        # 用户默认 LLM 配置指向 mock 端点：派发链用真实解密注入（T2.5 全有或全无）。
        async with biz.business_transaction() as session:
            session.add(
                store.UserLLMConfig(
                    user_id=case.uid,
                    name="mock",
                    base_url=mock.base_url,
                    model=MOCK_MODEL,
                    api_key_cipher=encrypt_api_key("sk-data15-test"),
                    is_default=True,
                )
            )
        response = await case.client.post(
            "/api/runs",
            json={
                "message": "analyse the frozen plan",
                "session_id": str(case.rid),
                "investment_input": {
                    "use_case": "plan_analysis",
                    "account": {"id": str(case.aid)},
                    "plan": {"id": str(case.pid)},
                    "idempotency_key": uuid.uuid4().hex,
                },
            },
            headers=case.headers,
        )
        assert response.status_code == 202, response.text
        run_id = uuid.UUID(response.json()["run_id"])

        dispatched = await dispatch.dispatch_once(real_orchestrator)
        assert dispatched == 1, "outbox 必须成功领取并派发"

        row = await _wait_terminal(run_id)

    # 终态与用量计量（计量来自真实轨迹，不是脚本伪造）。
    # 终态映射（T2.8）：mock 模型最后一轮为纯文本回复（无工具调用），运行以
    # stopped_by="no_tool" 自然结束 → 状态为 "stopped" 且带完整 final_answer；
    # "completed" 保留给真实多轮任务以工具收尾的路径。
    assert row.status == "stopped", row.error
    assert row.stopped_by == "no_tool"
    assert row.final_answer == "analysis complete from mock model"
    assert row.llm_calls and row.llm_calls >= 1
    assert row.prompt_tokens and row.prompt_tokens > 0
    assert row.completion_tokens and row.completion_tokens > 0
    assert row.usage_json and row.usage_json.get("status") == "complete"
    assert MOCK_MODEL in (row.usage_json.get("models") or [])

    # 文件链路：轨迹、diff、目录树与提交流程的 run_dir 登记一致。
    run_root = run_dir_for(run_id.hex)
    assert (run_root / "run" / "agent" / "trajectories" / "react_agent.jsonl").exists()
    assert (run_root / "diff.json").exists()
    assert row.run_dir == str(run_root)

    # AC-06：Run 执行不影响提交那一刻冻结的快照。
    async with biz.business_transaction() as session:
        snapshot = (
            await session.execute(
                select(store.RunInvestmentSnapshot).where(
                    store.RunInvestmentSnapshot.run_id == run_id
                )
            )
        ).scalar_one()
        # 快照值为 Numeric 归一化后的十进制文本（DATA-03 精度契约）。
        assert snapshot.resolved_json["account.total_capital"]["value"] == "100000.0000000000"
        assert snapshot.account_revision == 1

        # 派发终态：outbox 行留在 DISPATCHED（已派发，终态由 Run 状态承载）。
        dispatch_row = (
            await session.execute(
                select(store.RunDispatch).where(store.RunDispatch.run_id == run_id)
            )
        ).scalar_one()
        assert dispatch_row.status == dispatch.DISPATCHED

    # AC-18 联动：活体生成物直接通过 DATA-14 恢复核对。
    async with biz.business_transaction() as session:
        report = await restore_check.check_restore(session)
    assert report["ok"] is True, report["errors"]
    assert report["external_calls"]["run_dispatch_rows"] == 1

    # AC-20：汇总口径包含这条真实 Run，缓存读写按行分列（mock 不产缓存，记 0）。
    summary = usage.usage_summary_for_runs([row])
    assert summary["run_count"] == 1
    assert summary["totals"]["llm_calls"] == row.llm_calls
    assert summary["totals"]["prompt_tokens"] == row.prompt_tokens
    assert summary["totals"]["cache_read_tokens"] == 0
    assert summary["totals"]["cache_write_tokens"] == 0
    assert summary["runs"][0]["duration_s"] is not None


async def test_cache_read_and_write_reported_separately(pg_clean):
    """AC-20：分别报告缓存读写，不只报告命中率（新旧别名都要识别）。"""
    aggregate = usage.aggregate_usage(
        [
            {
                "t": "llm",
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 20,
                    "total_tokens": 120,
                    "cache_read_tokens": 80,
                    "cache_write_tokens": 30,
                },
            },
            {
                "t": "llm",
                "usage": {
                    "prompt_tokens": 50,
                    "completion_tokens": 10,
                    "cached_tokens": 40,  # 旧别名 → cache_read
                    "cache_creation_tokens": 25,  # 旧别名 → cache_write
                },
            },
            {"t": "result"},  # 非 llm 行不计量
        ]
    )
    assert aggregate["llm_calls"] == 2
    assert aggregate["prompt_tokens"] == 150
    assert aggregate["completion_tokens"] == 30
    assert aggregate["cache_read_tokens"] == 120  # 80 + 40，与写分列
    assert aggregate["cache_write_tokens"] == 55  # 30 + 25，与读分列

    run_id = uuid.uuid4()
    uid, rid = uuid.uuid4(), uuid.uuid4()
    async with biz.business_transaction() as session:
        session.add(store.User(id=uid, username=f"cache-{uid.hex[:8]}", password_hash="unused"))
        await session.flush()
        session.add(store.Session(id=rid, user_id=uid, title="cache"))
        await session.flush()
        session.add(
            store.Run(
                id=run_id,
                session_id=rid,
                user_id=uid,
                status="completed",
                pipeline_id="stateful-react-agent",
                prompt="cache-split",
                run_dir=str(run_dir_for(run_id.hex)),
            )
        )
    await update_run_usage(run_id=run_id, usage=aggregate)
    async with biz.business_transaction() as session:
        row = await session.get(store.Run, run_id)
        summary = usage.usage_summary_for_runs([row])
    assert summary["totals"]["cache_read_tokens"] == 120
    assert summary["totals"]["cache_write_tokens"] == 55
    assert summary["runs"][0]["cache_read_tokens"] != summary["runs"][0]["cache_write_tokens"]


async def test_zero_usage_run_stays_visible_in_summary(case):
    """未计量 Run 在成本比较中必须可见（0 值），不得静默丢弃。"""
    response = await case.client.post(
        "/api/runs",
        json={"message": "legacy run without business input", "session_id": str(case.rid)},
        headers=case.headers,
    )
    assert response.status_code == 202, response.text
    run_id = uuid.UUID(response.json()["run_id"])
    async with biz.business_transaction() as session:
        row = await session.get(store.Run, run_id)
        row.status = "failed"  # 直接置于终态（未派发、无轨迹）
        summary = usage.usage_summary_for_runs([row])
    assert summary["run_count"] == 1
    assert summary["runs"][0]["llm_calls"] == 0
    assert summary["runs"][0]["usage_status"] is None
    assert summary["totals"]["prompt_tokens"] == 0
