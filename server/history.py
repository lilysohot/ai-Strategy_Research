"""Web conversation persistence helpers.

Cross-turn model continuity has one carrier: the previous run's message list.
Since issue 01 §11 (S2), the authoritative copy is the session row in
``session_conversations``. The orchestrator writes it when a run ends and reads
it by primary key for the next turn; ``prior_conversation.json`` is only a
per-run staging copy. The server transports the payload without parsing or
depending on the workflow's internal message shape. The workflow validates it
and decides whether to replay it.

The ``turns`` table remains the Web presentation and audit transcript. It is not
rendered back into model input: the old ``history.txt`` / ``conversation_history``
carrier was retired in issue 01 S4.

The assistant turn written after a run is still taken solely from the worker's
``final_answer`` (with ``final_content`` / partial handling), never from inside
the workflow. See ``.scratch/web-business-context/issues/01-context-inheritance.md``
§9.12 (the boundary) and §11 (where the carrier lives now).
"""

from __future__ import annotations

from typing import Any

#: Prefix marking a transcript row that was not a submitted question but a
#: mid-run direction the user injected through ``POST /api/runs/{id}/steer``
#: (F21). It is written only when the steer was actually adopted, and it is the
#: presentation/audit record for the direction. Model continuity is carried by
#: the workflow's complete message list in ``session_conversations``.
#:
#: Deliberately a plain content prefix rather than a new column: the transcript
#: schema stays as it is, the text is still literally what the user wrote, and
#: the structured facts (who, when, adopted at which turn) live in
#: ``control_records``.
STEER_TURN_PREFIX = "[运行中补充方向] "


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


#: Run-relative location of the runtime's conversation dump (this run's own
#: message list, written by the workflow's observer). Single source of truth so
#: the writer and the ingest step that reads it cannot drift.
CONVERSATION_DUMP_RELPATH: tuple[str, ...] = ("run", "conversation.json")

#: Workflow-neutral export written by the worker after the native dump is
#: complete. The parent stores these bytes beside the immutable native source;
#: it never renders this value back into a prompt itself.
CROSS_MODE_CONTEXT_RELPATH: tuple[str, ...] = ("run", "cross_mode_context.json")

#: Ephemeral worker staging file containing portable archived contexts. The
#: worker validates, binds, and unlinks it before any model-controlled tool can
#: run; it is never a prompt carrier and is not persisted as a Run artifact.
RESEARCH_HISTORY_STAGE = "prior_research_history.json"
