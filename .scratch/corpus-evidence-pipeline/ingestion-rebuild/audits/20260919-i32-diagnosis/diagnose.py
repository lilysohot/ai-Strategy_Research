"""Read-only I3-2 probes. Synthetic observations are NOT business results.

Run from repository root with the existing venv:
  .venv/bin/python -B .scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i32-diagnosis/diagnose.py
Add --require-current-ready to return exit 1 while the formal gold is incomplete.
"""

import hashlib
import importlib.util
import json
import sys
from dataclasses import replace
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
ROOT = BASE.parents[2]
sys.path.insert(0, str(ROOT))

from plugins.corpus.preparation import guard

guard.install(BASE / "guards/i3.json")

from plugins.corpus import scoring as s


def records(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


formal_path = BASE / "query-gold-frozen.jsonl"
draft_path = BASE / "audits/20260918-i32-remaining-inventory/p1/query-gold-with-targets.jsonl"
formal_records = records(formal_path)
draft_records = records(draft_path)
draft = s.gold_from_records(draft_records)
observations = []
for question in draft:
    if question.answer_existence == s.AnswerExistence.NO_ANSWER:
        observation = s.QueryObservation(question.query_id, s.ObservationOutcome.NO_MATCH)
    else:
        documents = tuple(
            s.RetrievedDocument(
                source_id=source,
                evidence=tuple(
                    s.FetchedEvidence(target.quote, target.locator, True)
                    for target in question.evidence_targets
                    if target.source_id == source
                ),
                build_id="SYNTHETIC_INPUT_CONTRACT_ONLY",
            )
            for source in question.relevant_sources
        )
        observation = s.QueryObservation(question.query_id, documents=documents)
    observations.append(observation)

reports = {
    "formal": s.score(s.gold_from_records(formal_records), observations),
    "draft": s.score(draft, observations),
}
output = {"scope": "synthetic input/approval contracts only; no E2E, model, or PG"}
output["scoring"] = {
    label: {
        "passed": report.passed,
        "missing_targets": sum("evidence_targets_absent" in item for item in report.blockers),
        "blocker_count": len(report.blockers),
    }
    for label, report in reports.items()
}
output["counts"] = {
    "questions": len(draft),
    "required_targets": sum(len(q.evidence_targets) for q in draft),
    "supplementary_targets": sum(len(q.get("supplementary_evidence_targets", [])) for q in draft_records),
    "critical": sum(q.critical for q in draft),
    "negative": sum(q.answer_existence == s.AnswerExistence.NO_ANSWER for q in draft),
}
output["original_fields_unchanged"] = all(
    {key: value for key, value in new.items() if key not in (
        "evidence_targets", "supplementary_evidence_targets"
    )} == old
    for old, new in zip(formal_records, draft_records, strict=True)
)

spec = importlib.util.spec_from_file_location("i32_diagnosis_applier", BASE / "i3s2_apply_decisions.py")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
payload = json.loads(module.CANDIDATES.read_text())
slots = records(module.SOURCE_GOLD)
decisions = json.loads(module.DECISIONS.read_text())
current = module.evaluate(payload, formal_records, slots, decisions)
# Change only an in-memory module constant; do not overwrite the formal artifact.
module.QUERY_GOLD = draft_path
replacement = module.evaluate(payload, draft_records, slots, decisions)
output["approval"] = {
    "current_ready": current["ready"],
    "current_blockers": current["blockers"],
    "current_warning_count": len(current["warnings"]),
    "naive_replacement_ready": replacement["ready"],
    "naive_replacement_blockers": replacement["blockers"],
}

noncritical_failure = [
    replace(observation, documents=tuple(
        replace(document, evidence=()) for document in observation.documents
    )) if observation.query_id == "macro-004" else observation
    for observation in observations
]
threshold = s.score(draft, noncritical_failure)
output["noncritical_macro004_evidence_failure"] = {
    "passed": threshold.passed,
    "blockers": threshold.blockers,
}
output["inputs_sha256"] = {
    str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
    for path in (formal_path, draft_path, BASE / "i3-2/evidence-targets-decisions.json",
                 BASE / "i3-2/evidence-targets-approved.json", ROOT / "plugins/corpus/scoring.py")
}
print(json.dumps(output, ensure_ascii=False, indent=2))
if "--require-current-ready" in sys.argv:
    raise SystemExit(0 if reports["formal"].passed and current["ready"] else 1)
