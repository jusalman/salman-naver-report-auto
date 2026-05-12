import streamlit as st
import os
import pandas as pd
from datetime import datetime
import pytz
from dotenv import load_dotenv
import subprocess
import sys

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
    .status-card {
        padding: 20px;
        border-radius: 10px;
        margin-bottom: 15px;
    }
    </style>
    """, unsafe_allow_html=True)

@st.cache_resource
def get_client():
    try:
        return GoogleSheetClient()
    except Exception as e:
        return str(e)

@st.cache_data(ttl=30) # 캐시를 조금 더 짧게 (30초)
def fetch_as_df(_client, spreadsheet_id, range_name):
    if not spreadsheet_id:
        return pd.DataFrame()
    rows = _client.get_sheet_data(spreadsheet_id, range_name)
    if not rows or len(rows) < 1:
        return pd.DataFrame()
    if len(rows) == 1:
        return pd.DataFrame(columns=rows[0])
    return pd.DataFrame(rows[1:], columns=rows[0])

def decode_output(bytes_data):
    """Windows 환경의 다양한 인코딩(UTF-8, CP949)을 안전하게 처리합니다."""
    if not bytes_data:
        return ""
    try:
        return bytes_data.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return bytes_data.decode("cp949")
        except UnicodeDecodeError:
            return bytes_data.decode("utf-8", errors="replace")

# 세션 상태 초기화 (중복 클릭 방지)
if "is_running" not in st.session_state:
    st.session_state.is_running = False

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
    from src.google_auth import get_google_credentials
    from src.google_sheet_client import GoogleSheetClient
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
    show_admin = st.sidebar.checkbox("🔒 관리자 전용 옵션", value=False)
else:
    show_admin = False

# --- 데이터 로드 ---
client = get_client()
accounts_df = pd.DataFrame()
if not isinstance(client, str) and hub_id:
    accounts_df = fetch_as_df(client, hub_id, "CONFIG_ACCOUNTS!A:Q")

# --- 메인 화면 ---
st.title("📊 SALMAN OS - 네이버 광고 보고서 자동 수집")
st.markdown("---")

# 실행 영역
col_btn, col_info = st.columns([1, 2])

with col_btn:
    # 실행 버튼
    btn_label = "🚀 오늘 보고서 수집 시작"
    if st.session_state.is_running:
        st.button(btn_label, disabled=True, key="btn_disabled")
    else:
        if st.button(btn_label, use_container_width=True, type="primary"):
            st.session_state.is_running = True
            st.rerun()

# 실행 로직
if st.session_state.is_running:
    with st.status("보고서 수집 중입니다. 창을 닫지 마세요.", expanded=True) as status:
        stdout_text = ""
        stderr_text = ""
        try:
            # 1. run_engine 실행 (sys.executable 사용)
            cmd = [sys.executable, "-m", "src.run_engine", "--all-accounts", "--write"]
            
            # 인코딩 오류 방지를 위해 text=False(bytes)로 실행
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=False)
            
            if show_admin:
                st.write("시스템 로그 수집 중...")
            
            stdout_bytes, stderr_bytes = process.communicate()
            
            # 안전하게 디코딩
            stdout_text = decode_output(stdout_bytes)
            stderr_text = decode_output(stderr_bytes)
            
            if show_admin:
                if stdout_text: st.code(stdout_text)
                if stderr_text: st.warning(stderr_text)

            # 결과 처리
            if process.returncode == 0:
                st.success("오늘 보고서 수집이 완료되었습니다.")
                status.update(label="✅ 수집 완료", state="complete", expanded=False)
            elif process.returncode == 1:
                # 일부 실패 또는 전체 실패 판단
                if "성공: 0개" in stdout_text and "실패:" in stdout_text:
                    st.error("보고서 수집에 실패했습니다. 오류 내용을 확인하세요.")
                else:
                    st.warning("일부 고객사에서 조치가 필요합니다. 아래 결과를 확인하세요.")
                status.update(label="⚠️ 일부 실패 발생", state="error", expanded=True)
            else:
                st.error(f"시스템 오류 발생 (Code: {process.returncode})")
                status.update(label="❌ 시스템 오류", state="error", expanded=True)
                
        except Exception as e:
            # 직원 화면에는 간략하게, 관리자에게는 원인 노출
            if is_admin_mode:
                st.error(f"실행 중 예외 발생: {str(e)}")
            else:
                st.error("실행 중 문제가 발생했습니다. 관리자에게 문의하세요.")
            status.update(label="❌ 실행 중단", state="error")
        
        st.session_state.is_running = False
        st.cache_data.clear() # 결과 반영을 위해 캐시 삭제
        if st.button("결과 확인 및 화면 새로고침"):
            st.rerun()

# 요약 대시보드 및 결과 테이블
if not accounts_df.empty:
    # 1. 상단 알림 (조치 필요 건수)
    fail_mask = accounts_df["마지막실행결과"].astype(str).isin(["실패", "일부실패"])
    fail_count = fail_mask.sum()
    
    if fail_count > 0:
        st.warning(f"⚠️ 조치 필요 고객사 {fail_count}건")

    # 2. 메트릭 요약
    st.subheader("📋 운영 상태 요약")
    m_col1, m_col2, m_col3, m_col4 = st.columns(4)
    with m_col1:
        st.metric("전체 고객사", len(accounts_df))
    with m_col2:
        active_count = accounts_df["실행여부"].astype(str).str.upper().isin(["TRUE", "YES", "1"]).sum()
        st.metric("수집 대상", active_count)
    with m_col3:
        success_today = accounts_df["마지막실행결과"].astype(str).eq("성공").sum()
        st.metric("정상 수집 완료", success_today)
    with m_col4:
        st.metric("조치 필요", fail_count, delta=fail_count, delta_color="inverse" if fail_count > 0 else "normal")

    # 3. 상세 결과 리스트
    st.markdown("---")
    st.subheader("📝 최근 실행 상세 내역")
    
    # 표시용 데이터프레임 가공
    display_df = accounts_df.copy()
    
    # 필터링: 실행 대상이거나 최근 실행 기록이 있는 경우
    display_df = display_df[
        (display_df["실행여부"].astype(str).str.upper().isin(["TRUE", "YES", "1"])) |
        (display_df["마지막실행일시"].astype(str).str.strip() != "")
    ].copy()
    
    # 컬럼명 변경 (직원용)
    rename_map = {
        "고객사명": "고객사명",
        "마지막실행일시": "마지막 실행 시각",
        "마지막실행결과": "상태",
        "오류내용": "메시지/오류내용"
    }
    display_df = display_df.rename(columns=rename_map)
    
    # 표시할 컬럼 선택
    show_cols = ["고객사명", "마지막 실행 시각", "상태", "메시지/오류내용"]
    
    # 상태에 따른 스타일링을 위해 dataframe 대신 table 또는 styler 사용 시도
    # 여기서는 간단하게 st.dataframe 사용 (컬럼 필터링)
    st.dataframe(
        display_df[show_cols].sort_values(by="마지막 실행 시각", ascending=False),
        use_container_width=True,
        hide_index=True
    )

# 관리자 전용 도구 (사이드바 또는 하단)
if show_admin:
    with st.expander("🛠️ 관리자 전용 데이터 도구", expanded=False):
        if st.button("🔄 시트 데이터 강제 새로고침"):
            st.cache_data.clear()
            st.rerun()
        
        st.markdown("#### 시스템 설정값 (DEBUG)")
        st.write(f"HUB_ID: {hub_id}")
        st.write(f"Python: {sys.executable}")
        
        if not accounts_df.empty:
            st.write("전체 데이터 미리보기 (Raw)")
            st.dataframe(accounts_df)

st.markdown("---")
st.caption("SALMAN OS - Naver Ads Report Automation Dashboard v1.2")


