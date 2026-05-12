import os
import logging
import pandas as pd
from dotenv import load_dotenv
from src.google_sheet_client import GoogleSheetClient
from src.run_policy import filter_active_accounts, get_today_execution_plan
from src.models import (
    EXPECTED_COLUMNS_ACCOUNTS, 
    EXPECTED_COLUMNS_REPORTS, 
    EXPECTED_COLUMNS_DOWNLOAD_LOG, 
    EXPECTED_COLUMNS_ERROR_LOG
)

load_dotenv()

# 로그 설정
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

class ConfigLoader:
    def __init__(self):
        self.spreadsheet_id = os.getenv("HUB_SPREADSHEET_ID")
        if not self.spreadsheet_id or self.spreadsheet_id.strip() == "" or self.spreadsheet_id.startswith("#"):
            raise ValueError("HUB_SPREADSHEET_ID is missing or empty in .env file.")
        
        self.sheet_client = GoogleSheetClient()

    def _read_and_validate(self, tab_name: str, expected_columns: list) -> pd.DataFrame:
        """
        탭 데이터를 읽고 컬럼 스키마를 검증한 후 정제된 DataFrame을 반환합니다.
        GoogleSheetClient.get_sheet_data가 이미 행 길이 보정 및 빈 행 제거를 수행합니다.
        """
        logger.info(f"Reading data from tab: {tab_name}...")
        raw_data = self.sheet_client.get_sheet_data(self.spreadsheet_id, f"{tab_name}!A:Z")
        
        if not raw_data or len(raw_data) < 1:
            logger.warning(f"Tab '{tab_name}' is empty or could not be read.")
            return pd.DataFrame()

        # 첫 행은 헤더, 나머지는 데이터
        headers = raw_data[0]
        data_rows = raw_data[1:]
        
        df = pd.DataFrame(data_rows, columns=headers)

        # 필수 컬럼 존재 여부 확인 및 경고
        missing_columns = [col for col in expected_columns if col not in headers]
        if missing_columns:
            logger.warning(f"[{tab_name}] Missing expected columns: {missing_columns}")

        logger.info(f"Successfully loaded {len(df)} rows from {tab_name}.")
        return df

    def load_config_accounts(self) -> pd.DataFrame:
        return self._read_and_validate("CONFIG_ACCOUNTS", EXPECTED_COLUMNS_ACCOUNTS)

    def load_config_reports(self) -> pd.DataFrame:
        return self._read_and_validate("CONFIG_REPORTS", EXPECTED_COLUMNS_REPORTS)

    def load_download_log(self) -> pd.DataFrame:
        return self._read_and_validate("DOWNLOAD_LOG", EXPECTED_COLUMNS_DOWNLOAD_LOG)

    def load_error_log(self) -> pd.DataFrame:
        return self._read_and_validate("ERROR_LOG", EXPECTED_COLUMNS_ERROR_LOG)

    def get_filtered_accounts(self):
        """
        CONFIG_ACCOUNTS 탭을 읽어 실행 정책에 따라 필터링된 결과를 반환합니다.
        """
        df = self.load_config_accounts()
        return filter_active_accounts(df)

if __name__ == '__main__':
    try:
        loader = ConfigLoader()
        print("\n--- Testing Account Filtering & Execution Planning ---")
        
        # 1. 고객사 필터링 테스트
        active, skipped, invalid = loader.get_filtered_accounts()
        
        # 2. 보고서 설정 로드
        reports = loader.load_config_reports()
        
        print(f"\n[ Account Stats ]")
        print(f"✅ 활성 고객사 수: {len(active)}")
        print(f"✅ 스킵 고객사 수: {len(skipped)}")
        print(f"✅ 설정 오류 고객사 수: {len(invalid)}")

        # 3. 오늘 실행 계획 생성 테스트
        plan = get_today_execution_plan(active, reports)
        
        print(f"\n[ Execution Plan Stats ]")
        # 중복 제거한 고객사 수 계산
        active_count_in_plan = len(set(p['account']['고객사명'] for p in plan)) if plan else 0
        print(f"✅ 오늘 실행할 고객사 수: {active_count_in_plan}")
        print(f"✅ 오늘 실행할 보고서 작업 수: {len(plan)}")
        
        if plan:
            report_types = {}
            for p in plan:
                rtype = p['report']['보고서구분']
                report_types[rtype] = report_types.get(rtype, 0) + 1
            
            print(f"\n[ 보고서구분별 작업 수 ]")
            for rtype, count in report_types.items():
                print(f"- {rtype}: {count}")
        else:
            print(f"\n⚠️ 오늘 실행할 보고서가 없습니다.")
            
    except ValueError as e:
        print(f"\n❌ Configuration Error: {e}")
    except Exception as e:
        # 민감 정보 보호를 위해 상세 에러는 로그에만 남김
        logger.error(f"Unexpected Error: {str(e)}")
        print(f"\n❌ Execution Error: An unexpected error occurred. Please check credentials and sheet ID.")
