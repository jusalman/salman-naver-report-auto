import argparse
import sys
import subprocess
import os
from src.naver_report_downloader import download_report

def main():
    parser = argparse.ArgumentParser(description="SalMan Naver Report Auto Engine")
    parser.add_argument("--account-name", type=str, required=True, help="Customer name (e.g. 페이퍼백)")
    parser.add_argument("--account-id", type=str, required=True, help="Naver account ID (e.g. 1855171)")
    parser.add_argument("--report-name", type=str, required=True, help="Report name (e.g. 데일리_살만)")
    parser.add_argument("--dry-run", action="store_true", help="Dry run mode (validate only)")
    parser.add_argument("--write", action="store_true", help="Actual write mode")

    args = parser.parse_args()

    # 모드 결정 (기본값 dry-run)
    is_actual_write = args.write
    writer_mode = "--write" if is_actual_write else "--dry-run"

    print(f"\n[*] SalMan 실행 엔진 시작: {args.account_name} ({args.account_id}) / {args.report_name}")
    print(f"[*] 실행 모드: {'실제 저장 (WRITE)' if is_actual_write else '검증 전용 (DRY-RUN)'}")
    
    # 1. 네이버 광고센터 보고서 다운로드
    try:
        # Playwright를 이용한 세션 기반 다운로드
        csv_path = download_report(args.account_id, args.report_name, headless=False)
    except Exception as e:
        print(f"\n[❌] UNKNOWN_RUN_ENGINE_ERROR: {str(e)}")
        sys.exit(1)

    if not csv_path:
        print(f"\n[❌] DOWNLOAD_FAILED: 보고서 다운로드에 실패했습니다. (세션 만료 또는 보고서 탐색 실패)")
        sys.exit(1)

    print(f"[*] 다운로드 완료: {csv_path}")

    # 2. report_writer를 이용한 구글 시트 저장 (subprocess 호출)
    # 이미 구현된 report_writer의 --file-path 옵션을 활용하여 결합도를 낮춤
    cmd = [
        sys.executable, "-m", "src.report_writer",
        "--account-name", args.account_name,
        "--report-name", args.report_name,
        "--file-path", csv_path,
        writer_mode
    ]

    print(f"[*] 데이터 저장 단계 진입 ({writer_mode})...")
    try:
        # check=False로 설정하여 내부 에러 메시지를 직접 처리
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        
        # subprocess 출력 연결
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(result.stderr, file=sys.stderr)

        if result.returncode != 0:
            print(f"\n[❌] REPORT_WRITE_FAILED: 구글 시트 저장 도중 오류가 발생했습니다. (Exit Code: {result.returncode})")
            sys.exit(result.returncode)

    except Exception as e:
        print(f"\n[❌] UNKNOWN_RUN_ENGINE_ERROR: {str(e)}")
        sys.exit(1)

    print(f"\n[✅] 모든 프로세스가 성공적으로 완료되었습니다.")
    if is_actual_write:
        print(f" - 최종 결과: 데이터 저장 완료 (Google Sheets)")
    else:
        print(f" - 최종 결과: Dry-run 검증 성공 (저장되지 않음)")

if __name__ == "__main__":
    main()
