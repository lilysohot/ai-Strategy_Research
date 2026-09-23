"""I4-2 / r5g 收尾：生成 i0c-r5g.json 快照 + 追加 freeze-manifest.json 索引条目。

前置（必须已满足）：archive-first 归档、代码变更、门禁、验证器 r5g 节均已就位。
本脚本只做确定性组装：全部绑定哈希取自**当前磁盘最终字节**；父锚取自 i0c-r5f.json
实际字节；supersedes_validator_sha256 取自 r5f 快照的 freeze_validator 绑定值。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path("/home/administrator/FrontierAgent")
RB = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild"
FREEZES = RB / "freezes"
AUD = RB / "audits/20260923-i4-window"

ADAPTER = [
    "plugins/corpus/preparation/pg_target.py",
    "plugins/corpus/preparation/repository_pg.py",
    "plugins/corpus/preparation/read_pg.py",
    "plugins/corpus/preparation/search_pg.py",
    "plugins/corpus/preparation/cross_boundary.py",
    "plugins/corpus/service.py",
    "plugins/corpus/cli.py",
]
STATE = [
    "docs/plan/README.md",
    "docs/plan/corpus-ingestion-rebuild-tasks.md",
]
VALIDATOR_REL = ".scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/validate_i0c_freeze.py"
PREV_REL = ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260923-i4-window/previous-effective-bindings-r5g.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    r5f_path = FREEZES / "i0c-r5f.json"
    r5f = json.loads(r5f_path.read_text(encoding="utf-8"))
    parent_sha = digest(r5f_path)
    declared_parent_sha = (r5f.get("parent_snapshot") or {}).get("sha256")
    supersedes = r5g_supersedes = None
    # r5f 自身绑定的验证器哈希，即 r5g 所取代的验证器版本（权威取法）
    fv = (r5f.get("binding") or {}).get("freeze_validator") or {}
    supersedes = fv.get(VALIDATOR_REL)
    if not supersedes:
        raise SystemExit("r5f 未绑定验证器，无法建立 supersession 账目")
    if declared_parent_sha is None:
        raise SystemExit("r5f parent_snapshot 缺 sha256")
    declared_parent_sha = None  # parent 校验以实际字节为准（validator digest(parent5f)）

    binding = {
        "freeze_validator": {VALIDATOR_REL: digest(ROOT / VALIDATOR_REL)},
        "i4_window_target_adapter": {rel: digest(ROOT / rel) for rel in ADAPTER},
        "migrate_window_state": {rel: digest(ROOT / rel) for rel in STATE},
        "previous_effective_bindings": {PREV_REL: digest(ROOT / PREV_REL)},
    }
    tz = timezone(timedelta(hours=8))
    snapshot = {
        "snapshot_id": "i0c-r5g",
        "revision": "r5g",
        "phase": "i0c",
        "status": "i4_window_target_adapter",
        "business_accepted": True,
        "parent_snapshot": {
            "snapshot_id": "i0c-r5f",
            "path": str(r5f_path.relative_to(ROOT)),
            "sha256": parent_sha,
        },
        "supersedes_validator_sha256": supersedes,
        "binding": binding,
        "correction": (
            "I4 window target adapter: explicit CORPUS_TARGET_DB authorization for the "
            "read/write chain (default i2_sandbox_corpus fail-closed unchanged); docs "
            "rebound after I4-1 section-0 backfill per the r4z precedent (archive-first)."
        ),
        "corrections": {
            "i4_window_target_adapter": (
                "r5g: pg_target.py first-in-chain; repository_pg/read_pg/search_pg "
                "production hard-reject gated on production_instance_authorized(); "
                "service/cli target-db resolution via resolve_target_db(); "
                "docs/plan/README.md + tasks.md rebound (post-r5f section-0 backfill)."
            )
        },
        "created_at": datetime.now(tz).isoformat(timespec="microseconds"),
    }
    snap_path = FREEZES / "i0c-r5g.json"
    snap_path.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    manifest_path = FREEZES / "freeze-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = manifest.get("snapshots", [])
    ids = [e.get("snapshot_id") for e in entries]
    if "i0c-r5g" in ids:
        # 幂等 upsert：仅允许在 i0c-r5g 从未通过绿色验证前重组候选（绑定验证器
        # 当前字节）。若已存在条目则原位更新其 sha256/created_at。
        if ids[-1] != "i0c-r5g":
            raise SystemExit(f"i0c-r5g 不是链尾，拒绝改写：链尾 {ids[-1]}")
        entries[-1].update(
            {
                "created_at": snapshot["created_at"],
                "file": "i0c-r5g.json",
                "parent_snapshot_id": "i0c-r5f",
                "sha256": digest(snap_path),
                "snapshot_id": "i0c-r5g",
            }
        )
    else:
        if ids[-1] != "i0c-r5f":
            raise SystemExit(f"链头非 i0c-r5f：{ids[-1]}")
        entries.append(
            {
                "created_at": snapshot["created_at"],
                "file": "i0c-r5g.json",
                "parent_snapshot_id": "i0c-r5f",
                "sha256": digest(snap_path),
                "snapshot_id": "i0c-r5g",
            }
        )
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print("i0c-r5g.json + manifest 条目已写盘")
    for group, items in binding.items():
        for rel, h in items.items():
            print(f"{group}: {rel} = {h[:16]}…")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
