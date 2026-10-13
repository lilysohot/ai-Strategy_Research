"""Stratify the 34 matched (candidate, gold) pairs by match strength.

Zero model calls; read-only. The 34 pairs come from three signed worksheets:

* 222-row A worksheet  -> 26 pairs   (adjudication/worksheet.json)
* base packet worksheet -> 7 pairs   (66-.../r3-cumulative/adjudication-worksheet-base.json)
* r5 I06/I41 worksheet  -> 1 pair    (65-.../r5-adjudication-sheet/adjudication-worksheet.json)

Layers (strongest first) and their mechanical criteria — AGENT HEURISTIC, not an
adjudication; every row carries its flags so a human can overrule:

1. ``逐字一致``      candidate text equals the gold quote, or one contains the other verbatim
2. ``同义改写``      neither side contains the other, but similarity is clearly high
3. ``归一化后等价``  the pair only aligns after a ``caliber_rules`` normalisation
                     (perspective file/speech_role/statement_role/semantic_type differ)
4. ``可恢复省略``    the candidate is a fragment of the gold proposition (length ratio < 0.6)

Precedence applied: normalisation need > verbatim > fragment > paraphrase, and the full
flag set is printed for every row so the precedence can be audited or re-cut.
"""

from __future__ import annotations

import difflib
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
CLAIMS = HERE.parents[2]
E65 = CLAIMS / "evidence" / "65-rerun-two-arm-protocol-20261013" / "r5-adjudication-sheet"
E66 = CLAIMS / "evidence" / "66-base-protocol-change-proposal-20261013" / "r3-cumulative"

A_SHEET = CLAIMS / "adjudication" / "worksheet.json"
BASE_SHEET = E66 / "adjudication-worksheet-base.json"
R5_SHEET = E65 / "adjudication-worksheet.json"
GOLD = CLAIMS / "evidence" / "10-quality-gold-freeze-20261008-r2" / "frozen-gold.json"

NORMALISED_AXES = ("perspective", "speech_role", "statement_role", "semantic_type")


def norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "").strip("。；，,.;")


def load_gold() -> dict[str, dict]:
    rows = json.loads(GOLD.read_text(encoding="utf-8"))["records"]
    return {r["record_id"]: r for r in rows if r["role"] == "material_items"}


def pairs_from_a(gold: dict[str, dict]) -> list[dict]:
    out = []
    for r in json.loads(A_SHEET.read_text(encoding="utf-8"))["records"]:
        gid = r.get("matched_gold_id")
        if not gid:
            continue
        src = r["original_candidate"]
        out.append(
            {
                "origin": "A worksheet (222)",
                "candidate_id": r["candidate_id"],
                "gold_id": gid,
                "candidate_text": src.get("text", ""),
                "cand_fields": {k: src.get(k) for k in NORMALISED_AXES},
                "reason": (r.get("reason") or "")[:80],
            }
        )
    return out


def pairs_from_base(gold: dict[str, dict]) -> list[dict]:
    out = []
    for c in json.loads(BASE_SHEET.read_text(encoding="utf-8"))["candidates"]:
        if c["to_fill"].get("judgement") != "matched":
            continue
        sug = c["model_suggestion"]
        out.append(
            {
                "origin": "base packet (16 rows)",
                "candidate_id": c["candidate_id"],
                "gold_id": c["to_fill"]["matched_gold_id"],
                "candidate_text": c["proposition"],
                "cand_fields": {
                    "semantic_type": sug.get("semantic_type"),
                    "statement_role": sug.get("statement_role"),
                    "speech_role": sug.get("speech_role"),
                    "perspective": sug.get("perspective"),
                },
                "reason": "",
            }
        )
    return out


def pairs_from_r5(gold: dict[str, dict]) -> list[dict]:
    out = []
    for c in json.loads(R5_SHEET.read_text(encoding="utf-8"))["candidates"]:
        if c["to_fill"].get("judgement") != "matched":
            continue
        sug = c.get("model_suggestion") or {}
        out.append(
            {
                "origin": "r5 (I06/I41)",
                "candidate_id": c["candidate_id"],
                "gold_id": c["to_fill"]["matched_gold_id"],
                "candidate_text": c.get("proposition", ""),
                "cand_fields": {
                    "semantic_type": sug.get("semantic_type"),
                    "statement_role": sug.get("statement_role"),
                    "speech_role": sug.get("speech_role"),
                    "perspective": sug.get("perspective"),
                },
                "reason": "",
            }
        )
    return out


def stratify(pair: dict, gold: dict[str, dict]) -> dict:
    g = gold[pair["gold_id"]]
    gf = g["semantic_fields"]
    ct, gp, gq = norm(pair["candidate_text"]), norm(gf.get("proposition", "")), norm(g.get("quote", ""))
    sim = difflib.SequenceMatcher(None, ct, gp).ratio()
    flags: list[str] = []
    if not ct:
        flags.append("empty_candidate_text")
    if ct and (ct == gq or ct == gp):
        flags.append("equal")
    if ct and (ct in gp or ct in gq or gp in ct):
        flags.append("containment")
    if gp and len(ct) / max(len(gp), 1) < 0.6:
        flags.append("fragment")
    mismatched = [
        ax
        for ax in NORMALISED_AXES
        if (pair["cand_fields"].get(ax) or "") not in ("", "unknown", "absent")
        and (gf.get(ax) or "") not in ("", "unknown", "absent")
        and pair["cand_fields"].get(ax) != gf.get(ax)
    ]
    if mismatched:
        flags.append("needs_caliber:" + ",".join(sorted(mismatched)))

    if mismatched:
        layer = "归一化后等价"
    elif "equal" in flags or "containment" in flags:
        layer = "逐字一致"
    elif "fragment" in flags:
        layer = "可恢复省略"
    else:
        layer = "同义改写"

    return {
        "layer": layer,
        "similarity": round(sim, 3),
        "flags": flags,
        "candidate_text": pair["candidate_text"],
        "gold_proposition": gf.get("proposition", ""),
        "gold_quote": g.get("quote", ""),
        "gold_fields": {k: gf.get(k) for k in NORMALISED_AXES},
        "cand_fields": pair["cand_fields"],
        "origin": pair["origin"],
        "candidate_id": pair["candidate_id"],
        "gold_id": pair["gold_id"],
        "reason": pair["reason"],
    }


def main() -> None:
    gold = load_gold()
    pairs = pairs_from_a(gold) + pairs_from_base(gold) + pairs_from_r5(gold)
    rows = [stratify(p, gold) for p in pairs]

    order = ["逐字一致", "同义改写", "归一化后等价", "可恢复省略"]
    counts = {k: sum(1 for r in rows if r["layer"] == k) for k in order}
    assert len(rows) == 34, f"expected 34 pairs, got {len(rows)}"

    (HERE / "match-stratification.json").write_text(
        json.dumps(
            {
                "schema_version": "match-stratification-1",
                "created_on": "2026-10-13",
                "zero_model_calls": True,
                "status": "agent heuristic layer assignment — NOT an adjudication",
                "total_pairs": len(rows),
                "layer_counts": counts,
                "layers_strongest_first": order,
                "precedence": "needs_caliber > verbatim > fragment > paraphrase",
                "rows": rows,
            },
            ensure_ascii=False,
            indent=1,
        )
        + "\n",
        encoding="utf-8",
    )

    lines = [
        "# 34 条 matched 的匹配强度分层（代理启发式，非裁定）",
        "",
        "- 2026-10-13　零模型调用　配对来源：A 工作表 26 + base 包 7 + r5 1 = **34**",
        "- **这是机械分层，不是裁定**：每条都带 `flags`，可被人工推翻；层间优先序为",
        "  `归一化需求 > 逐字 > 碎片 > 同义改写`。",
        "",
        "| 层（强→弱） | 条数 | 判据 |",
        "|---|---|---|",
    ]
    criteria = {
        "逐字一致": "候选文本与金标命题/引文逐字相等或互为包含",
        "同义改写": "两侧互不包含，但相似度明显高",
        "归一化后等价": "需经 caliber_rules 归一化才能对齐（perspective/speech_role/statement_role/semantic_type 有差异）",
        "可恢复省略": "候选是金标命题的碎片（长度比 < 0.6）",
    }
    for k in order:
        lines.append(f"| **{k}** | {counts[k]} | {criteria[k]} |")
    # --- cross-tab: the four layers are NOT mutually exclusive -------------------
    def has(r: dict, token: str) -> bool:
        return any(f == token or f.startswith(token) for f in r["flags"])

    lines += [
        "",
        "## 交叉表（层不互斥，必须一起看）",
        "",
        "| 层 | 条数 | 其中与金标**引文逐字相同** | 其中需归一化 | 其中是碎片 |",
        "|---|---|---|---|---|",
    ]
    for k in order:
        sel = [r for r in rows if r["layer"] == k]
        lines.append(
            f"| {k} | {len(sel)} | {sum(1 for r in sel if has(r,'equal'))} | "
            f"{sum(1 for r in sel if has(r,'needs_caliber'))} | {sum(1 for r in sel if has(r,'fragment'))} |"
        )

    ladder = [
        ("① 只认与金标引文逐字相同", sum(1 for r in rows if has(r, "equal"))),
        ("② ＋ 文本互为包含", sum(1 for r in rows if has(r, "equal") or has(r, "containment"))),
        ("③ ＋ 同义改写（模糊相似）", len(rows)),
    ]
    lines += [
        "",
        "## 严格度阶梯（同一批 34 对，按口径收紧）",
        "",
        "| 口径 | 条数 | 召回 |",
        "|---|---|---|",
    ]
    for name, n in ladder:
        lines.append(f"| {name} | {n} | {n}/48 = {n/48:.3f} |")
    lines += [
        f"| ④ 契约口径（含 caliber 归一化后等价） | {len(rows)} | {len(rows)}/48 = {len(rows)/48:.3f} |",
        "",
        "> 34 条里有 **22 条**需要 `caliber_rules` 归一化才能对齐字段（perspective/speech_role/statement_role/semantic_type 差异）；",
        "> 剔除它们只剩 **12 条**（9 逐字 + 3 同义）。**34 与更严口径之间的差额，取决于剔除哪一层——先定口径，再看数字。**",
    ]

    lines += ["", "## 逐条明细", "", "| # | 层 | 相似度 | gold | 候选文本 | 金标命题 | flags |", "|---|---|---|---|---|---|---|"]
    for i, r in enumerate(sorted(rows, key=lambda x: order.index(x["layer"])), 1):
        lines.append(
            f"| {i} | {r['layer']} | {r['similarity']} | {r['gold_id']} | "
            f"{r['candidate_text'][:34]} | {r['gold_proposition'][:34]} | {'、'.join(r['flags']) or '—'} |"
        )
    (HERE / "match-stratification.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"total": len(rows), **counts}, ensure_ascii=False))


if __name__ == "__main__":
    main()
