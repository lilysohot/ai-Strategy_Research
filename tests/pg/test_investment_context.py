"""DATA-08: authenticated immutable InvestmentContext resolution on PostgreSQL."""

from __future__ import annotations

import uuid
from decimal import Decimal

import httpx
import pytest
from httpx import ASGITransport
from sqlalchemy import text

from server import business_service as biz
from server.app import app
from server.investment_context import InvestmentContextResolver
from server.security import create_access_token

pytestmark = pytest.mark.pg


async def _user(name: str) -> tuple[str, uuid.UUID, uuid.UUID]:
    user_id = uuid.uuid4()
    research_id = uuid.uuid4()
    async with biz.business_transaction() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, username, password_hash, status) "
                "VALUES (:id, :name, 'x', 'active')"
            ),
            {"id": user_id, "name": name},
        )
        await session.execute(
            text("INSERT INTO sessions (id, user_id, title) VALUES (:id, :uid, 'research')"),
            {"id": research_id, "uid": user_id},
        )
    return f"Bearer {create_access_token(user_id)}", user_id, research_id


async def _business_run(
    client: httpx.AsyncClient, token: str, research_id: uuid.UUID, suffix: str
) -> tuple[str, uuid.UUID]:
    account = await client.post(
        "/api/business/accounts",
        json={
            "name": "account",
            "base_currency": "CNY",
            "declared": {
                "total_capital": "100000",
                "available_capital": "60000",
                "capital_basis": "total",
                "currency": "CNY",
                "as_of": "2026-10-03T00:00:00Z",
            },
        },
        headers={"Authorization": token, "Idempotency-Key": f"account-{suffix}"},
    )
    assert account.status_code == 201, account.text
    plan = await client.post(
        f"/api/business/sessions/{research_id}/plans",
        json={
            "name": "plan",
            "declared": {
                "symbol": "600519.SH",
                "market": "CN",
                "direction": "buy",
                "plan_price_low": "19",
                "plan_price_high": "20",
                "target_price": "24",
                "risk_budget_value": "1",
                "risk_budget_unit": "percent",
                "position_limit_value": "20",
                "position_limit_unit": "percent",
                "currency": "CNY",
            },
        },
        headers={"Authorization": token, "Idempotency-Key": f"plan-{suffix}"},
    )
    assert plan.status_code == 201, plan.text
    submitted = await client.post(
        "/api/runs",
        json={
            "message": "analyse",
            "session_id": str(research_id),
            "investment_input": {
                "use_case": "plan_analysis",
                "account": {"id": account.json()["account_id"]},
                "plan": {"id": plan.json()["plan_id"]},
                "idempotency_key": f"run-{suffix}",
            },
        },
        headers={"Authorization": token},
    )
    assert submitted.status_code == 202, submitted.text
    return submitted.json()["run_id"], uuid.UUID(account.json()["account_id"])


async def test_resolver_is_owner_bound_frozen_minimal_and_cache_rebuildable(pg_clean) -> None:
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://context.test"
    ) as client:
        token, user_id, research_id = await _user("context-owner")
        _, other_id, _ = await _user("context-other")
        run_id, account_id = await _business_run(client, token, research_id, uuid.uuid4().hex)

        resolver = InvestmentContextResolver()
        first = await resolver.resolve(run_id=uuid.UUID(run_id), user_id=user_id)
        assert first is not None and first.cache_hit is False
        assert Decimal(first.data["values"]["account.total_capital"]["value"]) == Decimal(
            "100000"
        )
        assert "total_capital" not in first.data["values"], "flat duplicate leaked"
        assert await resolver.resolve(run_id=uuid.UUID(run_id), user_id=other_id) is None

        # Current account changes cannot alter this Run's immutable context.
        async with biz.business_transaction() as session:
            await biz.update_account(
                session,
                user_id=user_id,
                account_id=account_id,
                expected_revision=1,
                declared={"total_capital": "80000"},
                idempotency_key="context-account-update",
            )
        cached = await resolver.resolve(run_id=uuid.UUID(run_id), user_id=user_id)
        assert cached is not None and cached.cache_hit is True
        assert cached.data == first.data
        resolver.clear()
        rebuilt = await resolver.resolve(run_id=uuid.UUID(run_id), user_id=user_id)
        assert rebuilt is not None and rebuilt.cache_hit is False
        assert rebuilt.data == first.data
        assert resolver.calls == 4
        assert resolver.cache_reads == 1
        assert resolver.cache_writes == 2
