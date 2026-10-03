"""Inline keyboards. Every visible label is in Russian."""

from __future__ import annotations

from typing import Mapping, Sequence

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


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


def payout_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Отметить все как отправленные",
                    callback_data="payout:confirm-all",
                )
            ]
        ]
    )


def payout_confirmation_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Подтвердить", callback_data="payout:mark-all"),
                InlineKeyboardButton(text="Отмена", callback_data="payout:cancel"),
            ]
        ]
    )


def kpi_keyboard(statuses: Mapping[str, str]) -> InlineKeyboardMarkup:
    labels = (
        ("crm", "CRM", "Criteria 1 (CRM)"),
        ("plan", "Личный план ≥ 90%", "Criteria 2 (Plan >90%)"),
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