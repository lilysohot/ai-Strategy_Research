"""dev lane（U 2026-09-20 裁决）——只对 dev 构建生效，生产 in_scope 判定不变。

本文件从 ``test_corpus_preparation_admission.py`` 拆出：dev-lane 用例须读取
U 指定 2 份开发材料（工业富联 MD + 光模块 DOCX），它们只存在于 ``guards/i3-e2e.json``
（8 份允许清单）的开发来源清单内，不在 ``guards/i1.json``（6 份）内。若留在
i1 测试文件，模块顶层 ``read_bytes()`` 会在 i1 守卫下于**收集期**抛 OSError，
整文件一个测试都跑不了。

运行环境（两个变量必须同时声明，阶段与配置须一致）::

    CORPUS_GUARD_PHASE=i3-e2e \\
    CORPUS_GUARD_CONFIG=.scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i3-e2e.json \\
    uv run pytest -p plugins.corpus.preparation.guard_pytest tests/test_corpus_dev_lane.py

不构造真实 PG/模型客户端。
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from plugins.corpus.preparation.admission import (
    POLICY_REV_V1,
    POLICY_REV_V2_DEV,
    RULE_REV,
    AdmissionError,
    AdmissionPolicy,
    ProbeInput,
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

REPO = Path(__file__).resolve().parents[1]
POLICY_PATH = REPO / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/admission-policy.json"
_REVIEWED_AT = datetime(2026, 9, 15, 12, 0, 0, tzinfo=UTC)


def _sid(name: str) -> str:
    return hashlib.sha256(name.encode("utf-8")).hexdigest()


def _policy() -> AdmissionPolicy:
    return load_admission_policy(POLICY_PATH)


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


# --- dev lane（U 2026-09-20 裁决）：只对 dev 构建生效，生产 in_scope 判定不变 ---

DEV_POLICY_PATH = (
    REPO
    / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260920-i31-dev-lane"
    / "admission-policy-dev.json"
)
DEV_MD_PATH = "data/corpus/工业富联_投委会决策报告_20260829.md"
DEV_DOCX_PATH = "data/corpus/9月8日 光模块技术演进与供应链重构：从1.6T到3.2T的路径、格局.docx"
DEV_MD_SID = hashlib.sha256((REPO / DEV_MD_PATH).read_bytes()).hexdigest()
DEV_DOCX_SID = hashlib.sha256((REPO / DEV_DOCX_PATH).read_bytes()).hexdigest()


def _dev_policy() -> AdmissionPolicy:
    return load_admission_policy(DEV_POLICY_PATH, allow_dev_lane=True)


def _dev_review(
    decision_id: str,
    source_id: str,
    *,
    decision: ReviewDecision,
    material_type: MaterialType | None = None,
    research_domain: ResearchDomain | None = None,
    supersedes: str | None = None,
) -> ReviewedDecision:
    return ReviewedDecision(
        decision_id=decision_id,
        source_id=source_id,
        reviewer="U",
        reviewed_at=_REVIEWED_AT,
        decision=decision,
        rationale="dev lane 用例（U 2026-09-20 裁决）",
        material_type=material_type,
        research_domain=research_domain,
        supersedes=supersedes,
    )


def _dev_source(path: str, source_id: str, domain: ResearchDomain, fmt: DocumentFormat):
    return SourceDescriptor(
        source_id=source_id,
        fmt=fmt,
        location=path,
        title=Path(path).name,
        domain_hint=domain,
    )


def test_dev_lane_policy_asset_lists_exactly_u_approved_sources() -> None:
    policy = _dev_policy()
    assert policy.policy_rev == POLICY_REV_V2_DEV
    assert policy.scope == "dev"
    assert policy.lane_id == "i3-1-dev-lane-md-docx"
    assert policy.dev_lane_sources == (DEV_MD_SID, DEV_DOCX_SID)
    assert policy.allowed_materials == (
        MaterialType.RESEARCH_REPORT,
        MaterialType.INTERNAL_COMMITTEE_REPORT,
        MaterialType.INTERNAL_UNATTRIBUTED,
    )
    # 生产政策逐字不改：仍是 scope=production + 仅 research_report
    production = _policy()
    assert production.policy_rev == POLICY_REV_V1
    assert production.scope == "production"
    assert production.allowed_materials == (MaterialType.RESEARCH_REPORT,)
    assert production.dev_lane_sources == ()


def test_dev_lane_policy_rejected_without_explicit_flag() -> None:
    # fail-closed：dev 政策不得在生产路径（默认 allow_dev_lane=False）装载
    with pytest.raises(AdmissionError, match="dev lane 政策不得在生产路径装载"):
        load_admission_policy(DEV_POLICY_PATH)


def test_dev_lane_policy_missing_allowed_materials_rejected(tmp_path: Path) -> None:
    data = json.loads(DEV_POLICY_PATH.read_text(encoding="utf-8"))
    data.pop("allowed_materials")
    path = tmp_path / "dev-policy.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(AdmissionError, match="allowed_materials"):
        load_admission_policy(path, allow_dev_lane=True)


def test_dev_lane_policy_missing_dev_lane_block_rejected(tmp_path: Path) -> None:
    data = json.loads(DEV_POLICY_PATH.read_text(encoding="utf-8"))
    data.pop("dev_lane")
    path = tmp_path / "dev-policy.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(AdmissionError, match="dev_lane"):
        load_admission_policy(path, allow_dev_lane=True)


def test_dev_lane_off_production_decision_unchanged() -> None:
    """生产路径只加载生产决定：仍是 excluded_by_policy（与 2026-09-15 裁定逐字一致）。"""
    source = _dev_source(DEV_MD_PATH, DEV_MD_SID, ResearchDomain.COMPANY, DocumentFormat.MARKDOWN)
    production = (
        _dev_review(
            "i0a2-c-industrial-fii",
            DEV_MD_SID,
            decision=ReviewDecision.EXCLUDED_FROM_ACTIVE,
            material_type=MaterialType.INTERNAL_COMMITTEE_REPORT,
        ),
    )
    admission = decide_admission(source, production, _probes(source.title, ""), _policy())
    assert admission.decision is AdmissionDecision.EXCLUDED_BY_POLICY
    assert admission.rule_rev == RULE_REV
    assert "dev_lane" not in " ".join(admission.evidence_refs)


def test_dev_lane_requires_dev_policy_not_v1() -> None:
    """即便存在 supersedes 的 admitted 决定，v1 政策下仍按冻结语义拒绝（policy_conflict）。"""
    source = _dev_source(DEV_MD_PATH, DEV_MD_SID, ResearchDomain.COMPANY, DocumentFormat.MARKDOWN)
    reviews = (
        _dev_review(
            "i0a2-c-industrial-fii",
            DEV_MD_SID,
            decision=ReviewDecision.EXCLUDED_FROM_ACTIVE,
            material_type=MaterialType.INTERNAL_COMMITTEE_REPORT,
        ),
        _dev_review(
            "devlane-c-industrial-fii",
            DEV_MD_SID,
            decision=ReviewDecision.ADMITTED,
            material_type=MaterialType.INTERNAL_COMMITTEE_REPORT,
            research_domain=ResearchDomain.COMPANY,
            supersedes="i0a2-c-industrial-fii",
        ),
    )
    admission = decide_admission(source, reviews, _probes(source.title, ""), _policy())
    assert admission.decision is AdmissionDecision.REVIEW_REQUIRED
    assert "policy_conflict" in admission.reason_codes


def test_dev_lane_on_admits_declared_source_with_truthful_material() -> None:
    source = _dev_source(DEV_MD_PATH, DEV_MD_SID, ResearchDomain.COMPANY, DocumentFormat.MARKDOWN)
    reviews = (
        _dev_review(
            "i0a2-c-industrial-fii",
            DEV_MD_SID,
            decision=ReviewDecision.EXCLUDED_FROM_ACTIVE,
            material_type=MaterialType.INTERNAL_COMMITTEE_REPORT,
        ),
        _dev_review(
            "devlane-c-industrial-fii",
            DEV_MD_SID,
            decision=ReviewDecision.ADMITTED,
            material_type=MaterialType.INTERNAL_COMMITTEE_REPORT,
            research_domain=ResearchDomain.COMPANY,
            supersedes="i0a2-c-industrial-fii",
        ),
    )
    admission = decide_admission(source, reviews, _probes(source.title, ""), _dev_policy())
    assert admission.decision is AdmissionDecision.IN_SCOPE
    # 材料类型如实（不得伪写为 research_report）
    assert admission.material_type is MaterialType.INTERNAL_COMMITTEE_REPORT
    assert admission.research_domain is ResearchDomain.COMPANY
    assert admission.rule_rev == f"decision-order-{POLICY_REV_V2_DEV}"
    assert "dev_lane=i3-1-dev-lane-md-docx" in admission.evidence_refs
    assert "admitted_material=internal_committee_report" in admission.evidence_refs


def test_dev_lane_on_admits_declared_docx_source() -> None:
    source = _dev_source(
        DEV_DOCX_PATH, DEV_DOCX_SID, ResearchDomain.INDUSTRY, DocumentFormat.DOCX
    )
    reviews = (
        _dev_review(
            "i0a2-d-optical-docx",
            DEV_DOCX_SID,
            decision=ReviewDecision.EXCLUDED_FROM_ACTIVE,
            material_type=MaterialType.INTERNAL_UNATTRIBUTED,
        ),
        _dev_review(
            "devlane-d-optical-docx",
            DEV_DOCX_SID,
            decision=ReviewDecision.ADMITTED,
            material_type=MaterialType.INTERNAL_UNATTRIBUTED,
            research_domain=ResearchDomain.INDUSTRY,
            supersedes="i0a2-d-optical-docx",
        ),
    )
    admission = decide_admission(source, reviews, _probes(source.title, ""), _dev_policy())
    assert admission.decision is AdmissionDecision.IN_SCOPE
    assert admission.material_type is MaterialType.INTERNAL_UNATTRIBUTED
    assert admission.research_domain is ResearchDomain.INDUSTRY


def test_dev_lane_on_does_not_widen_other_sources() -> None:
    """dev lane 逐源生效：未列入 dev_lane.sources 的来源仍被冻结语义拒绝。"""
    other_sid = _sid("other-internal-committee.md")
    source = _dev_source(
        "data/corpus/其他_投委会决策报告.md", other_sid, ResearchDomain.COMPANY, DocumentFormat.MARKDOWN
    )
    reviews = (
        _dev_review(
            "other-excluded",
            other_sid,
            decision=ReviewDecision.EXCLUDED_FROM_ACTIVE,
            material_type=MaterialType.INTERNAL_COMMITTEE_REPORT,
        ),
        _dev_review(
            "other-admitted",
            other_sid,
            decision=ReviewDecision.ADMITTED,
            material_type=MaterialType.INTERNAL_COMMITTEE_REPORT,
            research_domain=ResearchDomain.COMPANY,
            supersedes="other-excluded",
        ),
    )
    admission = decide_admission(source, reviews, _probes(source.title, ""), _dev_policy())
    assert admission.decision is AdmissionDecision.REVIEW_REQUIRED
    assert "policy_conflict" in admission.reason_codes
