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
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, LiteralString, cast
from urllib.parse import quote

if TYPE_CHECKING:
    # Runtime import stays inside fetch() to avoid a circular import; this one
    # exists so the annotation resolves for type checking.
    # psycopg 是可选依赖（PG 演练链路专属）：类型仅用于标注（本模块有
    # ``from __future__ import annotations``，运行时不求值）；实际连接在
    # 函数内惰性 import，普通 sqlite 环境零 psycopg。
    from collections.abc import Mapping

    import psycopg
    from psycopg.rows import DictRow

    from plugins.corpus.derivation import Calculation
    from plugins.corpus.evidence_pipeline import EvidenceRun
    from plugins.corpus.fetch import FetchedBlock
    from plugins.corpus.material_semantics import MaterialRun, MaterialType
    from plugins.corpus.preparation.read_pg import CellEvidence, ChunkEvidence
    from plugins.corpus.preparation.search_pg import SearchHit as SearchPgHit
    from plugins.corpus.preparation.selection import SelectedBand

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
from plugins.corpus.metadata import (
    DOCUMENTS_MIGRATIONS_SQL,
    derive_metadata,
)
from plugins.corpus.preparation.admission import AdmissionPolicy, load_admission_policy
from plugins.corpus.preparation.contract import AdmissionDecision, sha256_of_bytes
from plugins.corpus.preparation.engine import (
    DEFAULT_LEASE,
    EngineError,
    PlanEntry,
    execute_builds,
    plan_builds,
    publish_build,
)
from plugins.corpus.preparation.repository import StoreError
from plugins.corpus.preparation.repository_pg import PgStore
from plugins.corpus.preparation.source import SourceIngestError

logger = logging.getLogger(__name__)

# ── I2-7：写路径代理新 preparation Module（design-review 消费者矩阵裁决）──────
# CorpusService 写路径唯一化：ingest_path/ingest_dir 一律走 preparation.engine
# 的 plan→execute→publish；新链落隔离演练库（PgStore/_check_target fail-closed
# 拒绝非 i2_sandbox_corpus 实例）。旧 documents/blocks 直写分支在本文件退役。
_I2_SANDBOX_DB = "i2_sandbox_corpus"

#: 生产检索候选池下限（R3 闭环）：选择策略需要足够大的候选池才能生效——
#: ``top_k 来源 × max_chunks_per_document 块`` = 5×8。池取 ``max(limit, 40)``，
#: 选择后仍截断到调用方 ``limit``（limit 语义 = 返回条数上限，不变）。
_SELECTION_POOL_MIN = 40
_I2_ARCHIVE_ROOT = Path(__file__).resolve().parents[2] / "data" / "corpus-archive"

#: B2 abstain 拒检通道：DB 级 websearch AND 预检的候选上限（F1 回测同口径，覆盖
#: 全部命中池）。AND 收紧查询在真负例下归零→零 fetch；仅在收紧仍有命中时才按命中
#: 逐块取原文跑单元级谓词（保险带，块数有界）。
_ABSTAIN_PRE_CHECK_LIMIT = 2000
_I2_POLICY_PATH = (
    Path(__file__).resolve().parents[2]
    / ".scratch"
    / "corpus-evidence-pipeline"
    / "ingestion-rebuild"
    / "admission-policy.json"
)
_I2_OWNER = "corpus-service"
_I2_DECISION_FAILED = "failed"

# ── 语料目录枚举（I2-7：自 ingest 退休内联；解析能力归 preparation/readers/*）──
CORPUS_ROOT = "data/corpus"
_INGEST_SUFFIXES = frozenset({".pdf", ".docx", ".md"})

# ── I2-7 新式版本化句柄（R2：基础读取迁移，读侧不再查旧 blocks）──────────────
# ``cv2:<source_id>``（source_id = 64 位 SHA-256）指向新链 corpus schema 的
# ``corpus_units``/``corpus_publications``；旧句柄（无前缀）显式走旧 blocks 归档
# 路径。二者显式区分，不静默互换正文（旧句柄精确版本/归档策略归 I2-8）。
_CV2_HANDLE_PREFIX = "cv2:"


def _source_id_from_cv2_handle(doc_id: str) -> str | None:
    """解析 ``cv2:<source_id>`` 新式句柄；非 cv2 句柄返回 None（旧句柄路径）。"""
    if not isinstance(doc_id, str) or not doc_id.startswith(_CV2_HANDLE_PREFIX):
        return None
    source_id = doc_id[len(_CV2_HANDLE_PREFIX) :]
    if len(source_id) != 64 or any(c not in "0123456789abcdef" for c in source_id):
        raise ValueError(f"新式句柄 source_id 非法（须为 64 位十六进制）: {doc_id!r}")
    return source_id


def _iter_corpus_files(root: str | Path = CORPUS_ROOT) -> Iterable[Path]:
    """遍历语料目录里的可解析文件（跳过 README 与隐藏文件）。"""
    directory = Path(root)
    for path in sorted(directory.iterdir()):
        if (
            path.is_file()
            and not path.name.startswith(".")
            and path.name != "README.md"
            and path.suffix.lower() in _INGEST_SUFFIXES
        ):
            yield path


EVIDENCE_RUNS_SQL = """
CREATE TABLE IF NOT EXISTS corpus_evidence_runs (
    run_id text PRIMARY KEY, doc_id text NOT NULL, source_rev text NOT NULL,
    parse_rev text NOT NULL, payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS corpus_evidence_runs_doc ON corpus_evidence_runs(doc_id, parse_rev);
"""


@dataclass
class SearchHit:
    """一次检索命中（与 index.SearchHit 字段对齐，供工具层复用）。

    I2-8：新链命中额外携带 ``source_id``/``build_id``/``chunk_id``——
    ``doc_id``/``locator`` 是§7.2 的取证句柄（``cv2:<build_id>`` + ``chunk:<chunk_id>``），
    稳定来源身份与块身份另列，便于调用方断言"读的是哪个 build"。
    """

    doc_id: str
    locator: str
    title: str
    snippet: str
    score: float
    published: str
    source_id: str = ""
    build_id: str = ""
    chunk_id: str = ""


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
    """Collapse identical observations, preserving different subjects and conflicting values."""
    seen: set[tuple[object, ...]] = set()
    kept: list[Claim] = []
    for claim in reversed(claims):
        if claim.metric is None:
            kept.append(claim)
            continue
        key = (
            tuple(sorted(claim.tickers)),
            claim.metric,
            claim.period,
            claim.kind,
            claim.value_text or claim.claim_text,
            claim.unit,
            claim.as_of,
        )
        if key in seen:
            continue
        seen.add(key)
        kept.append(claim)
    kept.reverse()
    return kept


@dataclass(frozen=True)
class EmittedCell:
    """网格派生的对齐单元格证据（§10.5 选项 A + cell 投影）。

    ``row``/``col`` 是相对网格坐标的权威标签文本（同一行左侧/同列上方最近的含字母
    单元），不是原始行列号；``text`` 是坐标对应的逐胞对齐文本（raw_text ``"\\n"``
    切分与 ``cells`` 精确对齐的格子内容）。
    """

    unit_id: str
    page: int | None
    row: str
    col: str
    text: str


@dataclass(frozen=True)
class BandEvidenceItem:
    """一个选中带内的单块证据（原文序带内全部块，含扩展的非池块）。"""

    chunk_id: str
    title_text: str | None
    section_path: tuple[str, ...]
    text: str
    pages: tuple[int, ...]


@dataclass(frozen=True)
class BandDocument:
    """:meth:`CorpusService.search_bands` 的返回：一个选中文档的带区间检索结果。

    ``bands`` 是 ``selection.select_band`` 的选中带（按带分降序、并列按带起点）；
    ``chunks_by_band[i]`` 对应 ``bands[i]`` 带内原文序全部块的逐字证据（含扩展块）；
    ``cells`` 是仅对选中带内对齐表单元派生的 row:/col: 证据（不改变选择）。
    """

    source_id: str
    build_id: str
    doc_handle: str
    bands: tuple[SelectedBand, ...]
    chunks_by_band: tuple[tuple[BandEvidenceItem, ...], ...]
    cells: tuple[EmittedCell, ...]


class CorpusService:
    """语料服务：所有 PG 访问经此。"""

    def __init__(self, dsn_url: str | None = None) -> None:
        self._dsn = dsn_url or dsn()
        self._lock = threading.Lock()
        # I2-7：新链写路径上下文（隔离演练库 Store + 冻结准入政策）惰性缓存。
        self._engine_store: PgStore | None = None
        self._engine_policy: AdmissionPolicy | None = None
        # I2-8：读链判定缓存（new=corpus schema 可用；legacy=旧 documents/blocks）。
        self._read_chain_cache: str | None = None

    # ── 连接 ──────────────────────────────────────────────────

    def _connect(self) -> psycopg.Connection[DictRow]:
        """Open a connection whose rows are dicts.

        The ``[DictRow]`` is what makes typed access work everywhere else:
        psycopg's ``connect`` infers its row type from the *return* context, so
        annotating this as a bare ``psycopg.Connection`` pins it to ``TupleRow``
        and every ``row["col"]`` downstream is then an error. One annotation
        here is the difference between ~70 type errors and none.
        """
        import psycopg
        from psycopg.rows import dict_row

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
        import psycopg

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
            conn.execute(EVIDENCE_RUNS_SQL)
            # 老库幂等迁移：三列事实列 + doc_kind_override + 删除 entities 死字段
            conn.execute(CLAIMS_MIGRATIONS_SQL)
            # P6（§3.5）：文档级元数据四列（doc_kind/subject/org/analysts）
            conn.execute(DOCUMENTS_MIGRATIONS_SQL)
            for stmt in (
                *_COLUMN_COMMENTS,
                *LEDGER_COMMENTS,
                *CLAIMS_COMMENTS,
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
        **非空即覆盖**（幂等）；``published`` 只回填 NULL（I2-7 后 ingest 与本
        方法共用 metadata 模块这一唯一日期落点：来源显式日期，禁止从 doc_id
        前缀推断，已填的不覆盖）。纯规则派生，0 LLM 成本；抽取链路行为不变
        （抽取仍按 override → 现算分类取插槽，这里只是把同一判定落到列，
        供 D3/D4 直接 join，不再各自重算）。
        """
        from psycopg.rows import dict_row

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
                meta = derive_metadata(title, texts, row["doc_kind_override"])
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
        from psycopg.rows import dict_row

        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT seq, text FROM blocks WHERE doc_id = %s ORDER BY seq",
                (doc_id,),
            )
            return cur.fetchall()

    # ── 写入 ──────────────────────────────────────────────────

    def _preparation_context(self) -> tuple[PgStore, AdmissionPolicy]:
        """新链写路径上下文（惰性缓存）：隔离演练库 Store + 冻结准入政策。

        fail-closed（I2-7 消费者矩阵）：``CORPUS_I2_DSN`` 未配置即拒绝一切写入——
        写路径已唯一化为 preparation.engine 链路（plan→execute→publish），不再有
        旧 documents/blocks 直写兜底；PgStore._check_target 会拒绝一切非
        ``i2_sandbox_corpus`` 实例。
        """
        if self._engine_store is None or self._engine_policy is None:
            sandbox_dsn = os.environ.get("CORPUS_I2_DSN", "")
            if not sandbox_dsn:
                raise RuntimeError(
                    "写路径已代理新 preparation Module（I2-7）：需要 CORPUS_I2_DSN 指向"
                    f"隔离演练库 {_I2_SANDBOX_DB}；未配置则拒绝写入（无旧直写兜底）"
                )
            self._engine_store = PgStore(sandbox_dsn, sandbox_db=_I2_SANDBOX_DB)
            self._engine_policy = load_admission_policy(_I2_POLICY_PATH)
        return self._engine_store, self._engine_policy

    def _ingest_via_engine(
        self,
        files: Sequence[Path],
        *,
        min_age: float = 0.0,
        review_decision_ids: Sequence[str] = (),
    ) -> tuple[IngestStats, list[tuple[str, str, bool]]]:
        """统一准备代理（I2-7）：逐来源 plan→execute→publish，返回（统计, 逐路径结果）。

        - ``min_age``（秒）：跳过刚被修改的文件（防半拷贝假失败，语义沿袭旧直写分支）。
        - ``review_decision_ids``：清单条目携带的人工审核决定（决定绑定单源哈希；
          政策 ``auto_decision.enabled=false``——无决定一律 review_required 不发布，
          这是设计内状态，无 legacy fallback）。批量目录共用一组决定仅对单文件
          清单有意义。
        - 内容寻址预检（契约 §4.1 source_id 仅由字节决定）：来源已登记且活动发布
          存在 ⇒ ``skipped_unchanged``（同目录重跑）/ ``skipped_duplicate``（改名
          重收），不重复解析、不重复发布（不二次解析生成主正文）。
        - 已登记但未发布的来源照常重新走链（补发布/重裁决，全程幂等）。
        - 单份失败记 ``failed`` 并继续（引擎保证该来源归档/登记一致、可恢复）；
          publish 走引擎 C1 四步协议（幂等重放短路 + VERIFIED 校验 + job 租约）。

        逐路径结果为 ``(路径, 准入决定取值, 是否本次新发布)``，与输入同序同长；
        排除/待复核不发布（无 legacy fallback），执行失败决定记 "failed"。
        """
        stats = IngestStats()
        results: list[tuple[str, str, bool]] = []
        decision_ids = tuple(review_decision_ids)

        pending: list[Path] = []
        if min_age > 0:
            cutoff = time.time() - min_age
            fresh = [p for p in files if p.stat().st_mtime > cutoff]
            pending = [p for p in files if p.stat().st_mtime <= cutoff]
            if fresh:
                stats.skipped_fresh = len(fresh)
                logger.warning(
                    "跳过 %s 份刚被修改的文件（可能仍在拷贝中）：稍后再跑一次即可，"
                    "或由下次跑批自动补上",
                    len(fresh),
                )
        else:
            pending = list(files)
        if not pending:
            return stats, results

        store, policy = self._preparation_context()
        for path in pending:
            key = str(path)
            stats.total += 1
            try:
                data = path.read_bytes()
            except OSError as exc:
                stats.failed += 1
                stats.failures.append((key, f"读取失败：{exc}"))
                logger.warning("ingest 读取失败：%s", key, exc_info=True)
                results.append((key, _I2_DECISION_FAILED, False))
                continue
            if not data:
                stats.failed += 1
                stats.failures.append((key, "来源文件为空，不接收"))
                results.append((key, _I2_DECISION_FAILED, False))
                continue

            # 内容寻址幂等预检：仅当调用方**未显式传入新审核决定**时，已登记且
            # 活动发布存在才短路（同目录重跑/改名重收不重复解析、不重复发布）。
            # 显式 review_decision_ids 表示要求重新裁决（R3），必须走 plan/engine
            # 求值新决定（新排除/缩小范围/新 index_rev 重评），不得被旧活动发布
            # 静默跳过——同源身份稳定不等于处理状态、授权范围与构建版本永远不变。
            source_id = sha256_of_bytes(data)
            publication = store.get_publication(source_id)
            if (
                not decision_ids
                and publication is not None
                and publication.active_build_id is not None
            ):
                source = store.get_source(source_id)
                if source is not None and path.name not in source.original_names:
                    stats.skipped_duplicate += 1  # 改名重收：同源不同路径名
                else:
                    stats.skipped_unchanged += 1
                results.append((key, AdmissionDecision.IN_SCOPE.value, False))
                continue

            try:
                plan = plan_builds(
                    [PlanEntry(path=key, review_decision_ids=decision_ids)], policy=policy
                )
                report = execute_builds(
                    store,
                    plan,
                    policy=policy,
                    archive_root=_I2_ARCHIVE_ROOT,
                    owner_id=_I2_OWNER,
                    now=datetime.now(UTC),
                    lease=DEFAULT_LEASE,
                )
            except (EngineError, SourceIngestError, StoreError) as exc:
                # 单份失败不中断整批；引擎保证失败来源状态一致（可恢复）。
                stats.failed += 1
                stats.failures.append((key, str(exc)))
                logger.exception("ingest 执行失败：%s", key)
                results.append((key, _I2_DECISION_FAILED, False))
                continue

            outcome = report.outcomes[0]
            decision = outcome.admission.decision
            if decision is not AdmissionDecision.IN_SCOPE or outcome.build is None:
                # 排除/待复核：不发布（无 legacy fallback）。
                results.append((key, decision.value, False))
                continue
            try:
                publish_build(
                    store,
                    outcome.build.build_id,
                    activated_at=datetime.now(UTC),
                    owner_id=_I2_OWNER,
                )
            except (EngineError, StoreError) as exc:
                # 发布失败不中断整批；来源已登记，下次重跑走补发布路径（幂等）。
                stats.failed += 1
                stats.failures.append((key, f"发布失败：{exc}"))
                logger.exception("ingest 发布失败：%s", key)
                results.append((key, decision.value, False))
                continue
            stats.added += 1
            stats.blocks += outcome.chunk_count
            results.append((key, decision.value, True))

        logger.info(
            "ingest 完成（新链代理）：total=%s added=%s unchanged=%s dup=%s failed=%s",
            stats.total,
            stats.added,
            stats.skipped_unchanged,
            stats.skipped_duplicate,
            stats.failed,
        )
        return stats, results

    def ingest_path(
        self, path: str | Path, *, review_decision_ids: Sequence[str] = ()
    ) -> tuple[str, bool]:
        """代理新链接收一份来源（plan→execute→publish），返回 ``(决定, published)``。

        I2-7：``status`` 语义由旧 ok/needs_ocr/empty 换为准入决定取值
        （in_scope/excluded_by_policy/review_required；执行失败记 "failed"）；
        ``published`` 表示本次调用后该来源是否新置于活动发布（已发布的重复来源
        幂等重放返回 False）。

        ``review_decision_ids``：绑定该来源哈希的人工审核决定（政策
        ``auto_decision.enabled=false``——无决定不自动纳入，落 review_required）。
        """
        _stats, results = self._ingest_via_engine(
            [Path(path)], review_decision_ids=review_decision_ids
        )
        decision, published = results[0][1], results[0][2]
        return decision, published

    def ingest_dir(
        self,
        root: str | Path = CORPUS_ROOT,
        *,
        rebuild_index: bool = True,
        min_age: float = 0.0,
    ) -> IngestStats:
        """跑批入库一个目录，返回统计（代理新链 plan→execute→publish）。

        ``rebuild_index`` 参数保留兼容签名但不再生效：新链发布时由引擎自动维护
        检索索引（PG 生成列 ``tsv``），无手动重建需求。

        ``min_age``（秒）：跳过最近刚被修改过的文件（防半拷贝假失败），0 表示
        不启用；幂等语义见 :meth:`_ingest_via_engine`（同目录重跑 skip_unchanged、
        改名重收 skip_duplicate、排除/待复核不发布）。
        """
        files = list(_iter_corpus_files(root))
        stats, _results = self._ingest_via_engine(files, min_age=min_age)
        return stats

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

    def read_chain(self) -> str:
        """读侧链路：``new``（corpus schema 活动版本）或 ``legacy``（旧 blocks）。

        RM-I28-8 裁定 A（演练目标无 legacy fallback，且降级不可达）：

        - ``new``：要求目标库承载 ``corpus.corpus_publications``，否则 fail-closed
          拒绝（不得默默回退旧 ``blocks``）；
        - ``legacy``：仅在**不含 corpus schema** 的真旧库上允许（切换期兜底）；
          目标库已有 corpus schema 时请求 ``legacy`` 直接拒绝——「新库上静默降级读旧表」
          这条路径不可达，M5 可据此自证；
        - ``auto``（默认）：按目标库结构探测（有 corpus schema 即 ``new``）；
          仅适用于尚未迁移的旧库，文档写明适用范围。
        """
        cached = self._read_chain_cache
        if cached is not None:
            return cached
        configured = os.environ.get("CORPUS_READ_CHAIN", "auto").strip().lower()
        if configured not in ("new", "legacy", "auto"):
            raise StoreError(
                f"拒绝：CORPUS_READ_CHAIN 取值非法: {configured!r}（须 new|legacy|auto）"
            )
        has_chain = self._corpus_schema_present()
        if configured == "new":
            if not has_chain:
                raise StoreError(
                    "拒绝：CORPUS_READ_CHAIN=new 但目标库无 corpus schema"
                    "（不得回退旧 blocks 冒充新链）"
                )
            chain = "new"
        elif configured == "legacy":
            if has_chain:
                raise StoreError(
                    "拒绝：目标库已承载新链（corpus schema），legacy 读路径不可达"
                    "（禁止在新库上静默降级读旧 blocks）"
                )
            chain = "legacy"
        else:
            chain = "new" if has_chain else "legacy"
        self._read_chain_cache = chain
        return chain

    def _corpus_schema_present(self) -> bool:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT to_regclass('corpus.corpus_publications') IS NOT NULL AS ok")
            row = cur.fetchone()
        return bool(row and row["ok"])

    def coverage(self, query_status: str = "unknown") -> dict[str, object]:
        """§7.3 三轴覆盖快照（新链）；新链不可用时返回 ``processing=unknown``。

        ``no_match`` 不自动转 ``absent``：自由文本 FTS 无命中时 availability 仍为
        unknown——只说明"该已查询范围无匹配"，不能外推整个来源集合没有相关资料。
        """
        if self.read_chain() != "new":
            return {
                "requested_scope_ref": None,
                "effective_scope_ref": None,
                "publication_snapshot_ref": None,
                "processing": "unknown",
                "query_status": query_status,
                "availability": "unknown",
                "reason_codes": ("legacy_chain",),
            }
        from plugins.corpus.preparation import read_pg

        return read_pg.coverage_snapshot(
            self._dsn, sandbox_db=_I2_SANDBOX_DB, query_status=query_status
        )

    def _apply_selection(
        self, raw_hits: tuple[SearchPgHit, ...], query: str, limit: int
    ) -> tuple[SearchPgHit, ...]:
        """生产检索路径的选择策略（R3 闭环，i42 perdoc 形态）。

        ``raw_hits`` 是 :mod:`search_pg` 的扁平命中（score 降序候选池）；策略为
        :func:`selection.select_structural`（perdoc：文档序=词法首次出现，文档内按
        (结构重叠数, score) 重排），随后截断到调用方 ``limit``。词元
        （``query_lexemes``）只依赖查询文本、不依赖语料快照，故在组合读取事务
        之外调用不破坏同快照保证；空池原样返回（保持 no_match 语义）。
        """
        from plugins.corpus.preparation.search_pg import query_lexemes
        from plugins.corpus.preparation.selection import SelectionPolicy, select_structural

        if not raw_hits:
            return raw_hits
        lexemes = query_lexemes(self._dsn, query, sandbox_db=_I2_SANDBOX_DB)
        # select_structural 只对 raw_hits 做选择/重排（返回其子序列），cast 到调用方
        # 期望的具体类型是安全的。
        selected = select_structural(raw_hits, SelectionPolicy(), lexemes=lexemes)
        return cast(tuple[SearchPgHit, ...], tuple(selected))[:limit]

    def _abstain_decision(self, query: str) -> bool:
        """B2 no-answer 判定层拒检兜底（U 受控，默认关）。

        F1 负例 6→0 只依赖金标分支收紧；产品侧无金标，故对所有查询统一走判定层
        兜底：若语料里没有**任一单元同时满足全部内容词元**（websearch AND 预检归零，
        或收紧命中后单元级谓词全拒），即判「有检索但无实质答案」→ 拒检（abstain）。
        有实质答案的单元在 AND 收紧下仍含全部内容词元、score 高且必在候选池内 →
        判定 False，产品查询路径原样返回（结构性保护 S1，不改查询路径、不改排序）。

        开关 ``CORPUS_ABSTAIN_NO_ANSWER``（on|off，默认 off）：off 恒返回 False，
        :meth:`search_with_coverage` 逐字节不变。非法值 fail-closed 抛
        :class:`StoreError`（镜像 :meth:`read_chain` 惯例）。仅作用于新链。
        """
        cfg = os.environ.get("CORPUS_ABSTAIN_NO_ANSWER", "off").strip().lower()
        if cfg not in ("on", "off"):
            raise StoreError(f"拒绝：CORPUS_ABSTAIN_NO_ANSWER 取值非法: {cfg!r}（须 on|off）")
        if cfg != "on" or self.read_chain() != "new":
            return False
        from plugins.corpus.preparation.negative_query import (
            abstain_content_lexemes,
            abstain_no_answer_query,
            is_abstain_candidate,
        )
        from plugins.corpus.preparation.search_pg import query_lexemes, search_chunks

        lexemes = query_lexemes(self._dsn, query, sandbox_db=_I2_SANDBOX_DB)
        if not abstain_content_lexemes(lexemes):
            return False
        # 主门：DB 级 websearch AND 预检（实质词元=去疑问词；F1 真负例下归零 → 零 fetch）。
        # 疑问词（什么/多少/如何…）只出现在题面、几乎不出现在答案单元——实证 24 条有
        # 答案题中 23 条含疑问词，保留则 full-AND 必然归零、误杀有答案题（S1 降），故剔除。
        hits = search_chunks(
            self._dsn,
            abstain_no_answer_query(lexemes),
            limit=_ABSTAIN_PRE_CHECK_LIMIT,
            sandbox_db=_I2_SANDBOX_DB,
        )
        if not hits:
            return True
        # 保险带：收紧仍有命中 → 按命中取权威单元，任一满足全部实质词元即放行。
        from plugins.corpus.preparation import read_pg

        for hit in hits:
            ev = read_pg.fetch_verbatim(
                self._dsn,
                read_pg.build_handle(hit.build_id),
                read_pg.chunk_locator(hit.chunk_id),
                sandbox_db=_I2_SANDBOX_DB,
            )
            if any(is_abstain_candidate(u.raw_text, lexemes) for u in ev.units):
                return False
        return True

    def search_with_coverage(
        self, query: str, *, limit: int = 10
    ) -> tuple[list[SearchHit], dict[str, object]]:
        """检索 + 覆盖元数据取自**同一数据库快照**（§7.3 并发发布一致性）。

        工具层用本方法一次取回两者，避免「先取 hits 再取 coverage」拼接自两个时刻。
        新链命中经选择策略（:meth:`_apply_selection`，perdoc）后返回，limit 仍是
        返回条数上限。

        B2（``CORPUS_ABSTAIN_NO_ANSWER=on``）：终点判定若判「无实质答案」→ 拒检，
        返回**空命中** + ``query_status="abstain"`` 的拒检覆盖信号（评分器对空观测
        不计误报；与 ``no_match``「无研报覆盖」机器可区分）。开关默认关闭，不改返回。
        """
        if self.read_chain() != "new":
            hits = self.search(query, limit=limit)
            return hits, self.coverage(query_status="matched" if hits else "no_match")
        from plugins.corpus.preparation import read_pg

        raw_hits, chunk_order, coverage = read_pg.search_with_coverage_bands(
            self._dsn,
            query,
            limit=max(limit, _SELECTION_POOL_MIN),
            sandbox_db=_I2_SANDBOX_DB,
        )
        if self._abstain_decision(query):
            abstain_cov = read_pg.coverage_snapshot(
                self._dsn,
                sandbox_db=_I2_SANDBOX_DB,
                query_status="abstain",
            )
            abstain_cov.update({"abstain": True, "abstain_reason": "no_answer_rejected"})
            return [], abstain_cov
        # 生产默认（i0c-r4n U 决策）：band 选带 → 带内原文序块摊平为逐块命中。
        raw_hits = self._selected_chunk_hits(raw_hits, chunk_order, limit)
        return (
            [
                SearchHit(
                    doc_id=read_pg.build_handle(hit.build_id),
                    locator=read_pg.chunk_locator(hit.chunk_id),
                    title=hit.title_text
                    or (hit.section_path[-1] if hit.section_path else hit.chunk_id),
                    snippet=hit.snippet,
                    score=float(hit.score),
                    published=hit.published or "undated",
                    source_id=hit.source_id,
                    build_id=hit.build_id,
                    chunk_id=hit.chunk_id,
                )
                for hit in raw_hits
            ],
            coverage,
        )

    def search_bands(
        self, query: str, *, limit: int = 10
    ) -> tuple[list[BandDocument], dict[str, object]]:
        """band 区间检索（§10.5 选项 A 落产品）：同快照命中 + 连续区间取回 + cell 投影。

        新链专属（legacy 链不支持带选择，fail-closed 拒绝）。同一数据快照内取得
        ``search_with_coverage_bands`` 的 (命中, 原文序块清单, 覆盖)，经
        :meth:`_apply_selection_bands` 选中带，再批量取回带内逐字证据，并对选中带内
        对齐表单元派生 row:/col: cell 证据（不改变选择）。返回 ``(list[BandDocument],
        coverage)``；``limit`` 仍是返回条数/带数的上限语义。
        """
        from plugins.corpus.preparation import read_pg

        if self.read_chain() != "new":
            raise read_pg.LegacyHandleError(
                f"目标库未承载 band 区间选择（read_chain={self.read_chain()}），需新链"
            )
        raw_hits, chunk_order, coverage = read_pg.search_with_coverage_bands(
            self._dsn,
            query,
            limit=max(limit, _SELECTION_POOL_MIN),
            sandbox_db=_I2_SANDBOX_DB,
        )
        bands = self._apply_selection_bands(raw_hits, chunk_order, limit)
        chunk_evs = read_pg.fetch_bands(self._dsn, bands, chunk_order, sandbox_db=_I2_SANDBOX_DB)
        docs = self._assemble_band_documents(bands, chunk_evs, chunk_order)
        return docs, coverage

    def _apply_selection_bands(
        self,
        raw_hits: tuple[SearchPgHit, ...],
        chunk_order_by_source: Mapping[str, tuple[str, ...]],
        limit: int,
    ) -> tuple[SelectedBand, ...]:
        """band 选择（§10.5 选项 A）：``select_band`` 前 ``top_k`` 来源 × 带数上限。

        与 :meth:`_apply_selection` 平行的带路径——文档序与 perdoc ``select`` 逐字节
        一致（首个命中确定来源排名），文档内把命中块聚簇成带并按带分取前 ``band_cap``
        个带。空池原样返回（保持 no_match 语义）。
        """
        from plugins.corpus.preparation.selection import BandPolicy, SelectionPolicy, select_band

        if not raw_hits:
            return ()
        bands = select_band(
            raw_hits,
            SelectionPolicy(),
            BandPolicy(),
            chunk_order_by_source=chunk_order_by_source,
        )
        return tuple(bands)[:limit]

    def _selected_chunk_hits(
        self,
        raw_hits: tuple[SearchPgHit, ...],
        chunk_order_by_source: Mapping[str, tuple[str, ...]],
        limit: int,
    ) -> tuple[SearchPgHit, ...]:
        """生产默认：band 选中的 chunk 集（§10.5 选项 A，i0c-r4n U 决策）。

        与 :meth:`_apply_selection`（perdoc）并列但为**生产默认**的带形态：文档选择与
        ``select`` 逐字节一致（首个命中定来源排名），文档内按 ``select_band`` 选中带，
        把带内 [start, end] 的原文序块（含扩展非池块）摊平为逐块命中返回，再截断到
        ``limit``。仍以 ``chunk:<chunk_id>`` 取证句柄交给工具——硬闸①不变：snippet 截断，
        逐字原文必须另走 ``corpus_fetch``。池块复用原命中的 snippet/score，扩展非池块
        以带分占位、snippet 为空（只定位，不泄漏全文）。
        """
        from plugins.corpus.preparation.search_pg import SearchHit as SearchPgHitAlias
        from plugins.corpus.preparation.selection import SelectionError

        bands = self._apply_selection_bands(raw_hits, chunk_order_by_source, limit)
        if not bands:
            return ()
        by_key = {(h.build_id, h.chunk_id): h for h in raw_hits}
        out: list[SearchPgHit] = []
        for band in bands:
            ordered = chunk_order_by_source.get(band.source_id)
            if ordered is None:
                raise SelectionError(f"缺少 {band.source_id} 的原文序块清单")
            for i in range(band.start, band.end + 1):
                if not (0 <= i < len(ordered)):
                    continue
                cid = ordered[i]
                hit = by_key.get((band.build_id, cid))
                if hit is None:
                    # 带内扩展的非池块没有原始命中——只给取证件，不留全文。
                    hit = SearchPgHitAlias(
                        source_id=band.source_id,
                        build_id=band.build_id,
                        chunk_id=cid,
                        kind="",
                        title_text=None,
                        section_path=(),
                        unit_refs=(),
                        score=band.score,
                        snippet="",
                        published=None,
                    )
                out.append(hit)
                if len(out) >= limit:
                    return tuple(out)
        return tuple(out)

    @staticmethod
    def _has_letter(s: str) -> bool:
        """含 CJK 或 ASCII 字母即视为行/列标签候选（排除纯数字/符号/占位符）。"""
        return any(ch.isalpha() for ch in s)

    def _emit_cells(self, chunk: ChunkEvidence) -> tuple[EmittedCell, ...]:
        """对单块对齐表单元建网格，派生 row:/col: 标签并发射 cell 证据。

        ``raw_text.split("\\n")`` 长度与 ``cells`` 精确对齐才入格（切分不对齐不派生）；
        row = 同行左侧最近含字母单元，col = 同列上方最近含字母单元；两者都派生成功才
        发射（否则诚实失败，不猜标签）。只派生、不改变块选择（遵守议题 A 硬约束）。
        """
        grid: dict[tuple[int, int], tuple[str, str]] = {}
        page: int | None = None
        for unit in chunk.units:
            if not unit.cells or unit.page is None:
                continue
            parts = unit.raw_text.split("\n")
            if len(parts) != len(unit.cells):
                continue
            if page is None:
                page = unit.page
            for (r, c), text in zip(unit.cells, parts, strict=True):
                grid[(r, c)] = (text, unit.unit_id)
        out: list[EmittedCell] = []
        for (r, c), (text, unit_id) in grid.items():
            row_label = col_label = None
            for c2 in range(c - 1, -1, -1):
                if grid.get((r, c2)) is not None and self._has_letter(grid[(r, c2)][0]):
                    row_label = grid[(r, c2)][0]
                    break
            for r2 in range(r - 1, -1, -1):
                if grid.get((r2, c)) is not None and self._has_letter(grid[(r2, c)][0]):
                    col_label = grid[(r2, c)][0]
                    break
            if row_label is None or col_label is None:
                continue
            out.append(
                EmittedCell(
                    unit_id=unit_id,
                    page=page,
                    row=row_label,
                    col=col_label,
                    text=text,
                )
            )
        return tuple(out)

    def _assemble_band_documents(
        self,
        bands: tuple[SelectedBand, ...],
        chunk_evs: tuple[ChunkEvidence, ...],
        chunk_order_by_source: Mapping[str, tuple[str, ...]],
    ) -> list[BandDocument]:
        """把``select_band``选中带 + ``fetch_bands``逐字块装配为 :class:`BandDocument`。

        ``chunk_evs`` 是扁平带序块（fetch_bands 已按 (build_id, chunk_id) 去重）；
        ``chunk_order_by_source`` 提供原文序，把每个带闭区间 [start, end] 投影为带内块，
        再补发射对齐 cell 证据。带内块仍按原文序（含扩展非池块；跨带共享块按带独立出现）。
        """
        from plugins.corpus.preparation import read_pg

        ev_by_key = {(ev.build_id, ev.chunk_id): ev for ev in chunk_evs}
        by_source: dict[str, list[SelectedBand]] = {}
        for band in bands:
            lst = by_source.setdefault(band.source_id, [])
            if lst and lst[0].build_id != band.build_id:
                raise read_pg.IntegrityError(f"band 来源跨多个活动 build: {band.source_id}")
            lst.append(band)

        docs: list[BandDocument] = []
        for source_id, source_bands in by_source.items():
            build_id = source_bands[0].build_id
            ordered = chunk_order_by_source[source_id]
            chunks_by_band: list[tuple[BandEvidenceItem, ...]] = []
            cells: list[EmittedCell] = []
            for band in source_bands:
                items: list[BandEvidenceItem] = []
                for p in range(band.start, band.end + 1):
                    cid = ordered[p]
                    ev = ev_by_key.get((build_id, cid))
                    if ev is None:
                        raise read_pg.IntegrityError(
                            f"band 带内块缺失（装配）: {build_id[:12]}…/{cid}"
                        )
                    items.append(
                        BandEvidenceItem(
                            chunk_id=ev.chunk_id,
                            title_text=ev.title_text,
                            section_path=ev.section_path,
                            text=ev.text,
                            pages=tuple(sorted({u.page for u in ev.units if u.page is not None})),
                        )
                    )
                    cells.extend(self._emit_cells(ev))
                chunks_by_band.append(tuple(items))
            docs.append(
                BandDocument(
                    source_id=source_id,
                    build_id=build_id,
                    doc_handle=read_pg.build_handle(build_id),
                    bands=tuple(source_bands),
                    chunks_by_band=tuple(chunks_by_band),
                    cells=tuple(cells),
                )
            )
        return docs

    def fetch_verbatim(self, doc_id: str, locator: str) -> ChunkEvidence:
        """按§7.2 句柄取回权威原文块（新链），失败即抛 :mod:`read_pg` 的拒绝类型。

        与 :meth:`fetch` 的差别：不吞异常——调用方（工具/verify/CLI）需要区分
        ``archive_required``（旧句柄）与"不存在"，而不是一律得到 None。
        """
        from plugins.corpus.preparation import read_pg

        if self.read_chain() != "new":
            raise read_pg.LegacyHandleError(
                f"目标库未承载新链（read_chain={self.read_chain()}），句柄 {doc_id!r} 不可取证"
            )
        return read_pg.fetch_verbatim(self._dsn, doc_id, locator, sandbox_db=_I2_SANDBOX_DB)

    def search(self, query: str, *, limit: int = 10) -> list[SearchHit]:
        q = (query or "").strip()
        if not q:
            return []
        if self.read_chain() == "new":
            # I2-8：检索只服务活动 build（PUBLISHED 指针），命中即§7.2 取证句柄。
            from plugins.corpus.preparation import read_pg

            raw_hits, chunk_order, _coverage = read_pg.search_with_coverage_bands(
                self._dsn,
                q,
                limit=max(limit, _SELECTION_POOL_MIN),
                sandbox_db=_I2_SANDBOX_DB,
            )
            # 生产默认（i0c-r4n U 决策）：band 选带 → 带内原文序块摊平为逐块命中。
            hits = self._selected_chunk_hits(raw_hits, chunk_order, limit)
            return [
                SearchHit(
                    doc_id=read_pg.build_handle(hit.build_id),
                    locator=read_pg.chunk_locator(hit.chunk_id),
                    title=hit.title_text
                    or (hit.section_path[-1] if hit.section_path else hit.chunk_id),
                    snippet=hit.snippet,
                    score=float(hit.score),
                    published=hit.published or "undated",
                    source_id=hit.source_id,
                    build_id=hit.build_id,
                    chunk_id=hit.chunk_id,
                )
                for hit in hits
            ]
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
                # I2-7：日期只来自 documents.published（metadata 唯一日期落点），
                # 禁止从 doc_id 前缀推断——doc_id 只是文件名派生的标识符。
                published=(r["published"].isoformat() if r.get("published") else "undated"),
            )
            for r in ranked
        ]

    def _active_build_units(self, source_id: str) -> list[dict[str, Any]]:
        """活动 build 的 ``corpus_units`` 投影（I2-7 基础读取迁移，R2）。

        读侧不再查旧 ``blocks``：经同一 ``self._connect()`` 连接访问新 corpus
        schema，取 ``corpus_publications.active_build_id`` 指向的 build 的全部单元
        （``raw_text`` 为权威原文，按 ``ordinal`` 排序）。返回
        ``[{seq, locator, text}]``，``locator`` 由 ``location.page/element`` 派生，
        供 ``document_text``/``fetch``/``blocks_of`` 复用。
        """
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT u.ordinal, u.location, u.raw_text "
                "FROM corpus.corpus_units u "
                "WHERE u.build_id = (SELECT p.active_build_id "
                "                    FROM corpus.corpus_publications p "
                "                    WHERE p.source_id = %s) "
                "ORDER BY u.ordinal",
                (source_id,),
            )
            rows = cur.fetchall()
        units: list[dict[str, object]] = []
        for row in rows:
            location = row["location"] if isinstance(row["location"], dict) else {}
            page = location.get("page")
            element = location.get("element")
            locator = element or (f"p{page}" if page is not None else None) or str(row["ordinal"])
            units.append(
                {
                    "seq": int(row["ordinal"]) if row["ordinal"] is not None else 0,
                    "locator": str(locator),
                    "text": str(row["raw_text"] or ""),
                }
            )
        return units

    def _active_report_publication(self, source_id: str) -> str | None:
        """活动 build 的研报发布日期（R4 唯一落点 = admission.report_publication）。

        读侧经 ``self._connect()`` 从 ``corpus_admissions.metadata_snapshot`` 取
        ``report_publication.value``，供 Evidence 投影的 ``published``（known_at
        兜底）；无活动 build 或日期 unknown 返回 None。
        """
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT a.metadata_snapshot->'report_publication'->>'value' AS published "
                "FROM corpus.corpus_publications p "
                "JOIN corpus.corpus_admissions a ON a.decision_id = p.current_decision_id "
                "WHERE p.source_id = %s",
                (source_id,),
            )
            row = cur.fetchone()
        if row is None or row["published"] is None:
            return None
        return str(row["published"])

    def fetch(self, doc_id: str, locator: str) -> FetchedBlock | None:
        from plugins.corpus.fetch import FetchedBlock  # 延迟导入，避免循环依赖

        if self.read_chain() == "new":
            # I2-8：句柄 = cv2:<build_id> + chunk:<chunk_id>；旧句柄抛 archive_required。
            evidence = self.fetch_verbatim(doc_id, locator)
            return FetchedBlock(doc_id=doc_id, seq=0, locator=locator, text=evidence.text)
        source_id = _source_id_from_cv2_handle(doc_id)
        if source_id is not None:
            # 新式版本化句柄：从活动 build 的 corpus_units 取回权威原文单元。
            for unit in self._active_build_units(source_id):
                if unit["locator"] == str(locator):
                    return FetchedBlock(
                        doc_id=doc_id,
                        seq=int(unit["seq"]),
                        locator=str(unit["locator"]),
                        text=str(unit["text"]),
                    )
            return None
        # 旧句柄：显式走旧 blocks 归档路径（I2-8 精确版本句柄/归档策略前保留）。
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
        if self.read_chain() == "new":
            # I2-8/RM-I28-1：文档级读取遵循**句柄绑定 build**（与块级同语义）；
            # 旧句柄 archive_required、撤销 = None（均非"合法空文档"），不静默换正文。
            from plugins.corpus.preparation import read_pg

            try:
                return read_pg.fetch_document(self._dsn, doc_id, sandbox_db=_I2_SANDBOX_DB).text
            except read_pg.ReadError:
                return None
        source_id = _source_id_from_cv2_handle(doc_id)
        if source_id is not None:
            units = self._active_build_units(source_id)
            return "\n".join(str(unit["text"]) for unit in units) if units else None
        # 旧句柄：显式走旧 blocks 归档路径（I2-8 归档策略前保留）。
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT string_agg(text, chr(10) ORDER BY seq) AS t FROM blocks WHERE doc_id = %s",
                (str(doc_id),),
            )
            row = cur.fetchone()
        return row["t"] if row and row["t"] else None

    def blocks_of(self, doc_id: str) -> list[DictRow]:
        """取一份文档的全部块（``seq`` / ``locator`` / ``text``）—— D2 抽取的输入。

        I2-7 基础读取迁移（R2）：新式 ``cv2:`` 句柄走 ``corpus_units``；旧句柄
        显式走旧 blocks 归档路径。
        """
        source_id = _source_id_from_cv2_handle(doc_id)
        if source_id is not None:
            return [  # type: ignore[return-value]
                cast("DictRow", unit) for unit in self._active_build_units(source_id)
            ]
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT seq, locator, text FROM blocks WHERE doc_id = %s ORDER BY seq",
                (str(doc_id),),
            )
            return list(cur.fetchall())

    def fetch_cell(
        self, doc_id: str, *, row: int, col: int, page: int | None = None
    ) -> CellEvidence:
        """按 (页, 行, 列) 取权威单元格原文（I2-6 authority：错 cell 必须拒绝）。"""
        from plugins.corpus.preparation import read_pg

        if self.read_chain() != "new":
            raise read_pg.IntegrityError(
                "目标库未承载新链，无法按 cell 坐标取权威原文（不回退旧 blocks表）"
            )
        return read_pg.fetch_cell(
            self._dsn, doc_id, row=row, col=col, page=page, sandbox_db=_I2_SANDBOX_DB
        )

    def verify_evidence_against_authority(self, run: EvidenceRun) -> None:
        """把证据副本与**权威集合**比对（I2-6 authority）。

        副本自带的 ``verify_identity`` 只能证明"自身未被改坏"；此处另行核验它对
        权威正文的投影指纹（``parse_rev`` = f(source_id, 投影版本, units 文本序列)）
        与当前 ``corpus_units`` 是否一致——篡改 JSONB 副本、或拿旧/别的内容冒称
        权威正文，都在此拒绝，而不是回退到"看起来可用"的副本。
        """
        from plugins.corpus.evidence_pipeline import UNITS_PROJECTION_VERSION, fingerprint

        if self.read_chain() != "new":
            return
        source_id = str(run.document.source_rev)
        units = self._active_build_units(source_id)
        texts = [str(unit["text"]) for unit in units]
        expected = fingerprint([source_id, UNITS_PROJECTION_VERSION, texts])
        if not units or expected != run.document.parse_rev:
            from plugins.corpus.preparation import read_pg

            raise read_pg.IntegrityError(
                "证据副本与权威集合不一致（units 指纹不符）：拒绝采用该副本，不以近似内容替代"
            )

    def save_evidence_run(self, run: EvidenceRun) -> str:
        """Persist a content-addressed shadow revision, without replacing legacy corpus rows."""
        from plugins.corpus.evidence_pipeline import EvidenceRun

        if not isinstance(run, EvidenceRun):
            raise TypeError("expected EvidenceRun")
        run.verify_identity()
        with self._lock, self._connect() as conn, conn.cursor() as cur:
            cur.execute(EVIDENCE_RUNS_SQL)
            cur.execute(
                "INSERT INTO corpus_evidence_runs (run_id,doc_id,source_rev,parse_rev,payload) "
                "VALUES (%s,%s,%s,%s,%s::jsonb) ON CONFLICT (run_id) DO NOTHING",
                (
                    run.run_id,
                    run.document.doc_id,
                    run.document.source_rev,
                    run.document.parse_rev,
                    run.model_dump_json(),
                ),
            )
        return run.run_id

    def load_evidence_run(self, run_id: str) -> EvidenceRun:
        """Fetch and validate the exact revision named by a calculation or evidence link."""
        from plugins.corpus.evidence_pipeline import EvidenceRun

        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT to_regclass('corpus_evidence_runs') AS relation")
            relation = cur.fetchone()
            if relation is None or relation["relation"] is None:
                raise KeyError(run_id)
            cur.execute("SELECT payload FROM corpus_evidence_runs WHERE run_id=%s", (run_id,))
            row = cur.fetchone()
        if row is None:
            raise KeyError(run_id)
        run = EvidenceRun.model_validate(row["payload"])
        run.verify_identity()
        if run.run_id != run_id:
            raise ValueError("stored evidence run ID mismatch")
        self.verify_evidence_against_authority(run)  # I2-6：副本必须与权威集合一致
        return run

    def fetch_evidence(self, run_id: str, packet_id: str) -> dict[str, object]:
        """Return exact source coordinates and content, rather than a search snippet."""
        run = self.load_evidence_run(run_id)
        return run.document.fetch(packet_id).model_dump(mode="json")

    def extract_claims(
        self,
        path: str | Path,
        *,
        pages: tuple[int, ...] | None = None,
        llm: Callable[[str], str] | None = None,
        model: str | None = None,
        max_prose_calls: int = 0,
        packet_chars: int = 2000,
        persist: bool = True,
    ) -> EvidenceRun:
        """Canonical extraction: source → verified evidence revision, never legacy tables.

        A positive prose budget explicitly enables model calls. Zero leaves prose deferred.
        No full-corpus selection or legacy fallback is implicit in this interface.

        I2-7（R1）：Evidence 由同源 ``corpus_units`` 投影（按 source_id 从活动 build
        取 raw_text），不再二次解析原文件生成独立权威正文——``parse_evidence`` 的
        PDF/DOCX/MD 解析退出 canonical 入口。标题由文件名派生（与 parse_evidence
        同口径）、主体由标题+正文确定、发布日期读 admission.report_publication（R4
        唯一落点）。
        """
        from plugins.corpus.claims import document_ticker
        from plugins.corpus.evidence import _title_from_filename
        from plugins.corpus.evidence_pipeline import build_evidence_run_from_units

        if max_prose_calls < 0 or not 100 <= packet_chars <= 2500 or pages == ():
            raise ValueError("invalid extraction budget, packet size or empty page selection")
        if max_prose_calls and llm is None:
            llm = build_default_llm()
            model = model or configured_model()
        source_path = Path(path)
        source_id = sha256_of_bytes(source_path.read_bytes())
        units = self._active_build_units(source_id)
        title = _title_from_filename(source_path)
        joined = "\n".join(str(unit["text"]) for unit in units)
        subject = document_ticker(title, [joined[:4000]])
        published = self._active_report_publication(source_id)
        run = build_evidence_run_from_units(
            source_id,
            units,
            title=title,
            subject=subject,
            published=published,
            llm=llm,
            model=model,
            max_prose_calls=max_prose_calls,
        )
        if persist:
            self.save_evidence_run(run)
        return run

    def understand_material(
        self,
        *,
        path: str | Path | None = None,
        evidence_run_id: str | None = None,
        pages: tuple[int, ...] | None = None,
        llm: Callable[[str], str] | None = None,
        model: str | None = None,
        max_calls: int = 0,
        packet_chars: int = 2000,
        material_type: MaterialType | None = None,
        persist_evidence: bool = False,
        staged_jsonl: bool = False,
        max_items_per_packet: int = 30,
        slot_protocol: bool = False,
        max_slots_per_batch: int = 8,
        extract_relations: bool = True,
        candidate_slot_ids: tuple[str, ...] | None = None,
    ) -> MaterialRun:
        """Build an R2 material view from a path or an exact saved evidence revision.

        A direct path does not ingest the source or persist its shadow EvidenceRun unless
        explicitly requested.  This keeps material semantics on the canonical evidence
        parser while allowing pre-ingestion acceptance samples.
        """
        from plugins.corpus.evidence_pipeline import build_evidence_run
        from plugins.corpus.material_semantics import extract_material_understanding

        if (path is None) == (evidence_run_id is None):
            raise ValueError("provide exactly one of path or evidence_run_id")
        if max_calls < 0 or max_items_per_packet < 1 or max_slots_per_batch < 1:
            raise ValueError("max_calls must be non-negative")
        if max_calls and llm is None:
            llm = build_default_llm()
            model = model or configured_model()
        if evidence_run_id is not None:
            evidence_run = self.load_evidence_run(evidence_run_id)
        else:
            if not 100 <= packet_chars <= 12000 or pages == ():
                raise ValueError("invalid material packet size or empty page selection")
            evidence_run = build_evidence_run(
                cast("Path", path),
                pages=pages,
                packet_chars=packet_chars,
            )
            if persist_evidence:
                self.save_evidence_run(evidence_run)
        return extract_material_understanding(
            evidence_run,
            llm=llm,
            max_calls=max_calls,
            material_type=material_type,
            staged_jsonl=staged_jsonl,
            max_items_per_packet=max_items_per_packet,
            slot_protocol=slot_protocol,
            max_slots_per_batch=max_slots_per_batch,
            extract_relations=extract_relations,
            candidate_slot_ids=candidate_slot_ids,
        )

    def claims_of(
        self,
        *,
        run_id: str,
        subject: str | None = None,
        kind: str | None = None,
        quality_status: str | None = "ok",
        purpose: str = "cite",
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, object]:
        """Read one exact evidence revision with usage gates and explicit coverage.

        ``audit`` may expose rejected rows; cite/compare/calculate enforce usable_for.
        Historical validation versions remain auditable, not computation-ready.
        Missing revisions raise KeyError; they never fall back to legacy claim tables.
        """
        from plugins.corpus.evidence_pipeline import project_claims

        return project_claims(
            self.load_evidence_run(run_id),
            subject=subject,
            kind=kind,
            quality_status=quality_status,
            purpose=purpose,
            limit=limit,
            offset=offset,
        )

    def claim_observation_projection(
        self,
        *,
        run_id: str,
        subject: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, object]:
        """Comparison-ready evidence only; quality=ok alone is insufficient."""
        return self.claims_of(
            run_id=run_id,
            subject=subject,
            purpose="compare",
            limit=limit,
            offset=offset,
        )

    def derive_claims(
        self,
        *,
        run_id: str,
        formula: str,
        input_ids: tuple[str, ...],
    ) -> Calculation:
        """Calculate against the same stored revision exposed by claims_of."""
        from plugins.corpus.derivation import derive
        from plugins.corpus.evidence_pipeline import validation_is_current

        run = self.load_evidence_run(run_id)
        if not validation_is_current(run):
            raise ValueError("validation_version_stale")
        return derive(run, formula, input_ids)

    def reconcile_claims(self, *, run_id: str) -> list[dict[str, Any]]:
        """Read-only financial basis review; historical evidence is not promoted."""
        from plugins.corpus.derivation import reconcile_net_margin

        return reconcile_net_margin(self.load_evidence_run(run_id))

    def claim_runs(
        self,
        *,
        doc_id: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, object]]:
        """Discover revisions, without selecting a supposedly complete/latest winner."""
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        sql = "SELECT payload FROM corpus_evidence_runs"
        params: list[object] = []
        if doc_id:
            sql += " WHERE doc_id=%s"
            params.append(doc_id)
        sql += " ORDER BY created_at DESC, run_id LIMIT %s"
        params.append(limit)
        from plugins.corpus.evidence_pipeline import EvidenceRun, claim_run_context

        with self._connect() as conn, conn.cursor() as cur:
            # Older databases with only legacy data have no evidence revisions yet.
            cur.execute("SELECT to_regclass('corpus_evidence_runs') AS relation")
            relation = cur.fetchone()
            if relation is None or relation["relation"] is None:
                return []
            cur.execute(cast(LiteralString, sql), params)
            runs = [EvidenceRun.model_validate(row["payload"]) for row in cur.fetchall()]
        return [claim_run_context(run) for run in runs]

    def extract_legacy_claims(
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

        **跨块去重**：仅合并主体、指标、期间、类型、原数值、单位与观察日均相同
        的重复观测。90.4% / 90.42% 等不同值保留为未决冲突，不能按页码裁决真伪；
        不同主体不互相覆盖。仅删除更早块的完全相同观测，缺指标或原数值不参与。
        下游不得直接把候选行相加；块内重复由 :func:`_dedup_claims` 先收一次。

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
                    # 只合并同主体、同坐标且原值相同的旧观测；保留不同值供冲突审计。
                    for claim in claims:
                        if claim.metric is None or claim.value_text is None:
                            continue
                        cur.execute(
                            "DELETE FROM claims WHERE doc_id = %s AND seq < %s "
                            "AND metric IS NOT DISTINCT FROM %s "
                            "AND period IS NOT DISTINCT FROM %s AND kind = %s "
                            "AND tickers @> %s::text[] AND tickers <@ %s::text[] "
                            "AND value_text IS NOT DISTINCT FROM %s "
                            "AND unit IS NOT DISTINCT FROM %s AND as_of IS NOT DISTINCT FROM %s",
                            (
                                str(doc_id),
                                int(seq),
                                claim.metric,
                                claim.period,
                                claim.kind,
                                list(claim.tickers),
                                list(claim.tickers),
                                claim.value_text,
                                claim.unit,
                                claim.as_of,
                            ),
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

    @staticmethod
    def _usage_delta(before: tuple[int, int], usage: dict[str, int]) -> tuple[int, int]:
        """单次 LLM 调用的 token 增量（``usage_sink`` 是跨调用累计值，相减即本次用量）。"""
        return (
            usage.get("prompt_tokens", 0) - before[0],
            usage.get("completion_tokens", 0) - before[1],
        )

    def average_block_seconds(self) -> float:
        """历史单块平均耗时（秒）——dry-run 预估用真实台账均值，无历史时回退 2.0。"""
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT AVG(duration_ms) AS avg_ms FROM claim_block_runs "
                "WHERE status = 'ok' AND duration_ms IS NOT NULL"
            )
            row = cur.fetchone()
        if row is None or row["avg_ms"] is None:
            return 2.0
        return float(row["avg_ms"]) / 1000.0

    def legacy_claims_of(
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
        "corpus_evidence_runs": (
            "run_id",
            "doc_id",
            "source_rev",
            "parse_rev",
            "payload",
            "created_at",
        ),
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
        # claims_v2 / claim_block_runs_v2 影子表已随 I2-7 消费者矩阵退役
        # （DDL 不再创建）；备份枚举必须与 init_db 同步，否则审计的
        # backup_coverage 会把「枚举了但库里没有」当漂移报出来。
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
            return sum(1 for _ in _iter_corpus_files(root))
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

    p_claims = sub.add_parser("extract-claims", help="源文件 → 新证据链；旧抽取须显式选择")
    p_claims.add_argument("--source", type=Path, help="新版：一个源文件，不隐式跑全库")
    p_claims.add_argument("--pages", type=int, nargs="+", help="新版：PDF 页码（从 1 开始）")
    p_claims.add_argument("--prose-calls", type=int, default=0, help="新版：正文调用上限，默认 0")
    p_claims.add_argument("--packet-chars", type=int, default=2000)
    extract_mode = p_claims.add_mutually_exclusive_group()
    extract_mode.add_argument("--legacy", action="store_true", help="兼容：显式写旧 claims 表")
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
    p_show_claims.add_argument("--run-id", help="新版：必须指定精确证据版本")
    p_show_claims.add_argument(
        "--purpose", choices=["cite", "compare", "calculate", "audit"], default="cite"
    )
    p_show_claims.add_argument("--offset", type=int, default=0)
    p_show_claims.add_argument("--doc", default=None)
    p_show_claims.add_argument("--ticker", default=None, help="按标的代码过滤，如 600519.SH")
    p_show_claims.add_argument(
        "--subject", default=None, help="subject 过滤；company 下等价于 ticker"
    )
    p_show_claims.add_argument("--kind", default=None, choices=["fact", "forecast", "opinion"])
    read_mode = p_show_claims.add_mutually_exclusive_group()
    read_mode.add_argument("--legacy", action="store_true", help="兼容：只读旧 claims 表")
    p_show_claims.add_argument(
        "--quality",
        default="ok",
        choices=["ok", "review", "rejected", "all"],
        help="质量状态过滤；默认 ok，all=包含 review/rejected",
    )
    p_show_claims.add_argument("--limit", type=int, default=50)
    p_show_claims.add_argument("--db", default=None)

    p_claim_runs = sub.add_parser("claim-runs", help="发现新证据版本及实际处理范围")
    p_claim_runs.add_argument("--doc", default=None)
    p_claim_runs.add_argument("--limit", type=int, default=20)
    p_claim_runs.add_argument("--db", default=None)

    p_derive = sub.add_parser("derive-claims", help="按同一证据版本和事实 IDs 复算")
    p_derive.add_argument("--run-id", required=True)
    p_derive.add_argument("--formula", required=True)
    p_derive.add_argument("--inputs", required=True, nargs="+")
    p_derive.add_argument("--db", default=None)

    p_reconcile = sub.add_parser("reconcile-claims", help="只读复核源净利率与明确公式的差异")
    p_reconcile.add_argument("--run-id", required=True)
    p_reconcile.add_argument("--db", default=None)

    p_evidence = sub.add_parser("claim-evidence", help="读取指定证据版本中的原文及坐标")
    p_evidence.add_argument("--run-id", required=True)
    p_evidence.add_argument("--packet-id", required=True)
    p_evidence.add_argument("--db", default=None)

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
    if args.cmd == "extract-claims":
        if args.legacy:
            if args.source or args.pages or args.prose_calls or args.packet_chars != 2000:
                parser.error("旧抽取不能混用 --source/--pages/--prose-calls/--packet-chars")
        else:
            if not args.source or args.doc or vars(args).get("limit") is not None or args.dry_run:
                parser.error("新抽取需要 --source；旧批处理参数须显式指定 --legacy")
            if args.prose_calls < 0 or not 100 <= args.packet_chars <= 2500:
                parser.error("--prose-calls 必须非负；--packet-chars 必须在 100—2500")
    if args.cmd == "claims":
        if args.legacy:
            if args.run_id or args.purpose != "cite" or args.offset:
                parser.error("旧查询不能混用新版 run-id/purpose/offset；旧表不提供计算许可")
        elif not args.run_id or args.doc:
            parser.error("新查询需要 --run-id；用 claim-runs --doc 查找版本，旧表须显式选择")
    svc = get_service(args.db)

    if args.cmd == "extract-claims":
        if not args.legacy:
            from plugins.corpus.evidence_pipeline import claim_run_context

            run = svc.extract_claims(
                args.source,
                pages=tuple(args.pages) if args.pages else None,
                max_prose_calls=args.prose_calls,
                packet_chars=args.packet_chars,
            )
            print(json.dumps(claim_run_context(run), ensure_ascii=False, indent=2))
            return 0 if run.summary()["complete"] else 1
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
            extract = svc.extract_legacy_claims
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
        if args.legacy:
            rows = svc.legacy_claims_of(
                doc_id=args.doc, ticker=args.ticker, kind=args.kind, limit=args.limit
            )
        else:
            result = svc.claims_of(
                run_id=args.run_id,
                subject=args.subject or args.ticker,
                kind=args.kind,
                quality_status=None if args.quality == "all" else args.quality,
                purpose=args.purpose,
                limit=args.limit,
                offset=args.offset,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
            return 0
        print(json.dumps(rows, ensure_ascii=False, indent=2, default=str))
        return 0

    if args.cmd == "claim-runs":
        print(
            json.dumps(
                svc.claim_runs(doc_id=args.doc, limit=args.limit), ensure_ascii=False, indent=2
            )
        )
        return 0

    if args.cmd == "derive-claims":
        calculation = svc.derive_claims(
            run_id=args.run_id,
            formula=args.formula,
            input_ids=tuple(args.inputs),
        )
        print(calculation.model_dump_json(indent=2))
        return 0

    if args.cmd == "reconcile-claims":
        print(json.dumps(svc.reconcile_claims(run_id=args.run_id), ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "claim-evidence":
        print(
            json.dumps(
                svc.fetch_evidence(args.run_id, args.packet_id),
                ensure_ascii=False,
                indent=2,
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
