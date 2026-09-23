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

import asyncio

import pytest

from plugins.corpus.preparation.negative_query import (
    content_lexemes,
    is_corpus_availability_query,
    is_relevant_candidate,
    tighten_no_answer_query,
)
from plugins.corpus.preparation.repository import StoreError
from plugins.corpus.scoring import (
    AnswerExistence,
    FailureCode,
    GoldQuestion,
    ObservationOutcome,
    QueryObservation,
    RetrievedDocument,
    score,
)
from plugins.corpus.service import CorpusService

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
    assert (
        tighten_no_answer_query(["给出", "光力", "科技", "2027", "经审", "是"])
        == '"光力" "科技" "2027" "经审"'
    )
    assert content_lexemes(["给出", "光力", "科技", "2027", "经审", "是"]) == (
        "光力",
        "科技",
        "2027",
        "经审",
    )


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
    return GoldQuestion(
        query_id=qid,
        domain=domain,
        question="能否给出X？",
        answer_existence=AnswerExistence.NO_ANSWER,
    )


def test_no_answer_empty_observation_not_false_positive() -> None:
    q = _neg("company-900")
    obs = QueryObservation(query_id=q.query_id, outcome=ObservationOutcome.NO_MATCH, documents=())
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
    obs = [QueryObservation(q.query_id, outcome=ObservationOutcome.NO_MATCH) for q in qu]
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


# ── B2：产品 abstain 拒检通道接线（服务层判定逻辑，合成输入，不触 PG）──


@pytest.mark.parametrize(
    "query",
    [
        "这六份开发材料能否给出2027年经审计的实际利润？",
        "这些研究报告是否披露设备唯一序列号？",
        "当前语料有没有提供已签署合同的确切吨数？",
    ],
)
def test_corpus_availability_intent_is_detected(query: str) -> None:
    assert is_corpus_availability_query(query) is True


@pytest.mark.parametrize(
    "query",
    [
        "能否把价格分位和价格涨幅当成同一种指标？",
        "报告中的收入和利润分别是多少？",
        "公司是否维持强推评级？",
    ],
)
def test_ordinary_research_question_is_not_availability_intent(query: str) -> None:
    assert is_corpus_availability_query(query) is False


@pytest.fixture()
def svc(monkeypatch: pytest.MonkeyPatch) -> CorpusService:
    """只依赖合成输入的 Fake 服务：read_chain 钉死 new，判定层 DB 依赖按需打桩。"""
    svc = CorpusService("postgresql://fake/nowhere")
    monkeypatch.setattr(svc, "read_chain", lambda: "new")
    return svc


def _monkey_setenv(monkeypatch: pytest.MonkeyPatch, value: str | None) -> None:
    if value is None:
        monkeypatch.delenv("CORPUS_ABSTAIN_NO_ANSWER", raising=False)
    else:
        monkeypatch.setenv("CORPUS_ABSTAIN_NO_ANSWER", value)


def test_abstain_switch_off_never_abstains(
    svc: CorpusService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """显式 off：恒不拒检，且完全不触碰检索/判定路径（回滚开关）。"""
    _monkey_setenv(monkeypatch, "off")
    # 若误调 DB 检索，判为失败：off 下判定层必须短路。
    monkeypatch.setattr(
        "plugins.corpus.preparation.search_pg.query_lexemes",
        lambda *a, **k: pytest.fail("off 不应触碰判定层检索"),
    )
    assert svc._abstain_decision("任意查询") is False


def test_abstain_defaults_on_for_corpus_availability_query(
    svc: CorpusService, monkeypatch: pytest.MonkeyPatch
) -> None:
    _monkey_setenv(monkeypatch, None)
    monkeypatch.setattr(
        "plugins.corpus.preparation.search_pg.query_lexemes",
        lambda *a, **k: ("审计", "利润"),
    )
    monkeypatch.setattr(
        "plugins.corpus.preparation.search_pg.search_chunks",
        lambda *a, **k: (),
    )
    assert svc._abstain_decision("这些报告是否提供经审计利润？") is True


def test_abstain_illegal_switch_fails_closed(
    svc: CorpusService, monkeypatch: pytest.MonkeyPatch
) -> None:
    _monkey_setenv(monkeypatch, "bogus")
    with pytest.raises(StoreError, match="CORPUS_ABSTAIN_NO_ANSWER"):
        svc._abstain_decision("查询")


def test_abstain_on_rejects_when_and_query_empty(
    svc: CorpusService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """on + websearch AND 预检归零 → 拒检（真负例主门，零 fetch）。"""
    _monkey_setenv(monkeypatch, "on")
    monkeypatch.setattr(
        "plugins.corpus.preparation.search_pg.query_lexemes",
        lambda *a, **k: ("美联储", "会议", "利率"),
    )
    monkeypatch.setattr(
        "plugins.corpus.preparation.search_pg.search_chunks",
        lambda *a, **k: (),
    )
    assert svc._abstain_decision("这些报告能否给出2026年9月美联储会议利率决定？") is True


def test_abstain_on_rejects_when_all_units_incidental(
    svc: CorpusService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """on + 收紧仍有命中，但命中单元的原文均不满足全部内容词元 → 拒检（保险带）。"""
    _monkey_setenv(monkeypatch, "on")
    monkeypatch.setattr(
        "plugins.corpus.preparation.search_pg.query_lexemes",
        lambda *a, **k: ("美联储", "会议", "利率", "决定"),
    )
    hit = type("Hit", (), {"build_id": "b", "chunk_id": "c0"})()
    monkeypatch.setattr(
        "plugins.corpus.preparation.search_pg.search_chunks", lambda *a, **k: (hit,)
    )
    ev = type("Ev", (), {"units": (type("U", (), {"raw_text": "会议纪要强调利率路径"})(),)})()
    monkeypatch.setattr("plugins.corpus.preparation.read_pg.fetch_verbatim", lambda *a, **k: ev)
    assert svc._abstain_decision("这些报告是否披露美联储9月会议利率决定？") is True


def test_abstain_on_releases_when_a_unit_carries_full_content(
    svc: CorpusService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """on + 某单元同时满足全部内容词元（有实质答案）→ 放行，产品查询路径原样返回。"""
    _monkey_setenv(monkeypatch, "on")
    monkeypatch.setattr(
        "plugins.corpus.preparation.search_pg.query_lexemes",
        lambda *a, **k: ("美联储", "会议", "利率", "决定"),
    )
    hit = type("Hit", (), {"build_id": "b", "chunk_id": "c0"})()
    monkeypatch.setattr(
        "plugins.corpus.preparation.search_pg.search_chunks", lambda *a, **k: (hit,)
    )
    ev = type(
        "Ev", (), {"units": (type("U", (), {"raw_text": "美联储9月议息会议决定维持利率不变"})(),)}
    )()
    monkeypatch.setattr("plugins.corpus.preparation.read_pg.fetch_verbatim", lambda *a, **k: ev)
    assert svc._abstain_decision("这些报告是否披露美联储9月会议利率决定？") is False


def test_abstain_on_ignores_question_words_for_answerable(
    svc: CorpusService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """on + 题面含疑问词（什么/多少…）但单元含全部实质词元 → 放行（不误杀有答案题）。

    实证：24 条有答案题中 23 条含疑问词，而答案单元几乎不引述疑问词——若保留疑问词
    full-AND 必然归零误杀。abstain 门剔除疑问词后，实质词元共现即放行（S1 保护）。
    """
    _monkey_setenv(monkeypatch, "on")
    monkeypatch.setattr(
        "plugins.corpus.preparation.search_pg.query_lexemes",
        lambda *a, **k: ("光力", "科技", "净利润", "什么"),
    )
    hit = type("Hit", (), {"build_id": "b", "chunk_id": "c0"})()
    monkeypatch.setattr(
        "plugins.corpus.preparation.search_pg.search_chunks", lambda *a, **k: (hit,)
    )
    ev = type(
        "Ev", (), {"units": (type("U", (), {"raw_text": "光力科技全年归母净利润同比增长23.5%"})(),)}
    )()
    monkeypatch.setattr("plugins.corpus.preparation.read_pg.fetch_verbatim", lambda *a, **k: ev)
    assert svc._abstain_decision("光力科技2027年经审计的归母净利润是多少？") is False


def test_abstain_does_not_probe_ordinary_research_question(
    svc: CorpusService, monkeypatch: pytest.MonkeyPatch
) -> None:
    _monkey_setenv(monkeypatch, "on")
    monkeypatch.setattr(
        "plugins.corpus.preparation.search_pg.query_lexemes",
        lambda *a, **k: pytest.fail("ordinary research question must not enter strict gate"),
    )
    assert svc._abstain_decision("能否把价格分位和涨幅当成同一指标？") is False


def test_corpus_search_abstain_signal_splits_from_no_match(monkeypatch: pytest.MonkeyPatch) -> None:
    """corpus_search：coverage["abstain"] 为真 → 顶层 abstain + ABSTAIN_HINT（可机器区分）。"""
    import importlib

    mod = importlib.import_module("plugins.tools.corpus_search")
    from plugins.tools.corpus_search import ABSTAIN_HINT, NO_COVERAGE_HINT

    class _FakeSvc:
        def search_with_coverage(self, query: str, *, limit: int = 10):
            return [], {
                "query_status": "abstain",
                "abstain": True,
                "abstain_reason": "no_answer_rejected",
            }

    monkeypatch.setattr(mod, "get_service", lambda: _FakeSvc())
    out = asyncio.run(mod.corpus_search.func("某负例题干"))
    assert '"abstain": true' in out
    assert ABSTAIN_HINT in out
    assert NO_COVERAGE_HINT not in out
    assert '"count": 0' in out
