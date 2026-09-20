"""生成 i3-e2e 阶段守卫（``guards/i3-e2e.json``）的合成反例自检报告：write-once。

与 ``i3_guard_selfcheck.py``（i3.json = I3-2 冻结期：零模型/无网络/无来源读取）同法：
守卫有效性由合成反例的**拒绝行为**证明（架构 §2.1），不由"日志 0 次"证明。
差异在于本配置是 **allowlist 网络 + 只读来源根 + 允许清单**，因此额外要求：

- 允许清单外的来源读取被拒（read_roots 内但未命中 ``allowed_source_paths``）；
- 网络只放行 ``127.0.0.1:543``，任何其他目标（含非允许公网地址）一律拒绝。

全部用例在全新子进程执行，不触真实 PG、不读来源正文、不发起公网连接或 DNS。

用法::

    env -u PYTHONPATH uv run python \
        .scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i3-1-e2e/i3_e2e_guard_selfcheck.py
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1]
ROOT = HERE.parents[4]
CONFIG = BASE / "guards" / "i3-e2e.json"
OUT = HERE / "i3-e2e-guard-report.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from plugins.corpus.preparation.guard import run_selfcheck

    if OUT.exists():
        print(f"I3-E2E GUARD REPORT REFUSED: {OUT.name} 已存在（write-once，不覆盖）")
        return 1

    report = run_selfcheck(CONFIG)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    cases = report.get("cases", [])
    failed = [item for item in cases if not item.get("passed")]
    print(
        f"i3-e2e guard selfcheck: passed={report.get('passed')} cases={len(cases)} failed={len(failed)}"
    )
    print(f"config_sha256={report.get('config_sha256')}")
    print(f"report sha256={digest(OUT)}")
    for item in failed:
        print(f"  FAILED: {item.get('case')} :: {item.get('detail')}")
    return 0 if report.get("passed") else 2


if __name__ == "__main__":
    raise SystemExit(main())
