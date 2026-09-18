"""I2-1 DDL 校验：内省实际对象并与冻结映射逐一比对（验收门：字段映射一致）。

期望结构 = design-review.json（i0c-r1 冻结，签认版 sha=3c346c61…）§i0c_1_candidates
ddl_mapping + §store_persistence_mapping 的代码化；本文件即两者的机器可核对照。

产出：write-once 报告 i2s1-report-r3.json（目标事实/对象清单/比对结果/证据哈希；不含凭据）。
r3 修订：I2-3（C13）读侧筛选索引入 DDL（idx_builds_source/idx_builds_decision/
idx_admissions_domain/idx_admissions_report_pub/idx_publications_active_build），
校验新增 index_names 全集比对。
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

import psycopg

REPO = Path(__file__).resolve().parents[4]
BASE = REPO / ".scratch/corpus-evidence-pipeline/ingestion-rebuild"
REPORT = BASE / "i2/i2s1-report-r3.json"
SANDBOX_DB = "i2_sandbox_corpus"

# 期望：表 → 列集合（源自 design-review ddl_mapping；列序不敏感、多列/少列均 MISS）
EXPECTED_COLUMNS: dict[str, set[str]] = {
    "corpus_sources": {"source_id", "format", "mime_type", "size_bytes", "archive_path",
                       "original_names", "current_decision_id"},
    "corpus_review_decisions": {"decision_id", "source_id", "reviewer", "reviewed_at", "decision",
                                "rationale", "scope_ref", "supersedes", "locators",
                                "material_type", "research_domain"},
    "corpus_admissions": {"decision_id", "source_id", "material_type", "research_domain",
                          "decision", "policy_rev", "reason_codes", "scope_ref",
                          "evidence_refs", "review_ref", "rule_rev", "metadata_snapshot"},
    "corpus_builds": {"build_id", "source_id", "decision_id", "parse_rev", "clean_rev",
                      "chunk_rev", "index_rev", "scope_ref", "config_fingerprint",
                      "artifact_manifest", "quality_report"},
    "corpus_units": {"build_id", "unit_id", "parent_id", "ordinal", "kind", "raw_text",
                     "content_hash", "location", "clean_view", "mapping", "status", "reasons"},
    "corpus_chunks": {"build_id", "chunk_id", "kind", "unit_refs", "context_refs",
                      "search_text", "title_text", "section_path", "source_ranges", "search_tsv"},
    "corpus_publications": {"source_id", "current_decision_id", "active_build_id",
                            "generation", "activated_at"},
    "corpus_jobs": {"build_id", "stage", "attempt", "state", "owner_id", "fence_token",
                    "lease_until", "heartbeat_at", "error", "checkpoint"},
    "corpus_source_checkpoints": {"source_id", "stage", "checkpoint", "updated_at"},
}
EXPECTED_FKS: set[tuple[str, str, str]] = {
    # corpus_review_decisions.source_id 无 FK（i0c-r2 修正）：审核终态先于新链接收存在，
    # FK 会令先审后收流程不可行；以普通索引 idx_review_decisions_source 替代。
    ("corpus_admissions", "source_id", "corpus_sources"),
    ("corpus_review_decisions", "supersedes", "corpus_review_decisions"),
    ("corpus_builds", "source_id", "corpus_sources"),
    ("corpus_builds", "decision_id", "corpus_admissions"),
    ("corpus_units", "build_id", "corpus_builds"),
    ("corpus_chunks", "build_id", "corpus_builds"),
    ("corpus_publications", "source_id", "corpus_sources"),
    ("corpus_publications", "current_decision_id", "corpus_admissions"),
    ("corpus_publications", "active_build_id", "corpus_builds"),
    ("corpus_jobs", "build_id", "corpus_builds"),
    ("corpus_sources", "current_decision_id", "corpus_admissions"),
}
EXPECTED_PKS: dict[str, list[str]] = {
    "corpus_sources": ["source_id"],
    "corpus_review_decisions": ["decision_id"],
    "corpus_admissions": ["decision_id"],
    "corpus_builds": ["build_id"],
    "corpus_units": ["build_id", "unit_id"],
    "corpus_chunks": ["build_id", "chunk_id"],
    "corpus_publications": ["source_id"],
    "corpus_jobs": ["build_id", "stage", "attempt"],
    "corpus_source_checkpoints": ["source_id", "stage"],
}


def _dsn() -> str:
    raw = os.environ.get("CORPUS_I2_DSN", "")
    if not raw or "corpus-guard" in raw:
        raise SystemExit("拒绝：CORPUS_I2_DSN 未设置或为守卫哨兵")
    return raw


def main() -> int:
    dsn = _dsn()
    sandbox_dsn = f"postgresql://{dsn.split('//', 1)[1].rsplit('/', 1)[0]}/{SANDBOX_DB}"
    checks: list[dict] = []

    def check(name: str, ok: bool, detail: str) -> None:
        checks.append({"check": name, "ok": ok, "detail": detail})
        print(f"  [{'ok' if ok else 'MISS'}] {name}: {detail}")

    with psycopg.connect(sandbox_dsn) as conn, conn.cursor() as cur:
            cur.execute("SELECT current_database()")
            db_row = cur.fetchone()
            check("target_database", db_row is not None and db_row[0] == SANDBOX_DB, SANDBOX_DB)
            cur.execute("SELECT datname FROM pg_database WHERE datallowconn")
            dbs = {r[0] for r in cur.fetchall()}
            check("not_production_instance", "apodex" not in dbs, f"databases={sorted(dbs)}")

            cur.execute(
                "SELECT c.relname, a.attname FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped "
                "WHERE n.nspname = 'corpus' AND c.relkind = 'r' ORDER BY c.relname, a.attnum"
            )
            actual: dict[str, set[str]] = {}
            for rel, col in cur.fetchall():
                actual.setdefault(rel, set()).add(col)
            check("table_set", set(actual) == set(EXPECTED_COLUMNS),
                  f"expected 9 tables, actual {sorted(actual)}")
            for table, expected in EXPECTED_COLUMNS.items():
                got = actual.get(table, set())
                check(f"columns:{table}", got == expected,
                      "match" if got == expected else
                      f"missing={sorted(expected - got)} extra={sorted(got - expected)}")

            cur.execute(
                "SELECT tc.relname, kcu.attname, ccu.relname AS foreign_table "
                "FROM pg_constraint con "
                "JOIN pg_class tc ON tc.oid = con.conrelid "
                "JOIN pg_namespace n ON n.oid = tc.relnamespace "
                "JOIN pg_class ccu ON ccu.oid = con.confrelid "
                "JOIN pg_attribute kcu ON kcu.attrelid = con.conrelid "
                "AND kcu.attnum = ANY(con.conkey) "
                "WHERE con.contype = 'f' AND n.nspname = 'corpus'"
            )
            fks = {(r[0], r[1], r[2]) for r in cur.fetchall()}
            check("foreign_keys", fks == EXPECTED_FKS,
                  "match" if fks == EXPECTED_FKS else f"diff={fks ^ EXPECTED_FKS}")

            for table, cols in EXPECTED_PKS.items():
                cur.execute(
                    "SELECT kcu.attname FROM pg_constraint con "
                    "JOIN pg_class tc ON tc.oid = con.conrelid "
                    "JOIN pg_namespace n ON n.oid = tc.relnamespace "
                    "JOIN pg_attribute kcu ON kcu.attrelid = con.conrelid "
                    "AND kcu.attnum = ANY(con.conkey) "
                    "WHERE con.contype = 'p' AND n.nspname = 'corpus' AND tc.relname = %s "
                    "ORDER BY kcu.attnum",
                    (table,),
                )
                pk = [r[0] for r in cur.fetchall()]
                check(f"pk:{table}", pk == cols, f"expected={cols} actual={pk}")

            cur.execute(
                "SELECT indexdef FROM pg_indexes WHERE schemaname = 'corpus' "
                "AND indexname = 'uq_jobs_single_running'"
            )
            row = cur.fetchone()
            uq_ok = row is not None and "WHERE" in row[0] and "running" in row[0]
            check("jobs_single_running_partial_unique", uq_ok,
                  row[0] if row else "index missing")

            cur.execute("SELECT indexname FROM pg_indexes WHERE schemaname = 'corpus'")
            index_names = {r[0] for r in cur.fetchall()}
            expected_indexes = {
                *(f"{t}_pkey" for t in EXPECTED_COLUMNS),
                "idx_review_decisions_source", "idx_chunks_tsv", "idx_chunks_unitrefs",
                "idx_builds_source", "idx_builds_decision", "idx_admissions_domain",
                "idx_admissions_report_pub", "idx_publications_active_build",
                "uq_jobs_single_running", "idx_jobs_current",
            }
            check("index_names", index_names == expected_indexes,
                  "match" if index_names == expected_indexes else
                  f"missing={sorted(expected_indexes - index_names)} "
                  f"extra={sorted(index_names - expected_indexes)}")

            cur.execute(
                "SELECT a.attname, pg_get_expr(d.adbin, d.adrelid) FROM pg_attrdef d "
                "JOIN pg_class c ON c.oid = d.adrelid "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = d.adnum "
                "WHERE n.nspname = 'corpus' AND c.relname = 'corpus_chunks' AND a.attname = 'search_tsv'"
            )
            gen = cur.fetchone()
            gen_ok = gen is not None and "to_tsvector('zhcfg'::regconfig, search_text)" in gen[1]
            check("chunks_search_tsv_generated_zhcfg", gen_ok, gen[1] if gen else "missing")

            cur.execute(
                "SELECT extname, extversion FROM pg_extension WHERE extname IN ('zhparser', 'pg_trgm', 'vector') ORDER BY 1"
            )
            exts = {r[0]: r[1] for r in cur.fetchall()}
            check("extensions", set(exts) == {"zhparser", "pg_trgm", "vector"}, json.dumps(exts))
            cur.execute("SELECT 1 FROM pg_ts_config WHERE cfgname = 'zhcfg'")
            check("zhcfg_exists", cur.fetchone() is not None, "text search configuration zhcfg")

            cur.execute(
                "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'corpus' AND c.relkind = 'r' AND c.reltuples::bigint > 0"
            )
            count_row = cur.fetchone()
            check("no_data_yet", count_row is not None and count_row[0] == 0,
                  "DDL 演练零数据行（I2-2 起写入）")

    all_ok = all(item["ok"] for item in checks)
    design_sha = hashlib.sha256((BASE / "design-review.json").read_bytes()).hexdigest()
    schema_sha = hashlib.sha256((BASE / "i2/sandbox_schema.sql").read_bytes()).hexdigest()
    guard_sha = hashlib.sha256((BASE / "guards/i2-sandbox.json").read_bytes()).hexdigest()
    report = {
        "artifact": "i2s1-report.json",
        "task": "I2-1 隔离库 DDL 演练 r3（i0c 布局 + I2-3/C13 读侧筛选索引；验收门：字段映射一致）",
        "all_ok": all_ok,
        "checks": checks,
        "evidence": {
            "design_review_sha256": design_sha,
            "sandbox_schema_sql_sha256": schema_sha,
            "guard_i2_sandbox_sha256": guard_sha,
            "apply_script": "i2/i2s1_apply.py",
            "verify_script": "i2/i2s1_verify.py",
            "teardown_script": "i2/i2s1_teardown.py（临时对象清理精确范围：仅 corpus schema）",
        },
        "next": "I2-3 FTS 读侧（search_pg.py）已落地；I2-4 起解析/分块以 i2_sandbox_corpus 为演练目标",
    }
    if not all_ok:
        # write-once 报告仅在全部命中时落盘；失败态留痕于会话输出，不占报告位。
        print("校验未全过：报告未写（write-once 位留给通过态）")
        return 1
    if REPORT.exists():
        raise SystemExit(f"拒绝：报告已存在（write-once）: {REPORT}")
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"汇总: 全部命中；报告 {REPORT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
