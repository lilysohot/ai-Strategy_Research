"""Bind report anchors to a bounded output file, never to arbitrary host paths."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

_MAX_REPORT_BYTES = 2 * 1024 * 1024


def read_report(path: str) -> tuple[str, dict[str, str]]:
    """Read one UTF-8 Markdown/text deliverable under this worker's outputs root."""
    root = Path(os.environ.get("FRONTIER_AGENT_OUTPUTS_DIR") or "/outputs").resolve()
    requested = Path(path)
    if requested.is_relative_to("/outputs"):
        requested = root / requested.relative_to("/outputs")
    target = requested.resolve()
    if not target.is_relative_to(root) or target.suffix.lower() not in {".md", ".txt"}:
        raise ValueError("report_path 必须是本运行 /outputs 下的 Markdown 或文本报告")
    if not target.is_file() or target.stat().st_size > _MAX_REPORT_BYTES:
        raise ValueError("报告不存在或超过 2 MiB，请先写入报告再提交清单")
    with target.open("rb") as stream:
        raw = stream.read(_MAX_REPORT_BYTES + 1)
    if len(raw) > _MAX_REPORT_BYTES:
        raise ValueError("报告超过 2 MiB")
    text = raw.decode("utf-8")
    return text, {
        "path": "/outputs/" + target.relative_to(root).as_posix(),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def bound_report(binding: Any) -> tuple[str, list[dict[str, str]]]:
    """Re-read and verify the exact submitted bytes; edits require resubmission."""
    try:
        if not isinstance(binding, dict) or not isinstance(binding.get("path"), str):
            raise ValueError("报告绑定格式无效")
        text, current = read_report(binding["path"])
        if current != binding:
            raise ValueError("报告已修改，请按最新文件重新提交完整证据清单")
        return text, []
    except (OSError, ValueError) as exc:
        return "", [{"code": "report_changed_or_unavailable", "message": str(exc)}]
