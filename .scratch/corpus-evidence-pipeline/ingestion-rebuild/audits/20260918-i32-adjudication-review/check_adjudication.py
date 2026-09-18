"""Audit frozen-candidate adjudication template without mutating any input."""
import copy
import json
from pathlib import Path
import re
import runpy

ROOT = Path(__file__).resolve().parents[5]
BASE = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild"


def main():
    payload = json.loads((BASE / "i3-2/evidence-targets-candidates.json").read_text())
    gold = [json.loads(s) for s in (BASE / "query-gold-frozen.jsonl").read_text().splitlines() if s]
    candidates = {q["query_id"]: q for q in payload["questions"]}
    markdown = (BASE / "i3-2/evidence-targets-adjudication.md").read_text()
    mapper = runpy.run_path(str(BASE / "i3s2_evidence_targets.py"))
    verifier = runpy.run_path(str(BASE / "i3s2_verify_candidates.py"))
    ids = re.findall(r"\*\*`(I32-[^`]+)`\*\*", markdown)
    expected = [item["item_id"] for q in candidates.values() for item in q["pending_human"]]
    gate = verifier["run_completeness_gate"]
    original = gate(gold, candidates)
    altered = copy.deepcopy(candidates)
    for q in altered.values():
        q["adjudication"]["status"] = "approved"
    bypass_all = gate(gold, altered)
    partial = copy.deepcopy(candidates)
    for item in original["blocked_questions"]:
        partial[item["query_id"]]["adjudication"]["status"] = "approved"
    bypass_some = gate(gold, partial)
    checks, failures = verifier["run_probes"](gold, candidates)
    result = {
        "question_count": len(candidates), "summary": payload["summary"],
        "adjudication_ids": len(ids), "unique_ids": len(set(ids)),
        "queue_ids_exact": set(ids) == set(expected),
        "markdown_replay_exact": mapper["render_adjudication"](payload) == markdown,
        "original_gate": original,
        "all_status_approved_only": bypass_all,
        "all_status_approved_pending_items_retained": sum(len(q["pending_human"]) for q in altered.values()),
        "only_blocked_status_approved": bypass_some,
        "existing_probes": {"count": len(checks), "failed": failures},
        "details": {qid: candidates[qid] for qid in (
            "company-001", "company-008", "industry-003", "macro-003", "macro-004", "macro-005", "macro-006")},
    }
    path = Path(__file__).resolve().parent / "checks.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k not in {"details", "original_gate"}},
                     ensure_ascii=False, indent=2))
    for qid in ("company-001", "macro-003"):
        item = candidates[qid]
        print(qid, "requirement_facets=", json.dumps(item["requirement_facets"], ensure_ascii=False))
    print("Audit output:", path)


if __name__ == "__main__":
    main()
