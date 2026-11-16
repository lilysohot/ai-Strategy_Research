"""The extractor may lose a citation, never invent one.

Every test here is about the boundary between "the model wrote something" and
"the record may replace the page". A fabricated ref is the one failure that would
survive every downstream check — the contract resolves refs, so it can only
reject what it cannot find; an invented-but-resolvable ref would pass. That is why
the whitelist lives here, against the text the model was actually shown.
"""

from __future__ import annotations

import json

import pytest

from frontier_agent.core.runtime.reading.contract import Finding, FindingKind
from frontier_agent.core.runtime.reading.stage import ExtractionBounds, RetirableBody
from frontier_agent.core.runtime.reading.store import (
    JsonCheckpointStore,
    checkpoint_from_dict,
    checkpoint_to_dict,
)
from plugins.corpus.reading_extractor import (
    CorpusReadingExtractor,
    parse_extraction_reply,
)

REF_A = "ce:" + "a" * 32
REF_B = "ce:" + "b" * 32


def _body(*, refs=(REF_A,), texts=("2025 财年营收 123 百万美元。",), tool="corpus_fetch") -> str:
    items = [
        {
            "text": text,
            "evidence_ref": ref,
            "location": f"第 {index + 1} 页",
        }
        for index, (ref, text) in enumerate(zip(refs, texts, strict=True))
    ]
    return json.dumps(
        {
            "ok": True,
            "protocol": "corpus-navigation-v2",
            "scope": "document",
            "items": items,
            "fetch_complete": False,
        },
        ensure_ascii=False,
    )


def _retirable(text: str, index: int = 0, tool: str = "corpus_fetch") -> RetirableBody:
    return RetirableBody(index=index, call_id=f"c{index}", tool_name=tool, text=text)


class _LLM:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.prompts: list[str] = []

    async def chat(self, messages, **kwargs):
        del kwargs
        self.prompts.append(messages[-1]["content"])

        class _Response:
            content = self.reply

        return _Response()


def _evidence(doc_id: str = "cv2:" + "d" * 64, start: int = 0, length: int = 10):
    def resolve(ref: str) -> dict:
        return {
            "doc_id": doc_id,
            "locator": f"unit:{ref[-4:]}",
            "quote": "x" * length,
            "source_start": start,
            "source_end": start + length,
        }

    return resolve


def _reply(**overrides) -> str:
    payload = {
        "findings": [
            {
                "finding_id": "f1",
                "kind": "number",
                "statement": "2025 财年营收 123 百万美元",
                "value": "123",
                "unit": "百万美元",
                "period": "FY2025",
                "evidence_refs": [REF_A],
            }
        ],
        "open_questions": ["毛利率口径是否一致"],
    }
    payload.update(overrides)
    return json.dumps(payload, ensure_ascii=False)


@pytest.mark.asyncio
async def test_a_well_formed_reply_becomes_a_checkpoint_with_ranges() -> None:
    extractor = CorpusReadingExtractor(llm=_LLM(_reply()), resolve=_evidence())

    checkpoint = await extractor(
        [_retirable(_body())],
        "营收口径",
        ExtractionBounds(record_limit=4_000, max_findings=24),
    )

    assert len(checkpoint.findings) == 1
    assert checkpoint.findings[0].kind == FindingKind.NUMBER
    assert checkpoint.findings[0].unit == "百万美元"
    assert checkpoint.sources
    assert checkpoint.sources[0].source_id.startswith("cv2:")
    assert checkpoint.coverage.complete is False
    assert checkpoint.open_questions == ("毛利率口径是否一致",)


@pytest.mark.asyncio
async def test_a_fabricated_reference_is_dropped_and_counted() -> None:
    """The model citing a ref it never saw is the one error a resolver cannot
    catch: a plausible-looking id resolves to nothing, or worse, to something."""
    reply = _reply(
        findings=[
            {
                "finding_id": "f1",
                "kind": "fact",
                "statement": "营收增长强劲",
                "evidence_refs": ["ce:" + "f" * 32],
            }
        ]
    )
    extractor = CorpusReadingExtractor(llm=_LLM(reply), resolve=_evidence())

    checkpoint = await extractor(
        [_retirable(_body())],
        "营收",
        ExtractionBounds(record_limit=4_000, max_findings=24),
    )

    assert checkpoint.findings == ()
    assert any("引用不在本次原文中" in note for note in checkpoint.coverage.limitations)


@pytest.mark.asyncio
async def test_a_number_missing_its_unit_is_passed_through_not_repaired() -> None:
    """Repairing here would hide the omission from the contract, which exists to
    refuse exactly this record."""
    reply = _reply(
        findings=[
            {
                "finding_id": "f1",
                "kind": "number",
                "statement": "营收 123",
                "value": "123",
                "evidence_refs": [REF_A],
            }
        ]
    )
    extractor = CorpusReadingExtractor(llm=_LLM(reply), resolve=_evidence())

    checkpoint = await extractor(
        [_retirable(_body())],
        "营收",
        ExtractionBounds(record_limit=4_000, max_findings=24),
    )

    finding = checkpoint.findings[0]
    assert finding.unit == ""
    assert finding.period == ""
    assert finding.kind == FindingKind.NUMBER


@pytest.mark.asyncio
async def test_bodies_beyond_the_digest_budget_are_reported_as_unread() -> None:
    """Silently leaving a page out of the prompt and then retiring it would claim
    coverage that never happened."""
    one = _retirable(_body())
    probe = CorpusReadingExtractor(llm=_LLM(_reply()), resolve=_evidence())
    one_chars = probe.build_digest([one]).fed_chars
    extractor = CorpusReadingExtractor(
        llm=_LLM(_reply()),
        resolve=_evidence(),
        digest_budget=one_chars + 1,
    )

    checkpoint = await extractor(
        [one, _retirable(_body(), index=1)],
        "营收",
        ExtractionBounds(record_limit=4_000, max_findings=24),
    )

    assert any("未进入提取输入" in note for note in checkpoint.coverage.limitations)
    assert checkpoint.coverage.complete is False


@pytest.mark.asyncio
async def test_a_non_json_body_is_shown_without_a_reference() -> None:
    extractor = CorpusReadingExtractor(llm=_LLM(_reply()), resolve=_evidence())
    digest = extractor.build_digest([_retirable("plain text, not json")])

    assert "plain text, not json" in digest.text
    assert digest.refs == frozenset()


@pytest.mark.asyncio
async def test_the_prompt_carries_every_reference_verbatim() -> None:
    llm = _LLM(_reply())
    extractor = CorpusReadingExtractor(llm=llm, resolve=_evidence())

    await extractor(
        [_retirable(_body(refs=(REF_A, REF_B), texts=("甲", "乙")))],
        "营收",
        ExtractionBounds(record_limit=1_000, max_findings=8),
    )

    prompt = llm.prompts[0]
    assert REF_A in prompt
    assert REF_B in prompt
    assert "1,000" not in prompt or "1000" in prompt  # bound is stated, format-agnostic
    assert "8" in prompt


def test_fenced_json_is_accepted() -> None:
    findings, questions, dropped = parse_extraction_reply(
        "```json\n" + _reply() + "\n```",
        {REF_A},
    )

    assert len(findings) == 1
    assert dropped == 0
    assert questions


@pytest.mark.parametrize("reply", ["", "not json", "{broken", "[]"])
def test_an_unparseable_reply_yields_nothing_rather_than_raising(reply: str) -> None:
    findings, questions, dropped = parse_extraction_reply(reply, {REF_A})

    assert findings == []
    assert questions == []
    assert dropped == 0


def test_an_unknown_kind_degrades_to_as_fact() -> None:
    reply = json.dumps(
        {
            "findings": [
                {
                    "finding_id": "f1",
                    "kind": "opinion",
                    "statement": "管理层谨慎",
                    "evidence_refs": [REF_A],
                }
            ],
        }
    )

    findings, _questions, _dropped = parse_extraction_reply(reply, {REF_A})

    assert findings[0].kind == FindingKind.FACT


def test_a_finding_without_a_statement_is_dropped() -> None:
    reply = json.dumps(
        {
            "findings": [
                {"finding_id": "f1", "kind": "fact", "statement": "  ", "evidence_refs": [REF_A]}
            ],
        }
    )

    findings, _questions, dropped = parse_extraction_reply(reply, {REF_A})

    assert findings == []
    assert dropped == 1


def test_a_checkpoint_survives_a_store_round_trip() -> None:
    """Installed records are read back by later turns; a lossy serialiser would
    turn a verified record into an unverifiable one."""
    from frontier_agent.core.runtime.reading.contract import (
        CheckpointBudget,
        CheckpointStatus,
        Coverage,
        ReadingCheckpoint,
        SourceRange,
    )

    checkpoint = ReadingCheckpoint(
        checkpoint_id="ck:run/001",
        task_id="run",
        question="口径",
        findings=(
            Finding(
                finding_id="f1",
                kind=FindingKind.NUMBER,
                statement="营收 123 百万美元",
                evidence_refs=(REF_A,),
                source_id="cv2:d",
                value="123",
                unit="百万美元",
                period="FY2025",
                contradicts=("f2",),
            ),
        ),
        sources=(SourceRange("cv2:d", "ddd", 10, 20, "unit:1"),),
        coverage=Coverage(
            read_ranges=(SourceRange("cv2:d", "ddd", 10, 20),),
            unread_ranges=(SourceRange("cv2:d", "ddd", 20, 40),),
            limitations=("附录未校验",),
            complete=False,
        ),
        budget=CheckpointBudget(100, 4_000, 50_000, 60_000),
        status=CheckpointStatus.INSTALLED,
    )

    restored = checkpoint_from_dict(checkpoint_to_dict(checkpoint))

    assert restored == checkpoint


def test_the_store_writes_atomically_and_reads_back(tmp_path) -> None:
    from frontier_agent.core.runtime.reading.contract import (
        CheckpointStatus,
        Coverage,
        ReadingCheckpoint,
    )

    store = JsonCheckpointStore(tmp_path / "reading")
    checkpoint = ReadingCheckpoint(
        checkpoint_id="ck:run/001",
        task_id="run",
        question="口径",
        findings=(Finding("f1", FindingKind.FACT, "x", (REF_A,)),),
        coverage=Coverage(),
        status=CheckpointStatus.INSTALLED,
    )

    store.put(checkpoint)
    loaded = store.get("ck:run/001")

    assert loaded is not None
    assert loaded.checkpoint_id == checkpoint.checkpoint_id
    assert loaded.status == CheckpointStatus.INSTALLED
    # No temp file left behind, and the id was sanitised into a filename.
    assert [p.name for p in (tmp_path / "reading").iterdir()] == ["ck_run_001.json"]
    assert store.get("ck:run/999") is None


# ── end to end: a real page, a real receipt, a real retirement ────────────
#
# Everything above tests one link. This one runs the whole chain the way the
# workflow does: a corpus page whose receipt is on disk, the real extractor, the
# real contract, the real store, and a tool message that ends up as a marker in
# the next request. If any link disagrees with another about what a ref is, this
# is where it shows.


@pytest.mark.asyncio
async def test_a_page_is_retired_behind_a_durable_checkpoint(tmp_path, monkeypatch) -> None:
    from frontier_agent.core.llm import LLMResponse
    from frontier_agent.core.loop_types import BaseObserver, LoopConfig
    from frontier_agent.core.runtime.loop.agent_loop import run_agent_loop
    from frontier_agent.core.tool import tool
    from plugins.corpus.reading_extractor import default_checkpoint_store
    from plugins.corpus.tool_refs import fetch_evidence_ref, publish_fetch_references
    from workflows._shared.reading_stage import build_reading_stage

    monkeypatch.setenv("CORPUS_TOOL_REF_ROOT", str(tmp_path))
    # Receipts are bound to ``CORPUS_TARGET_DB`` at both write and read time. The
    # loop loads ``.env`` lazily on the first config read, which would inject the
    # value *after* these receipts were written and turn them into binding
    # mismatches. Pinning it here makes the test describe the production order
    # (.env loaded before any receipt exists) instead of the accident of timing.
    monkeypatch.setenv("CORPUS_TARGET_DB", "postgres")

    doc_id = "cv2:" + "a" * 64
    quoted = "2025 财年营收 123 百万美元，同比 +8%，不含并购贡献。"
    item = {
        "text": quoted,
        "locator": "unit:0001",
        "kind": "paragraph",
        "page": 3,
        "fragment": {"start": 1000},
    }
    item["evidence_ref"] = fetch_evidence_ref(doc_id, item)
    page = publish_fetch_references(
        json.dumps(
            {
                "ok": True,
                "doc_id": doc_id,
                "scope": "document",
                "items": [item],
                "fetch_complete": False,
            },
            ensure_ascii=False,
        )
    )
    ref = item["evidence_ref"]
    # The receipt must be readable before the run, otherwise the assertions below
    # would be testing the test's own wiring.
    from plugins.corpus.tool_refs import resolve_evidence_reference

    assert resolve_evidence_reference(ref)["source_start"] == 1000

    @tool
    async def corpus_fetch(doc_id: str) -> str:
        """Read a page of the corpus document.

        Args:
            doc_id: Document identifier.
        """
        return page

    extraction = json.dumps(
        {
            "findings": [
                {
                    "finding_id": "f1",
                    "kind": "number",
                    "statement": "2025 财年营收 123 百万美元，同比 +8%",
                    "value": "123",
                    "unit": "百万美元",
                    "period": "FY2025",
                    "condition": "不含并购贡献",
                    "evidence_refs": [ref],
                }
            ],
            "open_questions": [],
        },
        ensure_ascii=False,
    )

    class _ExtractionLLM:
        model = "stub"

        async def chat(self, messages, **kwargs):
            del messages, kwargs
            return LLMResponse(content=extraction, finish_reason="stop")

    class _Agent:
        model = "stub"

        def __init__(self) -> None:
            self.calls = 0
            self.seen: list[list] = []

        async def chat(self, messages, **kwargs):
            del kwargs
            self.calls += 1
            self.seen.append([dict(m) for m in messages])
            if self.calls <= 2:
                return LLMResponse(
                    content="reading",
                    tool_calls=[
                        {
                            "id": f"r{self.calls}",
                            "type": "function",
                            "function": {
                                "name": "corpus_fetch",
                                "arguments": f'{{"doc_id":"{doc_id}"}}',
                            },
                        }
                    ],
                    finish_reason="tool_calls",
                )
            return LLMResponse(content="done", tool_calls=[], finish_reason="stop")

    events: list = []

    class _Spy(BaseObserver):
        critical = True

        async def on_reading_checkpoint(self, event) -> None:
            events.append(event)
            return None

    stage = build_reading_stage(
        llm=_ExtractionLLM(),
        agent_cfg={
            "reading_checkpoint": "on",
            "reading_checkpoint_working_set": 100,
            "reading_checkpoint_min_body_chars": 10,
            "reading_checkpoint_keep_recent": 0,
        },
        task_id="run-e2e",
    )
    assert stage is not None

    agent = _Agent()
    await run_agent_loop(
        system_prompt="system",
        user_message="读这篇财报",
        llm=agent,
        tools=[corpus_fetch],
        config=LoopConfig(max_turns=5, task_id="run-e2e", keep_recent=64, reading_stage=stage),
        observers=[_Spy()],
    )

    installed = [event for event in events if event.installed]
    assert installed, f"no checkpoint installed; events={[(e.reason, e.failure) for e in events]}"
    assert installed[0].retired_calls == ("r1",)
    assert installed[0].index_only is False

    # Durable, on disk, and readable back.
    store = default_checkpoint_store()
    saved = store.get(installed[0].checkpoint_id)
    assert saved is not None
    assert saved.findings[0].unit == "百万美元"
    assert saved.findings[0].period == "FY2025"
    assert saved.findings[0].evidence_refs == (ref,)
    assert saved.coverage.complete is False

    # And the request the model saw afterwards carries the archive, with the page
    # the model had already read reduced to a marker. The second read is still
    # verbatim: it belongs to the turn that was in flight.
    last = agent.seen[-1]
    blob = json.dumps(last, ensure_ascii=False)
    assert "研究归档" in blob
    assert ref in blob
    still_verbatim = [
        message
        for message in last
        if message.get("role") == "tool" and quoted in str(message.get("content") or "")
    ]
    assert len(still_verbatim) == 1
    assert "r1" in installed[0].retired_calls
