"""I3-2 补料自检：用评分器对候选证据目标做**往返验证**（纯合成，不触真实链路）。

验证内容：

1. ``gold_from_records`` 能接受"冻结 query-gold + 候选 targets"合成的记录（形状合契约）；
2. 对 ``mapped``/``partial`` 题，用**由候选自身构造的合成观测**（quote/locator/source 均取自候选，
   ``verified=True``）跑 ``score``，应逐题三项全过 —— 证明候选自洽、来源归属与定位 token 可用；
3. 对 ``needs_human`` 题（人工尚未指定目标）：应报 ``evidence_targets_absent`` 并阻断整轮，
   即"缺料不放行"在评分器上真实生效；
4. 负例题按 ``evidence_required=false`` 登记，空命中观测不得产生误报或伪造引用。

**不读原文正文、不连 PG、不调模型、不写业务状态**；只用冻结金标与候选产物。

用法::

    env -u PYTHONPATH uv run python \
        .scratch/corpus-evidence-pipeline/ingestion-rebuild/i3s2_verify_candidates.py
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
QUERY_GOLD = BASE / "query-gold-frozen.jsonl"
CANDIDATES = BASE / "i3-2" / "evidence-targets-candidates.json"
OUT = BASE / "i3-2" / "evidence-targets-verification.json"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from plugins.corpus.scoring import (  # noqa: E402
    FetchedEvidence,
    ObservationOutcome,
    QueryObservation,
    RetrievedDocument,
    gold_from_records,
    score,
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fail(message: str) -> None:
    print(f"I3S2 VERIFY FAILED: {message}")
    sys.exit(1)


def load_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def build_records(gold: Sequence[Mapping[str, object]], candidates: Mapping[str, Mapping]) -> list[dict]:
    """把候选 target 并回 query-gold 记录，得到"金标 v2 候选"（不落盘，只用于往返验证）。"""

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
            for target in candidate["targets"]
        ]
        records.append(record)
    return records


def synthesize_observation(question: Mapping[str, object], candidate: Mapping) -> QueryObservation:
    """由候选自身合成观测：每题按来源聚合证据（同一来源只出现一次）。"""

    query_id = str(question["query_id"])
    if question.get("answer_existence") != "answerable":
        return QueryObservation(query_id=query_id, outcome=ObservationOutcome.NO_MATCH)

    by_source: dict[str, list[FetchedEvidence]] = {}
    for source in question.get("relevant_sources") or ():
        by_source.setdefault(str(source), [])
    for target in candidate["targets"]:
        by_source.setdefault(str(target["source_id"]), []).append(
            FetchedEvidence(
                text=str(target["quote"]),
                locator=tuple(str(token) for token in target["locator"]),
                verified=True,
            )
        )
    documents = tuple(
        RetrievedDocument(source_id=source, evidence=tuple(items))
        for source, items in by_source.items()
    )
    return QueryObservation(query_id=query_id, documents=documents)


def main() -> int:
    for path in (QUERY_GOLD, CANDIDATES):
        if not path.is_file():
            fail(f"缺少输入：{path}")
    if OUT.exists():
        fail("验证报告已存在（write-once，不覆盖）；如需重做请先归档")

    gold = load_jsonl(QUERY_GOLD)
    payload = json.loads(CANDIDATES.read_text(encoding="utf-8"))
    candidates = {str(item["query_id"]): item for item in payload["questions"]}
    if set(candidates) != {str(item["query_id"]) for item in gold}:
        fail("候选与冻结金标的 query_id 集合不一致")

    records = build_records(gold, candidates)
    questions = gold_from_records(records)  # 形状合契约；不合即抛 ScoringInputError
    observations = [synthesize_observation(question, candidates[str(question["query_id"])])
                    for question in gold]
    report = score(questions, observations)

    checks: list[dict[str, object]] = []
    for question in gold:
        query_id = str(question["query_id"])
        candidate = candidates[query_id]
        item = report.question(query_id)
        status = str(candidate["status"])
        if status in {"mapped", "partial"}:
            ok = (
                item.doc_recall == 1
                and item.question_pass is True
                and item.evidence_pass is True
            )
            expectation = "三项全过（候选自洽：来源归属/定位/逐字引文均可用）"
        elif status == "needs_human":
            ok = item.evidence_pass is False and any(
                "evidence_targets_absent" in failure for failure in item.failures
            )
            expectation = "evidence_targets_absent 阻断（缺料不放行）"
        else:  # negative_opt_out
            ok = (
                item.false_positive is False
                and item.fabricated_citations == 0
                and item.evidence_pass is None
            )
            expectation = "负例空命中：无按误报、无伪造引用、不进证据分母"
        checks.append(
            {
                "query_id": query_id,
                "status": status,
                "passed": bool(ok),
                "expectation": expectation,
                "doc_recall": str(item.doc_recall),
                "question_pass": item.question_pass,
                "evidence_pass": item.evidence_pass,
                "failures": list(item.failures),
            }
        )

    failed = [item for item in checks if not item["passed"]]
    result = {
        "artifact": "i3-2-evidence-targets-verification",
        "generated_at": datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
        "inputs": {
            "query_gold": {"sha256": digest(QUERY_GOLD)},
            "candidates": {"sha256": digest(CANDIDATES), "rule_rev": payload.get("rule_rev")},
        },
        "generator": {
            "path": ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i3s2_verify_candidates.py",
            "sha256": digest(Path(__file__)),
        },
        "checks": checks,
        "summary": {
            "questions": len(checks),
            "passed": len(checks) - len(failed),
            "failed": len(failed),
            "scored_passed": report.passed,
            "blockers": list(report.blockers),
        },
        "notes": [
            "合成观测由候选自身构造（quote/locator/source 取自候选，verified=True），"
            "只证明候选自洽与契约兼容，不代表真实链路可达。",
            "needs_human 题被证实在缺目标时按设计阻断（evidence_targets_absent），不得当作通过。",
            "本轮不读原文正文、不连 PG、不调模型；生产库零写入。",
        ],
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"verification written: {OUT} sha256={digest(OUT)}")
    print(json.dumps(result["summary"], ensure_ascii=False)[:600])
    for item in failed:
        print(
            f"  FAILED {item['query_id']} ({item['status']}): expect {item['expectation']} "
            f"got recall={item['doc_recall']} qp={item['question_pass']} ep={item['evidence_pass']} "
            f"failures={item['failures']}"
        )
    return 0 if not failed else 2


if __name__ == "__main__":
    raise SystemExit(main())
