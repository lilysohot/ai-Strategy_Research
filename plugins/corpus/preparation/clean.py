"""保真清洗（任务 I1-3，架构 v1.1 §6.1）。

输入 I1-2 readers 的 :class:`~plugins.corpus.preparation.readers.base.ReaderResult`，
输出清洗区域台账 :class:`CleanResult`：每个来源区域（读取单元或读取缺口）都必须
有状态（kept/noise/review_required/needs_ocr；out_of_scope 保留给 I1-5 准入），
不存在无记录消失。纯标准库；同输入同 ``CLEAN_REV`` 输出逐字段一致。

规则（开发起点冻结于代码，I3 在开发集校准后才外置为参数）：

- ``clean_view`` 只做**空白投影**：逐行折叠水平空白、行间按 CJK 边界决定是否补
  空格；除空白外不删改任何字符——数字、符号、单位、期间、否定与条件句原样保留，
  可由 :func:`verify_clean_region` 的「非空白全覆盖」不变式机械验证（§6.1 不修改
  原数字/单位/指标名；规范值等附加投影不在此生成，不能覆盖原字段）。
- ``mapping`` 是 ``(clean_index, raw_index)`` 锚点序列：相邻锚点之间 clean 与 raw
  逐字符一一对应；任一 clean 偏移可经 :func:`resolve_mapping` 解析回权威原文
  code point 偏移。引用唯一权威仍是 ``raw_text`` + 原始坐标（契约 §4.2），
  ``clean_view`` 不是引用权威。
- 噪声判定保守（要求正向命中，宁漏勿删）：页眉/页脚需「归一化文本重复 ≥3 页 +
  几何顶/底带」共同判定，不凭单个词删除整页/整行；目录需点线引导行 ≥2 或精确
  标题；免责/评级说明按精确标题节与两个明确段落前缀进入噪声，节内单元保留原
  单元与原因；分析师名单需 ≥2 角色行或角色行+证书编号行。风险提示与实际评级
  不在任何噪声词表内（§6.1 相似前缀不删实际评级/风险提示/条件句）。
- 读取缺口（空页/图片页/表格冲突/不可读元素/未闭合围栏/未知元素）转为合成区域
  并继承缺口状态与结构化坐标，不静默吞掉；``garbled_text``/``multi_column_*``/
  ``table_text_overlap`` 已由读取单元的状态与原因承载，不重复立区。
- 缺口是否阻断发布**不在本模块判定**：本模块只保证「每个缺口都在台账里、带坐标」，
  分级（``blocking``/``acknowledged``）与 scope 归属由
  :mod:`plugins.corpus.preparation.gaps` 按架构 §7.3 表裁决。
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from plugins.corpus.preparation.contract import UnitStatus
from plugins.corpus.preparation.gaps import (
    GAP_CODE_STATUS,
    GAP_POLICY_REV,
    GapCoordinates,
    gap_key,
    parse_gap_location,
)
from plugins.corpus.preparation.readers.base import CandidateUnit, ReaderIssue, ReaderResult

CLEAN_REV = "clean-3"

# --- 开发起点参数（架构 §6.1；I3 校准前不外置） ---
_REPEAT_MIN_PAGES = 3
_BAND_RATIO = 0.12

# --- 噪声原因码 ---
_NOISE_HEADER = "header_repeated_geometric"
_NOISE_FOOTER = "footer_repeated_geometric"
_NOISE_TOC_HEADING = "toc_heading"
_NOISE_TOC_LEADERS = "toc_dot_leaders"
_NOISE_DISCLAIMER_HEADING = "disclaimer_heading"
_NOISE_DISCLAIMER_SECTION = "disclaimer_section"
_NOISE_DISCLAIMER_PREFIX = "disclaimer_prefix"
_NOISE_ROSTER = "analyst_roster"

_HEADING_KINDS = frozenset({"heading", "title"})
_DISCLAIMER_HEADINGS = frozenset(
    {"免责声明", "免责条款", "分析师声明", "分析师申明", "评级说明", "重要声明"}
)
_DISCLAIMER_PREFIXES = ("免责声明：", "免责声明:", "分析师声明：", "分析师声明:")
_TOC_EXACT = frozenset({"目录", "目錄", "contents"})
_TOC_LEADER = re.compile(r"[.．·…]{2,}\s*[0-9]{1,4}\s*$")
_ROLE_LINE = re.compile(r"(?:分析师|研究助理|联系人|报告联系人)\s*[：:]")
_CERT_PATTERN = re.compile(r"执业证书编号|\bS\d{8,12}\b")

# 票 08（I-E3）：免责节内『可复核数字事实句』的三类机器可读命中。
# 区分「规则阈值数字」vs「实测事实数字」：评级规则阈值句（『买入指…高于20%』）
# 只含裸百分比，不含持股/证券代码/金额语境，故不命中、不误降。
_NUMERIC_STAKE = re.compile(r"持有.{0,32}?\d+(?:\.\d+)?\s*%(?:[^。]{0,8})?(?:股份|股权|持股|股本)")
_STOCK_CODE = re.compile(r"(?<![0-9A-Za-z._=\-])[0368]\d{5}(?!\d)")
_MONEY_AMOUNT = re.compile(r"\d+(?:\.\d+)?\s*(?:亿|万|千|百)?\s*元(?!月|本|年)")

# 无对应读取单元的缺口码 → 合成区域状态（每区有状态，不无记录消失）。
# 词表唯一来源是 ``gaps.GAP_CODE_STATUS``（与默认分级表同键集，见架构 §7.3）：
# 本模块只负责「读取缺口 → 合成区域」的投影，是否阻断发布由 ``gaps`` 裁决。
# image_region_small（复核 R3）：面积阈值只决定复核优先级——小图按装饰噪声
# 显式记账进台账，不进入检索块，也不无记录消失。<25% 页面积的阈值是开发起点
# 约定，待 I3 人工金标验证校准后才冻结（校准只改阈值与优先级，不改记账语义）。
_SYNTHETIC_ISSUE_STATUS = GAP_CODE_STATUS

CleanMapping = tuple[tuple[int, int], ...]


class CleanError(ValueError):
    """清洗不变式被破坏（构造/校验即失败，不静默降级）。"""


@dataclass(frozen=True)
class NoiseVerdict:
    """一条噪声判定的机读依据（票 05：清洗判定依据可机读）。

    ``code`` 与 ``reasons`` 中的噪声码一致；``rule`` 是命中的具体规则名；
    ``observed`` 记录可复核的依据值（重复页数/带边界/命中行/占比/坐标，非空）；
    ``threshold`` 记录当时生效的阈值。区域为 KEPT 时，``verdicts`` 可含"评估过但
    未越过阈值"的近似命中（如页眉只重复 2 页），此时 ``code`` 不在 ``reasons``；
    仅 NOISE 区要求每条 ``code`` 都在 ``reasons`` 中（不变量 I-E1）。
    """

    code: str
    rule: str
    observed: dict[str, object]
    threshold: dict[str, object]


@dataclass(frozen=True)
class CleanRegion:
    """一个来源区域的清洗台账记录（对应契约 ``Unit`` 的清洗侧投影字段）。

    ``ordinal`` 指回读取单元（合成缺口区域为 ``None``）；``clean_view``/``mapping``
    仅对保留区给出（噪声/复核区不做投影，``raw_text`` 经单元保持权威可回溯）。

    ``coordinates`` 是合成缺口区域的结构化坐标（RM-FC-0：缺口坐标化）——读取单元
    区域为 ``None``（其坐标在 ``Unit.location`` 上）；无法给出坐标的缺口显式
    ``GapCoordinateKind.UNLOCATABLE``，不做静默假设。裁定（是否阻断发布）由
    :mod:`plugins.corpus.preparation.gaps` 依架构 §7.3 表判定，本模块不判。

    ``verdicts`` 是噪声判定的机读依据（票 05）：NOISE 区非空且每条 ``code`` 在
    ``reasons`` 中（I-E1），``observed`` 非空含数值/坐标（I-E2）。
    """

    key: str
    ordinal: int | None
    kind: str
    status: UnitStatus
    reasons: tuple[str, ...]
    clean_view: str | None
    mapping: CleanMapping
    coordinates: GapCoordinates | None = None
    verdicts: tuple[NoiseVerdict, ...] = ()


@dataclass(frozen=True)
class CleanResult:
    """一次确定性保真清洗的结果：``clean_rev`` + 全量区域台账。"""

    clean_rev: str
    regions: tuple[CleanRegion, ...]


def resolve_mapping(mapping: CleanMapping, clean_index: int) -> int | None:
    """把 ``clean_view`` 偏移解析回权威 ``raw_text`` code point 偏移。

    取 ``clean_index`` 之前（含）最近的锚点 ``(cs, rs)``，段内按 1:1 平移
    ``rs + (clean_index - cs)``；无锚点可解析时返回 ``None``。
    """
    resolved: int | None = None
    for cs, rs in mapping:
        if cs > clean_index:
            break
        resolved = rs + (clean_index - cs)
    return resolved


def verify_clean_region(raw_text: str, clean_view: str | None, mapping: CleanMapping) -> None:
    """校验保真不变式；任何破坏抛 :class:`CleanError`。

    - 逐字符：``clean_view[i]`` 必须等于 ``raw_text[resolve(i)]``，或 clean 为空格
      而 raw 为空白（行间补空格映射到换行符的等价类）。
    - 覆盖：``raw_text`` 中每个非空白字符都必须被映射命中——不无记录消失；
      因此 ``clean_view`` 为空串仅当原文不含非空白字符。
    - 顺序（复核 F6）：解析出的 raw 偏移序列必须严格递增——不得重排、不得
      重复映射同一原文偏移。
    """
    if clean_view is None:
        if mapping:
            raise CleanError("clean_view 为空时不得携带 mapping")
        return
    if clean_view == "":
        if mapping:
            raise CleanError("clean_view 为空串时 mapping 必须为空")
        if any(not char.isspace() for char in raw_text):
            raise CleanError("clean_view 为空但原文含非空白字符（不无记录消失）")
        return
    if not mapping or mapping[0][0] != 0:
        raise CleanError("首锚点必须覆盖 clean_index=0")
    previous = -1
    previous_raw = -1
    for cs, rs in mapping:
        if cs <= previous or cs >= len(clean_view) or rs < 0 or rs >= len(raw_text):
            raise CleanError(f"锚点非法: ({cs}, {rs})")
        if rs <= previous_raw:
            raise CleanError(f"锚点 raw 偏移必须严格递增: ({cs}, {rs})")
        previous = cs
        previous_raw = rs
    last_resolved = -1
    for clean_index in range(len(clean_view)):
        raw_index = resolve_mapping(mapping, clean_index)
        if raw_index is None or raw_index >= len(raw_text):
            raise CleanError(f"clean 偏移 {clean_index} 无法解析回原文")
        if raw_index <= last_resolved:
            raise CleanError(
                f"clean 偏移 {clean_index} 解析回 raw 偏移 {raw_index}："
                "raw 偏移必须严格递增（不得重排或重复映射）"
            )
        last_resolved = raw_index
        raw_char = raw_text[raw_index]
        clean_char = clean_view[clean_index]
        if raw_char != clean_char and not (clean_char == " " and raw_char.isspace()):
            raise CleanError(
                f"clean[{clean_index}]={clean_char!r} 与 raw[{raw_index}]={raw_char!r} 不等价"
            )
    resolved = {
        index
        for index in (resolve_mapping(mapping, c) for c in range(len(clean_view)))
        if index is not None
    }
    for raw_index, char in enumerate(raw_text):
        if not char.isspace() and raw_index not in resolved:
            raise CleanError(f"raw 非空白字符偏移 {raw_index}({char!r}) 未被映射覆盖")


def verify_noise_verdicts(regions: tuple[CleanRegion, ...]) -> None:
    """校验票 05 不变量（I-E1/I-E2）；任何破坏抛 :class:`CleanError`。

    - I-E1：任一 ``status is NOISE`` 的区域 ``verdicts`` 非空且每条 ``code`` 在
      ``reasons`` 中（KEPT 区可含"评估过但未越阈值"的近似命中，不受约束）。
    - I-E2：每条 ``verdicts[i].observed`` 非空（含可复核数值/坐标）。
    """
    for region in regions:
        if region.status is UnitStatus.NOISE and not region.verdicts:
            raise CleanError(f"{region.key}: NOISE 区缺少判定依据（I-E1）")
        for verdict in region.verdicts:
            if region.status is UnitStatus.NOISE and verdict.code not in region.reasons:
                raise CleanError(
                    f"{region.key}: verdict code {verdict.code!r} 不在 reasons 中（I-E1）"
                )
            if not verdict.observed:
                raise CleanError(f"{region.key}: verdict observed 为空（I-E2）")


def _is_cjk_char(char: str) -> bool:
    return unicodedata.east_asian_width(char) in ("W", "F")


def _normalized(text: str) -> str:
    return "".join(text.split())


def _norm_heading(text: str) -> str:
    return _normalized(text).rstrip("：:。．.")


def _strip_line(segment: str, base: int) -> list[tuple[str, int]]:
    """折叠行内水平空白：行首/行尾丢弃，内部 run 压成单空格（映射到 run 起点）。"""
    out: list[tuple[str, int]] = []
    index = 0
    while index < len(segment):
        char = segment[index]
        if char.isspace() and char != "\n":
            index += 1
            continue
        out.append((char, base + index))
        index += 1
        if index < len(segment) and segment[index].isspace() and segment[index] != "\n":
            run_end = index
            while (
                run_end < len(segment) and segment[run_end].isspace() and segment[run_end] != "\n"
            ):
                run_end += 1
            if run_end < len(segment):  # 内部 run 压成单空格；行尾 run 直接丢弃
                out.append((" ", base + index))
            index = run_end
    return out


def _clean_pieces(raw_text: str) -> list[tuple[str, int]]:
    """空白投影的逐字符决策序列 ``(clean_char, raw_index)``。"""
    lines: list[list[tuple[str, int]]] = []
    starts: list[int] = []
    cursor = 0
    for segment in raw_text.split("\n"):
        starts.append(cursor)
        lines.append(_strip_line(segment, cursor))
        cursor += len(segment) + 1  # +1 为换行符
    pieces: list[tuple[str, int]] = []
    for line_index, line_pieces in enumerate(lines):
        if not line_pieces:
            continue
        if pieces and not (_is_cjk_char(pieces[-1][0]) and _is_cjk_char(line_pieces[0][0])):
            # 非双侧 CJK 的换行补一个空格，映射到该换行符位置（空白等价类）。
            pieces.append((" ", starts[line_index] - 1))
        pieces.extend(line_pieces)
    return pieces


def _anchors_from(pieces: list[tuple[str, int]]) -> CleanMapping:
    anchors: list[tuple[int, int]] = []
    for clean_index, (_char, raw_index) in enumerate(pieces):
        if clean_index == 0:
            anchors.append((0, raw_index))
            continue
        prev_raw = pieces[clean_index - 1][1]
        if prev_raw != raw_index - 1:  # 原文侧不连续即新锚点（被丢弃的空白在间隙中）
            anchors.append((clean_index, raw_index))
    return tuple(anchors)


def _clean_view_of(unit: CandidateUnit) -> tuple[str, CleanMapping]:
    """保留区的保真视图：代码围栏原样保留，其余做空白投影；自校验 fail-closed。"""
    if "code_fence" in unit.reasons:
        clean_view = unit.raw_text
        mapping: CleanMapping = ((0, 0),) if clean_view else ()
        verify_clean_region(unit.raw_text, clean_view, mapping)
        return clean_view, mapping
    pieces = _clean_pieces(unit.raw_text)
    clean_view = "".join(char for char, _raw in pieces)
    mapping = _anchors_from(pieces)
    verify_clean_region(unit.raw_text, clean_view, mapping)
    return clean_view, mapping


def _repeated_page_counts(units: list[CandidateUnit]) -> dict[str, int]:
    pages: dict[str, set[int]] = {}
    for unit in units:
        page = unit.location.page
        if page is None or unit.location.bbox is None:
            continue
        pages.setdefault(_normalized(unit.raw_text), set()).add(page)
    return {norm: len(seen) for norm, seen in pages.items()}


def _page_bands(units: list[CandidateUnit]) -> dict[int, tuple[float, float]]:
    """每页顶/底带边界 ``(top_bound, bottom_bound)``；内容高不足时不设带。"""
    tops: dict[int, list[float]] = {}
    bottoms: dict[int, list[float]] = {}
    for unit in units:
        page = unit.location.page
        bbox = unit.location.bbox
        if page is None or bbox is None:
            continue
        tops.setdefault(page, []).append(bbox[1])
        bottoms.setdefault(page, []).append(bbox[3])
    bands: dict[int, tuple[float, float]] = {}
    for page in tops:
        t_min = min(tops[page])
        b_max = max(bottoms[page])
        height = b_max - t_min
        if height <= 0:
            continue
        bands[page] = (t_min + _BAND_RATIO * height, b_max - _BAND_RATIO * height)
    return bands


def _banded_noise(unit: CandidateUnit, bands: dict[int, tuple[float, float]]) -> str | None:
    page = unit.location.page
    bbox = unit.location.bbox
    if page is None or bbox is None or page not in bands:
        return None
    top_bound, bottom_bound = bands[page]
    if bbox[3] <= top_bound:
        return _NOISE_HEADER
    if bbox[1] >= bottom_bound:
        return _NOISE_FOOTER
    return None


def _toc_noise(unit: CandidateUnit) -> str | None:
    if unit.kind in _HEADING_KINDS and _norm_heading(unit.raw_text) in _TOC_EXACT:
        return _NOISE_TOC_HEADING
    lines = [line for line in unit.raw_text.splitlines() if line.strip()]
    leaders = sum(1 for line in lines if _TOC_LEADER.search(line))
    if leaders >= 2:
        return _NOISE_TOC_LEADERS
    return None


def _is_analyst_roster(raw_text: str) -> bool:
    lines = [line for line in raw_text.splitlines() if line.strip()]
    role_lines = sum(1 for line in lines if _ROLE_LINE.search(line))
    cert_lines = sum(1 for line in lines if _CERT_PATTERN.search(line))
    return role_lines >= 2 or (role_lines >= 1 and cert_lines >= 1)


def _band_verdict(
    code: str, unit: CandidateUnit, repeat_pages: int, bands: dict[int, tuple[float, float]]
) -> NoiseVerdict:
    """页眉/页脚带判定的机读依据（含低于 ``_REPEAT_MIN_PAGES`` 的近似命中）。"""
    assert unit.location.page is not None and unit.location.bbox is not None
    top_bound, bottom_bound = bands[unit.location.page]
    return NoiseVerdict(
        code=code,
        rule="banded_repeated_geometric",
        observed={
            "repeat_pages": repeat_pages,
            "page": unit.location.page,
            "bbox": unit.location.bbox,
            "top_bound": top_bound,
            "bottom_bound": bottom_bound,
        },
        threshold={"min_pages": _REPEAT_MIN_PAGES, "band_ratio": _BAND_RATIO},
    )


def _toc_verdict(code: str, unit: CandidateUnit) -> NoiseVerdict:
    if code == _NOISE_TOC_HEADING:
        return NoiseVerdict(
            code=code,
            rule="exact_toc_heading",
            observed={
                "heading": unit.raw_text,
                "kind": unit.kind,
                "line_count": sum(1 for line in unit.raw_text.splitlines() if line.strip()),
            },
            threshold={"exact_headings": sorted(_TOC_EXACT)},
        )
    lines = [line for line in unit.raw_text.splitlines() if line.strip()]
    leaders = sum(1 for line in lines if _TOC_LEADER.search(line))
    return NoiseVerdict(
        code=code,
        rule="dot_leader_lines",
        observed={"leader_lines": leaders, "nonempty_lines": len(lines)},
        threshold={"min_leader_lines": 2},
    )


def _roster_verdict(unit: CandidateUnit) -> NoiseVerdict:
    lines = [line for line in unit.raw_text.splitlines() if line.strip()]
    role_lines = sum(1 for line in lines if _ROLE_LINE.search(line))
    cert_lines = sum(1 for line in lines if _CERT_PATTERN.search(line))
    return NoiseVerdict(
        code=_NOISE_ROSTER,
        rule="analyst_roster_lines",
        observed={"role_lines": role_lines, "cert_lines": cert_lines},
        threshold={"min_role_lines": 2, "min_role_with_cert": (1, 1)},
    )


def _disclaimer_heading_verdict(unit: CandidateUnit) -> NoiseVerdict:
    return NoiseVerdict(
        code=_NOISE_DISCLAIMER_HEADING,
        rule="disclaimer_heading_exact",
        observed={
            "heading": unit.raw_text,
            "kind": unit.kind,
            "line_count": sum(1 for line in unit.raw_text.splitlines() if line.strip()),
        },
        threshold={"disclaimer_headings": sorted(_DISCLAIMER_HEADINGS)},
    )


def _disclaimer_section_verdict(origin: tuple[int, str]) -> NoiseVerdict:
    return NoiseVerdict(
        code=_NOISE_DISCLAIMER_SECTION,
        rule="disclaimer_section_after_heading",
        observed={"origin_ordinal": origin[0], "origin_heading": origin[1]},
        threshold={"disclaimer_headings": sorted(_DISCLAIMER_HEADINGS)},
    )


def _disclaimer_prefix_verdict(unit: CandidateUnit) -> NoiseVerdict:
    return NoiseVerdict(
        code=_NOISE_DISCLAIMER_PREFIX,
        rule="disclaimer_prefix_paragraph",
        observed={"prefix": _normalized(unit.raw_text)[:16], "start_index": 0},
        threshold={"prefixes": sorted(_DISCLAIMER_PREFIXES)},
    )


def _has_numeric_fact_sentence(raw_text: str) -> bool:
    """免责节单元是否含『可复核数字事实句』（票 08 三类命中，I-E3 判据）。

    命中任一即视为承载可复核事实：① 持股百分比『持有…X%的股份/股权/持股/股本』；
    ② 6 位证券代码（如 600519）；③ 带量词货币金额（X元/X亿元）。区域含此类句子
    时不整段剔除、降 KEPT，避免吞掉实质事实句。
    """
    return bool(
        _NUMERIC_STAKE.search(raw_text)
        or _STOCK_CODE.search(raw_text)
        or _MONEY_AMOUNT.search(raw_text)
    )


def _disclaimer_fact_keep_verdict(origin: tuple[int, str], raw_text: str) -> NoiseVerdict:
    """免责节含事实句、降 KEPT 的机读留痕（区域为 KEPT，code 不要求入 reasons）。"""
    return NoiseVerdict(
        code=_NOISE_DISCLAIMER_SECTION,
        rule="disclaimer_section_numeric_fact_keep",
        observed={
            "origin_ordinal": origin[0],
            "origin_heading": origin[1],
            "fact_markers": {
                "stake": bool(_NUMERIC_STAKE.search(raw_text)),
                "stock_code": bool(_STOCK_CODE.search(raw_text)),
                "money": bool(_MONEY_AMOUNT.search(raw_text)),
            },
        },
        threshold={"disclaimer_headings": sorted(_DISCLAIMER_HEADINGS)},
    )


def _region_from_unit(
    unit: CandidateUnit,
    status: UnitStatus,
    reasons: tuple[str, ...],
    verdicts: tuple[NoiseVerdict, ...] = (),
) -> CleanRegion:
    if status is not UnitStatus.KEPT:
        return CleanRegion(
            key=f"unit:{unit.ordinal}",
            ordinal=unit.ordinal,
            kind=unit.kind,
            status=status,
            reasons=reasons,
            clean_view=None,
            mapping=(),
            verdicts=verdicts,
        )
    clean_view, mapping = _clean_view_of(unit)
    return CleanRegion(
        key=f"unit:{unit.ordinal}",
        ordinal=unit.ordinal,
        kind=unit.kind,
        status=UnitStatus.KEPT,
        reasons=reasons,
        clean_view=clean_view,
        mapping=mapping,
        verdicts=verdicts,
    )


def _synthetic_regions(issues: tuple[ReaderIssue, ...]) -> tuple[CleanRegion, ...]:
    regions: list[CleanRegion] = []
    seen: set[str] = set()
    for issue in issues:
        status = _SYNTHETIC_ISSUE_STATUS.get(issue.code)
        if status is None:
            continue  # 该缺口已由读取单元的状态/原因承载，不重复立区
        key = gap_key(issue.code, issue.location)
        if key in seen:
            continue
        seen.add(key)
        coordinates = parse_gap_location(issue.location)
        # I-E1/I-E2：NOISE 合成区（当前仅 image_region_small）也须带机读依据。
        verdicts = (
            (
                NoiseVerdict(
                    code=issue.code,
                    rule="synthetic_gap_noise",
                    observed={**coordinates.as_payload(), "location": issue.location},
                    threshold={"gap_policy_rev": GAP_POLICY_REV},
                ),
            )
            if status is UnitStatus.NOISE
            else ()
        )
        regions.append(
            CleanRegion(
                key=key,
                ordinal=None,
                kind="gap",
                status=status,
                reasons=(issue.code,),
                clean_view=None,
                mapping=(),
                coordinates=coordinates,
                verdicts=verdicts,
            )
        )
    return tuple(regions)


def clean_reader_result(result: ReaderResult) -> CleanResult:
    """对读取结果做保真清洗：噪声判定 + 空白投影 + 全量区域台账。"""
    units = sorted(result.units, key=lambda unit: unit.ordinal)
    repeated = _repeated_page_counts(units)
    bands = _page_bands(units)
    regions: list[CleanRegion] = []
    in_disclaimer = False
    disclaimer_origin: tuple[int, str] | None = None
    for unit in units:
        is_heading = unit.kind in _HEADING_KINDS
        heading_is_disclaimer = is_heading and _norm_heading(unit.raw_text) in _DISCLAIMER_HEADINGS
        if is_heading:
            in_disclaimer = heading_is_disclaimer
            disclaimer_origin = (unit.ordinal, unit.raw_text) if heading_is_disclaimer else None
        if unit.status is not UnitStatus.KEPT:
            # 读取器已判复核/OCR 的区域原状态继承，不做投影、不升级为保留。
            regions.append(_region_from_unit(unit, unit.status, tuple(unit.reasons)))
            continue
        noise: list[str] = []
        verdicts: list[NoiseVerdict] = []
        banded = _banded_noise(unit, bands)
        if banded is not None:
            repeat_pages = repeated.get(_normalized(unit.raw_text), 0)
            verdicts.append(_band_verdict(banded, unit, repeat_pages, bands))
            if repeat_pages >= _REPEAT_MIN_PAGES:
                noise.append(banded)
        if is_heading and heading_is_disclaimer:
            noise.append(_NOISE_DISCLAIMER_HEADING)
            verdicts.append(_disclaimer_heading_verdict(unit))
        elif in_disclaimer:
            assert disclaimer_origin is not None  # in_disclaimer 只能由免责声明标题置位
            if _has_numeric_fact_sentence(unit.raw_text):
                # 票 08（I-E3）：免责节单元含『可复核数字事实句』→ 整段降 KEPT 保事实，
                # 不整段剔除。区域为 KEPT，verdict 留痕为『已评估免责节但含事实句』。
                verdicts.append(_disclaimer_fact_keep_verdict(disclaimer_origin, unit.raw_text))
            else:
                noise.append(_NOISE_DISCLAIMER_SECTION)
                verdicts.append(_disclaimer_section_verdict(disclaimer_origin))
        toc = _toc_noise(unit)
        if toc is not None:
            noise.append(toc)
            verdicts.append(_toc_verdict(toc, unit))
        if _is_analyst_roster(unit.raw_text):
            noise.append(_NOISE_ROSTER)
            verdicts.append(_roster_verdict(unit))
        if unit.kind == "paragraph" and _normalized(unit.raw_text).startswith(_DISCLAIMER_PREFIXES):
            noise.append(_NOISE_DISCLAIMER_PREFIX)
            verdicts.append(_disclaimer_prefix_verdict(unit))
        status = UnitStatus.NOISE if noise else UnitStatus.KEPT
        if status is UnitStatus.NOISE:
            # I-E1：NOISE 区只保留已触发（code ∈ noise）的判定；近命中仅在 KEPT 区记账。
            verdicts = [v for v in verdicts if v.code in noise]
        reasons = (*unit.reasons, *noise)
        regions.append(_region_from_unit(unit, status, reasons, verdicts=tuple(verdicts)))
    full_regions = (*regions, *_synthetic_regions(result.issues))
    verify_noise_verdicts(full_regions)
    return CleanResult(
        clean_rev=CLEAN_REV,
        regions=full_regions,
    )
