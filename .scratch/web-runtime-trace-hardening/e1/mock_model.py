"""Local OpenAI-compatible mock model for E1 storage-chain validation.

Binds 127.0.0.1 only — no external egress, no cost. Every request is appended
to ``MOCK_LOG`` (JSONL) so the call count, payload shape and endpoint can be
audited afterwards, which is what §5 of the validation plan requires
("记录模型、连接来源、用量边界与实际调用数").

Behaviour is driven by env vars:

    MOCK_MODE=text   first and every reply is a plain final answer (terminal
                     "no tool call" turn) — exercises the full lifecycle.
    MOCK_MODE=tool   first reply is a ``bash`` tool call, every reply after a
                     tool result is the plain final answer — exercises the
                     tool-call channel as well.

    MOCK_PORT        default 8899
    MOCK_LOG         default: mock-requests.jsonl beside this file
"""

from __future__ import annotations

import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DEFAULT_TEXT = "E1 mock model: synthetic answer (no external provider was called)."
DEFAULT_TOOL_COMMAND = "echo e1-mock"
#: Optional full override for the issued tool call (E1-WSL batch: create_file
#: into /outputs so artifact/diff/revert cases can run in the real chain).
DEFAULT_TOOL_NAME = (os.environ.get("MOCK_TOOL_NAME") or "bash").strip()
DEFAULT_TOOL_ARGS = os.environ.get("MOCK_TOOL_ARGS") or json.dumps(
    {"command": DEFAULT_TOOL_COMMAND, "description": "e1 mock"}, ensure_ascii=False
)

LOG_PATH = Path(os.environ.get("MOCK_LOG") or Path(__file__).with_name("mock-requests.jsonl"))
MODE = (os.environ.get("MOCK_MODE") or "text").strip().lower()
HOST = (os.environ.get("MOCK_HOST") or "127.0.0.1").strip()
PORT = int(os.environ.get("MOCK_PORT") or "8899")
#: Seconds to stall before answering. A non-zero value keeps the worker busy
#: long enough to attach a live SSE client and issue a stop.
DELAY_S = float(os.environ.get("MOCK_DELAY_S") or 0)

_log_lock = threading.Lock()


def _log(entry: dict) -> None:
    with _log_lock:
        with LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _usage(prompt_tokens: int = 8, completion_tokens: int = 8) -> dict:
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }


def _decide(messages: list[dict]) -> tuple[str, dict]:
    """Return ``("text", {...})`` or ``("tool", {...})`` for this request."""
    saw_tool_result = any(m.get("role") == "tool" for m in messages)
    if MODE == "tool" and not saw_tool_result:
        return "tool", {
            "name": DEFAULT_TOOL_NAME,
            "arguments": DEFAULT_TOOL_ARGS,
        }
    return "text", {"content": DEFAULT_TEXT}


def _non_stream_body(kind: str, payload: dict, model: str) -> dict:
    if kind == "text":
        message = {"role": "assistant", "content": payload["content"]}
        finish = "stop"
    else:
        message = {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_e1_1",
                    "type": "function",
                    "function": {
                        "name": payload["name"],
                        "arguments": payload["arguments"],
                    },
                }
            ],
        }
        finish = "tool_calls"
    return {
        "id": "chatcmpl-e1mock",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "message": message, "finish_reason": finish}],
        "usage": _usage(),
    }


def _stream_events(kind: str, payload: dict, model: str) -> list[dict]:
    """The chunk sequence for one streamed completion (usage chunk last)."""
    base = {"id": "chatcmpl-e1mock", "object": "chat.completion.chunk", "created": int(time.time()),
            "model": model}
    events: list[dict] = [
        {**base, "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]}
    ]
    if kind == "text":
        for piece in [payload["content"][i:i + 24] for i in range(0, len(payload["content"]), 24)]:
            events.append({**base, "choices": [
                {"index": 0, "delta": {"content": piece}, "finish_reason": None}]})
        events.append({**base, "choices": [
            {"index": 0, "delta": {}, "finish_reason": "stop"}]})
    else:
        events.append({**base, "choices": [{"index": 0, "delta": {"tool_calls": [
            {"index": 0, "id": "call_e1_1", "type": "function",
             "function": {"name": payload["name"], "arguments": ""}}]}, "finish_reason": None}]})
        events.append({**base, "choices": [{"index": 0, "delta": {"tool_calls": [
            {"index": 0, "function": {"arguments": payload["arguments"]}}]}, "finish_reason": None}]})
        events.append({**base, "choices": [
            {"index": 0, "delta": {}, "finish_reason": "tool_calls"}]})
    # Terminal usage chunk: empty choices, usage present (include_usage contract).
    events.append({**base, "choices": [], "usage": _usage()})
    return events


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: object) -> None:  # keep stderr quiet
        return

    def do_GET(self) -> None:  # noqa: N802 - stdlib naming
        if self.path.rstrip("/") in ("/healthz", "/v1/models"):
            body = json.dumps({"status": "ok", "mode": MODE}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802 - stdlib naming
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            req = json.loads(raw.decode("utf-8"))
        except Exception:
            req = {}
        messages = req.get("messages") or []
        model = str(req.get("model") or "mock")
        stream = bool(req.get("stream"))
        kind, payload = _decide(messages)
        _log({
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "path": self.path,
            "client": self.client_address[0] if self.client_address else "",
            "model": model,
            "stream": stream,
            "n_messages": len(messages),
            "roles": [m.get("role") for m in messages if isinstance(m, dict)],
            "n_tools": len(req.get("tools") or []),
            "reply_kind": kind,
        })
        if DELAY_S > 0:
            time.sleep(DELAY_S)
        if not stream:
            body = json.dumps(_non_stream_body(kind, payload, model)).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        # Close after the stream: no Content-Length is sent, so a client that
        # waits for EOF (rather than for ``data: [DONE]``) must see the socket
        # close instead of hanging on keep-alive.
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            for event in _stream_events(kind, payload, model):
                self.wfile.write(f"data: {json.dumps(event, ensure_ascii=False)}\n\n".encode())
                self.wfile.flush()
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return


def main() -> int:
    server = ThreadingHTTPServer((HOST, PORT), _Handler)
    _log({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "event": "started",
          "host": HOST, "port": PORT, "mode": MODE})
    print(f"mock model listening on http://{HOST}:{PORT}/v1 (mode={MODE})", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
