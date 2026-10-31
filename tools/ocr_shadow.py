"""Explicit, default-off OCR sidecar. Never imports an ingestion or database API."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RELEASE = ROOT / "config/ocr-shadow-release.json"
OUTPUT_ROOT = ROOT / "data/ocr-shadow-runs"
PAGE_TIMEOUT = 120
MAX_INPUT_BYTES = 100 * 1024 * 1024


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    with path.open("x", encoding="utf8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)


def validate_documents(documents: object) -> list[dict[str, Any]]:
    if not isinstance(documents, list) or not 1 <= len(documents) <= 6:
        raise ValueError("Select one to six documents explicitly")
    selected = []
    count = 0
    seen = set()
    for doc in documents:
        path = Path(doc["path"]).resolve(strict=True)
        if not path.is_file() or path.suffix.lower() != ".pdf":
            raise ValueError("Inputs must be PDF files")
        if path.stat().st_size > MAX_INPUT_BYTES:
            raise ValueError("100 MiB input limit exceeded")
        if path in seen:
            raise ValueError("Duplicate document")
        seen.add(path)
        pages = doc["pages"]
        if not isinstance(pages, list) or not pages:
            raise ValueError("Explicit page list required")
        if any(type(p) is not int or p < 1 for p in pages) or len(set(pages)) != len(pages):
            raise ValueError("Pages must be distinct positive integers")
        sha = digest(path)
        if sha != doc["sha256"]:
            raise ValueError("Source hash mismatch")
        count += len(pages)
        selected.append({"path": str(path), "sha256": sha, "pages": pages})
    if count > 6:
        raise ValueError("At most six explicitly selected pages per run")
    return selected


def verify_release() -> dict[str, Any]:
    release = json.loads(RELEASE.read_text(encoding="utf8"))
    for relative, sha in release["files"].items():
        path = (ROOT / relative).resolve(strict=True)
        if not path.is_relative_to(ROOT) or digest(path) != sha:
            raise ValueError(f"Frozen source changed: {relative}")
    observed = subprocess.run(
        ["docker", "image", "inspect", release["image"], "--format", "{{.Id}}"],
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    )
    if observed.stdout.strip() != release["image"]:
        raise ValueError("OCR image identity mismatch")
    return release


def container_command(
    name: str, frozen: Path, inputs: Path, out: Path, image: str, pdf: str, page: int
) -> list[str]:
    command = [
        "docker",
        "run",
        "--rm",
        "--pull",
        "never",
        "--name",
        name,
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        "--cpus",
        "2",
        "--memory",
        "4g",
        "--pids-limit",
        "128",
        "--tmpfs",
        "/tmp:rw,size=256m",
        "--tmpfs",
        "/workspace:rw,size=256m",
        "-e",
        "PYTHONDONTWRITEBYTECODE=1",
        "-e",
        "OMP_NUM_THREADS=1",
    ]
    for source, destination, readonly in (
        (frozen, "/frozen", True),
        (inputs, "/inputs", True),
        (out, "/out", False),
    ):
        command += [
            "--mount",
            f"type=bind,source={source},target={destination}" + (",readonly" if readonly else ""),
        ]
    return [
        *command,
        image,
        "/opt/rapid/bin/python",
        "/frozen/worker.py",
        f"/inputs/{pdf}",
        str(page),
    ]


def execute_page(command: list[str], out: Path, name: str) -> dict[str, Any]:
    try:
        with (out / "worker.log").open("xb") as log:
            subprocess.run(
                command, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=PAGE_TIMEOUT
            )
        result = json.loads((out / "result.json").read_text(encoding="utf8"))
        if (
            result.get("eligible_for_ingestion") is not False
            or result.get("human_review") != "pending"
        ):
            raise ValueError("Worker violated review-only contract")
        return result
    except (subprocess.SubprocessError, OSError, ValueError) as exc:
        # Killing docker's client alone does not terminate the container.
        # The name is generated for this call, never supplied by a document.
        cleanup_failed = False
        try:
            cleanup = subprocess.run(
                ["docker", "rm", "-f", name], capture_output=True, timeout=20, check=False
            )
            cleanup_failed = cleanup.returncode != 0
        except (OSError, subprocess.SubprocessError):
            cleanup_failed = True
        result = {
            "status": "timeout" if isinstance(exc, subprocess.TimeoutExpired) else "error",
            "error_type": type(exc).__name__,
            "needs_review": True,
            "human_review": "pending",
            "eligible_for_ingestion": False,
            "production_ingestion": False,
            "container_cleanup_failed": cleanup_failed,
        }
        write_json(out / "host-failure.json", result)
        return result


def render_review(run: Path, records: list[dict[str, Any]]) -> None:
    sections = []
    for row in records:
        key = row["id"]
        folder = run / "pages" / key
        links = []
        for name in (
            "source.png",
            "candidate.txt",
            "baseline-auto.txt",
            "baseline-text.txt",
            "baseline-image.txt",
            "result.json",
            "host-failure.json",
            "reference-0.txt",
            "reference-90.txt",
            "reference-180.txt",
            "reference-270.txt",
        ):
            if (folder / name).is_file():
                links.append(f'<a href="pages/{key}/{name}">{name}</a>')
        preview = (
            f'<img src="pages/{key}/source.png" alt="原页">'
            if (folder / "source.png").exists()
            else "源页预览未生成"
        )
        candidate = (
            (folder / "candidate.txt").read_text(encoding="utf8")
            if (folder / "candidate.txt").exists()
            else "未产生可用正文"
        )
        sections.append(
            f"<section><h2>{html.escape(row['source_name'])} · 第 {row['page']} 页</h2><p>{row['status']} · 人工复核待处理 · 禁止自动入库</p><p>{' · '.join(links)}</p><div>{preview}<pre>{html.escape(candidate)}</pre></div></section>"
        )
    page = (
        """<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>OCR 工程旁路</title><style>body{font:16px/1.6 system-ui;margin:24px;background:#f5f5f2}section{background:white;padding:20px;margin:24px 0}section div{display:grid;grid-template-columns:1fr 1fr;gap:20px}img{width:100%}pre{white-space:pre-wrap;overflow-wrap:anywhere}a{color:#245b72}@media(max-width:850px){section div{display:block}}</style><h1>OCR 工程旁路 · 待人工复核</h1><p>默认关闭的独立入口。原生重排/覆盖检查与整页方向 OCR 已接线。方向未知只保存候选参考；candidate 保留原生文字，不表示图片已读完。所有页禁止自动入库。</p><p><a href="summary.json">运行摘要</a> · <a href="review.json">人工复核模板</a> · <a href="manifest.json">版本与输入</a></p>"""
        + "".join(sections)
        + "</html>"
    )
    (run / "review.html").write_text(page, encoding="utf8")


def run_batch(documents: list[dict[str, Any]], release: dict[str, Any]) -> Path:
    import fcntl

    if OUTPUT_ROOT.is_symlink():
        raise ValueError("Output root must not be a symlink")
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    if OUTPUT_ROOT.resolve() != ROOT / "data/ocr-shadow-runs":
        raise ValueError("Output root escapes the independent lane")
    with (OUTPUT_ROOT / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        run = OUTPUT_ROOT / uuid.uuid4().hex
        run.mkdir()
        frozen, inputs = run / "frozen", run / "inputs"
        frozen.mkdir()
        inputs.mkdir()
        for destination, source in release["bundle"].items():
            target = frozen / destination
            shutil.copyfile(ROOT / source, target)
            if digest(target) != release["files"][source]:
                raise ValueError("Source changed while staging")
        reader = "\n\n\n".join(
            (frozen / name).read_text(encoding="utf8") for name in release["reader_parts"]
        )
        (frozen / "reader.py").write_text(
            reader + '\n\nif __name__ == "__main__":\n    main()\n', encoding="utf8"
        )
        for i, doc in enumerate(documents):
            staged = inputs / f"doc{i}.pdf"
            shutil.copyfile(doc["path"], staged)
            if digest(staged) != doc["sha256"]:
                raise ValueError("Input changed while staging")
        write_json(
            run / "manifest.json",
            {"release": release, "documents": documents, "production_ingestion": False},
        )
        records = []
        for i, doc in enumerate(documents):
            for page in doc["pages"]:
                key = f"doc{i}-p{page}"
                out = run / "pages" / key
                out.mkdir(parents=True)
                name = f"frontier-ocr-shadow-{uuid.uuid4().hex}"
                command = container_command(
                    name, frozen, inputs, out, release["image"], f"doc{i}.pdf", page
                )
                result = execute_page(command, out, name)
                row = {
                    "id": key,
                    "source_name": Path(doc["path"]).name,
                    "source_sha256": doc["sha256"],
                    "page": page,
                    "status": result["status"],
                    "human_review": "pending",
                    "eligible_for_ingestion": False,
                }
                records.append(row)
                print(json.dumps(row, ensure_ascii=False), flush=True)
        incomplete = any(
            r["status"] in {"error", "timeout", "unavailable", "empty", "fallback"} for r in records
        )
        write_json(
            run / "summary.json",
            {
                "status": "incomplete" if incomplete else "needs_review",
                "records": records,
                "production_ingestion": False,
            },
        )
        write_json(
            run / "review.json",
            {
                "reviewer": None,
                "reviewed_at": None,
                "pages": [{"id": r["id"], "decision": "pending", "notes": ""} for r in records],
            },
        )
        render_review(run, records)
        return run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--enable", action="store_true", help="Explicitly run one bounded shadow batch"
    )
    parser.add_argument("--manifest", type=Path, help="JSON documents with path, SHA-256 and pages")
    args = parser.parse_args(argv)
    if not args.enable:
        print(json.dumps({"status": "disabled", "production_ingestion": False}))
        return 0
    if sys.platform != "linux":
        parser.error("Run this isolated lane in Linux/WSL")
    if args.manifest is None:
        parser.error("--enable requires an explicit --manifest")
    documents = validate_documents(
        json.loads(args.manifest.read_text(encoding="utf8"))["documents"]
    )
    run = run_batch(documents, verify_release())
    print(json.dumps({"output": str(run), "production_ingestion": False}))
    records = json.loads((run / "summary.json").read_text())["records"]
    return int(
        any(
            r["status"] in {"error", "timeout", "unavailable", "empty", "fallback"} for r in records
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
