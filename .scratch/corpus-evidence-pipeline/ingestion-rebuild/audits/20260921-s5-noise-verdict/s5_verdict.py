"""票 05 目标级归因：e1 / a-1 的机读判定依据（spec §7.5 目标级）。

§10.4 已裁定 i37 成立（引文逐字存在于全文非 kept 单元）。本脚本进一步把两条
引文的 NOISE 判定还原成**机读依据**（`CleanRegion.verdicts`：code/rule/observed/
threshold），据此回答：是「规则过宽」还是「本就该剔」。

方法（只读 PG + 0 model calls）：
- 取当前活动语料（index-4-zhcfg-2）的目标 build 全量单元；
- 以 reader 态重建 `CandidateUnit`（status=KEPT、reasons=()，保留原文/kind/page/
  bbox）重放 `clean_reader_result`——噪声判定是 (raw_text, kind, page, bbox) 的
  纯函数，重放即复现当时判定依据；
- 对每条目标：定位引文片段命中的单元，输出重放 verdicts + 存储 status/reasons
  一致性比对；
- 结论只做「过宽 vs 本就该剔」二分类，**不调任何阈值**（调阈值须单独立项）。

产物 write-once：s5-summary.json。
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


def verdict_payload(region) -> list[dict]:
    out = []
    for v in region.verdicts:
        out.append(
            {
                "code": v.code,
                "rule": v.rule,
                "observed": {k: str(x) for k, x in v.observed.items()},
                "threshold": {k: str(x) for k, x in v.threshold.items()},
            }
        )
    return out


def main() -> int:
    from datetime import UTC, datetime

    from plugins.corpus.preparation.clean import clean_reader_result
    from plugins.corpus.preparation.contract import DocumentFormat, UnitStatus
    from plugins.corpus.preparation.readers.base import CandidateUnit, ReaderResult
    from plugins.corpus.preparation.repository_pg import PgStore
    from plugins.corpus.preparation.search_pg import _check_target
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

    findings: list[dict] = []
    with psycopg.connect(dsn, autocommit=True) as conn:
        _check_target(conn, SANDBOX)
        sources = dict(
            conn.execute(
                "SELECT source_id, active_build_id FROM corpus.corpus_publications "
                "WHERE active_build_id IS NOT NULL"
            ).fetchall()
        )
        alias_to_source = {}
        for t in want:
            alias = t.source_id
            matches = [src for src in sources if src.startswith(alias.rsplit("_", 1)[-1])]
            assert len(matches) == 1, f"{alias}: {matches}"
            alias_to_source[alias] = matches[0]

        for t in want:
            live_src = alias_to_source[t.source_id]
            build_id = sources[live_src]
            quote = norm(t.quote)
            page = None
            for tok in t.locator:
                if tok.startswith("page:"):
                    page = int(tok.split(":", 1)[1])
                    break

            with PgStore(dsn, sandbox_db=SANDBOX) as store:
                units = store.get_units(build_id)
            stored_by_ordinal = {u.ordinal: u for u in units if u.ordinal is not None}
            reader_units = [
                CandidateUnit(
                    ordinal=u.ordinal,
                    kind=u.kind,
                    status=UnitStatus.KEPT,
                    reasons=(),
                    raw_text=u.raw_text,
                    location=u.location,
                )
                for u in units
                if u.ordinal is not None
            ]
            clean = clean_reader_result(
                ReaderResult(
                    format=DocumentFormat.PDF,
                    extractor_rev="s5-replay",
                    source_path="replay",
                    page_count=None,
                    units=tuple(reader_units),
                    issues=(),
                )
            )
            regions_by_ordinal = {r.ordinal: r for r in clean.regions if r.ordinal is not None}

            hits = []
            for u in units:
                if u.ordinal is None:
                    continue
                un = norm(u.raw_text)
                frag = [p for p in (quote[:20], quote[-20:]) if p and p in un]
                if not frag:
                    continue
                region = regions_by_ordinal[u.ordinal]
                stored = stored_by_ordinal[u.ordinal]
                status_match = region.status is stored.status
                hits.append(
                    {
                        "ordinal": u.ordinal,
                        "page": u.location.page,
                        "stored_status": str(stored.status.value),
                        "stored_reasons": list(stored.reasons or ()),
                        "replayed_status": str(region.status.value),
                        "status_match": status_match,
                        "quote_fragment": "首尾" if len(frag) == 2 else frag[0],
                        "quote_contained": quote in un,
                        "kind": u.kind,
                        "raw_text": u.raw_text[:120],
                        "verdicts": verdict_payload(region),
                    }
                )

            print("=" * 100)
            print(f"TARGET {target_qid[t.target_id]}/{t.target_id}  src={live_src}  "
                  f"build={build_id[:12]}…  page={page}")
            print(f"quote: {t.quote!r}")
            for h in hits:
                print(f"  ord={h['ordinal']} p{h['page']} stored={h['stored_status']} "
                      f"replay={h['replayed_status']} match={h['status_match']} "
                      f"contained={h['quote_contained']} <<<{h['quote_fragment']}")
                for v in h["verdicts"]:
                    print(f"      verdict code={v['code']} rule={v['rule']}")
                    print(f"        observed={v['observed']}")
                    print(f"        threshold={v['threshold']}")

            findings.append(
                {
                    "query_id": target_qid[t.target_id],
                    "target_id": t.target_id,
                    "source_id": live_src,
                    "build_id": build_id,
                    "page": page,
                    "quote": t.quote,
                    "total_units": len(units),
                    "kept_units": sum(1 for u in units if u.status is UnitStatus.KEPT),
                    "hit_units": hits,
                }
            )

    # --- 目标级判定：规则过宽 vs 本就该剔（只读依据，不改阈值） ---
    e1 = next(f for f in findings if f["target_id"] == "e1")
    a1 = next(f for f in findings if f["target_id"] == "a-1")
    e1_hit = e1["hit_units"][0]
    a1_hits = a1["hit_units"]
    judgments = [
        {
            "target_id": "e1",
            "verdict_code": e1_hit["verdicts"][0]["code"] if e1_hit["verdicts"] else None,
            "judgment": "rules_too_wide",
            "basis": (
                f"ord={e1_hit['ordinal']} p{e1_hit['page']} 重放判定 "
                f"{e1_hit['verdicts'][0]['code']}："
                f"observed={e1_hit['verdicts'][0]['observed']}（含免责声明标题起点），"
                f"threshold={e1_hit['verdicts'][0]['threshold']}。规则按「标题→下一标题」"
                f"整段剔除；该段确为分析师声明（免责声明节），但同一单元内含实质事实句"
                f"「华创云信4.06%持股」，整段剔除粒度过宽。"
            ),
            "lever": "disclaimer_section 判定粒度（整段 → 事实句保留/子句粒度）",
        },
        {
            "target_id": "a-1",
            "verdict_code": "header_repeated_geometric",
            "judgment": "unit_level_fired_correctly_quote_boundary_issue",
            "basis": (
                f"{len(a1_hits)} 个命中单元（p1-p7）重放判定 header_repeated_geometric："
                f"observed.repeat_pages=7 ≥ threshold.min_pages=3 且在页顶带，规则按定义"
                f"正确触发（页眉本就该剔）；但引文前半在该 NOISE 表头、后半「强推（维持）」"
                f"在 kept 单元 ⇒ 引文横跨 NOISE/kept 边界，损失归表归属/引文粒度，"
                f"另立议题，非规则过宽。"
            ),
            "lever": "引文粒度/表归属边界（另立议题；不调 header 阈值）",
        },
    ]
    result = {
        "artifact": "s5-noise-verdict",
        "generated_at": datetime.now(UTC).astimezone().isoformat(timespec="seconds"),
        "corpus": "index-4-zhcfg-2 active (8 builds)",
        "method": "以 reader 态重放 clean_reader_result，还原 NOISE 判定机读依据；只读 PG + 0 model calls",
        "targets": findings,
        "judgments": judgments,
        "conclusion": (
            "e1：disclaimer_section 规则过宽（粒度）——整段免责声明吞实质事实句；"
            "a-1：header_repeated_geometric 按定义本就该剔，损失来自引文横跨 NOISE/kept 边界（另立议题）。"
            "本票不调任何阈值。"
        ),
    }
    write_once("s5-summary.json", result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
