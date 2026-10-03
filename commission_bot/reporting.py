"""CSV monthly reports and JSON Google Sheets backups."""

from __future__ import annotations

import csv
import io
import json
from decimal import Decimal
from typing import Any, Mapping

from calculations import DashboardTotals, format_kzt, month_label_ru, normalize_month


def generate_monthly_report_csv(
    month_key: str,
    totals: DashboardTotals,
    data: Mapping[str, Any],
) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["Месячный отчёт", month_label_ru(month_key)])
    writer.writerow(["Показатель", "Значение"])
    writer.writerow(["Рабочие дни", f"{totals.worked_days} / {totals.planned_days}"])
    writer.writerow(["Дни на больничном", totals.sick_days])
    writer.writerow(["Оклад", format_kzt(totals.fixed_salary)])
    writer.writerow(["Оплата больничного", format_kzt(totals.sick_pay)])
    writer.writerow(["План продаж", format_kzt(totals.monthly_plan)])
    writer.writerow(["Продажи", format_kzt(totals.plan_sales)])
    writer.writerow(["Выполнение плана", f"{totals.plan_completion_percent}%"])
    writer.writerow(["Ожидаемые бонусы", format_kzt(totals.expected_bonus)])
    writer.writerow(["Отправлено бонусов", format_kzt(totals.submitted_bonus)])
    writer.writerow(["Ожидают выплаты", format_kzt(totals.pending_bonus)])
    writer.writerow(["KPI", format_kzt(totals.kpi_bonus)])
    writer.writerow(["Ожидаемый доход", format_kzt(totals.total_expected_income)])
    writer.writerow([])

    deals_by_id = {
        str(deal.get("Deal ID", "")).strip(): deal
        for deal in data["deals"]
    }
    writer.writerow(["Оплаты"])
    writer.writerow(
        [
            "ID оплаты",
            "Дата",
            "ID сделки",
            "Сумма оплаты, KZT",
            "Бонус, KZT",
            "Статус выплаты",
            "Пакет выплаты",
        ]
    )
    for payment in data["payments"]:
        if normalize_month(payment.get("Date")) != month_key:
            continue
        payment_id = str(payment.get("Payment ID", "")).strip()
        is_submitted = str(payment.get("Submitted for Payout", "")).strip().lower() in {
            "yes",
            "да",
            "true",
            "1",
        }
        stored_bonus = str(payment.get("Payout Bonus Amount", "")).strip()
        bonus = (
            stored_bonus
            if is_submitted and stored_bonus
            else totals.payment_bonus_by_id.get(payment_id, Decimal("0"))
        )
        writer.writerow(
            [
                payment_id,
                payment.get("Date", ""),
                payment.get("Deal ID", ""),
                payment.get("Actual Paid Amount", ""),
                str(bonus),
                "Отправлено" if is_submitted else "Ожидает",
                payment.get("Payout Batch ID", ""),
            ]
        )
    writer.writerow([])

    writer.writerow(["Сделки"])
    writer.writerow(["ID сделки", "Дата", "Сумма, KZT", "Тип товара"])
    for deal in data["deals"]:
        if normalize_month(deal.get("Date")) == month_key:
            writer.writerow(
                [
                    deal.get("Deal ID", ""),
                    deal.get("Date", ""),
                    deal.get("Deal Total Amount", ""),
                    deal.get("Item Type", ""),
                ]
            )
    writer.writerow([])

    writer.writerow(["Табель"])
    writer.writerow(["Дата", "Статус"])
    for entry in data["timesheet"]:
        if normalize_month(entry.get("Date")) == month_key:
            writer.writerow([entry.get("Date", ""), entry.get("Status", "")])

    return output.getvalue().encode("utf-8-sig")


def generate_backup_json(data: Mapping[str, Any]) -> bytes:
    return json.dumps(
        data,
        ensure_ascii=False,
        indent=2,
        default=str,
    ).encode("utf-8")