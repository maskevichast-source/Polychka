"""Financial calculations for the commission and payroll bot."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Iterable, Mapping


ZERO = Decimal("0")
ONE_HUNDRED = Decimal("100")
FIXED_MONTHLY_SALARY = Decimal("250000")
SICK_LEAVE_MRP_CAP = Decimal("25")
MONEY_QUANTUM = Decimal("0.01")

MONTH_NAMES_RU = (
    "",
    "январь",
    "февраль",
    "март",
    "апрель",
    "май",
    "июнь",
    "июль",
    "август",
    "сентябрь",
    "октябрь",
    "ноябрь",
    "декабрь",
)


class CalculationError(ValueError):
    """Raised when a financial value is missing or outside its valid range."""


class MissingMonthlySettingsError(CalculationError):
    """Raised when a deal's month has no sales plan or payroll settings."""


@dataclass(frozen=True)
class DashboardTotals:
    month_key: str
    worked_days: int
    sick_days: int
    planned_days: int
    fixed_salary: Decimal
    sick_pay: Decimal
    plan_sales: Decimal
    monthly_plan: Decimal
    plan_completion_percent: Decimal
    expected_bonus: Decimal
    submitted_bonus: Decimal
    pending_bonus: Decimal
    payment_bonus_by_id: Mapping[str, Decimal]
    kpi_bonus: Decimal
    total_expected_income: Decimal


def to_decimal(value: Any, field_name: str = "value") -> Decimal:
    """Convert user or spreadsheet input to Decimal without float arithmetic."""
    if isinstance(value, Decimal):
        result = value
    else:
        cleaned = str(value if value is not None else "").strip()
        if not cleaned:
            return ZERO
        cleaned = cleaned.replace("\u00a0", "").replace(" ", "").replace(",", ".")
        try:
            result = Decimal(cleaned)
        except InvalidOperation as error:
            raise CalculationError(f"{field_name} must be a number") from error
    if not result.is_finite():
        raise CalculationError(f"{field_name} must be finite")
    return result


def quantize_money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def normalize_month(value: Any) -> str | None:
    """Return a YYYY-MM key from common Google Sheets date representations."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.strftime("%Y-%m")
    if isinstance(value, date):
        return value.strftime("%Y-%m")
    text = str(value).strip()
    if not text:
        return None
    for pattern in ("%Y-%m", "%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text[:10], pattern).strftime("%Y-%m")
        except ValueError:
            continue
    return None


def normalize_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    for pattern in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%Y-%m"):
        try:
            parsed = datetime.strptime(text[:10], pattern)
            return parsed.date()
        except ValueError:
            continue
    return None


def validate_percentage(value: Any, field_name: str) -> Decimal:
    percentage = to_decimal(value, field_name)
    if percentage < ZERO or percentage > ONE_HUNDRED:
        raise CalculationError(f"{field_name} must be between 0 and 100")
    return percentage


def discount_coefficient(discount_percent: Any, covered_by_designer: bool = False) -> Decimal:
    """Return the client-discount multiplier applied after the bonus rate."""
    if covered_by_designer:
        return Decimal("1")
    discount = validate_percentage(discount_percent, "discount_percent")
    if discount <= Decimal("10"):
        return Decimal("1")
    if discount <= Decimal("15"):
        return Decimal("0.9")
    return Decimal("0.8")


def _item_kind(item_type: Any) -> str:
    normalized = str(item_type).strip().lower().replace("_", "-")
    if normalized in {"in-stock", "in stock", "со склада"}:
        return "in-stock"
    if normalized in {"order", "под заказ"}:
        return "order"
    if normalized in {"sale", "распродажа"}:
        return "sale"
    raise CalculationError(f"Unsupported item type: {item_type}")


def calculate_progressive_bonus(
    gross_sales_amount: Any,
    commissionable_base: Any,
    sales_before: Any,
    monthly_plan: Any,
    item_type: Any,
) -> Decimal:
    """Apply tier rates to the part of a sales or payment interval in each band.

    The gross amount advances plan progress; the commissionable base is spread
    proportionally across the same slices. This keeps paid volume separate from
    the designer deduction and correctly handles a payment that crosses one or
    more rate boundaries.
    """
    gross = to_decimal(gross_sales_amount, "gross_sales_amount")
    base = to_decimal(commissionable_base, "commissionable_base")
    before = to_decimal(sales_before, "sales_before")
    plan = to_decimal(monthly_plan, "monthly_plan")
    kind = _item_kind(item_type)

    if gross < ZERO or base < ZERO or before < ZERO:
        raise CalculationError("Sales and payment amounts cannot be negative")
    if plan <= ZERO:
        raise CalculationError("monthly_plan must be greater than zero")
    if gross == ZERO or base == ZERO:
        return ZERO
    if kind == "sale":
        return quantize_money(base * Decimal("0.03"))

    thresholds = (
        (Decimal("0.60"), Decimal("0.01"), Decimal("0.01")),
        (Decimal("0.70"), Decimal("0.015"), Decimal("0.015")),
        (Decimal("0.90"), Decimal("0.017"), Decimal("0.017")),
        (Decimal("1.10"), Decimal("0.02"), Decimal("0.03")),
        (None, Decimal("0.025"), Decimal("0.035")),
    )
    start = before
    end = before + gross
    bonus = ZERO

    for threshold, in_stock_rate, order_rate in thresholds:
        band_end = plan * threshold if threshold is not None else end
        slice_start = max(start, ZERO)
        slice_end = min(end, band_end)
        slice_amount = max(slice_end - slice_start, ZERO)
        if slice_amount:
            rate = order_rate if kind == "order" else in_stock_rate
            bonus += (base * (slice_amount / gross)) * rate
        if band_end >= end:
            break
        start = max(start, band_end)

    return quantize_money(bonus)


def calculate_payment_bonus(
    payment_amount: Any,
    designer_percent: Any,
    discount_percent: Any,
    covered_by_designer: bool,
    deal_sales_before: Any,
    monthly_plan: Any,
    item_type: Any,
) -> Decimal:
    paid = to_decimal(payment_amount, "payment_amount")
    if paid < ZERO:
        raise CalculationError("payment_amount cannot be negative")
    designer_rate = validate_percentage(designer_percent, "designer_percent") / ONE_HUNDRED
    commissionable_base = paid * (Decimal("1") - designer_rate)
    progressive = calculate_progressive_bonus(
        gross_sales_amount=paid,
        commissionable_base=commissionable_base,
        sales_before=deal_sales_before,
        monthly_plan=monthly_plan,
        item_type=item_type,
    )
    return quantize_money(
        progressive * discount_coefficient(discount_percent, covered_by_designer)
    )


def calculate_fixed_salary(worked_days: Any, standard_working_days: Any) -> Decimal:
    worked = to_decimal(worked_days, "worked_days")
    standard = to_decimal(standard_working_days, "standard_working_days")
    if worked < ZERO:
        raise CalculationError("worked_days cannot be negative")
    if standard <= ZERO:
        raise CalculationError("standard_working_days must be greater than zero")
    return quantize_money(FIXED_MONTHLY_SALARY * worked / standard)


def calculate_sick_pay(
    sick_days: Any,
    average_daily_pay: Any,
    one_mrp_value: Any,
) -> Decimal:
    sick = to_decimal(sick_days, "sick_days")
    daily_average = to_decimal(average_daily_pay, "average_daily_pay")
    mrp = to_decimal(one_mrp_value, "one_mrp_value")
    if sick < ZERO or mrp <= ZERO:
        raise CalculationError("Sick days, average daily pay and MRP must be valid")
    if sick == ZERO:
        return ZERO
    if daily_average <= ZERO:
        raise CalculationError("average_daily_pay must be greater than zero")
    return quantize_money(min(daily_average * sick, SICK_LEAVE_MRP_CAP * mrp))


def calculate_kpi_bonus(
    criteria: Mapping[str, Any],
    plan_completion_percent: Any,
) -> Decimal:
    """Calculate KPI pay; plan qualification always comes from actual sales."""
    plan_completion = to_decimal(plan_completion_percent, "plan_completion_percent")
    values = (
        ("Criteria 1 (CRM)", Decimal("30000")),
        ("Criteria 3 (Marketing)", Decimal("30000")),
    )
    total = ZERO
    for key, amount in values:
        value = str(criteria.get(key, "")).strip().lower()
        if value in {"yes", "да", "true", "1", "on"}:
            total += amount
    if plan_completion >= Decimal("90"):
        total += Decimal("40000")
    return total


def _yes(value: Any) -> bool:
    return str(value).strip().lower() in {"yes", "да", "true", "1", "on"}


def _record_month(record: Mapping[str, Any], field: str) -> str | None:
    return normalize_month(record.get(field))


def calculate_dashboard_totals(
    month_key: str,
    settings_records: Iterable[Mapping[str, Any]],
    deal_records: Iterable[Mapping[str, Any]],
    payment_records: Iterable[Mapping[str, Any]],
    timesheet_records: Iterable[Mapping[str, Any]],
    kpi_records: Iterable[Mapping[str, Any]],
) -> DashboardTotals:
    """Build dashboard totals for a month using historical plan tiers per deal."""
    settings_by_month: dict[str, Mapping[str, Any]] = {}
    for row in settings_records:
        key = normalize_month(row.get("Month"))
        if not key and row.get("Year") and row.get("Month"):
            try:
                key = f"{int(to_decimal(row['Year'])):04d}-{int(to_decimal(row['Month'])):02d}"
            except (CalculationError, ValueError):
                key = None
        if key:
            settings_by_month[key] = row

    current_settings = settings_by_month.get(month_key)
    if current_settings is None:
        raise MissingMonthlySettingsError(
            f"Monthly settings are missing for {month_key}"
        )
    planned_days = int(to_decimal(current_settings.get("Standard working days"), "standard working days"))
    monthly_plan = to_decimal(current_settings.get("Monthly Sales Plan"), "monthly sales plan")
    mrp_value = to_decimal(current_settings.get("1 MRP value (in KZT)"), "MRP value")
    average_daily_pay = to_decimal(
        current_settings.get("Average daily pay (in KZT)"),
        "average daily pay",
    )
    if planned_days <= 0 or monthly_plan <= ZERO or mrp_value <= ZERO:
        raise CalculationError(
            "Monthly settings must contain positive workdays, plan and MRP"
        )

    deals = list(deal_records)
    deals_by_id: dict[str, Mapping[str, Any]] = {}
    deals_by_month: dict[str, list[tuple[date, Mapping[str, Any]]]] = {}
    for row in deals:
        deal_id = str(row.get("Deal ID", "")).strip()
        if deal_id:
            deals_by_id[deal_id] = row
        deal_date = normalize_date(row.get("Date"))
        if deal_date:
            deals_by_month.setdefault(deal_date.strftime("%Y-%m"), []).append((deal_date, row))

    sales_before_by_deal: dict[str, Decimal] = {}
    sales_by_month: dict[str, Decimal] = {}
    for deal_month, month_deals in deals_by_month.items():
        month_deals.sort(
            key=lambda item: (
                item[0],
                str(item[1].get("Deal ID", "")),
            )
        )
        running_sales = ZERO
        for _, row in month_deals:
            deal_id = str(row.get("Deal ID", "")).strip()
            if deal_id:
                sales_before_by_deal[deal_id] = running_sales
            deal_amount = to_decimal(row.get("Deal Total Amount"), "deal total amount")
            if deal_amount < ZERO:
                raise CalculationError("Deal total amount cannot be negative")
            running_sales += deal_amount
        sales_by_month[deal_month] = running_sales

    month_deals_total = sales_by_month.get(month_key, ZERO)
    plan_completion = (month_deals_total / monthly_plan * ONE_HUNDRED).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )

    worked_days = 0
    sick_days = 0
    for row in timesheet_records:
        if _record_month(row, "Date") != month_key:
            continue
        status = str(row.get("Status", "")).strip().lower()
        if status == "work":
            worked_days += 1
        elif status == "sick":
            sick_days += 1

    fixed_salary = calculate_fixed_salary(worked_days, planned_days)
    sick_pay = calculate_sick_pay(sick_days, average_daily_pay, mrp_value)
    current_kpi: Mapping[str, Any] = {}
    for row in kpi_records:
        if normalize_month(row.get("Month")) == month_key:
            current_kpi = row
            break
    kpi_bonus = calculate_kpi_bonus(current_kpi, plan_completion)

    expected_bonus = ZERO
    submitted_bonus = ZERO
    pending_bonus = ZERO
    payment_bonus_by_id: dict[str, Decimal] = {}
    paid_before_by_deal: dict[str, Decimal] = {}
    ordered_payments: list[tuple[date, Mapping[str, Any]]] = []
    for payment in payment_records:
        payment_date = normalize_date(payment.get("Date"))
        if payment_date:
            ordered_payments.append((payment_date, payment))
    ordered_payments.sort(
        key=lambda item: (
            item[0],
            str(item[1].get("Payment ID", "")),
        )
    )

    for payment_date, payment in ordered_payments:
        deal_id = str(payment.get("Deal ID", "")).strip()
        deal = deals_by_id.get(deal_id)
        is_current_month = payment_date.strftime("%Y-%m") == month_key
        if deal is None and is_current_month:
            raise CalculationError(f"Payment refers to missing deal {deal_id or '(blank)'}")
        if deal is None:
            continue
        paid = to_decimal(payment.get("Actual Paid Amount"), "actual paid amount")
        if paid < ZERO:
            raise CalculationError("Payment amount cannot be negative")

        deal_month = normalize_month(deal.get("Date"))
        if not deal_month and is_current_month:
            raise CalculationError(f"Deal {deal_id} has an invalid date")
        deal_settings = settings_by_month.get(deal_month or "")
        if deal_settings is None and is_current_month:
            raise MissingMonthlySettingsError(
                f"Monthly settings are missing for deal {deal_id} in {deal_month}"
            )
        if is_current_month:
            deal_plan = to_decimal(deal_settings.get("Monthly Sales Plan"), "monthly sales plan")
        else:
            deal_plan = ZERO
        if is_current_month and deal_plan <= ZERO:
            raise MissingMonthlySettingsError(
                f"Monthly sales plan is invalid for deal {deal_id} in {deal_month}"
            )
        if is_current_month:
            total = calculate_payment_bonus(
                payment_amount=paid,
                designer_percent=deal.get("Designer %"),
                discount_percent=deal.get("Client Discount %"),
                covered_by_designer=_yes(deal.get("Discount Covered by Designer?")),
                deal_sales_before=(
                    sales_before_by_deal.get(deal_id, ZERO)
                    + paid_before_by_deal.get(deal_id, ZERO)
                ),
                monthly_plan=deal_plan,
                item_type=deal.get("Item Type"),
            )
            expected_bonus += total
            payment_id = str(payment.get("Payment ID", "")).strip()
            if payment_id:
                payment_bonus_by_id[payment_id] = total
            if _yes(payment.get("Submitted for Payout")):
                submitted_snapshot = str(payment.get("Payout Bonus Amount", "")).strip()
                submitted_bonus += (
                    to_decimal(submitted_snapshot, "payout bonus amount")
                    if submitted_snapshot
                    else total
                )
            else:
                pending_bonus += total
        paid_before_by_deal[deal_id] = paid_before_by_deal.get(deal_id, ZERO) + paid

    total_expected = fixed_salary + sick_pay + expected_bonus + kpi_bonus
    return DashboardTotals(
        month_key=month_key,
        worked_days=worked_days,
        sick_days=sick_days,
        planned_days=planned_days,
        fixed_salary=quantize_money(fixed_salary),
        sick_pay=quantize_money(sick_pay),
        plan_sales=quantize_money(month_deals_total),
        monthly_plan=quantize_money(monthly_plan),
        plan_completion_percent=plan_completion,
        expected_bonus=quantize_money(expected_bonus),
        submitted_bonus=quantize_money(submitted_bonus),
        pending_bonus=quantize_money(pending_bonus),
        payment_bonus_by_id=payment_bonus_by_id,
        kpi_bonus=quantize_money(kpi_bonus),
        total_expected_income=quantize_money(total_expected),
    )


def format_kzt(value: Any) -> str:
    amount = quantize_money(to_decimal(value))
    rendered = f"{amount:,.0f}".replace(",", " ")
    return f"{rendered} ₸"


def month_label_ru(month_key: str) -> str:
    try:
        year, month = (int(part) for part in month_key.split("-", 1))
        return f"{MONTH_NAMES_RU[month].capitalize()} {year}"
    except (ValueError, IndexError):
        return month_key