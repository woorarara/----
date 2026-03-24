# =============================================================================
# [방법 2] Selenium 헤드리스 브라우저 기반 번개장터 크롤러 (백업용)
#
# ▶ 사용 시점:
#   bunjang_api_crawler.py 실행 시 403/차단 오류가 발생할 경우 이 파일을 사용하세요.
#   실제 Chrome 브라우저를 자동화하므로 차단 우회 가능성이 훨씬 높습니다.
#
# ▶ 필요한 라이브러리 설치 명령어:
#   pip install selenium webdriver-manager
#
# ▶ 추가 요구사항:
#   - Chrome 브라우저가 PC에 설치되어 있어야 합니다.
#   - webdriver-manager가 ChromeDriver를 자동으로 설치·관리합니다 (수동 설치 불필요).
#
# ▶ 실행 방법:
#   python bunjang_selenium_crawler.py
#
# ▶ 동작 원리:
#   실제 Chrome 브라우저를 헤드리스(화면 없는) 모드로 실행하여 번개장터를 탐색합니다.
#   브라우저가 렌더링하는 실제 페이지 소스를 읽으므로 JavaScript로 동적 생성되는
#   콘텐츠도 수집 가능합니다.
# =============================================================================

import re
import time
import json
from datetime import datetime, timezone, timedelta

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager

# =============================================================================
# [설정 섹션] - 검색 조건 및 필터링 키워드를 여기서 관리하세요
# =============================================================================

# 검색할 키워드
SEARCH_KEYWORD = "아이폰 15 프로"

# 검색 결과 정렬: "date" = 최신순, "score" = 정확도순
SORT_ORDER = "date"

# 페이지 로딩 최대 대기 시간 (초)
PAGE_LOAD_TIMEOUT = 20

# 스크롤 시 추가 대기 시간 (초) - 너무 빠르면 동적 콘텐츠 로드 실패
SCROLL_PAUSE_TIME = 2

# ▶ 1차 필터링: 아래 키워드 중 하나라도 제목에 포함된 매물은 수집에서 제외
EXCLUDE_KEYWORDS = ["매입", "부품", "부품용", "파손", "찍힘", "교신", "업자", "대납", "가개통"]

# 한국 시간대 (UTC+9) 정의
KST = timezone(timedelta(hours=9))


def build_search_url(keyword: str, sort: str = "date") -> str:
    """
    번개장터 검색 URL을 생성하는 함수.
    URL 인코딩된 한글 키워드를 포함한 검색 페이지 URL을 반환합니다.

    Args:
        keyword: 검색 키워드 (예: "아이폰 15 프로")
        sort:    정렬 방식 ("date" 또는 "score")

    Returns:
        완성된 번개장터 검색 URL 문자열
    """
    from urllib.parse import quote
    encoded_keyword = quote(keyword)
    return f"https://m.bunjang.co.kr/search/products?q={encoded_keyword}&order={sort}"


def setup_chrome_driver() -> webdriver.Chrome:
    """
    헤드리스 Chrome 드라이버를 설정하고 반환하는 함수.
    webdriver-manager를 통해 ChromeDriver를 자동으로 설치·버전 매칭합니다.

    Returns:
        설정이 완료된 Selenium Chrome WebDriver 인스턴스
    """
    # Chrome 브라우저 실행 옵션 설정
    chrome_options = Options()

    # ─── 헤드리스 모드 설정 (화면에 브라우저 창이 뜨지 않음) ─────────────────
    chrome_options.add_argument("--headless=new")       # Chrome 112+ 권장 방식
    chrome_options.add_argument("--no-sandbox")          # 리눅스 환경 호환성
    chrome_options.add_argument("--disable-dev-shm-usage")  # 메모리 공유 문제 방지

    # ─── 자동화 감지 우회 설정 ────────────────────────────────────────────────
    # 일부 사이트는 navigator.webdriver 속성으로 Selenium을 감지하므로 비활성화
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option("useAutomationExtension", False)

    # ─── 성능 최적화 설정 ─────────────────────────────────────────────────────
    chrome_options.add_argument("--disable-gpu")         # GPU 가속 불필요
    chrome_options.add_argument("--disable-extensions")  # 확장 프로그램 비활성화
    chrome_options.add_argument("--disable-images")      # 이미지 로드 비활성화 (속도 향상)
    chrome_options.add_argument("--window-size=1280,720")# 가상 창 크기 설정

    # ─── User-Agent 설정 (실제 Chrome 브라우저처럼 보이도록) ─────────────────
    chrome_options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    )

    # ChromeDriver 자동 설치 및 서비스 시작
    print("🔧 ChromeDriver 초기화 중... (최초 실행 시 다운로드가 진행될 수 있습니다)")
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)

    # navigator.webdriver 속성을 undefined로 변경하여 봇 감지 우회
    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"}
    )

    return driver


def intercept_api_response(driver: webdriver.Chrome, search_url: str) -> list[dict]:
    """
    Selenium으로 번개장터 검색 페이지를 열고, 브라우저가 내부적으로 호출한
    API 응답(Network 요청)을 가로채서 상품 목록을 추출하는 함수.

    이 방법은 페이지 렌더링 중 발생하는 XHR/Fetch 요청의 응답을 직접 읽어
    requests 방식처럼 깔끔한 JSON 데이터를 얻을 수 있습니다.

    Args:
        driver:     Selenium WebDriver 인스턴스
        search_url: 접속할 번개장터 검색 URL

    Returns:
        상품 딕셔너리 리스트 (파싱 결과)
    """
    # Chrome DevTools Protocol을 통해 네트워크 이벤트 수집 활성화
    driver.execute_cdp_cmd("Network.enable", {})

    # 수집된 네트워크 응답을 저장할 딕셔너리 {requestId: responseBody}
    captured_responses = {}

    # 검색 페이지 접속
    print(f"🌐 번개장터 접속 중: {search_url}")
    driver.get(search_url)

    # 페이지 최초 로딩 완료 대기 (상품 카드가 나타날 때까지)
    try:
        WebDriverWait(driver, PAGE_LOAD_TIMEOUT).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "[class*='ProductCard'], [class*='product-card'], [data-pid]"))
        )
        print("✅ 페이지 로딩 완료")
    except TimeoutException:
        print("⚠️  페이지 로딩 타임아웃. DOM 파싱 방식으로 전환합니다.")

    # 추가 로딩 대기 (JavaScript 비동기 렌더링 완료 보장)
    time.sleep(SCROLL_PAUSE_TIME)

    # 스크롤을 내려 추가 상품 로드 유도 (무한 스크롤 페이지 대응)
    print("📜 페이지 스크롤 중 (추가 상품 로드)...")
    last_height = driver.execute_script("return document.body.scrollHeight")
    for _ in range(3):  # 최대 3번 스크롤
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(SCROLL_PAUSE_TIME)
        new_height = driver.execute_script("return document.body.scrollHeight")
        if new_height == last_height:
            break  # 더 이상 새 콘텐츠가 없으면 스크롤 중단
        last_height = new_height

    return []  # 이 함수는 DOM 파싱 함수와 조합하여 사용


def parse_products_from_dom(driver: webdriver.Chrome) -> list[dict]:
    """
    현재 드라이버에 로드된 페이지의 DOM에서 상품 정보를 추출하는 함수.
    번개장터 모바일 웹의 HTML 구조를 분석하여 각 상품 카드에서 데이터를 읽습니다.

    Args:
        driver: 번개장터 검색 결과 페이지가 로드된 Selenium WebDriver

    Returns:
        파싱된 상품 딕셔너리 리스트
    """
    items = []

    # JavaScript를 실행하여 window.__NEXT_DATA__ (Next.js 앱 초기 상태) 추출 시도
    # 번개장터는 Next.js 기반이므로 이 변수에 서버 사이드 렌더링 데이터가 포함됩니다
    try:
        next_data_json = driver.execute_script(
            "return JSON.stringify(window.__NEXT_DATA__);"
        )
        if next_data_json:
            next_data = json.loads(next_data_json)
            # Next.js 데이터 구조 탐색: props > pageProps > initialState > ...
            page_props = (
                next_data.get("props", {})
                .get("pageProps", {})
            )
            # 검색 결과가 여러 경로에 있을 수 있으므로 순서대로 탐색
            search_list = (
                page_props.get("initialSearchData", {}).get("list")
                or page_props.get("dehydratedState", {}).get("queries", [{}])[0]
                       .get("state", {}).get("data", {}).get("list")
            )
            if search_list:
                print(f"✅ Next.js 초기 데이터에서 {len(search_list)}개 상품 발견")
                for raw in search_list:
                    item = _extract_item_from_api_data(raw)
                    if item:
                        items.append(item)
                return items
    except Exception as e:
        print(f"   Next.js 데이터 추출 실패: {e}")

    # ── 폴백: DOM에서 상품 카드 요소를 직접 선택하여 파싱 ────────────────────
    print("   DOM 직접 파싱 방식으로 전환...")

    # 번개장터 상품 카드에 사용되는 CSS 선택자 후보 목록
    # (사이트 업데이트로 클래스명이 변경될 수 있으므로 여러 후보를 시도)
    card_selectors = [
        "[data-pid]",                    # data 속성 기반 (가장 안정적)
        "li[class*='ProductCard']",      # 클래스명 부분 일치
        "div[class*='product_card']",
        "a[href*='/products/']",         # 상품 링크 기반
    ]

    product_cards = []
    for selector in card_selectors:
        try:
            product_cards = driver.find_elements(By.CSS_SELECTOR, selector)
            if product_cards:
                print(f"   선택자 '{selector}'로 {len(product_cards)}개 카드 발견")
                break
        except Exception:
            continue

    if not product_cards:
        print("❌ 상품 카드를 찾을 수 없습니다. 번개장터 HTML 구조가 변경되었을 수 있습니다.")
        # 디버깅용: 현재 페이지 소스 일부 출력
        page_source_preview = driver.page_source[:500]
        print(f"   페이지 소스 미리보기: {page_source_preview}")
        return items

    # 각 상품 카드에서 정보 추출
    for card in product_cards:
        try:
            # 상품 제목 추출 (여러 선택자 시도)
            title = _safe_get_text(card, [
                "[class*='name']", "[class*='title']", "strong", "p"
            ])

            # 상품 링크(URL) 추출
            url = ""
            pid = card.get_attribute("data-pid") or ""
            if pid:
                url = f"https://m.bunjang.co.kr/products/{pid}"
            else:
                # href 속성에서 URL 직접 추출
                href = card.get_attribute("href") or ""
                if "/products/" in href:
                    url = href if href.startswith("http") else f"https://m.bunjang.co.kr{href}"
                    pid_match = re.search(r"/products/(\d+)", href)
                    pid = pid_match.group(1) if pid_match else ""

            # 가격 추출
            price_text = _safe_get_text(card, [
                "[class*='price']", "[class*='Price']", "span[class*='won']"
            ])
            price_int = _parse_price_text(price_text)

            if title or url:
                items.append({
                    "title": title or "제목 없음",
                    "price": price_int,
                    "price_formatted": f"{price_int:,}원" if price_int else "가격 미상",
                    "registered_time": "번개장터 앱에서 확인",  # DOM에서 시간 추출이 어려울 수 있음
                    "url": url or "URL 없음",
                    "pid": pid,
                })
        except Exception as e:
            continue  # 개별 카드 파싱 오류는 무시하고 계속 진행

    return items


def _extract_item_from_api_data(raw: dict) -> dict | None:
    """
    API/Next.js 응답의 개별 상품 raw 데이터에서 필요한 필드를 추출하는 내부 함수.

    Args:
        raw: API 응답의 개별 상품 딕셔너리

    Returns:
        정제된 상품 딕셔너리, 유효하지 않으면 None
    """
    pid = str(raw.get("pid", ""))
    title = raw.get("name", "").strip()

    if not title:
        return None

    price_raw = raw.get("price", 0)
    price_int = int(re.sub(r"[^\d]", "", str(price_raw))) if price_raw else 0

    # 시간 처리
    ts_raw = raw.get("updated_at") or raw.get("updatedAt") or raw.get("created_at", "")
    registered_time = _parse_ts(ts_raw)

    return {
        "title": title,
        "price": price_int,
        "price_formatted": f"{price_int:,}원",
        "registered_time": registered_time,
        "url": f"https://m.bunjang.co.kr/products/{pid}" if pid else "URL 없음",
        "pid": pid,
    }


def _parse_ts(ts_value) -> str:
    """Unix 타임스탬프 또는 날짜 문자열을 KST 문자열로 변환하는 내부 헬퍼 함수."""
    if not ts_value:
        return "알 수 없음"
    try:
        if isinstance(ts_value, (int, float)):
            ts = int(str(int(ts_value))[:10])
            return datetime.fromtimestamp(ts, tz=KST).strftime("%Y-%m-%d %H:%M:%S")
        ts_str = str(ts_value)
        if ts_str.isdigit():
            return datetime.fromtimestamp(int(ts_str[:10]), tz=KST).strftime("%Y-%m-%d %H:%M:%S")
        if "T" in ts_str:
            return datetime.fromisoformat(ts_str.replace("Z", "+00:00")).astimezone(KST).strftime("%Y-%m-%d %H:%M:%S")
        return ts_str
    except Exception:
        return str(ts_value)


def _safe_get_text(element, selectors: list[str]) -> str:
    """
    여러 CSS 선택자를 순서대로 시도하여 첫 번째로 찾은 텍스트를 반환하는 내부 헬퍼 함수.
    사이트 구조 변경에 대한 내성을 높이기 위해 사용합니다.
    """
    for selector in selectors:
        try:
            el = element.find_element(By.CSS_SELECTOR, selector)
            text = el.text.strip()
            if text:
                return text
        except NoSuchElementException:
            continue
    return ""


def _parse_price_text(price_text: str) -> int:
    """가격 텍스트(예: '1,200,000원')에서 숫자만 추출하여 정수로 반환하는 내부 헬퍼 함수."""
    if not price_text:
        return 0
    try:
        cleaned = re.sub(r"[^\d]", "", price_text)
        return int(cleaned) if cleaned else 0
    except (ValueError, TypeError):
        return 0


def apply_filter(items: list[dict]) -> tuple[list[dict], int]:
    """
    수집된 상품 목록에 1차 필터링 키워드를 적용하는 함수.

    Args:
        items: 파싱된 상품 딕셔너리 리스트

    Returns:
        (필터링 통과 리스트, 제외된 상품 수) 튜플
    """
    passed = []
    excluded_count = 0
    for item in items:
        title = item.get("title", "")
        # 제목에 제외 키워드 포함 여부 검사
        if any(kw in title for kw in EXCLUDE_KEYWORDS):
            excluded_count += 1
            continue
        passed.append(item)
    return passed, excluded_count


def print_results(items: list[dict]) -> None:
    """
    수집된 상품 목록을 터미널에 보기 좋게 포맷팅하여 출력하는 함수.

    Args:
        items: 필터링이 완료된 상품 딕셔너리 리스트
    """
    if not items:
        print("표시할 상품이 없습니다.")
        return

    print("=" * 80)
    print(f"  번개장터 검색 결과 (Selenium): '{SEARCH_KEYWORD}'  (총 {len(items)}개)")
    print("=" * 80)

    for idx, item in enumerate(items, start=1):
        print(f"\n  [{idx:02d}] {item['title']}")
        print(f"       💰 가격       : {item['price_formatted']}")
        print(f"       🕒 등록 시간  : {item['registered_time']}")
        print(f"       🔗 링크       : {item['url']}")
        print(f"       {'─' * 60}")

    print("\n" + "=" * 80)
    print(f"  검색 완료. 총 {len(items)}개 매물 수집됨.")
    print("=" * 80 + "\n")


def main():
    """
    메인 실행 함수.
    Chrome 드라이버 초기화 → 페이지 접속 → DOM 파싱 → 필터링 → 출력 순서로 실행합니다.
    """
    print("\n" + "=" * 80)
    print("  번개장터 매물 수집 봇 시작 (Selenium 버전)")
    print(f"  검색어: {SEARCH_KEYWORD}  |  정렬: {SORT_ORDER}")
    print("=" * 80)

    start_time = time.time()
    driver = None

    try:
        # ── STEP 1: Chrome 드라이버 초기화 ────────────────────────────────────
        driver = setup_chrome_driver()

        # ── STEP 2: 검색 URL 생성 및 페이지 접속 + 스크롤 ──────────────────
        search_url = build_search_url(SEARCH_KEYWORD, SORT_ORDER)
        intercept_api_response(driver, search_url)  # 접속 및 스크롤 수행

        # ── STEP 3: DOM에서 상품 정보 파싱 ──────────────────────────────────
        print("⚙️  페이지 DOM 파싱 중...")
        raw_items = parse_products_from_dom(driver)
        print(f"   총 {len(raw_items)}개 상품 수집됨 (필터링 전)")

        # ── STEP 4: 1차 필터링 적용 ──────────────────────────────────────────
        filtered_items, excluded_count = apply_filter(raw_items)
        print(f"\n📊 필터링 결과: 전체 {len(raw_items)}개 중 {excluded_count}개 제외 → 최종 {len(filtered_items)}개 통과\n")

        # ── STEP 5: 결과 출력 ────────────────────────────────────────────────
        print_results(filtered_items)

    except Exception as e:
        print(f"\n❌ 예기치 않은 오류 발생: {e}")
        import traceback
        traceback.print_exc()

    finally:
        # 드라이버 종료 (메모리 누수 방지)
        if driver:
            driver.quit()
            print("🔒 Chrome 드라이버 종료 완료")

    elapsed = time.time() - start_time
    print(f"⏱️  총 실행 시간: {elapsed:.2f}초\n")


# 스크립트 직접 실행 시 main() 함수 호출
if __name__ == "__main__":
    main()
