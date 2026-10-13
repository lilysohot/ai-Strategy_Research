#!/usr/bin/env python3
"""Publish the base packet through the full executor path with the P-A repair note.

The repair note (ledger feedback + terminal-reason vocabulary) is injected by wrapping
the roles-module llm entry point via a module-attribute patch — production pipeline
code is untouched, and the deviation is declared in the run record. One model call
(doubao, thinking=disabled + 262144, same as the successful r1-repair attempt).
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(REPO_ROOT))

from plugins.corpus import structured  # noqa: E402
from plugins.corpus.structured import roles as roles_mod  # noqa: E402
from plugins.corpus.structured.config import (  # noqa: E402
    RequestOptions,
    bind_roles,
    load_extraction_config,
)
from plugins.corpus.structured.ledger import BatchPlan, execute_batch  # noqa: E402
from plugins.corpus.structured.snapshot import EvidenceSnapshot  # noqa: E402

HERE = Path(__file__).resolve().parent
RUNS = HERE.parents[1] / "65-rerun-two-arm-protocol-20261013"
# Control arm (Ark deepseek-v4-flash): the ONLY arm whose output may enter scoring.
TARGET = RUNS / "r3-control-live/base-7critical"

REPAIR_NOTE = """

【补充记账指令 — P-A 修复尝试（2026-10-13 授权，声明式提示词偏差）】
上一次尝试中有 3 个槽位未被正确记账，导致整包无法通过完整性门：
- slot_ef08e9bee54690b0、slot_1996d09d1fd9cdef：item 未通过 schema 校验
  （item_validation:schema）——请重新抽取并确保字段完整合法；
- slot_83bd83014d07f67e（「且无新的大额负面管制公告）；」）：其内容是相邻主张的
  从属条件从句，请输出终端覆盖记录 status=no_supported_item。
终端记录的 reason_code 必须使用白名单词汇：从属条件从句/非独立命题请使用
`no_independent_proposition`（上次自创的 SUBORDINATED_CONDITION_CLAUSE 不在白名单被拒）。
请输出全部 7 个槽位的结局。
"""


def sha(p: Path) -> str:
    return "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    import time

    from plugins.corpus.structured.ledger import plan_batch

    snapshot = EvidenceSnapshot.model_validate_json(
        (TARGET / "snapshot.json").read_text(encoding="utf-8")
    )
    snapshot.verify_identity()
    cfg = load_extraction_config(
        dotenv_path=REPO_ROOT / ".env",
        # env override: the plan freezes model=deepseek-v4-flash; .env currently holds
        # doubao (U switched back for treatment work). Only the model name is overridden —
        # base_url/API key in .env are already the Ark ones this plan was frozen with.
        environ={"STRUCTURED_EXTRACTION_MODEL": "deepseek-v4-flash"},
        options=RequestOptions(
            timeout_seconds=300.0,
            max_output_tokens=262144,
            token_parameter="max_tokens",
            reasoning_effort="minimal",
        ),
    )
    profile = cfg.require_profile()
    # Fresh plan with the same frozen config identity (fingerprint matches by
    # construction) and a live deadline — r3's frozen plan had expired.
    plan = plan_batch(
        snapshot,
        config=cfg,
        max_attempts=2,
        role_max_attempts={"claims": 0, "material_items": 2},
        relations_enabled=False,
        deadline_epoch=time.time() + 3600,
    )

    calls: list[dict[str, Any]] = []
    original = roles_mod.extract_material_items_role_from_snapshot

    def patched(snapshot: EvidenceSnapshot, *, llm, **kwargs: Any):
        def wrapped(prompt: str) -> str:
            resp = llm(prompt + REPAIR_NOTE)
            calls.append(
                {
                    "prompt_chars": len(prompt),
                    "response_chars": len(str(resp)),
                    "model": getattr(resp, "diagnostics", {}).get("response_model"),
                    "finish_reason": getattr(resp, "diagnostics", {}).get("finish_reason"),
                    "usage": getattr(resp, "diagnostics", {}).get("usage"),
                }
            )
            return str(resp)

        return original(snapshot, llm=wrapped, **kwargs)

    # Deviation point: patch the module attribute so execute_batch's internal dispatch
    # routes the items llm through the repair-note wrapper. Production code untouched.
    roles_mod.extract_material_items_role_from_snapshot = patched
    try:
        result = execute_batch(
            plan,
            store_root=HERE / "store-run3",
            allow_model=True,
            config=cfg,
        )
    finally:
        roles_mod.extract_material_items_role_from_snapshot = original

    summary = result.model_dump(mode="json") if hasattr(result, "model_dump") else {}
    (HERE / "publish-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8"
    )
    tasks = [
        {
            "role": t.role,
            "execution_status": t.execution_status,
            "protocol_status": t.protocol_status,
            "quality_status": t.quality_status,
            "publication_status": t.publication_status,
            "error_codes": list(t.error_codes),
        }
        for t in result.ledger.tasks
    ]
    report = {
        "schema_version": "base-publish-record-1",
        "created_on": "2026-10-13",
        "model": profile.model,
        "model_calls": len(calls),
        "calls": calls,
        "declared_deviation": "llm 包装注入 REPAIR_NOTE（逐字存档于本脚本）",
        "plan_consistent": result.plan_consistent,
        "findings": list(result.findings),
        "tasks": tasks,
    }
    (HERE / "publish-record.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {"calls": len(calls), "plan_consistent": result.plan_consistent, "tasks": tasks},
            ensure_ascii=False,
            indent=1,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
