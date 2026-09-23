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
