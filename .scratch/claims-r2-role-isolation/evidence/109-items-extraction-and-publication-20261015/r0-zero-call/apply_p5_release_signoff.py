"""Land the U signature on the 109 号 P5 release instrument (refuses anything unsigned, fills nothing in).

Produces ``items-p5-release-decided.json``: the P5 release record verbatim + ``status``
``decided_signed`` + a ``countersignature`` block pointing at the signed instrument, which is what
authorises P6 (publish) and P7 (read chain). Fail-closed: no named signature, no output. The signed
instrument, the release record and every pre-existing artifact stay byte-identical.

Usage:
    python apply_p5_release_signoff.py [--force]
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
RECORD = HERE / "p5-release-record.json"
INSTRUMENT = HERE / "items-p5-release-signoff.md"
DECIDED = HERE / "items-p5-release-decided.json"


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
        raise SystemExit("refusing to overwrite the decided release record; use --force")
    record: dict[str, Any] = json.loads(RECORD.read_text(encoding="utf-8"))
    if record.get("status") != "draft_pending_human_signature":
        raise SystemExit(f"refusing to apply: release record status is {record.get('status')!r}")
    instrument_hash = f"sha256:{sha256(INSTRUMENT)}"
    # The instrument binds the hash of the release record it signs; if the record drifted after
    # signing, the signature no longer points at it and this must stop.
    bound = next(
        (
            line
            for line in INSTRUMENT.read_text(encoding="utf-8").splitlines()
            if line.startswith("| 其 sha256 |")
        ),
        "",
    )
    record_hash = sha256(RECORD)
    if record_hash[:16] not in bound:
        raise SystemExit(
            f"refusing to apply: instrument does not bind the current release record "
            f"({record_hash[:16]} absent from {bound!r})"
        )
    signature = signature_of(INSTRUMENT.read_text(encoding="utf-8"))

    decided = copy.deepcopy(record)
    decided["status"] = "decided_signed"
    decided["countersignature"] = {
        "required": True,
        "status": "signed",
        "reviewer": signature["reviewer"],
        "adjudicator": signature["adjudicator"],
        "signed_on": signature["signed_on"],
        "instrument": {
            "path": str(INSTRUMENT.relative_to(ROOT)),
            "sha256": instrument_hash,
            "signature_line": signature["signature_line"],
            "body_status_line": (
                "状态：草稿，**未签认**。`status = draft_pending_human_signature`。"
                "（判为草稿期残留；本链统一读法 = 以签名栏为准）"
            ),
            "signed_record": {
                "path": str(RECORD.relative_to(ROOT)),
                "sha256": f"sha256:{record_hash}",
            },
        },
        "statement": (
            "核准 109 号 P5 放行：授权起跑 P6（发布）与 P7（读链），两步均零调用、不写生产 PG。"
            "放行依据 = 72 号既定解耦路线（发布标准为结构完备性，与门阈值/金标解耦）；"
            "发布理由写『结构完备 + coverage 补全 + 缺口清单明示』，**不写『门 PASS』**。"
        ),
        "covered": [
            "P5 判档读法：判定轴 5 项中 4 项达标、唯一实质未达标 = 哨兵 NT-I43（合同层布尔 rate_gate_passed=false 并列保留）",
            "显式缺口清单随发布件逐条列出（金标未覆盖 7 条 + claims 欠账 12 条）",
            "P6 发布：--import-items-artifact → plan_batch → publish_semantic 全门 → 生产 store 两源 material_items coverage 补全 → 查询验收",
            "P7 读链：web items 查询端点 + 常驻测试 + 落地记录 + MANIFEST",
        ],
        "does_not_cover": [
            "主张质量达标或门通过（verdict_reading.gate = FAIL 逐字保留）",
            "合同 v4.3 / 评分器 / 阈值 / 预注册 的任何修订",
            "material_relations 角色（契约 OPEN-2=C，本轮不抽不评）",
            "生产 PG 任何写入",
            "C-1 读法认可件的具名补签（其 status 仍 stated_effective_pending_countersignature）",
        ],
        "signature_applied_by": "apply_p5_release_signoff.py（零调用；不代填任何签名字段）",
    }
    decided["read_after_signature"] = {
        "p6_p7_authorised": True,
        "gate_verdict_unchanged": "FAIL（单轴：哨兵 NT-I43）——逐字保留，放行依据不读作门 PASS",
        "basis_precedent": (
            "72 号 terminal-decision.json:178 / corrections.md:53：发布标准（结构完备性）与门阈值、"
            "金标解耦；store 对 gold/recall/assertion 零引用"
        ),
    }
    payload = json.dumps(decided, ensure_ascii=False, indent=2) + "\n"
    assert_writable(DECIDED, reason="109 号 P5 放行生效件")
    write_once(DECIDED, payload)
    print(json.dumps({"decided_sha256": hashlib.sha256(payload.encode()).hexdigest()}, indent=2))
    print(json.dumps(decided["countersignature"]["instrument"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
