"""Search evidence must survive the wire boundary and authoritative verification."""

import importlib
import json
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import pytest

from plugins.corpus.ledger import ConsumptionLedger, verify_manifest
from plugins.corpus.retrieval import native_live
from plugins.corpus.retrieval.display import compose, compose_with_evidence
from plugins.corpus.retrieval.embedding import text_hash
from plugins.corpus.retrieval.native import NativeBlock, NativeSpan
from plugins.corpus.search_evidence import SEARCH_EVIDENCE_CONTRACT, search_evidence_items
from plugins.corpus.service import SearchHit
from plugins.tools.corpus_search import NATIVE_HINT, corpus_search, fit_search_payload

FIXTURES = json.loads((Path(__file__).parent / "fixtures/corpus_display_context.json").read_text())


def _hit(blocks, query, lexemes=(), chars=600):
    snippet, spans = compose_with_evidence(
        blocks, query, lexemes=lexemes, max_blocks=2, chars_per_block=chars
    )
    locators = tuple(
        native_live.locator_for(b.chunk_id, b.text, [asdict(s) for s in b.slices]) for b in blocks
    )
    return SearchHit(
        doc_id="cv2:" + blocks[0].build_id,
        locator=locators[0],
        title="test",
        snippet=snippet,
        score=1.0,
        published="2026-10-23",
        source_id=blocks[0].source_id,
        build_id=blocks[0].build_id,
        chunk_id=blocks[0].chunk_id,
        context_locators=locators,
        scope_id="scope:" + blocks[0].build_id,
        evidence_spans=spans,
    )


def _block(text="价格挂钩批价，平抑波动。", build="a", chunk="c1"):
    return NativeBlock(
        "source:" + build,
        build,
        chunk,
        None,
        text,
        (NativeSpan("u", 1, 0, len(text), text_hash(text)),),
        (len(text),),
    )


def _body(*hits):
    return json.dumps(
        {
            "ok": True,
            "hits": [
                {**asdict(hit), "evidence_contract": SEARCH_EVIDENCE_CONTRACT} for hit in hits
            ],
            "coverage": {"native": {"policy": "native1"}},
            "hint": NATIVE_HINT,
        },
        ensure_ascii=False,
    )


def _messages(body, role="tool"):
    return [{"role": role, "name": "corpus_search", "content": body}]


def _verify(ledger, hit, quote, source):
    manifest = {
        "conclusions": [
            {
                "id": "C1",
                "evidence": [
                    {
                        "doc_id": hit.doc_id,
                        "locator": hit.locator,
                        "quote": quote,
                        "purpose": "value",
                    }
                ],
            }
        ]
    }
    return verify_manifest(manifest, ledger, resolver=lambda doc, loc: source)["status"]


@pytest.mark.parametrize("case", FIXTURES, ids=lambda case: case["id"])
async def test_real_examples_tool_to_manifest_without_fetch(monkeypatch, case):
    blocks = [
        NativeBlock(**{**b, "slices": tuple(NativeSpan(**s) for s in b["slices"])})
        for b in case["blocks"]
    ]
    hit = _hit(blocks, case["query"], case["lexemes"])
    assert hit.snippet == compose(
        blocks, case["query"], lexemes=case["lexemes"], max_blocks=2, chars_per_block=600
    )
    # Exposes only search; a tool fetch would fail this integration test.
    svc = SimpleNamespace(search_with_coverage=lambda *a, **kw: ([hit], {"native": True}))
    monkeypatch.setattr(
        importlib.import_module("plugins.tools.corpus_search"), "get_service", lambda: svc
    )
    raw = await corpus_search.func(case["query"])
    final = fit_search_payload(raw, 12000)
    payload = json.loads(final)
    wire = payload["hits"][0]
    assert wire["context_locators"] == list(hit.context_locators)
    assert wire["locator"] == hit.locator
    ledger = ConsumptionLedger()
    ledger.record_search(raw)
    ledger.finalize(_messages(final))
    assert not ledger.requested
    items = search_evidence_items(wire)
    assert items
    conclusions = []
    sources = dict(zip(hit.context_locators, (b.text for b in blocks), strict=True))
    for i, item in enumerate(items):
        start, end = item["fragment"].values()
        assert sources[item["locator"]][start:end] == item["text"]
        conclusions.append(
            {
                "id": f"C{i}",
                "evidence": [
                    {
                        "doc_id": hit.doc_id,
                        "locator": item["locator"],
                        "quote": item["text"],
                    }
                ],
            }
        )
    verified = verify_manifest(
        {"conclusions": conclusions}, ledger, resolver=lambda doc, loc: sources[loc]
    )
    assert verified["status"] == "verified"
    assert not ledger.all_offered_fetched()  # excerpts are not the complete 19/20-block scope
    assert all(r["retrieved_via"] == ["corpus_search"] for r in ledger.to_dict()["fetched"])


def test_budget_dropped_hit_cannot_borrow_identical_retained_text():
    first, second = (_hit([_block(build=b)], "价格") for b in ("a", "b"))
    raw = _body(first, second)
    ledger = ConsumptionLedger()
    ledger.record_search(raw)
    # Enough for one intact hit with all descriptors; forces whole-hit elision.
    final = fit_search_payload(raw, 1800)
    payload = json.loads(final)
    assert payload["ok"] and payload["hits_elided"] == 1
    assert payload["hits"][0]["evidence_spans"] == list(first.evidence_spans)
    ledger.finalize(_messages(final))
    assert _verify(ledger, first, "价格挂钩批价", _block().text) == "verified"
    assert _verify(ledger, second, "价格挂钩批价", _block().text) == "partial"


@pytest.mark.parametrize("mutation", ["legacy", "hash", "offset", "member", "version", "type"])
def test_invalid_descriptor_and_legacy_preview_never_register(mutation):
    hit = json.loads(_body(_hit([_block()], "价格")))["hits"][0]
    if mutation == "legacy":
        hit.pop("evidence_contract")
    elif mutation == "version":
        hit["doc_id"] = "cv2:other"
    else:
        key, value = {
            "hash": ("quote_sha256", "0" * 64),
            "offset": ("snippet_end", 9999),
            "member": ("member", 2),
            "type": ("start", True),
        }[mutation]
        hit["evidence_spans"][0][key] = value
    assert not search_evidence_items(hit)
    ledger = ConsumptionLedger()
    ledger.record_search(json.dumps({"ok": True, "hits": [hit]}))
    assert not ledger.fetched


@pytest.mark.parametrize(
    "mode", ["user", "assistant", "broken_json", "wrong_handle", "metadata_lost"]
)
def test_only_intact_tool_delivery_counts(mode):
    hit = _hit([_block()], "价格")
    body = _body(hit)
    ledger = ConsumptionLedger()
    ledger.record_search(body)
    role = mode if mode in {"user", "assistant"} else "tool"
    if mode == "broken_json":
        body = body[:-1]
    elif mode in {"wrong_handle", "metadata_lost"}:
        payload = json.loads(body)
        wire = payload["hits"][0]
        if mode == "wrong_handle":
            wire["context_locators"][0] += "changed"
        else:
            wire.pop("evidence_spans")
        body = json.dumps(payload, ensure_ascii=False)
    ledger.finalize(_messages(body, role))
    assert _verify(ledger, hit, "价格挂钩批价", _block().text) == "partial"


def test_partial_sentence_has_no_citable_range():
    hit = _hit([_block("价格" + "波动" * 80 + "。")], "价格", chars=20)
    assert "上下文不完整" in hit.snippet
    assert not hit.evidence_spans


def test_search_then_fetch_preserves_scope_and_merges_delivery():
    block = _block("背景资料。\n价格挂钩批价，平抑波动。\n必要限定条件。")
    hit = _hit([block], "价格", chars=16)
    body = _body(hit)
    ledger = ConsumptionLedger()
    ledger.record_search(body)
    ledger.finalize(_messages(body))
    assert not ledger.all_offered_fetched()
    assert _verify(ledger, hit, "必要限定条件", block.text) == "partial"
    fetch = json.dumps(
        {
            "ok": True,
            "doc_id": hit.doc_id,
            "locator": hit.locator,
            "build_id": block.build_id,
            "text": block.text,
        },
        ensure_ascii=False,
    )
    ledger.record_fetch_call({"doc_id": hit.doc_id, "locator": hit.locator})
    ledger.record_fetch_result(fetch)
    ledger.finalize([{"role": "tool", "name": "corpus_fetch", "content": fetch}])
    assert _verify(ledger, hit, "必要限定条件", block.text) == "verified"
    assert ledger.all_offered_fetched()
    assert len(ledger.offered) == 1 and len(ledger.requested) == 1


def test_repeated_search_same_scope_adds_new_evidence_without_inflating_scope():
    block = _block("价格挂钩批价。\n可靠性提高十倍。")
    ledger = ConsumptionLedger()
    for query in ("价格", "可靠性", "价格"):
        body = _body(_hit([block], query, chars=12))
        ledger.record_search(body)
        ledger.finalize(_messages(body))
    assert len(ledger.offered) == 1 and len(ledger.fetched) == 2
    assert not ledger.requested


def test_search_evidence_still_needs_authoritative_current_source():
    hit = _hit([_block()], "价格")
    ledger = ConsumptionLedger()
    ledger.record_search(_body(hit))
    ledger.finalize(_messages(_body(hit)))
    assert _verify(ledger, hit, "价格挂钩批价", None) == "unsupported"
    assert _verify(ledger, hit, "价格挂钩批价", "来源已变化") == "unsupported"
    assert _verify(ledger, hit, "编造的引文", _block().text) == "unsupported"


def test_repeated_quote_uses_delivered_occurrence():
    block = _block("旧记录价格挂钩批价。最新记录价格挂钩批价。")
    hit = _hit([block], "最新记录", chars=15)
    assert hit.evidence_spans[0]["start"] > 0
    ledger = ConsumptionLedger()
    ledger.record_search(_body(hit))
    ledger.finalize(_messages(_body(hit)))
    assert _verify(ledger, hit, "价格挂钩批价", block.text) == "verified"


def test_later_fetch_of_same_interval_needs_its_own_delivery():
    block = _block()
    hit = _hit([block], "价格")
    ledger = ConsumptionLedger()
    ledger.record_search(_body(hit))
    fetch = json.dumps(
        {
            "ok": True,
            "doc_id": hit.doc_id,
            "locator": hit.locator,
            "build_id": block.build_id,
            "text": block.text,
        },
        ensure_ascii=False,
    )
    ledger.record_fetch_result(fetch)
    ledger.finalize([{"role": "assistant", "content": fetch}])
    assert _verify(ledger, hit, "价格挂钩批价", block.text) == "partial"
    ledger.finalize([{"role": "tool", "name": "corpus_fetch", "content": fetch}])
    assert _verify(ledger, hit, "价格挂钩批价", block.text) == "verified"
    assert len(ledger.fetched) == 1


def test_first_and_last_excerpts_do_not_cover_omitted_middle():
    block = _block("价格甲。未展示的背景说明。价格乙。")
    hit = _hit([block], "价格", chars=10)
    assert len(hit.evidence_spans) == 2
    ledger = ConsumptionLedger()
    ledger.record_search(_body(hit))
    ledger.finalize(_messages(_body(hit)))
    assert not ledger.all_offered_fetched()
    assert _verify(ledger, hit, "未展示的背景说明", block.text) == "partial"
