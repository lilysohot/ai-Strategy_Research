"""Model-selected receipts preserve exact source text and pagination state."""

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from plugins.corpus.ledger import get_run_ledger, reset_run_ledgers, verify_manifest
from plugins.corpus.preparation import read_pg
from plugins.corpus.service import emit_cells_from_units

fetch = importlib.import_module("plugins.tools.corpus_fetch")
manifest = importlib.import_module("plugins.tools.corpus_manifest")
DOC = "cv2:" + "a" * 64
LOC = "chunk:native1/aaaaaaaaaaaaaaaa%3Abody%3A0050/0123456789abcdef"
TEXT = "Lightmatter\u00a0还联手\n富士康推出 Open Silicon\n35 / 37\nPhotonics。🙂"


@pytest.fixture
def sources(tmp_path, monkeypatch):
    monkeypatch.setenv("APODEX_RUN_DIR", str(tmp_path / "run"))
    monkeypatch.setenv("CORPUS_TOOL_REF_ROOT", str(tmp_path / "refs"))
    reset_run_ledgers()
    blocks = {}

    class Service:
        def fetch_verbatim(self, doc_id, locator):
            assert doc_id == DOC
            text = blocks[locator]
            base = read_pg.ChunkEvidence(
                source_id="src",
                build_id="a" * 64,
                chunk_id=locator[6:],
                kind="body",
                title_text=None,
                section_path=(),
                units=(),
                text="",
                source_ranges=(),
                spans=(),
                active=True,
            )
            return read_pg.with_units(
                base,
                (
                    read_pg.UnitEvidence(
                        unit_id="u1",
                        raw_text=text,
                        page=35,
                        element=None,
                        cells=(),
                    ),
                ),
            )

        def emit_cells(self, evidence):
            return emit_cells_from_units(evidence.units)

        def context_relations(self, *_):
            return {}

    service = Service()
    monkeypatch.setattr(fetch, "get_service", lambda: service)
    monkeypatch.setattr(manifest, "get_service", lambda: service)
    blocks[LOC] = TEXT
    return blocks


async def test_quote_selected_by_id_survives_layout_and_binds_correct_block(sources):
    raw = await fetch.corpus_fetch.func(doc_id=DOC, locator=LOC, view="compact")
    ref = json.loads(raw)["evidence_ref"]
    ledger = get_run_ledger()
    ledger.record_fetch_result(raw)
    ledger.finalize([{"role": "tool", "content": raw}])
    out = json.loads(
        await manifest.corpus_submit_manifest.func(
            conclusions=[
                {
                    "id": "c7",
                    "report_quote": "生态参与",
                    "evidence": [{"evidence_ref": ref}],
                }
            ]
        )
    )
    assert out["publish_status"] == "pending_report"
    assert out["evidence_status"] == "verified"
    match = out["conclusions"][0]["matched_evidence"][0]
    assert (match["locator"], match["quote"]) == (LOC, TEXT)
    saved = json.loads(Path(out["manifest_file"]).read_text())
    assert saved["conclusions"][0]["evidence"][0]["quote"] == TEXT
    sources[LOC] = "原文已不可用"
    assert (
        verify_manifest(saved, ledger, resolver=lambda d, loc: sources[loc])["status"]
        == "unsupported"
    )


async def test_reference_does_not_turn_unseen_text_into_delivered_evidence(sources):
    raw = await fetch.corpus_fetch.func(doc_id=DOC, locator=LOC)
    ledger = get_run_ledger()
    ledger.record_fetch_result(raw)
    ledger.finalize([{"role": "tool", "content": "内容被预算裁剪"}])
    ledger.last_finalized_turn = 0
    out = json.loads(
        await manifest.corpus_submit_manifest.func(
            conclusions=[
                {
                    "evidence": [{"evidence_ref": json.loads(raw)["evidence_ref"]}],
                }
            ]
        )
    )
    assert out["publish_status"] == "partial"
    assert any(p["code"] == "not_delivered" for p in out["conclusions"][0]["problems"])


@pytest.mark.parametrize("override", ["doc_id", "locator", "quote", "source_start"])
async def test_reference_cannot_be_rebound_by_extra_model_fields(sources, override):
    raw = await fetch.corpus_fetch.func(doc_id=DOC, locator=LOC)
    out = json.loads(
        await manifest.corpus_submit_manifest.func(
            conclusions=[
                {
                    "evidence": [
                        {"evidence_ref": json.loads(raw)["evidence_ref"], override: "wrong"}
                    ],
                }
            ]
        )
    )
    assert out["ok"] is False


async def test_short_cursor_persists_and_replays_old_cursor_identically(sources):
    sources[LOC] = TEXT * 200
    raw = await fetch.corpus_fetch.func(doc_id=DOC, locators=[LOC], view="compact", max_chars=2400)
    first = json.loads(raw)
    assert len(raw) <= 2400 and first["items"]
    ref = first["next_cursor"]
    assert len(ref) < 50
    code = (
        "import json,sys; from plugins.corpus.tool_refs import resolve_cursor_reference; "
        "print(json.dumps(resolve_cursor_reference(sys.argv[1])))"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code, ref], capture_output=True, text=True, check=True
    )
    original_cursor = json.loads(proc.stdout)
    kwargs = dict(doc_id=DOC, max_chars=2400)
    second = await fetch.corpus_fetch.func(cursor=ref, **kwargs)
    assert second == await fetch.corpus_fetch.func(cursor=original_cursor, **kwargs)
    assert len(second) <= 2400
    assert (
        json.loads(second)["items"][0]["fragment"]["start"] == first["items"][-1]["fragment"]["end"]
    )
    assert first["items"][0]["evidence_ref"] != json.loads(second)["items"][0]["evidence_ref"]


@pytest.mark.parametrize("damage", ["missing", "corrupt", "target"])
async def test_unavailable_cursor_receipt_is_rejected(sources, monkeypatch, damage):
    sources[LOC] = TEXT * 200
    first = json.loads(await fetch.corpus_fetch.func(doc_id=DOC, locators=[LOC], max_chars=2400))
    ref = first["next_cursor"]
    assert len(ref) < 50
    if damage == "target":
        monkeypatch.setenv("CORPUS_TARGET_DB", "another-database")
    else:
        path = Path(os.environ["CORPUS_TOOL_REF_ROOT"]) / (ref.split(":")[1] + ".json")
        if damage == "missing":
            path.unlink()
        else:
            path.write_text("{}")
    out = json.loads(await fetch.corpus_fetch.func(doc_id=DOC, cursor=ref))
    assert out["ok"] is False and "游标" in out["error"]


async def test_fetch_receipt_can_be_resolved_in_another_process(sources):
    raw = await fetch.corpus_fetch.func(doc_id=DOC, locator=LOC, view="compact")
    ref = json.loads(raw)["evidence_ref"]
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            "import json,sys; from plugins.corpus.tool_refs import resolve_evidence_reference; "
            "print(json.dumps(resolve_evidence_reference(sys.argv[1])))",
            ref,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    evidence = json.loads(proc.stdout)
    assert evidence == {
        "doc_id": DOC,
        "locator": LOC,
        "quote": TEXT,
        "source_start": 0,
        "source_end": len(TEXT),
    }


async def test_storage_failure_retains_usable_inline_contract(sources, monkeypatch):
    from plugins.corpus import tool_refs

    def unavailable(*_):
        raise OSError("read-only receipt store")

    monkeypatch.setattr(tool_refs, "_store", unavailable)
    sources[LOC] = TEXT * 200
    raw = await fetch.corpus_fetch.func(doc_id=DOC, locators=[LOC], max_chars=2400)
    first = json.loads(raw)
    assert len(raw) <= 2400 and first["items"]
    assert "evidence_ref" not in first["items"][0]
    assert first["next_cursor"].startswith("z1_")
    second = json.loads(
        await fetch.corpus_fetch.func(
            doc_id=DOC,
            cursor=first["next_cursor"],
            max_chars=2400,
        )
    )
    assert second["ok"] and second["items"]


def test_receipt_coordinates_cannot_borrow_another_occurrence(sources):
    from plugins.corpus.ledger import ConsumptionLedger

    text = "证据。未读部分。证据。"
    raw = json.dumps(
        {
            "ok": True,
            "doc_id": DOC,
            "build_id": "a" * 64,
            "items": [
                {
                    "locator": LOC,
                    "build_id": "a" * 64,
                    "text": "证据。",
                    "fragment": {"start": 0, "end": 3},
                    "text_chars": len(text),
                }
            ],
        }
    )
    ledger = ConsumptionLedger()
    ledger.record_fetch_result(raw)
    ledger.finalize([{"role": "tool", "content": raw}])
    evidence = {
        "doc_id": DOC,
        "locator": LOC,
        "quote": "证据。",
        "source_start": len(text) - 3,
        "source_end": len(text),
    }
    candidate = {"conclusions": [{"evidence": [evidence]}]}
    out = verify_manifest(candidate, ledger, resolver=lambda *_: text)
    assert out["status"] == "partial"
    assert out["conclusions"][0]["matched_evidence"][0]["start"] == len(text) - 3
    evidence["source_end"] = len(text) + 1
    assert verify_manifest(candidate, ledger, resolver=lambda *_: text)["status"] == "unsupported"


async def test_receipt_size_limit_does_not_break_fetch_or_page_sizing(sources, monkeypatch):
    from plugins.corpus import tool_refs

    monkeypatch.setattr(tool_refs, "_MAX_BYTES", 128)
    raw = await fetch.corpus_fetch.func(doc_id=DOC, locator=LOC)
    out = json.loads(raw)
    assert out["ok"] and out["text"] == TEXT
    assert "evidence_ref" not in out


@pytest.mark.parametrize("repair", [True, False])
async def test_runaway_recovery_repairs_real_manifest_before_publication(sources, monkeypatch, repair):
    from frontier_agent.core.errors import LLMReasoningRunaway
    from frontier_agent.core.llm import LLMResponse
    from frontier_agent.core.loop_types import LoopConfig, LoopPolicy
    from frontier_agent.core.runtime.loop.agent_loop import run_agent_loop
    from plugins.corpus import ledger as ledger_module
    from plugins.corpus.ledger import ConsumptionLedgerObserver, publish_boundary
    from workflows.stateful_react_agent.convergence import ResearchConvergenceObserver

    monkeypatch.setenv("A4_ENFORCE", "1")
    monkeypatch.setattr(ledger_module, "_default_resolver", lambda *_: TEXT)
    verdicts = []

    class Model:
        model = "stub"

        def __init__(self):
            self.count = 0
            self.ref = ""

        async def chat(self, messages, **kwargs):
            self.count += 1
            if self.count == 1:
                name = "corpus_fetch"
                args = {"doc_id": DOC, "locator": LOC, "view": "compact"}
            elif self.count in (2, 4):
                if self.count == 2:
                    self.ref = json.loads(messages[-2]["content"])["evidence_ref"]
                evidence = (
                    {"evidence_ref": self.ref} if self.count == 4 and repair else
                    {"doc_id": DOC, "locator": LOC, "quote": TEXT.replace("\n", " ")}
                )
                name = "corpus_submit_manifest"
                args = {"conclusions": [{"id": "c1", "report_quote": "生态参与",
                                          "evidence": [evidence]}]}
            elif self.count == 3:
                verdicts.append(json.loads(messages[-1]["content"])["publish_status"])
                raise LLMReasoningRunaway(
                    elapsed_s=120, estimated_tokens=4000, trigger="time",
                    partial_response=LLMResponse(content="", reasoning_content="repairing citation"),
                )
            else:
                verdicts.append(json.loads(messages[-1]["content"])["publish_status"])
                return LLMResponse(content="生态参与")
            return LLMResponse(tool_calls=[{
                "id": f"c{self.count}", "type": "function",
                "function": {"name": name, "arguments": json.dumps(args)},
            }])

    model = Model()
    ledger = get_run_ledger()
    result = await run_agent_loop(
        system_prompt="Answer with sources", user_message="Explain ecosystem participation",
        llm=model, tools=[fetch.corpus_fetch, manifest.corpus_submit_manifest],
        config=LoopConfig(task_id="receipt-repair", role_id="stateful_react", max_turns=600,
                          max_llm_retries=1, loop_policy=LoopPolicy(no_tool_behavior="stop")),
        observers=[ConsumptionLedgerObserver(ledger=ledger),
                   ResearchConvergenceObserver(research_s=450, reserve_s=180)],
    )
    assert model.count == 5
    assert verdicts[0] == "unsupported"
    boundary = publish_boundary(ledger, final_text=result.final_content, answer_status="complete")
    assert boundary["answer_status"] == ("complete" if repair else "partial")
    assert boundary["publish_status"] == ("verified" if repair else "unsupported")
