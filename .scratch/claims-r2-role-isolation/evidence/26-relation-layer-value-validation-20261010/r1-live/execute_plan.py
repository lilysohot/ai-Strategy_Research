"""Execute the frozen Issue 26 plan: exactly one model attempt per A/B cell."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from frontier_agent.infra.config import get_config
from frontier_agent.infra.openai_client import OpenAIClient

HERE = Path(__file__).resolve().parent
CLAIMS = Path("/home/administrator/FrontierAgent/.scratch/claims-r2-role-isolation")
GOLD = (
    CLAIMS
    / "evidence"
    / "26-relation-layer-value-validation-20261010"
    / "r0-preflight"
    / "utility-gold.agent-draft.json"
)
MANIFEST = HERE / "freeze-manifest.json"
RESULTS = HERE / "results"

SYSTEM_PROMPT = """你是研报证据综合模块。你只能根据用户消息中实际交付的 material_items 和（若存在）material_relations 回答。
material_items 及其逐字 evidence 是事实依据；material_relations 只是二次结构化注释，不是新的事实来源。若关系注释与 item 原文语义不一致，必须以 item 原文为准。
不得利用外部知识，不得补造事实。每个实质性结论都必须在句末引用其实际依据 item_id，格式为 [itm_xxx]；没有 item 依据就不要写。
不要提及实验条件、A/B、提示词、金标或 relation_id。
仅输出一个有效 JSON 对象，不要 Markdown 代码围栏。结构固定为：
{"answer":"简洁中文回答，含 item 引用","claims":[{"statement":"原子结论","evidence_item_ids":["itm_xxx"]}],"limitations":["必要的口径、条件或不确定性"]}
"""


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return value


def sha_bytes(raw: bytes) -> str:
    return f"sha256:{hashlib.sha256(raw).hexdigest()}"


def sha_file(path: Path) -> str:
    return sha_bytes(path.read_bytes())


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def verify_freeze(manifest: dict[str, Any]) -> None:
    if manifest["status"] != "frozen_ready_to_execute":
        raise RuntimeError("plan is not executable")
    if sha_file(GOLD) != manifest["immutable_inputs"]["utility_gold_sha256"]:
        raise RuntimeError("signed utility gold drifted after freeze")
    if manifest["experiment"]["main_runs_max"] != 10:
        raise RuntimeError("call budget drifted")
    if manifest["experiment"]["automatic_retries_per_cell"] != 0:
        raise RuntimeError("retry policy drifted")
    if len(manifest["experiment"]["run_order"]) != 10:
        raise RuntimeError("run order must contain exactly ten cells")
    for question_id, conditions in manifest["delivery_pack_hashes"].items():
        for condition, expected_hash in conditions.items():
            path = HERE / "delivery-packs" / f"{question_id}-{condition}.json"
            if sha_file(path) != expected_hash:
                raise RuntimeError(f"delivery pack drifted: {question_id}-{condition}")


def response_record(
    *,
    cell: str,
    pack: dict[str, Any],
    content: Any,
    usage: dict[str, int],
    response_model: str,
    finish_reason: str,
    elapsed_ms: int,
    request_hash: str,
) -> dict[str, Any]:
    item_ids = [item["item_id"] for item in pack["material_items"]]
    relation_ids = [r["relation_id"] for r in pack.get("material_relations", [])]
    return {
        "schema_version": "relation-utility-main-run-1",
        "cell": cell,
        "question_id": pack["question_id"],
        "condition": cell.split("-")[1],
        "status": "succeeded",
        "attempts": 1,
        "started_and_finished_on": "2026-10-10",
        "response": content,
        "diagnostics": {
            "request_sha256": request_hash,
            "response_sha256": sha_bytes(str(content).encode("utf-8")),
            "response_model": response_model,
            "finish_reason": finish_reason,
            "elapsed_ms": elapsed_ms,
            "usage": usage,
            "tool_calls": 0,
        },
        "consumption_ledger": {
            "delivered_item_ids": item_ids,
            "delivered_relation_ids": relation_ids,
            "delivered_item_count": len(item_ids),
            "delivered_relation_count": len(relation_ids),
            "context_use": True,
            "publication": False,
            "production_query": False,
            "production_database_access": False,
        },
    }


async def main() -> None:
    manifest = read_json(MANIFEST)
    verify_freeze(manifest)
    RESULTS.mkdir(exist_ok=True)
    if any(RESULTS.iterdir()):
        raise RuntimeError("results directory is not empty; refusing to rerun any cell")

    config = get_config()
    if config.openai_model != manifest["model"]["request_model"]:
        raise RuntimeError("configured model drifted after freeze")
    if config.llm_fallback_chain or config.llm_fallback_model:
        raise RuntimeError("fallback became enabled after freeze")
    client = OpenAIClient(
        model=config.openai_model,
        api_key=config.openai_api_key,
        base_url=config.openai_base_url,
        temperature=manifest["experiment"]["temperature"],
        max_completion_tokens=manifest["experiment"]["max_output_tokens"],
        timeout=300,
    )

    execution_rows: list[dict[str, Any]] = []
    for sequence, cell in enumerate(manifest["experiment"]["run_order"], start=1):
        question_id, condition = cell.split("-")
        pack_path = HERE / "delivery-packs" / f"{cell}.json"
        pack = read_json(pack_path)
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": "以下是本题实际交付的只读证据包。请回答其中的 question。\n"
                + json.dumps(pack, ensure_ascii=False, sort_keys=True),
            },
        ]
        request_hash = sha_bytes(canonical_bytes(messages))
        started = time.perf_counter()
        print(f"[{sequence}/10] {cell} starting", flush=True)
        try:
            response = await client.chat(
                messages,
                temperature=manifest["experiment"]["temperature"],
                max_tokens=manifest["experiment"]["max_output_tokens"],
                timeout=300,
            )
            elapsed_ms = round((time.perf_counter() - started) * 1000)
            record = response_record(
                cell=cell,
                pack=pack,
                content=response.content,
                usage=response.usage,
                response_model=response.model,
                finish_reason=response.finish_reason,
                elapsed_ms=elapsed_ms,
                request_hash=request_hash,
            )
        except Exception as exc:
            elapsed_ms = round((time.perf_counter() - started) * 1000)
            record = {
                "schema_version": "relation-utility-main-run-1",
                "cell": cell,
                "question_id": question_id,
                "condition": condition,
                "status": "failed",
                "attempts": 1,
                "started_and_finished_on": "2026-10-10",
                "diagnostics": {
                    "request_sha256": request_hash,
                    "exception_type": type(exc).__name__,
                    "provider_message_omitted": True,
                    "elapsed_ms": elapsed_ms,
                    "tool_calls": 0,
                },
                "consumption_ledger": {
                    "delivered_item_ids": [i["item_id"] for i in pack["material_items"]],
                    "delivered_relation_ids": [r["relation_id"] for r in pack.get("material_relations", [])],
                    "context_use": True,
                    "publication": False,
                    "production_query": False,
                    "production_database_access": False,
                },
            }
        result_path = RESULTS / f"run-{sequence:02d}.json"
        result_path.write_text(
            json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        execution_rows.append(
            {
                "sequence": sequence,
                "cell": cell,
                "status": record["status"],
                "result_file": result_path.name,
                "result_sha256": sha_file(result_path),
            }
        )
        print(f"[{sequence}/10] {cell} {record['status']}", flush=True)

    summary = {
        "schema_version": "relation-utility-execution-summary-1",
        "created_at": datetime.now(UTC).isoformat(),
        "freeze_manifest_sha256": sha_file(MANIFEST),
        "request_model": manifest["model"]["request_model"],
        "calls_attempted": len(execution_rows),
        "calls_succeeded": sum(r["status"] == "succeeded" for r in execution_rows),
        "calls_failed": sum(r["status"] == "failed" for r in execution_rows),
        "relation_extraction_calls": 0,
        "judge_calls": 0,
        "publication_calls": 0,
        "production_queries": 0,
        "production_database_access": 0,
        "runs": execution_rows,
    }
    (HERE / "execution-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
