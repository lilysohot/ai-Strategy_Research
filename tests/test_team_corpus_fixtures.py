"""Production corpus protocol against fixed benchmark data, without an LLM."""

import json

import pytest

from benchmarks.team_workflow.corpus_fixtures import fixed_corpus_tools, measure_corpus
from benchmarks.team_workflow.run import catalog
from plugins.corpus.ledger import ConsumptionLedger, verify_manifest


def case(key):
    return next(c for c in catalog() if c["id"] == key)


async def call(tools, name, **kwargs):
    return json.loads(await tools[name].func(**kwargs))


async def test_real_excerpt_receipt_and_authority_binding(tmp_path):
    with fixed_corpus_tools(case("F18"), tmp_path, "A") as tools:
        assert not {"web_search", "web_fetch", "bash", "read_file"} & tools.keys()
        result = await call(tools, "corpus_search", query="轨道算力")
        excerpt = result["hits"][0]["excerpts"][0]
        ledger = ConsumptionLedger()
        raw = json.dumps(result, ensure_ascii=False)
        ledger.record_search(raw)
        ledger.finalize([{"role": "tool", "name": "corpus_search", "content": raw}])
        import plugins.corpus.service as service

        verified = verify_manifest(
            {
                "conclusions": [
                    {
                        "id": "c1",
                        "evidence": [
                            {
                                "doc_id": result["hits"][0]["doc_id"],
                                "locator": excerpt["ref"],
                                "quote": excerpt["text"],
                            }
                        ],
                    }
                ]
            },
            ledger,
            resolver=lambda d, loc: service.get_service().fetch_verbatim(d, loc).text,
        )
        assert verified["status"] == "verified"
        import psycopg

        with pytest.raises(RuntimeError, match="forbids DB"):
            psycopg.connect("")


@pytest.mark.parametrize("key", ["F18", "F22"])
async def test_ab_changes_only_the_short_hint_and_preview_stays_non_evidence(tmp_path, key):
    outputs = []
    for arm in ("A", "B"):
        out = tmp_path / arm
        out.mkdir()
        with fixed_corpus_tools(case(key), out, arm) as tools:
            result = await call(tools, "corpus_search", query="轨道算力")
            if key == "F22":
                assert not result["hits"][0]["excerpts"]
                assert result["hits"][0]["preview"]
            outputs.append(result)
    first, second = outputs[0].pop("hint"), outputs[1].pop("hint")
    assert (first != second) == (key == "F18")
    assert outputs[0] == outputs[1]


async def test_document_pages_reconstruct_every_unit_and_candidate_scope_is_smaller(tmp_path):
    import plugins.corpus.service as service

    with fixed_corpus_tools(case("F20"), tmp_path, "A") as tools:
        doc = case("F20")["sources"][0]["doc_id"]
        expected = service.get_service().document_units(doc)
        search = await call(tools, "corpus_search", query="轨道算力")
        inventory = await call(
            tools, "corpus_inventory", doc_id=doc, scope_ref=search["hits"][0]["scope_ref"]
        )
        assert inventory["exhausted"] and inventory["total_chunks"] == 2
        actual = {}
        args = {"scope": "document"}
        pages = 0
        while True:
            page = await call(tools, "corpus_fetch", doc_id=doc, **args)
            assert page["ok"]
            pages += 1
            assert pages < 30
            for item in page["items"]:
                actual[item["unit_id"]] = actual.get(item["unit_id"], "") + item["text"]
            if not page["next_cursor"]:
                assert page["fetch_complete"]
                break
            args = {"cursor": page["next_cursor"]}
        assert pages > 1
        assert actual == {item.unit.unit_id: item.unit.raw_text for item in expected.units}
        metrics = measure_corpus(tmp_path)
        assert metrics["document_pages_returned"] == pages
        assert metrics["document_completion_returns"] == 1
        assert metrics["exact_repeated_requests"] == 0
        assert metrics["repeated_original_chars"] == len(expected.units[0].unit.raw_text)


def test_ab_runner_interleaves_48_samples_and_stops_after_two_errors(tmp_path, monkeypatch):
    import argparse
    from pathlib import Path

    from benchmarks.team_workflow import run as runner

    launches = []

    class FailedWorker:
        def __init__(self, command, **kwargs):
            launches.append(command)
            trial = Path(command[command.index("--out") + 1])
            runner.write(trial / "worker.json", {"ok": False, "error": "test provider failure"})

        def wait(self, timeout):
            return 0

    monkeypatch.setattr(runner.subprocess, "Popen", FailedWorker)
    monkeypatch.setattr(runner, "source_fingerprint", lambda: {"test": True})
    out = tmp_path / "ab"
    runner.run(
        argparse.Namespace(
            layer="frozen",
            case=[f"F{i}" for i in range(18, 26)],
            repeats=3,
            hint_ab=True,
            profile="default",
            max_consecutive_errors=2,
            out=out,
        )
    )
    manifest = json.loads((out / "manifest.json").read_text())
    assert len(manifest["samples"]) == 48
    assert [s["sample"] for s in manifest["samples"][:2]] == ["F18-A-r1", "F18-B-r1"]
    assert [s["sample"] for s in manifest["samples"][16:18]] == ["F18-B-r2", "F18-A-r2"]
    assert len(launches) == 2
    assert [c[c.index("--hint-arm") + 1] for c in launches] == ["A", "B"]
    assert runner.summarize(out)["states"] == {"error": 2, "unassessed": 46}


async def test_withdrawal_closes_search_inventory_local_and_document_reads(tmp_path):
    with fixed_corpus_tools(case("F24"), tmp_path, "A") as tools:
        doc = case("F24")["sources"][0]["doc_id"]
        search = await call(tools, "corpus_search", query="轨道算力")
        hit = search["hits"][0]
        page = await call(tools, "corpus_fetch", doc_id=doc, scope="document")
        assert page["ok"] and not page["fetch_complete"]
        for name, args in [
            ("corpus_search", {"query": "new query"}),
            ("corpus_fetch", {"doc_id": doc, "scope": "document"}),
            ("corpus_fetch", {"doc_id": doc, "cursor": page["next_cursor"]}),
            ("corpus_fetch", {"doc_id": doc, "locator": hit["excerpts"][0]["ref"]}),
            ("corpus_inventory", {"doc_id": doc, "scope_ref": hit["scope_ref"]}),
        ]:
            response = await call(tools, name, **args)
            assert not response["ok"] and "source_withdrawn" in response["error"]
        metrics = measure_corpus(tmp_path)
        assert metrics["document_pages_returned"] == 1
        assert metrics["document_failure_returns"] == 2
        assert metrics["document_completion_returns"] == 0


def test_direct_corpus_delivery_does_not_inherit_web_teamwork_gate():
    from benchmarks.team_workflow.run import frozen_result

    worker = {"ok": True, "elapsed_s": 1, "result": {"final_answer": "已读完库内全文。"}}
    metrics = {
        "available": True,
        "agents": [{}],
        "known_prompt_tokens": 100,
        "attempts": 1,
        "max_prompt_tokens": 100,
        "exact_repeated_tool_requests": 0,
        "unknown_usage_attempts": 0,
    }
    assert frozen_result(worker, metrics, case("F20"))["status"] == "needs_review"
    legacy = frozen_result(worker, metrics, case("F04"))
    assert "no member execution observed" in legacy["hard_failures"]
