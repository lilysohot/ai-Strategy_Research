"""D1 验收：表格抽取（pdfplumber）——「表格数字未入 L3」这个 P0 短板的修复。

要点：
1. 表格按行列重建，**保留「指标 | 数值」的同行对应**（pymupdf 会把它拆散，
   这正是此前表格数字检索不到的原因）；
2. 页码 locator **不变**，表格以 `[表格]` 段追加进该页 —— 取证仍按页；
3. ``pdfplumber`` 是**可选**能力：缺失或解析失败都不影响 ingest 主流程。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from plugins.corpus.ingest import _render_table, extract_pdf_tables, parse_pdf

CORPUS = Path("data/corpus")
SAMPLE_PDFS = sorted(CORPUS.glob("*.pdf"))[:5] if CORPUS.is_dir() else []

needs_corpus = pytest.mark.skipif(
    not SAMPLE_PDFS, reason="data/corpus 下没有 PDF 样本，跳过真实语料验证"
)


def test_render_table_keeps_row_and_cell_alignment() -> None:
    """同一行的指标与数值必须同行 —— 这是数字可检索的前提。"""
    table = [
        ["利润表（百万元）", "2024", "2025", "2026E"],
        ["营业收入", "174144", "172054", "173340"],
        ["营业成本", "13789", "14892", "16601"],
    ]

    rendered = _render_table(table)

    assert "营业收入 | 174144 | 172054 | 173340" in rendered
    assert "营业成本 | 13789 | 14892 | 16601" in rendered


def test_render_table_skips_blank_rows() -> None:
    rendered = _render_table([["指标", "值"], [None, ""], ["营收", "100"]])
    assert rendered.splitlines() == ["指标 | 值", "营收 | 100"]


def test_extract_pdf_tables_tolerates_missing_file() -> None:
    """文件不存在/损坏 ⇒ 返回空，**绝不抛**（表格是增强，不是地基）。"""
    assert extract_pdf_tables("data/corpus/__definitely_missing__.pdf") == {}


@needs_corpus
def test_tables_are_extracted_from_real_reports() -> None:
    """真实研报里能抽出表格，且含数字（不是空壳）。"""
    for path in SAMPLE_PDFS:
        tables = extract_pdf_tables(path)
        if not tables:
            continue
        joined = "\n".join(text for rows in tables.values() for text in rows)
        assert any(char.isdigit() for char in joined), f"{path.name} 抽到表格但没有数字"
        return
    pytest.skip("前 5 份样本中未发现表格（换样本或扩大取样）")


@needs_corpus
def test_parse_pdf_appends_table_section_to_the_page() -> None:
    """表格进入该页块文本 ⇒ 落库后进 L3，可被检索。"""
    for path in SAMPLE_PDFS:
        if not extract_pdf_tables(path):
            continue
        blocks = parse_pdf(path, with_tables=True)
        assert any("[表格]" in block.text for block in blocks)
        # locator 仍必须是页码（取证句柄语义不变）
        assert all(block.locator.isdigit() for block in blocks)
        return
    pytest.skip("前 5 份样本中未发现表格")


@needs_corpus
def test_tables_can_be_disabled() -> None:
    """可按 `--no-tables` 思路关闭（pdfplumber 比 pymupdf 慢很多，全量时可权衡）。"""
    for path in SAMPLE_PDFS:
        if not extract_pdf_tables(path):
            continue
        blocks = parse_pdf(path, with_tables=False)
        assert not any("[表格]" in block.text for block in blocks)
        return
    pytest.skip("前 5 份样本中未发现表格")
