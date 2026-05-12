import pandas as pd
import logging
import datetime
import pytz
from src.models import SCHEDULE_DAILY, SCHEDULE_WEEKLY_MONDAY

logger = logging.getLogger(__name__)

def filter_active_accounts(df: pd.DataFrame):
    """
    CONFIG_ACCOUNTS에서 실제 실행 대상 고객사만 필터링합니다.
    
    조건:
    1. 실행여부 == TRUE
    2. 운영상태 == 운영중
    3. 고객사명, 네이버광고계정ID, 저장구글시트ID 필수값 존재
    
    Returns:
        tuple: (active_accounts, skipped_accounts, invalid_accounts)
    """
    if df.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    # 데이터 복사본 작업
    df_copy = df.copy()

    # 1. 다운로드 여부 컬럼 TRUE/FALSE 정규화
    bool_cols = ["데일리전환다운로드", "위클리키워드다운로드", "데일리성과다운로드"]
    for col in bool_cols:
        if col in df_copy.columns:
            # 문자열 'TRUE'인 경우만 True로 변환, 나머지는 False
            df_copy[col] = df_copy[col].astype(str).str.strip().str.upper() == 'TRUE'

    # 2. 필수 필드 체크
    required_fields = ["고객사명", "네이버광고계정ID", "저장구글시트ID"]
    
    # 컬럼 존재 여부 확인
    available_required = [f for f in required_fields if f in df_copy.columns]
    
    # 필수값 중 하나라도 비어있는지 확인 (NaN 또는 빈 문자열)
    def is_empty(val):
        if pd.isna(val): return True
        if str(val).strip() == '': return True
        return False

    # invalid: 필수 필드가 누락된 경우
    invalid_mask = df_copy[available_required].apply(lambda row: any(is_empty(x) for x in row), axis=1)
    
    # 만약 필수 컬럼 자체가 없으면 전체가 invalid
    if len(available_required) < len(required_fields):
        invalid_mask[:] = True

    invalid_accounts = df_copy[invalid_mask].copy()
    valid_candidates = df_copy[~invalid_mask].copy()

    # 3. 실행 대상 필터링 (실행여부 == TRUE AND 운영상태 == 운영중)
    if "실행여부" in valid_candidates.columns and "운영상태" in valid_candidates.columns:
        is_active_mask = (valid_candidates["실행여부"].astype(str).str.strip().str.upper() == 'TRUE') & \
                         (valid_candidates["운영상태"].astype(str).str.strip() == '운영중')
        
        active_accounts = valid_candidates[is_active_mask].copy()
        skipped_accounts = valid_candidates[~is_active_mask].copy()
    else:
        active_accounts = pd.DataFrame()
        skipped_accounts = valid_candidates.copy()

    # 4. 실행순서 기준 정렬
    if not active_accounts.empty and "실행순서" in active_accounts.columns:
        active_accounts["실행순서"] = pd.to_numeric(active_accounts["실행순서"], errors='coerce').fillna(999)
        active_accounts = active_accounts.sort_values(by="실행순서").reset_index(drop=True)

    return active_accounts, skipped_accounts, invalid_accounts

def get_today_execution_plan(active_accounts: pd.DataFrame, config_reports: pd.DataFrame, target_date=None):
    """
    오늘 실행해야 할 보고서 실행 계획(account + report 조합)을 생성합니다.
    
    Args:
        active_accounts: 필터링된 활성 고객사 DataFrame
        config_reports: CONFIG_REPORTS 설정 DataFrame
        target_date: 테스트용 기준 날짜 (None이면 오늘)
        
    Returns:
        list[dict]: [{'account': dict, 'report': dict}, ...]
    """
    if active_accounts.empty or config_reports.empty:
        return []

    if target_date is None:
        # Asia/Seoul 기준 오늘 날짜 계산
        seoul_tz = pytz.timezone('Asia/Seoul')
        target_date = datetime.datetime.now(seoul_tz).date()
    
    # 요일 계산 (0: 월요일, 1: 화요일, ..., 6: 일요일)
    day_of_week = target_date.weekday()
    is_monday = (day_of_week == 0)

    logger.info(f"Generating execution plan for date: {target_date} (Monday: {is_monday})")

    # 1. 전역 리포트 설정 필터링 (실행여부 == TRUE)
    active_reports = config_reports[config_reports["실행여부"].astype(str).str.strip().str.upper() == 'TRUE'].copy()
    
    # 2. 실행 주기 필터링
    def should_run_by_schedule(schedule):
        if schedule == SCHEDULE_DAILY:
            return True
        if schedule == SCHEDULE_WEEKLY_MONDAY and is_monday:
            return True
        return False

    active_reports["should_run_today"] = active_reports["실행주기"].apply(should_run_by_schedule)
    reports_to_run = active_reports[active_reports["should_run_today"]].copy()

    execution_plan = []
    
    # 3. 고객사별 상세 필터링
    for _, account in active_accounts.iterrows():
        for _, report in reports_to_run.iterrows():
            account_exec_col = report["고객사별실행컬럼"]
            
            # 고객사 설정 탭에 해당 컬럼이 있고 값이 True(이미 정규화됨)인 경우만 추가
            if account_exec_col in account and account[account_exec_col] is True:
                execution_plan.append({
                    "account": account.to_dict(),
                    "report": report.to_dict()
                })

    return execution_plan
