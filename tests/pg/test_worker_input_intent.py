"""DATA-07/04 定向验收：worker 声明缺料意图 → API 落库（方案 A，2026-10-08）。

worker 不写库：只在 Run 目录留下 ``input-request.json``（use_case + reason）。
API 侧 ``materialize_worker_intent`` 按该用途对冻结快照裁决缺失字段后建请求，
并把来源 Run 置 ``stopped/input_required``；无意图、字段齐全时不建请求；重复调用幂等。
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select, text

from server import business_service as biz
from server import input_requests, store
from server.app import app
from server.security import create_access_token

pytestmark = pytest.mark.pg

CAPITAL = {
    "total_capital": "100000",
    "available_capital": "60000",
    "capital_basis": "total",
    "as_of": "2026-10-02T00:00:00Z",
}
#: 故意不填 allocated_capital：plan_analysis 仍缺料。
PLAN = {
    "symbol": "600519.SH",
    "market": "CN",
    "direction": "buy",
    "currency": "CNY",
}


@pytest.fixture
async def client(pg_clean):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://intent.test"
    ) as http:
        yield http


async def _new_user(name: str) -> tuple[str, uuid.UUID]:
    user_id = uuid.uuid4()
    async with biz.business_transaction() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, username, password_hash, status) "
                "VALUES (:id, :name, 'x', 'active')"
            ),
            {"id": user_id, "name": name},
        )
    return f"Bearer {create_access_token(user_id)}", user_id


async def _new_research(user_id: uuid.UUID) -> uuid.UUID:
    research_id = uuid.uuid4()
    async with biz.business_transaction() as session:
        await session.execute(
            text("INSERT INTO sessions (id, user_id, title) VALUES (:id, :uid, '研究')"),
            {"id": research_id, "uid": user_id, "title": "研究"},
        )
    return research_id


async def _bootstrap(client, name: str) -> tuple[uuid.UUID, str]:
    """建账户 + 计划 + 一个 general_reading Run，返回 (research_id, run_id)。"""
    token, user_id = await _new_user(name)
    research_id = await _new_research(user_id)
    account = await client.post(
        "/api/business/accounts",
        json={"name": "主账户", "base_currency": "CNY", "declared": dict(CAPITAL)},
        headers={"Authorization": token, "Idempotency-Key": "intent-acc"},
    )
    assert account.status_code == 201, account.text
    plan = await client.post(
        f"/api/business/sessions/{research_id}/plans",
        json={"name": "计划A", "declared": dict(PLAN)},
        headers={"Authorization": token, "Idempotency-Key": "intent-plan"},
    )
    assert plan.status_code == 201, plan.text
    submitted = await client.post(
        "/api/runs",
        json={
            "message": "研究一下这只股票",
            "session_id": str(research_id),
            "investment_input": {
                "use_case": "general_reading",
                "account": {"id": account.json()["account_id"]},
                "plan": {"id": plan.json()["plan_id"]},
                "idempotency_key": f"analyze:{uuid.uuid4()}",
            },
        },
        headers={"Authorization": token},
    )
    assert submitted.status_code == 202, submitted.text
    return research_id, submitted.json()["run_id"]


async def _run_dir(run_id: str) -> Path:
    async with biz.business_transaction() as session:
        run = await session.get(store.Run, uuid.UUID(run_id))
    assert run is not None and run.run_dir
    path = Path(run.run_dir)
    # stub orchestrator 不真正建目录；这里模拟 worker 写出意图文件。
    path.mkdir(parents=True, exist_ok=True)
    return path


async def _intent_count(research_id: uuid.UUID) -> int:
    async with biz.business_transaction() as session:
        return (
            await session.execute(
                select(func.count())
                .select_from(store.InputRequest)
                .where(store.InputRequest.research_id == research_id)
            )
        ).scalar_one()


async def test_worker_intent_is_materialized_once_with_derived_fields(client) -> None:
    research_id, run_id = await _bootstrap(client, "pg-intent-ok")
    run_dir = await _run_dir(run_id)
    (run_dir / "input-request.json").write_text(
        json.dumps(
            {
                "schema_version": "input-request/1",
                "use_case": "plan_analysis",
                "reason": "要给仓位结论，但没有本标的规划资金",
            }
        ),
        encoding="utf-8",
    )

    async with biz.business_transaction() as session:
        first = await input_requests.materialize_worker_intent(
            session, run_id=uuid.UUID(run_id)
        )
    assert first is not None and first["request_id"]

    # 重复调用（帧收尾 / 兜底 summary / 孤儿恢复三条路径都会走到）不产生第二条。
    async with biz.business_transaction() as session:
        await input_requests.materialize_worker_intent(session, run_id=uuid.UUID(run_id))
    assert await _intent_count(research_id) == 1

    async with biz.business_transaction() as session:
        row = (await session.execute(select(store.InputRequest))).scalars().one()
        run = await session.get(store.Run, uuid.UUID(run_id))
    # 用途来自 worker 意图；字段由服务端按用途裁决得出。
    assert row.use_case == "plan_analysis"
    assert "plan.allocated_capital" in {field["name"] for field in row.fields_json}
    assert row.source_run_id == uuid.UUID(run_id)
    # 来源 Run 以 input_required 结束（不是 completed/failed）。
    assert (run.status, run.stopped_by) == ("stopped", "input_required")


async def test_no_intent_or_complete_fields_creates_nothing(client) -> None:
    research_id, run_id = await _bootstrap(client, "pg-intent-none")
    async with biz.business_transaction() as session:
        assert (
            await input_requests.materialize_worker_intent(session, run_id=uuid.UUID(run_id))
        ) is None
    assert await _intent_count(research_id) == 0
