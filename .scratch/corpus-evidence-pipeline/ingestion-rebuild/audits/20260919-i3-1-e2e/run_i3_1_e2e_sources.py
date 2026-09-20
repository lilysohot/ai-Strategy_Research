"""I3-1 第二阶段：**逐来源** check/publish，再对已发布集合做 search/fetch/verify。

第一阶段（run_i3_1_e2e.py）一次 build 六份来源；本阶段对**每个 build 单独**过门——
这样"某一份因缺口不可发布"不会掩盖其余来源的真实结果，也是 I3-1 要求的领域×格式矩阵来源。
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1]
ROOT = HERE.parents[4]
GUARD = BASE / "guards/i3-e2e.json"
FIRST = HERE / "i3-1-e2e-record.json"
OUT = HERE / "i3-1-e2e-sources.json"
OUT_MD = HERE / "i3-1-e2e-sources.md"
SANDBOX_DB = "i2_sandbox_corpus"
QUERIES = ("营业收入", "景气", "非农", "同比")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dotenv() -> dict[str, str]:
    data: dict[str, str] = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            key, value = line.split("=", 1)
            data[key.strip()] = value.strip()
    return data


def strip_banner(text: str) -> tuple[object, str | None]:
    """CLI 约定 stdout 为 JSON；PyMuPDF 会先打印一行横幅 → 记录污染并取首个 '{' 起解析。"""

    try:
        return json.loads(text), None
    except json.JSONDecodeError:
        index = text.find("{")
        if index > 0:
            try:
                return json.loads(text[index:]), text[:index].strip()
            except json.JSONDecodeError:
                pass
        return {"raw": text[:2000]}, None


def cli_run(cli, argv: list[str]) -> dict:
    buf = io.StringIO()
    started = time.perf_counter()
    with contextlib.redirect_stdout(buf):
        code = cli.main(argv)
    elapsed = round(time.perf_counter() - started, 2)
    payload, banner = strip_banner(buf.getvalue())
    result = {"argv": argv, "exit_code": code, "seconds": elapsed, "output": payload}
    if banner:
        result["stdout_prefix_pollution"] = banner[:160]
    return result


def main() -> int:
    env = dotenv()
    creds = env["CORPUS_DSN"].split("://", 1)[1].rsplit("@", 1)[0]
    dsn = f"postgresql://{creds}@127.0.0.1:543/{SANDBOX_DB}"
    first = json.loads(FIRST.read_text(encoding="utf-8"))
    outcomes = [
        o for o in (first["steps"]["build"]["output"] or {}).get("outcomes") or []
        if str(o.get("decision")) == "in_scope"
    ]
    record: dict = {
        "artifact": "i3-1-e2e-per-source",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "target": {"dsn": f"postgresql://***@127.0.0.1:543/{SANDBOX_DB}", "database": SANDBOX_DB},
        "guard": {"path": str(GUARD.relative_to(ROOT)), "sha256": digest(GUARD)},
        "scope_status": "proposed_pending_ratification",
        "sources": [],
        "findings": [],
    }

    sys.path.insert(0, str(ROOT))
    from plugins.corpus.preparation import guard  # noqa: PLC0415

    guard.install(GUARD)
    from plugins.corpus import cli  # noqa: PLC0415

    for outcome in outcomes:
        build_id = str(outcome["build_id"])
        name = str(outcome.get("original_name") or "?")
        row: dict = {
            "original_name": name,
            "build_id": build_id,
            "source_id": outcome.get("source_id"),
            "unit_count": outcome.get("unit_count"),
            "chunk_count": outcome.get("chunk_count"),
            "format": Path(name).suffix.lower().lstrip("."),
            "domain": next((d for d in ("company", "industry", "macro") if d in name.lower()), None),
        }
        checked = cli_run(cli, ["check", "--build", build_id, "--dsn", dsn])
        row["check"] = {
            "exit_code": checked["exit_code"],
            "seconds": checked["seconds"],
            "publishable": (checked["output"] or {}).get("publishable"),
            "gap_summary": (checked["output"] or {}).get("gap_summary"),
            "gaps": [
                {
                    "key": gap.get("key"),
                    "code": gap.get("code"),
                    "status": gap.get("status"),
                    "disposition": gap.get("disposition"),
                    "remedy": gap.get("remedy"),
                }
                for gap in (checked["output"] or {}).get("gaps") or []
            ],
        }
        if checked.get("stdout_prefix_pollution"):
            row["check"]["stdout_prefix_pollution"] = checked["stdout_prefix_pollution"]
        if checked["exit_code"] == 0:
            published = cli_run(
                cli, ["publish", "--build", build_id, "--operator", "i3-e2e", "--dsn", dsn]
            )
            row["publish"] = {
                "exit_code": published["exit_code"],
                "generation": (published["output"] or {}).get("generation"),
                "active_build_id": (published["output"] or {}).get("active_build_id"),
            }
        else:
            row["publish"] = {
                "exit_code": checked["exit_code"],
                "blocked": True,
                "why": (checked["output"] or {}).get("error"),
            }
        record["sources"].append(row)

    # 读侧：对已发布集合做 search/fetch/verify
    import plugins.corpus.service as service_mod  # noqa: PLC0415
    from plugins.corpus.audit import audit_corpus_chain  # noqa: PLC0415
    from plugins.corpus.preparation import read_pg  # noqa: PLC0415

    os.environ["CORPUS_READ_CHAIN"] = "new"
    service_mod.dsn = lambda: dsn
    service = service_mod.CorpusService(dsn)

    searches = []
    for query in QUERIES:
        hits = service.search(query, limit=5)
        rows = []
        for hit in hits:
            evidence = service.fetch_verbatim(hit.doc_id, hit.locator)
            document = read_pg.fetch_document(dsn, hit.doc_id, sandbox_db=SANDBOX_DB)
            rows.append(
                {
                    "doc_id": hit.doc_id,
                    "locator": hit.locator,
                    "units": len(evidence.units),
                    "active": bool(evidence.active),
                    "chunk_text_is_unit_join": evidence.text
                    == "\n".join(u.raw_text for u in evidence.units),
                    "units_in_document_text": all(u.raw_text in document.text for u in evidence.units),
                    "sample": evidence.text[:70],
                }
            )
        searches.append({"query": query, "hits": len(hits), "verified": rows})
    record["search"] = searches
    record["published_sources"] = [
        r["original_name"] for r in record["sources"] if (r.get("publish") or {}).get("exit_code") == 0
    ]
    record["blocked_sources"] = [
        {"name": r["original_name"], "gaps": [
            g for g in r["check"]["gaps"] if g.get("disposition") not in ("acknowledged",)
        ]}
        for r in record["sources"] if (r.get("publish") or {}).get("exit_code") != 0
    ]
    record["coverage"] = read_pg.coverage_snapshot(dsn, sandbox_db=SANDBOX_DB, query_status="matched")
    with __import__("psycopg").connect(dsn, autocommit=True) as conn:
        record["audit"] = audit_corpus_chain(conn)

    # findings：如实登记本轮观察到的缺陷/边界
    record["findings"] = [
        {
            "id": "F1",
            "what": "CLI `plan` 的 stdout 被 PyMuPDF 横幅（『Consider using the pymupdf_layout package…』）污染",
            "effect": "严格按 JSON 解析 stdout 的调用方会解析失败；本阶段已改为取首个 `{` 起解析并记录前缀",
            "evidence": {
                "step": "plan",
                "prefix": ((first["steps"]["plan"]["output"] or {}).get("raw") or "")[:120],
            },
            "suggest": "PyMuPDF 输出应改道 stderr（或 plan 阶段显式抑制）；属 CLI stdout 契约缺陷，建议单列修复",
        },
        {
            "id": "F2",
            "what": "开发范围 73 份来源终态仍为 review_required（M1 未决）",
            "effect": "本轮按 Agent 提案 3 类×2 份执行，登记决定作者已写明待追认；I3-1 不能据此宣告完成",
            "suggest": "U 批准范围后重跑并冻结该清单",
        },
        {
            "id": "F3",
            "what": "docx 无开发样本",
            "effect": "格式矩阵缺一格；按任务口径『缺格式门未过』登记",
            "suggest": "U 定性：补 DOCX 样本 或 声明缺格式",
        },
    ]
    OUT.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_md(record)
    print(json.dumps({
        "sources": len(record["sources"]),
        "published": len(record["published_sources"]),
        "blocked": [b["name"][:40] for b in record["blocked_sources"]],
        "search_hits": {s["query"]: s["hits"] for s in searches},
        "audit_conflicts": record["audit"].get("conflicts"),
        "matrix": {r["domain"]: r["format"] for r in record["sources"]},
    }, ensure_ascii=False, indent=2))
    return 0


def write_md(record: dict) -> None:
    lines = [
        "# I3-1 三类开发 E2E（逐来源结果）",
        "",
        f"- 生成：{record['generated_at']}；目标 `{record['target']['dsn']}`；守卫 sha256 "
        f"{record['guard']['sha256'][:12]}",
        f"- **范围状态：{record['scope_status']}**（见 findings F2）",
        "",
        "## 逐来源门与发布",
        "",
        "| 来源 | 格式 | 单元/切块 | check | publish | 阻断缺口 |",
        "|---|---|---|---|---|---|",
    ]
    for row in record["sources"]:
        blocking = [g["code"] + "@" + str(g.get("key", "")) for g in row["check"]["gaps"]
                    if g.get("disposition") not in ("acknowledged",)]
        lines.append(
            f"| {row['original_name'][:42]} | {row['format']} | {row['unit_count']}/{row['chunk_count']} "
            f"| {row['check']['exit_code']}（{'可发布' if row['check']['publishable'] else '不可发布'}） "
            f"| {row['publish']['exit_code']} | {'；'.join(blocking) or '无'} |"
        )
    lines += ["", "## 检索 / 取证 / 核验（已发布集合）", "", "| 查询 | 命中 |", "|---|---|"]
    for item in record.get("search") or []:
        lines.append(f"| {item['query']} | {item['hits']} |")
    lines += [
        "",
        f"- 已发布：{[n[:34] for n in record['published_sources']]}",
        f"- 覆盖：{json.dumps(record.get('coverage'), ensure_ascii=False)[:240]}",
        f"- 审计冲突：{record.get('audit', {}).get('conflicts')}",
        "",
        "## Findings",
        "",
    ]
    for finding in record["findings"]:
        lines.append(f"- **{finding['id']}** {finding['what']} → {finding['effect']}；建议：{finding['suggest']}")
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
