"""只读：新 build 中 glp1 / cxo-h1 / wuqi 等目标引文的实际保留位置。"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))

import dotenv  # noqa: E402

dotenv.load_dotenv(ROOT / ".env")
os.environ["CORPUS_TARGET_DB"] = "e6_holdout_corpus"
os.environ.pop("PGOPTIONS", None)

import psycopg  # noqa: E402
from psycopg.conninfo import conninfo_to_dict, make_conninfo  # noqa: E402

from plugins.corpus.service import dsn  # noqa: E402

d = json.loads((HERE / "e6-holdout-build.json").read_text(encoding="utf-8"))
BUILD = next(s["build_id"] for s in d["sources"] if s["sample_id"] == "holdout-industry-006")

PACKET = json.loads((HERE / "e6-human-gap-review-packet.json").read_text(encoding="utf-8"))
mat = next(m for m in PACKET["materials"] if m["sample_id"] == "holdout-industry-006")
WS = re.compile(r"\s+")


def norm(s):
    return WS.sub("", s or "")


def main() -> int:
    print("build:", BUILD[:16])
    target = make_conninfo(**{**conninfo_to_dict(dsn()), "dbname": "e6_holdout_corpus"})
    conn = psycopg.connect(target)
    rows = conn.execute(
        "select unit_id, kind, status, raw_text, location from corpus.corpus_units "
        "where build_id = %s and status='kept'",
        (BUILD,),
    ).fetchall()
    for tgt in mat["blocked_targets"]:
        qn = norm(tgt.get("expected_quote") or "")
        full = [(r[0], r[4].get("page"), len(r[3])) for r in rows if qn and qn in norm(r[3] or "")]
        print(f"target {tgt['target_id']}: 整条命中 {full}")
        if not full:
            toks = [t for t in WS.split(tgt.get("expected_quote") or "") if len(norm(t)) >= 4][:4]
            hits = [(r[0], r[4].get("page"), len(r[3])) for r in rows
                    if any(tok and norm(tok) in norm(r[3] or "") for tok in toks)]
            print(f"   token 命中 {len(hits)}: {hits[:6]}")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
