"""I3-1 最终开发范围（真实链路）：换料后的零阻断样本 + U 补的 DOCX + U 要求接受的 MD。

范围（11 份）：
- macro 2 份、industry 6 份：来自 `i3-1-screening.json` 的**零阻断且非留出**样本（规范口径"换料"）；
- DOCX 1 份（U 补，光模块）；
- MD 2 份（投委会报告）：按 U 2026-09-19 指示"MD 格式文件必须接受"，人工决定显式给出
  `material_type=research_report` 并 `supersedes` 既有决定（唯一取代链）。
- **company 0 份**：唯一零阻断的公司研报恰是留出件；另两份各带 1 处 blocking 缺口 →
  如实登记为素材缺口（见记录 findings），不静默缩范围。
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1]
ROOT = HERE.parents[4]
GUARD = BASE / "guards/i3-e2e.json"
SCREENING = HERE / "i3-1-screening.json"
MANIFEST = HERE / "dev-scope-manifest-v3.json"
OUT = HERE / "i3-1-e2e-scope-v2.json"
OUT_MD = HERE / "i3-1-e2e-scope-v2.md"
ARCHIVE = HERE / "archive"
SANDBOX_DB = "i2_sandbox_corpus"
NOW = datetime(2026, 9, 19, 21, 0, tzinfo=UTC)
AUTHOR = "i3-e2e-agent-proposal（Agent 提案，待 U 追认；不构成 M1 范围决定）"
MD_AUTHOR = "xyl（U 2026-09-19 指示：MD 格式文件必须接受；材料类型按研报认定）"
DOCX = "data/corpus/9月8日 光模块技术演进与供应链重构：从1.6T到3.2T的路径、格局.docx"
MDS = ("data/corpus/仕佳光子_投委会决策报告_20260831.md", "data/corpus/天孚通信_投委会决策报告_20260830.md")
QUERIES = ("营业收入", "景气", "非农", "同比", "光模块", "碳市场")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cli_run(cli, argv: list[str]) -> dict:
    buf = io.StringIO()
    started = time.perf_counter()
    with contextlib.redirect_stdout(buf):
        code = cli.main(argv)
    text = buf.getvalue()
    try:
        payload: object = json.loads(text)
    except json.JSONDecodeError:
        payload = json.loads(text[text.find("{"):]) if "{" in text else {"raw": text[:2000]}
    return {"argv": argv, "exit_code": code, "seconds": round(time.perf_counter() - started, 2),
            "output": payload}


def table_rows(cur, sql: str, params: tuple = ()) -> list[dict]:
    cur.execute(sql, params)
    columns = [c.name for c in cur.description]
    return [dict(zip(columns, row, strict=True)) for row in cur.fetchall()]


def main() -> int:
    env = dict(
        line.split("=", 1)
        for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines()
        if "=" in line and not line.strip().startswith("#")
    )
    dsn = (
        f"postgresql://{env['CORPUS_DSN'].split('://', 1)[1].rsplit('@', 1)[0]}"
        "@127.0.0.1:543/i2_sandbox_corpus"
    )

    screening = json.loads(SCREENING.read_text(encoding="utf-8"))
    holdouts = {
        Path(p).name for p in json.loads((BASE / "guards/i3.json").read_text(encoding="utf-8"))[
            "sources"
        ]["forbidden_roots"]
    }
    picked = [
        row for row in screening["all_rows"]
        if row["blocking"] == 0 and Path(row["path"]).name not in holdouts
        and row["domain_hint"] in ("macro", "industry")
    ]
    selection = [
        {"path": row["path"], "domain_hint": row["domain_hint"], "label": "pdf",
         "decision_author": AUTHOR, "material_type": None}
        for row in picked
    ] + [
        {"path": DOCX, "domain_hint": "industry", "label": "docx",
         "decision_author": AUTHOR, "material_type": None},
    ] + [
        {"path": md, "domain_hint": "company", "label": "md",
         "decision_author": MD_AUTHOR, "material_type": "research_report"}
        for md in MDS
    ]

    record: dict = {
        "artifact": "i3-1-e2e-scope-v2",
        "generated_at": datetime.now(UTC).astimezone().isoformat(timespec="seconds"),
        "target": {"dsn": f"postgresql://***@127.0.0.1:543/{SANDBOX_DB}", "database": SANDBOX_DB},
        "scope_status": "proposed_pending_ratification",
        "selection": {
            "rule": (
                "零阻断且非留出（换料，规范口径）+ U 补 DOCX + U 要求接受的 MD；"
                "company 类零阻断样本为 0（唯一干净者系留出件）"
            ),
            "sources": [{"path": item["path"], "domain": item["domain_hint"], "label": item["label"]}
                        for item in selection],
            "company_gap": (
                "company 类：3 份公司研报中 1 份零阻断但属留出件（不可用），另 2 份各 1 处 "
                "`image_region_unreadable`(needs_ocr/blocking)；规范内**无人工认可入口**"
                "（gaps.py 默认表把该代码固定为 blocking）→ company 需 U 决定：补料 / 改实现 / 显式登记未覆盖"
            ),
        },
    }

    # 守卫：把选定来源加入允许清单（草稿守卫，尚未绑定任何修订）
    guard = json.loads(GUARD.read_text(encoding="utf-8"))
    before = len(guard["sources"]["allowed_source_paths"])
    for item in selection:
        if item["path"] not in guard["sources"]["allowed_source_paths"]:
            guard["sources"]["allowed_source_paths"].append(item["path"])
    guard["note"] = guard["note"] + (
        f" 2026-09-19 夜：I3-1 最终范围选定后，允许路径 {before}→{len(guard['sources']['allowed_source_paths'])}"
        "（换料后的零阻断研报 8 份 + DOCX 1 + MD 2）。"
    )
    GUARD.write_text(json.dumps(guard, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    record["guard"] = {"path": str(GUARD.relative_to(ROOT)), "sha256": digest(GUARD),
                       "allowed_paths": len(guard["sources"]["allowed_source_paths"])}

    sys.path.insert(0, str(ROOT))
    from plugins.corpus.preparation import guard as guard_module  # noqa: PLC0415

    guard_module.install(GUARD)
    from plugins.corpus import cli  # noqa: PLC0415
    from plugins.corpus.preparation.contract import (  # noqa: PLC0415
        MaterialType,
        ReviewDecision,
        ReviewedDecision,
        sha256_of_bytes,
    )
    from plugins.corpus.preparation.repository_pg import PgStore  # noqa: PLC0415

    import psycopg  # noqa: PLC0415

    entries = []
    store = PgStore(dsn, sandbox_db=SANDBOX_DB)
    try:
        for item in selection:
            source_bytes = (ROOT / item["path"]).read_bytes()
            source_id = sha256_of_bytes(source_bytes)
            chain_ids: list[str] = []
            heads: list[str] = []
            with psycopg.connect(dsn, autocommit=True) as conn, conn.cursor() as cur:
                rows = table_rows(
                    cur,
                    "SELECT decision_id, supersedes FROM corpus.corpus_review_decisions "
                    "WHERE source_id = %s",
                    (source_id,),
                )
                children = {str(r["supersedes"]) for r in rows if r.get("supersedes")}
                heads = [str(r["decision_id"]) for r in rows if str(r["decision_id"]) not in children]
                # 关键：清单必须列出**整条取代链**——引擎只按清单声明的 ids 解析历史，
                # 若 tip 的 supersedes 指向未声明的决定 → 断链 → conflicting_review（本轮踩过）
                chain_ids = [str(r["decision_id"]) for r in rows]
            label = hashlib.sha256(item["path"].encode()).hexdigest()[:8]
            decision_id = f"i3e2e-scope-{item['label']}-{label}"
            existing_ids = {str(r["decision_id"]) for r in rows}
            if decision_id in existing_ids:
                # 幂等：本脚本可能被重跑；已登记且内容固定的决定直接复用（避免"内容不同"冲突）
                reused = True
            else:
                reused = False
                store.put_reviewed_decision(
                    ReviewedDecision(
                        decision_id=decision_id,
                        source_id=source_id,
                        reviewer=item["decision_author"],
                        reviewed_at=NOW,
                        decision=ReviewDecision.ADMITTED,
                        rationale=(
                            "I3-1 最终范围（隔离沙箱）：零阻断换料样本 / U 补 DOCX / U 要求接受的 MD"
                        ),
                        supersedes=heads[0] if len(heads) == 1 else None,
                        material_type=(
                            MaterialType(item["material_type"]) if item["material_type"] else None
                        ),
                    )
                )
                chain_ids = [*chain_ids, decision_id]
            item["reused"] = reused
            item["decision_id"] = decision_id
            item["superseded"] = heads
            entries.append(
                {"path": item["path"], "domain_hint": item["domain_hint"],
                 "review_decision_ids": list(dict.fromkeys([*chain_ids, decision_id]))}
            )
            item["chain"] = list(dict.fromkeys([*chain_ids, decision_id]))
    finally:
        store.close()
    MANIFEST.write_text(
        json.dumps({"sources": entries, "archive_root": str(ARCHIVE)}, ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    record["decisions"] = [
        {"path": item["path"], "label": item["label"], "decision_id": item["decision_id"],
         "superseded": item["superseded"], "material_type": item["material_type"]}
        for item in selection
    ]

    # ── 链路：build → 逐源 check/publish
    build = cli_run(cli, ["build", "--manifest", str(MANIFEST), "--dsn", dsn, "--owner", "i3-e2e-v3",
                          "--archive-root", str(ARCHIVE)])
    outcomes = {str(o.get("original_name")): o for o in (build["output"] or {}).get("outcomes") or []}
    record["steps"] = {"build": {"exit_code": build["exit_code"], "seconds": build["seconds"],
                                 "count": (build["output"] or {}).get("count")}}
    per_source = []
    for item in selection:
        name = Path(item["path"]).name
        outcome = outcomes.get(name) or {}
        row = {
            "path": item["path"], "domain": item["domain_hint"], "label": item["label"],
            "format": Path(item["path"]).suffix.lower().lstrip("."),
            "decision": outcome.get("decision"),
            "build_id": outcome.get("build_id"),
            "unit_count": outcome.get("unit_count"),
            "chunk_count": outcome.get("chunk_count"),
        }
        if outcome.get("decision") == "in_scope" and outcome.get("build_id"):
            checked = cli_run(cli, ["check", "--build", str(outcome["build_id"]), "--dsn", dsn])
            row["check_exit"] = checked["exit_code"]
            row["publishable"] = (checked["output"] or {}).get("publishable")
            row["blocking_gaps"] = [
                {"code": g.get("code"), "status": g.get("status"), "key": g.get("key")}
                for g in (checked["output"] or {}).get("gaps") or []
                if str(g.get("disposition")) not in ("acknowledged", "noise")
            ]
            row["acknowledged_gaps"] = sum(
                1 for g in (checked["output"] or {}).get("gaps") or []
                if str(g.get("disposition")) in ("acknowledged", "noise")
            )
            if checked["exit_code"] == 0:
                published = cli_run(cli, ["publish", "--build", str(outcome["build_id"]),
                                          "--operator", "i3-e2e", "--dsn", dsn])
                row["publish"] = {"exit_code": published["exit_code"],
                                  "generation": (published["output"] or {}).get("generation")}
            else:
                row["publish"] = {"exit_code": checked["exit_code"], "blocked": True,
                                  "error": (checked["output"] or {}).get("error")}
        per_source.append(row)
    record["per_source"] = per_source

    # ── 读侧
    import plugins.corpus.service as service_mod  # noqa: PLC0415
    from plugins.corpus.audit import audit_corpus_chain  # noqa: PLC0415
    from plugins.corpus.preparation import read_pg  # noqa: PLC0415

    os.environ["CORPUS_READ_CHAIN"] = "new"
    service_mod.dsn = lambda: dsn
    service = service_mod.CorpusService(dsn)
    searches = []
    for query in QUERIES:
        hits = service.search(query, limit=5)
        verified = []
        for hit in hits:
            try:
                evidence = service.fetch_verbatim(hit.doc_id, hit.locator)
                document = read_pg.fetch_document(dsn, hit.doc_id, sandbox_db=SANDBOX_DB)
            except Exception as exc:  # noqa: BLE001 - 读侧 fail-closed：如实登记被拒句柄
                verified.append({"locator": hit.locator, "refused": type(exc).__name__,
                                 "reason": str(exc)[:120]})
                continue
            verified.append({
                "locator": hit.locator, "units": len(evidence.units), "active": bool(evidence.active),
                "join_ok": evidence.text == "\n".join(u.raw_text for u in evidence.units),
                "units_in_doc": all(u.raw_text in document.text for u in evidence.units),
                "sample": evidence.text[:60],
            })
        searches.append({"query": query, "hits": len(hits), "verified": verified})
    record["search"] = searches
    record["coverage"] = read_pg.coverage_snapshot(dsn, sandbox_db=SANDBOX_DB, query_status="matched")
    with psycopg.connect(dsn, autocommit=True) as conn:
        record["audit"] = audit_corpus_chain(conn)
    published = [r for r in per_source if (r.get("publish") or {}).get("exit_code") == 0]
    record["summary"] = {
        "sources": len(per_source),
        "buildable": sum(1 for r in per_source if r.get("build_id")),
        "published": len(published),
        "review_required": sum(1 for r in per_source if r.get("decision") == "review_required"),
        "total_units": sum(r.get("unit_count") or 0 for r in per_source),
        "total_chunks": sum(r.get("chunk_count") or 0 for r in per_source),
        "search_hits": {s["query"]: s["hits"] for s in searches},
        "verify_all_ok": all(
            v.get("active") and v.get("join_ok") and v.get("units_in_doc")
            for s in searches for v in s["verified"] if "refused" not in v
        ),
        "refused_handles": sum(1 for s in searches for v in s["verified"] if "refused" in v),
        "audit_conflicts": record["audit"].get("conflicts"),
    }
    OUT.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_md(record)
    print(json.dumps({"summary": record["summary"],
                      "per_source": [{k: r.get(k) for k in ("domain", "format", "decision", "unit_count",
                                                            "chunk_count", "publishable")}
                                     for r in per_source]},
                     ensure_ascii=False, indent=2))
    return 0


def write_md(record: dict) -> None:
    lines = [
        "# I3-1 最终开发范围（换料 + U 补料）——真实结果",
        "",
        f"- 生成：{record['generated_at']}；目标 `{record['target']['dsn']}`；守卫 `{record['guard']['path']}`"
        f"（允许路径 {record['guard']['allowed_paths']} 条，sha256 {record['guard']['sha256'][:12]}）",
        f"- 范围规则：{record['selection']['rule']}",
        f"- **company 缺口**：{record['selection']['company_gap']}",
        "",
        "## 逐来源",
        "",
        "| 领域 | 格式 | 来源 | 单元/切块 | decision | check | publish |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in record["per_source"]:
        lines.append(
            f"| {row['domain']} | {row['format']} | {Path(row['path']).name[:34]} | "
            f"{row.get('unit_count')}/{row.get('chunk_count')} | {row.get('decision')} | "
            f"{row.get('check_exit', '—')} | "
            f"{(row.get('publish') or {}).get('exit_code', '—')}"
            f"{'（gen ' + str((row.get('publish') or {}).get('generation')) + '）' if (row.get('publish') or {}).get('generation') else ''} |"
        )
    summary = record["summary"]
    lines += [
        "",
        f"- 汇总：来源 {summary['sources']}，可 build {summary['buildable']}，**已发布 {summary['published']}**，"
        f"review_required {summary['review_required']}；{summary['total_units']} 单元 / {summary['total_chunks']} 切块",
        f"- 检索命中：{json.dumps(summary['search_hits'], ensure_ascii=False)}；"
        f"取证核验全过={summary['verify_all_ok']}；审计冲突={summary['audit_conflicts']}",
        "",
        "## 各份决定与取代链",
        "",
        "| 来源 | label | decision_id | supersedes | material_type |",
        "|---|---|---|---|---|",
    ]
    for item in record["decisions"]:
        lines.append(
            f"| {Path(item['path']).name[:30]} | {item['label']} | `{item['decision_id']}` | "
            f"{item['superseded'] or '—'} | {item['material_type'] or '（不给，沿用机器检出）'} |"
        )
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
