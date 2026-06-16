import logging
import argparse
import os
from dotenv import load_dotenv
import datetime
import re
import unicodedata
from decimal import Decimal, InvalidOperation, ROUND_FLOOR
import pandas as pd
from src.error_logger import ErrorLogger, append_download_log, append_error_log
from src.google_sheet_client import GoogleSheetClient
from src.report_parser import ParseResult
from src.models import DEFAULT_REPORT_CONFIGS, EXPECTED_COLUMNS_REPORTS, STANDARD_REPORT_NAMES, normalize_report_destination

# .env 로드
load_dotenv()

logger = logging.getLogger(__name__)

TARGET_HEADER_ALIASES = {
    "구분": ["캠페인유형"],
    "SA 구분": ["캠페인유형", "구분"],
    "일자": ["일별", "날짜"],
    "그룹": ["광고그룹"],
    "디바이스": ["PC/모바일 매체", "매체"],
    "노출": ["노출수"],
    "클릭": ["클릭수"],
    "비용(VAT-)": ["총비용", "총비용(VAT포함,원)"],
    "검색어": ["키워드"],
    "키워드": ["검색어"],
    "총비용(VAT포함,원)": ["총비용"],
    "전환수": ["총 전환수"],
    "전환 유형": ["전환유형"],
    "전환유형": ["전환 유형"],
    "총 전환매출액": ["총 전환매출액(원)", "구매완료 전환매출액(원)"],
    "전환매출액(원)": ["총 전환매출액(원)", "구매완료 전환매출액(원)"],
    "전환매출액": ["총 전환매출액(원)", "구매완료 전환매출액(원)"],
    "구매완료 전환매출액": ["구매완료 전환매출액(원)", "총 전환매출액(원)"],
    "구매완료 전환매출액(원)": ["구매완료 전환매출액(원)", "총 전환매출액(원)"],
    "총 전환매출액(원)": ["총 전환매출액(원)", "구매완료 전환매출액(원)"],
    "총 전환당비용": ["총 전환당비용(원)"],
    "전환당비용": ["총 전환당비용(원)", "총 전환당비용"],
    "전환당비용(원)": ["총 전환당비용(원)", "총 전환당비용"],
}

DATE_SOURCE_COLUMNS = ("일별", "주별", "날짜", "기간")
DERIVED_HEADERS = {"Year", "Month", "Week"}

RAW_WRITE_COLUMNS_BY_TAB = {
    "\ub370\uc77c\ub9acSA_RAW": 11,
    "\uc704\ud074\ub9ac\ud0a4\uc6cc\ub4dcSA_RAW": 12,
    "\ub370\uc77c\ub9ac\uc804\ud658SA_RAW": 8,
}

F_OFFSET_RAW_WRITE_START_COLUMN = 6
F_OFFSET_RAW_WRITE_COLUMNS_BY_TAB = {
    "\ub370\uc77c\ub9acSA_RAW": 10,
    "\uc704\ud074\ub9ac\ud0a4\uc6cc\ub4dcSA_RAW": 11,
    "\ub370\uc77c\ub9ac\uc804\ud658SA_RAW": 8,
}
F_OFFSET_IGNORED_SOURCE_COLUMNS_BY_TAB = {
    "\ub370\uc77c\ub9acSA_RAW": {"평균노출순위"},
    "\uc704\ud074\ub9ac\ud0a4\uc6cc\ub4dcSA_RAW": {"평균노출순위"},
}

VAT_RATE = Decimal("1.1")
VAT_ADJUST_COLUMNS_BY_TAB = {
    "\ub370\uc77c\ub9acSA_RAW": (8, 11),
    "\uc704\ud074\ub9ac\ud0a4\uc6cc\ub4dcSA_RAW": (9, 12),
    "\ub370\uc77c\ub9ac\uc804\ud658SA_RAW": (8,),
}

def _normalize_header_text(value) -> str:
    text = unicodedata.normalize("NFKC", str(value))
    return text.replace("\ufeff", "").replace(" ", "").replace("_", "").strip().lower()

KEY_HEADER_ALIASES = {
    "date": ["일별", "날짜", "일자"],
    "period": ["주별", "기간"],
    "campaign_type": ["캠페인유형", "구분", "SA 구분"],
    "campaign": ["캠페인"],
    "ad_group": ["광고그룹", "그룹"],
    "media": ["PC/모바일 매체", "매체", "디바이스"],
    "keyword": ["키워드", "검색어"],
    "conversion_type": ["전환 유형", "전환유형"],
}

KEY_HEADER_BY_NORMALIZED = {
    _normalize_header_text(alias): canonical
    for canonical, aliases in KEY_HEADER_ALIASES.items()
    for alias in aliases
}

NON_KEY_HEADERS = {
    "노출수",
    "노출",
    "클릭수",
    "클릭",
    "총비용",
    "총비용(VAT포함,원)",
    "비용(VAT-)",
    "평균노출순위",
    "전환수",
    "총 전환수",
    "직접 전환수",
    "간접 전환수",
    "구매완료 전환수",
    "전환매출액",
    "전환매출액(원)",
    "총 전환매출액",
    "총 전환매출액(원)",
    "구매완료 전환매출액",
    "구매완료 전환매출액(원)",
    "전환당비용",
    "전환당비용(원)",
    "총 전환당비용",
    "총 전환당비용(원)",
    "평균클릭비용",
    "평균 클릭 비용",
    "CPC",
    "CPM",
    "CTR",
    "클릭률",
    "전환율",
    "광고수익률",
    "ROAS",
    "노출점유율",
    "순위",
    "평균순위",
    "수입",
    "Year",
    "Month",
    "Week",
    "입력일",
    "메모",
    "담당자",
}

NON_KEY_NORMALIZED_HEADERS = {_normalize_header_text(header) for header in NON_KEY_HEADERS}
DATE_KEY_CANONICALS = {"date", "period"}

def _allow_existing_or_older_date_append() -> bool:
    return os.getenv("ALLOW_EXISTING_OR_OLDER_DATE_APPEND", "false").strip().lower() in {"1", "true", "yes", "y"}

def _allow_non_raw_target_tab() -> bool:
    return os.getenv("ALLOW_NON_RAW_TARGET_TAB", "false").strip().lower() in {"1", "true", "yes", "y"}

def _max_raw_write_columns() -> int:
    value = os.getenv("RAW_WRITE_MAX_COLUMNS", "11").strip()
    try:
        return max(1, int(value))
    except ValueError:
        return 11

def _max_raw_write_columns_for_tab(tab_name: str) -> int:
    return RAW_WRITE_COLUMNS_BY_TAB.get(str(tab_name).strip(), _max_raw_write_columns())

def _f_offset_raw_spreadsheet_ids() -> set[str]:
    return {
        item.strip()
        for item in os.getenv("F_OFFSET_RAW_SPREADSHEET_IDS", "").replace("\n", ",").split(",")
        if item.strip()
    }

def _uses_f_offset_raw_layout(spreadsheet_id: str) -> bool:
    target_ids = _f_offset_raw_spreadsheet_ids()
    spreadsheet_id = str(spreadsheet_id or "").strip()
    return "*" in target_ids or spreadsheet_id in target_ids

def _raw_write_start_column(spreadsheet_id: str) -> int:
    if _uses_f_offset_raw_layout(spreadsheet_id):
        return F_OFFSET_RAW_WRITE_START_COLUMN
    return 1

def _max_raw_write_columns_for_layout(tab_name: str, spreadsheet_id: str) -> int:
    if _uses_f_offset_raw_layout(spreadsheet_id):
        return F_OFFSET_RAW_WRITE_COLUMNS_BY_TAB.get(str(tab_name).strip(), _max_raw_write_columns_for_tab(tab_name))
    return _max_raw_write_columns_for_tab(tab_name)

def _ignored_source_columns_for_layout(spreadsheet_id: str, tab_name: str) -> set[str]:
    if not _uses_f_offset_raw_layout(spreadsheet_id):
        return set()
    return {
        _normalize_header_text(column)
        for column in F_OFFSET_IGNORED_SOURCE_COLUMNS_BY_TAB.get(str(tab_name).strip(), set())
    }

def _vat_adjust_spreadsheet_ids() -> set[str]:
    return {
        item.strip()
        for item in os.getenv("VAT_ADJUST_SPREADSHEET_IDS", "").replace("\n", ",").split(",")
        if item.strip()
    }

def _should_apply_vat_adjustment(spreadsheet_id: str) -> bool:
    target_ids = _vat_adjust_spreadsheet_ids()
    spreadsheet_id = str(spreadsheet_id or "").strip()
    return "*" in target_ids or spreadsheet_id in target_ids

def _env_id_set(name: str) -> set[str]:
    return {
        item.strip()
        for item in os.getenv(name, "").replace("\n", ",").split(",")
        if item.strip()
    }

def _download_date_skip_spreadsheet_ids() -> set[str]:
    return _env_id_set("DOWNLOAD_DATE_SKIP_SPREADSHEET_IDS")

def _download_date_q_column_spreadsheet_ids() -> set[str]:
    return _env_id_set("DOWNLOAD_DATE_Q_COLUMN_SPREADSHEET_IDS")

def _download_date_skip_account_ids() -> set[str]:
    return _env_id_set("DOWNLOAD_DATE_SKIP_ACCOUNT_IDS")

def _download_date_q_column_account_ids() -> set[str]:
    return _env_id_set("DOWNLOAD_DATE_Q_COLUMN_ACCOUNT_IDS")

def _download_date_column_for_sheet(spreadsheet_id: str, account_id: str = "") -> str | None:
    """Returns column letter (P or Q) for download date, or None to skip."""
    sid = str(spreadsheet_id or "").strip()
    aid = str(account_id or "").strip()
    if aid in _download_date_skip_account_ids() or sid in _download_date_skip_spreadsheet_ids():
        return None
    if aid in _download_date_q_column_account_ids() or sid in _download_date_q_column_spreadsheet_ids():
        return "Q"
    return "P"

class ReportWriter:
    def __init__(self):
        self.sheet_client = GoogleSheetClient()

    @staticmethod
    def _column_letter(n: int) -> str:
        result = ""
        while n > 0:
            n, remainder = divmod(n - 1, 26)
            result = chr(65 + remainder) + result
        return result

    @staticmethod
    def _sheet_cell(value) -> str:
        if pd.isna(value):
            return ""
        return str(value)

    @classmethod
    def _normalize_key_cell(cls, value) -> str:
        text = unicodedata.normalize("NFKC", cls._sheet_cell(value))
        text = text.replace("\ufeff", "").strip()
        text = re.sub(r"\s+", " ", text)

        date_match = re.search(r"(\d{4})[\.\-/]\s*(\d{1,2})[\.\-/]\s*(\d{1,2})", text)
        if date_match:
            year, month, day = (int(part) for part in date_match.groups())
            return f"{year:04d}-{month:02d}-{day:02d}"

        if re.fullmatch(r"-?\d[\d,]*(\.\d+)?", text):
            try:
                normalized = Decimal(text.replace(",", "")).normalize()
                return format(normalized, "f")
            except InvalidOperation:
                return text
        return text

    @classmethod
    def _row_key(cls, row: list, headers_or_indexes: list, key_canonicals: list[str] | None = None) -> tuple:
        if key_canonicals is None:
            indexes = headers_or_indexes
            return tuple(cls._normalize_key_cell(row[i]) if i < len(row) else "" for i in indexes)

        values_by_canonical = {canonical: [] for canonical in key_canonicals}
        for idx, header in enumerate(headers_or_indexes):
            canonical = cls._key_canonical_for_header(header)
            if canonical not in values_by_canonical:
                continue
            value = cls._normalize_key_cell(row[idx]) if idx < len(row) else ""
            if value:
                values_by_canonical[canonical].append(value)

        return tuple(
            values_by_canonical[canonical][0] if values_by_canonical[canonical] else ""
            for canonical in key_canonicals
        )

    @staticmethod
    def _parse_report_date(value):
        match = re.search(r"(\d{4})[\.\-/]\s*(\d{1,2})[\.\-/]\s*(\d{1,2})", str(value))
        if not match:
            return None
        year, month, day = (int(part) for part in match.groups())
        try:
            return datetime.date(year, month, day)
        except ValueError:
            return None

    @classmethod
    def _date_from_record(cls, record: dict):
        for column in DATE_SOURCE_COLUMNS:
            if column in record:
                parsed = cls._parse_report_date(record.get(column))
                if parsed:
                    return parsed
        return None

    @staticmethod
    def _week_label(report_date: datetime.date) -> str:
        # Monday-Sunday week labels follow the month that owns most days in the week.
        anchor = report_date - datetime.timedelta(days=report_date.weekday()) + datetime.timedelta(days=3)
        week_number = ((anchor.day - 1) // 7) + 1
        return f"{anchor.month:02d}월 {week_number}주"

    @classmethod
    def _derived_value(cls, header: str, record: dict) -> str:
        report_date = cls._date_from_record(record)
        if not report_date:
            return ""
        if header == "Year":
            return str(report_date.year)
        if header == "Month":
            return f"{report_date.month:02d}월"
        if header == "Week":
            return cls._week_label(report_date)
        return ""

    @classmethod
    def _source_for_target_header(cls, header: str, columns) -> str | None:
        if header in columns:
            return header
        normalized_columns = {_normalize_header_text(column): column for column in columns}
        normalized_header = _normalize_header_text(header)
        if normalized_header in normalized_columns:
            return normalized_columns[normalized_header]
        aliases = TARGET_HEADER_ALIASES.get(header, [])
        if not aliases:
            aliases = next(
                (
                    target_aliases
                    for target_header, target_aliases in TARGET_HEADER_ALIASES.items()
                    if _normalize_header_text(target_header) == normalized_header
                ),
                [],
            )
        for source in aliases:
            if source in columns:
                return source
            normalized_source = _normalize_header_text(source)
            if normalized_source in normalized_columns:
                return normalized_columns[normalized_source]
        return None

    @classmethod
    def _source_column_is_represented(cls, source_column: str, headers: list) -> bool:
        if source_column in headers:
            return True
        normalized_source = _normalize_header_text(source_column)
        if normalized_source in {_normalize_header_text(header) for header in headers}:
            return True
        return any(cls._source_for_target_header(header, [source_column]) is not None for header in headers)

    @classmethod
    def _row_for_headers(cls, record: dict, headers: list) -> list:
        columns = set(record.keys())
        row = []
        for header in headers:
            source = cls._source_for_target_header(header, columns)
            if source is not None:
                row.append(cls._sheet_cell(record.get(source, "")))
            elif header in DERIVED_HEADERS:
                row.append(cls._derived_value(header, record))
            else:
                row.append("")
        return row

    @classmethod
    def _comparison_indexes(cls, headers: list, columns) -> list[int]:
        columns = set(columns)
        return [
            idx
            for idx, header in enumerate(headers)
            if cls._source_for_target_header(header, columns) is not None
            and cls._key_canonical_for_header(header) is not None
        ]

    @classmethod
    def _key_canonical_for_header(cls, header: str) -> str | None:
        normalized_header = _normalize_header_text(header)
        if normalized_header in NON_KEY_NORMALIZED_HEADERS:
            return None
        return KEY_HEADER_BY_NORMALIZED.get(normalized_header, f"column:{normalized_header}")

    @classmethod
    def _comparison_key_canonicals(cls, headers: list, columns) -> list[str]:
        columns = set(columns)
        key_canonicals = []
        for header in headers:
            if cls._source_for_target_header(header, columns) is None:
                continue
            canonical = cls._key_canonical_for_header(header)
            if canonical is None or canonical in key_canonicals:
                continue
            key_canonicals.append(canonical)
        return key_canonicals

    @classmethod
    def _date_from_row(cls, row: list, headers: list):
        for idx, header in enumerate(headers):
            if cls._key_canonical_for_header(header) not in DATE_KEY_CANONICALS:
                continue
            value = row[idx] if idx < len(row) else ""
            parsed = cls._parse_report_date(value)
            if parsed:
                return parsed
        return None

    @classmethod
    def _max_existing_report_date(cls, headers: list, existing_rows: list[list]):
        parsed_dates = [
            parsed
            for row in existing_rows
            if (parsed := cls._date_from_row(row, headers)) is not None
        ]
        return max(parsed_dates) if parsed_dates else None

    @classmethod
    def _new_rows_for_append(
        cls,
        df: pd.DataFrame,
        headers: list,
        existing_rows: list[list],
        spreadsheet_id: str = "",
        tab_name: str = "",
    ) -> list[list]:
        append_rows, _ = cls._new_rows_for_append_with_stats(
            df,
            headers,
            existing_rows,
            spreadsheet_id=spreadsheet_id,
            tab_name=tab_name,
        )
        return append_rows

    @classmethod
    def _new_rows_for_append_with_stats(
        cls,
        df: pd.DataFrame,
        headers: list,
        existing_rows: list[list],
        spreadsheet_id: str = "",
        tab_name: str = "",
    ) -> tuple[list[list], dict]:
        stats = {
            "candidate_rows": len(df),
            "duplicate_rows": 0,
            "queued_duplicate_rows": 0,
            "skipped_existing_or_older_date_rows": 0,
            "existing_max_date": None,
            "key_columns": [],
            "allow_existing_or_older_date_append": _allow_existing_or_older_date_append(),
            "sorted_by_date": False,
        }
        ignored_columns = _ignored_source_columns_for_layout(spreadsheet_id, tab_name)
        missing_columns = [
            col
            for col in df.columns
            if _normalize_header_text(col) not in ignored_columns
            and not cls._source_column_is_represented(col, headers)
        ]
        if missing_columns:
            raise ValueError(
                "Existing sheet headers do not contain report columns: "
                + ", ".join(str(col) for col in missing_columns)
            )

        key_canonicals = cls._comparison_key_canonicals(headers, df.columns)
        stats["key_columns"] = key_canonicals
        max_existing_date = cls._max_existing_report_date(headers, existing_rows)
        stats["existing_max_date"] = max_existing_date.isoformat() if max_existing_date else ""

        if key_canonicals:
            existing_keys = {cls._row_key(row, headers, key_canonicals) for row in existing_rows}
        else:
            compare_indexes = cls._comparison_indexes(headers, df.columns)
            existing_keys = {cls._row_key(row, compare_indexes) for row in existing_rows}
        append_rows = []
        queued_keys = set()

        for record in df.to_dict(orient="records"):
            row = cls._row_for_headers(record, headers)
            if key_canonicals:
                key = cls._row_key(row, headers, key_canonicals)
            else:
                key = cls._row_key(row, compare_indexes)

            if key in existing_keys:
                stats["duplicate_rows"] += 1
                continue

            row_date = cls._date_from_row(row, headers)
            if (
                not stats["allow_existing_or_older_date_append"]
                and max_existing_date
                and row_date
                and row_date <= max_existing_date
            ):
                stats["skipped_existing_or_older_date_rows"] += 1
                continue

            if key in queued_keys:
                stats["queued_duplicate_rows"] += 1
                continue
            append_rows.append(row)
            queued_keys.add(key)

        append_rows = cls._sort_rows_for_append(append_rows, headers)
        stats["sorted_by_date"] = bool(append_rows)
        return append_rows, stats

    @classmethod
    def _sort_rows_for_append(cls, rows: list[list], headers: list) -> list[list]:
        if len(rows) < 2:
            return rows

        dated_rows = []
        for index, row in enumerate(rows):
            row_date = cls._date_from_row(row, headers)
            dated_rows.append((row_date is None, row_date or datetime.date.max, index, row))

        return [row for _, _, _, row in sorted(dated_rows)]

    @staticmethod
    def _log_append_stats(stats: dict, prefix: str = ""):
        label = f"{prefix} " if prefix else ""
        key_columns = ", ".join(stats.get("key_columns") or [])
        logger.info(f"{label}Duplicate key columns: {key_columns if key_columns else 'fallback row key'}")
        if stats.get("existing_max_date"):
            logger.info(f"{label}Existing max report date: {stats['existing_max_date']}")
        if stats.get("skipped_existing_or_older_date_rows"):
            logger.info(
                f"{label}Skipped existing/older-date new keys: "
                f"{stats['skipped_existing_or_older_date_rows']}"
            )
        logger.info(
            f"{label}Duplicate rows skipped: {stats.get('duplicate_rows', 0)} / "
            f"queued duplicates skipped: {stats.get('queued_duplicate_rows', 0)}"
        )
        if stats.get("sorted_by_date"):
            logger.info(f"{label}Append rows sorted by report date ascending.")

    def _ensure_tab_exists(self, spreadsheet_id: str, tab_name: str):
        info = self.sheet_client.get_sheet_info(spreadsheet_id)
        if not info:
            raise ValueError(f"Could not access spreadsheet {spreadsheet_id}")
        
        sheet_titles = [sheet['properties']['title'] for sheet in info.get('sheets', [])]
        
        if tab_name not in sheet_titles:
            logger.info(f"Tab '{tab_name}' not found. Creating it.")
            result = self.sheet_client.add_sheet(spreadsheet_id, tab_name)
            if result is None:
                raise RuntimeError(f"Failed to create tab '{tab_name}'")
            return True
        return False

    def _ensure_headers(self, spreadsheet_id: str, tab_name: str, columns: list):
        existing_data = self.sheet_client.get_sheet_data(spreadsheet_id, f"{tab_name}!A1:ZZ1")
        if not existing_data or not existing_data[0]:
            logger.info(f"Writing headers to '{tab_name}'")
            result = self.sheet_client.update_sheet_data(spreadsheet_id, f"{tab_name}!A1", [columns], value_input_option='RAW')
            if result is None:
                raise RuntimeError(f"Failed to write headers to '{tab_name}'")
            return True
        return False

    def _read_existing_target(self, spreadsheet_id: str, tab_name: str, columns: list) -> tuple[list, list[list], bool, bool]:
        info = self.sheet_client.get_sheet_info(spreadsheet_id)
        if not info:
            raise ValueError(f"Could not access spreadsheet {spreadsheet_id}")

        sheet_titles = [sheet['properties']['title'] for sheet in info.get('sheets', [])]
        tab_exists = tab_name in sheet_titles
        if not tab_exists:
            return columns, [], False, False

        header_data = self.sheet_client.get_sheet_data(spreadsheet_id, f"{tab_name}!A1:ZZ1")
        has_headers = bool(header_data and header_data[0])
        if not has_headers:
            return columns, [], True, False

        existing_data = self.sheet_client.get_sheet_data(spreadsheet_id, f"{tab_name}!A:ZZ")
        headers = existing_data[0] if existing_data else header_data[0]
        existing_rows = existing_data[1:] if len(existing_data) > 1 else []
        return headers, existing_rows, True, True

    @classmethod
    def _writable_report_width(
        cls,
        headers: list,
        source_columns,
        tab_name: str = "",
        spreadsheet_id: str = "",
    ) -> int:
        write_start_col = _raw_write_start_column(spreadsheet_id)
        max_width = _max_raw_write_columns_for_layout(tab_name, spreadsheet_id)
        start_index = write_start_col - 1
        width = 0
        for header in headers[start_index:]:
            if width >= max_width:
                break
            if cls._source_for_target_header(header, source_columns) is None:
                break
            width += 1
        return min(width, max_width)

    @classmethod
    def _next_raw_write_row(
        cls,
        headers: list,
        existing_rows: list[list],
        write_start_col: int,
        write_width: int,
        rows_count: int,
    ) -> int:
        last_raw_row = 1
        raw_row_numbers = []
        latest_date = None
        latest_date_last_row = None
        start_index = write_start_col - 1
        end_index = start_index + write_width

        for row_number, row in enumerate(existing_rows, start=2):
            raw_cells = row[start_index:end_index]
            if not any(cls._sheet_cell(cell).strip() for cell in raw_cells):
                continue

            last_raw_row = row_number
            raw_row_numbers.append(row_number)

            row_date = cls._date_from_row(row, headers)
            if row_date is None:
                continue
            if latest_date is None or row_date > latest_date:
                latest_date = row_date
                latest_date_last_row = row_number
            elif row_date == latest_date:
                latest_date_last_row = row_number

        if latest_date_last_row is not None:
            next_raw_after_latest = next(
                (row_number for row_number in raw_row_numbers if row_number > latest_date_last_row),
                None,
            )
            if next_raw_after_latest is None:
                return latest_date_last_row + 1

            gap_capacity = next_raw_after_latest - latest_date_last_row - 1
            if gap_capacity >= rows_count:
                return latest_date_last_row + 1

        return last_raw_row + 1

    @staticmethod
    def _round_like_apps_script(value: Decimal) -> int:
        return int((value + Decimal("0.5")).to_integral_value(rounding=ROUND_FLOOR))

    @classmethod
    def _vat_adjust_cell(cls, value):
        if value == "" or value is None:
            return value

        text = str(value).replace(",", "").strip()
        if text == "":
            return value

        try:
            number = Decimal(text)
        except InvalidOperation:
            return value

        if not number.is_finite() or number != number.to_integral_value():
            return value

        return str(cls._round_like_apps_script(number / VAT_RATE))

    @classmethod
    def _apply_vat_adjustment_to_rows(
        cls,
        spreadsheet_id: str,
        tab_name: str,
        rows: list[list],
        write_start_col: int,
        write_width: int,
    ) -> list[list]:
        target_cols = VAT_ADJUST_COLUMNS_BY_TAB.get(str(tab_name).strip())
        if not target_cols or not _should_apply_vat_adjustment(spreadsheet_id):
            return rows

        adjusted_count = 0
        adjusted_rows = []
        for row in rows:
            adjusted_row = list(row)
            for col in target_cols:
                index = col - write_start_col
                if index >= write_width or index >= len(adjusted_row):
                    continue
                if index < 0:
                    continue
                adjusted_value = cls._vat_adjust_cell(adjusted_row[index])
                if adjusted_value != adjusted_row[index]:
                    adjusted_count += 1
                adjusted_row[index] = adjusted_value
            adjusted_rows.append(adjusted_row)

        if adjusted_count:
            logger.info(
                f"Applied VAT adjustment (/1.1) to {adjusted_count} raw amount cells "
                f"for spreadsheet '{spreadsheet_id}' tab '{tab_name}'."
            )
        return adjusted_rows

    def _write_rows_without_inserting(
        self,
        spreadsheet_id: str,
        tab_name: str,
        headers: list,
        existing_rows: list[list],
        rows: list[list],
        write_start_col: int,
        write_width: int,
    ):
        if not rows:
            return {"updatedRows": 0}

        if write_width <= 0:
            raise RuntimeError(f"No writable raw report columns found in '{tab_name}'")

        start_index = write_start_col - 1
        end_index = start_index + write_width
        rows_to_write = [row[start_index:end_index] for row in rows]
        rows_to_write = self._apply_vat_adjustment_to_rows(
            spreadsheet_id,
            tab_name,
            rows_to_write,
            write_start_col,
            write_width,
        )
        start_row = self._next_raw_write_row(
            headers,
            existing_rows,
            write_start_col,
            write_width,
            len(rows_to_write),
        )
        end_row = start_row + len(rows_to_write) - 1
        start_col = self._column_letter(write_start_col)
        end_col = self._column_letter(write_start_col + write_width - 1)
        range_name = f"{tab_name}!{start_col}{start_row}:{end_col}{end_row}"
        result = self.sheet_client.update_sheet_data(
            spreadsheet_id,
            range_name,
            rows_to_write,
            value_input_option='USER_ENTERED',
        )
        if result is None:
            raise RuntimeError(f"Failed to write rows to '{tab_name}' at {range_name}")
        logger.info(
            f"Wrote raw report columns only with USER_ENTERED values.update at '{range_name}' "
            f"without inserting sheet rows."
        )
        return result

    def write_report(
        self,
        spreadsheet_id: str,
        tab_name: str,
        parse_result: ParseResult,
        dry_run: bool = True,
        account_id: str = "",
    ) -> dict:
        """
        파싱된 보고서 데이터를 구글 시트에 저장합니다.
        dry_run=True인 경우 실제 저장은 수행하지 않고 로그만 출력합니다.
        """
        logger.info(f"Starting write process for tab '{tab_name}' (dry_run={dry_run})")
        
        if not parse_result.success:
            logger.warning("No valid data to write.")
            return {"success": False, "rows_written": 0, "message": "No valid data"}

        if parse_result.dataframe is None:
            logger.warning("No valid data to write.")
            return {"success": False, "rows_written": 0, "message": "No valid data"}

        if getattr(parse_result, "no_data", False) or parse_result.dataframe.empty:
            message = "저장할 데이터가 없습니다."
            logger.info(message)
            return {
                "success": True,
                "no_data": True,
                "rows_written": 0,
                "message": message,
                "status": "NO_DATA_SUCCESS",
                "dry_run": dry_run,
            }

        df = parse_result.dataframe.fillna("")

        # Dry Run 모드
        if dry_run:
            headers, existing_rows, tab_exists, has_headers = self._read_existing_target(
                spreadsheet_id,
                tab_name,
                list(df.columns),
            )
            new_data_list, append_stats = self._new_rows_for_append_with_stats(
                df,
                headers,
                existing_rows,
                spreadsheet_id=spreadsheet_id,
                tab_name=tab_name,
            )
            logger.info(f"[DRY-RUN] Target Spreadsheet ID: {spreadsheet_id}")
            logger.info(f"[DRY-RUN] Target Tab: {tab_name}")
            logger.info(f"[DRY-RUN] Target tab exists: {tab_exists}")
            logger.info(f"[DRY-RUN] Target headers exist: {has_headers}")
            logger.info(f"[DRY-RUN] Candidate rows: {len(df)}")
            logger.info(f"[DRY-RUN] Existing rows checked: {len(existing_rows)}")
            logger.info(f"[DRY-RUN] New rows after duplicate check: {len(new_data_list)}")
            self._log_append_stats(append_stats, prefix="[DRY-RUN]")
            logger.info("[DRY-RUN] 실제 실행 시 기존 행은 수정하지 않고, 중복되지 않은 raw 행만 아래에 추가합니다.")
            return {
                "success": True,
                "rows_written": len(new_data_list),
                "candidate_rows": len(df),
                "duplicate_rows": append_stats["duplicate_rows"],
                "queued_duplicate_rows": append_stats["queued_duplicate_rows"],
                "skipped_existing_or_older_date_rows": append_stats["skipped_existing_or_older_date_rows"],
                "existing_max_date": append_stats["existing_max_date"],
                "message": "Dry run successful",
                "dry_run": True,
            }

        # 실제 쓰기
        try:
            self._ensure_tab_exists(spreadsheet_id, tab_name)
            self._ensure_headers(spreadsheet_id, tab_name, list(df.columns))

            existing_data = self.sheet_client.get_sheet_data(spreadsheet_id, f"{tab_name}!A:ZZ")
            headers = existing_data[0] if existing_data else list(df.columns)
            existing_rows = existing_data[1:] if len(existing_data) > 1 else []
            new_data_list, append_stats = self._new_rows_for_append_with_stats(
                df,
                headers,
                existing_rows,
                spreadsheet_id=spreadsheet_id,
                tab_name=tab_name,
            )
            write_start_col = _raw_write_start_column(spreadsheet_id)
            write_width = self._writable_report_width(
                headers,
                df.columns,
                tab_name,
                spreadsheet_id=spreadsheet_id,
            )
            if write_width:
                write_end_col = self._column_letter(write_start_col + write_width - 1)
                logger.info(
                    f"Writable raw report width: {write_width} columns "
                    f"({self._column_letter(write_start_col)}:{write_end_col})."
                )
            else:
                logger.info("Writable raw report width: 0 columns (N/A).")
            self._log_append_stats(append_stats)

            if new_data_list:
                write_start_row = self._next_raw_write_row(
                    headers, existing_rows, write_start_col, write_width, len(new_data_list)
                )
                self._write_rows_without_inserting(
                    spreadsheet_id,
                    tab_name,
                    headers,
                    existing_rows,
                    new_data_list,
                    write_start_col,
                    write_width,
                )
                if tab_name == "데일리SA_RAW":
                    date_col = _download_date_column_for_sheet(spreadsheet_id, account_id=account_id)
                    if date_col:
                        kst = datetime.timezone(datetime.timedelta(hours=9))
                        today_str = datetime.datetime.now(kst).strftime("%Y-%m-%d")
                        self.sheet_client.update_sheet_data(
                            spreadsheet_id, f"{tab_name}!{date_col}{write_start_row}", [[today_str]]
                        )
                        logger.info(f"Wrote download date to {date_col}{write_start_row}: {today_str}")
                    else:
                        logger.info(
                            f"Skipped download date write for spreadsheet '{spreadsheet_id}', "
                            f"account '{account_id}' (no date column)"
                        )

            rows_written = len(new_data_list)

            logger.info(f"Successfully wrote {rows_written} rows to '{tab_name}'")
            return {
                "success": True,
                "rows_written": rows_written,
                "candidate_rows": len(df),
                "duplicate_rows": append_stats["duplicate_rows"],
                "queued_duplicate_rows": append_stats["queued_duplicate_rows"],
                "skipped_existing_or_older_date_rows": append_stats["skipped_existing_or_older_date_rows"],
                "existing_max_date": append_stats["existing_max_date"],
                "message": "Success",
                "dry_run": False,
            }

        except Exception as e:
            logger.error(f"Error writing report: {e}")
            return {"success": False, "rows_written": 0, "message": str(e), "dry_run": False}

    def resolve_destination_from_config(self, account_name: str, report_name: str, account_id: str = "") -> dict:
        """
        허브 시트의 CONFIG_ACCOUNTS, CONFIG_REPORTS 설정을 조회하여
        고객사의 저장 대상 정보를 반환합니다.
        """
        hub_id = os.getenv("HUB_SPREADSHEET_ID")
        if not hub_id:
            raise ValueError("HUB_SPREADSHEET_ID is not set in .env")

        # 1. CONFIG_ACCOUNTS 조회
        accounts_data = self.sheet_client.get_sheet_data(hub_id, "CONFIG_ACCOUNTS!A:Z")
        if not accounts_data or len(accounts_data) < 2:
            raise ValueError("CONFIG_ACCOUNTS tab is empty or missing headers")
        
        acc_df = pd.DataFrame(accounts_data[1:], columns=accounts_data[0])
        account_id = str(account_id or "").strip()

        if account_id:
            account_row = acc_df[acc_df['네이버광고계정ID'].astype(str).str.strip() == account_id]
            if account_name and not account_row.empty:
                same_name_row = account_row[account_row['고객사명'] == account_name]
                if not same_name_row.empty:
                    account_row = same_name_row
        else:
            account_row = acc_df[acc_df['고객사명'] == account_name]
        
        if account_row.empty:
            if account_id:
                raise ValueError(f"Customer '{account_name}' / account ID '{account_id}' not found in CONFIG_ACCOUNTS")
            raise ValueError(f"Customer '{account_name}' not found in CONFIG_ACCOUNTS")
        
        account_info = account_row.iloc[0]

        # 2. CONFIG_REPORTS 조회
        reports_data = self.sheet_client.get_sheet_data(hub_id, "CONFIG_REPORTS!A:Z")
        if reports_data and len(reports_data) >= 2:
            rep_df = pd.DataFrame(reports_data[1:], columns=reports_data[0])
        else:
            rep_df = pd.DataFrame(DEFAULT_REPORT_CONFIGS, columns=EXPECTED_COLUMNS_REPORTS)

        if "네이버보고서명" in rep_df.columns and "저장탭명" in rep_df.columns:
            normalized = rep_df.apply(
                lambda row: normalize_report_destination(row.get("네이버보고서명", ""), row.get("저장탭명", "")),
                axis=1,
            )
            rep_df["네이버보고서명"] = normalized.apply(lambda value: value[0])
            rep_df["저장탭명"] = normalized.apply(lambda value: value[1])

        # 네이버보고서명 또는 저장탭명으로 검색
        report_row = rep_df[(rep_df['네이버보고서명'] == report_name) | (rep_df['저장탭명'] == report_name)]
        
        if report_row.empty:
            raise ValueError(f"Report '{report_name}' not found in CONFIG_REPORTS")
        
        report_info = report_row.iloc[0]
        naver_report_name = report_info.get("네이버보고서명", "")
        target_tab_name = report_info.get("저장탭명", "")
        if not _allow_non_raw_target_tab() and target_tab_name not in STANDARD_REPORT_NAMES:
            raise ValueError(
                f"Unsafe target tab '{target_tab_name}'. "
                f"Allowed raw tabs: {', '.join(STANDARD_REPORT_NAMES)}"
            )

        return {
            "customer_name": account_name,
            "naver_account_name": account_info.get("네이버광고계정명", ""),
            "naver_account_id": account_info.get("네이버광고계정ID", ""),
            "target_spreadsheet_id": account_info.get("저장구글시트ID", ""),
            "target_tab_name": target_tab_name,
            "report_name": naver_report_name
        }

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    from src.report_parser import parse_file
    import sys
    
    parser = argparse.ArgumentParser(description="Naver Report Writer")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Dry run mode (default)")
    parser.add_argument("--write", action="store_false", dest="dry_run", help="Actual write mode")
    parser.add_argument("--resolve-only", action="store_true", help="Only resolve destination from config and exit")
    parser.add_argument("--skip-log", action="store_true", help="Do not write DOWNLOAD_LOG/ERROR_LOG entries")
    parser.add_argument("--account-name", type=str, default="페이퍼백", help="Target account name")
    parser.add_argument("--account-id", type=str, default="", help="Target Naver account ID")
    parser.add_argument("--report-name", type=str, default="데일리_살만", help="Target report name")
    parser.add_argument("--file-path", type=str, help="Path to the CSV file to parse")
    args = parser.parse_args()

    writer = ReportWriter()

    # --resolve-only 모드
    if args.resolve_only:
        try:
            dest = writer.resolve_destination_from_config(args.account_name, args.report_name, args.account_id)
            masked_id = f"{dest['target_spreadsheet_id'][:4]}...{dest['target_spreadsheet_id'][-4:]}" if len(dest['target_spreadsheet_id']) > 8 else "****"
            
            print("\n" + "="*50)
            print(" [ 설정 조회 결과 ]")
            print(f" - 고객사명: {dest['customer_name']}")
            print(f" - 네이버광고계정명: {dest['naver_account_name']}")
            print(f" - 네이버광고계정ID: {dest['naver_account_id']}")
            print(f" - 저장구글시트ID: {masked_id}")
            print(f" - 저장탭명: {dest['target_tab_name']}")
            print("="*50 + "\n")
            sys.exit(0)
        except Exception as e:
            print(f"Error: {e}")
            sys.exit(1)

    # 파일 경로 결정
    file_to_process = args.file_path if args.file_path else "downloads/samples/paperbag100/paperbag100.csv"
    
    if not os.path.exists(file_to_process):
        print(f"파일을 찾을 수 없습니다: {file_to_process}")
        sys.exit(1)

    parse_res = parse_file(file_to_process)
    if not parse_res.success:
        print(f"파싱 실패: {parse_res.error_message}")
        sys.exit(1)

    try:
        # 1. 설정 정보 조회
        try:
            dest = writer.resolve_destination_from_config(args.account_name, args.report_name, args.account_id)
            spreadsheet_id = dest["target_spreadsheet_id"]
            tab_name = dest["target_tab_name"]
        except Exception as e:
            # Resolve failed (e.g., customer not found, report not found)
            err_msg = str(e)
            if "Customer" in err_msg and "CONFIG_ACCOUNTS" in err_msg:
                error_type = "CONFIG_ACCOUNT_NOT_FOUND"
            elif "Report" in err_msg and "CONFIG_REPORTS" in err_msg:
                error_type = "CONFIG_REPORT_NOT_FOUND"
            else:
                error_type = "UNKNOWN_ERROR"
            
            if not args.dry_run and not args.skip_log:
                el_err = ErrorLogger()
                run_id = el_err.generate_run_id()
                error_row = {
                    "run_id": run_id,
                    "단계": "CONFIG_RESOLVE",
                    "고객사명": args.account_name,
                    "네이버광고계정ID": "",
                    "보고서구분": args.report_name,
                    "오류유형": error_type,
                    "오류내용": err_msg,
                    "조치필요여부": "TRUE",
                    "담당자확인": ""
                }
                append_error_log(error_row)
            print(f"Error: {err_msg}")
            sys.exit(1)

        # 2. 실행 정보 요약 출력
        mode_str = "DRY-RUN" if args.dry_run else "ACTUAL WRITE"
        masked_id = f"{spreadsheet_id[:4]}...{spreadsheet_id[-4:]}" if len(spreadsheet_id) > 8 else "****"
        
        print("\n" + "="*50)
        print(f" [ 저장 실행 정보 요약 ({mode_str}) ]")
        print(f" - 고객사명: {dest['customer_name']}")
        print(f" - 네이버광고계정명: {dest['naver_account_name']}")
        print(f" - 네이버광고계정ID: {dest['naver_account_id']}")
        print(f" - 저장구글시트ID: {masked_id}")
        print(f" - 저장탭명: {tab_name}")
        print(f" - 파일명: {os.path.basename(file_to_process)}")
        print(f" - 저장 예정 행 수: {len(parse_res.dataframe)}")
        print(f" - dry-run 여부: {args.dry_run}")
        print("="*50 + "\n")
        
        # 3. 저장 실행
        res = writer.write_report(
            spreadsheet_id=spreadsheet_id, 
            tab_name=tab_name, 
            parse_result=parse_res,
            dry_run=args.dry_run,
            account_id=args.account_id or dest.get("naver_account_id", ""),
        )
        print(
            f"저장 결과: {res.get('message', '')} / "
            f"저장행수: {res.get('rows_written', 0)} / "
            f"status: {res.get('status', 'SUCCESS' if res.get('success') else 'FAILED')}"
        )
        if not res.get('success'):
            sys.exit(1)

        # 4. DOWNLOAD_LOG 기록
        if not args.dry_run and res.get('success') and not args.skip_log:
            el = ErrorLogger()
            run_id = el.generate_run_id()
            log_data = {
                "run_id": run_id,
                "고객사명": dest.get('customer_name', ''),
                "네이버광고계정명": dest.get('naver_account_name', ''),
                "네이버광고계정ID": dest.get('naver_account_id', ''),
                "보고서구분": dest.get('report_name', ''),
                "네이버보고서명": dest.get('report_name', ''),
                "저장탭명": dest.get('target_tab_name', ''),
                "통계기간": "",
                "다운로드파일명": os.path.basename(file_to_process),
                "저장행수": res.get('rows_written', 0),
                "결과": "성공",
                "오류내용": ""
            }
            append_download_log(log_data)
            
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
