"""I1-9 合成夹具生成器（一次性生成，输出字节此后冻结为固定夹具）。

任务清单 I1-9：``tests/fixtures/corpus_preparation/`` 拟新增合成 MD/DOCX/PDF
小夹具；真实版权资料不复制到公开夹具（架构 §12.1）。本脚本生成三件套：

- ``synthetic-company-report.md`` —— 重复标题、表格（负数/小数/单位）、问答、
  围栏代码、引用、列表、条件句/否定句；
- ``synthetic-company-report.docx`` —— 重复 Heading 2、外层表格含嵌套子表格
  与 cell 内图片（触发 unreadable_element）；
- ``synthetic-company-report.pdf`` —— 4 页：标题+正文页、文字+大图页
  （≥25% 页面积 → image_region_unreadable）、纯图页（image_only_page）、
  空页（empty_page）；不放有线表格（同基线多 cell 文本会触发多栏判定，
  表格覆盖由 DOCX/MD 夹具承担）。

全部内容为本任务虚构的合成文本，不含任何真实机构观点或受版权保护的第三方
材料；公司「星尘新材料」及全部数字均为编造。生成后夹具以当前字节为准冻结
（write-once，冻结快照记录各自 SHA-256）：MD 为纯文本写入、字节确定；DOCX/PDF
经 python-docx/pymupdf 保存，重生成行为等价但非逐字节相同（zip 时间戳、PDF
/ID 等运行期变量），完整性以冻结哈希为准，不依赖重生成一致性。

用法：``uv run python .scratch/corpus-evidence-pipeline/ingestion-rebuild/i1_9_make_fixtures.py``
输出为 write-once：目标文件已存在即退出，防止覆盖已冻结夹具。
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
OUT = REPO / "tests/fixtures/corpus_preparation"

MARKER = "本文件为语料入库 I1-9 合成夹具，全部内容为测试目的虚构。"

MD_TEXT = f"""# 合成样本：星尘新材料（虚构）2026 年第二季度业绩点评

{MARKER}公司「星尘新材料」与文中全部数字均为编造，不对应任何真实机构。

## 评级与观点

维持「增持」评级，目标价 42.50 元。并非所有产品线均实现提价；若下游需求不及预期，则全年增速可能放缓。经营现金流保持为正。

## 财务摘要

| 指标 | 本期 | 上年同期 | 同比 |
|---|---|---|---|
| 营业收入（万元） | 12,345.6 | 10,000.0 | 23.5% |
| 归母净利润（万元） | -234.5 | 1,000.0 | -123.5% |
| 毛利率 | 31.2% | 29.8% | 1.4pct |

2026 年第二季度公司营业收入为 12,345.6 万元，同比增长 23.5%；归母净利润为
-234.5 万元，同比下降 123.5%，主要由一次性计提导致。

## 问答（合成）

问：公司第二季度产能利用率如何？

答：第二季度产能利用率约为 82.3%，环比提升 3.1 个百分点。

问：新产能投放节奏是否有变化？

答：新产能按计划推进，预计第四季度试生产，不改变全年资本开支预算。

## 研发与产品

- 高纯石英材料良率提升至 91.2%
- 两个新牌号通过客户验证
- 研发费用率维持在 8.5% 左右

> 引用块（合成）：上游原料价格波动对成本的影响有限。

```
code_fence_sample_2026 = keep_original_lines
```

## 风险提示

行业竞争加剧的风险；原材料价格波动的风险。

## 风险提示

以上为重复标题合成样本，用于验证重复标题 ordinal 唯一、候选 ID 不冲突。
"""

PNG_4X4 = None  # 延迟构造，见 _png_bytes()


def _png_bytes() -> bytes:
    import pymupdf

    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 4, 4))
    return pixmap.tobytes("png")


def _guard_write_once(paths: tuple[Path, ...]) -> None:
    existing = [path for path in paths if path.exists()]
    if existing:
        print(f"FAIL 目标已存在（write-once，不得覆盖已冻结夹具）: {existing}")
        raise SystemExit(1)


def _write_md() -> Path:
    path = OUT / "synthetic-company-report.md"
    path.write_text(MD_TEXT, encoding="utf-8")
    return path


def _write_docx() -> Path:
    from docx import Document
    from docx.shared import Inches

    document = Document()
    document.core_properties.author = "corpus-i1-9-synthetic"
    document.core_properties.title = "synthetic-company-report (I1-9 fixture)"

    document.add_heading("合成样本：星尘新材料（虚构）2026 年第二季度业绩点评", level=1)
    document.add_paragraph(MARKER)
    document.add_paragraph(
        "2026 年第二季度公司营业收入为 12,345.6 万元，同比增长 23.5%；"
        "归母净利润为 -234.5 万元。并非所有产品线均实现提价；若下游需求不及预期，"
        "则全年增速可能放缓。"
    )

    document.add_heading("风险提示", level=2)
    document.add_paragraph("行业竞争加剧的风险；原材料价格波动的风险。")

    table = document.add_table(rows=2, cols=2)
    table.style = "Table Grid"
    cell_a = table.cell(0, 0)
    cell_a.text = "指标：产能利用率 82.3%，环比提升 3.1 个百分点。"
    cell_image = table.cell(0, 1)
    cell_image.paragraphs[0].add_run().add_picture(
        io.BytesIO(_png_bytes()), width=Inches(1.0)
    )
    cell_nested = table.cell(1, 0)
    cell_nested.text = "嵌套子表（合成）："
    nested = cell_nested.add_table(rows=2, cols=2)
    nested.style = "Table Grid"
    nested.cell(0, 0).text = "年份"
    nested.cell(0, 1).text = "营收（万元）"
    nested.cell(1, 0).text = "2025"
    nested.cell(1, 1).text = "10,000.0"
    table.cell(1, 1).text = "毛利率 31.2%，研发费用率 8.5%。"
    cell_nested.add_paragraph("嵌套子表后段落（合成）。")

    document.add_heading("风险提示", level=2)
    document.add_paragraph("以上为重复标题合成样本，用于验证重复标题 ordinal 唯一。")
    for item in ("高纯石英材料良率提升至 91.2%", "两个新牌号通过客户验证"):
        document.add_paragraph(item, style="List Bullet")

    path = OUT / "synthetic-company-report.docx"
    document.save(str(path))
    return path


def _write_pdf() -> Path:
    import pymupdf

    doc = pymupdf.open()

    # 第 1 页：标题（大字号）+ 两段正文（同段行距密、段间行距疏）。
    # 不放有线表格：同基线多 cell 文本会触发 multi_column 判定，表格覆盖由
    # DOCX/MD 夹具承担；本 PDF 专注页面级缺口记账。
    page = doc.new_page()
    page.insert_text(
        (72, 90), "合成样本：星尘新材料（虚构）二季度业绩点评", fontsize=16, fontname="china-s"
    )
    page.insert_text((72, 120), MARKER, fontsize=10.5, fontname="china-s")
    page.insert_text((72, 138), "公司「星尘新材料」与文中全部数字均为编造。", fontsize=10.5, fontname="china-s")
    page.insert_text((72, 170), "维持「增持」评级，目标价 42.50 元。", fontsize=10.5, fontname="china-s")
    page.insert_text((72, 188), "并非所有产品线均实现提价；若下游需求不及预期，则全年增速可能放缓。", fontsize=10.5, fontname="china-s")

    # 第 2 页：文字 + ≥25% 页面积大图（触发 image_region_unreadable）。
    page2 = doc.new_page()
    page2.insert_text((72, 90), "第二页：文字与合成大图共存。", fontsize=10.5, fontname="china-s")
    page2.insert_text((72, 115), "图片区域为编造占位，用于验证缺口记账。", fontsize=10.5, fontname="china-s")
    page2.insert_image(pymupdf.Rect(60, 150, 535, 790), pixmap=pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 4, 4)))

    # 第 3 页：纯图页（触发 image_only_page）。
    page3 = doc.new_page()
    page3.insert_image(pymupdf.Rect(120, 120, 475, 720), pixmap=pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 4, 4)))

    # 第 4 页：空页（触发 empty_page）。
    doc.new_page()

    doc.set_metadata({})  # 清空创建/修改时间等，保证生成即确定字节
    path = OUT / "synthetic-company-report.pdf"
    doc.save(str(path), garbage=3, deflate=True)
    doc.close()
    return path


def main() -> int:
    targets = (OUT / "synthetic-company-report.md", OUT / "synthetic-company-report.docx", OUT / "synthetic-company-report.pdf")
    _guard_write_once(targets)
    OUT.mkdir(parents=True, exist_ok=True)
    generated: list[Path] = []
    for writer in (_write_md, _write_docx, _write_pdf):
        path = writer()
        if path.exists() and path.stat().st_size == 0:
            print(f"FAIL 空文件: {path}")
            return 1
        generated.append(path)
    for path in sorted(OUT.iterdir()):
        import hashlib

        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        print(f"{path.name}\t{path.stat().st_size}\t{digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
