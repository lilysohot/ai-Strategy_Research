"""P0b B3：FTS5 索引与检索（纯函数侧，不含工具壳）。

两处设计是被实测逼出来的，不是凭空定的：

**一、数字单位必须自己绑定。** jieba 默认会把 ``47.3亿`` 切成 ``47.3`` / ``亿元``，
而研报检索里最有价值的查询恰恰是「47.3 亿」「30%」这类带单位的数字。
切碎之后，搜「47.3亿」会命中所有含 47.3 或所有含亿元的文档，
精确性归零。所以先用一个正则把「数字+单位」抠出来整体保留，
只把剩下的中文部分交给 jieba。

**二、FTS5 必须显式声明 tokenchars。** 预分词后词与词之间用空格连接，
交给 unicode61 切；但 unicode61 默认把 ``.`` 和 ``%`` 当分隔符，
``24.50`` 会被切成 ``24`` / ``50``、``30%`` 会变成 ``30``。
``tokenchars '.%'`` 就是为了保住这些数字的完整形态。

为什么用「预分词 + unicode61」而不是别的方案：它把分词策略掌握在自己手里
（换分词器不用重造索引格式），也让索引内容**可读**——直接 SELECT 出来
就能看出某个数字有没有被绑对，排查时不用猜。
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass

# 数字（含千分位与小数）+ 可选单位。单位按长度降序排列，
# 否则「亿元」会被「亿」先吃掉，绑成「47.3亿」+「元」。
_NUMBER_UNIT_PATTERN = re.compile(
    r"(?P<num>\d+(?:[.,]\d+)*)\s*(?P<unit>"
    r"个百分点|亿元|万元|千万元|亿美元|万美元"
    r"|亿|万|元|美元|港元|人民币"
    r"|万股|亿股|股|吨|倍"
    r"|%|pct"
    r")?",
    re.IGNORECASE,
)

# tokenchars 里放 . 与 %：保住 24.50 / 30% 这类数字的完整形态。
# title_tokens 单独成列，是为了给它更高的 bm25 权重——标题是信息密度最高的
# 元数据（「摩根大通」「贵州茅台」往往只出现在标题里），与正文同权会让这类
# 查询召回不到。这个缺陷是黄金题 O3 实测暴露出来的：标题未入索引时，
# 「摩根大通」在索引中出现 0 次。
FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS blocks_fts USING fts5(
    doc_id       UNINDEXED,
    locator      UNINDEXED,
    title_tokens,
    tokens,
    tokenize = "unicode61 tokenchars '.%'"
);
"""

# bm25 列权重：与 FTS 列一一对应（doc_id, locator, title_tokens, tokens）。
# 标题权重 5 倍于正文：标题里出现的词更能代表这份文档。
_BM25 = "bm25(blocks_fts, 0.0, 0.0, 5.0, 1.0)"

# snippet 宽度。刻意做窄：它的职责是「告诉 Agent 去哪儿取证」，
# 不是「把原文给它」。给足了全文，Agent 就不会再调 corpus_fetch，
# 硬闸①的溯源链就断了。
SNIPPET_WIDTH = 160


@dataclass(frozen=True)
class SearchHit:
    """一条检索命中。

    ``doc_id`` + ``locator`` 合起来是**取证句柄**：Agent 拿着它去调
    ``corpus_fetch`` 取逐字原文。snippet 故意不完整，且带省略号标记。
    """

    doc_id: str
    locator: str
    title: str
    snippet: str
    score: float
    # 发布/收录日期（``YYYY-MM-DD`` 或 ``undated``）。
    # 带上它是因为 BM25 **不理解「最新」**：它只能把候选找出来，
    # 「哪份最新」要由 Agent 看日期判断。不给日期，时效型问题无解。
    published: str = ""


def _cut(text: str, *, for_search: bool) -> list[str]:
    """调用 jieba 切中文部分。索引用细粒度（召回优先），查询用普通粒度。"""
    import jieba

    iterator = jieba.cut_for_search(text) if for_search else jieba.cut(text)
    return list(iterator)


def _clean(token: str) -> str:
    """清洗单个 token：去空白、丢纯标点、ASCII 转小写。

    纯标点必须丢，否则 FTS 里塞满「，」「。」这类噪音，
    既拖慢查询又让 bm25 排名失真。
    """
    token = token.strip()
    if not token:
        return ""
    # CJK 字符的 isalnum() 为 True，所以这条同时覆盖中英文
    if not any(char.isalnum() for char in token):
        return ""
    return token.lower() if token.isascii() else token


def tokenize(text: str, *, for_search: bool = False) -> str:
    """把原文变成空格分隔的 token 串（供 FTS 存储/匹配）。

    数字与单位绑成**一个** token：``47.3亿元`` 不再被切开，
    于是「47.3亿」能精确命中，而不是命中所有含「亿元」的文档。
    """
    tokens: list[str] = []
    position = 0

    for match in _NUMBER_UNIT_PATTERN.finditer(text):
        if match.start() > position:
            tokens.extend(_cut(text[position : match.start()], for_search=for_search))
        # 千分位去掉，让 "1,720.54" 与 "1720.54" 能被同一查询命中
        number = match.group("num").replace(",", "")
        unit = match.group("unit") or ""
        tokens.append((number + unit).lower() if unit else number)
        position = match.end()

    if position < len(text):
        tokens.extend(_cut(text[position:], for_search=for_search))

    return " ".join(token for token in (_clean(item) for item in tokens) if token)


def build_index(conn: sqlite3.Connection) -> int:
    """从 ``blocks`` 重建 FTS 索引，返回索引块数。

    整表重建而不是增量：17 份、298 块的量级下重建只需毫秒级，
    而增量更新的正确性问题（改了一块要不要连带重算 bm25）不值得为它冒险。
    等到了 8000 份再谈增量。
    """
    # FTS5 表结构可能随版本演进（如新增 title_tokens 列），DROP 再建，
    # 避免「CREATE IF NOT EXISTS」看到旧表而沿用过时 schema。
    conn.execute("DROP TABLE IF EXISTS blocks_fts")
    conn.executescript(FTS_SCHEMA)
    conn.execute("DELETE FROM blocks_fts")

    rows = conn.execute(
        "SELECT b.doc_id, b.locator, b.text, d.title"
        " FROM blocks b JOIN documents d ON d.doc_id = b.doc_id"
        " ORDER BY b.doc_id, b.seq",
    ).fetchall()

    conn.executemany(
        "INSERT INTO blocks_fts (doc_id, locator, title_tokens, tokens)"
        " VALUES (?, ?, ?, ?)",
        [
            # 标题也进索引：它往往含正文里不出现的机构名/标的名，
            # 不索引的话「摩根大通」这类查询会一无所获。
            (doc_id, locator, tokenize(title), tokenize(text))
            for doc_id, locator, text, title in rows
        ],
    )
    conn.commit()
    return len(rows)


def _match_expression(query_tokens: str) -> tuple[str, str]:
    """把 token 串转成 FTS5 表达式，返回 ``(AND 式, OR 式)``。

    含数字的 token 一律加前缀匹配（``"47.3亿"*``）。这是被实测逼出来的：
    文档里写的是「47.3 亿元」，绑定后 token 是 ``47.3亿元``；
    而查询「47.3亿」绑定后是 ``47.3亿``——两者不相等，精确匹配会**漏掉
    明明存在的数字**。数字单位本就有多种写法（亿/亿元、%/个百分点），
    要求用户按文档里的写法一字不差地搜是不现实的。前缀匹配让
    ``47.3亿`` 命中 ``47.3亿元``，``47.3`` 也能命中，同时不会把
    ``47.3`` 和 ``48.3`` 混为一谈。

    AND 召回准但可能过严；OR 召回宽但会引入噪音。默认走 AND，
    空结果时退回 OR——「什么都没搜到」对 Agent 是最坏的结果，
    它会据此得出「资料里没有」的结论，而这个结论可能是错的。
    """
    terms = [term.replace('"', "") for term in query_tokens.split() if term]
    if not terms:
        return "", ""
    quoted = [
        f'"{term}"*' if any(char.isdigit() for char in term) else f'"{term}"' for term in terms
    ]
    return " AND ".join(quoted), " OR ".join(quoted)


def _make_snippet(text: str, query_tokens: str, width: int = SNIPPET_WIDTH) -> str:
    """围绕首个命中词截一段原文，两端加省略号标明**被截断**。

    省略号不是装饰：它让 Agent（和人）一眼看出这不是可引用的原文，
    想要逐字引用必须去 ``corpus_fetch``。
    """
    flat = " ".join(text.split())
    terms = [term for term in query_tokens.split() if term]
    anchor = 0
    for term in terms:
        found = flat.find(term.replace('"', ""))
        if found >= 0:
            anchor = found
            break
    start = max(0, anchor - width // 3)
    end = min(len(flat), start + width)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(flat) else ""
    return prefix + flat[start:end] + suffix


def search(
    conn: sqlite3.Connection,
    query: str,
    *,
    limit: int = 10,
) -> list[SearchHit]:
    """检索语料，返回命中句柄 + 截断 snippet（**不含**完整原文）。"""
    query_tokens = tokenize(query, for_search=True)
    if not query_tokens:
        return []

    and_expr, or_expr = _match_expression(query_tokens)
    rows = conn.execute(
        f"SELECT f.doc_id, f.locator, d.title, {_BM25} AS score"
        " FROM blocks_fts f JOIN documents d ON d.doc_id = f.doc_id"
        " WHERE blocks_fts MATCH ? ORDER BY score, f.doc_id DESC LIMIT ?",
        (and_expr, limit),
    ).fetchall()

    if not rows and or_expr and or_expr != and_expr:
        # AND 查不到时退回 OR：宁可多给几条带噪音的候选，
        # 也不要让 Agent 误判「资料里没有」
        rows = conn.execute(
            "SELECT f.doc_id, f.locator, d.title, bm25(blocks_fts) AS score"
            " FROM blocks_fts f JOIN documents d ON d.doc_id = f.doc_id"
            " WHERE blocks_fts MATCH ? ORDER BY score LIMIT ?",
            (or_expr, limit),
        ).fetchall()

    hits: list[SearchHit] = []
    for doc_id, locator, title, score in rows:
        row = conn.execute(
            "SELECT text FROM blocks WHERE doc_id = ? AND locator = ?",
            (doc_id, locator),
        ).fetchone()
        text = row[0] if row else ""
        hits.append(
            SearchHit(
                doc_id=doc_id,
                locator=locator,
                title=title,
                snippet=_make_snippet(text, query_tokens),
                score=float(score),
                published=_published_of(doc_id),
            )
        )
    return hits


def _published_of(doc_id: str) -> str:
    """从 ``doc_id`` 前缀解析发布/收录日期。

    ``doc_id`` 形如 ``2026-09-03_810ef870``，前缀就是收录日期；
    未标注来源为 ``undated_xxxx``。BM25 **不理解「最新」**，所以把日期
    显式带回到结果里，让 Agent 能自己判断哪份最新——
    否则时效型查询（「最新一期」「最晚发布」）无解。
    """
    prefix = doc_id.split("_", 1)[0]
    return prefix if "-" in prefix else "undated"
