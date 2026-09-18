"""I1-5 准入判定测试：表驱动 gold 全过、同输入同版本同结果、未决不能发布。

验收（任务 I1-5）：确认清单纯函数、固定判定次序、冲突/未知原因。资源 =
admission-policy（I0A-3 冻结资产 v1-20260915）。锁定正反例：高盛 GS 茅台→
broker、FundaAI→absent 反例、长江化工十问十答 admitted industry（标题自设
问答非访谈实录，mixed_material 不阻断人工纳入）、unreadable ≠ absent。
不构造真实 PG/模型客户端。
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from plugins.corpus.preparation.admission import (
    POLICY_REV_V1,
    PROBE_REV,
    RULE_REV,
    AdmissionError,
    AdmissionPolicy,
    ProbeInput,
    ProbeValue,
    SourceDescriptor,
    decide_admission,
    load_admission_policy,
    probe_features,
)
from plugins.corpus.preparation.contract import (
    AdmissionDecision,
    DocumentFormat,
    MaterialType,
    ResearchDomain,
    ReviewDecision,
    ReviewedDecision,
)
from plugins.corpus.preparation.readers import read_document
from plugins.corpus.preparation.readers.base import UnitStatus

REPO = Path(__file__).resolve().parents[1]
POLICY_PATH = REPO / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/admission-policy.json"
_FEATURE_IDS = (
    "title_type_marker",
    "byline_institution",
    "heading_hierarchy",
    "speaker_turns",
    "qa_markers",
    "transcript_declaration",
)

_REVIEWED_AT = datetime(2026, 9, 15, 12, 0, 0, tzinfo=UTC)


def _sid(name: str) -> str:
    return hashlib.sha256(name.encode("utf-8")).hexdigest()


def _policy() -> AdmissionPolicy:
    return load_admission_policy(POLICY_PATH)


def _decision(
    decision_id: str,
    source_id: str,
    decision: ReviewDecision = ReviewDecision.ADMITTED,
    *,
    scope_ref: str | None = None,
    locators: tuple[str, ...] = (),
    supersedes: str | None = None,
) -> ReviewedDecision:
    return ReviewedDecision(
        decision_id=decision_id,
        source_id=source_id,
        reviewer="U",
        reviewed_at=_REVIEWED_AT,
        decision=decision,
        rationale="表驱动金标用例",
        scope_ref=scope_ref,
        supersedes=supersedes,
        locators=locators,
    )


def _source(
    *,
    title: str = "高盛GS：贵州茅台600519-2026年中报点评-报表实质扎实",
    domain: ResearchDomain | None = ResearchDomain.COMPANY,
    head: str = "高盛(中国)证券有限责任公司研究所",
    lines: tuple[str, ...] = ("盈利拐点确认。", "维持买入评级。"),
    source_id: str | None = None,
) -> SourceDescriptor:
    return SourceDescriptor(
        source_id=source_id or _sid("broker-moutai-1"),
        fmt=DocumentFormat.PDF,
        location="data/corpus/broker-moutai-1.pdf",
        title=title,
        domain_hint=domain,
    )


def _probes(
    title: str,
    head: str,
    lines: tuple[str, ...] = (),
    headings: tuple[str, ...] = (),
):
    return probe_features(
        ProbeInput(
            title=title, head_text=head, body_lines=tuple(lines), heading_texts=tuple(headings)
        )
    )


def _decide(source, decisions=(), probes=None):
    return decide_admission(
        source,
        tuple(decisions),
        probes if probes is not None else _probes(source.title, "研究所", ("正文内容。",)),
        _policy(),
    )


# --- 特征探查：有序首中与锁定正反例 ---


@pytest.mark.parametrize(
    ("title", "expected_detail"),
    [
        ("投委会会议纪要", "minutes"),  # 有序首中：minutes 先于 committee
        ("电话会交流实录", "minutes"),
        ("投委会README", "committee"),
        ("README", "pipeline"),
        ("c0_report", "pipeline"),
        ("c1c2_notes", "pipeline"),
        ("复盘：高盛观点", "personal"),  # personal 先于 broker
        ("Macro-Charts 每日", "personal"),
        ("CapitalWars digest", "personal"),
        ("高盛：贵州茅台点评", "broker"),
        ("GS：茅台", "broker"),
        ("摩根大通观点", "broker"),
        ("证券研究", "broker"),
        ("贵州茅台2026年中报点评", "absent"),
        ("FundaAI 每日观察", "absent"),  # 锁定反例
    ],
)
def test_title_type_marker_ordered_first_match(title: str, expected_detail: str) -> None:
    probe = _probes(title, "无关正文。")[0]
    assert probe.feature_id == "title_type_marker"
    if expected_detail == "absent":
        assert probe.value is ProbeValue.ABSENT
        assert probe.detail == ""
    else:
        assert probe.value is ProbeValue.MATCHED
        assert probe.detail == expected_detail


@pytest.mark.parametrize(
    ("head", "expected_detail"),
    [
        ("华创证券研究所", "broker"),
        ("GS 分部数据", "broker"),  # GS\b
        ("GSX 无关前缀", "absent"),
        ("Capital-Wars 每日", "personal"),
        ("JamesBulltard", "personal"),
        ("无署名正文片段", "absent"),
    ],
)
def test_byline_institution_patterns(head: str, expected_detail: str) -> None:
    probe = _probes("普通标题", head)[1]
    assert probe.feature_id == "byline_institution"
    if expected_detail == "absent":
        assert probe.value is ProbeValue.ABSENT
    else:
        assert probe.value is ProbeValue.MATCHED
        assert probe.detail == expected_detail


def test_speaker_turns_three_distinct_prefixes_matched() -> None:
    lines = ("张三： 观点一。", "李四： 观点二。", "王五： 观点三。")
    probe = _probes("专家访谈", "", lines=lines)[3]
    assert probe.value is ProbeValue.MATCHED


def test_speaker_turns_self_qa_pair_absent() -> None:
    # 恰为『问：/答：』自设问答 → 非访谈实录（十问十答先例的探查语义）。
    lines = ("问： 增长如何？", "答： 稳健。")
    probe = _probes("自设问答", "", lines=lines)[3]
    assert probe.value is ProbeValue.ABSENT


def test_qa_markers_two_hits_matched_one_absent() -> None:
    two = _probes("十问十答", "", lines=("提问： Q1？", "答： A1。", "提问： Q2？", "答： A2。"))[4]
    assert two.value is ProbeValue.MATCHED
    one = _probes("十问十答", "", lines=("提问： Q1？", "答： A1。"))[4]
    assert one.value is ProbeValue.ABSENT


def test_transcript_declaration_window_2000() -> None:
    inside = _probes("电话会", "", lines=("开头。", "以下为本次电话会议实录。"))[5]
    assert inside.value is ProbeValue.MATCHED
    beyond = _probes("电话会", "", lines=("x" * 2500 + "实录",))[5]
    assert beyond.value is ProbeValue.ABSENT  # 声明窗 2000 字符，窗外不扫


def test_heading_hierarchy_two_hits_matched() -> None:
    matched = _probes("研报", "", headings=("一、投资要点", "二、风险提示", "正文"))[2]
    assert matched.value is ProbeValue.MATCHED
    single = _probes("研报", "", headings=("一、投资要点",))[2]
    assert single.value is ProbeValue.ABSENT


def test_unreadable_is_not_absent() -> None:
    probes = _probes("", "", (), ())
    assert len(probes) == 6
    for probe in probes:
        assert probe.value is ProbeValue.UNREADABLE  # 探查不到内容 ≠ 确认无标记
        assert probe.extractor_rev == PROBE_REV
        assert probe.source_locator


# --- 判定次序：表驱动 gold ---


def test_admitted_broker_report_in_scope() -> None:
    source = _source()
    admission = _decide(source, (_decision("d1", source.source_id),))
    assert admission.decision is AdmissionDecision.IN_SCOPE
    assert admission.material_type is MaterialType.RESEARCH_REPORT
    assert admission.research_domain is ResearchDomain.COMPANY
    assert admission.reason_codes == ()
    assert admission.review_ref == "d1"
    assert admission.scope_ref is None
    assert admission.policy_rev == POLICY_REV_V1
    assert admission.rule_rev == RULE_REV
    assert "title_type_marker=matched:broker" in admission.evidence_refs


def test_no_decision_missing_review_cannot_publish() -> None:
    admission = _decide(_source(), ())
    assert admission.decision is AdmissionDecision.REVIEW_REQUIRED
    assert admission.reason_codes == ("missing_review",)
    assert admission.review_ref is None


def test_two_unresolved_tips_conflicting_review() -> None:
    source = _source()
    decisions = (
        _decision("d1", source.source_id, ReviewDecision.ADMITTED),
        _decision("d2", source.source_id, ReviewDecision.EXCLUDED),
    )
    admission = _decide(source, decisions)
    assert admission.decision is AdmissionDecision.REVIEW_REQUIRED
    assert admission.reason_codes == ("conflicting_review",)
    assert admission.review_ref is None  # 不凭时间最新猜测覆盖


def test_supersede_chain_resolves_to_new_decision() -> None:
    source = _source()
    decisions = (
        _decision("d1", source.source_id, ReviewDecision.ADMITTED),
        _decision("d2", source.source_id, ReviewDecision.EXCLUDED, supersedes="d1"),
    )
    admission = _decide(source, decisions)
    assert admission.decision is AdmissionDecision.EXCLUDED_BY_POLICY
    assert admission.review_ref == "d2"  # 显式取代链唯一生效


def test_broken_supersede_chain_conflicting() -> None:
    source = _source()
    decisions = (_decision("d2", source.source_id, ReviewDecision.ADMITTED, supersedes="ghost"),)
    admission = _decide(source, decisions)
    assert admission.decision is AdmissionDecision.REVIEW_REQUIRED
    assert "conflicting_review" in admission.reason_codes


def test_decision_bound_to_other_hash_is_source_changed() -> None:
    source = _source()
    decisions = (_decision("old-1", _sid("old-source"), ReviewDecision.ADMITTED),)
    admission = _decide(source, decisions)
    assert admission.decision is AdmissionDecision.REVIEW_REQUIRED
    assert "source_changed" in admission.reason_codes
    assert admission.decision is not AdmissionDecision.IN_SCOPE  # 新哈希不继承旧批准


def test_scope_ref_without_locators_invalid_locator() -> None:
    source = _source()
    decisions = (_decision("d1", source.source_id, scope_ref="scope-1"),)
    admission = _decide(source, decisions)
    assert admission.decision is AdmissionDecision.REVIEW_REQUIRED
    assert admission.reason_codes == ("invalid_locator",)


def test_scoped_admission_stays_scoped() -> None:
    source = _source()
    decisions = (_decision("d1", source.source_id, scope_ref="scope-1", locators=("p3",)),)
    admission = _decide(source, decisions)
    assert admission.decision is AdmissionDecision.IN_SCOPE
    assert admission.scope_ref == "scope-1"  # 部分章节批准按坐标纳入，不升级整篇


def test_locators_without_scope_ref_scope_upgrade_rejected() -> None:
    source = _source()
    decisions = (_decision("d1", source.source_id, locators=("p3",)),)
    admission = _decide(source, decisions)
    assert admission.decision is AdmissionDecision.REVIEW_REQUIRED
    assert admission.reason_codes == ("scope_upgrade_rejected",)


def test_admitted_minutes_title_policy_conflict() -> None:
    source = _source(title="投委会会议纪要", head="内部流转", lines=("议题一。",))
    decisions = (_decision("d1", source.source_id),)
    admission = _decide(source, decisions)
    assert admission.decision is AdmissionDecision.REVIEW_REQUIRED
    assert admission.material_type is MaterialType.INTERNAL_UNATTRIBUTED
    assert admission.reason_codes == ("policy_conflict",)


def test_excluded_minutes_excluded_by_policy() -> None:
    source = _source(title="投委会会议纪要", head="内部流转", lines=("议题一。",))
    decisions = (_decision("d1", source.source_id, ReviewDecision.EXCLUDED),)
    admission = _decide(source, decisions)
    assert admission.decision is AdmissionDecision.EXCLUDED_BY_POLICY
    assert admission.material_type is MaterialType.INTERNAL_UNATTRIBUTED
    assert admission.review_ref == "d1"


def test_excluded_from_active_also_excluded() -> None:
    source = _source()
    decisions = (_decision("d1", source.source_id, ReviewDecision.EXCLUDED_FROM_ACTIVE),)
    assert _decide(source, decisions).decision is AdmissionDecision.EXCLUDED_BY_POLICY


def test_missing_domain_hint_unsupported_domain() -> None:
    source = _source(domain=None)
    decisions = (_decision("d1", source.source_id),)
    admission = _decide(source, decisions)
    assert admission.decision is AdmissionDecision.REVIEW_REQUIRED
    assert admission.reason_codes == ("unsupported_domain",)


def test_mixed_signals_admitted_still_in_scope_with_mixed_material() -> None:
    # 长江化工十问十答先例：标题自设问答非访谈实录，mixed 只记不阻断人工纳入。
    source = _source(
        title="长江证券-化工专题-景气投资-十问十答",
        domain=ResearchDomain.INDUSTRY,
        head="长江证券研究所",
        lines=(
            "提问： 景气投资为何失效？",
            "答： 需求与供给错配。",
            "提问： 如何修复？",
            "答： 关注资本开支。",
        ),
    )
    decisions = (_decision("d1", source.source_id),)
    admission = _decide(
        source,
        decisions,
        _probes(
            source.title,
            "长江证券研究所",
            (
                "提问： 景气投资为何失效？",
                "答： 需求与供给错配。",
                "提问： 如何修复？",
                "答： 关注资本开支。",
            ),
        ),
    )
    assert admission.decision is AdmissionDecision.IN_SCOPE
    assert admission.material_type is MaterialType.RESEARCH_REPORT
    assert admission.research_domain is ResearchDomain.INDUSTRY
    assert admission.reason_codes == ("mixed_material",)


def test_all_absent_admitted_in_scope_without_reasons() -> None:
    # admitted absent 先例：全 absent 标记不否定人工纳入决定。
    source = _source(
        title="FundaAI 每日观察",
        head="内部观察记录",
        lines=("市场波动加大。",),
    )
    decisions = (_decision("d1", source.source_id),)
    admission = _decide(source, decisions)
    assert admission.decision is AdmissionDecision.IN_SCOPE
    assert admission.reason_codes == ()


def test_unreadable_probes_no_decision_records_both_reasons() -> None:
    source = _source()
    admission = decide_admission(source, (), _probes("", "", (), ()), _policy())
    assert admission.decision is AdmissionDecision.REVIEW_REQUIRED
    assert admission.reason_codes == ("missing_review", "unreadable_probe")  # 契约定义序


def test_duplicate_or_missing_probe_features_rejected() -> None:
    source = _source()
    probes = _probes(source.title, "高盛(中国)证券有限责任公司研究所", ("盈利拐点确认。",))
    with pytest.raises(AdmissionError, match="特征重复"):
        decide_admission(source, (), (*probes, probes[0]), _policy())
    with pytest.raises(AdmissionError, match="缺少特征"):
        decide_admission(source, (), probes[:-1], _policy())


def test_determinism_same_input_same_decision_id() -> None:
    source = _source()
    probes = _probes(source.title, "高盛(中国)证券有限责任公司研究所", ("盈利拐点确认。",))
    decisions = (_decision("d1", source.source_id),)
    first = decide_admission(source, decisions, probes, _policy())
    second = decide_admission(source, decisions, probes, _policy())
    assert first == second  # 同输入同版本同结果（含 decision_id 逐字节一致）
    other_domain = decide_admission(
        _source(domain=ResearchDomain.MACRO), decisions, probes, _policy()
    )
    assert first.decision_id != other_domain.decision_id  # 领域进入指纹


# --- 政策装载：fail-closed 校验 ---


def test_load_frozen_policy_from_i0a3_asset() -> None:
    policy = _policy()
    assert policy.policy_rev == POLICY_REV_V1
    assert policy.allowed_domains == (
        ResearchDomain.COMPANY,
        ResearchDomain.INDUSTRY,
        ResearchDomain.MACRO,
    )


def _write_policy(tmp_path: Path, **overrides: object) -> Path:
    data = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    data.update(overrides)
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def test_policy_not_frozen_rejected(tmp_path: Path) -> None:
    with pytest.raises(AdmissionError, match="未冻结"):
        load_admission_policy(_write_policy(tmp_path, frozen=False))


def test_policy_auto_decision_enabled_rejected(tmp_path: Path) -> None:
    with pytest.raises(AdmissionError, match="自动准入"):
        load_admission_policy(_write_policy(tmp_path, auto_decision={"enabled": True}))


def test_policy_bad_rev_rejected(tmp_path: Path) -> None:
    with pytest.raises(AdmissionError, match="policy_rev"):
        load_admission_policy(_write_policy(tmp_path, policy_rev="20260915"))


def test_policy_non_object_rejected(tmp_path: Path) -> None:
    path = tmp_path / "policy.json"
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(AdmissionError, match="JSON 对象"):
        load_admission_policy(path)


# --- 6 份开发材料只读 smoke：机器只给建议，未决不能发布 ---


def _dev_materials() -> list[Path]:
    config_path = REPO / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i1.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    return [REPO / raw for raw in config["sources"]["allowed_source_paths"]]


def test_dev_materials_probe_and_admission_invariants() -> None:
    for path in _dev_materials():
        reader_result = read_document(path)
        kept = [u for u in reader_result.units if u.status is UnitStatus.KEPT]
        head_text = "\n".join(u.raw_text for u in kept[:3])
        body_lines = tuple(line for u in kept[:100] for line in u.raw_text.splitlines())[:200]
        heading_texts = tuple(u.raw_text for u in kept if u.kind == "heading")
        probes = probe_features(
            ProbeInput(
                title=path.name,
                head_text=head_text,
                body_lines=body_lines,
                heading_texts=heading_texts,
            )
        )
        assert {p.feature_id for p in probes} == set(_FEATURE_IDS)
        assert all(p.value in ProbeValue for p in probes)
        assert all(p.extractor_rev == PROBE_REV for p in probes)
        source = SourceDescriptor(
            source_id=_sid(path.name),
            fmt=reader_result.format,
            location=str(path.relative_to(REPO)),
            title=path.name,
            domain_hint=ResearchDomain.COMPANY,
        )
        admission = decide_admission(source, (), probes, _policy())
        assert admission.decision is AdmissionDecision.REVIEW_REQUIRED, path.name
        assert "missing_review" in admission.reason_codes  # 无人工决定一律未决


def test_admission_does_not_import_pg_or_model_client() -> None:
    # 干净子进程断言：同进程其他测试文件（如 metadata 的 psycopg）不应污染本纪律
    code = (
        "import sys; import plugins.corpus.preparation.admission;"
        "bad = [m for m in ('psycopg', 'psycopg2', 'asyncpg', 'sqlalchemy',"
        " 'openai', 'anthropic') if m in sys.modules];"
        "print(f'leaked: {bad}'); sys.exit(1 if bad else 0)"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
