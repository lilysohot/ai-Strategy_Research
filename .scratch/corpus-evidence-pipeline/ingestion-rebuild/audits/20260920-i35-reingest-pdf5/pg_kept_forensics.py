"""I3-5 PG kept 文本取证的 I3-3 准数（reader-pdf-5，从 PG 读取 kept 单元）。

对照基线（I3-3，audits/20260920-i33-calibration evidence-diagnosis.json）：
- exact_quote_not_in_kept_page_text = 34 条（6 份 dev PDF）
- 本轮取 **PG kept 文本**：从 PgStore 读新 build 的 kept 单元，按页码拼接成
  kept_page_text，逐条核对金标引号是否在 kept 页内（normalize 空白后）。

区别 verify_native_order.py：
- 那边用 read_document 重解析 reader；这边直接读 PG 已发布 kept 单元，
  反映真实可检索/可取的 kept 文本（与发布一致，不引入 reader 口径偏差）。
只读 PG，不写任何状态。输出本目录 i35-pg-kept-forensics.json / .md。
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
I33 = HERE.parent / "20260920-i33-calibration"
BASE = HERE.parents[1]  # ingestion-rebuild
ROOT = HERE
while not (ROOT / "plugins").is_dir():
    ROOT = ROOT.parent
sys.path.insert(0, str(ROOT))
SANDBOX = "i2_sandbox_corpus"

WS = re.compile(r"\s+")


def norm(s: object) -> str:
    return WS.sub("", s) if isinstance(s, str) else ""


def main() -> int:
    os.environ["CORPUS_DEV_LANE"] = "1"
    from plugins.corpus.preparation import guard  # noqa: PLC0415
    guard.install(str(ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i3-e2e.json"))  # noqa: E501
    from plugins.corpus.preparation.contract import UnitStatus  # noqa: PLC0415
    from plugins.corpus.preparation.repository_pg import PgStore  # noqa: PLC0415

    env = {l.split("=", 1)[0]: l.split("=", 1)[1] for l in open(ROOT / ".env", encoding="utf-8") if "=" in l and not l.strip().startswith("#")}  # noqa: E501
    cred = env["CORPUS_DSN"].split("://", 1)[1].rsplit("@", 1)[0]
    dsn = f"postgresql://{cred}@127.0.0.1:543/{SANDBOX}"

    diag = json.loads((I33 / "evidence-diagnosis.json").read_text())
    gold = {json.loads(line)["query_id"]: json.loads(line)
            for line in (BASE / "i3-2/query-gold-scoring-v1.jsonl").read_text().splitlines()}
    rows = [t for t in diag["targets"] if t["cause"] == "exact_quote_not_in_kept_page_text"]

    with PgStore(dsn, sandbox_db=SANDBOX) as store:
        # source_id -> active build kept page text 缓存
        cache: dict[str, dict[int, str]] = {}
        for src in sorted({r["source_id"] for r in rows}):
            pub = store.get_publication(src)
            active = pub.active_build_id if pub else None
            build = store.get_build(active) if active else None
            if build is None:
                cache[src] = {}
                continue
            pages: dict[int, list[str]] = {}
            for u in store.get_units(build.build_id):
                if u.status is UnitStatus.KEPT:
                    pages.setdefault(u.location.page, []).append(u.raw_text)
            cache[src] = {pg: "\n".join(lines) for pg, lines in pages.items()}

    hit = miss = 0
    missed: list[str] = []
    target_rows = []
    for r in rows:
        pg = int(r["required_locator"][0].split(":")[1])
        q = next(et["quote"] for et in gold[r["query_id"]]["evidence_targets"]
                 if et["target_id"] == r["target_id"])
        in_page = norm(q) in norm(cache.get(r["source_id"], {}).get(pg, ""))
        # 全文回退检（若跨页误判）
        page_texts = cache.get(r["source_id"], {})
        in_kept_anywhere = any(norm(q) in norm(t) for t in page_texts.values())
        # 伪 miss 诊断:引号字符在 kept 全文本中的保留率（逐字，跨单元/换行/夹杂后）
        kept_full = norm("\n".join(t for t in page_texts.values()))
        qnorm = norm(q)
        char_kept = sum(1 for ch in qnorm if ch in kept_full) / max(len(qnorm), 1) if qnorm else 0.0
        if in_page:
            hit += 1
        else:
            miss += 1
            missed.append(f"{r['query_id']} {r['target_id']} p{pg}")
        target_rows.append({
            "query_id": r["query_id"], "target_id": r["target_id"],
            "source_id": r["source_id"][:12], "page": pg,
            "quote_in_kept_page": in_page, "quote_in_kept_anywhere": in_kept_anywhere,
            "quote_char_preserved_in_kept": round(char_kept, 3),
            "quote": q,
        })

    # 分来源统计
    # 每条 miss 归类:逐字引号完整缺失 vs 单元边界/换行/夹杂导致的伪 miss
    # 判据:全部引号字符在 kept 全文本中保留率 == 1.0 且声明页无完整连续匹配 → 伪 miss
    pseudo_missed = []
    for t in target_rows:
        if not t["quote_in_kept_page"]:
            if t["quote_char_preserved_in_kept"] >= 1.0:
                t["classification"] = "pseudo_mean_quote_split_across_unit_boundary_or_interspersed_text"
                pseudo_missed.append(f"{t['query_id']} {t['target_id']} p{t['page']}")
            else:
                t["classification"] = "quote_characters_missing_in_kept"

    by_src: dict[str, dict[str, int]] = {}
    for t in target_rows:
        s = by_src.setdefault(t["source_id"], {"kept_page_hit": 0, "page_hits": 0, "targets": 0})
        s["targets"] += 1
        if t["quote_in_kept_page"]:
            s["kept_page_hit"] += 1
        if t["quote_in_kept_anywhere"]:
            s["page_hits"] += 1

    by_source_list = [{"source_id": k, **v} for k, v in by_src.items()]
    total_targets = len(rows)
    out = {
        "artifact": "i3-5-pg-kept-forensics",
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "method": "PG kept 单元按页码拼接 matched against gold quote（norm 空白后逐字）",
        "baseline": "I3-3 exact_quote_not_in_kept_page_text = 34（reader-pdf-2 下全部 miss）",
        "targets": total_targets,
        "hit": hit, "miss": miss,
        "hit_in_kept_anywhere": sum(1 for t in target_rows if t["quote_in_kept_anywhere"]),
        "recovered": total_targets - miss,
        "missed": missed,
        "pseudo_missed": pseudo_missed,
        "target_rows": target_rows,
        "by_source": by_source_list,
        "reader5_company001_p1_contiguous": norm(
            "我们维持26-28年EPS预测值67.74/70.77/73.84元"
        ) in norm(cache.get("6f14cc145b798b3716bad47829c05d89d8a5e5955179f11d196ed9b9b8538f11", {}).get(1, "")),
    }
    json_path = HERE / "i35-pg-kept-forensics.json"
    json_path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# I3-5 PG kept 文本取证（reader-pdf-5，对准数复跑）",
        "",
        f"- 生成：{out['generated_at']}；口径：从 PG 读新 build 的 kept 单元按页码拼接",
        f"- 基线：I3-3 的 `exact_quote_not_in_kept_page_text` = 34（reader-pdf-2，全部 miss）",
        "",
        f"## 命中 {hit}/{total_targets}（kept 页内），另 {out['hit_in_kept_anywhere']}"
        f" 命中于全文任意 kept 页",
        "",
        "| 来源 | 目标数 | kept页命中 | 全文任页命中 |",
        "|---|---|---|---|",
    ]
    for s in by_source_list:
        lines.append(f"| {s['source_id']} | {s['targets']} | {s['kept_page_hit']} | {s['page_hits']} |")
    lines += ["", "## 未命中（kept 页内逐字）", ""]
    for m in missed:
        lines.append(f"- {m}")
    lines += [
        "",
        f"- 茅台 company-001 p1 连续引号：{out['reader5_company001_p1_contiguous']}",
        "- 说明：kept 页内未命中未必代表引号缺失，可能跨页/换行/Tab 差异；见 target_rows 明细。",
    ]
    (HERE / "i35-pg-kept-forensics.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({k: out[k] for k in
                      ("targets", "hit", "miss", "hit_in_kept_anywhere", "recovered")},
                     ensure_ascii=False, indent=2))
    print("-- by_source --")
    print(json.dumps(by_source_list, ensure_ascii=False, indent=2))
    print("-- missed --")
    for m in missed:
        print(" ", m)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())