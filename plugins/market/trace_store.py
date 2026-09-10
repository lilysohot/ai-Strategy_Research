"""留痕读写与 resolver（§5.3 / §5.5）：供离线 `verify` 做硬闸①比对。

**硬闸①对行情的语义**（§5.5）：证明「模型引用的数字出自标注 `as_of` 时点的真实调用」，
而不是「值等于某个冻结快照」——价格是实时时变的。

比对方式：`quote in rendered_text`（与 corpus 同一套 `quote in text` 逻辑）。
因此这里渲染出的文本必须**稳定、确定、字段顺序固定**，且要能容纳 `quote_text`
跨「行情 + 估值」两次调用的事实（故由 service 写聚合留痕，见 `MarketService._trace_quote`）。
"""

from __future__ import annotations

import json
from pathlib import Path

from plugins.market.sink import TRACE_FILENAME

SOURCE_PREFIX = "ths:"


class TraceStore:
    """读取 run 目录里的 `market_trace.jsonl`。"""

    def __init__(self, directory: str | Path) -> None:
        self._path = Path(directory) / TRACE_FILENAME

    @property
    def path(self) -> Path:
        return self._path

    def exists(self) -> bool:
        return self._path.is_file()

    def records(self) -> list[dict]:
        """读取全部留痕；文件缺失或损坏时返回空列表（**不抛**，留痕不可靠不影响取数）。"""
        if not self._path.is_file():
            return []
        records: list[dict] = []
        with self._path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return records

    def quote_texts(self, thscode: str | None = None) -> list[str]:
        """取聚合留痕里的 `quote_text`（可按 thscode 过滤）。"""
        texts: list[str] = []
        for record in self.records():
            if record.get("type") != "market_quote":
                continue
            for text, code in zip(
                record.get("quote_texts", []), record.get("thscodes", []), strict=False
            ):
                if thscode is None or code == thscode:
                    texts.append(text)
        return texts

    def render(self, thscode: str | None = None) -> str:
        """渲染成可比对文本：聚合 `quote_text` + 原始响应的 `key=value` 形式。"""
        blocks: list[str] = []
        for text in self.quote_texts(thscode):
            blocks.append(text)
        for record in self.records():
            if record.get("type") == "market_quote":
                continue
            blocks.append(render_raw_record(record))
        return "\n".join(block for block in blocks if block)


def render_raw_record(record: dict) -> str:
    """把原始响应留痕渲染成 `key=value; ...` 文本（确定性，字段顺序固定）。"""
    raw = record.get("raw") or {}
    data = raw.get("data")
    if not isinstance(data, dict):
        return ""
    item = data.get("item")
    rows = item if isinstance(item, list) else ([item] if isinstance(item, dict) else [])
    as_of = data.get("timestamp")

    lines: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        parts = [f"{key}={row[key]}" for key in sorted(row) if isinstance(row[key], (int, float, str))]
        if isinstance(as_of, int):
            parts.append(f"as_of={as_of}")
        lines.append("; ".join(parts))
    return "\n".join(lines)


def parse_source_ref(source_ref: str) -> tuple[str | None, str | None]:
    """解析 `ths:<thscode>:<request_id>` → (thscode, request_id)。"""
    if not source_ref.startswith(SOURCE_PREFIX):
        return None, None
    parts = source_ref[len(SOURCE_PREFIX) :].split(":")
    thscode = parts[0] if parts else None
    request_id = parts[1] if len(parts) > 1 else None
    return thscode or None, request_id


def resolve_market_source(source_ref: str, trace_dir: str | Path | None) -> str | None:
    """供 `verify` 调用的 resolver：**由调用方注入，verify 不反向 import market**。

    返回可比对文本；留痕缺失或无此目录时返回 `None`（⇒ 硬闸①降级为方案 B）。
    """
    if trace_dir is None:
        return None
    thscode, _request_id = parse_source_ref(source_ref)
    if thscode is None:
        return None
    store = TraceStore(trace_dir)
    if not store.exists():
        return None
    return store.render(thscode) or None
