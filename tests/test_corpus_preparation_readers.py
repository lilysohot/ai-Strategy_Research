"""I1-2 读取 Adapter 测试：空页/多栏/表格/重复标题/短 MD 反例 + 开发材料 smoke。

验收（任务 I1-2）：fidelity 空页/多栏/表格/重复标题/短 MD 反例通过，不靠装库
声称支持（格式签名 fail-closed、表格冲突显式记账、短 MD 正常处理、重复标题
单元唯一）。不构造真实 PG/模型客户端。
"""

from __future__ import annotations

import io
import json
import re
import subprocess
import sys
from pathlib import Path

import pymupdf
import pytest
from docx import Document

from plugins.corpus.preparation.contract import UnitStatus
from plugins.corpus.preparation.readers import ReaderError, read_document
from plugins.corpus.preparation.readers.pdf_reader import (
    _detect_header_rows,
    _emit_table,
    _garbled_ratio,
    _is_data_like,
    _Line,
    _merge_lines,
    _overlapping_row_indices,
    _row_text,
    _Table,
    _TableCell,
    _TableModel,
    _TableRow,
)

REPO = Path(__file__).resolve().parents[1]

_WS = re.compile(r"[\s\u3000\xa0\u200b]+")


# --- Markdown ---


def test_md_short_file_single_paragraph(tmp_path: Path) -> None:
    path = tmp_path / "short.md"
    path.write_text("# 标题\n\n正文一句话。", encoding="utf-8")
    result = read_document(path)
    assert result.format.value == "markdown"
    assert result.page_count is None
    assert [u.kind for u in result.units] == ["heading", "paragraph"]
    assert result.units[1].raw_text == "正文一句话。"
    span = result.units[1].location.char_span
    assert span is not None
    text = path.read_text(encoding="utf-8")
    assert text[span.start : span.end] == "正文一句话。"
    assert result.issues == ()


def test_md_repeated_headings_distinct_units(tmp_path: Path) -> None:
    path = tmp_path / "repeat.md"
    path.write_text("# 风险提示\n\n甲段\n\n# 风险提示\n\n乙段\n", encoding="utf-8")
    result = read_document(path)
    headings = [u for u in result.units if u.kind == "heading"]
    assert len(headings) == 2
    assert headings[0].ordinal != headings[1].ordinal
    assert all(u.status is UnitStatus.KEPT for u in result.units)
    assert not any("ocr" in issue.code for issue in result.issues)


def test_md_structural_kinds_and_offset_fidelity(tmp_path: Path) -> None:
    content = (
        "# 报告\n\n- 第一条\n- 第二条\n\n> 引用内容\n\n"
        "| 列A | 列B |\n|---|---|\n| 1 | 2 |\n\n结尾段落\n"
    )
    path = tmp_path / "structure.md"
    path.write_text(content, encoding="utf-8")
    result = read_document(path)
    kinds = [u.kind for u in result.units]
    assert kinds.count("heading") == 1
    assert kinds.count("list_item") == 2
    assert kinds.count("quote") == 1
    assert kinds.count("table_row") == 3
    assert kinds[-1] == "paragraph"
    text = path.read_text(encoding="utf-8")
    for unit in result.units:
        span = unit.location.char_span
        assert span is not None
        assert text[span.start : span.end] == unit.raw_text, unit.raw_text


def test_md_code_fence_kept_with_reason(tmp_path: Path) -> None:
    path = tmp_path / "code.md"
    path.write_text("```\nkeep line\n```\n", encoding="utf-8")
    result = read_document(path)
    assert result.units[0].raw_text == "```\nkeep line\n```"
    assert result.units[0].reasons == ("code_fence",)


# --- 格式识别 fail-closed（不靠装库声称支持） ---


def test_format_signature_fail_closed(tmp_path: Path) -> None:
    fake_pdf = tmp_path / "fake.pdf"
    fake_pdf.write_text("not a pdf", encoding="utf-8")
    with pytest.raises(ReaderError):
        read_document(fake_pdf)
    fake_docx = tmp_path / "fake.docx"
    fake_docx.write_bytes(b"MZ not a zip container")
    with pytest.raises(ReaderError):
        read_document(fake_docx)
    unsupported = tmp_path / "note.txt"
    unsupported.write_text("x", encoding="utf-8")
    with pytest.raises(ReaderError):
        read_document(unsupported)


# --- DOCX ---


def _png_bytes() -> bytes:
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 4, 4))
    return pixmap.tobytes("png")


def test_docx_repeated_headings_body_order_and_table(tmp_path: Path) -> None:
    document = Document()
    document.add_heading("风险提示", level=1)
    document.add_paragraph("正文甲")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "指标"
    table.cell(0, 1).text = "数值"
    table.cell(1, 0).text = "营收"
    table.cell(1, 1).text = "100"
    document.add_paragraph("表格后段落")
    document.add_heading("风险提示", level=1)
    document.add_paragraph("正文乙")
    path = tmp_path / "synthetic.docx"
    document.save(str(path))

    result = read_document(path)
    kinds = [(u.kind, u.raw_text) for u in result.units]
    assert kinds[0] == ("heading", "风险提示")
    assert kinds[1] == ("paragraph", "正文甲")
    rows = [u for u in result.units if u.kind == "table_row"]
    assert [r.raw_text for r in rows] == ["指标 | 数值", "营收 | 100"]
    assert rows[0].location.cells == ((0, 0), (0, 1))
    # 表格之后的正文顺序保持（不假设 document.paragraphs 覆盖全文）。
    assert kinds[-3:] == [
        ("paragraph", "表格后段落"),
        ("heading", "风险提示"),
        ("paragraph", "正文乙"),
    ]
    headings = [u for u in result.units if u.kind == "heading"]
    assert headings[0].ordinal != headings[1].ordinal


def test_docx_image_records_gap_issue(tmp_path: Path) -> None:
    document = Document()
    document.add_paragraph("图片前段落")
    document.add_picture(io.BytesIO(_png_bytes()))
    document.add_paragraph("图片后段落")
    path = tmp_path / "with-image.docx"
    document.save(str(path))

    result = read_document(path)
    assert "unreadable_element" in [issue.code for issue in result.issues]
    texts = [u.raw_text for u in result.units]
    assert "图片前段落" in texts and "图片后段落" in texts


# --- PDF ---


def test_pdf_paragraphs_headings_bbox(tmp_path: Path) -> None:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 100), "Overview", fontsize=16)
    page.insert_text((72, 140), "First body line", fontsize=11)
    page.insert_text((72, 155), "Second body line", fontsize=11)
    page.insert_text((72, 220), "Separate paragraph", fontsize=11)
    path = tmp_path / "text.pdf"
    doc.save(str(path))
    doc.close()

    result = read_document(path)
    assert result.page_count == 1
    headings = [u for u in result.units if u.kind == "heading"]
    assert [h.raw_text for h in headings] == ["Overview"]
    assert headings[0].location.page == 1
    assert headings[0].location.bbox is not None
    paragraphs = [u for u in result.units if u.kind == "paragraph"]
    assert len(paragraphs) == 2
    assert paragraphs[0].raw_text == "First body line\nSecond body line"
    assert paragraphs[1].raw_text == "Separate paragraph"


def test_pdf_uniform_multiline_block_is_not_split_into_headings(tmp_path: Path) -> None:
    """小字号元数据不能把同一正文块的每一行误判为标题。"""
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Overview", fontsize=16)
    body = "First body line\nSecond body line\nThird body line"
    page.insert_textbox(pymupdf.Rect(72, 110, 360, 180), body, fontsize=11)
    # 大量小字号行模拟表格／页脚，将页内中位字号压低到正文以下。
    for index in range(8):
        page.insert_text((400, 100 + index * 12), f"meta {index}", fontsize=6)
    path = tmp_path / "uniform_body_block.pdf"
    doc.save(str(path))
    doc.close()

    result = read_document(path)

    assert [unit.raw_text for unit in result.units if unit.kind == "heading"] == ["Overview"]
    assert body in [unit.raw_text for unit in result.units if unit.kind == "paragraph"]


def test_pdf_multiline_text_blocks_do_not_merge_across_block_boundary() -> None:
    """原生多行块是段落边界，几何相邻也不能合并。"""
    lines = [
        _Line("first-1", (0.0, 0.0, 100.0, 10.0), 11.0, 1, 2, 11.0, 11.0),
        _Line("first-2", (0.0, 11.0, 100.0, 21.0), 11.0, 1, 2, 11.0, 11.0),
        _Line("second-1", (0.0, 22.0, 100.0, 32.0), 11.0, 2, 2, 11.0, 11.0),
        _Line("second-2", (0.0, 33.0, 100.0, 43.0), 11.0, 2, 2, 11.0, 11.0),
    ]

    paragraphs = _merge_lines(lines)

    assert [[line.text for line in paragraph] for paragraph in paragraphs] == [
        ["first-1", "first-2"],
        ["second-1", "second-2"],
    ]


def test_pdf_empty_and_image_only_pages(tmp_path: Path) -> None:
    doc = pymupdf.open()
    doc.new_page()  # 第 1 页：无文字层无图片
    doc.new_page().insert_text((72, 72), "hello", fontsize=11)
    image_page = doc.new_page()
    image_page.insert_image(
        pymupdf.Rect(100, 100, 200, 200),
        pixmap=pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 10, 10)),
    )
    path = tmp_path / "pages.pdf"
    doc.save(str(path))
    doc.close()

    result = read_document(path)
    assert result.page_count == 3
    codes = [issue.code for issue in result.issues]
    assert codes.count("empty_page") == 1
    assert codes.count("image_only_page") == 1
    assert result.units and all(u.location.page == 2 for u in result.units)


def test_pdf_multicolumn_flagged_and_covered(tmp_path: Path) -> None:
    doc = pymupdf.open()
    page = doc.new_page()
    for index, y in enumerate((80, 100, 120, 140)):
        page.insert_text((60, y), f"LEFT{index} alpha beta", fontsize=11)
        page.insert_text((360, y), f"RIGHT{index} gamma delta", fontsize=11)
    path = tmp_path / "columns.pdf"
    doc.save(str(path))
    doc.close()

    result = read_document(path)
    assert "multi_column_order_unreliable" in [issue.code for issue in result.issues]
    order = [u.raw_text for u in result.units]
    joined = "\n".join(order)
    assert "LEFT0" in joined and "RIGHT3" in joined
    left_first = next(i for i, text in enumerate(order) if "LEFT0" in text)
    right_first = next(i for i, text in enumerate(order) if "RIGHT0" in text)
    assert left_first < right_first  # 阅读次序：先左栏后右栏


def test_pdf_true_two_column_native_order_kept(tmp_path: Path) -> None:
    """真双栏且内容流按整栏写入：原生序本身即「先左栏后右栏」，不需要强制重排。

    这是关闭 `_split_columns` 强制左→右重排后的正对照：证明移除重排不会让真正的
    双栏文档串行（I3-3 关闭重排的唯一语义风险）。
    """
    doc = pymupdf.open()
    page = doc.new_page()
    ys = (80, 100, 120, 140)
    for index, y in enumerate(ys):  # 整栏写：先写满左栏，再写满右栏
        page.insert_text((60, y), f"LEFT{index} alpha beta", fontsize=11)
    for index, y in enumerate(ys):
        page.insert_text((360, y), f"RIGHT{index} gamma delta", fontsize=11)
    path = tmp_path / "columns_native.pdf"
    doc.save(str(path))
    doc.close()

    result = read_document(path)
    assert "multi_column_order_unreliable" in [issue.code for issue in result.issues]
    order = [u.raw_text for u in result.units]
    left_idx = [i for i, text in enumerate(order) if "LEFT" in text]
    right_idx = [i for i, text in enumerate(order) if "RIGHT" in text]
    assert left_idx and right_idx
    assert max(left_idx) < min(right_idx)  # 原生序已是先左栏后右栏


def test_pdf_table_rows_no_silent_duplication(tmp_path: Path) -> None:
    doc = pymupdf.open()
    page = doc.new_page()
    xs = [50, 150, 250, 350]
    ys = [300, 330, 360, 390]
    for x in xs:
        page.draw_line((x, ys[0]), (x, ys[-1]))
    for y in ys:
        page.draw_line((xs[0], y), (xs[-1], y))
    for column, header in enumerate(["Yr", "Rev", "NP"]):
        page.insert_text(((xs[column] + xs[column + 1]) / 2 - 6, ys[0] + 20), header, fontsize=9)
    for row_index, row in enumerate([["2024", "9901", "11"], ["2025", "9902", "12"]]):
        for column, value in enumerate(row):
            page.insert_text(
                ((xs[column] + xs[column + 1]) / 2 - 6, ys[row_index + 1] + 20), value, fontsize=9
            )
    path = tmp_path / "table.pdf"
    doc.save(str(path))
    doc.close()

    result = read_document(path)
    rows = [u for u in result.units if u.kind == "table_row"]
    assert len(rows) >= 3
    table_text = "\n".join(u.raw_text for u in rows)
    assert "2024" in table_text and "9901" in table_text and "9902" in table_text
    assert "|" not in table_text  # I1：不得插入原文没有的字符（旧实现插入 " | "）
    prose = [u for u in result.units if u.kind != "table_row"]
    assert not any("9901" in u.raw_text or "9902" in u.raw_text for u in prose)
    assert "table_text_overlap" in [issue.code for issue in result.issues]


def test_table_row_text_invariants_native_order_and_source_characters() -> None:
    """表格行发射的两条不变量（I3-3 表格类引文失败的共因）。

    I1（字符保真）：单元格之间只用换行，不插入原文没有的字符。
    I2（顺序保真）：文本顺序服从原生阅读序；网格行列只作为 locator 元数据下发，
    不参与文本重排。
    """
    row = _TableRow(
        cells=(
            _TableCell(text="产品", row=0, col=1, native_pos=2),
            _TableCell(text="产能（万吨/年）", row=0, col=9, native_pos=1),  # 内容流里先画
            _TableCell(text="价格分位", row=0, col=6, native_pos=3),
        )
    )
    text, cells = _row_text(row)
    assert text == "产能（万吨/年）\n产品\n价格分位"  # 原生序，而非网格列序
    assert "|" not in text
    assert cells == ((0, 9), (0, 1), (0, 6))  # 行列仍在，只是降级为元数据


def test_garbled_ratio_helper() -> None:
    assert _garbled_ratio("") == 0.0
    assert _garbled_ratio("正常文本") == 0.0
    assert _garbled_ratio("abc\ufffd\ufffd") == pytest.approx(0.4)


# --- 表格结构模型（票 04：确定性表头识别 + 合并单元格 + label_path） ---


def test_is_data_like_discriminates_values_from_period_years() -> None:
    assert _is_data_like("5814.2")
    assert _is_data_like("32.1")
    assert _is_data_like("89.9%")
    assert _is_data_like("-1,234.5")
    assert not _is_data_like("尿素")
    assert not _is_data_like("2023 2024 2025")  # 裸 4 位年份是期间标签，非数据值


def test_detect_header_rows_stops_at_data_rows_and_skips_sparse() -> None:
    # 数据形态占比 ≥50% 即停；稀疏行（整行合并标题）跳过不计数
    grid = [
        ["开工率", "价差", "产能", "价格分位"],
        ["尿素", "5814.2", "32.1", "89.9%"],
        ["纯碱", "6728.3", "10.9", "82.9%"],
    ]
    assert _detect_header_rows(grid) == (0,)
    sparse = [
        ["表 6 主要化工品景气跟踪"],  # 稀疏行：非空 <2，跳过
        ["产品", "开工率", "产能"],
        ["尿素", "32.1", "100"],
    ]
    assert _detect_header_rows(sparse) == (1,)
    # 表头期间行（裸 4 位年份）豁免为表头而非数据行
    with_years = [
        ["产品", "2023", "2024", "2025"],
        ["尿素", "5814.2", "32.1", "89.9%"],
    ]
    assert _detect_header_rows(with_years) == (0,)


def test_table_model_label_path_merged_headers() -> None:
    """I-B1 读侧投影：多级表头 + 合并单元格按 bbox 覆盖继承列标签。

    ``开工率`` 跨列 2-3 合并（覆盖位 None）；``col_labels`` 自下而上遍历表头行，
    数据行锚定单元格的列中心落入合并 bbox 即继承标签。
    """
    model = _TableModel(
        page=10,
        table_index=0,
        header_rows=(0, 1),
        grid=(
            (None, "产品", "开工率", None),  # 合并单元格：开工率 横跨列 2-3
            ("周期", "尿素", "纯碱", "纯碱"),
            (None, "尿素", "5814.2", "8068.0"),  # 数据行
        ),
        anchored=(
            ((1, (100.0, 200.0)), (2, (200.0, 400.0))),  # 合并 bbox 覆盖列 2-3
            ((0, (50.0, 100.0)), (1, (100.0, 200.0)), (2, (200.0, 300.0)), (3, (300.0, 400.0))),
            ((1, (100.0, 200.0)), (2, (200.0, 300.0)), (3, (300.0, 400.0))),
        ),
    )
    # 数据行 cell(2, 3)：行标签 尿素 + 列标签链（纯碱 ← 开工率）
    assert model.label_path(2, 3) == ("尿素", "纯碱", "开工率")
    # cell(2, 2) 同属纯碱 列，且开工率 合并 bbox 覆盖列 2-3 → 同样继承完整链
    assert model.label_path(2, 2) == ("尿素", "纯碱", "开工率")
    # 表头行无行标签
    assert model.label_path(1, 2) == ("纯碱", "开工率")
    # 覆盖位空单元格不猜测内容
    assert model.cell_text(0, 3) == ""


def test_table_model_rejects_multiline_column_dump_as_labels() -> None:
    """表格解析器把整列折进一格时，该数据列不得污染每个单元的 label_path。"""
    model = _TableModel(
        page=8,
        table_index=0,
        header_rows=(0,),
        grid=(
            (
                "公司名称\n甲公司\n乙公司\n丙公司",
                "周度涨跌幅\n1.0%\n2.0%\n3.0%",
            ),
            ("甲公司\n乙公司\n丙公司", "1.0%\n2.0%\n3.0%"),
        ),
        anchored=(
            ((0, (50.0, 150.0)), (1, (150.0, 250.0))),
            ((0, (50.0, 150.0)), (1, (150.0, 250.0))),
        ),
    )

    assert model.label_path(1, 1) == ()


def test_emit_table_model_label_path_aligned_and_row_text_untouched() -> None:
    """保真反例：带 model 的表格发射不触碰原文。

    ``raw_text`` 与 ``_row_text`` 逐字节一致（仍按 native_pos 排序、只用换行连接，
    不插入 ``" | "``）；``label_path`` 与 ``cells`` 一一对齐（I-B1 读侧落点）。
    """
    model = _TableModel(
        page=10,
        table_index=0,
        header_rows=(0,),
        grid=(
            ("产品", "开工率", "产能"),
            ("尿素", "89.9%", "100"),
        ),
        anchored=(
            ((0, (50.0, 100.0)), (1, (100.0, 200.0)), (2, (200.0, 300.0))),
            ((0, (50.0, 100.0)), (1, (100.0, 200.0)), (2, (200.0, 300.0))),
        ),
    )
    row = _TableRow(
        cells=(
            _TableCell(text="产能", row=1, col=2, native_pos=0),
            _TableCell(text="尿素", row=1, col=0, native_pos=1),
            _TableCell(text="89.9%", row=1, col=1, native_pos=2),
        )
    )
    table = _Table(index=0, bbox=(50.0, 300.0, 300.0, 330.0), rows=[row], model=model)
    units: list[object] = []
    issues: list[object] = []
    _emit_table(table, 0, page_no=10, page_lines=[], units=units, issues=issues)
    assert len(units) == 1
    unit = units[0]  # type: ignore[attr-defined]
    text, cells = _row_text(row)
    assert unit.raw_text == text == "产能\n尿素\n89.9%"  # 原生序 + 纯换行，不插 " | "
    assert unit.location.cells == cells == ((1, 2), (1, 0), (1, 1))
    assert len(unit.location.label_path) == len(cells)
    # label_path 与 cells 顺序对齐（原生序）：产能→(尿素, 产能)、尿素→(尿素, 产品)、89.9%→(尿素, 开工率)
    assert unit.location.label_path == ("尿素 产能", "尿素 产品", "尿素 开工率")
    assert "|" not in unit.raw_text


# --- reader-pdf-8（R8：双栏无线预测表 cells 丢失 + 跨栏续表行序断裂） ---


def _r8_two_column_wireless_pdf(path: Path) -> None:
    """构造双栏并排、无制表线的预测表页：左表 甲~己 ×3 列、右表 甲~己 ×3 列。

    左右两表水平并排（x 空隙 > 页宽 25%），行 y 并排；不画任何制表线，
    复现华创茅台 6f14cc14 page3「附录：财务预测表」的无线双栏形态。
    """
    doc = pymupdf.open()
    page = doc.new_page()
    left_values = (
        ("甲", "311", "312", "313"),
        ("乙", "321", "322", "323"),
        ("丙", "331", "332", "333"),
        ("丁", "341", "342", "343"),
        ("戊", "351", "352", "353"),
        ("己", "361", "362", "363"),
    )
    right_values = (
        ("甲", "911", "912", "913"),
        ("乙", "921", "922", "923"),
        ("丙", "931", "932", "933"),
        ("丁", "941", "942", "943"),
        ("戊", "951", "952", "953"),
        ("己", "961", "962", "963"),
    )
    for row_index, row in enumerate(left_values):
        for col, value in enumerate(row):
            page.insert_text((60 + col * 45, 300 + row_index * 18), value, fontsize=9)
    for row_index, row in enumerate(right_values):
        for col, value in enumerate(row):
            page.insert_text((330 + col * 45, 300 + row_index * 18), value, fontsize=9)
    doc.save(str(path))
    doc.close()


def test_r8_side_by_side_wireless_tables_keep_cells_per_column(tmp_path: Path) -> None:
    """S1-S3 双栏并排无线预测表：两表各自 cells 非空且坐标互不串栏。

    修复前：find_tables(lines) 全页 0 表，数字行全部退化为 paragraph 单元
    （location.cells 为空）。修复后：无线表格 fallback 按 x 区间切分左右两栏
    各自成表，表格行单元携带 (row, col)，且左表行不含右栏值（反之亦然）。
    """
    path = tmp_path / "r8_wireless.pdf"
    _r8_two_column_wireless_pdf(path)

    result = read_document(path)
    rows = [u for u in result.units if u.kind == "table_row"]
    assert rows, "双栏无线表必须产出 table_row 单元（而非扁平数字段落）"
    assert all(u.location.cells for u in rows), "每个表格行单元的 cells 必须非空"

    def _tokens(unit: object) -> list[str]:
        return [tok for tok in str(unit.raw_text).split() if tok[0].isdigit()]  # type: ignore[attr-defined]

    # 左表行（值 3xx）与右表行（值 9xx）互不串栏；列号各自独立成表且 ≤3。
    left_rows = [u for u in rows if any(tok.startswith("3") for tok in _tokens(u))]
    right_rows = [u for u in rows if any(tok.startswith("9") for tok in _tokens(u))]
    assert left_rows and right_rows
    for unit in left_rows:
        assert all(tok.startswith("3") for tok in _tokens(unit)), unit.raw_text
        assert max(col for _, col in unit.location.cells) <= 3
    for unit in right_rows:
        assert all(tok.startswith("9") for tok in _tokens(unit)), unit.raw_text
        assert max(col for _, col in unit.location.cells) <= 3


def test_r8_single_column_ruled_table_cells_regression(tmp_path: Path) -> None:
    """S0 对照（dddc7cd0 形态）：单栏有线表格 cells 逐行非空、(row, col) 连续。

    既有用例 test_pdf_table_rows_no_silent_duplication 只断言文本与记账；
    本用例补齐 cells 坐标断言，守住无线 fallback 引入后单栏有线表不回归。
    """
    doc = pymupdf.open()
    page = doc.new_page()
    xs = [50, 150, 250, 350]
    ys = [300, 330, 360, 390]
    for x in xs:
        page.draw_line((x, ys[0]), (x, ys[-1]))
    for y in ys:
        page.draw_line((xs[0], y), (xs[-1], y))
    grid = [["Yr", "Rev", "NP"], ["2024", "9901", "11"], ["2025", "9902", "12"]]
    for row_index, row in enumerate(grid):
        for col, value in enumerate(row):
            page.insert_text(
                ((xs[col] + xs[col + 1]) / 2 - 6, ys[row_index] + 20), value, fontsize=9
            )
    path = tmp_path / "r8_ruled.pdf"
    doc.save(str(path))
    doc.close()

    result = read_document(path)
    rows = [u for u in result.units if u.kind == "table_row"]
    assert len(rows) >= 3
    for index, unit in enumerate(rows):
        cells = unit.location.cells
        assert cells, "单栏有线表每行 cells 非空"
        assert all(row == index for row, _ in cells), f"row {index} 网格行号连续"
        assert [col for _, col in cells] == sorted(col for _, col in cells)


def test_r8_overlapping_grid_rows_detected() -> None:
    """S4 信号：相邻网格行 bbox 纵向重叠 → 行切分错乱，须按列序修正行内顺序。"""
    # fake 行对象只需 bbox=(x0, y0, x1, y1)：row47 的 y 区间嵌进 row46（跨栏续表
    # 左侧行高 ≠ 右侧行高时 find_tables 的行网格互相咬合）。
    rows = [
        type("R", (), {"bbox": (42.0, 513.9, 553.1, 531.5)})(),
        type("R", (), {"bbox": (42.0, 522.7, 553.1, 531.5)})(),
        type("R", (), {"bbox": (42.0, 531.5, 553.1, 549.4)})(),
    ]
    assert _overlapping_row_indices(rows) == frozenset({0, 1})
    assert _overlapping_row_indices(rows[:1]) == frozenset()


def test_r8_cross_column_continuation_row_order_kept() -> None:
    """S4/R9 跨栏续表：发射主键是页面原生序连续组，而非错乱 grid 行/行内序。

    R9 修正：universality 探针证明页面原生流（``native_pos`` 次序）是 gold 引文的
    地面真值阅读序。旧实现 S4 对网格错乱行强排"网格列序"，会把左半列数值插进
    右半列标签与数值之间、打断引文连续。R9 改按 native 连续性切组并跨组发射：
    同一逻辑行（R32 的产能值）native 218/221/222/223 连续成组，不被右半标签
    （R32…，native 404-407 靠后）打断。
    """
    row46 = _TableRow(
        cells=(
            _TableCell(text="24.0 28.5 28.5", row=46, col=9, native_pos=218),
            _TableCell(text="R32", row=46, col=2, native_pos=404),
            _TableCell(text="99.6%", row=46, col=6, native_pos=405),
            _TableCell(text="-", row=46, col=7, native_pos=406),
            _TableCell(text="51.6%", row=46, col=8, native_pos=407),
        )
    )
    row47 = _TableRow(
        cells=(
            _TableCell(text="-", row=47, col=9, native_pos=221),
            _TableCell(text="18.8%", row=47, col=10, native_pos=222),
            _TableCell(text="0.0%", row=47, col=11, native_pos=223),
        )
    )
    table = _Table(
        index=0,
        bbox=(42.6, 112.0, 553.1, 704.2),
        rows=[row46, row47],
        column_ordered_rows=frozenset({0, 1}),
    )
    units: list[object] = []
    issues: list[object] = []
    _emit_table(table, 0, page_no=10, page_lines=[], units=units, issues=issues)
    # native 218 / 221-223 连续 → 产能值组 + 续接组相邻，右半标签组在其后。
    rendered = _WS.sub("", "".join(u.raw_text for u in units))  # type: ignore[attr-defined]
    # I2：e5 六个取值（24.0 28.5 28.5 - 18.8% 0.0%）在发射文本内连续成串。
    assert "24.028.528.5-18.8%0.0%" in rendered, rendered
    # I1：只换行、无插入字符（每行即一个 c.text；全部单元格一行一次）。
    emitted = [line for u in units for line in u.raw_text.split("\n")]  # type: ignore[attr-defined]
    assert sorted(emitted) == sorted(c.text for row in (row46, row47) for c in row.cells)
    # 覆盖：每个单元格恰好一行（无遗漏、无重复）。
    assert len(emitted) == len(row46.cells) + len(row47.cells)


# --- reader-pdf-9（R9：行内一律按原生阅读序发射，合并网格强排列序回归修正） ---


def test_r9_cross_column_merged_grid_keeps_quote_contiguous() -> None:
    """R9 图6 续表：合并网格行内按 native 连续性切组，尿素与价格分位连续成串。

    构造尿素逻辑行：产能值（col3，native 62）、价格值（col9，native 65）、标签
    尿素与价格分位（col2/6/7/8，native 349-352 连续）。即便该行被标 column_order，
    R9 仍按 native 连续性把同一逻辑行的取值切成连续组发射，使「尿素 32.1% 
    10.9% 89.9%」在发射文本内连续成串（不被产能/价格值打断）。
    """
    row = _TableRow(
        cells=(
            _TableCell(text="5814.2 6728.3 6759.6", row=10, col=3, native_pos=62),
            _TableCell(text="7696.0 7956.0 8068.0", row=10, col=9, native_pos=65),
            _TableCell(text="尿素", row=10, col=2, native_pos=349),
            _TableCell(text="32.1%", row=10, col=6, native_pos=350),
            _TableCell(text="10.9%", row=10, col=7, native_pos=351),
            _TableCell(text="89.9%", row=10, col=8, native_pos=352),
        )
    )
    table = _Table(
        index=0, bbox=(69.8, 112.0, 513.2, 220.0), rows=[row], column_ordered_rows=frozenset({0})
    )
    units: list[object] = []
    issues: list[object] = []
    _emit_table(table, 0, page_no=10, page_lines=[], units=units, issues=issues)
    # native 349-352 连续同行 → 自成一组；产能/价格值（native 62/65）另组。
    rendered = "".join(u.raw_text for u in units)  # type: ignore[attr-defined]
    merged = rendered.replace("\n", "")
    # I2：e3 四值（尿素 32.1% 10.9% 89.9%）在发射文本内连续成串。
    assert "尿素32.1%10.9%89.9%" in merged, rendered
    # I1/覆盖：每个单元格恰好一行（无插入、无遗漏、无重复）。
    emitted = [line for u in units for line in u.raw_text.split("\n")]  # type: ignore[attr-defined]
    assert sorted(emitted) == sorted(c.text for c in row.cells)
    assert len(emitted) == len(row.cells)


def test_r9_header_row_source_order_kept() -> None:
    """R9 表头行：行内按原生阅读序发射，产能/产品/表观/价格分位…回复源序。

    旧实现 column_order 按列强排把 header 散成「产品/表观/价格分位/价差分位/
    开工率/产能」，而来源序列是「产能/产品/表观/价格分位/价差分位/开工率」。
    """
    row = _TableRow(
        cells=(
            _TableCell(text="产品", row=0, col=1, native_pos=321),
            _TableCell(text="表观消费量（万吨）以及同比增长", row=0, col=3, native_pos=322),
            _TableCell(text="价格分位", row=0, col=6, native_pos=323),
            _TableCell(text="价差分位", row=0, col=7, native_pos=324),
            _TableCell(text="开工率", row=0, col=8, native_pos=325),
            _TableCell(text="产能（万吨/年）以及同比增长", row=0, col=9, native_pos=320),
        )
    )
    text, cells = _row_text(row)
    rendered = " ".join(text.split())
    assert rendered.startswith("产能（万吨/年）以及同比增长 产品 表观消费量（万吨）以及同比增长"), (
        rendered
    )
    assert "价格分位 价差分位 开工率" in rendered, rendered
    assert [col for _, col in cells] == [9, 1, 3, 6, 7, 8], cells


def test_r9_label_and_number_columns_not_lost_under_native_order() -> None:
    """R9 覆盖守卫：切换为原生序后，标签列与数字列单元格一律不丢。

    标签列（行首科目）与数字列（数值）在合并网格中的 native 位散布在不同文本块，
    一行内不得因重排而遗漏任何一格；I1 仅换行不变。
    """
    row = _TableRow(
        cells=(
            _TableCell(text="工业硅", row=3, col=0, native_pos=180),
            _TableCell(text="尿素", row=3, col=2, native_pos=349),
            _TableCell(text="32.1%", row=3, col=6, native_pos=350),
            _TableCell(text="89.9%", row=3, col=8, native_pos=352),
            _TableCell(text="5814.2 6728.3 6759.6", row=3, col=3, native_pos=62),
        )
    )
    text, _ = _row_text(row)
    lines = text.split("\n")
    assert all(
        cell in lines for cell in ("工业硅", "尿素", "32.1%", "89.9%", "5814.2 6728.3 6759.6")
    )
    # I1/覆盖：发射文本各行为单元格文本一一对应（无插入、无丢失、无重复）。
    assert sorted(lines) == sorted(c.text for c in row.cells)


def test_r9_value_and_growth_continuation_single_unit() -> None:
    """R9 续行归并：产能取值行与其同比增长续行拆成两网格行时，六值入同一单元。

    find_tables 把同一产品行拆成「取值行（含行标签/价格）」+「纯数值续行」。
    续行不含行标签，应并入前一逻辑行；行内按 ``_NATIVE_MERGE_GAP`` 吞掉取值格
    折叠子行的幻影空隙，使 e5 六值（24.0 28.5 28.5 - 18.8% 0.0%）落在**同一个**
    table_row 单元，右半价格（R32 99.6% - 51.6%）仍在独立单元。
    """
    row46 = _TableRow(
        cells=(
            _TableCell(text="24.0 28.5 28.5", row=46, col=9, native_pos=218),
            _TableCell(text="R32", row=46, col=2, native_pos=404),
            _TableCell(text="99.6%", row=46, col=6, native_pos=405),
            _TableCell(text="-", row=46, col=7, native_pos=406),
            _TableCell(text="51.6%", row=46, col=8, native_pos=407),
        )
    )
    row47 = _TableRow(  # 纯数值续行：无行标签，应并入 row46
        cells=(
            _TableCell(text="-", row=47, col=9, native_pos=221),
            _TableCell(text="18.8%", row=47, col=10, native_pos=222),
            _TableCell(text="0.0%", row=47, col=11, native_pos=223),
        )
    )
    table = _Table(index=0, bbox=(42.6, 112.0, 553.1, 704.2), rows=[row46, row47])
    units: list[object] = []
    issues: list[object] = []
    _emit_table(table, 0, page_no=10, page_lines=[], units=units, issues=issues)
    e5_norm = _WS.sub("", "24.0\n28.5\n28.5\n-\n18.8%\n0.0%")
    assert any(e5_norm in _WS.sub("", u.raw_text) for u in units), units  # type: ignore[attr-defined]
    # 右半价格独立成单元（不与 e5 六值混在同一单元）：
    assert any("R32" in str(u.raw_text) for u in units)  # type: ignore[attr-defined]
    # I1/覆盖：每个单元格恰好一行，无插入/遗漏/重复。
    emitted = [line for u in units for line in u.raw_text.split("\n")]  # type: ignore[attr-defined]
    assert sorted(emitted) == sorted(c.text for row in (row46, row47) for c in row.cells)
    assert len(emitted) == len(row46.cells) + len(row47.cells)


# --- 开发材料 smoke（守卫允许清单内的 6 份真实 PDF，只读） ---


def _dev_materials() -> list[Path]:
    config_path = REPO / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i1.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    return [REPO / raw for raw in config["sources"]["allowed_source_paths"]]


def test_dev_materials_smoke_units_and_pages() -> None:
    for path in _dev_materials():
        result = read_document(path)
        assert result.page_count is not None and result.page_count >= 1, path.name
        assert result.units, path.name
        assert result.extractor_rev.startswith("reader-pdf-10+")


def test_readers_do_not_import_pg_or_model_client() -> None:
    # 干净子进程断言：同进程其他测试文件不应污染本纪律
    code = (
        "import sys; import plugins.corpus.preparation.readers;"
        "bad = [m for m in ('psycopg', 'psycopg2', 'asyncpg', 'sqlalchemy',"
        " 'openai', 'anthropic') if m in sys.modules];"
        "print(f'leaked: {bad}'); sys.exit(1 if bad else 0)"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stdout + proc.stderr
