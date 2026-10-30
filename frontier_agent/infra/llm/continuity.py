"""Isolated auxiliary client settings for bounded continuation memories."""

from __future__ import annotations

from copy import deepcopy
from typing import Any
from urllib.parse import urlparse

from frontier_agent.infra.llm.aux_builder import build_aux_llm


def continuity_client(llm: Any, config: dict[str, Any] | None) -> Any:
    """Keep the main model unchanged; disable only supported summary reasoning."""
    if not config or not config.get("model") or not config.get("base_url"):
        return llm
    cfg = deepcopy(config)
    host = (urlparse(str(cfg["base_url"])).hostname or "").lower()
    model = str(cfg["model"]).lower()
    extra = cfg.setdefault("extra_body", {})
    # Ark's documented DeepSeek V4 Chat API supports this native switch.
    # Do not send it to unknown models/protocols, or guess from role text.
    # https://docs.volcengine.com/docs/ark/deep-thinking?lang=en
    native_switch = (host == "volces.com" or host.endswith(".volces.com")) and model.startswith(
        "deepseek-v4"
    )
    template = extra.get("chat_template_kwargs")
    if native_switch:
        extra["thinking"] = {"type": "disabled"}
        extra.pop("reasoning_effort", None)
    elif not (isinstance(template, dict) and "enable_thinking" in template):
        return llm
    if isinstance(template, dict):
        template["enable_thinking"] = False
        template["preserve_thinking"] = False
    cfg["enable_thinking"] = False
    cfg["max_tokens"] = 1024
    cfg["max_completion_tokens"] = 1024
    cfg.pop("fallback", None)
    return build_aux_llm(cfg)
