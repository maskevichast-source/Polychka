"""Google Sheets persistence for deals, payments, payroll and KPI data."""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
from typing import Any, Mapping, Sequence

import gspread
from oauth2client.service_account import ServiceAccountCredentials


SCOPES = (
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
)

SHEET_HEADERS: dict[str, tuple[str, ...]] = {
    "Settings": (
        "Month",
        "Year",
        "Standard working days",
        "Monthly Sales Plan",
        "1 MRP value (in KZT)",
    ),
    "Deals": (
        "Deal ID",
        "Date",
        "Deal Total Amount",
        "Designer %",
        "Client Discount %",
        "Item Type",
        "Discount Covered by Designer?",
    ),
    "Payments": (
        "Payment ID",
        "Deal ID",
        "Actual Paid Amount",
        "Date",
        "Submitted for Payout",
    ),
    "Timesheet": (
        "Date",
        "Status",
    ),
    "KPI": (
        "Month",
        "Criteria 1 (CRM)",
        "Criteria 2 (Plan >90%)",
        "Criteria 3 (Marketing)",
    ),
}

KPI_COLUMNS = {
    "crm": "Criteria 1 (CRM)",
    "plan": "Criteria 2 (Plan >90%)",
    "marketing": "Criteria 3 (Marketing)",
}


class GoogleSheetsConfigurationError(RuntimeError):
    """Raised when Google Sheets credentials or spreadsheet settings are missing."""


class GoogleSheetsAPI:
    def __init__(
        self,
        spreadsheet_id: str | None = None,
        service_account_json: str | None = None,
        service_account_file: str | None = None,
    ) -> None:
        self.spreadsheet_id = spreadsheet_id or os.getenv("SPREADSHEET_ID", "").strip()
        self.service_account_json = (
            service_account_json
            if service_account_json is not None
            else os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")
        )
        self.service_account_file = (
            service_account_file
            if service_account_file is not None
            else os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "")
        )
        if not self.spreadsheet_id:
            raise GoogleSheetsConfigurationError("SPREADSHEET_ID is required")
        if not self.service_account_json and not self.service_account_file:
            raise GoogleSheetsConfigurationError(
                "Set GOOGLE_SERVICE_ACCOUNT_JSON or GOOGLE_SERVICE_ACCOUNT_FILE"
            )
        self._workbook: gspread.Spreadsheet | None = None

    def connect(self) -> None:
        """Authenticate and create/repair the required worksheet headers."""
        if self.service_account_json:
            try:
                credentials_info = json.loads(self.service_account_json)
            except json.JSONDecodeError as error:
                raise GoogleSheetsConfigurationError(
                    "GOOGLE_SERVICE_ACCOUNT_JSON is not valid JSON"
                ) from error
            credentials = ServiceAccountCredentials.from_json_keyfile_dict(
                credentials_info, SCOPES
            )
        else:
            credentials_path = Path(self.service_account_file).expanduser()
            if not credentials_path.is_file():
                raise GoogleSheetsConfigurationError(
                    "GOOGLE_SERVICE_ACCOUNT_FILE does not point to a readable file"
                )
            credentials = ServiceAccountCredentials.from_json_keyfile_name(
                str(credentials_path), SCOPES
            )

        self._workbook = gspread.authorize(credentials).open_by_key(self.spreadsheet_id)
        for sheet_name, headers in SHEET_HEADERS.items():
            worksheet = self._get_or_create_worksheet(sheet_name)
            self._ensure_headers(worksheet, headers)

    def _require_workbook(self) -> gspread.Spreadsheet:
        if self._workbook is None:
            raise RuntimeError("Google Sheets connection has not been initialized")
        return self._workbook

    def _get_or_create_worksheet(self, title: str) -> gspread.Worksheet:
        workbook = self._require_workbook()
        try:
            return workbook.worksheet(title)
        except gspread.WorksheetNotFound:
            return workbook.add_worksheet(title=title, rows=1000, cols=20)

    @staticmethod
    def _ensure_headers(
        worksheet: gspread.Worksheet, expected_headers: Sequence[str]
    ) -> None:
        current_headers = worksheet.row_values(1)
        if not current_headers:
            worksheet.update(
                range_name="A1",
                values=[list(expected_headers)],
                value_input_option="RAW",
            )
            return
        missing_headers = [header for header in expected_headers if header not in current_headers]
        if missing_headers:
            worksheet.update(
                range_name="A1",
                values=[current_headers + missing_headers],
                value_input_option="RAW",
            )

    def _worksheet(self, title: str) -> gspread.Worksheet:
        return self._require_workbook().worksheet(title)

    def _records(self, title: str) -> list[dict[str, str]]:
        values = self._worksheet(title).get_all_values()
        if not values:
            return []
        headers = values[0]
        result: list[dict[str, str]] = []
        for row in values[1:]:
            if not any(str(value).strip() for value in row):
                continue
            padded = row + [""] * max(0, len(headers) - len(row))
            result.append(dict(zip(headers, padded)))
        return result

    def _append_record(self, title: str, values: Mapping[str, Any]) -> None:
        worksheet = self._worksheet(title)
        headers = worksheet.row_values(1)
        row = [values.get(header, "") for header in headers]
        worksheet.append_row(row, value_input_option="USER_ENTERED")

    def _upsert_record(
        self,
        title: str,
        values: Mapping[str, Any],
        key_fields: Sequence[str],
    ) -> None:
        worksheet = self._worksheet(title)
        all_values = worksheet.get_all_values()
        if not all_values:
            raise RuntimeError(f"Worksheet {title} is missing its header row")
        headers = all_values[0]
        target_key = tuple(str(values.get(key, "")).strip() for key in key_fields)
        row_values = [values.get(header, "") for header in headers]
        for row_number, row in enumerate(all_values[1:], start=2):
            padded = row + [""] * max(0, len(headers) - len(row))
            current_key = tuple(
                str(padded[headers.index(key)]).strip() for key in key_fields
            )
            if current_key == target_key:
                worksheet.update(
                    range_name=f"A{row_number}",
                    values=[row_values],
                    value_input_option="USER_ENTERED",
                )
                return
        worksheet.append_row(row_values, value_input_option="USER_ENTERED")

    @staticmethod
    def _split_month(month_key: str) -> tuple[int, int]:
        try:
            year_text, month_text = month_key.split("-", 1)
            year, month = int(year_text), int(month_text)
        except (ValueError, AttributeError) as error:
            raise ValueError("Month must use YYYY-MM format") from error
        if month < 1 or month > 12:
            raise ValueError("Month must use YYYY-MM format")
        return year, month

    def set_month_settings(
        self,
        month_key: str,
        monthly_plan: str,
        standard_working_days: int,
        mrp_value: str,
    ) -> None:
        year, month = self._split_month(month_key)
        self._upsert_record(
            "Settings",
            {
                "Month": month,
                "Year": year,
                "Standard working days": standard_working_days,
                "Monthly Sales Plan": monthly_plan,
                "1 MRP value (in KZT)": mrp_value,
            },
            ("Year", "Month"),
        )

    def add_deal(
        self,
        deal_id: str,
        deal_date: date,
        amount: str,
        designer_percent: str,
        discount_percent: str,
        item_type: str,
        discount_covered_by_designer: bool,
    ) -> None:
        self._append_record(
            "Deals",
            {
                "Deal ID": deal_id,
                "Date": deal_date.isoformat(),
                "Deal Total Amount": amount,
                "Designer %": designer_percent,
                "Client Discount %": discount_percent,
                "Item Type": item_type,
                "Discount Covered by Designer?": (
                    "Yes" if discount_covered_by_designer else "No"
                ),
            },
        )

    def add_payment(
        self,
        payment_id: str,
        deal_id: str,
        paid_amount: str,
        payment_date: date,
    ) -> None:
        self._append_record(
            "Payments",
            {
                "Payment ID": payment_id,
                "Deal ID": deal_id,
                "Actual Paid Amount": paid_amount,
                "Date": payment_date.isoformat(),
                "Submitted for Payout": "No",
            },
        )

    def get_deals(self) -> list[dict[str, str]]:
        return self._records("Deals")

    def get_payments(self) -> list[dict[str, str]]:
        return self._records("Payments")

    def get_unsubmitted_payments(self) -> list[dict[str, str]]:
        return [
            row
            for row in self.get_payments()
            if str(row.get("Submitted for Payout", "")).strip().lower()
            not in {"yes", "да", "true", "1"}
        ]

    def mark_all_payments_submitted(self) -> int:
        worksheet = self._worksheet("Payments")
        values = worksheet.get_all_values()
        if not values:
            return 0
        headers = values[0]
        status_column = headers.index("Submitted for Payout") + 1
        changed_rows = 0
        for row_number, row in enumerate(values[1:], start=2):
            current_status = row[status_column - 1] if len(row) >= status_column else ""
            if str(current_status).strip().lower() in {"yes", "да", "true", "1"}:
                continue
            if not any(str(value).strip() for value in row):
                continue
            worksheet.update_cell(row_number, status_column, "Yes")
            changed_rows += 1
        return changed_rows

    def upsert_timesheet(self, work_date: date, status: str) -> None:
        self._upsert_record(
            "Timesheet",
            {"Date": work_date.isoformat(), "Status": status},
            ("Date",),
        )

    def get_kpi(self, month_key: str) -> dict[str, str]:
        for row in self._records("KPI"):
            if str(row.get("Month", "")).strip() == month_key:
                return {
                    key: str(row.get(key, "No")).strip() or "No"
                    for key in KPI_COLUMNS.values()
                }
        return {key: "No" for key in KPI_COLUMNS.values()}

    def toggle_kpi(self, month_key: str, criterion: str) -> dict[str, str]:
        if criterion not in KPI_COLUMNS:
            raise ValueError("Unknown KPI criterion")
        current = self.get_kpi(month_key)
        column = KPI_COLUMNS[criterion]
        current_value = current.get(column, "No").strip().lower()
        current[column] = "No" if current_value in {"yes", "да", "true", "1"} else "Yes"
        self._upsert_record(
            "KPI",
            {"Month": month_key, **current},
            ("Month",),
        )
        return current

    def get_dashboard_data(self) -> dict[str, list[dict[str, str]]]:
        return {
            "settings": self._records("Settings"),
            "deals": self._records("Deals"),
            "payments": self._records("Payments"),
            "timesheet": self._records("Timesheet"),
            "kpi": self._records("KPI"),
        }