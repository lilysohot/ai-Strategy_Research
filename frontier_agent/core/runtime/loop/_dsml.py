"""Strict recovery of DeepSeek tool envelopes leaked into visible model output.

Only whole, complete envelopes are executable. Prose examples, partial batches,
duplicate parameters and invalid typed values must never become partial actions.
"""

from __future__ import annotations

import json
import re
from typing import Any

_MARKER = r"(?:｜｜DSML｜｜\s+|｜DSML｜)"
_ENVELOPE = re.compile(
    rf"\s*<{_MARKER}(?P<tag>calls|function_calls)>"
    rf"(?P<body>.*?)</{_MARKER}(?P=tag)>\s*",
    re.DOTALL,
)
_INVOKE = re.compile(
    rf'<{_MARKER}invoke name="(?P<name>[A-Za-z_][\w.-]*)">'
    rf"(?P<body>.*?)</{_MARKER}invoke>",
    re.DOTALL,
)
_PARAMETER = re.compile(
    rf'<{_MARKER}parameter name="(?P<name>[A-Za-z_][\w.-]*)" '
    rf'string="(?P<string>true|false)">(?P<body>.*?)</{_MARKER}parameter>',
    re.DOTALL,
)


def is_dsml_attempt(text: Any) -> bool:
    """Recognize a top-level envelope attempt, never a quoted prose example."""
    return isinstance(text, str) and bool(
        re.match(rf"\s*<{_MARKER}(?:calls|function_calls)>", text)
    )


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-JSON constant: {value}")


def parse_dsml(text: str, tool_names: set[str]) -> list[dict[str, Any]]:
    """Return an atomic, allowlisted batch; tool schemas/authorization still apply."""
    envelope = _ENVELOPE.fullmatch(text)
    if envelope is None:
        return []
    calls: list[dict[str, Any]] = []
    end = 0
    body = envelope["body"]
    for invoke in _INVOKE.finditer(body):
        if body[end : invoke.start()].strip() or invoke["name"] not in tool_names:
            return []
        end = invoke.end()
        args: dict[str, Any] = {}
        param_end = 0
        for param in _PARAMETER.finditer(invoke["body"]):
            if invoke["body"][param_end : param.start()].strip() or param["name"] in args:
                return []
            param_end = param.end()
            value = param["body"]
            if param["string"] == "false":
                try:
                    value = json.loads(value, parse_constant=_reject_constant)
                except (ValueError, RecursionError):
                    return []
            args[param["name"]] = value
        if invoke["body"][param_end:].strip():
            return []
        calls.append({"name": invoke["name"], "args": args, "id": f"dsml_tc_{len(calls)}"})
    return calls if not body[end:].strip() else []
