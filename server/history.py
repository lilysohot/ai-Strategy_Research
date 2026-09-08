"""Multi-turn history backfill (T2.6).

Responsibilities:
  * ``render_session_history`` — turn a list of prior turns into a compact text
    block the next run's prompt is prefixed with, so the agent sees the whole
    conversation instead of a single isolated question.
  * ``turns_to_dicts`` — project SQLAlchemy ``Turn`` rows into plain dicts (role
    + content) so the renderer and callers never depend on the ORM model.

Design note: the *only* thing we feed the next run is the rendered history.
We deliberately do NOT read the workflow's internal message list (the runtime's
``state['messages']``) — that is an implementation detail of the pipeline and
must stay opaque to the server. The assistant turn written after a run is taken
solely from the worker's ``final_answer`` (with ``final_content`` / partial
handling), never from inside the workflow.
"""

from __future__ import annotations

from typing import Any

# Roles we render. Anything else (system, tool) is excluded from the visible
# conversation — the history is a user<->assistant transcript.
_USER_ROLE = "user"
_ASSISTANT_ROLE = "assistant"

_ROLE_LABELS = {
    _USER_ROLE: "User",
    _ASSISTANT_ROLE: "Assistant",
}


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
