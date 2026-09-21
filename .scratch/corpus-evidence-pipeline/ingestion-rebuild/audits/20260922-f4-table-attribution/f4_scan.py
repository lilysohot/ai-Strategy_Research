"""F4 归因佐证：全库扫描 `header_repeated_geometric`/`footer_repeated_geometric` NOISE 单元的 kind 分布。

目标：验证"页 1 封面标题（heading 类型）被连带扫进页眉 NOISE、而 p2-7 页眉是 paragraph 类型"
是否为 company-008 独有，还是存在"heading/title 类型也被当页眉剔"的普遍现象 —— 这决定 F4
判定路径（若 heading 类型的带内重复单元普遍存在且其中部分是真实标题 ⇒ 表身份/标题归属缺失，
应豁免 heading 类型标题；若仅 company-008 一处 ⇒ 更接近个案边界）。

只读 PG，全活动 build，0 model calls。产物 write-once（f4-scan.json）。
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path("/home/administrator/FrontierAgent").resolve()
INGEST = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild"
AUDITS = INGEST / "audits"
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

SANDBOX = "i2_sandbox_corpus"
HEADER_CODES = {"header_repeated_geometric", "footer_repeated_geometric"}


def write_once(name: str, value) -> None:
    path = HERE / name
    raw = (json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n").encode()
    if path.exists() and path.read_bytes() != raw:
        raise RuntimeError(f"write-once conflict: {name}")
    path.write_bytes(raw)


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    from plugins.corpus.preparation.repository_pg import PgStore
    import psycopg

    release = load_module("i31_region_release", AUDITS / "20260920-i31-region-review/release.py")
    dsn = release.connect()

    with psycopg.connect(dsn, autocommit=True) as conn:
        sources = dict(conn.execute(
            "SELECT source_id, active_build_id FROM corpus.corpus_publications "
            "WHERE active_build_id IS NOT NULL").fetchall())

    rows = []
    stats = {"builds": len(sources), "total_noise_units": 0,
             "heroes_heading_kind": 0, "heading_kind_units": []}
    with PgStore(dsn, sandbox_db=SANDBOX) as store:
        for src, build_id in sources.items():
            units = store.get_units(build_id)
            counted = []
            for u in units:
                codes = set(u.reasons or ()) & HEADER_CODES
                if not codes:
                    continue
                is_noise = str(u.status.value) == "noise"
                if is_noise:
                    stats["total_noise_units"] += 1
                row = {
                    "src": src[:16], "build": build_id[:12],
                    "ordinal": u.ordinal, "kind": u.kind,
                    "status": str(u.status.value), "reasons": list(u.reasons or ()),
                    "page": u.location.page,
                    "bbox": list(u.location.bbox) if u.location.bbox else None,
                    "len": len(u.raw_text), "raw": u.raw_text[:220],
                }
                rows.append(row)
                if is_noise and u.kind in ("heading", "title"):
                    stats["heroes_heading_kind"] += 1
                    stats["heading_kind_units"].append({
                        "src": src[:16], "build": build_id[:12], "ordinal": u.ordinal,
                        "kind": u.kind, "page": u.location.page, "raw": u.raw_text[:200]})
            counted.append(len(units))

    stats["rows"] = len(rows)
    # 按 kind 聚合被剔的 NOISE 单元
    by_kind: dict[str, int] = {}
    for r in rows:
        if r["status"] == "noise":
            by_kind[r["kind"]] = by_kind.get(r["kind"], 0) + 1
    stats["noise_kind_distribution"] = by_kind

    result = {
        "artifact": "f4-scan", "generated_at": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc).astimezone().isoformat(timespec="seconds"),
        "corpus": "index-4-zhcfg-2 active (8 builds)", "stats": stats,
        "sources": [f"{s[:16]}={b[:12]}" for s, b in sources.items()],
        "all_header_footer_units": rows,
    }
    write_once("f4-scan.json", result)
    print(json.dumps({k: v for k, v in result.items() if k != "all_header_footer_units"},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())