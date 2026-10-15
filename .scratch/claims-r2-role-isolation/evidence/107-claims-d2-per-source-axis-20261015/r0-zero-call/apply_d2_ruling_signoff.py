"""Land the U signature on the D-2 axis ruling (refuses anything unsigned, fills nothing in).

Produces ``claims-d2-axis-decided.json``: the ruling body verbatim + ``status`` ``decided_signed`` +
``countersignature`` pointing at the signed instrument. Fail-closed: no named signature, no output.

Usage:
    python apply_d2_ruling_signoff.py [--force]
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]  # .scratch/claims-r2-role-isolation
REPO_ROOT = ROOT.parents[1]
sys.path.insert(0, str(REPO_ROOT))

from tools.evidence_guard import assert_writable, write_once  # noqa: E402

SIGNER = "xyl"
RULING = HERE / "claims-d2-axis-ruling.json"
INSTRUMENT = HERE / "claims-d2-axis-signoff.md"
DECIDED = HERE / "claims-d2-axis-decided.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _field(line: str, label: str) -> str:
    tail = line.split(label, 1)[1] if label in line else ""
    for stop in ("adjudicator:", "reviewer:", "signed_on:"):
        if stop != label and stop in tail:
            tail = tail.split(stop, 1)[0]
    return tail.strip()


def signature_of(text: str) -> dict[str, str]:
    line = next((ln.strip() for ln in text.splitlines() if ln.strip().startswith("reviewer:")), "")
    if not line:
        raise SystemExit("refusing to apply: instrument has no 'reviewer:' line")
    fields = {
        "signature_line": line,
        "reviewer": _field(line, "reviewer:"),
        "adjudicator": _field(line, "adjudicator:"),
        "signed_on": _field(line, "signed_on:"),
    }
    if SIGNER not in fields["reviewer"] or SIGNER not in fields["adjudicator"]:
        raise SystemExit(f"refusing to apply: instrument is not named-signed: {line!r}")
    if not fields["signed_on"]:
        raise SystemExit("refusing to apply: instrument signature carries no date")
    return fields


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    if DECIDED.exists() and not args.force:
        raise SystemExit("refusing to overwrite the decided record; use --force")
    ruling = json.loads(RULING.read_text(encoding="utf-8"))
    if ruling.get("status") != "draft_pending_human_signature":
        raise SystemExit(f"refusing to apply: ruling status is {ruling.get('status')!r}")
    signature = signature_of(INSTRUMENT.read_text(encoding="utf-8"))

    decided = copy.deepcopy(ruling)
    decided["status"] = "decided_signed"
    decided["countersignature"] = {
        "required": True,
        "status": "signed",
        "reviewer": signature["reviewer"],
        "adjudicator": signature["adjudicator"],
        "signed_on": signature["signed_on"],
        "instrument": {
            "path": str(INSTRUMENT.relative_to(ROOT)),
            "sha256": f"sha256:{sha256(INSTRUMENT)}",
            "signature_line": signature["signature_line"],
        },
        "statement": (
            "核准 D-2 分源精度轴裁定（107 号）：per_source_precision 维持诊断读法——只报告、"
            "不 gating，对本轮及后续轮次均生效；判定口径维持合并 candidate_precision 单一口径。"
            "本裁定不改变任何已发生判定（105 号 A 档由合并口径 + 护栏得出），95–106 号字节不动。"
        ),
        "covered": [
            "裁定：per_source_precision 维持诊断（只报告、不 gating）",
            "四条依据（小样本无判别力 / 本轮无不均衡信号 / 归因臂已有归属 / 时机纪律）",
            "对既有记录的影响：取代读法关闭 99 号 does_not_change[3] 的『D-2 仍未裁』自述",
        ],
        "does_not_cover": ["生产 PG/web 读链（另行立项）", "任何线值与护栏条款"],
        "signature_applied_by": "apply_d2_ruling_signoff.py（零调用；不代填任何签名字段）",
    }
    payload = json.dumps(decided, ensure_ascii=False, indent=2) + "\n"
    assert_writable(DECIDED, reason="107 号 D-2 生效裁定件")
    write_once(DECIDED, payload)
    print(json.dumps({"decided_sha256": hashlib.sha256(payload.encode()).hexdigest()}, indent=2))
    print(json.dumps(decided["countersignature"]["instrument"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
