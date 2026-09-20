"""r30 后续修正：完成门补 SIGNOFF_JSON 常量 + 验证器白名单同步 + 刷新 r30 绑定。"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path("/home/administrator/FrontierAgent")
BASE = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild"
HERE = BASE / "audits/20260919-i32-diagnosis"
FREEZES = BASE / "freezes"
GATE = FREEZES / "validate_i3_2_completion.py"
VALIDATOR = FREEZES / "validate_i0c_freeze.py"
R30 = FREEZES / "i0c-r30.json"
MANIFEST = FREEZES / "freeze-manifest.json"
BASE_REL = ".scratch/corpus-evidence-pipeline/ingestion-rebuild"
AUDIT_REL = f"{BASE_REL}/audits/20260919-i32-diagnosis"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# 1. 完成门补常量
text = GATE.read_text(encoding="utf-8")
if "SIGNOFF_JSON = " not in text:
    anchor = 'COMPLETION_GATE = FREEZES / "validate_i3_2_completion.py"'
    if anchor not in text:
        anchor = 'SCORER = ROOT / "plugins/corpus/scoring.py"'
    text = text.replace(
        anchor,
        anchor + '\nSIGNOFF_JSON = HERE / "signoff-record-i3-2.json"',
        1,
    )
    GATE.write_text(text, encoding="utf-8")
    import ast

    ast.parse(text)
    print("完成门补 SIGNOFF_JSON")
else:
    print("完成门已有常量")

# 2. 验证器 r30 白名单加 fix 脚本
vtext = VALIDATOR.read_text(encoding="utf-8")
marker = '            f"{audit}/fix_paths_r29.py",'
if 'fix_r30_gate_constant.py' not in vtext:
    assert marker in vtext
    vtext = vtext.replace(
        marker, marker + '\n            f"{audit}/fix_r30_gate_constant.py",', 1
    )
    VALIDATOR.write_text(vtext, encoding="utf-8")
    import ast

    ast.parse(vtext)
    print("验证器 r30 白名单已加 fix_r30_gate_constant.py")

# 3. 刷新 r30 绑定
data = json.loads(R30.read_text(encoding="utf-8"))
data["binding"]["freeze_validator"] = {
    f"{BASE_REL}/freezes/validate_i0c_freeze.py": digest(VALIDATOR),
    f"{BASE_REL}/freezes/validate_i3_2_completion.py": digest(GATE),
}
data["binding"]["i3_2_generators"][f"{AUDIT_REL}/fix_r30_gate_constant.py"] = digest(
    HERE / "fix_r30_gate_constant.py"
)
data["corrections"]["I3-2_completion_gate_signoff_check"] = (
    "完成门新增『阶段签认（具名 + 入链）』判据；补 SIGNOFF_JSON 常量后判据生效"
)
R30.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
for entry in manifest["snapshots"]:
    if entry.get("snapshot_id") == "i0c-r30":
        entry["sha256"] = digest(R30)
MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run(cmd):
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT), check=False)
    return proc.returncode


chain = run([sys.executable, str(VALIDATOR)])
gate = run([sys.executable, str(GATE)])
review = run([sys.executable, str(HERE / "step5_review.py"), "--no-write"])
chain_after = run([sys.executable, str(VALIDATOR)])
print(json.dumps({"chain": chain, "gate": gate, "review": review, "chain_after": chain_after,
                  "r30_sha256": digest(R30)}, ensure_ascii=False, indent=2))
