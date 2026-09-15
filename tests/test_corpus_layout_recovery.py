"""Mixed-page recall and customer-column evidence; no external models or PDFs."""

import pymupdf

from plugins.corpus.claims_v2 import triage_block_detail
from plugins.corpus.evidence import parse_evidence
from plugins.corpus.evidence_pipeline import build_evidence_run, project_claims


def test_sidebar_list_does_not_hide_numeric_body():
    text = "相关研究报告\n" + "《利率走势》20260101\n" * 8
    text += "美国8月新增非农就业改善。非农就业人数同比增长0.38%。"
    assert triage_block_detail(text).candidate


def test_footer_does_not_hide_numeric_body():
    text = "生产资料价格指数环比升0.70%，同比升20.15%。\n下载日志已记录，仅供内部参考"
    assert triage_block_detail(text).candidate


def test_contact_only_and_related_titles_remain_noise():
    assert not triage_block_detail("相关研究报告\n" + "《利率走势》20260101\n" * 8).candidate
    assert not triage_block_detail("投资评级标准：买入=预期收益率超过20%").candidate


def customer_pdf(tmp_path, *, header="销售额（万元）", period="2025", bad=False):
    path = tmp_path / "2026-09-01_301697.SZ.pdf"
    pdf = pymupdf.open()
    page = pdf.new_page()
    page.insert_text((40, 60), f"表1：公司{period}年前五大客户", fontname="china-s", fontsize=10)
    for x, label in [(40, "客户名称"), (220, header), (380, "占收入比例")]:
        page.insert_text((x, 90), label, fontname="china-s", fontsize=10)
    for y, name, sale, ratio in [
        (115, "甲客户", "120.00", "12.00%"),
        (140, "合计", "120.00", "12.00%"),
    ]:
        for x, value in [(45, name), (235, sale), (385, "12.00" if bad else ratio)]:
            page.insert_text((x, y), value, fontname="china-s", fontsize=10)
    page.insert_text((40, 165), "数据来源：公司招股说明书", fontname="china-s", fontsize=10)
    pdf.save(path)
    pdf.close()
    return path


def test_customer_table_restores_cells_title_footnote_and_period(tmp_path):
    run = build_evidence_run(customer_pdf(tmp_path), pages=(1,))
    packets = [p for p in run.document.packets if p.kind == "table"]
    assert len(packets) == 2
    cells = [c for p in packets for c in p.cells]
    assert {(c.row, c.column, c.value, c.unit) for c in cells} == {
        (name, column, value, unit)
        for name in ("甲客户", "合计")
        for column, value, unit in [
            ("销售额（万元）", "120.00", "万元"),
            ("占收入比例", "12.00%", "%"),
        ]
    }
    assert all("招股说明书" in " ".join(p.context) for p in packets)
    assert all(c.span.bbox and c.column_span.bbox for c in cells)
    assert all(c.unit_span.text.endswith("%") for c in cells if c.unit == "%")
    assert all(f.claim.period_raw == "2025" for f in run.facts)
    assert all(f.claim.qualifiers.get("customer") for f in run.facts)
    assert all("calculate" not in f.usable_for for f in run.facts)


def test_customer_ratio_without_explicit_percent_is_not_guessed(tmp_path):
    document = parse_evidence(customer_pdf(tmp_path, bad=True))
    assert not any(p.cells for p in document.packets)


def test_skipped_page_does_not_prove_source_absence(tmp_path):
    path = tmp_path / "noise.md"
    path.write_text("投资评级标准：买入=预期收益率超过20%", encoding="utf-8")
    run = build_evidence_run(path)
    result = project_claims(run, purpose="calculate")
    assert result["complete"]  # Backwards-compatible execution status only.
    assert not result["coverage_verified"]
    assert result["coverage_status"] == "unknown"
