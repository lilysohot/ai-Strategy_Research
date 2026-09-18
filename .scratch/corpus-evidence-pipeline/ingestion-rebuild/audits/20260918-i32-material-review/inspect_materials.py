"""Read-only audit of frozen expected assets, never candidate business results.

Does not execute generator main(), write gold, connect PG, or read source files.
Writes only its generated diagnostic output in this new audit directory.
"""
import hashlib
import json
from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[5]
BASE = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild"


def main():
    payload = json.loads((BASE / "i3-2/evidence-targets-candidates.json").read_text())
    queries = [json.loads(line) for line in (BASE / "query-gold-frozen.jsonl").read_text().splitlines() if line]
    slots = [json.loads(line) for line in (BASE / "source-gold-frozen.jsonl").read_text().splitlines() if line]
    candidates = {q["query_id"]: q for q in payload["questions"]}
    query_by_id = {q["query_id"]: q for q in queries}
    slot_by_id = {q["gold_id"]: q for q in slots}
    mapper = runpy.run_path(str(BASE / "i3s2_evidence_targets.py"))
    verifier = runpy.run_path(str(BASE / "i3s2_verify_candidates.py"))
    from plugins.corpus.scoring import gold_from_records, score

    hash_checks = {}
    for key, entry in payload["inputs"].items():
        hash_checks[key] = hashlib.sha256((ROOT / entry["path"]).read_bytes()).hexdigest() == entry["sha256"]
    trace_errors = []
    for q in payload["questions"]:
        for target in q["targets"]:
            basis = target["basis"]
            slot = slot_by_id[basis["gold_id"]]
            item = slot["expected_items"][basis["item_index"]]
            if not (target["quote"] == item["quote"] and
                    target["source_id"] == slot["source_id"] and
                    target["source_id"] in query_by_id[q["query_id"]]["relevant_sources"] and
                    target["locator"] == list(mapper["locator_tokens"](slot))):
                trace_errors.append([q["query_id"], target["target_id"]])
    recomputed = [mapper["map_question"](q, slots) for q in queries]
    result = {"summary": payload["summary"], "input_hashes": hash_checks,
              "query_ids_exact": len(candidates) == len(queries) == 30 and set(candidates) == set(query_by_id),
              "target_trace_errors": trace_errors,
              "mapping_replay_exact": recomputed == payload["questions"]}
    records = verifier["build_records"](queries, candidates)
    gold = {q.query_id: q for q in gold_from_records(records)}
    observations = {q["query_id"]: verifier["synthesize_observation"](q, candidates[q["query_id"]]) for q in queries}
    report = score(tuple(gold.values()), observations)
    result["synthetic_roundtrip_passed"] = report.passed
    result["synthetic_blockers"] = list(report.blockers)

    # Counterfactuals alter only synthetic observations. Frozen inputs remain intact.
    from dataclasses import replace
    variants = []
    for qid, kept in [("industry-001", [0, 2]), ("company-005", [1, 2]),
                      ("industry-004", [6, 7])]:
        obs = observations[qid]
        doc = obs.documents[0]
        variant = replace(obs, documents=(replace(doc, evidence=tuple(doc.evidence[i] for i in kept)),))
        item = score((gold[qid],), (variant,)).questions[0]
        variants.append({"query_id": qid, "kept_target_indices": kept,
                         "observation_texts": [e.text for e in variant.documents[0].evidence],
                         "evidence_pass": item.evidence_pass, "failures": list(item.failures)})
    result["counterfactuals"] = variants
    result["mapped_but_missing_qualifications"] = [
        {"query_id": qid, "requirement": query_by_id[qid]["evidence_requirement"],
         "targets": [t["quote"] for t in candidates[qid]["targets"]],
         "synthetic_evidence_pass": report.question(qid).evidence_pass}
        for qid in ("macro-003", "macro-005", "macro-006", "macro-008", "industry-001")]
    result["source_slot_details"] = {key: slot_by_id[key] for key in (
        "industry-009-claim-001", "macro-038-claim-001", "macro-039-claim-001",
        "macro-060-claim-001", "industry-057-claim-001")}
    result["company_004"] = candidates["company-004"]
    output = Path(__file__).resolve().parent / "material-checks.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items()
                      if key not in {"source_slot_details", "company_004", "mapped_but_missing_qualifications"}},
                     ensure_ascii=False, indent=2))
    print("Full diagnostic output:", output)


if __name__ == "__main__":
    main()
