"""Inline keyboards. Every visible label is in Russian."""

from __future__ import annotations

from typing import Mapping, Sequence

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from calculations import month_label_ru


def deal_type_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Со склада", callback_data="deal-type:stock"),
                InlineKeyboardButton(text="Под заказ", callback_data="deal-type:order"),
            ],
            [InlineKeyboardButton(text="Распродажа", callback_data="deal-type:sale")],
        ]
    )


def yes_no_keyboard(prefix: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Да", callback_data=f"{prefix}:yes"),
                InlineKeyboardButton(text="Нет", callback_data=f"{prefix}:no"),
            ]
        ]
    )


def deal_picker_keyboard(deals: Sequence[Mapping[str, str]]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for deal in deals:
        deal_id = str(deal.get("Deal ID", "")).strip()
        if not deal_id:
            continue
        date_text = str(deal.get("Date", ""))
        amount_text = str(deal.get("Deal Total Amount", ""))
        label = f"{deal_id} — {date_text} — {amount_text} ₸"
        rows.append(
            [
                InlineKeyboardButton(
                    text=label[:60],
                    callback_data=f"pay-deal:{deal_id}",
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def payout_keyboard(month_counts: Sequence[tuple[str, int]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{month_label_ru(month)} — {count} оплат",
                    callback_data=f"payout:preview:{month}",
                )
            ]
            for month, count in month_counts
        ]
    )


def payout_confirmation_keyboard(month_key: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Создать пакет выплаты",
                    callback_data=f"payout:confirm:{month_key}",
                ),
                InlineKeyboardButton(text="Отмена", callback_data="payout:cancel"),
            ]
        ]
    )


def kpi_keyboard(statuses: Mapping[str, str]) -> InlineKeyboardMarkup:
    labels = (
        ("crm", "CRM", "Criteria 1 (CRM)"),
        ("marketing", "Участие в маркетинге", "Criteria 3 (Marketing)"),
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{label}: {'Вкл.' if statuses.get(column, 'No').lower() in {'yes', 'да', 'true', '1'} else 'Выкл.'}",
                    callback_data=f"kpi:{key}",
                )
            ]
            for key, label, column in labels
        ]
    )


def deal_edit_field_keyboard() -> InlineKeyboardMarkup:
    labels = (
        ("amount", "Сумма сделки"),
        ("designer", "Процент дизайнера"),
        ("discount", "Скидка клиенту"),
        ("item_type", "Тип товара"),
        ("covered", "Скидка за счёт бонуса"),
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=label,
                    callback_data=f"deal-edit:{key}",
                )
            ]
            for key, label in labels
        ]
    )


def item_type_edit_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Со склада", callback_data="deal-edit-type:stock"),
                InlineKeyboardButton(text="Под заказ", callback_data="deal-edit-type:order"),
            ],
            [
                InlineKeyboardButton(
                    text="Распродажа",
                    callback_data="deal-edit-type:sale",
                )
            ],
        ]
    )


def timesheet_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Рабочий день", callback_data="timesheet:work"),
                InlineKeyboardButton(text="Выходной", callback_data="timesheet:dayoff"),
            ],
            [InlineKeyboardButton(text="Больничный", callback_data="timesheet:sick")],
        ]
    )


def monthly_settings_keyboard(month_key: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Ввести настройки месяца",
                    callback_data=f"settings:start:{month_key}",
                )
            ]
        ]
    )