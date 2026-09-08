"""投研引用纪律的注入链路测试（issue 10）。

TUI 侧**没有**结构化输入通道（``apodex/`` 下搜 ``addendum`` 曾零命中），
所以纪律只能走 profile → ``metadata["_sys_prompt_addendum"]`` → workflow 系统提示词
这条链路。本文件锁死这条链路：一旦它断了，「缺失参数必须追问」这类要求
就退化成文档里的一句口号。
"""

from __future__ import annotations

import pytest

from apodex.profiles import _resolve_addendum, get_profile
from plugins.corpus.research_discipline import RESEARCH_DISCIPLINE_ADDENDUM

# 纪律文本必须覆盖的要点。改动提示词时这里会先红，提醒同步
# docs/p0-implementation-spec.md §3.5。
_REQUIRED_MENTIONS = (
    "position_sizing",   # 算术纪律
    "strategy_lint",     # 落卡前校验
    "computed_by",       # 硬闸②
    "风险预算",           # 缺失参数必须追问
    "source_ref",        # 数字可溯源
)


def test_discipline_covers_every_required_point() -> None:
    for token in _REQUIRED_MENTIONS:
        assert token in RESEARCH_DISCIPLINE_ADDENDUM, token


def test_react_profile_resolves_the_discipline_addendum() -> None:
    addendum = get_profile("react").prompt_addendum
    assert addendum == RESEARCH_DISCIPLINE_ADDENDUM
    for token in _REQUIRED_MENTIONS:
        assert token in addendum, token


def test_react_profile_binds_the_finance_tools() -> None:
    names = {getattr(t, "name", "") for t in get_profile("react").tools()}
    assert {"position_sizing", "strategy_lint"} <= names


def test_profiles_without_an_addendum_get_an_empty_string() -> None:
    assert _resolve_addendum({}) == ""


def test_literal_addendum_is_used_when_no_ref_is_set() -> None:
    assert _resolve_addendum({"system_prompt_addendum": "inline"}) == "inline"


def test_ref_wins_over_literal_text() -> None:
    # ref 是权威来源：避免两份文本并存时静默分叉
    agent = {
        "system_prompt_addendum": "stale copy",
        "system_prompt_addendum_ref": (
            "plugins.corpus.research_discipline:RESEARCH_DISCIPLINE_ADDENDUM"
        ),
    }
    assert _resolve_addendum(agent) == RESEARCH_DISCIPLINE_ADDENDUM


def test_malformed_refs_fail_loudly() -> None:
    # 静默降级会让纪律块消失，而这正是本项目最不能接受的一类失败
    with pytest.raises(ValueError, match=r"pkg\.mod:CONST"):
        _resolve_addendum({"system_prompt_addendum_ref": "no_colon_here"})
    with pytest.raises(ValueError, match="could not be resolved"):
        _resolve_addendum({"system_prompt_addendum_ref": "plugins.corpus.nope:NOPE"})
