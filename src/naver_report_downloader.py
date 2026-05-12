import os
import argparse
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

# .env 로드
load_dotenv()

def run_login_check():
    """
    Playwright persistent context를 사용하여 브라우저를 열고,
    사용자가 수동으로 로그인할 수 있도록 대기하는 함수.
    세션은 BROWSER_PROFILE_DIR에 저장되어 다음 실행 시 유지됨.
    """
    profile_dir = os.getenv("BROWSER_PROFILE_DIR", "browser_profile")
    base_url = os.getenv("NAVER_BASE_URL", "https://ads.naver.com")
    
    print(f"[*] 브라우저 프로필 디렉토리: {profile_dir}")
    print(f"[*] 접속 URL: {base_url}")
    
    with sync_playwright() as p:
        # Persistent Context로 브라우저 실행 (headless=False)
        browser = p.chromium.launch_persistent_context(
            user_data_dir=profile_dir,
            headless=False,
            viewport={"width": 1280, "height": 800}
        )
        
        # 기본 페이지 또는 새 페이지 가져오기
        page = browser.pages[0] if browser.pages else browser.new_page()
        
        # 네이버 광고센터로 이동
        print("[*] 네이버 광고센터로 이동합니다...")
        page.goto(base_url)
        
        print("\n" + "="*60)
        print("🌐 네이버 광고센터 창이 열렸습니다.")
        print("⚠️ 만약 로그인이 되어 있지 않다면, 직접 로그인해 주세요.")
        print("✅ 로그인이 완료되면 이 터미널에서 Enter 키를 눌러주세요.")
        print("="*60 + "\n")
        
        # 사용자 입력을 대기 (터미널에서 Enter 입력 시까지 브라우저 유지)
        input("로그인 완료 후 터미널에서 Enter를 누르세요...")
        
        print("\n[*] 세션을 저장하고 브라우저를 닫습니다...")
        browser.close()
        print("[*] 완료되었습니다. 다음 실행 시 세션이 유지됩니다.")

def run_account_page_check(account_id):
    """
    특정 광고계정의 다차원 보고서 페이지로 직접 이동하여
    로그인 유지 여부, 권한 여부, 특정 보고서명 존재 여부를 확인하는 함수.
    """
    profile_dir = os.getenv("BROWSER_PROFILE_DIR", "browser_profile")
    target_url = f"https://ads.naver.com/manage/ad-accounts/{account_id}/sa/reports"
    
    print(f"[*] 브라우저 프로필 디렉토리: {profile_dir}")
    print(f"[*] 대상 보고서 URL: {target_url}")
    
    with sync_playwright() as p:
        browser = p.chromium.launch_persistent_context(
            user_data_dir=profile_dir,
            headless=False,
            viewport={"width": 1280, "height": 800}
        )
        
        page = browser.pages[0] if browser.pages else browser.new_page()
        
        print("[*] 보고서 페이지로 이동합니다...")
        try:
            page.goto(target_url, wait_until="networkidle")
            page.wait_for_timeout(3000) # JS 렌더링 대기
            
            # 1. 로그인 페이지 리다이렉션 체크
            if "nid.naver.com" in page.url or "login" in page.url.lower():
                print("NAVER_LOGIN_REQUIRED")
                return
            
            # 2. 권한 없음 / 잘못된 접근 체크 (ID가 URL에 없거나 에러 페이지인 경우)
            if account_id not in page.url:
                print("NAVER_ACCOUNT_ACCESS_ERROR")
                return
            
            print("[*] 페이지 로딩 성공. 보고서 목록 영역을 확인합니다.")
            
            # 네이버 광고센터는 iframe을 사용할 수도 있으므로 모든 frame의 텍스트를 수집
            all_text_content = page.content()
            for frame in page.frames:
                try:
                    all_text_content += frame.content()
                except Exception:
                    pass
            
            # 3. 텍스트 존재 여부 확인
            reports_to_check = ["데일리_살만", "데일리전환_살만", "위클리키워드_살만"]
            print("\n--- 보고서명 확인 결과 ---")
            for report in reports_to_check:
                if report in all_text_content:
                    print(f"  - {report}: 존재함 ✅")
                else:
                    print(f"  - {report}: 없음 ❌")
            print("---------------------------\n")
            
            print("="*60)
            print("확인이 완료되었습니다. 브라우저를 닫으려면 터미널에서 Enter를 누르세요.")
            print("="*60)
            
            input()
            
        except Exception as e:
            print(f"오류 발생: {str(e)}")
            
        finally:
            print("[*] 브라우저를 닫습니다...")
            browser.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Naver Ads Report Downloader")
    parser.add_argument("--login-check", action="store_true", help="Launch browser to manually login and save session")
    parser.add_argument("--account-page-check", action="store_true", help="Check report page for a specific account")
    parser.add_argument("--account-id", type=str, help="Account ID for --account-page-check")
    
    args = parser.parse_args()
    
    if args.login_check:
        run_login_check()
    elif args.account_page_check:
        if not args.account_id:
            print("오류: --account-page-check 옵션은 --account-id 와 함께 사용해야 합니다.")
            print("예시: python -m src.naver_report_downloader --account-page-check --account-id 1855171")
        else:
            run_account_page_check(args.account_id)
    else:
        print("현재 단계에서는 다른 기능이 비활성화되어 있습니다.")
        print("옵션을 확인해주세요: --login-check 또는 --account-page-check")
