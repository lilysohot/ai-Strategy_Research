"""Re-grade frozen generations with explicit JUDGE_MODEL/API_KEY/BASE_URL settings.

No fallback to the generator's credentials or model. Scores remain model judgments,
not ground truth; the case rubrics and raw answers are available for human review.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from benchmarks.team_synthesis.run import (
    DIMENSIONS,
    ROOT,
    digest,
    judge_messages,
    parse_judgment,
    write_json,
)
from frontier_agent.infra.openai_client import OpenAIClient


async def run(args: argparse.Namespace) -> None:
    load_dotenv(ROOT.parents[1] / ".env")
    settings = {
        key: os.environ.get(key, "").strip()
        for key in (
            "JUDGE_MODEL",
            "JUDGE_API_KEY",
            "JUDGE_BASE_URL",
        )
    }
    if not all(settings.values()):
        raise ValueError("set JUDGE_MODEL, JUDGE_API_KEY and JUDGE_BASE_URL explicitly")
    manifest = json.loads((args.source / "manifest.json").read_text())
    cases = {case["id"]: case for case in manifest["cases"]}
    llm = OpenAIClient(
        model=settings["JUDGE_MODEL"],
        api_key=settings["JUDGE_API_KEY"],
        base_url=settings["JUDGE_BASE_URL"].rstrip("/").removesuffix("/chat/completions"),
    )
    args.out.mkdir(parents=True, exist_ok=True)
    identity = {
        "source_fingerprint": manifest["fingerprint"],
        "model": settings["JUDGE_MODEL"],
        "settings_sha256": digest(settings),
        "max_tokens": args.max_tokens,
        "runner_sha256": digest(Path(__file__).read_text()),
    }
    path = args.out / "manifest.json"
    if path.exists() and json.loads(path.read_text()) != identity:
        raise ValueError("judge inputs changed; choose a fresh output directory")
    write_json(path, identity)
    semaphore = asyncio.Semaphore(args.concurrency)

    async def judge(pair: dict[str, Any]) -> dict[str, Any]:
        outputs = {
            label: json.loads((args.source / f"{pair['id']}-{label}.json").read_text())
            for label in pair["labels"]
        }
        if not all(output["ok"] for output in outputs.values()):
            raise ValueError("generation incomplete; finish the frozen source run first")
        messages = judge_messages(
            cases[pair["case"]], {label: output["content"] for label, output in outputs.items()}
        )
        input_hash = digest(messages)
        destination = args.out / f"{pair['id']}.json"
        if destination.exists():
            cached = json.loads(destination.read_text())
            if cached["input_sha256"] != input_hash:
                raise ValueError("source outputs changed after grading")
            if cached.get("ok"):
                return cached
        async with semaphore:
            started = time.monotonic()
            result: dict[str, Any] = {
                "pair": pair,
                "messages": messages,
                "input_sha256": input_hash,
                "ok": False,
            }
            try:
                response = await asyncio.wait_for(
                    llm.chat(messages, max_tokens=args.max_tokens, timeout=240), 250
                )
                result.update(
                    content=response.content,
                    model=response.model,
                    usage=response.usage,
                    finish_reason=response.finish_reason,
                )
                if response.tool_calls or response.finish_reason == "length":
                    raise ValueError("incomplete judgment")
                result["judgment"] = parse_judgment(response.content)
                result["ok"] = True
            except Exception as exc:
                result["error"] = type(exc).__name__
            result["elapsed_s"] = time.monotonic() - started
            write_json(destination, result)
            print(f"{pair['id']}: {'ok' if result['ok'] else result['error']}", flush=True)
            return result

    results = await asyncio.gather(*(judge(pair) for pair in manifest["pairs"]))
    groups: dict[str, list[list[int]]] = defaultdict(list)
    changes = []
    for result in results:
        if not result["ok"]:
            continue
        pair = result["pair"]
        scores = {}
        for label, arm in pair["labels"].items():
            scores[arm] = result["judgment"][label]["scores"]
            groups[f"{arm}/all"].append(scores[arm])
            groups[f"{arm}/{pair['split']}"].append(scores[arm])
        changes.append(
            {
                "case": pair["case"],
                "split": pair["split"],
                "repeat": pair["repeat"],
                "delta": [
                    c - b for b, c in zip(scores["baseline"], scores["candidate"], strict=True)
                ],
            }
        )
    summary = {
        "judge": identity["model"],
        "scored_pairs": len(changes),
        "failures": [r["pair"]["id"] for r in results if not r["ok"]],
        "paired_deltas": changes,
        "aggregates": {
            key: {
                "scored": len(rows),
                "passed": {dim: sum(row[i] for row in rows) for i, dim in enumerate(DIMENSIONS)},
            }
            for key, rows in groups.items()
        },
        "limitation": "Separate configured judge model; not human ground truth or proof of generality.",
    }
    write_json(args.out / "summary.json", summary)
    print(json.dumps(summary["aggregates"], ensure_ascii=False, indent=2))
    if summary["failures"]:
        raise RuntimeError("incomplete judging; inspect records before resuming")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--max-tokens", type=int, default=8192)
    args = parser.parse_args()
    if min(args.concurrency, args.max_tokens) < 1:
        parser.error("concurrency and max-tokens must be positive")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
