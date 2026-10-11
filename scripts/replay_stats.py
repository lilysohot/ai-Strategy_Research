"""Per-turn cross-turn replay / cache statistics (issue 01 §10.2 S1-a).

Read-only. Answers, per turn of one conversation: did this run replay the
previous turn's messages, how big was the window it replayed, and how much of
the prompt the provider billed as a cache read.

    uv run python scripts/replay_stats.py --session <session-or-research-uuid>
    uv run python scripts/replay_stats.py --runs-root <runs-root>
    uv run python scripts/replay_stats.py --session <uuid> --json

Why a script and not a query: the numbers this has to line up — prompt tokens,
``cache_read_tokens`` and the replay decision — live in three places (the Run
row's counters, its ``usage_json.replay`` block, and the run's own
``summary.json`` / trajectory on disk). Reading them with one fixed definition
is what makes "94% of the previous turn was reused" reproducible instead of
retold.

Definitions, so the arithmetic cannot drift:

* ``reuse%`` = this turn's ``cache_read_tokens`` / the **previous turn's**
  ``prompt_tokens``, computed **within one conversation**. Rows are grouped by
  session; the first turn of a session (and any turn whose session is unknown,
  because a directory source cannot name it) reports no ratio instead of a
  fabricated 0%.
* ``window`` describes what the *previous* run handed over, as the reader saw it
  (``messages`` / ``prior_turns`` / estimated tokens). It is a local fact, not a
  provider claim; ``est_tokens`` is 0 for dumps written before that field existed.
* A turn whose usage could not be metered is flagged and excluded from the mean
  (``server.usage`` reports ``status`` for exactly this reason).

The directory source takes each run's session id from its own conversation dump,
so a runs root holding several conversations still gets per-conversation
arithmetic rather than a root-wide average. A run with no dump has no verifiable
session, so it is treated as its own group — a wrong denominator is worse than no
number.

Control arms legitimately reuse the shared prefix (system prompt + tool
schemas), so a non-zero ``reuse%`` on a run that never replayed is expected, not
a bug — this tool reports; it does not judge.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

#: Run-relative locations, as ``server.config.build_run_paths`` lays them out.
_SUMMARY_RELPATH = ("run", "summary.json")
_TRAJECTORY_RELPATH = ("run", "agent", "trajectories", "react_agent.jsonl")
_DUMP_RELPATH = ("run", "conversation.json")


@dataclass(frozen=True)
class TurnStat:
    """One run of one conversation, as the board reads it."""

    turn: int
    run_id: str
    source: str
    session_id: str
    prompt_tokens: int
    cache_read_tokens: int
    llm_calls: int
    usage_status: str
    decision: str
    reason: str
    prior_turns: int
    messages: int
    est_tokens: int
    payload_bytes: int
    stopped_by: str
    error: str = ""

    @property
    def replayed(self) -> bool:
        return self.decision == "used"


def _replay_of(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Pull the replay block out of a ``usage_json`` / summary payload."""
    if not isinstance(payload, dict):
        return {}
    replay = payload.get("replay")
    return replay if isinstance(replay, dict) else {}


def _turn_stat(
    index: int,
    *,
    run_id: str,
    source: str,
    session_id: str,
    usage: dict[str, Any],
    replay: dict[str, Any],
    error: str = "",
) -> TurnStat:
    return TurnStat(
        turn=index,
        run_id=run_id,
        source=source,
        session_id=session_id,
        prompt_tokens=int(usage.get("prompt_tokens", 0) or 0),
        cache_read_tokens=int(usage.get("cache_read_tokens", 0) or 0),
        llm_calls=int(usage.get("llm_calls", 0) or 0),
        usage_status=str(usage.get("status") or ""),
        decision=str(replay.get("decision") or ""),
        reason=str(replay.get("reason") or ""),
        prior_turns=int(replay.get("prior_turns", 0) or 0),
        messages=int(replay.get("messages", 0) or 0),
        est_tokens=int(replay.get("est_tokens", 0) or 0),
        payload_bytes=int(replay.get("payload_bytes", 0) or 0),
        stopped_by=str(replay.get("stopped_by") or ""),
        error=error,
    )


async def load_from_db(session_id: str) -> list[TurnStat]:
    """Every Run of one session, oldest first, with its window statistics."""
    from sqlalchemy import select

    from server.store import Run, get_sessionmaker

    sid = uuid.UUID(session_id)
    async with get_sessionmaker()() as session:
        rows = (
            (
                await session.execute(
                    select(Run).where(Run.session_id == sid).order_by(Run.created_at)
                )
            )
            .scalars()
            .all()
        )

    stats: list[TurnStat] = []
    for index, row in enumerate(rows, start=1):
        usage_json = dict(row.usage_json or {})
        stats.append(
            _turn_stat(
                index,
                run_id=row.id.hex,
                source="db",
                session_id=row.session_id.hex,
                usage={
                    "prompt_tokens": row.prompt_tokens,
                    "cache_read_tokens": row.cache_read_tokens,
                    "llm_calls": row.llm_calls,
                    "status": usage_json.get("status"),
                },
                replay=_replay_of(usage_json),
                error=str(row.error or ""),
            )
        )
    return stats


def _summary_path(run_dir: Path) -> Path | None:
    """The run's ``summary.json``: at the run root, or under ``run/``.

    ``build_run_paths`` puts it at ``<run>/summary.json`` (``run/`` holds the
    trial's own files: agent trajectories, engine log, conversation dump). The
    ``run/`` fallback exists so a layout change cannot silently empty the board —
    this tool reports, so a missed file would read as "no decision".
    """
    for relpath in (("summary.json",), _SUMMARY_RELPATH):
        candidate = run_dir.joinpath(*relpath)
        if candidate.is_file():
            return candidate
    return None


def _session_from_dump(run_dir: Path) -> str:
    """The session a run belongs to, read from its own conversation dump.

    Returns ``""`` when the run left no dump (pre-dating continuity, or the
    workflow reported no messages). The caller then treats the run as its own
    group rather than inventing a session — reuse measured against an unrelated
    conversation's prompt is not a lower number, it is a wrong one.
    """
    path = run_dir.joinpath(*_DUMP_RELPATH)
    if not path.is_file():
        return ""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return str(document.get("session_id") or "") if isinstance(document, dict) else ""


def load_from_runs_root(runs_root: Path) -> list[TurnStat]:
    """Every run directory that carries a summary, oldest first by mtime.

    Directory source, so the board can be produced from a runs root (or a
    restored copy) with no database at all — the same numbers, read from the
    files the run itself wrote.
    """
    from server.usage import aggregate_usage

    candidates: list[tuple[float, Path]] = []
    for entry in runs_root.iterdir() if runs_root.is_dir() else []:
        if not entry.is_dir():
            continue
        summary = _summary_path(entry)
        if summary is not None:
            candidates.append((summary.stat().st_mtime, entry))
    candidates.sort(key=lambda item: item[0])

    stats: list[TurnStat] = []
    for index, (_, run_dir) in enumerate(candidates, start=1):
        summary_file = _summary_path(run_dir)
        assert summary_file is not None  # only candidates were collected
        summary = json.loads(summary_file.read_text(encoding="utf-8"))
        trajectory = run_dir.joinpath(*_TRAJECTORY_RELPATH)
        records: list[dict[str, Any]] = []
        if trajectory.is_file():
            for line in trajectory.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except ValueError:
                    continue
        usage = dict(aggregate_usage(records))
        # Same three-way verdict as ``server.usage.usage_for_run`` so the two
        # sources cannot disagree about whether a run was metered at all.
        if not records:
            usage["status"] = "unavailable"
        elif not usage["llm_calls"]:
            usage["status"] = "partial"
        else:
            usage["status"] = "complete"
        stats.append(
            _turn_stat(
                index,
                run_id=run_dir.name,
                source="dir",
                session_id=_session_from_dump(run_dir),
                usage=usage,
                replay=_replay_of(summary),
                error=str(summary.get("error") or ""),
            )
        )
    return stats


def _session_key(turn: TurnStat) -> str:
    """Grouping key: the session, or the run itself when the session is unknown."""
    return turn.session_id or f"@{turn.run_id}"


def summarise(turns: list[TurnStat]) -> dict[str, Any]:
    """Aggregate the board: reuse per conversation, replays, and skip reasons.

    ``reuse`` is ``None`` — never ``0.0`` — for a turn with no predecessor in its
    conversation and for a turn whose usage could not be metered. That distinction
    is the whole reason ``usage_status`` exists (see ``server.usage``): an
    unmetered run reported as "0% reuse" is indistinguishable from one that
    genuinely reused nothing, and would drag the mean down as if it were a
    measurement.
    """
    rows: list[dict[str, Any]] = [{**asdict(turn), "reuse": None} for turn in turns]
    groups: dict[str, list[int]] = {}
    for index, turn in enumerate(turns):
        groups.setdefault(_session_key(turn), []).append(index)

    reuse_values: list[float] = []
    sessions: list[dict[str, Any]] = []
    for indexes in groups.values():
        previous_prompt: int | None = None
        session_reuse: list[float] = []
        bucket: dict[str, Any] = {
            "session_id": turns[indexes[0]].session_id,
            # A run with no dump has no session to name; label it by run so the
            # per-session block does not print several identical "unknown" rows.
            "label": ((turns[indexes[0]].session_id or f"run {turns[indexes[0]].run_id[:8]}")[:10]),
            "runs": len(indexes),
            "replayed": 0,
        }
        for index in indexes:
            turn = turns[index]
            metered = turn.usage_status in ("complete", "")
            if previous_prompt and metered:
                value = turn.cache_read_tokens / previous_prompt
                rows[index]["reuse"] = value
                session_reuse.append(value)
                reuse_values.append(value)
            # Only a metered prompt can be the next turn's denominator; an
            # unmetered run must not displace the real one.
            if metered and turn.prompt_tokens:
                previous_prompt = turn.prompt_tokens
            if turn.replayed:
                bucket["replayed"] += 1
        bucket["mean_reuse"] = sum(session_reuse) / len(session_reuse) if session_reuse else None
        sessions.append(bucket)

    reasons: dict[str, int] = {}
    for turn in turns:
        if turn.decision == "skipped":
            key = turn.reason or "unspecified"
            reasons[key] = reasons.get(key, 0) + 1

    return {
        "turns": rows,
        "summary": {
            "runs": len(turns),
            "replayed": sum(1 for t in turns if t.replayed),
            "skipped": sum(1 for t in turns if t.decision == "skipped"),
            "no_decision": sum(1 for t in turns if not t.decision),
            "skip_reasons": reasons,
            "mean_reuse": (sum(reuse_values) / len(reuse_values) if reuse_values else None),
            "sessions": sessions,
            "total_prompt_tokens": sum(t.prompt_tokens for t in turns),
            "total_cache_read_tokens": sum(t.cache_read_tokens for t in turns),
            "unmetered": [t.run_id for t in turns if t.usage_status not in ("complete", "")],
        },
    }


def render(board: dict[str, Any]) -> str:
    """A fixed-column table plus the aggregate block."""
    lines = [
        f"{'turn':>4}  {'session':<10}  {'run':<12}  {'prompt':>9}  {'cache_read':>10}  "
        f"{'reuse':>6}  {'replay':<26}  window"
    ]
    for row in board["turns"]:
        reuse = "-" if row["reuse"] is None else f"{row['reuse'] * 100:.1f}%"
        if row["decision"] == "used":
            replay = f"used ({row['prior_turns']} turns)"
        elif row["decision"] == "skipped":
            replay = f"skipped: {row['reason']}"
        else:
            replay = "-"
        window = f"{row['messages']} msg / {row['est_tokens']} tok" if row["messages"] else "-"
        flag = "" if row["usage_status"] in ("complete", "") else f" [{row['usage_status']}]"
        session = (row["session_id"] or "-")[:10]
        lines.append(
            f"{row['turn']:>4}  {session:<10}  {row['run_id'][:12]:<12}  "
            f"{row['prompt_tokens']:>9}  {row['cache_read_tokens']:>10}  "
            f"{reuse:>6}  {replay:<26}  {window}{flag}"
        )

    summary = board["summary"]
    sessions = summary["sessions"]
    lines.append("")
    lines.append(
        f"{summary['runs']} run(s) in {len(sessions)} session(s); replayed "
        f"{summary['replayed']}, skipped {summary['skipped']}, "
        f"no decision {summary['no_decision']}"
    )
    if len(sessions) == 1:
        mean = summary["mean_reuse"]
        lines.append(
            f"mean reuse of the previous prompt: {'n/a' if mean is None else f'{mean * 100:.1f}%'}"
        )
    else:
        # A root-wide average across conversations would be a number about
        # nothing; per conversation is the same arithmetic the rows use.
        lines.append("mean reuse per session:")
        for bucket in sessions:
            mean = bucket["mean_reuse"]
            lines.append(
                f"  {bucket['label']:<10}  {bucket['runs']:>3} run(s)  "
                f"replayed {bucket['replayed']:>2}  "
                f"reuse {'n/a' if mean is None else f'{mean * 100:.1f}%'}"
            )
    lines.append(
        f"prompt {summary['total_prompt_tokens']} / cache_read {summary['total_cache_read_tokens']}"
    )
    if summary["skip_reasons"]:
        lines.append("skip reasons:")
        for reason, count in sorted(summary["skip_reasons"].items(), key=lambda kv: -kv[1]):
            lines.append(f"  {count:>4}  {reason}")
    if summary["unmetered"]:
        lines.append(
            "unmetered (usage unavailable/partial, printed above as flags): "
            + ", ".join(summary["unmetered"])
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--session", help="session (research) uuid; reads the database")
    source.add_argument("--runs-root", type=Path, help="a runs root; reads run directories")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--top", type=int, default=0, help="keep only the newest N turns (0 = all)")
    args = parser.parse_args(argv)

    if args.session:
        try:
            turns = asyncio.run(load_from_db(args.session))
        except (ValueError, OSError) as exc:
            print(
                f"cannot read session {args.session}: {type(exc).__name__}: {exc}", file=sys.stderr
            )
            return 2
    else:
        turns = load_from_runs_root(args.runs_root)

    if args.top > 0:
        turns = turns[-args.top :]

    board = summarise(turns)
    if args.json:
        print(json.dumps(board, ensure_ascii=False, indent=2))
    else:
        print(render(board))
    # Read-only tool: a non-zero exit means "nothing was found", never "bad data".
    return 0 if turns else 1


if __name__ == "__main__":
    raise SystemExit(main())
