"""修正 r29 归档声明：只保留真实归档（validator + 两份台账），把 P2/P3/P4 的流程缺陷显式登记。"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path("/home/administrator/FrontierAgent")
BASE = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild"
FREEZES = BASE / "freezes"
HERE = BASE / "audits/20260919-i32-diagnosis"
R29 = FREEZES / "i0c-r29.json"
MANIFEST = FREEZES / "freeze-manifest.json"
VALIDATOR = FREEZES / "validate_i0c_freeze.py"

BASE_REL = ".scratch/corpus-evidence-pipeline/ingestion-rebuild"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ── (a)(b) 修正 r29

r29 = json.loads(R29.read_text(encoding="utf-8"))
bogus = [
    key
    for key in r29["binding"]["i3_2_archive"]
    if any(name in key for name in ("policy-and-lists-confirmation", "baseline-mapping-reconciliation",
                                    "experiment-initial-version"))
]
for key in bogus:
    del r29["binding"]["i3_2_archive"][key]
r29["corrections"]["I3-2_archive_order_defect"] = (
    "流程缺陷登记：P2/P3/P4 的 r28 字节在本轮**归档前已被重生成覆盖**，故未形成归档（原 4 条归档声明已删除，"
    "只保留真实归档：validate_i0c_freeze.py 与两份台账）；r28 记录中这 4 个文件的哈希自此无法用字节核验，"
    "历史审计以 r28 记录值为准。已修正顺序（先归档、后覆盖），并提示："
    "生成器（generate_p2_p3_p4.py）从未入链，产物虽有哈希但生成器不可追溯——后续修订应同时绑定生成器。"
)
r29["notes"].append(
    "归档范围修正：i3_2_archive 只含 validate_i0c_freeze.py 与 docs 两份台账（真实 r28 字节）；"
    "P2/P3/P4 的 r28 字节因顺序错误未归档，已在 corrections 显式登记。"
)
R29.write_text(json.dumps(r29, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

# ── (c) 验证器 r29 归档检查改为真实归档清单

text = VALIDATOR.read_text(encoding="utf-8")
if 'r29 归档组不得声明未真实归档' in text:
    print("validator 已修，跳过")
else:
    old_list_start = text.find('    for original in (f"{inv}/p2/policy-and-lists-confirmation.json",')
    assert old_list_start > 0
    old_list_end = text.find('        check(len(matched) == 1,', old_list_start)
    new_list = '''    for original in (f"{base}/freezes/validate_i0c_freeze.py",
                         "docs/plan/corpus-ingestion-rebuild-tasks.md",
                         "docs/plan/claims-market-closed-loop-plan.md"):
    '''
    text = text[:old_list_start] + new_list + text[old_list_end:]
# 追加一条：P2/P3/P4 不得出现在归档组（防止再出现假声明）
    marker = '    for group, items in binding29.items():'
    assert marker in text
    text = text.replace(
    marker,
    '    for key in binding29.get("i3_2_archive", {}):\n'
    '        check("policy-and-lists-confirmation" not in key and "baseline-mapping-reconciliation" not in key\n'
    '              and "experiment-initial-version" not in key,\n'
    '              f"r29 归档组不得声明未真实归档的 P2/P3/P4 字节：{key}")\n'
        + marker,
        1,
    )
    VALIDATOR.write_text(text, encoding="utf-8")
    import ast

    ast.parse(text)

# ── (d) 复核（写出）

subprocess.run([sys.executable, str(HERE / "step5_review.py")], cwd=str(ROOT), check=False)


# ── (e) 刷新 r29 哈希（含验证器与复核产物）

data = json.loads(R29.read_text(encoding="utf-8"))
changed = []
for group in ("i3_2_assets", "i3_2_step5", "docs", "freeze_validator"):
    for rel in data["binding"][group]:
        current = digest(ROOT / rel)
        if data["binding"][group][rel] != current:
            changed.append(f"{group}:{rel.split('/')[-1]}")
            data["binding"][group][rel] = current
for rel, expected in data["binding"]["i3_2_archive"].items():
    if digest(ROOT / rel) != expected:
        raise SystemExit(f"归档件异常：{rel}")
R29.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
for entry in manifest["snapshots"]:
    if entry.get("snapshot_id") == "i0c-r29":
        entry["sha256"] = digest(R29)
MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# ── (f) 三门

def run(cmd):
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT), check=False)
    return {"exit": proc.returncode, "tail": (proc.stdout or "").strip().splitlines()[-1:]}


chain = run([sys.executable, str(VALIDATOR)])
gate = run([sys.executable, str(FREEZES / "validate_i3_2_completion.py")])
review = run([sys.executable, str(HERE / "step5_review.py"), "--no-write"])
chain_after = run([sys.executable, str(VALIDATOR)])
print(json.dumps({
    "archive_entries": len(data["binding"]["i3_2_archive"]),
    "refreshed": changed,
    "r29_sha256": digest(R29),
    "chain": chain["exit"], "gate": gate["exit"], "review": review["exit"],
    "chain_after_review": chain_after["exit"],
}, ensure_ascii=False, indent=2))
