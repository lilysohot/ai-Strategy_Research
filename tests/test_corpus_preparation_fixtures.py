"""I1-9 合成夹具收口测试（tests/fixtures/corpus_preparation）。

验收（任务 I1-9）：合成 MD/DOCX/PDF 小夹具进入公共目录（真实版权资料不入
公开夹具，架构 §12.1），并以其为固定样本收口 fidelity/mapping/引用式关联与
engine 全链/幂等路径。夹具内容全部虚构（公司「星尘新材料」与全部数字均为
编造），全程零模型、零 PG、不触留出。守卫语义：tests/fixtures 位于仓库根
runtime 路径内，仅只读，不构成来源授权。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from plugins.corpus.preparation.admission import POLICY_REV_V1, AdmissionPolicy
from plugins.corpus.preparation.chunk import chunk_clean_result, verify_chunk_result
from plugins.corpus.preparation.clean import (
    clean_reader_result,
    verify_clean_region,
)
from plugins.corpus.preparation.contract import (
    CHUNK_KINDS,
    AdmissionDecision,
    LeaseConfig,
    ResearchDomain,
    ReviewDecision,
    ReviewedDecision,
    UnitStatus,
    sha256_of_bytes,
)
from plugins.corpus.preparation.engine import (
    EngineError,
    ExecuteReport,
    PlanEntry,
    execute_builds,
    plan_builds,
    publish_build,
)
from plugins.corpus.preparation.readers import read_document
from plugins.corpus.preparation.repository import MemoryStore, StoreError

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "corpus_preparation"
MD = FIXTURES / "synthetic-company-report.md"
DOCX = FIXTURES / "synthetic-company-report.docx"
PDF = FIXTURES / "synthetic-company-report.pdf"

NOW = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)
POLICY = AdmissionPolicy(
    policy_rev=POLICY_REV_V1,
    allowed_domains=(ResearchDomain.COMPANY, ResearchDomain.INDUSTRY, ResearchDomain.MACRO),
)
LEASE = LeaseConfig(
    lease_ttl_seconds=300,
    heartbeat_interval_seconds=60,
    stage_timeout_seconds=600,
    max_attempts=3,
)


def _review(source_id: str) -> ReviewedDecision:
    return ReviewedDecision(
        decision_id="r1",
        source_id=source_id,
        reviewer="fixture",
        reviewed_at=NOW,
        decision=ReviewDecision.ADMITTED,
        rationale="合成夹具正例",
    )


def _execute(
    store: MemoryStore, source: Path, tmp_path: Path, decision_ids: tuple[str, ...] = ("r1",)
) -> ExecuteReport:
    plan = plan_builds(
        [
            PlanEntry(
                path=str(source),
                domain_hint=ResearchDomain.COMPANY,
                review_decision_ids=decision_ids,
            )
        ],
        policy=POLICY,
    )
    return execute_builds(
        store,
        plan,
        policy=POLICY,
        archive_root=tmp_path / "archive",
        owner_id="i1-9-fixture",
        now=NOW,
        lease=LEASE,
    )


# --- 夹具清单：synthetic-only（版权原料不入公开夹具） ---


def test_fixture_directory_is_synthetic_only() -> None:
    expected = {
        "synthetic-company-report.md",
        "synthetic-company-report.docx",
        "synthetic-company-report.pdf",
    }
    assert {path.name for path in FIXTURES.iterdir()} == expected
    md_text = MD.read_text(encoding="utf-8")
    assert "合成夹具" in md_text and "虚构" in md_text


# --- fidelity：三格式读取与缺口记账 ---


def test_md_fixture_repeated_headings_and_span_fidelity() -> None:
    result = read_document(MD)
    assert result.issues == ()
    headings = [unit for unit in result.units if unit.kind == "heading"]
    repeated = [h for h in headings if h.raw_text == "## 风险提示"]
    assert len(repeated) == 2 and repeated[0].ordinal != repeated[1].ordinal
    text = MD.read_text(encoding="utf-8")
    for unit in result.units:
        span = unit.location.char_span
        assert span is not None
        assert text[span.start : span.end] == unit.raw_text, unit.raw_text
    table_rows = [u for u in result.units if u.kind == "table_row"]
    assert any("-234.5" in row.raw_text for row in table_rows)  # 负数与单位保留
    assert any(unit.raw_text.startswith("问：") for unit in result.units)
    assert any("若下游需求不及预期" in unit.raw_text for unit in result.units)  # 条件句


def test_pdf_fixture_page_gap_accounting() -> None:
    result = read_document(PDF)
    assert result.page_count == 4
    codes = [issue.code for issue in result.issues]
    assert codes.count("empty_page") == 1  # 第 4 页
    assert codes.count("image_only_page") == 1  # 第 3 页
    assert codes.count("image_region_unreadable") == 1  # 第 2 页 ≥25% 面积
    assert "multi_column_order_unreliable" not in codes
    assert result.units[0].kind == "heading"  # 第 1 页大字号标题
    assert all(unit.location.page in (1, 2) for unit in result.units)


def test_docx_fixture_nested_table_and_cell_image() -> None:
    result = read_document(DOCX)
    codes = [issue.code for issue in result.issues]
    assert "unreadable_element" in codes
    cell_issues = [i for i in result.issues if i.code == "unreadable_element"]
    assert any("tbl[0]/row[0]/cell[1]" in i.location for i in cell_issues)  # cell 内图片
    table_rows = [u for u in result.units if u.kind == "table_row"]
    nested_texts = "\n".join(row.raw_text for row in table_rows)
    assert "年份" in nested_texts and "10,000.0" in nested_texts  # 嵌套子表行不丢失
    headings = [u for u in result.units if u.kind == "heading"]
    repeated = [h for h in headings if h.raw_text == "风险提示"]
    assert len(repeated) == 2 and repeated[0].ordinal != repeated[1].ordinal


# --- mapping：清洗映射回权威原文 + 缺口区域台账 ---


@pytest.mark.parametrize(
    ("source", "label"),
    [(MD, "md"), (DOCX, "docx"), (PDF, "pdf")],
    ids=["md", "docx", "pdf"],
)
def test_clean_mapping_roundtrip_on_fixtures(source: Path, label: str) -> None:
    result = read_document(source)
    clean = clean_reader_result(result)
    by_ordinal = {unit.ordinal: unit for unit in result.units}
    for region in clean.regions:
        if region.ordinal is None:
            continue  # 合成缺口区域：只留台账，无清洗投影
        unit = by_ordinal[region.ordinal]
        if region.status is UnitStatus.KEPT:
            assert region.clean_view is not None, (label, region.key)
            verify_clean_region(unit.raw_text, region.clean_view, region.mapping)


def test_pdf_fixture_synthetic_gap_regions_in_ledger() -> None:
    clean = clean_reader_result(read_document(PDF))
    synthetic = [region for region in clean.regions if region.ordinal is None]
    assert synthetic, "页面缺口必须进台账，不无记录消失"
    assert any(region.status is UnitStatus.NEEDS_OCR for region in synthetic)


# --- chunk：结构切块不变量与问答/表格分组 ---


@pytest.mark.parametrize(
    ("source", "label"),
    [(MD, "md"), (DOCX, "docx"), (PDF, "pdf")],
    ids=["md", "docx", "pdf"],
)
def test_chunk_invariants_on_fixtures(source: Path, label: str) -> None:
    result = read_document(source)
    clean = clean_reader_result(result)
    chunked = chunk_clean_result(result, clean)
    verify_chunk_result(clean, chunked)  # 覆盖/幻影引用/上限不变量，破坏即抛
    assert chunked.chunks
    kept_ordinals = {
        region.ordinal
        for region in clean.regions
        if region.ordinal is not None and region.status is UnitStatus.KEPT
    }
    for chunk in chunked.chunks:
        assert chunk.kind in CHUNK_KINDS, (label, chunk.kind)
        assert set(chunk.unit_ordinals) <= kept_ordinals, (label, chunk.key)
        assert set(chunk.context_refs) <= kept_ordinals, (label, chunk.key)


def test_md_fixture_question_answer_grouping() -> None:
    result = read_document(MD)
    clean = clean_reader_result(result)
    chunked = chunk_clean_result(result, clean)
    assert any(chunk.kind == "qa" for chunk in chunked.chunks)


# --- engine：合成夹具全链（接收→解析→清洗→切块→准入→发布）与幂等 ---


def test_engine_md_fixture_full_chain_and_idempotent_replay(tmp_path: Path) -> None:
    store = MemoryStore(clock=lambda: NOW)
    original = MD.read_bytes()
    store.put_reviewed_decision(_review(sha256_of_bytes(original)))

    first = _execute(store, MD, tmp_path).outcomes[0]
    assert first.admission.decision is AdmissionDecision.IN_SCOPE
    assert first.build is not None and first.unit_count > 0 and first.chunk_count > 0
    assert MD.read_bytes() == original  # 用户原文只读，不被改写

    second = _execute(store, MD, tmp_path).outcomes[0]
    assert second.build == first.build  # 同 build 幂等重放不重生产
    assert second.source_reused and second.archive_reused

    build_id = first.build.build_id
    publication = publish_build(store, build_id, activated_at=NOW)
    assert publication.generation == 1
    assert publish_build(store, build_id, activated_at=NOW) == publication  # 重试幂等
    lost_response = publish_build(store, build_id, activated_at=NOW + timedelta(seconds=1))
    # publish_idempotency_v2：同目标状态幂等不以时间为键（响应丢失+时钟前进恒幂等）。
    assert lost_response == publication and lost_response.generation == 1


def test_engine_pdf_fixture_quality_gaps_block_publication(tmp_path: Path) -> None:
    """N1 修正：有缺口的 PDF 夹具是「候选可留存、常规发布必须拒绝」的负例。

    材料准入 ≠ 处理完整：页面缺口（empty_page/image_only_page/image_region_unreadable）
    未消解前，架构 §8 第 2—3 条阻断常规发布，不因夹具标记豁免质量。
    """
    store = MemoryStore(clock=lambda: NOW)
    store.put_reviewed_decision(_review(sha256_of_bytes(PDF.read_bytes())))

    outcome = _execute(store, PDF, tmp_path).outcomes[0]
    assert outcome.admission.decision is AdmissionDecision.IN_SCOPE
    assert outcome.build is not None  # 候选可留存
    build_id = outcome.build.build_id

    quality = json.loads(outcome.build.quality_report or "{}")
    assert quality["gap_regions"], "夹具必须真实承载未消解缺口"
    with pytest.raises((EngineError, StoreError)):
        publish_build(store, build_id, activated_at=NOW)
    assert store.get_publication(outcome.source.source_id) is None


def test_engine_fixture_without_decision_is_not_published(tmp_path: Path) -> None:
    store = MemoryStore(clock=lambda: NOW)

    outcome = _execute(store, MD, tmp_path, decision_ids=()).outcomes[0]
    assert outcome.admission.decision is AdmissionDecision.REVIEW_REQUIRED
    assert outcome.build is None  # 未决不建 build，publish 无从发生
    with pytest.raises(EngineError):
        publish_build(store, "no-such-build", activated_at=NOW)
