"""I4-close 阶段 2 前置导出（i4-reset-manifest.json phases[1].tables export 义务）：

- blocks 行 note：「旧证据引用定位对照件随 I4-close 导出」→
  i4c-old-evidence-locator-crosswalk.jsonl（引用对 ← 三份导出台账；块内容 ← 现存
  public.blocks，阶段 2 TRUNCATE 前最后一次读取机会）；
- documents 行 note：「doc_id→source_id 映射 manifest 随 I4-close 导出」→
  i4c-docid-source-map.json（public.documents 全 89 行源身份；content_hash16 为新链
  corpus.corpus_sources.source_id 的 16-hex 前缀，精确 join，例证 6f14cc14…）。

只读 DB（READ ONLY 事务）+ 只读台账；write-once 三个文件；零模型调用。
守卫 lane：python DB 操作走守卫（i47_reset_phase1 同 lane）。
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

ROOT = Path("/home/administrator/FrontierAgent")
ING = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild"
AUD = ING / "audits/20260923-i4-window"
OUT_DIR = AUD / "i4c-exports"
LEDGERS = ING / "backups/i4-final-20260923T1544Z/ledgers"
BACKUP_MANIFEST_SHA = "085abf4c499bc0fc24a69abfe1e8d71634b4b9efbad097b81ca24d9f3bb648fb"
PG_DSN = "postgresql://postgres:postgres@127.0.0.1:5432/postgres"

CROSSWALK_OUT = OUT_DIR / "i4c-old-evidence-locator-crosswalk.jsonl"
SOURCemap_OUT = OUT_DIR / "i4c-docid-source-map.json"
MANIFEST_OUT = OUT_DIR / "i4c-exports-manifest.json"

_INT_RE = re.compile(r"^\d+$")


def _abort(msg: str) -> None:
    raise SystemExit(f"拒绝（漂移即停）：{msg}")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _collect_refs() -> dict[tuple[str, str], dict[str, int]]:
    """三份导出台账收集 (doc_id, locator) 引用对（locator 原样保留）。"""
    refs: dict[tuple[str, str], dict[str, int]] = {}

    def _add(doc_id: str, locator: str, kind: str) -> None:
        if not doc_id or locator is None:
            return
        key = (str(doc_id), str(locator))
        slot = refs.setdefault(key, {"claims": 0, "evidence_facts": 0, "block_runs": 0})
        slot[kind] += 1

    with (LEDGERS / "claims.jsonl").open(encoding="utf-8") as fh:
        for line in fh:
            row = json.loads(line)
            _add(row.get("doc_id"), row.get("locator"), "claims")
    with (LEDGERS / "claim_block_runs.jsonl").open(encoding="utf-8") as fh:
        for line in fh:
            row = json.loads(line)
            _add(row.get("doc_id"), row.get("seq"), "block_runs")
    with (LEDGERS / "corpus_evidence_runs.jsonl").open(encoding="utf-8") as fh:
        for line in fh:
            row = json.loads(line)
            run_doc = row.get("doc_id")
            payload = row.get("payload") or {}
            facts = payload.get("facts") if isinstance(payload, dict) else None
            if isinstance(facts, list):
                for fact in facts:
                    if not isinstance(fact, dict):
                        continue
                    _add(fact.get("doc_id") or run_doc, fact.get("locator"), "evidence_facts")
    return refs


def main() -> int:
    if OUT_DIR.exists():
        _abort(f"导出目录已存在（write-once）：{OUT_DIR}")
    tz = timezone(timedelta(hours=8))

    # 门 1：台账来源完整性（备份 artifact-manifest.sha256 与 i47 阶段 1 同一绑定）
    backup_dir = LEDGERS.parent
    amf = backup_dir / "artifact-manifest.sha256"
    if _sha(amf) != BACKUP_MANIFEST_SHA:
        _abort(f"artifact-manifest.sha256 哈希漂移：{_sha(amf)[:16]}…")
    for name in ("claims.jsonl", "claim_block_runs.jsonl", "corpus_evidence_runs.jsonl"):
        if not (LEDGERS / name).is_file():
            _abort(f"导出台账缺失：{name}")

    refs = _collect_refs()
    if not refs:
        _abort("台账引用对为空（异常：claims 1318 行不应零引用）")

    OUT_DIR.mkdir(parents=True)

    # 门 2：只读读取现存 blocks/documents + corpus.corpus_sources
    with psycopg.connect(PG_DSN, autocommit=True, row_factory=dict_row) as conn, conn.cursor() as cur:
        cur.execute("SET TRANSACTION READ ONLY")
        cur.execute("SELECT current_database() AS db")
        if cur.fetchone()["db"] != "postgres":
            _abort("current_database ≠ postgres")

        cur.execute("SELECT doc_id, seq, locator, text FROM public.blocks")
        blocks: dict[tuple[str, int], dict] = {}
        for row in cur.fetchall():
            blocks[(row["doc_id"], int(row["seq"]))] = row

        cur.execute(
            "SELECT doc_id, title, source_path, content_hash, mime, status, char_count,"
            " block_count, ingested_at, published, doc_kind, subject, org"
            " FROM public.documents ORDER BY doc_id"
        )
        documents = [dict(r) for r in cur.fetchall()]
        if len(documents) != 89:
            _abort(f"documents 行数漂移：{len(documents)} ≠ 89")

        cur.execute("SELECT source_id, original_names FROM corpus.corpus_sources")
        sources = [dict(r) for r in cur.fetchall()]

    # ── 对照件 1：旧证据引用定位 crosswalk ──
    matched = unmatched_non_numeric = unmatched_missing_block = 0
    crosswalk_rows: list[str] = []
    for (doc_id, locator), by in sorted(refs.items()):
        seq = int(locator) if _INT_RE.match(str(locator)) else None
        block = blocks.get((doc_id, seq)) if seq is not None else None
        if block is not None:
            matched += 1
            crosswalk_rows.append(json.dumps({
                "doc_id": doc_id,
                "locator": locator,
                "block_seq": block["seq"],
                "block_locator": block["locator"],
                "block_text": block["text"],
                "referenced_by": by,
            }, ensure_ascii=False))
        elif seq is None:
            unmatched_non_numeric += 1
            crosswalk_rows.append(json.dumps({
                "doc_id": doc_id, "locator": locator, "resolved": False,
                "reason": "non_numeric_locator", "referenced_by": by,
            }, ensure_ascii=False))
        else:
            unmatched_missing_block += 1
            crosswalk_rows.append(json.dumps({
                "doc_id": doc_id, "locator": locator, "resolved": False,
                "reason": "block_not_found_in_blocks_table", "referenced_by": by,
            }, ensure_ascii=False))
    CROSSWALK_OUT.write_text("\n".join(crosswalk_rows) + "\n", encoding="utf-8")

    # ── 对照件 2：doc_id→source_id 映射（content_hash16 → source_id 前缀 join）──
    prefix_index: dict[str, list[str]] = {}
    for s in sources:
        prefix_index.setdefault(str(s["source_id"])[:16], []).append(str(s["source_id"]))
    joined = 0
    for doc in documents:
        for key in ("ingested_at", "published"):
            if doc.get(key) is not None:
                doc[key] = doc[key].isoformat()
        prefix = str(doc["content_hash"])
        hits = prefix_index.get(prefix, [])
        doc["new_chain_source_id"] = hits[0] if len(hits) == 1 else None
        doc["new_chain_source_id_join"] = (
            "unique_16hex_prefix" if len(hits) == 1
            else f"ambiguous_{len(hits)}" if hits else "no_match")
        if len(hits) == 1:
            joined += 1
    source_map = {
        "artifact": "i4c-docid-source-map",
        "note": "旧链 public.documents 全量源身份；content_hash（16-hex）为冻结新链"
                " corpus.corpus_sources.source_id 的前缀（唯一即 join），供旧 evidence.doc_id"
                " 解析到已归档原件（backups/i4-final-20260923T1544Z + originals-corpus.tar.gz）",
        "exported_at": datetime.now(tz).isoformat(timespec="seconds"),
        "documents_total": len(documents),
        "joined_to_new_chain": joined,
        "documents": documents,
    }
    SOURCemap_OUT.write_text(json.dumps(source_map, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    manifest = {
        "artifact": "i4c-exports",
        "created_at": datetime.now(tz).isoformat(timespec="seconds"),
        "authority": "i4-reset-manifest.json phases[1].tables[].export（随 I4-close 导出义务）",
        "inputs": {
            "backup_artifact_manifest_sha256": BACKUP_MANIFEST_SHA,
            "ledger_dir": str(LEDGERS.relative_to(ROOT)),
            "reference_pairs_from_ledgers": len(refs),
            "blocks_rows_read": len(blocks),
            "documents_rows_read": len(documents),
            "corpus_sources_rows_read": len(sources),
        },
        "crosswalk": {
            "file": CROSSWALK_OUT.name,
            "sha256": _sha(CROSSWALK_OUT),
            "rows": len(crosswalk_rows),
            "matched": matched,
            "unmatched_non_numeric": unmatched_non_numeric,
            "unmatched_missing_block": unmatched_missing_block,
        },
        "docid_source_map": {
            "file": SOURCemap_OUT.name,
            "sha256": _sha(SOURCemap_OUT),
            "documents_total": len(documents),
            "joined_to_new_chain": joined,
        },
        "zero_model": True,
        "db_tx": "READ ONLY（无双写；blocks/documents 仍为 1101/89，阶段 2 前原样）",
    }
    MANIFEST_OUT.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
