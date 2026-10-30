import json
from types import SimpleNamespace

import pytest

from frontier_agent.core.llm import LLMResponse
from frontier_agent.core.loop_types import LoopConfig, LoopPolicy
from frontier_agent.core.runtime.loop.agent_loop import run_agent_loop
from frontier_agent.core.tool import tool
from plugins.corpus.context_reuse import CorpusContextReuseObserver
from plugins.corpus.ledger import DELIVERED, ConsumptionLedger, ConsumptionLedgerObserver

DOC = "cv2:" + "a" * 64
ARGS = {"doc_id": DOC, "locator": "chunk:c1"}
TEXT = "原文证据。"


def call(args=ARGS):
    return {"id": "old", "type": "function", "function": {
        "name": "corpus_fetch", "arguments": json.dumps(args)}}


def history(body=None):
    body = body or {"ok": True, "doc_id": DOC, "build_id": DOC[4:],
                    "locator": "chunk:c1", "kind": "body", "text": TEXT}
    return [{"role": "assistant", "tool_calls": [call()]},
            {"role": "tool", "tool_call_id": "old", "content": json.dumps(body, ensure_ascii=False)}]


@pytest.mark.parametrize("mode", ["missing", "summary", "partial", "version", "refresh", "different_args"])
async def test_reuse_never_hides_missing_or_changed_evidence(mode):
    messages, args = history(), dict(ARGS)
    if mode == "missing":
        messages = []
    elif mode == "summary":
        messages[-1]["content"] = "[summary] previously read evidence"
    elif mode == "partial":
        body = json.loads(messages[-1]["content"])
        messages[-1]["content"] = json.dumps(body | {"fetch_complete": False})
    elif mode == "version":
        args["doc_id"] = "cv2:" + "b" * 64
    elif mode == "refresh":
        args["force_refresh"] = True
    else:
        args["locator"] = "chunk:c2"
    result = await CorpusContextReuseObserver().on_tool_call(
        SimpleNamespace(messages=messages), {"name": "corpus_fetch", "args": args})
    assert result is None


async def test_loop_reuses_original_without_backend_or_duplicate_text(tmp_path, monkeypatch):
    monkeypatch.setenv("APODEX_RUN_DIR", str(tmp_path))
    executed = []

    @tool
    async def corpus_fetch(doc_id: str, locator: str) -> str:
        """Test backend that must not run for an already-visible exact fetch."""
        executed.append(doc_id)
        return "unexpected"

    class Model:
        count = 0
        model = "stub"

        async def chat(self, messages, **kwargs):
            self.count += 1
            if self.count == 1:
                return LLMResponse(tool_calls=[call() | {"id": "new"}])
            result = json.loads(messages[-1]["content"])
            assert result["reused_from_context"] is True
            assert TEXT not in messages[-1]["content"]
            return LLMResponse(content="沿用已读取原文。")

    ledger = ConsumptionLedger()
    original = history()
    saved = json.dumps(original)
    await run_agent_loop(
        system_prompt="Use evidence", user_message="沿用原文",
        initial_messages=original, llm=Model(), tools=[corpus_fetch],
        config=LoopConfig(task_id="reuse", max_turns=3, max_llm_retries=1,
                          loop_policy=LoopPolicy(no_tool_behavior="stop")),
        observers=[ConsumptionLedgerObserver(ledger=ledger), CorpusContextReuseObserver()],
    )
    assert not executed
    assert json.dumps(original) == saved
    assert ledger.fetched
    assert all(ledger.delivered_status(ref.identity) == DELIVERED for ref in ledger.fetched)
