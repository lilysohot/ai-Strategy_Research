"""Verify a sample of `correct_extra` candidates against the source corpus text.

Zero model calls; read-only. For each candidate we take its own ``evidence.quote``
(or ``text`` when no quote is present), look the fragment up in
``corpus.corpus_units.raw_text``, and print the surrounding source context so a human
adjudicator can decide whether the candidate is supported (``correct_extra``) or not
(``incorrect``).

Usage:
    uv run python <this file> [--ids itm_xxx,itm_yyy] [--limit N]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CLAIMS = HERE.parents[2]
WORKSHEET = CLAIMS / "adjudication" / "worksheet.json"
REPO_ROOT = HERE.parents[5]
sys.path.insert(0, str(REPO_ROOT))


def norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def suspicious(rows: list[dict]) -> list[dict]:
    """Rank correct_extra records by cheap, mechanical suspicion signals."""
    seen: dict[str, int] = {}
    for r in rows:
        t = norm(r["original_candidate"].get("text", ""))
        seen[t] = seen.get(t, 0) + 1
    out = []
    for r in rows:
        t = r["original_candidate"].get("text", "") or ""
        q = (r.get("evidence") or {}).get("quote", "") or ""
        flags = []
        if not q:
            flags.append("无引文")
        if len(norm(t)) < 14:
            flags.append("文本过短")
        if seen.get(norm(t), 0) > 1:
            flags.append("内容重复")
        if flags:
            out.append((len(flags), r, flags))
    out.sort(key=lambda x: -x[0])
    return [r for _, r, _ in out]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", default="")
    ap.add_argument("--limit", type=int, default=15)
    args = ap.parse_args()

    import psycopg

    ws = json.loads(WORKSHEET.read_text(encoding="utf-8"))
    rows = [r for r in ws["records"] if r["judgement"] == "correct_extra"]

    if args.ids:
        wanted = {i.strip() for i in args.ids.split(",") if i.strip()}
        targets = [r for r in rows if r["candidate_id"] in wanted]
    else:
        targets = suspicious(rows)[: args.limit]

    conn = psycopg.connect(
        "postgresql://postgres:postgres@127.0.0.1:5432/e6_holdout_corpus", autocommit=True
    )
    report = []
    for r in targets:
        cand = r["original_candidate"]
        text = cand.get("text", "") or ""
        quote = (r.get("evidence") or {}).get("quote", "") or ""
        probe_src = norm(quote or text)
        matched_probe, ctx, found = "", "", False
        for size in (len(probe_src), 16, 12, 8, 6, 4):
            if size < 4 or size > len(probe_src):
                continue
            probe = probe_src[:size]
            hit = conn.execute(
                "select unit_id, raw_text from corpus.corpus_units "
                "where replace(raw_text, ' ', '') like %s limit 1",
                (f"%{probe}%",),
            ).fetchone()
            if hit:
                found, matched_probe = True, probe
                raw = hit[1]
                i = norm(raw).find(probe)
                ctx = raw[max(0, (i if i >= 0 else 0) - 120) : (i if i >= 0 else 0) + 200]
                break
        report.append(
            {
                "candidate_id": r["candidate_id"],
                "candidate_text": text,
                "evidence_quote": quote,
                "quote_found_in_source": found,
                "matched_probe": matched_probe,
                "source_context": ctx,
                "current_judgement": r["judgement"],
                "current_reason": r.get("reason", ""),
            }
        )
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
