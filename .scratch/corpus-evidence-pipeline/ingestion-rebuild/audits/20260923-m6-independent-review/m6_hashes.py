"""M6 独立复核 · 哈希探针（不复用 gen_i0c_r5b.py / gen_i0c_r5a.py 等生成器）。

独立重算并逐项对账（全部就地计算 sha256，不信任任何中间产物转述）：

1. i0c-r5b 快照绑定：五件 I3-7 重验证据 + tasks.md + 验证器，逐一 vs 快照声明哈希；
2. r5b parent = i0c-r5a（文件字节 vs 声明）；r5a 绑定（final manifest / tasks.md / validator）
   与当前盘面对账（tasks.md 应已演进为 r5b 绑定值；validator 应为 r5b 值；manifest 应仍为 r5a 值）；
3. freeze-manifest.json 中 i0c-r5a / i0c-r5b 条目哈希 vs 实际文件字节；
4. i3-final-freeze-manifest.json：文件自身哈希 vs r5a 绑定；chain_head 三条目
   （i0c-r4z 文件、freeze-manifest、冻结时点验证器）重算；62 项 frozen_assets 逐项重算 → 零漂移；
5. tasks.md 双态：工作区字节（应 = r5b 绑定）与 git HEAD 字节（应 = r5a 绑定）。

用法（仓库根）::

    env -u PYTHONPATH uv run python \
      .scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260923-m6-independent-review/m6_hashes.py

零模型、零数据库、只读。产物：同目录 m6-hashes.json（write-once）。
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1]
ROOT = HERE.parents[4]
TASKS_MD = "docs/plan/corpus-ingestion-rebuild-tasks.md"
VALIDATOR = ".scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/validate_i0c_freeze.py"
FINAL_MANIFEST = ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-final-freeze-manifest.json"


def sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def main() -> int:
    results: dict = {
        "artifact": "m6-independent-review-hashes",
        "generated_at": datetime.now(UTC).astimezone().isoformat(timespec="seconds"),
        "checks": [],
    }
    failures: list[str] = []

    def check(name: str, expected: str, actual: str) -> None:
        ok = expected == actual
        results["checks"].append({"item": name, "expected": expected, "actual": actual,
                                  "match": ok})
        if not ok:
            failures.append(name)

    # 1) i0c-r5b 绑定逐项
    r5b = json.loads((BASE / "freezes/i0c-r5b.json").read_text(encoding="utf-8"))
    for group, items in r5b["binding"].items():
        for rel, expected in items.items():
            check(f"r5b.binding.{group}:{rel}", expected, sha_file(ROOT / rel))

    # 2) r5b parent = i0c-r5a
    parent = r5b["parent_snapshot"]
    check("r5b.parent:" + parent["path"], parent["sha256"], sha_file(ROOT / parent["path"]))

    r5a = json.loads((BASE / "freezes/i0c-r5a.json").read_text(encoding="utf-8"))
    check("r5a.parent:" + r5a["parent_snapshot"]["path"],
          r5a["parent_snapshot"]["sha256"], sha_file(ROOT / r5a["parent_snapshot"]["path"]))

    # 3) r5a 绑定 vs 当前盘面（manifest 应不变；tasks.md/validator 应已被 r5b 取代）
    r5a_manifest = r5a["binding"]["final_freeze_manifest"][FINAL_MANIFEST]
    check("r5a.binding.final_freeze_manifest (current)", r5a_manifest, sha_file(ROOT / FINAL_MANIFEST))
    r5a_tasks = r5a["binding"]["chain_rebind_evidence"][TASKS_MD]
    r5a_validator = r5a["binding"]["freeze_validator"][VALIDATOR]
    results["r5a_binding_superseded_by_r5b"] = {
        "tasks_md": {"r5a": r5a_tasks, "r5b": r5b["binding"]["chain_rebind_evidence"][TASKS_MD]},
        "validator": {"r5a": r5a_validator,
                      "r5b": r5b["binding"]["freeze_validator"][VALIDATOR]},
    }

    # 4) freeze-manifest 条目（i0c-r5a / i0c-r5b）vs 实际字节
    fm = json.loads((BASE / "freezes/freeze-manifest.json").read_text(encoding="utf-8"))
    entries = {e["snapshot_id"]: e for e in fm["snapshots"]}
    for sid in ("i0c-r5a", "i0c-r5b"):
        e = entries.get(sid)
        if e is None:
            failures.append(f"freeze-manifest missing {sid}")
            continue
        check(f"freeze-manifest:{sid}", e["sha256"], sha_file(BASE / "freezes" / e["file"]))
    results["freeze_manifest_snapshots_total"] = len(fm["snapshots"])

    # 5) final manifest：自哈希 + chain_head 三条目 + 62 项 frozen_assets
    fmdoc = json.loads((ROOT / FINAL_MANIFEST).read_text(encoding="utf-8"))
    ch = fmdoc["frozen_version"]["chain_head"]
    check("final-manifest.chain_head:i0c-r4z", ch["sha256"], sha_file(ROOT / ch["file"]))

    # chain_manifest：声明值为 I3-6 冻结时点字节（当时 61 快照）。r5a/r5b 追加入链后
    # 当前面哈希必然不同——此处按追加式索引语义核验：① 从 git 历史找回与声明哈希
    # 一致的冻结时点字节（fail-closed：找不到即失败）；② 当前面 = 冻结面 + 追加
    # r5a/r5b 两条（前缀逐字段相等、非快照字段不变）→ 证明是演进而非篡改。
    cm = fmdoc["frozen_version"]["chain_manifest"]
    frozen_raw: bytes | None = None
    frozen_commit: str | None = None
    commits = subprocess.run(["git", "log", "--format=%h", "--",
                              ".scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/"
                              "freeze-manifest.json"],
                             cwd=ROOT, check=True, capture_output=True,
                             text=True).stdout.split()
    for c in commits:
        raw = subprocess.run(["git", "show", f"{c}:"
                              ".scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/"
                              "freeze-manifest.json"], cwd=ROOT, check=True,
                             capture_output=True).stdout
        if sha_bytes(raw) == cm["sha256"]:
            frozen_raw, frozen_commit = raw, c
            break
    results["chain_manifest_evolution"] = {
        "declared_freeze_time_sha256": cm["sha256"],
        "actual_now": sha_file(ROOT / cm["file"]),
        "freeze_time_commit_found": frozen_commit,
        "appended_snapshots_after_freeze": None,
        "prefix_preserved": None,
        "nonsnapshot_fields_unchanged": None,
    }
    if frozen_raw is None:
        failures.append("final-manifest.chain_manifest:冻结时点字节在 git 历史中不可复得")
    else:
        frozen_doc = json.loads(frozen_raw)
        cur_doc = json.loads((ROOT / cm["file"]).read_text(encoding="utf-8"))
        frozen_snaps = frozen_doc["snapshots"]
        cur_snaps = cur_doc["snapshots"]
        prefix_ok = cur_snaps[:len(frozen_snaps)] == frozen_snaps
        appended = [e["snapshot_id"] for e in cur_snaps[len(frozen_snaps):]]
        nonsnap_ok = ({k: v for k, v in frozen_doc.items() if k != "snapshots"}
                      == {k: v for k, v in cur_doc.items() if k != "snapshots"})
        results["chain_manifest_evolution"].update({
            "freeze_time_snapshot_count": len(frozen_snaps),
            "current_snapshot_count": len(cur_snaps),
            "appended_snapshots_after_freeze": appended,
            "prefix_preserved": prefix_ok,
            "nonsnapshot_fields_unchanged": nonsnap_ok,
        })
        if not prefix_ok:
            failures.append("final-manifest.chain_manifest:冻结时点前缀被改动")
        if appended != ["i0c-r5a", "i0c-r5b"]:
            failures.append(f"final-manifest.chain_manifest:冻结后追加条目异常 {appended}")
        if not nonsnap_ok:
            failures.append("final-manifest.chain_manifest:非快照字段被改动")
    freeze_time_validator = fmdoc["frozen_version"]["freeze_validator"]
    actual_validator_now = sha_file(ROOT / freeze_time_validator["file"])
    results["final_manifest_freeze_time_validator"] = {
        "declared_at_freeze": freeze_time_validator["sha256"],
        "actual_now": actual_validator_now,
        "note": "冻结时点值；r5a/r5b 绑定修订后验证器演进为 1e1b63ec…（r5b 绑定，门 1 核验），"
                "此处不等属预期演进而非资产漂移",
    }

    asset_rows: list[dict] = []
    asset_mismatches: list[str] = []
    asset_total = 0
    for group, items in fmdoc["frozen_assets"].items():
        for rel, expected in items.items():
            asset_total += 1
            actual = sha_file(ROOT / rel)
            ok = expected == actual
            asset_rows.append({"group": group, "path": rel, "match": ok})
            if not ok:
                asset_mismatches.append(f"{group}:{rel}")
    results["frozen_assets"] = {"total": asset_total, "mismatches": asset_mismatches,
                                "all_match": not asset_mismatches}
    for rel in asset_mismatches:
        failures.append("frozen_assets:" + rel)

    # 6) tasks.md 双态
    working = sha_file(ROOT / TASKS_MD)
    head_raw = subprocess.run(["git", "show", f"HEAD:{TASKS_MD}"], cwd=ROOT, check=True,
                              capture_output=True).stdout
    head = sha_bytes(head_raw)
    r5b_tasks = r5b["binding"]["chain_rebind_evidence"][TASKS_MD]
    results["tasks_md_states"] = {
        "working_tree": {"sha256": working, "equals_r5b_binding": working == r5b_tasks},
        "git_head": {"sha256": head, "equals_r5a_binding": head == r5a_tasks},
        "committed": working == head,
        "note": "工作区=改后未 commit（r5b 绑定）；HEAD=fd254523（r5a 绑定）——签认轮若再改 "
                "tasks.md，archive-first 归档必须取当前盘面字节（== r5b 绑定哈希）",
    }
    if working != r5b_tasks:
        failures.append("tasks_md.working != r5b binding")
    if head != r5a_tasks:
        failures.append("tasks_md.git_head != r5a binding")

    results["all_match"] = not failures
    results["failures"] = failures

    out = HERE / "m6-hashes.json"
    payload = (json.dumps(results, ensure_ascii=False, indent=2) + "\n").encode()
    if out.exists():
        if out.read_bytes() != payload:
            print("write-once conflict: m6-hashes.json 已存在且字节不同", file=sys.stderr)
            return 1
        print("[write-once] m6-hashes.json: 逐字节一致 → 保留原产物", file=sys.stderr)
    else:
        out.write_bytes(payload)
    print(json.dumps({"asset_total": asset_total,
                      "asset_mismatches": asset_mismatches,
                      "checks_total": len(results["checks"]),
                      "failures": failures,
                      "all_match": not failures}, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
