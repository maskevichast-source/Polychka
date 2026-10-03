"""Shared helpers for Telegram handlers."""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime
from typing import Any, Callable
from zoneinfo import ZoneInfo

from calculations import CalculationError, format_kzt
from config import Settings

logger = logging.getLogger(__name__)


async def run_sheet(function: Callable[..., Any], *args: Any) -> Any:
    """Keep blocking Google Sheets calls off aiogram's event loop."""
    try:
        return await asyncio.to_thread(function, *args)
    except Exception:
        logger.exception("Google Sheets operation failed")
        raise


def local_today(settings: Settings) -> date:
    return datetime.now(ZoneInfo(settings.timezone)).date()


def parse_month(value: str) -> str | None:
    try:
        return datetime.strptime(value.strip(), "%Y-%m").strftime("%Y-%m")
    except ValueError:
        return None


def format_amount(value: Any) -> str:
    try:
        return format_kzt(value)
    except CalculationError:
        return f"{value} ₸"