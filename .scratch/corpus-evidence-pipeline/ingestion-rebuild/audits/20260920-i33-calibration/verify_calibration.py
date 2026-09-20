"""Replay aggregation and scoring from frozen fetch receipts, without PG or models."""
from dataclasses import asdict
from fractions import Fraction
import json
from pathlib import Path
from types import SimpleNamespace
import sys
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
BASE = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
import calibrate
from plugins.corpus.scoring import ScoringPolicy, gold_from_records, score

plan = json.loads((HERE / "calibration-plan-v2.json").read_text())
for rel, sha in plan["binding"].items():
    assert calibrate.digest(ROOT / rel) == sha, rel
gold_path = BASE / "i3-2/query-gold-scoring-v1.jsonl"
gold = gold_from_records([json.loads(line) for line in gold_path.read_text().splitlines()])
policy = dict(plan["policy"])
policy["min_rate"] = Fraction(policy["min_rate"])
policy = ScoringPolicy(**policy)
identities = json.loads((HERE / "source-identity-map.json").read_text())
receipts = json.loads((HERE / "fetch-receipts.json").read_text())


def fetch(hit):
    value = dict(receipts[hit.build_id + "/" + hit.chunk_id])
    value["units"] = [SimpleNamespace(**u) for u in value["units"]]
    return SimpleNamespace(**value)


for variant in plan["variants"]:
    traces = json.loads((HERE / (variant + "-trace.json")).read_text())
    assert [t["query_id"] for t in traces] == [q.query_id for q in gold]
    observations = []
    for trace, question in zip(traces, gold, strict=True):
        assert trace["input_question"] == question.question
        if variant == "baseline_literal_websearch":
            assert trace["executed_query"] == question.question
        grouped = {s: [SimpleNamespace(**h) for h in hits] for s, hits in trace["selected"].items()}
        assert len(grouped) <= policy.top_k
        assert all(len(h) <= plan["max_chunks_per_top_document"] for h in grouped.values())
        for source, hits in grouped.items():
            assert all(h.source_id == source and h.build_id == identities["active_builds"][source] for h in hits)
        observations.append(calibrate.observations_for(question.query_id, grouped, fetch, identities["aliases"]))
    actual_observations = json.loads(json.dumps([asdict(o) for o in observations], default=str))
    assert actual_observations == json.loads((HERE / (variant + "-observations.json")).read_text())
    actual_score = json.loads(json.dumps(asdict(score(gold, observations, policy)), default=str))
    assert actual_score == json.loads((HERE / (variant + "-score.json")).read_text())
print("Both 30-question observations and scores reproduced from frozen native fetch receipts; all bindings match.")
