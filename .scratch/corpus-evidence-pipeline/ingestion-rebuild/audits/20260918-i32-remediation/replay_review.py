"""Replay the review's full-material fake approval without writing real approvals."""

import copy
import json
import runpy
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1]
app = runpy.run_path(str(BASE / "i3s2_apply_decisions.py"))
verifier = runpy.run_path(str(BASE / "i3s2_verify_candidates.py"))
mapper = runpy.run_path(str(BASE / "i3s2_evidence_targets.py"))
payload = json.loads((BASE / "i3-2/evidence-targets-candidates.json").read_text())
gold = app["load_jsonl"](BASE / "query-gold-frozen.jsonl")
slots = app["load_jsonl"](BASE / "source-gold-frozen.jsonl")
slot_map = {s["gold_id"]: s for s in slots}
fake = {
    **verifier["_synthetic_decisions"](payload),
    "facet_decisions": [],
    "question_reviews": [],
    "negative_reviews": [],
    "human_status_clarifications": [],
}
for q in payload["questions"]:
    qid = q["query_id"]
    if q["answer_existence"] == "no_answer":
        fake["negative_reviews"].append(
            dict(
                query_id=qid,
                decision="批准",
                full_text_coverage_confirmed=True,
                reason="SYNTHETIC ONLY",
            )
        )
        continue
    fake["question_reviews"].append(
        dict(
            query_id=qid,
            decision="批准",
            reviewed_against_requirement=True,
            reason="SYNTHETIC ONLY",
        )
    )
    for pending in q["pending_human"]:
        primary = [i for i in pending.get("suggestions", []) if i.get("role") == "primary"]
        if not primary:
            fallback = next(
                slot for slot in q["candidate_slots"] if slot_map[slot].get("expected_items")
            )
            primary = [{"slot": fallback, "item_index": 0}]
        fake["facet_decisions"].append(
            dict(
                item_id=pending["item_id"],
                query_id=qid,
                facet_id=pending.get("facet_id"),
                decision="批准",
                chosen=[{"slot": i["slot"], "item_index": i["item_index"]} for i in primary],
                reason="SYNTHETIC ONLY",
                residual_accepted=True,
                residual_reason="missing facts NOT supplied",
            )
        )
fake["human_status_clarifications"] = [
    dict(gold_id=i["gold_id"], resolution="残留描述", reason="SYNTHETIC ONLY")
    for i in payload.get("human_status_conflicts", [])
]
scenarios = {"original_residual_waiver": fake}
wrong = copy.deepcopy(fake)
for entry in wrong["facet_decisions"]:
    if entry["query_id"] == "company-008":
        entry["chosen"] = [{"slot": "company-008-claim-001", "item_index": 4}]
scenarios["original_all_sources_collapse"] = wrong
hint = copy.deepcopy(fake)
for entry in hint["facet_decisions"]:
    if entry["item_id"] == "I32-industry-004-02":
        entry.update(
            chosen=[{"slot": "industry-009-claim-001", "item_index": 2}], residual_accepted=False
        )
scenarios["original_statistical_window_hint"] = hint
results = {}
for name, decision in scenarios.items():
    report = app["evaluate"](payload, gold, slots, decision)
    assert report["ready"] is False, name
    try:
        app["project"](payload, gold, slots, decision)
    except ValueError:
        report["projection_blocked"] = True
    else:
        raise AssertionError("invalid decisions projected: " + name)
    results[name] = report
assert (
    mapper["render_adjudication"](payload)
    == (BASE / "i3-2/evidence-targets-adjudication.md").read_text()
)
results["markdown_replay_exact"] = True
with (HERE / "review-replay.json").open("x", encoding="utf-8") as output:
    json.dump(results, output, ensure_ascii=False, indent=2)
    output.write("\n")
print("3 original full-material scenarios blocked; projection also refused; template replay exact")
