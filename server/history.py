"""Multi-turn history backfill (T2.6).

Responsibilities:
  * ``render_session_history`` — turn a list of prior turns into a compact text
    block the next run's prompt is prefixed with, so the agent sees the whole
    conversation instead of a single isolated question.
  * ``turns_to_dicts`` — project SQLAlchemy ``Turn`` rows into plain dicts (role
    + content) so the renderer and callers never depend on the ORM model.
  * ``resolve_prior_conversation`` — find the previous run's *conversation dump*
    (``<run_dir>/run/conversation.json``) so the orchestrator can copy it into
    the next run.

Design note: cross-turn continuity rides on two carriers, and the server's role
differs for each.

  * **presentation** — the rendered transcript above; plain text the next run's
    prompt shows as "conversation so far".
  * **continuity** — the previous run's own message list, dumped by the runtime
    and transported here as an opaque **byte** copy (see
    ``resolve_prior_conversation``). The server never parses its content, never
    reads the runtime's ``state['messages']``, and never depends on the
    pipeline's internal message shape: the next run's workflow validates the
    dump and decides whether to replay it.

The assistant turn written after a run is still taken solely from the worker's
``final_answer`` (with ``final_content`` / partial handling), never from inside
the workflow. Owning the message sequence outright is scheduled for a later phase
(server-side storage); until then the dump is the continuity carrier. See
``.scratch/web-business-context/issues/01-context-inheritance.md`` §9.12.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

# Roles we render. Anything else (system, tool) is excluded from the visible
# conversation — the history is a user<->assistant transcript.
_USER_ROLE = "user"
_ASSISTANT_ROLE = "assistant"

_ROLE_LABELS = {
    _USER_ROLE: "User",
    _ASSISTANT_ROLE: "Assistant",
}

#: Prefix marking a transcript row that was not a submitted question but a
#: mid-run direction the user injected through ``POST /api/runs/{id}/steer``
#: (F21). It is written only when the steer was actually adopted, and it is the
#: reason a later run sees the user's correction at all: history is rendered
#: from ``turns``, so an adopted steer that never became a turn would be
#: invisible to every subsequent run.
#:
#: Deliberately a plain content prefix rather than a new column: the transcript
#: schema stays as it is, the text is still literally what the user wrote, and
#: the structured facts (who, when, adopted at which turn) live in
#: ``control_records``.
STEER_TURN_PREFIX = "[运行中补充方向] "


def turns_to_dicts(turns: list[Any]) -> list[dict[str, str]]:
    """Project ``Turn`` rows (or dicts) to ``[{"role", "content"}]`` in seq order."""
    out: list[dict[str, str]] = []
    for t in turns:
        role = t.role if hasattr(t, "role") else t.get("role")
        content = t.content if hasattr(t, "content") else t.get("content")
        if role is None or content is None:
            continue
        out.append({"role": str(role), "content": str(content)})
    return out


def render_session_history(
    turns: list[Any],
    *,
    limit: int | None = None,
) -> str:
    """Render prior turns as a transcript block for the next run's prompt.

    The output is a plain markdown-ish transcript::

        ## Conversation so far
        User: <message>
        Assistant: <answer>
        ...

    Returns ``""`` when there are no user/assistant turns (the caller then skips
    prefixing the prompt entirely). ``limit`` keeps only the most recent N turns
    when the thread is long.
    """
    dicts = turns_to_dicts(turns)
    if limit is not None and len(dicts) > limit:
        dicts = dicts[-limit:]

    lines: list[str] = []
    for entry in dicts:
        label = _ROLE_LABELS.get(entry["role"])
        if label is None:
            continue
        text = entry["content"].strip()
        if not text:
            continue
        lines.append(f"{label}: {text}")

    if not lines:
        return ""
    return "## Conversation so far\n" + "\n".join(lines)


def extract_final_answer(state_or_summary: dict[str, Any]) -> str:
    """Pull the assistant's reply from a worker result.

    Accepts either a worker ``summary.json`` dict or a pipeline ``state`` dict.
    Prefers ``final_answer``; falls back to ``final_content`` (which may itself
    be a dict with a ``content`` field, or a bare string). Never raises on a
    missing key — returns ``""`` so the caller can decide how to handle an empty
    answer.
    """
    if not isinstance(state_or_summary, dict):
        return ""

    value = state_or_summary.get("final_answer")
    if isinstance(value, str) and value.strip():
        return value.strip()

    # final_content may carry the answer when the pipeline returns a structured
    # result instead of a flat final_answer string.
    content = state_or_summary.get("final_content")
    if isinstance(content, dict):
        content = content.get("content")
    if isinstance(content, str) and content.strip():
        return content.strip()

    # Last-resort fallbacks used by some pipeline shapes.
    for key in ("report", "answer", "output"):
        alt = state_or_summary.get(key)
        if isinstance(alt, str) and alt.strip():
            return alt.strip()
        if isinstance(alt, dict):
            alt_text = alt.get("content") or alt.get("text")
            if isinstance(alt_text, str) and alt_text.strip():
                return alt_text.strip()

    return ""


#: Run-relative location of the runtime's conversation dump (the previous run's
#: own message list). Single source of truth so writer and reader cannot drift.
CONVERSATION_DUMP_RELPATH: tuple[str, ...] = ("run", "conversation.json")


def resolve_prior_conversation(
    turns: list[Any],
    *,
    current_run_id: Any = None,
    path_for: Callable[[str], Path] | None = None,
) -> Path | None:
    """Locate the newest prior run's conversation dump, or ``None``.

    Looked up by **file existence only** — the server transports the file
    verbatim and never parses it (see the module design note). Runs are visited
    newest-first and turns sharing a run are collapsed, so a long transcript does
    not re-stat one directory per turn. Turns without a ``run_id`` (steers,
    imported rows) and the run being submitted are skipped.
    """
    if not turns:
        return None
    if path_for is None:
        from server.config import run_dir_for

        path_for = run_dir_for

    current = _run_id_hex(current_run_id)
    seen: set[str] = set()
    for turn in reversed(turns):
        raw_run_id = turn.get("run_id") if isinstance(turn, dict) else getattr(turn, "run_id", None)
        run_hex = _run_id_hex(raw_run_id)
        if not run_hex or run_hex == current or run_hex in seen:
            continue
        seen.add(run_hex)
        candidate = Path(path_for(run_hex)).joinpath(*CONVERSATION_DUMP_RELPATH)
        if candidate.is_file():
            return candidate
    return None


def _run_id_hex(run_id: Any) -> str:
    """Normalise a run id (UUID or either spelling of the string form) to hex."""
    if run_id is None:
        return ""
    if isinstance(run_id, uuid.UUID):
        return run_id.hex
    try:
        return uuid.UUID(str(run_id)).hex
    except (ValueError, AttributeError, TypeError):
        return str(run_id)
