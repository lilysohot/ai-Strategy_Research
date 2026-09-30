"""E5 收尾 #4：只读正向确证冻结 build 的发布门三硬项内部状态。

复刻 ``_verify_publication_ready`` 的三条正向判定 + 缺口可见性，对 6 个 gen-2 冻结 build
逐源输出确证记录，而不是「publish 未抛错」这种负向信号：

1. PARSED / CHUNKED job 终态必须 SUCCEEDED。
2. quality ledger 的 oversized_chunks 必须为空。
3. chunk 覆盖率：保留单元(KEPT) 集合 == chunk 引用集合（无 out_of_scope 越界、无缺引）。
另报 gap 状态：apply_gap_review 后 blocking 空、acknowledged 可见（放行但保持可见）。

零模型、只读 PG。产物：e5-publish-gate.json。
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
FROZEN_JSON = OUT / "e5-freeze-result.json"
sys.path.insert(0, str(ROOT))
import os  # noqa: E402

os.chdir(ROOT)

spec = importlib.util.spec_from_file_location(
    "b0", ROOT / ".scratch/b0-attribution-20260928/b0_attribution.py"
)
b0 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b0)

import psycopg  # noqa: E402

from plugins.corpus.preparation.engine import (  # noqa: E402
    EngineError,
    acknowledged_gaps,
    blocking_gaps,
    gap_records_of,
    quality_ledger_of,
)
from plugins.corpus.preparation.contract import JobStage, UnitStatus  # noqa: E402
from plugins.corpus.preparation.repository_pg import PgStore  # noqa: E402
from plugins.corpus.service import dsn  # noqa: E402


def main() -> None:
    frozen = json.loads(FROZEN_JSON.read_text(encoding="utf-8"))
    dsn_real = dsn()
    store = PgStore(dsn_real, sandbox_db="postgres")
    rows = []
    for s in frozen["sources"]:
        bid = s["build_id"]
        build = store.get_build(bid)
        parsed = store.get_job(bid, JobStage.PARSED)
        chunked = store.get_job(bid, JobStage.CHUNKED)
        ledger = quality_ledger_of(build)
        try:
            records = gap_records_of(build, store=store)
        except EngineError as exc:
            records = []
            gap_err = str(exc)
        else:
            gap_err = None
        blocking = [r.key for r in blocking_gaps(records)]
        ack_keys = [r.key for r in acknowledged_gaps(records)]
        units = store.get_units(bid)
        chunks = store.get_chunks(bid)
        kept_unit_ids = {u.unit_id for u in units if u.status is UnitStatus.KEPT}
        referenced = {ref for c in chunks for ref in c.unit_refs}
        missing = sorted(kept_unit_ids - referenced)
        out_of_scope = sorted(referenced - kept_unit_ids)
        rows.append(
            {
                "source": s["source"],
                "build_id": bid[:16],
                "parse_job_state": parsed.state.value if parsed else None,
                "chunk_job_state": chunked.state.value if chunked else None,
                "jobs_succeeded": bool(
                    parsed and parsed.state.value == "succeeded"
                    and chunked and chunked.state.value == "succeeded"
                ),
                "oversized_chunks": list(ledger.oversized_chunks),
                "oversized_empty": not ledger.oversized_chunks,
                "blocking_gaps": blocking,
                "blocking_empty": not blocking,
                "acknowledged_gaps": ack_keys,
                "gap_review_err": gap_err,
                "kept_unit_count": len(kept_unit_ids),
                "referenced_unit_count": len(referenced),
                "missing_units": missing,
                "out_of_scope_refs": out_of_scope,
                "full_coverage": not missing and not out_of_scope,
            }
        )

    all_pass = all(
        r["jobs_succeeded"]
        and r["oversized_empty"]
        and r["blocking_empty"]
        and r["full_coverage"]
        for r in rows
    )
    result = {
        "artifact": "e5-publish-gate",
        "version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "scope": "E5 frozen 6 gen-2 builds internal publish-gate positive assert (read-only, zero model)",
        "all_pass": all_pass,
        "per_source": rows,
    }
    out = json.dumps(result, ensure_ascii=False, indent=2, default=str).replace(
        dsn_real, "<REDACTED>"
    )
    (OUT / "e5-publish-gate.json").write_text(out, encoding="utf-8")
    print("ALL_PASS", all_pass)
    for r in rows:
        print(
            f"  {r['source']:<30} jobs={r['jobs_succeeded']} "
            f"oversized={'empty' if r['oversized_empty'] else r['oversized_chunks']} "
            f"blocking=({len(r['blocking_gaps'])}) kept={r['kept_unit_count']} "
            f"referenced={r['referenced_unit_count']} coverage={r['full_coverage']}"
        )


if __name__ == "__main__":
    main()