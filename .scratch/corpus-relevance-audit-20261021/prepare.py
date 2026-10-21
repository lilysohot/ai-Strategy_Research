"""Freeze retrieval-only audit; fetch authoritative corpus, never search/embed."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from dataclasses import asdict

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
BASE = ROOT / ".scratch/corpus-vector-acceptance-20261020"
CAPTURES = ROOT / ".scratch/corpus-selection-audit-20261021/captures"
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location("prior_eval", BASE / "run_eval.py")
prior = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prior)
SELECTED = ("p01", "p13", "p16", "n01")


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


cases, target, digest, profile = prior.setup()
sources = json.loads((BASE / "corpus.json").read_text())
plan = {"cases": [{"id": c["id"], "question": c["question"], "build_id": c.get("build_id"),
                   "source_id": c.get("source_id")} for c in cases if c["id"] in SELECTED],
        "manifest_sha256": digest, "profile": profile,
        "methods": ["lexical_candidates", "dense_candidates", "fused_candidates", "production_hybrid"],
        "k": [1, 5, 10],
        "labels": "Original-text relevance, no assessment of source factual truth. Full/partial evidence vs context-only vs mismatch. Source-constrained recall scoped to completely reviewed requested reports. No full-corpus recall claim.",
        "negative": "n01 pooled precision/mismatch only; recall undefined without positive evidence.",
        "no_agent_runs": True, "no_new_embedding_requests": True}
save(HERE / "plan.json", plan)
from plugins.corpus.preparation.read_pg import fetch_bands
from plugins.corpus.retrieval.embedding import VectorConfig
cfg = VectorConfig.from_env()
order = {s["source_id"]: tuple(c["chunk_id"] for c in s["chunks"]) for s in sources}
bands = tuple(SimpleNamespace(source_id=s["source_id"], build_id=s["active_build_id"],
                              start=0, end=len(s["chunks"])-1) for s in sources)
evidence_path = HERE / "authority.json"
if not evidence_path.exists():
    evidence = fetch_bands(target, bands, order, sandbox_db=cfg.target_db)
    assert len(evidence) == 703
    save(evidence_path, {c.chunk_id: asdict(c) for c in evidence})
evidence = json.loads(evidence_path.read_text())
titles = {s["source_id"]: s["title"] for s in sources}
for case in plan["cases"]:
    cid = case["id"]
    path = CAPTURES / f"{cid}.json"
    capture = json.loads(path.read_text())
    assert capture["manifest_sha256"] == digest and capture["profile"] == profile
    assert capture["trace"]["status"] == "hybrid"
    pool = set()
    ranks = {}
    for method, channel in (("lexical", "lexical"), ("dense", "dense"), ("fused", "fused"), ("production", "selected")):
        for rank, hit in enumerate(capture["trace"][channel][:10], 1):
            pool.add(hit["chunk_id"])
            ranks.setdefault(hit["chunk_id"], {})[method] = rank
    report_scope = {c["chunk_id"] for c in evidence.values() if c["build_id"] == case["build_id"]}
    wanted = sorted(pool | report_scope)
    save(HERE / "pools" / f"{cid}.json", {"case": case, "capture_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                                        "top10_pool": sorted(pool), "reviewed_report_scope": sorted(report_scope), "ranks": ranks})
    lines = [f"# {cid}", "", case["question"], "", "## Requested report, all chunks", ""]
    for chunkid in sorted(report_scope):
        c = evidence[chunkid]
        lines += [f"### {chunkid} ({c['kind']})", json.dumps(ranks.get(chunkid, {})), c["text"], ""]
    lines += ["## Other-source top10 pool", ""]
    for chunkid in sorted(pool - report_scope):
        c = evidence[chunkid]
        lines += [f"### {chunkid} ({c['kind']})", titles[c["source_id"]], json.dumps(ranks[chunkid]), c["text"], ""]
    (HERE / f"review-{cid}.md").write_text("\n".join(lines), encoding="utf-8")
    print(cid, "report_chunks", len(report_scope), "pooled", len(pool), "review_total", len(wanted))
save(HERE / "snapshot.json", {"authority_sha256": hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
                             "chunks": len(evidence), "sources": len(sources), "new_embeddings": 0})
