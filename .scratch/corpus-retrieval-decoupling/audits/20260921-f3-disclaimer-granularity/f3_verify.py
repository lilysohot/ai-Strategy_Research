"""票 08 目标级+v 归因：e1 免责事实句降 KEPT 的机读复核（spec §7.5 / issues/08）。

先归因后调阈值（不反序）：S5 已给出 e1=disclaimer_section 规则过宽的原始归因；
本脚本在 clean.py 改为句粒度后**整库回放**，量化免责节 NOISE→KEPT 的变化范围，
并确认 company-007/e1 引文事实句现落在 kept 单元、ord718/720 仍 NOISE。

只读 PG + 0 model calls；产物 write-once：f3-summary.json / f3-report.md。
"""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path("/home/administrator/FrontierAgent").resolve()
INGEST = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild"
AUDITS = INGEST / "audits"
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

SB = "i2_sandbox_corpus"
TARGETS = {("company-007", "e1")}


def load_module(name: str, path: Path) -> object:
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def write_once(name: str, value: object) -> None:
    path = HERE / name
    raw = (json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n").encode()
    if path.exists() and path.read_bytes() != raw:
        raise RuntimeError(f"write-once conflict: {name}")
    path.write_bytes(raw)


def norm(s: object) -> str:
    return "".join(ch for ch in s if not ch.isspace()) if isinstance(s, str) else ""


def verdict_payload(regions: tuple[object, ...], ordinal: int | str) -> list[dict]:
    region = next((r for r in regions if r.ordinal == ordinal), None)
    if region is None:
        return []
    return [
        {
            "code": v.code,
            "rule": v.rule,
            "observed": {k: str(x) for k, x in v.observed.items()},
            "threshold": {k: str(x) for k, x in v.threshold.items()},
        }
        for v in region.verdicts
    ]


def main() -> int:
    import psycopg

    from plugins.corpus.preparation.clean import clean_reader_result
    from plugins.corpus.preparation.contract import DocumentFormat, UnitStatus
    from plugins.corpus.preparation.readers.base import CandidateUnit, ReaderResult
    from plugins.corpus.preparation.repository_pg import PgStore
    from plugins.corpus.preparation.search_pg import _check_target
    from plugins.corpus.scoring import gold_from_records

    release = load_module("i31_region_release", AUDITS / "20260920-i31-region-review/release.py")
    dsn = release.connect()
    loader = load_module("i33_scoring_loader", INGEST / "i3s2_scoring_input.py")
    records = loader.load_scoring_input(INGEST / "i3-2/scoring-input-manifest.json")
    questions = gold_from_records(records)
    pairs = [(q.query_id, t) for q in questions for t in q.evidence_targets]
    want = [t for (qid, t) in pairs if (qid, t.target_id) in TARGETS]
    assert len(want) == 1, f"期望 1 个目标，实际 {len(want)}"

    summary: dict = {
        "artifact": "f3-disclaimer-granularity",
        "generated_at": datetime.now(UTC).isoformat(),
        "method": "整库回放 clean_reader_result（句粒度后）vs 存储 kept/NOISE，0 model calls",
        "per_doc": [],
        "e1": None,
        "bounds_change": None,
    }

    with psycopg.connect(dsn, autocommit=True) as conn:
        _check_target(conn, SB)
        rows = conn.execute(
            "SELECT source_id, active_build_id FROM corpus.corpus_publications "
            "WHERE active_build_id IS NOT NULL"
        ).fetchall()
        doc_deltas = []
        for source_id, build_id in rows:
            with PgStore(dsn, sandbox_db=SB) as store:
                units = store.get_units(build_id)
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
                    extractor_rev="f3-replay",
                    source_path="replay",
                    page_count=None,
                    units=tuple(reader_units),
                    issues=(),
                )
            )
            regions = {r.ordinal: r for r in clean.regions if r.ordinal is not None}
            switched_to_kept = []
            for u in units:
                if u.ordinal is None:
                    continue
                # 仅关注本票改动的判定面：存储为 disclaimer_section NOISE 的单元
                stored_noise_ds = u.status is UnitStatus.NOISE and "disclaimer_section" in (u.reasons or ())
                if not stored_noise_ds:
                    continue
                new_status = regions[u.ordinal].status
                if new_status is UnitStatus.KEPT:
                    switched_to_kept.append(
                        {
                            "ordinal": u.ordinal,
                            "page": u.location.page,
                            "gained_fact": "disclaimer_section_numeric_fact_keep"
                            in [v.rule for v in regions[u.ordinal].verdicts],
                            "sample": u.raw_text[:60],
                        }
                    )
            doc_deltas.append(
                {
                    "source_id": source_id,
                    "build_id": build_id,
                    "total_units": len(units),
                    "stored_disclaimer_section_noise": sum(
                        1 for u in units if u.ordinal is not None and u.status is UnitStatus.NOISE
                        and "disclaimer_section" in (u.reasons or ())
                    ),
                    "switched_to_kept": switched_to_kept,
                }
            )
        summary["per_doc"] = doc_deltas

        # --- e1 目标复核 ---
        t = want[0]
        alias = t.source_id
        live_src = next(
            s for s, _ in rows if s.startswith(alias.rsplit("_", 1)[-1])
        )
        build_id = next(b for s, b in rows if s == live_src)
        with PgStore(dsn, sandbox_db=SB) as store:
            units = store.get_units(build_id)
        reader_units = [
            CandidateUnit(
                ordinal=u.ordinal, kind=u.kind, status=UnitStatus.KEPT, reasons=(),
                raw_text=u.raw_text, location=u.location,
            )
            for u in units if u.ordinal is not None
        ]
        clean = clean_reader_result(
            ReaderResult(
                format=DocumentFormat.PDF, extractor_rev="f3-replay",
                source_path="replay", page_count=None, units=tuple(reader_units), issues=(),
            )
        )
        regions = {r.ordinal: r for r in clean.regions if r.ordinal is not None}
        # 定位语义事实句所在单元（含『华创云信』与『4.06%』的单元）
        fact_locus = None
        for u in units:
            if u.ordinal is None:
                continue
            un = norm(u.raw_text)
            if "华创云信" in un and "4.06%" in un and u.ordinal != fact_locus:
                fact_locus = u.ordinal
                break
        order = {u.ordinal: u for u in units if u.ordinal is not None}
        e1_payload = {
            "query_id": "company-007",
            "target_id": "e1",
            "source_id": live_src,
            "build_id": build_id,
            "quote": t.quote,
            "fact_sentence_ordinal": fact_locus,
            "fact_locus_status": str(regions[fact_locus].status.value) if fact_locus else None,
            "fact_locus_verdicts": verdict_payload(clean.regions, fact_locus) if fact_locus else [],
            "unit_slice": {
                str(o): {
                    "stored_status": str(order[o].status.value),
                    "replayed_status": str(regions[o].status.value),
                    "reasons": list(order[o].reasons or ()),
                }
                for o in (716, 717, 718, 719, 720) if o in order and o in regions
            },
        }
        summary["e1"] = e1_payload

    total_switched = sum(len(d["switched_to_kept"]) for d in doc_deltas)
    max_proven_docs = len(doc_deltas)
    summary["bounds_change"] = {
        "docs_scanned": max_proven_docs,
        "disclaimer_section_units_that_became_kept_total": total_switched,
        "basis": "仅免责节内含三类事实句的单元降 KEPT；纯免责措辞节（如 720）仍 NOISE。",
    }

    write_once("f3-summary.json", summary)
    # write_once 已写；此处再写报告
    report = [
        "# F3 机读复核：disclaimer_section 句粒度（三类事实句降 KEPT）",
        "",
        f"- 时间：{datetime.now(UTC).isoformat()}",
        "- 方法：history replay `clean_reader_result`（0 model calls，只读 PG）",
        "",
        "## 结论",
        "",
        "S5 已归因 e1=disclaimer_section 规则过宽（整段吞事实句）。本票把免责节判定改为：",
        "**仅当整段不含『可复核数字事实句』（持股百分比/证券代码/货币金额三类命中）才整段剔除；",
        "含事实句的单元整段降 KEPT**（I-E3）。",
        "",
        f"跨 {max_proven_docs} 个活动 build 回放：免责节中变为 KEPT 的单元共 {total_switched} 个。",
        "",
    ]
    for d in doc_deltas:
        report.append(f"- src={d['source_id'][:12]}… stored_D_S_NOISE={d['stored_disclaimer_section_noise']} "
                      f"→ 降 KEPT {len(d['switched_to_kept'])} 个")
        for s in d["switched_to_kept"]:
            report.append(
                f"    - ord={s['ordinal']} p{s['page']} gained_fact={s['gained_fact']}: {s['sample']}"
            )
    e1 = summary["e1"]
    report += [
        "",
        "## company-007/e1 目标",
        f"- 事实句（华创云信 4.06% 持股）所在 ord={e1['fact_sentence_ordinal']} "
        f"现为 **{e1['fact_locus_status']}**",
        f"- 单元切片：{json.dumps(e1['unit_slice'], ensure_ascii=False)}",
    ]
    write_once("f3-report.md", "\n".join(report) + "\n")

    for line in [
        "\n===== 跨文档免责节降 KEPT 汇总 =====",
        f"docs_scanned={max_proven_docs}  {total_switched=}",
        f"e1 fact_locus ord={e1['fact_sentence_ordinal']} status={e1['fact_locus_status']}",
        "unit 716-720:",
    ] + [f"  {o}: {v}" for o, v in e1["unit_slice"].items()]:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())