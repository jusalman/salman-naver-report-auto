import argparse
import sys
import subprocess
import os
import pandas as pd
import datetime
import pytz
from pathlib import Path
from src.naver_report_downloader import download_report
from src.config_loader import ConfigLoader
from src.run_policy import get_today_execution_plan

OPERATION_SHEET_NAMES = ("CONFIG_ACCOUNTS", "CONFIG_REPORTS", "DOWNLOAD_LOG", "ERROR_LOG")

def _configure_stdio():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(errors="replace")
            except Exception:
                pass

_configure_stdio()

def is_skipped_reason(reason):
    return str(reason).startswith("SKIPPED_")

def _first_existing_column(df, candidates):
    if df is None:
        return None

    def normalize_header(value):
        return str(value).replace("\ufeff", "").replace(" ", "").strip()

    normalized_columns = {normalize_header(col): col for col in df.columns}
    for candidate in candidates:
        if candidate in df.columns:
            return candidate
        normalized_candidate = normalize_header(candidate)
        if normalized_candidate in normalized_columns:
            return normalized_columns[normalized_candidate]
    return None

def _clean_config_value(value):
    if pd.isna(value):
        return ""
    return str(value).strip()

def _get_mapping_value(mapping, candidates, default="N/A"):
    normalized_mapping = {str(key).replace("\ufeff", "").replace(" ", "").strip(): key for key in mapping.keys()}
    for candidate in candidates:
        if candidate in mapping:
            value = _clean_config_value(mapping.get(candidate))
            return value if value else default
        normalized_candidate = str(candidate).replace("\ufeff", "").replace(" ", "").strip()
        if normalized_candidate in normalized_mapping:
            value = _clean_config_value(mapping.get(normalized_mapping[normalized_candidate]))
            return value if value else default
    return default

def _is_run_enabled(value):
    return _clean_config_value(value).upper() == "TRUE"

def _is_operating(value):
    return _clean_config_value(value) == "운영중"

def _filter_execution_target_accounts(df):
    """CONFIG_ACCOUNTS rows that are eligible for --all-accounts execution."""
    if df is None or df.empty:
        return pd.DataFrame(columns=[] if df is None else df.columns)

    run_col = _first_existing_column(df, ["실행여부", "실행 여부"])
    status_col = _first_existing_column(df, ["운영상태", "운영 상태"])
    if not run_col or not status_col:
        return df.iloc[0:0].copy()

    mask = df.apply(lambda row: _is_run_enabled(row.get(run_col)) and _is_operating(row.get(status_col)), axis=1)
    return df[mask].copy()

def _parse_account_ids_arg(value):
    if not value:
        return set()
    return {item.strip() for item in str(value).split(",") if item.strip()}

def _account_id_column(df):
    return _first_existing_column(df, ["네이버광고계정ID", "네이버 광고계정 ID", "네이버계정ID", "광고계정ID", "account_id"])

def _filter_rows_by_account_ids(df, selected_account_ids):
    if df is None or df.empty or not selected_account_ids:
        return df

    account_id_col = _account_id_column(df)
    if not account_id_col:
        return df.iloc[0:0].copy()

    mask = df[account_id_col].apply(lambda value: _clean_config_value(value) in selected_account_ids)
    return df[mask].copy()

def _collect_account_ids(df):
    if df is None or df.empty:
        return set()

    account_id_col = _account_id_column(df)
    if not account_id_col:
        return set()

    return {_clean_config_value(value) for value in df[account_id_col] if _clean_config_value(value)}

def _split_required_account_rows(df):
    if df is None or df.empty:
        return (pd.DataFrame(columns=[] if df is None else df.columns),
                pd.DataFrame(columns=[] if df is None else df.columns))

    target_sheet_col = _first_existing_column(df, ["저장구글시트ID", "저장 구글시트 ID"])
    naver_id_col = _first_existing_column(df, ["네이버광고계정ID", "네이버 광고계정 ID"])
    valid_mask = pd.Series(True, index=df.index)

    if target_sheet_col:
        valid_mask &= df[target_sheet_col].apply(lambda value: _clean_config_value(value) != "")
    if naver_id_col:
        valid_mask &= df[naver_id_col].apply(lambda value: _clean_config_value(value) != "")

    return df[valid_mask].copy(), df[~valid_mask].copy()

def _build_config_accounts_df(active_df, skipped_df, invalid_df):
    frames = [df for df in [active_df, skipped_df, invalid_df] if df is not None and not df.empty]
    if not frames:
        columns = active_df.columns if active_df is not None else []
        return pd.DataFrame(columns=columns)
    return pd.concat(frames, ignore_index=True).drop_duplicates()

def _get_missing_account_reason(row):
    target_sheet_col = _first_existing_column(pd.DataFrame(columns=row.index), ["저장구글시트ID", "저장 구글시트 ID"])
    naver_id_col = _first_existing_column(pd.DataFrame(columns=row.index), ["네이버광고계정ID", "네이버 광고계정 ID"])

    if target_sheet_col and _clean_config_value(row.get(target_sheet_col)) == "":
        return "MISSING_TARGET_SPREADSHEET_ID"
    if naver_id_col and _clean_config_value(row.get(naver_id_col)) == "":
        return "MISSING_NAVER_ACCOUNT_ID"
    return "UNKNOWN_INVALID"

def get_column_letter(n):
    """숫자 인덱스를 엑셀 컬럼 문자(A, B, C...)로 변환합니다."""
    result = ""
    while n > 0:
        n, remainder = divmod(n - 1, 26)
        result = chr(65 + remainder) + result
    return result

def _normalize_sheet_header(value):
    return str(value).replace("\ufeff", "").replace(" ", "").replace("_", "").strip().lower()

def _value_for_log_header(header, values):
    normalized_header = _normalize_sheet_header(header)
    candidates = {
        "timestamp": ["실행일시", "다운로드일시", "저장일시", "오류일시", "일시", "timestamp", "createdat"],
        "account_name": ["고객명", "계정명", "광고주명", "accountname", "account"],
        "account_id": ["네이버계정id", "네이버광고계정id", "광고계정id", "accountid"],
        "report_name": ["보고서명", "리포트명", "reportname"],
        "tab_name": ["저장탭", "대상탭", "시트명", "tabname", "sheetname"],
        "period": ["기간", "조회기간", "period"],
        "file_path": ["파일경로", "다운로드파일경로", "저장파일경로", "최근다운로드파일경로", "filepath", "downloadpath"],
        "status": ["결과", "상태", "실행결과", "저장결과", "status"],
        "error_code": ["오류코드", "에러코드", "errorcode"],
        "error_message": ["오류내용", "오류메시지", "에러내용", "errormessage"],
    }
    for key, aliases in candidates.items():
        if normalized_header in [_normalize_sheet_header(alias) for alias in aliases]:
            return values.get(key, "")
    return ""

def _append_log_row(sheet_client, spreadsheet_id, sheet_name, values):
    rows = sheet_client.get_sheet_data(spreadsheet_id, f"{sheet_name}!A:Z")
    if not rows:
        print(f"[WARNING] {sheet_name} tab has no header row; skipped log write.")
        return

    headers = rows[0]
    row_values = [_value_for_log_header(header, values) for header in headers]
    end_col = get_column_letter(max(len(headers), 1))
    result = sheet_client.append_sheet_data(spreadsheet_id, f"{sheet_name}!A:{end_col}", [row_values])
    if result is None:
        print(f"[WARNING] {sheet_name} log append failed.")

def append_execution_logs(all_execution_results, skipped_or_invalid_accounts, is_actual_write, loader):
    if not is_actual_write:
        return

    hub_id = os.getenv("HUB_SPREADSHEET_ID")
    if not hub_id:
        print("[WARNING] HUB_SPREADSHEET_ID is missing; skipped log write.")
        return

    seoul_tz = pytz.timezone('Asia/Seoul')
    now_str = datetime.datetime.now(seoul_tz).strftime("%Y-%m-%d %H:%M:%S")
    sheet_client = loader.sheet_client

    for account_info, results in all_execution_results:
        account_name = _get_mapping_value(account_info, ["고객명", "계정명", "광고주명", "æ€¨ì¢‰ì»¼?Ñ‰ì±¸"])
        account_id = _get_mapping_value(account_info, ["네이버계정ID", "네이버광고계정ID", "광고계정ID", "?ã…¼ì” è¸°ê¾§í‚…æ€¨ì¢‰í€Ž?ë·žD"])
        for result in results:
            values = {
                "timestamp": now_str,
                "account_name": account_name,
                "account_id": account_id,
                "report_name": result.get("report_name", ""),
                "tab_name": result.get("tab_name", ""),
                "period": result.get("period", ""),
                "file_path": result.get("download_path", ""),
                "status": "SUCCESS" if result.get("success") else "FAILED",
                "error_code": result.get("error_code", ""),
                "error_message": result.get("error_message", ""),
            }
            _append_log_row(sheet_client, hub_id, "DOWNLOAD_LOG" if result.get("success") else "ERROR_LOG", values)

    for account_info, reason in skipped_or_invalid_accounts:
        if is_skipped_reason(reason):
            continue
        values = {
            "timestamp": now_str,
            "account_name": _get_mapping_value(account_info, ["고객명", "계정명", "광고주명", "æ€¨ì¢‰ì»¼?Ñ‰ì±¸"]),
            "account_id": _get_mapping_value(account_info, ["네이버계정ID", "네이버광고계정ID", "광고계정ID", "?ã…¼ì” è¸°ê¾§í‚…æ€¨ì¢‰í€Ž?ë·žD"]),
            "report_name": "",
            "tab_name": "",
            "period": "",
            "file_path": "",
            "status": "FAILED",
            "error_code": reason,
            "error_message": reason,
        }
        _append_log_row(sheet_client, hub_id, "ERROR_LOG", values)

def run_preflight(loader):
    hub_id = os.getenv("HUB_SPREADSHEET_ID")
    if not hub_id:
        print("[ERROR] HUB_SPREADSHEET_ID is missing.")
        return 1

    missing_or_empty = []
    for sheet_name in OPERATION_SHEET_NAMES:
        rows = loader.sheet_client.get_sheet_data(hub_id, f"{sheet_name}!A:Z")
        if not rows:
            missing_or_empty.append(sheet_name)

    if missing_or_empty:
        print("[ERROR] Required operation sheets are missing or empty: " + ", ".join(missing_or_empty))
        return 1

    print("[OK] Required operation sheets are available: " + ", ".join(OPERATION_SHEET_NAMES))
    return 0

def update_hub_status(all_execution_results, skipped_or_invalid_accounts, is_actual_write, loader):
    """실행 결과를 CONFIG_ACCOUNTS 탭에 업데이트합니다."""
    seoul_tz = pytz.timezone('Asia/Seoul')
    now_str = datetime.datetime.now(seoul_tz).strftime("%Y-%m-%d %H:%M:%S")
    
    if not is_actual_write:
        total_reports = sum(len(results) for _, results in all_execution_results)
        success_reports = sum(sum(1 for r in results if r["success"]) for _, results in all_execution_results)
        failed_reports = total_reports - success_reports
        failed_accounts = len(skipped_or_invalid_accounts) + sum(1 for _, results in all_execution_results if any(not r["success"] for r in results))

        print("\n" + "="*80)
        print("[DRY-RUN] CONFIG_ACCOUNTS 업데이트 예정 요약")
        print(f" - 실행 결과 업데이트 대상 고객사: {len(all_execution_results) + len(skipped_or_invalid_accounts)}개")
        print(f" - 조치 필요 고객사: {failed_accounts}개")
        print(f" - 보고서 성공/실패: {success_reports}개 / {failed_reports}개")
        print("="*80 + "\n")
        return

        print("\n" + "="*80)
        print("[DRY-RUN] CONFIG_ACCOUNTS 업데이트 예정:")
        
        # 활성 고객사 처리
        for acc_info, results in all_execution_results:
            success_count = sum(1 for r in results if r["success"])
            if success_count == len(results):
                status = "성공"
            elif success_count > 0:
                status = "일부실패"
            else:
                first_err = next((r["error_code"] for r in results if not r["success"]), "UNKNOWN")
                status = f"실패 / {first_err}"
            print(f" - {acc_info.get('고객사명', 'N/A')}: {status}")
            
        # 스킵/오류 고객사 처리
        for acc_info, reason in skipped_or_invalid_accounts:
            if is_skipped_reason(reason):
                status = "미실행"
            else:
                status = f"실패 / {reason}"
            print(f" - {acc_info.get('고객사명', 'N/A')}: {status}")
        print("="*80 + "\n")
        return

    # 실제 업데이트
    hub_id = os.getenv("HUB_SPREADSHEET_ID")
    sheet_client = loader.sheet_client
    
    raw_data = sheet_client.get_sheet_data(hub_id, "CONFIG_ACCOUNTS!A:Z")
    if not raw_data or len(raw_data) < 2:
        print("⚠️ Hub 업데이트 실패: 시트 데이터를 읽을 수 없습니다.")
        return
        
    headers = raw_data[0]
    col_map = {col: i for i, col in enumerate(headers)}
    
    # 대상 컬럼 확인
    target_cols = ["마지막실행일시", "마지막실행결과", "최근다운로드파일경로", "오류내용"]
    for col in target_cols:
        if col not in col_map:
            print(f"⚠️ Hub 업데이트 실패: 필수 컬럼 '{col}'이 시트에 없습니다.")
            return

    # 행 인덱스 매핑 (ID 또는 이름 기준)
    row_idx_map = {}
    for i, row in enumerate(raw_data[1:]):
        acc_id = str(row[col_map["네이버광고계정ID"]]) if "네이버광고계정ID" in col_map else ""
        acc_name = str(row[col_map["고객사명"]]) if "고객사명" in col_map else ""
        if acc_id:
            row_idx_map[acc_id] = i + 2
        if acc_name:
            row_idx_map[acc_name] = i + 2

    print(f"[*] 허브 시트 상태 업데이트 중 ({len(all_execution_results) + len(skipped_or_invalid_accounts)}건)...")

    # 실행 고객사 업데이트
    for acc_info, results in all_execution_results:
        acc_id = str(acc_info.get("네이버광고계정ID", ""))
        acc_name = str(acc_info.get("고객사명", ""))
        row_num = row_idx_map.get(acc_id) or row_idx_map.get(acc_name)
        if not row_num: continue
        
        success_count = sum(1 for r in results if r["success"])
        if success_count == len(results):
            res_status = "성공"
        elif success_count > 0:
            res_status = "일부실패"
        else:
            res_status = "실패"
            
        last_path = ""
        for r in reversed(results):
            if r["success"] and r["download_path"]:
                if r.get("is_deleted"):
                    last_path = f"자동삭제됨: {os.path.basename(r['download_path'])}"
                else:
                    last_path = r["download_path"]
                break
                
        errors = [f"{r['report_name']}: {r['error_code']} - {r['error_message']}" for r in results if not r["success"]]
        error_content = " | ".join(errors)
        
        # 컬럼들이 연속적인지 확인하여 최적화
        is_contiguous = (col_map["마지막실행결과"] == col_map["마지막실행일시"] + 1 and 
                         col_map["최근다운로드파일경로"] == col_map["마지막실행결과"] + 1 and
                         col_map["오류내용"] == col_map["최근다운로드파일경로"] + 1)
        
        if is_contiguous:
            start_col = col_map["마지막실행일시"] + 1
            end_col = col_map["오류내용"] + 1
            range_name = f"CONFIG_ACCOUNTS!{get_column_letter(start_col)}{row_num}:{get_column_letter(end_col)}{row_num}"
            sheet_client.update_sheet_data(hub_id, range_name, [[now_str, res_status, last_path, error_content]])
        else:
            sheet_client.update_sheet_data(hub_id, f"CONFIG_ACCOUNTS!{get_column_letter(col_map['마지막실행일시']+1)}{row_num}", [[now_str]])
            sheet_client.update_sheet_data(hub_id, f"CONFIG_ACCOUNTS!{get_column_letter(col_map['마지막실행결과']+1)}{row_num}", [[res_status]])
            sheet_client.update_sheet_data(hub_id, f"CONFIG_ACCOUNTS!{get_column_letter(col_map['최근다운로드파일경로']+1)}{row_num}", [[last_path]])
            sheet_client.update_sheet_data(hub_id, f"CONFIG_ACCOUNTS!{get_column_letter(col_map['오류내용']+1)}{row_num}", [[error_content]])

    # 스킵/오류 고객사 업데이트
    for acc_info, reason in skipped_or_invalid_accounts:
        acc_id = str(acc_info.get("네이버광고계정ID", ""))
        acc_name = str(acc_info.get("고객사명", ""))
        row_num = row_idx_map.get(acc_id) or row_idx_map.get(acc_name)
        if not row_num: continue
        
        if is_skipped_reason(reason):
            res_status = "미실행"
            error_content = ""
        else:
            res_status = "실패"
            error_content = f"조치필요: {reason}"
            
        sheet_client.update_sheet_data(hub_id, f"CONFIG_ACCOUNTS!{get_column_letter(col_map['마지막실행일시']+1)}{row_num}", [[now_str]])
        sheet_client.update_sheet_data(hub_id, f"CONFIG_ACCOUNTS!{get_column_letter(col_map['마지막실행결과']+1)}{row_num}", [[res_status]])
        sheet_client.update_sheet_data(hub_id, f"CONFIG_ACCOUNTS!{get_column_letter(col_map['오류내용']+1)}{row_num}", [[error_content]])

def process_report(account_name, account_id, report_info, is_actual_write, keep_files=False):
    """단일 보고서에 대해 다운로드 및 구글시트 저장을 수행합니다."""
    if isinstance(report_info, str):
        report_name = report_info
        tab_name = "N/A"
        period = "N/A"
    else:
        report_name = report_info.get("네이버보고서명", "")
        tab_name = report_info.get("저장탭명", "N/A")
        period = report_info.get("통계기간", "N/A")

    writer_mode = "--write" if is_actual_write else "--dry-run"
    print(f"\n" + "="*60)
    print(f"[*] 보고서 처리 시작: {report_name} (탭: {tab_name})")
    print("="*60)

    result = {
        "report_name": report_name,
        "tab_name": tab_name,
        "period": period,
        "success": False,
        "download_path": None,
        "is_deleted": False,
        "write_status": "PENDING",
        "error_code": "",
        "error_message": ""
    }

    # 1. 네이버 광고센터 보고서 다운로드
    try:
        csv_path, err_code, err_msg = download_report(account_id, report_name, headless=False)
    except Exception as e:
        result["error_code"] = "UNKNOWN_RUN_ENGINE_ERROR"
        result["error_message"] = f"엔진 예외 발생: {str(e)}"
        print(f"\n[❌] {result['error_code']}: {result['error_message']}")
        return result

    if not csv_path:
        result["error_code"] = err_code if err_code else "DOWNLOAD_FAILED"
        result["error_message"] = err_msg if err_msg else "다운로드에 실패했습니다."
        print(f"\n[❌] {result['error_code']}: {result['error_message']}")
        return result

    print(f"[*] 다운로드 완료: {csv_path}")
    result["download_path"] = csv_path

    # 2. report_writer를 이용한 구글 시트 저장 (subprocess 호출)
    cmd = [
        sys.executable, "-m", "src.report_writer",
        "--account-name", account_name,
        "--account-id", str(account_id),
        "--report-name", report_name,
        "--file-path", csv_path,
        "--skip-log",
        writer_mode
    ]

    print(f"[*] 데이터 저장 단계 진입 ({writer_mode})...")
    stdout_text = ""
    stderr_text = ""
    no_data_success = False
    try:
        # check=False로 설정하여 내부 에러 메시지를 직접 처리
        output_encoding = sys.stdout.encoding or "utf-8"
        child_env = os.environ.copy()
        child_env["PYTHONIOENCODING"] = f"{output_encoding}:replace"
        proc_result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding=output_encoding,
            errors="replace",
            env=child_env,
            check=False,
        )
        stdout_text = proc_result.stdout or ""
        stderr_text = proc_result.stderr or ""
        
        # subprocess 출력 연결
        if stdout_text:
            print(stdout_text)
        if stderr_text:
            print(stderr_text, file=sys.stderr)

        no_data_success = (
            "NO_DATA_SUCCESS" in stdout_text
            or "EMPTY_REPORT_SUCCESS" in stdout_text
            or "저장할 데이터가 없습니다." in stdout_text
            or "저장행수: 0" in stdout_text
        )

        if proc_result.returncode != 0 and not no_data_success:
            result["error_code"] = "REPORT_WRITE_FAILED"
            result["error_message"] = f"Exit Code: {proc_result.returncode}"
            result["write_status"] = "FAILED"
            print(f"\n[❌] {result['error_code']}: {result['error_message']}")
            return result

    except Exception as e:
        result["error_code"] = "UNKNOWN_RUN_ENGINE_ERROR"
        result["error_message"] = f"엔진 예외 발생: {str(e)}"
        result["write_status"] = "FAILED"
        print(f"\n[❌] {result['error_code']}: {result['error_message']}")
        return result

    result["success"] = True
    if no_data_success:
        result["no_data"] = True
        result["rows_written"] = 0
        result["write_status"] = "NO_DATA_SUCCESS"
    else:
        result["write_status"] = "ACTUAL_WRITE_SUCCESS" if is_actual_write else "DRY_RUN_SUCCESS"
    print(f"\n[✅] '{report_name}' 처리 성공")
    
    # 3. 파일 정리 (Cleanup)
    if keep_files:
        print(f"[CLEANUP] --keep-files 옵션으로 CSV 보관: {os.path.basename(csv_path)}")
    else:
        try:
            p = Path(csv_path)
            if p.exists():
                p.unlink()
                result["is_deleted"] = True
                print(f"[CLEANUP] CSV 삭제 완료: {p.name}")
            else:
                print(f"[CLEANUP_WARNING] 삭제 대상 파일 없음: {csv_path}")
        except Exception as e:
            print(f"[CLEANUP_WARNING] CSV 삭제 실패: {csv_path} / {e}")
    
    return result

def process_account_reports(account_name, account_id, active_reports, is_actual_write, keep_files=False):
    """특정 고객사의 모든 활성 보고서를 순차적으로 실행합니다."""
    print(f"\n" + "#"*60)
    print(f"### 고객사 실행 시작: {account_name} ({account_id}) ###")
    print("#"*60)
    
    account_results = []
    for r_info in active_reports:
        res = process_report(account_name, account_id, r_info, is_actual_write, keep_files=keep_files)
        account_results.append(res)
    
    return account_results

def main():
    parser = argparse.ArgumentParser(description="SalMan Naver Report Auto Engine")
    parser.add_argument("--account-name", type=str, help="Customer name (e.g. 페이퍼백)")
    parser.add_argument("--account-id", type=str, help="Naver account ID (e.g. 1855171)")
    parser.add_argument("--report-name", type=str, help="Report name (e.g. 데일리_살만)")
    parser.add_argument("--all-reports", action="store_true", help="Run all predefined reports for the account")
    parser.add_argument("--all-accounts", action="store_true", help="Run all active accounts and their active reports")
    parser.add_argument("--account-ids", type=str, help="Comma-separated Naver account IDs to run within --all-accounts")
    parser.add_argument("--dry-run", action="store_true", help="Dry run mode (validate only)")
    parser.add_argument("--write", action="store_true", help="Actual write mode")
    parser.add_argument("--keep-files", action="store_true", help="Keep downloaded CSV files after processing")
    parser.add_argument("--preflight-only", action="store_true", help="Validate required operation sheets only")

    args = parser.parse_args()

    # 인자 유효성 검사
    if not args.preflight_only and not args.all_accounts:
        if not args.account_name or not args.account_id:
            parser.error("--account-name and --account-id are required unless --all-accounts is used.")
        if not args.all_reports and not args.report_name:
            parser.error("--report-name must be specified unless --all-reports or --all-accounts is used.")

    # 모드 결정 (기본값 dry-run)
    is_actual_write = args.write
    keep_files = args.keep_files
    loader = ConfigLoader()

    if args.preflight_only:
        sys.exit(run_preflight(loader))
    
    # 보고서 설정 로드
    df_reports = loader.load_config_reports()
    if df_reports.empty:
        print("\n[⚠️] NO_REPORTS_CONFIG_FOUND: CONFIG_REPORTS 설정을 불러올 수 없거나 비어있습니다.")
        sys.exit(1)
    
    active_reports = df_reports[df_reports['실행여부'].astype(str).str.strip().str.upper() == 'TRUE'].to_dict('records')
    if not active_reports and (args.all_reports or args.all_accounts):
        print("\n[⚠️] NO_ACTIVE_REPORTS_FOUND: 실행여부가 TRUE인 보고서가 없습니다.")
        sys.exit(1)

    all_execution_results = [] # [(account_info, [report_results])]
    skipped_or_invalid_accounts = [] # (account_info, reason)
    total_config_accounts_count = len(all_execution_results)
    execution_target_accounts_count = len(all_execution_results)
    excluded_accounts_count = 0

    if args.all_accounts:
        print("\n[*] 전체 고객사 실행 모드 진입")
        selected_account_ids = _parse_account_ids_arg(args.account_ids)
        active_df, skipped_df, invalid_df = loader.get_filtered_accounts()

        if selected_account_ids:
            all_config_rows = _build_config_accounts_df(active_df, skipped_df, invalid_df)
            known_account_ids = _collect_account_ids(all_config_rows)
            unknown_account_ids = selected_account_ids - known_account_ids

            print(f"[*] 선택 고객사 실행 모드: {len(selected_account_ids)}개 ID")
            active_df = _filter_rows_by_account_ids(active_df, selected_account_ids)
            skipped_df = _filter_rows_by_account_ids(skipped_df, selected_account_ids)
            invalid_df = _filter_rows_by_account_ids(invalid_df, selected_account_ids)

            for unknown_id in sorted(unknown_account_ids):
                skipped_or_invalid_accounts.append(
                    (
                        {"고객사명": "선택 고객사", "네이버광고계정ID": unknown_id},
                        "ACCOUNT_ID_NOT_FOUND_IN_CONFIG",
                    )
                )

        config_accounts_df = _build_config_accounts_df(active_df, skipped_df, invalid_df)
        execution_target_df = _filter_execution_target_accounts(config_accounts_df)
        active_df = _filter_execution_target_accounts(active_df)
        invalid_df = _filter_execution_target_accounts(invalid_df)
        active_df, invalid_active_df = _split_required_account_rows(active_df)
        if invalid_active_df is not None and not invalid_active_df.empty:
            invalid_df = pd.concat([invalid_df, invalid_active_df], ignore_index=True).drop_duplicates()
        skipped_df = skipped_df.iloc[0:0].copy() if skipped_df is not None else pd.DataFrame()

        total_config_accounts_count = len(config_accounts_df)
        execution_target_accounts_count = len(execution_target_df)
        excluded_accounts_count = total_config_accounts_count - execution_target_accounts_count
        
        # invalid 처리 (필수 필드 누락)
        for _, row in invalid_df.iterrows():
            reason = "UNKNOWN_INVALID"
            if pd.isna(row.get("저장구글시트ID")) or str(row.get("저장구글시트ID")).strip() == "":
                reason = "MISSING_TARGET_SPREADSHEET_ID"
            elif pd.isna(row.get("네이버광고계정ID")) or str(row.get("네이버광고계정ID")).strip() == "":
                reason = "MISSING_NAVER_ACCOUNT_ID"
            skipped_or_invalid_accounts.append((row.to_dict(), reason))

        # skipped 처리 (운영 안함 등) - 요약 출력을 위해 저장
        for _, row in skipped_df.iterrows():
            skipped_or_invalid_accounts.append((row.to_dict(), "SKIPPED_BY_POLICY"))

        # active 실행
        execution_plan = get_today_execution_plan(active_df, df_reports)
        reports_by_account_id = {}
        for item in execution_plan:
            account = item["account"]
            report = item["report"]
            account_id = str(account.get("네이버광고계정ID", ""))
            reports_by_account_id.setdefault(account_id, []).append(report)

        for _, row in active_df.iterrows():
            account_info = row.to_dict()
            account_reports = reports_by_account_id.get(str(account_info.get("네이버광고계정ID", "")), [])
            if not account_reports:
                continue

            report_results = process_account_reports(
                account_info["고객사명"], 
                account_info["네이버광고계정ID"], 
                account_reports, 
                is_actual_write,
                keep_files=keep_files
            )
            all_execution_results.append((account_info, report_results))
            
    elif args.all_reports:
        account_info = {"고객사명": args.account_name, "네이버광고계정ID": args.account_id}
        report_results = process_account_reports(args.account_name, args.account_id, active_reports, is_actual_write, keep_files=keep_files)
        all_execution_results.append((account_info, report_results))
        
    else:
        # 단일 보고서 모드
        account_info = {"고객사명": args.account_name, "네이버광고계정ID": args.account_id}
        res = process_report(args.account_name, args.account_id, args.report_name, is_actual_write, keep_files=keep_files)
        all_execution_results.append((account_info, [res]))

    # --- 전체 요약 출력 ---
    total_accounts_processed = len(all_execution_results)
    total_failed_skipped_accounts = len(skipped_or_invalid_accounts)
    
    total_reports_run = sum(len(results) for _, results in all_execution_results)
    success_reports_count = sum(sum(1 for r in results if r["success"]) for _, results in all_execution_results)
    fail_reports_count = total_reports_run - success_reports_count
    
    success_accounts_count = sum(1 for _, results in all_execution_results if all(r["success"] for r in results))

    if args.all_accounts:
        update_hub_status(all_execution_results, skipped_or_invalid_accounts, is_actual_write, loader)
        append_execution_logs(all_execution_results, skipped_or_invalid_accounts, is_actual_write, loader)

        total_failures_count = fail_reports_count + len(skipped_or_invalid_accounts)

        print("\n" + "="*80)
        print(" [최종 요약]")
        print("="*80)
        print(f" - 전체 CONFIG_ACCOUNTS 행 수: {total_config_accounts_count}개")
        print(f" - 실행 대상 고객사 수: {execution_target_accounts_count}개")
        print(f" - 실행 제외 고객사 수: {excluded_accounts_count}개")
        print(f" - 전체 보고서 실행 수: {total_reports_run}개")
        print(f" - 성공 수: {success_reports_count}개")
        print(f" - 실패 수: {total_failures_count}개")

        if total_failures_count > 0:
            print("-" * 80)
            print(" [조치 필요 고객사]")
            for acc, reason in skipped_or_invalid_accounts:
                account_name = _get_mapping_value(acc, ["고객사명", "고객사 명"])
                account_id = _get_mapping_value(acc, ["네이버광고계정ID", "네이버 광고계정 ID"])
                print(f" - {account_name} ({account_id}): {reason}")
            for account_info, results in all_execution_results:
                failed_results = [r for r in results if not r["success"]]
                if not failed_results:
                    continue
                account_name = _get_mapping_value(account_info, ["고객사명", "고객사 명"])
                account_id = _get_mapping_value(account_info, ["네이버광고계정ID", "네이버 광고계정 ID"])
                error_codes = ", ".join(r.get("error_code") or "UNKNOWN" for r in failed_results)
                print(f" - {account_name} ({account_id}): {error_codes}")
        print("="*80 + "\n")

        sys.exit(1 if total_failures_count > 0 else 0)

    print("\n" + "="*80)
    print(" [ 전 체 실 행 결 과 요 약 ]")
    print("="*80)
    print(f" - 전체 대상 고객사 수: {total_accounts_processed + total_failed_skipped_accounts}개")
    print(f"   * 실행 성공 고객사: {success_accounts_count}개")
    print(f"   * 실패/조치필요 고객사: {total_failed_skipped_accounts}개 (미실행 포함)")
    print(f" - 전체 보고서 실행 수: {total_reports_run}개")
    print(f"   * 성공: {success_reports_count}개")
    print(f"   * 실패: {fail_reports_count}개")
    print("-" * 80)

    # 고객사별 상세 결과
    for account_info, results in all_execution_results:
        account_name = account_info.get("고객사명", "N/A")
        account_id = account_info.get("네이버광고계정ID", "N/A")
        all_success = all(r["success"] for r in results)
        status_mark = "✅" if all_success else "⚠️"
        
        print(f"{status_mark} 고객사: {account_name} ({account_id})")
        for r in results:
            r_status = "✅" if r["success"] else "❌"
            print(f"    {r_status} 네이버보고서명: {r['report_name']}")
            if r.get("no_data"):
                print(f"        - 데이터 없음 / 저장행수 0 / {r['write_status']}")
            print(f"        - 저장탭명: {r['tab_name']}")
            print(f"        - 통계기간: {r['period']}")
            if r["download_path"]:
                print(f"        - 다운로드: {r['download_path']}")
            else:
                print(f"        - 다운로드: 실패")
            print(f"        - 저장상태: {r['write_status']}")
            if not r["success"]:
                if r.get("error_code"):
                    print(f"        - 오류코드: {r['error_code']}")
                print(f"        - 오류메시지: {r['error_message']}")
        print()

    # 실패/조치필요 고객사 리스트
    if skipped_or_invalid_accounts:
        print("-" * 80)
        print(" [ 실패/조치필요/스킵 고객사 ]")
        for acc, reason in skipped_or_invalid_accounts:
            print(f"❌ {acc.get('고객사명', 'N/A')} ({acc.get('네이버광고계정ID', 'N/A')}) -> 사유: {reason}")
        print()

    print("="*80 + "\n")

    # 허브 시트 상태 업데이트 (전체 고객사 실행 시)
    if args.all_accounts:
        update_hub_status(all_execution_results, skipped_or_invalid_accounts, is_actual_write, loader)

    # 최종 종료 코드 결정
    append_execution_logs(all_execution_results, skipped_or_invalid_accounts, is_actual_write, loader)

    if fail_reports_count > 0 or any(not is_skipped_reason(reason) for _, reason in skipped_or_invalid_accounts):
        sys.exit(1)
    else:
        sys.exit(0)

if __name__ == "__main__":
    main()
