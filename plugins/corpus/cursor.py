"""分页游标编解码（A1 清单 / A2 批量取回共用）。

游标是**自描述 + 校验和**的：服务把协议版本、文档、build、请求集合及顺序、视图、
当前位置与块内片段位置一起编码进 token，再附一段内容校验和。续取时解码即完整复
原这些绑定项——不依赖任何服务端状态，因此固定游标 + 相同有效预算重放必然得到同
一页（A2.2「固定游标和相同有效预算重放，应得到同一页内容与 page_id」）。

纪律：

- 校验和不符（被篡改或损坏）、版本不符、类型不符一律 :class:`CursorError` 拒绝，
  不静默降级、不猜一个「看起来能用」的位置；
- 类型区分 ``content``（正文取回）、``inventory``（结构清单）与
  ``semantic_query``（已发布语义记录），禁止混用
  （A1.1「游标类型必须区分 inventory 和 content」）；
- 校验和只证明完整性与一致性，不冒充签名——它能发现损坏/改写，不声称抗伪造。
"""

from __future__ import annotations

import base64
import hashlib
import json
from typing import Any

#: 游标 schema 版本；变更绑定语义时递增，旧游标随即显式失效。
CURSOR_SCHEMA_VERSION = 1

#: 允许的游标类型：正文、结构清单和已发布语义查询分页。
CONTENT = "content"
INVENTORY = "inventory"
SEMANTIC_QUERY = "semantic_query"
CURSOR_TYPES = (CONTENT, INVENTORY, SEMANTIC_QUERY)

_CHECKSUM_CHARS = 16


class CursorError(ValueError):
    """游标不可解析/校验失败/类型或版本不符（fail-closed）。"""


def _canonical(payload: dict[str, Any]) -> str:
    """确定性序列化：键排序、无多余空白——校验和与 token 都基于它。"""
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _checksum(payload: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()[:_CHECKSUM_CHARS]


def encode_cursor(payload: dict[str, Any]) -> str:
    """把绑定项编码为不透明游标字符串（URL 安全、无填充）。

    ``payload`` 应含 ``type`` 与各绑定字段；本函数补 ``v`` 与 ``sum``，不改调用方
    传入的其他键。
    """
    body = {k: v for k, v in payload.items() if k != "sum"}
    body["v"] = CURSOR_SCHEMA_VERSION
    body["sum"] = _checksum(body)
    raw = _canonical(body).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(token: str) -> dict[str, Any]:
    """解码并校验游标；任何异常一律 :class:`CursorError`。"""
    if not isinstance(token, str) or not token.strip():
        raise CursorError("游标必须是非空字符串")
    padded = token + "=" * (-len(token) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise CursorError(f"游标不可解析：{exc}") from exc
    if not isinstance(payload, dict):
        raise CursorError("游标结构非法（顶层非对象）")
    digest = payload.pop("sum", None)
    if digest != _checksum(payload):
        raise CursorError("游标校验和不符（被篡改或损坏）")
    version = payload.get("v")
    if version != CURSOR_SCHEMA_VERSION:
        raise CursorError(f"游标协议版本 {version!r} 不受支持（当前 {CURSOR_SCHEMA_VERSION}）")
    cursor_type = payload.get("type")
    if cursor_type not in CURSOR_TYPES:
        raise CursorError(f"游标类型 {cursor_type!r} 非法（须为 {CURSOR_TYPES}）")
    return payload


__all__ = [
    "CONTENT",
    "CURSOR_SCHEMA_VERSION",
    "CURSOR_TYPES",
    "INVENTORY",
    "SEMANTIC_QUERY",
    "CursorError",
    "decode_cursor",
    "encode_cursor",
]
