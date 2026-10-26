"""Small formatting and parsing helpers shared by every command."""

from __future__ import annotations

import re

SIZE_UNITS = ("B", "KB", "MB", "GB", "TB", "PB", "EB")

_SIZE_SCALES = {
    "": 1,
    "b": 1,
    "k": 1024,
    "kb": 1024,
    "kib": 1024,
    "m": 1024**2,
    "mb": 1024**2,
    "mib": 1024**2,
    "g": 1024**3,
    "gb": 1024**3,
    "gib": 1024**3,
    "t": 1024**4,
    "tb": 1024**4,
    "tib": 1024**4,
}

_DURATION_SCALES = {
    "s": 1,
    "sec": 1,
    "secs": 1,
    "second": 1,
    "seconds": 1,
    "m": 60,
    "min": 60,
    "mins": 60,
    "minute": 60,
    "minutes": 60,
    "h": 3600,
    "hr": 3600,
    "hour": 3600,
    "hours": 3600,
    "d": 86400,
    "day": 86400,
    "days": 86400,
    "w": 604800,
    "week": 604800,
    "weeks": 604800,
    "mo": 2_592_000,
    "month": 2_592_000,
    "months": 2_592_000,
    "y": 31_536_000,
    "year": 31_536_000,
    "years": 31_536_000,
}


def human_size(size: int) -> str:
    """Format a byte count the way `ls -lh` would, but shorter."""
    if size < 0:
        raise ValueError("size must not be negative")
    if size < 1024:
        return f"{size} B"
    value = float(size)
    unit = 0
    while value >= 1024 and unit < len(SIZE_UNITS) - 1:
        value /= 1024
        unit += 1
    if value >= 100:
        return f"{value:.0f} {SIZE_UNITS[unit]}"
    if value >= 10:
        return f"{value:.1f} {SIZE_UNITS[unit]}"
    return f"{value:.1f} {SIZE_UNITS[unit]}"


def parse_size(text: str) -> int:
    """Parse ``"10MB"``, ``"1.5 GiB"`` or ``"512"`` into bytes."""
    match = re.fullmatch(r"\s*(-?\d+(?:\.\d+)?)\s*([a-zA-Z]*)\s*", text or "")
    if not match:
        raise ValueError(f"not a size: {text!r}")
    number, unit = match.groups()
    scale = _SIZE_SCALES.get(unit.lower())
    if scale is None:
        raise ValueError(f"unknown size unit: {unit!r}")
    return int(float(number) * scale)


def human_age(seconds: float) -> str:
    """Format an age like ``"3d"``, ``"2mo"`` or ``"just now"``."""
    if seconds < 0:
        seconds = 0
    if seconds < 10:
        return "just now"
    if seconds < 60:
        return f"{int(seconds)}s"
    if seconds < 3600:
        return f"{int(seconds // 60)}m"
    if seconds < 86400:
        return f"{int(seconds // 3600)}h"
    days = int(seconds // 86400)
    if days < 30:
        return f"{days}d"
    if days < 365:
        return f"{days // 30}mo"
    return f"{days // 365}y"


def parse_duration(text: str) -> float:
    """Parse a duration such as ``"30d"``, ``"12h"``, ``"2w"``, ``"6mo"`` or ``"1y"``."""
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([a-zA-Z]*)\s*", text or "")
    if not match:
        raise ValueError(f"not a duration: {text!r}")
    number, unit = match.groups()
    scale = _DURATION_SCALES.get(unit.lower() or "s")
    if scale is None:
        raise ValueError(f"unknown duration unit: {unit!r}")
    return float(number) * scale


def plural(count: int, word: str, plural_form: str | None = None) -> str:
    """``1 repo`` / ``2 repos``; pass ``plural_form`` for irregular words."""
    if count == 1:
        return f"{count} {word}"
    return f"{count} {plural_form or word + 's'}"


def ago(seconds: float) -> str:
    """``just now`` / ``3d ago``."""
    age = human_age(seconds)
    return age if age == "just now" else f"{age} ago"


def percent(part: float, whole: float) -> float:
    """Return ``part`` as a 0-100 percentage, tolerating a zero ``whole``."""
    if whole <= 0:
        return 0.0
    return max(0.0, min(100.0, 100.0 * part / whole))
