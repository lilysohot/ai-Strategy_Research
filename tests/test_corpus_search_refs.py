"""Compact receipts preserve scope, delivery boundaries and live-source verification."""

import copy
import importlib
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from plugins.corpus.ledger import ConsumptionLedger, verify_manifest
from plugins.corpus.retrieval.embedding import text_hash
from plugins.corpus.search_evidence import SEARCH_EVIDENCE_CONTRACT, search_evidence_items
from plugins.corpus.search_refs import (
    SearchReferenceError,
    canonical_locator,
    compact_hit,
    offered_hit,
    resolve_scope,
)
from plugins.tools.corpus_search import fit_search_payload


def original(build="a", text="认证周期构成优势。"):
    build = build * 64
    locator = f"chunk:native1/{build[:16]}%3Abody%3A0001/0123456789abcdef"
    return {
        "doc_id": "cv2:" + build,
        "build_id": build,
        "source_id": build,
        "locator": locator,
        "chunk_id": "body:0001",
        "scope_id": "scope:" + build,
        "context_locators": [locator, locator.replace("0001", "0002")],
        "by_kind": {"body": 2},
        "total_chunks": 2,
        "title": "竞争优势",
        "published": "2026-10-24",
        "snippet": text,
        "evidence_contract": SEARCH_EVIDENCE_CONTRACT,
        "evidence_spans": [
            {
                "member": 1,
                "start": 0,
                "end": len(text),
                "snippet_start": 0,
                "snippet_end": len(text),
                "text_chars": len(text),
                "text_sha256": text_hash(text),
                "quote_sha256": text_hash(text),
            }
        ],
    }


def body(*hits):
    return json.dumps(
        {
            "ok": True,
            "count": len(hits),
            "hits": hits,
            "coverage": {"native": {"policy": "native1"}},
        },
        ensure_ascii=False,
    )


def messages(payload, role="tool"):
    return [{"role": role, "name": "corpus_search", "content": payload}]


def verify(ledger, hit, resolve):
    return verify_manifest(
        {
            "conclusions": [
                {
                    "id": "C1",
                    "evidence": [
                        {
                            "doc_id": hit["doc_id"],
                            "locator": hit["excerpts"][0]["ref"],
                            "quote": hit["excerpts"][0]["text"],
                        }
                    ],
                }
            ]
        },
        ledger,
        resolver=resolve,
    )["status"]


def test_compact_evidence_and_hidden_scope_survive_new_process():
    full = original(text="认证🙂周期\n构成优势。")
    hit = compact_hit(full)
    assert "context_locators" not in hit and "evidence_spans" not in hit and "by_kind" not in hit
    assert search_evidence_items(hit) == search_evidence_items(full)
    assert offered_hit(hit) == full
    code = (
        "import json,sys; from plugins.corpus.search_evidence import search_evidence_items; "
        "from plugins.corpus.search_refs import offered_hit; h=json.load(sys.stdin); "
        "print(json.dumps([search_evidence_items(h),offered_hit(h)],ensure_ascii=False))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        input=json.dumps(hit),
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(result.stdout) == [search_evidence_items(full), full]


@pytest.mark.parametrize("mutation", ["text", "truncate", "ref", "scope", "doc", "no_text"])
def test_damaged_or_rebound_wire_never_grants_evidence(mutation):
    hit = compact_hit(original())
    bad = copy.deepcopy(hit)
    if mutation == "text":
        bad["excerpts"][0]["text"] = "编造结论。"
    elif mutation == "truncate":
        bad["excerpts"][0]["text"] = bad["excerpts"][0]["text"][:-1]
    elif mutation == "ref":
        bad["excerpts"][0]["ref"] = compact_hit(original("b"))["excerpts"][0]["ref"]
    elif mutation == "scope":
        bad["scope_ref"] = compact_hit(original("b"))["scope_ref"]
    elif mutation == "doc":
        bad["doc_id"] = "cv2:" + "b" * 64
    else:
        bad["excerpts"] = [{"ref": bad["excerpts"][0]["ref"]}]
    assert not search_evidence_items(bad)
    ledger = ConsumptionLedger()
    ledger.record_search(body(hit))
    ledger.finalize(messages(body(bad)))
    assert verify(ledger, hit, lambda *a: original()["snippet"]) == "partial"


@pytest.mark.parametrize("damage", ["missing", "corrupt", "target"])
def test_reference_storage_failures_are_explicit(monkeypatch, damage):
    hit = compact_hit(original())
    path = Path(os.environ["CORPUS_SEARCH_REF_ROOT"]) / (hit["scope_ref"][5:] + ".json")
    if damage == "missing":
        path.unlink()
    elif damage == "corrupt":
        path.write_text("{}")
    else:
        monkeypatch.setenv("CORPUS_TARGET_DB", "different-target")
    assert not search_evidence_items(hit)
    with pytest.raises(SearchReferenceError):
        canonical_locator(hit["doc_id"], hit["excerpts"][0]["ref"])


def test_short_ref_citation_needs_actual_delivery_and_live_authority():
    full = original()
    hit = compact_hit(full)
    ledger = ConsumptionLedger()
    ledger.record_search(body(hit))
    # Stored complete scope is offered, not read. A summary cannot acknowledge it.
    assert ledger.offered[0]["locators"] == full["context_locators"]
    ledger.finalize(messages(body(hit), "assistant"))
    assert verify(ledger, hit, lambda *a: full["snippet"]) == "partial"
    ledger.finalize(messages(body(hit)))
    assert verify(ledger, hit, lambda *a: full["snippet"]) == "verified"
    assert not ledger.all_offered_fetched()
    assert verify(ledger, hit, lambda *a: None) == "unsupported"  # withdrawn/missing source


async def test_manifest_selects_search_excerpt_without_recopying_text(monkeypatch, tmp_path):
    from plugins.corpus.ledger import get_run_ledger, reset_run_ledgers
    from plugins.tools import corpus_manifest

    monkeypatch.setenv("APODEX_RUN_DIR", str(tmp_path / "run"))
    reset_run_ledgers()
    full = original(text=" 光学器件直接焊接在\nNVLink\u00a07\u00a0交换机托盘上。\n")
    hit = compact_hit(full)
    ledger = get_run_ledger()
    ledger.record_search(body(hit))
    ledger.finalize(messages(body(hit)))
    monkeypatch.setattr(corpus_manifest, "get_service", lambda: SimpleNamespace(
        fetch_verbatim=lambda d, loc: SimpleNamespace(text=full["snippet"]),
    ))
    out = json.loads(await corpus_manifest.corpus_submit_manifest.func(conclusions=[{
        "report_quote": "光学器件的位置", "evidence": [{
            "evidence_ref": hit["excerpts"][0]["ref"], "purpose": "value",
        }],
    }]))
    assert out["publish_status"] == "verified"
    match = out["conclusions"][0]["matched_evidence"][0]
    assert match["quote"] == full["snippet"]  # including leading/trailing whitespace
    assert match["locator"] == full["locator"]
    assert (match["start"], match["end"]) == (0, len(full["snippet"]))


def test_budget_elision_does_not_deliver_receipt_text():
    first, second = (compact_hit(original(b, "价格" * 250 + "。")) for b in ("a", "b"))
    raw = body(first, second)
    final = fit_search_payload(raw, len(body(first)) + 350)
    parsed = json.loads(final)
    assert parsed["ok"] and len(parsed["hits"]) == 1
    assert parsed["hits"][0]["excerpts"] == first["excerpts"]
    ledger = ConsumptionLedger()
    ledger.record_search(raw)
    ledger.finalize(messages(final))
    assert verify(ledger, first, lambda *a: first["excerpts"][0]["text"]) == "verified"
    assert verify(ledger, second, lambda *a: second["excerpts"][0]["text"]) == "partial"


async def test_storage_unavailable_returns_self_contained_v1(monkeypatch):
    refs = importlib.import_module("plugins.corpus.search_refs")
    search = importlib.import_module("plugins.tools.corpus_search")
    full = original()
    obj = SimpleNamespace(**{**full, "context_by_kind": (("body", 2),)})
    monkeypatch.setattr(
        search,
        "get_service",
        lambda: SimpleNamespace(search_with_coverage=lambda *a, **k: ([obj], {"native": True})),
    )

    def denied(*args):
        raise PermissionError("receipt storage unavailable")

    monkeypatch.setattr(refs, "_store", denied)
    result = json.loads(await search.corpus_search.func("竞争优势"))
    assert result["reference_storage"] == "unavailable_v1_fallback"
    assert result["hits"][0]["evidence_contract"] == SEARCH_EVIDENCE_CONTRACT
    assert search_evidence_items(result["hits"][0]) == search_evidence_items(full)


async def test_fetch_resolves_reference_before_live_read_and_records_canonical_request(monkeypatch):
    fetch = importlib.import_module("plugins.tools.corpus_fetch")
    full = original()
    hit = compact_hit(full)
    calls = []

    def withdrawn(doc_id, locator):
        calls.append((doc_id, locator))
        raise ValueError("source withdrawn")

    monkeypatch.setattr(fetch, "get_service", lambda: SimpleNamespace(fetch_verbatim=withdrawn))
    args = {"doc_id": hit["doc_id"], "locator": hit["excerpts"][0]["ref"]}
    result = json.loads(await fetch.corpus_fetch.func(**args))
    assert not result["ok"] and calls == [(full["doc_id"], full["locator"])]
    ledger = ConsumptionLedger()
    ledger.record_fetch_call(args)
    assert ledger.requested[0]["locators"] == [full["locator"]]
    assert not ledger.fetched


async def test_inventory_expands_exact_scope_and_rejects_wrong_document(monkeypatch):
    module = importlib.import_module("plugins.tools.corpus_inventory")
    full = original()
    hit = compact_hit(full)
    calls = []

    def inventory(doc_id, locators):
        calls.append((doc_id, locators))
        raise ValueError("stop after validating exact scope")

    monkeypatch.setattr(module, "get_service", lambda: SimpleNamespace(context_inventory=inventory))
    await module.corpus_inventory.func(hit["doc_id"], scope_ref=hit["scope_ref"])
    assert calls == [(full["doc_id"], full["context_locators"])]
    bad = json.loads(
        await module.corpus_inventory.func("cv2:" + "b" * 64, scope_ref=hit["scope_ref"])
    )
    assert not bad["ok"] and len(calls) == 1


def test_partial_preview_remains_available_but_cannot_be_cited():
    full = original()
    full["snippet"] += "\n【2/2】〔原文字符0:3；句内节选，上下文不完整〕未完句"
    hit = compact_hit(full)
    assert "未完句" in hit["preview"]
    assert "未完句" not in "".join(item["text"] for item in search_evidence_items(hit))
    assert resolve_scope(hit["doc_id"], hit["scope_ref"]) == full


def test_native_inventory_keeps_projection_handles_and_checks_live_source(monkeypatch):
    from plugins.corpus.service import CorpusService

    full = original()
    svc = CorpusService(dsn_url="postgresql://unused")
    calls = []

    def fetch(doc_id, locator):
        calls.append((doc_id, locator))
        return SimpleNamespace(
            chunk_id=locator,
            kind="body",
            title_text="章节",
            section_path=("章节",),
            units=(SimpleNamespace(page=3),),
        )

    monkeypatch.setattr(svc, "fetch_verbatim", fetch)
    result = svc.context_inventory(full["doc_id"], full["context_locators"])
    assert [member["locator"] for member in result["members"]] == full["context_locators"]
    assert calls == [(full["doc_id"], loc) for loc in full["context_locators"]]
    assert result["total_chunks"] == 2 and result["unknown_members"] == []
    assert all(member["relations"] == [] for member in result["members"])

    def withdrawn(*args):
        raise ValueError("source withdrawn or hash mismatch")

    monkeypatch.setattr(svc, "fetch_verbatim", withdrawn)
    with pytest.raises(ValueError, match="withdrawn"):
        svc.context_inventory(full["doc_id"], full["context_locators"])
