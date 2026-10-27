from __future__ import annotations

import json

import pytest

from plugins.corpus.ledger import ConsumptionLedger, verify_manifest, write_manifest_file

DOC = "cv2:" + "a" * 64
LOC = "chunk:c1"
TEXT = "DeepSeek\u00a0于\u00a010\u00a0月\u00a017\u00a0日发布新版本。\n价格为\u00a00.30\u00a0美元。"


def fixture(text=TEXT, delivered=True):
    payload = json.dumps(
        {
            "ok": True,
            "view": "full",
            "doc_id": DOC,
            "locator": LOC,
            "text": text,
            "build_id": "a" * 64,
            "kind": "text",
            "spans": [],
            "source_ranges": [],
        },
        ensure_ascii=False,
    )
    ledger = ConsumptionLedger()
    ledger.record_fetch_result(payload)
    if delivered:
        ledger.finalize([{"role": "tool", "content": payload}])
    return ledger


def manifest(quote, report="模型猜测：可以买300股"):
    return {
        "schema_version": 1,
        "conclusions": [
            {
                "id": "C1",
                "report_quote": report,
                "evidence": [{"doc_id": DOC, "locator": LOC, "quote": quote, "purpose": "value"}],
                "required_dependencies": ["value"],
            }
        ],
    }


def test_nbsp_match_preserves_original_offsets_and_verbatim_text():
    result = verify_manifest(
        manifest(TEXT.replace("\u00a0", " ")), fixture(), resolver=lambda *_: TEXT
    )
    row = result["conclusions"][0]
    assert row["status"] == "supported", row
    match = row["matched_evidence"][0]
    assert match["quote"] == TEXT
    assert TEXT[match["start"] : match["end"]] == TEXT
    assert match["match_kind"] == "unicode_space"


@pytest.mark.parametrize(
    "quote",
    [
        TEXT.replace("0.30", "0.03"),
        TEXT.replace("\n", " "),
        TEXT.replace("美元", "人民币"),
        TEXT.replace("\u00a0", ""),
    ],
)
def test_matching_does_not_relax_numbers_words_or_line_breaks(quote):
    result = verify_manifest(manifest(quote), fixture(), resolver=lambda *_: TEXT)
    assert result["conclusions"][0]["status"] == "unsupported"


def test_space_equivalence_does_not_bypass_delivery():
    result = verify_manifest(
        manifest(TEXT.replace("\u00a0", " ")), fixture(delivered=False), resolver=lambda *_: TEXT
    )
    row = result["conclusions"][0]
    assert row["status"] == "partial"
    assert [p["code"] for p in row["problems"]] == ["not_delivered"]


def test_timeout_recovery_only_publishes_source_excerpts(tmp_path):
    from plugins.corpus.recovery import verified_excerpt_fallback

    write_manifest_file(manifest(TEXT.replace("\u00a0", " ")), directory=tmp_path)
    answer = verified_excerpt_fallback(fixture(), directory=tmp_path, resolver=lambda *_: TEXT)
    assert answer and TEXT.splitlines()[0] in answer
    assert "可以买300股" not in answer
    assert DOC in answer and LOC in answer and "未完成" in answer
    assert (
        verified_excerpt_fallback(
            fixture(delivered=False), directory=tmp_path, resolver=lambda *_: TEXT
        )
        is None
    )


async def test_retry_does_not_spend_last_minute_waiting_for_first_chunk(monkeypatch):
    from frontier_agent.core.errors import LLMCallExhausted
    from frontier_agent.core.llm import LLMResponse
    from frontier_agent.core.runtime.loop import _call

    remaining = [100.0]
    sleeps = []

    class SlowLLM:
        model = "test"
        calls = 0

        async def chat(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                remaining[0] = 60.0
                raise TimeoutError("no first chunk")
            return LLMResponse(content="should not retry")

    async def sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr(_call, "wall_deadline_remaining_s", lambda: remaining[0])
    monkeypatch.setattr(_call.asyncio, "sleep", sleep)
    monkeypatch.setattr(_call, "_llm_gate", lambda: None)
    llm = SlowLLM()
    with pytest.raises(LLMCallExhausted):
        await _call.call_llm(llm, [], timeout=600, max_retries=5, turn=10, first_chunk_s=45)
    assert llm.calls == 1
    assert sleeps == []


def test_web_logical_call_budget_is_bounded():
    from server.profile import build_profile_overrides
    from workflows.stateful_react_agent.nodes.main_agent import _resolve_runaway_guardrails

    cfg = build_profile_overrides()["agent"]
    assert _resolve_runaway_guardrails(cfg)[2] == 180
    assert cfg["research_wall_time_s"] == 450


def test_later_space_equivalent_occurrence_must_be_delivered():
    from plugins.corpus.ledger import FragmentRef

    original = "A B|A\u00a0B"
    ledger = ConsumptionLedger()
    ref = FragmentRef(
        doc_id=DOC,
        build_id="a" * 64,
        locator=LOC,
        kind="text",
        start=4,
        end=7,
        chars=3,
        content_sha256="",
        fragment_sha256="",
    )
    ledger.fetched.append(ref)
    ledger.delivered[ref.identity] = "delivered"
    row = verify_manifest(manifest("A B"), ledger, resolver=lambda *_: original)["conclusions"][0]
    assert row["status"] == "supported"
    assert row["matched_evidence"][0]["start"] == 4
    assert row["matched_evidence"][0]["quote"] == "A\u00a0B"


def test_offline_citation_gate_uses_same_space_rule():
    from plugins.corpus.verify import _gate_traceability

    card = {"position": {"evidence": [{"source_ref": DOC, "quote": TEXT.replace("\u00a0", " ")}]}}
    _status, problems, total, traced = _gate_traceability(card, lambda _: TEXT)
    assert not problems and total == traced == 1


def test_recovery_excludes_partial_and_stale_claims(tmp_path):
    from plugins.corpus.recovery import verified_excerpt_fallback

    old = manifest(TEXT)
    old["owner_role"] = "same-owner"
    write_manifest_file(old, directory=tmp_path)
    replacement = manifest("invented quote")
    replacement["owner_role"] = "same-owner"
    write_manifest_file(replacement, directory=tmp_path)
    assert (
        verified_excerpt_fallback(fixture(), directory=tmp_path, resolver=lambda *_: TEXT) is None
    )


def test_recovery_fails_closed_on_resolver_failure(tmp_path):
    from plugins.corpus.recovery import verified_excerpt_fallback

    write_manifest_file(manifest(TEXT), directory=tmp_path)

    def broken(*_):
        raise OSError("source unavailable")

    assert verified_excerpt_fallback(fixture(), directory=tmp_path, resolver=broken) is None


@pytest.mark.parametrize("stop_reason", ["wall_deadline", "llm_error"])
@pytest.mark.parametrize("invalid_claim", [False, True])
async def test_real_node_publishes_verified_partial_after_wall_deadline(
    tmp_path, monkeypatch, stop_reason, invalid_claim
):
    from types import SimpleNamespace

    import apodex.session
    from frontier_agent.core.loop_types import AgentLoopResult
    from plugins.corpus import ledger as ledger_module
    from workflows.stateful_react_agent.nodes import main_agent as node

    monkeypatch.setenv("APODEX_RUN_DIR", str(tmp_path / "run"))
    candidate = manifest(TEXT.replace("\u00a0", " "))
    if invalid_claim:
        candidate["conclusions"][0]["evidence"].append(
            {"doc_id": DOC, "locator": LOC, "quote": "invented evidence"}
        )
        candidate["conclusions"][0]["required_dependencies"].append("period")
    write_manifest_file(candidate, directory=tmp_path / "run/corpus")
    ledger = fixture()
    monkeypatch.setattr(ledger_module, "get_run_ledger", lambda *a, **kw: ledger)
    monkeypatch.setattr(ledger_module, "_default_resolver", lambda *_: TEXT)
    monkeypatch.setattr(
        node,
        "_resolve_llm_and_profile",
        lambda *a, **kw: (SimpleNamespace(model_name="mock"), {"agent": {"direct": True}}, None),
    )
    monkeypatch.setattr(
        node, "registry", SimpleNamespace(get=lambda _: None, get_optional=lambda _: None)
    )
    monkeypatch.setattr(node, "_tools_for_stateful_react", lambda *a: [])
    monkeypatch.setattr(node, "resolve_sandbox_mode", lambda _: "bwrap")
    monkeypatch.setattr(node, "_resolve_worktree_root", lambda *a: tmp_path)
    monkeypatch.setattr(node, "_resolve_sandbox_binds", lambda *a: ((), tmp_path / "outputs"))
    monkeypatch.setattr(node, "_resolve_trajectory_dir", lambda *a: tmp_path / "trace")
    monkeypatch.setattr(
        node, "_resolve_conversation_path", lambda *a: tmp_path / "conversation.json"
    )

    async def loop(**kwargs):
        return AgentLoopResult(
            messages=[],
            stopped_by=stop_reason,
            metadata={
                "final_answer": "no reliable conclusion",
                "final_answer_source": "deterministic_fallback",
            },
        )

    monkeypatch.setattr(node, "run_agent_loop", loop)
    monkeypatch.setattr(apodex.session, "run_agent_loop", loop)
    result = await node.react_agent_node(
        {"original_question": "总结模型优势", "metadata": {}},
        SimpleNamespace(task_id="excerpt-test"),
    )
    assert result["answer_status"] == "partial"
    assert result["final_answer_source"] == "verified_corpus_excerpts"
    assert result["stopped_by"] == stop_reason
    assert TEXT.splitlines()[0] in result["final_answer"]
    assert "可以买300股" not in result["final_answer"]


async def test_logical_deadline_covers_retries_without_a_run_wall(monkeypatch):
    from types import SimpleNamespace

    from frontier_agent.core.errors import LLMCallExhausted
    from frontier_agent.core.runtime.loop import _call

    now = [0.0]

    class SlowLLM:
        model = "test"
        calls = 0

        async def chat(self, *args, **kwargs):
            self.calls += 1
            assert kwargs["timeout"] == 180
            now[0] += 120
            raise TimeoutError("slow attempt")

    async def no_sleep(_):
        pytest.fail("retry backoff must not start")

    monkeypatch.setattr(_call, "time", SimpleNamespace(monotonic=lambda: now[0]))
    monkeypatch.setattr(_call, "wall_deadline_remaining_s", lambda: None)
    monkeypatch.setattr(_call, "_llm_gate", lambda: None)
    monkeypatch.setattr(_call.asyncio, "sleep", no_sleep)
    llm = SlowLLM()
    with pytest.raises(LLMCallExhausted) as exc:
        await _call.call_llm(
            llm,
            [],
            timeout=600,
            max_retries=5,
            turn=10,
            first_chunk_s=45,
            logical_call_timeout_s=180,
        )
    assert exc.value.reason == "logical_call_deadline"
    assert llm.calls == 1


@pytest.mark.parametrize("delivered", [True, False])
def test_failed_claim_can_preserve_only_verified_delivered_excerpts(tmp_path, delivered):
    from plugins.corpus.recovery import verified_excerpt_fallback

    candidate = manifest(TEXT)
    row = candidate["conclusions"][0]
    row["required_dependencies"].append("period")
    row["evidence"].append({"doc_id": DOC, "locator": LOC, "quote": "invented evidence"})
    write_manifest_file(candidate, directory=tmp_path)
    ledger = fixture(delivered=delivered)
    assert verify_manifest(candidate, ledger, resolver=lambda *_: TEXT)["status"] == "unsupported"
    answer = verified_excerpt_fallback(ledger, directory=tmp_path, resolver=lambda *_: TEXT)
    if not delivered:
        assert answer is None
        return
    assert answer and TEXT.splitlines()[0] in answer
    assert "可以买300股" not in answer and "invented evidence" not in answer
    assert "结论未通过" in answer and "必要依赖" in answer


@pytest.mark.parametrize("first_chunk_delay", [2.082, 44.9])
@pytest.mark.parametrize("recovery_succeeds", [True, False])
@pytest.mark.parametrize("wall_remaining", [450, 130])
async def test_web_runaway_reserves_one_recovery_within_logical_budget(
    monkeypatch, first_chunk_delay, recovery_succeeds, wall_remaining
):
    from types import SimpleNamespace

    from frontier_agent.core.errors import LLMReasoningRunaway
    from frontier_agent.core.llm import LLMResponse
    from frontier_agent.core.loop_types import LoopConfig
    from frontier_agent.core.runtime.loop import _call
    from frontier_agent.core.runtime.loop.agent_loop import run_agent_loop
    from server.profile import PROFILE_NAME, build_profile_overrides
    from workflows.stateful_react_agent.nodes.main_agent import _loop_policy
    from workflows.stateful_react_agent.profile import load_react_profile

    cfg = load_react_profile(PROFILE_NAME, overrides=build_profile_overrides())["agent"]
    now = [0.0]
    calls = []

    async def stream(llm, messages, timeout, on_delta, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            now[0] += first_chunk_delay + kwargs["reasoning_only_timeout_s"] + 5
            raise LLMReasoningRunaway(
                elapsed_s=kwargs["reasoning_only_timeout_s"],
                estimated_tokens=6236,
                trigger="time",
                partial_response=LLMResponse(content="", reasoning_content="unfinished"),
            )
        if not recovery_succeeds:
            now[0] += timeout
            raise TimeoutError("recovery consumed remaining logical budget")
        now[0] += 20
        return LLMResponse(content="恢复后产生的正文", finish_reason="stop")

    async def sleep(delay):
        now[0] += delay

    monkeypatch.setattr(_call, "time", SimpleNamespace(monotonic=lambda: now[0]))
    monkeypatch.setattr(_call, "wall_deadline_remaining_s", lambda: wall_remaining - now[0])
    monkeypatch.setattr(_call, "_llm_gate", lambda: None)
    monkeypatch.setattr(_call, "_stream_llm_response", stream)
    monkeypatch.setattr(_call.asyncio, "sleep", sleep)
    llm = SimpleNamespace(model="offline-regression")
    result = await run_agent_loop(
        system_prompt="test",
        user_message="finish",
        llm=llm,
        tools=[],
        observers=[],
        config=LoopConfig(
            max_turns=1,
            max_llm_retries=5,
            llm_timeout=600,
            first_chunk_timeout=cfg["first_chunk_s"],
            reasoning_only_timeout_s=cfg["reasoning_only_timeout_s"],
            logical_call_timeout_s=cfg["logical_call_timeout_s"],
            loop_policy=_loop_policy(),
        ),
    )
    assert len(calls) == 2, result.metadata
    if recovery_succeeds:
        assert result.final_content == "恢复后产生的正文"
        assert result.stopped_by == "no_tool"
    else:
        assert result.stopped_by == "llm_error"
        assert result.metadata["llm_error_reason"] == (
            "exhausted" if wall_remaining < 180 else "logical_call_deadline"
        )
    assert now[0] <= min(wall_remaining, cfg["logical_call_timeout_s"])
