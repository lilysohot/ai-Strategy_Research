"""I4-7 迁移前只读探针：postgres 库 zhcfg 与沙箱库 zhcfg 的映射等价性核对。

背景（sandbox_schema.sql L14 注释）：zhcfg 必须含 'm' 数词映射，否则 "47.3亿" 类
数字 token 被丢弃（initdb 实测教训）。新链 DDL 的生成列 ``to_tsvector('zhcfg', …)``
在 CREATE TABLE 时把 'zhcfg' 解析为具体 regconfig OID——postgres 库现有 zhcfg
（旧链 initdb 产物，TOC 实证存在）若映射不全，新链 FTS 基线（index-4-zhcfg-2）
将与沙箱不一致。本探针只读核对，不写库、不改对象；任何异常即中止。
"""

from __future__ import annotations

import json

import psycopg
from psycopg.rows import dict_row

PG_DSN = "postgresql://postgres:postgres@127.0.0.1:5432/postgres"
SBX_DSN = "postgresql://postgres:postgres@127.0.0.1:543/i2_sandbox_corpus"

ZHCFG_MAPPING = "a,b,c,e,f,h,i,j,k,l,m,n,o,p,q,r,s,t,u,v,w,x,y,z"

MAPPING_SQL = """
SELECT m.maptokentype, d.dictname
FROM pg_ts_config c
JOIN pg_ts_config_map m ON m.mapcfg = c.oid
JOIN pg_ts_dict d ON d.oid = m.mapdict
WHERE c.oid = %s::regconfig
ORDER BY m.maptokentype
"""


def probe(dsn: str, label: str) -> dict[str, object]:
    out: dict[str, object] = {"label": label}
    with psycopg.connect(dsn, autocommit=True) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SET TRANSACTION READ ONLY")
            cur.execute("SELECT current_database() AS db, inet_server_port()::text AS port")
            row = cur.fetchone()
            assert row is not None
            out["database"] = row["db"]
            out["port"] = row["port"]

            # 解析 unqualified 'zhcfg'（与 DDL 生成列同一路径）与 public.zhcfg
            cur.execute("SHOW search_path")
            out["search_path"] = cur.fetchone()["search_path"]
            cur.execute("SELECT 'zhcfg'::regconfig::oid AS oid")
            resolved = cur.fetchone()["oid"]
            out["zhcfg_resolved_oid"] = resolved
            cur.execute("SELECT 'public.zhcfg'::regconfig::oid AS oid")
            out["public_zhcfg_oid"] = cur.fetchone()["oid"]

            cur.execute(MAPPING_SQL, (f"{resolved}",))
            mapping = {r["maptokentype"]: r["dictname"] for r in cur.fetchall()}
            out["mapping"] = mapping
            out["mapping_token_count"] = len(mapping)
            expected = set(ZHCFG_MAPPING.split(","))
            out["missing_tokens"] = sorted(expected - set(mapping))
            out["extra_tokens"] = sorted(set(mapping) - expected)
            out["all_simple"] = all(v == "simple" for v in mapping.values())

            cur.execute("SELECT count(*) AS n FROM zhparser.zhprs_custom_word")
            out["custom_words"] = cur.fetchone()["n"]

            # zhparser 解析器配置（等价性相关 GUC，会话默认值即库级默认）
            cur.execute(
                "SELECT name, setting FROM pg_settings WHERE name LIKE 'zhparser.%' ORDER BY name"
            )
            out["zhparser_gucs"] = {r["name"]: r["setting"] for r in cur.fetchall()}
    return out


def main() -> int:
    pg = probe(PG_DSN, "postgres(5432)")
    sbx = probe(SBX_DSN, "i2_sandbox_corpus(543)")
    report = {"postgres": pg, "sandbox": sbx}
    # 等价性判定：映射集合逐 token 相同、词典全部 simple、自定义词典一致（均为 0 行预期）
    equiv = (
        pg["mapping"] == sbx["mapping"]
        and pg["custom_words"] == sbx["custom_words"]
        and pg["zhparser_gucs"] == sbx["zhparser_gucs"]
    )
    report["equivalent"] = equiv
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not equiv:
        print("MISMATCH: zhcfg 基线与沙箱不一致——迁移脚本必须按此设计条件创建/修正路径")
        return 1
    print("OK: zhcfg 基线两库一致")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
