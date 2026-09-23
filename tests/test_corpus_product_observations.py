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
        return json.dumps(self.payload)


def tools():
    hit = {
        "source_id": "s",
        "build_id": "b",
        "chunk_id": "c",
        "doc_id": "cv2:b",
        "locator": "chunk:c",
    }
    return FakeTool({"ok": True, "hits": [hit]}), FakeTool(
        {"ok": True, **hit, "text": "真实原文", "units": [{"page": 1}]}
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
    assert result.observation.documents[0].evidence[0].text == "真实原文"


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
