"""A test run must fail before it spends money at a real provider.

Field evidence (2026-11-17): two integration tests believed they were using
``MockLLMServer``; the worker subprocess resolved its endpoint from the server's
own configuration and reached the production gateway instead — 1 run, 2 requests,
18,878 input tokens. Isolation has to be a mechanism, not a note in a ledger.
"""

from __future__ import annotations

import pytest

from frontier_agent.infra import llm_egress
from frontier_agent.infra.openai_client import OpenAIClient

REAL = "https://ark.cn-beijing.volces.com/api/plan/v3"


def test_local_only_rejects_a_real_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(llm_egress.LOCAL_ONLY_ENV, "1")
    with pytest.raises(RuntimeError, match="non-loopback"):
        llm_egress.assert_local_endpoint(REAL, model="deepseek-v4.1-flash")


def test_local_only_allows_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(llm_egress.LOCAL_ONLY_ENV, "1")
    for url in ("http://127.0.0.1:8123/v1", "http://localhost:8123/v1"):
        llm_egress.assert_local_endpoint(url)


def test_flag_absent_keeps_production_usable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(llm_egress.LOCAL_ONLY_ENV, raising=False)
    llm_egress.assert_local_endpoint(REAL)  # no restriction outside tests


async def test_send_path_blocks_before_the_request(monkeypatch: pytest.MonkeyPatch) -> None:
    """The refusal happens on the way out, not after a connection attempt."""
    monkeypatch.setenv(llm_egress.LOCAL_ONLY_ENV, "1")
    client = OpenAIClient(model="offline-guard", api_key="sk-not-used", base_url=REAL)

    sent: list[int] = []

    async def _never(*args: object, **kwargs: object) -> object:
        sent.append(1)
        raise AssertionError("the transport must not be reached")

    monkeypatch.setattr(client._client.chat.completions, "create", _never)
    with pytest.raises(RuntimeError, match="non-loopback"):
        await client.chat([{"role": "user", "content": "hi"}], timeout=5)
    assert not sent

    with pytest.raises(RuntimeError, match="non-loopback"):
        async for _delta in client.stream([{"role": "user", "content": "hi"}], timeout=5):
            pass
    assert not sent
