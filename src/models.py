EXPECTED_COLUMNS_ACCOUNTS = [
    "실행여부", "운영상태", "실행순서", "고객사명", "네이버광고계정명", 
    "네이버광고계정ID", "저장구글시트ID", "저장구글시트명", "데일리전환다운로드", 
    "위클리키워드다운로드", "데일리성과다운로드", "담당자", "메모", 
    "마지막실행일시", "마지막실행결과", "최근다운로드파일경로", "오류내용"
]

EXPECTED_COLUMNS_REPORTS = [
    "실행여부", "보고서구분", "네이버보고서명", "저장탭명", 
    "통계기간", "실행주기", "고객사별실행컬럼", "설명"
]

EXPECTED_COLUMNS_DOWNLOAD_LOG = [
    "run_id", "실행일시", "고객사명", "네이버광고계정명", "네이버광고계정ID", 
    "보고서구분", "네이버보고서명", "저장탭명", "통계기간", "다운로드파일명", 
    "저장행수", "결과", "오류내용"
]

EXPECTED_COLUMNS_ERROR_LOG = [
    "run_id", "실행일시", "단계", "고객사명", "네이버광고계정ID", 
    "보고서구분", "오류유형", "오류내용", "조치필요여부", "담당자확인"
]

REQUIRED_FIELDS_ACCOUNTS = ["고객사명", "네이버광고계정ID", "저장구글시트ID"]

# 실행 주기 상수
SCHEDULE_DAILY = "매일"
SCHEDULE_WEEKLY_MONDAY = "매주월요일"

LEGACY_REPORT_NAME_TO_STANDARD_NAME = {
    "데일리_살만": "데일리SA_RAW",
    "위클리키워드_살만": "위클리키워드SA_RAW",
    "데일리전환_살만": "데일리전환SA_RAW",
}

STANDARD_REPORT_NAMES = [
    "데일리SA_RAW",
    "위클리키워드SA_RAW",
    "데일리전환SA_RAW",
]

STANDARD_REPORT_TABS = {
    **LEGACY_REPORT_NAME_TO_STANDARD_NAME,
    **{report_name: report_name for report_name in STANDARD_REPORT_NAMES},
}

def normalize_report_destination(report_name, tab_name=""):
    report_name = "" if report_name is None else str(report_name).strip()
    tab_name = "" if tab_name is None else str(tab_name).strip()

    if report_name in STANDARD_REPORT_TABS:
        standard_name = STANDARD_REPORT_TABS[report_name]
        return standard_name, standard_name

    if tab_name in STANDARD_REPORT_TABS:
        standard_name = STANDARD_REPORT_TABS[tab_name]
        return report_name or standard_name, standard_name

    return report_name, tab_name

DEFAULT_REPORT_CONFIGS = [
    {
        "실행여부": "TRUE",
        "보고서구분": "데일리성과",
        "네이버보고서명": "데일리SA_RAW",
        "저장탭명": "데일리SA_RAW",
        "통계기간": "전일",
        "실행주기": SCHEDULE_DAILY,
        "고객사별실행컬럼": "데일리성과다운로드",
        "설명": "기본 데일리 SA 보고서",
    },
    {
        "실행여부": "TRUE",
        "보고서구분": "위클리키워드",
        "네이버보고서명": "위클리키워드SA_RAW",
        "저장탭명": "위클리키워드SA_RAW",
        "통계기간": "최근 7일",
        "실행주기": SCHEDULE_WEEKLY_MONDAY,
        "고객사별실행컬럼": "위클리키워드다운로드",
        "설명": "기본 위클리 키워드 SA 보고서",
    },
    {
        "실행여부": "TRUE",
        "보고서구분": "데일리전환",
        "네이버보고서명": "데일리전환SA_RAW",
        "저장탭명": "데일리전환SA_RAW",
        "통계기간": "전일",
        "실행주기": SCHEDULE_DAILY,
        "고객사별실행컬럼": "데일리전환다운로드",
        "설명": "기본 데일리 전환 SA 보고서",
    },
]
