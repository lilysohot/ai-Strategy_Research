"""B5-A 反事实探针（只读）：金标 e2 的 `col:` 改成哪个值才可能 matched。

问题：industry-002/e2（R32 × 2026E产能（配额） = 28.5）、industry-003/e2（尿素 × 2026E产能 = 8068.0）
的值经原文核实正确，但 `col:` 写作人工合成列名，机器不可派生。本探针不改任何冻结件，
只在**产品读取路径**（`svc.search_bands`）上 dump 该两题证据里实际存在的 locator token，
回答三件事：
  1. 承载 quote 的证据，其 locator 是什么（能不能同时给出 page/row/col）；
  2. 证据里到底有没有 `row:R32` / `row:尿素`；
  3. 若有，它旁边的 `col:` token 是什么 ⇒ 这就是金标应改写成的可派生值。

口径：产品路径（`RANK_LEXEME_PRUNE` 默认 on）+ 与 b5/f3b 同 OR 查询串；只读 PG、0 model calls、不写库。
用法： uv run python e2_col_probe.py [--no-write]
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path("/home/administrator/FrontierAgent").resolve()
INGEST = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild"
AUDITS = INGEST / "audits"
I33 = AUDITS / "20260920-i33-calibration"
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(I33))

TARGETS = {"industry-002": "e2", "industry-003": "e2"}
NON_SEMANTIC_FIELDS = ("generated_at",)


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _semantic_equal(old, new) -> bool:
    if json.dumps(old, sort_keys=True, default=str) == json.dumps(new, sort_keys=True, default=str):
        return True
    o = {k: v for k, v in old.items() if k not in NON_SEMANTIC_FIELDS} if isinstance(old, dict) else old
    n = {k: v for k, v in new.items() if k not in NON_SEMANTIC_FIELDS} if isinstance(new, dict) else new
    return json.dumps(o, sort_keys=True, default=str) == json.dumps(n, sort_keys=True, default=str)


def write_once(name: str, value) -> None:
    path = HERE / name
    raw = (json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n").encode()
    if path.exists():
        old = json.loads(path.read_text(encoding="utf-8"))
        if _semantic_equal(old, value):
            print(f"[write-once] {name} 语义逐字段一致（仅 {NON_SEMANTIC_FIELDS} 不同）→ 保留原产物字节")
            return
        diff = sorted({k for k in set(old) | set(value)
                       if k not in NON_SEMANTIC_FIELDS and old.get(k) != value.get(k)})
        raise RuntimeError(f"write-once conflict: {name}; 差异字段={diff}")
    path.write_bytes(raw)
    print(f"[write-once] {name} 写入 {path}")


def main() -> int:
    import psycopg

    from plugins.corpus.preparation.chunk import normalize_search_text
    from plugins.corpus.preparation.search_pg import _check_target
    from plugins.corpus.scoring import gold_from_records
    from plugins.corpus.service import CorpusService

    ap = argparse.ArgumentParser()
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args()

    release = load_module("i31_region_release", AUDITS / "20260920-i31-region-review/release.py")
    dsn = release.connect()
    loader = load_module("i33_scoring_loader", INGEST / "i3s2_scoring_input.py")
    records = loader.load_scoring_input(INGEST / "i3-2/scoring-input-manifest.json")
    questions = gold_from_records(records)
    svc = CorpusService(dsn)
    LIMIT = 2000

    with psycopg.connect(dsn, autocommit=True) as conn:
        _check_target(conn, "i2_sandbox_corpus")

    def or_query(c0, q) -> str:
        lexemes = c0.execute(
            "SELECT tsvector_to_array(to_tsvector('zhcfg', %s))",
            (normalize_search_text(q.question),)).fetchone()[0]
        return " OR ".join('"' + t.replace('"', " ") + '"' for t in lexemes)

    report: dict = {
        "artifact": "b5-e2-col-probe",
        "generated_at": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc).astimezone().isoformat(timespec="seconds"),
        "corpus": "i2_sandbox_corpus active publications",
        "mode": "产品路径 svc.search_bands；只读、0 model calls、不写库；不改任何冻结件",
        "per_query": {},
    }

    with psycopg.connect(dsn, autocommit=True) as c0:
        for q in questions:
            tid = TARGETS.get(q.query_id)
            if not tid:
                continue
            t = next((x for x in q.evidence_targets if x.target_id == tid), None)
            if t is None:
                continue
            docs, _cov = svc.search_bands(or_query(c0, q), limit=LIMIT)

            evs: list[tuple[str, tuple[str, ...]]] = []
            for doc in docs:
                for band_items in doc.chunks_by_band:
                    texts = [it.text for it in band_items]
                    pages = sorted({p for it in band_items for p in it.pages})
                    if texts:
                        evs.append(("\n".join(texts), tuple(f"page:{p}" for p in pages)))
                for c in doc.cells:
                    loc = ([f"page:{c.page}"] if c.page is not None else []) + \
                          [f"row:{c.row}", f"col:{c.col}"]
                    evs.append((c.text, tuple(loc)))

            quote = t.quote
            carrying = [list(loc) for text, loc in evs if quote in text]
            row_tok = next((tok for tok in t.locator if tok.startswith("row:")), None)
            with_row = [list(loc) for _text, loc in evs if row_tok and row_tok in loc]
            col_tokens = sorted({tok for _text, loc in evs for tok in loc if tok.startswith("col:")})

            # 反事实：把 locator 的 col 换成证据里真实存在的每个候选，看是否满足 matches 的 locator 条件
            fixed = [tok for tok in t.locator if not tok.startswith("col:")]
            candidates = []
            for cand in col_tokens:
                need = set(fixed) | {cand, row_tok} if row_tok else set(fixed) | {cand}
                if all(need <= set(loc) for _text, loc in [] ):  # 占位，实际逐条判定见下
                    pass
                ok = any(need <= set(loc) and quote in text for text, loc in evs)
                if ok:
                    candidates.append(cand)

            report["per_query"][q.query_id] = {
                "target_id": tid,
                "quote": quote,
                "locator_current": list(t.locator),
                "col_current": next((tok for tok in t.locator if tok.startswith("col:")), None),
                "n_evidence": len(evs),
                "evidence_locators_carrying_quote": carrying,
                "evidence_locators_with_row_token": with_row,
                "row_token": row_tok,
                "col_tokens_in_evidence": col_tokens,
                "derivable_col_candidates": candidates,
                "verdict": ("可派生（改 col 后 locator 条件可满足）" if candidates
                            else "不可派生（证据里没有能同时满足 page/row/col 且承载 quote 的证据）"),
            }

    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not args.no_write:
        write_once("e2-col-probe.json", report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
