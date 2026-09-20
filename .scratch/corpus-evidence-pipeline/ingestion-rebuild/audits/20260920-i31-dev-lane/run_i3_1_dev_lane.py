"""I3-1 第二轮 E2E（U 2026-09-20 裁决：dev lane 纳入 MD + DOCX）。

范围：
- `dev-scope-manifest.json` = U 2026-09-15 批准集 6 份 PDF（逐字保留）
  + dev lane 2 份（`工业富联_投委会决策报告_20260829.md`、`9月8日 光模块…docx`）。
- dev lane 只对 dev 构建生效：装载 `admission-policy-dev.json` 需 `CORPUS_DEV_LANE=1`
  （否则 fail-closed 拒绝）；生产政策 `admission-policy.json`（v1）逐字不改。
- 两份 dev lane 来源各起一条**完整取代链**：生产 `excluded_from_active` → dev `admitted`
  （`material_type` 如实保持 `internal_committee_report` / `internal_unattributed`）。

守卫：`guards/i3-e2e.json`（允许路径 8 份；网络仅 127.0.0.1:543；`CORPUS_DSN` 投毒）。
结果如实登记：含缺口的来源按 `check`/`status` 的机读 `gaps` 处置，**不得擅自降级门**。

用法::

    uv run python .scratch/.../audits/20260920-i31-dev-lane/run_i3_1_dev_lane.py
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
MANIFEST = HERE / "dev-scope-manifest.json"
DEV_POLICY = HERE / "admission-policy-dev.json"
PREFLIGHT = HERE / "preflight-scope-check.json"
PREFLIGHT_FAILCLOSED = HERE / "preflight-scope-check.failclosed-no-dev-lane.json"
OUT = HERE / "i3-1-dev-lane-e2e.json"
OUT_MD = HERE / "i3-1-dev-lane-e2e.md"
ARCHIVE = HERE / "archive-dev-lane"
SANDBOX_DB = "i2_sandbox_corpus"
NOW = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)
REVIEWER = "U（2026-09-20 会话裁决：新建 dev lane；material_type 如实）"
QUERIES = ("营业收入", "景气", "非农", "同比", "工业富联", "光模块")


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
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    dev_policy = json.loads(DEV_POLICY.read_text(encoding="utf-8"))
    dev_by_path = {str(item["path"]): item for item in dev_policy["dev_lane"]["sources"]}
    preflight = json.loads(PREFLIGHT.read_text(encoding="utf-8"))
    failclosed = json.loads(PREFLIGHT_FAILCLOSED.read_text(encoding="utf-8"))
    sources = manifest["sources"]
    record: dict = {
        "artifact": "i3-1-dev-lane-e2e",
        "generated_at": datetime.now(UTC).astimezone().isoformat(timespec="seconds"),
        "scope": {
            "manifest": MANIFEST.name,
            "manifest_sha256": digest(MANIFEST),
            "size": len(sources),
            "approved_set": [s["path"] for s in sources if s.get("provenance") == "approved_set"],
            "dev_lane": [s["path"] for s in sources if s.get("provenance") == "dev_lane"],
            "policy": {"path": DEV_POLICY.name, "sha256": digest(DEV_POLICY),
                       "policy_rev": dev_policy["policy_rev"], "scope": dev_policy["scope"],
                       "lane_id": dev_policy["dev_lane"]["lane_id"],
                       "production_in_scope_unchanged": dev_policy["production_in_scope_unchanged"]},
            "preflight_with_dev_lane": {"verdict": preflight["summary"]["verdict"],
                                        "pass": preflight["summary"]["pass"],
                                        "dev_lane_authorized": preflight["summary"]["dev_lane_authorized"],
                                        "formats": preflight["summary"]["formats_covered_by_pass_set"]},
            "preflight_failclosed_no_dev_lane": {
                "verdict": failclosed["summary"]["verdict"],
                "fail": failclosed["summary"]["fail"],
                "adjudication_conflicts": failclosed["summary"]["adjudication_conflicts"],
                "formats": failclosed["summary"]["formats_covered_by_pass_set"]},
        },
        "env": {"dsn": f"postgresql://***@127.0.0.1:543/{SANDBOX_DB}",
                "guard": {"path": str(GUARD.relative_to(ROOT)), "sha256": digest(GUARD)},
                "dev_lane_env": "CORPUS_DEV_LANE=1",
                "sandbox": "干净沙箱（teardown residue=0 后重建 corpus schema）"},
    }

    os.environ["CORPUS_DEV_LANE"] = "1"
    sys.path.insert(0, str(ROOT))
    from plugins.corpus.preparation import guard as guard_module  # noqa: PLC0415

    guard_module.install(GUARD)
    from plugins.corpus import cli  # noqa: PLC0415
    from plugins.corpus.preparation.contract import (  # noqa: PLC0415
        MaterialType,
        ResearchDomain,
        ReviewDecision,
        ReviewedDecision,
        sha256_of_bytes,
    )
    from plugins.corpus.preparation.repository_pg import PgStore  # noqa: PLC0415

    store = PgStore(dsn, sandbox_db=SANDBOX_DB)
    seeded: list[dict] = []
    try:
        for entry in sources:
            path = str(entry["path"])
            source_id = sha256_of_bytes((ROOT / path).read_bytes())
            domain = ResearchDomain(str(entry["domain_hint"]))
            ids = list(entry["review_decision_ids"])
            if entry.get("provenance") == "approved_set":
                store.put_reviewed_decision(
                    ReviewedDecision(
                        decision_id=ids[0],
                        source_id=source_id,
                        reviewer=REVIEWER,
                        reviewed_at=NOW,
                        decision=ReviewDecision.ADMITTED,
                        rationale="I3-1 第二轮：U 2026-09-15 批准集（逐字保留）",
                        research_domain=domain,
                    )
                )
                seeded.append({"path": path, "decisions": ids, "kind": "approved_set"})
            else:
                lane = dev_by_path[path]
                material = MaterialType(str(lane["material_type"]))
                store.put_reviewed_decision(
                    ReviewedDecision(
                        decision_id=ids[0],
                        source_id=source_id,
                        reviewer="U（i0a2-adjudicated-20260915.json）",
                        reviewed_at=datetime(2026, 9, 15, 8, 20, 52, tzinfo=UTC),
                        decision=ReviewDecision(lane["i0a2_decision"]),
                        rationale=str(lane["i0a2_note"]),
                        material_type=material,
                    )
                )
                store.put_reviewed_decision(
                    ReviewedDecision(
                        decision_id=ids[1],
                        source_id=source_id,
                        reviewer=REVIEWER,
                        reviewed_at=NOW,
                        decision=ReviewDecision.ADMITTED,
                        rationale=(
                            f"dev lane（{dev_policy['dev_lane']['lane_id']}）：{lane['reason']}"
                        ),
                        material_type=material,
                        research_domain=domain,
                        supersedes=ids[0],
                    )
                )
                seeded.append({"path": path, "decisions": ids, "kind": "dev_lane",
                               "material_type": str(lane["material_type"])})
    finally:
        store.close()
    record["seeded_decisions"] = seeded

    ARCHIVE.mkdir(parents=True, exist_ok=True)
    build = cli_run(cli, ["build", "--manifest", str(MANIFEST), "--dsn", dsn,
                          "--owner", "i3-e1-dev-lane", "--archive-root", str(ARCHIVE)])
    outcomes = {str(o.get("original_name")): o for o in (build["output"] or {}).get("outcomes") or []}
    record["build"] = {"exit_code": build["exit_code"], "seconds": build["seconds"],
                       "count": (build["output"] or {}).get("count")}
    per_source = []
    for entry in sources:
        name = Path(str(entry["path"])).name
        outcome = outcomes.get(name) or {}
        fmt = Path(name).suffix.lower().lstrip(".")
        row = {"path": str(entry["path"]), "domain": str(entry["domain_hint"]), "format": fmt,
               "provenance": entry.get("provenance"), "original_name": name,
               "decision": outcome.get("decision"), "material_type": outcome.get("material_type"),
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
                                          "--operator", "i3-e1-dev-lane", "--dsn", dsn])
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
    per_class: dict[str, dict] = {}
    for row in per_source:
        cell = per_class.setdefault(row["domain"], {"total": 0, "published": 0})
        cell["total"] += 1
        cell["published"] += int((row.get("publish") or {}).get("exit_code") == 0)
    format_coverage: dict[str, dict] = {}
    for row in per_source:
        cell = format_coverage.setdefault(row["format"], {"total": 0, "published": 0,
                                                          "sources": []})
        cell["total"] += 1
        cell["published"] += int((row.get("publish") or {}).get("exit_code") == 0)
        cell["sources"].append(Path(row["path"]).name[:40])
    record["summary"] = {
        "sources": len(per_source),
        "publishable": len(publishable),
        "blocked": len(per_source) - len(publishable),
        "total_units": sum(r.get("unit_count") or 0 for r in per_source),
        "total_chunks": sum(r.get("chunk_count") or 0 for r in per_source),
        "blocking_gaps_total": sum(len(r.get("blocking_gaps") or []) for r in per_source),
        "blocking_gap_inventory": dict(blocking_inventory),
        "matrix": matrix,
        "per_class": per_class,
        "format_coverage": format_coverage,
        "formats_claimed": ["pdf", "docx", "md"],
        "formats_with_publishable_sample": sorted(
            f for f, c in format_coverage.items() if c["published"] > 0
        ),
        "format_gate_section_12_1_satisfied": all(
            format_coverage.get(f, {}).get("published", 0) > 0 for f in ("pdf", "docx", "md")
        ),
        "search_hits": {s["query"]: s["hits"] for s in searches},
        "verify_all_ok": all(v.get("active") and v.get("join_ok") and v.get("units_in_doc")
                             for s in searches for v in s["verified"] if "refused" not in v),
        "refused_handles": sum(1 for s in searches for v in s["verified"] if "refused" in v),
        "audit_conflicts": record["audit"].get("conflicts"),
        "per_class_min_2_satisfied": all(c["published"] >= 2 for c in per_class.values()),
    }
    OUT.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    summary = record["summary"]
    lines = [
        "# I3-1 第二轮 E2E —— dev lane 纳入 MD / DOCX（U 2026-09-20 裁决）",
        "",
        f"- 生成：{record['generated_at']}；清单 `{MANIFEST.name}`"
        f"（sha256 {record['scope']['manifest_sha256'][:12]}，{record['scope']['size']} 份）",
        f"- dev lane 政策 `{DEV_POLICY.name}`（{record['scope']['policy']['policy_rev']}，"
        f"scope={record['scope']['policy']['scope']}，lane={record['scope']['policy']['lane_id']}，"
        f"production_in_scope_unchanged={record['scope']['policy']['production_in_scope_unchanged']}）",
        f"- 取样自检（带 `--dev-lane`）：**{record['scope']['preflight_with_dev_lane']['verdict']}**"
        f"（{record['scope']['preflight_with_dev_lane']['pass']}/{record['scope']['size']}，"
        f"dev lane 授权 {record['scope']['preflight_with_dev_lane']['dev_lane_authorized']} 份，"
        f"格式 {record['scope']['preflight_with_dev_lane']['formats']}）",
        f"- fail-closed 反例（不给 `--dev-lane`）：**{record['scope']['preflight_failclosed_no_dev_lane']['verdict']}**"
        f"（fail {record['scope']['preflight_failclosed_no_dev_lane']['fail']}，"
        f"裁定冲突 {record['scope']['preflight_failclosed_no_dev_lane']['adjudication_conflicts']}，"
        f"格式仅 {record['scope']['preflight_failclosed_no_dev_lane']['formats']}）",
        f"- 环境：{record['env']['sandbox']}；守卫 `{record['env']['guard']['path']}`"
        f"（{record['env']['guard']['sha256'][:12]}）；`{record['env']['dev_lane_env']}`",
        "",
        "## 逐来源（缺口如实登记）",
        "",
        "| 领域 | 格式 | 来源 | provenance | 材料类型 | 单元/切块 | check | publish | 阻断缺口 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for row in per_source:
        gaps = "；".join(f"{g['code']}({g['status']})@{str(g['key']).rsplit(':', 1)[-1]}"
                         for g in row.get("blocking_gaps") or []) or "无"
        lines.append(
            f"| {row['domain']} | {row['format']} | {row['original_name'][:32]} | {row.get('provenance')} | "
            f"{row.get('material_type')} | {row.get('unit_count')}/{row.get('chunk_count')} | "
            f"{row.get('check_exit')} | {(row.get('publish') or {}).get('exit_code')}"
            f"{'（gen ' + str((row.get('publish') or {}).get('generation')) + '）' if (row.get('publish') or {}).get('generation') else ''} | {gaps} |"
        )
    lines += [
        "",
        f"- 汇总：可发布 **{summary['publishable']}/{summary['sources']}**；阻断 {summary['blocked']}；"
        f"阻断缺口 {summary['blocking_gaps_total']} 处 {json.dumps(summary['blocking_gap_inventory'], ensure_ascii=False)}；"
        f"{summary['total_units']} 单元 / {summary['total_chunks']} 切块",
        f"- 检索命中：{json.dumps(summary['search_hits'], ensure_ascii=False)}；取证核验全过={summary['verify_all_ok']}；"
        f"被拒句柄={summary['refused_handles']}；审计冲突={summary['audit_conflicts']}",
        f"- 逐类可发布：{json.dumps(summary['per_class'], ensure_ascii=False)}；"
        f"**『每类≥2』满足：{summary['per_class_min_2_satisfied']}**",
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
        "## 格式覆盖（架构 §12.1）",
        "",
        "| 格式 | 份数 | 已发布 | 来源 |",
        "|---|---|---|---|",
    ]
    for fmt, info in sorted(format_coverage.items()):
        lines.append(f"| {fmt} | {info['total']} | {info['published']} | {'；'.join(info['sources'])} |")
    lines += [
        "",
        f"- 声称格式 {summary['formats_claimed']}；有可发布样本的格式 "
        f"**{summary['formats_with_publishable_sample']}**；"
        f"**§12.1 格式门满足：{summary['format_gate_section_12_1_satisfied']}**",
        "",
        "> dev lane 口径：两份新增来源的材料类型如实记为 `internal_committee_report` / "
        "`internal_unattributed`（**不得伪写为研报**）；其 in_scope 仅在 `scope=dev` 政策 + "
        "`CORPUS_DEV_LANE=1` 下成立，生产判定（v1 政策）不变。",
        "",
        "## 被阻断来源的处置口径（§7.3，机读）",
        "",
    ]
    for row in per_source:
        if row.get("blocking_gaps"):
            lines.append(f"- {row['original_name'][:40]}：{row.get('check_error')}")
    lines += ["", "处置路径：补 OCR（图像区域）/ 换料 / 转 review_required；**本轮未降级门**。"]
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"summary": summary, "build": record["build"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
