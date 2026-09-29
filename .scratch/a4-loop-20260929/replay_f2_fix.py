"""F2 修复的前后对照（确定性、零模型，基于真实运行产物）。

做法：把某次真实 run 的 ``corpus/manifests/*.json`` 原样复制到临时 run 目录，用同一份
账本做两次边界重算：

- **修复前**：候选清单不带 ``owner_role`` → 聚合退回文件名 → 每次提交各成一个拥有者
  → 全量并集（被取代的旧候选仍计入）；
- **修复后**：给候选清单补上该代理实例的 ``owner_role``（模拟修复后的生产者写入）
  → 同拥有者取最新 → 只计最后一次提交。

两次都不传 ``final_text``（跳过报告锚点检查），以**隔离聚合语义本身**，不受
``report_quote``（F3）影响。语料库只读。

用法：``PGOPTIONS='-c default_transaction_read_only=on' uv run python .scratch/a4-loop-20260929/replay_f2_fix.py [run_dir]``
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

# 与运行期一致地加载 .env（CORPUS_DSN / CORPUS_TARGET_DB 等由它提供；缺省会回落沙箱库名）。
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env", override=False)

from plugins.corpus.ledger import (  # noqa: E402
    ConsumptionLedger,
    FragmentRef,
    verify_and_record,
)

DEFAULT_RUN = ROOT / ".apodex/runs/20260929-135254+0800-react-55a2"


def _load_ledger(run_dir: Path) -> ConsumptionLedger:
    """从落盘账本重建内存账本（只取判定所需：fetched 身份 + delivered 状态）。"""
    data = json.loads((run_dir / "corpus" / "ledger.json").read_text(encoding="utf-8"))
    delivered = {
        (str(d["doc_id"]), str(d["locator"]), int(d["start"]), int(d["end"])): str(
            d["status"],
        )
        for d in data.get("delivered") or []
    }
    ledger = ConsumptionLedger()
    for ref in data.get("fetched") or []:
        fragment = FragmentRef.from_dict(ref)
        ledger.fetched.append(fragment)
        ledger.delivered[fragment.identity] = delivered.get(fragment.identity, "unknown")
    return ledger


def _rerun(label: str, run_dir: Path, owner: str | None) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        src = run_dir / "corpus" / "manifests"
        dst = root / "corpus" / "manifests"
        dst.mkdir(parents=True)
        for path in sorted(src.glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            if owner:
                payload["owner_role"] = owner
            dst.joinpath(path.name).write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8",
            )
        verification = verify_and_record(_load_ledger(run_dir), directory=root / "corpus")
    ids = [row["id"] for row in verification["conclusions"]]
    print(f"[{label}] status={verification['status']} counts={verification['counts']}")
    print(f"           ids={ids}")


def main() -> None:
    run_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_RUN
    print("run:", run_dir.relative_to(ROOT) if run_dir.is_relative_to(ROOT) else run_dir)
    _rerun("修复前（全量并集）", run_dir, owner=None)
    _rerun("修复后（同拥有者取最新）", run_dir, owner=f"stateful_react:{run_dir.name}")


if __name__ == "__main__":
    main()
