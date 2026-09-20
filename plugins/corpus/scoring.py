"""I3-0：三类开发指标的确定性评分器（``DocRecall@k`` / ``QuestionPass@k`` / ``EvidencePass@k``）。

**这是评分器，不是 LLM judge。** 它只做集合与算术判定：输入是两份**已经发生的事实**——
冻结的预期（gold，I3-2 冻结）与本轮链路的观测（检索排序结果 + 经 fetch/verify 取回的权威证据），
输出逐题明细、分母账与判定。它不检索、不读库、不解析原文、不调模型、不写文件、不看候选业务结果。

调用方必须知道的全部（接口契约）：

- ``GoldQuestion`` 是一题的冻结预期：``relevant_sources`` 为**非空且无重复**的相关文档集（架构 §12.3），
  ``satisfy_rule`` 决定 QuestionPass 取 any 还是 all——**多文档题必须显式声明**（``None``=未声明，
  多文档时拒绝，不猜成 any），``critical`` 参与关键题否决，``evidence_targets`` 为必须逐字取回的证据
  （机器可读）。有答案题默认需要证据；确实不做证据评分的题必须在金标里显式 ``evidence_required=False``
  ——用"没写目标"退出分母会被当作缺资产阻断。
- ``QueryObservation`` 是一题的观测：``documents`` 必须**按相关性排序**且**同一来源只出现一次**
  （真实检索层是 chunk 检索，I3 接线必须先把 chunk 聚合为**文档** Top-k，不得把多块当成多文档），
  多余条目按 @k 语义截断。``documents`` 表示**运行断言命中的文档**，因此"当前已发布范围无匹配"的正确
  表达是 ``outcome=NO_MATCH`` 且 ``documents=()``（带 payload 的 NO_MATCH 是矛盾输入，入口拒绝）；
  ``outcome=FAILED`` 表示故障/未完成，与"无匹配"严格区分——**故障即使带回部分 payload 也不计成功分**，
  只保留分母、失败原因与诊断。``RetrievedDocument.build_id`` 是身份留痕位：I3-1 接线时必须填真实
  build/handle，并据此扩展跨 build 判定（本版不参与计分，只保证身份不丢）。
- 证据只在**前 k 名文档**内计分，且**带来源归属**：``(source_id, evidence)`` 不被压平成文本池。
  目标的允许来源 = ``EvidenceTarget.source_id``（显式绑定）或有答案题的相关集；页码/数字相同不等于同一
  来源、同一对象的证据，来源不符记 ``evidence_source_mismatch``。挂在第 k 名之后的证据不计入并记
  ``evidence_outside_top_k``（不得靠额外搜索把一次失败补算成功）。``verified`` 必须**显式提交**：
  ``None``=未提交核验结果（按不可用处理，不自动算成功），``False``=核验失败。

缺必需输入（缺观测 / 缺相关集 / 零分母 / 故障 / 缺证据目标）**一律不能算通过**：逐题按未通过
计入分母（不静默剔除以抬高分数），并在 ``ScoreReport.blockers`` 留下机读条目。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from fractions import Fraction


class ScoringInputError(ValueError):
    """结构上非法的输入（重复 ID、未知观测、非法 top_k/门槛）——fail-closed 直接拒绝。"""


class AnswerExistence(StrEnum):
    """该题在冻结金标里的答案存在性（架构 §12.3 的分母依据）。"""

    ANSWERABLE = "answerable"
    NO_ANSWER = "no_answer"


class SatisfyRule(StrEnum):
    """多文档题的冻结要求：任一相关文档命中（any）或全部命中（all）。"""

    ANY = "any"
    ALL = "all"


class ObservationOutcome(StrEnum):
    """本轮观测的结局；故障（failed）不得与"无匹配"混淆。"""

    OK = "ok"
    NO_MATCH = "no_match"
    FAILED = "failed"


class FailureCode(StrEnum):
    """逐题失败原因的机读码（带 ``:<id>`` 后缀的具体条目按前缀匹配）。"""

    MISSING_OBSERVATION = "missing_observation"
    OBSERVATION_FAILED = "observation_failed"
    ANSWER_EXPECTED_BUT_NO_MATCH = "answer_expected_but_no_match"
    RELEVANT_SET_EMPTY = "relevant_set_empty"
    RELEVANT_SET_EXCEEDS_TOP_K = "relevant_set_exceeds_top_k"
    DOC_RECALL_INCOMPLETE = "doc_recall_incomplete"
    QUESTION_RULE_UNSATISFIED = "question_rule_unsatisfied"
    EVIDENCE_TARGET_MISSING = "evidence_target_missing"
    EVIDENCE_TARGETS_ABSENT = "evidence_targets_absent"
    EVIDENCE_SOURCE_MISMATCH = "evidence_source_mismatch"
    EVIDENCE_UNVERIFIED = "evidence_unverified"
    EVIDENCE_OUTSIDE_TOP_K = "evidence_outside_top_k"
    STALE_PAYLOAD_IGNORED = "stale_payload_ignored"
    NO_ANSWER_FALSE_POSITIVE = "no_answer_false_positive"
    FABRICATED_CITATION = "fabricated_citation"


@dataclass(frozen=True)
class FetchedEvidence:
    """经 fetch/verify 取回的一段权威原文。

    ``verified`` **必须显式提交**：``None``（默认）= 未提交核验结果，按**不可用**处理——漏接 verify
    不会自动变成成功；``False`` = 核验失败，同样不可用。
    """

    text: str
    locator: tuple[str, ...] = ()
    verified: bool | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            raise ScoringInputError(f"FetchedEvidence.text 必须是字符串，实际 {self.text!r}")
        if self.verified is not None and not isinstance(self.verified, bool):
            raise ScoringInputError(
                f"FetchedEvidence.verified 必须是布尔值或 None（未核验），实际 {self.verified!r}"
            )
        if any(not isinstance(token, str) or not token for token in self.locator):
            raise ScoringInputError("FetchedEvidence.locator 元素必须是非空字符串")


def _no_whitespace(s: str) -> str:
    """剥离全部空白（空格/tab/换行）用于引文包含判定。

    权威引文的"逐字"按**非空白码位序列**判定，与金标构建时 ``exact()`` 的空白容忍语义一致
    （金标 quote 常自带换行/行内空格的版面残留，而证据文本按单元 ``"\\n"`` 拼接整理过）；
    数字格式（千分位逗号/小数点）、大小写、全半角等**非空白差异仍构成不命中**——见
    ``test_evidence_quote_must_be_verbatim`` 中 ``84,679 ≠ 84679`` 的语义。
    """
    return "".join(ch for ch in s if not ch.isspace())


@dataclass(frozen=True)
class EvidenceTarget:
    """一条必需的原文证据：``quote`` 必须在权威正文里逐字出现（空白规约后的包含）。

    判定口径与金标 ``exact()`` 一致：剥离全部空白后再作 **code point 精确包含**——版面换行/
    行内空格不等效于删除内容；但数字/符号/大小写/全半角的差异照旧不命中。引文权威仍是
    ``unit.raw_text``，此处只影响包含判定，不改任何正文。

    ``locator`` 为可选坐标 token（如 ``page:3``、``cell:营业总收入×2026E``）：非空时要求证据的
    locator **包含全部 token**（证据可携带更细坐标）。

    ``source_id`` 为可选的显式来源绑定：为空时允许来源集取该题的相关文档集——**无关文档提供的
    相同文本不算证据**。
    """

    target_id: str
    quote: str
    locator: tuple[str, ...] = ()
    source_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.target_id, str) or not self.target_id:
            raise ScoringInputError(
                f"EvidenceTarget.target_id 必须是非空字符串：{self.target_id!r}"
            )
        if not isinstance(self.quote, str) or not self.quote.strip():
            raise ScoringInputError(
                f"{self.target_id}: quote 必须是非空字符串（空 quote 会匹配一切文本）"
            )
        if any(not isinstance(token, str) or not token for token in self.locator):
            raise ScoringInputError(f"{self.target_id}: locator 元素必须是非空字符串")
        if self.source_id is not None and (
            not isinstance(self.source_id, str) or not self.source_id
        ):
            raise ScoringInputError(f"{self.target_id}: source_id 必须为空或非空字符串")

    def matches(self, evidence: FetchedEvidence) -> bool:
        if evidence.verified is not True:
            return False
        # 空白规约后的码位包含（与金标 exact() 语义一致）；非空白差异仍不命中。
        if _no_whitespace(self.quote) not in _no_whitespace(evidence.text):
            return False
        return all(token in evidence.locator for token in self.locator)


@dataclass(frozen=True)
class RetrievedDocument:
    """检索结果中的一份候选文档，及其上取回的证据（仅前 k 名参与计分）。

    ``build_id`` 为身份留痕：I3-1 接线时填真实 build/handle，供跨 build 判定扩展使用。
    """

    source_id: str
    evidence: tuple[FetchedEvidence, ...] = ()
    build_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.source_id, str) or not self.source_id:
            raise ScoringInputError(
                f"RetrievedDocument.source_id 必须是非空字符串：{self.source_id!r}"
            )


@dataclass(frozen=True)
class QueryObservation:
    """一个问题的本轮观测。缺观测 = 该题未执行（按缺必需输入处理，不静默剔除）。

    不变量：文档排名中**同一来源只出现一次**（重复即拒绝，避免用重复条目顶替漏召回的文档）；
    ``NO_MATCH`` 必须配空候选集（否则是矛盾输入）。
    """

    query_id: str
    outcome: ObservationOutcome = ObservationOutcome.OK
    documents: tuple[RetrievedDocument, ...] = ()

    def __post_init__(self) -> None:
        # 只做字段级不变量；**输入一致性**（重复来源、NO_MATCH 带 payload）在 ``score()``
        # 入口统一校验——矛盾输入可能由 dataclasses.replace 拼出，拒绝必须发生在评分入口。
        if not isinstance(self.query_id, str) or not self.query_id:
            raise ScoringInputError(
                f"QueryObservation.query_id 必须是非空字符串：{self.query_id!r}"
            )
        if not isinstance(self.outcome, ObservationOutcome):
            raise ScoringInputError(f"{self.query_id}: outcome 必须是 ObservationOutcome")


@dataclass(frozen=True)
class GoldQuestion:
    """一个问题的冻结预期（不含任何候选结果）。

    ``evidence_required`` 是**显式**决议：有答案题默认必须给出机器可读证据目标；若某题确实不做
    证据评分，必须在金标里显式关掉（``evidence_required=False``），不允许用"没写目标"来静默退出
    EvidencePass 分母（那正是缺资产被掩盖的路径）。

    ``satisfy_rule=None`` 表示**未声明**：单文档题（至多一份相关文档）无歧义，按 any 处理；
    多文档题必须显式声明，否则拒绝（架构 §12.3 要求 any/all 预先冻结，导入器不得猜）。
    """

    query_id: str
    domain: str
    question: str = ""
    answer_existence: AnswerExistence = AnswerExistence.ANSWERABLE
    satisfy_rule: SatisfyRule | None = None
    critical: bool = False
    relevant_sources: tuple[str, ...] = ()
    evidence_targets: tuple[EvidenceTarget, ...] = ()
    evidence_required: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.query_id, str) or not self.query_id:
            raise ScoringInputError(f"GoldQuestion.query_id 必须是非空字符串：{self.query_id!r}")
        if not isinstance(self.domain, str) or not self.domain:
            raise ScoringInputError(f"{self.query_id}: domain 必须是非空字符串")
        if not isinstance(self.answer_existence, AnswerExistence):
            raise ScoringInputError(f"{self.query_id}: answer_existence 必须是 AnswerExistence")
        if self.satisfy_rule is not None and not isinstance(self.satisfy_rule, SatisfyRule):
            raise ScoringInputError(
                f"{self.query_id}: satisfy_rule 必须是 'any'/'all' 或 None（未声明），"
                f"实际 {self.satisfy_rule!r}"
            )
        if not isinstance(self.critical, bool) or not isinstance(self.evidence_required, bool):
            raise ScoringInputError(f"{self.query_id}: critical/evidence_required 必须是布尔值")

        sources = self.relevant_sources
        if not isinstance(sources, tuple):
            raise ScoringInputError(f"{self.query_id}: relevant_sources 必须是字符串元组")
        if any(not isinstance(source, str) or not source for source in sources):
            raise ScoringInputError(f"{self.query_id}: relevant_sources 元素必须是非空字符串")
        # 以下"输入一致性"校验在 ``score()`` 入口统一执行（见 ``_validate_gold``）：
        # 相关集重复、target_id 重复、多文档题未声明 any/all、负例题带 satisfy_rule。
        # 有答案题的空相关集同样不在构造期拒绝：它是**分母缺失的缺资产**，需在评分时按
        # 未通过计入分母并落 blocker（与 evidence_targets_absent 同一处理口径）。
        targets = self.evidence_targets
        if not isinstance(targets, tuple):
            raise ScoringInputError(f"{self.query_id}: evidence_targets 必须是元组")
        if any(not isinstance(target, EvidenceTarget) for target in targets):
            raise ScoringInputError(f"{self.query_id}: evidence_targets 元素必须是 EvidenceTarget")

    @property
    def rule(self) -> SatisfyRule:
        """生效的 any/all 规则（未声明按 any；多文档题不允许未声明）。"""

        return self.satisfy_rule if self.satisfy_rule is not None else SatisfyRule.ANY

    @property
    def is_evidence_question(self) -> bool:
        return self.answer_existence is AnswerExistence.ANSWERABLE and self.evidence_required


@dataclass(frozen=True)
class ScoringPolicy:
    """评分门槛与口径。I3-2 冻结其取值；默认值为架构 §12.3 的开发基线。

    ``min_rate`` 只接受 ``Fraction``/``int``：95% 这类门槛必须精确比较，用 float
    的二进制近似会让"10 题里 9 题通过"这类边界漂移（10 题 95% 即要求 10/10）。
    """

    top_k: int = 5
    min_rate: Fraction | int = Fraction(19, 20)
    require_critical_all_pass: bool = True
    max_false_positives: int = 0
    max_fabricated_citations: int = 0

    def __post_init__(self) -> None:
        if isinstance(self.min_rate, float):
            raise ScoringInputError(
                "min_rate 不接受 float（二进制近似会让 95% 边界漂移）；"
                '请用 Fraction(19, 20) 或 Fraction("0.95")'
            )
        if self.top_k < 1:
            raise ScoringInputError(f"top_k 必须 ≥1，实际 {self.top_k!r}")
        rate = Fraction(self.min_rate)
        if not (0 < rate <= 1):
            raise ScoringInputError(f"min_rate 必须落在 (0, 1]，实际 {self.min_rate!r}")
        if self.max_false_positives < 0 or self.max_fabricated_citations < 0:
            raise ScoringInputError("误报/伪引用上限不得为负")


DEFAULT_POLICY = ScoringPolicy()


@dataclass(frozen=True)
class DocRecallBlock:
    """DocRecall@k：逐题召回率的类内**宏平均**（分母 = 该类有答案题数）。"""

    per_question: tuple[Fraction, ...]

    @property
    def total(self) -> int:
        return len(self.per_question)

    @property
    def full(self) -> int:
        return sum(1 for rate in self.per_question if rate == 1)

    @property
    def rate(self) -> Fraction | None:
        """零分母 ⇒ ``None``（未定义，**不得**当作满分）。"""
        if not self.per_question:
            return None
        return sum(self.per_question, start=Fraction(0)) / len(self.per_question)


@dataclass(frozen=True)
class MetricBlock:
    """按题数计数的指标块（QuestionPass@k / EvidencePass@k）。"""

    passed: int = 0
    total: int = 0

    @property
    def rate(self) -> Fraction | None:
        if self.total == 0:
            return None
        return Fraction(self.passed, self.total)


@dataclass(frozen=True)
class ClassMetrics:
    """一类（领域）的指标账；判定按类逐项进行，不取总体平均。"""

    domain: str
    answerable_total: int
    doc_recall: DocRecallBlock
    question_pass: MetricBlock
    evidence_pass: MetricBlock


@dataclass(frozen=True)
class OverallSummary:
    """跨类汇总（**仅展示**，不参与判定）：三类指标均为**类间宏平均**（各类等权，不按题数加权）。

    各类题数不同时"类间平均"与"题数汇总"会给出不同数字，所以两个口径都给：
    ``question_pass_counts`` / ``evidence_pass_counts`` 是题数汇总（passed/total）。
    """

    answerable_total: int
    doc_recall: Fraction | None
    question_pass: Fraction | None
    evidence_pass: Fraction | None
    question_pass_counts: tuple[int, int]
    evidence_pass_counts: tuple[int, int]


@dataclass(frozen=True)
class QuestionScore:
    """单题结果；``None`` 表示该题不适用该指标（负例不进入三指标分母）。"""

    query_id: str
    domain: str
    critical: bool
    answer_existence: AnswerExistence
    outcome: ObservationOutcome | None
    doc_recall: Fraction | None
    question_pass: bool | None
    evidence_pass: bool | None
    failures: tuple[str, ...] = ()
    false_positive: bool = False
    fabricated_citations: int = 0


@dataclass(frozen=True)
class ScoreReport:
    """一轮评分的完整账：逐题明细 + 分类指标 + 机读阻断项 + 判定。"""

    policy: ScoringPolicy
    questions: tuple[QuestionScore, ...]
    classes: tuple[ClassMetrics, ...]
    false_positives: tuple[str, ...]
    fabricated_citations: tuple[str, ...]
    blockers: tuple[str, ...]
    passed: bool

    def question(self, query_id: str) -> QuestionScore:
        for item in self.questions:
            if item.query_id == query_id:
                return item
        raise KeyError(query_id)

    @property
    def critical_failures(self) -> tuple[str, ...]:
        """被关键题否决卡住的问题 ID（去重保序）。"""

        prefix = "critical_failed:"
        seen: list[str] = []
        for blocker in self.blockers:
            if not blocker.startswith(prefix):
                continue
            query_id = blocker.split(":", 2)[1]
            if query_id not in seen:
                seen.append(query_id)
        return tuple(seen)

    @property
    def overall(self) -> OverallSummary:
        """跨类汇总（**仅展示**）：类间宏平均 + 题数汇总；判定仍按类逐项。"""

        def mean(rates: list[Fraction]) -> Fraction | None:
            return sum(rates, start=Fraction(0)) / len(rates) if rates else None

        def counts(blocks: list[MetricBlock]) -> tuple[int, int]:
            return (sum(block.passed for block in blocks), sum(block.total for block in blocks))

        question_blocks = [metrics.question_pass for metrics in self.classes]
        evidence_blocks = [metrics.evidence_pass for metrics in self.classes]
        return OverallSummary(
            answerable_total=sum(metrics.answerable_total for metrics in self.classes),
            doc_recall=mean(
                [
                    metrics.doc_recall.rate
                    for metrics in self.classes
                    if metrics.doc_recall.rate is not None
                ]
            ),
            question_pass=mean([block.rate for block in question_blocks if block.rate is not None]),
            evidence_pass=mean([block.rate for block in evidence_blocks if block.rate is not None]),
            question_pass_counts=counts(question_blocks),
            evidence_pass_counts=counts(evidence_blocks),
        )


def score(
    gold: Sequence[GoldQuestion],
    observations: Iterable[QueryObservation] | Mapping[str, QueryObservation] = (),
    policy: ScoringPolicy = DEFAULT_POLICY,
) -> ScoreReport:
    """对一轮观测出账。纯函数：同输入同输出，无 I/O、无模型、无时钟。"""

    questions = _validate_gold(gold)
    observed = _index_observations(observations)
    unknown = sorted(set(observed) - {q.query_id for q in questions})
    if unknown:
        raise ScoringInputError(f"观测里出现金标中不存在的问题：{unknown}")

    scored = tuple(
        _score_question(question, observed.get(question.query_id), policy) for question in questions
    )
    classes = _aggregate(scored)
    blockers = _collect_blockers(scored, classes, policy)
    return ScoreReport(
        policy=policy,
        questions=scored,
        classes=classes,
        false_positives=tuple(item.query_id for item in scored if item.false_positive),
        fabricated_citations=tuple(item.query_id for item in scored if item.fabricated_citations),
        blockers=blockers,
        passed=not blockers,
    )


def gold_from_records(records: Iterable[Mapping[str, object]]) -> tuple[GoldQuestion, ...]:
    """把冻结的 ``query-gold.jsonl`` 记录转成 ``GoldQuestion``（缺字段不猜、不补）。

    ``evidence_targets`` 是 I3-0 引入的机器可读证据目标（键同 ``EvidenceTarget``）。记录未携带
    ``evidence_targets`` 且未显式声明 ``evidence_required=false`` 时，视为**该题需要证据但目标缺失**：
    按缺资产计入 EvidencePass 分母并阻断整轮——不要把散文 ``evidence_requirement`` 当机器目标用，
    也不要用"没写"让题目静默退出分母。
    """

    def _evidence_required(record: Mapping[str, object], existence: AnswerExistence) -> bool:
        if existence is AnswerExistence.NO_ANSWER:
            return False
        declared = record.get("evidence_required")
        if declared is None:
            return True
        if not isinstance(declared, bool):
            raise ScoringInputError(f"evidence_required 必须是布尔值：{declared!r}")
        return declared

    questions: list[GoldQuestion] = []
    for record in records:
        query_id = _require_str(record, "query_id")
        existence_raw = record.get("answer_existence")
        if existence_raw not in ("answerable", "no_answer"):
            # 缺字段不得默认成负例（负例不进三指标分母 = 静默退出分母的捷径）。
            raise ScoringInputError(
                f"{query_id}: answer_existence 必须是 'answerable' 或 'no_answer'，"
                f"实际 {existence_raw!r}"
            )
        existence = AnswerExistence(str(existence_raw))
        # any/all 只认显式合法的 'any'/'all'：缺字段或非法值（如 "ALL"）一律拒绝，
        # 不降级为 any（那是改变验收条件，不是解析兼容）。
        rule_raw = record.get("satisfy_rule")
        rule: SatisfyRule | None = None
        if rule_raw is not None:
            if not isinstance(rule_raw, str) or rule_raw not in ("any", "all"):
                raise ScoringInputError(
                    f"{query_id}: satisfy_rule 必须是 'any' 或 'all'，实际 {rule_raw!r}"
                )
            rule = SatisfyRule(rule_raw)
        critical_raw = record.get("critical")
        if critical_raw is not None and not isinstance(critical_raw, bool):
            raise ScoringInputError(f"{query_id}: critical 必须是布尔值，实际 {critical_raw!r}")
        targets_raw = record.get("evidence_targets") or ()
        if not isinstance(targets_raw, Sequence):
            raise ScoringInputError(f"{query_id}: evidence_targets 必须是数组")
        targets: list[EvidenceTarget] = []
        for item in targets_raw:
            if not isinstance(item, Mapping):
                raise ScoringInputError(f"{query_id}: evidence_targets 元素必须是对象")
            locator_raw = item.get("locator") or ()
            locator: tuple[str, ...]
            if isinstance(locator_raw, str):
                locator = (locator_raw,)
            elif isinstance(locator_raw, Sequence):
                locator = tuple(str(token) for token in locator_raw)
            else:
                raise ScoringInputError(f"{query_id}: locator 必须是字符串或数组")
            source_id_raw = item.get("source_id")
            if source_id_raw is not None and (
                not isinstance(source_id_raw, str) or not source_id_raw
            ):
                raise ScoringInputError(f"{query_id}: source_id 必须为空或非空字符串")
            targets.append(
                EvidenceTarget(
                    target_id=_require_str(item, "target_id"),
                    quote=_require_str(item, "quote"),
                    locator=locator,
                    source_id=source_id_raw,
                )
            )
        sources = _sources_of(record, query_id)
        questions.append(
            GoldQuestion(
                query_id=query_id,
                domain=_require_str(record, "domain"),
                question=str(record.get("question") or ""),
                answer_existence=existence,
                satisfy_rule=rule,
                critical=bool(critical_raw),
                relevant_sources=sources,
                evidence_targets=tuple(targets),
                evidence_required=_evidence_required(record, existence),
            )
        )
    # 与 score() 入口共用同一套金标校验：缺声明/非法声明在导入期就拒绝，不留到评分期才发现。
    _validate_gold(tuple(questions))
    return tuple(questions)


def format_report(report: ScoreReport) -> str:
    """渲染成可对着逐题核对的文本（含分母账，避免只看百分比）。"""

    lines = [
        f"语料检索评分：{'通过' if report.passed else '未通过'}"
        f"（top_k={report.policy.top_k}，门槛 ≥{_pct(report.policy.min_rate)}）",
        "",
        "逐类指标（判定按类逐项，不用总体平均掩盖弱类）",
    ]
    for metrics in report.classes:
        lines.append(
            f"  [{metrics.domain}] 有答案题 {metrics.answerable_total}"
            f" | DocRecall@{report.policy.top_k} 宏平均 {_pct(metrics.doc_recall.rate)}"
            f"（满分 {metrics.doc_recall.full}/{metrics.doc_recall.total}）"
            f" | QuestionPass {metrics.question_pass.passed}/{metrics.question_pass.total}"
            f"={_pct(metrics.question_pass.rate)}"
            f" | EvidencePass {metrics.evidence_pass.passed}/{metrics.evidence_pass.total}"
            f"={_pct(metrics.evidence_pass.rate)}"
        )
    overall = report.overall
    lines.append(
        f"  [合计] 类间宏平均（各类等权） DocRecall {_pct(overall.doc_recall)}"
        f" | QuestionPass {_pct(overall.question_pass)}"
        f" | EvidencePass {_pct(overall.evidence_pass)}"
    )
    lines.append(
        f"         题数汇总（非类间平均） QuestionPass {overall.question_pass_counts[0]}/"
        f"{overall.question_pass_counts[1]}"
        f"、EvidencePass {overall.evidence_pass_counts[0]}/{overall.evidence_pass_counts[1]}"
    )
    lines.append(
        f"  负例误报 {len(report.false_positives)} 条、伪造引用 {len(report.fabricated_citations)} 条"
        f"（另计，不混入召回分母）"
    )
    if report.blockers:
        lines.append("")
        lines.append("阻断项（存在即不得宣告通过）")
        lines.extend(f"  {blocker}" for blocker in report.blockers)
    failures = [item for item in report.questions if item.failures]
    if failures:
        lines.append("")
        lines.append("未通过逐题")
        for item in failures:
            mark = "关键题 " if item.critical else ""
            lines.append(f"  [{item.query_id}] {mark}{'；'.join(item.failures)}")
    return "\n".join(lines)


def _pct(rate: Fraction | int | None) -> str:
    if rate is None:
        return "未定义（零分母）"
    return f"{float(Fraction(rate)) * 100:.1f}%"


def _require_str(record: Mapping[str, object], key: str) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value:
        raise ScoringInputError(f"记录缺少非空字段 {key!r}：{value!r}")
    return value


def _sources_of(record: Mapping[str, object], query_id: str) -> tuple[str, ...]:
    """解析相关文档集：必须是**字符串数组**，不得把字符串当字符容器、也不强转元素。"""

    raw = record.get("relevant_sources")
    if raw is None:
        return ()
    if isinstance(raw, (str, bytes)) or not isinstance(raw, Sequence):
        raise ScoringInputError(
            f"{query_id}: relevant_sources 必须是字符串数组（不得用字符串/标量当容器），"
            f"实际 {type(raw).__name__}"
        )
    sources: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            raise ScoringInputError(
                f"{query_id}: relevant_sources 元素必须是非空字符串，实际 {item!r}"
            )
        sources.append(item)
    return tuple(sources)


def _validate_gold(gold: Sequence[GoldQuestion]) -> tuple[GoldQuestion, ...]:
    """金标入口校验：所有公开入口（JSON 导入器、直接构造）在此共用同一套规则。"""

    seen: set[str] = set()
    for question in gold:
        if question.query_id in seen:
            raise ScoringInputError(f"金标 query_id 重复：{question.query_id!r}")
        seen.add(question.query_id)
        sources = question.relevant_sources
        if len(set(sources)) != len(sources):
            raise ScoringInputError(
                f"{question.query_id}: relevant_sources 含重复来源 {sorted(set(sources))}"
            )
        ids = [target.target_id for target in question.evidence_targets]
        if len(set(ids)) != len(ids):
            raise ScoringInputError(f"{question.query_id}: evidence_targets 的 target_id 必须唯一")
        if question.answer_existence is AnswerExistence.NO_ANSWER:
            if question.satisfy_rule is not None:
                raise ScoringInputError(f"{question.query_id}: 负例题不得带 satisfy_rule（不适用）")
        elif len(sources) > 1 and question.satisfy_rule is None:
            raise ScoringInputError(
                f"{question.query_id}: 多文档题（{len(sources)} 份相关文档）必须显式声明"
                " satisfy_rule 为 'any' 或 'all'，不得默认"
            )
    if not gold:
        raise ScoringInputError("金标为空；缺预期不能算通过，也不能凭空评分")
    return tuple(sorted(gold, key=lambda item: item.query_id))


def _index_observations(
    observations: Iterable[QueryObservation] | Mapping[str, QueryObservation],
) -> dict[str, QueryObservation]:
    items = observations.values() if isinstance(observations, Mapping) else observations
    indexed: dict[str, QueryObservation] = {}
    for item in items:
        if item.query_id in indexed:
            raise ScoringInputError(f"观测 query_id 重复：{item.query_id!r}")
        # 观测入口校验：矛盾/重复输入在此拒绝（dataclasses.replace 拼出的也要拦住）。
        seen = [document.source_id for document in item.documents]
        if len(set(seen)) != len(seen):
            duplicated = sorted({sid for sid in seen if seen.count(sid) > 1})
            raise ScoringInputError(
                f"{item.query_id}: 文档排名含重复来源 {duplicated}；同一文档在 Top-k 里只能出现"
                "一次（chunk 须先聚合为文档排名，不得把多块当多文档）"
            )
        if item.outcome is ObservationOutcome.NO_MATCH and item.documents:
            raise ScoringInputError(
                f"{item.query_id}: outcome=NO_MATCH 却带 {len(item.documents)} 份文档；"
                "无匹配的正确表达是空候选集"
            )
        indexed[item.query_id] = item
    return indexed


def _score_question(
    question: GoldQuestion, observation: QueryObservation | None, policy: ScoringPolicy
) -> QuestionScore:
    if question.answer_existence is AnswerExistence.NO_ANSWER:
        return _score_negative(question, observation)
    return _score_answerable(question, observation, policy)


def _score_negative(question: GoldQuestion, observation: QueryObservation | None) -> QuestionScore:
    """负例：只计误报与伪造引用，不进入三指标分母（不混入召回分母提高分数）。"""

    outcome = observation.outcome if observation is not None else None
    documents = tuple(observation.documents) if observation is not None else ()
    failures: list[str] = []
    citations = sum(len(document.evidence) for document in documents)
    if observation is None:
        failures.append(str(FailureCode.MISSING_OBSERVATION))
    elif outcome is ObservationOutcome.FAILED:
        failures.append(str(FailureCode.OBSERVATION_FAILED))
    if documents:
        failures.append(str(FailureCode.NO_ANSWER_FALSE_POSITIVE))
    if citations:
        failures.append(f"{FailureCode.FABRICATED_CITATION}:{citations}")
    return QuestionScore(
        query_id=question.query_id,
        domain=question.domain,
        critical=question.critical,
        answer_existence=question.answer_existence,
        outcome=outcome,
        doc_recall=None,
        question_pass=None,
        evidence_pass=None,
        failures=tuple(failures),
        false_positive=bool(documents),
        fabricated_citations=citations,
    )


def _score_answerable(
    question: GoldQuestion, observation: QueryObservation | None, policy: ScoringPolicy
) -> QuestionScore:
    failures: list[str] = []
    relevant = set(question.relevant_sources)
    top_documents = tuple(observation.documents[: policy.top_k]) if observation is not None else ()
    overflow_documents = (
        tuple(observation.documents[policy.top_k :]) if observation is not None else ()
    )
    # 集合交集：重复条目（同一文档的多块）无法顶替漏召回的文档，也不会让召回超过 1。
    top_sources = {document.source_id for document in top_documents}
    hit_sources = relevant & top_sources
    failed = observation is not None and observation.outcome is ObservationOutcome.FAILED

    if observation is None:
        failures.append(str(FailureCode.MISSING_OBSERVATION))
    elif failed:
        failures.append(str(FailureCode.OBSERVATION_FAILED))
        if observation.documents:
            # 故障带回的 payload 一律作废；保留数量作为诊断，但不参与任何分子。
            failures.append(f"{FailureCode.STALE_PAYLOAD_IGNORED}:{len(observation.documents)}")
    elif observation.outcome is ObservationOutcome.NO_MATCH:
        failures.append(str(FailureCode.ANSWER_EXPECTED_BUT_NO_MATCH))

    if failed:
        # 故障不得计任何成功分：分母保留、三项一律未通过，原因与诊断留在 failures。
        return QuestionScore(
            query_id=question.query_id,
            domain=question.domain,
            critical=question.critical,
            answer_existence=question.answer_existence,
            outcome=observation.outcome if observation is not None else None,
            doc_recall=Fraction(0),
            question_pass=False,
            evidence_pass=False if question.is_evidence_question else None,
            failures=tuple(failures),
        )

    # ── DocRecall@k：|Top-k ∩ 相关| / |相关|（集合交集，条目重复不叠加）──────
    if not relevant:
        # 金标缺相关集：分母不存在，按未通过计入并阻断（缺必需输入不静默剔除）。
        failures.append(str(FailureCode.RELEVANT_SET_EMPTY))
        doc_recall = Fraction(0)
    else:
        doc_recall = Fraction(len(hit_sources), len(relevant))
        if doc_recall != 1:
            failures.append(
                f"{FailureCode.DOC_RECALL_INCOMPLETE}:{len(hit_sources)}/{len(relevant)}"
            )

    # ── QuestionPass@k：冻结的 any/all（集合包含，不比计数）──────────────────
    if not relevant:
        question_pass = False
    elif question.rule is SatisfyRule.ALL:
        satisfiable = len(relevant) <= policy.top_k
        if not satisfiable:
            failures.append(
                f"{FailureCode.RELEVANT_SET_EXCEEDS_TOP_K}:{len(relevant)}>{policy.top_k}"
            )
        question_pass = satisfiable and relevant <= top_sources
    else:
        question_pass = bool(hit_sources)
    if relevant and not question_pass:
        failures.append(str(FailureCode.QUESTION_RULE_UNSATISFIED))

    # ── EvidencePass@k：证据保留 (来源, 证据) 归属，只从前 k 名文档取 ────────
    evidence_pass: bool | None = None
    if question.is_evidence_question:
        in_scope = tuple(
            (document.source_id, evidence)
            for document in top_documents
            for evidence in document.evidence
        )
        outside = tuple(
            (document.source_id, evidence)
            for document in overflow_documents
            for evidence in document.evidence
        )
        if not question.evidence_targets:
            # 该题声明需要证据却没给目标：按缺资产计入分母并阻断，不得静默退出分母。
            failures.append(str(FailureCode.EVIDENCE_TARGETS_ABSENT))
            evidence_pass = False
        else:
            evidence_pass = True
            for target in question.evidence_targets:
                allowed = (target.source_id,) if target.source_id else tuple(relevant)
                if any(
                    target.matches(evidence) and source in allowed for source, evidence in in_scope
                ):
                    continue
                evidence_pass = False
                if any(
                    target.matches(evidence) and source in allowed for source, evidence in outside
                ):
                    failures.append(f"{FailureCode.EVIDENCE_OUTSIDE_TOP_K}:{target.target_id}")
                elif any(
                    target.matches(evidence) and source not in allowed
                    for source, evidence in in_scope + outside
                ):
                    failures.append(f"{FailureCode.EVIDENCE_SOURCE_MISMATCH}:{target.target_id}")
                elif any(
                    evidence.verified is not True and target.quote in evidence.text
                    for _source, evidence in in_scope + outside
                ):
                    failures.append(f"{FailureCode.EVIDENCE_UNVERIFIED}:{target.target_id}")
                else:
                    failures.append(f"{FailureCode.EVIDENCE_TARGET_MISSING}:{target.target_id}")

    return QuestionScore(
        query_id=question.query_id,
        domain=question.domain,
        critical=question.critical,
        answer_existence=question.answer_existence,
        outcome=observation.outcome if observation is not None else None,
        doc_recall=doc_recall,
        question_pass=question_pass,
        evidence_pass=evidence_pass,
        failures=tuple(failures),
    )


def _aggregate(scored: tuple[QuestionScore, ...]) -> tuple[ClassMetrics, ...]:
    metrics: list[ClassMetrics] = []
    for domain in sorted({item.domain for item in scored}):
        answerable = [
            item
            for item in scored
            if item.domain == domain and item.answer_existence is AnswerExistence.ANSWERABLE
        ]
        recall_rates = tuple(item.doc_recall for item in answerable if item.doc_recall is not None)
        question_pass = MetricBlock(
            passed=sum(1 for item in answerable if item.question_pass), total=len(answerable)
        )
        evidence_questions = [item for item in answerable if item.evidence_pass is not None]
        evidence_pass = MetricBlock(
            passed=sum(1 for item in evidence_questions if item.evidence_pass),
            total=len(evidence_questions),
        )
        metrics.append(
            ClassMetrics(
                domain=domain,
                answerable_total=len(answerable),
                doc_recall=DocRecallBlock(recall_rates),
                question_pass=question_pass,
                evidence_pass=evidence_pass,
            )
        )
    return tuple(metrics)


def _collect_blockers(
    scored: tuple[QuestionScore, ...], classes: tuple[ClassMetrics, ...], policy: ScoringPolicy
) -> tuple[str, ...]:
    blockers: list[str] = []

    for item in scored:
        for failure in item.failures:
            code = failure.split(":", 1)[0]
            if code in {
                FailureCode.MISSING_OBSERVATION,
                FailureCode.OBSERVATION_FAILED,
                FailureCode.RELEVANT_SET_EMPTY,
                FailureCode.RELEVANT_SET_EXCEEDS_TOP_K,
                FailureCode.EVIDENCE_TARGETS_ABSENT,
            }:
                blockers.append(f"missing_required_input:{item.query_id}:{failure}")

    for metrics in classes:
        for name, rate in (
            ("doc_recall", metrics.doc_recall.rate),
            ("question_pass", metrics.question_pass.rate),
            ("evidence_pass", metrics.evidence_pass.rate),
        ):
            if rate is None:
                blockers.append(f"undefined_metric:{metrics.domain}:{name}")
            elif rate < Fraction(policy.min_rate):
                blockers.append(f"below_threshold:{metrics.domain}:{name}={_pct(rate)}")
        if metrics.answerable_total == 0:
            blockers.append(f"no_answerable_questions:{metrics.domain}")

    if policy.require_critical_all_pass:
        for item in scored:
            if not item.critical:
                continue
            if item.answer_existence is AnswerExistence.NO_ANSWER:
                if item.false_positive or item.fabricated_citations:
                    blockers.append(f"critical_failed:{item.query_id}:负例被断言命中")
                continue
            if (item.doc_recall or Fraction(0)) != 1:
                blockers.append(f"critical_failed:{item.query_id}:DocRecall 未满分")
            if not item.question_pass:
                blockers.append(f"critical_failed:{item.query_id}:QuestionPass 未过")
            if item.evidence_pass is False:
                blockers.append(f"critical_failed:{item.query_id}:EvidencePass 未过")

    false_positives = [item.query_id for item in scored if item.false_positive]
    if len(false_positives) > policy.max_false_positives:
        blockers.append(f"false_positives:{len(false_positives)}>{policy.max_false_positives}")
    fabricated = [item.query_id for item in scored if item.fabricated_citations]
    if len(fabricated) > policy.max_fabricated_citations:
        blockers.append(f"fabricated_citations:{len(fabricated)}>{policy.max_fabricated_citations}")

    return tuple(blockers)
