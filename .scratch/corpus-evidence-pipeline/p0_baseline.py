"""Offline P0 evidence capture. No production writes, model calls or DB connection.

Generated audit files are write-once; verify requires an independently pinned SHA.
This is an execution-baseline guard, not a semantic acceptance scorer.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.abc
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
ROOTS = (
    "frontier_agent",
    "workflows",
    "apodex",
    "plugins",
    "server",
    "web",
    "config",
    "deploy",
    "docker",
    "scripts",
    "tools",
    "tests",
)
SUFFIXES = {
    ".py",
    ".yaml",
    ".yml",
    ".toml",
    ".json",
    ".sql",
    ".sh",
    ".bat",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".css",
    ".html",
    ".j2",
    ".jinja",
    ".md",
}
PRUNE = {"node_modules", ".venv", "__pycache__", ".git", ".next", "dist", "build"}
PLATFORM_TESTS = [
    "tests/test_stateful_workflow.py",
    "tests/test_agent_team_workflow.py",
    "tests/test_tool_registry.py",
    "tests/test_profile_literal_validation.py",
    "apodex/tests/test_profiles.py",
]
ISOLATION_TESTS = [
    "tests/test_corpus_claims_interface.py",
    "tests/test_corpus_ingest.py",
    "tests/test_corpus_search.py",
    "tests/test_corpus_evidence_pipeline.py",
    "tests/test_corpus_financial_review.py",
    "tests/test_corpus_semantic_gates.py",
    "tests/test_data_coverage.py",
    "tests/test_market_golden.py",
    "tests/test_market_gate.py",
    "tests/test_position_sizing.py",
    "tests/test_strategy_lint.py",
]
REPORTS = (
    "report-09b119120285666aac93fcb41ce1f8c0ebe3c4bb563f50a964bdc30b0b301b40.json",
    "report-46caccfc1c7d23ef3858a8a501560c07b250888b0b3f189fdff75d8ba6bc6b4b.json",
)
DEV_IDS = {
    "dev-company-report",
    "dev-industry-qa-report",
    "dev-personal-trade-review",
    "dev-expert-call-copper-foil",
}
DEV_SOURCES = {
    "dev-company-report": "data/corpus/2026-08-16_2026.08.16-华创证券-欧阳予-田晨曦-张慧-公司研究-业绩点评-贵州茅台-600519-报表实质扎实-经营底部已过-贵州茅台-600519-2026年中报点评-e034bdac.pdf",
    "dev-industry-qa-report": "data/corpus/2026-08-13_2026.08.13-长江证券-国内研报-长江证券-化工专题-景气投资-十问十答-7463f4d0.pdf",
    "dev-personal-trade-review": "data/corpus/2026-09-03_James-Bulltard_9326 复盘.pdf",
    "dev-expert-call-copper-foil": "data/corpus/5月：锂电铜箔和电子铜箔.md",
}


def encoded(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_path(root: Path, relative: str) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError("unsafe manifest path")
    result = (root / candidate).resolve()
    if not result.is_relative_to(root.resolve()):
        raise ValueError("manifest path escaped workspace")
    return result


def inventory(root: Path) -> dict[str, str]:
    files: dict[str, str] = {}
    for name in ROOTS:
        for directory, dirs, names in os.walk(root / name):
            dirs[:] = sorted(d for d in dirs if d not in PRUNE and not d.startswith("."))
            for filename in sorted(names):
                p = Path(directory) / filename
                if filename.startswith(".env") or p.suffix not in SUFFIXES:
                    continue
                rel = p.relative_to(root).as_posix()
                files[rel] = sha(safe_path(root, rel).read_bytes())
    for name in ("pyproject.toml", "uv.lock", "pyrightconfig.json", "AGENTS.md"):
        p = root / name
        if p.is_file():
            files[name] = sha(p.read_bytes())
    return dict(sorted(files.items()))


def service_public_fingerprint(text: str) -> str:
    """Audit reference only. P0 still protects the entire service file byte-for-byte."""
    tree = ast.parse(text)
    owner = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "CorpusService")
    owner.body = [
        n
        for n in owner.body
        if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        or n.name != "understand_material"
    ]
    return sha(ast.dump(tree, include_attributes=False).encode())


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=ROOT)


def assets() -> tuple[dict[str, str], list[dict[str, Any]]]:
    """Hash gold as opaque bytes; parse only development reports and material runs."""
    found: dict[str, str] = {}
    summaries: list[dict[str, Any]] = []
    from plugins.corpus.material_semantics import MaterialRun

    def bind(p: Path) -> None:
        rel = p.resolve().relative_to(ROOT).as_posix()
        found[rel] = sha(safe_path(ROOT, rel).read_bytes())

    for p in sorted(HERE.glob("r2-*.json")):
        bind(p)
    for p in sorted(HERE.glob("verify_*.py")):
        bind(p)
    for name in (
        "run_material_development.py",
        "replay_material_raw_audit.py",
        "p0_baseline.py",
        "test_p0_baseline.py",
    ):
        bind(HERE / name)
    for p in (HERE / "p0-fixtures").glob("*"):
        bind(p)
    for name in ("r1_material_gold_v1_20260913.json", "r2_material_micro_gold_v1_20260913.json"):
        bind(ROOT / "data/corpus/.audit" / name)
    for name in REPORTS:
        path = HERE / "material-semantics-runs" / name
        bind(path)
        report = json.loads(path.read_bytes())
        if report["split"] != "development":
            raise ValueError("non-development asset rejected")
        if {s["sample_id"] for s in report["samples"]} != DEV_IDS:
            raise ValueError("development sample inventory mismatch")
        rows = report["raw_audits"]
        if report["model_calls"] != len(rows):
            raise ValueError("incomplete raw response inventory")
        for row in rows:
            if row["sample_id"] not in DEV_IDS:
                raise ValueError("raw response outside development")
            raw = Path(row["path"])
            bind(raw)
            if found[raw.resolve().relative_to(ROOT).as_posix()] != row["response_sha256"]:
                raise ValueError("raw response hash mismatch")
        sample_refs = []
        for sample in report["samples"]:
            material = path.parent / (sample["material_run_id"] + ".json")
            bind(material)
            saved = MaterialRun.model_validate_json(material.read_bytes())
            saved.verify_identity()
            if saved.run_id != sample["material_run_id"]:
                raise ValueError("material artifact identity mismatch")
            source = safe_path(ROOT, DEV_SOURCES[sample["sample_id"]])
            bind(source)
            if sha(source.read_bytes())[:16] != sample["source_rev"]:
                raise ValueError("development source changed")
            sample_refs.append(
                {
                    **{k: sample[k] for k in ("sample_id", "source_rev", "material_run_id")},
                    "source_path": DEV_SOURCES[sample["sample_id"]],
                }
            )
        summaries.append({"report": name, "raw_responses": len(rows), "samples": sample_refs})
    return dict(sorted(found.items())), summaries


def environment() -> dict[str, Any]:
    packages = {}
    for name in ("pytest", "pydantic", "PyMuPDF", "python-docx", "psycopg", "jieba", "httpx"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = "not-installed"
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "packages": packages,
    }


def freeze() -> Path:
    source_files = inventory(ROOT)
    bound_assets, asset_summary = assets()
    # Capture only code diffs, never configuration/env/credentials or source documents.
    diff_paths = [n for n in source_files if n.endswith(".py")]
    patch = git("diff", "--no-ext-diff", "--binary", "HEAD", "--", *diff_paths)
    protected = {
        "phase": "P0-strict",
        "exceptions_active": [],
        "inventory_roots": ROOTS,
        "file_sha256": source_files,
        "future_service_public_ast_sha256": service_public_fingerprint(
            (ROOT / "plugins/corpus/service.py").read_text()
        ),
        "note": "No exceptions active; P1 must separately approve any R2/service allowlist.",
    }
    manifest = {
        "schema": "r2-p0-baseline-1",
        "head": git("rev-parse", "HEAD").decode().strip(),
        "environment": environment(),
        "protected_paths_sha256": sha(encoded(protected)),
        "asset_sha256": bound_assets,
        "development_assets": asset_summary,
        "workspace_code_diff_sha256": sha(patch),
        "untracked_protected_paths": sorted(
            set(git("ls-files", "--others", "--exclude-standard").decode().splitlines())
            & set(source_files)
        ),
        "scope": {
            "real_model_calls": 0,
            "real_market_calls": 0,
            "production_db_access": False,
            "holdout_source_access": False,
            "gold_access": "opaque file hashes only",
        },
        "pg_preflight": {
            "local_initdb": bool(shutil.which("initdb"))
            or bool(list(Path("/usr/lib/postgresql").glob("*/bin/initdb"))),
            "docker_executable": bool(shutil.which("docker")),
            "isolated_instance_verified": False,
            "required": ["zhparser", "vector", "pg_trgm", "zhcfg"],
            "status": "not_verified_no_database_contact",
        },
    }
    data = encoded(manifest)
    out = HERE / "p0-baselines" / ("baseline-" + sha(data)[:16])
    out.mkdir(parents=True, exist_ok=False, mode=0o700)
    write_once(out / "protected-paths.json", encoded(protected))
    write_once(out / "workspace-code.patch", patch)
    write_once(out / "baseline-manifest.json", data)
    print(
        json.dumps(
            {
                "manifest": str(out / "baseline-manifest.json"),
                "sha256": sha(data),
                "protected_files": len(source_files),
                "assets": len(bound_assets),
            }
        )
    )
    return out


def write_once(path: Path, data: bytes) -> None:
    with path.open("xb") as handle:
        os.chmod(path, 0o600)
        handle.write(data)


def verify_files(root: Path, expected: dict[str, str]) -> list[str]:
    failures = []
    for name, digest in expected.items():
        p = safe_path(root, name)
        if not p.is_file() or sha(p.read_bytes()) != digest:
            failures.append(name)
    return failures


def verify(path: Path, trusted_sha: str) -> dict[str, Any]:
    data = path.read_bytes()
    if sha(data) != trusted_sha:
        raise ValueError("baseline manifest differs from externally pinned SHA")
    manifest = json.loads(data)
    if manifest.get("schema") != "r2-p0-baseline-1":
        raise ValueError("unknown manifest schema")
    guard_data = (path.parent / "protected-paths.json").read_bytes()
    if sha(guard_data) != manifest["protected_paths_sha256"]:
        raise ValueError("protected-paths manifest changed")
    expected = json.loads(guard_data)["file_sha256"]
    actual = inventory(ROOT)
    failures = sorted(set(expected) ^ set(actual))
    failures += [n for n in expected.keys() & actual.keys() if expected[n] != actual[n]]
    failures += verify_files(ROOT, manifest["asset_sha256"])
    if git("rev-parse", "HEAD").decode().strip() != manifest["head"]:
        failures.append("git HEAD")
    if environment() != manifest["environment"]:
        failures.append("runtime environment")
    if (
        sha((path.parent / "workspace-code.patch").read_bytes())
        != manifest["workspace_code_diff_sha256"]
    ):
        failures.append("workspace-code.patch")
    if failures:
        raise ValueError("baseline drift: " + ", ".join(failures))
    return manifest


def block_external() -> dict[str, int]:
    os.environ["CORPUS_DSN"] = "postgresql://p0:p0@127.0.0.1:1/p0_forbidden?connect_timeout=1"
    counters = {"blocked_socket_connects": 0}

    def audit(event: str, args: Any) -> None:
        if event == "socket.connect":
            counters["blocked_socket_connects"] += 1
            raise OSError("P0 offline guard: external connections prohibited")

    sys.addaudithook(audit)
    # psycopg uses libpq rather than Python socket; stop before entering native code.
    import psycopg

    def reject_pg(*args: Any, **kwargs: Any) -> None:
        raise psycopg.OperationalError("P0 offline guard: PostgreSQL disabled")

    psycopg.connect = reject_pg  # type: ignore[assignment]
    return counters


class BlockR2(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname: str, path: Any = None, target: Any = None) -> None:
        if fullname == "plugins.corpus.material_semantics":
            raise ImportError("P0 intentionally disables R2")


def snapshot() -> dict[str, Any]:
    """Exercise existing public interfaces with synthetic source and fake provider."""
    from contextlib import redirect_stdout
    from dataclasses import asdict
    from io import StringIO
    from unittest.mock import Mock, patch

    from plugins.corpus.evidence_pipeline import EvidenceRun
    from plugins.corpus.fetch import fetch_block
    from plugins.corpus.index import build_index, search, tokenize
    from plugins.corpus.ingest import connect, init_db, parse_document, upsert_document
    from plugins.corpus.service import CorpusService, _main

    source = HERE / "p0-fixtures/2026-08-16_600519.SH.md"
    svc = CorpusService("postgresql://unused")
    svc._connect = Mock(side_effect=AssertionError("database must not be used"))
    stored: dict[str, str] = {}

    def save(run: Any) -> str:
        run.verify_identity()
        stored[run.run_id] = run.model_dump_json()
        return run.run_id

    def load(run_id: str) -> Any:
        run = EvidenceRun.model_validate_json(stored[run_id])
        run.verify_identity()
        return run

    def response(prompt: str) -> str:
        return json.dumps(
            [
                {
                    "claim_text": f"{p} 营业收入{v}元",
                    "evidence_quote": f"{p} 营业收入{v}元",
                    "scope": "company",
                    "subject": "600519.SH",
                    "metric": "营业收入",
                    "value_text": f"{v}元",
                    "period_raw": p,
                    "kind": k,
                }
                for p, v, k in [("2025A", "100", "fact"), ("2026E", "120", "forecast")]
            ],
            ensure_ascii=False,
        )

    svc.save_evidence_run, svc.load_evidence_run = save, load
    run = svc.extract_claims(source, llm=response, model="p0-fake", max_prose_calls=1)
    projection = svc.claims_of(run_id=run.run_id, purpose="calculate")
    ids = tuple(row["fact_id"] for row in reversed(projection["items"]))
    calculation = svc.derive_claims(run_id=run.run_id, formula="revenue_growth", input_ids=ids)
    if calculation.value != 20:
        raise AssertionError("known financial control failed")
    deferred = svc.extract_claims(source, max_prose_calls=0, persist=False)
    errors = {}
    for name, action in {
        "wrong_revision": lambda: svc.claims_of(run_id="missing"),
        "reversed_period": lambda: svc.derive_claims(
            run_id=run.run_id, formula="revenue_growth", input_ids=tuple(reversed(ids))
        ),
    }.items():
        try:
            action()
        except (KeyError, ValueError) as exc:
            errors[name] = type(exc).__name__
        else:
            raise AssertionError("negative control accepted: " + name)
    output = StringIO()
    with (
        patch("plugins.corpus.service.get_service", return_value=svc),
        patch.object(
            sys, "argv", ["corpus", "claims", "--run-id", run.run_id, "--purpose", "calculate"]
        ),
        redirect_stdout(output),
    ):
        exit_code = _main()
    cli_result = json.loads(output.getvalue())
    with tempfile.TemporaryDirectory(prefix="r2-p0-") as directory:
        conn = connect(Path(directory) / "fixture.sqlite")
        try:
            init_db(conn)
            parsed = parse_document(source)
            inserted = [upsert_document(conn, parsed), upsert_document(conn, parsed)]
            build_index(conn)
            hits = search(conn, "营业收入", limit=5)
            retrieved = [asdict(fetch_block(conn, h.doc_id, h.locator)) for h in hits]
            search_result = [asdict(h) for h in hits]
        finally:
            conn.close()
    return {
        "fixture_sha256": sha(source.read_bytes()),
        "evidence_run": run.model_dump(mode="json"),
        "projection": projection,
        "calculation": calculation.model_dump(mode="json"),
        "packets": [svc.fetch_evidence(run.run_id, p.packet_id) for p in run.document.packets],
        "deferred": deferred.summary(),
        "rejected": errors,
        "cli": {"exit_code": exit_code, "json": cli_result},
        "legacy_sqlite": {
            "inserted": inserted,
            "hits": search_result,
            "fetch": retrieved,
            "tokens": tokenize("营业收入100元，增长20%"),
        },
        "market": market_snapshot(),
        "limitations": [
            "PG persistence replaced by in-memory store",
            "provider is fake",
            "SQLite search is not PostgreSQL/zhparser acceptance",
        ],
    }


def market_snapshot() -> dict[str, Any]:
    """Reuse the existing fixed HTTP fixture with real transport/render/resolver."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "p0_fixed_market_fixture", ROOT / "tests/test_market_golden.py"
    )
    if spec is None or spec.loader is None:
        raise ValueError("market fixture unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    class TempFactory:
        def __init__(self, directory: str) -> None:
            self.directory = Path(directory)

        def mktemp(self, name: str) -> Path:
            return self.directory

    with tempfile.TemporaryDirectory(prefix="r2-p0-market-") as directory:
        trace, quote, history, financials = module.traced.__wrapped__(TempFactory(directory))
        for row in quote["items"]:
            row.pop("age", None)  # Display-relative age only; retain all source times.
        text = module.resolve_market_source("ths:600519.SH:rid-snap", trace)
        if not text or "1290.88" not in text:
            raise AssertionError("market positive trace control failed")
        return {
            "quote": quote,
            "history": history,
            "financials": financials,
            "resolved_text": text,
            "excluded_fields": ["quote.items[].age (relative display age, not source as_of)"],
            "limitations": [
                "fixed HTTP fixture, not a live THS call",
                "legacy resolver is not request-ID strict",
            ],
        }


def suite(name: str, output: Path) -> int:
    import pytest

    if name == "isolation":
        sys.meta_path.insert(0, BlockR2())
        try:
            __import__("plugins.corpus.material_semantics")
        except ImportError:
            pass
        else:
            raise AssertionError("R2 poison control ineffective")
        selected = ISOLATION_TESTS
    elif name == "guard":
        selected = [str((HERE / "test_p0_baseline.py").relative_to(ROOT))]
    elif name == "platform":
        selected = PLATFORM_TESTS
    else:
        prefixes = (
            "test_corpus_",
            "test_market_",
            "test_data_coverage",
            "test_position_sizing",
            "test_strategy_lint",
        )
        selected = sorted(
            str(p.relative_to(ROOT))
            for p in (ROOT / "tests").glob("test_*.py")
            if p.name.startswith(prefixes) and p.name != "test_corpus_tables.py"
        )
    records: list[dict[str, Any]] = []

    class Recorder:
        def pytest_runtest_logreport(self, report: Any) -> None:
            if report.when == "call" or report.failed or report.skipped:
                row = {"nodeid": report.nodeid, "when": report.when, "outcome": report.outcome}
                if report.skipped:
                    row["reason"] = (
                        str(report.longrepr[-1])
                        if isinstance(report.longrepr, tuple)
                        else "skipped"
                    )
                records.append(row)

    rc = pytest.main(
        [
            "-q",
            *selected,
            "--tb=short",
            "-k",
            "not supplied_source_is_classified_without_ingestion",
        ],
        plugins=[Recorder()],
    )
    if name == "isolation" and "plugins.corpus.material_semantics" in sys.modules:
        raise AssertionError("R2 was loaded during isolation check")
    write_once(
        output,
        encoded(
            {
                "suite": name,
                "exit_code": int(rc),
                "files": selected,
                "records": records,
                "db": "disabled before native driver",
                "real_corpus_tests": "excluded",
            }
        ),
    )
    return int(rc)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["freeze", "verify", "snapshot", "suite"])
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--sha256")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--suite", choices=["core", "platform", "isolation", "guard"])
    parser.add_argument("--block-r2", action="store_true")
    args = parser.parse_args()
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    if args.action == "freeze":
        freeze()
        return 0
    if not args.manifest or not args.sha256:
        parser.error("an existing manifest and independent --sha256 are required")
    verify(args.manifest, args.sha256)
    if args.action == "verify":
        print("PASS: protected code, test inventory, assets, HEAD and environment unchanged")
        return 0
    if not args.out or not args.out.resolve().is_relative_to(args.manifest.parent.resolve()):
        parser.error("output must be new and inside the baseline directory")
    if args.out.exists():
        parser.error("refusing to overwrite existing result")
    block_external()
    if args.action == "suite":
        if not args.suite:
            parser.error("--suite required")
        result = suite(args.suite, args.out)
    else:
        if args.block_r2:
            sys.meta_path.insert(0, BlockR2())
        value = snapshot()
        write_once(args.out, encoded(value))
        print(json.dumps({"snapshot_sha256": sha(encoded(value)), "output": str(args.out)}))
        result = 0
    verify(args.manifest, args.sha256)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
