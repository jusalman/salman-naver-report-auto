@echo off
cd /d C:\Users\USER\Desktop\자동화\salman-naver-report-auto

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -m src.naver_report_downloader --login-check
) else (
    python -m src.naver_report_downloader --login-check
)

pause