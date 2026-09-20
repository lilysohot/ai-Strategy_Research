"""按磁盘现况刷新 r29 绑定哈希（只刷新 r29 自己绑定的路径），并更新索引条目。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path("/home/administrator/FrontierAgent")
FREEZES = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes"
R29 = FREEZES / "i0c-r29.json"
MANIFEST = FREEZES / "freeze-manifest.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


data = json.loads(R29.read_text(encoding="utf-8"))
refreshed = {}
for group in ("i3_2_assets", "i3_2_step5", "docs", "freeze_validator"):
    for rel in data["binding"][group]:
        path = ROOT / rel
        current = digest(path) if path.is_file() else None
        old = data["binding"][group][rel]
        changed = current != old
        data["binding"][group][rel] = current
        refreshed[f"{group}:{rel.split('/')[-1]}"] = changed
for rel, expected in data["binding"]["i3_2_archive"].items():
    path = ROOT / rel
    if not path.is_file() or digest(path) != expected:
        raise SystemExit(f"归档件异常：{rel}")
R29.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
for entry in manifest["snapshots"]:
    if entry.get("snapshot_id") == "i0c-r29":
        entry["sha256"] = digest(R29)
        entry["created_at"] = data["created_at"]
MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"refreshed_changed": {k: v for k, v in refreshed.items() if v},
                  "r29_sha256": digest(R29)}, ensure_ascii=False, indent=2))
