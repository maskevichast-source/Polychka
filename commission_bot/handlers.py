"""Telegram commands and FSM forms for commission, payroll and KPI tracking."""

from __future__ import annotations

import asyncio
import logging
import secrets
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Callable
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

from calculations import (
    CalculationError,
    calculate_dashboard_totals,
    format_kzt,
    month_label_ru,
    to_decimal,
    validate_percentage,
)
from config import Settings
from google_sheets_api import GoogleSheetsAPI
from keyboards import (
    deal_picker_keyboard,
    deal_type_keyboard,
    kpi_keyboard,
    monthly_settings_keyboard,
    payout_confirmation_keyboard,
    payout_keyboard,
    timesheet_keyboard,
    yes_no_keyboard,
)
from states import DealForm, PaymentForm, SettingsForm, TimesheetForm

logger = logging.getLogger(__name__)
router = Router(name="commission-bot")

ITEM_TYPES = {
    "stock": "In-stock",
    "order": "Order",
    "sale": "Sale",
}
ITEM_TYPES_RU = {
    "In-stock": "Со склада",
    "Order": "Под заказ",
    "Sale": "Распродажа",
}
TIMESHEET_STATUSES = {
    "work": ("Work", "Рабочий день"),
    "dayoff": ("Day Off", "Выходной"),
    "sick": ("Sick", "Больничный"),
}


async def run_sheet(function: Callable[..., Any], *args: Any) -> Any:
    """Keep blocking Google Sheets calls off aiogram's event loop."""
    try:
        return await asyncio.to_thread(function, *args)
    except Exception:
        logger.exception("Google Sheets operation failed")
        raise


def local_today(settings: Settings) -> date:
    return datetime.now(ZoneInfo(settings.timezone)).date()


def _parse_month(value: str) -> str | None:
    try:
        return datetime.strptime(value.strip(), "%Y-%m").strftime("%Y-%m")
    except ValueError:
        return None


def _format_amount(value: Any) -> str:
    try:
        return format_kzt(value)
    except CalculationError:
        return f"{value} ₸"


async def _start_settings_form(
    message: Message,
    state: FSMContext,
    target_month: str,
) -> None:
    await state.clear()
    await state.update_data(target_month=target_month)
    await state.set_state(SettingsForm.monthly_plan)
    await message.answer(
        f"Настройки на {month_label_ru(target_month)}.\n"
        "Введите месячный план продаж в тенге."
    )


@router.message(Command("my_id"))
async def show_user_id(message: Message) -> None:
    if message.from_user:
        await message.answer(f"Ваш Telegram ID: {message.from_user.id}")


@router.message(Command("start"))
async def start_command(message: Message) -> None:
    await message.answer(
        "Бот учёта продаж, бонусов, KPI и выплат.\n\n"
        "Доступные команды:\n"
        "/dashboard — сводка за текущий месяц\n"
        "/add_deal — добавить сделку\n"
        "/add_payment — добавить оплату клиента\n"
        "/tuesday_sync — список оплат к отправке на выплату\n"
        "/kpi — отметить критерии KPI\n"
        "/timesheet — отметить сегодняшний рабочий статус\n"
        "/set_plan — задать план и рабочие дни\n"
        "/cancel — отменить текущий ввод"
    )


@router.message(Command("cancel"))
async def cancel_command(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Текущий ввод отменён.")


@router.message(Command("set_plan"))
async def set_plan_command(
    message: Message,
    state: FSMContext,
    command: CommandObject,
    settings: Settings,
) -> None:
    today = local_today(settings)
    requested = _parse_month(command.args or "")
    if command.args and not requested:
        await message.answer(
            "Укажите месяц в формате ГГГГ-ММ, например: /set_plan 2026-10"
        )
        return
    target_month = requested or today.strftime("%Y-%m")
    await _start_settings_form(message, state, target_month)


@router.message(SettingsForm.monthly_plan)
async def enter_monthly_plan(message: Message, state: FSMContext) -> None:
    try:
        plan = to_decimal(message.text, "monthly sales plan")
        if plan <= Decimal("0"):
            raise CalculationError("monthly sales plan must be positive")
    except CalculationError:
        await message.answer("Введите положительную сумму месячного плана в тенге.")
        return
    await state.update_data(monthly_plan=str(plan))
    await state.set_state(SettingsForm.standard_working_days)
    await message.answer("Введите количество стандартных рабочих дней в этом месяце.")


@router.message(SettingsForm.standard_working_days)
async def enter_standard_working_days(message: Message, state: FSMContext) -> None:
    try:
        days = to_decimal(message.text, "standard working days")
        if days != days.to_integral_value() or days < 1 or days > 31:
            raise CalculationError("standard working days must be from 1 to 31")
    except CalculationError:
        await message.answer("Введите целое число рабочих дней от 1 до 31.")
        return
    await state.update_data(standard_working_days=int(days))
    await state.set_state(SettingsForm.mrp_value)
    await message.answer(
        "Введите стоимость 1 МРП в тенге. Она используется для месячного лимита "
        "оплаты больничного."
    )


@router.message(SettingsForm.mrp_value)
async def enter_mrp_value(
    message: Message,
    state: FSMContext,
    sheets: GoogleSheetsAPI,
) -> None:
    try:
        mrp = to_decimal(message.text, "MRP value")
        if mrp <= Decimal("0"):
            raise CalculationError("MRP value must be positive")
    except CalculationError:
        await message.answer("Введите положительную стоимость 1 МРП в тенге.")
        return

    data = await state.get_data()
    target_month = str(data["target_month"])
    try:
        await run_sheet(
            sheets.set_month_settings,
            target_month,
            str(data["monthly_plan"]),
            int(data["standard_working_days"]),
            str(mrp),
        )
    except Exception:
        await state.clear()
        await message.answer(
            "Не удалось сохранить настройки. Проверьте подключение к таблице Google "
            "и попробуйте ещё раз."
        )
        return

    await state.clear()
    await message.answer(
        f"Настройки на {month_label_ru(target_month)} сохранены.\n"
        f"План: {_format_amount(data['monthly_plan'])}\n"
        f"Стандартные рабочие дни: {data['standard_working_days']}\n"
        f"1 МРП: {_format_amount(mrp)}"
    )


@router.callback_query(F.data.startswith("settings:start:"))
async def begin_scheduled_settings(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.message:
        await callback.answer()
        return
    target_month = (callback.data or "").split(":", 2)[-1]
    if not _parse_month(target_month):
        await callback.answer("Не удалось определить месяц.", show_alert=True)
        return
    await callback.answer()
    await _start_settings_form(callback.message, state, target_month)


@router.message(Command("add_deal"))
async def add_deal_command(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(DealForm.amount)
    await message.answer("Введите общую сумму сделки в тенге.")


@router.message(DealForm.amount)
async def enter_deal_amount(message: Message, state: FSMContext) -> None:
    try:
        amount = to_decimal(message.text, "deal amount")
        if amount <= Decimal("0"):
            raise CalculationError("deal amount must be positive")
    except CalculationError:
        await message.answer("Введите положительную сумму сделки в тенге.")
        return
    await state.update_data(amount=str(amount))
    await state.set_state(DealForm.designer_percent)
    await message.answer("Введите процент дизайнера от 0 до 100.")


@router.message(DealForm.designer_percent)
async def enter_designer_percent(message: Message, state: FSMContext) -> None:
    try:
        percentage = validate_percentage(message.text, "designer_percent")
    except CalculationError:
        await message.answer("Введите процент дизайнера от 0 до 100.")
        return
    await state.update_data(designer_percent=str(percentage))
    await state.set_state(DealForm.discount_percent)
    await message.answer("Введите скидку клиенту в процентах от 0 до 100.")


@router.message(DealForm.discount_percent)
async def enter_discount_percent(message: Message, state: FSMContext) -> None:
    try:
        percentage = validate_percentage(message.text, "discount_percent")
    except CalculationError:
        await message.answer("Введите скидку в процентах от 0 до 100.")
        return
    await state.update_data(discount_percent=str(percentage))
    await state.set_state(DealForm.item_type)
    await message.answer("Выберите тип товара:", reply_markup=deal_type_keyboard())


@router.callback_query(DealForm.item_type, F.data.startswith("deal-type:"))
async def choose_deal_type(callback: CallbackQuery, state: FSMContext) -> None:
    item_key = (callback.data or "").split(":", 1)[1]
    item_type = ITEM_TYPES.get(item_key)
    if not item_type:
        await callback.answer("Выберите тип товара из списка.", show_alert=True)
        return
    await state.update_data(item_type=item_type)
    await state.set_state(DealForm.discount_covered)
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            "Скидка покрывается бонусом дизайнера?",
            reply_markup=yes_no_keyboard("deal-covered"),
        )


@router.callback_query(
    DealForm.discount_covered,
    F.data.startswith("deal-covered:"),
)
async def choose_discount_coverage(
    callback: CallbackQuery,
    state: FSMContext,
    sheets: GoogleSheetsAPI,
    settings: Settings,
) -> None:
    covered = (callback.data or "").endswith(":yes")
    data = await state.get_data()
    deal_id = f"D-{secrets.token_hex(4).upper()}"
    try:
        await run_sheet(
            sheets.add_deal,
            deal_id,
            local_today(settings),
            str(data["amount"]),
            str(data["designer_percent"]),
            str(data["discount_percent"]),
            str(data["item_type"]),
            covered,
        )
    except Exception:
        await state.clear()
        await callback.answer("Не удалось сохранить сделку.", show_alert=True)
        if callback.message:
            await callback.message.answer(
                "Не удалось сохранить сделку. Проверьте подключение к таблице Google."
            )
        return
    await state.clear()
    await callback.answer("Сделка сохранена.")
    if callback.message:
        await callback.message.answer(
            f"Сделка {deal_id} сохранена.\n"
            f"Сумма: {_format_amount(data['amount'])}\n"
            f"Тип: {ITEM_TYPES_RU[data['item_type']]}"
        )


@router.message(Command("add_payment"))
async def add_payment_command(message: Message, state: FSMContext, sheets: GoogleSheetsAPI) -> None:
    await state.clear()
    try:
        deals = await run_sheet(sheets.get_deals)
    except Exception:
        await message.answer("Не удалось получить сделки из таблицы Google.")
        return
    if not deals:
        await message.answer("Сделок пока нет. Сначала добавьте сделку командой /add_deal.")
        return

    available = [
        row
        for row in reversed(deals)
        if str(row.get("Deal ID", "")).strip()
    ][:20]
    await state.set_state(PaymentForm.deal_id)
    await message.answer(
        "Выберите сделку, к которой относится оплата:",
        reply_markup=deal_picker_keyboard(available),
    )


@router.callback_query(PaymentForm.deal_id, F.data.startswith("pay-deal:"))
async def choose_payment_deal(callback: CallbackQuery, state: FSMContext) -> None:
    deal_id = (callback.data or "").split(":", 1)[1]
    await state.update_data(deal_id=deal_id)
    await state.set_state(PaymentForm.amount)
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            f"Введите фактически полученную оплату по сделке {deal_id} в тенге."
        )


@router.message(PaymentForm.amount)
async def enter_payment_amount(
    message: Message,
    state: FSMContext,
    sheets: GoogleSheetsAPI,
    settings: Settings,
) -> None:
    try:
        amount = to_decimal(message.text, "payment amount")
        if amount <= Decimal("0"):
            raise CalculationError("payment amount must be positive")
    except CalculationError:
        await message.answer("Введите положительную сумму полученной оплаты в тенге.")
        return

    data = await state.get_data()
    payment_id = f"P-{secrets.token_hex(4).upper()}"
    try:
        await run_sheet(
            sheets.add_payment,
            payment_id,
            str(data["deal_id"]),
            str(amount),
            local_today(settings),
        )
    except Exception:
        await state.clear()
        await message.answer(
            "Не удалось сохранить оплату. Проверьте подключение к таблице Google."
        )
        return
    await state.clear()
    await message.answer(
        f"Оплата {payment_id} сохранена.\n"
        f"Сделка: {data['deal_id']}\n"
        f"Сумма: {_format_amount(amount)}"
    )


@router.message(Command("tuesday_sync"))
async def tuesday_sync_command(message: Message, sheets: GoogleSheetsAPI) -> None:
    try:
        payments = await run_sheet(sheets.get_unsubmitted_payments)
        deals = await run_sheet(sheets.get_deals)
    except Exception:
        await message.answer("Не удалось получить список оплат из таблицы Google.")
        return
    if not payments:
        await message.answer("Нет новых оплат, ожидающих отправки на выплату.")
        return

    deal_map = {str(row.get("Deal ID", "")): row for row in deals}
    lines = ["Оплаты, ещё не отправленные на выплату:"]
    for payment in payments[:20]:
        deal_id = str(payment.get("Deal ID", ""))
        lines.append(
            f"• {payment.get('Payment ID', '—')} — сделка {deal_id}, "
            f"{payment.get('Date', '—')}, "
            f"{_format_amount(payment.get('Actual Paid Amount', '0'))}"
        )
        if deal_id not in deal_map:
            logger.warning("Payment references an unknown deal: %s", deal_id)
    if len(payments) > 20:
        lines.append(f"Показаны первые 20 из {len(payments)} оплат.")
    lines.append(f"Всего ожидают отправки: {len(payments)}.")
    await message.answer("\n".join(lines), reply_markup=payout_keyboard())


@router.callback_query(F.data == "payout:confirm-all")
async def confirm_all_payouts(callback: CallbackQuery, sheets: GoogleSheetsAPI) -> None:
    try:
        payments = await run_sheet(sheets.get_unsubmitted_payments)
    except Exception:
        await callback.answer("Не удалось проверить оплаты.", show_alert=True)
        return
    if not payments:
        await callback.answer("Новых оплат нет.", show_alert=True)
        if callback.message:
            await callback.message.edit_reply_markup(reply_markup=None)
        return
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            f"Отметить все {len(payments)} оплат как отправленные на выплату?",
            reply_markup=payout_confirmation_keyboard(),
        )


@router.callback_query(F.data == "payout:mark-all")
async def mark_all_payouts(callback: CallbackQuery, sheets: GoogleSheetsAPI) -> None:
    try:
        count = await run_sheet(sheets.mark_all_payments_submitted)
    except Exception:
        await callback.answer("Не удалось обновить таблицу.", show_alert=True)
        return
    await callback.answer("Статус обновлён.")
    if callback.message:
        await callback.message.edit_text(
            f"Готово. Отмечено отправленными оплат: {count}.",
            reply_markup=None,
        )


@router.callback_query(F.data == "payout:cancel")
async def cancel_payout_submission(callback: CallbackQuery) -> None:
    await callback.answer("Отправка не отмечена.")
    if callback.message:
        await callback.message.edit_reply_markup(reply_markup=None)


def _kpi_text(month_key: str, statuses: dict[str, str]) -> str:
    checks = (
        ("CRM", "Criteria 1 (CRM)"),
        ("Личный план не менее 90%", "Criteria 2 (Plan >90%)"),
        ("Участие в маркетинге", "Criteria 3 (Marketing)"),
    )
    lines = [f"KPI за {month_label_ru(month_key)}:"]
    for label, key in checks:
        is_on = statuses.get(key, "No").strip().lower() in {"yes", "да", "true", "1"}
        lines.append(f"{label}: {'выполнено' if is_on else 'не выполнено'}")
    return "\n".join(lines)


@router.message(Command("kpi"))
async def kpi_command(message: Message, sheets: GoogleSheetsAPI, settings: Settings) -> None:
    month_key = local_today(settings).strftime("%Y-%m")
    try:
        statuses = await run_sheet(sheets.get_kpi, month_key)
    except Exception:
        await message.answer("Не удалось получить KPI из таблицы Google.")
        return
    await message.answer(_kpi_text(month_key, statuses), reply_markup=kpi_keyboard(statuses))


@router.callback_query(F.data.startswith("kpi:"))
async def toggle_kpi(
    callback: CallbackQuery,
    sheets: GoogleSheetsAPI,
    settings: Settings,
) -> None:
    criterion = (callback.data or "").split(":", 1)[1]
    month_key = local_today(settings).strftime("%Y-%m")
    try:
        statuses = await run_sheet(sheets.toggle_kpi, month_key, criterion)
    except Exception:
        await callback.answer("Не удалось обновить KPI.", show_alert=True)
        return
    await callback.answer("Статус обновлён.")
    if callback.message:
        await callback.message.edit_text(
            _kpi_text(month_key, statuses),
            reply_markup=kpi_keyboard(statuses),
        )


@router.message(Command("timesheet"))
async def timesheet_command(
    message: Message,
    state: FSMContext,
    command: CommandObject,
    settings: Settings,
) -> None:
    requested_date: date | None = None
    if command.args:
        try:
            requested_date = datetime.strptime(command.args.strip(), "%Y-%m-%d").date()
        except ValueError:
            await message.answer(
                "Укажите дату в формате ГГГГ-ММ-ДД, например: /timesheet 2026-10-01"
            )
            return
    work_date = requested_date or local_today(settings)
    await state.clear()
    await state.update_data(work_date=work_date.isoformat())
    await state.set_state(TimesheetForm.status)
    await message.answer(
        f"Выберите статус за {work_date.strftime('%d.%m.%Y')}:",
        reply_markup=timesheet_keyboard(),
    )


@router.callback_query(TimesheetForm.status, F.data.startswith("timesheet:"))
async def choose_timesheet_status(
    callback: CallbackQuery,
    state: FSMContext,
    sheets: GoogleSheetsAPI,
) -> None:
    status_key = (callback.data or "").split(":", 1)[1]
    status = TIMESHEET_STATUSES.get(status_key)
    if not status:
        await callback.answer("Выберите статус из списка.", show_alert=True)
        return
    data = await state.get_data()
    work_date = date.fromisoformat(str(data["work_date"]))
    try:
        await run_sheet(sheets.upsert_timesheet, work_date, status[0])
    except Exception:
        await state.clear()
        await callback.answer("Не удалось сохранить статус.", show_alert=True)
        if callback.message:
            await callback.message.answer(
                "Не удалось сохранить табель. Проверьте подключение к таблице Google."
            )
        return
    await state.clear()
    await callback.answer("Статус сохранён.")
    if callback.message:
        await callback.message.answer(
            f"За {work_date.strftime('%d.%m.%Y')} отмечено: {status[1].lower()}."
        )


@router.message(Command("dashboard"))
async def dashboard_command(
    message: Message,
    sheets: GoogleSheetsAPI,
    settings: Settings,
) -> None:
    today = local_today(settings)
    month_key = today.strftime("%Y-%m")
    try:
        data = await run_sheet(sheets.get_dashboard_data)
        totals = calculate_dashboard_totals(month_key, **{
            "settings_records": data["settings"],
            "deal_records": data["deals"],
            "payment_records": data["payments"],
            "timesheet_records": data["timesheet"],
            "kpi_records": data["kpi"],
        })
    except Exception as error:
        logger.exception("Dashboard calculation failed")
        if isinstance(error, CalculationError) and "settings" in str(error).lower():
            await message.answer(
                "Не хватает настроек месяца для расчёта. Задайте план, стандартные "
                "рабочие дни и стоимость 1 МРП командой /set_plan."
            )
        elif isinstance(error, CalculationError):
            await message.answer(
                "Не удалось рассчитать сводку: проверьте данные о сделках, оплатах "
                "и настройках месяцев в таблице Google."
            )
        else:
            await message.answer("Не удалось построить сводку из таблицы Google.")
        return

    month_label = month_label_ru(totals.month_key)
    income_parts = totals.fixed_salary + totals.sick_pay
    await message.answer(
        f"Сводка за {month_label}\n\n"
        f"Рабочие дни: {totals.worked_days} / {totals.planned_days}\n"
        f"Дни на больничном: {totals.sick_days}\n"
        f"Начисленный оклад: {format_kzt(totals.fixed_salary)}\n"
        f"Оплата больничного: {format_kzt(totals.sick_pay)}\n"
        f"Оклад и больничный вместе: {format_kzt(income_parts)}\n\n"
        f"Выполнение плана: {totals.plan_completion_percent}%\n"
        f"Продажи: {format_kzt(totals.plan_sales)} / {format_kzt(totals.monthly_plan)}\n\n"
        f"Бонусы — ожидается: {format_kzt(totals.expected_bonus)}\n"
        f"Бонусы — отправлено на выплату: {format_kzt(totals.submitted_bonus)}\n"
        f"Начислено по KPI: {format_kzt(totals.kpi_bonus)}\n\n"
        f"Ожидаемый доход за месяц: {format_kzt(totals.total_expected_income)}"
    )


def register_handlers() -> Router:
    return router