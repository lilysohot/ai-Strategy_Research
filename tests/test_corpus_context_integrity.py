"""Regression coverage for contextual-unit integrity; all synthetic, no DB."""

from contextlib import nullcontext
from unittest.mock import patch

import pytest

from plugins.corpus.preparation import cross_boundary as cb
from plugins.corpus.preparation.contract import UnitStatus, sha256_of_bytes
from plugins.corpus.preparation.read_pg import ChunkEvidence, IntegrityError, UnitEvidence


@pytest.mark.parametrize("kind", ["header", "continuation", "source_note"])
def test_added_authority_unit_must_reject_invalid_hash(kind):
    raw = "Verified incomplete"
    cells = ((0, 0),) if kind == "source_note" else ()
    loc = {"page": 1, "bbox": [0, 20, 100, 40]}
    ev = ChunkEvidence(
        "s",
        "b",
        "c",
        "table" if cells else "paragraph",
        None,
        (),
        (UnitEvidence("kept", raw, 1, None, cells),),
        raw,
        (),
        (("kept", 0, len(raw)),),
        True,
    )
    if kind == "header":
        other = "TAMPERED HEADER"
        ordinal = 1
        other_loc = {"page": 1, "bbox": [0, 10, 100, 30]}
        reasons = ["header_repeated_geometric"]
        status = UnitStatus.NOISE.value
    elif kind == "continuation":
        other = "伪造的续接。"
        ordinal = 3
        other_loc = {"page": 1, "bbox": [0, 40, 100, 50]}
        reasons = ["disclaimer_section"]
        status = UnitStatus.NOISE.value
    else:
        other = "资料来源：测试；注1：口径被篡改"
        ordinal = 3
        other_loc = {"page": 1, "bbox": [0, 42, 100, 50]}
        reasons = []
        status = UnitStatus.KEPT.value
    rows = [
        ("b", "kept", 2, raw, loc, sha256_of_bytes(raw.encode()), UnitStatus.KEPT.value, []),
        ("b", "extra", ordinal, other, other_loc, "0" * 64, status, reasons),
    ]

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute(self, *args):
            pass

        def fetchall(self):
            return rows

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def transaction(self):
            return nullcontext()

        def cursor(self):
            return Cursor()

    with (
        patch("psycopg.connect", return_value=Conn()),
        patch("plugins.corpus.preparation.read_pg._check_target"),
        pytest.raises(IntegrityError),
    ):
        cb.aggregate_band_chunks("fake", (ev,))
