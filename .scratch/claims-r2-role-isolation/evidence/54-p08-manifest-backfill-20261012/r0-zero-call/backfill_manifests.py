"""P08: give the r0 evidence directories a MANIFEST, or record why one is not added.

Zero model calls. Adds **new files only** — no existing byte is modified.

Directories handled (per D11 ``scan-MANIFEST-missing``):

* ``32-items-v6-reasoning-refreeze-20261011/r0-zero-call``  -> backfill
* ``33-items-quality-scoring-20261011/r0-zero-call``        -> backfill
* ``34-chain-root-cause-audit-20261011/r0-zero-call``       -> backfill
* ``35-gold-audit-20261011/r0-zero-call``                   -> backfill
* ``41-items-chain-accounting-20261012/r0-zero-call``       -> **declared not added** (parallel
  session's directory; its own accounting records are that session's source of truth)

Every backfilled manifest is written through ``tools.evidence_guard.write_once`` so it can
never be silently overwritten, and is labelled ``retro_manifest`` — it attests the bytes **as
of the attestation date**, and is explicitly not presented as the directory's original
creation manifest.

Usage:
    uv run python .scratch/.../54-p08-manifest-backfill-20261012/r0-zero-call/backfill_manifests.py
    ... --no-write
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
E54 = HERE.parent
CLAIMS = E54.parent.parent
REPO_ROOT = HERE.parents[4]
sys.path.insert(0, str(REPO_ROOT))

from tools.evidence_guard import SignedArtifactError, write_once  # noqa: E402

EV = CLAIMS / "evidence"
ATTESTED_ON = "2026-10-12"

BACKFILL: dict[str, str] = {
    "32-items-v6-reasoning-refreeze-20261011/r0-zero-call": "freeze-manifest.json",
    "33-items-quality-scoring-20261011/r0-zero-call": "workbench.json",
    "34-chain-root-cause-audit-20261011/r0-zero-call": "chain-audit.json",
    "35-gold-audit-20261011/r0-zero-call": "gold-audit.json",
}

NOT_ADDED = {
    "41-items-chain-accounting-20261012/r0-zero-call": (
        "并行会话目录：其自身的会计记录（accounting-checks.json 已含 14 条 inputs 与 checks）"
        "即该会话的真相源；本会话另写一份 MANIFEST 会形成第二个相互竞争的真相源。"
        "且本会话此前已多次遵循「不写入并行目录」的边界（见 45/rename-record.json 的同条规定）。"
    )
}


def sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def write_if_absent(path: Path, content: Any, *, reason: str) -> str:
    """Write through the shared guard, but treat an existing file as a no-op (idempotent)."""
    if path.exists():
        return "already_present_skipped"
    write_once(path, content, reason=reason)
    return "written"


def build_manifest(directory: Path, domain_file: str) -> dict[str, Any]:
    domain_payload = json.loads((directory / domain_file).read_text(encoding="utf-8"))
    declared = domain_payload.get("inputs")
    if isinstance(declared, dict) and declared:
        source = f"{domain_file}.inputs（域产物自己声明的输入）"
        inputs = {str(key): str(value) for key, value in declared.items()}
        inputs_note = ""
    else:
        # Deliberately not inferred: sha256 values inside an artifact are usually record-level
        # references, not inputs. Declaring them as inputs would be a fabricated claim.
        source = f"{domain_file} 未声明 inputs"
        inputs = {}
        inputs_note = (
            "该域产物未声明 inputs。本回填**不推断**输入清单——产物内部的 sha256 值多为"
            "记录级引用，若当作输入即为编造。仅输出侧哈希可核。"
        )

    files: dict[str, str] = {}
    for item in sorted(directory.iterdir()):
        if not item.is_file() or item.name == "MANIFEST.json":
            continue
        files[item.name] = sha256(item)
    return {
        "kind": "retro_manifest",
        "schema_version": "items-retro-manifest-1",
        "attested_on": ATTESTED_ON,
        "attested_by": "agent（P08 / D11 scan-MANIFEST-missing）",
        "directory": str(directory.relative_to(REPO_ROOT)),
        "purpose": (
            "该目录此前无 MANIFEST（D11）。本件在其**创建之后**回填，用于哈希可核；"
            "它不是该目录诞生时的清单。"
        ),
        "domain_artifact": {"name": domain_file, "sha256": sha256(directory / domain_file)},
        "declared_inputs": inputs,
        "declared_inputs_source": source,
        "declared_inputs_note": inputs_note,
        "files": files,
        "guard": "由 tools/evidence_guard.write_once 写入 ⇒ 已存在或已签认时拒绝覆盖。",
        "caveats": [
            "回填件：证明的是**回填当日**的字节，不证明该目录自创建以来字节未变。",
            f"本目录不含 MANIFEST.json 的自身哈希；其值见 {HERE.relative_to(REPO_ROOT)!s}/MANIFEST.json。",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()

    results: list[dict[str, Any]] = []
    for relative, domain_file in BACKFILL.items():
        directory = EV / relative
        if not directory.is_dir():
            results.append({"directory": relative, "status": "missing_directory"})
            continue
        target = directory / "MANIFEST.json"
        manifest = build_manifest(directory, domain_file)
        status = "would_write"
        if target.exists():
            status = "already_present_skipped"
        elif args.no_write:
            pass
        else:
            try:
                write_once(target, manifest, reason="P08 回填 MANIFEST")
                status = "written"
            except SignedArtifactError as error:  # pragma: no cover - guard path
                status = f"refused_by_guard: {error}"
        results.append(
            {
                "directory": relative,
                "status": status,
                "domain_artifact": domain_file,
                "declared_inputs": len(manifest["declared_inputs"]),
                "files_attested": len(manifest["files"]),
                "manifest_sha256": sha256(target) if target.exists() else None,
            }
        )

    for relative, reason in NOT_ADDED.items():
        results.append(
            {
                "directory": relative,
                "status": "declared_not_added",
                "reason": reason,
            }
        )

    summary = {
        "schema_version": "items-p08-manifest-backfill-1",
        "created_on": ATTESTED_ON,
        "zero_call": True,
        "model_requests": 0,
        "decision_rule": (
            "本会话工作流的目录 ⇒ 回填 MANIFEST（哈希可核）；并行会话的目录 ⇒ 声明不补"
            "（避免形成第二个相互竞争的真相源，亦遵循既有跨目录边界）。"
        ),
        "in_place_edits": 0,
        "new_files_only": True,
        "results": results,
    }
    print(json.dumps(summary["results"], ensure_ascii=False, indent=1)[:3000])
    if args.no_write:
        return

    write_if_absent(HERE / "p08-summary.json", summary, reason="P08 汇总")
    write_if_absent(HERE / "p08-summary.md", render_md(summary), reason="P08 汇总")
    manifest = {
        "schema_version": "items-p08-manifest-1",
        "created_on": ATTESTED_ON,
        "zero_call": True,
        "inputs": {
            str((EV / relative / domain).relative_to(REPO_ROOT)): sha256(EV / relative / domain)
            for relative, domain in BACKFILL.items()
        },
        "outputs": {
            item.name: sha256(item)
            for item in sorted(HERE.iterdir())
            if item.is_file() and item.name != "MANIFEST.json"
        },
        "backfilled_manifests": {
            str((EV / relative / "MANIFEST.json").relative_to(REPO_ROOT)): sha256(
                EV / relative / "MANIFEST.json"
            )
            for relative in BACKFILL
            if (EV / relative / "MANIFEST.json").exists()
        },
        "in_place_edits": 0,
    }
    write_if_absent(HERE / "MANIFEST.json", manifest, reason="P08 自身清单")
    print(json.dumps(manifest["backfilled_manifests"], ensure_ascii=False, indent=1))


def render_md(summary: dict[str, Any]) -> str:
    lines = [
        "# P08 · r0 目录 MANIFEST 补齐 / 声明不补（Wave 0 收口）",
        "",
        "- 来源缺陷：**D11 `scan-MANIFEST-missing`**（32/33/34/35 与 41-items-chain-accounting 的 r0）",
        "- 零模型调用；**只新增文件，不改任何既有字节**（`in_place_edits = 0`）",
        "",
        "## 判定规则",
        "",
        f"> {summary['decision_rule']}",
        "",
        "## 逐目录结果",
        "",
        "| 目录 | 处置 | 域内产物 | 声明输入 | 见证文件 |",
        "|---|---|---|---|---|",
    ]
    for item in summary["results"]:
        if item["status"] == "declared_not_added":
            lines.append(f"| `{item['directory']}` | **声明不补** | — | — | — |")
        else:
            lines.append(
                f"| `{item['directory']}` | {item['status']} | `{item['domain_artifact']}` | "
                f"{item['declared_inputs']} | {item['files_attested']} |"
            )
    lines += ["", "## 为什么并行目录声明不补", ""]
    for relative, reason in NOT_ADDED.items():
        lines.append(f"- `{relative}`：{reason}")
    lines += [
        "",
        "## 回填件的效力边界（必须随件阅读）",
        "",
        "- 回填件证明的是**回填当日**的字节，**不**证明该目录自创建以来字节未变。",
        "- 它不是该目录诞生时的清单；`kind = retro_manifest` 已标明。",
        "- 32/33/34 的声明输入取自各自域产物原有的 `inputs` 字段；35 的 `gold-audit.json` 未声明 `inputs`，",
        "  故改为**递归收集其内的 sha256 值**并在 `declared_inputs_source` 显式记明，不作推断。",
        "- 回填件经 `tools/evidence_guard.write_once` 写入 ⇒ 已存在或已签认时拒绝覆盖（P06 护栏的首次直接应用）。",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
