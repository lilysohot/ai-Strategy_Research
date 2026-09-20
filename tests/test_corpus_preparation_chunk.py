"""I1-4 结构优先切块测试：不断单元格/句界安全/超长显式复核/问答表格上下文分离。

验收（任务 I1-4）：不断单元格/混期间；超长不可分单元显式复核；检索块不当
原子义务。通过真实 clean 管线构造输入（CandidateUnit → clean → chunk），并含
6 份开发材料只读 smoke。不构造真实 PG/模型客户端。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from plugins.corpus.preparation.chunk import (
    CHUNK_REV,
    HARD_LIMIT,
    TARGET_MIN,
    ChunkError,
    chunk_clean_result,
    normalize_search_text,
    verify_chunk_result,
)
from plugins.corpus.preparation.clean import clean_reader_result
from plugins.corpus.preparation.contract import DocumentFormat, UnitLocation, UnitStatus
from plugins.corpus.preparation.readers import read_document
from plugins.corpus.preparation.readers.base import CandidateUnit, ReaderResult

REPO = Path(__file__).resolve().parents[1]


def _unit(
    ordinal: int,
    raw_text: str,
    *,
    kind: str = "paragraph",
    reasons: tuple[str, ...] = (),
    page: int | None = None,
    bbox: tuple[float, float, float, float] | None = None,
    element: str | None = None,
    cells: tuple[tuple[int, int], ...] = (),
    label_path: tuple[str, ...] = (),
) -> CandidateUnit:
    return CandidateUnit(
        ordinal=ordinal,
        kind=kind,
        status=UnitStatus.KEPT,
        reasons=reasons,
        raw_text=raw_text,
        location=UnitLocation(
            page=page, bbox=bbox, element=element, cells=cells, label_path=label_path
        ),
    )


def _chunk_of(units: list[CandidateUnit]):
    reader_result = ReaderResult(
        format=DocumentFormat.MARKDOWN,
        extractor_rev="reader-test-1",
        source_path="synthetic",
        page_count=None,
        units=tuple(units),
        issues=(),
    )
    return chunk_clean_result(reader_result, clean_reader_result(reader_result))


def _reader(units: list[CandidateUnit]) -> ReaderResult:
    return ReaderResult(
        format=DocumentFormat.MARKDOWN,
        extractor_rev="reader-test-1",
        source_path="synthetic",
        page_count=None,
        units=tuple(units),
        issues=(),
    )


def _by_key(result):
    return {chunk.key: chunk for chunk in result.chunks}


# --- 正文：章节/段落/句界与标题关联 ---


def test_body_accumulation_with_heading_title_and_section() -> None:
    units = [
        _unit(1, "一、行业概况", kind="heading"),
        _unit(2, "甲" * 500),
        _unit(3, "乙" * 500),
        _unit(4, "丙" * 500),
    ]
    result = _chunk_of(units)
    bodies = [c for c in result.chunks if c.kind == "body"]
    assert len(bodies) == 2
    assert [c.unit_ordinals for c in bodies] == [(1, 2, 3), (4,)]  # 标题 ordinal 随首块携带
    assert all(c.title_text == "一、行业概况" for c in bodies)
    assert all(c.section_path == ("一、行业概况",) for c in bodies)
    sizes = [len(c.search_text) for c in bodies]
    assert sizes[0] == 1001  # 500+1+500：加满至 TARGET_MAX 上限内
    assert all(TARGET_MIN <= size <= HARD_LIMIT or size < TARGET_MIN for size in sizes)


def test_heading_without_following_content_kept_standalone() -> None:
    units = [
        _unit(1, "一、摘要", kind="heading"),
        _unit(2, "二、风险提示", kind="heading"),
        _unit(3, "若需求下滑则盈利承压。"),
    ]
    result = _chunk_of(units)
    headings = [c for c in result.chunks if c.kind == "heading"]
    assert len(headings) == 1  # 「一、摘要」无后文，独立保留不删除
    assert headings[0].search_text == "一、摘要"
    body = next(c for c in result.chunks if c.kind == "body")
    assert body.title_text == "二、风险提示"
    assert body.section_path == ("一、摘要", "二、风险提示")


def test_overlimit_paragraph_splits_at_sentence_boundary_without_loss() -> None:
    paragraph = "确定性句子内容。" * 500  # 4000 字符，仅 CJK 句界可切
    units = [_unit(1, paragraph)]
    result = _chunk_of(units)
    bodies = [c for c in result.chunks if c.kind == "body"]
    assert bodies, "应产生正文块"
    assert all(len(c.search_text) <= HARD_LIMIT for c in bodies)
    assert all(c.review_reasons == () for c in bodies)  # 句界可切，非超长不可分
    joined = "".join(c.search_text for c in bodies)
    assert joined.replace("\n", "") == paragraph  # 句界切分零丢失零改写
    verify_chunk_result(clean_reader_result(_reader(units)), result)


def test_unsplittable_oversized_sentence_flagged_for_review() -> None:
    units = [_unit(1, "乙" * 1999 + "。")]
    result = _chunk_of(units)
    assert result.oversized_ordinals == (1,)
    flagged = [c for c in result.chunks if c.review_reasons]
    assert len(flagged) == 1
    assert flagged[0].review_reasons == ("oversized_unsplittable",)
    assert flagged[0].search_text == "乙" * 1999 + "。"  # 不截断后宣称完整
    verify_chunk_result(clean_reader_result(_reader(units)), result)


# --- 列表：条目原子 ---


def test_list_items_atomic_and_oversized_item_reviewed() -> None:
    units = [
        _unit(1, "1、需求项甲" + "甲" * 92),
        _unit(2, "2、需求项乙" + "乙" * 92),
        _unit(3, "3、" + "丙" * (HARD_LIMIT + 10), kind="list_item"),
    ]
    units[0] = CandidateUnit(
        ordinal=1,
        kind="list_item",
        status=UnitStatus.KEPT,
        reasons=(),
        raw_text=units[0].raw_text,
        location=UnitLocation(),
    )
    units[1] = CandidateUnit(
        ordinal=2,
        kind="list_item",
        status=UnitStatus.KEPT,
        reasons=(),
        raw_text=units[1].raw_text,
        location=UnitLocation(),
    )
    result = _chunk_of(units)
    lists = [c for c in result.chunks if c.kind == "list"]
    normal = [c for c in lists if not c.review_reasons]
    assert normal and all(
        c.search_text.count("、") >= c.search_text.count("\n") + 1 for c in normal
    )  # 条目未被切断：每行仍是完整「N、」条目
    oversized = [c for c in lists if c.review_reasons == ("oversized_unsplittable",)]
    assert len(oversized) == 1 and oversized[0].unit_ordinals == (3,)
    assert result.oversized_ordinals == (3,)


# --- 表格：行原子、列头 context、跨页不猜接 ---


def test_table_rows_carry_header_context_and_page_boundary_splits() -> None:
    units: list[CandidateUnit] = []
    ordinal = 0
    for page in (1, 2):
        for row in range(25):
            ordinal += 1
            units.append(
                _unit(
                    ordinal,
                    f"第{page}表行{row:02d}数值{row * 7}",
                    kind="table_row",
                    reasons=("tbl[0]",),
                    page=page,
                    bbox=(50.0, 100.0 + row * 20.0, 500.0, 120.0 + row * 20.0),
                )
            )
    result = _chunk_of(units)
    tables = [c for c in result.chunks if c.kind == "table"]
    assert len(tables) >= 2  # 每页各成组，跨页不靠位置猜接
    first_page = [c for c in tables if "第1表行" in c.search_text]
    second_page = [c for c in tables if "第2表行" in c.search_text]
    assert first_page and second_page
    assert all("第2表行" not in c.search_text for c in first_page)  # 两页行不混块
    assert all("第1表行" not in c.search_text for c in second_page)
    continuation = second_page[1:]
    for chunk in continuation:
        assert chunk.search_text.startswith("第2表行00")  # 续块携带本表列头 context
        assert 26 in chunk.unit_ordinals  # 列头行（第2表首行）引用随块携带
    assert all(len(c.search_text) <= HARD_LIMIT for c in tables)


def test_table_row_never_split_and_single_row_group() -> None:
    units = [_unit(1, "指标|数值|期间", kind="table_row", reasons=("tbl[0]",))]
    result = _chunk_of(units)
    tables = [c for c in result.chunks if c.kind == "table"]
    assert len(tables) == 1
    assert tables[0].search_text == "指标|数值|期间"
    assert tables[0].review_reasons == ()


def test_table_cell_index_text_carries_row_and_column_labels() -> None:
    """I-B1：任一表格单元格的索引文本必须同时含列标签路径与行标签。

    表格行单元携带与 cells 对齐的 label_path 时，其索引文本（search_text）注入
    「行标签 × 列标签」前缀；无 label_path 的合成单元保持旧行为逐字节一致。
    """
    units = [
        _unit(
            1,
            "尿素|89.9%",
            kind="table_row",
            reasons=("tbl[0]",),
            page=10,
            cells=((2, 0), (2, 8)),
            label_path=("尿素", "尿素 开工率"),
        ),
        _unit(
            2,
            "纯碱|82.9%",
            kind="table_row",
            reasons=("tbl[0]",),
            page=10,
            cells=((27, 0), (27, 8)),
            label_path=("纯碱", "纯碱 开工率"),
        ),
    ]
    result = _chunk_of(units)
    tables = [c for c in result.chunks if c.kind == "table"]
    assert len(tables) == 1
    text = tables[0].search_text
    # 行标签与列标签成对出现在索引文本（I-B1）
    assert "尿素 开工率" in text
    assert "纯碱 开工率" in text
    # 原文逐字内容仍在（不因注入标签而丢失；R5：% 归一化为空格，仅影响索引文本）
    assert "尿素|89.9" in text and "纯碱|82.9" in text
    assert "%" not in text  # normalize_search_text 归一化 % → 空格（R5）
    # 无标签的合成单元（本文件其余表格用例）行为不变
    plain = _chunk_of([_unit(3, "指标|数值|期间", kind="table_row", reasons=("tbl[0]",))])
    assert next(c for c in plain.chunks if c.kind == "table").search_text == "指标|数值|期间"


# --- 问答：问与答结构组，答案分段仍关联同一问题 ---


def test_qa_group_keeps_question_verbatim_across_segments() -> None:
    question = "问：公司如何看待下一年的资本开支计划？"
    units = [
        _unit(1, question),
        _unit(2, "答：资本开支将保持稳定。" + "甲" * 600),
        _unit(3, "补充：主要投向产能升级。" + "乙" * 600),
        _unit(4, "另见风险提示段落。" + "丙" * 600),
    ]
    result = _chunk_of(units)
    qa_chunks = [c for c in result.chunks if c.kind == "qa"]
    assert len(qa_chunks) >= 2  # 答案长时分段
    assert all(c.title_text == question for c in qa_chunks)  # 显式关联同一问题
    assert all(question in c.search_text for c in qa_chunks)  # 引用式 context 携带原文
    assert all(1 in c.unit_ordinals for c in qa_chunks)  # 问题单元随块引用
    assert all(question in c.search_text.split("\n")[0] for c in qa_chunks)  # 不改写成陈述
    assert all(len(c.search_text) <= HARD_LIMIT for c in qa_chunks)


def test_answer_before_any_question_stays_body() -> None:
    units = [_unit(1, "答：这是没有问题的普通正文段落。")]
    result = _chunk_of(units)
    assert [c.kind for c in result.chunks] == ["body"]


# --- 不变量与确定性 ---


def test_verify_rejects_missing_coverage_and_unknown_reference() -> None:
    units = [_unit(1, "正文甲"), _unit(2, "正文乙")]
    clean = clean_reader_result(_reader(units))
    result = chunk_clean_result(_reader(units), clean)
    verify_chunk_result(clean, result)
    trimmed = type(result)(
        chunk_rev=result.chunk_rev,
        chunks=result.chunks[:-1],  # 丢块 → 保留区未覆盖
        oversized_ordinals=result.oversized_ordinals,
    )
    with pytest.raises(ChunkError):
        verify_chunk_result(clean, trimmed)
    phantom = type(result)(
        chunk_rev=result.chunk_rev,
        chunks=(
            type(result.chunks[0])(
                key="body:999",
                kind="body",
                unit_ordinals=(99,),  # 幻影引用
                search_text="x",
                title_text=None,
                section_path=(),
            ),
        ),
        oversized_ordinals=(),
    )
    with pytest.raises(ChunkError):
        verify_chunk_result(clean, phantom)


def test_noise_and_review_regions_never_chunked() -> None:
    units = [
        _unit(1, "正文甲"),
        _unit(2, "目录\n导论……1\n正文……2"),
        _unit(3, "正文乙"),
    ]
    clean = clean_reader_result(_reader(units))
    result = chunk_clean_result(_reader(units), clean)
    used = {ordinal for c in result.chunks for ordinal in c.unit_ordinals}
    assert 2 not in used  # 目录噪声区不进入任何检索块
    noise_status = {r.ordinal: r.status for r in clean.regions if r.ordinal is not None}
    assert noise_status[2] is UnitStatus.NOISE
    verify_chunk_result(clean, result)


def test_determinism_same_input_same_output() -> None:
    units = [
        _unit(1, "一、概况", kind="heading"),
        _unit(2, "问：怎么看？"),
        _unit(3, "答：稳定。" + "甲" * 100),
        _unit(4, "指标|数值", kind="table_row", reasons=("tbl[0]",)),
    ]
    first = _chunk_of(units)
    second = _chunk_of(units)
    assert first == second
    assert first.chunk_rev == CHUNK_REV


# --- R5：搜索文本规范化（写侧与查询侧同一契约） ---


def test_search_text_normalizes_percent_and_fullwidth() -> None:
    # 写侧与查询侧共用：% / 全角 ％ 均归一化为空格，保证 "23.5" 可查。
    assert normalize_search_text("同比增长23.5%") == "同比增长23.5 "
    assert normalize_search_text("同比增长23.5％") == "同比增长23.5 "
    assert normalize_search_text("毛利率 30.0% 净利率 12.5%") == "毛利率 30.0  净利率 12.5 "
    # 无百分号原文保持不变；负号/小数/单位不受影响（不粗暴替换）
    assert normalize_search_text("营收 -12.5 亿元") == "营收 -12.5 亿元"


# --- 开发材料 smoke（守卫允许清单内的 6 份真实 PDF，只读） ---


def _dev_materials() -> list[Path]:
    config_path = REPO / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i1.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    return [REPO / raw for raw in config["sources"]["allowed_source_paths"]]


def test_dev_materials_chunk_invariants() -> None:
    for path in _dev_materials():
        reader_result = read_document(path)
        clean = clean_reader_result(reader_result)
        result = chunk_clean_result(reader_result, clean)
        verify_chunk_result(clean, result)  # 覆盖/上限/复核标记全量不变式
        for chunk in result.chunks:
            assert chunk.kind in {"body", "heading", "list", "qa", "table"}
            assert chunk.search_text and chunk.unit_ordinals
            if len(chunk.search_text) > HARD_LIMIT:
                assert chunk.review_reasons == ("oversized_unsplittable",), (path.name, chunk.key)


def test_chunk_does_not_import_pg_or_model_client() -> None:
    # 干净子进程断言：同进程其他测试文件不应污染本纪律
    code = (
        "import sys; import plugins.corpus.preparation.chunk;"
        "bad = [m for m in ('psycopg', 'psycopg2', 'asyncpg', 'sqlalchemy',"
        " 'openai', 'anthropic') if m in sys.modules];"
        "print(f'leaked: {bad}'); sys.exit(1 if bad else 0)"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stdout + proc.stderr
