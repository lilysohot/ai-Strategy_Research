"""Replay of the streaming empty-arguments recovery path (round-2 verifier).

The round-2 verifier lost a completed verdict batch because its final
``submit_report`` call streamed with blank arguments after the reasoning
watchdog degraded the attempt, and the wall clock was already spent — so
the non-streaming replay never started and every judgment was lost with
the turn. These tests pin each layer of that path through the real
``call_llm`` streaming assembly: healthy chunked arguments, a blank
tool-call shell, a truncated argument payload, a recovery window too
small to start the replay, and a replay that itself loses the arguments.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from frontier_agent.core.llm import LLMResponse, StreamDelta
from frontier_agent.core.messages import user_msg
from frontier_agent.core.runtime.loop._bind import bind_tools
from frontier_agent.core.runtime.loop._call import call_llm
from frontier_agent.core.runtime.loop._tool import _lost_required_tool_arguments

TOOL_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "submit_report",
            "parameters": {
                "type": "object",
                "properties": {"content": {"type": "string"}},
                "required": ["content"],
            },
        },
    }
]


class FakeLLM:
    model = "fake-empty-args"

    def __init__(
        self,
        deltas: list[StreamDelta],
        chat_response: LLMResponse | None = None,
        stream_delay_s: float = 0.0,
    ) -> None:
        self._deltas = deltas
        self._chat_response = chat_response
        self._stream_delay_s = stream_delay_s
        self.chat_messages: list[list[Any]] = []

    async def stream(self, messages: list[Any], **_kwargs: Any):
        if self._stream_delay_s:
            await asyncio.sleep(self._stream_delay_s)
        for delta in self._deltas:
            yield delta

    async def chat(self, messages: list[Any], **_kwargs: Any) -> LLMResponse:
        self.chat_messages.append(list(messages))
        assert self._chat_response is not None, "non-streaming replay must not start"
        return self._chat_response


def _bound(deltas: list[StreamDelta], **kwargs: Any) -> Any:
    # Production detection runs against the bound wrapper whose ``tools``
    # carry the OpenAI schemas; a raw client's ``tools`` attribute would be
    # shadowed by ``_BoundLLM.tools`` (None) and empty-args detection would
    # never fire — bind through the same production entry.
    return bind_tools(FakeLLM(deltas, **kwargs), TOOL_SCHEMA)


def _tool_delta(arguments: str, *, first: bool = True) -> StreamDelta:
    delta: dict[str, Any] = {"index": 0, "arguments": arguments}
    if first:
        delta["id"] = "call-1"
        delta["name"] = "submit_report"
    return StreamDelta(
        tool_call_deltas=[delta],
        finish_reason="tool_calls",
    )


def _recovered_response(arguments: str) -> LLMResponse:
    return LLMResponse(
        tool_calls=[
            {
                "id": "call-2",
                "type": "function",
                "function": {"name": "submit_report", "arguments": arguments},
            }
        ],
        finish_reason="tool_calls",
    )


async def _call(llm: FakeLLM, timeout: int = 60) -> Any:
    async def on_delta(*_args: Any, **_kwargs: Any) -> None:
        return None

    return await call_llm(llm, [user_msg("submit")], timeout, 2, 1, on_delta=on_delta)


def test_lost_required_arguments_covers_every_observed_shape():
    required = {"content"}
    assert _lost_required_tool_arguments(None, required)
    assert _lost_required_tool_arguments("", required)
    assert _lost_required_tool_arguments("  ", required)
    assert _lost_required_tool_arguments({}, required)
    assert _lost_required_tool_arguments('{"content": "par', required)  # truncated
    assert _lost_required_tool_arguments('{"other": 1}', required)  # missing field
    assert not _lost_required_tool_arguments('{"content": "ok"}', required)


async def test_chunked_arguments_need_no_replay():
    llm = _bound(
        [
            _tool_delta('{"cont'),
            _tool_delta('ent": "rep', first=False),
            _tool_delta('ort"}', first=False),
        ]
    )
    response = await _call(llm)

    assert llm.client.chat_messages == [], "a healthy chunked stream must not replay"
    call = response.tool_calls[0]["function"]
    assert call["name"] == "submit_report"
    assert json.loads(call["arguments"]) == {"content": "report"}
    assert "stream_empty_args_fallback" not in response.response_metadata


async def test_blank_arguments_are_replayed_non_streaming():
    llm = _bound([_tool_delta("")], chat_response=_recovered_response('{"content": "ok"}'))
    response = await _call(llm)

    assert len(llm.client.chat_messages) == 1
    repair = llm.client.chat_messages[0][-1]["content"]
    assert "[Tool argument repair]" in repair
    assert "submit_report" in repair
    assert json.loads(response.tool_calls[0]["function"]["arguments"]) == {"content": "ok"}
    assert response.response_metadata["stream_empty_args_fallback"] is True
    assert response.response_metadata["stream_empty_args_recovered"] is True
    assert response.response_metadata["stream_empty_args_still_missing"] == []


async def test_truncated_arguments_are_replayed_non_streaming():
    llm = _bound(
        [_tool_delta('{"content": "par')],
        chat_response=_recovered_response('{"content": "full"}'),
    )
    response = await _call(llm)

    assert len(llm.client.chat_messages) == 1
    repair = llm.client.chat_messages[0][-1]["content"]
    assert '"missing_required_fields": ["content"]' in repair
    assert response.response_metadata["stream_empty_args_recovered"] is True


async def test_recovery_without_time_is_skipped_and_the_stream_is_kept():
    # The stream spends 0.55s of a 1s attempt budget, so the replay window
    # (≈0.45s) is under the 10s floor AND under half the attempt budget:
    # starting it would almost certainly time out. The streamed response —
    # the round-2 verifier's degraded submit_report shell — is kept instead.
    llm = _bound([_tool_delta("")], stream_delay_s=0.55)
    response = await _call(llm, timeout=1)

    assert llm.client.chat_messages == []
    assert response.tool_calls[0]["function"]["name"] == "submit_report"
    assert response.tool_calls[0]["function"]["arguments"] == ""
    assert response.response_metadata["stream_empty_args_fallback"] is False
    assert response.response_metadata["stream_empty_args_recovery_error"] == "TimeoutError"


async def test_replay_that_still_loses_arguments_reports_it():
    llm = _bound([_tool_delta("")], chat_response=_recovered_response("{}"))
    response = await _call(llm)

    assert len(llm.client.chat_messages) == 1
    assert response.response_metadata["stream_empty_args_fallback"] is True
    assert response.response_metadata["stream_empty_args_recovered"] is False
    assert response.response_metadata["stream_empty_args_still_missing"] == ["submit_report"]
