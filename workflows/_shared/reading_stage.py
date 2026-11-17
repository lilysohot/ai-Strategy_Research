"""Wire the reading-checkpoint stage from profile configuration.

Three call sites need the same object — the single-agent loop, the team
coordinator and each team member — and they all read the same profile keys. Doing
that assembly once keeps the switch honest: one key decides, and a member that
somehow assembled a different stage from the coordinator would be a silent
inconsistency in what "reading checkpoint on" means.

Off by default. The stage makes an extra model call and rewrites history; nobody
should get that from a config they did not ask for.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from frontier_agent.core.runtime.reading.stage import (
    ReadingBudget,
    ReadingStage,
    ReadingStageConfig,
)

logger = logging.getLogger(__name__)

__all__ = ["READING_CHECKPOINT_KEY", "build_reading_stage"]

#: Profile key. Accepted values are ``on``/``true``/``1`` and their negatives.
READING_CHECKPOINT_KEY = "reading_checkpoint"

_TRUTHY = frozenset({"on", "true", "1", "yes"})
_FALSY = frozenset({"", "off", "false", "0", "no"})


def _as_int(value: Any, default: int, *, allow_zero: bool = False) -> int:
    """Parse a profile number, falling back on nonsense.

    ``allow_zero`` exists for ``keep_recent``, where 0 is a real answer ("no extra
    margin, trust the position rule") rather than an absent value. Treating it as
    absent silently restores the 6-message margin, which makes the stage look
    broken on a short history.
    """
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    if parsed > 0:
        return parsed
    return 0 if (allow_zero and parsed == 0) else default


def _as_float(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _is_off(value: Any) -> bool:
    """Whether an opt-in profile key was left off (absent counts as off)."""
    return str(value if value is not None else "").strip().lower() in _FALSY


def build_reading_stage(
    *,
    llm: Any,
    agent_cfg: dict[str, Any] | None,
    task_id: str,
    budget: ReadingBudget | None = None,
) -> ReadingStage | None:
    """Return a configured stage, or ``None`` when the profile did not ask for one.

    Import failures are logged and turned into ``None`` rather than raised: a
    deployment without the corpus plugin must still run, and a reading archive is
    an optimisation — the loop's own compaction remains the capacity backstop.

    ``budget`` carries the caller's deadline and delivery reserve. It defaults to
    the loop's own wall deadline, which is what makes a checkpoint decline when
    the turn can no longer afford it; without that, an optional archive can spend
    the time the answer needed.
    """
    if agent_cfg is not None and not isinstance(agent_cfg, Mapping):
        # A profile section that is not a mapping cannot be read for the key, and
        # guessing would enable history rewriting from an unknown source.
        logger.warning(
            "reading checkpoint needs a mapping profile section, got %s; disabled",
            type(agent_cfg).__name__,
        )
        return None
    cfg: Mapping[str, Any] = agent_cfg if agent_cfg is not None else {}
    raw = str(cfg.get(READING_CHECKPOINT_KEY, "off")).strip().lower()
    if raw in _FALSY:
        return None
    if raw not in _TRUTHY:
        logger.warning("unknown %s value %r; treating it as off", READING_CHECKPOINT_KEY, raw)
        return None
    if llm is None:
        logger.warning("reading checkpoint requested without an LLM; disabled")
        return None

    try:
        from plugins.corpus.reading_extractor import (
            DEFAULT_DIGEST_BUDGET,
            CorpusReadingExtractor,
            default_checkpoint_store,
        )
        from plugins.corpus.statement_scope import scope_issues
        from plugins.corpus.tool_refs import resolve_evidence_reference
    except ImportError as exc:  # pragma: no cover - optional dependency
        logger.warning("reading checkpoint unavailable: %s", exc)
        return None

    stage_config = ReadingStageConfig(
        enabled=True,
        min_body_chars=_as_int(cfg.get("reading_checkpoint_min_body_chars"), 4_000),
        working_set_limit=_as_int(cfg.get("reading_checkpoint_working_set"), 40_000),
        keep_recent_messages=_as_int(
            cfg.get("reading_checkpoint_keep_recent"),
            6,
            allow_zero=True,
        ),
        record_limit=_as_int(cfg.get("reading_checkpoint_record_limit"), 4_000),
        max_findings=_as_int(cfg.get("reading_checkpoint_max_findings"), 24),
        archive_max_chars=_as_int(cfg.get("reading_checkpoint_archive_chars"), 3_000),
        max_attempts=_as_int(cfg.get("reading_checkpoint_attempts"), 2),
        total_timeout_s=_as_float(cfg.get("reading_checkpoint_timeout_s"), 60.0),
        min_remaining_budget_s=_as_float(
            cfg.get("reading_checkpoint_min_remaining_s"),
            45.0,
        ),
        min_attempt_s=_as_float(cfg.get("reading_checkpoint_min_attempt_s"), 5.0),
        # Absent means "do not pay twice for the same unchanged bodies"; a profile
        # opts back into retrying with ``reading_checkpoint_retry_same_input: on``.
        skip_unchanged_failed_input=_is_off(
            cfg.get("reading_checkpoint_retry_same_input"),
        ),
        # A statement that drops the source's own scope limiter widens the claim,
        # and an installed record is what replaces the body it came from. On by
        # default; a profile that wants structure-only validation sets
        # ``reading_checkpoint_scope_gate: off``. ``_is_off`` is "off or absent",
        # so the default has to be spelled out here rather than inferred from it.
        statement_check=(
            None
            if str(cfg.get("reading_checkpoint_scope_gate", "on")).strip().lower() in _FALSY
            else scope_issues
        ),
    )
    extractor = CorpusReadingExtractor(
        llm=llm,
        resolve=resolve_evidence_reference,
        digest_budget=_as_int(
            cfg.get("reading_checkpoint_digest_chars"),
            DEFAULT_DIGEST_BUDGET,
        ),
    )
    return ReadingStage(
        extractor=extractor,
        store=default_checkpoint_store(),
        config=stage_config,
        task_id=task_id,
        budget=budget,
        # The resolver is the same receipt store the refs were written to, so a
        # ref that cannot be read now is a dead pointer and the checkpoint is
        # refused rather than installed with an unusable citation.
        resolve=resolve_evidence_reference,
    )
