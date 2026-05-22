import os
import io
import csv
import zipfile
import logging
import pandas as pd
from pathlib import Path
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# 날짜 컬럼 후보 키워드 (네이버 보고서 기준)
DATE_COLUMN_KEYWORDS = ["일별", "날짜", "기간", "date", "week", "주별", "월별"]

@dataclass
class ParseResult:
    """파싱 결과를 담는 데이터 클래스"""
    success: bool
    file_name: str
    report_name: str = ""
    row_count: int = 0
    column_count: int = 0
    columns: list = field(default_factory=list)
    date_column_candidates: list = field(default_factory=list)
    dataframe: pd.DataFrame = None
    no_data: bool = False
    error_type: str = ""
    error_message: str = ""


def detect_encoding(file_bytes: bytes) -> str:
    """
    인코딩 자동 감지. 네이버 CSV는 주로 EUC-KR이며, UTF-8 fallback 포함.
    """
    encodings = ["utf-8-sig", "euc-kr", "cp949", "utf-8"]
    for enc in encodings:
        try:
            file_bytes.decode(enc)
            return enc
        except (UnicodeDecodeError, AttributeError):
            continue
    return "utf-8"  # 최후 fallback


def find_date_columns(columns: list) -> list:
    """
    날짜 컬럼 후보를 감지합니다. 키워드 기반으로 찾되, 없으면 빈 리스트.
    """
    found = []
    for col in columns:
        if not isinstance(col, str):
            continue
        col_lower = col.lower().strip()
        for keyword in DATE_COLUMN_KEYWORDS:
            if keyword.lower() in col_lower:
                found.append(col)
                break
    return found


def parse_naver_csv(file_bytes: bytes, file_name: str) -> ParseResult:
    """
    네이버 다차원 보고서 CSV를 파싱합니다.
    
    네이버 CSV 구조:
    - 1행: 보고서명 + 계정ID (메타 정보)
    - 2행: 컬럼 헤더
    - 3행~: 실제 데이터
    """
    encoding = detect_encoding(file_bytes)
    
    try:
        text = file_bytes.decode(encoding)
    except Exception:
        return ParseResult(
            success=False,
            file_name=file_name,
            error_type="FILE_PARSE_ERROR",
            error_message=f"파일을 디코딩할 수 없습니다. (시도한 인코딩: {encoding})"
        )
    
    lines = text.splitlines()
    
    if len(lines) < 2:
        return ParseResult(
            success=False,
            file_name=file_name,
            error_type="EMPTY_REPORT_FILE",
            error_message="파일에 데이터가 없습니다."
        )
    
    # 1행: 보고서명 추출 (첫 번째 셀에서 괄호 이전 텍스트)
    try:
        first_row_reader = list(csv.reader([lines[0]]))
        report_name_raw = first_row_reader[0][0] if first_row_reader and first_row_reader[0] else ""
        # "데일리_살만(2026.05.10.~2026.05.10.),1855171" -> "데일리_살만"
        report_name = report_name_raw.split("(")[0].strip() if "(" in report_name_raw else report_name_raw.strip()
    except Exception:
        report_name = "알 수 없음"
    
    # 2행부터 시작하는 실제 데이터 파싱 (헤더 + 데이터)
    try:
        data_text = "\n".join(lines[1:])
        df = pd.read_csv(
            io.StringIO(data_text),
            encoding=encoding if False else None,  # StringIO 사용 시 encoding 불필요
            on_bad_lines='skip'
        )
    except Exception as e:
        return ParseResult(
            success=False,
            file_name=file_name,
            error_type="FILE_PARSE_ERROR",
            error_message="DataFrame 파싱 실패. 파일 구조를 확인하세요."
        )
    
    # 완전히 빈 행 제거
    df.dropna(how='all', inplace=True)
    
    if df.empty:
        return ParseResult(
            success=True,
            file_name=file_name,
            report_name=report_name,
            row_count=0,
            column_count=len(df.columns),
            columns=list(df.columns),
            date_column_candidates=find_date_columns(list(df.columns)),
            dataframe=df,
            no_data=True,
        )
    
    columns = list(df.columns)
    date_cols = find_date_columns(columns)
    
    return ParseResult(
        success=True,
        file_name=file_name,
        report_name=report_name,
        row_count=len(df),
        column_count=len(columns),
        columns=columns,
        date_column_candidates=date_cols,
        dataframe=df
    )


def parse_naver_xlsx(file_bytes: bytes, file_name: str) -> ParseResult:
    """
    네이버 다차원 보고서 XLSX를 파싱합니다.
    CSV와 동일 구조 가정: 1행 메타, 2행 헤더, 3행~ 데이터.
    """
    try:
        df_raw = pd.read_excel(
            io.BytesIO(file_bytes),
            header=None,
            engine='openpyxl'
        )
    except Exception:
        return ParseResult(
            success=False,
            file_name=file_name,
            error_type="FILE_PARSE_ERROR",
            error_message="XLSX 파일 파싱 실패. 파일이 손상되었거나 형식이 다릅니다."
        )
    
    if df_raw.empty or len(df_raw) < 2:
        return ParseResult(
            success=False,
            file_name=file_name,
            error_type="EMPTY_REPORT_FILE",
            error_message="XLSX 파일에 데이터가 없습니다."
        )
    
    # 1행: 보고서명 추출
    try:
        report_name_raw = str(df_raw.iloc[0, 0])
        report_name = report_name_raw.split("(")[0].strip() if "(" in report_name_raw else report_name_raw.strip()
    except Exception:
        report_name = "알 수 없음"
    
    # 2행을 헤더로, 3행부터 데이터로
    df = df_raw.iloc[1:].copy()
    df.columns = df.iloc[0]
    df = df.iloc[1:].reset_index(drop=True)
    df.dropna(how='all', inplace=True)
    
    if df.empty:
        return ParseResult(
            success=True,
            file_name=file_name,
            report_name=report_name,
            row_count=0,
            column_count=len(df.columns),
            columns=list(df.columns),
            date_column_candidates=find_date_columns(list(df.columns)),
            dataframe=df,
            no_data=True,
        )
    
    columns = list(df.columns)
    date_cols = find_date_columns(columns)
    
    return ParseResult(
        success=True,
        file_name=file_name,
        report_name=report_name,
        row_count=len(df),
        column_count=len(columns),
        columns=columns,
        date_column_candidates=date_cols,
        dataframe=df
    )


def parse_file(file_path: str) -> ParseResult:
    """
    파일 경로를 받아 확장자에 맞는 파서를 실행합니다.
    ZIP이면 내부 CSV/XLSX를 찾아 파싱합니다.
    원본 파일을 수정하지 않습니다.
    """
    path = Path(file_path)
    file_name = path.name
    
    if not path.exists():
        return ParseResult(
            success=False,
            file_name=file_name,
            error_type="FILE_PARSE_ERROR",
            error_message=f"파일이 존재하지 않습니다: {file_path}"
        )
    
    with open(file_path, 'rb') as f:
        file_bytes = f.read()
    
    if len(file_bytes) == 0:
        return ParseResult(
            success=False,
            file_name=file_name,
            error_type="EMPTY_REPORT_FILE",
            error_message="파일 크기가 0바이트입니다."
        )
    
    suffix = path.suffix.lower()
    
    if suffix == '.csv':
        return parse_naver_csv(file_bytes, file_name)
    
    elif suffix in ('.xlsx', '.xls'):
        return parse_naver_xlsx(file_bytes, file_name)
    
    elif suffix == '.zip':
        # ZIP 내부에서 csv/xlsx 파일 탐색
        try:
            with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
                inner_files = [n for n in zf.namelist() if n.lower().endswith(('.csv', '.xlsx'))]
                
                if not inner_files:
                    return ParseResult(
                        success=False,
                        file_name=file_name,
                        error_type="FILE_PARSE_ERROR",
                        error_message="ZIP 내부에 CSV/XLSX 파일이 없습니다."
                    )
                
                # 첫 번째 파일을 파싱 대상으로 사용
                inner_name = inner_files[0]
                inner_bytes = zf.read(inner_name)
                inner_suffix = Path(inner_name).suffix.lower()
                
                logger.info(f"ZIP 내부 파일 파싱 중: {inner_name}")
                
                if inner_suffix == '.csv':
                    return parse_naver_csv(inner_bytes, inner_name)
                else:
                    return parse_naver_xlsx(inner_bytes, inner_name)
        
        except zipfile.BadZipFile:
            return ParseResult(
                success=False,
                file_name=file_name,
                error_type="FILE_PARSE_ERROR",
                error_message="ZIP 파일이 손상되었습니다."
            )
    
    else:
        return ParseResult(
            success=False,
            file_name=file_name,
            error_type="FILE_PARSE_ERROR",
            error_message=f"지원하지 않는 파일 형식입니다: {suffix} (지원: csv, xlsx, zip)"
        )


if __name__ == '__main__':
    import glob
    import sys

    # Windows 터미널 인코딩 안전 처리
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    
    SAMPLE_DIR = "downloads/samples/paperbag100"
    
    print(f"\n--- 보고서 샘플 파싱 테스트 ---")
    print(f"경로: {SAMPLE_DIR}\n")
    
    all_files = glob.glob(os.path.join(SAMPLE_DIR, "*.csv")) + \
                glob.glob(os.path.join(SAMPLE_DIR, "*.xlsx")) + \
                glob.glob(os.path.join(SAMPLE_DIR, "*.zip"))
    
    if not all_files:
        print(f"[경고] 샘플 파일이 없습니다. '{SAMPLE_DIR}' 폴더에 네이버 보고서 파일을 넣어주세요.")
    else:
        for file_path in sorted(all_files):
            result = parse_file(file_path)
            print(f"[ 파일명: {result.file_name} ]")
            
            if result.success:
                print(f"  [성공] 파싱 성공")
                print(f"  감지된 보고서명: {result.report_name}")
                print(f"  행 수: {result.row_count}")
                print(f"  컬럼 수: {result.column_count}")
                print(f"  날짜 컬럼 후보: {result.date_column_candidates if result.date_column_candidates else '없음 (수동 확인 필요)'}")
                print(f"  컬럼 목록: {result.columns}")
            else:
                print(f"  [실패] 파싱 실패")
                print(f"  오류 유형: {result.error_type}")
                print(f"  오류 내용: {result.error_message}")
            
            print()
