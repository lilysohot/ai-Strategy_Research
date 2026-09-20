"""I1-1 语料入库契约数据模型（M1 逻辑契约的确定性数据模型）。

本模块把 I0A-5 联合冻结的 M1 逻辑契约
（``.scratch/corpus-evidence-pipeline/ingestion-rebuild/i0a5-logic-contract-frozen-v1-20260915.json``）
中的模型/枚举/判定次序/必填字段实现为纯标准库 ``dataclass``，供 I1 内存链与
I2 的 PG 实现共同引用。权威来源是架构 v1.1 §4.1/4.2/4.3、§5.2、§7.3、§8/8.1。

纪律：
- 纯标准库（``dataclass``/``enum``/``hashlib``/``json``），不发起模型调用、不触网络/PG。
- 枚举与契约的 ``output_enums``/``coverage_axes``/``report_publication``/``job_state_machine``
  逐一对应；跨字段非法组合（known↔value、failed→unknown、in_scope→领域、租约参数、
  引用内容哈希）在构造即校验并抛 :class:`ContractError`，不 fallback 成功。
- ``source_id`` 仅由原始字节 SHA-256 决定；``build_id`` 绑定全部 rev + 准入决定 + scope。
- 物理表是候选（I0-C 可调整）；本模块锁定的是逻辑枚举与判定次序，不锁死物理表名。
"""

from __future__ import annotations

import enum
import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime


class ContractError(ValueError):
    """契约校验拒绝：非法枚举或非法字段组合。"""


_SHA256_HEX_LENGTH = 64

# admission.decision 判定次序（契约 §5.2，供 I1-5 与测试交叉核验）。
ADMISSION_DECISION_ORDER: tuple[str, ...] = (
    "review_binding_invalid_or_multiple_unresolved",
    "unique_human_decision_scope",
    "fallback_review_required",
    "single_type_word_not_decisive_new_hash_not_inherited",
)

# 契约 §5.2 声明的最少原因码集合（实现须至少覆盖这些）。
MINIMUM_REASON_CODES: frozenset[str] = frozenset(
    {
        "missing_review",
        "conflicting_review",
        "source_changed",
        "mixed_material",
        "unsupported_domain",
        "unreadable_probe",
        "policy_conflict",
    }
)

# job 阶段顺序（契约 §8）。
JOB_STAGE_ORDER: tuple[str, ...] = (
    "registered",
    "admission_decided",
    "parsed",
    "cleaned",
    "chunked",
    "staged",
    "indexed",
    "verified",
    "published",
)

# 结构性单元/检索块类别（架构 §5.3/§6.2，属于 I1-2/3/4 的映射语义，
# 非 M1 显式枚举号，故不设闭包枚举；此常量仅作文档化参考）。
UNIT_KINDS: frozenset[str] = frozenset(
    {
        "paragraph",
        "heading",
        "title",
        "list_item",
        "table",
        "table_row",
        "table_cell",
        "qa_question",
        "qa_answer",
        "footer",
        "header",
        "quote",
        "unknown",
    }
)
CHUNK_KINDS: frozenset[str] = frozenset(
    {"body", "heading", "list", "qa", "table", "context", "unknown"}
)


class DocumentFormat(enum.StrEnum):
    """来源文件格式（架构 §5.3：PDF/DOCX/Markdown）。"""

    PDF = "pdf"
    DOCX = "docx"
    MARKDOWN = "markdown"


class ResearchDomain(enum.StrEnum):
    """研究领域（架构 §5.2：company/industry/macro）。"""

    COMPANY = "company"
    INDUSTRY = "industry"
    MACRO = "macro"


class MaterialType(enum.StrEnum):
    """材料类型（与冻结的 I0A-2 终态词表一致）。"""

    RESEARCH_REPORT = "research_report"
    PIPELINE_ARTIFACT = "pipeline_artifact"
    PERSONAL_OR_EXTERNAL_SUBSCRIPTION = "personal_or_external_subscription"
    INTERNAL_UNATTRIBUTED = "internal_unattributed"
    INTERNAL_COMMITTEE_REPORT = "internal_committee_report"
    UNKNOWN = "unknown"


class AdmissionDecision(enum.StrEnum):
    """decide_admission 输出决定（契约 §5.2）。"""

    IN_SCOPE = "in_scope"
    EXCLUDED_BY_POLICY = "excluded_by_policy"
    REVIEW_REQUIRED = "review_required"


class AdmissionReasonCode(enum.StrEnum):
    """准入原因码（契约 §5.2 最少 7 项 + admission-policy 的 2 项）。"""

    MISSING_REVIEW = "missing_review"
    CONFLICTING_REVIEW = "conflicting_review"
    SOURCE_CHANGED = "source_changed"
    MIXED_MATERIAL = "mixed_material"
    UNSUPPORTED_DOMAIN = "unsupported_domain"
    UNREADABLE_PROBE = "unreadable_probe"
    POLICY_CONFLICT = "policy_conflict"
    INVALID_LOCATOR = "invalid_locator"
    SCOPE_UPGRADE_REJECTED = "scope_upgrade_rejected"


class ReviewDecision(enum.StrEnum):
    """人工审核终态（I0A-2 终态词表：admitted/excluded/excluded_from_active）。"""

    ADMITTED = "admitted"
    EXCLUDED = "excluded"
    EXCLUDED_FROM_ACTIVE = "excluded_from_active"


class CoverageProcessing(enum.StrEnum):
    """处理覆盖（契约 §7.3）。"""

    FULL = "full"
    SCOPED = "scoped"
    UNKNOWN = "unknown"


class QueryStatus(enum.StrEnum):
    """查询结果状态（契约 §7.3）。"""

    MATCHED = "matched"
    NO_MATCH = "no_match"
    FAILED = "failed"


class Availability(enum.StrEnum):
    """可用性（契约 §7.3）。"""

    AVAILABLE = "available"
    ABSENT = "absent"
    UNKNOWN = "unknown"


class PublicationDatePrecision(enum.StrEnum):
    """研报发布日期精度（契约 §4.3）。"""

    DATE = "date"
    INSTANT = "instant"
    UNKNOWN = "unknown"


class PublicationDateStatus(enum.StrEnum):
    """研报发布日期状态（契约 §4.3）。"""

    KNOWN = "known"
    UNKNOWN = "unknown"
    CONFLICT = "conflict"


class PublicationDateOrigin(enum.StrEnum):
    """研报发布日期依据来源（契约 §4.3）。"""

    SOURCE_EXPLICIT = "source_explicit"
    HUMAN_REVIEW = "human_review"


class JobStage(enum.StrEnum):
    """job 阶段（契约 §8，顺序见 :data:`JOB_STAGE_ORDER`）。"""

    REGISTERED = "registered"
    ADMISSION_DECIDED = "admission_decided"
    PARSED = "parsed"
    CLEANED = "cleaned"
    CHUNKED = "chunked"
    STAGED = "staged"
    INDEXED = "indexed"
    VERIFIED = "verified"
    PUBLISHED = "published"


class JobState(enum.StrEnum):
    """job 状态（契约 §8.1）。"""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class UnitStatus(enum.StrEnum):
    """单元区域处置状态（架构 §6.1/§6.2）。"""

    KEPT = "kept"
    NOISE = "noise"
    REVIEW_REQUIRED = "review_required"
    NEEDS_OCR = "needs_ocr"
    OUT_OF_SCOPE = "out_of_scope"
    OVERSIZED = "oversized"


def sha256_of_bytes(data: bytes) -> str:
    """返回字节数据的 SHA-256 十六进制指纹。"""
    return hashlib.sha256(data).hexdigest()


def source_id_from_bytes(data: bytes) -> str:
    """``source_id`` 仅由原始字节决定（契约 §4.1）。"""
    return sha256_of_bytes(data)


def canonical_fingerprint(value: object) -> str:
    """与文件位置/时间无关的内容指纹（对齐 :func:`plugins.corpus.evidence.fingerprint`）。"""
    return sha256_of_bytes(
        json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    )


def _require_sha256(value: str, field: str) -> str:
    if not isinstance(value, str) or len(value) != _SHA256_HEX_LENGTH:
        raise ContractError(f"{field} 必须是 64 位十六进制 SHA-256")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ContractError(f"{field} 不是合法十六进制") from exc
    return value


def compute_build_id(
    *,
    source_id: str,
    decision_id: str,
    parse_rev: str,
    clean_rev: str,
    chunk_rev: str,
    index_rev: str,
    scope_ref: str | None,
) -> str:
    """``build_id`` 绑定全部 rev + 准入决定 + 实际 scope（契约 §4.1）。

    重复执行确定且幂等；任一依赖变化都会得到不同 ``build_id``。
    """
    return canonical_fingerprint(
        {
            "source_id": source_id,
            "decision_id": decision_id,
            "parse_rev": parse_rev,
            "clean_rev": clean_rev,
            "chunk_rev": chunk_rev,
            "index_rev": index_rev,
            "scope_ref": scope_ref,
        }
    )


@dataclass(frozen=True)
class CharSpan:
    """原文 Unicode code point 区间 ``[start, end)``（契约 §4.2，非清洗文本偏移）。"""

    start: int
    end: int

    def __post_init__(self) -> None:
        if self.start < 0 or self.end <= self.start:
            raise ContractError(f"CharSpan 区间非法: [{self.start}, {self.end})")


@dataclass(frozen=True)
class UnitLocation:
    """原文单元坐标（page/element/char/bbox/cells，架构 §4.1）。

    ``cells`` 携带网格 (row, col) 数字；``label_path`` 携带与 ``cells`` 对齐的
    结构标签路径（每格 = ``" ".join(行标签, 列标签, 列标签父级, ...)``，票 04
    I-B1）。新增字段带默认值，不改 ``cells`` 既有语义。
    """

    page: int | None = None
    element: str | None = None
    char_span: CharSpan | None = None
    bbox: tuple[float, float, float, float] | None = None
    cells: tuple[tuple[int, int], ...] = ()
    label_path: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReportPublication:
    """研报发布日期（契约 §4.3 唯一落点）。"""

    value: str | None
    precision: PublicationDatePrecision
    status: PublicationDateStatus
    evidence_refs: tuple[str, ...] = ()
    origin: PublicationDateOrigin | None = None
    review_ref: str | None = None

    def __post_init__(self) -> None:
        if self.status is PublicationDateStatus.KNOWN:
            if self.value is None:
                raise ContractError("report_publication.known 必须有 value")
            if self.precision is PublicationDatePrecision.UNKNOWN:
                raise ContractError("report_publication.known 的 precision 不能为 unknown")
            if self.origin not in (
                PublicationDateOrigin.SOURCE_EXPLICIT,
                PublicationDateOrigin.HUMAN_REVIEW,
            ):
                raise ContractError(
                    "report_publication.known 的 origin 须为 source_explicit|human_review"
                )
            if not self.evidence_refs:
                # 静态收口（full-review §6）：日期 known 必有依据，不接受无证据的 known。
                raise ContractError("report_publication.known 必须携带 evidence_refs（依据）")
        else:
            if self.value is not None:
                raise ContractError("report_publication.unknown/conflict 的 value 必须为 null")
            if self.origin is not None:
                raise ContractError("report_publication.unknown/conflict 的 origin 必须为 null")


@dataclass(frozen=True)
class MetadataSnapshot:
    """准入元数据快照（仅携带契约定义字段；report_publication 是日期唯一落点）。"""

    report_publication: ReportPublication | None = None


@dataclass(frozen=True)
class Source:
    """原始来源（架构 §4.1 ``corpus_sources``）。"""

    source_id: str
    format: DocumentFormat
    mime_type: str
    size_bytes: int
    archive_path: str
    original_names: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_sha256(self.source_id, "source_id")
        if self.size_bytes < 0:
            raise ContractError("size_bytes 不能为负")
        if not self.archive_path:
            raise ContractError("archive_path 不能为空")


@dataclass(frozen=True)
class ReviewedDecision:
    """人工审核记录（契约 §5.2 的 ``reviewed_decisions`` 输入）。"""

    decision_id: str
    source_id: str
    reviewer: str
    reviewed_at: datetime
    decision: ReviewDecision
    rationale: str
    scope_ref: str | None = None
    supersedes: str | None = None
    locators: tuple[str, ...] = ()
    # 人工凭证（full-review §6 静态收口）：材料类型/领域由绑定同源哈希的人工决定
    # 给出时优先于登记提示（domain_hint 只是登记元数据，不是批准凭证）。
    material_type: MaterialType | None = None
    research_domain: ResearchDomain | None = None

    def __post_init__(self) -> None:
        _require_sha256(self.source_id, "reviewed_decisions.source_id")
        if not self.decision_id or not self.reviewer:
            raise ContractError("ReviewedDecision 的 decision_id/reviewer 不能为空")
        if not isinstance(self.decision, ReviewDecision):
            # 构造即拒绝（fail-closed）：非法词表不得流入取代链解析被当作批准。
            raise ContractError(f"ReviewedDecision.decision 非法: {self.decision!r}")
        if not self.rationale:
            raise ContractError("ReviewedDecision 必须有 rationale（依据）")


# in_scope 允许的材料类型按 **policy_rev** 绑定（dev lane，U 2026-09-20 裁决）：
# v1 冻结语义 = 仅 research_report（逐字保留，生产判定不变）；dev 政策可额外允许
# U 显式指定的内部材料，且生效范围由 admission-policy-dev 的 dev_lane.sources 限定。
# 未知 policy_rev 落到默认（最严）集合，fail-closed。
DEFAULT_IN_SCOPE_MATERIALS: tuple[MaterialType, ...] = (MaterialType.RESEARCH_REPORT,)
IN_SCOPE_MATERIALS_BY_POLICY_REV: dict[str, tuple[MaterialType, ...]] = {
    "v1-20260915": DEFAULT_IN_SCOPE_MATERIALS,
    # dev lane（U 2026-09-20 裁决）：仅新增 U 指定两份来源的材料类型，
    # 逐源由 admission-policy-dev.json 的 dev_lane.sources 限定。
    "v2-dev-20260920": (
        MaterialType.RESEARCH_REPORT,
        MaterialType.INTERNAL_COMMITTEE_REPORT,
        MaterialType.INTERNAL_UNATTRIBUTED,
    ),
}


@dataclass(frozen=True)
class Admission:
    """准入记录（契约 §5.2 ``decide_admission`` 输出 + ``corpus_admissions``）。"""

    decision_id: str
    source_id: str
    material_type: MaterialType
    research_domain: ResearchDomain | None
    decision: AdmissionDecision
    policy_rev: str = ""
    reason_codes: tuple[AdmissionReasonCode, ...] = ()
    scope_ref: str | None = None
    evidence_refs: tuple[str, ...] = ()
    review_ref: str | None = None
    rule_rev: str = ""
    metadata_snapshot: MetadataSnapshot = field(default_factory=MetadataSnapshot)

    def __post_init__(self) -> None:
        _require_sha256(self.source_id, "admission.source_id")
        if not self.decision_id:
            raise ContractError("admission.decision_id 不能为空")
        if self.policy_rev and not self.policy_rev.startswith("v"):
            raise ContractError("admission.policy_rev 须为版本号（如 v1-20260915）")
        for code in self.reason_codes:
            if code not in AdmissionReasonCode:
                raise ContractError(f"admission.reason_codes 含非法码: {code!r}")
        if self.decision is AdmissionDecision.IN_SCOPE:
            allowed_materials = IN_SCOPE_MATERIALS_BY_POLICY_REV.get(
                self.policy_rev, DEFAULT_IN_SCOPE_MATERIALS
            )
            if self.material_type not in allowed_materials:
                raise ContractError("in_scope 材料必须为分析师研报（research_report）")
            if self.research_domain not in (
                ResearchDomain.COMPANY,
                ResearchDomain.INDUSTRY,
                ResearchDomain.MACRO,
            ):
                raise ContractError("in_scope 必须有 company/industry/macro 领域")


@dataclass(frozen=True)
class Build:
    """一次确定性构建版本（架构 §4.1 ``corpus_builds``）。"""

    build_id: str
    source_id: str
    decision_id: str
    parse_rev: str
    clean_rev: str
    chunk_rev: str
    index_rev: str
    scope_ref: str | None = None
    config_fingerprint: str | None = None
    artifact_manifest: tuple[str, ...] = ()
    quality_report: str | None = None

    def __post_init__(self) -> None:
        _require_sha256(self.source_id, "build.source_id")
        _require_sha256(self.build_id, "build_id")
        if not self.decision_id:
            raise ContractError("build.decision_id 不能为空")
        for rev_name, rev in (
            ("parse_rev", self.parse_rev),
            ("clean_rev", self.clean_rev),
            ("chunk_rev", self.chunk_rev),
            ("index_rev", self.index_rev),
        ):
            if not rev:
                raise ContractError(f"build.{rev_name} 不能为空")


@dataclass(frozen=True)
class Unit:
    """原文结构单元（架构 §4.1 ``corpus_units``；引用唯一权威 raw_text + 坐标）。"""

    unit_id: str
    build_id: str
    kind: str
    raw_text: str
    content_hash: str
    parent_id: str | None = None
    ordinal: int | None = None
    location: UnitLocation = field(default_factory=UnitLocation)
    clean_view: str | None = None
    mapping: tuple[tuple[int, int], ...] = ()
    status: UnitStatus = UnitStatus.KEPT
    reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_sha256(self.build_id, "unit.build_id")
        _require_sha256(self.content_hash, "unit.content_hash")
        if not self.unit_id:
            raise ContractError("unit.unit_id 不能为空")
        if self.content_hash != sha256_of_bytes(self.raw_text.encode("utf-8")):
            raise ContractError(
                "unit.content_hash 必须等于 raw_text 的 SHA-256（引用只能指向权威原文）"
            )
        if self.ordinal is not None and self.ordinal < 0:
            raise ContractError("unit.ordinal 不能为负")


@dataclass(frozen=True)
class Chunk:
    """可重建的检索投影（架构 §4.1 ``corpus_chunks``；引用只能指向本 build 真实单元）。

    ``unit_refs`` 是全量引用闭合（核心内容 + 标题/表头等关联单元，引用必须指向
    真实单元）；``context_refs`` 标注其中承担**关联角色**的子集（full-review §6
    静态收口：core/context 角色在契约层保留，不由 consumers 猜回）。
    ``source_ranges`` 是成员单元的原文 code point 区间装配（可验坐标存在时）。
    """

    chunk_id: str
    build_id: str
    kind: str
    unit_refs: tuple[str, ...]
    search_text: str
    title_text: str | None = None
    section_path: tuple[str, ...] = ()
    source_ranges: tuple[CharSpan, ...] = ()
    context_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_sha256(self.build_id, "chunk.build_id")
        if not self.chunk_id:
            raise ContractError("chunk.chunk_id 不能为空")
        if not self.unit_refs:
            raise ContractError("chunk.unit_refs 不能为空（引用必须指向真实单元）")
        unknown = set(self.context_refs) - set(self.unit_refs)
        if unknown:
            raise ContractError(f"chunk.context_refs 必须是 unit_refs 的子集: {sorted(unknown)}")


@dataclass(frozen=True)
class CoverageCounts:
    """覆盖计数分母（契约 §7.3，绑定同一 scope 清单与查询快照）。"""

    source_count: int = 0
    published_count: int = 0
    excluded_count: int = 0
    review_or_failed_count: int = 0

    def __post_init__(self) -> None:
        for name in ("source_count", "published_count", "excluded_count", "review_or_failed_count"):
            if getattr(self, name) < 0:
                raise ContractError(f"coverage.counts.{name} 不能为负")


@dataclass(frozen=True)
class Coverage:
    """准入/处理覆盖/查询结果三轴契约（契约 §7.3）。"""

    admission_decision: AdmissionDecision | None
    processing: CoverageProcessing
    query_status: QueryStatus
    availability: Availability
    requested_scope_ref: str | None = None
    effective_scope_ref: str | None = None
    publication_snapshot_ref: str | None = None
    reason_codes: tuple[str, ...] = ()
    counts: CoverageCounts = field(default_factory=CoverageCounts)

    def __post_init__(self) -> None:
        if (
            self.query_status is QueryStatus.FAILED
            and self.availability is not Availability.UNKNOWN
        ):
            raise ContractError("coverage: failed 恒为 unknown（不能携带全范围无数据结论）")
        if (
            self.requested_scope_ref is None
            or self.effective_scope_ref is None
            or self.publication_snapshot_ref is None
        ) and self.processing is not CoverageProcessing.UNKNOWN:
            raise ContractError(
                "coverage: 没有有效 scope/快照时必须为 unknown（unknown 优先于 scoped）"
            )


@dataclass(frozen=True)
class LeaseConfig:
    """job 租约参数（契约 §8.1 必含四项）。"""

    lease_ttl_seconds: int
    heartbeat_interval_seconds: int
    stage_timeout_seconds: int
    max_attempts: int

    def __post_init__(self) -> None:
        for name in (
            "lease_ttl_seconds",
            "heartbeat_interval_seconds",
            "stage_timeout_seconds",
            "max_attempts",
        ):
            if getattr(self, name) <= 0:
                raise ContractError(f"lease.{name} 必须为正")
        if self.heartbeat_interval_seconds >= self.lease_ttl_seconds:
            raise ContractError("heartbeat 必须小于 TTL")
        if self.heartbeat_interval_seconds > self.lease_ttl_seconds // 3:
            raise ContractError("heartbeat 不得超过 TTL/3")


@dataclass(frozen=True)
class Publication:
    """活动版本选择（架构 §7.2/§8。排除/撤销时 active_build_id 为空）。"""

    source_id: str
    current_decision_id: str
    active_build_id: str | None
    generation: int
    activated_at: datetime

    def __post_init__(self) -> None:
        _require_sha256(self.source_id, "publication.source_id")
        if self.generation < 1:
            raise ContractError("publication.generation 必须 ≥ 1")


@dataclass(frozen=True)
class Job:
    """可恢复执行 job（契约 §8.1，逻辑唯一键 ``(build_id, stage)``）。"""

    job_id: str
    build_id: str
    stage: JobStage
    attempt: int
    state: JobState
    owner_id: str | None = None
    fence_token: str | None = None
    lease_until: datetime | None = None
    heartbeat_at: datetime | None = None
    error: str | None = None
    checkpoint: str | None = None

    def __post_init__(self) -> None:
        _require_sha256(self.build_id, "job.build_id")
        if self.attempt < 1:
            raise ContractError("job.attempt 必须 ≥ 1")
        if self.state is JobState.RUNNING and (self.owner_id is None or self.fence_token is None):
            raise ContractError("running job 必须有 owner_id 与 fence_token")
