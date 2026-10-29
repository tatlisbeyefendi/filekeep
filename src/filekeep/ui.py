"""Terminal helpers: colour, width handling and a small table renderer."""

from __future__ import annotations

import os
import shutil
import sys
from collections.abc import Iterable, Sequence

RESET = "\x1b[0m"
CODES = {
    "bold": "\x1b[1m",
    "dim": "\x1b[2m",
    "red": "\x1b[31m",
    "green": "\x1b[32m",
    "yellow": "\x1b[33m",
    "blue": "\x1b[34m",
    "magenta": "\x1b[35m",
    "cyan": "\x1b[36m",
    "grey": "\x1b[90m",
}


def supports_color(mode: str = "auto", stream: object | None = None) -> bool:
    """Decide whether to emit ANSI colour for ``mode`` (auto/always/never)."""
    if mode == "always":
        return True
    if mode == "never":
        return False
    stream = stream or sys.stdout
    if os.environ.get("NO_COLOR"):
        return False
    return bool(getattr(stream, "isatty", lambda: False)())


class Style:
    """Wrap text in ANSI codes when colour is enabled."""

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled

    def __call__(self, text: str, *names: str) -> str:
        if not self.enabled or not names:
            return text
        prefix = "".join(CODES[name] for name in names if name in CODES)
        return f"{prefix}{text}{RESET}" if prefix else text

    def bold(self, text: str) -> str:
        return self(text, "bold")

    def dim(self, text: str) -> str:
        return self(text, "dim")


def terminal_width(default: int = 100) -> int:
    """Return the usable terminal width, clamped to something sane."""
    try:
        width = shutil.get_terminal_size().columns
    except OSError:  # pragma: no cover - unusual tty
        width = default
    return max(40, min(width, 200))


def ellipsize(text: str, width: int, marker: str = "…") -> str:
    """Shorten ``text`` so that it fits in ``width`` characters."""
    if width <= 0:
        return ""
    if len(text) <= width:
        return text
    if width <= len(marker):
        return text[:width]
    return text[: width - len(marker)] + marker


def ellipsize_path(path: str, width: int, marker: str = "…") -> str:
    """Shorten a long path while keeping the file name intact."""
    if width <= 0:
        return ""
    if len(path) <= width:
        return path
    name = os.path.basename(path.rstrip(os.sep)) or path
    if len(name) + len(marker) >= width:
        return ellipsize(name, width, marker)
    keep = width - len(name) - len(marker)
    head = path[:keep]
    return f"{head}{marker}{name}"


def shorten_home(path: str, home: str | None = None) -> str:
    """Replace the leading home directory with ``~`` (both separators supported)."""
    home = home if home is not None else os.path.expanduser("~")
    if not home or home == "/":
        return path
    trimmed = home.rstrip("/" + os.sep + "\\")
    for separator in (os.sep, "/", "\\"):
        if path.startswith(trimmed + separator):
            return "~" + path[len(trimmed) :]
    if path == trimmed:
        return "~"
    return path


def render_table(
    headers: Sequence[str],
    rows: Iterable[Sequence[str]],
    *,
    align: Sequence[str] | None = None,
    style: Style | None = None,
) -> str:
    """Render a plain-text table; ``align`` items are ``l`` or ``r`` per column."""
    rows = [list(row) for row in rows]
    columns = len(headers)
    if not rows:
        return ""
    align = list(align or ["l"] * columns)
    widths = [len(header) for header in headers]
    for row in rows:
        for index in range(columns):
            widths[index] = max(widths[index], len(str(row[index])))

    def pad(text: str, index: int) -> str:
        if align[index] == "r":
            return text.rjust(widths[index])
        return text.ljust(widths[index])

    lines = ["  ".join(pad(str(headers[i]), i) for i in range(columns)).rstrip()]
    if style is not None:
        lines = [style.dim(lines[0])]
    for row in rows:
        lines.append("  ".join(pad(str(row[i]), i) for i in range(columns)).rstrip())
    return "\n".join(lines)


def render_bar(
    value: float, total: float, width: int = 24, fill: str = "█", empty: str = "·"
) -> str:
    """Return a proportional progress bar."""
    if width <= 0:
        return ""
    ratio = 0.0 if total <= 0 else max(0.0, min(1.0, value / total))
    filled = round(ratio * width)
    if value > 0 and filled == 0:
        filled = 1
    return fill * filled + empty * (width - filled)


def header_line(title: str, detail: str, style: Style, width: int) -> str:
    """``filekeep 0.1.0 · 12 files · ~/Documents`` one-line header."""
    left = style.bold(title)
    right = style.dim(detail)
    padding = max(1, width - len(title) - len(detail))
    return f"{left}{' ' * padding}{right}"
