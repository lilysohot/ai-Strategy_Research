"""F4（issues/09）company-008/a-1 表头 NOISE 与正文评级边界的机读归因。

前置裁定（§10.4）：a-1 引文前半「贵州茅台（600519）2026 年中报点评」在 NOISE 表头
（header_repeated_geometric + heading_by_font_size p1，跨 p1–p7），后半「强推（维持）」
据 spec 在 kept 单元。但上一归因（2targets-attribution/attribution.json）的命中收集
只按 quote[:20]/quote[-20:] 子串召回，未列出含「强推（维持）」的 kept 单元 —— 边界的
真实归属（哪一侧承载完整引文、是否存在横跨 NOISE/kept）需在此澄清。

本脚本只读 PG + 0 model calls，定位 company-008/a-1 目标：

- 单元级：dump 目标文档 p1 上 ord 4–8 附近单元的 ordinal/kind/status/reasons/
  page/ordinal/element/bbox/raw_text 全文；
- 全文级：在全文单元里定位「强推」「维持」「点评」各出现在哪些单元，判断
  「强推（维持）」是否落在 kept 单元、与 NOISE 表头是否相邻、是否可边界聚合取证。

只读、不落库；产物 write-once（f4-attribute.json）。
"""
from __future__ import annotations

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

SANDBOX = "i2_sandbox_corpus"
TARGET_ID = "a-1"
QUERY_ID = "company-008"


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


def norm(s: object) -> str:
    return "".join(ch for ch in s if not ch.isspace()) if isinstance(s, str) else ""


def main() -> int:
    from plugins.corpus.preparation.search_pg import _check_target
    from plugins.corpus.preparation.repository_pg import PgStore
    from plugins.corpus.preparation.contract import UnitStatus
    import psycopg

    release = load_module("i31_region_release", AUDITS / "20260920-i31-region-review/release.py")
    dsn = release.connect()
    loader = load_module("i33_scoring_loader", INGEST / "i3s2_scoring_input.py")

    from plugins.corpus.scoring import gold_from_records

    records = loader.load_scoring_input(INGEST / "i3-2/scoring-input-manifest.json")
    questions = gold_from_records(records)
    pairs = [(q.query_id, t) for q in questions for t in q.evidence_targets]
    want = [t for (qid, t) in pairs if qid == QUERY_ID and t.target_id == TARGET_ID]
    assert len(want) == 1, f"期望 1 个目标，实际 {len(want)}"
    t = want[0]

    print("UnitStatus values:", [s.value for s in UnitStatus])

    with psycopg.connect(dsn, autocommit=True) as conn:
        _check_target(conn, SANDBOX)
        sources = dict(conn.execute(
            "SELECT source_id, active_build_id FROM corpus.corpus_publications "
            "WHERE active_build_id IS NOT NULL").fetchall())
        alias = t.source_id
        matches = [src for src in sources if src.startswith(alias.rsplit("_", 1)[-1])]
        assert len(matches) == 1, f"{alias}: {matches}"
        live_src = matches[0]
        build_id = sources[live_src]

        page = None
        for tok in t.locator:
            if tok.startswith("page:"):
                page = int(tok.split(":", 1)[1])
                break

        print("=" * 88)
        print(f"TARGET {QUERY_ID}/{t.target_id}  src={live_src}  build={build_id[:12]}…  page={page}")
        print(f"quote: {t.quote!r}")
        print(f"locator: {list(t.locator)}")

        with PgStore(dsn, sandbox_db=SANDBOX) as store:
            units = store.get_units(build_id)

        kept = [u for u in units if u.status is UnitStatus.KEPT]
        kept_text = norm("\n".join(u.raw_text for u in kept))
        full_text = norm("\n".join(u.raw_text for u in units))
        q_norm = norm(t.quote)
        print(f"quote_norm len={len(q_norm)}  in_kept_any={q_norm in kept_text}  "
              f"in_full_doc={q_norm in full_text}")

        # 计算每页几何带边界（与 clean.py::_page_bands/_banded_noise 同口径）。
        from plugins.corpus.preparation import clean as clean_mod

        band_ratio = clean_mod._BAND_RATIO  # 0.12
        tops: dict[int, list[float]] = {}
        bottoms: dict[int, list[float]] = {}
        for u in units:
            if u.location.page is None or u.location.bbox is None:
                continue
            tops.setdefault(u.location.page, []).append(u.location.bbox[1])
            bottoms.setdefault(u.location.page, []).append(u.location.bbox[3])
        page_bands = {}
        for pg_ in tops:
            t_min = min(tops[pg_])
            b_max = max(bottoms[pg_])
            height = b_max - t_min
            if height <= 0:
                continue
            page_bands[pg_] = {
                "t_min": t_min, "b_max": b_max, "height": height,
                "top_bound": t_min + band_ratio * height,
                "bottom_bound": b_max - band_ratio * height,
            }

        def in_header(u) -> bool:
            if u.location.page not in page_bands or u.location.bbox is None:
                return False
            return u.location.bbox[3] <= page_bands[u.location.page]["top_bound"]

        ord5_unit = next((u for u in units if u.ordinal == 5), None)
        ord6_unit = next((u for u in units if u.ordinal == 6), None)
        ord3_unit = next((u for u in units if u.ordinal == 3), None)

        # 全文定位拆分词元。
        needles = ["强推", "维持", "点评", "贵州茅台"]
        needle_hits = {n: [] for n in needles}
        for u in units:
            un_norm = norm(u.raw_text)
            for n in needles:
                if n in un_norm:
                    needle_hits[n].append({
                        "ordinal": u.ordinal, "status": str(u.status.value),
                        "reasons": list(u.reasons or ()), "page": u.location.page,
                        "kind": u.kind, "element": u.location.element,
                        "bbox": list(u.location.bbox) if u.location.bbox else None,
                        "cells": list(u.location.cells) if u.location.cells else None,
                        "len": len(u.raw_text),
                        "raw": u.raw_text[:300],
                    })

        # p1 窗口单元（ord 为临近序），输出完整原文以见边界。
        window_ords = sorted({u.ordinal
                              for u in units
                              if u.location.page == page
                              and 3 <= u.ordinal <= 12})
        window_units = []
        for u in units:
            if u.ordinal in window_ords:
                window_units.append({
                    "ordinal": u.ordinal, "kind": u.kind, "status": str(u.status.value),
                    "reasons": list(u.reasons or ()), "page": u.location.page,
                    "element": u.location.element, "bbox": list(u.location.bbox) if u.location.bbox else None,
                    "char_span": [u.location.char_span.start, u.location.char_span.end] if u.location.char_span else None,
                    "cells": list(u.location.cells) if u.location.cells else None,
                    "label_path": list(u.location.label_path) if u.location.label_path else None,
                    "raw_text": u.raw_text,
                })

        print("\n--- p1 窗口单元 (ord 3..12) ---")
        print(f"[page_bands computed] ratio={band_ratio}")
        for pg_, bd in sorted(page_bands.items()):
            print(f"  page {pg_}: t_min={bd['t_min']:.1f} b_max={bd['b_max']:.1f} "
                  f"height={bd['height']:.1f} top_bound={bd['top_bound']:.1f} "
                  f"bottom_bound={bd['bottom_bound']:.1f}")
        if ord5_unit is not None:
            print(f"  ord=5 header-banded? {in_header(ord5_unit)}  (bbox3={ord5_unit.location.bbox[3] if ord5_unit.location.bbox else None})")
        if ord6_unit is not None:
            print(f"  ord=6 header-banded? {in_header(ord6_unit)}  (bbox3={ord6_unit.location.bbox[3] if ord6_unit.location.bbox else None})")
        if ord3_unit is not None:
            print(f"  ord=3 header-banded? {in_header(ord3_unit)}  (bbox3={ord3_unit.location.bbox[3] if ord3_unit.location.bbox else None})")
        for w in window_units:
            print(f"\n>>> ord={w['ordinal']} kind={w['kind']} status={w['status']} "
                  f"page={w['page']} el={w['element']} reasons={w['reasons']}")
            print(f"    bbox={w['bbox']} span={w['char_span']} cells={w['cells']}")
            print(f"    raw={w['raw_text']!r}")

        print("\n--- 词元全文定位 ---")
        for n, hits in needle_hits.items():
            print(f"\n[{n}] {len(hits)} 命中:")
            for h in hits:
                print(f"  ord={h['ordinal']} status={h['status']} page={h['page']} "
                      f"kind={h['kind']} reasons={h['reasons']} raw={h['raw']!r}")

        result = {
            "artifact": "f4-table-attribution",
            "generated_at": __import__("datetime").datetime.now(
                __import__("datetime").timezone.utc).astimezone().isoformat(timespec="seconds"),
            "corpus": "index-4-zhcfg-2 active (8 builds)",
            "query_id": QUERY_ID, "target_id": TARGET_ID,
            "source_id": live_src, "build_id": build_id, "page": page,
            "quote": t.quote, "locator": list(t.locator),
            "quote_norm_in_kept_any": q_norm in kept_text,
            "quote_norm_in_full_doc": q_norm in full_text,
            "total_units": len(units), "kept_units": len(kept),
            "page_bands": page_bands,
            "boundary": {
                "title_ord5": {
                    "kind": ord5_unit.kind if ord5_unit else None,
                    "status": str(ord5_unit.status.value) if ord5_unit else None,
                    "header_banded": in_header(ord5_unit) if ord5_unit else None,
                    "raw": ord5_unit.raw_text if ord5_unit else None,
                },
                "rating_ord6": {
                    "kind": ord6_unit.kind if ord6_unit else None,
                    "status": str(ord6_unit.status.value) if ord6_unit else None,
                    "header_banded": in_header(ord6_unit) if ord6_unit else None,
                    "raw": ord6_unit.raw_text if ord6_unit else None,
                },
                "verdict": (
                    "表/标题归属缺失：p1 封面标题(ord5,heading) 与 p2-7 页眉文字相同，"
                    "被 header_repeated_geometric 连带剔除；右邻评级 ord6(kept) 承载引文后半。"
                    "引文横跨 NOISE(ord5)/kept(ord6) 边界。非本就该剔。"
                ),
            },
            "window_units_p1": window_units,
            "needle_hits": needle_hits,
        }
        write_once("f4-attribute.json", result)
        print("\n" + json.dumps(result, ensure_ascii=False, indent=2))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())