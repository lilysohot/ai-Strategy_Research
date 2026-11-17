"""Pre-send request budget for a controlled pilot run.

Post-hoc aggregation is not a limit: a bucket that is read after the fact cannot
stop the forty-first request. This module reserves *before* the request leaves the
process and settles *after* — so the cap is enforced at the send boundary, and an
in-flight request already counts against it.

Scope is deliberately narrow: it is installed only when ``FRONTIER_PILOT_BUDGET``
is set (a JSON object), so production code keeps its current behaviour and no
other accounting system is refactored. Every path that builds an
``infra.openai_client.OpenAIClient`` — main loop, members, extraction, summary,
resample — goes through ``install`` on that client's own transport.

A reservation bounds one in-flight request; it is never a charge. It is released
when that request terminates — succeeded, failed, or abandoned mid-stream — because
a bound that outlives its request stops being a bound and silently becomes spend
the arm never made. Caps are therefore checked as ``settled + in-flight + next``.

Three kinds of consumption are kept apart, because conflating them is what makes a
ledger lie:

* **known** — usage was reported; it is charged.
* **in flight** — the request has not ended; the estimate bounds it.
* **unknown** — the request ended and its usage cannot be established. It is not
  charged as measured (that would invent tokens) and it is *not* returned to the
  pool (that would spend it twice). Under the default ``stop`` policy the first such
  request ends the arm with ``usage_unavailable``: past that point the ledger can no
  longer bound anything, so the only safe move is to stop asking for more.

Unknown usage also records *why* the request ended (``aborted_by`` / ``watchdog``)
so a caller-side cancel is not later misread as a provider fault. That annotation is
diagnostic only: a known cancel reason does not make the consumed tokens known, so
it never reopens admission by itself.

Two policies exist for what happens next, and the arm declares which one it runs
under (``unknown_usage`` in the arm spec; default ``stop``):

* ``stop`` — the strict policy above. Incompatible with workflows that cancel and
  resume by design (watchdogs, resampling): the first such cancellation ends the arm.
* ``estimate`` — the *estimated-placeholder* policy, and **only for a local,
  caller-side cancellation** (``caller_cancel`` / ``caller_close``) of a stream
  whose usage lived on a terminal chunk that was never read. The reservation already
  registered before sending stays charged as a **placeholder**: it is counted
  against the caps, published in its own fields, never merged into ``*_settled``,
  and never adjusted by a later request's usage. A stream that ended without usage,
  a transport or provider failure, and an abort of unknown provenance remain outside
  this policy and stop the arm. Request count, wall clock and the per-request output
  cap stay strict; the cancelled request's token cost is an estimate, so a
  net-benefit conclusion must carry that uncertainty rather than a bound.

An arm with unknown usage is stopped, not shrunk: the fix is a persisted counter,
not a tolerance parameter.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

ENV_FLAG = "FRONTIER_PILOT_BUDGET"

#: ``aborted_by`` values the guard itself derives. Anything else is the exception
#: class name that ended the stream, recorded verbatim.
ABORTED_BY_CALLER_CANCEL = "caller_cancel"
ABORTED_BY_CALLER_CLOSE = "caller_close"
ABORTED_BY_STREAM_END = "stream_ended_without_usage"
ABORTED_BY_UNRECORDED = "unrecorded"

#: What an unsettleable request does to the arm.
UNKNOWN_USAGE_STOP = "stop"
UNKNOWN_USAGE_ESTIMATE = "estimate"
_UNKNOWN_USAGE_POLICIES = frozenset({UNKNOWN_USAGE_STOP, UNKNOWN_USAGE_ESTIMATE})

#: The only aborts ``estimate`` may absorb: a local, caller-side cancellation of a
#: stream whose usage only existed on a terminal chunk we never read. A stream that
#: *ended* without usage, a transport/provider failure, or an abort of unknown
#: provenance is outside the approved scope and stops the arm exactly as before.
PLACEHOLDER_ELIGIBLE_ABORTS = frozenset({
    ABORTED_BY_CALLER_CANCEL,
    ABORTED_BY_CALLER_CLOSE,
})

#: Why the *caller* is about to abandon the stream, noted by the streaming layer
#: while the reason is still known (a watchdog, a semantic deadline). Keyed by task
#: so one request's note can never label another request's settlement.
_ABORT_CONTEXT: dict[int, tuple[asyncio.Task[Any], str]] = {}


def _current_task() -> asyncio.Task[Any] | None:
    try:
        return asyncio.current_task()
    except RuntimeError:  # no running loop (async-generator finalisation)
        return None


def note_abort_context(reason: str) -> None:
    """Record why the caller is cancelling the stream it is reading right now.

    The ledger cannot see *who* cancelled: ``asyncio.timeout``, a watchdog and an
    explicit ``aclose`` all reach the transport as the same cancellation. The layer
    that armed the bound does know, so it says so here. This is annotation, not
    accounting: it never changes ``usage_known`` and never admits another request.
    """
    if _BUDGET is None:
        # Nothing settles here, so a note would be kept forever and hold the task
        # alive. Production runs without the pilot armed must pay nothing.
        return
    task = _current_task()
    if task is None:
        return
    _ABORT_CONTEXT[id(task)] = (task, reason)


def clear_abort_context() -> None:
    """Drop this task's pending note (the bound it described no longer applies)."""
    task = _current_task()
    if task is not None:
        _ABORT_CONTEXT.pop(id(task), None)


def _pop_abort_context() -> str:
    task = _current_task()
    if task is None:
        return ""
    entry = _ABORT_CONTEXT.pop(id(task), None)
    if entry is None or entry[0] is not task:  # id reuse: not this task's note
        return ""
    return entry[1]


class PilotBudgetExhausted(RuntimeError):
    """Raised before sending when the next request would cross a limit."""


@dataclass
class _Ticket:
    prompt_estimate: int
    completion_reserve: int
    sent_at: float
    path: str = ""


@dataclass
class PilotBudget:
    """Counters shared by every client in one pilot run (one process, one arm)."""

    max_requests: int
    max_prompt_tokens: int
    max_completion_tokens: int
    max_wall_s: float
    #: Optional per-request output cap, clamped onto the wire request when set.
    #: Without it the arm inherits whatever the client chain configured (16,384 from
    #: ``llm_max_tokens``), which can exceed the budget the run was approved for and
    #: make every later admission fail on a reservation the arm never granted.
    per_request_completion_cap: int | None = None
    started_at: float = field(default_factory=time.monotonic)
    requests_sent: int = 0
    requests_failed: int = 0
    prompt_reserved: int = 0
    prompt_settled: int = 0
    completion_reserved: int = 0
    completion_settled: int = 0
    unknown_usage_requests: int = 0
    #: ``stop`` (strict) or ``estimate`` (charge the pre-send reservation as a
    #: placeholder and keep admitting). Declared by the arm, never inferred.
    unknown_usage_policy: str = UNKNOWN_USAGE_STOP
    #: Placeholder tokens for requests whose usage was never established. Separate
    #: from ``*_settled`` on purpose: no reader may mistake these for measurements.
    prompt_placeholder: int = 0
    completion_placeholder: int = 0
    #: Why the first unsettleable request ended. Diagnostics only: the arm is over
    #: either way, but "the caller cancelled it" must not be read later as "the
    #: provider failed", and vice versa.
    unknown_usage_aborted_by: str = ""
    unknown_usage_watchdog: str = ""
    stopped_reason: str = ""

    # ── lifecycle ────────────────────────────────────────────────────────
    def elapsed(self) -> float:
        return time.monotonic() - self.started_at

    def _stop(self, reason: str) -> PilotBudgetExhausted:
        if not self.stopped_reason:
            self.stopped_reason = reason
            logger.warning("pilot budget stop: %s (%s)", reason, self.snapshot())
        return PilotBudgetExhausted(reason)

    def reserve(
        self,
        prompt_estimate: int,
        completion_reserve: int,
        path: str = "",
        stream: bool = False,
    ) -> _Ticket:
        """Reserve for the request before it is sent, or refuse to send it."""
        if self.elapsed() >= self.max_wall_s:
            raise self._stop("wall_clock")
        if self.requests_sent + 1 > self.max_requests:
            raise self._stop("requests")
        if self.stopped_reason == "usage_unavailable":
            # One request already ended without a usable usage figure: the ledger
            # cannot bound anything after that, so no further request is admitted.
            raise self._stop("usage_unavailable")
        # A note describes the request that is about to be sent, never the one after
        # it: clear whatever the previous attempt left behind.
        clear_abort_context()
        # The cap covers what is already settled, everything still in flight, and
        # every placeholder a cancelled request left behind: the estimate is charged
        # on the way out, not on the way back.
        if (
            self.prompt_settled + self.prompt_placeholder + self.prompt_reserved + prompt_estimate
            > self.max_prompt_tokens
        ):
            raise self._stop("prompt_tokens")
        if (
            self.completion_settled
            + self.completion_placeholder
            + self.completion_reserved
            + completion_reserve
            > self.max_completion_tokens
        ):
            raise self._stop("completion_tokens")
        self.requests_sent += 1
        self.prompt_reserved += prompt_estimate
        self.completion_reserved += completion_reserve
        # The estimate is recorded before the request leaves, so a run that dies can
        # still be read: what was reserved is knowable even when what was spent is not.
        logger.info(
            "pilot send #%d: est_prompt=%d reserve_completion=%d stream=%s "
            "in_flight_prompt=%d in_flight_completion=%d mode=%s",
            self.requests_sent, prompt_estimate, completion_reserve, stream,
            self.prompt_reserved, self.completion_reserved, estimate_mode(),
        )
        return _Ticket(prompt_estimate, completion_reserve, time.monotonic(), path)

    def settle(
        self,
        ticket: _Ticket,
        usage: dict[str, Any] | None,
        *,
        failed: bool = False,
        aborted_by: str = "",
        watchdog: str = "",
    ) -> None:
        """Release this request's reservation and record what it actually cost.

        ``aborted_by`` / ``watchdog`` say who ended the request. They are recorded
        only when usage is missing. The annotation itself never changes admission —
        a cancel whose cause is known still leaves the *cost* unknown; what decides
        whether the arm continues is the declared ``unknown_usage_policy``.
        """
        if failed:
            self.requests_failed += 1
        # Released in every case: the bound belonged to the request, and the request
        # is over. Leaving it charged would charge the arm for tokens it never used.
        self.prompt_reserved -= ticket.prompt_estimate
        self.completion_reserved -= ticket.completion_reserve
        prompt = _int(usage, "prompt_tokens", "input_tokens") if usage else None
        completion = _int(usage, "completion_tokens", "output_tokens") if usage else None
        if prompt is None or completion is None:
            # Unknown is neither zero nor refundable. Under ``stop`` it ends the arm;
            # under ``estimate`` the pre-send reservation becomes a placeholder so the
            # arm can keep going. Neither path invents a measurement: the placeholder
            # is published separately and is never written into ``*_settled``.
            self.unknown_usage_requests += 1
            if not self.unknown_usage_aborted_by:
                self.unknown_usage_aborted_by = aborted_by or ABORTED_BY_UNRECORDED
                self.unknown_usage_watchdog = watchdog
            if (
                self.unknown_usage_policy == UNKNOWN_USAGE_ESTIMATE
                and self.unknown_usage_aborted_by in PLACEHOLDER_ELIGIBLE_ABORTS
            ):
                self.prompt_placeholder += ticket.prompt_estimate
                self.completion_placeholder += ticket.completion_reserve
                logger.warning(
                    "pilot settle #%d: est_prompt=%d usage=unavailable usage_known=False "
                    "failed=%s aborted_by=%s watchdog=%s -> placeholder charged "
                    "prompt+%d completion+%d (placeholders=%d/%d, settled stays %d/%d)",
                    self.requests_sent, ticket.prompt_estimate, failed,
                    self.unknown_usage_aborted_by, self.unknown_usage_watchdog or "-",
                    ticket.prompt_estimate, ticket.completion_reserve,
                    self.prompt_placeholder, self.completion_placeholder,
                    self.prompt_settled, self.completion_settled,
                )
                return
            # Everything else — a stream that ended without usage, a transport or
            # provider failure, an abort of unknown provenance — stays outside the
            # approved policy: no placeholder, stop the arm.
            logger.warning(
                "pilot settle #%d: est_prompt=%d usage=unavailable usage_known=False "
                "failed=%s aborted_by=%s watchdog=%s policy=%s -> usage_unavailable",
                self.requests_sent, ticket.prompt_estimate, failed,
                self.unknown_usage_aborted_by, self.unknown_usage_watchdog or "-",
                self.unknown_usage_policy,
            )
            self._stop("usage_unavailable")
            return
        self.prompt_settled += prompt
        self.completion_settled += completion
        # Estimate next to actual: this ratio is the only calibration evidence the
        # margin in ``_TOKENIZER_SAFETY`` has, and it has to come from real runs.
        logger.info(
            "pilot settle #%d: est_prompt=%d actual_prompt=%d ratio=%.2f actual_completion=%d "
            "totals=%d/%d in_flight=%d/%d",
            self.requests_sent, ticket.prompt_estimate, prompt,
            prompt / max(ticket.prompt_estimate, 1), completion,
            self.prompt_settled, self.completion_settled,
            self.prompt_reserved, self.completion_reserved,
        )

    def snapshot(self) -> dict[str, Any]:
        """``*_reserved`` is the in-flight window at this instant, not a running charge."""
        return {
            "requests_sent": self.requests_sent,
            "requests_failed": self.requests_failed,
            "unknown_usage_requests": self.unknown_usage_requests,
            "unknown_usage_aborted_by": self.unknown_usage_aborted_by,
            "unknown_usage_watchdog": self.unknown_usage_watchdog,
            "unknown_usage_policy": self.unknown_usage_policy,
            "estimate_mode": estimate_mode(),
            "prompt_settled": self.prompt_settled,
            "prompt_placeholder": self.prompt_placeholder,
            "prompt_reserved": self.prompt_reserved,
            "completion_settled": self.completion_settled,
            "completion_placeholder": self.completion_placeholder,
            "completion_reserved": self.completion_reserved,
            "elapsed_s": round(self.elapsed(), 3),
            "per_request_completion_cap": self.per_request_completion_cap,
            "limits": {
                "requests": self.max_requests,
                "prompt_tokens": self.max_prompt_tokens,
                "completion_tokens": self.max_completion_tokens,
                "wall_s": self.max_wall_s,
            },
            "stopped_reason": self.stopped_reason,
        }


def _int(usage: dict[str, Any], *names: str) -> int | None:
    for name in names:
        value = usage.get(name)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return value
    return None


def _optional_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


#: ``tokenizer`` counts the whole request with tiktoken and a documented margin;
#: ``bytes`` counts the serialized request in UTF-8 bytes. Both are estimates of the
#: *provider's* input tokens, and neither is a proven bound: the server applies its
#: own chat template, special tokens and tool-description rewriting after our bytes
#: leave the process, so any bound here would need an endpoint contract we do not
#: have. ``bytes`` is simply the more conservative of the two and reserves more.
#: Which one is in force is published in the ledger, not assumed.
ESTIMATE_MODE_ENV = "FRONTIER_PILOT_ESTIMATE"
_DEFAULT_ESTIMATE_MODE = "tokenizer"
_TOKENIZER_SAFETY = 1.35

#: Fields that consume prompt tokens besides the messages themselves. Omitting the
#: tool schemas is exactly how a 17,016-token request was costed at 14,290.
_PAYLOAD_KEYS = ("tools", "tool_choice", "response_format", "functions", "function_call")

_encoder: Any = None
_encoder_failed = False


def _encoder_or_none() -> Any:
    """Load the tokenizer once; return ``None`` when it is unavailable."""
    global _encoder, _encoder_failed
    if _encoder is not None or _encoder_failed:
        return _encoder
    try:
        import tiktoken

        _encoder = tiktoken.get_encoding("cl100k_base")
    except Exception:  # pragma: no cover - depends on the installed wheels
        logger.warning(
            "pilot budget: tokenizer unavailable, reserving on UTF-8 bytes instead "
            "(more conservative, higher reservation)"
        )
        _encoder_failed = True
    return _encoder


def estimate_mode() -> str:
    """Which estimator is in force: ``tokenizer`` or ``bytes``."""
    requested = os.environ.get(ESTIMATE_MODE_ENV, _DEFAULT_ESTIMATE_MODE).strip().lower()
    if requested == "bytes" or _encoder_or_none() is None:
        return "bytes"
    return "tokenizer"


def _payload_text(kwargs: dict[str, Any]) -> tuple[str, int]:
    """Serialize *everything* the request will carry, messages and schemas alike."""
    messages = kwargs.get("messages") or []
    parts = [
        json.dumps(message, ensure_ascii=False, sort_keys=True, default=str)
        for message in messages
    ]
    for key in _PAYLOAD_KEYS:
        if kwargs.get(key) is not None:
            parts.append(json.dumps(kwargs[key], ensure_ascii=False, sort_keys=True, default=str))
    return "\n".join(parts), len(messages)


def estimate_prompt_tokens(kwargs: dict[str, Any]) -> int:
    """Prompt-token estimate for the *complete* request, at the send boundary.

    The old estimator read only message text, divided characters by two, and called
    itself biased high; a recorded request then cost 17,016 tokens against a 14,290
    estimate. Two things changed: tool schemas and every other payload field are
    counted, and the unit conversion is no longer a guess.

    Both modes are estimates of the provider's input tokens, and the limit they
    enforce is therefore a budget of estimates, not a proven ceiling on spend. The
    server tokenizes its own chat template, its own special tokens and its own
    rendering of tool descriptions, none of which we can see from here; claiming a
    strict bound would need an endpoint contract this project does not have.

    ``tokenizer`` mode counts with tiktoken and multiplies by a margin; ``bytes``
    mode counts the serialized request in UTF-8 bytes and reserves more. Pick one,
    publish the limitation, and read the ledger's ``estimate_mode`` when in doubt.
    """
    text, message_count = _payload_text(kwargs)
    envelope = 8 * message_count + 64
    encoder = _encoder_or_none()
    if encoder is None or os.environ.get(ESTIMATE_MODE_ENV, "").strip().lower() == "bytes":
        return len(text.encode("utf-8")) + envelope
    return math.ceil(len(encoder.encode(text, disallowed_special=())) * _TOKENIZER_SAFETY) + envelope


_BUDGET: PilotBudget | None = None


def current() -> PilotBudget | None:
    return _BUDGET


def _unknown_usage_policy(value: Any) -> str:
    """Read the declared policy; anything unrecognised falls back to the strict one."""
    requested = str(value or UNKNOWN_USAGE_STOP).strip().lower()
    if requested not in _UNKNOWN_USAGE_POLICIES:
        logger.warning(
            "pilot budget: unknown unknown_usage policy %r, using %r",
            value, UNKNOWN_USAGE_STOP,
        )
        return UNKNOWN_USAGE_STOP
    return requested


def arm(spec: dict[str, Any]) -> PilotBudget:
    """Arm the process budget from an explicit mapping (per-run experiment config).

    Preferred over the env var for a paired pilot: the limits then belong to the
    run that carries them, so two arms sharing one server still get one ledger
    each and no process-global flag can leak into an unrelated run.
    """
    global _BUDGET
    _BUDGET = PilotBudget(
        max_requests=int(spec["requests"]),
        max_prompt_tokens=int(spec["prompt_tokens"]),
        max_completion_tokens=int(spec["completion_tokens"]),
        max_wall_s=float(spec["wall_s"]),
        per_request_completion_cap=_optional_int(spec.get("max_completion_tokens")),
        unknown_usage_policy=_unknown_usage_policy(spec.get("unknown_usage")),
    )
    logger.warning(
        "pilot budget armed per run: %s policy=%s",
        _BUDGET.snapshot()["limits"], _BUDGET.unknown_usage_policy,
    )
    return _BUDGET


def from_env() -> PilotBudget | None:
    """Build (once) the process budget described by ``FRONTIER_PILOT_BUDGET``."""
    global _BUDGET
    if _BUDGET is not None:
        return _BUDGET
    raw = os.environ.get(ENV_FLAG, "").strip()
    if not raw:
        return None
    spec = json.loads(raw)
    _BUDGET = PilotBudget(
        max_requests=int(spec["requests"]),
        max_prompt_tokens=int(spec["prompt_tokens"]),
        max_completion_tokens=int(spec["completion_tokens"]),
        max_wall_s=float(spec["wall_s"]),
        per_request_completion_cap=_optional_int(spec.get("max_completion_tokens")),
        unknown_usage_policy=_unknown_usage_policy(spec.get("unknown_usage")),
    )
    logger.info(
        "pilot budget armed: %s policy=%s",
        _BUDGET.snapshot()["limits"], _BUDGET.unknown_usage_policy,
    )
    return _BUDGET


def _settling_stream(stream: Any, budget: PilotBudget, ticket: _Ticket) -> Any:
    """Async generator that settles its ticket when the stream ends *or is closed*.

    The transport streams (``stream=True`` + ``stream_options.include_usage``), so
    the awaited call returns a stream, not a response: usage only arrives on the
    terminal chunk. Settling at the ``await`` saw no usage at all and left every
    reservation charged — that is how a 3-request arm once "exhausted" 100k
    completion tokens it had never spent.

    A generator rather than a hand-rolled iterator because callers abandon streams
    (``_timed_chunks`` breaks out of ``async for``): only a real async generator gets
    ``aclose()`` from the enclosing generator's cleanup, and only then does the
    ``finally`` below release the reservation.
    """
    state: dict[str, Any] = {"settled": False, "usage": None, "aborted_by": "", "watchdog": ""}

    def _attribute(exc: BaseException | None) -> None:
        """Label who ended the request, while the evidence is still in this frame."""
        watchdog = _pop_abort_context()
        if exc is None:
            state["aborted_by"] = ABORTED_BY_STREAM_END
        elif isinstance(exc, asyncio.CancelledError):
            # ``asyncio.timeout``, a watchdog and a caller cancel are the same
            # cancellation by the time it reaches the transport; only the note can
            # tell them apart, and the note is optional.
            state["aborted_by"] = ABORTED_BY_CALLER_CANCEL
        else:
            # A real transport/provider failure keeps its own name, whatever note
            # happens to be armed: it must not be filed as a deliberate cancel.
            state["aborted_by"] = type(exc).__name__
        state["watchdog"] = watchdog

    def _settle(failed: bool = False) -> None:
        # Idempotent: exhaustion, close and error can all land here.
        if state["settled"]:
            return
        state["settled"] = True
        usage = state["usage"]
        budget.settle(
            ticket,
            _as_dict(usage) if usage is not None else None,
            failed=failed,
            aborted_by=state["aborted_by"],
            watchdog=state["watchdog"],
        )

    async def _generate() -> Any:
        try:
            async for chunk in stream:
                usage = getattr(chunk, "usage", None)
                if usage is not None:
                    state["usage"] = usage
                yield chunk
        except GeneratorExit:
            _attribute(None)
            state["aborted_by"] = ABORTED_BY_CALLER_CLOSE
            raise
        except BaseException as exc:
            _attribute(exc)
            _settle(failed=True)
            raise
        else:
            _attribute(None)
        finally:
            _settle()

    return _generate()


def install(client: Any) -> PilotBudget | None:
    """Wrap one AsyncOpenAI client's ``chat.completions.create``.

    Returns the budget that was installed, or ``None`` when the pilot is not
    armed. Wrapping the transport per client is what makes the guarantee hold for
    summary and extraction clients too: they build their own ``OpenAIClient``.
    """
    budget = from_env()
    if budget is None:
        return None
    completions = client.chat.completions
    if getattr(completions, "_pilot_budget_installed", False):
        return budget
    original = completions.create

    async def create(*args: Any, **kwargs: Any) -> Any:
        inherited_cap = int(kwargs.get("max_completion_tokens") or kwargs.get("max_tokens") or 0)
        cap = budget.per_request_completion_cap
        if cap is not None and (inherited_cap == 0 or inherited_cap > cap):
            # The arm was approved for a per-request cap; the client chain may have
            # inherited a larger one (16,384 from ``llm_max_tokens``). Reserve and
            # send the approved number, otherwise every later admission is refused
            # on a bound the arm never granted.
            logger.info(
                "pilot budget: per-request output cap %d -> %d (arm limit)", inherited_cap, cap
            )
            kwargs["max_completion_tokens"] = cap
            kwargs.pop("max_tokens", None)
            inherited_cap = cap
        ticket = budget.reserve(
            estimate_prompt_tokens(kwargs),
            inherited_cap,
            path=str(kwargs.get("model") or ""),
            stream=bool(kwargs.get("stream")),
        )
        try:
            response = await original(*args, **kwargs)
        except BaseException:
            budget.settle(ticket, None, failed=True)
            raise
        if kwargs.get("stream") or hasattr(response, "__anext__"):
            # Usage is not on the returned object for a streamed call; it is the
            # terminal chunk. Hand back a generator that settles when it ends.
            return _settling_stream(response, budget, ticket)
        usage = _usage_from(response)
        budget.settle(ticket, _as_dict(usage) if usage is not None else None)
        return response

    completions.create = create
    completions._pilot_budget_installed = True
    return budget


def _usage_from(response: Any) -> Any:
    """Usage off a completion *or* off the raw wrapper some paths return.

    ``OpenAIClient.chat`` calls ``completions.with_raw_response.create(...)``, and
    that path routes through the patched ``completions.create``: the guard therefore
    received an ``openai._legacy_response.LegacyAPIResponse``, which carries no
    ``usage`` attribute at all. Settling on it reported "usage unavailable" for a
    fully billed request and stopped the arm on its first turn.
    """
    usage = getattr(response, "usage", None)
    if usage is not None:
        return usage
    parse = getattr(response, "parse", None)
    if not callable(parse):
        return None
    try:
        parsed = parse()
    except Exception:  # pragma: no cover - depends on the SDK's raw wrapper
        logger.warning("pilot budget: raw response could not be parsed for usage", exc_info=True)
        return None
    return getattr(parsed, "usage", None)


def _as_dict(usage: Any) -> dict[str, Any]:
    if isinstance(usage, dict):
        return dict(usage)
    for attr in ("model_dump", "to_dict"):
        method = getattr(usage, attr, None)
        if callable(method):
            value = method()
            if isinstance(value, dict):
                return value
    return {
        name: getattr(usage, name, None)
        for name in ("prompt_tokens", "completion_tokens", "input_tokens", "output_tokens")
        if getattr(usage, name, None) is not None
    }
