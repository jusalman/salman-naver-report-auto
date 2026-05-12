import streamlit as st
import os
import pandas as pd
from datetime import datetime
import pytz
from dotenv import load_dotenv
import subprocess
import sys

from src.google_auth import get_google_credentials
from src.google_sheet_client import GoogleSheetClient

# .env 로드
load_dotenv()

# 페이지 설정
st.set_page_config(
    page_title="SALMAN OS - Naver Ads Report Auto",
    page_icon="📊",
    layout="wide"
)

# 커스텀 CSS (프리미엄 스타일링)
st.markdown("""
    <style>
    .main {
        background-color: #f8f9fa;
    }
    .stMetric {
        background-color: white;
        padding: 15px;
        border-radius: 10px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        border: 1px solid #eee;
    }
    div[data-testid="stExpander"] {
        border: none;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        background-color: white;
        border-radius: 10px;
        margin-bottom: 1rem;
    }
    </style>
    """, unsafe_allow_html=True)

@st.cache_resource
def get_client():
    try:
        return GoogleSheetClient()
    except Exception as e:
        return str(e)

@st.cache_data(ttl=60)
def fetch_as_df(_client, spreadsheet_id, range_name):
    if not spreadsheet_id:
        return pd.DataFrame()
    rows = _client.get_sheet_data(spreadsheet_id, range_name)
    if not rows or len(rows) < 1:
        return pd.DataFrame()
    if len(rows) == 1:
        return pd.DataFrame(columns=rows[0])
    return pd.DataFrame(rows[1:], columns=rows[0])

# --- 사이드바: 시스템 상태 ---
st.sidebar.title("⚙️ 시스템 상태")

# 1. HUB 시트 ID 확인
hub_id = os.getenv("HUB_SPREADSHEET_ID")
if hub_id and not hub_id.startswith("#") and hub_id.strip() != "":
    st.sidebar.success(f"✅ 시스템 연결됨")
else:
    st.sidebar.error("❌ 시스템 연결 설정 미흡")

# 2. Google OAuth 인증 상태
try:
    creds = get_google_credentials()
    if creds:
        st.sidebar.success("✅ 인증 완료")
    else:
        st.sidebar.error("❌ 인증 필요")
except Exception:
    st.sidebar.error("❌ 인증 오류")

# 3. 시간 정보
seoul_tz = pytz.timezone('Asia/Seoul')
now = datetime.now(seoul_tz)
st.sidebar.info(f"🕒 {now.strftime('%Y-%m-%d %H:%M:%S')}")

# 4. 관리자 옵션
is_admin_mode = os.getenv("ADMIN_MODE", "false").lower() == "true"
if is_admin_mode:
    st.sidebar.markdown("---")
    show_admin = st.sidebar.checkbox("🔒 관리자 옵션", value=False)
else:
    show_admin = False

# --- 메인 화면 ---
st.title("📊 SALMAN OS - 네이버 광고 보고서 자동 수집")
st.markdown("---")

# 상단 메인 실행 버튼 (직원용, 현재 비활성화)
if st.button("🚀 오늘 보고서 수집 시작", disabled=True):
    pass
st.caption("현재는 테스트 단계입니다. 네이버 보고서 다운로드 엔진 연결 후 전체 실행이 활성화됩니다.")

# 개발자 테스트 도구 (관리자 모드에서만 표시)
if show_admin:
    with st.expander("🛠️ 관리자 전용 테스트 도구", expanded=True):
        dev_col1, dev_col2 = st.columns([1, 4])
        with dev_col1:
            if st.button("🔄 화면 데이터 새로고침"):
                st.cache_data.clear()
                st.rerun()
        with dev_col2:
            # Dry-run 실행 버튼
            if st.button("🚀 페이퍼백 데일리_살만 테스트 실행 (Dry-run)"):
                with st.spinner("테스트 실행 중..."):
                    try:
                        cmd = [
                            sys.executable, "-m", "src.report_writer",
                            "--account-name", "페이퍼백",
                            "--report-name", "데일리_살만",
                            "--dry-run"
                        ]
                        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
                        st.markdown("### 🖥️ 실행 로그 (Output)")
                        if result.stdout:
                            st.code(result.stdout)
                        if result.stderr:
                            st.warning("Standard Error:")
                            st.code(result.stderr)
                        if result.returncode == 0:
                            st.success("테스트 실행이 완료되었습니다.")
                        else:
                            st.error(f"오류 발생 (Code: {result.returncode})")
                    except Exception as e:
                        st.error(f"실행 실패: {str(e)}")
            
            # 실제 저장 전 확인 체크박스
            confirm = st.checkbox("실제 구글시트에 저장하고 기록되는 것을 확인했습니다.", key="confirm_write")
            # 실제 저장 실행 버튼
            if st.button("💾 페이퍼백 데일리_살만 실제 저장 실행"):
                if not confirm:
                    st.warning("⚠️ 실행을 위해 위 체크박스를 확인해 주세요.")
                else:
                    with st.spinner("데이터 저장 중..."):
                        try:
                            cmd = [
                                sys.executable, "-m", "src.report_writer",
                                "--account-name", "페이퍼백",
                                "--report-name", "데일리_살만",
                                "--write"
                            ]
                            result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
                            st.markdown("### 🖥️ 실행 로그 (Output)")
                            if result.stdout:
                                st.code(result.stdout)
                            if result.stderr:
                                st.warning("Standard Error:")
                                st.code(result.stderr)
                            if result.returncode == 0:
                                st.success("데이터 저장이 완료되었습니다.")
                            else:
                                st.error("저장 중 오류가 발생했습니다.")
                        except Exception as e:
                            st.error(f"예외 발생: {str(e)}")

client = get_client()

if isinstance(client, str):
    st.error(f"❌ 클라이언트 초기화 실패: {client}")
    st.info("인증 설정을 확인하세요.")
elif not hub_id:
    st.warning("⚠️ 시스템 연결 설정이 필요합니다.")
else:
    with st.spinner("데이터를 실시간으로 불러오는 중..."):
        try:
            # 1. 데이터 로드
            accounts_df = fetch_as_df(client, hub_id, "CONFIG_ACCOUNTS!A:Q")
            reports_df = fetch_as_df(client, hub_id, "CONFIG_REPORTS!A:H")
            download_log_df = fetch_as_df(client, hub_id, "DOWNLOAD_LOG!A:M")
            error_log_df = fetch_as_df(client, hub_id, "ERROR_LOG!A:J")
            
            # 2. 요약 대시보드
            st.subheader("📋 운영 대상 요약")
            col1, col2, col3, col4 = st.columns(4)
            
            if not accounts_df.empty:
                # 조치 필요 건수 미리 계산
                pending_count = 0
                if not error_log_df.empty and "조치필요여부" in error_log_df.columns:
                    pending_mask = error_log_df["조치필요여부"].astype(str).str.upper().isin(["TRUE", "YES", "1"])
                    pending_count = pending_mask.sum()
                
                if pending_count > 0:
                    st.warning(f"⚠️ 조치 필요 {pending_count}건")

                # 필수값 누락 체크
                req_fields = ["고객사명", "네이버광고계정ID", "저장구글시트ID"]
                actual_req_fields = [f for f in req_fields if f in accounts_df.columns]
                invalid_mask = accounts_df[actual_req_fields].apply(lambda x: x.astype(str).str.strip().eq("")).any(axis=1)
                invalid_count = invalid_mask.sum()
                
                with col1:
                    st.metric("전체 고객사", len(accounts_df))
                with col2:
                    active_mask = accounts_df["실행여부"].astype(str).str.upper().isin(["TRUE", "YES", "1"])
                    st.metric("실행 대상 고객사", active_mask.sum())
                with col3:
                    running_mask = accounts_df["운영상태"].astype(str) == "운영중"
                    st.metric("운영중 고객사", running_mask.sum())
                with col4:
                    st.metric("설정 누락", invalid_count, delta_color="inverse")
            else:
                st.warning("고객사 정보가 없습니다.")

            # 3. 보고서 목록
            st.markdown("---")
            st.subheader("📄 수집 대상 보고서")
            if not reports_df.empty:
                # 직원용 컬럼명 변경
                disp_reports = reports_df.copy()
                rename_map = {
                    "보고서구분": "보고서 종류",
                    "수집기준": "수집 기준",
                    "실행주기": "실행 주기",
                    "설명": "설명"
                }
                # 존재하는 컬럼만 변경
                actual_rename = {k: v for k, v in rename_map.items() if k in disp_reports.columns}
                disp_reports = disp_reports.rename(columns=actual_rename)
                
                # 표시할 컬럼만 선택 (순서 보장)
                cols_to_show = ["보고서 종류", "보고서명", "수집 기준", "실행 주기", "설명"]
                existing_cols = [c for c in cols_to_show if c in disp_reports.columns]
                st.dataframe(disp_reports[existing_cols], width="stretch", hide_index=True)
            else:
                st.info("설정된 보고서가 없습니다.")

            # 4. 결과 섹션
            st.markdown("---")
            tab_log, tab_err = st.tabs(["🚀 최근 수집 결과 (20건)", "⚠️ 조치가 필요한 항목 (20건)"])
            
            with tab_log:
                if not download_log_df.empty:
                    recent_dl = download_log_df.tail(20).iloc[::-1].copy()
                    # 직원용 컬럼명 변경
                    rename_dl = {
                        "실행일시": "실행일시",
                        "고객사명": "고객사명",
                        "보고서명": "보고서명",
                        "행수": "저장행수",
                        "결과": "결과",
                        "오류내용": "오류내용"
                    }
                    actual_rename_dl = {k: v for k, v in rename_dl.items() if k in recent_dl.columns}
                    recent_dl = recent_dl.rename(columns=actual_rename_dl)
                    
                    show_dl_cols = ["실행일시", "고객사명", "보고서명", "저장행수", "결과", "오류내용"]
                    existing_dl_cols = [c for c in show_dl_cols if c in recent_dl.columns]
                    st.dataframe(recent_dl[existing_dl_cols], width="stretch", hide_index=True)
                else:
                    st.info("최근 수집 기록이 없습니다.")
                    
            with tab_err:
                if not error_log_df.empty:
                    recent_err = error_log_df.tail(20).iloc[::-1].copy()
                    # 직원용 컬럼명 변경
                    rename_err = {
                        "실행일시": "실행일시",
                        "고객사명": "고객사명",
                        "보고서구분": "보고서구분",
                        "오류유형": "오류유형",
                        "오류내용": "오류내용",
                        "조치필요여부": "조치필요여부"
                    }
                    actual_rename_err = {k: v for k, v in rename_err.items() if k in recent_err.columns}
                    recent_err = recent_err.rename(columns=actual_rename_err)
                    
                    show_err_cols = ["실행일시", "고객사명", "보고서구분", "오류유형", "오류내용", "조치필요여부"]
                    existing_err_cols = [c for c in show_err_cols if c in recent_err.columns]
                    st.dataframe(recent_err[existing_err_cols], width="stretch", hide_index=True)
                else:
                    st.info("최근 발생한 오류가 없습니다.")

        except Exception as e:
            st.error(f"❌ 데이터를 불러오는 중 오류가 발생했습니다: {str(e)}")

st.markdown("---")
st.caption("SALMAN OS - Naver Ads Report Automation Dashboard v1.1")

