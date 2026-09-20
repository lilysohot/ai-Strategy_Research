"""Read-only post-score diagnosis; never adds evidence to scored observations."""
import json
from collections import Counter
from pathlib import Path
import sys
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
BASE = HERE.parents[1]
sys.path.insert(0, str(HERE))
import calibrate
release = calibrate.load_module("region_release_diagnosis", BASE / "audits/20260920-i31-region-review/release.py")
dsn = release.connect()
from plugins.corpus.preparation.repository_pg import PgStore
from plugins.corpus.preparation.contract import UnitStatus
identity = json.loads((HERE / "source-identity-map.json").read_text())
alias_to_source = {a: s for s, a in identity["aliases"].items()}
scores = json.loads((HERE / "candidate_question_lexemes_or-score.json").read_text())
observations = {r["query_id"]: r for r in json.loads((HERE / "candidate_question_lexemes_or-observations.json").read_text())}
records = {r["query_id"]: r for r in map(json.loads, (BASE / "i3-2/query-gold-scoring-v1.jsonl").read_text().splitlines())}
rows = []
with PgStore(dsn) as store:
    native = {source: tuple(u for u in store.get_units(build) if u.status is UnitStatus.KEPT)
              for source, build in identity["active_builds"].items()}
    for question in scores["questions"]:
        query_id = question["query_id"]
        missing = {f.split(":", 1)[1] for f in question["failures"] if f.startswith("evidence_target_missing:")}
        for target in records[query_id].get("evidence_targets", []):
            if target["target_id"] not in missing:
                continue
            source = alias_to_source[target["source_id"]]
            kept = native[source]
            pages = {}
            for unit in kept:
                pages.setdefault(unit.location.page, []).append(unit.raw_text)
            returned = [e for doc in observations[query_id]["documents"] if doc["source_id"] == target["source_id"]
                        for e in doc["evidence"]]
            quote_returned = any(target["quote"] in e["text"] for e in returned)
            quote_kept = any(target["quote"] in "\n".join(texts) for texts in pages.values())
            cause = "returned_quote_missing_required_locator" if quote_returned else (
                "retained_quote_outside_selected_chunks" if quote_kept else "exact_quote_not_in_kept_page_text")
            rows.append({"query_id": query_id, "target_id": target["target_id"], "cause": cause,
                         "source_id": source, "required_locator": target["locator"],
                         "quote_retained": quote_kept, "quote_returned": quote_returned})
calibrate.write_once("evidence-diagnosis.json", {"missing_targets": len(rows),
    "causes": dict(Counter(r["cause"] for r in rows)), "targets": rows,
    "note": "Diagnostic kept-unit scan only; original top-k observations and scores unchanged. No target-guided retrieval or score supplementation."})
print(json.dumps({"missing_targets": len(rows), "causes": dict(Counter(r["cause"] for r in rows))}, ensure_ascii=False))
