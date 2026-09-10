"""留痕接缝（L2，§5.3）：本次调用的真实响应写 run 目录，供硬闸①比对。

- 默认 `NullSink`（什么都不写）；
- 开启 `MARKET_TRACE=on` 时用 `FileSink` 写 **run 目录**（不是数据库，本模块不落库）；
- 留痕失败**绝不拖垮主流程**（写入异常一律吞掉）。
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

TRACE_FILENAME = "market_trace.jsonl"
ENV_TRACE = "MARKET_TRACE"


class NullSink:
    """默认：不留痕（硬闸①降级为方案 B）。"""

    def write(self, record: dict[str, Any]) -> None:
        _ = record


class FileSink:
    """写 JSONL 到 run 目录。写入失败只记不抛。"""

    def __init__(self, directory: str | Path) -> None:
        self._path = Path(directory) / TRACE_FILENAME
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self._path

    def write(self, record: dict[str, Any]) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            line = json.dumps(record, ensure_ascii=False, sort_keys=True)
            with self._lock, self._path.open("a", encoding="utf-8") as handle:
                handle.write(f"{line}\n")
        except Exception:  # 留痕失败不得影响取数主流程
            pass


def trace_enabled(env: dict[str, str] | None = None) -> bool:
    """`MARKET_TRACE` 默认 **on**（留痕开启，硬闸①可证伪来源与时点）。"""
    source = env if env is not None else os.environ
    return source.get(ENV_TRACE, "on").strip().lower() not in {"0", "off", "false", "no"}


def build_sink(run_dir: str | Path | None, *, enabled: bool | None = None) -> NullSink | FileSink:
    """按开关与 run 目录构造 sink；未开启或没有目录时用 `NullSink`。"""
    if enabled is None:
        enabled = trace_enabled()
    if not enabled or run_dir is None:
        return NullSink()
    return FileSink(run_dir)
