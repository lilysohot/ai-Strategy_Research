"""A cut-off run or a progress note must not be published as ``complete``."""

from __future__ import annotations

from workflows.stateful_react_agent.nodes.main_agent import _downgrade_unfinished

ANSWER = (
    "光力科技2025年半导体封测装备制造业务收入为 3.62 亿元，同比增长 31.16%，"
    "占营业收入的 53.99%。来源：国信中报点评，doc_id=cv2:568f，locator=chunk:native1/568f/abc。"
)


def test_infra_stop_is_never_complete() -> None:
    for reason in ("llm_error", "wall_deadline", "budget_exhausted", "max_attempts"):
        assert _downgrade_unfinished("complete", reason, ANSWER) == "partial"


def test_progress_tail_is_not_complete() -> None:
    text = "已定位到相关研报，正在取回逐字原文确认。"
    assert _downgrade_unfinished("complete", "no_tool", text) == "partial"

    text = "已取到 p4 数据段，接下来继续提交清单进行回验。"
    assert _downgrade_unfinished("complete", "no_tool", text) == "partial"


def test_trailing_colon_is_not_complete() -> None:
    assert _downgrade_unfinished("complete", "no_tool", "结论如下：") == "partial"


def test_finished_answer_stays_complete() -> None:
    assert _downgrade_unfinished("complete", "no_tool", ANSWER) == "complete"


def test_other_statuses_are_untouched() -> None:
    assert _downgrade_unfinished("best_effort", "llm_error", "半成品") == "best_effort"
    assert _downgrade_unfinished("not_found", "llm_error", "") == "not_found"


def test_empty_text_is_partial() -> None:
    assert _downgrade_unfinished("complete", "no_tool", "   ") == "partial"
