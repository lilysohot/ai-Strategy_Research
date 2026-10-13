"""Wave 0 · P06: the shared signature guard refuses to overwrite signed artifacts."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tools.evidence_guard import (
    SignedArtifactError,
    artifact_state,
    assert_writable,
    write_once,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_missing_and_plain(tmp_path: Path) -> None:
    assert artifact_state(tmp_path / "absent.json") == "missing"
    plain = tmp_path / "plain.json"
    plain.write_text(json.dumps({"status": "draft"}), encoding="utf-8")
    assert artifact_state(plain) == "plain"


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "frozen"},
        {"status": "frozen_signed"},
        {"status": "human_signed"},
        {"countersignature": {"status": "signed"}},
        {"signoff": {"signed_by": "xyl"}},
        {"signed_by": "xyl"},
    ],
)
def test_structured_signals_are_signed(tmp_path: Path, payload: dict[str, object]) -> None:
    target = tmp_path / "signed.json"
    target.write_text(json.dumps(payload), encoding="utf-8")
    assert artifact_state(target) == "signed"


def test_quoting_a_signature_does_not_make_a_file_signed(tmp_path: Path) -> None:
    """A report that merely *cites* a signer must stay writable (no false positive)."""
    target = tmp_path / "report.json"
    target.write_text(
        json.dumps(
            {
                "schema_version": "x",
                "contract_binding": {"signed_by": "xyl", "status": "frozen_signed"},
                "nested": [{"signoff": "被引用"}],
            }
        ),
        encoding="utf-8",
    )
    assert artifact_state(target) == "plain"


def test_markdown_review_sheet_is_signed_by_marker(tmp_path: Path) -> None:
    sheet = tmp_path / "review.md"
    sheet.write_text("# 审阅\n\n- 复核人：　xyl\n", encoding="utf-8")
    assert artifact_state(sheet) == "signed"
    other = tmp_path / "notes.md"
    other.write_text("# 随笔\n", encoding="utf-8")
    assert artifact_state(other) == "plain"


def test_blank_review_template_is_not_signed(tmp_path: Path) -> None:
    """A template carries the *words* of a signature slot; that is not a signature."""
    template = tmp_path / "review.md"
    template.write_text(
        "# 审阅件（待签）\n\n"
        "## 五、签认栏\n\n"
        "- 复核人：　　　　　　日期：\n"
        "- 结论：☐ 认可并签认　　☐ 退回修改\n"
        "- 备注：\n",
        encoding="utf-8",
    )
    assert artifact_state(template) == "plain"


def test_checked_box_counts_as_signed(tmp_path: Path) -> None:
    sheet = tmp_path / "review.md"
    sheet.write_text("- 结论：☑ 认可并签认 v4\n", encoding="utf-8")
    assert artifact_state(sheet) == "signed"
    xmark = tmp_path / "xmark.md"
    xmark.write_text("- 结论：x 认可并签认 v4　　☐ 退回修改\n", encoding="utf-8")
    assert artifact_state(xmark) == "signed"


def test_write_once_refuses_existing_file(tmp_path: Path) -> None:
    target = tmp_path / "artifact.json"
    write_once(target, {"a": 1})
    assert json.loads(target.read_text(encoding="utf-8")) == {"a": 1}
    with pytest.raises(SignedArtifactError, match="write-once"):
        write_once(target, {"a": 2})
    write_once(target, {"a": 3}, allow_overwrite=True)
    assert json.loads(target.read_text(encoding="utf-8")) == {"a": 3}


def test_write_once_refuses_signed_target_even_with_allow_overwrite(tmp_path: Path) -> None:
    target = tmp_path / "preregistered-gate.json"
    target.write_text(json.dumps({"status": "frozen_before_execution"}), encoding="utf-8")
    with pytest.raises(SignedArtifactError, match="已含签认/冻结标记"):
        write_once(target, {"status": "draft"}, allow_overwrite=True, reason="test")
    with pytest.raises(SignedArtifactError, match="已含签认/冻结标记"):
        assert_writable(target, reason="test")
    # The signed bytes are untouched.
    assert json.loads(target.read_text(encoding="utf-8"))["status"] == "frozen_before_execution"


def test_write_once_is_atomic_and_leaves_no_temp_files(tmp_path: Path) -> None:
    target = tmp_path / "artifact.json"
    write_once(target, {"a": 1})
    assert [item.name for item in tmp_path.iterdir()] == ["artifact.json"]


def test_conformance_scanner_passes_on_the_real_tree() -> None:
    """The scanner must be usable as a gate: zero violations, only registered exceptions."""
    result = subprocess.run(
        [sys.executable, "tools/check_evidence_guard.py", "--quiet"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_empty_signoff_placeholder_is_not_signed(tmp_path: Path) -> None:
    """A draft may carry an empty signoff block; only a filled one counts (P06 guard fix)."""
    draft = tmp_path / "draft.json"
    draft.write_text(
        json.dumps(
            {
                "schema_version": "x",
                "status": "draft_pending_human_signature",
                "signoff": {"signed_by": None, "signed_on": None, "instrument": None},
            }
        ),
        encoding="utf-8",
    )
    assert artifact_state(draft) == "plain"


def test_filled_signoff_block_is_signed(tmp_path: Path) -> None:
    signed = tmp_path / "signed.json"
    signed.write_text(
        json.dumps(
            {
                "schema_version": "x",
                "status": "draft_pending_human_signature",
                "signoff": {"signed_by": "xyl", "instrument": {"sha256": "sha256:" + "a" * 64}},
            }
        ),
        encoding="utf-8",
    )
    assert artifact_state(signed) == "signed"


def test_pending_countersignature_placeholder_is_not_signed(tmp_path: Path) -> None:
    """The R2 gate drafts carry a *pending* countersignature block; that is not a signature.

    Regression for ``evidence/74-…/gate-v3.proposed.json`` (found 2026-10-13): the same class
    of false positive already fixed for ``signoff`` on 2026-10-12. A nested ``signed_by`` (e.g.
    in ``revision_history``) must not leak into the top-level judgement either.
    """
    draft = tmp_path / "gate-v3.proposed.json"
    draft.write_text(
        json.dumps(
            {
                "schema_version": "x",
                "status": "draft_pending_human_signature",
                "countersignature": {
                    "required": True,
                    "status": "pending_human_signoff",
                    "reviewer": None,
                    "signed_on": None,
                },
                "revision_history": [{"signed_by": "xyl"}, {"signed_by": "xyl"}],
            }
        ),
        encoding="utf-8",
    )
    assert artifact_state(draft) == "plain"


@pytest.mark.parametrize(
    "block",
    [
        {"status": "pending_human_signoff", "signed_by": "xyl"},
        {"status": "pending_human_signoff", "signed_on": "2026-10-13"},
        {"status": "pending_human_signoff", "instrument": {"sha256": "x"}},
        {"status": "countersigned"},
        {"status": "不认识的未来状态"},
    ],
)
def test_filled_countersignature_is_signed(tmp_path: Path, block: dict[str, object]) -> None:
    """Explicit evidence wins over a pending status; unknown shapes stay protected (fail-closed)."""
    target = tmp_path / "countersigned.json"
    target.write_text(
        json.dumps({"schema_version": "x", "status": "draft", "countersignature": block}),
        encoding="utf-8",
    )
    assert artifact_state(target) == "signed"


def test_proposed_pending_signoff_status_stays_protected(tmp_path: Path) -> None:
    """Retained by design (2026-10-13): a proposal already sent out for signature must not be
    clobbered by a regenerating script. Loosening this needs an explicit ruling."""
    target = tmp_path / "proposal.json"
    target.write_text(json.dumps({"status": "proposed_pending_signoff"}), encoding="utf-8")
    assert artifact_state(target) == "signed"
