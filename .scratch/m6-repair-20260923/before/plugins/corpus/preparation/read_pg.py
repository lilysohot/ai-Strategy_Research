"""I2-8 权威读取 Adapter：版本句柄 → 逐字原文 + coverage 三轴（架构 §4.2/§7.2/§7.3）。

读侧与写侧共享同一权威集合：``corpus_units.raw_text`` 是唯一可逐字引用的正文，
``corpus_chunks`` 只是检索投影。本模块把「句柄解析 → 归属校验 → 权威原文 → 定位
坐标」收敛在一处，消费者（corpus_search/corpus_fetch/verify/service/CLI）只经它读取，
不再各自拼 SQL，也不再回退旧 ``blocks``。

句柄契约（§7.2）：

- ``doc_id`` = ``cv2:<build_id>``——一个确切文档构建版本；稳定来源身份另放 ``source_id``。
- ``locator`` = ``chunk:<chunk_id>``——该 build 内的确切检索块。
- **跨发布取回原版本**：句柄绑定的 build 即使已不是活动版本，也返回该不可变 build 的原文，
  不静默切换到新版本；只有来源被撤销（当前准入非 in_scope）才拒绝。
- **旧/未知句柄不静默换正文**：无 ``cv2:`` 前缀的旧句柄（旧 doc_id 或文件名派生 ID）
  一律 :class:`LegacyHandleError`（``archive_required``），绝不拿新链内容顶替。

目标 fail-closed：与 :class:`PgStore` / :func:`search_pg.search_chunks` 同纪律——
``current_database`` 必须等于隔离库，目标实例含 ``apodex`` 库即判定为生产实例并拒绝。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # psycopg 是可选依赖（PG 读链路专属）：类型仅用于标注；实际连接在函数内惰性 import。
    import psycopg

    from plugins.corpus.preparation.contract import ResearchDomain
    from plugins.corpus.preparation.search_pg import SearchHit

from plugins.corpus.preparation.contract import sha256_of_bytes
from plugins.corpus.preparation.repository import StoreError

_SANDBOX_DB = "i2_sandbox_corpus"

_HANDLE_PREFIX = "cv2:"
_LOCATOR_PREFIX = "chunk:"
_SHA256_HEX = "0123456789abcdef"


class ReadError(ValueError):
    """读侧拒绝（fail-closed）：调用方必须能看到原因，不能拿到"看起来可用"的正文。"""


class LegacyHandleError(ReadError):
    """旧句柄：历史引用由离线归档解释（``archive_required``），不静默换正文。"""


class UnknownHandleError(ReadError):
    """句柄格式非法或指向不存在的对象（未知/跨 build/坏哈希均拒绝）。"""


class WithdrawnError(ReadError):
    """句柄指向的来源当前准入已撤销/排除，不得继续服务（§7.2 撤销与权限检查）。"""


class IntegrityError(ReadError):
    """权威集合自相矛盾（内容哈希不符 / 引用悬空 / 坐标不存在）。

    按 §4.2「冲突返回完整性错误，禁止回退到『看起来可用』副本」——这类情况绝不
    降级为"取其余部分"或空正文，调用方必须看到拒绝。
    """


@dataclass(frozen=True)
class UnitEvidence:
    """一块权威原文单元（逐字引用与定位的最小单位）。"""

    unit_id: str
    raw_text: str
    page: int | None
    element: str | None
    cells: tuple[tuple[int, ...], ...]


@dataclass(frozen=True)
class ChunkEvidence:
    """一次 fetch 的取证结果：逐字原文 + 版本身份 + 定位坐标。

    ``text`` 是该 chunk 引用单元 ``raw_text`` 的逐字拼接（不清洗、不摘要、不拼接展示）；
    引用区间一律用权威原文的 code point 偏移，不用清洗文本偏移（§4.2）。
    """

    source_id: str
    build_id: str
    chunk_id: str
    kind: str
    title_text: str | None
    section_path: tuple[str, ...]
    units: tuple[UnitEvidence, ...]
    text: str
    #: chunk 投影的来源区间（权威原文 code point，§4.2；来自 corpus_chunks.source_ranges）
    source_ranges: tuple[tuple[int, int], ...]
    #: 每个单元在 **本返回 text** 内的偏移 ``(unit_id, start, end)``——切片可复算出 text
    spans: tuple[tuple[str, int, int], ...]
    active: bool


@dataclass(frozen=True)
class CellEvidence:
    """按 (页, 行, 列) 取到的权威单元格（错 cell 必须拒绝，不猜邻格）。"""

    source_id: str
    build_id: str
    unit_id: str
    raw_text: str
    page: int | None
    element: str | None
    cells: tuple[tuple[int, ...], ...]


@dataclass(frozen=True)
class DocumentEvidence:
    """文档级权威正文（句柄所绑定 build 的全量单元，按 ``ordinal`` 排序）。

    ``text`` 是各单元 ``raw_text`` 的**确定性 ``"\\n"`` 拼接**（RM-FC-5）：
    逐字性按**单元**成立——每个单元原文逐字出自源文件，但**拼接结果不是原文件的
    字节还原**（源文件中的空行分隔在拼接中不保留，源 ``A\\n\\nB`` → 文本 ``A\\nB``）。
    因此：① 不得把 ``text`` 当原文切片做逐字引文；② 跨单元引文必须按单元取证
    （块级用 :func:`fetch_verbatim` 的 ``units``/``spans``，文档级用 ``build_id``
    定位单元）；③ 需要「原文空行/排版」的场景应直接读源归档，不读本字段。
    """

    source_id: str
    build_id: str
    text: str


def parse_build_handle(doc_id: str) -> str:
    """解析 ``cv2:<build_id>``；旧句柄与非十六进制一律拒绝（不猜测、不兜底）。"""
    if not isinstance(doc_id, str) or not doc_id.startswith(_HANDLE_PREFIX):
        raise LegacyHandleError(
            f"旧句柄 {doc_id!r}：新链不以其取正文，历史引用请走归档解释（archive_required）"
        )
    build_id = doc_id[len(_HANDLE_PREFIX) :]
    if len(build_id) != 64 or any(c not in _SHA256_HEX for c in build_id):
        raise UnknownHandleError(f"句柄 build_id 非法（须 64 位十六进制 SHA-256）: {doc_id!r}")
    return build_id


def parse_chunk_locator(locator: str) -> str:
    """解析 ``chunk:<chunk_id>``；其余定位符（页码/标题）在新链下不是取证句柄。"""
    if not isinstance(locator, str) or not locator.startswith(_LOCATOR_PREFIX):
        raise UnknownHandleError(f"locator 必须是 {_LOCATOR_PREFIX!r} 形式的取证句柄: {locator!r}")
    chunk_id = locator[len(_LOCATOR_PREFIX) :]
    if not chunk_id:
        raise UnknownHandleError(f"locator 缺少 chunk_id: {locator!r}")
    return chunk_id


def build_handle(build_id: str) -> str:
    return f"{_HANDLE_PREFIX}{build_id}"


def chunk_locator(chunk_id: str) -> str:
    return f"{_LOCATOR_PREFIX}{chunk_id}"


def _check_target(conn: psycopg.Connection, sandbox_db: str) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT current_database()")
        row = cur.fetchone()
        if row is None or row[0] != sandbox_db:
            raise StoreError(f"拒绝：current_database={row[0] if row else None!r} ≠ {sandbox_db!r}")
        cur.execute("SELECT datname FROM pg_database WHERE datallowconn")
        dbs = {r[0] for r in cur.fetchall()}
    if "apodex" in dbs:
        raise StoreError("拒绝：目标实例含 apodex 库——判定为生产实例，禁止读取")


_CHUNK_SQL = """
SELECT c.build_id, c.chunk_id, c.kind, c.title_text, c.section_path, c.unit_refs,
       c.source_ranges, b.source_id, b.decision_id,
       (p.active_build_id IS NOT NULL AND p.active_build_id = c.build_id) AS active,
       COALESCE(a.decision, '') AS decision
FROM corpus.corpus_chunks c
JOIN corpus.corpus_builds b ON b.build_id = c.build_id
LEFT JOIN corpus.corpus_publications p ON p.source_id = b.source_id
LEFT JOIN corpus.corpus_admissions a ON a.decision_id = p.current_decision_id
WHERE c.build_id = %(build_id)s AND c.chunk_id = %(chunk_id)s
"""

_UNITS_SQL = """
SELECT unit_id, raw_text, location, content_hash
FROM corpus.corpus_units
WHERE build_id = %(build_id)s AND unit_id = ANY(%(unit_ids)s)
ORDER BY ordinal NULLS LAST, unit_id
"""


def fetch_verbatim(
    dsn: str,
    doc_id: str,
    locator: str,
    *,
    sandbox_db: str = _SANDBOX_DB,
) -> ChunkEvidence:
    """按版本句柄取回**逐字**权威原文（§7.2：跨发布仍读原 build，撤销才拒绝）。"""
    import psycopg

    build_id = parse_build_handle(doc_id)
    chunk_id = parse_chunk_locator(locator)
    with psycopg.connect(dsn, autocommit=True) as conn:
        _check_target(conn, sandbox_db)
        with conn.cursor() as cur:
            cur.execute(_CHUNK_SQL, {"build_id": build_id, "chunk_id": chunk_id})
            row = cur.fetchone()
            if row is None:
                raise UnknownHandleError(f"句柄不存在或跨 build：({build_id[:12]}…, {chunk_id})")
            decision = row[10]
            if decision and decision != "in_scope":
                raise WithdrawnError(
                    f"来源当前准入为 {decision!r}，活动版本已撤下，不得继续服务该句柄"
                )
            unit_ids = list(row[5] or ())
            units: list[UnitEvidence] = []
            if unit_ids:
                cur.execute(_UNITS_SQL, {"build_id": build_id, "unit_ids": unit_ids})
                for unit_id, raw_text, location, content_hash in cur.fetchall():
                    text = str(raw_text or "")
                    # §4.2：权威单元必须自证——内容哈希不符即完整性错误（疑似篡改），
                    # 不得把被改过的正文当原文返回。
                    if sha256_of_bytes(text.encode()) != str(content_hash or ""):
                        raise IntegrityError(
                            f"权威单元内容哈希不符（疑似篡改）: {unit_id} @ {build_id[:12]}…"
                        )
                    loc = location if isinstance(location, dict) else {}
                    cells = tuple(tuple(int(v) for v in cell) for cell in (loc.get("cells") or ()))
                    units.append(
                        UnitEvidence(
                            unit_id=str(unit_id),
                            raw_text=text,
                            page=loc.get("page"),
                            element=loc.get("element"),
                            cells=cells,
                        )
                    )
                resolved = {unit.unit_id for unit in units}
                missing = [ref for ref in unit_ids if ref not in resolved]
                if missing:
                    # 引用悬空 = 权威集合不完整：拒绝，不返回"其余部分"当完整原文。
                    raise IntegrityError(
                        f"chunk 引用了不存在的单元（权威集合不完整）: {missing} @ {build_id[:12]}…"
                    )
    source_ranges = tuple((int(span[0]), int(span[1])) for span in (row[6] or ()))
    spans: list[tuple[str, int, int]] = []
    offset = 0
    for index, unit in enumerate(units):
        if index:
            offset += 1  # text 以 "\n" 连接各单元
        spans.append((unit.unit_id, offset, offset + len(unit.raw_text)))
        offset += len(unit.raw_text)
    return ChunkEvidence(
        source_id=str(row[7]),
        build_id=str(row[0]),
        chunk_id=str(row[1]),
        kind=str(row[2] or ""),
        title_text=row[3],
        section_path=tuple(row[4] or ()),
        units=tuple(units),
        text="\n".join(unit.raw_text for unit in units),
        source_ranges=source_ranges,
        spans=tuple(spans),
        active=bool(row[9]),
    )


_DOC_SQL = """
SELECT u.raw_text, u.content_hash, u.unit_id
FROM corpus.corpus_units u
WHERE u.build_id = %(build_id)s
ORDER BY u.ordinal NULLS LAST, u.unit_id
"""

_SOURCE_SCOPE_SQL = """
SELECT COALESCE(a.decision, '') AS decision
FROM corpus.corpus_sources s
LEFT JOIN corpus.corpus_admissions a ON a.decision_id = s.current_decision_id
WHERE s.source_id = %(source_id)s
"""


def fetch_document(
    dsn: str,
    doc_id: str,
    *,
    sandbox_db: str = _SANDBOX_DB,
) -> DocumentEvidence:
    """取**句柄所绑定 build** 的全文（§7.2：文档级与块级同一版本语义）。

    跨发布后 ``cv2:<A>`` 仍返回 A 的正文，**不静默切换**到新的活动版本
    （RM-I28-1 裁定 A：引用必须绑定 build；`build_id` 字段即实际读取的 build）；
    来源被撤销/排除时抛 :class:`WithdrawnError`（与块级同信号，不以空串冒充
    "合法空文档"）。

    文本语义见 :class:`DocumentEvidence`：``text`` 是单元 ``raw_text`` 的 ``"\\n"``
    拼接，**不是源文件的字节还原**（跨单元引文必须按单元取证；RM-FC-5）。
    """
    import psycopg

    build_id = parse_build_handle(doc_id)
    with psycopg.connect(dsn, autocommit=True) as conn:
        _check_target(conn, sandbox_db)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT source_id FROM corpus.corpus_builds WHERE build_id = %(build_id)s",
                {"build_id": build_id},
            )
            build_row = cur.fetchone()
            if build_row is None:
                raise UnknownHandleError(f"build 不存在: {build_id[:12]}…")
            source_id = str(build_row[0])
            cur.execute(_SOURCE_SCOPE_SQL, {"source_id": source_id})
            scope_row = cur.fetchone()
            decision = str(scope_row[0]) if scope_row and scope_row[0] else ""
            if decision and decision != "in_scope":
                raise WithdrawnError(
                    f"来源当前准入为 {decision!r}，活动版本已撤下，不得继续服务该句柄"
                )
            cur.execute(_DOC_SQL, {"build_id": build_id})
            rows = cur.fetchall()
    for raw_text, content_hash, unit_id in rows:
        text = str(raw_text or "")
        if sha256_of_bytes(text.encode()) != str(content_hash or ""):
            raise IntegrityError(f"权威单元内容哈希不符（疑似篡改）: {unit_id} @ {build_id[:12]}…")
    return DocumentEvidence(
        source_id=source_id,
        build_id=build_id,
        text="\n".join(str(r[0] or "") for r in rows),
    )


_CELL_SQL = """
SELECT unit_id, raw_text, location, content_hash
FROM corpus.corpus_units
WHERE build_id = %(build_id)s
  AND location->'cells' @> %(cell)s::jsonb
  AND (%(page)s::int IS NULL OR (location->>'page')::int = %(page)s::int)
ORDER BY ordinal NULLS LAST, unit_id
"""


def fetch_cell(
    dsn: str,
    doc_id: str,
    *,
    row: int,
    col: int,
    page: int | None = None,
    sandbox_db: str = _SANDBOX_DB,
) -> CellEvidence:
    """按 (页, 行, 列) 取权威单元格原文（§4.2：cell 坐标也是引用绑定的一部分）。

    错 cell（不存在）、定位不唯一（命中多个单元）或内容哈希不符一律拒绝——不猜
    邻格、不取"最接近"的单元。
    """
    import json as _json

    import psycopg

    build_id = parse_build_handle(doc_id)
    with psycopg.connect(dsn, autocommit=True) as conn:
        _check_target(conn, sandbox_db)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT source_id FROM corpus.corpus_builds WHERE build_id = %(build_id)s",
                {"build_id": build_id},
            )
            build_row = cur.fetchone()
            if build_row is None:
                raise UnknownHandleError(f"build 不存在: {build_id[:12]}…")
            source_id = str(build_row[0])
            cur.execute(_SOURCE_SCOPE_SQL, {"source_id": source_id})
            scope_row = cur.fetchone()
            decision = str(scope_row[0]) if scope_row and scope_row[0] else ""
            if decision and decision != "in_scope":
                raise WithdrawnError(
                    f"来源当前准入为 {decision!r}，活动版本已撤下，不得继续服务该句柄"
                )
            cur.execute(
                _CELL_SQL,
                {
                    "build_id": build_id,
                    "cell": _json.dumps([[int(row), int(col)]]),
                    "page": page,
                },
            )
            rows = cur.fetchall()
    if not rows:
        raise UnknownHandleError(
            f"该 build 不含坐标 (page={page}, row={row}, col={col}) 的单元（错 cell 拒绝）"
        )
    if len(rows) > 1:
        raise IntegrityError(
            f"坐标 (page={page}, row={row}, col={col}) 命中 {len(rows)} 个单元，定位不唯一"
        )
    unit_id, raw_text, location, content_hash = rows[0]
    text = str(raw_text or "")
    if sha256_of_bytes(text.encode()) != str(content_hash or ""):
        raise IntegrityError(f"权威单元内容哈希不符（疑似篡改）: {unit_id}")
    loc = location if isinstance(location, dict) else {}
    return CellEvidence(
        source_id=source_id,
        build_id=build_id,
        unit_id=str(unit_id),
        raw_text=text,
        page=loc.get("page"),
        element=loc.get("element"),
        cells=tuple(tuple(int(v) for v in cell) for cell in (loc.get("cells") or ())),
    )


_COVERAGE_SQL = """
SELECT
  (SELECT count(*) FROM corpus.corpus_sources) AS sources,
  (SELECT count(*) FROM corpus.corpus_publications
     WHERE active_build_id IS NOT NULL) AS published,
  (SELECT count(*) FROM corpus.corpus_publications p
     JOIN corpus.corpus_admissions a ON a.decision_id = p.current_decision_id
     WHERE a.decision <> 'in_scope') AS withdrawn,
  (SELECT count(*) FROM corpus.corpus_sources s
     LEFT JOIN corpus.corpus_admissions a
            ON a.decision_id = s.current_decision_id
     WHERE a.decision_id IS NULL OR a.decision = 'review_required') AS pending,
  (SELECT count(*) FROM (
      SELECT build_id, stage FROM corpus.corpus_jobs
      GROUP BY build_id, stage
      HAVING bool_and(state = 'failed')) AS f) AS failed_jobs,
  (SELECT count(*) FROM corpus.corpus_builds) AS builds,
  (SELECT COALESCE(md5(string_agg(
        s.source_id || ':' || COALESCE(p.active_build_id, '') || ':' ||
        COALESCE(p.generation, 0)::text,
        ',' ORDER BY s.source_id)), md5('empty'))
   FROM corpus.corpus_sources s
   LEFT JOIN corpus.corpus_publications p ON p.source_id = s.source_id)
    AS publication_snapshot_ref,
  (SELECT count(*)
     FROM corpus.corpus_publications p
     JOIN corpus.corpus_builds b ON b.build_id = p.active_build_id
    WHERE p.active_build_id IS NOT NULL
      AND CASE WHEN jsonb_typeof(b.quality_report -> 'gap_regions') = 'array'
               THEN jsonb_array_length(b.quality_report -> 'gap_regions')
               ELSE 0 END > 0) AS published_with_gaps
"""


def _coverage_from_row(row: tuple, query_status: str) -> dict[str, object]:
    sources = int(row[0])
    published = int(row[1])
    withdrawn = int(row[2])
    pending = int(row[3])
    failed_jobs = int(row[4])
    builds = int(row[5])
    snapshot_ref = str(row[6])
    published_with_gaps = int(row[7])

    reason_codes: list[str] = []
    if sources == 0:
        reason_codes.append("empty_corpus")
    if pending:
        reason_codes.append("admission_pending")
    if failed_jobs:
        reason_codes.append("build_failed")
    if withdrawn:
        reason_codes.append("withdrawn_sources")
    if published and published < sources:
        reason_codes.append("partial_published")
    if published_with_gaps:
        # RM-FC-0：活动 build 的缺口台账非空 ⇒ 已发布集合只是请求范围的**真子集**
        # （缺口清单即「剩余范围」，由 check/status 的 gaps 机读返回）。
        reason_codes.append("gap_regions_present")

    if sources == 0:
        processing = "unknown"
    elif pending or failed_jobs:
        processing = "unknown"  # 未决/故障优先于 scoped（§7.3）
    elif published == 0:
        processing = "unknown"
    elif published < sources - withdrawn or published_with_gaps:
        processing = "scoped"
    else:
        processing = "full"

    availability = "available" if query_status == "matched" and processing == "full" else "unknown"

    return {
        "requested_scope_ref": "corpus_schema",
        "effective_scope_ref": "corpus_publications.active_build_id",
        # §7.3 必带：当前发布时点的稳定引用（与 counts 同一条 SQL 求值 ⇒ 同一快照），
        # 由 (source_id, active_build_id, generation) 的全集指纹构成；发布/撤销改变它。
        "publication_snapshot_ref": f"corpus_publications@{snapshot_ref}",
        "processing": processing,
        "query_status": query_status,
        "availability": availability,
        "reason_codes": tuple(reason_codes),
        "counts": {
            "sources": sources,
            "published": published,
            "withdrawn": withdrawn,
            "pending": pending,
            "failed_jobs": failed_jobs,
            "builds": builds,
            "published_with_gaps": published_with_gaps,
        },
    }


def coverage_snapshot_on(
    cur: psycopg.Cursor, *, query_status: str = "unknown"
) -> dict[str, object]:
    """在调用方给定游标/事务内取覆盖快照（供同快照组合读取复用）。"""
    cur.execute(_COVERAGE_SQL)
    row = cur.fetchone()
    if row is None:  # 聚合查询恒返回一行；缺行属不可读，按 fail-closed 处理
        raise StoreError("覆盖统计不可读（聚合查询无返回行）")
    return _coverage_from_row(row, query_status)


def coverage_snapshot(
    dsn: str,
    *,
    sandbox_db: str = _SANDBOX_DB,
    query_status: str = "unknown",
) -> dict[str, object]:
    """§7.3 三轴覆盖快照（不把 no_match 自动当 absent，failed 恒 unknown）。

    RM-FC-0：活动 build 的缺口台账非空时，已发布集合只是请求范围的**真子集** ⇒
    ``processing=scoped`` 且 ``reason_codes`` 含 ``gap_regions_present``（缺口清单
    即「剩余范围」，由 ``corpus-check``/``corpus-status`` 的 ``gaps`` 机读返回）。
    未决/失败/零发布仍优先 ``unknown``。判定只依赖「台账是否非空」这一结构性事实，
    不复制缺口分级表（分级口径只在 :mod:`plugins.corpus.preparation.gaps`）。
    """
    import psycopg

    with psycopg.connect(dsn, autocommit=True) as conn:
        _check_target(conn, sandbox_db)
        with conn.cursor() as cur:
            return coverage_snapshot_on(cur, query_status=query_status)


def search_with_coverage(
    dsn: str,
    query: str,
    *,
    sandbox_db: str = _SANDBOX_DB,
    domain: ResearchDomain | None = None,
    published_from: str | None = None,
    published_to: str | None = None,
    limit: int = 20,
) -> tuple[tuple[SearchHit, ...], dict[str, object]]:
    """同一数据库快照内取「检索命中 + 覆盖元数据」（§7.3 并发发布一致性要求）。

    两条查询在**同一个 REPEATABLE READ 事务**内执行：并发发布/撤销发生在事务之外
    时，命中与 coverage 要么都看到旧状态、要么都看到新状态，不会出现
    「coverage 说没有已发布来源，却返回了命中」这类拼接自不同时刻的结果。
    """
    import psycopg

    from plugins.corpus.preparation.search_pg import build_search_params, search_chunks_on

    params = build_search_params(
        query,
        domain=domain,
        published_from=published_from,
        published_to=published_to,
        limit=limit,
    )
    with psycopg.connect(dsn, autocommit=True) as conn:
        _check_target(conn, sandbox_db)
        with conn.transaction(), conn.cursor() as cur:
            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            hits = search_chunks_on(cur, params)
            coverage = coverage_snapshot_on(cur, query_status="matched" if hits else "no_match")
    return hits, coverage


_BAND_CHUNK_ORDER_SQL = """
SELECT c.build_id, c.chunk_id, c.unit_refs
FROM corpus.corpus_chunks c
WHERE c.build_id = ANY(%(build_ids)s::text[])
"""
_BAND_CHUNK_UNITS_ORDINAL_SQL = """
SELECT build_id, unit_id, ordinal
FROM corpus.corpus_units
WHERE build_id = ANY(%(build_ids)s::text[])
"""


def _chunk_order_by_source_on(
    cur: psycopg.Cursor, hits: tuple[SearchHit, ...]
) -> dict[str, tuple[str, ...]]:
    """同快照批量装配 ``{source_id: 该来源活动 build 的原文序全量块 id}``。

    原文序 = 按该块全部引用单元的最小 ``ordinal`` 升序（与 fetch_verbatim 的权威
    单元序同口径；禁 N+1：每个 build 一次 chunks + 一次 units）。命中涉及的每个
    build 都返回**全量**块，select_band 按需投影——缺块即 fail-closed。
    """
    if not hits:
        return {}
    build_ids = sorted({hit.build_id for hit in hits})
    build_to_source: dict[str, str] = {}
    for hit in hits:
        prev = build_to_source.get(hit.build_id)
        if prev is not None and prev != hit.source_id:
            raise IntegrityError(f"同一 build 归属多个来源（活跃发布不一致）: {hit.build_id[:12]}…")
        build_to_source[hit.build_id] = hit.source_id
    cur.execute(_BAND_CHUNK_ORDER_SQL, {"build_ids": build_ids})
    chunks_by_build: dict[str, list[tuple[str, tuple[str, ...]]]] = {}
    for build_id, chunk_id, unit_refs in cur.fetchall():
        chunks_by_build.setdefault(str(build_id), []).append(
            (str(chunk_id), tuple(refs for refs in (unit_refs or ())))
        )
    cur.execute(_BAND_CHUNK_UNITS_ORDINAL_SQL, {"build_ids": build_ids})
    ordinal_by_unit: dict[tuple[str, str], int] = {}
    for build_id, unit_id, ordinal in cur.fetchall():
        if ordinal is not None:
            ordinal_by_unit[(str(build_id), str(unit_id))] = int(ordinal)

    def min_ordinal(build_id: str, refs: tuple[str, ...]) -> int:
        vals = [
            ordinal_by_unit[(build_id, ref)] for ref in refs if (build_id, ref) in ordinal_by_unit
        ]
        return min(vals) if vals else 10**9

    result: dict[str, tuple[str, ...]] = {}
    for build_id, source_id in build_to_source.items():
        rows = chunks_by_build.get(build_id, [])
        rows = [(cid, min_ordinal(build_id, refs)) for cid, refs in rows]
        rows.sort(key=lambda r: r[1])  # 稳定排序：min ordinal 升序，同值保留 DB 序
        result[source_id] = tuple(cid for cid, _ in rows)
    return result


def search_with_coverage_bands(
    dsn: str,
    query: str,
    *,
    sandbox_db: str = _SANDBOX_DB,
    domain: ResearchDomain | None = None,
    published_from: str | None = None,
    published_to: str | None = None,
    limit: int = 20,
) -> tuple[tuple[SearchHit, ...], dict[str, tuple[str, ...]], dict[str, object]]:
    """同一数据库快照内取「检索命中 + 覆盖元数据 + band 原文序块清单」。

    供 band 选择（§10.5 选项 A）在同快照内取得命中块对应的原文位置投影
    （``chunk_order_by_source``）：三条查询在**同一个 REPEATABLE READ 事务**内
    执行，命中、覆盖与块序不可能拼接自不同时刻。返回 (hits, chunk_order, coverage)；
    ``chunk_order`` 每个来源都是该来源活动 build 的**全量**原文序块 id。
    """
    import psycopg

    from plugins.corpus.preparation.search_pg import build_search_params, search_chunks_on

    params = build_search_params(
        query,
        domain=domain,
        published_from=published_from,
        published_to=published_to,
        limit=limit,
    )
    with psycopg.connect(dsn, autocommit=True) as conn:
        _check_target(conn, sandbox_db)
        with conn.transaction(), conn.cursor() as cur:
            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            hits = search_chunks_on(cur, params)
            coverage = coverage_snapshot_on(cur, query_status="matched" if hits else "no_match")
            chunk_order = _chunk_order_by_source_on(cur, hits)
    return hits, chunk_order, coverage


_BANDS_CHUNK_SQL = """
SELECT c.build_id, c.chunk_id, c.kind, c.title_text, c.section_path, c.unit_refs,
       c.source_ranges, b.source_id, b.decision_id,
       (p.active_build_id IS NOT NULL AND p.active_build_id = c.build_id) AS active,
       COALESCE(a.decision, '') AS decision
FROM corpus.corpus_chunks c
JOIN corpus.corpus_builds b ON b.build_id = c.build_id
LEFT JOIN corpus.corpus_publications p ON p.source_id = b.source_id
LEFT JOIN corpus.corpus_admissions a ON a.decision_id = p.current_decision_id
WHERE c.build_id = ANY(%(build_ids)s::text[])
  AND c.chunk_id = ANY(%(chunk_ids)s::text[])
"""
_BANDS_UNITS_SQL = """
SELECT build_id, unit_id, raw_text, location, content_hash, ordinal
FROM corpus.corpus_units
WHERE (build_id, unit_id) IN (
    SELECT b, u FROM unnest(%(build_ids)s::text[], %(unit_ids)s::text[]) AS x(b, u)
)
"""


def fetch_bands(
    dsn: str,
    bands: tuple,
    chunk_order_by_source: dict[str, tuple[str, ...]],
    *,
    sandbox_db: str = _SANDBOX_DB,
) -> tuple[ChunkEvidence, ...]:
    """批量取回选中带内全部块的逐字证据（同一批 SQL，禁 N+1）。

    每个带按 ``chunk_order_by_source`` 把闭区间 [start, end] 投影为块 id；所有带
    的块合并取回：一次 chunks + 一次 units（按引用单元并集）。返回按「带序 × 带内
    原文序」的有序列表。band 对象只需携带 ``source_id``/``build_id``/``start``/``end``。
    """
    import psycopg

    wanted: dict[tuple[str, str], str] = {}  # (build_id, chunk_id) -> build_id
    for band in bands:
        ordered = chunk_order_by_source.get(band.source_id)
        if ordered is None or band.end >= len(ordered) or band.start < 0:
            raise IntegrityError(
                f"band 区间超出来源原文序清单: {band.source_id} [{band.start},{band.end}]"
            )
        for p in range(band.start, band.end + 1):
            wanted[(band.build_id, ordered[p])] = band.build_id
    if not wanted:
        return ()

    build_ids = sorted({bid for _, bid in wanted.items()})
    chunk_ids = sorted({cid for _, cid in wanted})

    with psycopg.connect(dsn, autocommit=True) as conn:
        _check_target(conn, sandbox_db)
        with conn.cursor() as cur:
            cur.execute(
                _BANDS_CHUNK_SQL,
                {"build_ids": build_ids, "chunk_ids": chunk_ids},
            )
            chunk_rows = cur.fetchall()
            unit_ids_by_chunk: dict[tuple[str, str], list[str]] = {}
            for row in chunk_rows:
                bid = str(row[0])
                cid = str(row[1])
                unit_ids_by_chunk[(bid, cid)] = [str(u) for u in (row[5] or ())]
            for key in wanted:
                if key not in unit_ids_by_chunk:
                    raise IntegrityError(f"band 带内块缺失: {key}")
            pairs = [(bid, uid) for (bid, cid), uids in unit_ids_by_chunk.items() for uid in uids]
            unit_ids: list[str] = [p[1] for p in pairs]
            pair_builds: list[str] = [p[0] for p in pairs]
            units_by_chunk: dict[tuple[str, str], list[tuple]] = {}
            if pairs:
                cur.execute(
                    _BANDS_UNITS_SQL,
                    {"build_ids": pair_builds, "unit_ids": unit_ids},
                )
                units_by_id: dict[tuple[str, str], tuple] = {
                    (str(r[0]), str(r[1])): r for r in cur.fetchall()
                }
                for (bid, cid), uids in unit_ids_by_chunk.items():
                    rows = []
                    for uid in uids:
                        r = units_by_id.get((bid, uid))
                        if r is None:
                            raise IntegrityError(f"band 块引用悬空单元: {bid[:12]}…/{cid}/{uid}")
                        rows.append(r)
                    # ordinal NULLS LAST, unit_id
                    rows.sort(
                        key=lambda r: (
                            1 if r[5] is None else 0,
                            r[5] if r[5] is not None else -1,
                            str(r[1]),
                        )
                    )
                    units_by_chunk[(bid, cid)] = rows
    by_key = {
        key: row
        for key, row in zip([(str(r[0]), str(r[1])) for r in chunk_rows], chunk_rows, strict=True)
    }
    out: list[ChunkEvidence] = []
    seen: set[tuple[str, str]] = set()
    for band in bands:
        ordered = chunk_order_by_source[band.source_id]
        for p in range(band.start, band.end + 1):
            bid = band.build_id
            cid = ordered[p]
            key = (bid, cid)
            if key in seen:
                continue
            seen.add(key)
            out.append(_assemble_chunk_evidence(bid, cid, by_key[key], units_by_chunk.get(key, [])))
    return tuple(out)


def _assemble_chunk_evidence(
    build_id: str,
    chunk_id: str,
    chunk_row: tuple,
    unit_rows: list[tuple],
) -> ChunkEvidence:
    """把批量 chunk/unit 行装配为 :class:`ChunkEvidence`（语义同 fetch_verbatim）。"""
    decision = chunk_row[10]
    if decision and decision != "in_scope":
        raise WithdrawnError(f"来源当前准入为 {decision!r}，活动版本已撤下，不得继续服务该句柄")
    units: list[UnitEvidence] = []
    for _build_id, unit_id, raw_text, location, content_hash, _ordinal in unit_rows:
        text = str(raw_text or "")
        if sha256_of_bytes(text.encode()) != str(content_hash or ""):
            raise IntegrityError(f"权威单元内容哈希不符（疑似篡改）: {unit_id} @ {build_id[:12]}…")
        loc = location if isinstance(location, dict) else {}
        cells = tuple(tuple(int(v) for v in cell) for cell in (loc.get("cells") or ()))
        units.append(
            UnitEvidence(
                unit_id=str(unit_id),
                raw_text=text,
                page=loc.get("page"),
                element=loc.get("element"),
                cells=cells,
            )
        )
    source_ranges = tuple((int(span[0]), int(span[1])) for span in (chunk_row[6] or ()))
    spans: list[tuple[str, int, int]] = []
    offset = 0
    for index, unit in enumerate(units):
        if index:
            offset += 1
        spans.append((unit.unit_id, offset, offset + len(unit.raw_text)))
        offset += len(unit.raw_text)
    return ChunkEvidence(
        source_id=str(chunk_row[7]),
        build_id=build_id,
        chunk_id=chunk_id,
        kind=str(chunk_row[2] or ""),
        title_text=chunk_row[3],
        section_path=tuple(chunk_row[4] or ()),
        units=tuple(units),
        text="\n".join(unit.raw_text for unit in units),
        source_ranges=source_ranges,
        spans=tuple(spans),
        active=bool(chunk_row[9]),
    )
