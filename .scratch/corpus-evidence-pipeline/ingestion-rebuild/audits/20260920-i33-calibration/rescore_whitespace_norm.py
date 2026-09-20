"""Read-only re-scoring of the frozen r39 OR-candidate observations under the
whitespace-normalized quote-containment scorer (Step 2). Does NOT re-retrieve,
does NOT supplement evidence, does NOT touch PG. Reports EvidencePass before/after
per class and lists which targets flipped (now matched) vs not yet reachable.
"""
import json
from fractions import Fraction
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
BASE = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))

import calibrate
loader = calibrate.load_module("i33_scoring_loader", BASE / "i3s2_scoring_input.py")
applier = loader.load_module(BASE / "i3s2_apply_decisions.py", "i33_approved_input")
records = loader.load_scoring_input(BASE / "i3-2/scoring-input-manifest.json")
# Intentional Step-2 scorer change: acknowledge only the scorer lineage in-memory
# (disk artifact untouched); all other gold/projection/decisions/payload checks stay live.
import hashlib
manifest = json.loads(loader.MANIFEST.read_text())
manifest.setdefault("lineage", {}).setdefault("scorer", {})["sha256"] = hashlib.sha256(
    Path(loader.SCORER).read_bytes()).hexdigest()
errors = loader.validate(records, loader.load_jsonl(loader.QUERY_GOLD),
    json.loads(loader.PROJECTION.read_text()), loader.load_jsonl(loader.SOURCE_GOLD),
    manifest, applier)
if errors:
    raise RuntimeError(f"frozen scoring assets invalid: {errors}")

from plugins.corpus.scoring import (
    FetchedEvidence, RetrievedDocument, QueryObservation, ObservationOutcome,
    gold_from_records, ScoringPolicy, score, format_report,
)
questions = gold_from_records(records)
plan = json.loads((HERE / "calibration-plan-v2.json").read_text())
config = dict(plan["policy"]); config["min_rate"] = Fraction(config["min_rate"])
policy = ScoringPolicy(**config)

obspath = HERE / "candidate_question_lexemes_or-observations.json"
obs = json.loads(obspath.read_text())
by_qid = {o["query_id"]: o for o in obs}
observations = []
for q in questions:
    o = by_qid.get(q.query_id)
    if o is None:
        observations.append(QueryObservation(q.query_id, ObservationOutcome.FAILED))
        continue
    docs = tuple(
        RetrievedDocument(
            source_id=d.get("source_id"),
            evidence=tuple(FetchedEvidence(text=e.get("text"), locator=tuple(e.get("locator") or ()),
                                           verified=e.get("verified")) for e in d.get("evidence") or ()),
            build_id=d.get("build_id"),
        ) for d in o.get("documents") or ())
    observations.append(QueryObservation(q.query_id, ObservationOutcome.OK if docs else ObservationOutcome.NO_MATCH, docs))

report = score(questions, observations, policy)
before = json.loads((HERE / "candidate_question_lexemes_or-score.json").read_text())
def per_class_dict(r):
    return {c.get("domain"): (c["evidence_pass"].get("passed"), c["evidence_pass"].get("total")) for c in r.get("classes")}
def per_class(r):
    return {c.domain: (c.evidence_pass.passed, c.evidence_pass.total) for c in r.classes}
print("== before (byte-exact) ==", per_class_dict(before))
print("== after (whitespace-norm) ==", per_class(report))

# which targets flipped to matched
for q in report.questions:
    b = next(x for x in before["questions"] if x["query_id"] == q.query_id)
    newf = set(q.failures); oldf = set(b["failures"])
    flipped = [f for f in (newf - oldf) if f.startswith("evidence_target_missing:")] or []
    gained = (newf ^ oldf)
    for g in sorted(gained):
        code = g.split(":", 1)[0]
        if code == "evidence_target_missing":
            tgt = g.split(":", 1)[1]
            before_gone = f"{code}:{tgt}" in oldf
            after_gone = f"{code}:{tgt}" in newf
            if before_gone and not after_gone:
                print(f"GAIN  {q.query_id}/{tgt}  now matched")
            elif not before_gone and after_gone:
                print(f"LOSS  {q.query_id}/{tgt}  now missing")

print("== report.md ==")
print(format_report(report))