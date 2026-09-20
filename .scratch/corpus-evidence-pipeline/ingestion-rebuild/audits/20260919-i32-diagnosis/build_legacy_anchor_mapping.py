"""Step B：旧检索 golden 的 **旧锚点 → 新 source 身份** 映射 + 公式输入字段声明。

证据来源（全部仓库内、零模型）：
- `plugins/corpus/golden.py::GOLDEN_SET`（20 题，旧锚点 = (title_contains, doc_prefix)）；
- `.scratch/corpus-evidence-pipeline/ingestion-rebuild/i0a5-doclist-recount-20260915.json`
  （旧文档目录：`doc_id`（`YYYY-MM-DD_<8hex>`）、`title`、`source_path`）——这正是旧 golden 运行时的文档标题来源；
- `plugins/corpus/derivation.py`（7 个公式的输入指标声明）。

产出：
- `legacy-anchor-mapping.json` / `.md`（每题每锚点的候选文档 + 匹配依据 + 是否已确认）；
- 就地更新 `baseline-case-manifest.json` / `.md`：legacy 类的映射状态与 formula_7 的输入字段。

**不猜**：匹配不到或多候选一律标 `ambiguous`/`unmatched` 并 `confirmed=false`，交人工确认。
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1]
ROOT = HERE.parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CATALOG = BASE / "i0a5-doclist-recount-20260915.json"
GOLDEN = ROOT / "plugins/corpus/golden.py"
DERIVATION = ROOT / "plugins/corpus/derivation.py"
MANIFEST = HERE / "baseline-case-manifest.json"
MANIFEST_MD = HERE / "baseline-case-manifest.md"
OUT = HERE / "legacy-anchor-mapping.json"
OUT_MD = HERE / "legacy-anchor-mapping.md"
HELDOUT_REASON = "O6（华泰证券联储加息）来源属留出（d571f138 在 guards/i3.json forbidden_roots），r27 已排除"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def now() -> str:
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


def norm(text: str) -> str:
    return re.sub(r"[\s\-_（）()【】\[\]，,。.：:；;、/]", "", str(text)).lower()


def load_catalog() -> list[dict]:
    data = json.loads(CATALOG.read_text(encoding="utf-8"))
    docs = []
    for doc in data.get("documents") or []:
        docs.append(
            {
                "doc_id": doc.get("doc_id"),
                "title": doc.get("title"),
                "source_path": doc.get("source_path"),
                "published": doc.get("published"),
                "status": doc.get("status"),
            }
        )
    return docs


def match_anchor(anchor_title: str, anchor_prefix: str, docs: list[dict]) -> dict:
    """归一化子串优先；否则退回"最长 token 命中"评分。"""

    target = norm(anchor_title)
    prefix = str(anchor_prefix or "")
    pool = [d for d in docs if not prefix or str(d.get("doc_id") or "").startswith(prefix)]
    exact = [d for d in pool if target and target in norm(d.get("title") or "")]
    if exact:
        return {"basis": "title_substring", "candidates": exact}
    tokens = [t for t in re.findall(r"[\u4e00-\u9fff]{2,}|\d{2,}", str(anchor_title))]
    scored = []
    for doc in pool:
        title = norm(doc.get("title") or "")
        hits = [t for t in tokens if norm(t) in title]
        if hits:
            scored.append((len(hits), max(len(t) for t in hits), doc))
    scored.sort(key=lambda row: (-row[0], -row[1]))
    best = [row for row in scored if row[0] == scored[0][0]] if scored else []
    return {
        "basis": "token_overlap" if best else "unmatched",
        "candidates": [row[2] for row in best],
        "matched_tokens": sorted({t for row in best for t in tokens if norm(t) in norm(row[2].get("title") or "")}) if best else [],
    }


def formula_inputs() -> dict[str, list[str]]:
    text = DERIVATION.read_text(encoding="utf-8")
    found: dict[str, list[str]] = {}
    for name in (
        "revenue_growth",
        "parent_profit_growth",
        "operating_cash_growth",
        "cash_profit_ratio",
        "net_margin",
        "balance_residual",
        "profit_residual",
    ):
        match = re.search(rf'"{name}":\s*\(([^)]*)\)', text)
        if match:
            found[name] = [item.strip().strip('"') for item in match.group(1).split(",") if item.strip()]
    return found


def build() -> dict:
    from plugins.corpus.golden import GOLDEN_SET  # type: ignore

    docs = load_catalog()
    questions = []
    for question in GOLDEN_SET:
        if question.qid == "O6":
            questions.append(
                {
                    "qid": "O6",
                    "question": question.question,
                    "kind": question.kind,
                    "require_all": question.require_all,
                    "status": "excluded_holdout",
                    "reason": HELDOUT_REASON,
                    "anchors": [],
                }
            )
            continue
        anchors = []
        for matcher in question.expects:
            title = str(getattr(matcher, "title_contains", ""))
            prefix = str(getattr(matcher, "doc_prefix", "") or "")
            matched = match_anchor(title, prefix, docs)
            candidates = [
                {
                    "doc_id": doc.get("doc_id"),
                    "title": doc.get("title"),
                    "source_path": doc.get("source_path"),
                    "candidate_source_id": doc.get("doc_id"),
                }
                for doc in matched["candidates"][:3]
            ]
            status = (
                "resolved_unique"
                if len(candidates) == 1
                else ("ambiguous" if len(candidates) > 1 else "unmatched")
            )
            anchors.append(
                {
                    "old_anchor": {"title_contains": title, "doc_prefix": prefix},
                    "match_basis": matched["basis"],
                    "matched_tokens": matched.get("matched_tokens"),
                    "candidates": candidates,
                    "status": status,
                    "confirmed": False,
                }
            )
        statuses = {a["status"] for a in anchors}
        status = (
            "resolved_unique"
            if statuses == {"resolved_unique"}
            else ("unmatched" if statuses == {"unmatched"} else "needs_human_confirm")
        )
        questions.append(
            {
                "qid": question.qid,
                "question": question.question,
                "kind": question.kind,
                "require_all": question.require_all,
                "status": status,
                "anchors": anchors,
            }
        )
    counts: dict[str, int] = {}
    for question in questions:
        counts[question["status"]] = counts.get(question["status"], 0) + 1
    inputs = formula_inputs()
    # 校验：①co 目录 source_path 是否在磁盘；②映射到的 doc_id 是否与已标注 source-gold 同源身份空间
    annotated = set()
    for line in (BASE / "source-gold-frozen.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            annotated.add(json.loads(line)["source_id"])
    path_ok = path_bad = 0
    matched_annotated: list[str] = []
    for question in questions:
        for anchor in question["anchors"]:
            for candidate in anchor["candidates"]:
                source_path = str(candidate.get("source_path") or "")
                if source_path and (ROOT / source_path).is_file():
                    path_ok += 1
                    if str(candidate.get("doc_id")) in annotated:
                        matched_annotated.append(str(candidate["doc_id"]))
                else:
                    path_bad += 1
    verification = {
        "source_path_exists": path_ok,
        "source_path_missing": path_bad,
        "doc_id_space": (
            "i0a5-doclist 的 doc_id 后缀是**内容哈希**，与 data/corpus 文件名后缀不是同一哈希空间；"
            "doc_id 与已标注 source-gold 的 source_id 同源（样例见下），因此锚点校验用 source_path + title，"
            "不用文件名后缀"
        ),
        "doc_ids_matching_annotated_source_gold": sorted(set(matched_annotated)),
        "note": "映射到的 doc_id 若在已标注 source-gold 中，可直接复用其 locator 体系；否则待该题进入开发范围时按同一 id 约定接入",
    }
    return {
        "artifact": "i3-2-legacy-anchor-mapping",
        "generated_at": now(),
        "status": "first_pass_pending_human_confirm",
        "inputs": {
            "golden": {"path": str(GOLDEN.relative_to(ROOT)), "sha256": digest(GOLDEN)},
            "doc_catalog": {"path": str(CATALOG.relative_to(ROOT)), "sha256": digest(CATALOG)},
            "derivation": {"path": str(DERIVATION.relative_to(ROOT)), "sha256": digest(DERIVATION)},
        },
        "mapping_rule": (
            "旧锚点 (title_contains, doc_prefix) → 旧文档目录 i0a5-doclist 的 doc_id（`YYYY-MM-DD_<8hex>`，"
            "即新体系的 source 身份）；先做归一化标题子串匹配，失败退回最长 CJK/数字 token 命中；"
            "多候选/零候选一律标 ambiguous/unmatched 且 confirmed=false"
        ),
        "verification": verification,
        "counts": counts,
        "question_count": len([q for q in questions if q["status"] != "excluded_holdout"]),
        "questions": questions,
        "formula_inputs": inputs,
    }


def patch_manifest(mapping: dict) -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    by_qid = {q["qid"]: q for q in mapping["questions"]}
    for category in manifest["categories"]:
        name = category["categories"][0]
        if name == "legacy_retrieval_golden":
            for case in category["cases"]:
                qid = str(case.get("qid"))
                mapped = by_qid.get(qid)
                if not mapped:
                    continue
                if mapped["status"] == "excluded_holdout":
                    case["new_locator_or_mapping_rule"] = "excluded（留出；不进入本轮适用范围）"
                    continue
                case["new_locator_or_mapping_rule"] = {
                    "rule": mapping["mapping_rule"],
                    "mapping_file": str(OUT.relative_to(ROOT)),
                    "status": mapped["status"],
                    "anchors": [
                        {
                            "old_anchor": a["old_anchor"],
                            "status": a["status"],
                            "doc_id": (a["candidates"][0]["doc_id"] if len(a["candidates"]) == 1 else None),
                            "candidates": [c["doc_id"] for c in a["candidates"]],
                            "confirmed": a["confirmed"],
                        }
                        for a in mapped["anchors"]
                    ],
                }
            for gap in category["gaps"]:
                if gap.get("item") == "旧锚点→新 locator 映射":
                    gap["status"] = "mapped_pending_human_confirm"
                    gap["detail"] = (
                        "首轮映射已产出（旧锚点→i0a5-doclist 的 doc_id）：唯一 "
                        f"{mapping['counts'].get('resolved_unique', 0)} 题、多候选 "
                        f"{mapping['counts'].get('needs_human_confirm', 0)} 题、零候选 "
                        f"{mapping['counts'].get('unmatched', 0)} 题；O6 留出排除"
                    )
                    gap["resolution_doc"] = str(OUT.relative_to(ROOT))
                    gap["question"] = (
                        "多候选/零候选题需人工确认（或补充旧 doc_id 权威清单）："
                        + "、".join(
                            f"{q['qid']}({q['status']})"
                            for q in mapping["questions"]
                            if q["status"] in {"needs_human_confirm", "unmatched"}
                        )
                    )
        if name == "formula_7":
            inputs = mapping["formula_inputs"]
            for case in category["cases"]:
                case["input_metrics"] = inputs.get(str(case.get("formula")))
                case["input_metrics_source"] = str(DERIVATION.relative_to(ROOT))
            for gap in category["gaps"]:
                if gap.get("item", "").startswith("输入字段"):
                    gap["status"] = "confirmed"
                    gap["detail"] = (
                        "已按 plugins/corpus/derivation.py 的公式输入声明逐条登记"
                        f"（{len(inputs)}/7 条）"
                    )
                    gap.pop("proposed_default", None)
    manifest["legacy_anchor_mapping"] = {
        "path": str(OUT.relative_to(ROOT)),
        "sha256": digest(OUT),
        "status": mapping["status"],
        "counts": mapping["counts"],
    }
    manifest["generated_at"] = now()
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_markdown(mapping: dict) -> None:
    lines = ["# 旧检索 golden：旧锚点 → 新 source 身份映射（首轮，待人工确认）", ""]
    lines.append(f"- 生成：{mapping['generated_at']}；状态：**{mapping['status']}**")
    lines.append(f"- 输入：`golden.py` `{mapping['inputs']['golden']['sha256'][:12]}…`；"
                 f"`i0a5-doclist-recount-20260915.json` `{mapping['inputs']['doc_catalog']['sha256'][:12]}…`")
    lines.append(f"- 规则：{mapping['mapping_rule']}")
    lines.append(f"- 计数：{json.dumps(mapping['counts'], ensure_ascii=False)}（O6 留出排除）")
    lines.append("")
    lines.append("| 题 | kind | 锚点 | 匹配依据 | 结论 | 文档 |")
    lines.append("|---|---|---|---|---|---|")
    for question in mapping["questions"]:
        if question["status"] == "excluded_holdout":
            lines.append(f"| {question['qid']} | {question['kind']} | — | — | **留出排除** | — |")
            continue
        for anchor in question["anchors"]:
            docs = "；".join(str(c["doc_id"]) for c in anchor["candidates"]) or "—"
            lines.append(
                f"| {question['qid']} | {question['kind']} | `{anchor['old_anchor']['title_contains']}`"
                f"（prefix={anchor['old_anchor']['doc_prefix'] or '—'}） | {anchor['match_basis']} | "
                f"{anchor['status']} | {docs} |"
            )
    lines.append("")
    lines.append("## 公式输入字段（来自 `plugins/corpus/derivation.py`）")
    lines.append("")
    for name, inputs in mapping["formula_inputs"].items():
        lines.append(f"- `{name}` ← {'、'.join(inputs)}")
    lines.append("")
    lines.append("## 待人工确认")
    lines.append("")
    pending = [q for q in mapping["questions"] if q["status"] in {"needs_human_confirm", "unmatched"}]
    if pending:
        for question in pending:
            lines.append(f"- **{question['qid']}**（{question['status']}）：{question['question']}")
            for anchor in question["anchors"]:
                if anchor["status"] != "resolved_unique":
                    lines.append(
                        f"  - 锚点 `{anchor['old_anchor']['title_contains']}`（prefix="
                        f"{anchor['old_anchor']['doc_prefix'] or '—'}）→ "
                        f"{[c['doc_id'] for c in anchor['candidates']] or '零候选'}"
                    )
    else:
        lines.append("- 无（全部唯一命中）")
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    mapping = build()
    OUT.write_text(json.dumps(mapping, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_markdown(mapping)
    patch_manifest(mapping)
    print(json.dumps(
        {
            "counts": mapping["counts"],
            "formula_inputs": {k: len(v) for k, v in mapping["formula_inputs"].items()},
            "pending": [
                {"qid": q["qid"], "status": q["status"],
                 "anchors": [a["status"] for a in q["anchors"]]}
                for q in mapping["questions"]
                if q["status"] in {"needs_human_confirm", "unmatched"}
            ],
            "mapping_sha256": digest(OUT),
            "manifest_sha256": digest(MANIFEST),
        },
        ensure_ascii=False, indent=2,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
