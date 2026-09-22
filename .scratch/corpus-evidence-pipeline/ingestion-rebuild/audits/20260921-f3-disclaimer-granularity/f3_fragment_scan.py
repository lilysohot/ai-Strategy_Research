"""B3 / F3 派生证据：全库扫描「kept 单元 + 续接 NOISE 片段」同构样本数。

背景：`company-007/e1` 的失败机制 = 事实句被版面切成 kept 前半（ord717）
与 NOISE/disclaimer_section 尾片段（ord718「份。」）。本脚本把该模式在
**当前 active corpus（8 builds）**上做全量枚举，用于判定修复面大小：

谓词（纯结构，不依赖金标）：
  相邻 ordinal 对 (i, i+1) 满足
  - `status[i] == kept` 且 `status[i+1] == noise`；
  - `i+1` 的 reasons 含 `disclaimer_section`；
  - `i` 的 raw_text 非空且**不以句末标点结尾**（句被切断）。

只读 PG + 0 model calls；产物 write-once 写入本目录。
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path("/home/administrator/FrontierAgent").resolve()
AUDITS = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits"
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

TERMINAL = ("。", "！", "？", "；", "…", "”", "」", "』", "）", ")", "]", "】")


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def write_once(name: str, value) -> None:
    path = HERE / name
    raw = (json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n").encode()
    if path.exists() and path.read_bytes() != raw:
        raise RuntimeError(f"write-once conflict: {name}")
    path.write_bytes(raw)


def main() -> int:
    import psycopg

    release = load_module("i31_region_release", AUDITS / "20260920-i31-region-review/release.py")
    dsn = release.connect()

    hits: list[dict] = []
    per_build: dict[str, int] = {}
    with psycopg.connect(dsn) as conn:
        sources = dict(conn.execute(
            "SELECT source_id, active_build_id FROM corpus.corpus_publications "
            "WHERE active_build_id IS NOT NULL").fetchall())
        for source_id, build_id in sources.items():
            rows = conn.execute(
                "SELECT ordinal, status, reasons, location->>'page', raw_text "
                "FROM corpus.corpus_units WHERE build_id = %s ORDER BY ordinal",
                (build_id,)).fetchall()
            count = 0
            for i in range(len(rows) - 1):
                o1, s1, _r1, p1, t1 = rows[i]
                o2, s2, r2, p2, t2 = rows[i + 1]
                if int(o2) != int(o1) + 1 or str(s1) != "kept" or str(s2) != "noise":
                    continue
                if "disclaimer_section" not in list(r2 or []):
                    continue
                if not t1 or (t1 or "").rstrip().endswith(TERMINAL):
                    continue
                count += 1
                hits.append({
                    "source_id": source_id, "build_id": build_id,
                    "kept_ordinal": int(o1), "kept_page": p1, "kept_tail": (t1 or "")[-16:],
                    "noise_ordinal": int(o2), "noise_page": p2,
                    "noise_reasons": list(r2 or []), "noise_fragment": (t2 or "")[:16],
                })
            per_build[str(build_id)[:12]] = count

    out = {
        "artifact": "f3-fragment-scan",
        "kind": "全库结构扫描（kept 单元 + disclaimer 续接 NOISE 片段）",
        "corpus": "index-4-zhcfg-2 active (8 builds)",
        "model_calls": 0,
        "predicate": ("ordinal 相邻 + 前 kept 后 noise/disclaimer_section + 前单元不以句末标点结尾"),
        "samples": len(hits),
        "hits": hits,
        "per_build": per_build,
    }
    write_once("f3-fragment-scan.json", out)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
