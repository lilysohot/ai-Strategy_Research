"""Per-worker capability channel; only the authenticated parent accesses the DB."""

from __future__ import annotations

import asyncio
import json
import secrets
import uuid
from typing import Any

from server import business_service as biz
from server.watch_agent import call


class WatchBridge:
    def __init__(self, run_id: uuid.UUID) -> None:
        self.run_id = run_id
        self.address = f"frontier-watch-{uuid.uuid4().hex}"
        self.token = secrets.token_urlsafe(32)
        self.server: asyncio.Server | None = None

    async def start(self) -> str:
        # Linux abstract UDS survives the worker's private /tmp mount, without a TCP listener.
        self.server = await asyncio.start_unix_server(
            self.handle, path="\0" + self.address, limit=65536
        )
        return json.dumps({"address": self.address, "token": self.token})

    async def close(self) -> None:
        if self.server:
            self.server.close()
            await self.server.wait_closed()

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        result: dict[str, Any] = {"ok": False, "error": "monitor_channel_unavailable"}
        try:
            request = json.loads(await asyncio.wait_for(reader.readline(), timeout=5))
            if not secrets.compare_digest(str(request.get("token", "")), self.token):
                result = {"ok": False, "error": "monitor_access_denied"}
            else:
                result = await asyncio.wait_for(
                    call(self.run_id, request["operation"], request.get("payload") or {}),
                    timeout=20,
                )
        except biz.BusinessError as exc:
            result = {"ok": False, "error": str(exc)}
        except Exception:
            # Database errors may carry DSNs and SQL parameters; never relay them.
            result = {"ok": False, "error": "监控请求失败，请重新读取状态后重试"}
        try:
            writer.write(json.dumps(result, ensure_ascii=False).encode() + b"\n")
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()
