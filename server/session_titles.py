"""Short research labels derived locally from the user's request."""

import re

PLACEHOLDER_TITLES = ("新对话", "新研究", "未命名研究", "")


def research_title(content: str, *, limit: int = 60) -> str | None:
    """Return a concise request excerpt; greetings leave room for a later topic."""
    cleaned = " ".join(content.split()).strip()
    if not cleaned:
        return None
    greeting = re.sub(r"[\s，。！？,.!?~～]+", "", cleaned).lower()
    if greeting in {"你好", "您好", "你好呀", "你好啊", "嗨", "hello", "hi", "hey", "谢谢", "谢谢你"}:
        return None
    cleaned = re.sub(r"^(?:你好|您好)[，,！!。\s]+", "", cleaned)
    cleaned = re.sub(r"^(?:请帮我|请你帮我|帮我|麻烦你)\s*", "", cleaned)
    cleaned = re.sub(r"^#{1,6}\s+", "", cleaned).strip()
    if not cleaned:
        return None
    return cleaned if len(cleaned) <= limit else cleaned[: limit - 1].rstrip() + "…"
