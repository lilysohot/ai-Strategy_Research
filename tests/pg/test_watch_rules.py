"""DATA-09 验收：监控规则持久化、版本与生命周期在真实 PostgreSQL 上的契约行为。

覆盖：创建/编辑/暂停/恢复/取消的版本、幂等与归属校验；C 阶段只开放单次触发；
规则配置只随自身版本变化（计划改版不静默改阈值）；最近检查与有效行情时间记录；
重启后（新连接/新请求）规则与状态仍存在。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import select

from server import business_service as biz
from server import store, watch_rules
from server.app import app
from server.security import create_access_token

pytestmark = pytest.mark.pg

RULE = {
    "symbol": "600519.SH",
    "market": "CN",
    "currency": "CNY",
    "quote_basis": "last",
    "direction": "up",
    "threshold": "20.00",
    "trigger_mode": "single",
    "action": "auto_analyze",
    "task": "触发后按当前计划重算仓位",
    "budget": {"max_runs": 1},
    "on_create_already_met": "trigger_now",
    "disconnect_recovery": "trigger_once",
}


@pytest.fixture
async def case(pg_clean):
    uid, rid, rid2 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    async with biz.business_transaction() as session:
        session.add(store.User(id=uid, username=f"watch-{uid.hex}", password_hash="unused"))
        await session.flush()
        session.add(store.Session(id=rid, user_id=uid, title="watch research"))
        session.add(store.Session(id=rid2, user_id=uid, title="other research"))
        await session.flush()
        plan = await biz.create_plan(
            session,
            user_id=uid,
            research_id=rid,
            name="plan",
            declared={
                "symbol": "600519.SH",
                "market": "CN",
                "direction": "buy",
                "plan_price": "19.90",
                "target_price": "24.00",
                "currency": "CNY",
            },
            idempotency_key=uuid.uuid4().hex,
        )
        plan2 = await biz.create_plan(
            session,
            user_id=uid,
            research_id=rid2,
            name="plan2",
            declared={
                "symbol": "600519.SH",
                "market": "CN",
                "direction": "buy",
                "plan_price": "20.00",
                "target_price": "25.00",
                "currency": "CNY",
            },
            idempotency_key=uuid.uuid4().hex,
        )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://watch.test"
    ) as client:
        yield SimpleNamespace(
            uid=uid,
            rid=rid,
            rid2=rid2,
            pid=uuid.UUID(plan.result["plan_id"]),
            pid2=uuid.UUID(plan2.result["plan_id"]),
            client=client,
            headers={"Authorization": f"Bearer {create_access_token(uid)}"},
        )


def headers(case, key: str | None = None) -> dict[str, str]:
    return {**case.headers, "Idempotency-Key": key or uuid.uuid4().hex}


async def create_rule(case, research_id=None, spec=None, **extra):
    body = {
        "name": "茅台上穿 20",
        "spec": spec if spec is not None else dict(RULE),
        **extra,
    }
    return await case.client.post(
        f"/api/business/sessions/{research_id or case.rid}/watch-rules",
        json=body,
        headers=headers(case),
    )


async def test_create_rule_returns_receipt(case) -> None:
    response = await create_rule(case)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["replayed"] is False
    assert body["operation_id"]
    assert body["status"] == "active"
    assert body["version"] == 1
    rule_id = body["rule_id"]
    detail = await case.client.get(f"/api/business/watch-rules/{rule_id}", headers=case.headers)
    assert detail.status_code == 200, detail.text
    item = detail.json()
    assert item["symbol"] == "600519.SH"
    assert item["threshold"] == "20"
    assert item["direction"] == "up"
    assert item["trigger_mode"] == "single"
    assert item["action"] == "auto_analyze"
    assert item["budget"] == {"max_runs": 1}
    assert item["research_id"] == str(case.rid)
    assert item["plan_id"] is None


async def test_create_rule_binds_plan_of_same_research(case) -> None:
    response = await create_rule(case, plan_id=str(case.pid))
    assert response.status_code == 201, response.text
    rule_id = response.json()["rule_id"]
    detail = await case.client.get(f"/api/business/watch-rules/{rule_id}", headers=case.headers)
    assert detail.json()["plan_id"] == str(case.pid)


async def test_create_rule_rejects_plan_of_other_research(case) -> None:
    response = await create_rule(case, plan_id=str(case.pid2))
    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "not_found"


async def test_create_rule_requires_existing_research(case) -> None:
    response = await create_rule(case, research_id=str(uuid.uuid4()))
    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "not_found"


async def test_create_rule_rejects_repeat_mode_in_c_phase(case) -> None:
    spec = {**RULE, "trigger_mode": "repeat"}
    response = await create_rule(case, spec=spec)
    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "validation_error"
    assert "trigger_mode" in response.json()["error"]["fields"]


async def test_create_rule_rejects_d_phase_fields(case) -> None:
    spec = {**RULE, "cooldown_seconds": 300}
    response = await create_rule(case, spec=spec)
    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "unknown_field_rejected"


async def test_create_rule_rejects_plan_id_inside_spec(case) -> None:
    # 计划绑定是独立参数，混进 spec 属未知字段，不能静默忽略。
    spec = {**RULE, "plan_id": str(case.pid)}
    response = await create_rule(case, spec=spec)
    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "unknown_field_rejected"
    assert "plan_id" in response.json()["error"]["fields"]


async def test_create_rule_validates_threshold(case) -> None:
    bad = [("abc", "validation_error"), ("1e9", "validation_error"), (20, "validation_error")]
    for threshold, _ in bad:
        response = await create_rule(case, spec={**RULE, "threshold": threshold})
        assert response.status_code == 400, response.text
        assert response.json()["error"]["code"] == "validation_error"


async def test_create_rule_range_requires_low_high(case) -> None:
    # 区间方向：threshold 必须是 {low, high}，且 low < high。
    spec = {**RULE, "direction": "range", "threshold": {"low": "20", "high": "18"}}
    response = await create_rule(case, spec=spec)
    assert response.status_code == 400, response.text
    assert "threshold" in response.json()["error"]["fields"]

    spec = {**RULE, "direction": "range", "threshold": "20"}
    response = await create_rule(case, spec=spec)
    assert response.status_code == 400, response.text

    spec = {**RULE, "direction": "range", "threshold": {"low": "18", "high": "20"}}
    response = await create_rule(case, spec=spec)
    assert response.status_code == 201, response.text
    detail = await case.client.get(
        f"/api/business/watch-rules/{response.json()['rule_id']}", headers=case.headers
    )
    assert detail.json()["threshold"] == {"low": "18", "high": "20"}


async def test_create_rule_requires_required_fields(case) -> None:
    for field in ("symbol", "market", "currency", "direction", "action"):
        spec = {k: v for k, v in RULE.items() if k != field}
        response = await create_rule(case, spec=spec)
        assert response.status_code == 400, response.text
        assert response.json()["error"]["code"] == "validation_error"
        assert field in response.json()["error"]["fields"]


async def test_create_rule_idempotent_replay(case) -> None:
    key = uuid.uuid4().hex
    first = await case.client.post(
        f"/api/business/sessions/{case.rid}/watch-rules",
        json={"name": "规则", "spec": dict(RULE)},
        headers=headers(case, key),
    )
    assert first.status_code == 201, first.text
    second = await case.client.post(
        f"/api/business/sessions/{case.rid}/watch-rules",
        json={"name": "规则", "spec": dict(RULE)},
        headers=headers(case, key),
    )
    assert second.status_code == 201, second.text
    body = second.json()
    assert body["replayed"] is True
    assert body["rule_id"] == first.json()["rule_id"]
    listing = await case.client.get("/api/business/watch-rules", headers=case.headers)
    assert listing.json()["total"] == 1


async def test_update_rule_creates_new_version_and_keeps_old(case) -> None:
    rule_id = (await create_rule(case)).json()["rule_id"]
    patch = {"threshold": "22.00"}
    response = await case.client.patch(
        f"/api/business/watch-rules/{rule_id}",
        json={"expected_version": 1, **patch},
        headers=headers(case),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["version"] == 2
    assert body["status"] == "active"

    versions = await case.client.get(
        f"/api/business/watch-rules/{rule_id}/versions", headers=case.headers
    )
    items = versions.json()["versions"]
    assert [item["version"] for item in items] == [2, 1]
    assert items[0]["config"]["threshold"] == "22"
    assert items[1]["config"]["threshold"] == "20"


async def test_update_rule_revision_conflict(case) -> None:
    rule_id = (await create_rule(case)).json()["rule_id"]
    response = await case.client.patch(
        f"/api/business/watch-rules/{rule_id}",
        json={"expected_version": 5, "threshold": "22.00"},
        headers=headers(case),
    )
    assert response.status_code == 409, response.text
    error = response.json()["error"]
    assert error["code"] == "revision_conflict"
    assert error["current"]["version"] == 1


async def test_update_rule_does_not_touch_untouched_fields(case) -> None:
    rule_id = (await create_rule(case)).json()["rule_id"]
    # 只改任务指令：阈值与方向必须保持 v1 冻结值。
    response = await case.client.patch(
        f"/api/business/watch-rules/{rule_id}",
        json={"expected_version": 1, "task": "改成提醒"},
        headers=headers(case),
    )
    assert response.status_code == 200, response.text
    detail = await case.client.get(f"/api/business/watch-rules/{rule_id}", headers=case.headers)
    item = detail.json()
    assert item["version"] == 2
    assert item["threshold"] == "20"
    assert item["direction"] == "up"
    assert item["action"] == "auto_analyze"


async def test_update_rule_missing_expected_version(case) -> None:
    rule_id = (await create_rule(case)).json()["rule_id"]
    response = await case.client.patch(
        f"/api/business/watch-rules/{rule_id}", json={"threshold": "22.00"}, headers=headers(case)
    )
    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "validation_error"
    assert "expected_version" in response.json()["error"]["fields"]


async def test_update_rule_rebinds_plan(case) -> None:
    rule_id = (await create_rule(case)).json()["rule_id"]
    response = await case.client.patch(
        f"/api/business/watch-rules/{rule_id}",
        json={"expected_version": 1, "plan_id": str(case.pid)},
        headers=headers(case),
    )
    assert response.status_code == 200, response.text
    detail = await case.client.get(f"/api/business/watch-rules/{rule_id}", headers=case.headers)
    assert detail.json()["plan_id"] == str(case.pid)
    # 重绑其他研究的计划被拒绝（归属一致性）。
    rebind = await case.client.patch(
        f"/api/business/watch-rules/{rule_id}",
        json={"expected_version": 2, "plan_id": str(case.pid2)},
        headers=headers(case),
    )
    assert rebind.status_code == 404, rebind.text


async def test_rule_lifecycle_pause_resume_cancel(case) -> None:
    rule_id = (await create_rule(case)).json()["rule_id"]

    paused = await case.client.post(
        f"/api/business/watch-rules/{rule_id}/pause",
        json={"expected_version": 1},
        headers=headers(case),
    )
    assert paused.status_code == 200, paused.text
    assert paused.json()["status"] == "paused"

    resumed = await case.client.post(
        f"/api/business/watch-rules/{rule_id}/resume",
        json={"expected_version": 1},
        headers=headers(case),
    )
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["status"] == "active"

    cancelled = await case.client.post(
        f"/api/business/watch-rules/{rule_id}/cancel",
        json={"expected_version": 1},
        headers=headers(case),
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"

    # 终态：不能再暂停/恢复/编辑；取消的重试本身幂等返回。
    for path in ("pause", "resume"):
        response = await case.client.post(
            f"/api/business/watch-rules/{rule_id}/{path}",
            json={"expected_version": 1},
            headers=headers(case),
        )
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "rule_cancelled"
    response = await case.client.patch(
        f"/api/business/watch-rules/{rule_id}",
        json={"expected_version": 1, "threshold": "25.00"},
        headers=headers(case),
    )
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "rule_cancelled"


async def test_status_op_requires_expected_version(case) -> None:
    rule_id = (await create_rule(case)).json()["rule_id"]
    response = await case.client.post(
        f"/api/business/watch-rules/{rule_id}/pause", json={}, headers=headers(case)
    )
    assert response.status_code == 400, response.text
    assert "expected_version" in response.json()["error"]["fields"]


async def test_other_user_cannot_read_or_modify(case) -> None:
    rule_id = (await create_rule(case)).json()["rule_id"]
    other = uuid.uuid4()
    async with biz.business_transaction() as session:
        session.add(store.User(id=other, username=f"watch-other-{other.hex}", password_hash="x"))
        await session.flush()
    other_headers = {"Authorization": f"Bearer {create_access_token(other)}"}
    get = await case.client.get(f"/api/business/watch-rules/{rule_id}", headers=other_headers)
    assert get.status_code == 404, get.text
    patch = await case.client.patch(
        f"/api/business/watch-rules/{rule_id}",
        json={"expected_version": 1, "threshold": "99.00"},
        headers={**other_headers, "Idempotency-Key": uuid.uuid4().hex},
    )
    assert patch.status_code == 404, patch.text
    cancel = await case.client.post(
        f"/api/business/watch-rules/{rule_id}/cancel",
        json={"expected_version": 1},
        headers={**other_headers, "Idempotency-Key": uuid.uuid4().hex},
    )
    assert cancel.status_code == 404, cancel.text


async def test_rule_survives_restart(case) -> None:
    rule_id = (await create_rule(case)).json()["rule_id"]
    await case.client.post(
        f"/api/business/watch-rules/{rule_id}/pause",
        json={"expected_version": 1},
        headers=headers(case),
    )
    # 模拟重启：完全新的会话/新连接重新读取数据库，规则与状态必须仍在。
    async with biz.business_transaction() as session:
        row = (
            await session.execute(
                select(store.WatchRule).where(store.WatchRule.id == uuid.UUID(rule_id))
            )
        ).scalar_one()
        assert row.status == "paused"
        assert row.current_version == 1
    listing = await case.client.get(
        f"/api/business/watch-rules?research_id={case.rid}", headers=case.headers
    )
    items = listing.json()["rules"]
    assert len(items) == 1
    assert items[0]["id"] == rule_id
    assert items[0]["status"] == "paused"


async def test_record_check_updates_quote_times(case) -> None:
    rule_id = uuid.UUID((await create_rule(case)).json()["rule_id"])
    quote_at = datetime.now(UTC) - timedelta(seconds=5)
    async with biz.business_transaction() as session:
        ok = await watch_rules.record_check(
            session, rule_id=rule_id, quote_at=quote_at, price=Decimal("20.05")
        )
        assert ok is True
    detail = await case.client.get(f"/api/business/watch-rules/{rule_id}", headers=case.headers)
    item = detail.json()
    assert item["last_check_at"] is not None
    assert item["last_valid_quote_at"] == quote_at.isoformat()
    assert item["last_valid_quote_price"] == "20.05"


async def test_version_rows_are_immutable(case) -> None:
    rule_id = (await create_rule(case)).json()["rule_id"]
    with pytest.raises(Exception) as err:
        async with biz.business_transaction() as session:
            row = (
                await session.execute(
                    select(store.WatchRuleRevision).where(
                        store.WatchRuleRevision.rule_id == uuid.UUID(rule_id),
                        store.WatchRuleRevision.version == 1,
                    )
                )
            ).scalar_one()
            # 版本行只 INSERT：数据库层拒绝 UPDATE（0014 触发器）。
            row.symbol = "000001.SZ"
            await session.flush()
    assert "immutable" in str(err.value)


async def test_list_filters_by_research_and_status(case) -> None:
    rule_id = (await create_rule(case)).json()["rule_id"]
    # 另一个研究中再建一条。
    await create_rule(case, research_id=case.rid2, name="另一研究规则")
    await case.client.post(
        f"/api/business/watch-rules/{rule_id}/pause",
        json={"expected_version": 1},
        headers=headers(case),
    )
    by_research = await case.client.get(
        f"/api/business/watch-rules?research_id={case.rid}", headers=case.headers
    )
    assert by_research.json()["total"] == 1
    by_status = await case.client.get(
        "/api/business/watch-rules?status=paused", headers=case.headers
    )
    assert by_status.json()["total"] == 1
    all_rules = await case.client.get("/api/business/watch-rules", headers=case.headers)
    assert all_rules.json()["total"] == 2
