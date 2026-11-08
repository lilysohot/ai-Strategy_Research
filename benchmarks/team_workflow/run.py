"""Run versioned protocol cases or isolated teams with frozen source tools."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from benchmarks.team_workflow.metrics import measure, percentile

ROOT = Path(__file__).resolve().parents[2]
CATALOG = Path(__file__).with_name("cases.json")


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def write(path: Path, value: Any) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def catalog() -> list[dict[str, Any]]:
    cases = json.loads(CATALOG.read_text())
    if len({c["id"] for c in cases}) != len(cases):
        raise ValueError("duplicate case IDs")
    for case in cases:
        if case["layer"] == "protocol":
            selectors = case.get("selectors", [case.get("selector")])
            if not isinstance(selectors, list) or not selectors:
                raise ValueError(f"invalid selectors: {case['id']}")
            for selector in selectors:
                if not isinstance(selector, str):
                    raise ValueError(f"invalid selector: {case['id']}")
                source = (ROOT / selector.split("::")[0]).resolve()
                if not source.is_relative_to(ROOT) or not source.is_file():
                    raise ValueError(f"invalid selector: {case['id']}")
        elif case["layer"] == "frozen":
            if not case.get("rubric") or not case.get("sources") or not case.get("question"):
                raise ValueError(f"incomplete frozen case: {case['id']}")
        else:
            raise ValueError("unknown case layer")
    return cases


def require_runnable(case: dict[str, Any]) -> None:
    """Draft cases stay inspectable without silently joining model runs."""
    if case.get("review_status", "approved") != "approved":
        raise ValueError(f"Case {case['id']} is pending user review")
    if case.get("tool_fixture", "web") not in {"web", "corpus_document_v1"}:
        raise ValueError(f"Case {case['id']} has an unknown fixture adapter")


def select_cases(layer: str, requested: list[str] | None) -> list[dict[str, Any]]:
    cases = [c for c in catalog() if c["layer"] == layer]
    if requested:
        cases = [c for c in cases if c["id"] in requested]
        if set(requested) != {c["id"] for c in cases}:
            raise ValueError("unknown case or case belongs to another layer")
    else:
        cases = [c for c in cases if c.get("review_status", "approved") == "approved"]
    for case in cases:
        require_runnable(case)
    return cases


def source_fingerprint() -> dict[str, Any]:
    paths = []
    for folder in ("frontier_agent", "plugins", "workflows", "benchmarks/team_workflow", "tests"):
        paths.extend(
            p
            for p in (ROOT / folder).rglob("*")
            if p.is_file() and p.suffix in {".py", ".yaml", ".txt"}
        )
    hashes = {
        str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)
    }
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True, check=True
    ).stdout.strip()
    return {"git_revision": revision, "code_and_profiles_sha256": digest(hashes)}


def protocol_result(xml: Path, returncode: int) -> dict[str, Any]:
    if not xml.exists():
        return {"status": "error", "reason": "pytest produced no result XML"}
    tests = list(ET.parse(xml).getroot().iter("testcase"))
    failures = [t for t in tests if t.find("failure") is not None]
    errors = [t for t in tests if t.find("error") is not None]
    skipped = [t for t in tests if t.find("skipped") is not None]
    status = (
        "error"
        if errors or not tests or returncode not in (0, 1)
        else "fail"
        if failures or returncode
        else "unassessed"
        if skipped
        else "pass"
    )
    return {
        "status": status,
        "tests": len(tests),
        "failed": len(failures),
        "errors": len(errors),
        "skipped": len(skipped),
        "details": [
            {"test": t.get("name"), "text": "".join(t.itertext())[-6000:]}
            for t in failures + errors + skipped
        ],
    }


def frozen_result(
    worker: dict[str, Any], metrics: dict[str, Any], case: dict[str, Any]
) -> dict[str, Any]:
    if not worker.get("ok"):
        return {"status": "error", "reason": worker.get("error", "worker failed")}
    result = worker["result"]
    if result.get("stopped_by") in {"llm_error", "cancelled", "error"}:
        return {
            "status": "error",
            "reason": result["stopped_by"],
            "answer_status": result.get("answer_status"),
        }
    failures = []
    if not str(result.get("final_answer") or result.get("final_content") or "").strip():
        failures.append("empty final answer")
    if not metrics.get("available"):
        failures.append("missing trajectories")
    elif len(metrics["agents"]) < 2 and case.get("tool_fixture") != "corpus_document_v1":
        # Corpus reading cases permit direct delivery. Preserve the historical
        # teamwork gate for web fixtures without adding an unreviewed obligation.
        failures.append("no member execution observed")
    if worker["elapsed_s"] > case["budgets"]["wall_s"]:
        failures.append("wall budget exceeded")
    if metrics.get("known_prompt_tokens", 0) > case["budgets"]["max_prompt_tokens"]:
        failures.append("known input token budget exceeded")
    for budget, metric in (
        ("max_model_attempts", "attempts"),
        ("max_single_prompt_tokens", "max_prompt_tokens"),
        ("max_exact_repeated_requests", "exact_repeated_tool_requests"),
    ):
        if budget in case["budgets"]:
            observed = metrics.get(metric)
            if observed is None:
                failures.append(f"missing budget telemetry: {metric}")
            elif observed > case["budgets"][budget]:
                failures.append(f"{budget} exceeded")
    jobs = (result.get("report_contract") or {}).get("job_outcomes")
    research_jobs = (
        sum(not job.get("verification_checks") for job in jobs) if jobs is not None else None
    )
    if research_jobs is not None and research_jobs > case["budgets"]["max_research_jobs"]:
        failures.append("research task budget exceeded")
    return {
        "status": "fail" if failures else "needs_review",
        "hard_failures": failures,
        "answer_status": result.get("answer_status"),
        "semantic_review_required": True,
        "usage_complete": metrics.get("unknown_usage_attempts", 1) == 0,
        "research_jobs_accepted": research_jobs,
    }


def summarize(out: Path) -> dict[str, Any]:
    manifest = json.loads((out / "manifest.json").read_text())
    rows = []
    for sample in manifest["samples"]:
        path = out / sample["sample"] / "result.json"
        row = json.loads(path.read_text()) if path.exists() else {"status": "missing"}
        rows.append({**sample, **row})
    states = Counter(row["status"] for row in rows)
    durations = [float(r["elapsed_s"]) for r in rows if r.get("elapsed_s") is not None]
    summary = {
        "schema_version": 1,
        "manifest_sha256": digest(manifest),
        "states": dict(states),
        "samples": rows,
        "all_passed": bool(rows) and all(r["status"] == "pass" for r in rows),
        "duration_p50_s": percentile(durations, 0.5),
        "duration_p90_s": percentile(durations, 0.9),
        "limitations": [
            "Visible transfer cases are not an unseen holdout.",
            "Protocol passes do not certify model behavior.",
            "Frozen web fixtures do not test live retrieval ranking or network quality.",
            "Semantic results require artifact-bound human review.",
            "Repeated samples of one case are not independent task families.",
        ],
    }
    write(out / "summary.json", summary)
    lines = [
        "# Team workflow evaluation",
        "",
        f"States: {dict(states)}",
        "",
        "| Sample | Layer | Dimension | Status | Seconds |",
        "|---|---|---|---|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['sample']} | {row['layer']} | {row['dimension']} | "
            f"{row['status']} | {row.get('elapsed_s', '—')} |"
        )
    lines += ["", *summary["limitations"]]
    (out / "report.md").write_text("\n".join(lines) + "\n")
    return summary


def compare(before: Path, after: Path) -> dict[str, Any]:
    """Compare fixed samples; reject changed fixtures instead of inventing a paired score."""
    old_manifest = json.loads((before / "manifest.json").read_text())
    new_manifest = json.loads((after / "manifest.json").read_text())
    if old_manifest["catalog_sha256"] != new_manifest["catalog_sha256"]:
        raise ValueError("case set or budgets changed; these are not paired evaluations")
    if old_manifest["profile"] != new_manifest["profile"]:
        raise ValueError("profile differs; compare as separate experiments")
    old = {r["sample"]: r for r in summarize(before)["samples"]}
    new = {r["sample"]: r for r in summarize(after)["samples"]}
    comparisons = []
    for key in sorted(old.keys() | new.keys()):
        left, right = old.get(key, {}), new.get(key, {})
        a, b = left.get("status", "missing"), right.get("status", "missing")
        settings_a, settings_b = before / key / "settings.json", after / key / "settings.json"
        same_settings = None
        if settings_a.exists() and settings_b.exists():
            same_settings = json.loads(settings_a.read_text()) == json.loads(settings_b.read_text())
        comparisons.append(
            {
                "sample": key,
                "before": a,
                "after": b,
                "regressed": a == "pass" and b != "pass",
                "improved": a in {"fail", "error"} and b == "pass",
                "same_effective_settings": same_settings,
                "elapsed_delta_s": round(right["elapsed_s"] - left["elapsed_s"], 3)
                if left.get("elapsed_s") is not None and right.get("elapsed_s") is not None
                else None,
            }
        )
    return {
        "samples": comparisons,
        "regressions": sum(r["regressed"] for r in comparisons),
        "improvements": sum(r["improved"] for r in comparisons),
        "limits": "Latency deltas are diagnostic; settings drift and unknown usage require review.",
    }


def rescore(out: Path) -> None:
    """Reapply mechanical scoring to frozen outputs, preserving earlier assessments."""
    manifest = json.loads((out / "manifest.json").read_text())
    for sample in manifest["samples"]:
        trial = out / sample["sample"]
        if sample["layer"] != "frozen" or not (trial / "worker.json").exists():
            continue
        previous = json.loads((trial / "result.json").read_text())
        if previous.get("review_file"):
            raise ValueError("cannot mechanically rescore a reviewed sample")
        case = next(c for c in manifest["cases"] if c["id"] == sample["case"])
        metrics = measure(trial)
        current = frozen_result(json.loads((trial / "worker.json").read_text()), metrics, case)
        current["elapsed_s"] = previous.get("elapsed_s")
        current["assessment_code_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        count = len(list(trial.glob("assessment-before-*.json")))
        write(trial / f"assessment-before-{count:03d}.json", previous)
        write(trial / "result.json", current)
        write(trial / "metrics.json", metrics)
    summarize(out)


def mark_unassessed(out: Path, reason: str, *, mode: str = "automatic") -> None:
    """Stop accounting: never remove unrun samples from the denominator."""
    manifest = json.loads((out / "manifest.json").read_text())
    pending = []
    for sample in manifest["samples"]:
        trial = out / sample["sample"]
        if (trial / "result.json").exists():
            continue
        trial.mkdir(exist_ok=True)
        write(
            trial / "result.json",
            {
                "status": "unassessed",
                "reason": reason,
                "partial_trace_retained": (trial / "agent").exists(),
            },
        )
        pending.append(sample["sample"])
    write(
        out / "batch_stop.json",
        {
            "mode": mode,
            "reason": reason,
            "unassessed": pending,
            "timestamp": datetime.now(UTC).isoformat(),
        },
    )
    summarize(out)


def run(args: argparse.Namespace) -> int:
    selected = select_cases(args.layer, args.case)
    if not selected or args.repeats < 1:
        raise ValueError("select at least one matching case and a positive repeat count")
    if args.max_consecutive_errors < 1:
        raise ValueError("max-consecutive-errors must be positive")
    if args.case and set(args.case) != {c["id"] for c in selected}:
        raise ValueError("unknown case or case belongs to another layer")
    ab = getattr(args, "hint_ab", False)
    if ab and (
        args.layer != "frozen"
        or any(c.get("tool_fixture") != "corpus_document_v1" for c in selected)
    ):
        raise ValueError("--hint-ab requires explicit corpus frozen cases")
    out = args.out.resolve()
    # A new output directory per execution prevents silent reuse across dirty code,
    # changed budgets, profiles, fixtures or provider settings.
    out.mkdir(parents=True, exist_ok=False)
    samples = [
        {
            "sample": f"{c['id']}-r{i + 1}",
            "case": c["id"],
            "layer": c["layer"],
            "dimension": c["dimension"],
            "split": c["split"],
        }
        for c in selected
        for i in range(args.repeats)
    ]
    if ab:
        samples = [
            {
                "sample": f"{c['id']}-{arm}-r{i + 1}",
                "case": c["id"],
                "layer": c["layer"],
                "dimension": c["dimension"],
                "split": c["split"],
                "hint_arm": arm,
            }
            for i in range(args.repeats)
            for c in selected
            for arm in (("A", "B") if i % 2 == 0 else ("B", "A"))
        ]
    write(
        out / "manifest.json",
        {
            "schema_version": 1,
            "created_at": datetime.now(UTC).isoformat(),
            "source": source_fingerprint(),
            "catalog_sha256": digest(catalog()),
            "cases": selected,
            "samples": samples,
            "profile": args.profile,
            "python": sys.version,
            "concurrency": 1,
            "hint_ab": ab,
            "max_consecutive_execution_errors": args.max_consecutive_errors,
        },
    )
    by_id = {c["id"]: c for c in selected}
    consecutive_errors = 0
    for sample in samples:
        if args.layer == "frozen" and consecutive_errors >= args.max_consecutive_errors:
            mark_unassessed(
                out, f"Batch halted after {consecutive_errors} consecutive execution errors"
            )
            break
        case = by_id[sample["case"]]
        trial = out / sample["sample"]
        trial.mkdir()
        write(trial / "input.json", case)
        write(trial / "source.json", source_fingerprint())
        if args.layer == "protocol":
            command = [
                sys.executable,
                "-m",
                "pytest",
                *case.get("selectors", [case.get("selector")]),
                "-q",
                f"--junitxml={trial / 'pytest.xml'}",
            ]
            timeout = 120
        else:
            command = [
                sys.executable,
                "-m",
                "benchmarks.team_workflow.worker",
                "--input",
                str(trial / "input.json"),
                "--out",
                str(trial),
                "--profile",
                args.profile,
            ]
            timeout = case["budgets"]["wall_s"] + 60
            if ab:
                command.extend(["--hint-arm", sample["hint_arm"]])
        started = time.monotonic()
        result: dict[str, Any]
        with (trial / "execution.log").open("w") as log:
            process = subprocess.Popen(
                command, cwd=ROOT, stdout=log, stderr=log, start_new_session=True
            )
            try:
                returncode = process.wait(timeout=timeout)
                if args.layer == "protocol":
                    result = protocol_result(trial / "pytest.xml", returncode)
                else:
                    worker_file = trial / "worker.json"
                    worker = json.loads(worker_file.read_text()) if worker_file.exists() else {}
                    if returncode != 0:
                        worker = {"ok": False, "error": f"worker exited with code {returncode}"}
                    metrics = measure(trial)
                    write(trial / "metrics.json", metrics)
                    result = frozen_result(worker, metrics, case)
            except subprocess.TimeoutExpired:
                # Worker descendants must not keep making model calls after the outer budget.
                import signal

                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
                result = {"status": "error", "reason": "outer process deadline exceeded"}
            except (ValueError, OSError, KeyError) as exc:
                result = {"status": "error", "reason": f"{type(exc).__name__}: {exc}"}
            except BaseException:
                import signal

                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                raise
        if args.layer == "frozen" and not (trial / "metrics.json").exists():
            write(trial / "metrics.json", measure(trial))
        if case.get("tool_fixture") == "corpus_document_v1":
            from benchmarks.team_workflow.corpus_fixtures import measure_corpus

            write(trial / "corpus-metrics.json", measure_corpus(trial))
        result["elapsed_s"] = round(time.monotonic() - started, 3)
        write(trial / "result.json", result)
        consecutive_errors = consecutive_errors + 1 if result["status"] == "error" else 0
        print(f"{sample['sample']}: {result['status']} ({result['elapsed_s']}s)", flush=True)
        summarize(out)
    return 0 if summarize(out)["all_passed"] else 1


def apply_review(out: Path, sample: str, review_path: Path) -> None:
    manifest = json.loads((out / "manifest.json").read_text())
    record = next(s for s in manifest["samples"] if s["sample"] == sample)
    if record["layer"] != "frozen":
        raise ValueError("protocol verdicts cannot be overridden by a human review")
    trial = out / sample
    result = json.loads((trial / "result.json").read_text())
    worker = json.loads((trial / "worker.json").read_text())
    case = next(c for c in manifest["cases"] if c["id"] == record["case"])
    review = json.loads(review_path.read_text())
    if review.get("review_type") not in {"human", "model"}:
        raise ValueError("review_type must explicitly identify human or model review")
    scores = review.get("criteria", [])
    if review.get("worker_sha256") != digest(worker) or review.get("case_sha256") != digest(case):
        raise ValueError("review must bind this exact worker output and case")
    if not str(review.get("reviewer", "")).strip() or len(scores) != len(case["rubric"]):
        raise ValueError("reviewer and one verdict per rubric item required")
    if any(
        s.get("verdict") not in {"pass", "fail", "unassessed"}
        or not str(s.get("evidence", "")).strip()
        for s in scores
    ):
        raise ValueError("each criterion needs a verdict and artifact-grounded explanation")
    if result["status"] == "error" or result.get("hard_failures"):
        raise ValueError("human review cannot override execution errors or hard failures")
    review_name = f"review-{len(list(trial.glob('review-*.json'))):03d}.json"
    write(trial / review_name, review)
    verdict = (
        "fail"
        if any(s["verdict"] == "fail" for s in scores)
        else "unassessed"
        if any(s["verdict"] == "unassessed" for s in scores)
        else "pass"
    )
    result["status"] = verdict if review["review_type"] == "human" else "needs_review"
    result["diagnostic_verdict"] = verdict
    result["review_type"] = review["review_type"]
    result["semantic_review_required"] = review["review_type"] != "human"
    result["reviewer"] = review["reviewer"]
    result["review_file"] = review_name
    write(trial / "result.json", result)
    summarize(out)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)
    execution = subs.add_parser("run")
    execution.add_argument("--layer", choices=["protocol", "frozen"], required=True)
    execution.add_argument("--case", action="append")
    execution.add_argument("--repeats", type=int, default=1)
    execution.add_argument("--profile", default="default")
    execution.add_argument("--hint-ab", action="store_true")
    execution.add_argument("--max-consecutive-errors", type=int, default=2)
    execution.add_argument("--out", type=Path, required=True)
    report = subs.add_parser("report")
    report.add_argument("--out", type=Path, required=True)
    report.add_argument("--rescore", action="store_true")
    review = subs.add_parser("review")
    review.add_argument("--out", type=Path, required=True)
    review.add_argument("--sample", required=True)
    review.add_argument("--file", type=Path, required=True)
    inspect = subs.add_parser("inspect")
    inspect.add_argument("--run", type=Path, required=True)
    inspect.add_argument("--out", type=Path, required=True)
    comparison = subs.add_parser("compare")
    comparison.add_argument("--before", type=Path, required=True)
    comparison.add_argument("--after", type=Path, required=True)
    comparison.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "run":
        raise SystemExit(run(args))
    if args.command == "report":
        if args.rescore:
            rescore(args.out)
        print(json.dumps(summarize(args.out)["states"]))
    elif args.command == "review":
        apply_review(args.out, args.sample, args.file)
    elif args.command == "compare":
        if args.out.exists():
            raise ValueError("refusing to overwrite comparison")
        write(args.out, compare(args.before, args.after))
    else:
        if args.out.exists():
            raise ValueError("refusing to overwrite existing metrics")
        write(args.out, measure(args.run))


if __name__ == "__main__":
    main()
