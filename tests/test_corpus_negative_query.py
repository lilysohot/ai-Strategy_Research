"""F1 永驻测试：负例判定层拒检门（negative_query）+ 评分耦合。

F1（issues/06）把 6 条 no-answer 题的 retrieved_documents 从 5 降到 0（M6 硬判据）。
机制是纯消费侧判定层兜底：收紧查询（全部内容词元 websearch AND）+ 拒检谓词（同一单元
满足全部内容词元）。**不触 search_pg/scoring 字节**，只作用于 no-answer 题的观测构造，
与有答案题的 OR 查询 / S1 命中池完全独立（I-M6-2 结构性零扰动）。

验收（issues/06）：
- I-M6-1：任一被裁 answer_existence = no_answer 的题，retrieved_documents == 0 ⇒ 计分不误报。
- I-M6-2：有答案题 79 目标漏斗 S1_candidates 恒 66 不降（由 f1_backtest 在真实语料上断言；
  本文件在纯函数层验证收紧查询只按给定词元变换、不触碰有答案题 OR 路径）。
- 反例：构造"expected=0 但单个低频 token 命中"的伪负例，断言拒检生效。

全部为合成输入：不读真实金标、不跑检索、不触 PG/模型/网络。
"""

from __future__ import annotations

from plugins.corpus.preparation.negative_query import (
    content_lexemes,
    is_relevant_candidate,
    tighten_no_answer_query,
)
from plugins.corpus.scoring import (
    AnswerExistence,
    FailureCode,
    GoldQuestion,
    ObservationOutcome,
    QueryObservation,
    RetrievedDocument,
    score,
)

# ── tighten_no_answer_query / content_lexemes：收紧查询变换 ──


def test_tighten_ands_all_content_terms_quoted() -> None:
    lexemes = ["美联储", "会议", "利率", "决定", "正式", "2026", "的"]
    out = tighten_no_answer_query(lexemes)
    assert "的" not in out
    for term in ("美联储", "会议", "利率", "决定", "正式", "2026"):
        assert f'"{term}"' in out
    assert " AND " not in out  # websearch：空格即 AND，不再注入字面 AND
    # 全部内容词元在同一个查询里，且不带 OR 分叉（词元间仅空格）
    assert out == '"美联储" "会议" "利率" "决定" "正式" "2026"'


def test_tighten_keeps_ordering_after_strip() -> None:
    # 停用/单字被剔除后，内容词元保持原序
    assert tighten_no_answer_query(["给出", "光力", "科技", "2027", "经审", "是"])\
        == '"光力" "科技" "2027" "经审"'
    assert content_lexemes(["给出", "光力", "科技", "2027", "经审", "是"])\
        == ("光力", "科技", "2027", "经审")


def test_tighten_empty_when_no_content() -> None:
    assert tighten_no_answer_query(["给出", "是否", "的", "能", "份"]) == ""  # 无内容词元
    assert tighten_no_answer_query(["这", "六", "份"]) == ""


# ── is_relevant_candidate：判定层拒检谓词 ──


def test_pseudo_negative_single_low_freq_token_is_rejected() -> None:
    # 反例：expected=0，OR 只靠单个低频词元"利率"命中，但单元不满足"全部内容词元"。
    lexemes = ["美联储", "2026", "9", "会议", "利率", "决定"]
    unit = "非农就业超预期，市场关于利率的猜测再度升温。"  # 只含"利率"，缺美联储/会议/决定等
    assert is_relevant_candidate(unit, lexemes) is False


def test_relevant_candidate_requires_full_content_set() -> None:
    lexemes = ["美联储", "会议", "利率", "决定"]
    full = "美联储9月议息会议决定维持利率不变"
    partial = "会议纪要强调利率路径取决于数据"  # 缺美联储/决定
    assert is_relevant_candidate(full, lexemes) is True
    assert is_relevant_candidate(partial, lexemes) is False


def test_relevant_candidate_whitespace_normalized() -> None:
    unit = "美联储\n议息  会议\n正式  决定利率"
    assert is_relevant_candidate(unit, ["美联储", "会议", "决定", "利率"]) is True


def test_relevant_candidate_empty_content_false() -> None:
    assert is_relevant_candidate("任何文本", ["是否", "给出", "的"]) is False


# ── I-M6-1：no-answer + 拒检（空观测）⇒ 不误报 ──


def _neg(qid: str, domain: str = "company") -> GoldQuestion:
    return GoldQuestion(query_id=qid, domain=domain, question="能否给出X？",
                        answer_existence=AnswerExistence.NO_ANSWER)


def test_no_answer_empty_observation_not_false_positive() -> None:
    q = _neg("company-900")
    obs = QueryObservation(query_id=q.query_id,
                           outcome=ObservationOutcome.NO_MATCH, documents=())
    (item,) = score((q,), (obs,)).questions
    assert item.false_positive is False
    assert not any(str(FailureCode.NO_ANSWER_FALSE_POSITIVE) in f for f in item.failures)


def test_no_answer_with_documents_is_false_positive() -> None:
    q = _neg("company-901")
    obs = QueryObservation(query_id=q.query_id, documents=(RetrievedDocument("src-x"),))
    (item,) = score((q,), (obs,)).questions
    assert item.false_positive is True
    assert any(f == str(FailureCode.NO_ANSWER_FALSE_POSITIVE) for f in item.failures)


def test_total_eq_zero_observations_then_zero_false_positives() -> None:
    qu = [_neg(f"company-90{i}") for i in range(3)]
    obs = [QueryObservation(q.query_id, outcome=ObservationOutcome.NO_MATCH)
           for q in qu]
    report = score(tuple(qu), tuple(obs))
    assert report.false_positives == ()


# ── I-M6-2：收紧查询只按给定词元变换，不触碰有答案题 OR 路径 ──


def test_tighten_is_pure_transform_of_given_lexemes() -> None:
    # 收紧查询是**纯函数**：只对传入的词元序列做 AND 连接；有答案题的 OR 查询不经由本模块，
    # 因此 F1 对 S1 命中池结构性零扰动。
    lexemes = ["光力", "科技", "净利润"]
    before = tuple(lexemes)
    tighten_no_answer_query(lexemes)
    assert tuple(lexemes) == before  # 不改变/不消费调用方的词元
    # 词元不变 ⇒ 与有答案题共享的检索输入不做任何改写
    assert content_lexemes(lexemes) == tuple(lexemes)