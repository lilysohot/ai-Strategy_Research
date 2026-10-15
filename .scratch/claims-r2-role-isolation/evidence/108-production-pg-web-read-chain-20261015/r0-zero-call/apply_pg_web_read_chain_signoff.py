"""Land the U signature on the 108 号 production release gate (refuses anything unsigned, fills nothing in).

Produces ``production-pg-web-read-chain-release-decision.json``: the release question + the landed
evidence base verbatim, plus ``status`` ``decided_signed`` and a ``countersignature`` block pointing at
the signed instrument. Fail-closed: no named signature, no output. The signed instrument and every
existing artifact are left byte-identical.

Usage:
    python apply_pg_web_read_chain_signoff.py [--force]
"""

from __future__ import annotations

import argparse
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
PROPOSAL = HERE / "production-pg-web-read-chain-proposal.json"
INSTRUMENT = HERE / "production-pg-web-read-chain-signoff.md"
DECIDED = HERE / "production-pg-web-read-chain-release-decision.json"
BASE_FILES = (
    "production-pg-web-read-chain-proposal.json",
    "landing-record.json",
    "s3-acceptance-record.json",
    "current-state-scan.json",
    "place_production_store.py",
)


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
        raise SystemExit("refusing to overwrite the release decision; use --force")
    proposal: dict[str, Any] = json.loads(PROPOSAL.read_text(encoding="utf-8"))
    if proposal.get("status") != "draft_pending_human_signature":
        raise SystemExit(f"refusing to apply: proposal status is {proposal.get('status')!r}")
    signature = signature_of(INSTRUMENT.read_text(encoding="utf-8"))
    landing = json.loads((HERE / "landing-record.json").read_text(encoding="utf-8"))

    decision = {
        "schema_version": "production-pg-web-read-chain-release-decision-1",
        "id": "108-production-pg-web-read-chain-20261015",
        "created_on": "2026-10-15",
        "model_calls": 0,
        "production_pg_writes": 0,
        "status": "decided_signed",
        "title": "生产 PG/web 读链（生产放行门）· 放行裁定",
        "question": {
            "statement": proposal["title"],
            "scope_verbatim": proposal["plan"],
            "acceptance_criteria": proposal["acceptance_criteria"],
            "out_of_scope": proposal["out_of_scope"],
        },
        "landed_evidence": {
            "verdict_verbatim": landing["verdict"],
            "S1_production_store": landing["S1_production_store"],
            "S3_acceptance": landing["S3_acceptance"],
            "frozen_inputs_unchanged": landing["frozen_inputs_unchanged"],
        },
        "ruling": {
            "decision": "放行：接受 108 号落地记录所述生产形态为「生产放行门」通过",
            "accepted_form": (
                "生产 PG 活动 build（postgres.corpus，8 源 8 发布全 active、zhparser 全文索引在位）"
                " + 文件型 claims 生产 store（data/corpus/structured-store，CORPUS_STRUCTURED_ROOT 指向）"
                " + server/routes/corpus.py 四只读端点（get_current_user 鉴权）"
            ),
            "basis": (
                "U 于生产放行签认件具名签认（本件 countersignature.instrument）；"
                "签认件 §五 明示『是否放行由 U 具名签认，实施方不自宣』"
            ),
            "what_it_does_not_do": [
                "不改变 95–107 号任何已落地产物字节",
                "不放行 web 前端 corpus/claims 页面（立项时已出范围）",
                "不放行 claims 语义发布件进生产 PG（生产形态为文件型 store，已登记出范围）",
                "不改变生产 PG 任何状态（generation / activated_at 不变）",
            ],
        },
        "evidence_base": {
            name: f"sha256:{sha256(HERE / name)}" for name in BASE_FILES
        },
        "countersignature": {
            "required": True,
            "status": "signed",
            "reviewer": signature["reviewer"],
            "adjudicator": signature["adjudicator"],
            "signed_on": signature["signed_on"],
            "instrument": {
                "path": str(INSTRUMENT.relative_to(ROOT)),
                "sha256": f"sha256:{sha256(INSTRUMENT)}",
                "signature_line": signature["signature_line"],
                "body_status_line": (
                    "状态：草稿，**未签认**。`status = draft_pending_human_signature`。"
                    "（判为草稿期残留；本链统一读法 = 以签名栏为准）"
                ),
            },
            "statement": (
                "核准 108 号生产放行：生产 PG 活动 build 与文件型 claims 生产 store + server 只读读链"
                "端点为可接受的生产形态；放行判定由 U 具名作出，实施方不自宣。"
            ),
            "covered": [
                "S1 生产 claims store 落位（临时 root 复算 publication_id 与 106 号签认件逐一相同）",
                "S2 server/routes/corpus.py 四只读端点 + get_current_user 鉴权",
                "S3 端到端验收（401 守卫、检索命中、取证回读、两源三用途 7/7/7 与 8/3/3）",
                "S4 常驻测试 + 回归 + 落地记录",
            ],
            "does_not_cover": [
                "web 前端 corpus/claims 页面",
                "claims 语义发布件进生产 PG",
                "e6_holdout_corpus",
                "95–107 号任何产物的修订",
            ],
            "signature_applied_by": "apply_pg_web_read_chain_signoff.py（零调用；不代填任何签名字段）",
        },
        "untouched": [
            "签认件（production-pg-web-read-chain-signoff.md）保持 U 填写后的原字节",
            "proposal / landing-record / s3-acceptance / current-state-scan / place_production_store.py：字节未动",
            "95–107 号已落地产物：字节未动",
            "未写生产 PG、未发布任何东西、未代签",
        ],
    }
    payload = json.dumps(decision, ensure_ascii=False, indent=2) + "\n"
    assert_writable(DECIDED, reason="108 号生产放行裁定件")
    write_once(DECIDED, payload)
    print(json.dumps({"decided_sha256": hashlib.sha256(payload.encode()).hexdigest()}, indent=2))
    print(json.dumps(decision["countersignature"]["instrument"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
