"""Dedicated parent-owned capability socket. No platform credentials reach workers."""

from __future__ import annotations

import asyncio
import json
import secrets
import uuid

from server.super_link.contracts import CollaborationError
from server.super_link.inbox import read_from_worker
from server.super_link.runtime import register_from_worker


class DeliveryBridge:
    def __init__(self, run_id: uuid.UUID) -> None:
        self.run_id = run_id
        self.address = f"frontier-super-link-{uuid.uuid4().hex}"
        self.token = secrets.token_urlsafe(32)
        self.server: asyncio.Server | None = None

    async def start(self) -> str:
        self.server = await asyncio.start_unix_server(
            self.handle, path="\0" + self.address, limit=524288
        )
        return json.dumps({"address": self.address, "token": self.token})

    async def close(self) -> None:
        if self.server:
            self.server.close()
            await self.server.wait_closed()

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        result = {"ok": False, "error": "delivery_channel_unavailable"}
        try:
            request = json.loads(await asyncio.wait_for(reader.readline(), timeout=5))
            if not secrets.compare_digest(str(request.get("token", "")), self.token):
                result = {"ok": False, "error": "delivery_access_denied"}
            else:
                operation = request.get("operation", "register")
                if operation not in {"register", "read_inbox"}:
                    raise CollaborationError("unknown_delivery_operation")
                handler = read_from_worker if operation == "read_inbox" else register_from_worker
                result = await asyncio.wait_for(handler(self.run_id, request["payload"]), 20)
        except CollaborationError as exc:
            result = {"ok": False, "error": str(exc)}
        except Exception:
            # Never expose DB exceptions, SQL parameters or secrets.
            pass
        try:
            writer.write(json.dumps(result, ensure_ascii=False).encode() + b"\n")
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()
