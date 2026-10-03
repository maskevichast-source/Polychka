"""Month-scoped payout batch preview and confirmation handlers."""

from __future__ import annotations

import logging
import secrets
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from bot_utils import format_amount, local_today, run_sheet
from calculations import (
    CalculationError,
    calculate_dashboard_totals,
    month_label_ru,
    normalize_month,
)
from config import Settings
from google_sheets_api import GoogleSheetsAPI
from keyboards import payout_confirmation_keyboard, payout_keyboard

logger = logging.getLogger(__name__)
router = Router(name="payout-batches")


def _month_pending(data: dict, month_key: str) -> list[dict[str, str]]:
    return [
        payment
        for payment in data["payments"]
        if normalize_month(payment.get("Date")) == month_key
        and str(payment.get("Submitted for Payout", "")).strip().lower()
        not in {"yes", "да", "true", "1"}
    ]


def _month_totals(data: dict, month_key: str):
    return calculate_dashboard_totals(
        month_key,
        data["settings"],
        data["deals"],
        data["payments"],
        data["timesheet"],
        data["kpi"],
    )


@router.message(Command("tuesday_sync"))
async def tuesday_sync_command(message: Message, sheets: GoogleSheetsAPI) -> None:
    try:
        data = await run_sheet(sheets.get_dashboard_data)
    except Exception:
        await message.answer("Не удалось получить список оплат из таблицы Google.")
        return

    month_counts: list[tuple[str, int]] = []
    pending_months: dict[str, list[dict[str, str]]] = {}
    for payment in data["payments"]:
        if str(payment.get("Submitted for Payout", "")).strip().lower() in {
            "yes",
            "да",
            "true",
            "1",
        }:
            continue
        month_key = normalize_month(payment.get("Date"))
        if month_key:
            pending_months.setdefault(month_key, []).append(payment)

    if not pending_months:
        await message.answer("Нет новых оплат, ожидающих отправки на выплату.")
        return

    lines = ["Неотправленные оплаты сгруппированы по месяцу поступления:"]
    for month_key in sorted(pending_months, reverse=True):
        try:
            totals = _month_totals(data, month_key)
        except CalculationError:
            logger.exception("Could not calculate pending payouts for %s", month_key)
            lines.append(
                f"• {month_label_ru(month_key)} — нельзя рассчитать. "
                "Проверьте настройки месяца и сделки."
            )
            continue
        count = len(pending_months[month_key])
        month_counts.append((month_key, count))
        lines.append(
            f"• {month_label_ru(month_key)} — {count} оплат; "
            f"к выплате бонусами: {format_amount(totals.pending_bonus)}"
        )

    if month_counts:
        await message.answer(
            "\n".join(lines),
            reply_markup=payout_keyboard(month_counts),
        )
    else:
        await message.answer("\n".join(lines))


@router.callback_query(F.data.startswith("payout:preview:"))
async def preview_payout_batch(
    callback: CallbackQuery,
    sheets: GoogleSheetsAPI,
) -> None:
    month_key = (callback.data or "").split(":", 2)[-1]
    try:
        data = await run_sheet(sheets.get_dashboard_data)
        pending = _month_pending(data, month_key)
        if not pending:
            await callback.answer("За этот месяц нет новых оплат.", show_alert=True)
            if callback.message:
                await callback.message.edit_reply_markup(reply_markup=None)
            return
        totals = _month_totals(data, month_key)
        bonuses = totals.payment_bonus_by_id
        missing_ids = [
            str(row.get("Payment ID", "")).strip()
            for row in pending
            if str(row.get("Payment ID", "")).strip() not in bonuses
        ]
        if missing_ids:
            raise CalculationError(
                "Не удалось рассчитать бонус для оплат: " + ", ".join(missing_ids)
            )
    except Exception:
        logger.exception("Payout batch preview failed for %s", month_key)
        await callback.answer(
            "Не удалось рассчитать пакет. Проверьте настройки и записи в таблице.",
            show_alert=True,
        )
        return

    lines = [f"Проверка пакета выплаты за {month_label_ru(month_key)}:"]
    for payment in pending[:20]:
        payment_id = str(payment.get("Payment ID", "")).strip()
        lines.append(
            f"• {payment_id} — сделка {payment.get('Deal ID', '—')}, "
            f"{payment.get('Date', '—')}; оплата "
            f"{format_amount(payment.get('Actual Paid Amount', '0'))}; "
            f"бонус {format_amount(bonuses[payment_id])}"
        )
    if len(pending) > 20:
        lines.append(f"Показаны первые 20 из {len(pending)} оплат.")
    lines.extend(
        [
            f"Всего оплат в пакете: {len(pending)}.",
            f"Сумма бонусов к выплате: {format_amount(totals.pending_bonus)}.",
            "После подтверждения записи получат номер пакета и отметку об отправке.",
        ]
    )
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            "\n".join(lines),
            reply_markup=payout_confirmation_keyboard(month_key),
        )


@router.callback_query(F.data.startswith("payout:confirm:"))
async def confirm_payout_batch(
    callback: CallbackQuery,
    sheets: GoogleSheetsAPI,
    settings: Settings,
) -> None:
    month_key = (callback.data or "").split(":", 2)[-1]
    try:
        data = await run_sheet(sheets.get_dashboard_data)
        pending = _month_pending(data, month_key)
        if not pending:
            await callback.answer("Новых оплат больше нет.", show_alert=True)
            if callback.message:
                await callback.message.edit_reply_markup(reply_markup=None)
            return
        totals = _month_totals(data, month_key)
        pending_ids = {
            str(payment.get("Payment ID", "")).strip()
            for payment in pending
        }
        if "" in pending_ids or not pending_ids.issubset(totals.payment_bonus_by_id):
            raise CalculationError("Для одной или нескольких оплат нет расчётного бонуса")
        bonuses = {
            payment_id: totals.payment_bonus_by_id[payment_id]
            for payment_id in pending_ids
        }
        actor_id = callback.from_user.id
        created_at = datetime.now(ZoneInfo(settings.timezone)).isoformat(timespec="seconds")
        batch_id = (
            f"PB-{local_today(settings).strftime('%Y%m%d')}-"
            f"{secrets.token_hex(3).upper()}"
        )
        count = await run_sheet(
            sheets.mark_payout_batch,
            month_key,
            batch_id,
            created_at,
            actor_id,
            bonuses,
        )
        if count != len(pending_ids):
            raise RuntimeError("The payout batch did not include every pending payment")
    except Exception:
        logger.exception("Payout batch submission failed for %s", month_key)
        await callback.answer(
            "Не удалось создать пакет. Данные не подтверждены; обновите список и попробуйте снова.",
            show_alert=True,
        )
        return

    await callback.answer("Пакет выплаты создан.")
    if callback.message:
        await callback.message.edit_text(
            f"Пакет {batch_id} создан.\n"
            f"Месяц: {month_label_ru(month_key)}\n"
            f"Оплат: {count}\n"
            f"Бонусы к выплате: {format_amount(totals.pending_bonus)}",
            reply_markup=None,
        )


@router.callback_query(F.data == "payout:cancel")
async def cancel_payout_submission(callback: CallbackQuery) -> None:
    await callback.answer("Пакет не создан.")
    if callback.message:
        await callback.message.edit_reply_markup(reply_markup=None)