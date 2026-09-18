"""I3-2 补料自检（``evidence-mapping-5`` 版）：**形状往返 + 独立反例 + 审批门反例**。

三段分开判定，互不替代：

A. ``self_consistency``：``gold_from_records`` 接受"冻结金标 + 候选目标"合成记录；对
   ``machine_ready``/``pending_human`` 题，用**模拟批准**（``required`` + ``suggested``）造观测
   跑 ``score``，逐题三项应全过；``blocked`` 题不参与该判定，只登记。
   合成观测由候选自身构造，**只证明自洽，不代表真实链路可达**，也不是补料完整性。
B. ``regression_probes``：
   - 证据判定类（P1—P9）：结构身份、脚注、条件、补充证据、型号边界、fail-closed 入口、数值等价；
   - **审批门类（P10—P16）**：状态翻转不能开门、空审阅人不能开门、要件缺项不能开门、
     部分覆盖锚点不得直接批准、负例未确认不能开门、审批件过期不能开门、
     完整审批件可以开门（含批准投影）。
C. ``completeness_gate``：调用 ``i3s2_apply_decisions.py`` 的 ``evaluate``；当前没有审批件时
   为 ``stage=no_decisions``。候选阶段它必须是 **false**，且**不能**由自洽往返代替。

**不读原文正文、不连 PG、不调模型、不写业务状态**；只用冻结金标、候选产物与（若存在的）审批件。

用法::

    env -u PYTHONPATH uv run python \
        .scratch/corpus-evidence-pipeline/ingestion-rebuild/i3s2_verify_candidates.py
"""

from __future__ import annotations

import hashlib
import json
import runpy
import sys
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[2]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

QUERY_GOLD = BASE / "query-gold-frozen.jsonl"
SOURCE_GOLD = BASE / "source-gold-frozen.jsonl"
CANDIDATES = BASE / "i3-2" / "evidence-targets-candidates.json"
DECISIONS = BASE / "i3-2" / "evidence-targets-decisions.json"
OUT = BASE / "i3-2" / "evidence-targets-verification.json"

from plugins.corpus.scoring import (  # noqa: E402
    FetchedEvidence,
    ObservationOutcome,
    QueryObservation,
    RetrievedDocument,
    ScoringInputError,
    gold_from_records,
    score,
)

_APPLIER = runpy.run_path(str(BASE / "i3s2_apply_decisions.py"))
_SIMULATED_APPROVAL_ROLES = ("required", "suggested")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fail(message: str) -> None:
    print(f"I3S2 VERIFY FAILED: {message}")
    sys.exit(1)


def load_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def simulated_approval(candidate: Mapping) -> list[dict]:
    """机器当前最佳集合 = 必需 + 待批准锚点（模拟"人工全部批准"，只用于自洽与探针）。"""

    return [
        target for target in candidate["targets"] if target["role"] in _SIMULATED_APPROVAL_ROLES
    ]


def build_records(
    gold: Sequence[Mapping[str, object]], candidates: Mapping[str, Mapping]
) -> list[dict]:
    records: list[dict] = []
    for question in gold:
        query_id = str(question["query_id"])
        candidate = candidates[query_id]
        record = dict(question)
        record["evidence_required"] = bool(candidate["evidence_required"])
        record["evidence_targets"] = [
            {
                "target_id": target["target_id"],
                "quote": target["quote"],
                "locator": list(target["locator"]),
                "source_id": target["source_id"],
            }
            for target in simulated_approval(candidate)
        ]
        records.append(record)
    return records


def evidence_of(targets: Sequence[Mapping]) -> dict[str, list[FetchedEvidence]]:
    by_source: dict[str, list[FetchedEvidence]] = {}
    for target in targets:
        by_source.setdefault(str(target["source_id"]), []).append(
            FetchedEvidence(
                text=str(target["quote"]),
                locator=tuple(str(token) for token in target["locator"]),
                verified=True,
            )
        )
    return by_source


def observation_for(question: Mapping[str, object], targets: Sequence[Mapping]) -> QueryObservation:
    query_id = str(question["query_id"])
    if question.get("answer_existence") != "answerable":
        return QueryObservation(query_id=query_id, outcome=ObservationOutcome.NO_MATCH)
    by_source = {str(source): [] for source in question.get("relevant_sources") or ()}
    for source, items in evidence_of(targets).items():
        by_source.setdefault(source, [])
        by_source[source] = list(items)
    documents = tuple(
        RetrievedDocument(source_id=source, evidence=tuple(items))
        for source, items in by_source.items()
    )
    return QueryObservation(query_id=query_id, documents=documents)


def run_self_consistency(
    gold: Sequence[Mapping[str, object]], candidates: Mapping[str, Mapping]
) -> tuple[list[dict], int]:
    records = build_records(gold, candidates)
    questions = {item.query_id: item for item in gold_from_records(records)}
    checks: list[dict[str, object]] = []
    for question in gold:
        query_id = str(question["query_id"])
        candidate = candidates[query_id]
        status = str(candidate["machine_status"])
        observation = observation_for(question, simulated_approval(candidate))
        item = score((questions[query_id],), (observation,)).questions[0]
        if status in {"machine_ready", "pending_human"}:
            ok = (
                item.doc_recall == 1
                and item.question_pass is True
                and item.evidence_pass is True
            )
            expectation = "三项全过（模拟批准后候选自洽：来源归属/定位/逐字引文可用）"
        elif status == "blocked":
            ok = True  # 缺标注由完整性门拦截，不在这里伪装成败
            expectation = "blocked：缺承载 item 的要件由完整性门拦截，不参与自洽判定"
        else:
            ok = (
                item.false_positive is False
                and item.fabricated_citations == 0
                and item.evidence_pass is None
            )
            expectation = "负例空命中：无误报、无伪造引用、不进证据分母"
        checks.append(
            {
                "query_id": query_id,
                "machine_status": status,
                "passed": bool(ok),
                "expectation": expectation,
                "doc_recall": str(item.doc_recall),
                "question_pass": item.question_pass,
                "evidence_pass": item.evidence_pass,
                "failures": list(item.failures),
            }
        )
    failed = sum(1 for item in checks if not item["passed"])
    return checks, failed


def _probe_context(
    gold: Sequence[Mapping[str, object]], candidates: Mapping[str, Mapping], query_id: str
) -> tuple[Mapping[str, object], object, list[dict]]:
    records = build_records(gold, candidates)
    question = next(item for item in gold_from_records(records) if item.query_id == query_id)
    source = next(item for item in gold if str(item["query_id"]) == query_id)
    return source, question, simulated_approval(candidates[query_id])


def _observation(
    source: Mapping[str, object],
    evidence: Sequence[tuple[str, str, tuple[str, ...], bool | None]],
) -> QueryObservation:
    by_source: dict[str, list[FetchedEvidence]] = {
        str(item): [] for item in source.get("relevant_sources") or ()
    }
    for source_id, text, locator, verified in evidence:
        by_source.setdefault(source_id, []).append(
            FetchedEvidence(text=text, locator=locator, verified=verified)
        )
    return QueryObservation(
        query_id=str(source["query_id"]),
        documents=tuple(
            RetrievedDocument(source_id=source_id, evidence=tuple(items))
            for source_id, items in by_source.items()
        ),
    )


def _synthetic_payload() -> tuple[dict, list[dict], list[dict]]:
    """最小合成夹具：1 道有答案题 + 1 道负例，用于证明审批门**可以**打开。"""

    payload = {
        "artifact": "i3-2-evidence-targets-candidates",
        "rule_rev": "probe-synthetic",
        "human_status_conflicts": [],
        "questions": [
            {
                "query_id": "probe-q1",
                "domain": "probe",
                "answer_existence": "answerable",
                "satisfy_rule": "any",
                "relevant_sources": ["probe-source"],
                "evidence_required": True,
                "machine_status": "pending_human",
                "adjudication": {"status": "pending", "reviewer": None, "reviewed_at": None},
                "candidate_slots": ["probe-slot"],
                "requirement_clauses": [
                    {
                        "clause_id": "c1",
                        "text": "门槛为0.5%",
                        "period_tokens": [],
                        "value_facet_ids": ["f1"],
                        "qualification_facet_ids": ["q2"],
                    }
                ],
                "requirement_facets": [
                    {"facet_id": "f1", "clause_id": "c1", "kind": "value", "token": "0.5%",
                     "coverage": "required", "candidates": []},
                    {"facet_id": "q2", "clause_id": "c1", "kind": "qualification",
                     "text": "门槛口径", "coverage": "suggested", "suggestions": []},
                ],
                "answer_constraints": [],
                "targets": [
                    {"target_id": "e1", "role": "required", "quote": "0.5%",
                     "locator": ["page:1"], "source_id": "probe-source",
                     "constraints": {}, "basis": {"gold_id": "probe-slot", "item_index": 0}},
                ],
                "pending_human": [
                    {"item_id": "I32-probe-q1-01", "kind": "qualification", "facet_id": "q2",
                     "clause_id": "c1", "question": "确认门槛口径",
                     "clause": "门槛口径", "coverage": "suggested",
                     "suggestions": [
                         {"slot": "probe-slot", "source_id": "probe-source", "item_index": 0,
                          "kind": "condition", "locator": ["page:1"], "quote": "口径为年度累计",
                          "why": "probe", "role": "primary", "adequacy": "full",
                          "uncovered_terms": []}
                     ]},
                ],
            },
            {
                "query_id": "probe-q2",
                "domain": "probe",
                "answer_existence": "no_answer",
                "satisfy_rule": None,
                "relevant_sources": [],
                "evidence_required": False,
                "machine_status": "negative_opt_out",
                "adjudication": {"status": "pending", "reviewer": None, "reviewed_at": None},
                "candidate_slots": [],
                "requirement_clauses": [],
                "requirement_facets": [],
                "answer_constraints": [],
                "targets": [],
                "pending_human": [],
            },
        ],
    }
    gold = [
        {"query_id": "probe-q1", "domain": "probe", "answer_existence": "answerable",
         "satisfy_rule": "any", "evidence_requirement": "门槛为0.5%"},
        {"query_id": "probe-q2", "domain": "probe", "answer_existence": "no_answer",
         "satisfy_rule": None},
    ]
    slots = [
        {"gold_id": "probe-slot", "source_id": "probe-source", "locator": {"page": "1"},
         "expected_items": [
             {"kind": "value", "quote": "0.5%", "text": "门槛为0.5%"},
             {"kind": "condition", "quote": "口径为年度累计", "text": "门槛口径为年度累计"},
         ]},
    ]
    return payload, gold, slots


def _synthetic_decisions(payload: Mapping) -> dict:
    return {
        "artifact": "i3-2-evidence-targets-decisions",
        "rule_rev": payload["rule_rev"],
        "reviewer": "SYNTHETIC-PROBE（仅用于验证门可开，不是真实批准）",
        "reviewed_at": "2026-01-01T00:00:00+08:00",
        # 门的过期检查永远对着真实冻结件：合成审批件也要带真实哈希，否则一律判过期
        "based_on": {
            "candidates_sha256": digest(CANDIDATES),
            "query_gold_sha256": digest(QUERY_GOLD),
            "source_gold_sha256": digest(SOURCE_GOLD),
        },
        "facet_decisions": [
            {"item_id": "I32-probe-q1-01", "facet_id": "q2", "query_id": "probe-q1",
             "decision": "批准", "chosen": [{"slot": "probe-slot", "item_index": 1}],
             "residual_accepted": False, "residual_reason": "", "reason": "probe"}
        ],
        "question_reviews": [
            {"query_id": "probe-q1", "decision": "批准", "reviewed_against_requirement": True,
             "reason": "probe"}
        ],
        "negative_reviews": [
            {"query_id": "probe-q2", "decision": "批准", "full_text_coverage_confirmed": True,
             "reason": "probe"}
        ],
        "human_status_clarifications": [],
    }


def _gate(
    payload: Mapping,
    gold: Sequence[Mapping],
    slots: Sequence[Mapping],
    decisions: Mapping | None,
) -> dict:
    return _APPLIER["evaluate"](payload, gold, slots, decisions)


def run_probes(
    gold: Sequence[Mapping[str, object]], candidates: Mapping[str, Mapping]
) -> tuple[list[dict], int]:
    checks: list[dict[str, object]] = []

    def _record(probe_id: str, description: str, passed: bool, detail: dict) -> None:
        checks.append(
            {"probe_id": probe_id, "description": description, "passed": bool(passed),
             "detail": detail}
        )

    # ── 证据判定类 ────────────────────────────────────────────────────────
    source, question, targets = _probe_context(gold, candidates, "industry-001")
    obs = _observation(
        source,
        [
            (str(target["source_id"]), str(target["quote"]), ("page:10",), True)
            for target in targets
        ],
    )
    item = score((question,), (obs,)).questions[0]
    _record(
        "P1-table-identity-required",
        "适配器只给 page 不给 row/col 时，表格目标必须失败（结构身份是契约的一部分）",
        item.evidence_pass is False,
        {"evidence_pass": item.evidence_pass, "failures": list(item.failures)},
    )

    obs = _observation(
        source,
        [
            (str(targets[1]["source_id"]), str(targets[1]["quote"]),
             tuple(str(token) for token in targets[1]["locator"]), True),
            (str(targets[2]["source_id"]), str(targets[2]["quote"]),
             tuple(str(token) for token in targets[2]["locator"]), True),
        ],
    )
    item = score((question,), (obs,)).questions[0]
    _record(
        "P2-same-value-different-cell",
        "两个 0.0% 分属价格分位/价差分位：只给价差分位不得顶替价格分位",
        item.evidence_pass is False,
        {"evidence_pass": item.evidence_pass, "failures": list(item.failures)},
    )

    source, question, targets = _probe_context(gold, candidates, "industry-004")
    note1 = next(target for target in targets if "注1" in str(target["quote"]))
    obs = _observation(
        source,
        [(str(note1["source_id"]), str(note1["quote"]),
          tuple(str(token) for token in note1["locator"]), True)],
    )
    item = score((question,), (obs,)).questions[0]
    _record(
        "P3-missing-footnote-fails",
        "industry-004 只给注1、缺注2 时必须失败",
        item.evidence_pass is False,
        {"evidence_pass": item.evidence_pass, "failures": list(item.failures)},
    )

    notes = [target for target in targets if "注" in str(target["quote"])]
    obs = _observation(
        source,
        [(str(target["source_id"]), str(target["quote"]),
          tuple(str(token) for token in target["locator"]), True) for target in notes],
    )
    item = score((question,), (obs,)).questions[0]
    _record(
        "P4-minimal-correct-evidence-passes",
        "industry-004 的两条脚注是完整最小证据，不得再要求无关产品数值",
        item.evidence_pass is True and len(notes) == 2,
        {"evidence_pass": item.evidence_pass, "notes": len(notes), "failures": list(item.failures)},
    )

    source, question, targets = _probe_context(gold, candidates, "company-005")
    required = [target for target in targets if target["role"] == "required"]
    obs = _observation(
        source,
        [(str(target["source_id"]), str(target["quote"]),
          tuple(str(token) for token in target["locator"]), True) for target in required],
    )
    item = score((question,), (obs,)).questions[0]
    supplementary = [
        str(target["basis"]["gold_id"])
        for target in candidates["company-005"]["targets"]
        if target["role"] == "supplementary"
    ]
    _record(
        "P5-supplementary-not-required",
        "company-005 的第2页型号清单属补充证据（非必需），缺失不得判失败",
        item.evidence_pass is True and supplementary == ["company-024-claim-001"],
        {"evidence_pass": item.evidence_pass, "supplementary": supplementary,
         "failures": list(item.failures)},
    )

    source, question, targets = _probe_context(gold, candidates, "macro-003")
    main = next(target for target in targets if target["role"] == "required")
    obs = _observation(
        source,
        [(str(main["source_id"]), str(main["quote"]),
          tuple(str(token) for token in main["locator"]), True)],
    )
    item = score((question,), (obs,)).questions[0]
    _record(
        "P6-missing-condition-fails",
        "macro-003 缺『通胀下行有限』条件句时必须失败（条件是要件，不是可忽略部分）",
        item.evidence_pass is False,
        {"evidence_pass": item.evidence_pass, "failures": list(item.failures)},
    )

    fake = [
        target
        for target in candidates["company-005"]["targets"]
        if target["basis"]["gold_id"] == "company-060-claim-001"
    ]
    _record(
        "P7-model-suffix-boundary",
        "8230CF 不得作为 8230 的命中（型号后缀不是同一型号）",
        not fake,
        {"company-060_targets": [target["target_id"] for target in fake]},
    )

    source, question, _targets = _probe_context(gold, candidates, "industry-001")
    duplicated = QueryObservation(
        query_id=str(source["query_id"]),
        documents=(
            RetrievedDocument(source_id="2026-08-13_174b6462"),
            RetrievedDocument(source_id="2026-08-13_174b6462"),
        ),
    )
    try:
        score((question,), (duplicated,))
        rejected = False
        reason = ""
    except ScoringInputError as exc:
        rejected = True
        reason = str(exc)
    _record(
        "P8-duplicate-source-rejected",
        "同一来源在 Top-k 出现两次必须被入口拒绝（不得靠重复条目顶替漏召回）",
        rejected,
        {"reason": reason},
    )

    candidate = candidates["company-004"]
    queued = [item for item in candidate["pending_human"] if item["kind"] == "value_equivalence"]
    target = next(
        target
        for target in candidate["targets"]
        if "13.4" in str(target["quote"])
    )
    _record(
        "P9-value-equivalence-declared",
        "13.40 与原文 13.4 的等价必须显式入队，且 quote 保持原文逐字（不改写成 13.40）",
        bool(queued) and "13.40" not in str(target["quote"]),
        {"queued": [item["item_id"] for item in queued],
         "quote_unchanged": "13.40" not in str(target["quote"])},
    )

    # ── 审批门类（复核 A1/A2） ─────────────────────────────────────────────
    payload, probe_gold, probe_slots = _synthetic_payload()
    decisions = _synthetic_decisions(payload)

    flipped = json.loads(json.dumps(payload))
    for question in flipped["questions"]:
        question["adjudication"]["status"] = "approved"
    gate_flipped = _gate(flipped, probe_gold, probe_slots, None)
    _record(
        "P10-status-flip-cannot-open-gate",
        "把候选 adjudication.status 全部改成 approved（无审批件）不得开门",
        gate_flipped["ready"] is False and gate_flipped["stage"] == "no_decisions",
        {"ready": gate_flipped["ready"], "stage": gate_flipped["stage"]},
    )

    empty_reviewer = dict(decisions, reviewer="")
    gate_reviewer = _gate(payload, probe_gold, probe_slots, empty_reviewer)
    _record(
        "P11-empty-reviewer-blocked",
        "审批件缺 reviewer / reviewed_at 不得开门",
        gate_reviewer["ready"] is False
        and any("reviewer" in blocker for blocker in gate_reviewer["blockers"]),
        {"blockers": gate_reviewer["blockers"]},
    )

    partial_decisions = dict(decisions, facet_decisions=[])
    gate_partial = _gate(payload, probe_gold, probe_slots, partial_decisions)
    _record(
        "P12-missing-facet-decisions-blocked",
        "要件裁决缺项（未逐个 item_id 裁决）不得开门，且列出未决项",
        gate_partial["ready"] is False and "I32-probe-q1-01" in gate_partial["unresolved_items"],
        {"unresolved": gate_partial["unresolved_items"]},
    )

    residual_decisions = dict(decisions, human_status_clarifications=[])
    no_negative = dict(decisions, negative_reviews=[])
    gate_negative = _gate(payload, probe_gold, probe_slots, no_negative)
    _record(
        "P13-negative-coverage-required",
        "负例未做全文覆盖确认不得开门",
        gate_negative["ready"] is False
        and any("负例" in blocker for blocker in gate_negative["blockers"]),
        {"blockers": gate_negative["blockers"]},
    )

    stale = dict(decisions, based_on={"candidates_sha256": "stale"})
    gate_stale = _gate(payload, probe_gold, probe_slots, stale)
    _record(
        "P14-stale-approval-blocked",
        "审批件绑定的输入哈希过期不得开门",
        gate_stale["ready"] is False
        and any("过期" in blocker for blocker in gate_stale["blockers"]),
        {"blockers": gate_stale["blockers"]},
    )

    if "I32-macro-004-03" in {
        str(entry["item_id"])
        for entry in candidates["macro-004"]["pending_human"]
    }:
        entry = next(
            item for item in candidates["macro-004"]["pending_human"]
            if item["item_id"] == "I32-macro-004-03"
        )
        primary = [item for item in entry["suggestions"] if item.get("role") == "primary"]
        partial = [item for item in primary if item.get("adequacy") == "partial"]
        _record(
            "P15-partial-anchor-flagged",
            "四路径这类锚点必须标为部分覆盖并列出未覆盖词元（不得当成完整证据）",
            bool(partial) and bool(partial[0].get("uncovered_terms")),
            {"partial_primary": [
                {"slot": item["slot"], "item_index": item["item_index"],
                 "uncovered_terms": item.get("uncovered_terms")}
                for item in partial
            ]},
        )
    else:
        _record("P15-partial-anchor-flagged", "macro-004-03 不存在，无法检验", False, {})

    gate_ready = _gate(payload, probe_gold, probe_slots, decisions)
    projection = _APPLIER["project"](payload, probe_gold, probe_slots, decisions)
    _record(
        "P16-complete-approval-opens-gate",
        "完整审批件（含整题验收/负例确认/来源澄清）应当开门并产出批准投影",
        gate_ready["ready"] is True
        and len(projection["questions"][0]["approved_required"]) == 2,
        {"ready": gate_ready["ready"], "blockers": gate_ready["blockers"],
         "approved_required": len(projection["questions"][0]["approved_required"])},
    )
    del residual_decisions

    failed = sum(1 for item in checks if not item["passed"])
    return checks, failed


def run_completeness_gate(
    gold: Sequence[Mapping[str, object]],
    candidates: Mapping[str, Mapping],
    slots: Sequence[Mapping[str, object]] = (),
    decisions: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """完整性门：委托 ``i3s2_apply_decisions.evaluate``（只看审批件，不看候选状态字段）。"""

    payload = {
        "rule_rev": None,  # 真实调用走下面 main() 的完整 payload；此处兜底以免误判为通过
        "questions": list(candidates.values()),
        "human_status_conflicts": [],
    }
    return _APPLIER["evaluate"](payload, gold, slots, decisions)


def archive_current() -> list[str]:
    archived: list[str] = []
    if OUT.is_file():
        index = 1
        while (OUT.parent / f"evidence-targets-verification-v{index}.json").exists():
            index += 1
        target = OUT.parent / f"evidence-targets-verification-v{index}.json"
        OUT.rename(target)
        archived.append(target.name)
    return archived


def main() -> int:
    for path in (QUERY_GOLD, SOURCE_GOLD, CANDIDATES):
        if not path.is_file():
            fail(f"缺少输入：{path}")

    gold = load_jsonl(QUERY_GOLD)
    slots = load_jsonl(SOURCE_GOLD)
    payload = json.loads(CANDIDATES.read_text(encoding="utf-8"))
    candidates = {str(item["query_id"]): item for item in payload["questions"]}
    if set(candidates) != {str(item["query_id"]) for item in gold}:
        fail("候选与冻结金标的 query_id 集合不一致")

    decisions = json.loads(DECISIONS.read_text(encoding="utf-8")) if DECISIONS.is_file() else None

    archived = archive_current()
    if archived:
        print(f"archived previous verification: {', '.join(archived)}")

    self_checks, self_failed = run_self_consistency(gold, candidates)
    probes, probe_failed = run_probes(gold, candidates)
    gate = _APPLIER["evaluate"](payload, gold, slots, decisions)

    result = {
        "artifact": "i3-2-evidence-targets-verification",
        "generated_at": datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
        "inputs": {
            "query_gold": {"sha256": digest(QUERY_GOLD)},
            "source_gold": {"sha256": digest(SOURCE_GOLD)},
            "candidates": {
                "sha256": digest(CANDIDATES),
                "rule_rev": payload.get("rule_rev"),
                "summary": payload.get("summary"),
            },
            "decisions": {
                "present": decisions is not None,
                "sha256": digest(DECISIONS) if DECISIONS.is_file() else None,
            },
        },
        "generator": {
            "path": ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i3s2_verify_candidates.py",
            "sha256": digest(Path(__file__)),
        },
        "self_consistency": {
            "checks": self_checks,
            "failed": self_failed,
            "note": (
                "模拟批准（required + suggested）后逐题自洽；合成观测由候选自身构造，"
                "只证明契约兼容与来源/定位可用，**不代表真实链路可达**，也不是补料完整性。"
            ),
        },
        "regression_probes": {
            "checks": probes,
            "failed": probe_failed,
            "note": (
                "证据判定类：结构身份/脚注/条件/补充证据/型号边界/fail-closed/数值等价；"
                "审批门类：状态翻转、空审阅人、要件缺项、负例未确认、审批过期均不得开门，"
                "完整审批件应能开门并产出批准投影（合成夹具，非真实批准）。"
            ),
        },
        "completeness_gate": gate,
        "summary": {
            "questions": len(self_checks),
            "self_consistency_failed": self_failed,
            "probes_total": len(probes),
            "probes_failed": probe_failed,
            "completeness_ready": gate["ready"],
            "completeness_stage": gate["stage"],
        },
        "notes": [
            "本轮不读原文正文、不连 PG、不调模型；生产库零写入。",
            "completeness_gate 由 i3s2_apply_decisions.evaluate 计算，只看审批件；"
            "候选阶段的 no_decisions/ready=false 是正确状态，不得用 self_consistency 代替人工裁决。",
        ],
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"verification written: {OUT} sha256={digest(OUT)}")
    print(json.dumps(result["summary"], ensure_ascii=False))
    for item in self_checks:
        if not item["passed"]:
            print(f"  SELF FAILED {item['query_id']} ({item['machine_status']}): {item['failures']}")
    for item in probes:
        if not item["passed"]:
            print(f"  PROBE FAILED {item['probe_id']}: {item['description']} {item['detail']}")
    return 0 if not (self_failed or probe_failed) else 2


if __name__ == "__main__":
    raise SystemExit(main())
