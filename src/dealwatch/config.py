"""Local configuration loading without an additional runtime dependency."""

from __future__ import annotations

import os
from collections.abc import MutableMapping
from pathlib import Path


def load_dotenv(
    path: Path | None = None,
    *,
    environ: MutableMapping[str, str] | None = None,
) -> None:
    """Load simple KEY=VALUE entries without overwriting existing environment values."""

    target = path or Path.cwd() / ".env"
    target_environment = environ if environ is not None else os.environ
    if not target.is_file():
        return

    lines = target.read_text(encoding="utf-8").splitlines()
    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line.removeprefix("export ").lstrip()
        key, separator, value = line.partition("=")
        if not separator or not key or not key.replace("_", "").isalnum() or key[0].isdigit():
            raise ValueError(f"Invalid .env entry on line {line_number}")
        target_environment.setdefault(key, _unquote(value.strip()))


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value
