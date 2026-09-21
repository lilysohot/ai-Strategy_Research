"""只读归因：dump company-007 免责声明节（ord 713-727）原文，供 F3 制裁决设计。

不写库；仅打印 unit 原文 + 当前存储状态。read-only + 0 model calls。
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path("/home/administrator/FrontierAgent").resolve()
AUDITS = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits"
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

SB = "i2_sandbox_corpus"
SRC = "6f14cc145b798b3716bad47829c05d89d8a5e5955179f11d196ed9b9b8538f11"


def load_module(name: str, path: Path) -> object:
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    import psycopg

    from plugins.corpus.preparation.contract import UnitStatus
    from plugins.corpus.preparation.repository_pg import PgStore

    release = load_module(
        "i31_region_release", AUDITS / "20260920-i31-region-review/release.py"
    )
    dsn = release.connect()
    with psycopg.connect(dsn, autocommit=True) as conn:
        row = conn.execute(
            "SELECT active_build_id FROM corpus.corpus_publications "
            "WHERE source_id = %s",
            (SRC,),
        ).fetchone()
    if row is None:
        print("source not active")
        return 1
    build_id = row[0]
    print(f"build={build_id[:12]}...  (DISCLAIMER 节 dump)")
    with PgStore(dsn, sandbox_db=SB) as store:
        units = store.get_units(build_id)
    for u in units:
        if u.ordinal is None or u.ordinal < 713 or u.ordinal > 727:
            continue
        st = UnitStatus.KEPT if u.status is UnitStatus.KEPT else u.status.value
        print("-" * 90)
        print(f"ord={u.ordinal} kind={u.kind} status={st} reasons={list(u.reasons or ())} page={u.location.page}")
        print(u.raw_text)
    return 0


if __name__ == "__main__":
    sys.exit(main())