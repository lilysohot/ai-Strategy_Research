"""I3-2 裁决应用器：**独立审批件 → 批准投影 → 完整性门**（复核 A1/A2 的修复）。

背景：v4 的完整性门看候选文件里的 ``adjudication.status``，于是"把 30 题状态改成 approved"
就能得到 ``ready=true``（即使 36 项要件全部未决、审阅人为空）。本版把批准拆成三个可核查的步骤：

1. **审批件**：``i3-2/evidence-targets-decisions.json``（人工填写，绑定它所针对的
   候选/query gold/source gold 哈希）；
2. **批准投影**：本脚本按审批件把"机器必需 + 人工选取的锚点"投影成
   ``i3-2/evidence-targets-approved.json``——**不改任何冻结候选字节**；
3. **完整性门**：本脚本同时输出 ``i3-2/approval-report.json``，逐项核对
   ① 要件裁决全覆盖 ② 有答案题整题验收 ③ 负例全文覆盖确认 ④ 来源槽位人工状态澄清
   ⑤ 原文锚点覆盖与同义映射（不得豁免缺证）⑥ 输入哈希未过期 ⑦ 投影引用真源一致。

纪律：

- 候选文件里的 ``adjudication.status`` **不参与**判定，改它不会开门；
- `驳回` 只驳回**候选锚点**，不删除原题要求：仍算未决，门保持不放行；
- `补标注` 指出具新引文，须先形成新的 source-gold 版本（本脚本只认与冻结版本一致的引用），
  在此之前保持未决——不得用题目要求生成伪原文；
- 本脚本零模型、零网络、零 PG、只读冻结件。

用法::

    env -u PYTHONPATH uv run python \
        .scratch/corpus-evidence-pipeline/ingestion-rebuild/i3s2_apply_decisions.py
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[2]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from i3s2_textutil import content_units, unit_stats  # noqa: E402

QUERY_GOLD = BASE / "query-gold-frozen.jsonl"
SOURCE_GOLD = BASE / "source-gold-frozen.jsonl"
CANDIDATES = BASE / "i3-2" / "evidence-targets-candidates.json"
DECISIONS = BASE / "i3-2" / "evidence-targets-decisions.json"
APPROVED = BASE / "i3-2" / "evidence-targets-approved.json"
REPORT = BASE / "i3-2" / "approval-report.json"

_FACET_DECISIONS = ("批准", "改选", "补标注", "驳回")
_RESOLUTIONS = ("残留描述", "实质未决")
_MAX_LISTED = 40


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def split_items(slot: Mapping[str, object]) -> list[tuple[int, Mapping[str, object]]]:
    items = slot.get("expected_items") or ()
    if not isinstance(items, Sequence):
        return []
    return [(index, item) for index, item in enumerate(items) if isinstance(item, Mapping)]


def _nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _chosen_keys(entry: Mapping[str, object]) -> list[tuple[str, int]]:
    chosen = entry.get("chosen") or ()
    keys: list[tuple[str, int]] = []
    if not isinstance(chosen, Sequence) or isinstance(chosen, (str, bytes)):
        return keys
    for item in chosen:
        if not isinstance(item, Mapping):
            continue
        slot = item.get("slot")
        index = item.get("item_index")
        if _nonempty(slot) and type(index) is int and index >= 0:
            keys.append((str(slot), index))
    return keys


def _facet_text(question: Mapping[str, object], facet_id: str | None) -> str:
    for facet in question.get("requirement_facets") or ():
        if facet.get("facet_id") == facet_id:
            return str(facet.get("text") or facet.get("token") or "")
    for clause in question.get("requirement_clauses") or ():
        if facet_id and (
            facet_id in (clause.get("value_facet_ids") or [])
            or facet_id in (clause.get("qualification_facet_ids") or [])
        ):
            return str(clause.get("text") or "")
    return ""


def _covered_terms(
    facet_text: str,
    keys: Sequence[tuple[str, int]],
    pool: Mapping[str, Mapping[str, object]],
    frequency: Mapping[str, int],
    total_items: int,
) -> list[str]:
    """chosen 集合整体仍未覆盖的判别性词元（复核 A3：批准前必须证明覆盖）。"""

    if not facet_text:
        return []
    missing = content_units(facet_text)
    for slot_id, index in keys:
        slot = pool.get(slot_id)
        if slot is None:
            continue
        text = ""
        for candidate_index, item in split_items(slot):
            if candidate_index == index:
                text = str(item.get("quote") or "")
                break
        missing = missing - content_units(text)
    # Search ranking may use metadata/frequency; approval coverage may not.
    return sorted(missing)


def _review_index(decisions, name, key, allowed, blockers):
    entries = decisions.get(name, [])
    indexed = {}
    if not isinstance(entries, list):
        blockers.append(f"{name} 必须是数组")
        return indexed
    for entry in entries:
        if not isinstance(entry, Mapping):
            blockers.append(f"{name} 元素必须是对象")
            continue
        identity = entry.get(key)
        if not isinstance(identity, str) or identity not in allowed:
            blockers.append(f"{name} 未知 {key}: {identity!r}")
        elif identity in indexed:
            blockers.append(f"{name} 重复 {key}: {identity}")
        else:
            indexed[identity] = entry
    return indexed


def _anchor_review(review, facet_id, facet_text, keys, pool, missing, kind):
    """Validate auditable human lexical/reselection mapping, never a fact waiver.

    This validates provenance and completeness of the review record, NOT whether
    a paraphrase is semantically true. That remains the named human's judgment.
    """
    if not isinstance(review, Mapping):
        return False
    if (
        review.get("kind") != kind
        or review.get("facet_id") != facet_id
        or review.get("requirement") != facet_text
        or review.get("evidence_complete") is not True
        or review.get("missing_evidence") is not False
    ):
        return False
    mappings = review.get("mappings")
    if not isinstance(mappings, list) or not mappings:
        return False
    covered = set()
    refs = set()
    for mapping in mappings:
        if not isinstance(mapping, Mapping):
            return False
        slot, index = mapping.get("slot"), mapping.get("item_index")
        if not isinstance(slot, str) or type(index) is not int or (slot, index) not in keys:
            return False
        item = dict(split_items(pool[slot])).get(index, {})
        span = mapping.get("quote_span")
        terms = mapping.get("terms")
        if (
            not _nonempty(span)
            or span not in str(item.get("quote") or "")
            or not content_units(span)
            or not _nonempty(mapping.get("reason"))
            or not isinstance(terms, list)
            or any(not isinstance(t, str) for t in terms)
        ):
            return False
        covered.update(terms)
        refs.add((slot, index))
    return covered == set(missing) and refs == set(keys)


def evaluate(
    payload: Mapping[str, object],
    gold: Sequence[Mapping[str, object]],
    slots: Sequence[Mapping[str, object]],
    decisions: Mapping[str, object] | None,
) -> dict[str, object]:
    """完整性门：只认审批件，不看候选文件里的 ``adjudication.status``。"""

    candidates = {str(item["query_id"]): item for item in payload.get("questions", [])}
    gold_by_id = {str(item["query_id"]): item for item in gold}
    slot_by_id = {str(slot.get("gold_id")): slot for slot in slots}
    blockers: list[str] = []
    warnings: list[str] = []

    expected_items = {
        str(entry["item_id"]): (query_id, entry)
        for query_id, question in candidates.items()
        for entry in question.get("pending_human") or []
    }
    answerable = [qid for qid, q in candidates.items() if q["machine_status"] != "negative_opt_out"]
    negatives = [qid for qid, q in candidates.items() if q["machine_status"] == "negative_opt_out"]
    conflicts = [str(item["gold_id"]) for item in payload.get("human_status_conflicts") or []]

    if decisions is None:
        return {
            "ready": False,
            "stage": "no_decisions",
            "blockers": [
                f"缺少审批件 {DECISIONS.name}：批准必须走"
                "『审批件 → 批准投影 → 完整性门』，候选内的 adjudication.status 不作凭据"
            ],
            "required": {
                "facet_decisions": len(expected_items),
                "question_reviews": len(answerable),
                "negative_reviews": len(negatives),
                "human_status_clarifications": len(conflicts),
            },
            "unresolved_items": sorted(expected_items),
            "warnings": [],
        }

    # ── 0. 审批件形状与过期检查 ────────────────────────────────────────────
    if not _nonempty(decisions.get("reviewer")):
        blockers.append("审批件缺少非空 reviewer")
    if not _nonempty(decisions.get("reviewed_at")):
        blockers.append("审批件缺少非空 reviewed_at")
    if decisions.get("artifact") != "i3-2-evidence-targets-decisions":
        blockers.append(f"审批件 artifact 非法：{decisions.get('artifact')!r}")
    if decisions.get("rule_rev") != payload.get("rule_rev"):
        blockers.append(
            f"审批件 rule_rev（{decisions.get('rule_rev')!r}）与候选（{payload.get('rule_rev')!r}）不符"
        )
    based_on = decisions.get("based_on") or {}
    expected_hashes = {
        "candidates_sha256": digest(CANDIDATES),
        "query_gold_sha256": digest(QUERY_GOLD),
        "source_gold_sha256": digest(SOURCE_GOLD),
    }
    for key, actual in expected_hashes.items():
        declared = based_on.get(key) if isinstance(based_on, Mapping) else None
        if declared != actual:
            blockers.append(
                f"审批件 based_on.{key} 与当前冻结件不符（{declared!r} != {actual!r}）：审批已过期"
            )

    # ── 1. 要件裁决：全覆盖 + 覆盖度 ───────────────────────────────────────
    facet_entries = decisions.get("facet_decisions") or []
    if not isinstance(facet_entries, Sequence) or isinstance(facet_entries, (str, bytes)):
        blockers.append("审批件 facet_decisions 必须是数组")
        facet_entries = []
    decided: dict[str, Mapping[str, object]] = {}
    for entry in facet_entries:
        if not isinstance(entry, Mapping):
            blockers.append("facet_decisions 元素必须是对象")
            continue
        item_id = str(entry.get("item_id") or "")
        if item_id not in expected_items:
            blockers.append(f"facet_decisions 出现未知 item_id：{item_id!r}")
            continue
        if item_id in decided:
            blockers.append(f"facet_decisions 重复 item_id：{item_id}")
            continue
        decided[item_id] = entry
    unresolved: list[str] = []
    for item_id, (query_id, entry) in expected_items.items():
        decision_entry = decided.get(item_id)
        if decision_entry is None:
            unresolved.append(item_id)
            continue
        if (
            decision_entry.get("query_id") != query_id
            or "facet_id" not in decision_entry
            or decision_entry.get("facet_id") != entry.get("facet_id")
        ):
            blockers.append(f"{item_id}: query_id/facet_id 与候选身份不符")
        if decision_entry.get("residual_accepted") not in (None, False):
            blockers.append(
                f"{item_id}: residual 豁免已禁用；实质缺证须补标，词面差异用 lexical_review"
            )
        decision = str(decision_entry.get("decision") or "")
        if decision not in _FACET_DECISIONS:
            blockers.append(f"{item_id}: decision 非法 {decision!r}")
            continue
        if not _nonempty(decision_entry.get("reason")):
            blockers.append(f"{item_id}: 缺少非空 reason")
        if decision == "驳回":
            unresolved.append(item_id)
            warnings.append(f"{item_id}: 驳回候选锚点；原题要求仍保留，须改选或补标注后才可能放行")
            continue
        question = candidates[query_id]
        pool_ids = {str(value) for value in question.get("candidate_slots") or []}
        if str(entry.get("kind")) == "answer_constraint":
            if (
                decision != "批准"
                or decision_entry.get("chosen") not in (None, [])
                or decision_entry.get("lexical_review") is not None
                or decision_entry.get("anchor_review") is not None
            ):
                blockers.append(f"{item_id}: 答案侧约束只可批准/驳回且禁止 chosen，不产生证据目标")
            continue
        if decision == "补标注":
            supplement = decision_entry.get("supplement")
            if not isinstance(supplement, Mapping):
                blockers.append(f"{item_id}: 补标注缺少 supplement")
                unresolved.append(item_id)
                continue
            slot_id = str(supplement.get("slot") or "")
            index = supplement.get("item_index")
            revision = supplement.get("source_gold_revision")
            if slot_id not in pool_ids:
                blockers.append(f"{item_id}: supplement.slot 不在该题候选来源范围内（{slot_id!r}）")
                unresolved.append(item_id)
                continue
            if isinstance(index, int) and any(
                i == index for i, _ in split_items(slot_by_id.get(slot_id, {}))
            ):
                blockers.append(
                    f"{item_id}: supplement 指向的 item 已在冻结标注中存在，"
                    "请改用『批准/改选』；『补标注』只用于新增引文"
                )
                unresolved.append(item_id)
                continue
            blockers.append(
                f"{item_id}: 补标注需先形成新的 source-gold 版本（当前声明 {revision!r}）；"
                "新引文未经来源核验前不得开门"
            )
            unresolved.append(item_id)
            continue
        keys = _chosen_keys(decision_entry)
        raw_chosen = decision_entry.get("chosen")
        if (
            not keys
            or not isinstance(raw_chosen, list)
            or len(keys) != len(raw_chosen)
            or len(set(keys)) != len(keys)
        ):
            blockers.append(f"{item_id}: {decision} 必须给出非空 chosen（slot#item_index）")
            unresolved.append(item_id)
            continue
        bad = [f"{slot}#{index}" for slot, index in keys if slot not in pool_ids]
        if bad:
            blockers.append(f"{item_id}: chosen 超出该题候选来源范围 {bad}")
            unresolved.append(item_id)
            continue
        missing_index = [
            f"{slot}#{index}"
            for slot, index in keys
            if not any(i == index for i, _ in split_items(slot_by_id.get(slot, {})))
        ]
        if missing_index:
            blockers.append(f"{item_id}: chosen 指向不存在的 item {missing_index}")
            unresolved.append(item_id)
            continue
        if entry.get("source_id") and any(
            slot_by_id[slot].get("source_id") != entry["source_id"] for slot, _ in keys
        ):
            blockers.append(f"{item_id}: chosen 必须来自指定来源 {entry['source_id']}")
            unresolved.append(item_id)
            continue
        facet_text = _facet_text(question, entry.get("facet_id"))
        pool = {slot_id: slot_by_id[slot_id] for slot_id in pool_ids if slot_id in slot_by_id}
        weights_unused, frequency, total_items = unit_stats(list(pool.values()), split_items)
        del weights_unused
        still_missing = _covered_terms(facet_text, keys, pool, frequency, total_items)
        primary = {
            (v.get("slot"), v.get("item_index"))
            for v in entry.get("suggestions") or []
            if v.get("role") == "primary"
        }
        hinted = {
            (v.get("slot"), v.get("item_index"))
            for v in entry.get("suggestions") or []
            if v.get("role") == "search_hint"
        }
        reselected = bool(set(keys) & hinted or (primary and not set(keys) <= primary))
        if reselected and (
            decision != "改选"
            or not _anchor_review(
                decision_entry.get("anchor_review"),
                entry.get("facet_id"),
                facet_text,
                keys,
                pool,
                [],
                "anchor_reselection",
            )
        ):
            blockers.append(
                f"{item_id}: 检索线索/新锚点须显式改选并提交 anchor_review 原文承载映射"
            )
        if (
            still_missing or decision_entry.get("lexical_review") is not None
        ) and not _anchor_review(
            decision_entry.get("lexical_review"),
            entry.get("facet_id"),
            facet_text,
            keys,
            pool,
            still_missing,
            "lexical_mismatch",
        ):
            blockers.append(
                f"{item_id}: chosen 仍未覆盖判别性词元 {still_missing}；"
                "实质缺证须改选/补标注；仅词面差异可提交逐项原文 lexical_review，不得豁免事实"
            )
            unresolved.append(item_id)
            continue
        if still_missing:
            warnings.append(
                f"{item_id}: 人工同义映射待审计（非机器语义证明）：{'、'.join(still_missing)}"
            )
    if unresolved:
        blockers.append(f"要件裁决未完成 {len(unresolved)} 项：{unresolved[:_MAX_LISTED]}")

    # ── 2. 有答案题整题验收（machine_ready 题同样必须） ─────────────────────
    reviewed = _review_index(decisions, "question_reviews", "query_id", answerable, blockers)
    unreviewed: list[str] = []
    for query_id in answerable:
        entry = reviewed.get(query_id)
        if entry is None:
            unreviewed.append(query_id)
            continue
        if str(entry.get("decision") or "") != "批准":
            unreviewed.append(query_id)
            continue
        if entry.get("reviewed_against_requirement") is not True:
            blockers.append(
                f"{query_id}: 整题验收须 reviewed_against_requirement=true（对照冻结 requirement 逐项确认）"
            )
            unreviewed.append(query_id)
            continue
        if not _nonempty(entry.get("reason")):
            blockers.append(f"{query_id}: 整题验收缺少非空 reason")
            unreviewed.append(query_id)
    if unreviewed:
        blockers.append(f"有答案题整题验收未完成 {len(unreviewed)} 题：{unreviewed[:_MAX_LISTED]}")
    unknown_reviews = sorted(set(reviewed) - set(answerable) - set(negatives))
    if unknown_reviews:
        blockers.append(f"question_reviews 出现未知题号：{unknown_reviews[:_MAX_LISTED]}")

    # ── 3. 负例覆盖确认 ────────────────────────────────────────────────────
    neg_done = _review_index(decisions, "negative_reviews", "query_id", negatives, blockers)
    neg_missing: list[str] = []
    for query_id in negatives:
        entry = neg_done.get(query_id)
        if entry is None or str(entry.get("decision") or "") != "批准":
            neg_missing.append(query_id)
            continue
        if entry.get("full_text_coverage_confirmed") is not True:
            blockers.append(
                f"{query_id}: 负例须 full_text_coverage_confirmed=true（人工确认全文无该证据）"
            )
            neg_missing.append(query_id)
        if not _nonempty(entry.get("reason")):
            blockers.append(f"{query_id}: 负例覆盖确认缺少非空 reason")
    if neg_missing:
        blockers.append(f"负例覆盖确认未完成 {len(neg_missing)} 题：{neg_missing}")

    # ── 4. 来源槽位人工状态澄清 ────────────────────────────────────────────
    resolved = _review_index(
        decisions, "human_status_clarifications", "gold_id", conflicts, blockers
    )
    unresolved_conflicts: list[str] = []
    for gold_id in conflicts:
        entry = resolved.get(gold_id)
        if entry is None:
            unresolved_conflicts.append(gold_id)
            continue
        resolution = str(entry.get("resolution") or "")
        if resolution not in _RESOLUTIONS or not _nonempty(entry.get("reason")):
            blockers.append(f"{gold_id}: 澄清须给 resolution（{'/'.join(_RESOLUTIONS)}）与理由")
            unresolved_conflicts.append(gold_id)
            continue
        if resolution == "实质未决":
            blockers.append(f"{gold_id}: 人工状态仍实质未决，不得放行")
            unresolved_conflicts.append(gold_id)
    if unresolved_conflicts:
        blockers.append(f"来源槽位状态澄清未完成：{unresolved_conflicts}")

    # ── 5. 金标切片与负例集合一致性 ────────────────────────────────────────
    if set(candidates) != set(gold_by_id):
        blockers.append("候选与冻结 query-gold 的题号集合不一致")

    if not blockers:
        blockers.extend(
            _projection_errors(_project(payload, gold, slots, decisions), payload, slots)
        )

    return {
        "ready": not blockers,
        "stage": "evaluated",
        "reviewer": decisions.get("reviewer"),
        "reviewed_at": decisions.get("reviewed_at"),
        "based_on": based_on,
        "counts": {
            "facet_decisions_expected": len(expected_items),
            "facet_decisions_present": len(decided),
            "facet_decisions_unresolved": len(unresolved),
            "question_reviews_expected": len(answerable),
            "question_reviews_present": len(reviewed),
            "negative_reviews_expected": len(negatives),
            "negative_reviews_present": len(neg_done),
            "status_clarifications_expected": len(conflicts),
            "status_clarifications_present": len(resolved),
        },
        "blockers": blockers,
        "unresolved_items": unresolved,
        "warnings": warnings,
        "note": (
            "门只看本审批件：候选文件里的 adjudication.status 改不动结论；"
            "驳回不删除原题要求，补标注须先形成新的 source-gold 版本"
        ),
    }


def project(
    payload: Mapping[str, object],
    gold: Sequence[Mapping[str, object]],
    slots: Sequence[Mapping[str, object]],
    decisions: Mapping[str, object],
) -> dict[str, object]:
    """Only validated decisions may produce an approved projection, including direct callers."""
    report = evaluate(payload, gold, slots, decisions)
    if not report["ready"]:
        raise ValueError("批准投影被阻断：" + "; ".join(report["blockers"]))
    return _project(payload, gold, slots, decisions)


def _project(payload, gold, slots, decisions):

    slot_by_id = {str(slot.get("gold_id")): slot for slot in slots}
    gold_by_id = {str(item["query_id"]): item for item in gold}
    decisions_by_item = {
        str(entry.get("item_id")): entry
        for entry in decisions.get("facet_decisions") or []
        if isinstance(entry, Mapping)
    }
    questions: list[dict[str, object]] = []
    for question in payload.get("questions", []):
        query_id = str(question["query_id"])
        required: list[dict[str, object]] = []
        supplementary: list[dict[str, object]] = []
        for target in question.get("targets") or []:
            if target["role"] == "required":
                required.append(_target_spec(target, "approved_required"))
            elif target["role"] == "supplementary":
                supplementary.append(_target_spec(target, "supplementary"))
        for entry in question.get("pending_human") or []:
            if entry.get("kind") == "answer_constraint":
                continue
            decision_entry = decisions_by_item.get(str(entry["item_id"]))
            if decision_entry is None:
                continue
            if str(decision_entry.get("decision") or "") not in ("批准", "改选"):
                continue
            for slot_id, index in _chosen_keys(decision_entry):
                slot = slot_by_id.get(slot_id, {})
                item = next((candidate for i, candidate in split_items(slot) if i == index), {})
                required.append(
                    {
                        "target_id": f"a-{len(required) + 1}",
                        "role": "approved_required",
                        "quote": str(item.get("quote") or ""),
                        "locator": _locator_tokens(slot, item),
                        "source_id": str(slot.get("source_id")),
                        "constraints": {
                            key: (item.get(key) if isinstance(item.get(key), str) else None)
                            for key in ("row", "col", "cell", "unit", "period")
                        },
                        "basis": {
                            "gold_id": slot_id,
                            "item_index": index,
                            "facet_id": entry.get("facet_id"),
                            "decided_item_id": entry["item_id"],
                            "decision": decision_entry.get("decision"),
                        },
                    }
                )
        questions.append(
            {
                "query_id": query_id,
                "domain": question.get("domain"),
                "answer_existence": question.get("answer_existence"),
                "satisfy_rule": question.get("satisfy_rule"),
                "evidence_required": question.get("evidence_required"),
                "relevant_sources": question.get("relevant_sources"),
                "requirement": gold_by_id.get(query_id, {}).get("evidence_requirement"),
                "approved_required": required,
                "supplementary": supplementary,
                "answer_constraints": question.get("answer_constraints") or [],
            }
        )
    return {
        "artifact": "i3-2-evidence-targets-approved",
        "rule_rev": payload.get("rule_rev"),
        "reviewer": decisions.get("reviewer"),
        "reviewed_at": decisions.get("reviewed_at"),
        "based_on": decisions.get("based_on"),
        "decision_record": decisions,
        "questions": questions,
    }


def _projection_errors(projection, payload, slots):
    errors = []
    by_slot = {s["gold_id"]: s for s in slots}
    by_question = {q["query_id"]: q for q in payload["questions"]}
    for question in projection["questions"]:
        qid = question["query_id"]
        original = by_question[qid]
        targets = question["approved_required"]
        if original.get("evidence_required") and not targets:
            errors.append(f"{qid}: 批准投影缺少必需证据")
        for target in targets + question["supplementary"]:
            basis = target.get("basis") or {}
            slot = by_slot.get(basis.get("gold_id"), {})
            item = dict(split_items(slot)).get(basis.get("item_index"), {})
            if (
                not _nonempty(target.get("quote"))
                or target["quote"] != item.get("quote")
                or not _nonempty(target.get("source_id"))
                or target["source_id"] != slot.get("source_id")
                or basis.get("gold_id") not in original.get("candidate_slots", [])
                or not target.get("locator")
                or target["locator"] != _locator_tokens(slot, item)
                or any(
                    (target.get("constraints") or {}).get(key)
                    != (item.get(key) if isinstance(item.get(key), str) else None)
                    for key in ("row", "col", "cell", "unit", "period")
                )
            ):
                errors.append(f"{qid}: 投影引用必须与合法 source-gold 原文/来源/定位一致")
        required_sources = {
            e["source_id"]
            for e in original.get("pending_human", [])
            if e.get("kind") == "source_coverage" and e.get("source_id")
        }
        missing = required_sources - {t["source_id"] for t in targets}
        if missing:
            errors.append(f"{qid}: 批准投影缺少来源义务 {sorted(missing)}")
    return errors


def _target_spec(target: Mapping[str, object], role: str) -> dict[str, object]:
    return {
        "target_id": target["target_id"],
        "role": role,
        "quote": target["quote"],
        "locator": list(target["locator"]),
        "source_id": target["source_id"],
        "constraints": target["constraints"],
        "basis": target["basis"],
    }


def _locator_tokens(slot: Mapping[str, object], item: Mapping[str, object]) -> list[str]:
    locator = slot.get("locator") or {}
    tokens = [
        f"page:{locator[key]}"
        for key in sorted(locator)
        if isinstance(locator, Mapping) and locator[key] not in (None, "")
    ]
    for key in ("row", "col"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            tokens.append(f"{key}:{value.strip()}")
    return tokens


def archive_previous() -> list[str]:
    archived: list[str] = []
    for current, pattern in (
        (APPROVED, "evidence-targets-approved-v{}.json"),
        (REPORT, "approval-report-v{}.json"),
    ):
        if not current.is_file():
            continue
        index = 1
        while (current.parent / pattern.format(index)).exists():
            index += 1
        target = current.parent / pattern.format(index)
        current.rename(target)
        archived.append(target.name)
    return archived


def main() -> int:
    for path in (CANDIDATES, QUERY_GOLD, SOURCE_GOLD):
        if not path.is_file():
            print(f"I3S2 APPLY FAILED: 缺少输入 {path}")
            return 1
    payload = json.loads(CANDIDATES.read_text(encoding="utf-8"))
    gold = load_jsonl(QUERY_GOLD)
    slots = load_jsonl(SOURCE_GOLD)
    decisions = json.loads(DECISIONS.read_text(encoding="utf-8")) if DECISIONS.is_file() else None

    report = evaluate(payload, gold, slots, decisions)
    report["artifact"] = "i3-2-evidence-targets-approval-report"
    report["generated_at"] = datetime.now(timezone(timedelta(hours=8))).isoformat(
        timespec="seconds"
    )
    report["inputs"] = {
        "candidates_sha256": digest(CANDIDATES),
        "query_gold_sha256": digest(QUERY_GOLD),
        "source_gold_sha256": digest(SOURCE_GOLD),
        "decisions_present": decisions is not None,
        "decisions_sha256": digest(DECISIONS) if DECISIONS.is_file() else None,
    }
    report["applier_sha256"] = digest(Path(__file__))

    archived = archive_previous()
    if archived:
        print(f"archived previous: {', '.join(archived)}")
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"approval report: {REPORT} sha256={digest(REPORT)}")
    if decisions is not None and report["ready"]:
        # 批准投影只在门通过时产出：未通过时不得生成"看起来已批准"的投影。
        projection = project(payload, gold, slots, decisions)
        projection["generated_at"] = report["generated_at"]
        APPROVED.write_text(
            json.dumps(projection, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"approved projection: {APPROVED} sha256={digest(APPROVED)}")
    print(
        json.dumps(
            {key: report[key] for key in ("ready", "stage", "counts") if key in report},
            ensure_ascii=False,
        )
    )
    for blocker in report.get("blockers", [])[:_MAX_LISTED]:
        print(f"  BLOCKED {blocker}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
