import argparse
import sys
import subprocess
import os
from src.naver_report_downloader import download_report

def process_report(account_name, account_id, report_name, is_actual_write):
    """단일 보고서에 대해 다운로드 및 구글시트 저장을 수행합니다."""
    writer_mode = "--write" if is_actual_write else "--dry-run"
    print(f"\n" + "="*60)
    print(f"[*] 보고서 처리 시작: {report_name}")
    print("="*60)

    result = {
        "report_name": report_name,
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
        proc_result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        
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

def main():
    parser = argparse.ArgumentParser(description="SalMan Naver Report Auto Engine")
    parser.add_argument("--account-name", type=str, required=True, help="Customer name (e.g. 페이퍼백)")
    parser.add_argument("--account-id", type=str, required=True, help="Naver account ID (e.g. 1855171)")
    parser.add_argument("--report-name", type=str, help="Report name (e.g. 데일리_살만)")
    parser.add_argument("--all-reports", action="store_true", help="Run all predefined reports for the account")
    parser.add_argument("--dry-run", action="store_true", help="Dry run mode (validate only)")
    parser.add_argument("--write", action="store_true", help="Actual write mode")

    args = parser.parse_args()

    if not args.all_reports and not args.report_name:
        parser.error("--report-name must be specified unless --all-reports is used.")

    # 모드 결정 (기본값 dry-run)
    is_actual_write = args.write

    # 대상 보고서 목록 설정
    reports_to_run = []
    if args.all_reports:
        reports_to_run = ["데일리전환_살만", "데일리_살만", "위클리키워드_살만"]
    else:
        reports_to_run = [args.report_name]

    print(f"\n[*] SalMan 실행 엔진 시작: {args.account_name} ({args.account_id})")
    print(f"[*] 대상 보고서 수: {len(reports_to_run)}개")
    print(f"[*] 실행 모드: {'실제 저장 (WRITE)' if is_actual_write else '검증 전용 (DRY-RUN)'}")
    
    results = []
    for report_name in reports_to_run:
        res = process_report(args.account_name, args.account_id, report_name, is_actual_write)
        results.append(res)

    # 전체 요약 출력
    total = len(results)
    success_count = sum(1 for r in results if r["success"])
    fail_count = total - success_count

    print("\n" + "="*60)
    print(" [ 전체 실행 결과 요약 ]")
    print(f" - 대상 고객사: {args.account_name} ({args.account_id})")
    print(f" - 전체 보고서: {total}개")
    print(f" - 성공: {success_count}개")
    print(f" - 실패: {fail_count}개")
    print("-" * 60)
    
    for r in results:
        status_icon = "✅" if r["success"] else "❌"
        print(f"{status_icon} 보고서명: {r['report_name']}")
        if r["download_path"]:
            print(f"    - 다운로드: {r['download_path']}")
        else:
            print(f"    - 다운로드: 실패")
        
        print(f"    - 저장상태: {r['write_status']}")
        
        if not r["success"]:
            print(f"    - 오류원인: {r['error_message']}")
        print()
    print("="*60 + "\n")

    # 하나라도 실패한 경우 에러 코드 반환
    if fail_count > 0:
        sys.exit(1)
    else:
        sys.exit(0)

if __name__ == "__main__":
    main()
