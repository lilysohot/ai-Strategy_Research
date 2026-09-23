"""I4-1 原文预演归档（受守卫；排除 5 份留出件，排除显式记录）。

- 守卫：i4-inventory（data/corpus 只读；5 份留出禁读——归档同样被拒，fail-closed）。
- 留出件仅以 stat 元数据入账（已在 i41-inventory-findings.json 记录 size/mtime），
  完整原文归档（含留出）属 I4-6 最终备份，须窗口守卫单独授权。
- 产物：originals/i4r-data-corpus-NOT-FINAL.tar.gz + originals-files.sha256。
"""
from __future__ import annotations

import hashlib
import json
import os
import tarfile
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[5]
_GUARD_CONFIG = _REPO_ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i4-inventory.json"
_BACKUP_BASE = _REPO_ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/backups"
_DIR = sorted(_BACKUP_BASE.glob("i4-rehearsal-*-NOT-FINAL"))[-1]
_ORIG = _DIR / "originals"
_ORIG.mkdir(parents=True, exist_ok=True)

from plugins.corpus.preparation import guard  # noqa: E402

cfg = guard.install(_GUARD_CONFIG)

forbidden = set()
for x in cfg.forbidden_roots:
    xp = Path(x)
    forbidden.add(str(xp if xp.is_absolute() else (_REPO_ROOT / xp).resolve()))

excluded: list[str] = []
included: list[str] = []
tar_path = _ORIG / "i4r-data-corpus-NOT-FINAL.tar.gz"
corpus_root = _REPO_ROOT / "data/corpus"
with tarfile.open(tar_path, "w:gz") as tf:
    for f in sorted(corpus_root.rglob("*")):
        if not f.is_file():
            continue
        rel = str(f.relative_to(_REPO_ROOT))
        if str(f) in forbidden:
            excluded.append(rel)
            continue
        tf.add(f, arcname=rel, recursive=False)
        included.append(rel)

hashes = []
for p in sorted(_DIR.rglob("*")):
    if p.is_file() and p.name != "artifact-manifest.sha256" and not p.name.endswith(".sha256"):
        h = hashlib.sha256(p.read_bytes()).hexdigest()
        hashes.append(f"{h}  {p.relative_to(_DIR)}")
(_ORIG / "included-and-excluded.json").write_text(json.dumps({
    "included_count": len(included),
    "excluded_holdouts": excluded,
    "excluded_note": "留出件字节未读未归档（守卫禁读）；完整原文归档属 I4-6 窗口守卫授权范围",
    "tar_sha256": hashlib.sha256(tar_path.read_bytes()).hexdigest(),
    "tar_size": tar_path.stat().st_size,
    "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

manifest = _DIR / "artifact-manifest.sha256"
manifest.write_text("\n".join(hashes) + "\n", encoding="utf-8")
print(json.dumps({
    "dir": str(_DIR.relative_to(_REPO_ROOT)),
    "included": len(included),
    "excluded_holdouts": len(excluded),
    "tar_sha256": hashlib.sha256(tar_path.read_bytes()).hexdigest()[:16],
    "manifest_entries": len(hashes),
}, ensure_ascii=False))
