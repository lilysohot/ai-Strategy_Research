"""Concurrent dispatcher for the frozen S5 full-model matrix.

This file leaves the frozen runner unchanged and delegates every session,
judge call, protocol check, result write, and report write to that runner.
It only changes dispatch after the completed 102-session first round.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from types import ModuleType
from typing import Any


HERE = Path(__file__).resolve().parent
RUNNER_PATH = HERE / "s5_full_model_matrix.py"


def load_runner() -> ModuleType:
    spec = importlib.util.spec_from_file_location("s5_frozen_runner", RUNNER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load frozen runner: {RUNNER_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--concurrency", type=int, choices=(2, 3, 4), default=2)
    parser.add_argument("--timeout", type=int, default=1800)
    args = parser.parse_args()

    runner = load_runner()
    answer_model, judge_model = runner.load_configured_models()
    targets = runner.load_targets()
    target_ids = list(targets)
    if len(target_ids) != 51:
        raise SystemExit(f"expected 51 frozen targets, found {len(target_ids)}")

    profile_checks: dict[str, dict[str, Any]] = {}
    for name, arm in runner.ARMS.items():
        actual = runner.git_output("rev-parse", "HEAD", cwd=Path(arm["code_root"]))
        if actual != arm["commit"]:
            raise SystemExit(f"{name} code root is {actual}, expected {arm['commit']}")
        database = runner.verify_arm_database(str(arm["database"]))
        print(f"[preflight] {name} database={database}", flush=True)
        profile_checks[name] = runner.verify_tool_profile(Path(arm["code_root"]))
        print(f"[preflight] {name} tools={profile_checks[name]}", flush=True)

    manifest = json.loads(runner.MANIFEST.read_text(encoding="utf-8"))
    runner.validate_manifest(
        manifest,
        answer_model=answer_model,
        judge_model=judge_model,
        target_ids=target_ids,
        profile_checks=profile_checks,
    )
    print(f"[freeze-check] validated {runner.MANIFEST}", flush=True)
    asyncio.run(runner.verify_judge_access())
    print("[preflight] Judge authentication and model routing succeeded", flush=True)

    schedule = runner.build_schedule(target_ids)
    results_by_position: dict[int, dict[str, Any]] = {}
    pending_by_repeat: dict[int, list[tuple[int, dict[str, Any]]]] = {2: [], 3: []}

    for position, item in enumerate(schedule, start=1):
        repeat = int(item["repeat"])
        target_id = str(item["target_id"])
        arm_name = str(item["arm"])
        result_path = (
            runner.RUNS_ROOT / arm_name / target_id / f"run-{repeat:02d}" / "result.json"
        )
        if result_path.exists():
            result = json.loads(result_path.read_text(encoding="utf-8"))
            verdict = (result.get("judge") or {}).get("verdict")
            if result.get("status") == "protocol_violation":
                raise RuntimeError(
                    "closed-tool protocol violation; matrix halted: "
                    + "; ".join(result.get("protocol_violations") or [])
                )
            if verdict in {"pass", "fail"}:
                runner.refresh_source_offered(result)
                result_path.write_text(
                    json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                results_by_position[position] = result
                continue
        if repeat == 1:
            raise RuntimeError(
                f"first-round boundary is incomplete at session {position}: "
                f"{arm_name}/{target_id}/run-{repeat:02d}"
            )
        pending_by_repeat[repeat].append((position, item))

    def ordered_results() -> list[dict[str, Any]]:
        return [results_by_position[position] for position in sorted(results_by_position)]

    def execute_item(position: int, item: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        repeat = int(item["repeat"])
        target_id = str(item["target_id"])
        arm_name = str(item["arm"])
        print(
            f"[run {position}/{len(schedule)}] r{repeat} {target_id} {arm_name}",
            flush=True,
        )
        result_path = (
            runner.RUNS_ROOT / arm_name / target_id / f"run-{repeat:02d}" / "result.json"
        )
        existed = result_path.exists()
        result = runner.run_one(arm_name, targets[target_id], repeat, args.timeout)
        if result.get("status") == "protocol_violation":
            raise RuntimeError(
                "closed-tool protocol violation; matrix halted: "
                + "; ".join(result.get("protocol_violations") or [])
            )
        if not existed or (result.get("judge") or {}).get("verdict") not in {"pass", "fail"}:
            result["judge"] = asyncio.run(runner.judge_one(result, targets[target_id]))
        if (result.get("judge") or {}).get("verdict") == "judge_error":
            result_path.write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            raise RuntimeError(
                f"Judge failed for {arm_name}/{target_id}/run-{repeat:02d}: "
                f"{result['judge']['reason']}"
            )
        runner.refresh_source_offered(result)
        result_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return position, result

    runner.write_report(ordered_results(), manifest)
    pending_count = sum(len(items) for items in pending_by_repeat.values())
    print(
        f"[resume] completed={len(results_by_position)} pending={pending_count} "
        f"concurrency={args.concurrency}",
        flush=True,
    )

    for repeat in (2, 3):
        pending = pending_by_repeat[repeat]
        if not pending:
            continue
        print(f"[round] repeat={repeat} pending={len(pending)}", flush=True)
        with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
            futures = {
                executor.submit(execute_item, position, item): position
                for position, item in pending
            }
            for future in as_completed(futures):
                position, result = future.result()
                results_by_position[position] = result
                results = ordered_results()
                runner.write_report(results, manifest)
                print(
                    f"[done {position}/{len(schedule)}] {result['status']} "
                    f"judge={result['judge'].get('verdict')} "
                    f"offered={(result.get('deterministic') or {}).get('source_offered')} "
                    f"fetched={(result.get('deterministic') or {}).get('quote_fetched')} "
                    f"wall={result.get('wall_s')}s",
                    flush=True,
                )

    results = ordered_results()
    runner.write_report(results, manifest)
    print(json.dumps(runner.aggregate(results), ensure_ascii=False, indent=2), flush=True)
    print(f"[report] {runner.REPORT}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
