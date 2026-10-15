"""Zero-call registration of the 83-号 superseded signoff-md drift.

``tools/check_claims_gate.py`` has reported ``[DIVERGENCE] superseded-artifact-drift`` since the
85-号 v2 audit (2026-10-14): the 83-号 draft MANIFEST pins
``claims-gate-v1-signoff.md`` to ``c3f212…`` while the file on disk hashes to ``7403d1…``. The
check's own claim carries the exception — *"md 漂移须登记"* — so the drift is not forbidden, it is
**unregistered**. This record supplies the missing registration:

* which artifact drifted, with **both** hashes (MANIFEST-recorded and on-disk);
* what the drift does *not* touch (the two 83-号 JSON products still match their recorded bytes);
* why it cannot be reverted (the recorded version exists nowhere — neither on disk nor in git, whose
  history for this tree is a single squashed commit — and reverting would flip
  ``superseded-signoff-consistency`` from pass to divergence);
* that no cause was recorded at the time, so none is asserted here.

Zero model calls; read-only with respect to every frozen artifact: this script writes only inside
its own directory, through ``tools.evidence_guard.write_once`` (write-once, refuses signed targets).

Usage:
    python build_drift_registration.py [--no-write] [--force]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]  # .scratch/claims-r2-role-isolation
REPO_ROOT = ROOT.parents[1]
sys.path.insert(0, str(REPO_ROOT))

from tools.evidence_guard import write_once  # noqa: E402

REGISTERED_ON = "2026-10-15"

SUPERSEDED_DIR = ROOT / "evidence/83-claims-scope-gate-draft-20261014/r0-zero-call"
SUPERSEDED_MANIFEST = SUPERSEDED_DIR / "MANIFEST.json"
SUPERSEDED_MD = SUPERSEDED_DIR / "claims-gate-v1-signoff.md"
SUPERSEDED_GATE = SUPERSEDED_DIR / "claims-gate-v1.proposed.json"
SUPERSEDED_COVERAGE = SUPERSEDED_DIR / "coverage-measurements.json"

OUT_REGISTRATION = HERE / "superseded-drift-registration.json"
OUT_MANIFEST = HERE / "MANIFEST.json"

# The md product name as it appears in the 83-号 MANIFEST ``outputs`` map.
MD_OUTPUT_NAME = "claims-gate-v1-signoff.md"


def sha256(path: Path) -> str:
    """Bare hex digest, matching the 83-号 MANIFEST's own digest convention."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _relative(path: Path) -> str:
    """Scratch-relative path (``evidence/…``), matching the 92/93/89-号 record convention.

    The checker accepts either this form or the repo-relative ``.scratch/…`` form.
    """
    return str(path.relative_to(ROOT))


def build() -> tuple[dict[str, object], dict[str, object]]:
    """Derive the registration and manifest bodies from the frozen inputs."""
    recorded = json.loads(SUPERSEDED_MANIFEST.read_text(encoding="utf-8"))
    recorded_outputs: dict[str, str] = recorded["outputs"]

    md_recorded = recorded_outputs[MD_OUTPUT_NAME]
    md_on_disk = sha256(SUPERSEDED_MD)
    if md_recorded == md_on_disk:
        raise SystemExit(
            "无可登记项：83 号 signoff md 已与 MANIFEST 记录哈希一致；"
            "本件描述的是既往漂移，一旦复原即应改为空登记并复核。"
        )

    # The two JSON products must still match their recorded bytes: the registration covers the md
    # only, so a JSON drift would have to be a separate, more serious finding.
    json_drift = {
        name: {"recorded": digest, "on_disk": sha256(SUPERSEDED_DIR / name)}
        for name, digest in recorded_outputs.items()
        if name != MD_OUTPUT_NAME and (SUPERSEDED_DIR / name).exists()
        and sha256(SUPERSEDED_DIR / name) != digest
    }
    if json_drift:
        raise SystemExit(f"83 号 JSON 产物也发生漂移，超出本件范围：{json_drift}")

    md_text = SUPERSEDED_MD.read_text(encoding="utf-8")
    gate = json.loads(SUPERSEDED_GATE.read_text(encoding="utf-8"))

    registration: dict[str, object] = {
        "schema_version": "claims-superseded-artifact-drift-registration-1",
        "created_on": REGISTERED_ON,
        "zero_model_calls": True,
        "basis": {
            "claim": "被取代的 83 号产物未在草案态被改动（md 漂移须登记）",
            "checker": "tools/check_claims_gate.py",
            "check_id": "superseded-artifact-drift",
            "manifest": _relative(SUPERSEDED_MANIFEST),
            "reading": (
                "该主张的括号例外即本件：草案 md 的文本改动本身不被禁止，但必须登记"
                "（产物路径 + MANIFEST 记录哈希 + 磁盘现值 + 触及范围 + 不可逆性）；"
                "83 号的 JSON 产物与 coverage 物不得漂移。"
            ),
            "detected_since": "evidence/85-claims-gate-v2-audit-20261014（此后 87/89/91 号落地记录均照实录出）",
        },
        "entries": [
            {
                "artifact": _relative(SUPERSEDED_MD),
                "manifest_recorded_sha256": md_recorded,
                "on_disk_sha256": md_on_disk,
                "change_kind": "text_edit_on_superseded_draft",
                "observed_on_disk_state": {
                    "residual_signed_on": "signed_on: 2026-10-14" in md_text,
                    "carries_reviewer_name": "reviewer: xyl" in md_text,
                    "json_signoff_reviewer_null": gate["signoff"].get("reviewer") is None,
                },
                "counterpart_check": (
                    "superseded-signoff-consistency（要求 83 号 JSON signoff 为 null 且 md 无残留 signed_on）"
                ),
                "cause": (
                    "无当时记录：83 号 MANIFEST 写于 2026-10-14 01:30（mtime），md 于 2026-10-14 09:33 "
                    "被改，其间没有任何变更记录件。本件只登记事实与范围，不以推测代替证据。"
                ),
                "scope": (
                    "仅该草案 md 的文本；claims-gate-v1.proposed.json 与 coverage-measurements.json "
                    "的字节与 MANIFEST 记录逐条一致，未漂移。不触及任何已签认产物。"
                ),
                "irreversibility": (
                    f"{md_recorded[:12]}… 版本在磁盘与 git 中均不存在（该目录的 git 历史为单次压缩提交），"
                    "无法复原；且回退会使 superseded-signoff-consistency 由 pass 转为 divergence。"
                ),
                "disposition": (
                    "接受该改动并登记为已知漂移；不得再次改动——后续修订须另立新目录并留旧哈希。"
                ),
                "status": "registered_pending_human_signature",
            }
        ],
        "not_covered": [
            {
                "item": "83 号 JSON 产物（claims-gate-v1.proposed.json / coverage-measurements.json）",
                "reason": "与 MANIFEST 记录哈希逐条一致，无漂移，无需登记；builder 会在其漂移时直接拒绝出件",
            },
            {
                "item": "83 号 md 的改动原因",
                "reason": "无当时记录；本件登记事实、范围与不可逆性，不为无据的原因背书",
            },
        ],
        "signoff": {"reviewer": None, "adjudicator": None, "signed_on": None},
    }

    manifest: dict[str, object] = {
        "schema_version": "claims-zero-call-cleanup-manifest-1",
        "status": "draft",
        "created_on": REGISTERED_ON,
        "model_calls": 0,
        "inputs": {
            "superseded_83_manifest": sha256(SUPERSEDED_MANIFEST),
            "superseded_83_signoff_md": md_on_disk,
            "superseded_83_gate": sha256(SUPERSEDED_GATE),
            "superseded_83_coverage": sha256(SUPERSEDED_COVERAGE),
        },
        "outputs": {},
        "registers": {
            "check_id": "superseded-artifact-drift",
            "drifted_artifact": _relative(SUPERSEDED_MD),
            "manifest_recorded_sha256": md_recorded,
            "on_disk_sha256": md_on_disk,
        },
    }
    return registration, manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-write", action="store_true", help="只打印将要写出的件")
    parser.add_argument("--force", action="store_true", help="允许覆盖已存在文件（默认拒绝）")
    args = parser.parse_args(argv)

    registration, manifest = build()
    registration_text = json.dumps(registration, ensure_ascii=False, indent=2) + "\n"
    if args.no_write:
        print(registration_text)
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return 0

    write_once(
        OUT_REGISTRATION,
        registration_text,
        reason="83 号 md 漂移登记",
        allow_overwrite=args.force,
    )
    manifest["outputs"] = {
        "superseded-drift-registration.json": sha256(OUT_REGISTRATION),
    }
    write_once(
        OUT_MANIFEST,
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        reason="83 号 md 漂移登记清单",
        allow_overwrite=args.force,
    )
    print(f"wrote {_relative(OUT_REGISTRATION)}")
    print(f"wrote {_relative(OUT_MANIFEST)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
