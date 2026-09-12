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
import contextlib
import json
import logging
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, LiteralString, cast
from urllib.parse import quote

if TYPE_CHECKING:
    # Runtime import stays inside fetch() to avoid a circular import; this one
    # exists so the annotation resolves for type checking.
    from plugins.corpus.fetch import FetchedBlock

import psycopg
from psycopg.rows import DictRow, dict_row
from psycopg.types.json import Jsonb

from plugins.corpus.claims import (
    CLAIMS_COMMENTS,
    CLAIMS_MIGRATIONS_SQL,
    CLAIMS_SQL,
    DOC_KINDS,
    EXTRACTOR_VERSION,
    INJECTED_MODEL,
    BlockView,
    Claim,
    ExtractStats,
    apply_as_of_fallback,
    apply_doc_ticker,
    build_default_llm,
    classify_doc_kind,
    configured_model,
    document_ticker,
    extract_from_block,
    triage_blocks,
    with_retry,
)
from plugins.corpus.claims_v2 import (
    CLAIMS_V2_COMMENTS,
    CLAIMS_V2_SQL,
    EXTRACTOR_VERSION_V2,
    LINT_VERSION,
    ClaimRecord,
    ExtractionResult,
    claim_record_to_legacy,
    classify_doc_kind_detail,
    extract_from_block_v2,
    triage_blocks_detail,
)
from plugins.corpus.ingest import (
    CORPUS_ROOT,
    STATUS_EMPTY,
    STATUS_NEEDS_OCR,
    content_hash,
    iter_corpus_files,
    parse_document,
)
from plugins.corpus.metadata import (
    DOCUMENTS_MIGRATIONS_SQL,
    derive_metadata,
    derive_published,
)

logger = logging.getLogger(__name__)


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
    skipped_fresh: int = 0  # 因"刚被修改（可能还在拷贝）"而跳过
    needs_ocr: int = 0
    empty: int = 0
    failed: int = 0
    blocks: int = 0
    failures: list[tuple[str, str]] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.failures is None:
            self.failures = []

    def as_dict(self) -> dict[str, object]:
        # Annotated: the literal below would otherwise narrow to dict[str, int]
        # and the failures list would not fit.
        data: dict[str, object] = {
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


#: 语料库本机开发默认值。生产 / 容器环境请用 ``CORPUS_DSN``（完整连接串）覆盖，
#: 或用 ``CORPUS_DB_HOST/PORT/NAME/USER/PASSWORD`` 组件式覆盖。
DEFAULT_CORPUS_DB_HOST = "localhost"
DEFAULT_CORPUS_DB_PORT = "5432"
DEFAULT_CORPUS_DB_NAME = "postgres"
DEFAULT_CORPUS_DB_USER = "postgres"
DEFAULT_CORPUS_DB_PASSWORD = "postgres"


def dsn() -> str:
    """语料库连接串 —— 全部连接参数均来自配置，无散落硬编码。

    解析优先级（高 → 低）：

    1. ``CORPUS_DSN``：完整连接串，部署 / 容器环境推荐。
    2. ``CORPUS_DB_HOST`` / ``_PORT`` / ``_NAME`` / ``_USER`` / ``_PASSWORD``：
       组件式拼装，便于 Docker Compose 与本机 CLI 共用同一组变量。
    3. 本机开发默认值（WSL2 ``localhost`` 经转发可达 Windows Docker 发布的端口）。

    注意：语料库与平台业务库（``SERVER_DATABASE_URL``）是**同一实例上的不同
    database**（默认 ``postgres`` vs ``apodex``），host / port / 账号相同、仅库名
    不同，配置时勿混（见根 ``.env`` 与 ``.env.example`` 的注释）。
    """
    configured = os.environ.get("CORPUS_DSN", "").strip()
    if configured:
        return configured
    user = os.environ.get("CORPUS_DB_USER", DEFAULT_CORPUS_DB_USER)
    password = os.environ.get("CORPUS_DB_PASSWORD", DEFAULT_CORPUS_DB_PASSWORD)
    host = os.environ.get("CORPUS_DB_HOST", DEFAULT_CORPUS_DB_HOST)
    port = os.environ.get("CORPUS_DB_PORT", DEFAULT_CORPUS_DB_PORT)
    name = os.environ.get("CORPUS_DB_NAME", DEFAULT_CORPUS_DB_NAME)
    return f"postgresql://{quote(user, safe='')}:{quote(password, safe='')}@{host}:{port}/{name}"


def _dedup_claims(claims: list[Claim]) -> list[Claim]:
    """块内去重（§3.4）：同一 ``(metric, period, kind)`` 保留最后一条。

    LLM 偶尔在同一次输出里对同一指标重复给值（两次表述、两个精度）。"最后一条"
    与逐块提交的顺序一致 —— 后给的表述是对前者的修正。``metric`` 为空的行没有
    可比的坐标，不参与去重。
    """
    seen: set[tuple[str, str | None, str]] = set()
    kept: list[Claim] = []
    for claim in reversed(claims):
        if claim.metric is None:
            kept.append(claim)
            continue
        key = (claim.metric, claim.period, claim.kind)
        if key in seen:
            continue
        seen.add(key)
        kept.append(claim)
    kept.reverse()
    return kept


def _claim_record_from_row(row: dict[str, object]) -> ClaimRecord:
    """把 PG dict 行恢复成 ClaimRecord，供 v2 legacy adapter 使用。"""
    table_ref = row.get("table_ref")
    qualifiers = row.get("qualifiers")
    reason_codes = row.get("reason_codes")
    return ClaimRecord(
        doc_id=str(row["doc_id"]),
        source_rev=str(row["source_rev"]),
        seq=int(str(row["seq"])),
        locator=str(row["locator"]),
        claim_text=str(row["claim_text"]),
        evidence_quote=str(row["evidence_quote"]) if row.get("evidence_quote") else None,
        evidence_kind=str(row.get("evidence_kind") or "prose"),
        table_ref={str(k): str(v) for k, v in table_ref.items()}
        if isinstance(table_ref, dict)
        else {},
        scope=str(row.get("scope") or "company"),
        subject_raw=str(row["subject_raw"]) if row.get("subject_raw") else None,
        subject=str(row["subject"]) if row.get("subject") else None,
        metric_raw=str(row["metric_raw"]) if row.get("metric_raw") else None,
        metric=str(row["metric"]) if row.get("metric") else None,
        qualifiers={str(k): str(v) for k, v in qualifiers.items()}
        if isinstance(qualifiers, dict)
        else {},
        kind=str(row.get("kind") or "fact"),
        value_text=str(row["value_text"]) if row.get("value_text") else None,
        value_num=cast(Decimal | None, row.get("value_num")),
        unit_raw=str(row["unit_raw"]) if row.get("unit_raw") else None,
        unit=str(row["unit"]) if row.get("unit") else None,
        period_raw=str(row["period_raw"]) if row.get("period_raw") else None,
        period_end=str(row["period_end"]) if row.get("period_end") else None,
        period_grain=str(row["period_grain"]) if row.get("period_grain") else None,
        observed_at=str(row["observed_at"]) if row.get("observed_at") else None,
        known_at=str(row["known_at"]) if row.get("known_at") else None,
        quality_status=str(row.get("quality_status") or "review"),
        reason_codes=tuple(str(code) for code in reason_codes)
        if isinstance(reason_codes, list)
        else (),
        model=str(row["model"]) if row.get("model") else None,
        extractor_version=str(row.get("extractor_version") or EXTRACTOR_VERSION_V2),
        lint_version=str(row.get("lint_version") or LINT_VERSION),
        extracted_at=str(row["extracted_at"]) if row.get("extracted_at") else None,
    )


class CorpusService:
    """语料服务：所有 PG 访问经此。"""

    def __init__(self, dsn_url: str | None = None) -> None:
        self._dsn = dsn_url or dsn()
        self._lock = threading.Lock()

    # ── 连接 ──────────────────────────────────────────────────

    def _connect(self) -> psycopg.Connection[DictRow]:
        """Open a connection whose rows are dicts.

        The ``[DictRow]`` is what makes typed access work everywhere else:
        psycopg's ``connect`` infers its row type from the *return* context, so
        annotating this as a bare ``psycopg.Connection`` pins it to ``TupleRow``
        and every ``row["col"]`` downstream is then an error. One annotation
        here is the difference between ~70 type errors and none.
        """
        # ``connect`` cannot infer Row from ``row_factory`` (its return type is
        # effectively pinned to TupleRow), so the dict-row contract is asserted
        # here once instead of at every ``row["col"]`` downstream.
        return cast(
            "psycopg.Connection[DictRow]",
            psycopg.connect(
                self._dsn,
                # psycopg cannot infer Row from row_factory — its signature pins
                # the parameter to RowFactory[TupleRow] — so the dict-row
                # contract is asserted on the result instead of here.
                row_factory=dict_row,  # type: ignore[arg-type]
                connect_timeout=10,
            ),
        )

    def ensure_prerequisites(self) -> None:
        """确保扩展与中文检索配置存在 —— **恢复到全新库时必须先做这一步**。

        扩展（zhparser / pgvector / pg_trgm）与检索配置 ``zhcfg`` 都是**库级对象**，
        不会随 ``CREATE DATABASE`` 继承（除非来自 template）。灾备恢复到一个新库时，
        若不做这一步，``init_db`` 建生成列会因 ``zhcfg`` 不存在而失败。
        """
        with self._connect() as conn:
            for ext in ("zhparser", "vector", "pg_trgm"):
                try:
                    # Extension names are internal constants, not caller input.
                    # Kept as the original f-string: routing it through
                    # sql.Identifier() would quote the name and change the
                    # emitted DDL for no functional gain.
                    conn.execute(cast(LiteralString, f"CREATE EXTENSION IF NOT EXISTS {ext}"))
                except psycopg.Error as exc:
                    raise RuntimeError(
                        f"无法创建扩展 {ext}（通常需要超级用户权限）：{exc}"
                    ) from exc
            if not conn.execute("SELECT 1 FROM pg_ts_config WHERE cfgname = 'zhcfg'").fetchone():
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
            conn.execute(CLAIMS_SQL)  # D2：claim 抽取（幂等，不影响既有表）
            conn.execute(CLAIMS_V2_SQL)  # D2 v2：影子抽取表，不改变生产读取路径
            # 老库幂等迁移：三列事实列 + doc_kind_override + 删除 entities 死字段
            conn.execute(CLAIMS_MIGRATIONS_SQL)
            # P6（§3.5）：文档级元数据四列（doc_kind/subject/org/analysts）
            conn.execute(DOCUMENTS_MIGRATIONS_SQL)
            for stmt in (
                *_COLUMN_COMMENTS,
                *LEDGER_COMMENTS,
                *CLAIMS_COMMENTS,
                *CLAIMS_V2_COMMENTS,
            ):
                # COMMENT statements are module-level constants; the cast only
                # tells the type checker they are not caller-supplied SQL.
                conn.execute(cast(LiteralString, stmt))
            conn.commit()

    def set_doc_kind(self, doc_id: str, kind: str | None) -> None:
        """人工纠正文档领域分类（§11 缺口#1 的纠正入口）。

        ``doc_kind`` 决定抽取插槽与是否给文档级标的兜底，自动分类误判时
        （公司研报标题无代码且正文码为 0/多），坐标会整份文档全错 —— 这里是
        事后的手动纠偏。``None`` 清除覆盖、恢复自动分类。
        """
        if kind is not None and kind not in DOC_KINDS:
            raise ValueError(f"未知 doc_kind：{kind!r}（应为 {'/'.join(DOC_KINDS)} 或 None）")
        with self._lock, self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE documents SET doc_kind_override = %s WHERE doc_id = %s",
                (kind, str(doc_id)),
            )
            conn.commit()

    def refresh_metadata(self, doc_ids: Sequence[str] | None = None) -> dict[str, object]:
        """派生并物化文档级元数据（P6，§3.5 可得子集），返回统计摘要。

        ``doc_kind`` / ``subject`` / ``org`` / ``analysts`` 以派生为唯一权威，
        **非空即覆盖**（幂等）；``published`` 只回填 NULL（ingest 写入的 doc_id
        日期是事实，不覆盖）。纯规则派生，0 LLM 成本；抽取链路行为不变
        （抽取仍按 override → 现算分类取插槽，这里只是把同一判定落到列，
        供 D3/D4 直接 join，不再各自重算）。
        """
        with self._lock, self._connect() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT doc_id, title, published, doc_kind_override FROM documents"
                + (" WHERE doc_id = ANY(%s)" if doc_ids else "")
                + " ORDER BY doc_id",
                (list(doc_ids),) if doc_ids else None,
            )
            documents = cur.fetchall()
            stats = {
                "docs": len(documents),
                "org_filled": 0,
                "analysts_filled": 0,
                "subject_filled": 0,
                "published_backfilled": 0,
                "kind_dist": {},
            }
            kinds: dict[str, int] = {}
            for row in documents:
                doc_id, title = str(row["doc_id"]), str(row["title"] or "")
                texts = [str(b["text"] or "") for b in self._blocks_rows(conn, doc_id)]
                meta = derive_metadata(doc_id, title, texts, row["doc_kind_override"])
                kinds[str(meta["doc_kind"])] = kinds.get(str(meta["doc_kind"]), 0) + 1
                cur.execute(
                    "UPDATE documents SET doc_kind = %s, subject = %s, org = %s,"
                    " analysts = %s WHERE doc_id = %s",
                    (
                        meta["doc_kind"],
                        meta["subject"],
                        meta["org"],
                        list(meta["analysts"]) or None,
                        doc_id,
                    ),
                )
                # published：只回填 NULL（见 docstring），ingest 已填的不动
                if row["published"] is None and meta["published"] is not None:
                    cur.execute(
                        "UPDATE documents SET published = %s WHERE doc_id = %s",
                        (meta["published"], doc_id),
                    )
                    stats["published_backfilled"] += 1
                if meta["org"]:
                    stats["org_filled"] += 1
                if meta["analysts"]:
                    stats["analysts_filled"] += 1
                if meta["subject"]:
                    stats["subject_filled"] += 1
            stats["kind_dist"] = dict(sorted(kinds.items()))
            conn.commit()
        return stats

    def _blocks_rows(self, conn: psycopg.Connection[Any], doc_id: str) -> list[dict[str, Any]]:
        """一份文档的块文本（元数据派生用；与 blocks_of 同源但走 dict 行）。"""
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT seq, text FROM blocks WHERE doc_id = %s ORDER BY seq",
                (doc_id,),
            )
            return cur.fetchall()

    # ── 写入 ──────────────────────────────────────────────────

    def ingest_path(self, path: str | Path) -> tuple[str, bool]:
        """解析并落库一份，返回 ``(status, added)``。"""
        parsed = parse_document(path)
        first_text = parsed.blocks[0].text if parsed.blocks else None
        published = derive_published(parsed.doc_id, parsed.title, first_text)
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
        if inserted:
            # P6（§3.5）：元数据随 ingest 物化（org/analysts/doc_kind/subject +
            # published 的首块日期回填），新文档入即可被 D3/D4 join
            self.refresh_metadata([parsed.doc_id])
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
        added_doc_ids: list[str] = []

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

                first_text = parsed.blocks[0].text if parsed.blocks else None
                published = derive_published(parsed.doc_id, parsed.title, first_text)
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
                    added_doc_ids.append(parsed.doc_id)
                else:
                    stats.skipped_duplicate += 1

                if parsed.status == STATUS_NEEDS_OCR:
                    stats.needs_ocr += 1
                elif parsed.status == STATUS_EMPTY:
                    stats.empty += 1

            conn.commit()

        if added_doc_ids:
            # P6（§3.5）：本批新增文档的元数据随 ingest 物化（事务外批量补）
            refresh = self.refresh_metadata(added_doc_ids)
            logger.info(
                "元数据物化：%s 份（org=%s analysts=%s published 补=%s）",
                refresh["docs"],
                refresh["org_filled"],
                refresh["analysts_filled"],
                refresh["published_backfilled"],
            )

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
                self._SEARCH_SELECT.format(tsquery="plainto_tsquery('zhcfg', %(q)s)"),
                {"q": q, "limit": candidate_limit},
            )
            rows = cur.fetchall()
            if not rows:
                # AND 全空时退回 OR：宁可给几条带噪音的候选，
                # 也不要让调用方误判「资料里没有」——
                # 与 P0 的 FTS5 AND→OR 兜底一致。
                cur.execute("SELECT plainto_tsquery('zhcfg', %(q)s)::text AS tsv", {"q": q})
                row = cur.fetchone()
                and_text = row["tsv"] if row else ""
                or_ts = and_text.replace(" & ", " | ")
                if or_ts and or_ts.strip() not in ("''",):
                    cur.execute(
                        self._SEARCH_SELECT.format(tsquery="to_tsquery('zhcfg', %(or_ts)s)"),
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
        ranked = sorted(best_per_doc.values(), key=lambda r: r["score"] or 0.0, reverse=True)[
            :limit
        ]

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
                "SELECT doc_id, seq, locator, text FROM blocks WHERE doc_id = %s AND locator = %s",
                (str(doc_id), str(locator)),
            )
            r = cur.fetchone()
        if r is None:
            return None
        return FetchedBlock(doc_id=r["doc_id"], seq=r["seq"], locator=r["locator"], text=r["text"])

    def document_text(self, doc_id: str) -> str | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT string_agg(text, chr(10) ORDER BY seq) AS t FROM blocks WHERE doc_id = %s",
                (str(doc_id),),
            )
            row = cur.fetchone()
        return row["t"] if row and row["t"] else None

    def blocks_of(self, doc_id: str) -> list[DictRow]:
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
        should_stop: Callable[[], bool] | None = None,
        max_consecutive_failures: int = 5,
        max_attempts: int = 3,
    ) -> ExtractStats:
        """D2：**分级 → LLM 抽取 → 逐块落库**。

        ``llm`` 可注入（测试用假实现）；不给则用 :func:`build_default_llm`。
        ``retry_attempts`` 控制退避重试（实测供应商会 429 限流，重试即可成功）。
        ``sleep_between`` 块间限速（秒）：610 块连打会触发限流风暴，全量跑批建议 1s。
        ``should_stop`` 每次取块前问一次（Ctrl-C 的优雅退出钩子）。命中即停，
        但**不影响已经落库的块**。

        **落库粒度 = 块，而不是文档**（关键保证）：每块抽完立刻把「claims 行 +
        块级标记」在**同一个事务**里提交。理由是不可逆的 LLM 开销：若攒到文档
        末尾再写，一次限流 / Ctrl-C / kill 会让整份文档已花掉的钱全部蒸发（实测
        发生过）。逐块提交后，任何时刻被打断，已完成块都已落库；配合
        ``claim_block_runs`` 标记与 ``skip_existing``，重跑只补没做过的块。

        ``skip_existing`` 断点续跑的跳过判据是**同模型 + 同抽取器指纹**下的
        ``status='ok'`` 记录（含"抽出 0 条 claim"的块）。``failed`` 且未达
        ``max_attempts`` 的块**不跳过**，下次会重试；达上限的视为死信，跳过并
        计入 ``skipped_dead_letter``，避免某个必然失败的块反复白花钱。

        ``max_consecutive_failures``：连续失败这么多块就**干净退出**。额度耗尽 /
        被限流时，后续块注定全败 —— 继续跑只会把剩余额度全烧在重试上。熔断与
        中断都只停"往后跑"，已落库的块不受影响。

        纪律与 ingest 一致：**单块失败只记 failure，不中断整批**（直到熔断阈值）。
        """
        usage: dict[str, int] = {}
        model_name = configured_model()
        llm_fn = None
        if not dry_run:
            if llm is not None:
                llm_fn = llm
                # 注入实现没有"配置模型"的概念：用稳定标识，保证同一套假实现
                # 的重跑互相跳过，且不受环境里 OPENAI_MODEL 变化影响。
                model_name = INJECTED_MODEL
            else:
                llm_fn = build_default_llm(usage_sink=usage)
            if retry_attempts > 1:
                llm_fn = with_retry(llm_fn, attempts=retry_attempts)

        done: set[tuple[str, int]] = set()
        dead: set[tuple[str, int]] = set()
        if skip_existing:
            done, dead = self._done_blocks(model=model_name, max_attempts=max_attempts)
        stats = ExtractStats()

        documents = self.list_documents()
        # 标题 / 发布日 / doc_kind 覆盖用于：文档级标的兜底、as_of 兜底、插槽选择
        # （券商研报的代码常只出现在标题里；published 是 as_of 的兜底来源，§5.1）
        titles = {str(row["doc_id"]): str(row["title"] or "") for row in documents}
        published_by = {str(row["doc_id"]): row["published"] for row in documents}
        kind_overrides = {
            str(row["doc_id"]): row["doc_kind_override"]
            for row in documents
            if row.get("doc_kind_override")
        }
        targets = list(doc_ids) if doc_ids else [str(row["doc_id"]) for row in documents]
        stop = False
        consecutive_failures = 0
        for doc_id in targets:
            stats.documents += 1
            rows = self.blocks_of(doc_id)
            stats.blocks += len(rows)
            views = [
                BlockView(int(r["seq"]), str(r["locator"]), str(r["text"] or "")) for r in rows
            ]
            candidates, skipped = triage_blocks(views)
            stats.skipped_no_signal += skipped
            # 领域插槽选择（§3.1/§3.2）：人工覆盖优先（缺口#1），否则零成本规则分类
            override = kind_overrides.get(doc_id)
            if override in DOC_KINDS:
                doc_kind = str(override)
            else:
                doc_kind = classify_doc_kind(titles.get(doc_id, ""), [v.text for v in views])
            # 文档级标的：模型在表格块里常常抽不出代码（表格里没有代码列）。
            # **只给 company**（§3.1 副产品）：industry/macro 给错误的标的坐标
            # 比缺失更危险 —— 下游无法察觉。
            ticker = (
                document_ticker(titles.get(doc_id, ""), [view.text for view in views])
                if doc_kind == "company"
                else None
            )
            if ticker:
                logger.info("文档 %s（%s）的文档级标的兜底：%s", doc_id, doc_kind, ticker)

            for block in candidates:
                if limit is not None and stats.candidates >= limit:
                    # 只是本批到量就收，不算「被中断」：保持原有语义
                    # （继续扫后续文档，跟 limit 前一样不做任何事）。
                    break
                if should_stop is not None and should_stop():
                    # 中断信号：干净退出。已落库的块不受影响，重跑自动跳过。
                    stop = True
                    stats.stopped_early = True
                    stats.stopped_reason = "收到中断信号；已完成的块均已落库，重跑自动续上"
                    break
                if (doc_id, block.seq) in done:
                    stats.skipped_existing += 1
                    continue
                if (doc_id, block.seq) in dead:
                    stats.skipped_dead_letter += 1
                    continue
                stats.candidates += 1
                if dry_run:  # 错峰前只统计将抽取多少块，不调 LLM、不入库
                    continue
                started = time.monotonic()
                tokens_before = (
                    usage.get("prompt_tokens", 0),
                    usage.get("completion_tokens", 0),
                )
                try:
                    # dry_run already continued above, so an llm is always
                    # resolved by here; the assert narrows it for the checker.
                    assert llm_fn is not None
                    extracted = apply_as_of_fallback(
                        apply_doc_ticker(
                            extract_from_block(block, doc_id=doc_id, llm=llm_fn, doc_kind=doc_kind),
                            ticker,
                        ),
                        # as_of 兜底（§5.1）：模型没给时用发布日（≈0 token 成本）
                        str(published_by[doc_id]) if published_by.get(doc_id) else None,
                    )
                except Exception as exc:  # 单块失败不得拖垮整批
                    reason = f"{type(exc).__name__}: {exc}"[:200]
                    stats.failed += 1
                    consecutive_failures += 1
                    stats.failures.append(
                        {"doc_id": doc_id, "locator": block.locator, "reason": reason}
                    )
                    prompt_t, completion_t = self._usage_delta(tokens_before, usage)
                    stats.prompt_tokens += prompt_t
                    stats.completion_tokens += completion_t
                    # 失败也留痕（status=failed）：重跑时这些块会被重试，
                    # 而不是像以前那样只在内存里记一笔、进程一死就查无此事。
                    self._commit_block_result(
                        doc_id=doc_id,
                        seq=block.seq,
                        claims=[],
                        status="failed",
                        model=model_name,
                        error=reason,
                        duration_ms=int((time.monotonic() - started) * 1000),
                        prompt_tokens=prompt_t,
                        completion_tokens=completion_t,
                    )
                    if 0 < max_consecutive_failures <= consecutive_failures:
                        # 熔断：额度耗尽 / 被限流时后续块注定全败，
                        # 继续跑只会把剩下的额度烧在重试上。
                        stop = True
                        stats.stopped_early = True
                        stats.stopped_reason = (
                            f"连续 {consecutive_failures} 块失败（多为额度耗尽或限流），"
                            "已干净退出；已完成的块均已落库，重跑自动续上"
                        )
                        break
                else:
                    consecutive_failures = 0
                    prompt_t, completion_t = self._usage_delta(tokens_before, usage)
                    stats.prompt_tokens += prompt_t
                    stats.completion_tokens += completion_t
                    # ★ 一块一提交：此后即使限流 / 中断 / 被 kill，这块的钱也不白花。
                    stats.claims += self._commit_block_result(
                        doc_id=doc_id,
                        seq=block.seq,
                        claims=extracted,
                        status="ok",
                        model=model_name,
                        duration_ms=int((time.monotonic() - started) * 1000),
                        prompt_tokens=prompt_t,
                        completion_tokens=completion_t,
                    )
                if sleep_between > 0:
                    time.sleep(sleep_between)
            if stop:
                break

        return stats

    def extract_claims_v2(
        self,
        *,
        llm: Callable[[str], str] | None = None,
        doc_ids: list[str] | None = None,
        limit: int | None = None,
        retry_attempts: int = 3,
        sleep_between: float = 0.0,
        skip_existing: bool = True,
        dry_run: bool = False,
        should_stop: Callable[[], bool] | None = None,
        max_consecutive_failures: int = 5,
        max_attempts: int = 3,
    ) -> ExtractStats:
        """D2 Claims v2 影子抽取：不写 v1 ``claims``，不改变默认生产读取。

        与 v1 一样按块原子提交，但 v2 的块级状态更细：``empty``、``all_review``、
        ``all_rejected`` 与 ``failed`` 分开落账，review/rejected 记录也保存在影子表，
        默认查询只投影 ``quality_status='ok'``。
        """
        usage: dict[str, int] = {}
        model_name = configured_model()
        llm_fn = None
        if not dry_run:
            if llm is not None:
                llm_fn = llm
                model_name = INJECTED_MODEL
            else:
                llm_fn = build_default_llm(usage_sink=usage)
            if retry_attempts > 1:
                llm_fn = with_retry(llm_fn, attempts=retry_attempts)

        done: set[tuple[str, str, int]] = set()
        dead: set[tuple[str, str, int]] = set()
        if skip_existing:
            done, dead = self._done_blocks_v2(model=model_name, max_attempts=max_attempts)

        stats = ExtractStats()
        documents = self.list_documents()
        rows_by_doc = {str(row["doc_id"]): row for row in documents}
        targets = list(doc_ids) if doc_ids else [str(row["doc_id"]) for row in documents]
        stop = False
        consecutive_failures = 0
        for doc_id in targets:
            doc_row = rows_by_doc.get(doc_id, {})
            stats.documents += 1
            rows = self.blocks_of(doc_id)
            stats.blocks += len(rows)
            views = [
                BlockView(int(r["seq"]), str(r["locator"]), str(r["text"] or "")) for r in rows
            ]
            candidates, reason_counts = triage_blocks_detail(views)
            stats.skipped_no_signal += reason_counts.get("noise", 0) + reason_counts.get(
                "no_signal", 0
            )
            title = str(doc_row.get("title") or "")
            published = str(doc_row["published"]) if doc_row.get("published") else None
            source_rev = str(doc_row.get("content_hash") or "unknown")
            detail = classify_doc_kind_detail(
                title,
                tuple(v.text for v in views),
                str(doc_row["doc_kind_override"]) if doc_row.get("doc_kind_override") else None,
            )

            for block in candidates:
                if limit is not None and stats.candidates >= limit:
                    break
                if should_stop is not None and should_stop():
                    stop = True
                    stats.stopped_early = True
                    stats.stopped_reason = "收到中断信号；v2 已完成的块均已落库，重跑自动续上"
                    break
                key = (doc_id, source_rev, block.seq)
                if key in done:
                    stats.skipped_existing += 1
                    continue
                if key in dead:
                    stats.skipped_dead_letter += 1
                    continue
                stats.candidates += 1
                if dry_run:
                    continue

                started = time.monotonic()
                tokens_before = (
                    usage.get("prompt_tokens", 0),
                    usage.get("completion_tokens", 0),
                )
                try:
                    assert llm_fn is not None
                    result = extract_from_block_v2(
                        block,
                        doc_id=doc_id,
                        source_rev=source_rev,
                        llm=llm_fn,
                        doc_kind=detail.kind,
                        model=model_name,
                        known_at_fallback=published,
                    )
                except Exception as exc:
                    reason = f"{type(exc).__name__}: {exc}"[:200]
                    result = ExtractionResult(
                        diagnostics=[{"code": "llm_failed", "message": reason}],
                        model=model_name,
                        extractor_version=EXTRACTOR_VERSION_V2,
                    )
                    status = "failed"
                    stats.failures.append(
                        {"doc_id": doc_id, "locator": block.locator, "reason": reason}
                    )
                else:
                    status = result.block_status()
                    if status == "failed":
                        stats.failures.append(
                            {
                                "doc_id": doc_id,
                                "locator": block.locator,
                                "reason": str(result.diagnostics[:1]),
                            }
                        )

                prompt_t, completion_t = self._usage_delta(tokens_before, usage)
                stats.prompt_tokens += prompt_t
                stats.completion_tokens += completion_t
                stats.claims += len(result.accepted)
                stats.review += len(result.review)
                stats.rejected += len(result.rejected)
                stats.truncated += 1 if result.truncated else 0
                self._commit_block_result_v2(
                    doc_id=doc_id,
                    source_rev=source_rev,
                    seq=block.seq,
                    result=result,
                    status=status,
                    model=model_name,
                    error="; ".join(
                        str(d.get("message") or d.get("code")) for d in result.diagnostics
                    )
                    or None,
                    duration_ms=int((time.monotonic() - started) * 1000),
                    prompt_tokens=prompt_t,
                    completion_tokens=completion_t,
                )
                if status == "failed":
                    stats.failed += 1
                    consecutive_failures += 1
                    if 0 < max_consecutive_failures <= consecutive_failures:
                        stop = True
                        stats.stopped_early = True
                        stats.stopped_reason = (
                            f"连续 {consecutive_failures} 块失败（v2），已干净退出；"
                            "已完成的块均已落库，重跑自动续上"
                        )
                        break
                else:
                    consecutive_failures = 0
                if sleep_between > 0:
                    time.sleep(sleep_between)
            if stop:
                break

        return stats

    @staticmethod
    def _usage_delta(before: tuple[int, int], sink: dict[str, int]) -> tuple[int, int]:
        """取一块的 token 增量（含该块的全部重试尝试）。"""
        return (
            sink.get("prompt_tokens", 0) - before[0],
            sink.get("completion_tokens", 0) - before[1],
        )

    def _done_blocks(
        self, *, model: str, max_attempts: int
    ) -> tuple[set[tuple[str, int]], set[tuple[str, int]]]:
        """返回 ``(已完成的块, 死信块)`` —— 断点续跑的跳过判据。

        **已完成** = 同一 ``model`` + 同一 ``extractor_version`` 下 ``status='ok'``
        的块。指纹不能省：块一旦记为 ok 就永不重抽，而"抽得好不好"完全取决于模型
        与 prompt；不认指纹的话，换模型（GLM-4.7 → AirX）或改 prompt 之后旧块会被
        **静默永久跳过** —— 看起来在跑，实际一条都不抽，且不报错。

        **死信** = 同一指纹下 ``status='failed'`` 且 ``attempts`` 已达
        ``max_attempts`` 的块。这类块多因内容本身必然失败（超长 JSON、内容过滤），
        没有上限的话每次重跑都会再失败一次、**每次都白花一次钱**。
        换模型/换 prompt 后 ``attempts`` 归零（见 :meth:`_commit_block_result`），
        所以换指纹后死信会被重新尝试。

        **不再**拿 ``claims`` 表反推"做过没有"：那条路既漏掉"抽出 0 条 claim"的块
        （每次重跑都要再烧一次钱），又没有模型信息，会让换模型静默失效。
        """
        with self._connect() as conn:
            done = {
                (str(row["doc_id"]), int(row["seq"]))
                for row in conn.execute(
                    "SELECT doc_id, seq FROM claim_block_runs "
                    "WHERE status = 'ok' AND model = %s AND extractor_version = %s",
                    (model, EXTRACTOR_VERSION),
                ).fetchall()
            }
            dead = {
                (str(row["doc_id"]), int(row["seq"]))
                for row in conn.execute(
                    "SELECT doc_id, seq FROM claim_block_runs "
                    "WHERE status = 'failed' AND attempts >= %s "
                    "AND model = %s AND extractor_version = %s",
                    (int(max_attempts), model, EXTRACTOR_VERSION),
                ).fetchall()
            }
        return done, dead

    def _done_blocks_v2(
        self, *, model: str, max_attempts: int
    ) -> tuple[set[tuple[str, str, int]], set[tuple[str, str, int]]]:
        """v2 断点续跑集合，source_rev/extractor/lint 任一变化都会重抽。"""
        with self._connect() as conn:
            done = {
                (str(row["doc_id"]), str(row["source_rev"]), int(row["seq"]))
                for row in conn.execute(
                    "SELECT doc_id, source_rev, seq FROM claim_block_runs_v2 "
                    "WHERE status IN ('ok', 'empty', 'all_review', 'all_rejected') "
                    "AND model = %s AND extractor_version = %s AND lint_version = %s",
                    (model, EXTRACTOR_VERSION_V2, LINT_VERSION),
                ).fetchall()
            }
            dead = {
                (str(row["doc_id"]), str(row["source_rev"]), int(row["seq"]))
                for row in conn.execute(
                    "SELECT doc_id, source_rev, seq FROM claim_block_runs_v2 "
                    "WHERE status = 'failed' AND attempts >= %s "
                    "AND model = %s AND extractor_version = %s AND lint_version = %s",
                    (int(max_attempts), model, EXTRACTOR_VERSION_V2, LINT_VERSION),
                ).fetchall()
            }
        return done, dead

    def _commit_block_result(
        self,
        *,
        doc_id: str,
        seq: int,
        claims: list,
        status: str,
        model: str,
        error: str | None = None,
        duration_ms: int | None = None,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
    ) -> int:
        """**原子**写入一块的抽取结果：claims 行 + 块级标记，同一事务提交。

        这是「钱花了必落库」的落点：只写 claims 不写标记，抽出 0 条的块下次仍被
        重抽；只写标记不写 claims，中断时数据本身就丢了 —— 两者必须同生共死，
        所以合进一个事务。

        **换指纹即整块替换**：这块上次若是用别的模型 / 别的 prompt 版本抽的，先把
        该块旧 claims 删掉再插新的。否则一张表里会混着两代模型的结果 ——
        ``ON CONFLICT`` 只挡完全相同的文本，挡不住同一个数字被两种口径表述。
        仅在 ``status='ok'`` 时替换；失败时不动既有数据。

        ``attempts`` 只统计**当前指纹**下的次数：指纹变了就归 1，否则"换个模型
        重试"会被上一个模型累计的失败次数直接判成死信。

        **跨块去重（§3.4 缺陷 4）**：同一 ``(doc_id, metric, period, kind)`` 在
        多个块重复出现（如 毛利率 2026E 文字块 90.4% / 表格块 90.42%，文本不同
        ``ON CONFLICT`` 挡不住），按标的聚合时会被**重复计数**。口径：序号更大
        （更靠后）的块覆盖之前的 —— 与逐块提交顺序一致，只删 ``seq < 当前块`` 的
        旧行，重抽靠前的块永远不会碰掉靠后块已落库的结果。``metric`` 为空的行
        没有可比坐标，不参与。块内重复由 :func:`_dedup_claims` 先收一次。

        返回本次实际插入的 claim 行数（``ON CONFLICT DO NOTHING`` 后的净增，
        重跑同一块时为 0，不会重复计数）。
        """
        claims = _dedup_claims(list(claims))
        rows = [
            (
                str(c.doc_id),
                int(c.seq),
                str(c.locator),
                str(c.claim_text),
                str(c.kind),
                list(c.tickers),
                c.metric,
                c.value_text,
                c.value_num,
                c.unit,
                c.period,
                c.as_of,
                c.confidence,
            )
            for c in claims
        ]
        with self._lock, self._connect() as conn:
            with conn.cursor() as cur:
                inserted = 0
                if status == "ok":
                    cur.execute(
                        "SELECT model, extractor_version FROM claim_block_runs "
                        "WHERE doc_id = %s AND seq = %s",
                        (str(doc_id), int(seq)),
                    )
                    previous = cur.fetchone()
                    if previous is not None and (
                        str(previous["model"]) != model
                        or str(previous["extractor_version"]) != EXTRACTOR_VERSION
                    ):
                        cur.execute(
                            "DELETE FROM claims WHERE doc_id = %s AND seq = %s",
                            (str(doc_id), int(seq)),
                        )
                if rows:
                    # 跨块去重（§3.4 缺陷 4）：删掉更靠前块里同坐标的旧行。
                    # IS NOT DISTINCT FROM 让 NULL period 也参与比较（目标价这类
                    # 不带期间的指标在多个块重复时同样只留一条）。
                    # 排序键把 None 归到 ""：同块内 period 混有 NULL 与字符串时
                    # （表格块常见），tuple 直接比较会 TypeError。
                    triples = sorted(
                        {(c.metric, c.period, c.kind) for c in claims if c.metric is not None},
                        key=lambda t: (t[0], t[1] or "", t[2]),
                    )
                    for metric, period, kind in triples:
                        cur.execute(
                            "DELETE FROM claims WHERE doc_id = %s AND seq < %s "
                            "AND metric IS NOT DISTINCT FROM %s "
                            "AND period IS NOT DISTINCT FROM %s AND kind = %s",
                            (str(doc_id), int(seq), metric, period, kind),
                        )
                    cur.executemany(
                        "INSERT INTO claims (doc_id, seq, locator, claim_text, kind, tickers, "
                        "metric, value_text, value_num, unit, period, as_of, confidence) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                        "ON CONFLICT (doc_id, seq, claim_text) DO NOTHING",
                        rows,
                    )
                    inserted = cur.rowcount
                cur.execute(
                    "INSERT INTO claim_block_runs "
                    "(doc_id, seq, status, claims_n, attempts, model, extractor_version, "
                    " duration_ms, prompt_tokens, completion_tokens, error, updated_at) "
                    "VALUES (%s,%s,%s,%s,1,%s,%s,%s,%s,%s,%s,now()) "
                    "ON CONFLICT (doc_id, seq) DO UPDATE SET "
                    "status = EXCLUDED.status, "
                    "claims_n = EXCLUDED.claims_n, "
                    "attempts = CASE "
                    "  WHEN claim_block_runs.model IS DISTINCT FROM EXCLUDED.model "
                    "    OR claim_block_runs.extractor_version "
                    "       IS DISTINCT FROM EXCLUDED.extractor_version "
                    "  THEN 1 ELSE claim_block_runs.attempts + 1 END, "
                    "model = EXCLUDED.model, "
                    "extractor_version = EXCLUDED.extractor_version, "
                    "duration_ms = EXCLUDED.duration_ms, "
                    "prompt_tokens = EXCLUDED.prompt_tokens, "
                    "completion_tokens = EXCLUDED.completion_tokens, "
                    "error = EXCLUDED.error, "
                    "updated_at = now()",
                    (
                        str(doc_id),
                        int(seq),
                        str(status),
                        len(claims),
                        model,
                        EXTRACTOR_VERSION,
                        duration_ms,
                        prompt_tokens,
                        completion_tokens,
                        error,
                    ),
                )
            conn.commit()
        return max(inserted, 0)

    def _commit_block_result_v2(
        self,
        *,
        doc_id: str,
        source_rev: str,
        seq: int,
        result: ExtractionResult,
        status: str,
        model: str,
        error: str | None = None,
        duration_ms: int | None = None,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
    ) -> None:
        """原子写入 v2 单块结果：三类 claim + 块级台账同事务。"""
        records = result.all_records()
        rows = [
            (
                r.doc_id,
                r.source_rev,
                r.seq,
                r.locator,
                r.claim_text,
                r.evidence_quote,
                r.evidence_kind,
                Jsonb(r.table_ref),
                r.scope,
                r.subject_raw,
                r.subject,
                r.metric_raw,
                r.metric,
                Jsonb(r.qualifiers),
                r.kind,
                r.value_text,
                r.value_num,
                r.unit_raw,
                r.unit,
                r.period_raw,
                r.period_end,
                r.period_grain,
                r.observed_at,
                r.known_at,
                r.quality_status,
                list(r.reason_codes),
                r.model,
                r.extractor_version,
                r.lint_version,
                r.extracted_at,
            )
            for r in records
        ]
        with self._lock, self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT model, extractor_version, lint_version FROM claim_block_runs_v2 "
                    "WHERE doc_id = %s AND source_rev = %s AND seq = %s",
                    (str(doc_id), str(source_rev), int(seq)),
                )
                previous = cur.fetchone()
                previous_fingerprint_differs = previous is not None and (
                    str(previous["model"]) != model
                    or str(previous["extractor_version"]) != EXTRACTOR_VERSION_V2
                    or str(previous["lint_version"]) != LINT_VERSION
                )
                if status != "failed" or previous_fingerprint_differs:
                    cur.execute(
                        "DELETE FROM claims_v2 WHERE doc_id = %s AND source_rev = %s AND seq = %s",
                        (str(doc_id), str(source_rev), int(seq)),
                    )
                if rows:
                    cur.executemany(
                        "INSERT INTO claims_v2 ("
                        "doc_id, source_rev, seq, locator, claim_text, evidence_quote, "
                        "evidence_kind, table_ref, scope, subject_raw, subject, metric_raw, "
                        "metric, qualifiers, kind, value_text, value_num, unit_raw, unit, "
                        "period_raw, period_end, period_grain, observed_at, known_at, "
                        "quality_status, reason_codes, model, extractor_version, "
                        "lint_version, extracted_at) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,"
                        "%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                        "ON CONFLICT DO NOTHING",
                        rows,
                    )
                cur.execute(
                    "INSERT INTO claim_block_runs_v2 "
                    "(doc_id, source_rev, seq, status, accepted_n, review_n, rejected_n, "
                    " attempts, model, extractor_version, lint_version, duration_ms, "
                    " prompt_tokens, completion_tokens, truncated, diagnostics, error, updated_at) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,1,%s,%s,%s,%s,%s,%s,%s,%s,%s,now()) "
                    "ON CONFLICT (doc_id, source_rev, seq) DO UPDATE SET "
                    "status = EXCLUDED.status, "
                    "accepted_n = EXCLUDED.accepted_n, "
                    "review_n = EXCLUDED.review_n, "
                    "rejected_n = EXCLUDED.rejected_n, "
                    "attempts = CASE "
                    "  WHEN claim_block_runs_v2.model IS DISTINCT FROM EXCLUDED.model "
                    "    OR claim_block_runs_v2.extractor_version "
                    "       IS DISTINCT FROM EXCLUDED.extractor_version "
                    "    OR claim_block_runs_v2.lint_version "
                    "       IS DISTINCT FROM EXCLUDED.lint_version "
                    "  THEN 1 ELSE claim_block_runs_v2.attempts + 1 END, "
                    "model = EXCLUDED.model, "
                    "extractor_version = EXCLUDED.extractor_version, "
                    "lint_version = EXCLUDED.lint_version, "
                    "duration_ms = EXCLUDED.duration_ms, "
                    "prompt_tokens = EXCLUDED.prompt_tokens, "
                    "completion_tokens = EXCLUDED.completion_tokens, "
                    "truncated = EXCLUDED.truncated, "
                    "diagnostics = EXCLUDED.diagnostics, "
                    "error = EXCLUDED.error, "
                    "updated_at = now()",
                    (
                        str(doc_id),
                        str(source_rev),
                        int(seq),
                        str(status),
                        len(result.accepted),
                        len(result.review),
                        len(result.rejected),
                        model,
                        EXTRACTOR_VERSION_V2,
                        LINT_VERSION,
                        duration_ms,
                        prompt_tokens,
                        completion_tokens,
                        result.truncated,
                        Jsonb(result.diagnostics),
                        error,
                    ),
                )
            conn.commit()

    def average_block_seconds(self, *, default: float = 45.0) -> float:
        """历史平均单块耗时（秒）—— 排期估算用真实数据，而不是拍脑袋的常数。

        旧版 ``--dry-run`` 用"每次调用 ~2s"估算，把 614 块算成 30.8 分钟；实测
        中位数约 51s（20~177s），真实耗时约 9 小时 —— 低估 17 倍。台账里的
        ``duration_ms`` 一上线就有真实样本，没有样本时才退化为 ``default``。
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT avg(duration_ms) AS avg_ms, count(*) AS n FROM claim_block_runs "
                "WHERE status = 'ok' AND duration_ms IS NOT NULL"
            ).fetchone()
        if row and row["n"] and row["avg_ms"]:
            return max(1.0, float(row["avg_ms"]) / 1000.0)
        return default

    def block_runs(
        self,
        *,
        doc_id: str | None = None,
        status: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, object]]:
        """查询块级台账 —— D2 进度、失败原因与花费的可见性入口。

        跳过只认"同模型 + 同抽取器指纹"的 ``ok`` 记录，所以排查"为什么某块没被重抽"
        或"还有多少没抽"时，看这张表而不是 ``claims``。
        """
        sql = (
            "SELECT doc_id, seq, status, claims_n, attempts, model, extractor_version, "
            "duration_ms, prompt_tokens, completion_tokens, error, updated_at "
            "FROM claim_block_runs"
        )
        where: list[str] = []
        params: list[object] = []
        if doc_id:
            where.append("doc_id = %s")
            params.append(str(doc_id))
        if status:
            where.append("status = %s")
            params.append(str(status))
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY doc_id, seq LIMIT %s"
        params.append(int(limit))

        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(cast(LiteralString, sql), params)
            return list(cur.fetchall())

    def block_runs_v2(
        self,
        *,
        doc_id: str | None = None,
        status: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, object]]:
        """查询 v2 块级台账。"""
        sql = (
            "SELECT doc_id, source_rev, seq, status, accepted_n, review_n, rejected_n, "
            "attempts, model, extractor_version, lint_version, duration_ms, prompt_tokens, "
            "completion_tokens, truncated, diagnostics, error, updated_at "
            "FROM claim_block_runs_v2"
        )
        where: list[str] = []
        params: list[object] = []
        if doc_id:
            where.append("doc_id = %s")
            params.append(str(doc_id))
        if status:
            where.append("status = %s")
            params.append(str(status))
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY doc_id, source_rev, seq LIMIT %s"
        params.append(int(limit))

        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(cast(LiteralString, sql), params)
            return list(cur.fetchall())

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
            "metric, value_text, value_num, unit, period, as_of, confidence FROM claims"
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
            # Built from fixed fragments with %s placeholders and bound params —
            # the cast documents that no caller text reaches the SQL itself.
            cur.execute(cast(LiteralString, sql), params)
            return list(cur.fetchall())

    def claims_v2_of(
        self,
        *,
        doc_id: str | None = None,
        subject: str | None = None,
        kind: str | None = None,
        quality_status: str | None = "ok",
        limit: int = 50,
    ) -> list[dict[str, object]]:
        """查询 v2 claims；默认只暴露 ok，review/rejected 需显式传 ``None`` 或状态。"""
        sql = (
            "SELECT claim_id, doc_id, source_rev, seq, locator, claim_text, "
            "evidence_quote, evidence_kind, table_ref, scope, subject_raw, subject, "
            "metric_raw, metric, qualifiers, kind, value_text, value_num, unit_raw, unit, "
            "period_raw, period_end, period_grain, observed_at, known_at, quality_status, "
            "reason_codes, model, extractor_version, lint_version, extracted_at "
            "FROM claims_v2"
        )
        where: list[str] = []
        params: list[object] = []
        if doc_id:
            where.append("doc_id = %s")
            params.append(str(doc_id))
        if subject:
            where.append("subject = %s")
            params.append(str(subject))
        if kind:
            where.append("kind = %s")
            params.append(str(kind))
        if quality_status:
            where.append("quality_status = %s")
            params.append(str(quality_status))
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY doc_id, source_rev, seq, claim_id LIMIT %s"
        params.append(int(limit))

        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(cast(LiteralString, sql), params)
            return list(cur.fetchall())

    def claim_observation_projection(
        self,
        *,
        doc_id: str | None = None,
        subject: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, object]]:
        """Claims v2 给后续判断层的只读投影；默认排除 review/rejected。"""
        rows = self.claims_v2_of(doc_id=doc_id, subject=subject, quality_status="ok", limit=limit)
        return [
            {
                "doc_id": row["doc_id"],
                "source_rev": row["source_rev"],
                "seq": row["seq"],
                "locator": row["locator"],
                "evidence_quote": row["evidence_quote"],
                "scope": row["scope"],
                "subject": row["subject"],
                "metric": row["metric"],
                "qualifiers": row["qualifiers"],
                "kind": row["kind"],
                "value_text": row["value_text"],
                "value_num": row["value_num"],
                "unit": row["unit"],
                "period_end": row["period_end"],
                "known_at": row["known_at"],
                "quality_status": row["quality_status"],
            }
            for row in rows
        ]

    def legacy_claims_from_v2(
        self,
        *,
        doc_id: str | None = None,
        subject: str | None = None,
        limit: int = 50,
    ) -> list[Claim]:
        """v2 → v1 兼容 Adapter；仅转换 ok 记录。"""
        records = [
            _claim_record_from_row(row)
            for row in self.claims_v2_of(
                doc_id=doc_id,
                subject=subject,
                quality_status="ok",
                limit=limit,
            )
        ]
        return [claim_record_to_legacy(record) for record in records]

    def claim_version_diff(
        self,
        *,
        doc_id: str | None = None,
        limit: int = 1000,
    ) -> dict[str, object]:
        """v1/v2 影子差异摘要：新增、删除、证据/坐标/数值/时间/状态变化。"""
        v1 = self.claims_of(doc_id=doc_id, limit=limit)
        v2 = self.claims_v2_of(doc_id=doc_id, quality_status=None, limit=limit)
        v1_by_text = {str(row["claim_text"]): row for row in v1}
        v2_by_text = {str(row["claim_text"]): row for row in v2}
        added = sorted(set(v2_by_text) - set(v1_by_text))
        removed = sorted(set(v1_by_text) - set(v2_by_text))
        common = sorted(set(v1_by_text) & set(v2_by_text))

        def examples(names: list[str]) -> list[str]:
            return names[:20]

        def tickers_of(value: object) -> tuple[object, ...]:
            return tuple(value) if isinstance(value, (list, tuple)) else ()

        coordinate_changes = [
            text
            for text in common
            if (
                v1_by_text[text].get("metric"),
                tickers_of(v1_by_text[text].get("tickers")),
            )
            != (
                v2_by_text[text].get("metric"),
                (v2_by_text[text].get("subject"),)
                if v2_by_text[text].get("scope") == "company" and v2_by_text[text].get("subject")
                else (),
            )
        ]
        value_changes = [
            text
            for text in common
            if (
                v1_by_text[text].get("value_text"),
                str(v1_by_text[text].get("value_num")),
            )
            != (
                v2_by_text[text].get("value_text"),
                str(v2_by_text[text].get("value_num")),
            )
        ]
        time_changes = [
            text
            for text in common
            if str(v1_by_text[text].get("as_of")) != str(v2_by_text[text].get("known_at"))
        ]
        status_changes = [text for text in common if v2_by_text[text].get("quality_status") != "ok"]
        evidence_changes = [
            text for text in common if v2_by_text[text].get("evidence_quote") not in (None, text)
        ]
        return {
            "v1_total": len(v1),
            "v2_total": len(v2),
            "added": {"count": len(added), "examples": examples(added)},
            "removed": {"count": len(removed), "examples": examples(removed)},
            "evidence_changes": {
                "count": len(evidence_changes),
                "examples": examples(evidence_changes),
            },
            "coordinate_changes": {
                "count": len(coordinate_changes),
                "examples": examples(coordinate_changes),
            },
            "value_changes": {"count": len(value_changes), "examples": examples(value_changes)},
            "time_changes": {"count": len(time_changes), "examples": examples(time_changes)},
            "status_changes": {"count": len(status_changes), "examples": examples(status_changes)},
        }

    def list_documents(self) -> list[dict[str, object]]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT doc_id, title, source_path, content_hash, mime, status, "
                "block_count, char_count, published, doc_kind_override "
                "FROM documents ORDER BY doc_id"
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
    #
    # ⚠️ 该列表是**逐列枚举**的：``claims`` 加了新列而忘了同步这里，不会被报错，
    # 只会在备份里**静默丢字段**（上次整张 claims 表漏出备份就是这样踩的，
    # 见 d2-claims-design §5.1 / 附录 A）。
    #
    # 抽取产物（claims）与块级台账（claim_block_runs）**必须一起备份**：
    # 台账是断点续跑的跳过标记，丢了它的后果不是"少几行"，而是恢复后所有块
    # 都被判定为"没做过" —— 已经花过的钱要再花一遍。
    _BACKUP_COLUMNS: ClassVar[dict[str, tuple[str, ...]]] = {
        "documents": (
            "doc_id",
            "title",
            "source_path",
            "content_hash",
            "mime",
            "status",
            "char_count",
            "block_count",
            "ingested_at",
            "published",
            # P1 迁移加列（§5.1 ⚠️）：不同步这行，备份会静默丢 doc_kind_override，
            # 恢复后人工纠正过的分类全部归零 —— 审计（P5）的备份覆盖率检查抓的正是它。
            "doc_kind_override",
            # P6 迁移加列（§3.5 可得子集）：同一教训，加列必须同步备份枚举
            "doc_kind",
            "subject",
            "org",
            "analysts",
        ),
        "blocks": ("doc_id", "seq", "locator", "text"),
        "claims": (
            "claim_id",
            "doc_id",
            "seq",
            "locator",
            "claim_text",
            "kind",
            "tickers",
            "metric",
            "value_text",
            "value_num",
            "unit",
            "period",
            "as_of",
            "confidence",
            "extracted_at",
        ),
        "claim_block_runs": (
            "doc_id",
            "seq",
            "status",
            "claims_n",
            "attempts",
            "model",
            "extractor_version",
            "duration_ms",
            "prompt_tokens",
            "completion_tokens",
            "error",
            "updated_at",
        ),
        "claims_v2": (
            "claim_id",
            "doc_id",
            "source_rev",
            "seq",
            "locator",
            "claim_text",
            "evidence_quote",
            "evidence_kind",
            "table_ref",
            "scope",
            "subject_raw",
            "subject",
            "metric_raw",
            "metric",
            "qualifiers",
            "kind",
            "value_text",
            "value_num",
            "unit_raw",
            "unit",
            "period_raw",
            "period_end",
            "period_grain",
            "observed_at",
            "known_at",
            "quality_status",
            "reason_codes",
            "model",
            "extractor_version",
            "lint_version",
            "extracted_at",
        ),
        "claim_block_runs_v2": (
            "doc_id",
            "source_rev",
            "seq",
            "status",
            "accepted_n",
            "review_n",
            "rejected_n",
            "attempts",
            "model",
            "extractor_version",
            "lint_version",
            "duration_ms",
            "prompt_tokens",
            "completion_tokens",
            "truncated",
            "diagnostics",
            "error",
            "updated_at",
        ),
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
            [
                "pg_dump",
                "--format=custom",
                "--no-owner",
                "--no-acl",
                "--file",
                str(path),
                self._dsn,
            ],
            capture_output=True,
            text=True,
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
                    # Table/column names come from _BACKUP_COLUMNS, not a caller.
                    statement = cast(
                        LiteralString,
                        f"COPY {table} ({columns_sql}) TO STDOUT WITH (FORMAT CSV, HEADER)",
                    )
                    with cur.copy(statement) as copy:
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
            counts: dict[str, int] = {}
            for table in self._BACKUP_COLUMNS:
                # Table names come from _BACKUP_COLUMNS, never from a caller.
                query = cast(LiteralString, f"SELECT count(*) AS n FROM {table}")
                row = conn.execute(query).fetchone()
                counts[table] = int(row["n"]) if row else 0
            return counts

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
            [
                tool,
                "--no-owner",
                "--no-acl",
                "--dbname",
                target_dsn,
                "--clean",
                "--if-exists",
                str(dump),
            ],
            capture_output=True,
            text=True,
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
            # 恢复 = **覆盖**，不是追加。CSV 路径原本直接 COPY，往非空表灌会撞
            # 主键 / UNIQUE；先整体清空，与 pg_dump 路径的 --clean 语义对齐。
            table_names = ", ".join(self._BACKUP_COLUMNS)
            conn.execute(cast(LiteralString, f"TRUNCATE {table_names} CASCADE"))
            for table, columns in self._BACKUP_COLUMNS.items():
                csv_path = src / f"{table}.csv"
                if not csv_path.exists():
                    # 旧备份可能缺表（claims 曾被漏掉过）：跳过并告警，而不是
                    # 让整次恢复失败。
                    logger.warning("备份里缺少 %s.csv，跳过该表", table)
                    continue
                # 列取**当前 schema 与备份文件表头的交集**：旧备份没有后加的列
                # （如 claims 的 value_num/unit/as_of），直接按当前列 COPY 会报
                # "column does not exist in file"；旧备份里已删除的列（entities）
                # 也不能再写。缺的列恢复后为 NULL / 默认值，可重跑补齐。
                header_line = csv_path.open("r", encoding="utf-8").readline()
                header = {name.strip() for name in header_line.strip().split(",")}
                present = [c for c in columns if c in header]
                dropped = [c for c in columns if c not in header]
                if dropped:
                    logger.warning("备份 %s.csv 缺少列 %s，恢复后该列为空", table, dropped)
                columns_sql = ", ".join(present)
                statement = cast(
                    LiteralString,
                    f"COPY {table} ({columns_sql}) FROM STDIN WITH (FORMAT CSV, HEADER)",
                )
                with conn.cursor() as cur, cur.copy(statement) as copy:
                    copy.write(csv_path.read_bytes())
            # claims.claim_id 是显式写回的，序列不会自动跟进；不同步的话下次
            # nextval 会直接撞主键。
            conn.execute(
                "SELECT setval('claims_claim_id_seq', "
                "COALESCE((SELECT max(claim_id) FROM claims), 0) + 1, false)"
            )
            conn.execute(
                "SELECT setval('claims_v2_claim_id_seq', "
                "COALESCE((SELECT max(claim_id) FROM claims_v2), 0) + 1, false)"
            )
            conn.commit()

        counts = target._row_counts()
        # 只比对备份 manifest 里声明过的表：旧 manifest 不含后加的表（claims /
        # claim_block_runs），按全量比对会误报不一致。
        mismatch = {
            table: (counts.get(table), want)
            for table, want in expected.items()
            if counts.get(table) != want
        }
        if mismatch:
            raise RuntimeError(f"恢复后行数与备份不一致：{mismatch}")
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
            row = cur.fetchone()
            total = int(row["n"]) if row else 0
            cur.execute("SELECT COUNT(*) AS n FROM blocks")
            row = cur.fetchone()
            blocks = int(row["n"]) if row else 0
            cur.execute("SELECT status, COUNT(*) AS n FROM documents GROUP BY status")
            by_status = {r["status"]: r["n"] for r in cur.fetchall()}
            cur.execute("SELECT mime, COUNT(*) AS n FROM documents GROUP BY mime")
            by_mime = {r["mime"]: r["n"] for r in cur.fetchall()}
            cur.execute("SELECT MIN(published) AS lo, MAX(published) AS hi FROM documents")
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
                "total": 0,
                "added": 0,
                "skipped_duplicate": 0,
                "skipped_unchanged": 0,
                "skipped_fresh": 0,
                "needs_ocr": 0,
                "empty": 0,
                "failed": 0,
                "failures": [],
                "duration_ms": int((time.monotonic() - started) * 1000),
                "exit_code": 2,
            }
            # 数据库可能就是挂的那个 —— 这时更要留下痕迹，所以写磁盘镜像
            self._ledger_json(record)
            return record

    def _ingest_inner(self, root: str | Path, *, trigger: str, min_age: float) -> dict[str, object]:
        self.init_db()
        with self._connect() as lock_conn:
            got = lock_conn.execute(
                "SELECT pg_try_advisory_lock(%s) AS got", (_INGEST_LOCK_KEY,)
            ).fetchone()
            if not got or not got["got"]:
                msg = "已有跑批在运行（未取得 advisory lock），本次跳过"
                logger.warning(msg)
                return {
                    "run_id": None,
                    "status": "error",
                    "error": msg,
                    "exit_code": 2,
                }
            try:
                return self._ingest_locked(root, trigger=trigger, min_age=min_age)
            finally:
                lock_conn.execute("SELECT pg_advisory_unlock(%s)", (_INGEST_LOCK_KEY,))
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
                run_id,
                None,
                "error",
                error=str(exc),
                duration_ms=int((time.monotonic() - started) * 1000),
            )
            return {**record, "exit_code": 2}

        # 空文档 / 需 OCR 不算"失败"，但必须让人看见 —— 否则报告静默搜不到
        problems = stats.failed + stats.empty + stats.needs_ocr
        status = "ok" if problems == 0 else "warn"
        record = self._ledger_finish(
            run_id,
            stats,
            status,
            duration_ms=int((time.monotonic() - started) * 1000),
        )
        exit_code = 0 if status == "ok" else 1
        logger.info(
            "跑批结束：status=%s added=%s failed=%s empty=%s needs_ocr=%s",
            status,
            stats.added,
            stats.failed,
            stats.empty,
            stats.needs_ocr,
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
            # RETURNING always yields a row; a missing one means the insert did
            # not happen, and continuing with a fabricated id would mis-attribute
            # the whole run.
            if row is None:
                raise RuntimeError("创建 ingest_run 台账失败")
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
        "--trigger",
        default="manual",
        choices=["manual", "cron", "scheduler", "script"],
        help="记进台账的触发来源（默认 manual）",
    )
    p_ingest.add_argument(
        "--min-age",
        type=float,
        default=60.0,
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
    p_claims.add_argument(
        "--limit", type=int, default=None, help="最多处理多少个候选块（先跑小样本）"
    )
    p_claims.add_argument(
        "--sleep",
        type=float,
        default=1.0,
        help="块间限速秒数，防供应商 429 限流风暴（0=不限速；全量跑批建议 1s）",
    )
    p_claims.add_argument("--doc", default=None, help="只处理指定 doc_id")
    p_claims.add_argument(
        "--dry-run",
        action="store_true",
        help="只统计将抽取多少块 / 预计多少次 LLM 调用与耗时，不真正调模型（错峰前规划批次用）",
    )
    p_claims.add_argument(
        "--v2",
        action="store_true",
        help="写入 claims_v2 影子表并保留 review/rejected 审计记录；默认仍写 v1 claims",
    )
    p_claims.add_argument(
        "--max-consecutive-failures",
        type=int,
        default=5,
        help="连续失败多少块即熔断干净退出（额度耗尽 / 限流时别再烧额度；0=关闭熔断）",
    )
    p_claims.add_argument(
        "--max-attempts",
        type=int,
        default=3,
        help="同一块累计失败多少次后视为死信、不再重试（防必然失败的块反复花钱）",
    )
    p_claims.add_argument("--db", default=None)

    p_show_claims = sub.add_parser("claims", help="查询已抽取的 claim（D3/D4 的数据源）")
    p_show_claims.add_argument("--doc", default=None)
    p_show_claims.add_argument("--ticker", default=None, help="按标的代码过滤，如 600519.SH")
    p_show_claims.add_argument(
        "--subject", default=None, help="v2 subject 过滤；company 下等价于 ticker"
    )
    p_show_claims.add_argument("--kind", default=None, choices=["fact", "forecast", "opinion"])
    p_show_claims.add_argument("--v2", action="store_true", help="读取 claims_v2 影子表")
    p_show_claims.add_argument(
        "--quality",
        default="ok",
        choices=["ok", "review", "rejected", "all"],
        help="v2 质量状态过滤；默认 ok，all=包含 review/rejected",
    )
    p_show_claims.add_argument("--limit", type=int, default=50)
    p_show_claims.add_argument("--db", default=None)

    p_diff = sub.add_parser("claim-diff", help="D2 v1/v2 影子差异报告")
    p_diff.add_argument("--doc", default=None)
    p_diff.add_argument("--limit", type=int, default=1000)
    p_diff.add_argument("--db", default=None)

    p_set_kind = sub.add_parser(
        "set-doc-kind", help="人工纠正文档领域分类（§11 缺口#1：分类误判的纠正入口）"
    )
    p_set_kind.add_argument("--doc", required=True, help="doc_id")
    p_set_kind.add_argument(
        "--kind",
        required=True,
        choices=[*DOC_KINDS, "auto"],
        help="company/industry/macro；auto=清除覆盖、恢复自动分类",
    )
    p_set_kind.add_argument("--db", default=None)

    p_audit = sub.add_parser(
        "audit", help="D2 P5：语料库三类审计报告（完整性/一致性/质量，只读，JSON 输出）"
    )
    p_audit.add_argument("--doc", default=None, help="只审计指定 doc_id")
    p_audit.add_argument(
        "--jsonl",
        default=None,
        help="审计留痕 JSONL 路径（默认 data/corpus/.audit/audit_runs.jsonl，传空串禁用）",
    )
    p_audit.add_argument("--db", default=None)

    p_meta = sub.add_parser(
        "refresh-metadata",
        help="D2 P6：派生并物化文档级元数据（doc_kind/subject/org/analysts/published，纯规则 0 LLM）",
    )
    p_meta.add_argument("--doc", default=None, help="只处理指定 doc_id")
    p_meta.add_argument("--db", default=None)

    p_snap = sub.add_parser("snapshot", help="[旧名] 等价于 backup")
    p_snap.add_argument("--out", required=True)
    p_snap.add_argument("--db", default=None)

    args = parser.parse_args()
    svc = get_service(args.db)

    if args.cmd == "extract-claims":
        doc_ids = [args.doc] if args.doc else None
        # 幂等建表：块级台账（claim_block_runs）是后加的，老库必须先迁移，
        # 否则第一次跑会因为"表不存在"直接失败。
        svc.init_db()
        stop_requested = {"flag": False}

        def _request_stop(signum: int, _frame: object) -> None:
            """Ctrl-C 不再立刻炸掉进程：先把当前块做完，再干净退出。

            落库粒度是块，所以"当前块之后"没有任何未提交的数据会丢；这里做的是
            让汇总（含失败清单）能打印出来。**第二次 Ctrl-C 恢复默认行为**立即中断，
            否则一个卡在 300s 超时上的块会让用户等足 5 分钟。
            """
            if stop_requested["flag"]:
                signal.signal(signum, signal.SIG_DFL)
                return
            stop_requested["flag"] = True
            logger.warning(
                "收到信号 %s：当前块完成后干净退出（已落库的块不受影响，"
                "重跑会自动跳过）；再按一次 Ctrl-C 立即中断",
                signum,
            )

        previous_handlers: dict[int, object] = {}
        for sig in (signal.SIGINT, signal.SIGTERM):
            with contextlib.suppress(ValueError, OSError):  # 非主线程 / 平台不支持
                previous_handlers[sig] = signal.signal(sig, _request_stop)
        try:
            extract = svc.extract_claims_v2 if args.v2 else svc.extract_claims
            stats = extract(
                doc_ids=doc_ids,
                limit=args.limit,
                sleep_between=args.sleep,
                dry_run=args.dry_run,
                should_stop=lambda: stop_requested["flag"],
                max_consecutive_failures=args.max_consecutive_failures,
                max_attempts=args.max_attempts,
            )
        except RuntimeError as exc:  # 缺 OPENAI_API_KEY 等
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
            return 2
        finally:
            for sig, handler in previous_handlers.items():
                signal.signal(sig, handler)  # type: ignore[arg-type]
        out = stats.as_dict()
        if args.dry_run:
            # 用**真实历史均值**估算，而不是"每次 2 秒"这种拍脑袋常数：
            # 那版常数把 614 块估成 30.8 分钟，实测约 9 小时（差 17 倍）。
            per_call = svc.average_block_seconds()
            calls = out["candidates"]
            est_seconds = calls * (max(args.sleep, 0) + per_call)
            out = {
                **out,
                "dry_run": True,
                "estimated_llm_calls": calls,
                "estimated_seconds_per_call": round(per_call, 1),
                "estimated_seconds": round(est_seconds, 1),
                "estimated_minutes": round(est_seconds / 60, 1),
                "estimated_hours": round(est_seconds / 3600, 1),
            }
        print(json.dumps(out, ensure_ascii=False, indent=2))
        if args.dry_run:
            return 0
        if stats.stopped_early:
            return 130  # 中断 / 熔断提前退出（Unix 惯例：130 = 被 SIGINT 打断）
        return 1 if stats.failed else 0

    if args.cmd == "claims":
        if args.v2:
            subject = args.subject or args.ticker
            rows = svc.claims_v2_of(
                doc_id=args.doc,
                subject=subject,
                kind=args.kind,
                quality_status=None if args.quality == "all" else args.quality,
                limit=args.limit,
            )
        else:
            rows = svc.claims_of(
                doc_id=args.doc, ticker=args.ticker, kind=args.kind, limit=args.limit
            )
        print(json.dumps(rows, ensure_ascii=False, indent=2, default=str))
        return 0

    if args.cmd == "claim-diff":
        print(
            json.dumps(
                svc.claim_version_diff(doc_id=args.doc, limit=args.limit),
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )
        return 0

    if args.cmd == "set-doc-kind":
        # doc_kind 决定抽取插槽与文档级标的兜底；误判时整份文档坐标全错（§11 缺口#1）
        svc.set_doc_kind(args.doc, None if args.kind == "auto" else args.kind)
        print(json.dumps({"ok": True, "doc_id": args.doc, "doc_kind": args.kind}))
        return 0

    if args.cmd == "audit":
        # 延迟导入：audit 反向依赖本模块的 _BACKUP_COLUMNS（备份覆盖率检查）
        from plugins.corpus.audit import run_audit

        report, code = run_audit(
            args.db or dsn(),
            doc_ids=[args.doc] if args.doc else None,
            jsonl_path=args.jsonl,
        )
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        return code

    if args.cmd == "refresh-metadata":
        svc.init_db()  # 幂等：老库补 P6 四列迁移
        print(
            json.dumps(
                svc.refresh_metadata([args.doc] if args.doc else None), ensure_ascii=False, indent=2
            )
        )
        return 0

    if args.cmd == "ingest":
        result = svc.run_ingest(args.dir, trigger=args.trigger, min_age=args.min_age)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        code = result.get("exit_code", 2)
        return code if isinstance(code, int) else 2
    elif args.cmd == "runs":
        svc.init_db()
        print(json.dumps(svc.recent_runs(args.limit), ensure_ascii=False, indent=2, default=str))
    elif args.cmd == "failures":
        svc.init_db()
        print(json.dumps(svc.run_failures(args.run), ensure_ascii=False, indent=2, default=str))
    elif args.cmd == "stats":
        svc.init_db()
        print(json.dumps(svc.stats(), ensure_ascii=False, indent=2, default=str))
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
