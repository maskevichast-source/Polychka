"""Finite-state forms used for safe bot data entry."""

from aiogram.fsm.state import State, StatesGroup


class DealForm(StatesGroup):
    amount = State()
    designer_percent = State()
    discount_percent = State()
    item_type = State()
    discount_covered = State()


class PaymentForm(StatesGroup):
    deal_id = State()
    amount = State()


class SettingsForm(StatesGroup):
    monthly_plan = State()
    standard_working_days = State()
    mrp_value = State()


class TimesheetForm(StatesGroup):
    status = State()