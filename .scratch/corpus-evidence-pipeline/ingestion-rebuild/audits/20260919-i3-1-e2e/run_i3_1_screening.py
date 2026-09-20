"""I3-1 筛料（只读预检）：对 43 份券商研报跑 `corpus plan`，按缺口分级挑"无 blocking 缺口"的样本。

规范依据（不是本轮新决定）：
- 架构 §385-386：`image_only_page` / `image_region_unreadable` → needs_ocr → **blocking**；
- 架构 §91：首版**不允许自动 OCR**；§57：自动 OCR 不纳入当前基线，须"有证据的变更"才引入；
- 任务行 I3-1：`blocking` 缺口按 `check`/`status` 的 `gaps` 机读处置（**补 OCR / 换料 / 转 review_required**），
  并"先用 `corpus-plan` 预检筛料"。

本阶段：不装守卫（只读筛料，不写 PG、不发布）、不改任何冻结件、不写正式路径。
"""

from __future__ import annotations

import contextlib
import io
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
BASE = HERE.parents[1]
DEV_MANIFEST = BASE / "dev-manifest.json"
MANIFEST = HERE / "screening-manifest.json"
OUT = HERE / "i3-1-screening.json"
OUT_MD = HERE / "i3-1-screening.md"

# 领域提示仅作"登记元数据"（契约明文：domain_hint 不是批准凭证），按研报标题关键词推断
# 判定次序很重要：先 company（个股点评最具体）→ macro（宏观/策略/海外）→ industry（行业/主题）
DOMAIN_KEYWORDS = {
    "company": ("公司研究", "业绩点评", "中报点评", "季报点评", "个股", "买入", "增持"),
    "macro": ("宏观", "非农", "策略", "海外", "加息", "通胀", "高频数据", "议息", "数据面面观", "周观点", "轮动"),
    "industry": ("行业", "周报", "产业链", "化工", "新材料", "电子", "半导体", "机械", "医药",
                 "有色", "金属", "地产", "环保", "通信", "传媒", "电力设备", "新能源", "机器人",
                 "农业", "光模块", "ai", "hbm", "ipo", "新股", "电信", "汽车"),
}
HOLDOUT_MARKERS = ("2594e01d", "65b4b040", "d571f138", "2b0eb6ce", "5520fab6")


def domain_hint(name: str) -> str | None:
    lowered = name.lower()
    for domain in ("company", "macro", "industry"):
        if any(key.lower() in lowered for key in DOMAIN_KEYWORDS[domain]):
            return domain
    return None


def main() -> int:
    dm = json.loads(DEV_MANIFEST.read_text(encoding="utf-8"))
    brokers = [
        s for s in dm["sources"]
        if (s.get("machine_suggestion") or {}).get("material_type") == "broker_research"
    ]
    rows = []
    for source in brokers:
        path = str(source["path"])
        name = Path(path).name
        rows.append(
            {
                "path": path,
                "name": name,
                "format": Path(path).suffix.lower().lstrip("."),
                "domain_hint": domain_hint(name),
                "size": source.get("size_bytes"),
                "on_disk": (ROOT / path).is_file(),
            }
        )
    rows = [r for r in rows if r["on_disk"] and r["format"] == "pdf"]
    MANIFEST.write_text(
        json.dumps(
            {
                "sources": [
                    {"path": r["path"], **({"domain_hint": r["domain_hint"]} if r["domain_hint"] else {})}
                    for r in rows
                ]
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    sys.path.insert(0, str(ROOT))
    from plugins.corpus import cli  # noqa: PLC0415

    env = dict(
        line.split("=", 1)
        for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines()
        if "=" in line and not line.strip().startswith("#")
    )
    dsn = (
        f"postgresql://{env['CORPUS_DSN'].split('://', 1)[1].rsplit('@', 1)[0]}"
        "@127.0.0.1:543/i2_sandbox_corpus"
    )

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = cli.main(["plan", "--manifest", str(MANIFEST), "--dsn", dsn])
    text = buf.getvalue()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = json.loads(text[text.find("{"):])

    if not isinstance(payload, dict) or payload.get("ok") is not True:
        error = json.dumps(payload, ensure_ascii=False)[:600]
        (OUT).write_text(
            json.dumps(
                {"artifact": "i3-1-screening", "ok": False, "plan_exit_code": code, "error": error,
                 "note": "plan 未成功 → 不得把空 entries 当作『全干净』（旧版假阴性已修）"},
                ensure_ascii=False, indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print(json.dumps({"plan_failed": True, "exit": code, "error": error}, ensure_ascii=False, indent=2))
        return 1
    entries = {
        str(e.get("path") or e.get("original_name")): e
        for e in (payload.get("entries") or [])
    }
    missing = [r["path"] for r in rows if r["path"] not in entries]
    if missing:
        raise SystemExit(f"断言失败：plan 未覆盖 {len(missing)} 个来源，源例 {missing[:2]}")
    graded = []
    for row in rows:
        entry = entries.get(row["path"]) or entries.get(row["name"]) or {}
        # 缺口在 entry["precheck"]（不在顶层）——旧版解析错层级导致"全干净"假象
        precheck = entry.get("precheck") or {}
        gaps = precheck.get("gaps") or []
        summary = precheck.get("gap_summary") or {}
        blocking = [
            g for g in gaps
            if str(g.get("disposition") or g.get("lifecycle") or "") not in ("acknowledged", "noise")
        ]
        if summary and int(summary.get("blocking", -1)) != len(blocking):
            raise SystemExit(
                f"断言失败：{row['name'][:40]} precheck.blocking={summary.get('blocking')} "
                f"但逐条判定得 {len(blocking)}"
            )
        graded.append(
            {
                **row,
                "decision": entry.get("decision"),
                "publishable_prejudgement": precheck.get("publishable_prejudgement"),
                "holdout": any(marker in row["path"] for marker in HOLDOUT_MARKERS),
                "gap_summary": summary,
                "gap_codes": dict(Counter(str(g.get("code")) for g in blocking)),
                "blocking": len(blocking),
                "acknowledged": sum(
                    1 for g in gaps
                    if str(g.get("disposition") or g.get("lifecycle") or "") in ("acknowledged", "noise")
                ),
                "gaps_all": gaps[:40],
            }
        )
    clean = [g for g in graded if g["blocking"] == 0 and not g["holdout"]]
    holdout_clean = [g for g in graded if g["blocking"] == 0 and g["holdout"]]
    by_domain: dict[str, list] = defaultdict(list)
    for row in clean:
        if row["domain_hint"]:
            by_domain[row["domain_hint"]].append(row)

    record = {
        "artifact": "i3-1-screening",
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "method": "corpus plan（只读可发布性预检；同一缺口分级实现；未装守卫、无 PG 写入）",
        "screened": len(graded),
        "clean": len(clean),
        "clean_excluding_holdouts": len(clean),
        "clean_but_holdout": [g["name"] for g in holdout_clean],
        "blocked": len(graded) - len(clean),
        "blocking_code_inventory": dict(
            Counter(
                code
                for row in graded
                for code, count in row["gap_codes"].items()
                for _ in range(count)
            )
        ),
        "clean_by_domain": {
            domain: [
                {"name": r["name"], "blocking": r["blocking"], "acknowledged": r["acknowledged"]}
                for r in sorted(rows, key=lambda x: x["size"] or 0)
            ]
            for domain, rows in by_domain.items()
        },
        "blocked_detail": [
            {"name": r["name"], "domain_hint": r["domain_hint"], "gap_codes": r["gap_codes"]}
            for r in graded if r["blocking"] > 0
        ],
        "all_rows": [
            {k: v for k, v in r.items() if k != "gaps_all"} for r in graded
        ],
        "plan_exit_code": code,
    }
    OUT.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# I3-1 筛料（只读预检：从 43 份研报挑无 blocking 缺口的样本）",
        "",
        f"- 生成：{record['generated_at']}；方法：{record['method']}",
        f"- 筛了 {record['screened']} 份：**干净 {record['clean']} / 有 blocking 缺口 {record['blocked']}**",
        f"- 阻断代码分布：{json.dumps(record['blocking_code_inventory'], ensure_ascii=False)}",
        "",
        "## 各类可用的干净样本（按体量升序，题名已截断）",
        "",
    ]
    for domain, items in record["clean_by_domain"].items():
        lines.append(f"### {domain}（{len(items)} 份）")
        lines.append("")
        lines.append("| 来源 | blocking | acknowledged |")
        lines.append("|---|---|---|")
        for item in items:
            lines.append(f"| {item['name'][:60]} | {item['blocking']} | {item['acknowledged']} |")
        lines.append("")
    lines += ["## 有阻断的样本", "", "| 来源 | 领域提示 | 阻断代码 |", "|---|---|---|"]
    for row in record["blocked_detail"][:25]:
        lines.append(f"| {row['name'][:52]} | {row['domain_hint']} | {json.dumps(row['gap_codes'], ensure_ascii=False)} |")
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({
        "screened": record["screened"], "clean": record["clean"], "blocked": record["blocked"],
        "clean_by_domain": {d: len(v) for d, v in record["clean_by_domain"].items()},
        "blocking_codes": record["blocking_code_inventory"],
        "plan_exit": code,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
