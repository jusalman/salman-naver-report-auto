import unittest

import pandas as pd

from src.report_parser import ParseResult
from src.report_writer import ReportWriter


class FakeSheetClient:
    def __init__(self, headers, existing_rows):
        self.headers = headers
        self.existing_rows = existing_rows
        self.append_calls = []
        self.update_calls = []
        self.clear_calls = []

    def get_sheet_info(self, spreadsheet_id):
        return {"sheets": [{"properties": {"title": "수입"}}]}

    def get_sheet_data(self, spreadsheet_id, range_name):
        if range_name == "수입!A1:Z1":
            return [self.headers]
        if range_name == "수입!A:Z":
            return [self.headers] + self.existing_rows
        return []

    def append_sheet_data(self, spreadsheet_id, range_name, values, value_input_option="USER_ENTERED"):
        self.append_calls.append((spreadsheet_id, range_name, values, value_input_option))
        return {"updates": {"updatedRows": len(values)}}

    def update_sheet_data(self, spreadsheet_id, range_name, values, value_input_option="USER_ENTERED"):
        self.update_calls.append((spreadsheet_id, range_name, values, value_input_option))
        return {"updatedRows": len(values)}

    def clear_sheet_data(self, spreadsheet_id, range_name):
        self.clear_calls.append((spreadsheet_id, range_name))
        return {}


class ReportWriterTest(unittest.TestCase):
    def test_write_report_appends_only_new_raw_rows_without_touching_existing_rows(self):
        headers = ["날짜", "캠페인", "수입"]
        existing_rows = [
            ["2026-05-22", "A", "100"],
            ["2026-05-22", "A", "100"],
        ]
        df = pd.DataFrame(
            [
                {"날짜": "2026-05-22", "캠페인": "A", "수입": "100"},
                {"날짜": "2026-05-22", "캠페인": "B", "수입": "200"},
                {"날짜": "2026-05-22", "캠페인": "B", "수입": "200"},
            ]
        )
        parse_result = ParseResult(
            success=True,
            file_name="report.csv",
            dataframe=df,
            date_column_candidates=["날짜"],
        )
        writer = object.__new__(ReportWriter)
        writer.sheet_client = FakeSheetClient(headers, existing_rows)

        result = writer.write_report("spreadsheet-id", "수입", parse_result, dry_run=False)

        self.assertTrue(result["success"])
        self.assertEqual(result["rows_written"], 1)
        self.assertEqual(writer.sheet_client.clear_calls, [])
        self.assertEqual(writer.sheet_client.update_calls, [])
        self.assertEqual(
            writer.sheet_client.append_calls,
            [
                (
                    "spreadsheet-id",
                    "수입!A:C",
                    [["2026-05-22", "B", "200"]],
                    "RAW",
                )
            ],
        )


if __name__ == "__main__":
    unittest.main()
