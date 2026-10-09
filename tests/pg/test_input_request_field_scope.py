"""补数回答的字段范围与无快照续接：2026-10-09 缺陷回归。

实测（2026-10-09，补数弹窗）：按 PRD §4.2 一次收集"规划资金（必需）+ 承受风险/期望盈利
（可后补）"，但后两项依用途裁决并不是本次请求的字段；回答端点却额外要求"只能回答本次
请求列举的字段"，于是整条回答被 `400 unknown_field_rejected` 拒掉——弹窗永远保存不了。

同一批还有两个连通缺口（研究还没有账户/计划时最明显）：

* 无快照续接把账户/计划引用冻结成 ``null``，用户"先创建主账户"后回答仍会撞
  ``persist_declared`` 的"保存资料需要明确的目标对象"；
* 无快照续接不记录当时版本，问答双方都拿不到期望版本，回答会撞"回答缺少资料版本"。

本文件锁三件事：契约内字段可随回答落库（AC-30）、冻结引用为 ``null`` 时按研究当前绑定
补全、已有对象时续接记下版本。负例固定"契约外字段仍被拒"，防止放宽被误读成放开契约。
"""

from __future__ import annotations

import json
import uuid
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select

from server import business_service as biz
from server import input_requests, store
from server.app import app
from server.security import create_access_token

pytestmark = pytest.mark.pg

ACCOUNT = {
    "total_capital": "200000",
    "available_capital": "200000",
    "capital_basis": "tradable_assets",
    "currency": "CNY",
    "as_of": "2026-10-09T00:00:00Z",
}
PLAN = {
    "symbol": "600519.SH",
    "market": "CN",
    "direction": "buy",
    "allocated_capital": "20000",
    "currency": "CNY",
}
#: 计划齐备但**缺本标的规划资金**：PRD §4.2 弹窗要采集的那一项。
PLAN_PENDING_CAPITAL = {
    "symbol": "600519.SH",
    "market": "CN",
    "direction": "buy",
    "currency": "CNY",
}
#: 无账户/无计划时按用途裁决出的 8 个字段（`evaluate_purpose` 结果）。
DERIVED_FIELDS = [
    "account.as_of",
    "account.capital_basis",
    "account.currency",
    "account.total_capital",
    "plan.allocated_capital",
    "plan.direction",
    "plan.market",
    "plan.symbol",
]


@pytest.fixture
async def client(pg_clean):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://field-scope.test"
    ) as http:
        yield http


async def _research(client, name: str) -> tuple[dict[str, str], uuid.UUID, uuid.UUID]:
    """建用户 + 研究（**不建**账户/计划），返回 (headers, user_id, research_id)。"""
    user_id, research_id = uuid.uuid4(), uuid.uuid4()
    async with biz.business_transaction() as session:
        session.add(store.User(id=user_id, username=f"{name}-{user_id.hex}", password_hash="x"))
        await session.flush()
        session.add(store.Session(id=research_id, user_id=user_id, title=name))
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}, user_id, research_id


async def _bind_account_and_plan(
    user_id: uuid.UUID, research_id: uuid.UUID, *, declared: dict[str, dict] | None = None
) -> tuple[uuid.UUID, uuid.UUID]:
    """按 PRD §4.2 步 2 / §4.1 补齐主账户与会话主计划，并绑定到该研究。

    ``declared`` 可按组覆盖（例如只填总资金的账户），其余用完整资料。
    """
    values = declared or {}
    async with biz.business_transaction() as session:
        account = await biz.create_account(
            session,
            user_id=user_id,
            name="主账户",
            base_currency="CNY",
            declared=dict(values.get("account") or ACCOUNT),
            idempotency_key=f"field-scope-account:{uuid.uuid4()}",
        )
        plan = await biz.create_plan(
            session,
            user_id=user_id,
            research_id=research_id,
            name="计划A",
            declared=dict(values.get("plan") or PLAN_PENDING_CAPITAL),
            idempotency_key=f"field-scope-plan:{uuid.uuid4()}",
        )
        account_id = uuid.UUID(account.result["account_id"])
        plan_id = uuid.UUID(plan.result["plan_id"])
        await biz.set_research_link(
            session,
            user_id=user_id,
            research_id=research_id,
            account_id=account_id,
            primary_plan_id=plan_id,
            idempotency_key=f"field-scope-link:{uuid.uuid4()}",
        )
    return account_id, plan_id


async def _worker_intent_request(
    user_id: uuid.UUID, research_id: uuid.UUID, tmp_root: Path, tag: str
) -> tuple[uuid.UUID, store.InputRequest]:
    """走 worker 意图 → API 落库，拿到一条 pending 请求（`source_run_id=None` 形态）。"""
    run_id = uuid.uuid4()
    run_dir = tmp_root / tag
    run_dir.mkdir(parents=True, exist_ok=True)
    async with biz.business_transaction() as session:
        store.add_run(
            session,
            run_id=run_id,
            session_id=research_id,
            user_id=user_id,
            prompt="按当前资料给个仓位结论",
            pipeline_id="stateful-react-agent",
            run_dir=str(run_dir),
        )
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
        outcome = await input_requests.materialize_worker_intent(session, run_id=run_id)
        assert outcome is not None
        request_id = uuid.UUID(outcome["request_id"])
        row = await session.get(store.InputRequest, request_id)
        assert row is not None
        await session.refresh(row)
    return request_id, row


async def _answer(client, request_id, declared, *, headers, key=None, answer="明确回答", **extra):
    return await client.post(
        f"/api/business/input-requests/{request_id}/answers",
        json={"answer": answer, "declared": declared, **extra},
        headers={**headers, "Idempotency-Key": key or uuid.uuid4().hex},
    )


async def test_answer_may_carry_contract_fields_that_were_not_requested(tmp_path, client) -> None:
    """AC-30：弹窗三项一次收集并保存，即使后两项不在本次请求字段里。"""
    headers, user_id, research_id = await _research(client, "pg-scope-carried")
    await _bind_account_and_plan(user_id, research_id)
    request_id, row = await _worker_intent_request(user_id, research_id, tmp_path, "carried")
    # 账户/计划都齐备时，用途裁决只缺本标的规划资金。
    assert sorted(f["name"] for f in row.fields_json) == ["plan.allocated_capital"]

    answer = await _answer(
        client,
        request_id,
        {
            "plan": {
                "allocated_capital": {"value": "20000"},
                "risk_budget_value": {"value": "10"},
                "risk_budget_unit": {"value": "percent"},
                "target_profit_value": {"value": "10"},
                "target_profit_unit": {"value": "percent"},
            }
        },
        headers=headers,
    )
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert body["status"] == "answered"
    assert body["follow_up_run_id"]

    # 未被请求的"可后补"项确实写进了计划版本，而不是只停在回答记录里。
    plan_id = uuid.UUID(row.continuation_json["investment_input"]["plan"]["id"])
    async with biz.business_transaction() as session:
        revision = (
            await session.execute(
                select(store.InvestmentPlanRevision)
                .where(store.InvestmentPlanRevision.plan_id == plan_id)
                .order_by(store.InvestmentPlanRevision.revision.desc())
                .limit(1)
            )
        ).scalar_one()
    assert Decimal(revision.risk_budget_value) == Decimal("10")
    assert revision.risk_budget_unit == "percent"
    assert Decimal(revision.target_profit_value) == Decimal("10")


async def test_contract_external_field_is_still_rejected(tmp_path, client) -> None:
    """负例：放宽的是"未被请求"，不是"契约外"——plan 子结构里的废弃价格字段仍拒。"""
    headers, user_id, research_id = await _research(client, "pg-scope-negative")
    await _bind_account_and_plan(user_id, research_id)
    request_id, _ = await _worker_intent_request(user_id, research_id, tmp_path, "negative")

    rejected = await _answer(client, request_id, {"plan": {"plan_price": "25"}}, headers=headers)
    assert rejected.status_code == 400, rejected.text
    error = rejected.json()["error"]
    assert error["code"] == "unknown_field_rejected"
    assert "plan_price" in error["fields"]


async def test_null_frozen_refs_are_adopted_from_the_research_link(tmp_path, client) -> None:
    """无快照续接 + 对象在请求之后建立：回答要能落库并生成唯一续接 Run。"""
    headers, user_id, research_id = await _research(client, "pg-scope-adopted")
    request_id, row = await _worker_intent_request(user_id, research_id, tmp_path, "adopted")
    assert sorted(f["name"] for f in row.fields_json) == DERIVED_FIELDS
    frozen = row.continuation_json["investment_input"]
    assert frozen["account"] is None and frozen["plan"] is None

    # 用户按引导补齐账户与主计划（弹窗内联建账户 / 会话计划建主计划）。
    await _bind_account_and_plan(user_id, research_id)

    answer = await _answer(
        client,
        request_id,
        {
            "account": dict(ACCOUNT),
            "plan": {
                "symbol": PLAN["symbol"],
                "market": PLAN["market"],
                "direction": PLAN["direction"],
                "allocated_capital": PLAN["allocated_capital"],
            },
        },
        headers=headers,
    )
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert body["status"] == "answered"
    assert body["follow_up_run_id"]

    async with biz.business_transaction() as session:
        follow_up = await session.get(store.Run, uuid.UUID(body["follow_up_run_id"]))
        snapshot = (
            await session.execute(
                select(store.RunInvestmentSnapshot).where(
                    store.RunInvestmentSnapshot.run_id == follow_up.id
                )
            )
        ).scalar_one_or_none()
    assert follow_up is not None and follow_up.status == "queued"
    assert snapshot is not None and not dict(snapshot.missing_json or {})


async def test_existing_objects_record_versions_in_the_continuation(tmp_path, client) -> None:
    """无快照续接 + 当时已有账户：续接记下版本，回答才能通过版本要求。"""
    headers, user_id, research_id = await _research(client, "pg-scope-versions")
    await _bind_account_and_plan(
        user_id,
        research_id,
        declared={"account": {"total_capital": "150000"}, "plan": PLAN},
    )
    request_id, row = await _worker_intent_request(user_id, research_id, tmp_path, "versions")

    known = dict(row.known_versions_json)
    assert known == {"account": 1, "plan": 1}
    frozen = row.continuation_json["investment_input"]
    assert frozen["account"]["expected_revision"] == 1
    assert frozen["plan"]["expected_revision"] == 1

    answer = await _answer(
        client,
        request_id,
        {
            "account": {
                "available_capital": "150000",
                "capital_basis": "total",
                "currency": "CNY",
                "as_of": "2026-10-09T00:00:00Z",
            },
            "plan": {
                "allocated_capital": "20000",
                "direction": "buy",
                "market": "CN",
                "symbol": "600519.SH",
            },
        },
        headers=headers,
        expected_versions=known,
    )
    assert answer.status_code == 200, answer.text
    assert answer.json()["status"] == "answered"
