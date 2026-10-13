#!/usr/bin/env python3
"""P-A repair attempt for the base packet (authorized 2026-10-13).

One model call. The pluggable ``llm`` callable appends the DECLARED ledger-feedback
note (P-A) to the pipeline's own prompt — the model sees which slot was left
unaccounted and must give every slot an explicit terminal disposition. Everything
downstream (parse → slot ledger → coverage) runs through the unmodified pipeline, so
fail-closed semantics are untouched.

Model/params mirror the r2 treatment arm (doubao + thinking=disabled + 262144), the
best-performing doubao configuration.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(REPO_ROOT))

from plugins.corpus.material_semantics import (  # noqa: E402
    extract_material_items_role_from_snapshot,
)
from plugins.corpus.structured.config import (  # noqa: E402
    RequestOptions,
    bind_roles,
    load_extraction_config,
)
from plugins.corpus.structured.snapshot import EvidenceSnapshot  # noqa: E402

HERE = Path(__file__).resolve().parent
BASE = HERE.parent  # 66-base-protocol-change-proposal-20261013
R4_BASE = (
    REPO_ROOT
    / ".scratch/claims-r2-role-isolation/evidence/65-rerun-two-arm-protocol-20261013"
    / "r4-control-official/base-7critical"
)
SLOT_IDS = {
    "slot_ef08e9bee54690b0": "若从零开一个观察仓：",
    "slot_36c304436d5d2703": "等两件事至少中一件再议——(1) 回撤到 52–58…",
    "slot_83bd83014d07f67e": "且无新的大额负面管制公告）；",
    "slot_1996d09d1fd9cdef": "(2) Q3 OCF/扣非回到 0.6 以上…",
    "slot_3dfa35e5b40c1201": "单票不超过组合的合理上限。",
    "slot_292e7f88898806e5": "止损看两条硬的：",
    "slot_90af9c4e66866cda": "下季 OCF 盖不住扣非的一半…目标价…",
}

REPAIR_NOTE = """

【补充记账指令 — P-A 修复尝试（2026-10-13 授权，声明式提示词偏差）】
上一次对该片段的抽取中，槽位 slot_83bd83014d07f67e（原文：「且无新的大额负面管制公告）；」）
未被显式记账，导致整包无法通过完整性门。协议要求：每个槽位都必须有明确结局。
- 若你认为某槽位没有可独立抽取的条目（例如其内容只是相邻槽位主张的条件从句），
  请为该槽位输出终端覆盖记录（status=no_supported_item 或 not_candidate）；
  **reason_code 必须使用以下白名单词汇之一**（上一次尝试使用的
  SUBORDINATED_CONDITION_CLAUSE 不在白名单内被拒）：对"从属条件从句/非独立命题"
  请使用 `no_independent_proposition`；其他可用：fragment、incomplete_clause、
  incomplete_sentence、affirmation_fragment、header_only、section_label 等；
- 若你认为有，请重新抽取并输出完整 item 记录；
- 输出中请包含全部 7 个槽位的结局（6 个已提取槽位维持其 item 记录，1 个未决槽位给出终端记录）。
"""


def sha(p: Path) -> str:
    return "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    snapshot = EvidenceSnapshot.model_validate_json(
        (R4_BASE / "snapshot.json").read_text(encoding="utf-8")
    )
    snapshot.verify_identity()
    cfg = load_extraction_config(
        dotenv_path=REPO_ROOT / ".env",
        options=RequestOptions(
            timeout_seconds=300.0, max_output_tokens=262144, thinking="disabled"
        ),
    )
    profile = cfg.require_profile()
    import httpx

    from plugins.corpus.structured.adapter import ExtractionAdapter

    binding = next(b for b in bind_roles(cfg) if b.role == "material_items")
    adapter = ExtractionAdapter(
        binding=binding,
        authorize=lambda intent: f"repair-pa-{intent.request_sha256[7:23]}",
        transport_factory=lambda: httpx.HTTPTransport(),
    )

    calls: list[dict[str, Any]] = []

    def repair_llm(prompt: str) -> str:
        # P-A: append the declared ledger-feedback note to the pipeline's own prompt.
        resp = adapter(prompt + REPAIR_NOTE)
        calls.append(
            {
                "prompt_chars": len(prompt),
                "repair_note_chars": len(REPAIR_NOTE),
                "response_chars": len(str(resp)),
                "response_sha256": hashlib.sha256(str(resp).encode()).hexdigest(),
                "model": resp.diagnostics.get("response_model"),
                "finish_reason": resp.diagnostics.get("finish_reason"),
                "usage": resp.diagnostics.get("usage"),
            }
        )
        return str(resp)

    run = extract_material_items_role_from_snapshot(
        snapshot,
        protocol="material-atomic-jsonl-v5",
        llm=repair_llm,
        max_calls=2,
    )
    ledger = [
        {"slot": e.candidate_slot_id[:24], "status": e.status, "reason_codes": list(e.reason_codes)}
        for e in run.understanding.coverage.slot_ledger
    ]
    accounted = all(
        e["status"] in ("extracted", "no_supported_item", "not_candidate") for e in ledger
    )
    report = {
        "schema_version": "repair-attempt-record-1",
        "created_on": "2026-10-13",
        "authorization": "U 2026-10-13「执行 P-A」（66 提案 P-A：修复式重试，声明式提示词偏差）",
        "model": profile.model,
        "request_options": str(profile.options),
        "model_calls": len(calls),
        "calls": calls,
        "declared_deviation": "prompt 追加 REPAIR_NOTE（记账反馈）——已在本记录逐字存档",
        "slot_ledger": ledger,
        "all_slots_accounted": accounted,
        "records_per_packet": [p.records for p in run.packet_runs],
        "packet_status": [p.status for p in run.packet_runs],
        "packet_reasons": [list(p.reasons) for p in run.packet_runs],
    }
    (HERE / "repair-record.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "model_calls": len(calls),
                "all_slots_accounted": accounted,
                "ledger": ledger,
                "records": report["records_per_packet"],
                "packet_status": report["packet_status"],
            },
            ensure_ascii=False,
            indent=1,
        )
    )
    return 0 if accounted else 5


if __name__ == "__main__":
    raise SystemExit(main())
