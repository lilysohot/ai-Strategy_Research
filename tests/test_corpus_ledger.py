"""A4 消费账本与结论证据校验测试（offered/requested/fetched/delivered + 两类完整性）。

覆盖 docs/data_clean_dos/01-table-recovery.md §2 的「消费判定」与「结论证据」两类场景：
服务取回但后处理截断、只读部分片段、显式跳过、范围缩小；正文已有有效证据、
缺单位／期间／脚注、表头错配；以及「缺清单只能标 draft」「模型自报 complete 不采信」。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from frontier_agent.core.loop_types import AgentLoopResult, ToolResult, TurnContext
from plugins.corpus.ledger import (
    DELIVERED,
    PARTIAL,
    PUBLISH_DRAFT,
    PUBLISH_PARTIAL,
    PUBLISH_UNSUPPORTED,
    PUBLISH_VERIFICATION_ERROR,
    PUBLISH_VERIFIED,
    SUPPORTED,
    TRUNCATED,
    UNKNOWN,
    UNSUPPORTED,
    ConsumptionLedger,
    ConsumptionLedgerObserver,
    enforcement_enabled,
    get_run_ledger,
    load_manifest,
    load_manifest_files,
    publish_boundary,
    reset_run_ledgers,
    verify_and_record,
    verify_manifest,
    write_ledger,
    write_manifest_file,
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
    assert payload["schema_version"] == 2
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
    # 评审 C5：无 corpus 活动的 run 在边界直接 skip（非语料任务不写工件），
    # 先给 run 账本播种一次取回，才能走到「缺清单 → draft」的校验路径。
    ledger = get_run_ledger()
    ledger.record_fetch_result(_single_fetch("营业收入 1,234 万元。"))

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


# ── 评审反例回归（C1／C2／C7）────────────────────────────────────────────


def _two_fragment_ledger() -> tuple[ConsumptionLedger, str]:
    """两片段信封：只有首段真正进入最终消息（第二段被预算挤出）。"""
    text = "甲" * 200 + "乙" * 200
    first = {"locator": "chunk:c1", "text": "甲" * 200,
             "fragment": {"start": 0, "end": 200, "of_chars": 400}}
    second = {"locator": "chunk:c1", "text": "乙" * 200,
              "fragment": {"start": 200, "end": 400, "of_chars": 400}}
    ledger = ConsumptionLedger()
    ledger.record_fetch_result(_envelope_fetch([first, second]))
    ledger.finalize(_msg(json.dumps({"ok": True, "items": [first]}, ensure_ascii=False)))
    return ledger, text


def test_c1_quote_in_delivered_region_supported() -> None:
    ledger, text = _two_fragment_ledger()
    manifest = _manifest({"id": "C1", "evidence": [
        {"doc_id": DOC, "locator": "chunk:c1", "quote": "甲" * 50, "purpose": "value"}]})
    result = verify_manifest(
        manifest, ledger, resolver=_resolver({f"{DOC}|chunk:c1": text}),
    )
    assert result["conclusions"][0]["status"] == SUPPORTED
    assert result["status"] == PUBLISH_VERIFIED


def test_c1_quote_in_undelivered_region_is_partial_not_supported() -> None:
    """评审 C1：引文区间必须被已送达片段覆盖——只读首段不等于整块送达。

    旧判定「locator 出现过即 delivered」会把未送达区间里的引文误判 supported。
    """
    ledger, text = _two_fragment_ledger()
    manifest = _manifest({"id": "C1", "evidence": [
        {"doc_id": DOC, "locator": "chunk:c1", "quote": "乙" * 50, "purpose": "value"}]})
    result = verify_manifest(
        manifest, ledger, resolver=_resolver({f"{DOC}|chunk:c1": text}),
    )
    row = result["conclusions"][0]
    assert row["status"] == PARTIAL
    assert any(p["code"] == "not_delivered" for p in row["problems"])
    assert result["status"] == PUBLISH_PARTIAL


def test_c2_invalid_evidence_element_rejected() -> None:
    """评审 C2：``evidence:[null]`` 必须拒绝登记——静默跳过会让零有效证据伪装通过。"""
    text = "营业收入 1,234 万元。"
    ledger = ConsumptionLedger()
    ledger.record_fetch_result(_single_fetch(text))
    ledger.finalize(_msg(_single_fetch(text)))
    manifest = _manifest({"id": "C1", "evidence": [None], "complete": True})
    result = verify_manifest(
        manifest, ledger, resolver=_resolver({f"{DOC}|chunk:c1": text}),
    )
    row = result["conclusions"][0]
    assert row["status"] == UNSUPPORTED
    assert any(p["code"] == "invalid_evidence" for p in row["problems"])
    assert result["status"] == PUBLISH_UNSUPPORTED


def test_c2_non_dict_conclusion_rejected() -> None:
    ledger = ConsumptionLedger()
    result = verify_manifest(_manifest("不是对象"), ledger)
    row = result["conclusions"][0]
    assert row["status"] == UNSUPPORTED
    assert row["problems"][0]["code"] == "invalid_conclusion"
    assert result["status"] == PUBLISH_UNSUPPORTED


def test_c7_infra_failure_is_verification_error_not_gap() -> None:
    """评审 C7：resolver 基础设施故障 → verification_error，整体不可信。"""
    text = "营业收入 1,234 万元。"
    ledger = ConsumptionLedger()
    ledger.record_fetch_result(_single_fetch(text))
    ledger.finalize(_msg(_single_fetch(text)))

    def boom(doc_id: str, locator: str) -> str | None:
        raise ConnectionError("store unavailable")

    result = verify_manifest(
        _manifest({"id": "C1", "evidence": [
            {"doc_id": DOC, "locator": "chunk:c1", "quote": "营业收入", "purpose": "value"}]}),
        ledger, resolver=boom,
    )
    assert result["status"] == PUBLISH_VERIFICATION_ERROR
    assert any(
        p["code"] == "verification_error"
        for p in result["conclusions"][0]["problems"]
    )


def test_c7_deterministic_refusal_is_source_unresolvable() -> None:
    """评审 C7：确定性拒绝（来源无法解析）→ 结论缺口，不与基础设施故障混同。"""
    text = "营业收入 1,234 万元。"
    ledger = ConsumptionLedger()
    ledger.record_fetch_result(_single_fetch(text))
    ledger.finalize(_msg(_single_fetch(text)))
    result = verify_manifest(
        _manifest({"id": "C1", "evidence": [
            {"doc_id": DOC, "locator": "chunk:c1", "quote": "营业收入", "purpose": "value"}]}),
        ledger, resolver=lambda d, loc: None,
    )
    assert result["status"] == PUBLISH_UNSUPPORTED
    assert any(
        p["code"] == "source_unresolvable"
        for p in result["conclusions"][0]["problems"]
    )


# ── 报告绑定（评审 C4）───────────────────────────────────────────────────


def test_report_anchor_absent_from_final_text_presses_partial() -> None:
    """report_quote 不在最终报告 → not_in_report 压 partial，不虚报 supported。"""
    text = "营业收入 1,234 万元。"
    ledger = ConsumptionLedger()
    ledger.record_fetch_result(_single_fetch(text))
    ledger.finalize(_msg(_single_fetch(text)))
    manifest = _manifest({"id": "C1", "report_quote": "这句话不在报告里", "evidence": [
        {"doc_id": DOC, "locator": "chunk:c1", "quote": "营业收入 1,234", "purpose": "value"}]})
    result = verify_manifest(
        manifest, ledger, resolver=_resolver({f"{DOC}|chunk:c1": text}),
        final_text="# 最终报告\n\n别的结论。",
    )
    row = result["conclusions"][0]
    assert any(p["code"] == "not_in_report" for p in row["problems"])
    assert row["status"] == PARTIAL
    assert result["status"] == PUBLISH_PARTIAL


def test_verify_and_record_binds_report_sha256(tmp_path: Path) -> None:
    text = "营业收入 1,234 万元。"
    final_text = f"报告：{text}"
    ledger = ConsumptionLedger()
    ledger.record_fetch_result(_single_fetch(text))
    ledger.finalize(_msg(_single_fetch(text)))
    write_manifest_file({
        "schema_version": 2,
        "conclusions": [{"id": "C1", "report_quote": text, "evidence": [
            {"doc_id": DOC, "locator": "chunk:c1", "quote": text, "purpose": "value"}]}],
    }, directory=tmp_path)
    verification = verify_and_record(
        ledger, directory=tmp_path,
        resolver=_resolver({f"{DOC}|chunk:c1": text}), final_text=final_text,
    )
    assert verification["status"] == PUBLISH_VERIFIED
    assert verification["report_sha256"] == hashlib.sha256(
        final_text.encode("utf-8"),
    ).hexdigest()
    assert verification["report_chars"] == len(final_text)


# ── 子清单独立落盘与聚合（评审 C4）───────────────────────────────────────


def test_manifest_files_never_overwrite_and_merge_with_owner_prefix(tmp_path: Path) -> None:
    """多代理提交写独立子清单互不覆盖；聚合时结论 id 加拥有者前缀防撞。"""
    p1 = write_manifest_file({"schema_version": 2, "owner_role": "lit_search",
                              "conclusions": [{"id": "C1"}]}, directory=tmp_path)
    p2 = write_manifest_file({"schema_version": 2, "owner_role": "final_verify",
                              "conclusions": [{"id": "C1"}]}, directory=tmp_path)
    assert p1 is not None and p2 is not None and p1 != p2
    assert p1.name == "manifest-000.json" and p2.name == "manifest-001.json"

    files = load_manifest_files(directory=tmp_path)
    assert [path.name for path, _ in files] == ["manifest-000.json", "manifest-001.json"]

    ledger = ConsumptionLedger()
    verification = verify_and_record(ledger, directory=tmp_path, resolver=lambda d, loc: None)
    assert [row["id"] for row in verification["conclusions"]] == [
        "lit_search/C1", "final_verify/C1",
    ]


def test_manifest_files_fall_back_to_legacy_single_file(tmp_path: Path) -> None:
    (tmp_path / "manifest.json").write_text(
        json.dumps({"schema_version": 1, "conclusions": []}, ensure_ascii=False),
        encoding="utf-8",
    )
    files = load_manifest_files(directory=tmp_path)
    assert len(files) == 1 and files[0][0].name == "manifest.json"


# ── 发布边界四态（评审 C5／C6）───────────────────────────────────────────


def test_boundary_skips_runs_without_corpus_activity(tmp_path: Path) -> None:
    """评审 C5：非语料任务的 run 在边界 skip，不写校验工件。"""
    out = publish_boundary(
        ConsumptionLedger(), final_text="报告", answer_status="complete",
        directory=tmp_path,
    )
    assert out["boundary_action"] == "skip"
    assert not (tmp_path / "manifest_verification.json").exists()


def test_boundary_observe_by_default_records_without_blocking(tmp_path: Path, monkeypatch) -> None:
    """默认（A4_ENFORCE 关闭）：缺清单 → draft 记录工件，但发布文本原样放行。"""
    monkeypatch.delenv("A4_ENFORCE", raising=False)
    text = "营业收入 1,234 万元。"
    ledger = ConsumptionLedger()
    ledger.record_fetch_result(_single_fetch(text))
    ledger.finalize(_msg(_single_fetch(text)))
    out = publish_boundary(
        ledger, final_text="报告正文", answer_status="complete", directory=tmp_path,
    )
    assert out["boundary_action"] == "observe"
    assert out["publish_status"] == PUBLISH_DRAFT
    assert out["final_text"] == "报告正文"
    assert out["answer_status"] == "complete"
    assert (tmp_path / "manifest_verification.json").exists()


def test_boundary_downgrades_under_enforce_with_anchored_block(
    tmp_path: Path, monkeypatch,
) -> None:
    """评审 C6：enforce 开启时未通过 → 追加锚定限定块（草稿保留，只加不删）。"""
    monkeypatch.setenv("A4_ENFORCE", "1")
    text = "营业收入 1,234 万元。"
    ledger = ConsumptionLedger()
    ledger.record_fetch_result(_single_fetch(text))
    ledger.finalize(_msg(_single_fetch(text)))
    out = publish_boundary(
        ledger, final_text="报告正文", answer_status="complete", directory=tmp_path,
    )
    assert out["boundary_action"] == "downgrade"
    assert out["final_text"].startswith("报告正文")  # 原报告保留
    assert "证据完整性校验（A4）" in out["final_text"]
    assert out["answer_status"] == "partial"  # complete 降级


def test_boundary_enforce_keeps_non_complete_answer_status(
    tmp_path: Path, monkeypatch,
) -> None:
    """not_found／best_effort 不往弱处反向升级。"""
    monkeypatch.setenv("A4_ENFORCE", "1")
    text = "营业收入 1,234 万元。"
    ledger = ConsumptionLedger()
    ledger.record_fetch_result(_single_fetch(text))
    ledger.finalize(_msg(_single_fetch(text)))
    out = publish_boundary(
        ledger, final_text="报告正文", answer_status="not_found", directory=tmp_path,
    )
    assert out["boundary_action"] == "downgrade"
    assert out["answer_status"] == "not_found"


def test_boundary_publishes_when_verified(tmp_path: Path) -> None:
    text = "营业收入 1,234 万元。"
    ledger = ConsumptionLedger()
    ledger.record_fetch_result(_single_fetch(text))
    ledger.finalize(_msg(_single_fetch(text)))
    write_manifest_file({
        "schema_version": 2,
        "conclusions": [{"id": "C1", "report_quote": text, "evidence": [
            {"doc_id": DOC, "locator": "chunk:c1", "quote": text, "purpose": "value"}]}],
    }, directory=tmp_path)
    out = publish_boundary(
        ledger, final_text=f"报告：{text}", answer_status="complete", directory=tmp_path,
        resolver=_resolver({f"{DOC}|chunk:c1": text}),
    )
    assert out["boundary_action"] == "publish"
    assert out["publish_status"] == PUBLISH_VERIFIED
    assert out["answer_status"] == "complete"


def test_enforcement_flag_parsing(monkeypatch) -> None:
    for raw in ("1", "true", "Yes", "ON"):
        monkeypatch.setenv("A4_ENFORCE", raw)
        assert enforcement_enabled() is True
    monkeypatch.delenv("A4_ENFORCE", raising=False)
    assert enforcement_enabled() is False
    for raw in ("", "0", "false", "off"):
        monkeypatch.setenv("A4_ENFORCE", raw)
        assert enforcement_enabled() is False
