"""Generate candidates and freeze only this bounded remediation, never approvals."""

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1]
ROOT = BASE.parents[2]
FREEZES = BASE / "freezes"
ENV = {
    "PATH": "/usr/bin:/bin",
    "LANG": "C.UTF-8",
    "PYTHONPATH": str(ROOT),
    "PYTHONDONTWRITEBYTECODE": "1",
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(name, args):
    result = subprocess.run(
        [str(ROOT / ".venv/bin/python"), "-B", *map(str, args)],
        cwd=ROOT,
        env=ENV,
        text=True,
        capture_output=True,
        check=False,
    )
    with (HERE / f"{name}.txt").open("x", encoding="utf-8") as output:
        output.write(
            f"$ python -B {' '.join(map(str, args))}\n{result.stdout}{result.stderr}\nexit={result.returncode}\n"
        )
    print(name, result.returncode, result.stdout[-1300:])
    if result.returncode:
        raise SystemExit(result.returncode)


def main():
    action = sys.argv[1]
    assert action in {"prepare", "freeze", "verify"}
    if action == "verify":
        run("freeze-validation", [FREEZES / "validate_i0c_freeze.py"])
        return
    assert not (FREEZES / "i0c-r25.json").exists(), "r25 is write-once"
    for filename in ("evidence-targets-decisions.json", "evidence-targets-approved.json"):
        assert not (BASE / "i3-2" / filename).exists(), "real decisions require a separate review"
    if action == "prepare":
        for name in ("i3s2_evidence_targets", "i3s2_apply_decisions", "i3s2_verify_candidates"):
            run(name, [BASE / (name + ".py")])
        run("contracts", [HERE / "run_checks.py", "green"])
        return
    candidates = json.loads((BASE / "i3-2/evidence-targets-candidates.json").read_text())
    verification = json.loads((BASE / "i3-2/evidence-targets-verification.json").read_text())
    report = json.loads((BASE / "i3-2/approval-report.json").read_text())
    assert candidates["rule_rev"] == "evidence-mapping-6"
    assert report["stage"] == "no_decisions" and report["ready"] is False
    assert verification["self_consistency"]["failed"] == 0
    assert verification["regression_probes"]["failed"] == 0
    assert report["applier_sha256"] == digest(BASE / "i3s2_apply_decisions.py")
    assert candidates["generator"]["sha256"] == digest(BASE / "i3s2_evidence_targets.py")
    for key in ("source_gold", "query_gold"):
        asset = candidates["inputs"][key]
        assert digest(ROOT / asset["path"]) == asset["sha256"]
    # Rerun tests at freeze time; historical green logs are not sufficient.
    run("pre-freeze-contracts", [HERE / "run_checks.py", "green-final"])
    parent = json.loads((FREEZES / "i0c-r24.json").read_text())
    prefix = str(BASE.relative_to(ROOT))
    groups = {
        "i3_2_tooling": [
            str(BASE / f)
            for f in (
                "i3s2_apply_decisions.py",
                "i3s2_evidence_targets.py",
                "i3s2_verify_candidates.py",
            )
        ],
        "i3_2_assets": [
            str(BASE / "i3-2" / f)
            for f in (
                "evidence-targets-candidates.json",
                "evidence-targets-adjudication.md",
                "evidence-targets-review.md",
                "evidence-targets-verification.json",
                "approval-report.json",
            )
        ],
        "docs": [
            str(ROOT / "docs/plan" / f)
            for f in ("claims-market-closed-loop-plan.md", "corpus-ingestion-rebuild-tasks.md")
        ],
        "freeze_validator": [str(FREEZES / "validate_i0c_freeze.py")],
        "i3_2_regressions": [str(p) for p in HERE.iterdir() if p.is_file()],
        "i3_2_archive": [],
    }
    for group in ("i3_2_tooling", "i3_2_assets", "docs", "freeze_validator"):
        for relative, expected in parent["binding"][group].items():
            archived = HERE / "before-r24" / relative
            assert digest(archived) == expected, relative
            groups["i3_2_archive"].append(str(archived))
    binding = {
        group: {str(Path(p).relative_to(ROOT)): digest(Path(p)) for p in paths}
        for group, paths in groups.items()
    }
    manifest_path = FREEZES / "freeze-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    parents = {s["snapshot_id"]: s for s in manifest["snapshots"]}
    assert "i0c-r25" not in parents
    assert parents["i0c-r24"]["sha256"] == digest(FREEZES / "i0c-r24.json")
    snapshot = {
        "snapshot_id": "i0c-r25",
        "revision": "r25",
        "phase": "i0c",
        "task": "I3-2 approval contract B1-B5 remediation; candidates only, no human sign-off",
        "binding": binding,
        "corrections": {
            "B1": "source-specific binding and projection coverage",
            "B2": "answer constraints isolated; checked projection",
            "B3": "no residual waiver; human lexical mapping bound to exact quote",
            "B4": "quote-only adequacy, explicit reviewed hint reselection",
            "B5": "unique known identities and mandatory negative reasons",
            "I3-5": "zero-model constraint transport tests; answer semantics not_run",
        },
        "created_at": datetime.now(timezone.utc).isoformat(),
        "parent_snapshot": {
            "snapshot_id": "i0c-r24",
            "path": f"{prefix}/freezes/i0c-r24.json",
            "sha256": digest(FREEZES / "i0c-r24.json"),
        },
        "notes": [
            "No source/query gold, scorer, public modules, guard, database or model changes.",
            "Human approval remains no_decisions; I3-2/M6 not released.",
        ],
    }
    target = FREEZES / "i0c-r25.json"
    with target.open("x", encoding="utf-8") as output:
        json.dump(snapshot, output, ensure_ascii=False, indent=2)
        output.write("\n")
    manifest["snapshots"].append(
        {
            "snapshot_id": "i0c-r25",
            "file": target.name,
            "sha256": digest(target),
            "parent_snapshot_id": "i0c-r24",
            "created_at": snapshot["created_at"],
        }
    )
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print("r25 candidate remediation frozen; approval remains blocked.")


if __name__ == "__main__":
    main()
