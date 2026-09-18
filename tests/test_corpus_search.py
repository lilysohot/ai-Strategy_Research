"""P0b B3/B4：分词绑定、FTS5 检索、以及「snippet 只定位」这条约束。

最要紧的一条是 ``test_snippet_is_not_usable_as_a_quote``：如果 snippet
哪天变得完整，硬闸①的机制约束就悄悄失效了——Agent 不再需要 fetch，
「引用必须逐字来自原文」会退化成一句提示词。这条测试就是那个失效的警报。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from plugins.corpus.evidence import parse_evidence
from plugins.corpus.fetch import connect, fetch_block
from plugins.corpus.index import SNIPPET_WIDTH, _make_snippet, build_index, search, tokenize

STUB_DIR = Path(__file__).parent / "fixtures" / "stub_reports"

# 读侧最小 schema：列集按 index/fetch 的实际 SELECT 反推（I2-7 后写链已退休，
# 测试只负责把解析结果放进读侧认识的形状）。
_STUB_DDL = """
CREATE TABLE documents (
    doc_id      TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    source_path TEXT NOT NULL,
    mime        TEXT NOT NULL,
    status      TEXT NOT NULL,
    block_count INTEGER NOT NULL,
    char_count  INTEGER NOT NULL
);
CREATE TABLE blocks (
    doc_id  TEXT NOT NULL,
    seq     INTEGER NOT NULL,
    locator TEXT NOT NULL,
    text    TEXT NOT NULL,
    PRIMARY KEY (doc_id, seq)
);
"""


def _stub_body(path: Path) -> str:
    """stub md 的正文：剥掉头部 key: value 元数据区（fixture 的组织方式）。

    parse_evidence 的 md 路径原文透传、不认识元数据区；而块文本应当只含
    正文——元数据混进块里会稀释 FTS 排名并挤占 snippet 窗口。
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        if line.startswith("# "):
            return "\n".join(lines[i:])
    return "\n".join(lines)


def _load_stub_corpus(conn: sqlite3.Connection) -> None:
    """stub 研报 → 真实解析 → 手搓最小 sqlite 写入。

    I2-7：旧 ingest.parse_document/upsert_document 已随写链整体退休。
    解析仍走生产同源（parse_evidence）：doc_id/title 不是手搓的；md 恒为
    单页（locator="document"），整篇正文自然成为一块。
    """
    conn.executescript(_STUB_DDL)
    for path in sorted(STUB_DIR.glob("*.md")):
        doc = parse_evidence(path)
        page = doc.pages[0]
        conn.execute(
            "INSERT INTO documents (doc_id, title, source_path, mime, status, block_count,"
            " char_count) VALUES (?, ?, ?, 'text/markdown', 'active', 1, ?)",
            (doc.doc_id, doc.title, doc.source_path, len(page.text)),
        )
        conn.execute(
            "INSERT INTO blocks (doc_id, seq, locator, text) VALUES (?, 1, ?, ?)",
            (doc.doc_id, page.locator, _stub_body(path)),
        )
    conn.commit()


@pytest.fixture
def indexed_corpus(tmp_path: Path):
    """stub 研报入库 → 建索引。全链路真实，只是数据换成 stub。"""
    conn = connect(tmp_path / "index.db")
    _load_stub_corpus(conn)
    build_index(conn)
    yield conn
    conn.close()


# ── 数字单位绑定 ────────────────────────────────────────────────────────


def test_number_and_unit_are_bound_into_one_token():
    """jieba 会把 47.3 / 亿元 切开，这里必须粘回来。"""
    tokens = tokenize("公司 2025 年营收 47.3 亿元，同比增长 30%，目标价 24.50 元")
    assert "47.3亿元" in tokens.split()
    assert "30%" in tokens.split()
    assert "24.50元" in tokens.split()


def test_thousand_separators_are_normalized():
    """千分位去掉，让「1,720.54」与「1720.54」能被同一查询命中。"""
    tokens = tokenize("营收 1,720.54 亿元").split()
    # 数字被绑上单位，所以检查的是「去掉千分位后的整体」
    assert "1720.54亿元" in tokens
    assert not any("," in token for token in tokens)


def test_punctuation_only_tokens_are_dropped():
    tokens = tokenize("，。、；：（）")
    assert tokens == ""


# ── 检索 ────────────────────────────────────────────────────────────────


def test_search_returns_handle_and_snippet(indexed_corpus):
    hits = search(indexed_corpus, "目标价", limit=5)
    assert hits, "stub 语料里应当能搜到「目标价」"
    for hit in hits:
        assert hit.doc_id
        assert hit.locator  # 取证句柄：没有它就无法 fetch
        assert hit.title


def test_number_query_finds_the_report_that_contains_it(indexed_corpus):
    """「47.3亿」要能命中写着「47.3 亿元」的 R01。

    文档里的写法带「元」，查询不带——靠前缀匹配兜住这类差异。
    精确匹配会漏，而漏了会让 Agent 误判「资料里没有这个数」。
    """
    hits = search(indexed_corpus, "47.3亿", limit=5)
    assert hits, "47.3亿 应当命中 stub R01"
    assert any("47.3" in hit.snippet for hit in hits)


def test_search_respects_limit(indexed_corpus):
    assert len(search(indexed_corpus, "公司", limit=2)) <= 2


def test_empty_query_returns_nothing(indexed_corpus):
    assert search(indexed_corpus, "", limit=5) == []
    assert search(indexed_corpus, "，。、", limit=5) == []


def test_or_fallback_when_and_query_finds_nothing(indexed_corpus):
    """AND 查不到时退回 OR：宁可给几条带噪音的候选，也不要空手而归。"""
    # 「产能」与「失效」分别出现在不同研报里，AND 大概率无解
    hits = search(indexed_corpus, "产能 失效条件", limit=5)
    assert hits, "AND 无结果时应退回 OR 并给出候选"


# ── snippet 只定位，不取证 ──────────────────────────────────────────────


def test_snippet_is_truncated_and_marked():
    long_text = "营收增长" + "甲" * 900
    snippet = _make_snippet(long_text, "甲")
    assert len(snippet) < len(long_text)
    assert snippet.endswith("…") or snippet.startswith("…")


def test_snippet_is_not_usable_as_a_quote(indexed_corpus):
    """**关键约束**：snippet 必须短于原文，否则 Agent 不会再调 fetch。

    这是「取证必须走 corpus_fetch」的机制保证，不是提示词约定。
    """
    conn = indexed_corpus
    hits = search(conn, "营业收入", limit=5)
    assert hits
    for hit in hits:
        row = conn.execute(
            "SELECT text FROM blocks WHERE doc_id = ? AND locator = ?",
            (hit.doc_id, hit.locator),
        ).fetchone()
        full_text = " ".join(row[0].split())
        assert len(hit.snippet) <= SNIPPET_WIDTH + 2
        # 只要原文比 snippet 宽，snippet 就必然不等于完整原文
        if len(full_text) > SNIPPET_WIDTH:
            assert hit.snippet != full_text


# ── 取证（search → fetch 往返）────────────────────────────────────────


def test_search_then_fetch_returns_verbatim_text(indexed_corpus):
    """拿到句柄后能取回逐字原文，且原文确实包含 snippet 里的内容。"""
    conn = indexed_corpus
    hits = search(conn, "营业收入", limit=5)
    assert hits
    hit = hits[0]

    block = fetch_block(conn, hit.doc_id, hit.locator)
    assert block is not None
    assert block.text.strip()
    # snippet 里的关键内容必须能在原文里找到（证明它是从这块截出来的）
    core = hit.snippet.strip("…").strip()
    assert core.split()[0] in block.text or core[:8] in block.text


def test_locator_accepts_integer_page(indexed_corpus: sqlite3.Connection):
    """模型抄回 locator 时可能带类型变化（3 vs "3"），必须都能取到。"""
    conn = indexed_corpus
    row = conn.execute("SELECT doc_id, locator FROM blocks LIMIT 1").fetchone()
    doc_id, locator = row
    if locator.isdigit():
        assert fetch_block(conn, doc_id, int(locator)) is not None
    assert fetch_block(conn, doc_id, locator) is not None


def test_unknown_locator_returns_none_instead_of_raising(indexed_corpus):
    """查不到是正常结果，不该抛异常炸掉 ReAct 循环。"""
    conn = indexed_corpus
    row = conn.execute("SELECT doc_id FROM blocks LIMIT 1").fetchone()
    assert fetch_block(conn, row[0], "不存在的定位符") is None
