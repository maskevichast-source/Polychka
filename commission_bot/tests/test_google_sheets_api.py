import unittest

from google_sheets_api import GoogleSheetsAPI, SHEET_HEADERS


class FakeWorksheet:
    def __init__(self, worksheet_id, headers, rows=None):
        self.id = worksheet_id
        self._headers = list(headers)
        self._rows = [list(self._headers)] + [list(row) for row in (rows or [])]

    def row_values(self, row_number):
        return self._rows[row_number - 1] if row_number <= len(self._rows) else []

    def get_all_values(self):
        return [list(row) for row in self._rows]


class FakeWorkbook:
    def __init__(self, worksheets):
        self.worksheets = worksheets
        self.requests = []

    def worksheet(self, title):
        return self.worksheets[title]

    def batch_update(self, body):
        self.requests.append(body)


def make_api(deal_rows=None, payment_rows=None):
    sheets = {
        "Deals": FakeWorksheet(1, SHEET_HEADERS["Deals"], deal_rows),
        "Payments": FakeWorksheet(2, SHEET_HEADERS["Payments"], payment_rows),
        "Payout Batches": FakeWorksheet(3, SHEET_HEADERS["Payout Batches"]),
        "Audit Log": FakeWorksheet(4, SHEET_HEADERS["Audit Log"]),
    }
    api = GoogleSheetsAPI(spreadsheet_id="test", service_account_json="{}")
    api._workbook = FakeWorkbook(sheets)
    return api


class GoogleSheetsAuditTests(unittest.TestCase):
    def test_payout_batch_updates_only_requested_month_and_appends_audit(self):
        api = make_api(
            payment_rows=[
                [
                    "P-1",
                    "D-1",
                    "1000",
                    "2026-10-03",
                    "No",
                    "",
                    "",
                    "",
                    "",
                ],
                [
                    "P-2",
                    "D-1",
                    "2000",
                    "2026-09-30",
                    "No",
                    "",
                    "",
                    "",
                    "",
                ],
                [
                    "P-3",
                    "D-1",
                    "3000",
                    "2026-10-04",
                    "Yes",
                    "PB-OLD",
                    "2026-10-05T10:00:00",
                    "7",
                    "30",
                ],
            ]
        )

        count = api.mark_payout_batch(
            "2026-10",
            "PB-NEW",
            "2026-10-10T10:00:00",
            42,
            {"P-1": "25.50"},
        )

        self.assertEqual(count, 1)
        requests = api._workbook.requests[0]["requests"]
        appended_titles = [
            request["appendCells"]["sheetId"]
            for request in requests
            if "appendCells" in request
        ]
        self.assertEqual(appended_titles, [3, 4])
        updated_cells = [
            request["updateCells"]["range"]
            for request in requests
            if "updateCells" in request
        ]
        self.assertEqual(len(updated_cells), 5)
        self.assertTrue(all(cell["sheetId"] == 2 for cell in updated_cells))
        self.assertEqual(
            {cell["startRowIndex"] for cell in updated_cells},
            {1},
        )
        bonus_cell = requests[4]["updateCells"]["rows"][0]["values"][0]
        self.assertEqual(
            bonus_cell["userEnteredValue"]["numberValue"],
            25.5,
        )
        payout_batch_row = requests[5]["appendCells"]["rows"][0]["values"]
        self.assertEqual(
            payout_batch_row[5]["userEnteredValue"]["numberValue"],
            25.5,
        )

    def test_deal_correction_and_audit_are_sent_in_one_batch(self):
        api = make_api(
            deal_rows=[
                [
                    "D-1",
                    "2026-10-01",
                    "1000",
                    "5",
                    "0",
                    "In-stock",
                    "No",
                ]
            ]
        )

        self.assertEqual(
            api.update_deal_field(
                "D-1",
                "Deal Total Amount",
                "1200",
                42,
                "Исправление опечатки",
            ),
            ("1000", "1200"),
        )
        requests = api._workbook.requests[0]["requests"]
        self.assertEqual(len(requests), 2)
        self.assertIn("updateCells", requests[0])
        self.assertEqual(requests[1]["appendCells"]["sheetId"], 4)

    def test_payment_from_a_payout_batch_cannot_be_corrected(self):
        api = make_api(
            payment_rows=[
                [
                    "P-1",
                    "D-1",
                    "1000",
                    "2026-10-03",
                    "Yes",
                    "PB-OLD",
                    "2026-10-05T10:00:00",
                    "7",
                    "30",
                ]
            ]
        )
        with self.assertRaises(ValueError):
            api.update_pending_payment_amount(
                "P-1",
                "1200",
                42,
                "Исправление опечатки",
            )
        self.assertEqual(api._workbook.requests, [])


if __name__ == "__main__":
    unittest.main()