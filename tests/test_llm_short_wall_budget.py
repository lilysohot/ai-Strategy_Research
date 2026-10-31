"""Short-wall budget policy for the shared LLM call chain.

Run ``eedcd41c`` (2026-10-27) reserved a recovery request that could not
happen and cut a healthy request's reasoning watchdog to 1 s at 95.8 s and
55.8 s remaining; the "reserved" retry was then refused (53.1 s < 65 s floor)
and the run ended with an incomplete response.

The policy pinned here is: reserve a recovery window, allowing 60 s of first
reasoning by spending part of the worst-case TTFT reserve when budget allows;
admit retries only against actual remaining time. Short budgets keep one bounded
last chance inside the absolute deadline. These tests drive the real
``run_agent_loop``/``call_llm`` path with time and the model boundary mocked,
so they apply identically to team members and the single agent.
"""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest

from frontier_agent.core.errors import LLMReasoningRunaway, LLMStreamStalled
from frontier_agent.core.llm import LLMResponse
from frontier_agent.core.loop_types import LoopConfig
from frontier_agent.core.runtime.loop import _call
from frontier_agent.core.runtime.loop._streaming import _stream_llm_response
from frontier_agent.core.runtime.loop.agent_loop import run_agent_loop
from server.profile import PROFILE_NAME, build_profile_overrides
from workflows.stateful_react_agent.nodes.main_agent import _loop_policy
from workflows.stateful_react_agent.profile import load_react_profile

# The Web product's single-agent profile values. ``first_chunk_s=45`` and the
# 20 s wall floor make the retry admission floor 65 s; the reservation needs
# 45 + 65 + 2 backoff + 10 closure = 122 s.
_WEB_FIRST_CHUNK_S = 45.0
_WEB_RETRY_FLOOR_S = 65.0


def _web_agent_config() -> dict:
    return load_react_profile(PROFILE_NAME, overrides=build_profile_overrides())["agent"]


def _decide(available: float | None) -> tuple[float | None, str]:
    cfg = _web_agent_config()
    return _call._first_attempt_reasoning_watchdog(
        available_s=available,
        effective_timeout_s=600.0,
        configured_s=float(cfg["reasoning_only_timeout_s"]),
        first_chunk_s=float(cfg["first_chunk_s"]),
        retry_floor_s=_WEB_RETRY_FLOOR_S,
    )


def _loop_config(cfg: dict, *, max_retries: int = 5) -> LoopConfig:
    return LoopConfig(
        max_turns=1,
        max_llm_retries=max_retries,
        llm_timeout=600,
        first_chunk_timeout=cfg["first_chunk_s"],
        reasoning_only_timeout_s=cfg["reasoning_only_timeout_s"],
        logical_call_timeout_s=cfg["logical_call_timeout_s"],
        loop_policy=_loop_policy(),
    )


def _patch_clock(monkeypatch, now: list[float], remaining: float) -> None:
    monkeypatch.setattr(_call, "time", SimpleNamespace(monotonic=lambda: now[0]))
    monkeypatch.setattr(_call, "wall_deadline_remaining_s", lambda: remaining - now[0])
    monkeypatch.setattr(_call, "_llm_gate", lambda: None)

    async def sleep(delay):
        now[0] += delay

    monkeypatch.setattr(_call.asyncio, "sleep", sleep)


async def _run_single_agent(cfg: dict, *, max_retries: int = 5):
    return await run_agent_loop(
        system_prompt="test",
        user_message="finish",
        llm=SimpleNamespace(model="offline-short-wall"),
        tools=[],
        observers=[],
        config=_loop_config(cfg, max_retries=max_retries),
    )


# ── Decision boundaries ───────────────────────────────────────────────


@pytest.mark.parametrize("remaining", [53.0, 56.0, 96.0])
def test_short_wall_gives_one_last_chance_instead_of_a_one_second_kill(remaining):
    timeout, mode = _decide(remaining)

    assert mode == "last_chance"
    assert timeout == pytest.approx(remaining - 10.0)
    # The old policy produced 1.0 here, which no healthy response can survive.
    assert timeout > 20.0


def test_reservation_is_not_taken_when_it_buys_almost_nothing():
    timeout, mode = _decide(126.0)  # room = 4 s, below the 5 s reserve floor

    assert mode == "last_chance"
    assert timeout == pytest.approx(116.0)


@pytest.mark.parametrize(("remaining", "expected"), [(130.0, 8.0), (200.0, 78.0)])
def test_a_retry_that_fits_keeps_its_reserved_window(remaining, expected):
    timeout, mode = _decide(remaining)

    assert mode == "reserved"
    assert timeout == pytest.approx(expected)


@pytest.mark.parametrize("remaining", [137.0, 164.0, 180.0])
def test_first_reasoning_window_is_relaxed_to_sixty_seconds(remaining):
    timeout, mode = _decide(remaining)

    assert (timeout, mode) == (60.0, "reserved_relaxed")


@pytest.mark.parametrize(("configured", "expected", "mode"), [
    (30.0, 30.0, "configured"),
    (50.0, 42.0, "reserved"),
])
def test_relaxation_requires_room_for_recovery_and_respects_explicit_limits(
    configured, expected, mode,
):
    assert _decide(136.0) == (14.0, "reserved")
    assert _decide(None) == (120.0, "configured")
    timeout, actual_mode = _call._first_attempt_reasoning_watchdog(
        available_s=164.0,
        effective_timeout_s=600.0,
        configured_s=configured,
        first_chunk_s=_WEB_FIRST_CHUNK_S,
        retry_floor_s=_WEB_RETRY_FLOOR_S,
    )
    assert (timeout, actual_mode) == (expected, mode)


def test_no_last_chance_fits_so_only_the_absolute_deadline_bounds_the_attempt():
    timeout, mode = _decide(8.0)

    assert mode == "deadline_only"
    assert timeout is None


# ── End-to-end through the real loop ──────────────────────────────────


@pytest.mark.parametrize("remaining", [53.0, 56.0, 96.0])
async def test_healthy_response_survives_a_short_remaining_wall(monkeypatch, remaining):
    now = [0.0]
    calls: list[dict] = []

    async def stream(llm, messages, timeout, on_delta, **kwargs):
        watchdog = kwargs["reasoning_only_timeout_s"]
        calls.append({**kwargs, "timeout": timeout})
        now[0] += 2.0  # healthy first chunk, well inside first_chunk_s
        if watchdog is None or watchdog < 5.0:
            now[0] += watchdog or 0.0
            raise LLMReasoningRunaway(
                elapsed_s=watchdog or 0.0,
                estimated_tokens=46,
                trigger="time",
                partial_response=LLMResponse(content="", reasoning_content="unfinished"),
            )
        now[0] += 5.0  # a complete answer, still far inside the wall
        return LLMResponse(content="bounded member handoff", finish_reason="stop")

    _patch_clock(monkeypatch, now, remaining)
    monkeypatch.setattr(_call, "_stream_llm_response", stream)

    result = await _run_single_agent(_web_agent_config())

    assert result.final_content == "bounded member handoff"
    assert result.stopped_by == "no_tool"
    assert len(calls) == 1
    assert calls[0]["reasoning_only_timeout_s"] == pytest.approx(remaining - 10.0)
    # Zero-chunk output stays bounded: the first-chunk leash is still passed.
    assert calls[0]["first_chunk_s"] == _WEB_FIRST_CHUNK_S
    # Absolute deadline still clamps the attempt.
    assert calls[0]["timeout"] == pytest.approx(remaining)
    assert now[0] < remaining


@pytest.mark.parametrize(("remaining", "reserved"), [(130.0, 8.0), (164.0, 60.0)])
async def test_short_wall_still_recovers_when_retry_fits(monkeypatch, remaining, reserved):
    now = [0.0]
    watchdogs: list[float | None] = []

    async def stream(llm, messages, timeout, on_delta, **kwargs):
        watchdog = kwargs["reasoning_only_timeout_s"]
        watchdogs.append(watchdog)
        now[0] += 2.0
        if len(watchdogs) == 1:
            now[0] += (watchdog or 0.0) + 5.0
            raise LLMReasoningRunaway(
                elapsed_s=watchdog or 0.0,
                estimated_tokens=6236,
                trigger="time",
                partial_response=LLMResponse(content="", reasoning_content="unfinished"),
            )
        now[0] += 5.0
        return LLMResponse(content="recovered answer", finish_reason="stop")

    cfg = _web_agent_config()
    _patch_clock(monkeypatch, now, remaining)
    monkeypatch.setattr(_call, "_stream_llm_response", stream)

    result = await _run_single_agent(cfg)

    assert result.final_content == "recovered answer"
    assert result.stopped_by == "no_tool"
    assert len(watchdogs) == 2
    assert watchdogs[0] == pytest.approx(reserved)
    # The retry keeps the configured watchdog; only the first attempt reserves.
    assert watchdogs[1] == pytest.approx(float(cfg["reasoning_only_timeout_s"]))
    assert now[0] <= min(remaining, float(cfg["logical_call_timeout_s"]))


async def test_answer_after_fifty_seconds_finishes_without_restarting(monkeypatch):
    now = [0.0]
    calls = []

    async def stream(llm, messages, timeout, on_delta, **kwargs):
        calls.append({**kwargs, "timeout": timeout})
        now[0] += 2.0
        watchdog = kwargs["reasoning_only_timeout_s"]
        if watchdog < 50.0:
            now[0] += watchdog
            raise LLMReasoningRunaway(
                elapsed_s=watchdog,
                estimated_tokens=2500,
                trigger="time",
                partial_response=LLMResponse(content="", reasoning_content="unfinished"),
            )
        now[0] += 50.0
        return LLMResponse(content="finished after reasoning", finish_reason="stop")

    _patch_clock(monkeypatch, now, 164.0)
    monkeypatch.setattr(_call, "_stream_llm_response", stream)
    result = await _run_single_agent(_web_agent_config())

    assert result.final_content == "finished after reasoning"
    assert len(calls) == 1
    assert calls[0]["reasoning_only_timeout_s"] == 60.0
    assert calls[0]["first_chunk_s"] == 45.0
    assert calls[0]["timeout"] == 164.0


async def test_slow_first_chunk_does_not_launch_retry_without_budget(monkeypatch):
    now = [0.0]
    calls = []

    async def stream(llm, messages, timeout, on_delta, **kwargs):
        calls.append(kwargs)
        now[0] += 44.0 + kwargs["reasoning_only_timeout_s"]
        raise LLMReasoningRunaway(
            elapsed_s=kwargs["reasoning_only_timeout_s"],
            estimated_tokens=3000,
            trigger="time",
            partial_response=LLMResponse(content="", reasoning_content="unfinished"),
        )

    _patch_clock(monkeypatch, now, 164.0)
    monkeypatch.setattr(_call, "_stream_llm_response", stream)
    await _run_single_agent(_web_agent_config())

    assert len(calls) == 1
    assert calls[0]["reasoning_only_timeout_s"] == 60.0
    assert now[0] < 164.0


# ── Sustained non-progress stays bounded ──────────────────────────────


async def test_sustained_reasoning_is_still_stopped_by_the_guard():
    class ReasoningOnlyStream:
        async def stream(self, _messages, *, timeout=None):
            del timeout
            for _ in range(10_000):
                await asyncio.sleep(0.01)
                yield SimpleNamespace(
                    content="",
                    reasoning_content="still thinking ",
                    tool_call_deltas=[],
                )

    async def on_delta(*_args, **_kwargs) -> None:
        pass

    started = time.monotonic()
    with pytest.raises(LLMReasoningRunaway) as exc:
        await _stream_llm_response(
            ReasoningOnlyStream(),
            [],
            timeout=5,
            on_delta=on_delta,
            reasoning_only_timeout_s=0.3,
        )

    assert exc.value.trigger == "time"
    assert time.monotonic() - started < 2.0


async def test_zero_chunk_stream_keeps_the_first_chunk_bound():
    class SilentStream:
        async def stream(self, _messages, *, timeout=None):
            del timeout
            await asyncio.sleep(1)
            if False:
                yield None

    async def on_delta(*_args, **_kwargs) -> None:
        pass

    started = time.monotonic()
    with pytest.raises(LLMStreamStalled):
        await _stream_llm_response(
            SilentStream(),
            [],
            timeout=1,
            on_delta=on_delta,
            first_chunk_s=0.02,
        )

    assert time.monotonic() - started < 0.5


# ── Both execution paths receive the same budget ──────────────────────


def test_team_member_loop_resolves_the_same_short_wall_budget():
    from workflows.agent_team.nodes.main_agent import _resolve_team_loop_timeouts
    from workflows.agent_team.profile import load_swarm_profile

    overrides = build_profile_overrides(pipeline_id="agent_team")
    cfg = load_swarm_profile(PROFILE_NAME, overrides=overrides)["agent"]
    timeouts = _resolve_team_loop_timeouts(cfg)

    assert timeouts.first_chunk_timeout_s == _WEB_FIRST_CHUNK_S
    assert timeouts.logical_call_timeout_s == 180.0
    assert timeouts.reasoning_only_timeout_s == float(
        _web_agent_config()["reasoning_only_timeout_s"],
    )
    kwargs = timeouts.loop_config_kwargs()
    assert kwargs["first_chunk_timeout"] == 45
    assert kwargs["logical_call_timeout_s"] == 180
