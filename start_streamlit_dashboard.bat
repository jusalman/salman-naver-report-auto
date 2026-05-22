@echo off
chcp 65001 >nul
cd /d C:\Users\USER\Desktop\자동화\salman-naver-report-auto

echo.
echo ==========================================
echo SALMAN OS 보고서 수집 화면을 시작합니다.
echo ==========================================
echo.

if exist ".venv\Scripts\activate.bat" (
    call ".venv\Scripts\activate.bat"
) else (
    echo 가상환경을 찾지 못했습니다. 현재 환경으로 실행합니다.
)

echo.
echo 직원 PC에서는 아래에 표시되는 Network URL로 접속하세요.
echo 예: http://자동화PC_IP주소:8501
echo.
echo 이 창을 닫으면 직원용 화면도 종료됩니다.
echo.

streamlit run app.py --server.address 0.0.0.0 --server.port 8501

echo.
echo 화면 실행이 종료되었습니다.
pause
