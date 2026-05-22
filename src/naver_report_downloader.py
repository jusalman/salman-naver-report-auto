import os
import argparse
import re
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

# .env 로드
load_dotenv()

DEFAULT_REPORT_NAMES_TO_CHECK = [
    "데일리SA_RAW",
    "데일리전환SA_RAW",
    "위클리키워드SA_RAW",
]

def get_report_names_to_check():
    """
    CONFIG_REPORTS의 네이버보고서명을 우선 사용하고, 읽을 수 없으면 새 표준 기본값을 사용한다.
    """
    try:
        from src.config_loader import ConfigLoader

        reports_df = ConfigLoader().load_config_reports()
        if "네이버보고서명" not in reports_df.columns:
            return DEFAULT_REPORT_NAMES_TO_CHECK

        report_names = []
        for value in reports_df["네이버보고서명"].tolist():
            report_name = "" if value is None else str(value).strip()
            if report_name and report_name not in report_names:
                report_names.append(report_name)

        return report_names or DEFAULT_REPORT_NAMES_TO_CHECK
    except Exception:
        return DEFAULT_REPORT_NAMES_TO_CHECK

def _page_contexts(page):
    contexts = [page]
    contexts.extend(page.frames)
    return contexts

def _context_text(context):
    try:
        return context.evaluate("() => document.body ? document.body.innerText : ''")
    except Exception:
        try:
            return context.content()
        except Exception:
            return ""

def _all_page_text(page):
    texts = []
    for context in _page_contexts(page):
        text = _context_text(context)
        if text:
            texts.append(text)
    return "\n".join(texts)

def _print_detected_report_candidates(page):
    text = _all_page_text(page)
    candidates = []
    for line in text.splitlines():
        line = line.strip()
        if not line or "RAW" not in line:
            continue
        for candidate in re.findall(r"[^\s,;|/\\(){}\[\]<>]+(?:SA_RAW|_RAW)", line):
            if candidate not in candidates:
                candidates.append(candidate)

    print("[DEBUG] 화면에서 감지한 보고서명 후보:")
    if candidates:
        for candidate in candidates:
            print(f"  - {candidate}")
    else:
        print("  - 감지된 후보 없음")

def _try_first_locator(locator):
    try:
        if locator.count() > 0:
            return locator.first
    except Exception:
        return None
    return None

def _find_report_locator_once(page, report_name):
    for context in _page_contexts(page):
        locator = _try_first_locator(context.get_by_text(report_name, exact=True))
        if locator:
            return locator

    for context in _page_contexts(page):
        locator = _try_first_locator(context.locator(f"text={report_name}"))
        if locator:
            return locator

    for context in _page_contexts(page):
        for selector in ["a", "button", "tr", "[role='row']", "[role='button']", "li", "div"]:
            try:
                locator = _try_first_locator(context.locator(selector).filter(has_text=report_name))
                if locator:
                    return locator
            except Exception:
                continue

    if report_name in _all_page_text(page):
        for context in _page_contexts(page):
            locator = _try_first_locator(context.get_by_text(report_name, exact=False))
            if locator:
                return locator

    return None

def _scroll_report_page(page):
    try:
        page.mouse.wheel(0, 900)
    except Exception:
        pass
    try:
        page.evaluate("() => window.scrollBy(0, Math.floor(window.innerHeight * 0.8))")
    except Exception:
        pass
    for frame in page.frames:
        try:
            frame.evaluate("""
                () => {
                    window.scrollBy(0, Math.floor(window.innerHeight * 0.8));
                    for (const el of document.querySelectorAll('*')) {
                        if (el.scrollHeight > el.clientHeight + 20) {
                            el.scrollTop = Math.min(el.scrollTop + 900, el.scrollHeight);
                        }
                    }
                }
            """)
        except Exception:
            continue

def find_report_locator(page, report_name, attempts=6):
    for attempt in range(attempts):
        locator = _find_report_locator_once(page, report_name)
        if locator:
            return locator

        if report_name in _all_page_text(page):
            break

        _scroll_report_page(page)
        page.wait_for_timeout(1500 if attempt < 2 else 2000)

    return _find_report_locator_once(page, report_name)

def wait_for_report_list(page, report_names=None, attempts=8):
    report_names = report_names or []
    for attempt in range(attempts):
        page_text = _all_page_text(page)
        if any(report_name in page_text for report_name in report_names):
            return True
        if "RAW" in page_text or "보고서" in page_text:
            return True
        _scroll_report_page(page)
        page.wait_for_timeout(1500 if attempt < 3 else 2000)
    return False

def wait_for_login_enter():
    """로그인 완료 후 Enter 입력을 기다린다. stdin이 끊긴 경우 Windows 콘솔 입력으로 대기한다."""
    prompt = "네이버 광고센터에 로그인한 뒤 이 창에서 Enter를 눌러주세요."
    print(prompt)
    try:
        input()
        return
    except EOFError:
        print("표준 입력을 사용할 수 없어 콘솔 키 입력 대기 방식으로 전환합니다.")

    try:
        import msvcrt
        print(prompt)
        while True:
            key = msvcrt.getwch()
            if key in ("\r", "\n"):
                return
    except Exception:
        import time
        print("키 입력을 받을 수 없습니다. 브라우저를 30분 동안 유지합니다.")
        print("로그인이 끝나면 브라우저를 직접 닫거나, 대기 시간이 끝날 때까지 기다려주세요.")
        time.sleep(1800)

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
        
        try:
            # 네이버 광고센터로 이동
            print("[*] 네이버 광고센터로 이동합니다...")
            try:
                page.goto(base_url)
            except Exception as e:
                print(f"[!] 네이버 광고센터 이동 중 오류가 발생했습니다: {e}")
                print("[!] 브라우저 창은 유지됩니다. 열린 창에서 직접 네이버 광고센터에 접속해 주세요.")
            
            print("\n" + "="*60)
            print("🌐 네이버 광고센터 창이 열렸습니다.")
            print("⚠️ 만약 로그인이 되어 있지 않다면, 직접 로그인해 주세요.")
            print("✅ 로그인이 완료되면 이 터미널에서 Enter 키를 눌러주세요.")
            print("="*60 + "\n")
            
            wait_for_login_enter()
            
            print("\n[*] 세션을 저장하고 브라우저를 닫습니다...")
        finally:
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

            # 3. 텍스트 존재 여부 확인
            reports_to_check = get_report_names_to_check()
            wait_for_report_list(page, reports_to_check)
            print("\n--- 보고서명 확인 결과 ---")
            missing_reports = []
            for report in reports_to_check:
                locator = find_report_locator(page, report, attempts=4)
                if locator or report in _all_page_text(page):
                    print(f"  - {report}: 존재함 ✅")
                else:
                    missing_reports.append(report)
                    print(f"  - {report}: 없음 ❌")
            print("---------------------------\n")

            if missing_reports:
                _print_detected_report_candidates(page)
            
            print("="*60)
            print("확인이 완료되었습니다. 브라우저를 닫으려면 터미널에서 Enter를 누르세요.")
            print("="*60)
            
            input()
            
        except Exception as e:
            print(f"오류 발생: {str(e)}")
            
        finally:
            print("[*] 브라우저를 닫습니다...")
            browser.close()

def run_open_report(account_id, report_name):
    """
    특정 광고계정의 보고서 목록에서 지정된 보고서명을 클릭하여
    상세/조회 화면으로 진입하는 함수. 다운로드는 수행하지 않음.
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
            
            if "nid.naver.com" in page.url or "login" in page.url.lower():
                print("NAVER_LOGIN_REQUIRED")
                return
            
            if account_id not in page.url:
                print("NAVER_ACCOUNT_ACCESS_ERROR")
                return
                
            print(f"[*] '{report_name}' 보고서를 찾습니다...")
            wait_for_report_list(page, [report_name])
            target_element = find_report_locator(page, report_name)
                                 
            if not target_element:
                _print_detected_report_candidates(page)
                print(f"❌ '{report_name}' 보고서를 화면에서 찾을 수 없습니다.")
                return
                
            print(f"[*] '{report_name}' 보고서를 클릭합니다...")
            target_element.click()
            
            print("[*] 보고서 진입 대기 중...")
            page.wait_for_timeout(3000) # 로딩 대기
            
            print("\n" + "="*60)
            print("✅ 보고서 클릭 완료. 상세/조회 화면으로 진입했는지 확인해 주세요.")
            print("(다운로드 버튼 클릭 및 파일 저장은 수행하지 않았습니다.)")
            print("브라우저를 닫으려면 터미널에서 Enter를 누르세요.")
            print("="*60 + "\n")
            
            input()
            
        except Exception as e:
            print(f"오류 발생: {str(e)}")
            
        finally:
            print("[*] 브라우저를 닫습니다...")
            browser.close()

def download_report(account_id, report_name, headless=False):
    """
    보고서를 찾아 클릭한 후, 다운로드 버튼을 눌러 실제 파일을 다운로드하는 함수.
    성공 시 (저장된 파일의 절대 경로, None, "") 를 반환합니다.
    실패 시 (None, 오류코드, 오류메시지) 를 반환합니다.
    """
    from datetime import datetime
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    
    profile_dir = os.getenv("BROWSER_PROFILE_DIR", "browser_profile")
    target_url = f"https://ads.naver.com/manage/ad-accounts/{account_id}/sa/reports"
    
    print(f"[*] 브라우저 프로필 디렉토리: {profile_dir}")
    print(f"[*] 대상 보고서 URL: {target_url}")
    
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch_persistent_context(
                user_data_dir=profile_dir,
                headless=headless,
                viewport={"width": 1280, "height": 800},
                accept_downloads=True
            )
            
            page = browser.pages[0] if browser.pages else browser.new_page()
            
            print("[*] 보고서 페이지로 이동합니다...")
            page.goto(target_url, wait_until="networkidle")
            page.wait_for_timeout(3000) # JS 렌더링 대기
            
            if "nid.naver.com" in page.url or "login" in page.url.lower():
                print("NAVER_LOGIN_REQUIRED")
                return None, "NAVER_LOGIN_REQUIRED", "네이버 로그인이 필요합니다."
            
            if account_id not in page.url:
                print("NAVER_ACCOUNT_ACCESS_ERROR")
                return None, "NAVER_ACCOUNT_ACCESS_ERROR", "광고계정 접근 권한이 없습니다."
                
            print(f"[*] '{report_name}' 보고서를 찾습니다...")
            wait_for_report_list(page, [report_name])
            target_element = find_report_locator(page, report_name)
                                 
            if not target_element:
                _print_detected_report_candidates(page)
                print(f"❌ '{report_name}' 보고서를 화면에서 찾을 수 없습니다.")
                return None, "REPORT_NOT_FOUND", f"'{report_name}' 보고서를 찾을 수 없습니다."
                
            print(f"[*] '{report_name}' 보고서를 클릭합니다...")
            target_element.click()
            
            print("[*] 상세 화면 진입 대기 중...")
            page.wait_for_timeout(3000) # 로딩 대기
            
            print("[*] '다운로드' 버튼을 찾습니다...")
            download_btn = None
            
            loc_dl = page.get_by_text("다운로드", exact=True)
            if loc_dl.count() > 0:
                download_btn = loc_dl.first
            else:
                loc_dl = page.get_by_text("다운로드", exact=False)
                if loc_dl.count() > 0:
                    download_btn = loc_dl.first
                    
            if not download_btn:
                for frame in page.frames:
                    floc_dl = frame.get_by_text("다운로드", exact=True)
                    if floc_dl.count() > 0:
                        download_btn = floc_dl.first
                        break
                    else:
                        floc_dl = frame.get_by_text("다운로드", exact=False)
                        if floc_dl.count() > 0:
                            download_btn = floc_dl.first
                            break
                            
            if not download_btn:
                print("❌ '다운로드' 버튼을 찾을 수 없습니다.")
                return None, "DOWNLOAD_BUTTON_NOT_FOUND", "다운로드 버튼을 찾을 수 없습니다."
                
            print("[*] 다운로드 버튼 클릭 및 파일 저장을 대기합니다...")
            
            download_dir = os.path.join(os.getcwd(), "downloads", "runtime")
            os.makedirs(download_dir, exist_ok=True)
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{account_id}_{report_name}_{timestamp}.csv"
            save_path = os.path.abspath(os.path.join(download_dir, filename))
            
            try:
                with page.expect_download(timeout=60000) as download_info:
                    download_btn.click()
                download = download_info.value
                
                print("[*] 파일 다운로드 중...")
                download.save_as(save_path)
                
                print("\n" + "="*60)
                print("✅ 보고서 다운로드 성공!")
                print(f"저장 경로: {save_path}")
                print("="*60 + "\n")
                
                return save_path, None, ""
                
            except PlaywrightTimeoutError:
                print("\n❌ 다운로드 응답 시간 초과\n")
                return None, "DOWNLOAD_TIMEOUT", "다운로드 응답 시간 초과"
            except Exception as e:
                if "Timeout" in str(e):
                    print("\n❌ 다운로드 응답 시간 초과\n")
                    return None, "DOWNLOAD_TIMEOUT", "다운로드 응답 시간 초과"
                print(f"\n❌ 다운로드 실패: {str(e)}\n")
                return None, "NAVER_DOWNLOAD_UNKNOWN_ERROR", f"다운로드 실패: {str(e)}"
            
        except Exception as e:
            print(f"오류 발생: {str(e)}")
            return None, "NAVER_DOWNLOAD_UNKNOWN_ERROR", f"예외 발생: {str(e)}"
            
        finally:
            print("[*] 브라우저를 닫습니다...")
            if 'browser' in locals() and browser:
                browser.close()

def run_download_report(account_id, report_name):
    """
    기존 CLI 호환성을 위한 래퍼 함수
    """
    save_path, _, _ = download_report(account_id, report_name, headless=False)
    return save_path

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Naver Ads Report Downloader")
    parser.add_argument("--login-check", action="store_true", help="Launch browser to manually login and save session")
    parser.add_argument("--account-page-check", action="store_true", help="Check report page for a specific account")
    parser.add_argument("--open-report", action="store_true", help="Open a specific report page")
    parser.add_argument("--download-report", action="store_true", help="Download a specific report")
    parser.add_argument("--account-id", type=str, help="Account ID")
    parser.add_argument("--report-name", type=str, help="Report Name for --open-report / --download-report")
    
    args = parser.parse_args()
    
    if args.login_check:
        run_login_check()
    elif args.account_page_check:
        if not args.account_id:
            print("오류: --account-page-check 옵션은 --account-id 와 함께 사용해야 합니다.")
            print("예시: python -m src.naver_report_downloader --account-page-check --account-id 1855171")
        else:
            run_account_page_check(args.account_id)
    elif args.open_report:
        if not args.account_id or not args.report_name:
            print("오류: --open-report 옵션은 --account-id 와 --report-name 이 모두 필요합니다.")
            print("예시: python -m src.naver_report_downloader --open-report --account-id 1855171 --report-name 데일리SA_RAW")
        else:
            run_open_report(args.account_id, args.report_name)
    elif args.download_report:
        if not args.account_id or not args.report_name:
            print("오류: --download-report 옵션은 --account-id 와 --report-name 이 모두 필요합니다.")
            print("예시: python -m src.naver_report_downloader --download-report --account-id 1855171 --report-name 데일리SA_RAW")
        else:
            run_download_report(args.account_id, args.report_name)
    else:
        print("현재 단계에서는 제한된 기능만 활성화되어 있습니다.")
        print("사용 가능 옵션: --login-check, --account-page-check, --open-report, --download-report")
