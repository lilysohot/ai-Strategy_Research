"""Post-run structured input continuation without an Agent tool call."""

from __future__ import annotations

import uuid
from decimal import Decimal

import httpx
from sqlalchemy import select

from server import business_service as biz
from server import store
from server.app import app
from server.config import run_dir_for
from server.security import create_access_token


async def test_finished_run_can_collect_missing_data_and_start_follow_up() -> None:
    await store.init_db()
    user = await store.create_user(username="post-run-input", password_hash="x")
    research_id = uuid.uuid4()
    await store.ensure_session(session_id=research_id, user_id=user.id, title="工业富联研究")
    headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://post-run.test"
    ) as client:
        account = await client.post(
            "/api/business/accounts",
            json={
                "name": "主账户",
                "base_currency": "CNY",
                "declared": {
                    "total_capital": "200000",
                    "available_capital": "120000",
                    "capital_basis": "tradable_assets",
                    "as_of": "2026-10-12T00:00:00Z",
                },
            },
            headers={**headers, "Idempotency-Key": "post-run-account"},
        )
        assert account.status_code == 201, account.text
        plan = await client.post(
            f"/api/business/sessions/{research_id}/plans",
            json={
                "name": "工业富联计划",
                "declared": {
                    "symbol": "601138.SH",
                    "market": "CN",
                    "direction": "buy",
                    "currency": "CNY",
                },
            },
            headers={**headers, "Idempotency-Key": "post-run-plan"},
        )
        assert plan.status_code == 201, plan.text
        linked = await client.put(
            f"/api/business/sessions/{research_id}/link",
            json={
                "account_id": account.json()["account_id"],
                "primary_plan_id": plan.json()["plan_id"],
            },
            headers={**headers, "Idempotency-Key": "post-run-link"},
        )
        assert linked.status_code == 200, linked.text

        run_id = uuid.uuid4()
        async with biz.business_transaction() as session:
            row = store.add_run(
                session,
                run_id=run_id,
                session_id=research_id,
                user_id=user.id,
                prompt="结合我的情况分析是否适合买入工业富联",
                pipeline_id="stateful-react-agent",
                run_dir=str(run_dir_for(run_id.hex)),
            )
            row.status = "completed"
            row.final_answer = "先给出一般性分析。"

        prepared = await client.post(
            f"/api/business/runs/{run_id}/input-request",
            headers={**headers, "Idempotency-Key": f"post-run-input:{run_id}:plan_analysis"},
        )
        assert prepared.status_code == 201, prepared.text
        prepared_body = prepared.json()
        assert prepared_body["required"] is True
        request_id = prepared_body["request_id"]

        # Repeated clicks reuse one durable request instead of opening parallel
        # continuations for the same answer.
        repeated = await client.post(
            f"/api/business/runs/{run_id}/input-request",
            headers={**headers, "Idempotency-Key": f"post-run-input:{run_id}:plan_analysis"},
        )
        assert repeated.status_code == 201
        assert repeated.json()["request_id"] == request_id
        assert repeated.json()["reused"] is True

        # A retry can finish as a different Run while asking the same question.
        # Research-level semantic de-duplication must reuse the open form too.
        retry_run_id = uuid.uuid4()
        async with biz.business_transaction() as session:
            retry = store.add_run(
                session,
                run_id=retry_run_id,
                session_id=research_id,
                user_id=user.id,
                prompt="结合我的情况分析是否适合买入工业富联",
                pipeline_id="stateful-react-agent",
                run_dir=str(run_dir_for(retry_run_id.hex)),
            )
            retry.status = "completed"
            retry.final_answer = "本轮重试仍需补数。"
        cross_run = await client.post(
            f"/api/business/runs/{retry_run_id}/input-request",
            headers={
                **headers,
                "Idempotency-Key": f"post-run-input:{retry_run_id}:plan_analysis",
            },
        )
        assert cross_run.status_code == 201, cross_run.text
        assert cross_run.json()["request_id"] == request_id
        assert cross_run.json()["reused"] is True

        request = await client.get(f"/api/business/input-requests/{request_id}", headers=headers)
        assert request.status_code == 200, request.text
        request_body = request.json()
        assert request_body["remaining_fields"] == ["plan.allocated_capital"]

        answered = await client.post(
            f"/api/business/input-requests/{request_id}/answers",
            json={
                "answer": "本标的规划资金 30000 元",
                "declared": {"plan": {"allocated_capital": {"value": "30000"}}},
                "expected_versions": request_body["current_versions"],
            },
            headers={**headers, "Idempotency-Key": f"post-run-answer:{request_id}"},
        )
        assert answered.status_code == 200, answered.text
        answer_body = answered.json()
        assert answer_body["status"] == "answered"
        assert answer_body["follow_up_run_id"]

    async with biz.business_transaction() as session:
        follow_up = await session.get(store.Run, uuid.UUID(answer_body["follow_up_run_id"]))
        assert follow_up is not None
        assert follow_up.status == "queued"
        assert follow_up.prompt == "结合我的情况分析是否适合买入工业富联"
        snapshot = (
            await session.execute(
                select(store.RunInvestmentSnapshot).where(
                    store.RunInvestmentSnapshot.run_id == follow_up.id
                )
            )
        ).scalar_one_or_none()
        assert snapshot is not None
        assert snapshot.source == "input_answer"
        assert Decimal(snapshot.resolved_json["plan.allocated_capital"]["value"]) == Decimal(
            "30000"
        )
