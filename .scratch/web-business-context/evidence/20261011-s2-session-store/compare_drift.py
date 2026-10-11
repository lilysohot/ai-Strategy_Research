"""Compare two ``alembic check`` outputs as operation sets (issue 01 §11.5).

Why a differential: this checkout's models and its deployed schema have drifted
apart over many revisions (~40 historical operations report on every run), so
"``alembic check`` is clean" is not a usable acceptance criterion. What *is*
usable is the delta: adding revision 0019 must make exactly one operation
disappear — the ``session_conversations`` create — and change nothing else.

    uv run python .scratch/web-business-context/evidence/20261011-s2-session-store/compare_drift.py \
        before.txt after.txt

Prints the (op, table) sets and their differences; exits 0 only when the delta is
exactly the expected one (see ``EXPECTED_REMOVED``).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

#: The operation the new revision should retire from the check output.
EXPECTED_REMOVED = {("add_table", "session_conversations")}

# Alembic names a whole-table operation ``('add_table', Table('name', ...))``; a
# column-level one is ``('modify_type', None, 'artifacts', 'size', {...})``; an
# index is ``('remove_index', Index('idx_runs_session', ...))``.
_OP_ADD_TABLE = re.compile(r"\('(add_table|remove_table)',\s*Table\('(\w+)'")
_OP_TABLE = re.compile(r"\('(\w+)',\s*None,\s*'(\w+)'")
_OP_INDEX = re.compile(r"\('(add_index|remove_index)',\s*Index\('(\w+)'")
_OP_CONSTRAINT = re.compile(r"\('(add_constraint|remove_constraint)',\s*\w+Constraint\(")


def operations(text: str) -> set[tuple[str, str]]:
    """The (op, table/name) pairs a check output mentions, order-insensitive.

    Coarse on purpose: two runs of the same comparison must produce the same set
    even though alembic prints one giant nested list with dict payloads.
    """
    found: set[tuple[str, str]] = set()
    for op, table in _OP_ADD_TABLE.findall(text):
        found.add((op, table))
    for op, table in _OP_TABLE.findall(text):
        found.add((op, table))
    for op, index in _OP_INDEX.findall(text):
        found.add((op, index))
    for op in _OP_CONSTRAINT.findall(text):
        found.add((op, "<constraint>"))
    return found


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__.splitlines()[0])
        return 2
    before = operations(Path(argv[1]).read_text(encoding="utf-8"))
    after = operations(Path(argv[2]).read_text(encoding="utf-8"))

    removed = before - after
    added = after - before
    print(f"before: {len(before)} operation(s)")
    print(f"after:  {len(after)} operation(s)")
    print(f"removed by the revision: {sorted(removed)}")
    print(f"added by the revision:   {sorted(added)}")

    if removed == EXPECTED_REMOVED and not added:
        print("\nOK: the revision retired exactly the new table's create operation.")
        return 0
    print(
        "\nFAIL: expected the delta to be exactly "
        f"{sorted(EXPECTED_REMOVED)} with nothing added.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
