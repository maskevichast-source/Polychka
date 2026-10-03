"""Environment-backed application configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


class ConfigurationError(RuntimeError):
    """Raised when required runtime configuration is absent or invalid."""


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    spreadsheet_id: str
    allowed_telegram_user_ids: frozenset[int]
    timezone: str = "Asia/Almaty"


def load_settings() -> Settings:
    load_dotenv()
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    spreadsheet_id = os.getenv("SPREADSHEET_ID", "").strip()
    raw_user_ids = os.getenv("ALLOWED_TELEGRAM_USER_IDS", "").strip()

    missing = [
        key
        for key, value in (
            ("TELEGRAM_BOT_TOKEN", token),
            ("SPREADSHEET_ID", spreadsheet_id),
        )
        if not value
    ]
    if missing:
        raise ConfigurationError(f"Required environment variables are missing: {', '.join(missing)}")

    try:
        allowed_user_ids = frozenset(
            int(value.strip())
            for value in raw_user_ids.split(",")
            if value.strip()
        )
    except ValueError as error:
        raise ConfigurationError(
            "ALLOWED_TELEGRAM_USER_IDS must be a comma-separated list of numeric IDs"
        ) from error
    return Settings(
        telegram_bot_token=token,
        spreadsheet_id=spreadsheet_id,
        allowed_telegram_user_ids=allowed_user_ids,
        timezone=os.getenv("BOT_TIMEZONE", "Asia/Almaty").strip() or "Asia/Almaty",
    )