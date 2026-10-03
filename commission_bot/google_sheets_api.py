"""Google Sheets persistence for deals, payments, payroll and KPI data."""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping, Sequence

import gspread
from oauth2client.service_account import ServiceAccountCredentials

from calculations import normalize_month


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
        "Average daily pay (in KZT)",
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
        "Payout Batch ID",
        "Payout Submitted At",
        "Payout Submitted By",
        "Payout Bonus Amount",
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
    "Payout Batches": (
        "Batch ID",
        "Month",
        "Created At",
        "Actor Telegram ID",
        "Payment Count",
        "Bonus Total",
        "Payment IDs",
    ),
    "Audit Log": (
        "Timestamp",
        "Actor Telegram ID",
        "Action",
        "Entity Type",
        "Entity ID",
        "Field",
        "Old Value",
        "New Value",
        "Reason",
    ),
}

KPI_COLUMNS = {
    "crm": "Criteria 1 (CRM)",
    "marketing": "Criteria 3 (Marketing)",
}

NUMERIC_COLUMNS = {
    "Standard working days",
    "Monthly Sales Plan",
    "1 MRP value (in KZT)",
    "Average daily pay (in KZT)",
    "Deal Total Amount",
    "Designer %",
    "Client Discount %",
    "Actual Paid Amount",
    "Payment Count",
    "Bonus Total",
    "Payout Bonus Amount",
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

    @staticmethod
    def _cell_value(value: Any, numeric: bool = False) -> dict[str, Any]:
        if value is None or value == "":
            return {"userEnteredValue": {"stringValue": ""}}
        if numeric:
            try:
                return {"userEnteredValue": {"numberValue": float(value)}}
            except (TypeError, ValueError):
                pass
        return {"userEnteredValue": {"stringValue": str(value)}}

    def _append_cells_request(
        self,
        title: str,
        values: Mapping[str, Any],
    ) -> dict[str, Any]:
        worksheet = self._worksheet(title)
        headers = worksheet.row_values(1)
        return {
            "appendCells": {
                "sheetId": worksheet.id,
                "rows": [
                    {
                        "values": [
                            self._cell_value(
                                values.get(header, ""),
                                numeric=header in NUMERIC_COLUMNS,
                            )
                            for header in headers
                        ]
                    }
                ],
                "fields": "userEnteredValue",
            }
        }

    @staticmethod
    def _update_cell_request(
        sheet_id: int,
        row_index: int,
        column_index: int,
        value: Any,
        numeric: bool = False,
    ) -> dict[str, Any]:
        return {
            "updateCells": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": row_index,
                    "endRowIndex": row_index + 1,
                    "startColumnIndex": column_index,
                    "endColumnIndex": column_index + 1,
                },
                "rows": [{"values": [GoogleSheetsAPI._cell_value(value, numeric)]}],
                "fields": "userEnteredValue",
            }
        }

    def _audit_values(
        self,
        actor_id: int | str,
        action: str,
        entity_type: str,
        entity_id: str,
        field: str,
        old_value: Any,
        new_value: Any,
        reason: str = "",
    ) -> dict[str, Any]:
        def render(value: Any) -> str:
            if isinstance(value, (dict, list)):
                return json.dumps(value, ensure_ascii=False, default=str, sort_keys=True)
            return str(value)

        return {
            "Timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "Actor Telegram ID": str(actor_id),
            "Action": action,
            "Entity Type": entity_type,
            "Entity ID": entity_id,
            "Field": field,
            "Old Value": render(old_value),
            "New Value": render(new_value),
            "Reason": reason,
        }

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
        average_daily_pay: str,
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
                "Average daily pay (in KZT)": average_daily_pay,
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
        actor_id: int,
    ) -> None:
        values = {
            "Deal ID": deal_id,
            "Date": deal_date.isoformat(),
            "Deal Total Amount": amount,
            "Designer %": designer_percent,
            "Client Discount %": discount_percent,
            "Item Type": item_type,
            "Discount Covered by Designer?": (
                "Yes" if discount_covered_by_designer else "No"
            ),
        }
        self._require_workbook().batch_update(
            {
                "requests": [
                    self._append_cells_request("Deals", values),
                    self._append_cells_request(
                        "Audit Log",
                        self._audit_values(
                            actor_id, "CREATE", "Deal", deal_id, "", "", values
                        ),
                    ),
                ]
            }
        )

    def add_payment(
        self,
        payment_id: str,
        deal_id: str,
        paid_amount: str,
        payment_date: date,
        actor_id: int,
    ) -> None:
        values = {
            "Payment ID": payment_id,
            "Deal ID": deal_id,
            "Actual Paid Amount": paid_amount,
            "Date": payment_date.isoformat(),
            "Submitted for Payout": "No",
        }
        self._require_workbook().batch_update(
            {
                "requests": [
                    self._append_cells_request("Payments", values),
                    self._append_cells_request(
                        "Audit Log",
                        self._audit_values(
                            actor_id, "CREATE", "Payment", payment_id, "", "", values
                        ),
                    ),
                ]
            }
        )

    def get_deals(self) -> list[dict[str, str]]:
        return self._records("Deals")

    def get_payments(self) -> list[dict[str, str]]:
        return self._records("Payments")

    def get_deal_by_id(self, deal_id: str) -> dict[str, str] | None:
        return next(
            (
                row
                for row in self.get_deals()
                if str(row.get("Deal ID", "")).strip() == deal_id.strip()
            ),
            None,
        )

    def get_pending_payment_by_id(self, payment_id: str) -> dict[str, str] | None:
        return next(
            (
                row
                for row in self.get_unsubmitted_payments()
                if str(row.get("Payment ID", "")).strip() == payment_id.strip()
            ),
            None,
        )

    def get_unsubmitted_payments(self) -> list[dict[str, str]]:
        return [
            row
            for row in self.get_payments()
            if str(row.get("Submitted for Payout", "")).strip().lower()
            not in {"yes", "да", "true", "1"}
        ]

    def mark_payout_batch(
        self,
        month_key: str,
        batch_id: str,
        created_at: str,
        actor_id: int,
        payment_bonus_by_id: Mapping[str, Any],
    ) -> int:
        """Atomically mark a month of pending payments and append batch/audit rows."""
        worksheet = self._worksheet("Payments")
        values = worksheet.get_all_values()
        if not values:
            return 0
        headers = values[0]
        header_index = {header: index for index, header in enumerate(headers)}
        id_column = header_index["Payment ID"]
        date_column = header_index["Date"]
        status_column = header_index["Submitted for Payout"]
        target_ids = set(payment_bonus_by_id)
        matched_ids: set[str] = set()
        updates: list[dict[str, Any]] = []
        cells_to_set = {
            "Submitted for Payout": "Yes",
            "Payout Batch ID": batch_id,
            "Payout Submitted At": created_at,
            "Payout Submitted By": str(actor_id),
            "Payout Bonus Amount": "",
        }

        for row_number, row in enumerate(values[1:], start=2):
            padded = row + [""] * max(0, len(headers) - len(row))
            current_status = padded[status_column]
            if str(current_status).strip().lower() in {"yes", "да", "true", "1"}:
                continue
            if not any(str(value).strip() for value in row):
                continue
            payment_id = str(padded[id_column]).strip()
            payment_month = normalize_month(padded[date_column])
            if payment_id not in target_ids or payment_month != month_key:
                continue
            matched_ids.add(payment_id)
            cells_to_set["Payout Bonus Amount"] = str(payment_bonus_by_id[payment_id])
            for field, value in cells_to_set.items():
                updates.append(
                    self._update_cell_request(
                        worksheet.id,
                        row_number - 1,
                        header_index[field],
                        value,
                        numeric=field == "Payout Bonus Amount",
                    )
                )

        if matched_ids != target_ids:
            missing = ", ".join(sorted(target_ids - matched_ids))
            raise ValueError(
                "Pending payments changed before payout confirmation"
                + (f": {missing}" if missing else "")
            )
        if not matched_ids:
            return 0

        bonus_total = sum(
            (Decimal(str(payment_bonus_by_id[payment_id])) for payment_id in matched_ids),
            Decimal("0"),
        )
        batch_values = {
            "Batch ID": batch_id,
            "Month": month_key,
            "Created At": created_at,
            "Actor Telegram ID": str(actor_id),
            "Payment Count": len(matched_ids),
            "Bonus Total": bonus_total,
            "Payment IDs": json.dumps(sorted(matched_ids), ensure_ascii=False),
        }
        audit_values = self._audit_values(
            actor_id,
            "PAYOUT_BATCH_SUBMITTED",
            "Payout Batch",
            batch_id,
            "Payment IDs",
            "",
            json.dumps(sorted(matched_ids), ensure_ascii=False),
            f"Месяц {month_key}; бонусы к выплате: {bonus_total:.2f} KZT",
        )
        updates.extend(
            [
                self._append_cells_request("Payout Batches", batch_values),
                self._append_cells_request("Audit Log", audit_values),
            ]
        )
        self._require_workbook().batch_update({"requests": updates})
        return len(matched_ids)

    def update_deal_field(
        self,
        deal_id: str,
        field: str,
        new_value: str,
        actor_id: int,
        reason: str,
    ) -> tuple[str, str]:
        allowed_fields = {
            "Deal Total Amount",
            "Designer %",
            "Client Discount %",
            "Item Type",
            "Discount Covered by Designer?",
        }
        if field not in allowed_fields:
            raise ValueError("This deal field cannot be edited")
        worksheet = self._worksheet("Deals")
        values = worksheet.get_all_values()
        headers = values[0] if values else []
        if field not in headers or "Deal ID" not in headers:
            raise RuntimeError("Deals worksheet is missing required headers")
        id_column = headers.index("Deal ID")
        field_column = headers.index(field)
        target = None
        for row_number, row in enumerate(values[1:], start=2):
            padded = row + [""] * max(0, len(headers) - len(row))
            if str(padded[id_column]).strip() == deal_id.strip():
                target = (row_number, padded)
                break
        if target is None:
            raise KeyError(f"Deal {deal_id} was not found")
        row_number, row = target

        for payment in self.get_payments():
            if (
                str(payment.get("Deal ID", "")).strip() == deal_id.strip()
                and str(payment.get("Submitted for Payout", "")).strip().lower()
                in {"yes", "да", "true", "1"}
            ):
                raise ValueError(
                    "Deal has a submitted payout and cannot be edited"
                )

        old_value = str(row[field_column])
        if old_value == new_value:
            raise ValueError("The new value is unchanged")
        audit_values = self._audit_values(
            actor_id, "CORRECT", "Deal", deal_id, field, old_value, new_value, reason
        )
        self._require_workbook().batch_update(
            {
                "requests": [
                    self._update_cell_request(
                        worksheet.id,
                        row_number - 1,
                        field_column,
                        new_value,
                        numeric=field in NUMERIC_COLUMNS,
                    ),
                    self._append_cells_request("Audit Log", audit_values),
                ]
            }
        )
        return old_value, new_value

    def update_pending_payment_amount(
        self,
        payment_id: str,
        new_amount: str,
        actor_id: int,
        reason: str,
    ) -> tuple[str, str]:
        worksheet = self._worksheet("Payments")
        values = worksheet.get_all_values()
        headers = values[0] if values else []
        if "Payment ID" not in headers or "Submitted for Payout" not in headers:
            raise RuntimeError("Payments worksheet is missing required headers")
        id_column = headers.index("Payment ID")
        status_column = headers.index("Submitted for Payout")
        amount_column = headers.index("Actual Paid Amount")
        target = None
        for row_number, row in enumerate(values[1:], start=2):
            padded = row + [""] * max(0, len(headers) - len(row))
            if str(padded[id_column]).strip() == payment_id.strip():
                target = (row_number, padded)
                break
        if target is None:
            raise KeyError(f"Payment {payment_id} was not found")
        row_number, row = target
        if str(row[status_column]).strip().lower() in {"yes", "да", "true", "1"}:
            raise ValueError("Payment already has a payout batch and cannot be edited")
        old_value = str(row[amount_column])
        if old_value == new_amount:
            raise ValueError("The new amount is unchanged")
        audit_values = self._audit_values(
            actor_id,
            "CORRECT",
            "Payment",
            payment_id,
            "Actual Paid Amount",
            old_value,
            new_amount,
            reason,
        )
        self._require_workbook().batch_update(
            {
                "requests": [
                    self._update_cell_request(
                        worksheet.id,
                        row_number - 1,
                        amount_column,
                        new_amount,
                        numeric=True,
                    ),
                    self._append_cells_request("Audit Log", audit_values),
                ]
            }
        )
        return old_value, new_amount

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

    def get_payout_batches(self) -> list[dict[str, str]]:
        return self._records("Payout Batches")

    def get_backup_data(self) -> dict[str, Any]:
        return {
            "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "sheets": {
                title: self._records(title)
                for title in SHEET_HEADERS
            },
        }