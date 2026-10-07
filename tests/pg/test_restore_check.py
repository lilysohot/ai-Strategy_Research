"""真 PG 验收：DATA-14 恢复/迁移核对与后台任务闸门。

覆盖四类恢复语义（§5 生命周期、恢复和工程验收）：

* ``check_restore`` 一次核对——完整清单通过、缺目录/缺轨迹/孤立引用/密钥解密失败
  分别明确报错，报告结构可供恢复操作员对照备份快照；
* ``restore_mode`` 闸门——dispatch/monitor/scheduler 三个后台循环见到即停，
  显式关闭后恢复工作；手动提交 Run 返回 503，关闭后恢复 202；
* 敏感数据——归档审计 detail 只含标识符，不含资金正文（金额/持仓值）；
* CLI 出口——``python -m server.restore_check`` 对干净库 exit 0。
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import uuid
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import select

from server import business_service as biz
from server import dispatch_outbox as dispatch
from server import monitor as monitor_mod
from server import restore_check, store
from server import watch_scheduler as scheduler_mod
from server.app import app
from server.business_archive import archive_account
from server.config import get_config, run_dir_for
from server.security import create_access_token

pytestmark = pytest.mark.pg


def _make_run_dir(run_id: uuid.UUID, *, trajectory: bool) -> Path:
    root = run_dir_for(str(run_id))
    for rel in restore_check.REQUIRED_RUN_DIRS:
        (root / rel).mkdir(parents=True, exist_ok=True)
    if trajectory:
        path = root / restore_check.TRAJECTORY_RELPATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"events": []}\n', encoding="utf-8")
    return root


@pytest.fixture
async def user_and_research(pg_clean):
    uid, rid = uuid.uuid4(), uuid.uuid4()
    async with biz.business_transaction() as session:
        session.add(store.User(id=uid, username=f"restore-{uid.hex[:8]}", password_hash="unused"))
        await session.flush()
        session.add(store.Session(id=rid, user_id=uid, title="restore"))
    return SimpleNamespace(uid=uid, rid=rid)


async def _add_run(user_id: uuid.UUID, session_id: uuid.UUID, *, status: str) -> uuid.UUID:
    run_id = uuid.uuid4()
    async with biz.business_transaction() as session:
        # 与提交流程一致（routes/runs.py）：Run 行记录 run_dir 绝对路径（列非空），
        # 必须在 flush 前就位。
        session.add(
            store.Run(
                id=run_id,
                session_id=session_id,
                user_id=user_id,
                status=status,
                pipeline_id="stateful-react-agent",
                prompt="restore-check",
                run_dir=str(run_dir_for(run_id.hex)),
            )
        )
    return run_id


async def _check() -> dict:
    async with biz.business_transaction() as session:
        return await restore_check.check_restore(session)


# — check_restore：一次核对 ———————————————————————————————————————


async def test_clean_database_with_complete_run_dirs_passes(user_and_research):
    run_id = await _add_run(user_and_research.uid, user_and_research.rid, status="queued")
    _make_run_dir(run_id, trajectory=False)  # queued Run 尚无轨迹是合法状态
    report = await _check()
    assert report["errors"] == []
    assert report["ok"] is True
    assert report["schema"]["ok"] is True
    assert report["runs"] == {
        "run_count": 1,
        "missing_dirs": [],
        "missing_trajectories": [],
    }
    assert report["relations"] == {name: 0 for name in report["relations"]}
    assert report["external_calls"] == {
        "watch_event_runs": 0,
        "budget_runs_created": 0,
        "run_dispatch_rows": 0,
        "pending_watch_events": 0,
    }
    assert report["credential_errors"] == []


async def test_started_run_requires_trajectory(user_and_research):
    run_id = await _add_run(user_and_research.uid, user_and_research.rid, status="running")
    _make_run_dir(run_id, trajectory=False)
    report = await _check()
    assert report["ok"] is False
    assert report["runs"]["missing_trajectories"] == [run_id.hex]
    assert any("missing trajectories" in error for error in report["errors"])


async def test_missing_run_dir_is_reported(user_and_research):
    await _add_run(user_and_research.uid, user_and_research.rid, status="queued")
    report = await _check()
    assert report["ok"] is False
    assert any("missing run dirs" in error for error in report["errors"])


async def test_schema_watermark_mismatch_is_reported(user_and_research):
    async with biz.business_transaction() as session:
        report = await restore_check.check_restore(
            session, expected_head="0000_not_a_real_revision"
        )
    assert report["schema"]["ok"] is False
    assert report["schema"]["expected_head"] == "0000_not_a_real_revision"
    assert any("schema watermark mismatch" in error for error in report["errors"])


async def test_orphan_watch_event_reference_is_reported(user_and_research):
    # InputRequest.watch_event_id 是唯一刻意不加外键的引用（DATA-11 表独立演进），
    # 因此也是恢复核对必须能抓到的真实孤立行来源。
    async with biz.business_transaction() as session:
        session.add(
            store.InputRequest(
                user_id=user_and_research.uid,
                research_id=user_and_research.rid,
                watch_event_id=uuid.uuid4(),  # 指向不存在的事件
                use_case="watch_follow_up",
                fields_json=[{"name": "account.currency", "required": True}],
            )
        )
    report = await _check()
    assert report["ok"] is False
    assert report["relations"]["InputRequest.watch_event_id"] == 1
    assert any("orphan InputRequest.watch_event_id: 1" in error for error in report["errors"])


async def test_undecryptable_llm_key_is_reported(user_and_research):
    async with biz.business_transaction() as session:
        session.add(
            store.UserLLMConfig(
                user_id=user_and_research.uid,
                name="default",
                base_url="https://example.invalid",
                model="glm-5.3-flash",
                api_key_cipher=b"not-a-fernet-token",  # master_key 轮换后无法解密
                is_default=True,
            )
        )
    report = await _check()
    assert report["ok"] is False
    assert report["credential_errors"] == [str(user_and_research.uid)]
    assert any("undecryptable llm keys" in error for error in report["errors"])


# — restore_mode：后台任务闸门 —————————————————————————————————————


async def _run_loops_briefly(monkeypatch, stub_orchestrator, *, restore_mode: bool) -> dict:
    """以极短轮询运行三个后台循环一小段时间，返回各工作函数的调用记录。"""
    monkeypatch.setattr(get_config(), "restore_mode", restore_mode)
    monkeypatch.setattr(get_config(), "dispatch_poll_seconds", 0.05)
    calls = {"dispatch": 0, "monitor": 0, "schedule": 0}

    async def _record_dispatch(orch):
        calls["dispatch"] += 1

    async def _record_monitor(quote_source, **kwargs):
        calls["monitor"] += 1

    async def _record_schedule(session, *, limit):
        calls["schedule"] += 1
        return {}

    monkeypatch.setattr(dispatch, "dispatch_once", _record_dispatch)
    monkeypatch.setattr(monitor_mod, "monitor_tick", _record_monitor)
    monkeypatch.setattr(scheduler_mod, "schedule_cycle", _record_schedule)

    tasks = [
        asyncio.create_task(dispatch.dispatch_loop(stub_orchestrator)),
        asyncio.create_task(
            monitor_mod.monitor_loop(
                object(),
                poll_seconds=0.05,
                max_rules=10,
                max_symbols=10,
                max_gap=timedelta(seconds=300),
            )
        ),
        asyncio.create_task(scheduler_mod.scheduler_loop(poll_seconds=0.05, batch=10)),
    ]
    await asyncio.sleep(0.25)
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    return calls


async def test_restore_mode_blocks_all_background_loops(monkeypatch, stub_orchestrator):
    calls = await _run_loops_briefly(monkeypatch, stub_orchestrator, restore_mode=True)
    assert calls == {"dispatch": 0, "monitor": 0, "schedule": 0}


async def test_closing_restore_mode_resumes_background_work(monkeypatch, stub_orchestrator):
    calls = await _run_loops_briefly(monkeypatch, stub_orchestrator, restore_mode=False)
    assert calls["dispatch"] >= 1
    assert calls["monitor"] >= 1
    assert calls["schedule"] >= 1


async def test_restore_mode_rejects_manual_submit_then_reopens(user_and_research, monkeypatch):
    monkeypatch.setattr(get_config(), "restore_mode", True)
    headers = {"Authorization": f"Bearer {create_access_token(user_and_research.uid)}"}
    body = {"message": "analyze", "session_id": str(user_and_research.rid)}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://restore.test"
    ) as client:
        response = await client.post("/api/runs", json=body, headers=headers)
        assert response.status_code == 503, response.text
        assert "恢复/迁移模式" in response.json()["detail"]
        monkeypatch.setattr(get_config(), "restore_mode", False)
        reopened = await client.post("/api/runs", json=body, headers=headers)
        assert reopened.status_code == 202, reopened.text


# — 敏感数据与 CLI 出口 ————————————————————————————————————————————


async def test_archive_audit_detail_contains_no_funding_body(user_and_research):
    uid = user_and_research.uid
    async with biz.business_transaction() as session:
        outcome = await biz.create_account(
            session,
            user_id=uid,
            name="restore-audit",
            base_currency="CNY",
            declared={
                "total_capital": "123456.78",
                "currency": "CNY",
                "capital_basis": "total",
                "as_of": "2026-10-07T00:00:00Z",
            },
            idempotency_key=uuid.uuid4().hex,
        )
        account_id = uuid.UUID(outcome.result["account_id"])
        await archive_account(
            session, user_id=uid, account_id=account_id, idempotency_key=uuid.uuid4().hex
        )
        rows = (
            (await session.execute(select(store.AuditLog).where(store.AuditLog.user_id == uid)))
            .scalars()
            .all()
        )
    archives = [row for row in rows if row.action == "account.archive"]
    assert archives, "归档必须留下审计行"
    for row in archives:
        detail = row.detail_json
        assert set(detail) == {"account_id", "paused_rules"}, detail
        # 资金正文（金额/币种/时点声明）绝不进审计 detail：只允许标识符。
        assert "123456.78" not in json.dumps(detail, ensure_ascii=False)


async def test_unreadable_report_is_flagged_not_crashed(user_and_research, pg_dsn):
    """AC-18：报告不可读时明确标识。

    模拟旧备份还原（缺 0016+0017 的表）：schema 水位不一致与分节失败都必须
    出现在同一份 JSON 报告里，而不是让核对崩溃丢失水位信息。核对后还原迁移。
    """
    run_id = await _add_run(user_and_research.uid, user_and_research.rid, status="queued")
    _make_run_dir(run_id, trajectory=False)

    def _alembic(action: str, target: str) -> None:
        proc = subprocess.run(
            [sys.executable, "-m", "alembic", "-c", "server/alembic.ini", action, target],
            cwd=str(Path(__file__).resolve().parents[2]),
            env=dict(os.environ, SERVER_DATABASE_URL=pg_dsn),
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert proc.returncode == 0, f"{action} {target} 失败：{proc.stdout}{proc.stderr}"

    try:
        _alembic("downgrade", "0015_watch_monitoring")
        report = await _check()
    finally:
        _alembic("upgrade", "head")

    assert report["schema"]["ok"] is False  # 旧备份水位不一致
    assert any("schema watermark mismatch" in error for error in report["errors"])
    assert any("restore check incomplete" in error for error in report["errors"])
    assert report["ok"] is False


def test_cli_exit_zero_on_clean_database(pg_dsn, pg_clean, tmp_path):
    runs_root = tmp_path / "cli-runs"
    runs_root.mkdir()
    proc = subprocess.run(
        [sys.executable, "-m", "server.restore_check", str(runs_root)],
        cwd=str(Path(__file__).resolve().parents[2]),
        env=dict(os.environ, SERVER_DATABASE_URL=pg_dsn),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    report = json.loads(proc.stdout)
    assert report["ok"] is True
    assert report["runs"]["run_count"] == 0
