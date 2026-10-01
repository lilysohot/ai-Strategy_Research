"""Mechanical gap-vs-evidence *pre-screen* for the blocked E6 holdout materials.

The human gap-review packet (``e6_review_packet.py``) hands a reviewer the gap
inventory and the blocked targets, but leaves the reviewer to work out, one
target at a time, whether the gap actually hides the evidence that target needs.
This script does that cross-check mechanically, and only mechanically:

for every blocked target it asks whether the quote the target requires is
already present in the text the frozen build *did* extract, and whether the
page(s) holding that text are the same pages the publication gate flagged.

Deliberately *not* a decision.  It never writes ``human-gap-review``, never
publishes, and never treats "found" as "acknowledged" — a reviewer still signs
each material in the packet.  The direction column is a reading aid, labelled as
such, and is derived from a literal text comparison that has real limits: it
does not re-run search or paginated fetch (the builds are unpublished, so a real
delivery cannot be attempted), and a quote can in principle be present yet still
be unreachable through the normal retrieval path.  Both limits are stated in the
output.

Outputs, next to this file::

    uv run python .scratch/corpus-access-validation/e6_gap_prescreen.py

    e6-gap-prescreening.md     for the reviewer
    e6-gap-prescreening.json   same data, machine-readable

The production corpus database is never touched; the isolated holdout database
is opened in a read-only transaction.
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import e6_review_packet as pq  # noqa: E402  (same directory, shared loaders)

OUT_MD = HERE / "e6-gap-prescreening.md"
OUT_JSON = HERE / "e6-gap-prescreening.json"

#: Highlight markup that search projections may embed; never part of the text.
MARKUP_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")
#: Sentence-ish boundaries — the granularity at which partial loss is reported.
SPLIT_RE = re.compile(r"[；;。\n]+")
#: Shorter fragments match almost anything Chinese; not evidence of anything.
MIN_FRAGMENT = 4

#: Gap kinds that do not sit over running text.  ``image_region_small`` is on
#: nearly every page of these reports, so on its own it says nothing about
#: whether a given quote survived; every other kind is treated as potentially
#: evidence-hiding (an unknown kind is therefore read conservatively).
BENIGN_GAP_KINDS = {"image_region_small"}

OUTCOME_LABELS = {
    "intact": "缺口不遮挡：引文已完整提取，且证据页无缺口",
    "benign_overlap": "轻微交集：引文已完整提取，证据页仅有小图片区域缺口",
    "overlap": "实质交集：引文已完整提取，但证据页带可能遮挡的缺口",
    "noise_only": "仅存于 noise 单元：投递不会送达",
    "partial": "部分提取：引文有片段未进已提取文本",
    "absent": "未见提取：引文完全不在已提取文本中",
    "no_quote": "无引文：无法预筛",
}

#: Reading aid only.  ``leaning-*`` is not a verdict and carries no signature.
DIRECTIONS = {
    "intact": "leaning-acknowledge",
    "benign_overlap": "leaning-acknowledge",
    "overlap": "needs-human",
    "noise_only": "leaning-re-extract",
    "partial": "leaning-re-extract",
    "absent": "leaning-re-extract",
    "no_quote": "needs-human",
}


def _normalize(text: str) -> str:
    """NFKC + strip markup/whitespace, so ＂２２２４ 元＂ matches ＂2224元＂."""
    s = unicodedata.normalize("NFKC", text or "")
    return WS_RE.sub("", MARKUP_RE.sub("", s))


def _fragments(quote_norm: str) -> list[str]:
    frags = [p for p in SPLIT_RE.split(quote_norm) if len(p) >= MIN_FRAGMENT]
    return frags or ([quote_norm] if quote_norm else [])


def _load_units(conn, build_id: str) -> list[tuple]:
    return conn.execute(
        "select unit_id, kind, status, coalesce(clean_view, raw_text, ''), "
        "(location ->> 'page') "
        "from corpus.corpus_units where build_id = %s order by ordinal",
        (build_id,),
    ).fetchall()


def _text_index(rows: list[tuple]) -> dict:
    """Normalized text of the build, whole-document and per page, kept vs all."""
    kept_all: list[str] = []
    all_all: list[str] = []
    kept_pages: dict[int, list[str]] = {}
    all_pages: dict[int, list[str]] = {}
    kinds: Counter = Counter()
    statuses: Counter = Counter()
    for _unit_id, kind, status, text, page in rows:
        kinds[str(kind)] += 1
        statuses[str(status)] += 1
        norm = _normalize(text or "")
        if not norm:
            continue
        all_all.append(norm)
        page_no = int(page) if page is not None else None
        if page_no is not None:
            all_pages.setdefault(page_no, []).append(norm)
        if str(status) == "kept":
            kept_all.append(norm)
            if page_no is not None:
                kept_pages.setdefault(page_no, []).append(norm)
    return {
        "kept_all": "".join(kept_all),
        "all_all": "".join(all_all),
        "kept_pages": {p: "".join(v) for p, v in kept_pages.items()},
        "all_pages": {p: "".join(v) for p, v in all_pages.items()},
        "kinds": dict(sorted(kinds.items())),
        "statuses": dict(sorted(statuses.items())),
    }


def _prescreen_target(target: dict, index: dict, gap_pages: dict[int, list[str]]) -> dict:
    quote = str(target.get("expected_quote") or "")
    quote_norm = _normalize(quote)
    record: dict = {
        "target_id": target.get("target_id"),
        "role": target.get("role"),
        "question": target.get("question"),
        "quote_chars": len(quote),
    }
    if not quote_norm:
        return {**record, "outcome": "no_quote", "coverage": None,
                "fragments_total": 0, "fragments_found": 0,
                "evidence_pages": [], "overlap_pages": [], "note": "该目标未记录 expected_quote"}

    frags = _fragments(quote_norm)
    found = [f for f in frags if f in index["all_all"]]
    coverage = len(found) / len(frags)
    full_kept = quote_norm in index["kept_all"]
    full_all = quote_norm in index["all_all"]

    kept_pages: set[int] = set()
    noise_pages: set[int] = set()
    spanning = False
    for frag in found:
        hits = {p for p, txt in index["kept_pages"].items() if frag in txt}
        if hits:
            kept_pages |= hits
        elif any(frag in txt for txt in index["all_pages"].values()):
            noise_pages |= {p for p, txt in index["all_pages"].items() if frag in txt}
        else:  # present only when fragments are concatenated across a page break
            spanning = True

    overlap = sorted(kept_pages & set(gap_pages))
    overlap_kinds = sorted({k for p in overlap for k in gap_pages[p]})
    serious_overlap = sorted(k for k in overlap_kinds if k not in BENIGN_GAP_KINDS)
    if full_kept:
        if not kept_pages:
            outcome = "overlap"
        elif not overlap:
            outcome = "intact"
        else:
            outcome = "overlap" if serious_overlap else "benign_overlap"
    elif full_all:
        outcome = "noise_only"
    elif coverage > 0:
        outcome = "partial"
    else:
        outcome = "absent"

    notes: list[str] = []
    if outcome == "intact":
        notes.append("引文全部落在 kept 单元，证据页未被门禁标记")
    elif outcome == "benign_overlap":
        notes.append("证据页仅有 image_region_small：小图片区域不覆盖正文/表格行")
    elif outcome == "overlap":
        if not kept_pages and spanning:
            notes.append("引文跨页拼接，无法定位到单一证据页")
        notes.append("证据页带缺口：" + ", ".join(
            f"page {p}（{', '.join(gap_pages[p])}）" for p in overlap))
    elif outcome == "noise_only":
        notes.append("引文只出现在被判为 noise 的单元中，正常投递不会带回")
    elif outcome == "partial":
        missing = [f for f in frags if f not in index["all_all"]]
        notes.append(f"{len(missing)}/{len(frags)} 个引文片段不在已提取文本中")
        if overlap:
            notes.append("已命中片段位于缺口页：" + ", ".join(str(p) for p in overlap))
    else:
        notes.append("引文与其所有片段均未出现在已提取文本中")
        notes.append("相关缺口页：" + (
            ", ".join(f"page {p}" for p in sorted(gap_pages)) or "无"))
    if noise_pages and outcome != "noise_only":
        notes.append("另有片段落在 noise 单元（页 " + ", ".join(
            str(p) for p in sorted(noise_pages)) + "）")

    return {
        **record,
        "outcome": outcome,
        "direction": DIRECTIONS[outcome],
        "quote_norm": quote_norm,
        "coverage": round(coverage, 4),
        "fragments_total": len(frags),
        "fragments_found": len(found),
        "evidence_pages": sorted(kept_pages),
        "noise_only_pages": sorted(noise_pages),
        "overlap_pages": overlap,
        "overlap_kinds": overlap_kinds,
        "serious_overlap_kinds": serious_overlap,
        "spanning_pages": spanning,
        "note": "；".join(notes),
    }


def build_prescreen() -> dict:
    blocked = pq.load_blocked_materials(pq.BUILD_RESULT)
    targets_by_sample = pq.load_blocked_targets(pq.DELIVERY_RESULT)
    conn = pq._read_only_connection()
    try:
        materials: list[dict] = []
        for source in blocked:
            sample_id = str(source["sample_id"])
            build_id = str(source["build_id"])
            gap_pages = source["gap_pages"]
            index = _text_index(_load_units(conn, build_id))
            rows = [
                _prescreen_target(target, index, gap_pages)
                for target in targets_by_sample.get(sample_id, [])
            ]
            materials.append({
                "sample_id": sample_id,
                "domain": source.get("domain", ""),
                "source_id": source["source_id"],
                "build_id": build_id,
                "gap_pages": [{"page": p, "gap_kinds": k} for p, k in gap_pages.items()],
                "unit_count": source.get("unit_count"),
                "extracted_units": index["statuses"],
                "unit_kinds": index["kinds"],
                "targets": rows,
                "outcome_counts": dict(sorted(Counter(r["outcome"] for r in rows).items())),
            })
    finally:
        conn.close()

    counts = Counter(r["outcome"] for m in materials for r in m["targets"])
    return {
        "artifact": "e6-gap-prescreening",
        "note": ("Mechanical pre-screen only. No decision is recorded and no "
                 "human-gap-review is written; every direction here is a reading "
                 "aid and a reviewer still signs the packet."),
        "method": (
            "对每个被阻断目标，取其 expected_quote，做 NFKC+去空白归一化后，"
            "在冻结 build 的 corpus_units 文本（kept 与全量两套）中做字面比对："
            "整条引文 / 按句切分的片段是否已在已提取文本中，以及命中的证据页是否"
            "落在门禁 gap_regions 标记的页上。"
        ),
        "limitations": [
            "只比对『引文是否已被提取』，不重跑 corpus_search / fetch_plan / corpus_fetch；"
            "被阻断 build 未发布，无法做真实投递验证。",
            "引文存在 ≠ 检索可达：目标仍可能因分块或检索未命中而失败。",
            "方向列（leaning-*）由字面比对机械得出，不是裁决、不带签名。",
        ],
        "source_artifacts": {
            "gate": pq.BUILD_RESULT.name,
            "delivery": pq.DELIVERY_RESULT.name,
            "packet": "e6-human-gap-review-packet.json",
            "corpus_db": pq.TARGET_DB,
        },
        "summary": {
            "materials": len(materials),
            "blocked_targets": sum(len(m["targets"]) for m in materials),
            "outcomes": dict(sorted(counts.items())),
            "directions": dict(sorted(Counter(
                DIRECTIONS[r["outcome"]] for m in materials for r in m["targets"]
            ).items())),
        },
        "materials": materials,
    }


def _fmt_pages(pages: list[int]) -> str:
    return ", ".join(str(p) for p in pages) if pages else "—"


def render_markdown(packet: dict) -> str:
    summary = packet["summary"]
    materials = packet["materials"]
    lines = [
        "# E6 缺口预筛（非裁决）",
        "",
        f"> {packet['note']}",
        "",
        "## 范围",
        "",
        f"- 被阻断材料：**{summary['materials']}** 份；被阻断目标：**{summary['blocked_targets']}** 项。",
        f"- 证据来源：冻结门禁 `{packet['source_artifacts']['gate']}`、"
        f"`{packet['source_artifacts']['delivery']}`，以及隔离库 "
        f"`{packet['source_artifacts']['corpus_db']}`（只读事务）。",
        "",
        "## 方法",
        "",
        packet["method"],
        "",
        "## 已知局限（务必连读）",
        "",
    ]
    lines += [f"- {item}" for item in packet["limitations"]]
    lines += [
        "",
        "## 预筛分布",
        "",
        "| 预筛方向 | 目标数 |",
        "|---|---:|",
    ]
    for direction, count in summary["directions"].items():
        lines.append(f"| `{direction}` | {count} |")
    lines += ["", "| 结果 | 目标数 | 含义 |", "|---|---:|---|"]
    for outcome, count in summary["outcomes"].items():
        lines.append(f"| `{outcome}` | {count} | {OUTCOME_LABELS[outcome]} |")
    lines.append("")

    for index, material in enumerate(materials, start=1):
        targets = material["targets"]
        lines += [
            f"## {index}. `{material['sample_id']}`（{material['domain']}）",
            "",
            f"- `build_id`：`{material['build_id']}`",
            f"- 缺口页：" + (", ".join(
                f"{p['page']}（{', '.join(p['gap_kinds'])}）"
                for p in material["gap_pages"]) or "无"),
            f"- 已提取：units {material['unit_count']}，状态 {material['extracted_units']}",
            f"- 本材料分布：" + (", ".join(
                f"`{k}` {v}" for k, v in material["outcome_counts"].items()) or "无目标"),
            "",
            "| target_id | role | 预筛方向 | 结果 | 引文覆盖 | 证据页 | 交集缺口页 | 说明 |",
            "|---|---|---|---|---:|---|---|---|",
        ]
        for row in targets:
            coverage = "—" if row["coverage"] is None else f"{row['fragments_found']}/{row['fragments_total']}"
            lines.append(
                f"| `{row['target_id']}` | {row['role']} | `{DIRECTIONS[row['outcome']]}` | "
                f"`{row['outcome']}` | {coverage} | {_fmt_pages(row['evidence_pages'])} | "
                f"{_fmt_pages(row['overlap_pages'])} | {row['note']} |"
            )
        lines.append("")

    lines += [
        "## 重申",
        "",
        "本预筛不构成裁决：不改发布门、不写 `human-gap-review`、不代签。",
        "",
        "- `leaning-acknowledge`：引文整条已落在 kept 单元中，证据页最多只有 "
        "`image_region_small`（小图片区域，不覆盖正文/表格行）。仍需人工签署。",
        "- `needs-human`：引文虽已提取，但证据页带 `image_region_unreadable` 或 "
        "`table_lines_without_extraction`，缺口与证据同页，须逐页对照原稿判断。",
        "- `leaning-re-extract`：引文及其片段均未出现在已提取文本中，缺口疑似正压在这条证据上。",
        "",
        "三者都不是终局：是否 `acknowledged` / `re-extract` / `reject` 由人工裁决，"
        "本轮不写任何裁决行。",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    packet = build_prescreen()
    OUT_JSON.write_text(json.dumps(packet, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_MD.write_text(render_markdown(packet), encoding="utf-8")
    summary = packet["summary"]
    print(f"materials={summary['materials']} blocked_targets={summary['blocked_targets']}")
    print(f"outcomes={summary['outcomes']}")
    print(f"directions={summary['directions']}")
    print(f"wrote {OUT_MD.name} and {OUT_JSON.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())