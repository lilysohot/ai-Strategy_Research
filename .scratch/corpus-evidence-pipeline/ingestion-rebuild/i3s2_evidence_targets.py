"""I3-2 补料：把 source-gold 的 ``locator``/``expected_items`` 映射成 query-gold 30 题的证据目标候选。

**这是机器建议，不是人工金标。** 产物必须经 U 裁决后才能进 I3-2 的正式冻结（架构 §12.1/§12.2：
规则与预期在候选结果可见前冻结；不得模型出题、不得从候选结果倒推答案）。

输入（均只读冻结件，**不读原文正文**）：
- ``query-gold-frozen.jsonl``：30 题（company/industry/macro 各 10，含 6 道 no_answer 负例）
- ``source-gold-frozen.jsonl``：23 个**人工标注**槽位（reviewer=xyl；I0A-4 冻结门已校验 quote 为原文子串）

匹配规则（确定性、可重放；``rule_rev`` 记录版本）：

1. 候选来源池 = 该题 ``relevant_sources`` 命中的槽位（不跨来源）。
2. token 来源 = 人工写的 ``evidence_requirement``，先剥离 ``第N页`` 页码提示（另存 ``page_hints``，
   只供人工对账，不参与匹配）。
3. **数字 token 带边界**（``(?<![\\d.])TOKEN(?![\\d.])``；token 不含 ``%`` 时后面也不得紧跟 ``%``）——
   修复 v1 缺陷："20"（来自"第20页"）命中 "2026"、"2" 命中 "445.2" 这类子串误命中导致 target 爆量。
   4 位年份（1900—2099）与单字符数字记为弱 token，**不参与自动匹配**，只在说明里列出。
4. item 可搜索文本 = ``quote/text/cell/row/col/unit/period/kind`` 归一化后拼接；命中即记一次匹配。
5. 同一 ``(槽位, item 序号)`` 内多个 token 合并为**一个** target（quote 取该 item 的逐字 ``quote``，
   locator 取槽位 ``page``，``source_id`` 取槽位来源）——不重复计数。
6. 状态：全部 token 命中 ⇒ ``mapped``；部分命中 ⇒ ``partial``；零命中或无强 token ⇒ ``needs_human``
   （纯定性题没有可判别的数字线索时**不猜**，只给候选槽位与 item 预览，交人工指定）；
   target 数超过护栏 ⇒ ``needs_human``（匹配过宽会让 EvidencePass 不可达）。
7. 负例题（``no_answer``）⇒ 显式 ``evidence_required=false``（答案为"库中无答案"，天然无证据目标；
   该例外须有独立业务依据，不得用来规避证据缺口）。
8. 无 ``quote`` 的 item 不生成 target，并记 ``item_without_quote``（缺资产可见，不倒推填充）。

分母口径（**裁决点，不由本脚本决定**）：产物同时给出逐 item 目标与 ``aggregation.by_slot`` 槽位聚合视图。
逐 item 严、槽位聚合宽；EvidencePass 的分母口径必须由 U 在 I3-2 冻结时明确选定。

产物（write-once；重跑时自动把当前产物归档为 ``-v<n>`` 再写新版，历史不覆盖）：
- ``i3-2/evidence-targets-candidates.json``
- ``i3-2/evidence-targets-review.md``（逐题核对：requirement ↔ 命中 item ↔ 未命中 token ↔ 页码提示）

用法::

    env -u PYTHONPATH uv run python \
        .scratch/corpus-evidence-pipeline/ingestion-rebuild/i3s2_evidence_targets.py
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[2]
QUERY_GOLD = BASE / "query-gold-frozen.jsonl"
SOURCE_GOLD = BASE / "source-gold-frozen.jsonl"
OUT_DIR = BASE / "i3-2"
OUT_JSON = OUT_DIR / "evidence-targets-candidates.json"
OUT_MD = OUT_DIR / "evidence-targets-review.md"

RULE_REV = "evidence-mapping-3"
_BROAD_LIMIT = 8
_PREVIEW_LIMIT = 12
_WEAK_YEAR = re.compile(r"^(?:19|20)\d{2}$")
_NUMERIC = re.compile(r"\d[\d,]*(?:\.\d+)?%?")
_PAGE_HINT = re.compile(r"第(\d+)页")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fail(message: str) -> None:
    print(f"I3S2 EVIDENCE MAPPING FAILED: {message}")
    sys.exit(1)


def normalize(text: str) -> str:
    """归一化用于 token 匹配：全角空格/逗号/百分号统一、去千分位逗号、压缩空白。"""

    flat = text.replace("\u3000", " ").replace("，", ",").replace("％", "%")
    flat = re.sub(r"(?<=\d),(?=\d)", "", flat)
    return re.sub(r"\s+", "", flat)


def numbers_of(text: str) -> tuple[list[str], list[str]]:
    """(强数字 token, 弱数字 token)；弱 = 4 位年份或单字符数字（不参与自动匹配）。"""

    strong: list[str] = []
    weak: list[str] = []
    for raw in _NUMERIC.findall(text):
        token = normalize(raw)
        if not token:
            continue
        digits = token.rstrip("%").replace(".", "")
        bucket = weak if (_WEAK_YEAR.match(digits) or len(digits) <= 1) else strong
        if token not in bucket:
            bucket.append(token)
    return strong, weak


def token_pattern(token: str) -> re.Pattern[str]:
    """数字 token 的边界匹配：前后不得是数字/小数点；不含 ``%`` 时后面也不得紧跟 ``%``。"""

    escaped = re.escape(token)
    if token.endswith("%"):
        return re.compile(rf"(?<![\d.]){escaped}(?![\d.])")
    return re.compile(rf"(?<![\d.]){escaped}(?![\d.%])")


def load_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def item_text(item: Mapping[str, object]) -> str:
    keys = ("quote", "text", "cell", "row", "col", "unit", "period", "kind")
    return normalize(" ".join(str(item.get(key, "")) for key in keys))


def locator_tokens(slot: Mapping[str, object]) -> tuple[str, ...]:
    locator = slot.get("locator") or {}
    if not isinstance(locator, Mapping):
        return ()
    return tuple(f"{key}:{locator[key]}" for key in sorted(locator) if locator[key] not in (None, ""))


def preview_items(pool: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    """人工指定证据目标时的候选 item 预览（不参与自动匹配，仅降低人工裁决成本）。"""

    previews: list[dict[str, object]] = []
    for slot in pool:
        items = slot.get("expected_items") or ()
        if not isinstance(items, Sequence):
            continue
        for index, item in enumerate(items):
            if not isinstance(item, Mapping):
                continue
            quote = item.get("quote")
            previews.append(
                {
                    "slot": str(slot.get("gold_id")),
                    "item_index": index,
                    "kind": item.get("kind"),
                    "quote_preview": (quote[:60] if isinstance(quote, str) else ""),
                }
            )
    return previews


def base_question(question: Mapping[str, object]) -> dict[str, object]:
    return {
        "query_id": str(question["query_id"]),
        "domain": question.get("domain"),
        "answer_existence": question.get("answer_existence"),
        "evidence_required": True,
        "status": "",
        "status_reason": "",
        "targets": [],
        "unmatched_tokens": [],
        "weak_tokens": [],
        "page_hints": [],
        "candidate_slots": [],
        "item_without_quote": [],
        "review_candidates": [],
        "aggregation": {"by_slot": {}},
    }


def map_question(
    question: Mapping[str, object], slots: Sequence[Mapping[str, object]]
) -> dict[str, object]:
    requirement = str(question.get("evidence_requirement") or "")
    page_hints = [f"page:{value}" for value in _PAGE_HINT.findall(requirement)]
    requirement_clean = _PAGE_HINT.sub("", requirement)

    if question.get("answer_existence") != "answerable":
        result = base_question(question)
        result["evidence_required"] = False
        result["status"] = "negative_opt_out"
        result["status_reason"] = (
            "负例题：答案为『库中无答案』，不适用证据目标，按评分器契约显式 "
            "evidence_required=false（该例外有独立业务依据，不得用于规避证据缺口）"
        )
        return result

    relevant = tuple(str(source) for source in question.get("relevant_sources") or ())
    pool = [slot for slot in slots if slot.get("source_id") in relevant]
    strong, weak = numbers_of(requirement_clean)

    result = base_question(question)
    result["page_hints"] = page_hints
    result["weak_tokens"] = weak
    result["candidate_slots"] = [str(slot.get("gold_id")) for slot in pool]
    if not strong:
        result["status"] = "needs_human"
        result["status_reason"] = (
            "evidence_requirement 中没有可判别的强数字 token"
            + (f"（仅弱 token：{'、'.join(weak)}）" if weak else "（也没有弱 token）")
            + "：纯定性题不猜，请人工从下方候选 item 预览中指定证据目标"
        )
        result["review_candidates"] = preview_items(pool)[:_PREVIEW_LIMIT]
        return result

    patterns = [(token, token_pattern(token)) for token in strong]
    matched: set[str] = set()
    targets: list[dict[str, object]] = []
    item_without_quote: list[str] = []

    for slot in pool:
        gold_id = str(slot.get("gold_id"))
        items = slot.get("expected_items") or ()
        if not isinstance(items, Sequence):
            continue
        for index, item in enumerate(items):
            if not isinstance(item, Mapping):
                continue
            text = item_text(item)
            hits = [token for token, pattern in patterns if pattern.search(text)]
            if not hits:
                continue
            quote = item.get("quote")
            if not isinstance(quote, str) or not quote.strip():
                item_without_quote.append(f"{gold_id}#{index}")
                continue
            matched.update(hits)
            targets.append(
                {
                    "target_id": f"e{len(targets) + 1}",
                    "quote": quote,
                    "locator": list(locator_tokens(slot)),
                    "source_id": str(slot.get("source_id")),
                    "basis": {
                        "gold_id": gold_id,
                        "item_index": index,
                        "kind": item.get("kind"),
                        "matched": hits,
                        "annotation_role": slot.get("annotation_role"),
                        "must_preserve": slot.get("must_preserve"),
                    },
                }
            )

    unmatched = [token for token in strong if token not in matched]
    result["targets"] = targets
    result["unmatched_tokens"] = unmatched
    result["item_without_quote"] = item_without_quote
    if targets and not unmatched:
        result["status"] = "mapped"
    elif targets:
        result["status"] = "partial"
        result["status_reason"] = (
            "部分 token 未在人工标注槽位中找到承载 item（缺标注或需人工指定），"
            "补齐前该题证据分母不完整"
        )
    else:
        result["status"] = "needs_human"
        result["status_reason"] = "全部 token 零命中：不猜，请人工从候选 item 预览中指定证据目标"
        result["review_candidates"] = preview_items(pool)[:_PREVIEW_LIMIT]
    if len(targets) > _BROAD_LIMIT:
        result["status"] = "needs_human"
        result["status_reason"] = (
            f"target 数 {len(targets)} 超过护栏 {_BROAD_LIMIT}（匹配过宽，直接进分母会让 "
            "EvidencePass 不可达）：需人工收窄或改选槽位聚合口径"
        )

    by_slot: dict[str, int] = {}
    for target in targets:
        slot_id = str(target["basis"]["gold_id"])
        by_slot[slot_id] = by_slot.get(slot_id, 0) + 1
    result["aggregation"] = {"by_slot": by_slot}
    return result


def render_markdown(payload: Mapping[str, object]) -> str:
    summary = payload["summary"]
    inputs = payload["inputs"]
    lines = [
        "# I3-2 补料：证据目标候选（待 U 裁决）",
        "",
        f"- 生成时间：{payload['generated_at']}；规则版本：`{payload['rule_rev']}`",
        f"- 输入：`query-gold-frozen.jsonl` sha256={inputs['query_gold']['sha256'][:12]}…、"
        f"`source-gold-frozen.jsonl` sha256={inputs['source_gold']['sha256'][:12]}…",
        f"- 统计：mapped **{summary['mapped']}** ／ partial **{summary['partial']}** ／ "
        f"needs_human **{summary['needs_human']}** ／ 负例显式不做证据评分 "
        f"**{summary['negative_opt_out']}**；候选证据目标合计 **{summary['targets_total']}** 条"
        f"（{summary['questions_total']} 题）",
        "",
        "> 本文件是**机器建议**：证据来源全部是 I0A-4 人工标注槽位（reviewer=xyl），quote 为原文逐字子串；",
        "> 未命中/无法判别一律登记不猜，交人工裁决；匹配过宽超护栏时显式降级为 needs_human。",
        "> **裁决点**：EvidencePass 分母口径（逐 item 严／槽位聚合宽）由 U 在 I3-2 冻结时选定，本脚本不代决。",
        "",
        "> 版本记录：v1（`evidence-mapping-1`）子串匹配致短 token 误命中（`20` 命中 `2026`，"
        "company-003 达 28 条）；v2（`evidence-mapping-2`）用连续汉字串当关键词（整句当词）；"
        "本版 v3 用数字边界匹配 + 无强 token 时显式交人工，历史产物保留为 `-v1`/`-v2` 后缀。",
        "",
    ]
    for question in payload["questions"]:
        lines.append(f"## {question['query_id']}（{question['domain']}，{question['status']}）")
        lines.append("")
        lines.append(f"- evidence_required：`{str(question['evidence_required']).lower()}`")
        if question["candidate_slots"]:
            lines.append(f"- 候选槽位：{'、'.join(question['candidate_slots'])}")
        if question.get("status_reason"):
            lines.append(f"- 说明：{question['status_reason']}")
        if question.get("page_hints"):
            lines.append(f"- 页码提示（不参与匹配）：{'、'.join(question['page_hints'])}")
        for target in question["targets"]:
            basis = target["basis"]
            lines.append(
                f"- `{target['target_id']}` {target['source_id']} {' '.join(target['locator'])}"
                f" ← {basis['gold_id']}#{basis['item_index']}"
                f"（命中 {'、'.join(basis['matched'])}）"
            )
            lines.append(f"    - quote：{target['quote']!r}")
        by_slot = question.get("aggregation", {}).get("by_slot") or {}
        if by_slot:
            lines.append(
                "- 槽位聚合视图（宽口径）："
                + "、".join(f"{slot}×{count}" for slot, count in sorted(by_slot.items()))
            )
        if question["unmatched_tokens"]:
            lines.append(
                f"- **未命中 token（不得猜，待人工裁决）**：{'、'.join(question['unmatched_tokens'])}"
            )
        if question.get("review_candidates"):
            lines.append("- 候选 item 预览（供人工指定目标）：")
            for preview in question["review_candidates"]:
                lines.append(
                    f"    - {preview['slot']}#{preview['item_index']}（{preview['kind']}）"
                    f" {preview['quote_preview']!r}"
                )
        if question.get("item_without_quote"):
            lines.append(
                f"- 无 quote 的 item（缺资产，未生成 target）：{'、'.join(question['item_without_quote'])}"
            )
        lines.append("")
    return "\n".join(lines)


def archive_current() -> list[str]:
    """write-once：把已有当前产物按版本号归档（不覆盖历史）。"""

    archived: list[str] = []
    for current, pattern in ((OUT_JSON, "evidence-targets-candidates-v{}.json"),
                             (OUT_MD, "evidence-targets-review-v{}.md")):
        if not current.is_file():
            continue
        index = 1
        while (OUT_DIR / pattern.format(index)).exists():
            index += 1
        target = OUT_DIR / pattern.format(index)
        current.rename(target)
        archived.append(target.name)
    return archived


def main() -> int:
    for path in (QUERY_GOLD, SOURCE_GOLD):
        if not path.is_file():
            fail(f"缺少输入冻结件：{path}")

    questions = load_jsonl(QUERY_GOLD)
    slots = load_jsonl(SOURCE_GOLD)
    mapped = [map_question(question, slots) for question in questions]

    summary = {
        "questions_total": len(mapped),
        "targets_total": sum(len(item["targets"]) for item in mapped),
        "mapped": sum(1 for item in mapped if item["status"] == "mapped"),
        "partial": sum(1 for item in mapped if item["status"] == "partial"),
        "needs_human": sum(1 for item in mapped if item["status"] == "needs_human"),
        "negative_opt_out": sum(1 for item in mapped if item["status"] == "negative_opt_out"),
    }
    payload = {
        "artifact": "i3-2-evidence-targets-candidates",
        "rule_rev": RULE_REV,
        "generated_at": datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
        "supersedes": [
            {
                "artifact": "i3-2-evidence-targets-candidates-v1",
                "rule_rev": "evidence-mapping-1",
                "defect": (
                    "子串匹配致短 token 误命中：『第20页』的 20 命中 2026 等长数字，候选目标爆量"
                    "（company-003 28 条、company-002 18 条）；定性题也无回退。"
                ),
            },
            {
                "artifact": "i3-2-evidence-targets-candidates-v2",
                "rule_rev": "evidence-mapping-2",
                "defect": (
                    "CJK 关键词用连续汉字串抽取，把整句当词（如『必须取得两份材料』），"
                    "关键词模式既不可用又掩盖了『需人工指定』这一事实。"
                ),
            },
        ],
        "generator": {
            "path": ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i3s2_evidence_targets.py",
            "sha256": digest(Path(__file__)),
        },
        "inputs": {
            "query_gold": {
                "path": ".scratch/corpus-evidence-pipeline/ingestion-rebuild/query-gold-frozen.jsonl",
                "sha256": digest(QUERY_GOLD),
            },
            "source_gold": {
                "path": ".scratch/corpus-evidence-pipeline/ingestion-rebuild/source-gold-frozen.jsonl",
                "sha256": digest(SOURCE_GOLD),
            },
        },
        "summary": summary,
        "questions": mapped,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    archived = archive_current()
    if archived:
        print(f"archived previous revision: {', '.join(archived)}")
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUT_MD.write_text(render_markdown(payload), encoding="utf-8")
    print(f"candidates written: {OUT_JSON} sha256={digest(OUT_JSON)}")
    print(f"review sheet: {OUT_MD} sha256={digest(OUT_MD)}")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
