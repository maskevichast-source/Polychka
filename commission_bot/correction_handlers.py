"""Audited correction flows for deals and unpaid client payments."""

from __future__ import annotations

import logging
from decimal import Decimal

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot_utils import format_amount, run_sheet
from calculations import CalculationError, to_decimal, validate_percentage
from google_sheets_api import GoogleSheetsAPI
from keyboards import deal_edit_field_keyboard, item_type_edit_keyboard, yes_no_keyboard
from states import DealCorrectionForm, PaymentCorrectionForm

logger = logging.getLogger(__name__)
router = Router(name="audited-corrections")

DEAL_FIELDS = {
    "amount": "Deal Total Amount",
    "designer": "Designer %",
    "discount": "Client Discount %",
    "item_type": "Item Type",
    "covered": "Discount Covered by Designer?",
}
EDITABLE_ITEM_TYPES = {
    "stock": "In-stock",
    "order": "Order",
    "sale": "Sale",
}


@router.message(Command("edit_deal"))
async def begin_deal_correction(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(DealCorrectionForm.deal_id)
    await message.answer(
        "Введите ID сделки, которую нужно исправить. "
        "Изменение сохранится в журнале вместе с причиной."
    )


@router.message(DealCorrectionForm.deal_id)
async def select_deal_for_correction(
    message: Message,
    state: FSMContext,
    sheets: GoogleSheetsAPI,
) -> None:
    deal_id = (message.text or "").strip()
    if not deal_id:
        await message.answer("Введите ID сделки.")
        return
    try:
        deal = await run_sheet(sheets.get_deal_by_id, deal_id)
    except Exception:
        await message.answer("Не удалось проверить сделку в таблице Google.")
        return
    if not deal:
        await message.answer("Сделка с таким ID не найдена. Введите ID ещё раз.")
        return
    await state.update_data(deal_id=deal_id)
    await state.set_state(DealCorrectionForm.field)
    await message.answer(
        f"Сделка {deal_id} найдена. Выберите поле для исправления:",
        reply_markup=deal_edit_field_keyboard(),
    )


@router.callback_query(
    DealCorrectionForm.field,
    F.data.startswith("deal-edit:"),
)
async def choose_deal_field(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    field_key = (callback.data or "").split(":", 1)[1]
    if field_key not in DEAL_FIELDS:
        await callback.answer("Неизвестное поле.", show_alert=True)
        return
    await state.update_data(field_key=field_key)
    if field_key == "item_type":
        await state.set_state(DealCorrectionForm.item_type)
        prompt = "Выберите новый тип товара:"
        markup = item_type_edit_keyboard()
    elif field_key == "covered":
        await state.set_state(DealCorrectionForm.discount_covered)
        prompt = "Скидка покрывается бонусом дизайнера?"
        markup = yes_no_keyboard("deal-edit-covered")
    else:
        await state.set_state(DealCorrectionForm.value)
        prompt = {
            "amount": "Введите новую сумму сделки в тенге.",
            "designer": "Введите новый процент дизайнера от 0 до 100.",
            "discount": "Введите новую скидку от 0 до 100 процентов.",
        }[field_key]
        markup = None
    await callback.answer()
    if callback.message:
        await callback.message.answer(prompt, reply_markup=markup)


async def _ask_deal_correction_reason(
    message: Message,
    state: FSMContext,
    new_value: str,
) -> None:
    await state.update_data(new_value=new_value)
    await state.set_state(DealCorrectionForm.reason)
    await message.answer("Укажите причину исправления (не менее 5 символов).")


@router.message(DealCorrectionForm.value)
async def enter_deal_correction_value(
    message: Message,
    state: FSMContext,
) -> None:
    data = await state.get_data()
    field_key = str(data.get("field_key", ""))
    try:
        if field_key == "amount":
            value = to_decimal(message.text, "deal amount")
            if value <= Decimal("0"):
                raise CalculationError("amount must be positive")
        elif field_key in {"designer", "discount"}:
            value = validate_percentage(message.text, field_key)
        else:
            raise CalculationError("unsupported correction field")
    except CalculationError:
        await message.answer(
            "Введите корректное положительное значение или процент от 0 до 100."
        )
        return
    await _ask_deal_correction_reason(message, state, str(value))


@router.callback_query(
    DealCorrectionForm.item_type,
    F.data.startswith("deal-edit-type:"),
)
async def choose_corrected_item_type(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    item_key = (callback.data or "").split(":", 1)[1]
    value = EDITABLE_ITEM_TYPES.get(item_key)
    if not value:
        await callback.answer("Выберите тип товара из списка.", show_alert=True)
        return
    await callback.answer()
    if callback.message:
        await _ask_deal_correction_reason(callback.message, state, value)


@router.callback_query(
    DealCorrectionForm.discount_covered,
    F.data.startswith("deal-edit-covered:"),
)
async def choose_corrected_discount_coverage(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    value = "Yes" if (callback.data or "").endswith(":yes") else "No"
    await callback.answer()
    if callback.message:
        await _ask_deal_correction_reason(callback.message, state, value)


@router.message(DealCorrectionForm.reason)
async def save_deal_correction(
    message: Message,
    state: FSMContext,
    sheets: GoogleSheetsAPI,
) -> None:
    reason = (message.text or "").strip()
    if len(reason) < 5:
        await message.answer("Причина должна содержать не менее 5 символов.")
        return
    data = await state.get_data()
    field_key = str(data.get("field_key", ""))
    actor_id = message.from_user.id if message.from_user else 0
    try:
        old_value, new_value = await run_sheet(
            sheets.update_deal_field,
            str(data["deal_id"]),
            DEAL_FIELDS[field_key],
            str(data["new_value"]),
            actor_id,
            reason,
        )
    except Exception as error:
        logger.exception("Could not correct deal %s", data.get("deal_id"))
        await state.clear()
        if isinstance(error, (KeyError, ValueError)):
            await message.answer(
                "Исправление не сохранено. Сделка могла уже попасть в выплату "
                "или новое значение совпадает с текущим."
            )
        else:
            await message.answer(
                "Не удалось сохранить исправление. Проверьте Google Sheets."
            )
        return
    await state.clear()
    await message.answer(
        f"Сделка {data['deal_id']} исправлена.\n"
        f"Поле: {DEAL_FIELDS[field_key]}\n"
        f"Было: {old_value}\n"
        f"Стало: {new_value}\n"
        f"Причина записана в журнал."
    )


@router.message(Command("edit_payment"))
async def begin_payment_correction(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(PaymentCorrectionForm.payment_id)
    await message.answer(
        "Введите ID оплаты, которую нужно исправить. "
        "Оплату из уже созданного пакета изменить нельзя."
    )


@router.message(PaymentCorrectionForm.payment_id)
async def select_payment_for_correction(
    message: Message,
    state: FSMContext,
    sheets: GoogleSheetsAPI,
) -> None:
    payment_id = (message.text or "").strip()
    if not payment_id:
        await message.answer("Введите ID оплаты.")
        return
    try:
        payment = await run_sheet(sheets.get_pending_payment_by_id, payment_id)
    except Exception:
        await message.answer("Не удалось проверить оплату в таблице Google.")
        return
    if not payment:
        await message.answer(
            "Ожидающая оплата с таким ID не найдена. "
            "Уже включённые в пакет выплаты оплаты менять нельзя."
        )
        return
    await state.update_data(payment_id=payment_id)
    await state.set_state(PaymentCorrectionForm.amount)
    await message.answer(
        f"Текущая сумма оплаты {format_amount(payment.get('Actual Paid Amount', '0'))}. "
        "Введите новую сумму в тенге."
    )


@router.message(PaymentCorrectionForm.amount)
async def enter_payment_correction_amount(
    message: Message,
    state: FSMContext,
) -> None:
    try:
        amount = to_decimal(message.text, "payment amount")
        if amount <= Decimal("0"):
            raise CalculationError("payment amount must be positive")
    except CalculationError:
        await message.answer("Введите положительную сумму оплаты в тенге.")
        return
    await state.update_data(new_amount=str(amount))
    await state.set_state(PaymentCorrectionForm.reason)
    await message.answer("Укажите причину исправления (не менее 5 символов).")


@router.message(PaymentCorrectionForm.reason)
async def save_payment_correction(
    message: Message,
    state: FSMContext,
    sheets: GoogleSheetsAPI,
) -> None:
    reason = (message.text or "").strip()
    if len(reason) < 5:
        await message.answer("Причина должна содержать не менее 5 символов.")
        return
    data = await state.get_data()
    actor_id = message.from_user.id if message.from_user else 0
    try:
        old_value, new_value = await run_sheet(
            sheets.update_pending_payment_amount,
            str(data["payment_id"]),
            str(data["new_amount"]),
            actor_id,
            reason,
        )
    except Exception as error:
        logger.exception("Could not correct payment %s", data.get("payment_id"))
        await state.clear()
        if isinstance(error, (KeyError, ValueError)):
            await message.answer(
                "Исправление не сохранено. Оплата могла уже попасть в пакет "
                "или новое значение совпадает с текущим."
            )
        else:
            await message.answer(
                "Не удалось сохранить исправление. Проверьте Google Sheets."
            )
        return
    await state.clear()
    await message.answer(
        f"Оплата {data['payment_id']} исправлена.\n"
        f"Было: {format_amount(old_value)}\n"
        f"Стало: {format_amount(new_value)}\n"
        "Причина записана в журнал."
    )