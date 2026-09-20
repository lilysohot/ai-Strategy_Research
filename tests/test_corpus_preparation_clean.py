"""I1-3 保真清洗测试：映射回原文、区域台账无记录不消失、噪声保守判定反例。

验收（任务 I1-3）：每区有状态；映射回到权威原文；不无记录消失。保护数字/
期间/否定/条件（空白投影不变式）；页眉页脚需重复+几何共同判定；风险提示与
实际评级不因相似前缀被删；读取缺口转合成区域。不构造真实 PG/模型客户端。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from plugins.corpus.preparation.clean import (
    CLEAN_REV,
    CleanError,
    clean_reader_result,
    resolve_mapping,
    verify_clean_region,
)
from plugins.corpus.preparation.contract import DocumentFormat, UnitLocation, UnitStatus
from plugins.corpus.preparation.readers import read_document
from plugins.corpus.preparation.readers.base import CandidateUnit, ReaderIssue, ReaderResult

REPO = Path(__file__).resolve().parents[1]


def _unit(
    ordinal: int,
    raw_text: str,
    *,
    kind: str = "paragraph",
    status: UnitStatus = UnitStatus.KEPT,
    reasons: tuple[str, ...] = (),
    page: int | None = None,
    bbox: tuple[float, float, float, float] | None = None,
) -> CandidateUnit:
    return CandidateUnit(
        ordinal=ordinal,
        kind=kind,
        status=status,
        reasons=reasons,
        raw_text=raw_text,
        location=UnitLocation(page=page, bbox=bbox),
    )


def _result(units: list[CandidateUnit], issues: tuple[ReaderIssue, ...] = ()) -> ReaderResult:
    return ReaderResult(
        format=DocumentFormat.PDF,
        extractor_rev="reader-test-1",
        source_path="synthetic",
        page_count=None,
        units=tuple(units),
        issues=issues,
    )


def _regions_by_ordinal(result) -> dict[int, object]:
    return {r.ordinal: r for r in result.regions if r.ordinal is not None}


# --- 保真视图与锚点映射 ---


def test_cjk_join_and_ascii_join_mapping() -> None:
    cjk = _unit(1, "第一段\n第二段")
    ascii_mix = _unit(2, "First line\nSecond line")
    result = clean_reader_result(_result([cjk, ascii_mix]))
    regions = _regions_by_ordinal(result)
    assert regions[1].clean_view == "第一段第二段"  # type: ignore[attr-defined]
    assert regions[2].clean_view == "First line Second line"  # type: ignore[attr-defined]
    mapping_cjk = regions[1].mapping  # type: ignore[attr-defined]
    assert mapping_cjk == ((0, 0), (3, 4))
    assert resolve_mapping(mapping_cjk, 0) == 0
    assert resolve_mapping(mapping_cjk, 2) == 2
    assert resolve_mapping(mapping_cjk, 3) == 4  # 第二个「第」回到原文偏移 4
    for ordinal, raw in {1: "第一段\n第二段", 2: "First line\nSecond line"}.items():
        region = regions[ordinal]
        verify_clean_region(raw, region.clean_view, region.mapping)  # type: ignore[arg-type]


def test_whitespace_collapse_and_strip_mapping() -> None:
    raw = "甲  乙  \n  丙 "
    result = clean_reader_result(_result([_unit(1, raw)]))
    region = _regions_by_ordinal(result)[1]
    assert region.clean_view == "甲 乙丙"  # type: ignore[attr-defined]
    assert region.mapping == ((0, 0), (2, 3), (3, 9))  # type: ignore[attr-defined]
    assert resolve_mapping(region.mapping, 2) == 3  # type: ignore[attr-defined]
    assert resolve_mapping(region.mapping, 3) == 9  # type: ignore[attr-defined]
    verify_clean_region(raw, region.clean_view, region.mapping)  # type: ignore[attr-defined]


def test_numbers_periods_negation_conditionals_preserved() -> None:
    raw = "2024年营收  -3.5%（不包含补贴）；如果Q4超预期则上调。数字 1  234 如上。"
    result = clean_reader_result(_result([_unit(1, raw)]))
    region = _regions_by_ordinal(result)[1]
    clean_view = region.clean_view  # type: ignore[attr-defined]
    assert "".join(clean_view.split()) == "".join(raw.split())  # 非空白字符零丢失零改写
    assert "1 234" in clean_view and "2024" in clean_view and "如果" in clean_view  # type: ignore[union-attr]
    verify_clean_region(raw, clean_view, region.mapping)  # type: ignore[attr-defined]


def test_code_fence_kept_verbatim() -> None:
    raw = "```\nkeep  spacing\n```"
    result = clean_reader_result(_result([_unit(1, raw, reasons=("code_fence",))]))
    region = _regions_by_ordinal(result)[1]
    assert region.clean_view == raw  # 代码内容空白原样保留，不折叠
    assert region.mapping == ((0, 0),)
    verify_clean_region(raw, region.clean_view, region.mapping)


def test_verify_clean_region_rejects_broken_mapping() -> None:
    verify_clean_region("甲乙", "甲乙", ((0, 0),))
    with pytest.raises(CleanError):  # 非空白字符未被覆盖
        verify_clean_region("甲乙", "甲", ((0, 0),))
    with pytest.raises(CleanError):  # 首锚点未覆盖 clean 0
        verify_clean_region("甲乙", "甲乙", ((1, 0),))
    with pytest.raises(CleanError):  # clean 空格映射到非空白原文
        verify_clean_region("甲乙", "甲 乙", ((0, 0), (2, 1)))
    with pytest.raises(CleanError):  # clean_view 为空时不得携带 mapping
        verify_clean_region("甲乙", None, ((0, 0),))


# --- 区域台账：每区有状态，不无记录消失 ---


def test_region_ledger_complete_with_synthetic_gaps() -> None:
    units = [
        _unit(1, "正文甲"),
        _unit(2, "……\ufffd……", status=UnitStatus.REVIEW_REQUIRED, reasons=("garbled_text",)),
        _unit(3, "LEFT0 alpha", reasons=("multi_column_order_flagged",)),
    ]
    issues = (
        ReaderIssue("empty_page", "page:1", "无文字层且无图片"),
        ReaderIssue("image_only_page", "page:2", "需 OCR"),
        ReaderIssue("unreadable_element", "body[3]", "段落含图片"),
        ReaderIssue("unreadable_element", "body[3]", "重复位置去重"),
    )
    result = clean_reader_result(_result(units, issues))
    unit_regions = [r for r in result.regions if r.ordinal is not None]
    assert sorted(r.ordinal for r in unit_regions) == [1, 2, 3]  # 读取单元逐一立区
    gaps = {(r.reasons[0], r.status) for r in result.regions if r.ordinal is None}
    assert ("empty_page", UnitStatus.REVIEW_REQUIRED) in gaps
    assert ("image_only_page", UnitStatus.NEEDS_OCR) in gaps
    assert ("unreadable_element", UnitStatus.REVIEW_REQUIRED) in gaps
    assert (
        len(
            [
                r
                for r in result.regions
                if r.ordinal is None and r.reasons[0] == "unreadable_element"
            ]
        )
        == 1
    )  # 去重
    assert len(result.regions) == len(units) + 3
    assert all(
        r.status
        in {
            UnitStatus.KEPT,
            UnitStatus.NOISE,
            UnitStatus.REVIEW_REQUIRED,
            UnitStatus.NEEDS_OCR,
        }
        for r in result.regions
    )  # clean 不产出 out_of_scope/oversized（分别留给 I1-5 准入与 I1-4 切块）


def test_reader_status_propagates_without_upgrade() -> None:
    units = [
        _unit(1, "乱码页文本", status=UnitStatus.REVIEW_REQUIRED, reasons=("garbled_text",)),
        _unit(2, "图片页占位", status=UnitStatus.NEEDS_OCR, reasons=("image_only_page",)),
        _unit(3, "LEFT0 alpha beta", reasons=("multi_column_order_flagged",)),
    ]
    result = clean_reader_result(_result(units))
    regions = _regions_by_ordinal(result)
    assert regions[1].status is UnitStatus.REVIEW_REQUIRED  # 不升级为保留
    assert regions[1].clean_view is None
    assert regions[2].status is UnitStatus.NEEDS_OCR
    assert regions[3].status is UnitStatus.KEPT  # 多栏标记（不重排）后正常清洗
    assert "multi_column_order_flagged" in regions[3].reasons
    assert regions[3].clean_view == "LEFT0 alpha beta"


def test_determinism_same_input_same_output() -> None:
    units = [_unit(1, "正文\n第二行"), _unit(2, "目录\n导论……1\n正文……2", kind="heading")]
    first = clean_reader_result(_result(units))
    second = clean_reader_result(_result(units))
    assert first == second
    assert first.clean_rev == CLEAN_REV


# --- 噪声判定：保守正向命中 ---


def test_header_footer_requires_repetition_and_band() -> None:
    units: list[CandidateUnit] = []
    ordinal = 0
    for page in (1, 2, 3, 4):
        for text, bbox in (
            ("请务必阅读正文之后的免责条款", (60.0, 20.0, 500.0, 40.0)),
            (f"第{page}页正文内容", (60.0, 100.0, 500.0, 120.0)),
        ):
            ordinal += 1
            units.append(_unit(ordinal, text, page=page, bbox=bbox))
    for page in (1, 2, 3):
        ordinal += 1
        units.append(
            _unit(ordinal, "免责条款详见背面", page=page, bbox=(60.0, 760.0, 500.0, 780.0))
        )
    ordinal += 1
    units.append(_unit(ordinal, "只在两页出现的文字", page=2, bbox=(60.0, 300.0, 500.0, 320.0)))
    ordinal += 1
    units.append(_unit(ordinal, "页底补充说明", page=4, bbox=(60.0, 700.0, 500.0, 720.0)))

    regions = _regions_by_ordinal(clean_reader_result(_result(units)))
    header_regions = [r for r in regions.values() if "header_repeated_geometric" in r.reasons]
    assert len(header_regions) == 4  # 重复 4 页 + 顶带共同判定
    footer_regions = [r for r in regions.values() if "footer_repeated_geometric" in r.reasons]
    assert len(footer_regions) == 3
    assert all(r.status is UnitStatus.NOISE for r in header_regions + footer_regions)
    twice = [r for r in regions.values() if r.ordinal == 12]
    assert twice[0].status is UnitStatus.KEPT  # 仅重复 2 页 < 阈值，不删
    body = [r for r in regions.values() if r.ordinal == 2]
    assert body[0].status is UnitStatus.KEPT
    bottom_note = [r for r in regions.values() if r.ordinal == 13]
    assert bottom_note[0].status is UnitStatus.KEPT  # 仅几何在底带而内容不重复，不删


def test_toc_disclaimer_sections_and_protected_prefixes() -> None:
    units = [
        _unit(1, "目录", kind="heading"),
        _unit(2, "第一章 公司概况……3\n第二章 行业分析……7"),
        _unit(3, "风险提示", kind="heading"),
        _unit(4, "若原材料价格大幅上涨，则毛利率承压。"),
        _unit(5, "免责声明", kind="heading"),
        _unit(6, "本报告仅供签约客户使用。"),
        _unit(7, "风险提示", kind="heading"),
        _unit(8, "评级：买入，目标价12元。"),
        _unit(9, "评级说明", kind="heading"),
        _unit(10, "买入指未来六个月相对涨幅高于20%。"),
        _unit(11, "盈利预测", kind="heading"),
        _unit(12, "免责声明：本报告作者具有专业胜任能力。"),
        _unit(13, "评级说明：维持买入评级。"),
        _unit(14, "分析师：张三\n联系人：李四"),
    ]
    regions = _regions_by_ordinal(clean_reader_result(_result(units)))
    expected_noise = {
        1: "toc_heading",
        2: "toc_dot_leaders",
        5: "disclaimer_heading",
        6: "disclaimer_section",
        9: "disclaimer_heading",
        10: "disclaimer_section",
        12: "disclaimer_prefix",
        14: "analyst_roster",
    }
    for ordinal, reason in expected_noise.items():
        assert regions[ordinal].status is UnitStatus.NOISE, ordinal
        assert reason in regions[ordinal].reasons, ordinal
    for ordinal in (3, 4, 7, 8, 11, 13):  # 风险提示/实际评级/条件句/相似前缀保护
        assert regions[ordinal].status is UnitStatus.KEPT, ordinal


def test_analyst_roster_versus_body_citation() -> None:
    units = [
        _unit(1, "分析师：张三\n联系人：李四"),
        _unit(2, "分析师：张三 执业证书编号：S0120520000014"),
        _unit(3, "分析师张三（执业证书编号：S0120520000014）覆盖该公司并维持买入评级。"),
    ]
    regions = _regions_by_ordinal(clean_reader_result(_result(units)))
    assert regions[1].status is UnitStatus.NOISE and "analyst_roster" in regions[1].reasons
    assert regions[2].status is UnitStatus.NOISE
    assert regions[3].status is UnitStatus.KEPT  # 正文句内引用证书编号不因相似片段被删


# --- 开发材料 smoke（守卫允许清单内的 6 份真实 PDF，只读） ---


def _dev_materials() -> list[Path]:
    config_path = REPO / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i1.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    return [REPO / raw for raw in config["sources"]["allowed_source_paths"]]


def test_dev_materials_clean_fidelity() -> None:
    for path in _dev_materials():
        reader_result = read_document(path)
        result = clean_reader_result(reader_result)
        unit_regions = [r for r in result.regions if r.ordinal is not None]
        assert sorted(r.ordinal for r in unit_regions) == [
            u.ordinal for u in reader_result.units
        ], path.name
        for region in unit_regions:
            unit = next(u for u in reader_result.units if u.ordinal == region.ordinal)
            if region.status is UnitStatus.KEPT:
                assert region.clean_view is not None, (path.name, region.ordinal)
                assert "".join(region.clean_view.split()) == "".join(unit.raw_text.split()), (
                    path.name,
                    region.ordinal,
                )  # 非空白零丢失：映射可回到权威原文
                verify_clean_region(unit.raw_text, region.clean_view, region.mapping)


def test_clean_does_not_import_pg_or_model_client() -> None:
    # 干净子进程断言：同进程其他测试文件不应污染本纪律
    code = (
        "import sys; import plugins.corpus.preparation.clean;"
        "bad = [m for m in ('psycopg', 'psycopg2', 'asyncpg', 'sqlalchemy',"
        " 'openai', 'anthropic') if m in sys.modules];"
        "print(f'leaked: {bad}'); sys.exit(1 if bad else 0)"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
