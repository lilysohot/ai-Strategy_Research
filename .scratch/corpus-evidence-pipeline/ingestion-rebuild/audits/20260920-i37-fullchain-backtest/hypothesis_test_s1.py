"""S1（评分器空白规约）的假设性 / 反事实测试。

四组检验：
  T1 归因检验：13 条翻转是否严格满足「非空白码位序列包含」，差异是否 ⊆ 空白类。
  T2 来源检验：这 13 条是否全部落在 i33 的 34 条（当年判为"引文不在文本中"）名单内。
  T3 反事实检验：把 S1 放到**旧语料**（i33 观测，reader-pdf-2 时代）上，它还能救几条？
     —— 若救不了，则证明 S1 的收益**依赖**阅读层修复先到位，S1 不能替代它。
  T4 放水检验（变异）：对每条翻转引文做非空白变异（删字/改数字/插 ‖/全半角/大小写/零宽），
     确认 S1 仍不命中；并检查零宽字符（U+200B 等）是否构成 S1 的盲区。
只读文件，不访问 PG，不改任何资产。
"""
from __future__ import annotations

import json
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
I33 = HERE.parent / "20260920-i33-calibration"

FLIPS = {
    ("company-001", "e4"), ("company-001", "a-2"), ("company-002", "e1"),
    ("company-002", "e2"), ("company-002", "e3"), ("company-008", "a-4"),
    ("industry-007", "e2"), ("macro-005", "e1"), ("macro-006", "e1"),
    ("macro-006", "e2"), ("macro-006", "a-3"), ("macro-007", "e1"),
    ("macro-007", "e3"),
}


def nospace(s: str) -> str:
    return "".join(ch for ch in s if not ch.isspace())


def load_obs(path: Path) -> dict:
    return {o["query_id"]: o for o in json.loads(path.read_text())}


def pool_of(obs: dict, qid: str, source_id: str) -> list[dict]:
    question = obs.get(qid)
    if question is None:
        return []
    return [
        ev
        for document in (question.get("documents") or [])
        if document["source_id"] == source_id
        for ev in (document.get("evidence") or [])
    ]


def main() -> None:
    diag = json.loads((HERE / "diagnostics.json").read_text())
    new_obs = load_obs(HERE / "candidate_question_lexemes_or-observations.json")
    old_obs = load_obs(I33 / "candidate_question_lexemes_or-observations.json")
    old34 = {
        (t["query_id"], t["target_id"])
        for t in json.loads((I33 / "evidence-diagnosis.json").read_text())["targets"]
        if t["cause"] == "exact_quote_not_in_kept_page_text"
    }
    rows = {(r["query_id"], r["target_id"]): r for r in diag}

    print("== T1 归因检验（新语料）==")
    bad = []
    for key in sorted(FLIPS):
        row = rows[key]
        pool = pool_of(new_obs, key[0], row["source_id"])
        hit = [ev for ev in pool if nospace(row["quote"]) in nospace(ev["text"])]
        strict = [ev for ev in pool if row["quote"] in ev["text"]]
        diff_chars = set()
        exact_region = False
        if hit:
            target = nospace(row["quote"])
            text = nospace(hit[0]["text"])
            pos = text.find(target)
            # 严格性：命中区域必须与引文去空白后**逐字符完全相同**，而非包含更长文本
            exact_region = text[pos : pos + len(target)] == target
            for ch in row["quote"]:
                if ch.isspace():
                    diff_chars.add(repr(ch))
        ok = bool(hit) and not strict and exact_region
        print(f"  {key[0]} {key[1]}: 规约命中={bool(hit)} 严格命中={bool(strict)} "
              f"命中区域逐字相等={exact_region} 差异空白类={sorted(diff_chars)}")
        if not ok:
            bad.append(key)
    print(f"  T1 结论：{len(FLIPS) - len(bad)}/{len(FLIPS)} 条为『严格不命中、规约命中』（异常 {bad}）")

    print("== T2 来源检验：13 条是否都在旧 34 条名单内 ==")
    outside = sorted(k for k in FLIPS if k not in old34)
    print(f"  命中旧 34 条名单: {len(FLIPS) - len(outside)}/{len(FLIPS)}；不在名单内: {outside}")

    print("== T3 反事实检验：S1 放到旧语料上还能救几条 ==")
    rescued_old = rescued_new = 0
    rescued_names = []
    for key in sorted(FLIPS):
        row = rows[key]
        pool_old = pool_of(old_obs, key[0], row["source_id"])
        pool_new = pool_of(new_obs, key[0], row["source_id"])
        if any(nospace(row["quote"]) in nospace(ev["text"]) for ev in pool_old):
            rescued_old += 1
            rescued_names.append(f"{key[0]} {key[1]}")
        if any(nospace(row["quote"]) in nospace(ev["text"]) for ev in pool_new):
            rescued_new += 1
    print(f"  旧语料（reader-pdf-2 时代观测）S1 可救: {rescued_old}/{len(FLIPS)}  {rescued_names}")
    print(f"  新语料（reader-pdf-5 重摄入观测）S1 可救: {rescued_new}/{len(FLIPS)}")

    print("== T4a 放水检验 v2：只做『保证改变内容且破坏内部子串』的变异 ==")
    all_ok = True
    for key in sorted(FLIPS):
        row = rows[key]
        pool = pool_of(new_obs, key[0], row["source_id"])
        evidence = [ev for ev in pool if nospace(row["quote"]) in nospace(ev["text"])]
        if not evidence:
            continue
        text = evidence[0]["text"]
        q = row["quote"]
        mid = len(q) // 2
        variants: dict[str, str] = {}
        # 内部删一个非空白字符（不是尾部，破坏子串关系）
        for i in range(mid, len(q)):
            if not q[i].isspace():
                variants["内部删一字"] = q[:i] + q[i + 1 :]
                break
        # 数字改一位（仅当引文含数字）
        for i, ch in enumerate(q):
            if ch.isdigit():
                variants["数字改一位"] = q[:i] + ("7" if ch != "7" else "3") + q[i + 1 :]
                break
        # ASCII 标点/字母改全角（仅当存在）
        for i, ch in enumerate(q):
            if ch in "%.,/:":
                full = {"%": "％", ".": "．", ",": "，", "/": "／", ":": "："}[ch]
                variants["标点改全角"] = q[:i] + full + q[i + 1 :]
                break
        # ASCII 字母改大小写（仅当存在）
        for i, ch in enumerate(q):
            if ch.isascii() and ch.isalpha():
                variants["字母改大小写"] = q[:i] + ch.swapcase() + q[i + 1 :]
                break
        # 内部插竖线（I1 类）
        variants["内部插竖线"] = q[:mid] + "|" + q[mid:]
        for name, v in variants.items():
            if v == q:
                print(f"  {key[0]} {key[1]} {name}: 变异无效（未改变字符串），跳过")
                continue
            hit = nospace(v) in nospace(text)
            if hit:
                all_ok = False
            print(f"  {key[0]} {key[1]} {name}: 命中={hit} {'← 放水！' if hit else 'OK'}")
    print(f"  T4a 结论：{'全部变异均未命中（判据未放水）' if all_ok else '存在放水'}")

    print("== T4b 证据侧注入不可见字符：S1 的盲区 ==")
    for name, ch in (("U+00A0 NBSP(isspace=True)", "\u00a0"), ("U+200B ZWSP(isspace=False)", "\u200b")):
        still = []
        lost = []
        for key in sorted(FLIPS):
            row = rows[key]
            pool = pool_of(new_obs, key[0], row["source_id"])
            evidence = [ev for ev in pool if nospace(row["quote"]) in nospace(ev["text"])]
            if not evidence:
                continue
            text = evidence[0]["text"]
            pos = nospace(text).find(nospace(row["quote"]))
            raw_pos = 0
            count = 0
            for i, c in enumerate(text):  # 找到去空白命中对应的原始位置
                if count == pos:
                    raw_pos = i
                    break
                if not c.isspace():
                    count += 1
            offset = max(1, len(row["quote"]) // 2)  # 注入到命中区**内部**，破坏连续性
            injected = text[: raw_pos + offset] + ch + text[raw_pos + offset :]
            (still if nospace(row["quote"]) in nospace(injected) else lost).append(
                f"{key[0]} {key[1]}"
            )
        print(f"  注入 {name}: 仍命中 {len(still)} 条，转为不命中 {len(lost)} 条"
              f"{'（说明是盲区）' if lost else ''}")

    print("== T4b 零宽/特殊空白盲区检验 ==")
    zw = [ch for ch in "\u200b\u200c\u200d\ufeff\u00a0\u3000" ]
    for ch in zw:
        print(f"  U+{ord(ch):04X} {unicodedata.name(ch, '?')}: isspace={ch.isspace()} "
              f"→ {'会被规约' if ch.isspace() else '不会被规约（盲区）'}")
    blind = []
    for key in sorted(FLIPS):
        row = rows[key]
        pool = pool_of(new_obs, key[0], row["source_id"])
        for ev in pool:
            if any(ord(ch) in (0x200B, 0x200C, 0x200D, 0xFEFF) for ch in ev["text"]):
                blind.append(f"{key[0]} {key[1]}")
                break
    print(f"  证据文本含零宽字符的翻转条目: {sorted(set(blind)) or '无'}")


if __name__ == "__main__":
    main()
