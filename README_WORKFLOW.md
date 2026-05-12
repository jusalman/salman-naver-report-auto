# 운영 절차 및 워크플로우

## 인증 절차 (초기 1회)

이 프로젝트는 Google Sheets와 상호작용하기 위해 Google OAuth Desktop 인증 방식을 사용합니다. 

### 첫 실행 시 인증 방법

1. 터미널을 열고 프로젝트 루트 디렉토리로 이동합니다.
2. 파이썬 가상환경을 활성화합니다. (설정한 경우)
3. 아래 명령어를 실행하여 인증 테스트 모듈을 구동합니다:
   ```bash
   python -m src.google_auth
   ```
4. 브라우저 창이 자동으로 열리며 Google 로그인 화면이 나타납니다.
5. 구글 시트 접근(읽기/쓰기) 권한이 있는 계정으로 로그인합니다.
6. "Google에서 확인하지 않은 앱"이라는 경고 창이 나타나면 좌측 하단의 `고급`을 클릭한 뒤 `(안전하지 않음)으로 이동`을 선택하여 계속 진행합니다.
7. 필요한 권한(Sheets, Drive) 요청 창이 뜨면 모두 **허용(Allow)** 합니다.
8. 브라우저에 "The authentication flow has completed." 메시지가 표시되면 창을 닫아도 됩니다.
9. 터미널에서 `✅ Authentication Successful!` 메시지를 확인합니다.
10. 프로젝트 폴더 내에 `token/token.json` 파일이 정상적으로 생성되었는지 확인합니다.

이후 자동화 스크립트 실행 시에는 생성된 `token.json` 파일을 사용하여 사용자 개입 없이 자동으로 인증을 처리합니다.

## 허브 시트 연결 테스트 (Phase 2)

인증이 완료된 후, 설정한 허브 구글 시트에서 4개의 필수 탭(`CONFIG_ACCOUNTS`, `CONFIG_REPORTS`, `DOWNLOAD_LOG`, `ERROR_LOG`)을 정상적으로 읽어오는지 테스트할 수 있습니다.

### 테스트 실행 방법

1. `.env` 파일에 `HUB_SPREADSHEET_ID` 값이 올바르게 입력되었는지 확인합니다.
2. 터미널에서 다음 명령어를 실행합니다:
   ```bash
   python -m src.config_loader
   ```
3. 각 탭의 데이터 행 수(Row Count)와 컬럼 목록(Column List)이 정상적으로 출력되는지 확인합니다.
4. 만약 PRD와 다르게 누락된 컬럼이 있다면 `WARNING: [탭이름] Missing expected columns: [...]` 형식의 경고 메시지가 출력됩니다. 이를 참고하여 시트의 컬럼명을 수정해 주세요.

## 💡 팁: Windows 터미널 한글 깨짐 해결
Windows PowerShell 또는 CMD에서 실행 결과의 한글이 깨져 보인다면, 명령어를 실행하기 전에 터미널에 아래 명령어를 입력하여 인코딩을 UTF-8로 변경해 주세요:
```powershell
chcp 65001
```
