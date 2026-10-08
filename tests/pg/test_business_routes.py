"""DATA-03 收尾验收：业务 HTTP 路由在真实 PostgreSQL 上的契约行为。

这里验证的是“页面/聊天真正会走的那条链路”：身份绑定、幂等键、错误信封、版本冲突与
归属隔离都必须在 HTTP 层也成立，而不是只在服务层成立。

* 写操作缺幂等键 → 400 validation_error
* 同键重放 → replayed=true 且不产生新版本
* 假设值 → 400 assumption_rejected（含字段定位）
* 版本冲突 → 409 revision_conflict（带当前版本）
* 他人对象 → 404 not_found（与不存在同结果）
"""

from __future__ import annotations

import uuid

import httpx
import pytest
from httpx import ASGITransport
from sqlalchemy import text

from server import business_service as biz
from server.app import app
from server.security import create_access_token

pytestmark = pytest.mark.pg

CAPITAL = {
    "total_capital": "100000",
    "available_capital": "60000",
    "capital_basis": "total",
    "as_of": "2026-10-02T00:00:00Z",
}
PLAN = {
    "symbol": "600519.SH",
    "market": "CN",
    "direction": "buy",
    "allocated_capital": "10000",
    "target_price": "24.00",
    "currency": "CNY",
}


@pytest.fixture
async def client(pg_clean):
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://business.test"
    ) as http:
        yield http


async def _make_user(name: str) -> tuple[str, str, uuid.UUID]:
    """返回 (Authorization 头值, 用户名, user_id)。"""
    user_id = uuid.uuid4()
    async with biz.business_transaction() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, username, password_hash, status) "
                "VALUES (:id, :name, 'x', 'active')"
            ),
            {"id": user_id, "name": name},
        )
    return f"Bearer {create_access_token(user_id)}", name, user_id


async def _create_account(client, token: str, declared=None, key: str = "k", **extra):
    return await client.post(
        "/api/business/accounts",
        json={
            "name": "主账户",
            "base_currency": "CNY",
            "declared": declared if declared is not None else dict(CAPITAL),
            **extra,
        },
        headers={"Authorization": token, "Idempotency-Key": key},
    )


async def test_create_account_returns_receipt(client) -> None:
    token, _, _ = await _make_user("pg-route-create")
    response = await _create_account(client, token, key="route-create-1")
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["revision"] == 1
    assert body["operation_id"]
    assert body["replayed"] is False


async def test_write_without_idempotency_key_is_refused(client) -> None:
    token, _, _ = await _make_user("pg-route-nokey")
    response = await client.post(
        "/api/business/accounts",
        json={"name": "主账户", "base_currency": "CNY", "declared": dict(CAPITAL)},
        headers={"Authorization": token},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"


async def test_replay_same_key_writes_once(client) -> None:
    token, _, _ = await _make_user("pg-route-replay")
    first = await _create_account(client, token, key="route-replay-1")
    second = await _create_account(client, token, key="route-replay-1")
    assert second.status_code == 201
    assert second.json()["replayed"] is True
    assert second.json()["account_id"] == first.json()["account_id"]


async def test_assumed_value_is_refused_with_field_location(client) -> None:
    token, _, _ = await _make_user("pg-route-assume")
    response = await _create_account(
        client,
        token,
        declared={"total_capital": {"value": "80000", "status": "assumed"}},
        key="route-assume-1",
    )
    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "assumption_rejected"
    assert "total_capital" in error["fields"]


async def test_revision_conflict_returns_current_version(client) -> None:
    token, _, _ = await _make_user("pg-route-conflict")
    created = (await _create_account(client, token, key="route-conflict-1")).json()
    account_id = created["account_id"]

    first = await client.patch(
        f"/api/business/accounts/{account_id}",
        json={"expected_revision": 1, "declared": {"total_capital": "80000"}},
        headers={"Authorization": token, "Idempotency-Key": "route-conflict-2"},
    )
    assert first.status_code == 200, first.text

    stale = await client.patch(
        f"/api/business/accounts/{account_id}",
        json={"expected_revision": 1, "declared": {"total_capital": "70000"}},
        headers={"Authorization": token, "Idempotency-Key": "route-conflict-3"},
    )
    assert stale.status_code == 409
    error = stale.json()["error"]
    assert error["code"] == "revision_conflict"
    assert error["current"]["revision"] == 2


async def test_other_users_account_is_not_found(client) -> None:
    owner_token, _, _ = await _make_user("pg-route-owner")
    other_token, _, _ = await _make_user("pg-route-other")
    account_id = (await _create_account(client, owner_token, key="route-iso-1")).json()[
        "account_id"
    ]

    response = await client.get(
        f"/api/business/accounts/{account_id}", headers={"Authorization": other_token}
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_plan_belongs_to_one_research(client) -> None:
    token, _, user_id = await _make_user("pg-route-plan")
    async with biz.business_transaction() as session:
        research_a, research_b = uuid.uuid4(), uuid.uuid4()
        await session.execute(
            text("INSERT INTO sessions (id, user_id, title) VALUES (:id, :uid, 'A')"),
            {"id": research_a, "uid": user_id},
        )
        await session.execute(
            text("INSERT INTO sessions (id, user_id, title) VALUES (:id, :uid, 'B')"),
            {"id": research_b, "uid": user_id},
        )

    created = await client.post(
        f"/api/business/sessions/{research_a}/plans",
        json={"name": "计划A", "declared": dict(PLAN)},
        headers={"Authorization": token, "Idempotency-Key": "route-plan-1"},
    )
    assert created.status_code == 201, created.text
    plan_id = created.json()["plan_id"]

    listed = await client.get(
        f"/api/business/sessions/{research_a}/plans", headers={"Authorization": token}
    )
    assert [p["id"] for p in listed.json()["plans"]] == [plan_id]

    cross = await client.put(
        f"/api/business/sessions/{research_b}/link",
        json={"primary_plan_id": plan_id},
        headers={"Authorization": token, "Idempotency-Key": "route-link-1"},
    )
    assert cross.status_code == 404, "跨研究计划被当成本研究主计划"


async def test_operation_can_be_recovered_after_lost_response(client) -> None:
    token, _, _ = await _make_user("pg-route-op")
    created = (await _create_account(client, token, key="route-op-1")).json()

    found = await client.get(
        f"/api/business/operations/{created['operation_id']}",
        headers={"Authorization": token},
    )
    assert found.status_code == 200
    assert found.json()["account_id"] == created["account_id"]

    unknown = await client.get(
        f"/api/business/operations/{uuid.uuid4()}", headers={"Authorization": token}
    )
    assert unknown.status_code == 404, "未知键必须明确报告，不能诱导客户端重发"


async def test_trade_registration_and_correction(client) -> None:
    token, _, _ = await _make_user("pg-route-trade")
    account_id = (await _create_account(client, token, key="route-trade-1")).json()["account_id"]

    trade = await client.post(
        f"/api/business/accounts/{account_id}/trades",
        json={
            "declared": {
                "symbol": "600519.SH",
                "side": "buy",
                "quantity": "100",
                "price": "20",
                "currency": "CNY",
                "traded_at": "2026-10-02T01:00:00Z",
            }
        },
        headers={"Authorization": token, "Idempotency-Key": "route-trade-2"},
    )
    assert trade.status_code == 201, trade.text
    trade_id = trade.json()["trade_id"]

    corrected = await client.post(
        f"/api/business/trades/{trade_id}/correct",
        json={"declared": {"price": "20.5"}},
        headers={"Authorization": token, "Idempotency-Key": "route-trade-3"},
    )
    assert corrected.status_code == 201, corrected.text

    listed = await client.get(
        f"/api/business/trades?account_id={account_id}", headers={"Authorization": token}
    )
    rows = listed.json()["trades"]
    assert sorted(r["status"] for r in rows) == ["active", "corrected"]
    assert sorted(r["price"] for r in rows) == ["20", "20.5"]
