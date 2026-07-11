from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable


CARD_RE = re.compile(r"\b(?:[2-9TJQKA][shdc])\b", re.IGNORECASE)


def stable_name_key(name: str) -> str:
    """Local deterministic key; it is never sent anywhere."""
    return hashlib.sha256(name.strip().casefold().encode("utf-8")).hexdigest()


def anonymize_names(text: str, hero_name: str | None, names: Iterable[str]) -> str:
    sanitized = text
    counter = 1
    for name in sorted({n for n in names if n}, key=len, reverse=True):
        label = "HERO" if hero_name and name.casefold() == hero_name.casefold() else f"VILLAIN_{counter}"
        if label.startswith("VILLAIN"):
            counter += 1
        sanitized = re.sub(re.escape(name), label, sanitized, flags=re.IGNORECASE)
    return sanitized


def sanitize_log_line(text: str, hero_name: str | None = None, names: Iterable[str] = ()) -> str:
    sanitized = anonymize_names(text, hero_name, names)
    return CARD_RE.sub("CARD", sanitized)[:500]

