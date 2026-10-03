"""Application entry point for the Telegram commission bot."""

from __future__ import annotations

import asyncio
import logging
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.dispatcher.middlewares.base import BaseMiddleware
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, CallbackQuery, Message
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from config import ConfigurationError, Settings, load_settings
from bot_utils import local_today
from correction_handlers import router as correction_router
from google_sheets_api import GoogleSheetsAPI
from handlers import router
from keyboards import monthly_settings_keyboard
from payout_handlers import router as payout_router
from report_handlers import router as reports_router
from report_handlers import send_monthly_backup


logger = logging.getLogger(__name__)


class UserAccessMiddleware(BaseMiddleware):
    """Restrict business data and actions to the configured Telegram users."""

    def __init__(self, allowed_user_ids: frozenset[int]) -> None:
        self.allowed_user_ids = allowed_user_ids

    async def __call__(self, handler, event, data):
        user = getattr(event, "from_user", None)
        if user is None:
            return None

        if isinstance(event, Message):
            text = event.text or ""
            command = text.split(maxsplit=1)[0].split("@", 1)[0] if text else ""
            if command == "/my_id":
                return await handler(event, data)

        if user.id not in self.allowed_user_ids:
            if isinstance(event, CallbackQuery):
                await event.answer(
                    "Доступ к данным бота не разрешён. Обратитесь к владельцу бота.",
                    show_alert=True,
                )
            elif isinstance(event, Message):
                await event.answer(
                    "Доступ к данным бота не разрешён. "
                    "Ваш Telegram ID можно узнать командой /my_id."
                )
            return None
        return await handler(event, data)


async def send_monthly_settings_prompt(bot: Bot, app_settings: Settings) -> None:
    month_key = local_today(app_settings).strftime("%Y-%m")
    text = (
        f"Пора задать настройки на {month_key}.\n"
        "Введите месячный план продаж, стандартное количество рабочих дней "
        "и стоимость 1 МРП. Также потребуется средний дневной заработок, "
        "согласованный с бухгалтером, для расчёта больничного."
    )
    for user_id in app_settings.allowed_telegram_user_ids:
        try:
            await bot.send_message(
                chat_id=user_id,
                text=text,
                reply_markup=monthly_settings_keyboard(month_key),
            )
        except Exception:
            logger.exception("Failed to send monthly settings prompt to an authorized user")


async def register_commands(bot: Bot) -> None:
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Показать справку"),
            BotCommand(command="dashboard", description="Сводка за текущий месяц"),
            BotCommand(command="add_deal", description="Добавить сделку"),
            BotCommand(command="add_payment", description="Добавить оплату клиента"),
            BotCommand(command="tuesday_sync", description="Оплаты к отправке на выплату"),
            BotCommand(command="kpi", description="Отметить критерии KPI"),
            BotCommand(command="timesheet", description="Отметить рабочий статус"),
            BotCommand(command="set_plan", description="Задать настройки месяца"),
            BotCommand(command="edit_deal", description="Исправить сделку с журналом"),
            BotCommand(command="edit_payment", description="Исправить оплату с журналом"),
            BotCommand(command="report", description="Скачать отчёт за месяц"),
            BotCommand(command="backup", description="Скачать резервную копию"),
            BotCommand(command="cancel", description="Отменить текущий ввод"),
            BotCommand(command="my_id", description="Показать ваш Telegram ID"),
        ],
        language_code="ru",
    )


async def run_bot() -> None:
    app_settings = load_settings()
    if not app_settings.allowed_telegram_user_ids:
        logger.warning(
            "No authorized users are configured; only the public /my_id command is available"
        )

    sheets = GoogleSheetsAPI(spreadsheet_id=app_settings.spreadsheet_id)
    await asyncio.to_thread(sheets.connect)

    bot = Bot(
        token=app_settings.telegram_bot_token,
        default=DefaultBotProperties(),
    )
    dispatcher = Dispatcher(storage=MemoryStorage())
    access_middleware = UserAccessMiddleware(app_settings.allowed_telegram_user_ids)
    dispatcher.message.outer_middleware(access_middleware)
    dispatcher.callback_query.outer_middleware(access_middleware)
    dispatcher["sheets"] = sheets
    dispatcher["settings"] = app_settings
    dispatcher.include_router(router)
    dispatcher.include_router(payout_router)
    dispatcher.include_router(correction_router)
    dispatcher.include_router(reports_router)

    await register_commands(bot)
    scheduler = AsyncIOScheduler(timezone=ZoneInfo(app_settings.timezone))
    scheduler.add_job(
        send_monthly_settings_prompt,
        trigger=CronTrigger(
            day=2,
            hour=9,
            minute=0,
            timezone=ZoneInfo(app_settings.timezone),
        ),
        args=[bot, app_settings],
        id="monthly-settings-prompt",
        replace_existing=True,
        coalesce=True,
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        send_monthly_backup,
        trigger=CronTrigger(
            day="last",
            hour=20,
            minute=0,
            timezone=ZoneInfo(app_settings.timezone),
        ),
        args=[bot, sheets, app_settings],
        id="monthly-sheets-backup",
        replace_existing=True,
        coalesce=True,
        misfire_grace_time=3600,
    )
    scheduler.start()

    logger.info("Telegram commission bot started")
    try:
        await bot.delete_webhook()
        await dispatcher.start_polling(bot)
    finally:
        scheduler.shutdown(wait=False)
        await bot.session.close()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        asyncio.run(run_bot())
    except ConfigurationError as error:
        logger.error("Invalid application configuration: %s", error)
        raise SystemExit(2) from error


if __name__ == "__main__":
    main()