import unittest
from unittest.mock import patch

import pandas as pd

from src.report_parser import ParseResult
from src.report_writer import ReportWriter


class FakeSheetClient:
    def __init__(self, headers, existing_rows, append_result=None, tab_name="수입"):
        self.headers = headers
        self.existing_rows = existing_rows
        self.append_result = append_result
        self.tab_name = tab_name
        self.append_calls = []
        self.update_calls = []
        self.clear_calls = []

    def get_sheet_info(self, spreadsheet_id):
        return {"sheets": [{"properties": {"title": self.tab_name}}]}

    def get_sheet_data(self, spreadsheet_id, range_name):
        if range_name.endswith("!A1:Z1") or range_name.endswith("!A1:ZZ1"):
            return [self.headers]
        if range_name.endswith("!A:Z") or range_name.endswith("!A:ZZ"):
            return [self.headers] + self.existing_rows
        return []

    def add_sheet(self, spreadsheet_id, tab_name):
        self.tab_name = tab_name
        return {}

    def append_sheet_data(self, spreadsheet_id, range_name, values, value_input_option="USER_ENTERED"):
        self.append_calls.append((spreadsheet_id, range_name, values, value_input_option))
        if self.append_result is not None:
            return self.append_result
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
                {"날짜": "2026-05-23", "캠페인": "B", "수입": "200"},
                {"날짜": "2026-05-23", "캠페인": "B", "수입": "200"},
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
        self.assertEqual(
            writer.sheet_client.update_calls,
            [
                (
                    "spreadsheet-id",
                    "수입!A4:C4",
                    [["2026-05-23", "B", "200"]],
                    "USER_ENTERED",
                )
            ],
        )
        self.assertEqual(writer.sheet_client.append_calls, [])

    def test_dry_run_counts_only_new_rows_without_writing(self):
        headers = ["날짜", "캠페인", "수입"]
        existing_rows = [["2026-05-22", "A", "100"]]
        df = pd.DataFrame(
            [
                {"날짜": "2026-05-22", "캠페인": "A", "수입": "100"},
                {"날짜": "2026-05-23", "캠페인": "B", "수입": "200"},
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

        result = writer.write_report("spreadsheet-id", "수입", parse_result, dry_run=True)

        self.assertTrue(result["success"])
        self.assertEqual(result["candidate_rows"], 2)
        self.assertEqual(result["rows_written"], 1)
        self.assertEqual(writer.sheet_client.append_calls, [])
        self.assertEqual(writer.sheet_client.update_calls, [])
        self.assertEqual(writer.sheet_client.clear_calls, [])

    def test_new_key_on_existing_or_older_date_is_blocked_by_default(self):
        headers = ["날짜", "캠페인", "수입"]
        existing_rows = [["2026-05-22", "A", "100"]]
        df = pd.DataFrame([{"날짜": "2026-05-22", "캠페인": "B", "수입": "200"}])
        parse_result = ParseResult(success=True, file_name="report.csv", dataframe=df)
        writer = object.__new__(ReportWriter)
        writer.sheet_client = FakeSheetClient(headers, existing_rows)

        result = writer.write_report("spreadsheet-id", "수입", parse_result, dry_run=False)

        self.assertTrue(result["success"])
        self.assertEqual(result["rows_written"], 0)
        self.assertEqual(result["skipped_existing_or_older_date_rows"], 1)
        self.assertEqual(writer.sheet_client.append_calls, [])

    def test_existing_or_older_date_append_can_be_enabled_for_backfill(self):
        headers = ["날짜", "캠페인", "수입"]
        existing_rows = [["2026-05-22", "A", "100"]]
        df = pd.DataFrame([{"날짜": "2026-05-22", "캠페인": "B", "수입": "200"}])
        parse_result = ParseResult(success=True, file_name="report.csv", dataframe=df)
        writer = object.__new__(ReportWriter)
        writer.sheet_client = FakeSheetClient(headers, existing_rows)

        with patch.dict("os.environ", {"ALLOW_EXISTING_OR_OLDER_DATE_APPEND": "true"}):
            result = writer.write_report("spreadsheet-id", "수입", parse_result, dry_run=False)

        self.assertTrue(result["success"])
        self.assertEqual(result["rows_written"], 1)
        self.assertEqual(writer.sheet_client.update_calls[0][2], [["2026-05-22", "B", "200"]])
        self.assertEqual(writer.sheet_client.append_calls, [])

    def test_new_rows_are_appended_in_date_order(self):
        headers = ["날짜", "캠페인", "수입"]
        existing_rows = [["2026-05-22", "A", "100"]]
        df = pd.DataFrame(
            [
                {"날짜": "2026-05-24", "캠페인": "C", "수입": "300"},
                {"날짜": "2026-05-23", "캠페인": "B", "수입": "200"},
                {"날짜": "2026-05-25", "캠페인": "D", "수입": "400"},
            ]
        )
        parse_result = ParseResult(success=True, file_name="report.csv", dataframe=df)
        writer = object.__new__(ReportWriter)
        writer.sheet_client = FakeSheetClient(headers, existing_rows)

        result = writer.write_report("spreadsheet-id", "수입", parse_result, dry_run=False)

        self.assertTrue(result["success"])
        self.assertEqual(result["rows_written"], 3)
        self.assertEqual(
            writer.sheet_client.update_calls[0][2],
            [
                ["2026-05-23", "B", "200"],
                ["2026-05-24", "C", "300"],
                ["2026-05-25", "D", "400"],
            ],
        )
        self.assertEqual(writer.sheet_client.update_calls[0][1], "수입!A3:C5")
        self.assertEqual(writer.sheet_client.append_calls, [])

    def test_duplicate_check_ignores_extra_sheet_columns(self):
        headers = ["날짜", "캠페인", "수입", "메모"]
        existing_rows = [["2026-05-22", "A", "100", "확인"]]
        df = pd.DataFrame([{"날짜": "2026-05-22", "캠페인": "A", "수입": "100"}])
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
        self.assertEqual(result["rows_written"], 0)
        self.assertEqual(writer.sheet_client.append_calls, [])
        self.assertEqual(writer.sheet_client.update_calls, [])
        self.assertEqual(writer.sheet_client.clear_calls, [])

    def test_append_failure_returns_failure(self):
        headers = ["날짜", "캠페인", "수입"]
        existing_rows = []
        df = pd.DataFrame([{"날짜": "2026-05-22", "캠페인": "A", "수입": "100"}])
        parse_result = ParseResult(
            success=True,
            file_name="report.csv",
            dataframe=df,
            date_column_candidates=["날짜"],
        )
        writer = object.__new__(ReportWriter)
        writer.sheet_client = FakeSheetClient(headers, existing_rows, append_result=None)
        writer.sheet_client.update_sheet_data = lambda *args, **kwargs: None

        result = writer.write_report("spreadsheet-id", "수입", parse_result, dry_run=False)

        self.assertFalse(result["success"])
        self.assertEqual(result["rows_written"], 0)
        self.assertEqual(writer.sheet_client.clear_calls, [])

    def test_write_report_maps_naver_columns_to_existing_sheet_schema(self):
        headers = [
            "일별",
            "구분",
            "캠페인",
            "광고그룹",
            "PC/모바일 매체",
            "노출수",
            "클릭수",
            "총비용(VAT포함,원)",
            "평균노출순위",
            "전환수",
            "전환매출액(원)",
            "Year",
            "Month",
            "Week",
            "캠페인유형",
            "입력일",
        ]
        df = pd.DataFrame(
            [
                {
                    "일별": "2026.05.20.",
                    "캠페인유형": "파워링크",
                    "캠페인": "A",
                    "광고그룹": "G",
                    "PC/모바일 매체": "PC",
                    "노출수": "10",
                    "클릭수": "2",
                    "총비용": "22210",
                    "평균노출순위": "1.4",
                    "총 전환수": "5",
                    "총 전환매출액(원)": "0",
                }
            ]
        )
        parse_result = ParseResult(
            success=True,
            file_name="report.csv",
            dataframe=df,
            date_column_candidates=["일별"],
        )
        writer = object.__new__(ReportWriter)
        writer.sheet_client = FakeSheetClient(headers, [])

        result = writer.write_report("spreadsheet-id", "수입", parse_result, dry_run=False)

        self.assertTrue(result["success"])
        self.assertEqual(result["rows_written"], 1)
        self.assertEqual(
            writer.sheet_client.update_calls[0][2],
            [[
                "2026.05.20.",
                "파워링크",
                "A",
                "G",
                "PC",
                "10",
                "2",
                "22210",
                "1.4",
                "5",
                "0",
            ]],
        )
        self.assertEqual(writer.sheet_client.update_calls[0][1], "수입!A2:K2")
        self.assertEqual(writer.sheet_client.append_calls, [])

    def test_standard_raw_tabs_use_fixed_write_widths(self):
        headers = [f"col{i:02d}" for i in range(1, 16)]
        df = pd.DataFrame(
            [
                {
                    header: f"value-{index:02d}"
                    for index, header in enumerate(headers, start=1)
                }
            ]
        )
        parse_result = ParseResult(success=True, file_name="report.csv", dataframe=df)
        cases = [
            ("데일리SA_RAW", 11, "K"),
            ("위클리키워드SA_RAW", 12, "L"),
            ("데일리전환SA_RAW", 8, "H"),
        ]

        for tab_name, expected_width, end_col in cases:
            with self.subTest(tab_name=tab_name):
                writer = object.__new__(ReportWriter)
                writer.sheet_client = FakeSheetClient(headers, [], tab_name=tab_name)

                result = writer.write_report("spreadsheet-id", tab_name, parse_result, dry_run=False)

                self.assertTrue(result["success"])
                self.assertEqual(result["rows_written"], 1)
                self.assertEqual(
                    writer.sheet_client.update_calls[0][1],
                    f"{tab_name}!A2:{end_col}2",
                )
                self.assertEqual(len(writer.sheet_client.update_calls[0][2][0]), expected_width)
                self.assertEqual(writer.sheet_client.append_calls, [])

    def test_f_offset_raw_spreadsheet_writes_download_columns_to_configured_ranges(self):
        cases = [
            (
                "데일리SA_RAW",
                [
                    "년",
                    "월",
                    "주차",
                    "매체영역",
                    "-",
                    "일자",
                    "SA 구분",
                    "캠페인",
                    "그룹",
                    "디바이스",
                    " 노출 ",
                    " 클릭 ",
                    " 비용(VAT-) ",
                    " 총 전환수 ",
                    " 구매완료 전환매출액 ",
                    " 브랜드 분류 ",
                ],
                {
                    "일별": "2026.05.20.",
                    "캠페인유형": "파워링크",
                    "캠페인": "A",
                    "광고그룹": "G",
                    "PC/모바일 매체": "PC",
                    "노출수": "10",
                    "클릭수": "2",
                    "총비용": "22210",
                    "평균노출순위": "1.4",
                    "총 전환수": "5",
                    "구매완료 전환매출액(원)": "0",
                },
                "데일리SA_RAW!F2:O2",
                ["2026.05.20.", "파워링크", "A", "G", "PC", "10", "2", "22210", "5", "0"],
            ),
            (
                "위클리키워드SA_RAW",
                [
                    "년",
                    "월",
                    "주차",
                    "매체영역",
                    "-",
                    "주별",
                    "SA 구분",
                    "캠페인",
                    "그룹",
                    "검색어",
                    "디바이스",
                    " 노출 ",
                    " 클릭 ",
                    " 비용(VAT-) ",
                    " 전환수 ",
                    " 구매완료 전환매출액 ",
                    " 브랜드 분류 ",
                ],
                {
                    "주별": "2026.05.18.(월)주",
                    "캠페인유형": "파워링크",
                    "캠페인": "A",
                    "광고그룹": "G",
                    "검색어": "검색어 A",
                    "PC/모바일 매체": "PC",
                    "노출수": "10",
                    "클릭수": "1",
                    "총비용": "1100",
                    "평균노출순위": "1",
                    "총 전환수": "0",
                    "구매완료 전환매출액(원)": "2200",
                },
                "위클리키워드SA_RAW!F2:P2",
                ["2026.05.18.(월)주", "파워링크", "A", "G", "검색어 A", "PC", "10", "1", "1100", "0", "2200"],
            ),
            (
                "데일리전환SA_RAW",
                [
                    "년",
                    "월",
                    "주차",
                    "매체영역",
                    "-",
                    "일자",
                    "SA 구분",
                    "캠페인",
                    "그룹",
                    "디바이스",
                    "전환유형",
                    " 전환수 ",
                    " 전환매출액 ",
                    " 전환액션 ",
                ],
                {
                    "일별": "2026.05.20.",
                    "캠페인유형": "파워링크",
                    "캠페인": "A",
                    "광고그룹": "G",
                    "PC/모바일 매체": "PC",
                    "전환 유형": "신청 완료",
                    "총 전환수": "2",
                    "총 전환매출액(원)": "5500",
                },
                "데일리전환SA_RAW!F2:M2",
                ["2026.05.20.", "파워링크", "A", "G", "PC", "신청 완료", "2", "5500"],
            ),
        ]

        with patch.dict("os.environ", {"F_OFFSET_RAW_SPREADSHEET_IDS": "mars-sheet"}):
            for tab_name, headers, record, expected_range, expected_values in cases:
                with self.subTest(tab_name=tab_name):
                    parse_result = ParseResult(success=True, file_name="report.csv", dataframe=pd.DataFrame([record]))
                    writer = object.__new__(ReportWriter)
                    writer.sheet_client = FakeSheetClient(headers, [], tab_name=tab_name)

                    result = writer.write_report("mars-sheet", tab_name, parse_result, dry_run=False)

                    self.assertTrue(result["success"])
                    self.assertEqual(writer.sheet_client.update_calls[0][1], expected_range)
                    self.assertEqual(writer.sheet_client.update_calls[0][2], [expected_values])
                    self.assertEqual(writer.sheet_client.append_calls, [])

    def test_configured_spreadsheet_applies_vat_adjustment_to_raw_amount_columns(self):
        cases = [
            (
                "데일리SA_RAW",
                [
                    "일별",
                    "구분",
                    "캠페인",
                    "광고그룹",
                    "PC/모바일 매체",
                    "노출수",
                    "클릭수",
                    "총비용(VAT포함,원)",
                    "평균노출순위",
                    "전환수",
                    "전환매출액(원)",
                ],
                {
                    "일별": "2026.05.20.",
                    "캠페인유형": "파워링크",
                    "캠페인": "A",
                    "광고그룹": "G",
                    "PC/모바일 매체": "PC",
                    "노출수": "10",
                    "클릭수": "2",
                    "총비용": "22210",
                    "평균노출순위": "1.4",
                    "총 전환수": "5",
                    "총 전환매출액(원)": "11000",
                },
                {7: "20191", 10: "10000"},
            ),
            (
                "위클리키워드SA_RAW",
                [
                    "주별",
                    "구분",
                    "캠페인",
                    "광고그룹",
                    "키워드",
                    "PC/모바일 매체",
                    "노출수",
                    "클릭수",
                    "총비용(VAT포함,원)",
                    "평균노출순위",
                    "전환수",
                    "전환매출액(원)",
                ],
                {
                    "주별": "2026.05.18.(월)주",
                    "캠페인유형": "파워링크",
                    "캠페인": "A",
                    "광고그룹": "G",
                    "검색어": "검색어 A",
                    "PC/모바일 매체": "PC",
                    "노출수": "10",
                    "클릭수": "1",
                    "총비용": "1100",
                    "평균노출순위": "1",
                    "총 전환수": "0",
                    "구매완료 전환매출액(원)": "2200",
                },
                {8: "1000", 11: "2000"},
            ),
            (
                "데일리전환SA_RAW",
                ["일별", "캠페인유형", "캠페인", "광고그룹", "PC/모바일 매체", "전환 유형", "전환수", "전환매출액(원)"],
                {
                    "일별": "2026.05.20.",
                    "캠페인유형": "파워링크",
                    "캠페인": "A",
                    "광고그룹": "G",
                    "PC/모바일 매체": "PC",
                    "전환 유형": "신청 완료",
                    "총 전환수": "2",
                    "총 전환매출액(원)": "5500",
                },
                {7: "5000"},
            ),
        ]

        with patch.dict("os.environ", {"VAT_ADJUST_SPREADSHEET_IDS": "spreadsheet-id"}):
            for tab_name, headers, record, expected_cells in cases:
                with self.subTest(tab_name=tab_name):
                    parse_result = ParseResult(success=True, file_name="report.csv", dataframe=pd.DataFrame([record]))
                    writer = object.__new__(ReportWriter)
                    writer.sheet_client = FakeSheetClient(headers, [], tab_name=tab_name)

                    result = writer.write_report("spreadsheet-id", tab_name, parse_result, dry_run=False)

                    self.assertTrue(result["success"])
                    written_row = writer.sheet_client.update_calls[0][2][0]
                    for index, expected_value in expected_cells.items():
                        self.assertEqual(written_row[index], expected_value)
                    expected_update_calls = 2 if tab_name == "데일리SA_RAW" else 1
                    self.assertEqual(len(writer.sheet_client.update_calls), expected_update_calls)

    def test_vat_adjustment_is_limited_to_configured_spreadsheets_and_integer_values(self):
        headers = [
            "일별",
            "구분",
            "캠페인",
            "광고그룹",
            "PC/모바일 매체",
            "노출수",
            "클릭수",
            "총비용(VAT포함,원)",
            "평균노출순위",
            "전환수",
            "전환매출액(원)",
        ]
        record = {
            "일별": "2026.05.20.",
            "캠페인유형": "파워링크",
            "캠페인": "A",
            "광고그룹": "G",
            "PC/모바일 매체": "PC",
            "노출수": "10",
            "클릭수": "2",
            "총비용": "22210",
            "평균노출순위": "1.4",
            "총 전환수": "5",
            "총 전환매출액(원)": "1000.5",
        }
        parse_result = ParseResult(success=True, file_name="report.csv", dataframe=pd.DataFrame([record]))

        with patch.dict("os.environ", {"VAT_ADJUST_SPREADSHEET_IDS": "other-spreadsheet"}):
            writer = object.__new__(ReportWriter)
            writer.sheet_client = FakeSheetClient(headers, [], tab_name="데일리SA_RAW")
            result = writer.write_report("spreadsheet-id", "데일리SA_RAW", parse_result, dry_run=False)
            self.assertTrue(result["success"])
            self.assertEqual(writer.sheet_client.update_calls[0][2][0][7], "22210")
            self.assertEqual(writer.sheet_client.update_calls[0][2][0][10], "1000.5")
            self.assertEqual(len(writer.sheet_client.update_calls), 2)

        with patch.dict("os.environ", {"VAT_ADJUST_SPREADSHEET_IDS": "spreadsheet-id"}):
            writer = object.__new__(ReportWriter)
            writer.sheet_client = FakeSheetClient(headers, [], tab_name="데일리SA_RAW")
            result = writer.write_report("spreadsheet-id", "데일리SA_RAW", parse_result, dry_run=False)
            self.assertTrue(result["success"])
            self.assertEqual(writer.sheet_client.update_calls[0][2][0][7], "20191")
            self.assertEqual(writer.sheet_client.update_calls[0][2][0][10], "1000.5")
            self.assertEqual(len(writer.sheet_client.update_calls), 2)

    def test_raw_append_position_ignores_formula_only_rows_after_raw_columns(self):
        headers = [
            "일별",
            "구분",
            "캠페인",
            "광고그룹",
            "PC/모바일 매체",
            "노출수",
            "클릭수",
            "총비용(VAT포함,원)",
            "평균노출순위",
            "전환수",
            "전환매출액(원)",
            "Year",
            "Month",
            "Week",
            "캠페인유형",
        ]
        existing_rows = [
            ["2026.05.21.", "파워링크", "A", "G", "PC", "10", "2", "1000", "1", "0", "0", "2026", "05월", "05월 3주", "파워링크"],
            ["2026.05.22.", "파워링크", "A", "G", "PC", "20", "3", "2000", "1", "1", "0", "2026", "05월", "05월 3주", "파워링크"],
            ["", "", "", "", "", "", "", "", "", "", "", "2026", "05월", "05월 4주", ""],
            ["", "", "", "", "", "", "", "", "", "", "", "2026", "05월", "05월 4주", ""],
        ]
        df = pd.DataFrame(
            [
                {
                    "일별": "2026.05.23.",
                    "캠페인유형": "파워링크",
                    "캠페인": "A",
                    "광고그룹": "G",
                    "PC/모바일 매체": "PC",
                    "노출수": "30",
                    "클릭수": "4",
                    "총비용": "3000",
                    "평균노출순위": "1",
                    "총 전환수": "2",
                    "총 전환매출액(원)": "0",
                }
            ]
        )
        parse_result = ParseResult(success=True, file_name="report.csv", dataframe=df)
        writer = object.__new__(ReportWriter)
        writer.sheet_client = FakeSheetClient(headers, existing_rows, tab_name="데일리SA_RAW")

        result = writer.write_report("spreadsheet-id", "데일리SA_RAW", parse_result, dry_run=False)

        self.assertTrue(result["success"])
        self.assertEqual(result["rows_written"], 1)
        self.assertEqual(writer.sheet_client.update_calls[0][1], "데일리SA_RAW!A4:K4")
        self.assertEqual(writer.sheet_client.append_calls, [])

    def test_raw_append_position_uses_gap_after_latest_date_before_orphaned_older_rows(self):
        headers = ["일별", "캠페인", "수입"]
        existing_rows = [
            ["2026-06-01", "A", "100"],
            ["", "", ""],
            ["", "", ""],
            ["", "", ""],
            ["2026-05-20", "B", "200"],
        ]
        df = pd.DataFrame([{"일별": "2026-06-02", "캠페인": "C", "수입": "300"}])
        parse_result = ParseResult(success=True, file_name="report.csv", dataframe=df)
        writer = object.__new__(ReportWriter)
        writer.sheet_client = FakeSheetClient(headers, existing_rows)

        result = writer.write_report("spreadsheet-id", "수입", parse_result, dry_run=False)

        self.assertTrue(result["success"])
        self.assertEqual(result["rows_written"], 1)
        self.assertEqual(writer.sheet_client.update_calls[0][1], "수입!A3:C3")
        self.assertEqual(writer.sheet_client.append_calls, [])

    def test_duplicate_check_normalizes_existing_formatted_numbers(self):
        headers = [
            "일별",
            "구분",
            "캠페인",
            "광고그룹",
            "PC/모바일 매체",
            "노출수",
            "클릭수",
            "총비용(VAT포함,원)",
            "평균노출순위",
            "전환수",
            "전환매출액(원)",
            "Year",
            "Month",
            "Week",
            "캠페인유형",
        ]
        existing_rows = [[
            "2026.05.20.",
            "파워링크",
            "A",
            "G",
            "PC",
            "10",
            "2",
            "22,210.0",
            "1.40",
            "5.0",
            "0",
            "2026",
            "05월",
            "05월 3주",
            "파워링크",
        ]]
        df = pd.DataFrame(
            [
                {
                    "일별": "2026.05.20.",
                    "캠페인유형": "파워링크",
                    "캠페인": "A",
                    "광고그룹": "G",
                    "PC/모바일 매체": "PC",
                    "노출수": "10",
                    "클릭수": "2",
                    "총비용": "22210",
                    "평균노출순위": "1.4",
                    "총 전환수": "5",
                    "총 전환매출액(원)": "0",
                }
            ]
        )
        parse_result = ParseResult(
            success=True,
            file_name="report.csv",
            dataframe=df,
            date_column_candidates=["일별"],
        )
        writer = object.__new__(ReportWriter)
        writer.sheet_client = FakeSheetClient(headers, existing_rows)

        result = writer.write_report("spreadsheet-id", "수입", parse_result, dry_run=False)

        self.assertTrue(result["success"])
        self.assertEqual(result["rows_written"], 0)
        self.assertEqual(writer.sheet_client.append_calls, [])

    def test_duplicate_check_ignores_changed_metric_values(self):
        headers = [
            "일별",
            "구분",
            "캠페인",
            "광고그룹",
            "PC/모바일 매체",
            "노출수",
            "클릭수",
            "총비용(VAT포함,원)",
            "평균노출순위",
            "전환수",
            "전환매출액(원)",
        ]
        existing_rows = [[
            "2026.05.21.",
            "파워링크",
            "A",
            "G",
            "PC",
            "10",
            "2",
            "1000",
            "1.4",
            "1",
            "10000",
        ]]
        df = pd.DataFrame(
            [
                {
                    "일별": "2026.05.21.",
                    "캠페인유형": "파워링크",
                    "캠페인": "A",
                    "광고그룹": "G",
                    "PC/모바일 매체": "PC",
                    "노출수": "12",
                    "클릭수": "3",
                    "총비용": "1200",
                    "평균노출순위": "1.2",
                    "총 전환수": "2",
                    "총 전환매출액(원)": "20000",
                }
            ]
        )
        parse_result = ParseResult(success=True, file_name="report.csv", dataframe=df)
        writer = object.__new__(ReportWriter)
        writer.sheet_client = FakeSheetClient(headers, existing_rows)

        result = writer.write_report("spreadsheet-id", "수입", parse_result, dry_run=False)

        self.assertTrue(result["success"])
        self.assertEqual(result["rows_written"], 0)
        self.assertEqual(writer.sheet_client.append_calls, [])

    def test_duplicate_check_ignores_blank_derived_and_duplicate_alias_columns(self):
        headers = [
            "일별",
            "구분",
            "캠페인",
            "광고그룹",
            "PC/모바일 매체",
            "노출수",
            "클릭수",
            "총비용(VAT포함,원)",
            "평균노출순위",
            "전환수",
            "전환매출액(원)",
            "Year",
            "Month",
            "Week",
            "캠페인유형",
        ]
        existing_rows = [[
            "2026.05.21.",
            "파워링크",
            "A",
            "G",
            "PC",
            "10",
            "2",
            "1000",
            "1.4",
            "1",
            "10000",
            "",
            "",
            "",
            "",
        ]]
        df = pd.DataFrame(
            [
                {
                    "일별": "2026.05.21.",
                    "캠페인유형": "파워링크",
                    "캠페인": "A",
                    "광고그룹": "G",
                    "PC/모바일 매체": "PC",
                    "노출수": "10",
                    "클릭수": "2",
                    "총비용": "1000",
                    "평균노출순위": "1.4",
                    "총 전환수": "1",
                    "총 전환매출액(원)": "10000",
                }
            ]
        )
        parse_result = ParseResult(success=True, file_name="report.csv", dataframe=df)
        writer = object.__new__(ReportWriter)
        writer.sheet_client = FakeSheetClient(headers, existing_rows)

        result = writer.write_report("spreadsheet-id", "수입", parse_result, dry_run=False)

        self.assertTrue(result["success"])
        self.assertEqual(result["rows_written"], 0)
        self.assertEqual(writer.sheet_client.append_calls, [])

    def test_duplicate_check_normalizes_date_formats(self):
        headers = ["일별", "구분", "캠페인", "광고그룹", "PC/모바일 매체", "노출수"]
        existing_rows = [["2026-05-21", "파워링크", "A", "G", "PC", "10"]]
        df = pd.DataFrame(
            [
                {
                    "일별": "2026.05.21.",
                    "캠페인유형": "파워링크",
                    "캠페인": "A",
                    "광고그룹": "G",
                    "PC/모바일 매체": "PC",
                    "노출수": "99",
                }
            ]
        )
        parse_result = ParseResult(success=True, file_name="report.csv", dataframe=df)
        writer = object.__new__(ReportWriter)
        writer.sheet_client = FakeSheetClient(headers, existing_rows)

        result = writer.write_report("spreadsheet-id", "수입", parse_result, dry_run=False)

        self.assertTrue(result["success"])
        self.assertEqual(result["rows_written"], 0)
        self.assertEqual(writer.sheet_client.append_calls, [])

    def test_search_term_and_keyword_headers_are_treated_as_same_field(self):
        headers = [
            "주별",
            "구분",
            "캠페인",
            "광고그룹",
            "키워드",
            "PC/모바일 매체",
            "노출수",
            "클릭수",
            "총비용(VAT포함,원)",
            "평균노출순위",
            "전환수",
            "전환매출액(원)",
        ]
        df = pd.DataFrame(
            [
                {
                    "주별": "2026.05.18.(월)주",
                    "캠페인유형": "파워링크",
                    "캠페인": "A",
                    "광고그룹": "G",
                    "검색어": "검색어 A",
                    "PC/모바일 매체": "PC",
                    "노출수": "10",
                    "클릭수": "1",
                    "총비용": "1000",
                    "평균노출순위": "1",
                    "총 전환수": "0",
                    "구매완료 전환매출액(원)": "0",
                }
            ]
        )
        parse_result = ParseResult(success=True, file_name="report.csv", dataframe=df)
        writer = object.__new__(ReportWriter)
        writer.sheet_client = FakeSheetClient(headers, [])

        result = writer.write_report("spreadsheet-id", "수입", parse_result, dry_run=False)

        self.assertTrue(result["success"])
        self.assertEqual(result["rows_written"], 1)
        self.assertEqual(writer.sheet_client.update_calls[0][2][0][4], "검색어 A")
        self.assertEqual(writer.sheet_client.append_calls, [])

    def test_conversion_type_header_spacing_is_treated_as_same_field(self):
        headers = ["일별", "캠페인유형", "캠페인", "광고그룹", "PC/모바일 매체", "전환유형", "전환수", "전환매출액(원)"]
        df = pd.DataFrame(
            [
                {
                    "일별": "2026.05.20.",
                    "캠페인유형": "파워링크",
                    "캠페인": "A",
                    "광고그룹": "G",
                    "PC/모바일 매체": "PC",
                    "전환 유형": "신청 완료",
                    "총 전환수": "2",
                    "총 전환매출액(원)": "0",
                }
            ]
        )
        parse_result = ParseResult(success=True, file_name="report.csv", dataframe=df)
        writer = object.__new__(ReportWriter)
        writer.sheet_client = FakeSheetClient(headers, [])

        result = writer.write_report("spreadsheet-id", "수입", parse_result, dry_run=False)

        self.assertTrue(result["success"])
        self.assertEqual(result["rows_written"], 1)
        self.assertEqual(writer.sheet_client.update_calls[0][2][0][5], "신청 완료")
        self.assertEqual(writer.sheet_client.append_calls, [])

    def test_conversion_cost_header_is_mapped_to_existing_schema(self):
        headers = ["일별", "구분", "캠페인", "광고그룹", "PC/모바일 매체", "전환당비용"]
        df = pd.DataFrame(
            [
                {
                    "일별": "2026.05.20.",
                    "캠페인유형": "파워링크",
                    "캠페인": "A",
                    "광고그룹": "G",
                    "PC/모바일 매체": "PC",
                    "총 전환당비용(원)": "1000",
                }
            ]
        )
        parse_result = ParseResult(success=True, file_name="report.csv", dataframe=df)
        writer = object.__new__(ReportWriter)
        writer.sheet_client = FakeSheetClient(headers, [])

        result = writer.write_report("spreadsheet-id", "수입", parse_result, dry_run=False)

        self.assertTrue(result["success"])
        self.assertEqual(result["rows_written"], 1)
        self.assertEqual(writer.sheet_client.update_calls[0][2][0][5], "1000")
        self.assertEqual(writer.sheet_client.append_calls, [])

    def test_total_conversion_cost_header_without_unit_is_mapped(self):
        headers = ["일별", "구분", "캠페인", "광고그룹", "PC/모바일 매체", "총 전환당비용"]
        df = pd.DataFrame(
            [
                {
                    "일별": "2026.05.20.",
                    "캠페인유형": "파워링크",
                    "캠페인": "A",
                    "광고그룹": "G",
                    "PC/모바일 매체": "PC",
                    "총 전환당비용(원)": "1000",
                }
            ]
        )
        parse_result = ParseResult(success=True, file_name="report.csv", dataframe=df)
        writer = object.__new__(ReportWriter)
        writer.sheet_client = FakeSheetClient(headers, [])

        result = writer.write_report("spreadsheet-id", "수입", parse_result, dry_run=False)

        self.assertTrue(result["success"])
        self.assertEqual(result["rows_written"], 1)
        self.assertEqual(writer.sheet_client.update_calls[0][2][0][5], "1000")
        self.assertEqual(writer.sheet_client.append_calls, [])

    def test_total_conversion_revenue_without_unit_is_mapped(self):
        headers = ["일별", "캠페인유형", "캠페인", "광고그룹", "PC/모바일 매체", "전환 유형", "전환수", "총 전환매출액"]
        df = pd.DataFrame(
            [
                {
                    "일별": "2026.05.20.",
                    "캠페인유형": "파워링크",
                    "캠페인": "A",
                    "광고그룹": "G",
                    "PC/모바일 매체": "PC",
                    "전환 유형": "신청 완료",
                    "총 전환수": "2",
                    "총 전환매출액(원)": "5000",
                }
            ]
        )
        parse_result = ParseResult(success=True, file_name="report.csv", dataframe=df)
        writer = object.__new__(ReportWriter)
        writer.sheet_client = FakeSheetClient(headers, [])

        result = writer.write_report("spreadsheet-id", "수입", parse_result, dry_run=False)

        self.assertTrue(result["success"])
        self.assertEqual(result["rows_written"], 1)
        self.assertEqual(writer.sheet_client.update_calls[0][2][0][7], "5000")
        self.assertEqual(writer.sheet_client.append_calls, [])

    def test_download_date_write_can_be_skipped_by_account_id(self):
        headers = ["일별", "캠페인", "수입"]
        df = pd.DataFrame([{"일별": "2026-06-09", "캠페인": "A", "수입": "100"}])
        parse_result = ParseResult(success=True, file_name="report.csv", dataframe=df)
        writer = object.__new__(ReportWriter)
        writer.sheet_client = FakeSheetClient(headers, [], tab_name="데일리SA_RAW")

        with patch.dict(
            "os.environ",
            {
                "DOWNLOAD_DATE_SKIP_ACCOUNT_IDS": "1899219",
                "DOWNLOAD_DATE_Q_COLUMN_ACCOUNT_IDS": "",
            },
        ):
            result = writer.write_report(
                "spreadsheet-id",
                "데일리SA_RAW",
                parse_result,
                dry_run=False,
                account_id="1899219",
            )

        self.assertTrue(result["success"])
        self.assertEqual(result["rows_written"], 1)
        self.assertEqual(writer.sheet_client.update_calls[0][1], "데일리SA_RAW!A2:C2")
        self.assertEqual(len(writer.sheet_client.update_calls), 1)

    def test_download_date_q_column_can_be_selected_by_account_id(self):
        headers = ["일별", "캠페인", "수입"]
        df = pd.DataFrame([{"일별": "2026-06-09", "캠페인": "A", "수입": "100"}])
        parse_result = ParseResult(success=True, file_name="report.csv", dataframe=df)
        writer = object.__new__(ReportWriter)
        writer.sheet_client = FakeSheetClient(headers, [], tab_name="데일리SA_RAW")

        with patch.dict(
            "os.environ",
            {
                "DOWNLOAD_DATE_SKIP_ACCOUNT_IDS": "",
                "DOWNLOAD_DATE_Q_COLUMN_ACCOUNT_IDS": "1245865",
            },
        ):
            result = writer.write_report(
                "spreadsheet-id",
                "데일리SA_RAW",
                parse_result,
                dry_run=False,
                account_id="1245865",
            )

        self.assertTrue(result["success"])
        self.assertEqual(result["rows_written"], 1)
        self.assertEqual(writer.sheet_client.update_calls[0][1], "데일리SA_RAW!A2:C2")
        self.assertEqual(writer.sheet_client.update_calls[1][1], "데일리SA_RAW!Q2")
        self.assertEqual(len(writer.sheet_client.update_calls), 2)


if __name__ == "__main__":
    unittest.main()
