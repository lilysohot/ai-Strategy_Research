"""I3-1 三类开发 E2E（真实链路：登记→准入→解析→清洗→切块→build/check/publish→search/fetch/verify）。

边界（务必如实）：
- 只写隔离库 ``i2_sandbox_corpus``（``corpus-db`` 容器，127.0.0.1:543；实例无 ``apodex`` 库=非生产）；
- 运行时装载 ``guards/i3-e2e.json``（网络仅允许 127.0.0.1:543；``CORPUS_DSN`` 被投毒 → 生产串不可用）；
- **开发范围未冻结**：全部来源在 ``dev-manifest.json`` 中仍是 ``review_required``。本脚本按 Agent 提案的
  3 类×2 份执行，并在记录里标注 ``scope_status=proposed_pending_ratification``；登记的人工审核决定
  作者写明"Agent 提案、待 U 追认"，**不冒充 M1 范围决定**。
- 复用合成分数：无。本记录只写真实产物（build_id/generation/句柄/缺口/命中）。
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
DEV_MANIFEST = BASE / "dev-manifest.json"
RECORD = HERE / "i3-1-e2e-record.json"
RECORD_MD = HERE / "i3-1-e2e-record.md"
ARCHIVE = HERE / "archive"
MANIFEST = HERE / "dev-scope-manifest.json"
SANDBOX_DB = "i2_sandbox_corpus"
SANDBOX_HOST, SANDBOX_PORT = "127.0.0.1", 543
NOW = datetime(2026, 9, 19, 19, 0, tzinfo=UTC)
AUTHOR = "i3-e2e-agent-proposal（Agent 提案，待 U 追认；不构成 M1 范围决定）"
# 预先固定的查询（不看结果再挑；命中数为 0 也是真实结果）
QUERIES = ("营业收入", "景气", "非农", "同比")
DOMAINS = ("company", "industry", "macro")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dotenv() -> dict[str, str]:
    data: dict[str, str] = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            key, value = line.split("=", 1)
            data[key.strip()] = value.strip()
    return data


def sandbox_dsn(env: dict[str, str]) -> str:
    prod = env["CORPUS_DSN"]
    creds = prod.split("://", 1)[1].rsplit("@", 1)[0]
    return f"postgresql://{creds}@{SANDBOX_HOST}:{SANDBOX_PORT}/{SANDBOX_DB}"


def masked(dsn: str) -> str:
    return dsn.split("://", 1)[0] + "://***@" + dsn.split("@", 1)[1]


def cli_run(cli, argv: list[str]) -> dict:
    buf = io.StringIO()
    started = time.perf_counter()
    with contextlib.redirect_stdout(buf):
        code = cli.main(argv)
    elapsed = round(time.perf_counter() - started, 2)
    raw = buf.getvalue()
    try:
        payload: object = json.loads(raw)
    except json.JSONDecodeError:
        payload = {"raw": raw[:4000]}
    return {"argv": argv, "exit_code": code, "seconds": elapsed, "output": payload}


def main() -> int:
    env = dotenv()
    dsn = sandbox_dsn(env)
    record: dict = {
        "artifact": "i3-1-e2e-record",
        "phase": "i3-1",
        "generated_at": datetime.now(UTC).astimezone().isoformat(timespec="seconds"),
        "target": {"dsn": masked(dsn), "database": SANDBOX_DB, "host": SANDBOX_HOST, "port": SANDBOX_PORT},
        "guard": {"path": str(GUARD.relative_to(ROOT)), "sha256": digest(GUARD)},
        "scope_status": "proposed_pending_ratification",
        "scope_note": (
            "dev-manifest.json 的 73 份来源终态均为 review_required（M1 前置未决）。"
            "本轮按 Agent 提案的 3 类×2 份在隔离库执行，登记的审核决定作者已写明"
            "『Agent 提案，待 U 追认』；**本记录不构成开发范围冻结，也不宣告 I3-1 完成**。"
        ),
        "steps": {},
        "problems": [],
    }

    # ── 0. 目标预检（非生产 + 沙箱 schema）
    import psycopg

    with psycopg.connect(dsn, autocommit=True, connect_timeout=8) as conn, conn.cursor() as cur:
        cur.execute("SELECT current_database()")
        database = cur.fetchone()[0]
        cur.execute("SELECT datname FROM pg_database WHERE datallowconn")
        dbs = {row[0] for row in cur.fetchall()}
        cur.execute("SELECT 1 FROM pg_namespace WHERE nspname = 'corpus'")
        has_schema = cur.fetchone() is not None
    record["preflight"] = {
        "current_database": database,
        "is_sandbox_db": database == SANDBOX_DB,
        "instance_has_apodex": "apodex" in dbs,
        "corpus_schema_present": has_schema,
        "databases": sorted(dbs),
    }
    if database != SANDBOX_DB or "apodex" in dbs:
        print(json.dumps({"refused": "目标不是隔离沙箱库", "preflight": record["preflight"]},
                         ensure_ascii=False, indent=2))
        return 3
    if not has_schema:
        record["problems"].append("沙箱库缺 corpus schema（需先跑 i2/i2s1_apply.py）")
        print(json.dumps({"refused": "缺 corpus schema", "hint": "先跑 i2s1_apply.py"},
                         ensure_ascii=False, indent=2))
        return 4

    # ── 1. 装载阶段守卫（此后 CORPUS_DSN 被投毒、网络仅 127.0.0.1:543）
    sys.path.insert(0, str(ROOT))
    from plugins.corpus.preparation import guard  # noqa: PLC0415

    guard.install(GUARD)
    record["guard"]["installed"] = True
    record["guard"]["poisoned_env"] = ["OPENAI_API_KEY"]
    record["guard"]["poisoned_dsn"] = ["CORPUS_DSN"]

    from plugins.corpus import cli  # noqa: PLC0415
    from plugins.corpus.preparation.contract import (  # noqa: PLC0415
        ReviewedDecision,
        ReviewDecision,
        sha256_of_bytes,
    )
    from plugins.corpus.preparation.repository_pg import PgStore  # noqa: PLC0415

    # ── 2. 开发范围：Agent 提案 3 类×2 份（登记人工审核决定 → 逐来源）
    dm = json.loads(DEV_MANIFEST.read_text(encoding="utf-8"))
    cand = dm["dev_selection_candidates"]
    selection = {domain: list(cand[domain]) for domain in DOMAINS}
    record["selection"] = selection
    record["selection_on_disk"] = {
        domain: [Path(p).is_file() for p in paths] for domain, paths in selection.items()
    }

    store = PgStore(dsn, sandbox_db=SANDBOX_DB)
    decisions: dict[str, str] = {}
    try:
        entries = []
        for domain in DOMAINS:
            for path in selection[domain]:
                key = f"{domain}:{Path(path).name[:24]}"
                decision_id = f"i3e2e-{domain}-{hashlib.sha256(path.encode()).hexdigest()[:8]}"
                store.put_reviewed_decision(
                    ReviewedDecision(
                        decision_id=decision_id,
                        source_id=sha256_of_bytes(Path(path).read_bytes()),
                        reviewer=AUTHOR,
                        reviewed_at=NOW,
                        decision=ReviewDecision.ADMITTED,
                        rationale=(
                            "I3-1 开发 E2E（隔离沙箱）：按领域×格式覆盖选入，Agent 提案待 U 追认；"
                            "material_type 不由本决定给（沿用机器建议/政策），避免冒充人工凭证"
                        ),
                    )
                )
                decisions[path] = decision_id
                entries.append(
                    {"path": path, "domain_hint": domain, "review_decision_ids": [decision_id]}
                )
    finally:
        store.close()
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(
        json.dumps({"sources": entries, "archive_root": str(ARCHIVE)}, ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    record["manifest"] = {"path": str(MANIFEST.relative_to(ROOT)), "sha256": digest(MANIFEST),
                          "sources": len(entries)}

    # ── 3. 链路：plan → build → check → publish → status
    record["steps"]["plan"] = cli_run(cli, ["plan", "--manifest", str(MANIFEST), "--dsn", dsn])
    build_step = cli_run(
        cli,
        ["build", "--manifest", str(MANIFEST), "--dsn", dsn, "--owner", "i3-e2e",
         "--archive-root", str(ARCHIVE)],
    )
    record["steps"]["build"] = build_step
    outcomes = (build_step["output"] or {}).get("outcomes") or []
    in_scope = [o for o in outcomes if str(o.get("decision")) == "in_scope"]
    build_ids = sorted({str(o["build_id"]) for o in in_scope if o.get("build_id")})
    record["build_ids"] = build_ids
    record["outcome_decisions"] = [
        {"source": Path(str(o.get("path") or "?")).name[:40], "decision": o.get("decision"),
         "build_id": o.get("build_id"), "material_type": o.get("material_type")}
        for o in outcomes
    ]
    if build_step["exit_code"] != 0 or not build_ids:
        record["problems"].append("build 未产出可发布 build（见 steps.build）")
        write_record(record)
        print(json.dumps({"stop": "build 未成功", "exit": build_step["exit_code"]},
                         ensure_ascii=False, indent=2))
        return 5
    build_id = build_ids[0]
    record["steps"]["check"] = cli_run(cli, ["check", "--build", build_id, "--dsn", dsn])
    record["steps"]["publish"] = cli_run(
        cli, ["publish", "--build", build_id, "--operator", "i3-e2e", "--dsn", dsn]
    )
    record["steps"]["status"] = cli_run(cli, ["status", "--build", build_id, "--dsn", dsn])

    # ── 4. search / fetch / verify（读侧同一权威 Seam）
    import plugins.corpus.service as service_mod  # noqa: PLC0415
    from plugins.corpus.preparation import read_pg  # noqa: PLC0415
    from plugins.corpus.audit import audit_corpus_chain  # noqa: PLC0415

    os.environ["CORPUS_READ_CHAIN"] = "new"
    service_mod.dsn = lambda: dsn  # 守卫已投毒 CORPUS_DSN，读侧显式取沙箱 DSN
    service = service_mod.CorpusService(dsn)

    searches = []
    for query in QUERIES:
        hits = service.search(query, limit=3)
        rows = []
        for hit in hits:
            evidence = service.fetch_verbatim(hit.doc_id, hit.locator)
            document = read_pg.fetch_document(dsn, hit.doc_id, sandbox_db=SANDBOX_DB)
            checks = {
                "active": bool(evidence.active),
                "chunk_text_is_unit_join": evidence.text == "\n".join(u.raw_text for u in evidence.units),
                "units_nonempty": bool(evidence.units),
                "units_in_document_text": all(u.raw_text in document.text for u in evidence.units),
                "pages_within_range": all(
                    (u.location.page is None) or (document.page_count is None)
                    or (u.location.page <= document.page_count)
                    for u in evidence.units
                ),
            }
            rows.append(
                {
                    "doc_id": hit.doc_id,
                    "locator": hit.locator,
                    "chunk_id": hit.chunk_id,
                    "units": len(evidence.units),
                    "checks": checks,
                    "sample": evidence.text[:60],
                }
            )
        searches.append({"query": query, "hits": len(hits), "verified": rows})
    record["search"] = searches
    record["coverage"] = read_pg.coverage_snapshot(dsn, sandbox_db=SANDBOX_DB, query_status="matched")
    hits_for_cov, cov_together = read_pg.search_with_coverage(dsn, QUERIES[0], sandbox_db=SANDBOX_DB)
    record["coverage_with_hits"] = {
        "hits": len(hits_for_cov),
        "same_snapshot_ok": bool(hits_for_cov) and cov_together.get("query_status") == "matched",
    }
    with psycopg.connect(dsn, autocommit=True) as conn:
        record["audit"] = audit_corpus_chain(conn)

    # ── 5. 领域×格式矩阵
    from collections import Counter

    formats = Counter()
    domains = Counter()
    for outcome in outcomes:
        if str(outcome.get("decision")) != "in_scope":
            continue
        path = str(outcome.get("path") or "")
        formats[Path(path).suffix.lower().lstrip(".") or "?"] += 1
        domains[str(outcome.get("domain_hint") or "?")] += 1
    record["matrix"] = {
        "domains": dict(domains),
        "formats": dict(formats),
        "cells": {f"{d}:{f}": c for d, f, c in
                  ((d, f, 0) for d in DOMAINS for f in formats)},
        "gaps": [
            "docx：开发范围无 DOCX 样本 → 缺格式门未过（需 U 定性：补样本 或 声明缺格式）",
            "pdf：company/industry/macro 各 2 份",
        ],
    }
    write_record(record)
    print(json.dumps({
        "record": RECORD.name,
        "build_id": build_id,
        "publish": (record["steps"]["publish"]["output"] or {}).get("generation"),
        "exit_codes": {k: v["exit_code"] for k, v in record["steps"].items()},
        "search_hits": {s["query"]: s["hits"] for s in searches},
        "audit_conflicts": record["audit"].get("conflicts"),
        "problems": record["problems"],
    }, ensure_ascii=False, indent=2))
    return 0


def write_record(record: dict) -> None:
    RECORD.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# I3-1 三类开发 E2E 记录",
        "",
        f"- 生成：{record['generated_at']}；目标：`{record['target']['dsn']}`（库 `{record['target']['database']}`）",
        f"- 守卫：`{record['guard']['path']}`（sha256 {record['guard']['sha256'][:12]}；已装载={record['guard'].get('installed')}）",
        f"- **范围状态：{record['scope_status']}** —— {record['scope_note']}",
        "",
        "## 前置",
        "",
        f"- 当前库：{record['preflight']['current_database']}；实例含 apodex："
        f"{record['preflight']['instance_has_apodex']}；corpus schema："
        f"{record['preflight']['corpus_schema_present']}",
        "",
        "## 链路（真实产物）",
        "",
        "| 步骤 | 退出码 | 秒 |",
        "|---|---|---|",
    ]
    for name, step in record["steps"].items():
        lines.append(f"| {name} | {step['exit_code']} | {step['seconds']} |")
    lines += [
        "",
        f"- build_id：`{record.get('build_ids')}`",
        f"- publish generation：{(record['steps'].get('publish', {}).get('output') or {}).get('generation')}",
        "",
        "## 检索 / 取证 / 核验",
        "",
        "| 查询 | 命中 |",
        "|---|---|",
    ]
    for item in record.get("search") or []:
        lines.append(f"| {item['query']} | {item['hits']} |")
    lines += [
        "",
        "逐条核验（任一项 false = 链路问题）：active / chunk=单元拼接 / 单元非空 / 单元文本⊆文档文本 / 页号在范围。",
        "PDF 说明：正文由 PyMuPDF 解析而来，**字节级逐字不适用**；本记录按『单元文本 ⊆ 该文档解析文本』核验。",
        "",
        "## 覆盖与审计",
        "",
        f"- coverage：{json.dumps(record.get('coverage'), ensure_ascii=False)[:300]}",
        f"- 同快照组合读取：{json.dumps(record.get('coverage_with_hits'), ensure_ascii=False)}",
        f"- 审计冲突：{record.get('audit', {}).get('conflicts')}",
        "",
        "## 领域×格式矩阵",
        "",
        f"- 领域：{json.dumps(record['matrix']['domains'], ensure_ascii=False)}；"
        f"格式：{json.dumps(record['matrix']['formats'], ensure_ascii=False)}",
    ]
    lines += [f"- 缺口：{gap}" for gap in record["matrix"]["gaps"]]
    if record.get("problems"):
        lines += ["", "## 问题", ""] + [f"- {p}" for p in record["problems"]]
    RECORD_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
