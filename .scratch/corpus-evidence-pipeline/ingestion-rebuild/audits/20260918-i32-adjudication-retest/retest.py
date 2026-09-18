"""Read-only product audit. Synthetic decisions never leave memory or become approvals."""
import copy
import json
from pathlib import Path
import re
import runpy
import subprocess

ROOT = Path(__file__).resolve().parents[5]
BASE = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild"


def main():
    verifier = runpy.run_path(str(BASE / "i3s2_verify_candidates.py"))
    app = runpy.run_path(str(BASE / "i3s2_apply_decisions.py"))
    mapper = runpy.run_path(str(BASE / "i3s2_evidence_targets.py"))
    payload = json.loads((BASE / "i3-2/evidence-targets-candidates.json").read_text())
    gold = [json.loads(s) for s in (BASE / "query-gold-frozen.jsonl").read_text().splitlines() if s]
    slots = [json.loads(s) for s in (BASE / "source-gold-frozen.jsonl").read_text().splitlines() if s]
    by_id = {q["query_id"]: q for q in payload["questions"]}
    slot_map = {s["gold_id"]: s for s in slots}
    doc = (BASE / "i3-2/evidence-targets-adjudication.md").read_text()
    ids = re.findall(r"\*\*`(I32-[^`]+)`\*\*", doc)
    expected = [i["item_id"] for q in payload["questions"] for i in q["pending_human"]]
    results = {"ids": len(ids), "ids_unique": len(set(ids)), "ids_exact": set(ids) == set(expected),
               "markdown_replay_exact": mapper["render_adjudication"](payload) == doc}
    checks, failed = verifier["run_probes"](gold, by_id)
    results["existing_probes"] = {"count": len(checks), "failed": failed}
    changed = copy.deepcopy(payload)
    for q in changed["questions"]:
        q["adjudication"]["status"] = "approved"
    results["old_status_flip"] = app["evaluate"](changed, gold, slots, None)

    # Reuse existing tiny positive-control fixture; mutate one field at a time.
    p, g, s = verifier["_synthetic_payload"]()
    d = verifier["_synthetic_decisions"](p)
    results["positive_control"] = app["evaluate"](p, g, s, d)["ready"]
    mutations = {}
    dupe = copy.deepcopy(d)
    dupe["question_reviews"].insert(0, {**dupe["question_reviews"][0], "decision": "需补要件"})
    mutations["conflicting_question_reviews"] = dupe
    no_reason = copy.deepcopy(d)
    no_reason["negative_reviews"][0].pop("reason")
    mutations["negative_review_without_reason"] = no_reason
    identity = copy.deepcopy(d)
    identity["facet_decisions"][0].update(query_id="wrong-question", facet_id="wrong-facet")
    mutations["mismatched_decision_identity"] = identity
    results["schema_mutations"] = {name: app["evaluate"](p, g, s, decision)
                                  for name, decision in mutations.items()}

    # Isolate source-specific coverage without relying on residual waivers.
    sp, sg, ss = copy.deepcopy((p, g, s))
    sq = sp["questions"][0]
    sq["satisfy_rule"] = sg[0]["satisfy_rule"] = "all"
    sq["relevant_sources"].append("probe-source-B")
    sg[0]["relevant_sources"] = list(sq["relevant_sources"])
    sq["candidate_slots"].append("probe-slot-B")
    ss.append({**copy.deepcopy(ss[0]), "gold_id": "probe-slot-B", "source_id": "probe-source-B"})
    sq["pending_human"][0].update(kind="source_coverage", facet_id=None, source_id="probe-source-B")
    sd = copy.deepcopy(d)
    sd["facet_decisions"][0]["facet_id"] = None
    # chosen remains source A; request explicitly requires B.
    results["isolated_wrong_source_no_residual"] = app["evaluate"](sp, sg, ss, sd)
    results["isolated_source_projection"] = app["project"](sp, sg, ss, sd)["questions"][0]

    # Answer constraints must never project arbitrary chosen references.
    ap, ag, ass = copy.deepcopy((p, g, s))
    ap["questions"][0]["pending_human"][0]["kind"] = "answer_constraint"
    ad = copy.deepcopy(d)
    ad["facet_decisions"][0]["chosen"] = [{"slot": "nonexistent-slot", "item_index": 999}]
    results["answer_constraint_unchecked_chosen"] = app["evaluate"](ap, ag, ass, ad)
    results["answer_constraint_projection"] = app["project"](ap, ag, ass, ad)["questions"][0]

    # All-data harness is intentionally NOT semantically valid: residual is switched on
    # to expose whether required facts can be waived. Never persist this decision object.
    fake = {**verifier["_synthetic_decisions"](payload), "facet_decisions": [],
            "question_reviews": [], "negative_reviews": [], "human_status_clarifications": []}
    for q in payload["questions"]:
        qid = q["query_id"]
        if q["answer_existence"] == "no_answer":
            fake["negative_reviews"].append(dict(query_id=qid, decision="批准",
                full_text_coverage_confirmed=True, reason="SYNTHETIC ONLY"))
            continue
        fake["question_reviews"].append(dict(query_id=qid, decision="批准",
            reviewed_against_requirement=True, reason="SYNTHETIC ONLY"))
        for pending in q["pending_human"]:
            primary = [i for i in pending.get("suggestions", []) if i.get("role") == "primary"]
            if not primary:
                fallback = next(slot for slot in q["candidate_slots"] if slot_map[slot].get("expected_items"))
                primary = [{"slot": fallback, "item_index": 0}]
            chosen = [{"slot": i["slot"], "item_index": i["item_index"]} for i in primary]
            fake["facet_decisions"].append(dict(item_id=pending["item_id"], query_id=qid,
                facet_id=pending.get("facet_id"), decision="批准", chosen=chosen,
                reason="SYNTHETIC ONLY", residual_accepted=True, residual_reason="SYNTHETIC missing facts NOT supplied"))
    fake["human_status_clarifications"] = [dict(gold_id=i["gold_id"], resolution="残留描述",
        reason="SYNTHETIC ONLY") for i in payload.get("human_status_conflicts", [])]
    results["residual_waives_missing_facts"] = app["evaluate"](payload, gold, slots, fake)
    wrong_sources = copy.deepcopy(fake)
    for d_item in wrong_sources["facet_decisions"]:
        if d_item["query_id"] == "company-008":
            d_item["chosen"] = [{"slot": "company-008-claim-001", "item_index": 4}]
    results["all_rule_one_source_only"] = app["evaluate"](payload, gold, slots, wrong_sources)
    projection = app["project"](payload, gold, slots, wrong_sources)
    q8 = next(q for q in projection["questions"] if q["query_id"] == "company-008")
    results["company_008_projected_identity"] = {
        "relevant_sources": q8["relevant_sources"], "satisfy_rule": q8["satisfy_rule"],
        "required_evidence_sources": sorted({t["source_id"] for t in q8["approved_required"]})}
    # Search-hint table cell must not replace a required footnote.
    hint = copy.deepcopy(fake)
    for d_item in hint["facet_decisions"]:
        if d_item["item_id"] == "I32-industry-004-02":
            d_item["chosen"] = [{"slot": "industry-009-claim-001", "item_index": 2}]
            d_item["residual_accepted"] = False
            d_item["residual_reason"] = ""
    hint_result = app["evaluate"](payload, gold, slots, hint)
    results["footnote_replaced_by_search_hint"] = hint_result
    clean = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "PYTHONPATH": str(ROOT),
             "PYTHONDONTWRITEBYTECODE": "1", "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
             "CORPUS_GUARD_PHASE": "i3", "CORPUS_GUARD_CONFIG": str(BASE / "guards/i3.json")}
    commands = {
        "freeze-validation": [str(ROOT / ".venv/bin/python"), "-B", str(BASE / "freezes/validate_i0c_freeze.py")],
        "scorer-regression": [str(ROOT / ".venv/bin/python"), "-B", "-m", "pytest", "--noconftest",
            "-c", "/dev/null", "-p", "no:cacheprovider", "-p", "plugins.corpus.preparation.guard_pytest",
            "tests/test_corpus_scoring.py", str(BASE / "audits/20260918-i30-review/test_review_probes.py"),
            "-q", "--tb=short"],
    }
    results["commands"] = {}
    for name, command in commands.items():
        result = subprocess.run(command, cwd=ROOT, env=clean, text=True, capture_output=True, check=False)
        (Path(__file__).parent / (name + ".txt")).write_text(
            "$ " + " ".join(command) + "\n" + result.stdout + result.stderr + f"\nexit={result.returncode}\n",
            encoding="utf-8")
        results["commands"][name] = result.returncode
    output = Path(__file__).resolve().parent / "checks.json"
    output.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for key, value in results.items():
        if isinstance(value, dict) and "ready" in value:
            print(key, json.dumps({k: value[k] for k in ("ready", "stage", "blockers", "counts") if k in value}, ensure_ascii=False))
        elif key == "schema_mutations":
            print(key, {k: v["ready"] for k, v in value.items()})
        else:
            print(key, json.dumps(value, ensure_ascii=False))
    print("Output:", output)


if __name__ == "__main__":
    main()
