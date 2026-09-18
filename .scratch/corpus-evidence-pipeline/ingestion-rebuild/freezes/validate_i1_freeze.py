"""Verify the append-only I1 freeze index, r3 bindings and lineage to M1.

显式检查 + 非零退出；不使用 assert（``python -O`` 优化模式下断言会被剥离，
本验证器不得依赖 assert）。核验内容：

1. freeze-manifest.json：条目 snapshot_id 唯一、每条目哈希与文件实际字节一致；
2. 索引存在 i1-r3 条目；
3. r3.parent_snapshot = i1-r1 且父文件字节与声明哈希一致；
4. r3.binding 全部绑定（当前实现/测试/夹具/配置/现行探针）逐一核验；
5. 血缘到 M1：r1.parent_snapshot = i0a5 且 M1 快照文件字节与声明哈希一致。

注：r1 内部 binding 指向 I1-9 时点的历史文件状态，不与当前工作区比对。
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[3]

errors: list[str] = []


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(cond: bool, message: str) -> None:
    if not cond:
        errors.append(message)


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        errors.append(f"{path.name}: 不可读或非法 JSON（{exc}）")
        return {}


manifest = load_json(BASE / "freeze-manifest.json")
snapshots = manifest.get("snapshots", [])
ids = [entry.get("snapshot_id") for entry in snapshots]
check(len(ids) == len(set(ids)), f"索引 snapshot_id 重复: {ids}")
check(bool(ids), "索引无条目")

by_id: dict[str, dict] = {}
for entry in snapshots:
    sid = entry.get("snapshot_id")
    by_id[sid] = entry
    rel = entry.get("file", "")
    file = BASE / rel
    if not file.is_file():
        errors.append(f"{sid}: 索引文件缺失 {rel}")
        continue
    actual = digest(file)
    check(actual == entry.get("sha256"), f"{sid}: 索引哈希失配 {rel}")
check("i1-r3" in by_id, "索引缺少 i1-r3 条目")
check("i1-r1" in by_id, "索引缺少 i1-r1 条目")

if "i1-r3" in by_id:
    r3 = load_json(BASE / by_id["i1-r3"].get("file", ""))
    parent = r3.get("parent_snapshot", {})
    check(parent.get("snapshot_id") == "i1-r1",
          f"r3.parent 应为 i1-r1，实际 {parent.get('snapshot_id')!r}")
    if parent.get("snapshot_id") == "i1-r1":
        pfile = ROOT / parent.get("path", "")
        if not pfile.is_file() or digest(pfile) != parent.get("sha256"):
            errors.append("r3.parent(i1-r1) 文件字节与声明哈希不一致")
    binding = r3.get("binding", {})
    total = 0
    for group in sorted(binding):
        for rel in sorted(binding[group]):
            total += 1
            f = ROOT / rel
            if not f.is_file() or digest(f) != binding[group][rel]:
                errors.append(f"r3.binding[{group}]: {rel} 哈希失配或缺失")
    if total == 0:
        errors.append("r3.binding 为空")

if "i1-r1" in by_id:
    r1 = load_json(BASE / by_id["i1-r1"].get("file", ""))
    gp = r1.get("parent_snapshot", {})
    check(gp.get("snapshot_id") == "i0a5",
          f"r1.parent 应为 i0a5(M1)，实际 {gp.get('snapshot_id')!r}")
    if gp.get("snapshot_id") == "i0a5":
        gfile = ROOT / gp.get("path", "")
        if not gfile.is_file() or digest(gfile) != gp.get("sha256"):
            errors.append("r1.parent(i0a5/M1) 文件字节与声明哈希不一致")

if errors:
    for message in errors:
        print(f"FREEZE CHECK FAILED: {message}")
    print(f"freeze chain verification FAILED: {len(errors)} error(s)")
    sys.exit(1)
print("freeze chain verified: index ids unique, r3 bindings ok, lineage r3->r1->i0a5(M1) ok")
