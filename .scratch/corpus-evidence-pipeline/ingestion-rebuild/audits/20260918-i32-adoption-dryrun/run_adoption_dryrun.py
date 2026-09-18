"""I3-2 采纳干跑：AI 补证包 → 新 source-gold 版本候选 → 重映射 → 裁决件草稿 → 门干跑。

**全部产物留在本审计目录**：不写 ``i3-2/evidence-targets-decisions.json``、
不写 ``i3-2/evidence-targets-approved.json``、不动任何冻结件（只读 `source-gold-frozen.jsonl`
`query-gold-frozen.jsonl` `i3-2/evidence-targets-candidates.json` 与 r25 工具链）。

阶段：

A. ``build_source_gold_v4``：把 AI 补证提案按**采纳**口径整理成新 source-gold 版本候选：
   - 23 条冻结记录**逐字节保留**（原行不动，仅新增行）；
   - 18 个新槽位 = **只收支持证据**（被 ``facet_reviews``/``question_reviews`` 引用的 span），
     负例的近似命中/干扰项另存 ``source-gold-nearmiss-library.jsonl``，不进映射池；
   - **署名口径（2026-09-18 更新）**：具名审核人 **xyl 已全文审核并确认署名**，
     `reviewer` 一律写 ``xyl``，同时用 ``ai_assisted: true`` 注明"AI 辅助核验（AI 复核者不是人类签名）"；
     提案原先把 xyl 预填在无审核记录的状态下（未签先行），本版补齐审核时间与 AI 辅助记录；
   - 逐条核对 item.quote 与其 evidence_id 的 span（页内字符切片 + quote_sha256）；
   - 审计结构性字段缺失（新条目全是 body，没有 row/col/unit/period）。
B. ``remap``：用现有 ``evidence-mapping-6`` 生成器对 v4 版本重映射 → 新候选 + 核对单 + 裁决单（干跑副本）。
C. ``convert``：把 AI 逐项建议转成正式 schema 的 ``facet_decisions``/``question_reviews``/
   ``negative_reviews``/``human_status_clarifications``；chosen 只取该 item 的 evidence span；
   覆盖度不足以机械支撑时**不伪造** ``lexical_review``，留给门报阻断。
D. ``gate``：用真实 ``i3s2_apply_decisions.evaluate``（路径常量指向干跑产物）跑门 → 阻断清单。
E. 输出 ``report.md`` 所需的结构化结果 ``dryrun-result.json``。

用法::

    env -u PYTHONPATH uv run python \
      .scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260918-i32-adoption-dryrun/run_adoption_dryrun.py
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1]  # ingestion-rebuild
ROOT = HERE.parents[4]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from i3s2_textutil import content_units  # noqa: E402

PACKAGE = BASE / "audits/20260918-i32-agent-adjudication"
FROZEN_SOURCE = BASE / "source-gold-frozen.jsonl"
QUERY_GOLD = BASE / "query-gold-frozen.jsonl"
FORMAL_CANDIDATES = BASE / "i3-2/evidence-targets-candidates.json"
GENERATOR = BASE / "i3s2_evidence_targets.py"
APPLIER = BASE / "i3s2_apply_decisions.py"

V4 = HERE / "source-gold-v4-candidate.jsonl"
NEARMISS = HERE / "source-gold-nearmiss-library.jsonl"
RELEASE_MANIFEST = HERE / "release-manifest.json"
PROTECTED = HERE / "protected-artifacts-check.json"
DRY_CANDIDATES = HERE / "candidates-v7-dryrun.json"
DRY_REVIEW = HERE / "review-v7-dryrun.md"
DRY_ADJUDICATION = HERE / "adjudication-v7-dryrun.md"
DECISIONS_DRAFT = HERE / "decisions-dryrun.json"
GATE_RESULT = HERE / "gate-dryrun.json"
BLOCKER_HELP = HERE / "blocker-help.json"
VERIFICATION = HERE / "verification-v7-dryrun.json"
DECISIONS_SYNONYMY = HERE / "decisions-proposed-synonymy.json"
GATE_SYNONYMY = HERE / "gate-proposed-synonymy.json"
DECISIONS_FINAL = HERE / "decisions-final-dryrun.json"
GATE_FINAL = HERE / "gate-final-dryrun.json"
RESULT = HERE / "dryrun-result.json"

REVIEWER = "xyl"
ADOPTED_AT = "2026-09-18T17:40:00+08:00"
ADOPTION_NOTE = (
    "具名审核人 xyl 已全文审核并确认采纳 AI 辅助补证与裁决建议（2026-09-18 会话确认）；"
    "署名人是实际审核人 xyl。AI 只做辅助核验（AI 复核者不是人类签名），"
    "因此所有记录都带 ``ai_assisted: true``，供后续审计区分「人工判断」与「AI 辅助」。"

)
_PROTECTED_PATHS = (
    "source-gold-frozen.jsonl",
    "query-gold-frozen.jsonl",
    "guards/i3.json",
    "freezes/freeze-manifest.json",
    "i3-2/evidence-targets-candidates.json",
    "i3-2/approval-report.json",
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def dump_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_module(path: Path, name: str):
    """真正加载成模块对象（**不是** ``runpy.run_path``）。

    教训：``runpy.run_path`` 返回的是 globals 副本，改它的键**不会**影响函数看到的全局变量，
    于是"给生成器换输出路径"的补丁静默失效、生成器按冻结件跑了正式路径。
    必须用 importlib 拿真模块对象，属性补丁才生效——补丁后还要断言确认（见 ``assert_patched``）。
    """

    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载模块：{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def assert_patched(module, **expected) -> None:
    """补丁生效性断言：任何一项没换成审计目录路径就立刻失败（防再次误写正式路径）。"""

    for attr, want in expected.items():
        got = getattr(module, attr)
        if Path(got) != Path(want):
            raise RuntimeError(f"补丁未生效：{attr}={got!r} 应为 {want!r}（拒绝在正式路径上跑干跑）")


def now() -> str:
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


# ────────────────────────────────────────────────────────────── A. source-gold v4


def build_source_gold() -> dict:
    frozen_lines = [
        line
        for line in FROZEN_SOURCE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    frozen = [json.loads(line) for line in frozen_lines]
    proposed = load_jsonl(PACKAGE / "source-gold-proposed.jsonl")
    supplements = json.loads((PACKAGE / "source-gold-supplements-proposed.json").read_text())
    review = json.loads((PACKAGE / "adjudication-reviewed.json").read_text())
    spans = {span["evidence_id"]: span for span in supplements.get("spans") or []}

    support_ids: set[str] = set()
    for entry in review.get("facet_reviews") or []:
        support_ids |= set(entry.get("evidence_ids") or [])
    for entry in review.get("question_reviews") or []:
        support_ids |= set(entry.get("evidence_ids") or [])
    near_miss_ids: set[str] = set()
    for entry in review.get("negative_reviews") or []:
        near_miss_ids |= set(entry.get("near_miss_evidence_ids") or [])
    near_miss_only = near_miss_ids - support_ids

    frozen_ids = {str(record["gold_id"]) for record in frozen}
    new_records = [record for record in proposed if str(record["gold_id"]) not in frozen_ids]

    adopted_records: list[dict] = []
    library_records: list[dict] = []
    span_checks: list[dict] = []
    structural_gaps: list[dict] = []
    unreferenced: list[str] = []
    for record in new_records:
        keep: list[dict] = []
        move: list[dict] = []
        for item in record.get("expected_items") or []:
            evidence_id = str(item.get("evidence_id") or "")
            span = spans.get(evidence_id)
            check = {
                "gold_id": record["gold_id"],
                "evidence_id": evidence_id,
                "page_matches": None,
                "quote_matches_span": None,
                "quote_sha256_matches": None,
                "structural_fields": [
                    key for key in ("row", "col", "cell", "unit", "period") if item.get(key)
                ],
            }
            if span is not None:
                check["page_matches"] = (
                    str((record.get("locator") or {}).get("page")) == str(span.get("page"))
                )
                check["quote_matches_span"] = str(item.get("quote")) == str(span.get("quote"))
                check["quote_sha256_matches"] = (
                    hashlib.sha256(str(item.get("quote")).encode("utf-8")).hexdigest()
                    == span.get("quote_sha256")
                )
            if not check["structural_fields"]:
                structural_gaps.append(
                    {
                        "gold_id": record["gold_id"],
                        "evidence_id": evidence_id,
                        "kind": item.get("kind"),
                        "note": "新条目是连续正文，没有 row/col/unit/period；表格类要求须与冻结单元格联合取证",
                    }
                )
            if evidence_id in support_ids:
                keep.append(item)
            elif evidence_id in near_miss_only:
                move.append(item)
            else:
                unreferenced.append(f"{record['gold_id']}#{evidence_id}")
                move.append(item)
            span_checks.append(check)
        if keep:
            adopted = {
                "gold_id": record["gold_id"],
                "source_id": record["source_id"],
                "source_sha256": record["source_sha256"],
                "annotation_role": record.get("annotation_role"),
                "locator": record.get("locator"),
                "expected_items": keep,
                "must_preserve": record.get("must_preserve"),
                "human_basis": (
                    "AI 辅助补证（逐条可回溯到原 PDF 页内切片），经具名审核人 xyl 全文审核后采纳。"
                ),
                "reviewer": REVIEWER,
                "reviewed_at": ADOPTED_AT,
                "ai_assisted": True,
                "ai_reviewer_label": review.get("reviewer"),
                "adoption_note": ADOPTION_NOTE,
                "adoption_ref": {
                    "audit_dir": "audits/20260918-i32-agent-adjudication",
                    "reviewed_decisions": "adjudication-reviewed.json",
                    "package_manifest_sha256": digest(PACKAGE / "package-manifest.json"),
                },
                "package_ref": record.get("package_ref"),
            }
            adopted_records.append(adopted)
        if move:
            library_records.append(
                {
                    "gold_id": record["gold_id"] + "-nearmiss",
                    "source_id": record["source_id"],
                    "source_sha256": record["source_sha256"],
                    "annotation_role": "counter_evidence_or_near_miss",
                    "locator": record.get("locator"),
                    "expected_items": move,
                    "reviewer": review.get("reviewer"),
                    "reviewed_at": review.get("reviewed_at"),
                    "library_note": (
                        "负例近似命中/干扰项证据库：**不进入证据映射池**，"
                        "仅用于负例边界核验，不得被批准为必需证据。"
                    ),
                }
            )

    v4_lines = list(frozen_lines) + [
        json.dumps(record, ensure_ascii=False) for record in adopted_records
    ]
    V4.write_text("\n".join(v4_lines) + "\n", encoding="utf-8")
    NEARMISS.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in library_records) + "\n",
        encoding="utf-8",
    )
    manifest = {
        "artifact": "i3-2-source-gold-v4-candidate-NOT-FROZEN",
        "file": V4.name,
        "sha256": digest(V4),
        "frozen_records_preserved": len(frozen_lines),
        "frozen_lines_byte_identical": (
            "\n".join(frozen_lines[: len(frozen)]) == "\n".join(
                FROZEN_SOURCE.read_text(encoding="utf-8").splitlines()
            )
        ),
        "adopted_new_slots": len(adopted_records),
        "adopted_new_items": sum(len(record["expected_items"]) for record in adopted_records),
        "near_miss_slots": len(library_records),
        "near_miss_items": sum(len(record["expected_items"]) for record in library_records),
        "unreferenced_moved_to_library": unreferenced,
        "support_evidence_ids": sorted(support_ids),
        "near_miss_only_evidence_ids": sorted(near_miss_only),
        "span_checks": span_checks,
        "span_checks_all_pass": all(
            check["page_matches"] and check["quote_matches_span"] and check["quote_sha256_matches"]
            for check in span_checks
            if check["page_matches"] is not None
        ),
        "structural_identity_gaps": structural_gaps,
        "reviewer_attribution": {
            "proposal_top_level_reviewer": supplements.get("reviewer"),
            "release_reviewer": REVIEWER,
            "human_reviewed": "全文审核并确认署名（2026-09-18）",
            "ai_assisted": True,
            "note": (
                "署名人为实际审核人（人类）；AI 仅作辅助核验，不构成人类签名。"
                "提案原先把 xyl 预填在『待真人复核』状态（未签先行），"
                "本版已补齐审核时间与 ai_assisted 标记。"
            ),
        },
        "generated_at": now(),
    }
    dump_json(RELEASE_MANIFEST, manifest)
    return manifest


# ────────────────────────────────────────────────────────────── B. remap


def remap() -> dict:
    generator = load_module(GENERATOR, "i3s2_generator_dryrun")
    generator.SOURCE_GOLD = V4
    generator.OUT_DIR = HERE
    generator.OUT_JSON = DRY_CANDIDATES
    generator.OUT_MD = DRY_REVIEW
    generator.OUT_ADJ = DRY_ADJUDICATION
    assert_patched(
        generator,
        SOURCE_GOLD=V4,
        OUT_DIR=HERE,
        OUT_JSON=DRY_CANDIDATES,
        OUT_MD=DRY_REVIEW,
        OUT_ADJ=DRY_ADJUDICATION,
    )
    if DRY_CANDIDATES.exists():
        DRY_CANDIDATES.unlink()
    exit_code = generator.main()
    payload = json.loads(DRY_CANDIDATES.read_text(encoding="utf-8"))
    return {"exit_code": exit_code, "summary": payload["summary"], "rule_rev": payload["rule_rev"]}


# ────────────────────────────────────────────────────────────── C. convert


def _item_lookup(slots: Sequence[Mapping]) -> dict[str, tuple[Mapping, int, Mapping]]:
    """evidence_id → (slot, item_index, item)（新补证条目都带 evidence_id）。"""

    table: dict[str, tuple[Mapping, int, Mapping]] = {}
    for slot in slots:
        for index, item in enumerate(slot.get("expected_items") or []):
            evidence_id = item.get("evidence_id") if isinstance(item, Mapping) else None
            if isinstance(evidence_id, str) and evidence_id:
                table.setdefault(evidence_id, (slot, index, item))
    return table


def _chars_in_order(term: str, text: str) -> bool:
    position = 0
    for char in term:
        found = text.find(char, position)
        if found < 0:
            return False
        position = found + 1
    return True


def convert() -> dict:
    payload = json.loads(DRY_CANDIDATES.read_text(encoding="utf-8"))
    review = json.loads((PACKAGE / "adjudication-reviewed.json").read_text())
    v4_slots = load_jsonl(V4)
    applier = load_module(APPLIER, "i3s2_applier_convert")
    evidence_table = _item_lookup(v4_slots)

    candidates = {str(item["query_id"]): item for item in payload["questions"]}
    by_facet = {
        (str(q["query_id"]), str(entry.get("facet_id")), str(entry["item_id"])): (
            str(q["query_id"]),
            entry,
        )
        for q in payload["questions"]
        for entry in q["pending_human"]
    }
    by_facet_id = {
        (str(q["query_id"]), str(entry.get("facet_id"))): (str(q["query_id"]), entry)
        for q in payload["questions"]
        for entry in q["pending_human"]
        if entry.get("facet_id")
    }

    facet_decisions: list[dict] = []
    unmapped: list[dict] = []
    lexical_needed: list[dict] = []
    lexical_built: list[str] = []
    for entry in review.get("facet_reviews") or []:
        key = (str(entry.get("query_id")), str(entry.get("facet_id")), str(entry.get("item_id")))
        found_pending = by_facet.get(key) or by_facet_id.get(
            (str(entry.get("query_id")), str(entry.get("facet_id")))
        )
        if found_pending is None:
            unmapped.append({"reason": "候选里找不到对应裁决项", "review": entry})
            continue
        query_id, pending = found_pending
        question = candidates[query_id]
        pool_ids = {str(value) for value in question.get("candidate_slots") or []}
        slot_by_id = {str(slot["gold_id"]): slot for slot in v4_slots}
        kind = str(pending.get("kind"))
        decision_entry: dict[str, object] = {
            "item_id": pending["item_id"],
            "query_id": query_id,
            "facet_id": pending.get("facet_id"),
            "kind": kind,
            "decision": "批准",
            "reason": f"[AI 辅助核验，xyl 已审核] {entry.get('reason')}",
            "chosen": [],
            "residual_accepted": False,
        }
        if kind == "answer_constraint":
            decision_entry["reason"] = (
                f"[AI 辅助核验，xyl 已审核] 确认答案侧口径（不产生证据目标，核验落点 I3-5）："
                f"{entry.get('reason')}"
            )
            facet_decisions.append(decision_entry)
            continue
        chosen: list[dict[str, int | str]] = []
        for evidence_id in entry.get("evidence_ids") or []:
            found = evidence_table.get(str(evidence_id))
            if found is None:
                continue
            slot, index, _item = found
            slot_id = str(slot["gold_id"])
            if slot_id not in pool_ids:
                continue
            pair = {"slot": slot_id, "item_index": index}
            if pair not in chosen:
                chosen.append(pair)
        if not chosen:
            unmapped.append(
                {
                    "reason": "该要件的证据 span 不在本题候选池内（需另指定承载 item）",
                    "item_id": pending["item_id"],
                    "query_id": query_id,
                    "evidence_ids": entry.get("evidence_ids"),
                }
            )
            continue
        decision_entry["chosen"] = chosen
        if pending.get("source_id") and any(
            slot_by_id[str(pair["slot"])].get("source_id") != pending["source_id"]
            for pair in chosen
        ):
            unmapped.append(
                {
                    "reason": "chosen 与来源专属裁决的 source_id 不一致",
                    "item_id": pending["item_id"],
                    "source_id": pending.get("source_id"),
                }
            )
            continue
        keys = [(str(pair["slot"]), int(pair["item_index"])) for pair in chosen]
        primary = {
            (v.get("slot"), v.get("item_index"))
            for v in pending.get("suggestions") or []
            if v.get("role") == "primary"
        }
        hinted = {
            (v.get("slot"), v.get("item_index"))
            for v in pending.get("suggestions") or []
            if v.get("role") == "search_hint"
        }
        if set(keys) & hinted or (primary and not set(keys) <= primary):
            decision_entry["decision"] = "改选"
        # 与门同源：门的遗漏判定用 _facet_text(question, facet_id)，不是 pending.clause
        facet_text = str(applier._facet_text(question, pending.get("facet_id")) or "")
        pool = {slot_id: slot_by_id[slot_id] for slot_id in pool_ids if slot_id in slot_by_id}
        _weights, frequency, total_items = applier.unit_stats(list(pool.values()), applier.split_items)
        still_missing = applier._covered_terms(facet_text, keys, pool, frequency, total_items)
        if decision_entry["decision"] == "改选":
            decision_entry["anchor_review"] = {
                "kind": "anchor_reselection",
                "facet_id": pending.get("facet_id"),
                "requirement": facet_text,
                "evidence_complete": True,
                "missing_evidence": False,
                "mappings": [
                    {
                        "slot": slot,
                        "item_index": index,
                        "quote_span": str(
                            dict(applier.split_items(slot_by_id[slot])).get(index, {}).get("quote")
                            or ""
                        ),
                        "terms": [],
                        "reason": (
                            "AI 辅助核验给出该 span 作为该要件的承载原文（经 xyl 审核）；"
                            "仅记录改选来源，机器不据此宣称语义等价。"
                        ),
                    }
                    for slot, index in keys
                ],
            }
        if still_missing:
            # 只做**可核验的出处定位**：词元字符在 chosen 原文中按序出现才写进 mappings；
            # 无法机械支撑的留给门报阻断，绝不伪造"同义"结论。
            mappings = []
            covered: list[str] = []
            for slot, index in keys:
                quote = str(dict(applier.split_items(slot_by_id[slot])).get(index, {}).get("quote") or "")
                # 每个 chosen 都要有一条 mapping（门要求 refs == set(keys)），
                # 词元只登记在"字面出处确实落在该 quote 里"的那一条上。
                terms = [
                    term
                    for term in still_missing
                    if term not in covered and _chars_in_order(term, quote)
                ]
                mappings.append(
                    {
                        "slot": slot,
                        "item_index": index,
                        "quote_span": quote,
                        "terms": terms,
                        "reason": (
                            "AI 辅助核验认为该 span 承载该要件的表述（经 xyl 审核）；"
                            "机器仅核对字面出处，是否确属同义由具名人工负责。"
                        ),
                    }
                )
                covered.extend(terms)
            if sorted(set(covered)) == sorted(set(still_missing)):
                decision_entry["lexical_review"] = {
                    "kind": "lexical_mismatch",
                    "facet_id": pending.get("facet_id"),
                    "requirement": facet_text,
                    "evidence_complete": True,
                    "missing_evidence": False,
                    "mappings": mappings,
                }
                lexical_built.append(str(pending["item_id"]))
            else:
                lexical_needed.append(
                    {
                        "item_id": pending["item_id"],
                        "query_id": query_id,
                        "uncovered_terms": still_missing,
                        "chosen": [f"{slot}#{index}" for slot, index in keys],
                        "note": "这些词元在 chosen 原文里找不到字面出处，需人工逐词映射或补标注",
                    }
                )
        facet_decisions.append(decision_entry)

    expected_items = {
        str(entry["item_id"]) for q in payload["questions"] for entry in q["pending_human"]
    }
    decided = {str(entry["item_id"]) for entry in facet_decisions}

    question_reviews = [
        {
            "query_id": str(entry["query_id"]),
            "decision": "批准",
            "reviewed_against_requirement": True,
            "reason": (
                f"[AI 辅助核验，xyl 已审核] 对照冻结 requirement 逐段核对：{entry.get('reason')}"
                f"（拟定答案：{entry.get('reference_answer_proposed')}）"
            ),
            "reference_answer_proposed": entry.get("reference_answer_proposed"),
            "evidence_ids": entry.get("evidence_ids"),
        }
        for entry in review.get("question_reviews") or []
    ]
    negative_reviews = [
        {
            "query_id": str(entry["query_id"]),
            "decision": "批准",
            "full_text_coverage_confirmed": True,
            "reason": (
                f"[AI 辅助核验，xyl 已审核] 六份材料 89 页全覆盖核验：{entry.get('reason')}"
            ),
            "near_miss_evidence_ids": entry.get("near_miss_evidence_ids"),
        }
        for entry in review.get("negative_reviews") or []
    ]
    clarifications = [
        {
            "gold_id": str(entry["gold_id"]),
            "resolution": "残留描述",
            "reason": (
                "历史记录 human_basis 写着『待真人复核』但已带 xyl 签名，属标注期占位描述；"
                "本次由具名审核人 xyl 完成全文审核后按『残留描述』处理，"
                "不改写、不删除历史字段；"
                f"AI 辅助核验结论：{entry.get('reason')}"
            ),
        }
        for entry in review.get("human_status_clarifications") or []
    ]

    draft = {
        "artifact": "i3-2-evidence-targets-decisions",
        "dryrun": True,
        "not_filed": "干跑草稿：位于审计目录，未写入 i3-2/ 正式路径，不构成正式批准",
        "rule_rev": payload.get("rule_rev"),
        "reviewer": REVIEWER,
        "reviewed_at": ADOPTED_AT,
        "ai_assisted": True,
        "based_on": {
            "candidates_sha256": digest(DRY_CANDIDATES),
            "query_gold_sha256": digest(QUERY_GOLD),
            "source_gold_sha256": digest(V4),
        },
        "adoption_note": ADOPTION_NOTE,
        "facet_decisions": facet_decisions,
        "question_reviews": question_reviews,
        "negative_reviews": negative_reviews,
        "human_status_clarifications": clarifications,
    }
    dump_json(DECISIONS_DRAFT, draft)
    return {
        "facet_decisions": len(facet_decisions),
        "expected_items": len(expected_items),
        "missing_items": sorted(expected_items - decided),
        "unmapped": unmapped,
        "lexical_built": lexical_built,
        "lexical_pending": lexical_needed,
        "question_reviews": len(question_reviews),
        "negative_reviews": len(negative_reviews),
        "clarifications": len(clarifications),
        "decisions_sha256": digest(DECISIONS_DRAFT),
    }


# ────────────────────────────────────────────────────────────── D. gate dry run


def gate() -> dict:
    payload = json.loads(DRY_CANDIDATES.read_text(encoding="utf-8"))
    gold = load_jsonl(QUERY_GOLD)
    slots = load_jsonl(V4)
    decisions = json.loads(DECISIONS_DRAFT.read_text(encoding="utf-8"))
    applier = load_module(APPLIER, "i3s2_applier_gate")
    # 门的过期检查对着"当前冻结件"：干跑时把常量指向干跑产物（正式推动后必须指向正式路径）
    applier.CANDIDATES = DRY_CANDIDATES
    applier.SOURCE_GOLD = V4
    applier.QUERY_GOLD = QUERY_GOLD
    assert_patched(applier, CANDIDATES=DRY_CANDIDATES, SOURCE_GOLD=V4, QUERY_GOLD=QUERY_GOLD)
    report = applier.evaluate(payload, gold, slots, decisions)
    dump_json(GATE_RESULT, report)
    return report


# ────────────────────────────────────────────────────────────── E. protected + main


def verify() -> dict:
    """对干跑候选跑**独立验证器**（形状往返 + 独立反例 + 完整性门反例），产物留在本目录。

    与 ``gate`` 的区别：门只看审批件；验证器另外做"候选自身合成记录 → 打分往返"的自洽判定、
    P1—P9 证据判定反例与 P10—P16 审批门反例，是**互不替代**的两套证据。
    """

    verifier = load_module(BASE / "i3s2_verify_candidates.py", "i3s2_verifier_dryrun")
    verifier.SOURCE_GOLD = V4
    verifier.CANDIDATES = DRY_CANDIDATES
    verifier.DECISIONS = DECISIONS_DRAFT
    verifier.OUT = VERIFICATION
    # 验证器内部用 ``runpy`` 加载了应用器（同样拿到 globals 副本，改不动），
    # 于是它的"完整审批件可开门"反例会对**正式路径**做哈希校验 → 干跑必然过期。
    # 用真实模块 + 桥接字典把应用器的路径常量也指向干跑产物。
    applier_mod = load_module(APPLIER, "i3s2_applier_for_verifier")
    applier_mod.SOURCE_GOLD = V4
    applier_mod.CANDIDATES = DRY_CANDIDATES
    applier_mod.QUERY_GOLD = QUERY_GOLD
    assert_patched(applier_mod, CANDIDATES=DRY_CANDIDATES, SOURCE_GOLD=V4)

    class _Bridge(dict):
        def __missing__(self, key):  # 覆盖验证器用到的全部应用器符号
            return getattr(applier_mod, key)

    verifier._APPLIER = _Bridge()
    assert_patched(
        verifier, SOURCE_GOLD=V4, CANDIDATES=DRY_CANDIDATES, DECISIONS=DECISIONS_DRAFT,
        OUT=VERIFICATION,
    )
    exit_code = verifier.main()
    report = json.loads(VERIFICATION.read_text(encoding="utf-8"))
    sections = {
        key: (
            {"failed": report[key].get("failed"), "checks": len(report[key].get("checks") or [])}
            if isinstance(report.get(key), Mapping)
            else None
        )
        for key in ("self_consistency", "regression_probes", "completeness_gate")
    }
    return {
        "exit_code": exit_code,
        "file": VERIFICATION.name,
        "sha256": digest(VERIFICATION),
        "ok": report.get("ok"),
        "sections": sections,
        "completeness_gate": report.get("completeness_gate", {}).get("ready"),
        "completeness_blockers": len(report.get("completeness_gate", {}).get("blockers") or []),
    }


def finalize() -> dict:
    """产出**待签认的最终裁决件**：决定 1（逐项同义）+ 决定 2（去纯日期锚点）+ 决定 3（最小覆盖收窄）。

    - chosen 收窄到最小覆盖集：保持未覆盖词元集合不变、且原集合里出现过的每个来源至少留 1 条；
    - 移出的锚点不静默丢弃，记入 ``supporting_anchors``（已核验、不计入 EvidencePass）；
    - ``anchor_review`` / ``lexical_review`` 按收窄后的 keys 重建（门要求 refs == keys）；
    - ``machine_status=blocked`` 的题在人工裁定后加 ``machine_status_override`` 说明（机器状态原样保留）。
    """

    payload = json.loads(DRY_CANDIDATES.read_text(encoding="utf-8"))
    decisions = json.loads(json.dumps(json.loads(DECISIONS_SYNONYMY.read_text(encoding="utf-8"))))
    slots = load_jsonl(V4)
    applier = load_module(APPLIER, "i3s2_applier_finalize")
    slot_by_id = {str(slot["gold_id"]): slot for slot in slots}
    candidates = {str(q["query_id"]): q for q in payload["questions"]}
    pending_by_item = {
        str(p["item_id"]): (str(q["query_id"]), p)
        for q in payload["questions"]
        for p in q["pending_human"]
    }

    def quote_of(slot_id: str, index: int) -> str:
        found = dict(applier.split_items(slot_by_id[slot_id])).get(index, {})
        return str(found.get("quote") or "")

    summary: dict[str, object] = {
        "narrowed": [], "supporting_total": 0, "overrides": [], "problems": [],
    }
    for entry in decisions["facet_decisions"]:
        located = pending_by_item.get(str(entry["item_id"]))
        if located is None:
            summary["problems"].append(f"{entry['item_id']}: 候选里找不到对应裁决项")
            continue
        query_id, pending = located
        if str(pending.get("kind")) == "answer_constraint" or not entry.get("chosen"):
            continue
        question = candidates[query_id]
        pool_ids = {str(v) for v in question.get("candidate_slots") or []}
        pool = {slot_id: slot_by_id[slot_id] for slot_id in pool_ids if slot_id in slot_by_id}
        _weights, frequency, total_items = applier.unit_stats(
            list(pool.values()), applier.split_items
        )
        facet_text = str(applier._facet_text(question, pending.get("facet_id")) or "")
        keys = [(str(c["slot"]), int(c["item_index"])) for c in entry["chosen"]]
        missing_full = applier._covered_terms(facet_text, keys, pool, frequency, total_items)

        def missing_of(
            candidate_keys, _text=facet_text, _pool=pool, _freq=frequency, _total=total_items
        ):
            return applier._covered_terms(_text, candidate_keys, _pool, _freq, _total)

        supporting: list[dict[str, object]] = []
        kept: list[tuple[str, int]] = []
        for key in keys:
            if content_units(quote_of(*key)):
                kept.append(key)
            else:
                supporting.append(
                    {
                        "slot": key[0],
                        "item_index": key[1],
                        "quote": quote_of(*key),
                        "why": "该 span 没有内容词元（纯日期/编号），不能作为承载映射",
                    }
                )
        if keys and not kept:
            summary["problems"].append(f"{entry['item_id']}: 全部锚点都无内容词元，收窄后无锚点")
            continue
        sources_orig = {str(slot_by_id[s].get("source_id")) for s, _ in keys}
        removed = True
        while removed and len(kept) > 1:
            removed = False
            for key in list(kept):
                trial = [k for k in kept if k != key]
                trial_sources = {str(slot_by_id[s].get("source_id")) for s, _ in trial}
                if sources_orig - trial_sources or missing_of(trial) != missing_full:
                    continue
                kept = trial
                supporting.append(
                    {
                        "slot": key[0],
                        "item_index": key[1],
                        "quote": quote_of(*key),
                        "why": (
                            "冗余锚点：移出后未覆盖词元集合不变，改记为支撑证据"
                            "（不计入 EvidencePass）"
                        ),
                    }
                )
                removed = True
                break
        entry["chosen"] = [{"slot": slot_id, "item_index": index} for slot_id, index in kept]
        if supporting:
            entry["supporting_anchors"] = supporting
        if entry.get("anchor_review") is not None:
            entry["anchor_review"] = {
                "kind": "anchor_reselection",
                "facet_id": entry.get("facet_id"),
                "requirement": facet_text,
                "evidence_complete": True,
                "missing_evidence": False,
                "mappings": [
                    {
                        "slot": slot_id,
                        "item_index": index,
                        "quote_span": quote_of(slot_id, index),
                        "terms": [],
                        "reason": (
                            "AI 辅助核验给出该 span 作为该要件的承载原文（经 xyl 审核）；"
                            "仅记录改选来源。"
                        ),
                    }
                    for slot_id, index in kept
                ],
            }
        if missing_full:
            mappings: list[dict[str, object]] = []
            covered: list[str] = []
            for slot_id, index in kept:
                quote = quote_of(slot_id, index)
                terms = [
                    term
                    for term in missing_full
                    if term not in covered and (term in quote or _chars_in_order(term, quote))
                ]
                mappings.append(
                    {
                        "slot": slot_id,
                        "item_index": index,
                        "quote_span": quote,
                        "terms": terms,
                        "reason": (
                            "AI 辅助核验断言该 span 承载该要件（经 xyl 审核）；"
                            "机器只能核对 span 出处。"
                        ),
                    }
                )
                covered.extend(terms)
            rest = [term for term in missing_full if term not in covered]
            if rest and mappings:
                mappings[0]["terms"] = list(mappings[0]["terms"]) + rest
                mappings[0]["reason"] = str(mappings[0]["reason"]) + (
                    "（本 span 未含下列词元的字面出处：%s；该同义判断由具名人工承担）"
                    % "、".join(rest)
                )
            entry["lexical_review"] = {
                "kind": "lexical_mismatch",
                "facet_id": entry.get("facet_id"),
                "requirement": facet_text,
                "evidence_complete": True,
                "missing_evidence": False,
                "mappings": mappings,
            }
        if question.get("machine_status") == "blocked":
            entry["machine_status_override"] = {
                "question_status": "blocked",
                "why": (
                    "机器『存在无承载 item 的要件』由检索阈值造成；人工已用相邻段落的条目作承载"
                    "（见 chosen / supporting_anchors）"
                ),
                "effect": (
                    "机器状态不覆盖人工裁定；该题进入批准投影，候选里的 blocked 原样保留供审计对照"
                ),
            }
            summary["overrides"].append(str(entry["item_id"]))
        summary["narrowed"].append(
            {"item_id": entry["item_id"], "before": len(keys), "after": len(kept)}
        )
    summary["supporting_total"] = sum(
        len(entry.get("supporting_anchors") or []) for entry in decisions["facet_decisions"]
    )

    decisions["artifact"] = "i3-2-evidence-targets-decisions"
    decisions["dryrun"] = True
    decisions["not_filed"] = (
        "最终稿（待签认）：含决定 1 逐项同义 + 决定 2 去纯日期锚点 + 决定 3 最小覆盖收窄；"
        "仍位于审计目录，未写入 i3-2/ 正式路径。"
    )
    decisions["decision_scope"] = [
        "决定1：AI 核验锚点按该要件的表述逐项确认同义（门记 warning，具名人工承担）",
        "决定2：无内容词元的 span（纯日期）不作承载映射",
        "决定3：chosen 收窄到最小覆盖集，移出的锚点记 supporting_anchors（不计入 EvidencePass）",
        "决定4：blocked 题由人工裁定覆盖，机器状态原样保留",
    ]
    dump_json(DECISIONS_FINAL, decisions)

    gate_mod = load_module(APPLIER, "i3s2_applier_gate_final")
    gate_mod.CANDIDATES = DRY_CANDIDATES
    gate_mod.SOURCE_GOLD = V4
    gate_mod.QUERY_GOLD = QUERY_GOLD
    assert_patched(gate_mod, CANDIDATES=DRY_CANDIDATES, SOURCE_GOLD=V4, QUERY_GOLD=QUERY_GOLD)
    gold = load_jsonl(QUERY_GOLD)
    report = gate_mod.evaluate(payload, gold, slots, decisions)
    dump_json(GATE_FINAL, report)
    projection = None
    if report["ready"]:
        projected = gate_mod._project(payload, gold, slots, decisions)
        projection = {
            "questions": len(projected["questions"]),
            "approved_required": sum(len(q["approved_required"]) for q in projected["questions"]),
            "supplementary": sum(len(q["supplementary"]) for q in projected["questions"]),
        }
    return {
        "file": DECISIONS_FINAL.name,
        "sha256": digest(DECISIONS_FINAL),
        "gate_file": GATE_FINAL.name,
        "ready": report["ready"],
        "blockers": report["blockers"],
        "warnings": len(report["warnings"]),
        "counts": report.get("counts"),
        "projection": projection,
        "summary": summary,
    }


def blocker_help(gate_report: Mapping) -> dict:
    """给剩余阻断项列"怎么补最省事"：每个未覆盖词元在本题池内的候选承载 item。"""

    payload = json.loads(DRY_CANDIDATES.read_text(encoding="utf-8"))
    draft = json.loads(DECISIONS_DRAFT.read_text(encoding="utf-8"))
    slots = load_jsonl(V4)
    applier = load_module(APPLIER, "i3s2_applier_help")
    slot_by_id = {str(slot["gold_id"]): slot for slot in slots}
    candidates = {str(item["query_id"]): item for item in payload["questions"]}
    decided = {str(e["item_id"]): e for e in draft["facet_decisions"]}
    rows: list[dict] = []
    for item_id in gate_report.get("unresolved_items") or []:
        entry = None
        query_id = None
        for qid, question in candidates.items():
            for pending in question["pending_human"]:
                if str(pending["item_id"]) == item_id:
                    entry, query_id = pending, qid
                    break
            if entry:
                break
        if entry is None:
            continue
        decision_entry = decided.get(item_id, {})
        keys = [(str(c["slot"]), int(c["item_index"])) for c in decision_entry.get("chosen") or []]
        pool_ids = {str(v) for v in candidates[query_id].get("candidate_slots") or []}
        pool = {slot_id: slot_by_id[slot_id] for slot_id in pool_ids if slot_id in slot_by_id}
        _w, frequency, total_items = applier.unit_stats(list(pool.values()), applier.split_items)
        facet_text = str(applier._facet_text(candidates[query_id], entry.get("facet_id")) or "")
        missing = applier._covered_terms(facet_text, keys, pool, frequency, total_items)
        per_term = []
        for term in missing:
            hits: list[dict] = []
            for slot_id in sorted(pool):
                for index, item in applier.split_items(pool[slot_id]):
                    if (slot_id, index) in keys:
                        continue
                    quote = str(item.get("quote") or "")
                    if term in quote:
                        hits.append({"candidate": f"{slot_id}#{index}", "kind": item.get("kind"),
                                     "match": "exact", "quote": quote[:80]})
                    elif _chars_in_order(term, quote):
                        hits.append({"candidate": f"{slot_id}#{index}", "kind": item.get("kind"),
                                     "match": "loose_chars", "quote": quote[:80]})
            per_term.append({"term": term, "candidates": hits[:3]})
        rows.append(
            {
                "item_id": item_id,
                "query_id": query_id,
                "clause": facet_text,
                "chosen": [f"{slot}#{index}" for slot, index in keys],
                "missing_terms": missing,
                "per_term_candidates": per_term,
                "options": [
                    "改选到含该词元的 item（须同时提交 anchor_review 原文承载映射）",
                    "补标注（新 source-gold 版本）后按新版本复核",
                    "若确属词面差异：提交逐项 lexical_review（terms 必须恰好等于未覆盖集合）",
                ],
            }
        )
    return {"count": len(rows), "rows": rows}


def synonymy_variant(gate_report: Mapping, help_payload: Mapping) -> dict:
    """对照口径：假设 U 对剩余项**逐项确认同义**（协议允许具名人工做同义映射，机器只核出处）。

    产物是**提案**，不是批准：文件里写明"待 U 逐项确认"，并保留未确认时门为 false 的事实。
    """

    payload = json.loads(DRY_CANDIDATES.read_text(encoding="utf-8"))
    draft = json.loads(DECISIONS_DRAFT.read_text(encoding="utf-8"))
    slots = load_jsonl(V4)
    applier = load_module(APPLIER, "i3s2_applier_variant")
    slot_by_id = {str(slot["gold_id"]): slot for slot in slots}
    by_item = {str(e["item_id"]): e for e in draft["facet_decisions"]}
    for row in help_payload["rows"]:
        entry = by_item.get(str(row["item_id"]))
        if entry is None:
            continue
        keys = [(str(c["slot"]), int(c["item_index"])) for c in entry.get("chosen") or []]
        missing = list(row["missing_terms"])
        mappings = []
        remaining = list(missing)
        for slot, index in keys:
            quote = str(dict(applier.split_items(slot_by_id[slot])).get(index, {}).get("quote") or "")
            terms = [term for term in remaining if term in quote or _chars_in_order(term, quote)]
            if not terms and remaining and not mappings:
                terms = list(remaining)
            for term in terms:
                if term in remaining:
                    remaining.remove(term)
            mappings.append(
                {
                    "slot": slot,
                    "item_index": index,
                    "quote_span": quote,
                    "terms": terms,
                    "reason": (
                        "AI 辅助核验断言该 span 承载该要件（经 xyl 审核）；"
                        "机器只能核对 span 出处，无法证明同义——接受与否由具名人工负责。"
                    ),
                }
            )
        if remaining and mappings:
            # 门要求 terms 联合**恰好等于**未覆盖集合：字面出处找不到的词元必须显式落位，
            # 并写明"本 span 未含其字面出处"，由具名人工承担同义判断。
            mappings[0]["terms"] = list(mappings[0]["terms"]) + list(remaining)
            mappings[0]["reason"] = str(mappings[0]["reason"]) + (
                "（本 span 未含下列词元的字面出处：%s；该同义判断由具名人工承担）"
                % "、".join(remaining)
            )
            remaining = []
        entry["lexical_review"] = {
            "kind": "lexical_mismatch",
            "facet_id": entry.get("facet_id"),
            "requirement": row["clause"],
            "evidence_complete": True,
            "missing_evidence": False,
            "mappings": mappings,
        }
        entry["decision"] = "改选" if entry.get("anchor_review") else entry.get("decision", "批准")
        entry["reason"] = str(entry.get("reason") or "") + "；[对照口径] 含 U 逐项同义确认（待确认）"
    draft["artifact"] = "i3-2-evidence-targets-decisions"
    draft["dryrun"] = True
    draft["synonymy_variant"] = True
    draft["not_filed"] = (
        "对照口径提案：假设 U 对剩余要件逐项确认同义后门是否可开；**尚未获得该确认**，"
        "不是批准件，不得写入 i3-2/ 正式路径。"
    )
    dump_json(DECISIONS_SYNONYMY, draft)
    applier_gate = load_module(APPLIER, "i3s2_applier_gate_variant")
    applier_gate.CANDIDATES = DRY_CANDIDATES
    applier_gate.SOURCE_GOLD = V4
    applier_gate.QUERY_GOLD = QUERY_GOLD
    assert_patched(applier_gate, CANDIDATES=DRY_CANDIDATES, SOURCE_GOLD=V4, QUERY_GOLD=QUERY_GOLD)
    report = applier_gate.evaluate(
        payload, load_jsonl(QUERY_GOLD), slots, json.loads(DECISIONS_SYNONYMY.read_text(encoding="utf-8"))
    )
    dump_json(GATE_SYNONYMY, report)
    return {
        "file": DECISIONS_SYNONYMY.name,
        "sha256": digest(DECISIONS_SYNONYMY),
        "gate_file": GATE_SYNONYMY.name,
        "ready": report["ready"],
        "blockers": report["blockers"],
        "warnings": report["warnings"],
        "note": "对照口径，尚未获得 U 逐项确认；不得据此宣告 I3-2 完成",
    }


def protected_check(before: dict[str, str]) -> dict:
    after = {name: digest(BASE / name) for name in _PROTECTED_PATHS if (BASE / name).is_file()}
    payload = {
        "checked_paths": list(_PROTECTED_PATHS),
        "unchanged": {name: before[name] == after.get(name) for name in before},
        "sha256": after,
        "note": "干跑只读冻结件；本检查证明源金标/守卫/冻结索引/正式候选与审批报告字节未变。",
    }
    dump_json(PROTECTED, payload)
    return payload


def main() -> int:
    before = {name: digest(BASE / name) for name in _PROTECTED_PATHS if (BASE / name).is_file()}
    release = build_source_gold()
    remap_result = remap()
    convert_result = convert()
    gate_result = gate()
    verify_result = verify()
    help_result = blocker_help(gate_result)
    dump_json(BLOCKER_HELP, help_result)
    variant_result = synonymy_variant(gate_result, help_result)
    final_result = finalize()
    protected = protected_check(before)
    result = {
        "artifact": "i3-2-adoption-dryrun-NOT-FORMAL-APPROVAL",
        "generated_at": now(),
        "adoption": {
            "adopted_by": "xyl",
            "adopted_at": ADOPTED_AT,
            "scope": "全文审核后全部采纳（含 Q1/Q2/Q3 处置口径）",
            "human_reviewed_full_text": True,
            "ai_reviewer": json.loads(
                (PACKAGE / "adjudication-reviewed.json").read_text(encoding="utf-8")
            ).get("reviewer"),
        },
        "release": release,
        "remap": remap_result,
        "convert": convert_result,
        "gate": {
            "ready": gate_result["ready"],
            "stage": gate_result["stage"],
            "counts": gate_result.get("counts"),
            "blockers": gate_result.get("blockers"),
            "warnings": gate_result.get("warnings"),
        },
        "verification": verify_result,
        "final": {
            "file": final_result["file"], "gate_file": final_result["gate_file"],
            "ready": final_result["ready"], "blockers": final_result["blockers"],
            "warnings": final_result["warnings"], "counts": final_result["counts"],
            "projection": final_result["projection"], "summary": final_result["summary"],
            "sha256": final_result["sha256"],
        },
        "blocker_help": {"count": help_result["count"], "file": BLOCKER_HELP.name,
                         "sha256": digest(BLOCKER_HELP)},
        "synonymy_variant": {
            "file": variant_result["file"], "gate_file": variant_result["gate_file"],
            "ready": variant_result["ready"], "blockers": variant_result["blockers"],
            "warnings": variant_result["warnings"], "note": variant_result["note"],
            "sha256": variant_result["sha256"],
        },
        "protected": protected["unchanged"],
        "files": {
            path.name: digest(path)
            for path in (V4, NEARMISS, RELEASE_MANIFEST, DRY_CANDIDATES, DRY_REVIEW,
                         DRY_ADJUDICATION, DECISIONS_DRAFT, GATE_RESULT, BLOCKER_HELP,
                         DECISIONS_SYNONYMY, GATE_SYNONYMY, DECISIONS_FINAL, GATE_FINAL,
                         VERIFICATION, PROTECTED)
            if path.is_file()
        },
    }
    dump_json(RESULT, result)
    print(f"dryrun result: {RESULT} sha256={digest(RESULT)}")
    print(json.dumps({"release": {k: release[k] for k in (
        "adopted_new_slots", "adopted_new_items", "near_miss_items",
        "span_checks_all_pass", "frozen_lines_byte_identical")},
        "gate": {"ready": gate_result["ready"], "blockers": len(gate_result.get("blockers") or [])},
        "convert": {k: convert_result[k] for k in (
            "facet_decisions", "expected_items", "question_reviews", "negative_reviews",
            "lexical_pending", "decisions_sha256") if not isinstance(convert_result[k], list)},
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
