"""Human gap-review packet for the blocked E6 holdout materials (E6 follow-up).

Nine of the twelve holdout materials failed the *normal* fail-closed publication
gate on real reading-quality gaps.  The gate cannot be satisfied by code alone:
each blocked gap needs a human to say whether the material is good enough as it
stands (``acknowledged``) or must be re-extracted (see the closure report).  This
script does not make that call and writes **no** ``human-gap-review`` — it only
assembles the evidence a reviewer needs:

- the gap inventory per material (page + gap kind), taken from the frozen gate
  result, not re-derived;
- which of the 51 holdout targets this material blocks, with the quote each one
  needs, so the reviewer can weigh the actual cost of shipping the gap;
- what *was* extracted on each gap page, read straight from the isolated
  ``e6_holdout_corpus`` under a read-only transaction, so the reviewer can see
  the shape of the loss (e.g. a page whose lines are drawn as a table but whose
  units are all plain paragraphs).

Outputs, next to this file::

    uv run python .scratch/corpus-access-validation/e6_review_packet.py

    e6-human-gap-review-packet.md     for the reviewer
    e6-human-gap-review-packet.json   same data, machine-readable

The production corpus database is never touched, and no decision row is written.
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
TARGET_DB = "e6_holdout_corpus"
BUILD_RESULT = HERE / "e6-holdout-build.json"
DELIVERY_RESULT = HERE / "e6-data-delivery-holdout.json"
OUT_MD = HERE / "e6-human-gap-review-packet.md"
OUT_JSON = HERE / "e6-human-gap-review-packet.json"

#: ``issue:<kind>:page:<n>`` — the only shape the gate emits.
GAP_RE = re.compile(r"^issue:(?P<kind>[a-z_]+):page:(?P<page>\d+)$")
#: Enough of a page to judge the loss without pasting the whole study.
PREVIEW_CHARS = 200
PREVIEW_UNITS = 4

sys.path.insert(0, str(ROOT))
os.chdir(ROOT)


def load_blocked_materials(path: Path) -> list[dict]:
    """The gate-rejected materials, with ``{page: [gap kinds]}``."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    blocked: list[dict] = []
    for source in payload.get("sources", []):
        if source.get("outcome") != "blocked_by_publish_gate":
            continue
        pages: dict[int, list[str]] = {}
        for region in source.get("quality_report", {}).get("gap_regions", []):
            match = GAP_RE.match(str(region))
            if match:
                pages.setdefault(int(match.group("page")), []).append(match.group("kind"))
        blocked.append({**source, "gap_pages": dict(sorted(pages.items()))})
    return blocked


def load_blocked_targets(path: Path) -> dict[str, list[dict]]:
    """Holdout targets that were never offered a source, grouped by material."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    by_sample: dict[str, list[dict]] = {}
    for target in payload.get("targets", []):
        if target.get("source_offered"):
            continue
        by_sample.setdefault(str(target["sample_id"]), []).append(target)
    return by_sample


def _read_only_connection():
    from dotenv import load_dotenv
    from psycopg import connect
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    load_dotenv(ROOT / ".env")
    os.environ["CORPUS_TARGET_DB"] = TARGET_DB
    os.environ.pop("PGOPTIONS", None)
    from plugins.corpus.service import dsn

    # A read-only transaction, not just a convention: this packet must not be
    # able to publish, re-extract or record a decision even by mistake.
    target = make_conninfo(
        **{**conninfo_to_dict(dsn()), "dbname": TARGET_DB,
           "options": "-c default_transaction_read_only=on"}
    )
    return connect(target, autocommit=True)


def _material_context(conn, source_id: str, build_id: str) -> dict:
    row = conn.execute(
        "select original_names, format, size_bytes from corpus.corpus_sources "
        "where source_id = %s", (source_id,)
    ).fetchone()
    names = list(row[0] or []) if row else []
    build = conn.execute(
        "select parse_rev, clean_rev, chunk_rev from corpus.corpus_builds "
        "where build_id = %s", (build_id,)
    ).fetchone()
    revisions = dict(zip(("parse_rev", "clean_rev", "chunk_rev"), build or ())) if build else {}
    return {"file_names": names, "format": row[1] if row else "", "revisions": revisions}


def _page_evidence(conn, build_id: str, page: int) -> dict:
    """What the pipeline actually kept on one gap page."""
    rows = conn.execute(
        "select kind, status, reasons, left(coalesce(clean_view, raw_text, ''), %s) "
        "from corpus.corpus_units "
        "where build_id = %s and (location ->> 'page')::int = %s "
        "order by ordinal",
        (PREVIEW_CHARS, build_id, page),
    ).fetchall()
    kinds = Counter(str(kind) for kind, _status, _reasons, _text in rows)
    statuses = Counter(str(status) for _kind, status, _reasons, _text in rows)
    previews = [
        {
            "kind": str(kind),
            "status": str(status),
            "reasons": [str(r) for r in (reasons or [])],
            "chars": len(text or ""),
            "text": (text or "").strip(),
        }
        for kind, status, reasons, text in rows
        if (text or "").strip()
    ][:PREVIEW_UNITS]
    return {
        "unit_count": len(rows),
        "by_kind": dict(sorted(kinds.items())),
        "by_status": dict(sorted(statuses.items())),
        "table_units": kinds.get("table", 0),
        "previews": previews,
    }


def build_packet() -> dict:
    blocked = load_blocked_materials(BUILD_RESULT)
    targets_by_sample = load_blocked_targets(DELIVERY_RESULT)
    conn = _read_only_connection()
    try:
        materials: list[dict] = []
        for source in blocked:
            sample_id = str(source["sample_id"])
            build_id = str(source["build_id"])
            context = _material_context(conn, str(source["source_id"]), build_id)
            pages = [
                {
                    "page": page,
                    "gap_kinds": kinds,
                    "evidence": _page_evidence(conn, build_id, page),
                }
                for page, kinds in source["gap_pages"].items()
            ]
            materials.append({
                "sample_id": sample_id,
                "domain": source.get("domain", ""),
                "source_id": source["source_id"],
                "build_id": build_id,
                "unit_count": source.get("unit_count"),
                "chunk_count": source.get("chunk_count"),
                "outcome": source.get("outcome"),
                "gate_error": source.get("error", ""),
                "gap_pages": [{"page": p["page"], "gap_kinds": p["gap_kinds"]} for p in pages],
                "page_evidence": pages,
                "blocked_targets": [
                    {
                        "target_id": t.get("target_id"),
                        "role": t.get("role"),
                        "question": t.get("question"),
                        "expected_quote": t.get("expected_quote"),
                        "dependencies": t.get("dependencies"),
                        "first_fail": t.get("first_fail"),
                    }
                    for t in targets_by_sample.get(sample_id, [])
                ],
                **context,
            })
    finally:
        conn.close()

    return {
        "artifact": "e6-human-gap-review-packet",
        "note": ("Evidence only. No decision is recorded and no human-gap-review "
                 "is written; the closed form at the end of each section is for a "
                 "human reviewer to fill in."),
        "source_artifacts": {
            "gate": BUILD_RESULT.name,
            "delivery": DELIVERY_RESULT.name,
            "corpus_db": TARGET_DB,
        },
        "summary": {
            "materials": len(materials),
            "blocked_targets": sum(len(m["blocked_targets"]) for m in materials),
            "materials_published": 3,
            "materials_total": 12,
        },
        "materials": materials,
    }


def _fmt_kinds(kinds: list[str]) -> str:
    return ", ".join(f"`{k}`" for k in kinds)


def _fmt_counts(counts: dict[str, int]) -> str:
    return ", ".join(f"{k} {v}" for k, v in counts.items()) or "-"


def render_markdown(packet: dict) -> str:
    summary = packet["summary"]
    lines = [
        "# E6 留出材料人工缺口复核包",
        "",
        f"> {packet['note']}",
        "",
        "## 范围",
        "",
        f"- 留出材料：**{summary['materials_total']}** 份，其中 **{summary['materials_published']}** 份已过发布门，"
        f"**{summary['materials']}** 份因真实读取质量缺口被阻断。",
        f"- 被阻断目标：**{summary['blocked_targets']}** 项，全部表现为 `source_not_offered`"
        "（非模型、检索或分页错误）。",
        "- 缺口与页面来自冻结的门禁结果 `e6-holdout-build.json`；页面证据只读自隔离库 "
        f"`{packet['source_artifacts']['corpus_db']}`（只读事务），未重跑构建、未写入任何裁决。",
        "",
        "## 复核方式",
        "",
        "逐份判定，三选一并在「裁决」栏签名：",
        "",
        "- `acknowledged`：承认缺口，按现状发布（需写明为何该缺口不影响目标证据）；",
        "- `re-extract`：需重新提取/更换解析，该材料暂不放行；",
        "- `reject`：材料或目标不可用。",
        "",
        "完成后重跑隔离构建与 51 项数据送达验证；在达到 51/51 之前 E6 与端到端总任务保持未关闭。",
        "",
    ]
    for index, material in enumerate(packet["materials"], start=1):
        targets = material["blocked_targets"]
        revisions = material["revisions"]
        rev_text = ", ".join(f"{k}={v}" for k, v in revisions.items()) or "未记录"
        lines += [
            f"## {index}. `{material['sample_id']}`（{material['domain']}）",
            "",
            f"- 来源文件：`{material['file_names'][0] if material['file_names'] else '未知'}`",
            f"- `source_id`：`{material['source_id']}`",
            f"- `build_id`：`{material['build_id']}`",
            f"- 修订：{rev_text}",
            f"- 规模：units {material['unit_count']} / chunks {material['chunk_count']}",
            f"- 门禁结论：`{material['outcome']}`",
            f"- 门禁原因：{material['gate_error']}",
            "",
            "### 缺口页",
            "",
            "| 页 | 缺口类型 | 该页已提取单元 | 单元类型分布 | table 单元 |",
            "|---:|---|---:|---|---:|",
        ]
        for entry in material["page_evidence"]:
            evidence = entry["evidence"]
            lines.append(
                f"| {entry['page']} | {_fmt_kinds(entry['gap_kinds'])} | "
                f"{evidence['unit_count']} | {_fmt_counts(evidence['by_kind'])} | "
                f"{evidence['table_units']} |"
            )
        lines += ["", "### 缺口页已提取文本样例", ""]
        for entry in material["page_evidence"]:
            lines.append(f"**第 {entry['page']} 页**")
            lines.append("")
            for preview in entry["evidence"]["previews"]:
                reasons = f" reasons={preview['reasons']}" if preview["reasons"] else ""
                lines.append(
                    f"- `{preview['kind']}`/{preview['status']}{reasons} "
                    f"（{preview['chars']} 字）：{preview['text']}"
                )
            if not entry["evidence"]["previews"]:
                lines.append("- （该页无任何已提取文本——整页内容均未进入语料）")
            lines.append("")
        lines += [
            f"### 被本材料阻断的目标（{len(targets)}）",
            "",
            "| target_id | role | 所需引文 | 依赖 | 问题 |",
            "|---|---|---|---|---|",
        ]
        for target in targets:
            deps = target.get("dependencies") or {}
            dep_text = ", ".join(k for k, v in deps.items() if v) or "-"
            quote = (target.get("expected_quote") or "").replace("|", "\\|").replace("\n", " ")
            question = (target.get("question") or "").replace("|", "\\|").replace("\n", " ")
            lines.append(
                f"| `{target['target_id']}` | {target['role']} | {quote} | {dep_text} | {question} |"
            )
        lines += [
            "",
            "### 裁决（待人工填写；本包不代签）",
            "",
            "- [ ] `acknowledged`　- [ ] `re-extract`　- [ ] `reject`",
            "- reviewer：__________　日期：__________",
            "- 理由：______________________________________________",
            "",
        ]
    return "\n".join(lines)


def main() -> int:
    packet = build_packet()
    OUT_JSON.write_text(json.dumps(packet, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_MD.write_text(render_markdown(packet), encoding="utf-8")
    summary = packet["summary"]
    print(f"materials={summary['materials']} blocked_targets={summary['blocked_targets']}")
    print(f"wrote {OUT_MD.name} and {OUT_JSON.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())