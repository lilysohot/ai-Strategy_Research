# -*- coding: utf-8 -*-
"""Craft trajectory JSONL fixtures for the F05/F06 browser validation.

Modes:
  full     -- every F05 display state in one complete trace (terminal end line)
  partial  -- same records but WITHOUT the terminal end line (F06 partial)
"""
import json
import sys
import time
from pathlib import Path

RUNS_ROOT = Path(r"C:\Users\Administrator\AppData\Local\Temp\f05e2e\runs")
RELPATH = "run/agent/trajectories/react_agent.jsonl"


def build(mode: str) -> list[dict]:
    ts = time.time()

    def rec(**kw):
        kw.setdefault("ts", ts)
        return kw

    usage = {"prompt_tokens": 128, "completion_tokens": 20, "total_tokens": 148}

    long_result = "OK" * 150  # exactly 300 chars of clean prefix
    long_result += "【关键错误】磁盘已满，无法写入 checkpoint（本信息位于第 300 字符之后）"
    long_result += "-" * 2000

    emoji_result = "A" * 299 + "😀" + "B" * 50  # surrogate pair straddles char 300

    records = [
        rec(t="start", task_id="f05-e2e", role_id="react", max_turns=60,
            model_name="mock-frontier-model",
            tool_names=["bash", "read_file", "write_file"]),
        rec(t="llm", turn=1, content="我先读取文件再总结。",
            thinking="用户要验证推理展示。第一步应读取 notes.txt，检查内容后给出结论。",
            tool_calls=[{"id": "call_a1", "name": "read_file",
                         "args": {"path": "notes.txt"}}],
            usage=usage),
        rec(t="result", turn=1, name="read_file", tool_call_id="call_a1",
            result="notes 内容很短：一切正常。", error=False, ms=12),
        rec(t="llm", turn=2, content="运行诊断命令检查写入能力。",
            tool_calls=[{"id": "call_b2", "name": "bash",
                         "args": {"command": "diag --write-probe"}}],
            usage=usage),
        rec(t="result", turn=2, name="bash", tool_call_id="call_b2",
            result=long_result, error=True, ms=45),
        rec(t="result", turn=2, name="bash", tool_call_id="call_emoji",
            result=emoji_result, error=False, ms=3),
        rec(t="llm", turn=3, content="第三轮：空推理。",
            thinking="", tool_calls=[], usage=usage),
        rec(t="llm", turn=4, content="第四轮：仅有加密推理块。",
            thinking_blocks=[{"type": "redacted_thinking", "data": "enc-block-xyz"}],
            tool_calls=[], usage=usage),
        rec(t="llm", turn=5, content="第五轮：完全没有推理字段。",
            tool_calls=[], usage=usage),
    ]
    if mode == "full":
        records.append(rec(t="end", turns=5, tool_calls=2, stopped_by="end"))
    return records


def main() -> int:
    run_id, mode = sys.argv[1], sys.argv[2]
    path = RUNS_ROOT / run_id / RELPATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for record in build(mode):
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"wrote {mode} trace -> {path} ({len(build(mode))} records)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
