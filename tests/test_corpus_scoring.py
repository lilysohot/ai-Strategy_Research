"""I3-0 合成测试：评分器（DocRecall@k / QuestionPass@k / EvidencePass@k）的边界与分母。

**全部用例都是合成输入**：不读真实金标、不跑检索、不触 PG/模型/网络，也不看任何候选业务结果。
被锁定的边界（tasks.md §3.6 I3-0 验收门）：多文档、零分母、缺资产、10 题 95%、any/all、
负例误报与伪造引用、关键题否决、缺必需输入不得算通过；并且评分器**不是 LLM judge**。
"""

from __future__ import annotations

from fractions import Fraction

import pytest

from plugins.corpus.scoring import (
    DEFAULT_POLICY,
    AnswerExistence,
    EvidenceTarget,
    FailureCode,
    FetchedEvidence,
    GoldQuestion,
    ObservationOutcome,
    QueryObservation,
    RetrievedDocument,
    SatisfyRule,
    ScoreReport,
    ScoringInputError,
    ScoringPolicy,
    format_report,
    gold_from_records,
    score,
)


def _evidence(
    text: str, *, locator: tuple[str, ...] = (), verified: bool = True
) -> FetchedEvidence:
    return FetchedEvidence(text=text, locator=locator, verified=verified)


def _doc(source_id: str, *attached: FetchedEvidence) -> RetrievedDocument:
    return RetrievedDocument(source_id=source_id, evidence=tuple(attached))


def _perfect_class(
    domain: str, count: int = 8
) -> tuple[list[GoldQuestion], list[QueryObservation]]:
    """造一类全通过的题：每题 1 个相关文档、1 条证据，首题标关键题。"""

    questions: list[GoldQuestion] = []
    observations: list[QueryObservation] = []
    for index in range(count):
        qid = f"{domain}-{index:03d}"
        source = f"src-{qid}"
        quote = f"{qid} 的权威原值 1,234.5"
        questions.append(
            GoldQuestion(
                query_id=qid,
                domain=domain,
                question=f"{qid}?",
                critical=index == 0,
                relevant_sources=(source,),
                evidence_targets=(
                    EvidenceTarget(target_id=f"{qid}-e1", quote=quote, locator=("page:1",)),
                ),
            )
        )
        observations.append(
            QueryObservation(
                query_id=qid,
                documents=(
                    _doc(
                        source,
                        _evidence(f"……{quote}……", locator=("page:1", "cell:A1")),
                    ),
                ),
            )
        )
    return questions, observations


def _negative(domain: str, index: int) -> GoldQuestion:
    return GoldQuestion(
        query_id=f"{domain}-neg-{index}",
        domain=domain,
        question="该库中并不存在答案的问题",
        answer_existence=AnswerExistence.NO_ANSWER,
        critical=False,
    )


def _clean_negative_observation(query_id: str) -> QueryObservation:
    return QueryObservation(query_id=query_id, outcome=ObservationOutcome.NO_MATCH)


def _one(
    qid: str = "company-001",
    *,
    domain: str = "company",
    sources: tuple[str, ...] = ("src-1",),
    rule: SatisfyRule = SatisfyRule.ANY,
    critical: bool = False,
    targets: tuple[EvidenceTarget, ...] = (),
) -> GoldQuestion:
    return GoldQuestion(
        query_id=qid,
        domain=domain,
        question="合成题",
        satisfy_rule=rule,
        critical=critical,
        relevant_sources=sources,
        evidence_targets=targets,
    )


def _report(question: GoldQuestion, observation: QueryObservation | None = None) -> ScoreReport:
    observations = () if observation is None else (observation,)
    return score((question,), observations)


# ── 全通过基线 ───────────────────────────────────────────────────────────────


def test_perfect_run_passes_and_keeps_denominators() -> None:
    questions: list[GoldQuestion] = []
    observations: list[QueryObservation] = []
    for domain in ("company", "industry", "macro"):
        cls_questions, cls_observations = _perfect_class(domain)
        questions.extend(cls_questions)
        observations.extend(cls_observations)
        negatives = [_negative(domain, index) for index in (1, 2)]
        questions.extend(negatives)
        observations.extend(_clean_negative_observation(item.query_id) for item in negatives)

    report = score(questions, observations)

    assert report.blockers == ()
    assert report.passed is True
    assert report.false_positives == ()
    assert report.fabricated_citations == ()
    for metrics in report.classes:
        assert metrics.answerable_total == 8
        assert metrics.doc_recall.rate == 1
        assert metrics.question_pass.rate == 1
        assert metrics.evidence_pass.rate == 1
    # 负例不进三指标分母（每类 8 有答案题 / 6 负例）。
    assert report.overall.answerable_total == 24
    assert report.overall.question_pass_counts == (24, 24)
    assert report.overall.evidence_pass_counts == (24, 24)
    # 类间宏平均与题数汇总两个口径都给，且此时一致。
    assert report.overall.question_pass == 1
    assert report.overall.doc_recall == 1


def test_negative_questions_are_not_in_recall_denominator() -> None:
    question = _one(sources=("src-1",))
    negative = _negative("company", 1)
    report = score(
        (question, negative),
        (
            QueryObservation(query_id="company-001", documents=(_doc("src-1"),)),
            _clean_negative_observation(negative.query_id),
        ),
    )
    assert report.questions[0].doc_recall == 1
    assert report.questions[1].doc_recall is None
    assert report.classes[0].answerable_total == 1


# ── 门槛：10 题 95% 即 10/10 ─────────────────────────────────────────────────


def test_ten_questions_95_percent_requires_ten_of_ten() -> None:
    questions, observations = _perfect_class("company", count=10)
    all_pass = score(questions, observations)
    assert all_pass.passed is True

    nine_of_ten = score(questions, observations[:-1])
    assert nine_of_ten.passed is False
    assert any(
        blocker.startswith("below_threshold:company:question_pass=")
        for blocker in nine_of_ten.blockers
    )
    assert any(
        blocker.startswith("missing_required_input:company-009:missing_observation")
        for blocker in nine_of_ten.blockers
    )


def test_threshold_comparison_is_exact() -> None:
    questions, observations = _perfect_class("company", count=20)
    # 19/20 恰好等于门槛 → 不判"低于门槛"（用 float 近似会在这里误判/漏判）。
    boundary = score(questions, observations[:19])
    assert boundary.classes[0].doc_recall.rate == Fraction(19, 20)
    assert boundary.classes[0].question_pass.rate == Fraction(19, 20)
    assert not any(blocker.startswith("below_threshold:company:") for blocker in boundary.blockers)
    assert any(
        blocker.startswith("missing_required_input:company-019") for blocker in boundary.blockers
    )

    # 18/20 = 90% < 95% → 明确低于门槛。
    short = score(questions, observations[:18])
    assert short.classes[0].doc_recall.rate == Fraction(18, 20)
    assert any(
        blocker.startswith("below_threshold:company:doc_recall") for blocker in short.blockers
    )


# ── any / all 与多文档 ──────────────────────────────────────────────────────


def test_any_rule_passes_while_recall_still_penalises_missing_document() -> None:
    question = _one(sources=("src-1", "src-2", "src-3"), rule=SatisfyRule.ANY)
    observation = QueryObservation(
        query_id="company-001", documents=(_doc("src-1"), _doc("src-2"), _doc("other"))
    )
    item = _report(question, observation).questions[0]
    assert item.doc_recall == Fraction(2, 3)
    assert item.question_pass is True
    assert f"{FailureCode.DOC_RECALL_INCOMPLETE}:2/3" in item.failures
    assert str(FailureCode.QUESTION_RULE_UNSATISFIED) not in item.failures


def test_all_rule_fails_when_one_required_document_misses_top_k() -> None:
    question = _one(sources=("src-1", "src-2", "src-3"), rule=SatisfyRule.ALL)
    observation = QueryObservation(query_id="company-001", documents=(_doc("src-1"), _doc("src-2")))
    item = _report(question, observation).questions[0]
    assert item.question_pass is False
    assert str(FailureCode.QUESTION_RULE_UNSATISFIED) in item.failures
    assert item.doc_recall == Fraction(2, 3)


def test_all_rule_unsatisfiable_beyond_top_k_is_a_blocker() -> None:
    question = _one(sources=tuple(f"src-{i}" for i in range(6)), rule=SatisfyRule.ALL)
    observation = QueryObservation(
        query_id="company-001", documents=tuple(_doc(f"src-{i}") for i in range(6))
    )
    report = _report(question, observation)
    item = report.questions[0]
    assert item.question_pass is False
    assert f"{FailureCode.RELEVANT_SET_EXCEEDS_TOP_K}:6>5" in item.failures
    assert any(
        blocker.startswith("missing_required_input:company-001:relevant_set_exceeds_top_k")
        for blocker in report.blockers
    )
    # 多传的文档按 @k 截断：DocRecall 分母是 6，命中 5。
    assert item.doc_recall == Fraction(5, 6)


# ── 缺资产 / 零分母 / 缺必需输入 ─────────────────────────────────────────────


def test_answerable_without_relevant_set_is_blocked_not_silently_dropped() -> None:
    question = _one(sources=())
    report = _report(question, QueryObservation(query_id="company-001"))
    assert report.passed is False
    assert str(FailureCode.RELEVANT_SET_EMPTY) in report.questions[0].failures
    assert any("relevant_set_empty" in blocker for blocker in report.blockers)
    assert report.questions[0].doc_recall == 0


def test_zero_denominator_class_is_undefined_and_blocks() -> None:
    negative = _negative("macro", 1)
    report = score((negative,), (_clean_negative_observation(negative.query_id),))
    assert report.passed is False
    assert any(blocker == "undefined_metric:macro:doc_recall" for blocker in report.blockers)
    assert any(blocker == "undefined_metric:macro:question_pass" for blocker in report.blockers)
    assert any(blocker == "no_answerable_questions:macro" for blocker in report.blockers)
    assert report.classes[0].doc_recall.rate is None
    assert "未定义（零分母）" in format_report(report)


def test_answerable_without_evidence_targets_is_blocked_as_missing_asset() -> None:
    """声明需要证据却没给机器可读目标：计入分母 + 阻断，不得静默退出分母。"""

    question = _one()
    report = _report(question, QueryObservation(query_id="company-001", documents=(_doc("src-1"),)))
    item = report.questions[0]
    assert item.evidence_pass is False
    assert str(FailureCode.EVIDENCE_TARGETS_ABSENT) in item.failures
    assert report.classes[0].evidence_pass.total == 1
    assert report.classes[0].evidence_pass.passed == 0
    assert any(blocker.endswith("evidence_targets_absent") for blocker in report.blockers)
    assert report.passed is False


def test_explicit_evidence_opt_out_is_not_silent() -> None:
    """显式 ``evidence_required=False`` 才可退出 EvidencePass 分母；此时指标未定义并阻断。"""

    opted_out = GoldQuestion(
        query_id="company-001",
        domain="company",
        question="按金标决议不做证据评分",
        relevant_sources=("src-1",),
        evidence_required=False,
    )
    report = _report(
        opted_out, QueryObservation(query_id="company-001", documents=(_doc("src-1"),))
    )
    assert report.questions[0].evidence_pass is None
    assert not any("evidence_targets_absent" in blocker for blocker in report.blockers)
    assert any(blocker == "undefined_metric:company:evidence_pass" for blocker in report.blockers)


def test_opted_out_questions_do_not_hide_the_rest_of_the_denominator() -> None:
    questions, observations = _perfect_class("company", count=3)
    questions.append(
        GoldQuestion(
            query_id="company-opt-out",
            domain="company",
            question="显式不做证据评分",
            relevant_sources=("src-opt",),
            evidence_required=False,
        )
    )
    observations.append(QueryObservation(query_id="company-opt-out", documents=(_doc("src-opt"),)))
    report = score(questions, observations)
    assert report.classes[0].answerable_total == 4
    assert report.classes[0].evidence_pass.total == 3  # 只有 3 题是证据题
    assert report.classes[0].evidence_pass.rate == 1
    assert report.passed is True


def test_missing_observation_is_counted_as_failure_and_blocks() -> None:
    questions, observations = _perfect_class("company", count=4)
    report = score(questions, observations[:3])
    assert report.passed is False
    assert report.classes[0].question_pass.total == 4
    assert report.classes[0].question_pass.passed == 3
    assert any(
        blocker.startswith("missing_required_input:company-003:missing_observation")
        for blocker in report.blockers
    )


def test_failed_outcome_is_distinct_from_no_match() -> None:
    question = _one()
    failed = _report(
        question, QueryObservation(query_id="company-001", outcome=ObservationOutcome.FAILED)
    )
    assert str(FailureCode.OBSERVATION_FAILED) in failed.questions[0].failures
    assert any("observation_failed" in blocker for blocker in failed.blockers)

    no_match = _report(
        question, QueryObservation(query_id="company-001", outcome=ObservationOutcome.NO_MATCH)
    )
    assert str(FailureCode.ANSWER_EXPECTED_BUT_NO_MATCH) in no_match.questions[0].failures
    # "无匹配"是真实的检索落空，按指标扣分，但不冒充"故障/缺必需输入"。
    assert not any(
        "observation_failed" in blocker or "answer_expected_but_no_match" in blocker
        for blocker in no_match.blockers
    )


# ── 证据：范围、核验、定位 ──────────────────────────────────────────────────


def _target(target_id: str = "e1", quote: str = "权威原值 42") -> EvidenceTarget:
    return EvidenceTarget(target_id=target_id, quote=quote, locator=("page:3",))


def test_evidence_pass_requires_every_target_from_top_k_documents() -> None:
    question = _one(targets=(_target("e1"), _target("e2", quote="第二处原值 7")))
    partial = _report(
        question,
        QueryObservation(
            query_id="company-001",
            documents=(_doc("src-1", _evidence("……权威原值 42……", locator=("page:3",))),),
        ),
    )
    item = partial.questions[0]
    assert item.evidence_pass is False
    assert f"{FailureCode.EVIDENCE_TARGET_MISSING}:e2" in item.failures

    complete = _report(
        question,
        QueryObservation(
            query_id="company-001",
            documents=(
                _doc(
                    "src-1",
                    _evidence("……权威原值 42……", locator=("page:3",)),
                    _evidence("……第二处原值 7……", locator=("page:3",)),
                ),
            ),
        ),
    )
    assert complete.questions[0].evidence_pass is True


def test_evidence_beyond_top_k_is_recorded_not_counted() -> None:
    """证据所在的文档是**相关来源**，但排在第 k 名之外 → 记账不计分。"""

    question = _one(sources=("src-1", "src-late"), rule=SatisfyRule.ANY, targets=(_target(),))
    documents = (
        *(_doc(f"src-{i}") for i in range(5)),
        _doc("src-late", _evidence("……权威原值 42……", locator=("page:3",))),
    )
    report = _report(question, QueryObservation(query_id="company-001", documents=documents))
    assert report.questions[0].evidence_pass is False
    assert f"{FailureCode.EVIDENCE_OUTSIDE_TOP_K}:e1" in report.questions[0].failures


def test_unverified_evidence_never_counts() -> None:
    question = _one(targets=(_target(),))
    report = _report(
        question,
        QueryObservation(
            query_id="company-001",
            documents=(
                _doc(
                    "src-1",
                    _evidence("……权威原值 42……", locator=("page:3",), verified=False),
                ),
            ),
        ),
    )
    assert report.questions[0].evidence_pass is False
    assert f"{FailureCode.EVIDENCE_UNVERIFIED}:e1" in report.questions[0].failures


def test_evidence_locator_tokens_must_match() -> None:
    question = _one(targets=(_target(),))
    wrong_page = _report(
        question,
        QueryObservation(
            query_id="company-001",
            documents=(_doc("src-1", _evidence("……权威原值 42……", locator=("page:9",))),),
        ),
    )
    assert wrong_page.questions[0].evidence_pass is False
    assert f"{FailureCode.EVIDENCE_TARGET_MISSING}:e1" in wrong_page.questions[0].failures

    right_page = _report(
        question,
        QueryObservation(
            query_id="company-001",
            documents=(_doc("src-1", _evidence("……权威原值 42……", locator=("page:3", "cell:B2"))),),
        ),
    )
    assert right_page.questions[0].evidence_pass is True


def test_evidence_quote_must_be_verbatim() -> None:
    """证据必须逐字包含：数字格式差异（千分位/小数）不算命中。"""

    question = _one(targets=(_target(quote="净利润 84,679 百万元"),))
    report = _report(
        question,
        QueryObservation(
            query_id="company-001",
            documents=(_doc("src-1", _evidence("净利润 84679 百万元", locator=("page:3",))),),
        ),
    )
    assert report.questions[0].evidence_pass is False
    assert f"{FailureCode.EVIDENCE_TARGET_MISSING}:e1" in report.questions[0].failures


# ── 负例：误报与伪造引用 ────────────────────────────────────────────────────


def test_negative_false_positive_and_fabricated_citation_block() -> None:
    negative = _negative("company", 1)
    asserted = _report(
        negative,
        QueryObservation(
            query_id=negative.query_id,
            documents=(
                _doc("src-x"),
                _doc("src-y", _evidence("伪造的引用")),
            ),
        ),
    )
    item = asserted.questions[0]
    assert item.false_positive is True
    assert item.fabricated_citations == 1
    assert asserted.false_positives == (negative.query_id,)
    assert asserted.fabricated_citations == (negative.query_id,)
    assert any(blocker.startswith("false_positives:") for blocker in asserted.blockers)
    assert any(blocker.startswith("fabricated_citations:") for blocker in asserted.blockers)


def test_fabricated_citation_tolerance_is_policy_controlled() -> None:
    negative = _negative("company", 1)
    observation = QueryObservation(query_id=negative.query_id, documents=(_doc("src-x"),))
    report = score((negative,), (observation,), ScoringPolicy(max_false_positives=1))
    assert report.false_positives == (negative.query_id,)
    assert not any(blocker.startswith("false_positives:") for blocker in report.blockers)


# ── 关键题否决 ──────────────────────────────────────────────────────────────


def test_critical_question_veto_even_when_class_rates_are_high() -> None:
    questions, observations = _perfect_class("company", count=8)
    questions[0] = GoldQuestion(
        query_id="company-000",
        domain="company",
        question="关键题",
        critical=True,
        relevant_sources=("src-company-000", "src-extra"),
        satisfy_rule=SatisfyRule.ANY,
    )
    report = score(questions, observations)
    assert report.classes[0].question_pass.rate == 1  # any 规则：命中 1 份即算题通过
    assert report.passed is False
    assert report.critical_failures == ("company-000",)
    assert any(blocker.startswith("critical_failed:company-000") for blocker in report.blockers)


def test_critical_negative_question_veto() -> None:
    negative = GoldQuestion(
        query_id="company-neg-1",
        domain="company",
        question="关键负例",
        answer_existence=AnswerExistence.NO_ANSWER,
        critical=True,
    )
    report = score(
        (negative,),
        (QueryObservation(query_id="company-neg-1", documents=(_doc("src-x"),)),),
    )
    assert report.passed is False
    assert report.critical_failures == ("company-neg-1",)


def test_critical_rule_is_policy_controlled() -> None:
    question = _one(sources=("src-1", "src-2"), critical=True)
    observation = QueryObservation(query_id="company-001", documents=(_doc("src-1"),))
    strict = _report(question, observation)
    assert strict.passed is False
    relaxed = score((question,), (observation,), ScoringPolicy(require_critical_all_pass=False))
    assert relaxed.critical_failures == ()
    assert not any(blocker.startswith("critical_failed") for blocker in relaxed.blockers)


# ── 输入合法性与确定性 ──────────────────────────────────────────────────────


def test_invalid_inputs_fail_closed() -> None:
    question = _one()
    with pytest.raises(ScoringInputError):
        score((), ())
    with pytest.raises(ScoringInputError):
        score((question, question), ())
    with pytest.raises(ScoringInputError):
        score((question,), (QueryObservation(query_id="company-001"),) * 2)
    with pytest.raises(ScoringInputError):
        score((question,), (QueryObservation(query_id="ghost"),))
    with pytest.raises(ScoringInputError):
        ScoringPolicy(top_k=0)
    with pytest.raises(ScoringInputError):
        ScoringPolicy(min_rate=0.95)  # type: ignore[arg-type]
    with pytest.raises(ScoringInputError):
        ScoringPolicy(min_rate=Fraction(3, 2))
    with pytest.raises(ScoringInputError):
        ScoringPolicy(max_false_positives=-1)


def test_scoring_is_deterministic_and_accepts_mapping_observations() -> None:
    questions, observations = _perfect_class("company", count=3)
    first = score(questions, observations)
    second = score(tuple(reversed(questions)), {item.query_id: item for item in observations})
    assert first == second
    assert [item.query_id for item in first.questions] == sorted(
        item.query_id for item in first.questions
    )


def test_report_text_carries_denominators_and_blockers() -> None:
    questions, observations = _perfect_class("company", count=2)
    report = score(questions, observations[:1])
    text = format_report(report)
    assert "未通过" in text
    assert "DocRecall@5" in text
    assert "1/2" in text
    assert "阻断项" in text


def _frozen_style_rows(*, second_evidence_required: bool | None = None) -> list[dict[str, object]]:
    """模拟冻结 query-gold 的记录形状（含负例；可切换第二题的证据决议）。"""

    second: dict[str, object] = {
        "query_id": "company-002",
        "domain": "company",
        "question": "Q2",
        "answer_existence": "answerable",
        "satisfy_rule": "any",
        "critical": False,
        "relevant_sources": ["src-3"],
    }
    if second_evidence_required is not None:
        second["evidence_required"] = second_evidence_required
    return [
        {
            "query_id": "company-001",
            "domain": "company",
            "question": "Q1",
            "answer_existence": "answerable",
            "satisfy_rule": "all",
            "critical": True,
            "relevant_sources": ["src-1", "src-2"],
            "evidence_targets": [
                {"target_id": "e1", "quote": "原值 42", "locator": ["page:3"]},
            ],
        },
        second,
        {
            "query_id": "company-003",
            "domain": "company",
            "question": "负例",
            "answer_existence": "no_answer",
            "query_kind": "negative",
            "relevant_sources": [],
        },
    ]


def _frozen_style_observations() -> tuple[QueryObservation, ...]:
    return (
        QueryObservation(
            query_id="company-001",
            documents=(
                _doc("src-1", _evidence("……原值 42……", locator=("page:3",))),
                _doc("src-2"),
            ),
        ),
        QueryObservation(query_id="company-002", documents=(_doc("src-3", _evidence("……")),)),
        _clean_negative_observation("company-003"),
    )


def test_gold_from_records_maps_frozen_schema() -> None:
    questions = gold_from_records(_frozen_style_rows())
    assert [item.query_id for item in questions] == ["company-001", "company-002", "company-003"]
    assert questions[0].satisfy_rule is SatisfyRule.ALL
    assert questions[0].critical is True
    assert questions[0].evidence_targets[0].locator == ("page:3",)
    assert questions[1].answer_existence is AnswerExistence.ANSWERABLE
    assert questions[2].answer_existence is AnswerExistence.NO_ANSWER
    # 负例题不适用 any/all：规则必须保持"未声明"，不得被导入器补成 any。
    assert questions[2].satisfy_rule is None
    assert questions[2].evidence_required is False


def test_frozen_gold_without_evidence_targets_is_visibly_blocked() -> None:
    """冻结金标当前只有散文 ``evidence_requirement``：缺机器可读目标必须显式阻断。"""

    questions = gold_from_records(_frozen_style_rows())
    assert questions[1].evidence_required is True
    report = score(questions, _frozen_style_observations())
    assert report.passed is False
    assert report.classes[0].evidence_pass.total == 2
    assert report.classes[0].evidence_pass.passed == 1
    assert any(
        blocker.startswith("missing_required_input:company-002:evidence_targets_absent")
        for blocker in report.blockers
    )

    # 显式决议（不做证据评分）后，同一轮观测即可通过：缺资产被如实登记，而不是被猜掉。
    declared = gold_from_records(_frozen_style_rows(second_evidence_required=False))
    declared_report = score(declared, _frozen_style_observations())
    assert declared_report.classes[0].evidence_pass.total == 1
    assert declared_report.classes[0].evidence_pass.rate == 1
    assert declared_report.passed is True


def test_gold_from_records_rejects_malformed_rows() -> None:
    with pytest.raises(ScoringInputError):
        gold_from_records([{"query_id": "x"}])  # 缺 domain
    with pytest.raises(ScoringInputError):
        gold_from_records(
            [{"query_id": "x", "domain": "company", "evidence_targets": [{"target_id": "e1"}]}]
        )
    with pytest.raises(ScoringInputError):
        # 缺 answer_existence 不得默认成负例（那是静默退出分母的捷径）。
        gold_from_records([{"query_id": "x", "domain": "company"}])
    with pytest.raises(ScoringInputError):
        gold_from_records([{"query_id": "x", "domain": "company", "answer_existence": "maybe"}])
    with pytest.raises(ScoringInputError):
        gold_from_records(
            [
                {
                    "query_id": "x",
                    "domain": "company",
                    "answer_existence": "answerable",
                    "evidence_required": "yes",
                }
            ]
        )


def test_scorer_is_not_an_llm_judge_and_touches_nothing() -> None:
    """评分器只做集合与算术：import 面锁死为纯标准库，源码不得引用模型/PG/网络/时钟。"""

    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    path = root / "plugins" / "corpus" / "scoring.py"
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)

    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported <= {"__future__", "collections", "dataclasses", "enum", "fractions"}, imported

    for forbidden in ("openai", "anthropic", "psycopg", "sqlalchemy", "requests", "urllib"):
        assert forbidden not in text, f"评分器不得引用 {forbidden}"
    for forbidden_call in ("open(", "datetime.now(", "random."):
        assert forbidden_call not in text, f"评分器不得做 I/O 或引入非确定性：{forbidden_call}"

    assert DEFAULT_POLICY.top_k == 5
    assert DEFAULT_POLICY.min_rate == Fraction(19, 20)


# ── 2026-09-18 独立复核反例的常驻回归（F1—F5）────────────────────────────────
#
# 来源：audits/20260918-i30-review/test_review_probes.py（write-once，不修改）。
# 这些输入在修复前会让"本应失败"的关键题整轮通过；此处一律以**修复不变量**关闭，
# 不放松任何断言。


def _review_fixture() -> tuple[GoldQuestion, QueryObservation]:
    question = GoldQuestion(
        query_id="q",
        domain="company",
        critical=True,
        relevant_sources=("A",),
        evidence_targets=(EvidenceTarget("e", "营收 42", ("page:3",)),),
    )
    evidence = FetchedEvidence("营收 42", ("page:3",), verified=True)
    return question, QueryObservation("q", documents=(RetrievedDocument("A", (evidence,)),))


def test_review_positive_control_still_passes() -> None:
    question, observation = _review_fixture()
    assert score((question,), (observation,)).passed


def test_review_f1_duplicate_source_cannot_replace_missing_document() -> None:
    """``[A, A]`` 不能顶替漏召回的 B；重复来源直接拒绝，或集合交集只算 1/2。"""

    question = GoldQuestion(
        query_id="q",
        domain="company",
        critical=True,
        relevant_sources=("A", "B"),
        satisfy_rule=SatisfyRule.ALL,
        evidence_targets=(EvidenceTarget("e", "营收 42", ("page:3",)),),
    )
    document = RetrievedDocument("A", (FetchedEvidence("营收 42", ("page:3",), verified=True),))
    with pytest.raises(ScoringInputError):
        score((question,), (QueryObservation("q", documents=(document, document)),))


def test_review_f1_recall_never_exceeds_one_with_repeated_entries() -> None:
    """即便调用方自行去重后送入，召回也不得超过 1（分子是集合交集）。"""

    question, observation = _review_fixture()
    report = _report(question, observation)
    assert report.questions[0].doc_recall == 1
    # 同一文档的多份证据仍归属同一来源，不放大召回。
    duplicated_evidence = QueryObservation(
        "q",
        documents=(
            RetrievedDocument(
                "A",
                (
                    FetchedEvidence("营收 42", ("page:3",), verified=True),
                    FetchedEvidence("营收 42", ("page:3",), verified=True),
                ),
            ),
        ),
    )
    assert _report(question, duplicated_evidence).questions[0].doc_recall == 1


def test_review_f2_unrelated_source_cannot_supply_required_evidence() -> None:
    question, observation = _review_fixture()
    evidence = observation.documents[0].evidence
    observation = QueryObservation(
        "q", documents=(RetrievedDocument("A"), RetrievedDocument("unrelated", evidence))
    )
    report = score((question,), (observation,))
    assert report.questions[0].evidence_pass is False
    assert f"{FailureCode.EVIDENCE_SOURCE_MISMATCH}:e" in report.questions[0].failures
    assert report.passed is False


def test_review_f2_explicit_source_binding_narrows_the_match() -> None:
    question = GoldQuestion(
        query_id="q",
        domain="company",
        relevant_sources=("A", "B"),
        satisfy_rule=SatisfyRule.ANY,
        evidence_targets=(EvidenceTarget("e", "营收 42", ("page:3",), source_id="B"),),
    )
    observation = QueryObservation(
        "q",
        documents=(
            RetrievedDocument("A", (FetchedEvidence("营收 42", ("page:3",), verified=True),)),
            RetrievedDocument("B"),
        ),
    )
    report = score((question,), (observation,))
    assert report.questions[0].evidence_pass is False


def test_review_f2_unverified_evidence_is_not_success() -> None:
    """``verified`` 未提交（None）不得自动算成功——漏接 verify 不能变成通过。"""

    question, _observation = _review_fixture()
    observation = QueryObservation(
        "q", documents=(RetrievedDocument("A", (FetchedEvidence("营收 42", ("page:3",)),)),)
    )
    report = score((question,), (observation,))
    assert report.questions[0].evidence_pass is False
    assert f"{FailureCode.EVIDENCE_UNVERIFIED}:e" in report.questions[0].failures


def test_review_f3_no_match_with_documents_is_contradictory_input() -> None:
    question, observation = _review_fixture()
    contradictory = QueryObservation(
        "q", outcome=ObservationOutcome.NO_MATCH, documents=observation.documents
    )
    with pytest.raises(ScoringInputError):
        score((question,), (contradictory,))


def test_review_f3_failed_observation_scores_zero_even_with_payload() -> None:
    question, observation = _review_fixture()
    observation = QueryObservation(
        "q", outcome=ObservationOutcome.FAILED, documents=observation.documents
    )
    item = score((question,), (observation,)).questions[0]
    assert (item.doc_recall, item.question_pass, item.evidence_pass) == (0, False, False)
    assert f"{FailureCode.STALE_PAYLOAD_IGNORED}:1" in item.failures


@pytest.mark.parametrize("rule", [None, "ALL"])
def test_review_f4_multidocument_rule_must_be_explicit_and_valid(rule: object) -> None:
    record = {
        "query_id": "q",
        "domain": "company",
        "answer_existence": "answerable",
        "relevant_sources": ["A", "B"],
        "satisfy_rule": rule,
    }
    with pytest.raises(ScoringInputError):
        gold_from_records([record])
    # 直接对象入口在 score() 时同样拒绝未声明的多文档题
    direct = GoldQuestion(query_id="q", domain="company", relevant_sources=("A", "B"))
    with pytest.raises(ScoringInputError):
        score((direct,), ())


def test_review_f4_scalar_relevant_sources_not_split_into_characters() -> None:
    record = {
        "query_id": "q",
        "domain": "company",
        "answer_existence": "answerable",
        "relevant_sources": "AB",
        "satisfy_rule": "all",
    }
    with pytest.raises(ScoringInputError):
        gold_from_records([record])


def test_review_f4_non_string_source_element_rejected() -> None:
    record = {
        "query_id": "q",
        "domain": "company",
        "answer_existence": "answerable",
        "relevant_sources": ["A", 7],
        "satisfy_rule": "all",
    }
    with pytest.raises(ScoringInputError):
        gold_from_records([record])


def test_review_f5_empty_quote_rejected_in_every_entry_point() -> None:
    """空 quote 会匹配一切文本：dataclass 入口与 JSON 入口都必须拒绝。"""

    with pytest.raises(ScoringInputError):
        EvidenceTarget("e", "")
    with pytest.raises(ScoringInputError):
        EvidenceTarget("e", "   ")
    with pytest.raises(ScoringInputError):
        gold_from_records(
            [
                {
                    "query_id": "q",
                    "domain": "company",
                    "answer_existence": "answerable",
                    "relevant_sources": ["A"],
                    "evidence_targets": [{"target_id": "e", "quote": ""}],
                }
            ]
        )


def test_review_duplicate_and_conflicting_identifiers_rejected() -> None:
    duplicated_sources = GoldQuestion(
        query_id="q", domain="company", relevant_sources=("A", "A"), satisfy_rule=SatisfyRule.ANY
    )
    duplicated_targets = GoldQuestion(
        query_id="q",
        domain="company",
        relevant_sources=("A",),
        evidence_targets=(EvidenceTarget("e", "x"), EvidenceTarget("e", "y")),
    )
    negative_with_rule = GoldQuestion(
        query_id="q",
        domain="company",
        answer_existence=AnswerExistence.NO_ANSWER,
        satisfy_rule=SatisfyRule.ANY,
    )
    for question in (duplicated_sources, duplicated_targets, negative_with_rule):
        with pytest.raises(ScoringInputError):
            score((question,), ())
    # 字段级不变量在构造期即拒绝（空来源标识无意义）
    with pytest.raises(ScoringInputError):
        RetrievedDocument("")


def test_review_build_identity_is_preserved_for_i3_1_wiring() -> None:
    """``build_id`` 是身份留痕位（本版不参与计分），必须原样保留。"""

    document = RetrievedDocument("A", (), build_id="cv2:build-7")
    assert document.build_id == "cv2:build-7"
