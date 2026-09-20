"""Read-only FIX-1 feasibility repro (Stage-0). Never writes PG / bumps versions.

Uses the FROZEN stored KEPT units (real bbox) per target page. "before" = the stored
ordinal order (the actually-corrupt page join used by diagnosis). "after" = a
candidate improved reading order (column-first: full-width spanners separated, then
columns clustered by x-center, each y-sorted, left->right). For each of the 25 B-class
targets we check whether norm(quote) becomes contiguous in the "after" page text,
proving column reconstruction is both necessary and sufficient before any re-ingestion.
Also reports the A/C split for completeness and a company-001 p1 before/after diff.
"""
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(BASE.parents[2]))

import calibrate
release = calibrate.load_module(
    "region_release_diagnosis",
    str(BASE / "audits/20260920-i31-region-review/release.py"))
dsn = release.connect()
from plugins.corpus.preparation.repository_pg import PgStore
from plugins.corpus.preparation.contract import UnitStatus

WS = re.compile(r"\s+")
def norm(s): return WS.sub("", s) if isinstance(s, str) else ""

identity = json.loads((HERE / "source-identity-map.json").read_text())
alias_to_source = {a: s for s, a in identity["aliases"].items()}
diag = json.loads((HERE / "evidence-diagnosis.json").read_text())
gold = {json.loads(l)["query_id"]: json.loads(l)
        for l in (BASE / "i3-2/query-gold-scoring-v1.jsonl").read_text().splitlines()}
rows34 = [t for t in diag["targets"] if t["cause"] == "exact_quote_not_in_kept_page_text"]


def _bx(u): return u.location.bbox


def cluster_columns(units):
    """One-dimensional gap clustering on x-center; returns columns (each list of units),
    ordered left->right by median x. Units are non-full-width."""
    if not units:
        return []
    order = sorted(units, key=lambda u: (_bx(u)[0] + _bx(u)[2]) / 2.0)
    gap_thresh = (max(_bx(u)[2] for u in units) - min(_bx(u)[0] for u in units)) * 0.18
    cols = [[order[0]]]
    cur_x = (_bx(order[0])[0] + _bx(order[0])[2]) / 2.0
    for u in order[1:]:
        cx = (_bx(u)[0] + _bx(u)[2]) / 2.0
        if cx - cur_x >= gap_thresh:
            cols.append([])
        cols[-1].append(u)
        cur_x = cx  # track running (monotonic, stable for left->right sorted centers)
    # order columns by median x (stable already by construction: sorted centers)
    return cols


def reorder_page(units):
    """Candidate improved reading order produced by column-first reconstruction."""
    width = max(_bx(u)[2] for u in units) if units else 1.0
    spanners = [u for u in units if (_bx(u)[2] - _bx(u)[0]) >= width * 0.6]
    normal = [u for u in units if (_bx(u)[2] - _bx(u)[0]) < width * 0.6]
    spanners.sort(key=lambda u: (_bx(u)[1], _bx(u)[0]))
    cols = cluster_columns(normal)
    for col in cols:
        col.sort(key=lambda u: (_bx(u)[1], _bx(u)[0]))
    # splice spanners into the column sweep at their vertical band: emit column-first,
    # and insert a spanner right before the first emitted unit whose y is below the
    # spanner's y-bottom, within the SAME column pass. Simpler deterministic fallback:
    # place spanners interleaved by y relative to the whole (col-major) sequence.
    seq: list = []
    if len(cols) == 1:
        seq = [u for u in normal]
        seq.sort(key=lambda u: (_bx(u)[1], _bx(u)[0]))
        return _merge_spanners(seq, spanners)
    col_iter = [iter(c) for c in cols]
    # column-first concatenation: emit each column's y-sorted units left->right
    # (guide FIX-1: "栏内按 y 排序，再按栏顺序拼接"); a vertical sweep would re-interleave
    # a floating sidebar back between body rows, which is exactly the bug we are removing.
    out: list = []
    for col in cols:
        out.extend(col)
    return _merge_spanners(out, spanners)


def _merge_spanners(col_seq, spanners):
    merged = list(col_seq)
    for sp in spanners:
        idx = 0
        for k, u in enumerate(merged):
            if u.location.bbox[1] >= sp.location.bbox[1]:
                idx = k
                break
            idx = k + 1
        merged.insert(idx, sp)
    return merged


def classify(quote, txt_bytes, txt_norm):
    """A/B/C against a page text (norm lens)."""
    qn = norm(quote)
    if qn in norm(txt_bytes):
        return "A"
    parts = [p for p in re.split(r"[\n；;。]", quote) if len(norm(p)) >= 6]
    if parts and all(norm(p) in txt_norm for p in parts):
        return "B"
    return "C"


result = {"note": "read-only FIX-1 feasibility; stored kept units only; before=stored ordinal, after=column-first",
          "pages": {}, "targets": [], "summary": {}}
summary = Counter()
with PgStore(dsn) as store:
    for r in rows34:
        src = alias_to_source.get(r["source_id"], r["source_id"])
        build = identity["active_builds"].get(src)
        pg = int(r["required_locator"][0].split(":")[1])
        quote = next((et["quote"] for et in gold[r["query_id"]].get("evidence_targets", [])
                      if et["target_id"] == r["target_id"]), None)
        key = (build, pg)
        page_cache = result["pages"]
        if key not in page_cache:
            units = [u for u in store.get_units(build) if u.status is UnitStatus.KEPT and u.location.page == pg]
            units.sort(key=lambda u: u.ordinal)
            before = "\n".join(u.raw_text for u in units)
            after = "\n".join(u.raw_text for u in reorder_page([u for u in units if u.location.bbox]))
            page_cache[str(key)] = {
                "build": build, "page": pg, "n_units": len(units),
                "before": {"ordinals": [u.ordinal for u in units],
                           "text": before, "norm": norm(before)},
                "after": {"ordinals": [u.ordinal for u in reorder_page([u for u in units if u.location.bbox])],
                          "text": after, "norm": norm(after)},
            }
        pc = page_cache[str(key)]
        cls_before = classify(quote, pc["before"]["text"], pc["before"]["norm"])
        cls_after = classify(quote, pc["after"]["text"], pc["after"]["norm"])
        summary[("before", cls_before)] += 1
        result["targets"].append({
            "query_id": r["query_id"], "target_id": r["target_id"], "page": pg,
            "class_before": cls_before, "class_after": cls_after,
            "norm_hit_before": norm(quote) in pc["before"]["norm"],
            "norm_hit_after": norm(quote) in pc["after"]["norm"],
        })

result["summary"] = {"before": {f"{c}": n for (_, c), n in sorted(summary.items())},
                     "by_target_after": dict(Counter(t["class_after"] for t in result["targets"]))}

out = {"spec": result}
for name, value in result.items():
    out[name] = value
path = HERE / "remediation-repro.json"
raw = (json.dumps(out, ensure_ascii=False, indent=2) + "\n").encode()
# NOTE: remediation-repro.json is a working (non-frozen) repro artifact, not a chain
# event; rewrite is allowed so the prototype can be re-run while iterating.
path.write_bytes(raw)
print(json.dumps({"before": out["summary"]["before"], "by_target_after": out["summary"]["by_target_after"]},
                 ensure_ascii=False, indent=2))
print("company-001 p1 check:")
for k, v in out["pages"].items():
    b, a = out["pages"][k]["before"]["ordinals"], out["pages"][k]["after"]["ordinals"]
    if b != a:
        print("  page", k, "B before", b, "A after", a)