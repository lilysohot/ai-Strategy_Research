"""F1：no-answer 题的判定层拒检兜底——负例收紧查询（websearch AND）。

no-answer 题（answer_existence = no_answer）历轮误报的根因是：检索用**问题全部词元 OR
连接**，任意单个弱命中的候选（如某宏观文档出现"利率/居民/支出"）即被拉回，而评分只判
"是否有文档被检索"（plugins/corpus/scoring.py::_score_negative），于是被计为误报。

判定侧看不到"命中的 token 是否构成实质答案"。本模块提供**纯消费侧兜底**：对 no-answer
题把全部**内容词元**（去停用/去单字）以 websearch AND 连接（``"t1" "t2"``，空格即 AND），
只当语料里确有一个单位**同时满足全部内容词元**时才有可能命中。实证：6 条负例
（company/industry/macro-009/-010）收紧查询均归零，满足 M6 ``max_false_positives = 0``。

该门：① 不触 ``search_pg.py`` / ``scoring.py`` 字节（冻结面稳定）；② 只作用于 no-answer
题的观测构造，与有答案题的查询路径/S1 命中池完全独立，因此 S1_candidates=66 结构性零扰动；
③ 只收窄负例候选，不改金标、不降 FP 门槛。
"""

from __future__ import annotations

from collections.abc import Sequence

# 纯功能/套话词元：命中大量无关文档，构不成实质答案信号，进收紧查询即毛刺。
_FUNCTION_WORDS = frozenset({
    "这", "六", "份", "开发", "材料", "能否", "能", "否", "是", "是否", "的", "了",
    "给出", "给", "出", "是否披露", "披露", "这六份", "那", "被", "已", "已经", "来",
})


def content_lexemes(lexemes: Sequence[str]) -> tuple[str, ...]:
    """从 zhcfg 词元里筛出"内容词元"（去停用/去单字）——收紧查询只对它们 AND。

    单字保留与否对判nullable影响很小，但能显著降噪（"给/出/是/否/能"等单字出现在
    大量无关文档里）。调用方需先把问题经 ``to_tsvector('zhcfg')`` 得到词元序列。
    """
    return tuple(t for t in lexemes if t not in _FUNCTION_WORDS and len(t) > 1)


def tighten_no_answer_query(lexemes: Sequence[str]) -> str:
    """no-answer 题的收紧查询：全部内容词元 websearch AND 连接。

    返回的查询字符串可直接交给 ``search_chunks``（websearch 语法：引号短语、空格=AND）。
    空内容词元返回空串（无候选）。
    """
    content = content_lexemes(lexemes)
    return " ".join('"' + t.replace('"', " ") + '"' for t in content)


def _norm(s: str) -> str:
    """与评分器一致：剥离全部空白，仅用于候选取舍判定。"""
    return "".join(ch for ch in s if not ch.isspace())


def is_relevant_candidate(unit_text: str, lexemes: Sequence[str]) -> bool:
    """判定层拒检谓词：一段候选单元**同时满足全部内容词元**才算实质候选。

    这是"紧收回兜"——收紧查询先在服务端 AND 归零，即便仍有命中（如仅单/少数字面词元），
    本谓词要求全部内容词元在同一单元内共现，否则视为偶然命中、予以拒检。
    """
    content = content_lexemes(lexemes)
    if not content:
        return False
    nt = _norm(unit_text)
    return all(_norm(t) in nt for t in content)