# SALMAN OS - Naver Ads Report Auto

네이버 광고센터의 다차원 보고서 3종을 자동으로 다운로드하여 고객사별 구글 시트에 저장하는 자동화 도구입니다.

## 🚀 현재 준비 상태 (Phase 0 완료)
- [x] 프로젝트 폴더 구조 생성
- [x] `.env` 및 `requirements.txt` 설정 완료
- [x] `.gitignore` 설정 완료
- [x] `credentials/google_oauth_client.json` 준비 완료 (사용자)

## 🛠️ 설치 및 설정 방법
1. **파이썬 가상환경 생성 및 활성화** (권장):
   ```bash
   python -m venv .venv
   source .venv/Scripts/activate  # Windows: .venv\Scripts\activate
   ```
2. **필수 패키지 설치**:
   ```bash
   pip install -r requirements.txt
   playwright install
   ```
3. **환경 변수 설정**:
   - `.env` 파일의 `HUB_SPREADSHEET_ID`에 실제 관리용 허브 구글 시트 ID를 입력하세요.
4. **구글 자격 증명**:
   - `credentials/google_oauth_client.json` 파일이 있는지 확인하세요.

## 📅 다음 실행 순서 (Phase 1)
1. **Google OAuth 인증**: `src/google_auth.py`를 통해 첫 인증을 진행하고 `token/token.json`을 생성합니다.
2. **허브 시트 연결 확인**: `src/google_sheet_client.py`를 통해 시트 데이터를 정상적으로 읽어오는지 테스트합니다.

## ⚠️ 주의 사항
- `credentials/`, `token/`, `browser_profile/` 등 민감한 정보가 포함된 폴더는 외부에 노출되지 않도록 주의하세요.
- 네이버 로그인은 최초 1회 수동 로그인을 통해 세션을 `browser_profile/`에 저장한 뒤 재사용합니다.
