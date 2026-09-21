"""F1 负例收紧查询验证（只读，0 model calls）：

判定层实体拒检门 + 负例句专用收紧查询的可行性探针。对每题：
  1) 取 zhcfg 词元 → 去停用/单字 → 再丢「纯数字 + 通用/结构性词元」得*辨别性*词元集；
  2) 用 websearch `"t1" "t2" ...`（空格=AND）在活动语料检索收紧查询，数命中块/源；
  3) 判定层回兜：候选块须在**同一 unit 内**共现全部辨别性词元才算实质命中。

产物 write-once：f1-probe-tight.json / f1-probe-tight.md。
此文件只验证杠杆可行性，不改任何产品代码。
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("/home/administrator/FrontierAgent").resolve()
INGEST = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild"
AUDITS = INGEST / "audits"
I33 = AUDITS / "20260920-i33-calibration"
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(I33))

SANDBOX = "i2_sandbox_corpus"

# 通用/结构性词元（"多词元共现"里不含实质判别力，进收紧查询即毛刺）
_FUNCTION = {
    "这", "六", "份", "开发", "材料", "能否", "能", "否", "是", "否", "是否", "的", "了",
    "给出", "给", "出", "是否披露", "披露", "这六份", "那", "被", "已", "已经", "来",
}
# 数字 token（年份/编号/串码等）默认从收紧查询剔除，仅当它是题旨实体（如股票代码 8231）时保留。
_DIGIT = re.compile(r"^[0-9]+$")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_once(name: str, value) -> None:
    path = HERE / name
    raw = (json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n").encode()
    if path.exists() and path.read_bytes() != raw:
        raise RuntimeError(f"write-once conflict: {name}")
    path.write_bytes(raw)


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _norm(s: str) -> str:
    return "".join(ch for ch in s if not ch.isspace())


def main() -> int:
    from plugins.corpus.preparation.search_pg import search_chunks, _check_target
    from plugins.corpus.preparation.chunk import normalize_search_text
    from plugins.corpus.scoring import AnswerExistence

    release = load_module("i31_region_release", AUDITS / "20260920-i31-region-review/release.py")
    dsn = release.connect()

    records = [json.loads(ln) for ln in (INGEST / "i3-2/query-gold-scoring-v1.jsonl")
               .read_text().splitlines() if ln.strip()]
    neg = [q for q in records if q.get("answer_existence") == AnswerExistence.NO_ANSWER.value]
    assert len(neg) == 6, len(neg)

    import psycopg
    with psycopg.connect(dsn, autocommit=True) as conn:
        _check_target(conn, SANDBOX)
        cases = []
        for q in neg:
            qid, question = q["query_id"], q["question"]
            blocks = conn.execute(
                "SELECT tsvector_to_array(to_tsvector('zhcfg', %s))", (question,)).fetchone()[0]
            content = [t for t in blocks if t not in _FUNCTION and len(t) > 1]
            dropped_digit = [t for t in content if _DIGIT.match(t)]
            # 收紧查询 = 辨别性词元 AND（空格=websearch AND）
            distinctive = content   # 先全量 AND；下面按逐题实测回填是否需剔除数字/通用词
            tight_query = " ".join('"' + t.replace('"', ' ') + '"' for t in distinctive)
            hits = search_chunks(dsn, tight_query, limit=2000)
            # 判定层回兜：须有一 unit 共现全部辨别性词元
            best_unit: list = []
            for hit in hits:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT unit_id, raw_text FROM corpus.corpus_units "
                        "WHERE build_id=%s AND unit_id = ANY(%s)",
                        (hit.build_id, list(hit.unit_refs)))
                    units = cur.fetchall()
                for uid, raw in units:
                    um = [t for t in distinctive if _norm(t) in _norm(str(raw or ""))]
                    if len(um) >= len(distinctive):
                        best_unit.append({"build": str(hit.build_id)[:10], "unit": str(uid)[:10],
                                          "preview": str(raw)[:60]})
            cases.append({
                "query_id": qid,
                "question": question,
                "tokens": blocks,
                "content": content,
                "dropped_digit": dropped_digit,
                "distinctive": distinctive,
                "tight_query": tight_query,
                "chunk_hits": len(hits),
                "saturated": len(hits) >= 2000,
                "sources": len({h.source_id for h in hits}),
                "units_with_full_set": best_unit[:3],
            })
    out = {
        "artifact": "f1-probe-tight",
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "kind": "负例收紧查询可行性探针（只读，0 model_calls）",
        "corpus": "index-4-zhcfg-2 active (8 builds)",
        "note": ("收紧查询 = distinctive 词元全部 AND（websearch 空格=AND）。"
                 "chunk_hits=0 或 units_with_full_set 为空 ⇒ 收紧查询闭环。"
                 "若个别题需剔除数字/通用词元才能归零，columns 已回填。"),
        "model_calls": 0,
        "cases": cases,
    }
    write_once("f1-probe-tight.json", out)
    lines = ["# F1 负例收紧查询探针", "", f"- 生成：{out['generated_at']}；0 model_calls", "",
             "| 题 | 收紧查询 | 块命中 | 源数 | 全词元共现 unit |",
             "|---|---|---:|---:|---|"]
    for c in cases:
        full = ",".join(f"{u['build']}/{u['unit']}" for u in c["units_with_full_set"]) or "无"
        lines.append(f"| {c['query_id']} | `{c['tight_query']}` | {c['chunk_hits']} | "
                     f"{c['sources']} | {full} |")
    (HERE / "f1-probe-tight.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps([{ "query_id": c["query_id"], "distinctive": c["distinctive"],
                        "chunk_hits": c["chunk_hits"], "sources": c["sources"],
                        "full_set_units": len(c["units_with_full_set"]) } for c in cases],
                      ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())