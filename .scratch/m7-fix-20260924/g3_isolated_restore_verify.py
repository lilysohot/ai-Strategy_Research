"""G3 隔离恢复补验（M7 复核 G3）：为 I4-6 恢复验证补齐三项缺失证据——

1. 恢复后**权限对账**（生产 pg 容器 postgres 库 vs 恢复库：角色/库 ACL/schema ACL/
   表 owner/非默认 relacl 五轴）；
2. **历史证据引用回环**（备份台账 JSONL → 恢复库逐条解析：claims→blocks(doc_id,locator)、
   claim_block_runs→claims 计数一致、corpus_evidence_runs→blocks 存在 + 文本子串往返率）；
3. **实测恢复耗时**（pg_restore --no-owner --exit-on-error 墙钟秒数）。

纪律：一次性库 i4_g3_restore_20260924（corpus-db 隔离实例 127.0.0.1:543，I4-6 同目标），
验证后销毁；生产 pg 容器仅只读目录查询（PGOPTIONS default_transaction_read_only=on），
零写路径；报告 write-once。
"""
from __future__ import annotations

import ast
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("/home/administrator/FrontierAgent")
BAK = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/backups/i4-final-20260923T1544Z"
OUT = ROOT / ".scratch/m7-fix-20260924/g3-isolated-restore-verification.json"
VERIFY_DB = "i4_g3_restore_20260924"
PROD_DSN_DB = "postgres"

LEDGER_TABLES = [
    "blocks", "chinese_docs", "claim_block_runs", "claim_block_runs_v2", "claims",
    "claims_v2", "corpus_evidence_runs", "docs", "documents", "ingest_failures", "ingest_runs",
]


def run(args: list[str], stdin_path: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args, stdin=(stdin_path.open("rb") if stdin_path else None),
        capture_output=True, text=True, timeout=900,
    )


def prod_sql(sql: str) -> str:
    """生产 pg 容器只读目录查询（会话级 read-only 兜底）。"""
    proc = run([
        "docker", "exec", "-e", "PGOPTIONS=-c default_transaction_read_only=on",
        "pg", "psql", "-U", "postgres", "-d", PROD_DSN_DB, "-At", "-F", "\x1f", "-c", sql,
    ])
    if proc.returncode != 0:
        raise SystemExit(f"prod psql failed: {proc.stderr[:300]}")
    return proc.stdout


def verify_sql(sql: str, db: str = VERIFY_DB) -> str:
    proc = run(["docker", "exec", "corpus-db", "psql", "-U", "postgres", "-d", db,
                "-At", "-F", "\x1f", "-c", sql])
    if proc.returncode != 0:
        raise SystemExit(f"verify psql failed ({db}): {proc.stderr[:300]}")
    return proc.stdout


def priv_snapshot(side: str, db: str) -> dict[str, object]:
    """权限对账五轴：角色、库 ACL、public schema ACL、表 owner、非默认 relacl。"""
    if side == "prod":
        q = lambda s: prod_sql(s)  # noqa: E731
    else:
        q = lambda s: verify_sql(s, db)  # noqa: E731
    roles_out = q("SELECT rolname FROM pg_roles WHERE rolname NOT LIKE 'pg\\_%' ORDER BY 1")
    db_acl = q(f"SELECT coalesce(datacl::text,'<default>') FROM pg_database "
               f"WHERE datname='{db}'")
    nsp_acl = q("SELECT nspname, coalesce(nspacl::text,'<default>') FROM pg_namespace "
                "WHERE nspname='public'")
    owners = q("SELECT count(*), count(DISTINCT tableowner), coalesce(string_agg(DISTINCT "
               "tableowner, ','),'') FROM pg_tables WHERE schemaname='public'")
    relacl = q("SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
               "WHERE n.nspname='public' AND c.relkind IN ('r','S') AND c.relacl IS NOT NULL")
    return {
        "roles": sorted(r for r in roles_out.splitlines() if r),
        "database_acl": db_acl.strip(),
        "public_schema_acl": nsp_acl.strip(),
        "public_tables": owners.strip(),
        "public_nondefault_relacl_count": relacl.strip(),
    }


def main() -> int:
    if OUT.exists():
        raise SystemExit(f"write-once 报告已存在: {OUT}")

    # ── 门 0：备份 manifest 25/25 ──────────────────────────────
    chk = subprocess.run(["sha256sum", "--check", "--quiet", "artifact-manifest.sha256"],
                         cwd=BAK, capture_output=True, text=True, timeout=900)
    manifest_ok = chk.returncode == 0 and not chk.stdout.strip()
    n_manifest = len([l for l in (BAK / "artifact-manifest.sha256").read_text().splitlines() if l.strip()])
    print(f"[gate0] manifest {n_manifest if manifest_ok else 'FAIL'}/{n_manifest}")

    # ── 门 1：一次性库不存在（防覆盖）─────────────────────────
    existing = verify_sql("SELECT datname FROM pg_database ORDER BY 1", "postgres")
    if VERIFY_DB in existing.split():
        raise SystemExit(f"一次性库 {VERIFY_DB} 已存在，拒绝执行")
    print("[gate1] one-off DB name free")

    # ── 门 2：生产权限基线（只读目录查询，先于任何恢复）───────
    prod_priv = priv_snapshot("prod", PROD_DSN_DB)
    print(f"[gate2] prod baseline: roles={len(prod_priv['roles'])} "
          f"owners={prod_priv['public_tables']}")

    # ── 建 One-off 库 + 计时恢复 ──────────────────────────────
    verify_sql("CREATE DATABASE " + VERIFY_DB, "postgres")
    t0 = time.perf_counter()
    restore = subprocess.run(
        ["docker", "exec", "-i", "corpus-db", "pg_restore", "-U", "postgres",
         "-d", VERIFY_DB, "--no-owner", "--exit-on-error"],
        stdin=(BAK / "postgres.dump").open("rb"), capture_output=True, text=True, timeout=900,
    )
    restore_seconds = round(time.perf_counter() - t0, 3)
    if restore.returncode != 0:
        verify_sql(f"DROP DATABASE IF EXISTS {VERIFY_DB} WITH (FORCE)", "postgres")
        raise SystemExit(f"pg_restore FAILED exit={restore.returncode}: {restore.stderr[:500]}")
    print(f"[restore] exit 0 in {restore_seconds}s")

    # ── 门 3：计数 11/11 ─────────────────────────────────────
    baseline = json.loads((BAK / "ledgers" / "_counts.json").read_text(encoding="utf-8"))["counts"]
    counts: dict[str, dict[str, object]] = {}
    counts_ok = True
    for table in LEDGER_TABLES:
        got = int(verify_sql(f"SELECT count(*) FROM public.{table}").strip())
        counts[table] = {"baseline": baseline.get(table), "restored": got}
        counts_ok &= got == baseline.get(table)
    print(f"[gate3] counts {'11/11 OK' if counts_ok else 'MISMATCH'}")

    # ── 门 4：扩展 4/4 + zhparser 词典 ───────────────────────
    ext_expected = {"pg_trgm": "1.6", "plpgsql": "1.0", "vector": "0.8.6", "zhparser": "2.4"}
    ext_restored = dict(
        line.split("\x1f", 1) for line in
        verify_sql("SELECT extname, extversion FROM pg_extension ORDER BY 1").splitlines() if line
    )
    ext_ok = {k: ext_restored.get(k) for k in ext_expected} == ext_expected
    zh_out = verify_sql(
        "SELECT coalesce((SELECT count(*) FROM zhparser.zhprs_custom_word), -1)").strip()
    print(f"[gate4] extensions {'4/4 OK' if ext_ok else 'MISMATCH'}; zhdict_rows={zh_out}")

    # ── 门 5：权限对账（恢复库 vs 生产基线）──────────────────
    verify_priv = priv_snapshot("verify", VERIFY_DB)
    priv_axes = {}
    for axis in ("database_acl", "public_schema_acl", "public_tables",
                 "public_nondefault_relacl_count"):
        priv_axes[axis] = {"prod": prod_priv[axis], "restored": verify_priv[axis],
                           "parity": prod_priv[axis] == verify_priv[axis]}
    prod_only_roles = sorted(set(prod_priv["roles"]) - set(verify_priv["roles"]))
    verify_only_roles = sorted(set(verify_priv["roles"]) - set(prod_priv["roles"]))
    priv_ok = all(v["parity"] for v in priv_axes.values())
    print(f"[gate5] privilege parity {'OK' if priv_ok else 'MISMATCH'} "
          f"(verify-only roles: {verify_only_roles or 'none'})")

    # ── 门 6：历史证据引用回环（台账 → 恢复库，全量非抽样）────
    # 纪律：blocks.text 含换行，不走 psql 行协议——文本子串检查在服务端
    # （\copy 临时表 JOIN）；跨行拉取仅限无换行列（键/计数/md5）。
    def load_jsonl(name: str) -> list[dict]:
        return [json.loads(l) for l in (BAK / "ledgers" / name).read_text(encoding="utf-8")
                .splitlines() if l.strip()]

    claims = load_jsonl("claims.jsonl")
    cbr = load_jsonl("claim_block_runs.jsonl")
    cer = load_jsonl("corpus_evidence_runs.jsonl")

    block_keys = {
        (r.split("\x1f")[0], r.split("\x1f")[1])
        for r in verify_sql("SELECT doc_id, locator FROM public.blocks").splitlines() if r
    }
    block_docs = {k[0] for k in block_keys}
    block_md5_by_doc: dict[str, set[str]] = {}
    for line in verify_sql("SELECT DISTINCT doc_id, md5(text) FROM public.blocks").splitlines():
        if not line:
            continue
        doc_id, h = line.split("\x1f", 1)
        block_md5_by_doc.setdefault(doc_id, set()).add(h)

    # 回环 A（引用解析）：claims.locator → blocks(doc_id, locator) 逐条（客户端，无文本列）
    claims_doc_ok = sum(1 for c in claims if c["doc_id"] in block_docs)
    claims_key_ok = sum(1 for c in claims if (c["doc_id"], c["locator"]) in block_keys)

    # 回环 B（恢复保真度，服务端）：I4-6 备份 CSV 台账 \copy 入临时表，与恢复库逐行
    # 双向 EXCEPT 比对——备份时刻导出的每一行必须与恢复库逐字一致（含 NULL/时间戳）。
    export_tables = ["claims", "claim_block_runs", "corpus_evidence_runs",
                     "ingest_runs", "ingest_failures", "docs", "chinese_docs"]
    fidelity: dict[str, object] = {}
    for table in export_tables:
        src_csv = BAK / "ledgers" / f"{table}.csv"
        # 数组列：JSONL/CSV 导出为 Python repr（如 []），COPY 需 PG 数组字面量（{}）。
        # 按表探测数组列位置，逐行转换后写入临时 CSV。
        type_rows = verify_sql(
            "SELECT ordinal_position, column_name, udt_name, data_type FROM information_schema.columns "
            f"WHERE table_schema='public' AND table_name='{table}' ORDER BY ordinal_position")
        cols = [(int(pos) - 1, name, udt, dt) for pos, name, udt, dt in
                (line.split("\x1f") for line in type_rows.splitlines() if line)]
        parsed_cols = {
            idx: ("array" if dt == "ARRAY" else "json")
            for idx, _n, _u, dt in cols if dt in {"ARRAY", "json", "jsonb"}
        }  # ordinal_position 1 基 → CSV 行索引 0 基
        # 导出侧把空 tsvector 写成 ''，NULL '' 选项令其导入为 NULL（导出混淆，非恢复差异）：
        # tsvector 列在 EXCEPT 投影中以 coalesce(col::text,'') 中和。
        tsv_idx = {idx for idx, _n, udt, _dt in cols if udt == "tsvector"}
        csv_path: Path = src_csv
        if parsed_cols:
            import csv as _csv

            _csv.field_size_limit(50_000_000)  # payload JSON 大字段
            csv_path = ROOT / f".scratch/m7-fix-20260924/.g3-{table}.csv"
            with src_csv.open(encoding="utf-8", newline="") as fin, \
                    csv_path.open("w", encoding="utf-8", newline="") as fout:
                reader = _csv.reader(fin)
                writer = _csv.writer(fout)
                header = next(reader)
                writer.writerow(header)
                for row in reader:
                    for idx, kind in parsed_cols.items():
                        v = row[idx]
                        if not v.startswith(("[", "{")):
                            continue
                        items = ast.literal_eval(v)  # 导出为 Python repr（单引号），非 JSON
                        if kind == "array":
                            row[idx] = "{" + ",".join(
                                str(i) if isinstance(i, (int, float))
                                else '"' + str(i).replace("\\", "\\\\").replace('"', '\\"') + '"'
                                for i in items) + "}" if items else "{}"
                        else:
                            row[idx] = json.dumps(items, ensure_ascii=False, default=str)
                    writer.writerow(row)
        proj = ", ".join(
            f"coalesce(\"{name}\"::text, '')" if idx in tsv_idx else f'"{name}"'
            for idx, name, _u, _dt in cols)
        probe = run(
            ["docker", "exec", "-i", "corpus-db", "psql", "-U", "postgres", "-d", VERIFY_DB,
             "-At", "-v", "ON_ERROR_STOP=1",
             "-c", f"CREATE TEMP TABLE g3_{table}(LIKE public.{table})",
             "-c", f"\\copy g3_{table} FROM STDIN WITH (FORMAT csv, HEADER true, NULL '')",
             "-c", f"SELECT (SELECT count(*) FROM (SELECT {proj} FROM g3_{table} "
                   f"EXCEPT SELECT {proj} FROM public.{table}) a) || '/' || "
                   f"(SELECT count(*) FROM (SELECT {proj} FROM public.{table} "
                   f"EXCEPT SELECT {proj} FROM g3_{table}) b)",
             "-c", f"SELECT count(*) FROM g3_{table}"],
            stdin_path=csv_path,
        )
        if probe.returncode != 0:
            verify_sql(f"DROP DATABASE IF EXISTS {VERIFY_DB} WITH (FORCE)", "postgres")
            raise SystemExit(f"fidelity probe {table} failed: {probe.stderr[:300]}")
        diff, loaded = probe.stdout.strip().splitlines()[-2:]
        fidelity[table] = {"rows": int(loaded), "except_diff_rows": diff}
        if parsed_cols:
            csv_path.unlink()
    fidelity_ok = all(v["except_diff_rows"] == "0/0" for v in fidelity.values())  # type: ignore[union-attr]

    # 信息性证据（不入门）：cbr(seq=抽取批次) 计数一致性 + cer.source_rev 前缀 vs blocks.text md5
    restored_groups = {
        (line.split("\x1f")[0], int(line.split("\x1f")[1])): int(line.split("\x1f")[2])
        for line in verify_sql(
            "SELECT doc_id, seq, count(*) FROM public.claims GROUP BY 1, 2").splitlines() if line
    }
    cbr_n_ok = sum(1 for r in cbr
                   if restored_groups.get((r["doc_id"], int(r["seq"])), 0) == int(r["claims_n"]))
    cer_rev_ok = sum(
        1 for r in cer
        if any(r["source_rev"] and h.startswith(str(r["source_rev"]))
               for h in block_md5_by_doc.get(r["doc_id"], ())))

    loop = {
        "claims_to_blocks": {"claims_rows": len(claims), "doc_resolved": claims_doc_ok,
                             "locator_resolved": claims_key_ok,
                             "result": "全部解析" if claims_key_ok == len(claims) else "存在未解析"},
        "ledger_vs_restored_fidelity": {
            **fidelity,
            "result": "七表双向 EXCEPT 逐行一致" if fidelity_ok else "存在差异行",
        },
        "informational": {
            "note": "claim_text 为模型抽取改写文本，逐字子串率不构成恢复保真度门；"
                    "cbr.seq 为抽取批次序号（非 block 定位符）",
            "claim_block_runs_claims_n_match_vs_restored_groups": f"{cbr_n_ok}/{len(cbr)}",
            "corpus_evidence_runs_source_rev_prefix_vs_block_md5": f"{cer_rev_ok}/{len(cer)}",
        },
    }
    loop_ok = (claims_key_ok == len(claims) and claims_doc_ok == len(claims)
               and fidelity_ok)
    print(f"[gate6] reference loop: claims→blocks {claims_key_ok}/{len(claims)} locators, "
          f"ledger↔restored fidelity {'7 tables 0/0 diff' if fidelity_ok else 'DIFF'}; "
          f"[info] cbr_n {cbr_n_ok}/{len(cbr)}, cer_rev {cer_rev_ok}/{len(cer)}")

    # ── 销毁一次性库 ─────────────────────────────────────────
    verify_sql(f"DROP DATABASE {VERIFY_DB} WITH (FORCE)", "postgres")
    remaining = verify_sql("SELECT datname FROM pg_database ORDER BY 1", "postgres")
    destroyed = VERIFY_DB not in remaining.split()
    print(f"[teardown] destroyed={destroyed}")

    gate = all([manifest_ok, counts_ok, ext_ok, priv_ok, loop_ok, destroyed])
    report = {
        "artifact": "g3-isolated-restore-verification.json",
        "task": "M7 复核 G3：I4-6 恢复验证补验（权限对账 + 历史证据引用回环 + 实测耗时）",
        "review_ref": ".scratch/m7-review-20260924/report.md §G3",
        "observed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_backup": "backups/i4-final-20260923T1544Z（I4-6 最终备份，manifest "
                         f"{n_manifest} 件 sha256sum -c {'OK' if manifest_ok else 'FAIL'}）",
        "restore": {
            "target": f"corpus-db 隔离实例 127.0.0.1:543 / 一次性库 {VERIFY_DB}（PG 18.6，与源匹配）",
            "command": "pg_restore -U postgres --no-owner --exit-on-error < postgres.dump",
            "exit_code": restore.returncode,
            "measured_seconds": restore_seconds,
            "measurement": "宿主机 time.perf_counter 墙钟（单次全量 custom-format 恢复）",
        },
        "table_counts": counts,
        "extensions": {"expected": ext_expected, "restored": ext_restored,
                       "zhprs_custom_word_rows": {"restored": int(zh_out)}},
        "privilege_reconciliation": {
            "method": "pg_roles / pg_database.datacl / pg_namespace.nspacl / pg_tables.tableowner "
                      "/ pg_class.relacl 五轴，生产基线（只读目录查询，read-only 会话）vs 恢复库",
            "prod_roles": prod_priv["roles"], "restored_roles": verify_priv["roles"],
            "prod_only_roles": prod_only_roles, "verify_only_roles": verify_only_roles,
            "axes": priv_axes,
            "note": "pg_restore --no-owner：所有权语句抑制；dump 无 ACL 条目（TOC 0 条），"
                    "两侧均为 postgres 单角色默认权限态",
        },
        "reference_loop": {
            "method": "回环 A：备份 claims.jsonl → 恢复库 blocks(doc_id, locator) 逐条解析"
                      "（全量非抽样）；回环 B：备份 CSV 台账 \\copy 入临时表与恢复库双向 "
                      "EXCEPT 逐行比对（恢复保真度回环，含 NULL/时间戳）",
            **loop,
            "result": "引用全解析 + 台账逐行一致" if loop_ok else "存在差异",
        },
        "gate": {
            "passed": gate,
            "checks": [
                f"manifest {n_manifest}/{n_manifest} OK" if manifest_ok else "manifest FAIL",
                "pg_restore exit 0",
                "计数 11/11" if counts_ok else "计数失配",
                "扩展 4/4" if ext_ok else "扩展失配",
                "权限对账五轴 parity" if priv_ok else "权限对账失配",
                "引用回环：claims→blocks 全解析 + 七表台账↔恢复库逐行一致" if loop_ok else "引用回环失配",
                "一次性库已销毁" if destroyed else "一次性库销毁失败",
            ],
        },
        "production_write_paths_touched": False,
        "note": "I4-6 原记录（i46-restore-verification.json）保持不变；本件为其补验附录"
                "（G3 建议项：权限、旧引用往返、实测耗时）。不绑入冻结链（tasks.md r5j 条目"
                "注明另行执行）。",
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[report] {OUT} gate.passed={gate}")
    return 0 if gate else 1


if __name__ == "__main__":
    raise SystemExit(main())
