"""Independent byte/provenance checks and candidate-only integration diagnostic."""
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1]
ROOT = HERE.parents[4]
sys.path[:0] = [str(ROOT), str(BASE)]
from plugins.corpus.preparation.guard import install

install(HERE / "annotation-guard.json")
import pymupdf
import i3s2_apply_decisions as approval
import i3s2_evidence_targets as mapping


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_lines(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line]


checks = []


def check(name, passed, details=None):
    checks.append({"name": name, "passed": bool(passed), "details": details})


review = read(HERE / "adjudication-reviewed.json")
supplements = read(HERE / "source-gold-supplements-proposed.json")
source_list = read(HERE / "authorized-sources.json")["sources"]
texts = {}
for source in source_list:
    raw = (ROOT / source["path"]).read_bytes()
    check("source_sha256:" + source["source_id"], hashlib.sha256(raw).hexdigest() == source["sha256"])
    doc = pymupdf.open(stream=raw, filetype="pdf")
    texts[source["source_id"]] = [p.get_text() for p in doc]
    doc.close()
check("only_six_sources_89_pages", len(texts) == 6 and sum(map(len, texts.values())) == 89)
by_id = {e["evidence_id"]: e for e in supplements["spans"]}
check("unique_span_ids", len(by_id) == 56)
for e in supplements["spans"]:
    raw = texts[e["source_id"]][e["page"] - 1]
    check("raw_slice:" + e["evidence_id"], raw[e["char_start"]:e["char_end_exclusive"]] == e["quote"])
    check("quote_sha:" + e["evidence_id"], hashlib.sha256(e["quote"].encode()).hexdigest() == e["quote_sha256"])
    check("text_and_image_binding:" + e["evidence_id"], sha(HERE / e["text_artifact"]) == e["text_artifact_sha256"] and sha(HERE / e["image_artifact"]) == e["image_sha256"])
gold = load_lines(BASE / "query-gold-frozen.jsonl")
slots = load_lines(BASE / "source-gold-frozen.jsonl")
payload = read(BASE / "i3-2/evidence-targets-candidates.json")
pending = {p["item_id"]: p for q in payload["questions"] for p in q["pending_human"]}
facets = review["facet_reviews"]
check("all_40_facets_unique_exact_identity", len(facets) == 40 and {r["item_id"] for r in facets} == set(pending) and all(r["facet_id"] == pending[r["item_id"]].get("facet_id") for r in facets))
check("answer_constraints_no_targets", all(not r["evidence_ids"] for r in facets if r["kind"] == "answer_constraint"))
check("other_facets_have_actual_references", all(r["evidence_ids"] and set(r["evidence_ids"]) <= set(by_id) for r in facets if r["kind"] != "answer_constraint"))
check("source_specific_obligations_isolated", all(not pending[r["item_id"]].get("source_id") or {by_id[e]["source_id"] for e in r["evidence_ids"]} == {pending[r["item_id"]]["source_id"]} for r in facets))
answerable = {q["query_id"] for q in gold if q["answer_existence"] == "answerable"}
negative = {q["query_id"] for q in gold if q["answer_existence"] == "no_answer"}
check("24_positive_reviews_no_omission", len(review["question_reviews"]) == 24 and {r["query_id"] for r in review["question_reviews"]} == answerable)
check("6_negative_reviews_no_omission", len(review["negative_reviews"]) == 6 and {r["query_id"] for r in review["negative_reviews"]} == negative)
check("negative_coverage_exact_scope", all(set(r["coverage_source_ids"]) == set(texts) and r["reason"] and r["scope_limit"] for r in review["negative_reviews"]))
check("not_claiming_human_approval", review["human_approved"] is False and review["ready_for_gold_freeze"] is False and all(r["human_approved"] is False for r in facets + review["question_reviews"] + review["negative_reviews"]))
proposal = load_lines(HERE / "source-gold-proposed.jsonl")
check("frozen_source_gold_unchanged_prefix", proposal[:len(slots)] == slots and (HERE / "source-gold-proposed.jsonl").read_bytes().startswith((BASE / "source-gold-frozen.jsonl").read_bytes()))
check("new_annotations_explicit_AI_provenance", all("AI" in r["reviewer"] and r["approval_state"] == "pending_user_adoption" for r in proposal[len(slots):]))
pool = {r["gold_id"]: r for r in proposal}
check("proposal_refs_match_exact_quote", all(pool[e["proposed_ref"]["slot"]]["expected_items"][e["proposed_ref"]["item_index"]]["quote"] == e["quote"] for e in by_id.values()))
protected = read(HERE / "protected-artifacts-check.json")
check("frozen_files_unchanged", all(sha(BASE / path) == h for path, h in protected["sha256"].items()))
check("no_formal_approval_created", not (BASE / "i3-2/evidence-targets-decisions.json").exists() and not (BASE / "i3-2/evidence-targets-approved.json").exists())
gate = approval.evaluate(payload, gold, slots, None)
check("formal_gate_remains_closed_without_signoff", gate["ready"] is False)
# A draft must fail even if someone accidentally hands it to the real applier.
accidental_gate = approval.evaluate(payload, gold, slots, review)
check("AI_draft_cannot_masquerade_as_approval", accidental_gate["ready"] is False)
old_stats = Counter(q["machine_status"] for q in payload["questions"])
new = [mapping.map_question(q, proposal) for q in gold]
diagnostic = {"artifact": "proposal-remapping-diagnostic-NOT-APPROVAL", "rule_rev": mapping.RULE_REV,
    "warning": "仅离线检查补证对候选映射的影响；不是正式候选/批准投影/业务验收，不回写I3资产。",
    "old_statuses": dict(old_stats), "proposed_statuses": dict(Counter(q["machine_status"] for q in new)),
    "old_targets": sum(len(q["targets"]) for q in payload["questions"]),
    "proposed_targets": sum(len(q["targets"]) for q in new),
    "pending_decisions": sum(len(q["pending_human"]) for q in new),
    "questions": [{"query_id": q["query_id"], "machine_status": q["machine_status"], "target_count": len(q["targets"]), "pending_count": len(q["pending_human"])} for q in new]}
with (HERE / "candidate-remap-diagnostic.json").open("x") as out:
    json.dump(diagnostic, out, ensure_ascii=False, indent=2)
report = {"passed": all(c["passed"] for c in checks), "checks": checks,
    "summary": {"passed": sum(c["passed"] for c in checks), "total": len(checks)},
    "independent_reader_exact_whitespace_normalized_matches": sum(e["independent_reader_contains_whitespace_normalized_quote"] for e in by_id.values()),
    "independent_reader_layout_differences": [e["evidence_id"] for e in by_id.values() if not e["independent_reader_contains_whitespace_normalized_quote"]],
    "limitations": "机器检查只证明引用字节、身份、完整性和隔离；AI语义判断/图表绑定由审阅记录承担，未声称独立人工验收。两阅读器的抽取顺序/重复字层导致部分长句非连续匹配，不篡改quote来强制匹配。",
    "formal_gate_ready": gate["ready"], "draft_as_approval_ready": accidental_gate["ready"]}
with (HERE / "verification.json").open("x") as out:
    json.dump(report, out, ensure_ascii=False, indent=2)
print(json.dumps(report["summary"]))
print(json.dumps({k: v for k, v in diagnostic.items() if k != "questions"}, ensure_ascii=False))
assert report["passed"]
