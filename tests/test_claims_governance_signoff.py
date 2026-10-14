"""Governance signoff materialisation (96 号): the human act is the only way in.

These tests pin the properties that keep "signing" a human act:

* the real instrument is still unsigned, and the tool refuses it;
* a blank slot, a blank signature field, a missing slot or an unknown enum value all refuse;
* ``--apply`` writes a *new* signed record whose signature is bound to the instrument hash, and the
  93-号 plan bytes are untouched;
* the materialised record is exactly what the executor consumes -- signoff -> decisions -> drafts
  works end to end.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.apply_claims_governance_decisions import read_decisions
from tools.apply_claims_governance_signoff import (
    DEFAULT_INSTRUMENT,
    DEFAULT_PLAN,
    SignoffError,
    build_signed_plan,
    load_json,
    main,
    parse_instrument,
    sha256,
)

SIGNED_INSTRUMENT = """
## 二、三格

```
M1 = b_scaled_floor            # a_transplant | b_scaled_floor | b_scaled_ceil | c_diagnostic
M2 = report_only            # exists | report_only
M3 = O1_status_quo            # O1_status_quo | O2_remap_two_codes | O3_extend_vocabulary
```

## 签名

reviewer: xyl    adjudicator: xyl    signed_on: 2026-10-14
"""


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "instrument.md"
    path.write_text(text, encoding="utf-8")
    return path


def test_the_real_instrument_is_still_unsigned_and_refused() -> None:
    with pytest.raises(SignoffError, match="仍为空白"):
        parse_instrument(DEFAULT_INSTRUMENT.read_text(encoding="utf-8"))


def test_a_complete_instrument_parses() -> None:
    parsed = parse_instrument(SIGNED_INSTRUMENT)
    assert parsed["decisions"] == {
        "M1": "b_scaled_floor",
        "M2": "report_only",
        "M3": "O1_status_quo",
    }
    assert parsed["signoff"] == {
        "reviewer": "xyl",
        "adjudicator": "xyl",
        "signed_on": "2026-10-14",
    }


@pytest.mark.parametrize(
    ("text", "error"),
    [
        (SIGNED_INSTRUMENT.replace("M2 = report_only", "M2 = ____"), "仍为空白"),
        (SIGNED_INSTRUMENT.replace("M1 =", "M9 ="), "缺少格位"),
        (
            SIGNED_INSTRUMENT.replace("M3 = O1_status_quo", "M3 = O9_something"),
            "M3 取值未知",
        ),
        (
            SIGNED_INSTRUMENT.replace("reviewer: xyl", "reviewer: ____________"),
            "签名栏未填",
        ),
        (
            SIGNED_INSTRUMENT.replace("signed_on: 2026-10-14", "signed_on: ____"),
            "签名栏未填",
        ),
        (SIGNED_INSTRUMENT.split("## 签名")[0], "找不到签名行"),
    ],
)
def test_incomplete_or_unknown_instruments_refuse(text: str, error: str) -> None:
    with pytest.raises(SignoffError, match=error):
        parse_instrument(text)


def test_dry_run_writes_nothing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    instrument = _write(tmp_path, SIGNED_INSTRUMENT)
    out = tmp_path / "out"
    assert main(["--instrument", str(instrument), "--out", str(out)]) == 0
    assert not out.exists()
    assert "[dry-run] 未写盘" in capsys.readouterr().out


def test_signed_record_binds_the_instrument_and_the_unsigned_plan(tmp_path: Path) -> None:
    instrument = _write(tmp_path, SIGNED_INSTRUMENT)
    out = tmp_path / "out"
    assert main(["--instrument", str(instrument), "--apply", "--out", str(out)]) == 0

    signed = load_json(out / "claims-governance-plan.signed.json")
    assert signed["status"] == "signed"
    assert signed["decision_signoff"]["reviewer"] == "xyl"
    assert signed["decision_signoff"]["instrument"]["sha256"] == sha256(instrument)
    assert signed["rules_in_force"]["status"] == "signed"
    cells = {cell["id"]: cell for cell in signed["cells"]}
    for cell_id, value in (
        ("M1", "b_scaled_floor"),
        ("M2", "report_only"),
        ("M3", "O1_status_quo"),
    ):
        assert cells[cell_id]["status"] == "decided"
        assert cells[cell_id]["value"] == value
        assert cells[cell_id]["pending_caliber"] is False
    assert signed["_materialised_from"]["plan_sha256"] == sha256(DEFAULT_PLAN)
    with pytest.raises(SignoffError, match="refusing to overwrite"):
        main(["--instrument", str(instrument), "--apply", "--out", str(out)])


def test_the_unsigned_plan_bytes_are_untouched(tmp_path: Path) -> None:
    before = sha256(DEFAULT_PLAN)
    instrument = _write(tmp_path, SIGNED_INSTRUMENT)
    main(["--instrument", str(instrument), "--apply", "--out", str(tmp_path / "out")])
    assert sha256(DEFAULT_PLAN) == before
    assert before == "5aa29fca91e6d64aab6b31d04dfee3dd902fcb726d57ca22ec99792f2a02ed82"


def test_signoff_feeds_the_executor_end_to_end(tmp_path: Path) -> None:
    """signoff -> decisions -> contract leaves: the signed record must be executable as-is."""
    instrument = _write(tmp_path, SIGNED_INSTRUMENT)
    out = tmp_path / "out"
    main(["--instrument", str(instrument), "--apply", "--out", str(out)])
    signed = load_json(out / "claims-governance-plan.signed.json")
    assert read_decisions(signed) == {
        "M1": "b_scaled_floor",
        "M2": "report_only",
        "M3": "O1_status_quo",
    }
    # And the executor path itself still refuses the unsigned record.
    with pytest.raises(Exception, match="decision_signoff"):
        read_decisions(json.loads(DEFAULT_PLAN.read_text(encoding="utf-8")))


def test_build_signed_plan_marks_every_cell_decided() -> None:
    parsed = parse_instrument(SIGNED_INSTRUMENT)
    plan = load_json(DEFAULT_PLAN)
    signed = build_signed_plan(
        plan,
        parsed,
        plan_sha="0" * 64,
        instrument_sha="1" * 64,
        instrument_relative="evidence/x.md",
    )
    assert all(cell["status"] == "decided" for cell in signed["cells"])
    assert {cell["value"] for cell in signed["cells"]} == {
        "b_scaled_floor",
        "report_only",
        "O1_status_quo",
    }
