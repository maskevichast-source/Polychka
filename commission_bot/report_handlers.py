"""Downloadable reporting and monthly backup handlers."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Bot, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import BufferedInputFile, Message

from bot_utils import local_today, parse_month, run_sheet
from calculations import CalculationError, calculate_dashboard_totals
from config import Settings
from google_sheets_api import GoogleSheetsAPI
from reporting import generate_backup_json, generate_monthly_report_csv

logger = logging.getLogger(__name__)
router = Router(name="reports-and-backups")


@router.message(Command("report"))
async def monthly_report_command(
    message: Message,
    command: CommandObject,
    sheets: GoogleSheetsAPI,
    settings: Settings,
) -> None:
    today = local_today(settings)
    requested_month = parse_month(command.args or "")
    if command.args and not requested_month:
        await message.answer(
            "Укажите месяц в формате ГГГГ-ММ, например: /report 2026-10"
        )
        return
    month_key = requested_month or today.strftime("%Y-%m")
    try:
        data = await run_sheet(sheets.get_dashboard_data)
        totals = calculate_dashboard_totals(
            month_key,
            data["settings"],
            data["deals"],
            data["payments"],
            data["timesheet"],
            data["kpi"],
        )
        content = generate_monthly_report_csv(month_key, totals, data)
    except Exception:
        logger.exception("Could not build monthly report for %s", month_key)
        await message.answer(
            "Не удалось подготовить отчёт. Проверьте настройки месяца и данные "
            "в таблице Google."
        )
        return

    await message.answer_document(
        BufferedInputFile(content, filename=f"otchet-{month_key}.csv"),
        caption=f"Месячный отчёт за {month_key}.",
    )


@router.message(Command("backup"))
async def backup_command(message: Message, sheets: GoogleSheetsAPI) -> None:
    try:
        data = await run_sheet(sheets.get_backup_data)
        content = generate_backup_json(data)
    except Exception:
        logger.exception("Could not export Google Sheets backup")
        await message.answer("Не удалось создать резервную копию таблиц.")
        return
    date_suffix = datetime.now().strftime("%Y%m%d-%H%M")
    await message.answer_document(
        BufferedInputFile(content, filename=f"rezervnaya-kopiya-{date_suffix}.json"),
        caption="Резервная копия данных Google Sheets.",
    )


async def send_monthly_backup(
    bot: Bot,
    sheets: GoogleSheetsAPI,
    app_settings: Settings,
) -> None:
    """Send each authorized user a full JSON export at month end."""
    if not app_settings.allowed_telegram_user_ids:
        logger.warning("Monthly backup skipped: no authorized users are configured")
        return
    try:
        data = await asyncio.to_thread(sheets.get_backup_data)
        content = generate_backup_json(data)
    except Exception:
        logger.exception("Could not create scheduled Google Sheets backup")
        return

    timestamp = datetime.now(ZoneInfo(app_settings.timezone)).strftime("%Y%m%d-%H%M")
    document = BufferedInputFile(
        content,
        filename=f"rezervnaya-kopiya-{timestamp}.json",
    )
    for user_id in app_settings.allowed_telegram_user_ids:
        try:
            await bot.send_document(
                chat_id=user_id,
                document=document,
                caption="Ежемесячная резервная копия Google Sheets.",
            )
        except Exception:
            logger.exception(
                "Failed to send scheduled backup to an authorized Telegram user"
            )