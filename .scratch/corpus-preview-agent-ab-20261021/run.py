"""Six serial real-workflow runs; only the evidence-preview flag differs."""
import argparse
import asyncio
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
BASE = ROOT / ".scratch/corpus-vector-acceptance-20261020"
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location("prior_eval", BASE / "run_eval.py")
prior = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prior)
save = prior.save
SELECTED = ("p01", "p16", "n01")


async def run(case_id, mode):
    cases, _, digest, profile = prior.setup()
    case = next(c for c in cases if c["id"] == case_id)
    os.environ["CORPUS_RETRIEVAL_MODE"] = "hybrid"
    os.environ["CORPUS_EVIDENCE_PREVIEW"] = mode
    trial = HERE / "runs" / case_id / mode
    if (trial / "result.json").exists():
        return
    recorder = prior.Recorder(trial / "observations.json")
    recorder.flush()
    from benchmarks.public.core.kernel_adapter import BenchmarkSession
    prompt = (
        "仅根据当前已发布的本地资料库回答下面的问题。先检索，再用 corpus_fetch 读取原文，"
        "最终答案简洁，并给出来源标题、doc_id 和 locator。信息不足就明确指出，"
        "不要用其他公司、其他年份或预测数替代。不要调用外部数据。问题：\n" + case["question"]
    )
    meta = {
        "profile": "tui", "_trial_dir": str(trial), "sdk_extra_observers": [recorder],
        "profile_overrides": {
            "llm": {"max_tokens": 8192},
            "agent": {
                "agent_tools": ["corpus_search", "corpus_fetch"],
                "task_board": False, "reporter": False, "main_max_turns": 12,
                "research_wall_time_s": 300, "wall_deadline_reserve_s": 30,
                "llm_timeout_s": 180, "logical_call_timeout_s": 210,
                "reasoning_only_timeout_s": 120, "reasoning_only_max_tokens": 4096,
                "salvage_infra_errors": False, "compaction_spill": False,
            },
        },
    }
    result = {"case": case_id, "mode": mode, "question": case["question"],
              "manifest_sha256": digest, "vector_profile": profile,
              "model": os.environ.get("OPENAI_MODEL"), "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
              "profile_overrides": meta["profile_overrides"]}
    start = time.monotonic()
    try:
        async with BenchmarkSession() as session:
            state = await asyncio.wait_for(session.run(
                prompt, meta=meta, pipeline_id="stateful-react-agent",
                extra_input={"language": "zh", "continuity_enabled": False},
            ), timeout=355)
        for key in ("final_answer", "answer_status", "stopped_by", "final_answer_source",
                    "final_answer_rescued", "errors", "react_steps"):
            result[key] = state.get(key)
    except Exception as exc:
        result["error_type"] = type(exc).__name__
    result["elapsed_s"] = round(time.monotonic() - start, 3)
    entries = recorder.data["tools"]
    for name in ("search", "fetch"):
        group = [t for t in entries if t["name"] == "corpus_" + name]
        result[name + "_calls"] = len(group)
        result[name + "_duration_ms"] = sum(t["duration_ms"] for t in group)
    result["tool_errors"] = sum(t["is_error"] for t in entries)
    result["usage_responses"] = [r["usage"] for r in recorder.data["responses"]]
    result["degraded_attempts"] = sum(a.get("outcome") == "accepted_degraded" for a in recorder.data["attempts"])
    result["progress_only"] = any(r.get("tool_calls") and r.get("text") == result.get("final_answer")
                                  for r in recorder.data["responses"]) and bool(result.get("final_answer"))
    save(trial / "result.json", result)
    print(json.dumps({k: result.get(k) for k in ("case", "mode", "elapsed_s", "search_calls", "fetch_calls", "stopped_by", "error_type")}), flush=True)


def batch():
    cases, _, digest, profile = prior.setup()
    plan = {"cases": [{"id": c["id"], "question": c["question"]} for c in cases if c["id"] in SELECTED],
            "order": [[cid, mode] for i, cid in enumerate(SELECTED)
                      for mode in (("off", "pilot") if i % 2 == 0 else ("pilot", "off"))],
            "manifest_sha256": digest, "vector_profile": profile,
            "limitations": "One run per arm/case; no statistical speed claim; same authored questions, no blind holdout. Real model/query embedding calls, no document re-embedding. Serial fresh processes; existing workflow tool budgets unchanged."}
    save(HERE / "plan.json", plan)
    failures = 0
    for cid, mode in plan["order"]:
        trial = HERE / "runs" / cid / mode
        trial.mkdir(parents=True, exist_ok=True)
        if not (trial / "result.json").exists():
            with (trial / "run.log").open("w") as log:
                try:
                    subprocess.run([sys.executable, str(Path(__file__).resolve()), "run", "--case", cid, "--mode", mode],
                                   cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, timeout=380, check=True)
                except (subprocess.TimeoutExpired, subprocess.CalledProcessError) as exc:
                    save(trial / "result.json", {"case": cid, "mode": mode, "error_type": type(exc).__name__})
        result = json.loads((trial / "result.json").read_text())
        print(json.dumps({k: result.get(k) for k in ("case", "mode", "elapsed_s", "search_calls", "fetch_calls", "stopped_by", "error_type")}), flush=True)
        if result.get("error_type") or result.get("stopped_by") == "llm_error" or result.get("progress_only"):
            failures += 1
            if failures >= 2:
                print("Stopped after two infrastructure failures.", flush=True)
                break


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("run", "batch"))
    parser.add_argument("--case", choices=SELECTED)
    parser.add_argument("--mode", choices=("off", "pilot"))
    args = parser.parse_args()
    if args.action == "batch":
        batch()
    else:
        asyncio.run(run(args.case, args.mode))
