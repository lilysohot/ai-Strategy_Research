"""I3-1 格式覆盖探针：把 U 补的 DOCX（+ 一份 MD 投委会报告）放进真实链路，看引擎的真实准入判定。

两种口径：
- **口径 A（无材料类型凭证）**：人工决定 ADMITTED 但不给 material_type → 沿用机器建议
  （DOCX=internal_or_unsigned_analysis / MD=internal_committee_report）→ 按 admission.py 次序 2
  预期 `POLICY_CONFLICT` → `REVIEW_REQUIRED`（**这就是"格式门未过"的真实证据**）。
- **口径 B（对照：假设 U 认定该 DOCX 为分析师研报）**：以 `material_type=research_report` 且
  显式 `supersedes` 前一条决定（满足唯一取代链），跑出 DOCX 管道的真实结果（单元/缺口/可发布性）。
  口径 B **不是已批准的决定**，只为让 U 看到"若认定研报会得到什么"。
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
V1_MANIFEST = HERE / "dev-scope-manifest.json"
V2_MANIFEST = HERE / "dev-scope-manifest-v2.json"
OUT = HERE / "i3-1-e2e-format-probe.json"
OUT_MD = HERE / "i3-1-e2e-format-probe.md"
ARCHIVE = HERE / "archive"
SANDBOX_DB = "i2_sandbox_corpus"
NOW = datetime(2026, 9, 19, 20, 0, tzinfo=UTC)
AUTHOR = "i3-e2e-agent-proposal（Agent 提案，待 U 追认；不构成 M1 范围决定）"
DOCX = "data/corpus/9月8日 光模块技术演进与供应链重构：从1.6T到3.2T的路径、格局.docx"
MD = "data/corpus/仕佳光子_投委会决策报告_20260831.md"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dotenv() -> dict[str, str]:
    data: dict[str, str] = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            key, value = line.split("=", 1)
            data[key.strip()] = value.strip()
    return data


def cli_run(cli, argv: list[str]) -> dict:
    buf = io.StringIO()
    started = time.perf_counter()
    with contextlib.redirect_stdout(buf):
        code = cli.main(argv)
    text = buf.getvalue()
    try:
        payload: object = json.loads(text)
    except json.JSONDecodeError:
        index = text.find("{")
        payload = json.loads(text[index:]) if index > 0 else {"raw": text[:2000]}
    return {"argv": argv, "exit_code": code, "seconds": round(time.perf_counter() - started, 2),
            "output": payload}


def main() -> int:
    env = dotenv()
    creds = env["CORPUS_DSN"].split("://", 1)[1].rsplit("@", 1)[0]
    dsn = f"postgresql://{creds}@127.0.0.1:543/{SANDBOX_DB}"

    v1 = json.loads(V1_MANIFEST.read_text(encoding="utf-8"))
    record: dict = {
        "artifact": "i3-1-e2e-format-probe",
        "generated_at": datetime.now(UTC).astimezone().isoformat(timespec="seconds"),
        "target": {"dsn": f"postgresql://***@127.0.0.1:543/{SANDBOX_DB}", "database": SANDBOX_DB},
        "guard": {"path": str(GUARD.relative_to(ROOT)), "sha256": digest(GUARD)},
        "question": "U 补的 DOCX 能否使『格式门』通过？MD（投委会报告）同理",
        "policy_rule": (
            "admission.py 次序 2：admitted 且 material_type ∉ {research_report, unknown} → "
            "POLICY_CONFLICT → REVIEW_REQUIRED；仅 research_report 才 IN_SCOPE"
        ),
        "inputs": {
            "docx": {"path": DOCX, "exists": (ROOT / DOCX).is_file(),
                     "sha256": digest(ROOT / DOCX), "size": (ROOT / DOCX).stat().st_size},
            "md": {"path": MD, "exists": (ROOT / MD).is_file(),
                   "sha256": digest(ROOT / MD) if (ROOT / MD).is_file() else None},
        },
    }

    sys.path.insert(0, str(ROOT))
    from plugins.corpus.preparation import guard  # noqa: PLC0415

    guard.install(GUARD)
    from plugins.corpus import cli  # noqa: PLC0415
    from plugins.corpus.preparation.contract import (  # noqa: PLC0415
        MaterialType,
        ReviewDecision,
        ReviewedDecision,
        sha256_of_bytes,
    )
    from plugins.corpus.preparation.repository_pg import PgStore  # noqa: PLC0415

    extra = [
        {"path": DOCX, "domain_hint": "industry", "label": "docx"},
        {"path": MD, "domain_hint": "company", "label": "md"},
    ]
    entries = list(v1["sources"])
    store = PgStore(dsn, sandbox_db=SANDBOX_DB)
    decision_ids: dict[str, str] = {}
    try:
        for item in extra:
            decision_id = f"i3e2e-{item['label']}-{hashlib.sha256(item['path'].encode()).hexdigest()[:8]}"
            store.put_reviewed_decision(
                ReviewedDecision(
                    decision_id=decision_id,
                    source_id=sha256_of_bytes((ROOT / item["path"]).read_bytes()),
                    reviewer=AUTHOR,
                    reviewed_at=NOW,
                    decision=ReviewDecision.ADMITTED,
                    rationale="口径 A：不给 material_type（沿用机器建议）→ 观察政策判定",
                )
            )
            decision_ids[item["path"]] = decision_id
            entries.append(
                {"path": item["path"], "domain_hint": item["domain_hint"],
                 "review_decision_ids": [decision_id]}
            )
    finally:
        store.close()
    V2_MANIFEST.write_text(
        json.dumps({"sources": entries, "archive_root": str(ARCHIVE)}, ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )

    # ── 口径 A
    build_a = cli_run(cli, ["build", "--manifest", str(V2_MANIFEST), "--dsn", dsn,
                            "--owner", "i3-e2e-format", "--archive-root", str(ARCHIVE)])
    outcomes_a = {
        str(o.get("original_name")): o for o in (build_a["output"] or {}).get("outcomes") or []
    }
    record["pass_a"] = {
        "manifest": str(V2_MANIFEST.relative_to(ROOT)),
        "exit_code": build_a["exit_code"],
        "seconds": build_a["seconds"],
        "new_sources": [
            {
                "path": item["path"],
                "decision": (outcomes_a.get(Path(item["path"]).name) or {}).get("decision"),
                "reason_codes": (outcomes_a.get(Path(item["path"]).name) or {}).get("reason_codes"),
                "material_type": (outcomes_a.get(Path(item["path"]).name) or {}).get("material_type"),
                "build_id": (outcomes_a.get(Path(item["path"]).name) or {}).get("build_id"),
                "raw": json.dumps(outcomes_a.get(Path(item["path"]).name) or {}, ensure_ascii=False)[:400],
            }
            for item in extra
        ],
    }

    # ── 口径 B（对照）：DOCX 认定研报，显式取代前一条决定
    store = PgStore(dsn, sandbox_db=SANDBOX_DB)
    whatif_id = f"{decision_ids[DOCX]}-whatif"
    try:
        store.put_reviewed_decision(
            ReviewedDecision(
                decision_id=whatif_id,
                source_id=sha256_of_bytes((ROOT / DOCX).read_bytes()),
                reviewer=f"{AUTHOR}｜对照口径（未获 U 追认）",
                reviewed_at=NOW,
                decision=ReviewDecision.ADMITTED,
                rationale="口径 B 对照：假设 U 认定该 DOCX 为分析师研报（material_type=research_report）",
                supersedes=decision_ids[DOCX],
                material_type=MaterialType.RESEARCH_REPORT,
            )
        )
    finally:
        store.close()
    build_b = cli_run(cli, ["build", "--manifest", str(V2_MANIFEST), "--dsn", dsn,
                            "--owner", "i3-e2e-format-b", "--archive-root", str(ARCHIVE)])
    outcomes_b = {
        str(o.get("original_name")): o for o in (build_b["output"] or {}).get("outcomes") or []
    }
    docx_outcome = outcomes_b.get(Path(DOCX).name) or {}
    record["pass_b_whatif"] = {
        "supersedes": decision_ids[DOCX],
        "decision_id": whatif_id,
        "exit_code": build_b["exit_code"],
        "docx": {
            "decision": docx_outcome.get("decision"),
            "build_id": docx_outcome.get("build_id"),
            "unit_count": docx_outcome.get("unit_count"),
            "chunk_count": docx_outcome.get("chunk_count"),
        },
    }
    build_id = docx_outcome.get("build_id")
    if build_id:
        checked = cli_run(cli, ["check", "--build", str(build_id), "--dsn", dsn])
        record["pass_b_whatif"]["check"] = {
            "exit_code": checked["exit_code"],
            "publishable": (checked["output"] or {}).get("publishable"),
            "gaps": [
                {"code": g.get("code"), "status": g.get("status"), "disposition": g.get("disposition"),
                 "key": g.get("key")}
                for g in (checked["output"] or {}).get("gaps") or []
            ],
            "error": (checked["output"] or {}).get("error"),
        }
        if checked["exit_code"] == 0:
            published = cli_run(cli, ["publish", "--build", str(build_id), "--operator", "i3-e2e",
                                      "--dsn", dsn])
            record["pass_b_whatif"]["publish"] = {
                "exit_code": published["exit_code"],
                "generation": (published["output"] or {}).get("generation"),
            }
    record["conclusion"] = {
        "docx_under_policy_v1_without_credential": "见 pass_a：预期 REVIEW_REQUIRED（POLICY_CONFLICT）",
        "docx_pipeline_if_admitted": "见 pass_b_whatif：DOCX 管道自身能否出版=看 check",
        "what_U_must_decide": (
            "① 该 DOCX 的材料类型是否为『分析师研报』（人工凭证，只有你能给）；"
            "② 若不是：要么换一份 analyst 类 DOCX，要么批准准入政策 v2（放宽格式/类型）并重跑政策验证"
        ),
        "md_note": "MD（投委会报告=internal_committee_report）同理；本轮未做 MD 的对照口径",
    }
    OUT.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_md(record)
    print(json.dumps({
        "pass_a": record["pass_a"]["new_sources"],
        "pass_b": record["pass_b_whatif"],
        "conclusion": record["conclusion"],
    }, ensure_ascii=False, indent=2)[:2600])
    return 0


def write_md(record: dict) -> None:
    lines = [
        "# I3-1 格式覆盖探针（U 补的 DOCX / MD）",
        "",
        f"- 生成：{record['generated_at']}；问题：{record['question']}",
        f"- 政策规则：{record['policy_rule']}",
        f"- DOCX：`{record['inputs']['docx']['path']}`（{record['inputs']['docx']['size']} 字节，"
        f"sha256 {record['inputs']['docx']['sha256'][:12]}）",
        "",
        "## 口径 A：不给材料类型凭证（真实政策判定）",
        "",
        "| 来源 | decision | reason_codes | material_type | build_id |",
        "|---|---|---|---|---|",
    ]
    for row in record["pass_a"]["new_sources"]:
        lines.append(
            f"| {Path(row['path']).name[:44]} | **{row['decision']}** | {row['reason_codes']} | "
            f"{row['material_type']} | {row['build_id']} |"
        )
    lines += [
        "",
        "## 口径 B（对照，未获追认）：假设 U 认定该 DOCX 为分析师研报",
        "",
        f"- 取代链：`{record['pass_b_whatif']['supersedes']}` → `{record['pass_b_whatif']['decision_id']}`",
        f"- DOCX：decision={record['pass_b_whatif']['docx'].get('decision')}，"
        f"build_id={record['pass_b_whatif']['docx'].get('build_id')}，"
        f"单元 {record['pass_b_whatif']['docx'].get('unit_count')} / 切块 "
        f"{record['pass_b_whatif']['docx'].get('chunk_count')}",
    ]
    check = record["pass_b_whatif"].get("check")
    if check:
        lines += [
            f"- check：exit={check['exit_code']}，publishable={check['publishable']}",
            f"- 缺口：{json.dumps(check['gaps'], ensure_ascii=False)[:500]}",
        ]
        if check.get("error"):
            lines.append(f"- 阻断理由：{check['error']}")
    if record["pass_b_whatif"].get("publish"):
        lines.append(f"- publish：{json.dumps(record['pass_b_whatif']['publish'], ensure_ascii=False)}")
    lines += ["", "## 结论（需要 U 的动作）", ""]
    for key, value in record["conclusion"].items():
        lines.append(f"- **{key}**：{value}")
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
