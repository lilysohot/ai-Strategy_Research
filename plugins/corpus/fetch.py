"""P0b B4（读侧）：按定位符取回原文块。

与 ``ingest`` 的分工：ingest 写库，这里只读。读侧独立成模块，是因为
``corpus_fetch`` 工具、``verify.py`` 的 source_resolver、以及将来的黄金题
评测都要引用它——若写进 ingest，这些「只想读」的调用方会被迫 import
pymupdf / python-docx 一整条解析依赖链。

定位符归一化是这里的重点：模型从工具输出抄回 locator 时可能带类型变化
（整数 3 与字符串 "3"），不做归一就会出现「明明有这一页却查不到」的假阴性，
而假阴性会让 Agent 误判「资料里没有」——那正是要避免的静默失败。
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

#: 落盘路径。旧 sqlite 链只读保留（读侧迁移归 I2-8）。
DEFAULT_DB_PATH = "data/corpus/index.db"


def connect(db_path: str | Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """打开语料库（外键约束显式打开）。从 ingest 退休内联，行为不变。"""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@dataclass(frozen=True)
class FetchedBlock:
    """取回的一个原文块。"""

    doc_id: str
    seq: int
    locator: str
    text: str


def _normalize_locator(locator: object) -> str:
    """定位符归一化：去空白、整数转十进制字符串。"""
    if isinstance(locator, bool):
        return str(locator)
    if isinstance(locator, int):
        return str(locator)
    if isinstance(locator, float) and locator.is_integer():
        return str(int(locator))
    return str(locator).strip()


def fetch_block(
    conn: sqlite3.Connection,
    doc_id: str,
    locator: object,
) -> FetchedBlock | None:
    """按 ``(doc_id, locator)`` 取一个块；不存在返回 ``None``。

    返回 ``None`` 而不是抛异常：查不到是**正常结果**（模型可能猜了一个
    不存在的页码），应当让它拿到「没有」再去试别的，而不是炸掉整个 ReAct 循环。
    """
    row = conn.execute(
        "SELECT seq, locator, text FROM blocks WHERE doc_id = ? AND locator = ?",
        (doc_id.strip(), _normalize_locator(locator)),
    ).fetchone()
    if row is None:
        return None
    return FetchedBlock(doc_id=doc_id, seq=row[0], locator=row[1], text=row[2])


def document_text(conn: sqlite3.Connection, doc_id: str) -> str | None:
    """整篇原文（按 seq 顺序拼接）；文档不存在返回 ``None``。

    溯源校验用它判断「quote 是否逐字出现在原文里」。**拼接而非逐块比对**：
    一条引用跨两个块（比如跨页的表格）是合法的，逐块比对会误判。
    """
    rows = conn.execute(
        "SELECT text FROM blocks WHERE doc_id = ? ORDER BY seq",
        (doc_id.strip(),),
    ).fetchall()
    if not rows:
        return None
    return "\n".join(row[0] for row in rows)


def list_documents(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """列出全部文档（供 corpus_search 与调试用）。"""
    conn.row_factory = sqlite3.Row
    return list(
        conn.execute(
            "SELECT doc_id, title, source_path, mime, status, block_count, char_count"
            " FROM documents ORDER BY doc_id",
        ).fetchall()
    )


def make_source_resolver(conn: sqlite3.Connection) -> Callable[[str], str | None]:
    """造一个 ``source_ref -> 原文`` 解析器，交给 ``verify.py`` 跑硬闸①。

    连接由调用方持有（不在这里开/关）：一个 resolver 可能在一次校验里被
    调用十几次，每次开关连接既慢又容易漏关。
    """

    def resolver(source_ref: str) -> str | None:
        return document_text(conn, source_ref)

    return resolver


def open_resolver(
    db_path: str | Path = DEFAULT_DB_PATH,
) -> tuple[sqlite3.Connection, Callable[[str], str | None]]:
    """便利入口：开连接并返回 ``(conn, resolver)``，调用方负责 ``conn.close()``。"""
    conn = connect(db_path)
    return conn, make_source_resolver(conn)
