"""M6 独立复核 · DB 直读独立核验（不复用 i37_rebuild.py / i37_score.py 的库级断言）。

独立直读沙箱 PG（127.0.0.1:543/i2_sandbox_corpus，**只读**，corpus schema 零写入）：

1. 指针态：corpus_publications active_build_id 非空恰 8 源；corpus_sources/builds/chunks/units
   规模清点；i2_% 库清单（I3-7 宣称 d2d6 第三库已 DROP——独立确认只剩 i2_sandbox_corpus）；
2. revs 库级重算：活动 build 的 parse/clean/chunk/index rev 按**冻结清单 runtime_configuration**
   的常量经冻结 canonical_fingerprint + reader._extractor_rev 现算对账（pdf/docx/md 三格式各按
   dev-scope-manifest 路径字节定 source_id），并三向对照 rebuild-report.json 汇总集合；
3. 独立 search→fetch 回环：直接从 corpus_units 取 3 个真实单元（三源各一），取其原文首句的
   zhcfg 词元 OR 查询走 search_bands——命中须含该源 → 对命中句柄 fetch_verbatim → 逐字文本
   非空且 build_id 与该源活动 build 一致（不借 i37 的检索组装）；
4. 纪律：守卫装载后运行（零模型/网络仅 543/forbidden_roots 留出零读取）；DSN fail-closed。

产物 write-once：m6-dbcheck.json。用法（仓库根）::

    env -u PYTHONPATH uv run python \\
      .scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260923-m6-independent-review/m6_dbcheck.py
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1]
ROOT = HERE.parents[4]
FINAL_MANIFEST = BASE / "i3-final-freeze-manifest.json"
REBUILD_REPORT = BASE / "audits/20260923-i37-final-reverify/rebuild-report.json"
GUARD = BASE / "guards/i3-e2e.json"
DEV_MANIFEST = BASE / "audits/20260920-i31-dev-lane/dev-scope-manifest.json"
SANDBOX_DB = "i2_sandbox_corpus"
sys.path.insert(0, str(ROOT))

NON_SEMANTIC = ("generated_at",)


def _semantic(value):
    if isinstance(value, dict):
        return {k: _semantic(v) for k, v in value.items() if k not in NON_SEMANTIC}
    if isinstance(value, list):
        return [_semantic(v) for v in value]
    return value


def write_once(name: str, value) -> None:
    path = HERE / name
    raw = (json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n").encode()
    if path.exists():
        if _semantic(json.loads(path.read_text(encoding="utf-8"))) != _semantic(value):
            raise RuntimeError(f"write-once conflict: {name}")
        print(f"[write-once] {name}: 语义一致 → 保留", file=sys.stderr)
        return
    path.write_bytes(raw)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fail(msg: str):
    print(json.dumps({"fatal": msg}, ensure_ascii=False), file=sys.stderr)
    raise SystemExit(1)


def main() -> int:
    fm = json.loads(FINAL_MANIFEST.read_text(encoding="utf-8"))
    if digest(GUARD) != fm["frozen_assets"]["guards"][
            ".scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i3-e2e.json"]:
        fail("guards/i3-e2e.json 与冻结清单不符")

    env: dict[str, str] = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            env[k] = v
    cred = env.get("CORPUS_DSN", "").split("://", 1)[-1].rsplit("@", 1)[0]
    parts = urlsplit(f"postgresql://{cred}@127.0.0.1:543/{SANDBOX_DB}")
    if parts.hostname != "127.0.0.1" or parts.port != 543:
        fail("DSN fail-closed 校验失败")
    sandbox_dsn = f"postgresql://{cred}@127.0.0.1:543/{SANDBOX_DB}"

    from plugins.corpus.preparation import guard as guard_module

    guard_module.install(GUARD)

    import psycopg

    from plugins.corpus.preparation import read_pg, search_pg
    from plugins.corpus.preparation.admission import PROBE_REV
    from plugins.corpus.preparation.chunk import CHUNK_REV, normalize_search_text
    from plugins.corpus.preparation.clean import CLEAN_REV
    from plugins.corpus.preparation.contract import (DocumentFormat, canonical_fingerprint,
                                                     sha256_of_bytes)
    from plugins.corpus.preparation.engine import INDEX_REV_V3, PARSE_RULE_REV
    from plugins.corpus.preparation.readers import docx_reader, pdf_reader
    from plugins.corpus.preparation.readers.md_reader import READER_MD_REV
    from plugins.corpus.preparation.search_pg import _check_target
    from plugins.corpus.service import CorpusService

    # 1) 指针态 + 规模清点 + 库清单
    with psycopg.connect(sandbox_dsn, autocommit=True) as conn:
        _check_target(conn, SANDBOX_DB)
        pubs = conn.execute(
            "SELECT source_id, active_build_id, generation FROM corpus.corpus_publications "
            "WHERE active_build_id IS NOT NULL ORDER BY source_id").fetchall()
        counts = dict(conn.execute(
            "SELECT 'corpus_sources', count(*) FROM corpus.corpus_sources "
            "UNION ALL SELECT 'corpus_builds', count(*) FROM corpus.corpus_builds "
            "UNION ALL SELECT 'corpus_chunks', count(*) FROM corpus.corpus_chunks "
            "UNION ALL SELECT 'corpus_units', count(*) FROM corpus.corpus_units").fetchall())
        i2_dbs = [r[0] for r in conn.execute(
            "SELECT datname FROM pg_database WHERE datname LIKE 'i2_%' "
            "ORDER BY datname").fetchall()]
    pointer_state = {
        "active_publications": len(pubs),
        "unique_sources": len({r[0] for r in pubs}),
        "unique_active_builds": len({r[1] for r in pubs}),
        "counts": counts,
        "i2_databases": i2_dbs,
        "d2d6_third_db_dropped": i2_dbs == ["i2_sandbox_corpus"],
    }

    # 2) revs 库级重算（冻结常量 + 冻结组装公式；三格式枚举自 dev-scope-manifest 字节）
    revs_manifest = fm["runtime_configuration"]["revs"]
    code_revs = {
        "reader_pdf": pdf_reader.READER_PDF_REV,
        "reader_docx": docx_reader.READER_DOCX_REV,
        "reader_md": READER_MD_REV,
        "clean": CLEAN_REV,
        "chunk": CHUNK_REV,
        "index": INDEX_REV_V3,
        "ingest": __import__("plugins.corpus.preparation.source", fromlist=["INGEST_REV"])
        .INGEST_REV,
        "admission_probe": PROBE_REV,
    }
    code_revs_match_manifest = code_revs == dict(revs_manifest)

    stamped = {DocumentFormat.PDF: pdf_reader._extractor_rev(),
               DocumentFormat.DOCX: docx_reader._extractor_rev(),
               DocumentFormat.MARKDOWN: READER_MD_REV}
    fmt_enum = {".pdf": DocumentFormat.PDF, ".docx": DocumentFormat.DOCX,
                ".md": DocumentFormat.MARKDOWN}
    fmt_by_sid: dict[str, str] = {}
    for entry in json.loads(DEV_MANIFEST.read_text(encoding="utf-8"))["sources"]:
        sid = sha256_of_bytes((ROOT / str(entry["path"])).read_bytes())
        fmt_by_sid[sid] = Path(str(entry["path"])).suffix.lower()

    with psycopg.connect(sandbox_dsn, autocommit=True) as conn:
        builds = conn.execute(
            "SELECT b.source_id, b.build_id, b.parse_rev, b.clean_rev, b.chunk_rev, b.index_rev "
            "FROM corpus.corpus_builds b WHERE b.build_id IN "
            "(SELECT active_build_id FROM corpus.corpus_publications "
            "WHERE active_build_id IS NOT NULL)").fetchall()
    rev_rows = []
    revs_ok = len(builds) == 8 and len(fmt_by_sid) == 8
    for row in builds:
        sid, bid, parse_rev, clean_rev, chunk_rev, index_rev = row
        fmt = fmt_by_sid.get(sid)
        if fmt is None:
            revs_ok = False
            rev_rows.append({"source_id": sid[:16], "error": "source 不在 dev-scope-manifest"})
            continue
        exp_parse = canonical_fingerprint(
            [PARSE_RULE_REV, sid, stamped[fmt_enum[fmt]]])
        row_ok = (parse_rev == exp_parse
                  and clean_rev == canonical_fingerprint([CLEAN_REV])
                  and chunk_rev == canonical_fingerprint([CHUNK_REV])
                  and index_rev == INDEX_REV_V3)
        revs_ok = revs_ok and row_ok
        rev_rows.append({"source_id": sid[:16] + "…", "format": fmt, "build_id": bid[:16] + "…",
                         "parse_rev_match": parse_rev == exp_parse,
                         "clean_rev_match": clean_rev == canonical_fingerprint([CLEAN_REV]),
                         "chunk_rev_match": chunk_rev == canonical_fingerprint([CHUNK_REV]),
                         "index_rev_match": index_rev == INDEX_REV_V3})

    rebuild = json.loads(REBUILD_REPORT.read_text(encoding="utf-8"))["summary"]
    sets_match_rebuild = (
        sorted({r[2] for r in builds}) == sorted(rebuild["parse_revs"])
        and sorted({r[3] for r in builds}) == sorted(rebuild["clean_revs"])
        and sorted({r[4] for r in builds}) == sorted(rebuild["chunk_revs"])
        and sorted({r[5] for r in builds}) == sorted(rebuild["index_revs"]))

    # 3) 独立 search→fetch 回环：corpus_units 直取 3 源真实单元
    svc = CorpusService(sandbox_dsn)
    roundtrips = []
    loop_ok = True
    probe_sids = sorted({r[0] for r in pubs})[:1] + sorted({r[0] for r in pubs})[-2:]
    with psycopg.connect(sandbox_dsn, autocommit=True) as conn:
        for sid in probe_sids:
            unit = conn.execute(
                "SELECT unit_id, raw_text FROM corpus.corpus_units WHERE build_id = "
                "(SELECT active_build_id FROM corpus.corpus_publications WHERE source_id=%s) "
                "AND length(raw_text) > 60 ORDER BY unit_id LIMIT 1", (sid,)).fetchone()
            if unit is None:
                roundtrips.append({"source_id": sid[:16] + "…", "error": "无可用单元"})
                loop_ok = False
                continue
            uid, raw_text = unit
            sentence = raw_text.split("。")[0][:80]
            lex = conn.execute(
                "SELECT tsvector_to_array(to_tsvector('zhcfg', %s))",
                (normalize_search_text(sentence),)).fetchone()[0]
            query = " OR ".join('"' + str(t).replace('"', " ") + '"' for t in lex)
            docs, _ = svc.search_bands(query, limit=10)
            hit = next((d for d in docs if d.source_id == sid), None)
            if hit is None:
                roundtrips.append({"source_id": sid[:16] + "…", "unit_id": uid,
                                   "query": query[:80], "hit": False})
                loop_ok = False
                continue
            ev = svc.fetch_verbatim(hit.doc_handle, read_pg.chunk_locator(
                hit.chunks_by_band[0][0].chunk_id))
            active_build = next(r[1] for r in pubs if r[0] == sid)
            rt = {
                "source_id": sid[:16] + "…", "unit_id": uid, "n_query_lexemes": len(lex),
                "hit": True, "handle_format_ok": hit.doc_handle.startswith("cv2:"),
                "fetch_text_nonempty": bool(ev.text.strip()),
                "build_id_match": ev.build_id == active_build and ev.build_id == hit.build_id,
            }
            roundtrips.append(rt)
            loop_ok = loop_ok and rt["hit"] and rt["fetch_text_nonempty"] and rt["build_id_match"]

    all_ok = (pointer_state["active_publications"] == 8
              and pointer_state["unique_sources"] == 8
              and pointer_state["unique_active_builds"] == 8
              and pointer_state["d2d6_third_db_dropped"]
              and code_revs_match_manifest and revs_ok and sets_match_rebuild and loop_ok)

    results = {
        "artifact": "m6-independent-dbcheck",
        "generated_at": datetime.now(UTC).astimezone().isoformat(timespec="seconds"),
        "dsn_fail_closed": {"host": "127.0.0.1", "port": 543, "db": SANDBOX_DB,
                            "read_only": "全程 SELECT + 检索/fetch，corpus schema 零写入"},
        "pointer_state": pointer_state,
        "code_revs_match_manifest": code_revs_match_manifest,
        "db_revs_recomputed": {"all_match": revs_ok, "rows": rev_rows},
        "rev_sets_match_rebuild_report": sets_match_rebuild,
        "search_fetch_roundtrips": roundtrips,
        "search_fetch_roundtrip_ok": loop_ok,
        "all_ok": all_ok,
        "discipline": {
            "model_calls": 0,
            "guard": "guards/i3-e2e.json 已装载（零模型 / 网络仅 127.0.0.1:543 / "
                     "forbidden_roots 留出零读取）",
            "pg": "只读；生产库 5432 零触碰；_check_target fail-closed",
        },
    }
    write_once("m6-dbcheck.json", results)
    print(json.dumps({"all_ok": all_ok,
                      "active": pointer_state["active_publications"],
                      "d2d6_dropped": pointer_state["d2d6_third_db_dropped"],
                      "code_revs_match": code_revs_match_manifest,
                      "db_revs_ok": revs_ok,
                      "rev_sets_match_rebuild": sets_match_rebuild,
                      "roundtrip_ok": loop_ok,
                      "roundtrips": roundtrips}, ensure_ascii=False, indent=2))
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
