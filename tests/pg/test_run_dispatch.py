"""DATA-06 验收：原子提交、outbox 派发、租约与研究级串行（真实 PostgreSQL）。

覆盖 AC-05、15、23 的服务端部分：

* 提交原子性：业务 Run 的事务同时落 session/run/turn/快照/outbox；失败全回滚
* 派发恢复：领取 → 投递 → 回报全链路；提交成功即可恢复派发
* 研究级串行：同研究已有 active Run 时延后领取，绝不并发执行
* 租约过期：先核定旧 worker 状态 —— 未启动才重投，已启动绝不投第二个
* 失败退避与重试耗尽：retryable_failed → abandoned，Run 仍可取消重提
* 幂等重放不产生第二个 Run、第二个 outbox 行
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from httpx import ASGITransport
from sqlalchemy import text

from server import business_service as biz
from server import dispatch_outbox, store
from server.app import app
from server.config import build_run_paths, get_config, run_dir_for
from server.orchestrator import Orchestrator
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
        transport=ASGITransport(app=app), base_url="http://dispatch.test"
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


async def _business_payload(client, token, research_id, key=None) -> dict:
    """建会话 + 账户 + 计划，返回可直接提交的 investment_input。"""
    from server.security import decode_access_token

    # 计划端点要求研究（sessions）存在且属于该用户；这里按需要补建会话行。
    async with biz.business_transaction() as session:
        await session.execute(
            text(
                "INSERT INTO sessions (id, user_id, title) VALUES (:id, :uid, '研究') "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {"id": research_id, "uid": decode_access_token(token.removeprefix("Bearer "))},
        )
    payload = {
        "use_case": "plan_analysis",
        "account": {"id": None},
        "idempotency_key": key or f"analyze:{uuid.uuid4()}",
    }
    response = await client.post(
        "/api/business/accounts",
        json={
            "name": f"账户{uuid.uuid4().hex[:8]}",
            "base_currency": "CNY",
            "declared": dict(CAPITAL),
        },
        headers={"Authorization": token, "Idempotency-Key": f"acc:{uuid.uuid4()}"},
    )
    assert response.status_code == 201, response.text
    account = response.json()
    plan_response = await client.post(
        f"/api/business/sessions/{research_id}/plans",
        json={"name": f"计划{uuid.uuid4().hex[:8]}", "declared": dict(PLAN)},
        headers={"Authorization": token, "Idempotency-Key": f"plan:{uuid.uuid4()}"},
    )
    assert plan_response.status_code == 201, plan_response.text
    plan = plan_response.json()

    payload["account"] = {"id": account["account_id"]}
    payload["plan"] = {"id": plan["plan_id"]}
    return payload


async def _submit_json_run(client, token, research_id, payload):
    return await client.post(
        "/api/runs",
        json={
            "message": "按计划分析",
            "session_id": str(research_id),
            "investment_input": payload,
        },
        headers={"Authorization": token},
    )


async def _submit_multipart_run(client, token, research_id, files, payload):
    return await client.post(
        "/api/runs",
        data={
            "message": "按计划分析",
            "session_id": str(research_id),
            "investment_input": json.dumps(payload),
        },
        files=files,
        headers={"Authorization": token},
    )


async def _submit_business_run(client, token, research_id, key=None):
    payload = await _business_payload(client, token, research_id, key=key)
    response = await _submit_json_run(client, token, research_id, payload)
    assert response.status_code == 202, response.text
    return response.json()


async def _outbox_rows(research_id: uuid.UUID) -> list:
    async with biz.business_transaction() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT run_id, status, attempt, claim_version, next_attempt_at "
                    "FROM run_dispatch_outbox WHERE research_id = :rid"
                ),
                {"rid": research_id},
            )
        ).all()
    return rows


async def _turn_count(research_id: uuid.UUID) -> int:
    async with biz.business_transaction() as session:
        return (
            await session.execute(
                text("SELECT count(*) FROM turns WHERE session_id = :rid"),
                {"rid": research_id},
            )
        ).scalar_one()


async def test_submit_persists_dispatch_intent_atomically(client) -> None:
    """提交成功即同时存在 Run、用户消息与待派发行（AC-05/23）。"""
    token, _ = await _new_user("pg-disp-atomic")
    research_id = uuid.uuid4()
    body = await _submit_business_run(client, token, research_id)

    assert body["dispatch"]["status"] == "pending"
    rows = await _outbox_rows(research_id)
    assert len(rows) == 1
    assert rows[0].status == "pending"
    assert rows[0].attempt == 0
    # 用户消息随提交事务落库，派发不得再追加。
    assert await _turn_count(research_id) == 1


async def test_dispatch_once_claims_and_submits(client, stub_orchestrator) -> None:
    """领取 → 投递 → 回报：一行完成一次派发，消息不被重复追加。"""
    token, _ = await _new_user("pg-disp-once")
    research_id = uuid.uuid4()
    body = await _submit_business_run(client, token, research_id)

    dispatched = await dispatch_outbox.dispatch_once(stub_orchestrator)
    assert dispatched == 1
    assert len(stub_orchestrator.submitted) == 1
    submitted = stub_orchestrator.submitted[0]
    assert submitted["run_id"] == body["run_id"]
    assert submitted["backfill_turn"] is False

    rows = await _outbox_rows(research_id)
    assert rows[0].status == "dispatched"
    assert rows[0].attempt == 1
    assert await _turn_count(research_id) == 1, "派发重复追加了用户消息"


async def test_research_serialization_defers_dispatch(client, stub_orchestrator) -> None:
    """AC-13：同研究已有 active Run 时延后，而不是并发执行。"""
    token, _ = await _new_user("pg-disp-serial")
    research_id = uuid.uuid4()
    first = await _submit_business_run(client, token, research_id)
    second = await _submit_business_run(client, token, research_id)

    # 第一轮只能投递一个（第二个必须等第一个结束）。
    dispatched = await dispatch_outbox.dispatch_once(stub_orchestrator)
    assert dispatched == 1

    # 模拟第一个仍在执行：把它的 Run 标记为 running。
    async with biz.business_transaction() as session:
        await session.execute(
            text("UPDATE runs SET status='running' WHERE id=:rid"),
            {"rid": uuid.UUID(first["run_id"])},
        )

    await dispatch_outbox.dispatch_once(stub_orchestrator)
    rows = {r.run_id.hex: r for r in await _outbox_rows(research_id)}
    assert rows[second["run_id"]].status in ("pending", "retryable_failed"), (
        "研究忙时应延后而不是派发"
    )
    assert rows[second["run_id"]].next_attempt_at is not None
    assert len(stub_orchestrator.submitted) == 1


async def test_research_ready_after_previous_finishes(client, stub_orchestrator) -> None:
    """前一个 Run 终态后，同研究的下一个可以派发。"""
    token, _ = await _new_user("pg-disp-ready")
    research_id = uuid.uuid4()
    first = await _submit_business_run(client, token, research_id)
    second = await _submit_business_run(client, token, research_id)

    assert await dispatch_outbox.dispatch_once(stub_orchestrator) == 1
    # 第一个完成（终态）后释放研究。
    async with biz.business_transaction() as session:
        await session.execute(
            text("UPDATE runs SET status='completed' WHERE id=:rid"),
            {"rid": uuid.UUID(first["run_id"])},
        )
    # 把第二个的退避时间拨回过去，模拟到期。
    async with biz.business_transaction() as session:
        await session.execute(
            text("UPDATE run_dispatch_outbox SET next_attempt_at = :past WHERE run_id = :rid"),
            {"past": datetime.now(UTC) - timedelta(seconds=1), "rid": uuid.UUID(second["run_id"])},
        )
    assert await dispatch_outbox.dispatch_once(stub_orchestrator) == 1
    assert len(stub_orchestrator.submitted) == 2


async def test_failed_submit_backs_off_then_abandons(client, stub_orchestrator) -> None:
    """投递失败退避重试；重试耗尽 abandoned，Run 不被重复创建。"""
    token, _ = await _new_user("pg-disp-fail")
    research_id = uuid.uuid4()
    body = await _submit_business_run(client, token, research_id)

    async def failing(**kwargs):
        raise RuntimeError("worker spawn failed")

    stub_orchestrator.submit = failing  # type: ignore[method-assign]
    await dispatch_outbox.dispatch_once(stub_orchestrator)
    rows = {r.run_id.hex: r for r in await _outbox_rows(research_id)}
    assert rows[body["run_id"]].status == "retryable_failed"
    assert rows[body["run_id"]].attempt == 1

    # 把重试上限压到已耗尽：下一次失败应直接 abandoned。
    async with biz.business_transaction() as session:
        await session.execute(
            text(
                "UPDATE run_dispatch_outbox SET attempt = max_attempts, "
                "status='pending', next_attempt_at=NULL WHERE run_id=:rid"
            ),
            {"rid": uuid.UUID(body["run_id"])},
        )
    await dispatch_outbox.dispatch_once(stub_orchestrator)
    rows = {r.run_id.hex: r for r in await _outbox_rows(research_id)}
    assert rows[body["run_id"]].status == "abandoned"
    # Run 仍是 queued：可被取消重提，不会自己复活。
    async with biz.business_transaction() as session:
        run = await session.get(store.Run, uuid.UUID(body["run_id"]))
        assert run.status == "queued"


async def test_expired_lease_requeues_unstarted_run(client, stub_orchestrator) -> None:
    """租约过期 + Run 仍 queued：原领取从未启动 worker，允许重新领取。"""
    token, _ = await _new_user("pg-disp-lease-queued")
    research_id = uuid.uuid4()
    body = await _submit_business_run(client, token, research_id)

    async with store.get_sessionmaker()() as session, session.begin():
        claimed = await dispatch_outbox.claim_due(session)
        assert len(claimed) == 1
    # 不投递，直接把租约拨到过期。
    async with biz.business_transaction() as session:
        await session.execute(
            text(
                "UPDATE run_dispatch_outbox SET lease_expires_at = :past, "
                "status='claimed' WHERE run_id=:rid"
            ),
            {"past": datetime.now(UTC) - timedelta(seconds=1), "rid": uuid.UUID(body["run_id"])},
        )
    async with store.get_sessionmaker()() as session, session.begin():
        released = await dispatch_outbox.reclaim_expired(session)
        assert released == 1
    rows = {r.run_id.hex: r for r in await _outbox_rows(research_id)}
    assert rows[body["run_id"]].status == "pending"
    # 重新领取后可以正常投递，且仍是同一个 Run。
    assert await dispatch_outbox.dispatch_once(stub_orchestrator) == 1
    assert stub_orchestrator.submitted[0]["run_id"] == body["run_id"]


async def test_expired_lease_never_redispatches_started_run(client) -> None:
    """租约过期 + Run 已 running：绝不投出第二个执行（AC-15/21）。"""
    token, _ = await _new_user("pg-disp-lease-running")
    research_id = uuid.uuid4()
    body = await _submit_business_run(client, token, research_id)

    async with store.get_sessionmaker()() as session, session.begin():
        claimed = await dispatch_outbox.claim_due(session)
        assert len(claimed) == 1
    # worker 已启动：Run 变 running，租约同时过期。
    async with biz.business_transaction() as session:
        await session.execute(
            text("UPDATE runs SET status='running' WHERE id=:rid"),
            {"rid": uuid.UUID(body["run_id"])},
        )
        await session.execute(
            text("UPDATE run_dispatch_outbox SET lease_expires_at=:past WHERE run_id=:rid"),
            {"rid": uuid.UUID(body["run_id"]), "past": datetime.now(UTC) - timedelta(seconds=1)},
        )
    async with store.get_sessionmaker()() as session, session.begin():
        await dispatch_outbox.reclaim_expired(session)
    rows = {r.run_id.hex: r for r in await _outbox_rows(research_id)}
    assert rows[body["run_id"]].status == "dispatched"


async def test_cancel_pending_dispatch_marks_run_stopped(client) -> None:
    """排队任务的"取消重提"：pending 派发作废 + Run 置 stopped，同一事务。"""
    token, _ = await _new_user("pg-disp-cancel")
    research_id = uuid.uuid4()
    body = await _submit_business_run(client, token, research_id)
    run_uuid = uuid.UUID(body["run_id"])

    async with biz.business_transaction() as session:
        cancelled = await dispatch_outbox.cancel_pending(
            session, run_id=run_uuid, reason="测试取消"
        )
        assert cancelled is True
        run = await session.get(store.Run, run_uuid, with_for_update=True)
        run.status = "stopped"
        run.stopped_by = "superseded_by_rerun"

    rows = {r.run_id.hex: r for r in await _outbox_rows(research_id)}
    assert rows[body["run_id"]].status == "abandoned"


async def test_idempotent_replay_creates_no_second_outbox(client) -> None:
    """AC-05：同键重放回到原 Run，不产生第二个 Run 或派发行。"""
    token, _ = await _new_user("pg-disp-idem")
    research_id = uuid.uuid4()
    from server.security import decode_access_token

    async with biz.business_transaction() as session:
        await session.execute(
            text(
                "INSERT INTO sessions (id, user_id, title) VALUES (:id, :uid, '研究') "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {"id": research_id, "uid": decode_access_token(token.removeprefix("Bearer "))},
        )
    # 幂等重放：同键 + 同内容（对象引用与声明完全一致）→ 回原 Run。
    payload_key = f"analyze:fixed-{uuid.uuid4()}"

    account_response = await client.post(
        "/api/business/accounts",
        json={
            "name": f"账户{uuid.uuid4().hex[:6]}",
            "base_currency": "CNY",
            "declared": dict(CAPITAL),
        },
        headers={"Authorization": token, "Idempotency-Key": f"acc:{uuid.uuid4()}"},
    )
    assert account_response.status_code == 201, account_response.text
    account = account_response.json()
    plan_response = await client.post(
        f"/api/business/sessions/{research_id}/plans",
        json={"name": f"计划{uuid.uuid4().hex[:8]}", "declared": dict(PLAN)},
        headers={"Authorization": token, "Idempotency-Key": f"plan:{uuid.uuid4()}"},
    )
    assert plan_response.status_code == 201, plan_response.text
    plan = plan_response.json()

    investment_input = {
        "use_case": "plan_analysis",
        "account": {"id": account["account_id"]},
        "plan": {"id": plan["plan_id"]},
        "idempotency_key": payload_key,
    }

    async def submit_once():
        return await client.post(
            "/api/runs",
            json={
                "message": "按计划分析",
                "session_id": str(research_id),
                "investment_input": investment_input,
            },
            headers={"Authorization": token},
        )

    first = await submit_once()
    second = await submit_once()
    assert first.status_code == 202 and second.status_code == 202
    assert second.json()["run_id"] == first.json()["run_id"]
    assert second.json()["replayed"] is True

    rows = await _outbox_rows(research_id)
    assert len(rows) == 1, "重放产生了第二个派发行"
    async with biz.business_transaction() as session:
        run_count = (
            await session.execute(
                text("SELECT count(*) FROM runs WHERE session_id=:rid"), {"rid": research_id}
            )
        ).scalar_one()
    assert run_count == 1


async def test_dispatch_status_endpoint(client) -> None:
    """派发状态与 Run 状态分离可查；旧客户端路径报 not_required。"""
    token, _ = await _new_user("pg-disp-status")
    research_id = uuid.uuid4()
    body = await _submit_business_run(client, token, research_id)

    response = await client.get(
        f"/api/runs/{body['run_id']}/dispatch", headers={"Authorization": token}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "pending"
    assert response.json()["attempt"] == 0

    legacy = await client.post(
        "/api/runs",
        json={"message": "普通问题", "session_id": str(research_id)},
        headers={"Authorization": token},
    )
    assert legacy.status_code == 202
    legacy_status = await client.get(
        f"/api/runs/{legacy.json()['run_id']}/dispatch", headers={"Authorization": token}
    )
    assert legacy_status.json()["status"] == "not_required"


async def test_rerun_stops_a_running_old_run(client, stub_orchestrator) -> None:
    """重算运行中的旧 Run：停止请求必须真正发出（async stop 必须被 await）。"""
    token, _ = await _new_user("pg-disp-rerun-stop")
    research_id = uuid.uuid4()
    body = await _submit_business_run(client, token, research_id)

    async with biz.business_transaction() as session:
        await session.execute(
            text("UPDATE runs SET status='running' WHERE id=:rid"),
            {"rid": uuid.UUID(body["run_id"])},
        )

    rerun = await client.post(
        f"/api/runs/{body['run_id']}/rerun",
        json={},
        headers={"Authorization": token, "Idempotency-Key": f"rerun:{uuid.uuid4()}"},
    )
    assert rerun.status_code == 202, rerun.text
    payload = rerun.json()
    assert payload["old_run_stop_requested"] is True
    assert stub_orchestrator.stopped == [body["run_id"]], "旧执行的停止请求没有真正发出"


async def test_orphan_reconcile_keeps_committed_but_undispatched_run(
    client, stub_orchestrator
) -> None:
    """重启恢复（AC-05）：已提交待派发的 Run 有存活 outbox，不得被孤儿扫描判死。"""
    token, user_id = await _new_user("pg-disp-reconcile")
    research_id = uuid.uuid4()
    body = await _submit_business_run(client, token, research_id)

    # 对照组：无 outbox 的旧式排队 Run，是真正的孤儿（worker 已随进程消失）。
    legacy_session = uuid.uuid4()
    legacy_run = uuid.uuid4()
    async with biz.business_transaction() as session:
        await session.execute(
            text("INSERT INTO sessions (id, user_id, title) VALUES (:id, :uid, '旧研究')"),
            {"id": legacy_session, "uid": user_id},
        )
    await store.create_run(
        run_id=legacy_run,
        session_id=legacy_session,
        user_id=user_id,
        prompt="旧式排队",
        pipeline_id="stateful-react-agent",
        run_dir=str(run_dir_for(legacy_run.hex)),
        status="queued",
    )

    # 模拟重启：真实 Orchestrator 启动时做孤儿扫描。
    closed = await Orchestrator().reconcile_orphan_runs()

    assert closed == 1, "只有无派发意图的真孤儿应被收尾"
    async with biz.business_transaction() as session:
        reaped = await session.get(store.Run, legacy_run)
        kept = await session.get(store.Run, uuid.UUID(body["run_id"]))
    assert reaped.status in ("failed", "stopped")
    assert kept.status == "queued", "已提交待派发的 Run 被误判为孤儿"

    rows = await _outbox_rows(research_id)
    assert rows[0].status == "pending", "派发意图被孤儿恢复作废"

    # 重启后派发循环仍能把它投出去：恢复承诺成立。
    assert await dispatch_outbox.dispatch_once(stub_orchestrator) == 1
    assert stub_orchestrator.submitted[0]["run_id"] == body["run_id"]


async def _upload_rows(run_uuid: uuid.UUID) -> list:
    async with biz.business_transaction() as session:
        return (
            await session.execute(
                text(
                    "SELECT stored_name, display_name, status, sha256, size_bytes "
                    "FROM run_uploads WHERE run_id = :rid ORDER BY stored_name"
                ),
                {"rid": run_uuid},
            )
        ).all()


# ── DATA-06 附件：受控暂存区 + 持久清单 + 发布门禁 ─────────────────────


async def test_submit_stages_upload_and_dispatch_publishes_it(client, stub_orchestrator) -> None:
    """附件先进暂存区并记清单；worker 领取前才校验并发布到 inputs（AC-05/23）。"""
    token, _ = await _new_user("pg-up-staged")
    research_id = uuid.uuid4()
    payload = await _business_payload(client, token, research_id)

    response = await _submit_multipart_run(
        client,
        token,
        research_id,
        {"files": ("brief.md", b"# Brief\nread me\n", "text/markdown")},
        payload,
    )
    assert response.status_code == 202, response.text
    body = response.json()
    run_uuid = uuid.UUID(body["run_id"])

    rows = await _upload_rows(run_uuid)
    assert len(rows) == 1
    assert rows[0].status == "staged", "清单行（发布意图）未与提交同事务落库"
    paths = build_run_paths(body["run_id"])
    assert (paths["staging"] / "brief.md").exists(), "附件没有进受控暂存区"
    assert not (paths["inputs"] / "brief.md").exists(), "未校验就发布到了 inputs"

    # 派发：先做发布校验（移入 inputs 并置 published），再投 worker。
    assert await dispatch_outbox.dispatch_once(stub_orchestrator) == 1
    assert (paths["inputs"] / "brief.md").read_bytes() == b"# Brief\nread me\n"
    assert (await _upload_rows(run_uuid))[0].status == "published"
    assert "/inputs/brief.md" in stub_orchestrator.submitted[0]["prompt_addendum"]


async def test_tampered_staged_file_blocks_dispatch(client, stub_orchestrator) -> None:
    """暂存文件被篡改（摘要不符）：不发布、不投递，避免带着错文件启动（AC-23）。"""
    token, _ = await _new_user("pg-up-tamper")
    research_id = uuid.uuid4()
    payload = await _business_payload(client, token, research_id)
    response = await _submit_multipart_run(
        client, token, research_id, {"files": ("note.txt", b"original", "text/plain")}, payload
    )
    assert response.status_code == 202, response.text
    body = response.json()
    run_uuid = uuid.UUID(body["run_id"])
    paths = build_run_paths(body["run_id"])

    (paths["staging"] / "note.txt").write_bytes(b"tampered")
    assert await dispatch_outbox.dispatch_once(stub_orchestrator) == 0
    assert stub_orchestrator.submitted == []
    assert not (paths["inputs"] / "note.txt").exists()
    # 清单停在 staged（未发布）；派发意图退避重试。
    assert (await _upload_rows(run_uuid))[0].status == "staged"
    assert (await _outbox_rows(research_id))[0].status == "retryable_failed"


async def test_missing_staged_file_blocks_dispatch(client, stub_orchestrator) -> None:
    """暂存文件缺失：不投递（退避重试），"数据库成功但启动缺文件"不发生。"""
    token, _ = await _new_user("pg-up-missing")
    research_id = uuid.uuid4()
    payload = await _business_payload(client, token, research_id)
    response = await _submit_multipart_run(
        client, token, research_id, {"files": ("gone.txt", b"x", "text/plain")}, payload
    )
    assert response.status_code == 202, response.text
    body = response.json()
    run_uuid = uuid.UUID(body["run_id"])
    paths = build_run_paths(body["run_id"])

    (paths["staging"] / "gone.txt").unlink()
    assert await dispatch_outbox.dispatch_once(stub_orchestrator) == 0
    assert stub_orchestrator.submitted == []
    assert (await _upload_rows(run_uuid))[0].status == "staged"
    assert (await _outbox_rows(research_id))[0].status == "retryable_failed"


async def test_duplicate_upload_name_rejected_before_writing(client) -> None:
    """重名在写盘前就拒绝（409），不留任何字节。"""
    token, _ = await _new_user("pg-up-dup")
    research_id = uuid.uuid4()
    payload = await _business_payload(client, token, research_id)

    response = await _submit_multipart_run(
        client,
        token,
        research_id,
        [
            ("files", ("dup.txt", b"a", "text/plain")),
            ("files", ("dup.txt", b"b", "text/plain")),
        ],
        payload,
    )
    assert response.status_code == 409, response.text
    assert "duplicate" in response.json()["detail"].lower()


# ── DATA-06 队列上限与停止超时 ─────────────────────────────────────────


async def test_research_queue_limit_rejects_submit(client, monkeypatch) -> None:
    """逐研究队列上限：到顶后拒绝新建（429 quota_exceeded），不产生第二个 Run。"""
    monkeypatch.setattr(get_config(), "dispatch_research_queue_limit", 1)
    token, _ = await _new_user("pg-q-limit")
    research_id = uuid.uuid4()
    first = await _submit_business_run(client, token, research_id)

    payload = await _business_payload(client, token, research_id)
    response = await _submit_json_run(client, token, research_id, payload)
    assert response.status_code == 429, response.text
    error = response.json()["error"]
    assert error["code"] == "quota_exceeded"
    assert error["remedy"] == "wait"

    async with biz.business_transaction() as session:
        count = (
            await session.execute(
                text("SELECT count(*) FROM runs WHERE session_id = :rid"), {"rid": research_id}
            )
        ).scalar_one()
    assert count == 1, "超限提交仍创建了 Run"
    assert first["run_id"]


async def test_rerun_not_blocked_by_queue_limit_for_superseded_run(client, monkeypatch) -> None:
    """重算取代排队中的旧 Run：旧 Run 不计入深度，不被上限误拒。"""
    monkeypatch.setattr(get_config(), "dispatch_research_queue_limit", 1)
    token, _ = await _new_user("pg-q-rerun")
    research_id = uuid.uuid4()
    first = await _submit_business_run(client, token, research_id)

    response = await client.post(
        f"/api/runs/{first['run_id']}/rerun",
        json={},
        headers={"Authorization": token, "Idempotency-Key": f"rerun:{uuid.uuid4()}"},
    )
    assert response.status_code == 202, response.text
    assert response.json()["old_run_cancelled"] is True


async def test_rerun_reports_stop_timeout_and_still_serializes(client, stub_orchestrator) -> None:
    """停止超时：报告超时，且新 Run 仍被研究互斥挡住，绝不并发执行（DATA-06）。"""
    token, _ = await _new_user("pg-stop-timeout")
    research_id = uuid.uuid4()
    body = await _submit_business_run(client, token, research_id)
    async with biz.business_transaction() as session:
        await session.execute(
            text("UPDATE runs SET status='running' WHERE id=:rid"),
            {"rid": uuid.UUID(body["run_id"])},
        )

    async def _never_stopped(run_id: str, *, timeout: float) -> bool:
        return False

    stub_orchestrator.wait_stopped = _never_stopped  # type: ignore[method-assign]
    response = await client.post(
        f"/api/runs/{body['run_id']}/rerun",
        json={},
        headers={"Authorization": token, "Idempotency-Key": f"rerun:{uuid.uuid4()}"},
    )
    assert response.status_code == 202, response.text
    data = response.json()
    assert data["old_run_stop_requested"] is True
    assert data["old_run_stopped"] is False
    assert data["old_run_stop_timed_out"] is True

    # 旧 Run 仍在 running：研究互斥必须挡住新 Run，一个都不投。
    assert await dispatch_outbox.dispatch_once(stub_orchestrator) == 0
    assert stub_orchestrator.submitted == []
