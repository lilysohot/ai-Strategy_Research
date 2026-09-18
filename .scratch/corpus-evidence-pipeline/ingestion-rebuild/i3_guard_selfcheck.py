"""生成 I3 阶段守卫（``guards/i3.json``）的合成反例自检报告：write-once。

守卫有效性不由"日志 0 次"证明，而由合成反例的**拒绝行为**证明（架构 §2.1）。本脚本在
当前进程（普通环境，非守卫 env）调用 ``guard.run_selfcheck``：全部用例在全新子进程执行，
不触真实 PG、不读来源正文、不发起公网连接或 DNS。

用法::

    env -u PYTHONPATH uv run python \
        .scratch/corpus-evidence-pipeline/ingestion-rebuild/i3_guard_selfcheck.py
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[2]
CONFIG = BASE / "guards" / "i3.json"
OUT = BASE / "i3-guard-report.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from plugins.corpus.preparation.guard import run_selfcheck

    if OUT.exists():
        print(f"I3 GUARD REPORT REFUSED: {OUT.name} 已存在（write-once，不覆盖）")
        return 1

    report = run_selfcheck(CONFIG)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    cases = report.get("cases", [])
    failed = [item for item in cases if not item.get("passed")]
    print(
        f"i3 guard selfcheck: passed={report.get('passed')} cases={len(cases)} failed={len(failed)}"
    )
    print(f"config_sha256={report.get('config_sha256')}")
    print(f"report sha256={digest(OUT)}")
    for item in failed:
        print(f"  FAILED: {item.get('case')} :: {item.get('detail')}")
    return 0 if report.get("passed") else 2


if __name__ == "__main__":
    raise SystemExit(main())
