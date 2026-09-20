"""Read-only I3-3 root-cause forensics (r39 post-mortem). Never modifies PG.

Reclassifies the 54 missing evidence targets from evidence-diagnosis.json under a
whitespace-normalized quote-containment lens (mirroring gold's own `exact()`), and
dumps the real table structure for the 6 coordinate targets so structural header
resolution can be judged. Outputs i33-rootcause.json (+ print summary). No scoring
change, no gold change, no evidence supplementation.
"""
import json
import re
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
from plugins.corpus.preparation import read_pg

WS = re.compile(r"\s+")


def norm(s: str) -> str:
    # strip ALL whitespace (mirrors gold exact(): needle/haystack filtered by isspace)
    return WS.sub("", s) if isinstance(s, str) else ""


def main() -> None:
    identity = json.loads((HERE / "source-identity-map.json").read_text())
    alias_to_source = {a: s for s, a in identity["aliases"].items()}
    diag = json.loads((HERE / "evidence-diagnosis.json").read_text())
    gold = {r["query_id"]: r for r in
            map(json.loads, (BASE / "i3-2/query-gold-scoring-v1.jsonl").read_text().splitlines())}

    rows = []
    with PgStore(dsn) as store:
        for t in diag["targets"]:
            source = alias_to_source.get(t["source_id"], t["source_id"])
            build = identity["active_builds"].get(source)
            units = tuple(u for u in store.get_units(build) if u.status is UnitStatus.KEPT)
            quote = next((et["quote"] for et in gold[t["query_id"]].get("evidence_targets", [])
                          if et["target_id"] == t["target_id"]), None)
            # full-document text (all units = superset; doc build is immutable)
            doc = read_pg.fetch_document(dsn, read_pg.build_handle(build),
                                         sandbox_db="i2_sandbox_corpus")
            # kept page-joined text (per page), matching diagnosis semantics
            by_page_id = {}
            by_page_norm = {}
            for u in units:
                p = u.location.page if u.location.page is not None else -1
                by_page_id.setdefault(p, []).append(u.raw_text)
                by_page_norm.setdefault(p, []).append(norm(u.raw_text))
            kept_all = "\n".join(u.raw_text for u in units)
            kept_norm_all = norm(kept_all)
            doc_norm_all = norm(doc.text)
            qn = norm(quote)
            kept_norm = qn in kept_norm_all
            doc_norm = qn in doc_norm_all
            kept_bytes = (quote in kept_all) if quote else False
            # page evidence (norm), restricted to required pages if declared
            pages_decl = [tok.split(":", 1)[1] for tok in t["required_locator"] if tok.startswith("page:")]
            page_hits = [p for p in by_page_norm if qn in "".join(by_page_norm[p])]
            if kept_norm and not kept_bytes:
                cls = "present_kept_norm_only"  # retained content, byte-repr mismatch
            elif doc_norm and not kept_norm:
                cls = "present_doc_not_kept"  # dropped by cleaning (image/non-kept)
            elif not doc_norm:
                cls = "absent_in_extraction"  # truly not found in doc build text
            else:
                cls = "present_kept_bytes"  # already byte-present (shouldn't be in 54)
            rows.append({
                "query_id": t["query_id"], "target_id": t["target_id"],
                "prior_cause": t["cause"], "source_id": t["source_id"],
                "required_locator": t["required_locator"],
                "quote": quote, "norm_len": len(qn),
                "kept_bytes": kept_bytes, "kept_norm": kept_norm, "doc_norm": doc_norm,
                "reclass": cls, "kept_pages_norm": sorted(page_hits),
            })

    by_cls = Counter(r["reclass"] for r in rows)
    prior_x_cur = Counter((r["prior_cause"], r["reclass"]) for r in rows)
    orig = Counter(r["prior_cause"] for r in rows)
    print(json.dumps({"reclass": dict(by_cls), "prior": dict(orig),
                      "prior_x_reclass": {f"{a}+{b}": n for (a, b), n in sorted(prior_x_cur.items())}},
                     ensure_ascii=False, indent=2))

    # ---- dump real structure for the 6 coordinate targets ----
    six = [r for r in rows if r["prior_cause"] == "returned_quote_missing_required_locator"]
    grid_dump = {}
    with PgStore(dsn) as store:
        for r in six:
            source = alias_to_source.get(r["source_id"], r["source_id"])
            build = identity["active_builds"].get(source)
            units = tuple(u for u in store.get_units(build) if u.status is UnitStatus.KEPT)
            decl_page = next((tok.split(":", 1)[1] for tok in r["required_locator"] if tok.startswith("page:")), None)
            page = int(decl_page) if decl_page else None
            qn = norm(r["quote"])
            hit = [u for u in units if u.location.page == page and qn in norm(u.raw_text)]
            meta = {"decl_page": page, "quote": r["quote"],
                    "units_hitting": [{"page": u.location.page, "element": u.location.element,
                                       "cells": u.location.cells, "raw": u.raw_text} for u in hit]}
            # all units in the same (page, element) = the table grid
            elems = {u.location.element for u in hit}
            meta["grid"] = []
            for el in elems:
                grid_units = [u for u in units if u.location.page == page and u.location.element == el]
                meta["grid"].append({"element": el, "cells": [
                    {"cells": u.location.cells, "raw": u.raw_text} for u in grid_units]})
            grid_dump[r["query_id"] + "/" + r["target_id"]] = meta
    print("=== 6-coordinate structure dump ===")
    print(json.dumps(grid_dump, ensure_ascii=False, indent=2))

    out = {"note": "Read-only r39 root-cause forensics; whitespace-normalized lens matching gold exact(); "
                   "no scoring/gold/DB change.", "reclass": dict(by_cls), "prior": dict(orig),
           "prior_x_reclass": {f"{a}+{b}": n for (a, b), n in sorted(prior_x_cur.items())},
           "targets": rows, "coordinate_structure": grid_dump}

    def write_once(name: str, value) -> None:
        path = HERE / name
        raw = (json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n").encode()
        if path.exists() and path.read_bytes() != raw:
            raise RuntimeError(f"write-once conflict: {name}")
        path.write_bytes(raw)

    write_once("i33-rootcause.json", out)


if __name__ == "__main__":
    main()