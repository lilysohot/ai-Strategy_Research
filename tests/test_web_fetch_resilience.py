"""Regressions for the retrieval failures found in run 4c9f1c2e.

That run's members spent 60-88% of their tool time inside calls that returned
nothing: hosts whose resolver answered with a synthetic Teredo address were
rejected as ``policy_blocked`` even though a public A record existed, direct
scrapes waited the full 60 s on anti-bot pages, and every anti-bot page paid a
pointless Unpaywall detour. The tests below pin each fix and the model-facing
messages that replace a bare ``TypeError``.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from frontier_agent.core.runtime.loop.tool_exec import _invocation_error_text
from frontier_agent.core.tool import Tool, ToolOutcome
from plugins.tools._content_outcome import combine_content_outcomes


async def test_batch_keeps_fast_result_when_one_url_exceeds_budget(monkeypatch):
    import importlib

    module = importlib.import_module("plugins.tools.web_fetch")
    cancelled = asyncio.Event()

    async def fetch(url, focus):
        if url.endswith("fast"):
            return "original evidence = 32"
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    monkeypatch.setattr(module, "_fetch_one", fetch)
    monkeypatch.setattr(module, "_FETCH_ONE_TIMEOUT_S", 0.02, raising=False)
    result = await asyncio.wait_for(
        module.web_fetch.func(["https://example.org/fast", "https://example.org/slow"]), 0.2,
    )
    assert isinstance(result, ToolOutcome)
    payload = json.loads(result.result)
    assert payload["acquired_count"] == 1 and payload["failed_count"] == 1
    assert payload["items"][0]["content"] == "original evidence = 32"
    assert cancelled.is_set()


async def test_partial_search_is_not_misclassified_as_empty():
    from frontier_agent.components.observers.duplicate_query_rollback import _is_failed_search
    from frontier_agent.core.loop_types import ToolResult

    outcome = combine_content_outcomes(
        ["good query", "failed query"],
        ["useful search hits", ToolOutcome(json.dumps({
            "ok": False, "status": "unavailable", "source": "failed query", "content": "",
        }), is_error=True)],
    )
    result = ToolResult("web_search", {"q": ["good query", "failed query"]}, outcome.result, 1, "c", True)
    assert not _is_failed_search(result)
    from frontier_agent.components.observers.duplicate_query_rollback import (
        DuplicateQueryRollbackObserver,
    )
    from frontier_agent.core.loop_types import TurnContext

    observer = DuplicateQueryRollbackObserver()
    ctx = TurnContext(
        turn=1, max_turns=10, task_id="root", role_id="worker", ai_text="",
        thinking="", tool_calls=[], messages=[], usage=None, metadata={},
    )
    await observer.on_tool_result(ctx, result)
    for query, blocked in [("good query", True), ("failed query", False)]:
        ctx.tool_calls = [{"name": "web_search", "args": {"q": query}}]
        assert (await observer.on_llm_response(ctx) is not None) is blocked


async def test_batch_propagates_parent_cancellation(monkeypatch):
    import importlib

    module = importlib.import_module("plugins.tools.web_fetch")
    started = asyncio.Event()
    cancelled = []

    async def fetch(url, focus):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append(url)

    monkeypatch.setattr(module, "_fetch_one", fetch)
    task = asyncio.create_task(module.web_fetch.func(["https://a.test", "https://b.test"]))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(cancelled) == 2

# ── Address policy ────────────────────────────────────────────────────


def _resolver(*answers):
    def fake(host, port, **kwargs):
        del host, port, kwargs
        return [
            (2 if ":" in address else 4, 1, 6, "", (address, 0))
            for address in answers
        ]

    return fake


def test_public_a_record_survives_a_synthetic_ipv6_answer(monkeypatch):
    from plugins.tools import _download_runner as runner

    monkeypatch.setattr(
        runner.socket,
        "getaddrinfo",
        _resolver("31.13.90.19", "2001::1f0d:460d"),
    )

    addresses = runner._validate_public_url("https://huggingface.co/deepseek-ai")

    # IPv4 first, and the non-public Teredo answer is dropped rather than
    # poisoning the whole host.
    assert addresses == ("31.13.90.19",)


def test_host_with_only_non_public_answers_is_still_refused(monkeypatch):
    from plugins.tools import _download_runner as runner

    monkeypatch.setattr(runner.socket, "getaddrinfo", _resolver("127.0.0.1", "2001::1"))

    with pytest.raises(runner.DownloadError) as exc:
        runner._validate_public_url("http://metadata.internal/")

    assert "refusing non-public address" in str(exc.value)
    assert "127.0.0.1" in str(exc.value)


# ── Direct scrape bound ───────────────────────────────────────────────


def test_direct_scrape_timeout_defaults_shorter_and_is_overridable(monkeypatch):
    import importlib

    web_fetch = importlib.import_module("plugins.tools.web_fetch")

    monkeypatch.delenv(web_fetch._DIRECT_SCRAPE_TIMEOUT_ENV, raising=False)
    assert web_fetch._direct_scrape_timeout_s() == 20.0

    monkeypatch.setenv(web_fetch._DIRECT_SCRAPE_TIMEOUT_ENV, "7.5")
    assert web_fetch._direct_scrape_timeout_s() == 7.5

    monkeypatch.setenv(web_fetch._DIRECT_SCRAPE_TIMEOUT_ENV, "not-a-number")
    assert web_fetch._direct_scrape_timeout_s() == 20.0


async def test_direct_scrape_uses_the_configured_bound(monkeypatch):
    import importlib

    web_fetch = importlib.import_module("plugins.tools.web_fetch")

    seen: list[dict] = []

    class _Stream:
        async def __aenter__(self):
            raise httpx.TimeoutException("simulated slow origin")

        async def __aexit__(self, *_exc):
            return False

    class _Client:
        def __init__(self, **kwargs):
            seen.append(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return False

        def stream(self, *_args, **_kwargs):
            return _Stream()

    monkeypatch.setattr(web_fetch.httpx, "AsyncClient", _Client)
    monkeypatch.setenv(web_fetch._DIRECT_SCRAPE_TIMEOUT_ENV, "6")

    assert await web_fetch._direct_scrape("https://slow.example/page") == ""
    assert seen and seen[0]["timeout"] == 6.0


# ── Unpaywall detour ──────────────────────────────────────────────────


async def test_generic_news_page_does_not_pay_the_unpaywall_detour(monkeypatch):
    import importlib

    web_fetch = importlib.import_module("plugins.tools.web_fetch")

    calls: list[str] = []

    async def fake_resolve(url):
        calls.append(url)
        return None

    monkeypatch.setattr(web_fetch, "resolve_doi", fake_resolve)
    garbage = "Please enable JavaScript and cookies to continue"

    result = await web_fetch._maybe_recover_via_unpaywall(
        "https://qz.com/deepseek-v4-1-flash-1017", "jina", garbage, SimpleNamespace(),
    )

    assert result == garbage
    assert calls == []


async def test_doi_bearing_page_still_gets_the_unpaywall_detour(monkeypatch):
    import importlib

    web_fetch = importlib.import_module("plugins.tools.web_fetch")

    calls: list[str] = []

    async def fake_resolve(url):
        calls.append(url)
        return None

    monkeypatch.setattr(web_fetch, "resolve_doi", fake_resolve)

    await web_fetch._maybe_recover_via_unpaywall(
        "https://doi.org/10.1000/xyz123", "jina", "", SimpleNamespace(),
    )

    assert calls == ["https://doi.org/10.1000/xyz123"]


# ── Empty-fetch message ───────────────────────────────────────────────


async def test_empty_fetch_tells_the_model_not_to_repeat_the_same_url(monkeypatch):
    import importlib

    web_fetch = importlib.import_module("plugins.tools.web_fetch")
    from plugins.tools._scrape_cache import ScrapeUnavailable

    async def no_block(_url):
        return ""

    async def empty_scrape(*_args, **_kwargs):
        raise ScrapeUnavailable("empty")

    monkeypatch.setattr(web_fetch, "non_public_url_error", no_block)
    monkeypatch.setattr(web_fetch, "blocked_download_url", lambda _url: "")
    monkeypatch.setattr(web_fetch._scrape_cache, "check", lambda _url: None)
    monkeypatch.setattr(
        web_fetch.scrape_result_cache, "get_or_scrape", empty_scrape,
    )
    monkeypatch.setattr(
        web_fetch, "get_config",
        lambda: SimpleNamespace(jina_api_key="", jina_base_url=""),
    )
    web_search = importlib.import_module("plugins.tools.web_search")
    monkeypatch.setattr(web_search, "is_domain_blocked", lambda _url: False)

    outcome = await web_fetch._fetch_one("https://news.example/a", "")

    assert isinstance(outcome, ToolOutcome) and outcome.is_error
    payload = json.loads(outcome.result)
    assert payload["status"] == "unavailable"
    assert "Repeating the same URL is unlikely to help" in payload["detail"]


# ── Batch envelope ────────────────────────────────────────────────────


def test_mixed_batch_names_what_was_acquired_and_what_failed():
    outcome = combine_content_outcomes(
        ["https://ok.example", "https://blocked.example"],
        [
            "usable body text",
            ToolOutcome(
                json.dumps(
                    {
                        "ok": False,
                        "status": "policy_blocked",
                        "source": "https://blocked.example",
                        "content": "",
                        "detail": "blocked",
                    }
                ),
                is_error=True,
            ),
        ],
    )

    assert outcome is not None and outcome.is_error
    payload = json.loads(outcome.result)
    assert payload["status"] == "partial"
    assert payload["succeeded"] == ["https://ok.example"]
    assert payload["failed"] == ["https://blocked.example"]
    assert payload["acquired_count"] == 1
    assert "do not re-fetch this whole batch" in payload["advice"]


# ── Model-facing invocation errors ────────────────────────────────────


def test_missing_argument_names_the_field_and_the_required_set():
    tool = Tool(
        name="web_search",
        description="search",
        parameters={"type": "object", "properties": {"q": {"type": "string"}},
                    "required": ["q"]},
        func=None,  # type: ignore[arg-type]
    )
    exc = TypeError("web_search() missing 1 required positional argument: 'q'")

    text = _invocation_error_text("web_search", {}, tool, exc)

    assert "without required argument(s): q" in text
    assert "required: q" in text
    assert "did not run" in text


async def test_missing_argument_is_reported_through_the_real_executor():
    from frontier_agent.core.runtime.loop.tool_exec import execute_tools

    async def needs_q(q: str) -> str:  # pragma: no cover - never invoked
        return q

    tool = Tool(
        name="web_search",
        description="search",
        parameters={"type": "object", "properties": {"q": {"type": "string"}},
                    "required": ["q"]},
        func=needs_q,
    )

    results = await execute_tools(
        [{"id": "c1", "name": "web_search", "args": {}}],
        {"web_search": tool},
        timeout=5,
        turn=1,
        count_offset=0,
    )

    assert len(results) == 1
    assert results[0].is_error
    assert "without required argument(s): q" in results[0].result


def test_other_tool_errors_keep_their_type_name():
    tool = Tool(name="x", description="", parameters={}, func=None)  # type: ignore[arg-type]

    assert (
        _invocation_error_text("x", {}, tool, ValueError("bad"))
        == "Error: ValueError: bad"
    )


async def test_assign_task_empty_call_names_the_required_shape():
    from plugins.tools.assign_task import assign_task

    message = await assign_task.func(tasks="")

    assert "requires at least one task" in message
    assert '"agent"' in message and '"prompt"' in message
    assert "will fail again" in message


async def test_replay_that_still_loses_arguments_is_reported(monkeypatch):
    """A non-streaming replay that also loses args must not look recovered.

    The live run dispatched ``assign_task({})`` after a replay and the only
    signal was a generic tool error. Record the failed recovery so the attempt
    trace and the downstream error can be read together.
    """
    from frontier_agent.core.llm import LLMResponse
    from frontier_agent.core.runtime.loop import _call
    from frontier_agent.core.runtime.loop._bind import _BoundLLM

    response = LLMResponse(
        content="",
        tool_calls=[{
            "id": "call_1",
            "type": "function",
            "function": {"name": "assign_task", "arguments": "{}"},
        }],
        finish_reason="tool_calls",
    )

    class FakeClient:
        model = "offline"

        async def chat(self, *_args, **_kwargs):
            return response

        async def stream(self, *_args, **_kwargs):
            if False:
                yield None

    tools = [{
        "type": "function",
        "function": {
            "name": "assign_task",
            "parameters": {"type": "object", "required": ["tasks"]},
        },
    }]

    async def fake_stream(*_args, **_kwargs):
        return response

    async def on_delta(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(_call, "_stream_llm_response", fake_stream)
    monkeypatch.setattr(_call, "_llm_gate", lambda: None)
    monkeypatch.setattr(_call, "wall_deadline_remaining_s", lambda: None)

    got = await _call.call_llm(
        _BoundLLM(client=FakeClient(), tools=tools),
        [],
        timeout=60,
        max_retries=2,
        turn=1,
        on_delta=on_delta,
    )

    metadata = got.response_metadata or {}
    assert metadata["stream_empty_args_recovered"] is False
    assert metadata["stream_empty_args_still_missing"] == ["assign_task"]
