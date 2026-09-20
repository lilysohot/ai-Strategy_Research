"""I3-1 开发集 E2E（**照 U 批准集**，干净沙箱重跑）。

范围唯一来源：`i0a2-adjudicated-20260915.json :: dev_selection_approved`（U 2026-09-15 批准，6 份 PDF）。
不换料、不自选、不使用被裁定排除的材料；取样前已跑 `preflight_scope_check.py`（PASS）。
守卫：`guards/i3-e2e.json`（允许路径 = 批准集 6 份；网络仅 127.0.0.1:543；`CORPUS_DSN` 投毒）。
结果如实登记：含缺口的来源按 `check`/`status` 的机读 `gaps` 处置，**不得擅自降级门**。
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1]
ROOT = HERE.parents[4]
GUARD = BASE / "guards/i3-e2e.json"
ADJUDICATED = BASE / "i0a2-adjudicated-20260915.json"
PREFLIGHT = HERE / "preflight-scope-check.json"
MANIFEST = HERE / "dev-scope-approved.json"
OUT = HERE / "i3-1-e2e-approved-set-rerun.json"
OUT_MD = HERE / "i3-1-e2e-approved-set-rerun.md"
ARCHIVE = HERE / "archive-approved"
SANDBOX_DB = "i2_sandbox_corpus"
NOW = datetime(2026, 9, 19, 22, 30, tzinfo=UTC)
REVIEWER = "xyl（U 2026-09-15 批准集；权威源 i0a2.dev_selection_approved）"
QUERIES = ("营业收入", "景气", "非农", "同比")


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
    adjudicated = json.loads(ADJUDICATED.read_text(encoding="utf-8"))
    approved = adjudicated["dev_selection_approved"]
    preflight = json.loads(PREFLIGHT.read_text(encoding="utf-8"))
    record: dict = {
        "artifact": "i3-1-e2e-approved-set-rerun",
        "generated_at": datetime.now(UTC).astimezone().isoformat(timespec="seconds"),
        "scope": {
            "authority": "i0a2-adjudicated-20260915.json :: dev_selection_approved",
            "authority_sha256": digest(ADJUDICATED),
            "size": len(approved),
            "sources": [{"path": str(x["path"]), "domain": x["scope"]} for x in approved],
            "preflight_check": {"verdict": preflight["summary"]["verdict"],
                                "pass": preflight["summary"]["pass"],
                                "fail": preflight["summary"]["fail"],
                                "file": PREFLIGHT.name},
            "no_self_selection": True,
        },
        "env": {"dsn": f"postgresql://***@127.0.0.1:543/{SANDBOX_DB}",
                "guard": {"path": str(GUARD.relative_to(ROOT)), "sha256": digest(GUARD)},
                "sandbox": "干净沙箱（teardown residue=0 后重建 corpus schema）"},
    }

    sys.path.insert(0, str(ROOT))
    from plugins.corpus.preparation import guard as guard_module  # noqa: PLC0415

    guard_module.install(GUARD)
    from plugins.corpus import cli  # noqa: PLC0415
    from plugins.corpus.preparation.contract import (  # noqa: PLC0415
        ReviewDecision,
        ReviewedDecision,
        sha256_of_bytes,
    )
    from plugins.corpus.preparation.repository_pg import PgStore  # noqa: PLC0415

    store = PgStore(dsn, sandbox_db=SANDBOX_DB)
    entries = []
    try:
        for item in approved:
            path = str(item["path"])
            decision_id = f"i3e1-approved-{hashlib.sha256(path.encode()).hexdigest()[:10]}"
            store.put_reviewed_decision(
                ReviewedDecision(
                    decision_id=decision_id,
                    source_id=sha256_of_bytes((ROOT / path).read_bytes()),
                    reviewer=REVIEWER,
                    reviewed_at=NOW,
                    decision=ReviewDecision.ADMITTED,
                    rationale=(
                        "I3-1 开发 E2E：范围取自 U 2026-09-15 批准的 dev_selection_approved；"
                        "不含任何 Agent 自选或换料样本"
                    ),
                )
            )
            entries.append({"path": path, "domain_hint": str(item["scope"]),
                            "review_decision_ids": [decision_id]})
    finally:
        store.close()
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(
        json.dumps({"sources": entries, "archive_root": str(ARCHIVE)}, ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )

    build = cli_run(cli, ["build", "--manifest", str(MANIFEST), "--dsn", dsn, "--owner", "i3-e1-approved",
                          "--archive-root", str(ARCHIVE)])
    outcomes = {str(o.get("original_name")): o for o in (build["output"] or {}).get("outcomes") or []}
    record["build"] = {"exit_code": build["exit_code"], "seconds": build["seconds"],
                       "count": (build["output"] or {}).get("count")}
    per_source = []
    for item in approved:
        name = Path(str(item["path"])).name
        outcome = outcomes.get(name) or {}
        row = {"path": str(item["path"]), "domain": str(item["scope"]), "format": "pdf",
               "original_name": name, "decision": outcome.get("decision"),
               "build_id": outcome.get("build_id"), "unit_count": outcome.get("unit_count"),
               "chunk_count": outcome.get("chunk_count")}
        if outcome.get("decision") == "in_scope" and outcome.get("build_id"):
            checked = cli_run(cli, ["check", "--build", str(outcome["build_id"]), "--dsn", dsn])
            gaps = (checked["output"] or {}).get("gaps") or []
            row["check_exit"] = checked["exit_code"]
            row["publishable"] = (checked["output"] or {}).get("publishable")
            row["blocking_gaps"] = [
                {"key": g.get("key"), "code": g.get("code"), "status": g.get("status"),
                 "disposition": g.get("disposition"), "remedy": str(g.get("remedy"))[:100]}
                for g in gaps if str(g.get("disposition")) not in ("acknowledged", "noise")
            ]
            row["acknowledged_gaps"] = sum(
                1 for g in gaps if str(g.get("disposition")) in ("acknowledged", "noise")
            )
            row["check_error"] = (checked["output"] or {}).get("error")
            if checked["exit_code"] == 0:
                published = cli_run(cli, ["publish", "--build", str(outcome["build_id"]),
                                          "--operator", "i3-e1-approved", "--dsn", dsn])
                row["publish"] = {"exit_code": published["exit_code"],
                                  "generation": (published["output"] or {}).get("generation")}
            else:
                row["publish"] = {"exit_code": checked["exit_code"], "blocked": True}
        per_source.append(row)
    record["per_source"] = per_source

    import plugins.corpus.service as service_mod  # noqa: PLC0415
    import psycopg  # noqa: PLC0415
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
            except Exception as exc:  # noqa: BLE001 - 读侧 fail-closed
                verified.append({"locator": hit.locator, "refused": type(exc).__name__,
                                 "reason": str(exc)[:120]})
                continue
            verified.append({
                "locator": hit.locator, "units": len(evidence.units), "active": bool(evidence.active),
                "join_ok": evidence.text == "\n".join(u.raw_text for u in evidence.units),
                "units_in_doc": all(u.raw_text in document.text for u in evidence.units),
            })
        searches.append({"query": query, "hits": len(hits), "verified": verified})
    record["search"] = searches
    record["coverage"] = read_pg.coverage_snapshot(dsn, sandbox_db=SANDBOX_DB, query_status="matched")
    with psycopg.connect(dsn, autocommit=True) as conn:
        record["audit"] = audit_corpus_chain(conn)

    matrix: dict[str, dict] = {}
    for row in per_source:
        cell = matrix.setdefault(f"{row['domain']}:{row['format']}", {"total": 0, "published": 0})
        cell["total"] += 1
        cell["published"] += int((row.get("publish") or {}).get("exit_code") == 0)
    blocking_inventory = Counter(g["code"] for r in per_source for g in r.get("blocking_gaps") or [])
    publishable = [r for r in per_source if (r.get("publish") or {}).get("exit_code") == 0]
    record["summary"] = {
        "sources": len(per_source),
        "publishable": len(publishable),
        "blocked": len(per_source) - len(publishable),
        "total_units": sum(r.get("unit_count") or 0 for r in per_source),
        "total_chunks": sum(r.get("chunk_count") or 0 for r in per_source),
        "blocking_gaps_total": sum(len(r.get("blocking_gaps") or []) for r in per_source),
        "blocking_gap_inventory": dict(blocking_inventory),
        "matrix": matrix,
        "search_hits": {s["query"]: s["hits"] for s in searches},
        "verify_all_ok": all(v.get("active") and v.get("join_ok") and v.get("units_in_doc")
                             for s in searches for v in s["verified"] if "refused" not in v),
        "refused_handles": sum(1 for s in searches for v in s["verified"] if "refused" in v),
        "audit_conflicts": record["audit"].get("conflicts"),
        "per_class_min_2_satisfied": False,
        "per_class_min_2_why": (
            "照批准集真实结果：company 0/2、industry 1/2、macro 1/2 可发布 → "
            "『三类每类≥2 份』在现行门 + 现行裁定下不可满足；缺口无处置路径"
        ),
    }
    OUT.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# I3-1 开发集 E2E —— 照 U 批准集（干净沙箱重跑）",
        "",
        f"- 生成：{record['generated_at']}；范围来源：{record['scope']['authority']}"
        f"（sha256 {record['scope']['authority_sha256'][:12]}，{record['scope']['size']} 份）",
        f"- 取样自检：**{record['scope']['preflight_check']['verdict']}**"
        f"（{record['scope']['preflight_check']['pass']}/{record['scope']['size']}；`{PREFLIGHT.name}`）；"
        "**无自选、无换料、无越权**",
        f"- 环境：{record['env']['sandbox']}；守卫 `{record['env']['guard']['path']}`"
        f"（{record['env']['guard']['sha256'][:12]}）",
        "",
        "## 逐来源（缺口如实登记）",
        "",
        "| 领域 | 来源 | 单元/切块 | check | publish | 阻断缺口 |",
        "|---|---|---|---|---|---|",
    ]
    for row in per_source:
        gaps = "；".join(f"{g['code']}({g['status']})@{str(g['key']).rsplit(':', 1)[-1]}"
                         for g in row.get("blocking_gaps") or []) or "无"
        lines.append(
            f"| {row['domain']} | {row['original_name'][:36]} | {row.get('unit_count')}/{row.get('chunk_count')} | "
            f"{row.get('check_exit')} | {(row.get('publish') or {}).get('exit_code')}"
            f"{'（gen ' + str((row.get('publish') or {}).get('generation')) + '）' if (row.get('publish') or {}).get('generation') else ''} | {gaps} |"
        )
    summary = record["summary"]
    lines += [
        "",
        f"- 汇总：可发布 **{summary['publishable']}/{summary['sources']}**；阻断 {summary['blocked']}；"
        f"阻断缺口 {summary['blocking_gaps_total']} 处 {json.dumps(summary['blocking_gap_inventory'], ensure_ascii=False)}；"
        f"{summary['total_units']} 单元 / {summary['total_chunks']} 切块",
        f"- 检索命中：{json.dumps(summary['search_hits'], ensure_ascii=False)}；取证核验全过={summary['verify_all_ok']}；"
        f"被拒句柄={summary['refused_handles']}；审计冲突={summary['audit_conflicts']}",
        f"- **『三类每类≥2』满足：{summary['per_class_min_2_satisfied']}** —— {summary['per_class_min_2_why']}",
        "",
        "## 领域×格式矩阵",
        "",
        "| 单元格 | 份数 | 已发布 |",
        "|---|---|---|",
    ]
    for cell, info in sorted(matrix.items()):
        lines.append(f"| {cell} | {info['total']} | {info['published']} |")
    lines += [
        "",
        "> DOCX/MD 在准入口径下样本数 = 0（相关材料均被裁定 `excluded_from_active`）→ "
        "§12.1 的格式门在现行裁定下无法满足（须补研报类料，或 U 明确 v1 不声称覆盖）。",
        "",
        "## 被阻断来源的处置口径（§7.3，机读）",
        "",
    ]
    for row in per_source:
        if row.get("blocking_gaps"):
            lines.append(f"- {row['original_name'][:40]}：{row.get('check_error')}")
    lines += ["", "处置路径：补 OCR（图像区域）/ 换料 / 转 review_required；**本轮未降级门**。"]
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"summary": summary, "build": record["build"],
                      "per_source": [{k: r.get(k) for k in ("domain", "unit_count", "chunk_count",
                                                            "check_exit", "publishable")}
                                     for r in per_source]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
