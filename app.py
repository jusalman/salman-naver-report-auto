import streamlit as st
import os
import pandas as pd
from datetime import datetime
import pytz
from dotenv import load_dotenv
import subprocess
import sys

STAFF_SHEET_RANGES = {
    "accounts": "CONFIG_ACCOUNTS!A:Q",
    "reports": "CONFIG_REPORTS!A:Z",
    "downloads": "DOWNLOAD_LOG!A:Z",
    "errors": "ERROR_LOG!A:Z",
}

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
    .hero-container {
        padding: 20px;
        background-color: white;
        border-radius: 15px;
        border: 1px solid #e0e0e0;
        margin-bottom: 25px;
    }
    /* 메인 실행 버튼 스타일링 (CTA 강조) */
    div.stButton > button:first-child {
        background-color: #2563EB !important;
        color: white !important;
        border: none !important;
        padding: 0.6rem 1.2rem !important;
        border-radius: 10px !important;
        font-weight: 700 !important;
        font-size: 1.1rem !important;
        width: 100% !important;
        transition: all 0.3s ease !important;
        box-shadow: 0 4px 6px -1px rgba(37, 99, 235, 0.2), 0 2px 4px -1px rgba(37, 99, 235, 0.1) !important;
    }
    div.stButton > button:first-child:hover {
        background-color: #1D4ED8 !important;
        color: white !important;
        box-shadow: 0 10px 15px -3px rgba(37, 99, 235, 0.3), 0 4px 6px -2px rgba(37, 99, 235, 0.05) !important;
        transform: translateY(-1px) !important;
    }
    div.stButton > button:first-child:active {
        background-color: #1E3A8A !important;
        transform: translateY(0px) !important;
    }
    /* 비활성화 상태 (실행 중) */
    div.stButton > button:disabled {
        background-color: #CBD5E1 !important;
        color: #64748B !important;
        cursor: not-allowed !important;
        transform: none !important;
        box-shadow: none !important;
    }
    </style>
    """, unsafe_allow_html=True)

@st.cache_resource
def get_client():
    from src.google_sheet_client import GoogleSheetClient
    try:
        return GoogleSheetClient()
    except Exception as e:
        return str(e)

@st.cache_data(ttl=30)
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

def map_error_to_friendly_msg(error_str):
    """내부 오류 코드를 직원용 친화 문구로 변환합니다."""
    if not error_str or str(error_str).strip() == "":
        return ""

    mapping = {
        "REPORT_NOT_FOUND": "네이버 광고센터에 저장된 보고서명을 찾을 수 없습니다.",
        "NAVER_LOGIN_REQUIRED": "네이버 로그인이 필요합니다.",
        "NAVER_ACCOUNT_ACCESS_ERROR": "광고계정 접근 권한을 확인해야 합니다.",
        "DOWNLOAD_BUTTON_NOT_FOUND": "다운로드 버튼을 찾지 못했습니다.",
        "DOWNLOAD_TIMEOUT": "다운로드 시간이 초과되었습니다."
    }

    for code, msg in mapping.items():
        if code in str(error_str):
            return msg

    return "관리자 확인이 필요합니다."

# 세션 상태 초기화 (중복 클릭 방지)
if "is_running" not in st.session_state:
    st.session_state.is_running = False

# --- 사이드바: 시스템 상태 ---
st.sidebar.title("⚙️ 시스템 상태")

hub_id = os.getenv("HUB_SPREADSHEET_ID")
if hub_id and not hub_id.startswith("#") and hub_id.strip() != "":
    st.sidebar.success(f"✅ 시스템 연결됨")
else:
    st.sidebar.error("❌ 시스템 연결 설정 미흡")

try:
    from src.google_auth import get_google_credentials
    creds = get_google_credentials()
    if creds:
        st.sidebar.success("✅ 인증 완료")
    else:
        st.sidebar.error("❌ 인증 필요")
except Exception:
    st.sidebar.error("❌ 인증 오류")

seoul_tz = pytz.timezone('Asia/Seoul')
now = datetime.now(seoul_tz)
st.sidebar.info(f"🕒 {now.strftime('%Y-%m-%d %H:%M:%S')}")

# 내부 로컬 운영 권장값: .env에 ADMIN_MODE=true
is_admin_mode = os.getenv("ADMIN_MODE", "false").lower() == "true"
if is_admin_mode:
    st.sidebar.markdown("---")
    show_admin = st.sidebar.checkbox("🔐 로그인/시스템 관리", value=False)
else:
    show_admin = False

# --- 데이터 로드 ---
client = get_client()
accounts_df = pd.DataFrame()
reports_df = pd.DataFrame()
download_log_df = pd.DataFrame()
error_log_df = pd.DataFrame()
if not isinstance(client, str) and hub_id:
    accounts_df = fetch_as_df(client, hub_id, STAFF_SHEET_RANGES["accounts"])
    reports_df = fetch_as_df(client, hub_id, STAFF_SHEET_RANGES["reports"])
    download_log_df = fetch_as_df(client, hub_id, STAFF_SHEET_RANGES["downloads"])
    error_log_df = fetch_as_df(client, hub_id, STAFF_SHEET_RANGES["errors"])

# --- 메인 화면 ---
st.title("📊 SALMAN OS - 네이버 광고 보고서 자동 수집")

# Hero 영역
with st.container():
    st.markdown("""
        <div class="hero-container">
            <h3 style='margin-top:0;'>🗓️ 오늘 보고서 수집 상태</h3>
            <p style='color: #666; margin-bottom: 0;'>버튼을 누르면 실행 대상 고객사의 보고서를 자동으로 수집하여 구글 시트에 업데이트합니다.</p>
        </div>
        """, unsafe_allow_html=True)

# 2. 실행 버튼 영역
col_btn, _ = st.columns([1, 2])
with col_btn:
    btn_label = "🚀 오늘 보고서 수집 시작"
    if st.session_state.is_running:
        st.button(btn_label, disabled=True, key="btn_disabled", use_container_width=True)
    else:
        # type="primary"를 제거하여 파란색/중립톤으로 유지 (테마에 따라 다름)
        if st.button(btn_label, use_container_width=True):
            st.session_state.is_running = True
            st.rerun()

    # 버튼 하단 간단 요약
    if not accounts_df.empty:
        success_today = accounts_df["마지막실행결과"].astype(str).eq("성공").sum()
        fail_count = accounts_df["마지막실행결과"].astype(str).isin(["실패", "일부실패"]).sum()
        st.caption(f"최근 실행 결과: {success_today}개 완료 · {fail_count}개 확인 필요")

# 실행 로직
if st.session_state.is_running:
    with st.status("보고서를 수집 중입니다. 창을 닫지 마세요.", expanded=True) as status:
        stdout_text, stderr_text = "", ""
        try:
            cmd = [sys.executable, "-m", "src.run_engine", "--all-accounts", "--write"]
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=False)

            if show_admin: st.write("시스템 로그 수집 중...")

            stdout_bytes, stderr_bytes = process.communicate()
            stdout_text = decode_output(stdout_bytes)
            stderr_text = decode_output(stderr_bytes)

            if show_admin:
                if stdout_text: st.code(stdout_text)
                if stderr_text: st.warning(stderr_text)

            # 결과 처리 및 세션 저장 (rerun 후 표시용)
            if process.returncode == 0:
                st.session_state.exec_result = {"type": "success", "msg": "✅ 오늘 보고서 수집이 완료되었습니다."}
                status.update(label="✅ 수집 완료", state="complete", expanded=False)
            elif process.returncode == 1:
                if "성공: 0개" in stdout_text and "실패:" in stdout_text:
                    st.session_state.exec_result = {"type": "error", "msg": "❌ 보고서 수집에 실패했습니다. 관리자에게 문의해 주세요."}
                else:
                    st.session_state.exec_result = {"type": "warning", "msg": "⚠️ 일부 고객사에서 조치가 필요합니다. 아래 내용을 확인해 주세요."}
                status.update(label="⚠️ 수집 결과 확인 필요", state="error", expanded=True)
            else:
                st.session_state.exec_result = {"type": "error", "msg": "❌ 시스템 오류가 발생했습니다. 관리자에게 문의해 주세요."}
                status.update(label="❌ 시스템 오류", state="error", expanded=True)

        except Exception as e:
            st.session_state.exec_result = {"type": "error", "msg": f"❌ 실행 중 문제가 발생했습니다: {str(e)}"}
            status.update(label="❌ 예외 발생", state="error")

        # 상태 종료 및 화면 갱신
        st.session_state.is_running = False
        st.cache_data.clear() # 결과 반영을 위해 캐시 삭제
        st.rerun()

# 최근 실행 결과 알림 (실행 직후에만 표시)
if "exec_result" in st.session_state:
    res = st.session_state.exec_result
    if res["type"] == "success": st.success(res["msg"])
    elif res["type"] == "warning": st.warning(res["msg"])
    else: st.error(res["msg"])
    # 세션에서 제거하여 다음 새로고침 시 사라지게 함
    del st.session_state.exec_result

st.markdown("---")

# 3. 운영 상태 요약 카드
if not accounts_df.empty:
    st.subheader("📋 수집 현황 요약")
    m_col1, m_col2, m_col3, m_col4 = st.columns(4)

    fail_mask = accounts_df["마지막실행결과"].astype(str).isin(["실패", "일부실패"])
    fail_df = accounts_df[fail_mask].copy()
    fail_count = len(fail_df)

    with m_col1:
        st.metric("전체 고객사", len(accounts_df))
    with m_col2:
        active_count = accounts_df["실행여부"].astype(str).str.upper().isin(["TRUE", "YES", "1"]).sum()
        st.metric("수집 대상", active_count)
    with m_col3:
        success_today = accounts_df["마지막실행결과"].astype(str).eq("성공").sum()
        st.metric("정상 완료", success_today)
    with m_col4:
        st.metric("조치 필요", fail_count, delta=fail_count if fail_count > 0 else None, delta_color="inverse")

    st.markdown("<br>", unsafe_allow_html=True)

    # 4. 확인이 필요한 고객사 (또는 완료 메시지)
    if not fail_df.empty:
        st.subheader("⚠️ 확인이 필요한 고객사가 있습니다")
        st.info("아래 고객사의 네이버 보고서 설정을 확인해 주세요.")

        # 조치용 DF 가공
        action_df = fail_df.copy()
        action_df["확인할 내용"] = action_df["오류내용"].apply(map_error_to_friendly_msg)
        st.dataframe(
            action_df[["고객사명", "마지막실행결과", "확인할 내용"]].rename(columns={"마지막실행결과": "상태"}),
            use_container_width=True, hide_index=True
        )
    else:
        st.success("✅ 현재 조치가 필요한 고객사가 없습니다.")

    # 5. 최근 실행 내역
    st.markdown("---")
    st.subheader("📋 최근 실행 내역")

    display_df = accounts_df.copy()
    display_df = display_df[
        (display_df["실행여부"].astype(str).str.upper().isin(["TRUE", "YES", "1"])) |
        (display_df["마지막실행일시"].astype(str).str.strip() != "")
    ].copy()

    display_df["메시지/요구사항"] = display_df["오류내용"].apply(lambda x: map_error_to_friendly_msg(x) if str(x).strip() else "정상 처리됨")

    st.dataframe(
        display_df[["고객사명", "마지막실행일시", "마지막실행결과", "메시지/요구사항"]].rename(columns={
            "마지막실행일시": "마지막 실행 시간",
            "마지막실행결과": "상태"
        }).sort_values(by="마지막 실행 시간", ascending=False),
        use_container_width=True, hide_index=True
    )

# 관리자 도구
if show_admin:
    st.info("네이버 비밀번호가 변경되었거나 로그인이 풀린 경우, 아래 버튼으로 네이버 광고센터를 다시 연결하세요.")
    if st.button("🔐 네이버 로그인 다시 연결"):
        project_root = os.path.dirname(os.path.abspath(__file__))
        bat_path = os.path.join(project_root, "네이버_로그인_다시연결.bat")
        if os.path.exists(bat_path):
            subprocess.Popen(["cmd", "/k", bat_path], cwd=project_root)
            st.info("로그인 재연결 창을 열었습니다. 열린 브라우저에서 네이버 광고센터에 로그인한 뒤, 터미널에서 Enter를 눌러 완료하세요.")
        else:
            st.error("네이버_로그인_다시연결.bat 파일을 찾을 수 없습니다.")

    with st.expander("🛠️ 관리자 전용 데이터 도구", expanded=False):
        if st.button("🔄 시트 데이터 강제 새로고침"):
            st.cache_data.clear()
            st.rerun()
        st.write(f"HUB_ID: {hub_id}")
        st.write(f"Python: {sys.executable}")
        st.write("운영 탭: CONFIG_ACCOUNTS, CONFIG_REPORTS, DOWNLOAD_LOG, ERROR_LOG")
        if not accounts_df.empty:
            st.write("전체 데이터 미리보기 (Raw)")
            st.dataframe(accounts_df)
        if not reports_df.empty:
            st.write("CONFIG_REPORTS")
            st.dataframe(reports_df)
        if not download_log_df.empty:
            st.write("DOWNLOAD_LOG")
            st.dataframe(download_log_df)
        if not error_log_df.empty:
            st.write("ERROR_LOG")
            st.dataframe(error_log_df)

st.markdown("---")
st.caption("SALMAN OS - Naver Ads Report Automation Dashboard v1.4")
