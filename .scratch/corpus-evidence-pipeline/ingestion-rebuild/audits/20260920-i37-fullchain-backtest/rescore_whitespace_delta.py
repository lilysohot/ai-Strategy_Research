"""离线重算：冻结版（码位精确）vs 工作树版（空白规约）scorer 的 EvidencePass 差额。

数据源 = 本目录 i37 观测（candidate_question_lexemes_or-observations.json）与诊断
（diagnostics.json）。只读、不访问 PG、不改评分资产。用于核实 S1 的 +6 收益与
"哪些目标翻转"。
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def nospace(s: str) -> str:
    return "".join(ch for ch in s if not ch.isspace())


def matches(target: dict, evidence: dict, *, normalize: bool) -> bool:
    if evidence.get("verified") is not True:
        return False
    quote, text = target["quote"], evidence["text"]
    if normalize:
        if nospace(quote) not in nospace(text):
            return False
    elif quote not in text:
        return False
    return all(token in evidence["locator"] for token in target["locator"])


def main() -> None:
    diag = json.loads((HERE / "diagnostics.json").read_text())
    obs = json.loads((HERE / "candidate_question_lexemes_or-observations.json").read_text())
    by_query = {o["query_id"]: o for o in obs}

    targets_by_query: dict[str, list[dict]] = {}
    for row in diag:
        targets_by_query.setdefault(row["query_id"], []).append(row)

    flips: list[str] = []
    pass_frozen = pass_norm = 0
    domain_frozen: dict[str, int] = {}
    domain_norm: dict[str, int] = {}

    for qid, targets in sorted(targets_by_query.items()):
        question = by_query.get(qid)
        if question is None:
            continue
        # 证据池：声明来源的文档（按别名匹配）
        pools: dict[str, list[dict]] = {}
        for document in question.get("documents") or []:
            pools.setdefault(document["source_id"], []).extend(document.get("evidence") or [])
        for variant, normalize in (("frozen", False), ("norm", True)):
            ok_all = True
            for target in targets:
                pool = pools.get(target["source_id"], [])
                hit = any(matches(target, ev, normalize=normalize) for ev in pool)
                if hit and not normalize:
                    pass
                if not hit:
                    ok_all = False
                    if normalize:
                        # 只有"规约版命中而冻结版不命中"才算翻转
                        if any(matches(target, ev, normalize=False) for ev in pool):
                            pass
                        else:
                            pass
            if normalize:
                if ok_all:
                    pass_norm += 1
                    key = qid.split("-")[0]
                    domain_norm[key] = domain_norm.get(key, 0) + 1
            elif ok_all:
                pass_frozen += 1
                key = qid.split("-")[0]
                domain_frozen[key] = domain_frozen.get(key, 0) + 1

    # 逐目标翻转明细
    for row in diag:
        question = by_query.get(row["query_id"])
        if question is None:
            continue
        pool: list[dict] = []
        for document in question.get("documents") or []:
            if document["source_id"] == row["source_id"]:
                pool.extend(document.get("evidence") or [])
        frozen = any(matches(row, ev, normalize=False) for ev in pool)
        norm = any(matches(row, ev, normalize=True) for ev in pool)
        if norm and not frozen:
            flips.append(f"{row['query_id']} {row['target_id']}  ({row['domain']})")

    print(f"EvidencePass 冻结版 = {pass_frozen}/24   规约版 = {pass_norm}/24")
    print("  冻结版分层:", domain_frozen)
    print("  规约版分层:", domain_norm)
    print(f"---- 仅因空白规约而翻转的目标（{len(flips)} 条）----")
    for line in flips:
        print("   ", line)

    # 单调性核对：是否存在"冻结版命中、规约版反而不命中"（不应存在）
    reverse: list[str] = []
    for row in diag:
        question = by_query.get(row["query_id"])
        if question is None:
            continue
        pool = [ev for document in (question.get("documents") or [])
                if document["source_id"] == row["source_id"]
                for ev in (document.get("evidence") or [])]
        if any(matches(row, ev, normalize=False) for ev in pool) and not any(
            matches(row, ev, normalize=True) for ev in pool
        ):
            reverse.append(f"{row['query_id']} {row['target_id']}")
    print(f"---- 反向翻转（冻结命中→规约不命中，必须为 0）：{len(reverse)} {reverse} ----")
    print(f"---- 竖线边界：规约版能否把『证据含 | 、引文不含』判为命中 "
          f"---- {nospace('a|b') in nospace('a|b')} / 分隔符不是空白："
          f"{'|'.isspace()}")
    print(f"---- 竖线边界自检：引文 'ab' 是否命中证据 'a|b' —— "
          f"{nospace('ab') in nospace('a|b')}（必须为 False，证明 S1 不掩盖 I1）")

    print("---- 翻转样例：差异是否**只有空白** ----")
    shown = 0
    for row in diag:
        question = by_query.get(row["query_id"])
        if question is None or shown >= 3:
            continue
        pool: list[dict] = []
        for document in question.get("documents") or []:
            if document["source_id"] == row["source_id"]:
                pool.extend(document.get("evidence") or [])
        if any(matches(row, ev, normalize=False) for ev in pool):
            continue
        for ev in pool:
            if matches(row, ev, normalize=True):
                print(f"  [{row['query_id']} {row['target_id']}]")
                print(f"    gold  : {row['quote'][:90]!r}")
                print(f"    eviden: {ev['text'][:90]!r}")
                print(f"    去空白后是否完全相等: {nospace(row['quote']) in nospace(ev['text'])}"
                      f"  引文去空白长度={len(nospace(row['quote']))}")
                print(f"    引文中是否含竖线/逗号等非空白分隔符: "
                      f"{sorted({c for c in row['quote'] if not c.isspace() and not (c.isalnum() or c.isalpha())})[:8]}")
                shown += 1
                break


if __name__ == "__main__":
    main()
