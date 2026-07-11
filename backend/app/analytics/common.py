"""Small, dependency-free helpers shared by the analytics modules.

The analytics layer deliberately accepts mappings *and* light objects.  This
keeps it usable from tests, from Pydantic schemas and from SQLAlchemy rows
without coupling the formulas to the persistence layer.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any


MISSING = object()


def value(item: Any, *names: str, default: Any = None) -> Any:
    """Return the first present, non-``None`` field from a mapping/object."""

    if item is None:
        return default
    for name in names:
        candidate = MISSING
        if isinstance(item, Mapping):
            candidate = item.get(name, MISSING)
        elif hasattr(item, name):
            candidate = getattr(item, name)
        if candidate is not MISSING and candidate is not None:
            return candidate
    return default


def has_value(item: Any, *names: str) -> bool:
    """Whether at least one named field exists and is not ``None``."""

    return value(item, *names, default=MISSING) is not MISSING


def number(raw: Any, default: float = 0.0) -> float:
    """Convert common database/JSON numeric values without leaking NaNs."""

    if raw is None or isinstance(raw, bool):
        return default
    try:
        converted = float(Decimal(str(raw).strip().replace(",", ".")))
    except (InvalidOperation, ValueError, TypeError):
        return default
    if converted != converted or converted in (float("inf"), float("-inf")):
        return default
    return converted


def optional_number(raw: Any) -> float | None:
    if raw is None or isinstance(raw, bool):
        return None
    try:
        converted = float(Decimal(str(raw).strip().replace(",", ".")))
    except (InvalidOperation, ValueError, TypeError):
        return None
    if converted != converted or converted in (float("inf"), float("-inf")):
        return None
    return converted


def integer(raw: Any, default: int = 0) -> int:
    parsed = optional_number(raw)
    return default if parsed is None else int(parsed)


def boolean(raw: Any, default: bool = False) -> bool:
    if raw is None:
        return default
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        return bool(raw)
    lowered = str(raw).strip().casefold()
    if lowered in {"1", "true", "yes", "oui", "y", "o"}:
        return True
    if lowered in {"0", "false", "no", "non", "n"}:
        return False
    return default


def as_datetime(raw: Any) -> datetime | None:
    """Parse the formats emitted by the parser and common Winamax timestamps."""

    if raw is None:
        return None
    if isinstance(raw, datetime):
        parsed = raw
    elif isinstance(raw, date):
        parsed = datetime.combine(raw, datetime.min.time())
    elif isinstance(raw, (int, float)):
        try:
            parsed = datetime.fromtimestamp(raw, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    else:
        text = str(raw).strip()
        if not text:
            return None
        # ISO covers the normalized format used by the API.  ``Z`` needs an
        # explicit UTC offset for Python's parser on older supported versions.
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            parsed = None
            cleaned = text.removesuffix(" ET").removesuffix(" CET").strip()
            for fmt in (
                "%Y/%m/%d %H:%M:%S",
                "%Y-%m-%d %H:%M:%S",
                "%d/%m/%Y %H:%M:%S",
                "%d/%m/%Y %H:%M",
            ):
                try:
                    parsed = datetime.strptime(cleaned, fmt)
                    break
                except ValueError:
                    continue
            if parsed is None:
                return None
    # Comparisons between aware and naive values fail.  The database stores
    # naive UTC values, so normalize aware inputs to that representation.
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def sequence(raw: Any) -> list[Any]:
    if raw is None:
        return []
    if isinstance(raw, (str, bytes)):
        return [raw]
    if isinstance(raw, Sequence):
        return list(raw)
    try:
        return list(raw)
    except TypeError:
        return [raw]


def item_id(item: Any, fallback: Any = None) -> Any:
    return value(item, "hand_id", "tournament_id", "external_id", "id", default=fallback)


def metric(numerator: int | float, denominator: int | float) -> dict[str, Any]:
    """Return an auditable percentage with its numerator and denominator."""

    num = float(numerator)
    den = float(denominator)
    percentage = round((num / den) * 100.0, 2) if den > 0 else None
    return {
        "numerator": int(num) if num.is_integer() else num,
        "denominator": int(den) if den.is_integer() else den,
        "percentage": percentage,
    }


def round_money(raw: float) -> float:
    # Avoid binary noise in JSON while retaining cents (or centimes).
    return round(raw + 0.0, 2)

