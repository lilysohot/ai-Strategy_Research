#!/usr/bin/env python3
"""Acceptance gates for ``server/spike.py``.

Run after the spike::

    uv run python server/spike.py
    uv run python server/verify_spike.py --root /tmp/frontier-spike

Each gate has an explicit "what it means if this fails" so a red result points
at a decision rather than at a stack trace. Exit code is 0 only when every
gate that applies to the current mode passes.

    A1  pipeline registered          CWD-relative spec discovery works
    A2  tool call round-trips        the endpoint can drive native function
                                     calling — THE go/no-go gate
    A3  artefact lands in run dir    per-run filesystem roots are honoured
    A4  trajectory archived in run   _trial_dir works, no CWD-relative logs/
    A5  final answer produced        end-to-end reasoning works
    A6  no upstream files touched    the monorepo boundary rule holds
    A7  event stream persisted       events.jsonl is replayable by line number
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"


def _load_events(run_dir: Path) -> list[dict[str, Any]]:
    path = run_dir / "events.jsonl"
    if not path.is_file():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            events.append({"type": "__unparseable__"})
    return events


def _tree(path: Path, *, depth: int = 2) -> list[str]:
    if not path.is_dir():
        return []
    out: list[str] = []
    for child in sorted(path.rglob("*")):
        rel = child.relative_to(path)
        if len(rel.parts) <= depth:
            out.append(str(rel) + ("/" if child.is_dir() else ""))
    return out


def check_a1(summary: dict[str, Any], events: list[dict]) -> tuple[str, str]:
    if summary.get("error"):
        return FAIL, f"run raised: {summary['error']}"
    if not any(e.get("type") == "run_started" for e in events):
        return FAIL, "no run_started event — the loop never entered"
    return PASS, f"events={len(events)}, turns={summary.get('turns', 0)}"


def check_a2(summary: dict[str, Any], events: list[dict]) -> tuple[str, str]:
    calls = summary.get("tool_calls") or []
    started = [e for e in events if e.get("type") == "tool_started"]
    if not calls or not started:
        return FAIL, (
            "no tool call round-tripped. The endpoint could not drive native "
            "function calling, or the tool was not in the role's allowlist. "
            "This is the go/no-go gate: tool_call_format has no profile knob."
        )
    errors = summary.get("tool_errors") or []
    if errors:
        return FAIL, f"tool calls raised: {errors}"
    return PASS, f"{len(calls)} call(s): {', '.join(calls)}"


def check_a3(paths: dict[str, Path]) -> tuple[str, str]:
    outputs = paths["outputs"]
    deliverables = [p for p in outputs.rglob("*") if p.is_file()] if outputs.is_dir() else []
    if not deliverables:
        return FAIL, (
            f"nothing written to {outputs}. Deliverables landed elsewhere — "
            "the per-run outputs root is not being honoured, or the write was "
            "denied by path authorisation."
        )
    stray = [
        str(p) for p in (Path("/workspace"), Path("/outputs"), Path("/inputs"))
        if p.exists()
    ]
    if stray:
        return FAIL, f"agent used container-default mounts, not per-run roots: {stray}"
    names = ", ".join(p.name for p in deliverables)
    return PASS, f"{len(deliverables)} deliverable(s) in run dir: {names}"


def check_a4(paths: dict[str, Path]) -> tuple[str, str]:
    traj = paths["run"] / "agent" / "trajectories"
    files = [p for p in traj.rglob("*") if p.is_file()] if traj.is_dir() else []
    if not files:
        return FAIL, (
            f"no trajectories under {traj}. Without _trial_dir the runtime "
            "writes to CWD-relative logs/, which is outside the persistent "
            "run volume."
        )
    return PASS, f"{len(files)} trajectory file(s)"


def check_a5(summary: dict[str, Any], real: bool) -> tuple[str, str]:
    answer = (summary.get("answer") or "").strip()
    if not answer:
        return FAIL, "final_answer empty — the run produced no answer"
    if not real:
        return PASS, f"answer present ({len(answer)} chars); content N/A (scripted mock)"
    if len(answer) < 20:
        return FAIL, f"answer implausibly short for a real endpoint: {answer!r}"
    return PASS, f"answer {len(answer)} chars: {answer[:120]}…"


def check_a6(baseline: list[str]) -> tuple[str, str]:
    """The spike must not write outside ``server/``.

    Compared against the porcelain snapshot ``spike.py`` took before the run,
    so a working tree that was already dirty is not reported as a regression.
    """
    current = subprocess.run(
        ["git", "status", "--porcelain"], cwd=REPO_ROOT,
        capture_output=True, text=True, check=True,
    ).stdout.strip().splitlines()
    ignored = subprocess.run(
        ["git", "status", "--porcelain", "--ignored"], cwd=REPO_ROOT,
        capture_output=True, text=True, check=True,
    ).stdout
    ignored_paths = {line[3:].strip() for line in ignored.splitlines()
                     if line.startswith("!!")}

    introduced = [line for line in current if line not in baseline]
    offenders: list[str] = []
    for line in introduced:
        path = line[3:].strip().strip('"')
        if path.split("/")[0] == "server":
            continue
        if any(path == ig or path.startswith(ig.rstrip("/") + "/")
               for ig in ignored_paths if ig):
            continue
        offenders.append(line)
    if offenders:
        return FAIL, "spike wrote outside server/: " + "; ".join(offenders)

    # data/ is created by BenchmarkSession._bootstrap at CWD and is gitignored,
    # so it never shows up above — say so explicitly rather than look clean.
    side_effects = [p for p in ("data", "logs") if (REPO_ROOT / p).is_dir()]
    note = f"; CWD side effects (gitignored): {', '.join(side_effects)}" if side_effects else ""
    return PASS, f"no new changes outside server/{note}"


def check_a7(events: list[dict]) -> tuple[str, str]:
    if not events:
        return FAIL, "events.jsonl empty or missing"
    unparseable = [e for e in events if e.get("type") == "__unparseable__"]
    if unparseable:
        return FAIL, f"{len(unparseable)} line(s) not valid JSON"
    seqs = [e.get("seq") for e in events]
    if seqs != list(range(1, len(events) + 1)):
        return FAIL, f"line-number cursor is not dense 1..N: got {seqs[:10]}…"
    return PASS, f"{len(events)} events, dense cursor 1..{len(events)}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default="/tmp/frontier-spike")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    run_dir = root / "run"
    summary_path = run_dir / "summary.json"
    if not summary_path.is_file():
        print(f"no summary at {summary_path} — run server/spike.py first")
        return 2

    summary: dict[str, Any] = json.loads(summary_path.read_text(encoding="utf-8"))
    events = _load_events(run_dir)
    paths = {k: Path(v) for k, v in summary["paths"].items()}
    real = bool(summary.get("config", {}).get("real"))

    gates = [
        ("A1 pipeline registered", check_a1(summary, events)),
        ("A2 tool call round-trips", check_a2(summary, events)),
        ("A3 artefact in run dir", check_a3(paths)),
        ("A4 trajectory archived", check_a4(paths)),
        ("A5 final answer produced", check_a5(summary, real)),
        ("A6 no upstream touched", check_a6(summary.get("git_baseline") or [])),
        ("A7 events replayable", check_a7(events)),
    ]

    width = max(len(name) for name, _ in gates)
    print(f"\nspike tree : {root}")
    print(f"mode       : {'REAL endpoint' if real else 'scripted mock'}"
          f"  model={summary.get('config', {}).get('model')}")
    print(f"duration   : {summary.get('duration_s')}s\n")
    for name, (status, detail) in gates:
        print(f"  [{status}] {name.ljust(width)}  {detail}")

    failed = [name for name, (status, _) in gates if status == FAIL]
    print()
    if failed:
        print(f"RESULT: FAIL — {len(failed)} gate(s) red: {', '.join(failed)}")
        if "A2 tool call round-trips" in failed:
            print("\nA2 is the go/no-go gate. If it is red on the real endpoint and the")
            print("endpoint cannot be changed, stop: tool_call_format has no profile")
            print("knob and the boundary rule forbids patching the kernel.")
        return 1
    print("RESULT: PASS — the web-platform runtime chain is reachable end to end.")
    if not real:
        print("\nNOTE: this run used the scripted mock. It proves the wiring, not the")
        print("model. Re-run with --real before committing to M1:")
        print("  uv run python server/spike.py --real \\")
        print("    --base-url <endpoint>/v1 --model <model> --api-key \"$KEY\"")
    return 0


if __name__ == "__main__":
    sys.exit(main())
