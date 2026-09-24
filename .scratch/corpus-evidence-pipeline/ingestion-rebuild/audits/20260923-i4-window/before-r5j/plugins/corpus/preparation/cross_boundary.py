"""F4：跨 NOISE/kept 边界联合取证（消费侧，仅读 PG）。

company-008/a-1（spec §10.4 / issue 09）：引文「贵州茅台（600519）2026 年中报点评
…强推（维持）」横跨 NOISE/kept 边界——前半是 `header_repeated_geometric`（+`heading_by_font_size`）
p1 封面标题 NOISE 单元，后半在 kept ord=6 p1 评级行。band 读取链取回的
:class:`ChunkEvidence` ``units`` 只含 kept 单元，故单从块内取证永远取不到完整引文
（stewed 边界：`quote_norm_in_kept_any=False`）。

本模块在**读取侧**把「与某 kept 单元同页、且处于同一水平行带（bbox 垂直区间重叠）」
的 ``header_repeated_geometric``/``footer_repeated_geometric`` NOISE 单元，按其
``ordinal`` 保序聚合进该块的证据文本——跨边界联合取证，命中即补、留 NOISE 来源标记。

F3-B（i0c-r4u，U 2026-09-22 具名裁决路径 B）：**读取侧续接片段聚合**——kept 单元
句中截断（raw_text 不以句末标点收尾）且其**紧邻下一 ordinal** 的 NOISE 单元以句末
标点收尾（拼接即补全句子）并同页时，把该 NOISE 尾片段按 ``ordinal`` 保序聚合进块
证据（``stitch_continuation``）。同构样本＝company-007/e1『…4.06%的股』（kept
ord717）+『份。』（NOISE/disclaimer_section ord718）；谓词纯结构、不绑噪声类型，
与 ``f3-fragment-scan`` 及精化扫描同口径——全库 8 builds 裸相邻 132 处中仅此一处
满足「拼接补全句子」（``20260922-f3b-continuation-fragment`` 扫描产物）。

纪律（issue 09 不做）：
- 不写库、不改 clean 判定、不重摄入（只读 ``i2_sandbox_corpus``）。
- 不把整表头降 KEPT、不按金标词/页补取证据。
- 聚入的是**权威原文单元**，逐字取自 ``corpus_units.raw_text`` 并校验内容哈希
  （同 :func:`read_pg._assemble_chunk_evidence` fail-closed）。
- 只聚合同页同水平带的 NOISE 表头/脚注；不改变检索、选择（band 集/池不变）。
- 保序：合并单元按 ``(ordinal, unit_id)`` 稳定排序，保证「标题 ord<评级 ord」的
  substring 顺序成立，verdict 由 :meth:`read_pg.ChunkEvidence.spans` 可复算。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import psycopg

from plugins.corpus.preparation.contract import UnitStatus
from plugins.corpus.preparation.pg_target import resolve_target_db
from plugins.corpus.preparation.read_pg import (
    ChunkEvidence,
    UnitEvidence,
    verified_unit,
    with_units,
)

_SANDBOX_DB = resolve_target_db()

#: F4 只聚合这两类「重复几何表头/脚注」NOISE（与 f4_replay 同口径；不含普通 heading）。
_HEADER_FOOTER = frozenset({"header_repeated_geometric", "footer_repeated_geometric"})

#: F3-B 续接片段谓词的句末标点（与 f3-fragment-scan / 精化扫描同口径）。
_SENTENCE_TERMINAL = ("。", "！", "？", "；", "…", "”", "」", "』", "）", ")", "]", "】")

#: D2（i0c-r4y）表格来源注谓词：段首标记 + 说明性分句（与 d2_footnote_scan 的 L1/L2 同口径）。
#: 两段式是为了排除纯「资料来源：WIND，光大证券研究所」这类**无口径信息**的标注
#: （全库 91 段里 88 段属此类，聚合它们只有噪声没有收益）。
_SOURCE_NOTE_LEAD = r"^\s*(资料来源|注\s*[0-9１-９]|注\s*[:：]|数据来源|说明\s*[:：])"
_SOURCE_NOTE_EXPLAIN = r"(注\s*[0-9１-９]\s*[:：]|注\s*[:：]|备注\s*[:：]|口径)"

#: D2 版面判据：注段上沿与上方表格行下沿的垂直间距上限（pt）。
_SOURCE_NOTE_MAX_GAP_PT = 12.0

#: 候选 NOISE 单元 + 块内 kept 单元一并取回（kept 只需 bbox 作行带判据）。
#: F3-B 第三支：紧邻某块内 kept 单元（ordinal-1）之后的 NOISE 单元（续接片段候选）。
#: D2 第四支：同 build 内 kept 且形似「来源注 + 说明性分句」的单元（表格来源注候选，
#: 谓词在 _merge_chunk 内按版面精化——只用 bbox 判上下，**ordinal 序 ≠ 版面序**；
#: 表格行的判定改用 ``UnitEvidence.cells`` 非空，避免给单元记录引入新字段）。
_BOUNDARY_UNITS_SQL = """
SELECT u.build_id, u.unit_id, u.ordinal, u.raw_text, u.location, u.content_hash, u.status, u.reasons
FROM corpus.corpus_units u
WHERE u.build_id = ANY(%(build_ids)s::text[])
  AND (
        u.unit_id = ANY(%(kept_ids)s::text[])
        OR (u.status = %(noise)s AND u.reasons && %(hf)s::text[])
        OR (u.status = %(noise)s AND EXISTS (
              SELECT 1 FROM corpus.corpus_units k
              WHERE k.build_id = u.build_id AND k.ordinal = u.ordinal - 1
                AND k.unit_id = ANY(%(kept_ids)s::text[])))
        OR (u.status = %(kept)s AND u.raw_text ~ %(note_lead)s
            AND u.raw_text ~ %(note_explain)s)
      )
"""


def _bbox_overlap_y(
    a: tuple[float, float, float, float] | None, b: tuple[float, float, float, float] | None
) -> bool:
    """两 bbox 在**垂直**方向上是否存在重叠（同一水平行带）。

    bbox = (x0, y0, x1, y1)（左上/右下）；y 轴向下。返回 False 当其中一个缺失，
    或二者在 y 方向被严格分隔（a 在 b 之下 || b 在 a 之下）。
    """
    if a is None or b is None:
        return False
    return not (a[3] <= b[1] or b[3] <= a[1])


def aggregate_band_chunks(
    dsn: str,
    chunk_evs: tuple[ChunkEvidence, ...],
    *,
    sandbox_db: str = _SANDBOX_DB,
    stitch_continuation: bool = True,
    attach_source_note: bool = True,
) -> tuple[ChunkEvidence, ...]:
    """跨边界联合取证：把同页同水平带 NOISE 表头/脚注保序聚合进块证据文本。

    对每个块的每个 kept 单元，取与其同页、bbox 垂直重叠、且不在该块内的
    `header_repeated_geometric`/`footer_repeated_geometric` NOISE 单元，按其
    ``ordinal`` 与块内单元共同排序重建 ``units``/``text``/``spans``。无候选则原样返回。

    F3-B（``stitch_continuation``，默认开）：对每个 kept 单元，若其句中截断
    （raw_text 不以句末标点收尾）且**紧邻下一 ordinal** 的 NOISE 单元以句末标点
    收尾（拼接即补全句子）并同页，则该续接片段一并保序聚合（I-CONT-1）。
    复验 A/B 用 ``stitch_continuation=False`` 取关断基线（生产行为不变）。

    D2（``attach_source_note``，默认开）：若块内含**表格行** kept 单元，则把与它同页、
    版面在其**下方**且垂直间距 < ``_SOURCE_NOTE_MAX_GAP_PT``、形似「来源注 + 说明性
    分句」的 kept 注段一并保序聚合（I-NOTE-1）。动机：图/表的口径脚注被切成独立块、
    词法重叠低而排不进 ``pool_cap`` ⇒ 读者拿到表格却拿不到口径说明。纯结构谓词、
    不绑金标（全库三条件精化后仅 4 条配对 / 2 份语料，见 d2_footnote_scan）。
    复验 A/B 用 ``attach_source_note=False`` 取关断基线。

    纯只读、0 model calls。fail-closed：聚合的 NOISE 单元同样校验内容哈希，权威
    单元被篡改即 :class:`IntegrityError`，绝不把改过的正文当原文。
    """
    import psycopg

    from plugins.corpus.preparation.read_pg import _check_target

    if not chunk_evs:
        return chunk_evs

    with psycopg.connect(dsn, autocommit=True) as conn:
        _check_target(conn, sandbox_db)
        with conn.transaction(), conn.cursor() as cur:
            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            return aggregate_band_chunks_on(
                cur,
                chunk_evs,
                stitch_continuation=stitch_continuation,
                attach_source_note=attach_source_note,
            )


def aggregate_band_chunks_on(
    cur: psycopg.Cursor,
    chunk_evs: tuple[ChunkEvidence, ...],
    *,
    stitch_continuation: bool = True,
    attach_source_note: bool = True,
) -> tuple[ChunkEvidence, ...]:
    """Read bounded context in the same transaction as its chunk and authorization."""
    if not chunk_evs:
        return chunk_evs
    # 需要 bbox 的块内 kept 单元（ChunkEvidence.units 不含 bbox）+ 候选 NOISE 所在 build
    build_ids = sorted({ev.build_id for ev in chunk_evs})
    kept_ids: list[str] = [u.unit_id for ev in chunk_evs for u in ev.units]
    noise_status = UnitStatus.NOISE.value
    kept_status = UnitStatus.KEPT.value
    hf = list(sorted(_HEADER_FOOTER))

    cur.execute(
        _BOUNDARY_UNITS_SQL,
        {
            "build_ids": build_ids,
            "kept_ids": kept_ids,
            "noise": noise_status,
            "kept": kept_status,
            "hf": hf,
            "note_lead": _SOURCE_NOTE_LEAD,
            "note_explain": _SOURCE_NOTE_EXPLAIN,
        },
    )
    # build_id -> {unit_id: (ordinal, raw_text, location, content_hash, reasons, kind)}
    kept_by_build: dict[str, dict[str, tuple]] = {}
    noise_by_build: dict[str, dict[str, tuple]] = {}
    frag_by_build: dict[str, dict[str, tuple]] = {}
    note_by_build: dict[str, dict[str, tuple]] = {}
    for bid, uid, ordinal, raw, loc, chash, status, reasons in cur.fetchall():
        cell = (ordinal, str(raw or ""), loc, str(chash or ""), tuple(reasons or ()))
        if status == noise_status:
            if set(reasons or ()) & _HEADER_FOOTER:
                noise_by_build.setdefault(str(bid), {})[str(uid)] = cell
            # F3-B：全部取回的 NOISE 行都是续接片段候选（谓词在 _merge_chunk 内过滤）。
            frag_by_build.setdefault(str(bid), {})[str(uid)] = cell
        else:  # kept 单元（bbox 判据 + 续接谓词的前半句判据）
            kept_by_build.setdefault(str(bid), {})[str(uid)] = cell
            # D2：形似来源注的 kept 段（谓词在 _merge_chunk 内按版面精化）。
            if _is_source_note(str(raw or "")):
                note_by_build.setdefault(str(bid), {})[str(uid)] = cell

    frag_map = frag_by_build if stitch_continuation else {}
    note_map = note_by_build if attach_source_note else {}
    out: list[ChunkEvidence] = [
        _merge_chunk(
            ev,
            kept_by_build.get(ev.build_id, {}),
            noise_by_build.get(ev.build_id, {}),
            fragments=frag_map.get(ev.build_id, {}),
            notes=note_map.get(ev.build_id, {}),
        )
        for ev in chunk_evs
    ]
    return tuple(out)


def _is_source_note(raw: str) -> bool:
    """D2 段形判据：段首为来源/注标记 **且** 含说明性分句（与扫描脚本 L1∩L2 同口径）。"""

    import re

    return bool(re.search(_SOURCE_NOTE_LEAD, raw) and re.search(_SOURCE_NOTE_EXPLAIN, raw))


def _merge_chunk(
    ev: ChunkEvidence,
    kept: dict[str, tuple],
    noise: dict[str, tuple],
    fragments: dict[str, tuple] | None = None,
    notes: dict[str, tuple] | None = None,
) -> ChunkEvidence:
    """纯合并逻辑（可离线测试，I-ATT-1 / I-CONT-1 / I-NOTE-1）：把与块内 kept 单元同页
    同水平带（bbox 垂直重叠）的 NOISE 表头/脚注、「kept 句中截断 + 紧邻下一 ordinal
    NOISE 尾片段以句末标点收尾」的续接片段（F3-B）、以及版面紧贴块内表格行下方的
    「来源注 + 说明性分句」kept 段（D2），按 (ordinal, unit_id) 保序聚合进块证据，
    重建 units/text/spans。

    ``kept``/``noise``/``fragments``/``notes`` 为 ``unit_id -> (ordinal, raw_text,
    location, content_hash, reasons, kind)``；非本 build 单元调用方应先用
    ``{unit_id: None}`` 和 [] 控制，本函数只基于给定映射合并。
    """
    # 块内 kept 单元的 bbox
    kept_bbox: dict[str, tuple | None] = {}
    for unit in ev.units:
        rec = kept.get(unit.unit_id)
        if rec is not None:
            loc = rec[2] if isinstance(rec[2], dict) else {}
            kept_bbox[unit.unit_id] = tuple(loc.get("bbox") or ()) or None

    merges: list[tuple[str, str, dict]] = []  # (unit_id, raw_text, location)
    seen = {u.unit_id for u in ev.units}
    for unit in ev.units:
        if unit.page is None:
            continue
        kept_b = kept_bbox.get(unit.unit_id)
        for nid, (_ord, raw, loc, _chash, _reasons) in noise.items():
            if nid in seen:
                continue
            nloc = loc if isinstance(loc, dict) else {}
            if nloc.get("page") != unit.page:
                continue
            if not _bbox_overlap_y(tuple(nloc.get("bbox") or ()) or None, kept_b):
                continue
            seen.add(nid)
            merges.append((nid, raw, nloc))

    # F3-B（i0c-r4u）续接片段：kept 单元句中截断（不以句末标点收尾）时，其紧邻
    # 下一 ordinal 的 NOISE 单元若以句末标点收尾（拼接即补全句子）且同页 ⇒ 保序聚合。
    # 结构谓词、不绑噪声类型（与 f3-fragment-scan / 精化扫描同口径，全库同构样本=1）。
    for unit in ev.units:
        rec = kept.get(unit.unit_id)
        if rec is None or unit.page is None:
            continue
        ord_k = rec[0]
        head = str(rec[1] or "").rstrip()
        if not head or head.endswith(_SENTENCE_TERMINAL):
            continue
        for fid, (ord_f, raw_f, loc_f, _chash, _rsn) in (fragments or {}).items():
            if fid in seen or int(ord_f) != int(ord_k) + 1:
                continue
            floc = loc_f if isinstance(loc_f, dict) else {}
            if floc.get("page") != unit.page:
                continue
            tail = str(raw_f or "").rstrip()
            if not tail or not tail.endswith(_SENTENCE_TERMINAL):
                continue
            seen.add(fid)
            merges.append((fid, raw_f, floc))

    # D2（i0c-r4y）表格来源注：块内 kept 单元若是**表格行**（``UnitEvidence.cells`` 非空），
    # 则同页、版面在其**下方**（注段上沿 ≥ 表格行下沿）且垂直间距 < _SOURCE_NOTE_MAX_GAP_PT
    # 的「来源注 + 说明性分句」kept 段 ⇒ 保序聚合。
    # ⚠ 只用 bbox 判上下：ordinal 序 ≠ 版面序（本文档 ord518 的 ordinal 就排在表格之前）。
    for unit in ev.units:
        rec = kept.get(unit.unit_id)
        if rec is None or unit.page is None:
            continue
        if not unit.cells:  # 非表格行 ⇒ 不作为来源注的锚
            continue
        loc_k = rec[2] if isinstance(rec[2], dict) else {}
        bbox_k = tuple(loc_k.get("bbox") or ()) or None
        if not bbox_k:
            continue
        table_y1 = bbox_k[3]
        for nid, (_ord_n, raw_n, loc_n, _chash, _rsn) in (notes or {}).items():
            if nid in seen:
                continue
            # 段形判据在此复算（SQL 只做粗筛）：纯「资料来源：…」无口径说明者一律不聚合。
            if not _is_source_note(str(raw_n or "")):
                continue
            nloc = loc_n if isinstance(loc_n, dict) else {}
            if nloc.get("page") != unit.page:
                continue
            bbox_n = tuple(nloc.get("bbox") or ()) or None
            if not bbox_n:
                continue
            gap = bbox_n[1] - table_y1
            if gap < 0 or gap >= _SOURCE_NOTE_MAX_GAP_PT:
                continue
            seen.add(nid)
            merges.append((nid, raw_n, nloc))

    if not merges:
        return ev

    # 保序：块内单元（含 ordinal）+ 补入 NOISE（含 ordinal）按 (ordinal, unit_id) 稳定排序
    merged_units: list[tuple[int, str, UnitEvidence]] = []
    for unit in ev.units:
        rec = kept.get(unit.unit_id)
        ordinal = rec[0] if rec is not None else 0
        merged_units.append((ordinal if ordinal is not None else -1, unit.unit_id, unit))
    for nid, raw, nloc in merges:
        rec = noise.get(nid)
        if rec is None:  # F3-B 续接片段 / D2 来源注的 ordinal 在各自映射
            rec = (fragments or {}).get(nid)
        if rec is None:
            rec = (notes or {}).get(nid)
        ordinal = rec[0] if rec is not None else 0
        merged_units.append(
            (
                ordinal if ordinal is not None else -1,
                nid,
                verified_unit(ev.build_id, nid, raw, nloc, str(rec[3]) if rec else ""),
            )
        )
    merged_units.sort(key=lambda x: (x[0], x[1]))

    units_out = tuple(ue for *_a, ue in merged_units)
    context_ids = tuple(dict.fromkeys((*ev.context_unit_ids, *(uid for uid, _, _ in merges))))
    return with_units(ev, units_out, context_unit_ids=context_ids)
