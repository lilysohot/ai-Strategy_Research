"""§10.4 归因裁定：company-007/e1 与 company-008/a-1 在当前活动语料上的真相。

i37 判 `doc_not_kept_clean_stage_loss`（引文在全文存在、只在非 kept 单元），
i42 判 `not_in_doc_unreachable`（全文任意处不逐字出现）——两个结论矛盾。

关键：i42 的漏斗只检查 kept 单元（`in_kept_any`），从未检查**全文**（含非 kept
单元）。故 i42 的 `not_in_doc_unreachable` 命名可能失真。本脚本在**当前活动语料**
（index-4-zhcfg-2，与 band 回测同）上对每目标检查：

- 引文是否逐字出现在 kept 单元（任意页 / 声明页）；
- 引文是否逐字出现在**任一**单元（全文，含 NOISE/OUT_OF_SCOPE/REVIEW_REQUIRED/…）；
- 命中的非 kept 单元逐一列出（status/reasons/page/ordinal）。

裁定规则（§10.4）：
- 全文存在 + kept 缺失 ⇒ **i37 成立**：清洗剔除（票 05 有活干）；
- 全文任意处都不存在 ⇒ **i42 成立**：金标改写/重建，管线不可达（票 05 白做）。

只读 PG + 0 model calls；产物 write-once。
"""
from __future__ import annotations

import hashlib
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
TARGETS = {("company-007", "e1"), ("company-008", "a-1")}


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
    from plugins.corpus.scoring import gold_from_records
    loader = load_module("i33_scoring_loader", INGEST / "i3s2_scoring_input.py")
    records = loader.load_scoring_input(INGEST / "i3-2/scoring-input-manifest.json")
    questions = gold_from_records(records)
    pairs = [(q.query_id, t) for q in questions for t in q.evidence_targets]
    want = [t for (qid, t) in pairs if (qid, t.target_id) in TARGETS]
    assert len(want) == 2, f"期望 2 个目标，实际 {len(want)}"
    target_qid = {t.target_id: next(qid for qid, x in pairs if x is t) for t in want}

    print("UnitStatus values:", [s.value for s in UnitStatus])

    with psycopg.connect(dsn, autocommit=True) as conn:
        _check_target(conn, SANDBOX)
        sources = dict(conn.execute(
            "SELECT source_id, active_build_id FROM corpus.corpus_publications "
            "WHERE active_build_id IS NOT NULL").fetchall())
        print(f"active builds: {len(sources)}")
        alias_to_source = {}
        for t in want:
            alias = t.source_id
            matches = [src for src in sources if src.startswith(alias.rsplit("_", 1)[-1])]
            assert len(matches) == 1, f"{alias}: {matches}"
            alias_to_source[alias] = matches[0]

        findings = []
        for t in want:
            live_src = alias_to_source[t.source_id]
            build_id = sources[live_src]
            quote = norm(t.quote)
            page = None
            for tok in t.locator:
                if tok.startswith("page:"):
                    page = int(tok.split(":", 1)[1])
                    break
            print("=" * 88)
            print(f"TARGET {target_qid[t.target_id]}/{t.target_id}  "
                  f"src={live_src}  build={build_id[:12]}…  page={page}")
            print(f"quote: {t.quote!r}")

            with PgStore(dsn, sandbox_db=SANDBOX) as store:
                units = store.get_units(build_id)
            kept = [u for u in units if u.status is UnitStatus.KEPT]
            kept_text = norm("\n".join(u.raw_text for u in kept))
            in_kept_any = quote in kept_text
            page_kept = [u for u in kept if u.location.page == page]
            page_kept_text = norm("\n".join(u.raw_text for u in page_kept))
            in_kept_declared_page = quote in page_kept_text
            full_text = norm("\n".join(u.raw_text for u in units))
            in_full_doc = quote in full_text

            hits = []
            for u in units:
                un = norm(u.raw_text)
                frag = [p for p in (quote[:20], quote[-20:]) if p and p in un]
                if frag:
                    hits.append({"ordinal": u.ordinal, "status": str(u.status.value),
                                 "reasons": list(u.reasons or ()), "page": u.location.page,
                                 "element": u.location.element,
                                 "fragment": "首尾" if len(frag) == 2 else frag[0],
                                 "len": len(u.raw_text),
                                 "raw_head": u.raw_text[:120]})

            non_kept_hits = [h for h in hits if h["status"] != "kept"]
            bucket = ("i37_clean_stage_loss" if in_full_doc and not in_kept_any
                      else "i42_not_in_doc_unreachable" if not in_full_doc
                      else "matched_or_kept" if in_kept_any
                      else "unknown")
            print(f"  in_kept_any={in_kept_any}  in_kept_declared_page={in_kept_declared_page}  "
                  f"in_full_doc={in_full_doc}  → bucket={bucket}")
            print(f"  全文命中单元数={len(hits)}（其中非 kept {len(non_kept_hits)}）")
            for h in hits:
                print(f"    ord={h['ordinal']} status={h['status']} reasons={h['reasons']} "
                      f"page={h['page']} el={h['element']} len={h['len']}  <<<{h['fragment']}")
                print(f"        raw={h['raw_head']!r}")
            findings.append({
                "query_id": target_qid[t.target_id], "target_id": t.target_id,
                "source_id": live_src, "build_id": build_id, "page": page,
                "quote": t.quote,
                "in_kept_any": in_kept_any, "in_kept_declared_page": in_kept_declared_page,
                "in_full_doc": in_full_doc, "bucket": bucket,
                "unit_hits": hits,
                "total_units": len(units), "kept_units": len(kept),
            })

    verdict = "i37" if any(f["bucket"] == "i37_clean_stage_loss" for f in findings) else "i42"
    result = {"artifact": "2targets-attribution", "generated_at": __import__("datetime").datetime.now(
        __import__("datetime").timezone.utc).astimezone().isoformat(timespec="seconds"),
        "corpus": "index-4-zhcfg-2 active (8 builds)",
        "targets": findings,
        "verdict": verdict,
        "meaning": ("引文在全文（含非 kept 单元）逐字存在、kept 缺失 ⇒ i37 成立：清洗剔除，票 05 有活干"
                    if verdict == "i37" else
                    "引文在全文任意处不逐字出现 ⇒ i42 成立：金标改写/重建，管线不可达，票 05 白做")}
    write_once("attribution.json", result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
