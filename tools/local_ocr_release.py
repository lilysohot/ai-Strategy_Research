"""Build/start the production OCR service from verified frozen model code."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/local-ocr-production"
BASE = "sha256:141ee6ffbc6d0ec0c025f9deccbf93ae832f6721ef90018de93312b6dfc36c1b"
FILES = {
    "page_orientation.py": "experiments/rapidocr-page-orientation-20261031/page_orientation.py",
    "body_reader.py": "experiments/rapidocr-body-20261030/body_reader.py",
    "config.py": "experiments/rapidocr-smoke-20261019/config.py",
    "service.py": "plugins/local_ocr/service.py",
    "worker.py": "plugins/local_ocr/worker.py",
}


def run(command: list[str]) -> str:
    return subprocess.run(
        command, check=True, text=True, capture_output=True, timeout=180
    ).stdout.strip()


def build() -> dict[str, object]:
    frozen = json.loads((ROOT / "config/ocr-shadow-release.json").read_text())["files"]
    hashes = {
        name: hashlib.sha256((ROOT / source).read_bytes()).hexdigest()
        for name, source in FILES.items()
    }
    for name in ("page_orientation.py", "body_reader.py", "config.py"):
        if hashes[name] != frozen[FILES[name]]:
            raise ValueError("Frozen OCR algorithm/model configuration drift")
    fingerprint = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    release = "rapidocr-prod-" + fingerprint[:16]
    directory = DATA / "builds" / fingerprint
    directory.mkdir(parents=True, exist_ok=True)
    code = directory / "code"
    code.mkdir(exist_ok=True)
    for name, source in FILES.items():
        shutil.copyfile(ROOT / source, code / name)
    shutil.copyfile(ROOT / "deploy/Dockerfile.ocr", directory / "Dockerfile")
    run(["docker", "image", "inspect", BASE])
    run(["docker", "tag", BASE, "frontier-ocr-base:20261031"])
    tag = "frontier-local-ocr:" + fingerprint[:16]
    log = subprocess.run(
        ["docker", "build", "--pull=false", "-t", tag, str(directory)],
        capture_output=True,
        text=True,
        timeout=180,
    )
    (directory / "build.log").write_text(log.stdout + log.stderr)
    log.check_returncode()
    image = run(["docker", "image", "inspect", tag, "--format", "{{.Id}}"])
    manifest = {"release": release, "image": image, "base_image": BASE, "files": hashes}
    (DATA / "release.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def start() -> dict[str, object]:
    release = json.loads((DATA / "release.json").read_text())
    token = DATA / "token"
    if not token.exists():
        with os.fdopen(os.open(token, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as out:
            out.write("Bearer " + secrets.token_urlsafe(40))
    results = DATA / "results"
    results.mkdir(exist_ok=True)
    command = [
        "docker",
        "run",
        "-d",
        "--name",
        "frontier-local-ocr",
        "--restart",
        "unless-stopped",
        "--pull",
        "never",
        "--network",
        "bridge",
        "-p",
        "127.0.0.1:8780:8780",
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
        "-e",
        "OCR_RELEASE=" + release["release"],
        "--mount",
        f"type=bind,source={token},target=/run/ocr-token,readonly",
        "--mount",
        f"type=bind,source={results},target=/results",
        release["image"],
    ]
    container = run(command)
    return {
        "container": container,
        "release": release["release"],
        "endpoint": "http://127.0.0.1:8780",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["build", "start"])
    args = parser.parse_args()
    print(json.dumps(build() if args.action == "build" else start()))
