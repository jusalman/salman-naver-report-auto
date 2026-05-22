import logging
import argparse
import os
from dotenv import load_dotenv
import datetime
import pandas as pd
from src.error_logger import ErrorLogger, append_download_log, append_error_log
from src.google_sheet_client import GoogleSheetClient
from src.report_parser import ParseResult
from src.models import DEFAULT_REPORT_CONFIGS, EXPECTED_COLUMNS_REPORTS, normalize_report_destination

# .env 로드
load_dotenv()

logger = logging.getLogger(__name__)

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
    def _row_key(cls, row: list, width: int) -> tuple:
        return tuple(cls._sheet_cell(row[i]) if i < len(row) else "" for i in range(width))

    @classmethod
    def _new_rows_for_append(cls, df: pd.DataFrame, headers: list, existing_rows: list[list]) -> list[list]:
        missing_columns = [col for col in df.columns if col not in headers]
        if missing_columns:
            raise ValueError(
                "Existing sheet headers do not contain report columns: "
                + ", ".join(str(col) for col in missing_columns)
            )

        width = len(headers)
        existing_keys = {cls._row_key(row, width) for row in existing_rows}
        append_rows = []
        queued_keys = set()

        for record in df.to_dict(orient="records"):
            row = [cls._sheet_cell(record.get(header, "")) for header in headers]
            key = cls._row_key(row, width)
            if key in existing_keys or key in queued_keys:
                continue
            append_rows.append(row)
            queued_keys.add(key)

        return append_rows

    def _ensure_tab_exists(self, spreadsheet_id: str, tab_name: str):
        info = self.sheet_client.get_sheet_info(spreadsheet_id)
        if not info:
            raise ValueError(f"Could not access spreadsheet {spreadsheet_id}")
        
        sheet_titles = [sheet['properties']['title'] for sheet in info.get('sheets', [])]
        
        if tab_name not in sheet_titles:
            logger.info(f"Tab '{tab_name}' not found. Creating it.")
            self.sheet_client.add_sheet(spreadsheet_id, tab_name)
            return True
        return False

    def _ensure_headers(self, spreadsheet_id: str, tab_name: str, columns: list):
        existing_data = self.sheet_client.get_sheet_data(spreadsheet_id, f"{tab_name}!A1:Z1")
        if not existing_data or not existing_data[0]:
            logger.info(f"Writing headers to '{tab_name}'")
            self.sheet_client.update_sheet_data(spreadsheet_id, f"{tab_name}!A1", [columns], value_input_option='RAW')
            return True
        return False

    def write_report(self, spreadsheet_id: str, tab_name: str, parse_result: ParseResult, dry_run: bool = True) -> dict:
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
            logger.info(f"[DRY-RUN] Target Spreadsheet ID: {spreadsheet_id}")
            logger.info(f"[DRY-RUN] Target Tab: {tab_name}")
            logger.info(f"[DRY-RUN] Candidate rows: {len(df)}")
            logger.info("[DRY-RUN] 실제 실행 시 기존 행은 수정하지 않고, 중복되지 않은 raw 행만 아래에 추가합니다.")
            return {"success": True, "rows_written": len(df), "message": "Dry run successful", "dry_run": True}

        # 실제 쓰기
        try:
            self._ensure_tab_exists(spreadsheet_id, tab_name)
            self._ensure_headers(spreadsheet_id, tab_name, list(df.columns))

            existing_data = self.sheet_client.get_sheet_data(spreadsheet_id, f"{tab_name}!A:Z")
            headers = existing_data[0] if existing_data else list(df.columns)
            existing_rows = existing_data[1:] if len(existing_data) > 1 else []
            new_data_list = self._new_rows_for_append(df, headers, existing_rows)

            if new_data_list:
                end_col = self._column_letter(len(headers))
                self.sheet_client.append_sheet_data(
                    spreadsheet_id,
                    f"{tab_name}!A:{end_col}",
                    new_data_list,
                    value_input_option='RAW',
                )

            rows_written = len(new_data_list)

            logger.info(f"Successfully wrote {rows_written} rows to '{tab_name}'")
            return {"success": True, "rows_written": rows_written, "message": "Success", "dry_run": False}

        except Exception as e:
            logger.error(f"Error writing report: {e}")
            return {"success": False, "rows_written": 0, "message": str(e), "dry_run": False}

    def resolve_destination_from_config(self, account_name: str, report_name: str) -> dict:
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
        account_row = acc_df[acc_df['고객사명'] == account_name]
        
        if account_row.empty:
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

        return {
            "customer_name": account_name,
            "naver_account_name": account_info.get("네이버광고계정명", ""),
            "naver_account_id": account_info.get("네이버광고계정ID", ""),
            "target_spreadsheet_id": account_info.get("저장구글시트ID", ""),
            "target_tab_name": report_info.get("저장탭명", ""),
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
    parser.add_argument("--account-name", type=str, default="페이퍼백", help="Target account name")
    parser.add_argument("--report-name", type=str, default="데일리_살만", help="Target report name")
    parser.add_argument("--file-path", type=str, help="Path to the CSV file to parse")
    args = parser.parse_args()

    writer = ReportWriter()

    # --resolve-only 모드
    if args.resolve_only:
        try:
            dest = writer.resolve_destination_from_config(args.account_name, args.report_name)
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
            dest = writer.resolve_destination_from_config(args.account_name, args.report_name)
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
            dry_run=args.dry_run
        )
        print(
            f"저장 결과: {res.get('message', '')} / "
            f"저장행수: {res.get('rows_written', 0)} / "
            f"status: {res.get('status', 'SUCCESS' if res.get('success') else 'FAILED')}"
        )

        # 4. DOWNLOAD_LOG 기록
        if not args.dry_run and res.get('success'):
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
