"""I3-2 补料（规则 ``evidence-mapping-6``）：把冻结预期转成**可审核的固定映射**。

**这是机器候选，不是人工金标。** 批准只能通过 ``i3s2_apply_decisions.py`` 的
"独立审批件 → 批准投影 → 完整性门"路径产生；候选文件里的 ``adjudication.status``
是信息字段，**改它不能开门**。

v6 额外修复审批 B1—B5：来源绑定、答案约束隔离、原文承载映射、身份与投影核验。
下列记录 v5 相对 ``evidence-mapping-4`` 的第二轮独立复核修复
（``audits/20260918-i32-adjudication-review`` 的 A1—A5）：

- **A4 数值与限定并行登记**：按 ``，,；;。`` 切**段**；段内含数值时，若同时出现限定/口径标记
  （必须/须/需/不得/不能/区分/标明/所述/样本/口径/限定…），**另立**定性要件——旧版只在
  "整段无强数值"时才建定性要件，导致 ``macro-003``「必须区分附条件判断、市场预期和正式决定」、
  ``company-001``「年度对应/维持强推/标明预测」在账上消失。
- **A3 不再把词面相近当成锚点**：每条机器锚点都算 ``uncovered_terms``（段内**判别性**词元中
  未被该 item 覆盖的部分）与 ``adequacy``（``full`` / ``partial``）。``partial`` 的锚点明确写
  "需补标注或改选，不得直接批准"；非首选候选标 ``search_hint``（仅供检索线索，不进可批准集合）。
- **A5 角色与展示**：``required`` / ``supplementary``（补充，**非必需**，不声明等价替代关系）/
  ``suggested``（待批准锚点）；不再使用"可替代"这一会误导的说法。裁决单直接展示
  ``source_coverage`` 项下的锚点候选，不再让 U 去 JSON 里找。
- **A2 审批覆盖**：``pending_human`` 只是"要件级"队列；每题另有**整题验收**要求
  （对照冻结 ``evidence_requirement``），负例另有覆盖确认，来源槽位人工状态矛盾另有澄清项。
  三者都不再由机器代决，全部写进裁决单与裁决应用器的校验。

- **A1**：完整性门不再看 ``adjudication.status``。它只按审批件逐项核对（见
  ``i3s2_apply_decisions.py``），因此"把状态全改 approved"不会放行。

数值等价：requirement 的 ``13.40`` 与原文逐字 ``13.4`` 视为同一数值，**原文 quote 不改写**，
等价事实单独入队交人工确认。答案侧口径记 ``answer_constraints`` 并标注后续核验落点
（I3-5 答案侧检查），不冒充证据评分。

输入（均只读冻结件，**不读原文正文**）：

- ``query-gold-frozen.jsonl``：30 题（company/industry/macro 各 10，含 6 道 no_answer 负例）
- ``source-gold-frozen.jsonl``：23 个**人工标注**槽位（reviewer=xyl；I0A-4 冻结门已校验
  quote 为原文子串）

产物（write-once；重跑时自动把当前产物归档为 ``-v<n>`` 再写新版，历史不覆盖）：

- ``i3-2/evidence-targets-candidates.json``：机器候选（要求覆盖账 + 裁决队列）
- ``i3-2/evidence-targets-review.md``：逐题核对单
- ``i3-2/evidence-targets-adjudication.md``：**人工裁决单**（候选与批准件分开存储）

用法::

    env -u PYTHONPATH uv run python \
        .scratch/corpus-evidence-pipeline/ingestion-rebuild/i3s2_evidence_targets.py
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[2]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from i3s2_textutil import (  # noqa: E402
    EVIDENCE_MARKERS,
    KIND_PRIORITY,
    NOTE_REF,
    PAGE_HINT,
    SOURCE_REF_MARKERS,
    USAGE_MARKERS,
    VALUE_SEGMENT_MARKERS,
    content_units,
    item_text,
    mask_dates,
    match_token,
    overlap,
    segments_of,
    unit_stats,
    value_tokens,
)

QUERY_GOLD = BASE / "query-gold-frozen.jsonl"
SOURCE_GOLD = BASE / "source-gold-frozen.jsonl"
OUT_DIR = BASE / "i3-2"
OUT_JSON = OUT_DIR / "evidence-targets-candidates.json"
OUT_MD = OUT_DIR / "evidence-targets-review.md"
OUT_ADJ = OUT_DIR / "evidence-targets-adjudication.md"

RULE_REV = "evidence-mapping-6"
_BROAD_LIMIT = 8
_PREVIEW_LIMIT = 24
_SUGGESTION_LIMIT = 3
_MIN_SHARED_UNITS = 2

_ANSWER_VERIFY_POINT = "I3-5（答案侧检查）"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fail(message: str) -> None:
    print(f"I3S2 EVIDENCE MAPPING FAILED: {message}")
    sys.exit(1)


def load_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def locator_of(slot: Mapping[str, object]) -> dict[str, str]:
    locator = slot.get("locator") or {}
    if not isinstance(locator, Mapping):
        return {}
    return {str(key): str(value) for key, value in locator.items() if value not in (None, "")}


def page_of(slot: Mapping[str, object]) -> int:
    raw = locator_of(slot).get("page")
    try:
        return int(str(raw))
    except (TypeError, ValueError):
        return 10**6


def item_locator_tokens(slot: Mapping[str, object], item: Mapping[str, object]) -> list[str]:
    """定位 token = 槽位 page + 表格单元格行列身份（I3-1 由权威侧产出）。"""

    tokens = [f"page:{value}" for value in locator_of(slot).values()]
    for key in ("row", "col"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            tokens.append(f"{key}:{value.strip()}")
    return tokens


def constraints_of(item: Mapping[str, object]) -> dict[str, str | None]:
    return {
        key: (item.get(key) if isinstance(item.get(key), str) else None)
        for key in ("row", "col", "cell", "unit", "period")
    }


def split_items(slot: Mapping[str, object]) -> list[tuple[int, Mapping[str, object]]]:
    items = slot.get("expected_items") or ()
    if not isinstance(items, Sequence):
        return []
    return [(index, item) for index, item in enumerate(items) if isinstance(item, Mapping)]


def _slot_by_id(pool: Sequence[Mapping[str, object]], gold_id: str) -> Mapping[str, object]:
    for slot in pool:
        if str(slot.get("gold_id")) == gold_id:
            return slot
    return {}


def _item_by_index(slot: Mapping[str, object], index: int) -> Mapping[str, object]:
    for candidate_index, item in split_items(slot):
        if candidate_index == index:
            return item
    return {}


def _human_basis_pending(text: str) -> bool:
    return any(marker in text for marker in ("待真人复核", "需真人确认", "待人工"))


def expand_clause(clause: str) -> list[str]:
    """子句 → 段：默认整句一段；**仅当**该子句既有数值又有标记时，才按逗号细分，
    把"限定/口径"从数值旁边拆出来（复核 A4）。无差别逗号切分会把"约四个月""均下降"
    这类从属短语切成无锚点的假缺口，故不做。
    """

    masked, _periods = mask_dates(clause)
    strong, _weak = value_tokens(masked)
    has_marker = any(marker in clause for marker in VALUE_SEGMENT_MARKERS)
    if strong and has_marker:
        parts = [part.strip() for part in re.split(r"[，,]", clause) if part.strip()]
        if len(parts) > 1:
            return parts
    return [clause]


def base_question(question: Mapping[str, object]) -> dict[str, object]:
    return {
        "query_id": str(question["query_id"]),
        "domain": question.get("domain"),
        "answer_existence": question.get("answer_existence"),
        "satisfy_rule": question.get("satisfy_rule"),
        "relevant_sources": list(question.get("relevant_sources") or []),
        "evidence_required": True,
        "machine_status": "",
        "machine_status_reason": "",
        "adjudication": {
            "status": "pending",
            "reviewer": None,
            "reviewed_at": None,
            "note": (
                "本字段仅作信息展示：批准必须走 evidence-targets-decisions.json → "
                "i3s2_apply_decisions.py 的批准投影，直接改本字段不会打开完整性门"
            ),
        },
        "requirement_clauses": [],
        "requirement_facets": [],
        "answer_constraints": [],
        "targets": [],
        "pending_human": [],
        "unmatched_tokens": [],
        "weak_tokens": [],
        "period_tokens": [],
        "page_hints": [],
        "candidate_slots": [],
        "item_without_quote": [],
        "review_candidates": [],
        "item_coverage": {"by_slot": {}, "by_role": {}},
    }


def preview_of(pool: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    """人工指定证据目标时的候选 item 预览（**完整 quote + 定位**，不做截断）。"""

    previews: list[dict[str, object]] = []
    for slot in pool:
        for index, item in split_items(slot):
            quote = item.get("quote")
            previews.append(
                {
                    "slot": str(slot.get("gold_id")),
                    "source_id": str(slot.get("source_id")),
                    "item_index": index,
                    "kind": item.get("kind"),
                    "locator": item_locator_tokens(slot, item),
                    "quote": quote if isinstance(quote, str) else "",
                    "text": item.get("text"),
                }
            )
    return previews


def _suggestion(
    slot: Mapping[str, object],
    index: int,
    item: Mapping[str, object],
    segment: str,
    why: str,
    primary: bool,
    frequency: Mapping[str, int],
    total_items: int,
) -> dict[str, object]:
    # Metadata helps rank candidates, but cannot prove a condition appeared in source text.
    missing = sorted(content_units(segment) - content_units(str(item.get("quote") or "")))
    return {
        "slot": str(slot.get("gold_id")),
        "source_id": str(slot.get("source_id")),
        "item_index": index,
        "kind": item.get("kind"),
        "locator": item_locator_tokens(slot, item),
        "quote": str(item.get("quote") or ""),
        "why": why,
        "role": "primary" if primary else "search_hint",
        "adequacy": "full" if not missing else "partial",
        "uncovered_terms": missing,
    }


def suggest_for_segment(
    segment: str,
    pool: Sequence[Mapping[str, object]],
    source_ids: set[str],
    weights: Mapping[str, float],
    frequency: Mapping[str, int],
    total_items: int,
) -> list[dict[str, object]]:
    """定性要件的机器锚点建议：``note_ref``（显式注号）优先，否则按 IDF 加权重叠排序。

    建议**只是建议**：``role=primary`` 的才进待批准集合；``search_hint`` 仅供检索线索。
    ``adequacy=partial`` 的锚点必须补标注或改选，不得直接批准（复核 A3）。
    """

    notes = set(NOTE_REF.findall(segment))
    if notes:
        anchored: list[dict[str, object]] = []
        for slot in pool:
            for index, item in split_items(slot):
                quote = str(item.get("quote") or "")
                text = str(item.get("text") or "")
                if any(f"注{note}" in text or f"注{note}" in quote for note in notes):
                    anchored.append(
                        _suggestion(
                            slot,
                            index,
                            item,
                            segment,
                            f"note_ref(注{','.join(sorted(notes))})",
                            True,
                            frequency,
                            total_items,
                        )
                    )
        if anchored:
            return anchored[:_SUGGESTION_LIMIT]

    ranked: list[tuple[int, float, float, int, Mapping[str, object], int]] = []
    for slot in pool:
        for index, item in split_items(slot):
            shared, score, ratio = overlap(segment, item, weights)
            if shared >= _MIN_SHARED_UNITS:
                ranked.append(
                    (
                        shared,
                        score,
                        ratio,
                        KIND_PRIORITY.get(str(item.get("kind") or ""), 0),
                        slot,
                        index,
                    )
                )
    ranked.sort(key=lambda row: (-row[1], -row[0], -row[2], -row[3], page_of(row[4]), row[5]))
    chosen: list[tuple[int, float, float, int, Mapping[str, object], int]] = []
    primary: set[tuple[str, int]] = set()
    if len(source_ids) > 1:  # 多来源题：先保证每个来源都有首选，避免建议全落在一份材料
        for source in sorted(source_ids):
            for row in ranked:
                if str(row[4].get("source_id")) == source and row not in chosen:
                    chosen.append(row)
                    primary.add((str(row[4].get("gold_id")), row[5]))
                    break
    if not chosen and ranked:
        chosen.append(ranked[0])
        primary.add((str(ranked[0][4].get("gold_id")), ranked[0][5]))
    for row in ranked:
        if len(chosen) >= _SUGGESTION_LIMIT:
            break
        if row not in chosen:
            chosen.append(row)
    suggestions: list[dict[str, object]] = []
    for shared, score, ratio, _priority, slot, index in chosen[:_SUGGESTION_LIMIT]:
        suggestions.append(
            _suggestion(
                slot,
                index,
                _item_by_index(slot, index),
                segment,
                f"content_overlap(shared={shared}, idf={score:.2f}, ratio={ratio:.2f})",
                (str(slot.get("gold_id")), index) in primary,
                frequency,
                total_items,
            )
        )
    return suggestions


def map_question(
    question: Mapping[str, object], slots: Sequence[Mapping[str, object]]
) -> dict[str, object]:
    requirement = str(question.get("evidence_requirement") or "")
    query_id = str(question["query_id"])
    result = base_question(question)

    if question.get("answer_existence") != "answerable":
        result["evidence_required"] = False
        result["machine_status"] = "negative_opt_out"
        result["machine_status_reason"] = (
            "负例题：答案为『库中无答案』，不适用证据目标，按评分器契约显式 "
            "evidence_required=false（该例外有独立业务依据，不得用于规避证据缺口）；"
            "仍须参加误报/伪造引用检查并人工确认全文覆盖"
        )
        result["negative_check"] = {
            "checks": ["误报（断言命中）", "伪造引用", "不进入证据分母"],
            "human_basis_pending_coverage": _human_basis_pending(
                str(question.get("human_basis") or "")
            ),
            "confirmation_required": (
                "须人工确认材料全文确实没有该证据（不得以未检索到代替），"
                "并在 decisions.negative_reviews 中登记 full_text_coverage_confirmed=true"
            ),
        }
        return result

    page_hints = [f"page:{value}" for value in PAGE_HINT.findall(requirement)]
    requirement_clean = PAGE_HINT.sub("", requirement)
    relevant = tuple(str(source) for source in question.get("relevant_sources") or ())
    source_ids = set(relevant)
    pool = [slot for slot in slots if slot.get("source_id") in source_ids]

    result["page_hints"] = page_hints
    result["candidate_slots"] = [str(slot.get("gold_id")) for slot in pool]
    weights, frequency, total_items = unit_stats(pool, split_items)

    # ── 1. 要求覆盖账：段 → 数值要件 / 定性要件（并行登记，复核 A4） ─────────
    clauses: list[dict[str, object]] = []
    facets: list[dict[str, object]] = []
    all_periods: list[str] = []
    all_weak: list[str] = []
    facet_seq = 0
    segments: list[str] = []
    for clause in segments_of(requirement_clean):
        segments.extend(expand_clause(clause))
    for segment_index, segment in enumerate(segments, start=1):
        masked, periods = mask_dates(segment)
        strong, weak = value_tokens(masked)
        all_periods.extend(periods)
        for token in weak:
            if token not in all_weak:
                all_weak.append(token)
        clause_id = f"c{segment_index}"
        value_ids: list[str] = []
        qual_ids: list[str] = []
        for token in strong:
            facet_seq += 1
            facet_id = f"f{facet_seq}"
            value_ids.append(facet_id)
            facets.append(
                {
                    "facet_id": facet_id,
                    "clause_id": clause_id,
                    "kind": "value",
                    "token": token,
                    "coverage": "",
                    "candidates": [],
                }
            )
        has_value_marker = any(marker in segment for marker in VALUE_SEGMENT_MARKERS)
        if not strong or has_value_marker:
            facet_seq += 1
            facet_id = f"q{facet_seq}"
            qual_ids.append(facet_id)
            # 建议始终计算：即使该段由来源覆盖规则承接，也要把候选锚点交给 U。
            suggestions = suggest_for_segment(
                segment, pool, source_ids, weights, frequency, total_items
            )
            has_evidence_marker = any(marker in segment for marker in EVIDENCE_MARKERS)
            has_usage_marker = any(marker in segment for marker in USAGE_MARKERS)
            if len(source_ids) > 1 and any(marker in segment for marker in SOURCE_REF_MARKERS):
                coverage = "source_coverage"
            elif suggestions and (has_evidence_marker or not has_usage_marker):
                coverage = "suggested"
            elif has_usage_marker:
                coverage = "usage_constraint"
            elif suggestions:
                coverage = "suggested"
            else:
                coverage = "missing"
            primary_terms = [
                set(suggestion.get("uncovered_terms") or ())
                for suggestion in suggestions
                if suggestion.get("role") == "primary"
            ]
            # 面级"联合仍未覆盖" = 各 primary 未覆盖集合的**交集**（某锚点缺、另一锚点有的词元，
            # 不应算缺口——按并集算会把 company-008 两个来源各自的评级锚点误判成缺口）。
            union_missing = sorted(set.intersection(*primary_terms)) if primary_terms else []
            facets.append(
                {
                    "facet_id": facet_id,
                    "clause_id": clause_id,
                    "kind": "qualification",
                    "text": segment,
                    "period_tokens": periods,
                    "coverage": coverage,
                    "suggestions": suggestions,
                    # 面级覆盖度：多个 primary 联合（人工可同时选多个）仍未覆盖的判别性词元
                    "union_uncovered_terms": union_missing,
                    "union_adequacy": "full" if not union_missing else "partial",
                }
            )
            if coverage == "usage_constraint":
                result["answer_constraints"].append(  # type: ignore[union-attr]
                    {
                        "facet_id": facet_id,
                        "clause_id": clause_id,
                        "text": segment,
                        "note": (
                            "答案侧用法约束：不产生证据目标，须在答案口径上与证据同时满足；"
                            f"后续核验落点 {_ANSWER_VERIFY_POINT}"
                        ),
                        "verified_by": _ANSWER_VERIFY_POINT,
                    }
                )
        clauses.append(
            {
                "clause_id": clause_id,
                "text": segment,
                "period_tokens": periods,
                "value_facet_ids": value_ids,
                "qualification_facet_ids": qual_ids,
            }
        )
    result["requirement_clauses"] = clauses
    result["requirement_facets"] = facets
    result["period_tokens"] = sorted(set(all_periods))
    result["weak_tokens"] = all_weak

    # ── 2. 数值要件 → item 候选 ────────────────────────────────────────────
    clause_text = {entry["clause_id"]: entry["text"] for entry in clauses}
    value_facets = [facet for facet in facets if facet["kind"] == "value"]
    for facet in value_facets:
        candidates: list[dict[str, object]] = []
        for slot in pool:
            for index, item in split_items(slot):
                forms = match_token(str(facet["token"]), item_text(item))
                if not forms:
                    continue
                shared, score, ratio = overlap(str(clause_text[facet["clause_id"]]), item, weights)
                candidates.append(
                    {
                        "gold_id": str(slot.get("gold_id")),
                        "item_index": index,
                        "kind": item.get("kind"),
                        "forms": forms,
                        "exact": forms == [facet["token"]],
                        "shared_units": shared,
                        "score": score,
                        "ratio": ratio,
                        "has_quote": bool(str(item.get("quote") or "").strip()),
                    }
                )
        facet["candidates"] = candidates

    # ── 3. 必需目标 = 覆盖全部数值要件的最小集合；其余命中降 supplementary ────
    used: set[tuple[str, int]] = set()
    selection: dict[str, dict[str, object]] = {}
    for facet in value_facets:
        candidates = [cand for cand in facet["candidates"] if cand["has_quote"]]
        if not candidates:
            facet["coverage"] = "missing"
            continue
        candidates.sort(
            key=lambda cand: (
                -float(cand["score"]),
                0 if (str(cand["gold_id"]), int(cand["item_index"])) not in used else 1,
                -float(cand["ratio"]),
                -KIND_PRIORITY.get(str(cand.get("kind") or ""), 0),
                page_of(_slot_by_id(pool, str(cand["gold_id"]))),
                int(cand["item_index"]),
            )
        )
        pick = candidates[0]
        key = (str(pick["gold_id"]), int(pick["item_index"]))
        used.add(key)
        selection[str(facet["facet_id"])] = pick
        facet["coverage"] = "required"

    required_keys = sorted(used)
    matched_keys: set[tuple[str, int]] = set()
    key_tokens: dict[tuple[str, int], list[str]] = {}
    key_facets: dict[tuple[str, int], list[str]] = {}
    key_equivalents: dict[tuple[str, int], dict[str, list[str]]] = {}
    for facet in value_facets:
        for cand in facet["candidates"]:
            key = (str(cand["gold_id"]), int(cand["item_index"]))
            matched_keys.add(key)
            forms = [str(form) for form in cand["forms"]]
            if str(facet["token"]) not in key_tokens.setdefault(key, []):
                key_tokens[key].append(str(facet["token"]))
            if forms != [str(facet["token"])]:
                key_equivalents.setdefault(key, {})[str(facet["token"])] = forms
        chosen = selection.get(str(facet["facet_id"]))
        if chosen is not None:
            key = (str(chosen["gold_id"]), int(chosen["item_index"]))
            key_facets.setdefault(key, []).append(str(facet["facet_id"]))

    targets: list[dict[str, object]] = []
    item_without_quote: list[str] = []
    matched_by_key: dict[tuple[str, int], dict[str, object]] = {}
    for slot in pool:
        gold_id = str(slot.get("gold_id"))
        for index, item in split_items(slot):
            key = (gold_id, index)
            if key not in matched_keys:
                continue
            quote = item.get("quote")
            if not isinstance(quote, str) or not quote.strip():
                item_without_quote.append(f"{gold_id}#{index}")
                continue
            target = {
                "target_id": f"e{len(targets) + 1}",
                "role": "required" if key in required_keys else "supplementary",
                "quote": quote,
                "locator": item_locator_tokens(slot, item),
                "source_id": str(slot.get("source_id")),
                "constraints": constraints_of(item),
                "basis": {
                    "gold_id": gold_id,
                    "item_index": index,
                    "kind": item.get("kind"),
                    "matched_tokens": key_tokens.get(key, []),
                    "value_equivalents": key_equivalents.get(key, {}),
                    "matched_facet_ids": sorted(set(key_facets.get(key, []))),
                    "annotation_role": slot.get("annotation_role"),
                    "must_preserve": slot.get("must_preserve"),
                    "role_note": (
                        "必需证据"
                        if key in required_keys
                        else "补充证据（非必需；本版不声明替代关系）"
                    ),
                },
            }
            targets.append(target)
            matched_by_key[key] = target

    # ── 4. 定性要件：primary 锚点降 suggested（批准前不计入必需） ─────────────
    suggested: list[dict[str, object]] = []
    for facet in facets:
        if facet["kind"] != "qualification":
            continue
        for suggestion in facet.get("suggestions") or ():
            if suggestion.get("role") != "primary":
                continue
            key = (str(suggestion["slot"]), int(suggestion["item_index"]))
            existing = matched_by_key.get(key)
            if existing is not None:
                if str(facet["facet_id"]) not in existing["basis"]["matched_facet_ids"]:
                    existing["basis"]["matched_facet_ids"].append(str(facet["facet_id"]))
                suggestion["existing_target_id"] = existing["target_id"]
                continue
            duplicate = next(
                (
                    target
                    for target in suggested
                    if (str(target["basis"]["gold_id"]), int(target["basis"]["item_index"])) == key
                ),
                None,
            )
            if duplicate is not None:
                if str(facet["facet_id"]) not in duplicate["basis"]["matched_facet_ids"]:
                    duplicate["basis"]["matched_facet_ids"].append(str(facet["facet_id"]))
                continue
            quote = str(suggestion.get("quote") or "")
            if not quote.strip():
                item_without_quote.append(f"{key[0]}#{key[1]}")
                continue
            slot = _slot_by_id(pool, key[0])
            suggested.append(
                {
                    "target_id": f"s{len(suggested) + 1}",
                    "role": "suggested",
                    "quote": quote,
                    "locator": list(suggestion.get("locator") or ()),
                    "source_id": str(suggestion.get("source_id")),
                    "constraints": constraints_of(_item_by_index(slot, key[1])),
                    "basis": {
                        "gold_id": key[0],
                        "item_index": key[1],
                        "kind": suggestion.get("kind"),
                        "why": suggestion.get("why"),
                        "adequacy": suggestion.get("adequacy"),
                        "uncovered_terms": suggestion.get("uncovered_terms"),
                        "matched_facet_ids": [str(facet["facet_id"])],
                        "annotation_role": slot.get("annotation_role"),
                        "must_preserve": slot.get("must_preserve"),
                        "role_note": "待批准锚点：批准前不得计入必需证据",
                    },
                }
            )
    order = {"required": 0, "supplementary": 1, "suggested": 2}
    result["targets"] = sorted(targets, key=lambda item: order[str(item["role"])]) + suggested
    result["item_without_quote"] = item_without_quote

    # ── 5. 裁决队列（机器不代决的每一件事都显式入队） ───────────────────────
    queue: list[dict[str, object]] = []
    sequence = 0

    def _enqueue(
        kind: str, facet_id: str | None, clause_id: str | None, question: str, extra: dict
    ) -> None:
        nonlocal sequence
        sequence += 1
        queue.append(
            {
                "item_id": f"I32-{query_id}-{sequence:02d}",
                "kind": kind,
                "facet_id": facet_id,
                "clause_id": clause_id,
                "question": question,
                "suggestions": [],
                **extra,
            }
        )

    for facet in value_facets:
        facet_id = str(facet["facet_id"])
        clause_id = str(facet["clause_id"])
        clause = clause_text[clause_id]
        chosen = selection.get(facet_id)
        if chosen is None:
            _enqueue(
                "unmatched_value",
                facet_id,
                clause_id,
                f"要求里的数值 {facet['token']!r} 在人工标注槽位中找不到承载 item："
                "补标注、指定其他承载 item，或裁定该数值不作为必需证据",
                {"token": facet["token"], "clause": clause},
            )
            continue
        forms = [str(form) for form in chosen["forms"]]
        if forms != [str(facet["token"])]:
            _enqueue(
                "value_equivalence",
                facet_id,
                clause_id,
                f"确认数值等价：要求写作 {facet['token']!r}，原文逐字为 "
                f"{forms}（原文 quote 不改写，按同一数值接受）",
                {
                    "token": facet["token"],
                    "clause": clause,
                    "equivalents": forms,
                    "slot": chosen["gold_id"],
                    "item_index": chosen["item_index"],
                },
            )
    for facet in facets:
        if facet["kind"] != "qualification":
            continue
        coverage = str(facet["coverage"])
        facet_id = str(facet["facet_id"])
        clause_id = str(facet["clause_id"])
        suggestions = list(facet.get("suggestions") or [])
        union_missing = list(facet.get("union_uncovered_terms") or [])
        tail = (
            f"；**机器锚点联合仍未覆盖**：{'、'.join(union_missing)} —— "
            "实质缺证须改选/补标；仅词面差异可用逐项原文 lexical_review，禁止 residual 豁免"
            if union_missing
            else ""
        )
        extra = {
            "clause": facet["text"],
            "suggestions": suggestions,
            "union_adequacy": facet.get("union_adequacy"),
            "union_uncovered_terms": union_missing,
        }
        if coverage == "source_coverage":
            _enqueue(
                "source_coverage",
                facet_id,
                clause_id,
                f"该子句要求引用多份材料：{facet['text']!r}{tail}",
                extra,
            )
        elif coverage == "usage_constraint":
            _enqueue(
                "answer_constraint",
                facet_id,
                clause_id,
                f"确认答案侧口径（不产生证据目标，但答案必须满足；核验落点 {_ANSWER_VERIFY_POINT}）："
                f"{facet['text']!r}",
                extra,
            )
        elif coverage == "suggested":
            _enqueue(
                "qualification",
                facet_id,
                clause_id,
                f"确认该定性要件已由候选原文承载（或改选/裁定需补标注）：{facet['text']!r}{tail}",
                extra,
            )
        else:
            _enqueue(
                "qualification",
                facet_id,
                clause_id,
                f"该定性要件在冻结标注中没有承载 item，需人工补标注或裁定：{facet['text']!r}",
                extra,
            )
    if question.get("satisfy_rule") == "all" and len(source_ids) > 1:
        covered = {str(target["source_id"]) for target in targets if target["role"] == "required"}
        for source in sorted(source_ids - covered):
            hints: list[dict[str, object]] = []
            for facet in facets:
                if facet["kind"] != "qualification":
                    continue
                for suggestion in facet.get("suggestions") or ():
                    if str(suggestion.get("source_id")) != source:
                        continue
                    if any(
                        (str(hint["slot"]), int(hint["item_index"]))
                        == (str(suggestion["slot"]), int(suggestion["item_index"]))
                        for hint in hints
                    ):
                        continue
                    hints.append(suggestion)
            _enqueue(
                "source_coverage",
                None,
                None,
                f"该题 satisfy_rule=all：来源 {source} 目前没有必需证据目标，"
                "必须指定该来源的承载 item；若改变来源义务须另行修订金标，不能以理由豁免",
                {"source_id": source, "suggestions": hints[:_SUGGESTION_LIMIT]},
            )
    if len(required_keys) > _BROAD_LIMIT:
        _enqueue(
            "guard",
            None,
            None,
            f"必需目标数 {len(required_keys)} 超过护栏 {_BROAD_LIMIT}：请收窄或改选题型口径",
            {"required_count": len(required_keys)},
        )
    result["pending_human"] = queue

    # ── 6. 状态机（machine_status：缺标注 / 待裁决 / 机器就绪） ───────────────
    missing = [facet for facet in facets if facet.get("coverage") == "missing"]
    if missing or len(required_keys) > _BROAD_LIMIT:
        result["machine_status"] = "blocked"
        result["machine_status_reason"] = (
            f"存在无承载 item 的要件 {len(missing)} 项"
            + (
                f" 且必需目标超护栏 {len(required_keys)}"
                if len(required_keys) > _BROAD_LIMIT
                else ""
            )
            + "：需补人工标注或由 U 裁定，候选不得据此冻结为金标"
        )
    elif queue:
        result["machine_status"] = "pending_human"
        result["machine_status_reason"] = (
            f"机器已定位全部数值要件（必需 {len(required_keys)} 条、补充 "
            f"{len(matched_keys) - len(required_keys)} 条），但仍有 {len(queue)} 项"
            "需人工裁决（定性要件锚点/数值等价/多来源覆盖/答案侧口径）；"
            "批准前不得计入必需证据，且机器状态不等于人工已核验"
        )
    else:
        result["machine_status"] = "machine_ready"
        result["machine_status_reason"] = (
            f"全部要求要件均为数值且已由人工标注 item 承载（必需 {len(required_keys)} 条）；"
            "仍需**整题**对照冻结 requirement 人工验收后才成为金标"
        )

    result["unmatched_tokens"] = [
        str(facet["token"]) for facet in value_facets if facet.get("coverage") == "missing"
    ]
    result["review_candidates"] = preview_of(pool)[:_PREVIEW_LIMIT]
    by_slot: dict[str, int] = {}
    for target in result["targets"]:  # type: ignore[union-attr]
        gold_id = str(target["basis"]["gold_id"])
        by_slot[gold_id] = by_slot.get(gold_id, 0) + 1
    by_role: dict[str, int] = {}
    for target in result["targets"]:  # type: ignore[union-attr]
        role = str(target["role"])
        by_role[role] = by_role.get(role, 0) + 1
    result["item_coverage"] = {"by_slot": by_slot, "by_role": by_role}
    return result


def human_status_conflicts(slots: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    conflicts: list[dict[str, object]] = []
    for slot in slots:
        basis = str(slot.get("human_basis") or "")
        reviewer = slot.get("reviewer")
        reviewed_at = slot.get("reviewed_at")
        if reviewer and reviewed_at and _human_basis_pending(basis):
            conflicts.append(
                {
                    "gold_id": str(slot.get("gold_id")),
                    "issue": "human_basis 文本仍写『待复核/需确认』，但 reviewer/reviewed_at 已有值",
                    "human_basis": basis,
                    "reviewer": reviewer,
                    "reviewed_at": reviewed_at,
                }
            )
    return conflicts


def _decision_hint(item: Mapping[str, object]) -> str:
    """按裁决项类型给"要填什么"的提示（不同 kind 的可填字段不同）。"""

    kind = str(item.get("kind"))
    if kind == "answer_constraint":
        return (
            "`批准（确认答案侧口径） / 驳回`；依据：____（本项不产生证据目标，无需 chosen；"
            "核验落点在 I3-5 答案侧检查）"
        )
    if kind == "value_equivalence":
        return "`批准（确认数值等价） / 改选 / 驳回`；chosen：____；依据：____"
    if kind == "unmatched_value":
        return "`补标注 / 改选 / 驳回`；chosen 或 supplement：____；依据：____"
    if kind == "source_coverage" and item.get("facet_id") is None:
        return (
            "`批准（指定该来源的承载 item） / 驳回`；chosen：____；"
            "chosen 必须来自本项 source_id，不得用其他来源替代"
        )
    return (
        "`批准 / 改选 / 补标注 / 驳回`；chosen（可多选，按联合覆盖）：____；"
        "仅词面差异填 lexical_review 原文映射；线索改选填 anchor_review；实质缺证补标"
    )


def _render_suggestion(lines: list[str], suggestion: Mapping[str, object], index: int) -> None:
    role = (
        "首选"
        if suggestion.get("role") == "primary"
        else "备选（仅供检索线索；须显式改选及原文承载核验）"
    )
    adequacy = (
        "原文词面覆盖（非语义证明）" if suggestion.get("adequacy") == "full" else "**部分覆盖**"
    )
    lines.append(
        f"    - 机器锚点候选[{index}]（{role}；{adequacy}）："
        f"{suggestion['slot']}#{suggestion['item_index']}"
        f"（{suggestion['kind']}）{' '.join(suggestion['locator'])}"
        f"；{suggestion['why']}"
    )
    if suggestion.get("uncovered_terms"):
        lines.append(f"        - 未覆盖词元：{'、'.join(suggestion['uncovered_terms'])}")
    lines.append(f"        - quote：{suggestion['quote']!r}")


def render_markdown(payload: Mapping[str, object]) -> str:
    summary = payload["summary"]
    inputs = payload["inputs"]
    lines = [
        "# I3-2 补料：证据目标候选核对单（待 U 裁决）",
        "",
        f"- 生成时间：{payload['generated_at']}；规则版本：`{payload['rule_rev']}`",
        f"- 输入：`query-gold-frozen.jsonl` sha256={inputs['query_gold']['sha256'][:12]}…、"
        f"`source-gold-frozen.jsonl` sha256={inputs['source_gold']['sha256'][:12]}…",
        f"- 机器状态：machine_ready **{summary['machine_ready']}** ／ "
        f"pending_human **{summary['pending_human']}** ／ blocked **{summary['blocked']}** ／ "
        f"负例 **{summary['negative_opt_out']}**",
        f"- 目标：必需 **{summary['required_targets']}** ／ 补充（非必需）**{summary['supplementary_targets']}** "
        f"／ 待批准锚点 **{summary['suggested_targets']}**（合计 {summary['targets_total']} 条）",
        f"- 要件裁决队列：**{summary['pending_decisions']}** 项；另有整题验收 "
        f"{summary['answerable_questions']} 题、负例覆盖 {summary['negative_opt_out']} 题、"
        f"来源状态澄清 {summary['status_conflicts']} 项",
        "",
        "> 证据来源全部是 I0A-4 人工标注槽位（reviewer=xyl），quote 为原文逐字子串；",
        "> **机器候选不等于批准**：`role=required` 是机器判定的必需证据，`role=supplementary` 是"
        "补充证据（**非必需**，本版**不声明替代关系**），`role=suggested` 是待批准锚点"
        "（批准前不得计入必需；`adequacy=partial` 的锚点必须补标注或改选）。",
        f"> **EvidencePass 分母 = 逐题**（{payload['contract']['evidence_pass_denominator']}）；"
        "item/槽位计数只作诊断，不得替代分母。",
        "",
        "> 版本记录：v1 子串误命中；v2 连续汉字串当关键词；v3 只证数字覆盖/丢表格身份/日期碎片；"
        "v4 建要求覆盖账与三层角色，但定性要件只在无数字时才登记、锚点未验覆盖度、"
        "批准路径未接通（详见 `supersedes`）；本版 v5 按段并行登记数值与限定、锚点给"
        "未覆盖词元与覆盖度、补充/锚点不再称「可替代」、审批走独立审批件。",
        "",
    ]
    for question in payload["questions"]:
        lines.append(
            f"## {question['query_id']}（{question['domain']}，{question['machine_status']}，"
            f"satisfy_rule={question.get('satisfy_rule')}）"
        )
        lines.append("")
        lines.append(
            f"- evidence_required：`{str(question['evidence_required']).lower()}`；"
            f"候选文件内状态：`{question['adjudication']['status']}`（信息字段，不作批准凭据）"
        )
        if question.get("machine_status_reason"):
            lines.append(f"- 机器判定：{question['machine_status_reason']}")
        if question.get("page_hints"):
            lines.append(f"- 页码提示（不参与匹配）：{'、'.join(question['page_hints'])}")
        if question.get("candidate_slots"):
            lines.append(f"- 候选槽位：{'、'.join(question['candidate_slots'])}")
        by_facet = {str(facet["facet_id"]): facet for facet in question["requirement_facets"]}
        if question["requirement_clauses"]:
            lines.append("- 要求覆盖账（按段）：")
            for entry in question["requirement_clauses"]:
                lines.append(f"    - `{entry['clause_id']}` {entry['text']!r}")
                for facet_id in entry["value_facet_ids"]:
                    facet = by_facet[facet_id]
                    lines.append(
                        f"        - 数值要件 `{facet_id}` {facet['token']!r} → {facet['coverage']}"
                    )
                for facet_id in entry["qualification_facet_ids"]:
                    facet = by_facet[facet_id]
                    lines.append(
                        f"        - 定性要件 `{facet_id}` → {facet['coverage']}"
                        f"（锚点 {len(facet['suggestions'])} 条）"
                    )
        for role, title in (
            ("required", "必需证据（计入 EvidencePass）"),
            ("supplementary", "补充证据（非必需；不声明替代关系）"),
            ("suggested", "待批准锚点（批准前不得计入必需）"),
        ):
            group = [target for target in question["targets"] if target["role"] == role]
            if not group:
                continue
            lines.append(f"- {title}：")
            for target in group:
                constraints = {
                    key: value
                    for key, value in target["constraints"].items()
                    if value not in (None, "")
                }
                lines.append(
                    f"    - `{target['target_id']}` {target['source_id']} "
                    f"{' '.join(target['locator'])} ← {target['basis']['gold_id']}"
                    f"#{target['basis']['item_index']}"
                    f"（{target['basis']['kind']}；约束 {constraints}）"
                )
                lines.append(f"        - quote：{target['quote']!r}")
                if target["basis"].get("value_equivalents"):
                    lines.append(f"        - 数值等价：{target['basis']['value_equivalents']}")
                if target["basis"].get("adequacy") == "partial":
                    lines.append(
                        f"        - **部分覆盖，未覆盖词元："
                        f"{'、'.join(target['basis'].get('uncovered_terms') or [])}**"
                    )
        if question.get("answer_constraints"):
            lines.append("- 答案侧约束（不产生证据目标，核验落点 I3-5）：")
            for constraint in question["answer_constraints"]:
                lines.append(f"    - `{constraint['facet_id']}` {constraint['text']!r}")
        if question["pending_human"]:
            lines.append(f"- 要件裁决队列（{len(question['pending_human'])} 项）：")
            for item in question["pending_human"]:
                lines.append(f"    - `{item['item_id']}`（{item['kind']}）{item['question']}")
        if question.get("unmatched_tokens"):
            lines.append(
                f"- **无承载 item 的数值（不得猜）**：{'、'.join(question['unmatched_tokens'])}"
            )
        if question.get("weak_tokens"):
            lines.append(
                f"- 弱 token（年份/单字符，不参与匹配）：{'、'.join(question['weak_tokens'])}"
            )
        if question.get("period_tokens"):
            lines.append(
                f"- 期间 token（已掩码，另作期间要件）：{'、'.join(question['period_tokens'])}"
            )
        if question.get("item_without_quote"):
            lines.append(
                f"- 无 quote 的 item（缺资产，未生成 target）：{'、'.join(question['item_without_quote'])}"
            )
        by_slot = question["item_coverage"]["by_slot"]
        if by_slot:
            lines.append(
                "- item 覆盖统计（**诊断用，不是 EvidencePass 分母**）："
                + "、".join(f"{slot}×{count}" for slot, count in sorted(by_slot.items()))
            )
        lines.append("")
    return "\n".join(lines)


def render_adjudication(payload: Mapping[str, object]) -> str:
    summary = payload["summary"]
    questions = payload["questions"]
    answerable = [q for q in questions if q["machine_status"] != "negative_opt_out"]
    negatives = [q for q in questions if q["machine_status"] == "negative_opt_out"]
    conflicts = payload.get("human_status_conflicts") or []
    lines = [
        "# I3-2 证据目标：人工裁决单（待 U 填）",
        "",
        "> 本文件是**批准件模板**，与机器候选 "
        "[evidence-targets-candidates.json](evidence-targets-candidates.json) 分开存储；",
        "> 批准结果写进 `evidence-targets-decisions.json`，由 `i3s2_apply_decisions.py` 生成"
        "**批准投影** `evidence-targets-approved.json` 并给出完整性门结论。",
        "",
        "## 0. 本次裁决的口径（先确认，再逐项裁决）",
        "",
        f"- **EvidencePass 分母 = 逐题**：{payload['contract']['evidence_pass_denominator']}；",
        "  item 条数与槽位聚合只作诊断展示，**不得**用来替代分母。",
        f"- 机器候选规则 `{payload['rule_rev']}`：`role=required` 必需 ／ `role=supplementary` "
        "补充（**非必需**，本版不声明替代关系）／ `role=suggested` 待批准锚点（批准前不计入必需）。",
        f"- **本次要填的不是只有要件裁决**，共四类：① 要件裁决 **{summary['pending_decisions']}** 项"
        "（定性锚点/数值等价/多来源覆盖/答案侧口径）；"
        f"② 有答案题**整题验收** **{len(answerable)}** 题（对照冻结 `evidence_requirement` 逐项确认，"
        "含 `machine_ready` 题——它们没有待裁决要件，但**不等于**无需人工审核）；"
        f"③ 负例覆盖确认 **{len(negatives)}** 题；④ 来源槽位人工状态澄清 **{len(conflicts)}** 项。",
        "- **改候选文件里的 `adjudication.status` 不能开门**：完整性门只认审批件"
        "（`facet_decisions` / `question_reviews` / `negative_reviews` / `human_status_clarifications` "
        "+ 输入哈希）。审批件必须绑定它所针对的候选/金标哈希，哈希不符即视为过期。",
        "- `adequacy=partial` 的机器锚点（「部分覆盖」）不得直接批准：必须改选覆盖更全的 item、"
        "补人工标注。`residual_accepted=true` 禁用；仅词面差异可提交 lexical_review，"
        "逐项绑定未覆盖词元、原文片段和理由，不得豁免缺失事实。",
        "- `search_hint`/非首选锚点不得直接批准：须 decision=改选 与 anchor_review 原文承载映射。"
        "text/period 等标注元数据只供搜寻，不替代 quote；同义映射仍是人工判断，不是机器语义认证。",
        "- 来源专属项须选择同一 source_id；答案侧约束禁止 chosen，不生成证据目标。"
        "全部审批数组禁止重复/未知身份，负例必须写覆盖依据。",
        "- 「驳回」只表示**驳回这个候选锚点**，不删除原题要求：要件仍在覆盖账里，"
        "必须给出改选或补标注，否则完整性门保持不放行。",
        "- 裁决前不得把候选当正式金标，也不得先跑候选业务结果再补答案。",
        "",
        "## 1. 逐题状态总表",
        "",
        "| 题号 | 类别 | 机器状态 | 必需 | 补充 | 待批准锚点 | 要件裁决 | 整题验收 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for question in questions:
        roles = question["item_coverage"]["by_role"]
        whole = "需验收" if question["machine_status"] != "negative_opt_out" else "负例"
        lines.append(
            f"| {question['query_id']} | {question['domain']} | {question['machine_status']} | "
            f"{roles.get('required', 0)} | {roles.get('supplementary', 0)} | "
            f"{roles.get('suggested', 0)} | {len(question['pending_human'])} | {whole} |"
        )
    lines += ["", "## 2. 要件裁决（逐项）", ""]
    for question in questions:
        if not question["pending_human"]:
            continue
        lines.append(f"### {question['query_id']}（{question['machine_status']}）")
        lines.append("")
        for item in question["pending_human"]:
            lines.append(f"- **`{item['item_id']}`**（{item['kind']}）{item['question']}")
            for index, suggestion in enumerate(item.get("suggestions") or (), start=1):
                _render_suggestion(lines, suggestion, index)
            lines.append(f"    - 决定口径：{_decision_hint(item)}")
        lines.append("")
    lines += [
        "## 3. 有答案题整题验收（对照冻结 requirement）",
        "",
        "要件裁决完成**不等于**整题验收完成：还须逐题确认覆盖账没有漏掉冻结 `evidence_requirement` 里的"
        "对象、期间、单位、条件、否定与归属要求。发现漏项时，必须新增要件（补标注）或写明裁定依据，"
        "不得只勾「批准」。",
        "",
    ]
    for question in answerable:
        clauses = "；".join(entry["text"] for entry in question["requirement_clauses"])
        lines.append(f"- `{question['query_id']}`：冻结 requirement 分段 = {clauses!r}")
        lines.append("    - 决定：`批准 / 需补要件`；依据（含未覆盖项说明）：____")
    lines += [
        "",
        "## 4. 负例覆盖确认",
        "",
        "负例不进入 EvidencePass 正例分母（既有合同），但仍须参加误报/伪造引用检查，",
        "并须人工确认『材料全文确实没有该证据』，不得以未检索到来代替没有证据。",
        "",
    ]
    for question in negatives:
        flag = question.get("negative_check", {}).get("human_basis_pending_coverage")
        lines.append(
            f"- `{question['query_id']}`：human_basis 是否仍写『待/需确认全文覆盖』=**{flag}**；"
            "决定：`批准 / 待补`；full_text_coverage_confirmed：____；依据：____"
        )
    lines += ["", "## 5. 来源槽位人工状态澄清", ""]
    if not conflicts:
        lines.append("- 无。")
    for conflict in conflicts:
        lines.append(f"- `{conflict['gold_id']}`：{conflict['issue']}")
        lines.append(f"    - human_basis：{conflict['human_basis']!r}")
        lines.append(
            f"    - reviewer={conflict['reviewer']}；reviewed_at={conflict['reviewed_at']}"
        )
        lines.append("    - resolution（`残留描述` / `实质未决`）与依据：____")
    template = {
        "artifact": "i3-2-evidence-targets-decisions",
        "rule_rev": payload["rule_rev"],
        "reviewer": "<U>",
        "reviewed_at": "<ISO8601>",
        "based_on": {
            "candidates_sha256": "<候选文件 sha256>",
            "query_gold_sha256": payload["inputs"]["query_gold"]["sha256"],
            "source_gold_sha256": payload["inputs"]["source_gold"]["sha256"],
        },
        "question_reviews": [
            {
                "query_id": "<题号>",
                "decision": "批准|需补要件",
                "reviewed_against_requirement": True,
                "reason": "...",
            }
        ],
        "facet_decisions": [
            {
                "item_id": "I32-<题号>-01",
                "facet_id": "<facet>",
                "query_id": "<题号>",
                "decision": "批准|改选|补标注|驳回",
                "chosen": [{"slot": "...", "item_index": 0}],
                "lexical_review": {
                    "kind": "lexical_mismatch",
                    "facet_id": "<与本项相同，来源专属项为null>",
                    "requirement": "<对应facet原文>",
                    "evidence_complete": True,
                    "missing_evidence": False,
                    "mappings": [
                        {
                            "terms": ["<机器列出的未覆盖词元，合计须精确覆盖>"],
                            "slot": "...",
                            "item_index": 0,
                            "quote_span": "<chosen原文逐字子串，不得取自text/period>",
                            "reason": "<同义依据>",
                        }
                    ],
                },
                "supplement": {"slot": "...", "item_index": 3, "source_gold_revision": "..."},
                "reviewed_against_clause": "<段原文>",
                "reason": "...",
            }
        ],
        "negative_reviews": [
            {
                "query_id": "<负例题号>",
                "decision": "批准|待补",
                "full_text_coverage_confirmed": True,
                "reason": "...",
            }
        ],
        "human_status_clarifications": [
            {"gold_id": "<槽位>", "resolution": "残留描述|实质未决", "reason": "..."}
        ],
    }
    lines += [
        "",
        "## 6. 决策回填模板",
        "",
        "```json",
        json.dumps(template, ensure_ascii=False, indent=2),
        "```",
        "",
        "lexical_review 只在词面不一致但原文实质完整时填写；每个 chosen 均须被映射引用，"
        "mappings.terms 的并集须等于机器列出的缺词。实质缺证不得填写 evidence_complete=true。",
        "anchor_review 仅用于改选：结构同 lexical_review，但 kind=anchor_reselection，"
        "每条 mappings.terms=[]；它核验改选依据，不替代所需的 lexical_review。无例外时省略两字段。",
        "answer_constraint 只填批准/驳回及理由，必须省略 chosen、lexical_review、anchor_review。"
        "来源专属项 facet_id=null、requirement为空串。不得把模板占位符当成真实审批。",
        "I3-5 本轮零模型只验证答案约束登记与投影保真；真实生成答案的语义验收未执行，"
        "若需要须另行制定输入/人工评分规则与有限预算，不得据检索分数宣称答案合规。",
        "回填后运行 `i3s2_apply_decisions.py`：它校验输入哈希、逐项裁决覆盖、整题验收、",
        "负例覆盖、状态澄清、引用真源与投影一致性（不接受缺证豁免），",
        "生成 `evidence-targets-approved.json`（批准投影）与 `approval-report.json`（完整性门结论）。",
        "`ready=true` 时必须**另建冻结修订**并同步台账，不得复用旧快照。",
        "",
    ]
    return "\n".join(lines)


def archive_current() -> list[str]:
    """write-once：把已有当前产物按版本号归档（不覆盖历史）。"""

    archived: list[str] = []
    for current, pattern in (
        (OUT_JSON, "evidence-targets-candidates-v{}.json"),
        (OUT_MD, "evidence-targets-review-v{}.md"),
        (OUT_ADJ, "evidence-targets-adjudication-v{}.md"),
    ):
        if not current.is_file():
            continue
        index = 1
        while (OUT_DIR / pattern.format(index)).exists():
            index += 1
        target = OUT_DIR / pattern.format(index)
        current.rename(target)
        archived.append(target.name)
    return archived


def main() -> int:
    for path in (QUERY_GOLD, SOURCE_GOLD):
        if not path.is_file():
            fail(f"缺少输入冻结件：{path}")

    questions = load_jsonl(QUERY_GOLD)
    slots = load_jsonl(SOURCE_GOLD)
    mapped = [map_question(question, slots) for question in questions]

    roles = [target["role"] for item in mapped for target in item["targets"]]
    answerable = [item for item in mapped if item["machine_status"] != "negative_opt_out"]
    conflicts = human_status_conflicts(slots)
    summary = {
        "questions_total": len(mapped),
        "answerable_questions": len(answerable),
        "targets_total": len(roles),
        "required_targets": roles.count("required"),
        "supplementary_targets": roles.count("supplementary"),
        "suggested_targets": roles.count("suggested"),
        "machine_ready": sum(1 for item in mapped if item["machine_status"] == "machine_ready"),
        "pending_human": sum(1 for item in mapped if item["machine_status"] == "pending_human"),
        "blocked": sum(1 for item in mapped if item["machine_status"] == "blocked"),
        "negative_opt_out": sum(
            1 for item in mapped if item["machine_status"] == "negative_opt_out"
        ),
        "pending_decisions": sum(len(item["pending_human"]) for item in mapped),
        "partial_anchors": sum(
            1
            for item in mapped
            for target in item["targets"]
            if target["basis"].get("adequacy") == "partial"
        ),
        "status_conflicts": len(conflicts),
    }
    payload = {
        "artifact": "i3-2-evidence-targets-candidates",
        "rule_rev": RULE_REV,
        "generated_at": datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
        "contract": {
            "evidence_pass_denominator": (
                "逐题：满足全部必需证据的题数 / 证据题数（架构 §12.3）；"
                "item 条数或槽位聚合只决定每题内部是否全部满足，不能替代分母"
            ),
            "item_coverage_is_diagnostic_only": True,
            "evidence_target_roles": {
                "required": "机器判定的必需证据，计入 EvidencePass",
                "supplementary": "补充证据，非必需；本版不声明任何替代/等价关系",
                "suggested": "定性要件的待批准锚点，人工批准前不得计入必需；"
                "adequacy=partial 的锚点须改选/补标；词面差异须逐项原文映射，不接受 residual 豁免",
            },
            "structural_identity": (
                "表格 item 的 row/col/cell/unit/period 保留在 constraints，"
                "row:/col: 写入 locator；I3-1 必须由权威侧（页/行/列，如 read_pg.fetch_cell）"
                "产出这些 token，不得由适配器从金标回填"
            ),
            "approval_path": (
                "候选文件里的 adjudication.status 只是信息字段；批准必须经 "
                "evidence-targets-decisions.json → i3s2_apply_decisions.py（批准投影 + 完整性门）。"
                "审批件必须绑定候选/金标哈希，哈希不符即过期"
            ),
            "answer_constraints": (
                "答案侧口径（不得混淆/标明预测等）不产生证据目标；其核验落点为 "
                f"{_ANSWER_VERIFY_POINT}，检索证据评分不得冒充已核验答案语义"
            ),
            "verification_scope": (
                "本规则只覆盖**证据取回**的可判定性；整题语义完整性由人工整题验收负责"
            ),
        },
        "supersedes": [
            {
                "artifact": "i3-2-evidence-targets-candidates-v5",
                "rule_rev": "evidence-mapping-5",
                "defect": "审批缺来源/身份/投影核验；residual可豁免缺证；元数据误计原文覆盖。",
            },
            {
                "artifact": "i3-2-evidence-targets-candidates-v1",
                "rule_rev": "evidence-mapping-1",
                "defect": "子串匹配致短 token 误命中（『第20页』的 20 命中 2026），目标爆量。",
            },
            {
                "artifact": "i3-2-evidence-targets-candidates-v2",
                "rule_rev": "evidence-mapping-2",
                "defect": "CJK 关键词用连续汉字串抽取，把整句当词。",
            },
            {
                "artifact": "i3-2-evidence-targets-candidates-v3",
                "rule_rev": "evidence-mapping-3",
                "defect": (
                    "只证数字覆盖不证要求完整；表格行列身份丢失；日期碎片与型号后缀造成"
                    "无关强制目标；同值重复出现被去重；分母口径与架构 §12.3 冲突。"
                ),
            },
            {
                "artifact": "i3-2-evidence-targets-candidates-v4",
                "rule_rev": "evidence-mapping-4",
                "defect": (
                    "定性要件只在『整段无强数值』时才登记，含数字子句里的限定（如 macro-003 的"
                    "『区分附条件判断/市场预期/正式决定』、company-001 的年度对应/评级/预测标注）"
                    "漏账；机器锚点只按词面重叠推荐，未标「部分覆盖」，易被当成完整证据批准；"
                    "把补充证据称「可替代」，且批准流程未接通（改状态即可开门）。"
                ),
            },
        ],
        "generator": {
            "path": ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i3s2_evidence_targets.py",
            "sha256": digest(Path(__file__)),
        },
        "textutil": {
            "path": ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i3s2_textutil.py",
            "sha256": digest(BASE / "i3s2_textutil.py"),
        },
        "inputs": {
            "query_gold": {
                "path": ".scratch/corpus-evidence-pipeline/ingestion-rebuild/query-gold-frozen.jsonl",
                "sha256": digest(QUERY_GOLD),
            },
            "source_gold": {
                "path": ".scratch/corpus-evidence-pipeline/ingestion-rebuild/source-gold-frozen.jsonl",
                "sha256": digest(SOURCE_GOLD),
            },
        },
        "summary": summary,
        "human_status_conflicts": conflicts,
        "questions": mapped,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    archived = archive_current()
    if archived:
        print(f"archived previous revision: {', '.join(archived)}")
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUT_MD.write_text(render_markdown(payload), encoding="utf-8")
    OUT_ADJ.write_text(render_adjudication(payload), encoding="utf-8")
    print(f"candidates written: {OUT_JSON} sha256={digest(OUT_JSON)}")
    print(f"review sheet: {OUT_MD} sha256={digest(OUT_MD)}")
    print(f"adjudication sheet: {OUT_ADJ} sha256={digest(OUT_ADJ)}")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
