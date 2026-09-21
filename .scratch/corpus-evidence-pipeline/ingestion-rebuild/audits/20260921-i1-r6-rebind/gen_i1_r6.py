"""i1-r6 生成器：收口 i1 冻结门转红（spec 复核报告 B1）。

背景（机读归因）
----------------
`validate_i1_freeze.py` 红在 `r5.binding[tests]: tests/test_corpus_preparation_admission.py 哈希失配或缺失`：

- i1-r5 绑定该测试 = `ccfd2dd8…`（i1-r5 创建时点字节，与 i0c-r4n 绑定一致）；
- r4s 为修复 M5 复核 MISS②（dev-lane 用例在 i1 守卫环境下读越界来源）把 9 条 dev-lane 用例
  拆到新文件 `tests/test_corpus_dev_lane.py`，`tests/test_corpus_preparation_admission.py` 恢复
  i1 纯净 6 份材料语义 ⇒ 当前字节 = `6adbb274…`；
- i0c-r4s 已重绑该路径（i0c 链绿），但 **i1-r5 未同步** ⇒ i1 链红。

本修订做什么
------------
新增 **i1-r6**（parent=i1-r5，append-only，不改写历史字节）：

1. `tests`: 重绑 `tests/test_corpus_preparation_admission.py` 为当前权威字节；
2. `freeze_validator`: 重绑 `validate_i1_freeze.py`（新增 r6 块 + r5/r3 supersession 豁免）；
3. i1-r5 上述两路径按 supersession 豁免（最新修订优先）；i1-r3 其余条目仍逐一核验。

archive-first
-------------
r6 不修改 `tests/test_corpus_preparation_admission.py` 的任何字节（漂移已在 r4s 发生），
因此"被取代的字节"= i1-r5 声明的 `ccfd2dd8…` 版本，它已不在工作树中，但 r4s 已按纪律归档于
`audits/20260922-r4s-rebind/before-r4s/test_corpus_preparation_admission.py.pre-r4s`
（sha256 实测 = `ccfd2dd8…`，与 i1-r5 绑定逐字节一致）。本脚本把该归档字节复制进
`before-r6/` 并断言与上一绑定一致（`assert_archives_faithful`），不留假归档。

用法
----
    uv run python .../audits/20260921-i1-r6-rebind/gen_i1_r6.py --no-write   # 干跑
    uv run python .../audits/20260921-i1-r6-rebind/gen_i1_r6.py            # 落盘

可重入：已存在的 r6 块 / manifest 条目 / 归档文件均不重复写入，`created_at` 固定复用 ⇒ 复跑产物确定。
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import shutil
import sys
from pathlib import Path

ROOT = Path("/home/administrator/FrontierAgent").resolve()
INGEST = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild"
FREEZES = INGEST / "freezes"
AUDIT = INGEST / "audits/20260921-i1-r6-rebind"
R4S_ARCHIVE = (
    INGEST / "audits/20260922-r4s-rebind/before-r4s/test_corpus_preparation_admission.py.pre-r4s"
)

ADM_TEST = "tests/test_corpus_preparation_admission.py"
VALIDATOR_REL = ".scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/validate_i1_freeze.py"
VALIDATOR = ROOT / VALIDATOR_REL
I1_R5 = FREEZES / "i1-r5.json"
I1_R6 = FREEZES / "i1-r6.json"
MANIFEST = FREEZES / "freeze-manifest.json"

CREATED_AT = "2026-09-22T04:10:00+08:00"

R6_BLOCK = '''
# i1-r6（B1 收口）：r4s 为修 M5 MISS② 把 dev-lane 用例拆出本测试文件，i1-r5 对该路径的
# 绑定（ccfd2dd8…）随之失效；r6 重绑当前字节并同步重绑本校验器。i1-r5 / i1-r3 的对应
# 旧绑定按 supersession 豁免（最新修订优先，不改写历史字节）。
superseded_i6: set[str] = set()
r6_binding: dict = {}
if "i1-r6" in by_id:
    r6 = load_json(BASE / by_id["i1-r6"].get("file", ""))
    p6 = r6.get("parent_snapshot", {})
    check(p6.get("snapshot_id") == "i1-r5",
          f"r6.parent 应为 i1-r5，实际 {p6.get('snapshot_id')!r}")
    if p6.get("snapshot_id") == "i1-r5":
        pfile6 = ROOT / p6.get("path", "")
        if not pfile6.is_file() or digest(pfile6) != p6.get("sha256"):
            errors.append("r6.parent(i1-r5) 文件字节与声明哈希不一致")
    r6_binding = r6.get("binding", {})
    for items in r6_binding.values():
        superseded_i6.update(items)
    if not r6_binding:
        errors.append("r6.binding 为空")

'''

OLD_R3_SKIP = """            if rel in superseded_i5:
                continue  # 已由 i1-r5 重绑，i1-r3 旧绑定豁免"""
NEW_R3_SKIP = """            if rel in superseded_i5 or rel in superseded_i6:
                continue  # 已由 i1-r5/i1-r6 重绑，i1-r3 旧绑定豁免"""

OLD_R5_VERIFY = """    for group in sorted(r5_binding):
        for rel in sorted(r5_binding[group]):
            f = ROOT / rel
            if not f.is_file() or digest(f) != r5_binding[group][rel]:
                errors.append(f"r5.binding[{group}]: {rel} 哈希失配或缺失")"""
NEW_R5_VERIFY = """    for group in sorted(r5_binding):
        for rel in sorted(r5_binding[group]):
            if rel in superseded_i6:
                continue  # 已由 i1-r6 重绑
            f = ROOT / rel
            if not f.is_file() or digest(f) != r5_binding[group][rel]:
                errors.append(f"r5.binding[{group}]: {rel} 哈希失配或缺失")
    # i1-r6 重绑的路径逐一核到 i1-r6 声明的当前哈希
    for group in sorted(r6_binding):
        for rel in sorted(r6_binding[group]):
            f = ROOT / rel
            if not f.is_file() or digest(f) != r6_binding[group][rel]:
                errors.append(f"r6.binding[{group}]: {rel} 哈希失配或缺失")"""

OLD_PRINT = 'print("freeze chain verified: index ids unique, r3 bindings ok, lineage r3->r1->i0a5(M1) ok")'
NEW_PRINT = (
    'print("freeze chain verified: index ids unique, r3 bindings ok, '
    'lineage r3->r1->i0a5(M1) ok"\n'
    '      + ("; i1-r5 supersession -> i1-r6 (admission test + i1 validator rebind)"\n'
    '         if "i1-r6" in by_id else ""))'
)

ANCHOR = '\nif "i1-r3" in by_id:'


def digest(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_freeze_utils():
    spec = importlib.util.spec_from_file_location("freeze_utils_i1r6", FREEZES / "freeze_utils.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def archive_before_r6() -> list[dict]:
    """archive-first：归档本修订取代的字节。

    - `tests/test_corpus_preparation_admission.py`：r6 不改木文件；被取代的 i1-r5 声明字节
      （ccfd2dd8…）由 r4s 归档留存（工作树已无该字节）；
    - `validate_i1_freeze.py`：本修订**直接改写**该文件 ⇒ 改前归档 pre-r6 字节。
    """

    before = AUDIT / "before-r6"
    records: list[dict] = []

    adm_target = before / ADM_TEST
    if not adm_target.is_file() and not DRY:
        adm_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(R4S_ARCHIVE, adm_target)
    adm_live = adm_target if adm_target.is_file() else R4S_ARCHIVE
    records.append(
        {
            "path": ADM_TEST,
            "archived_as": str(adm_target.relative_to(ROOT)),
            "sha256": digest(adm_live),
            "matches_previous_binding": digest(adm_live) == r5_admission_hash,
            "archive_source": str(R4S_ARCHIVE.relative_to(ROOT)),
            "archive_source_sha256": digest(R4S_ARCHIVE),
            "note": "r6 不改本文件字节；被取代的 i1-r5 声明字节由 r4s 归档留存（工作树已无该字节）",
        }
    )

    val_target = before / "freezes/validate_i1_freeze.py.pre-r6"
    if not val_target.is_file() and not DRY:
        val_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(VALIDATOR, val_target)
    val_live = val_target if val_target.is_file() else VALIDATOR
    records.append(
        {
            "path": VALIDATOR_REL,
            "archived_as": str(val_target.relative_to(ROOT)),
            "sha256": digest(val_live),
            "matches_previous_binding": digest(val_live) == r5_validator_hash,
            "note": "本修订改写 i1 校验器（新增 r6 块）；此前归档等价于 freeze_utils.archive_first",
        }
    )

    if not DRY:
        before.mkdir(parents=True, exist_ok=True)
        (before / "archive-provenance.json").write_text(
            json.dumps({"records": records}, ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8",
        )
    return records


def patch_validator() -> str:
    text = VALIDATOR.read_text(encoding="utf-8")
    for old, new, marker in (
        (ANCHOR, R6_BLOCK + ANCHOR, "superseded_i6: set[str] = set()"),
        (OLD_R3_SKIP, NEW_R3_SKIP, "or rel in superseded_i6"),
        (OLD_R5_VERIFY, NEW_R5_VERIFY, 'errors.append(f"r6.binding'),
        (OLD_PRINT, NEW_PRINT, "i1-r5 supersession -> i1-r6"),
    ):
        if marker in text:
            continue  # 幂等：该补丁已存在
        if text.count(old) != 1:
            raise SystemExit(f"补丁锚点不唯一/缺失（{text.count(old)} 次）：{old[:60]!r}")
        text = text.replace(old, new, 1)
    return text


def build_r6(validator_hash: str) -> dict:
    return {
        "snapshot_id": "i1-r6",
        "revision": "i1-r6",
        "scope": "B1 收口：i1-r5 对 admission 测试的绑定随 r4s dev-lane 拆文件失效，重绑测试 + i1 校验器",
        "status": "frozen",
        "parent_snapshot": {
            "snapshot_id": "i1-r5",
            "path": str(I1_R5.relative_to(ROOT)),
            "sha256": digest(I1_R5),
        },
        "binding": {
            "tests": {ADM_TEST: digest(ROOT / ADM_TEST)},
            "freeze_validator": {VALIDATOR_REL: validator_hash},
        },
        "corrections": {
            "r4s_dev_lane_split_invalidated_i1_r5": (
                "r4s 修复 M5 复核 MISS②：dev-lane 9 条用例拆出 tests/test_corpus_dev_lane.py 后，"
                "tests/test_corpus_preparation_admission.py 恢复 i1 纯净（6 份材料）语义，字节由 "
                f"ccfd2dd8… 变为 6adbb274…；i0c-r4s 已重绑，i1-r5 未同步 ⇒ i1 链转红。"
                "本修订按 supersession 重绑该测试 + i1 校验器（不改写 i1-r5 字节、不改任何运行语义）。"
            )
        },
        "notes": [
            "r6 为 i1 链的记账修订（parent=i1-r5）：仅重绑被 r4s 合法演进的绑定锚点，恢复 "
            "validate_i1_freeze.py exit 0；不改任何实现/测试字节。",
            f"重绑锚点：{ADM_TEST} = {digest(ROOT / ADM_TEST)[:12]}…（i0c-r4s 同值），"
            f"{VALIDATOR_REL} = {validator_hash[:12]}…（新增 r6 块 + r5/r3 supersession 豁免）。",
            "archive-first：被取代的 i1-r5 声明字节（ccfd2dd8…）取自 r4s 归档，已在 before-r6/ 留痕并断言一致。",
            "纪律：不 commit、不 publish、不重摄入；不改 scorer/金标；不触 I2/检索层运行字节。",
        ],
        "created_at": CREATED_AT,
    }


def update_manifest(r6_hash: str) -> dict:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    ids = [entry.get("snapshot_id") for entry in manifest["snapshots"]]
    if "i1-r6" in ids:
        return manifest
    manifest["snapshots"].append(
        {
            "snapshot_id": "i1-r6",
            "file": "i1-r6.json",
            "sha256": r6_hash,
            "parent_snapshot_id": "i1-r5",
            "created_at": CREATED_AT,
        }
    )
    return manifest


def main() -> int:
    global DRY, r5_admission_hash, r5_validator_hash

    parser = argparse.ArgumentParser()
    parser.add_argument("--no-write", action="store_true", help="干跑：只做校验与计划打印")
    args = parser.parse_args()
    DRY = args.no_write

    freeze_utils = load_freeze_utils()
    r5 = json.loads(I1_R5.read_text(encoding="utf-8"))
    r5_binding = r5.get("binding", {})
    r5_admission_hash = r5_binding["tests"][ADM_TEST]
    r5_validator_hash = r5_binding["freeze_validator"][VALIDATOR_REL]
    live_admission = digest(ROOT / ADM_TEST)

    print(f"i1-r5 绑定 admission 测试 : {r5_admission_hash[:12]}…")
    print(f"工作树当前 admission 测试 : {live_admission[:12]}…")
    print(f"i1-r5 绑定 i1 校验器      : {r5_validator_hash[:12]}…")
    if live_admission == r5_admission_hash:
        raise SystemExit("工作树与 i1-r5 绑定一致 —— 本修订无对象（漂移不存在？）")
    if r5_validator_hash != digest(VALIDATOR):
        print(f"提示：i1 校验器当前字节 = {digest(VALIDATOR)[:12]}… ≠ i1-r5 绑定"
              "（本修订已落盘或另有改动，archive-first 断言仍按 i1-r5 绑定核对）")

    # 1) archive-first（先在内存里记录，写盘前断言忠实性）
    records = archive_before_r6()
    freeze_utils.assert_archives_faithful(records)
    for record in records:
        print(f"archive-first OK: {record['archived_as']} sha={record['sha256'][:12]}… "
              f"(matches_previous_binding={record['matches_previous_binding']})")

    # 2) 补丁 i1 校验器（先定字节 → 再定绑定哈希）
    patched = patch_validator()
    current_text = VALIDATOR.read_text(encoding="utf-8")
    if patched == current_text:
        print("i1 校验器补丁：已是最新（幂等命中）")
    elif DRY:
        print(f"[dry] i1 校验器将改写：{len(current_text)} -> {len(patched)} 字节")
    else:
        VALIDATOR.write_text(patched, encoding="utf-8")
        print(f"i1 校验器已补丁：{len(patched)} 字节")
    validator_hash = digest(VALIDATOR) if not DRY else hashlib.sha256(patched.encode()).hexdigest()
    print(f"i1 校验器（r6 绑定值）    : {validator_hash[:12]}…")

    # 3) 写 i1-r6.json
    r6 = build_r6(validator_hash)
    r6_text = json.dumps(r6, ensure_ascii=False, indent=1) + "\n"
    r6_hash = hashlib.sha256(r6_text.encode()).hexdigest()
    if I1_R6.is_file():
        on_disk = I1_R6.read_text(encoding="utf-8")
        if on_disk == r6_text:
            print("i1-r6.json：已存在且逐字节一致（幂等）")
        else:
            print(f"注意：i1-r6.json 已存在但内容不同（重建）。旧 sha={digest(I1_R6)[:12]}…")
    elif DRY:
        print(f"[dry] 将写 i1-r6.json ({len(r6_text)} 字节, sha={r6_hash[:12]}…)")
    else:
        I1_R6.write_text(r6_text, encoding="utf-8")
        print(f"i1-r6.json 已写: sha={digest(I1_R6)[:12]}…")

    # 4) 追加 manifest 条目
    manifest = update_manifest(r6_hash)
    manifest_text = json.dumps(manifest, ensure_ascii=False, indent=1) + "\n"
    if DRY:
        print("[dry] 将追加 freeze-manifest.json 条目 i1-r6")
    else:
        MANIFEST.write_text(manifest_text, encoding="utf-8")
        print("freeze-manifest.json 已追加 i1-r6 条目")

    if not DRY:
        print("\n下一步：跑三门")
        print(f"  uv run python {VALIDATOR_REL}")
        print("  uv run python .scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/validate_i0c_freeze.py")
        print("  uv run python .scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/validate_i3_2_completion.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
