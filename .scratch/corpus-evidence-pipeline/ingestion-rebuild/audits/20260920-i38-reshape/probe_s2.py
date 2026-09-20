"""S2 探针：验证 table_row 单元结构可否派生 row:/col: 标签（只读，不写产物）。

核查目标：
1. fetched 表格 chunk 内 table_row 单元 raw_text 与 cells 的切分对齐（split 长度 == cells 长度）；
2. 同 chunk 内是否表头行 + 数据行同现；
3. 用单元格网格派生 row:/col: 标签，并与 gold locator token（row:每股收益/col:2026E 等）比对；
4. 统计每 build 的 chunk 总数（评估 S3 全量回填的代价）。
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
BASE = HERE.parents[1]
I33 = BASE / "audits/20260920-i33-calibration"
I37 = BASE / "audits/20260920-i37-fullchain-backtest"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(I33))


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def norm(s: object) -> str:
    return "".join(ch for ch in s if not ch.isspace()) if isinstance(s, str) else ""


def main() -> int:
    release = load_module("i31_region_release", BASE / "audits/20260920-i31-region-review/release.py")
    dsn = release.connect()
    import psycopg
    from plugins.corpus.preparation.search_pg import _check_target
    from plugins.corpus.preparation.read_pg import fetch_verbatim, build_handle, chunk_locator

    report: dict = {"builds": {}, "cases": []}

    with psycopg.connect(dsn, autocommit=True) as conn:
        _check_target(conn, "i2_sandbox_corpus")
        sources = dict(conn.execute(
            "SELECT source_id, active_build_id FROM corpus.corpus_publications "
            "WHERE active_build_id IS NOT NULL").fetchall())

        # 每 build chunk 总数（S3 全量回填代价）
        for src, build_id in sources.items():
            n = conn.execute(
                "SELECT count(*) FROM corpus.corpus_chunks WHERE build_id = %s", (build_id,)
            ).fetchone()[0]
            report["builds"][src] = {"build_id": build_id, "chunks": int(n)}

        def page_table_chunks(build_id: str, page: int) -> list[str]:
            rows = conn.execute(
                "SELECT DISTINCT c.chunk_id FROM corpus.corpus_chunks c "
                "JOIN corpus.corpus_units u ON u.build_id = c.build_id AND u.unit_id = ANY(c.unit_refs) "
                "WHERE c.build_id = %s AND u.location->>'page' = %s "
                "AND jsonb_typeof(u.location->'cells') = 'array' "
                "ORDER BY c.chunk_id", (build_id, str(page))).fetchall()
            return [str(r[0]) for r in rows]

        def table_units(chunk: object) -> list[dict]:
            out = []
            for u in chunk.units:
                if not u.cells:
                    continue
                parts = u.raw_text.split("\n")
                out.append({
                    "unit_id": u.unit_id, "page": u.page, "raw_text": u.raw_text,
                    "cells": [list(c) for c in u.cells],
                    "split_aligned": len(parts) == len(u.cells),
                    "split_len": len(parts),
                })
            return out

        def derive_grid(units: list[dict], page: int) -> dict:
            """从对齐的 table 单元派生 (page, row, col) -> text 网格。"""
            grid: dict[tuple[int, int], str] = {}
            bad = []
            for u in units:
                if u["page"] != page or not u["split_aligned"]:
                    bad.append(u["unit_id"])
                    continue
                for (r, c), text in zip(u["cells"], u["raw_text"].split("\n")):
                    grid[(r, c)] = text
            return grid, bad

        def labels_for(grid: dict) -> dict:
            if not grid:
                return {"header_row": None, "rows": {}, "cols": {}}
            header_row = min(r for r, _ in grid)
            row_min: dict[int, int] = {}
            for r, c in grid:
                row_min[r] = c if r not in row_min else min(row_min[r], c)
            return {
                "header_row": header_row,
                "rows": {r: grid.get((r, row_min[r])) for r in sorted(row_min)},
                "cols": {c: grid.get((header_row, c)) for c in sorted({c for _, c in grid})},
            }

        cases = [
            ("company-003", "2026-09-06_dddc7cd0", 20),
            ("industry-002", "2026-08-13_174b6462", 10),
        ]
        # industry-002 的 source_id 需解析（gold alias 形如 2026-09-06_xxx）
        for qid, alias_suffix, page in cases:
            suffix = alias_suffix.rsplit("_", 1)[-1]
            matches = [s for s in sources if s.startswith(suffix)]
            if not matches:
                print("NO MATCH for", qid, repr(suffix), "sources:", list(sources), file=sys.stderr)
            src = matches[0]
            build_id = sources[src]
            chunks = page_table_chunks(build_id, page)
            entry = {"query_id": qid, "source": src, "build": build_id[:12], "page": page,
                     "table_chunks_on_page": chunks, "chunk_detail": []}
            for cid in chunks[:4]:
                chunk = fetch_verbatim(dsn, build_handle(build_id), chunk_locator(cid))
                units = table_units(chunk)
                grid, bad = derive_grid(units, page)
                labels = labels_for(grid)
                entry["chunk_detail"].append({
                    "chunk_id": cid,
                    "kind": chunk.kind,
                    "table_units": units[:8],
                    "units_on_page_mismatch": bad,
                    "header_row": labels.get("header_row"),
                    "row_labels": {k: labels["rows"].get(k) for k in sorted(labels["rows"])},
                    "col_labels": {k: labels["cols"].get(k) for k in sorted(labels["cols"])},
                })
            report["cases"].append(entry)

        # gold locator 标签比对
        loader = load_module("i33_scoring_loader", BASE / "i3s2_scoring_input.py")
        records = loader.load_scoring_input(BASE / "i3-2/scoring-input-manifest.json")
        targets = []
        for rec in records:
            for t in rec.get("evidence_targets") or []:
                toks = list(t.get("locator") or ())
                if any(tok.startswith("row:") or tok.startswith("col:") for tok in toks):
                    targets.append({"query_id": rec["query_id"], "target_id": t["target_id"],
                                    "quote": t["quote"], "locator": toks})
        report["gold_row_col_targets"] = targets

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
