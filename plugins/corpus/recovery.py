"""Deterministic partial delivery from verified, delivered source excerpts only."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from plugins.corpus.ledger import (
    PUBLISH_VERIFICATION_ERROR,
    SUPPORTED,
    ConsumptionLedger,
    SourceResolver,
    verify_and_record,
)


def verified_excerpt_fallback(
    ledger: ConsumptionLedger,
    *,
    directory: Path | None = None,
    resolver: SourceResolver | None = None,
    stopped_by: str = "",
    error_reason: str = "",
) -> str | None:
    """Recover evidence, never model-authored claims or a fresh recommendation.

    Check the latest manifests against authoritative text and actual delivery.
    Conclusion validity and excerpt provenance are separate: a failed claim may
    still contain an authentic delivered quotation. Publish only those original
    quotations, never the failed claim or an assertion that its dependencies hold.
    """
    verification = verify_and_record(ledger, directory=directory, resolver=resolver)
    if verification.get("status") == PUBLISH_VERIFICATION_ERROR:
        return None
    groups: list[str] = []
    seen: set[tuple[str, str, int, int]] = set()
    used = 0
    for row in verification.get("conclusions", []):
        matches = [
            m for m in row.get("matched_evidence") or [] if m.get("delivery") == "delivered"
        ]
        # Match provenance/offsets and delivery were recomputed above. A missing
        # dependency on the *claim* does not make these original excerpts false.
        # Do not publish report_quote, fabricate dependencies, or clip a quote.
        selected = [
            m for m in matches if (m["doc_id"], m["locator"], m["start"], m["end"]) not in seen
        ]
        size = sum(len(m["quote"]) for m in selected)
        if not selected or used + size > 6000:
            continue
        blocks = []
        for match in selected:
            seen.add((match["doc_id"], match["locator"], match["start"], match["end"]))
            blocks.append("> " + match["quote"].replace("\n", "\n> "))
            blocks.append(
                f"来源：`{match['doc_id']}`，位置 `{match['locator']}`，"
                f"原文字符区间 [{match['start']}, {match['end']})。"
            )
        groups.append("\n\n".join(blocks))
        used += size
        if len(groups) >= 8:
            break
    if not groups:
        return None
    failed_rows = [r for r in verification.get("conclusions", []) if r.get("status") != SUPPORTED]
    problems = Counter(
        code for row in failed_rows for code in {p["code"] for p in row.get("problems", [])}
    )
    labels = {
        "quote_not_found": "引文不匹配",
        "missing_dependencies": "必要依赖缺失",
        "not_delivered": "证据未完整送达",
        "source_unresolvable": "来源无法解析",
    }
    limitations = ""
    if failed_rows:
        details = "、".join(f"{label} {problems[code]} 条" for code, label in labels.items() if problems[code])
        limitations = f"{len(failed_rows)} 条结论未通过完整校验"
        limitations += f"（{details}）。" if details else "。"
    interruption = ""
    if error_reason in {"reasoning_runaway", "reasoning_runaway_early"}:
        interruption = "模型持续推理但未产生正文或工具调用，受限恢复未成功，已转为资料摘录交付。"
    elif stopped_by == "llm_error":
        interruption = "模型请求未能完成，已转为资料摘录交付。"
    elif stopped_by == "wall_deadline":
        interruption = "研究执行达到时限，已转为资料摘录交付。"
    return (
        "本次研究未完成。" + interruption + limitations
        + "以下仅保留已核验且实际送达的资料原文摘录，供继续研究。"
        "原文可追溯不代表相关结论成立；这些摘录不构成完整结论或投资建议。\n\n"
        + "\n\n".join(groups)
    )
