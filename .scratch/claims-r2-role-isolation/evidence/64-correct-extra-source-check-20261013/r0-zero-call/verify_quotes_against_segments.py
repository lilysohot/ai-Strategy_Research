"""Verify every adjudicated candidate's evidence quote against the source segments.

The extraction run's own input is the only in-reach copy of the source text: the
snapshot that fed the run has 0 rows in the corpus DB, so we read the 10 source
segments carried by the v6 run payload
(``32-…/live/treatment-store/industrial-fulian-md/objects/sha256/51/5164a8…``).

Zero model calls; read-only. Reports, per candidate:
  * whether the quote literally occurs in a source segment (normalised),
  * which segment, and whether that segment is the ``最坏情景`` hypothetical block,
  * the candidate's own type/factuality/condition labels for cross-checking.

Usage:
    uv run python <this file> [--ids itm_a,itm_b] [--json out.json]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CLAIMS = HERE.parents[2]
REPO_ROOT = HERE.parents[5]
sys.path.insert(0, str(REPO_ROOT))

WORKSHEET = CLAIMS / "adjudication" / "worksheet.json"
WORKBENCH = CLAIMS / "evidence" / "38-gate33-workbench-rebuild-20261012" / "r0-zero-call" / "workbench-v2.json"
SEGMENTS = (
    CLAIMS
    / "evidence"
    / "32-items-v6-reasoning-refreeze-20261011"
    / "live"
    / "treatment-store"
    / "industrial-fulian-md"
    / "objects"
    / "sha256"
    / "51"
    / "5164a8c10df8cbad70a04cd6b223c8ff6aaef2f9c74e43523596734ec9b040c0.json"
)

HYPOTHETICAL_MARKERS = ("最坏情景", "次坏", "再坏")


def norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", default="")
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    ws = json.loads(WORKSHEET.read_text(encoding="utf-8"))
    wb = json.loads(WORKBENCH.read_text(encoding="utf-8"))
    payload = json.loads(SEGMENTS.read_text(encoding="utf-8"))
    segs = payload["structure"]["segments"]

    by_id = {r["candidate_id"]: r for r in (wb.get("candidates") or [])}
    norm_segs = [(i, s.get("segment_id", ""), norm(s.get("text", ""))) for i, s in enumerate(segs)]
    seg_meta = {}
    for i, s in enumerate(segs):
        seg_meta[i] = {
            "segment_id": s.get("segment_id", ""),
            "hypothetical": any(m in (s.get("text") or "")[:12] for m in HYPOTHETICAL_MARKERS),
        }

    rows = ws["records"]
    if args.ids:
        wanted = {i.strip() for i in args.ids.split(",") if i.strip()}
        rows = [r for r in rows if r["candidate_id"] in wanted]

    out = []
    for r in rows:
        cid = r["candidate_id"]
        cand = r["original_candidate"]
        quote = (r.get("evidence") or {}).get("quote", "") or cand.get("evidence_quote", "") or ""
        nq = norm(quote)
        seg_idx = None
        for i, _, ns in norm_segs:
            if nq and nq in ns:
                seg_idx = i
                break
        wb_row = by_id.get(cid, {})
        out.append(
            {
                "candidate_id": cid,
                "judgement": r["judgement"],
                "candidate_text": cand.get("text", ""),
                "evidence_quote": quote,
                "quote_in_source": seg_idx is not None,
                "segment": seg_idx,
                "segment_hypothetical": seg_meta.get(seg_idx, {}).get("hypothetical") if seg_idx is not None else None,
                "semantic_type": wb_row.get("semantic_type"),
                "factuality": wb_row.get("factuality"),
                "condition": wb_row.get("condition"),
                "temporal_frame": wb_row.get("temporal_frame"),
            }
        )

    hits = sum(1 for o in out if o["quote_in_source"])
    print(f"核对 {len(out)} 条：引文在原文命中 {hits} / 未命中 {len(out) - hits}")
    if args.json:
        Path(args.json).write_text(
            json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
        )
    else:
        print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
