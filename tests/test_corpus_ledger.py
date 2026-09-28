"""A4 消费账本与结论证据校验测试（offered/requested/fetched/delivered + 两类完整性）。

覆盖 docs/data_clean_dos/01-table-recovery.md §2 的「消费判定」与「结论证据」两类场景：
服务取回但后处理截断、只读部分片段、显式跳过、范围缩小；正文已有有效证据、
缺单位／期间／脚注、表头错配；以及「缺清单只能标 draft」「模型自报 complete 不采信」。
"""

from __future__ import annotations

import json
from pathlib import Path

from frontier_agent.core.loop_types import AgentLoopResult, ToolResult, TurnContext
from plugins.corpus.ledger import (
    DELIVERED,
    PUBLISH_DRAFT,
    PUBLISH_PARTIAL,
    PUBLISH_UNSUPPORTED,
    PUBLISH_VERIFIED,
    SUPPORTED,
    TRUNCATED,
    UNKNOWN,
    UNSUPPORTED,
    ConsumptionLedger,
    ConsumptionLedgerObserver,
    get_run_ledger,
    load_manifest,
    reset_run_ledgers,
    verify_and_record,
    verify_manifest,
    write_ledger,
)

DOC = "cv2:" + "a" * 64
BUILD = "a" * 64


def _search_result(scope_id: str = "scope-1") -> str:
    return json.dumps({
        "ok": True,
        "query": "营收",
        "count": 1,
        "hits": [{
            "doc_id": DOC,
            "locator": "chunk:c1",
            "build_id": BUILD,
            "context_locators": ["chunk:c1", "chunk:c2"],
            "scope_id": scope_id,
            "total_chunks": 2,
            "by_kind": {"table": 1, "text": 1},
        }],
    }, ensure_ascii=False)


def _single_fetch(text: str, locator: str = "chunk:c1", kind: str = "table") -> str:
    return json.dumps({
        "ok": True,
        "view": "full",
        "doc_id": DOC,
        "locator": locator,
        "kind": kind,
        "build_id": BUILD,
        "text": text,
        "spans": [],
        "source_ranges": [],
    }, ensure_ascii=False)


def _envelope_fetch(items: list[dict], unresolved: list[str] | None = None) -> str:
    return json.dumps({
        "ok": True,
        "schema_version": 1,
        "cursor_type": "content",
        "doc_id": DOC,
        "build_id": BUILD,
        "scope_id": "scope-1",
        "view": "full",
        "items": items,
        "item_errors": [],
        "unresolved": unresolved or [],
        "next_cursor": None,
        "exhausted": True,
        "fetch_complete": not unresolved,
        "page_id": "fpage:x",
    }, ensure_ascii=False)


def _msg(*contents: str) -> list[dict]:
    return [{"role": "tool", "content": c} for c in contents]


# ── 四集合采集 ───────────────────────────────────────────────────────────


def test_offered_requested_fetched_recorded() -> None:
    ledger = ConsumptionLedger()
    ledger.record_search(_search_result())
    ledger.record_fetch_call({"doc_id": DOC, "locator": "chunk:c1"})
    ledger.record_fetch_result(_single_fetch("Q1 revenue 123 万元", kind="text"))

    assert len(ledger.offered) == 1
    assert ledger.offered[0]["locators"] == ["chunk:c1", "chunk:c2"]
    assert ledger.requested[0]["mode"] == "single"
    assert [ref.locator for ref in ledger.fetched] == ["chunk:c1"]
    assert ledger.fetched[0].start == 0
    assert ledger.fetched[0].end == len("Q1 revenue 123 万元")
    # 未核验前一律 unknown，不预设已送达。
    assert ledger.delivered_status(ledger.fetched[0].identity) == UNKNOWN


def test_search_dedupe_by_scope() -> None:
    ledger = ConsumptionLedger()
    ledger.record_search(_search_result())
    ledger.record_search(_search_result())
    assert len(ledger.offered) == 1


# ── delivered：最终消息边界核验 ──────────────────────────────────────────


def test_fragment_delivered_when_fully_present() -> None:
    text = "表格正文：营业收入 1,234 万元，同比增长 12%。"
    ledger = ConsumptionLedger()
    ledger.record_fetch_result(_single_fetch(text))
    ledger.finalize(_msg(_single_fetch(text)))
    assert ledger.delivered_status(ledger.fetched[0].identity) == DELIVERED


def test_fragment_truncated_when_head_capped() -> None:
    text = "营业收入明细：" + "0" * 400 + "期末余额 999 万元。"
    body = _single_fetch(text)
    ledger = ConsumptionLedger()
    ledger.record_fetch_result(body)
    # 模拟后处理 head-cap：JSON 在片段中途被切断。
    ledger.finalize(_msg(body[: int(len(body) * 0.6)]))
    assert ledger.delivered_status(ledger.fetched[0].identity) == TRUNCATED


def test_fragment_unknown_when_absent() -> None:
    text = "营业收入 1,234 万元。"
    ledger = ConsumptionLedger()
    ledger.record_fetch_result(_single_fetch(text))
    ledger.finalize(_msg("另一个完全不相关的工具结果"))
    assert ledger.delivered_status(ledger.fetched[0].identity) == UNKNOWN


def test_delivery_never_downgrades_across_paths() -> None:
    text = "营业收入 1,234 万元。"
    ledger = ConsumptionLedger()
    ledger.record_fetch_result(_single_fetch(text))
    ledger.finalize(_msg(_single_fetch(text)))  # delivered
    ledger.finalize(_msg("看不到"))  # 另一路径看不到 → 不得降级
    assert ledger.delivered_status(ledger.fetched[0].identity) == DELIVERED


# ── 范围完整性 ───────────────────────────────────────────────────────────


def test_range_incomplete_after_partial_fetch_and_skip() -> None:
    ledger = ConsumptionLedger()
    ledger.record_search(_search_result())
    ledger.record_fetch_result(_single_fetch("块一正文", locator="chunk:c1"))
    ledger.record_fetch_result(
        _envelope_fetch([], unresolved=["chunk:c2"]),
    )
    rows = ledger.range_completeness()
    assert len(rows) == 1
    row = rows[0]
    assert row["total"] == 2
    assert row["fetched"] == 1
    assert row["missing"] == ["chunk:c2"]
    assert row["skipped"] == ["chunk:c2"]
    assert row["complete"] is False
    assert ledger.all_offered_fetched() is False


def test_all_offered_fetched_none_without_offer() -> None:
    ledger = ConsumptionLedger()
    ledger.record_fetch_result(_single_fetch("正文"))
    assert ledger.all_offered_fetched() is None


# ── 结论证据校验 ─────────────────────────────────────────────────────────


def _manifest(*conclusions: dict, complete: bool | None = None) -> dict:
    return {"schema_version": 1, "conclusions": list(conclusions)}


def _resolver(texts: dict[str, str]):
    def resolve(doc_id: str, locator: str) -> str | None:
        return texts.get(f"{doc_id}|{locator}")
    return resolve


def test_conclusion_supported_when_quote_traced_and_delivered() -> None:
    text = "营业收入 1,234 万元（单位：万元）。"
    ledger = ConsumptionLedger()
    ledger.record_fetch_result(_single_fetch(text))
    ledger.finalize(_msg(_single_fetch(text)))

    manifest = _manifest({
        "id": "C1",
        "evidence": [{
            "doc_id": DOC, "locator": "chunk:c1",
            "quote": "营业收入 1,234 万元", "purpose": "value",
        }],
        "required_dependencies": ["value"],
    })
    result = verify_manifest(manifest, ledger, resolver=_resolver({f"{DOC}|chunk:c1": text}))
    assert result["conclusions"][0]["status"] == SUPPORTED
    assert result["status"] == PUBLISH_VERIFIED


def test_fabricated_quote_is_unsupported() -> None:
    text = "营业收入 1,234 万元。"
    ledger = ConsumptionLedger()
    ledger.record_fetch_result(_single_fetch(text))
    ledger.finalize(_msg(_single_fetch(text)))

    manifest = _manifest({
        "id": "C1",
        "evidence": [{
            "doc_id": DOC, "locator": "chunk:c1",
            "quote": "营业收入 9,999 亿元", "purpose": "value",
        }],
    })
    result = verify_manifest(manifest, ledger, resolver=_resolver({f"{DOC}|chunk:c1": text}))
    assert result["conclusions"][0]["status"] == UNSUPPORTED
    assert result["status"] == PUBLISH_UNSUPPORTED
    assert any(p["code"] == "quote_not_found"
               for p in result["conclusions"][0]["problems"])


def test_traceable_but_truncated_is_partial() -> None:
    text = "营业收入明细：" + "0" * 400 + "期末余额 999 万元。"
    body = _single_fetch(text)
    ledger = ConsumptionLedger()
    ledger.record_fetch_result(body)
    ledger.finalize(_msg(body[: int(len(body) * 0.6)]))

    manifest = _manifest({
        "id": "C1",
        "evidence": [{
            "doc_id": DOC, "locator": "chunk:c1",
            "quote": "期末余额 999 万元", "purpose": "value",
        }],
    })
    result = verify_manifest(manifest, ledger, resolver=_resolver({f"{DOC}|chunk:c1": text}))
    assert result["conclusions"][0]["status"] == "partial"
    assert result["status"] == PUBLISH_PARTIAL


def test_missing_declared_dependency_is_partial() -> None:
    text = "营业收入 1,234（单位：万元）。"
    ledger = ConsumptionLedger()
    ledger.record_fetch_result(_single_fetch(text))
    ledger.finalize(_msg(_single_fetch(text)))
    manifest = _manifest({
        "id": "C1",
        "evidence": [{
            "doc_id": DOC, "locator": "chunk:c1",
            "quote": "营业收入 1,234", "purpose": "value",
        }],
        # 声明需要单位，但没有任何证据用途覆盖 unit。
        "required_dependencies": ["value", "unit"],
    })
    result = verify_manifest(manifest, ledger, resolver=_resolver({f"{DOC}|chunk:c1": text}))
    assert result["conclusions"][0]["missing_dependencies"] == ["unit"]
    assert result["conclusions"][0]["status"] == "partial"


def test_model_claimed_complete_is_recorded_not_trusted() -> None:
    text = "营业收入 1,234 万元。"
    ledger = ConsumptionLedger()
    ledger.record_fetch_result(_single_fetch(text))
    ledger.finalize(_msg(_single_fetch(text)))
    manifest = _manifest({
        "id": "C1",
        "complete": True,  # 模型自报通过——必须被忽略
        "evidence": [{
            "doc_id": DOC, "locator": "chunk:c1",
            "quote": "根本不存在的数字 42", "purpose": "value",
        }],
    })
    result = verify_manifest(manifest, ledger, resolver=_resolver({f"{DOC}|chunk:c1": text}))
    assert result["conclusions"][0]["status"] == UNSUPPORTED
    assert result["conclusions"][0]["model_claimed_complete"] is True


def test_evidence_from_never_fetched_source_is_unknown_delivery() -> None:
    text = "营业收入 1,234 万元。"
    ledger = ConsumptionLedger()  # 从未 fetch
    manifest = _manifest({
        "id": "C1",
        "evidence": [{
            "doc_id": DOC, "locator": "chunk:c1",
            "quote": "营业收入 1,234", "purpose": "value",
        }],
    })
    result = verify_manifest(manifest, ledger, resolver=_resolver({f"{DOC}|chunk:c1": text}))
    assert result["conclusions"][0]["status"] == "partial"


# ── 落盘与 draft ─────────────────────────────────────────────────────────


def test_write_ledger_and_draft_without_manifest(tmp_path: Path) -> None:
    ledger = ConsumptionLedger(task_id="t1")
    ledger.record_search(_search_result())
    ledger.record_fetch_result(_single_fetch("营业收入 1,234 万元。"))
    ledger.finalize(_msg(_single_fetch("营业收入 1,234 万元。")))

    path = write_ledger(ledger, directory=tmp_path)
    assert path is not None and path.exists()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["offered"] and payload["fetched"] and payload["delivered"]

    # 缺清单：只能标 draft，且不声称已通过校验。
    verification = verify_and_record(ledger, directory=tmp_path)
    assert verification["status"] == PUBLISH_DRAFT
    assert load_manifest(directory=tmp_path) is None
    assert (tmp_path / "manifest_verification.json").exists()


def test_verify_and_record_reads_manifest_from_disk(tmp_path: Path) -> None:
    text = "营业收入 1,234 万元。"
    ledger = ConsumptionLedger()
    ledger.record_fetch_result(_single_fetch(text))
    ledger.finalize(_msg(_single_fetch(text)))
    (tmp_path / "manifest.json").write_text(json.dumps({
        "schema_version": 1,
        "conclusions": [{
            "id": "C1",
            "evidence": [{
                "doc_id": DOC, "locator": "chunk:c1",
                "quote": "营业收入 1,234", "purpose": "value",
            }],
        }],
    }, ensure_ascii=False), encoding="utf-8")

    result = verify_and_record(
        ledger, directory=tmp_path,
        resolver=_resolver({f"{DOC}|chunk:c1": text}),
    )
    assert result["status"] == PUBLISH_VERIFIED
    assert result["artifact_path"] is not None


# ── 观察者接线（观测模式）────────────────────────────────────────────────


def _turn(turn: int = 1) -> TurnContext:
    return TurnContext(
        turn=turn, max_turns=10, task_id="t1", role_id="stateful_react",
        ai_text="", thinking="", tool_calls=[], messages=[], usage=None, metadata={},
    )


async def test_observer_collects_and_finalizes(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("APODEX_RUN_DIR", str(tmp_path))
    ledger = ConsumptionLedger(task_id="t1")
    observer = ConsumptionLedgerObserver(task_id="t1", pipeline_id="stateful-react-agent",
                                         ledger=ledger)
    text = "营业收入 1,234 万元。"
    body = _single_fetch(text)

    await observer.on_tool_result(
        _turn(), ToolResult(name="corpus_search", args={}, result=_search_result(),
                            duration_ms=1, tool_call_id="x", is_error=False),
    )
    await observer.on_tool_call(_turn(), {"name": "corpus_fetch", "id": "y",
                                          "args": {"doc_id": DOC, "locator": "chunk:c1"}})
    await observer.on_tool_result(
        _turn(), ToolResult(name="corpus_fetch", args={}, result=body,
                            duration_ms=1, tool_call_id="y", is_error=False),
    )
    await observer.on_loop_end(AgentLoopResult(messages=_msg(body)))
    assert ledger.offered and ledger.requested and ledger.fetched
    assert ledger.delivered_status(ledger.fetched[0].identity) == DELIVERED
    assert (tmp_path / "corpus" / "ledger.json").exists()


async def test_reporter_boundary_writes_verification(tmp_path: Path, monkeypatch) -> None:
    """agent_team 报告边界必须触发 A4 校验并落盘（缺清单 → draft）。"""
    monkeypatch.setenv("APODEX_RUN_DIR", str(tmp_path))
    from workflows.agent_team.nodes import reporter as reporter_mod

    reset_run_ledgers()
    get_run_ledger()

    async def _fake_report(state, ctx):
        return "# 报告\n\n营业收入 1,234 万元。"

    monkeypatch.setattr(
        "workflows.agent_team.nodes.fast_reporter_v1._run_fast_reporter",
        _fake_report,
    )
    monkeypatch.setattr(reporter_mod, "_refresh_trace_terminal", lambda *a, **k: None)

    out = await reporter_mod.agent_team_reporter({"reporter_backend": "fast"}, object())

    assert out["final_answer"]
    verification = json.loads(
        (tmp_path / "corpus" / "manifest_verification.json").read_text(encoding="utf-8"),
    )
    assert verification["status"] == PUBLISH_DRAFT
