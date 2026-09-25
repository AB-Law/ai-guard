"""Shared text-extraction helper for the two LangChain integrations
(langchain_middleware.py, langchain_handler.py) — not part of the public
API, just avoids duplicating the same fix in both places.
"""

from __future__ import annotations

from typing import Any


def extract_text(content: Any) -> str:
    """Newer/reasoning-style models (langchain-openai's Responses-API
    output, o-series, etc.) give AIMessage.content as a list of typed
    blocks — {"type": "reasoning", "encrypted_content": ...}, {"type":
    "text", "text": ...}, {"type": "function_call", ...} — not a plain
    string. A naive str(content) fallback sends that raw Python-list repr
    (including internal fields like encrypted_content) to the tower as the
    rationale/context, which is both unreadable and a worse groundedness
    signal than the model's actual text buried inside it. Pull out only the
    human-readable "text" blocks instead.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text" and block.get("text"):
                parts.append(str(block["text"]))
        return "\n".join(parts)
    return str(content) if content else ""
