"""Pure retrieval comparison of frozen same-query pools; no agent or model calls."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from dataclasses import replace

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PREVIOUS = ROOT / ".scratch/corpus-selection-audit-20261021"
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location("selection_audit", PREVIOUS / "run.py")
prior = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prior)
from plugins.corpus.retrieval.diagnostics import global_rrf, candidate_fates, relevance_bands

labels = json.loads((HERE / "labels.json").read_text())
authority = json.loads((HERE / "authority.json").read_text())
assert labels["authority_sha256"] == hashlib.sha256((HERE / "authority.json").read_bytes()).hexdigest()


def scope(hits):
    return {c for h in hits for c in (h.context_chunk_ids or (h.chunk_id,))}


def dedupe_contained(hits):
    """Offline only: same anchor and contained scopes; retain complete superset."""
    output = []
    for hit in hits:
        current = set(hit.context_chunk_ids or (hit.chunk_id,))
        for i, old in enumerate(output):
            if (old.build_id,old.chunk_id) != (hit.build_id,hit.chunk_id):
                continue
            previous = set(old.context_chunk_ids or (old.chunk_id,))
            if current <= previous:
                break
            if previous <= current:
                output[i] = replace(old, context_chunk_ids=hit.context_chunk_ids)
                break
        else:
            output.append(hit)
    # Preserve all versioned evidence scopes; no backfill and no fabricated spans.
    def identities(values):
        return {(h.build_id,c) for h in values for c in (h.context_chunk_ids or (h.chunk_id,))}
    assert identities(output) == identities(hits)
    return tuple(output)


def grade(case, chunk):
    if chunk in case["labels"]:
        return case["labels"][chunk]
    if case["build_id"] is not None and authority[chunk]["build_id"] != case["build_id"]:
        return {"grade": "source_scope_mismatch", "facets": []}
    raise AssertionError("Unjudged chunk: " + chunk)


def metrics(case, hits, k):
    page = hits[:k]
    anchors = [h.chunk_id for h in page]
    relevant = set(case["positive_chunks"])
    facets = set(case["facets"])
    gathered = set(anchors) & relevant
    regions = scope(page)
    anchor_facets = {f for c in set(anchors) for f in grade(case, c)["facets"]}
    scope_facets = {f for c in regions & relevant for f in grade(case, c)["facets"]}
    return {"returned": len(page), "precision_at_k": sum(c in relevant for c in anchors)/k,
            "precision_returned": sum(c in relevant for c in anchors)/len(page) if page else None,
            "full_evidence_precision_at_k": sum(grade(case,c)["grade"] == "full" for c in anchors)/k,
            "unique_relevant_per_k": len(gathered)/k,
            "anchor_recall": len(gathered)/len(relevant) if relevant else None,
            "context_recall": len(regions & relevant)/len(relevant) if relevant else None,
            "anchor_facet_coverage": len(anchor_facets)/len(facets) if facets else None,
            "context_facet_coverage": len(scope_facets)/len(facets) if facets else None,
            "duplicate_anchor_slots": len(anchors)-len(set(anchors)),
            "context_chunks": len(regions),
            "repeated_context_slots": sum(len(h.context_chunk_ids or (h.chunk_id,)) for h in page)-len(regions),
            "anchors": [{"chunk": c, "grade": grade(case,c)["grade"], "facets": grade(case,c)["facets"]} for c in anchors]}


out = {"labels_sha256": hashlib.sha256((HERE / "labels.json").read_bytes()).hexdigest(),
       "notes": "Candidate lists versus production output are separate stages. P@K uses substantive partial/full evidence; recall is within reviewed report only. Negative-case recall undefined. Global RRF is offline diagnostic, not enabled.", "cases": {}}
for cid, case in labels["cases"].items():
    capture = json.loads((PREVIOUS / f"captures/{cid}.json").read_text())
    pool = json.loads((HERE / f"pools/{cid}.json").read_text())
    assert pool["capture_sha256"] == hashlib.sha256((PREVIOUS / f"captures/{cid}.json").read_bytes()).hexdigest()
    trace = prior.restore(capture["trace"])
    methods = {"lexical_candidates": trace.lexical, "dense_candidates": trace.dense,
               "two_level_rrf_candidates": trace.fused, "production_hybrid": trace.selected,
               "contained_duplicate_diagnostic": dedupe_contained(trace.selected)}
    if cid != "n01":
        methods["global_rrf_diagnostic"] = global_rrf(trace)
        methods["global_rrf_bands_cap3_diagnostic"] = relevance_bands(trace)
    row = {"positive_chunks": case["positive_chunks"], "methods": {}, "candidate_coverage": {}, "evidence_paths": []}
    for name, hits in methods.items():
        row["methods"][name] = {str(k): metrics(case,hits,k) for k in (1,5,10)}
        row["candidate_coverage"][name] = {"size": len(hits), "relevant": sorted({h.chunk_id for h in hits} & set(case["positive_chunks"]))}
    row["production_duplicate_groups"] = []
    for chunk in dict.fromkeys(h.chunk_id for h in trace.selected):
        group = [(i+1,h) for i,h in enumerate(trace.selected) if h.chunk_id == chunk]
        if len(group) > 1:
            row["production_duplicate_groups"].append({"chunk":chunk,"ranks":[i for i,h in group],
                "context_sizes":[len(h.context_chunk_ids) for i,h in group],
                "same_context":len({h.context_chunk_ids for i,h in group}) == 1})
    fates = {r["chunk_id"]: r for r in candidate_fates(trace)}
    for chunk in case["positive_chunks"]:
        path = {"chunk": chunk, "facets": grade(case,chunk)["facets"], "fate": fates.get(chunk),
                "production_anchor_ranks": [i+1 for i,h in enumerate(trace.selected) if h.chunk_id == chunk],
                "production_context_ranks": [i+1 for i,h in enumerate(trace.selected) if chunk in (h.context_chunk_ids or (h.chunk_id,))]}
        row["evidence_paths"].append(path)
    out["cases"][cid] = row
    print(cid, {name: {k: data["10"][k] for k in ("precision_at_k", "anchor_recall", "context_recall", "duplicate_anchor_slots")} for name,data in row["methods"].items()})

# Broader 32-question proxy remains separate: original labels are incomplete.
manifest = json.loads((ROOT / ".scratch/corpus-vector-acceptance-20261020/manifest.json").read_text())
proxy = []
for case in manifest["cases"]:
    cid = case["id"]
    capture = json.loads((PREVIOUS / f"captures/{cid}.json").read_text())
    trace = prior.restore(capture["trace"])
    gold = set(case.get("gold_chunks", []))
    row = {"case": cid, "status": trace.status, "gold_count": len(gold), "channels": {}}
    for name in ("lexical", "dense", "fused", "selected"):
        hits = getattr(trace,name)
        ids = [h.chunk_id for h in hits]
        row["channels"][name] = {"pool_size":len(ids), "gold_in_pool":len(set(ids)&gold),
            "gold_anchors_top10":len(set(ids[:10])&gold), "gold_context_top10":len(scope(hits[:10])&gold),
            "duplicate_anchor_slots_top10":len(ids[:10])-len(set(ids[:10]))}
    if trace.status == "hybrid":
        variant = relevance_bands(trace)
        row["channels"]["global_rrf_bands_cap3_diagnostic"] = {
            "gold_anchors_top10":len({h.chunk_id for h in variant}&gold),
            "gold_context_top10":len(scope(variant)&gold)}
    deduped = dedupe_contained(trace.selected)
    row["contained_duplicate_diagnostic"] = {"before":len(trace.selected), "after":len(deduped),
        "all_versioned_context_preserved":True, "gold_context":len(scope(deduped)&gold)}
    proxy.append(row)
out["all32_incomplete_gold_proxy"] = proxy
(HERE / "metrics.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
