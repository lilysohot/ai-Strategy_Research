"""P1 数据层服务：PostgreSQL 收口（zhparser 中文全文 + pgvector 留位）。

这是 P0 验证期「SQLite 直连」的替代收口层。所有 DB 访问经本模块，调用方
（``corpus_search`` / ``corpus_fetch`` / ``verify`` / ``golden``）一律不直连驱动。

选型依据见 ``docs/plan/data-layer-architecture.md`` v2.0 与 ``docs/plan/pg-migration.md``：
- 存储定为 PostgreSQL（你要 host:port + Windows 接入 + 多人 + web 端）
- 中文全文用 **zhparser**（PG 内置 FTS 无中文分词）
- 向量用 **pgvector**，但**判据驱动**：当前 FTS Recall@5=100%，无缺口，暂不建列

读侧语义不变（硬闸①依赖）：``search`` 返回截断 snippet（只定位），
``fetch`` 返回逐字原文（取证）。

检索排序（**已于 2026-09-08 校准定稿**，黄金集 Recall@5 = 100%）：
``search`` 使用 ``ts_rank`` + **标题 5× 加权** + **AND→OR 兜底** +
**按 ``doc_id`` 去重** + 时效查询 Recency 偏置。
**PG 原生没有 BM25**，SQLite 的 ``bm25(fts,0,0,5.0,1.0)`` 由这套组合近似，
不能想当然认为二者等价——换库后必须重跑黄金集校准。
五步校准的逐项效果与原理见 ``docs/guide-recall-calibration.md``。

另：``blocks.tsv`` / ``documents.title_tsv`` 是 **GENERATED 列**，入库即自动维护，
不存在「入库忘了建索引导致检索静默失效」这个失败模式（对应 P1 的 A1，见
``tests/test_corpus_a1_ingest_search.py``）。
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from plugins.corpus.claims import (
    CLAIMS_COMMENTS,
    CLAIMS_SQL,
    BlockView,
    ExtractStats,
    build_default_llm,
    extract_from_block,
    triage_blocks,
    with_retry,
)
from plugins.corpus.ingest import (
    CORPUS_ROOT,
    STATUS_EMPTY,
    STATUS_NEEDS_OCR,
    content_hash,
    iter_corpus_files,
    parse_document,
)

logger = logging.getLogger(__name__)

# doc_id 形如 ``2026-08-16_6f14cc14``：日期前缀即 published（documents 表无 published 列时派生）
_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})_")


@dataclass
class SearchHit:
    """一次检索命中（与 index.SearchHit 字段对齐，供工具层复用）。"""

    doc_id: str
    locator: str
    title: str
    snippet: str
    score: float
    published: str


@dataclass
class IngestStats:
    """一次跑批的结果。"""

    total: int = 0
    added: int = 0
    skipped_duplicate: int = 0
    skipped_unchanged: int = 0
    skipped_fresh: int = 0      # 因"刚被修改（可能还在拷贝）"而跳过
    needs_ocr: int = 0
    empty: int = 0
    failed: int = 0
    blocks: int = 0
    failures: list[tuple[str, str]] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.failures is None:
            self.failures = []

    def as_dict(self) -> dict[str, object]:
        data = {
            "total": self.total,
            "added": self.added,
            "skipped_duplicate": self.skipped_duplicate,
            "skipped_unchanged": self.skipped_unchanged,
            "needs_ocr": self.needs_ocr,
            "empty": self.empty,
            "failed": self.failed,
            "blocks": self.blocks,
        }
        if self.failures:
            data["failures"] = [{"path": p, "reason": r} for p, r in self.failures]
        return data


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS documents (
    doc_id       text PRIMARY KEY,
    title        text        NOT NULL,
    source_path  text        NOT NULL,
    content_hash text        NOT NULL UNIQUE,
    mime         text        NOT NULL,
    status       text        NOT NULL,
    char_count   integer     NOT NULL DEFAULT 0,
    block_count  integer     NOT NULL DEFAULT 0,
    ingested_at  timestamptz NOT NULL DEFAULT now(),
    published    date,
    title_tsv    tsvector GENERATED ALWAYS AS (to_tsvector('zhcfg', title)) STORED
);

CREATE TABLE IF NOT EXISTS blocks (
    doc_id  text    NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    seq     integer NOT NULL,
    locator text    NOT NULL,
    text    text    NOT NULL,
    tsv     tsvector GENERATED ALWAYS AS (to_tsvector('zhcfg', text)) STORED,
    PRIMARY KEY (doc_id, seq)
);

CREATE INDEX IF NOT EXISTS idx_blocks_locator       ON blocks (doc_id, locator);
CREATE INDEX IF NOT EXISTS idx_blocks_tsv          ON blocks USING gin (tsv);
CREATE INDEX IF NOT EXISTS idx_documents_published  ON documents (published DESC);
"""

# 列注释：让 PG 里的「字段」自带说明，省去翻代码。init_db 里逐条落地。
_COLUMN_COMMENTS: tuple[str, ...] = (
    # documents
    "COMMENT ON TABLE documents IS '语料文档元数据：一份研报/文章一条记录'",
    "COMMENT ON COLUMN documents.doc_id IS '文档唯一标识：<日期>_<内容哈希前8位>；短且无中文，供模型抄进 evidence.source_ref'",
    "COMMENT ON COLUMN documents.title IS '去噪后的标题；同时生成 title_tsv 进 FTS 标题权重（A 权重）'",
    "COMMENT ON COLUMN documents.source_path IS '原始文件相对路径，可回溯到磁盘'",
    "COMMENT ON COLUMN documents.content_hash IS '文件字节 SHA-256 前 16 位；幂等去重键（UNIQUE）'",
    "COMMENT ON COLUMN documents.mime IS 'MIME 类型：application/pdf / text/markdown / docx...'",
    "COMMENT ON COLUMN documents.status IS '入库状态：ok / needs_ocr / empty'",
    "COMMENT ON COLUMN documents.char_count IS '全文字符数（含空白）'",
    "COMMENT ON COLUMN documents.block_count IS '切块数'",
    "COMMENT ON COLUMN documents.ingested_at IS '入库时间（默认 now()）'",
    "COMMENT ON COLUMN documents.published IS '发布/收录日期，从 doc_id 日期前缀派生'",
    "COMMENT ON COLUMN documents.title_tsv IS '标题 FTS 向量（zhcfg 中文分词），GENERATED 列自动维护'",
    # blocks
    "COMMENT ON TABLE blocks IS '可定位的原文块：一份文档切成多条'",
    "COMMENT ON COLUMN blocks.doc_id IS '外键→documents(doc_id)，级联删除'",
    "COMMENT ON COLUMN blocks.seq IS '块序号，同文档内从 1 递增，用于排序'",
    "COMMENT ON COLUMN blocks.locator IS '定位符：PDF=页码；DOCX/MD=标题/段落。取证句柄之一'",
    "COMMENT ON COLUMN blocks.text IS '块内逐字原文；硬闸①逐字比对的来源'",
    "COMMENT ON COLUMN blocks.tsv IS '正文 FTS 向量（zhcfg），GENERATED 列自动维护'",
)

# ── 跑批台账（C 组）──────────────────────────────────────────
# 存数据库：随 pg_dump 一起备份、可 SQL 查询、由服务层收口。
# failures 单独成表而不是塞 JSONB：失败清单是要被"按文件名查"的，
# 展开成行才能直接 WHERE；且与 run 级联删除，不留孤儿。
LEDGER_SQL = """
CREATE TABLE IF NOT EXISTS ingest_runs (
    run_id             BIGSERIAL PRIMARY KEY,
    started_at         timestamptz NOT NULL DEFAULT now(),
    finished_at        timestamptz,
    duration_ms        integer,
    root               text        NOT NULL,          -- 本次扫描的语料目录
    total              integer     NOT NULL DEFAULT 0,
    added              integer     NOT NULL DEFAULT 0,
    skipped_duplicate  integer     NOT NULL DEFAULT 0,
    skipped_unchanged  integer     NOT NULL DEFAULT 0,
    needs_ocr          integer     NOT NULL DEFAULT 0,
    empty              integer     NOT NULL DEFAULT 0,
    failed             integer     NOT NULL DEFAULT 0,
    status             text        NOT NULL,          -- running | ok | warn | error
    error              text,                          -- status=error 时的异常
    trigger            text        NOT NULL DEFAULT 'manual'
);
CREATE INDEX IF NOT EXISTS idx_ingest_runs_started ON ingest_runs (started_at DESC);

CREATE TABLE IF NOT EXISTS ingest_failures (
    run_id  bigint NOT NULL REFERENCES ingest_runs(run_id) ON DELETE CASCADE,
    path    text   NOT NULL,      -- 失败文件
    reason  text   NOT NULL       -- 失败原因
);
CREATE INDEX IF NOT EXISTS idx_ingest_failures_run ON ingest_failures (run_id);
"""

LEDGER_COMMENTS: tuple[str, ...] = (
    "COMMENT ON TABLE ingest_runs IS '每次跑批一条：什么时候跑的、成了多少、是否失败'",
    "COMMENT ON COLUMN ingest_runs.status IS 'running / ok / warn（跑完但有失败或空文档）/ error（没跑起来）'",
    "COMMENT ON COLUMN ingest_runs.trigger IS '触发方式：manual（手动）/ cron / scheduler（定时）/ script（一键脚本）'",
    "COMMENT ON TABLE ingest_failures IS '单次跑批里失败的文件清单，带文件名与原因'",
)

# 台账 JSON 镜像目录：数据库挂了也能看最近跑批发生了什么
# （诊断路径不能依赖被诊断对象）
RUNS_DIR = Path("data/corpus_runs")
# 防重入的 advisory lock key（固定值，'corp'）
_INGEST_LOCK_KEY = 0x636F7270


def dsn() -> str:
    """连接串：默认本机（WSL2 localhost 经转发可达 Windows Docker 发布的端口）。"""
    return os.environ.get(
        "CORPUS_DSN", "postgresql://postgres:postgres@localhost:5432/postgres"
    )


class CorpusService:
    """语料服务：所有 PG 访问经此。"""

    def __init__(self, dsn_url: str | None = None) -> None:
        self._dsn = dsn_url or dsn()
        self._lock = threading.Lock()

    # ── 连接 ──────────────────────────────────────────────────

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(self._dsn, row_factory=dict_row, connect_timeout=10)

    def ensure_prerequisites(self) -> None:
        """确保扩展与中文检索配置存在 —— **恢复到全新库时必须先做这一步**。

        扩展（zhparser / pgvector / pg_trgm）与检索配置 ``zhcfg`` 都是**库级对象**，
        不会随 ``CREATE DATABASE`` 继承（除非来自 template）。灾备恢复到一个新库时，
        若不做这一步，``init_db`` 建生成列会因 ``zhcfg`` 不存在而失败。
        """
        with self._connect() as conn:
            for ext in ("zhparser", "vector", "pg_trgm"):
                try:
                    conn.execute(f"CREATE EXTENSION IF NOT EXISTS {ext}")
                except psycopg.Error as exc:
                    raise RuntimeError(
                        f"无法创建扩展 {ext}（通常需要超级用户权限）：{exc}"
                    ) from exc
            if not conn.execute(
                "SELECT 1 FROM pg_ts_config WHERE cfgname = 'zhcfg'"
            ).fetchone():
                conn.execute("CREATE TEXT SEARCH CONFIGURATION zhcfg (PARSER = zhparser)")
                conn.execute(
                    "ALTER TEXT SEARCH CONFIGURATION zhcfg ADD MAPPING FOR "
                    "a,b,c,e,f,h,i,j,k,l,m,n,o,p,q,r,s,t,u,v,w,x,y,z WITH simple"
                )
            conn.commit()

    def init_db(self) -> None:
        self.ensure_prerequisites()
        with self._connect() as conn:
            conn.execute(SCHEMA_SQL)
            conn.execute(LEDGER_SQL)
            conn.execute(CLAIMS_SQL)  # D2：claim / entities（幂等，不影响既有表）
            for stmt in (*_COLUMN_COMMENTS, *LEDGER_COMMENTS, *CLAIMS_COMMENTS):
                conn.execute(stmt)
            conn.commit()

    # ── 写入 ──────────────────────────────────────────────────

    @staticmethod
    def _published_of(doc_id: str) -> str | None:
        m = _DATE_RE.match(doc_id)
        return m.group(1) if m else None

    def ingest_path(self, path: str | Path) -> tuple[str, bool]:
        """解析并落库一份，返回 ``(status, added)``。"""
        parsed = parse_document(path)
        published = self._published_of(parsed.doc_id)
        with self._lock, self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO documents
                        (doc_id, title, source_path, content_hash, mime, status,
                         char_count, block_count, published)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (content_hash) DO NOTHING
                    RETURNING true
                    """,
                    (
                        parsed.doc_id,
                        parsed.title,
                        str(parsed.source_path),
                        parsed.content_hash,
                        parsed.mime,
                        parsed.status,
                        parsed.char_count,
                        len(parsed.blocks),
                        published,
                    ),
                )
                inserted = cur.fetchone() is not None
            if inserted:
                with conn.cursor() as cur:
                    cur.executemany(
                        "INSERT INTO blocks (doc_id, seq, locator, text) VALUES (%s,%s,%s,%s)",
                        [(parsed.doc_id, b.seq, b.locator, b.text) for b in parsed.blocks],
                    )
            conn.commit()
        return parsed.status, inserted

    def ingest_dir(
        self,
        root: str | Path = CORPUS_ROOT,
        *,
        rebuild_index: bool = True,
        min_age: float = 0.0,
    ) -> IngestStats:
        """跑批入库一个目录，返回统计。

        三件 P0 缺口在此补齐：跳过已入库未变（content_hash 比对）、失败带文件名与原因、
        末尾索引可用（PG 用生成列自动维护 ``tsv``，无需手动重建 —— 消除 SQLite 的
        "全表重建长事务"问题）。

        ``min_age``（秒）：**跳过最近刚被修改过的文件**。
        大文件拷贝/同步过程中跑批，会解析到只写了一半的 PDF ⇒ 产生一条**假失败**
        （文件其实没问题，只是还没拷完）。跳过它们即可，下次跑批会自然补上。
        0 表示不启用。
        """
        stats = IngestStats()
        known = self._known_hashes()

        files = list(iter_corpus_files(root))
        if min_age > 0:
            cutoff = time.time() - min_age
            fresh = [p for p in files if p.stat().st_mtime > cutoff]
            files = [p for p in files if p.stat().st_mtime <= cutoff]
            if fresh:
                stats.skipped_fresh = len(fresh)
                logger.warning(
                    "跳过 %s 份刚被修改的文件（可能仍在拷贝中）：稍后再跑一次即可，"
                    "或由下次跑批自动补上",
                    len(fresh),
                )

        with self._lock, self._connect() as conn:
            for path in files:
                stats.total += 1
                key = str(path)
                try:
                    digest = content_hash(path)
                except OSError as exc:
                    stats.failed += 1
                    stats.failures.append((key, f"读取失败：{exc}"))
                    logger.warning("ingest 读取失败：%s", key, exc_info=True)
                    continue

                if known.get(key) == digest:
                    stats.skipped_unchanged += 1
                    continue

                try:
                    parsed = parse_document(path)
                except Exception as exc:  # 单份失败不中断整批
                    stats.failed += 1
                    stats.failures.append((key, f"解析失败：{exc}"))
                    logger.exception("ingest 解析失败：%s", key)
                    continue

                published = self._published_of(parsed.doc_id)
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO documents
                            (doc_id, title, source_path, content_hash, mime, status,
                             char_count, block_count, published)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (content_hash) DO NOTHING
                        RETURNING true
                        """,
                        (
                            parsed.doc_id,
                            parsed.title,
                            str(parsed.source_path),
                            parsed.content_hash,
                            parsed.mime,
                            parsed.status,
                            parsed.char_count,
                            len(parsed.blocks),
                            published,
                        ),
                    )
                    inserted = cur.fetchone() is not None
                if inserted:
                    with conn.cursor() as cur:
                        cur.executemany(
                            "INSERT INTO blocks (doc_id, seq, locator, text) VALUES (%s,%s,%s,%s)",
                            [(parsed.doc_id, b.seq, b.locator, b.text) for b in parsed.blocks],
                        )
                    stats.added += 1
                    stats.blocks += len(parsed.blocks)
                else:
                    stats.skipped_duplicate += 1

                if parsed.status == STATUS_NEEDS_OCR:
                    stats.needs_ocr += 1
                elif parsed.status == STATUS_EMPTY:
                    stats.empty += 1

            conn.commit()

        logger.info(
            "ingest 完成：total=%s added=%s unchanged=%s dup=%s failed=%s",
            stats.total,
            stats.added,
            stats.skipped_unchanged,
            stats.skipped_duplicate,
            stats.failed,
        )
        return stats

    def _known_hashes(self) -> dict[str, str]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT source_path, content_hash FROM documents")
            return {r["source_path"]: r["content_hash"] for r in cur.fetchall()}

    # ── 读取 ──────────────────────────────────────────────────

    # 共享 SELECT：用 {tsquery} 占位，调用方填入 AND 或 OR 形式的 tsquery。
    # 模板里的 %(q)s / %(limit)s 是 psycopg 参数，不是 str.format 占位符，不会被破坏。
    _SEARCH_SELECT = """
        SELECT b.doc_id, b.locator, d.title, d.published AS published,
               (ts_rank(d.title_tsv, {tsquery}) * 5
                + ts_rank(b.tsv, {tsquery})) AS score,
               ts_headline('zhcfg', b.text,
                   {tsquery},
                   'MaxWords=28, MinWords=8, ShortWord=1') AS snippet
        FROM blocks b
        JOIN documents d ON d.doc_id = b.doc_id
        WHERE setweight(d.title_tsv,'A') || setweight(b.tsv,'B') @@ {tsquery}
        ORDER BY score DESC
        LIMIT %(limit)s
    """

    def search(self, query: str, *, limit: int = 10) -> list[SearchHit]:
        q = (query or "").strip()
        if not q:
            return []
        candidate_limit = max(50, limit * 10)
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                self._SEARCH_SELECT.format(
                    tsquery="plainto_tsquery('zhcfg', %(q)s)"
                ),
                {"q": q, "limit": candidate_limit},
            )
            rows = cur.fetchall()
            if not rows:
                # AND 全空时退回 OR：宁可给几条带噪音的候选，
                # 也不要让调用方误判「资料里没有」——
                # 与 P0 的 FTS5 AND→OR 兜底一致。
                cur.execute(
                    "SELECT plainto_tsquery('zhcfg', %(q)s)::text AS tsv", {"q": q}
                )
                row = cur.fetchone()
                and_text = row["tsv"] if row else ""
                or_ts = and_text.replace(" & ", " | ")
                if or_ts and or_ts.strip() not in ("''",):
                    cur.execute(
                        self._SEARCH_SELECT.format(
                            tsquery="to_tsquery('zhcfg', %(or_ts)s)"
                        ),
                        {"or_ts": or_ts, "limit": candidate_limit},
                    )
                    rows = cur.fetchall()

        # 时效型查询（含「最新/近期/最近」等词）：对 published 做轻度 Recency 偏置，
        # 让「最新一期」这类问题倾向更近的文档。非时效查询不受影响。
        _RECENCY_WORDS = ("最新", "近期", "最近", "本期", "新一期", "最近一篇", "上一期")
        if any(w in q for w in _RECENCY_WORDS) and rows:
            pubs = [r["published"] for r in rows if r.get("published")]
            if pubs:
                lo, hi = min(pubs), max(pubs)
                span = (hi - lo).days or 1
                for r in rows:
                    pub = r.get("published")
                    if pub is not None:
                        r["score"] = (r["score"] or 0.0) + 0.1 * ((pub - lo).days / span)

        # 同一文档多个块都命中时，只保留分最高的那一块，再按文档取 top-k。
        # 否则「一份多块的长文档」会用它的 N 个块霸占前 N 名，把真正相关的
        # 其他文档挤出候选集（FTS 按块排序的经典坑）。顺带让工具输出不再把
        # 同一文档刷好几遍。
        best_per_doc: dict[str, dict] = {}
        for r in rows:
            prev = best_per_doc.get(r["doc_id"])
            if prev is None or (r["score"] or 0.0) > (prev["score"] or 0.0):
                best_per_doc[r["doc_id"]] = r
        ranked = sorted(
            best_per_doc.values(), key=lambda r: r["score"] or 0.0, reverse=True
        )[:limit]

        return [
            SearchHit(
                doc_id=r["doc_id"],
                locator=r["locator"],
                title=r["title"],
                snippet=r["snippet"],
                score=float(r["score"]) if r["score"] is not None else 0.0,
                published=(r["doc_id"][:10] if len(r["doc_id"]) >= 10 else "undated"),
            )
            for r in ranked
        ]

    def fetch(self, doc_id: str, locator: str) -> FetchedBlock | None:
        from plugins.corpus.fetch import FetchedBlock  # 延迟导入，避免循环依赖

        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT doc_id, seq, locator, text FROM blocks "
                "WHERE doc_id = %s AND locator = %s",
                (str(doc_id), str(locator)),
            )
            r = cur.fetchone()
        if r is None:
            return None
        return FetchedBlock(doc_id=r["doc_id"], seq=r["seq"], locator=r["locator"], text=r["text"])

    def document_text(self, doc_id: str) -> str | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT string_agg(text, chr(10) ORDER BY seq) AS t "
                "FROM blocks WHERE doc_id = %s",
                (str(doc_id),),
            )
            row = cur.fetchone()
        return row["t"] if row and row["t"] else None

    def blocks_of(self, doc_id: str) -> list[dict[str, object]]:
        """取一份文档的全部块（``seq`` / ``locator`` / ``text``）—— D2 抽取的输入。"""
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT seq, locator, text FROM blocks WHERE doc_id = %s ORDER BY seq",
                (str(doc_id),),
            )
            return list(cur.fetchall())

    def extract_claims(
        self,
        *,
        llm: Callable[[str], str] | None = None,
        doc_ids: list[str] | None = None,
        limit: int | None = None,
        retry_attempts: int = 3,
        sleep_between: float = 0.0,
        skip_existing: bool = True,
        dry_run: bool = False,
    ) -> ExtractStats:
        """D2：**分级 → LLM 抽取 → 落库**。

        ``llm`` 可注入（测试用假实现）；不给则用 :func:`build_default_llm`。
        ``retry_attempts`` 控制退避重试（实测供应商会 429 限流，重试即可成功）。
        ``sleep_between`` 块间限速（秒）：610 块连打会触发限流风暴，全量跑批建议 1s。
        ``skip_existing`` 断点续跑：跳过 claims 表已有 ``(doc_id, seq)`` 的块——
        ``ON CONFLICT`` 只保证不重复**插入**，不挡重复的 **LLM 调用**；批跑中断后
        重跑若不跳过，已成功的块会再花一遍钱。
        纪律与 ingest 一致：**单块失败只记 failure，不中断整批**。
        """
        llm_fn = None
        if not dry_run:
            llm_fn = llm if llm is not None else build_default_llm()
            if retry_attempts > 1:
                llm_fn = with_retry(llm_fn, attempts=retry_attempts)

        done: set[tuple[str, int]] = set()
        if skip_existing:
            with self._connect() as conn:
                done = {
                    (str(row["doc_id"]), int(row["seq"]))
                    for row in conn.execute("SELECT DISTINCT doc_id, seq FROM claims").fetchall()
                }
        stats = ExtractStats()

        targets = list(doc_ids) if doc_ids else [str(row["doc_id"]) for row in self.list_documents()]
        for doc_id in targets:
            stats.documents += 1
            rows = self.blocks_of(doc_id)
            stats.blocks += len(rows)
            views = [BlockView(int(r["seq"]), str(r["locator"]), str(r["text"] or "")) for r in rows]
            candidates, skipped = triage_blocks(views)
            stats.skipped_no_signal += skipped

            pending: list = []
            for block in candidates:
                if limit is not None and stats.candidates >= limit:
                    break
                if (doc_id, block.seq) in done:
                    stats.skipped_existing += 1
                    continue
                stats.candidates += 1
                if dry_run:  # 错峰前只统计将抽取多少块，不调 LLM、不入库
                    continue
                try:
                    pending.extend(extract_from_block(block, doc_id=doc_id, llm=llm_fn))
                except Exception as exc:  # 单块失败不得拖垮整批
                    stats.failed += 1
                    stats.failures.append(
                        {
                            "doc_id": doc_id,
                            "locator": block.locator,
                            "reason": f"{type(exc).__name__}: {exc}"[:200],
                        }
                    )
                if sleep_between > 0:
                    time.sleep(sleep_between)
            if not dry_run:
                stats.claims += self._insert_claims(pending)

        return stats

    def _insert_claims(self, claims: list) -> int:
        """批量写入 claim；``(doc_id, seq, claim_text)`` 重复则跳过（幂等重跑）。"""
        if not claims:
            return 0
        rows = [
            (
                str(c.doc_id), int(c.seq), str(c.locator), str(c.claim_text), str(c.kind),
                list(c.tickers), c.metric, c.value_text, c.period, c.confidence,
            )
            for c in claims
        ]
        with self._lock, self._connect() as conn:
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO claims (doc_id, seq, locator, claim_text, kind, tickers, "
                    "metric, value_text, period, confidence) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                    "ON CONFLICT (doc_id, seq, claim_text) DO NOTHING",
                    rows,
                )
                inserted = cur.rowcount
            conn.commit()
        return max(inserted, 0)

    def claims_of(
        self,
        *,
        doc_id: str | None = None,
        ticker: str | None = None,
        kind: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, object]]:
        """查询 claim（按文档 / 标的 / 类型）—— D3 挖掘与 D4 聚合的入口。"""
        sql = (
            "SELECT claim_id, doc_id, seq, locator, claim_text, kind, tickers, "
            "metric, value_text, period, confidence FROM claims"
        )
        where: list[str] = []
        params: list[object] = []
        if doc_id:
            where.append("doc_id = %s")
            params.append(str(doc_id))
        if ticker:
            where.append("%s = ANY(tickers)")
            params.append(str(ticker))
        if kind:
            where.append("kind = %s")
            params.append(str(kind))
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY doc_id, seq LIMIT %s"
        params.append(int(limit))

        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(sql, params)
            return list(cur.fetchall())

    def list_documents(self) -> list[dict[str, object]]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT doc_id, title, source_path, mime, status, "
                "block_count, char_count, published FROM documents ORDER BY doc_id"
            )
            rows = cur.fetchall()
        return [dict(r) for r in rows]

    def source_resolver(self) -> Callable[[str], str | None]:
        """给 ``verify_card`` 用的 ``doc_id -> 全文`` 解析器。"""

        def resolve(doc_id: str) -> str | None:
            return self.document_text(doc_id)

        return resolve

    # ── 备份 ──────────────────────────────────────────────────

    # 导出时显式指定列：**排除 GENERATED 列**（documents.title_tsv / blocks.tsv）。
    # 它们由 PG 在恢复写入时自动重算，写回去会直接报
    # "cannot insert a non-DEFAULT value into column ... generated always"。
    _BACKUP_COLUMNS: dict[str, tuple[str, ...]] = {
        "documents": (
            "doc_id", "title", "source_path", "content_hash", "mime", "status",
            "char_count", "block_count", "ingested_at", "published",
        ),
        "blocks": ("doc_id", "seq", "locator", "text"),
    }

    @staticmethod
    def _pg_tool(name: str) -> str | None:
        """外部客户端工具（``pg_dump`` / ``pg_restore``）是否可用。"""
        return shutil.which(name)

    def backup(self, dest: str | Path, *, mode: str = "auto") -> Path:
        """备份语料库，返回产物路径（``corpus.dump`` 文件或备份目录）。

        ``mode``：

        - ``"auto"``（默认）：有 ``pg_dump`` 就用它，否则退回纯 Python 的 CSV 逻辑备份；
        - ``"pg_dump"``：强制用 ``pg_dump``，找不到就报错（**拒绝静默降级**）；
        - ``"csv"``：只用 CSV，不依赖任何外部二进制。

        **为什么优先 pg_dump**：它在单个事务里做**一致性快照**，并带上 schema、
        约束、索引与生成列定义，可用 ``pg_restore`` 选择性恢复。
        CSV 模式只导两张表的数据、恢复时靠 ``init_db()`` 重建 schema，
        适合装不了客户端二进制的环境（本工作区就没有 ``pg_dump``）。
        """
        if mode not in ("auto", "pg_dump", "csv"):
            raise ValueError(f"未知备份模式：{mode!r}")
        target = Path(dest)
        use_pg_dump = mode == "pg_dump" or (mode == "auto" and self._pg_tool("pg_dump"))
        if use_pg_dump and self._pg_tool("pg_dump") is None:
            raise RuntimeError("mode='pg_dump' 但未找到 pg_dump，拒绝静默降级")
        return self._backup_pg_dump(target) if use_pg_dump else self._backup_csv(target)

    def _backup_pg_dump(self, dest: Path) -> Path:
        dest.mkdir(parents=True, exist_ok=True)
        path = dest / "corpus.dump"
        proc = subprocess.run(
            ["pg_dump", "--format=custom", "--no-owner", "--no-acl",
             "--file", str(path), self._dsn],
            capture_output=True, text=True,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"pg_dump 失败：{(proc.stderr or '').strip()[:300]}")
        self._write_manifest(dest, "pg_dump")
        logger.info("backup(pg_dump) 完成：%s", path)
        return path

    def _backup_csv(self, dest: Path) -> Path:
        dest.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            for table, columns in self._BACKUP_COLUMNS.items():
                columns_sql = ", ".join(columns)
                with (dest / f"{table}.csv").open("wb") as fh, conn.cursor() as cur:
                    with cur.copy(
                        f"COPY {table} ({columns_sql}) TO STDOUT WITH (FORMAT CSV, HEADER)"
                    ) as copy:
                        while True:
                            chunk = copy.read()
                            if not chunk:
                                break
                            fh.write(chunk)
        self._write_manifest(dest, "corpus-csv")
        logger.info("backup(csv) 完成：%s", dest)
        return dest

    def _write_manifest(self, dest: Path, fmt: str) -> None:
        """写备份清单：格式、时间、行数、列顺序 —— 恢复时按它校验。"""
        (dest / "manifest.json").write_text(
            json.dumps(
                {
                    "format": fmt,
                    "created_at": datetime.now(UTC).isoformat(),
                    "counts": self._row_counts(),
                    "columns": {k: list(v) for k, v in self._BACKUP_COLUMNS.items()},
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def _row_counts(self) -> dict[str, int]:
        with self._connect() as conn:
            return {
                table: conn.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"]
                for table in self._BACKUP_COLUMNS
            }

    def restore(self, src: str | Path, target_dsn: str) -> dict[str, int]:
        """把备份恢复到 ``target_dsn`` 指向的库，返回恢复后的行数。

        ⚠️ 会写目标库：``pg_dump`` 模式带 ``--clean --if-exists``，会先删同名表。
        调用前务必确认 DSN 没写错。
        """
        path = Path(src)
        if (path.is_dir() and (path / "corpus.dump").exists()) or (
            path.is_file() and path.suffix == ".dump"
        ):
            dump = path / "corpus.dump" if path.is_dir() else path
            return self._restore_pg_dump(dump, target_dsn)
        if path.is_dir() and (path / "manifest.json").exists():
            return self._restore_csv(path, target_dsn)
        raise ValueError(f"无法识别的备份：{src}")

    def _restore_pg_dump(self, dump: Path, target_dsn: str) -> dict[str, int]:
        tool = self._pg_tool("pg_restore")
        if tool is None:
            raise RuntimeError("未找到 pg_restore，无法恢复 .dump 备份")
        proc = subprocess.run(
            [tool, "--no-owner", "--no-acl", "--dbname", target_dsn,
             "--clean", "--if-exists", str(dump)],
            capture_output=True, text=True,
        )
        # pg_restore 遇到「对象不存在」等提示也会返回非 0，
        # 所以以「恢复后行数」为准，退出码只用来告警。
        if proc.returncode != 0:
            logger.warning("pg_restore 返回非 0：%s", (proc.stderr or "").strip()[:300])
        counts = CorpusService(target_dsn)._row_counts()
        logger.info("restore(pg_dump) 完成：%s", counts)
        return counts

    def _restore_csv(self, src: Path, target_dsn: str) -> dict[str, int]:
        manifest = json.loads((src / "manifest.json").read_text(encoding="utf-8"))
        if manifest.get("format") != "corpus-csv":
            raise ValueError(f"不是 CSV 备份：{manifest.get('format')!r}")
        expected: dict[str, int] = manifest.get("counts") or {}

        target = CorpusService(target_dsn)
        target.init_db()  # 建表 + 生成列（zhcfg 检索配置须已存在于目标库）
        with target._connect() as conn:
            for table, columns in self._BACKUP_COLUMNS.items():
                columns_sql = ", ".join(columns)
                data = (src / f"{table}.csv").read_bytes()
                with conn.cursor() as cur, cur.copy(
                    f"COPY {table} ({columns_sql}) FROM STDIN WITH (FORMAT CSV, HEADER)"
                ) as copy:
                    copy.write(data)
            conn.commit()

        counts = target._row_counts()
        if expected and counts != expected:
            raise RuntimeError(f"恢复后行数与备份不一致：{counts} != {expected}")
        logger.info("restore(csv) 完成：%s", counts)
        return counts

    def snapshot(self, dest: str | Path) -> Path:
        """兼容旧名，等价于 :meth:`backup`（默认 ``auto`` 模式）。"""
        return self.backup(dest)

    # ── 台账 / 梳理 ───────────────────────────────────────────

    def corpus_file_count(self, root: str | Path = CORPUS_ROOT) -> int:
        """语料目录里**可解析**的文件数（与入库数对比即可知道是否全跑完）。

        份数不预设目标值：放多少文件就该 ingest 多少，
        所以验收用「目录文件数 == ``documents`` 数」而不是某个固定数字。
        目录不存在时返回 0。
        """
        try:
            return sum(1 for _ in iter_corpus_files(root))
        except OSError:  # 目录不存在 / 不可读
            return 0

    def stats(self) -> dict[str, object]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM documents")
            total = cur.fetchone()["n"]
            cur.execute("SELECT COUNT(*) AS n FROM blocks")
            blocks = cur.fetchone()["n"]
            cur.execute("SELECT status, COUNT(*) AS n FROM documents GROUP BY status")
            by_status = {r["status"]: r["n"] for r in cur.fetchall()}
            cur.execute("SELECT mime, COUNT(*) AS n FROM documents GROUP BY mime")
            by_mime = {r["mime"]: r["n"] for r in cur.fetchall()}
            cur.execute(
                "SELECT MIN(published) AS lo, MAX(published) AS hi FROM documents"
            )
            span = cur.fetchone()
        return {
            "documents": total,
            "blocks": blocks,
            "by_status": by_status,
            "by_mime": by_mime,
            "published_from": span["lo"] if span else None,
            "published_to": span["hi"] if span else None,
            # 目录里实际有多少可解析文件 —— 与 documents 对比即知是否全跑完
            "corpus_files": self.corpus_file_count(),
            "fully_ingested": total == self.corpus_file_count(),
            "dsn": self._dsn,
        }

    def list_by_status(self, status: str) -> list[dict[str, object]]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT doc_id, title, source_path, published FROM documents "
                "WHERE status = %s ORDER BY doc_id",
                (status,),
            )
            rows = cur.fetchall()
        return [dict(r) for r in rows]

    # ── 跑批任务化（C1a）──────────────────────────────────────
    #
    # 跑批 = 加锁 → 开始记台账 → ingest_dir → 收尾记台账 → 返回退出码。
    # 退出码语义（调度器唯一能看的东西）：
    #   0 ok    全部成功
    #   1 warn  跑完了，但有失败 / 空文档 / 需 OCR —— 需要人看
    #   2 error 没跑起来（PG 不可达 / 已有跑批在跑 / 目录不存在）—— 必须处理

    def run_ingest(
        self,
        root: str | Path = CORPUS_ROOT,
        *,
        trigger: str = "manual",
        min_age: float = 60.0,
    ) -> dict[str, object]:
        """跑一次完整批：防重入 → 落台账 → 返回结果（含 ``exit_code``）。

        ``trigger`` 记进台账，用来区分是谁触发的（手动 / 定时 / 脚本）。
        ``min_age`` 默认 60 秒：跳过可能仍在拷贝中的文件，避免假失败。
        """
        started = time.monotonic()
        try:
            return self._ingest_inner(root, trigger=trigger, min_age=min_age)
        except Exception as exc:
            # 兜住"跑批没跑起来"的一切情况：数据库不可达、目录不存在、
            # 权限问题…… 调度器只能看退出码，所以必须给 2，不能抛栈。
            logger.exception("跑批未能启动")
            record: dict[str, object] = {
                "run_id": None,
                "status": "error",
                "error": f"{type(exc).__name__}: {exc}",
                "total": 0, "added": 0, "skipped_duplicate": 0,
                "skipped_unchanged": 0, "skipped_fresh": 0,
                "needs_ocr": 0, "empty": 0, "failed": 0,
                "failures": [],
                "duration_ms": int((time.monotonic() - started) * 1000),
                "exit_code": 2,
            }
            # 数据库可能就是挂的那个 —— 这时更要留下痕迹，所以写磁盘镜像
            self._ledger_json(record)
            return record

    def _ingest_inner(
        self, root: str | Path, *, trigger: str, min_age: float
    ) -> dict[str, object]:
        self.init_db()
        with self._connect() as lock_conn:
            got = lock_conn.execute(
                "SELECT pg_try_advisory_lock(%s) AS got", (_INGEST_LOCK_KEY,)
            ).fetchone()
            if not got or not got["got"]:
                msg = "已有跑批在运行（未取得 advisory lock），本次跳过"
                logger.warning(msg)
                return {
                    "run_id": None, "status": "error", "error": msg,
                    "exit_code": 2,
                }
            try:
                return self._ingest_locked(root, trigger=trigger, min_age=min_age)
            finally:
                lock_conn.execute(
                    "SELECT pg_advisory_unlock(%s)", (_INGEST_LOCK_KEY,)
                )
                lock_conn.commit()

    def _ingest_locked(
        self, root: str | Path, *, trigger: str, min_age: float
    ) -> dict[str, object]:
        run_id = self._ledger_start(root, trigger)
        started = time.monotonic()
        try:
            stats = self.ingest_dir(root, min_age=min_age)
        except Exception as exc:  # 跑批整个挂了（如 PG 不可达）
            logger.exception("跑批失败")
            record = self._ledger_finish(
                run_id, None, "error", error=str(exc),
                duration_ms=int((time.monotonic() - started) * 1000),
            )
            return {**record, "exit_code": 2}

        # 空文档 / 需 OCR 不算"失败"，但必须让人看见 —— 否则报告静默搜不到
        problems = stats.failed + stats.empty + stats.needs_ocr
        status = "ok" if problems == 0 else "warn"
        record = self._ledger_finish(
            run_id, stats, status,
            duration_ms=int((time.monotonic() - started) * 1000),
        )
        exit_code = 0 if status == "ok" else 1
        logger.info(
            "跑批结束：status=%s added=%s failed=%s empty=%s needs_ocr=%s",
            status, stats.added, stats.failed, stats.empty, stats.needs_ocr,
        )
        return {**record, "exit_code": exit_code}

    def _ledger_start(self, root: str | Path, trigger: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "INSERT INTO ingest_runs (root, status, trigger) "
                "VALUES (%s, 'running', %s) RETURNING run_id",
                (str(root), trigger),
            ).fetchone()
            conn.commit()
            return int(row["run_id"])

    def _ledger_finish(
        self,
        run_id: int,
        stats: IngestStats | None,
        status: str,
        *,
        error: str | None = None,
        duration_ms: int,
    ) -> dict[str, object]:
        values = {
            "run_id": run_id,
            "status": status,
            "error": error,
            "duration_ms": duration_ms,
            "total": stats.total if stats else 0,
            "added": stats.added if stats else 0,
            "skipped_duplicate": stats.skipped_duplicate if stats else 0,
            "skipped_unchanged": stats.skipped_unchanged if stats else 0,
            "skipped_fresh": stats.skipped_fresh if stats else 0,
            "needs_ocr": stats.needs_ocr if stats else 0,
            "empty": stats.empty if stats else 0,
            "failed": stats.failed if stats else 0,
        }
        with self._connect() as conn:
            conn.execute(
                "UPDATE ingest_runs SET finished_at = now(), duration_ms = %(duration_ms)s, "
                "total = %(total)s, added = %(added)s, "
                "skipped_duplicate = %(skipped_duplicate)s, "
                "skipped_unchanged = %(skipped_unchanged)s, needs_ocr = %(needs_ocr)s, "
                "empty = %(empty)s, failed = %(failed)s, status = %(status)s, "
                "error = %(error)s WHERE run_id = %(run_id)s",
                values,
            )
            failures = list(stats.failures) if stats else []
            for path, reason in failures:
                conn.execute(
                    "INSERT INTO ingest_failures (run_id, path, reason) VALUES (%s,%s,%s)",
                    (run_id, path, reason),
                )
            conn.commit()

        record = {k: v for k, v in values.items() if k != "run_id"}
        record["run_id"] = run_id
        record["failures"] = [{"path": p, "reason": r} for p, r in failures]
        self._ledger_json(record)
        return record

    def _ledger_json(self, record: dict[str, object]) -> None:
        """台账镜像到磁盘（JSONL）。

        为什么还要一份：数据库出问题时，诊断信息不能只存在于"被诊断的对象"里。
        JSONL 天然支持追加，不需要读-改-写。
        """
        try:
            RUNS_DIR.mkdir(parents=True, exist_ok=True)
            with (RUNS_DIR / "runs.jsonl").open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        except OSError as exc:  # 镜像失败不影响主流程，但必须留痕
            logger.warning("台账 JSON 镜像写入失败：%s", exc)

    # ── 台账查询（C2a）────────────────────────────────────────

    def recent_runs(self, limit: int = 10) -> list[dict[str, object]]:
        """最近 N 次跑批概览。"""
        with self._connect() as conn:
            return [
                dict(r)
                for r in conn.execute(
                    "SELECT run_id, started_at, finished_at, duration_ms, root, total, "
                    "added, skipped_unchanged, failed, empty, needs_ocr, status, "
                    "error, trigger FROM ingest_runs ORDER BY run_id DESC LIMIT %s",
                    (limit,),
                ).fetchall()
            ]

    def run_failures(self, run_id: int | None = None) -> list[dict[str, object]]:
        """失败清单：不指定 run_id 则列出所有仍有记录的失败。"""
        sql = (
            "SELECT f.run_id, r.started_at, f.path, f.reason "
            "FROM ingest_failures f JOIN ingest_runs r USING (run_id)"
        )
        params: tuple[object, ...] = ()
        if run_id is not None:
            sql += " WHERE f.run_id = %s"
            params = (run_id,)
        sql += " ORDER BY f.run_id DESC"
        with self._connect() as conn:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

    def list_revisions(self) -> dict[str, list[str]]:
        """同一 source_path 出现多份（修订/重发）—— 已知缺口，E1 用 superseded_by 解决。"""
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT source_path, array_agg(doc_id ORDER BY doc_id) AS ids "
                "FROM documents GROUP BY source_path HAVING COUNT(*) > 1"
            )
            rows = cur.fetchall()
        return {r["source_path"]: r["ids"] for r in rows}


_SERVICES: dict[str, CorpusService] = {}
_SERVICES_LOCK = threading.Lock()


def get_service(dsn_url: str | None = None) -> CorpusService:
    key = dsn_url or dsn()
    with _SERVICES_LOCK:
        svc = _SERVICES.get(key)
        if svc is None:
            svc = CorpusService(key)
            _SERVICES[key] = svc
        return svc


def _main() -> int:
    """返回进程退出码：0 ok / 1 warn（有失败，需人看）/ 2 error（没跑起来）。"""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(prog="corpus-service", description="语料库 PG 服务层 CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_ingest = sub.add_parser("ingest", help="跑批入库一个目录（幂等，并落台账）")
    p_ingest.add_argument("--dir", default=CORPUS_ROOT)
    p_ingest.add_argument("--db", default=None)
    p_ingest.add_argument(
        "--trigger", default="manual",
        choices=["manual", "cron", "scheduler", "script"],
        help="记进台账的触发来源（默认 manual）",
    )
    p_ingest.add_argument(
        "--min-age", type=float, default=60.0,
        help="跳过最近 N 秒內被修改的文件，避免解析到拷贝一半的 PDF（0=不启用，默认 60）",
    )

    p_runs = sub.add_parser("runs", help="最近跑批台账概览")
    p_runs.add_argument("--limit", type=int, default=10)
    p_runs.add_argument("--db", default=None)

    p_fail = sub.add_parser("failures", help="失败清单（带文件名与原因）")
    p_fail.add_argument("--run", type=int, default=None, help="只看某一次跑批")
    p_fail.add_argument("--db", default=None)

    p_stats = sub.add_parser("stats", help="台账总览")
    p_stats.add_argument("--db", default=None)

    p_backup = sub.add_parser("backup", help="备份（优先 pg_dump，无则 CSV 兜底）")
    p_backup.add_argument("--out", required=True, help="输出目录")
    p_backup.add_argument("--mode", default="auto", choices=["auto", "pg_dump", "csv"])
    p_backup.add_argument("--db", default=None)

    p_restore = sub.add_parser("restore", help="从备份恢复到指定库（会写目标库）")
    p_restore.add_argument("--src", required=True, help="备份目录或 corpus.dump 文件")
    p_restore.add_argument("--db", required=True, help="目标库 DSN，务必确认")

    p_claims = sub.add_parser("extract-claims", help="D2：分级 + LLM 抽取 claim 并落库")
    p_claims.add_argument("--limit", type=int, default=None, help="最多处理多少个候选块（先跑小样本）")
    p_claims.add_argument(
        "--sleep", type=float, default=1.0,
        help="块间限速秒数，防供应商 429 限流风暴（0=不限速；全量跑批建议 1s）",
    )
    p_claims.add_argument("--doc", default=None, help="只处理指定 doc_id")
    p_claims.add_argument(
        "--dry-run", action="store_true",
        help="只统计将抽取多少块 / 预计多少次 LLM 调用与耗时，不真正调模型（错峰前规划批次用）",
    )
    p_claims.add_argument("--db", default=None)

    p_show_claims = sub.add_parser("claims", help="查询已抽取的 claim（D3/D4 的数据源）")
    p_show_claims.add_argument("--doc", default=None)
    p_show_claims.add_argument("--ticker", default=None, help="按标的代码过滤，如 600519.SH")
    p_show_claims.add_argument("--kind", default=None, choices=["fact", "forecast"])
    p_show_claims.add_argument("--limit", type=int, default=50)
    p_show_claims.add_argument("--db", default=None)

    p_snap = sub.add_parser("snapshot", help="[旧名] 等价于 backup")
    p_snap.add_argument("--out", required=True)
    p_snap.add_argument("--db", default=None)

    args = parser.parse_args()
    svc = get_service(args.db)

    if args.cmd == "extract-claims":
        doc_ids = [args.doc] if args.doc else None
        try:
            stats = svc.extract_claims(
                doc_ids=doc_ids, limit=args.limit, sleep_between=args.sleep,
                dry_run=args.dry_run,
            )
        except RuntimeError as exc:  # 缺 OPENAI_API_KEY 等
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
            return 2
        out = stats.as_dict()
        if args.dry_run:
            # 估算：每次 LLM 调用 ~2s 响应 + 限速间隔（实测均值，仅作排期参考）
            calls = out["candidates"]
            est_seconds = calls * (max(args.sleep, 0) + 2.0)
            out = {
                **out,
                "dry_run": True,
                "estimated_llm_calls": calls,
                "estimated_seconds": round(est_seconds, 1),
                "estimated_minutes": round(est_seconds / 60, 1),
            }
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0 if args.dry_run else (1 if stats.failed else 0)

    if args.cmd == "claims":
        rows = svc.claims_of(
            doc_id=args.doc, ticker=args.ticker, kind=args.kind, limit=args.limit
        )
        print(json.dumps(rows, ensure_ascii=False, indent=2, default=str))
        return 0

    if args.cmd == "ingest":
        result = svc.run_ingest(args.dir, trigger=args.trigger, min_age=args.min_age)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        code = result.get("exit_code", 2)
        return code if isinstance(code, int) else 2
    elif args.cmd == "runs":
        svc.init_db()
        print(json.dumps(
            svc.recent_runs(args.limit), ensure_ascii=False, indent=2, default=str
        ))
    elif args.cmd == "failures":
        svc.init_db()
        print(json.dumps(
            svc.run_failures(args.run), ensure_ascii=False, indent=2, default=str
        ))
    elif args.cmd == "stats":
        svc.init_db()
        print(json.dumps(svc.stats(), ensure_ascii=False, indent=2))
    elif args.cmd in ("backup", "snapshot"):
        mode = getattr(args, "mode", "auto")
        out = svc.backup(args.out, mode=mode)
        print(json.dumps({"ok": True, "path": str(out)}, ensure_ascii=False))
    elif args.cmd == "restore":
        counts = svc.restore(args.src, args.db)
        print(json.dumps({"ok": True, "counts": counts}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(_main())
