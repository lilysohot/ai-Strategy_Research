"""B4.3 隔离发布与回滚演练（真实引擎 × 隔离库 i2_sandbox_corpus）。

契约（`docs/data_clean_dos/02-fragment-chunking.md` §B4.3，L269-281）五项：

1. 新 build 的原文、结构、索引和引用校验通过，候选效果可复现；
2. 消费清单、缓存、游标及后续 Claims/R2 结果绑定 build 和内容身份，新旧版本不能错误复用；
3. 旧 build、兼容的代码/配置、索引访问能力和源访问权限均仍可用；
4. 对既有运行固定快照，新请求按发布策略选版本；旧游标不被静默升级；
5. 回滚时能够恢复完整兼容组合，并重放旧引用、检索和分页请求。

隔离保证（§B4.3）：零模型 import 陷阱（DenyModels 拒绝 openai/anthropic 及
material_semantics/_r2_）；只读源（i3-1 e2e 归档副本，engine 解析读归档、新副本
落在本目录 archive/）；仅向隔离库 ``i2_sandbox_corpus`` 写入；生产库连接显式
``SET default_transaction_read_only=on``。

回滚语义说明（写入报告的限制）：Store Seam 的 ``put_admission`` 只前移
``current_decision_id`` 指针（F1/F2，同内容重放不回退），故正式 API 没有
「指针回退」。演练以**操作者回滚动作**直接复位来源指针到旧决定（沙箱内单行
SQL，记入报告），再走 ``engine.publish_build`` 重发旧 build —— 这是 B4.3 第 5 项
「恢复完整兼容组合」的受控验证路径。
"""

from __future__ import annotations

import hashlib
import importlib.abc
import json
import os
import re
import sys
from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
PROD_DSN = "postgresql://postgres:postgres@localhost:5432/postgres"
SANDBOX_DSN = "postgresql://postgres:postgres@127.0.0.1:543/i2_sandbox_corpus"
SANDBOX_DB = "i2_sandbox_corpus"
# 只读源：i3-1 e2e 审计固定归档副本（生产 data/corpus-archive 无此批次）。
ARCHIVE = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i3-1-e2e/archive"
# 新产物位置：engine.ingest_source 会把归档副本原子写入本目录。
DRILL_ARCHIVE = OUT / "archive"
GOLD = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-2/query-gold-scoring-v1.jsonl"
POLICY_PATH = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/admission-policy.json"
B4_JSON = ROOT / ".scratch/b4-combined-20260929/b4-combined-comparison.json"

sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

# B4.3 隔离保证：零模型 import 陷阱（拒绝 openai/anthropic 与语义模型实现）。
class DenyModels(importlib.abc.MetaPathFinder):
    _DENIED_ROOTS: tuple[str, ...] = ("openai", "anthropic")
    _DENIED_PREFIXES: tuple[str, ...] = ("plugins.corpus.material_semantics", "plugins.corpus._r2_")

    def find_spec(self, fullname, path=None, target=None):  # noqa: ANN001, ANN201
        if fullname.split(".")[0] in self._DENIED_ROOTS or fullname.startswith(
            self._DENIED_PREFIXES
        ):
            raise RuntimeError(f"Model module forbidden during B4.3 drill: {fullname}")
        return None


sys.meta_path.insert(0, DenyModels())

import psycopg  # noqa: E402

from plugins.corpus.preparation.admission import load_admission_policy  # noqa: E402
from plugins.corpus.preparation.contract import (  # noqa: E402
    Admission,
    AdmissionDecision,
    AdmissionReasonCode,
    Build,
    CharSpan,
    Chunk,
    DocumentFormat,
    JobStage,
    JobState,
    LeaseConfig,
    MaterialType,
    MetadataSnapshot,
    PublicationDateOrigin,
    PublicationDatePrecision,
    PublicationDateStatus,
    ReportPublication,
    ResearchDomain,
    ReviewDecision,
    ReviewedDecision,
    Source,
    Unit,
    UnitLocation,
    UnitStatus,
    canonical_fingerprint,
)
from plugins.corpus.preparation.engine import (  # noqa: E402
    PlanEntry,
    check_build_publishable,
    execute_builds,
    gap_records_of,
    plan_builds,
    publish_build,
)
from plugins.corpus.preparation.gap_review import (  # noqa: E402
    ATTESTATION,
    REVIEW_STAGE_PREFIX,
    SCHEMA_REV,
    GapReview,
)
from plugins.corpus.preparation.gaps import (  # noqa: E402
    GAP_POLICY_REV,
    GapCoordinateKind,
    blocking_gaps,
)
from plugins.corpus.preparation.negative_query import retrieval_query  # noqa: E402
from plugins.corpus.preparation.read_pg import (  # noqa: E402
    build_handle,
    chunk_locator,
    fetch_verbatim,
)
from plugins.corpus.preparation.repository_pg import PgStore  # noqa: E402
from plugins.corpus.preparation.search_pg import query_lexemes, search_chunks  # noqa: E402

LEASE = LeaseConfig(300, 60, 600, 3)
OWNER = "b43-publish-drill"
DRIL_NOW = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
TABLES = (
    "corpus_source_checkpoints",
    "corpus_jobs",
    "corpus_publications",
    "corpus_chunks",
    "corpus_units",
    "corpus_builds",
    "corpus_admissions",
    "corpus_review_decisions",
    "corpus_sources",
)

_WS = re.compile(r"[\s\u3000\xa0\u200b]+")


def norm(text: str) -> str:
    """去全部空白后比较（与 B0/B1 同口径），抵消排版换行差异。"""
    return _WS.sub("", text or "")


# ---- 生产数据拷贝辅助（只读 SELECT） ----


def _loc_from_dict(data: dict) -> UnitLocation:
    span = data.get("char_span")
    return UnitLocation(
        page=data.get("page"),
        element=data.get("element"),
        char_span=CharSpan(span[0], span[1]) if span else None,
        bbox=tuple(data.get("bbox")) if data.get("bbox") else None,
        cells=tuple(tuple(c) for c in (data.get("cells") or ())),
        label_path=tuple(data.get("label_path") or ()),
    )


def _snapshot_from_dict(data: dict) -> MetadataSnapshot:
    rp = (data or {}).get("report_publication")
    if rp is None:
        return MetadataSnapshot()
    return MetadataSnapshot(
        report_publication=ReportPublication(
            value=rp.get("value"),
            precision=PublicationDatePrecision(rp["precision"]),
            status=PublicationDateStatus(rp["status"]),
            evidence_refs=tuple(rp.get("evidence_refs") or ()),
            origin=PublicationDateOrigin(rp["origin"]) if rp.get("origin") else None,
            review_ref=rp.get("review_ref"),
        )
    )


def load_old_world(conn: psycopg.Connection, source_ids: tuple[str, ...]) -> dict[str, dict]:
    """按 source_id 装载生产旧 world 的 Source/ReviewedDecision/Admission/Build/units/chunks。"""
    out: dict[str, dict] = {}
    for sid in source_ids:
        srow = conn.execute(
            "SELECT format, mime_type, size_bytes, archive_path, original_names "
            "FROM corpus.corpus_sources WHERE source_id=%s",
            (sid,),
        ).fetchone()
        if srow is None:
            raise RuntimeError(f"生产来源缺失: {sid[:16]}")
        source = Source(
            source_id=sid,
            format=DocumentFormat(srow[0]),
            mime_type=srow[1],
            size_bytes=srow[2],
            archive_path=srow[3],
            original_names=tuple(srow[4] or ()),
        )
        rrow = conn.execute(
            "SELECT decision_id, reviewer, reviewed_at, decision, rationale, scope_ref, "
            "supersedes, locators, material_type, research_domain "
            "FROM corpus.corpus_review_decisions WHERE source_id=%s",
            (sid,),
        ).fetchall()
        # 只取该来源的人工批准决定（B4.3 沙箱按 v1 政策重判，需唯一 admitted 决定）。
        reviews = []
        for r in rrow:
            reviews.append(
                ReviewedDecision(
                    decision_id=r[0],
                    source_id=sid,
                    reviewer=r[1],
                    reviewed_at=r[2],
                    decision=ReviewDecision(r[3]),
                    rationale=r[4],
                    scope_ref=r[5],
                    supersedes=r[6],
                    locators=tuple(r[7] or ()),
                    material_type=MaterialType(r[8]) if r[8] else None,
                    research_domain=ResearchDomain(r[9]) if r[9] else None,
                )
            )
        review = next((d for d in reviews if d.decision is ReviewDecision.ADMITTED), None)
        if review is None:
            raise RuntimeError(f"来源无 admitted 人工决定: {sid[:16]}")
        arow = conn.execute(
            "SELECT decision_id, material_type, research_domain, decision, policy_rev, "
            "reason_codes, scope_ref, evidence_refs, review_ref, rule_rev, metadata_snapshot "
            "FROM corpus.corpus_admissions WHERE decision_id="
            "(SELECT current_decision_id FROM corpus.corpus_sources WHERE source_id=%s)",
            (sid,),
        ).fetchone()
        if arow is None:
            raise RuntimeError(f"来源无当前准入记录: {sid[:16]}")
        admission = Admission(
            decision_id=arow[0],
            source_id=sid,
            material_type=MaterialType(arow[1]) if arow[1] else MaterialType.UNKNOWN,
            research_domain=ResearchDomain(arow[2]) if arow[2] else None,
            decision=AdmissionDecision(arow[3]),
            policy_rev=arow[4],
            reason_codes=tuple(AdmissionReasonCode(c) for c in (arow[5] or ())),
            scope_ref=arow[6],
            evidence_refs=tuple(arow[7] or ()),
            review_ref=arow[8],
            rule_rev=arow[9],
            metadata_snapshot=_snapshot_from_dict(arow[10] if isinstance(arow[10], dict) else {}),
        )
        brow = conn.execute(
            "SELECT build_id, decision_id, parse_rev, clean_rev, chunk_rev, index_rev, "
            "scope_ref, config_fingerprint, artifact_manifest, quality_report "
            "FROM corpus.corpus_builds WHERE source_id=%s ORDER BY build_id",
            (sid,),
        ).fetchall()
        if not brow:
            raise RuntimeError(f"来源无 build: {sid[:16]}")
        # 生产活动的旧 build（active_build_id）是本次的「旧版本」。
        act = conn.execute(
            "SELECT active_build_id FROM corpus.corpus_publications WHERE source_id=%s",
            (sid,),
        ).fetchone()
        old_build_id = act[0] if act and act[0] else brow[0][0]
        b = next((r for r in brow if r[0] == old_build_id), brow[0])
        build = Build(
            build_id=b[0],
            source_id=sid,
            decision_id=b[1],
            parse_rev=b[2],
            clean_rev=b[3],
            chunk_rev=b[4],
            index_rev=b[5],
            scope_ref=b[6],
            config_fingerprint=b[7],
            artifact_manifest=tuple(b[8] or ()),
            quality_report=json.dumps(b[9], ensure_ascii=False, sort_keys=True) if b[9] else None,
        )
        units = []
        for u in conn.execute(
            "SELECT unit_id, parent_id, ordinal, kind, raw_text, content_hash, location, "
            "clean_view, mapping, status, reasons FROM corpus.corpus_units "
            "WHERE build_id=%s ORDER BY ordinal NULLS LAST, unit_id",
            (old_build_id,),
        ).fetchall():
            loc = u[6] if isinstance(u[6], dict) else {}
            units.append(
                Unit(
                    unit_id=u[0],
                    build_id=old_build_id,
                    parent_id=u[1],
                    ordinal=u[2],
                    kind=u[3],
                    raw_text=u[4],
                    content_hash=u[5],
                    location=_loc_from_dict(loc),
                    clean_view=u[7],
                    mapping=tuple(tuple(s) for s in (u[8] or ())),
                    status=UnitStatus(u[9]),
                    reasons=tuple(u[10] or ()),
                )
            )
        chunks = []
        for c in conn.execute(
            "SELECT chunk_id, kind, unit_refs, context_refs, search_text, title_text, "
            "section_path, source_ranges FROM corpus.corpus_chunks "
            "WHERE build_id=%s ORDER BY chunk_id",
            (old_build_id,),
        ).fetchall():
            chunks.append(
                Chunk(
                    chunk_id=c[0],
                    build_id=old_build_id,
                    kind=c[1],
                    unit_refs=tuple(c[2] or ()),
                    context_refs=tuple(c[3] or ()),
                    search_text=c[4],
                    title_text=c[5],
                    section_path=tuple(c[6] or ()),
                    source_ranges=tuple(CharSpan(s[0], s[1]) for s in (c[7] or ())),
                )
            )
        # 旧 build 的具名缺口凭证（human-gap-review:<build_id> 检查点；publish 门按 §7.3
        # 用它放行 blocking 缺口，须随旧 world 一并复制，否则沙箱重发旧 build 会误判阻断）。
        gr_row = conn.execute(
            "SELECT checkpoint FROM corpus.corpus_source_checkpoints "
            "WHERE source_id=%s AND stage=%s",
            (sid, REVIEW_STAGE_PREFIX + old_build_id),
        ).fetchone()
        gap_review_checkpoint = None
        if gr_row is not None:
            cp = gr_row[0]
            gap_review_checkpoint = (
                cp if isinstance(cp, str) else json.dumps(cp, ensure_ascii=False, sort_keys=True)
            )
        out[sid] = {
            "source": source,
            "review": review,
            "admission": admission,
            "build": build,
            "units": units,
            "chunks": chunks,
            "gap_review_checkpoint": gap_review_checkpoint,
        }
    return out


def load_source_artifacts(conn: psycopg.Connection, build_id: str) -> dict:
    """沙箱活动 build 的权威单元与 chunk（B0 形状，供可复现性对照）。"""
    units = conn.execute(
        "SELECT u.ordinal, u.unit_id, u.location->>'page', "
        "jsonb_array_length(COALESCE(u.location->'cells','[]'::jsonb)), "
        "u.location->>'element', u.raw_text, u.kind "
        "FROM corpus.corpus_units u WHERE u.build_id=%s ORDER BY u.ordinal",
        (build_id,),
    ).fetchall()
    unit_rows = [
        {"ordinal": r[0], "unit_id": r[1], "page": r[2], "n_cells": int(r[3]),
         "element": r[4], "raw": r[5] or "", "norm": norm(r[5] or ""), "kind": r[6]}
        for r in units
    ]
    by_unit = {u["unit_id"]: u for u in unit_rows}
    chunks = conn.execute(
        "SELECT c.chunk_id, c.kind, c.title_text, c.unit_refs, c.section_path "
        "FROM corpus.corpus_chunks c WHERE c.build_id=%s",
        (build_id,),
    ).fetchall()
    chunk_rows = []
    for c in chunks:
        refs = list(c[3] or [])
        text = "\n".join(by_unit[u]["raw"] for u in refs if u in by_unit)
        chunk_rows.append(
            {"chunk_id": c[0], "kind": c[1], "title": c[2], "unit_refs": refs,
             "text": text, "norm": norm(text)}
        )
    return {
        "units": unit_rows,
        "chunks": chunk_rows,
        "chunk_by_locator": {f"chunk:{c['chunk_id']}": c for c in chunk_rows},
        "doc_norm": "".join(u["norm"] for u in unit_rows),
    }


# ---- 阶段辅助 ----


def verify_cleanup_target(cur: psycopg.Cursor) -> None:
    cur.execute("SELECT current_database()")
    row = cur.fetchone()
    if row is None or row[0] != SANDBOX_DB:
        raise RuntimeError(f"拒绝清理：current_database={row[0]!r} ≠ {SANDBOX_DB!r}")
    cur.execute("SELECT datname FROM pg_database WHERE datallowconn")
    dbs = {r[0] for r in cur.fetchall()}
    if "apodex" in dbs:
        raise RuntimeError("拒绝清理：目标实例含 apodex 库")


def truncate_sandbox() -> None:
    qualified = ", ".join(f"corpus.{t}" for t in TABLES)
    with psycopg.connect(SANDBOX_DSN, autocommit=True) as conn, conn.cursor() as cur:
        verify_cleanup_target(cur)
        cur.execute(f"TRUNCATE {qualified}")
        print("phase0: TRUNCATE 九表完成")


def seed_stage(store: PgStore, build_id: str, stage: JobStage, payload: object) -> None:
    store.register_job(build_id, stage)
    job = store.acquire_job(build_id, stage, OWNER, DRIL_NOW, LEASE)
    token = job.fence_token
    if token is None:
        raise RuntimeError(f"{stage.value} job 缺少 fence_token: {build_id[:16]}")
    if stage is JobStage.PARSED:
        store.put_units(build_id, payload, owner_id=OWNER, fence_token=token)  # type: ignore[arg-type]
    else:
        store.put_chunks(build_id, payload, owner_id=OWNER, fence_token=token)  # type: ignore[arg-type]
    store.finish_job(build_id, stage, OWNER, token, DRIL_NOW, JobState.SUCCEEDED)


def publication_row(conn: psycopg.Connection, source_id: str) -> dict:
    r = conn.execute(
        "SELECT current_decision_id, active_build_id, generation, activated_at "
        "FROM corpus.corpus_publications WHERE source_id=%s",
        (source_id,),
    ).fetchone()
    return {
        "current_decision_id": (r[0][:24] + "…") if r and r[0] else None,
        "active_build_id": (r[1][:24] + "…") if r and r[1] else None,
        "generation": r[2] if r else None,
        "activated_at": str(r[3]) if r and r[3] else None,
    }


def search_snapshot(queries: list[str], limit: int) -> dict[str, list[dict]]:
    """在沙箱活动范围检索固定查询，返回确定序 (source_id, build_id, chunk_id)。

    查询形态 = 产品候选查询（``retrieval_query``：实质词元 OR 连接，websearch 语法）。
    不用问题原文——``websearch_to_tsquery`` 会把连续中文词合成邻接短语（``<->``），
    全题 23 词短语在真实语料中不命中（生产同 0 命中）；B0 金标走的服务层
    ``plainto_tsquery``（AND）。本处与产品候选查询同口径，命中非空、可复现。
    """
    out: dict[str, list[dict]] = {}
    for qid, q in enumerate(queries):
        lexemes = query_lexemes(SANDBOX_DSN, q, sandbox_db=SANDBOX_DB)
        product_q = retrieval_query(lexemes)
        hits = search_chunks(
            SANDBOX_DSN, product_q or q, sandbox_db=SANDBOX_DB, limit=limit
        )
        out[str(qid)] = [
            {"source_id": h.source_id, "build_id": h.build_id, "chunk_id": h.chunk_id}
            for h in hits
        ]
    return out


def fetch_snapshot(items: list[tuple[str, str]]) -> dict[str, dict]:
    """对 (doc_id, locator) 逐条取回取证结果（绑定 build 的逐字文本）。"""
    out: dict[str, dict] = {}
    for doc_id, locator in items:
        ev = fetch_verbatim(SANDBOX_DSN, doc_id, locator, sandbox_db=SANDBOX_DB)
        out[f"{doc_id}|{locator}"] = {
            "build_id": ev.build_id,
            "chunk_id": ev.chunk_id,
            "active": ev.active,
            "text_hash": hashlib.sha256(ev.text.encode("utf-8")).hexdigest()[:24],
            "text_head": ev.text[:60].replace("\n", "\\n"),
        }
    return out


def _ack_blocking_gaps(store: PgStore, build: Build) -> dict:
    """操作者动作：为新 build 的阻断缺口签署具名凭证（§7.3，发布前置）。

    演练语义：新 build（reader-pdf-7 + chunk-4）与旧 build 同源，阻断缺口同码
    （image_region_unreadable / table_lines_without_extraction，均页级）——真实发布
    流程同样须对新 build 指纹重签。凭证要求（gap_review.apply_gap_review）：
    ``required_locators`` 非空且与每个阻断缺口不相交（页级选非缺口页）、并在保留单元
    中可定位；``gaps`` 恰为全部当前阻断键。仅支持页级阻断缺口；非页级 fail-closed。
    """
    records = gap_records_of(build)
    blocking = blocking_gaps(records)
    if not blocking:
        return {"acknowledged": 0, "keys": []}
    if not all(
        r.coordinates.kind is GapCoordinateKind.PAGE and r.coordinates.page for r in blocking
    ):
        raise RuntimeError(f"新 build 存在非页级阻断缺口，演练不自动签署: {[r.key for r in blocking]}")
    keys = tuple(sorted(r.key for r in blocking))
    gap_pages = {r.coordinates.page for r in blocking}
    kept_pages = {
        u.location.page
        for u in store.get_units(build.build_id)
        if u.status is UnitStatus.KEPT and u.location.page is not None
    }
    candidates = sorted(kept_pages - gap_pages)
    if not candidates:
        raise RuntimeError(
            f"无可用作 required_locators 的非缺口页（保留页 {sorted(kept_pages)} vs 缺口页 {sorted(gap_pages)}）"
        )
    target = f"page:{candidates[0]}"
    review = GapReview(
        schema_rev=SCHEMA_REV,
        policy_rev=GAP_POLICY_REV,
        source_id=build.source_id,
        build_id=build.build_id,
        build_fingerprint=canonical_fingerprint(asdict(build)),
        reviewer="b43-drill-operator",
        reviewed_at=DRIL_NOW.isoformat(),
        evidence_scope_ref="b4.3-drill:operator-ack-same-codes-as-production",
        required_locators=(target,),
        scope_rationale="隔离演练操作者按 §7.3 签署新 build 阻断缺口（与生产同码，重签新 build 指纹）；缺口保持可见，不静默丢弃",
        attestation=ATTESTATION,
        gaps=tuple((key, "operator acknowledged in isolated B4.3 drill") for key in keys),
    )
    store.put_gap_review(review)
    return {"acknowledged": len(keys), "keys": keys, "required_locators": (target,)}


def main() -> None:
    result: dict = {
        "artifact": "b4.3-publish-drill",
        "version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "scope": "B4.3 isolated publish & rollback drill (real engine × i2_sandbox_corpus)",
        "isolation": {
            "production_dsn_read_only": True,
            "write_target": SANDBOX_DB,
            "zero_model": True,
            "source_archive": str(ARCHIVE),
            "new_archive": str(DRILL_ARCHIVE),
        },
        "phases": {},
    }
    gold = [
        json.loads(line) for line in GOLD.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    gold_source_ids = {
        t["source_id"]
        for row in gold
        for t in (row.get("evidence_targets") or []) + (row.get("supplementary_evidence_targets") or [])
    }
    # 6 来源（i3e1-approved 批准集；dev-lane 的 docx/md 两份不在本次演练范围）。
    queries = [row["question"] for row in gold]
    b4 = json.loads(B4_JSON.read_text(encoding="utf-8"))
    b1b3_by_prefix = {
        r["source_id"][:8]: r for r in b4["doc_level"]["b1b3"]
    }

    truncate_sandbox()

    with psycopg.connect(PROD_DSN, autocommit=True) as prod:
        prod.execute("SET default_transaction_read_only=on")
        ro = prod.execute("SHOW transaction_read_only").fetchone()[0]
        db = prod.execute("SELECT current_database()").fetchone()[0]
        if ro != "on" or db != "postgres":
            raise RuntimeError(f"生产连接非只读/非目标库: {ro!r} {db!r}")
        # 解析 gold 来源：<date>_<hash8> → 生产 source_id
        rows = prod.execute("SELECT source_id FROM corpus.corpus_sources").fetchall()
        by_prefix = {r[0][:8]: r[0] for r in rows}
        resolved = {
            gid: by_prefix[gid.split("_")[-1]] for gid in gold_source_ids if gid.split("_")[-1] in by_prefix
        }
        if len(resolved) != len(gold_source_ids):
            missing = sorted(gold_source_ids - set(resolved))
            raise RuntimeError(f"金标来源无法解析: {missing}")
        old_world = load_old_world(prod, tuple(sorted(set(resolved.values()))))

    source_ids = sorted(old_world)
    result["old_world_sources"] = [
        {"source_id": sid[:16], "old_build_id": old_world[sid]["build"].build_id[:16],
         "review": old_world[sid]["review"].decision_id,
         "decision_id": old_world[sid]["admission"].decision_id[:16],
         "units": len(old_world[sid]["units"]), "chunks": len(old_world[sid]["chunks"])}
        for sid in source_ids
    ]

    # ---- Phase 1：种子旧 world + 发布旧 build（gen1）----
    phase1: dict = {"seeded": [], "publications": {}}
    with PgStore(SANDBOX_DSN, sandbox_db=SANDBOX_DB) as store:
        for sid in source_ids:
            w = old_world[sid]
            store.put_source(w["source"])
            store.put_reviewed_decision(w["review"])
            store.put_admission(w["admission"])  # 指针 → 旧决定
            store.put_build(w["build"])
            seed_stage(store, w["build"].build_id, JobStage.PARSED, w["units"])
            if w.get("gap_review_checkpoint") is not None:
                # 具名缺口凭证随旧 world 复制（§7.3 放行阻断缺口的唯一凭证）。
                store.put_gap_review(GapReview.from_json(w["gap_review_checkpoint"]))
            seed_stage(store, w["build"].build_id, JobStage.CHUNKED, w["chunks"])
            pub = publish_build(
                store, w["build"].build_id, activated_at=DRIL_NOW,
                owner_id=OWNER, operator="b43-drill:seed-old-world",
            )
            phase1["seeded"].append(
                {"source_id": sid[:16], "old_build_id": w["build"].build_id[:16],
                 "generation": pub.generation}
            )
    with psycopg.connect(SANDBOX_DSN, autocommit=True) as conn:
        for sid in source_ids:
            phase1["publications"][sid[:16]] = publication_row(conn, sid)
    result["phases"]["phase1_seed_old_world"] = phase1
    print("phase1:", json.dumps({"generation": [p["generation"] for p in phase1["seeded"]]}, ensure_ascii=False))

    # ---- Phase 4a：旧版本固定快照（发布新版本前）----
    snap_old_20 = search_snapshot(queries, limit=20)
    snap_old_5 = search_snapshot(queries, limit=5)
    # 从旧命中挑取每来源 ≤2 个旧 chunk 作 fetch 快照（旧引用句柄）。
    fetch_items: list[tuple[str, str]] = []
    seen_chunks: dict[str, int] = {}
    for _qid, hits in snap_old_20.items():
        for h in hits:
            if seen_chunks.get(h["chunk_id"], 0) >= 2:
                continue
            seen_chunks[h["chunk_id"]] = seen_chunks.get(h["chunk_id"], 0) + 1
            fetch_items.append((build_handle(h["build_id"]), chunk_locator(h["chunk_id"])))
    fetch_old = fetch_snapshot(fetch_items)
    phase4a = {
        "queries": len(queries),
        "query_form": "retrieval_query(question)（实质词元 OR，websearch 语法）",
        "old_active_build_ids": sorted({h["build_id"] for hits in snap_old_20.values() for h in hits}),
        "old_fetch_refs": len(fetch_old),
        "hit_count": sum(len(v) for v in snap_old_20.values()),
    }
    result["phases"]["phase4a_old_snapshot"] = phase4a
    print("phase4a:", json.dumps(phase4a, ensure_ascii=False))

    # ---- Phase 2：真实引擎构建新 build（reader-pdf-7 + chunk-4，v1 政策）----
    policy = load_admission_policy(POLICY_PATH)
    entries = [
        PlanEntry(
            path=str(ARCHIVE / old_world[sid]["source"].archive_path),
            original_name=old_world[sid]["source"].original_names[0],
            domain_hint=old_world[sid]["review"].research_domain,
            review_decision_ids=(old_world[sid]["review"].decision_id,),
        )
        for sid in source_ids
    ]
    plan = plan_builds(entries, policy=policy)
    phase2: dict = {"policy_rev": policy.policy_rev, "builds": {}}
    with PgStore(SANDBOX_DSN, sandbox_db=SANDBOX_DB) as store:
        report = execute_builds(
            store, plan, policy=policy, archive_root=DRILL_ARCHIVE,
            owner_id=OWNER, now=DRIL_NOW, lease=LEASE,
        )
        for outcome in report.outcomes:
            sid = outcome.source.source_id
            if outcome.admission.decision.value != "in_scope" or outcome.build is None:
                raise RuntimeError(
                    f"来源未获 in_scope 构建（v1 政策重判）: {sid[:16]} "
                    f"{outcome.admission.decision.value} {outcome.admission.reason_codes}"
                )
            # 操作者动作：新 build 阻断缺口（与旧 build 同码）先签具名凭证，才可发布。
            ack = _ack_blocking_gaps(store, outcome.build)
            check_build_publishable(store, outcome.build.build_id)
            phase2["builds"][sid[:16]] = {
                "new_build_id": outcome.build.build_id,
                "decision_id": outcome.admission.decision_id,
                "parse_rev": outcome.build.parse_rev[:16],
                "clean_rev": outcome.build.clean_rev[:16],
                "chunk_rev": outcome.build.chunk_rev[:16],
                "unit_count": outcome.unit_count,
                "chunk_count": outcome.chunk_count,
                "gap_review_acknowledged": ack["acknowledged"],
                "gap_review_keys": ack["keys"],
            }
    result["phases"]["phase2_build_new"] = phase2
    print("phase2:", json.dumps({k: {k2: v2 for k2, v2 in v.items() if k2 != "decision_id"} for k, v in phase2["builds"].items()}, ensure_ascii=False))

    # ---- Phase 3：可复现性对照（真实引擎落库 vs B4.1 b1b3 内存对照）----
    phase3: dict = {"reproducible": True, "rows": [], "failures": []}
    with psycopg.connect(SANDBOX_DSN, autocommit=True) as conn:
        for sid in source_ids:
            new_bid = phase2["builds"][sid[:16]]["new_build_id"]
            art = load_source_artifacts(conn, new_bid)
            expect = b1b3_by_prefix[sid[:8]]
            kind_hist = dict(Counter(c["kind"] for c in art["chunks"]))
            row = {
                "source_id": sid[:16],
                "gold_source_id": expect["gold_source_id"],
                "new_units": len(art["units"]),
                "expected_units": expect["new_units"],
                "new_chunks": len(art["chunks"]),
                "expected_chunks": expect["new_chunks"],
                "kind_hist": kind_hist,
                "expected_kind_hist": expect.get("kind_hist"),
                "doc_norm_chars": len(art["doc_norm"]),
                "expected_doc_norm_chars": expect["new_doc_norm_chars"],
            }
            mism = []
            if row["new_units"] != row["expected_units"]:
                mism.append("units")
            if row["new_chunks"] != row["expected_chunks"]:
                mism.append("chunks")
            if row["doc_norm_chars"] != row["expected_doc_norm_chars"]:
                mism.append("doc_norm_chars")
            if kind_hist != (expect.get("kind_hist") or {}):
                mism.append("kind_hist")
            row["mismatches"] = mism
            if mism:
                phase3["reproducible"] = False
                phase3["failures"].append(mism)
            phase3["rows"].append(row)
    result["phases"]["phase3_reproducibility"] = phase3
    if not phase3["reproducible"]:
        raise RuntimeError(f"可复现性对照失败: {phase3['failures']}")
    print("phase3: reproducible, total_chunks=",
          sum(r["new_chunks"] for r in phase3["rows"]),
          "total_units=", sum(r["new_units"] for r in phase3["rows"]))

    # ---- Phase 4b：发布新 build（gen2）+ 版本身份断言 ----
    phase4b: dict = {"published": [], "new_active_build_ids": [], "old_handle_preserved": {}}
    with PgStore(SANDBOX_DSN, sandbox_db=SANDBOX_DB) as store:
        for sid in source_ids:
            new_bid = phase2["builds"][sid[:16]]["new_build_id"]
            pub = publish_build(
                store, new_bid, activated_at=DRIL_NOW,
                owner_id=OWNER, operator="b43-drill:publish-new",
            )
            phase4b["published"].append(
                {"source_id": sid[:16], "new_build_id": new_bid[:16], "generation": pub.generation}
            )
    snap_new_20 = search_snapshot(queries, limit=20)
    new_ids = {phase2["builds"][sid[:16]]["new_build_id"] for sid in source_ids}
    old_ids = {w["build"].build_id for w in old_world.values()}
    hit_builds = {h["build_id"] for hits in snap_new_20.values() for h in hits}
    if not (hit_builds <= new_ids and not (hit_builds & old_ids)):
        raise RuntimeError(f"新发布后检索仍命中旧 build 或混入新 build 外 id: {sorted(hit_builds)[:5]}")
    # 旧句柄不被静默升级：跨发布后仍取回旧 build 的不可变正文。
    fetch_after_new = fetch_snapshot(fetch_items)
    diff = {
        k: v for k, v in fetch_after_new.items()
        if v["text_hash"] != fetch_old[k]["text_hash"] or v["build_id"] != fetch_old[k]["build_id"]
    }
    phase4b["new_active_build_ids"] = sorted(hit_builds)[:8]
    phase4b["old_handle_preserved"] = {
        "refs": len(fetch_items),
        "changed": len(diff),
        "build_id_flipped": [k for k in diff if fetch_after_new[k]["build_id"] != fetch_old[k]["build_id"]][:3],
        "all_old_hits_vanished_from_search": True,
    }
    if diff:
        raise RuntimeError(f"旧句柄内容或版本变化: {list(diff)[:3]}")
    with psycopg.connect(SANDBOX_DSN, autocommit=True) as conn:
        phase4b["publications"] = {sid[:16]: publication_row(conn, sid) for sid in source_ids}
    result["phases"]["phase4b_publish_new_identity"] = phase4b
    print("phase4b:", json.dumps({"generation": [p["generation"] for p in phase4b["published"]],
                                  "old_handle_preserved": phase4b["old_handle_preserved"]}, ensure_ascii=False))

    # ---- Phase 5：回滚（retire 撤下 → 复位旧决定指针 → 重发旧 build）+ 重放断言 ----
    phase5: dict = {"retired": [], "rolled_back": [], "replay": {}}
    with PgStore(SANDBOX_DSN, sandbox_db=SANDBOX_DB) as store:
        for sid in source_ids:
            new_dec = phase2["builds"][sid[:16]]["decision_id"]
            retired = store.retire(sid, new_dec, DRIL_NOW)
            phase5["retired"].append({"source_id": sid[:16], "active_build_id": retired.active_build_id,
                                      "generation": retired.generation})
        # 操作者回滚动作：直接复位来源指针到旧决定（Store Seam 无指针回退 API，见模块 docstring）。
        with store._conn.cursor() as cur:
            for sid in source_ids:
                cur.execute(
                    "UPDATE corpus.corpus_sources SET current_decision_id=%s WHERE source_id=%s",
                    (old_world[sid]["admission"].decision_id, sid),
                )
        for sid in source_ids:
            old_bid = old_world[sid]["build"].build_id
            pub = publish_build(
                store, old_bid, activated_at=DRIL_NOW,
                owner_id=OWNER, operator="b43-drill:rollback-old",
            )
            phase5["rolled_back"].append(
                {"source_id": sid[:16], "old_build_id": old_bid[:16], "generation": pub.generation}
            )
    snap_rollback_20 = search_snapshot(queries, limit=20)
    snap_rollback_5 = search_snapshot(queries, limit=5)
    fetch_rollback = fetch_snapshot(fetch_items)

    # 重放：旧检索/旧引用/旧分页逐条与旧快照比对。
    search_diff = {
        qid: v for qid, v in snap_rollback_20.items() if v != snap_old_20[qid]
    }
    fetch_diff = {
        k: v for k, v in fetch_rollback.items()
        if v["text_hash"] != fetch_old[k]["text_hash"] or v["build_id"] != fetch_old[k]["build_id"]
    }
    page_diff = {
        qid: v for qid, v in snap_rollback_5.items()
        if v != snap_old_5[qid] or v != snap_old_20[qid][: len(v)]
    }
    rb_ids = {h["build_id"] for hits in snap_rollback_20.values() for h in hits}
    phase5["replay"] = {
        "search_hits_match_old_snapshot": len(search_diff) == 0,
        "search_diff_queries": sorted(search_diff)[:3],
        "fetch_refs": len(fetch_diff),
        "fetch_all_unchanged": len(fetch_diff) == 0,
        "pagination_rollback_matches_old": len(page_diff) == 0,
        "page_diff_queries": sorted(page_diff)[:3],
        "rolled_back_active_build_ids": sorted(rb_ids)[:8],
        "old_build_active_again": rb_ids == {h["build_id"] for hits in snap_old_20.values() for h in hits},
    }
    if search_diff or fetch_diff or page_diff:
        raise RuntimeError("回滚重放断言失败（检索/引用/分页）")
    with psycopg.connect(SANDBOX_DSN, autocommit=True) as conn:
        phase5["publications"] = {sid[:16]: publication_row(conn, sid) for sid in source_ids}
    result["phases"]["phase5_rollback_replay"] = phase5
    print("phase5:", json.dumps({"rolled_back_generations": [p["generation"] for p in phase5["rolled_back"]],
                                 "replay": phase5["replay"]}, ensure_ascii=False))

    # ---- 汇总 ----
    result["summary"] = {
        "sources": len(source_ids),
        "old_total_units": sum(len(old_world[s]["units"]) for s in source_ids),
        "old_total_chunks": sum(len(old_world[s]["chunks"]) for s in source_ids),
        "new_total_units": sum(phase3["rows"][i]["new_units"] for i in range(len(source_ids))),
        "new_total_chunks": sum(phase3["rows"][i]["new_chunks"] for i in range(len(source_ids))),
        "generation_sequence": {
            "phase1_old_publish": {p["source_id"]: p["generation"] for p in phase1["seeded"]},
            "phase4b_new_publish": {p["source_id"]: p["generation"] for p in phase4b["published"]},
            "phase5_retire": {p["source_id"]: p["generation"] for p in phase5["retired"]},
            "phase5_rollback_old": {p["source_id"]: p["generation"] for p in phase5["rolled_back"]},
        },
        "checks": {
            "1_reproducible": phase3["reproducible"],
            "2_identity_bound_new": not (hit_builds & old_ids),
            "3_old_build_still_available": len(fetch_old) == len(fetch_after_new),
            "4_old_cursor_not_upgraded": len(diff) == 0,
            "5_rollback_restores_compatible": phase5["replay"]["old_build_active_again"],
        },
        "models_absent": not any(x in sys.modules for x in ("openai", "anthropic")),
    }

    (OUT / "b43-publish-drill.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    print("drill_json:", OUT / "b43-publish-drill.json")


if __name__ == "__main__":
    main()
