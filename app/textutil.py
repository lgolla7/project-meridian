"""Shared normalization for matching names across drawings and the BOM."""

from __future__ import annotations

import re

_STOP = {
    "a", "an", "the", "of", "for", "and", "or", "to", "in", "on", "with",
    "what", "which", "who", "how", "is", "are", "was", "were", "does", "do",
    "me", "about", "tell", "show", "please", "from", "that", "this", "its",
    "part", "parts", "drawing", "drawings", "bom", "machine",
}


def fold(value: str) -> str:
    """Lowercase and strip accents that show up in Danish titles."""
    text = (value or "").lower().replace("ø", "o").replace("æ", "ae").replace("å", "a")
    text = text.replace("–", "-")
    return text


def normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", fold(value)).strip()


def tokens(value: str) -> list[str]:
    return [tok for tok in normalize(value).split() if tok and tok not in _STOP]


def compact(value: str) -> str:
    """Ignore spaces so a wrapped PDF line still contains the quote."""
    return re.sub(r"\s+", "", fold(value)).replace(".", ",")


def quote_in_text(quote: str, text: str) -> bool:
    if quote.lower() in text.lower():
        return True
    return compact(quote) in compact(text)


def snippet(text: str, needle: str = "", limit: int = 220) -> str:
    raw = " ".join((text or "").split())
    if not raw:
        return ""
    if needle:
        idx = raw.lower().find(needle.lower())
        if idx < 0:
            idx = compact(raw).find(compact(needle))
        if idx >= 0:
            start = max(0, idx - 40)
            return raw[start:start + limit].strip()
    return raw[:limit].strip()
