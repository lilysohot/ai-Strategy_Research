import hashlib
import json

import pytest

from plugins.corpus.scoring import ObservationOutcome
from tools.corpus_product_observations import ProductQuery, collect_query


class FakeTool:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    async def ainvoke(self, args):
        self.calls.append(args)
        return json.dumps(self.payload(args) if callable(self.payload) else self.payload)


_BLOCK_TEXT = "每股收益\n2026E\n0.36"
_BLOCK_SHA = hashlib.sha256(_BLOCK_TEXT.encode()).hexdigest()
_BLOCK_UNITS = [{"unit_id": "u1", "page": 1}, {"unit_id": "u2", "page": 1}]
_BLOCK_SPANS = [
    {"unit_id": "u1", "start": 0, "end": 10},
    {"unit_id": "u2", "start": 10, "end": 15},
]
_BLOCK_CELLS = [{"unit_id": "u2", "page": 1, "row": "每股收益", "col": "2026E", "text": "0.36"}]


def _envelope(items, *, next_cursor, exhausted, block_evidence=None):
    envelope = {
        "ok": True,
        "schema_version": 1,
        "cursor_type": "content",
        "doc_id": "cv2:b",
        "build_id": "b",
        "view": "full",
        "items": items,
        "item_errors": [],
        "unresolved": [],
        "next_cursor": next_cursor,
        "exhausted": exhausted,
        "fetch_complete": exhausted,
    }
    if block_evidence is not None:
        envelope["block_evidence"] = block_evidence
    return envelope


def _paged_item(start, end):
    return {
        "locator": "chunk:c",
        "chunk_id": "c",
        "kind": "body",
        "build_id": "b",
        "source_id": "s",
        "text": _BLOCK_TEXT[start:end],
        "fragment": {"start": start, "end": end, "of_chars": 15},
        "text_chars": 15,
        "text_sha256": _BLOCK_SHA,
        "structure_status": "verified",
    }


def paged_tools(*, block_evidence=None):
    hit = {
        "source_id": "s",
        "build_id": "b",
        "chunk_id": "c",
        "doc_id": "cv2:b",
        "locator": "chunk:c",
    }
    search = FakeTool({"ok": True, "hits": [hit]})

    def payload(args):
        if "cursor" in args:
            return _envelope(
                [_paged_item(10, 15)],
                next_cursor=None,
                exhausted=True,
                block_evidence=block_evidence,
            )
        return _envelope(
            [_paged_item(0, 10)],
            next_cursor="CUR-1",
            exhausted=False,
            block_evidence=block_evidence,
        )

    return search, FakeTool(payload)


def _default_block_evidence():
    return {
        "locator": "chunk:c",
        "source_id": "s",
        "chunk_id": "c",
        "units": _BLOCK_UNITS,
        "spans": _BLOCK_SPANS,
        "semantic_cells": _BLOCK_CELLS,
    }


async def test_paged_envelope_follows_cursor_and_reassembles_block():
    search, fetch = paged_tools(block_evidence=_default_block_evidence())
    result = await collect_query(ProductQuery("q", "query"), search=search, fetch=fetch)
    assert result.observation.outcome is ObservationOutcome.OK
    assert fetch.calls == [
        {"doc_id": "cv2:b", "locator": "chunk:c"},
        {"doc_id": "cv2:b", "cursor": "CUR-1"},
    ]
    evidence = result.observation.documents[0].evidence
    assert evidence[0].text == _BLOCK_TEXT  # 拼回即整块
    assert evidence[1].text == "0.36"  # 行／列证据在分页路径可恢复
    assert evidence[1].locator == (
        "page:1",
        "row:每股收益",
        "col:2026E",
        "cell:每股收益×2026E",
    )


async def test_paged_envelope_without_block_evidence_fails_closed():
    search, fetch = paged_tools(block_evidence=None)
    result = await collect_query(ProductQuery("q", "query"), search=search, fetch=fetch)
    assert result.observation.outcome is ObservationOutcome.FAILED
    assert "block evidence" in (result.error or "")


async def test_paged_envelope_with_unresolved_members_fails_closed():
    search, fetch = paged_tools(block_evidence=_default_block_evidence())
    original = fetch.payload

    def payload(args):
        body = original(args)
        body["unresolved"] = ["chunk:c"]
        return body

    fetch.payload = payload
    result = await collect_query(ProductQuery("q", "query"), search=search, fetch=fetch)
    assert result.observation.outcome is ObservationOutcome.FAILED


async def test_paged_fragments_with_gaps_fail_closed():
    search, fetch = paged_tools(block_evidence=_default_block_evidence())
    original = fetch.payload

    def payload(args):
        body = original(args)
        if "cursor" not in args:
            body["items"][0]["fragment"]["end"] = 9  # 制造覆盖缺口
        return body

    fetch.payload = payload
    result = await collect_query(ProductQuery("q", "query"), search=search, fetch=fetch)
    assert result.observation.outcome is ObservationOutcome.FAILED


def tools():
    hit = {
        "source_id": "s",
        "build_id": "b",
        "chunk_id": "c",
        "doc_id": "cv2:b",
        "locator": "chunk:c",
    }
    return FakeTool({"ok": True, "hits": [hit]}), FakeTool(
        {
            "ok": True,
            **hit,
            "text": "每股收益\n2026E\n0.36",
            "units": [
                {"unit_id": "u1", "page": 1},
                {"unit_id": "u2", "page": 1},
            ],
            "spans": [
                {"unit_id": "u1", "start": 0, "end": 10},
                {"unit_id": "u2", "start": 11, "end": 15},
            ],
            "semantic_cells": [
                {
                    "unit_id": "u2",
                    "page": 1,
                    "row": "每股收益",
                    "col": "2026E",
                    "text": "0.36",
                }
            ],
        }
    )


@pytest.mark.parametrize("qid", ["positive-001", "no-answer-001"])
async def test_every_query_executes_same_registered_path(qid):
    search, fetch = tools()
    result = await collect_query(
        ProductQuery(qid, "原始问题，含什么？"), search=search, fetch=fetch
    )
    assert search.calls == [{"query": "原始问题，含什么？", "limit": 10}]
    assert len(fetch.calls) == 1
    assert result.observation.outcome is ObservationOutcome.OK
    assert result.observation.documents[0].evidence[0].text == "每股收益\n2026E\n0.36"


async def test_verified_semantic_cells_become_scoring_evidence():
    search, fetch = tools()
    result = await collect_query(ProductQuery("q", "query"), search=search, fetch=fetch)
    evidence = result.observation.documents[0].evidence
    assert evidence[1].text == "0.36"
    assert evidence[1].locator == (
        "page:1",
        "row:每股收益",
        "col:2026E",
        "cell:每股收益×2026E",
    )


async def test_context_locators_are_fetched_once_and_assembled_in_order():
    hit = {
        "source_id": "s",
        "build_id": "b",
        "chunk_id": "c2",
        "doc_id": "cv2:b",
        "locator": "chunk:c2",
        "context_locators": ["chunk:c1", "chunk:c2"],
    }
    search = FakeTool({"ok": True, "hits": [hit]})

    def payload(args):
        chunk = args["locator"].split(":", 1)[1]
        return {
            "ok": True,
            "source_id": "s",
            "build_id": "b",
            "chunk_id": chunk,
            "doc_id": "cv2:b",
            "locator": args["locator"],
            "text": "甲" if chunk == "c1" else "乙",
            "units": [{"unit_id": f"u-{chunk}", "page": 1}],
            "semantic_cells": [],
        }

    fetch = FakeTool(payload)
    result = await collect_query(ProductQuery("q", "query"), search=search, fetch=fetch)
    assert result.observation.outcome is ObservationOutcome.OK
    assert fetch.calls == [
        {"doc_id": "cv2:b", "locator": "chunk:c1"},
        {"doc_id": "cv2:b", "locator": "chunk:c2"},
    ]
    assert result.observation.documents[0].evidence[0].text == "甲\n乙"


@pytest.mark.parametrize(
    "mutation",
    [
        {"unit_id": "unknown"},
        {"unit_id": "u1"},
        {"text": "not in authority text"},
        {"page": 99},
    ],
)
async def test_semantic_cells_fail_closed_on_authority_mismatch(mutation):
    search, fetch = tools()
    fetch.payload["semantic_cells"][0].update(mutation)
    result = await collect_query(ProductQuery("q", "query"), search=search, fetch=fetch)
    assert result.observation.outcome is ObservationOutcome.FAILED


@pytest.mark.parametrize(
    "payload,outcome",
    [
        ({"ok": True, "hits": []}, ObservationOutcome.NO_MATCH),
        ({"ok": False, "hits": []}, ObservationOutcome.FAILED),
        ({"ok": True}, ObservationOutcome.FAILED),
    ],
)
async def test_no_match_and_failure_are_distinct(payload, outcome):
    search = FakeTool(payload)
    fetch = FakeTool({})
    result = await collect_query(ProductQuery("q", "query"), search=search, fetch=fetch)
    assert result.observation.outcome is outcome
    assert not fetch.calls


@pytest.mark.parametrize(
    "field,value", [("source_id", "other"), ("build_id", "new"), ("chunk_id", "other")]
)
async def test_fetch_identity_mismatch_fails_closed(field, value):
    search, fetch = tools()
    fetch.payload[field] = value
    result = await collect_query(ProductQuery("q", "query"), search=search, fetch=fetch)
    assert result.observation.outcome is ObservationOutcome.FAILED
    assert not result.observation.documents


async def test_fetch_failure_is_not_an_abstention():
    search, fetch = tools()
    fetch.payload = {"ok": False}
    result = await collect_query(ProductQuery("q", "query"), search=search, fetch=fetch)
    assert result.observation.outcome is ObservationOutcome.FAILED


@pytest.mark.parametrize("limit", [0, 21, 2000, True])
async def test_cannot_silently_use_private_candidate_limit(limit):
    search, fetch = tools()
    with pytest.raises(ValueError):
        await collect_query(ProductQuery("q", "query"), search=search, fetch=fetch, limit=limit)
    assert not search.calls
