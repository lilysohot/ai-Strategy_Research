"""准入判定（任务 I1-5，架构 §5.2 + I0A-3 冻结政策 admission-policy v1-20260915）。

两个纯函数，无 I/O、无模型调用、无网络；同输入同 ``policy_rev`` 输出逐字段一致：

- :func:`probe_features` —— 内容级特征探查（政策 §features 六特征，含扫描上限），
  值域 matched/absent/unreadable；**unreadable ≠ absent**（探查不到内容不等于
  确认无标记，``probe_discipline.unreadable_is_not_absent``）。
- :func:`decide_admission` —— 固定判定次序（政策 §decision_order 四层）：

  1. 审核绑定完整性：决定绑定不同源哈希（source_changed）、坐标无效
     （invalid_locator）、取代链断裂/多未决决定（conflicting_review）→
     review_required；不凭时间最新猜测覆盖。
  2. 唯一有效人工决定：admitted 且材料为分析师研报（或全 absent 由人工确认）
     且领域 ∈ 允许集且范围明确 → in_scope；excluded/excluded_from_active →
     excluded_by_policy；部分章节批准须有明确坐标不得升级为整篇纳入
     （scope_upgrade_rejected）；admitted 非研报材料与冻结范围冲突
     （policy_conflict）→ 复核。
  3. 其余一律 review_required，原因至少含适用项（missing_review/
     mixed_material/unsupported_domain/unreadable_probe 等）。
  4. 单一『会议/专家/Q/A』词不直接决定类型：书面问答等混合信号只记
     mixed_material 复核建议，不阻断已锁定正例的人工纳入（十问十答先例）；
     新哈希不继承旧哈希批准（决定必须绑定同源哈希）。

政策 ``auto_decision.enabled=false`` 在此落实：机器特征只生成复核建议，
in_scope/excluded_by_policy 必须由绑定同源哈希的唯一有效人工决定驱动；
无有效决定一律 review_required（未决不能发布，由 I1-7 引擎拒绝 publish）。
表驱动 gold 用例见 tests/test_corpus_preparation_admission.py。
"""

from __future__ import annotations

import enum
import json
import re
from dataclasses import dataclass
from pathlib import Path

from plugins.corpus.preparation.contract import (
    Admission,
    AdmissionDecision,
    AdmissionReasonCode,
    DocumentFormat,
    MaterialType,
    ResearchDomain,
    ReviewDecision,
    ReviewedDecision,
    canonical_fingerprint,
)

POLICY_REV_V1 = "v1-20260915"
# dev lane 政策修订（U 2026-09-20 裁决：新建 dev lane，只对 dev 构建生效，
# 不改变任何生产 in_scope 判定；material_type 如实保持 internal_committee_report）。
POLICY_REV_V2_DEV = "v2-dev-20260920"
RULE_REV = f"decision-order-{POLICY_REV_V1}"
PROBE_REV = "admission-probe-1"

# 本实现可执行的冻结政策版本集（复核 R5：版本绑定，拒绝未支持版本）。
_SUPPORTED_POLICY_REVS = (POLICY_REV_V1, POLICY_REV_V2_DEV)
# v1 冻结语义：in_scope 只接受 research_report；dev 政策在文件里显式声明放宽集合。
_DEFAULT_ALLOWED_MATERIALS: tuple[MaterialType, ...] = (MaterialType.RESEARCH_REPORT,)
_SCOPE_PRODUCTION = "production"
_SCOPE_DEV = "dev"

_FEATURE_IDS = (
    "title_type_marker",
    "byline_institution",
    "heading_hierarchy",
    "speaker_turns",
    "qa_markers",
    "transcript_declaration",
)

# 政策 §decision_order 2：领域 ∈ {company, industry, macro}（v1 冻结语义）。
_ALLOWED_DOMAINS_V1: tuple[ResearchDomain, ...] = (
    ResearchDomain.COMPANY,
    ResearchDomain.INDUSTRY,
    ResearchDomain.MACRO,
)

_REASON_ORDER = {code: index for index, code in enumerate(AdmissionReasonCode)}


class AdmissionError(ValueError):
    """准入输入非法或政策不满足冻结要求（fail-closed）。"""


class ProbeValue(enum.StrEnum):
    """特征探查值域（政策 §interface.probe）。"""

    MATCHED = "matched"
    ABSENT = "absent"
    UNREADABLE = "unreadable"


@dataclass(frozen=True)
class FeatureProbe:
    """单特征探查结果（政策 §interface.probe 输出）。"""

    feature_id: str
    value: ProbeValue
    source_locator: str
    extractor_rev: str = PROBE_REV
    detail: str = ""  # 命中类别（如 title_type_marker 的 minutes/broker）


@dataclass(frozen=True)
class ProbeInput:
    """特征探查的纯文本输入（由调用方从 reader/clean 结果装配）。"""

    title: str  # 文件名+标题候选（非批准凭证）
    head_text: str  # 首页头部区域文本
    body_lines: tuple[str, ...]  # 正文行流
    heading_texts: tuple[str, ...]  # 标题单元文本（前 50 个参与判定）


@dataclass(frozen=True)
class SourceDescriptor:
    """decide_admission 的来源输入（政策 §interface.inputs.source）。"""

    source_id: str  # 完整来源哈希（sha256）
    fmt: DocumentFormat
    location: str  # 登记位置；路径/标题不是批准凭证
    title: str
    domain_hint: ResearchDomain | None = None  # 登记元数据，非批准凭证


@dataclass(frozen=True)
class AdmissionPolicy:
    """已校验的冻结政策（policy_rev + 允许领域/材料 + 是否 dev lane；探查上限内置）。

    ``scope=dev`` 的政策只在调用方显式 ``allow_dev_lane`` 时可装载，且其材料放宽
    只对 ``dev_lane_sources``（U 指定来源的 source_id）生效——生产判定不受影响。
    """

    policy_rev: str
    allowed_domains: tuple[ResearchDomain, ...]
    allowed_materials: tuple[MaterialType, ...] = _DEFAULT_ALLOWED_MATERIALS
    scope: str = _SCOPE_PRODUCTION
    lane_id: str | None = None
    dev_lane_sources: tuple[str, ...] = ()


# --- 政策 §features 的冻结表达式（有序首中；上限内置） ---

_TITLE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("minutes", re.compile(r"纪要|实录|电话会|业绩会|交流会")),
    ("committee", re.compile(r"投委会")),
    ("pipeline", re.compile(r"README|^c[0-9]_|^c[0-9]c[0-9]_")),
    (
        "personal",
        re.compile(r"复盘|盘面回顾|市场回顾|Substack|Simons|Capital-?Wars|Macro-?Charts|小红书"),
    ),
    (
        "broker",
        re.compile(r"证券|jpmorgan|J\.?P\.?Morgan|Goldman|GS[：: \u4e00-\u9fff]|高盛|摩根大通"),
    ),
)
_BYLINE_BROKER = re.compile(r"证券|jpmorgan|J\.?P\.?Morgan|Goldman|GS\b|高盛|摩根大通")
_BYLINE_PERSONAL = re.compile(r"James-?Bulltard|Simons|Capital-?Wars")
_HEADING_MARKER = re.compile(r"^(#+\s|\d+(?:\.\d+)*[、\.． ]|[一二三四五六七八九十]+[、\.．])")
_SPEAKER_PREFIX = re.compile(r"^([^，。\n：:]{1,12})[：:]\s")
_QA_MARKER = re.compile(r"^(Q\s*[0-9]*\s*[：:]|(?:提问|投资者|分析师)\s*[：:])")
_TRANSCRIPT_DECLARATION = re.compile(r"会议纪要|电话会议|业绩说明会|实录|发言实录|转写|速记")


def _probe(feature_id: str, value: ProbeValue, locator: str, detail: str = "") -> FeatureProbe:
    return FeatureProbe(feature_id=feature_id, value=value, source_locator=locator, detail=detail)


def probe_features(payload: ProbeInput) -> tuple[FeatureProbe, ...]:
    """按政策 §features 逐特征探查；扫描上限内置（title 200 / head 400 / 行 200 / 声明 2000）。"""
    title = payload.title[:200]
    if title.strip():
        detail = ""
        for class_name, pattern in _TITLE_PATTERNS:  # 有序首中
            if pattern.search(title):
                detail = class_name
                break
        title_probe = (
            _probe("title_type_marker", ProbeValue.MATCHED, "title[0:200]", detail)
            if detail
            else _probe("title_type_marker", ProbeValue.ABSENT, "title[0:200]")
        )
    else:
        title_probe = _probe("title_type_marker", ProbeValue.UNREADABLE, "title[0:200]")

    head = payload.head_text[:400]
    if head.strip():
        if _BYLINE_BROKER.search(head):
            byline_probe = _probe("byline_institution", ProbeValue.MATCHED, "head[0:400]", "broker")
        elif _BYLINE_PERSONAL.search(head):
            byline_probe = _probe(
                "byline_institution", ProbeValue.MATCHED, "head[0:400]", "personal"
            )
        else:
            byline_probe = _probe("byline_institution", ProbeValue.ABSENT, "head[0:400]")
    else:
        byline_probe = _probe("byline_institution", ProbeValue.UNREADABLE, "head[0:400]")

    text_present = bool(
        payload.head_text.strip() or any(line.strip() for line in payload.body_lines)
    )
    headings = payload.heading_texts[:50]
    if not text_present and not headings:
        heading_probe = _probe("heading_hierarchy", ProbeValue.UNREADABLE, "headings[0:50]")
    else:
        hits = sum(1 for heading in headings if _HEADING_MARKER.match(heading))
        heading_probe = (
            _probe("heading_hierarchy", ProbeValue.MATCHED, "headings[0:50]")
            if hits >= 2
            else _probe("heading_hierarchy", ProbeValue.ABSENT, "headings[0:50]")
        )

    lines = payload.body_lines[:200]
    if not lines:
        speaker_probe = _probe("speaker_turns", ProbeValue.UNREADABLE, "lines[0:200]")
        qa_probe = _probe("qa_markers", ProbeValue.UNREADABLE, "lines[0:200]")
    else:
        prefixes = {
            match.group(1).strip() for line in lines if (match := _SPEAKER_PREFIX.match(line))
        }
        if len(prefixes) >= 3:
            speaker_probe = _probe("speaker_turns", ProbeValue.MATCHED, "lines[0:200]")
        else:
            # 恰为『问：/答：』两前缀（自设问答）→ absent（政策 §features.speaker_turns）。
            speaker_probe = _probe("speaker_turns", ProbeValue.ABSENT, "lines[0:200]")
        qa_hits = sum(1 for line in lines if _QA_MARKER.match(line))
        qa_probe = (
            _probe("qa_markers", ProbeValue.MATCHED, "lines[0:200]")
            if qa_hits >= 2
            else _probe("qa_markers", ProbeValue.ABSENT, "lines[0:200]")
        )

    window = (payload.head_text + "\n" + "\n".join(payload.body_lines))[:2000]
    if not window.strip():
        transcript_probe = _probe(
            "transcript_declaration", ProbeValue.UNREADABLE, "content[0:2000]"
        )
    elif _TRANSCRIPT_DECLARATION.search(window):
        transcript_probe = _probe("transcript_declaration", ProbeValue.MATCHED, "content[0:2000]")
    else:
        transcript_probe = _probe("transcript_declaration", ProbeValue.ABSENT, "content[0:2000]")

    return (
        title_probe,
        byline_probe,
        heading_probe,
        speaker_probe,
        qa_probe,
        transcript_probe,
    )


def load_admission_policy(
    path: str | Path, *, allow_dev_lane: bool = False
) -> AdmissionPolicy:
    """装载 I0A-3 冻结政策文件；frozen/auto_decision/版本绑定/deve lane 校验 fail-closed。

    复核 R5：``policy_rev`` 必须属于本实现绑定的受支持版本集——拒绝未支持版本，
    不以硬编码 v1 规则冒充任意版本的执行语义；政策升级须同步扩展实现并重跑验证。

    dev lane（U 2026-09-20 裁决）：``scope=dev`` 的政策**不得**在生产路径装载——
    除调用方显式传 ``allow_dev_lane=True`` 外一律拒绝；且其材料放宽只在
    ``dev_lane.sources``（U 指定来源的 source_id）上生效。v1 冻结政策不含
    ``scope``/``allowed_materials`` 字段，落到默认（仅 research_report）语义。
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise AdmissionError("admission policy 必须是 JSON 对象")
    policy_rev = data.get("policy_rev")
    if not isinstance(policy_rev, str) or not policy_rev.startswith("v"):
        raise AdmissionError(f"admission policy policy_rev 非法: {policy_rev!r}")
    if policy_rev not in _SUPPORTED_POLICY_REVS:
        raise AdmissionError(
            f"admission policy 版本不受支持: {policy_rev!r}"
            f"（本实现绑定 {_SUPPORTED_POLICY_REVS}；升级政策须同步扩展实现并重跑验证）"
        )
    if data.get("frozen") is not True:
        raise AdmissionError("admission policy 未冻结，不得用于准入判定")
    auto = data.get("auto_decision")
    if not isinstance(auto, dict) or auto.get("enabled") is not False:
        raise AdmissionError("admission policy 自动准入未显式禁用，fail-closed")

    scope = data.get("scope", _SCOPE_PRODUCTION)
    if scope not in (_SCOPE_PRODUCTION, _SCOPE_DEV):
        raise AdmissionError(f"admission policy scope 非法: {scope!r}")
    if scope == _SCOPE_DEV and not allow_dev_lane:
        raise AdmissionError(
            "dev lane 政策不得在生产路径装载（需调用方显式 allow_dev_lane=True）"
        )

    raw_materials = data.get("allowed_materials")
    if raw_materials is None:
        if scope == _SCOPE_DEV:
            raise AdmissionError("dev lane 政策必须显式声明 allowed_materials")
        allowed_materials = _DEFAULT_ALLOWED_MATERIALS
    else:
        if not isinstance(raw_materials, list) or not raw_materials:
            raise AdmissionError("admission policy allowed_materials 必须是非空数组")
        try:
            allowed_materials = tuple(MaterialType(item) for item in raw_materials)
        except ValueError as exc:
            raise AdmissionError(f"admission policy allowed_materials 含非法材料: {exc}") from exc

    lane_id: str | None = None
    dev_lane_sources: tuple[str, ...] = ()
    if scope == _SCOPE_DEV:
        lane = data.get("dev_lane")
        if not isinstance(lane, dict):
            raise AdmissionError("dev lane 政策缺少 dev_lane 块")
        lane_id = lane.get("lane_id")
        if not isinstance(lane_id, str) or not lane_id:
            raise AdmissionError("dev lane 缺少 lane_id")
        sources = lane.get("sources")
        if not isinstance(sources, list) or not sources:
            raise AdmissionError("dev lane 必须列出 sources（U 指定来源）")
        ids: list[str] = []
        for item in sources:
            source_id = item.get("source_id") if isinstance(item, dict) else None
            if not isinstance(source_id, str) or len(source_id) != 64:
                raise AdmissionError(f"dev lane sources[].source_id 非法: {source_id!r}")
            ids.append(source_id)
        dev_lane_sources = tuple(ids)

    return AdmissionPolicy(
        policy_rev=policy_rev,
        allowed_domains=_ALLOWED_DOMAINS_V1,
        allowed_materials=allowed_materials,
        scope=scope,
        lane_id=lane_id,
        dev_lane_sources=dev_lane_sources,
    )


def _effective_decision(
    decisions: list[ReviewedDecision], reasons: list[AdmissionReasonCode]
) -> ReviewedDecision | None:
    """解析显式取代历史（复核 F5：全连通分量检查，而非仅查唯一 tip）。

    合法历史必须满足：decision_id 唯一、取代目标全部存在（无断链）、
    根（不取代任何决定）恰好一个、沿根的子链无分支、且链覆盖全部决定
    （孤立分量/独立环不得旁路生效）。任一不满足即 conflicting_review，
    不凭时间最新猜测覆盖。
    """
    if not decisions:
        return None
    by_id: dict[str, ReviewedDecision] = {}
    for decision in decisions:
        if decision.decision_id in by_id:
            reasons.append(AdmissionReasonCode.CONFLICTING_REVIEW)  # decision_id 重复
            return None
        by_id[decision.decision_id] = decision
    for decision in decisions:
        if decision.supersedes is not None and decision.supersedes not in by_id:
            reasons.append(AdmissionReasonCode.CONFLICTING_REVIEW)  # 断链：取代指向不存在的决定
            return None
    children: dict[str, list[str]] = {}
    roots: list[str] = []
    for decision in decisions:
        if decision.supersedes is None:
            roots.append(decision.decision_id)
        else:
            children.setdefault(decision.supersedes, []).append(decision.decision_id)
    if len(roots) != 1:
        # 无根（纯环）或多根（多未决/多条独立链）→ 不猜测覆盖。
        reasons.append(AdmissionReasonCode.CONFLICTING_REVIEW)
        return None
    chain: list[str] = [roots[0]]
    while True:
        kids = children.get(chain[-1], ())
        if len(kids) > 1:
            reasons.append(AdmissionReasonCode.CONFLICTING_REVIEW)  # 分支：同一决定被多次取代
            return None
        if not kids:
            break
        chain.append(kids[0])
    if len(chain) != len(by_id):
        # 孤立分量（如独立成环的 a↔b 旁路唯一链）未进入链 → 历史不可解释。
        reasons.append(AdmissionReasonCode.CONFLICTING_REVIEW)
        return None
    return by_id[chain[-1]]


def _material_suggestion(
    probes: tuple[FeatureProbe, ...],
) -> tuple[MaterialType, list[AdmissionReasonCode], list[str]]:
    """机器材料类型建议 + 混合/不可读复核建议 + 证据引用（不自动纳入/排除）。"""
    by_id: dict[str, FeatureProbe] = {}
    for probe in probes:
        if probe.feature_id in by_id:
            raise AdmissionError(f"特征重复探查: {probe.feature_id}")
        by_id[probe.feature_id] = probe
    missing = [feature_id for feature_id in _FEATURE_IDS if feature_id not in by_id]
    if missing:
        raise AdmissionError(f"缺少特征探查结果: {missing}")

    title_probe = by_id["title_type_marker"]
    transcript_signals = any(
        by_id[feature_id].value is ProbeValue.MATCHED
        for feature_id in ("speaker_turns", "qa_markers", "transcript_declaration")
    )
    detail = title_probe.detail if title_probe.value is ProbeValue.MATCHED else ""
    type_by_title = {
        "minutes": MaterialType.INTERNAL_UNATTRIBUTED,
        "committee": MaterialType.INTERNAL_COMMITTEE_REPORT,
        "pipeline": MaterialType.PIPELINE_ARTIFACT,
        "personal": MaterialType.PERSONAL_OR_EXTERNAL_SUBSCRIPTION,
        "broker": MaterialType.RESEARCH_REPORT,
    }
    material = (
        type_by_title[detail]
        if detail
        else (MaterialType.INTERNAL_UNATTRIBUTED if transcript_signals else MaterialType.UNKNOWN)
    )
    reasons: list[AdmissionReasonCode] = []
    # 单一『会议/专家/Q/A』词不直接决定类型；混合信号只记复核建议（政策 §decision_order 4）。
    if transcript_signals and detail not in ("", "minutes"):
        reasons.append(AdmissionReasonCode.MIXED_MATERIAL)
    unreadable = [probe.feature_id for probe in probes if probe.value is ProbeValue.UNREADABLE]
    if unreadable:  # unreadable ≠ absent：探查不到内容必须显式记账
        reasons.append(AdmissionReasonCode.UNREADABLE_PROBE)
    evidence = [
        f"{probe.feature_id}={probe.value.value}" + (f":{probe.detail}" if probe.detail else "")
        for probe in probes
        if probe.value is not ProbeValue.ABSENT
    ]
    return material, reasons, evidence


def resolve_review_chain(
    decisions: tuple[ReviewedDecision, ...],
) -> tuple[ReviewedDecision | None, tuple[AdmissionReasonCode, ...]]:
    """公开的显式取代链解析（full-review C4：引擎免探查排除复用同一判定）。

    返回 ``(链尾有效决定, 冲突原因)``：链不可解释（断链/多根/分支/孤立分量/
    decision_id 重复）时决定为 ``None`` 且原因含 ``conflicting_review``；
    无决定时 ``(None, ())``。引擎据此把「明确排除」与「需完整探查」分流，
    两处使用同一实现，不出现第二套链语义。
    """
    reasons: list[AdmissionReasonCode] = []
    effective = _effective_decision(list(decisions), reasons)
    return effective, tuple(reasons)


# 免探查排除的显式证据占位（full-review C4）：排除资格不依赖解析成功，
# 但也不留虚假探查结论——证据明确记录「本判定跳过了内容级探查及原因」。
EXCLUSION_FAST_PATH_EVIDENCE = "probe=skipped:exclusion_fast_path"


def decide_exclusion_without_probe(
    source: SourceDescriptor,
    policy: AdmissionPolicy,
    effective: ReviewedDecision,
) -> Admission:
    """明确排除的免探查判定（full-review C4）：撤销资格不依赖解析成功。

    前置条件由调用方（engine）核验：全部决定绑定同源哈希、无 invalid_locator、
    :func:`resolve_review_chain` 干净解析为排除类决定。材料未知不阻断排除
    （排除决定本身即批准凭证，材料语义只影响纳入判定）；探查证据以显式占位
    记录，不猜测材料类型、不编造探查特征。
    """
    return _admission_of(
        source,
        policy,
        AdmissionDecision.EXCLUDED_BY_POLICY,
        MaterialType.UNKNOWN,
        [],
        [EXCLUSION_FAST_PATH_EVIDENCE, f"review_ref={effective.decision_id}"],
        review_ref=effective.decision_id,
        scope_ref=effective.scope_ref,
    )


def decide_admission(
    source: SourceDescriptor,
    reviewed_decisions: tuple[ReviewedDecision, ...],
    probes: tuple[FeatureProbe, ...],
    policy: AdmissionPolicy,
) -> Admission:
    """固定判定次序的纯函数准入判定；同输入同 policy_rev 同结果。

    ``probe_reasons``（mixed_material/unreadable_probe）只是复核建议，
    全程不阻断唯一有效人工决定（政策 §decision_order 4，十问十答先例）；
    阻断类原因（missing_review/conflicting_review/source_changed/
    invalid_locator/policy_conflict/scope_upgrade_rejected/unsupported_domain）
    单独累积并驱动判定。
    """
    material, probe_reasons, evidence = _material_suggestion(probes)
    reasons: list[AdmissionReasonCode] = []  # 阻断类原因

    # ---- 次序 1：审核绑定完整性（source_changed / invalid_locator / conflicting_review）----
    if any(decision.source_id != source.source_id for decision in reviewed_decisions):
        reasons.append(AdmissionReasonCode.SOURCE_CHANGED)
    mine = [decision for decision in reviewed_decisions if decision.source_id == source.source_id]
    for decision in mine:
        if decision.scope_ref and not decision.locators:
            reasons.append(AdmissionReasonCode.INVALID_LOCATOR)
    effective = _effective_decision(mine, reasons)
    if reasons:
        return _admission_of(
            source,
            policy,
            AdmissionDecision.REVIEW_REQUIRED,
            material,
            reasons + probe_reasons,
            evidence,
            review_ref=None,
            scope_ref=None,
        )

    # ---- 次序 3（无有效决定）：未决不能发布 ----
    if effective is None:
        return _admission_of(
            source,
            policy,
            AdmissionDecision.REVIEW_REQUIRED,
            material,
            [AdmissionReasonCode.MISSING_REVIEW, *probe_reasons],
            evidence,
            review_ref=None,
            scope_ref=None,
        )

    # ---- 次序 2：唯一有效人工决定 ----
    if effective.decision in (ReviewDecision.EXCLUDED, ReviewDecision.EXCLUDED_FROM_ACTIVE):
        return _admission_of(
            source,
            policy,
            AdmissionDecision.EXCLUDED_BY_POLICY,
            material,
            probe_reasons,
            evidence,
            review_ref=effective.decision_id,
            scope_ref=effective.scope_ref,
        )
    # admitted：
    # 人工凭证（full-review §6 静态收口）：绑定同源哈希的人工决定显式给出的
    # 材料类型/领域优先于登记提示与机器建议（凭证是批准依据，提示不是）。
    effective_material = effective.material_type or material
    effective_domain = effective.research_domain or source.domain_hint
    order2: list[AdmissionReasonCode] = []
    # 材料类型门：v1 冻结语义 = 仅 research_report/unknown。dev lane 政策（scope=dev）
    # 可另行声明 allowed_materials，但**只对 dev_lane_sources 内 U 指定来源**生效；
    # 其余来源仍按冻结语义拒绝（生产判定不变，见 tests 的 dev lane 反例）。
    material_ok = effective_material in (MaterialType.RESEARCH_REPORT, MaterialType.UNKNOWN)
    if not material_ok and policy.scope == _SCOPE_DEV:
        material_ok = (
            source.source_id in policy.dev_lane_sources
            and effective_material in policy.allowed_materials
        )
    if not material_ok:
        # 冻结范围仅纳入分析师研报；admitted 非研报材料与政策冲突 → 复核。
        order2.append(AdmissionReasonCode.POLICY_CONFLICT)
    if effective.locators and not effective.scope_ref:
        # 部分章节批准须有明确坐标，不得升级为整篇纳入。
        order2.append(AdmissionReasonCode.SCOPE_UPGRADE_REJECTED)
    if effective_domain is None or effective_domain not in policy.allowed_domains:
        order2.append(AdmissionReasonCode.UNSUPPORTED_DOMAIN)
    if order2:
        # 冲突复核保留检出类型以呈现冲突（人工凭证优先，其次机器检出）；
        # 无检出视作审阅人认定的研报。
        blocked_material = (
            effective_material
            if effective_material not in (MaterialType.RESEARCH_REPORT, MaterialType.UNKNOWN)
            else MaterialType.RESEARCH_REPORT
        )
        return _admission_of(
            source,
            policy,
            AdmissionDecision.REVIEW_REQUIRED,
            blocked_material,
            order2 + probe_reasons,
            evidence,
            review_ref=effective.decision_id,
            scope_ref=effective.scope_ref,
        )
    # in_scope 落地的材料类型：v1 恒为 research_report（unknown 视作审阅人认定的研报）；
    # dev lane 下如实记录人工凭证的类型（如 internal_committee_report），不伪造为研报。
    in_scope_material = (
        MaterialType.RESEARCH_REPORT
        if effective_material is MaterialType.UNKNOWN
        else effective_material
    )
    dev_evidence = (
        [f"dev_lane={policy.lane_id}", f"admitted_material={effective_material.value}"]
        if policy.scope == _SCOPE_DEV
        and in_scope_material is not MaterialType.RESEARCH_REPORT
        else []
    )
    return _admission_of(
        source,
        policy,
        AdmissionDecision.IN_SCOPE,
        in_scope_material,
        probe_reasons,
        [*evidence, *dev_evidence],
        review_ref=effective.decision_id,
        scope_ref=effective.scope_ref,
        research_domain=effective_domain,
    )


def _admission_of(
    source: SourceDescriptor,
    policy: AdmissionPolicy,
    decision: AdmissionDecision,
    material: MaterialType,
    reasons: list[AdmissionReasonCode],
    evidence: list[str],
    *,
    review_ref: str | None,
    scope_ref: str | None,
    research_domain: ResearchDomain | None = None,
) -> Admission:
    ordered = sorted(set(reasons), key=lambda code: _REASON_ORDER[code])
    # v1 下 rule_rev == RULE_REV（逐字不变，decision_id 稳定）；dev 政策另起 rule_rev
    # 使 dev 判定与生产判定指纹可区分。
    rule_rev = f"decision-order-{policy.policy_rev}"
    decision_id = canonical_fingerprint(
        [
            rule_rev,
            policy.policy_rev,
            source.source_id,
            decision.value,
            material.value,
            research_domain.value if research_domain else None,
            [code.value for code in ordered],
            review_ref,
            scope_ref,
        ]
    )
    return Admission(
        decision_id=decision_id,
        source_id=source.source_id,
        material_type=material,
        research_domain=research_domain,
        decision=decision,
        policy_rev=policy.policy_rev,
        reason_codes=tuple(ordered),
        scope_ref=scope_ref,
        evidence_refs=tuple(evidence),
        review_ref=review_ref,
        rule_rev=rule_rev,
    )
