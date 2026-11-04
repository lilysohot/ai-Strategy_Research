"""Regressions minimized from Web run b0a4261742b64931804ae5b64b14b4a5."""

import hashlib

import pytest

from workflows.agent_team.final_report import finalize_team_report


def publish(text, **kwargs):
    return finalize_team_report(
        text,
        source="agent",
        answer_status="complete",
        stopped_by="final_answer",
        question="交叉论述架构差异",
        language="auto",
        **kwargs,
    )


@pytest.mark.parametrize(
    "text",
    [
        "原文声称判断“各个 Worker 是否有实质进展、方向是否偏离整体目标”（逐字核验通过）。",
        "所有原文引文均由核验员用程序化检索回查。",
        "全文由核验员阅读，尚有两项未核实。",
        "[估算] 在串行处理且负载不变的假设下，容量约 43 trigger/min。",
        "我认为这是一个潜在的工程范式节点；五次合成实验不足以证明普遍优势。",
        "并非所有结论均已核验。",
        "所有结果核验失败，尚不能确认。",
        "计划对全文核验，完成后再报告。",
        "全文核验尚未完成。",
    ],
)
def test_scoped_fidelity_and_analysis_survive_publication(text):
    out = publish(text)
    assert out["answer_status"] == "complete"
    assert out["final_answer"] == text


def test_local_assurance_removed_without_losing_analysis_or_original_candidate():
    draft = "全部数字均已核对。\n\n[估算] 在串行假设下容量约 43 trigger/min。"
    out = publish(draft)
    assert out["answer_status"] == "partial"
    assert "全部数字均已核对" not in out["final_answer"]
    assert "[估算] 在串行假设下容量约 43 trigger/min。" in out["final_answer"]
    audit = out["report_contract"]["publication"]
    assert audit["status"] == "revised"
    assert audit["candidate_text"] == draft
    assert audit["candidate_sha256"] == hashlib.sha256(draft.encode()).hexdigest()
    finding = audit["findings"][0]
    assert finding["rule"] == "blanket_verification"
    assert draft[finding["start"] : finding["end"]] == finding["sentence"]
    assert finding["match"] == "全部数字均已核对"
    assert finding["reason"]
    assert "synthesis_unavailable" not in {g["code"] for g in out["report_contract"]["gaps"]}


def test_only_assurance_is_withheld_with_accurate_status_and_chinese_auto_language():
    draft = "整份报告已经完成核验。"
    out = publish(draft)
    assert out["answer_status"] == "not_found"
    assert out["report_contract"]["publication"]["status"] == "withheld"
    assert "候选正文已生成" in out["final_answer"]
    assert "提前收尾" not in out["final_answer"]
    assert "at the limit" not in out["final_answer"]
    assert "最终综合未形成" not in out["final_answer"]
    codes = {g["code"] for g in out["report_contract"]["gaps"]}
    assert "publication_withheld" in codes
    assert not codes & {"synthesis_unavailable", "invalid_user_report"}


def test_empty_normal_completion_does_not_claim_timeout():
    out = publish("")
    assert out["answer_status"] == "not_found"
    assert out["report_contract"]["publication"]["status"] == "unavailable"
    assert "提前收尾" not in out["final_answer"]
    assert "上限" not in out["final_answer"]


def test_report_wide_quote_assurance_is_not_inherited_from_source_checks():
    out = publish("本答复所有原文引文均已核验通过。\n\n这是一个可能的工程节点。")
    assert out["answer_status"] == "partial"
    assert "本答复所有原文引文均已核验通过" not in out["final_answer"]
    assert "这是一个可能的工程节点。" in out["final_answer"]


@pytest.mark.parametrize(
    "claim",
    [
        "所有数据均已核验通过。",
        "全部核验通过。",
        "全文核验完成。",
        "本答复所有原文引文均由核验员用程序化检索回查。",
        "All findings are verified.",
        "The whole report is fully verified.",
    ],
)
def test_explicit_blanket_assurances_remain_detectable(claim):
    out = publish(claim)
    assert out["answer_status"] == "not_found"
    assert out["report_contract"]["publication"]["findings"]


def test_original_candidate_preserved_before_control_cleaning():
    draft = r"全文已核验。结论：\"估算\"仍待验证。"
    out = publish(draft)
    audit = out["report_contract"]["publication"]
    assert audit["candidate_text"] == draft
    assert audit["candidate_sha256"] == hashlib.sha256(draft.encode()).hexdigest()
    for finding in audit["findings"]:
        assert audit["examined_text"][finding["start"] : finding["end"]] == finding["sentence"]


def test_headings_and_list_numbers_are_not_deliverable_after_omission():
    out = publish("## 结论\n\n1. 全文已核验。")
    assert out["answer_status"] == "not_found"
    assert out["report_contract"]["publication"]["status"] == "withheld"
