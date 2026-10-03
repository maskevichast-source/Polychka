from decimal import Decimal
import unittest

from calculations import (
    CalculationError,
    calculate_dashboard_totals,
    calculate_fixed_salary,
    calculate_kpi_bonus,
    calculate_payment_bonus,
    calculate_progressive_bonus,
    calculate_sick_pay,
    discount_coefficient,
)


class ProgressiveBonusTests(unittest.TestCase):
    def test_one_deal_crossing_multiple_bands_is_split_by_band(self) -> None:
        bonus = calculate_progressive_bonus(
            gross_sales_amount="300",
            commissionable_base="300",
            sales_before="550",
            monthly_plan="1000",
            item_type="In-stock",
        )
        self.assertEqual(bonus, Decimal("4.55"))

    def test_order_uses_higher_rates_above_ninety_percent(self) -> None:
        bonus = calculate_progressive_bonus(
            gross_sales_amount="300",
            commissionable_base="300",
            sales_before="850",
            monthly_plan="1000",
            item_type="Order",
        )
        self.assertEqual(bonus, Decimal("8.60"))

    def test_sale_uses_fixed_rate_independent_of_plan_progress(self) -> None:
        bonus = calculate_progressive_bonus(
            gross_sales_amount="1000",
            commissionable_base="800",
            sales_before="9500",
            monthly_plan="10000",
            item_type="Sale",
        )
        self.assertEqual(bonus, Decimal("24.00"))

    def test_discount_coefficient_boundaries_and_designer_exception(self) -> None:
        self.assertEqual(discount_coefficient("10"), Decimal("1"))
        self.assertEqual(discount_coefficient("10.01"), Decimal("0.9"))
        self.assertEqual(discount_coefficient("15"), Decimal("0.9"))
        self.assertEqual(discount_coefficient("15.01"), Decimal("0.8"))
        self.assertEqual(discount_coefficient("40", covered_by_designer=True), Decimal("1"))

    def test_payment_bonus_deducts_designer_percentage_before_discount(self) -> None:
        bonus = calculate_payment_bonus(
            payment_amount="1000",
            designer_percent="10",
            discount_percent="12",
            covered_by_designer=False,
            deal_sales_before="0",
            monthly_plan="1000",
            item_type="In-stock",
        )
        self.assertEqual(bonus, Decimal("10.45"))

    def test_single_payment_can_cross_multiple_bonus_bands(self) -> None:
        bonus = calculate_payment_bonus(
            payment_amount="300",
            designer_percent="0",
            discount_percent="0",
            covered_by_designer=False,
            deal_sales_before="550",
            monthly_plan="1000",
            item_type="In-stock",
        )
        self.assertEqual(bonus, Decimal("4.55"))

    def test_invalid_plan_is_rejected(self) -> None:
        with self.assertRaises(CalculationError):
            calculate_progressive_bonus("100", "100", "0", "0", "Order")


class PayrollTests(unittest.TestCase):
    def test_fixed_salary_is_proportional_to_worked_days(self) -> None:
        self.assertEqual(
            calculate_fixed_salary("16", "22"),
            Decimal("181818.18"),
        )

    def test_sick_pay_uses_daily_average_and_monthly_cap(self) -> None:
        self.assertEqual(calculate_sick_pay("3", "20", "5000"), Decimal("37500.00"))
        self.assertEqual(calculate_sick_pay("30", "20", "1000"), Decimal("25000.00"))

    def test_kpi_maximum_is_one_hundred_thousand(self) -> None:
        self.assertEqual(
            calculate_kpi_bonus(
                {
                    "Criteria 1 (CRM)": "Yes",
                    "Criteria 2 (Plan >90%)": "Yes",
                    "Criteria 3 (Marketing)": "Yes",
                }
            ),
            Decimal("100000"),
        )


class DashboardTests(unittest.TestCase):
    def test_month_summary_counts_plan_payments_attendance_and_kpi(self) -> None:
        totals = calculate_dashboard_totals(
            "2026-10",
            settings_records=[
                {
                    "Month": "10",
                    "Year": "2026",
                    "Standard working days": "20",
                    "Monthly Sales Plan": "1000",
                    "1 MRP value (in KZT)": "5000",
                }
            ],
            deal_records=[
                {
                    "Deal ID": "D-1",
                    "Date": "2026-10-01",
                    "Deal Total Amount": "700",
                    "Designer %": "0",
                    "Client Discount %": "0",
                    "Item Type": "In-stock",
                    "Discount Covered by Designer?": "No",
                },
                {
                    "Deal ID": "D-2",
                    "Date": "2026-10-02",
                    "Deal Total Amount": "500",
                    "Designer %": "0",
                    "Client Discount %": "0",
                    "Item Type": "Order",
                    "Discount Covered by Designer?": "No",
                },
            ],
            payment_records=[
                {
                    "Payment ID": "P-1",
                    "Deal ID": "D-2",
                    "Actual Paid Amount": "500",
                    "Date": "2026-10-03",
                    "Submitted for Payout": "Yes",
                }
            ],
            timesheet_records=[
                {"Date": "2026-10-01", "Status": "Work"},
                {"Date": "2026-10-02", "Status": "Sick"},
                {"Date": "2026-10-03", "Status": "Day Off"},
            ],
            kpi_records=[
                {
                    "Month": "2026-10",
                    "Criteria 1 (CRM)": "Yes",
                    "Criteria 2 (Plan >90%)": "Yes",
                    "Criteria 3 (Marketing)": "No",
                }
            ],
        )
        self.assertEqual(totals.plan_sales, Decimal("1200.00"))
        self.assertEqual(totals.plan_completion_percent, Decimal("120.00"))
        self.assertEqual(totals.worked_days, 1)
        self.assertEqual(totals.sick_days, 1)
        self.assertEqual(totals.expected_bonus, Decimal("12.90"))
        self.assertEqual(totals.submitted_bonus, Decimal("12.90"))
        self.assertEqual(totals.kpi_bonus, Decimal("70000"))
        self.assertEqual(
            totals.total_expected_income,
            totals.fixed_salary + totals.sick_pay + totals.expected_bonus + totals.kpi_bonus,
        )

    def test_installments_continue_through_progressive_bands(self) -> None:
        totals = calculate_dashboard_totals(
            "2026-10",
            settings_records=[
                {
                    "Month": "10",
                    "Year": "2026",
                    "Standard working days": "20",
                    "Monthly Sales Plan": "1000",
                    "1 MRP value (in KZT)": "5000",
                }
            ],
            deal_records=[
                {
                    "Deal ID": "D-1",
                    "Date": "2026-10-01",
                    "Deal Total Amount": "550",
                    "Designer %": "0",
                    "Client Discount %": "0",
                    "Item Type": "In-stock",
                    "Discount Covered by Designer?": "No",
                },
                {
                    "Deal ID": "D-2",
                    "Date": "2026-10-02",
                    "Deal Total Amount": "300",
                    "Designer %": "0",
                    "Client Discount %": "0",
                    "Item Type": "In-stock",
                    "Discount Covered by Designer?": "No",
                },
            ],
            payment_records=[
                {
                    "Payment ID": "P-1",
                    "Deal ID": "D-2",
                    "Actual Paid Amount": "100",
                    "Date": "2026-10-03",
                    "Submitted for Payout": "No",
                },
                {
                    "Payment ID": "P-2",
                    "Deal ID": "D-2",
                    "Actual Paid Amount": "200",
                    "Date": "2026-10-04",
                    "Submitted for Payout": "No",
                },
            ],
            timesheet_records=[],
            kpi_records=[],
        )
        self.assertEqual(totals.expected_bonus, Decimal("4.55"))


if __name__ == "__main__":
    unittest.main()