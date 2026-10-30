"""Run-scoped monitoring tools; this module has no server or database imports."""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from frontier_agent.core.tool import tool


async def request(operation: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    config = os.environ.get("FRONTIER_WATCH_CHANNEL")
    if not config:
        return {"ok": False, "error": "当前运行没有启用监控工具通道"}
    try:
        connection = json.loads(config)
        async with asyncio.timeout(25):
            reader, writer = await asyncio.open_unix_connection(
                "\0" + connection["address"], limit=262144
            )
            try:
                writer.write(
                    json.dumps(
                        {
                            "token": connection["token"],
                            "operation": operation,
                            "payload": payload or {},
                        },
                        ensure_ascii=False,
                    ).encode()
                    + b"\n"
                )
                await writer.drain()
                return json.loads(await reader.readline())
            finally:
                writer.close()
                await writer.wait_closed()
    except Exception:
        return {"ok": False, "error": "监控通道不可用，不能声称保存成功"}


@tool
async def get_watch_targets() -> str:
    """读取当前会话监控目标、版本、暂停状态、可用名额与自动维护授权。

    生成价格监控前先读取。最多三个目标，长期每15分钟检查，首次达标立即触发。
    continuous 每轮达标重复触发；crossing 仅再次穿越时触发，不重复触发同侧停留。
    工具返回真实服务端状态；不得绕过人工暂停或取消。
    """
    return json.dumps(await request("get"), ensure_ascii=False)


@tool
async def submit_watch_intents(intents: list[dict[str, Any]]) -> str:
    """将分析形成的价格条件保存到本会话，整批原子执行并返回真实回执。

    Args:
        intents: 明确操作列表。每项需要 operation(create/update/cancel)、稳定 intent_key、
            reason、evidence_refs。update/cancel 还需要 rule_id、expected_version。
            create 需要 name 和 spec；spec 含 symbol(如601138.SH)、market(CN)、currency(CNY)、
            quote_basis(last)、direction(up/down/range)、threshold(十进制字符串或low/high对象)、
            task(触发后的综合分析任务)。expires_at可不填以长期监控。
            trigger_mode=continuous 表示每轮达标；crossing 表示采样上穿/下穿/进入区间，
            首次达标立即触发，后续需离开条件再进入。用户要求减少同侧重复时选择 crossing。
            update 的 spec 仅含拟修改字段。未提及目标保持不变，不可虚构资料或恢复人工暂停。
            只有人工发起的本轮明确要求替换时，才取消已暂停的 Agent 目标；自动监控不得取消它。

    Returns:
        applied 表示已保存；unchanged 无需更改；ok=false时明确未保存，读取后修正。
    """
    return json.dumps(await request("submit", {"intents": intents}), ensure_ascii=False)
