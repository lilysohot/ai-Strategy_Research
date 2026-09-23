"""I4-5：真注册工具 corpus_search/corpus_fetch 生产往返 + 失败恢复 + 旧写入口停用记录。

运行形态（I3-7 冻结偏差先例，audits/20260923-i37-final-reverify/README.md「两轮实测
复发后确立」节）：corpus 守卫对 ``CORPUS_DSN`` fail-closed 投毒属**冻结设计的正确
行为**（dsn() 默认路径必须不可用），而注册工具 corpus_search/corpus_fetch 经
``get_service()→service.dsn()`` 取连接串，守卫 lane 下结构性不可用 → 本核验按 I3-7
同款以**无守卫子进程**执行并登记偏差。补偿控制：

1. 本脚本只做 PG 往返（零 data/ 读取；search/fetch 为纯读路径，不触
   ``save_evidence_run``）；
2. 结构性零模型断言：运行前后 ``sys.modules`` 不得含 openai / anthropic /
   material_semantics / _r2_runtime；
3. 无双写实测：往返前后旧链七表行数恒 0、blocks/documents 见证计数不变；
4. 固定脚本 + write-once 报告（i45-tool-roundtrip.json）。

往返内容：正向 search（命中→cv2 句柄+chunk 定位+coverage）→ 正向 fetch（逐字原文
+units+source_ranges）→ 失败三例（伪造 cv2 句柄 / 旧句柄 archive_required / 无命中
检索）→ 恢复核验（复取成功）。产出含旧写入口停用记录与实际切换/保留对象清单。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
OUT = HERE / "i45-tool-roundtrip.json"

BLOCKED_MODULES = ("openai", "anthropic", "plugins.corpus.material_semantics", "plugins.corpus._r2_runtime")
PHASE1_TABLES = [
    "claims", "claims_v2", "claim_block_runs", "claim_block_runs_v2",
    "corpus_evidence_runs", "ingest_runs", "ingest_failures",
]
WITNESS = {"blocks": 1101, "documents": 89}
POSITIVE_QUERY = "半导体划片机"  # 光力科技中报点评（I4-4 已发布源）实体词
GARBAGE_QUERY = "qzzx不存在词组wjqtt"


def _abort(msg: str) -> None:
    raise SystemExit(f"拒绝（漂移即停）：{msg}")


def _counts(cur) -> dict[str, int]:
    out: dict[str, int] = {}
    for t in PHASE1_TABLES + list(WITNESS):
        cur.execute(f"SELECT count(*) FROM public.{t}")  # noqa: S608 — 表名来自清单白名单
        out[t] = int(cur.fetchone()[0])
    return out


def _trim(payload: dict, *fields: str, size: int = 240) -> dict:
    out = dict(payload)
    for f in fields:
        v = out.get(f)
        if isinstance(v, str) and len(v) > size:
            out[f] = v[:size] + f"…（len={len(v)})"
    return out


async def _roundtrip(record: dict) -> None:
    from plugins.tools.corpus_fetch import corpus_fetch
    from plugins.tools.corpus_search import corpus_search

    # ── 正向 search ──
    raw = await corpus_search.func(query=POSITIVE_QUERY, limit=10)
    search = json.loads(raw)
    if not search.get("ok") or not search.get("hits"):
        _abort(f"search 未命中：{_trim(search, 'error')}")
    hit = search["hits"][0]
    for key in ("doc_id", "locator", "source_id", "build_id", "chunk_id", "snippet"):
        if not hit.get(key):
            _abort(f"search 首命中缺 {key}：{hit}")
    if not str(hit["doc_id"]).startswith("cv2:") or not str(hit["locator"]).startswith("chunk:"):
        _abort(f"句柄形态非法：{hit['doc_id']}/{hit['locator']}")
    record["search_positive"] = {
        "query": POSITIVE_QUERY,
        "hit_count": len(search["hits"]),
        "query_status": (search.get("coverage") or {}).get("query_status"),
        "first_hit": _trim(hit, "snippet", "title"),
        "coverage": search.get("coverage"),
    }

    # ── 正向 fetch（逐字原文）──
    raw = await corpus_fetch.func(doc_id=hit["doc_id"], locator=hit["locator"])
    fetch = json.loads(raw)
    if not fetch.get("ok"):
        _abort(f"fetch 失败：{_trim(fetch, 'error')}")
    text = str(fetch.get("text") or "")
    spans = fetch.get("spans")
    # source_ranges 可合法为空（contract 默认 ()，仅坐标可验时装配；I4-1 receipts 先例
    # 每条均为 []）——只断言键存在且为列表。text/units 必须非空；spans 必须按序无缝
    # 平铺 text（工具契约「切片可复算出 text」）。
    if (not text or not fetch.get("units")
            or not isinstance(fetch.get("source_ranges"), list)
            or not isinstance(spans, list) or not spans):
        _abort("fetch 载荷不完整（text/units/source_ranges/spans）")
    ordered = sorted(spans, key=lambda s: s["start"])
    if any(ordered[i]["end"] > ordered[i + 1]["start"] for i in range(len(ordered) - 1)):
        _abort(f"spans 重叠：{ordered}")
    # text = 单元按 ordinal 以 "\n" 拼接；span 覆盖各单元内容、不含分隔符
    # （read_pg.fetch_verbatim 同语义）→ "\n".join(切片) 必须复算 text。
    if "\n".join(text[s["start"]:s["end"]] for s in ordered) != text:
        _abort("spans 切片不能复算 text（逐字链破坏）")
    # snippet 是 ts_headline 对清洗视图 search_text 的定位投影（<b> 高亮 + 截断），
    # 与 fetch 的权威 raw_text 不同源，不做子串断言（I4-1 receipts 同口径）；
    # 只验证「截断高亮」结构存在。
    snippet = str(hit["snippet"])
    if not snippet or "<b>" not in snippet:
        _abort(f"snippet 非定位投影（缺高亮标记）：{snippet[:80]}")
    record["fetch_positive"] = {
        "doc_id": fetch["doc_id"],
        "locator": fetch["locator"],
        "active": fetch.get("active"),
        "authority_rev": fetch.get("authority_rev"),
        "units_n": len(fetch["units"]),
        "text_len": len(text),
        "text_head": text[:200],
        "snippet_len": len(snippet),
        "spans_n": len(ordered),
        "spans_reassemble_text": True,
        "snippet_is_highlight_projection": True,
    }

    # ── 失败三例（结构化拒绝，不崩溃）──
    bogus = json.loads(await corpus_fetch.func(doc_id="cv2:" + "0" * 64, locator="chunk:does-not-exist"))
    legacy = json.loads(await corpus_fetch.func(doc_id="doc-legacy-001", locator="b1"))
    miss = json.loads(await corpus_search.func(query=GARBAGE_QUERY, limit=10))
    record["failures"] = {
        "bogus_cv2_handle": {"ok": bogus.get("ok"), "error": str(bogus.get("error"))[:160]},
        "legacy_handle": {"ok": legacy.get("ok"), "error": str(legacy.get("error"))[:160],
                          "archive_required_refusal": "archive_required" in str(legacy.get("error"))},
        "garbage_search": {"ok": miss.get("ok"), "hit_count": len(miss.get("hits") or []),
                           "query_status": (miss.get("coverage") or {}).get("query_status")},
    }
    if bogus.get("ok") or legacy.get("ok") or "archive_required" not in str(legacy.get("error")):
        _abort("失败用例行为不符（伪造句柄须拒、旧句柄须 archive_required）")

    # ── 恢复核验（服务复用同一实例，复取成功）──
    again = json.loads(await corpus_fetch.func(doc_id=hit["doc_id"], locator=hit["locator"]))
    record["recovery"] = {"ok": again.get("ok"), "same_text": again.get("text") == text}
    if not again.get("ok") or again.get("text") != text:
        _abort("失败注入后服务未恢复")


def main() -> int:
    if OUT.exists():
        _abort(f"write-once 报告已存在：{OUT}")
    tz = timezone(timedelta(hours=8))
    dsn = os.environ.get("CORPUS_DSN", "").strip()
    if not dsn or "corpus-guard" in dsn:
        _abort("CORPUS_DSN 未设置或为守卫哨兵（本 lane 为无守卫偏差 lane，须显式生产 DSN）")
    if not dsn.endswith("/postgres"):
        _abort("CORPUS_DSN 目标库必须为 postgres")
    if os.environ.get("CORPUS_TARGET_DB") != "postgres":
        _abort("CORPUS_TARGET_DB=postgres 未设置（r5g 生产放行开关）")
    pre_blocked = [m for m in BLOCKED_MODULES if m in sys.modules]
    if pre_blocked:
        _abort(f"被禁模块先于往返加载：{pre_blocked}")

    import psycopg  # noqa: PLC0415

    record: dict = {
        "artifact": "i45-tool-roundtrip",
        "executed_at": datetime.now(tz).isoformat(timespec="seconds"),
        "target": {"dsn": "postgresql://***@127.0.0.1:5432/postgres", "database": "postgres"},
        "lane": {
            "form": "无守卫子进程（I3-7 冻结偏差先例：守卫对 CORPUS_DSN 的 fail-closed 投毒"
                    "使 dsn() 依赖路径在守卫 lane 下结构性不可用）",
            "deviation_registration": "同 audits/20260923-i37-final-reverify/README.md 偏差登记；"
                                      "随 I4-close 冻结修订一并登记",
            "compensating_controls": [
                "零 data/ 读取（search/fetch 为纯读 DB 路径，不触 save_evidence_run）",
                "结构性零模型断言（sys.modules 白名单反证）",
                "无双写实测（往返前后旧链七表恒 0 + blocks/documents 见证不变）",
                "固定脚本 + write-once 报告",
            ],
        },
    }

    with psycopg.connect(dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("SET TRANSACTION READ ONLY")
        cur.execute("SELECT current_database()")
        if cur.fetchone()[0] != "postgres":
            _abort("current_database ≠ postgres")
        record["pre_row_counts"] = _counts(cur)
        cur.execute("SELECT count(*) FROM corpus.corpus_publications WHERE active_build_id IS NOT NULL")
        record["active_publications"] = int(cur.fetchone()[0])

    asyncio.run(_roundtrip(record))

    post_blocked = [m for m in BLOCKED_MODULES if m in sys.modules]
    if post_blocked:
        _abort(f"往返加载了被禁模块：{post_blocked}")
    record["zero_model_assert"] = {"blocked_modules_absent": True, "checked": list(BLOCKED_MODULES)}

    with psycopg.connect(dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("SET TRANSACTION READ ONLY")
        record["post_row_counts"] = _counts(cur)
    pre, post = record["pre_row_counts"], record["post_row_counts"]
    if any(post[t] != 0 for t in PHASE1_TABLES):
        _abort(f"旧链表出现写入（无双写破坏）：{ {t: post[t] for t in PHASE1_TABLES} }")
    if any(post[t] != WITNESS[t] for t in WITNESS):
        _abort(f"见证表行数变化：{ {t: post[t] for t in WITNESS} }")
    record["no_dual_write"] = {
        "phase1_tables_all_zero": True,
        "witness_unchanged": {t: WITNESS[t] for t in WITNESS},
    }

    # ── 旧写入口停用记录 + 实际切换/保留对象 ──
    record["old_write_entries_deactivated"] = [
        {
            "entry": "claims / claim_block_runs 写入（旧抽取落账）",
            "location": "plugins/corpus/service.py:2169 / :2177",
            "deactivation": "I4-3 停写核验 + i4-cutover-manifest forbidden[1]（public 旧表零写入）"
                            "+ I4-7 reset 阶段 1 清空；本往返前后行数恒 0（无双写实测）",
        },
        {
            "entry": "ingest_runs / ingest_failures 写入（旧 ingest 台账）",
            "location": "plugins/corpus/service.py:2758 / :2806",
            "deactivation": "同上；ingest 链路写路径唯一化至 preparation engine（I2-7 起）",
        },
        {
            "entry": "corpus_evidence_runs 写入（save_evidence_run）",
            "location": "plugins/corpus/service.py:1596（仅 parse_evidence / understand_material "
                        "persist 路径调用；检索/取证纯读不触）",
            "deactivation": "同上；I4-5 往返全程零新行",
        },
        {
            "entry": "documents / blocks 直写",
            "location": "I2-7 已退役（plugins/corpus 无 INSERT INTO documents/blocks 残留）",
            "deactivation": "读侧旧句柄由 corpus_fetch archive_required 显式拒绝（本往返失败用例实测）",
        },
    ]
    record["switched"] = {
        "schema": "corpus（postgres 库内新建，I4-7 migrate 九表）",
        "active_set": "8/8 活动 build（I4-4，build_id 与 I3-7 沙箱基线逐一相同）",
        "consumer_path": "corpus_search → search_pg（活动范围 FTS）+ corpus_fetch → read_pg"
                         "（cv2 句柄逐字取证）；失败恢复核验通过",
        "write_path": "唯一化 preparation engine（I2-7）；I4 窗口内生产写入=I4-4 播种/构建/发布",
    }
    record["retained"] = {
        "public.docs / public.chinese_docs": "C12 归属未定，默认保留（U 单独裁决）",
        "blocks / documents": "阶段 2 TRUNCATE 随 I4-close（新链重建核对后，U 复核）",
        "apodex 库": "零触碰",
        "扩展与 zhcfg / 自定义词典挂点": "保留（C13 FTS 基线，zhparser.zhprs_custom_word 0 行）",
        "旧人工审核导出与备份": "I0B/I4 备份永久保留；reset 后回退只靠已验证备份（不靠旧指针）",
    }

    OUT.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    slim = {k: v for k, v in record.items() if k not in ("pre_row_counts",)}
    print(json.dumps(slim, ensure_ascii=False, indent=2)[:3000])
    print("sha256:", hashlib.sha256(OUT.read_bytes()).hexdigest()[:16], "…")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
