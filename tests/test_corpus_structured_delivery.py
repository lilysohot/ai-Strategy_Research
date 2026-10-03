"""Semantic query delivery survives every tool-result shaping boundary."""

from __future__ import annotations

import json
import socket
from pathlib import Path

import dotenv
import dotenv.main
import httpx
import pytest
from test_corpus_structured_contracts import V1, _load, _validation_errors
from test_corpus_structured_query import published_material_with_condition

from frontier_agent.core.llm import LLMResponse
from frontier_agent.core.loop_types import LoopConfig, LoopPolicy, ToolResult
from frontier_agent.core.runtime.loop.agent_loop import run_agent_loop
from plugins.corpus.cursor import decode_cursor
from plugins.corpus.service import CorpusService
from plugins.corpus.structured.query import SemanticQueryPage, query_semantic
from plugins.tools._overflow import structured_result_fit
from plugins.tools.corpus_semantic_query import (
    corpus_semantic_query,
    fit_structured_payload,
)
from workflows.stateful_react_agent._runtime import ReactToolResultPostProcessor


@pytest.fixture(autouse=True)
def deny_external_io(monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("semantic delivery tests must not access external systems")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket, "getaddrinfo", denied)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", denied)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", denied)
    monkeypatch.setattr(dotenv, "load_dotenv", denied)
    monkeypatch.setattr(dotenv.main, "load_dotenv", denied)
    monkeypatch.setattr(CorpusService, "_connect", denied)


def _bulky_page(tmp_path: Path, *, start_position: int = 0) -> str:
    snapshot, root, _publication = published_material_with_condition(tmp_path, extra_units=15)
    cursor = None
    if start_position:
        cursor = query_semantic(
            snapshot.source_id,
            snapshot.build_id,
            purpose="cite",
            query_text="收入",
            limit=start_position,
            max_chars=100_000,
            store_root=root,
        ).next_cursor
    page = query_semantic(
        snapshot.source_id,
        snapshot.build_id,
        purpose="cite",
        query_text="收入",
        max_chars=100_000,
        cursor=cursor,
        store_root=root,
    )
    assert len(page.records) == 10 and page.next_cursor
    return page.model_dump_json()


@pytest.mark.asyncio
async def test_registered_tool_reads_publication_and_returns_contract_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot, root, publication = published_material_with_condition(tmp_path)
    monkeypatch.setenv("CORPUS_STRUCTURED_ROOT", str(root))

    body = await corpus_semantic_query.ainvoke(
        {
            "source_id": snapshot.source_id,
            "build_id": snapshot.build_id,
            "purpose": "cite",
            "query_text": "收入",
            "limit": 10,
        }
    )
    payload = json.loads(body)
    schema = _load(V1 / "semantic-query-page.schema.json")

    assert _validation_errors(payload, schema, schema) == []
    assert payload["publication_id"] == publication.publication_id
    assert payload["records"][0]["dependencies"][0]["kind"] == "condition"


@pytest.mark.parametrize("start_position", [0, 3])
def test_tool_and_runtime_refits_keep_valid_whole_protocol_units(
    tmp_path: Path,
    start_position: int,
) -> None:
    body = _bulky_page(tmp_path, start_position=start_position)
    original = SemanticQueryPage.model_validate_json(body)
    first = fit_structured_payload(body, 10_000)
    assert first is not None
    first_page = SemanticQueryPage.model_validate_json(first)
    second = structured_result_fit("corpus_semantic_query", first, 6_000)
    assert second is not None
    runtime = ReactToolResultPostProcessor().process(
        ToolResult(
            name="corpus_semantic_query",
            args={},
            result=second,
            duration_ms=0,
            tool_call_id="call-semantic",
            is_error=False,
        )
    )

    payload = SemanticQueryPage.model_validate_json(runtime)
    assert payload.page_status == "budget_limited"
    assert "CS_BUDGET_EXHAUSTED" in payload.error_codes
    assert len(runtime) <= 6_000
    assert payload.records
    assert 0 < len(payload.records) < len(first_page.records) < len(original.records)
    assert payload.records == original.records[: len(payload.records)]
    assert decode_cursor(payload.next_cursor)["position"] == start_position + len(payload.records)
    for record in payload.records:
        assert record.evidence
        assert record.dependencies
        assert record.evidence[record.dependencies[0].evidence_index].quote
    assert "body truncated" not in runtime


@pytest.mark.asyncio
@pytest.mark.parametrize("initial_limit", [10, 100])
async def test_actual_second_llm_request_contains_parseable_uncut_semantic_page(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    initial_limit: int,
) -> None:
    snapshot, root, _ = published_material_with_condition(tmp_path, extra_units=15)
    monkeypatch.setenv("CORPUS_STRUCTURED_ROOT", str(root))
    args = dict(
        source_id=snapshot.source_id,
        build_id=snapshot.build_id,
        purpose="cite",
        query_text="收入",
        limit=initial_limit,
        max_chars=100_000,
    )
    expected = query_semantic(**{**args, "limit": 100}, store_root=root)
    expected_records = {record.record_id: record for record in expected.records}
    assert len(expected_records) == 16

    class RepeatedFitter:
        def process(self, result: ToolResult) -> str:
            fitted = structured_result_fit(result.name, result.result, 10_000)
            assert fitted is not None
            return ReactToolResultPostProcessor().process(
                ToolResult(
                    name=result.name,
                    args=result.args,
                    result=fitted,
                    duration_ms=0,
                    tool_call_id=result.tool_call_id,
                    is_error=False,
                )
            )

    class CapturingLlm:
        model = "synthetic-no-network"

        def __init__(self) -> None:
            self.calls = 0
            self.delivered: list[SemanticQueryPage] = []
            self.restart_gaps: list[SemanticQueryPage] = []

        async def chat(self, messages: list[dict], **_kwargs: object) -> LLMResponse:
            self.calls += 1
            cursor = None
            if self.calls > 1:
                message = next(m for m in reversed(messages) if m.get("role") == "tool")
                content = str(message["content"])
                assert len(content) <= 6_000 and "body truncated" not in content
                page = SemanticQueryPage.model_validate_json(content)
                if "CS_CURSOR_STALE" in page.error_codes:
                    assert page.page_status == "budget_limited"
                    assert not page.records and page.next_cursor is None
                    assert not self.delivered and not self.restart_gaps
                    self.restart_gaps.append(page)
                    args["limit"] = 2
                    args["max_chars"] = 5_500
                    # Explicit fresh query after a terminal page was clipped.
                    return LLMResponse(
                        content="",
                        tool_calls=[
                            {
                                "id": f"restart-{self.calls}",
                                "type": "function",
                                "function": {
                                    "name": "corpus_semantic_query",
                                    "arguments": json.dumps(args),
                                },
                            }
                        ],
                        finish_reason="tool_calls",
                    )
                self.delivered.append(page)
                assert page.records
                for record in page.records:
                    assert record == expected_records[record.record_id]
                    assert record.dependencies
                if page.page_status == "complete":
                    assert page.next_cursor is None
                    return LLMResponse(content="done", finish_reason="stop")
                assert page.page_status in {"budget_limited", "more_available"}
                assert "CS_CURSOR_STALE" not in page.error_codes
                cursor = page.next_cursor
                assert cursor
                # Adapt the page size to observed delivery capacity; limit is
                # deliberately not part of the immutable query/budget identity.
                args["limit"] = len(page.records)
            return LLMResponse(
                content="",
                tool_calls=[
                    {
                        "id": f"call-semantic-{self.calls}",
                        "type": "function",
                        "function": {
                            "name": "corpus_semantic_query",
                            "arguments": json.dumps({**args, "cursor": cursor}),
                        },
                    }
                ],
                finish_reason="tool_calls",
            )

    llm = CapturingLlm()
    result = await run_agent_loop(
        system_prompt="synthetic",
        user_message="deliver evidence",
        llm=llm,
        tools=[corpus_semantic_query],
        config=LoopConfig(
            max_turns=12,
            loop_policy=LoopPolicy(no_tool_behavior="stop"),
            tool_result_post_processor=RepeatedFitter(),
        ),
    )

    assert result.final_content == "done"
    delivered_ids = [record.record_id for page in llm.delivered for record in page.records]
    assert len(llm.delivered) > 1
    assert len(delivered_ids) == len(set(delivered_ids))
    assert set(delivered_ids) == set(expected_records)
    assert len(llm.restart_gaps) == (1 if initial_limit == 100 else 0)


def test_empty_refit_rewinds_cursor_without_skipping_first_record(tmp_path: Path) -> None:
    snapshot, root, _ = published_material_with_condition(tmp_path)
    args = dict(purpose="cite", limit=1, store_root=root)
    original = query_semantic(snapshot.source_id, snapshot.build_id, **args)
    fitted = SemanticQueryPage.model_validate_json(
        fit_structured_payload(original.model_dump_json(), 1_000)
    )
    assert fitted.records == ()
    assert decode_cursor(fitted.next_cursor)["position"] == 0
    resumed = query_semantic(
        snapshot.source_id, snapshot.build_id, cursor=fitted.next_cursor, **args
    )
    assert resumed == original


@pytest.mark.parametrize("continuation", [False, True])
def test_clipped_terminal_page_requires_explicit_restart(
    tmp_path: Path, continuation: bool
) -> None:
    snapshot, root, _ = published_material_with_condition(tmp_path)
    args = dict(purpose="cite", store_root=root)
    first = query_semantic(snapshot.source_id, snapshot.build_id, limit=1, **args)
    page = query_semantic(
        snapshot.source_id,
        snapshot.build_id,
        cursor=first.next_cursor if continuation else None,
        **args,
    )
    assert page.page_status == "complete" and page.next_cursor is None
    fitted = fit_structured_payload(page.model_dump_json(), 700)
    assert fitted is not None
    result = SemanticQueryPage.model_validate_json(fitted)
    assert result.page_status == "budget_limited"
    assert result.records == () and result.next_cursor is None
    assert set(result.error_codes) == {"CS_BUDGET_EXHAUSTED", "CS_CURSOR_STALE"}
    assert fit_structured_payload(fitted, 500) == fitted
    restarted = query_semantic(snapshot.source_id, snapshot.build_id, **args)
    assert {r.record_id for r in page.records} <= {r.record_id for r in restarted.records}
