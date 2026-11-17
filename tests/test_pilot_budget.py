"""Pre-send pilot budget: the caps are enforced at the send boundary.

Three field failures are encoded here, because the original self-check used
non-streaming stubs and passed while all of them were live:

* the transport streams, so ``usage`` is on the terminal chunk, not on the awaited
  value — settling at the ``await`` charged nothing back;
* callers abandon streams (``_timed_chunks`` breaks out of ``async for``), so a
  hand-rolled iterator was never closed and its reservation never released;
* an unsettleable request was refunded, which let 4 requests with 32,768 output
  each pass a 100,000 cap while the ledger read 0 / 0.

The invariant under test: every request settles exactly once, the in-flight window
returns to zero when it ends, and unknown usage stops the arm instead of shrinking
it.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import pytest

from frontier_agent.infra import pilot_budget


def _arm(monkeypatch: pytest.MonkeyPatch, **limits: Any) -> pilot_budget.PilotBudget:
    spec = {"requests": 40, "prompt_tokens": 1_500_000, "completion_tokens": 100_000, "wall_s": 1800}
    spec.update(limits)
    monkeypatch.setenv(pilot_budget.ENV_FLAG, json.dumps(spec))
    monkeypatch.setattr(pilot_budget, "_BUDGET", None)
    monkeypatch.setattr(pilot_budget, "_ABORT_CONTEXT", {})
    budget = pilot_budget.from_env()
    assert budget is not None
    return budget


def _client(create: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    pilot_budget.install(client)
    return client


def _usage(prompt: int, completion: int) -> Any:
    return SimpleNamespace(prompt_tokens=prompt, completion_tokens=completion)


async def test_stream_usage_settles_on_terminal_chunk(monkeypatch: pytest.MonkeyPatch) -> None:
    budget = _arm(monkeypatch)

    async def create(*args: Any, **kwargs: Any) -> Any:
        async def chunks() -> Any:
            yield SimpleNamespace(usage=None, choices=[])
            yield SimpleNamespace(usage=_usage(100, 20), choices=[])

        return chunks()

    client = _client(create, monkeypatch)
    stream = await client.chat.completions.create(
        messages=[{"role": "user", "content": "x" * 400}], max_completion_tokens=64, stream=True
    )
    assert [chunk async for chunk in stream]
    assert budget.prompt_settled == 100
    assert budget.completion_settled == 20
    assert budget.prompt_reserved == 0
    assert budget.completion_reserved == 0
    assert budget.unknown_usage_requests == 0


async def test_abandoned_stream_releases_its_reservation(monkeypatch: pytest.MonkeyPatch) -> None:
    budget = _arm(monkeypatch)

    async def create(*args: Any, **kwargs: Any) -> Any:
        async def chunks() -> Any:
            for _ in range(5):
                yield SimpleNamespace(usage=None, choices=[])

        return chunks()

    client = _client(create, monkeypatch)
    stream = await client.chat.completions.create(
        messages=[{"role": "user", "content": "y" * 400}], max_completion_tokens=64, stream=True
    )
    async for _chunk in stream:
        break
    await stream.aclose()
    assert budget.prompt_reserved == 0
    assert budget.completion_reserved == 0


def test_stream_dropped_without_aclose_settles_on_finalize(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real abandonment path: nobody calls ``aclose``, the loop finalises it."""
    budget = _arm(monkeypatch)

    async def create(*args: Any, **kwargs: Any) -> Any:
        async def chunks() -> Any:
            for _ in range(5):
                yield SimpleNamespace(usage=None, choices=[])

        return chunks()

    client = _client(create, monkeypatch)

    async def _walk_away() -> None:
        stream = await client.chat.completions.create(
            messages=[{"role": "user", "content": "w" * 400}], max_completion_tokens=64, stream=True
        )
        async for _chunk in stream:
            break
        del stream  # dropped, never closed

    # A fresh loop per call: closing the loop is what finalises the abandoned
    # async generator, which is the only reason the reservation comes back.
    import asyncio

    asyncio.run(_walk_away())
    assert budget.prompt_reserved == 0
    assert budget.completion_reserved == 0


async def test_each_request_settles_exactly_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """Normal end, explicit close and mid-stream error must not double-charge."""
    budget = _arm(monkeypatch)
    calls = 0

    async def create(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        index = calls

        async def chunks() -> Any:
            yield SimpleNamespace(usage=None, choices=[])
            if index == 3:
                raise RuntimeError("stream broke")
            yield SimpleNamespace(usage=_usage(100, 10), choices=[])

        return chunks()

    client = _client(create, monkeypatch)

    # 1: consumed to exhaustion.
    stream = await client.chat.completions.create(
        messages=[{"role": "user", "content": "a"}], max_completion_tokens=8, stream=True
    )
    async for _chunk in stream:
        pass
    # 2: closed early, after the usage chunk had already arrived.
    stream = await client.chat.completions.create(
        messages=[{"role": "user", "content": "b"}], max_completion_tokens=8, stream=True
    )
    async for _chunk in stream:
        pass
    await stream.aclose()
    # 3: dies mid-stream.
    stream = await client.chat.completions.create(
        messages=[{"role": "user", "content": "c"}], max_completion_tokens=8, stream=True
    )
    with pytest.raises(RuntimeError):
        async for _chunk in stream:
            pass

    assert budget.requests_sent == 3
    assert budget.prompt_settled == 200  # two known requests, never double-charged
    assert budget.completion_settled == 20
    assert budget.prompt_reserved == 0
    assert budget.completion_reserved == 0
    # The third died before its usage chunk, so its cost is unknown — not zero, and
    # not refunded: the arm stops and the total is published as a lower bound.
    assert budget.requests_failed == 1
    assert budget.unknown_usage_requests == 1
    assert budget.stopped_reason == "usage_unavailable"


async def test_cap_counts_in_flight_request_and_blocks_before_send(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    budget = _arm(monkeypatch, requests=2)
    sent: list[int] = []

    async def create(*args: Any, **kwargs: Any) -> Any:
        sent.append(1)
        return SimpleNamespace(usage=_usage(10, 1), choices=[])

    client = _client(create, monkeypatch)
    for _ in range(2):
        await client.chat.completions.create(
            messages=[{"role": "user", "content": "z"}], max_completion_tokens=8
        )
    with pytest.raises(pilot_budget.PilotBudgetExhausted) as excinfo:
        await client.chat.completions.create(
            messages=[{"role": "user", "content": "z"}], max_completion_tokens=8
        )
    assert str(excinfo.value) == "requests"
    assert len(sent) == 2
    assert budget.requests_sent == 2


async def test_completion_cap_uses_settled_not_reservations(monkeypatch: pytest.MonkeyPatch) -> None:
    """A settled request must not keep charging its ``max_completion_tokens`` bound."""
    budget = _arm(monkeypatch, completion_tokens=100, requests=40)

    async def create(*args: Any, **kwargs: Any) -> Any:
        return SimpleNamespace(usage=_usage(10, 10), choices=[])

    client = _client(create, monkeypatch)
    for _ in range(5):
        await client.chat.completions.create(
            messages=[{"role": "user", "content": "q"}], max_completion_tokens=30
        )
    assert budget.completion_settled == 50
    assert budget.completion_reserved == 0
    assert not budget.stopped_reason


async def test_first_unknown_usage_stops_the_arm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Four 32,768-output requests may not pass a 100,000 cap as "unknown, 0 spent"."""
    budget = _arm(monkeypatch, requests=40)
    sent: list[int] = []

    async def create(*args: Any, **kwargs: Any) -> Any:
        sent.append(1)
        return SimpleNamespace(usage=None, choices=[])

    client = _client(create, monkeypatch)
    await client.chat.completions.create(
        messages=[{"role": "user", "content": "u"}], max_completion_tokens=32_768
    )
    assert budget.unknown_usage_requests == 1
    assert budget.stopped_reason == "usage_unavailable"
    assert budget.prompt_settled == 0  # unknown is never credited as consumption
    assert budget.completion_reserved == 0  # nor is it returned to the pool

    with pytest.raises(pilot_budget.PilotBudgetExhausted) as excinfo:
        await client.chat.completions.create(
            messages=[{"role": "user", "content": "u"}], max_completion_tokens=32_768
        )
    assert str(excinfo.value) == "usage_unavailable"
    assert len(sent) == 1  # the second request never left


async def test_failed_request_is_counted_and_ends_the_arm(monkeypatch: pytest.MonkeyPatch) -> None:
    budget = _arm(monkeypatch)

    async def create(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("transport down")

    client = _client(create, monkeypatch)
    with pytest.raises(RuntimeError):
        await client.chat.completions.create(
            messages=[{"role": "user", "content": "f"}], max_completion_tokens=8
        )
    assert budget.requests_failed == 1
    assert budget.unknown_usage_requests == 1
    assert budget.prompt_reserved == 0
    assert budget.completion_reserved == 0
    assert budget.stopped_reason == "usage_unavailable"


def test_estimator_covers_the_whole_request(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tool schemas are part of the prompt; the old estimator ignored them."""
    monkeypatch.delenv(pilot_budget.ESTIMATE_MODE_ENV, raising=False)
    messages = [{"role": "user", "content": "解读这篇报告" * 200}]
    tools = [
        {
            "type": "function",
            "function": {
                "name": "corpus_fetch",
                "description": "按引用取回原文" * 40,
                "parameters": {"type": "object", "properties": {"ref": {"type": "string"}}},
            },
        }
    ]
    without_tools = pilot_budget.estimate_prompt_tokens({"messages": messages})
    with_tools = pilot_budget.estimate_prompt_tokens({"messages": messages, "tools": tools})
    assert with_tools > without_tools


def test_estimator_modes_are_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    messages = [{"role": "user", "content": "表格里的研发费用是多少"}]
    monkeypatch.delenv(pilot_budget.ESTIMATE_MODE_ENV, raising=False)
    tokenizer_estimate = pilot_budget.estimate_prompt_tokens({"messages": messages})
    assert pilot_budget.estimate_mode() == "tokenizer"

    monkeypatch.setenv(pilot_budget.ESTIMATE_MODE_ENV, "bytes")
    bytes_estimate = pilot_budget.estimate_prompt_tokens({"messages": messages})
    assert pilot_budget.estimate_mode() == "bytes"
    # bytes mode is the more conservative of the two, so it must not be smaller.
    # Neither mode is a proven bound on the provider's token count; the point here is
    # only that switching modes cannot silently shrink the reservation.
    assert bytes_estimate >= tokenizer_estimate


async def test_caller_cancel_records_its_source_and_still_stops_the_arm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A local cancel loses the terminal usage chunk: still unknown, still a stop.

    Field evidence: turn 8 of ``2774ab11…`` was cancelled by the reasoning-only
    watchdog after 60 s, so the terminal billing chunk never arrived. Recording the
    source must not be mistaken for recovering the cost.
    """
    budget = _arm(monkeypatch)
    sent: list[int] = []

    async def create(*args: Any, **kwargs: Any) -> Any:
        sent.append(1)

        async def chunks() -> Any:
            yield SimpleNamespace(usage=None, choices=[])
            raise asyncio.CancelledError()

        return chunks()

    client = _client(create, monkeypatch)
    stream = await client.chat.completions.create(
        messages=[{"role": "user", "content": "c"}], max_completion_tokens=64, stream=True
    )
    with pytest.raises(asyncio.CancelledError):
        async for _chunk in stream:
            pass

    assert budget.unknown_usage_requests == 1
    assert budget.unknown_usage_aborted_by == pilot_budget.ABORTED_BY_CALLER_CANCEL
    assert budget.stopped_reason == "usage_unavailable"
    assert budget.prompt_settled == 0  # a known cancel reason is not a known cost
    assert budget.prompt_reserved == 0

    with pytest.raises(pilot_budget.PilotBudgetExhausted) as excinfo:
        await client.chat.completions.create(
            messages=[{"role": "user", "content": "c"}], max_completion_tokens=64, stream=True
        )
    assert str(excinfo.value) == "usage_unavailable"
    assert len(sent) == 1  # admission is unchanged by the annotation


async def test_watchdog_reason_is_recorded_alongside_the_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    budget = _arm(monkeypatch)

    async def create(*args: Any, **kwargs: Any) -> Any:
        async def chunks() -> Any:
            yield SimpleNamespace(usage=None, choices=[])
            pilot_budget.note_abort_context("reasoning_only_watchdog:time")
            raise asyncio.CancelledError()

        return chunks()

    client = _client(create, monkeypatch)
    stream = await client.chat.completions.create(
        messages=[{"role": "user", "content": "w"}], max_completion_tokens=64, stream=True
    )
    with pytest.raises(asyncio.CancelledError):
        async for _chunk in stream:
            pass

    # Both facts hold at once: the cause is known, the cost is not.
    assert budget.unknown_usage_aborted_by == pilot_budget.ABORTED_BY_CALLER_CANCEL
    assert budget.unknown_usage_watchdog == "reasoning_only_watchdog:time"
    assert budget.stopped_reason == "usage_unavailable"
    assert budget.unknown_usage_requests == 1


async def test_caller_close_is_labelled_separately(monkeypatch: pytest.MonkeyPatch) -> None:
    budget = _arm(monkeypatch)

    async def create(*args: Any, **kwargs: Any) -> Any:
        async def chunks() -> Any:
            for _ in range(3):
                yield SimpleNamespace(usage=None, choices=[])

        return chunks()

    client = _client(create, monkeypatch)
    stream = await client.chat.completions.create(
        messages=[{"role": "user", "content": "x"}], max_completion_tokens=64, stream=True
    )
    async for _chunk in stream:
        break
    await stream.aclose()

    assert budget.unknown_usage_aborted_by == pilot_budget.ABORTED_BY_CALLER_CLOSE
    assert budget.stopped_reason == "usage_unavailable"
    assert budget.prompt_reserved == 0


async def test_known_usage_records_no_abort_source(monkeypatch: pytest.MonkeyPatch) -> None:
    budget = _arm(monkeypatch)

    async def create(*args: Any, **kwargs: Any) -> Any:
        async def chunks() -> Any:
            pilot_budget.note_abort_context("reasoning_only_watchdog:time")
            yield SimpleNamespace(usage=_usage(10, 2), choices=[])

        return chunks()

    client = _client(create, monkeypatch)
    stream = await client.chat.completions.create(
        messages=[{"role": "user", "content": "k"}], max_completion_tokens=64, stream=True
    )
    assert [chunk async for chunk in stream]

    assert budget.prompt_settled == 10
    assert budget.unknown_usage_aborted_by == ""
    assert budget.unknown_usage_watchdog == ""
    assert budget.stopped_reason == ""


async def test_estimated_placeholder_policy_keeps_the_arm_alive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Declared policy ``estimate``: the pre-send reservation stays charged, arm continues.

    The cost of the cancelled call is still an estimate — that is the trade the policy
    registers deliberately, and why the placeholder never lands in ``*_settled``.
    """
    budget = _arm(monkeypatch, unknown_usage="estimate")
    calls = 0

    async def create(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        index = calls

        async def chunks() -> Any:
            if index == 1:
                yield SimpleNamespace(usage=None, choices=[])
                # Local caller-side cancellation: the one abort this policy covers.
                raise asyncio.CancelledError()
            yield SimpleNamespace(usage=_usage(100, 10), choices=[])

        return chunks()

    client = _client(create, monkeypatch)
    first = await client.chat.completions.create(
        messages=[{"role": "user", "content": "a" * 400}], max_completion_tokens=64, stream=True
    )
    with pytest.raises(asyncio.CancelledError):
        async for _chunk in first:
            pass

    placeholder = budget.prompt_placeholder
    completion_placeholder = budget.completion_placeholder
    assert budget.unknown_usage_requests == 1
    assert budget.prompt_placeholder > 0
    assert completion_placeholder == 64  # the declared per-request output cap, not a measurement
    assert budget.prompt_settled == 0
    assert budget.stopped_reason == ""  # admission is not closed by the cancel

    second = await client.chat.completions.create(
        messages=[{"role": "user", "content": "b" * 400}], max_completion_tokens=64, stream=True
    )
    assert [chunk async for chunk in second]
    assert budget.prompt_settled == 100
    assert budget.completion_settled == 10
    # The later request's usage does not settle the earlier one.
    assert budget.prompt_placeholder == placeholder
    assert budget.completion_placeholder == completion_placeholder
    assert budget.requests_sent == 2


async def test_placeholder_is_never_merged_into_settled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    budget = _arm(monkeypatch, unknown_usage="estimate")

    async def create(*args: Any, **kwargs: Any) -> Any:
        async def chunks() -> Any:
            for _ in range(3):
                yield SimpleNamespace(usage=None, choices=[])

        return chunks()

    client = _client(create, monkeypatch)
    stream = await client.chat.completions.create(
        messages=[{"role": "user", "content": "q" * 400}], max_completion_tokens=64, stream=True
    )
    async for _chunk in stream:
        break
    await stream.aclose()  # local caller close: eligible for the placeholder

    assert budget.prompt_settled == 0
    assert budget.completion_settled == 0
    assert budget.prompt_placeholder > 0
    assert budget.prompt_reserved == 0  # the reservation moved, it was not handed back


async def test_placeholders_still_count_against_the_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    """The placeholder is not free: it consumes the same cumulative cap.

    Request count, wall clock and the per-request output cap stay strict; only the
    cumulative token figure for a cancelled call becomes an estimate.
    """
    messages = [{"role": "user", "content": "z" * 400}]
    per_request = pilot_budget.estimate_prompt_tokens({"messages": messages})
    budget = _arm(monkeypatch, unknown_usage="estimate", prompt_tokens=per_request * 2)

    async def create(*args: Any, **kwargs: Any) -> Any:
        async def chunks() -> Any:
            yield SimpleNamespace(usage=None, choices=[])
            raise asyncio.CancelledError()

        return chunks()

    client = _client(create, monkeypatch)
    for _ in range(20):
        try:
            stream = await client.chat.completions.create(
                messages=messages,
                max_completion_tokens=64,
                stream=True,
            )
        except pilot_budget.PilotBudgetExhausted as exc:
            assert str(exc) == "prompt_tokens"
            break
        with pytest.raises(asyncio.CancelledError):
            async for _chunk in stream:
                pass
    else:  # pragma: no cover - the placeholders must eventually hit the cap
        pytest.fail("placeholders never exhausted the prompt cap")

    assert budget.stopped_reason == "prompt_tokens"
    assert budget.prompt_placeholder == per_request * 2  # two placeholders filled the cap
    assert budget.requests_sent == 2
    assert budget.prompt_settled == 0


async def test_strict_policy_remains_the_default(monkeypatch: pytest.MonkeyPatch) -> None:
    budget = _arm(monkeypatch)
    assert budget.unknown_usage_policy == pilot_budget.UNKNOWN_USAGE_STOP
    assert budget.prompt_placeholder == 0


async def test_estimate_policy_covers_only_local_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The approved scope is narrow: other unknowns still stop the arm.

    Only ``caller_cancel`` / ``caller_close`` get a placeholder. A stream that ends
    on its own without usage, a transport failure and an abort of unknown provenance
    keep the strict behaviour even when the arm declared ``estimate``.
    """
    assert frozenset(
        {pilot_budget.ABORTED_BY_CALLER_CANCEL, pilot_budget.ABORTED_BY_CALLER_CLOSE}
    ) == pilot_budget.PLACEHOLDER_ELIGIBLE_ABORTS

    # 1: the stream ended by itself and no usage chunk ever arrived.
    budget = _arm(monkeypatch, unknown_usage="estimate")

    async def ends_without_usage(*args: Any, **kwargs: Any) -> Any:
        async def chunks() -> Any:
            yield SimpleNamespace(usage=None, choices=[])

        return chunks()

    client = _client(ends_without_usage, monkeypatch)
    stream = await client.chat.completions.create(
        messages=[{"role": "user", "content": "e" * 400}], max_completion_tokens=64, stream=True
    )
    assert [chunk async for chunk in stream]
    assert budget.unknown_usage_aborted_by == pilot_budget.ABORTED_BY_STREAM_END
    assert budget.prompt_placeholder == 0
    assert budget.stopped_reason == "usage_unavailable"

    # 2: the transport failed mid-stream.
    budget = _arm(monkeypatch, unknown_usage="estimate")

    async def transport_failure(*args: Any, **kwargs: Any) -> Any:
        async def chunks() -> Any:
            yield SimpleNamespace(usage=None, choices=[])
            raise ConnectionResetError("gateway dropped the stream")

        return chunks()

    client = _client(transport_failure, monkeypatch)
    stream = await client.chat.completions.create(
        messages=[{"role": "user", "content": "t" * 400}], max_completion_tokens=64, stream=True
    )
    with pytest.raises(ConnectionResetError):
        async for _chunk in stream:
            pass
    assert budget.unknown_usage_aborted_by == "ConnectionResetError"
    assert budget.prompt_placeholder == 0
    assert budget.stopped_reason == "usage_unavailable"


def test_estimate_policy_does_not_cover_unrecorded_aborts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An abort with no known provenance stays strict: no placeholder, arm stops."""
    budget = _arm(monkeypatch, unknown_usage="estimate")
    ticket = budget.reserve(1000, 64, path="no-provenance", stream=True)
    budget.settle(ticket, None)  # aborted_by == "" → unrecorded

    assert budget.unknown_usage_aborted_by == pilot_budget.ABORTED_BY_UNRECORDED
    assert budget.prompt_placeholder == 0
    assert budget.completion_placeholder == 0
    assert budget.stopped_reason == "usage_unavailable"
    assert budget.prompt_reserved == 0


def test_dropped_stream_counts_as_a_local_cancel(monkeypatch: pytest.MonkeyPatch) -> None:
    """A stream dropped without ``aclose`` surfaces as a local cancel, not a failure.

    At loop shutdown the pending read is cancelled, which reaches the transport as
    ``CancelledError`` — the same class as a watchdog or caller cancel. It is an
    abandonment, not a provider fault, so the declared policy covers it.
    """
    budget = _arm(monkeypatch, unknown_usage="estimate")

    async def create(*args: Any, **kwargs: Any) -> Any:
        async def chunks() -> Any:
            for _ in range(5):
                yield SimpleNamespace(usage=None, choices=[])

        return chunks()

    client = _client(create, monkeypatch)

    async def _walk_away() -> None:
        stream = await client.chat.completions.create(
            messages=[{"role": "user", "content": "d" * 400}],
            max_completion_tokens=64,
            stream=True,
        )
        async for _chunk in stream:
            break
        del stream  # dropped, never closed

    asyncio.run(_walk_away())
    assert budget.unknown_usage_aborted_by == pilot_budget.ABORTED_BY_CALLER_CANCEL
    assert budget.prompt_placeholder > 0
    assert budget.stopped_reason == ""
    assert budget.prompt_reserved == 0


async def test_raw_response_wrapper_settles_through_parse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``chat()`` returns a raw wrapper: no ``.usage``, only ``.parse()``.

    Field evidence: the streaming acceptance run stopped on its first turn with
    ``usage_unavailable`` because the guard settled on a ``LegacyAPIResponse`` and
    found no usage, while the request itself was fully billed.
    """
    budget = _arm(monkeypatch)

    class _Raw:
        def parse(self) -> Any:
            return SimpleNamespace(usage=_usage(36, 25))

    async def create(*args: Any, **kwargs: Any) -> Any:
        return _Raw()

    client = _client(create, monkeypatch)
    await client.chat.completions.create(
        messages=[{"role": "user", "content": "收到"}], max_completion_tokens=8
    )
    assert budget.prompt_settled == 36
    assert budget.completion_settled == 25
    assert budget.unknown_usage_requests == 0
    assert budget.stopped_reason == ""
