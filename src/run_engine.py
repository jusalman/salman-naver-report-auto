import argparse
import sys
import subprocess
import os
import pandas as pd
from src.naver_report_downloader import download_report
from src.config_loader import ConfigLoader

def process_report(account_name, account_id, report_info, is_actual_write):
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
        "write_status": "PENDING",
        "error_message": ""
    }

    # 1. 네이버 광고센터 보고서 다운로드
    try:
        csv_path = download_report(account_id, report_name, headless=False)
    except Exception as e:
        result["error_message"] = f"UNKNOWN_RUN_ENGINE_ERROR: {str(e)}"
        print(f"\n[❌] {result['error_message']}")
        return result

    if not csv_path:
        result["error_message"] = "DOWNLOAD_FAILED: 세션 만료 또는 보고서 탐색 실패"
        print(f"\n[❌] {result['error_message']}")
        return result

    print(f"[*] 다운로드 완료: {csv_path}")
    result["download_path"] = csv_path

    # 2. report_writer를 이용한 구글 시트 저장 (subprocess 호출)
    cmd = [
        sys.executable, "-m", "src.report_writer",
        "--account-name", account_name,
        "--report-name", report_name,
        "--file-path", csv_path,
        writer_mode
    ]

    print(f"[*] 데이터 저장 단계 진입 ({writer_mode})...")
    try:
        # check=False로 설정하여 내부 에러 메시지를 직접 처리
        proc_result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        
        # subprocess 출력 연결
        if proc_result.stdout:
            print(proc_result.stdout)
        if proc_result.stderr:
            print(proc_result.stderr, file=sys.stderr)

        if proc_result.returncode != 0:
            result["error_message"] = f"REPORT_WRITE_FAILED (Exit Code: {proc_result.returncode})"
            result["write_status"] = "FAILED"
            print(f"\n[❌] {result['error_message']}")
            return result

    except Exception as e:
        result["error_message"] = f"UNKNOWN_RUN_ENGINE_ERROR: {str(e)}"
        result["write_status"] = "FAILED"
        print(f"\n[❌] {result['error_message']}")
        return result

    result["success"] = True
    result["write_status"] = "ACTUAL_WRITE_SUCCESS" if is_actual_write else "DRY_RUN_SUCCESS"
    print(f"\n[✅] '{report_name}' 처리 성공")
    
    return result

def process_account_reports(account_name, account_id, active_reports, is_actual_write):
    """특정 고객사의 모든 활성 보고서를 순차적으로 실행합니다."""
    print(f"\n" + "#"*60)
    print(f"### 고객사 실행 시작: {account_name} ({account_id}) ###")
    print("#"*60)
    
    account_results = []
    for r_info in active_reports:
        res = process_report(account_name, account_id, r_info, is_actual_write)
        account_results.append(res)
    
    return account_results

def main():
    parser = argparse.ArgumentParser(description="SalMan Naver Report Auto Engine")
    parser.add_argument("--account-name", type=str, help="Customer name (e.g. 페이퍼백)")
    parser.add_argument("--account-id", type=str, help="Naver account ID (e.g. 1855171)")
    parser.add_argument("--report-name", type=str, help="Report name (e.g. 데일리_살만)")
    parser.add_argument("--all-reports", action="store_true", help="Run all predefined reports for the account")
    parser.add_argument("--all-accounts", action="store_true", help="Run all active accounts and their active reports")
    parser.add_argument("--dry-run", action="store_true", help="Dry run mode (validate only)")
    parser.add_argument("--write", action="store_true", help="Actual write mode")

    args = parser.parse_args()

    # 인자 유효성 검사
    if not args.all_accounts:
        if not args.account_name or not args.account_id:
            parser.error("--account-name and --account-id are required unless --all-accounts is used.")
        if not args.all_reports and not args.report_name:
            parser.error("--report-name must be specified unless --all-reports or --all-accounts is used.")

    # 모드 결정 (기본값 dry-run)
    is_actual_write = args.write
    loader = ConfigLoader()
    
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

    if args.all_accounts:
        print("\n[*] 전체 고객사 실행 모드 진입")
        active_df, skipped_df, invalid_df = loader.get_filtered_accounts()
        
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
        for _, row in active_df.iterrows():
            account_info = row.to_dict()
            report_results = process_account_reports(
                account_info["고객사명"], 
                account_info["네이버광고계정ID"], 
                active_reports, 
                is_actual_write
            )
            all_execution_results.append((account_info, report_results))
            
    elif args.all_reports:
        account_info = {"고객사명": args.account_name, "네이버광고계정ID": args.account_id}
        report_results = process_account_reports(args.account_name, args.account_id, active_reports, is_actual_write)
        all_execution_results.append((account_info, report_results))
        
    else:
        # 단일 보고서 모드
        account_info = {"고객사명": args.account_name, "네이버광고계정ID": args.account_id}
        res = process_report(args.account_name, args.account_id, args.report_name, is_actual_write)
        all_execution_results.append((account_info, [res]))

    # --- 전체 요약 출력 ---
    total_accounts_processed = len(all_execution_results)
    total_failed_skipped_accounts = len(skipped_or_invalid_accounts)
    
    total_reports_run = sum(len(results) for _, results in all_execution_results)
    success_reports_count = sum(sum(1 for r in results if r["success"]) for _, results in all_execution_results)
    fail_reports_count = total_reports_run - success_reports_count
    
    success_accounts_count = sum(1 for _, results in all_execution_results if all(r["success"] for r in results))

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
            print(f"        - 저장탭명: {r['tab_name']}")
            print(f"        - 통계기간: {r['period']}")
            if r["download_path"]:
                print(f"        - 다운로드: {r['download_path']}")
            else:
                print(f"        - 다운로드: 실패")
            print(f"        - 저장상태: {r['write_status']}")
            if not r["success"]:
                print(f"        - 오류원인: {r['error_message']}")
        print()

    # 실패/조치필요 고객사 리스트
    if skipped_or_invalid_accounts:
        print("-" * 80)
        print(" [ 실패/조치필요/스킵 고객사 ]")
        for acc, reason in skipped_or_invalid_accounts:
            print(f"❌ {acc.get('고객사명', 'N/A')} ({acc.get('네이버광고계정ID', 'N/A')}) -> 사유: {reason}")
        print()

    print("="*80 + "\n")

    # 최종 종료 코드 결정
    if fail_reports_count > 0 or any(reason != "SKIPPED_BY_POLICY" for _, reason in skipped_or_invalid_accounts):
        sys.exit(1)
    else:
        sys.exit(0)

if __name__ == "__main__":
    main()
