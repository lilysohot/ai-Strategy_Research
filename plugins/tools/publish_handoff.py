"""Publish a private team-member file as a controlled shared reference."""

from __future__ import annotations

import asyncio
import json

from frontier_agent.core.tool import ToolOutcome, tool
from plugins.tools._handoff import publish_file


@tool
async def publish_handoff(source_path: str, label: str = "") -> str | ToolOutcome:
    """Publish one private workspace file for another team member to read.

    The file is copied into the task-scoped, content-addressed handoff store.
    The returned ``ref`` is stable, includes a verified SHA-256 version, and is
    read-only to model commands. Put that exact ``ref`` in
    ``submit_report(attachments=[...])``. This tool never publishes a user
    deliverable and cannot read arbitrary host paths.

    Args:
        source_path: File inside this member's private ``/workspace``.
        label: Short logical name such as ``screening-results``. Re-publishing
            changed content under the same label creates another digest version.

    Returns:
        JSON provenance record containing ``ref``, SHA-256, size, producer,
        job id, logical label, and content version.
    """
    try:
        payload = await asyncio.to_thread(publish_file, source_path, label)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        return ToolOutcome(f"Error: publish_handoff rejected: {exc}", is_error=True)
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


__all__ = ["publish_handoff"]
