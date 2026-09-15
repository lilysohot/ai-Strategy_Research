"""Replay captured development responses through the current material extractor."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from run_material_development import GOLD, OUT, ROOT, score_sample

from plugins.corpus.evidence import fingerprint
from plugins.corpus.evidence_pipeline import build_evidence_run
from plugins.corpus.material_semantics import extract_material_understanding


class RawResponseReplay:
    """Callable one-pass source for previously captured model responses."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = iter(responses)
        self.consumed = 0

    def __call__(self, _prompt: str) -> str:
        self.consumed += 1
        return next(self._responses)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-report", type=Path, required=True)
    parser.add_argument("--budget", type=Path, required=True)
    args = parser.parse_args()
    source_report_path = args.source_report.resolve()
    budget_path = args.budget.resolve()
    source_report = json.loads(source_report_path.read_text(encoding="utf-8"))
    budget = json.loads(budget_path.read_text(encoding="utf-8"))
    gold = json.loads(GOLD.read_text(encoding="utf-8"))
    if source_report.get("budget_version") != budget.get("budget_version"):
        raise ValueError("source report and budget differ")
    if source_report.get("split") != "development" or budget.get("split") != "development":
        raise ValueError("raw replay is development-only")
    if source_report.get("model_calls") != len(source_report.get("raw_audits", [])):
        raise ValueError("source report does not contain every raw response")

    audit_by_sample: dict[str, list[dict[str, str]]] = defaultdict(list)
    for audit in source_report["raw_audits"]:
        path = Path(audit["path"])
        raw = path.read_text(encoding="utf-8")
        if hashlib.sha256(raw.encode()).hexdigest() != audit["response_sha256"]:
            raise ValueError(f"raw response hash mismatch: {path}")
        audit_by_sample[audit["sample_id"]].append({"path": str(path), "raw": raw})

    sample_by_id = {sample["sample_id"]: sample for sample in gold["samples"]}
    results: list[dict[str, Any]] = []
    replay_runs: list[dict[str, Any]] = []
    for sample_id in budget["sample_ids"]:
        sample = sample_by_id[sample_id]
        evidence_run = build_evidence_run(
            ROOT / sample["source_path"],
            pages=tuple(sample.get("scoped_pages", ())) or None,
            packet_chars=budget["packet_chars"],
        )
        replay_llm = RawResponseReplay(
            [entry["raw"] for entry in audit_by_sample[sample_id]]
        )

        material_run = extract_material_understanding(
            evidence_run,
            llm=replay_llm,
            max_calls=budget["calls_per_document_per_round_max"],
            material_type=sample["material_type"],
            staged_jsonl=True,
            slot_protocol=True,
            max_items_per_packet=budget["max_items_per_packet"],
            max_slots_per_batch=budget["max_slots_per_batch"],
            extract_relations=False,
            candidate_slot_ids=tuple(budget["candidate_slot_ids_by_sample"][sample_id]),
        )
        expected = len(audit_by_sample[sample_id])
        if replay_llm.consumed != expected:
            raise ValueError(
                f"raw response count drifted for {sample_id}: "
                f"{replay_llm.consumed} != {expected}"
            )
        material_run.verify_identity()
        (OUT / f"{material_run.run_id}.json").write_text(
            material_run.model_dump_json(indent=2), encoding="utf-8"
        )
        results.append(score_sample(sample, material_run))
        replay_runs.append(
            {
                "sample_id": sample_id,
                "material_run_id": material_run.run_id,
                "raw_responses_reused": replay_llm.consumed,
            }
        )

    report = {
        "scorer_version": "material-raw-audit-replay-1",
        "split": "development",
        "model": source_report["model"],
        "model_calls": 0,
        "source_model_calls_reused": source_report["model_calls"],
        "source_report": str(source_report_path),
        "source_report_sha256": hashlib.sha256(source_report_path.read_bytes()).hexdigest(),
        "budget": str(budget_path),
        "budget_sha256": hashlib.sha256(budget_path.read_bytes()).hexdigest(),
        "replay_runs": replay_runs,
        "samples": results,
        "limitations": [
            "No model call is made; captured v12 responses are reused exactly once.",
            "This diagnostic replay does not amend the frozen v12 result.",
        ],
    }
    target = OUT / f"raw-replay-{fingerprint(report)}.json"
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(target), "runs": replay_runs}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
