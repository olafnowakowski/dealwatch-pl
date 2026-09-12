from __future__ import annotations

from pathlib import Path

import pytest

from dealwatch.config import load_dotenv


def test_loads_dotenv_without_overwriting_existing_values(tmp_path: Path) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "# local only\nDISCORD_WEBHOOK_URL='https://discord.test/webhook'\nOTHER=value\n",
        encoding="utf-8",
    )
    environment = {"OTHER": "already-set"}

    load_dotenv(dotenv, environ=environment)

    assert environment == {
        "DISCORD_WEBHOOK_URL": "https://discord.test/webhook",
        "OTHER": "already-set",
    }


def test_rejects_invalid_dotenv_entry(tmp_path: Path) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text("not an assignment\n", encoding="utf-8")

    with pytest.raises(ValueError, match="line 1"):
        load_dotenv(dotenv, environ={})
