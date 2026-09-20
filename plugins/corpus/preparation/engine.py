"""全链编排引擎（任务 I1-7，架构 v1.1 §9 + §4.1 + §8.1 + §5.2）。

公开编排 Interface 收敛为 ``plan → execute → publish``（架构 §9），内部处理全部
阶段与恢复，CLI 不自行复制逻辑；本模块只编排，不新增业务规则（准入判定在
I1-5，存储所有权/幂等在 repository，清洗/切块规则在各自模块）。纯标准库编排，
无模型调用、无网络/PG 连接；I1 仅测试暂存/内存登记。

端到端不变式（full-review §6）：

1. 每个阶段输出明确成功/失败/待复核/可恢复状态，后继消费状态而非仅消费 payload：
   ``registered=False`` 终止后续阶段；SUCCEEDED 短路由检查点驱动。
2. 审核与范围是构建约束（C2）：locator 解析为可验区间，unit 标 out_of_scope，
   chunk/上下文投影受限；无法解释的 scope 拒绝（不降级为全篇）。
3. 撤销资格不依赖全文解析成功（C4）：绑定同源哈希、链解析干净的明确排除走
   免探查快路径；需探查的未知材料继续做受控解析。
4. 发布不允许无 job/no-check 的备用路径（C1）：幂等重放短路 → VERIFIED 校验
   （缺口裁决/oversized/阶段 SUCCEEDED/scope 闭合）→ PUBLISHED job 租约 →
   store.publish(owner/token)。generation/token/当前审核各司其职。
   缺口按 §7.3 裁决（RM-FC-0）：``blocking`` 拒绝，``acknowledged``/可证范围外
   允许但保持可见。
5. 执行协议管理实际工作、可验证检查点、取消和时钟（C6）：解析检查点按来源
   键控；先读有效检查点再决定重算；心跳/取消/逐阶段时钟接入。
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from plugins.corpus.preparation.admission import (
    AdmissionPolicy,
    ProbeInput,
    SourceDescriptor,
    decide_admission,
    decide_exclusion_without_probe,
    probe_features,
    resolve_review_chain,
)
from plugins.corpus.preparation.chunk import CHUNK_REV, ChunkResult, chunk_clean_result
from plugins.corpus.preparation.clean import (
    CLEAN_REV,
    CleanRegion,
    CleanResult,
    clean_reader_result,
)
from plugins.corpus.preparation.contract import (
    Admission,
    AdmissionDecision,
    AdmissionReasonCode,
    Build,
    CharSpan,
    Chunk,
    DocumentFormat,
    Job,
    JobStage,
    JobState,
    LeaseConfig,
    MetadataSnapshot,
    Publication,
    ResearchDomain,
    ReviewDecision,
    ReviewedDecision,
    Source,
    Unit,
    UnitLocation,
    UnitStatus,
    canonical_fingerprint,
    compute_build_id,
)
from plugins.corpus.preparation.gaps import (
    GAP_POLICY_REV,
    GapRecord,
    acknowledged_gaps,
    blocking_gaps,
    evaluate_against_scope,
    gap_records,
)
from plugins.corpus.preparation.publication import probe_report_publication
from plugins.corpus.preparation.readers import extractor_rev_for, read_document
from plugins.corpus.preparation.readers.base import (
    CandidateUnit,
    ReaderIssue,
    ReaderResult,
    detect_format,
)
from plugins.corpus.preparation.repository import Store, StoreError
from plugins.corpus.preparation.source import IngestLimits, ingest_source

ENGINE_REV = "engine-1"
PARSE_RULE_REV = "parse-2"
# I2-3 定稿（design-review C13）：index_rev = 分词配置版本（zhcfg：zhparser 解析器
# + zhcfg 全词性→simple 映射，须含 'm' 数词，否则 "47.3亿" 类数字被丢弃）+ 索引文本
# 生成规则（= chunk.normalize_search_text，写入 search_text 前的规范化）的组合版本。
#
# RM-10：索引文本规则**由 index_rev 独立表达**，不随 chunk_rev 绑定——
# chunk_rev 描述「哪些单元组成一个块」（切块规则），normalize_search_text 描述
# 「块文本如何变成可检索文本」（索引文本规则）；前者改变块边界，后者只改变
# token 形态，二者影响面不同，不应共用一个版本号。故 search_text 规则变更只升
# index_rev，chunk_rev 保持 chunk-2（避免无谓的全量重建）。
# R5（2026-09-17）：search_text 规范化由仅 ASCII % 扩展为 % 与全角 ％，
# 属索引文本规则变更，index_rev 由 index-2-zhcfg-2 升为 index-3-zhcfg-2。
# zhcfg 或文本规则任一升级必须换用新 index_rev，禁止同名配置原地沿用旧版本；
# index_rev 进入 build_id，升级即全量重建（新 build 重算 search_tsv/GIN）。
# 票 04（结构标签入索引文本）：search_text 规则变更只升 index_rev，
# index-3-zhcfg-2 -> index-4-zhcfg-2（表格块注入行/列标签，I-B1）。
INDEX_REV_V3 = "index-4-zhcfg-2"

_TITLE_KINDS = frozenset({"heading", "title"})
# source 级解析检查点阶段名（与 store 检查点键控一致；非 JobStage）。
_PARSE_CHECKPOINT_STAGE = "parse"

# 发布租约默认配置（复用 §8.1 四项；engine.publish_build 缺省时使用）。
DEFAULT_LEASE = LeaseConfig(300, 60, 600, 3)


class EngineError(ValueError):
    """编排输入非法或阶段前置不满足（fail-closed：不猜测、不降级、不覆盖）。"""


class EngineCancelled(EngineError):
    """执行被 cancel_check 取消，阻断一切后继阶段（取消不是成功的空结果）。

    已创建 build 的阶段会提交 ``CANCELLED``；准入前的解析取消则不创建一个并不
    存在的 build/job。
    """


class _CancelledError(Exception):
    """内部取消信号：由 cancel_check 回调抛出，engine 统一捕获并提交 CANCELLED，
    再重抛 :class:`EngineCancelled`（取消对调用方必须可见，不静默 return）。"""


@dataclass(frozen=True)
class PlanEntry:
    """显式清单条目（冻结清单由调用方逐条给出；路径/标题不是批准凭证）。"""

    path: str
    original_name: str | None = None
    domain_hint: ResearchDomain | None = None  # 登记元数据，非批准凭证
    review_decision_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class PlannedSource:
    """通过清单校验的条目：格式/大小在 plan 阶段确定（只读，不写任何状态）。"""

    path: str
    original_name: str
    domain_hint: ResearchDomain | None
    review_decision_ids: tuple[str, ...]
    format: DocumentFormat
    size_bytes: int


@dataclass(frozen=True)
class BuildPlan:
    """一次编排计划：校验后的显式清单 + 政策版本（预计工作量 = 条目与字节量）。"""

    entries: tuple[PlannedSource, ...]
    policy_rev: str


@dataclass(frozen=True)
class ExecuteOutcome:
    """单条来源的全链执行结果（build 仅在 in_scope 时存在）。"""

    original_name: str
    source: Source
    admission: Admission
    build: Build | None
    unit_count: int
    chunk_count: int
    source_reused: bool  # store 已有同源登记（幂等重放/改名重收）
    archive_reused: bool  # 内容寻址对象已存在且核验一致（重复执行）


@dataclass(frozen=True)
class ExecuteReport:
    """一次 execute_builds 的全部结果。"""

    outcomes: tuple[ExecuteOutcome, ...]


def plan_builds(
    entries: Iterable[PlanEntry],
    *,
    policy: AdmissionPolicy,
    limits: IngestLimits | None = None,
) -> BuildPlan:
    """校验显式清单（格式/非空/大小上限）；只读不写，无模型无 PG（§9 corpus-plan）。"""
    bounds = limits if limits is not None else IngestLimits()
    planned: list[PlannedSource] = []
    for entry in entries:
        path = Path(entry.path)
        fmt, detected = detect_format(path)
        size = detected.stat().st_size
        if size == 0:
            raise EngineError(f"清单来源为空文件: {path.name}")
        if size > bounds.max_bytes:
            raise EngineError(
                f"清单来源超过大小上限 {bounds.max_bytes} 字节: {path.name}（{size} 字节）"
            )
        planned.append(
            PlannedSource(
                path=str(path),
                original_name=entry.original_name if entry.original_name else path.name,
                domain_hint=entry.domain_hint,
                review_decision_ids=entry.review_decision_ids,
                format=fmt,
                size_bytes=size,
            )
        )
    return BuildPlan(entries=tuple(planned), policy_rev=policy.policy_rev)


def _probe_input(descriptor: SourceDescriptor, result: ReaderResult) -> ProbeInput:
    """从解析结果装配准入探查输入（标题=文件名+标题候选；探查上限由 probe 内置）。"""
    units = sorted(result.units, key=lambda unit: unit.ordinal)
    headings = [unit.raw_text for unit in units if unit.kind in _TITLE_KINDS]
    title = " ".join([descriptor.title, *headings[:3]])
    head_units = [unit for unit in units if unit.location.page is None or unit.location.page <= 1][
        :10
    ]
    return ProbeInput(
        title=title,
        head_text="\n".join(unit.raw_text for unit in head_units),
        body_lines=tuple(line for unit in units for line in unit.raw_text.splitlines()),
        heading_texts=tuple(headings),
    )


# --- C2：scope 解析（locator → 可验区间；无法解释拒绝，不降级全篇） ---


@dataclass(frozen=True)
class _ScopeRange:
    """解析后的可验批准区间（code point 偏移，闭开区间 ``[start, end)``）。"""

    start: int
    end: int
    raw: str  # 原始 locator（审计可追溯）


def _parse_scope_ref(scope_ref: str | None) -> tuple[_ScopeRange, ...]:
    """解析审核 locator 为可验 code point 区间（full-review C2）。

    支持的语法：``char:<start>-<end>``（闭开区间，对齐 MD raw_text 切片）。
    未知前缀/格式非法/范围空 → 拒绝（EngineError，不降级为全篇）。
    """
    # ``None`` is the only spelling for an unrestricted admission.  In
    # particular, an empty/whitespace-only locator is an attempted scoped
    # admission with no verifiable interval, not an invitation to publish the
    # entire source.
    if scope_ref is None:
        return ()
    ranges: list[_ScopeRange] = []
    for part in scope_ref.split(","):
        token = part.strip()
        if not token:
            continue
        prefix, _, rest = token.partition(":")
        if prefix != "char":
            raise EngineError(
                f"scope locator 不支持的前缀 {prefix!r}（仅支持 char:；fail-closed，不降级全篇）"
            )
        start_str, _, end_str = rest.partition("-")
        try:
            start = int(start_str)
            end = int(end_str)
        except ValueError as exc:
            raise EngineError(f"scope locator 坐标非法: {token!r}（{exc}）") from exc
        if start < 0 or end <= start:
            raise EngineError(f"scope locator 区间非法: {token!r}（需要 0 ≤ start < end）")
        ranges.append(_ScopeRange(start=start, end=end, raw=token))
    if not ranges:
        raise EngineError("scope locator 未包含任何有效 char 区间（fail-closed，不降级为全篇）")
    return tuple(ranges)


def _span_in_scope(
    span: CharSpan | None,
    scope: tuple[_ScopeRange, ...],
) -> tuple[bool, str | None]:
    """判定坐标区间是否落在批准范围内（full-review C2）。

    - 无坐标：不可验，记 ``scope_unverifiable_no_coordinates``，范围外。
    - 部分重叠：记 ``out_of_scope_partial_overlap``，范围外（宁可少保留，不越权）。
    - 完全在任一区间外：记 ``out_of_scope_outside_approved_range``，范围外。
    - 完全包含于任一区间：in-scope，保留。
    """
    if not scope:
        return True, None  # 无 scope 约束：全部保留
    if span is None or span.end <= span.start:
        return False, "scope_unverifiable_no_coordinates"
    for rng in scope:
        if span.start >= rng.start and span.end <= rng.end:
            return True, None
        if span.start < rng.end and span.end > rng.start:
            return False, "out_of_scope_partial_overlap"
    return False, "out_of_scope_outside_approved_range"


def _apply_scope_to_clean(
    reader_result: ReaderResult,
    clean: CleanResult,
    scope: tuple[_ScopeRange, ...],
) -> CleanResult:
    """把 scope 约束作用到 **clean 层**（full-review C2 的关键落点）。

    chunker 的输入是 clean 而非 Unit——只把 Unit 标 out_of_scope 拦不住范围外
    文本进入检索块（chunk_clean_result 消费的是 clean 保留区）。因此 scope 必须
    在 chunk 之前作用于 clean：范围外/无坐标/部分重叠区域 ``status→OUT_OF_SCOPE``、
    ``clean_view=None``、``mapping=()``（raw_text 经单元保持权威可回溯）。

    - 合成缺口区域（``ordinal=None``）保留原样：缺口坐标与 scope 归属由
      :func:`gap_records_of` 在发布门按架构 §7.3 裁决，不在此静默丢弃、也不在此
      直接判阻断（RM-FC-0：缺口记账与发布阻断分离）。
    - scope 存在但零 in-scope 保留区域 → EngineError：空 build 非法，fail-closed，
      不降级为全篇构建。
    """
    if not scope:
        return clean
    span_by_ordinal = {unit.ordinal: unit.location.char_span for unit in reader_result.units}
    kept_in_scope = 0
    regions: list[CleanRegion] = []
    for region in clean.regions:
        if region.ordinal is None:
            regions.append(region)  # 合成缺口区域：坐标保留，交发布门裁决
            continue
        in_scope, reason = _span_in_scope(span_by_ordinal.get(region.ordinal), scope)
        if in_scope:
            if region.status is UnitStatus.KEPT and region.clean_view:
                kept_in_scope += 1
            regions.append(region)
            continue
        if reason == "out_of_scope_partial_overlap":
            # A chunk is a structural unit.  Dropping an overlapping unit
            # would keep the publication within scope but silently lose
            # approved text, so reject this unsupported scope rather than
            # claim complete scoped processing.
            raise EngineError(
                "scope 区间未与读取单元边界对齐（包含部分批准文本）；拒绝自动缩小批准范围"
            )
        if reason is None:  # pragma: no cover - _span_in_scope 范围外必给原因
            regions.append(region)
            continue
        regions.append(
            replace(
                region,
                status=UnitStatus.OUT_OF_SCOPE,
                reasons=(*region.reasons, reason),
                clean_view=None,
                mapping=(),
            )
        )
    if kept_in_scope == 0:
        raise EngineError(
            "scope 约束使全部保留区域 out_of_scope（空 build 非法，fail-closed，"
            "不降级为全篇构建）；检查 scope_ref 与实际内容的坐标区间是否匹配"
        )
    return CleanResult(clean_rev=clean.clean_rev, regions=tuple(regions))


def _units_of(
    build_id: str,
    reader_result: ReaderResult,
    clean: CleanResult,
) -> list[Unit]:
    """把读取单元 + 清洗台账装配为契约 ``Unit``（raw_text 权威 + 清洗投影字段）。

    ``clean`` 必须已过 :func:`_apply_scope_to_clean`（C2：scope 在 chunk 之前
    作用于 clean 层）；单元状态直接继承区域状态（含 OUT_OF_SCOPE），
    chunk 阶段按 status=KEPT 过滤，检索/证据范围受批准区间限制。
    """
    region_by_ordinal = {
        region.ordinal: region for region in clean.regions if region.ordinal is not None
    }
    units: list[Unit] = []
    for candidate in sorted(reader_result.units, key=lambda unit: unit.ordinal):
        region = region_by_ordinal.get(candidate.ordinal)
        if region is None:
            raise EngineError(
                f"读取单元 {candidate.ordinal} 缺少清洗台账记录（每来源区域必须有状态）"
            )
        units.append(
            Unit(
                unit_id=f"unit:{candidate.ordinal:04d}",
                build_id=build_id,
                kind=region.kind,
                raw_text=candidate.raw_text,
                content_hash=candidate.content_hash,
                ordinal=candidate.ordinal,
                location=candidate.location,
                clean_view=region.clean_view,
                mapping=region.mapping,
                status=region.status,
                reasons=region.reasons,
            )
        )
    return units


def _chunks_of(
    build_id: str,
    chunk_result: ChunkResult,
    unit_id_by_ordinal: dict[int, str],
    unit_char_spans: dict[int, CharSpan | None],
) -> list[Chunk]:
    """把候选块装配为契约 ``Chunk``（引用只能指向本 build 真实单元）。

    复核 R4 + full-review §6：``context_refs``（引用式表头/问题关联）与
    ``unit_refs``（核心内容）在契约层各司其职——``unit_refs`` 保持合并超集
    以兼容旧消费者（旧测试断言 chunk.unit_refs 含全部相关单元），``context_refs``
    标注其中承担关联角色的子集（引用内容不因此从台账消失）。
    C2：``source_ranges`` 装配成员单元 char_span（可验坐标存在时），检索/证据
    范围受批准区间限制（chunk 输入的 clean 已 scoped，范围外单元不成为成员）。
    """
    chunks: list[Chunk] = []
    for candidate in chunk_result.chunks:
        try:
            unit_refs = tuple(
                dict.fromkeys(
                    unit_id_by_ordinal[ordinal]
                    for ordinal in (*candidate.unit_ordinals, *candidate.context_refs)
                )
            )
        except KeyError as exc:
            raise EngineError(f"候选块 {candidate.key} 引用了不存在的单元: {exc}") from exc
        context_ref_ids = (
            {unit_id_by_ordinal[ordinal] for ordinal in candidate.context_refs}
            if candidate.context_refs
            else set()
        )
        source_ranges: list[CharSpan] = []
        for ordinal in candidate.unit_ordinals:
            span = unit_char_spans.get(ordinal)
            if span is not None:
                source_ranges.append(span)
        chunks.append(
            Chunk(
                chunk_id=f"{build_id[:16]}:{candidate.key}",
                build_id=build_id,
                kind=candidate.kind,
                unit_refs=unit_refs,
                search_text=candidate.search_text,
                title_text=candidate.title_text,
                section_path=candidate.section_path,
                source_ranges=tuple(dict.fromkeys(source_ranges)),
                context_refs=tuple(ref for ref in unit_refs if ref in context_ref_ids)
                if context_ref_ids
                else (),
            )
        )
    return chunks


def _quality_report(build_id: str, clean: CleanResult, chunk_result: ChunkResult) -> str:
    """确定性质量台账：合成缺口区域 + 超长不可分块清单（审计可见，不静默）。"""
    payload = {
        "gap_regions": sorted(region.key for region in clean.regions if region.ordinal is None),
        "oversized_chunks": sorted(
            f"{build_id[:16]}:{candidate.key}"
            for candidate in chunk_result.chunks
            if candidate.review_reasons
        ),
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


# --- C6：解析检查点（按 source 键控；先读有效检查点再决定重算） ---


def _serialize_parse_checkpoint(
    source_id: str,
    reader_result: ReaderResult,
    extractor_rev: str,
    unit_hashes: tuple[str, ...],
    *,
    reparse_reason: str | None = None,
) -> str:
    """序列化解析检查点（值由 store 持有，键为 ``(source_id, "parse")``）。

    检查点记录：parse_rule_rev + source_id + extractor_rev + 逐单元 content_hash +
    reader units 的精简投影（ordinal/kind/raw_text/坐标 + bbox + cells + label_path）。
    引擎据此校验当前代码对该格式会产出的 extractor_rev 是否与检查点一致——不一致
    即不可复用。

    C6 保真：``bbox``（4 元组）、``cells`` 与 ``label_path`` 序列化必须完整——
    否则 PDF 恢复后 clean 结果漂移（同一 reader_result 走 clean 应得到同
    clean_rev），检查点重放复用的 ReaderResult 与原解析逐字段等价。
    ``reparse_reason`` 记录本次重算原因（检查点缺失/损坏/版本不匹配等，审计可追溯）。
    """
    payload = {
        "checkpoint_schema_rev": "parse-checkpoint-2",
        "parse_rule_rev": PARSE_RULE_REV,
        "source_id": source_id,
        "extractor_rev": extractor_rev,
        "unit_hashes": list(unit_hashes),
        "reparse_reason": reparse_reason,
        "units": [
            {
                "ordinal": u.ordinal,
                "kind": u.kind,
                "raw_text": u.raw_text,
                "status": u.status.value,
                "reasons": list(u.reasons),
                "page": u.location.page,
                "element": u.location.element,
                "char_start": u.location.char_span.start if u.location.char_span else None,
                "char_end": u.location.char_span.end if u.location.char_span else None,
                "bbox": list(u.location.bbox) if u.location.bbox else None,
                "cells": [list(cell) for cell in u.location.cells] if u.location.cells else None,
                "label_path": list(u.location.label_path) if u.location.label_path else None,
            }
            for u in reader_result.units
        ],
        "issues": [
            {"code": i.code, "location": i.location, "detail": i.detail}
            for i in reader_result.issues
        ],
        "format": reader_result.format.value,
        "source_path": reader_result.source_path,
        "page_count": reader_result.page_count,
    }
    # ``unit_hashes`` only protects raw text.  The replay result also depends
    # on statuses, locations, issues and document metadata, so bind the whole
    # normalized payload before it leaves this trusted producer.
    payload["payload_hash"] = canonical_fingerprint(payload)
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _validate_parse_checkpoint(
    checkpoint: str | None,
    source_id: str,
    expected_extractor_rev: str,
) -> tuple[ReaderResult | None, str | None]:
    """校验解析检查点：返回 ``(可复用 ReaderResult | None, 重算原因 | None)``。

    - 检查点不存在 → ``(None, "checkpoint_absent")``：首次解析。
    - extractor_rev 不匹配 → ``(None, "extractor_rev_mismatch")``：读取器升级，重算。
    - parse_rule_rev/source_id 不匹配 → ``(None, "rule_or_source_mismatch")``。
    - 内容哈希不一致 → ``(None, "content_hash_mismatch")``：源或解析结果变化。
    - 全部通过 → ``(ReaderResult, None)``：复用检查点内的解析结果。
    """
    if checkpoint is None:
        return None, "checkpoint_absent"
    try:
        data = json.loads(checkpoint)
    except json.JSONDecodeError:
        return None, "checkpoint_corrupt"
    if not isinstance(data, dict):
        return None, "checkpoint_corrupt"
    if data.get("checkpoint_schema_rev") != "parse-checkpoint-2":
        return None, "checkpoint_schema_mismatch"
    payload_hash = data.pop("payload_hash", None)
    if not isinstance(payload_hash, str) or payload_hash != canonical_fingerprint(data):
        return None, "checkpoint_payload_hash_mismatch"
    if data.get("parse_rule_rev") != PARSE_RULE_REV:
        return None, "rule_or_source_mismatch"
    if data.get("source_id") != source_id:
        return None, "rule_or_source_mismatch"
    if data.get("extractor_rev") != expected_extractor_rev:
        return None, "extractor_rev_mismatch"
    unit_hashes = data.get("unit_hashes")
    if not isinstance(unit_hashes, list):
        return None, "checkpoint_corrupt"
    units_data = data.get("units")
    if not isinstance(units_data, list):
        return None, "checkpoint_corrupt"
    units: list[CandidateUnit] = []
    for entry in units_data:
        if not isinstance(entry, dict):
            return None, "checkpoint_corrupt"
        try:
            ordinal = int(entry["ordinal"])
            raw_text = str(entry["raw_text"])
        except (KeyError, ValueError, TypeError):
            return None, "checkpoint_corrupt"
        kind = str(entry.get("kind", "unknown"))
        status = UnitStatus(str(entry.get("status", "kept")))
        reasons = tuple(str(r) for r in entry.get("reasons", []))
        page = entry.get("page")
        element = entry.get("element")
        cs = entry.get("char_start")
        ce = entry.get("char_end")
        char_span = (
            CharSpan(start=int(cs), end=int(ce)) if cs is not None and ce is not None else None
        )
        # C6 保真：bbox/cells/label_path 必须完整恢复，否则 PDF 恢复后 clean 结果漂移。
        bbox_raw = entry.get("bbox")
        bbox: tuple[float, float, float, float] | None = None
        if bbox_raw is not None:
            if not isinstance(bbox_raw, list) or len(bbox_raw) != 4:
                return None, "checkpoint_corrupt"
            try:
                bbox = (
                    float(bbox_raw[0]),
                    float(bbox_raw[1]),
                    float(bbox_raw[2]),
                    float(bbox_raw[3]),
                )
            except (TypeError, ValueError):
                return None, "checkpoint_corrupt"
        cells_raw = entry.get("cells")
        cells: tuple[tuple[int, int], ...] = ()
        if cells_raw is not None:
            if not isinstance(cells_raw, list):
                return None, "checkpoint_corrupt"
            try:
                cells = tuple((int(cell[0]), int(cell[1])) for cell in cells_raw)
            except (TypeError, ValueError, IndexError):
                return None, "checkpoint_corrupt"
        label_path_raw = entry.get("label_path")
        label_path: tuple[str, ...] = ()
        if label_path_raw is not None:
            if not isinstance(label_path_raw, list) or not all(
                isinstance(item, str) for item in label_path_raw
            ):
                return None, "checkpoint_corrupt"
            label_path = tuple(label_path_raw)
        units.append(
            CandidateUnit(
                ordinal=ordinal,
                kind=kind,
                status=status,
                reasons=reasons,
                raw_text=raw_text,
                location=UnitLocation(
                    page=page,
                    element=element,
                    char_span=char_span,
                    bbox=bbox,
                    cells=cells,
                    label_path=label_path,
                ),
            )
        )
    issues_data = data.get("issues", [])
    issues: list[ReaderIssue] = []
    for entry in issues_data:
        if not isinstance(entry, dict):
            return None, "checkpoint_corrupt"
        issues.append(
            ReaderIssue(
                code=str(entry.get("code", "")),
                location=str(entry.get("location", "")),
                detail=str(entry.get("detail", "")),
            )
        )
    try:
        fmt = DocumentFormat(str(data.get("format", "")))
    except ValueError:
        return None, "checkpoint_corrupt"
    result = ReaderResult(
        format=fmt,
        extractor_rev=expected_extractor_rev,
        source_path=str(data.get("source_path", "")),
        page_count=data.get("page_count") if isinstance(data.get("page_count"), int) else None,
        units=tuple(units),
        issues=tuple(issues),
    )
    # 校验逐单元哈希与检查点记录一致（源/解析变化则重算）。
    actual_hashes = [u.content_hash for u in result.units]
    if actual_hashes != unit_hashes:
        return None, "content_hash_mismatch"
    return result, None


def _run_pre_admission_operation[OperationResult](
    operation: str,
    produce: Callable[[], OperationResult],
    lease: LeaseConfig,
    *,
    clock: Callable[[], datetime] | None,
    now: datetime,
    cancel_check: Callable[[], bool] | None,
) -> OperationResult:
    """Run real pre-build work under the same cancellation/time contract.

    Reader output is required to make an admission decision and therefore
    exists before a build id can be formed.  It cannot honestly be represented
    as a build job.  This boundary still brackets the *actual* reader/clean
    computation (rather than a later list write), checking cancellation both
    before and after the expensive call and measuring it with the injected
    clock.  Build-scoped persistence remains fenced by :func:`_run_stage`.
    """
    now_fn = clock if clock is not None else (lambda: datetime.now(UTC))
    started = now_fn()
    if cancel_check is not None and cancel_check():
        raise EngineCancelled(f"预构建阶段 {operation} 被 cancel_check 取消（未开始昂贵操作）")
    result = produce()
    if cancel_check is not None and cancel_check():
        raise EngineCancelled(f"预构建阶段 {operation} 被 cancel_check 取消")
    elapsed = (now_fn() - started).total_seconds()
    if elapsed > lease.stage_timeout_seconds:
        raise EngineError(
            f"预构建阶段 {operation} 超时：{elapsed:.1f}s > "
            f"stage_timeout_seconds={lease.stage_timeout_seconds}"
        )
    return result


def _run_stage(
    store: Store,
    build_id: str,
    stage: JobStage,
    owner_id: str,
    now: datetime,
    lease: LeaseConfig,
    produce: Callable[[], list[Unit] | list[Chunk]],
    *,
    clock: Callable[[], datetime] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> None:
    """单阶段 job 生命周期：登记→取得租约→fencing 写入→提交终态（§8.1）。

    C6：produce 前后心跳检查；stage_timeout_seconds 超时 → FAILED + EngineError；
    cancel_check 返回 True → 提交 CANCELLED + 抛 :class:`EngineCancelled`（阻断
    后继阶段——PARSED 被取消后 CHUNKED 不允许继续跑，取消对调用方可见）；
    同 build 阶段已 SUCCEEDED 短路返回（幂等重放，不重复生产/增行）。
    """
    store.register_job(build_id, stage)
    job = store.acquire_job(build_id, stage, owner_id, now, lease)
    if job.state is JobState.SUCCEEDED:
        return  # 幂等：阶段产物已在库（契约 §8.1 同 build 重复执行不重复增行）
    token = job.fence_token
    if token is None:
        raise EngineError(f"job {job.job_id} 处于 RUNNING 却缺少 fence_token")
    # ``now`` is the store's lease-clock value used by ``acquire_job``.  Keep
    # persistence on that same clock when no explicit test/production clock is
    # supplied; otherwise a fixed-clock store would see its new lease as
    # instantly expired.  Pre-build work uses real UTC time independently.
    now_fn = clock if clock is not None else (lambda: now)
    stage_started = now_fn()
    try:
        if cancel_check is not None and cancel_check():
            raise _CancelledError()
        payload = produce()
        if cancel_check is not None and cancel_check():
            raise _CancelledError()
        # 心跳：produce 结束后续租（长 produce 不让租约过期被误判接管）。
        # 心跳失败不阻断已成功 produce；fencing 写入会暴露真正的 lease_lost。
        with contextlib.suppress(Exception):
            store.heartbeat_job(build_id, stage, owner_id, token, now_fn(), lease)
        elapsed = (now_fn() - stage_started).total_seconds()
        if elapsed > lease.stage_timeout_seconds:
            raise EngineError(
                f"阶段 {stage.value} 超时：{elapsed:.1f}s > "
                f"stage_timeout_seconds={lease.stage_timeout_seconds}"
            )
        if stage is JobStage.PARSED:
            store.put_units(
                build_id, cast("list[Unit]", payload), owner_id=owner_id, fence_token=token
            )
        elif stage is JobStage.CHUNKED:
            store.put_chunks(
                build_id, cast("list[Chunk]", payload), owner_id=owner_id, fence_token=token
            )
        else:
            raise EngineError(f"I1 引擎不支持的阶段: {stage.value}")
    except _CancelledError:
        store.finish_job(
            build_id,
            stage,
            owner_id,
            token,
            now_fn(),
            JobState.CANCELLED,
            error="cancelled by cancel_check",
        )
        raise EngineCancelled(
            f"阶段 {stage.value} 被 cancel_check 取消（job 已提交 CANCELLED，"
            f"后继阶段终止）: build {build_id}"
        ) from None
    except Exception as exc:
        store.finish_job(
            build_id, stage, owner_id, token, now_fn(), JobState.FAILED, error=str(exc)
        )
        raise
    store.finish_job(build_id, stage, owner_id, token, now_fn(), JobState.SUCCEEDED)


def _build_and_stage(
    store: Store,
    source: Source,
    admission: Admission,
    reader_result: ReaderResult,
    clean: CleanResult,
    *,
    owner_id: str,
    now: datetime,
    lease: LeaseConfig,
    clock: Callable[[], datetime] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> tuple[Build, int, int]:
    """装配 build（§4.1 版本绑定）并以 job 租约写入 units/chunks 两阶段权威产物。

    C2：scope 过滤在此处、chunk 之前作用于 clean 层——chunker 输入是 clean，
    只改 Unit 层拦不住范围外文本进入检索块。构建顺序：
    解析 scope locator → scoped clean → chunk → 装配 Unit/Chunk → 质量台账。
    """
    parse_rev = _parse_rev_for(source.source_id, reader_result.extractor_rev)
    clean_rev = canonical_fingerprint([CLEAN_REV])
    chunk_rev = canonical_fingerprint([CHUNK_REV])
    build_id = compute_build_id(
        source_id=source.source_id,
        decision_id=admission.decision_id,
        parse_rev=parse_rev,
        clean_rev=clean_rev,
        chunk_rev=chunk_rev,
        index_rev=INDEX_REV_V3,
        scope_ref=admission.scope_ref,
    )
    scope = _parse_scope_ref(admission.scope_ref)
    scoped_clean = _run_pre_admission_operation(
        "scope/clean",
        lambda: _apply_scope_to_clean(reader_result, clean, scope),
        lease,
        clock=clock,
        now=now,
        cancel_check=cancel_check,
    )
    chunk_result = _run_pre_admission_operation(
        "chunk",
        lambda: chunk_clean_result(reader_result, scoped_clean),
        lease,
        clock=clock,
        now=now,
        cancel_check=cancel_check,
    )
    units = _units_of(build_id, reader_result, scoped_clean)
    unit_id_by_ordinal = {unit.ordinal: unit.unit_id for unit in units if unit.ordinal is not None}
    unit_char_spans = {unit.ordinal or 0: unit.location.char_span for unit in units}
    chunks = _chunks_of(build_id, chunk_result, unit_id_by_ordinal, unit_char_spans)
    build = Build(
        build_id=build_id,
        source_id=source.source_id,
        decision_id=admission.decision_id,
        parse_rev=parse_rev,
        clean_rev=clean_rev,
        chunk_rev=chunk_rev,
        index_rev=INDEX_REV_V3,
        scope_ref=admission.scope_ref,
        quality_report=_quality_report(build_id, scoped_clean, chunk_result),
    )
    store.put_build(build)
    _run_stage(
        store,
        build_id,
        JobStage.PARSED,
        owner_id,
        now,
        lease,
        lambda: units,
        clock=clock,
        cancel_check=cancel_check,
    )
    _run_stage(
        store,
        build_id,
        JobStage.CHUNKED,
        owner_id,
        now,
        lease,
        lambda: chunks,
        clock=clock,
        cancel_check=cancel_check,
    )
    return build, len(units), len(chunks)


# --- C4：明确排除的免探查快路径（撤销资格不依赖解析成功） ---


def _exclusion_fast_path_eligible(
    reviews: list[ReviewedDecision],
    source_id: str,
) -> tuple[bool, ReviewedDecision | None, tuple[AdmissionReasonCode, ...]]:
    """判断是否可走免探查排除快路径（full-review C4）。

    前提：全部决定绑定同源哈希、无 invalid_locator、链解析干净为排除类决定。
    任何阻断条件不满足即返回不可走快路径，落回完整探查。
    """
    if not reviews:
        return False, None, ()
    if any(decision.source_id != source_id for decision in reviews):
        return False, None, (AdmissionReasonCode.SOURCE_CHANGED,)
    if any(decision.scope_ref and not decision.locators for decision in reviews):
        return False, None, (AdmissionReasonCode.INVALID_LOCATOR,)
    effective, chain_reasons = resolve_review_chain(tuple(reviews))
    if chain_reasons or effective is None:
        return False, None, chain_reasons
    if effective.decision not in (ReviewDecision.EXCLUDED, ReviewDecision.EXCLUDED_FROM_ACTIVE):
        return False, None, ()
    return True, effective, ()


def _execute_one(
    store: Store,
    planned: PlannedSource,
    policy: AdmissionPolicy,
    *,
    archive_root: str | Path,
    owner_id: str,
    now: datetime,
    lease: LeaseConfig,
    limits: IngestLimits | None,
    reader: Callable[[Path], ReaderResult],
    clock: Callable[[], datetime] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> ExecuteOutcome:
    reviews = []
    for decision_id in planned.review_decision_ids:
        decision = store.get_reviewed_decision(decision_id)
        if decision is None:
            raise EngineError(f"清单引用的人工审核决定不存在: {decision_id}")
        reviews.append(decision)

    ingest = ingest_source(
        store,
        planned.path,
        archive_root,
        limits=limits,
        original_name=planned.original_name,
    )
    # C3：登记失败必须终止后续阶段（不忽略 registered=False 继续 build）。
    if not ingest.registered:
        raise EngineError(
            f"来源登记失败，终止后续阶段: {planned.original_name}"
            f"（归档已保留，可由 register_archived_source 恢复；error={ingest.error}）"
        )
    source = ingest.source

    descriptor = SourceDescriptor(
        source_id=source.source_id,
        fmt=source.format,
        location=source.archive_path,
        title=planned.original_name,
        domain_hint=planned.domain_hint,
    )

    # C4：明确排除先于解析处理（撤销资格不依赖解析成功）。
    fast, effective_exclusion, _ = _exclusion_fast_path_eligible(reviews, source.source_id)
    if fast and effective_exclusion is not None:
        admission = decide_exclusion_without_probe(descriptor, policy, effective_exclusion)
        store.put_admission(admission)
        publication = store.get_publication(source.source_id)
        if publication is not None and publication.active_build_id is not None:
            # 显式排除决定生效时原子撤下活动版本（§5.2）；旧 build 仅供审计。
            store.retire(source.source_id, admission.decision_id, now)
        return ExecuteOutcome(
            original_name=planned.original_name,
            source=source,
            admission=admission,
            build=None,
            unit_count=0,
            chunk_count=0,
            source_reused=ingest.already_registered,
            archive_reused=ingest.reused_archive,
        )

    # 普通路径：解析（读归档副本）→ 清洗 → 准入判定 → 登记；chunk 在
    # _build_and_stage 内于 scope 过滤之后执行（C2：chunk 消费 scoped clean）。
    archived_copy = Path(archive_root) / source.archive_path
    expected_extractor_rev = extractor_rev_for(source.format)
    # C6：先读解析检查点；有效则复用，无效则重算并写回检查点（重算原因落盘）。
    checkpoint = store.get_source_checkpoint(source.source_id, _PARSE_CHECKPOINT_STAGE)
    reader_result, reparse_reason = _validate_parse_checkpoint(
        checkpoint, source.source_id, expected_extractor_rev
    )
    if reader_result is None:
        reader_result = _run_pre_admission_operation(
            "parse",
            lambda: reader(archived_copy),  # 解析只读归档副本，用户原文不再触碰
            lease,
            clock=clock,
            now=now,
            cancel_check=cancel_check,
        )
        unit_hashes = tuple(u.content_hash for u in reader_result.units)
        new_checkpoint = _serialize_parse_checkpoint(
            source.source_id,
            reader_result,
            expected_extractor_rev,
            unit_hashes,
            reparse_reason=reparse_reason,
        )
        store.put_source_checkpoint(source.source_id, _PARSE_CHECKPOINT_STAGE, new_checkpoint)
    clean = _run_pre_admission_operation(
        "clean",
        lambda: clean_reader_result(reader_result),
        lease,
        clock=clock,
        now=now,
        cancel_check=cancel_check,
    )

    probe_payload = _probe_input(descriptor, reader_result)
    probes = probe_features(probe_payload)
    admission = decide_admission(descriptor, tuple(reviews), probes, policy)
    # §4.3：发布日期唯一落点 metadata_snapshot.report_publication，按原文依据重建
    # （禁止 doc_id 前缀派生）；unknown 亦显式落库记账。排除快路径（免探查）不带
    # 日期快照。
    admission = replace(
        admission,
        metadata_snapshot=MetadataSnapshot(
            report_publication=probe_report_publication(probe_payload)
        ),
    )
    store.put_admission(admission)

    build: Build | None = None
    unit_count = 0
    chunk_count = 0
    if admission.decision is AdmissionDecision.IN_SCOPE:
        build, unit_count, chunk_count = _build_and_stage(
            store,
            source,
            admission,
            reader_result,
            clean,
            owner_id=owner_id,
            now=now,
            lease=lease,
            clock=clock,
            cancel_check=cancel_check,
        )
    elif admission.decision is AdmissionDecision.EXCLUDED_BY_POLICY:
        publication = store.get_publication(source.source_id)
        if publication is not None and publication.active_build_id is not None:
            # 显式排除决定生效时原子撤下活动版本（§5.2）；旧 build 仅供审计。
            store.retire(source.source_id, admission.decision_id, now)
    return ExecuteOutcome(
        original_name=planned.original_name,
        source=source,
        admission=admission,
        build=build,
        unit_count=unit_count,
        chunk_count=chunk_count,
        source_reused=ingest.already_registered,
        archive_reused=ingest.reused_archive,
    )


def execute_builds(
    store: Store,
    plan: BuildPlan,
    *,
    policy: AdmissionPolicy,
    archive_root: str | Path,
    owner_id: str,
    now: datetime,
    lease: LeaseConfig,
    limits: IngestLimits | None = None,
    reader: Callable[[Path], ReaderResult] = read_document,
    clock: Callable[[], datetime] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> ExecuteReport:
    """全链编排：接收→解析（归档副本，检查点驱动）→清洗→切块→准入→登记。"""
    if policy.policy_rev != plan.policy_rev:
        raise EngineError(
            f"plan 政策版本 {plan.policy_rev!r} 与执行政策 {policy.policy_rev!r} 不一致，拒绝执行"
        )
    if not owner_id:
        raise EngineError("owner_id 不能为空（job 租约与 fencing 依赖它）")
    outcomes = tuple(
        _execute_one(
            store,
            planned,
            policy,
            archive_root=archive_root,
            owner_id=owner_id,
            now=now,
            lease=lease,
            limits=limits,
            reader=reader,
            clock=clock,
            cancel_check=cancel_check,
        )
        for planned in plan.entries
    )
    return ExecuteReport(outcomes=outcomes)


# --- C1：发布门（四步协议：幂等重放→VERIFIED 校验→PUBLISHED job 租约→store.publish） ---


@dataclass(frozen=True)
class QualityLedger:
    """确定性质量台账（build.quality_report 的校验后投影）。"""

    gap_keys: tuple[str, ...]
    oversized_chunks: tuple[str, ...]


def quality_ledger_of(build: Build) -> QualityLedger:
    """校验并解析 build 的质量台账（fail-closed：缺台账/形状漂移/条目非法即拒绝）。

    C1 收紧的落点：不得靠 ``or "{}"`` 旁路通过发布门。形状仍为
    ``gap_regions``/``oversized_chunks`` 两键（RM-FC-0：缺口身份编码在键里，
    ``issue:<code>:<location>``，不改台账形状）。
    """
    if not build.quality_report:
        raise EngineError(
            f"publish 拒绝：build 缺少质量台账（quality_report 为空）: {build.build_id}"
        )
    try:
        quality = json.loads(build.quality_report)
    except json.JSONDecodeError as exc:
        raise EngineError(f"publish 拒绝：quality_report 非法 JSON: {exc}") from exc
    if not isinstance(quality, dict) or set(quality) != {"gap_regions", "oversized_chunks"}:
        raise EngineError(
            "publish 拒绝：quality_report 形状非法（必须恰为 gap_regions/oversized_chunks 两键）"
        )
    gap_regions = quality["gap_regions"]
    oversized_chunks = quality["oversized_chunks"]
    if not isinstance(gap_regions, list) or not isinstance(oversized_chunks, list):
        raise EngineError(f"publish 拒绝：quality_report 字段类型非法: {build.quality_report!r}")
    if not all(isinstance(item, str) for item in (*gap_regions, *oversized_chunks)):
        raise EngineError(
            f"publish 拒绝：quality_report 条目非法（缺口/超长键必须是字符串）: "
            f"{build.quality_report!r}"
        )
    return QualityLedger(
        gap_keys=tuple(str(item) for item in gap_regions),
        oversized_chunks=tuple(str(item) for item in oversized_chunks),
    )


def gap_records_of(build: Build, *, store: Store | None = None) -> tuple[GapRecord, ...]:
    """build 的缺口裁决记录（默认分级 + scope 归属）。

    发布门、``corpus-check``、``corpus-status``、``corpus-plan`` 预检共用本实现
    （RM-FC-7：预判与判定必须同口径，不得各算一套）。
    """
    ledger = quality_ledger_of(build)
    scope = _parse_scope_ref(build.scope_ref)
    records = evaluate_against_scope(
        gap_records(ledger.gap_keys),
        tuple((entry.start, entry.end) for entry in scope),
    )
    if store is not None:
        from plugins.corpus.preparation.gap_review import GapReviewError, apply_gap_review

        try:
            review = store.get_gap_review(build.build_id)
            if review is not None:
                records = apply_gap_review(review, build, store.get_units(build.build_id), records)
        except GapReviewError as exc:
            raise EngineError(f"gap_regions human review rejected: {exc}") from exc
    return records


def _acknowledged_keys_of(build: Build | None, store: Store) -> tuple[str, ...]:
    """已放行（``acknowledged``）缺口的键，用于 PUBLISHED 检查点留痕。

    台账不可读时不抛异常：本函数只服务于「发布已成立」的留痕（发布门已单独校验），
    幂等重放补齐执行台账不得因台账形状问题失败——但缺口本身仍留在 quality_report。
    """
    if build is None:
        return ()
    try:
        records = gap_records_of(build, store=store)
    except EngineError:
        return ()
    return tuple(record.key for record in acknowledged_gaps(records))


def _verify_publication_ready(
    store: Store,
    build: Build,
) -> None:
    """发布前置校验（full-review C1 + RM-FC-0）：阶段完成 + 质量门 + scope 闭合。

    - PARSED 与 CHUNKED 阶段 job 必须 SUCCEEDED（部分 build 不得发布）。
    - ``oversized_chunks`` 必须为空（超长不得发布）。
    - 缺口（``gap_regions``）按架构 §7.3 的裁决口径判定：``blocking`` 拒绝发布；
      ``acknowledged``（默认分级已放行）与 ``out_of_scope``（可证在获批范围之外）
      允许发布，但**必须保持可见**（quality_report + check/status + coverage）。
    - chunk.unit_refs ⊆ 保留单元（out_of_scope 单元不得进入检索投影）。
    - 保留单元（status=KEPT）必须被至少一个 chunk 引用（全覆盖）。
    """
    parsed_job = store.get_job(build.build_id, JobStage.PARSED)
    chunked_job = store.get_job(build.build_id, JobStage.CHUNKED)
    if parsed_job is None or parsed_job.state is not JobState.SUCCEEDED:
        raise EngineError(
            f"publish 拒绝：PARSED 阶段未成功（build {build.build_id}），不得发布部分 build"
        )
    if chunked_job is None or chunked_job.state is not JobState.SUCCEEDED:
        raise EngineError(
            f"publish 拒绝：CHUNKED 阶段未成功（build {build.build_id}），不得发布部分 build"
        )
    ledger = quality_ledger_of(build)
    blocking = blocking_gaps(gap_records_of(build, store=store))
    if blocking:
        # 文案保留 ``gap_regions``（既有消费者/探针据此路由），并给出机读字段之外的
        # 人类可读摘要（码 + 坐标 + 恢复路径由 check/status 的 gaps/recovery 提供）。
        detail = ", ".join(f"{r.code}@{r.location or '?'}" for r in blocking)
        raise EngineError(
            "publish 拒绝：存在未解决的质量缺口（gap_regions 非空，须按架构 §7.3 处置）: "
            f"{sorted(r.key for r in blocking)}（{detail}）"
        )
    oversized_chunks = list(ledger.oversized_chunks)
    if oversized_chunks:
        raise EngineError(
            f"publish 拒绝：存在超长不可分块（oversized_chunks 非空）: {oversized_chunks}"
        )
    units = store.get_units(build.build_id)
    chunks = store.get_chunks(build.build_id)
    kept_unit_ids = {u.unit_id for u in units if u.status is UnitStatus.KEPT}
    referenced: set[str] = set()
    for chunk in chunks:
        for ref in chunk.unit_refs:
            referenced.add(ref)
    out_of_scope_refs = referenced - kept_unit_ids
    if out_of_scope_refs:
        raise EngineError(
            f"publish 拒绝：chunk 引用了 out_of_scope/非保留单元: {sorted(out_of_scope_refs)}"
        )
    missing = kept_unit_ids - referenced
    if missing:
        raise EngineError(f"publish 拒绝：保留单元未被任何 chunk 引用: {sorted(missing)}")


def _parse_rev_for(source_id: str, extractor_rev: str) -> str:
    """parse_rev 的**唯一**组装公式（parse 规则版本 + 源哈希 + 读取器版本）。

    写入侧（:func:`_build_and_stage`）与复用判定侧（:func:`expected_parse_rev`）共用，
    避免 CLI/审计各拼一套导致「静默给出错误复用判定」（RM-I28-9）。
    """
    return canonical_fingerprint([PARSE_RULE_REV, source_id, extractor_rev])


def expected_parse_rev(source: Source) -> str:
    """期望的 parse_rev（复用判定唯一来源；CLI 不得自行拼公式）。

    ``source_id`` 由原始字节决定（§4.1），读取器版本取当前代码对该格式的常量——
    规则、读取器或源字节任一变化都会得到不同值，检查点即不可复用。
    """
    return _parse_rev_for(source.source_id, extractor_rev_for(source.format))


def current_revs() -> dict[str, str]:
    """当前代码的版本身份（供 CLI ``corpus-rebuild-plan`` 判定阶段可否复用）。

    与 ``_build_and_stage`` 写进 build 的取值**同一来源**：clean/chunk 是模块规则
    常量的指纹，index 是索引配置+文本规则版本，parse 规则版本单列——调用方不得
    自行拼接或比较字面量（否则会误报"需要全量重建"）。
    """
    return {
        "parse_rule_rev": PARSE_RULE_REV,
        "clean_rev": canonical_fingerprint([CLEAN_REV]),
        "chunk_rev": canonical_fingerprint([CHUNK_REV]),
        "index_rev": INDEX_REV_V3,
    }


def check_build_publishable(store: Store, build_id: str) -> Build:
    """公开的发布前核验（CLI/WEB 复用同一门，不复制规则），返回被核验的 build。

    与 :func:`publish_build` 第 3 步完全同一实现：build 存在 + 阶段 SUCCEEDED +
    质量门（缺口按 §7.3 裁决：``blocking`` 拒绝、``acknowledged``/范围外放行；
    oversized 拒绝）+ scope 与 chunk 引用闭合。只读，不切指针。
    """
    build = store.get_build(build_id)
    if build is None:
        raise EngineError(f"build 不存在: {build_id}")
    _verify_publication_ready(store, build)
    return build


def _verify_admission_still_current(store: Store, build: Build) -> None:
    """核验 build 绑定的准入仍是来源的**当前有效**决定（RM-3）。

    ``publish_build`` 的幂等短路是「请求当前有效发布」，不是只读查询历史结果：
    若准入已变更为新的排除/缩范围决定、而撤销动作尚未完成，仅凭
    ``(decision_id, active_build_id)`` 相同就返回成功，会让调用方误以为该来源
    在当前准入下仍处于已发布状态。此处与 ``Store.publish`` 事务内的准入校验
    （当前决定指针 + in_scope）形成同一协议，消除 Store 门与入口行为的不一致。

    拒绝时抛 ``StoreError``（与 ``Store.publish`` 事务内同情形的拒绝**同族**）：
    入口短路与事务内检查不仅「都拒绝」，异常协议也一致，调用方无需区分来源。
    """
    admission = store.latest_admission(build.source_id)
    if admission is None or admission.decision_id != build.decision_id:
        current = admission.decision_id if admission is not None else None
        raise StoreError(
            f"publish 拒绝：build {build.build_id} 绑定决定 {build.decision_id}，"
            f"已不是 source {build.source_id} 的当前决定（当前为 {current}）；"
            "准入已变更，须按新决定重新评估，不得沿用旧发布结果"
        )
    if admission.decision is not AdmissionDecision.IN_SCOPE:
        raise StoreError(
            f"publish 拒绝：当前决定 {admission.decision_id} 为 "
            f"{admission.decision.value}，非 in_scope；撤销完成前不得宣称发布有效"
        )


def _publish_record(
    publication: Publication,
    *,
    operator: str | None,
    owner_id: str,
    acknowledged_gap_keys: tuple[str, ...] = (),
    human_gap_review_id: str | None = None,
) -> str:
    """PUBLISHED job 成功检查点：记录操作者、generation 与已放行缺口（I2-4 审计口径）。

    ``corpus_publications`` 的冻结列不含操作者，故把「谁在哪个 generation 切的
    活动指针」写进该 attempt 行的 checkpoint（同事务随 finish_job 提交），
    不新增表/列、不双写权威。

    RM-FC-0：``acknowledged`` 缺口的**记录人**就是这个发布操作者，依据是
    默认分级表（``gap_policy_rev``）；缺口本身仍留在 ``quality_report`` 与
    ``coverage``/``status`` 输出里，不因发布而消失。
    """
    return json.dumps(
        {
            "schema_rev": "publish-record-1",
            "operator": operator or owner_id,
            "owner_id": owner_id,
            "source_id": publication.source_id,
            "decision_id": publication.current_decision_id,
            "active_build_id": publication.active_build_id,
            "generation": publication.generation,
            "activated_at": (
                publication.activated_at.isoformat() if publication.activated_at else None
            ),
            "gap_policy_rev": GAP_POLICY_REV,
            "acknowledged_gaps": sorted(acknowledged_gap_keys),
            "human_gap_review_id": human_gap_review_id,
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _reconcile_published_job(
    store: Store,
    build_id: str,
    *,
    owner_id: str,
    activated_at: datetime,
    lease: LeaseConfig,
    clock: Callable[[], datetime] | None = None,
    operator: str | None = None,
) -> Job | None:
    """补齐「活动指针已切换、PUBLISHED job 未终态」的执行台账（RM-2）。

    活动指针切换与 ``finish_job`` 是两次 Store 提交：前者成功、后者提交前断线时，
    重试若被幂等短路直接返回，PUBLISHED job 会永久停在 RUNNING——表面发布幂等
    成立，执行台账、恢复路径与 attempt 预算却未闭合。

    采用**受 fencing 保护的幂等恢复**（而非合并事务）：先用当前行租约提交；
    因租约已过期被拒则重新取得租约后再提交；租约仍被他人持有（未过期）时
    **不抢占**，交由其自己收尾或由接管流程处理。这保持 Store Seam 的职责划分
    （publish 管指针、finish_job 管 job 状态），也不扩大 J1/J2 锁的范围。
    """
    job = store.get_job(build_id, JobStage.PUBLISHED)
    if job is None or job.state is not JobState.RUNNING:
        return job  # 未登记（发布早于登记协议）或已终态：无需补齐
    _now = clock or (lambda: activated_at)
    build = store.get_build(build_id)
    publication = store.get_publication(build.source_id) if build is not None else None
    record = (
        _publish_record(
            publication,
            operator=operator,
            owner_id=owner_id,
            acknowledged_gap_keys=_acknowledged_keys_of(build, store),
            human_gap_review_id=_human_gap_review_id(store, build_id),
        )
        if publication is not None
        else None
    )
    if job.owner_id == owner_id and job.fence_token is not None:
        try:
            return store.finish_job(
                build_id,
                JobStage.PUBLISHED,
                owner_id,
                job.fence_token,
                _now(),
                JobState.SUCCEEDED,
                checkpoint=record,
            )
        except StoreError:
            # 租约已过期或状态已变：重读确认是否仍待补齐，再决定重新取租约。
            job = store.get_job(build_id, JobStage.PUBLISHED)
            if job is None or job.state is not JobState.RUNNING:
                return job
    try:
        acquired = store.acquire_job(build_id, JobStage.PUBLISHED, owner_id, _now(), lease)
    except StoreError:
        return store.get_job(build_id, JobStage.PUBLISHED)  # 仍被他人持有：不抢占
    if acquired.fence_token is None:  # 与引擎主路径同纪律（fail-closed）
        raise EngineError(f"PUBLISHED job {acquired.job_id} 处于 RUNNING 却缺少 fence_token")
    return store.finish_job(
        build_id,
        JobStage.PUBLISHED,
        owner_id,
        acquired.fence_token,
        _now(),
        JobState.SUCCEEDED,
        checkpoint=record,
    )


def _human_gap_review_id(store: Store, build_id: str) -> str | None:
    from plugins.corpus.preparation.gap_review import GapReviewError

    try:
        review = store.get_gap_review(build_id)
        return review.review_id if review is not None else None
    except GapReviewError as exc:
        raise EngineError(f"gap_regions human review rejected: {exc}") from exc


def publish_build(
    store: Store,
    build_id: str,
    *,
    activated_at: datetime,
    owner_id: str = "engine-publish",
    lease: LeaseConfig | None = None,
    clock: Callable[[], datetime] | None = None,
    operator: str | None = None,
) -> Publication:
    """发布检查门（full-review C1 四步协议，fail-closed）。

    1. build 存在校验。
    2. 幂等重放短路（publish_idempotency_v2，I0-C 裁决）：相同目标状态
       ``(decision_id, active_build_id)`` 的重复调用直接返回已提交结果
       （不递增 generation、不刷新 activated_at；幂等不以时间为键）。
       短路前先执行两项一致性检查（RM-2/RM-3）：当前准入仍有效、PUBLISHED job
       终态已闭合——否则「已发布」只是指针事实，执行台账与准入状态并未闭合。
    3. VERIFIED 校验（:func:`_verify_publication_ready`）：阶段 SUCCEEDED + 质量
       门 + scope 闭合。
    4. PUBLISHED job 租约：register_job → acquire_job 取得当前租约 → store.publish
       携带 owner/token 切活动指针；finish_job SUCCEEDED。无 job/no-check 旁路。
    """
    build = store.get_build(build_id)
    if build is None:
        raise EngineError(f"build 不存在，不得发布: {build_id}")
    # Human approval is a live precondition even for retries/rollback. Never reuse
    # an old success checkpoint after its credential is missing, stale or corrupt.
    review_id = _human_gap_review_id(store, build_id)
    published_job = store.get_job(build_id, JobStage.PUBLISHED)
    recorded_review_id = None
    if published_job is not None and published_job.checkpoint:
        try:
            recorded_review_id = json.loads(published_job.checkpoint).get("human_gap_review_id")
        except (ValueError, AttributeError) as exc:
            raise EngineError(
                "published checkpoint cannot verify human gap review identity"
            ) from exc
    if recorded_review_id is not None and recorded_review_id != review_id:
        raise EngineError(
            "gap_regions human review is missing or differs from published credential"
        )
    if review_id is not None:
        _verify_publication_ready(store, build)
    # 幂等重放短路：目标状态 (决定, build) 已发布 → 先补齐一致性再返回
    # （不以时间为键，响应丢失+时钟前进的重试恒幂等）。
    existing = store.get_publication(build.source_id)
    if (
        existing is not None
        and existing.current_decision_id == build.decision_id
        and existing.active_build_id == build_id
    ):
        # RM-3：这是「请求当前有效发布」，不是只读查询历史结果——准入已变更
        # （新排除/缩范围决定）而撤销动作未完成时，不得沿用旧发布结果。
        _verify_admission_still_current(store, build)
        if blocking_gaps(gap_records_of(build)):
            _verify_publication_ready(store, build)
        # RM-2：指针已切换但 PUBLISHED 终态未提交（断线于两次提交之间）时，
        # 直接返回会让该 job 永久停在 RUNNING；返回前补齐终态。
        _reconcile_published_job(
            store,
            build_id,
            owner_id=owner_id,
            activated_at=activated_at,
            lease=lease if lease is not None else DEFAULT_LEASE,
            clock=clock,
            operator=operator,
        )
        return existing
    # VERIFIED 校验：阶段完成 + 质量门 + scope 闭合。
    _verify_publication_ready(store, build)
    # PUBLISHED job 租约：取得当前所有权后由 store.publish 切指针。
    lease_config = lease if lease is not None else DEFAULT_LEASE
    _now = clock or (lambda: activated_at)
    store.register_job(build_id, JobStage.PUBLISHED)
    job = store.acquire_job(build_id, JobStage.PUBLISHED, owner_id, _now(), lease_config)
    token = job.fence_token
    if token is None:
        raise EngineError(f"PUBLISHED job {job.job_id} 处于 RUNNING 却缺少 fence_token")
    try:
        publication = store.publish(
            build.source_id,
            build.decision_id,
            build_id,
            activated_at,
            owner_id=owner_id,
            fence_token=token,
        )
    except Exception as exc:
        store.finish_job(
            build_id,
            JobStage.PUBLISHED,
            owner_id,
            token,
            _now(),
            JobState.FAILED,
            error=str(exc),
        )
        raise
    store.finish_job(
        build_id,
        JobStage.PUBLISHED,
        owner_id,
        token,
        _now(),
        JobState.SUCCEEDED,
        checkpoint=_publish_record(
            publication,
            operator=operator,
            owner_id=owner_id,
            acknowledged_gap_keys=_acknowledged_keys_of(build, store),
            human_gap_review_id=review_id,
        ),
    )
    return publication
