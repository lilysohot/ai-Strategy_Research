"""I3-1 dev lane 独立反例探针（对抗式）：证明 dev lane **不能**外溢为生产放宽。

复核面（与实现方自测分开，独立成文件）：
1. dev 政策未显式放行即拒绝装载（fail-closed）；
2. dev 声明自相矛盾/字段缺失/来源清单非法一律拒绝；
3. v1 冻结政策下，带完整取代链的 dev 来源仍判 policy_conflict（生产判定不变）；
4. dev lane 只对清单内来源生效（未列入者不放宽）；
5. 生产 scope 即便声明放宽 `allowed_materials` 也不能放行内部材料（防夹带）；
6. 契约的材料类型不变量按 policy_rev 绑定，未知版本落最严默认；
7. 落地的 `material_type` 必须**如实**（不得被伪写为 research_report）。

只读 `.scratch/`（守卫 runtime root）与内存构造；不读 `data/` 来源、不触 PG、不调模型。
篡改件写在仓库内临时目录（守卫阶段不依赖 /tmp）。
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
    AdmissionError,
    ProbeInput,
    SourceDescriptor,
    decide_admission,
    load_admission_policy,
    probe_features,
)
from plugins.corpus.preparation.contract import (
    Admission,
    AdmissionDecision,
    ContractError,
    DocumentFormat,
    MaterialType,
    ResearchDomain,
    ReviewDecision,
    ReviewedDecision,
)

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
DEV_POLICY = HERE / "admission-policy-dev.json"
PROD_POLICY = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/admission-policy.json"
SCRATCH = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i2/tmp/dev-lane-probes"
MD_SID = "f8fa22084535e3696fed0bc4da1e9a1b71c863ddb1a883603dcb3d251839cbcb"
DOCX_SID = "48c05895798ba0096b5ac5cc6fbf42fcc9d63929c2a7a2df61e7b16b3a4a659f"
OTHER_SID = hashlib.sha256(b"probe-other-internal.md").hexdigest()
REVIEWED_AT = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


def _tampered(**overrides: object) -> Path:
    SCRATCH.mkdir(parents=True, exist_ok=True)
    data = json.loads(DEV_POLICY.read_text(encoding="utf-8"))
    data.update(overrides)
    key = hashlib.sha256(
        json.dumps(data, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:12]
    path = SCRATCH / f"dev-policy-{key}.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def _source(sid: str, path: str, fmt: DocumentFormat, domain: ResearchDomain) -> SourceDescriptor:
    return SourceDescriptor(source_id=sid, fmt=fmt, location=path, title=Path(path).name,
                            domain_hint=domain)


def _review(decision_id: str, sid: str, decision: ReviewDecision,
            material: MaterialType | None = None,
            domain: ResearchDomain | None = None, supersedes: str | None = None) -> ReviewedDecision:
    return ReviewedDecision(decision_id=decision_id, source_id=sid, reviewer="probe",
                            reviewed_at=REVIEWED_AT, decision=decision,
                            rationale="独立反例探针", material_type=material,
                            research_domain=domain, supersedes=supersedes)


def _dev_chain(sid: str, domain: ResearchDomain, material: MaterialType):
    return (
        _review("prod", sid, ReviewDecision.EXCLUDED_FROM_ACTIVE, material),
        _review("dev", sid, ReviewDecision.ADMITTED, material, domain, supersedes="prod"),
    )


def _probes(title: str):
    return probe_features(ProbeInput(title=title, head_text="", body_lines=(), heading_texts=()))


# --- 1. 装载门（fail-closed） ---


def test_probe_dev_policy_refused_without_explicit_flag() -> None:
    with pytest.raises(AdmissionError, match="dev lane 政策不得在生产路径装载"):
        load_admission_policy(DEV_POLICY)


def test_probe_dev_policy_requires_production_unchanged_true() -> None:
    path = _tampered(production_in_scope_unchanged=False)
    with pytest.raises(AdmissionError, match="生产路径"):
        load_admission_policy(path)  # 未显式放行：先被装载门拦下


def test_probe_dev_policy_rejects_empty_sources() -> None:
    data = json.loads(DEV_POLICY.read_text(encoding="utf-8"))
    data["dev_lane"] = {**data["dev_lane"], "sources": []}
    SCRATCH.mkdir(parents=True, exist_ok=True)
    path = SCRATCH / "dev-policy-empty-sources.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(AdmissionError, match="sources"):
        load_admission_policy(path, allow_dev_lane=True)


def test_probe_dev_policy_rejects_non_sha256_source_id() -> None:
    data = json.loads(DEV_POLICY.read_text(encoding="utf-8"))
    data["dev_lane"] = {
        **data["dev_lane"],
        "sources": [{**data["dev_lane"]["sources"][0], "source_id": "short-id"}],
    }
    SCRATCH.mkdir(parents=True, exist_ok=True)
    path = SCRATCH / "dev-policy-bad-sid.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(AdmissionError, match="source_id"):
        load_admission_policy(path, allow_dev_lane=True)


def test_probe_production_policy_still_loads_and_is_narrow() -> None:
    policy = load_admission_policy(PROD_POLICY)
    assert policy.policy_rev == POLICY_REV_V1
    assert policy.scope == "production"
    assert policy.allowed_materials == (MaterialType.RESEARCH_REPORT,)
    assert policy.dev_lane_sources == ()


# --- 2/3. 生产判定不变 ---


def test_probe_v1_policy_keeps_dev_material_out_even_with_chain() -> None:
    source = _source(MD_SID, "data/corpus/工业富联_投委会决策报告_20260829.md",
                     DocumentFormat.MARKDOWN, ResearchDomain.COMPANY)
    admission = decide_admission(
        source, _dev_chain(MD_SID, ResearchDomain.COMPANY, MaterialType.INTERNAL_COMMITTEE_REPORT),
        _probes(source.title), load_admission_policy(PROD_POLICY),
    )
    assert admission.decision is AdmissionDecision.REVIEW_REQUIRED
    assert "policy_conflict" in admission.reason_codes


def test_probe_dev_lane_does_not_widen_unlisted_source() -> None:
    source = _source(OTHER_SID, "data/corpus/其他_投委会决策报告.md",
                     DocumentFormat.MARKDOWN, ResearchDomain.COMPANY)
    admission = decide_admission(
        source, _dev_chain(OTHER_SID, ResearchDomain.COMPANY, MaterialType.INTERNAL_COMMITTEE_REPORT),
        _probes(source.title), load_admission_policy(DEV_POLICY, allow_dev_lane=True),
    )
    assert admission.decision is AdmissionDecision.REVIEW_REQUIRED
    assert "policy_conflict" in admission.reason_codes


def test_probe_production_scope_cannot_widen_via_allowed_materials() -> None:
    """防夹带：把 dev 政策改成 scope=production 并保留放宽材料，仍不得放行内部材料。"""
    path = _tampered(scope="production")
    policy = load_admission_policy(path)
    source = _source(MD_SID, "data/corpus/工业富联_投委会决策报告_20260829.md",
                     DocumentFormat.MARKDOWN, ResearchDomain.COMPANY)
    admission = decide_admission(
        source, _dev_chain(MD_SID, ResearchDomain.COMPANY, MaterialType.INTERNAL_COMMITTEE_REPORT),
        _probes(source.title), policy,
    )
    assert admission.decision is AdmissionDecision.REVIEW_REQUIRED
    assert "policy_conflict" in admission.reason_codes


# --- 4/5. dev 落地事实 ---


def test_probe_dev_lane_sets_truthful_material_type_and_marker() -> None:
    policy = load_admission_policy(DEV_POLICY, allow_dev_lane=True)
    source = _source(MD_SID, "data/corpus/工业富联_投委会决策报告_20260829.md",
                     DocumentFormat.MARKDOWN, ResearchDomain.COMPANY)
    admission = decide_admission(
        source, _dev_chain(MD_SID, ResearchDomain.COMPANY, MaterialType.INTERNAL_COMMITTEE_REPORT),
        _probes(source.title), policy,
    )
    assert admission.decision is AdmissionDecision.IN_SCOPE
    assert admission.material_type is MaterialType.INTERNAL_COMMITTEE_REPORT
    assert admission.material_type is not MaterialType.RESEARCH_REPORT
    assert admission.policy_rev == POLICY_REV_V2_DEV
    assert f"dev_lane={policy.lane_id}" in admission.evidence_refs


def test_probe_dev_lane_docx_material_type_truthful() -> None:
    policy = load_admission_policy(DEV_POLICY, allow_dev_lane=True)
    source = _source(DOCX_SID, "data/corpus/9月8日 光模块技术演进与供应链重构：从1.6T到3.2T的路径、格局.docx",
                     DocumentFormat.DOCX, ResearchDomain.INDUSTRY)
    admission = decide_admission(
        source, _dev_chain(DOCX_SID, ResearchDomain.INDUSTRY, MaterialType.INTERNAL_UNATTRIBUTED),
        _probes(source.title), policy,
    )
    assert admission.decision is AdmissionDecision.IN_SCOPE
    assert admission.material_type is MaterialType.INTERNAL_UNATTRIBUTED


# --- 6. 契约不变量 ---


def test_probe_contract_unknown_policy_rev_falls_back_to_strict() -> None:
    common = {
        "decision_id": "probe-d",
        "source_id": hashlib.sha256(b"probe-x").hexdigest(),
        "research_domain": ResearchDomain.COMPANY,
        "decision": AdmissionDecision.IN_SCOPE,
    }
    with pytest.raises(ContractError, match="research_report"):
        Admission(policy_rev="v9-unknown", material_type=MaterialType.INTERNAL_UNATTRIBUTED, **common)  # type: ignore[arg-type]
    with pytest.raises(ContractError, match="research_report"):
        Admission(policy_rev=POLICY_REV_V1, material_type=MaterialType.INTERNAL_COMMITTEE_REPORT, **common)  # type: ignore[arg-type]
