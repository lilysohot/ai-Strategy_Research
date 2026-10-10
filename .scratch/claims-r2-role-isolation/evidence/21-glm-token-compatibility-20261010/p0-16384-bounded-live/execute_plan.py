"""Execute the frozen 16K plan with its exact credential-bearing profile."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from plugins.corpus.structured.config import RequestOptions, load_extraction_config
from plugins.corpus.structured.ledger import BatchPlan, execute_batch

ROOT = Path(__file__).resolve().parents[5]
HERE = Path(__file__).resolve().parent
STORE = HERE / "live-store-16k"


def main() -> None:
    if STORE.exists():
        raise RuntimeError("16K live store already exists; automatic rerun is forbidden")
    plan = BatchPlan.model_validate_json((HERE / "plan.json").read_text(encoding="utf-8"))
    plan.verify_identity()
    config = load_extraction_config(
        dotenv_path=ROOT / ".env",
        options=RequestOptions(
            timeout_seconds=300.0,
            max_output_tokens=16384,
            token_parameter="max_tokens",
        ),
    )
    profile = config.require_profile()
    if profile.model != "glm-5.3-flash" or profile.options.max_output_tokens != 16384:
        raise RuntimeError("frozen 16K extraction profile was not restored")
    result = execute_batch(
        plan,
        store_root=STORE,
        allow_model=True,
        config=config,
    )
    attempts = result.ledger.attempts
    relation_task = next(
        task for task in result.ledger.tasks if task.role == "material_relations"
    )
    usage = {
        key: sum((attempt.usage or {}).get(key) or 0 for attempt in attempts)
        for key in (
            "prompt_tokens",
            "completion_tokens",
            "reasoning_tokens",
            "total_tokens",
        )
    }
    print(
        json.dumps(
            {
                "batch_id": result.ledger.batch_id,
                "attempts": len(attempts),
                "attempt_status": dict(
                    Counter(attempt.execution_status for attempt in attempts)
                ),
                "relation_task_status": relation_task.execution_status,
                "usage": usage,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
