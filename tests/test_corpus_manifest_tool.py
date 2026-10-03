"""corpus_submit_manifest 工具与伴随绑定测试（A4 修订契约，评审 C3/C4/C7）。

覆盖：入口 schema 拒绝（空清单／非对象条目／缺 quote／杜撰 purpose）、
提交即回验（supported／pending 两种形态）、独立子清单落盘、resolver 基础设施
故障按 C7 分类为 verification_error（不吞）、伴随绑定（绑定语料检索即绑定清单
生产者）与白名单注册、观察者 on_turn_end 送达快照更新（pending → delivered）。
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import pytest

from frontier_agent.core.loop_types import ToolResult, TurnContext
from plugins.corpus.ledger import (
    DELIVERED,
    PUBLISH_PARTIAL,
    PUBLISH_VERIFIED,
    reset_run_ledgers,
)
from plugins.corpus.ledger import (
    evidence_delivery_for_submit as ledger_delivery_for_submit,
)
from plugins.tools import _BUILTIN_TOOLS
from plugins.tools.corpus_manifest import (
    MANIFEST_PROMPT_NOTE,
    MANIFEST_TOOL_NAME,
    corpus_submit_manifest,
    with_manifest_tool,
)

DOC = "cv2:" + "a" * 64
BUILD = "a" * 64
TEXT = "营业收入 1,234 万元。"


def _fetch_body(text: str = TEXT, locator: str = "chunk:c1") -> str:
    return json.dumps({
        "ok": True, "view": "full", "doc_id": DOC, "locator": locator,
        "kind": "table", "build_id": BUILD, "text": text,
        "spans": [], "source_ranges": [],
    }, ensure_ascii=False)


class _Verbatim:
    def __init__(self, text: str) -> None:
        self.text = text


class _StubService:
    def __init__(self, texts: dict[str, str]) -> None:
        self._texts = texts

    def fetch_verbatim(self, doc_id: str, locator: str) -> _Verbatim:
        text = self._texts.get(f"{doc_id}|{locator}")
        if text is None:
            raise LookupError(f"no source for {doc_id}|{locator}")
        return _Verbatim(text)


@pytest.fixture
def run_env(tmp_path, monkeypatch):
    """独立 run 目录 + 干净的 run 账本 + 可解析的权威原文。"""
    monkeypatch.setenv("APODEX_RUN_DIR", str(tmp_path))
    reset_run_ledgers()
    import plugins.tools.corpus_manifest as mod

    monkeypatch.setattr(
        mod, "get_service", lambda: _StubService({f"{DOC}|chunk:c1": TEXT}),
    )
    return tmp_path


def _submit(conclusions: list[dict[str, Any]]) -> dict:
    return json.loads(asyncio.run(corpus_submit_manifest.func(conclusions=conclusions)))


# ── 入口 schema 校验 ─────────────────────────────────────────────────────


def test_schema_rejects_empty_list(run_env) -> None:
    out = _submit([])
    assert out["ok"] is False and out["errors"]
    assert not (run_env / "corpus" / "manifests").exists()  # 拒绝即不落盘


def test_schema_rejects_non_dict_row_and_missing_quote(run_env) -> None:
    out = _submit([{"id": "C1", "evidence": "不是数组"},
                   {"id": "C2", "evidence": [{"doc_id": DOC, "locator": "chunk:c1"}]}])
    assert out["ok"] is False
    assert any("evidence" in e for e in out["errors"])
    assert any("quote" in e for e in out["errors"])


def test_schema_rejects_fabricated_purpose(run_env) -> None:
    out = _submit([{"id": "C1", "evidence": [
        {"doc_id": DOC, "locator": "chunk:c1", "quote": TEXT, "purpose": "vibes"}]}])
    assert out["ok"] is False
    assert any("vibes" in e for e in out["errors"])


def test_semantic_query_alone_binds_manifest_companion() -> None:
    from plugins.tools.corpus_semantic_query import corpus_semantic_query

    tools = with_manifest_tool([corpus_semantic_query], role_id="stateful_react")
    assert [tool.name for tool in tools] == ["corpus_semantic_query", "corpus_submit_manifest"]
    assert with_manifest_tool(tools, role_id="stateful_react") == tools


def test_dependency_roles_are_not_semantic_use_permissions(run_env) -> None:
    from plugins.tools.corpus_manifest import _validate_conclusions

    for role in ("condition", "negation", "attribution"):
        assert _validate_conclusions([{"evidence": [{
            "doc_id": DOC, "locator": "chunk:c1", "quote": TEXT, "purpose": role,
        }], "required_dependencies": [role]}]) == []
    for use in ("cite", "compare", "calculate"):
        assert _validate_conclusions([{"evidence": [{
            "doc_id": DOC, "locator": "chunk:c1", "quote": TEXT, "purpose": use,
        }]}])


# ── 提交即回验（评审 C3）─────────────────────────────────────────────────


def _conclusion(**overrides: Any) -> dict[str, Any]:
    row = {"id": "C1", "evidence": [
        {"doc_id": DOC, "locator": "chunk:c1", "quote": TEXT, "purpose": "value"}]}
    row.update(overrides)
    return row


def test_valid_submission_verifies_supported_and_writes_manifest(run_env) -> None:
    from plugins.corpus.ledger import get_run_ledger

    ledger = get_run_ledger()
    ledger.record_fetch_result(_fetch_body())
    ledger.finalize([{"role": "tool", "content": _fetch_body()}])  # 已送达

    out = _submit([_conclusion()])
    assert out["ok"] is True
    assert out["publish_status"] == PUBLISH_VERIFIED
    assert out["conclusions"][0]["status"] == "supported"
    manifest_file = run_env / "corpus" / "manifests" / "manifest-000.json"
    assert out["manifest_file"] == str(manifest_file)
    assert manifest_file.exists()
    payload = json.loads(manifest_file.read_text(encoding="utf-8"))
    assert payload["conclusions"][0]["id"] == "C1"  # 入口未编号时自动补


def test_new_fetch_before_turn_boundary_is_pending(run_env) -> None:
    """评审 C3：新取片段尚未经过消息边界核验 → pending，提示下一轮重新提交。"""
    from plugins.corpus.ledger import get_run_ledger

    get_run_ledger().record_fetch_result(_fetch_body(), turn=3)
    # 未 finalize：last_finalized_turn=-1，片段 turn=3 → pending

    out = _submit([_conclusion()])
    assert out["ok"] is True
    assert out["publish_status"] == PUBLISH_PARTIAL
    row = out["conclusions"][0]
    assert row["status"] == "partial"
    assert any(p["code"] == "pending_delivery" for p in row["problems"])


def test_resolver_infra_failure_surfaces_verification_error(run_env, monkeypatch) -> None:
    """评审 C7：resolver 基础设施故障随结果如实返回，不被描述成证据缺口。"""
    import plugins.tools.corpus_manifest as mod

    class _BrokenService:
        def fetch_verbatim(self, doc_id: str, locator: str) -> _Verbatim:
            raise ConnectionError("store unavailable")

    monkeypatch.setattr(mod, "get_service", _BrokenService)

    out = _submit([_conclusion()])
    assert out["ok"] is True  # 工具不抛，问题随结果返回
    assert out["publish_status"] == "verification_error"
    assert out["conclusions"][0]["problems"][0]["code"] == "verification_error"


# ── 同拥有者取代（F2：校验语义修复）──────────────────────────────────────


def test_resubmit_from_same_agent_supersedes_and_records_owner(run_env) -> None:
    """清单按当前代理实例的 owner 落盘；同代理重新提交取代先前候选（F2）。

    修复前：每次提交各成一个 owner（退回文件名），边界把被取代的旧候选并入，
    环内已 ``verified`` 的修正到边界仍判 ``partial``。
    """
    from frontier_agent.core.execution_context import (
        ExecutionScope,
        reset_current_execution_scope,
        set_current_execution_scope,
    )
    from plugins.corpus.ledger import (
        get_run_ledger,
        load_manifest_files,
        verify_and_record,
    )

    ledger = get_run_ledger()
    ledger.record_fetch_result(_fetch_body())
    ledger.finalize([{"role": "tool", "content": _fetch_body()}])

    token = set_current_execution_scope(
        ExecutionScope(task_id="run-1", role_id="stateful_react"),
    )
    try:
        first = _submit([_conclusion()])
        second = _submit([_conclusion()])
    finally:
        reset_current_execution_scope(token)

    assert first["owner"] == second["owner"] == "stateful_react:run-1"
    assert [p.name for p, _ in load_manifest_files()] == [
        "manifest-000.json", "manifest-001.json",
    ]
    # 同拥有者取最新 → 只有一份结论，不重复、无前缀（修复前会是两条）。
    verification = verify_and_record(ledger, resolver=lambda d, loc: TEXT)
    assert [row["id"] for row in verification["conclusions"]] == ["C1"]


def test_submit_without_scope_still_succeeds(run_env) -> None:
    """无执行作用域（直接调用／脚本）时不报错，owner 退回空（文件名语义）。"""
    out = _submit([_conclusion()])
    assert out["ok"] is True
    assert out["owner"] is None


# ── 伴随绑定（评审 C4 配套）──────────────────────────────────────────────


def test_with_manifest_tool_binds_companion_only_for_retrieval_tools() -> None:
    tools = [SimpleNamespace(name="corpus_search"), SimpleNamespace(name="bash")]
    bound = with_manifest_tool(tools, role_id="t")
    assert [t.name for t in bound] == ["corpus_search", "bash", MANIFEST_TOOL_NAME]
    assert len(with_manifest_tool(bound, role_id="t")) == 3  # 已绑定不重复
    assert [t.name for t in with_manifest_tool(
        [SimpleNamespace(name="bash")], role_id="t",
    )] == ["bash"]  # 无语料检索工具不注入


def test_manifest_tool_is_in_builtin_allowlist() -> None:
    assert MANIFEST_TOOL_NAME in {getattr(t, "name", "") for t in _BUILTIN_TOOLS}


def test_subagent_funnel_binds_manifest_tool() -> None:
    from plugins.tools.create_subagent import _with_manifest

    bound = _with_manifest([SimpleNamespace(name="corpus_fetch")])
    assert bound[-1].name == MANIFEST_TOOL_NAME


def test_manifest_prompt_note_ships_submission_duties() -> None:
    assert "corpus_submit_manifest" in MANIFEST_PROMPT_NOTE
    assert "pending" in MANIFEST_PROMPT_NOTE


# ── 送达快照：on_turn_end 边界（评审 C3）─────────────────────────────────


def _turn(turn: int, messages: list) -> TurnContext:
    return TurnContext(
        turn=turn, max_turns=10, task_id="t1", role_id="stateful_react",
        ai_text="", thinking="", tool_calls=[], messages=messages, usage=None,
        metadata={},
    )


async def test_on_turn_end_moves_pending_to_delivered(run_env) -> None:
    from plugins.corpus.ledger import ConsumptionLedgerObserver, get_run_ledger

    ledger = get_run_ledger()
    observer = ConsumptionLedgerObserver(
        task_id="t1", pipeline_id="stateful-react-agent", ledger=ledger,
    )
    body = _fetch_body()
    await observer.on_tool_result(
        _turn(1, []), ToolResult(name="corpus_fetch", args={}, result=body,
                                 duration_ms=1, tool_call_id="y", is_error=False),
    )
    start, end = 0, len(TEXT)
    assert ledger_delivery_for_submit(ledger, DOC, "chunk:c1", start, end) == "pending"

    await observer.on_turn_end(_turn(1, [{"role": "tool", "content": body}]))
    assert ledger.last_finalized_turn == 1
    assert ledger_delivery_for_submit(ledger, DOC, "chunk:c1", start, end) == DELIVERED
