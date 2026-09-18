"""I0A-2 来源登记分母对账：PG documents 只读清单。

纪律（与 i0a1_inventory.py 相同；I0A-2 前置含"旧库只读"）：
- 零 DDL/DML：仅 documents 单表 SELECT；连接层 default_transaction_read_only=on 兜底。
- 先装守卫再连接：guard.install(i0-inventory) + DSN host/port 必须命中 allowed_targets。
- 连接串经显式环境变量 CORPUS_INVENTORY_DSN 传入，不读 CORPUS_DSN（守卫投毒）。
- 输出 findings JSON 不含任何凭据；仅 doc_id/title/source_path/content_hash/status/时间。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NoReturn

_REPO_ROOT = Path(__file__).resolve().parents[3]
_GUARD_CONFIG = _REPO_ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i0-inventory.json"


def _fail(msg: str) -> NoReturn:
    print(f"I0A-2 文档清单拒绝执行: {msg}", file=sys.stderr)
    raise SystemExit(2)


def main() -> None:
    parser = argparse.ArgumentParser(description="I0A-2 read-only documents list")
    parser.add_argument("--out", required=True, help="findings JSON 输出路径")
    parser.add_argument("--dsn-env", default="CORPUS_INVENTORY_DSN")
    args = parser.parse_args()

    dsn = os.environ.get(args.dsn_env, "").strip()
    if not dsn:
        _fail(f"环境变量 {args.dsn_env} 未设置；连接串必须显式传入，禁止读 CORPUS_DSN/.env")

    from plugins.corpus.preparation import guard

    cfg = guard.install(_GUARD_CONFIG)

    from psycopg.conninfo import conninfo_to_dict

    dsn_parts = conninfo_to_dict(dsn)
    host = dsn_parts.get("host") or "localhost"
    port = int(dsn_parts.get("port") or 5432)
    approved = {(h, p) for h, p in cfg.allowed_targets}
    if (host, port) not in approved:
        _fail(f"目标 {host}:{port} 不在守卫阶段 {cfg.phase} 的 allowed_targets {sorted(approved)} 中")

    import psycopg
    from psycopg.rows import dict_row

    findings: dict[str, Any] = {
        "artifact": "i0a2-doclist-findings.json",
        "task": "I0A-2 documents 只读清单（登记分母对账输入）",
        "observed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "guard": {
            "phase": cfg.phase,
            "config_sha256": hashlib.sha256(_GUARD_CONFIG.read_bytes()).hexdigest(),
        },
        "target": {"host": host, "port": port, "database": dsn_parts.get("dbname"), "note": "凭据不出现在本文件"},
        "errors": [],
        "documents": [],
        "counts_by_status": {},
    }

    conn = psycopg.connect(
        dsn,
        row_factory=dict_row,
        connect_timeout=10,
        autocommit=True,
        options="-c default_transaction_read_only=on",
    )
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT doc_id, title, source_path, content_hash, mime, status, "
                "block_count, ingested_at, published FROM documents ORDER BY doc_id"
            )
            rows = cur.fetchall()
            for r in rows:
                for k in ("ingested_at", "published"):
                    if r.get(k) is not None:
                        r[k] = str(r[k])
            findings["documents"] = rows
            cur.execute("SELECT status, count(*) AS n FROM documents GROUP BY status ORDER BY status")
            findings["counts_by_status"] = {r["status"]: r["n"] for r in cur.fetchall()}
    except Exception as exc:  # noqa: BLE001 - 单查询失败记录后退出
        findings["errors"].append(f"{type(exc).__name__}: {exc}")
    finally:
        conn.close()

    if findings["errors"]:
        print(json.dumps(findings["errors"], ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(findings, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"documents={len(findings['documents'])} by_status={findings['counts_by_status']} -> {out}")


if __name__ == "__main__":
    main()
