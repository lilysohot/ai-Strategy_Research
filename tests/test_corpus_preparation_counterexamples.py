"""N4 反例回归（i1-9 复审 §4-N4：夹具避开的困难结构，独立小反例补覆盖）。

三件套反例，冻结期望为「正确读取或明确复核」，不强求全部自动准入，不通过改
样本使特征冲突消失：

1. 有线 PDF 表格：必须产出 ``table_row`` 单元（正确读取）或显式缺口记账
   （``table_lines_without_extraction``/``table_extraction_failed``），二者必居
   其一——有线表格既无行单元又无缺口记账即为静默丢失。
2. 正文引用访谈/带「实录」标题：机器检出 minutes 类材料与人工 admitted 凭证
   冲突 → ``policy_conflict`` → ``review_required``，不自动准入、不产生 build。
3. 条件句跨行换行：前件/后件分行不得丢失任何一侧——单元 raw_text 逐字符保真，
   检索投影覆盖全部非空白字符。

全部为合成输入，零模型、零网络、无 PG。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pymupdf
import pytest

from plugins.corpus.preparation.admission import POLICY_REV_V1, AdmissionPolicy
from plugins.corpus.preparation.contract import (
    AdmissionDecision,
    AdmissionReasonCode,
    LeaseConfig,
    MaterialType,
    ResearchDomain,
    ReviewDecision,
    ReviewedDecision,
    UnitStatus,
    source_id_from_bytes,
)
from plugins.corpus.preparation.engine import (
    PlanEntry,
    execute_builds,
    plan_builds,
    publish_build,
)
from plugins.corpus.preparation.readers import read_document
from plugins.corpus.preparation.repository import MemoryStore

NOW = datetime(2026, 9, 16, 12, tzinfo=UTC)
POLICY = AdmissionPolicy(POLICY_REV_V1, tuple(ResearchDomain))
LEASE = LeaseConfig(300, 60, 600, 3)

_TABLE_GAP_CODES = frozenset({"table_lines_without_extraction", "table_extraction_failed"})


def _execute(tmp_path: Path, path: Path, *, name: str = "synthetic-company-report"):
    store = MemoryStore(clock=lambda: NOW)
    sid = source_id_from_bytes(path.read_bytes())
    store.put_reviewed_decision(
        ReviewedDecision("r1", sid, "reviewer", NOW, ReviewDecision.ADMITTED, "synthetic approval")
    )
    plan = plan_builds(
        [
            PlanEntry(
                str(path),
                original_name=f"{name}.md",
                domain_hint=ResearchDomain.COMPANY,
                review_decision_ids=("r1",),
            )
        ],
        policy=POLICY,
    )
    outcome = execute_builds(
        store,
        plan,
        policy=POLICY,
        archive_root=tmp_path / "archive",
        owner_id="n4",
        now=NOW,
        lease=LEASE,
    ).outcomes[0]
    return store, outcome


# --- 反例 1：有线 PDF 表格（正确读取或显式缺口，不静默丢失） ---


def _write_wired_table_pdf(path: Path) -> None:
    """合成 2×2 有线表格 PDF：网格线 + 单元格文字（内置 CJK 字体保证可提取）。"""
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "证券公司研究", fontsize=11, fontname="china-s")
    x0, y0, x1, y1 = 72, 100, 400, 180
    rows = [y0, (y0 + y1) // 2, y1]
    cols = [x0, (x0 + x1) // 2, x1]
    for y in rows:
        page.draw_line((x0, y), (x1, y))
    for x in cols:
        page.draw_line((x, y0), (x, y1))
    cells = {(0, 0): "指标", (0, 1): "数值", (1, 0): "营收", (1, 1): "100亿元"}
    for (r, c), text in cells.items():
        page.insert_text((cols[c] + 4, rows[r] + 14), text, fontsize=10, fontname="china-s")
    doc.save(str(path))
    doc.close()


def test_wired_pdf_table_rows_preserved_or_gap_recorded(tmp_path: Path) -> None:
    path = tmp_path / "wired-table.pdf"
    _write_wired_table_pdf(path)
    parsed = read_document(path)
    table_rows = [u for u in parsed.units if u.kind == "table_row"]
    if not table_rows:
        # 未提取出表行：必须有显式缺口记账（明确复核），不得静默丢失。
        found = _TABLE_GAP_CODES & {i.code for i in parsed.issues}
        assert found, f"有线表格既无 table_row 又无缺口记账（静默丢失）: {parsed.issues}"
        pytest.skip(f"表行未提取但缺口已记账: {sorted(found)}")  # 复核分支，本轮走读取分支
    joined = "".join(u.raw_text for u in table_rows)
    assert "指标" in joined and "数值" in joined
    assert "营收" in joined and "100亿元" in joined  # 单元格文字零丢失
    for unit in table_rows:
        assert unit.status is UnitStatus.KEPT

    # 全链：表行进入检索投影且发布成功（读取分支的端到端闭合）。
    store = MemoryStore(clock=lambda: NOW)
    sid = source_id_from_bytes(path.read_bytes())
    store.put_reviewed_decision(
        ReviewedDecision("r1", sid, "reviewer", NOW, ReviewDecision.ADMITTED, "approval")
    )
    plan = plan_builds(
        [PlanEntry(str(path), domain_hint=ResearchDomain.COMPANY, review_decision_ids=("r1",))],
        policy=POLICY,
    )
    outcome = execute_builds(
        store,
        plan,
        policy=POLICY,
        archive_root=tmp_path / "archive",
        owner_id="n4",
        now=NOW,
        lease=LEASE,
    ).outcomes[0]
    assert outcome.build is not None
    search = "\n".join(chunk.search_text for chunk in store.get_chunks(outcome.build.build_id))
    assert "营收" in search and "100亿元" in search
    publication = publish_build(store, outcome.build.build_id, activated_at=NOW)
    assert publication.active_build_id == outcome.build.build_id


# --- 反例 2：「实录」标题 → policy_conflict → review_required，不自动准入 ---


def test_transcript_titled_document_conflicts_to_review_required(tmp_path: Path) -> None:
    path = tmp_path / "transcript.md"
    path.write_text(
        "# 访谈实录：某公司经营情况交流\n\n管理层介绍了经营情况。\n\n与会方提问。\n",
        encoding="utf-8",
    )
    _store, outcome = _execute(tmp_path, path, name="interview-notes")
    assert outcome.admission.decision is AdmissionDecision.REVIEW_REQUIRED
    assert AdmissionReasonCode.POLICY_CONFLICT in outcome.admission.reason_codes
    assert outcome.admission.material_type is MaterialType.INTERNAL_UNATTRIBUTED
    assert outcome.build is None  # 复核未决：不产生 build、无可发布物


# --- 反例 3：条件句跨行换行（前件/后件分行，全字符保真） ---


def test_condition_sentence_wrapped_across_lines_keeps_all_chars(tmp_path: Path) -> None:
    text = "# 证券公司研究\n\n若需求下滑，\n则盈利承压。\n"
    path = tmp_path / "wrapped.md"
    path.write_text(text, encoding="utf-8")
    store, outcome = _execute(tmp_path, path)
    assert outcome.build is not None
    units = store.get_units(outcome.build.build_id)
    # 单元 raw_text 权威逐字符保真（换行不丢前件/后件）。
    raw_all = "\n".join(u.raw_text for u in units)
    assert "若需求下滑，" in raw_all
    assert "则盈利承压。" in raw_all
    # 检索投影覆盖全部非空白字符（含两侧行）。
    search = "\n".join(chunk.search_text for chunk in store.get_chunks(outcome.build.build_id))
    for char in "若需求下滑，则盈利承压。":
        if char.isspace():
            continue
        assert char in search, f"换行条件句丢失字符 {char!r}"
    publication = publish_build(store, outcome.build.build_id, activated_at=NOW)
    assert publication.active_build_id == outcome.build.build_id
    quality = json.loads(outcome.build.quality_report)
    assert quality == {"gap_regions": [], "oversized_chunks": []}


# --- 反例 4：图表页坐标轴/刻度线不得误报“有线无表”缺口（E6 M1/M7 回归） ---
#
# 折线图/柱状图的坐标轴、刻度线与曲线碎片也是矢量线段，若仅按“横竖线段
# 数量 ≥3”计数，图表页会被误判成 `table_lines_without_extraction` 而阻断
# 整篇发布。真实表格的格线相互交叉成网；图表轴与刻度线多为单轴排列、
# 交点稀少。本反例合成一张“文字 + 带坐标轴和大量刻度线的图表”页，断言：
#   - 不产生 `table_lines_without_extraction` 缺口；
#   - 正文行仍被提取；
#   - 发布门放行（无 blocking gap）。


def _write_chart_page_pdf(path: Path) -> None:
    """合成图表页：横/纵坐标轴 + 大量短刻度线，无真实表格。"""
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "证券公司研究", fontsize=11, fontname="china-s")
    page.insert_text((72, 100), "行业景气度持续修复", fontsize=10.5, fontname="china-s")
    # 坐标轴：一条长横轴、一条长纵轴
    page.draw_line((72, 600), (520, 600), color=(0, 0, 0), width=1)
    page.draw_line((72, 200), (72, 600), color=(0, 0, 0), width=1)
    # 刻度线：沿横轴密布短竖线、沿纵轴密布短横线（<40pt，模拟图表刻度）
    for i in range(30):
        x = 72 + i * 15
        page.draw_line((x, 595), (x, 605), color=(0, 0, 0), width=0.5)
    for i in range(20):
        y = 200 + i * 20
        page.draw_line((67, y), (77, y), color=(0, 0, 0), width=0.5)
    # 一条曲线（多段短线近似）
    import math

    prev = (72, 580)
    for i in range(1, 30):
        x = 72 + i * 15
        y = 580 - 120 * math.sin(i / 3.0)
        page.draw_line(prev, (x, y), color=(0.2, 0.4, 0.8), width=1)
        prev = (x, y)
    doc.save(str(path))
    doc.close()


def test_chart_page_lines_do_not_trigger_table_gap(tmp_path: Path) -> None:
    path = tmp_path / "chart-page.pdf"
    _write_chart_page_pdf(path)
    parsed = read_document(path)
    codes = [issue.code for issue in parsed.issues]
    assert "table_lines_without_extraction" not in codes, codes
    assert "table_extraction_failed" not in codes, codes
    text = "\n".join(u.raw_text for u in parsed.units)
    assert "行业景气度持续修复" in text  # 正文行仍被提取
    # 全链：无 blocking 缺口 → 发布门放行。
    store = MemoryStore(clock=lambda: NOW)
    sid = source_id_from_bytes(path.read_bytes())
    store.put_reviewed_decision(
        ReviewedDecision("r1", sid, "reviewer", NOW, ReviewDecision.ADMITTED, "approval")
    )
    plan = plan_builds(
        [PlanEntry(str(path), domain_hint=ResearchDomain.COMPANY, review_decision_ids=("r1",))],
        policy=POLICY,
    )
    outcome = execute_builds(
        store,
        plan,
        policy=POLICY,
        archive_root=tmp_path / "archive",
        owner_id="n4",
        now=NOW,
        lease=LEASE,
    ).outcomes[0]
    assert outcome.build is not None
    quality = json.loads(outcome.build.quality_report)
    assert quality == {"gap_regions": [], "oversized_chunks": []}
    publication = publish_build(store, outcome.build.build_id, activated_at=NOW)
    assert publication.active_build_id == outcome.build.build_id
