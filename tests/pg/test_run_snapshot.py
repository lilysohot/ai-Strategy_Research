"""DATA-05 验收：Run 业务输入快照在真实 PostgreSQL 上的冻结、读取与重算。

覆盖 AC-05—07、09、26、27 的服务端部分：

* 提交时冻结：提交后修改账户/计划，快照值不变（AC-06/07）
* 只存 ID 不算快照：快照保存解析后的完整有效值、对象版本与来源
* 旧的非业务 Run 明确报 ``404 snapshot_absent``，不用当前资料回填
* 跨研究计划、跨用户账户、混用账户资料一律拒绝（AC-01/09/26）
* 假设覆盖、预期版本不符、用途必需字段缺失都不放行（AC-02/27）
* JSON 与 multipart 同一契约（AC-27）
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import httpx
import pytest
from httpx import ASGITransport
from sqlalchemy import text

from server import business_service as biz
from server import investment_snapshot, store
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
        transport=ASGITransport(app=app), base_url="http://snapshot.test"
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


async def _new_research(user_id: uuid.UUID, title: str = "研究") -> uuid.UUID:
    research_id = uuid.uuid4()
    async with biz.business_transaction() as session:
        await session.execute(
            text("INSERT INTO sessions (id, user_id, title) VALUES (:id, :uid, :title)"),
            {"id": research_id, "uid": user_id, "title": title},
        )
    return research_id


async def _create_account(client, token, declared=None, key="acc-1"):
    response = await client.post(
        "/api/business/accounts",
        json={
            "name": "主账户",
            "base_currency": "CNY",
            "declared": declared if declared is not None else dict(CAPITAL),
        },
        headers={"Authorization": token, "Idempotency-Key": key},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _create_plan(client, token, research_id, key="plan-1", declared=None):
    response = await client.post(
        f"/api/business/sessions/{research_id}/plans",
        json={"name": "计划A", "declared": declared if declared is not None else dict(PLAN)},
        headers={"Authorization": token, "Idempotency-Key": key},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _submit(client, token, research_id, investment_input, message="按计划分析"):
    return await client.post(
        "/api/runs",
        json={
            "message": message,
            "session_id": str(research_id),
            "investment_input": investment_input,
        },
        headers={"Authorization": token},
    )


def _input(account_id, plan_id, **extra):
    payload = {
        "use_case": "plan_analysis",
        "account": {"id": str(account_id)},
        "plan": {"id": str(plan_id)},
        "idempotency_key": f"analyze:{uuid.uuid4()}",
    }
    payload.update(extra)
    return payload


async def test_submit_freezes_snapshot_and_it_does_not_move(client) -> None:
    """AC-06/07：提交后改资料，快照保持提交那一刻的值。"""
    token, user_id = await _new_user("pg-snap-freeze")
    research_id = await _new_research(user_id)
    account = await _create_account(client, token)
    plan = await _create_plan(client, token, research_id)

    submitted = await _submit(
        client, token, research_id, _input(account["account_id"], plan["plan_id"])
    )
    assert submitted.status_code == 202, submitted.text
    body = submitted.json()
    assert body["snapshot_id"], "提交没有冻结快照"

    # 提交之后把资金从 100000 改成 80000，并改计划的规划资金。
    async with biz.business_transaction() as session:
        await biz.update_account(
            session,
            user_id=user_id,
            account_id=uuid.UUID(account["account_id"]),
            expected_revision=1,
            declared={"total_capital": "80000"},
            idempotency_key="snap-edit-1",
        )
    async with biz.business_transaction() as session:
        await biz.update_plan(
            session,
            user_id=user_id,
            plan_id=uuid.UUID(plan["plan_id"]),
            expected_revision=1,
            declared={"allocated_capital": "20000"},
            idempotency_key="snap-edit-2",
        )

    snapshot = await client.get(
        f"/api/runs/{body['run_id']}/investment-snapshot", headers={"Authorization": token}
    )
    assert snapshot.status_code == 200
    values = snapshot.json()["values"]
    assert Decimal(values["total_capital"]["value"]) == Decimal("100000"), values
    assert Decimal(values["allocated_capital"]["value"]) == Decimal("10000"), values
    assert snapshot.json()["account"]["revision"] == 1
    assert snapshot.json()["plan"]["revision"] == 1


async def test_snapshot_carries_resolved_values_and_sources(client) -> None:
    """只存 ID 不算快照：必须带解析后的有效值、对象版本与来源。"""
    token, user_id = await _new_user("pg-snap-content")
    research_id = await _new_research(user_id)
    account = await _create_account(client, token)
    plan = await _create_plan(client, token, research_id)

    submitted = await _submit(
        client, token, research_id, _input(account["account_id"], plan["plan_id"])
    )
    snapshot = (
        await client.get(
            f"/api/runs/{submitted.json()['run_id']}/investment-snapshot",
            headers={"Authorization": token},
        )
    ).json()

    assert snapshot["schema_version"] == investment_snapshot.SNAPSHOT_SCHEMA_VERSION
    assert snapshot["use_case"] == "plan_analysis"
    assert snapshot["source"] == "manual"
    assert snapshot["frozen_at"]
    for field in (
        "total_capital",
        "currency",
        "capital_basis",
        "symbol",
        "allocated_capital",
        "target_price",
    ):
        assert field in snapshot["values"], f"快照缺少字段 {field}"
    assert snapshot["values"]["total_capital"]["source"]["kind"] == "account_revision"
    assert snapshot["values"]["total_capital"]["status"] == "user_provided"


async def test_legacy_run_has_no_snapshot_and_is_not_backfilled(client) -> None:
    """旧的非业务 Run 必须明确报缺，不能用当前资料伪造。"""
    token, user_id = await _new_user("pg-snap-legacy")
    research_id = await _new_research(user_id)
    response = await client.post(
        "/api/runs",
        json={"message": "普通问题", "session_id": str(research_id)},
        headers={"Authorization": token},
    )
    assert response.status_code == 202, response.text
    run_id = response.json()["run_id"]

    missing = await client.get(
        f"/api/runs/{run_id}/investment-snapshot", headers={"Authorization": token}
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "snapshot_absent"


async def test_plan_from_another_research_is_refused(client) -> None:
    """AC-01：不能借别的研究的计划来跑本次分析。"""
    token, user_id = await _new_user("pg-snap-cross")
    research_a = await _new_research(user_id, "研究A")
    research_b = await _new_research(user_id, "研究B")
    account = await _create_account(client, token)
    plan_a = await _create_plan(client, token, research_a)

    response = await _submit(
        client, token, research_b, _input(account["account_id"], plan_a["plan_id"])
    )
    assert response.status_code == 404, response.text


async def test_other_users_objects_are_invisible(client) -> None:
    """AC-09：他人账户/计划既不能采用也不能借快照读出。"""
    owner_token, owner_id = await _new_user("pg-snap-owner")
    other_token, other_id = await _new_user("pg-snap-other")
    research_owner = await _new_research(owner_id, "他人研究")
    research_other = await _new_research(other_id, "我的研究")
    account = await _create_account(client, owner_token)
    plan = await _create_plan(client, owner_token, research_owner)

    response = await _submit(
        client, other_token, research_other, _input(account["account_id"], plan["plan_id"])
    )
    assert response.status_code == 404, response.text


async def test_assumption_override_is_refused(client) -> None:
    """AC-02/27：不支持“仅本次按假设值分析”。"""
    token, user_id = await _new_user("pg-snap-assume")
    research_id = await _new_research(user_id)
    account = await _create_account(client, token)
    plan = await _create_plan(client, token, research_id)

    response = await _submit(
        client,
        token,
        research_id,
        _input(account["account_id"], plan["plan_id"], assume={"total_capital": "500000"}),
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "assumption_rejected"


async def test_stale_expected_revision_conflicts(client) -> None:
    """AC-04/07：基于旧版本提交时明确冲突，不静默采用新值。"""
    token, user_id = await _new_user("pg-snap-conflict")
    research_id = await _new_research(user_id)
    account = await _create_account(client, token)
    plan = await _create_plan(client, token, research_id)
    async with biz.business_transaction() as session:
        await biz.update_account(
            session,
            user_id=user_id,
            account_id=uuid.UUID(account["account_id"]),
            expected_revision=1,
            declared={"total_capital": "90000"},
            idempotency_key="snap-conflict-1",
        )

    response = await _submit(
        client,
        token,
        research_id,
        _input(account["account_id"], plan["plan_id"])
        | {"account": {"id": account["account_id"], "expected_revision": 1}},
    )
    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "revision_conflict"
    assert error["current"]["revision"] == 2


async def test_purpose_requirement_blocks_incomplete_capital(client) -> None:
    """AC-02/24：资金缺失时不做依赖资金的分析。"""
    token, user_id = await _new_user("pg-snap-purpose")
    research_id = await _new_research(user_id)
    # 只填币种：资金口径与金额都缺。
    account = await _create_account(client, token, declared={"currency": "CNY"}, key="acc-partial")
    plan = await _create_plan(client, token, research_id)

    response = await _submit(
        client, token, research_id, _input(account["account_id"], plan["plan_id"])
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "purpose_requirement_unmet"


async def test_multipart_submission_uses_the_same_contract(client) -> None:
    """AC-27：multipart 里的 investment_input 必须被解析，不能被忽略。"""
    token, user_id = await _new_user("pg-snap-multipart")
    research_id = await _new_research(user_id)
    account = await _create_account(client, token)
    plan = await _create_plan(client, token, research_id)

    import json

    response = await client.post(
        "/api/runs",
        data={
            "message": "按计划分析",
            "session_id": str(research_id),
            "investment_input": json.dumps(_input(account["account_id"], plan["plan_id"])),
        },
        files={"file": ("note.txt", b"position note", "text/plain")},
        headers={"Authorization": token},
    )
    assert response.status_code == 202, response.text
    assert response.json()["snapshot_id"], "multipart 提交没有冻结快照"


async def test_rerun_uses_a_new_snapshot_and_keeps_the_old_one(client) -> None:
    """重算：新 Run + 新快照，旧快照原样保留并保留来源关系。"""
    token, user_id = await _new_user("pg-snap-rerun")
    research_id = await _new_research(user_id)
    account = await _create_account(client, token)
    plan = await _create_plan(client, token, research_id)

    submitted = await _submit(
        client, token, research_id, _input(account["account_id"], plan["plan_id"])
    )
    first_run_id = submitted.json()["run_id"]

    async with biz.business_transaction() as session:
        await biz.update_account(
            session,
            user_id=user_id,
            account_id=uuid.UUID(account["account_id"]),
            expected_revision=1,
            declared={"total_capital": "80000"},
            idempotency_key="snap-rerun-edit",
        )

    rerun = await client.post(
        f"/api/runs/{first_run_id}/rerun",
        json={},
        headers={"Authorization": token, "Idempotency-Key": "rerun-1"},
    )
    assert rerun.status_code == 202, rerun.text
    second = rerun.json()
    assert second["rerun_of_run_id"] == first_run_id
    assert second["run_id"] != first_run_id

    old_snapshot = (
        await client.get(
            f"/api/runs/{first_run_id}/investment-snapshot", headers={"Authorization": token}
        )
    ).json()
    new_snapshot = (
        await client.get(
            f"/api/runs/{second['run_id']}/investment-snapshot", headers={"Authorization": token}
        )
    ).json()
    assert Decimal(old_snapshot["values"]["total_capital"]["value"]) == Decimal("100000")
    assert Decimal(new_snapshot["values"]["total_capital"]["value"]) == Decimal("80000")
    assert new_snapshot["rerun_of_run_id"] == first_run_id

    async with biz.business_transaction() as session:
        rows = (
            await session.execute(
                text("SELECT run_id, rerun_of_run_id FROM run_investment_snapshots")
            )
        ).all()
    assert len(rows) == 2, "重算应当产生第二份快照而不是改写旧快照"


async def test_same_idempotency_key_does_not_create_a_second_run(client) -> None:
    """AC-05：同键重试回到同一个 Run，不产生第二个分析。"""
    token, user_id = await _new_user("pg-snap-idem")
    research_id = await _new_research(user_id)
    account = await _create_account(client, token)
    plan = await _create_plan(client, token, research_id)

    payload = _input(account["account_id"], plan["plan_id"])
    payload["idempotency_key"] = "analyze:fixed-key"
    first = await _submit(client, token, research_id, payload)
    second = await _submit(client, token, research_id, payload)
    assert first.status_code == 202 and second.status_code == 202
    assert second.json()["run_id"] == first.json()["run_id"]
    assert second.json()["replayed"] is True

    async with biz.business_transaction() as session:
        count = (
            await session.execute(
                text("SELECT count(*) FROM runs WHERE session_id = :sid"),
                {"sid": research_id},
            )
        ).scalar_one()
    assert count == 1, "同键重放产生了第二个 Run"


async def test_snapshot_is_not_readable_by_another_user(client) -> None:
    token, user_id = await _new_user("pg-snap-read-owner")
    other_token, _ = await _new_user("pg-snap-read-other")
    research_id = await _new_research(user_id)
    account = await _create_account(client, token)
    plan = await _create_plan(client, token, research_id)
    submitted = await _submit(
        client, token, research_id, _input(account["account_id"], plan["plan_id"])
    )

    response = await client.get(
        f"/api/runs/{submitted.json()['run_id']}/investment-snapshot",
        headers={"Authorization": other_token},
    )
    assert response.status_code == 404


async def test_snapshot_row_is_immutable_by_convention(client) -> None:
    """快照行只 INSERT：同一 Run 重复冻结在库层失败。"""
    token, user_id = await _new_user("pg-snap-immutable")
    research_id = await _new_research(user_id)
    account = await _create_account(client, token)
    plan = await _create_plan(client, token, research_id)
    submitted = await _submit(
        client, token, research_id, _input(account["account_id"], plan["plan_id"])
    )
    run_id = uuid.UUID(submitted.json()["run_id"])

    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        async with biz.business_transaction() as session:
            session.add(
                store.RunInvestmentSnapshot(
                    run_id=run_id,
                    user_id=user_id,
                    research_id=research_id,
                    schema_version="x",
                    use_case="general_reading",
                    source="manual",
                    resolved_json={},
                    frozen_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
                )
            )
            await session.flush()
