"""守卫下运行 I3-1 dev lane build + check（只 build/check，不 publish）。

装载 guards/i3-e2e.json（网络仅 127.0.0.1:543；来源读取限 8 份授权路径；
CORPUS_DSN 等投毒），调用 cli.main 跑 build，再对每个 in_scope 产物跑 check，
输出机读 gaps / publishable / blocking。
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
GUARD = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i3-e2e.json"
MANIFEST = HERE / "dev-scope-manifest.json"
DSN = "postgresql://postgres:postgres@127.0.0.1:543/i2_sandbox_corpus"


def cli_run(cli, argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = cli.main(argv)
    text = buf.getvalue()
    return {"exit_code": code, "text": text}


def main() -> int:
    os.environ["CORPUS_DEV_LANE"] = "1"
    sys.path.insert(0, str(ROOT))
    from plugins.corpus.preparation import guard as guard_module  # noqa: PLC0415
    guard_module.install(GUARD)
    from plugins.corpus import cli  # noqa: PLC0415

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    sources = manifest["sources"]

    build = cli_run(cli, ["build", "--manifest", str(MANIFEST), "--dsn", DSN,
                          "--owner", "cli-build-i31-dev-lane"])
    print("=== BUILD ===")
    print(build["text"])

    payload = None
    text = build["text"]
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = json.loads(text[text.find("{"):])
    outcomes = {str(o.get("original_name")): o for o in (payload or {}).get("outcomes") or []}

    per_source = []
    for entry in sources:
        name = Path(str(entry["path"])).name
        outcome = outcomes.get(name) or {}
        row = {
            "path": str(entry["path"]), "original_name": name,
            "provenance": entry.get("provenance"),
            "decision": outcome.get("decision"),
            "decision_id": outcome.get("decision_id"),
            "build_id": outcome.get("build_id"),
            "unit_count": outcome.get("unit_count"),
            "chunk_count": outcome.get("chunk_count"),
            "source_reused": outcome.get("source_reused"),
            "archive_reused": outcome.get("archive_reused"),
        }
        if outcome.get("decision") == "in_scope" and outcome.get("build_id"):
            checked = cli_run(cli, ["check", "--build", str(outcome["build_id"]), "--dsn", DSN])
            cpayload = None
            ctext = checked["text"]
            try:
                cpayload = json.loads(ctext)
            except json.JSONDecodeError:
                cpayload = json.loads(ctext[ctext.find("{"):])
            row["check"] = {
                "exit_code": checked["exit_code"],
                "publishable": (cpayload or {}).get("publishable"),
                "error": (cpayload or {}).get("error"),
                "gap_summary": (cpayload or {}).get("gap_summary"),
                "gaps": (cpayload or {}).get("gaps"),
            }
        per_source.append(row)

    print("=== PER_SOURCE ===")
    print(json.dumps({"batch_exit": build["exit_code"], "per_source": per_source},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())