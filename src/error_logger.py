import os
import datetime
import pytz
import logging
from src.google_sheet_client import GoogleSheetClient

logger = logging.getLogger(__name__)

class ErrorLogger:
    def __init__(self):
        self.spreadsheet_id = os.getenv("HUB_SPREADSHEET_ID")
        self.sheet_client = GoogleSheetClient()
        self.seoul_tz = pytz.timezone('Asia/Seoul')

    def generate_run_id(self, mode="manual"):
        """
        run_id를 생성합니다. 형식: YYYYMMDD_HHMMSS_manual
        """
        now = datetime.datetime.now(self.seoul_tz)
        return now.strftime(f"%Y%m%d_%H%M%S_{mode}")

    def log_download(self, data: dict):
        """
        DOWNLOAD_LOG 탭에 로그를 추가합니다.
        필수 키: run_id, 고객사명, 네이버광고계정ID, 보고서구분, 결과
        """
        now_str = datetime.datetime.now(self.seoul_tz).strftime("%Y-%m-%d %H:%M:%S")
        
        # DOWNLOAD_LOG 스키마 순서에 맞춤
        row = [
            data.get("run_id", ""),
            now_str,
            data.get("고객사명", ""),
            data.get("네이버광고계정명", ""),
            data.get("네이버광고계정ID", ""),
            data.get("보고서구분", ""),
            data.get("네이버보고서명", ""),
            data.get("저장탭명", ""),
            data.get("통계기간", ""),
            data.get("다운로드파일명", ""),
            data.get("저장행수", 0),
            data.get("결과", ""),
            data.get("오류내용", "")
        ]
        
        logger.info(f"Logging to DOWNLOAD_LOG: {data.get('고객사명')} - {data.get('보고서구분')}")
        return self.sheet_client.append_sheet_data(self.spreadsheet_id, "DOWNLOAD_LOG!A:M", [row])

    def append_error_log(self, data: dict):
        """Append a row dict to the ERROR_LOG tab.
        The row must follow the ERROR_LOG header order (A:J).
        Missing keys are filled with empty strings.
        """
        now_str = datetime.datetime.now(self.seoul_tz).strftime("%Y-%m-%d %H:%M:%S")
        # Build row with exact 10 columns in order
        row = [
            data.get("run_id", ""),               # A: run_id
            now_str,                                 # B: 실행일시
            data.get("단계", ""),                  # C: 단계
            data.get("고객사명", ""),              # D: 고객사명
            data.get("네이버광고계정ID", ""),       # E: 네이버광고계정ID
            data.get("보고서구분", ""),            # F: 보고서구분
            data.get("오류유형", ""),              # G: 오류유형
            data.get("오류내용", ""),              # H: 오류내용
            data.get("조치필요여부", ""),          # I: 조치필요여부
            data.get("담당자확인", "")            # J: 담당자확인
        ]
        logger.info(f"Logging to ERROR_LOG: {data.get('고객사명')} - {data.get('오류유형')}")
        # Use range A:J to write only the 10 columns
        return self.sheet_client.append_sheet_data(self.spreadsheet_id, "ERROR_LOG!A:J", [row])

# helper function for external use
def append_error_log(row: dict):
    """Convenient wrapper to log an error row using a fresh ErrorLogger instance."""
    logger = ErrorLogger()
    return logger.append_error_log(row)

def append_download_log(row: dict):
    """Append a row dict to DOWNLOAD_LOG using hub spreadsheet.
    Returns the Google Sheets API response.
    """
    logger = ErrorLogger()
    return logger.log_download(row)

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='ErrorLogger utilities')
    parser.add_argument('--test-download-log', action='store_true', help='Append a test row to DOWNLOAD_LOG')
    args = parser.parse_args()
    if args.test_download_log:
        el = ErrorLogger()
        run_id = el.generate_run_id()
        test_data = {
            "run_id": run_id,
            "고객사명": "페이퍼백",
            "네이버광고계정명": "paperbag100",
            "네이버광고계정ID": "1855171",
            "보고서구분": "데일리성과",
            "네이버보고서명": "데일리_살만",
            "저장탭명": "데일리_살만",
            "통계기간": "어제",
            "다운로드파일명": "paperbag100.csv",
            "저장행수": 74,
            "결과": "성공",
            "오류내용": ""
        }
        result = el.log_download(test_data)
        print('Download log append result:', result)
