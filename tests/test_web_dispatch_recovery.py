"""A debug-mode boot during a DB outage must resume dispatch after recovery."""

import asyncio
from unittest.mock import AsyncMock

import server.app as app_module
from server.config import get_config
from server.readiness import Readiness


async def test_dispatch_recovers_after_unready_startup(monkeypatch):
    cfg = get_config()
    monkeypatch.setattr(cfg, "debug", True)
    monkeypatch.setattr(cfg, "restore_mode", False)
    monkeypatch.setattr(cfg, "dispatch_enabled", True)
    monkeypatch.setattr(cfg, "dispatch_poll_seconds", 0.01)
    monkeypatch.setattr(app_module, "check_startup_secrets", lambda: None)
    monkeypatch.setattr(app_module, "init_db", AsyncMock())
    ready = False
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def readiness():
        return Readiness(ok=ready, reasons=() if ready else ("database_unavailable",))

    async def dispatch(_orch):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    monkeypatch.setattr(app_module, "storage_readiness", readiness)
    monkeypatch.setattr(app_module, "dispatch_loop", dispatch)
    orch = AsyncMock()
    monkeypatch.setattr(app_module, "get_orchestrator", lambda: orch)
    async with app_module.lifespan(app_module.app):
        await asyncio.sleep(0.03)
        assert not started.is_set(), "dispatch must remain gated while storage is unready"
        ready = True
        await asyncio.wait_for(started.wait(), timeout=0.5)
    assert cancelled.is_set()
    orch.shutdown.assert_awaited_once()
