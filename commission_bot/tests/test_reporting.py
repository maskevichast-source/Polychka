import json
import unittest

from calculations import calculate_dashboard_totals
from reporting import generate_backup_json, generate_monthly_report_csv


class ReportingTests(unittest.TestCase):
    def setUp(self):
        self.data = {
            "settings": [
                {
                    "Month": "10",
                    "Year": "2026",
                    "Standard working days": "20",
                    "Monthly Sales Plan": "1000",
                    "1 MRP value (in KZT)": "5000",
                    "Average daily pay (in KZT)": "12500",
                }
            ],
            "deals": [
                {
                    "Deal ID": "D-1",
                    "Date": "2026-10-01",
                    "Deal Total Amount": "1000",
                    "Designer %": "0",
                    "Client Discount %": "0",
                    "Item Type": "In-stock",
                    "Discount Covered by Designer?": "No",
                }
            ],
            "payments": [
                {
                    "Payment ID": "P-1",
                    "Deal ID": "D-1",
                    "Actual Paid Amount": "100",
                    "Date": "2026-10-03",
                    "Submitted for Payout": "No",
                    "Payout Batch ID": "",
                },
                {
                    "Payment ID": "P-2",
                    "Deal ID": "D-1",
                    "Actual Paid Amount": "50",
                    "Date": "2026-09-30",
                    "Submitted for Payout": "No",
                    "Payout Batch ID": "",
                },
            ],
            "timesheet": [{"Date": "2026-10-01", "Status": "Work"}],
            "kpi": [],
        }
        self.totals = calculate_dashboard_totals(
            "2026-10",
            self.data["settings"],
            self.data["deals"],
            self.data["payments"],
            self.data["timesheet"],
            self.data["kpi"],
        )

    def test_monthly_report_contains_only_selected_month_payments(self):
        content = generate_monthly_report_csv("2026-10", self.totals, self.data)
        rendered = content.decode("utf-8-sig")
        self.assertIn("P-1", rendered)
        self.assertNotIn("P-2", rendered)
        self.assertIn("Ожидают выплаты", rendered)

    def test_backup_is_utf8_json_with_all_sheet_data(self):
        content = generate_backup_json(
            {"exported_at": "2026-10-31T20:00:00+00:00", "sheets": self.data}
        )
        rendered = json.loads(content.decode("utf-8"))
        self.assertIn("payments", rendered["sheets"])
        self.assertEqual(rendered["sheets"]["payments"][0]["Payment ID"], "P-1")


if __name__ == "__main__":
    unittest.main()